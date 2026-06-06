"""Controlled import paths for manual RKE review gates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .phase_minus1 import load_jsonl_with_errors


GOLD_REVIEW_TEMPLATE_PATH = "registry/gold_sets/tushare_research_reports.review_template.jsonl"
GOLD_REVIEW_PACKET_PATH = "registry/gold_sets/tushare_research_reports.review_packet.json"
GOLD_REVIEW_IMPORT_REPORT_PATH = "registry/gold_sets/tushare_research_reports.review_import_report.json"
LICENSE_REVIEW_TEMPLATE_PATH = "registry/compliance/tushare_license_review_template.jsonl"
LICENSE_REVIEW_PACKET_PATH = "registry/compliance/tushare_license_review_packet.json"
LICENSE_REVIEW_IMPORT_REPORT_PATH = "registry/compliance/tushare_license_review_import_report.json"

GOLD_BOOL_FIELDS = (
    "claim_correct",
    "source_span_supports_claim",
    "direction_correct",
    "variable_mapping_correct",
    "unsupported_field_false_grounded",
)
GOLD_IMPORTED_FIELDS = (
    "manual_claim_text",
    *GOLD_BOOL_FIELDS,
    "reviewer",
    "review_date",
    "review_notes",
)
LICENSE_IMPORTED_FIELDS = (
    "approved_for_derived_claim_storage",
    "approved_for_production_runtime",
    "reviewer",
    "review_date",
    "notes",
)
TARGET_ROW_HASH_FIELD = "target_row_hash"
MANUAL_REVIEW_PROVENANCE_FIELDS = (
    "review_context_ref",
    "target_review_path",
    TARGET_ROW_HASH_FIELD,
)
GOLD_IMPORT_TEMPLATE_ONLY_FIELDS = (
    "proposed_claim_text_truncated",
)
MANUAL_REVIEW_IMPORT_FORBIDDEN_FIELDS = frozenset(
    {
        "abstract",
        "source_text",
        "source_span_text",
        "span_text",
        "span_preview",
        "full_text",
    }
)


def manual_review_forbidden_field_paths(value: Any, prefix: str = "") -> tuple[str, ...]:
    """Return forbidden source-text field paths anywhere in a manual payload."""
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = str(key)
            path = f"{prefix}.{key_path}" if prefix else key_path
            if key_path in MANUAL_REVIEW_IMPORT_FORBIDDEN_FIELDS:
                paths.append(path)
            paths.extend(manual_review_forbidden_field_paths(item, path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(manual_review_forbidden_field_paths(item, path))
    return tuple(sorted(paths))


@dataclass(frozen=True)
class ManualReviewImportInvalidRow:
    row_number: int
    row_id: str
    reasons: Sequence[str]


@dataclass(frozen=True)
class ManualReviewImportReport:
    report_id: str
    review_kind: Literal["gold_set", "source_license"]
    input_path: str
    target_path: str
    dry_run: bool
    accepted: bool
    input_rows: int
    applied_rows: int
    rejected_rows: int
    duplicate_ids: Sequence[str]
    missing_target_ids: Sequence[str]
    invalid_rows: Sequence[ManualReviewImportInvalidRow]
    downstream_outputs: Mapping[str, str]
    blockers: Sequence[str]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return {"path": str(path), "rows": len(rows)}


def _split_mapping_rows(rows: Sequence[Any]) -> tuple[list[Mapping[str, Any]], tuple[int, ...]]:
    valid_rows: list[Mapping[str, Any]] = []
    invalid_row_numbers: list[int] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            invalid_row_numbers.append(index)
    return valid_rows, tuple(invalid_row_numbers)


def review_row_fingerprint(row: Mapping[str, Any]) -> str:
    encoded = json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + sha256(encoded).hexdigest()


def _resolve_input_path(root_path: Path, input_path: str | Path) -> Path:
    path = Path(input_path)
    return path if path.is_absolute() else root_path / path


def _duplicates(ids: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row_id in ids:
        if row_id in seen:
            duplicates.add(row_id)
        seen.add(row_id)
    return tuple(sorted(duplicates))


def _row_string_id(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    return value.strip() if isinstance(value, str) else ""


def _reviewer_fields_invalid(row: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    failures.extend(_required_string_field_failures(row, "reviewer"))
    failures.extend(_required_string_field_failures(row, "review_date"))
    failures.extend(_iso_date_field_failures(row, "review_date"))
    return failures


def _iso_date_field_failures(row: Mapping[str, Any], field: str) -> list[str]:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return [f"{field} must be YYYY-MM-DD"]
    if parsed.isoformat() != value:
        return [f"{field} must be YYYY-MM-DD"]
    return []


def _required_string_field_failures(row: Mapping[str, Any], field: str) -> list[str]:
    value = row.get(field)
    if value is None or value == "":
        return [f"{field} required"]
    if not isinstance(value, str):
        return [f"{field} must be string"]
    if not value.strip():
        return [f"{field} required"]
    return []


def _optional_string_field_failures(row: Mapping[str, Any], field: str) -> list[str]:
    value = row.get(field)
    if value is None:
        return []
    if not isinstance(value, str):
        return [f"{field} must be string"]
    return []


def _forbidden_field_failures(row: Mapping[str, Any]) -> list[str]:
    return [
        f"{field} forbidden in manual review import"
        for field in manual_review_forbidden_field_paths(row)
    ]


def _allowed_review_import_fields(
    target_rows: Sequence[Mapping[str, Any]],
    extra_fields: Sequence[str] = (),
) -> frozenset[str]:
    allowed: set[str] = set(MANUAL_REVIEW_PROVENANCE_FIELDS)
    allowed.update(extra_fields)
    for row in target_rows:
        allowed.update(str(field) for field in row)
    return frozenset(allowed)


def _unexpected_field_failures(
    row: Mapping[str, Any],
    allowed_fields: frozenset[str],
) -> list[str]:
    return [
        f"{field} unexpected in manual review import"
        for field in sorted(str(field) for field in set(row) - allowed_fields)
    ]


def _gold_row_failures(row: Mapping[str, Any]) -> list[str]:
    failures = _reviewer_fields_invalid(row)
    failures.extend(_required_string_field_failures(row, "manual_claim_text"))
    failures.extend(_optional_string_field_failures(row, "review_notes"))
    for field in GOLD_BOOL_FIELDS:
        if not isinstance(row.get(field), bool):
            failures.append(f"{field} must be boolean")
    return failures


def _optional_exact_match_failures(
    row: Mapping[str, Any],
    target_row: Mapping[str, Any] | None,
    *,
    expected_values: Mapping[str, str],
    target_fields: Sequence[str],
) -> list[str]:
    failures: list[str] = []
    for field, expected in expected_values.items():
        actual, field_failures = _required_string_value(row, field)
        failures.extend(field_failures)
        if field_failures:
            continue
        if not actual:
            failures.append(f"{field} required")
        elif actual != expected:
            failures.append(f"{field} must match {expected}")
    expected_hash, hash_failures = _required_string_value(row, TARGET_ROW_HASH_FIELD)
    failures.extend(hash_failures)
    if not hash_failures and target_row is not None and expected_hash != review_row_fingerprint(target_row):
        failures.append(f"{TARGET_ROW_HASH_FIELD} does not match target review row")
    for field in target_fields:
        actual, field_failures = _required_string_value(row, field)
        failures.extend(field_failures)
        if field_failures:
            continue
        if target_row is None:
            continue
        expected = str(target_row.get(field) or "").strip()
        if actual != expected:
            failures.append(f"{field} does not match target review row")
    return failures


def _required_string_value(row: Mapping[str, Any], field: str) -> tuple[str, list[str]]:
    value = row.get(field)
    if value is None or value == "":
        return "", [f"{field} required"]
    if not isinstance(value, str):
        return "", [f"{field} must be string"]
    stripped = value.strip()
    if not stripped:
        return "", [f"{field} required"]
    return stripped, []


def _gold_reference_failures(row: Mapping[str, Any], target_row: Mapping[str, Any] | None) -> list[str]:
    return _optional_exact_match_failures(
        row,
        target_row,
        expected_values={
            "target_review_path": GOLD_REVIEW_TEMPLATE_PATH,
            "review_context_ref": GOLD_REVIEW_PACKET_PATH,
        },
        target_fields=(
            "source_id",
            "source_span_id",
            "document_id",
            "gold_set_domain",
        ),
    )


def _license_row_failures(row: Mapping[str, Any]) -> list[str]:
    failures = _reviewer_fields_invalid(row)
    failures.extend(_optional_string_field_failures(row, "notes"))
    for field in ("approved_for_derived_claim_storage", "approved_for_production_runtime"):
        if not isinstance(row.get(field), bool):
            failures.append(f"{field} must be boolean")
    return failures


def _license_reference_failures(row: Mapping[str, Any], target_row: Mapping[str, Any] | None) -> list[str]:
    return _optional_exact_match_failures(
        row,
        target_row,
        expected_values={
            "target_review_path": LICENSE_REVIEW_TEMPLATE_PATH,
            "review_context_ref": LICENSE_REVIEW_PACKET_PATH,
        },
        target_fields=(
            "source_type",
            "title",
            "publish_date",
            "current_license_status",
        ),
    )


def _build_report(
    *,
    review_kind: Literal["gold_set", "source_license"],
    input_path: Path,
    target_path: str,
    dry_run: bool,
    input_rows: Sequence[Any],
    applied_rows: int,
    duplicate_ids: Sequence[str],
    missing_target_ids: Sequence[str],
    invalid_rows: Sequence[ManualReviewImportInvalidRow],
    downstream_outputs: Mapping[str, str],
    extra_blockers: Sequence[str] = (),
) -> ManualReviewImportReport:
    blockers: list[str] = []
    if not input_rows:
        blockers.append("manual review import file is empty")
    if duplicate_ids:
        blockers.append(f"{len(duplicate_ids)} duplicate review ids")
    if missing_target_ids:
        blockers.append(f"{len(missing_target_ids)} review ids are missing from target")
    if invalid_rows:
        blockers.append(f"{len(invalid_rows)} review rows failed validation")
    blockers.extend(extra_blockers)
    return ManualReviewImportReport(
        report_id=(
            "RKE-GOLD-SET-REVIEW-IMPORT-REPORT-20260606"
            if review_kind == "gold_set"
            else "RKE-SOURCE-LICENSE-REVIEW-IMPORT-REPORT-20260606"
        ),
        review_kind=review_kind,
        input_path=str(input_path),
        target_path=target_path,
        dry_run=dry_run,
        accepted=bool(input_rows)
        and not duplicate_ids
        and not missing_target_ids
        and not invalid_rows
        and not extra_blockers,
        input_rows=len(input_rows),
        applied_rows=applied_rows,
        rejected_rows=len(invalid_rows),
        duplicate_ids=tuple(duplicate_ids),
        missing_target_ids=tuple(missing_target_ids),
        invalid_rows=tuple(invalid_rows),
        downstream_outputs=dict(downstream_outputs),
        blockers=tuple(blockers),
    )


def _write_gold_downstream(root_path: Path) -> dict[str, str]:
    from .completion_auditor import write_completion_audit
    from .dashboard_reports import write_dashboard_reports
    from .manual_review_batches import write_manual_review_batches
    from .operator_handoff import write_operator_handoff
    from .promotion_gate import write_production_promotion_gate_report
    from .registry_manifest import write_registry_manifest
    from .review_gates import write_gold_set_review_summary
    from .source_text_redaction import write_source_text_redaction_report

    outputs: dict[str, str] = {}
    outputs["gold_set_review_summary"] = str(write_gold_set_review_summary(root_path)["path"])
    review_batches = write_manual_review_batches(root_path)
    outputs["manual_review_batch_status"] = review_batches["status"]
    outputs["manual_review_gold_set_import_template"] = review_batches["gold_set_import_template"]
    outputs["source_text_redaction"] = str(write_source_text_redaction_report(root_path)["path"])
    outputs["completion_audit"] = str(write_completion_audit(root_path)["path"])
    outputs["production_promotion_gate"] = str(write_production_promotion_gate_report(root_path)["path"])
    operator_handoff = write_operator_handoff(root_path)
    outputs["operator_handoff.json"] = operator_handoff["json"]
    outputs["operator_handoff.markdown"] = operator_handoff["markdown"]
    outputs["lockbox_review_import_template"] = operator_handoff["lockbox_import_template"]
    outputs.update({f"dashboard.{key}": value for key, value in write_dashboard_reports(root_path).items()})
    outputs["registry_manifest"] = str(write_registry_manifest(root_path)["path"])
    return outputs


def _write_license_downstream(root_path: Path) -> dict[str, str]:
    from .completion_auditor import write_completion_audit
    from .dashboard_reports import write_dashboard_reports
    from .manual_review_batches import write_manual_review_batches
    from .operator_handoff import write_operator_handoff
    from .promotion_gate import write_production_promotion_gate_report
    from .registry_manifest import write_registry_manifest
    from .review_gates import write_source_license_review_summary
    from .source_registry_validation import write_source_registry_validation_report
    from .source_text_redaction import write_source_text_redaction_report

    outputs: dict[str, str] = {}
    outputs["license_review_summary"] = str(write_source_license_review_summary(root_path)["path"])
    outputs["source_registry_validation"] = str(write_source_registry_validation_report(root_path)["path"])
    review_batches = write_manual_review_batches(root_path)
    outputs["manual_review_batch_status"] = review_batches["status"]
    outputs["manual_review_source_license_import_template"] = review_batches["source_license_import_template"]
    outputs["source_text_redaction"] = str(write_source_text_redaction_report(root_path)["path"])
    outputs["completion_audit"] = str(write_completion_audit(root_path)["path"])
    outputs["production_promotion_gate"] = str(write_production_promotion_gate_report(root_path)["path"])
    operator_handoff = write_operator_handoff(root_path)
    outputs["operator_handoff.json"] = operator_handoff["json"]
    outputs["operator_handoff.markdown"] = operator_handoff["markdown"]
    outputs["lockbox_review_import_template"] = operator_handoff["lockbox_import_template"]
    outputs.update({f"dashboard.{key}": value for key, value in write_dashboard_reports(root_path).items()})
    outputs["registry_manifest"] = str(write_registry_manifest(root_path)["path"])
    return outputs


def apply_gold_set_review_import(
    root: str | Path,
    input_path: str | Path,
    *,
    dry_run: bool = False,
) -> ManualReviewImportReport:
    root_path = Path(root)
    resolved_input_path = _resolve_input_path(root_path, input_path)
    target_path = root_path / GOLD_REVIEW_TEMPLATE_PATH
    input_rows, input_parse_blockers = load_jsonl_with_errors(
        resolved_input_path,
        label="gold-set review import",
    )
    raw_target_rows, target_parse_blockers = load_jsonl_with_errors(
        target_path,
        label="gold-set target review",
    )
    target_rows, invalid_target_rows = _split_mapping_rows(raw_target_rows)
    target_by_id = {str(row.get("claim_id") or ""): row for row in target_rows}
    allowed_fields = _allowed_review_import_fields(
        target_rows,
        (*GOLD_IMPORT_TEMPLATE_ONLY_FIELDS, *GOLD_IMPORTED_FIELDS),
    )
    target_blockers = [*target_parse_blockers]
    if invalid_target_rows:
        target_blockers.append(
            "gold-set target review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_target_rows)
        )
    input_ids = [_row_string_id(row, "claim_id") for row in input_rows if isinstance(row, Mapping)]
    duplicate_ids = _duplicates(input_ids)
    missing_target_ids = tuple(sorted({row_id for row_id in input_ids if row_id and row_id not in target_by_id}))
    invalid_rows: list[ManualReviewImportInvalidRow] = []
    for idx, raw_row in enumerate(input_rows, 1):
        if not isinstance(raw_row, Mapping):
            invalid_rows.append(
                ManualReviewImportInvalidRow(
                    row_number=idx,
                    row_id=f"<non-object-row-{idx}>",
                    reasons=("review row must be object",),
                )
            )
            continue
        row = raw_row
        row_id = _row_string_id(row, "claim_id")
        failures: list[str] = []
        failures.extend(_required_string_field_failures(row, "claim_id"))
        if row_id in duplicate_ids:
            failures.append("duplicate claim_id in import")
        if row_id in missing_target_ids:
            failures.append("claim_id missing from target review template")
        failures.extend(_unexpected_field_failures(row, allowed_fields))
        failures.extend(_forbidden_field_failures(row))
        failures.extend(_gold_reference_failures(row, target_by_id.get(row_id)))
        failures.extend(_gold_row_failures(row))
        if failures:
            invalid_rows.append(
                ManualReviewImportInvalidRow(row_number=idx, row_id=row_id or "<missing-claim-id>", reasons=tuple(failures))
            )

    applied_rows = 0
    downstream_outputs: dict[str, str] = {}
    parse_blockers = tuple((*input_parse_blockers, *target_blockers))
    accepted = (
        bool(input_rows)
        and not duplicate_ids
        and not missing_target_ids
        and not invalid_rows
        and not parse_blockers
    )
    if accepted and not dry_run:
        import_by_id = {str(row["claim_id"]): row for row in input_rows if isinstance(row, Mapping)}
        merged: list[dict[str, Any]] = []
        for row in target_rows:
            out = dict(row)
            imported = import_by_id.get(str(row.get("claim_id") or ""))
            if imported is not None:
                for field in GOLD_IMPORTED_FIELDS:
                    if field in imported:
                        out[field] = imported[field]
                applied_rows += 1
            merged.append(out)
        _write_jsonl(target_path, merged)
        downstream_outputs = _write_gold_downstream(root_path)

    report = _build_report(
        review_kind="gold_set",
        input_path=resolved_input_path,
        target_path=GOLD_REVIEW_TEMPLATE_PATH,
        dry_run=dry_run,
        input_rows=input_rows,
        applied_rows=applied_rows,
        duplicate_ids=duplicate_ids,
        missing_target_ids=missing_target_ids,
        invalid_rows=tuple(invalid_rows),
        downstream_outputs=downstream_outputs,
        extra_blockers=parse_blockers,
    )
    _write_json(root_path / GOLD_REVIEW_IMPORT_REPORT_PATH, asdict(report))
    return report


def apply_source_license_review_import(
    root: str | Path,
    input_path: str | Path,
    *,
    dry_run: bool = False,
) -> ManualReviewImportReport:
    root_path = Path(root)
    resolved_input_path = _resolve_input_path(root_path, input_path)
    target_path = root_path / LICENSE_REVIEW_TEMPLATE_PATH
    input_rows, input_parse_blockers = load_jsonl_with_errors(
        resolved_input_path,
        label="source-license review import",
    )
    raw_target_rows, target_parse_blockers = load_jsonl_with_errors(
        target_path,
        label="source-license target review",
    )
    target_rows, invalid_target_rows = _split_mapping_rows(raw_target_rows)
    target_by_id = {str(row.get("source_id") or ""): row for row in target_rows}
    allowed_fields = _allowed_review_import_fields(target_rows, LICENSE_IMPORTED_FIELDS)
    target_blockers = [*target_parse_blockers]
    if invalid_target_rows:
        target_blockers.append(
            "source-license target review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_target_rows)
        )
    input_ids = [_row_string_id(row, "source_id") for row in input_rows if isinstance(row, Mapping)]
    duplicate_ids = _duplicates(input_ids)
    missing_target_ids = tuple(sorted({row_id for row_id in input_ids if row_id and row_id not in target_by_id}))
    invalid_rows: list[ManualReviewImportInvalidRow] = []
    for idx, raw_row in enumerate(input_rows, 1):
        if not isinstance(raw_row, Mapping):
            invalid_rows.append(
                ManualReviewImportInvalidRow(
                    row_number=idx,
                    row_id=f"<non-object-row-{idx}>",
                    reasons=("review row must be object",),
                )
            )
            continue
        row = raw_row
        row_id = _row_string_id(row, "source_id")
        failures: list[str] = []
        failures.extend(_required_string_field_failures(row, "source_id"))
        if row_id in duplicate_ids:
            failures.append("duplicate source_id in import")
        if row_id in missing_target_ids:
            failures.append("source_id missing from target review template")
        failures.extend(_unexpected_field_failures(row, allowed_fields))
        failures.extend(_forbidden_field_failures(row))
        failures.extend(_license_reference_failures(row, target_by_id.get(row_id)))
        failures.extend(_license_row_failures(row))
        if failures:
            invalid_rows.append(
                ManualReviewImportInvalidRow(row_number=idx, row_id=row_id or "<missing-source-id>", reasons=tuple(failures))
            )

    applied_rows = 0
    downstream_outputs: dict[str, str] = {}
    parse_blockers = tuple((*input_parse_blockers, *target_blockers))
    accepted = (
        bool(input_rows)
        and not duplicate_ids
        and not missing_target_ids
        and not invalid_rows
        and not parse_blockers
    )
    if accepted and not dry_run:
        import_by_id = {str(row["source_id"]): row for row in input_rows if isinstance(row, Mapping)}
        merged: list[dict[str, Any]] = []
        for row in target_rows:
            out = dict(row)
            imported = import_by_id.get(str(row.get("source_id") or ""))
            if imported is not None:
                for field in LICENSE_IMPORTED_FIELDS:
                    if field in imported:
                        out[field] = imported[field]
                applied_rows += 1
            merged.append(out)
        _write_jsonl(target_path, merged)
        downstream_outputs = _write_license_downstream(root_path)

    report = _build_report(
        review_kind="source_license",
        input_path=resolved_input_path,
        target_path=LICENSE_REVIEW_TEMPLATE_PATH,
        dry_run=dry_run,
        input_rows=input_rows,
        applied_rows=applied_rows,
        duplicate_ids=duplicate_ids,
        missing_target_ids=missing_target_ids,
        invalid_rows=tuple(invalid_rows),
        downstream_outputs=downstream_outputs,
        extra_blockers=parse_blockers,
    )
    _write_json(root_path / LICENSE_REVIEW_IMPORT_REPORT_PATH, asdict(report))
    return report

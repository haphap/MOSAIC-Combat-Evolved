"""Controlled import paths for manual RKE review gates."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .phase_minus1 import load_jsonl_with_errors

from mosaic.rke.json_io import jsonable as _jsonable, write_json as _write_json


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
    "target_correct",
    "horizon_correct",
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
    "proposed_analyst_claim",
    "proposed_pre_review",
    "proposed_claim_type",
    "proposed_extraction_confidence_bin",
    "proposed_gold_set_domain",
    "proposed_gold_set_domains",
    "proposed_direction",
    "proposed_cause_variables",
    "proposed_target_variables",
    "proposed_review_risk_flags",
    "proposed_research_layers",
    "proposed_mosaic_agent_trace",
    "proposed_claim_regime_trace",
    "proposed_source_start_char",
    "proposed_source_end_char",
    "proposed_source_span_ref_id",
    "proposed_source_text_hash",
    "proposed_verifier_status",
)
MANUAL_REVIEW_IMPORT_FORBIDDEN_FIELDS = frozenset(
    {
        "abstract",
        "claim_text",
        "markdown_path",
        "original_markdown",
        "pdf_path",
        "pdf_url",
        "retrieval_locator",
        "source_text",
        "source_span_text",
        "span_text",
        "span_preview",
        "full_text",
        "url",
    }
)
STALE_TARGET_ROW_HASH_REASON = "target_row_hash does not match target review row"


def manual_review_forbidden_field_paths(value: Any, prefix: str = "") -> tuple[str, ...]:
    """Return forbidden source-text field paths anywhere in a manual payload."""
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = str(key)
            path = f"{prefix}.{key_path}" if prefix else key_path
            if key_path.strip().lower() in MANUAL_REVIEW_IMPORT_FORBIDDEN_FIELDS:
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
    invalid_reason_counts: Mapping[str, int]
    downstream_outputs: Mapping[str, str]
    blockers: Sequence[str]


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


def _load_jsonl_with_missing_blocker(
    path: Path,
    *,
    label: str,
) -> tuple[list[tuple[int, Any]], tuple[str, ...]]:
    try:
        return load_jsonl_with_errors(path, label=label)
    except FileNotFoundError:
        return [], (f"{label} missing: {path}",)


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
        blockers.extend(
            _invalid_row_reason_summary_blockers(
                review_kind=review_kind,
                invalid_rows=invalid_rows,
            )
        )
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
        invalid_reason_counts=dict(
            sorted(
                Counter(
                    reason for row in invalid_rows for reason in row.reasons
                ).items()
            )
        ),
        downstream_outputs=dict(downstream_outputs),
        blockers=tuple(blockers),
    )


def _invalid_row_reason_summary_blockers(
    *,
    review_kind: Literal["gold_set", "source_license"],
    invalid_rows: Sequence[ManualReviewImportInvalidRow],
) -> tuple[str, ...]:
    reason_counts = Counter(
        reason for row in invalid_rows for reason in row.reasons
    )
    blockers: list[str] = []
    stale_count = reason_counts.pop(STALE_TARGET_ROW_HASH_REASON, 0)
    if stale_count:
        refresh_hint = (
            "rerun `mosaic-rke prepare-gold-review --root . --full --force` "
            "before filling reviewer decisions"
            if review_kind == "gold_set"
            else "rerun the source-license policy build from the current template"
        )
        blockers.append(
            f"{stale_count} review rows have stale target_row_hash; {refresh_hint}"
        )
    for reason, count in reason_counts.most_common(8):
        blockers.append(f"{count} review rows: {reason}")
    remaining_reason_count = max(len(reason_counts) - 8, 0)
    if remaining_reason_count:
        blockers.append(
            f"{remaining_reason_count} additional validation reason(s) suppressed"
        )
    return tuple(blockers)


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
    from .license_review_packet import write_license_review_packet
    from .manual_review_batches import write_manual_review_batches
    from .operator_handoff import write_operator_handoff
    from .promotion_gate import write_production_promotion_gate_report
    from .registry_manifest import write_registry_manifest
    from .review_gates import write_source_license_review_summary
    from .source_registry_validation import write_source_registry_validation_report
    from .source_text_redaction import write_source_text_redaction_report

    outputs: dict[str, str] = {}
    outputs["license_review_summary"] = str(write_source_license_review_summary(root_path)["path"])
    license_packet = write_license_review_packet(root_path)
    outputs["license_review_packet.json"] = license_packet["json"]
    outputs["license_review_packet.markdown"] = license_packet["markdown"]
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


def build_manual_review_import_report(
    *,
    review_kind: Literal["gold_set", "source_license"],
    input_rows: Sequence[Any],
    target_rows: Sequence[Any],
    input_path: str | Path,
    dry_run: bool = True,
    parse_blockers: Sequence[str] = (),
) -> ManualReviewImportReport:
    """Validate supplied review rows without applying decisions or writing reports."""
    if review_kind == "gold_set":
        id_field = "claim_id"
        target_path = GOLD_REVIEW_TEMPLATE_PATH
        target_label = "gold-set"
        imported_fields = (*GOLD_IMPORT_TEMPLATE_ONLY_FIELDS, *GOLD_IMPORTED_FIELDS)
        reference_failures = _gold_reference_failures
        row_failures = _gold_row_failures
    else:
        id_field = "source_id"
        target_path = LICENSE_REVIEW_TEMPLATE_PATH
        target_label = "source-license"
        imported_fields = LICENSE_IMPORTED_FIELDS
        reference_failures = _license_reference_failures
        row_failures = _license_row_failures
    valid_targets, invalid_target_rows = _split_mapping_rows(target_rows)
    target_by_id = {str(row.get(id_field) or ""): row for row in valid_targets}
    allowed_fields = _allowed_review_import_fields(valid_targets, imported_fields)
    blockers = list(parse_blockers)
    if invalid_target_rows:
        blockers.append(
            f"{target_label} target review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_target_rows)
        )
    input_ids = [_row_string_id(row, id_field) for row in input_rows if isinstance(row, Mapping)]
    duplicate_ids = _duplicates(input_ids)
    missing_target_ids = tuple(sorted({row_id for row_id in input_ids if row_id and row_id not in target_by_id}))
    invalid_rows: list[ManualReviewImportInvalidRow] = []
    for idx, row in enumerate(input_rows, 1):
        if not isinstance(row, Mapping):
            invalid_rows.append(
                ManualReviewImportInvalidRow(
                    row_number=idx,
                    row_id=f"<non-object-row-{idx}>",
                    reasons=("review row must be object",),
                )
            )
            continue
        row_id = _row_string_id(row, id_field)
        failures = _required_string_field_failures(row, id_field)
        if row_id in duplicate_ids:
            failures.append(f"duplicate {id_field} in import")
        if row_id in missing_target_ids:
            failures.append(f"{id_field} missing from target review template")
        failures.extend(_unexpected_field_failures(row, allowed_fields))
        failures.extend(_forbidden_field_failures(row))
        failures.extend(reference_failures(row, target_by_id.get(row_id)))
        failures.extend(row_failures(row))
        if failures:
            invalid_rows.append(
                ManualReviewImportInvalidRow(
                    row_number=idx,
                    row_id=row_id or f"<missing-{id_field.replace('_', '-')}>",
                    reasons=tuple(failures),
                )
            )
    return _build_report(
        review_kind=review_kind,
        input_path=Path(input_path),
        target_path=target_path,
        dry_run=dry_run,
        input_rows=input_rows,
        applied_rows=0,
        duplicate_ids=duplicate_ids,
        missing_target_ids=missing_target_ids,
        invalid_rows=invalid_rows,
        downstream_outputs={},
        extra_blockers=blockers,
    )


def _apply_manual_review_import(
    root: str | Path,
    input_path: str | Path,
    *,
    review_kind: Literal["gold_set", "source_license"],
    dry_run: bool,
) -> ManualReviewImportReport:
    root_path = Path(root)
    resolved_input_path = _resolve_input_path(root_path, input_path)
    if review_kind == "gold_set":
        target_path = root_path / GOLD_REVIEW_TEMPLATE_PATH
        report_path = GOLD_REVIEW_IMPORT_REPORT_PATH
        label = "gold-set"
        id_field = "claim_id"
        imported_fields = GOLD_IMPORTED_FIELDS
        write_downstream = _write_gold_downstream
    else:
        target_path = root_path / LICENSE_REVIEW_TEMPLATE_PATH
        report_path = LICENSE_REVIEW_IMPORT_REPORT_PATH
        label = "source-license"
        id_field = "source_id"
        imported_fields = LICENSE_IMPORTED_FIELDS
        write_downstream = _write_license_downstream
    input_rows, input_blockers = _load_jsonl_with_missing_blocker(
        resolved_input_path, label=f"{label} review import",
    )
    target_rows, target_blockers = _load_jsonl_with_missing_blocker(
        target_path, label=f"{label} target review",
    )
    report = build_manual_review_import_report(
        review_kind=review_kind,
        input_rows=input_rows,
        target_rows=target_rows,
        input_path=resolved_input_path,
        dry_run=dry_run,
        parse_blockers=(*input_blockers, *target_blockers),
    )
    if report.accepted and not dry_run:
        import_by_id = {str(row[id_field]): row for row in input_rows}
        merged: list[dict[str, Any]] = []
        applied_rows = 0
        for row in target_rows:
            out = dict(row)
            imported = import_by_id.get(str(row.get(id_field) or ""))
            if imported is not None:
                out.update({field: imported[field] for field in imported_fields if field in imported})
                applied_rows += 1
            merged.append(out)
        _write_jsonl(target_path, merged)
        report = replace(report, applied_rows=applied_rows, downstream_outputs=write_downstream(root_path))
    _write_json(root_path / report_path, asdict(report))
    return report


def apply_gold_set_review_import(
    root: str | Path,
    input_path: str | Path,
    *,
    dry_run: bool = False,
) -> ManualReviewImportReport:
    return _apply_manual_review_import(root, input_path, review_kind="gold_set", dry_run=dry_run)


def apply_source_license_review_import(
    root: str | Path,
    input_path: str | Path,
    *,
    dry_run: bool = False,
) -> ManualReviewImportReport:
    return _apply_manual_review_import(root, input_path, review_kind="source_license", dry_run=dry_run)

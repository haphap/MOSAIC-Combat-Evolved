"""Expand a signed source-license policy into sparse review import rows."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .manual_review_import import (
    LICENSE_REVIEW_TEMPLATE_PATH,
    TARGET_ROW_HASH_FIELD,
    manual_review_forbidden_field_paths,
    review_row_fingerprint,
)


DEFAULT_LICENSE_POLICY_IMPORT_PATH = "registry/review_batches/source_license_policy_import.jsonl"
LICENSE_POLICY_IMPORT_REPORT_PATH = "registry/review_batches/source_license_policy_import_report.json"
SOURCE_LICENSE_POLICY_TEMPLATE_PATH = "registry/review_batches/source_license_policy_template.json"
SOURCE_LICENSE_REVIEWED_POLICY_PATH = "registry/review_batches/source_license_policy_reviewed.json"
SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH = "registry/review_batches/source_license_review_workbook.md"
SOURCE_LICENSE_WORKBOOK_SAMPLE_ROWS = 50
MATCHED_ROWS_FINGERPRINT_FIELD = "matched_rows_fingerprint"
SOURCE_LICENSE_POLICY_ALLOWED_FIELDS = frozenset(
    {
        "approved_for_derived_claim_storage",
        "approved_for_production_runtime",
        "build_command",
        "dry_run_command",
        "filters",
        "matched_row_count",
        MATCHED_ROWS_FINGERPRINT_FIELD,
        "notes",
        "publish_date_max",
        "publish_date_min",
        "review_context_ref",
        "review_date",
        "reviewer",
        "target_review_path",
        "template_note",
    }
)
SOURCE_LICENSE_POLICY_FILTER_ALLOWED_FIELDS = frozenset(
    {
        "current_license_status",
        "publish_date_max",
        "publish_date_min",
        "review_status",
        "source_id_prefix",
        "source_type",
    }
)


@dataclass(frozen=True)
class SourceLicensePolicyFilters:
    source_type: Sequence[str] = ()
    current_license_status: Sequence[str] = ()
    review_status: Sequence[str] = ()
    publish_date_min: str | None = None
    publish_date_max: str | None = None
    source_id_prefix: Sequence[str] = ()


@dataclass(frozen=True)
class SourceLicensePolicyImportReport:
    report_id: str
    policy_path: str
    target_review_path: str
    output_path: str
    dry_run: bool
    accepted: bool
    total_review_rows: int
    matched_rows: int
    output_rows: int
    reviewer: str
    review_date: str
    approved_for_derived_claim_storage: bool | None
    approved_for_production_runtime: bool | None
    filters: SourceLicensePolicyFilters
    blockers: Sequence[str]


@dataclass(frozen=True)
class SourceLicenseReviewedPolicyStarterResult:
    path: str
    template_path: str
    workbook_path: str
    workbook_rows: int
    force: bool
    written: bool
    overwritten: bool
    blockers: Sequence[str]


@dataclass(frozen=True)
class SourceLicenseReviewWorkbookSummary:
    workbook_id: str
    path: str
    review_template_path: str
    review_packet_path: str
    policy_template_path: str
    reviewed_policy_path: str
    policy_import_path: str
    pending_rows: int
    row_count: int
    sample_rows: int
    matched_row_count: int
    matched_rows_fingerprint: str
    publish_date_min: str | None
    publish_date_max: str | None
    source_type_counts: Mapping[str, int]
    license_status_counts: Mapping[str, int]
    blockers: Sequence[str]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return {"path": str(path), "rows": len(rows)}


def _malformed_review_row_blocker(row_numbers: Sequence[int]) -> str:
    return "source license review row must be object at row(s): " + ", ".join(
        str(row_number) for row_number in row_numbers
    )


def _load_review_template_rows(root_path: Path) -> tuple[list[Any], list[Mapping[str, Any]], tuple[str, ...], int]:
    path = root_path / LICENSE_REVIEW_TEMPLATE_PATH
    if not path.exists():
        return [], [], (f"{LICENSE_REVIEW_TEMPLATE_PATH} missing",), 0

    raw_rows: list[Any] = []
    valid_rows: list[Mapping[str, Any]] = []
    invalid_row_numbers: list[int] = []
    blockers: list[str] = []
    total_rows = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            total_rows += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                blockers.append(f"source license review row {line_number} must contain valid JSON: {exc.msg}")
                continue
            raw_rows.append(row)
            if isinstance(row, Mapping):
                valid_rows.append(row)
            else:
                invalid_row_numbers.append(line_number)
    if invalid_row_numbers:
        blockers.append(_malformed_review_row_blocker(invalid_row_numbers))
    return raw_rows, valid_rows, tuple(blockers), total_rows


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, list | tuple) else [value]
    return tuple(str(item).strip() for item in values if str(item).strip())


def _load_policy(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _policy_rejection_report(
    *,
    root_path: Path,
    resolved_policy_path: Path,
    resolved_output_path: Path,
    dry_run: bool,
    blocker: str,
    write_report: bool = True,
) -> SourceLicensePolicyImportReport:
    _, _, review_blockers, total_review_rows = _load_review_template_rows(root_path)
    report = SourceLicensePolicyImportReport(
        report_id="RKE-SOURCE-LICENSE-POLICY-IMPORT-REPORT-20260606",
        policy_path=str(resolved_policy_path),
        target_review_path=LICENSE_REVIEW_TEMPLATE_PATH,
        output_path=str(resolved_output_path),
        dry_run=dry_run,
        accepted=False,
        total_review_rows=total_review_rows,
        matched_rows=0,
        output_rows=0,
        reviewer="",
        review_date="",
        approved_for_derived_claim_storage=None,
        approved_for_production_runtime=None,
        filters=SourceLicensePolicyFilters(),
        blockers=tuple(dict.fromkeys((blocker, *review_blockers))),
    )
    if write_report:
        _write_json(root_path / LICENSE_POLICY_IMPORT_REPORT_PATH, asdict(report))
    return report


def _forbidden_policy_fields(policy: Mapping[str, Any]) -> tuple[str, ...]:
    return manual_review_forbidden_field_paths(policy)


def _unexpected_policy_fields(policy: Mapping[str, Any]) -> tuple[str, ...]:
    fields = [str(field) for field in set(policy) - SOURCE_LICENSE_POLICY_ALLOWED_FIELDS]
    filters = policy.get("filters") or {}
    if isinstance(filters, Mapping):
        fields.extend(
            f"filters.{field}"
            for field in sorted(str(field) for field in set(filters) - SOURCE_LICENSE_POLICY_FILTER_ALLOWED_FIELDS)
        )
    return tuple(sorted(fields))


def _required_policy_string_failures(policy: Mapping[str, Any], field: str) -> list[str]:
    value = policy.get(field)
    if value is None or value == "":
        return [f"{field} required"]
    if not isinstance(value, str):
        return [f"{field} must be string"]
    if not value.strip():
        return [f"{field} required"]
    return []


def _iso_policy_date_failures(policy: Mapping[str, Any], field: str) -> list[str]:
    return _iso_optional_date_failures(policy.get(field), field)


def _iso_optional_date_failures(value: Any, label: str) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return [f"{label} must be YYYY-MM-DD"]
    if parsed.isoformat() != value:
        return [f"{label} must be YYYY-MM-DD"]
    return []


def _optional_policy_date_range_failures(
    start_value: Any,
    end_value: Any,
    *,
    start_label: str,
    end_label: str,
) -> list[str]:
    if not isinstance(start_value, str) or not isinstance(end_value, str):
        return []
    start = start_value.strip()
    end = end_value.strip()
    if not start or not end:
        return []
    try:
        parsed_start = date.fromisoformat(start)
        parsed_end = date.fromisoformat(end)
    except ValueError:
        return []
    if parsed_start > parsed_end:
        return [f"{start_label} must be <= {end_label}"]
    return []


def _optional_policy_string_failures(policy: Mapping[str, Any], field: str) -> list[str]:
    value = policy.get(field)
    if value is None:
        return []
    if not isinstance(value, str):
        return [f"{field} must be string"]
    return []


def _policy_filter_shape_failures(policy: Mapping[str, Any]) -> list[str]:
    raw_filters = policy.get("filters") or {}
    if not isinstance(raw_filters, Mapping):
        return ["filters must be object"]
    failures: list[str] = []
    for field in (
        "source_type",
        "current_license_status",
        "review_status",
        "source_id_prefix",
    ):
        value = raw_filters.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            if not value.strip():
                failures.append(f"filters.{field} required")
            continue
        if not isinstance(value, list | tuple):
            failures.append(f"filters.{field} must be string or list of strings")
            continue
        for index, item in enumerate(value):
            if not isinstance(item, str):
                failures.append(f"filters.{field}[{index}] must be string")
            elif not item.strip():
                failures.append(f"filters.{field}[{index}] required")
    return failures


def _policy_filter_date_failures(policy: Mapping[str, Any]) -> list[str]:
    raw_filters = policy.get("filters") or {}
    if not isinstance(raw_filters, Mapping):
        return []
    failures: list[str] = []
    for field in ("publish_date_min", "publish_date_max"):
        value = raw_filters.get(field)
        label = f"filters.{field}"
        if value is not None and not isinstance(value, str):
            failures.append(f"{label} must be string")
            continue
        failures.extend(_iso_optional_date_failures(value, label))
    failures.extend(
        _optional_policy_date_range_failures(
            raw_filters.get("publish_date_min"),
            raw_filters.get("publish_date_max"),
            start_label="filters.publish_date_min",
            end_label="filters.publish_date_max",
        )
    )
    return failures


def _policy_filters(policy: Mapping[str, Any]) -> SourceLicensePolicyFilters:
    raw_filters = policy.get("filters") or {}
    if not isinstance(raw_filters, Mapping):
        return SourceLicensePolicyFilters()
    return SourceLicensePolicyFilters(
        source_type=_as_str_tuple(raw_filters.get("source_type")),
        current_license_status=_as_str_tuple(raw_filters.get("current_license_status")),
        review_status=_as_str_tuple(raw_filters.get("review_status")),
        publish_date_min=(
            str(raw_filters.get("publish_date_min")).strip()
            if raw_filters.get("publish_date_min") is not None
            else None
        ),
        publish_date_max=(
            str(raw_filters.get("publish_date_max")).strip()
            if raw_filters.get("publish_date_max") is not None
            else None
        ),
        source_id_prefix=_as_str_tuple(raw_filters.get("source_id_prefix")),
    )


def _matches(row: Mapping[str, Any], filters: SourceLicensePolicyFilters) -> bool:
    source_type = str(row.get("source_type") or "")
    current_status = str(row.get("current_license_status") or "")
    review_status = "reviewed" if _license_row_complete(row) else "pending"
    publish_date = str(row.get("publish_date") or "")
    source_id = str(row.get("source_id") or "")
    if filters.source_type and source_type not in set(filters.source_type):
        return False
    if filters.current_license_status and current_status not in set(filters.current_license_status):
        return False
    if filters.review_status and review_status not in set(filters.review_status):
        return False
    if filters.publish_date_min and publish_date < filters.publish_date_min:
        return False
    if filters.publish_date_max and publish_date > filters.publish_date_max:
        return False
    return not filters.source_id_prefix or any(
        source_id.startswith(prefix) for prefix in filters.source_id_prefix
    )


def _license_row_complete(row: Mapping[str, Any]) -> bool:
    return (
        isinstance(row.get("approved_for_derived_claim_storage"), bool)
        and isinstance(row.get("approved_for_production_runtime"), bool)
        and bool(str(row.get("reviewer") or "").strip())
        and bool(str(row.get("review_date") or "").strip())
    )


def _matched_rows_fingerprint(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {
            "source_id": str(row.get("source_id") or ""),
            TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        }
        for row in rows
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + sha256(encoded).hexdigest()


def _matched_publish_date_bounds(rows: Sequence[Mapping[str, Any]]) -> tuple[str | None, str | None]:
    publish_dates = sorted(str(row.get("publish_date") or "").strip() for row in rows if row.get("publish_date"))
    if not publish_dates:
        return None, None
    return publish_dates[0], publish_dates[-1]


def _review_row(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "approved_for_derived_claim_storage": policy.get("approved_for_derived_claim_storage"),
        "approved_for_production_runtime": policy.get("approved_for_production_runtime"),
        "current_license_status": str(row.get("current_license_status") or ""),
        "notes": str(policy.get("notes") or ""),
        "publish_date": str(row.get("publish_date") or ""),
        "review_date": str(policy.get("review_date") or ""),
        "review_context_ref": str(policy.get("review_context_ref") or "registry/compliance/tushare_license_review_packet.json"),
        "reviewer": str(policy.get("reviewer") or ""),
        "source_id": str(row.get("source_id") or ""),
        "source_type": str(row.get("source_type") or ""),
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        "target_review_path": LICENSE_REVIEW_TEMPLATE_PATH,
        "title": str(row.get("title") or ""),
    }


def _short_workbook_preview(value: Any, *, max_chars: int = 96) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _markdown_cell(value: Any, *, max_chars: int = 96) -> str:
    if isinstance(value, Mapping):
        text = json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
    elif isinstance(value, (list, tuple, set)):
        text = ", ".join(str(item) for item in value)
    else:
        text = str(value or "")
    return _short_workbook_preview(text, max_chars=max_chars).replace("|", "\\|") or "-"


def _counter_dict(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(row.get(field) or "").strip() or "missing" for row in rows)
    return dict(sorted(counts.items()))


def _source_license_workbook_row(index: int, row: Mapping[str, Any]) -> dict[str, Any]:
    title = str(row.get("title") or "").strip()
    return {
        "index": index,
        "source_id": str(row.get("source_id") or ""),
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        "source_type": str(row.get("source_type") or ""),
        "current_license_status": str(row.get("current_license_status") or ""),
        "publish_date": str(row.get("publish_date") or ""),
        "title_preview": _short_workbook_preview(title, max_chars=96),
        "title_truncated": len(title) > 96,
    }


def build_source_license_policy_template(root: str | Path = ".") -> Mapping[str, Any]:
    """Build a reviewer-fillable policy template for same-source license batches.

    The template is intentionally not accepted by ``build-license-review-import``
    until a reviewer supplies the booleans, reviewer, and review_date.
    """
    root_path = Path(root)
    _, review_rows, _, _ = _load_review_template_rows(root_path)
    pending_rows = [row for row in review_rows if not _license_row_complete(row)]
    source_types = sorted({str(row.get("source_type") or "") for row in pending_rows if row.get("source_type")})
    statuses = sorted(
        {
            str(row.get("current_license_status") or "")
            for row in pending_rows
            if row.get("current_license_status")
        }
    )
    publish_dates = sorted(str(row.get("publish_date") or "") for row in pending_rows if row.get("publish_date"))
    filters = SourceLicensePolicyFilters(
        current_license_status=tuple(statuses),
        review_status=("pending",) if pending_rows else (),
        publish_date_min=publish_dates[0] if publish_dates else None,
        publish_date_max=publish_dates[-1] if publish_dates else None,
        source_type=tuple(source_types),
        source_id_prefix=()
        if pending_rows
        else ("__NO_PENDING_SOURCE_LICENSE_ROWS__",),
    )
    matched_rows = [row for row in pending_rows if _matches(row, filters)]
    return {
        "approved_for_derived_claim_storage": None,
        "approved_for_production_runtime": None,
        "build_command": (
            "mosaic-rke build-license-review-import --root . "
            f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
            f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH}"
        ),
        "dry_run_command": (
            "mosaic-rke apply-license-review --root . "
            f"--input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} --dry-run"
        ),
        "filters": {
            "current_license_status": statuses,
            "publish_date_max": publish_dates[-1] if publish_dates else None,
            "publish_date_min": publish_dates[0] if publish_dates else None,
            "review_status": ["pending"] if pending_rows else [],
            "source_id_prefix": list(filters.source_id_prefix),
            "source_type": source_types,
        },
        "matched_row_count": len(matched_rows),
        MATCHED_ROWS_FINGERPRINT_FIELD: _matched_rows_fingerprint(matched_rows),
        "notes": "",
        "publish_date_max": publish_dates[-1] if publish_dates else None,
        "publish_date_min": publish_dates[0] if publish_dates else None,
        "review_date": "",
        "review_context_ref": "registry/compliance/tushare_license_review_packet.json",
        "reviewer": "",
        "target_review_path": LICENSE_REVIEW_TEMPLATE_PATH,
        "template_note": (
            f"Copy this template to {SOURCE_LICENSE_REVIEWED_POLICY_PATH}; reviewer "
            "must fill reviewer, review_date, notes, and both approval booleans "
            "in the reviewed policy before expanding it into per-source import rows."
        ),
    }


def build_source_license_review_workbook(
    root: str | Path = ".",
    *,
    sample_rows: int = SOURCE_LICENSE_WORKBOOK_SAMPLE_ROWS,
) -> tuple[SourceLicenseReviewWorkbookSummary, tuple[Mapping[str, Any], ...]]:
    """Build a read-only source-license policy review workbook.

    The workbook helps compliance review the policy scope without embedding
    report abstracts or any approval decisions. The signed policy JSON remains
    the only importable artifact.
    """
    if sample_rows <= 0:
        raise ValueError("sample_rows must be positive")

    root_path = Path(root)
    raw_rows, review_rows, review_blockers, total_review_rows = _load_review_template_rows(root_path)
    pending_rows = [row for row in review_rows if not _license_row_complete(row)]
    policy_template = build_source_license_policy_template(root_path)
    filters = _policy_filters(policy_template)
    matched_rows = [row for row in review_rows if _matches(row, filters)]
    publish_date_min, publish_date_max = _matched_publish_date_bounds(matched_rows)
    workbook_rows = tuple(
        _source_license_workbook_row(index, row)
        for index, row in enumerate(pending_rows[:sample_rows], 1)
    )
    blockers: list[str] = [*review_blockers]
    if not raw_rows:
        blockers.append("source-license review template is missing or empty")
    elif not review_rows:
        blockers.append("source-license review template has no valid review rows")

    return (
        SourceLicenseReviewWorkbookSummary(
            workbook_id="RKE-SOURCE-LICENSE-REVIEW-WORKBOOK-20260606",
            path=SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
            review_template_path=LICENSE_REVIEW_TEMPLATE_PATH,
            review_packet_path="registry/compliance/tushare_license_review_packet.json",
            policy_template_path=SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
            reviewed_policy_path=SOURCE_LICENSE_REVIEWED_POLICY_PATH,
            policy_import_path=DEFAULT_LICENSE_POLICY_IMPORT_PATH,
            pending_rows=len(pending_rows),
            row_count=total_review_rows,
            sample_rows=len(workbook_rows),
            matched_row_count=len(matched_rows),
            matched_rows_fingerprint=_matched_rows_fingerprint(matched_rows),
            publish_date_min=publish_date_min,
            publish_date_max=publish_date_max,
            source_type_counts=_counter_dict(review_rows, "source_type"),
            license_status_counts=_counter_dict(review_rows, "current_license_status"),
            blockers=tuple(blockers),
        ),
        workbook_rows,
    )


def render_source_license_review_workbook_markdown(
    summary: SourceLicenseReviewWorkbookSummary,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# RKE Source-License Review Workbook",
        "",
        f"- Workbook ID: {summary.workbook_id}",
        f"- Pending rows: {summary.pending_rows}",
        f"- Source rows in template: {summary.row_count}",
        f"- Matched policy rows: {summary.matched_row_count}",
        f"- Matched rows fingerprint: `{summary.matched_rows_fingerprint}`",
        f"- Publish date range: {summary.publish_date_min or 'none'} to {summary.publish_date_max or 'none'}",
        f"- Review template: `{summary.review_template_path}`",
        f"- Review packet: `{summary.review_packet_path}`",
        f"- Policy template: `{summary.policy_template_path}`",
        f"- Reviewed policy: `{summary.reviewed_policy_path}`",
        f"- Policy import output: `{summary.policy_import_path}`",
        "- Prepare reviewed policy: `mosaic-rke prepare-license-policy-review --root .`",
        (
            "- Build policy import: "
            "`mosaic-rke build-license-review-import --root . "
            f"--policy {summary.reviewed_policy_path} --output {summary.policy_import_path}`"
        ),
        (
            "- Dry run policy import: "
            "`mosaic-rke apply-license-review --root . "
            f"--input {summary.policy_import_path} --dry-run`"
        ),
        "",
        (
            "This workbook is read-only. Fill reviewer decisions only in the reviewed "
            "policy JSON; do not edit this Markdown file or use it as an import file."
        ),
        "It intentionally lists only IDs, hashes, dates, statuses, and short title previews.",
        "",
        "## Policy Scope",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| source_type_counts | {_markdown_cell(summary.source_type_counts, max_chars=160)} |",
        f"| license_status_counts | {_markdown_cell(summary.license_status_counts, max_chars=160)} |",
        "",
    ]
    if summary.blockers:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in summary.blockers)
        lines.append("")
    lines.extend(
        [
            "## Sample Pending Source Rows",
            "",
            (
                f"The table shows the first {summary.sample_rows} pending rows. "
                "The full policy scope is bound by the matched rows fingerprint above."
            ),
            "",
            "| # | source_id | target_hash | publish_date | source_type | status | title_preview |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(row.get("index"), max_chars=12),
                    _markdown_cell(row.get("source_id"), max_chars=48),
                    _markdown_cell(row.get(TARGET_ROW_HASH_FIELD), max_chars=24),
                    _markdown_cell(row.get("publish_date"), max_chars=16),
                    _markdown_cell(row.get("source_type"), max_chars=40),
                    _markdown_cell(row.get("current_license_status"), max_chars=32),
                    _markdown_cell(row.get("title_preview"), max_chars=96),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def write_source_license_review_workbook(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    summary, rows = build_source_license_review_workbook(root_path)
    path = root_path / SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_source_license_review_workbook_markdown(summary, rows) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": len(rows), "blockers": len(summary.blockers)}


def write_source_license_policy_template(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    return _write_json(
        root_path / SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        build_source_license_policy_template(root_path),
    )


def write_source_license_reviewed_policy_starter(
    root: str | Path = ".",
    *,
    output_path: str | Path = SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    force: bool = False,
) -> SourceLicenseReviewedPolicyStarterResult:
    """Write a reviewer-editable policy starter without clobbering reviews."""
    root_path = Path(root)
    resolved_output_path = Path(output_path)
    if not resolved_output_path.is_absolute():
        resolved_output_path = root_path / resolved_output_path
    template = build_source_license_policy_template(root_path)
    workbook = write_source_license_review_workbook(root_path)
    exists = resolved_output_path.exists()
    blockers: list[str] = []
    if exists and not force:
        blockers.append(f"{resolved_output_path} already exists; pass --force to overwrite")
    if not blockers:
        _write_json(resolved_output_path, template)
    return SourceLicenseReviewedPolicyStarterResult(
        path=str(resolved_output_path),
        template_path=SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        workbook_path=str(workbook["path"]),
        workbook_rows=int(workbook["rows"]),
        force=force,
        written=not blockers,
        overwritten=exists and force and not blockers,
        blockers=tuple(blockers),
    )


def build_source_license_policy_import(
    root: str | Path,
    policy_path: str | Path,
    *,
    output_path: str | Path = DEFAULT_LICENSE_POLICY_IMPORT_PATH,
    dry_run: bool = False,
    write_report: bool = True,
) -> SourceLicensePolicyImportReport:
    """Build a sparse ``apply-license-review`` input from a signed policy file.

    This does not apply the decision. Reviewers must inspect the generated JSONL
    and pass it to ``apply-license-review`` to update the registry.
    """
    root_path = Path(root)
    resolved_policy_path = Path(policy_path)
    if not resolved_policy_path.is_absolute():
        resolved_policy_path = root_path / resolved_policy_path
    resolved_output_path = Path(output_path)
    if not resolved_output_path.is_absolute():
        resolved_output_path = root_path / resolved_output_path

    try:
        policy_payload = _load_policy(resolved_policy_path)
    except json.JSONDecodeError as exc:
        return _policy_rejection_report(
            root_path=root_path,
            resolved_policy_path=resolved_policy_path,
            resolved_output_path=resolved_output_path,
            dry_run=dry_run,
            blocker=f"source-license policy must contain valid JSON: {exc.msg}",
            write_report=write_report,
        )
    raw_review_rows, review_rows, review_row_blockers, total_review_rows = _load_review_template_rows(root_path)
    if not isinstance(policy_payload, Mapping):
        report = SourceLicensePolicyImportReport(
            report_id="RKE-SOURCE-LICENSE-POLICY-IMPORT-REPORT-20260606",
            policy_path=str(resolved_policy_path),
            target_review_path=LICENSE_REVIEW_TEMPLATE_PATH,
            output_path=str(resolved_output_path),
            dry_run=dry_run,
            accepted=False,
            total_review_rows=total_review_rows,
            matched_rows=0,
            output_rows=0,
            reviewer="",
            review_date="",
            approved_for_derived_claim_storage=None,
            approved_for_production_runtime=None,
            filters=SourceLicensePolicyFilters(),
            blockers=tuple(dict.fromkeys(("source-license policy must be object", *review_row_blockers))),
        )
        if write_report:
            _write_json(root_path / LICENSE_POLICY_IMPORT_REPORT_PATH, asdict(report))
        return report

    policy = policy_payload
    filters = _policy_filters(policy)
    reviewer_value = policy.get("reviewer")
    review_date_value = policy.get("review_date")
    reviewer = reviewer_value.strip() if isinstance(reviewer_value, str) else ""
    review_date = review_date_value.strip() if isinstance(review_date_value, str) else ""
    derived = policy.get("approved_for_derived_claim_storage")
    production = policy.get("approved_for_production_runtime")
    matched = [row for row in review_rows if _matches(row, filters)]
    output_rows = [_review_row(row, policy) for row in matched]
    matched_rows_fingerprint = _matched_rows_fingerprint(matched)
    publish_date_min, publish_date_max = _matched_publish_date_bounds(matched)

    blockers: list[str] = []
    blockers.extend(review_row_blockers)
    for field in _unexpected_policy_fields(policy):
        blockers.append(f"{field} unexpected in source-license policy import")
    for field in _forbidden_policy_fields(policy):
        blockers.append(f"{field} forbidden in source-license policy import")
    for field in ("reviewer", "review_date"):
        blockers.extend(_required_policy_string_failures(policy, field))
    blockers.extend(_iso_policy_date_failures(policy, "review_date"))
    for field in (
        "notes",
        "review_context_ref",
        "target_review_path",
        "publish_date_min",
        "publish_date_max",
    ):
        blockers.extend(_optional_policy_string_failures(policy, field))
    for field in ("publish_date_min", "publish_date_max"):
        blockers.extend(_iso_policy_date_failures(policy, field))
    blockers.extend(
        _optional_policy_date_range_failures(
            policy.get("publish_date_min"),
            policy.get("publish_date_max"),
            start_label="publish_date_min",
            end_label="publish_date_max",
        )
    )
    blockers.extend(_policy_filter_date_failures(policy))
    blockers.extend(_policy_filter_shape_failures(policy))
    if str(policy.get("target_review_path") or "").strip() != LICENSE_REVIEW_TEMPLATE_PATH:
        blockers.append(f"target_review_path must match {LICENSE_REVIEW_TEMPLATE_PATH}")
    if str(policy.get(MATCHED_ROWS_FINGERPRINT_FIELD) or "").strip() != matched_rows_fingerprint:
        blockers.append(f"{MATCHED_ROWS_FINGERPRINT_FIELD} does not match current matched rows")
    matched_row_count = policy.get("matched_row_count")
    if type(matched_row_count) is not int:
        blockers.append("matched_row_count must be integer")
    elif matched_row_count != len(matched):
        blockers.append("matched_row_count does not match current matched rows")
    if policy.get("publish_date_min") != publish_date_min:
        blockers.append("publish_date_min does not match current matched rows")
    if policy.get("publish_date_max") != publish_date_max:
        blockers.append("publish_date_max does not match current matched rows")
    if not isinstance(derived, bool):
        blockers.append("approved_for_derived_claim_storage must be boolean")
    if not isinstance(production, bool):
        blockers.append("approved_for_production_runtime must be boolean")
    if not matched:
        blockers.append("policy filters matched zero source-license rows")
    if not any(
        (
            filters.source_type,
            filters.current_license_status,
            filters.review_status,
            filters.publish_date_min,
            filters.publish_date_max,
            filters.source_id_prefix,
        )
    ):
        blockers.append("at least one policy filter is required")

    accepted = not blockers
    if accepted and not dry_run:
        _write_jsonl(resolved_output_path, output_rows)

    report = SourceLicensePolicyImportReport(
        report_id="RKE-SOURCE-LICENSE-POLICY-IMPORT-REPORT-20260606",
        policy_path=str(resolved_policy_path),
        target_review_path=LICENSE_REVIEW_TEMPLATE_PATH,
        output_path=str(resolved_output_path),
        dry_run=dry_run,
        accepted=accepted,
        total_review_rows=total_review_rows,
        matched_rows=len(matched),
        output_rows=0 if dry_run else len(output_rows) if accepted else 0,
        reviewer=reviewer,
        review_date=review_date,
        approved_for_derived_claim_storage=derived if isinstance(derived, bool) else None,
        approved_for_production_runtime=production if isinstance(production, bool) else None,
        filters=filters,
        blockers=tuple(blockers),
    )
    if write_report:
        _write_json(root_path / LICENSE_POLICY_IMPORT_REPORT_PATH, asdict(report))
    return report

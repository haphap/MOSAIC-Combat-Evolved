"""Batch export helpers for the manual RKE review gates.

The generated import templates are intentionally sparse: they identify pending
gold-set claims and source-license rows without duplicating long source text.
Reviewers should use the existing packets/source pool for context, then fill
the generated rows and import them with the controlled apply commands.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .license_policy_import import (
    SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
    write_source_license_policy_template,
    write_source_license_review_workbook,
)
from .manual_review_import import GOLD_BOOL_FIELDS, TARGET_ROW_HASH_FIELD, review_row_fingerprint


GOLD_REVIEW_TEMPLATE_PATH = "registry/gold_sets/tushare_research_reports.review_template.jsonl"
GOLD_REVIEW_PACKET_PATH = "registry/gold_sets/tushare_research_reports.review_packet.json"
GOLD_BATCH_IMPORT_TEMPLATE_PATH = "registry/review_batches/gold_set_next_import_template.jsonl"
GOLD_FULL_IMPORT_TEMPLATE_PATH = "registry/review_batches/gold_set_full_import_template.jsonl"
GOLD_REVIEW_WORKBOOK_MD_PATH = "registry/review_batches/gold_set_review_workbook.md"
GOLD_REVIEW_ASSIST_JSONL_PATH = "registry/review_batches/gold_set_review_assist.jsonl"
GOLD_REVIEW_ASSIST_MD_PATH = "registry/review_batches/gold_set_review_assist.md"
GOLD_REVIEW_EVIDENCE_JSONL_PATH = "registry/review_batches/gold_set_review_evidence.jsonl"
GOLD_REVIEW_EVIDENCE_MD_PATH = "registry/review_batches/gold_set_review_evidence.md"
GOLD_REVIEWED_IMPORT_PATH = "registry/review_batches/gold_set_reviewed.jsonl"
GOLD_FULL_REVIEWED_IMPORT_PATH = "registry/review_batches/gold_set_full_reviewed.jsonl"
LICENSE_REVIEW_TEMPLATE_PATH = "registry/compliance/tushare_license_review_template.jsonl"
LICENSE_REVIEW_PACKET_PATH = "registry/compliance/tushare_license_review_packet.json"
LICENSE_BATCH_IMPORT_TEMPLATE_PATH = "registry/review_batches/source_license_next_import_template.jsonl"
MANUAL_REVIEW_BATCH_STATUS_PATH = "registry/review_batches/manual_review_batch_status.json"


@dataclass(frozen=True)
class ReviewBatchExportSummary:
    review_kind: Literal["gold_set", "source_license"]
    target_path: str
    review_packet_path: str
    import_template_path: str
    full_import_template_path: str
    total_rows: int
    pending_rows: int
    batch_size: int
    exported_rows: int
    first_pending_id: str | None
    last_pending_id: str | None
    required_manual_fields: Sequence[str]
    dry_run_command: str
    apply_command: str


@dataclass(frozen=True)
class ManualReviewBatchStatus:
    status_id: str
    ready_for_manual_review: bool
    gold_set: ReviewBatchExportSummary
    source_license: ReviewBatchExportSummary
    generated_paths: Sequence[str]
    blockers: Sequence[str]


@dataclass(frozen=True)
class GoldReviewStarterResult:
    path: str
    template_path: str
    full: bool
    force: bool
    written: bool
    overwritten: bool
    rows: int
    blockers: Sequence[str]


@dataclass(frozen=True)
class GoldReviewWorkbookSummary:
    workbook_id: str
    path: str
    review_template_path: str
    full_import_template_path: str
    review_packet_path: str
    pending_rows: int
    row_count: int
    blockers: Sequence[str]


@dataclass(frozen=True)
class GoldReviewAssistSummary:
    assist_id: str
    jsonl_path: str
    markdown_path: str
    review_template_path: str
    reviewed_import_path: str
    row_count: int
    pending_rows: int
    blockers: Sequence[str]


@dataclass(frozen=True)
class GoldReviewEvidenceSummary:
    evidence_id: str
    jsonl_path: str
    markdown_path: str
    review_template_path: str
    reviewed_import_path: str
    requested_limit: int
    row_count: int
    evidence_rows: int
    missing_markdown_rows: int
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


def _load_review_rows(
    root_path: Path,
    relative_path: str,
    *,
    label: str,
) -> tuple[list[Any], list[Mapping[str, Any]], tuple[int, ...], tuple[str, ...], int]:
    path = root_path / relative_path
    if not path.exists():
        return [], [], (), (), 0

    raw_rows: list[Any] = []
    valid_rows: list[Mapping[str, Any]] = []
    invalid_row_numbers: list[int] = []
    parse_blockers: list[str] = []
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
                parse_blockers.append(f"{label} row {line_number} must contain valid JSON: {exc.msg}")
                continue
            raw_rows.append(row)
            if isinstance(row, Mapping):
                valid_rows.append(row)
            else:
                invalid_row_numbers.append(line_number)
    return raw_rows, valid_rows, tuple(invalid_row_numbers), tuple(parse_blockers), total_rows


def _gold_row_complete(row: Mapping[str, Any]) -> bool:
    return (
        bool(str(row.get("manual_claim_text") or "").strip())
        and all(isinstance(row.get(field), bool) for field in GOLD_BOOL_FIELDS)
        and bool(str(row.get("reviewer") or "").strip())
        and bool(str(row.get("review_date") or "").strip())
    )


def _license_row_complete(row: Mapping[str, Any]) -> bool:
    return (
        isinstance(row.get("approved_for_derived_claim_storage"), bool)
        and isinstance(row.get("approved_for_production_runtime"), bool)
        and bool(str(row.get("reviewer") or "").strip())
        and bool(str(row.get("review_date") or "").strip())
    )


def _short_review_preview(value: Any, *, max_chars: int = 72) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _markdown_cell(value: Any, *, max_chars: int = 72) -> str:
    if isinstance(value, (list, tuple, set)):
        text = ", ".join(str(item) for item in value)
    elif isinstance(value, Mapping):
        text = json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
    else:
        text = str(value or "")
    text = _short_review_preview(text, max_chars=max_chars)
    return text.replace("|", "\\|") or "-"


def _gold_template_row(row: Mapping[str, Any]) -> dict[str, Any]:
    proposed_claim_text = str(row.get("proposed_claim_text") or "").strip()
    return {
        "claim_id": str(row.get("claim_id") or ""),
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        "source_id": str(row.get("source_id") or ""),
        "source_span_id": str(row.get("source_span_id") or ""),
        "document_id": str(row.get("document_id") or row.get("source_id") or ""),
        "gold_set_domain": str(row.get("gold_set_domain") or "other"),
        "gold_set_domains": tuple(row.get("gold_set_domains") or ()),
        "gold_set_domain_matches": dict(row.get("gold_set_domain_matches") or {}),
        "gold_set_domain_scores": dict(row.get("gold_set_domain_scores") or {}),
        "review_context_ref": GOLD_REVIEW_PACKET_PATH,
        "target_review_path": GOLD_REVIEW_TEMPLATE_PATH,
        "proposed_claim_text": _short_review_preview(proposed_claim_text),
        "proposed_claim_text_truncated": len(proposed_claim_text) > 72,
        "proposed_claim_type": row.get("proposed_claim_type"),
        "proposed_extraction_confidence_bin": row.get("proposed_extraction_confidence_bin"),
        "proposed_gold_set_domain": row.get("proposed_gold_set_domain"),
        "proposed_gold_set_domains": tuple(row.get("proposed_gold_set_domains") or ()),
        "proposed_direction": row.get("proposed_direction"),
        "proposed_cause_variables": tuple(row.get("proposed_cause_variables") or ()),
        "proposed_target_variables": tuple(row.get("proposed_target_variables") or ()),
        "proposed_review_risk_flags": tuple(row.get("proposed_review_risk_flags") or ()),
        "proposed_source_start_char": row.get("proposed_source_start_char"),
        "proposed_source_end_char": row.get("proposed_source_end_char"),
        "proposed_source_span_ref_id": row.get("proposed_source_span_ref_id"),
        "proposed_source_text_hash": row.get("proposed_source_text_hash"),
        "proposed_verifier_status": row.get("proposed_verifier_status"),
        "manual_claim_text": "",
        "claim_correct": None,
        "source_span_supports_claim": None,
        "direction_correct": None,
        "target_correct": None,
        "horizon_correct": None,
        "variable_mapping_correct": None,
        "unsupported_field_false_grounded": None,
        "reviewer": "",
        "review_date": "",
        "review_notes": "",
    }


def _gold_workbook_row(index: int, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "index": index,
        "claim_id": str(row.get("claim_id") or ""),
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        "source_id": str(row.get("source_id") or ""),
        "gold_set_domain": str(row.get("gold_set_domain") or "other"),
        "proposed_claim_type": str(row.get("proposed_claim_type") or ""),
        "proposed_direction": str(row.get("proposed_direction") or ""),
        "proposed_extraction_confidence_bin": str(
            row.get("proposed_extraction_confidence_bin") or ""
        ),
        "proposed_variables": tuple(
            str(variable)
            for variable in (
                *(row.get("proposed_cause_variables") or ()),
                *(row.get("proposed_target_variables") or ()),
            )
            if str(variable).strip()
        ),
        "proposed_source_offsets": (
            f"{row.get('proposed_source_start_char')}-{row.get('proposed_source_end_char')}"
        ),
        "proposed_source_text_hash": str(row.get("proposed_source_text_hash") or ""),
        "proposed_source_span_ref_id": str(row.get("proposed_source_span_ref_id") or ""),
        "proposed_review_risk_flags": tuple(row.get("proposed_review_risk_flags") or ()),
        "claim_preview": _short_review_preview(row.get("proposed_claim_text"), max_chars=72),
    }


def _gold_assist_row(index: int, row: Mapping[str, Any]) -> dict[str, Any]:
    proposed_claim_text = str(row.get("proposed_claim_text") or "").strip()
    proposed_variables = tuple(
        str(variable)
        for variable in (
            *(row.get("proposed_cause_variables") or ()),
            *(row.get("proposed_target_variables") or ()),
        )
        if str(variable).strip()
    )
    return {
        "assist_kind": "gold_review_assist_not_import",
        "not_apply_gold_review_input": True,
        "index": index,
        "claim_id": str(row.get("claim_id") or ""),
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        "source_id": str(row.get("source_id") or ""),
        "source_span_id": str(row.get("source_span_id") or ""),
        "document_id": str(row.get("document_id") or row.get("source_id") or ""),
        "gold_set_domain": str(row.get("gold_set_domain") or "other"),
        "review_context_ref": GOLD_REVIEW_PACKET_PATH,
        "target_review_path": GOLD_REVIEW_TEMPLATE_PATH,
        "reviewed_import_path": GOLD_FULL_REVIEWED_IMPORT_PATH,
        "proposed_claim_text_preview": _short_review_preview(
            proposed_claim_text,
            max_chars=72,
        ),
        "proposed_claim_text_truncated": len(proposed_claim_text) > 72,
        "suggested_manual_claim_text_preview": _short_review_preview(
            proposed_claim_text,
            max_chars=72,
        ),
        "suggested_manual_claim_text_hash": review_row_fingerprint(
            {"manual_claim_text": proposed_claim_text}
        ),
        "proposed_claim_type": row.get("proposed_claim_type"),
        "proposed_direction": row.get("proposed_direction"),
        "proposed_extraction_confidence_bin": row.get(
            "proposed_extraction_confidence_bin"
        ),
        "proposed_variables": proposed_variables,
        "proposed_source_offsets": (
            f"{row.get('proposed_source_start_char')}-{row.get('proposed_source_end_char')}"
        ),
        "proposed_source_text_hash": str(row.get("proposed_source_text_hash") or ""),
        "proposed_source_span_ref_id": str(
            row.get("proposed_source_span_ref_id") or ""
        ),
        "proposed_review_risk_flags": tuple(
            row.get("proposed_review_risk_flags") or ()
        ),
        "human_required_fields": (
            "manual_claim_text",
            *GOLD_BOOL_FIELDS,
            "reviewer",
            "review_date",
            "review_notes",
        ),
        "human_review_required": True,
    }


def build_gold_review_workbook(
    root: str | Path = ".",
) -> tuple[GoldReviewWorkbookSummary, tuple[Mapping[str, Any], ...]]:
    root_path = Path(root)
    raw_rows, rows, invalid_rows, parse_blockers, total_rows = _load_review_rows(
        root_path,
        GOLD_REVIEW_TEMPLATE_PATH,
        label="gold-set review",
    )
    pending_rows = [row for row in rows if not _gold_row_complete(row)]
    workbook_rows = tuple(
        _gold_workbook_row(index, row)
        for index, row in enumerate(pending_rows, 1)
    )
    blockers: list[str] = [*parse_blockers]
    if invalid_rows:
        blockers.append(
            "gold-set review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_rows)
        )
    if not raw_rows:
        blockers.append("gold-set review template is missing or empty")
    elif not rows:
        blockers.append("gold-set review template has no valid review rows")
    return (
        GoldReviewWorkbookSummary(
            workbook_id="RKE-GOLD-REVIEW-WORKBOOK-20260606",
            path=GOLD_REVIEW_WORKBOOK_MD_PATH,
            review_template_path=GOLD_REVIEW_TEMPLATE_PATH,
            full_import_template_path=GOLD_FULL_IMPORT_TEMPLATE_PATH,
            review_packet_path=GOLD_REVIEW_PACKET_PATH,
            pending_rows=len(pending_rows),
            row_count=total_rows,
            blockers=tuple(blockers),
        ),
        workbook_rows,
    )


def render_gold_review_workbook_markdown(
    summary: GoldReviewWorkbookSummary,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# RKE Gold Review Workbook",
        "",
        f"- Workbook ID: {summary.workbook_id}",
        f"- Pending rows: {summary.pending_rows}",
        f"- Review template: `{summary.review_template_path}`",
        f"- Full import template: `{summary.full_import_template_path}`",
        f"- Review packet: `{summary.review_packet_path}`",
        "- Prepare reviewed scratch: `mosaic-rke prepare-gold-review --root . --full`",
        (
            "- Dry run reviewed scratch: "
            "`mosaic-rke apply-gold-review --root . "
            f"--input {GOLD_FULL_REVIEWED_IMPORT_PATH} --dry-run`"
        ),
        "",
        "This workbook is a read-only checklist. Fill reviewer decisions only in the reviewed JSONL scratch file.",
        "",
    ]
    if summary.blockers:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in summary.blockers)
        lines.append("")
    lines.extend(
        [
            "## Pending Claims",
            "",
            (
                "| # | claim_id | target_hash | domain | source_id | offsets | type | "
                "direction | confidence | variables | risk_flags | claim_preview |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(row.get("index"), max_chars=12),
                    _markdown_cell(row.get("claim_id"), max_chars=48),
                    _markdown_cell(row.get(TARGET_ROW_HASH_FIELD), max_chars=24),
                    _markdown_cell(row.get("gold_set_domain"), max_chars=24),
                    _markdown_cell(row.get("source_id"), max_chars=48),
                    _markdown_cell(row.get("proposed_source_offsets"), max_chars=24),
                    _markdown_cell(row.get("proposed_claim_type"), max_chars=32),
                    _markdown_cell(row.get("proposed_direction"), max_chars=16),
                    _markdown_cell(row.get("proposed_extraction_confidence_bin"), max_chars=16),
                    _markdown_cell(row.get("proposed_variables"), max_chars=72),
                    _markdown_cell(row.get("proposed_review_risk_flags"), max_chars=72),
                    _markdown_cell(row.get("claim_preview"), max_chars=72),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def write_gold_review_workbook(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    summary, rows = build_gold_review_workbook(root_path)
    path = root_path / GOLD_REVIEW_WORKBOOK_MD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_gold_review_workbook_markdown(summary, rows) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": len(rows), "blockers": len(summary.blockers)}


def build_gold_review_assist(
    root: str | Path = ".",
) -> tuple[GoldReviewAssistSummary, tuple[Mapping[str, Any], ...]]:
    root_path = Path(root)
    raw_rows, rows, invalid_rows, parse_blockers, _ = _load_review_rows(
        root_path,
        GOLD_REVIEW_TEMPLATE_PATH,
        label="gold-set review",
    )
    pending_rows = [row for row in rows if not _gold_row_complete(row)]
    assist_rows = tuple(
        _gold_assist_row(index, row) for index, row in enumerate(pending_rows, 1)
    )
    blockers: list[str] = [*parse_blockers]
    if invalid_rows:
        blockers.append(
            "gold-set review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_rows)
        )
    if not raw_rows:
        blockers.append("gold-set review template is missing or empty")
    elif not rows:
        blockers.append("gold-set review template has no valid review rows")
    return (
        GoldReviewAssistSummary(
            assist_id="RKE-GOLD-REVIEW-ASSIST-20260606",
            jsonl_path=GOLD_REVIEW_ASSIST_JSONL_PATH,
            markdown_path=GOLD_REVIEW_ASSIST_MD_PATH,
            review_template_path=GOLD_REVIEW_TEMPLATE_PATH,
            reviewed_import_path=GOLD_FULL_REVIEWED_IMPORT_PATH,
            row_count=len(assist_rows),
            pending_rows=len(pending_rows),
            blockers=tuple(blockers),
        ),
        assist_rows,
    )


def render_gold_review_assist_markdown(
    summary: GoldReviewAssistSummary,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# RKE Gold Review Assist",
        "",
        f"- Assist ID: {summary.assist_id}",
        f"- Pending rows: {summary.pending_rows}",
        f"- Review template: `{summary.review_template_path}`",
        f"- Reviewed import target: `{summary.reviewed_import_path}`",
        f"- JSONL assist: `{summary.jsonl_path}`",
        "",
        "This file is machine-generated review assistance only. It is not an import file and does not satisfy the manual gold-set gate.",
        "Use it to copy short claim previews and hashes while filling the reviewed JSONL scratch file by hand.",
        "",
    ]
    if summary.blockers:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in summary.blockers)
        lines.append("")
    lines.extend(
        [
            "## Assist Rows",
            "",
            (
                "| # | claim_id | target_hash | domain | type | direction | "
                "variables | risk_flags | manual_claim_preview |"
            ),
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(row.get("index"), max_chars=12),
                    _markdown_cell(row.get("claim_id"), max_chars=48),
                    _markdown_cell(row.get(TARGET_ROW_HASH_FIELD), max_chars=24),
                    _markdown_cell(row.get("gold_set_domain"), max_chars=24),
                    _markdown_cell(row.get("proposed_claim_type"), max_chars=32),
                    _markdown_cell(row.get("proposed_direction"), max_chars=16),
                    _markdown_cell(row.get("proposed_variables"), max_chars=72),
                    _markdown_cell(row.get("proposed_review_risk_flags"), max_chars=72),
                    _markdown_cell(
                        row.get("suggested_manual_claim_text_preview"),
                        max_chars=72,
                    ),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def write_gold_review_assist(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    summary, rows = build_gold_review_assist(root_path)
    jsonl_result = _write_jsonl(root_path / GOLD_REVIEW_ASSIST_JSONL_PATH, rows)
    md_path = root_path / GOLD_REVIEW_ASSIST_MD_PATH
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(
        render_gold_review_assist_markdown(summary, rows) + "\n",
        encoding="utf-8",
    )
    return {
        "jsonl": str(jsonl_result["path"]),
        "markdown": str(md_path),
        "rows": len(rows),
        "blockers": len(summary.blockers),
    }


def _load_jsonl_mapping_rows(path: Path) -> tuple[list[Mapping[str, Any]], tuple[str, ...]]:
    if not path.exists():
        return [], (f"{path} missing",)
    rows: list[Mapping[str, Any]] = []
    blockers: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                blockers.append(f"{path} row {line_number} must contain valid JSON: {exc.msg}")
                continue
            if not isinstance(row, Mapping):
                blockers.append(f"{path} row {line_number} must be object")
                continue
            rows.append(row)
    return rows, tuple(blockers)


def _gold_evidence_priority_score(row: Mapping[str, Any]) -> int:
    score = 0
    risk_flags = tuple(str(flag) for flag in row.get("proposed_review_risk_flags") or ())
    if "manual_review_required" in risk_flags:
        score += 2
    if "sentence_fallback_requires_context_synthesis" in risk_flags:
        score += 2
    if str(row.get("proposed_direction") or "") in {"ambiguous", "neutral"}:
        score += 2
    if str(row.get("proposed_extraction_confidence_bin") or "") == "low":
        score += 1
    if not row.get("proposed_target_variables"):
        score += 1
    if not row.get("proposed_cause_variables"):
        score += 1
    return score


def _gold_evidence_terms(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw_terms: list[str] = []
    for value in (
        row.get("proposed_claim_text"),
        row.get("gold_set_domain"),
        row.get("proposed_claim_type"),
        row.get("proposed_direction"),
        *(row.get("proposed_cause_variables") or ()),
        *(row.get("proposed_target_variables") or ()),
    ):
        text = str(value or "").strip()
        if not text:
            continue
        raw_terms.extend(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_\-/ ]{2,}", text))
    seen: list[str] = []
    for term in raw_terms:
        normalized = " ".join(str(term or "").split())
        if not normalized or normalized in seen or len(normalized) > 64:
            continue
        seen.append(normalized)
    return tuple(seen[:24])


def _gold_source_offset_snippet(
    source_row: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    max_chars: int = 900,
) -> dict[str, Any] | None:
    abstract = str(source_row.get("abstract") or "")
    if not abstract:
        return None
    start_raw = row.get("proposed_source_start_char")
    end_raw = row.get("proposed_source_end_char")
    try:
        start = int(start_raw)
        end = int(end_raw)
    except (TypeError, ValueError):
        start = -1
        end = -1
    if start < 0 or end <= start or start >= len(abstract):
        start = 0
        end = min(len(abstract), max_chars)
    snippet_start = max(0, start - max_chars // 3)
    snippet_end = min(len(abstract), max(end + max_chars // 3, snippet_start + max_chars))
    return {
        "source": "tushare_abstract_offsets",
        "start_char": snippet_start,
        "end_char": snippet_end,
        "snippet": " ".join(abstract[snippet_start:snippet_end].split()),
    }


def _gold_markdown_snippets(
    markdown_text: str,
    terms: Sequence[str],
    *,
    max_snippets: int = 1,
    max_chars: int = 900,
) -> tuple[dict[str, Any], ...]:
    snippets: list[dict[str, Any]] = []
    for term in terms:
        match = re.search(re.escape(term), markdown_text, re.IGNORECASE)
        if match is None:
            continue
        start = max(0, int(match.start()) - max_chars // 3)
        end = min(len(markdown_text), int(match.end()) + max_chars)
        snippets.append(
            {
                "source": "local_markdown",
                "matched_term": term,
                "start_char": start,
                "end_char": end,
                "snippet": " ".join(markdown_text[start:end].split()),
            }
        )
        if len(snippets) >= max_snippets:
            break
    return tuple(snippets)


def _gold_markdown_text(
    root_path: Path,
    metadata_row: Mapping[str, Any] | None,
) -> tuple[str, str, bool]:
    if metadata_row is None:
        return "", "", False
    markdown = metadata_row.get("markdown")
    if not isinstance(markdown, Mapping):
        return "", "", False
    markdown_path_text = str(markdown.get("path") or "")
    if not markdown_path_text:
        return "", "", False
    markdown_path = Path(markdown_path_text)
    if not markdown_path.is_absolute():
        markdown_path = root_path / markdown_path
    if not markdown_path.exists():
        return markdown_path_text, "", False
    return markdown_path_text, markdown_path.read_text(encoding="utf-8", errors="ignore"), True


def _gold_evidence_row(
    index: int,
    row: Mapping[str, Any],
    *,
    root_path: Path,
    source_by_id: Mapping[str, Mapping[str, Any]],
    metadata_by_source: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    source_id = str(row.get("source_id") or "")
    source_row = source_by_id.get(source_id, {})
    metadata_row = metadata_by_source.get(source_id)
    markdown_path_text, markdown_text, markdown_exists = _gold_markdown_text(root_path, metadata_row)
    terms = _gold_evidence_terms(row)
    abstract_snippet = _gold_source_offset_snippet(source_row, row)
    snippets: list[dict[str, Any]] = []
    if abstract_snippet is not None:
        snippets.append(abstract_snippet)
    snippets.extend(_gold_markdown_snippets(markdown_text, terms))
    has_source_evidence = bool(snippets)
    proposed_claim_text = str(row.get("proposed_claim_text") or "").strip()
    proposed_direction = str(row.get("proposed_direction") or "").strip()
    suggested_decision = {
        "claim_correct": True if has_source_evidence and proposed_claim_text else None,
        "source_span_supports_claim": True if has_source_evidence else None,
        "direction_correct": None if proposed_direction in {"", "ambiguous"} else True,
        "target_correct": None,
        "horizon_correct": None,
        "variable_mapping_correct": None,
        "unsupported_field_false_grounded": False,
    }
    tags: list[str] = []
    if not has_source_evidence:
        tags.append("source_evidence_unverified")
    if not markdown_exists:
        tags.append("markdown_missing")
    if proposed_direction == "ambiguous":
        tags.append("direction_ambiguous")
    if "sentence_fallback_requires_context_synthesis" in tuple(row.get("proposed_review_risk_flags") or ()):
        tags.append("context_synthesis_required")
    return {
        "evidence_kind": "gold_review_evidence_not_import",
        "not_apply_gold_review_input": True,
        "human_review_required": True,
        "index": index,
        "priority_score": _gold_evidence_priority_score(row),
        "claim_id": str(row.get("claim_id") or ""),
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        "source_id": source_id,
        "source_span_id": str(row.get("source_span_id") or ""),
        "document_id": str(row.get("document_id") or row.get("source_id") or ""),
        "gold_set_domain": str(row.get("gold_set_domain") or "other"),
        "proposed_claim_text": proposed_claim_text,
        "proposed_claim_type": row.get("proposed_claim_type"),
        "proposed_direction": proposed_direction,
        "proposed_cause_variables": tuple(row.get("proposed_cause_variables") or ()),
        "proposed_target_variables": tuple(row.get("proposed_target_variables") or ()),
        "proposed_review_risk_flags": tuple(row.get("proposed_review_risk_flags") or ()),
        "proposed_source_offsets": (
            f"{row.get('proposed_source_start_char')}-{row.get('proposed_source_end_char')}"
        ),
        "proposed_source_text_hash": str(row.get("proposed_source_text_hash") or ""),
        "metadata_title_preview": _short_review_preview(
            (metadata_row or source_row).get("title"),
            max_chars=160,
        ),
        "markdown_path": markdown_path_text,
        "markdown_exists": markdown_exists,
        "evidence_terms": terms,
        "evidence_snippets": tuple(snippets),
        "suggested_manual_claim_text": proposed_claim_text,
        "suggested_review_decision": suggested_decision,
        "suggested_manual_error_tags": tuple(tags),
        "suggested_review_notes": (
            "Review local abstract/markdown evidence before copying decisions into "
            "gold_set_full_reviewed.jsonl. Draft suggestion only; not an import row."
        ),
        "reviewed_import_path": GOLD_FULL_REVIEWED_IMPORT_PATH,
    }


def build_gold_review_evidence(
    root: str | Path = ".",
    *,
    limit: int = 50,
) -> tuple[GoldReviewEvidenceSummary, tuple[Mapping[str, Any], ...]]:
    root_path = Path(root)
    raw_rows, template_rows, invalid_rows, parse_blockers, _ = _load_review_rows(
        root_path,
        GOLD_REVIEW_TEMPLATE_PATH,
        label="gold-set review",
    )
    reviewed_path = root_path / GOLD_FULL_REVIEWED_IMPORT_PATH
    if reviewed_path.exists():
        reviewed_rows, reviewed_blockers = _load_jsonl_mapping_rows(reviewed_path)
    else:
        reviewed_rows, reviewed_blockers = [], ()
    source_rows, source_blockers = _load_jsonl_mapping_rows(
        root_path / "registry/sources/tushare_research_reports.jsonl"
    )
    metadata_rows, metadata_blockers = _load_jsonl_mapping_rows(
        root_path / "registry/report_intelligence/report_metadata.jsonl"
    )
    reviewed_by_id = {
        str(row.get("claim_id") or ""): row
        for row in reviewed_rows
        if str(row.get("claim_id") or "").strip()
    }
    source_by_id = {
        str(row.get("source_id") or ""): row
        for row in source_rows
        if str(row.get("source_id") or "").strip()
    }
    metadata_by_source = {
        str(row.get("source_id") or ""): row
        for row in metadata_rows
        if str(row.get("source_id") or "").strip()
    }
    pending_rows = [
        row
        for row in template_rows
        if not _gold_row_complete(reviewed_by_id.get(str(row.get("claim_id") or ""), row))
    ]
    prioritized_rows = sorted(
        enumerate(pending_rows, 1),
        key=lambda item: (-_gold_evidence_priority_score(item[1]), item[0]),
    )[: max(0, int(limit))]
    evidence_rows = tuple(
        _gold_evidence_row(
            index,
            row,
            root_path=root_path,
            source_by_id=source_by_id,
            metadata_by_source=metadata_by_source,
        )
        for index, row in prioritized_rows
    )
    blockers: list[str] = [*parse_blockers, *reviewed_blockers, *source_blockers, *metadata_blockers]
    if invalid_rows:
        blockers.append(
            "gold-set review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_rows)
        )
    if not raw_rows:
        blockers.append("gold-set review template is missing or empty")
    elif not template_rows:
        blockers.append("gold-set review template has no valid review rows")
    if not source_rows:
        blockers.append("tushare research report source rows are missing or empty")
    missing_markdown_rows = sum(1 for row in evidence_rows if not row.get("markdown_exists"))
    return (
        GoldReviewEvidenceSummary(
            evidence_id="RKE-GOLD-REVIEW-EVIDENCE-20260612",
            jsonl_path=GOLD_REVIEW_EVIDENCE_JSONL_PATH,
            markdown_path=GOLD_REVIEW_EVIDENCE_MD_PATH,
            review_template_path=GOLD_REVIEW_TEMPLATE_PATH,
            reviewed_import_path=GOLD_FULL_REVIEWED_IMPORT_PATH,
            requested_limit=max(0, int(limit)),
            row_count=len(evidence_rows),
            evidence_rows=sum(1 for row in evidence_rows if row.get("evidence_snippets")),
            missing_markdown_rows=missing_markdown_rows,
            blockers=tuple(blockers),
        ),
        evidence_rows,
    )


def render_gold_review_evidence_markdown(
    summary: GoldReviewEvidenceSummary,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# RKE Gold Review Evidence Draft",
        "",
        f"- Evidence ID: {summary.evidence_id}",
        f"- Rows: {summary.row_count}",
        f"- Review template: `{summary.review_template_path}`",
        f"- Reviewed import target: `{summary.reviewed_import_path}`",
        "",
        "This private file contains local source snippets and machine suggestions for human review. It is not an import file.",
        "Do not commit this file. Confirm decisions before copying them into the reviewed JSONL scratch file.",
        "",
    ]
    if summary.blockers:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in summary.blockers)
        lines.append("")
    for row in rows:
        lines.extend(
            [
                f"## {row.get('index')}. {row.get('claim_id')}",
                "",
                f"- Source: `{row.get('source_id')}`",
                f"- Domain: {row.get('gold_set_domain') or '-'}",
                f"- Direction: {row.get('proposed_direction') or '-'}",
                f"- Priority score: {row.get('priority_score')}",
                f"- Suggested tags: {_markdown_cell(row.get('suggested_manual_error_tags'), max_chars=200)}",
                "",
                "Suggested manual claim text:",
                "",
                "> " + _short_review_preview(row.get("suggested_manual_claim_text"), max_chars=900),
                "",
                "Suggested decision:",
                "",
                "```json",
                json.dumps(row.get("suggested_review_decision"), ensure_ascii=False, indent=2),
                "```",
                "",
                "Evidence snippets:",
                "",
            ]
        )
        snippets = tuple(row.get("evidence_snippets") or ())
        if not snippets:
            lines.append("- No local evidence snippet found.")
        for snippet in snippets:
            snippet_map = dict(snippet) if isinstance(snippet, Mapping) else {}
            label = snippet_map.get("source") or "unknown"
            term = snippet_map.get("matched_term")
            if term:
                label = f"{label}; matched `{term}`"
            lines.extend(
                [
                    f"- {label}",
                    "",
                    "> " + _short_review_preview(snippet_map.get("snippet"), max_chars=900),
                    "",
                ]
            )
    return "\n".join(lines)


def write_gold_review_evidence(
    root: str | Path = ".",
    *,
    limit: int = 50,
) -> dict[str, Any]:
    root_path = Path(root)
    summary, rows = build_gold_review_evidence(root_path, limit=limit)
    jsonl_result = _write_jsonl(root_path / GOLD_REVIEW_EVIDENCE_JSONL_PATH, rows)
    md_path = root_path / GOLD_REVIEW_EVIDENCE_MD_PATH
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(
        render_gold_review_evidence_markdown(summary, rows) + "\n",
        encoding="utf-8",
    )
    return {
        "jsonl": str(jsonl_result["path"]),
        "markdown": str(md_path),
        "rows": len(rows),
        "evidence_rows": summary.evidence_rows,
        "missing_markdown_rows": summary.missing_markdown_rows,
        "blockers": len(summary.blockers),
    }


def _license_template_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": str(row.get("source_id") or ""),
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        "source_type": str(row.get("source_type") or ""),
        "title": str(row.get("title") or ""),
        "publish_date": str(row.get("publish_date") or ""),
        "current_license_status": str(row.get("current_license_status") or ""),
        "review_context_ref": LICENSE_REVIEW_PACKET_PATH,
        "target_review_path": LICENSE_REVIEW_TEMPLATE_PATH,
        "approved_for_derived_claim_storage": None,
        "approved_for_production_runtime": None,
        "reviewer": "",
        "review_date": "",
        "notes": "",
    }


def _summary(
    *,
    review_kind: Literal["gold_set", "source_license"],
    target_path: str,
    packet_path: str,
    import_template_path: str,
    full_import_template_path: str = "",
    total_rows: int,
    pending_ids: Sequence[str],
    batch_size: int,
    exported_rows: int,
    required_fields: Sequence[str],
) -> ReviewBatchExportSummary:
    command = (
        "mosaic-rke apply-gold-review"
        if review_kind == "gold_set"
        else "mosaic-rke apply-license-review"
    )
    return ReviewBatchExportSummary(
        review_kind=review_kind,
        target_path=target_path,
        review_packet_path=packet_path,
        import_template_path=import_template_path,
        full_import_template_path=full_import_template_path,
        total_rows=total_rows,
        pending_rows=len(pending_ids),
        batch_size=batch_size,
        exported_rows=exported_rows,
        first_pending_id=pending_ids[0] if pending_ids else None,
        last_pending_id=pending_ids[-1] if pending_ids else None,
        required_manual_fields=tuple(required_fields),
        dry_run_command=f"{command} --root . --input {import_template_path} --dry-run",
        apply_command=f"{command} --root . --input {import_template_path}",
    )


def build_manual_review_batch_status(
    root: str | Path = ".",
    *,
    gold_batch_size: int = 50,
    license_batch_size: int = 50,
) -> tuple[ManualReviewBatchStatus, tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    if gold_batch_size <= 0:
        raise ValueError("gold_batch_size must be positive")
    if license_batch_size <= 0:
        raise ValueError("license_batch_size must be positive")

    root_path = Path(root)
    raw_gold_rows, gold_rows, invalid_gold_rows, gold_parse_blockers, gold_total_rows = _load_review_rows(
        root_path,
        GOLD_REVIEW_TEMPLATE_PATH,
        label="gold-set review",
    )
    (
        raw_license_rows,
        license_rows,
        invalid_license_rows,
        license_parse_blockers,
        license_total_rows,
    ) = _load_review_rows(
        root_path,
        LICENSE_REVIEW_TEMPLATE_PATH,
        label="source license review",
    )

    pending_gold = [row for row in gold_rows if not _gold_row_complete(row)]
    pending_license = [row for row in license_rows if not _license_row_complete(row)]
    gold_batch = tuple(_gold_template_row(row) for row in pending_gold[:gold_batch_size])
    license_batch = tuple(_license_template_row(row) for row in pending_license[:license_batch_size])
    gold_pending_ids = tuple(str(row.get("claim_id") or "") for row in pending_gold)
    license_pending_ids = tuple(str(row.get("source_id") or "") for row in pending_license)

    gold_summary = _summary(
        review_kind="gold_set",
        target_path=GOLD_REVIEW_TEMPLATE_PATH,
        packet_path=GOLD_REVIEW_PACKET_PATH,
        import_template_path=GOLD_BATCH_IMPORT_TEMPLATE_PATH,
        full_import_template_path=GOLD_FULL_IMPORT_TEMPLATE_PATH,
        total_rows=gold_total_rows,
        pending_ids=gold_pending_ids,
        batch_size=gold_batch_size,
        exported_rows=len(gold_batch),
        required_fields=(
            "manual_claim_text",
            *GOLD_BOOL_FIELDS,
            "reviewer",
            "review_date",
            "review_notes",
        ),
    )
    license_summary = _summary(
        review_kind="source_license",
        target_path=LICENSE_REVIEW_TEMPLATE_PATH,
        packet_path=LICENSE_REVIEW_PACKET_PATH,
        import_template_path=LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
        total_rows=license_total_rows,
        pending_ids=license_pending_ids,
        batch_size=license_batch_size,
        exported_rows=len(license_batch),
        required_fields=(
            "approved_for_derived_claim_storage",
            "approved_for_production_runtime",
            "reviewer",
            "review_date",
            "notes",
        ),
    )

    blockers: list[str] = []
    blockers.extend(gold_parse_blockers)
    blockers.extend(license_parse_blockers)
    if invalid_gold_rows:
        blockers.append(
            "gold-set review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_gold_rows)
        )
    if invalid_license_rows:
        blockers.append(
            "source license review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_license_rows)
        )
    if not raw_gold_rows:
        blockers.append("gold-set review template is missing or empty")
    elif not gold_rows:
        blockers.append("gold-set review template has no valid review rows")
    if not raw_license_rows:
        blockers.append("source-license review template is missing or empty")
    elif not license_rows:
        blockers.append("source-license review template has no valid review rows")
    if gold_pending_ids:
        blockers.append(f"{len(gold_pending_ids)} gold-set review rows still pending")
    if license_pending_ids:
        blockers.append(f"{len(license_pending_ids)} source-license review rows still pending")

    status = ManualReviewBatchStatus(
        status_id="RKE-MANUAL-REVIEW-BATCH-STATUS-20260606",
        ready_for_manual_review=bool(
            gold_rows
            and license_rows
            and not invalid_gold_rows
            and not invalid_license_rows
            and not gold_parse_blockers
            and not license_parse_blockers
        ),
        gold_set=gold_summary,
        source_license=license_summary,
        generated_paths=(
            GOLD_BATCH_IMPORT_TEMPLATE_PATH,
            GOLD_FULL_IMPORT_TEMPLATE_PATH,
            GOLD_REVIEW_WORKBOOK_MD_PATH,
            GOLD_REVIEW_ASSIST_JSONL_PATH,
            GOLD_REVIEW_ASSIST_MD_PATH,
            LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
            SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
            SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
            MANUAL_REVIEW_BATCH_STATUS_PATH,
        ),
        blockers=tuple(blockers),
    )
    return status, gold_batch, license_batch


def write_manual_review_batches(
    root: str | Path = ".",
    *,
    gold_batch_size: int = 50,
    license_batch_size: int = 50,
) -> dict[str, Any]:
    root_path = Path(root)
    status, gold_batch, license_batch = build_manual_review_batch_status(
        root_path,
        gold_batch_size=gold_batch_size,
        license_batch_size=license_batch_size,
    )
    _, gold_rows, _, _, _ = _load_review_rows(
        root_path,
        GOLD_REVIEW_TEMPLATE_PATH,
        label="gold-set review",
    )
    gold_full = tuple(_gold_template_row(row) for row in gold_rows if not _gold_row_complete(row))
    gold_result = _write_jsonl(root_path / GOLD_BATCH_IMPORT_TEMPLATE_PATH, gold_batch)
    gold_full_result = _write_jsonl(root_path / GOLD_FULL_IMPORT_TEMPLATE_PATH, gold_full)
    gold_workbook_result = write_gold_review_workbook(root_path)
    gold_assist_result = write_gold_review_assist(root_path)
    license_result = _write_jsonl(root_path / LICENSE_BATCH_IMPORT_TEMPLATE_PATH, license_batch)
    license_policy_template_result = write_source_license_policy_template(root_path)
    license_workbook_result = write_source_license_review_workbook(root_path)
    status_result = _write_json(root_path / MANUAL_REVIEW_BATCH_STATUS_PATH, asdict(status))
    return {
        "status": str(status_result["path"]),
        "gold_set_import_template": str(gold_result["path"]),
        "gold_set_full_import_template": str(gold_full_result["path"]),
        "gold_set_review_workbook": str(gold_workbook_result["path"]),
        "gold_set_review_assist_jsonl": str(gold_assist_result["jsonl"]),
        "gold_set_review_assist_markdown": str(gold_assist_result["markdown"]),
        "source_license_import_template": str(license_result["path"]),
        "source_license_policy_template": str(license_policy_template_result["path"]),
        "source_license_review_workbook": str(license_workbook_result["path"]),
        "gold_set_rows": int(gold_result["rows"]),
        "gold_set_full_rows": int(gold_full_result["rows"]),
        "gold_set_review_workbook_rows": int(gold_workbook_result["rows"]),
        "gold_set_review_assist_rows": int(gold_assist_result["rows"]),
        "source_license_rows": int(license_result["rows"]),
        "source_license_review_workbook_rows": int(license_workbook_result["rows"]),
    }


def write_gold_review_starter(
    root: str | Path = ".",
    *,
    output_path: str | Path | None = None,
    full: bool = False,
    force: bool = False,
    gold_batch_size: int = 50,
) -> GoldReviewStarterResult:
    """Write a reviewer-editable gold-set JSONL starter without clobbering reviews."""
    if gold_batch_size <= 0:
        raise ValueError("gold_batch_size must be positive")

    root_path = Path(root)
    relative_output = (
        output_path
        if output_path is not None
        else GOLD_FULL_REVIEWED_IMPORT_PATH
        if full
        else GOLD_REVIEWED_IMPORT_PATH
    )
    resolved_output_path = Path(relative_output)
    if not resolved_output_path.is_absolute():
        resolved_output_path = root_path / resolved_output_path

    if full:
        _, gold_rows, _, _, _ = _load_review_rows(
            root_path,
            GOLD_REVIEW_TEMPLATE_PATH,
            label="gold-set review",
        )
        rows = tuple(_gold_template_row(row) for row in gold_rows if not _gold_row_complete(row))
        template_path = GOLD_FULL_IMPORT_TEMPLATE_PATH
    else:
        _, rows, _ = build_manual_review_batch_status(
            root_path,
            gold_batch_size=gold_batch_size,
        )
        template_path = GOLD_BATCH_IMPORT_TEMPLATE_PATH

    exists = resolved_output_path.exists()
    blockers: list[str] = []
    if exists and not force:
        blockers.append(f"{resolved_output_path} already exists; pass --force to overwrite")
    if not blockers:
        _write_jsonl(resolved_output_path, rows)
    return GoldReviewStarterResult(
        path=str(resolved_output_path),
        template_path=template_path,
        full=full,
        force=force,
        written=not blockers,
        overwritten=exists and force and not blockers,
        rows=len(rows),
        blockers=tuple(blockers),
    )

"""Batch export helpers for the manual RKE review gates.

The generated import templates are intentionally sparse: they identify pending
gold-set claims and source-license rows without duplicating long source text.
Reviewers should use the existing packets/source pool for context, then fill
the generated rows and import them with the controlled apply commands.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .claim_text_filters import is_gold_candidate_noise_text, is_non_research_claim_text
from .license_policy_import import (
    SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
    write_source_license_policy_template,
    write_source_license_review_workbook,
)
from .manual_review_import import GOLD_BOOL_FIELDS, TARGET_ROW_HASH_FIELD, review_row_fingerprint
from .report_intelligence import _gold_review_quality_gap_targets_from_summary
from .review_gates import summarize_gold_set_review
from .temp_paths import rke_tmp_root


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
GOLD_REVIEW_SUMMARY_PATH = "registry/gold_sets/tushare_research_reports.review_summary.json"
LICENSE_REVIEW_TEMPLATE_PATH = "registry/compliance/tushare_license_review_template.jsonl"
LICENSE_REVIEW_PACKET_PATH = "registry/compliance/tushare_license_review_packet.json"
LICENSE_BATCH_IMPORT_TEMPLATE_PATH = "registry/review_batches/source_license_next_import_template.jsonl"
MANUAL_REVIEW_BATCH_STATUS_PATH = "registry/review_batches/manual_review_batch_status.json"
GOLD_REVIEW_MAX_ROWS_PER_SOURCE = 1


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
    reviewed_failures: bool
    force: bool
    offset: int
    written: bool
    overwritten: bool
    rows: int
    selected_priority_score_counts: Mapping[str, int]
    selected_priority_reason_counts: Mapping[str, int]
    blockers: Sequence[str]
    backed_up_existing_output: bool = False
    backup_path: str = ""


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
    selection_source: str = "priority_sorted_pending"
    review_input_path: str = ""


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
    selection_source: str = "priority_sorted_pending"
    review_input_path: str = ""
    quality_gap_targets: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class GoldReviewEvidenceSummary:
    evidence_id: str
    jsonl_path: str
    markdown_path: str
    review_template_path: str
    reviewed_import_path: str
    requested_limit: int
    requested_offset: int
    row_count: int
    evidence_rows: int
    missing_markdown_rows: int
    selected_priority_score_counts: Mapping[str, int]
    selected_priority_reason_counts: Mapping[str, int]
    blockers: Sequence[str]
    selection_source: str = "priority_sorted_pending"
    review_input_path: str = ""
    quality_gap_targets: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class GoldReviewBackfillResult:
    path: str
    prior_review_path: str
    output_path: str
    dry_run: bool
    written: bool
    row_count: int
    matched_prior_rows: int
    updated_rows: int
    copied_field_count: int
    preserved_existing_field_count: int
    complete_after_backfill_rows: int
    blockers: Sequence[str]
    backed_up_existing_output: bool = False
    backup_path: str = ""


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


def _read_mapping_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _gold_quality_gap_targets_from_summary(
    root_path: Path,
    summary: Any,
) -> Mapping[str, Any] | None:
    if getattr(summary, "quality_gap_targets", None):
        return summary.quality_gap_targets
    public_quality_gap_targets = _gold_review_quality_gap_targets_from_summary(
        _read_mapping_json(root_path / GOLD_REVIEW_SUMMARY_PATH)
    )
    if public_quality_gap_targets:
        return public_quality_gap_targets
    return _gold_review_quality_gap_targets_from_summary(asdict(summary))


def _manual_review_backup_path(root_path: Path, source_path: Path) -> Path:
    try:
        relative = source_path.resolve().relative_to(root_path.resolve())
        label = "__".join(relative.parts)
    except ValueError:
        label = source_path.name
    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "_", label)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return rke_tmp_root() / "review-backups" / f"{timestamp}_{safe_label}"


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


_GENERIC_COMPANY_SUBJECT_RE = re.compile(r"(^|[，,。；;\s])公司(?=\S)")
_GENERIC_COMPANY_EFFECT_RE = re.compile(r"(?:推动|带动|支撑|改善|影响|增厚|强化|拖累)公司")


def _generic_company_stock_target(row: Mapping[str, Any], claim_text: str) -> bool:
    target_variables = {str(value) for value in row.get("proposed_target_variables") or ()}
    if "stock_forward_excess_return" not in target_variables:
        return False
    return bool(
        _GENERIC_COMPANY_SUBJECT_RE.search(claim_text)
        or _GENERIC_COMPANY_EFFECT_RE.search(claim_text)
    )


def gold_candidate_reviewable(row: Mapping[str, Any]) -> bool:
    if row.get("proposed_candidate_current") is False:
        return False
    proposed_claim_text = str(row.get("proposed_claim_text") or "").strip()
    if not proposed_claim_text:
        return False
    proposed_flags = {str(flag) for flag in row.get("proposed_review_risk_flags") or ()}
    if "candidate_unavailable" in proposed_flags:
        return False
    if "low_mechanism_keyword_support" in proposed_flags:
        return False
    if "canonical_variable_mapping_needed" in proposed_flags:
        return False
    if "direction_conflict_requires_review" in proposed_flags:
        return False
    if proposed_flags & {
        "sentence_fallback_not_reviewable",
        "sentence_fallback_requires_context_synthesis",
        "original_markdown_sentence_fallback",
        "fragment_or_sentence_level_claim",
        "full_text_thesis_logic_chain_missing",
        "layered_regime_or_company_logic_missing",
        "economic_mechanism_missing",
        "mosaic_agent_trace_missing",
        "stock_target_missing_company_subject",
        "stock_prediction_or_valuation_logic_missing",
    }:
        return False
    if "manual claim required" in proposed_claim_text.lower():
        return False
    if str(row.get("proposed_direction") or "").strip() in {
        "",
        "ambiguous",
        "neutral",
        "unknown",
    }:
        return False
    if not tuple(row.get("proposed_cause_variables") or ()):
        return False
    if not tuple(row.get("proposed_target_variables") or ()):
        return False
    if _generic_company_stock_target(row, proposed_claim_text):
        return False
    return not is_gold_candidate_noise_text(proposed_claim_text)


def _gold_candidate_reviewable(row: Mapping[str, Any]) -> bool:
    return gold_candidate_reviewable(row)


def _gold_reviewable_pending_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_rows_per_source: int = GOLD_REVIEW_MAX_ROWS_PER_SOURCE,
) -> list[Mapping[str, Any]]:
    pending: list[Mapping[str, Any]] = []
    source_counts: Counter[str] = Counter()
    for row in rows:
        if _gold_row_complete(row) or not _gold_candidate_reviewable(row):
            continue
        source_id = str(row.get("source_id") or row.get("document_id") or "")
        if max_rows_per_source > 0 and source_id and source_counts[source_id] >= max_rows_per_source:
            continue
        pending.append(row)
        if source_id:
            source_counts[source_id] += 1
    return pending


def _gold_reviewed_failure_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_rows_per_source: int = 0,
) -> list[Mapping[str, Any]]:
    failed: list[Mapping[str, Any]] = []
    source_counts: Counter[str] = Counter()
    for row in rows:
        if not _gold_row_complete(row):
            continue
        has_failed_decision = (
            any(
                row.get(field) is False
                for field in GOLD_BOOL_FIELDS
                if field != "unsupported_field_false_grounded"
            )
            or row.get("unsupported_field_false_grounded") is True
        )
        if not has_failed_decision:
            continue
        source_id = str(row.get("source_id") or row.get("document_id") or "")
        if max_rows_per_source > 0 and source_id and source_counts[source_id] >= max_rows_per_source:
            continue
        failed.append(row)
        if source_id:
            source_counts[source_id] += 1
    return failed


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


def _layer_trace_preview(row: Mapping[str, Any]) -> str:
    layers = row.get("proposed_research_layers")
    if not isinstance(layers, Mapping):
        return ""
    parts: list[str] = []
    for key, label in (
        ("macro_regime", "macro"),
        ("industry_regime", "industry"),
        ("company_layer", "company"),
        ("valuation_or_forecast_layer", "valuation"),
        ("mechanism_layer", "mechanism"),
    ):
        layer = layers.get(key)
        if isinstance(layer, Mapping) and layer.get("present") is True:
            parts.append(label)
    return ",".join(parts)


def _agent_trace_preview(row: Mapping[str, Any]) -> str:
    trace = row.get("proposed_mosaic_agent_trace")
    if not isinstance(trace, Mapping):
        return ""
    agents: list[str] = []
    for field in (
        "macro_agents",
        "sector_agents",
        "company_or_single_name_layer",
        "valuation_layer",
    ):
        for value in trace.get(field) or ():
            text = str(value or "").strip()
            if text and text not in agents:
                agents.append(text)
    return ", ".join(agents)


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
        "proposed_research_layers": dict(row.get("proposed_research_layers") or {}),
        "proposed_mosaic_agent_trace": dict(row.get("proposed_mosaic_agent_trace") or {}),
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


GOLD_MANUAL_REVIEW_FIELDS = (
    "manual_claim_text",
    *GOLD_BOOL_FIELDS,
    "reviewer",
    "review_date",
    "review_notes",
)


def _gold_manual_value_missing(field: str, value: Any) -> bool:
    if field in GOLD_BOOL_FIELDS:
        return not isinstance(value, bool)
    return not str(value or "").strip()


def _gold_prior_review_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("claim_id") or "").strip(),
        str(row.get("document_id") or row.get("source_id") or "").strip(),
    )


def _gold_prior_review_complete(row: Mapping[str, Any]) -> bool:
    return all(
        not _gold_manual_value_missing(field, row.get(field))
        for field in GOLD_MANUAL_REVIEW_FIELDS
        if field != "review_notes"
    )


def backfill_gold_review_from_prior(
    root: str | Path = ".",
    *,
    input_path: str | Path = GOLD_REVIEWED_IMPORT_PATH,
    prior_review_path: str | Path = GOLD_REVIEW_TEMPLATE_PATH,
    output_path: str | Path | None = None,
    dry_run: bool = True,
    allow_missing_prior: bool = False,
) -> GoldReviewBackfillResult:
    """Backfill a gold review scratch from existing human-reviewed rows.

    This only copies manual review fields from prior rows that match the current
    scratch by claim id and document/source id. Existing manual field values in
    the scratch are preserved, so this cannot silently replace a reviewer edit.
    """
    root_path = Path(root)
    input_text = str(input_path)
    prior_text = str(prior_review_path)
    output_text = str(output_path or input_path)
    input_resolved = Path(input_path)
    if not input_resolved.is_absolute():
        input_resolved = root_path / input_resolved
    output_resolved = Path(output_text)
    if not output_resolved.is_absolute():
        output_resolved = root_path / output_resolved

    _, input_rows, input_invalid_rows, input_parse_blockers, input_total = (
        _load_review_rows(root_path, input_text, label="gold-set backfill input")
    )
    _, prior_rows, prior_invalid_rows, prior_parse_blockers, _ = _load_review_rows(
        root_path,
        prior_text,
        label="gold-set prior review",
    )
    blockers: list[str] = [*input_parse_blockers, *prior_parse_blockers]
    if input_invalid_rows:
        blockers.append(
            "gold-set backfill input row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in input_invalid_rows)
        )
    if prior_invalid_rows:
        blockers.append(
            "gold-set prior review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in prior_invalid_rows)
        )
    if input_total == 0:
        blockers.append("gold-set backfill input is missing or empty")
    if not prior_rows:
        blockers.append("gold-set prior review rows are missing or empty")

    prior_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    duplicate_prior_keys: set[tuple[str, str]] = set()
    for row in prior_rows:
        key = _gold_prior_review_key(row)
        if not key[0]:
            continue
        if key in prior_by_key:
            duplicate_prior_keys.add(key)
        else:
            prior_by_key[key] = row
    if duplicate_prior_keys:
        blockers.append(
            "gold-set prior review has duplicate claim/document keys: "
            + ", ".join(
                f"{claim_id}/{document_id or '-'}"
                for claim_id, document_id in sorted(duplicate_prior_keys)
            )
        )

    updated_rows: list[dict[str, Any]] = []
    matched_prior_rows = 0
    copied_field_count = 0
    preserved_existing_field_count = 0
    changed_row_count = 0
    complete_after_backfill_rows = 0
    for row_index, row in enumerate(input_rows, 1):
        updated = dict(row)
        key = _gold_prior_review_key(row)
        if not key[0]:
            blockers.append(f"gold-set backfill input row {row_index}.claim_id: required")
            updated_rows.append(updated)
            continue
        prior = prior_by_key.get(key)
        if prior is None:
            updated_rows.append(updated)
            if not allow_missing_prior:
                blockers.append(
                    f"gold-set backfill input row {row_index}.claim_id: "
                    f"no prior reviewed row for {key[0]}/{key[1] or '-'}"
                )
            continue
        matched_prior_rows += 1
        if not _gold_prior_review_complete(prior):
            blockers.append(
                f"gold-set prior review row for {key[0]}/{key[1] or '-'} "
                "is missing required manual fields"
            )
            updated_rows.append(updated)
            continue
        row_changed = False
        for field in GOLD_MANUAL_REVIEW_FIELDS:
            if _gold_manual_value_missing(field, updated.get(field)):
                updated[field] = prior.get(field)
                copied_field_count += 1
                row_changed = True
            else:
                preserved_existing_field_count += 1
        if row_changed:
            changed_row_count += 1
        if _gold_row_complete(updated):
            complete_after_backfill_rows += 1
        updated_rows.append(updated)

    backed_up_existing_output = False
    backup_path = ""
    written = False
    if not blockers and not dry_run:
        if output_resolved.exists():
            backup = _manual_review_backup_path(root_path, output_resolved)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(output_resolved.read_bytes())
            backed_up_existing_output = True
            backup_path = str(backup)
        _write_jsonl(output_resolved, updated_rows)
        written = True

    return GoldReviewBackfillResult(
        path=str(input_resolved),
        prior_review_path=str(root_path / prior_text),
        output_path=str(output_resolved),
        dry_run=dry_run,
        written=written,
        row_count=len(input_rows),
        matched_prior_rows=matched_prior_rows,
        updated_rows=changed_row_count,
        copied_field_count=copied_field_count,
        preserved_existing_field_count=preserved_existing_field_count,
        complete_after_backfill_rows=complete_after_backfill_rows,
        blockers=tuple(blockers),
        backed_up_existing_output=backed_up_existing_output,
        backup_path=backup_path,
    )


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
        "proposed_layer_trace": _layer_trace_preview(row),
        "proposed_agent_trace": _agent_trace_preview(row),
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
        "proposed_layer_trace": _layer_trace_preview(row),
        "proposed_agent_trace": _agent_trace_preview(row),
        "human_required_fields": (
            "manual_claim_text",
            *GOLD_BOOL_FIELDS,
            "reviewer",
            "review_date",
            "review_notes",
        ),
        "human_review_required": True,
    }


def _select_gold_review_rows_for_input(
    root_path: Path,
    template_rows: Sequence[Mapping[str, Any]],
    review_input_path: str | Path | None,
) -> tuple[list[Mapping[str, Any]], list[str], str, str]:
    if review_input_path is None:
        return (
            _gold_reviewable_pending_rows(template_rows),
            [],
            "priority_sorted_pending",
            "",
        )

    review_input_text = str(review_input_path)
    input_raw, input_rows, input_invalid_rows, input_parse_blockers, _ = (
        _load_review_rows(
            root_path,
            review_input_text,
            label="gold-set review input",
        )
    )
    blockers: list[str] = [*input_parse_blockers]
    if input_invalid_rows:
        blockers.append(
            "gold-set review input row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in input_invalid_rows)
        )
    if not input_raw:
        blockers.append("gold-set review input is missing or empty")

    template_by_id = {
        str(row.get("claim_id") or ""): row
        for row in template_rows
        if str(row.get("claim_id") or "").strip()
    }
    selected_rows: list[Mapping[str, Any]] = []
    seen_claim_ids: set[str] = set()
    for row_index, input_row in enumerate(input_rows, 1):
        claim_id = str(input_row.get("claim_id") or "").strip()
        if not claim_id:
            blockers.append(f"gold-set review input row {row_index}.claim_id: required")
            continue
        if claim_id in seen_claim_ids:
            blockers.append(
                f"gold-set review input row {row_index}.claim_id: duplicate {claim_id}"
            )
            continue
        seen_claim_ids.add(claim_id)
        template_row = template_by_id.get(claim_id)
        if template_row is None:
            blockers.append(
                f"gold-set review input row {row_index}.claim_id: no matching target review row"
            )
            continue
        expected_hash = review_row_fingerprint(template_row)
        input_hash = str(input_row.get(TARGET_ROW_HASH_FIELD) or "").strip()
        if input_hash and input_hash != expected_hash:
            blockers.append(
                f"gold-set review input row {row_index}.{TARGET_ROW_HASH_FIELD}: "
                "does not match target review row"
            )
        selected_rows.append(template_row)
    return selected_rows, blockers, "review_input", review_input_text


def build_gold_review_workbook(
    root: str | Path = ".",
    *,
    review_input_path: str | Path | None = None,
) -> tuple[GoldReviewWorkbookSummary, tuple[Mapping[str, Any], ...]]:
    root_path = Path(root)
    raw_rows, rows, invalid_rows, parse_blockers, total_rows = _load_review_rows(
        root_path,
        GOLD_REVIEW_TEMPLATE_PATH,
        label="gold-set review",
    )
    pending_rows, input_blockers, selection_source, review_input_text = (
        _select_gold_review_rows_for_input(root_path, rows, review_input_path)
    )
    workbook_rows = tuple(
        _gold_workbook_row(index, row)
        for index, row in enumerate(pending_rows, 1)
    )
    blockers: list[str] = [*parse_blockers, *input_blockers]
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
            selection_source=selection_source,
            review_input_path=review_input_text,
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
        f"- Selection source: `{summary.selection_source}`",
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
    if summary.review_input_path:
        lines.insert(8, f"- Review input: `{summary.review_input_path}`")
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
                "direction | confidence | layers | agents | variables | risk_flags | claim_preview |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
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
                    _markdown_cell(row.get("proposed_layer_trace"), max_chars=48),
                    _markdown_cell(row.get("proposed_agent_trace"), max_chars=72),
                    _markdown_cell(row.get("proposed_variables"), max_chars=72),
                    _markdown_cell(row.get("proposed_review_risk_flags"), max_chars=72),
                    _markdown_cell(row.get("claim_preview"), max_chars=72),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def write_gold_review_workbook(
    root: str | Path = ".",
    *,
    review_input_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    summary, rows = build_gold_review_workbook(
        root_path,
        review_input_path=review_input_path,
    )
    path = root_path / GOLD_REVIEW_WORKBOOK_MD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_gold_review_workbook_markdown(summary, rows) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": len(rows), "blockers": len(summary.blockers)}


def build_gold_review_assist(
    root: str | Path = ".",
    *,
    review_input_path: str | Path | None = None,
) -> tuple[GoldReviewAssistSummary, tuple[Mapping[str, Any], ...]]:
    root_path = Path(root)
    raw_rows, rows, invalid_rows, parse_blockers, _ = _load_review_rows(
        root_path,
        GOLD_REVIEW_TEMPLATE_PATH,
        label="gold-set review",
    )
    pending_rows, input_blockers, selection_source, review_input_text = (
        _select_gold_review_rows_for_input(root_path, rows, review_input_path)
    )
    assist_rows = tuple(
        _gold_assist_row(index, row) for index, row in enumerate(pending_rows, 1)
    )
    blockers: list[str] = [*parse_blockers, *input_blockers]
    gold_summary = summarize_gold_set_review(root_path)
    quality_gap_targets = _gold_quality_gap_targets_from_summary(
        root_path,
        gold_summary,
    )
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
            selection_source=selection_source,
            review_input_path=review_input_text,
            quality_gap_targets=quality_gap_targets,
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
        f"- Selection source: `{summary.selection_source}`",
        f"- Review template: `{summary.review_template_path}`",
        f"- Reviewed import target: `{summary.reviewed_import_path}`",
        f"- JSONL assist: `{summary.jsonl_path}`",
        "",
        "This file is machine-generated review assistance only. It is not an import file and does not satisfy the manual gold-set gate.",
        "Use it to copy short claim previews and hashes while filling the reviewed JSONL scratch file by hand.",
        "",
    ]
    if summary.review_input_path:
        lines.insert(8, f"- Review input: `{summary.review_input_path}`")
    if summary.blockers:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in summary.blockers)
        lines.append("")
    if summary.quality_gap_targets:
        lines.extend(["## Quality Gate Gap Targets", ""])
        lines.append(
            "Aggregate only; these counts contain no source text and are not import decisions."
        )
        lines.append("")
        document_gap = summary.quality_gap_targets.get("sample_size_documents", {})
        claim_gap = summary.quality_gap_targets.get("sample_size_claims", {})
        if isinstance(document_gap, Mapping):
            lines.append(
                "- Documents: "
                f"{document_gap.get('current_count')} / {document_gap.get('threshold')} "
                f"(need +{document_gap.get('minimum_additional_count')})"
            )
        if isinstance(claim_gap, Mapping):
            lines.append(
                "- Claims: "
                f"{claim_gap.get('current_count')} / {claim_gap.get('threshold')} "
                f"(need +{claim_gap.get('minimum_additional_count')})"
            )
        metrics = summary.quality_gap_targets.get("metrics", {})
        if isinstance(metrics, Mapping):
            for metric, target in metrics.items():
                if not isinstance(target, Mapping) or target.get("is_passing") is True:
                    continue
                if target.get("operator") == ">=":
                    lines.append(
                        "- "
                        f"{metric}: {target.get('current_rate')} / {target.get('threshold')} "
                        f"(pass count {target.get('current_pass_count')}/"
                        f"{target.get('required_pass_count')}, need +"
                        f"{target.get('minimum_additional_pass_count_if_denominator_unchanged')})"
                    )
                else:
                    lines.append(
                        "- "
                        f"{metric}: {target.get('current_rate')} / {target.get('threshold')} "
                        f"(flag count {target.get('current_true_count')}/"
                        f"{target.get('max_allowed_true_count')}, excess "
                        f"{target.get('minimum_excess_true_count_if_denominator_unchanged')})"
                    )
        lines.append("")
    lines.extend(
        [
            "## Assist Rows",
            "",
            (
                "| # | claim_id | target_hash | domain | type | direction | "
                "layers | agents | variables | risk_flags | manual_claim_preview |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|---|",
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
                    _markdown_cell(row.get("proposed_layer_trace"), max_chars=48),
                    _markdown_cell(row.get("proposed_agent_trace"), max_chars=72),
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


def write_gold_review_assist(
    root: str | Path = ".",
    *,
    review_input_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    summary, rows = build_gold_review_assist(
        root_path,
        review_input_path=review_input_path,
    )
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
        "selection_source": summary.selection_source,
        "review_input_path": summary.review_input_path,
        "quality_gap_targets": summary.quality_gap_targets,
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


def _gold_evidence_priority_reasons(row: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    risk_flags = tuple(str(flag) for flag in row.get("proposed_review_risk_flags") or ())
    if "manual_review_required" in risk_flags:
        reasons.append("manual_review_required")
    if "sentence_fallback_requires_context_synthesis" in risk_flags:
        reasons.append("context_synthesis_required")
    if "forecast_mapping_insufficient" in risk_flags:
        reasons.append("forecast_mapping_insufficient")
    if "long_candidate_sentence" in risk_flags:
        reasons.append("long_candidate_sentence")
    if str(row.get("proposed_direction") or "") in {"ambiguous", "neutral"}:
        reasons.append("ambiguous_or_neutral_direction")
    if str(row.get("proposed_extraction_confidence_bin") or "") == "low":
        reasons.append("low_extraction_confidence")
    if not row.get("proposed_target_variables"):
        reasons.append("missing_target_variables")
    if not row.get("proposed_cause_variables"):
        reasons.append("missing_cause_variables")
    return tuple(reasons)


GOLD_EVIDENCE_PRIORITY_REASON_WEIGHTS: Mapping[str, int] = {
    "manual_review_required": 2,
    "context_synthesis_required": 2,
    "forecast_mapping_insufficient": 2,
    "ambiguous_or_neutral_direction": 2,
    "long_candidate_sentence": 1,
    "low_extraction_confidence": 1,
    "missing_target_variables": 1,
    "missing_cause_variables": 1,
}


def _gold_evidence_priority_score(row: Mapping[str, Any]) -> int:
    return sum(
        GOLD_EVIDENCE_PRIORITY_REASON_WEIGHTS.get(reason, 0)
        for reason in _gold_evidence_priority_reasons(row)
    )


def _gold_priority_counts(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    score_counts = Counter(str(_gold_evidence_priority_score(row)) for row in rows)
    reason_counts = Counter(
        reason for row in rows for reason in _gold_evidence_priority_reasons(row)
    )
    return dict(sorted(score_counts.items())), dict(sorted(reason_counts.items()))


def _gold_evidence_terms(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw_terms: list[str] = []
    for value in (
        row.get("proposed_claim_text"),
        row.get("gold_set_domain"),
        row.get("proposed_claim_type"),
        row.get("proposed_direction"),
        _layer_trace_preview(row),
        _agent_trace_preview(row),
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


GOLD_POSITIVE_DIRECTION_TERMS = (
    "看好",
    "受益",
    "有望",
    "改善",
    "修复",
    "增长",
    "提升",
    "上行",
    "上涨",
    "扩张",
    "回升",
    "提振",
    "跑赢",
    "优于",
    "强于",
    "超额收益",
)
GOLD_NEGATIVE_DIRECTION_TERMS = (
    "承压",
    "下滑",
    "下降",
    "下行",
    "回落",
    "恶化",
    "亏损",
    "收窄",
    "走弱",
    "低于预期",
    "不及预期",
    "压力",
    "拖累",
    "压制",
    "减弱",
    "放缓",
    "跑输",
    "弱于",
)
GOLD_MAPPING_RISK_FLAGS = {
    "canonical_variable_mapping_needed",
}
GOLD_GROUNDING_RISK_FLAGS = {
    "forecast_mapping_insufficient",
    "forecast_not_testable",
    "not_source_grounded",
}
GOLD_STOCK_TARGET_TERMS = (
    "公司",
    "股价",
    "目标价",
    "归母",
    "净利润",
    "营收",
    "收入",
    "盈利",
    "利润",
    "现金流",
    "市占率",
    "订单",
    "毛利",
    "EPS",
)
GOLD_INDUSTRY_TARGET_TERMS = (
    "行业",
    "板块",
    "产业链",
    "景气",
    "市场",
    "供需",
    "运价",
    "油运",
    "航运",
    "ETF",
)
GOLD_STRONG_FORECAST_TERMS = (
    "看好",
    "有望",
    "预计",
    "预期",
    "未来",
    "后续",
    "将",
    "建议",
    "目标价",
    "维持",
    "上调",
    "下调",
    "承压",
    "受益",
    "驱动",
    "带动",
    "开启",
)
GOLD_EXPLICIT_HORIZON_TERMS = (
    "短期",
    "中期",
    "长期",
    "中长期",
    "未来",
    "后续",
    "2026",
    "2027",
    "2028",
    "三年",
    "两年",
    "一年",
)
GOLD_HISTORICAL_FACT_TERMS = (
    "本月",
    "当月",
    "环比",
    "同比",
    "26Q1",
    "25Q4",
    "24Q4",
    "2026年5月",
)


def _matched_gold_direction_terms(
    text: str,
    terms: Sequence[str],
    *,
    limit: int = 8,
) -> tuple[str, ...]:
    normalized = str(text or "")
    hits: list[str] = []
    for term in terms:
        if term in normalized and term not in hits:
            hits.append(term)
        if len(hits) >= limit:
            break
    return tuple(hits)


def _gold_direction_text_diagnostics(
    text: str,
    proposed_direction: str,
) -> dict[str, Any]:
    positive_hits = _matched_gold_direction_terms(text, GOLD_POSITIVE_DIRECTION_TERMS)
    negative_hits = _matched_gold_direction_terms(text, GOLD_NEGATIVE_DIRECTION_TERMS)
    direction = str(proposed_direction or "").strip()
    if direction not in {"positive", "negative"}:
        status = "unsupported_direction"
        needs_review = True
    elif positive_hits and negative_hits:
        status = "mixed_direction_terms"
        needs_review = True
    elif direction == "positive" and negative_hits and not positive_hits:
        status = "positive_label_negative_text"
        needs_review = True
    elif direction == "negative" and positive_hits and not negative_hits:
        status = "negative_label_positive_text"
        needs_review = True
    elif not positive_hits and not negative_hits:
        status = "no_explicit_direction_terms"
        needs_review = False
    else:
        status = "text_terms_aligned"
        needs_review = False
    return {
        "proposed_direction": direction,
        "positive_term_hits": positive_hits,
        "negative_term_hits": negative_hits,
        "status": status,
        "needs_review": needs_review,
    }


def _gold_term_hits(text: str, terms: Sequence[str], *, limit: int = 12) -> tuple[str, ...]:
    normalized = str(text or "")
    hits: list[str] = []
    for term in terms:
        if term in normalized and term not in hits:
            hits.append(term)
        if len(hits) >= limit:
            break
    return tuple(hits)


def _gold_expected_cause_variables(text: str) -> tuple[str, ...]:
    expected: list[str] = []

    def append(variable: str) -> None:
        if variable not in expected:
            expected.append(variable)

    if _gold_term_hits(
        text,
        (
            "需求",
            "订单",
            "市场规模",
            "增长",
            "复苏",
            "景气",
            "运价",
            "销量",
        ),
    ):
        append("industry_demand_cycle")
    if _gold_term_hits(text, ("供给", "产能", "库存", "短缺", "瓶颈", "运力", "投产")):
        append("industry_supply_constraint")
    if _gold_term_hits(text, ("收入", "营收", "盈利", "利润", "现金流", "回款", "毛利", "市占率")):
        append("company_fundamental_momentum")
    if _gold_term_hits(text, ("铜", "铝", "锂", "黄金", "金价", "铝价", "铜价", "油价", "原油")):
        append("commodity_price_cycle")
    if _gold_term_hits(
        text,
        ("美联储", "联储", "FOMC", "美国通胀", "加息", "降息", "美元指数", "美元汇率", "美债"),
    ):
        append("global_dollar_liquidity_pressure")
    if _gold_term_hits(text, ("地缘", "关税", "出口管制", "贸易摩擦")):
        append("trade_friction_intensity")
    if _gold_term_hits(text, ("政策", "监管", "补贴", "供给侧改革")):
        append("industry_policy_catalyst")
    if _gold_term_hits(text, ("技术", "创新", "研发", "产品迭代")):
        append("technology_innovation_cycle")
    if _gold_term_hits(text, ("竞争", "同质化", "价格战", "竞品")):
        append("competitive_intensity_pressure")
    return tuple(expected)


def _gold_variable_mapping_diagnostics(
    row: Mapping[str, Any],
    proposed_flags: Sequence[str],
) -> dict[str, Any]:
    cause_variables = tuple(
        str(item)
        for item in row.get("proposed_cause_variables") or ()
        if str(item).strip()
    )
    target_variables = tuple(
        str(item)
        for item in row.get("proposed_target_variables") or ()
        if str(item).strip()
    )
    flag_set = {str(flag) for flag in proposed_flags}
    blockers = []
    if not cause_variables:
        blockers.append("missing_cause_variables")
    if not target_variables:
        blockers.append("missing_target_variables")
    blockers.extend(sorted(flag_set & GOLD_MAPPING_RISK_FLAGS))
    claim_text = str(row.get("proposed_claim_text") or "")
    expected_cause_variables = _gold_expected_cause_variables(claim_text)
    missing_expected = tuple(
        variable for variable in expected_cause_variables if variable not in cause_variables
    )
    questionable: list[str] = []
    if "commodity_price_cycle" in cause_variables and not _gold_term_hits(
        claim_text,
        ("铜", "铝", "锂", "黄金", "金价", "铝价", "铜价", "油价", "原油", "商品", "大宗"),
    ):
        questionable.append("commodity_price_cycle")
    if "competitive_intensity_pressure" in cause_variables and not _gold_term_hits(
        claim_text,
        (
            "竞争",
            "同质化",
            "价格战",
            "竞品",
        ),
    ):
        questionable.append("competitive_intensity_pressure")
    return {
        "cause_variable_count": len(cause_variables),
        "target_variable_count": len(target_variables),
        "cause_variables": cause_variables,
        "target_variables": target_variables,
        "expected_cause_variables": expected_cause_variables,
        "missing_expected_cause_variables": missing_expected,
        "questionable_cause_variables": tuple(questionable),
        "mapping_risk_flags": tuple(sorted(flag_set & GOLD_MAPPING_RISK_FLAGS)),
        "blockers": tuple(dict.fromkeys(blockers)),
        "needs_review": bool(blockers or missing_expected or questionable),
    }


def _gold_target_diagnostics(row: Mapping[str, Any]) -> dict[str, Any]:
    text = str(row.get("proposed_claim_text") or "")
    target_variables = tuple(
        str(item)
        for item in row.get("proposed_target_variables") or ()
        if str(item).strip()
    )
    stock_hits = _gold_term_hits(text, GOLD_STOCK_TARGET_TERMS)
    industry_hits = _gold_term_hits(text, GOLD_INDUSTRY_TARGET_TERMS)
    forecast_hits = _gold_term_hits(text, GOLD_STRONG_FORECAST_TERMS)
    historical_hits = _gold_term_hits(text, GOLD_HISTORICAL_FACT_TERMS)
    blockers: list[str] = []
    suggested: bool | None = None
    status = "needs_human_review"
    if not target_variables:
        blockers.append("missing_target_variables")
        status = "missing_target_variables"
    elif "stock_forward_excess_return" in target_variables:
        if historical_hits and not forecast_hits:
            blockers.append("historical_fact_without_forward_stock_target")
            suggested = False
            status = "historical_fact_without_forward_stock_target"
        elif stock_hits and forecast_hits:
            suggested = True
            status = "stock_forward_target_supported_by_text"
        elif stock_hits:
            blockers.append("stock_target_without_explicit_forward_view")
            status = "stock_target_without_explicit_forward_view"
        else:
            blockers.append("stock_target_without_stock_context")
            status = "stock_target_without_stock_context"
    elif "industry_etf_forward_return" in target_variables:
        if industry_hits or forecast_hits:
            suggested = True
            status = "industry_forward_target_supported_by_text"
        else:
            blockers.append("industry_target_without_industry_context")
            status = "industry_target_without_industry_context"
    else:
        blockers.append("unknown_target_variable")
        status = "unknown_target_variable"
    return {
        "target_variables": target_variables,
        "stock_target_term_hits": stock_hits,
        "industry_target_term_hits": industry_hits,
        "forecast_term_hits": forecast_hits,
        "historical_fact_term_hits": historical_hits,
        "status": status,
        "blockers": tuple(dict.fromkeys(blockers)),
        "needs_review": bool(blockers),
        "suggested_correct": suggested,
    }


def _gold_horizon_diagnostics(row: Mapping[str, Any]) -> dict[str, Any]:
    text = str(row.get("proposed_claim_text") or "")
    explicit_hits = _gold_term_hits(text, GOLD_EXPLICIT_HORIZON_TERMS)
    forecast_hits = _gold_term_hits(text, GOLD_STRONG_FORECAST_TERMS)
    historical_hits = _gold_term_hits(text, GOLD_HISTORICAL_FACT_TERMS)
    blockers: list[str] = []
    suggested: bool | None = None
    status = "needs_human_review"
    if explicit_hits:
        suggested = True
        status = "explicit_horizon_or_period_text"
    elif historical_hits and not forecast_hits:
        blockers.append("historical_fact_without_forward_horizon")
        suggested = False
        status = "historical_fact_without_forward_horizon"
    elif forecast_hits:
        suggested = True
        status = "implicit_forward_horizon_from_forecast_terms"
    else:
        blockers.append("horizon_not_obvious_from_claim_text")
        status = "horizon_not_obvious_from_claim_text"
    return {
        "explicit_horizon_term_hits": explicit_hits,
        "forecast_term_hits": forecast_hits,
        "historical_fact_term_hits": historical_hits,
        "status": status,
        "blockers": tuple(dict.fromkeys(blockers)),
        "needs_review": bool(blockers),
        "suggested_correct": suggested,
    }


def _gold_unsupported_grounding_diagnostics(
    *,
    non_research_claim: bool,
    has_source_evidence: bool,
    proposed_flags: Sequence[str],
) -> dict[str, Any]:
    flag_set = {str(flag) for flag in proposed_flags}
    blockers = []
    if non_research_claim:
        blockers.append("non_research_claim_text")
    if not has_source_evidence:
        blockers.append("source_evidence_unverified")
    blockers.extend(sorted(flag_set & GOLD_GROUNDING_RISK_FLAGS))
    return {
        "non_research_claim_text": non_research_claim,
        "has_source_evidence": has_source_evidence,
        "grounding_risk_flags": tuple(sorted(flag_set & GOLD_GROUNDING_RISK_FLAGS)),
        "blockers": tuple(dict.fromkeys(blockers)),
        "needs_review": bool(blockers),
    }


def _gold_quality_gap_focus_fields(
    *,
    non_research_claim: bool,
    direction_diagnostics: Mapping[str, Any],
    variable_diagnostics: Mapping[str, Any],
    unsupported_diagnostics: Mapping[str, Any],
) -> tuple[str, ...]:
    fields: list[str] = []
    if non_research_claim:
        fields.extend(("claim_correct", "unsupported_field_false_grounded"))
    if direction_diagnostics.get("needs_review") is True:
        fields.append("direction_correct")
    if variable_diagnostics.get("needs_review") is True:
        fields.append("variable_mapping_correct")
    if unsupported_diagnostics.get("needs_review") is True:
        fields.append("unsupported_field_false_grounded")
    return tuple(dict.fromkeys(fields))


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
    source_id: str,
) -> tuple[str, str, bool]:
    candidate_paths: list[str] = []
    if metadata_row is not None:
        markdown = metadata_row.get("markdown")
        if isinstance(markdown, Mapping):
            markdown_path_text = str(markdown.get("path") or "")
            if markdown_path_text:
                candidate_paths.append(markdown_path_text)
    safe_source_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(source_id or "").strip())[:180] or "unknown"
    candidate_paths.append(
        f".mosaic/rke/report_intelligence/markdown/{safe_source_id}.md"
    )
    for markdown_path_text in candidate_paths:
        markdown_path = Path(markdown_path_text)
        if not markdown_path.is_absolute():
            markdown_path = root_path / markdown_path
        if markdown_path.exists() and markdown_path.stat().st_size > 0:
            return (
                markdown_path_text,
                markdown_path.read_text(encoding="utf-8", errors="ignore"),
                True,
            )
    return (candidate_paths[0] if candidate_paths else ""), "", False


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
    markdown_path_text, markdown_text, markdown_exists = _gold_markdown_text(
        root_path,
        metadata_row,
        source_id,
    )
    terms = _gold_evidence_terms(row)
    abstract_snippet = _gold_source_offset_snippet(source_row, row)
    snippets: list[dict[str, Any]] = []
    if abstract_snippet is not None:
        snippets.append(abstract_snippet)
    snippets.extend(_gold_markdown_snippets(markdown_text, terms))
    has_source_evidence = bool(snippets)
    proposed_claim_text = str(row.get("proposed_claim_text") or "").strip()
    proposed_direction = str(row.get("proposed_direction") or "").strip()
    proposed_flags = tuple(str(flag) for flag in row.get("proposed_review_risk_flags") or ())
    proposed_start = row.get("proposed_source_start_char")
    proposed_end = row.get("proposed_source_end_char")
    candidate_unavailable = (
        "candidate_unavailable" in proposed_flags
        or "manual claim required" in proposed_claim_text.lower()
        or (proposed_start == 0 and proposed_end == 0)
    )
    non_research_claim = is_non_research_claim_text(proposed_claim_text)
    direction_diagnostics = _gold_direction_text_diagnostics(
        proposed_claim_text,
        proposed_direction,
    )
    variable_diagnostics = _gold_variable_mapping_diagnostics(row, proposed_flags)
    target_diagnostics = _gold_target_diagnostics(row)
    horizon_diagnostics = _gold_horizon_diagnostics(row)
    unsupported_diagnostics = _gold_unsupported_grounding_diagnostics(
        non_research_claim=non_research_claim,
        has_source_evidence=has_source_evidence,
        proposed_flags=proposed_flags,
    )
    direction_needs_review = (
        direction_diagnostics.get("needs_review") is True
        or "direction_conflict_requires_review" in proposed_flags
    )
    unsupported_needs_review = unsupported_diagnostics.get("needs_review") is True
    variable_needs_review = variable_diagnostics.get("needs_review") is True
    target_suggested_correct = target_diagnostics.get("suggested_correct")
    horizon_suggested_correct = horizon_diagnostics.get("suggested_correct")
    suggested_decision = {
        "claim_correct": (
            False
            if non_research_claim
            else (
                None
                if candidate_unavailable
                else (True if has_source_evidence and proposed_claim_text else None)
            )
        ),
        "source_span_supports_claim": None if candidate_unavailable else (True if has_source_evidence else None),
        "direction_correct": (
            None
            if candidate_unavailable
            or non_research_claim
            or proposed_direction in {"", "ambiguous"}
            or direction_needs_review
            else True
        ),
        "target_correct": (
            None if candidate_unavailable or non_research_claim else target_suggested_correct
        ),
        "horizon_correct": (
            None if candidate_unavailable or non_research_claim else horizon_suggested_correct
        ),
        "variable_mapping_correct": (
            None
            if candidate_unavailable or non_research_claim
            else (False if variable_needs_review else True)
        ),
        "unsupported_field_false_grounded": (
            True
            if non_research_claim
            else (
                None
                if candidate_unavailable or unsupported_needs_review
                else False
            )
        ),
    }
    tags: list[str] = []
    rationales: list[dict[str, Any]] = []
    if candidate_unavailable:
        tags.append("candidate_unavailable_requires_manual_rewrite")
        rationales.append(
            {
                "field": "manual_claim_text",
                "suggested_value": "",
                "reason": "candidate unavailable or placeholder offsets require a human rewrite",
                "requires_human_confirmation": True,
            }
        )
    if non_research_claim:
        tags.append("non_research_claim_text")
        rationales.append(
            {
                "field": "claim_correct",
                "suggested_value": False,
                "reason": "candidate text matches shared non-research filters such as risk warnings, disclaimers, ratings definitions, headings, or table-of-contents fragments",
                "requires_human_confirmation": True,
            }
        )
        rationales.append(
            {
                "field": "unsupported_field_false_grounded",
                "suggested_value": True,
                "reason": "non-research boilerplate should not be accepted as a source-grounded forecast claim",
                "requires_human_confirmation": True,
            }
        )
    if not has_source_evidence:
        tags.append("source_evidence_unverified")
        rationales.append(
            {
                "field": "source_span_supports_claim",
                "suggested_value": None,
                "reason": "no abstract or local markdown snippet matched the candidate evidence terms",
                "requires_human_confirmation": True,
            }
        )
    elif not candidate_unavailable:
        rationales.append(
            {
                "field": "source_span_supports_claim",
                "suggested_value": True,
                "reason": "candidate has local abstract or markdown evidence snippets for reviewer inspection",
                "requires_human_confirmation": True,
            }
        )
    if not markdown_exists:
        tags.append("markdown_missing")
    if "direction_conflict_requires_review" in proposed_flags:
        tags.append("direction_conflict_requires_review")
    if proposed_direction == "ambiguous":
        tags.append("direction_ambiguous")
        rationales.append(
            {
                "field": "direction_correct",
                "suggested_value": None,
                "reason": "candidate direction is ambiguous and must be resolved from local evidence",
                "requires_human_confirmation": True,
            }
        )
    elif direction_needs_review and not candidate_unavailable:
        tags.append("direction_text_needs_review")
        rationales.append(
            {
                "field": "direction_correct",
                "suggested_value": None,
                "reason": (
                    "proposed direction should be rechecked because the claim text "
                    f"diagnostic is {direction_diagnostics.get('status')}"
                ),
                "requires_human_confirmation": True,
            }
        )
    elif proposed_direction and not candidate_unavailable and not non_research_claim:
        rationales.append(
            {
                "field": "direction_correct",
                "suggested_value": True,
                "reason": "candidate direction is explicit; reviewer should verify it against local evidence",
                "requires_human_confirmation": True,
            }
        )
    if "sentence_fallback_requires_context_synthesis" in proposed_flags:
        tags.append("context_synthesis_required")
        rationales.append(
            {
                "field": "manual_claim_text",
                "suggested_value": "synthesize_from_context",
                "reason": "candidate came from a sentence fallback and may need paragraph-level synthesis",
                "requires_human_confirmation": True,
            }
        )
    if not candidate_unavailable and not non_research_claim:
        if target_suggested_correct is not None:
            rationales.append(
                {
                    "field": "target_correct",
                    "suggested_value": target_suggested_correct,
                    "reason": (
                        "target diagnostic is "
                        f"{target_diagnostics.get('status')}"
                    ),
                    "requires_human_confirmation": True,
                }
            )
        if horizon_suggested_correct is not None:
            rationales.append(
                {
                    "field": "horizon_correct",
                    "suggested_value": horizon_suggested_correct,
                    "reason": (
                        "horizon diagnostic is "
                        f"{horizon_diagnostics.get('status')}"
                    ),
                    "requires_human_confirmation": True,
                }
            )
    if "canonical_variable_mapping_needed" in proposed_flags:
        tags.append("variable_mapping_needs_review")
        rationales.append(
            {
                "field": "variable_mapping_correct",
                "suggested_value": None,
                "reason": "candidate lacks a governed canonical variable mapping or needs reviewer normalization",
                "requires_human_confirmation": True,
            }
        )
    if not variable_diagnostics.get("cause_variable_count"):
        tags.append("variable_mapping_missing_cause")
    if not variable_diagnostics.get("target_variable_count"):
        tags.append("variable_mapping_missing_target")
    if variable_diagnostics.get("missing_expected_cause_variables"):
        tags.append("variable_mapping_missing_expected_cause")
    if variable_diagnostics.get("questionable_cause_variables"):
        tags.append("variable_mapping_questionable_cause")
    if (
        not candidate_unavailable
        and not non_research_claim
        and variable_diagnostics.get("needs_review") is True
    ):
        rationales.append(
            {
                "field": "variable_mapping_correct",
                "suggested_value": False,
                "reason": (
                    "variable mapping diagnostic found blockers, missing expected "
                    "cause variables, or questionable cause variables"
                ),
                "requires_human_confirmation": True,
            }
        )
    elif not candidate_unavailable and not non_research_claim:
        rationales.append(
            {
                "field": "variable_mapping_correct",
                "suggested_value": True,
                "reason": "proposed cause and target variables match the claim text diagnostics",
                "requires_human_confirmation": True,
            }
        )
    if "forecast_mapping_insufficient" in proposed_flags:
        tags.append("forecast_mapping_insufficient")
        rationales.append(
            {
                "field": "target_correct",
                "suggested_value": None,
                "reason": "candidate forecast target/proxy mapping is insufficient for automatic acceptance",
                "requires_human_confirmation": True,
            }
        )
    if unsupported_needs_review and not candidate_unavailable and not non_research_claim:
        tags.append("unsupported_grounding_needs_review")
        rationales.append(
            {
                "field": "unsupported_field_false_grounded",
                "suggested_value": None,
                "reason": "candidate has source-evidence or mapping risk flags that require reviewer grounding checks",
                "requires_human_confirmation": True,
            }
        )
    if "low_mechanism_keyword_support" in proposed_flags:
        tags.append("mechanism_support_needs_review")
        rationales.append(
            {
                "field": "claim_correct",
                "suggested_value": suggested_decision["claim_correct"],
                "reason": "candidate has weak mechanism keyword support; reviewer should confirm economic logic is present",
                "requires_human_confirmation": True,
            }
        )
    if "long_candidate_sentence" in proposed_flags:
        tags.append("manual_claim_text_needs_compaction")
        rationales.append(
            {
                "field": "manual_claim_text",
                "suggested_value": "compact_synthesis",
                "reason": "candidate sentence is long and should be compacted without losing source-supported logic",
                "requires_human_confirmation": True,
            }
        )
    quality_gap_focus_fields = _gold_quality_gap_focus_fields(
        non_research_claim=non_research_claim,
        direction_diagnostics=direction_diagnostics,
        variable_diagnostics=variable_diagnostics,
        unsupported_diagnostics=unsupported_diagnostics,
    )
    return {
        "evidence_kind": "gold_review_evidence_not_import",
        "not_apply_gold_review_input": True,
        "human_review_required": True,
        "index": index,
        "priority_score": _gold_evidence_priority_score(row),
        "priority_reasons": _gold_evidence_priority_reasons(row),
        "claim_id": str(row.get("claim_id") or ""),
        TARGET_ROW_HASH_FIELD: str(
            row.get(TARGET_ROW_HASH_FIELD) or review_row_fingerprint(row)
        ),
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
        "direction_text_diagnostics": direction_diagnostics,
        "target_mapping_diagnostics": target_diagnostics,
        "horizon_diagnostics": horizon_diagnostics,
        "variable_mapping_diagnostics": variable_diagnostics,
        "unsupported_grounding_diagnostics": unsupported_diagnostics,
        "quality_gap_focus_fields": quality_gap_focus_fields,
        "suggested_manual_claim_text": "" if candidate_unavailable else proposed_claim_text,
        "suggested_review_decision": suggested_decision,
        "suggested_review_rationales": tuple(rationales),
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
    offset: int = 0,
    review_input_path: str | Path | None = None,
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
    pending_rows = _gold_reviewable_pending_rows(
        [
            row
            for row in template_rows
            if not _gold_row_complete(reviewed_by_id.get(str(row.get("claim_id") or ""), row))
        ]
    )
    blockers: list[str] = [*parse_blockers, *reviewed_blockers, *source_blockers, *metadata_blockers]
    selection_source = "priority_sorted_pending"
    review_input_text = ""
    template_by_id = {
        str(row.get("claim_id") or ""): row
        for row in template_rows
        if str(row.get("claim_id") or "").strip()
    }
    if review_input_path is not None:
        selection_source = "review_input"
        review_input = Path(review_input_path)
        review_input_text = str(review_input)
        input_raw, input_rows, input_invalid_rows, input_parse_blockers, _ = (
            _load_review_rows(
                root_path,
                review_input_text,
                label="gold-set review input",
            )
        )
        blockers.extend(input_parse_blockers)
        if input_invalid_rows:
            blockers.append(
                "gold-set review input row must be object at row(s): "
                + ", ".join(str(row_number) for row_number in input_invalid_rows)
            )
        if not input_raw:
            blockers.append("gold-set review input is missing or empty")
        selected_rows: list[Mapping[str, Any]] = []
        seen_claim_ids: set[str] = set()
        for row_index, input_row in enumerate(input_rows, 1):
            claim_id = str(input_row.get("claim_id") or "").strip()
            if not claim_id:
                blockers.append(
                    f"gold-set review input row {row_index}.claim_id: required"
                )
                continue
            if claim_id in seen_claim_ids:
                blockers.append(
                    f"gold-set review input row {row_index}.claim_id: duplicate {claim_id}"
                )
                continue
            seen_claim_ids.add(claim_id)
            template_row = template_by_id.get(claim_id)
            if template_row is None:
                blockers.append(
                    f"gold-set review input row {row_index}.claim_id: no matching target review row"
                )
                continue
            expected_hash = review_row_fingerprint(template_row)
            input_hash = str(input_row.get(TARGET_ROW_HASH_FIELD) or "").strip()
            if input_hash and input_hash != expected_hash:
                blockers.append(
                    f"gold-set review input row {row_index}.{TARGET_ROW_HASH_FIELD}: "
                    "does not match target review row"
                )
            selected_rows.append(template_row)
        prioritized_rows = tuple(enumerate(selected_rows, 1))
    else:
        prioritized_rows = sorted(
            enumerate(pending_rows, 1),
            key=lambda item: (-_gold_evidence_priority_score(item[1]), item[0]),
        )[max(0, int(offset)) : max(0, int(offset)) + max(0, int(limit))]
    selected_rows = tuple(row for _, row in prioritized_rows)
    priority_score_counts, priority_reason_counts = _gold_priority_counts(selected_rows)
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
    gold_summary = summarize_gold_set_review(root_path)
    quality_gap_targets = _gold_quality_gap_targets_from_summary(
        root_path,
        gold_summary,
    )
    return (
        GoldReviewEvidenceSummary(
            evidence_id="RKE-GOLD-REVIEW-EVIDENCE-20260612",
            jsonl_path=GOLD_REVIEW_EVIDENCE_JSONL_PATH,
            markdown_path=GOLD_REVIEW_EVIDENCE_MD_PATH,
            review_template_path=GOLD_REVIEW_TEMPLATE_PATH,
            reviewed_import_path=GOLD_FULL_REVIEWED_IMPORT_PATH,
            requested_limit=max(0, int(limit)),
            requested_offset=max(0, int(offset)),
            row_count=len(evidence_rows),
            evidence_rows=sum(1 for row in evidence_rows if row.get("evidence_snippets")),
            missing_markdown_rows=missing_markdown_rows,
            selected_priority_score_counts=priority_score_counts,
            selected_priority_reason_counts=priority_reason_counts,
            blockers=tuple(blockers),
            selection_source=selection_source,
            review_input_path=review_input_text,
            quality_gap_targets=quality_gap_targets,
        ),
        evidence_rows,
    )


def render_gold_review_evidence_markdown(
    summary: GoldReviewEvidenceSummary,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    suggested_tag_counts = Counter(
        str(tag)
        for row in rows
        for tag in row.get("suggested_manual_error_tags") or ()
        if str(tag).strip()
    )
    priority_score_counts = Counter(
        str(row.get("priority_score") if row.get("priority_score") is not None else 0)
        for row in rows
    )
    priority_reason_counts = Counter(
        str(reason)
        for row in rows
        for reason in row.get("priority_reasons") or ()
        if str(reason).strip()
    )
    proposed_flag_counts = Counter(
        str(flag)
        for row in rows
        for flag in row.get("proposed_review_risk_flags") or ()
        if str(flag).strip()
    )
    quality_focus_counts = Counter(
        str(field)
        for row in rows
        for field in row.get("quality_gap_focus_fields") or ()
        if str(field).strip()
    )
    direction_diagnostic_counts = Counter(
        str((row.get("direction_text_diagnostics") or {}).get("status") or "")
        for row in rows
        if isinstance(row.get("direction_text_diagnostics"), Mapping)
    )
    variable_blocker_counts = Counter(
        str(blocker)
        for row in rows
        for blocker in (row.get("variable_mapping_diagnostics") or {}).get("blockers", ())
        if str(blocker).strip()
    )
    unsupported_blocker_counts = Counter(
        str(blocker)
        for row in rows
        for blocker in (row.get("unsupported_grounding_diagnostics") or {}).get("blockers", ())
        if str(blocker).strip()
    )
    decision_counts: dict[str, Counter[str]] = {
        field: Counter()
        for field in (
            "claim_correct",
            "source_span_supports_claim",
            "direction_correct",
            "target_correct",
            "horizon_correct",
            "variable_mapping_correct",
            "unsupported_field_false_grounded",
        )
    }
    decision_row_indexes: dict[str, dict[str, list[Any]]] = {
        field: {"false": [], "null": []} for field in decision_counts
    }
    for row in rows:
        decision = row.get("suggested_review_decision")
        decision_map = dict(decision) if isinstance(decision, Mapping) else {}
        for field, counts in decision_counts.items():
            value = decision_map.get(field)
            if value is True:
                counts["true"] += 1
            elif value is False:
                counts["false"] += 1
                decision_row_indexes[field]["false"].append(row.get("index"))
            else:
                counts["null"] += 1
                decision_row_indexes[field]["null"].append(row.get("index"))

    def quick_value(value: Any) -> str:
        if value is True:
            return "true"
        if value is False:
            return "false"
        return "review"

    quick_field_labels = (
        ("claim_correct", "claim"),
        ("source_span_supports_claim", "span"),
        ("direction_correct", "dir"),
        ("target_correct", "target"),
        ("horizon_correct", "horizon"),
        ("variable_mapping_correct", "vars"),
        ("unsupported_field_false_grounded", "false_ground"),
    )
    quick_rows: list[str] = []
    for row in rows:
        decision_map = (
            dict(row.get("suggested_review_decision"))
            if isinstance(row.get("suggested_review_decision"), Mapping)
            else {}
        )
        quick_cells = [
            _markdown_cell(row.get("index"), max_chars=12),
            f"`{_markdown_cell(row.get('claim_id'), max_chars=48)}`",
            _markdown_cell(row.get("gold_set_domain") or "-", max_chars=24),
            _markdown_cell(row.get("proposed_direction") or "-", max_chars=16),
        ]
        quick_cells.extend(
            quick_value(decision_map.get(field)) for field, _ in quick_field_labels
        )
        quick_cells.append(
            _markdown_cell(row.get("quality_gap_focus_fields"), max_chars=120)
        )
        quick_cells.append(
            _markdown_cell(row.get("suggested_manual_error_tags"), max_chars=120)
        )
        quick_rows.append("| " + " | ".join(quick_cells) + " |")
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
    lines.extend(
        [
            "## Batch Triage Summary",
            "",
            "- Priority score counts: "
            + _markdown_cell(dict(sorted(priority_score_counts.items())), max_chars=500),
            "- Priority reason counts: "
            + _markdown_cell(dict(sorted(priority_reason_counts.items())), max_chars=500),
            "- Suggested tag counts: "
            + _markdown_cell(dict(sorted(suggested_tag_counts.items())), max_chars=500),
            "- Proposed risk flag counts: "
            + _markdown_cell(dict(sorted(proposed_flag_counts.items())), max_chars=500),
            "- Quality-gap focus field counts: "
            + _markdown_cell(dict(sorted(quality_focus_counts.items())), max_chars=500),
            "- Direction diagnostic counts: "
            + _markdown_cell(
                dict(sorted(direction_diagnostic_counts.items())),
                max_chars=500,
            ),
            "- Variable mapping blocker counts: "
            + _markdown_cell(dict(sorted(variable_blocker_counts.items())), max_chars=500),
            "- Unsupported grounding blocker counts: "
            + _markdown_cell(
                dict(sorted(unsupported_blocker_counts.items())),
                max_chars=500,
            ),
            "- Suggested decision counts: "
            + _markdown_cell(
                {field: dict(counts) for field, counts in decision_counts.items()},
                max_chars=900,
            ),
            "",
        ]
    )
    field_meanings = (
        (
            "manual_claim_text",
            "human-entered compact claim label; keep it private and source-supported.",
        ),
        (
            "claim_correct",
            "whether the extracted text is a valid forecast or research claim, not a generic investment suggestion, valuation comment, disclaimer, heading, or unrelated statement.",
        ),
        (
            "source_span_supports_claim",
            "whether the cited local context supports the reviewed claim without unsupported inference.",
        ),
        (
            "direction_correct",
            "whether the extracted direction matches the claim's forecast direction.",
        ),
        (
            "target_correct",
            "whether the forecast target entity, asset, industry, or variable is the one actually forecast.",
        ),
        (
            "horizon_correct",
            "whether the extracted horizon matches the stated or implied forecast window.",
        ),
        (
            "variable_mapping_correct",
            "whether cause and target variables map to governed canonical variables; missing, broad, or unrelated mappings are false.",
        ),
        (
            "unsupported_field_false_grounded",
            "defect flag for an extracted field falsely grounded in the source; true means a grounding problem was found.",
        ),
        ("reviewer", "human reviewer identifier."),
        ("review_date", "human review date in YYYY-MM-DD format."),
        (
            "review_notes",
            "optional private rationale for overrides, false values, uncertain rows, or quality-gap cases.",
        ),
    )
    review_order = (
        (
            "unsupported_field_false_grounded",
            "review first because it directly controls the false-grounding excess blocker.",
        ),
        (
            "target_correct",
            "review next because the current quality gap can close if enough target decisions are confirmed.",
        ),
        (
            "direction_correct",
            "review next because direction accuracy remains below threshold.",
        ),
        (
            "horizon_correct",
            "review for consistency even though the aggregate metric is currently passing.",
        ),
        (
            "variable_mapping_correct",
            "verify every drafted value because this is the largest remaining quality gap.",
        ),
        (
            "claim_correct",
            "verify drafted values after the active quality-gap fields.",
        ),
        (
            "source_span_supports_claim",
            "verify drafted values against local evidence snippets.",
        ),
        (
            "manual_claim_text",
            "fill or edit every row after confirming the source-supported claim.",
        ),
    )
    lines.extend(["## Field Meaning And Review Order", ""])
    lines.extend(f"- `{field}`: {meaning}" for field, meaning in field_meanings)
    lines.extend(["", "Recommended order:", ""])
    for field, reason in review_order:
        row_notes: list[str] = []
        if field in decision_row_indexes:
            null_rows = decision_row_indexes[field]["null"]
            false_rows = decision_row_indexes[field]["false"]
            if null_rows:
                row_notes.append(
                    "suggested null rows: "
                    + _markdown_cell(null_rows, max_chars=240)
                )
            if false_rows:
                row_notes.append(
                    "suggested false rows: "
                    + _markdown_cell(false_rows, max_chars=240)
                )
        elif field == "manual_claim_text":
            row_notes.append("all rows require human text verification")
        suffix = " " + "; ".join(row_notes) if row_notes else ""
        lines.append(f"- `{field}`: {reason}{suffix}")
    lines.append("")
    if rows:
        quick_headers = [
            "#",
            "claim_id",
            "domain",
            "direction",
            *[label for _, label in quick_field_labels],
            "focus",
            "tags",
        ]
        lines.extend(
            [
                "## Quick Fill Checklist",
                "",
                "Machine suggestions below are a navigation aid only. Confirm each field against the evidence snippets before copying values into the reviewed JSONL scratch.",
                "",
                "| " + " | ".join(quick_headers) + " |",
                "| " + " | ".join("---" for _ in quick_headers) + " |",
                *quick_rows,
                "",
            ]
        )
    if summary.blockers:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in summary.blockers)
        lines.append("")
    if summary.quality_gap_targets:
        lines.extend(["## Quality Gate Gap Targets", ""])
        lines.append(
            "Aggregate only; these counts contain no source text and are not import decisions."
        )
        lines.append("")
        metrics = summary.quality_gap_targets.get("metrics", {})
        if isinstance(metrics, Mapping):
            for metric, target in metrics.items():
                if not isinstance(target, Mapping) or target.get("is_passing") is True:
                    continue
                if target.get("operator") == ">=":
                    lines.append(
                        "- "
                        f"{metric}: {target.get('current_rate')} / {target.get('threshold')} "
                        f"(need +{target.get('minimum_additional_pass_count_if_denominator_unchanged')})"
                    )
                else:
                    lines.append(
                        "- "
                        f"{metric}: {target.get('current_rate')} / {target.get('threshold')} "
                        f"(excess {target.get('minimum_excess_true_count_if_denominator_unchanged')})"
                    )
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
                f"- Priority reasons: {_markdown_cell(row.get('priority_reasons'), max_chars=200)}",
                f"- Suggested tags: {_markdown_cell(row.get('suggested_manual_error_tags'), max_chars=200)}",
                f"- Quality-gap focus fields: {_markdown_cell(row.get('quality_gap_focus_fields'), max_chars=200)}",
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
            ]
        )
        rationales = tuple(row.get("suggested_review_rationales") or ())
        if rationales:
            lines.extend(
                [
                    "Suggested decision rationales:",
                    "",
                    "```json",
                    json.dumps(rationales, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
        lines.extend(
            [
                "Review diagnostics:",
                "",
                "```json",
                json.dumps(
                    {
                        "direction_text_diagnostics": row.get(
                            "direction_text_diagnostics"
                        ),
                        "variable_mapping_diagnostics": row.get(
                            "variable_mapping_diagnostics"
                        ),
                        "unsupported_grounding_diagnostics": row.get(
                            "unsupported_grounding_diagnostics"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
            ]
        )
        lines.extend(["Evidence snippets:", ""])
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
    offset: int = 0,
    review_input_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    summary, rows = build_gold_review_evidence(
        root_path,
        limit=limit,
        offset=offset,
        review_input_path=review_input_path,
    )
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
        "offset": summary.requested_offset,
        "selection_source": summary.selection_source,
        "review_input_path": summary.review_input_path,
        "evidence_rows": summary.evidence_rows,
        "missing_markdown_rows": summary.missing_markdown_rows,
        "selected_priority_score_counts": summary.selected_priority_score_counts,
        "selected_priority_reason_counts": summary.selected_priority_reason_counts,
        "blockers": len(summary.blockers),
        "quality_gap_targets": summary.quality_gap_targets,
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

    pending_gold = _gold_reviewable_pending_rows(gold_rows)
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
    gold_full = tuple(_gold_template_row(row) for row in _gold_reviewable_pending_rows(gold_rows))
    gold_result = _write_jsonl(root_path / GOLD_BATCH_IMPORT_TEMPLATE_PATH, gold_batch)
    gold_full_result = _write_jsonl(root_path / GOLD_FULL_IMPORT_TEMPLATE_PATH, gold_full)
    gold_review_input_path = (
        GOLD_REVIEWED_IMPORT_PATH
        if (root_path / GOLD_REVIEWED_IMPORT_PATH).exists()
        else None
    )
    gold_workbook_result = write_gold_review_workbook(
        root_path,
        review_input_path=gold_review_input_path,
    )
    gold_assist_result = write_gold_review_assist(
        root_path,
        review_input_path=gold_review_input_path,
    )
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
    reviewed_failures: bool = False,
    force: bool = False,
    gold_batch_size: int = 50,
    offset: int = 0,
    reviewer: str = "",
    review_date: str = "",
) -> GoldReviewStarterResult:
    """Write a reviewer-editable gold-set JSONL starter without clobbering reviews."""
    if gold_batch_size <= 0:
        raise ValueError("gold_batch_size must be positive")
    if full and reviewed_failures:
        raise ValueError("full and reviewed_failures are mutually exclusive")

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

    _, gold_rows, _, _, _ = _load_review_rows(
        root_path,
        GOLD_REVIEW_TEMPLATE_PATH,
        label="gold-set review",
    )
    source_rows = (
        _gold_reviewed_failure_rows(gold_rows)
        if reviewed_failures
        else _gold_reviewable_pending_rows(gold_rows)
    )
    offset_value = 0 if full else max(0, int(offset))
    if full:
        selected_source_rows = tuple(source_rows)
        template_path = GOLD_FULL_IMPORT_TEMPLATE_PATH
    else:
        selected_source_rows = tuple(
            source_rows[offset_value : offset_value + gold_batch_size]
        )
        template_path = GOLD_BATCH_IMPORT_TEMPLATE_PATH
    priority_score_counts, priority_reason_counts = _gold_priority_counts(
        selected_source_rows
    )
    rows = tuple(_gold_template_row(row) for row in selected_source_rows)
    reviewer_text = str(reviewer or "").strip()
    review_date_text = str(review_date or "").strip()
    if reviewer_text or review_date_text:
        rows = tuple(
            {
                **dict(row),
                **({"reviewer": reviewer_text} if reviewer_text else {}),
                **({"review_date": review_date_text} if review_date_text else {}),
            }
            for row in rows
        )

    exists = resolved_output_path.exists()
    blockers: list[str] = []
    if exists and not force:
        blockers.append(f"{resolved_output_path} already exists; pass --force to overwrite")
    backed_up_existing_output = False
    backup_path = ""
    if not blockers:
        if exists and force:
            backup = _manual_review_backup_path(root_path, resolved_output_path)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(resolved_output_path.read_bytes())
            backed_up_existing_output = True
            backup_path = str(backup)
        _write_jsonl(resolved_output_path, rows)
    return GoldReviewStarterResult(
        path=str(resolved_output_path),
        template_path=template_path,
        full=full,
        reviewed_failures=reviewed_failures,
        force=force,
        offset=offset_value,
        written=not blockers,
        overwritten=exists and force and not blockers,
        rows=len(rows),
        selected_priority_score_counts=priority_score_counts,
        selected_priority_reason_counts=priority_reason_counts,
        blockers=tuple(blockers),
        backed_up_existing_output=backed_up_existing_output,
        backup_path=backup_path,
    )

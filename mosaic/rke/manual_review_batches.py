"""Batch export helpers for the manual RKE review gates.

The generated import templates are intentionally sparse: they identify pending
gold-set claims and source-license rows without duplicating long source text.
Reviewers should use the existing packets/source pool for context, then fill
the generated rows and import them with the controlled apply commands.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .manual_review_import import GOLD_BOOL_FIELDS, TARGET_ROW_HASH_FIELD, review_row_fingerprint
from .phase_minus1 import load_jsonl


GOLD_REVIEW_TEMPLATE_PATH = "registry/gold_sets/tushare_research_reports.review_template.jsonl"
GOLD_REVIEW_PACKET_PATH = "registry/gold_sets/tushare_research_reports.review_packet.json"
GOLD_BATCH_IMPORT_TEMPLATE_PATH = "registry/review_batches/gold_set_next_import_template.jsonl"
GOLD_FULL_IMPORT_TEMPLATE_PATH = "registry/review_batches/gold_set_full_import_template.jsonl"
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
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


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
        "variable_mapping_correct": None,
        "unsupported_field_false_grounded": None,
        "reviewer": "",
        "review_date": "",
        "review_notes": "",
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
    gold_rows = load_jsonl(root_path / GOLD_REVIEW_TEMPLATE_PATH)
    license_rows = load_jsonl(root_path / LICENSE_REVIEW_TEMPLATE_PATH)

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
        total_rows=len(gold_rows),
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
        total_rows=len(license_rows),
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
    if not gold_rows:
        blockers.append("gold-set review template is missing or empty")
    if not license_rows:
        blockers.append("source-license review template is missing or empty")
    if gold_pending_ids:
        blockers.append(f"{len(gold_pending_ids)} gold-set review rows still pending")
    if license_pending_ids:
        blockers.append(f"{len(license_pending_ids)} source-license review rows still pending")

    status = ManualReviewBatchStatus(
        status_id="RKE-MANUAL-REVIEW-BATCH-STATUS-20260606",
        ready_for_manual_review=bool(gold_rows and license_rows),
        gold_set=gold_summary,
        source_license=license_summary,
        generated_paths=(
            GOLD_BATCH_IMPORT_TEMPLATE_PATH,
            GOLD_FULL_IMPORT_TEMPLATE_PATH,
            LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
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
    gold_rows = load_jsonl(root_path / GOLD_REVIEW_TEMPLATE_PATH)
    gold_full = tuple(_gold_template_row(row) for row in gold_rows if not _gold_row_complete(row))
    gold_result = _write_jsonl(root_path / GOLD_BATCH_IMPORT_TEMPLATE_PATH, gold_batch)
    gold_full_result = _write_jsonl(root_path / GOLD_FULL_IMPORT_TEMPLATE_PATH, gold_full)
    license_result = _write_jsonl(root_path / LICENSE_BATCH_IMPORT_TEMPLATE_PATH, license_batch)
    status_result = _write_json(root_path / MANUAL_REVIEW_BATCH_STATUS_PATH, asdict(status))
    return {
        "status": str(status_result["path"]),
        "gold_set_import_template": str(gold_result["path"]),
        "gold_set_full_import_template": str(gold_full_result["path"]),
        "source_license_import_template": str(license_result["path"]),
        "gold_set_rows": int(gold_result["rows"]),
        "gold_set_full_rows": int(gold_full_result["rows"]),
        "source_license_rows": int(license_result["rows"]),
    }

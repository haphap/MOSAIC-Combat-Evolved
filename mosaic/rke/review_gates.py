"""Manual review gate summaries for RKE external blockers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .compliance import apply_source_license_reviews, evaluate_source_license
from .phase_minus1 import evaluate_gold_set_reviews, load_jsonl


GOLD_REVIEW_FIELDS = (
    "claim_correct",
    "source_span_supports_claim",
    "direction_correct",
    "variable_mapping_correct",
    "unsupported_field_false_grounded",
)


@dataclass(frozen=True)
class GoldSetReviewSummary:
    summary_id: str
    review_path: str
    total_documents: int
    total_claims: int
    reviewed_claims: int
    pending_claims: int
    review_complete: bool
    passed: bool
    metrics: Mapping[str, float | int] | None
    blockers: Sequence[str]


@dataclass(frozen=True)
class SourceLicenseReviewSummary:
    summary_id: str
    source_path: str
    review_path: str
    total_sources: int
    total_review_rows: int
    reviewed_sources: int
    pending_sources: int
    approved_for_production_runtime: int
    review_complete: bool
    passed: bool
    missing_review_source_ids: Sequence[str]
    extra_review_source_ids: Sequence[str]
    blockers: Sequence[str]


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def _gold_row_reviewed(row: Mapping[str, Any]) -> bool:
    return all(row.get(field) is not None for field in GOLD_REVIEW_FIELDS)


def summarize_gold_set_review(
    root: str | Path = ".",
    *,
    review_relative_path: str = "registry/gold_sets/tushare_research_reports.review_template.jsonl",
) -> GoldSetReviewSummary:
    root_path = Path(root)
    review_path = root_path / review_relative_path
    rows = load_jsonl(review_path) if review_path.exists() else []
    documents = {str(row.get("document_id") or row.get("source_id") or "") for row in rows}
    documents.discard("")
    reviewed = [row for row in rows if _gold_row_reviewed(row)]
    pending_claims = len(rows) - len(reviewed)
    blockers: list[str] = []
    metrics: dict[str, float | int] | None = None
    passed = False

    if not rows:
        blockers.append("gold-set review file missing or empty")
    if pending_claims:
        blockers.append(f"{pending_claims} gold-set claim review rows still pending")

    if rows and pending_claims == 0:
        gold_set = evaluate_gold_set_reviews(rows, gold_set_id="GOLD-CLAIM-2026Q2")
        metrics = {
            "sample_size_documents": gold_set.sample_size_documents,
            "sample_size_claims": gold_set.sample_size_claims,
            "claim_precision": gold_set.claim_precision,
            "source_span_support_precision": gold_set.source_span_support_precision,
            "direction_accuracy": gold_set.direction_accuracy,
            "variable_mapping_accuracy": gold_set.variable_mapping_accuracy,
            "unsupported_field_false_grounding_rate": gold_set.unsupported_field_false_grounding_rate,
        }
        gate_failures = gold_set.gate_failures()
        passed = not gate_failures
        blockers.extend(gate_failures)

    return GoldSetReviewSummary(
        summary_id="RKE-GOLD-SET-REVIEW-SUMMARY-20260606",
        review_path=review_relative_path,
        total_documents=len(documents),
        total_claims=len(rows),
        reviewed_claims=len(reviewed),
        pending_claims=pending_claims,
        review_complete=bool(rows) and pending_claims == 0,
        passed=passed,
        metrics=metrics,
        blockers=tuple(blockers),
    )


def write_gold_set_review_summary(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    summary = summarize_gold_set_review(root_path)
    output_path = root_path / "registry/gold_sets/tushare_research_reports.review_summary.json"
    return _write_json(output_path, asdict(summary))


def _license_row_reviewed(row: Mapping[str, Any]) -> bool:
    return (
        isinstance(row.get("approved_for_derived_claim_storage"), bool)
        and isinstance(row.get("approved_for_production_runtime"), bool)
        and bool(str(row.get("reviewer") or "").strip())
        and bool(str(row.get("review_date") or "").strip())
    )


def summarize_source_license_review(
    root: str | Path = ".",
    *,
    source_relative_path: str = "registry/sources/tushare_research_reports.jsonl",
    review_relative_path: str = "registry/compliance/tushare_license_review_template.jsonl",
) -> SourceLicenseReviewSummary:
    root_path = Path(root)
    source_path = root_path / source_relative_path
    review_path = root_path / review_relative_path
    sources = load_jsonl(source_path) if source_path.exists() else []
    reviews = load_jsonl(review_path) if review_path.exists() else []
    source_ids = {str(row.get("source_id") or "") for row in sources}
    review_ids = {str(row.get("source_id") or "") for row in reviews}
    source_ids.discard("")
    review_ids.discard("")

    reviewed_rows = [row for row in reviews if _license_row_reviewed(row)]
    reviewed_ids = {str(row.get("source_id") or "") for row in reviewed_rows}
    missing_review_ids = tuple(sorted(source_ids - reviewed_ids))
    extra_review_ids = tuple(sorted(review_ids - source_ids))

    reviewed_sources = apply_source_license_reviews(sources, reviewed_rows)
    decisions = [evaluate_source_license(source) for source in reviewed_sources]
    approved_for_production = sum(decision.allowed_for_production_runtime for decision in decisions)
    pending_sources = len(source_ids - reviewed_ids)
    blockers: list[str] = []

    if not sources:
        blockers.append("source registry missing or empty")
    if not reviews:
        blockers.append("license review file missing or empty")
    if pending_sources:
        blockers.append(f"{pending_sources} source license review rows still pending")
    if extra_review_ids:
        blockers.append(f"{len(extra_review_ids)} review rows do not match current source registry")
    if sources and approved_for_production < len(source_ids):
        blockers.append(
            f"{approved_for_production} / {len(source_ids)} sources approved for production runtime"
        )

    passed = bool(sources) and not pending_sources and not extra_review_ids and approved_for_production == len(source_ids)
    return SourceLicenseReviewSummary(
        summary_id="RKE-SOURCE-LICENSE-REVIEW-SUMMARY-20260606",
        source_path=source_relative_path,
        review_path=review_relative_path,
        total_sources=len(source_ids),
        total_review_rows=len(reviews),
        reviewed_sources=len(reviewed_ids & source_ids),
        pending_sources=pending_sources,
        approved_for_production_runtime=int(approved_for_production),
        review_complete=bool(sources) and pending_sources == 0 and not extra_review_ids,
        passed=passed,
        missing_review_source_ids=missing_review_ids,
        extra_review_source_ids=extra_review_ids,
        blockers=tuple(blockers),
    )


def write_source_license_review_summary(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    summary = summarize_source_license_review(root_path)
    output_path = root_path / "registry/compliance/tushare_license_review_summary.json"
    return _write_json(output_path, asdict(summary))

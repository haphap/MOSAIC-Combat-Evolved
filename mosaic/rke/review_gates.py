"""Manual review gate summaries for RKE external blockers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from math import ceil, floor
from pathlib import Path
from typing import Any, Mapping, Sequence

from .compliance import apply_source_license_reviews, evaluate_source_license
from .p0 import (
    CLAIM_GOLD_SET_METRIC_THRESHOLDS,
    MIN_CLAIM_GOLD_SET_CLAIMS,
    MIN_CLAIM_GOLD_SET_DOCUMENTS,
)
from .phase_minus1 import evaluate_gold_set_reviews, load_jsonl_with_errors
from .review_integrity import (
    gold_review_integrity_failures,
    gold_review_row_complete,
    license_review_integrity_failures,
    license_review_row_complete,
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
    quality_gap_targets: Mapping[str, Any] | None
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
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _split_mapping_rows(
    rows: Sequence[Any],
) -> tuple[list[Mapping[str, Any]], tuple[int, ...]]:
    valid: list[Mapping[str, Any]] = []
    invalid: list[int] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid.append(row)
        else:
            invalid.append(index)
    return valid, tuple(invalid)


def _gold_row_reviewed(row: Mapping[str, Any]) -> bool:
    return gold_review_row_complete(row)


_GOLD_REVIEW_FIELD_BY_METRIC = {
    "claim_precision": "claim_correct",
    "source_span_support_precision": "source_span_supports_claim",
    "direction_accuracy": "direction_correct",
    "target_accuracy": "target_correct",
    "horizon_accuracy": "horizon_correct",
    "variable_mapping_accuracy": "variable_mapping_correct",
    "unsupported_field_false_grounding_rate": "unsupported_field_false_grounded",
}


def _gold_quality_gap_targets(
    rows: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, float | int],
) -> Mapping[str, Any]:
    sample_size_claims = int(metrics.get("sample_size_claims") or 0)
    sample_size_documents = int(metrics.get("sample_size_documents") or 0)
    metric_targets: dict[str, Mapping[str, Any]] = {}
    active_gap_count = 0

    for metric, (operator, threshold) in CLAIM_GOLD_SET_METRIC_THRESHOLDS.items():
        field = _GOLD_REVIEW_FIELD_BY_METRIC[metric]
        current_rate = float(metrics.get(metric) or 0.0)
        is_passing = (
            current_rate >= threshold if operator == ">=" else current_rate <= threshold
        )
        if operator == ">=":
            current_pass_count = sum(row.get(field) is True for row in rows)
            required_pass_count = ceil((threshold * sample_size_claims) - 1e-12)
            minimum_gap_count = max(0, required_pass_count - current_pass_count)
            if minimum_gap_count:
                active_gap_count += 1
            metric_targets[metric] = {
                "operator": operator,
                "threshold": threshold,
                "current_rate": current_rate,
                "denominator": sample_size_claims,
                "current_pass_count": current_pass_count,
                "required_pass_count": required_pass_count,
                "minimum_additional_pass_count_if_denominator_unchanged": minimum_gap_count,
                "is_passing": is_passing,
            }
        else:
            current_true_count = sum(row.get(field) is True for row in rows)
            max_allowed_true_count = floor((threshold * sample_size_claims) + 1e-12)
            excess_true_count = max(0, current_true_count - max_allowed_true_count)
            if excess_true_count:
                active_gap_count += 1
            metric_targets[metric] = {
                "operator": operator,
                "threshold": threshold,
                "current_rate": current_rate,
                "denominator": sample_size_claims,
                "current_true_count": current_true_count,
                "max_allowed_true_count": max_allowed_true_count,
                "minimum_excess_true_count_if_denominator_unchanged": excess_true_count,
                "is_passing": is_passing,
            }

    document_gap = max(0, MIN_CLAIM_GOLD_SET_DOCUMENTS - sample_size_documents)
    claim_gap = max(0, MIN_CLAIM_GOLD_SET_CLAIMS - sample_size_claims)
    return {
        "policy": (
            "public_safe_aggregate_quality_gate_gap_targets_no_source_text"
        ),
        "interpretation": (
            "count deltas are the minimum gaps if the reviewed denominator stays "
            "unchanged; use them to prioritize re-review or candidate expansion, "
            "not as instructions to flip labels"
        ),
        "sample_size_documents": {
            "operator": ">=",
            "threshold": MIN_CLAIM_GOLD_SET_DOCUMENTS,
            "current_count": sample_size_documents,
            "minimum_additional_count": document_gap,
            "is_passing": document_gap == 0,
        },
        "sample_size_claims": {
            "operator": ">=",
            "threshold": MIN_CLAIM_GOLD_SET_CLAIMS,
            "current_count": sample_size_claims,
            "minimum_additional_count": claim_gap,
            "is_passing": claim_gap == 0,
        },
        "metrics": metric_targets,
        "active_gap_count": active_gap_count
        + int(document_gap > 0)
        + int(claim_gap > 0),
    }


def summarize_gold_set_review(
    root: str | Path = ".",
    *,
    review_relative_path: str = "registry/gold_sets/tushare_research_reports.review_template.jsonl",
) -> GoldSetReviewSummary:
    root_path = Path(root)
    review_path = root_path / review_relative_path
    raw_rows, review_parse_blockers = (
        load_jsonl_with_errors(review_path, label="gold-set review")
        if review_path.exists()
        else ([], ())
    )
    rows, invalid_rows = _split_mapping_rows(raw_rows)
    documents = {
        str(row.get("document_id") or row.get("source_id") or "") for row in rows
    }
    documents.discard("")
    reviewed = [row for row in rows if _gold_row_reviewed(row)]
    total_claim_rows = len(raw_rows) + len(review_parse_blockers)
    pending_claims = total_claim_rows - len(reviewed)
    blockers: list[str] = []
    metrics: dict[str, float | int] | None = None
    quality_gap_targets: Mapping[str, Any] | None = None
    passed = False

    if not raw_rows and not review_parse_blockers:
        blockers.append("gold-set review file missing or empty")
    blockers.extend(review_parse_blockers)
    if invalid_rows:
        blockers.append(
            "gold-set review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_rows)
        )
    integrity_failures = gold_review_integrity_failures(rows) if rows else ()
    blockers.extend(integrity_failures)
    if pending_claims:
        blockers.append(f"{pending_claims} gold-set claim review rows still pending")

    if rows and not invalid_rows and not integrity_failures and pending_claims == 0:
        gold_set = evaluate_gold_set_reviews(rows, gold_set_id="GOLD-CLAIM-2026Q2")
        metrics = {
            "sample_size_documents": gold_set.sample_size_documents,
            "sample_size_claims": gold_set.sample_size_claims,
            "claim_precision": gold_set.claim_precision,
            "source_span_support_precision": gold_set.source_span_support_precision,
            "direction_accuracy": gold_set.direction_accuracy,
            "target_accuracy": gold_set.target_accuracy,
            "horizon_accuracy": gold_set.horizon_accuracy,
            "variable_mapping_accuracy": gold_set.variable_mapping_accuracy,
            "unsupported_field_false_grounding_rate": gold_set.unsupported_field_false_grounding_rate,
        }
        quality_gap_targets = _gold_quality_gap_targets(reviewed, metrics)
        gate_failures = gold_set.gate_failures()
        passed = not gate_failures
        blockers.extend(gate_failures)

    return GoldSetReviewSummary(
        summary_id="RKE-GOLD-SET-REVIEW-SUMMARY-20260606",
        review_path=review_relative_path,
        total_documents=len(documents),
        total_claims=total_claim_rows,
        reviewed_claims=len(reviewed),
        pending_claims=pending_claims,
        review_complete=(
            bool(raw_rows)
            and not review_parse_blockers
            and not invalid_rows
            and not integrity_failures
            and pending_claims == 0
        ),
        passed=passed,
        metrics=metrics,
        quality_gap_targets=quality_gap_targets,
        blockers=tuple(blockers),
    )


def write_gold_set_review_summary(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    summary = summarize_gold_set_review(root_path)
    output_path = (
        root_path / "registry/gold_sets/tushare_research_reports.review_summary.json"
    )
    return _write_json(output_path, asdict(summary))


def _license_row_reviewed(row: Mapping[str, Any]) -> bool:
    return license_review_row_complete(row)


def summarize_source_license_review(
    root: str | Path = ".",
    *,
    source_relative_path: str = "registry/sources/tushare_research_reports.jsonl",
    review_relative_path: str = "registry/compliance/tushare_license_review_template.jsonl",
) -> SourceLicenseReviewSummary:
    root_path = Path(root)
    source_path = root_path / source_relative_path
    review_path = root_path / review_relative_path
    raw_sources, source_parse_blockers = (
        load_jsonl_with_errors(source_path, label="source registry")
        if source_path.exists()
        else ([], ())
    )
    raw_reviews, review_parse_blockers = (
        load_jsonl_with_errors(review_path, label="source license review")
        if review_path.exists()
        else ([], ())
    )
    sources, invalid_source_rows = _split_mapping_rows(raw_sources)
    reviews, invalid_review_rows = _split_mapping_rows(raw_reviews)
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
    approved_for_production = sum(
        decision.allowed_for_production_runtime for decision in decisions
    )
    pending_sources = len(source_ids - reviewed_ids)
    blockers: list[str] = []

    if not raw_sources and not source_parse_blockers:
        blockers.append("source registry missing or empty")
    elif not sources:
        blockers.append("source registry has no valid source rows")
    if not raw_reviews and not review_parse_blockers:
        blockers.append("license review file missing or empty")
    elif not reviews:
        blockers.append("license review file has no valid review rows")
    blockers.extend(source_parse_blockers)
    blockers.extend(review_parse_blockers)
    if invalid_source_rows:
        blockers.append(
            "source registry row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_source_rows)
        )
    if invalid_review_rows:
        blockers.append(
            "source license review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_review_rows)
        )
    integrity_failures = (
        license_review_integrity_failures(sources, reviews)
        if sources or reviews
        else ()
    )
    blockers.extend(integrity_failures)
    if pending_sources:
        blockers.append(f"{pending_sources} source license review rows still pending")
    if extra_review_ids:
        blockers.append(
            f"{len(extra_review_ids)} review rows do not match current source registry"
        )
    if sources and approved_for_production < len(source_ids):
        blockers.append(
            f"{approved_for_production} / {len(source_ids)} sources approved for production runtime"
        )

    passed = (
        bool(sources)
        and not source_parse_blockers
        and not review_parse_blockers
        and not invalid_source_rows
        and not invalid_review_rows
        and not integrity_failures
        and not pending_sources
        and not extra_review_ids
        and approved_for_production == len(source_ids)
    )
    return SourceLicenseReviewSummary(
        summary_id="RKE-SOURCE-LICENSE-REVIEW-SUMMARY-20260606",
        source_path=source_relative_path,
        review_path=review_relative_path,
        total_sources=len(source_ids),
        total_review_rows=len(raw_reviews) + len(review_parse_blockers),
        reviewed_sources=len(reviewed_ids & source_ids),
        pending_sources=pending_sources,
        approved_for_production_runtime=int(approved_for_production),
        review_complete=(
            bool(sources)
            and not source_parse_blockers
            and not review_parse_blockers
            and not invalid_source_rows
            and not invalid_review_rows
            and not integrity_failures
            and pending_sources == 0
            and not extra_review_ids
        ),
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

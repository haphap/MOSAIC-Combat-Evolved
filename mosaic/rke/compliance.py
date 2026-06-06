"""Compliance and license gates for RKE source material."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


LicenseStatus = Literal["approved", "pending_review", "restricted", "prohibited"]


@dataclass(frozen=True)
class SourceLicenseDecision:
    source_id: str
    license_status: str
    allowed_for_ingest: bool
    allowed_for_sandbox: bool
    allowed_for_derived_claim_storage: bool
    allowed_for_production_runtime: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SourceLicenseReviewRecord:
    source_id: str
    approved_for_derived_claim_storage: bool
    approved_for_production_runtime: bool
    reviewer: str
    review_date: str
    notes: str = ""


@dataclass(frozen=True)
class SourceLicensePolicy:
    approved_statuses_for_production: Sequence[str] = ("approved",)
    statuses_allowed_for_sandbox: Sequence[str] = ("approved", "pending_review", "restricted")
    statuses_allowed_for_derived_claim_storage: Sequence[str] = ("approved",)
    prohibited_statuses: Sequence[str] = ("prohibited",)


def evaluate_source_license(
    source: Any,
    *,
    policy: SourceLicensePolicy = SourceLicensePolicy(),
) -> SourceLicenseDecision:
    if not isinstance(source, Mapping):
        return SourceLicenseDecision(
            source_id="<malformed-source-row>",
            license_status="invalid",
            allowed_for_ingest=False,
            allowed_for_sandbox=False,
            allowed_for_derived_claim_storage=False,
            allowed_for_production_runtime=False,
            reasons=("source row must be object",),
        )

    source_id = str(source.get("source_id") or "<missing-source-id>")
    license_status = str(source.get("license_status") or "pending_review")
    reasons: list[str] = []

    allowed_for_ingest = license_status not in set(policy.prohibited_statuses)
    allowed_for_sandbox = license_status in set(policy.statuses_allowed_for_sandbox)
    allowed_for_derived_claim_storage = license_status in set(
        policy.statuses_allowed_for_derived_claim_storage
    )
    allowed_for_production_runtime = license_status in set(
        policy.approved_statuses_for_production
    )

    if not source.get("source_hash"):
        reasons.append("source_hash required")
    if source.get("point_in_time_available") is not True:
        reasons.append("point_in_time_available must be true")
        allowed_for_production_runtime = False
    if license_status in set(policy.prohibited_statuses):
        reasons.append("prohibited source cannot be ingested")
    elif license_status == "pending_review":
        reasons.append("pending_review source is sandbox-only until compliance approval")
    elif license_status == "restricted":
        reasons.append("restricted source is not allowed in production runtime")
    if source.get("forbidden_uses"):
        forbidden_uses = {str(item) for item in source.get("forbidden_uses", ())}
        if "production_runtime_retrieval" in forbidden_uses:
            allowed_for_production_runtime = False
            reasons.append("production_runtime_retrieval is forbidden")
        if "derived_claim_storage" in forbidden_uses:
            allowed_for_derived_claim_storage = False
            reasons.append("derived_claim_storage is forbidden")

    return SourceLicenseDecision(
        source_id=source_id,
        license_status=license_status,
        allowed_for_ingest=allowed_for_ingest,
        allowed_for_sandbox=allowed_for_sandbox,
        allowed_for_derived_claim_storage=allowed_for_derived_claim_storage,
        allowed_for_production_runtime=allowed_for_production_runtime,
        reasons=tuple(reasons),
    )


def filter_sources_for_runtime(
    sources: Sequence[Any],
    *,
    production: bool,
    policy: SourceLicensePolicy = SourceLicensePolicy(),
) -> tuple[tuple[Mapping[str, Any], ...], tuple[SourceLicenseDecision, ...]]:
    allowed: list[Mapping[str, Any]] = []
    decisions: list[SourceLicenseDecision] = []
    for source in sources:
        decision = evaluate_source_license(source, policy=policy)
        decisions.append(decision)
        if production:
            if decision.allowed_for_production_runtime:
                allowed.append(source)
        elif decision.allowed_for_sandbox:
            allowed.append(source)
    return tuple(allowed), tuple(decisions)


def build_source_license_review_template(
    sources: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in sources:
        rows.append(
            {
                "source_id": str(source.get("source_id") or ""),
                "source_type": str(source.get("source_type") or ""),
                "title": str(source.get("title") or ""),
                "publish_date": str(source.get("publish_date") or ""),
                "current_license_status": str(source.get("license_status") or "pending_review"),
                "approved_for_derived_claim_storage": None,
                "approved_for_production_runtime": None,
                "reviewer": "",
                "review_date": "",
                "notes": "",
            }
        )
    return rows


def write_source_license_review_template(
    sources: Sequence[Mapping[str, Any]],
    output_path: str | Path,
) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = build_source_license_review_template(sources)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"path": str(path), "rows": len(rows)}


def apply_source_license_reviews(
    sources: Sequence[Mapping[str, Any]],
    reviews: Sequence[Any],
) -> tuple[dict[str, Any], ...]:
    review_by_source: dict[str, SourceLicenseReviewRecord | Mapping[str, Any]] = {}
    for review in reviews:
        if isinstance(review, SourceLicenseReviewRecord):
            source_id = str(review.source_id or "")
        elif isinstance(review, Mapping):
            source_id = str(review.get("source_id") or "")
        else:
            continue
        if source_id:
            review_by_source[source_id] = review

    updated: list[dict[str, Any]] = []
    for source in sources:
        row = dict(source)
        source_id = str(row.get("source_id") or "")
        review = review_by_source.get(source_id)
        if review is None:
            updated.append(row)
            continue
        if isinstance(review, SourceLicenseReviewRecord):
            derived = review.approved_for_derived_claim_storage
            production = review.approved_for_production_runtime
            reviewer = review.reviewer
            review_date = review.review_date
            notes = review.notes
        else:
            derived = review.get("approved_for_derived_claim_storage") is True
            production = review.get("approved_for_production_runtime") is True
            reviewer = str(review.get("reviewer") or "")
            review_date = str(review.get("review_date") or "")
            notes = str(review.get("notes") or "")
        forbidden_uses: list[str] = []
        allowed_uses = ["human_reading", "internal_research_summary"]
        if derived:
            allowed_uses.append("derived_claim_storage")
        else:
            forbidden_uses.append("derived_claim_storage")
        if production:
            allowed_uses.append("production_runtime_retrieval")
        else:
            forbidden_uses.append("production_runtime_retrieval")
        row["license_status"] = "approved" if derived and production else "restricted"
        row["allowed_uses"] = allowed_uses
        row["forbidden_uses"] = forbidden_uses
        row["review_owner"] = reviewer
        row["review_date"] = review_date
        row["review_notes"] = notes
        updated.append(row)
    return tuple(updated)

"""Compliance and license gates for RKE source material."""

from __future__ import annotations

from dataclasses import dataclass
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
class SourceLicensePolicy:
    approved_statuses_for_production: Sequence[str] = ("approved",)
    statuses_allowed_for_sandbox: Sequence[str] = ("approved", "pending_review", "restricted")
    statuses_allowed_for_derived_claim_storage: Sequence[str] = ("approved",)
    prohibited_statuses: Sequence[str] = ("prohibited",)


def evaluate_source_license(
    source: Mapping[str, Any],
    *,
    policy: SourceLicensePolicy = SourceLicensePolicy(),
) -> SourceLicenseDecision:
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
    sources: Sequence[Mapping[str, Any]],
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

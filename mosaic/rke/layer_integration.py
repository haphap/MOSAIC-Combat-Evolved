"""Phase 7 cross-layer integration contracts for RKE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence


ConfirmationDimension = Literal["fundamental", "policy", "flow", "price"]


@dataclass(frozen=True)
class SectorIntegrationOutput:
    agent_id: str
    macro_handoff_ids: Sequence[str]
    rule_pack_ids: Sequence[str]
    confirmation_dimensions: Sequence[ConfirmationDimension]
    confidence: float
    actionability: str


@dataclass(frozen=True)
class SuperinvestorCandidateReview:
    ticker: str
    style_fit_score: float
    accepted: bool
    reason: str
    mismatch_with_style: str = ""


@dataclass(frozen=True)
class SuperinvestorIntegrationOutput:
    agent_id: str
    investor_style: str
    accepted_candidates: Sequence[SuperinvestorCandidateReview]
    rejected_candidates: Sequence[SuperinvestorCandidateReview]


@dataclass(frozen=True)
class DecisionIntegrationOutput:
    agent_id: str
    upstream_agent_ids: Sequence[str]
    ignored_signal_reasons: Sequence[str]
    risk_discount: float
    cash_floor: float
    override_audit: Sequence[str]
    correlated_exposure_notes: Sequence[str]
    execution_turnover_impact: str


@dataclass(frozen=True)
class IntegrationCheckResult:
    accepted: bool
    reasons: tuple[str, ...]


def check_sector_integration(output: SectorIntegrationOutput) -> IntegrationCheckResult:
    reasons: list[str] = []
    if not output.macro_handoff_ids:
        reasons.append("sector output requires macro handoff")
    if not output.rule_pack_ids:
        reasons.append("sector output requires rule pack references")
    confirmations = set(output.confirmation_dimensions)
    if output.confidence >= 0.65 and len(confirmations) < 2:
        reasons.append("high-confidence sector output requires at least two confirmation dimensions")
    if output.confidence > 0.60 and confirmations <= {"policy"}:
        reasons.append("policy-only theme confidence must be capped at 0.60")
    if output.confidence <= 0.60 and output.actionability not in {
        "monitor_only",
        "watchlist_or_tiny_tilt",
        "no_trade",
    }:
        reasons.append("low-confidence sector output must not exceed tiny-tilt actionability")
    return IntegrationCheckResult(accepted=not reasons, reasons=tuple(reasons))


def check_superinvestor_integration(output: SuperinvestorIntegrationOutput) -> IntegrationCheckResult:
    reasons: list[str] = []
    if not output.investor_style:
        reasons.append("investor_style required")
    if not output.accepted_candidates and not output.rejected_candidates:
        reasons.append("superinvestor output requires accepted or rejected candidates")
    for review in (*output.accepted_candidates, *output.rejected_candidates):
        if review.style_fit_score < 0 or review.style_fit_score > 1:
            reasons.append(f"{review.ticker}: style_fit_score must be in [0, 1]")
        if not review.reason:
            reasons.append(f"{review.ticker}: reason required")
        if not review.accepted and not review.mismatch_with_style:
            reasons.append(f"{review.ticker}: rejected candidate requires mismatch_with_style")
    return IntegrationCheckResult(accepted=not reasons, reasons=tuple(reasons))


def check_decision_integration(output: DecisionIntegrationOutput) -> IntegrationCheckResult:
    reasons: list[str] = []
    if not output.upstream_agent_ids:
        reasons.append("decision output requires upstream_agent_ids")
    if output.risk_discount < 0 or output.risk_discount > 1:
        reasons.append("risk_discount must be in [0, 1]")
    if output.cash_floor < 0 or output.cash_floor > 1:
        reasons.append("cash_floor must be in [0, 1]")
    if not output.override_audit:
        reasons.append("override_audit required")
    if not output.correlated_exposure_notes:
        reasons.append("correlated_exposure_notes required")
    if not output.execution_turnover_impact:
        reasons.append("execution_turnover_impact required")
    return IntegrationCheckResult(accepted=not reasons, reasons=tuple(reasons))

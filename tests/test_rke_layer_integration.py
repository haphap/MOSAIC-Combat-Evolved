from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    DecisionIntegrationOutput,
    SectorIntegrationOutput,
    SuperinvestorCandidateReview,
    SuperinvestorIntegrationOutput,
    check_decision_integration,
    check_sector_integration,
    check_superinvestor_integration,
)


def test_sector_integration_accepts_monitor_only_policy_signal():
    result = check_sector_integration(
        SectorIntegrationOutput(
            agent_id="sector.semiconductor",
            macro_handoff_ids=("OUT-CB-20260605-0001",),
            rule_pack_ids=("sector.semiconductor.policy_substitution.v1",),
            confirmation_dimensions=("policy",),
            confidence=0.50,
            actionability="monitor_only",
        )
    )

    assert result.accepted


def test_sector_integration_rejects_high_confidence_single_dimension():
    result = check_sector_integration(
        SectorIntegrationOutput(
            agent_id="sector.semiconductor",
            macro_handoff_ids=("OUT-CB-20260605-0001",),
            rule_pack_ids=("sector.semiconductor.policy_substitution.v1",),
            confirmation_dimensions=("policy",),
            confidence=0.72,
            actionability="modest_tilt",
        )
    )

    assert not result.accepted
    assert any("two confirmation" in reason for reason in result.reasons)
    assert any("policy-only" in reason for reason in result.reasons)


def test_superinvestor_integration_requires_rejection_reasons_and_style_fit():
    accepted = check_superinvestor_integration(
        SuperinvestorIntegrationOutput(
            agent_id="superinvestor.druckenmiller",
            investor_style="macro-aware concentrated growth",
            accepted_candidates=(
                SuperinvestorCandidateReview(
                    ticker="WATCHLIST-SEMI-QUALITY",
                    style_fit_score=0.74,
                    accepted=True,
                    reason="matches style but remains watchlist-only",
                ),
            ),
            rejected_candidates=(
                SuperinvestorCandidateReview(
                    ticker="POLICY-THEME-ONLY-SEMI",
                    style_fit_score=0.42,
                    accepted=False,
                    reason="no current confirmation",
                    mismatch_with_style="sandbox-only policy theme",
                ),
            ),
        )
    )
    rejected = check_superinvestor_integration(
        SuperinvestorIntegrationOutput(
            agent_id="superinvestor.druckenmiller",
            investor_style="macro-aware concentrated growth",
            accepted_candidates=(),
            rejected_candidates=(
                SuperinvestorCandidateReview(
                    ticker="BAD",
                    style_fit_score=1.2,
                    accepted=False,
                    reason="",
                ),
            ),
        )
    )

    assert accepted.accepted
    assert not rejected.accepted
    assert any("style_fit_score" in reason for reason in rejected.reasons)
    assert any("reason required" in reason for reason in rejected.reasons)
    assert any("mismatch_with_style" in reason for reason in rejected.reasons)


def test_decision_integration_requires_risk_and_override_audit():
    accepted = check_decision_integration(
        DecisionIntegrationOutput(
            agent_id="decision.cio",
            upstream_agent_ids=("macro.central_bank", "sector.semiconductor"),
            ignored_signal_reasons=("sandbox-only sector signal",),
            risk_discount=0.2,
            cash_floor=0.05,
            override_audit=("research-only signal cannot override CRO gates",),
            correlated_exposure_notes=("semiconductor signal is growth-beta correlated",),
            execution_turnover_impact="tiny-tilt maximum",
        )
    )
    rejected = check_decision_integration(
        DecisionIntegrationOutput(
            agent_id="decision.cio",
            upstream_agent_ids=(),
            ignored_signal_reasons=(),
            risk_discount=1.2,
            cash_floor=-0.1,
            override_audit=(),
            correlated_exposure_notes=(),
            execution_turnover_impact="",
        )
    )

    assert accepted.accepted
    assert not rejected.accepted
    assert any("upstream" in reason for reason in rejected.reasons)
    assert any("risk_discount" in reason for reason in rejected.reasons)
    assert any("cash_floor" in reason for reason in rejected.reasons)


def test_phase7_integration_registry_is_valid():
    payload = json.loads(
        Path("registry/integration/phase7_layer_integration_contracts.json").read_text(
            encoding="utf-8"
        )
    )
    sector = SectorIntegrationOutput(**payload["sector"])
    superinvestor = SuperinvestorIntegrationOutput(
        agent_id=payload["superinvestor"]["agent_id"],
        investor_style=payload["superinvestor"]["investor_style"],
        accepted_candidates=tuple(
            SuperinvestorCandidateReview(**item)
            for item in payload["superinvestor"]["accepted_candidates"]
        ),
        rejected_candidates=tuple(
            SuperinvestorCandidateReview(**item)
            for item in payload["superinvestor"]["rejected_candidates"]
        ),
    )
    decision = DecisionIntegrationOutput(**payload["decision"])

    assert check_sector_integration(sector).accepted
    assert check_superinvestor_integration(superinvestor).accepted
    assert check_decision_integration(decision).accepted

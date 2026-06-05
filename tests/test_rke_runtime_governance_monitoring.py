from __future__ import annotations

from mosaic.rke import (
    EvidenceLedgerItem,
    LearnableParameter,
    MutationProposal,
    PaperTradingReport,
    PaperTradingSnapshot,
    ProductionMonitorPolicy,
    ProductionPatch,
    ProgressEvent,
    RuntimeAgentOutput,
    RuntimeInference,
    RuntimeRecommendation,
    build_audit_trace,
    check_runtime_output,
    default_evolution_targets,
    evaluate_production_monitor,
    validate_audit_trace,
    validate_patch,
)


TARGET_PATH = (
    "/rule_packs/macro.central_bank.liquidity.v1/rules/"
    "macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value"
)


def test_patch_checker_accepts_valid_parameter_update():
    patch = ProductionPatch(
        patch_id="PATCH-CB-20260605-0001",
        source_experiment_id="EXP-CB-20260605-0001",
        operation="replace",
        target_path=TARGET_PATH,
        old_value=7,
        new_value=10,
        allowed_by_evolution_targets=True,
        validation_summary={"promotion_state": "paper_trading"},
        rollback_rule={"metric": "live_net_alpha_after_cost_20d", "delta_lt": -0.02},
    )

    result = validate_patch(
        patch,
        current_registry={TARGET_PATH: 7},
        parameter_types={
            TARGET_PATH: LearnableParameter(
                value=7,
                type="integer",
                unit="trading_day",
                min=3,
                max=20,
            )
        },
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={"EXP-CB-20260605-0001"},
    )

    assert result.accepted
    assert result.reasons == ()


def test_patch_checker_rejects_forbidden_or_type_unsafe_updates():
    mutation = MutationProposal(
        mutation_id="MUT-BAD",
        proposal_type="parameter_update",
        agent_id="macro.central_bank",
        target_path=TARGET_PATH,
        operation="replace",
        old_value=7,
        new_value="10d",
        source_experiment_id="EXP-UNKNOWN",
        expected_effect={"primary_metric": "net_alpha_after_cost_20d"},
        risk="type mismatch",
        rollback_condition={},
    )

    result = validate_patch(
        mutation,
        current_registry={TARGET_PATH: 5},
        parameter_types={TARGET_PATH: LearnableParameter(value=7, type="integer", min=3, max=20)},
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={"EXP-CB-20260605-0001"},
    )

    assert not result.accepted
    assert any("old_value" in reason for reason in result.reasons)
    assert any("integer" in reason for reason in result.reasons)
    assert any("source_experiment_id" in reason for reason in result.reasons)
    assert any("rollback" in reason for reason in result.reasons)


def _runtime_output(confidence: float = 0.62, actionability: str = "watchlist_or_tiny_tilt"):
    return RuntimeAgentOutput(
        evidence_ledger=(
            EvidenceLedgerItem(
                evidence_id="E1",
                source_type="tool_output",
                source_tool="get_pboc_ops",
                metric="net_injection_7d",
                value=12500,
                unit="CNY 100mn",
                as_of="2026-06-05",
                freshness_days=0,
                direction="liquidity_supportive",
                fallback=False,
                confidence_impact="positive",
                source_claim_ids=("CLAIM-CB-20260605-0001",),
            ),
        ),
        research_rule_ids_used=("macro.central_bank.soft.001",),
        source_claim_ids_used=("CLAIM-CB-20260605-0001",),
        hypothesis_ids_used=("HYP-CB-20260605-0001",),
        inferences=(
            RuntimeInference(
                inference_id="I1",
                statement="Liquidity is supportive after confirmation.",
                evidence_ids=("E1",),
                rule_ids=("macro.central_bank.soft.001",),
                source_claim_ids=("CLAIM-CB-20260605-0001",),
            ),
        ),
        recommendations=(
            RuntimeRecommendation(
                recommendation_id="R1",
                statement="Allow a small risk-appetite prior.",
                inference_ids=("I1",),
                confidence=confidence,
                actionability=actionability,
            ),
        ),
        uncertainties=("requires flow confirmation",),
        confidence_components={
            "data_confidence": 0.7,
            "research_confidence": 0.7,
            "empirical_validation_confidence": 0.62,
            "regime_match_confidence": 0.7,
        },
        rule_aggregation_summary={
            "has_opposing_rules": False,
            "correlated_rule_duplicate_count": 0,
        },
        downstream_handoff={"agent_id": "macro.central_bank", "summary": "supportive liquidity"},
        progress_event=ProgressEvent(
            agent_id="macro.central_bank",
            layer="macro",
            status="completed",
            tools_used=("get_pboc_ops",),
            evidence_count=1,
            fallback_count=0,
            missing_count=0,
            schema_valid=True,
            confidence=confidence,
        ),
    )


def test_runtime_output_checker_accepts_bound_evidence_chain():
    result = check_runtime_output(
        _runtime_output(),
        verified_claim_ids={"CLAIM-CB-20260605-0001"},
        confidence_cap=0.65,
    )

    assert result.accepted


def test_runtime_output_checker_rejects_research_only_actionability_and_missing_conflict():
    output = _runtime_output(confidence=0.62, actionability="modest_tilt")
    output = RuntimeAgentOutput(
        **{
            **output.__dict__,
            "rule_aggregation_summary": {
                "has_opposing_rules": True,
                "correlated_rule_duplicate_count": 2,
            },
        }
    )

    result = check_runtime_output(
        output,
        verified_claim_ids={"CLAIM-CB-20260605-0001"},
        confidence_cap=0.65,
        research_only=True,
    )

    assert not result.accepted
    assert any("research-only" in reason for reason in result.reasons)
    assert any("conflict_objects" in reason for reason in result.reasons)
    assert any("deduped_rule_groups" in reason for reason in result.reasons)


def test_paper_trading_report_and_production_monitor_track_decay():
    report = PaperTradingReport(
        rule_id="macro.central_bank.soft.001",
        snapshots=(
            PaperTradingSnapshot(
                rule_id="macro.central_bank.soft.001",
                date="2026-06-05",
                live_shadow_signal=0.12,
                baseline_signal=0.08,
                live_net_alpha_after_cost=0.006,
                turnover=0.08,
                calibration_error=0.02,
            ),
        ),
    )

    summary = report.summarize()
    monitor = evaluate_production_monitor(
        original_validation_effect=0.012,
        rolling_net_alpha_after_cost=-0.003,
        calibration_error=0.14,
        turnover_delta=0.25,
        effective_events=45,
        policy=ProductionMonitorPolicy(),
    )

    assert summary["ready"]
    assert summary["mean_live_vs_baseline_delta"] == 0.04
    assert monitor.state == "rollback_required"
    assert monitor.action == "rollback"


def test_audit_trace_requires_full_source_to_output_chain():
    trace = build_audit_trace(
        source_ids=("SRC-1",),
        claim_ids=("CLAIM-1",),
        hypothesis_ids=("HYP-1",),
        rule_ids=("macro.central_bank.soft.001",),
        parameter_paths=(TARGET_PATH,),
        experiment_ids=("EXP-1",),
        patch_ids=("PATCH-1",),
        agent_output_ids=("OUT-1",),
    )

    assert validate_audit_trace(trace) == ()
    assert validate_audit_trace({**trace, "patch_ids": ()}) == ("patch_ids required",)

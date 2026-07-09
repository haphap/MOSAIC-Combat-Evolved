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
    ResearchSupportItem,
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


def test_v15_evolution_targets_allow_report_intelligence_shadow_paths():
    targets = default_evolution_targets()

    assert targets.allows("/analysis_recipe_registry/RECIPE-CB-00009/runtime_mode")
    assert targets.allows("/metric_candidate_registry/METRIC-CB-00017/aliases")
    assert targets.allows("/tool_design_proposals/TDP-CB-00018/status")
    assert targets.allows("/rule_packs/macro.central_bank.liquidity.v1/research_prior")
    assert targets.allows(
        "/rule_packs/macro.central_bank.liquidity.v1/rules/"
        "macro.central_bank.soft.001/confidence_policy/missing_current_data/cap"
    )
    assert not targets.allows("/sector_score")
    assert not targets.allows("/role_contract/may_decide")
    assert not targets.allows(
        "/report_intelligence/forecast_claims/FC-0001/claim_provenance"
    )


def test_patch_checker_accepts_v15_non_parameter_registry_update():
    patch = ProductionPatch(
        patch_id="PATCH-METHOD-2026-0014",
        source_experiment_id="EXP-CB-20260605-0001",
        operation="replace",
        target_path="/analysis_recipe_registry/RECIPE-CB-00009/runtime_mode",
        old_value="shadow_only",
        new_value="paper_trading",
        allowed_by_evolution_targets=True,
        validation_summary={
            "promotion_state": "paper_trading",
            "evidence": {
                "tool_correctness_tests_passed": True,
                "pit_validation_status": "passed_with_caution",
                "effective_n": 44.2,
            },
            "constraints": {
                "no_direct_sizing": True,
                "requires_current_data": True,
                "confidence_cap": 0.65,
            },
        },
        rollback_rule={"metric": "paper_trading_after_cost_alpha_delta", "delta_lt": -0.01},
    )

    result = validate_patch(
        patch,
        current_registry={
            "/analysis_recipe_registry/RECIPE-CB-00009/runtime_mode": "shadow_only"
        },
        parameter_types={},
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={"EXP-CB-20260605-0001"},
    )

    assert result.accepted


def test_patch_checker_rejects_v15_method_promotion_without_validation_evidence():
    patch = ProductionPatch(
        patch_id="PATCH-METHOD-UNDERPROVEN",
        source_experiment_id="EXP-CB-20260605-0001",
        operation="replace",
        target_path="/analysis_recipe_registry/RECIPE-CB-00009/runtime_mode",
        old_value="shadow_only",
        new_value="production",
        allowed_by_evolution_targets=True,
        validation_summary={
            "promotion_state": "paper_trading",
            "evidence": {
                "tool_correctness_tests_passed": False,
                "pit_validation_status": "failed",
                "effective_n": 8,
            },
            "constraints": {
                "no_direct_sizing": False,
                "requires_current_data": False,
                "confidence_cap": 0.9,
            },
        },
        rollback_rule={"metric": "paper_trading_after_cost_alpha_delta", "delta_lt": -0.01},
    )

    result = validate_patch(
        patch,
        current_registry={
            "/analysis_recipe_registry/RECIPE-CB-00009/runtime_mode": "shadow_only"
        },
        parameter_types={},
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={"EXP-CB-20260605-0001"},
    )

    assert not result.accepted
    assert any("cannot target production" in reason for reason in result.reasons)
    assert any("tool_correctness_tests_passed" in reason for reason in result.reasons)
    assert any("effective_n" in reason for reason in result.reasons)
    assert any("confidence_cap" in reason for reason in result.reasons)


def test_patch_checker_accepts_v15_source_weight_update_with_shrinkage_evidence():
    patch = ProductionPatch(
        patch_id="PATCH-RW-2026-0009",
        source_experiment_id="EXP-CB-20260605-0001",
        operation="replace",
        target_path="/research_weighting/source_profiles/AUTH-001/weight_policy",
        old_value={"weight_multiplier": 1.0, "bucket": "neutral"},
        new_value={"weight_multiplier": 1.18, "bucket": "above_neutral"},
        allowed_by_evolution_targets=True,
        validation_summary={
            "promotion_state": "paper_trading",
            "evidence": {
                "n_effective": 32.4,
                "validation_method": "overlap_adjusted_after_cost_backtest",
                "fdr_passed": True,
            },
            "constraints": {
                "max_multiplier": 1.5,
                "pit_only": True,
                "requires_shadow_mode_first": True,
            },
        },
        rollback_rule={"metric": "weighted_research_calibration_error", "delta_gt": 0.05},
    )

    result = validate_patch(
        patch,
        current_registry={
            "/research_weighting/source_profiles/AUTH-001/weight_policy": {
                "weight_multiplier": 1.0,
                "bucket": "neutral",
            }
        },
        parameter_types={},
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={"EXP-CB-20260605-0001"},
    )

    assert result.accepted


def test_patch_checker_rejects_v15_source_weight_update_without_effective_n():
    patch = ProductionPatch(
        patch_id="PATCH-RW-UNDERPOWERED",
        source_experiment_id="EXP-CB-20260605-0001",
        operation="replace",
        target_path="/research_weighting/source_profiles/AUTH-001/weight_policy",
        old_value={"weight_multiplier": 1.0, "bucket": "neutral"},
        new_value={"weight_multiplier": 2.0, "bucket": "above_neutral"},
        allowed_by_evolution_targets=True,
        validation_summary={
            "promotion_state": "paper_trading",
            "evidence": {
                "n_effective": 2.0,
                "validation_method": "plain_backtest",
                "fdr_passed": False,
            },
            "constraints": {
                "max_multiplier": 1.5,
                "pit_only": False,
                "requires_shadow_mode_first": False,
            },
        },
        rollback_rule={"metric": "weighted_research_calibration_error", "delta_gt": 0.05},
    )

    result = validate_patch(
        patch,
        current_registry={
            "/research_weighting/source_profiles/AUTH-001/weight_policy": {
                "weight_multiplier": 1.0,
                "bucket": "neutral",
            }
        },
        parameter_types={},
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={"EXP-CB-20260605-0001"},
    )

    assert not result.accepted
    assert any("n_effective" in reason for reason in result.reasons)
    assert any("fdr_passed" in reason for reason in result.reasons)
    assert any("overlap-adjusted" in reason for reason in result.reasons)
    assert any("max_multiplier" in reason for reason in result.reasons)


def test_patch_checker_accepts_v15_metric_candidate_alias_merge():
    patch = ProductionPatch(
        patch_id="PATCH-METRIC-MERGE-2026-0003",
        source_experiment_id="EXP-CB-20260605-0001",
        operation="merge_alias",
        target_path="/metric_candidate_registry/METRIC-CB-00017/aliases",
        old_value=["pboc_net_injection_7d"],
        new_value=["pboc_net_injection_7d", "公开市场7日净投放"],
        allowed_by_evolution_targets=True,
        validation_summary={
            "promotion_state": "paper_trading",
            "evidence": {
                "raw_source_match": True,
                "unit_match": True,
                "frequency_match": True,
                "transformation_match": True,
                "human_review_required": True,
                "human_review_status": "approved",
            },
        },
        rollback_rule={"metric": "metric_alias_error_rate", "delta_gt": 0.01},
    )

    result = validate_patch(
        patch,
        current_registry={
            "/metric_candidate_registry/METRIC-CB-00017/aliases": [
                "pboc_net_injection_7d"
            ]
        },
        parameter_types={},
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={"EXP-CB-20260605-0001"},
    )

    assert result.accepted


def test_patch_checker_rejects_v15_metric_candidate_alias_merge_without_review():
    patch = ProductionPatch(
        patch_id="PATCH-METRIC-MERGE-BAD",
        source_experiment_id="EXP-CB-20260605-0001",
        operation="append",
        target_path="/metric_candidate_registry/METRIC-CB-00017/aliases",
        old_value=["pboc_net_injection_7d"],
        new_value=["pboc_net_injection_7d", "unknown proxy"],
        allowed_by_evolution_targets=True,
        validation_summary={
            "promotion_state": "paper_trading",
            "evidence": {
                "raw_source_match": False,
                "unit_match": False,
                "frequency_match": True,
                "transformation_match": True,
                "human_review_required": True,
                "human_review_status": "pending",
                "forbidden_if": ["unit_mismatch"],
            },
        },
        rollback_rule={"metric": "metric_alias_error_rate", "delta_gt": 0.01},
    )

    result = validate_patch(
        patch,
        current_registry={
            "/metric_candidate_registry/METRIC-CB-00017/aliases": [
                "pboc_net_injection_7d"
            ]
        },
        parameter_types={},
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={"EXP-CB-20260605-0001"},
    )

    assert not result.accepted
    assert any("merge_alias operation" in reason for reason in result.reasons)
    assert any("raw_source_match" in reason for reason in result.reasons)
    assert any("approved human review" in reason for reason in result.reasons)
    assert any("forbidden by evidence" in reason for reason in result.reasons)


def test_patch_checker_rejects_v15_forbidden_provenance_rewrite():
    patch = ProductionPatch(
        patch_id="PATCH-BAD-PROVENANCE",
        source_experiment_id="EXP-CB-20260605-0001",
        operation="replace",
        target_path="/report_intelligence/forecast_claims/FC-0001/claim_provenance",
        old_value="analyst_or_llm_hypothesis",
        new_value="source_grounded",
        allowed_by_evolution_targets=True,
        validation_summary={"promotion_state": "paper_trading"},
        rollback_rule={"metric": "manual_review_error_rate", "delta_gt": 0.01},
    )

    result = validate_patch(
        patch,
        current_registry={
            "/report_intelligence/forecast_claims/FC-0001/claim_provenance": (
                "analyst_or_llm_hypothesis"
            )
        },
        parameter_types={},
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={"EXP-CB-20260605-0001"},
    )

    assert not result.accepted
    assert any("forbidden paths" in reason for reason in result.reasons)


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
                evidence_type="current_tool_data",
                metric_candidate_id="METRIC-CB-PBOC-NET-INJECTION-7D",
                analysis_recipe_id="RECIPE-CB-LIQUIDITY-IMPULSE",
                report_footprint_ids=("AFP-CB-LIQUIDITY-IMPULSE",),
                tool_proposal_id="TDP-CB-PBOC-OMO",
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
            "research_weight_confidence": 0.7,
            "empirical_validation_confidence": 0.62,
            "method_tool_confidence": 0.7,
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
    output = _runtime_output()
    result = check_runtime_output(
        output,
        verified_claim_ids={"CLAIM-CB-20260605-0001"},
        confidence_cap=0.65,
    )

    assert result.accepted
    evidence = output.evidence_ledger[0]
    assert evidence.evidence_type == "current_tool_data"
    assert evidence.metric_candidate_id == "METRIC-CB-PBOC-NET-INJECTION-7D"
    assert evidence.analysis_recipe_id == "RECIPE-CB-LIQUIDITY-IMPULSE"


def test_runtime_output_checker_rejects_research_prior_in_evidence_ledger():
    output = _runtime_output()
    bad_evidence = EvidenceLedgerItem(
        **{
            **output.evidence_ledger[0].__dict__,
            "evidence_type": "research_prior_not_current_data",
        }
    )
    output = RuntimeAgentOutput(
        **{
            **output.__dict__,
            "evidence_ledger": (bad_evidence,),
        }
    )

    result = check_runtime_output(
        output,
        verified_claim_ids={"CLAIM-CB-20260605-0001"},
        confidence_cap=0.65,
    )

    assert not result.accepted
    assert any("research priors must use research_support_ledger" in reason for reason in result.reasons)


def test_runtime_output_checker_rejects_confidence_above_v15_min_components():
    result = check_runtime_output(
        _runtime_output(confidence=0.63),
        verified_claim_ids={"CLAIM-CB-20260605-0001"},
        confidence_cap=0.65,
    )

    assert not result.accepted
    assert any("v1.5 min-components cap" in reason for reason in result.reasons)


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


def _research_support_only_output(actionability: str) -> RuntimeAgentOutput:
    support = ResearchSupportItem(
        research_support_id="RS-CB-20260605-0001",
        evidence_type="research_prior_not_current_data",
        source_claim_ids=("CLAIM-CB-20260605-0001",),
        viewpoint_cluster_ids=("VIEW-LIQUIDITY-IMPULSE",),
        source_weight_bucket="neutral",
        method_pattern_ids=("METHOD-CB-LIQUIDITY",),
        allowed_use="prior_and_explanation_only",
        cannot_support_action_without_current_data=True,
    )
    return RuntimeAgentOutput(
        evidence_ledger=(),
        research_support_ledger=(support,),
        research_rule_ids_used=("macro.central_bank.soft.001",),
        source_claim_ids_used=("CLAIM-CB-20260605-0001",),
        hypothesis_ids_used=("HYP-CB-20260605-0001",),
        inferences=(
            RuntimeInference(
                inference_id="I-RS-ONLY",
                statement="Research prior supports a watchlist only.",
                evidence_ids=(),
                research_support_ids=(support.research_support_id,),
                rule_ids=("macro.central_bank.soft.001",),
                source_claim_ids=("CLAIM-CB-20260605-0001",),
            ),
        ),
        recommendations=(
            RuntimeRecommendation(
                recommendation_id="R-RS-ONLY",
                statement="Research support alone cannot justify a tilt.",
                inference_ids=("I-RS-ONLY",),
                confidence=0.50,
                actionability=actionability,
            ),
        ),
        uncertainties=("current tool data missing",),
        confidence_components={
            "data_confidence": 0.50,
            "research_weight_confidence": 0.58,
            "empirical_validation_confidence": 0.58,
            "method_tool_confidence": 0.50,
            "regime_match_confidence": 0.50,
        },
        rule_aggregation_summary={
            "has_opposing_rules": False,
            "correlated_rule_duplicate_count": 0,
        },
        downstream_handoff={
            "agent_id": "macro.central_bank",
            "summary": "research_prior_only",
        },
        progress_event=ProgressEvent(
            agent_id="macro.central_bank",
            layer="macro",
            status="completed",
            tools_used=(),
            evidence_count=0,
            fallback_count=0,
            missing_count=1,
            schema_valid=True,
            confidence=0.50,
        ),
    )


def test_runtime_output_checker_rejects_research_support_actionability_without_current_data():
    output = _research_support_only_output(actionability="watchlist_or_tiny_tilt")

    result = check_runtime_output(
        output,
        verified_claim_ids={"CLAIM-CB-20260605-0001"},
        confidence_cap=0.60,
    )

    assert not result.accepted
    assert any("research support cannot be actionable" in reason for reason in result.reasons)


def test_runtime_output_checker_allows_research_support_monitoring_without_current_data():
    output = _research_support_only_output(actionability="monitor_only")

    result = check_runtime_output(
        output,
        verified_claim_ids={"CLAIM-CB-20260605-0001"},
        confidence_cap=0.60,
    )

    assert result.accepted


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

from mosaic.rke import (
    ClaimExtractionGoldSet,
    ConfidenceComponents,
    CostAwareAcceptance,
    DataAvailabilityMatrix,
    MetricProxyAvailability,
    MultipleTestingControl,
    PreRegistration,
    RuleAggregationPolicy,
    RuleFireOutput,
    SamplingDesign,
    SourceGroundedClaim,
    aggregate_rule_outputs,
    benjamini_hochberg_q_values,
    build_central_bank_p0_mvp,
    check_research_only_actionability,
    compute_confidence_v1,
    evaluate_validation_experiment,
    validate_rule_id,
    validate_rule_pack_id,
    validate_target_path,
    verify_source_grounded_claim,
)


def test_p0_07_data_matrix_blocks_non_pit_proxy():
    matrix = DataAvailabilityMatrix(
        matrix_id="DAM-BAD",
        proxies={
            "latest_only_policy_news": MetricProxyAvailability(
                metric_proxy="latest_only_policy_news",
                data_source="scraped_latest_only",
                point_in_time_available=False,
                history_start="",
                history_end="2026-06-05",
                vintage_handling="latest",
                restatement_risk="unknown",
                survivorship_bias_risk="unknown",
                timestamp_granularity="daily",
                allowed_for_validation=False,
                allowed_for_production=False,
                coverage_drift_risk="unknown",
            )
        },
    )

    failures = matrix.require(("latest_only_policy_news",), production=True)

    assert any("PIT" in failure for failure in failures)
    assert any("not allowed for validation" in failure for failure in failures)
    assert any("not allowed for production" in failure for failure in failures)


def test_p0_04_claim_gold_set_and_span_verifier_gate_compilation():
    gold = ClaimExtractionGoldSet(
        gold_set_id="GOLD-CLAIM-2026Q2",
        sample_size_documents=50,
        sample_size_claims=500,
        claim_precision=0.87,
        source_span_support_precision=0.92,
        direction_accuracy=0.86,
        variable_mapping_accuracy=0.81,
        unsupported_field_false_grounding_rate=0.03,
    )
    assert gold.passed

    claim = SourceGroundedClaim(
        claim_id="CLAIM-CB-20260605-0001",
        source_id="SRC-CB-20260605-0001",
        source_span_id="PAGE-1-PARA-1",
        claim_type="causal_mechanism",
        claim_text="PBOC liquidity injections can ease short-term liquidity pressure.",
        cause_variables=("pboc_net_injection",),
        target_variables=("short_term_liquidity_pressure",),
        direction="positive",
        verifier_status="passed",
        human_review_required=False,
    )
    result = verify_source_grounded_claim(
        claim,
        source_spans={
            "PAGE-1-PARA-1": (
                "PBOC liquidity injections can ease short-term liquidity pressure."
            )
        },
        controlled_variables={"pboc_net_injection", "short_term_liquidity_pressure"},
    )

    assert result.accepted
    assert result.eligible_for_rule_compiler


def test_p0_04_claim_checker_rejects_fabricated_fields():
    claim = SourceGroundedClaim(
        claim_id="CLAIM-BAD",
        source_id="SRC-BAD",
        source_span_id="PAGE-1-PARA-1",
        claim_type="causal_mechanism",
        claim_text="Liquidity is mentioned.",
        cause_variables=("unknown_metric",),
        target_variables=("risk_appetite",),
        direction="ambiguous",
        unsupported_fields=("failure_modes",),
        verifier_status="pending",
    )

    result = verify_source_grounded_claim(
        claim,
        source_spans={"PAGE-1-PARA-1": "Liquidity is mentioned."},
        controlled_variables={"risk_appetite"},
    )

    assert not result.accepted
    assert any("unsupported fields" in reason for reason in result.reasons)
    assert any("verifier_status" in reason for reason in result.reasons)


def test_p0_02_effective_n_uses_independent_events_not_daily_rows():
    sampling = SamplingDesign(
        signal_unit="independent_event",
        horizon_days=20,
        overlap_policy="block_bootstrap",
        minimum_effective_n=60,
        nominal_n=1000,
        block_length_days=20,
    )

    assert sampling.effective_n() == 50
    assert any("effective_n below" in failure for failure in sampling.gate_failures())


def test_p0_01_multiple_testing_uses_family_fdr():
    q_values = benjamini_hochberg_q_values((0.003, 0.04, 0.08, 0.20))
    control = MultipleTestingControl(
        method="benjamini_hochberg_fdr",
        max_fdr=0.10,
        family_p_values=(0.003, 0.04, 0.08, 0.20),
        selected_trial_index=0,
    )

    assert q_values[0] == 0.012
    assert control.adjusted_q_value == 0.012
    assert control.gate_failures() == ()


def test_p0_03_pre_registration_freezes_specification_search():
    spec = {
        "hypothesis": "central-bank liquidity supports risk appetite",
        "rule_ids": ("macro.central_bank.soft.001",),
        "parameter_paths": (
            "/rule_packs/macro.central_bank.liquidity.v1/rules/"
            "macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value",
        ),
        "candidate_values": (5, 10, 20),
        "primary_metric": "net_alpha_after_cost_20d",
        "secondary_metrics": ("hit_rate",),
        "data_requirements": ("pboc_net_injection_7d",),
        "sampling_design": {"minimum_effective_n": 60},
        "validation_design": {"walk_forward_required": True},
        "multiple_testing_control": {"method": "benjamini_hochberg_fdr"},
        "acceptance_rule": {"cost_model_required": True},
    }
    prereg = PreRegistration.freeze(registered_at="2026-06-05T11:00:00+09:00", spec=spec)

    assert prereg.gate_failures(spec) == ()
    changed = {**spec, "candidate_values": (5, 10, 20, 40)}
    assert any("frozen_spec_hash" in failure for failure in prereg.gate_failures(changed))


def test_p0_01_validation_experiment_is_cost_aware_walk_forward_and_no_direct_production():
    mvp = build_central_bank_p0_mvp()
    decision = evaluate_validation_experiment(
        mvp["experiment"],
        data_matrix=mvp["data_matrix"],
    )

    assert decision.status == "paper_trading"
    assert decision.paper_trading_allowed
    assert not decision.production_allowed
    assert decision.report["effective_n"] >= 60
    assert decision.report["adjusted_q_value"] <= 0.10
    assert decision.report["net_alpha_after_cost"] > 0.005
    assert decision.report["walk_forward_passed"]
    assert not decision.report["lockbox_passed"]


def test_p0_01_cost_aware_acceptance_blocks_gross_only_alpha():
    cost = CostAwareAcceptance(
        primary_metric="gross_alpha_20d",
        gross_alpha=0.020,
        estimated_transaction_cost=0.010,
        slippage=0.006,
        turnover_delta=0.25,
        max_turnover_delta=0.20,
        drawdown_worsening=0.01,
        max_drawdown_worsening=0.02,
        min_net_alpha=0.005,
    )

    failures = cost.gate_failures()

    assert any("after-cost" in failure for failure in failures)
    assert any("net alpha" in failure for failure in failures)
    assert any("turnover" in failure for failure in failures)


def test_p0_05_runtime_aggregation_dedupes_groups_and_emits_conflicts():
    rules = (
        RuleFireOutput(
            rule_id="macro.central_bank.soft.001",
            rule_group_id="macro.central_bank.liquidity",
            target_signal="risk_appetite",
            direction="positive",
            raw_score_delta=0.09,
            horizon_days=20,
            validation_status="paper_trading",
            empirical_confidence_bin="medium",
            evidence_ids=("E1",),
            source_claim_ids=("CLAIM-CB-1",),
        ),
        RuleFireOutput(
            rule_id="macro.central_bank.soft.002",
            rule_group_id="macro.central_bank.liquidity",
            target_signal="risk_appetite",
            direction="positive",
            raw_score_delta=0.08,
            horizon_days=20,
            validation_status="paper_trading",
            empirical_confidence_bin="medium",
            evidence_ids=("E2",),
            source_claim_ids=("CLAIM-CB-2",),
        ),
        RuleFireOutput(
            rule_id="macro.china.soft.001",
            rule_group_id="macro.china.policy_uncertainty",
            target_signal="risk_appetite",
            direction="negative",
            raw_score_delta=0.07,
            horizon_days=20,
            validation_status="paper_trading",
            empirical_confidence_bin="medium",
            evidence_ids=("E3",),
            source_claim_ids=("CLAIM-CN-1",),
        ),
    )

    result = aggregate_rule_outputs(
        rules,
        target_signal="risk_appetite",
        horizon_days=20,
        policy=RuleAggregationPolicy(),
    )

    assert set(result.group_deltas) == {
        "macro.central_bank.liquidity",
        "macro.china.policy_uncertainty",
    }
    assert abs(result.group_deltas["macro.central_bank.liquidity"]) <= 0.10
    assert abs(result.final_research_delta) <= 0.20
    assert result.conflict_objects
    assert result.evidence_clusters["macro.central_bank.liquidity"] == ("E1", "E2")


def test_p0_06_confidence_uses_min_component_and_research_only_no_trade():
    result = compute_confidence_v1(
        ConfidenceComponents(
            data_confidence=0.90,
            research_confidence=0.80,
            empirical_validation_confidence=0.70,
            regime_match_confidence=0.75,
        ),
        confidence_cap=0.85,
        current_data_confirmed=True,
    )
    assert result.final_confidence == 0.70
    assert result.actionability == "modest_tilt"

    research_only = compute_confidence_v1(
        ConfidenceComponents(0.90, 0.90, 0.90, 0.90),
        current_data_confirmed=False,
    )
    assert research_only.final_confidence == 0.50
    assert research_only.actionability == "no_trade"
    assert check_research_only_actionability(
        research_only=True,
        current_data_confirmed=False,
        actionability="modest_tilt",
    )


def test_p0_08_central_bank_first_mvp_deliverables_are_present_and_valid():
    mvp = build_central_bank_p0_mvp()
    rule_pack = mvp["rule_pack"]
    parameter_prior = mvp["parameter_prior"]
    claim = mvp["claim"]
    hypothesis = mvp["hypothesis"]
    data_matrix = mvp["data_matrix"]

    assert rule_pack.rule_pack_id == "macro.central_bank.liquidity.v1"
    assert rule_pack.gate_failures(
        data_matrix=data_matrix,
        known_claim_ids={claim.claim_id},
        known_hypothesis_ids={hypothesis.hypothesis_id},
    ) == ()
    assert parameter_prior.gate_failures() == ()


def test_rule_identity_and_target_paths_follow_master_plan():
    path = (
        "/rule_packs/macro.central_bank.liquidity.v1/rules/"
        "macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value"
    )

    assert validate_rule_id("macro.central_bank.soft.001")
    assert not validate_rule_id("CB_LIQ_SOFT_001")
    assert validate_rule_pack_id("macro.central_bank.liquidity.v1")
    assert validate_target_path(path)["valid"]

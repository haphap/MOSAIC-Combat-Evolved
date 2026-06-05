from __future__ import annotations

import pytest

from mosaic.rke import (
    ClaimAnnotation,
    LearnableParameter,
    build_central_bank_p0_mvp,
    compile_rule_pack,
    default_evolution_targets,
    extract_claims_from_annotations,
    generate_parameter_prior,
    ingest_source_row,
    plan_parameter_update,
    run_empirical_validation,
    validate_patch,
    verify_claim_batch,
)


def _source_row():
    claim_text = "PBOC liquidity injections can ease short-term liquidity pressure."
    return {
        "source_id": "SRC-PIPE-CB-20260605-0001",
        "source_span_id": "SRC-PIPE-CB-20260605-0001:abstract",
        "source_type": "official_pboc_policy_notice_seed",
        "publish_date": "2026-06-05",
        "ingest_time": "2026-06-05T11:00:00+08:00",
        "license_status": "approved",
        "point_in_time_available": True,
        "title": "Central bank liquidity seed",
        "abstract": f"{claim_text} The market-transmission statement remains a hypothesis.",
    }


def test_research_pipeline_compiles_validated_central_bank_candidate_rule():
    mvp = build_central_bank_p0_mvp()
    document = ingest_source_row(_source_row())
    annotations = (
        ClaimAnnotation(
            claim_id="CLAIM-PIPE-CB-20260605-0001",
            source_span_id="SRC-PIPE-CB-20260605-0001:abstract",
            claim_type="causal_mechanism",
            claim_text="PBOC liquidity injections can ease short-term liquidity pressure.",
            cause_variables=("pboc_net_injection",),
            target_variables=("short_term_liquidity_pressure",),
            direction="positive",
            extraction_confidence_bin="medium",
            hypothesis_id="HYP-PIPE-CB-20260605-0001",
            hypothesis_type="market_transmission",
            hypothesis_statement=(
                "A confirmed liquidity impulse can support short-horizon risk appetite."
            ),
            hypothesis_metric_proxies=("pboc_net_injection_7d", "risk_appetite_proxy"),
        ),
    )

    claims, hypotheses = extract_claims_from_annotations(document, annotations)
    verified = verify_claim_batch(
        claims,
        source_spans=document.source_spans,
        controlled_variables={"pboc_net_injection", "short_term_liquidity_pressure"},
    )
    rule_pack = compile_rule_pack(
        rule_pack_id="macro.central_bank.liquidity.v1",
        agent_id="macro.central_bank",
        rule_id="macro.central_bank.soft.001",
        claims=verified.claims,
        hypotheses=hypotheses,
        metric_proxies=("pboc_net_injection_7d", "risk_appetite_proxy"),
        mechanism_chain=(
            "pboc_net_injection",
            "short_term_liquidity_pressure",
            "risk_appetite_proxy",
        ),
        horizon_days=(20, 20),
        learnable_parameters={
            "net_injection_window_days": LearnableParameter(
                value=7,
                type="integer",
                unit="trading_day",
                min=3,
                max=20,
            )
        },
        data_matrix=mvp["data_matrix"],
    )
    prior = generate_parameter_prior(
        parameter_proposal_id="PARAM-PIPE-CB-20260605-0001",
        rule_pack=rule_pack,
        rule_id="macro.central_bank.soft.001",
        parameter_name="net_injection_window_days",
        candidate_values=(5, 10, 20),
        rationale="Use a short confirmation window before validation.",
    )
    validation_report = run_empirical_validation(
        mvp["experiment"],
        data_matrix=mvp["data_matrix"],
    )
    mutation = plan_parameter_update(
        mutation_id="MUT-PIPE-CB-20260605-0001",
        source_experiment_id=mvp["experiment"].experiment_id,
        parameter_prior=prior,
        validation_decision=validation_report.decision,
        selected_value=10,
        risk="May respond more slowly to very short liquidity shocks.",
    )
    patch_check = validate_patch(
        mutation,
        current_registry={prior.target_path: 7},
        parameter_types={
            prior.target_path: rule_pack.rules[
                "macro.central_bank.soft.001"
            ].learnable_parameters["net_injection_window_days"]
        },
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={mvp["experiment"].experiment_id},
    )

    assert document.metadata.gate_failures() == ()
    assert verified.passed_claim_ids == {"CLAIM-PIPE-CB-20260605-0001"}
    assert hypotheses[0].not_source_grounded
    assert rule_pack.gate_failures(
        data_matrix=mvp["data_matrix"],
        known_claim_ids={verified.claims[0].claim_id},
        known_hypothesis_ids={hypotheses[0].hypothesis_id},
    ) == ()
    assert prior.candidate_values == (7, 5, 10, 20)
    assert validation_report.paper_trading_ready
    assert validation_report.hardened_metrics["effective_n"] >= 60
    assert mutation.target_path == prior.target_path
    assert patch_check.accepted


def test_rule_pack_compiler_rejects_unverified_claims():
    mvp = build_central_bank_p0_mvp()
    document = ingest_source_row(_source_row())
    claims, hypotheses = extract_claims_from_annotations(
        document,
        (
            ClaimAnnotation(
                claim_id="CLAIM-PIPE-BAD",
                source_span_id="SRC-PIPE-CB-20260605-0001:abstract",
                claim_type="causal_mechanism",
                claim_text="This sentence is not in the source span.",
                cause_variables=("pboc_net_injection",),
                target_variables=("short_term_liquidity_pressure",),
                direction="positive",
            ),
        ),
    )
    verified = verify_claim_batch(
        claims,
        source_spans=document.source_spans,
        controlled_variables={"pboc_net_injection", "short_term_liquidity_pressure"},
    )

    with pytest.raises(ValueError, match="claims must pass verifier"):
        compile_rule_pack(
            rule_pack_id="macro.central_bank.liquidity.v1",
            agent_id="macro.central_bank",
            rule_id="macro.central_bank.soft.001",
            claims=verified.claims,
            hypotheses=hypotheses,
            metric_proxies=("pboc_net_injection_7d",),
            mechanism_chain=("pboc_net_injection", "risk_appetite_proxy"),
            horizon_days=(20, 20),
            learnable_parameters={
                "net_injection_window_days": LearnableParameter(
                    value=7,
                    type="integer",
                    min=3,
                    max=20,
                )
            },
            data_matrix=mvp["data_matrix"],
        )

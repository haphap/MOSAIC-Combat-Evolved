from __future__ import annotations

from mosaic.rke import (
    ResearchSourceMetadata,
    build_central_bank_mvp_bundle,
    check_agent_runtime_output,
    check_claim_grounding,
    check_experiment,
    check_production_patch,
    check_rule_pack,
    check_source_metadata,
    default_evolution_targets,
)


def test_unified_checkers_accept_central_bank_mvp_chain():
    bundle = build_central_bank_mvp_bundle()
    artifacts = bundle.artifacts
    rule_pack = artifacts["rule_pack"]
    rule = rule_pack.rules["macro.central_bank.soft.001"]
    target_path = artifacts["parameter_prior"].target_path

    source_result = check_source_metadata(artifacts["source_metadata"])
    claim_result = check_claim_grounding(
        artifacts["claim"],
        source_spans={
            artifacts["claim"].source_span_id: artifacts["claim"].claim_text,
        },
        controlled_variables={"pboc_net_injection", "short_term_liquidity_pressure"},
    )
    rule_pack_result = check_rule_pack(
        rule_pack,
        data_matrix=artifacts["data_matrix"],
        known_claim_ids={artifacts["claim"].claim_id},
        known_hypothesis_ids={artifacts["hypothesis"].hypothesis_id},
    )
    experiment_result = check_experiment(
        artifacts["experiment"],
        data_matrix=artifacts["data_matrix"],
    )
    patch_result = check_production_patch(
        artifacts["production_patch"],
        current_registry={target_path: 7},
        parameter_types={
            target_path: rule.learnable_parameters["net_injection_window_days"],
        },
        evolution_targets=default_evolution_targets(),
        valid_experiment_ids={artifacts["experiment"].experiment_id},
    )
    runtime_result = check_agent_runtime_output(
        bundle.runtime_output,
        verified_claim_ids={artifacts["claim"].claim_id},
        confidence_cap=0.64,
    )

    assert source_result.accepted
    assert claim_result.accepted
    assert rule_pack_result.accepted
    assert experiment_result.accepted
    assert patch_result.accepted
    assert runtime_result.accepted


def test_source_checker_rejects_prohibited_or_non_pit_sources():
    result = check_source_metadata(
        ResearchSourceMetadata(
            source_id="SRC-BAD",
            source_type="sell_side_report",
            publish_date="2026-06-05",
            ingest_time="2026-06-05T12:00:00+08:00",
            license_status="prohibited",
            point_in_time_available=False,
            source_hash="sha256:bad",
        )
    )

    assert not result.accepted
    assert "prohibited source cannot be ingested" in result.reasons
    assert "source lacks PIT availability" in result.reasons


def test_runtime_checker_wrapper_preserves_research_only_gate():
    bundle = build_central_bank_mvp_bundle()
    artifacts = bundle.artifacts

    result = check_agent_runtime_output(
        bundle.runtime_output,
        verified_claim_ids={artifacts["claim"].claim_id},
        confidence_cap=0.64,
        research_only=True,
    )

    assert not result.accepted
    assert any("research-only" in reason for reason in result.reasons)

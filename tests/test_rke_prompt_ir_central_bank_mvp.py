from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    build_central_bank_mvp_bundle,
    build_central_bank_prompt_ir,
    render_prompt_markdown,
    validate_prompt_ir_contract,
    write_central_bank_mvp_registry,
)


def test_central_bank_prompt_ir_contract_enforces_runtime_boundaries():
    contract = build_central_bank_prompt_ir()

    failures = validate_prompt_ir_contract(contract)

    assert failures == ()
    assert contract.agent_id == "macro.central_bank"
    assert "final_portfolio_sizing" in contract.role_contract.must_not_decide
    assert {tool.name for tool in contract.required_tools} == {"get_pboc_ops"}
    tool = contract.required_tools[0]
    assert tool.metric_ids == ("pboc_net_injection_7d",)
    assert tool.metric_candidate_ids == ("METRIC-CB-PBOC-NET-INJECTION-7D",)
    assert tool.analysis_recipe_ids == ("RECIPE-CB-LIQUIDITY-IMPULSE",)
    assert tool.pit_required_for_backtest is True
    assert tool.fallback_confidence_cap == 0.60
    assert tool.lineage["tool_proposal_id"] == "TDP-CB-PBOC-OMO"
    assert contract.output_schema_ref == "agent_output_schema.v2"
    assert "/role_contract" in contract.evolution_targets.forbidden_paths
    assert (
        "/analysis_recipe_registry/*/runtime_mode"
        in contract.evolution_targets.allowed_paths
    )
    assert "/sector_score" in contract.evolution_targets.forbidden_paths
    assert (
        "production_blocked_until_manual_gold_license_and_lockbox_gates_pass"
        in contract.guardrails
    )


def test_central_bank_mvp_bundle_reaches_paper_trading_but_blocks_broad_rollout():
    bundle = build_central_bank_mvp_bundle()
    artifacts = bundle.artifacts

    assert artifacts["prompt_ir_failures"] == ()
    assert artifacts["validation_decision"].status == "paper_trading"
    assert artifacts["runtime_output_check"].accepted
    assert artifacts["patch_validation"].accepted
    assert artifacts["mutation_validation"].accepted
    assert artifacts["paper_trading_summary"]["ready"]
    assert artifacts["production_monitor"].state == "production"
    assert artifacts["audit_trace_failures"] == ()
    assert not bundle.completion_audit.ready_for_broad_rollout
    assert "manual gold-set review still required" in bundle.completion_audit.blockers
    assert "source license review still pending" in bundle.completion_audit.blockers


def test_central_bank_registry_writer_emits_schema_aligned_artifacts(tmp_path: Path):
    outputs = write_central_bank_mvp_registry(tmp_path)

    for path in outputs.values():
        assert Path(path).exists()

    data_matrix = json.loads(Path(outputs["data_availability"]).read_text(encoding="utf-8"))
    experiment = json.loads(Path(outputs["experiment"]).read_text(encoding="utf-8"))
    completion_audit = json.loads(Path(outputs["completion_audit"]).read_text(encoding="utf-8"))
    source_rows = [
        json.loads(line)
        for line in Path(outputs["source_metadata"]).read_text(encoding="utf-8").splitlines()
    ]
    claim_rows = [
        json.loads(line) for line in Path(outputs["claims"]).read_text(encoding="utf-8").splitlines()
    ]

    assert data_matrix["matrix_id"] == "DAM-CB-P0-2026Q2"
    assert "pboc_net_injection_7d" in data_matrix["proxies"]
    assert experiment["experiment_family_id"] == "FAM-CB-LIQUIDITY-2026Q2"
    assert experiment["pre_registered"] is True
    assert experiment["sampling_design"]["effective_n"] >= 60
    assert experiment["multiple_testing_control"]["adjusted_q_value"] <= 0.10
    assert source_rows[0]["source_id"] == claim_rows[0]["source_id"]
    assert completion_audit["criteria"][1]["passed"] is False

    rendered_prompt = Path(outputs["rendered_prompt_markdown"]).read_text(encoding="utf-8")
    rendered_metadata = json.loads(Path(outputs["rendered_prompt_metadata"]).read_text(encoding="utf-8"))
    prompt_ir = json.loads(Path(outputs["prompt_ir"]).read_text(encoding="utf-8"))
    runtime_input = json.loads(Path(outputs["runtime_input"]).read_text(encoding="utf-8"))
    mutation_patch = json.loads(Path(outputs["mutation_patch"]).read_text(encoding="utf-8"))
    prompt_asset_validation = json.loads(
        Path(outputs["prompt_asset_validation"]).read_text(encoding="utf-8")
    )
    claim_variable_validation = json.loads(
        Path(outputs["claim_variable_validation"]).read_text(encoding="utf-8")
    )
    statistical_significance = json.loads(
        Path(outputs["statistical_significance"]).read_text(encoding="utf-8")
    )
    source_registry_validation = json.loads(
        Path(outputs["source_registry_validation"]).read_text(encoding="utf-8")
    )

    assert "## Output Schema" in rendered_prompt
    assert "research_only_no_trade" in rendered_prompt
    assert rendered_metadata["output_schema_ref"] == "agent_output_schema.v2"
    assert prompt_ir["required_tools"][0]["metric_ids"] == [
        "pboc_net_injection_7d"
    ]
    assert prompt_ir["required_tools"][0]["metric_candidate_ids"] == [
        "METRIC-CB-PBOC-NET-INJECTION-7D"
    ]
    assert runtime_input["active_rule_packs"] == ["macro.central_bank.liquidity.v1"]
    assert mutation_patch["mutation"]["mutation_id"] == "MUT-CB-20260605-0001"
    assert mutation_patch["validation"]["accepted"] is True
    assert mutation_patch["production_allowed"] is False
    production_patch = json.loads(Path(outputs["patch"]).read_text(encoding="utf-8"))
    assert production_patch["patch_type"] == "parameter_update"
    assert prompt_asset_validation["accepted"] is True
    assert claim_variable_validation["accepted"] is True
    assert source_registry_validation["accepted_for_sandbox"] is True
    assert statistical_significance["accepted"] is True


def test_render_prompt_markdown_keeps_schema_and_guardrails():
    bundle = build_central_bank_mvp_bundle()
    text = render_prompt_markdown(bundle.prompt_ir, bundle.artifacts["runtime_input"])

    assert "# macro.central_bank RKE Runtime Prompt" in text
    assert "get_pboc_ops" in text
    assert "METRIC-CB-PBOC-NET-INJECTION-7D" in text
    assert "RECIPE-CB-LIQUIDITY-IMPULSE" in text
    assert "AFP-CB-LIQUIDITY-IMPULSE" in text
    assert "TDP-CB-PBOC-OMO" in text
    assert "output_schema_ref: agent_output_schema.v2" in text
    assert "research_reports_are_prior_not_signal" in text
    assert "production_blocked_until_manual_gold_license_and_lockbox_gates_pass" in text

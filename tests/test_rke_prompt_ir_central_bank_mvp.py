from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    build_central_bank_mvp_bundle,
    build_central_bank_prompt_ir,
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
    assert contract.output_schema_ref == "agent_output_schema.v2"
    assert "/role_contract" in contract.evolution_targets.forbidden_paths


def test_central_bank_mvp_bundle_reaches_paper_trading_but_blocks_broad_rollout():
    bundle = build_central_bank_mvp_bundle()
    artifacts = bundle.artifacts

    assert artifacts["prompt_ir_failures"] == ()
    assert artifacts["validation_decision"].status == "paper_trading"
    assert artifacts["runtime_output_check"].accepted
    assert artifacts["patch_validation"].accepted
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

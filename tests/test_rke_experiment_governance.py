from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from mosaic.rke import (
    build_experiment_governance_bundle,
    check_experiment_governance,
    validate_experiment_governance_bundle,
    write_central_bank_mvp_registry,
    write_experiment_governance_registry,
)


def test_experiment_governance_bundle_matches_current_registry():
    bundle = build_experiment_governance_bundle(".")
    result = check_experiment_governance(bundle)

    assert result.accepted
    assert bundle.experiment_family.family_id == "FAM-CB-LIQUIDITY-2026Q2"
    assert bundle.experiment_family.adjusted_q_value == 0.012
    assert bundle.cost_model.primary_metric == "net_alpha_after_cost_20d"
    assert bundle.cost_model.net_alpha_after_cost > bundle.cost_model.min_net_alpha
    assert bundle.effective_n_overlap_policy.overlap_policy == "block_bootstrap"
    assert bundle.effective_n_overlap_policy.effective_n == 80
    assert bundle.effective_n_overlap_policy.gate_status == "passed"
    assert bundle.lockbox_policy.policy_status == "paper_trading_only"


def test_experiment_governance_checker_rejects_bad_policy():
    bundle = build_experiment_governance_bundle(".")
    bad_bundle = replace(
        bundle,
        lockbox_policy=replace(
            bundle.lockbox_policy,
            direct_production_allowed=True,
        ),
        effective_n_overlap_policy=replace(
            bundle.effective_n_overlap_policy,
            effective_n=10,
        ),
    )

    failures = validate_experiment_governance_bundle(bad_bundle)

    assert "direct production promotion is forbidden" in failures
    assert "effective_n below minimum_effective_n" in failures
    assert not check_experiment_governance(bad_bundle).accepted


def test_write_experiment_governance_registry(tmp_path: Path):
    write_central_bank_mvp_registry(tmp_path)
    outputs = write_experiment_governance_registry(tmp_path)

    assert {
        "baseline_versions",
        "experiment_family",
        "pre_registration",
        "cost_model",
        "effective_n_overlap_policy",
        "lockbox_policy",
    } <= set(outputs)
    for path in outputs.values():
        assert Path(path).exists()

    family = json.loads(Path(outputs["experiment_family"]).read_text(encoding="utf-8"))
    prereg = json.loads(Path(outputs["pre_registration"]).read_text(encoding="utf-8"))
    experiment = json.loads(
        (tmp_path / "registry/experiments/central_bank_validation_experiment_v2.json").read_text(
            encoding="utf-8"
        )
    )

    assert family["selected_experiment_id"] == "EXP-CB-20260605-0001"
    assert prereg["protocol_status"] == "frozen"
    assert experiment["acceptance_rule"]["gross_alpha"] == 0.018
    assert experiment["acceptance_rule"]["net_alpha_after_cost"] == 0.013

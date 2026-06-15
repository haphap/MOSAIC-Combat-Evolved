from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    AblationResult,
    RegimeBucketObservation,
    StatisticalSignificanceInput,
    build_central_bank_statistical_significance_report,
    check_ablation_coverage,
    check_horizon_metric_alignment,
    check_scoring_precision,
    evaluate_statistical_significance,
    evaluate_regime_partial_pooling,
)
from mosaic.rke.cli import main


def test_regime_partial_pooling_shrinks_small_buckets():
    report = evaluate_regime_partial_pooling(
        (
            RegimeBucketObservation("risk_on", raw_delta=0.018, effective_n=44),
            RegimeBucketObservation("risk_off", raw_delta=-0.010, effective_n=23),
            RegimeBucketObservation("neutral", raw_delta=0.013, effective_n=80),
        ),
        global_delta=0.013,
    )

    assert report.regime_effects["risk_on"].gate_status == "auxiliary_evidence"
    assert report.regime_effects["risk_off"].gate_status == "insufficient_data"
    assert report.regime_effects["neutral"].gate_status == "regime_specific_gate"
    assert report.regime_effects["risk_off"].shrunk_delta == 0.003019
    assert any("risk_off" in failure for failure in report.failures)


def test_ablation_coverage_requires_all_master_plan_tests():
    accepted = check_ablation_coverage(
        (
            AblationResult("single_rule", passed=True, metric_delta=0.012),
            AblationResult("rule_group", passed=True, metric_delta=0.011),
            AblationResult("correlated_rule_dedup", passed=True, metric_delta=0.003),
            AblationResult("interaction", passed=True, metric_delta=0.002),
            AblationResult("aggregation_level_backtest", passed=True, metric_delta=0.013),
        )
    )
    rejected = check_ablation_coverage(
        (
            AblationResult("single_rule", passed=True, metric_delta=0.012),
            AblationResult("rule_group", passed=False, metric_delta=-0.001),
        )
    )

    assert accepted.accepted
    assert not rejected.accepted
    assert any("missing ablation" in reason for reason in rejected.reasons)
    assert any("rule_group" in reason for reason in rejected.reasons)


def test_horizon_metric_alignment_blocks_mismatched_primary_metric():
    assert check_horizon_metric_alignment(
        horizon_days=(20, 60),
        primary_metric="net_alpha_after_cost_20d",
        secondary_metrics=("net_alpha_after_cost_60d",),
    ) == ()

    failures = check_horizon_metric_alignment(
        horizon_days=(20, 60),
        primary_metric="net_alpha_after_cost_120d",
        secondary_metrics=("hit_rate_20d",),
    )

    assert failures == ("primary metric horizon does not match rule horizon",)


def test_scoring_precision_rejects_false_quality_scores():
    assert check_scoring_precision(
        {
            "source_quality": "high",
            "research_strength": "medium",
            "empirical_confidence_bin": "low",
        }
    ) == ()

    failures = check_scoring_precision(
        {
            "source_quality_score": 0.72,
            "research_strength": 0.61,
        }
    )

    assert "source_quality_score: false precision score is not allowed" in failures
    assert "research_strength: use coarse quality bin high/medium/low/unknown" in failures


def test_statistical_significance_requires_positive_ci_and_dsr():
    accepted = build_central_bank_statistical_significance_report()
    rejected = evaluate_statistical_significance(
        StatisticalSignificanceInput(
            experiment_id="EXP-BAD",
            metric_name="net_alpha_after_cost_20d",
            mean_effect=0.003,
            standard_error=0.004,
            effective_n=80,
            minimum_effective_n=60,
            tested_specification_count=5,
            observed_sharpe=0.2,
            deflated_sharpe_ratio=0.8,
        )
    )

    assert accepted.accepted
    assert accepted.confidence_interval["low"] > 0
    assert accepted.deflated_sharpe_ratio >= accepted.minimum_deflated_sharpe_ratio
    assert not rejected.accepted
    assert "after-cost confidence interval includes zero" in rejected.failures
    assert "deflated_sharpe_ratio below threshold" in rejected.failures


def test_central_bank_validation_hardening_registry_is_parseable():
    payload = json.loads(
        Path("registry/validation_hardening/central_bank_hardening_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["experiment_id"] == "EXP-CB-20260605-0001"
    assert payload["ablation_checks"]["accepted"] is True
    assert payload["horizon_metric_failures"] == []
    assert payload["precision_failures"] == []
    assert payload["statistical_significance_ref"] == (
        "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"
    )
    assert payload["regime_partial_pooling"]["regime_effects"]["risk_off"]["gate_status"] == (
        "insufficient_data"
    )


def test_central_bank_statistical_significance_registry_is_parseable():
    payload = json.loads(
        Path("registry/evaluation/statistical_significance/central_bank_after_cost_significance.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["experiment_id"] == "EXP-CB-20260605-0001"
    assert payload["accepted"] is True
    assert payload["confidence_interval"]["low"] > 0
    assert payload["deflated_sharpe_ratio"] >= payload["minimum_deflated_sharpe_ratio"]


def test_validation_status_cli_writes_reports(tmp_path: Path, capsys):
    shutil.copytree(Path("registry"), tmp_path / "registry")

    code = main(("validation-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["statistical_significance"]["accepted"] is True
    assert (
        tmp_path / "registry/validation_hardening/central_bank_hardening_report.json"
    ).exists()
    assert Path(
        tmp_path
        / "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"
    ).exists()

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.autoresearch.domain_evaluator import (
    DEFAULT_EVALUATION_CONTRACT_PATH,
    DomainEvaluationError,
    evaluate_domain_mutation,
    load_evaluation_contract,
)
from mosaic.autoresearch.domain_metrics import calculate_rank_correlation


def _binding_and_metric(*, direction: str = "higher_is_better"):
    contract = load_evaluation_contract()
    binding = next(
        binding
        for binding in contract["card_bindings"]
        if binding["activation_state"] == "active"
        and contract["evaluation_metrics"][binding["evaluation_metric"]]["direction"]
        == direction
    )
    metric = contract["evaluation_metrics"][binding["evaluation_metric"]]
    calculator = contract["evaluation_calculators"][metric["calculator_id"]]
    return contract, binding, metric, calculator


def _metadata(contract, binding, metric, calculator):
    return {
        "schema_version": "knob_mutation_metadata_v1",
        "mutation_id": "KM-domain-test",
        "transaction_id": "TX-KM-domain-test",
        "experiment_id": "EXP-KM-domain-test",
        "mutation_kind": "domain_knob",
        "agent": binding["owner_agent"].split(".", 1)[1],
        "owner_agent": binding["owner_agent"],
        "owner_stage": binding["owner_stage"],
        "changed_paths": [binding["path"]],
        "domain_card_id": binding["card_id"],
        "domain_card_ids": [binding["card_id"]],
        "prediction_target": binding["prediction_target"],
        "evaluation_metric": metric["id"],
        "horizon": binding["horizon"],
        "rollback_condition": binding["rollback_condition"],
        "base_knobs_sha256": f"sha256:{'1' * 64}",
        "catalog_version": contract["catalog_version"],
        "catalog_hash": contract["catalog_hash"],
        "schema_hash": contract["schema_hash"],
        "evaluation_contract_hash": contract["contract_hash"],
        "metric_registry_hash": contract["metric_registry_hash"],
        "calculator_registry_hash": contract["calculator_registry_hash"],
        "calculator_id": calculator["id"],
        "calculator_version": calculator["version"],
        "evaluation_policy": {
            "baseline_id": f"sha256:{'1' * 64}",
            "baseline": metric["baseline"],
            "min_effect_size": 0.0,
            "min_sample_size": metric["min_sample_size"],
            "uncertainty_method": metric["uncertainty_method"],
            "overlapping_sample_policy": metric["overlapping_sample_policy"],
            "require_uncertainty_bound": True,
        },
    }


def _arm(calculator_id: str, value: float):
    if calculator_id == "pit.signed_return":
        return {"signed_return": value}
    if calculator_id == "pit.nonnegative_loss":
        return {"loss_magnitude": value}
    if calculator_id == "pit.bps_cost":
        return {"cost_bps": value}
    if calculator_id == "pit.rate":
        return {"event": int(value)}
    if calculator_id == "pit.calibration_error":
        return {"probability": value, "outcome": 1}
    if calculator_id == "pit.rank_correlation":
        return {"scores": [1, 2, 3], "outcomes": [1, 2, 3]}
    raise AssertionError(calculator_id)


def _manifest(metadata, calculator, baseline_value: float, treatment_value: float, count=30):
    source_type = "execution_record" if calculator["id"] == "pit.bps_cost" else "pit_outcome"
    return {
        "schema_version": "domain_evaluation_sample_manifest_v1",
        "mutation_id": metadata["mutation_id"],
        "evaluation_as_of": "2026-06-30T00:00:00+00:00",
        "sample_window": {
            "start": "2026-01-01T00:00:00+00:00",
            "end": "2026-06-30T00:00:00+00:00",
        },
        "decision_evidence_refs": ["episode:EXP-KM-domain-test"],
        "samples": [
            {
                "sample_id": f"sample-{index:03d}",
                "source_type": source_type,
                "horizon": metadata["horizon"],
                "observed_at": "2026-01-01T00:00:00+00:00",
                "label_available_at": "2026-02-01T00:00:00+00:00",
                "data_vintage_hash": f"sha256:{index:064x}",
                "pit_valid": True,
                "mature": True,
                "exclusion_reasons": [],
                "baseline": _arm(calculator["id"], baseline_value),
                "treatment": _arm(calculator["id"], treatment_value),
                "evidence_refs": [f"outcome:{index:03d}"],
                "regime": "normal" if index % 2 else "stress",
            }
            for index in range(count)
        ],
    }


def test_generated_contract_hashes_validate():
    contract = load_evaluation_contract()
    assert contract["contract_hash"].startswith("sha256:")
    assert len(contract["evaluation_metrics"]) >= 1


def test_contract_tampering_fails_closed(tmp_path: Path):
    contract = json.loads(DEFAULT_EVALUATION_CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["catalog_hash"] = f"sha256:{'0' * 64}"
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(DomainEvaluationError, match="contract hash mismatch"):
        load_evaluation_contract(path)


def test_higher_is_better_metric_can_become_eligible():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"])

    result = evaluate_domain_mutation(metadata, manifest)

    assert result["status"] == "eligible_for_promotion"
    assert result["metric_id"] == metric["id"]
    assert result["sample_count"] == metric["min_sample_size"]
    assert result["effect_size"] == pytest.approx(0.02)
    assert result["rollback_triggered"] is False
    assert result["pit_audit_hash"].startswith("sha256:")


def test_lower_is_better_metric_uses_card_rollback_direction():
    contract, binding, metric, calculator = _binding_and_metric(direction="lower_is_better")
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 1.0, metric["min_sample_size"])

    result = evaluate_domain_mutation(metadata, manifest)

    assert result["status"] == "reverted"
    assert result["new_value"] > result["baseline_value"]
    assert result["improvement"] < 0


def test_insufficient_mature_common_support_needs_fill():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"] - 1)

    result = evaluate_domain_mutation(metadata, manifest)

    assert result["status"] == "needs_fill"
    assert result["required_sample_count"] == metric["min_sample_size"]


def test_catalog_hash_drift_and_inactive_cards_are_rejected():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    metadata["catalog_hash"] = f"sha256:{'0' * 64}"
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"])
    with pytest.raises(DomainEvaluationError, match="catalog_hash"):
        evaluate_domain_mutation(metadata, manifest)

    inactive = next(
        item for item in contract["card_bindings"] if item["activation_state"] != "active"
    )
    inactive_metric = contract["evaluation_metrics"][inactive["evaluation_metric"]]
    inactive_calculator = contract["evaluation_calculators"][inactive_metric["calculator_id"]]
    metadata = _metadata(contract, inactive, inactive_metric, inactive_calculator)
    manifest = _manifest(
        metadata, inactive_calculator, 0.0, 0.02, inactive_metric["min_sample_size"]
    )
    with pytest.raises(DomainEvaluationError, match="not active"):
        evaluate_domain_mutation(metadata, manifest)


def test_prompt_rationale_is_not_a_calculator_input():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"])
    result_without_rationale = evaluate_domain_mutation(metadata, manifest)
    for sample in manifest["samples"]:
        sample["prompt_rationale"] = "LLM says this mutation is excellent"
        sample["llm_confidence"] = 1.0
    result_with_rationale = evaluate_domain_mutation(metadata, manifest)
    assert result_with_rationale == result_without_rationale


def test_rank_correlation_calculator_is_deterministic():
    sample = {
        "baseline": {"scores": [10, 20, 30, 40], "outcomes": [1, 2, 3, 4]},
        "treatment": {"scores": [40, 30, 20, 10], "outcomes": [1, 2, 3, 4]},
    }
    assert calculate_rank_correlation(sample, "baseline") == pytest.approx(1.0)
    assert calculate_rank_correlation(sample, "treatment") == pytest.approx(-1.0)

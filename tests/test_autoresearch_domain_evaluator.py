from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from mosaic.autoresearch.domain_evaluator import (
    DEFAULT_EVALUATION_CONTRACT_PATH,
    DomainEvaluationError,
    _uncertainty,
    domain_sample_manifest_hash,
    evaluate_domain_mutation,
    load_evaluation_contract,
)
from mosaic.autoresearch.domain_metrics import calculate_rank_correlation
from mosaic.rke.schema_validation import validate_json_schema_artifact


def _canonical_hash(value):
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


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
    generic = "card_id" not in binding
    secondary_metrics = binding.get(
        "secondary_metrics", binding.get("evaluation_metrics", [])
    )
    evaluation_metric = binding.get("evaluation_metric", metric["id"])
    horizon = binding.get("horizon", metric["window"])
    rollback_condition = binding.get(
        "rollback_condition",
        {
            "metric": metric["id"],
            "worse_by": 5 if metric["unit"] == "bps" else 0.02,
            "unit": metric["unit"],
        },
    )
    registered_at = "2025-12-01T00:00:00+00:00"
    guardrail_ids = {
        evaluation_metric,
        *secondary_metrics,
        "fallback_rate",
        "missing_rate",
        "confidence_calibration_error",
    } - {metric["id"]}
    guardrails = []
    for metric_id in sorted(guardrail_ids):
        guardrail_metric = contract["evaluation_metrics"][metric_id]
        guardrails.append(
            {
                "metric_id": metric_id,
                "direction": guardrail_metric["direction"],
                "max_degradation": (
                    5 if guardrail_metric["unit"] == "bps" else 0.02
                ),
            }
        )
    holdout_id = _canonical_hash(
        {
            "experiment_family_id": "family:domain-test",
            "start": "2026-09-01T00:00:00+00:00",
            "end": "2026-11-30T00:00:00+00:00",
        }
    )
    preregistration = {
        "schema_version": "domain_evaluation_preregistration_v1",
        "experiment_id": "EXP-KM-domain-test",
        "experiment_family_id": "family:domain-test",
        "registered_at": registered_at,
        "calendar_id": "cn_a_share",
        "split_policy": {
            "train": {
                "start": "2024-01-01T00:00:00+00:00",
                "end": "2025-06-01T00:00:00+00:00",
            },
            "evaluation": {
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-03-31T00:00:00+00:00",
            },
            "holdout": {
                "holdout_id": holdout_id,
                "start": "2026-09-01T00:00:00+00:00",
                "end": "2026-11-30T00:00:00+00:00",
                "reuse_budget": 1,
            },
            "purge_days": int(horizon.removesuffix("d")),
            "embargo_days": int(horizon.removesuffix("d")),
        },
        "primary_metric": metric["id"],
        "secondary_guardrails": guardrails,
        "min_effect_size": 0.0,
        "min_samples_per_split": metric["min_sample_size"],
        "common_support_required": True,
        "regime_guardrail": {
            "required_regimes": ["normal", "stress"],
            "min_samples_per_regime": max(5, metric["min_sample_size"] // 4),
            "max_degradation": 0.02,
        },
        "multiple_testing": {
            "method": "bonferroni",
            "family_size": 20,
            "attempt_index": 1,
            "alpha": 0.05,
            "adjusted_alpha": 0.0025,
        },
    }
    return {
        "schema_version": "knob_mutation_metadata_v1",
        "mutation_id": "KM-domain-test",
        "transaction_id": "TX-KM-domain-test",
        "experiment_id": "EXP-KM-domain-test",
        "mutation_kind": "generic_knob" if generic else "domain_knob",
        "created_at": registered_at,
        "agent": binding["owner_agent"].split(".", 1)[1],
        "owner_agent": binding["owner_agent"],
        **(
            {"owner_stages": binding["owner_stages"]}
            if generic
            else {"owner_stage": binding["owner_stage"]}
        ),
        "changed_paths": [binding["path"]],
        **(
            {"generic_target_paths": [binding["path"]], "domain_card_ids": []}
            if generic
            else {
                "domain_card_id": binding["card_id"],
                "domain_card_ids": [binding["card_id"]],
            }
        ),
        "prediction_target": binding.get(
            "prediction_target", f"{binding['owner_agent']}.generic.20d"
        ),
        "evaluation_metric": metric["id"],
        "horizon": horizon,
        "rollback_condition": rollback_condition,
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
            "preregistration": preregistration,
            "preregistration_hash": _canonical_hash(preregistration),
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
        scores = [1, 2, 3] if value >= 0 else [3, 2, 1]
        return {"scores": scores, "outcomes": [1, 2, 3]}
    raise AssertionError(calculator_id)


def _comparison_values(metric, calculator):
    higher_is_better = metric["direction"] == "higher_is_better"
    if calculator["id"] == "pit.rate":
        improved = (0, 1) if higher_is_better else (1, 0)
        degraded = (1, 0) if higher_is_better else (0, 1)
    elif calculator["id"] == "pit.rank_correlation":
        improved = (-1, 1) if higher_is_better else (1, -1)
        degraded = (1, -1) if higher_is_better else (-1, 1)
    elif higher_is_better:
        improved = (0.0, 0.05)
        degraded = (0.0, -0.05)
    else:
        improved = (0.1, 0.0)
        degraded = (0.0, 0.1)
    return improved, degraded


def _assert_paired_evaluation_and_rollback(contract, binding):
    metric_id = binding.get("evaluation_metric")
    if metric_id is None:
        preferred = {
            "portfolio_risk_quality_20d",
            "portfolio_construction_quality_20d",
            "macro_signal_accuracy_5d",
        }
        metric_id = next(
            (
                candidate
                for candidate in binding["evaluation_metrics"]
                if candidate in preferred
            ),
            binding["evaluation_metrics"][0],
        )
    metric = contract["evaluation_metrics"][metric_id]
    calculator = contract["evaluation_calculators"][metric["calculator_id"]]
    metadata = _metadata(contract, binding, metric, calculator)
    improved, degraded = _comparison_values(metric, calculator)

    eligible = evaluate_domain_mutation(
        metadata,
        _manifest(
            metadata,
            calculator,
            improved[0],
            improved[1],
            metric["min_sample_size"],
        ),
    )
    reverted = evaluate_domain_mutation(
        metadata,
        _manifest(
            metadata,
            calculator,
            degraded[0],
            degraded[1],
            metric["min_sample_size"],
        ),
    )

    assert eligible["status"] == "eligible_for_promotion"
    assert eligible["holdout_consumption_required"] is True
    assert reverted["status"] == "reverted"
    assert reverted["rollback_triggered"] is True
    return eligible, reverted


def _manifest(metadata, calculator, baseline_value: float, treatment_value: float, count=30):
    source_type = "execution_record" if calculator["id"] == "pit.bps_cost" else "pit_outcome"
    preregistration = metadata["evaluation_policy"]["preregistration"]
    guardrail_ids = [
        item["metric_id"] for item in preregistration["secondary_guardrails"]
    ]

    def neutral_secondary(metric_id):
        contract = load_evaluation_contract()
        guardrail_metric = contract["evaluation_metrics"][metric_id]
        guardrail_calculator = contract["evaluation_calculators"][
            guardrail_metric["calculator_id"]
        ]
        return {
            "baseline": _arm(guardrail_calculator["id"], 0),
            "treatment": _arm(guardrail_calculator["id"], 0),
        }

    manifest = {
        "schema_version": "domain_evaluation_sample_manifest_v1",
        "mutation_id": metadata["mutation_id"],
        "generator": {"id": "domain-evaluation-test-fixture", "version": "1"},
        "source_snapshot_hashes": {
            "scorecard": "sha256:" + "a" * 64,
            "runtime_audit": "sha256:" + "b" * 64,
        },
        "preregistration_hash": metadata["evaluation_policy"]["preregistration_hash"],
        "holdout_id": preregistration["split_policy"]["holdout"]["holdout_id"],
        "holdout_prior_consumption_count": 0,
        "evaluation_as_of": "2027-06-30T00:00:00+00:00",
        "sample_window": {
            "start": preregistration["split_policy"]["evaluation"]["start"],
            "end": preregistration["split_policy"]["holdout"]["end"],
        },
        "decision_evidence_refs": ["episode:EXP-KM-domain-test"],
        "samples": [
            {
                "sample_id": f"sample-{index:03d}",
                "source_type": source_type,
                "horizon": metadata["horizon"],
                "split": "evaluation" if index < count else "holdout",
                "observed_at": (
                    "2026-01-15T00:00:00+00:00"
                    if index < count
                    else "2026-09-15T00:00:00+00:00"
                ),
                "label_available_at": (
                    "2026-03-01T00:00:00+00:00"
                    if index < count
                    else "2026-11-15T00:00:00+00:00"
                ),
                "data_vintage_hash": f"sha256:{index:064x}",
                "pit_valid": True,
                "mature": True,
                "exclusion_reasons": [],
                "baseline_exclusion_reasons": [],
                "treatment_exclusion_reasons": [],
                "baseline": _arm(calculator["id"], baseline_value),
                "treatment": _arm(calculator["id"], treatment_value),
                "secondary_metrics": {
                    metric_id: neutral_secondary(metric_id)
                    for metric_id in guardrail_ids
                },
                "evidence_refs": [f"outcome:{index:03d}"],
                "regime": "normal" if index % 2 else "stress",
            }
            for index in range(count * 2)
        ],
    }
    manifest["sample_manifest_hash"] = domain_sample_manifest_hash(manifest)
    return manifest


def _rehash_manifest(manifest):
    manifest["sample_manifest_hash"] = domain_sample_manifest_hash(manifest)
    return manifest


def test_generated_contract_hashes_validate():
    contract = load_evaluation_contract()
    assert contract["contract_hash"].startswith("sha256:")
    assert len(contract["evaluation_metrics"]) >= 1


def test_registered_uncertainty_methods_use_their_declared_estimators():
    baseline = [float(index) for index in range(20)]
    treatment = [value + 0.5 for value in baseline]
    weights = [1.0] * len(baseline)

    paired = _uncertainty(
        baseline,
        treatment,
        weights,
        "mean",
        "paired_block_bootstrap",
        0.05,
    )
    repeated = _uncertainty(
        baseline,
        treatment,
        weights,
        "mean",
        "paired_block_bootstrap",
        0.05,
    )
    independent = _uncertainty(
        baseline,
        treatment,
        weights,
        "mean",
        "block_bootstrap",
        0.05,
    )
    wilson = _uncertainty(
        [0.0] * 20,
        [1.0] * 20,
        weights,
        "hit_rate",
        "wilson_interval",
        0.05,
    )
    fisher = _uncertainty(
        [-0.5] * 20,
        [0.5] * 20,
        weights,
        "rank_correlation",
        "fisher_z",
        0.05,
    )

    assert paired == repeated
    assert paired["estimator_version"] == "domain_uncertainty_v1"
    assert paired["seed_policy"] == "sha256_numpy_pcg64_index_plan_v1"
    assert paired["quantile_rule"] == "linear_type7_v1"
    assert paired["lower"] == pytest.approx(0.5)
    assert paired["upper"] == pytest.approx(0.5)
    assert independent["lower"] < 0.5 < independent["upper"]
    assert wilson["lower"] < 1.0
    assert wilson["upper"] == pytest.approx(1.0)
    assert fisher["lower"] < 1.0 < fisher["upper"]


def test_unregistered_uncertainty_method_fails_closed():
    with pytest.raises(DomainEvaluationError, match="unsupported uncertainty method"):
        _uncertainty([0.0] * 5, [1.0] * 5, [1.0] * 5, "mean", "gaussian", 0.05)


def test_preregistration_sample_and_result_schemas_validate(tmp_path: Path):
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"])
    result = evaluate_domain_mutation(metadata, manifest)
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "artifacts"
    schema_dir.mkdir()
    artifact_dir.mkdir()
    fixtures = {
        "domain_evaluation_preregistration_v1": metadata["evaluation_policy"][
            "preregistration"
        ],
        "domain_evaluation_sample_manifest_v1": manifest,
        "domain_evaluation_result_v1": result,
    }
    repo_root = Path(__file__).resolve().parents[1]
    for name, payload in fixtures.items():
        shutil.copyfile(
            repo_root / "schemas" / f"{name}.schema.json",
            schema_dir / f"{name}.schema.json",
        )
        (artifact_dir / f"{name}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        record = validate_json_schema_artifact(
            root=tmp_path,
            schema_path=f"schemas/{name}.schema.json",
            artifact_path=f"artifacts/{name}.json",
            artifact_kind="json",
        )
        assert record.accepted, record.failures


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
    assert result["sample_count"] == metric["min_sample_size"] * 2
    assert result["sample_count_by_split"] == {
        "evaluation": metric["min_sample_size"],
        "holdout": metric["min_sample_size"],
    }
    assert result["effect_size"] == pytest.approx(0.02)
    assert result["rollback_triggered"] is False
    assert result["holdout_consumption_required"] is True
    assert result["pit_audit_hash"].startswith("sha256:")


def test_lower_is_better_metric_uses_card_rollback_direction():
    contract, binding, metric, calculator = _binding_and_metric(direction="lower_is_better")
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 1.0, metric["min_sample_size"])

    result = evaluate_domain_mutation(metadata, manifest)

    assert result["status"] == "reverted"
    assert result["new_value"] > result["baseline_value"]
    assert result["improvement"] < 0


def test_generic_confidence_and_weight_targets_use_paired_evaluator():
    contract = load_evaluation_contract()
    generic = [
        binding
        for binding in contract["generic_bindings"]
        if binding["owner_agent"] == "decision.cro"
    ]
    confidence = next(binding for binding in generic if binding["weight_group"] is None)
    weight = next(
        binding for binding in generic if binding["weight_group"] == "evidence_weights"
    )

    _assert_paired_evaluation_and_rollback(contract, confidence)
    _assert_paired_evaluation_and_rollback(contract, weight)


def test_representative_domain_categories_complete_paired_evaluation_and_rollback():
    contract = load_evaluation_contract()
    catalog = json.loads(
        Path("registry/prompt_checks/domain_knob_catalog_v1.json").read_text(
            encoding="utf-8"
        )
    )
    cards = [card for agent in catalog["agents"] for card in agent["cards"]]
    active = [card for card in cards if card["activation_state"] == "active"]
    representatives = {
        "tool_dependent": next(
            card for card in active if card["evidence_dependencies"]
        ),
        "runtime_state": next(
            card
            for card in active
            if card["runtime_input_sources"] and not card["evidence_dependencies"]
        ),
        "position": next(card for card in active if card["id"] == "stop_loss_pct"),
        "mirofish": next(
            card for card in active if card["id"].startswith("mirofish_")
        ),
    }
    bindings = {binding["path"]: binding for binding in contract["card_bindings"]}

    for category, card in representatives.items():
        eligible, reverted = _assert_paired_evaluation_and_rollback(
            contract, bindings[card["path"]]
        )
        assert eligible["decision_evidence_refs"]
        assert reverted["decision_reason_codes"], category


def test_insufficient_mature_common_support_needs_fill():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"] - 1)

    result = evaluate_domain_mutation(metadata, manifest)

    assert result["status"] == "needs_fill"
    assert result["required_sample_count"] == metric["min_sample_size"]
    assert result["missing_samples_by_split"] == {"evaluation": 1, "holdout": 1}


def test_preregistration_hash_and_single_use_holdout_fail_closed():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"])

    metadata["evaluation_policy"]["preregistration"]["multiple_testing"][
        "attempt_index"
    ] = 2
    with pytest.raises(DomainEvaluationError, match="preregistration hash mismatch"):
        evaluate_domain_mutation(metadata, manifest)

    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"])
    manifest["holdout_prior_consumption_count"] = 1
    _rehash_manifest(manifest)
    with pytest.raises(DomainEvaluationError, match="already consumed"):
        evaluate_domain_mutation(metadata, manifest)


def test_secondary_operational_guardrail_can_block_promotion():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"])
    for sample in manifest["samples"]:
        sample["secondary_metrics"]["fallback_rate"] = {
            "baseline": {"event": 0},
            "treatment": {"event": 1},
        }
    _rehash_manifest(manifest)

    result = evaluate_domain_mutation(metadata, manifest)

    assert result["status"] == "reverted"
    assert "SECONDARY_GUARDRAIL_FAILED" in result["decision_reason_codes"]
    assert result["secondary_guardrails"]["fallback_rate"]["passes"] is False


def test_worst_regime_degradation_blocks_positive_overall_effect():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"])
    for sample in manifest["samples"]:
        sample["treatment"] = _arm(
            calculator["id"], 0.1 if sample["regime"] == "normal" else -0.03
        )
    _rehash_manifest(manifest)

    result = evaluate_domain_mutation(metadata, manifest)

    assert result["improvement"] > 0
    assert result["status"] == "reverted"
    assert "REGIME_GUARDRAIL_FAILED" in result["decision_reason_codes"]
    assert result["regime_slices"]["stress"]["passes"] is False


def test_arm_exclusion_delta_is_reported_on_common_support():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"] + 1)
    manifest["samples"][0]["treatment_exclusion_reasons"] = [
        "missing_required_runtime_source"
    ]
    _rehash_manifest(manifest)

    result = evaluate_domain_mutation(metadata, manifest)

    assert result["status"] == "reverted"
    assert result["arm_exclusion_delta"]["missing_required_runtime_source"] == 1
    assert result["excluded_count_by_reason"]["arm_excluded_from_common_support"] == 1
    assert result["common_support_audit"]["missingness_guardrail_passed"] is False
    assert "ASYMMETRIC_MISSINGNESS_GUARDRAIL_FAILED" in result["decision_reason_codes"]


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
    _rehash_manifest(manifest)
    result_with_rationale = evaluate_domain_mutation(metadata, manifest)
    for field in (
        "status",
        "baseline_value",
        "new_value",
        "effect_size",
        "improvement",
        "uncertainty",
        "split_results",
        "secondary_guardrails",
    ):
        assert result_with_rationale[field] == result_without_rationale[field]


def test_sample_manifest_hash_binds_values_vintages_and_normalizes_order():
    contract, binding, metric, calculator = _binding_and_metric()
    metadata = _metadata(contract, binding, metric, calculator)
    manifest = _manifest(metadata, calculator, 0.0, 0.02, metric["min_sample_size"])
    original_hash = manifest["sample_manifest_hash"]

    reversed_manifest = {**manifest, "samples": list(reversed(manifest["samples"]))}
    assert domain_sample_manifest_hash(reversed_manifest) == original_hash

    manifest["samples"][0]["data_vintage_hash"] = "sha256:" + "f" * 64
    assert domain_sample_manifest_hash(manifest) != original_hash
    manifest["samples"][0]["treatment"] = _arm(calculator["id"], -0.5)
    assert domain_sample_manifest_hash(manifest) != original_hash

    with pytest.raises(DomainEvaluationError, match="sample manifest hash mismatch"):
        evaluate_domain_mutation(metadata, manifest)


def test_rank_correlation_calculator_is_deterministic():
    sample = {
        "baseline": {"scores": [10, 20, 30, 40], "outcomes": [1, 2, 3, 4]},
        "treatment": {"scores": [40, 30, 20, 10], "outcomes": [1, 2, 3, 4]},
    }
    assert calculate_rank_correlation(sample, "baseline") == pytest.approx(1.0)
    assert calculate_rank_correlation(sample, "treatment") == pytest.approx(-1.0)

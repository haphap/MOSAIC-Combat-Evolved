"""Card-bound, point-in-time evaluation for domain knob mutations."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain_metrics import DomainMetricInputError


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVALUATION_CONTRACT_PATH = (
    _REPO_ROOT / "registry/prompt_checks/domain_knob_evaluation_contract_v1.json"
)
DEFAULT_EVALUATION_SCHEMA_PATH = (
    _REPO_ROOT / "schemas/domain_knob_evaluation_contract_v1.schema.json"
)
_SHA256_PREFIX = "sha256:"
_ALLOWED_SOURCE_TYPES = {
    "pit_outcome",
    "execution_record",
    "runtime_audit",
    "scorecard",
}
_CALCULATOR_INPUT_FIELDS = {
    "pit.signed_return": ("signed_return",),
    "pit.nonnegative_loss": ("loss_magnitude",),
    "pit.rate": ("event",),
    "pit.bps_cost": ("cost_bps",),
    "pit.calibration_error": ("probability", "outcome"),
    "pit.rank_correlation": ("scores", "outcomes"),
}


class DomainEvaluationError(ValueError):
    """The mutation, contract, calculator, or PIT sample manifest is invalid."""


def _json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{_SHA256_PREFIX}{hashlib.sha256(payload).hexdigest()}"


def _file_hash(path: Path) -> str:
    return f"{_SHA256_PREFIX}{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DomainEvaluationError(f"{field} must be an object")
    return value


def _strings(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DomainEvaluationError(f"{field} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise DomainEvaluationError(f"{field} entries must be non-empty strings")
        result.append(item)
    if not allow_empty and not result:
        raise DomainEvaluationError(f"{field} must not be empty")
    return result


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainEvaluationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise DomainEvaluationError(f"{field} must be a finite number")
    return result


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DomainEvaluationError(f"{field} must be an ISO-8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DomainEvaluationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _require_hash(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(_SHA256_PREFIX)
        or len(value) != len(_SHA256_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise DomainEvaluationError(f"{field} must be a sha256 digest")
    return value


def load_evaluation_contract(
    path: Path | str = DEFAULT_EVALUATION_CONTRACT_PATH,
    *,
    schema_path: Path | str = DEFAULT_EVALUATION_SCHEMA_PATH,
) -> dict[str, Any]:
    """Load and cryptographically validate the generated TS evaluation contract."""
    contract_path = Path(path)
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DomainEvaluationError(f"cannot load evaluation contract: {exc}") from exc
    if not isinstance(contract, dict):
        raise DomainEvaluationError("evaluation contract must be an object")
    if contract.get("schema_version") != "domain_knob_evaluation_contract_v1":
        raise DomainEvaluationError("unsupported evaluation contract schema_version")
    if contract.get("contract_version") != "domain_knob_evaluation_contract_v1":
        raise DomainEvaluationError("unsupported evaluation contract version")

    contract_without_hash = dict(contract)
    declared_contract_hash = contract_without_hash.pop("contract_hash", None)
    if declared_contract_hash != _json_hash(contract_without_hash):
        raise DomainEvaluationError("evaluation contract hash mismatch")

    expected_schema_hash = _file_hash(Path(schema_path))
    if contract.get("schema_hash") != expected_schema_hash:
        raise DomainEvaluationError("evaluation contract schema hash mismatch")
    metrics = _mapping(contract.get("evaluation_metrics"), "evaluation_metrics")
    calculators = _mapping(
        contract.get("evaluation_calculators"), "evaluation_calculators"
    )
    if contract.get("metric_registry_hash") != _json_hash(metrics):
        raise DomainEvaluationError("evaluation metric registry hash mismatch")
    if contract.get("calculator_registry_hash") != _json_hash(calculators):
        raise DomainEvaluationError("evaluation calculator registry hash mismatch")
    if not isinstance(contract.get("card_bindings"), list):
        raise DomainEvaluationError("evaluation contract card_bindings must be an array")
    return contract


def _binding_by_path(contract: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in contract["card_bindings"]:
        binding = _mapping(raw, "card_binding")
        path = binding.get("path")
        if not isinstance(path, str) or not path:
            raise DomainEvaluationError("card binding path must be a non-empty string")
        if path in result:
            raise DomainEvaluationError(f"duplicate card binding path: {path}")
        result[path] = binding
    return result


def _validate_mutation_binding(
    metadata: Mapping[str, Any], contract: Mapping[str, Any]
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    if metadata.get("catalog_version") != contract.get("catalog_version"):
        raise DomainEvaluationError("mutation catalog_version does not match contract")
    required_hashes = {
        "catalog_hash": contract.get("catalog_hash"),
        "schema_hash": contract.get("schema_hash"),
        "evaluation_contract_hash": contract.get("contract_hash"),
        "metric_registry_hash": contract.get("metric_registry_hash"),
        "calculator_registry_hash": contract.get("calculator_registry_hash"),
    }
    for field, expected in required_hashes.items():
        if metadata.get(field) != expected:
            raise DomainEvaluationError(f"mutation {field} does not match evaluation contract")

    changed_paths = _strings(metadata.get("changed_paths"), "changed_paths")
    if len(changed_paths) != len(set(changed_paths)):
        raise DomainEvaluationError("changed_paths must not contain duplicates")
    bindings = _binding_by_path(contract)
    selected: list[Mapping[str, Any]] = []
    for path in changed_paths:
        binding = bindings.get(path)
        if binding is None:
            raise DomainEvaluationError(f"mutation path has no card binding: {path}")
        if binding.get("activation_state") != "active":
            raise DomainEvaluationError(f"mutation path is not active: {path}")
        selected.append(binding)

    first = selected[0]
    policy_fields = (
        "owner_agent",
        "owner_stage",
        "prediction_target",
        "horizon",
        "rollback_condition",
    )
    for binding in selected[1:]:
        for field in policy_fields:
            if binding.get(field) != first.get(field):
                raise DomainEvaluationError(
                    f"mutation spans incompatible card policies: {field}"
                )

    owner_agent = first.get("owner_agent")
    metadata_agent = metadata.get("owner_agent", metadata.get("agent"))
    if metadata_agent not in (owner_agent, str(owner_agent).split(".", 1)[-1]):
        raise DomainEvaluationError("mutation agent does not match card owner")
    if metadata.get("prediction_target") != first.get("prediction_target"):
        raise DomainEvaluationError("mutation prediction_target does not match card")
    if metadata.get("horizon") != first.get("horizon"):
        raise DomainEvaluationError("mutation horizon does not match card")
    if metadata.get("rollback_condition") != first.get("rollback_condition"):
        raise DomainEvaluationError("mutation rollback_condition does not match card")
    expected_card_ids = sorted(str(binding.get("card_id")) for binding in selected)
    if sorted(_strings(metadata.get("domain_card_ids"), "domain_card_ids")) != expected_card_ids:
        raise DomainEvaluationError("mutation domain_card_ids do not match changed paths")
    if metadata.get("domain_card_id") != first.get("card_id"):
        raise DomainEvaluationError("mutation domain_card_id does not match primary card")

    metric_id = metadata.get("evaluation_metric")
    allowed_metrics = {
        first.get("evaluation_metric"),
        *first.get("secondary_metrics", []),
    }
    if metric_id not in allowed_metrics:
        raise DomainEvaluationError("mutation evaluation_metric is not bound to card")
    metrics = _mapping(contract.get("evaluation_metrics"), "evaluation_metrics")
    metric = _mapping(metrics.get(metric_id), f"evaluation_metrics.{metric_id}")
    calculators = _mapping(
        contract.get("evaluation_calculators"), "evaluation_calculators"
    )
    calculator_id = metric.get("calculator_id")
    calculator = _mapping(
        calculators.get(calculator_id), f"evaluation_calculators.{calculator_id}"
    )
    if metadata.get("calculator_id") != calculator_id:
        raise DomainEvaluationError("mutation calculator_id does not match metric")
    if metadata.get("calculator_version") != calculator.get("version"):
        raise DomainEvaluationError("mutation calculator_version does not match contract")
    if metric.get("calculator_version") != calculator.get("version"):
        raise DomainEvaluationError("metric calculator version does not match registry")
    if metric.get("value_convention") not in calculator.get(
        "supported_value_conventions", []
    ):
        raise DomainEvaluationError("calculator does not support metric value convention")
    evaluation_policy = _mapping(metadata.get("evaluation_policy"), "evaluation_policy")
    policy_matches = {
        "baseline": metric.get("baseline"),
        "min_sample_size": metric.get("min_sample_size"),
        "uncertainty_method": metric.get("uncertainty_method"),
        "overlapping_sample_policy": metric.get("overlapping_sample_policy"),
    }
    for field, expected in policy_matches.items():
        if evaluation_policy.get(field) != expected:
            raise DomainEvaluationError(
                f"mutation evaluation_policy.{field} does not match metric"
            )
    baseline_id = evaluation_policy.get("baseline_id")
    if not isinstance(baseline_id, str) or not baseline_id:
        raise DomainEvaluationError("mutation evaluation_policy.baseline_id is required")
    return first, metric, calculator


def _load_calculator(calculator: Mapping[str, Any]) -> Callable[[Mapping[str, Any], str], float]:
    if calculator.get("implementation_language") != "python":
        raise DomainEvaluationError("domain evaluator requires a Python calculator")
    if calculator.get("deterministic") is not True or calculator.get("pit_enforced") is not True:
        raise DomainEvaluationError("calculator must be deterministic and PIT-enforced")
    implementation_ref = calculator.get("implementation_ref")
    if not isinstance(implementation_ref, str) or ":" not in implementation_ref:
        raise DomainEvaluationError("calculator implementation_ref is invalid")
    module_name, function_name = implementation_ref.split(":", 1)
    if module_name != "mosaic.autoresearch.domain_metrics":
        raise DomainEvaluationError("calculator implementation module is not registered")
    try:
        function = getattr(importlib.import_module(module_name), function_name)
    except (ImportError, AttributeError) as exc:
        raise DomainEvaluationError("calculator implementation cannot be loaded") from exc
    if not callable(function):
        raise DomainEvaluationError("calculator implementation is not callable")
    return function


def _sample_weight(sample: Mapping[str, Any], overlap_policy: str) -> float:
    weight = _finite_number(sample.get("weight", 1.0), "sample.weight")
    if weight <= 0:
        raise DomainEvaluationError("sample.weight must be positive")
    overlap_count = sample.get("overlap_count", 1)
    if isinstance(overlap_count, bool) or not isinstance(overlap_count, int) or overlap_count < 1:
        raise DomainEvaluationError("sample.overlap_count must be a positive integer")
    if overlap_policy == "inverse_overlap_weight":
        return weight / overlap_count
    if overlap_policy == "purged_nonoverlap" and overlap_count != 1:
        raise DomainEvaluationError("purged_nonoverlap sample has overlapping labels")
    return weight


def _aggregate(values: Sequence[float], weights: Sequence[float], aggregation: str) -> float:
    if not values or len(values) != len(weights):
        raise DomainEvaluationError("metric aggregation requires weighted values")
    if aggregation in ("mean", "hit_rate", "calibration_error", "rank_correlation"):
        return sum(value * weight for value, weight in zip(values, weights)) / sum(weights)
    ordered = sorted(zip(values, weights), key=lambda item: item[0])
    if aggregation in ("median", "p50", "p95"):
        quantile = 0.5 if aggregation in ("median", "p50") else 0.95
        target = sum(weights) * quantile
        cumulative = 0.0
        for value, weight in ordered:
            cumulative += weight
            if cumulative >= target:
                return value
        return ordered[-1][0]
    if aggregation == "max":
        return max(values)
    if aggregation == "min":
        return min(values)
    if aggregation == "sum":
        return sum(value * weight for value, weight in zip(values, weights))
    raise DomainEvaluationError(f"unsupported metric aggregation: {aggregation}")


def _validate_range(value: float, metric: Mapping[str, Any], field: str) -> None:
    valid_range = _mapping(metric.get("valid_range"), "metric.valid_range")
    minimum = valid_range.get("minimum")
    maximum = valid_range.get("maximum")
    if minimum is not None and value < _finite_number(minimum, "metric.valid_range.minimum"):
        raise DomainEvaluationError(f"{field} is below metric valid range")
    if maximum is not None and value > _finite_number(maximum, "metric.valid_range.maximum"):
        raise DomainEvaluationError(f"{field} is above metric valid range")


def _uncertainty(
    effects: Sequence[float], weights: Sequence[float], method: str
) -> dict[str, Any]:
    weight_sum = sum(weights)
    mean = sum(value * weight for value, weight in zip(effects, weights)) / weight_sum
    effective_n = weight_sum**2 / sum(weight**2 for weight in weights)
    if effective_n <= 1:
        standard_error = 0.0
    else:
        variance = sum(
            weight * (value - mean) ** 2 for value, weight in zip(effects, weights)
        ) / weight_sum
        standard_error = math.sqrt(variance / effective_n)
    return {
        "method": method,
        "confidence_level": 0.95,
        "standard_error": standard_error,
        "lower": mean - 1.96 * standard_error,
        "upper": mean + 1.96 * standard_error,
        "effective_sample_size": effective_n,
    }


def _pit_audit_hash(
    manifest: Mapping[str, Any], eligible_ids: Sequence[str], exclusions: Mapping[str, int]
) -> str:
    return _json_hash(
        {
            "schema_version": manifest.get("schema_version"),
            "mutation_id": manifest.get("mutation_id"),
            "evaluation_as_of": manifest.get("evaluation_as_of"),
            "sample_window": manifest.get("sample_window"),
            "eligible_sample_ids": sorted(eligible_ids),
            "excluded_count_by_reason": dict(sorted(exclusions.items())),
        }
    )


def evaluate_domain_mutation(
    metadata: Mapping[str, Any],
    sample_manifest: Mapping[str, Any],
    *,
    contract_path: Path | str = DEFAULT_EVALUATION_CONTRACT_PATH,
    schema_path: Path | str = DEFAULT_EVALUATION_SCHEMA_PATH,
) -> dict[str, Any]:
    """Evaluate one domain mutation against a paired PIT sample manifest.

    The generated contract selects the card, metric, direction, calculator, and
    rollback policy. Prompt rationale and model confidence are never calculator
    inputs.
    """
    contract = load_evaluation_contract(contract_path, schema_path=schema_path)
    binding, metric, calculator = _validate_mutation_binding(metadata, contract)
    calculator_fn = _load_calculator(calculator)

    mutation_id = metadata.get("mutation_id")
    if not isinstance(mutation_id, str) or not mutation_id:
        raise DomainEvaluationError("mutation_id must be a non-empty string")
    if sample_manifest.get("schema_version") != "domain_evaluation_sample_manifest_v1":
        raise DomainEvaluationError("unsupported domain sample manifest schema_version")
    if sample_manifest.get("mutation_id") != mutation_id:
        raise DomainEvaluationError("sample manifest mutation_id mismatch")
    evaluation_as_of = _parse_timestamp(
        sample_manifest.get("evaluation_as_of"), "sample_manifest.evaluation_as_of"
    )
    sample_window = _mapping(sample_manifest.get("sample_window"), "sample_window")
    window_start = _parse_timestamp(sample_window.get("start"), "sample_window.start")
    window_end = _parse_timestamp(sample_window.get("end"), "sample_window.end")
    if window_start > window_end or window_end > evaluation_as_of:
        raise DomainEvaluationError("sample_window must be ordered and observable as of evaluation")
    raw_samples = sample_manifest.get("samples")
    if not isinstance(raw_samples, list):
        raise DomainEvaluationError("sample_manifest.samples must be an array")

    exclusions: Counter[str] = Counter()
    eligible_ids: list[str] = []
    baseline_values: list[float] = []
    treatment_values: list[float] = []
    weights: list[float] = []
    evidence_refs: set[str] = set(
        _strings(
            sample_manifest.get("decision_evidence_refs", []),
            "decision_evidence_refs",
            allow_empty=True,
        )
    )
    regimes: defaultdict[str, list[int]] = defaultdict(list)
    seen_ids: set[str] = set()
    registered_exclusions = set(metric.get("exclusion_rules", []))

    for index, raw_sample in enumerate(raw_samples):
        sample = _mapping(raw_sample, f"samples[{index}]")
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            raise DomainEvaluationError(f"samples[{index}].sample_id must be non-empty")
        if sample_id in seen_ids:
            raise DomainEvaluationError(f"duplicate sample_id: {sample_id}")
        seen_ids.add(sample_id)
        if sample.get("source_type") not in _ALLOWED_SOURCE_TYPES:
            raise DomainEvaluationError(f"sample {sample_id} has unregistered source_type")
        if sample.get("horizon") != metadata.get("horizon"):
            raise DomainEvaluationError(f"sample {sample_id} horizon mismatch")
        _require_hash(sample.get("data_vintage_hash"), f"sample {sample_id} data_vintage_hash")
        if sample.get("pit_valid") is not True:
            raise DomainEvaluationError(f"sample {sample_id} failed PIT audit")
        observed_at = _parse_timestamp(sample.get("observed_at"), f"sample {sample_id} observed_at")
        label_available_at = _parse_timestamp(
            sample.get("label_available_at"), f"sample {sample_id} label_available_at"
        )
        if label_available_at < observed_at:
            raise DomainEvaluationError(f"sample {sample_id} label precedes observation")
        if observed_at < window_start or observed_at > window_end:
            raise DomainEvaluationError(f"sample {sample_id} observation is outside sample_window")
        if sample.get("mature") is not True or label_available_at > evaluation_as_of:
            exclusions["pending_label"] += 1
            continue

        exclusion_reasons = _strings(
            sample.get("exclusion_reasons", []),
            f"sample {sample_id} exclusion_reasons",
            allow_empty=True,
        )
        unknown_exclusions = set(exclusion_reasons) - registered_exclusions
        if unknown_exclusions:
            raise DomainEvaluationError(
                f"sample {sample_id} has unregistered exclusions: {sorted(unknown_exclusions)}"
            )
        if "lookahead_risk" in exclusion_reasons:
            raise DomainEvaluationError(f"sample {sample_id} has lookahead risk")
        if exclusion_reasons:
            exclusions.update(exclusion_reasons)
            continue
        if not isinstance(sample.get("baseline"), Mapping) or not isinstance(
            sample.get("treatment"), Mapping
        ):
            exclusions["missing_common_support"] += 1
            continue

        required_input_fields = _CALCULATOR_INPUT_FIELDS.get(str(calculator.get("id")))
        if required_input_fields is None:
            raise DomainEvaluationError("calculator input field contract is not registered")
        baseline_arm = _mapping(sample["baseline"], f"sample {sample_id} baseline")
        treatment_arm = _mapping(sample["treatment"], f"sample {sample_id} treatment")
        if any(
            arm.get(field) is None
            for arm in (baseline_arm, treatment_arm)
            for field in required_input_fields
        ):
            if metric.get("null_policy") == "exclude_sample":
                exclusions["null_metric_input"] += 1
                continue
            raise DomainEvaluationError(f"sample {sample_id} has null metric input")

        try:
            baseline_value = float(calculator_fn(sample, "baseline"))
            treatment_value = float(calculator_fn(sample, "treatment"))
        except DomainMetricInputError as exc:
            raise DomainEvaluationError(f"sample {sample_id}: {exc}") from exc
        if not math.isfinite(baseline_value) or not math.isfinite(treatment_value):
            raise DomainEvaluationError(f"sample {sample_id} produced a non-finite metric")
        _validate_range(baseline_value, metric, f"sample {sample_id} baseline")
        _validate_range(treatment_value, metric, f"sample {sample_id} treatment")
        weight = _sample_weight(sample, str(metric.get("overlapping_sample_policy")))
        eligible_ids.append(sample_id)
        baseline_values.append(baseline_value)
        treatment_values.append(treatment_value)
        weights.append(weight)
        regime = sample.get("regime", "all")
        if not isinstance(regime, str) or not regime:
            raise DomainEvaluationError(f"sample {sample_id} regime must be a string")
        regimes[regime].append(len(eligible_ids) - 1)
        evidence_refs.update(
            _strings(
                sample.get("evidence_refs", []),
                f"sample {sample_id} evidence_refs",
                allow_empty=True,
            )
        )

    pit_audit_hash = _pit_audit_hash(sample_manifest, eligible_ids, exclusions)
    base_result: dict[str, Any] = {
        "schema_version": "domain_evaluation_result_v1",
        "mutation_id": mutation_id,
        "metric_id": metric.get("id"),
        "calculator_id": calculator.get("id"),
        "calculator_version": calculator.get("version"),
        "sample_window": dict(sample_window),
        "baseline_id": (
            _mapping(metadata.get("evaluation_policy", {}), "evaluation_policy").get(
                "baseline_id"
            )
            or metadata.get("base_knobs_sha256")
        ),
        "sample_count": len(eligible_ids),
        "excluded_count_by_reason": dict(sorted(exclusions.items())),
        "pit_audit_hash": pit_audit_hash,
        "decision_evidence_refs": sorted(
            {
                *evidence_refs,
                f"evaluation_contract:{contract['contract_hash']}",
                f"pit_audit:{pit_audit_hash}",
            }
        ),
    }
    minimum_samples = int(metric.get("min_sample_size", 0))
    if len(eligible_ids) < minimum_samples:
        return {
            **base_result,
            "status": "needs_fill",
            "required_sample_count": minimum_samples,
            "baseline_value": None,
            "new_value": None,
            "effect_size": None,
            "uncertainty": None,
            "regime_slices": {},
            "rollback_triggered": False,
        }

    aggregation = str(metric.get("aggregation"))
    baseline_value = _aggregate(baseline_values, weights, aggregation)
    treatment_value = _aggregate(treatment_values, weights, aggregation)
    effect_size = treatment_value - baseline_value
    effects = [new - old for old, new in zip(baseline_values, treatment_values)]
    uncertainty = _uncertainty(effects, weights, str(metric.get("uncertainty_method")))
    regime_slices: dict[str, Any] = {}
    for regime, indices in sorted(regimes.items()):
        slice_weights = [weights[index] for index in indices]
        slice_baseline = _aggregate(
            [baseline_values[index] for index in indices], slice_weights, aggregation
        )
        slice_treatment = _aggregate(
            [treatment_values[index] for index in indices], slice_weights, aggregation
        )
        regime_slices[regime] = {
            "sample_count": len(indices),
            "baseline_value": slice_baseline,
            "new_value": slice_treatment,
            "effect_size": slice_treatment - slice_baseline,
        }

    rollback = _mapping(binding.get("rollback_condition"), "rollback_condition")
    worse_by = _finite_number(rollback.get("worse_by"), "rollback_condition.worse_by")
    direction = metric.get("direction")
    if direction == "higher_is_better":
        rollback_triggered = treatment_value < baseline_value - worse_by
        improvement = effect_size
        uncertainty_passes = uncertainty["lower"] > 0
    elif direction == "lower_is_better":
        rollback_triggered = treatment_value > baseline_value + worse_by
        improvement = -effect_size
        uncertainty_passes = uncertainty["upper"] < 0
    else:
        raise DomainEvaluationError("metric direction is invalid")
    evaluation_policy = _mapping(metadata.get("evaluation_policy", {}), "evaluation_policy")
    minimum_effect = _finite_number(
        evaluation_policy.get("min_effect_size", 0.0), "evaluation_policy.min_effect_size"
    )
    require_uncertainty = evaluation_policy.get("require_uncertainty_bound", True)
    if not isinstance(require_uncertainty, bool):
        raise DomainEvaluationError("evaluation_policy.require_uncertainty_bound must be boolean")
    eligible = (
        not rollback_triggered
        and improvement > minimum_effect
        and (uncertainty_passes or not require_uncertainty)
    )
    return {
        **base_result,
        "status": "eligible_for_promotion" if eligible else "reverted",
        "required_sample_count": minimum_samples,
        "baseline_value": baseline_value,
        "new_value": treatment_value,
        "effect_size": effect_size,
        "improvement": improvement,
        "uncertainty": uncertainty,
        "regime_slices": regime_slices,
        "rollback_triggered": rollback_triggered,
    }

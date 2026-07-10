"""Card-bound, point-in-time evaluation for domain knob mutations."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import NormalDist
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


def _canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
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
) -> tuple[
    Mapping[str, Any],
    Mapping[str, Any],
    Mapping[str, Any],
    Mapping[str, Any],
]:
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
    preregistration = _validate_preregistration(
        metadata,
        evaluation_policy,
        first,
        metric,
        metrics,
        calculators,
    )
    return first, metric, calculator, preregistration


def _validate_preregistration(
    metadata: Mapping[str, Any],
    evaluation_policy: Mapping[str, Any],
    binding: Mapping[str, Any],
    metric: Mapping[str, Any],
    metrics: Mapping[str, Any],
    calculators: Mapping[str, Any],
) -> Mapping[str, Any]:
    preregistration = _mapping(
        evaluation_policy.get("preregistration"),
        "evaluation_policy.preregistration",
    )
    if preregistration.get("schema_version") != "domain_evaluation_preregistration_v1":
        raise DomainEvaluationError("unsupported evaluation preregistration schema_version")
    declared_hash = _require_hash(
        evaluation_policy.get("preregistration_hash"),
        "evaluation_policy.preregistration_hash",
    )
    if declared_hash != _canonical_json_hash(preregistration):
        raise DomainEvaluationError("evaluation preregistration hash mismatch")
    if preregistration.get("experiment_id") != metadata.get("experiment_id"):
        raise DomainEvaluationError("evaluation preregistration experiment_id mismatch")
    if preregistration.get("primary_metric") != metric.get("id"):
        raise DomainEvaluationError("evaluation preregistration primary_metric mismatch")
    if preregistration.get("calendar_id") != "cn_a_share":
        raise DomainEvaluationError("evaluation preregistration calendar is unsupported")
    registered_at = _parse_timestamp(
        preregistration.get("registered_at"), "preregistration.registered_at"
    )
    created_at = _parse_timestamp(metadata.get("created_at"), "mutation.created_at")
    if registered_at != created_at:
        raise DomainEvaluationError("evaluation preregistration must be frozen at mutation creation")

    split_policy = _mapping(preregistration.get("split_policy"), "split_policy")
    train = _mapping(split_policy.get("train"), "split_policy.train")
    evaluation = _mapping(split_policy.get("evaluation"), "split_policy.evaluation")
    holdout = _mapping(split_policy.get("holdout"), "split_policy.holdout")
    train_start = _parse_timestamp(train.get("start"), "split_policy.train.start")
    train_end = _parse_timestamp(train.get("end"), "split_policy.train.end")
    evaluation_start = _parse_timestamp(
        evaluation.get("start"), "split_policy.evaluation.start"
    )
    evaluation_end = _parse_timestamp(
        evaluation.get("end"), "split_policy.evaluation.end"
    )
    holdout_start = _parse_timestamp(holdout.get("start"), "split_policy.holdout.start")
    holdout_end = _parse_timestamp(holdout.get("end"), "split_policy.holdout.end")
    if not (
        train_start <= train_end < evaluation_start <= evaluation_end < holdout_start <= holdout_end
    ):
        raise DomainEvaluationError("evaluation preregistration split ranges overlap or are unordered")
    purge_days = split_policy.get("purge_days")
    embargo_days = split_policy.get("embargo_days")
    for value, field in ((purge_days, "purge_days"), (embargo_days, "embargo_days")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise DomainEvaluationError(f"split_policy.{field} must be a positive integer")
    if evaluation_start - train_end <= timedelta(days=purge_days):
        raise DomainEvaluationError("evaluation preregistration purge gap is too short")
    if holdout_start - evaluation_end <= timedelta(days=embargo_days):
        raise DomainEvaluationError("evaluation preregistration embargo gap is too short")
    if registered_at >= evaluation_start:
        raise DomainEvaluationError("evaluation preregistration is not prior to evaluation split")
    _require_hash(holdout.get("holdout_id"), "split_policy.holdout.holdout_id")
    if holdout.get("reuse_budget") != 1:
        raise DomainEvaluationError("untouched holdout reuse_budget must be exactly one")
    if preregistration.get("common_support_required") is not True:
        raise DomainEvaluationError("paired common support must be required")
    minimum_samples = preregistration.get("min_samples_per_split")
    if (
        isinstance(minimum_samples, bool)
        or not isinstance(minimum_samples, int)
        or minimum_samples < int(metric.get("min_sample_size", 0))
    ):
        raise DomainEvaluationError("preregistered split sample minimum is below metric policy")
    preregistered_minimum_effect = _finite_number(
        preregistration.get("min_effect_size"), "preregistration.min_effect_size"
    )
    if preregistered_minimum_effect != _finite_number(
        evaluation_policy.get("min_effect_size"), "evaluation_policy.min_effect_size"
    ):
        raise DomainEvaluationError("preregistered minimum effect does not match mutation policy")
    if evaluation_policy.get("require_uncertainty_bound") is not True:
        raise DomainEvaluationError("domain evaluation requires an uncertainty bound")

    multiple_testing = _mapping(
        preregistration.get("multiple_testing"), "multiple_testing"
    )
    if multiple_testing.get("method") != "bonferroni":
        raise DomainEvaluationError("multiple-testing method is unsupported")
    family_size = multiple_testing.get("family_size")
    attempt_index = multiple_testing.get("attempt_index")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in (family_size, attempt_index)
    ) or attempt_index > family_size:
        raise DomainEvaluationError("multiple-testing family/rank/attempt is invalid")
    alpha = _finite_number(multiple_testing.get("alpha"), "multiple_testing.alpha")
    adjusted_alpha = _finite_number(
        multiple_testing.get("adjusted_alpha"), "multiple_testing.adjusted_alpha"
    )
    expected_adjusted_alpha = alpha / family_size
    if not 0 < alpha < 1 or not math.isclose(
        adjusted_alpha, expected_adjusted_alpha, rel_tol=0, abs_tol=1e-12
    ):
        raise DomainEvaluationError("multiple-testing adjusted alpha is invalid")

    required_guardrails = {
        binding.get("evaluation_metric"),
        *binding.get("secondary_metrics", []),
        "fallback_rate",
        "missing_rate",
        "confidence_calibration_error",
    } - {metric.get("id")}
    raw_guardrails = preregistration.get("secondary_guardrails")
    if not isinstance(raw_guardrails, list):
        raise DomainEvaluationError("secondary_guardrails must be an array")
    guardrail_ids: set[str] = set()
    for index, raw_guardrail in enumerate(raw_guardrails):
        guardrail = _mapping(raw_guardrail, f"secondary_guardrails[{index}]")
        metric_id = guardrail.get("metric_id")
        if not isinstance(metric_id, str) or metric_id in guardrail_ids:
            raise DomainEvaluationError("secondary guardrail metric ids must be unique")
        guardrail_ids.add(metric_id)
        guardrail_metric = _mapping(metrics.get(metric_id), f"evaluation_metrics.{metric_id}")
        if guardrail.get("direction") != guardrail_metric.get("direction"):
            raise DomainEvaluationError("secondary guardrail direction mismatch")
        max_degradation = _finite_number(
            guardrail.get("max_degradation"),
            f"secondary_guardrails[{index}].max_degradation",
        )
        if max_degradation < 0:
            raise DomainEvaluationError("secondary guardrail degradation must be nonnegative")
        calculator_id = guardrail_metric.get("calculator_id")
        if calculator_id not in calculators:
            raise DomainEvaluationError("secondary guardrail calculator is not registered")
    if guardrail_ids != required_guardrails:
        raise DomainEvaluationError("secondary guardrail set does not match card policy")

    regime_guardrail = _mapping(
        preregistration.get("regime_guardrail"), "regime_guardrail"
    )
    required_regimes = _strings(
        regime_guardrail.get("required_regimes"), "regime_guardrail.required_regimes"
    )
    if len(required_regimes) != len(set(required_regimes)):
        raise DomainEvaluationError("required regimes must be unique")
    min_regime_samples = regime_guardrail.get("min_samples_per_regime")
    if (
        isinstance(min_regime_samples, bool)
        or not isinstance(min_regime_samples, int)
        or min_regime_samples < 1
    ):
        raise DomainEvaluationError("regime sample minimum must be positive")
    if _finite_number(
        regime_guardrail.get("max_degradation"), "regime_guardrail.max_degradation"
    ) < 0:
        raise DomainEvaluationError("regime max degradation must be nonnegative")
    return preregistration


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
    effects: Sequence[float], weights: Sequence[float], method: str, alpha: float
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
    critical_value = NormalDist().inv_cdf(1 - alpha / 2)
    return {
        "method": method,
        "confidence_level": 1 - alpha,
        "adjusted_alpha": alpha,
        "standard_error": standard_error,
        "lower": mean - critical_value * standard_error,
        "upper": mean + critical_value * standard_error,
        "effective_sample_size": effective_n,
    }


def _pit_audit_hash(
    manifest: Mapping[str, Any],
    eligible_ids: Sequence[str],
    eligible_ids_by_split: Mapping[str, Sequence[str]],
    exclusions: Mapping[str, int],
) -> str:
    return _json_hash(
        {
            "schema_version": manifest.get("schema_version"),
            "mutation_id": manifest.get("mutation_id"),
            "evaluation_as_of": manifest.get("evaluation_as_of"),
            "sample_window": manifest.get("sample_window"),
            "preregistration_hash": manifest.get("preregistration_hash"),
            "holdout_id": manifest.get("holdout_id"),
            "eligible_sample_ids": sorted(eligible_ids),
            "eligible_sample_ids_by_split": {
                split: sorted(sample_ids)
                for split, sample_ids in sorted(eligible_ids_by_split.items())
            },
            "excluded_count_by_reason": dict(sorted(exclusions.items())),
        }
    )


def _finalize_result(result: dict[str, Any]) -> dict[str, Any]:
    return {**result, "result_hash": _canonical_json_hash(result)}


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
    binding, metric, calculator, preregistration = _validate_mutation_binding(
        metadata, contract
    )
    calculator_fn = _load_calculator(calculator)

    mutation_id = metadata.get("mutation_id")
    if not isinstance(mutation_id, str) or not mutation_id:
        raise DomainEvaluationError("mutation_id must be a non-empty string")
    if sample_manifest.get("schema_version") != "domain_evaluation_sample_manifest_v1":
        raise DomainEvaluationError("unsupported domain sample manifest schema_version")
    if sample_manifest.get("mutation_id") != mutation_id:
        raise DomainEvaluationError("sample manifest mutation_id mismatch")
    evaluation_policy = _mapping(metadata.get("evaluation_policy"), "evaluation_policy")
    preregistration_hash = _require_hash(
        evaluation_policy.get("preregistration_hash"),
        "evaluation_policy.preregistration_hash",
    )
    if sample_manifest.get("preregistration_hash") != preregistration_hash:
        raise DomainEvaluationError("sample manifest preregistration hash mismatch")
    split_policy = _mapping(preregistration.get("split_policy"), "split_policy")
    evaluation_split = _mapping(split_policy.get("evaluation"), "split_policy.evaluation")
    holdout_split = _mapping(split_policy.get("holdout"), "split_policy.holdout")
    holdout_id = _require_hash(
        holdout_split.get("holdout_id"), "split_policy.holdout.holdout_id"
    )
    if sample_manifest.get("holdout_id") != holdout_id:
        raise DomainEvaluationError("sample manifest holdout_id mismatch")
    if sample_manifest.get("holdout_prior_consumption_count") != 0:
        raise DomainEvaluationError("untouched holdout was already consumed")
    evaluation_as_of = _parse_timestamp(
        sample_manifest.get("evaluation_as_of"), "sample_manifest.evaluation_as_of"
    )
    sample_window = _mapping(sample_manifest.get("sample_window"), "sample_window")
    window_start = _parse_timestamp(sample_window.get("start"), "sample_window.start")
    window_end = _parse_timestamp(sample_window.get("end"), "sample_window.end")
    if window_start > window_end or window_end > evaluation_as_of:
        raise DomainEvaluationError("sample_window must be ordered and observable as of evaluation")
    expected_window_start = _parse_timestamp(
        evaluation_split.get("start"), "split_policy.evaluation.start"
    )
    expected_window_end = _parse_timestamp(
        holdout_split.get("end"), "split_policy.holdout.end"
    )
    if window_start != expected_window_start or window_end != expected_window_end:
        raise DomainEvaluationError("sample_window does not match preregistered OOS ranges")
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
    splits: defaultdict[str, list[int]] = defaultdict(list)
    arm_exclusions: dict[str, Counter[str]] = {
        "baseline": Counter(),
        "treatment": Counter(),
    }
    seen_ids: set[str] = set()
    registered_exclusions = set(metric.get("exclusion_rules", []))
    metrics = _mapping(contract.get("evaluation_metrics"), "evaluation_metrics")
    calculators = _mapping(
        contract.get("evaluation_calculators"), "evaluation_calculators"
    )
    secondary_series: dict[str, dict[str, Any]] = {}
    for raw_guardrail in preregistration.get("secondary_guardrails", []):
        guardrail = _mapping(raw_guardrail, "secondary_guardrail")
        metric_id = str(guardrail.get("metric_id"))
        guardrail_metric = _mapping(metrics.get(metric_id), f"evaluation_metrics.{metric_id}")
        guardrail_calculator = _mapping(
            calculators.get(guardrail_metric.get("calculator_id")),
            f"evaluation_calculators.{guardrail_metric.get('calculator_id')}",
        )
        secondary_series[metric_id] = {
            "policy": guardrail,
            "metric": guardrail_metric,
            "calculator": guardrail_calculator,
            "calculator_fn": _load_calculator(guardrail_calculator),
            "baseline": [],
            "treatment": [],
            "weights": [],
        }

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
        split = sample.get("split")
        if split not in ("evaluation", "holdout"):
            raise DomainEvaluationError(f"sample {sample_id} split must be evaluation or holdout")
        registered_split = _mapping(split_policy.get(split), f"split_policy.{split}")
        split_start = _parse_timestamp(
            registered_split.get("start"), f"split_policy.{split}.start"
        )
        split_end = _parse_timestamp(
            registered_split.get("end"), f"split_policy.{split}.end"
        )
        if observed_at < split_start or observed_at > split_end:
            raise DomainEvaluationError(
                f"sample {sample_id} observation is outside preregistered {split} split"
            )
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
        arm_reason_sets: dict[str, set[str]] = {}
        for arm in ("baseline", "treatment"):
            reasons = set(
                _strings(
                    sample.get(f"{arm}_exclusion_reasons", []),
                    f"sample {sample_id} {arm}_exclusion_reasons",
                    allow_empty=True,
                )
            )
            unknown_arm_exclusions = reasons - registered_exclusions
            if unknown_arm_exclusions:
                raise DomainEvaluationError(
                    f"sample {sample_id} has unregistered {arm} exclusions: "
                    f"{sorted(unknown_arm_exclusions)}"
                )
            arm_reason_sets[arm] = reasons
            arm_exclusions[arm].update(reasons)
        if arm_reason_sets["baseline"] or arm_reason_sets["treatment"]:
            exclusions["arm_excluded_from_common_support"] += 1
            continue
        baseline_present = isinstance(sample.get("baseline"), Mapping)
        treatment_present = isinstance(sample.get("treatment"), Mapping)
        if not baseline_present or not treatment_present:
            if not baseline_present:
                arm_exclusions["baseline"]["missing_arm"] += 1
            if not treatment_present:
                arm_exclusions["treatment"]["missing_arm"] += 1
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
        raw_secondary = _mapping(
            sample.get("secondary_metrics"), f"sample {sample_id} secondary_metrics"
        )
        calculated_secondary: dict[str, tuple[float, float, float]] = {}
        secondary_missing = False
        for metric_id, series in secondary_series.items():
            metric_sample = raw_secondary.get(metric_id)
            if not isinstance(metric_sample, Mapping):
                exclusions[f"missing_secondary_metric:{metric_id}"] += 1
                secondary_missing = True
                break
            guardrail_metric = series["metric"]
            guardrail_calculator = series["calculator"]
            required_fields = _CALCULATOR_INPUT_FIELDS.get(
                str(guardrail_calculator.get("id"))
            )
            if required_fields is None:
                raise DomainEvaluationError("secondary calculator input contract is not registered")
            if any(
                not isinstance(metric_sample.get(arm), Mapping)
                or any(metric_sample[arm].get(field) is None for field in required_fields)
                for arm in ("baseline", "treatment")
            ):
                exclusions[f"null_secondary_metric:{metric_id}"] += 1
                secondary_missing = True
                break
            try:
                secondary_baseline = float(series["calculator_fn"](metric_sample, "baseline"))
                secondary_treatment = float(series["calculator_fn"](metric_sample, "treatment"))
            except DomainMetricInputError as exc:
                raise DomainEvaluationError(
                    f"sample {sample_id} secondary {metric_id}: {exc}"
                ) from exc
            if not math.isfinite(secondary_baseline) or not math.isfinite(
                secondary_treatment
            ):
                raise DomainEvaluationError(
                    f"sample {sample_id} secondary {metric_id} is non-finite"
                )
            _validate_range(
                secondary_baseline,
                guardrail_metric,
                f"sample {sample_id} secondary {metric_id} baseline",
            )
            _validate_range(
                secondary_treatment,
                guardrail_metric,
                f"sample {sample_id} secondary {metric_id} treatment",
            )
            secondary_weight = _sample_weight(
                sample, str(guardrail_metric.get("overlapping_sample_policy"))
            )
            calculated_secondary[metric_id] = (
                secondary_baseline,
                secondary_treatment,
                secondary_weight,
            )
        if secondary_missing:
            continue
        weight = _sample_weight(sample, str(metric.get("overlapping_sample_policy")))
        eligible_ids.append(sample_id)
        baseline_values.append(baseline_value)
        treatment_values.append(treatment_value)
        weights.append(weight)
        for metric_id, (secondary_baseline, secondary_treatment, secondary_weight) in (
            calculated_secondary.items()
        ):
            secondary_series[metric_id]["baseline"].append(secondary_baseline)
            secondary_series[metric_id]["treatment"].append(secondary_treatment)
            secondary_series[metric_id]["weights"].append(secondary_weight)
        regime = sample.get("regime", "all")
        if not isinstance(regime, str) or not regime:
            raise DomainEvaluationError(f"sample {sample_id} regime must be a string")
        regimes[regime].append(len(eligible_ids) - 1)
        splits[str(split)].append(len(eligible_ids) - 1)
        evidence_refs.update(
            _strings(
                sample.get("evidence_refs", []),
                f"sample {sample_id} evidence_refs",
                allow_empty=True,
            )
        )

    eligible_ids_by_split = {
        split: [eligible_ids[index] for index in indices]
        for split, indices in splits.items()
    }
    pit_audit_hash = _pit_audit_hash(
        sample_manifest, eligible_ids, eligible_ids_by_split, exclusions
    )
    base_result: dict[str, Any] = {
        "schema_version": "domain_evaluation_result_v1",
        "mutation_id": mutation_id,
        "metric_id": metric.get("id"),
        "calculator_id": calculator.get("id"),
        "calculator_version": calculator.get("version"),
        "sample_window": dict(sample_window),
        "preregistration_hash": preregistration_hash,
        "experiment_family_id": preregistration.get("experiment_family_id"),
        "holdout_id": holdout_id,
        "baseline_id": (
            _mapping(metadata.get("evaluation_policy", {}), "evaluation_policy").get(
                "baseline_id"
            )
            or metadata.get("base_knobs_sha256")
        ),
        "sample_count": len(eligible_ids),
        "sample_count_by_split": {
            split: len(indices) for split, indices in sorted(splits.items())
        },
        "excluded_count_by_reason": dict(sorted(exclusions.items())),
        "arm_exclusion_count_by_reason": {
            arm: dict(sorted(reasons.items()))
            for arm, reasons in sorted(arm_exclusions.items())
        },
        "arm_exclusion_delta": {
            reason: arm_exclusions["treatment"].get(reason, 0)
            - arm_exclusions["baseline"].get(reason, 0)
            for reason in sorted(
                set(arm_exclusions["baseline"]) | set(arm_exclusions["treatment"])
            )
        },
        "pit_audit_hash": pit_audit_hash,
        "multiple_testing": dict(preregistration.get("multiple_testing", {})),
        "decision_evidence_refs": sorted(
            {
                *evidence_refs,
                f"evaluation_contract:{contract['contract_hash']}",
                f"pit_audit:{pit_audit_hash}",
            }
        ),
    }
    minimum_samples = int(preregistration.get("min_samples_per_split", 0))
    missing_splits = {
        split: minimum_samples - len(splits.get(split, []))
        for split in ("evaluation", "holdout")
        if len(splits.get(split, [])) < minimum_samples
    }
    regime_policy = _mapping(
        preregistration.get("regime_guardrail"), "regime_guardrail"
    )
    minimum_regime_samples = int(regime_policy.get("min_samples_per_regime", 0))
    required_regimes = _strings(
        regime_policy.get("required_regimes"), "regime_guardrail.required_regimes"
    )
    missing_regimes = {
        regime: minimum_regime_samples - len(regimes.get(regime, []))
        for regime in required_regimes
        if len(regimes.get(regime, [])) < minimum_regime_samples
    }
    if missing_splits or missing_regimes:
        return _finalize_result({
            **base_result,
            "status": "needs_fill",
            "required_sample_count": minimum_samples,
            "missing_samples_by_split": missing_splits,
            "missing_samples_by_regime": missing_regimes,
            "baseline_value": None,
            "new_value": None,
            "effect_size": None,
            "uncertainty": None,
            "regime_slices": {},
            "split_results": {},
            "secondary_guardrails": {},
            "rollback_triggered": False,
            "holdout_consumption_required": False,
        })

    aggregation = str(metric.get("aggregation"))
    baseline_value = _aggregate(baseline_values, weights, aggregation)
    treatment_value = _aggregate(treatment_values, weights, aggregation)
    effect_size = treatment_value - baseline_value
    effects = [new - old for old, new in zip(baseline_values, treatment_values)]
    multiple_testing = _mapping(
        preregistration.get("multiple_testing"), "multiple_testing"
    )
    adjusted_alpha = _finite_number(
        multiple_testing.get("adjusted_alpha"), "multiple_testing.adjusted_alpha"
    )
    uncertainty = _uncertainty(
        effects,
        weights,
        str(metric.get("uncertainty_method")),
        adjusted_alpha,
    )
    rollback = _mapping(binding.get("rollback_condition"), "rollback_condition")
    worse_by = _finite_number(rollback.get("worse_by"), "rollback_condition.worse_by")
    direction = metric.get("direction")
    if direction not in ("higher_is_better", "lower_is_better"):
        raise DomainEvaluationError("metric direction is invalid")
    minimum_effect = _finite_number(
        preregistration.get("min_effect_size"), "preregistration.min_effect_size"
    )
    require_uncertainty = evaluation_policy.get("require_uncertainty_bound", True)
    if not isinstance(require_uncertainty, bool):
        raise DomainEvaluationError("evaluation_policy.require_uncertainty_bound must be boolean")

    def directional_result(
        split_baseline: float,
        split_treatment: float,
        split_uncertainty: Mapping[str, Any],
    ) -> dict[str, Any]:
        split_effect = split_treatment - split_baseline
        if direction == "higher_is_better":
            rollback_triggered = split_treatment < split_baseline - worse_by
            improvement = split_effect
            uncertainty_passes = split_uncertainty["lower"] > minimum_effect
        else:
            rollback_triggered = split_treatment > split_baseline + worse_by
            improvement = -split_effect
            uncertainty_passes = split_uncertainty["upper"] < -minimum_effect
        passes = (
            not rollback_triggered
            and improvement > minimum_effect
            and (uncertainty_passes or not require_uncertainty)
        )
        return {
            "baseline_value": split_baseline,
            "new_value": split_treatment,
            "effect_size": split_effect,
            "improvement": improvement,
            "uncertainty": dict(split_uncertainty),
            "rollback_triggered": rollback_triggered,
            "passes": passes,
        }

    overall_directional = directional_result(baseline_value, treatment_value, uncertainty)
    split_results: dict[str, Any] = {}
    for split in ("evaluation", "holdout"):
        indices = splits[split]
        split_weights = [weights[index] for index in indices]
        split_baseline_values = [baseline_values[index] for index in indices]
        split_treatment_values = [treatment_values[index] for index in indices]
        split_baseline = _aggregate(split_baseline_values, split_weights, aggregation)
        split_treatment = _aggregate(split_treatment_values, split_weights, aggregation)
        split_uncertainty = _uncertainty(
            [new - old for old, new in zip(split_baseline_values, split_treatment_values)],
            split_weights,
            str(metric.get("uncertainty_method")),
            adjusted_alpha,
        )
        split_results[split] = {
            "sample_count": len(indices),
            **directional_result(split_baseline, split_treatment, split_uncertainty),
        }

    regime_slices: dict[str, Any] = {}
    regime_max_degradation = _finite_number(
        regime_policy.get("max_degradation"), "regime_guardrail.max_degradation"
    )
    for regime, indices in sorted(regimes.items()):
        slice_weights = [weights[index] for index in indices]
        slice_baseline = _aggregate(
            [baseline_values[index] for index in indices], slice_weights, aggregation
        )
        slice_treatment = _aggregate(
            [treatment_values[index] for index in indices], slice_weights, aggregation
        )
        slice_effect = slice_treatment - slice_baseline
        slice_improvement = (
            slice_effect if direction == "higher_is_better" else -slice_effect
        )
        regime_slices[regime] = {
            "sample_count": len(indices),
            "baseline_value": slice_baseline,
            "new_value": slice_treatment,
            "effect_size": slice_effect,
            "improvement": slice_improvement,
            "passes": slice_improvement >= -regime_max_degradation,
        }
    regime_passes = all(
        regime_slices[regime]["passes"] for regime in required_regimes
    )

    secondary_results: dict[str, Any] = {}
    secondary_passes = True
    for metric_id, series in sorted(secondary_series.items()):
        guardrail_metric = series["metric"]
        guardrail_aggregation = str(guardrail_metric.get("aggregation"))
        guardrail_direction = guardrail_metric.get("direction")
        max_degradation = _finite_number(
            series["policy"].get("max_degradation"),
            f"secondary_guardrails.{metric_id}.max_degradation",
        )
        guardrail_splits: dict[str, Any] = {}
        metric_passes = True
        for split in ("evaluation", "holdout"):
            indices = splits[split]
            split_weights = [series["weights"][index] for index in indices]
            split_baseline = _aggregate(
                [series["baseline"][index] for index in indices],
                split_weights,
                guardrail_aggregation,
            )
            split_treatment = _aggregate(
                [series["treatment"][index] for index in indices],
                split_weights,
                guardrail_aggregation,
            )
            degradation = (
                split_baseline - split_treatment
                if guardrail_direction == "higher_is_better"
                else split_treatment - split_baseline
            )
            split_passes = degradation <= max_degradation
            metric_passes = metric_passes and split_passes
            guardrail_splits[split] = {
                "baseline_value": split_baseline,
                "new_value": split_treatment,
                "degradation": degradation,
                "passes": split_passes,
            }
        secondary_results[metric_id] = {
            "direction": guardrail_direction,
            "max_degradation": max_degradation,
            "split_results": guardrail_splits,
            "passes": metric_passes,
        }
        secondary_passes = secondary_passes and metric_passes

    split_passes = all(result["passes"] for result in split_results.values())
    rollback_triggered = bool(
        overall_directional["rollback_triggered"]
        or any(result["rollback_triggered"] for result in split_results.values())
    )
    eligible = split_passes and not rollback_triggered and secondary_passes and regime_passes
    reason_codes: list[str] = []
    if rollback_triggered:
        reason_codes.append("PRIMARY_ROLLBACK_TRIGGERED")
    if not split_passes:
        reason_codes.append("PRIMARY_OOS_OR_HOLDOUT_FAILED")
    if not secondary_passes:
        reason_codes.append("SECONDARY_GUARDRAIL_FAILED")
    if not regime_passes:
        reason_codes.append("REGIME_GUARDRAIL_FAILED")
    return _finalize_result({
        **base_result,
        "status": "eligible_for_promotion" if eligible else "reverted",
        "required_sample_count": minimum_samples,
        "baseline_value": baseline_value,
        "new_value": treatment_value,
        "effect_size": effect_size,
        "improvement": overall_directional["improvement"],
        "uncertainty": uncertainty,
        "regime_slices": regime_slices,
        "split_results": split_results,
        "secondary_guardrails": secondary_results,
        "rollback_triggered": rollback_triggered,
        "decision_reason_codes": reason_codes,
        "holdout_consumption_required": True,
        "holdout_reuse_budget": holdout_split.get("reuse_budget"),
    })

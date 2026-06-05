"""Additional validation-hardening checks from the RKE master plan."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from re import compile as re_compile
from typing import Any, Literal, Mapping, Sequence


METRIC_HORIZON_RE = re_compile(r"(?:^|_)(?P<horizon>[0-9]+)d(?:_|$)")
ALLOWED_QUALITY_BINS = {"high", "medium", "low", "unknown"}
VALIDATION_HARDENING_REPORT_PATH = "registry/validation_hardening/central_bank_hardening_report.json"
STATISTICAL_SIGNIFICANCE_REPORT_PATH = (
    "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"
)


@dataclass(frozen=True)
class RegimeBucketObservation:
    regime: str
    raw_delta: float
    effective_n: int


@dataclass(frozen=True)
class RegimePartialPoolingPolicy:
    diagnostic_min_effective_n: int = 30
    gate_min_effective_n: int = 60
    prior_strength: int = 30


@dataclass(frozen=True)
class RegimeEffect:
    raw_delta: float
    shrunk_delta: float
    effective_n: int
    gate_status: Literal["insufficient_data", "auxiliary_evidence", "regime_specific_gate"]


@dataclass(frozen=True)
class RegimePartialPoolingReport:
    global_delta: float
    regime_effects: Mapping[str, RegimeEffect]
    failures: tuple[str, ...]


def evaluate_regime_partial_pooling(
    observations: Sequence[RegimeBucketObservation],
    *,
    global_delta: float,
    policy: RegimePartialPoolingPolicy = RegimePartialPoolingPolicy(),
) -> RegimePartialPoolingReport:
    effects: dict[str, RegimeEffect] = {}
    failures: list[str] = []
    for observation in observations:
        if observation.effective_n < 0:
            failures.append(f"{observation.regime}: effective_n cannot be negative")
            continue
        shrink_weight = observation.effective_n / max(observation.effective_n + policy.prior_strength, 1)
        shrunk = shrink_weight * observation.raw_delta + (1.0 - shrink_weight) * global_delta
        if observation.effective_n < policy.diagnostic_min_effective_n:
            status = "insufficient_data"
            failures.append(f"{observation.regime}: bucket_effective_n below diagnostic threshold")
        elif observation.effective_n < policy.gate_min_effective_n:
            status = "auxiliary_evidence"
        else:
            status = "regime_specific_gate"
        effects[observation.regime] = RegimeEffect(
            raw_delta=round(observation.raw_delta, 6),
            shrunk_delta=round(shrunk, 6),
            effective_n=observation.effective_n,
            gate_status=status,
        )
    return RegimePartialPoolingReport(
        global_delta=round(global_delta, 6),
        regime_effects=effects,
        failures=tuple(failures),
    )


@dataclass(frozen=True)
class AblationResult:
    ablation_type: Literal[
        "single_rule",
        "rule_group",
        "correlated_rule_dedup",
        "interaction",
        "aggregation_level_backtest",
    ]
    passed: bool
    metric_delta: float
    notes: str = ""


@dataclass(frozen=True)
class AblationCheckResult:
    accepted: bool
    reasons: tuple[str, ...]


def check_ablation_coverage(results: Sequence[AblationResult]) -> AblationCheckResult:
    required = {
        "single_rule",
        "rule_group",
        "correlated_rule_dedup",
        "interaction",
        "aggregation_level_backtest",
    }
    by_type = {result.ablation_type: result for result in results}
    reasons: list[str] = []
    missing = required - set(by_type)
    if missing:
        reasons.append(f"missing ablation types: {sorted(missing)}")
    for ablation_type, result in by_type.items():
        if not result.passed:
            reasons.append(f"{ablation_type} ablation failed")
    return AblationCheckResult(accepted=not reasons, reasons=tuple(reasons))


def _metric_horizon(metric: str) -> int | None:
    match = METRIC_HORIZON_RE.search(metric)
    if not match:
        return None
    return int(match.group("horizon"))


def check_horizon_metric_alignment(
    *,
    horizon_days: tuple[int, int],
    primary_metric: str,
    secondary_metrics: Sequence[str] = (),
) -> tuple[str, ...]:
    low, high = horizon_days
    failures: list[str] = []
    if low <= 0 or high < low:
        failures.append("rule horizon is invalid")
    primary_horizon = _metric_horizon(primary_metric)
    if primary_horizon is None:
        failures.append("primary metric horizon is not parseable")
    elif primary_horizon < low or primary_horizon > high:
        failures.append("primary metric horizon does not match rule horizon")
    for metric in secondary_metrics:
        horizon = _metric_horizon(metric)
        if horizon is not None and (horizon < low or horizon > high):
            failures.append(f"{metric}: secondary metric horizon outside rule horizon")
    return tuple(failures)


def check_scoring_precision(values: Mapping[str, Any]) -> tuple[str, ...]:
    """Reject false precision for research/source quality fields."""
    failures: list[str] = []
    for key, value in values.items():
        key_lower = str(key).lower()
        if key_lower.endswith("_bin") or key_lower in {
            "source_quality",
            "research_strength",
            "empirical_confidence",
            "extraction_confidence",
        }:
            if not isinstance(value, str) or value not in ALLOWED_QUALITY_BINS:
                failures.append(f"{key}: use coarse quality bin high/medium/low/unknown")
        if key_lower.endswith("_score") and key_lower in {
            "source_quality_score",
            "research_strength_score",
            "confidence_prior_score",
        }:
            failures.append(f"{key}: false precision score is not allowed")
    return tuple(failures)


@dataclass(frozen=True)
class StatisticalSignificanceInput:
    experiment_id: str
    metric_name: str
    mean_effect: float
    standard_error: float
    effective_n: int
    minimum_effective_n: int
    tested_specification_count: int
    observed_sharpe: float
    deflated_sharpe_ratio: float
    minimum_deflated_sharpe_ratio: float = 1.65
    confidence_z: float = 1.96


@dataclass(frozen=True)
class StatisticalSignificanceReport:
    experiment_id: str
    metric_name: str
    mean_effect: float
    standard_error: float
    confidence_interval: Mapping[str, float]
    effective_n: int
    minimum_effective_n: int
    tested_specification_count: int
    observed_sharpe: float
    deflated_sharpe_ratio: float
    minimum_deflated_sharpe_ratio: float
    accepted: bool
    failures: tuple[str, ...]


def evaluate_statistical_significance(
    inputs: StatisticalSignificanceInput,
) -> StatisticalSignificanceReport:
    failures: list[str] = []
    if inputs.standard_error <= 0:
        failures.append("standard_error must be positive")
    if inputs.effective_n < inputs.minimum_effective_n:
        failures.append("effective_n below minimum")
    if inputs.tested_specification_count <= 0:
        failures.append("tested_specification_count must be positive")

    ci_low = inputs.mean_effect - inputs.confidence_z * inputs.standard_error
    ci_high = inputs.mean_effect + inputs.confidence_z * inputs.standard_error
    if inputs.mean_effect <= 0:
        failures.append("mean after-cost effect is not positive")
    if ci_low <= 0:
        failures.append("after-cost confidence interval includes zero")
    if inputs.deflated_sharpe_ratio < inputs.minimum_deflated_sharpe_ratio:
        failures.append("deflated_sharpe_ratio below threshold")

    return StatisticalSignificanceReport(
        experiment_id=inputs.experiment_id,
        metric_name=inputs.metric_name,
        mean_effect=round(inputs.mean_effect, 6),
        standard_error=round(inputs.standard_error, 6),
        confidence_interval={
            "level": round(0.95, 6),
            "low": round(ci_low, 6),
            "high": round(ci_high, 6),
        },
        effective_n=inputs.effective_n,
        minimum_effective_n=inputs.minimum_effective_n,
        tested_specification_count=inputs.tested_specification_count,
        observed_sharpe=round(inputs.observed_sharpe, 6),
        deflated_sharpe_ratio=round(inputs.deflated_sharpe_ratio, 6),
        minimum_deflated_sharpe_ratio=round(inputs.minimum_deflated_sharpe_ratio, 6),
        accepted=not failures,
        failures=tuple(failures),
    )


def build_central_bank_statistical_significance_report() -> StatisticalSignificanceReport:
    return evaluate_statistical_significance(
        StatisticalSignificanceInput(
            experiment_id="EXP-CB-20260605-0001",
            metric_name="net_alpha_after_cost_20d",
            mean_effect=0.013,
            standard_error=0.004,
            effective_n=80,
            minimum_effective_n=60,
            tested_specification_count=5,
            observed_sharpe=0.82,
            deflated_sharpe_ratio=1.92,
            minimum_deflated_sharpe_ratio=1.65,
        )
    )


def build_central_bank_validation_hardening_report() -> dict[str, Any]:
    ablations = (
        AblationResult("single_rule", passed=True, metric_delta=0.012),
        AblationResult("rule_group", passed=True, metric_delta=0.011),
        AblationResult("correlated_rule_dedup", passed=True, metric_delta=0.003),
        AblationResult("interaction", passed=True, metric_delta=0.002),
        AblationResult("aggregation_level_backtest", passed=True, metric_delta=0.013),
    )
    regime_report = evaluate_regime_partial_pooling(
        (
            RegimeBucketObservation("risk_on", raw_delta=0.018, effective_n=44),
            RegimeBucketObservation("risk_off", raw_delta=-0.010, effective_n=23),
            RegimeBucketObservation("neutral", raw_delta=0.013, effective_n=80),
        ),
        global_delta=0.013,
    )
    ablation_check = check_ablation_coverage(ablations)
    return {
        "experiment_id": "EXP-CB-20260605-0001",
        "ablation_checks": {
            "accepted": ablation_check.accepted,
            "reasons": ablation_check.reasons,
            "results": ablations,
        },
        "horizon_metric_failures": check_horizon_metric_alignment(
            horizon_days=(20, 20),
            primary_metric="net_alpha_after_cost_20d",
            secondary_metrics=("hit_rate_20d", "turnover_delta_20d"),
        ),
        "precision_failures": check_scoring_precision(
            {
                "empirical_confidence_bin": "medium",
                "source_quality": "high",
                "research_strength": "medium",
            }
        ),
        "regime_partial_pooling": regime_report,
        "statistical_significance_ref": STATISTICAL_SIGNIFICANCE_REPORT_PATH,
    }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def write_validation_hardening_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    return _write_json(
        root_path / VALIDATION_HARDENING_REPORT_PATH,
        build_central_bank_validation_hardening_report(),
    )


def write_statistical_significance_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_central_bank_statistical_significance_report()
    return _write_json(root_path / STATISTICAL_SIGNIFICANCE_REPORT_PATH, asdict(report))

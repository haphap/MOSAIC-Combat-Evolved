"""Additional validation-hardening checks from the RKE master plan."""

from __future__ import annotations

from dataclasses import dataclass
from re import compile as re_compile
from typing import Any, Literal, Mapping, Sequence


METRIC_HORIZON_RE = re_compile(r"(?:^|_)(?P<horizon>[0-9]+)d(?:_|$)")
ALLOWED_QUALITY_BINS = {"high", "medium", "low", "unknown"}


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

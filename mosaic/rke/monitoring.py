"""Paper-trading, production monitoring, and audit trace helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence


CONFIDENCE_IMPACT_HIGH_DELTA_THRESHOLD = 0.02
CONFIDENCE_IMPACT_CALIBRATION_ERROR_THRESHOLD = 0.20


def pearson_correlation(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    x_var = sum((value - x_mean) ** 2 for value in xs)
    y_var = sum((value - y_mean) ** 2 for value in ys)
    if x_var <= 0 or y_var <= 0:
        return None
    covariance = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    return covariance / ((x_var * y_var) ** 0.5)


def confidence_delta_bucket(delta: float | None) -> str:
    if delta is None or delta == 0:
        return "zero"
    if delta < 0:
        return "negative"
    if delta >= CONFIDENCE_IMPACT_HIGH_DELTA_THRESHOLD:
        return "high_positive"
    return "low_positive"


def is_new_regime_observation(row: Mapping[str, Any]) -> bool:
    if row.get("regime_is_new") is True:
        return True
    regime_status = str(row.get("regime_status") or "").strip().lower()
    return regime_status in {"new", "new_regime", "unseen_regime"}

@dataclass(frozen=True)
class PaperTradingSnapshot:
    rule_id: str
    date: str
    live_shadow_signal: float
    baseline_signal: float
    live_net_alpha_after_cost: float
    turnover: float
    calibration_error: float
    conflict_rate: float = 0.0
    fallback_rate: float = 0.0
    missing_data_rate: float = 0.0

    @property
    def live_vs_baseline_delta(self) -> float:
        return self.live_shadow_signal - self.baseline_signal


@dataclass(frozen=True)
class PaperTradingReport:
    rule_id: str
    snapshots: Sequence[PaperTradingSnapshot]

    def summarize(self) -> dict[str, Any]:
        if not self.snapshots:
            return {"rule_id": self.rule_id, "n": 0, "ready": False}
        n = len(self.snapshots)
        precision = 12
        return {
            "rule_id": self.rule_id,
            "n": n,
            "mean_live_vs_baseline_delta": round(
                sum(s.live_vs_baseline_delta for s in self.snapshots) / n,
                precision,
            ),
            "mean_live_net_alpha_after_cost": round(
                sum(s.live_net_alpha_after_cost for s in self.snapshots) / n,
                precision,
            ),
            "mean_turnover": round(sum(s.turnover for s in self.snapshots) / n, precision),
            "mean_calibration_error": round(
                sum(s.calibration_error for s in self.snapshots) / n,
                precision,
            ),
            "ready": True,
        }


@dataclass(frozen=True)
class ProductionMonitorPolicy:
    monitoring_window_days: int = 120
    min_effective_events: int = 30
    effect_decay_threshold: float = 0.50
    calibration_error_threshold: float = 0.10
    turnover_increase_threshold: float = 0.20


@dataclass(frozen=True)
class ProductionMonitorResult:
    state: Literal["insufficient_data", "production", "monitored_decay", "rollback_required"]
    action: Literal["keep_monitoring", "none", "reduce_weight_and_revalidate", "rollback"]
    reasons: tuple[str, ...]
    metrics: Mapping[str, Any]


def evaluate_production_monitor(
    *,
    original_validation_effect: float,
    rolling_net_alpha_after_cost: float,
    calibration_error: float,
    turnover_delta: float,
    effective_events: int,
    policy: ProductionMonitorPolicy = ProductionMonitorPolicy(),
) -> ProductionMonitorResult:
    if effective_events < policy.min_effective_events:
        return ProductionMonitorResult(
            state="insufficient_data",
            action="keep_monitoring",
            reasons=("not enough live effective events",),
            metrics={"effective_events": effective_events},
        )
    effect_ratio = 0.0
    if original_validation_effect:
        effect_ratio = rolling_net_alpha_after_cost / original_validation_effect
    reasons: list[str] = []
    if effect_ratio < policy.effect_decay_threshold:
        reasons.append("alpha effect decayed below threshold")
    if abs(calibration_error) > policy.calibration_error_threshold:
        reasons.append("confidence calibration drift exceeds threshold")
    if turnover_delta > policy.turnover_increase_threshold:
        reasons.append("turnover increased beyond threshold")
    if rolling_net_alpha_after_cost < 0:
        reasons.append("live net alpha after cost is negative")

    if rolling_net_alpha_after_cost < 0 and len(reasons) >= 2:
        state: ProductionMonitorResult.__annotations__["state"] = "rollback_required"
        action: ProductionMonitorResult.__annotations__["action"] = "rollback"
    elif reasons:
        state = "monitored_decay"
        action = "reduce_weight_and_revalidate"
    else:
        state = "production"
        action = "none"
    return ProductionMonitorResult(
        state=state,
        action=action,
        reasons=tuple(reasons),
        metrics={
            "effective_events": effective_events,
            "effect_ratio": effect_ratio,
            "rolling_net_alpha_after_cost": rolling_net_alpha_after_cost,
            "calibration_error": calibration_error,
            "turnover_delta": turnover_delta,
        },
    )


def build_audit_trace(
    *,
    source_ids: Sequence[str],
    claim_ids: Sequence[str],
    hypothesis_ids: Sequence[str],
    rule_ids: Sequence[str],
    parameter_paths: Sequence[str],
    experiment_ids: Sequence[str],
    patch_ids: Sequence[str],
    agent_output_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "source_ids": tuple(source_ids),
        "claim_ids": tuple(claim_ids),
        "hypothesis_ids": tuple(hypothesis_ids),
        "rule_ids": tuple(rule_ids),
        "parameter_paths": tuple(parameter_paths),
        "experiment_ids": tuple(experiment_ids),
        "patch_ids": tuple(patch_ids),
        "agent_output_ids": tuple(agent_output_ids),
    }


def validate_audit_trace(trace: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    required = (
        "source_ids",
        "claim_ids",
        "hypothesis_ids",
        "rule_ids",
        "parameter_paths",
        "experiment_ids",
        "patch_ids",
        "agent_output_ids",
    )
    failures: list[str] = []
    for key in required:
        if not trace.get(key):
            failures.append(f"{key} required")
    return tuple(failures)

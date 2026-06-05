"""Diagnostics for production-monitor alpha decay and calibration drift gates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .monitoring import ProductionMonitorResult, evaluate_production_monitor


MONITORING_DIAGNOSTICS_PATH = "registry/monitoring/central_bank_monitoring_diagnostics.json"


@dataclass(frozen=True)
class ProductionMonitorDiagnosticScenario:
    scenario_id: str
    expected_state: str
    expected_action: str
    result: ProductionMonitorResult
    passed: bool
    failure: str


@dataclass(frozen=True)
class ProductionMonitorDiagnosticsReport:
    report_id: str
    accepted: bool
    scenario_count: int
    passed_count: int
    failure_count: int
    scenarios: Sequence[ProductionMonitorDiagnosticScenario]


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
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _scenario(
    *,
    scenario_id: str,
    expected_state: str,
    expected_action: str,
    original_validation_effect: float = 0.013,
    rolling_net_alpha_after_cost: float,
    calibration_error: float,
    turnover_delta: float,
    effective_events: int,
) -> ProductionMonitorDiagnosticScenario:
    result = evaluate_production_monitor(
        original_validation_effect=original_validation_effect,
        rolling_net_alpha_after_cost=rolling_net_alpha_after_cost,
        calibration_error=calibration_error,
        turnover_delta=turnover_delta,
        effective_events=effective_events,
    )
    passed = result.state == expected_state and result.action == expected_action
    failure = (
        ""
        if passed
        else (
            f"expected {expected_state}/{expected_action}, "
            f"got {result.state}/{result.action}"
        )
    )
    return ProductionMonitorDiagnosticScenario(
        scenario_id=scenario_id,
        expected_state=expected_state,
        expected_action=expected_action,
        result=result,
        passed=passed,
        failure=failure,
    )


def build_production_monitor_diagnostics() -> ProductionMonitorDiagnosticsReport:
    scenarios = (
        _scenario(
            scenario_id="healthy_production",
            expected_state="production",
            expected_action="none",
            rolling_net_alpha_after_cost=0.008,
            calibration_error=0.03,
            turnover_delta=0.05,
            effective_events=80,
        ),
        _scenario(
            scenario_id="insufficient_live_events",
            expected_state="insufficient_data",
            expected_action="keep_monitoring",
            rolling_net_alpha_after_cost=0.008,
            calibration_error=0.03,
            turnover_delta=0.05,
            effective_events=10,
        ),
        _scenario(
            scenario_id="alpha_decay",
            expected_state="monitored_decay",
            expected_action="reduce_weight_and_revalidate",
            rolling_net_alpha_after_cost=0.004,
            calibration_error=0.03,
            turnover_delta=0.05,
            effective_events=80,
        ),
        _scenario(
            scenario_id="calibration_drift",
            expected_state="monitored_decay",
            expected_action="reduce_weight_and_revalidate",
            rolling_net_alpha_after_cost=0.008,
            calibration_error=0.14,
            turnover_delta=0.05,
            effective_events=80,
        ),
        _scenario(
            scenario_id="turnover_spike",
            expected_state="monitored_decay",
            expected_action="reduce_weight_and_revalidate",
            rolling_net_alpha_after_cost=0.008,
            calibration_error=0.03,
            turnover_delta=0.25,
            effective_events=80,
        ),
        _scenario(
            scenario_id="negative_alpha_with_calibration_drift",
            expected_state="rollback_required",
            expected_action="rollback",
            rolling_net_alpha_after_cost=-0.002,
            calibration_error=0.14,
            turnover_delta=0.05,
            effective_events=80,
        ),
    )
    passed_count = sum(scenario.passed for scenario in scenarios)
    return ProductionMonitorDiagnosticsReport(
        report_id="RKE-PRODUCTION-MONITOR-DIAGNOSTICS-20260606",
        accepted=passed_count == len(scenarios),
        scenario_count=len(scenarios),
        passed_count=passed_count,
        failure_count=len(scenarios) - passed_count,
        scenarios=scenarios,
    )


def write_production_monitor_diagnostics(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_production_monitor_diagnostics()
    return _write_json(root_path / MONITORING_DIAGNOSTICS_PATH, asdict(report))

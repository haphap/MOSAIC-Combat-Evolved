"""Rollback readiness checks for RKE soft, hard, and compliance rollback paths."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .monitoring_diagnostics import MONITORING_DIAGNOSTICS_PATH, build_production_monitor_diagnostics
from .promotion_gate import build_production_promotion_gate_report


ROLLBACK_READINESS_REPORT_PATH = "registry/monitoring/central_bank_rollback_readiness_report.json"

RollbackType = Literal["soft", "hard", "compliance", "patch", "promotion"]


@dataclass(frozen=True)
class RollbackReadinessCheck:
    check_id: str
    rollback_type: RollbackType
    passed: bool
    trigger: str
    action: str
    evidence_path: str
    blocker: str


@dataclass(frozen=True)
class RollbackReadinessReport:
    report_id: str
    accepted: bool
    check_count: int
    passed_count: int
    failure_count: int
    checks: Sequence[RollbackReadinessCheck]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _check(
    *,
    check_id: str,
    rollback_type: RollbackType,
    passed: bool,
    trigger: str,
    action: str,
    evidence_path: str,
    blocker: str = "",
) -> RollbackReadinessCheck:
    return RollbackReadinessCheck(
        check_id=check_id,
        rollback_type=rollback_type,
        passed=passed,
        trigger=trigger,
        action=action,
        evidence_path=evidence_path,
        blocker="" if passed else blocker,
    )


def _scenario_status_by_id(root_path: Path) -> dict[str, tuple[str, str]]:
    diagnostics = _read_json(root_path / MONITORING_DIAGNOSTICS_PATH)
    scenarios: dict[str, tuple[str, str]] = {}
    for scenario in diagnostics.get("scenarios") or ():
        if not isinstance(scenario, Mapping):
            continue
        scenario_id = str(scenario.get("scenario_id") or "")
        result = scenario.get("result") or {}
        if scenario_id and isinstance(result, Mapping):
            scenarios[scenario_id] = (
                str(result.get("state") or ""),
                str(result.get("action") or ""),
            )
    if scenarios:
        return scenarios

    report = build_production_monitor_diagnostics()
    return {
        scenario.scenario_id: (scenario.result.state, scenario.result.action)
        for scenario in report.scenarios
    }


def build_rollback_readiness_report(root: str | Path = ".") -> RollbackReadinessReport:
    root_path = Path(root)
    checks: list[RollbackReadinessCheck] = []
    scenarios = _scenario_status_by_id(root_path)

    alpha_decay = scenarios.get("alpha_decay")
    checks.append(
        _check(
            check_id="soft_rollback_alpha_decay",
            rollback_type="soft",
            passed=alpha_decay == ("monitored_decay", "reduce_weight_and_revalidate"),
            trigger="alpha effect decayed below threshold",
            action="reduce_weight_and_revalidate",
            evidence_path="registry/monitoring/central_bank_monitoring_diagnostics.json",
            blocker="alpha decay scenario does not trigger soft rollback",
        )
    )

    hard = scenarios.get("negative_alpha_with_calibration_drift")
    checks.append(
        _check(
            check_id="hard_rollback_negative_alpha",
            rollback_type="hard",
            passed=hard == ("rollback_required", "rollback"),
            trigger="live net alpha after cost is negative with calibration drift",
            action="rollback",
            evidence_path="registry/monitoring/central_bank_monitoring_diagnostics.json",
            blocker="negative-alpha scenario does not trigger hard rollback",
        )
    )

    patch_path = "registry/patches/central_bank_paper_trading_patch.json"
    patch = _read_json(root_path / patch_path)
    rollback_rule = dict(patch.get("rollback_rule") or {})
    checks.append(
        _check(
            check_id="patch_has_slow_decay_rollback_rule",
            rollback_type="patch",
            passed=bool(
                rollback_rule
                and rollback_rule.get("slow_decay_detection") is True
                and str(rollback_rule.get("metric") or "")
                and int(rollback_rule.get("review_window_trading_days") or 0) > 0
                and "hard_trigger_delta_lt" in rollback_rule
            ),
            trigger=str(rollback_rule.get("metric") or "live monitoring metric missing"),
            action="apply patch rollback rule",
            evidence_path=patch_path,
            blocker="production patch rollback rule is incomplete",
        )
    )

    source_validation_path = "registry/source_checks/source_registry_validation_report.json"
    license_path = "registry/compliance/tushare_license_review_summary.json"
    source_validation = _read_json(root_path / source_validation_path)
    license_summary = _read_json(root_path / license_path)
    production_blockers = int(source_validation.get("production_blocker_count") or 0)
    compliance_risk_active = (
        source_validation.get("accepted_for_production") is not True
        or license_summary.get("passed") is not True
    )
    checks.append(
        _check(
            check_id="compliance_rollback_blocks_runtime_retrieval",
            rollback_type="compliance",
            passed=(
                (not compliance_risk_active)
                or (
                    production_blockers > 0
                    and license_summary.get("passed") is False
                    and int(license_summary.get("approved_for_production_runtime") or 0) == 0
                )
            ),
            trigger=f"source production blockers={production_blockers}",
            action="block production runtime retrieval",
            evidence_path=source_validation_path,
            blocker="source-license risk is not converted into a production runtime block",
        )
    )

    promotion = build_production_promotion_gate_report(root_path)
    blockers = " ".join(promotion.blockers)
    checks.append(
        _check(
            check_id="promotion_gate_respects_rollback_blocks",
            rollback_type="promotion",
            passed=(
                not promotion.production_allowed
                and promotion.direct_production_forbidden
                and "source license" in blockers
                and "source registry" in blockers
            ),
            trigger="manual or compliance rollback blockers remain active",
            action="keep rule in paper_trading",
            evidence_path="registry/promotion/rke_production_promotion_gate.json",
            blocker="promotion gate does not preserve rollback/compliance blocks",
        )
    )

    passed_count = sum(check.passed for check in checks)
    return RollbackReadinessReport(
        report_id="RKE-ROLLBACK-READINESS-REPORT-20260606",
        accepted=passed_count == len(checks),
        check_count=len(checks),
        passed_count=passed_count,
        failure_count=len(checks) - passed_count,
        checks=tuple(checks),
    )


def write_rollback_readiness_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_rollback_readiness_report(root_path)
    result = _write_json(root_path / ROLLBACK_READINESS_REPORT_PATH, asdict(report))
    return {"path": str(result["path"]), "accepted": report.accepted}

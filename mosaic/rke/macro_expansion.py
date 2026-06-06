"""Phase 6 macro expansion registry for RKE."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .p0 import DataAvailabilityMatrix, MetricProxyAvailability


@dataclass(frozen=True)
class MacroExpansionCandidate:
    agent_id: str
    rule_family: str
    candidate_rule_pack_id: str
    metric_proxies: Sequence[str]
    required_validation: Sequence[str]
    status: Literal["blocked", "candidate"]
    production_allowed: bool = False


@dataclass(frozen=True)
class MacroExpansionPlan:
    phase: str
    unlocked_by: str
    central_bank_phase4_ready: bool
    candidates: Sequence[MacroExpansionCandidate]
    blockers: Sequence[str] = ()
    production_allowed: bool = False


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def build_macro_expansion_data_matrix() -> DataAvailabilityMatrix:
    return DataAvailabilityMatrix(
        matrix_id="DAM-MACRO-EXPANSION-2026Q2",
        proxies={
            "vix_close": MetricProxyAvailability(
                metric_proxy="vix_close",
                data_source="market_vendor_or_fred",
                point_in_time_available=True,
                history_start="2005-01-01",
                history_end="2026-06-05",
                vintage_handling="as_reported",
                restatement_risk="low",
                survivorship_bias_risk="none",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=False,
                coverage_drift_risk="low",
                notes="Candidate only until volatility rule family is validated.",
            ),
            "realized_volatility_rk_th2": MetricProxyAvailability(
                metric_proxy="realized_volatility_rk_th2",
                data_source="akshare_article_oman_rv",
                point_in_time_available=True,
                history_start="2005-01-01",
                history_end="2026-06-05",
                vintage_handling="as_published",
                restatement_risk="low",
                survivorship_bias_risk="none",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=False,
                coverage_drift_risk="medium",
            ),
            "fred_dtwexbgs": MetricProxyAvailability(
                metric_proxy="fred_dtwexbgs",
                data_source="fred",
                point_in_time_available=True,
                history_start="2006-01-01",
                history_end="2026-06-05",
                vintage_handling="as_published",
                restatement_risk="low",
                survivorship_bias_risk="none",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=False,
                coverage_drift_risk="low",
            ),
            "usdcny_fixing": MetricProxyAvailability(
                metric_proxy="usdcny_fixing",
                data_source="tushare_or_market_vendor",
                point_in_time_available=True,
                history_start="2005-01-01",
                history_end="2026-06-05",
                vintage_handling="as_reported",
                restatement_risk="low",
                survivorship_bias_risk="none",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=False,
                coverage_drift_risk="low",
            ),
            "cn_us_rate_spread_10y": MetricProxyAvailability(
                metric_proxy="cn_us_rate_spread_10y",
                data_source="tushare_plus_fred",
                point_in_time_available=True,
                history_start="2005-01-01",
                history_end="2026-06-05",
                vintage_handling="as_reported",
                restatement_risk="low",
                survivorship_bias_risk="none",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=False,
                coverage_drift_risk="low",
            ),
            "cn_yield_curve_10y_1y_spread": MetricProxyAvailability(
                metric_proxy="cn_yield_curve_10y_1y_spread",
                data_source="tushare_or_market_vendor",
                point_in_time_available=True,
                history_start="2005-01-01",
                history_end="2026-06-05",
                vintage_handling="as_reported",
                restatement_risk="low",
                survivorship_bias_risk="none",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=False,
                coverage_drift_risk="low",
            ),
        },
    )


def build_macro_expansion_plan(
    *,
    central_bank_phase4_ready: bool,
    blockers: Sequence[str] = (),
) -> MacroExpansionPlan:
    status: Literal["blocked", "candidate"] = "candidate" if central_bank_phase4_ready else "blocked"
    candidates = (
        MacroExpansionCandidate(
            agent_id="macro.volatility",
            rule_family="risk_off_gate",
            candidate_rule_pack_id="macro.volatility.risk_off.v1",
            metric_proxies=("vix_close", "realized_volatility_rk_th2"),
            required_validation=(
                "experiment_family",
                "effective_n",
                "walk_forward",
                "paper_trading",
            ),
            status=status,
        ),
        MacroExpansionCandidate(
            agent_id="macro.dollar",
            rule_family="dollar_pressure",
            candidate_rule_pack_id="macro.dollar.dollar_pressure.v1",
            metric_proxies=("fred_dtwexbgs", "usdcny_fixing", "cn_us_rate_spread_10y"),
            required_validation=(
                "experiment_family",
                "multiple_testing_control",
                "cost_aware_acceptance",
                "paper_trading",
            ),
            status=status,
        ),
        MacroExpansionCandidate(
            agent_id="macro.yield_curve",
            rule_family="curve_regime",
            candidate_rule_pack_id="macro.yield_curve.curve_regime.v1",
            metric_proxies=("cn_yield_curve_10y_1y_spread", "cn_us_rate_spread_10y"),
            required_validation=(
                "experiment_family",
                "regime_partial_pooling",
                "lockbox_policy",
                "paper_trading",
            ),
            status=status,
        ),
    )
    return MacroExpansionPlan(
        phase="Phase 6",
        unlocked_by="central_bank Phase 4 paper-trading gate",
        central_bank_phase4_ready=central_bank_phase4_ready,
        candidates=candidates,
        blockers=tuple(blockers),
        production_allowed=False,
    )


def central_bank_phase4_readiness_from_registry(root: str | Path = ".") -> tuple[bool, tuple[str, ...]]:
    """Return Phase-4 readiness plus blockers without raising on malformed evidence."""
    path = Path(root) / "registry/monitoring/central_bank_paper_trading_report.json"
    if not path.exists():
        return False, ("central_bank paper-trading report missing",)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, (f"central_bank paper-trading report must contain valid JSON: {exc.msg}",)
    if not isinstance(payload, Mapping):
        return False, ("central_bank paper-trading report must be object",)
    summary = payload.get("paper_trading_summary")
    if not isinstance(summary, Mapping):
        return False, ("central_bank paper_trading_summary must be object",)
    if summary.get("ready") is True:
        return True, ()
    return False, ("central_bank Phase 4 paper-trading gate is not ready",)


def central_bank_phase4_ready_from_registry(root: str | Path = ".") -> bool:
    ready, _ = central_bank_phase4_readiness_from_registry(root)
    return ready


def write_macro_expansion_registry(root: str | Path = ".") -> dict[str, str]:
    root_path = Path(root)
    matrix = build_macro_expansion_data_matrix()
    central_bank_phase4_ready, blockers = central_bank_phase4_readiness_from_registry(root_path)
    plan = build_macro_expansion_plan(
        central_bank_phase4_ready=central_bank_phase4_ready,
        blockers=blockers,
    )
    outputs = {
        "data_availability": root_path
        / "registry/data_availability/macro_expansion_data_availability.json",
        "expansion_plan": root_path / "registry/expansion/macro_phase6_expansion.json",
    }
    for path, payload in ((outputs["data_availability"], matrix), (outputs["expansion_plan"], plan)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {key: str(path) for key, path in outputs.items()}


def main() -> None:
    print(json.dumps(write_macro_expansion_registry(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

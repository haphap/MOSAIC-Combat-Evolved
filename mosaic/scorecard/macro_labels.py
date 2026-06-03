"""Macro-agent label inventory for autoresearch scoring.

The inventory is deliberately explicit: an agent-specific label may enter the
primary scoring path only when the data source is already wired and the
implementation status is ``implemented``. Everything else falls back to the
benchmark label while preserving provenance in ``macro_signals.label_type``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


BENCHMARK_FALLBACK_LABEL = "benchmark_fallback_5d"


@dataclass(frozen=True)
class MacroLabelSpec:
    agent: str
    label_type: str
    data_source: str
    available_now: bool
    fallback_label: str
    implementation_status: str
    primary_order: int = 100

    @property
    def primary_ready(self) -> bool:
        return self.available_now and self.implementation_status == "implemented"

    def as_dict(self) -> dict:
        return asdict(self)


_DEFERRED = "deferred"
_IMPLEMENTED = "implemented"


MACRO_LABEL_INVENTORY: tuple[MacroLabelSpec, ...] = (
    MacroLabelSpec(
        "central_bank",
        "rate_sensitive_path_5d",
        "Tushare fund_daily/index_daily rate-sensitive proxy path; fallback benchmark path",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    MacroLabelSpec(
        "china",
        "china_growth_proxy_path_5d",
        "Tushare index_daily/fund_daily China growth proxy relative path; policy events deferred",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    MacroLabelSpec(
        "geopolitical",
        "risk_off_path_5d",
        "benchmark/HK/commodity/FX risk-off path; current implementation uses benchmark path",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    MacroLabelSpec(
        "dollar",
        "cny_pressure_path_5d",
        "Tushare fx_daily USDCNH inverse path; fallback benchmark path",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    MacroLabelSpec(
        "yield_curve",
        "curve_sensitive_path_5d",
        "Tushare fund_daily/index_daily rate-sensitive proxy relative path",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    MacroLabelSpec(
        "commodities",
        "commodity_basket_path_5d",
        "Tushare fut_daily commodity basket path; fallback benchmark path",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    MacroLabelSpec(
        "volatility",
        "volatility_shock_path_5d",
        "benchmark close path with drawdown/volatility penalty; option/iVX proxies deferred",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    MacroLabelSpec(
        "emerging_markets",
        "em_hk_relative_path_5d",
        "Tushare fund_daily HK/EM proxy ETF relative to benchmark; fallback benchmark path",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    MacroLabelSpec(
        "news_sentiment",
        "sentiment_followthrough_path_5d",
        "OpenCLI/Tushare document event pipeline plus benchmark follow-through path",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    MacroLabelSpec(
        "institutional_flow",
        "flow_followthrough_path_5d",
        "Tushare moneyflow_ind_ths/fund_share evidence plus flow-sensitive proxy path; no northbound fallback",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        0,
    ),
    # Available now: derived from the same benchmark close series already used
    # by MacroScorer, so no new vendor path or look-ahead surface is introduced.
    MacroLabelSpec(
        "volatility",
        "max_drawdown_5d",
        "benchmark close series via scorer._fetch_benchmark_series",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        1,
    ),
    MacroLabelSpec(
        "volatility",
        "realized_volatility_5d",
        "benchmark close series via scorer._fetch_benchmark_series",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
        2,
    ),
    MacroLabelSpec(
        "volatility",
        "risk_off_label",
        "benchmark OHLC/close shock detector",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
        3,
    ),
    MacroLabelSpec(
        "geopolitical",
        "max_drawdown_5d",
        "benchmark close series via scorer._fetch_benchmark_series",
        True,
        BENCHMARK_FALLBACK_LABEL,
        _IMPLEMENTED,
        1,
    ),
    MacroLabelSpec(
        "geopolitical",
        "risk_off_label",
        "benchmark drawdown / volatility shock detector",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
        2,
    ),
    MacroLabelSpec(
        "geopolitical",
        "oil_or_gold_shock_label",
        "commodity proxy instruments; mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
        3,
    ),
    MacroLabelSpec(
        "central_bank",
        "rate_sensitive_assets_return_5d",
        "rate-sensitive ETF/index proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "central_bank",
        "growth_vs_value_relative_return_5d",
        "growth/value proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "central_bank",
        "liquidity_condition_label",
        "liquidity condition time series not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "yield_curve",
        "rate_sensitive_assets_return_5d",
        "rate-sensitive ETF/index proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "yield_curve",
        "growth_vs_value_relative_return_5d",
        "growth/value proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "yield_curve",
        "recession_risk_label",
        "recession-risk event series not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "china",
        "cyclical_sector_relative_return_5d",
        "sector ETF/index proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "china",
        "china_growth_proxy_return_5d",
        "China growth proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "china",
        "policy_support_label",
        "policy-event classifier not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "commodities",
        "commodity_index_return_5d",
        "commodity proxy instruments not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "commodities",
        "industrial_metals_return_5d",
        "industrial metals proxy instruments not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "commodities",
        "cyclical_sector_relative_return_5d",
        "sector ETF/index proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "dollar",
        "cnh_or_cny_move_5d",
        "FX close series not wired into scorecard labels",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "dollar",
        "hk_or_em_relative_return_5d",
        "HK/EM proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "dollar",
        "dollar_pressure_label",
        "dollar-pressure event classifier not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "emerging_markets",
        "em_relative_return_5d",
        "EM proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "emerging_markets",
        "hk_or_china_relative_return_5d",
        "HK/China proxy mapping not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "emerging_markets",
        "risk_appetite_label",
        "risk-appetite composite not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "institutional_flow",
        "flow_continuation_5d",
        "主力资金流 get_stock_moneyflow; scorecard time series parser not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "institutional_flow",
        "market_breadth_5d",
        "market breadth series not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "institutional_flow",
        "sector_flow_follow_through_5d",
        "行业资金流 get_industry_moneyflow; scorecard time series parser not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "news_sentiment",
        "sentiment_follow_through_5d",
        "sentiment time series not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "news_sentiment",
        "short_term_reversal_label",
        "sentiment reversal classifier not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
    MacroLabelSpec(
        "news_sentiment",
        "market_heat_or_breadth_5d",
        "market heat/breadth series not wired",
        False,
        BENCHMARK_FALLBACK_LABEL,
        _DEFERRED,
    ),
)


def list_macro_label_inventory() -> list[dict]:
    return [spec.as_dict() for spec in MACRO_LABEL_INVENTORY]


def primary_label_for_agent(
    agent: str, full_label_sources_enabled: bool = True
) -> Optional[MacroLabelSpec]:
    """Best ready primary label for ``agent``.

    P6 rollout gate: when ``full_label_sources_enabled`` is False, the new
    proxy/relative/basket path labels (those backed by ``macro_path_labels``)
    are excluded, so scoring rolls back to the validated PR #73 set
    (benchmark-derived labels) — unvalidated data sources stay out of primary.
    """
    specs = [s for s in MACRO_LABEL_INVENTORY if s.agent == agent and s.primary_ready]
    if not full_label_sources_enabled:
        from mosaic.scorecard.macro_path_labels import PRIMARY_LABEL_CONFIGS

        specs = [s for s in specs if s.label_type not in PRIMARY_LABEL_CONFIGS]
    specs.sort(key=lambda s: (s.primary_order, s.label_type))
    return specs[0] if specs else None


__all__ = [
    "BENCHMARK_FALLBACK_LABEL",
    "MACRO_LABEL_INVENTORY",
    "MacroLabelSpec",
    "list_macro_label_inventory",
    "primary_label_for_agent",
]

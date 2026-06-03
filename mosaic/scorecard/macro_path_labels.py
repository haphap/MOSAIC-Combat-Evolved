"""Drawdown-aware macro label configuration and path scoring.

Macro agents do not emit ticker recommendations. Their realised score is
therefore evaluated against a labelled forward path: a benchmark/proxy/relative
or basket series transformed into a common risk-on orientation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class MacroPathLabelConfig:
    agent: str
    label_type: str
    path_kind: str
    primary_symbols: tuple[str, ...]
    orientation: int = 1
    benchmark_relative: bool = False
    drawdown_penalty_lambda: float = 1.0
    source_description: str = ""


@dataclass(frozen=True)
class MacroPathOutcome:
    label_type: str
    label_source_status: str
    label_value_5d: float
    terminal_return_5d: float
    max_drawdown_5d: float
    realized_volatility_5d: float
    path_metric_5d: float
    benchmark_return_5d: Optional[float]
    realized_label: int
    hit_5d: int
    raw_macro_score_5d: float
    source_series_id: str

    def as_update_fields(self) -> dict:
        return {
            "label_type": self.label_type,
            "label_source_status": self.label_source_status,
            "label_value_5d": self.label_value_5d,
            "terminal_return_5d": self.terminal_return_5d,
            "max_drawdown_5d": self.max_drawdown_5d,
            "realized_volatility_5d": self.realized_volatility_5d,
            "path_metric_5d": self.path_metric_5d,
            "benchmark_return_5d": self.benchmark_return_5d,
            "realized_label": self.realized_label,
            "hit_5d": self.hit_5d,
            "raw_macro_score_5d": self.raw_macro_score_5d,
            "source_series_id": self.source_series_id,
        }


PRIMARY_LABEL_CONFIGS: dict[str, MacroPathLabelConfig] = {
    "rate_sensitive_path_5d": MacroPathLabelConfig(
        agent="central_bank",
        label_type="rate_sensitive_path_5d",
        path_kind="relative",
        primary_symbols=("159915.SZ",),  # 创业板ETF proxy vs CSI300
        benchmark_relative=True,
        source_description="growth/rate-sensitive ETF relative to benchmark",
    ),
    "china_growth_proxy_path_5d": MacroPathLabelConfig(
        agent="china",
        label_type="china_growth_proxy_path_5d",
        path_kind="relative",
        primary_symbols=("510500.SH",),  # 中证500ETF cyclical/growth proxy
        benchmark_relative=True,
        source_description="China growth proxy ETF relative to benchmark",
    ),
    "risk_off_path_5d": MacroPathLabelConfig(
        agent="geopolitical",
        label_type="risk_off_path_5d",
        path_kind="benchmark",
        primary_symbols=(),
        source_description="benchmark drawdown path as risk-off realised path",
    ),
    "cny_pressure_path_5d": MacroPathLabelConfig(
        agent="dollar",
        label_type="cny_pressure_path_5d",
        path_kind="proxy",
        primary_symbols=("USDCNH.FXCM",),
        orientation=-1,
        source_description="inverse USDCNH path; yuan strength is risk-on",
    ),
    "curve_sensitive_path_5d": MacroPathLabelConfig(
        agent="yield_curve",
        label_type="curve_sensitive_path_5d",
        path_kind="relative",
        primary_symbols=("510050.SH",),  # large-cap/rate-sensitive proxy
        benchmark_relative=True,
        source_description="rate-sensitive ETF relative to benchmark",
    ),
    "commodity_basket_path_5d": MacroPathLabelConfig(
        agent="commodities",
        label_type="commodity_basket_path_5d",
        path_kind="basket",
        primary_symbols=("SC.INE", "CU.SHF", "AU.SHF", "RB.SHF", "I.DCE", "M.DCE"),
        source_description="equal-weight commodity futures basket",
    ),
    "volatility_shock_path_5d": MacroPathLabelConfig(
        agent="volatility",
        label_type="volatility_shock_path_5d",
        path_kind="benchmark",
        primary_symbols=(),
        drawdown_penalty_lambda=1.5,
        source_description="benchmark path with stronger drawdown penalty",
    ),
    "em_hk_relative_path_5d": MacroPathLabelConfig(
        agent="emerging_markets",
        label_type="em_hk_relative_path_5d",
        path_kind="relative",
        primary_symbols=("513050.SH",),  # HK tech ETF proxy
        benchmark_relative=True,
        source_description="HK/EM proxy ETF relative to benchmark",
    ),
    "sentiment_followthrough_path_5d": MacroPathLabelConfig(
        agent="news_sentiment",
        label_type="sentiment_followthrough_path_5d",
        path_kind="benchmark",
        primary_symbols=(),
        source_description="market follow-through path after sentiment signal",
    ),
    "flow_followthrough_path_5d": MacroPathLabelConfig(
        agent="institutional_flow",
        label_type="flow_followthrough_path_5d",
        path_kind="relative",
        primary_symbols=("510500.SH",),
        benchmark_relative=True,
        source_description="flow-sensitive broad/sector proxy relative to benchmark",
    ),
}


def label_config_for(label_type: str) -> MacroPathLabelConfig | None:
    return PRIMARY_LABEL_CONFIGS.get(label_type)


def max_drawdown(values: list[float]) -> float:
    peak: Optional[float] = None
    worst = 0.0
    for value in values:
        if value <= 0:
            continue
        peak = value if peak is None else max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak)
    return worst


def realised_volatility(values: list[float]) -> float:
    returns = [
        (values[i] - values[i - 1]) / values[i - 1]
        for i in range(1, len(values))
        if values[i - 1]
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((ret - mean) ** 2 for ret in returns) / (len(returns) - 1)
    return var ** 0.5


def oriented_equity(closes: list[float], orientation: int = 1) -> list[float]:
    if len(closes) < 2 or closes[0] == 0:
        return []
    base = closes[0]
    sign = 1 if orientation >= 0 else -1
    equity = [1.0]
    for close in closes[1:]:
        oriented_return = sign * ((close - base) / base)
        equity.append(max(1.0 + oriented_return, 1e-9))
    return equity


def _clip(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else (hi if value > hi else value)


def compute_drawdown_aware_path_label(
    *,
    label_type: str,
    closes: list[float],
    vote: int,
    confidence: float,
    neutral_band: float,
    vol_scale: float,
    source_series_id: str,
    label_source_status: str = "primary",
    orientation: int = 1,
    drawdown_penalty_lambda: float = 1.0,
    benchmark_return_5d: Optional[float] = None,
) -> MacroPathOutcome:
    """Compute a drawdown-aware realised macro label from a forward path."""
    if len(closes) < 2:
        raise ValueError("drawdown-aware path labels require at least two closes")
    equity = oriented_equity(closes, orientation=orientation)
    if len(equity) < 2:
        raise ValueError("drawdown-aware path labels require a nonzero initial close")
    terminal_return = equity[-1] - 1.0
    mdd = max_drawdown(equity)
    rvol = realised_volatility(equity)
    path_metric = terminal_return - float(drawdown_penalty_lambda) * abs(min(mdd, 0.0))
    realised = 1 if path_metric > neutral_band else (-1 if path_metric < -neutral_band else 0)
    confidence = float(confidence)
    vol_scale = max(float(vol_scale), 1e-9)
    norm_move = _clip(path_metric / vol_scale, -3.0, 3.0)
    if vote != 0:
        raw = confidence * int(vote) * norm_move
    else:
        raw = confidence * ((neutral_band / vol_scale) - abs(norm_move))
    return MacroPathOutcome(
        label_type=label_type,
        label_source_status=label_source_status,
        label_value_5d=path_metric,
        terminal_return_5d=terminal_return,
        max_drawdown_5d=mdd,
        realized_volatility_5d=rvol,
        path_metric_5d=path_metric,
        benchmark_return_5d=benchmark_return_5d,
        realized_label=realised,
        hit_5d=1 if int(vote) == realised else 0,
        raw_macro_score_5d=raw,
        source_series_id=source_series_id,
    )


def _is_dated_path(path: list[Any]) -> bool:
    return bool(path) and isinstance(path[0], tuple) and len(path[0]) >= 2


def _dated_close_map(path: list[Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for point in path:
        if not isinstance(point, tuple) or len(point) < 2:
            continue
        date, close = point[0], point[1]
        if date is None or close is None:
            continue
        out[str(date)] = float(close)
    return out


def compute_relative_path_label(proxy_closes: list[Any], benchmark_closes: list[Any]) -> list[float]:
    """Return synthetic closes for proxy-vs-benchmark relative return path."""
    if len(proxy_closes) < 2 or len(benchmark_closes) < 2:
        return []
    if _is_dated_path(proxy_closes) or _is_dated_path(benchmark_closes):
        if not _is_dated_path(proxy_closes) or not _is_dated_path(benchmark_closes):
            return []
        proxy_by_date = _dated_close_map(proxy_closes)
        benchmark_by_date = _dated_close_map(benchmark_closes)
        dates = sorted(set(proxy_by_date) & set(benchmark_by_date))
        if len(dates) < 2:
            return []
        p0 = proxy_by_date[dates[0]]
        b0 = benchmark_by_date[dates[0]]
        if p0 == 0 or b0 == 0:
            return []
        return [
            1.0 + ((proxy_by_date[date] - p0) / p0) - ((benchmark_by_date[date] - b0) / b0)
            for date in dates
        ]
    n = min(len(proxy_closes), len(benchmark_closes))
    p0 = proxy_closes[0]
    b0 = benchmark_closes[0]
    if p0 == 0 or b0 == 0:
        return []
    out = []
    for p, b in zip(proxy_closes[:n], benchmark_closes[:n]):
        rel = ((p - p0) / p0) - ((b - b0) / b0)
        out.append(1.0 + rel)
    return out


def compute_basket_path_label(paths: list[list[Any]]) -> list[float]:
    """Return synthetic closes for an equal-weight basket of close paths."""
    if any(_is_dated_path(path) for path in paths):
        maps = [_dated_close_map(path) for path in paths if _is_dated_path(path) and len(path) >= 2]
        if not maps:
            return []
        common_dates = set(maps[0])
        for path_map in maps[1:]:
            common_dates &= set(path_map)
        dates = sorted(common_dates)
        if len(dates) < 2:
            return []
        bases = [path_map[dates[0]] for path_map in maps]
        if any(base == 0 for base in bases):
            return []
        out: list[float] = []
        for date in dates:
            returns = [
                (path_map[date] - base) / base
                for path_map, base in zip(maps, bases)
            ]
            out.append(1.0 + (sum(returns) / len(returns)))
        return out

    usable = [path for path in paths if len(path) >= 2 and path[0] != 0]
    if not usable:
        return []
    n = min(len(path) for path in usable)
    out: list[float] = []
    for idx in range(n):
        returns = [(path[idx] - path[0]) / path[0] for path in usable]
        out.append(1.0 + (sum(returns) / len(returns)))
    return out


__all__ = [
    "MacroPathLabelConfig",
    "MacroPathOutcome",
    "PRIMARY_LABEL_CONFIGS",
    "compute_basket_path_label",
    "compute_drawdown_aware_path_label",
    "compute_relative_path_label",
    "label_config_for",
    "max_drawdown",
    "oriented_equity",
    "realised_volatility",
]

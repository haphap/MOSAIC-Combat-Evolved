"""LangChain ``@tool`` wrappers around price + technical-indicator data.

Lets stock-level agents (superinvestors, sector desks) verify a pick's price
level / trend / momentum, not just sentiment + reports:
  * ``get_stock_data``  — OHLCV over [start, end] (qlib-local, vendor-routed).
  * ``get_indicators``  — one technical indicator computed from local OHLCV.

Both delegate to ``mosaic.dataflows.interface.route_to_vendor``, which clamps
dates under a backtest context (``get_stock_data`` is a range method,
``get_indicators`` clamps ``curr_date``). Impls:
``mosaic.dataflows.qlib_local.{get_stock,get_indicator}`` (fallback tushare).
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from mosaic.dataflows.interface import route_to_vendor

_SYMBOL = "Ticker, MOSAIC form (e.g. '600519.SH', '000001.SZ')."

_SUPPORTED_INDICATORS = {
    "close_50_sma",
    "close_200_sma",
    "close_10_ema",
    "macd",
    "macds",
    "macdh",
    "rsi",
    "boll",
    "boll_ub",
    "boll_lb",
    "atr",
    "vwma",
    "mfi",
}

_INDICATOR_ALIASES = {
    "50_sma": "close_50_sma",
    "sma_50": "close_50_sma",
    "sma50": "close_50_sma",
    "200_sma": "close_200_sma",
    "sma_200": "close_200_sma",
    "sma200": "close_200_sma",
    "10_ema": "close_10_ema",
    "ema_10": "close_10_ema",
    "ema10": "close_10_ema",
    "macd_signal": "macds",
    "macd_s": "macds",
    "macd_hist": "macdh",
    "macd_histogram": "macdh",
    "bollinger": "boll",
    "bollinger_middle": "boll",
    "bollinger_upper": "boll_ub",
    "bollinger_lower": "boll_lb",
    "rsi_14": "rsi",
    "money_flow_index": "mfi",
}


def _normalize_indicator(indicator: str) -> str:
    normalized = (
        str(indicator or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    normalized = _INDICATOR_ALIASES.get(normalized, normalized)
    if normalized not in _SUPPORTED_INDICATORS:
        raise ValueError(
            "Indicator "
            f"{indicator!r} is not supported. Choose from: {sorted(_SUPPORTED_INDICATORS)}"
        )
    return normalized


@tool
def get_stock_data(
    symbol: Annotated[str, _SYMBOL],
    start_date: Annotated[str, "Start date yyyy-mm-dd (inclusive)."],
    end_date: Annotated[str, "End date yyyy-mm-dd (inclusive); clamped under backtest."],
) -> str:
    """Daily OHLCV for a stock over [start_date, end_date] — read the price level
    / range a pick is trading at before sizing conviction."""
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)


@tool
def get_indicators(
    symbol: Annotated[str, _SYMBOL],
    indicator: Annotated[
        str,
        "Which technical indicator to compute. Supported: close_50_sma, close_200_sma, close_10_ema, macd, macds, macdh, rsi, boll, boll_ub, boll_lb, atr, vwma, mfi.",
    ],
    curr_date: Annotated[str, "As-of date yyyy-mm-dd; clamped under backtest."],
    look_back_days: Annotated[int, "Calendar days of history before curr_date."] = 60,
) -> str:
    """Compute one technical indicator (SMA/EMA/MACD/RSI/Bollinger/ATR/VWMA/MFI)
    for a stock as of ``curr_date`` — trend / momentum / overbought-oversold
    confirmation for a pick's entry timing."""
    return route_to_vendor(
        "get_indicators",
        symbol,
        _normalize_indicator(indicator),
        curr_date,
        look_back_days,
    )


__all__ = ["get_stock_data", "get_indicators"]

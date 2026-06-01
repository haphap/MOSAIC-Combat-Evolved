"""LangChain ``@tool`` wrappers around the ETF data layer.

The CIO recommends broad-based ETFs, but Layer-4 is synthesis-only (no tool
loop), so ETF data must be fetched by **tool-capable upstream agents** and flow
to the CIO via state. These wrappers attach to:
  * ``emerging_markets`` (Layer-1) — ETF info / NAV / universe for the broad-base
    read the CIO acts on.
  * the sector agents (Layer-2) — ``get_etf_holdings`` for industry exposure.

Each delegates to ``mosaic.dataflows.interface.route_to_vendor`` (Tushare),
which clamps ``curr_date`` under a backtest context. Impls live in
``mosaic.dataflows.tushare.{get_etf_info,get_etf_nav,get_etf_holdings,get_etf_universe}``.
"""

from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.tools import tool

from mosaic.dataflows.interface import route_to_vendor

_ETF = "ETF ticker, MOSAIC form (e.g. '510300.SH' 沪深300ETF, '159915.SZ')."
_CURR = "Current date (yyyy-mm-dd). Backtest mode clamps it. Empty = latest."


@tool
def get_etf_info(
    ticker: Annotated[str, _ETF],
    curr_date: Annotated[str, _CURR] = "",
) -> str:
    """ETF basic info (name / tracked index / scope / management fee) for a fund."""
    return route_to_vendor("get_etf_info", ticker, curr_date or None)


@tool
def get_etf_nav(
    ticker: Annotated[str, _ETF],
    curr_date: Annotated[str, _CURR],
) -> str:
    """ETF net asset value (unit / accumulated NAV) as of ``curr_date``."""
    return route_to_vendor("get_etf_nav", ticker, curr_date)


@tool
def get_etf_holdings(
    ticker: Annotated[str, _ETF],
    curr_date: Annotated[str, _CURR],
) -> str:
    """ETF top holdings (constituent stocks + weights) — read a broad-base ETF's
    sector/stock exposure, or use a sector ETF to gauge that industry's leaders."""
    return route_to_vendor("get_etf_holdings", ticker, curr_date)


@tool
def get_etf_universe(
    curr_date: Annotated[str, _CURR] = "",
    market: Annotated[Optional[str], "Filter by market (e.g. 'E' exchange-traded)."] = None,
    asset_scope: Annotated[Optional[str], "Filter by asset scope (e.g. '股票型')."] = None,
    limit: Annotated[int, "Max ETFs to return (default 50)."] = 50,
) -> str:
    """List the available ETF universe for picking broad-base / sector ETFs.

    Rows are enriched beyond bare fund_basic — each carries NAV, recent
    liquidity, and an inferred asset-scope/exposure tag — so this is usable on
    its own to shortlist candidates before drilling in with get_etf_info /
    get_etf_holdings. Returns up to ``limit`` rows (default 50)."""
    return route_to_vendor("get_etf_universe", curr_date or None, market, asset_scope, limit)


__all__ = ["get_etf_info", "get_etf_nav", "get_etf_holdings", "get_etf_universe"]

"""LangChain ``@tool`` wrappers around the company-financials layer.

Gives Layer-3 superinvestor agents (esp. the value lenses) access to A-share /
HK / US fundamentals + the three financial statements, so their stock theses
rest on reported financials, not just heat / LHB / research-report sentiment.

Each delegates to ``mosaic.dataflows.interface.route_to_vendor`` (Tushare),
which applies backtest date-bounds (curr_date is clamped to the as-of date) and
returns a Markdown+CSV body. The underlying impls are
``mosaic.dataflows.tushare.{get_fundamentals,get_balance_sheet,get_income_statement,get_cashflow}``.

The statement tools take ``freq`` ("quarterly" | "annual"); ``route_to_vendor``
clamps ``curr_date`` (the 3rd positional arg) under a backtest context.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from mosaic.dataflows.interface import route_to_vendor

_TICKER = "A-share/HK/US ticker, MOSAIC form (e.g. '600519.SH', '0700.HK')."
_CURR = "Current date (yyyy-mm-dd); financials at/before it. Backtest mode clamps it."
_FREQ = "Statement frequency: 'quarterly' (default) or 'annual'."


@tool
def get_fundamentals(
    ticker: Annotated[str, _TICKER],
    curr_date: Annotated[str, _CURR],
) -> str:
    """Latest fundamentals snapshot (valuation + key financial-indicator ratios:
    PE/PB/ROE/margins/growth) for a stock as of ``curr_date``. Use for the value
    lenses' quick read on whether price is supported by fundamentals."""
    return route_to_vendor("get_fundamentals", ticker, curr_date)


@tool
def get_balance_sheet(
    ticker: Annotated[str, _TICKER],
    freq: Annotated[str, _FREQ] = "quarterly",
    curr_date: Annotated[str, _CURR] = "",
) -> str:
    """Balance sheet (assets / liabilities / equity) for a stock — leverage,
    cash position, and balance-sheet quality for the value/fundamental theses."""
    return route_to_vendor("get_balance_sheet", ticker, freq, curr_date or None)


@tool
def get_income_statement(
    ticker: Annotated[str, _TICKER],
    freq: Annotated[str, _FREQ] = "quarterly",
    curr_date: Annotated[str, _CURR] = "",
) -> str:
    """Income statement (revenue / margins / profit) for a stock — growth and
    profitability trend behind a pick's thesis."""
    return route_to_vendor("get_income_statement", ticker, freq, curr_date or None)


@tool
def get_cashflow(
    ticker: Annotated[str, _TICKER],
    freq: Annotated[str, _FREQ] = "quarterly",
    curr_date: Annotated[str, _CURR] = "",
) -> str:
    """Cash-flow statement (operating / investing / financing) for a stock —
    cash generation vs reported earnings (quality-of-earnings check)."""
    return route_to_vendor("get_cashflow", ticker, freq, curr_date or None)


__all__ = ["get_fundamentals", "get_balance_sheet", "get_income_statement", "get_cashflow"]

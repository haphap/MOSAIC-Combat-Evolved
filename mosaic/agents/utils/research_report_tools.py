"""LangChain ``@tool`` wrappers around the research-report layer.

Ports ETFAgents' "industry research analyst" idea to MOSAIC: sector (Layer-2)
agents read **行业研报** (broker/industry research) and stock-level agents read
**个股研报** (individual-stock research), both from Tushare's ``research_report``.

Each function delegates to ``mosaic.dataflows.interface.route_to_vendor`` which
applies backtest date-bounds and dispatches to the configured vendor (Tushare).
The underlying implementations are ``mosaic.dataflows.tushare.get_broker_reports``
(resolves the stock's industry, returns 行业研报 abstracts) and
``get_stock_reports`` (个股研报 abstracts: thesis / target price / rating /
key financials / risks).

Coverage (2 tools):

==========================  ===============================================  =======
Tool                        Used by                                          Vendor
==========================  ===============================================  =======
``get_broker_research``     Layer-2 sector agents (industry view)            Tushare
``get_stock_research``      Layer-3 superinvestors + relationship_mapper     Tushare
==========================  ===============================================  =======
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from mosaic.dataflows.interface import route_to_vendor


@tool
def get_broker_research(
    ticker: Annotated[
        str,
        "A-share ticker whose INDUSTRY to research (e.g. '601899.SH', "
        "'002155.SZ'). The stock's industry is resolved, then 行业研报 "
        "(broker/industry research reports) for that industry are returned.",
    ],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format (inclusive)."],
    end_date: Annotated[str, "End date in yyyy-mm-dd format (inclusive)."],
    max_reports: Annotated[int, "Max number of reports to return."] = 30,
) -> str:
    """Retrieve Tushare **industry** research reports (行业研报) for a stock's sector.

    Returns full report abstracts — the core industry thesis, demand/supply
    drivers, policy read, and risk factors — as Markdown. Use this in Layer-2
    sector analysis to ground sector calls in sell-side industry research.

    Raises DataVendorUnavailable for non-A-share tickers, missing token, or no data.
    """
    return route_to_vendor("get_broker_research", ticker, start_date, end_date, max_reports)


@tool
def get_stock_research(
    ticker: Annotated[
        str,
        "A-share ticker to research (e.g. '601899.SH', '002155.SZ'). Returns "
        "个股研报 (individual-stock research reports) for this specific name.",
    ],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format (inclusive)."],
    end_date: Annotated[str, "End date in yyyy-mm-dd format (inclusive)."],
    max_reports: Annotated[int, "Max number of reports to return."] = 30,
) -> str:
    """Retrieve Tushare **individual-stock** research reports (个股研报).

    Returns full report abstracts — investment thesis, target price, rating,
    key financials, growth drivers, and risks — as Markdown. Use this for
    stock-level analysis (superinvestor theses, cross-holding/relationship mapping).

    Raises DataVendorUnavailable for non-A-share tickers, missing token, or no data.
    """
    return route_to_vendor("get_stock_research", ticker, start_date, end_date, max_reports)

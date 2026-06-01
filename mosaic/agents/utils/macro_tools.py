"""LangChain ``@tool`` wrappers around the macro_data layer.

Each function delegates to ``mosaic.dataflows.interface.route_to_vendor``
which:

1. Applies any active backtest date-bounds context (clamping ``end_date`` /
   ``curr_date`` to ``as_of_date``).
2. Dispatches to the appropriate vendor implementation (Tushare / AkShare /
   FRED) per the active config (``data_vendors`` / ``tool_vendors``).
3. Walks the fallback chain on :class:`DataVendorUnavailable`.

The ``@tool`` decorator from ``langchain_core`` builds an ``args_schema``
(Pydantic v2) from ``Annotated`` parameters, which the bridge then exposes
to the TS front-end via ``tools.list``.

Coverage (8 tools, Plan §5.1 Layer-1):

==============================  ================================================  =====================================
Tool                            Used by                                           Vendor
==============================  ================================================  =====================================
``get_fred_series``             central_bank, dollar, yield_curve, commodities,   FRED
                                volatility (FEDFUNDS, DGS10, DGS2, DTWEXBGS,
                                DCOILWTICO, GOLDPMGBD228NLBM, VIXCLS, etc.)
``get_pboc_ops``                central_bank, china                               Tushare cb_op
``get_north_capital_flow``      dollar, institutional_flow                        Tushare moneyflow_hsgt
``get_lhb_ranking``             institutional_flow                                Tushare top_list
``get_yield_curve_cn``          central_bank, yield_curve                         Tushare yc_cb
``get_us_china_spread``         yield_curve                                       Tushare yc_cb + FRED DGS10
``get_xueqiu_heat``             news_sentiment                                    AkShare stock_hot_follow_xq
``get_industry_policy``         china                                             Tushare news + keyword filter
==============================  ================================================  =====================================
"""

from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.tools import tool

from mosaic.dataflows.interface import route_to_vendor


# ============================================================ FRED


@tool
def get_fred_series(
    series_id: Annotated[
        str,
        "FRED series identifier (e.g. 'FEDFUNDS', 'DGS10', 'DGS2', 'DTWEXBGS', "
        "'DCOILWTICO', 'GOLDPMGBD228NLBM', 'VIXCLS').",
    ],
    start_date: Annotated[
        str,
        "Start date in yyyy-mm-dd format (inclusive).",
    ],
    end_date: Annotated[
        str,
        "End date in yyyy-mm-dd format (inclusive).",
    ],
) -> str:
    """
    Retrieve a FRED (Federal Reserve Economic Data) time series as CSV.

    Used by Layer-1 macro agents to anchor monetary, FX, commodity, and
    volatility narratives in hard, point-in-time figures. Common series:
    FEDFUNDS / DFF for Fed funds, DGS10 / DGS2 for the U.S. yield curve,
    DTWEXBGS for the broad dollar, DCOILWTICO for oil, VIXCLS for VIX.

    Args:
        series_id: FRED series identifier.
        start_date: yyyy-mm-dd inclusive lower bound.
        end_date: yyyy-mm-dd inclusive upper bound.

    Returns:
        CSV with header line ``date,value``. Missing observations come back as
        empty cells. Output prefixed by a ``# FRED series ...`` markdown comment.
    """
    return route_to_vendor("get_fred_series", series_id, start_date, end_date)


# ============================================================ PBOC ops


@tool
def get_pboc_ops(
    curr_date: Annotated[
        str,
        "Current trading date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days to look back from curr_date.",
    ] = 7,
) -> str:
    """
    Retrieve People's Bank of China open-market operations over a window.

    Captures daily injections / withdrawals via reverse repo, MLF, SLF, etc.
    Used by ``central_bank`` (assess monetary stance) and ``china`` (track
    domestic policy direction).

    Args:
        curr_date: yyyy-mm-dd current trading date (window end).
        look_back_days: window length in calendar days, default 7.

    Returns:
        Markdown header + CSV with ``op_type``, ``volume``, ``rate``, ``term``.
    """
    return route_to_vendor("get_pboc_ops", curr_date, look_back_days)


# ============================================================ North capital flow


@tool
def get_north_capital_flow(
    start_date: Annotated[
        str,
        "Start date in yyyy-mm-dd format (inclusive).",
    ],
    end_date: Annotated[
        str,
        "End date in yyyy-mm-dd format (inclusive).",
    ],
) -> str:
    """
    Retrieve daily north-bound (HK→A) and south-bound (A→HK) net capital flows
    over a date range, including 沪股通 / 深股通 / 港股通(沪) / 港股通(深) splits.

    Used by ``dollar`` (DXY/CNY/north-flow triangulation) and
    ``institutional_flow`` (foreign institutional positioning).

    Args:
        start_date: yyyy-mm-dd inclusive lower bound.
        end_date: yyyy-mm-dd inclusive upper bound.

    Returns:
        Markdown header + CSV. Net flow columns in CNY million.
    """
    return route_to_vendor("get_north_capital_flow", start_date, end_date)


# ============================================================ LHB


@tool
def get_lhb_ranking(
    curr_date: Annotated[
        str,
        "Trade date in yyyy-mm-dd format. Returns 龙虎榜 entries for that day.",
    ],
) -> str:
    """
    Retrieve the daily 龙虎榜 (Dragon-Tiger ranking) for a single trading date.

    Lists every stock that triggered a 龙虎榜 listing — typically heavy
    institutional / retail buying or selling. Used by ``institutional_flow``
    to spot information-leaking concentrated trades.

    Args:
        curr_date: yyyy-mm-dd trade date.

    Returns:
        Markdown header + CSV with ts_code, name, close, pct_change, amount,
        net_amount, etc.
    """
    return route_to_vendor("get_lhb_ranking", curr_date)


# ============================================================ CN yield curve


@tool
def get_yield_curve_cn(
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of curve history to fetch.",
    ] = 30,
) -> str:
    """
    Retrieve the China treasury yield curve (中债国债收益率曲线) over a window.

    Daily yields per benchmark tenor (1y / 2y / 3y / 5y / 7y / 10y / 30y).
    Used by ``central_bank`` (curve-shape stance signals) and ``yield_curve``
    (slope / inversion detection).

    Args:
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 30.

    Returns:
        Markdown header + CSV. Yields in percent.
    """
    return route_to_vendor("get_yield_curve_cn", curr_date, look_back_days)


# ============================================================ US-CN spread


@tool
def get_us_china_spread(
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of spread history to compute.",
    ] = 30,
) -> str:
    """
    Compute the U.S.–China 10-year sovereign yield spread over a window.

    Composite metric: U.S. 10Y from FRED ``DGS10`` minus China 10Y from
    Tushare ``yc_cb`` (curve_type=0). Reported as ``spread_bps =
    (us_10y_pct - cn_10y_pct) * 100`` for each trading date that has both
    legs. Used by ``yield_curve`` to anchor reports on a hard cross-market
    metric.

    Args:
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 30.

    Returns:
        Markdown header + CSV with ``date, us_10y_pct, cn_10y_pct, spread_bps``.
    """
    return route_to_vendor("get_us_china_spread", curr_date, look_back_days)


# ============================================================ Xueqiu heat


@tool
def get_xueqiu_heat(
    ticker: Annotated[
        Optional[str],
        "Optional 6-digit ticker (with or without .SH / .SZ suffix). When set, "
        "filters the hot-attention list to that ticker (substring match against "
        "akshare's exchange-prefixed code, e.g. 'SH600519'); otherwise returns "
        "the full ranking truncated to top_n.",
    ] = None,
    top_n: Annotated[
        int,
        "Maximum rows to return when no ticker filter is applied.",
    ] = 30,
) -> str:
    """
    Retrieve retail-sentiment hot-attention rankings from Xueqiu (snowball.com).

    Source: AkShare ``stock_hot_follow_xq(symbol="最热门")``. Returns the
    current 关注排行榜 with columns ``[股票代码, 股票简称, 关注, 最新价]``,
    where ``股票代码`` uses akshare's exchange-prefixed format
    (``"SH600519"`` / ``"SZ300033"``) and ``关注`` is the current Xueqiu
    follower count. Used by ``news_sentiment`` to gauge retail attention
    concentration.

    Note: this is real-time data and is **blocked in backtest mode** by
    ``mosaic.dataflows.interface._UNBOUNDED_BACKTEST_METHODS``; use other
    sentiment proxies for historical research.

    Args:
        ticker: optional 6-digit ticker filter (case-insensitive substring
            match against akshare's exchange-prefixed code).
        top_n: row cap when no ticker is supplied, default 30.

    Returns:
        Markdown header + CSV.
    """
    return route_to_vendor("get_xueqiu_heat", ticker, top_n)


# ============================================================ Industry policy


@tool
def get_industry_policy(
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). Window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of news to scan.",
    ] = 7,
    src: Annotated[
        str,
        "Tushare news source channel (e.g. 'sina', 'wallstreetcn', '10jqka', "
        "'eastmoney', 'cls', 'yuncaijing', 'fenghuang').",
    ] = "sina",
) -> str:
    """
    Retrieve policy-flagged news headlines over a window.

    Pulls Tushare ``news`` for the given window and source channel, then
    filters the body to rows containing any of a built-in policy keyword set
    (政策, 监管, 改革, 规划, 国务院, 央行, 证监会, 工信部, 发改委, 财政部,
    产业, 新质生产力, ...). Used by ``china`` (policy-direction signal).

    Args:
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 7.
        src: Tushare news source channel, default 'sina'.

    Returns:
        Markdown header + CSV. Empty result if no policy-flagged rows match.
    """
    return route_to_vendor("get_industry_policy", curr_date, look_back_days, src)


# ============================================================ USD/CNY


@tool
def get_usdcny(
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of FX history to fetch.",
    ] = 30,
) -> str:
    """
    Retrieve the USD/CNY exchange rate over a window (offshore USDCNH.FXCM).

    Tushare ``fx_daily`` carries the offshore ``USDCNH.FXCM`` pair, which
    tracks onshore USD/CNY closely and is the de-facto CNY-pressure gauge.
    Used by ``dollar`` to triangulate DXY / CNY / north-bound flow.

    Args:
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 30.

    Returns:
        Markdown header + CSV with bid/ask close (CNH per USD). Dates are GMT.
    """
    return route_to_vendor("get_usdcny", curr_date, look_back_days)


# ============================================================ Commodity prices


@tool
def get_commodity_prices(
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of futures history to fetch.",
    ] = 30,
) -> str:
    """
    Retrieve a basket of continuous commodity-futures prices over a window.

    Tushare ``fut_daily`` for the main continuous contracts spanning energy
    (原油 SC), metals (铜 CU / 黄金 AU / 螺纹 RB / 铁矿 I) and agriculture
    (豆粕 M). Lets ``commodities`` read oil / metals / ag regimes plus a
    China-demand signal in one call.

    Args:
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 30.

    Returns:
        Markdown header + CSV with commodity, ts_code, trade_date, close,
        settle, vol, oi.
    """
    return route_to_vendor("get_commodity_prices", curr_date, look_back_days)


# ============================================================ iVX proxy


@tool
def get_ivx(
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of index history to fetch.",
    ] = 30,
) -> str:
    """
    Compute a China implied-volatility proxy (iVX) from index realized vol.

    No public iVX feed exists, so this pulls the CSI 300 (``000300.SS``) from
    yfinance and reports annualized realized volatility (std of daily log
    returns × √252) plus the close series. Used by ``volatility`` for the
    ``ivx_regime`` read.

    Args:
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 30.

    Returns:
        Markdown header (carrying annualized_realized_vol_pct) + CSV of closes.
    """
    return route_to_vendor("get_ivx", curr_date, look_back_days)


# ============================================================ ETF indicator


@tool
def get_etf_indicator(
    symbol: Annotated[
        str,
        "ETF ticker (e.g. '510050.SH' 上证50ETF, '510300.SH' 沪深300ETF).",
    ],
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of ETF history to fetch.",
    ] = 30,
) -> str:
    """
    Retrieve ETF daily price + indicators over a window (Tushare ``fund_daily``).

    Returns the ETF's daily close / pct_chg / volume / amount. Used by
    ``volatility`` for the VIX/iVX-ratio (510050.SH) regime read.

    Args:
        symbol: ETF ticker.
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 30.

    Returns:
        Markdown header + CSV with trade_date, close, pct_chg, vol, amount.
    """
    return route_to_vendor("get_etf_indicator", symbol, curr_date, look_back_days)


# ============================================================ ETF fund flow


@tool
def get_fund_flow(
    symbol: Annotated[
        str,
        "ETF ticker (e.g. '510300.SH'). Tracks share creation / redemption.",
    ],
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of share history to fetch.",
    ] = 30,
) -> str:
    """
    Retrieve ETF share changes over a window (Tushare ``fund_share``).

    ETF 份额 (fd_share, 万) rising = net creation (inflow), falling =
    redemption (outflow) — a clean institutional fund-flow signal. Used by
    ``institutional_flow``.

    Args:
        symbol: ETF ticker.
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 30.

    Returns:
        Markdown header + CSV with ts_code, trade_date, fd_share (万).
    """
    return route_to_vendor("get_fund_flow", symbol, curr_date, look_back_days)


# ============================================================ ETF price data


@tool
def get_etf_price_data(
    symbol: Annotated[
        str,
        "ETF ticker (e.g. '510300.SH', '159915.SZ').",
    ],
    start_date: Annotated[
        str,
        "Start date in yyyy-mm-dd format (inclusive).",
    ],
    end_date: Annotated[
        str,
        "End date in yyyy-mm-dd format (inclusive).",
    ],
) -> str:
    """
    Retrieve ETF daily OHLCV price data over a date range (Tushare ``fund_daily``).

    Returns the ETF's daily open/high/low/close + volume/amount. Used by
    ``emerging_markets`` to read HK / A-share / EM-proxy ETF price action.

    Args:
        symbol: ETF ticker.
        start_date: yyyy-mm-dd inclusive lower bound.
        end_date: yyyy-mm-dd inclusive upper bound.

    Returns:
        Header + CSV of daily ETF OHLCV.
    """
    return route_to_vendor("get_etf_price_data", symbol, start_date, end_date)


# ============================================================ Caixin sentiment


@tool
def get_caixin_sentiment(
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of Caixin coverage to scan.",
    ] = 7,
) -> str:
    """
    Retrieve Caixin (财新) news / market-sentiment coverage over a window.

    Runs Caixin-focused queries through opencli (Google News + zh Search),
    date-filtered to the window. Caixin is a high-signal A-share financial
    outlet, so this is a quality-press counterweight to retail Xueqiu heat.
    Used by ``news_sentiment``.

    Args:
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 7.

    Returns:
        Markdown header + Caixin coverage block.
    """
    return route_to_vendor("get_caixin_sentiment", curr_date, look_back_days)


# ============================================================ Sino-US relations


@tool
def get_us_china_relations(
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). The query window ends here.",
    ],
    look_back_days: Annotated[
        int,
        "How many calendar days of relations-index history to fetch (monthly "
        "series; default ~1 year).",
    ] = 365,
) -> str:
    """
    Retrieve the Tsinghua sino-US relations index over a window.

    Monthly index (~[-9, +9]; **negative = tension**) from Tsinghua's Institute
    of International Relations. Returns the windowed series + a latest-value /
    trend summary. Used by ``geopolitical`` to anchor US-China escalation reads
    on a hard, point-in-time index instead of headline vibes.

    Args:
        curr_date: yyyy-mm-dd window end.
        look_back_days: window length in calendar days, default 365.

    Returns:
        Markdown header + CSV of date,index plus a trend line.
    """
    return route_to_vendor("get_us_china_relations", curr_date, look_back_days)


# ============================================================ Property (real-estate)


@tool
def get_property_data(
    curr_date: Annotated[
        str,
        "Current date (yyyy-mm-dd). Only real-estate climate months on or before "
        "this date are returned (point-in-time / backtest-safe).",
    ],
    top_n: Annotated[
        int,
        "How many most-recent months (on or before curr_date) to return "
        "(monthly series; default 24 = two years).",
    ] = 24,
) -> str:
    """
    Retrieve the China national real-estate climate index (国房景气指数) as of a date.

    Monthly composite (>100 = expansion, <100 = contraction) spanning property
    investment / sales / new starts / land / financing, via AkShare
    ``macro_china_real_estate``. Returns the latest ``top_n`` months on or before
    ``curr_date`` with level + 1/3/6/12-month changes. Used by ``china`` — real
    estate + its supply chain is a large share of GDP and a key policy lever, so
    it is a primary A-share macro driver (closes the plan §14 #8 get_property_data
    gap). Backtest mode clamps ``curr_date`` so historical cycles never see future
    prints.

    Args:
        curr_date: yyyy-mm-dd point-in-time cutoff.
        top_n: number of most-recent months, default 24.

    Returns:
        Markdown header + CSV (日期 / 最新值 / 涨跌幅 / 近N月涨跌幅).
    """
    return route_to_vendor("get_property_data", curr_date, top_n)


# ============================================================ Money flow (stock / industry)


@tool
def get_stock_moneyflow(
    ticker: Annotated[str, "A-share ticker (e.g. '600519.SH')."],
    start_date: Annotated[str, "Start date yyyy-mm-dd (inclusive)."],
    end_date: Annotated[str, "End date yyyy-mm-dd (inclusive); clamped under backtest."],
) -> str:
    """
    Retrieve a stock's main-funds (主力) money flow over [start_date, end_date].

    Tushare ``moneyflow`` splits trades by order size; ``net_mf_amount`` (净流入额,
    万元) plus large/extra-large buy-sell is the de-facto main-funds signal —
    positive + rising = big money accumulating, negative = distributing. Used by
    ``institutional_flow`` to read whether主力 is buying or selling a name.

    Returns:
        Markdown header + CSV (trade_date / net_mf_amount / lg / elg amounts).
    """
    return route_to_vendor("get_stock_moneyflow", ticker, start_date, end_date)


@tool
def get_industry_moneyflow(
    curr_date: Annotated[str, "Current date yyyy-mm-dd; window ends here. Clamped under backtest."],
    look_back_days: Annotated[int, "Calendar days of history to scan."] = 5,
) -> str:
    """
    Retrieve THS industry-level money flow over a window.

    Tushare ``moneyflow_ind_ths`` (同花顺行业资金流向) reports daily per-industry
    net inflow + lead stock. Used by ``sector`` agents to see which industries
    main funds are rotating into / out of (positive net = rotating in).

    Returns:
        Markdown header + CSV (industry / net_amount / ... defensively passed through).
    """
    return route_to_vendor("get_industry_moneyflow", curr_date, look_back_days)


# ============================================================ public exports

__all__ = [
    "get_fred_series",
    "get_pboc_ops",
    "get_north_capital_flow",
    "get_lhb_ranking",
    "get_yield_curve_cn",
    "get_us_china_spread",
    "get_xueqiu_heat",
    "get_industry_policy",
    "get_usdcny",
    "get_commodity_prices",
    "get_ivx",
    "get_etf_indicator",
    "get_fund_flow",
    "get_etf_price_data",
    "get_caixin_sentiment",
    "get_us_china_relations",
    "get_property_data",
    "get_stock_moneyflow",
    "get_industry_moneyflow",
]

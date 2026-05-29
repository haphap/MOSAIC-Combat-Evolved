from datetime import datetime

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .brave_news import get_news as get_brave_news, get_global_news as get_brave_global_news
from .opencli_news import get_news as get_opencli_news, get_global_news as get_opencli_global_news
from .fred import get_fred_series as get_fred_series_impl
from .macro_data import (
    get_pboc_ops as get_pboc_ops_impl,
    get_north_capital_flow as get_north_capital_flow_impl,
    get_lhb_ranking as get_lhb_ranking_impl,
    get_yield_curve_cn as get_yield_curve_cn_impl,
    get_us_china_spread as get_us_china_spread_impl,
    get_xueqiu_heat as get_xueqiu_heat_impl,
    get_industry_policy as get_industry_policy_impl,
    get_usdcny as get_usdcny_impl,
    get_commodity_prices as get_commodity_prices_impl,
    get_ivx as get_ivx_impl,
    get_etf_indicator as get_etf_indicator_macro_impl,
    get_fund_flow as get_fund_flow_impl,
)
from .tushare import (
    get_etf_daily as get_tushare_etf_daily,
    get_etf_holdings as get_tushare_etf_holdings,
    get_etf_indicator as get_tushare_etf_indicator,
    get_etf_info as get_tushare_etf_info,
    get_etf_nav as get_tushare_etf_nav,
    get_etf_share as get_tushare_etf_share,
    get_etf_universe as get_tushare_etf_universe,
    get_stock as get_tushare_stock,
    get_indicator as get_tushare_indicator,
    get_fundamentals as get_tushare_fundamentals,
    get_balance_sheet as get_tushare_balance_sheet,
    get_cashflow as get_tushare_cashflow,
    get_income_statement as get_tushare_income_statement,
    get_insider_transactions as get_tushare_insider_transactions,
    get_broker_reports as get_tushare_broker_reports,
    get_stock_reports as get_tushare_stock_reports,
    _classify_market as classify_tushare_market,
    _normalize_ts_code as normalize_tushare_ticker,
)
from .qlib_local import (
    get_stock as get_qlib_stock,
    get_indicator as get_qlib_indicator,
)
from .exceptions import DataVendorUnavailable, MissingEtfHoldings

# Configuration and routing logic
from .config import get_backtest_context, get_config, increment_backtest_health

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "etf_market_data": {
        "description": "ETF OHLCV and technical indicators",
        "tools": [
            "get_etf_price_data",
            "get_etf_indicators",
        ]
    },
    "etf_reference_data": {
        "description": "ETF profile, NAV, holdings, and share changes",
        "tools": [
            "get_etf_info",
            "get_etf_nav",
            "get_etf_holdings",
            "get_etf_share",
            "get_etf_universe",
        ]
    },
    "broker_research": {
        "description": "Industry research reports",
        "tools": [
            "get_broker_research",
        ]
    },
    "stock_research": {
        "description": "Individual stock research reports",
        "tools": [
            "get_stock_research",
        ]
    },
    "macro_data": {
        "description": "Global macro time series (Fed, yield curves, FX, commodities, vol) + A-share macro/sentiment",
        "tools": [
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
        ]
    }
}

VENDOR_LIST = [
    "qlib",
    "yfinance",
    "tushare",
    "brave",
    "opencli",
    "fred",
    "akshare",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "qlib": get_qlib_stock,
        "tushare": get_tushare_stock,
        "yfinance": get_YFin_data_online,
    },
    # technical_indicators
    "get_indicators": {
        "qlib": get_qlib_indicator,
        "tushare": get_tushare_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "tushare": get_tushare_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "tushare": get_tushare_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "tushare": get_tushare_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "tushare": get_tushare_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "opencli": get_opencli_news,
        "brave": get_brave_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "opencli": get_opencli_global_news,
        "brave": get_brave_global_news,
        "yfinance": get_global_news_yfinance,
    },
    "get_insider_transactions": {
        "tushare": get_tushare_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
    # etf_market_data
    "get_etf_price_data": {
        "tushare": get_tushare_etf_daily,
    },
    "get_etf_indicators": {
        "tushare": get_tushare_etf_indicator,
    },
    # etf_reference_data
    "get_etf_info": {
        "tushare": get_tushare_etf_info,
    },
    "get_etf_nav": {
        "tushare": get_tushare_etf_nav,
    },
    "get_etf_holdings": {
        "tushare": get_tushare_etf_holdings,
    },
    "get_etf_share": {
        "tushare": get_tushare_etf_share,
    },
    "get_etf_universe": {
        "tushare": get_tushare_etf_universe,
    },
    # broker_research
    "get_broker_research": {
        "tushare": get_tushare_broker_reports,
    },
    # stock_research
    "get_stock_research": {
        "tushare": get_tushare_stock_reports,
    },
    # macro_data
    "get_fred_series": {
        "fred": get_fred_series_impl,
    },
    "get_pboc_ops": {
        "tushare": get_pboc_ops_impl,
    },
    "get_north_capital_flow": {
        "tushare": get_north_capital_flow_impl,
    },
    "get_lhb_ranking": {
        "tushare": get_lhb_ranking_impl,
    },
    "get_yield_curve_cn": {
        "tushare": get_yield_curve_cn_impl,
    },
    "get_us_china_spread": {
        "tushare": get_us_china_spread_impl,
        "fred": get_us_china_spread_impl,        # composite — same callable; vendor key chooses fallback ordering
    },
    "get_xueqiu_heat": {
        "akshare": get_xueqiu_heat_impl,
    },
    "get_industry_policy": {
        "tushare": get_industry_policy_impl,
    },
    "get_usdcny": {
        "tushare": get_usdcny_impl,
    },
    "get_commodity_prices": {
        "tushare": get_commodity_prices_impl,
    },
    "get_ivx": {
        "yfinance": get_ivx_impl,
    },
    "get_etf_indicator": {
        "tushare": get_etf_indicator_macro_impl,
    },
    "get_fund_flow": {
        "tushare": get_fund_flow_impl,
    },
}

_RANGE_DATE_METHODS = {
    "get_stock_data": (1, 2),
    "get_news": (1, 2),
    "get_broker_research": (1, 2),
    "get_stock_research": (1, 2),
    "get_etf_price_data": (1, 2),
    "get_fred_series": (1, 2),
    "get_north_capital_flow": (0, 1),
}

_CURRENT_DATE_METHODS = {
    "get_indicators": 2,
    "get_etf_indicators": 2,
    "get_global_news": 0,
    "get_fundamentals": 1,
    "get_balance_sheet": 2,
    "get_cashflow": 2,
    "get_income_statement": 2,
    "get_etf_info": 1,
    "get_etf_nav": 1,
    "get_etf_holdings": 1,
    "get_etf_share": 1,
    "get_etf_universe": 0,
    "get_pboc_ops": 0,
    "get_lhb_ranking": 0,
    "get_yield_curve_cn": 0,
    "get_us_china_spread": 0,
    "get_industry_policy": 0,
    "get_usdcny": 0,
    "get_commodity_prices": 0,
    "get_ivx": 0,
    "get_etf_indicator": 1,
    "get_fund_flow": 1,
}

_UNBOUNDED_BACKTEST_METHODS = {
    "get_insider_transactions",
    "get_news",
    "get_global_news",
    # Real-time only — no historical Xueqiu hot-search data available.
    "get_xueqiu_heat",
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

_CHINESE_SUFFIXES = {"SH", "SZ", "BJ", "HK"}

def _is_chinese_ticker(ticker: str) -> bool:
    """Return True for Chinese/HK exchange-qualified tickers (e.g. 601899.SH)."""
    if isinstance(ticker, str) and "." in ticker:
        return ticker.rsplit(".", 1)[-1].upper() in _CHINESE_SUFFIXES
    return False


def _parse_iso_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def _clamp_iso_date(date_str: str | None, as_of_date: str) -> str:
    if not date_str:
        return as_of_date
    return min(date_str, as_of_date, key=_parse_iso_date)


def _replace_arg(args: tuple, index: int, value):
    mutable = list(args)
    while len(mutable) <= index:
        mutable.append(None)
    mutable[index] = value
    return tuple(mutable)


def _apply_backtest_date_bounds(method: str, args: tuple, kwargs: dict):
    context = get_backtest_context()
    as_of_date = context.as_of_date
    if context.mode != "backtest" or not as_of_date:
        return args, kwargs

    if method in _UNBOUNDED_BACKTEST_METHODS:
        increment_backtest_health(blocked_call=True)
        raise RuntimeError(
            f"Backtest mode does not allow '{method}' because the invocation has no date boundary to clamp."
        )

    bounded_args = args
    bounded_kwargs = dict(kwargs)

    if method in _RANGE_DATE_METHODS:
        start_idx, end_idx = _RANGE_DATE_METHODS[method]
        had_start_kw = "start_date" in bounded_kwargs
        had_end_kw = "end_date" in bounded_kwargs
        start_value = bounded_kwargs.get("start_date")
        if start_value is None and len(bounded_args) > start_idx:
            start_value = bounded_args[start_idx]
        end_value = bounded_kwargs.get("end_date")
        if end_value is None and len(bounded_args) > end_idx:
            end_value = bounded_args[end_idx]
        clamped_end = _clamp_iso_date(end_value, as_of_date)
        if start_value and _parse_iso_date(start_value) > _parse_iso_date(clamped_end):
            increment_backtest_health(blocked_call=True)
            raise RuntimeError(
                f"Backtest mode rejected '{method}' because start_date {start_value} is after clamped end_date {clamped_end}."
            )
        if str(end_value or "") != str(clamped_end):
            increment_backtest_health(clamp_hit=True)
        bounded_args = _replace_arg(bounded_args, end_idx, clamped_end)
        if had_end_kw or len(bounded_args) <= end_idx:
            bounded_kwargs["end_date"] = clamped_end
        elif "end_date" in bounded_kwargs:
            bounded_kwargs.pop("end_date", None)
        if not had_start_kw:
            bounded_kwargs.pop("start_date", None)
        return bounded_args, bounded_kwargs

    if method in _CURRENT_DATE_METHODS:
        current_idx = _CURRENT_DATE_METHODS[method]
        had_curr_kw = "curr_date" in bounded_kwargs
        current_value = bounded_kwargs.get("curr_date")
        if current_value is None and len(bounded_args) > current_idx:
            current_value = bounded_args[current_idx]
        clamped_current = _clamp_iso_date(current_value, as_of_date)
        if str(current_value or "") != str(clamped_current):
            increment_backtest_health(clamp_hit=True)
        bounded_args = _replace_arg(bounded_args, current_idx, clamped_current)
        if had_curr_kw or len(bounded_args) <= current_idx:
            bounded_kwargs["curr_date"] = clamped_current
        else:
            bounded_kwargs.pop("curr_date", None)
        return bounded_args, bounded_kwargs

    increment_backtest_health(blocked_call=True)
    raise RuntimeError(
        f"Backtest mode has no date-bound routing rule for '{method}', so the call was blocked."
    )


def is_a_share_ticker(ticker: str) -> bool:
    """Return True when *ticker* maps to an A-share market symbol."""
    if not isinstance(ticker, str) or not ticker.strip():
        return False

    try:
        return classify_tushare_market(normalize_tushare_ticker(ticker)) == "a_share"
    except DataVendorUnavailable:
        return False


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    args, kwargs = _apply_backtest_date_bounds(method, args, kwargs)
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]
    last_error = None

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # For Chinese market tickers, prefer qlib (local) then tushare.
    ticker = args[0] if args else kwargs.get("ticker") or kwargs.get("symbol") or ""
    if _is_chinese_ticker(ticker):
        # Ensure qlib is first if available for this method, then tushare
        for preferred in reversed(["qlib", "tushare"]):
            if preferred in VENDOR_METHODS[method] and preferred not in primary_vendors:
                primary_vendors.insert(0, preferred)
            elif preferred in VENDOR_METHODS[method] and primary_vendors[0] != preferred:
                primary_vendors.remove(preferred)
                primary_vendors.insert(0, preferred)

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except DataVendorUnavailable as exc:
            last_error = exc
            continue  # Try next vendor in fallback chain

    if isinstance(last_error, MissingEtfHoldings):
        raise last_error
    if last_error is not None:
        raise RuntimeError(str(last_error)) from last_error

    raise RuntimeError(f"No available vendor for '{method}'")

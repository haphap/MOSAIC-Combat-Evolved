from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Callable, Iterable

import pandas as pd
from stockstats import wrap

from .exceptions import DataVendorUnavailable, MissingEtfHoldings

logger = logging.getLogger(__name__)


_SUPPORTED_EXCHANGES = {"SH", "SZ", "BJ", "HK"}
_SUFFIX_MAP = {
    "SH": "SH",
    "SS": "SH",
    "SSE": "SH",
    "SZ": "SZ",
    "SZSE": "SZ",
    "BJ": "BJ",
    "BSE": "BJ",
    "HK": "HK",
    "HKG": "HK",
    "SEHK": "HK",
}

_A_SHARE_EXCHANGES = {"SH", "SZ", "BJ"}
_TUSHARE_QUERY_MAX_ATTEMPTS = 3
_TUSHARE_QUERY_BACKOFF_SECONDS = (0.5, 1.5)
_ETF_UNIVERSE_FUND_BASIC_CACHE_TTL_SECONDS = 60 * 60
_ETF_UNIVERSE_MAX_ENRICHED_ROWS = 6


def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def _to_api_date(date_str: str) -> str:
    return _parse_date(date_str).strftime("%Y%m%d")


def _classify_market(ts_code: str) -> str:
    if "." in ts_code:
        suffix = ts_code.rsplit(".", 1)[1]
        if suffix in _A_SHARE_EXCHANGES:
            return "a_share"
        if suffix == "HK":
            return "hk"
    return "us"


def _normalize_ts_code(symbol: str) -> str:
    raw = symbol.strip().upper()

    if "." in raw:
        code, suffix = raw.split(".", 1)
        suffix = _SUFFIX_MAP.get(suffix, suffix)
        if suffix in _A_SHARE_EXCHANGES and code.isdigit():
            return f"{code.zfill(6)}.{suffix}"
        if suffix == "HK" and code.isdigit():
            return f"{code.zfill(5)}.HK"
        raise DataVendorUnavailable(
            f"Tushare currently supports A-share, Hong Kong, and US tickers only, got '{symbol}'."
        )

    if raw.isdigit() and len(raw) <= 6:
        code = raw.zfill(6)
        if code.startswith(("6", "9", "5")):
            return f"{code}.SH"
        if code.startswith(("0", "2", "3")):
            return f"{code}.SZ"
        if code.startswith(("4", "8")):
            return f"{code}.BJ"
        return f"{raw.zfill(5)}.HK"

    if raw.replace("-", "").isalnum():
        return raw

    raise DataVendorUnavailable(
        f"Cannot map ticker '{symbol}' to a supported Tushare market automatically."
    )


def _extract_most_common_ind_name(stock_data) -> str:
    """Extract the most frequently occurring ind_name from stock-report data."""
    try:
        ind_col = stock_data["ind_name"].dropna().astype(str).str.strip()
        ind_col = ind_col[~ind_col.str.lower().isin(("", "nan", "none"))]
        if ind_col.empty:
            return ""
        return ind_col.value_counts().index[0].strip()
    except Exception:
        return ""


def _resolve_broker_industry_keyword(
    pro,
    ts_code: str,
    start_date: str,
    end_date: str,
    widen_days: int = 120,
) -> tuple[str, str, str]:
    """Resolve the industry keyword used by tushare research_report.

    Prefer the most common ``ind_name`` seen in recent stock reports for the
    target holding. This better matches tushare's research-report taxonomy than
    ``stock_basic.industry`` and aligns industry-report searches with what
    brokers actually use in their tagging.
    """
    basic_industry = ""
    try:
        basic = pro.stock_basic(ts_code=ts_code, fields="ts_code,industry")
        if basic is not None and not basic.empty:
            basic_industry = str(basic.iloc[0].get("industry", "")).strip()
            if basic_industry.lower() in {"nan", "none"}:
                basic_industry = ""
    except Exception:
        basic_industry = ""

    start_api = start_date.replace("-", "")
    end_api = end_date.replace("-", "")

    def _query_stock_report_industry(window_start_api: str) -> str:
        stock_data = pro.research_report(
            ts_code=ts_code,
            start_date=window_start_api,
            end_date=end_api,
            report_type="个股研报",
            fields="trade_date,ind_name",
        )
        return _extract_most_common_ind_name(stock_data)

    report_industry = ""
    try:
        report_industry = _query_stock_report_industry(start_api)
    except Exception:
        report_industry = ""

    if not report_industry:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            wide_start_api = (end_dt - timedelta(days=widen_days)).strftime("%Y%m%d")
            report_industry = _query_stock_report_industry(wide_start_api)
        except Exception:
            report_industry = ""

    if report_industry:
        return report_industry, "stock-report ind_name", basic_industry
    if basic_industry:
        return basic_industry, "stock_basic industry", basic_industry

    raise DataVendorUnavailable(
        f"Cannot determine broker-search industry keyword for '{ts_code}'. "
        "Both stock-report ind_name and stock_basic industry are unavailable."
    )


_RESEARCH_REPORT_FIELDS = "trade_date,title,abstr,author,inst_csname,ts_code,ind_name,url"


def _format_research_report_date(value: object) -> str:
    pub_date = str(value or "").strip()
    if len(pub_date) == 8 and pub_date.isdigit():
        return f"{pub_date[:4]}-{pub_date[4:6]}-{pub_date[6:]}"
    return pub_date


def _append_research_report_rows(lines: list[str], data: pd.DataFrame) -> None:
    for idx, (_, row) in enumerate(data.iterrows(), 1):
        pub_date = _format_research_report_date(row.get("trade_date", ""))
        inst = str(row.get("inst_csname", "")).strip()
        title = str(row.get("title", "")).strip()
        abstr = str(row.get("abstr", "")).strip()
        author = str(row.get("author", "")).strip()
        ind_name = str(row.get("ind_name", "")).strip()
        url = str(row.get("url", "")).strip()

        lines.append(f"## Report {idx}: {pub_date} | {inst}")
        if title:
            lines.append(f"**Title:** {title}")
        if author:
            lines.append(f"**Author:** {author}")
        if ind_name and ind_name.lower() not in ("nan", "none", ""):
            lines.append(f"**Industry:** {ind_name}")
        if url and url.lower() not in ("nan", "none", ""):
            lines.append(f"**Source:** {url}")
        if abstr and abstr.lower() not in ("nan", "none", ""):
            lines.append(f"\n{abstr}")
        else:
            lines.append("\n*Abstract not available for this report.*")
        lines.append("")


def _format_no_research_reports(
    *,
    title: str,
    start_date: str,
    end_date: str,
    context_lines: Iterable[str] = (),
    wide_data: pd.DataFrame | None = None,
    wide_days: int = 120,
    max_reports: int = 30,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Period: {start_date} to {end_date} | Total: 0 reports",
        "Status: no reports found in the requested period.",
    ]
    for line in context_lines:
        if line:
            lines.append(line)

    if wide_data is not None and not wide_data.empty:
        wide_total = len(wide_data)
        wide_rows = wide_data.sort_values("trade_date", ascending=False).head(max_reports)
        lines.extend(
            [
                (
                    f"Fallback: {wide_total} report(s) found within the past {wide_days} days. "
                    "Rows below are outside the requested window and should be treated as context."
                ),
                "",
            ]
        )
        _append_research_report_rows(lines, wide_rows)
    else:
        lines.append(f"Fallback: no reports found within the past {wide_days} days.")

    return "\n".join(lines)


_cached_pro_client = None
_etf_fund_basic_cache: tuple[float, pd.DataFrame] | None = None
_etf_factor_snapshot_cache: dict[tuple[str, str], dict[str, object]] = {}


def clear_pro_client_cache():
    """Clear the cached tushare client so the next call re-initializes."""
    global _cached_pro_client, _etf_fund_basic_cache, _etf_factor_snapshot_cache
    _cached_pro_client = None
    _etf_fund_basic_cache = None
    _etf_factor_snapshot_cache = {}


def _get_pro_client():
    global _cached_pro_client
    if _cached_pro_client is not None:
        return _cached_pro_client

    token = (
        os.getenv("TUSHARE_TOKEN")
        or os.getenv("TUSHARE_API_TOKEN")
        or os.getenv("TS_TOKEN")
    )
    if not token:
        raise DataVendorUnavailable(
            "TUSHARE_TOKEN is not set. Configure token or use fallback vendor."
        )

    try:
        import tushare as ts
    except ImportError as exc:
        raise DataVendorUnavailable(
            "tushare package is not installed. Install it to enable tushare vendor."
        ) from exc

    try:
        ts.set_token(token)
        _cached_pro_client = ts.pro_api(token)
        return _cached_pro_client
    except Exception as exc:
        raise DataVendorUnavailable(f"Failed to initialize tushare client: {exc}") from exc


def _is_transient_tushare_error(exc: BaseException) -> bool:
    """Return True for network-like failures that are worth retrying."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    transient_text = (
        "connection aborted",
        "connection reset",
        "connectionreseterror",
        "read timed out",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "remote end closed connection",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    )

    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (ConnectionError, TimeoutError)):
            return True
        if isinstance(current, OSError) and getattr(current, "errno", None) in {104, 110, 111}:
            return True
        message = str(current).lower()
        if any(marker in message for marker in transient_text):
            return True
        for nested in (*getattr(current, "args", ()), getattr(current, "__cause__", None), getattr(current, "__context__", None)):
            if isinstance(nested, BaseException):
                stack.append(nested)
    return False


def _query_pro(api_name: str, **params) -> pd.DataFrame:
    client = _get_pro_client()
    clean_params = {key: value for key, value in params.items() if value is not None}
    ticker = clean_params.get("ts_code", "")
    last_exc: Exception | None = None
    attempts_executed = 0
    for attempt in range(1, _TUSHARE_QUERY_MAX_ATTEMPTS + 1):
        try:
            return client.query(api_name, **clean_params)
        except Exception as exc:
            last_exc = exc
            attempts_executed = attempt
            if attempt >= _TUSHARE_QUERY_MAX_ATTEMPTS or not _is_transient_tushare_error(exc):
                break
            delay = _TUSHARE_QUERY_BACKOFF_SECONDS[min(attempt - 1, len(_TUSHARE_QUERY_BACKOFF_SECONDS) - 1)]
            logger.debug(
                "Transient Tushare query '%s' failure for '%s'; retrying in %.1fs (%d/%d): %s",
                api_name,
                ticker or "unknown",
                delay,
                attempt + 1,
                _TUSHARE_QUERY_MAX_ATTEMPTS,
                exc,
            )
            time.sleep(delay)
    if last_exc is not None:
        raise DataVendorUnavailable(
            f"Tushare query '{api_name}' failed for '{ticker or 'unknown'}' after "
            f"{attempts_executed} attempt(s): {last_exc}"
        ) from last_exc
    raise DataVendorUnavailable(
        f"Tushare query '{api_name}' failed for '{ticker or 'unknown'}': unknown error"
    )


def _to_csv_with_header(
    df: pd.DataFrame,
    title: str,
    summary_lines: list[str] | None = None,
) -> str:
    if df is None or df.empty:
        return f"No {title.lower()} data found."

    header = f"# {title}\n"
    header += f"# Total records: {len(df)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    if summary_lines:
        header += "# Key snapshot\n"
        header += "\n".join(summary_lines) + "\n\n"
    return header + df.to_csv(index=False)


def _to_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_billions(value) -> str | None:
    number = _to_float(value)
    if number is None:
        return None
    return f"{number / 1e8:.2f}亿 CNY"


def _format_pct(value) -> str | None:
    number = _to_float(value)
    if number is None:
        return None
    return f"{number:.2f}%"


def _format_multiple(value) -> str | None:
    number = _to_float(value)
    if number is None:
        return None
    return f"{number:.2f}x"


def _format_price(value) -> str | None:
    number = _to_float(value)
    if number is None:
        return None
    return f"{number:.2f} CNY/share"


def _format_market_value_10k_cny(value) -> str | None:
    number = _to_float(value)
    if number is None:
        return None
    return f"{number / 1e4:.2f}亿 CNY"


def _append_if_present(
    lines: list[str],
    label: str,
    value,
    formatter: Callable | None = None,
):
    rendered = formatter(value) if formatter else value
    if rendered is None:
        return
    if not isinstance(rendered, str) and pd.isna(rendered):
        return
    if rendered == "":
        return
    lines.append(f"{label}: {rendered}")


def _clean_scalar_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _portfolio_code_lookup_keys(value) -> set[str]:
    code = _clean_scalar_text(value).upper()
    if not code:
        return set()

    keys = {code}
    if "." in code:
        keys.add(code.split(".", 1)[0])
    elif code.isdigit():
        keys.add(code.zfill(6))

    try:
        normalized = _normalize_ts_code(code)
    except DataVendorUnavailable:
        return keys

    keys.add(normalized)
    if "." in normalized:
        keys.add(normalized.split(".", 1)[0])
    return keys


_stock_basic_name_cache: dict[str, str] | None = None


def _stock_basic_name_lookup() -> dict[str, str]:
    global _stock_basic_name_cache
    if _stock_basic_name_cache is not None:
        return _stock_basic_name_cache

    basics = _query_pro("stock_basic", fields="ts_code,symbol,name")
    if basics.empty:
        return {}

    lookup: dict[str, str] = {}
    for _, row in basics.iterrows():
        name = _clean_scalar_text(row.get("name"))
        if not name:
            continue
        for column in ("ts_code", "symbol"):
            for key in _portfolio_code_lookup_keys(row.get(column)):
                lookup.setdefault(key, name)
    _stock_basic_name_cache = lookup
    return lookup


def _enrich_fund_portfolio_stock_names(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    code_columns = [column for column in ("symbol", "stk_code") if column in df.columns]
    if not code_columns:
        return df

    enriched = df.copy()
    if "stk_name" not in enriched.columns:
        enriched["stk_name"] = ""

    missing_name = enriched["stk_name"].map(_clean_scalar_text).eq("")
    if not missing_name.any():
        return enriched

    try:
        name_lookup = _stock_basic_name_lookup()
    except DataVendorUnavailable as exc:
        logger.debug("Unable to enrich ETF holdings names from stock_basic: %s", exc)
        return enriched

    if not name_lookup:
        return enriched

    for index, row in enriched[missing_name].iterrows():
        for column in code_columns:
            for key in _portfolio_code_lookup_keys(row.get(column)):
                name = name_lookup.get(key)
                if name:
                    enriched.at[index, "stk_name"] = name
                    break
            if _clean_scalar_text(enriched.at[index, "stk_name"]):
                break
    return enriched


def _safe_ratio(numerator, denominator) -> float | None:
    num = _to_float(numerator)
    den = _to_float(denominator)
    if num is None or den is None or den == 0:
        return None
    return num / den


def _same_period_previous_year(df: pd.DataFrame) -> pd.Series | None:
    if df is None or df.empty or "end_date" not in df.columns:
        return None
    latest_end = str(df.iloc[0]["end_date"])
    if len(latest_end) != 8 or not latest_end.isdigit():
        return None
    prior_end = f"{int(latest_end[:4]) - 1}{latest_end[4:]}"
    prior_rows = df[df["end_date"].astype(str) == prior_end]
    if prior_rows.empty:
        return None
    return prior_rows.iloc[0]


def _trim_text(value, max_chars: int = 220) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _prepare_latest_records(
    df: pd.DataFrame,
    cutoff_col: str | None = None,
    cutoff: str | None = None,
    sort_cols: tuple[str, ...] = (),
    dedupe_cols: tuple[str, ...] = (),
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    output = df.copy()
    if cutoff and cutoff_col and cutoff_col in output.columns:
        output = output[output[cutoff_col].astype(str) <= cutoff]
    if output.empty:
        return output

    sort_by: list[str] = []
    ascending: list[bool] = []
    for col in sort_cols:
        if col in output.columns:
            sort_by.append(col)
            ascending.append(False)
    if "update_flag" in output.columns:
        output = output.assign(
            _update_rank=pd.to_numeric(output["update_flag"], errors="coerce").fillna(0)
        )
        sort_by.append("_update_rank")
        ascending.append(False)

    if sort_by:
        output = output.sort_values(sort_by, ascending=ascending)
    else:
        output = output.sort_values(output.columns[0], ascending=False)

    subset = [col for col in dedupe_cols if col in output.columns]
    if subset:
        output = output.drop_duplicates(subset=subset, keep="first")

    if "_update_rank" in output.columns:
        output = output.drop(columns=["_update_rank"])
    return output


def _sort_descending(df: pd.DataFrame, *columns: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    sort_cols = [column for column in columns if column in df.columns]
    if not sort_cols:
        return df
    return df.sort_values(sort_cols, ascending=[False] * len(sort_cols))


def _prepare_etf_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    output = df.copy()
    rename_map = {}
    if "trade_date" in output.columns:
        rename_map["trade_date"] = "Date"
    if "open" in output.columns:
        rename_map["open"] = "Open"
    if "high" in output.columns:
        rename_map["high"] = "High"
    if "low" in output.columns:
        rename_map["low"] = "Low"
    if "close" in output.columns:
        rename_map["close"] = "Close"
    if "vol" in output.columns:
        rename_map["vol"] = "Volume"
    elif "volume" in output.columns:
        rename_map["volume"] = "Volume"

    output = output.rename(columns=rename_map)
    required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
    if any(column not in output.columns for column in required_cols):
        return pd.DataFrame()

    output = output[required_cols].copy()
    output["Date"] = pd.to_datetime(output["Date"], format="%Y%m%d", errors="coerce")
    output = output.dropna(subset=["Date"])
    output = output.sort_values("Date").reset_index(drop=True)
    return output


_ETF_INDICATOR_DESCRIPTIONS = {
    "close_10_ema": "10 EMA for short-term ETF timing.",
    "close_20_sma": "20 SMA for short swing trend confirmation.",
    "close_50_sma": "50 SMA for intermediate ETF trend confirmation.",
    "close_120_sma": "120 SMA for medium-to-long ETF regime assessment.",
    "close_200_sma": "200 SMA for long-term ETF regime assessment.",
    "macd": "MACD line for ETF momentum.",
    "macds": "MACD signal line for ETF momentum.",
    "macdh": "MACD histogram for ETF momentum acceleration or deceleration.",
    "rsi": "RSI for overbought / oversold ETF context.",
    "boll": "Bollinger middle band for ETF mean-reversion / trend context.",
    "boll_ub": "Bollinger upper band for ETF breakout / stretch context.",
    "boll_lb": "Bollinger lower band for ETF breakdown / mean-reversion context.",
    "atr": "ATR for ETF volatility and stop-distance calibration.",
    "vwma": "VWMA for ETF price-volume confirmation.",
}

_ETF_SCOPE_HINTS = {
    "bond": ("债", "国债", "政金债", "信用债", "可转债", "bond"),
    "commodity": ("黄金", "有色", "原油", "商品", "commodity", "gold", "oil"),
    "cross_border": ("qdii", "纳斯达克", "标普", "恒生", "日经", "德国", "法国", "美国", "美股", "港股", "跨境", "海外"),
    "sector_theme": ("医药", "消费", "证券", "银行", "半导体", "芯片", "军工", "人工智能", "新能源", "红利", "科创", "主题", "行业", "sector", "theme"),
}

_ETF_EXPOSURE_HINTS = {
    "broad_market": ("沪深300", "中证500", "中证1000", "创业板", "科创50", "上证50", "broad", "market", "300", "500", "1000"),
    "dividend_value": ("红利", "价值", "央企", "高股息", "dividend", "value"),
    "growth_innovation": ("成长", "科技", "半导体", "芯片", "人工智能", "创新", "科创", "nasdaq", "tech", "ai"),
    "financial_property": ("证券", "银行", "保险", "地产", "financial", "broker"),
    "consumer_healthcare": ("消费", "医药", "医疗", "health", "consumer"),
    "fixed_income": ("债", "bond", "credit", "国债", "政金债"),
    "commodity_real_asset": ("黄金", "有色", "原油", "commodity", "gold", "oil"),
    "cross_border": ("qdii", "海外", "跨境", "美国", "港股", "恒生", "标普", "日经"),
}


def _infer_etf_asset_scope(row: pd.Series) -> str:
    text = " ".join(
        str(row.get(column, "") or "")
        for column in ("name", "benchmark", "fund_type", "invest_type", "market")
    ).lower()
    for scope, hints in _ETF_SCOPE_HINTS.items():
        if any(hint.lower() in text for hint in hints):
            return scope
    return "broad_equity"


def _infer_etf_exposure_bucket(row: pd.Series) -> str:
    text = " ".join(
        str(row.get(column, "") or "")
        for column in ("name", "benchmark", "fund_type", "invest_type", "asset_scope")
    ).lower()
    for bucket, hints in _ETF_EXPOSURE_HINTS.items():
        if any(hint.lower() in text for hint in hints):
            return bucket
    return "broad_market"


def _is_money_market_fund(row: pd.Series) -> bool:
    text = " ".join(
        str(row.get(column, "") or "")
        for column in ("name", "benchmark", "fund_type", "invest_type")
    ).lower()
    return "货币" in text or "money market" in text


def _score_etf_liquidity(avg_amount: float | None) -> int | None:
    if avg_amount is None:
        return None
    if avg_amount >= 1_000_000:
        return 5
    if avg_amount >= 300_000:
        return 4
    if avg_amount >= 80_000:
        return 3
    if avg_amount >= 20_000:
        return 2
    return 1


def _classify_flow_regime(share_change_pct: float | None) -> str | None:
    if share_change_pct is None:
        return None
    if share_change_pct >= 5:
        return "strong_inflow"
    if share_change_pct >= 1:
        return "mild_inflow"
    if share_change_pct <= -5:
        return "strong_outflow"
    if share_change_pct <= -1:
        return "mild_outflow"
    return "stable"


def _classify_aum_bucket(total_netasset: float | None) -> str | None:
    if total_netasset is None:
        return None
    if total_netasset >= 10_000_000_000:
        return "mega"
    if total_netasset >= 3_000_000_000:
        return "large"
    if total_netasset >= 1_000_000_000:
        return "medium"
    if total_netasset >= 300_000_000:
        return "small"
    return "micro"


def _latest_etf_factor_snapshot(ts_code: str, curr_date: str) -> dict[str, object]:
    end_api = _to_api_date(curr_date)
    start_api = (_parse_date(curr_date) - timedelta(days=45)).strftime("%Y%m%d")
    factors: dict[str, object] = {"factor_status": "ok"}

    price_df = _sort_descending(
        _query_pro(
            "fund_daily",
            ts_code=ts_code,
            start_date=start_api,
            end_date=end_api,
        ),
        "trade_date",
    )
    nav_df = _query_pro("fund_nav", ts_code=ts_code)
    share_df = _query_pro("fund_share", ts_code=ts_code)

    if not nav_df.empty:
        nav_date_col = "nav_date" if "nav_date" in nav_df.columns else "end_date"
        if nav_date_col in nav_df.columns:
            nav_df = nav_df[nav_df[nav_date_col].astype(str) <= end_api]
        nav_df = _sort_descending(nav_df, "end_date", "nav_date")

    if not share_df.empty and "end_date" in share_df.columns:
        share_df = share_df[share_df["end_date"].astype(str) <= end_api]
        share_df = _sort_descending(share_df, "end_date")

    if not price_df.empty:
        latest_price = price_df.iloc[0]
        avg_amount_20d = _to_float(price_df.head(20)["amount"].mean()) if "amount" in price_df.columns else None
        avg_volume_20d = _to_float(price_df.head(20)["vol"].mean()) if "vol" in price_df.columns else None
        factors["latest_trade_date"] = latest_price.get("trade_date")
        factors["latest_close"] = _to_float(latest_price.get("close"))
        factors["avg_amount_20d"] = avg_amount_20d
        factors["avg_volume_20d"] = avg_volume_20d
        factors["liquidity_score"] = _score_etf_liquidity(avg_amount_20d)

    if not nav_df.empty:
        latest_nav = nav_df.iloc[0]
        nav_date_col = "nav_date" if "nav_date" in nav_df.columns else "end_date"
        factors["latest_nav_date"] = latest_nav.get(nav_date_col)
        factors["unit_nav"] = _to_float(latest_nav.get("unit_nav"))
        factors["total_netasset"] = _to_float(latest_nav.get("total_netasset"))
        factors["aum_bucket"] = _classify_aum_bucket(factors["total_netasset"])

    if not price_df.empty and not nav_df.empty:
        nav_date_col = "nav_date" if "nav_date" in nav_df.columns else "end_date"
        price_history = price_df[["trade_date", "close"]].copy()
        price_history["trade_date"] = pd.to_datetime(
            price_history["trade_date"].astype(str),
            format="%Y%m%d",
            errors="coerce",
        )
        price_history["close"] = pd.to_numeric(price_history["close"], errors="coerce")
        nav_history = nav_df[[nav_date_col, "unit_nav"]].copy()
        nav_history["nav_ref_date"] = pd.to_datetime(
            nav_history[nav_date_col].astype(str),
            format="%Y%m%d",
            errors="coerce",
        )
        nav_history["unit_nav"] = pd.to_numeric(nav_history["unit_nav"], errors="coerce")
        price_history = price_history.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
        nav_history = nav_history.dropna(subset=["nav_ref_date", "unit_nav"]).sort_values("nav_ref_date")

        if not price_history.empty and not nav_history.empty:
            premium_df = pd.merge_asof(
                price_history,
                nav_history[["nav_ref_date", "unit_nav"]],
                left_on="trade_date",
                right_on="nav_ref_date",
                direction="backward",
                tolerance=pd.Timedelta(days=7),
            )
            premium_df = premium_df.dropna(subset=["unit_nav"])
            if not premium_df.empty:
                premium_df["premium_discount_bps"] = (
                    (premium_df["close"] - premium_df["unit_nav"])
                    / premium_df["unit_nav"]
                    * 10000
                )
                latest_premium = premium_df.iloc[-1]["premium_discount_bps"]
                premium_vol = premium_df.tail(20)["premium_discount_bps"].std()
                factors["premium_discount_bps"] = round(float(latest_premium), 2)
                factors["premium_discount_volatility_bps_20d"] = round(float(premium_vol), 2) if pd.notna(premium_vol) else None

    share_col = "fd_share" if "fd_share" in share_df.columns else "fund_share" if "fund_share" in share_df.columns else None
    if share_col and not share_df.empty:
        share_history = share_df[["end_date", share_col]].copy()
        share_history[share_col] = pd.to_numeric(share_history[share_col], errors="coerce")
        share_history = share_history.dropna(subset=[share_col]).sort_values("end_date")
        if not share_history.empty:
            latest_share = _to_float(share_history.iloc[-1][share_col])
            prior_share = _to_float(share_history.iloc[-2][share_col]) if len(share_history) >= 2 else None
            share_change_pct = (
                (latest_share - prior_share) / prior_share * 100
                if latest_share is not None and prior_share not in (None, 0)
                else None
            )
            factors["latest_fund_share"] = latest_share
            factors["share_change_pct"] = round(float(share_change_pct), 2) if share_change_pct is not None else None
            factors["flow_regime"] = _classify_flow_regime(share_change_pct)

    return factors


def _enrich_etf_universe_snapshot(df: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    enriched = df.copy()
    enriched["exposure_bucket"] = enriched.apply(_infer_etf_exposure_bucket, axis=1)
    max_enriched = max(0, int(_ETF_UNIVERSE_MAX_ENRICHED_ROWS))
    for row_position, (index, row) in enumerate(enriched.iterrows()):
        ts_code = row.get("ts_code")
        if row_position >= max_enriched:
            enriched.at[index, "factor_status"] = (
                f"not_enriched; enrichment_cap={max_enriched}"
            )
            continue
        cache_key = (str(ts_code), curr_date)
        factor_snapshot = _etf_factor_snapshot_cache.get(cache_key)
        if factor_snapshot is None:
            try:
                factor_snapshot = _latest_etf_factor_snapshot(str(ts_code), curr_date)
            except Exception as exc:
                factor_snapshot = {"factor_status": f"error: {exc}"}
            _etf_factor_snapshot_cache[cache_key] = dict(factor_snapshot)
        for key, value in factor_snapshot.items():
            enriched.at[index, key] = value
    return enriched


def _get_etf_fund_basic_snapshot() -> pd.DataFrame:
    global _etf_fund_basic_cache
    now = time.time()
    if _etf_fund_basic_cache is not None:
        cached_at, cached_df = _etf_fund_basic_cache
        if now - cached_at <= _ETF_UNIVERSE_FUND_BASIC_CACHE_TTL_SECONDS:
            return cached_df.copy()

    df = _query_pro("fund_basic")
    _etf_fund_basic_cache = (now, df.copy())
    return df


def get_etf_daily(symbol: str, start_date: str, end_date: str) -> str:
    ts_code = _normalize_ts_code(symbol)
    df = _query_pro(
        "fund_daily",
        ts_code=ts_code,
        start_date=_to_api_date(start_date),
        end_date=_to_api_date(end_date),
    )
    df = _sort_descending(df, "trade_date")
    if df.empty:
        return f"No ETF price data found for '{ts_code}' between {start_date} and {end_date}."

    snapshot = df.iloc[0]
    summary_lines: list[str] = []
    _append_if_present(summary_lines, "Ticker", ts_code)
    _append_if_present(summary_lines, "Trade Date", snapshot.get("trade_date"))
    _append_if_present(summary_lines, "Close", snapshot.get("close"))
    _append_if_present(summary_lines, "Pct Change", snapshot.get("pct_chg"), _format_pct)
    _append_if_present(summary_lines, "Volume", snapshot.get("vol"))
    _append_if_present(summary_lines, "Amount", snapshot.get("amount"))

    display = df.sort_values("trade_date").reset_index(drop=True)
    return _to_csv_with_header(display, f"ETF price data for {ts_code}", summary_lines)


def get_etf_indicator(symbol: str, indicator: str, curr_date: str, look_back_days: int) -> str:
    if indicator not in _ETF_INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"ETF indicator '{indicator}' is not supported. Choose from {sorted(_ETF_INDICATOR_DESCRIPTIONS)}."
        )

    end_dt = _parse_date(curr_date)
    start_dt = end_dt - timedelta(days=max(look_back_days * 3, 260))
    raw = _query_pro(
        "fund_daily",
        ts_code=_normalize_ts_code(symbol),
        start_date=start_dt.strftime("%Y%m%d"),
        end_date=end_dt.strftime("%Y%m%d"),
    )
    prepared = _prepare_etf_ohlcv(raw)
    if prepared.empty:
        return f"No ETF OHLCV data found to calculate '{indicator}' for '{symbol}'."

    df = wrap(prepared.copy())
    df["Date"] = pd.to_datetime(df["Date"])
    df[indicator]
    window_start = end_dt - timedelta(days=look_back_days)
    rows = df[(df["Date"] >= window_start) & (df["Date"] <= end_dt)].copy()
    if rows.empty:
        return f"No ETF indicator window available for '{symbol}' and indicator '{indicator}'."

    lines = []
    for _, row in rows.iterrows():
        value = row[indicator]
        rendered = "N/A" if pd.isna(value) else value
        lines.append(f"{row['Date'].strftime('%Y-%m-%d')}: {rendered}")

    return (
        f"## {indicator} values from {window_start.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        + "\n".join(lines)
        + "\n\n"
        + _ETF_INDICATOR_DESCRIPTIONS[indicator]
    )


def get_etf_info(ticker: str, curr_date: str | None = None) -> str:
    ts_code = _normalize_ts_code(ticker)
    df = _query_pro("fund_basic", ts_code=ts_code)
    if df.empty:
        return f"No ETF profile data found for '{ts_code}'."

    snapshot = df.iloc[0]
    summary_lines: list[str] = []
    for label, column in (
        ("Ticker", "ts_code"),
        ("Name", "name"),
        ("Market", "market"),
        ("Fund Type", "fund_type"),
        ("Benchmark", "benchmark"),
        ("Management", "management"),
        ("Custodian", "custodian"),
        ("Issue Date", "found_date"),
        ("List Date", "list_date"),
        ("Management Fee", "m_fee"),
        ("Custody Fee", "c_fee"),
    ):
        _append_if_present(summary_lines, label, snapshot.get(column))

    return _to_csv_with_header(df.reset_index(drop=True), f"ETF profile for {ts_code}", summary_lines)


def get_etf_nav(ticker: str, curr_date: str) -> str:
    ts_code = _normalize_ts_code(ticker)
    df = _query_pro("fund_nav", ts_code=ts_code)
    if "end_date" in df.columns:
        df = df[df["end_date"].astype(str) <= _to_api_date(curr_date)]
    elif "nav_date" in df.columns:
        df = df[df["nav_date"].astype(str) <= _to_api_date(curr_date)]
    df = _sort_descending(df, "end_date", "nav_date")
    if df.empty:
        return f"No ETF NAV data found for '{ts_code}' up to {curr_date}."

    snapshot = df.iloc[0]
    summary_lines: list[str] = []
    for label, column in (
        ("Ticker", "ts_code"),
        ("End Date", "end_date"),
        ("NAV Date", "nav_date"),
        ("Unit NAV", "unit_nav"),
        ("Accum NAV", "accum_nav"),
        ("Adjusted NAV", "adj_nav"),
        ("Net Asset", "net_asset"),
        ("Total Net Asset", "total_netasset"),
    ):
        _append_if_present(summary_lines, label, snapshot.get(column))

    return _to_csv_with_header(df.head(20).reset_index(drop=True), f"ETF NAV for {ts_code}", summary_lines)


def get_etf_holdings(ticker: str, curr_date: str) -> str:
    ts_code = _normalize_ts_code(ticker)
    df = _query_pro("fund_portfolio", ts_code=ts_code)
    if "end_date" in df.columns:
        df = df[df["end_date"].astype(str) <= _to_api_date(curr_date)]
    df = _sort_descending(df, "end_date", "ann_date", "stk_mkv_ratio")
    if df.empty:
        raise MissingEtfHoldings(f"No ETF holdings data found for '{ts_code}' up to {curr_date}.")

    df = _enrich_fund_portfolio_stock_names(df)

    summary_lines: list[str] = []
    latest = df.iloc[0]
    _append_if_present(summary_lines, "Ticker", latest.get("ts_code"))
    _append_if_present(summary_lines, "Disclosure Date", latest.get("ann_date"))
    _append_if_present(summary_lines, "Report Date", latest.get("end_date"))
    _append_if_present(summary_lines, "Top Holding", latest.get("symbol") or latest.get("stk_code"))
    _append_if_present(summary_lines, "Top Holding Weight", latest.get("stk_mkv_ratio"), _format_pct)

    return _to_csv_with_header(df.head(20).reset_index(drop=True), f"ETF holdings for {ts_code}", summary_lines)


def get_etf_share(ticker: str, curr_date: str) -> str:
    ts_code = _normalize_ts_code(ticker)
    df = _query_pro("fund_share", ts_code=ts_code)
    if "end_date" in df.columns:
        df = df[df["end_date"].astype(str) <= _to_api_date(curr_date)]
    df = _sort_descending(df, "end_date")
    if df.empty:
        return f"No ETF share-change data found for '{ts_code}' up to {curr_date}."

    snapshot = df.iloc[0]
    summary_lines: list[str] = []
    _append_if_present(summary_lines, "Ticker", snapshot.get("ts_code"))
    _append_if_present(summary_lines, "End Date", snapshot.get("end_date"))
    _append_if_present(summary_lines, "Fund Share", snapshot.get("fd_share") or snapshot.get("fund_share"))
    return _to_csv_with_header(df.head(12).reset_index(drop=True), f"ETF share changes for {ts_code}", summary_lines)


def get_etf_universe(
    curr_date: str | None = None,
    market: str | None = None,
    asset_scope: str | None = None,
    limit: int = 50,
) -> str:
    df = _get_etf_fund_basic_snapshot()
    if df.empty:
        return "No ETF universe data found."

    output = df.copy()
    if curr_date and "list_date" in output.columns:
        output = output[
            output["list_date"].astype(str).fillna("") <= _to_api_date(curr_date)
        ]
    if "ts_code" in output.columns:
        output = output[
            ~output["ts_code"].astype(str).str.upper().str.endswith(".OF")
        ]
    output = output[~output.apply(_is_money_market_fund, axis=1)]

    normalized_market = (market or "E").strip().upper()
    if normalized_market and normalized_market != "ALL" and "market" in output.columns:
        output = output[output["market"].astype(str).str.upper() == normalized_market]

    output["asset_scope"] = output.apply(_infer_etf_asset_scope, axis=1)
    normalized_scope = (asset_scope or "").strip().lower()
    if normalized_scope and normalized_scope != "all":
        output = output[output["asset_scope"] == normalized_scope]

    if output.empty:
        scope_label = normalized_scope or "all"
        market_label = market or "E"
        return f"No ETF universe entries found for market={market_label} scope={scope_label}."

    if "list_date" in output.columns:
        output = output.sort_values("list_date", ascending=False)

    limited = output.head(max(1, int(limit))).reset_index(drop=True)
    reference_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    limited = _enrich_etf_universe_snapshot(limited, reference_date)
    enriched_rows = min(len(limited), max(0, int(_ETF_UNIVERSE_MAX_ENRICHED_ROWS)))
    summary_lines = [
        f"Universe size after filters: {len(output)}",
        f"Returned rows: {len(limited)}",
        f"Enriched rows: {enriched_rows} of {len(limited)}",
        "Rows beyond the enrichment cap keep basic ETF metadata and factor_status=not_enriched.",
        "latest_close comes from Tushare fund_daily and reflects the latest available daily close, not an intraday real-time quote.",
    ]
    if market:
        summary_lines.append(f"Market filter: {market.upper()}")
    else:
        summary_lines.append("Market filter: E (default exchange-traded ETF universe)")
    if normalized_scope:
        summary_lines.append(f"Asset scope: {normalized_scope}")

    scope_counts = (
        output["asset_scope"].value_counts().sort_index().to_dict()
        if "asset_scope" in output.columns
        else {}
    )
    for scope_name, count in scope_counts.items():
        summary_lines.append(f"{scope_name}: {count}")

    keep_columns = [
        column
        for column in (
            "ts_code",
            "name",
            "market",
            "fund_type",
            "invest_type",
            "benchmark",
            "list_date",
            "management",
            "asset_scope",
            "exposure_bucket",
            "latest_trade_date",
            "latest_close",
            "avg_amount_20d",
            "avg_volume_20d",
            "liquidity_score",
            "unit_nav",
            "premium_discount_bps",
            "premium_discount_volatility_bps_20d",
            "total_netasset",
            "aum_bucket",
            "latest_fund_share",
            "share_change_pct",
            "flow_regime",
            "factor_status",
        )
        if column in limited.columns
    ]
    return _to_csv_with_header(
        limited[keep_columns] if keep_columns else limited,
        "ETF universe snapshot",
        summary_lines,
    )


def _build_growth_and_valuation_snapshot(
    latest_price_row: pd.Series | None,
    fina_indicator_row: pd.Series | None,
) -> list[str]:
    if fina_indicator_row is None:
        return []

    lines: list[str] = []
    growth_specs = {
        "Revenue YoY": "or_yoy",
        "Net Profit YoY": "netprofit_yoy",
        "Deducted Net Profit YoY": "dt_netprofit_yoy",
        "Quarterly Revenue YoY": "q_sales_yoy",
        "Quarterly Operating Profit QoQ": "q_op_qoq",
    }
    for label, field in growth_specs.items():
        _append_if_present(lines, label, fina_indicator_row.get(field), _format_pct)

    pe_value = _to_float(latest_price_row.get("pe")) if latest_price_row is not None else None
    if pe_value is not None and pe_value > 0:
        for label, field in (
            ("Net Profit YoY", "netprofit_yoy"),
            ("Deducted Net Profit YoY", "dt_netprofit_yoy"),
            ("Revenue YoY", "or_yoy"),
        ):
            growth_value = _to_float(fina_indicator_row.get(field))
            if growth_value is not None and growth_value > 0:
                lines.append(f"PEG (using {label}): {pe_value / growth_value:.2f}x")
                break
    return lines


def _build_rd_snapshot(income_df: pd.DataFrame) -> list[str]:
    if income_df is None or income_df.empty:
        return []

    row = income_df.iloc[0]
    lines: list[str] = []
    _append_if_present(lines, "Latest Report Date", row.get("end_date"))
    _append_if_present(lines, "R&D Expense", row.get("rd_exp"), _format_billions)

    rd_exp = _to_float(row.get("rd_exp"))
    total_revenue = _to_float(row.get("total_revenue"))
    if rd_exp is not None and total_revenue not in (None, 0):
        lines.append(f"R&D Intensity: {rd_exp / total_revenue * 100:.2f}%")

    operate_profit = _to_float(row.get("operate_profit"))
    if rd_exp is not None and operate_profit not in (None, 0):
        lines.append(f"R&D / Operating Profit: {rd_exp / operate_profit * 100:.2f}%")

    prior_row = _same_period_previous_year(income_df)
    if prior_row is not None:
        prior_rd_exp = _to_float(prior_row.get("rd_exp"))
        if rd_exp is not None and prior_rd_exp not in (None, 0):
            lines.append(
                f"R&D Expense YoY (same period): {(rd_exp - prior_rd_exp) / prior_rd_exp * 100:.2f}%"
            )
    return lines


def _build_main_business_snapshot(
    company_df: pd.DataFrame | None,
    main_business_df: pd.DataFrame | None,
    end_api: str,
) -> list[str]:
    lines: list[str] = []

    if company_df is not None and not company_df.empty:
        row = company_df.iloc[0]
        _append_if_present(lines, "Main Business Summary", _trim_text(row.get("main_business"), 320))
        _append_if_present(lines, "Business Scope", _trim_text(row.get("business_scope"), 260))

    prepared = _prepare_latest_records(
        main_business_df,
        cutoff_col="end_date",
        cutoff=end_api,
        sort_cols=("end_date",),
        dedupe_cols=("end_date", "bz_item"),
    )
    if prepared.empty:
        return lines

    latest_end = str(prepared.iloc[0]["end_date"])
    latest = prepared[prepared["end_date"].astype(str) == latest_end].copy()
    if latest.empty or "bz_sales" not in latest.columns:
        return lines

    latest = latest[latest["bz_sales"].notna()].sort_values("bz_sales", ascending=False)
    if latest.empty:
        return lines

    disclosed_sales = pd.to_numeric(latest["bz_sales"], errors="coerce").fillna(0).sum()
    lines.append(f"Latest Segment Period: {latest_end}")
    for _, segment in latest.head(3).iterrows():
        pieces = [f"Segment: {segment.get('bz_item')}"]
        sales_value = _to_float(segment.get("bz_sales"))
        sales_text = _format_billions(sales_value)
        if sales_text is not None:
            pieces.append(f"Sales: {sales_text}")
        if sales_value is not None and disclosed_sales > 0:
            pieces.append(
                f"Share of disclosed segment sales: {sales_value / disclosed_sales * 100:.2f}%"
            )
        segment_margin = _safe_ratio(segment.get("bz_profit"), segment.get("bz_sales"))
        if segment_margin is not None:
            pieces.append(f"Segment Margin: {segment_margin * 100:.2f}%")
        lines.append(" | ".join(pieces))
    return lines


def _build_earnings_guidance_snapshot(
    forecast_df: pd.DataFrame | None,
    express_df: pd.DataFrame | None,
    end_api: str,
    latest_actual_end: str | None,
    total_market_value_10k: float | None,
) -> list[str]:
    lines: list[str] = []

    prepared_forecast = _prepare_latest_records(
        forecast_df,
        cutoff_col="ann_date",
        cutoff=end_api,
        sort_cols=("ann_date", "end_date", "first_ann_date"),
        dedupe_cols=("end_date",),
    )
    if not prepared_forecast.empty:
        row = prepared_forecast.iloc[0]
        _append_if_present(lines, "Latest Forecast Announcement Date", row.get("ann_date"))
        _append_if_present(lines, "Latest Forecast Period", row.get("end_date"))
        _append_if_present(lines, "Forecast Net Profit Min", row.get("net_profit_min"), _format_market_value_10k_cny)
        _append_if_present(lines, "Forecast Net Profit Max", row.get("net_profit_max"), _format_market_value_10k_cny)
        _append_if_present(lines, "Forecast Change Min", row.get("p_change_min"), _format_pct)
        _append_if_present(lines, "Forecast Change Max", row.get("p_change_max"), _format_pct)
        _append_if_present(lines, "Forecast Summary", _trim_text(row.get("summary"), 180))
        _append_if_present(lines, "Forecast Reason", _trim_text(row.get("change_reason"), 260))

        forecast_period = str(row.get("end_date")) if pd.notna(row.get("end_date")) else None
        forecast_min = _to_float(row.get("net_profit_min"))
        forecast_max = _to_float(row.get("net_profit_max"))
        forecast_midpoint = None
        if forecast_min is not None and forecast_max is not None:
            forecast_midpoint = (forecast_min + forecast_max) / 2
        elif forecast_min is not None:
            forecast_midpoint = forecast_min
        elif forecast_max is not None:
            forecast_midpoint = forecast_max

        if latest_actual_end and forecast_period and forecast_period > latest_actual_end:
            _append_if_present(
                lines,
                "Forecast Net Profit Midpoint",
                forecast_midpoint,
                _format_market_value_10k_cny,
            )
            if (
                total_market_value_10k is not None
                and total_market_value_10k > 0
                and forecast_midpoint is not None
                and forecast_midpoint > 0
            ):
                lines.append(
                    "Forward PE (market cap / forecast net profit midpoint): "
                    f"{total_market_value_10k / forecast_midpoint:.2f}x"
                )
        elif latest_actual_end:
            lines.append(
                "Forward PE Status: Latest available forecast is not newer than "
                f"the latest reported financial period {latest_actual_end}."
            )
        return lines

    prepared_express = _prepare_latest_records(
        express_df,
        cutoff_col="ann_date",
        cutoff=end_api,
        sort_cols=("ann_date", "end_date"),
        dedupe_cols=("end_date",),
    )
    if not prepared_express.empty:
        row = prepared_express.iloc[0]
        _append_if_present(lines, "Latest Earnings Express Period", row.get("end_date"))
        _append_if_present(lines, "Earnings Express Revenue", row.get("revenue"), _format_billions)
        _append_if_present(lines, "Earnings Express Net Income", row.get("n_income"), _format_billions)
        _append_if_present(lines, "Earnings Express Summary", _trim_text(row.get("perf_summary"), 180))

    if latest_actual_end:
        lines.append(
            "Forward PE Status: No current earnings guidance newer than "
            f"the latest reported financial period {latest_actual_end} was found."
        )
    return lines


def _extract_peer_keywords(company_df: pd.DataFrame | None) -> list[str]:
    if company_df is None or company_df.empty:
        return []
    row = company_df.iloc[0]
    text = " ".join(
        filter(
            None,
            [
                _trim_text(row.get("main_business"), 600),
                _trim_text(row.get("business_scope"), 600),
                _trim_text(row.get("introduction"), 600),
            ],
        )
    )
    if not text:
        return []

    strong_keywords = (
        "动力电池",
        "锂电池",
        "电池系统",
        "电池材料",
        "电池回收",
        "磷酸铁锂",
        "三元材料",
    )
    broad_keywords = ("储能",)

    matched_strong_keywords = [keyword for keyword in strong_keywords if keyword in text]
    if matched_strong_keywords:
        return matched_strong_keywords[:4]
    return [keyword for keyword in broad_keywords if keyword in text][:2]


def _load_keyword_peer_candidates(pro, keywords: list[str]) -> pd.DataFrame:
    if not keywords:
        return pd.DataFrame()

    company_frames = [
        pro.stock_company(exchange="SSE"),
        pro.stock_company(exchange="SZSE"),
        pro.stock_company(exchange="BSE"),
    ]
    companies = pd.concat(company_frames, ignore_index=True)
    business_text = (
        companies.get("main_business", pd.Series(dtype=object)).fillna("")
        + " "
        + companies.get("business_scope", pd.Series(dtype=object)).fillna("")
    )
    keyword_pattern = "|".join(re.escape(keyword) for keyword in keywords)
    matches = companies[business_text.str.contains(keyword_pattern, regex=True)]
    if matches.empty:
        return matches
    return matches[["ts_code"]].drop_duplicates()


def _build_peer_comparison_snapshot(
    pro,
    ts_code: str,
    industry: str | None,
    latest_trade_date: str | None,
    latest_price_row: pd.Series | None,
    fina_indicator_row: pd.Series | None,
    start_api_400d: str,
    end_api: str,
    company_df: pd.DataFrame | None = None,
) -> list[str]:
    if industry is None or pd.isna(industry) or latest_trade_date is None or pd.isna(latest_trade_date):
        return []

    peer_universe = pro.stock_basic(fields="ts_code,name,industry,market,list_status")
    if peer_universe is None or peer_universe.empty:
        return []

    peers = peer_universe[
        (peer_universe["industry"] == industry)
        & (peer_universe["list_status"] == "L")
        & (peer_universe["ts_code"] != ts_code)
    ]
    if peers.empty:
        return []

    peer_basis = f"same Tushare industry '{industry}'"
    keyword_candidates = _load_keyword_peer_candidates(pro, _extract_peer_keywords(company_df))
    if not keyword_candidates.empty:
        keyword_peers = peers.merge(keyword_candidates, on="ts_code", how="inner")
        if len(keyword_peers) >= 3:
            peers = keyword_peers
            keywords_display = ", ".join(_extract_peer_keywords(company_df))
            peer_basis = (
                f"same Tushare industry '{industry}' and business keywords [{keywords_display}]"
            )

    peer_valuation = pro.daily_basic(
        trade_date=latest_trade_date,
        fields="ts_code,close,pe,pb,ps,total_mv",
    )
    if peer_valuation is None or peer_valuation.empty:
        return []

    merged = peers.merge(peer_valuation, on="ts_code", how="inner")
    merged = merged[merged["total_mv"].notna()].sort_values("total_mv", ascending=False)
    sample = merged.head(3)
    if sample.empty:
        return []

    lines = [
        "Peer Sample Basis: "
        f"{peer_basis}, ranked by market value on {latest_trade_date}."
    ]
    peer_metrics: list[dict[str, float]] = []

    for _, peer in sample.iterrows():
        peer_indicator = _prepare_latest_records(
            pro.fina_indicator(ts_code=peer["ts_code"], start_date=start_api_400d, end_date=end_api),
            cutoff_col="end_date",
            cutoff=end_api,
            sort_cols=("end_date", "ann_date"),
            dedupe_cols=("end_date",),
        )
        peer_indicator_row = peer_indicator.iloc[0] if not peer_indicator.empty else None

        pieces = [f"{peer.get('name')} ({peer.get('ts_code')})"]
        _append_if_present(pieces, "Market Value", peer.get("total_mv"), _format_market_value_10k_cny)
        _append_if_present(pieces, "PE", peer.get("pe"), _format_multiple)
        _append_if_present(pieces, "PB", peer.get("pb"), _format_multiple)
        _append_if_present(pieces, "PS", peer.get("ps"), _format_multiple)
        if peer_indicator_row is not None:
            _append_if_present(pieces, "ROE", peer_indicator_row.get("roe"), _format_pct)
            _append_if_present(
                pieces,
                "Net Profit YoY",
                peer_indicator_row.get("netprofit_yoy"),
                _format_pct,
            )
        lines.append("Peer Sample: " + " | ".join(pieces))

        peer_metrics.append(
            {
                "pe": _to_float(peer.get("pe")),
                "pb": _to_float(peer.get("pb")),
                "ps": _to_float(peer.get("ps")),
                "roe": _to_float(peer_indicator_row.get("roe")) if peer_indicator_row is not None else None,
                "netprofit_yoy": (
                    _to_float(peer_indicator_row.get("netprofit_yoy"))
                    if peer_indicator_row is not None
                    else None
                ),
            }
        )

    comparisons: list[str] = []
    target_metric_map = {
        "PE": _to_float(latest_price_row.get("pe")) if latest_price_row is not None else None,
        "PB": _to_float(latest_price_row.get("pb")) if latest_price_row is not None else None,
        "PS": _to_float(latest_price_row.get("ps")) if latest_price_row is not None else None,
        "ROE": _to_float(fina_indicator_row.get("roe")) if fina_indicator_row is not None else None,
        "Net Profit YoY": (
            _to_float(fina_indicator_row.get("netprofit_yoy"))
            if fina_indicator_row is not None
            else None
        ),
    }
    peer_metric_map = {
        "PE": "pe",
        "PB": "pb",
        "PS": "ps",
        "ROE": "roe",
        "Net Profit YoY": "netprofit_yoy",
    }
    for label, metric_key in peer_metric_map.items():
        values = [item[metric_key] for item in peer_metrics if item.get(metric_key) is not None]
        target_value = target_metric_map[label]
        if not values or target_value is None:
            continue
        median_value = float(pd.Series(values).median())
        suffix = "%" if "YoY" in label or label == "ROE" else "x"
        comparisons.append(
            f"{label}: target {target_value:.2f}{suffix} vs sample median {median_value:.2f}{suffix}"
        )
    if comparisons:
        lines.append("Target vs Peer Median: " + " | ".join(comparisons))

    return lines


def _build_balance_sheet_summary(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []
    row = df.iloc[0]
    lines: list[str] = []
    _append_if_present(lines, "Latest Report Date", row.get("end_date"))
    _append_if_present(lines, "Total Assets", row.get("total_assets"), _format_billions)
    _append_if_present(lines, "Total Liabilities", row.get("total_liab"), _format_billions)
    _append_if_present(
        lines,
        "Equity Attributable to Shareholders",
        row.get("total_hldr_eqy_exc_min_int"),
        _format_billions,
    )
    debt_ratio = _safe_ratio(row.get("total_liab"), row.get("total_assets"))
    if debt_ratio is not None:
        lines.append(f"Asset-Liability Ratio: {debt_ratio * 100:.2f}%")
    _append_if_present(
        lines,
        "Current Assets",
        row.get("total_cur_assets"),
        _format_billions,
    )
    _append_if_present(
        lines,
        "Current Liabilities",
        row.get("total_cur_liab"),
        _format_billions,
    )
    current_ratio = _safe_ratio(row.get("total_cur_assets"), row.get("total_cur_liab"))
    if current_ratio is not None:
        lines.append(f"Current Ratio: {current_ratio:.2f}x")
    _append_if_present(lines, "Cash", row.get("money_cap"), _format_billions)
    _append_if_present(
        lines,
        "Accounts Receivable",
        row.get("accounts_receiv"),
        _format_billions,
    )
    _append_if_present(lines, "Inventories", row.get("inventories"), _format_billions)
    _append_if_present(
        lines,
        "Contract Liabilities",
        row.get("contract_liab"),
        _format_billions,
    )
    return lines


def _build_cashflow_summary(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []
    row = df.iloc[0]
    lines: list[str] = []
    _append_if_present(lines, "Latest Report Date", row.get("end_date"))
    _append_if_present(
        lines,
        "Operating Cash Flow",
        row.get("n_cashflow_act"),
        _format_billions,
    )
    _append_if_present(
        lines,
        "Investing Cash Flow",
        row.get("n_cashflow_inv_act"),
        _format_billions,
    )
    _append_if_present(
        lines,
        "Financing Cash Flow",
        row.get("n_cash_flows_fnc_act"),
        _format_billions,
    )
    free_cashflow = row.get("free_cashflow")
    if _to_float(free_cashflow) is None:
        operating_cash_flow = _to_float(row.get("n_cashflow_act"))
        capex_cash = _to_float(row.get("c_pay_acq_const_fiolta"))
        if operating_cash_flow is not None and capex_cash is not None:
            free_cashflow = operating_cash_flow - capex_cash
    _append_if_present(lines, "Free Cash Flow", free_cashflow, _format_billions)
    _append_if_present(
        lines,
        "Ending Cash and Cash Equivalents",
        row.get("c_cash_equ_end_period"),
        _format_billions,
    )
    _append_if_present(
        lines,
        "Beginning Cash and Cash Equivalents",
        row.get("c_cash_equ_beg_period"),
        _format_billions,
    )
    _append_if_present(
        lines,
        "Cash Received from Sales",
        row.get("c_fr_sale_sg"),
        _format_billions,
    )
    _append_if_present(
        lines,
        "Cash Paid for Goods and Services",
        row.get("c_paid_goods_s"),
        _format_billions,
    )
    _append_if_present(
        lines,
        "Capex Cash Outflow",
        row.get("c_pay_acq_const_fiolta"),
        _format_billions,
    )
    return lines


def _build_income_statement_summary(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []
    row = df.iloc[0]
    lines: list[str] = []
    _append_if_present(lines, "Latest Report Date", row.get("end_date"))
    _append_if_present(lines, "Total Revenue", row.get("total_revenue"), _format_billions)
    _append_if_present(
        lines,
        "Operating Profit",
        row.get("operate_profit"),
        _format_billions,
    )
    _append_if_present(lines, "Total Profit", row.get("total_profit"), _format_billions)
    _append_if_present(lines, "Net Income", row.get("n_income"), _format_billions)
    _append_if_present(
        lines,
        "Parent Net Income",
        row.get("n_income_attr_p"),
        _format_billions,
    )
    _append_if_present(lines, "R&D Expense", row.get("rd_exp"), _format_billions)
    _append_if_present(lines, "EBIT", row.get("ebit"), _format_billions)
    _append_if_present(lines, "EBITDA", row.get("ebitda"), _format_billions)
    rd_exp = _to_float(row.get("rd_exp"))
    total_revenue = _to_float(row.get("total_revenue"))
    if rd_exp is not None and total_revenue not in (None, 0):
        lines.append(f"R&D Intensity: {rd_exp / total_revenue * 100:.2f}%")
    operate_profit = _to_float(row.get("operate_profit"))
    if rd_exp is not None and operate_profit not in (None, 0):
        lines.append(f"R&D / Operating Profit: {rd_exp / operate_profit * 100:.2f}%")

    prior_row = _same_period_previous_year(df)
    if prior_row is not None:
        current_revenue = _to_float(row.get("total_revenue"))
        prior_revenue = _to_float(prior_row.get("total_revenue"))
        revenue_growth = None
        if current_revenue is not None and prior_revenue not in (None, 0):
            revenue_growth = (current_revenue - prior_revenue) / prior_revenue
        if revenue_growth is not None:
            lines.append(f"Revenue YoY (same period): {revenue_growth * 100:.2f}%")
        current_profit = _to_float(row.get("n_income_attr_p"))
        prior_profit = _to_float(prior_row.get("n_income_attr_p"))
        profit_growth = None
        if current_profit is not None and prior_profit not in (None, 0):
            profit_growth = (current_profit - prior_profit) / prior_profit
        if profit_growth is not None:
            lines.append(f"Parent Net Income YoY (same period): {profit_growth * 100:.2f}%")
        prior_rd_exp = _to_float(prior_row.get("rd_exp"))
        if rd_exp is not None and prior_rd_exp not in (None, 0):
            lines.append(f"R&D Expense YoY (same period): {(rd_exp - prior_rd_exp) / prior_rd_exp * 100:.2f}%")
    return lines


def _filter_statement(df: pd.DataFrame, freq: str, curr_date: str | None) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    output = df.copy()

    if curr_date and "end_date" in output.columns:
        cutoff = _to_api_date(curr_date)
        output = output[output["end_date"].astype(str) <= cutoff]

    if freq.lower() == "annual" and "end_date" in output.columns:
        output = output[output["end_date"].astype(str).str.endswith("1231")]

    sort_cols = []
    ascending = []
    if "end_date" in output.columns:
        sort_cols.append("end_date")
        ascending.append(False)
    if "update_flag" in output.columns:
        output = output.assign(
            _update_rank=pd.to_numeric(output["update_flag"], errors="coerce").fillna(0)
        )
        sort_cols.append("_update_rank")
        ascending.append(False)
    for col in ("ann_date", "f_ann_date"):
        if col in output.columns:
            sort_cols.append(col)
            ascending.append(False)

    sort_col = sort_cols[0] if sort_cols else output.columns[0]
    output = output.sort_values(sort_cols or sort_col, ascending=ascending or False)
    if "end_date" in output.columns:
        output = output.drop_duplicates(subset=["end_date"], keep="first")
    if "_update_rank" in output.columns:
        output = output.drop(columns=["_update_rank"])
    output = output.head(8)
    return output


def _fetch_price_data(pro, ts_code: str, start_api: str, end_api: str) -> pd.DataFrame:
    market = _classify_market(ts_code)
    if market == "a_share":
        return pro.daily(ts_code=ts_code, start_date=start_api, end_date=end_api)
    if market == "hk":
        return pro.hk_daily(ts_code=ts_code, start_date=start_api, end_date=end_api)
    return pro.us_daily(ts_code=ts_code, start_date=start_api, end_date=end_api)


def get_stock(symbol: str, start_date: str, end_date: str) -> str:
    pro = _get_pro_client()
    ts_code = _normalize_ts_code(symbol)

    start_api = _to_api_date(start_date)
    end_api = _to_api_date(end_date)

    data = _fetch_price_data(pro, ts_code, start_api, end_api)
    if data is None or data.empty:
        return f"No stock data found for '{ts_code}' between {start_date} and {end_date}."

    rename_map = {
        "trade_date": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "vol": "Volume",
        "amount": "Amount",
        "pct_chg": "PctChg",
        "pre_close": "PrevClose",
        "change": "Change",
    }

    output = data.rename(columns=rename_map)
    if "Date" in output.columns:
        output["Date"] = pd.to_datetime(output["Date"], format="%Y%m%d").dt.strftime(
            "%Y-%m-%d"
        )
    output = output.sort_values("Date", ascending=True)

    preferred_cols = [
        "Date",
        "Open",
        "High",
        "Low",
        "Close",
        "PrevClose",
        "Change",
        "PctChg",
        "Volume",
        "Amount",
    ]
    existing_cols = [c for c in preferred_cols if c in output.columns]
    output = output[existing_cols]

    return _to_csv_with_header(
        output,
        f"Tushare stock data for {ts_code} from {start_date} to {end_date}",
    )


def _load_price_frame(symbol: str, curr_date: str, look_back_days: int = 260) -> pd.DataFrame:
    pro = _get_pro_client()
    ts_code = _normalize_ts_code(symbol)
    end_dt = _parse_date(curr_date)
    start_dt = end_dt - timedelta(days=look_back_days)
    data = _fetch_price_data(
        pro,
        ts_code,
        start_dt.strftime("%Y%m%d"),
        end_dt.strftime("%Y%m%d"),
    )
    if data is None or data.empty:
        raise DataVendorUnavailable(
            f"No tushare price data found for '{ts_code}' before {curr_date}."
        )

    df = data.rename(
        columns={
            "trade_date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "vol": "Volume",
        }
    ).copy()
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
    df = df.sort_values("Date", ascending=True)
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]


def get_indicator(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int,
) -> str:
    from mosaic.dataflows.indicator_descriptions import INDICATOR_DESCRIPTIONS as descriptions
    if indicator not in descriptions:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(descriptions.keys())}"
        )

    current_dt = _parse_date(curr_date)
    start_dt = current_dt - timedelta(days=look_back_days)
    stats_df = wrap(_load_price_frame(symbol, curr_date))
    stats_df["Date"] = stats_df["Date"].dt.strftime("%Y-%m-%d")
    stats_df[indicator]

    lines = []
    probe_dt = current_dt
    while probe_dt >= start_dt:
        date_str = probe_dt.strftime("%Y-%m-%d")
        row = stats_df[stats_df["Date"] == date_str]
        if row.empty:
            lines.append(f"{date_str}: N/A: Not a trading day (weekend or holiday)")
        else:
            value = row.iloc[0][indicator]
            if pd.isna(value):
                lines.append(f"{date_str}: N/A")
            else:
                lines.append(f"{date_str}: {value}")
        probe_dt -= timedelta(days=1)

    return (
        f"## {indicator} values from {start_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        + "\n".join(lines)
        + "\n\n"
        + descriptions[indicator]
    )


def get_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    pro = _get_pro_client()
    ts_code = _normalize_ts_code(ticker)
    market = _classify_market(ts_code)

    if curr_date:
        curr_dt = _parse_date(curr_date)
    else:
        curr_dt = datetime.now()
        curr_date = curr_dt.strftime("%Y-%m-%d")

    end_api = curr_dt.strftime("%Y%m%d")
    start_api_40d = (curr_dt - timedelta(days=40)).strftime("%Y%m%d")
    start_api_400d = (curr_dt - timedelta(days=400)).strftime("%Y%m%d")
    stock_company = None
    main_business = None
    earnings_forecast = None
    earnings_express = None
    income_statement = None

    if market == "a_share":
        basic = pro.stock_basic(
            ts_code=ts_code,
            fields="ts_code,symbol,name,area,industry,market,list_date,list_status",
        )
        latest_price = pro.daily_basic(
            ts_code=ts_code,
            start_date=start_api_40d,
            end_date=end_api,
        )
        fina_indicator = pro.fina_indicator(
            ts_code=ts_code,
            start_date=start_api_400d,
            end_date=end_api,
        )
        stock_company = pro.stock_company(ts_code=ts_code)
        main_business = pro.fina_mainbz(ts_code=ts_code, type="P")
        earnings_forecast = pro.forecast(ts_code=ts_code)
        earnings_express = pro.express(ts_code=ts_code)
        income_statement = _filter_statement(pro.income(ts_code=ts_code), "quarterly", curr_date)
    elif market == "hk":
        basic = pro.hk_basic(ts_code=ts_code)
        latest_price = pro.hk_daily(ts_code=ts_code, start_date=start_api_40d, end_date=end_api)
        fina_indicator = None
    else:
        basic = pro.us_basic(ts_code=ts_code)
        latest_price = pro.us_daily(ts_code=ts_code, start_date=start_api_40d, end_date=end_api)
        fina_indicator = None

    overview_lines = [
        f"Ticker: {ts_code}",
        f"Market: {market}",
        f"Reference date: {curr_date}",
    ]
    company_profile_lines: list[str] = []
    valuation_lines: list[str] = []
    growth_lines: list[str] = []
    rd_lines: list[str] = []
    business_lines: list[str] = []
    guidance_lines: list[str] = []
    peer_lines: list[str] = []

    basic_row = None
    if basic is not None and not basic.empty:
        basic_row = basic.iloc[0]
        if market == "a_share":
            field_map = {
                "name": "Name",
                "area": "Area",
                "industry": "Industry",
                "market": "Market",
                "list_date": "List Date",
                "list_status": "List Status",
            }
        elif market == "hk":
            field_map = {
                "name": "Name",
                "fullname": "Full Name",
                "enname": "English Name",
                "market": "Market",
                "curr_type": "Currency",
                "list_date": "List Date",
                "list_status": "List Status",
            }
        else:
            field_map = {
                "name": "Name",
                "enname": "English Name",
                "classify": "Classify",
                "list_date": "List Date",
                "delist_date": "Delist Date",
            }
        for field, label in field_map.items():
            value = basic_row.get(field)
            if pd.notna(value):
                company_profile_lines.append(f"{label}: {value}")

    latest_price_row = None
    if latest_price is not None and not latest_price.empty:
        latest_price_row = latest_price.sort_values("trade_date", ascending=False).iloc[0]
        if market == "a_share":
            field_specs = {
                "trade_date": ("Latest Trade Date", None),
                "close": ("Latest Close Price", _format_price),
                "turnover_rate": ("Turnover Rate", _format_pct),
                "pe": ("PE", _format_multiple),
                "pb": ("PB", _format_multiple),
                "ps": ("PS", _format_multiple),
                "dv_ratio": ("Dividend Yield Ratio", _format_pct),
                "total_mv": ("Total Market Value", _format_market_value_10k_cny),
                "circ_mv": ("Circulating Market Value", _format_market_value_10k_cny),
            }
        else:
            field_specs = {
                "trade_date": ("Latest Trade Date", None),
                "close": ("Close", None),
                "open": ("Open", None),
                "high": ("High", None),
                "low": ("Low", None),
                "pre_close": ("Prev Close", None),
                "change": ("Change", None),
                "pct_chg": ("Pct Change", None),
                "vol": ("Volume", None),
                "amount": ("Amount", None),
            }
        for field, (label, formatter) in field_specs.items():
            _append_if_present(valuation_lines, label, latest_price_row.get(field), formatter)

    fina_indicator_row = None
    if fina_indicator is not None and not fina_indicator.empty:
        prepared_fina_indicator = _prepare_latest_records(
            fina_indicator,
            cutoff_col="end_date",
            cutoff=end_api,
            sort_cols=("end_date", "ann_date"),
            dedupe_cols=("end_date",),
        )
        fina_indicator_row = (
            prepared_fina_indicator.iloc[0] if not prepared_fina_indicator.empty else None
        )
        if fina_indicator_row is not None:
            field_specs = {
                "end_date": ("Latest Financial Period", None),
                "roe": ("ROE", _format_pct),
                "roa": ("ROA", _format_pct),
                "grossprofit_margin": ("Gross Margin", _format_pct),
                "netprofit_margin": ("Net Margin", _format_pct),
                "debt_to_assets": ("Debt to Assets", _format_pct),
                "ocf_to_or": ("OCF to Revenue", _format_pct),
            }
            for field, (label, formatter) in field_specs.items():
                _append_if_present(valuation_lines, label, fina_indicator_row.get(field), formatter)
        growth_lines.extend(_build_growth_and_valuation_snapshot(latest_price_row, fina_indicator_row))
    elif market == "hk":
        income = pro.hk_income(ts_code=ts_code, end_date=end_api)
        if income is not None and not income.empty:
            latest_end = income["end_date"].astype(str).max()
            valuation_lines.append(f"Latest Financial Period: {latest_end}")
            sample = income[income["end_date"].astype(str) == latest_end].head(12)
            for _, rec in sample.iterrows():
                valuation_lines.append(f"{rec.get('ind_name')}: {rec.get('ind_value')}")
    else:
        income = pro.us_income(ts_code=ts_code, end_date=end_api)
        if income is not None and not income.empty:
            latest_end = income["end_date"].astype(str).max()
            valuation_lines.append(f"Latest Financial Period: {latest_end}")
            sample = income[income["end_date"].astype(str) == latest_end].head(12)
            for _, rec in sample.iterrows():
                valuation_lines.append(f"{rec.get('ind_name')}: {rec.get('ind_value')}")

    if market == "a_share":
        if stock_company is not None and not stock_company.empty:
            stock_company_row = stock_company.iloc[0]
            _append_if_present(company_profile_lines, "Employees", stock_company_row.get("employees"))
            _append_if_present(
                company_profile_lines,
                "Company Introduction",
                _trim_text(stock_company_row.get("introduction"), 280),
            )

        rd_lines.extend(_build_rd_snapshot(income_statement))
        business_lines.extend(_build_main_business_snapshot(stock_company, main_business, end_api))

        latest_actual_end = None
        if fina_indicator_row is not None and pd.notna(fina_indicator_row.get("end_date")):
            latest_actual_end = str(fina_indicator_row.get("end_date"))
        elif income_statement is not None and not income_statement.empty:
            latest_actual_end = str(income_statement.iloc[0].get("end_date"))

        total_market_value_10k = (
            _to_float(latest_price_row.get("total_mv")) if latest_price_row is not None else None
        )
        guidance_lines.extend(
            _build_earnings_guidance_snapshot(
                earnings_forecast,
                earnings_express,
                end_api,
                latest_actual_end,
                total_market_value_10k,
            )
        )
        peer_lines.extend(
            _build_peer_comparison_snapshot(
                pro,
                ts_code,
                basic_row.get("industry") if basic_row is not None else None,
                str(latest_price_row.get("trade_date")) if latest_price_row is not None else None,
                latest_price_row,
                fina_indicator_row,
                start_api_400d,
                end_api,
                stock_company,
            )
        )

    header = f"# Tushare fundamentals for {ts_code}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    sections = []
    for title, section_lines in (
        ("Overview", overview_lines),
        ("Company Profile", company_profile_lines),
        ("Valuation and Profitability Snapshot", valuation_lines),
        ("Growth and PEG Snapshot", growth_lines),
        ("R&D Snapshot", rd_lines),
        ("Main Business and Segment Mix", business_lines),
        ("Earnings Guidance and Forward Valuation", guidance_lines),
        ("Peer Comparison Snapshot", peer_lines),
    ):
        if section_lines:
            sections.append(f"## {title}\n" + "\n".join(section_lines))

    return header + "\n\n".join(sections)


def _statement_common(
    ticker: str,
    freq: str,
    curr_date: str | None,
    fetcher: Callable,
    title: str,
    summary_builder: Callable[[pd.DataFrame], list[str]] | None = None,
) -> str:
    pro = _get_pro_client()
    ts_code = _normalize_ts_code(ticker)
    market = _classify_market(ts_code)
    data = fetcher(pro, ts_code, market)
    filtered = _filter_statement(data, freq, curr_date)
    return _to_csv_with_header(
        filtered,
        f"Tushare {title} for {ts_code} ({freq})",
        summary_builder(filtered) if summary_builder else None,
    )


def get_balance_sheet(
    ticker: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
) -> str:
    return _statement_common(
        ticker,
        freq,
        curr_date,
        lambda pro, ts_code, market: (
            pro.balancesheet(ts_code=ts_code)
            if market == "a_share"
            else pro.hk_balancesheet(ts_code=ts_code)
            if market == "hk"
            else pro.us_balancesheet(ts_code=ts_code)
        ),
        "balance sheet",
        _build_balance_sheet_summary,
    )


def get_cashflow(
    ticker: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
) -> str:
    return _statement_common(
        ticker,
        freq,
        curr_date,
        lambda pro, ts_code, market: (
            pro.cashflow(ts_code=ts_code)
            if market == "a_share"
            else pro.hk_cashflow(ts_code=ts_code)
            if market == "hk"
            else pro.us_cashflow(ts_code=ts_code)
        ),
        "cashflow",
        _build_cashflow_summary,
    )


def get_income_statement(
    ticker: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
) -> str:
    return _statement_common(
        ticker,
        freq,
        curr_date,
        lambda pro, ts_code, market: (
            pro.income(ts_code=ts_code)
            if market == "a_share"
            else pro.hk_income(ts_code=ts_code)
            if market == "hk"
            else pro.us_income(ts_code=ts_code)
        ),
        "income statement",
        _build_income_statement_summary,
    )


def get_insider_transactions(ticker: str) -> str:
    pro = _get_pro_client()
    ts_code = _normalize_ts_code(ticker)
    market = _classify_market(ts_code)

    if market != "a_share":
        raise DataVendorUnavailable(
            f"Tushare insider transactions currently support A-share tickers only, got '{ts_code}'."
        )

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=365)

    try:
        data = pro.stk_holdertrade(
            ts_code=ts_code,
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_dt.strftime("%Y%m%d"),
        )
    except Exception as exc:
        raise DataVendorUnavailable(
            f"Failed to retrieve tushare insider transactions for '{ts_code}': {exc}"
        ) from exc

    if data is None or data.empty:
        return f"No tushare insider transactions found for '{ts_code}'."

    output = data.rename(
        columns={
            "ann_date": "AnnouncementDate",
            "holder_name": "HolderName",
            "holder_type": "HolderType",
            "in_de": "Direction",
            "change_vol": "ChangeVolume",
            "change_ratio": "ChangeRatio",
            "after_share": "AfterShareholding",
            "after_ratio": "AfterRatio",
            "avg_price": "AveragePrice",
            "total_share": "TotalShareholding",
            "begin_date": "StartDate",
            "close_date": "EndDate",
        }
    ).copy()

    for col in ("AnnouncementDate", "StartDate", "EndDate"):
        if col in output.columns:
            output[col] = pd.to_datetime(
                output[col], format="%Y%m%d", errors="coerce"
            ).dt.strftime("%Y-%m-%d")

    preferred_cols = [
        "AnnouncementDate",
        "HolderName",
        "HolderType",
        "Direction",
        "ChangeVolume",
        "ChangeRatio",
        "AfterShareholding",
        "AfterRatio",
        "AveragePrice",
        "TotalShareholding",
        "StartDate",
        "EndDate",
    ]
    existing_cols = [col for col in preferred_cols if col in output.columns]
    if existing_cols:
        output = output[existing_cols]

    sort_col = "AnnouncementDate" if "AnnouncementDate" in output.columns else output.columns[0]
    output = output.sort_values(sort_col, ascending=False)
    return _to_csv_with_header(output, f"Tushare insider transactions for {ts_code}")


def get_broker_reports(
    ticker: str,
    start_date: str,
    end_date: str,
    max_reports: int = 30,
    extra_ind_names: Iterable[str] | None = None,
    *,
    _skip_market_check: bool = False,
    _skip_industry_resolution: bool = False,
) -> str:
    """Retrieve broker research reports from tushare for A-share stocks.

    Returns the full abstract text for each report. The abstract (abstr) field
    from tushare contains the report's core investment thesis, target price,
    rating, key financials, growth drivers, and risk factors — typically multiple
    paragraphs of substantive content.

    Args:
        ticker: Stock ticker (e.g. '601899.SH', '002155.SZ')
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        max_reports: Maximum number of reports to return (default 30)
        extra_ind_names: Additional tushare industry keywords to search and merge.
        _skip_market_check: Internal ETF proxy escape hatch; callers outside
            ``etf_data_tools`` should not pass this.
        _skip_industry_resolution: Internal ETF proxy mode that uses explicit
            ``extra_ind_names`` without resolving industry from stock reports.

    Returns:
        Formatted Markdown string of broker research reports with full abstracts, or a no-data note

    Raises:
        DataVendorUnavailable: If ticker is not A-share, tushare token missing, or vendor failures
    """
    pro = _get_pro_client()
    ts_code = _normalize_ts_code(ticker)
    market = _classify_market(ts_code)

    if not _skip_market_check and market != "a_share":
        raise DataVendorUnavailable(
            f"Tushare broker research reports support A-share tickers only, got '{ts_code}'."
        )

    raw_extra_ind_names = (
        (extra_ind_names,)
        if isinstance(extra_ind_names, str)
        else (extra_ind_names or [])
    )
    normalized_extra_ind_names = [
        str(candidate or "").strip() for candidate in raw_extra_ind_names
    ]
    normalized_extra_ind_names = [
        candidate for candidate in normalized_extra_ind_names if candidate
    ]

    if _skip_industry_resolution:
        if not normalized_extra_ind_names:
            raise DataVendorUnavailable(
                "Explicit industry keywords are required when skipping broker industry resolution."
            )
        industry = normalized_extra_ind_names[0]
        industry_source = "explicit industry keywords"
        basic_industry = ""
    elif _skip_market_check and market != "a_share":
        raise DataVendorUnavailable(
            "Non-A-share broker report queries require _skip_industry_resolution=True "
            "together with explicit extra_ind_names."
        )
    else:
        try:
            industry, industry_source, basic_industry = _resolve_broker_industry_keyword(
                pro,
                ts_code,
                start_date,
                end_date,
            )
        except DataVendorUnavailable as exc:
            message = str(exc)
            if not message.startswith("Cannot determine broker-search industry keyword"):
                raise
            return _format_no_research_reports(
                title=f"Industry Research Reports for unresolved industry (search keyword for {ts_code})",
                start_date=start_date,
                end_date=end_date,
                context_lines=[
                    "Industry keyword source: unresolved",
                    f"Resolution failed: {message}",
                ],
                max_reports=max_reports,
            )

    start_api = start_date.replace("-", "")
    end_api = end_date.replace("-", "")
    candidate_industries = []
    if _skip_industry_resolution:
        industry_candidates = normalized_extra_ind_names
    else:
        industry_candidates = (industry, basic_industry, *normalized_extra_ind_names)
    for candidate in industry_candidates:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in candidate_industries:
            candidate_industries.append(normalized)

    data = None
    matched_industries: list[str] = []
    data_frames: list[pd.DataFrame] = []
    last_exc = None
    collect_all_candidates = bool(normalized_extra_ind_names)
    for candidate in candidate_industries:
        try:
            candidate_data = pro.research_report(
                ind_name=candidate,
                start_date=start_api,
                end_date=end_api,
                report_type="行业研报",
                fields=_RESEARCH_REPORT_FIELDS,
            )
        except Exception as exc:
            last_exc = exc
            continue
        if candidate_data is not None and not candidate_data.empty:
            data_frames.append(candidate_data.copy())
            matched_industries.append(candidate)
            if not collect_all_candidates:
                break

    if data_frames:
        data = pd.concat(data_frames, ignore_index=True)
        dedupe_cols = [
            column
            for column in ("trade_date", "title", "inst_csname", "url", "ind_name")
            if column in data.columns
        ]
        if dedupe_cols:
            data = data.drop_duplicates(subset=dedupe_cols)
    matched_industry = ", ".join(matched_industries) or industry

    if data is None or data.empty:
        if last_exc is not None and len(candidate_industries) == 1:
            raise DataVendorUnavailable(
                f"Failed to retrieve tushare industry research reports for '{candidate_industries[0]}': {last_exc}"
            ) from last_exc

        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            wide_start = (end_dt - timedelta(days=120)).strftime("%Y%m%d")
            for candidate in candidate_industries:
                wide_data = pro.research_report(
                    ind_name=candidate,
                    start_date=wide_start,
                    end_date=end_api,
                    report_type="行业研报",
                    fields=_RESEARCH_REPORT_FIELDS,
                )
                if wide_data is not None and not wide_data.empty:
                    return _format_no_research_reports(
                        title=f"Industry Research Reports for {candidate} (search keyword for {ts_code})",
                        start_date=start_date,
                        end_date=end_date,
                        context_lines=[
                            f"Industry keyword source: {industry_source}",
                            f"Stock basic industry: {basic_industry}" if basic_industry else "",
                        ],
                        wide_data=wide_data,
                        max_reports=max_reports,
                    )
        except Exception as exc:
            logger.debug("Wider-window industry report search failed: %s", exc)

        candidates_label = ", ".join(candidate_industries) or "N/A"
        return _format_no_research_reports(
            title=f"Industry Research Reports for {candidates_label} (search keyword for {ts_code})",
            start_date=start_date,
            end_date=end_date,
            context_lines=[
                f"Industry keyword source: {industry_source}",
                f"Stock basic industry: {basic_industry}" if basic_industry else "",
            ],
            max_reports=max_reports,
        )

    data = data.sort_values("trade_date", ascending=False).head(max_reports)

    lines = [
        f"# Industry Research Reports for {matched_industry} (search keyword for {ts_code})",
        "",
        f"Period: {start_date} to {end_date} | Total: {len(data)} reports",
        f"Industry keyword source: {industry_source}",
        "",
    ]
    if basic_industry and basic_industry != matched_industry:
        lines.insert(3, f"Stock basic industry: {basic_industry}")
    _append_research_report_rows(lines, data)

    return "\n".join(lines)


def get_stock_reports(
    ticker: str,
    start_date: str,
    end_date: str,
    max_reports: int = 30,
) -> str:
    """Retrieve individual stock research reports from tushare for A-share stocks.

    Returns the full abstract text for each report. The abstract (abstr) field
    from tushare contains the report's core investment thesis, target price,
    rating, key financials, growth drivers, and risk factors — typically multiple
    paragraphs of substantive content.

    Args:
        ticker: Stock ticker (e.g. '601899.SH', '002155.SZ')
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        max_reports: Maximum number of reports to return (default 30)

    Returns:
        Formatted Markdown string of individual stock research reports with full abstracts, or a no-data note

    Raises:
        DataVendorUnavailable: If ticker is not A-share, tushare token missing, or vendor failures
    """
    pro = _get_pro_client()
    ts_code = _normalize_ts_code(ticker)
    market = _classify_market(ts_code)

    if market != "a_share":
        raise DataVendorUnavailable(
            f"Tushare stock research reports support A-share tickers only, got '{ts_code}'."
        )

    start_api = start_date.replace("-", "")
    end_api = end_date.replace("-", "")

    try:
        data = pro.research_report(
            ts_code=ts_code,
            start_date=start_api,
            end_date=end_api,
            report_type="个股研报",
            fields=_RESEARCH_REPORT_FIELDS,
        )
    except Exception as exc:
        raise DataVendorUnavailable(
            f"Failed to retrieve tushare stock research reports for '{ts_code}': {exc}"
        ) from exc

    if data is None or data.empty:
        # Try a wider 120-day window to check if the stock has any recent coverage
        from datetime import datetime, timedelta
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            wide_start = (end_dt - timedelta(days=120)).strftime("%Y%m%d")
            wide_data = pro.research_report(
                ts_code=ts_code,
                start_date=wide_start,
                end_date=end_api,
                report_type="个股研报",
                fields=_RESEARCH_REPORT_FIELDS,
            )
            if wide_data is not None and not wide_data.empty:
                return _format_no_research_reports(
                    title=f"Individual Stock Research Reports for {ts_code}",
                    start_date=start_date,
                    end_date=end_date,
                    wide_data=wide_data,
                    max_reports=max_reports,
                )
        except Exception as exc:
            logger.debug("Wider-window stock report search failed: %s", exc)

        return _format_no_research_reports(
            title=f"Individual Stock Research Reports for {ts_code}",
            start_date=start_date,
            end_date=end_date,
            max_reports=max_reports,
        )

    data = data.sort_values("trade_date", ascending=False).head(max_reports)

    lines = [
        f"# Individual Stock Research Reports for {ts_code}",
        "",
        f"Period: {start_date} to {end_date} | Total: {len(data)} reports",
        "",
    ]
    _append_research_report_rows(lines, data)

    return "\n".join(lines)

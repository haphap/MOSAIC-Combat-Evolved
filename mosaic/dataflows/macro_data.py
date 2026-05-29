"""A-share macro & sentiment data sources for Layer-1 agents.

Covers seven of the **macro_data** category functions consumed by the Layer-1
analysts (Plan §5.1):

==================================  =====================================  ============================================================
Function                            Vendor / endpoint                      Used by (Layer-1 agents)
==================================  =====================================  ============================================================
:func:`get_pboc_ops`                Tushare ``cb_op``                      ``central_bank``, ``china``
:func:`get_north_capital_flow`      Tushare ``moneyflow_hsgt``             ``dollar``, ``institutional_flow``, ``sector`` (by_sector mode)
:func:`get_lhb_ranking`             Tushare ``top_list``                   ``institutional_flow``
:func:`get_yield_curve_cn`          Tushare ``yc_cb``                      ``central_bank``, ``yield_curve``
:func:`get_us_china_spread`         Tushare ``yc_cb`` + FRED ``DGS10``     ``yield_curve``
:func:`get_xueqiu_heat`             AkShare ``stock_hot_search_xq``        ``news_sentiment``
:func:`get_industry_policy`         Tushare ``news`` (filtered)            ``china``
==================================  =====================================  ============================================================

All public functions return ``str`` (markdown-with-CSV body) so they slot into
``mosaic.dataflows.interface.route_to_vendor`` and the bridge ``tools.call``
envelope. Errors raise :class:`DataVendorUnavailable` so the caller's fallback
chain decides what to do.

Endpoint disclaimer
-------------------
Several endpoint names follow the plan exactly (``cb_op``, ``yc_cb``,
``anns_d``) but have not yet been live-verified against the current Tushare
API surface. If a name turns out to differ, the call site here is the only
place to update — the rest of the system (interface routing, tests, bridge)
will continue to work because the function signatures and CSV envelope are
stable. Live verification is a Day 5 sub-task; uncertainties tracked in
plan §14 待决议题.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta
from typing import Any

from .exceptions import DataVendorUnavailable

logger = logging.getLogger(__name__)

_DATE_FMT = "%Y-%m-%d"


# ============================================================ helpers (shared)


def _validate_iso_date(value: str | None, label: str) -> str:
    if not value:
        raise DataVendorUnavailable(f"{label} is required (YYYY-MM-DD).")
    try:
        datetime.strptime(value, _DATE_FMT)
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"{label} must be in YYYY-MM-DD format, got {value!r}: {exc}"
        ) from exc
    return value


def _to_tushare_date(value: str) -> str:
    return _validate_iso_date(value, "date").replace("-", "")


def _shift_date(value: str, days: int) -> str:
    """Return value + days as a YYYY-MM-DD string."""
    return (datetime.strptime(value, _DATE_FMT) + timedelta(days=days)).strftime(_DATE_FMT)


def _date_range_from_lookback(curr_date: str, look_back_days: int) -> tuple[str, str]:
    _validate_iso_date(curr_date, "curr_date")
    if look_back_days < 0:
        raise DataVendorUnavailable("look_back_days must be >= 0.")
    return _shift_date(curr_date, -look_back_days), curr_date


def _query_tushare(api_name: str, **params: Any):
    """Reuse the cached pro client + retry/backoff implemented in tushare.py."""
    # Lazy import — keeps this module importable without the Tushare package
    # for tests that rely on monkeypatching.
    from .tushare import _query_pro  # noqa: PLC0415

    try:
        df = _query_pro(api_name, **params)
    except DataVendorUnavailable:
        raise
    except Exception as exc:
        raise DataVendorUnavailable(
            f"Tushare endpoint {api_name!r} failed: {exc}"
        ) from exc
    if df is None:
        # Treat ``None`` as an empty result so callers always see a DataFrame.
        try:
            import pandas as pd  # noqa: PLC0415
        except ImportError as imp_exc:
            raise DataVendorUnavailable(
                "pandas is required to materialise Tushare responses."
            ) from imp_exc
        df = pd.DataFrame()
    return df


def _df_to_markdown_csv(
    df,
    title: str,
    subtitle: str | None = None,
    empty_note: str | None = None,
) -> str:
    """Format a DataFrame as ``# title\\n# subtitle\\n<csv>``.

    Empty frames return ``# title\\n<empty_note>`` so the agent receives a
    clear "no data" signal instead of an opaque empty string.
    """
    buf = io.StringIO()
    buf.write(f"# {title}\n")
    if subtitle:
        buf.write(f"# {subtitle}\n")
    if df is None or df.empty:
        note = empty_note or "No data returned for the requested window."
        buf.write(f"{note}\n")
        return buf.getvalue()
    # Use pandas' built-in to_csv — preserves headers, handles NaN as empty cells.
    df.to_csv(buf, index=False)
    return buf.getvalue()


# ============================================================ 1. PBOC ops


def get_pboc_ops(curr_date: str, look_back_days: int = 7) -> str:
    """Fetch People's Bank of China open-market operations over a window.

    Window = ``[curr_date - look_back_days, curr_date]``. The Tushare endpoint
    ``cb_op`` returns daily injections / withdrawals via reverse repo, MLF,
    SLF, etc. (operation type, volume, rate, term).

    Used by Layer-1 agents ``central_bank`` (assess monetary stance) and
    ``china`` (track domestic policy direction).
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    df = _query_tushare(
        "cb_op",
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
    )
    return _df_to_markdown_csv(
        df,
        title=f"PBOC Open Market Operations ({start_date} → {end_date})",
        subtitle="Source: Tushare cb_op. Columns include op_type, volume (亿元), rate, term.",
        empty_note=f"No PBOC operations recorded between {start_date} and {end_date}.",
    )


# ============================================================ 2. North capital flow


def get_north_capital_flow(start_date: str, end_date: str) -> str:
    """Fetch HK→A-share / A→HK net flows (沪深股通) for a date range.

    Tushare endpoint ``moneyflow_hsgt`` provides daily totals:
    * ``hgt`` 沪股通 net buy (CNY million)
    * ``sgt`` 深股通 net buy (CNY million)
    * ``ggt_ss`` 港股通(沪) net buy
    * ``ggt_sz`` 港股通(深) net buy
    * ``north_money`` aggregate north-bound (HK→A) net flow
    * ``south_money`` aggregate south-bound (A→HK) net flow

    Used by ``dollar`` (DXY/CNY/north-flow triangulation), ``institutional_flow``
    (track foreign institutional positioning), and ``sector`` agents (by-sector
    mode aggregates flows to specific industries via the ``moneyflow_hsgt_top10``
    sibling endpoint, which we may add in Phase 2).
    """
    _validate_iso_date(start_date, "start_date")
    _validate_iso_date(end_date, "end_date")
    if start_date > end_date:
        raise DataVendorUnavailable(
            f"start_date {start_date!r} is after end_date {end_date!r}."
        )
    df = _query_tushare(
        "moneyflow_hsgt",
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
    )
    return _df_to_markdown_csv(
        df,
        title=f"沪深股通资金流向 / North-South Capital Flow ({start_date} → {end_date})",
        subtitle="Source: Tushare moneyflow_hsgt. north_money / south_money in CNY million.",
        empty_note=f"No HSGT flow rows returned between {start_date} and {end_date}.",
    )


# ============================================================ 3. LHB ranking


def get_lhb_ranking(curr_date: str) -> str:
    """Fetch the daily 龙虎榜 (Dragon-Tiger list) ranking for ``curr_date``.

    Tushare endpoint ``top_list`` returns every stock that triggered a 龙虎榜
    listing on the requested trade date, including:
    * ts_code, name, close, pct_change
    * turnover_rate, amount, l_buy / l_sell / l_amount
    * net_amount, net_rate, amount_rate
    * top_amount: top-5 buyer/seller table aggregates

    Used by ``institutional_flow`` to spot concentrated buying/selling that
    leaks information about institutional positioning.
    """
    trade_date = _to_tushare_date(_validate_iso_date(curr_date, "curr_date"))
    df = _query_tushare("top_list", trade_date=trade_date)
    return _df_to_markdown_csv(
        df,
        title=f"龙虎榜 / Dragon-Tiger Ranking ({curr_date})",
        subtitle="Source: Tushare top_list. amount/l_amount in CNY thousands; net_amount in CNY thousands.",
        empty_note=f"No 龙虎榜 entries recorded on {curr_date} (likely a non-trading day).",
    )


# ============================================================ 4. CN yield curve


# Tushare ``yc_cb`` (中债国债收益率曲线) ts_codes for the headline curve.
# Format: ``Y{tenor_years*100}.CB`` per Tushare convention; we restrict to the
# benchmark tenors that drive the Layer-1 ``yield_curve`` agent's analysis.
_YC_CB_TENORS = (
    "1.0000.CB",   # 1y
    "2.0000.CB",   # 2y
    "3.0000.CB",   # 3y
    "5.0000.CB",   # 5y
    "7.0000.CB",   # 7y
    "10.0000.CB",  # 10y
    "30.0000.CB",  # 30y
)


def get_yield_curve_cn(curr_date: str, look_back_days: int = 30) -> str:
    """Fetch the CN treasury yield curve over a window.

    Window = ``[curr_date - look_back_days, curr_date]``. Tushare endpoint
    ``yc_cb`` (中债国债收益率曲线) returns daily yields per benchmark tenor.

    Used by ``central_bank`` (curve shape signals stance shifts) and
    ``yield_curve`` (slope / inversion detection).
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    df = _query_tushare(
        "yc_cb",
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
        curve_type="0",   # 0 = Treasury (国债); 1 = Corporate (信用债)
    )
    return _df_to_markdown_csv(
        df,
        title=f"中国国债收益率曲线 / CN Treasury Yield Curve ({start_date} → {end_date})",
        subtitle="Source: Tushare yc_cb. Yields in percent. Tenors: 1y/2y/3y/5y/7y/10y/30y benchmarks.",
        empty_note=f"No yc_cb rows returned between {start_date} and {end_date}.",
    )


# ============================================================ 5. US-CN 10Y spread


def get_us_china_spread(curr_date: str, look_back_days: int = 30) -> str:
    """Compute the US-CN 10-year sovereign yield spread over a window.

    * CN 10Y from Tushare ``yc_cb`` (curve_type=0, 10y tenor).
    * US 10Y from FRED ``DGS10``.

    Spread (bps) = US 10Y - CN 10Y, both in percent.

    Used by ``yield_curve`` to anchor reports on a hard cross-market metric.
    Returns a CSV with one row per trade date that has both legs.
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError as exc:
        raise DataVendorUnavailable(
            "pandas is required for the US-CN spread calculation."
        ) from exc

    cn_df = _query_tushare(
        "yc_cb",
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
        curve_type="0",
    )

    # Reduce CN frame to (date, cn_10y_pct). Tushare yc_cb columns expected:
    # ts_code, trade_date, curve_type, curve_term, curve_yield (or `value`).
    if cn_df is not None and not cn_df.empty:
        cn_view = _extract_cn_10y_yield(cn_df)
    else:
        cn_view = pd.DataFrame(columns=["date", "cn_10y_pct"])

    # Now pull US DGS10 from FRED.
    from .fred import _fetch_series_dataframe  # noqa: PLC0415

    try:
        us_df = _fetch_series_dataframe("DGS10", start_date, end_date)
    except DataVendorUnavailable as exc:
        raise DataVendorUnavailable(
            f"US-CN spread requires FRED DGS10 — {exc}"
        ) from exc
    us_view = us_df.rename(columns={"value": "us_10y_pct"})
    us_view["date"] = pd.to_datetime(us_view["date"], errors="coerce")
    us_view = us_view.dropna(subset=["date"])

    if not cn_view.empty:
        cn_view["date"] = pd.to_datetime(cn_view["date"], errors="coerce")
    merged = pd.merge(us_view, cn_view, on="date", how="inner").sort_values("date")

    if not merged.empty:
        merged["spread_bps"] = (
            (merged["us_10y_pct"] - merged["cn_10y_pct"]) * 100
        ).round(2)
        # Render the date column back to ISO.
        merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")

    return _df_to_markdown_csv(
        merged[["date", "us_10y_pct", "cn_10y_pct", "spread_bps"]] if not merged.empty else merged,
        title=f"US-CN 10Y Yield Spread ({start_date} → {end_date})",
        subtitle="spread_bps = (us_10y_pct - cn_10y_pct) * 100. Sources: FRED DGS10 + Tushare yc_cb.",
        empty_note=f"No overlapping observations between {start_date} and {end_date}.",
    )


def _extract_cn_10y_yield(df):
    """Reduce a Tushare ``yc_cb`` payload to ``DataFrame[date, cn_10y_pct]``.

    The ``yc_cb`` schema reports yields keyed by ``curve_term`` (years) for
    each ``trade_date``. We pick term==10. If the schema differs (e.g. uses
    ``ts_code`` like ``10.0000.CB``), we also accept that alternate.
    """
    import pandas as pd  # noqa: PLC0415

    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "cn_10y_pct"])

    # Locate the date column.
    date_col = None
    for candidate in ("trade_date", "date", "stat_date"):
        if candidate in df.columns:
            date_col = candidate
            break
    if date_col is None:
        return pd.DataFrame(columns=["date", "cn_10y_pct"])

    # Locate the yield column.
    yield_col = None
    for candidate in ("curve_yield", "yield", "value"):
        if candidate in df.columns:
            yield_col = candidate
            break
    if yield_col is None:
        return pd.DataFrame(columns=["date", "cn_10y_pct"])

    rows = df.copy()
    if "curve_term" in rows.columns:
        # numeric tenor column
        rows = rows[rows["curve_term"].astype(str).str.strip().isin({"10", "10.0", "10.0000"})]
    elif "ts_code" in rows.columns:
        rows = rows[rows["ts_code"].astype(str).str.startswith("10.0000")]
    else:
        # Without a tenor column we cannot disambiguate — return empty.
        return pd.DataFrame(columns=["date", "cn_10y_pct"])

    if rows.empty:
        return pd.DataFrame(columns=["date", "cn_10y_pct"])

    # Normalise date to ISO yyyy-mm-dd.
    iso_dates = pd.to_datetime(rows[date_col].astype(str), format="%Y%m%d", errors="coerce")
    if iso_dates.isna().all():
        iso_dates = pd.to_datetime(rows[date_col], errors="coerce")
    rows = rows.assign(date=iso_dates.dt.strftime("%Y-%m-%d"), cn_10y_pct=rows[yield_col])
    return rows[["date", "cn_10y_pct"]].dropna(subset=["date"]).reset_index(drop=True)


# ============================================================ 6. Xueqiu heat


def get_xueqiu_heat(ticker: str | None = None, top_n: int = 30) -> str:
    """Fetch retail-sentiment hot-attention rankings from Xueqiu (snowball.com).

    AkShare endpoint ``stock_hot_follow_xq(symbol="最热门")`` returns a 200-row
    daily ranking with columns ``["股票代码", "股票简称", "关注", "最新价"]``.
    The ``股票代码`` column uses akshare's exchange-prefixed format
    (``"SH600519"`` / ``"SZ300033"``). When ``ticker`` is supplied we filter to
    rows whose code contains the bare 6-digit number; otherwise we return the
    top ``top_n`` rows of the global ranking.

    Used by ``news_sentiment`` to gauge retail attention concentration.

    Endpoint history: an earlier draft of this module called
    ``stock_hot_search_xq``, which does **not** exist in akshare ≥1.18 — see
    plan §14 待决议题 for the list of vendor endpoint names that were
    realigned during Day 4 live verification.
    """
    if top_n < 1:
        raise DataVendorUnavailable("top_n must be >= 1.")
    try:
        import akshare as ak  # noqa: PLC0415
    except ImportError as exc:
        raise DataVendorUnavailable(
            "akshare package is not installed. Install via `uv pip install -e .[data]`."
        ) from exc

    try:
        df = ak.stock_hot_follow_xq(symbol="最热门")
    except Exception as exc:
        raise DataVendorUnavailable(
            f"AkShare stock_hot_follow_xq failed: {exc}"
        ) from exc

    if df is None or df.empty:
        try:
            import pandas as pd  # noqa: PLC0415
        except ImportError as imp_exc:
            raise DataVendorUnavailable(
                "pandas is required to materialise AkShare responses."
            ) from imp_exc
        df = pd.DataFrame()

    title = "雪球关注排行榜 / Xueqiu Hot Follow Ranking"
    if ticker:
        ticker_norm = str(ticker).strip().upper()
        # Strip MOSAIC's "600519.SH" suffix style → bare 6-digit "600519".
        bare = ticker_norm.split(".")[0] if "." in ticker_norm else ticker_norm
        if not df.empty and "股票代码" in df.columns:
            df = df[df["股票代码"].astype(str).str.upper().str.contains(bare, na=False)]
        title = f"{title} — filter ticker={ticker}"
    elif top_n:
        df = df.head(int(top_n))

    return _df_to_markdown_csv(
        df,
        title=title,
        subtitle="Source: AkShare stock_hot_follow_xq(symbol='最热门'). 关注 = current follower count.",
        empty_note=f"No Xueqiu hot-follow entries{f' for ticker {ticker}' if ticker else ''}.",
    )


# ============================================================ 7. Industry policy


_DEFAULT_POLICY_KEYWORDS = (
    "政策",
    "监管",
    "改革",
    "规划",
    "通知",
    "意见",
    "国务院",
    "央行",
    "证监会",
    "工信部",
    "发改委",
    "财政部",
    "产业",
    "新质生产力",
)


def get_industry_policy(
    curr_date: str,
    look_back_days: int = 7,
    keywords: tuple[str, ...] | None = None,
    src: str = "sina",
) -> str:
    """Fetch policy-relevant news headlines over a window.

    Window = ``[curr_date - look_back_days, curr_date]``. We hit Tushare
    ``news`` (新闻快讯) — a broad real-time newsfeed across multiple sources —
    then filter the body to rows containing any of the supplied keywords. The
    default keyword list targets central-government and regulator policy
    language.

    Used by ``china`` (policy-direction signal) and indirectly by sector
    agents looking for industry-specific catalysts.

    The plan §11 mentions ``anns_d``; that endpoint surfaces issuer-level
    company filings rather than policy news, so we route through the
    higher-recall ``news`` endpoint and filter. If the schema differs we
    fall back to returning the raw frame.
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)

    df = _query_tushare(
        "news",
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
        src=src,
    )

    keywords = keywords or _DEFAULT_POLICY_KEYWORDS
    if df is not None and not df.empty:
        text_cols = [c for c in ("content", "title") if c in df.columns]
        if text_cols:
            mask = False
            for col in text_cols:
                col_str = df[col].astype(str)
                col_mask = False
                for kw in keywords:
                    col_mask = col_mask | col_str.str.contains(kw, na=False)
                mask = mask | col_mask
            try:
                df = df[mask]
            except Exception:
                # If mask logic above degraded to a scalar bool, fall through.
                pass

    return _df_to_markdown_csv(
        df,
        title=f"产业政策 / Industry Policy News ({start_date} → {end_date})",
        subtitle=(
            f"Source: Tushare news (src={src}); "
            f"keyword filter: {', '.join(keywords)}"
        ),
        empty_note=f"No policy-flagged news rows between {start_date} and {end_date}.",
    )


# ============================================================ 8. USD/CNY FX


def get_usdcny(curr_date: str, look_back_days: int = 30) -> str:
    """Fetch the USD/CNY exchange rate over a window (Tushare ``fx_daily``).

    Window = ``[curr_date - look_back_days, curr_date]``. Tushare ``fx_daily``
    only carries the offshore ``USDCNH.FXCM`` pair (FXCM), which tracks
    onshore USD/CNY closely and is the de-facto CNY-pressure gauge. Dates are
    GMT (one day behind Beijing) per the Tushare doc.

    Used by ``dollar`` (DXY/CNY/north-flow triangulation).
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    df = _query_tushare(
        "fx_daily",
        ts_code="USDCNH.FXCM",
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
    )
    return _df_to_markdown_csv(
        df,
        title=f"USD/CNY (offshore USDCNH.FXCM) ({start_date} → {end_date})",
        subtitle="Source: Tushare fx_daily. bid_close/ask_close = CNH per USD. Dates GMT.",
        empty_note=f"No fx_daily rows for USDCNH.FXCM between {start_date} and {end_date}.",
    )


# ============================================================ 9. Commodity futures


# Continuous main-contract ts_codes (品种主连) for the headline commodities the
# ``commodities`` agent tracks. ``XX.EXG`` is Tushare's main-contract convention.
_COMMODITY_CONTRACTS = (
    ("SC.INE", "原油 / Crude Oil"),
    ("CU.SHF", "铜 / Copper"),
    ("AU.SHF", "黄金 / Gold"),
    ("RB.SHF", "螺纹钢 / Rebar"),
    ("I.DCE", "铁矿石 / Iron Ore"),
    ("M.DCE", "豆粕 / Soybean Meal"),
)


def get_commodity_prices(curr_date: str, look_back_days: int = 30) -> str:
    """Fetch a basket of continuous commodity-futures prices (Tushare ``fut_daily``).

    Window = ``[curr_date - look_back_days, curr_date]``. Pulls the main
    continuous contract for a fixed basket spanning energy (原油), metals
    (铜/黄金/螺纹/铁矿) and agriculture (豆粕) so the ``commodities`` agent can
    read oil / metals / ag regimes plus a China-demand signal in one call.

    Used by ``commodities``.
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError as exc:
        raise DataVendorUnavailable(
            "pandas is required for the commodity basket."
        ) from exc

    frames = []
    for ts_code, label in _COMMODITY_CONTRACTS:
        df = _query_tushare(
            "fut_daily",
            ts_code=ts_code,
            start_date=_to_tushare_date(start_date),
            end_date=_to_tushare_date(end_date),
        )
        if df is not None and not df.empty:
            keep = [c for c in ("ts_code", "trade_date", "close", "settle", "vol", "oi") if c in df.columns]
            sub = df[keep].copy()
            sub.insert(0, "commodity", label)
            frames.append(sub)

    merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return _df_to_markdown_csv(
        merged,
        title=f"商品期货主连 / Commodity Futures Basket ({start_date} → {end_date})",
        subtitle="Source: Tushare fut_daily (continuous main contracts). close/settle = price; vol 手; oi 持仓手.",
        empty_note=f"No fut_daily rows for the commodity basket between {start_date} and {end_date}.",
    )


# ============================================================ 10. iVX proxy (yfinance)


def get_ivx(curr_date: str, look_back_days: int = 30, index_symbol: str = "000300.SS") -> str:
    """Compute a China implied-volatility proxy (iVX) from index realized vol.

    No public iVX feed exists, so we approximate it: pull the CSI 300
    (``000300.SS``) daily closes from yfinance over the window and report
    annualized realized volatility (std of daily log returns × √252) alongside
    the close series. The ``volatility`` agent uses this as the ``ivx_regime``
    input.

    Used by ``volatility``.
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    try:
        import numpy as np  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
        import yfinance as yf  # noqa: PLC0415
    except ImportError as exc:
        raise DataVendorUnavailable(
            "yfinance + pandas are required for get_ivx. Install via `.[data]`."
        ) from exc

    # yfinance end is exclusive — bump one day so curr_date is included.
    yf_end = _shift_date(end_date, 1)
    try:
        raw = yf.download(
            index_symbol, start=start_date, end=yf_end, progress=False, auto_adjust=True
        )
    except Exception as exc:
        raise DataVendorUnavailable(f"yfinance download for {index_symbol} failed: {exc}") from exc

    if raw is None or raw.empty or "Close" not in raw.columns:
        return _df_to_markdown_csv(
            pd.DataFrame(),
            title=f"iVX proxy ({index_symbol}) ({start_date} → {end_date})",
            empty_note=f"No yfinance data for {index_symbol} between {start_date} and {end_date}.",
        )

    close = raw["Close"].squeeze()
    log_ret = np.log(close / close.shift(1)).dropna()
    realized_vol = float(log_ret.std() * np.sqrt(252) * 100) if len(log_ret) > 1 else float("nan")

    out = pd.DataFrame({"date": close.index.strftime("%Y-%m-%d"), "close": close.values})
    return _df_to_markdown_csv(
        out,
        title=f"iVX proxy ({index_symbol}) ({start_date} → {end_date})",
        subtitle=(
            f"annualized_realized_vol_pct={realized_vol:.2f}. "
            "Proxy: std(daily log return)×√252. Source: yfinance (no public iVX feed)."
        ),
        empty_note=f"No yfinance data for {index_symbol}.",
    )


# ============================================================ 11. ETF indicator


def get_etf_indicator(symbol: str, curr_date: str, look_back_days: int = 30) -> str:
    """Fetch ETF price + daily indicators over a window (Tushare ``fund_daily``).

    Window = ``[curr_date - look_back_days, curr_date]``. Returns the ETF's
    daily close / pct_chg / volume / amount, which the ``volatility`` agent
    uses for the VIX/iVX-ratio (510050.SH 上证50ETF) regime read.

    Used by ``volatility``.
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    from .tushare import _normalize_ts_code  # noqa: PLC0415

    df = _query_tushare(
        "fund_daily",
        ts_code=_normalize_ts_code(symbol),
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
    )
    if df is not None and not df.empty:
        keep = [c for c in ("trade_date", "close", "pct_chg", "vol", "amount") if c in df.columns]
        if keep:
            df = df[keep]
    return _df_to_markdown_csv(
        df,
        title=f"ETF 指标 / ETF Indicator {symbol} ({start_date} → {end_date})",
        subtitle="Source: Tushare fund_daily. close=price; pct_chg=日涨跌%; vol 手; amount 千元.",
        empty_note=f"No fund_daily rows for {symbol} between {start_date} and {end_date}.",
    )


# ============================================================ 12. ETF fund flow (share)


def get_fund_flow(symbol: str, curr_date: str, look_back_days: int = 30) -> str:
    """Fetch ETF share changes over a window (Tushare ``fund_share``).

    Window = ``[curr_date - look_back_days, curr_date]``. ETF 份额 (fd_share, 万)
    rising = net creation (inflow), falling = redemption (outflow) — a clean
    institutional fund-flow signal for A-share ETFs.

    Used by ``institutional_flow``.
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    from .tushare import _normalize_ts_code  # noqa: PLC0415

    df = _query_tushare(
        "fund_share",
        ts_code=_normalize_ts_code(symbol),
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
    )
    return _df_to_markdown_csv(
        df,
        title=f"ETF 份额变动 / Fund Share Flow {symbol} ({start_date} → {end_date})",
        subtitle="Source: Tushare fund_share. fd_share 基金份额(万). Rising=inflow, falling=redemption.",
        empty_note=f"No fund_share rows for {symbol} between {start_date} and {end_date}.",
    )


# ============================================================ public exports

__all__ = [
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

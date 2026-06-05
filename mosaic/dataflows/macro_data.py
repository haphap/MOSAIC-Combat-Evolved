"""A-share macro & sentiment data sources for Layer-1 agents.

Covers seven of the **macro_data** category functions consumed by the Layer-1
analysts (Plan §5.1):

==================================  =====================================  ============================================================
Function                            Vendor / endpoint                      Used by (Layer-1 agents)
==================================  =====================================  ============================================================
:func:`get_pboc_ops`                PBOC website mirror                    ``central_bank``, ``china``
:func:`get_lhb_ranking`             Tushare ``top_list``                   ``institutional_flow``
:func:`get_yield_curve_cn`          Tushare ``yc_cb``                      ``central_bank``, ``yield_curve``
:func:`get_tushare_macro_series`    Tushare ``us_tycr`` / ``fx_daily``     ``dollar``, ``yield_curve``
:func:`get_us_china_spread`         Tushare ``yc_cb`` + ``us_tycr``        ``yield_curve``
:func:`get_xueqiu_heat`             AkShare ``stock_hot_search_xq``        ``news_sentiment``
:func:`get_industry_policy`         gov.cn policy document library         ``china``
==================================  =====================================  ============================================================

All public functions return ``str`` (markdown-with-CSV body) so they slot into
``mosaic.dataflows.interface.route_to_vendor`` and the bridge ``tools.call``
envelope. Errors raise :class:`DataVendorUnavailable` so the caller's fallback
chain decides what to do.

Endpoint disclaimer
-------------------
Several endpoint names follow the plan exactly (``yc_cb``,
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
import re
from datetime import datetime, timedelta
from typing import Any

from .exceptions import DataVendorUnavailable
from .gov_policy import get_gov_policy_documents

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
    """Fetch People's Bank of China open-market announcements over a window.

    Used by Layer-1 agents ``central_bank`` (assess monetary stance) and
    ``china`` (track domestic policy direction).
    """
    from .pboc_ops import get_pboc_ops as _get_pboc_ops_from_pbc  # noqa: PLC0415

    return _get_pboc_ops_from_pbc(curr_date, look_back_days)


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


_US_TREASURY_SERIES_FIELDS = {
    "DGS1MO": "m1",
    "DGS2MO": "m2",
    "DGS3MO": "m3",
    "DGS6MO": "m6",
    "DGS1": "y1",
    "DGS2": "y2",
    "DGS3": "y3",
    "DGS5": "y5",
    "DGS7": "y7",
    "DGS10": "y10",
    "DGS20": "y20",
    "DGS30": "y30",
}


def get_tushare_macro_series(
    series_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Fetch a macro series from Tushare using the ``get_fred_series`` shape.

    This is a compatibility adapter for agent prompts/tool schemas that still
    name FRED series.  Route ordering now tries this Tushare adapter before the
    real FRED client, so series covered by Tushare avoid FRED entirely while
    unsupported series raise :class:`DataVendorUnavailable` and fall back.
    """
    series_id = (series_id or "").strip().upper()
    if not series_id:
        raise DataVendorUnavailable("series_id must be a non-empty string.")
    start_date = _validate_iso_date(start_date, "start_date")
    end_date = _validate_iso_date(end_date, "end_date")
    if start_date and end_date and start_date > end_date:
        raise DataVendorUnavailable(
            f"start_date {start_date!r} is after end_date {end_date!r}."
        )

    if series_id in _US_TREASURY_SERIES_FIELDS:
        field = _US_TREASURY_SERIES_FIELDS[series_id]
        df = _fetch_tushare_us_treasury_series(series_id, field, start_date, end_date)
        return _df_to_markdown_csv(
            df,
            title=f"Tushare macro series {series_id} ({start_date} → {end_date})",
            subtitle=(
                f"Source: Tushare us_tycr.{field}. Compatible replacement for "
                f"FRED {series_id}; values are percentages."
            ),
            empty_note=f"No Tushare us_tycr rows for {series_id} between {start_date} and {end_date}.",
        )

    raise DataVendorUnavailable(
        f"Tushare macro adapter does not support series {series_id!r}; falling back to FRED."
    )


def _normalise_tushare_date_column(df, source_col: str, target_col: str = "date"):
    import pandas as pd  # noqa: PLC0415

    values = df[source_col].astype(str).str.strip()
    parsed = pd.to_datetime(values, format="%Y%m%d", errors="coerce")
    parsed = parsed.where(~parsed.isna(), pd.to_datetime(values, errors="coerce"))
    return df.assign(**{target_col: parsed.dt.strftime("%Y-%m-%d")}).dropna(subset=[target_col])


def _fetch_tushare_us_treasury_series(
    series_id: str,
    field: str,
    start_date: str | None,
    end_date: str | None,
):
    import pandas as pd  # noqa: PLC0415

    if not start_date or not end_date:
        raise DataVendorUnavailable(
            f"Tushare us_tycr requires start_date and end_date for {series_id}."
        )
    df = _query_tushare(
        "us_tycr",
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
    )
    if df is None or df.empty:
        raise DataVendorUnavailable(
            f"Tushare us_tycr returned no rows for {series_id} between {start_date} and {end_date}."
        )
    if "date" not in df.columns or field not in df.columns:
        raise DataVendorUnavailable(
            f"Tushare us_tycr response missing required columns date/{field}."
        )
    out = _normalise_tushare_date_column(df[["date", field]].copy(), "date")
    out = out.rename(columns={field: "value"})
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out[["date", "value"]].dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def get_us_china_spread(curr_date: str, look_back_days: int = 30) -> str:
    """Compute the US-CN 10-year sovereign yield spread over a window.

    * CN 10Y from Tushare ``yc_cb`` (curve_type=0, 10y tenor).
    * US 10Y from Tushare ``us_tycr.y10`` first, FRED ``DGS10`` fallback.

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

    us_source = "Tushare us_tycr.y10"
    try:
        us_df = _fetch_tushare_us_treasury_series("DGS10", "y10", start_date, end_date)
    except DataVendorUnavailable as tushare_exc:
        from .fred import _fetch_series_dataframe  # noqa: PLC0415

        try:
            us_df = _fetch_series_dataframe("DGS10", start_date, end_date)
            us_source = "FRED DGS10 fallback"
        except DataVendorUnavailable as fred_exc:
            empty = pd.DataFrame(columns=["date", "us_10y_pct", "cn_10y_pct", "spread_bps"])
            return _df_to_markdown_csv(
                empty,
                title=f"US-CN 10Y Yield Spread ({start_date} → {end_date})",
                subtitle=(
                    "spread_bps = (us_10y_pct - cn_10y_pct) * 100. "
                    f"US leg unavailable: Tushare us_tycr.y10 ({tushare_exc}); "
                    f"FRED DGS10 ({fred_exc})."
                ),
                empty_note=f"No US-CN spread observations between {start_date} and {end_date}.",
            )
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
        subtitle=f"spread_bps = (us_10y_pct - cn_10y_pct) * 100. Sources: {us_source} + Tushare yc_cb.",
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


def get_industry_policy(
    curr_date: str,
    look_back_days: int = 7,
    src: str = "govcn",
    *,
    keywords: tuple[str, ...] | None = None,
) -> str:
    """Fetch policy-relevant documents over a window.

    The default source is the public State Council policy document library
    behind ``https://www.gov.cn/zhengce/zhengcewenjianku/index.htm``.  It
    provides structured government, department, gazette, and policy-interpretation
    records without Tushare ``news`` permissions.

    ``src`` is retained for the existing bridge schema.  Values other than
    ``govcn`` are accepted for backward compatibility but do not route back to
    Tushare.
    """
    _ = src
    return get_gov_policy_documents(
        curr_date,
        look_back_days,
        keywords=keywords,
    )


# ============================================================ 8. USD/CNY FX


def get_usdcny(curr_date: str, look_back_days: int = 30) -> str:
    """Fetch the USD/CNY exchange rate over a window (Tushare ``fx_daily``).

    Window = ``[curr_date - look_back_days, curr_date]``. Tushare ``fx_daily``
    only carries the offshore ``USDCNH.FXCM`` pair (FXCM), which tracks
    onshore USD/CNY closely and is the de-facto CNY-pressure gauge. Dates are
    GMT (one day behind Beijing) per the Tushare doc.

    Used by ``dollar`` (DXY/CNY/CN-US-spread triangulation).
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    title = f"USD/CNY (offshore USDCNH.FXCM) ({start_date} → {end_date})"
    subtitle = "Source: Tushare fx_daily. bid_close/ask_close = CNH per USD. Dates GMT."
    try:
        df = _query_tushare(
            "fx_daily",
            ts_code="USDCNH.FXCM",
            start_date=_to_tushare_date(start_date),
            end_date=_to_tushare_date(end_date),
        )
    except DataVendorUnavailable as exc:
        try:
            import pandas as pd  # noqa: PLC0415
        except ImportError as imp_exc:
            raise DataVendorUnavailable(
                "pandas is required to materialise Tushare responses."
            ) from imp_exc
        return _df_to_markdown_csv(
            pd.DataFrame(),
            title=title,
            subtitle=f"{subtitle} Tushare fx_daily unavailable: {exc}",
            empty_note=f"No fx_daily rows for USDCNH.FXCM between {start_date} and {end_date}.",
        )
    return _df_to_markdown_csv(
        df,
        title=title,
        subtitle=subtitle,
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


# ============================================================ 13. Property (real-estate)


def get_property_data(curr_date: str, top_n: int = 24) -> str:
    """Fetch the China national real-estate climate index (国房景气指数) as of a date.

    Tushare's macro section has no dedicated real-estate endpoint (plan §14 #8),
    so this routes to AkShare ``macro_china_real_estate`` — the monthly 国房景气
    指数 (>100 = expansion / <100 = contraction composite of property investment,
    sales, new starts, land, and financing).

    Point-in-time: only months **on or before** ``curr_date`` are returned, then
    the most recent ``top_n`` of those. This keeps backtests honest — under a
    backtest as-of context, ``route_to_vendor`` clamps ``curr_date`` to the
    replayed date (``get_property_data`` is registered in
    ``interface._CURRENT_DATE_METHODS``), so the china agent never sees
    future real-estate prints. Dates are coerced via ``pd.to_datetime`` before
    sorting so ordering doesn't depend on the raw label format.

    Used by ``china`` (property + its supply chain is a large share of GDP and a
    key policy lever — a primary A-share macro driver).
    """
    _validate_iso_date(curr_date, "curr_date")
    if top_n < 1:
        raise DataVendorUnavailable("top_n must be >= 1.")
    try:
        import akshare as ak  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
    except ImportError as exc:
        raise DataVendorUnavailable(
            "akshare + pandas are required. Install via `uv pip install -e .[data]`."
        ) from exc

    try:
        df = ak.macro_china_real_estate()
    except Exception as exc:
        raise DataVendorUnavailable(
            f"AkShare macro_china_real_estate failed: {exc}"
        ) from exc

    if df is not None and not df.empty:
        date_col = "日期" if "日期" in df.columns else df.columns[0]
        parsed = pd.to_datetime(df[date_col], errors="coerce")
        cutoff = pd.Timestamp(curr_date)
        df = (
            df.assign(_dt=parsed)
            .dropna(subset=["_dt"])
            .loc[lambda d: d["_dt"] <= cutoff]
            .sort_values("_dt", ascending=False)
            .head(int(top_n))
            .drop(columns=["_dt"])
        )

    return _df_to_markdown_csv(
        df,
        title=f"国房景气指数 / China Real-Estate Climate Index (as of {curr_date})",
        subtitle=(
            "Source: AkShare macro_china_real_estate (monthly). 最新值 = index level "
            "(>100 expansion, <100 contraction); 涨跌幅 / 近N月涨跌幅 in percent."
        ),
        empty_note=f"No real-estate climate index rows on or before {curr_date}.",
    )


# ============================================================ 14. Stock / industry money-flow


def get_stock_moneyflow(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch a single stock's main-funds flow over [start_date, end_date].

    Tushare ``moneyflow`` (个股资金流向) splits trades into small / medium /
    large / extra-large orders (by amount) and reports daily ``net_mf_amount``
    (净流入额, CNY 万元) — large + extra-large net is the de-facto "main funds"
    (主力) signal. Used by ``institutional_flow`` to see whether big money is
    accumulating or distributing a name.
    """
    _validate_iso_date(start_date, "start_date")
    _validate_iso_date(end_date, "end_date")
    if start_date > end_date:
        raise DataVendorUnavailable(
            f"start_date {start_date!r} is after end_date {end_date!r}."
        )
    from .tushare import _normalize_ts_code  # noqa: PLC0415

    df = _query_tushare(
        "moneyflow",
        ts_code=_normalize_ts_code(ticker),
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
    )
    if df is not None and not df.empty:
        keep = [
            c
            for c in (
                "trade_date", "net_mf_amount",
                "buy_lg_amount", "sell_lg_amount",
                "buy_elg_amount", "sell_elg_amount",
            )
            if c in df.columns
        ]
        if keep:
            df = df[keep]
    return _df_to_markdown_csv(
        df,
        title=f"个股资金流向 / Stock Money Flow {ticker} ({start_date} → {end_date})",
        subtitle=(
            "Source: Tushare moneyflow. net_mf_amount = 净流入额(万元); "
            "lg/elg = 大单/特大单 (主力) buy/sell amount(万元)."
        ),
        empty_note=f"No moneyflow rows for {ticker} between {start_date} and {end_date}.",
    )


def get_industry_moneyflow(
    curr_date: str, look_back_days: int = 5, industries: str = ""
) -> str:
    """Fetch THS industry-level money-flow over a window.

    Window = ``[curr_date - look_back_days, curr_date]``. Tushare
    ``moneyflow_ind_ths`` (同花顺行业资金流向) reports daily per-industry net
    inflow + lead stock. Used by ``sector`` agents to see which industries main
    funds are rotating into / out of. Columns are passed through defensively
    (THS schema: industry / net_amount / pct_change / lead_stock / …).

    ``industries`` optionally narrows the ~90-industry table to just the THS
    industries a caller cares about — a comma-separated list of 同花顺行业 name
    substrings (ASCII ``,`` or CJK ``，`` / ``、``; e.g. ``"半导体"`` or
    ``"银行,证券,保险"``). The match is a **substring** test on the ``industry``
    column — deliberately broad, so a single token like ``"医疗"`` captures the
    whole family (医疗器械 / 医疗服务 / …); pass a narrower exact name to tighten
    it. If nothing matches it **degrades to the full table with a note** (so a
    mistyped 同花顺行业 name never blanks the output).
    """
    start_date, end_date = _date_range_from_lookback(curr_date, look_back_days)
    df = _query_tushare(
        "moneyflow_ind_ths",
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
    )
    subtitle = (
        "Source: Tushare moneyflow_ind_ths (同花顺行业). net_amount = 行业净流入; "
        "positive = main funds rotating in."
    )

    tokens = [t.strip() for t in re.split(r"[,，、]", industries) if t.strip()]
    if tokens and df is not None and not df.empty and "industry" in df.columns:
        pattern = "|".join(re.escape(t) for t in tokens)
        matched = df[df["industry"].astype(str).str.contains(pattern, na=False)]
        if not matched.empty:
            df = matched
            subtitle += f" Filtered to industries matching: {', '.join(tokens)}."
        else:
            subtitle += (
                f" (No THS industry matched {', '.join(tokens)} — showing all; "
                "check the 同花顺行业 name.)"
            )

    return _df_to_markdown_csv(
        df,
        title=f"行业资金流向 / Industry Money Flow ({start_date} → {end_date})",
        subtitle=subtitle,
        empty_note=f"No industry moneyflow rows between {start_date} and {end_date}.",
    )


# ============================================================ public exports

__all__ = [
    "get_pboc_ops",
    "get_lhb_ranking",
    "get_yield_curve_cn",
    "get_tushare_macro_series",
    "get_us_china_spread",
    "get_xueqiu_heat",
    "get_industry_policy",
    "get_usdcny",
    "get_commodity_prices",
    "get_ivx",
    "get_etf_indicator",
    "get_fund_flow",
    "get_property_data",
    "get_stock_moneyflow",
    "get_industry_moneyflow",
]

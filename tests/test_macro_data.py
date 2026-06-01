"""Tests for ``mosaic.dataflows.macro_data``.

All seven functions are exercised offline via :mod:`unittest.mock` patches of
the underlying Tushare ``_query_pro`` helper, AkShare, and the FRED client.
Live integration tests are gated on ``TUSHARE_TOKEN`` / ``FRED_API_KEY`` and
remain skipped in CI.
"""

from __future__ import annotations

import os
from unittest import mock

import pandas as pd
import pytest

from mosaic.dataflows import macro_data
from mosaic.dataflows.exceptions import DataVendorUnavailable


# --------------------------------------------------------------------- helpers


def _df_with_rows(rows: list[dict]):
    return pd.DataFrame(rows)


@pytest.fixture
def mock_query_pro(monkeypatch):
    """Patch ``mosaic.dataflows.tushare._query_pro`` to return canned frames.

    The patch survives the ``_query_tushare`` lazy import inside macro_data.
    """

    def _set(return_value, side_effect=None):
        from mosaic.dataflows import tushare as _tushare_mod  # noqa: PLC0415

        patcher = mock.patch.object(
            _tushare_mod,
            "_query_pro",
            side_effect=side_effect,
            return_value=return_value if side_effect is None else None,
        )
        m = patcher.start()
        monkeypatch.setattr(macro_data, "_query_tushare_patcher", patcher, raising=False)
        return m

    return _set


# --------------------------------------------------------------------- helpers (input validation)


class TestSharedHelpers:
    def test_validate_iso_date_accepts_padded(self):
        assert macro_data._validate_iso_date("2024-06-30", "x") == "2024-06-30"

    @pytest.mark.parametrize(
        "bad_date", ["2024/06/30", "20240630", "Jan 1 2024", "", None]
    )
    def test_validate_iso_date_rejects_others(self, bad_date):
        with pytest.raises(DataVendorUnavailable):
            macro_data._validate_iso_date(bad_date, "x")

    def test_to_tushare_date_strips_dashes(self):
        assert macro_data._to_tushare_date("2024-06-30") == "20240630"

    def test_date_range_from_lookback(self):
        start, end = macro_data._date_range_from_lookback("2024-06-30", 7)
        assert start == "2024-06-23"
        assert end == "2024-06-30"

    def test_date_range_zero_lookback(self):
        start, end = macro_data._date_range_from_lookback("2024-06-30", 0)
        assert start == end == "2024-06-30"

    def test_date_range_negative_lookback_rejected(self):
        with pytest.raises(DataVendorUnavailable, match=">= 0"):
            macro_data._date_range_from_lookback("2024-06-30", -1)


class TestMarkdownCsv:
    def test_empty_frame_emits_note(self):
        out = macro_data._df_to_markdown_csv(
            pd.DataFrame(),
            title="Empty",
            empty_note="No rows",
        )
        assert out.startswith("# Empty\n")
        assert "No rows" in out

    def test_populated_frame_emits_csv(self):
        df = pd.DataFrame([{"a": 1, "b": 2}, {"a": 3, "b": 4}])
        out = macro_data._df_to_markdown_csv(df, title="T", subtitle="S")
        lines = out.splitlines()
        assert lines[0] == "# T"
        assert lines[1] == "# S"
        assert lines[2] == "a,b"
        assert lines[3] == "1,2"


# --------------------------------------------------------------------- 1. PBOC ops


def test_get_pboc_ops_uses_window(mock_query_pro):
    canned = _df_with_rows(
        [
            {"trade_date": "20240624", "op_type": "Reverse Repo", "volume": 200, "rate": 1.8, "term": 7},
            {"trade_date": "20240625", "op_type": "MLF", "volume": 100, "rate": 2.5, "term": 365},
        ]
    )
    m = mock_query_pro(canned)

    out = macro_data.get_pboc_ops("2024-06-30", look_back_days=7)

    assert m.call_count == 1
    kwargs = m.call_args.kwargs
    assert kwargs["start_date"] == "20240623"
    assert kwargs["end_date"] == "20240630"
    assert "PBOC Open Market Operations" in out
    assert "Reverse Repo" in out
    assert "MLF" in out


def test_get_pboc_ops_empty_frame(mock_query_pro):
    mock_query_pro(pd.DataFrame())
    out = macro_data.get_pboc_ops("2024-06-30", look_back_days=2)
    assert "No PBOC operations recorded" in out


# --------------------------------------------------------------------- 2. North-flow


def test_get_north_capital_flow_emits_csv(mock_query_pro):
    canned = _df_with_rows(
        [
            {
                "trade_date": "20240628",
                "ggt_ss": 12.3,
                "ggt_sz": 4.5,
                "hgt": 30.1,
                "sgt": 12.4,
                "north_money": 42.5,
                "south_money": 16.8,
            }
        ]
    )
    mock_query_pro(canned)

    out = macro_data.get_north_capital_flow("2024-06-24", "2024-06-28")

    assert "沪深股通" in out
    assert "north_money" in out
    assert "42.5" in out


def test_get_north_capital_flow_rejects_inverted_range():
    with pytest.raises(DataVendorUnavailable, match="after end_date"):
        macro_data.get_north_capital_flow("2024-12-31", "2024-01-01")


# --------------------------------------------------------------------- 3. LHB


def test_get_lhb_ranking_passes_trade_date(mock_query_pro):
    canned = _df_with_rows(
        [
            {
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "close": 1700,
                "pct_change": 1.5,
                "amount": 9_500_000,
                "net_amount": 4_500_000,
            }
        ]
    )
    m = mock_query_pro(canned)

    out = macro_data.get_lhb_ranking("2024-06-28")

    assert m.call_args.kwargs == {"trade_date": "20240628"}
    assert "Dragon-Tiger" in out
    assert "贵州茅台" in out


def test_get_lhb_ranking_empty_day(mock_query_pro):
    mock_query_pro(pd.DataFrame())
    out = macro_data.get_lhb_ranking("2024-06-29")
    assert "non-trading day" in out


# --------------------------------------------------------------------- 4. CN curve


def test_get_yield_curve_cn_emits_csv(mock_query_pro):
    canned = _df_with_rows(
        [
            {"trade_date": "20240628", "curve_type": "0", "curve_term": "10", "curve_yield": 2.43},
            {"trade_date": "20240628", "curve_type": "0", "curve_term": "1", "curve_yield": 1.55},
        ]
    )
    m = mock_query_pro(canned)

    out = macro_data.get_yield_curve_cn("2024-06-28", look_back_days=5)

    assert m.call_args.kwargs["curve_type"] == "0"
    assert m.call_args.kwargs["start_date"] == "20240623"
    assert m.call_args.kwargs["end_date"] == "20240628"
    assert "CN Treasury Yield Curve" in out
    assert "2.43" in out


# --------------------------------------------------------------------- 5. US-CN spread


def test_us_china_spread_merges_fred_and_tushare(monkeypatch, mock_query_pro):
    # Tushare side: minimal yc_cb payload with 10y rows on three dates.
    cn_df = _df_with_rows(
        [
            {"trade_date": "20240624", "curve_term": "10", "curve_yield": 2.4},
            {"trade_date": "20240625", "curve_term": "10", "curve_yield": 2.42},
            {"trade_date": "20240626", "curve_term": "10", "curve_yield": 2.45},
            # noise rows that should be filtered
            {"trade_date": "20240624", "curve_term": "1", "curve_yield": 1.5},
        ]
    )
    mock_query_pro(cn_df)

    # FRED side: monkeypatch the module-level fetcher.
    fred_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-06-24", "2024-06-25", "2024-06-26"]),
            "value": [4.30, 4.32, 4.40],
        }
    )

    def _fake_fetch(series_id, start_date=None, end_date=None):
        assert series_id == "DGS10"
        return fred_df

    from mosaic.dataflows import fred as fred_mod

    monkeypatch.setattr(fred_mod, "_fetch_series_dataframe", _fake_fetch)

    out = macro_data.get_us_china_spread("2024-06-26", look_back_days=2)

    assert "US-CN 10Y Yield Spread" in out
    # spread = (4.30 - 2.40) * 100 = 190.0
    assert "190.0" in out
    # spread = (4.40 - 2.45) * 100 = 195.0
    assert "195.0" in out


def test_us_china_spread_handles_missing_us_leg(monkeypatch, mock_query_pro):
    cn_df = _df_with_rows(
        [{"trade_date": "20240624", "curve_term": "10", "curve_yield": 2.4}]
    )
    mock_query_pro(cn_df)

    from mosaic.dataflows import fred as fred_mod

    def _raise(*_args, **_kwargs):
        raise DataVendorUnavailable("FRED_API_KEY is not set.")

    monkeypatch.setattr(fred_mod, "_fetch_series_dataframe", _raise)

    with pytest.raises(DataVendorUnavailable, match="FRED DGS10"):
        macro_data.get_us_china_spread("2024-06-30", look_back_days=10)


def test_extract_cn_10y_yield_handles_alt_schema():
    # Alt: ts_code carries "10.0000.CB"
    df = pd.DataFrame(
        [
            {"trade_date": "20240624", "ts_code": "10.0000.CB", "value": 2.40},
            {"trade_date": "20240624", "ts_code": "1.0000.CB", "value": 1.50},
        ]
    )
    out = macro_data._extract_cn_10y_yield(df)
    assert list(out.columns) == ["date", "cn_10y_pct"]
    assert len(out) == 1
    assert out.iloc[0]["cn_10y_pct"] == 2.40


# --------------------------------------------------------------------- 6. Xueqiu


@pytest.fixture
def fake_xq_module(monkeypatch):
    """Provide a stand-in for ``akshare.stock_hot_follow_xq``."""

    class _StubAk:
        def __init__(self, df=None, raises=None):
            self._df = df
            self._raises = raises

        def stock_hot_follow_xq(self, symbol="最热门"):
            assert symbol == "最热门"
            if self._raises is not None:
                raise self._raises
            return self._df

    def _make(df=None, raises=None):
        stub = _StubAk(df=df, raises=raises)
        monkeypatch.setitem(__import__("sys").modules, "akshare", stub)
        return stub

    return _make


def test_get_xueqiu_heat_returns_top_n(fake_xq_module):
    df = pd.DataFrame(
        {
            "股票代码": [f"SZ{300000 + i:06d}" for i in range(50)],
            "股票简称": [f"name{i}" for i in range(50)],
            "关注": list(range(50, 0, -1)),
            "最新价": [10.0 + 0.1 * i for i in range(50)],
        }
    )
    fake_xq_module(df=df)

    out = macro_data.get_xueqiu_heat(top_n=5)
    body_lines = out.splitlines()
    # title + subtitle + csv-header + 5 rows = 8 lines (no trailing blank)
    assert "Hot Follow Ranking" in out
    csv_rows = [ln for ln in body_lines if ln.startswith("SZ")]
    assert len(csv_rows) == 5


def test_get_xueqiu_heat_filters_by_ticker(fake_xq_module):
    df = pd.DataFrame(
        [
            {"股票代码": "SH600519", "股票简称": "贵州茅台", "关注": 9999, "最新价": 1700.0},
            {"股票代码": "SH601398", "股票简称": "工商银行", "关注": 5000, "最新价": 5.5},
        ]
    )
    fake_xq_module(df=df)

    out = macro_data.get_xueqiu_heat(ticker="600519.SH")
    assert "贵州茅台" in out
    assert "工商银行" not in out


def test_get_xueqiu_heat_failure_wraps(fake_xq_module):
    fake_xq_module(raises=RuntimeError("network down"))
    with pytest.raises(DataVendorUnavailable, match="stock_hot_follow_xq failed"):
        macro_data.get_xueqiu_heat()


def test_get_xueqiu_heat_rejects_zero_top_n():
    with pytest.raises(DataVendorUnavailable, match=">= 1"):
        macro_data.get_xueqiu_heat(top_n=0)


# --------------------------------------------------------------------- 13. Property data


@pytest.fixture
def fake_real_estate_module(monkeypatch):
    """Stand-in for ``akshare.macro_china_real_estate``."""

    class _StubAk:
        def __init__(self, df=None, raises=None):
            self._df = df
            self._raises = raises

        def macro_china_real_estate(self):
            if self._raises is not None:
                raise self._raises
            return self._df

    def _make(df=None, raises=None):
        monkeypatch.setitem(__import__("sys").modules, "akshare", _StubAk(df=df, raises=raises))

    return _make


def test_get_property_data_returns_top_n(fake_real_estate_module):
    df = pd.DataFrame(
        {
            "日期": [f"2025-{m:02d}-01" for m in range(1, 13)],
            "最新值": [90 + m for m in range(1, 13)],
            "涨跌幅": [0.1 * m for m in range(1, 13)],
        }
    )
    fake_real_estate_module(df=df)
    out = macro_data.get_property_data("2025-12-31", top_n=3)
    assert "国房景气指数" in out
    csv_rows = [ln for ln in out.splitlines() if ln.startswith("2025-")]
    assert len(csv_rows) == 3
    # Most-recent-first: December should be present, January should not.
    assert "2025-12-01" in out
    assert "2025-01-01" not in out


def test_get_property_data_clamps_to_curr_date(fake_real_estate_module):
    """Point-in-time: months after curr_date must be excluded (anti-lookahead)."""
    df = pd.DataFrame(
        {
            "日期": [f"2025-{m:02d}-01" for m in range(1, 13)],
            "最新值": [90 + m for m in range(1, 13)],
        }
    )
    fake_real_estate_module(df=df)
    out = macro_data.get_property_data("2025-06-15", top_n=24)
    # June and earlier present; July+ (future relative to curr_date) excluded.
    assert "2025-06-01" in out
    assert "2025-05-01" in out
    assert "2025-07-01" not in out
    assert "2025-12-01" not in out


def test_get_property_data_failure_wraps(fake_real_estate_module):
    fake_real_estate_module(raises=RuntimeError("akshare down"))
    with pytest.raises(DataVendorUnavailable, match="macro_china_real_estate failed"):
        macro_data.get_property_data("2025-06-30")


def test_get_property_data_rejects_zero_top_n():
    with pytest.raises(DataVendorUnavailable, match=">= 1"):
        macro_data.get_property_data("2025-06-30", top_n=0)


# --------------------------------------------------------------------- 7. Industry policy


def test_get_industry_policy_filters_keywords(mock_query_pro):
    canned = _df_with_rows(
        [
            {
                "datetime": "2024-06-25 10:00",
                "title": "国务院发布新质生产力发展规划",
                "content": "国务院今日发布关于推动新质生产力发展的指导意见，重点支持半导体...",
            },
            {
                "datetime": "2024-06-25 12:30",
                "title": "茅台股价创新高",
                "content": "贵州茅台早盘冲高，市值再创历史新高。",
            },
        ]
    )
    mock_query_pro(canned)

    out = macro_data.get_industry_policy("2024-06-30", look_back_days=7)

    assert "Industry Policy News" in out
    assert "新质生产力" in out
    assert "茅台" not in out  # filtered out


def test_get_industry_policy_empty_results(mock_query_pro):
    mock_query_pro(pd.DataFrame())
    out = macro_data.get_industry_policy("2024-06-30", look_back_days=7)
    assert "No policy-flagged news rows" in out


# --------------------------------------------------------------------- 8. USD/CNY


def test_get_usdcny_uses_usdcnh_pair(mock_query_pro):
    canned = _df_with_rows(
        [{"ts_code": "USDCNH.FXCM", "trade_date": "20240628", "bid_close": 7.26, "ask_close": 7.27}]
    )
    m = mock_query_pro(canned)
    out = macro_data.get_usdcny("2024-06-30", look_back_days=7)
    assert m.call_args.kwargs["ts_code"] == "USDCNH.FXCM"
    assert m.call_args.kwargs["start_date"] == "20240623"
    assert "USD/CNY" in out
    assert "7.26" in out


def test_get_usdcny_empty(mock_query_pro):
    mock_query_pro(pd.DataFrame())
    assert "No fx_daily rows" in macro_data.get_usdcny("2024-06-30", look_back_days=3)


# --------------------------------------------------------------------- 9. Commodity prices


def test_get_commodity_prices_basket(mock_query_pro):
    canned = _df_with_rows(
        [{"ts_code": "CU.SHF", "trade_date": "20240628", "close": 80000, "settle": 79900, "vol": 12, "oi": 50}]
    )
    m = mock_query_pro(canned)
    out = macro_data.get_commodity_prices("2024-06-30", look_back_days=7)
    # one query per basket contract
    assert m.call_count == len(macro_data._COMMODITY_CONTRACTS)
    assert "Commodity Futures Basket" in out
    assert "铜 / Copper" in out


def test_get_commodity_prices_all_empty(mock_query_pro):
    mock_query_pro(pd.DataFrame())
    assert "No fut_daily rows" in macro_data.get_commodity_prices("2024-06-30", look_back_days=3)


# --------------------------------------------------------------------- 10. iVX proxy


@pytest.fixture
def fake_yf_module(monkeypatch):
    """Stand-in for yfinance.download."""

    class _StubYf:
        def __init__(self, df):
            self._df = df

        def download(self, symbol, start=None, end=None, progress=False, auto_adjust=True):
            return self._df

    def _make(df):
        monkeypatch.setitem(__import__("sys").modules, "yfinance", _StubYf(df))

    return _make


def test_get_ivx_computes_realized_vol(fake_yf_module):
    idx = pd.date_range("2024-06-20", periods=6, freq="D")
    df = pd.DataFrame({"Close": [3500, 3520, 3490, 3530, 3510, 3550]}, index=idx)
    fake_yf_module(df)
    out = macro_data.get_ivx("2024-06-26", look_back_days=10)
    assert "iVX proxy" in out
    assert "annualized_realized_vol_pct" in out


def test_get_ivx_empty(fake_yf_module):
    fake_yf_module(pd.DataFrame())
    assert "No yfinance data" in macro_data.get_ivx("2024-06-26", look_back_days=5)


# --------------------------------------------------------------------- 11. ETF indicator


def test_get_etf_indicator_selects_columns(mock_query_pro):
    canned = _df_with_rows(
        [{"trade_date": "20240628", "close": 2.85, "pct_chg": 0.7, "vol": 1000, "amount": 2850, "extra": "drop"}]
    )
    m = mock_query_pro(canned)
    out = macro_data.get_etf_indicator("510050.SH", "2024-06-30", look_back_days=7)
    assert m.call_args.kwargs["ts_code"] == "510050.SH"
    assert "ETF Indicator 510050.SH" in out
    assert "pct_chg" in out
    assert "extra" not in out


# --------------------------------------------------------------------- 12. Fund flow


def test_get_fund_flow_emits_shares(mock_query_pro):
    canned = _df_with_rows(
        [{"ts_code": "510300.SH", "trade_date": "20240628", "fd_share": 206733.28}]
    )
    m = mock_query_pro(canned)
    out = macro_data.get_fund_flow("510300.SH", "2024-06-30", look_back_days=7)
    assert m.call_args.kwargs["ts_code"] == "510300.SH"
    assert "Fund Share Flow" in out
    assert "fd_share" in out


def test_get_fund_flow_empty(mock_query_pro):
    mock_query_pro(pd.DataFrame())
    assert "No fund_share rows" in macro_data.get_fund_flow("510300.SH", "2024-06-30", 3)


# --------------------------------------------------------------------- live integration


@pytest.mark.skipif(
    not os.getenv("TUSHARE_TOKEN"),
    reason="set TUSHARE_TOKEN to run live Tushare integration tests",
)
class TestLiveTushare:
    def test_live_north_capital_flow(self):
        out = macro_data.get_north_capital_flow("2024-06-03", "2024-06-07")
        # Either real data or "non-trading day" empty note — both acceptable.
        assert "north_money" in out or "No HSGT flow rows" in out

    def test_live_yield_curve_cn(self):
        out = macro_data.get_yield_curve_cn("2024-06-28", look_back_days=5)
        assert "CN Treasury Yield Curve" in out


# --------------------------------------------------------------------- 14. Money flow


def test_get_stock_moneyflow_emits_net_mf(mock_query_pro):
    mock_query_pro(
        _df_with_rows(
            [
                {
                    "ts_code": "600519.SH",
                    "trade_date": "20240628",
                    "net_mf_amount": 12345.6,
                    "buy_lg_amount": 9000.0,
                    "sell_lg_amount": 4000.0,
                    "buy_elg_amount": 6000.0,
                    "sell_elg_amount": 2000.0,
                }
            ]
        )
    )
    out = macro_data.get_stock_moneyflow("600519.SH", "2024-06-01", "2024-06-28")
    assert "Stock Money Flow" in out
    assert "net_mf_amount" in out
    assert "12345.6" in out


def test_get_stock_moneyflow_rejects_inverted_range():
    with pytest.raises(DataVendorUnavailable, match="after end_date"):
        macro_data.get_stock_moneyflow("600519.SH", "2024-06-30", "2024-06-01")


def test_get_industry_moneyflow_windowed(mock_query_pro):
    captured = {}

    def _capture(api_name, **params):
        captured["api"] = api_name
        captured["params"] = params
        return _df_with_rows([{"industry": "半导体", "net_amount": 4200.0}])

    mock_query_pro(None, side_effect=_capture)
    out = macro_data.get_industry_moneyflow("2024-06-30", look_back_days=5)
    assert "Industry Money Flow" in out
    assert captured["api"] == "moneyflow_ind_ths"
    assert captured["params"]["start_date"] == "20240625"
    assert captured["params"]["end_date"] == "20240630"


def test_get_industry_moneyflow_empty(mock_query_pro):
    mock_query_pro(_df_with_rows([]))
    out = macro_data.get_industry_moneyflow("2024-06-30")
    assert "No industry moneyflow" in out

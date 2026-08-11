"""Tests for legacy ETF wrappers used outside the v2 Agent tool manifest."""

from __future__ import annotations

import pandas as pd

from mosaic.agents.utils import etf_tools as etf
from mosaic.dataflows import tushare

_NAMES = ["get_etf_info", "get_etf_nav", "get_etf_holdings", "get_etf_universe"]


def test_all_registered():
    for name in _NAMES:
        assert getattr(etf, name).name == name


def test_routing_arg_order(monkeypatch):
    cap = {}
    monkeypatch.setattr(etf, "route_to_vendor", lambda m, *a: cap.update(method=m, args=a) or "MD")

    etf.get_etf_info.invoke({"ticker": "510300.SH"})
    assert cap["method"] == "get_etf_info" and cap["args"] == ("510300.SH", None)

    etf.get_etf_holdings.invoke({"ticker": "510300.SH", "curr_date": "2024-06-30"})
    assert cap["method"] == "get_etf_holdings" and cap["args"] == ("510300.SH", "2024-06-30")

    etf.get_etf_nav.invoke({"ticker": "510300.SH", "curr_date": "2024-06-30"})
    assert cap["method"] == "get_etf_nav" and cap["args"] == ("510300.SH", "2024-06-30")

    etf.get_etf_universe.invoke({"limit": 20})
    assert cap["method"] == "get_etf_universe" and cap["args"] == (None, None, None, 20)


def test_tushare_etf_holdings_is_bounded_and_does_not_enrich_full_market(monkeypatch):
    calls = []

    def query_pro(api_name, **kwargs):
        calls.append((api_name, kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "510300.SH",
                    "end_date": "20240331",
                    "ann_date": "20240420",
                    "symbol": "600519.SH",
                    "stk_mkv_ratio": 5.0,
                    "marker": "valid",
                },
                {
                    "ts_code": "510300.SH",
                    "end_date": "20240331",
                    "ann_date": "20240701",
                    "symbol": "000001.SZ",
                    "stk_mkv_ratio": 4.0,
                    "marker": "future",
                },
                {
                    "ts_code": "510300.SH",
                    "end_date": "20231231",
                    "ann_date": "",
                    "symbol": "000002.SZ",
                    "stk_mkv_ratio": 3.0,
                    "marker": "blank",
                },
            ]
        )

    monkeypatch.setattr(tushare, "_query_pro", query_pro)

    out = tushare.get_etf_holdings("510300.SH", "2024-06-30")

    assert calls == [
        (
            "fund_portfolio",
            {
                "ts_code": "510300.SH",
                "start_date": "20230527",
                "end_date": "20240630",
            },
        )
    ]
    assert "valid" in out
    assert "future" not in out
    assert "blank" not in out


def test_module_exposed_via_bridge():
    import mosaic.bridge.handlers.tools as th

    names = {t.name for t in th._iter_module_tools("mosaic.agents.utils.etf_tools")}
    assert set(_NAMES).issubset(names)

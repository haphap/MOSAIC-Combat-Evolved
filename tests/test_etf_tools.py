"""Tests for the ETF @tool wrappers (emerging_markets + sector exposure)."""

from __future__ import annotations

from mosaic.agents.utils import etf_tools as etf

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


def test_module_exposed_via_bridge():
    import mosaic.bridge.handlers.tools as th

    names = {t.name for t in th._iter_module_tools("mosaic.agents.utils.etf_tools")}
    assert set(_NAMES).issubset(names)

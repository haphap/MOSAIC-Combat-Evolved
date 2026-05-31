"""Tests for the research-report @tool wrappers (行业研报 + 个股研报).

Deps-light: asserts the @tool wrappers register with the right schema and that
invoking them routes through ``route_to_vendor`` to the configured vendor. We
monkeypatch the vendor call so no Tushare token / network is needed.
"""

from __future__ import annotations

from mosaic.agents.utils import research_report_tools as rr


def test_both_tools_registered_with_schema():
    assert rr.get_broker_research.name == "get_broker_research"
    assert rr.get_stock_research.name == "get_stock_research"
    for t in (rr.get_broker_research, rr.get_stock_research):
        assert list(t.args.keys()) == ["ticker", "start_date", "end_date", "max_reports"]


def test_broker_research_routes_to_vendor(monkeypatch):
    captured = {}

    def fake_route(method, *args, **kwargs):
        captured["method"] = method
        captured["args"] = args
        return "INDUSTRY REPORT MD"

    monkeypatch.setattr(rr, "route_to_vendor", fake_route)
    out = rr.get_broker_research.invoke(
        {"ticker": "601899.SH", "start_date": "2024-01-01", "end_date": "2024-03-31"}
    )
    assert out == "INDUSTRY REPORT MD"
    assert captured["method"] == "get_broker_research"
    # ticker, start, end, default max_reports=30
    assert captured["args"] == ("601899.SH", "2024-01-01", "2024-03-31", 30)


def test_stock_research_routes_to_vendor(monkeypatch):
    captured = {}

    def fake_route(method, *args, **kwargs):
        captured["method"] = method
        captured["args"] = args
        return "STOCK REPORT MD"

    monkeypatch.setattr(rr, "route_to_vendor", fake_route)
    out = rr.get_stock_research.invoke(
        {
            "ticker": "002155.SZ",
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "max_reports": 5,
        }
    )
    assert out == "STOCK REPORT MD"
    assert captured["method"] == "get_stock_research"
    assert captured["args"] == ("002155.SZ", "2024-01-01", "2024-03-31", 5)


def test_module_tools_exposed_via_bridge():
    import mosaic.bridge.handlers.tools as th

    names = [t.name for t in th._iter_module_tools("mosaic.agents.utils.research_report_tools")]
    assert "get_broker_research" in names
    assert "get_stock_research" in names

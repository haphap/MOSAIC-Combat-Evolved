"""Tests for the price + technical-indicator @tool wrappers."""

from __future__ import annotations

from mosaic.agents.utils import technical_tools as tt


def test_registered():
    assert tt.get_stock_data.name == "get_stock_data"
    assert tt.get_indicators.name == "get_indicators"


def test_stock_data_routes_range(monkeypatch):
    cap = {}
    monkeypatch.setattr(tt, "route_to_vendor", lambda m, *a: cap.update(method=m, args=a) or "MD")
    tt.get_stock_data.invoke({"symbol": "600519.SH", "start_date": "2024-01-01", "end_date": "2024-06-30"})
    assert cap["method"] == "get_stock_data"
    assert cap["args"] == ("600519.SH", "2024-01-01", "2024-06-30")


def test_indicators_routes_with_default_lookback(monkeypatch):
    cap = {}
    monkeypatch.setattr(tt, "route_to_vendor", lambda m, *a: cap.update(method=m, args=a) or "MD")
    tt.get_indicators.invoke({"symbol": "600519.SH", "indicator": "rsi", "curr_date": "2024-06-30"})
    assert cap["method"] == "get_indicators"
    assert cap["args"] == ("600519.SH", "rsi", "2024-06-30", 60)


def test_indicator_is_enum_constrained():
    schema = tt.get_indicators.args_schema.model_json_schema()
    enum = schema["properties"]["indicator"]["enum"]
    assert "rsi" in enum and "macd" in enum and "boll" in enum
    assert "not_an_indicator" not in enum


def test_module_exposed_via_bridge():
    import mosaic.bridge.handlers.tools as th

    names = {t.name for t in th._iter_module_tools("mosaic.agents.utils.technical_tools")}
    assert {"get_stock_data", "get_indicators"}.issubset(names)

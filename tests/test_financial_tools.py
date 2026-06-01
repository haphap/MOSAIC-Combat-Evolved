"""Tests for the company-financials @tool wrappers (superinvestor support)."""

from __future__ import annotations

from mosaic.agents.utils import financial_tools as fin

_NAMES = ["get_fundamentals", "get_balance_sheet", "get_income_statement", "get_cashflow"]


def test_all_registered_with_schema():
    for name in _NAMES:
        t = getattr(fin, name)
        assert t.name == name
        assert "ticker" in t.args


def test_fundamentals_routes_ticker_currdate(monkeypatch):
    captured = {}
    monkeypatch.setattr(fin, "route_to_vendor", lambda m, *a: captured.update(method=m, args=a) or "MD")
    out = fin.get_fundamentals.invoke({"ticker": "600519.SH", "curr_date": "2024-06-30"})
    assert out == "MD"
    assert captured["method"] == "get_fundamentals"
    assert captured["args"] == ("600519.SH", "2024-06-30")


def test_statements_route_ticker_freq_currdate(monkeypatch):
    for name in ("get_balance_sheet", "get_income_statement", "get_cashflow"):
        captured = {}
        monkeypatch.setattr(fin, "route_to_vendor", lambda m, *a: captured.update(method=m, args=a) or "MD")
        getattr(fin, name).invoke(
            {"ticker": "000001.SZ", "freq": "annual", "curr_date": "2024-06-30"}
        )
        assert captured["method"] == name
        assert captured["args"] == ("000001.SZ", "annual", "2024-06-30")


def test_statements_default_freq_quarterly(monkeypatch):
    captured = {}
    monkeypatch.setattr(fin, "route_to_vendor", lambda m, *a: captured.update(args=a) or "MD")
    fin.get_cashflow.invoke({"ticker": "000001.SZ", "curr_date": "2024-06-30"})
    assert captured["args"] == ("000001.SZ", "quarterly", "2024-06-30")


def test_module_exposed_via_bridge():
    import mosaic.bridge.handlers.tools as th

    names = {t.name for t in th._iter_module_tools("mosaic.agents.utils.financial_tools")}
    assert set(_NAMES).issubset(names)


def test_freq_is_enum_constrained():
    # review #2: freq is Literal["quarterly","annual"], enforced by the schema.
    for name in ("get_balance_sheet", "get_income_statement", "get_cashflow"):
        schema = getattr(fin, name).args_schema.model_json_schema()
        assert schema["properties"]["freq"]["enum"] == ["quarterly", "annual"]


def test_curr_date_optional_everywhere(monkeypatch):
    # review #1: all 4 default curr_date (empty → None = latest), consistently.
    captured = {}
    monkeypatch.setattr(fin, "route_to_vendor", lambda m, *a: captured.update(method=m, args=a) or "MD")
    fin.get_fundamentals.invoke({"ticker": "600519.SH"})
    assert captured["args"] == ("600519.SH", None)
    fin.get_cashflow.invoke({"ticker": "600519.SH"})
    assert captured["args"] == ("600519.SH", "quarterly", None)

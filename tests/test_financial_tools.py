"""Tests for the company-financials @tool wrappers (superinvestor support)."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pandas as pd
import pytest

from mosaic.agents.utils import financial_tools as fin
from mosaic.dataflows import tushare

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


def test_tushare_fundamentals_only_uses_ticker_scoped_bounded_calls(monkeypatch):
    pro = MagicMock()
    for endpoint in (
        "stock_basic",
        "daily_basic",
        "fina_indicator",
        "stock_company",
        "fina_mainbz",
        "forecast",
        "express",
        "income",
    ):
        getattr(pro, endpoint).return_value = pd.DataFrame()
    monkeypatch.setattr(tushare, "_get_pro_client", lambda: pro)

    tushare.get_fundamentals("600519.SH", "2024-06-30")

    assert pro.method_calls == [
        call.stock_basic(
            ts_code="600519.SH",
            fields="ts_code,symbol,name,area,industry,market,list_date,list_status",
        ),
        call.daily_basic(
            ts_code="600519.SH",
            start_date="20240521",
            end_date="20240630",
        ),
        call.fina_indicator(
            ts_code="600519.SH",
            start_date="20230527",
            end_date="20240630",
        ),
        call.stock_company(ts_code="600519.SH"),
        call.fina_mainbz(
            ts_code="600519.SH",
            type="P",
            start_date="20230527",
            end_date="20240630",
        ),
        call.forecast(
            ts_code="600519.SH",
            start_date="20230527",
            end_date="20240630",
        ),
        call.express(
            ts_code="600519.SH",
            start_date="20230527",
            end_date="20240630",
        ),
        call.income(
            ts_code="600519.SH",
            start_date="20230527",
            end_date="20240630",
        ),
    ]


@pytest.mark.parametrize(
    ("tool_name", "endpoint"),
    [
        ("get_balance_sheet", "balancesheet"),
        ("get_income_statement", "income"),
        ("get_cashflow", "cashflow"),
    ],
)
def test_tushare_statements_use_one_bounded_call_and_release_cutoff(
    monkeypatch, tool_name, endpoint
):
    pro = MagicMock()
    endpoint_mock = getattr(pro, endpoint)
    endpoint_mock.return_value = pd.DataFrame(
        [
            {"end_date": "20240331", "ann_date": "20240420", "marker": "valid"},
            {"end_date": "20240331", "ann_date": "20240701", "marker": "future"},
            {"end_date": "20231231", "ann_date": "", "marker": "blank"},
        ]
    )
    monkeypatch.setattr(tushare, "_get_pro_client", lambda: pro)

    out = getattr(tushare, tool_name)("600519.SH", "quarterly", "2024-06-30")

    endpoint_mock.assert_called_once_with(
        ts_code="600519.SH",
        start_date="20210628",
        end_date="20240630",
    )
    assert len(pro.method_calls) == 1
    assert "valid" in out
    assert "future" not in out
    assert "blank" not in out


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

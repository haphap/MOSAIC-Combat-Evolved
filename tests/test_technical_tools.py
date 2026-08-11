"""Tests for the price + technical-indicator @tool wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pandas as pd
import pytest

from mosaic.agents.utils import technical_tools as tt
from mosaic.dataflows import tushare


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


def test_tushare_indicator_uses_one_ticker_request_with_fixed_warmup(monkeypatch):
    pro = MagicMock()
    pro.daily.return_value = pd.DataFrame(
        [
            {
                "trade_date": "20240628",
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "vol": 100.0,
            }
        ]
    )
    monkeypatch.setattr(tushare, "_get_pro_client", lambda: pro)
    monkeypatch.setattr(tushare, "_render_indicator_frame", lambda *_args, **_kwargs: "MD")

    out = tushare.get_indicator("600519.SH", "rsi", "2024-06-30", 60)

    assert out == "MD"
    assert pro.method_calls == [
        call.daily(
            ts_code="600519.SH",
            start_date="20230502",
            end_date="20240630",
        )
    ]


def test_indicators_normalizes_common_llm_indicator_names(monkeypatch):
    cap = {}
    monkeypatch.setattr(tt, "route_to_vendor", lambda m, *a: cap.update(method=m, args=a) or "MD")
    tt.get_indicators.invoke({"symbol": "600519.SH", "indicator": "RSI", "curr_date": "2024-06-30"})
    assert cap["args"] == ("600519.SH", "rsi", "2024-06-30", 60)


def test_indicator_rejects_unknown_name_before_routing(monkeypatch):
    monkeypatch.setattr(tt, "route_to_vendor", lambda *a: "MD")
    with pytest.raises(ValueError, match="not supported"):
        tt.get_indicators.invoke(
            {"symbol": "600519.SH", "indicator": "not_an_indicator", "curr_date": "2024-06-30"}
        )


def test_module_exposed_via_bridge():
    import mosaic.bridge.handlers.tools as th

    names = {t.name for t in th._iter_module_tools("mosaic.agents.utils.technical_tools")}
    assert {"get_stock_data", "get_indicators"}.issubset(names)

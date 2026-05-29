"""Tests for ``mosaic.agents.utils.macro_tools``.

Covers:

* **Registration**  — every public tool in ``__all__`` is a LangChain
  ``BaseTool`` instance and is discoverable by the bridge's
  ``_iter_module_tools`` helper.
* **Schema**        — each tool surfaces a Pydantic v2 ``args_schema`` with
  the expected parameter names, types, and ``required`` markers; descriptions
  are non-empty.
* **Dispatch**      — ``.invoke(args)`` forwards into
  ``mosaic.dataflows.interface.route_to_vendor`` with the right positional
  arguments, and returns the underlying string verbatim.
* **Bridge handler** — ``tools.bridge.handlers.tools.tools_list`` /
  ``tools_call`` wire up correctly so the JSON-RPC endpoints exposed via
  ``python -m mosaic.bridge`` use the registered macro tools.
"""

from __future__ import annotations

import pytest
from langchain_core.tools import BaseTool

from mosaic.agents.utils import macro_tools
from mosaic.bridge.handlers import tools as tools_handler
from mosaic.bridge.protocol import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    TOOL_EXECUTION_ERROR,
    RpcError,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable


# --------------------------------------------------------------------- expected metadata


_EXPECTED_TOOLS = {
    "get_fred_series": {
        "required": {"series_id", "start_date", "end_date"},
        "optional": set(),
        "vendor_method": "get_fred_series",
    },
    "get_pboc_ops": {
        "required": {"curr_date"},
        "optional": {"look_back_days"},
        "vendor_method": "get_pboc_ops",
    },
    "get_north_capital_flow": {
        "required": {"start_date", "end_date"},
        "optional": set(),
        "vendor_method": "get_north_capital_flow",
    },
    "get_lhb_ranking": {
        "required": {"curr_date"},
        "optional": set(),
        "vendor_method": "get_lhb_ranking",
    },
    "get_yield_curve_cn": {
        "required": {"curr_date"},
        "optional": {"look_back_days"},
        "vendor_method": "get_yield_curve_cn",
    },
    "get_us_china_spread": {
        "required": {"curr_date"},
        "optional": {"look_back_days"},
        "vendor_method": "get_us_china_spread",
    },
    "get_xueqiu_heat": {
        "required": set(),
        "optional": {"ticker", "top_n"},
        "vendor_method": "get_xueqiu_heat",
    },
    "get_industry_policy": {
        "required": {"curr_date"},
        "optional": {"look_back_days", "src"},
        "vendor_method": "get_industry_policy",
    },
    "get_usdcny": {
        "required": {"curr_date"},
        "optional": {"look_back_days"},
        "vendor_method": "get_usdcny",
    },
    "get_commodity_prices": {
        "required": {"curr_date"},
        "optional": {"look_back_days"},
        "vendor_method": "get_commodity_prices",
    },
    "get_ivx": {
        "required": {"curr_date"},
        "optional": {"look_back_days"},
        "vendor_method": "get_ivx",
    },
    "get_etf_indicator": {
        "required": {"symbol", "curr_date"},
        "optional": {"look_back_days"},
        "vendor_method": "get_etf_indicator",
    },
    "get_fund_flow": {
        "required": {"symbol", "curr_date"},
        "optional": {"look_back_days"},
        "vendor_method": "get_fund_flow",
    },
    "get_etf_price_data": {
        "required": {"symbol", "start_date", "end_date"},
        "optional": set(),
        "vendor_method": "get_etf_price_data",
    },
}


# --------------------------------------------------------------------- registration


class TestRegistration:
    def test_each_export_is_basetool(self):
        for name in _EXPECTED_TOOLS:
            obj = getattr(macro_tools, name)
            assert isinstance(obj, BaseTool), f"{name} should be a langchain BaseTool"
            assert obj.name == name, f"{name}.name should equal the export name"

    def test_module_lists_all_tools_in_dunder_all(self):
        assert set(macro_tools.__all__) == set(_EXPECTED_TOOLS)

    def test_bridge_iter_finds_all_tools(self):
        names = sorted(
            t.name for t in tools_handler._iter_module_tools(
                "mosaic.agents.utils.macro_tools"
            )
        )
        assert names == sorted(_EXPECTED_TOOLS)

    def test_tool_modules_includes_macro_tools(self):
        assert "mosaic.agents.utils.macro_tools" in tools_handler._TOOL_MODULES


# --------------------------------------------------------------------- schemas


class TestSchemas:
    @pytest.mark.parametrize("name", sorted(_EXPECTED_TOOLS))
    def test_args_schema_has_expected_properties(self, name):
        spec = _EXPECTED_TOOLS[name]
        tool_obj = getattr(macro_tools, name)
        schema = tool_obj.args_schema.model_json_schema()
        properties = set(schema.get("properties", {}).keys())
        assert spec["required"] | spec["optional"] == properties, (
            f"{name} schema properties mismatch: expected "
            f"{spec['required'] | spec['optional']}, got {properties}"
        )

    @pytest.mark.parametrize("name", sorted(_EXPECTED_TOOLS))
    def test_required_set_matches(self, name):
        spec = _EXPECTED_TOOLS[name]
        tool_obj = getattr(macro_tools, name)
        schema = tool_obj.args_schema.model_json_schema()
        required = set(schema.get("required", []))
        assert required == spec["required"]

    @pytest.mark.parametrize("name", sorted(_EXPECTED_TOOLS))
    def test_descriptions_are_non_empty(self, name):
        tool_obj = getattr(macro_tools, name)
        assert tool_obj.description.strip(), f"{name} should have a description"
        # Each Annotated parameter should expose its description, not just the
        # auto-generated title.
        schema = tool_obj.args_schema.model_json_schema()
        for prop_name, prop in schema.get("properties", {}).items():
            assert prop.get("description"), (
                f"{name}.{prop_name} missing description annotation"
            )


# --------------------------------------------------------------------- dispatch


class TestDispatch:
    """``.invoke(args)`` routes through route_to_vendor with positional args."""

    @pytest.fixture
    def patched_route(self, monkeypatch):
        captured = {}

        def _fake(method, *args, **kwargs):
            captured["method"] = method
            captured["args"] = args
            captured["kwargs"] = kwargs
            return f"<{method} response>"

        monkeypatch.setattr(macro_tools, "route_to_vendor", _fake)
        return captured

    def test_get_fred_series_invocation(self, patched_route):
        out = macro_tools.get_fred_series.invoke(
            {"series_id": "FEDFUNDS", "start_date": "2024-01-01", "end_date": "2024-06-30"}
        )
        assert out == "<get_fred_series response>"
        assert patched_route["method"] == "get_fred_series"
        assert patched_route["args"] == ("FEDFUNDS", "2024-01-01", "2024-06-30")

    def test_get_pboc_ops_with_default_lookback(self, patched_route):
        macro_tools.get_pboc_ops.invoke({"curr_date": "2024-06-30"})
        assert patched_route["method"] == "get_pboc_ops"
        assert patched_route["args"] == ("2024-06-30", 7)

    def test_get_pboc_ops_overrides_lookback(self, patched_route):
        macro_tools.get_pboc_ops.invoke(
            {"curr_date": "2024-06-30", "look_back_days": 14}
        )
        assert patched_route["args"] == ("2024-06-30", 14)

    def test_get_north_capital_flow_invocation(self, patched_route):
        macro_tools.get_north_capital_flow.invoke(
            {"start_date": "2024-06-24", "end_date": "2024-06-28"}
        )
        assert patched_route["args"] == ("2024-06-24", "2024-06-28")

    def test_get_lhb_ranking_invocation(self, patched_route):
        macro_tools.get_lhb_ranking.invoke({"curr_date": "2024-06-28"})
        assert patched_route["args"] == ("2024-06-28",)

    def test_get_yield_curve_cn_invocation(self, patched_route):
        macro_tools.get_yield_curve_cn.invoke(
            {"curr_date": "2024-06-30", "look_back_days": 60}
        )
        assert patched_route["args"] == ("2024-06-30", 60)

    def test_get_us_china_spread_invocation(self, patched_route):
        macro_tools.get_us_china_spread.invoke({"curr_date": "2024-06-30"})
        assert patched_route["args"] == ("2024-06-30", 30)

    def test_get_xueqiu_heat_no_args(self, patched_route):
        macro_tools.get_xueqiu_heat.invoke({})
        assert patched_route["args"] == (None, 30)

    def test_get_xueqiu_heat_with_ticker(self, patched_route):
        macro_tools.get_xueqiu_heat.invoke({"ticker": "600519.SH", "top_n": 5})
        assert patched_route["args"] == ("600519.SH", 5)

    def test_get_industry_policy_invocation(self, patched_route):
        macro_tools.get_industry_policy.invoke(
            {"curr_date": "2024-06-30", "look_back_days": 14, "src": "wallstreetcn"}
        )
        assert patched_route["args"] == ("2024-06-30", 14, "wallstreetcn")

    def test_get_usdcny_invocation(self, patched_route):
        macro_tools.get_usdcny.invoke({"curr_date": "2024-06-30"})
        assert patched_route["method"] == "get_usdcny"
        assert patched_route["args"] == ("2024-06-30", 30)

    def test_get_commodity_prices_invocation(self, patched_route):
        macro_tools.get_commodity_prices.invoke({"curr_date": "2024-06-30", "look_back_days": 60})
        assert patched_route["args"] == ("2024-06-30", 60)

    def test_get_ivx_invocation(self, patched_route):
        macro_tools.get_ivx.invoke({"curr_date": "2024-06-30"})
        assert patched_route["args"] == ("2024-06-30", 30)

    def test_get_etf_indicator_invocation(self, patched_route):
        macro_tools.get_etf_indicator.invoke({"symbol": "510050.SH", "curr_date": "2024-06-30"})
        assert patched_route["args"] == ("510050.SH", "2024-06-30", 30)

    def test_get_fund_flow_invocation(self, patched_route):
        macro_tools.get_fund_flow.invoke(
            {"symbol": "510300.SH", "curr_date": "2024-06-30", "look_back_days": 5}
        )
        assert patched_route["args"] == ("510300.SH", "2024-06-30", 5)

    def test_get_etf_price_data_invocation(self, patched_route):
        macro_tools.get_etf_price_data.invoke(
            {"symbol": "510300.SH", "start_date": "2024-06-01", "end_date": "2024-06-30"}
        )
        assert patched_route["method"] == "get_etf_price_data"
        assert patched_route["args"] == ("510300.SH", "2024-06-01", "2024-06-30")


# --------------------------------------------------------------------- bridge handler


class TestBridgeHandler:
    """Exercise ``tools.list`` / ``tools.call`` JSON-RPC handlers in-process."""

    def test_tools_list_returns_eight(self):
        result = tools_handler.tools_list({})
        assert isinstance(result, list)
        names = sorted(t["name"] for t in result)
        assert names == sorted(_EXPECTED_TOOLS)
        for entry in result:
            assert entry["description"]
            assert entry["args_schema"]["type"] == "object"

    def test_tools_call_dispatches_through_route(self, monkeypatch):
        # Patch route_to_vendor at the macro_tools module level — that's the
        # symbol the @tool wrappers actually call.
        captured = {}

        def _fake(method, *args, **kwargs):
            captured.setdefault("calls", []).append((method, args, kwargs))
            return "<spread CSV body>"

        monkeypatch.setattr(macro_tools, "route_to_vendor", _fake)

        result = tools_handler.tools_call(
            {
                "name": "get_us_china_spread",
                "args": {"curr_date": "2024-06-30", "look_back_days": 5},
            }
        )

        assert result == {"text": "<spread CSV body>"}
        assert captured["calls"] == [
            ("get_us_china_spread", ("2024-06-30", 5), {})
        ]

    def test_tools_call_unknown_name(self):
        with pytest.raises(RpcError) as exc:
            tools_handler.tools_call({"name": "no_such_tool"})
        assert exc.value.code == METHOD_NOT_FOUND

    def test_tools_call_invalid_args_type(self):
        with pytest.raises(RpcError) as exc:
            tools_handler.tools_call(
                {"name": "get_fred_series", "args": "not a dict"}
            )
        assert exc.value.code == INVALID_PARAMS

    def test_tools_call_underlying_failure_wraps(self, monkeypatch):
        def _raise(*_args, **_kwargs):
            raise DataVendorUnavailable("FRED_API_KEY is not set.")

        monkeypatch.setattr(macro_tools, "route_to_vendor", _raise)

        with pytest.raises(RpcError) as exc:
            tools_handler.tools_call(
                {
                    "name": "get_fred_series",
                    "args": {"series_id": "FEDFUNDS", "start_date": "2024-01-01", "end_date": "2024-06-30"},
                }
            )
        # tools_call catches DataVendorUnavailable explicitly
        from mosaic.bridge.protocol import DATA_VENDOR_UNAVAILABLE

        assert exc.value.code == DATA_VENDOR_UNAVAILABLE

    def test_tools_call_missing_required_arg(self, monkeypatch):
        # When the @tool wrapper validation fails, langchain raises a ValueError
        # inside .invoke; tools_call wraps it in TOOL_EXECUTION_ERROR.
        # Pre-patch route to ensure we don't actually hit it on accident.
        monkeypatch.setattr(macro_tools, "route_to_vendor", lambda *a, **k: "")

        with pytest.raises(RpcError) as exc:
            tools_handler.tools_call(
                {"name": "get_fred_series", "args": {"series_id": "FEDFUNDS"}}
            )
        # Either INVALID_PARAMS-mapped or TOOL_EXECUTION_ERROR depending on
        # langchain version; both indicate the schema rejected the call.
        assert exc.value.code in (TOOL_EXECUTION_ERROR, INVALID_PARAMS)

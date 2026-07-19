"""Model-tool security and v2 Macro snapshot routing tests."""

from __future__ import annotations

import pytest

from mosaic.bridge.handlers import tools as tools_handler
from mosaic.bridge.protocol import INVALID_PARAMS, METHOD_NOT_FOUND, RpcError
from mosaic.bridge.tool_capabilities import (
    AGENT_TOOL_MATRIX,
    MACRO_AGENT_TO_TOOL,
    TOOL_DESCRIPTIONS,
    materialize_tool_payload,
)


def test_bridge_does_not_register_arbitrary_query_tool_modules():
    assert tools_handler._TOOL_MODULES == ()
    with pytest.raises(RpcError) as exc:
        tools_handler.tools_list({})
    assert exc.value.code == INVALID_PARAMS
    assert "capability" in exc.value.message


def test_macro_matrix_has_one_role_snapshot_and_no_legacy_or_search_tools():
    assert len(MACRO_AGENT_TO_TOOL) == 10
    for agent, tool_id in MACRO_AGENT_TO_TOOL.items():
        assert AGENT_TOOL_MATRIX[agent] == (tool_id,)
        assert tool_id in TOOL_DESCRIPTIONS
    forbidden = {
        "get_fred_series",
        "get_news",
        "get_xueqiu_heat",
        "get_caixin_sentiment",
        "get_rates_credit_snapshot",
        "get_fx_conditions_snapshot",
        "get_volatility_snapshot",
        "get_rke_research_context",
    }
    assert forbidden.isdisjoint(TOOL_DESCRIPTIONS)


@pytest.mark.parametrize(
    ("tool_id", "agent"),
    list((tool_id, agent) for agent, tool_id in MACRO_AGENT_TO_TOOL.items()),
)
def test_macro_materializer_uses_bound_role_and_as_of(monkeypatch, tool_id, agent):
    captured = {}

    def fake_render(role: str, as_of: str) -> str:
        captured["role"] = role
        captured["as_of"] = as_of
        return "frozen-role-snapshot"

    def fake_breadth(as_of: str) -> str:
        captured["role"] = "market_breadth"
        captured["as_of"] = as_of
        return "frozen-breadth-snapshot"

    monkeypatch.setattr(
        "mosaic.bridge.tool_capabilities.render_role_snapshot",
        fake_render,
    )
    monkeypatch.setattr(
        "mosaic.bridge.tool_capabilities.render_market_breadth_snapshot",
        fake_breadth,
    )
    result = materialize_tool_payload(
        tool_id,
        agent_id=agent,
        stage=agent,
        as_of="2026-07-09",
    )
    assert result.startswith("frozen-")
    assert captured == {"role": agent, "as_of": "2026-07-09"}


def test_macro_materializer_rejects_cross_role_use():
    with pytest.raises(ValueError, match="cannot be materialised"):
        materialize_tool_payload(
            "get_china_macro_snapshot",
            agent_id="us_economy",
            stage="us_economy",
            as_of="2026-07-09",
        )


class _FakeCapabilityStore:
    def __init__(self):
        self.calls = []

    def prepare(self, params):
        self.calls.append(("prepare", params))
        return {"bundle": {"snapshot_bundle_id": "bundle"}, "capability": {"manifest": {}}}

    def list_tools(self, capability):
        self.calls.append(("list", capability))
        return [
            {
                "name": "get_china_macro_snapshot",
                "description": "frozen",
                "args_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            }
        ]

    def call_tool(self, capability, name, args):
        self.calls.append(("call", capability, name, args))
        if name != "get_china_macro_snapshot":
            raise ValueError(f"tool {name!r} is not allowed by this capability")
        if args:
            raise ValueError("role-scoped model tools accept no arguments")
        return "frozen payload"

    def terminate(self, capability, reason):
        self.calls.append(("terminate", capability, reason))


def test_bridge_handlers_delegate_only_with_signed_capability(monkeypatch):
    store = _FakeCapabilityStore()
    monkeypatch.setattr(tools_handler, "get_capability_store", lambda: store)
    capability = {"manifest": {}, "signing_key_id": "key", "signature": "sig"}

    prepared = tools_handler.tools_prepare_capability({"agent_id": "china"})
    assert prepared["bundle"]["snapshot_bundle_id"] == "bundle"
    listed = tools_handler.tools_list({"capability": capability})
    assert listed[0]["args_schema"]["properties"] == {}
    assert tools_handler.tools_call(
        {"capability": capability, "name": "get_china_macro_snapshot", "args": {}}
    ) == {"text": "frozen payload"}
    assert tools_handler.tools_terminate_capability(
        {"capability": capability, "reason": "node_finished"}
    ) == {"terminated": True}

    with pytest.raises(RpcError) as exc:
        tools_handler.tools_call(
            {"capability": capability, "name": "get_news", "args": {}}
        )
    assert exc.value.code == METHOD_NOT_FOUND
    with pytest.raises(RpcError) as exc:
        tools_handler.tools_call(
            {
                "capability": capability,
                "name": "get_china_macro_snapshot",
                "args": {"as_of_date": "2099-01-01"},
            }
        )
    assert exc.value.code == INVALID_PARAMS

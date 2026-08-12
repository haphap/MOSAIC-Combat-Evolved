from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.rke.schema_validation import validate_json_schema_artifact
from mosaic.scorecard.canonical_json import canonical_hash, canonical_json
from mosaic.scorecard.l1_l2_activation import (
    build_l1_l2_active_route_manifest,
    build_l1_l2_active_tool_manifest,
)
from mosaic.scorecard.l3_l4_activation import (
    active_stage_for_l3_l4_overlay,
    build_l3_l4_active_route_manifest,
    build_l3_l4_active_tool_manifest,
    l3_l4_overlay_stage_for_active,
    validate_l3_l4_active_fixed_point,
)


ROOT = Path(__file__).parents[1]
PRESERVATION_ROOT = ROOT / "registry/prompt_checks/capability_preservation"


def _load(name: str) -> dict:
    return json.loads((PRESERVATION_ROOT / name).read_text(encoding="utf-8"))


def _surface(manifest: dict) -> set[tuple[str, str, str]]:
    return {
        (agent["agent_id"], stage, tool_id)
        for agent in manifest["agents"]
        for stage in agent["execution_stages"]
        for tool_id in agent["allowed_tools"]
    }


def test_l3_l4_activation_adds_exact_overlay_bindings_without_roster_drift() -> None:
    base_tools = build_l1_l2_active_tool_manifest(ROOT)
    active_tools = build_l3_l4_active_tool_manifest(ROOT)
    overlay = _load("l3_l4_preservation_overlay_v1.json")

    assert active_tools["agent_count"] == 27
    assert active_tools["execution_stage_count"] == 28
    assert _surface(base_tools) < _surface(active_tools)
    expected_additions = {
        (
            row["agent_id"],
            active_stage_for_l3_l4_overlay(row["agent_id"], row["stage"]),
            row["tool_id"],
        )
        for row in overlay["bindings"]
    }
    assert _surface(active_tools) - _surface(base_tools) == expected_additions
    assert len(expected_additions) == 33


def test_live_active_tool_manifest_is_schema_valid() -> None:
    result = validate_json_schema_artifact(
        root=ROOT,
        schema_path="schemas/agent_tool_contract_manifest_v1.schema.json",
        artifact_path="registry/prompt_checks/agent_tool_contract_manifest_v1.json",
        artifact_kind="json",
    )
    assert result.accepted, result.failures


def test_live_manifests_are_the_l3_l4_fixed_point() -> None:
    expected_tools = build_l3_l4_active_tool_manifest(ROOT)
    expected_routes = build_l3_l4_active_route_manifest(
        ROOT,
        active_tool_manifest=expected_tools,
    )
    live_tools = json.loads(
        (ROOT / "registry/prompt_checks/agent_tool_contract_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    live_routes = json.loads(
        (ROOT / "registry/data_sources/agent_data_route_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert expected_routes["manifest_version"] == "agent_data_routes_20260812_v1"
    assert canonical_json(live_tools) == canonical_json(expected_tools)
    assert canonical_json(live_routes) == canonical_json(expected_routes)


def test_l3_l4_active_route_manifest_closes_exact_tool_surface() -> None:
    base_routes = build_l1_l2_active_route_manifest(ROOT)
    active_tools = build_l3_l4_active_tool_manifest(ROOT)
    active_routes = build_l3_l4_active_route_manifest(
        ROOT,
        active_tool_manifest=active_tools,
    )

    assert {
        (row["agent_id"], row["stage"], row["tool_id"])
        for row in base_routes["bindings"]
    } < {
        (row["agent_id"], row["stage"], row["tool_id"])
        for row in active_routes["bindings"]
    }
    assert {
        (row["agent_id"], row["stage"], row["tool_id"])
        for row in active_routes["bindings"]
    } == _surface(active_tools)
    assert active_routes["agent_tool_contract_manifest_hash"] == canonical_hash(
        active_tools
    )
    assert active_routes["manifest_hash"] == canonical_hash(
        {key: value for key, value in active_routes.items() if key != "manifest_hash"}
    )
    route_by_id = {row["route_id"]: row for row in active_routes["routes"]}
    binding_by_key = {
        (row["agent_id"], row["stage"], row["tool_id"]): row
        for row in active_routes["bindings"]
    }
    assert binding_by_key[
        ("druckenmiller", "druckenmiller", "get_yield_curve_cn")
    ]["required_route_ids"] == ["composite.cn_rates"]
    assert "tushare.shibor_yield_curve" not in route_by_id
    assert route_by_id["composite.cn_rates"] == {
        "route_id": "composite.cn_rates",
        "source_family": "composite",
        "contract_version": "composite_cn_rates_mof_chinabond_v1",
        "pit_strategy": "OBSERVED_LIVE",
        "implementation_stage": "PR15",
    }
    assert set(route_by_id) == {
        route_id
        for binding in active_routes["bindings"]
        for route_id in binding["required_route_ids"]
    }
    validate_l3_l4_active_fixed_point(
        ROOT,
        active_tool_manifest=active_tools,
        active_route_manifest=active_routes,
    )


def test_l3_l4_overlay_stage_translation_is_exact_and_fail_closed() -> None:
    assert active_stage_for_l3_l4_overlay("cro", "cro_review") == "cro"
    assert (
        active_stage_for_l3_l4_overlay(
            "autonomous_execution", "execution_feasibility"
        )
        == "autonomous_execution"
    )
    assert active_stage_for_l3_l4_overlay("cio", "cio_final") == "cio_final"
    assert l3_l4_overlay_stage_for_active("cro", "cro") == "cro_review"
    assert (
        l3_l4_overlay_stage_for_active(
            "autonomous_execution", "autonomous_execution"
        )
        == "execution_feasibility"
    )
    with pytest.raises(ValueError, match="unknown L3/L4 overlay stage"):
        active_stage_for_l3_l4_overlay("cro", "execution_feasibility")
    with pytest.raises(ValueError, match="unknown active L3/L4 stage"):
        l3_l4_overlay_stage_for_active("cro", "cro_review")

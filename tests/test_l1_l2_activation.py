from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l1_l2_activation import (
    build_l1_l2_active_route_manifest,
    build_l1_l2_active_tool_manifest,
    validate_l1_l2_active_fixed_point,
    write_l1_l2_active_manifests,
)
from mosaic.scorecard.l3_l4_preservation import validate_l3_l4_preservation_overlay
from mosaic.scorecard.macro_europe_preservation import (
    validate_macro_europe_preservation_overlay,
)
from mosaic.scorecard.macro_us_preservation import validate_macro_us_preservation_overlay
from mosaic.scorecard.sector_relationship_preservation import (
    validate_sector_relationship_preservation_overlay,
)


ROOT = Path(__file__).parents[1]
PRESERVATION_ROOT = ROOT / "registry/prompt_checks/capability_preservation"
BASE_ROUTE_SNAPSHOT = (
    PRESERVATION_ROOT / "current_agent_data_route_manifest_snapshot_v1.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _surface(manifest: dict) -> set[tuple[str, str, str]]:
    return {
        (agent["agent_id"], stage, tool_id)
        for agent in manifest["agents"]
        for stage in agent["execution_stages"]
        for tool_id in agent["allowed_tools"]
    }


def test_l1_l2_tool_activation_is_exact_base_union_pr6_overlay() -> None:
    base = _load(PRESERVATION_ROOT / "current_agent_tool_contract_snapshot_v1.json")
    overlay = _load(PRESERVATION_ROOT / "sector_relationship_preservation_overlay_v1.json")
    base_routes = _load(BASE_ROUTE_SNAPSHOT)
    active = build_l1_l2_active_tool_manifest(ROOT)

    assert active["agent_count"] == base["agent_count"] == 28
    assert active["execution_stage_count"] == base["execution_stage_count"] == 29
    assert active["tool_count"] == 31
    assert overlay["activation_state"] == "staged"
    assert overlay["base_agent_data_route_manifest_hash"] == canonical_hash(base_routes)

    base_by_agent = {row["agent_id"]: row for row in base["agents"]}
    active_by_agent = {row["agent_id"]: row for row in active["agents"]}
    restored_by_agent: dict[str, set[str]] = {}
    for binding in overlay["bindings"]:
        restored_by_agent.setdefault(binding["agent_id"], set()).add(
            binding["tool_id"]
        )

    assert set(restored_by_agent) == {
        "agriculture",
        "biotech",
        "consumer",
        "energy",
        "financials",
        "industrials",
        "real_estate_construction",
        "relationship_mapper",
        "semiconductor",
        "technology",
    }
    for agent_id, base_row in base_by_agent.items():
        expected = [
            *base_row["allowed_tools"],
            *sorted(restored_by_agent.get(agent_id, set())),
        ]
        assert active_by_agent[agent_id]["allowed_tools"] == expected
        assert active_by_agent[agent_id]["layer"] == base_row["layer"]
        assert active_by_agent[agent_id]["execution_stages"] == base_row[
            "execution_stages"
        ]

    added_surface = _surface(active) - _surface(base)
    assert added_surface == {
        (binding["agent_id"], binding["stage"], binding["tool_id"])
        for binding in overlay["bindings"]
    }


def test_l1_l2_route_activation_exactly_closes_the_new_tool_surface() -> None:
    active_tools = build_l1_l2_active_tool_manifest(ROOT)
    active_routes = build_l1_l2_active_route_manifest(
        ROOT, active_tool_manifest=active_tools
    )

    assert active_routes["agent_tool_contract_manifest_hash"] == canonical_hash(
        active_tools
    )
    assert active_routes["manifest_hash"] == canonical_hash(
        {
            key: value
            for key, value in active_routes.items()
            if key != "manifest_hash"
        }
    )
    assert {
        (row["agent_id"], row["stage"], row["tool_id"])
        for row in active_routes["bindings"]
    } == _surface(active_tools)

    overlay = _load(PRESERVATION_ROOT / "sector_relationship_preservation_overlay_v1.json")
    route_by_id = {row["route_id"]: row for row in active_routes["routes"]}
    for row in overlay["routes"]:
        assert route_by_id[row["route_id"]] == row
    for binding in overlay["bindings"]:
        assert {
            "agent_id": binding["agent_id"],
            "stage": binding["stage"],
            "tool_id": binding["tool_id"],
            "required_route_ids": binding["source_route_ids"],
        } in active_routes["bindings"]


def test_l1_l2_fixed_point_rejects_half_switch_and_self_resealed_drift() -> None:
    base_tools = _load(PRESERVATION_ROOT / "current_agent_tool_contract_snapshot_v1.json")
    base_routes = _load(BASE_ROUTE_SNAPSHOT)
    active_tools = build_l1_l2_active_tool_manifest(ROOT)
    active_routes = build_l1_l2_active_route_manifest(
        ROOT, active_tool_manifest=active_tools
    )
    validate_l1_l2_active_fixed_point(
        ROOT,
        active_tool_manifest=active_tools,
        active_route_manifest=active_routes,
    )

    with pytest.raises(ValueError, match="active tool manifest"):
        validate_l1_l2_active_fixed_point(
            ROOT,
            active_tool_manifest=base_tools,
            active_route_manifest=active_routes,
        )
    with pytest.raises(ValueError, match="active route manifest"):
        validate_l1_l2_active_fixed_point(
            ROOT,
            active_tool_manifest=active_tools,
            active_route_manifest=base_routes,
        )

    missing = copy.deepcopy(active_routes)
    missing["bindings"].pop()
    body = {key: value for key, value in missing.items() if key != "manifest_hash"}
    missing["manifest_hash"] = canonical_hash(body)
    with pytest.raises(ValueError, match="active route manifest"):
        validate_l1_l2_active_fixed_point(
            ROOT,
            active_tool_manifest=active_tools,
            active_route_manifest=missing,
        )


def test_live_manifests_preserve_the_l1_l2_fixed_point() -> None:
    expected_tools = build_l1_l2_active_tool_manifest(ROOT)
    expected_routes = build_l1_l2_active_route_manifest(
        ROOT, active_tool_manifest=expected_tools
    )
    live_tools = _load(
        ROOT / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
    )
    live_routes = _load(
        ROOT / "registry/data_sources/agent_data_route_manifest_v1.json"
    )

    assert _surface(expected_tools) <= _surface(live_tools)
    assert {canonical_hash(row) for row in expected_routes["bindings"]} <= {
        canonical_hash(row) for row in live_routes["bindings"]
    }


def test_writer_publishes_both_active_manifests_from_frozen_inputs(
    tmp_path: Path,
) -> None:
    shutil.copytree(ROOT / "registry", tmp_path / "registry")
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")

    written = write_l1_l2_active_manifests(tmp_path)

    assert written == {
        "route_manifest": (
            tmp_path / "registry/data_sources/agent_data_route_manifest_v1.json"
        ),
        "tool_manifest": (
            tmp_path / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
        ),
    }
    validate_l1_l2_active_fixed_point(
        tmp_path,
        active_tool_manifest=_load(written["tool_manifest"]),
        active_route_manifest=_load(written["route_manifest"]),
    )


def test_staged_overlays_remain_bound_to_frozen_base_after_active_switch(
    tmp_path: Path,
) -> None:
    shutil.copytree(ROOT / "registry", tmp_path / "registry")
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")
    active_tools = build_l1_l2_active_tool_manifest(ROOT)
    active_routes = build_l1_l2_active_route_manifest(
        ROOT, active_tool_manifest=active_tools
    )
    live_tool_path = (
        tmp_path / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
    )
    live_route_path = tmp_path / "registry/data_sources/agent_data_route_manifest_v1.json"
    live_tool_path.write_text(json.dumps(active_tools), encoding="utf-8")
    live_route_path.write_text(json.dumps(active_routes), encoding="utf-8")

    overlay_root = tmp_path / "registry/prompt_checks/capability_preservation"
    validators = (
        (
            "sector_relationship_preservation_overlay_v1.json",
            validate_sector_relationship_preservation_overlay,
        ),
        ("l3_l4_preservation_overlay_v1.json", validate_l3_l4_preservation_overlay),
        ("macro_us_preservation_overlay_v1.json", validate_macro_us_preservation_overlay),
        (
            "macro_europe_preservation_overlay_v1.json",
            validate_macro_europe_preservation_overlay,
        ),
    )
    for name, validator in validators:
        validator(_load(overlay_root / name), root=tmp_path)

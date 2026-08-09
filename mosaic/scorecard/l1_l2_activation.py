"""Deterministic PR12 activation of the frozen L1/L2 tool and route surface."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mosaic.scorecard.canonical_json import canonical_hash, canonical_json
from mosaic.scorecard.preservation_snapshots import (
    load_preactivation_agent_manifests,
)
from mosaic.scorecard.sector_relationship_preservation import (
    validate_sector_relationship_preservation_overlay,
)


_PRESERVATION_DIRECTORY = Path("registry/prompt_checks/capability_preservation")
_OVERLAY = "sector_relationship_preservation_overlay_v1.json"
_ACTIVE_TOOL_MANIFEST = Path(
    "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
)
_ACTIVE_ROUTE_MANIFEST = Path(
    "registry/data_sources/agent_data_route_manifest_v1.json"
)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(canonical_json(value))


def _tool_surface(manifest: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    agents = manifest.get("agents")
    if not isinstance(agents, list):
        raise ValueError("Agent tool manifest agents must be an array")
    surface: set[tuple[str, str, str]] = set()
    for agent in agents:
        if not isinstance(agent, Mapping):
            raise ValueError("Agent tool manifest row must be an object")
        agent_id = str(agent.get("agent_id", ""))
        stages = agent.get("execution_stages")
        tools = agent.get("allowed_tools")
        if (
            not agent_id
            or not isinstance(stages, list)
            or not stages
            or not isinstance(tools, list)
            or not tools
        ):
            raise ValueError("Agent tool manifest row is incomplete")
        for stage in stages:
            for tool_id in tools:
                key = (agent_id, str(stage), str(tool_id))
                if key in surface:
                    raise ValueError("Agent tool manifest surface contains duplicates")
                surface.add(key)
    return surface


def _load_inputs(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = root / _PRESERVATION_DIRECTORY
    base, _ = load_preactivation_agent_manifests(root)
    overlay = _read_object(directory / _OVERLAY)
    validate_sector_relationship_preservation_overlay(overlay, root=root)
    if overlay.get("base_active_agent_tool_manifest_hash") != canonical_hash(base):
        raise ValueError("PR6 overlay base active Agent tool manifest drift")
    return base, overlay


def build_l1_l2_active_tool_manifest(root: Path) -> dict[str, Any]:
    """Return the exact pre-activation surface plus the 70 PR6 bindings."""

    base, overlay = _load_inputs(root)
    restored_by_agent: dict[str, set[str]] = {}
    for binding in overlay["bindings"]:
        agent_id = str(binding["agent_id"])
        stage = str(binding["stage"])
        if stage != agent_id:
            raise ValueError("PR6 restored binding stage differs from its Agent")
        restored_by_agent.setdefault(agent_id, set()).add(str(binding["tool_id"]))

    agents: list[dict[str, Any]] = []
    known_agents: set[str] = set()
    for source in base["agents"]:
        row = _copy(source)
        agent_id = str(row["agent_id"])
        if agent_id in known_agents:
            raise ValueError("base Agent tool manifest contains duplicate agents")
        known_agents.add(agent_id)
        restored = sorted(restored_by_agent.get(agent_id, set()))
        overlap = set(row["allowed_tools"]) & set(restored)
        if overlap:
            raise ValueError(
                f"PR6 restored tools already exist in the base active surface: {sorted(overlap)}"
            )
        row["allowed_tools"] = [*row["allowed_tools"], *restored]
        agents.append(row)
    if set(restored_by_agent) - known_agents:
        raise ValueError("PR6 overlay references an unknown current Agent")

    tools = {
        tool_id for agent in agents for tool_id in agent["allowed_tools"]
    }
    body = {
        "schema_version": base["schema_version"],
        "agent_count": len(agents),
        "execution_stage_count": sum(
            len(agent["execution_stages"]) for agent in agents
        ),
        "tool_count": len(tools),
        "agents": agents,
    }
    _tool_surface(body)
    if body["agent_count"] != base["agent_count"] or body[
        "execution_stage_count"
    ] != base["execution_stage_count"]:
        raise ValueError("L1/L2 activation changed the Agent or stage roster")
    return body


def _project_base_route_manifest(
    root: Path, base_tool_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    _, current = load_preactivation_agent_manifests(root)
    base_surface = _tool_surface(base_tool_manifest)
    bindings = [_copy(row) for row in current.get("bindings", [])]
    if {
        (row["agent_id"], row["stage"], row["tool_id"]) for row in bindings
    } != base_surface:
        raise ValueError("frozen base route manifest does not close its tool surface")
    route_ids = {
        route_id for binding in bindings for route_id in binding["required_route_ids"]
    }
    routes = [_copy(row) for row in current.get("routes", [])]
    if {row["route_id"] for row in routes} != route_ids:
        raise ValueError("frozen base route manifest contains orphan or missing routes")
    if current.get("agent_tool_contract_manifest_hash") != canonical_hash(
        base_tool_manifest
    ):
        raise ValueError("frozen base route manifest tool hash drift")
    body = {key: value for key, value in current.items() if key != "manifest_hash"}
    if current.get("manifest_hash") != canonical_hash(body):
        raise ValueError("frozen base route manifest hash mismatch")
    return current


def build_l1_l2_active_route_manifest(
    root: Path,
    *,
    active_tool_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge the base route surface with exact PR6 binding route requirements."""

    base, overlay = _load_inputs(root)
    expected_tools = build_l1_l2_active_tool_manifest(root)
    active = _copy(active_tool_manifest or expected_tools)
    if canonical_json(active) != canonical_json(expected_tools):
        raise ValueError("active tool manifest does not equal the PR12 fixed point")
    base_routes = _project_base_route_manifest(root, base)
    if overlay.get("base_agent_data_route_manifest_hash") != canonical_hash(base_routes):
        raise ValueError("PR6 overlay base Agent data route manifest drift")

    route_by_id = {row["route_id"]: _copy(row) for row in base_routes["routes"]}
    for source in overlay["routes"]:
        row = _copy(source)
        route_id = str(row["route_id"])
        existing = route_by_id.get(route_id)
        if existing is not None and canonical_json(existing) != canonical_json(row):
            raise ValueError(f"PR6 route {route_id} conflicts with the base route")
        route_by_id[route_id] = row

    binding_by_key = {
        (row["agent_id"], row["stage"], row["tool_id"]): _copy(row)
        for row in base_routes["bindings"]
    }
    if len(binding_by_key) != len(base_routes["bindings"]):
        raise ValueError("base route manifest contains duplicate bindings")
    for source in overlay["bindings"]:
        key = (source["agent_id"], source["stage"], source["tool_id"])
        if key in binding_by_key:
            raise ValueError("PR6 restored route binding overlaps the base surface")
        binding_by_key[key] = {
            "agent_id": source["agent_id"],
            "stage": source["stage"],
            "tool_id": source["tool_id"],
            "required_route_ids": list(source["source_route_ids"]),
        }

    expected_order = [
        (agent["agent_id"], stage, tool_id)
        for agent in active["agents"]
        for stage in agent["execution_stages"]
        for tool_id in sorted(agent["allowed_tools"])
    ]
    if set(binding_by_key) != set(expected_order):
        raise ValueError("active route binding surface does not close the active tools")

    body = {
        key: value
        for key, value in base_routes.items()
        if key
        not in {
            "agent_tool_contract_manifest_hash",
            "bindings",
            "manifest_hash",
            "routes",
        }
    }
    body.update(
        {
            "agent_tool_contract_manifest_hash": canonical_hash(active),
            "routes": [route_by_id[key] for key in sorted(route_by_id)],
            "bindings": [binding_by_key[key] for key in expected_order],
        }
    )
    return {**body, "manifest_hash": canonical_hash(body)}


def validate_l1_l2_active_fixed_point(
    root: Path,
    *,
    active_tool_manifest: Mapping[str, Any],
    active_route_manifest: Mapping[str, Any],
) -> None:
    expected_tools = build_l1_l2_active_tool_manifest(root)
    if canonical_json(active_tool_manifest) != canonical_json(expected_tools):
        raise ValueError("active tool manifest does not equal the PR12 fixed point")
    expected_routes = build_l1_l2_active_route_manifest(
        root, active_tool_manifest=expected_tools
    )
    if canonical_json(active_route_manifest) != canonical_json(expected_routes):
        raise ValueError("active route manifest does not equal the PR12 fixed point")


def _stage_manifest(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    staged = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        staged.unlink(missing_ok=True)
        raise
    return staged


def write_l1_l2_active_manifests(root: Path) -> dict[str, Path]:
    """Build, validate, and fail-closed publish the two active manifests."""

    resolved_root = root.resolve()
    tool_manifest = build_l1_l2_active_tool_manifest(resolved_root)
    route_manifest = build_l1_l2_active_route_manifest(
        resolved_root, active_tool_manifest=tool_manifest
    )
    validate_l1_l2_active_fixed_point(
        resolved_root,
        active_tool_manifest=tool_manifest,
        active_route_manifest=route_manifest,
    )
    tool_path = resolved_root / _ACTIVE_TOOL_MANIFEST
    route_path = resolved_root / _ACTIVE_ROUTE_MANIFEST
    staged_tool = _stage_manifest(tool_path, tool_manifest)
    staged_route = _stage_manifest(route_path, route_manifest)
    try:
        os.replace(staged_tool, tool_path)
        os.replace(staged_route, route_path)
    finally:
        staged_tool.unlink(missing_ok=True)
        staged_route.unlink(missing_ok=True)
    return {"route_manifest": route_path, "tool_manifest": tool_path}


__all__ = [
    "build_l1_l2_active_route_manifest",
    "build_l1_l2_active_tool_manifest",
    "validate_l1_l2_active_fixed_point",
    "write_l1_l2_active_manifests",
]

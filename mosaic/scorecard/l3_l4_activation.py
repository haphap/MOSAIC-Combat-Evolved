"""Deterministic activation of the frozen L3/L4 preservation overlay."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mosaic.scorecard.canonical_json import canonical_hash, canonical_json
from mosaic.scorecard.l1_l2_activation import (
    _APPROVED_ACTIVE_ROUTE_REPLACEMENTS,
    _active_overlay_route_is_already_projected,
    _copy,
    _project_overlay_binding_route_ids,
    _stage_manifest,
    _tool_surface,
    build_l1_l2_active_route_manifest,
    build_l1_l2_active_tool_manifest,
)
from mosaic.scorecard.l3_l4_preservation import (
    L3_TOOL_ROSTER,
    validate_l3_l4_preservation_overlay,
)


_PRESERVATION_DIRECTORY = Path("registry/prompt_checks/capability_preservation")
_OVERLAY = "l3_l4_preservation_overlay_v1.json"
_ACTIVE_TOOL_MANIFEST = Path(
    "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
)
_ACTIVE_ROUTE_MANIFEST = Path("registry/data_sources/agent_data_route_manifest_v1.json")
_ACTIVE_STAGE_BY_OVERLAY_STAGE = {
    **{(agent_id, agent_id): agent_id for agent_id in L3_TOOL_ROSTER},
    ("alpha_discovery", "alpha_discovery"): "alpha_discovery",
    ("cro", "cro_review"): "cro",
    ("autonomous_execution", "execution_feasibility"): "autonomous_execution",
    ("cio", "cio_proposal"): "cio_proposal",
    ("cio", "cio_final"): "cio_final",
}
_OVERLAY_STAGE_BY_ACTIVE_STAGE = {
    (agent_id, active_stage): overlay_stage
    for (agent_id, overlay_stage), active_stage in _ACTIVE_STAGE_BY_OVERLAY_STAGE.items()
}
_APPROVED_ACTIVE_OVERLAY_BINDING_MIGRATIONS = {
    ("druckenmiller", "druckenmiller", "get_yield_curve_cn"): (
        ("tushare.shibor_yield_curve",),
        ("composite.cn_rates",),
    ),
}


def _read_object(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_overlay(root: Path) -> dict[str, Any]:
    overlay = _read_object(root / _PRESERVATION_DIRECTORY / _OVERLAY)
    validate_l3_l4_preservation_overlay(overlay, root=root)
    return overlay


def active_stage_for_l3_l4_overlay(agent_id: str, overlay_stage: str) -> str:
    """Map the frozen prompt-stage name to the active capability-stage name."""
    try:
        return _ACTIVE_STAGE_BY_OVERLAY_STAGE[(agent_id, overlay_stage)]
    except KeyError as exc:
        raise ValueError(
            f"unknown L3/L4 overlay stage {agent_id}/{overlay_stage}"
        ) from exc


def l3_l4_overlay_stage_for_active(agent_id: str, active_stage: str) -> str:
    """Map the active capability stage back to its frozen preservation stage."""
    try:
        return _OVERLAY_STAGE_BY_ACTIVE_STAGE[(agent_id, active_stage)]
    except KeyError as exc:
        raise ValueError(
            f"unknown active L3/L4 stage {agent_id}/{active_stage}"
        ) from exc


def build_l3_l4_active_tool_manifest(root: Path) -> dict[str, Any]:
    """Add the exact 33 frozen L3/L4 bindings to the active role whitelist."""
    root = root.resolve()
    base = build_l1_l2_active_tool_manifest(root)
    overlay = _load_overlay(root)
    additions: dict[str, dict[str, set[str]]] = {}
    for binding in overlay["bindings"]:
        agent_id = str(binding["agent_id"])
        stage = active_stage_for_l3_l4_overlay(agent_id, str(binding["stage"]))
        additions.setdefault(agent_id, {}).setdefault(stage, set()).add(
            str(binding["tool_id"])
        )

    agents: list[dict[str, Any]] = []
    known_agents: set[str] = set()
    for source in base["agents"]:
        row = _copy(source)
        agent_id = str(row["agent_id"])
        known_agents.add(agent_id)
        by_stage = additions.get(agent_id, {})
        if set(by_stage) - set(row["execution_stages"]):
            raise ValueError("L3/L4 overlay stage is outside the active Agent roster")
        restored = set().union(*by_stage.values()) if by_stage else set()
        overlap = set(row["allowed_tools"]) & restored
        if overlap:
            raise ValueError(
                f"L3/L4 restored tools already active for {agent_id}: {sorted(overlap)}"
            )
        row["allowed_tools"] = [*row["allowed_tools"], *sorted(restored)]
        agents.append(row)
    if set(additions) - known_agents:
        raise ValueError("L3/L4 overlay references an unknown current Agent")

    tools = {tool_id for agent in agents for tool_id in agent["allowed_tools"]}
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
        raise ValueError("L3/L4 activation changed the Agent or stage roster")
    return body


def build_l3_l4_active_route_manifest(
    root: Path,
    *,
    active_tool_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge exact overlay routes/bindings over the active L1/L2 fixed point."""
    root = root.resolve()
    overlay = _load_overlay(root)
    expected_tools = build_l3_l4_active_tool_manifest(root)
    active = _copy(active_tool_manifest or expected_tools)
    if canonical_json(active) != canonical_json(expected_tools):
        raise ValueError("active tool manifest does not equal the L3/L4 fixed point")
    base_tools = build_l1_l2_active_tool_manifest(root)
    base_routes = build_l1_l2_active_route_manifest(
        root, active_tool_manifest=base_tools
    )

    route_by_id = {row["route_id"]: _copy(row) for row in base_routes["routes"]}
    for source in overlay["routes"]:
        if _active_overlay_route_is_already_projected(route_by_id, source):
            continue
        row = _copy(source)
        route_id = str(row["route_id"])
        existing = route_by_id.get(route_id)
        if existing is not None and canonical_json(existing) != canonical_json(row):
            raise ValueError(f"L3/L4 route {route_id} conflicts with the active route")
        route_by_id[route_id] = row

    binding_by_key = {
        (row["agent_id"], row["stage"], row["tool_id"]): _copy(row)
        for row in base_routes["bindings"]
    }
    if len(binding_by_key) != len(base_routes["bindings"]):
        raise ValueError("active L1/L2 route manifest contains duplicate bindings")
    for source in overlay["bindings"]:
        agent_id = str(source["agent_id"])
        stage = active_stage_for_l3_l4_overlay(agent_id, str(source["stage"]))
        key = (agent_id, stage, str(source["tool_id"]))
        if key in binding_by_key:
            raise ValueError("L3/L4 restored binding overlaps the active surface")
        binding_by_key[key] = {
            "agent_id": agent_id,
            "stage": stage,
            "tool_id": source["tool_id"],
            "required_route_ids": _project_overlay_binding_route_ids(
                key=key,
                source_route_ids=source["source_route_ids"],
                migrations=_APPROVED_ACTIVE_OVERLAY_BINDING_MIGRATIONS,
            ),
        }

    expected_order = [
        (agent["agent_id"], stage, tool_id)
        for agent in active["agents"]
        for stage in agent["execution_stages"]
        for tool_id in sorted(agent["allowed_tools"])
    ]
    if set(binding_by_key) != set(expected_order):
        raise ValueError("active L3/L4 routes do not close the active tool surface")
    referenced_route_ids = {
        route_id
        for binding in binding_by_key.values()
        for route_id in binding["required_route_ids"]
    }
    retired_route_ids = set(_APPROVED_ACTIVE_ROUTE_REPLACEMENTS)
    if retired_route_ids.intersection(referenced_route_ids):
        raise ValueError("retired route remains reachable after L3/L4 migration")
    if set(route_by_id) != referenced_route_ids:
        raise ValueError("active L3/L4 route catalog does not exactly close bindings")
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


def validate_l3_l4_active_fixed_point(
    root: Path,
    *,
    active_tool_manifest: Mapping[str, Any],
    active_route_manifest: Mapping[str, Any],
) -> None:
    expected_tools = build_l3_l4_active_tool_manifest(root)
    if canonical_json(active_tool_manifest) != canonical_json(expected_tools):
        raise ValueError("active tool manifest does not equal the L3/L4 fixed point")
    expected_routes = build_l3_l4_active_route_manifest(
        root, active_tool_manifest=expected_tools
    )
    if canonical_json(active_route_manifest) != canonical_json(expected_routes):
        raise ValueError("active route manifest does not equal the L3/L4 fixed point")


def write_l3_l4_active_manifests(root: Path) -> dict[str, Path]:
    """Build, validate, and atomically publish the two active manifests."""
    root = root.resolve()
    tools = build_l3_l4_active_tool_manifest(root)
    routes = build_l3_l4_active_route_manifest(root, active_tool_manifest=tools)
    validate_l3_l4_active_fixed_point(
        root,
        active_tool_manifest=tools,
        active_route_manifest=routes,
    )
    tool_path = root / _ACTIVE_TOOL_MANIFEST
    route_path = root / _ACTIVE_ROUTE_MANIFEST
    staged_tool = _stage_manifest(tool_path, tools)
    staged_route = _stage_manifest(route_path, routes)
    try:
        os.replace(staged_tool, tool_path)
        os.replace(staged_route, route_path)
    finally:
        staged_tool.unlink(missing_ok=True)
        staged_route.unlink(missing_ok=True)
    return {"route_manifest": route_path, "tool_manifest": tool_path}


__all__ = [
    "active_stage_for_l3_l4_overlay",
    "build_l3_l4_active_route_manifest",
    "build_l3_l4_active_tool_manifest",
    "l3_l4_overlay_stage_for_active",
    "validate_l3_l4_active_fixed_point",
    "write_l3_l4_active_manifests",
]

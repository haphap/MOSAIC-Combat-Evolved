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
    SECTOR_AGENT_IDS,
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
_RETIRED_ACTIVE_AGENT_IDS = frozenset({"relationship_mapper"})
_RETIRED_RELATIONSHIP_TOOL_IDS = frozenset(
    {"get_rke_research_context", "get_stock_research", "get_supply_chain_evidence"}
)
_MIGRATED_RELATIONSHIP_TOOL_ID = "get_supply_chain_evidence"
_APPROVED_ACTIVE_ROUTE_REPLACEMENTS = {
    "tushare.shibor_yield_curve": {
        "route_id": "composite.cn_rates",
        "source_family": "composite",
        "contract_version": "composite_cn_rates_mof_chinabond_v1",
        "pit_strategy": "OBSERVED_LIVE",
        "implementation_stage": "PR15",
    },
    "eurostat.euro_macro": {
        "route_id": "ecb.eu_real_economy",
        "source_family": "ecb",
        "contract_version": "ecb_eu_real_economy_history_v1",
        "pit_strategy": "AUTHORITATIVE_VINTAGE_REPLAY",
        "implementation_stage": "PR15",
    },
}
_APPROVED_ACTIVE_ROUTE_UPGRADES = {
    "ecb.euro_macro": {
        "route_id": "ecb.euro_macro",
        "source_family": "ecb",
        "contract_version": "ecb_euro_macro_v2",
        "pit_strategy": "AUTHORITATIVE_VINTAGE_REPLAY",
        "implementation_stage": "PR15",
    }
}
_APPROVED_ACTIVE_BINDING_MIGRATIONS = {
    ("central_bank", "central_bank", "get_central_bank_snapshot"): (
        (
            "official.cn_macro",
            "tushare.eco_cal.cny",
            "tushare.shibor_yield_curve",
        ),
        ("composite.cn_rates", "official.cn_macro", "tushare.eco_cal.cny"),
    ),
    ("eu_economy", "eu_economy", "get_eu_macro_snapshot"): (
        ("ecb.euro_macro", "eurostat.euro_macro", "tushare.eco_cal.eur"),
        ("ecb.eu_real_economy", "ecb.euro_macro", "tushare.eco_cal.eur"),
    ),
}
_APPROVED_ACTIVE_OVERLAY_BINDING_MIGRATIONS = {
    ("financials", "financials", "get_yield_curve_cn"): (
        ("tushare.shibor_yield_curve",),
        ("composite.cn_rates",),
    ),
}


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(canonical_json(value))


def _active_overlay_route_is_already_projected(
    route_by_id: Mapping[str, Mapping[str, Any]], source: Mapping[str, Any]
) -> bool:
    replacement = _APPROVED_ACTIVE_ROUTE_REPLACEMENTS.get(str(source["route_id"]))
    if replacement is None:
        return False
    active = route_by_id.get(str(replacement["route_id"]))
    if active is None or canonical_json(active) != canonical_json(replacement):
        raise ValueError("approved active overlay route replacement drift")
    return True


def _project_overlay_binding_route_ids(
    *,
    key: tuple[str, str, str],
    source_route_ids: list[str],
    migrations: Mapping[
        tuple[str, str, str], tuple[tuple[str, ...], tuple[str, ...]]
    ],
) -> list[str]:
    source = tuple(source_route_ids)
    migration = migrations.get(key)
    if migration is None:
        return list(source)
    expected_old, replacement = migration
    if source != expected_old:
        raise ValueError("approved active overlay binding input drift")
    return list(replacement)


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
    retired_relationship_tool_ids: set[str] = set()
    for binding in overlay["bindings"]:
        agent_id = str(binding["agent_id"])
        if agent_id in _RETIRED_ACTIVE_AGENT_IDS:
            tool_id = str(binding["tool_id"])
            retired_relationship_tool_ids.add(tool_id)
            if tool_id == _MIGRATED_RELATIONSHIP_TOOL_ID:
                for sector_agent_id in SECTOR_AGENT_IDS:
                    restored_by_agent.setdefault(sector_agent_id, set()).add(tool_id)
            continue
        stage = str(binding["stage"])
        if stage != agent_id:
            raise ValueError("PR6 restored binding stage differs from its Agent")
        restored_by_agent.setdefault(agent_id, set()).add(str(binding["tool_id"]))
    if retired_relationship_tool_ids != _RETIRED_RELATIONSHIP_TOOL_IDS:
        raise ValueError("retired Relationship binding tool roster drift")

    agents: list[dict[str, Any]] = []
    known_agents: set[str] = set()
    for source in base["agents"]:
        row = _copy(source)
        agent_id = str(row["agent_id"])
        if agent_id in _RETIRED_ACTIVE_AGENT_IDS:
            continue
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
    expected_agents = [
        row
        for row in base["agents"]
        if row["agent_id"] not in _RETIRED_ACTIVE_AGENT_IDS
    ]
    if body["agent_count"] != len(expected_agents) or body[
        "execution_stage_count"
    ] != sum(len(row["execution_stages"]) for row in expected_agents):
        raise ValueError("L1/L2 activation active Agent or stage roster drift")
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


def _apply_approved_active_route_migrations(
    frozen: Mapping[str, Any],
) -> dict[str, Any]:
    migrated = _copy(frozen)
    route_by_id = {str(row["route_id"]): row for row in migrated["routes"]}
    for old_route_id, replacement in _APPROVED_ACTIVE_ROUTE_REPLACEMENTS.items():
        if old_route_id not in route_by_id or replacement["route_id"] in route_by_id:
            raise ValueError("approved active route replacement input drift")
        route_by_id.pop(old_route_id)
        route_by_id[str(replacement["route_id"])] = _copy(replacement)
    for route_id, replacement in _APPROVED_ACTIVE_ROUTE_UPGRADES.items():
        if route_id not in route_by_id:
            raise ValueError("approved active route upgrade input drift")
        route_by_id[route_id] = _copy(replacement)

    binding_by_key = {
        (str(row["agent_id"]), str(row["stage"]), str(row["tool_id"])): row
        for row in migrated["bindings"]
    }
    for key, (expected_old, replacement) in (
        _APPROVED_ACTIVE_BINDING_MIGRATIONS.items()
    ):
        binding = binding_by_key.get(key)
        if binding is None or tuple(binding["required_route_ids"]) != expected_old:
            raise ValueError("approved active route binding input drift")
        binding["required_route_ids"] = list(replacement)

    retired = set(_APPROVED_ACTIVE_ROUTE_REPLACEMENTS)
    if any(
        retired.intersection(binding["required_route_ids"])
        for binding in migrated["bindings"]
    ):
        raise ValueError("retired route remains reachable after active migration")
    migrated["routes"] = [route_by_id[route_id] for route_id in sorted(route_by_id)]
    return migrated


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
    frozen_base_routes = _project_base_route_manifest(root, base)
    if overlay.get("base_agent_data_route_manifest_hash") != canonical_hash(
        frozen_base_routes
    ):
        raise ValueError("PR6 overlay base Agent data route manifest drift")
    base_routes = _apply_approved_active_route_migrations(frozen_base_routes)

    route_by_id = {row["route_id"]: _copy(row) for row in base_routes["routes"]}
    for source in overlay["routes"]:
        if _active_overlay_route_is_already_projected(route_by_id, source):
            continue
        row = _copy(source)
        route_id = str(row["route_id"])
        existing = route_by_id.get(route_id)
        if existing is not None and canonical_json(existing) != canonical_json(row):
            raise ValueError(f"PR6 route {route_id} conflicts with the base route")
        route_by_id[route_id] = row

    retired_route_ids = {
        route_id
        for row in base_routes["bindings"]
        if row["agent_id"] in _RETIRED_ACTIVE_AGENT_IDS
        for route_id in row["required_route_ids"]
    }
    retired_route_ids.update(
        route_id
        for row in overlay["bindings"]
        if row["agent_id"] in _RETIRED_ACTIVE_AGENT_IDS
        for route_id in row["source_route_ids"]
    )
    binding_by_key = {
        (row["agent_id"], row["stage"], row["tool_id"]): _copy(row)
        for row in base_routes["bindings"]
        if row["agent_id"] not in _RETIRED_ACTIVE_AGENT_IDS
    }
    if len(binding_by_key) != sum(
        row["agent_id"] not in _RETIRED_ACTIVE_AGENT_IDS
        for row in base_routes["bindings"]
    ):
        raise ValueError("base route manifest contains duplicate bindings")
    for source in overlay["bindings"]:
        if source["agent_id"] in _RETIRED_ACTIVE_AGENT_IDS:
            if source["tool_id"] == _MIGRATED_RELATIONSHIP_TOOL_ID:
                for sector_agent_id in SECTOR_AGENT_IDS:
                    key = (
                        sector_agent_id,
                        sector_agent_id,
                        _MIGRATED_RELATIONSHIP_TOOL_ID,
                    )
                    if key in binding_by_key:
                        raise ValueError(
                            "migrated Relationship binding overlaps active Sector surface"
                        )
                    binding_by_key[key] = {
                        "agent_id": sector_agent_id,
                        "stage": sector_agent_id,
                        "tool_id": _MIGRATED_RELATIONSHIP_TOOL_ID,
                        "required_route_ids": list(source["source_route_ids"]),
                    }
            continue
        key = (source["agent_id"], source["stage"], source["tool_id"])
        if key in binding_by_key:
            raise ValueError("PR6 restored route binding overlaps the base surface")
        binding_by_key[key] = {
            "agent_id": source["agent_id"],
            "stage": source["stage"],
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
        raise ValueError("active route binding surface does not close the active tools")
    referenced_route_ids = {
        route_id
        for binding in binding_by_key.values()
        for route_id in binding["required_route_ids"]
    }
    replaced_route_ids = set(_APPROVED_ACTIVE_ROUTE_REPLACEMENTS)
    if replaced_route_ids.intersection(referenced_route_ids):
        raise ValueError("retired route remains reachable after overlay migration")
    orphan_route_ids = set(route_by_id) - referenced_route_ids
    if not orphan_route_ids.issubset(retired_route_ids):
        raise ValueError("active route catalog contains non-retirement orphans")
    route_by_id = {
        route_id: row
        for route_id, row in route_by_id.items()
        if route_id in referenced_route_ids
    }
    if set(route_by_id) != referenced_route_ids:
        raise ValueError("active route catalog does not exactly close binding routes")

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

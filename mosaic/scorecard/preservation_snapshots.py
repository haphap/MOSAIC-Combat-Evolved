"""Immutable pre-activation Agent tool and route manifest inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mosaic.scorecard.capability_preservation import build_binding_manifest


_DIRECTORY = Path("registry/prompt_checks/capability_preservation")
_TOOL_SNAPSHOT = "current_agent_tool_contract_snapshot_v1.json"
_ROUTE_SNAPSHOT = "current_agent_data_route_manifest_snapshot_v1.json"


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_preactivation_agent_manifests(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = root / _DIRECTORY
    return (
        _read_object(directory / _TOOL_SNAPSHOT),
        _read_object(directory / _ROUTE_SNAPSHOT),
    )


def build_preactivation_capability_binding_manifest(root: Path) -> dict[str, Any]:
    tool_manifest, route_manifest = load_preactivation_agent_manifests(root)
    return build_binding_manifest(tool_manifest, route_manifest)


__all__ = [
    "build_preactivation_capability_binding_manifest",
    "load_preactivation_agent_manifests",
]

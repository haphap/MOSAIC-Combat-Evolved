from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT_CHECKS = ROOT / "registry" / "prompt_checks"


def _read(name: str) -> dict:
    return json.loads((PROMPT_CHECKS / name).read_text(encoding="utf-8"))


def test_superseded_runtime_and_macro_manifests_are_audit_only() -> None:
    expected = {
        "runtime_agent_manifest_v1.json": "runtime_agent_manifest_v4",
        "runtime_agent_manifest_v2.json": "runtime_agent_manifest_v4",
        "runtime_agent_manifest_v3.json": "runtime_agent_manifest_v4",
        "macro_prompt_role_contract_manifest_v1.json": (
            "agent_prompt_role_contract_manifest_v2"
        ),
    }
    for filename, successor in expected.items():
        payload = _read(filename)
        assert payload["lifecycle_status"] == "legacy_unverified"
        assert payload["production_selectable"] is False
        assert payload["superseded_by"] == successor


def test_production_runtime_manifest_consumers_pin_v4() -> None:
    consumers = (
        "mosaic/bridge/handlers/prompts.py",
        "mosaic/rke/prompt_evolution_delivery.py",
        "scripts/check_private_knot_boundary.py",
        "mosaic-ts/scripts/generate_runtime_manifest.ts",
        "mosaic-ts/src/agents/prompts/runtime_agent_spec.ts",
    )
    for relative_path in consumers:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "runtime_agent_manifest_v4" in source
        assert "runtime_agent_manifest_v1" not in source
        assert "runtime_agent_manifest_v2" not in source
        assert "runtime_agent_manifest_v3" not in source

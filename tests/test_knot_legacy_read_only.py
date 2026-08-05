from __future__ import annotations

import json
from pathlib import Path

from mosaic.bridge import handlers as _handlers  # noqa: F401
from mosaic.bridge.registry import all_methods

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_knot_protocol_has_no_executable_public_surface() -> None:
    assert not any(method.startswith("darwinian.knot_") for method in all_methods())
    assert not (ROOT / "mosaic/scorecard/knot_v2.py").exists()

    sources = (
        ROOT / "mosaic/bridge/handlers/darwinian.py",
        ROOT / "mosaic/bridge/tool_capabilities.py",
        ROOT / "mosaic/scorecard/store.py",
    )
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert "def darwinian_knot_" not in text
        assert "def _reject_legacy_knot_write" not in text


def test_legacy_inventory_is_a_compact_read_only_audit_index() -> None:
    inventory = json.loads(
        (ROOT / "registry/knot/legacy_read_only_v2.json").read_text(encoding="utf-8")
    )
    assert inventory["status"] == "legacy_read_only"
    assert inventory["active_runtime"] is False
    assert inventory["writes_enabled"] is False
    assert inventory["public_tombstones"] == []
    assert inventory["public_fail_closed_legacy_ports"] == []
    assert inventory["retired_rpc_prefixes"] == ["darwinian.knot_"]

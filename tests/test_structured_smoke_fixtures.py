from __future__ import annotations

import json
from pathlib import Path

from mosaic.bridge.tool_capabilities import (
    AGENT_TOOL_MATRIX,
    ALL_AGENT_IDS,
    materialize_tool_payload,
)
from scripts.build_structured_smoke_fixtures import build_structured_smoke_fixtures


def test_structured_smoke_bundle_materializes_all_29_stage_tools(
    tmp_path: Path, monkeypatch
) -> None:
    as_of = "2026-07-17"
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", as_of)
    for key, value in bindings.items():
        monkeypatch.setenv(key, value)

    stages = [
        (agent_id, stage)
        for agent_id in ALL_AGENT_IDS
        for stage in (
            ("cio_proposal", "cio_final") if agent_id == "cio" else (agent_id,)
        )
    ]
    assert len(stages) == 29
    for agent_id, stage in stages:
        for tool_id in AGENT_TOOL_MATRIX[agent_id]:
            payload = json.loads(
                materialize_tool_payload(
                    tool_id,
                    agent_id=agent_id,
                    stage=stage,
                    as_of=as_of,
                )
            )
            assert isinstance(payload, dict)
            assert payload
            if agent_id == "geopolitical" and tool_id == "get_geopolitical_events_snapshot":
                assert payload["schema_version"] == "geopolitical_role_snapshot_v2"
                assert payload["direct_data_quality"] == 1.0
                assert "route_source_coverage" not in payload
                assert len(json.dumps(payload)) < 100_000

    marker = json.loads(
        (tmp_path / "cache" / "structured_smoke_fixture_bundle.json").read_text(
            encoding="utf-8"
        )
    )
    assert marker["fixture_class"] == "SYNTHETIC_NON_PRODUCTION"
    assert marker["contains_vendor_prose"] is False

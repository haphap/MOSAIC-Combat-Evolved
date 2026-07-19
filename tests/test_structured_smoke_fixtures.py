from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.bridge.tool_capabilities import (
    AGENT_TOOL_MATRIX,
    ALL_AGENT_IDS,
    materialize_tool_payload,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.geopolitical_events import load_geopolitical_events_snapshot
from mosaic.scorecard.darwinian_v2 import canonical_hash
from scripts.build_structured_smoke_fixtures import (
    build_structured_smoke_fixtures,
    render_shell_exports,
)


def _bind_structured_smoke(
    bindings: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in bindings.items():
        monkeypatch.setenv(key, value)


def test_structured_smoke_bundle_materializes_all_29_stage_tools(
    tmp_path: Path, monkeypatch
) -> None:
    as_of = "2026-07-17"
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", as_of)
    for key, value in bindings.items():
        if key == "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS":
            continue
        monkeypatch.setenv(key, value)
    with pytest.raises(DataVendorUnavailable, match="snapshot rejected"):
        load_geopolitical_events_snapshot(as_of)
    monkeypatch.setenv(
        "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS",
        bindings["MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS"],
    )

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
    body = {key: value for key, value in marker.items() if key != "bundle_hash"}
    assert marker["bundle_hash"] == canonical_hash(body)


@pytest.mark.parametrize("mutation", ["tamper", "extra", "missing"])
def test_structured_smoke_runtime_rejects_artifact_inventory_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    as_of = "2026-07-17"
    cache_root = tmp_path / "cache"
    bindings = build_structured_smoke_fixtures(cache_root, as_of)
    _bind_structured_smoke(bindings, monkeypatch)

    macro_fixture = cache_root / "macro_snapshots" / as_of / "china.json"
    if mutation == "tamper":
        macro_fixture.write_bytes(macro_fixture.read_bytes() + b"\n")
    elif mutation == "extra":
        extra = cache_root / "sector_snapshots" / as_of / "unexpected.json"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("{}\n", encoding="utf-8")
    else:
        macro_fixture.unlink()

    with pytest.raises(DataVendorUnavailable, match="artifact inventory mismatch"):
        materialize_tool_payload(
            "get_superinvestor_candidate_snapshot",
            agent_id="ackman",
            stage="ackman",
            as_of=as_of,
        )


def test_structured_smoke_builder_rejects_nonempty_root_without_deleting_it(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    retained = cache_root / "preexisting.txt"
    retained.write_text("must remain untouched\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="fresh empty directory"):
        build_structured_smoke_fixtures(cache_root, "2026-07-17")

    assert retained.read_text(encoding="utf-8") == "must remain untouched\n"
    assert not (cache_root / "structured_smoke_fixture_bundle.json").exists()


def test_structured_smoke_shell_exports_quote_every_binding() -> None:
    rendered = render_shell_exports(
        {
            "MOSAIC_CACHE_DIR": "/tmp/root with spaces",
            "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS": "structured_smoke",
        }
    )

    assert rendered.splitlines() == [
        "export MOSAIC_CACHE_DIR='/tmp/root with spaces'",
        "export MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS=structured_smoke",
    ]


def test_geopolitical_structured_smoke_requires_expected_bundle_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", "2026-07-17")
    _bind_structured_smoke(bindings, monkeypatch)
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH")

    with pytest.raises(DataVendorUnavailable, match="marker binding mismatch"):
        load_geopolitical_events_snapshot("2026-07-17")


def test_geopolitical_structured_smoke_rejects_symlinked_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "cache"
    bindings = build_structured_smoke_fixtures(cache_root, "2026-07-17")
    _bind_structured_smoke(bindings, monkeypatch)
    marker_path = cache_root / "structured_smoke_fixture_bundle.json"
    marker_copy = cache_root / "marker-copy.json"
    marker_copy.write_bytes(marker_path.read_bytes())
    marker_path.unlink()
    marker_path.symlink_to(marker_copy.name)

    with pytest.raises(DataVendorUnavailable, match="marker is unavailable"):
        load_geopolitical_events_snapshot("2026-07-17")

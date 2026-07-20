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
from mosaic.dataflows.outcome_runtime_inputs import (
    load_evaluation_opportunity_projection,
)
from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.opportunity_authority import materialize_pre_run_authority
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


def test_structured_smoke_bundle_supports_a_non_trading_as_of_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of = "2024-06-30"  # Sunday.
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", as_of)
    _bind_structured_smoke(bindings, monkeypatch)

    payload = json.loads(
        materialize_tool_payload(
            "get_market_breadth_snapshot",
            agent_id="market_breadth",
            stage="market_breadth",
            as_of=as_of,
        )
    )
    assert payload["as_of_date"] == as_of
    assert payload["coverage_ratio"] == 1.0


def test_structured_smoke_l1_l3_opportunities_use_exact_member_authorities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of_date = "2026-07-17"
    as_of = f"{as_of_date}T15:00:00+08:00"
    cache_root = tmp_path / "cache"
    bindings = build_structured_smoke_fixtures(cache_root, as_of_date)
    _bind_structured_smoke(bindings, monkeypatch)

    expected_fields = {
        "MACRO_TRANSMISSION": None,
        "SECTOR_TILT_PICKS": {
            "subindustry_id",
            "security_shortlist_id",
            "security_shortlist_hash",
            "security_ts_codes",
        },
        "RELATIONSHIP_EDGES": {"edge_candidate_id", "materiality_weight"},
        "SUPERINVESTOR_PICKS": {"candidate_ref", "ts_code"},
    }
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        if contract["layer"] == "DECISION":
            continue
        projection = load_evaluation_opportunity_projection(
            as_of,
            agent_id,
            root=cache_root / "outcome_runtime",
        )
        members = projection["member_refs"]
        object_type = contract["evaluation_object_type"]
        if object_type == "SUPERINVESTOR_PICKS":
            assert members == []
            continue
        assert members
        fields = expected_fields[object_type]
        if fields is None:
            member_field = (
                "event_id"
                if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
                else "path_snapshot_id"
            )
            fields = {member_field}
        assert all(set(member) == fields for member in members)
        authority = materialize_pre_run_authority(
            agent_id=agent_id,
            as_of=as_of,
            graph_run_id="structured-smoke-opportunity-test",
            schedule_slot={
                "outcome_schedule_slot_hash": "sha256:" + "1" * 64,
                "trigger_event": (
                    {
                        "event_id": (
                            f"structured-smoke:event:{agent_id}:{as_of_date}"
                        )
                    }
                    if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
                    else None
                ),
            },
        )
        assert members == authority["member_refs"]


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

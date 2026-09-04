from __future__ import annotations

import copy
from pathlib import Path

import pytest

import mosaic.dataflows.agent_stage_preparer as agent_stage_preparer
from mosaic.dataflows.bound_runtime_snapshots import compile_bound_runtime_snapshot
from mosaic.dataflows.runtime_paths import agent_runtime_root_override
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.dataflows.exceptions import DataVendorUnavailable


AS_OF = "2025-06-17"
GRAPH_RUN_ID = "structured-smoke-graph"
BUNDLE_HASH = "sha256:" + "a" * 64


def _record(*, kind: str, agent_id: str, payload: object) -> tuple[dict, dict]:
    identity = {
        "schema_version": "structured_smoke_accepted_output_ref_v1",
        "fixture_bundle_hash": BUNDLE_HASH,
        "graph_run_id": GRAPH_RUN_ID,
        "as_of": AS_OF,
        "accepted_output_kind": kind,
        "agent_id": agent_id,
        "payload_hash": canonical_hash(payload),
    }
    accepted_output_id = "structured-smoke-accepted-output:" + canonical_hash(identity).removeprefix(
        "sha256:"
    )
    accepted_output_hash = canonical_hash({**identity, "accepted_output_id": accepted_output_id})
    record = {
        "schema_version": "structured_smoke_accepted_output_record_v1",
        "sample_origin": "NON_PRODUCTION_STRUCTURED_SMOKE",
        "fixture_bundle_hash": BUNDLE_HASH,
        "accepted_output_kind": kind,
        "agent_id": agent_id,
        "accepted_output_id": accepted_output_id,
        "accepted_output_hash": accepted_output_hash,
        "graph_run_id": GRAPH_RUN_ID,
        "as_of": AS_OF,
        "accepted_at": "2025-06-17T00:00:00.000Z",
        "output": {"payload": payload},
    }
    ref = {
        "accepted_output_kind": kind,
        "agent_id": agent_id,
        "accepted_output_id": accepted_output_id,
        "accepted_output_hash": accepted_output_hash,
    }
    return record, ref


def _runtime_state() -> dict:
    return {
        "captured_at": "2025-06-17T12:00:00+00:00",
        "current_positions": {
            "snapshot_status": "empty_confirmed",
            "position_source": "empty_confirmed",
            "source_error_code": None,
            "position_snapshot_hash": canonical_hash("empty-positions"),
            "positions": [],
        },
    }


def test_structured_smoke_records_compile_and_are_not_production_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH", BUNDLE_HASH)
    macro, macro_ref = _record(
        kind="MACRO_TRANSMISSION",
        agent_id="china",
        payload={"direction": "positive"},
    )
    sector, sector_ref = _record(
        kind="STANDARD_SECTOR_SELECTION",
        agent_id="semiconductor",
        payload={
            "preferred_direction": {"direction_id": "semiconductor:preferred"},
            "least_preferred_direction": {"direction_id": "semiconductor:least"},
            "long_picks": [],
            "short_or_avoid_picks": [],
        },
    )

    snapshot = compile_bound_runtime_snapshot(
        agent_id="ackman",
        stage="ackman",
        as_of=AS_OF,
        graph_run_id=GRAPH_RUN_ID,
        accepted_output_refs=[macro_ref, sector_ref],
        accepted_output_records=[macro, sector],
        runtime_state=_runtime_state(),
        generated_at="2025-06-17T12:01:00+00:00",
    )

    assert snapshot["candidate_status"] == "EMPTY_CONFIRMED"
    assert snapshot["candidate_universe"] == []


def test_structured_smoke_empty_positions_bind_to_actual_as_of_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH", BUNDLE_HASH)
    macro, macro_ref = _record(
        kind="MACRO_TRANSMISSION",
        agent_id="china",
        payload={"direction": "positive"},
    )
    sector, sector_ref = _record(
        kind="STANDARD_SECTOR_SELECTION",
        agent_id="semiconductor",
        payload={
            "preferred_direction": {"direction_id": "semiconductor:preferred"},
            "least_preferred_direction": {"direction_id": "semiconductor:least"},
            "long_picks": [],
            "short_or_avoid_picks": [],
        },
    )
    runtime_state = _runtime_state()
    runtime_state["captured_at"] = "2026-08-19T16:33:59.266270+00:00"
    snapshot = compile_bound_runtime_snapshot(
        agent_id="ackman",
        stage="ackman",
        as_of=AS_OF,
        graph_run_id=GRAPH_RUN_ID,
        accepted_output_refs=[macro_ref, sector_ref],
        accepted_output_records=[macro, sector],
        runtime_state=runtime_state,
        generated_at="2026-08-19T16:33:59.266270+00:00",
    )

    position_evidence = next(
        row for row in snapshot["evidence_ledger"] if row["source_kind"] == "POSITION_SNAPSHOT"
    )
    assert position_evidence["available_at"] == "2025-06-17T00:00:00+08:00"


def test_structured_smoke_loaded_cli_fixture_positions_bind_to_actual_as_of_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH", BUNDLE_HASH)
    macro, macro_ref = _record(
        kind="MACRO_TRANSMISSION",
        agent_id="china",
        payload={"direction": "positive"},
    )
    sector, sector_ref = _record(
        kind="STANDARD_SECTOR_SELECTION",
        agent_id="semiconductor",
        payload={
            "preferred_direction": {"direction_id": "semiconductor:preferred"},
            "least_preferred_direction": {"direction_id": "semiconductor:least"},
            "long_picks": [],
            "short_or_avoid_picks": [],
        },
    )
    positions = [
        {
            "ticker": "510300.SH",
            "current_weight": 0.1,
            "cost_basis": 1.0,
            "market_price": 1.0,
            "unrealized_pnl_pct": 0.0,
            "holding_days": 1,
            "entry_date": AS_OF,
            "source_agent": "cio",
            "entry_thesis_id": "test:position",
            "last_review_date": AS_OF,
        }
    ]
    runtime_state = _runtime_state()
    runtime_state["captured_at"] = "2026-08-19T16:33:59.266270+00:00"
    runtime_state["current_positions"] = {
        "snapshot_status": "loaded",
        "position_source": "cli_fixture",
        "source_error_code": None,
        "position_snapshot_hash": canonical_hash(positions),
        "positions": positions,
    }
    snapshot = compile_bound_runtime_snapshot(
        agent_id="ackman",
        stage="ackman",
        as_of=AS_OF,
        graph_run_id=GRAPH_RUN_ID,
        accepted_output_refs=[macro_ref, sector_ref],
        accepted_output_records=[macro, sector],
        runtime_state=runtime_state,
        generated_at="2026-08-19T16:33:59.266270+00:00",
    )

    position_evidence = next(
        row for row in snapshot["evidence_ledger"] if row["source_kind"] == "POSITION_SNAPSHOT"
    )
    assert position_evidence["available_at"] == "2025-06-17T00:00:00+08:00"


def test_structured_smoke_l3_prepare_compiles_with_projected_candidate_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH", BUNDLE_HASH)
    macro, macro_ref = _record(
        kind="MACRO_TRANSMISSION",
        agent_id="china",
        payload={"direction": "positive"},
    )
    sector, sector_ref = _record(
        kind="STANDARD_SECTOR_SELECTION",
        agent_id="semiconductor",
        payload={
            "preferred_direction": {"direction_id": "semiconductor:preferred"},
            "least_preferred_direction": {"direction_id": "semiconductor:least"},
            "long_picks": [],
            "short_or_avoid_picks": [],
        },
    )
    refs = [macro_ref, sector_ref]
    runtime_state = _runtime_state()
    runtime_state.pop("captured_at")
    request = {
        "agent_id": "ackman",
        "stage": "ackman",
        "as_of": AS_OF,
        "graph_run_id": GRAPH_RUN_ID,
        "candidate_scope": {
            "accepted_output_refs": [
                {"key": f"{ref['accepted_output_kind']}:{ref['agent_id']}", **ref}
                for ref in refs
            ]
        },
        "runtime_inputs": {
            "accepted_output_refs": refs,
            "accepted_output_records": [macro, sector],
            "bound_runtime_state": runtime_state,
        },
    }
    output_root = tmp_path / "runtime"
    with agent_runtime_root_override(output_root):
        prepared = agent_stage_preparer.ensure_agent_stage_materialization(request)

    assert prepared == {
        "agent_id": "ackman",
        "stage": "ackman",
        "as_of": AS_OF,
        "cache_status": "MISS",
        "ensure_mode": "enforce",
        "prepared_build_receipt_hashes": {
            "get_superinvestor_candidate_snapshot": prepared[
                "prepared_build_receipt_hashes"
            ]["get_superinvestor_candidate_snapshot"]
        },
    }
    assert list(output_root.rglob("*.json"))


def test_structured_smoke_non_bound_request_remains_bypassed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")

    assert agent_stage_preparer.ensure_agent_stage_materialization(
        {"agent_id": "ackman", "stage": "ackman"}
    ) == {"status": "SYNTHETIC_NON_PRODUCTION_BYPASS"}


@pytest.mark.parametrize("tamper", ["missing", "mismatch"])
def test_structured_smoke_l3_prepare_rejects_bound_scope_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH", BUNDLE_HASH)
    macro, macro_ref = _record(
        kind="MACRO_TRANSMISSION",
        agent_id="china",
        payload={"direction": "positive"},
    )
    sector, sector_ref = _record(
        kind="STANDARD_SECTOR_SELECTION",
        agent_id="semiconductor",
        payload={
            "preferred_direction": {"direction_id": "semiconductor:preferred"},
            "least_preferred_direction": {"direction_id": "semiconductor:least"},
            "long_picks": [],
            "short_or_avoid_picks": [],
        },
    )
    refs = [macro_ref, sector_ref]
    scoped_refs = [
        {"key": f"{ref['accepted_output_kind']}:{ref['agent_id']}", **ref}
        for ref in refs
    ]
    if tamper == "missing":
        del scoped_refs[0]["accepted_output_hash"]
    else:
        scoped_refs[0]["accepted_output_hash"] = "sha256:" + "f" * 64
    runtime_state = _runtime_state()
    runtime_state.pop("captured_at")
    request = {
        "agent_id": "ackman",
        "stage": "ackman",
        "as_of": AS_OF,
        "candidate_scope": {"accepted_output_refs": scoped_refs},
        "runtime_inputs": {
            "accepted_output_refs": refs,
            "accepted_output_records": [macro, sector],
            "bound_runtime_state": runtime_state,
        },
    }
    with agent_runtime_root_override(tmp_path / "runtime"):
        with pytest.raises(DataVendorUnavailable):
            agent_stage_preparer.ensure_agent_stage_materialization(request)


def test_structured_smoke_direct_superinvestor_payload_drives_alpha_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH", BUNDLE_HASH)
    records: list[dict] = []
    refs: list[dict] = []
    ts_codes: list[str] = []
    for agent_id, ts_code in (
        ("ackman", "510300.SH"),
        ("burry", "512480.SH"),
        ("druckenmiller", "159915.SZ"),
        ("munger", "512880.SH"),
    ):
        record, ref = _record(
            kind="SUPERINVESTOR_SELECTION",
            agent_id=agent_id,
            payload={"picks": [{"ts_code": ts_code, "conviction": 0.2}]},
        )
        records.append(record)
        refs.append(ref)
        ts_codes.append(ts_code)

    snapshot = compile_bound_runtime_snapshot(
        agent_id="alpha_discovery",
        stage="alpha_discovery",
        as_of=AS_OF,
        graph_run_id=GRAPH_RUN_ID,
        accepted_output_refs=refs,
        accepted_output_records=records,
        runtime_state=_runtime_state(),
        generated_at="2025-06-17T12:01:00+00:00",
    )

    assert snapshot["constraints"]["excluded_selected_ts_codes"] == sorted(ts_codes)


@pytest.mark.parametrize("tamper", ["payload", "ref", "unknown_kind"])
def test_structured_smoke_records_fail_closed_on_tampering_or_unknown_kind(
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH", BUNDLE_HASH)
    record, ref = _record(
        kind="STANDARD_SECTOR_SELECTION" if tamper != "unknown_kind" else "UNKNOWN_KIND",
        agent_id="semiconductor",
        payload={"selection_status": "NONE_FOUND"},
    )
    if tamper == "payload":
        record["output"]["payload"] = {"selection_status": "tampered"}
    elif tamper == "ref":
        ref["accepted_output_hash"] = "sha256:" + "f" * 64

    with pytest.raises(DataVendorUnavailable):
        compile_bound_runtime_snapshot(
            agent_id="ackman",
            stage="ackman",
            as_of=AS_OF,
            graph_run_id=GRAPH_RUN_ID,
            accepted_output_refs=[ref],
            accepted_output_records=[record],
            runtime_state=_runtime_state(),
            generated_at="2025-06-17T12:01:00+00:00",
        )


def test_structured_smoke_record_is_rejected_without_explicit_smoke_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH", BUNDLE_HASH)
    record, ref = _record(
        kind="MACRO_TRANSMISSION",
        agent_id="china",
        payload={"direction": "positive"},
    )

    with pytest.raises(DataVendorUnavailable):
        compile_bound_runtime_snapshot(
            agent_id="ackman",
            stage="ackman",
            as_of=AS_OF,
            graph_run_id=GRAPH_RUN_ID,
            accepted_output_refs=[ref],
            accepted_output_records=[copy.deepcopy(record)],
            runtime_state=_runtime_state(),
            generated_at="2025-06-17T12:01:00+00:00",
        )

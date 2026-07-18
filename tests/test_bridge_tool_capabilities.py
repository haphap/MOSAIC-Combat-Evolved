from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mosaic.bridge.tool_capabilities import (
    AGENT_TOOL_MATRIX,
    ALL_AGENT_IDS,
    AgentToolCapabilityStore,
    allowed_tools_for_agent,
    execution_stage_for_agent,
)


def _request(agent: str = "china", stage: str | None = None) -> dict:
    return {
        "graph_run_id": "graph-1",
        "run_slot_id": f"slot-{agent}",
        "run_id": "run-1",
        "node_id": f"node-{agent}",
        "agent_id": agent,
        "stage": stage or agent,
        "as_of": "2026-07-09",
        "materialization_request_id": f"materialize-{agent}-{stage or agent}",
        "runtime_inputs": {"accepted_record_ids": ["record-1"]},
        "candidate_scope": None if agent == "china" else {"scope_id": "scope-1"},
        "ttl_seconds": 60,
    }


def _store(tmp_path: Path, now: list[datetime]) -> AgentToolCapabilityStore:
    return AgentToolCapabilityStore(
        tmp_path / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: now[0],
    )


def test_v3_matrix_has_28_agents_and_29_closed_execution_stages():
    assert len(ALL_AGENT_IDS) == 28
    assert set(AGENT_TOOL_MATRIX) == set(ALL_AGENT_IDS)
    stages = [execution_stage_for_agent(agent) for agent in ALL_AGENT_IDS if agent != "cio"]
    stages += [execution_stage_for_agent("cio", "cio_proposal")]
    stages += [execution_stage_for_agent("cio", "cio_final")]
    assert len(stages) == len(set(stages)) == 29
    with pytest.raises(ValueError, match="capability stage"):
        execution_stage_for_agent("central_bank", "agent_run")
    with pytest.raises(ValueError, match="cio capability stage"):
        execution_stage_for_agent("cio", "cio")


def test_matrix_restricts_roles_to_the_frozen_plan_tools():
    assert allowed_tools_for_agent("china") == ("get_china_macro_snapshot",)
    assert allowed_tools_for_agent("central_bank") == ("get_central_bank_snapshot",)
    assert allowed_tools_for_agent("relationship_mapper") == (
        "get_relationship_graph_snapshot",
    )
    assert allowed_tools_for_agent("biotech") == ("get_sector_research_snapshot",)
    assert allowed_tools_for_agent("semiconductor") == (
        "get_sector_research_snapshot",
        "get_role_event_snapshot",
    )
    assert allowed_tools_for_agent("agriculture") == (
        "get_sector_research_snapshot",
        "get_role_event_snapshot",
    )
    assert allowed_tools_for_agent("alpha_discovery") == (
        "get_alpha_candidate_snapshot",
        "get_role_event_snapshot",
    )
    assert allowed_tools_for_agent("cio") == ("get_cio_decision_snapshot",)


def test_matrix_is_loaded_from_typescript_generated_runtime_manifest():
    manifest_path = (
        Path(__file__).parents[1]
        / "registry"
        / "prompt_checks"
        / "agent_tool_contract_manifest_v1.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        row["agent_id"]: tuple(row["allowed_tools"]) for row in manifest["agents"]
    }
    assert AGENT_TOOL_MATRIX == expected


def test_prepare_materializes_once_and_calls_read_only_bundle_payload(tmp_path):
    now = [datetime(2026, 7, 9, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    calls: list[tuple[str, str, str, str, str]] = []

    def materializer(
        tool_id: str, *, agent_id: str, stage: str, as_of: str, graph_run_id: str
    ) -> str:
        calls.append((tool_id, agent_id, stage, as_of, graph_run_id))
        return f'{{"tool":"{tool_id}","frozen":true}}'

    prepared = store.prepare(_request(), materializer=materializer)
    envelope = prepared["capability"]
    assert calls == [
        ("get_china_macro_snapshot", "china", "china", "2026-07-09", "graph-1")
    ]
    assert prepared["bundle"]["tool_payload_hashes"].keys() == {
        "get_china_macro_snapshot"
    }
    assert prepared["bundle"]["runtime_input_hash"].startswith("sha256:")
    assert prepared["bundle"]["candidate_scope_hash"] is None

    metadata = store.list_tools(envelope)
    assert metadata == [
        {
            "name": "get_china_macro_snapshot",
            "description": "Return the frozen China macro snapshot for this run.",
            "args_schema": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        }
    ]
    assert store.call_tool(envelope, "get_china_macro_snapshot", {}) == (
        '{"tool":"get_china_macro_snapshot","frozen":true}'
    )
    assert len(calls) == 1
    with pytest.raises(ValueError, match="already been used"):
        store.call_tool(envelope, "get_china_macro_snapshot", {})


def test_zero_args_wrong_tool_signature_and_termination_fail_closed(tmp_path):
    now = [datetime(2026, 7, 9, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    prepared = store.prepare(
        _request(),
        materializer=lambda *_args, **_kwargs: "frozen payload",
    )
    envelope = prepared["capability"]
    with pytest.raises(ValueError, match="accept no arguments"):
        store.call_tool(envelope, "get_china_macro_snapshot", {"as_of_date": "2099-01-01"})
    with pytest.raises(ValueError, match="not allowed"):
        store.call_tool(envelope, "get_us_macro_snapshot", {})

    tampered = {
        **envelope,
        "manifest": {**envelope["manifest"], "agent_id": "us_economy"},
    }
    with pytest.raises(ValueError, match="signature"):
        store.list_tools(tampered)

    store.terminate(envelope, "node_finished")
    with pytest.raises(ValueError, match="terminated"):
        store.list_tools(envelope)
    with pytest.raises(ValueError, match="terminated"):
        store.call_tool(envelope, "get_china_macro_snapshot", {})


def test_expiry_and_materialization_request_replay_are_rejected(tmp_path):
    now = [datetime(2026, 7, 9, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    request = _request()
    prepared = store.prepare(
        request,
        materializer=lambda *_args, **_kwargs: "frozen payload",
    )
    now[0] += timedelta(seconds=61)
    with pytest.raises(ValueError, match="expired"):
        store.list_tools(prepared["capability"])

    now[0] -= timedelta(seconds=61)
    replay_materializer_called = False

    def forbidden_materializer(*_args, **_kwargs):
        nonlocal replay_materializer_called
        replay_materializer_called = True
        raise AssertionError("a replay must be rejected before materialization")

    with pytest.raises(ValueError, match="already been used"):
        store.prepare(
            request,
            materializer=forbidden_materializer,
        )
    assert replay_materializer_called is False


def test_multi_tool_capability_has_one_atomic_use_slot_per_tool(tmp_path):
    now = [datetime(2026, 7, 9, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    prepared = store.prepare(
        _request("cro"),
        materializer=lambda tool_id, **_kwargs: f"payload:{tool_id}",
    )
    envelope = prepared["capability"]
    assert [row["name"] for row in store.list_tools(envelope)] == [
        "get_cro_risk_snapshot",
        "get_role_event_snapshot",
    ]
    assert store.call_tool(envelope, "get_cro_risk_snapshot", {}) == (
        "payload:get_cro_risk_snapshot"
    )
    assert store.call_tool(envelope, "get_role_event_snapshot", {}) == (
        "payload:get_role_event_snapshot"
    )


def test_paired_nodes_get_distinct_capabilities_for_the_same_root_bundle(tmp_path):
    now = [datetime(2026, 7, 9, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    root = store.prepare(
        _request(), materializer=lambda *_args, **_kwargs: "frozen payload"
    )
    issued = store.issue_for_bundle(
        {
            "graph_run_id": "graph-1",
            "run_slot_id": "slot-china-candidate",
            "run_id": "run-candidate",
            "node_id": "node-china-candidate",
            "agent_id": "china",
            "stage": "china",
            "as_of": "2026-07-09",
            "snapshot_bundle_id": root["bundle"]["snapshot_bundle_id"],
            "snapshot_bundle_hash": root["bundle"]["snapshot_bundle_hash"],
        }
    )
    assert issued["bundle"] == root["bundle"]
    assert (
        issued["capability"]["manifest"]["capability_id"]
        != root["capability"]["manifest"]["capability_id"]
    )
    assert store.call_tool(
        root["capability"], "get_china_macro_snapshot", {}
    ) == "frozen payload"
    assert store.call_tool(
        issued["capability"], "get_china_macro_snapshot", {}
    ) == "frozen payload"
    store.terminate(root["capability"], "champion_finished")
    assert store.list_tools(issued["capability"])

    with pytest.raises(ValueError, match="does not match"):
        store.issue_for_bundle(
            {
                "graph_run_id": "graph-1",
                "run_slot_id": "slot-us",
                "run_id": "run-us",
                "node_id": "node-us",
                "agent_id": "us_economy",
                "stage": "us_economy",
                "as_of": "2026-07-09",
                "snapshot_bundle_id": root["bundle"]["snapshot_bundle_id"],
                "snapshot_bundle_hash": root["bundle"]["snapshot_bundle_hash"],
            }
        )


def test_capability_ledger_tables_reject_update_and_delete(tmp_path):
    now = [datetime(2026, 7, 9, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    prepared = store.prepare(
        _request(), materializer=lambda *_args, **_kwargs: "frozen payload"
    )
    store.call_tool(prepared["capability"], "get_china_macro_snapshot", {})
    store.terminate(prepared["capability"], "node_finished")

    with sqlite3.connect(store.db_path) as conn:
        for table in (
            "snapshot_bundles",
            "materialization_requests",
            "capabilities",
            "capability_events",
            "capability_tool_uses",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                conn.execute(f"DELETE FROM {table}")

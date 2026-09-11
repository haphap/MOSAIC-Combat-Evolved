from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

import mosaic.bridge.tool_capabilities as capability_module
from mosaic.bridge.tool_capabilities import AgentToolCapabilityStore
from mosaic.dataflows.bound_runtime_production import ActiveAdaptiveQueryPreparer
from mosaic.dataflows.frozen_adaptive_queries import (
    CALL_TIME_ARGUMENT_CONTRACT,
    FrozenAdaptiveQueryStore,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l3_l4_preservation import build_l3_l4_preservation_overlay
from mosaic.scorecard.l3_l4_preservation import L3_TOOL_ROSTER


ROOT = Path(__file__).parents[1]


def _l4_scope() -> dict:
    return {
        "as_of": "2026-07-09",
        "accepted_candidate_tickers": ["600519.SH"],
        "accepted_output_set_hash": canonical_hash({"accepted": "l1-l3"}),
        "account_positions_policy_hash": canonical_hash({"positions": "current"}),
        "market_liquidity_vintage_hash": canonical_hash({"market": "2026-07-09"}),
    }


def _request() -> dict:
    return {
        "graph_run_id": "graph-cro",
        "run_slot_id": "slot-cro",
        "run_id": "run-cro",
        "node_id": "node-cro",
        "agent_id": "cro",
        "stage": "cro",
        "as_of": "2026-07-09",
        "materialization_request_id": "materialize-cro",
        "runtime_inputs": {},
        "candidate_scope": {"scope_id": "scope-cro"},
        "ttl_seconds": 60,
    }


@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize(
    ("agent_id", "stage", "preservation_stage"),
    [
        ("alpha_discovery", "alpha_discovery", "alpha_discovery"),
        ("cro", "cro", "cro_review"),
        ("autonomous_execution", "autonomous_execution", "execution_feasibility"),
        ("cio", "cio_proposal", "cio_proposal"),
        ("cio", "cio_final", "cio_final"),
    ],
)
def test_l4_capability_serves_frozen_initial_prior_without_adaptive_session(
    tmp_path: Path, agent_id: str, stage: str, preservation_stage: str, deferred: bool
) -> None:
    now = datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc)
    frozen = FrozenAdaptiveQueryStore(
        tmp_path / "frozen.sqlite3", clock=lambda: now
    )
    prior_payload = json.dumps({"kind": "rke-prior", "shadow_only": True})

    def materializer(tool_id: str, args: dict) -> dict:
        return {
            "payload": prior_payload,
            "source_receipt_hashes": [canonical_hash({"tool_id": tool_id, "args": args})],
        }

    prepared_query = frozen.prepare(
        agent_id=agent_id,
        stage=stage,
        preservation_stage=preservation_stage,
        as_of="2026-07-09",
        authorized_scope=_l4_scope(),
        initial_query_requests=[
            {
                "tool_id": "get_rke_research_context",
                "args": {
                    "agent_id": agent_id,
                    "as_of": "2026-07-09",
                    "layer": "decision",
                    "max_items": 3,
                },
            }
        ],
        query_requests=[],
        preservation_overlay=build_l3_l4_preservation_overlay(ROOT),
        materializer=materializer,
        defer_materialization=deferred,
    )

    def finalizer(context: dict) -> dict:
        return {
            "agent_id": context["agent_id"],
            "stage": context["stage"],
            "as_of": context["as_of"],
            "status": "READY",
            "tool_ids": sorted(context["initial_snapshot_tool_ids"]),
            "build_receipt_hashes": {
                tool_id: canonical_hash({"tool_id": tool_id})
                for tool_id in context["initial_snapshot_tool_ids"]
            },
            "materialization_attempt_receipt_hash": None,
            "deferred_tool_ids": sorted(context["deferred_tool_ids"]),
            "deferred_query_bundle_hash": context["adaptive_query"]["bundle_hash"],
            "deferred_query_call_contract": CALL_TIME_ARGUMENT_CONTRACT,
        }

    store = AgentToolCapabilityStore(
        tmp_path / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: now,
        adaptive_query_store=frozen,
        adaptive_query_preparer=(
            ActiveAdaptiveQueryPreparer(
                sector_relationship_preparer=lambda **_kwargs: pytest.fail("L4 is bound"),
                bound_runtime_preparer=lambda **_kwargs: prepared_query,
            )
            if deferred
            else lambda **_kwargs: prepared_query
        ),
        adaptive_query_materializer=materializer,
        stage_materialization_finalizer=finalizer if deferred else None,
        require_knot_v2_audit_authority=deferred,
    )
    result = store.prepare(
        {**_request(), "agent_id": agent_id, "stage": stage},
        materializer=lambda tool_id, **_kwargs: json.dumps(
            {"tool": tool_id, "snapshot": True}, sort_keys=True
        ),
    )
    envelope = result["capability"]

    assert store.call_tool(envelope, "get_rke_research_context", {}) == prior_payload
    with pytest.raises(
        ValueError, match="does not permit|unavailable|not uniquely authorized"
    ):
        store.call_tool(
            envelope,
            "get_rke_research_context",
            {
                "agent_id": agent_id,
                "as_of": "2026-07-10",
                "layer": "decision",
                "max_items": 3,
            },
        )
    with sqlite3.connect(store.db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM capability_adaptive_sessions"
            ).fetchone()[0]
            == 0
        )

    reissued = store.issue_for_bundle(
        {
            "graph_run_id": "graph-cro",
            "run_slot_id": "slot-cro-reissue",
            "run_id": "run-cro-2",
            "node_id": "node-cro-reissue",
            "agent_id": agent_id,
            "stage": stage,
            "as_of": "2026-07-09",
            "snapshot_bundle_id": result["bundle"]["snapshot_bundle_id"],
            "snapshot_bundle_hash": result["bundle"]["snapshot_bundle_hash"],
            "ttl_seconds": 60,
        }
    )
    assert (
        store.call_tool(
            reissued["capability"], "get_rke_research_context", {}
        )
        == prior_payload
    )


def test_deferred_call_prefers_exact_replayed_initial_before_follow_up(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc)
    frozen = FrozenAdaptiveQueryStore(tmp_path / "frozen.sqlite3", clock=lambda: now)
    overlay = build_l3_l4_preservation_overlay(ROOT)
    initial_requests = [
        {
            "tool_id": "get_fundamentals",
            "args": {"ticker": "600519.SH", "as_of": "2026-07-09"},
        },
        {
            "tool_id": "get_cashflow",
            "args": {
                "ticker": "600519.SH",
                "frequency": "annual",
                "as_of": "2026-07-09",
            },
        },
    ]
    follow_up_requests = [
        {
            "tool_id": "get_income_statement",
            "args": {
                "ticker": "600519.SH",
                "frequency": "quarterly",
                "as_of": "2026-07-09",
            },
        }
    ]
    scope = {
        "as_of": "2026-07-09",
        "earliest_date": "2026-06-01",
        "accepted_candidate_tickers": ["600519.SH"],
        "indicator_families": ["macd", "rsi"],
        "candidate_scope_hash": canonical_hash({"scope": "ackman"}),
        "candidate_universe_hash": canonical_hash({"universe": "accepted"}),
        "source_snapshot_hash": canonical_hash({"snapshot": "layer2"}),
    }

    def materializer(tool_id: str, args: dict) -> dict:
        return {
            "payload": json.dumps({"tool_id": tool_id, "args": args}, sort_keys=True),
            "source_receipt_hashes": [],
        }

    prepared_query = frozen.prepare(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-07-09",
        authorized_scope=scope,
        initial_query_requests=initial_requests,
        query_requests=follow_up_requests,
        preservation_overlay=overlay,
        materializer=materializer,
        defer_materialization=True,
    )
    adaptive_tools = tuple(
        tool_id
        for tool_id in L3_TOOL_ROSTER["ackman"]
        if tool_id != "get_superinvestor_candidate_snapshot"
    )
    store = AgentToolCapabilityStore(
        tmp_path / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: now,
        adaptive_query_store=frozen,
        adaptive_query_preparer=ActiveAdaptiveQueryPreparer(
            sector_relationship_preparer=lambda **_kwargs: pytest.fail(
                "bound L3 stage must not use the Sector preparer"
            ),
            bound_runtime_preparer=lambda **_kwargs: prepared_query,
        ),
        adaptive_query_materializer=materializer,
        stage_materialization_finalizer=lambda context: {
            "agent_id": context["agent_id"],
            "stage": context["stage"],
            "as_of": context["as_of"],
            "status": "READY",
            "tool_ids": sorted(context["initial_snapshot_tool_ids"]),
            "build_receipt_hashes": {
                tool_id: canonical_hash(
                    {"tool_id": tool_id, "payload_hash": context["tool_payload_hashes"][tool_id]}
                )
                for tool_id in context["initial_snapshot_tool_ids"]
            },
            "materialization_attempt_receipt_hash": None,
            "deferred_tool_ids": sorted(adaptive_tools),
            "deferred_query_bundle_hash": context["adaptive_query"]["bundle_hash"],
            "deferred_query_call_contract": CALL_TIME_ARGUMENT_CONTRACT,
        },
        require_knot_v2_audit_authority=True,
    )
    result = store.prepare(
        {
            "graph_run_id": "graph-ackman",
            "run_slot_id": "slot-ackman",
            "run_id": "run-ackman",
            "node_id": "node-ackman",
            "agent_id": "ackman",
            "stage": "ackman",
            "as_of": "2026-07-09",
            "materialization_request_id": "materialize-ackman",
            "runtime_inputs": {},
            "candidate_scope": None,
            "ttl_seconds": 60,
        },
        materializer=lambda tool_id, **_kwargs: json.dumps(
            {"tool_id": tool_id, "snapshot": True}, sort_keys=True
        ),
    )

    replayed = store.call_tool_result(
        result["capability"], "get_fundamentals", initial_requests[0]["args"]
    )
    assert json.loads(replayed["text"]) == {
        "tool_id": "get_fundamentals",
        "args": initial_requests[0]["args"],
    }
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute(
            "SELECT call_mode FROM tool_result_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()[0] == "INITIAL"
    with pytest.raises(ValueError, match="frozen follow-up request"):
        store.call_tool_result(
            result["capability"],
            "get_fundamentals",
            {"ticker": "000001.SZ", "as_of": "2026-07-09"},
        )


def test_l3_empty_scope_issues_zero_count_descriptors_and_no_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc)
    frozen = FrozenAdaptiveQueryStore(
        tmp_path / "frozen.sqlite3", clock=lambda: now
    )
    scope = {
        "as_of": "2026-07-09",
        "earliest_date": "2026-06-01",
        "accepted_candidate_tickers": [],
        "indicator_families": [],
        "candidate_scope_hash": canonical_hash({"scope": "empty"}),
        "candidate_universe_hash": canonical_hash({"universe": []}),
        "source_snapshot_hash": canonical_hash({"snapshot": "empty"}),
    }
    prepared_query = frozen.prepare(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-07-09",
        authorized_scope=scope,
        initial_query_requests=[],
        query_requests=[],
        preservation_overlay=build_l3_l4_preservation_overlay(ROOT),
        materializer=lambda *_args: pytest.fail("empty scope must not materialize queries"),
    )
    tools = (
        "get_superinvestor_candidate_snapshot",
        "get_fundamentals",
        "get_cashflow",
    )
    monkeypatch.setitem(capability_module.AGENT_TOOL_MATRIX, "ackman", tools)
    store = AgentToolCapabilityStore(
        tmp_path / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: now,
        adaptive_query_store=frozen,
        adaptive_query_preparer=lambda **_kwargs: prepared_query,
    )
    request = {
        **_request(),
        "graph_run_id": "graph-ackman",
        "run_slot_id": "slot-ackman",
        "run_id": "run-ackman",
        "node_id": "node-ackman",
        "agent_id": "ackman",
        "stage": "ackman",
        "materialization_request_id": "materialize-ackman",
    }

    result = store.prepare(
        request,
        materializer=lambda tool_id, **_kwargs: json.dumps(
            {"tool": tool_id, "snapshot": True}, sort_keys=True
        ),
    )

    assert result["prepared_initial_tool_ids"] == []
    listed = {row["name"]: row for row in store.list_tools(result["capability"])}
    assert set(listed["get_fundamentals"]["args_schema"]["properties"]) == {
        "ticker",
        "as_of",
    }
    assert listed["get_fundamentals"]["args_schema"]["additionalProperties"] is False
    with sqlite3.connect(store.db_path) as connection:
        payloads = json.loads(
            connection.execute(
                "SELECT payloads_json FROM snapshot_bundles WHERE snapshot_bundle_id = ?",
                (result["bundle"]["snapshot_bundle_id"],),
            ).fetchone()[0]
        )
    for tool_id in tools[1:]:
        descriptor = json.loads(payloads[tool_id])
        assert descriptor["prepared_request_count"] == 0
        assert descriptor["prepared_initial_count"] == 0
        assert descriptor["adaptive_max_rounds"] == 0
        with pytest.raises(ValueError, match="initial payload is unavailable"):
            store.call_tool(result["capability"], tool_id, {})
    with sqlite3.connect(store.db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM capability_adaptive_sessions"
            ).fetchone()[0]
            == 0
        )

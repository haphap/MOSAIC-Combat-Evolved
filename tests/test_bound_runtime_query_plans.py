from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.dataflows.bound_runtime_query_plans import (
    build_bound_runtime_query_plan,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l3_l4_preservation import L3_TOOL_ROSTER


ROOT = Path(__file__).parents[1]


def _snapshot(
    *, agent_id: str, stage: str, candidates: list[dict], as_of: str = "2026-08-06"
) -> dict:
    candidate_body = {
        "candidate_status": "AVAILABLE" if candidates else "EMPTY_CONFIRMED",
        "candidate_universe": candidates,
    }
    candidate_hash = canonical_hash(candidate_body)
    constraints = {"evidence_ids": ["policy-evidence"]}
    role_context = {
        "context_kind": "TEST_BOUND_RUNTIME",
        "position_snapshot_hash": canonical_hash({"positions": agent_id}),
        "liquidity_vintage_hash": canonical_hash({"liquidity": stage}),
        "evidence_ids": ["position-evidence"],
    }
    candidate_scope = {
        "candidate_universe_id": "candidate-universe:" + candidate_hash[7:],
        "candidate_universe_hash": candidate_hash,
        "constraint_set_id": "constraint-set:" + canonical_hash(constraints)[7:],
        "constraint_set_hash": canonical_hash(constraints),
    }
    body = {
        "schema_version": "test_bound_runtime_snapshot_v1",
        "contract_version": "test_bound_runtime_snapshot_v1",
        "snapshot_id": "runtime-snapshot:test",
        "graph_run_id": "graph-test",
        "agent_id": agent_id,
        "stage": stage,
        "as_of": as_of,
        "generated_at": f"{as_of}T16:30:00+08:00",
        "pit_status": "VERIFIED",
        "candidate_scope": candidate_scope,
        "candidate_scope_hash": canonical_hash(candidate_scope),
        "candidate_universe_id": candidate_scope["candidate_universe_id"],
        "candidate_universe_hash": candidate_hash,
        **candidate_body,
        "constraint_set_id": candidate_scope["constraint_set_id"],
        "constraint_set_hash": canonical_hash(constraints),
        "constraints": constraints,
        "role_context": role_context,
        "role_context_hash": canonical_hash(role_context),
        "upstream_accepted_output_refs": [
            {
                "accepted_output_kind": "STANDARD_SECTOR_SELECTION",
                "agent_id": "consumer",
                "stage": "consumer",
                "as_of": as_of,
                "accepted_output_id": "accepted:test",
                "accepted_output_hash": canonical_hash({"accepted": agent_id}),
                "evidence_ids": ["accepted-evidence"],
            }
        ],
        "evidence_ledger": [],
    }
    return {**body, "snapshot_hash": canonical_hash(body)}


def _payload(snapshot: dict) -> str:
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))


def test_l3_plan_derives_exact_candidate_scope_and_finite_legacy_queries() -> None:
    snapshot = _snapshot(
        agent_id="ackman",
        stage="ackman",
        candidates=[
            {
                "candidate_ref": "candidate:2",
                "ts_code": "000858.SZ",
                "source_sector_agent_id": "consumer",
                "source_direction_id": "baijiu",
            },
            {
                "candidate_ref": "candidate:1",
                "ts_code": "600519.SH",
                "source_sector_agent_id": "consumer",
            },
        ],
    )

    plan = build_bound_runtime_query_plan(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-08-06",
        initial_payloads={"get_superinvestor_candidate_snapshot": _payload(snapshot)},
        allowed_tools=L3_TOOL_ROSTER["ackman"],
    )

    assert plan["preservation_stage"] == "ackman"
    assert plan["authorized_scope"]["accepted_candidate_tickers"] == [
        "000858.SZ",
        "600519.SH",
    ]
    assert plan["authorized_scope"]["candidate_scope_hash"] == snapshot[
        "candidate_scope_hash"
    ]
    assert plan["authorized_scope"]["candidate_universe_hash"] == snapshot[
        "candidate_universe_hash"
    ]
    assert plan["authorized_scope"]["source_snapshot_hash"] == snapshot[
        "snapshot_hash"
    ]
    assert plan["initial_query_requests"] == [
        {
            "tool_id": "get_fundamentals",
            "args": {"ticker": "000858.SZ", "as_of": "2026-08-06"},
        },
        {
            "tool_id": "get_cashflow",
            "args": {
                "ticker": "000858.SZ",
                "frequency": "annual",
                "as_of": "2026-08-06",
            },
        },
    ]
    assert {row["tool_id"] for row in plan["query_requests"]} == set(
        L3_TOOL_ROSTER["ackman"]
    )
    rke_request = next(
        row
        for row in plan["query_requests"]
        if row["tool_id"] == "get_rke_research_context"
        and row["args"]["ticker"] == "000858.SZ"
    )
    assert rke_request["args"]["sector"] == "baijiu"
    assert not {
        (row["tool_id"], canonical_hash(row["args"]))
        for row in plan["initial_query_requests"]
    } & {
        (row["tool_id"], canonical_hash(row["args"]))
        for row in plan["query_requests"]
    }


def test_druckenmiller_policy_queries_use_candidate_sector_topic() -> None:
    snapshot = _snapshot(
        agent_id="druckenmiller",
        stage="druckenmiller",
        candidates=[
            {
                "candidate_ref": "candidate:energy",
                "ts_code": "600028.SH",
                "source_sector_agent_id": "energy",
            },
            {
                "candidate_ref": "candidate:consumer",
                "ts_code": "600519.SH",
                "source_sector_agent_id": "consumer",
            },
        ],
    )
    plan = build_bound_runtime_query_plan(
        agent_id="druckenmiller",
        stage="druckenmiller",
        as_of="2026-08-06",
        initial_payloads={
            "get_superinvestor_candidate_snapshot": _payload(snapshot)
        },
        allowed_tools=L3_TOOL_ROSTER["druckenmiller"],
    )

    policy_args = sorted(
        (
            row["args"]
            for row in plan["query_requests"]
            if row["tool_id"] == "get_industry_policy_digest"
        ),
        key=lambda args: args["lookback_days"],
    )
    assert policy_args == [
        {
            "as_of": "2026-08-06",
            "lookback_days": lookback,
            "source": "govcn",
            "topic": "煤炭",
        }
        for lookback in (7, 30, 90)
    ]

    unknown = _snapshot(
        agent_id="druckenmiller",
        stage="druckenmiller",
        candidates=[
            {
                "candidate_ref": "candidate:unknown",
                "ts_code": "600028.SH",
                "source_sector_agent_id": "unknown",
            }
        ],
    )
    with pytest.raises(ValueError, match="exact Sector policy topic"):
        build_bound_runtime_query_plan(
            agent_id="druckenmiller",
            stage="druckenmiller",
            as_of="2026-08-06",
            initial_payloads={
                "get_superinvestor_candidate_snapshot": _payload(unknown)
            },
            allowed_tools=L3_TOOL_ROSTER["druckenmiller"],
        )


def test_l4_plan_translates_active_stage_and_builds_only_proactive_prior() -> None:
    snapshot = _snapshot(
        agent_id="cro",
        stage="cro",
        candidates=[
            {
                "candidate_ref": "candidate:cro",
                "ts_code": "600519.SH",
            }
        ],
    )

    plan = build_bound_runtime_query_plan(
        agent_id="cro",
        stage="cro",
        as_of="2026-08-06",
        initial_payloads={"get_cro_risk_snapshot": _payload(snapshot)},
        allowed_tools=("get_rke_research_context",),
    )

    assert plan["preservation_stage"] == "cro_review"
    assert plan["query_requests"] == []
    assert plan["initial_query_requests"] == [
        {
            "tool_id": "get_rke_research_context",
            "args": {
                "agent_id": "cro",
                "as_of": "2026-08-06",
                "layer": "decision",
                "max_items": 3,
            },
        }
    ]
    assert plan["authorized_scope"]["accepted_candidate_tickers"] == [
        "600519.SH"
    ]
    assert plan["authorized_scope"]["accepted_output_set_hash"] == canonical_hash(
        snapshot["upstream_accepted_output_refs"]
    )


def test_l3_empty_candidate_scope_produces_no_private_queries() -> None:
    snapshot = _snapshot(
        agent_id="ackman",
        stage="ackman",
        candidates=[],
    )

    plan = build_bound_runtime_query_plan(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-08-06",
        initial_payloads={"get_superinvestor_candidate_snapshot": _payload(snapshot)},
        allowed_tools=L3_TOOL_ROSTER["ackman"],
    )

    assert plan["authorized_scope"]["accepted_candidate_tickers"] == []
    assert plan["initial_query_requests"] == []
    assert plan["query_requests"] == []


def test_bound_plan_rejects_snapshot_hash_and_tool_surface_drift() -> None:
    snapshot = _snapshot(
        agent_id="ackman",
        stage="ackman",
        candidates=[
            {
                "candidate_ref": "candidate:1",
                "ts_code": "600519.SH",
                "source_sector_agent_id": "consumer",
            }
        ],
    )
    snapshot["candidate_universe"][0]["ts_code"] = "000001.SZ"
    with pytest.raises(ValueError, match="snapshot hash"):
        build_bound_runtime_query_plan(
            agent_id="ackman",
            stage="ackman",
            as_of="2026-08-06",
            initial_payloads={"get_superinvestor_candidate_snapshot": _payload(snapshot)},
            allowed_tools=L3_TOOL_ROSTER["ackman"],
        )

    druckenmiller = _snapshot(
        agent_id="druckenmiller",
        stage="druckenmiller",
        candidates=[],
    )
    runtime_order = (
        "get_fundamentals",
        "get_indicators",
        "get_industry_policy_digest",
        "get_rke_research_context",
        "get_stock_data",
        "get_stock_research",
        "get_yield_curve_cn",
    )
    plan = build_bound_runtime_query_plan(
        agent_id="druckenmiller",
        stage="druckenmiller",
        as_of="2026-08-06",
        initial_payloads={
            "get_superinvestor_candidate_snapshot": _payload(druckenmiller)
        },
        allowed_tools=runtime_order,
    )
    assert plan["preservation_stage"] == "druckenmiller"
    with pytest.raises(ValueError, match="allowed tools"):
        build_bound_runtime_query_plan(
            agent_id="druckenmiller",
            stage="druckenmiller",
            as_of="2026-08-06",
            initial_payloads={
                "get_superinvestor_candidate_snapshot": _payload(druckenmiller)
            },
            allowed_tools=runtime_order[:-1],
        )

    valid = _snapshot(
        agent_id="cro",
        stage="cro",
        candidates=[{"candidate_ref": "candidate:cro", "ts_code": "600519.SH"}],
    )
    with pytest.raises(ValueError, match="allowed tools"):
        build_bound_runtime_query_plan(
            agent_id="cro",
            stage="cro",
            as_of="2026-08-06",
            initial_payloads={"get_cro_risk_snapshot": _payload(valid)},
            allowed_tools=("get_stock_data",),
        )


def test_bound_plan_rejects_candidate_status_drift() -> None:
    snapshot = _snapshot(
        agent_id="ackman",
        stage="ackman",
        candidates=[],
    )
    snapshot["candidate_status"] = "AVAILABLE"
    snapshot["candidate_universe_hash"] = canonical_hash(
        {"candidate_status": "AVAILABLE", "candidate_universe": []}
    )
    body = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    snapshot["snapshot_hash"] = canonical_hash(body)

    with pytest.raises(ValueError, match="candidate status"):
        build_bound_runtime_query_plan(
            agent_id="ackman",
            stage="ackman",
            as_of="2026-08-06",
            initial_payloads={"get_superinvestor_candidate_snapshot": _payload(snapshot)},
            allowed_tools=L3_TOOL_ROSTER["ackman"],
        )

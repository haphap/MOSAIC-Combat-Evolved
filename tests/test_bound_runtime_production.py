from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mosaic.dataflows.bound_runtime_production import (
    ActiveAdaptiveQueryPreparer,
    BoundRuntimeAdaptiveQueryPreparer,
)
from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l3_l4_preservation import (
    L3_TOOL_ROSTER,
    build_l3_l4_preservation_overlay,
)


ROOT = Path(__file__).parents[1]


def _snapshot(*, agent_id: str = "ackman", stage: str = "ackman") -> dict:
    candidates = [
        {
            "candidate_ref": "candidate:1",
            "ts_code": "600519.SH",
            "source_sector_agent_id": "consumer",
        }
    ]
    candidate_body = {"candidate_status": "AVAILABLE", "candidate_universe": candidates}
    candidate_hash = canonical_hash(candidate_body)
    constraints = {"evidence_ids": ["policy-evidence"]}
    role_context = {
        "context_kind": "TEST",
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
        "agent_id": agent_id,
        "stage": stage,
        "as_of": "2026-08-06",
        "pit_status": "VERIFIED",
        "candidate_scope": candidate_scope,
        "candidate_scope_hash": canonical_hash(candidate_scope),
        "candidate_universe_hash": candidate_hash,
        **candidate_body,
        "constraint_set_hash": canonical_hash(constraints),
        "constraints": constraints,
        "role_context": role_context,
        "role_context_hash": canonical_hash(role_context),
        "upstream_accepted_output_refs": [],
    }
    return {**body, "snapshot_hash": canonical_hash(body)}


class _FrozenStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def prepare(self, **kwargs):
        self.calls.append(kwargs)
        return {"bundle_id": "frozen-bound", "public_projection": {"ok": True}}


def test_bound_preparer_passes_active_and_preservation_stage_to_frozen_store() -> None:
    frozen = _FrozenStore()
    materializer = object()
    preparer = BoundRuntimeAdaptiveQueryPreparer(
        root=ROOT,
        frozen_store=frozen,
        materializer=materializer,
    )

    result = preparer(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-08-06",
        initial_payloads={
            "get_superinvestor_candidate_snapshot": json.dumps(_snapshot())
        },
        runtime_inputs={},
        candidate_scope=None,
        allowed_tools=L3_TOOL_ROSTER["ackman"],
    )

    assert result["bundle_id"] == "frozen-bound"
    call = frozen.calls[0]
    assert call["stage"] == "ackman"
    assert call["preservation_stage"] == "ackman"
    assert call["materializer"] is materializer
    assert call["initial_query_requests"][0]["tool_id"] == "get_fundamentals"


def test_active_dispatcher_routes_only_l3_l4_roster_to_bound_preparer() -> None:
    calls: list[str] = []

    def sector(**_kwargs):
        calls.append("sector")
        return {"bundle_id": "sector", "public_projection": {}}

    def bound(**_kwargs):
        calls.append("bound")
        return {"bundle_id": "bound", "public_projection": {}}

    dispatcher = ActiveAdaptiveQueryPreparer(
        sector_relationship_preparer=sector,
        bound_runtime_preparer=bound,
    )
    common = {
        "as_of": "2026-08-06",
        "initial_payloads": {},
        "runtime_inputs": {},
        "candidate_scope": None,
        "allowed_tools": (),
    }
    assert dispatcher(agent_id="financials", stage="financials", **common)[
        "bundle_id"
    ] == "sector"
    assert dispatcher(agent_id="cro", stage="cro", **common)["bundle_id"] == "bound"
    assert calls == ["sector", "bound"]


@pytest.mark.parametrize(
    ("agent_id", "stage", "snapshot_tool", "preservation_stage"),
    [
        ("ackman", "ackman", "get_superinvestor_candidate_snapshot", "ackman"),
        ("burry", "burry", "get_superinvestor_candidate_snapshot", "burry"),
        ("munger", "munger", "get_superinvestor_candidate_snapshot", "munger"),
        (
            "druckenmiller",
            "druckenmiller",
            "get_superinvestor_candidate_snapshot",
            "druckenmiller",
        ),
        (
            "alpha_discovery",
            "alpha_discovery",
            "get_alpha_candidate_snapshot",
            "alpha_discovery",
        ),
        ("cro", "cro", "get_cro_risk_snapshot", "cro_review"),
        (
            "autonomous_execution",
            "autonomous_execution",
            "get_execution_snapshot",
            "execution_feasibility",
        ),
        ("cio", "cio_proposal", "get_cio_decision_snapshot", "cio_proposal"),
        ("cio", "cio_final", "get_cio_decision_snapshot", "cio_final"),
    ],
)
def test_all_bound_stages_publish_real_frozen_query_bundles(
    tmp_path: Path,
    agent_id: str,
    stage: str,
    snapshot_tool: str,
    preservation_stage: str,
) -> None:
    overlay = build_l3_l4_preservation_overlay(ROOT)
    bindings = {
        row["tool_id"]: row
        for row in overlay["bindings"]
        if row["agent_id"] == agent_id and row["stage"] == preservation_stage
    }
    materialized: list[tuple[str, dict]] = []

    def materializer(tool_id: str, args: dict) -> dict:
        materialized.append((tool_id, args))
        result = {
            "payload": json.dumps({"tool_id": tool_id, "args": args}, sort_keys=True),
            "source_receipt_hashes": [canonical_hash({"tool_id": tool_id, "args": args})],
        }
        derivation_contract = bindings[tool_id]["materializer_contract"][
            "derivation_contract"
        ]
        if all(
            derivation_contract.get(field) is True
            for field in (
                "model_hash_required",
                "prompt_hash_required",
                "source_payload_hash_required",
            )
        ):
            result["derivation"] = {
                "derivation_contract_version": derivation_contract["contract_version"],
                "model_hash": canonical_hash({"model": "test"}),
                "prompt_hash": canonical_hash({"prompt": "test"}),
                "source_payload_hash": canonical_hash({"source": tool_id, "args": args}),
            }
        return result

    frozen = FrozenAdaptiveQueryStore(
        tmp_path / f"{agent_id}-{stage}.sqlite3",
        clock=lambda: datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc),
    )
    preparer = BoundRuntimeAdaptiveQueryPreparer(
        root=ROOT,
        frozen_store=frozen,
        materializer=materializer,
    )
    allowed_tools = L3_TOOL_ROSTER.get(agent_id, ("get_rke_research_context",))

    prepared = preparer(
        agent_id=agent_id,
        stage=stage,
        as_of="2026-08-06",
        initial_payloads={snapshot_tool: json.dumps(_snapshot(agent_id=agent_id, stage=stage))},
        runtime_inputs={},
        candidate_scope=None,
        allowed_tools=allowed_tools,
    )

    projection = prepared["public_projection"]
    assert projection.get("preservation_stage", stage) == preservation_stage
    assert projection["private_payload_count"] == len(materialized)
    assert {row["tool_id"] for row in projection["entries"]} == set(allowed_tools)
    assert projection["adaptive_max_rounds"] == (3 if agent_id in L3_TOOL_ROSTER else 0)

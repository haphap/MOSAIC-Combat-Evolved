from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import mosaic.bridge.tool_capabilities as capability_module
from mosaic.bridge.tool_capabilities import (
    AGENT_TOOL_MATRIX,
    ALL_AGENT_IDS,
    AgentToolCapabilityStore,
    allowed_tools_for_agent,
    execution_stage_for_agent,
    materialize_tool_payload,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.scorecard.canonical_json import canonical_hash
from scripts.build_structured_smoke_fixtures import build_structured_smoke_fixtures


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


def _canonical_hash(value: object) -> str:
    return canonical_hash(value)


def _sector_budget(**overrides: object) -> dict:
    body = {
        "budget_contract_id": "sector-inference-budget",
        "budget_contract_version": "sector_inference_budget_v3",
        "direction_research_output_token_cap": 100,
        "conflict_review_output_token_reserve": 50,
        "final_selection_output_token_cap": 50,
        "total_stage_input_token_cap": 1_000,
        "total_stage_output_token_cap": 200,
        "maximum_model_subcalls": 3,
        "review_reserve_transfer_policy": "NON_TRANSFERABLE",
        "budget_breach_policy": "STAGE_REJECT",
        **overrides,
    }
    return {**body, "budget_contract_hash": _canonical_hash(body)}


def _bound_snapshot(
    *,
    tool_id: str,
    agent_id: str,
    stage: str,
    upstream_agent: str,
    upstream_stage: str,
    upstream_kind: str,
) -> dict:
    contract_versions = {
        "get_superinvestor_candidate_snapshot": "superinvestor_candidate_snapshot_v1",
        "get_cro_risk_snapshot": "cro_risk_snapshot_v1",
        "get_alpha_candidate_snapshot": "alpha_candidate_snapshot_v1",
        "get_execution_snapshot": "execution_snapshot_v1",
        "get_cio_decision_snapshot": "cio_decision_snapshot_v1",
    }
    def accepted_ref(
        index: int, *, agent: str, ref_stage: str, kind: str
    ) -> dict:
        return {
            "accepted_output_id": f"accepted-upstream-{index}",
            "accepted_output_hash": f"sha256:{str(index) * 64}",
            "accepted_output_kind": kind,
            "agent_id": agent,
            "stage": ref_stage,
            "as_of": "2026-07-09",
            "evidence_ids": [f"upstream-evidence-{index}"],
        }

    upstream_refs = [
        accepted_ref(
            1,
            agent=upstream_agent,
            ref_stage=upstream_stage,
            kind=upstream_kind,
        )
    ]
    if tool_id == "get_superinvestor_candidate_snapshot":
        upstream_refs.append(
            accepted_ref(
                2,
                agent="energy",
                ref_stage="energy",
                kind="STANDARD_SECTOR_SELECTION",
            )
        )
        candidates = [
            {
                "candidate_ref": "candidate-1",
                "ts_code": "600000.SH",
                "source_output_id": "accepted-upstream-2",
                "source_output_hash": f"sha256:{'2' * 64}",
                "source_sector_agent_id": "energy",
                "source_direction_id": "direction-energy-oil",
                "source_direction": "PREFERRED",
                "metrics": {"relative_strength_20d": 0.12},
                "evidence_ids": ["candidate-evidence"],
            }
        ]
        constraints = {
            "cash_only": False,
            "allow_new_positions": True,
            "max_pick_count": 5,
            "max_total_conviction": 1.0,
            "prohibited_ts_codes": [],
            "evidence_ids": ["constraint-evidence"],
        }
        role_context = {
            "context_kind": "SUPERINVESTOR_CANDIDATE_SELECTION",
            "candidate_origin_set_id": "sector-candidate-origin-set-1",
            "candidate_origin_set_hash": f"sha256:{'a' * 64}",
            "evidence_ids": ["context-evidence"],
        }
    elif tool_id == "get_alpha_candidate_snapshot":
        missing_superinvestors = [
            candidate
            for candidate in ("druckenmiller", "munger", "burry", "ackman")
            if candidate != upstream_agent
        ]
        next_index = 2
        for superinvestor in missing_superinvestors:
            upstream_refs.append(
                accepted_ref(
                    next_index,
                    agent=superinvestor,
                    ref_stage=superinvestor,
                    kind="SUPERINVESTOR_SELECTION",
                )
            )
            next_index += 1
        sector_ref_index = next_index
        upstream_refs.append(
            accepted_ref(
                sector_ref_index,
                agent="energy",
                ref_stage="energy",
                kind="STANDARD_SECTOR_SELECTION",
            )
        )
        candidates = [
            {
                "candidate_ref": "candidate-1",
                "ts_code": "600000.SH",
                "source_output_id": f"accepted-upstream-{sector_ref_index}",
                "source_output_hash": f"sha256:{str(sector_ref_index) * 64}",
                "source_agent_id": "energy",
                "source_candidate_ref": "energy-long-candidate-1",
                "omitted_by_superinvestor_agents": [
                    "druckenmiller",
                    "munger",
                    "burry",
                    "ackman",
                ],
                "metrics": {"relative_strength_20d": 0.12},
                "evidence_ids": ["candidate-evidence"],
            }
        ]
        constraints = {
            "cash_only": False,
            "allow_new_positions": True,
            "max_novel_pick_count": 5,
            "excluded_selected_ts_codes": [],
            "evidence_ids": ["constraint-evidence"],
        }
        role_context = {
            "context_kind": "ALPHA_NOVELTY_SEARCH",
            "superinvestor_selection_set_id": "superinvestor-selection-set-1",
            "superinvestor_selection_set_hash": f"sha256:{'a' * 64}",
            "excluded_security_set_id": "excluded-security-set-1",
            "excluded_security_set_hash": f"sha256:{'b' * 64}",
            "evidence_ids": ["context-evidence"],
        }
    elif tool_id == "get_cro_risk_snapshot":
        candidates = [
            {
                "candidate_ref": "candidate-1",
                "ts_code": "600000.SH",
                "proposal_position_ref": "proposal-position-1",
                "current_weight": 0.03,
                "proposed_target_weight": 0.04,
                "proposed_delta_weight": 0.01,
                "sector_id": "energy",
                "metrics": {"relative_strength_20d": 0.12},
                "evidence_ids": ["candidate-evidence"],
            }
        ]
        constraints = {
            "max_total_target_weight": 1.0,
            "max_single_name_weight": 0.2,
            "max_sector_weight": 0.4,
            "restricted_ts_codes": [],
            "evidence_ids": ["constraint-evidence"],
        }
        role_context = {
            "context_kind": "CRO_PROPOSAL_RISK_REVIEW",
            "proposal_accepted_output_id": upstream_refs[0]["accepted_output_id"],
            "proposal_accepted_output_hash": upstream_refs[0]["accepted_output_hash"],
            "position_snapshot_id": "position-snapshot-1",
            "position_snapshot_hash": f"sha256:{'a' * 64}",
            "portfolio_exposure_snapshot_id": "portfolio-exposure-snapshot-1",
            "portfolio_exposure_snapshot_hash": f"sha256:{'b' * 64}",
            "evidence_ids": ["context-evidence"],
        }
    elif tool_id == "get_execution_snapshot":
        upstream_refs.append(
            accepted_ref(
                2,
                agent="cio",
                ref_stage="cio_proposal",
                kind="CIO_PROPOSAL",
            )
        )
        candidates = [
            {
                "candidate_ref": "candidate-1",
                "ts_code": "600000.SH",
                "order_intent_ref": "order-intent-1",
                "current_weight": 0.03,
                "target_weight": 0.04,
                "requested_delta_weight": 0.01,
                "side": "BUY",
                "metrics": {"relative_strength_20d": 0.12},
                "evidence_ids": ["candidate-evidence"],
            }
        ]
        constraints = {
            "execution_mode": "PAPER",
            "max_slippage_bps": 50,
            "max_participation_rate": 0.1,
            "min_trade_weight": 0.001,
            "max_slice_count": 10,
            "prohibited_ts_codes": [],
            "evidence_ids": ["constraint-evidence"],
        }
        role_context = {
            "context_kind": "EXECUTION_ORDER_FEASIBILITY",
            "proposal_accepted_output_id": "accepted-upstream-2",
            "proposal_accepted_output_hash": f"sha256:{'2' * 64}",
            "cro_control_source": {
                "source_status": "ACCEPTED_OUTPUT",
                "agent_id": "cro",
                "accepted_output_kind": "CRO_RISK_REVIEW",
                "accepted_output_id": upstream_refs[0]["accepted_output_id"],
                "accepted_output_hash": upstream_refs[0]["accepted_output_hash"],
                "stage_skip_id": None,
                "stage_skip_hash": None,
            },
            "order_intent_set_id": "order-intent-set-1",
            "order_intent_set_hash": f"sha256:{'a' * 64}",
            "liquidity_vintage_hash": f"sha256:{'b' * 64}",
            "evidence_ids": ["context-evidence"],
        }
    elif stage == "cio_proposal":
        candidates = [
            {
                "candidate_ref": "candidate-1",
                "ts_code": "600000.SH",
                "source_kind": "ALPHA_DISCOVERY",
                "current_weight": 0.0,
                "reference_target_weight": 0.04,
                "source_output_id": upstream_refs[0]["accepted_output_id"],
                "source_output_hash": upstream_refs[0]["accepted_output_hash"],
                "metrics": {"relative_strength_20d": 0.12},
                "evidence_ids": ["candidate-evidence"],
            }
        ]
        constraints = {
            "max_total_target_weight": 1.0,
            "min_cash_weight": 0.0,
            "max_single_name_weight": 0.2,
            "restricted_ts_codes": [],
            "evidence_ids": ["constraint-evidence"],
        }
        role_context = {
            "context_kind": "CIO_PORTFOLIO_DECISION",
            "decision_stage": "PROPOSAL",
            "position_snapshot_id": "position-snapshot-1",
            "position_snapshot_hash": f"sha256:{'a' * 64}",
            "previous_target_id": None,
            "previous_target_hash": None,
            "evidence_ids": ["context-evidence"],
        }
    else:
        upstream_refs.extend(
            [
                accepted_ref(
                    2,
                    agent="cio",
                    ref_stage="cio_proposal",
                    kind="CIO_PROPOSAL",
                ),
                accepted_ref(
                    3,
                    agent="cro",
                    ref_stage="cro",
                    kind="CRO_RISK_REVIEW",
                ),
            ]
        )
        candidates = [
            {
                "candidate_ref": "candidate-1",
                "ts_code": "600000.SH",
                "proposal_position_ref": "proposal-position-1",
                "current_weight": 0.03,
                "proposed_target_weight": 0.04,
                "proposed_delta_weight": 0.01,
                "metrics": {"relative_strength_20d": 0.12},
                "evidence_ids": ["candidate-evidence"],
            }
        ]
        constraints = {
            "max_total_target_weight": 1.0,
            "min_cash_weight": 0.0,
            "max_single_name_weight": 0.2,
            "restricted_ts_codes": [],
            "evidence_ids": ["constraint-evidence"],
        }
        role_context = {
            "context_kind": "CIO_PORTFOLIO_DECISION",
            "decision_stage": "FINAL",
            "proposal_accepted_output_id": "accepted-upstream-2",
            "proposal_accepted_output_hash": f"sha256:{'2' * 64}",
            "cro_control_source": {
                "source_status": "ACCEPTED_OUTPUT",
                "agent_id": "cro",
                "accepted_output_kind": "CRO_RISK_REVIEW",
                "accepted_output_id": "accepted-upstream-3",
                "accepted_output_hash": f"sha256:{'3' * 64}",
                "stage_skip_id": None,
                "stage_skip_hash": None,
            },
            "execution_control_source": {
                "source_status": "ACCEPTED_OUTPUT",
                "agent_id": "autonomous_execution",
                "accepted_output_kind": "EXECUTION_ASSESSMENT",
                "accepted_output_id": upstream_refs[0]["accepted_output_id"],
                "accepted_output_hash": upstream_refs[0]["accepted_output_hash"],
                "stage_skip_id": None,
                "stage_skip_hash": None,
            },
            "evidence_ids": ["context-evidence"],
        }
    candidate_universe_hash = _canonical_hash(
        {"candidate_status": "AVAILABLE", "candidate_universe": candidates}
    )
    constraint_set_hash = _canonical_hash(constraints)
    candidate_scope = {
        "candidate_universe_id": "candidate-universe-1",
        "candidate_universe_hash": candidate_universe_hash,
        "constraint_set_id": "constraint-set-1",
        "constraint_set_hash": constraint_set_hash,
    }
    contract_version = contract_versions[tool_id]
    body = {
        "schema_version": contract_version,
        "contract_version": contract_version,
        "snapshot_id": f"snapshot-{agent_id}-{stage}",
        "graph_run_id": "graph-1",
        "agent_id": agent_id,
        "stage": stage,
        "as_of": "2026-07-09",
        "generated_at": "2026-07-09T07:01:00+00:00",
        "pit_status": "VERIFIED",
        "candidate_scope": candidate_scope,
        "candidate_scope_hash": _canonical_hash(candidate_scope),
        "candidate_universe_id": "candidate-universe-1",
        "candidate_universe_hash": candidate_universe_hash,
        "candidate_status": "AVAILABLE",
        "candidate_universe": candidates,
        "constraint_set_id": "constraint-set-1",
        "constraint_set_hash": constraint_set_hash,
        "constraints": constraints,
        "role_context": role_context,
        "role_context_hash": _canonical_hash(role_context),
        "upstream_accepted_output_refs": upstream_refs,
        "evidence_ledger": [
            {
                "evidence_id": "candidate-evidence",
                "source_kind": "MARKET_SNAPSHOT",
                "source_id": "market-1",
                "metric": "relative_strength_20d",
                "value": 0.12,
                "unit": "ratio",
                "as_of": "2026-07-09",
                "available_at": "2026-07-09T06:59:00+00:00",
                "source_fingerprint": f"sha256:{'2' * 64}",
            },
            {
                "evidence_id": "constraint-evidence",
                "source_kind": "POLICY_CONSTRAINT",
                "source_id": "policy-1",
                "metric": "cash_only",
                "value": True,
                "unit": "boolean",
                "as_of": "2026-07-09",
                "available_at": "2026-07-09T06:58:00+00:00",
                "source_fingerprint": f"sha256:{'3' * 64}",
            },
            {
                "evidence_id": "context-evidence",
                "source_kind": "DERIVED_METRIC",
                "source_id": "runtime-context-1",
                "metric": "role_context_binding",
                "value": True,
                "unit": "boolean",
                "as_of": "2026-07-09",
                "available_at": "2026-07-09T06:56:00+00:00",
                "source_fingerprint": f"sha256:{'4' * 64}",
            },
            *[
                {
                    "evidence_id": ref["evidence_ids"][0],
                    "source_kind": "ACCEPTED_OUTPUT",
                    "source_id": ref["accepted_output_id"],
                    "metric": "accepted_output_ref",
                    "value": "ACCEPTED",
                    "unit": "status",
                    "as_of": "2026-07-09",
                    "available_at": "2026-07-09T06:57:00+00:00",
                    "source_fingerprint": ref["accepted_output_hash"],
                }
                for ref in upstream_refs
            ],
        ],
    }
    return {**body, "snapshot_hash": _canonical_hash(body)}


def _rehash_bound_snapshot(payload: dict) -> dict:
    payload = json.loads(json.dumps(payload))
    payload["candidate_universe_hash"] = _canonical_hash(
        {
            "candidate_status": payload["candidate_status"],
            "candidate_universe": payload["candidate_universe"],
        }
    )
    payload["constraint_set_hash"] = _canonical_hash(payload["constraints"])
    payload["role_context_hash"] = _canonical_hash(payload["role_context"])
    payload["candidate_scope"] = {
        "candidate_universe_id": payload["candidate_universe_id"],
        "candidate_universe_hash": payload["candidate_universe_hash"],
        "constraint_set_id": payload["constraint_set_id"],
        "constraint_set_hash": payload["constraint_set_hash"],
    }
    payload["candidate_scope_hash"] = _canonical_hash(payload["candidate_scope"])
    payload["snapshot_hash"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "snapshot_hash"}
    )
    return payload


def _write_bound_snapshot(
    root: Path,
    *,
    payload: dict,
    tool_id: str,
    agent_id: str,
    stage: str,
) -> None:
    directory = root / "2026-07-09"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{agent_id}.{stage}.{tool_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _bound_request_refs(payload: dict) -> dict[str, dict[str, str]]:
    return {
        f"{ref['accepted_output_kind']}:{ref['agent_id']}:{index}": {
            key: ref[key]
            for key in (
                "accepted_output_kind",
                "agent_id",
                "accepted_output_id",
                "accepted_output_hash",
            )
        }
        for index, ref in enumerate(payload["upstream_accepted_output_refs"])
    }


def _paired_capabilities(
    store: AgentToolCapabilityStore,
) -> tuple[dict, dict, dict]:
    root = store.prepare(
        _request(), materializer=lambda *_args, **_kwargs: "frozen payload"
    )
    candidate = store.issue_for_bundle(
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
    binding = {
        "knot_research_track_id": "knot-track-1",
        "knot_pair_assignment_id": "knot-assignment-1",
        "research_slot_id": "research-slot-1",
        "evaluation_opportunity_set_id": "opportunity-1",
    }
    return root, candidate, binding


def _paired_sector_capabilities(
    store: AgentToolCapabilityStore, *, suffix: str
) -> tuple[dict, dict, dict]:
    root = store.prepare(
        {
            **_request("biotech"),
            "materialization_request_id": f"materialize-biotech-{suffix}",
        },
        materializer=lambda *_args, **_kwargs: "frozen sector payload",
    )
    candidate = store.issue_for_bundle(
        {
            "graph_run_id": "graph-1",
            "run_slot_id": f"slot-biotech-candidate-{suffix}",
            "run_id": f"run-candidate-{suffix}",
            "node_id": f"node-biotech-candidate-{suffix}",
            "agent_id": "biotech",
            "stage": "biotech",
            "as_of": "2026-07-09",
            "snapshot_bundle_id": root["bundle"]["snapshot_bundle_id"],
            "snapshot_bundle_hash": root["bundle"]["snapshot_bundle_hash"],
        }
    )
    binding = {
        "knot_research_track_id": f"knot-track-{suffix}",
        "knot_pair_assignment_id": f"knot-assignment-{suffix}",
        "research_slot_id": f"research-slot-{suffix}",
        "evaluation_opportunity_set_id": f"opportunity-{suffix}",
    }
    return root, candidate, binding


def test_capability_hashing_uses_shared_cross_runtime_jcs_authority():
    value = {"number": 1.0, "\U00010000": "astral", "\ue000": "bmp"}

    assert capability_module._canonical_json(value) == '{"number":1,"𐀀":"astral","":"bmp"}'
    assert capability_module._sha256(value) == canonical_hash(value)


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


@pytest.mark.parametrize(
    (
        "tool_id",
        "agent_id",
        "stage",
        "upstream_agent",
        "upstream_stage",
        "upstream_kind",
    ),
    [
        (
            "get_superinvestor_candidate_snapshot",
            "ackman",
            "ackman",
            "china",
            "china",
            "MACRO_TRANSMISSION",
        ),
        (
            "get_cro_risk_snapshot",
            "cro",
            "cro",
            "cio",
            "cio_proposal",
            "CIO_PROPOSAL",
        ),
        (
            "get_alpha_candidate_snapshot",
            "alpha_discovery",
            "alpha_discovery",
            "ackman",
            "ackman",
            "SUPERINVESTOR_SELECTION",
        ),
        (
            "get_execution_snapshot",
            "autonomous_execution",
            "autonomous_execution",
            "cro",
            "cro",
            "CRO_RISK_REVIEW",
        ),
        (
            "get_cio_decision_snapshot",
            "cio",
            "cio_proposal",
            "alpha_discovery",
            "alpha_discovery",
            "ALPHA_DISCOVERY",
        ),
        (
            "get_cio_decision_snapshot",
            "cio",
            "cio_final",
            "autonomous_execution",
            "autonomous_execution",
            "EXECUTION_ASSESSMENT",
        ),
    ],
)
def test_bound_runtime_snapshots_use_strict_versioned_role_contracts(
    tmp_path,
    monkeypatch,
    tool_id,
    agent_id,
    stage,
    upstream_agent,
    upstream_stage,
    upstream_kind,
):
    payload = _bound_snapshot(
        tool_id=tool_id,
        agent_id=agent_id,
        stage=stage,
        upstream_agent=upstream_agent,
        upstream_stage=upstream_stage,
        upstream_kind=upstream_kind,
    )
    _write_bound_snapshot(
        tmp_path,
        payload=payload,
        tool_id=tool_id,
        agent_id=agent_id,
        stage=stage,
    )
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(tmp_path))

    rendered = materialize_tool_payload(
        tool_id,
        agent_id=agent_id,
        stage=stage,
        as_of="2026-07-09",
        graph_run_id="graph-1",
        expected_candidate_scope_hash=payload["candidate_scope_hash"],
    )

    assert json.loads(rendered) == payload


@pytest.mark.parametrize(
    (
        "tool_id",
        "agent_id",
        "stage",
        "upstream_agent",
        "upstream_stage",
        "upstream_kind",
        "mutation",
    ),
    [
        (
            "get_superinvestor_candidate_snapshot",
            "ackman",
            "ackman",
            "china",
            "china",
            "MACRO_TRANSMISSION",
            lambda row: row["candidate_universe"][0].pop("source_direction"),
        ),
        (
            "get_alpha_candidate_snapshot",
            "alpha_discovery",
            "alpha_discovery",
            "ackman",
            "ackman",
            "SUPERINVESTOR_SELECTION",
            lambda row: row["candidate_universe"][0].pop(
                "omitted_by_superinvestor_agents"
            ),
        ),
        (
            "get_cro_risk_snapshot",
            "cro",
            "cro",
            "cio",
            "cio_proposal",
            "CIO_PROPOSAL",
            lambda row: row["candidate_universe"][0].pop(
                "proposed_target_weight"
            ),
        ),
        (
            "get_execution_snapshot",
            "autonomous_execution",
            "autonomous_execution",
            "cro",
            "cro",
            "CRO_RISK_REVIEW",
            lambda row: row["candidate_universe"][0].update({"side": "ADD"}),
        ),
        (
            "get_cio_decision_snapshot",
            "cio",
            "cio_final",
            "autonomous_execution",
            "autonomous_execution",
            "EXECUTION_ASSESSMENT",
            lambda row: row["role_context"].update(
                {"decision_stage": "PROPOSAL"}
            ),
        ),
    ],
)
def test_bound_runtime_role_schemas_reject_foreign_or_incomplete_role_payloads(
    tmp_path,
    monkeypatch,
    tool_id,
    agent_id,
    stage,
    upstream_agent,
    upstream_stage,
    upstream_kind,
    mutation,
):
    payload = _bound_snapshot(
        tool_id=tool_id,
        agent_id=agent_id,
        stage=stage,
        upstream_agent=upstream_agent,
        upstream_stage=upstream_stage,
        upstream_kind=upstream_kind,
    )
    mutation(payload)
    payload = _rehash_bound_snapshot(payload)
    _write_bound_snapshot(
        tmp_path,
        payload=payload,
        tool_id=tool_id,
        agent_id=agent_id,
        stage=stage,
    )
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(tmp_path))

    with pytest.raises(DataVendorUnavailable, match="strict contract"):
        materialize_tool_payload(
            tool_id,
            agent_id=agent_id,
            stage=stage,
            as_of="2026-07-09",
            graph_run_id="graph-1",
            expected_candidate_scope_hash=payload["candidate_scope_hash"],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row.update({"unexpected": True}), "strict contract"),
        (
            lambda row: row.update(
                {
                    "schema_version": "alpha_candidate_snapshot_v2",
                    "contract_version": "alpha_candidate_snapshot_v2",
                }
            ),
            "strict contract",
        ),
        (
            lambda row: row["candidate_universe"][0]["metrics"].update(
                {"source_text": "LEAKED_TEXT"}
            ),
            "forbidden source prose",
        ),
        (
            lambda row: row["evidence_ledger"].pop(),
            "evidence closure",
        ),
        (
            lambda row: row["upstream_accepted_output_refs"][0].update(
                {
                    "agent_id": "cio",
                    "stage": "cio_final",
                    "accepted_output_kind": "SUPERINVESTOR_SELECTION",
                }
            ),
            "accepted-output lineage",
        ),
        (
            lambda row: row["evidence_ledger"][0].update(
                {"available_at": "2026-07-09T16:00:00+08:00"}
            ),
            "not PIT",
        ),
        (
            lambda row: row["candidate_universe"].append(
                dict(row["candidate_universe"][0])
            ),
            "unique A-share scope",
        ),
    ],
)
def test_bound_runtime_snapshots_reject_untrusted_or_incomplete_payloads(
    tmp_path,
    monkeypatch,
    mutation,
    message,
):
    payload = _bound_snapshot(
        tool_id="get_alpha_candidate_snapshot",
        agent_id="alpha_discovery",
        stage="alpha_discovery",
        upstream_agent="ackman",
        upstream_stage="ackman",
        upstream_kind="SUPERINVESTOR_SELECTION",
    )
    mutation(payload)
    payload = _rehash_bound_snapshot(payload)
    _write_bound_snapshot(
        tmp_path,
        payload=payload,
        tool_id="get_alpha_candidate_snapshot",
        agent_id="alpha_discovery",
        stage="alpha_discovery",
    )
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(tmp_path))

    with pytest.raises(DataVendorUnavailable, match=message):
        materialize_tool_payload(
            "get_alpha_candidate_snapshot",
            agent_id="alpha_discovery",
            stage="alpha_discovery",
            as_of="2026-07-09",
            graph_run_id="graph-1",
            expected_candidate_scope_hash=payload["candidate_scope_hash"],
        )


def test_bound_runtime_control_skip_cannot_mask_an_accepted_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _bound_snapshot(
        tool_id="get_execution_snapshot",
        agent_id="autonomous_execution",
        stage="autonomous_execution",
        upstream_agent="cro",
        upstream_stage="cro",
        upstream_kind="CRO_RISK_REVIEW",
    )
    payload["role_context"]["cro_control_source"] = {
        "source_status": "NO_EVALUATION_OBJECT",
        "agent_id": "cro",
        "accepted_output_kind": "CRO_RISK_REVIEW",
        "accepted_output_id": None,
        "accepted_output_hash": None,
        "stage_skip_id": "stage-skip:cro:forged",
        "stage_skip_hash": f"sha256:{'9' * 64}",
    }
    payload = _rehash_bound_snapshot(payload)
    _write_bound_snapshot(
        tmp_path,
        payload=payload,
        tool_id="get_execution_snapshot",
        agent_id="autonomous_execution",
        stage="autonomous_execution",
    )
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(tmp_path))

    with pytest.raises(DataVendorUnavailable, match="stage skip masks"):
        materialize_tool_payload(
            "get_execution_snapshot",
            agent_id="autonomous_execution",
            stage="autonomous_execution",
            as_of="2026-07-09",
            graph_run_id="graph-1",
            expected_candidate_scope_hash=payload["candidate_scope_hash"],
        )


def test_prepare_binds_bound_tools_to_snapshot_authoritative_candidate_scope(
    tmp_path,
    monkeypatch,
):
    payload = _bound_snapshot(
        tool_id="get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
        upstream_agent="china",
        upstream_stage="china",
        upstream_kind="MACRO_TRANSMISSION",
    )
    snapshot_root = tmp_path / "runtime"
    _write_bound_snapshot(
        snapshot_root,
        payload=payload,
        tool_id="get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
    )
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(snapshot_root))
    store = _store(tmp_path, [datetime(2026, 7, 9, tzinfo=timezone.utc)])
    request = _request("ackman")
    accepted_refs = _bound_request_refs(payload)
    request["runtime_inputs"] = {"accepted_output_refs": accepted_refs}
    request["candidate_scope"] = {"accepted_output_refs": accepted_refs}

    prepared = store.prepare(request)

    assert prepared["bundle"]["candidate_scope_hash"] == payload[
        "candidate_scope_hash"
    ]
    assert prepared["capability"]["manifest"]["candidate_scope_hash"] == payload[
        "candidate_scope_hash"
    ]
    assert json.loads(
        store.call_tool(
            prepared["capability"], "get_superinvestor_candidate_snapshot", {}
        )
    ) == payload


def test_explicit_synthetic_bundle_rebinds_run_and_exact_accepted_lineage(
    tmp_path,
    monkeypatch,
):
    bindings = build_structured_smoke_fixtures(tmp_path, "2026-07-09")
    snapshot_root = tmp_path / "runtime_snapshots"
    payload = json.loads(
        (
            snapshot_root
            / "2026-07-09"
            / "ackman.ackman.get_superinvestor_candidate_snapshot.json"
        ).read_text(encoding="utf-8")
    )
    for key, value in bindings.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(snapshot_root))

    accepted_refs = _bound_request_refs(payload)
    for index, ref in enumerate(accepted_refs.values(), start=1):
        ref["accepted_output_id"] = f"runtime-accepted-{index}"
        ref["accepted_output_hash"] = f"sha256:{index:064x}"
    request = _request("ackman")
    request["graph_run_id"] = "synthetic-dynamic-graph"
    request["runtime_inputs"] = {"accepted_output_refs": accepted_refs}
    request["candidate_scope"] = {"accepted_output_refs": accepted_refs}
    store = _store(tmp_path, [datetime(2026, 7, 9, tzinfo=timezone.utc)])
    prepared = store.prepare(request)
    rebound = json.loads(
        store.call_tool(
            prepared["capability"], "get_superinvestor_candidate_snapshot", {}
        )
    )

    assert rebound["graph_run_id"] == "synthetic-dynamic-graph"
    assert {
        (row["accepted_output_kind"], row["agent_id"]): (
            row["accepted_output_id"],
            row["accepted_output_hash"],
        )
        for row in rebound["upstream_accepted_output_refs"]
    } == {
        (row["accepted_output_kind"], row["agent_id"]): (
            row["accepted_output_id"],
            row["accepted_output_hash"],
        )
        for row in accepted_refs.values()
    }
    assert rebound["snapshot_hash"] == _canonical_hash(
        {key: value for key, value in rebound.items() if key != "snapshot_hash"}
    )


@pytest.mark.parametrize(
    ("artifact", "tool_id", "agent_id"),
    [
        ("macro_snapshots/2026-07-09/china.json", "get_china_macro_snapshot", "china"),
        (
            "sector_snapshots/2026-07-09/energy.json",
            "get_sector_research_snapshot",
            "energy",
        ),
    ],
)
def test_synthetic_bundle_is_revalidated_before_each_rendered_tool_call(
    tmp_path,
    monkeypatch,
    artifact,
    tool_id,
    agent_id,
):
    bindings = build_structured_smoke_fixtures(tmp_path, "2026-07-09")
    for key, value in bindings.items():
        monkeypatch.setenv(key, value)

    assert materialize_tool_payload(
        tool_id,
        agent_id=agent_id,
        stage=agent_id,
        as_of="2026-07-09",
    )
    target = tmp_path / artifact
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(DataVendorUnavailable, match="artifact inventory mismatch"):
        materialize_tool_payload(
            tool_id,
            agent_id=agent_id,
            stage=agent_id,
            as_of="2026-07-09",
        )


@pytest.mark.parametrize("mutation", ["omitted", "added", "hash_swapped", "runtime_mismatch"])
def test_prepare_rejects_nonexact_bound_accepted_output_closure(
    tmp_path,
    monkeypatch,
    mutation,
):
    payload = _bound_snapshot(
        tool_id="get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
        upstream_agent="china",
        upstream_stage="china",
        upstream_kind="MACRO_TRANSMISSION",
    )
    snapshot_root = tmp_path / "runtime"
    _write_bound_snapshot(
        snapshot_root,
        payload=payload,
        tool_id="get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
    )
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(snapshot_root))
    refs = list(_bound_request_refs(payload).values())
    scoped: list[dict] = [dict(ref) for ref in refs]
    runtime: list[dict] = [dict(ref) for ref in refs]
    if mutation == "omitted":
        scoped.clear()
        runtime.clear()
    elif mutation == "added":
        extra = {**refs[0], "accepted_output_id": "accepted-extra-1"}
        scoped.append(extra)
        runtime.append(extra)
    elif mutation == "hash_swapped":
        scoped[0]["accepted_output_hash"] = f"sha256:{'9' * 64}"
        runtime[0]["accepted_output_hash"] = f"sha256:{'9' * 64}"
    else:
        runtime[0]["accepted_output_id"] = "accepted-cross-run-1"
    request = _request("ackman")
    request["runtime_inputs"] = {"accepted_output_refs": runtime}
    request["candidate_scope"] = {"accepted_output_refs": scoped}

    with pytest.raises(DataVendorUnavailable, match="accepted-output closure"):
        _store(tmp_path, [datetime(2026, 7, 9, tzinfo=timezone.utc)]).prepare(
            request
        )


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


def test_prepare_rejects_live_source_drift_before_capability_issuance(
    tmp_path: Path,
) -> None:
    request = _request()
    request["runtime_inputs"] = {
        "outcome_opportunity_authority": {
            "source_tool_id": "get_china_macro_snapshot",
            "source_snapshot_hash": f"sha256:{'4' * 64}",
            "domain_hash": f"sha256:{'5' * 64}",
        }
    }

    with pytest.raises(DataVendorUnavailable, match="changed after opportunity freeze"):
        _store(tmp_path, [datetime(2026, 7, 9, tzinfo=timezone.utc)]).prepare(
            request,
            materializer=lambda *_args, **_kwargs: json.dumps(
                {"snapshot_hash": f"sha256:{'6' * 64}"}
            ),
        )


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


def test_knot_pair_root_is_authoritative_atomic_and_replay_safe(tmp_path):
    now = [datetime(2026, 7, 9, 8, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    champion, candidate, binding = _paired_capabilities(store)

    receipt = store.verify_and_reserve_knot_pair_root(
        pair_binding=binding,
        champion_envelope=champion["capability"],
        candidate_envelope=candidate["capability"],
    )

    assert store.verify_knot_pair_root_receipt(receipt) == receipt
    assert receipt["pair_binding"] == binding
    assert receipt["snapshot_bundle_hash"] == champion["bundle"][
        "snapshot_bundle_hash"
    ]
    assert receipt["capabilities"]["CHAMPION"]["capability_id"] == champion[
        "capability"
    ]["manifest"]["capability_id"]
    assert receipt["capabilities"]["CANDIDATE"]["capability_id"] == candidate[
        "capability"
    ]["manifest"]["capability_id"]
    assert store.verify_and_reserve_knot_pair_root(
        pair_binding=binding,
        champion_envelope=champion["capability"],
        candidate_envelope=candidate["capability"],
    ) == receipt

    with pytest.raises(ValueError, match="already been reserved"):
        store.verify_and_reserve_knot_pair_root(
            pair_binding={**binding, "research_slot_id": "research-slot-2"},
            champion_envelope=champion["capability"],
            candidate_envelope=candidate["capability"],
        )

    store.call_tool(champion["capability"], "get_china_macro_snapshot", {})
    store.call_tool(candidate["capability"], "get_china_macro_snapshot", {})
    store.terminate(champion["capability"], "side_finished")
    store.terminate(candidate["capability"], "side_finished")
    now[0] += timedelta(seconds=61)
    assert store.verify_and_reserve_knot_pair_root(
        pair_binding=binding,
        champion_envelope=champion["capability"],
        candidate_envelope=candidate["capability"],
    ) == receipt
    now[0] -= timedelta(seconds=61)

    tampered = {**receipt, "agent_id": "us_economy"}
    with pytest.raises(ValueError, match="hash mismatch"):
        store.verify_knot_pair_root_receipt(tampered)


def test_knot_pair_root_rejects_bad_signature_wrong_lineage_and_expiry(tmp_path):
    now = [datetime(2026, 7, 9, 8, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    champion, candidate, binding = _paired_capabilities(store)
    bad_signature = {**candidate["capability"], "signature": "hmac-sha256:bad"}
    with pytest.raises(ValueError, match="signature"):
        store.verify_and_reserve_knot_pair_root(
            pair_binding=binding,
            champion_envelope=champion["capability"],
            candidate_envelope=bad_signature,
        )

    us = store.prepare(
        _request("us_economy"),
        materializer=lambda *_args, **_kwargs: "us payload",
    )
    with pytest.raises(ValueError, match="different agent_id"):
        store.verify_and_reserve_knot_pair_root(
            pair_binding=binding,
            champion_envelope=champion["capability"],
            candidate_envelope=us["capability"],
        )

    now[0] += timedelta(seconds=61)
    with pytest.raises(ValueError, match="expired"):
        store.verify_and_reserve_knot_pair_root(
            pair_binding=binding,
            champion_envelope=champion["capability"],
            candidate_envelope=candidate["capability"],
        )


def test_knot_strict_output_receipt_requires_schema_claims_tools_and_timeline(
    tmp_path,
):
    now = [datetime(2026, 7, 9, 8, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    champion, candidate, binding = _paired_capabilities(store)
    root_receipt = store.verify_and_reserve_knot_pair_root(
        pair_binding=binding,
        champion_envelope=champion["capability"],
        candidate_envelope=candidate["capability"],
    )
    store.bind_knot_private_pair(
        pair_root_reservation_id=root_receipt["pair_root_reservation_id"],
        knot_pair_id="knot-pair-1",
        knot_pair_input_hash=f"sha256:{'a' * 64}",
        sector_inference_budget_contract=None,
    )
    store.call_tool(
        champion["capability"], "get_china_macro_snapshot", {}
    )
    store.terminate(champion["capability"], "side_finished")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["agent_id", "claims", "claim_refs"],
        "properties": {
            "agent_id": {"const": "china"},
            "claims": {"type": "array", "minItems": 1},
            "claim_refs": {"type": "array", "minItems": 1},
        },
    }
    output = {
        "agent_id": "china",
        "claims": [
            {
                "claim_id": "claim-1",
                "claim_kind": "FACT",
                "evidence_ids": ["evidence-1"],
            }
        ],
        "claim_refs": ["claim-1"],
    }
    graph = {
        "schema_version": "evidence_claim_graph_v1",
        "run_id": "graph-1",
        "snapshot_hash": root_receipt["snapshot_bundle_hash"],
        "evidence_ledger": [
            {
                "evidence_id": "evidence-1",
                "run_id": "graph-1",
                "snapshot_hash": root_receipt["snapshot_bundle_hash"],
                "source_kind": "tool",
                "tool_or_source": "get_china_macro_snapshot",
                "source_fingerprint": f"sha256:{'b' * 64}",
                "freshness": "current",
            }
        ],
        "claims": output["claims"],
        "recommendation_claim_refs": [],
    }
    schema_binding = {
        "accepted_output_kind": "MACRO_TRANSMISSION",
        "schema_phase": "DEFAULT",
        "schema_id": "macro.china.output.test",
        "schema_hash": _canonical_hash(schema),
        "immutable_phase_instruction_hash": f"sha256:{'c' * 64}",
        "structured_output_schema_binding_set_hash": f"sha256:{'d' * 64}",
    }

    receipt = store.mint_knot_strict_output_validation_receipt(
        knot_pair_id="knot-pair-1",
        pair_side="CHAMPION",
        accepted_output_kind="MACRO_TRANSMISSION",
        accepted_output_record=output,
        verified_claim_graph=graph,
        schema_binding=schema_binding,
        schema_json=schema,
    )

    assert store.verify_knot_strict_output_validation_receipt(receipt) == receipt
    assert receipt["accepted_output_record_hash"] == _canonical_hash(output)
    assert receipt["verified_claim_graph_hash"] == _canonical_hash(graph)
    assert store.mint_knot_strict_output_validation_receipt(
        knot_pair_id="knot-pair-1",
        pair_side="CHAMPION",
        accepted_output_kind="MACRO_TRANSMISSION",
        accepted_output_record=output,
        verified_claim_graph=graph,
        schema_binding=schema_binding,
        schema_json=schema,
    ) == receipt
    changed_output = {
        **output,
        "claims": [
            {
                "claim_id": "claim-2",
                "claim_kind": "FACT",
                "evidence_ids": ["evidence-1"],
            }
        ],
        "claim_refs": ["claim-2"],
    }
    changed_graph = {**graph, "claims": changed_output["claims"]}
    with pytest.raises(ValueError, match="changed immutable inputs"):
        store.mint_knot_strict_output_validation_receipt(
            knot_pair_id="knot-pair-1",
            pair_side="CHAMPION",
            accepted_output_kind="MACRO_TRANSMISSION",
            accepted_output_record=changed_output,
            verified_claim_graph=changed_graph,
            schema_binding=schema_binding,
            schema_json=schema,
        )


def test_knot_pair_budget_binding_is_required_only_for_standard_sector(tmp_path):
    now = [datetime(2026, 7, 9, 8, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    sector_champion, sector_candidate, sector_binding = _paired_sector_capabilities(
        store, suffix="budget-scope"
    )
    sector_root = store.verify_and_reserve_knot_pair_root(
        pair_binding=sector_binding,
        champion_envelope=sector_champion["capability"],
        candidate_envelope=sector_candidate["capability"],
    )
    with pytest.raises(ValueError, match="requires an inference budget"):
        store.bind_knot_private_pair(
            pair_root_reservation_id=sector_root["pair_root_reservation_id"],
            knot_pair_id="sector-without-budget",
            knot_pair_input_hash=_canonical_hash({"pair": "sector-without-budget"}),
            sector_inference_budget_contract=None,
        )
    shared_budget = _sector_budget()
    store.bind_knot_private_pair(
        pair_root_reservation_id=sector_root["pair_root_reservation_id"],
        knot_pair_id="sector-with-budget-1",
        knot_pair_input_hash=_canonical_hash({"pair": "sector-with-budget-1"}),
        sector_inference_budget_contract=shared_budget,
    )
    second_champion, second_candidate, second_binding = _paired_sector_capabilities(
        store, suffix="budget-scope-second"
    )
    second_root = store.verify_and_reserve_knot_pair_root(
        pair_binding=second_binding,
        champion_envelope=second_champion["capability"],
        candidate_envelope=second_candidate["capability"],
    )
    store.bind_knot_private_pair(
        pair_root_reservation_id=second_root["pair_root_reservation_id"],
        knot_pair_id="sector-with-budget-2",
        knot_pair_input_hash=_canonical_hash({"pair": "sector-with-budget-2"}),
        sector_inference_budget_contract=shared_budget,
    )

    macro_champion, macro_candidate, macro_binding = _paired_capabilities(store)
    macro_root = store.verify_and_reserve_knot_pair_root(
        pair_binding=macro_binding,
        champion_envelope=macro_champion["capability"],
        candidate_envelope=macro_candidate["capability"],
    )
    with pytest.raises(ValueError, match="restricted to standard Sector"):
        store.bind_knot_private_pair(
            pair_root_reservation_id=macro_root["pair_root_reservation_id"],
            knot_pair_id="macro-with-sector-budget",
            knot_pair_input_hash=_canonical_hash({"pair": "macro-with-sector-budget"}),
            sector_inference_budget_contract=_sector_budget(),
        )


def test_knot_sector_usage_receipt_is_derived_from_server_owned_subcalls(tmp_path):
    now = [datetime(2026, 7, 9, 8, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    request = _request("biotech")
    champion = store.prepare(
        request, materializer=lambda *_args, **_kwargs: "frozen sector payload"
    )
    candidate = store.issue_for_bundle(
        {
            "graph_run_id": "graph-1",
            "run_slot_id": "slot-biotech-candidate",
            "run_id": "run-candidate",
            "node_id": "node-biotech-candidate",
            "agent_id": "biotech",
            "stage": "biotech",
            "as_of": "2026-07-09",
            "snapshot_bundle_id": champion["bundle"]["snapshot_bundle_id"],
            "snapshot_bundle_hash": champion["bundle"]["snapshot_bundle_hash"],
        }
    )
    root_receipt = store.verify_and_reserve_knot_pair_root(
        pair_binding={
            "knot_research_track_id": "knot-track-sector-1",
            "knot_pair_assignment_id": "knot-assignment-sector-1",
            "research_slot_id": "research-slot-sector-1",
            "evaluation_opportunity_set_id": "opportunity-sector-1",
        },
        champion_envelope=champion["capability"],
        candidate_envelope=candidate["capability"],
    )
    store.bind_knot_private_pair(
        pair_root_reservation_id=root_receipt["pair_root_reservation_id"],
        knot_pair_id="knot-pair-sector-1",
        knot_pair_input_hash=f"sha256:{'a' * 64}",
        sector_inference_budget_contract=_sector_budget(),
    )
    store.call_tool(champion["capability"], "get_sector_research_snapshot", {})
    common = {
        "attempt_index": 1,
        "attempt_status": "ACCEPTED",
        "provider_usage_evidence_hash": f"sha256:{'b' * 64}",
        "conflict_review_id": None,
        "conflict_review_hash": None,
    }
    direction_hash = f"sha256:{'c' * 64}"
    store.record_knot_sector_model_usage(
        capability_envelope=champion["capability"],
        usage_report={
            **common,
            "model_subcall_id": "sector-subcall-direction-1",
            "attempted_stage": "DIRECTION_RESEARCH",
            "input_tokens": 40,
            "output_tokens": 10,
            "provider_usage_evidence_id": "provider-usage-direction-1",
            "direction_comparison_audit_id": None,
            "direction_comparison_audit_hash": None,
        },
    )
    store.record_knot_sector_model_usage(
        capability_envelope=champion["capability"],
        usage_report={
            **common,
            "model_subcall_id": "sector-subcall-final-1",
            "attempted_stage": "FINAL_SELECTION",
            "input_tokens": 60,
            "output_tokens": 20,
            "provider_usage_evidence_id": "provider-usage-final-1",
            "direction_comparison_audit_id": "direction-comparison-1",
            "direction_comparison_audit_hash": direction_hash,
        },
    )
    usage_summary = store.finalize_sector_model_usage(
        capability_envelope=champion["capability"]
    )
    store.terminate(champion["capability"], "side_finished")
    capability = root_receipt["capabilities"]["CHAMPION"]
    runtime_audit_body = {
        "schema_version": "sector_runtime_inference_cost_audit_v3",
        "evidence_source": "SIGNED_SERVER_MODEL_USAGE_SUMMARY",
        "sector_agent_id": "biotech",
        "snapshot_bundle_hash": root_receipt["snapshot_bundle_hash"],
        "usage_summary_receipt_id": usage_summary["usage_summary_receipt_id"],
        "usage_summary_receipt_hash": usage_summary["usage_summary_receipt_hash"],
        "usage_summary_receipt": usage_summary,
        "model_subcall_count": 2,
        "last_attempted_stage": "COMPLETED",
        "conflict_review_triggered": False,
        "input_tokens": 100,
        "output_tokens": 30,
        "disposition": "SUCCESS",
    }
    runtime_audit_hash = _canonical_hash(runtime_audit_body)
    budget = _sector_budget()
    binding_body = {
        "schema_version": "knot_sector_usage_binding_v2",
        "knot_pair_id": "knot-pair-sector-1",
        "knot_pair_input_hash": f"sha256:{'a' * 64}",
        "pair_side": "CHAMPION",
        "production_variant_roster_id": "roster-1",
        "production_variant_roster_revision_id": "roster-revision-1",
        "execution_behavior_release_id": "release-1",
        "cohort_id": "cohort_default",
        "language": "zh",
        "pair_root_reservation_id": root_receipt["pair_root_reservation_id"],
        "pair_root_receipt_hash": root_receipt["pair_root_receipt_hash"],
        "capability_id": capability["capability_id"],
        "capability_manifest_hash": capability["capability_manifest_hash"],
        "graph_run_id": capability["graph_run_id"],
        "run_slot_id": capability["run_slot_id"],
        "run_id": capability["run_id"],
        "node_id": capability["node_id"],
        "agent_id": capability["agent_id"],
        "stage": capability["stage"],
        "as_of": capability["as_of"],
        "snapshot_bundle_hash": root_receipt["snapshot_bundle_hash"],
        "operational_opportunity_audit_id": "operational-sector-1",
        "operational_opportunity_audit_hash": f"sha256:{'e' * 64}",
        "accepted_output_id": "accepted-sector-1",
        "accepted_output_hash": f"sha256:{'f' * 64}",
        "accepted_direction_comparison_audit_id": "direction-comparison-1",
        "accepted_direction_comparison_audit_hash": direction_hash,
        "accepted_runtime_inference_cost_audit_id": (
            "sector-inference-cost:" + runtime_audit_hash.removeprefix("sha256:")
        ),
        "accepted_runtime_inference_cost_audit_hash": runtime_audit_hash,
        "budget_contract_id": budget["budget_contract_id"],
        "budget_contract_version": budget["budget_contract_version"],
        "budget_contract_hash": budget["budget_contract_hash"],
        "expected_result_disposition": "ACCEPTED",
    }
    binding = {
        **binding_body,
        "sector_usage_binding_hash": _canonical_hash(binding_body),
    }

    receipt = store.mint_knot_sector_inference_usage_receipt(binding=binding)

    assert receipt["model_subcall_count"] == 2
    assert receipt["input_tokens"] == 100
    assert receipt["output_tokens"] == 30
    assert receipt["budget_contract_id"] == budget["budget_contract_id"]
    assert receipt["budget_decision"] == {
        "disposition": "WITHIN_BUDGET",
        "violation_codes": [],
    }
    assert receipt["runtime_inference_cost_audit_hash"] == runtime_audit_hash
    assert usage_summary["budget_contract_ref"] == {
        "budget_contract_id": budget["budget_contract_id"],
        "budget_contract_version": budget["budget_contract_version"],
        "budget_contract_hash": budget["budget_contract_hash"],
    }
    assert "budget_compliant" not in receipt
    assert "normalized_inference_cost" not in receipt
    assert store.verify_knot_sector_inference_usage_receipt(receipt) == receipt
    tampered = {**receipt, "input_tokens": 101}
    with pytest.raises(ValueError, match="hash mismatch"):
        store.verify_knot_sector_inference_usage_receipt(tampered)


def test_standard_sector_usage_summary_counts_repairs_and_finalizes_before_termination(
    tmp_path,
):
    now = [datetime(2026, 7, 9, 8, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    prepared = store.prepare(
        _request("biotech"),
        materializer=lambda *_args, **_kwargs: "frozen sector payload",
    )
    capability = prepared["capability"]
    store.call_tool(capability, "get_sector_research_snapshot", {})
    base = {
        "input_tokens": 10,
        "output_tokens": 5,
        "provider_usage_evidence_hash": f"sha256:{'a' * 64}",
        "direction_comparison_audit_id": None,
        "direction_comparison_audit_hash": None,
        "conflict_review_id": None,
        "conflict_review_hash": None,
    }
    for attempt_index, status in ((1, "REJECTED"), (2, "ACCEPTED")):
        store.record_sector_model_usage(
            capability_envelope=capability,
            usage_report={
                **base,
                "model_subcall_id": f"standard-direction-{attempt_index}",
                "attempted_stage": "DIRECTION_RESEARCH",
                "attempt_index": attempt_index,
                "attempt_status": status,
                "provider_usage_evidence_id": f"provider-direction-{attempt_index}",
            },
        )
    direction_hash = f"sha256:{'b' * 64}"
    store.record_sector_model_usage(
        capability_envelope=capability,
        usage_report={
            **base,
            "model_subcall_id": "standard-final-1",
            "attempted_stage": "FINAL_SELECTION",
            "attempt_index": 1,
            "attempt_status": "ACCEPTED",
            "provider_usage_evidence_id": "provider-final-1",
            "direction_comparison_audit_id": "direction-comparison-1",
            "direction_comparison_audit_hash": direction_hash,
        },
    )

    summary = store.finalize_sector_model_usage(capability_envelope=capability)

    assert summary["schema_version"] == "sector_model_usage_summary_receipt_v1"
    assert summary["model_subcall_count"] == 3
    assert summary["input_tokens"] == 30
    assert summary["output_tokens"] == 15
    assert summary["model_path_disposition"] == "COMPLETED"
    assert summary["direction_comparison_audit_hash"] == direction_hash
    assert summary["pair_root_reservation_id"] is None
    assert summary["budget_contract_ref"] is None
    assert "accepted_output_id" not in summary
    assert "normalized_inference_cost" not in summary
    assert "budget_compliant" not in summary
    assert store.finalize_sector_model_usage(capability_envelope=capability) == summary
    store.terminate(capability, "summary_finalized")
    assert store.verify_sector_model_usage_summary(summary) == summary


def test_standard_sector_usage_summary_preserves_failed_attempt_path(tmp_path):
    now = [datetime(2026, 7, 9, 8, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    prepared = store.prepare(
        _request("biotech"),
        materializer=lambda *_args, **_kwargs: "frozen sector payload",
    )
    capability = prepared["capability"]
    store.call_tool(capability, "get_sector_research_snapshot", {})
    store.record_sector_model_usage(
        capability_envelope=capability,
        usage_report={
            "model_subcall_id": "failed-direction-1",
            "attempted_stage": "DIRECTION_RESEARCH",
            "attempt_index": 1,
            "attempt_status": "OPERATIONAL_FAILURE",
            "input_tokens": 0,
            "output_tokens": 0,
            "provider_usage_evidence_id": "provider-failed-direction-1",
            "provider_usage_evidence_hash": f"sha256:{'c' * 64}",
            "direction_comparison_audit_id": None,
            "direction_comparison_audit_hash": None,
            "conflict_review_id": None,
            "conflict_review_hash": None,
        },
    )

    summary = store.finalize_sector_model_usage(capability_envelope=capability)

    assert summary["model_subcall_count"] == 1
    assert summary["last_attempted_stage"] == "DIRECTION_RESEARCH"
    assert summary["model_path_disposition"] == "INCOMPLETE"
    assert summary["direction_comparison_audit_id"] is None
    store.terminate(capability, "failed_path_finalized")
    assert store.verify_sector_model_usage_summary(summary) == summary


@pytest.mark.parametrize(
    ("suffix", "budget_overrides", "reports", "violation_code"),
    [
        (
            "stage-attempt-sum",
            {"direction_research_output_token_cap": 5},
            [
                ("DIRECTION_RESEARCH", 1, "REJECTED", 1, 3),
                ("DIRECTION_RESEARCH", 2, "ACCEPTED", 1, 3),
                ("FINAL_SELECTION", 1, "ACCEPTED", 1, 1),
            ],
            "DIRECTION_RESEARCH_OUTPUT_TOKENS_EXCEEDED",
        ),
        (
            "aggregate-input",
            {"total_stage_input_token_cap": 10},
            [
                ("DIRECTION_RESEARCH", 1, "ACCEPTED", 6, 1),
                ("FINAL_SELECTION", 1, "ACCEPTED", 5, 1),
            ],
            "TOTAL_STAGE_INPUT_TOKENS_EXCEEDED",
        ),
        (
            "conflict-reserve",
            {"conflict_review_output_token_reserve": 2},
            [
                ("DIRECTION_RESEARCH", 1, "ACCEPTED", 1, 1),
                ("CONFLICT_REVIEW", 1, "ACCEPTED", 1, 3),
                ("FINAL_SELECTION", 1, "ACCEPTED", 1, 1),
            ],
            "CONFLICT_REVIEW_OUTPUT_TOKENS_EXCEEDED",
        ),
        (
            "final-cap",
            {"final_selection_output_token_cap": 2},
            [
                ("DIRECTION_RESEARCH", 1, "ACCEPTED", 1, 1),
                ("FINAL_SELECTION", 1, "ACCEPTED", 1, 3),
            ],
            "FINAL_SELECTION_OUTPUT_TOKENS_EXCEEDED",
        ),
        (
            "aggregate-output",
            {
                "direction_research_output_token_cap": 10,
                "final_selection_output_token_cap": 10,
                "total_stage_output_token_cap": 6,
            },
            [
                ("DIRECTION_RESEARCH", 1, "ACCEPTED", 1, 4),
                ("FINAL_SELECTION", 1, "ACCEPTED", 1, 3),
            ],
            "TOTAL_STAGE_OUTPUT_TOKENS_EXCEEDED",
        ),
        (
            "subcall-count",
            {"maximum_model_subcalls": 2},
            [
                ("DIRECTION_RESEARCH", 1, "ACCEPTED", 1, 1),
                ("CONFLICT_REVIEW", 1, "ACCEPTED", 1, 1),
                ("FINAL_SELECTION", 1, "ACCEPTED", 1, 1),
            ],
            "MODEL_SUBCALL_COUNT_EXCEEDED",
        ),
    ],
)
def test_knot_sector_budget_breaches_persist_incomplete_signed_summary(
    tmp_path,
    suffix,
    budget_overrides,
    reports,
    violation_code,
):
    now = [datetime(2026, 7, 9, 8, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    champion, candidate, pair_binding = _paired_sector_capabilities(
        store, suffix=suffix
    )
    root_receipt = store.verify_and_reserve_knot_pair_root(
        pair_binding=pair_binding,
        champion_envelope=champion["capability"],
        candidate_envelope=candidate["capability"],
    )
    budget = _sector_budget(**budget_overrides)
    pair_input_hash = _canonical_hash({"pair": suffix})
    store.bind_knot_private_pair(
        pair_root_reservation_id=root_receipt["pair_root_reservation_id"],
        knot_pair_id=f"knot-pair-{suffix}",
        knot_pair_input_hash=pair_input_hash,
        sector_inference_budget_contract=budget,
    )
    store.call_tool(champion["capability"], "get_sector_research_snapshot", {})
    has_conflict = any(stage == "CONFLICT_REVIEW" for stage, *_ in reports)
    for sequence, (stage, attempt, status, input_tokens, output_tokens) in enumerate(
        reports, start=1
    ):
        final = stage == "FINAL_SELECTION"
        store.record_sector_model_usage(
            capability_envelope=champion["capability"],
            usage_report={
                "model_subcall_id": f"{suffix}-subcall-{sequence}",
                "attempted_stage": stage,
                "attempt_index": attempt,
                "attempt_status": status,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "provider_usage_evidence_id": f"{suffix}-evidence-{sequence}",
                "provider_usage_evidence_hash": _canonical_hash(
                    {"suffix": suffix, "sequence": sequence}
                ),
                "direction_comparison_audit_id": (
                    f"{suffix}-direction-audit" if final else None
                ),
                "direction_comparison_audit_hash": (
                    _canonical_hash({"direction": suffix}) if final else None
                ),
                "conflict_review_id": (
                    f"{suffix}-conflict-review" if final and has_conflict else None
                ),
                "conflict_review_hash": (
                    _canonical_hash({"conflict": suffix})
                    if final and has_conflict
                    else None
                ),
            },
        )

    summary = store.finalize_sector_model_usage(
        capability_envelope=champion["capability"]
    )

    assert summary["budget_contract_ref"] == {
        "budget_contract_id": budget["budget_contract_id"],
        "budget_contract_version": budget["budget_contract_version"],
        "budget_contract_hash": budget["budget_contract_hash"],
    }
    assert summary["model_path_disposition"] == "INCOMPLETE"
    assert summary["last_attempted_stage"] == reports[-1][0]
    assert store.verify_sector_model_usage_summary(summary) == summary
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT usage_ledger_record_json FROM sector_model_usage_summaries "
            "WHERE capability_id = ?",
            (champion["capability"]["manifest"]["capability_id"],),
        ).fetchone()
    assert row is not None
    decision = json.loads(row[0])["budget_decision"]
    assert decision["disposition"] == "STAGE_REJECT"
    assert violation_code in decision["violation_codes"]

    store.terminate(champion["capability"], "budget-stage-rejected")
    capability = root_receipt["capabilities"]["CHAMPION"]
    failure_binding_body = {
        "schema_version": "knot_sector_usage_binding_v2",
        "knot_pair_id": f"knot-pair-{suffix}",
        "knot_pair_input_hash": pair_input_hash,
        "pair_side": "CHAMPION",
        "production_variant_roster_id": "fixture-roster",
        "production_variant_roster_revision_id": "fixture-roster-revision",
        "execution_behavior_release_id": "fixture-execution-release",
        "cohort_id": "cohort_default",
        "language": "zh",
        "pair_root_reservation_id": root_receipt["pair_root_reservation_id"],
        "pair_root_receipt_hash": root_receipt["pair_root_receipt_hash"],
        "capability_id": capability["capability_id"],
        "capability_manifest_hash": capability["capability_manifest_hash"],
        "graph_run_id": capability["graph_run_id"],
        "run_slot_id": capability["run_slot_id"],
        "run_id": capability["run_id"],
        "node_id": capability["node_id"],
        "agent_id": capability["agent_id"],
        "stage": capability["stage"],
        "as_of": capability["as_of"],
        "snapshot_bundle_hash": root_receipt["snapshot_bundle_hash"],
        "operational_opportunity_audit_id": f"operational-{suffix}",
        "operational_opportunity_audit_hash": _canonical_hash(
            {"operational": suffix}
        ),
        "accepted_output_id": None,
        "accepted_output_hash": None,
        "accepted_direction_comparison_audit_id": None,
        "accepted_direction_comparison_audit_hash": None,
        "accepted_runtime_inference_cost_audit_id": None,
        "accepted_runtime_inference_cost_audit_hash": None,
        "budget_contract_id": budget["budget_contract_id"],
        "budget_contract_version": budget["budget_contract_version"],
        "budget_contract_hash": budget["budget_contract_hash"],
        "expected_result_disposition": "AGENT_FAILURE",
    }
    failure_binding = {
        **failure_binding_body,
        "sector_usage_binding_hash": _canonical_hash(failure_binding_body),
    }
    usage_receipt = store.mint_knot_sector_inference_usage_receipt(
        binding=failure_binding
    )
    assert usage_receipt["accepted_output_id"] is None
    assert usage_receipt["budget_decision"]["disposition"] == "STAGE_REJECT"
    assert violation_code in usage_receipt["budget_decision"]["violation_codes"]
    assert usage_receipt["last_attempted_stage"] == summary["last_attempted_stage"]
    assert store.verify_knot_sector_inference_usage_receipt(usage_receipt) == (
        usage_receipt
    )

    changed_binding_body = {
        **failure_binding_body,
        "operational_opportunity_audit_id": f"changed-operational-{suffix}",
    }
    with pytest.raises(ValueError, match="changed immutable binding"):
        store.mint_knot_sector_inference_usage_receipt(
            binding={
                **changed_binding_body,
                "sector_usage_binding_hash": _canonical_hash(changed_binding_body),
            }
        )


def test_knot_regime_receipt_is_deterministic_signed_and_source_bound(
    tmp_path, monkeypatch
):
    now = [datetime(2026, 7, 9, 8, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    body = {
        "schema_version": "component_calibration_regime_snapshot_v1",
        "regime_contract_version": "a_share_realized_volatility_regime_v1",
        "generated_at": "2026-07-09T07:30:00+00:00",
        "pit_status": "VERIFIED",
        "source_evidence_ids": ["market-volatility-1"],
        "observations": [
            {
                "as_of": "2026-07-09",
                "available_at": "2026-07-09T14:50:00+08:00",
                "private_feature_payload": {"fixture": 1},
                "pit_status": "VERIFIED",
                "source_evidence_ids": ["market-volatility-1"],
            }
        ],
    }
    snapshot = {**body, "snapshot_hash": _canonical_hash(body)}
    monkeypatch.setattr(
        capability_module,
        "_classify_private_knot_regime",
        lambda value, *, as_of: {
            "regime_label": "stress",
            "classifier_contract_id": "opaque-private-classifier",
            "classifier_contract_version": "opaque-private-classifier-v1",
            "classifier_contract_hash": f"sha256:{'7' * 64}",
            "pit_snapshot_hash": value["snapshot_hash"],
        },
    )

    receipt = store.classify_and_reserve_knot_regime(
        knot_research_track_id="track-1",
        research_slot_id="slot-1",
        scheduled_sample_id="sample-1",
        expected_as_of="2026-07-09",
        source_snapshot=snapshot,
    )

    assert receipt["evaluation_regime"] == "stress"
    assert store.verify_knot_regime_classification_receipt(receipt) == receipt
    tampered = {**receipt, "evaluation_regime": "normal"}
    with pytest.raises(ValueError, match="hash mismatch"):
        store.verify_knot_regime_classification_receipt(tampered)

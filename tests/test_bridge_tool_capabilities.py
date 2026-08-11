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
from mosaic.dataflows.bound_runtime_production import ActiveAdaptiveQueryPreparer
from mosaic.dataflows.frozen_adaptive_queries import (
    CALL_TIME_ARGUMENT_CONTRACT,
    FrozenAdaptiveQueryStore,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.sector_relationship_preservation import (
    build_sector_relationship_preservation_overlay,
)
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


def test_source_admission_preparation_reuses_exact_families_without_signing_capability(
    tmp_path: Path,
) -> None:
    family_calls: list[tuple[str, str, str]] = []
    family_requests: list[dict] = []
    adaptive_calls: list[tuple[str, str, tuple[str, ...]]] = []

    def stage_preparer(request: dict) -> dict:
        family_requests.append(dict(request))
        family_calls.append(
            (request["agent_id"], request["stage"], request["as_of"])
        )
        return {"cache_status": "MISS", "ensure_mode": "enforce"}

    def adaptive_preparer(**kwargs: object) -> dict:
        agent_id = str(kwargs["agent_id"])
        stage = str(kwargs["stage"])
        allowed_tools = tuple(kwargs["allowed_tools"])
        adaptive_calls.append((agent_id, stage, allowed_tools))
        bundle_id = f"source-only-{agent_id}-{stage}"
        projection_body = {
            "bundle_id": bundle_id,
            "bundle_hash": canonical_hash({"bundle_id": bundle_id}),
            "agent_id": agent_id,
            "stage": stage,
            "as_of": kwargs["as_of"],
            "entries": [],
            "private_payload_count": 0,
            "initial_payload_count": 0,
            "adaptive_max_rounds": 0,
        }
        return {
            "bundle_id": bundle_id,
            "public_projection": {
                **projection_body,
                "projection_hash": canonical_hash(projection_body),
            },
        }

    materializer_calls: list[tuple[str, str, str]] = []

    def materializer(tool_id: str, **kwargs: object) -> str:
        materializer_calls.append(
            (tool_id, str(kwargs["agent_id"]), str(kwargs["stage"]))
        )
        return "{}"

    store = AgentToolCapabilityStore(
        tmp_path / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        adaptive_query_store=FrozenAdaptiveQueryStore(tmp_path / "adaptive.sqlite3"),
        adaptive_query_preparer=adaptive_preparer,
        stage_materialization_preparer=stage_preparer,
    )

    result = store.prepare_source_admission(
        as_of="2026-07-09",
        materializer=materializer,
    )

    assert family_calls == [
        ("china", "china", "2026-07-09"),
        ("us_economy", "us_economy", "2026-07-09"),
        ("eu_economy", "eu_economy", "2026-07-09"),
        ("geopolitical", "geopolitical", "2026-07-09"),
        ("market_breadth", "market_breadth", "2026-07-09"),
        ("semiconductor", "semiconductor", "2026-07-09"),
    ]
    assert [(agent_id, stage) for agent_id, stage, _ in adaptive_calls] == [
        ("agriculture", "agriculture"),
        ("biotech", "biotech"),
        ("consumer", "consumer"),
        ("energy", "energy"),
        ("financials", "financials"),
        ("industrials", "industrials"),
        ("real_estate_construction", "real_estate_construction"),
        ("semiconductor", "semiconductor"),
        ("technology", "technology"),
    ]
    assert materializer_calls
    assert result == {
        "as_of": "2026-07-09",
        "adaptive_stage_count": 9,
        "family_stage_count": 6,
        "status": "SOURCE_PREPARED",
    }
    with store._connect() as conn:
        assert conn.execute("SELECT count(*) FROM materialization_requests").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM snapshot_bundles").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM capabilities").fetchone()[0] == 0

    materializer_count = len(materializer_calls)
    route_result = store.prepare_source_admission(
        as_of="2026-07-09",
        route_id="tushare.sector_market",
        materializer=materializer,
    )

    assert family_calls == [("semiconductor", "semiconductor", "2026-07-09")]
    assert adaptive_calls == []
    assert len(materializer_calls) == materializer_count
    assert route_result == {
        "as_of": "2026-07-09",
        "adaptive_stage_count": 0,
        "family_stage_count": 1,
        "route_id": "tushare.sector_market",
        "status": "SOURCE_PREPARED",
    }
    assert family_requests[-1] == {
        "agent_id": "semiconductor",
        "stage": "semiconductor",
        "as_of": "2026-07-09",
        "route_id": "tushare.sector_market",
    }

def test_source_admission_preserves_exact_owner_blockers_for_operator(
    tmp_path: Path,
) -> None:
    def stage_preparer(_request: dict) -> dict:
        error = DataVendorUnavailable(
            "sector relationship archive is blocked at /private/operator/root"
        )
        error.reason_code = "SECTOR_RELATIONSHIP_ARCHIVE_BLOCKED"
        raise error

    def materializer(_tool_id: str, **_kwargs: object) -> str:
        error = DataVendorUnavailable(
            "no private PIT sector snapshot under /private/operator/root"
        )
        error.reason_code = "PRIVATE_PIT_SECTOR_SNAPSHOT_MISSING"
        raise error

    store = AgentToolCapabilityStore(
        tmp_path / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        adaptive_query_store=FrozenAdaptiveQueryStore(tmp_path / "adaptive.sqlite3"),
        adaptive_query_preparer=lambda **_kwargs: {},
        stage_materialization_preparer=stage_preparer,
    )

    result = store.prepare_source_admission(
        as_of="2026-07-09",
        route_id="tushare.sector_market",
        materializer=materializer,
    )

    assert result["adaptive_stage_count"] == 0
    assert result["blocked_stage_ids"] == ["semiconductor/semiconductor"]
    assert result["blocked_stage_reasons"] == {
        "semiconductor/semiconductor": [
            "SECTOR_RELATIONSHIP_ARCHIVE_BLOCKED",
        ]
    }




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






def test_capability_hashing_uses_shared_cross_runtime_jcs_authority():
    value = {"number": 1.0, "\U00010000": "astral", "\ue000": "bmp"}

    assert capability_module._canonical_json(value) == '{"number":1,"𐀀":"astral","":"bmp"}'
    assert capability_module._sha256(value) == canonical_hash(value)


def test_v3_matrix_has_27_agents_and_28_closed_execution_stages():
    assert len(ALL_AGENT_IDS) == 27
    assert set(AGENT_TOOL_MATRIX) == set(ALL_AGENT_IDS)
    stages = [execution_stage_for_agent(agent) for agent in ALL_AGENT_IDS if agent != "cio"]
    stages += [execution_stage_for_agent("cio", "cio_proposal")]
    stages += [execution_stage_for_agent("cio", "cio_final")]
    assert len(stages) == len(set(stages)) == 28
    with pytest.raises(ValueError, match="capability stage"):
        execution_stage_for_agent("central_bank", "agent_run")
    with pytest.raises(ValueError, match="cio capability stage"):
        execution_stage_for_agent("cio", "cio")


def test_matrix_restricts_roles_to_the_frozen_plan_tools():
    assert allowed_tools_for_agent("china") == ("get_china_macro_snapshot",)
    assert allowed_tools_for_agent("central_bank") == ("get_central_bank_snapshot",)
    assert allowed_tools_for_agent("biotech") == (
        "get_sector_research_snapshot",
        "get_broker_research",
        "get_etf_holdings",
        "get_indicators",
        "get_industry_moneyflow",
        "get_industry_policy_digest",
        "get_rke_research_context",
        "get_stock_data",
        "get_supply_chain_evidence",
    )
    assert allowed_tools_for_agent("semiconductor") == (
        "get_sector_research_snapshot",
        "get_role_event_snapshot",
        "get_balance_sheet",
        "get_broker_research",
        "get_cashflow",
        "get_etf_holdings",
        "get_income_statement",
        "get_indicators",
        "get_industry_moneyflow",
        "get_industry_policy_digest",
        "get_rke_research_context",
        "get_stock_data",
        "get_supply_chain_evidence",
    )
    assert allowed_tools_for_agent("agriculture") == (
        "get_sector_research_snapshot",
        "get_role_event_snapshot",
        "get_broker_research",
        "get_etf_holdings",
        "get_indicators",
        "get_industry_moneyflow",
        "get_industry_policy_digest",
        "get_rke_research_context",
        "get_stock_data",
        "get_supply_chain_evidence",
    )
    assert allowed_tools_for_agent("alpha_discovery") == (
        "get_alpha_candidate_snapshot",
        "get_role_event_snapshot",
        "get_rke_research_context",
    )
    assert allowed_tools_for_agent("ackman") == (
        "get_superinvestor_candidate_snapshot",
        "get_balance_sheet",
        "get_cashflow",
        "get_fundamentals",
        "get_income_statement",
        "get_rke_research_context",
        "get_stock_data",
        "get_stock_research",
    )
    assert allowed_tools_for_agent("cio") == (
        "get_cio_decision_snapshot",
        "get_rke_research_context",
    )


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


def test_bound_runtime_snapshot_allows_same_run_accepted_output_after_market_close(
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
    for evidence in payload["evidence_ledger"]:
        if evidence["source_kind"] == "ACCEPTED_OUTPUT":
            evidence["available_at"] = "2026-07-09T08:00:00+00:00"
    payload["generated_at"] = "2026-07-09T08:01:00+00:00"
    payload = _rehash_bound_snapshot(payload)
    _write_bound_snapshot(
        tmp_path,
        payload=payload,
        tool_id="get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
    )
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(tmp_path))

    rendered = materialize_tool_payload(
        "get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
        as_of="2026-07-09",
        graph_run_id="graph-1",
        expected_candidate_scope_hash=payload["candidate_scope_hash"],
    )

    assert json.loads(rendered) == payload


def test_bound_runtime_snapshot_still_rejects_market_evidence_after_cutoff(
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
    market = next(
        row
        for row in payload["evidence_ledger"]
        if row["source_kind"] == "MARKET_SNAPSHOT"
    )
    market["available_at"] = "2026-07-09T08:00:00+00:00"
    payload["generated_at"] = "2026-07-09T08:01:00+00:00"
    payload = _rehash_bound_snapshot(payload)
    _write_bound_snapshot(
        tmp_path,
        payload=payload,
        tool_id="get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
    )
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(tmp_path))

    with pytest.raises(DataVendorUnavailable, match="not PIT"):
        materialize_tool_payload(
            "get_superinvestor_candidate_snapshot",
            agent_id="ackman",
            stage="ackman",
            as_of="2026-07-09",
            graph_run_id="graph-1",
            expected_candidate_scope_hash=payload["candidate_scope_hash"],
        )


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
    monkeypatch.setitem(
        capability_module.AGENT_TOOL_MATRIX,
        "ackman",
        ("get_superinvestor_candidate_snapshot",),
    )
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
    monkeypatch.setitem(
        capability_module.AGENT_TOOL_MATRIX,
        "ackman",
        ("get_superinvestor_candidate_snapshot",),
    )
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
    monkeypatch.setitem(
        capability_module.AGENT_TOOL_MATRIX,
        "ackman",
        ("get_superinvestor_candidate_snapshot",),
    )
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


def test_prepare_runs_stage_preparer_then_materializer_then_finalizer(
    tmp_path: Path,
) -> None:
    events: list[tuple[str, str]] = []

    def stage_preparer(request: dict) -> dict:
        events.append(("prepare", request["stage"]))
        return {"cache_status": "MISS"}

    def materializer(
        tool_id: str, *, agent_id: str, stage: str, as_of: str, graph_run_id: str
    ) -> str:
        events.append(("materialize", stage))
        return f'{{"tool":"{tool_id}","frozen":true}}'

    def stage_finalizer(context: dict) -> None:
        assert context["stage_preparation"] == {"cache_status": "MISS"}
        assert context["adaptive_query"] is None
        assert set(context["tool_payload_hashes"]) == {"get_china_macro_snapshot"}
        events.append(("finalize", context["stage"]))

    store = AgentToolCapabilityStore(
        tmp_path / "prepared-capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: datetime(2026, 7, 9, tzinfo=timezone.utc),
        stage_materialization_preparer=stage_preparer,
        stage_materialization_finalizer=stage_finalizer,
    )
    request = _request()
    request.pop("stage")
    store.prepare(request, materializer=materializer)
    assert events == [
        ("prepare", "china"),
        ("materialize", "china"),
        ("finalize", "china"),
    ]


@pytest.mark.parametrize(
    ("ensure_mode", "expected_finalizer_calls"),
    [("off", 0), ("shadow", 0), ("enforce", 1)],
)
def test_prepare_only_finalizes_explicit_enforce_mode(
    tmp_path: Path,
    ensure_mode: str,
    expected_finalizer_calls: int,
) -> None:
    finalizer_calls = 0

    def stage_preparer(_request: dict) -> dict:
        return {"ensure_mode": ensure_mode, "status": ensure_mode.upper()}

    def materializer(
        tool_id: str, *, agent_id: str, stage: str, as_of: str, graph_run_id: str
    ) -> str:
        return f'{{"tool":"{tool_id}","frozen":true}}'

    def stage_finalizer(_context: dict) -> None:
        nonlocal finalizer_calls
        finalizer_calls += 1

    store = AgentToolCapabilityStore(
        tmp_path / ensure_mode / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: datetime(2026, 7, 9, tzinfo=timezone.utc),
        stage_materialization_preparer=stage_preparer,
        stage_materialization_finalizer=stage_finalizer,
    )
    store.prepare(_request(), materializer=materializer)
    assert finalizer_calls == expected_finalizer_calls


def test_prepare_failure_does_not_consume_capability_request(tmp_path: Path) -> None:
    materializer_called = False

    def stage_preparer(_request: dict) -> None:
        raise DataVendorUnavailable("trusted stage materialization is blocked")

    def materializer(
        tool_id: str, *, agent_id: str, stage: str, as_of: str, graph_run_id: str
    ) -> str:
        nonlocal materializer_called
        materializer_called = True
        return f'{{"tool":"{tool_id}","frozen":true}}'

    store = AgentToolCapabilityStore(
        tmp_path / "blocked-capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: datetime(2026, 7, 9, tzinfo=timezone.utc),
        stage_materialization_preparer=stage_preparer,
    )
    with pytest.raises(DataVendorUnavailable, match="materialization is blocked"):
        store.prepare(_request(), materializer=materializer)
    assert materializer_called is False
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM materialization_requests").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM snapshot_bundles").fetchone()[0] == 0


def test_stage_finalizer_failure_prevents_capability_publication(tmp_path: Path) -> None:
    materializer_called = False

    def stage_preparer(_request: dict) -> dict:
        return {"cache_status": "MISS"}

    def materializer(
        tool_id: str, *, agent_id: str, stage: str, as_of: str, graph_run_id: str
    ) -> str:
        nonlocal materializer_called
        materializer_called = True
        return f'{{"tool":"{tool_id}","frozen":true}}'

    def stage_finalizer(_context: dict) -> None:
        raise DataVendorUnavailable("trusted stage finalization is blocked")

    store = AgentToolCapabilityStore(
        tmp_path / "finalizer-blocked-capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: datetime(2026, 7, 9, tzinfo=timezone.utc),
        stage_materialization_preparer=stage_preparer,
        stage_materialization_finalizer=stage_finalizer,
    )
    with pytest.raises(DataVendorUnavailable, match="finalization is blocked"):
        store.prepare(_request(), materializer=materializer)
    assert materializer_called is True
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM materialization_requests").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM snapshot_bundles").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM capabilities").fetchone()[0] == 0


@pytest.mark.parametrize(
    "finalizer_status",
    ["READY", "SYNTHETIC_NON_PRODUCTION_BYPASS"],
)
def test_sector_capability_defers_transport_and_limits_successful_followups(
    tmp_path: Path,
    finalizer_status: str,
) -> None:
    now = [datetime(2026, 7, 9, tzinfo=timezone.utc)]
    adaptive_store = FrozenAdaptiveQueryStore(
        tmp_path / "private" / "frozen-queries.sqlite3",
        clock=lambda: now[0],
    )
    indicator_args = {
        "ticker": "600000.SH",
        "as_of": "2026-07-09",
        "lookback": 20,
        "indicator": "rsi",
    }
    adaptive_transports: list[tuple[str, dict]] = []

    def adaptive_materializer(tool_id: str, args: dict) -> dict:
        adaptive_transports.append((tool_id, dict(args)))
        return {
            "payload": json.dumps(
                {"tool": tool_id, "args": args, "frozen": True},
                sort_keys=True,
            ),
            "source_receipt_hashes": [],
        }

    def deferred_sector_preparer(**_kwargs: object) -> dict:
        return adaptive_store.prepare(
            agent_id="energy",
            stage="energy",
            as_of="2026-07-09",
            authorized_scope={
                "as_of": "2026-07-09",
                "earliest_date": "2026-06-01",
                "tickers": ["600000.SH"],
                "etfs": ["512800.SH"],
                "sectors": ["coal"],
                "indicator_families": ["rsi"],
            },
            query_requests=[{"tool_id": "get_indicators", "args": indicator_args}],
            preservation_overlay=build_sector_relationship_preservation_overlay(
                Path(__file__).parents[1]
            ),
            materializer=adaptive_materializer,
            defer_materialization=True,
        )

    adaptive_preparer = ActiveAdaptiveQueryPreparer(
        sector_relationship_preparer=deferred_sector_preparer,
        bound_runtime_preparer=lambda **_kwargs: pytest.fail(
            "sector test dispatched to the bound-runtime preparer"
        ),
    )
    snapshot_calls: list[str] = []

    def stage_finalizer(context: dict) -> dict:
        if finalizer_status == "SYNTHETIC_NON_PRODUCTION_BYPASS":
            return {"status": finalizer_status}
        tool_ids = sorted(context["initial_snapshot_tool_ids"])
        return {
            "agent_id": context["agent_id"],
            "stage": context["stage"],
            "as_of": context["as_of"],
            "status": "READY",
            "tool_ids": tool_ids,
            "build_receipt_hashes": {
                tool_id: canonical_hash(
                    {
                        "tool_id": tool_id,
                        "payload_hash": context["tool_payload_hashes"][tool_id],
                    }
                )
                for tool_id in tool_ids
            },
            "materialization_attempt_receipt_hash": None,
            "cache_status": "MISS",
            "deferred_tool_ids": sorted(context["deferred_tool_ids"]),
            "deferred_query_bundle_hash": context["adaptive_query"]["bundle_hash"],
            "deferred_query_call_contract": CALL_TIME_ARGUMENT_CONTRACT,
        }

    store = AgentToolCapabilityStore(
        tmp_path / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: now[0],
        adaptive_query_store=adaptive_store,
        adaptive_query_preparer=adaptive_preparer,
        adaptive_query_materializer=adaptive_materializer,
        stage_materialization_finalizer=stage_finalizer,
        require_knot_v2_audit_authority=True,
    )

    prepared = store.prepare(
        _request("energy"),
        materializer=lambda tool_id, **_kwargs: (
            snapshot_calls.append(tool_id)
            or json.dumps({"tool": tool_id, "snapshot": True}, sort_keys=True)
        ),
    )
    envelope = prepared["capability"]
    assert adaptive_transports == []
    assert snapshot_calls == [
        "get_sector_research_snapshot",
        "get_role_event_snapshot",
    ]
    assert set(prepared["bundle"]["tool_payload_hashes"]) == set(
        allowed_tools_for_agent("energy")
    )
    with sqlite3.connect(store.db_path) as conn:
        stored_projection = json.loads(
            conn.execute(
                "SELECT public_projection_json FROM snapshot_bundle_adaptive_queries"
            ).fetchone()[0]
        )
        signed_context = json.loads(
            conn.execute(
                "SELECT context_json FROM snapshot_bundle_audit_contexts"
            ).fetchone()[0]
        )
        signed_capability_context = json.loads(
            conn.execute(
                "SELECT context_json FROM capability_audit_contexts"
            ).fetchone()[0]
        )
    expected_eligibility = (
        "ELIGIBLE" if finalizer_status == "READY" else "INELIGIBLE"
    )
    assert signed_context["knot_v2_eligibility"] == expected_eligibility
    assert signed_context["ineligibility_reasons"] == (
        []
        if finalizer_status == "READY"
        else ["SYNTHETIC_NON_PRODUCTION_BYPASS"]
    )
    assert signed_capability_context["knot_v2_eligibility"] == expected_eligibility
    active_indicator_context = next(
        context
        for context in signed_context["tool_contexts"]
        if context["tool_id"] == "get_indicators"
    )
    assert len(active_indicator_context["binding_refs"]) == 1
    assert stored_projection["entries"][0]["binding_id"] == (
        active_indicator_context["binding_refs"][0]["binding_id"]
    )
    expected = {"tool": "get_indicators", "args": indicator_args, "frozen": True}
    if finalizer_status == "SYNTHETIC_NON_PRODUCTION_BYPASS":
        result = store.call_tool_result(envelope, "get_indicators", indicator_args)
        assert json.loads(result["text"]) == expected
        assert "audit" not in result
        assert adaptive_transports == [("get_indicators", indicator_args)]
    else:
        for _round in range(3):
            result = store.call_tool_result(envelope, "get_indicators", indicator_args)
            assert json.loads(result["text"]) == expected
            assert result["audit"]["result_authority_type"] == "FROZEN_QUERY"
        with pytest.raises(ValueError, match="follow-up round limit is exhausted"):
            store.call_tool_result(envelope, "get_indicators", indicator_args)
        assert adaptive_transports == [
            ("get_indicators", indicator_args),
            ("get_indicators", indicator_args),
            ("get_indicators", indicator_args),
        ]
    assert snapshot_calls == [
        "get_sector_research_snapshot",
        "get_role_event_snapshot",
    ]

    with sqlite3.connect(store.db_path) as conn:
        event_rows = conn.execute(
            "SELECT call_mode, status, event_json FROM tool_result_events "
            "ORDER BY sequence"
        ).fetchall()
        if finalizer_status == "SYNTHETIC_NON_PRODUCTION_BYPASS":
            assert event_rows == []
        else:
            assert (
                [row[:2] for row in event_rows].count(("FOLLOW_UP", "SUCCEEDED"))
                == 3
            )
    with sqlite3.connect(adaptive_store.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM frozen_query_payloads").fetchone()[0] == 0


def test_legacy_eager_followup_uses_frozen_store_and_generic_result_event(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    frozen = FrozenAdaptiveQueryStore(
        tmp_path / "private-eager" / "frozen-queries.sqlite3",
        clock=lambda: now,
    )
    indicator_args = {
        "ticker": "600000.SH",
        "as_of": "2026-07-09",
        "lookback": 20,
        "indicator": "rsi",
    }
    expected = {"tool": "get_indicators", "args": indicator_args}
    prepared_query = frozen.prepare(
        agent_id="energy",
        stage="energy",
        as_of="2026-07-09",
        authorized_scope={
            "as_of": "2026-07-09",
            "earliest_date": "2026-06-01",
            "tickers": ["600000.SH"],
            "etfs": ["512800.SH"],
            "sectors": ["coal"],
            "indicator_families": ["rsi"],
        },
        query_requests=[{"tool_id": "get_indicators", "args": indicator_args}],
        preservation_overlay=build_sector_relationship_preservation_overlay(
            Path(__file__).parents[1]
        ),
        materializer=lambda tool_id, args: {
            "payload": json.dumps(expected, sort_keys=True),
            "source_receipt_hashes": [
                canonical_hash({"source": tool_id, "args": args})
            ],
        },
    )

    def stage_finalizer(context: dict) -> dict:
        tool_ids = sorted(context["tool_payload_hashes"])
        return {
            "agent_id": context["agent_id"],
            "stage": context["stage"],
            "as_of": context["as_of"],
            "status": "READY",
            "tool_ids": tool_ids,
            "build_receipt_hashes": {
                tool_id: canonical_hash(
                    {
                        "tool_id": tool_id,
                        "payload_hash": context["tool_payload_hashes"][tool_id],
                    }
                )
                for tool_id in tool_ids
            },
            "materialization_attempt_receipt_hash": canonical_hash(
                {
                    "materialization_request_id": context[
                        "materialization_request_id"
                    ],
                    "tool_ids": tool_ids,
                }
            ),
            "cache_status": "MISS",
        }

    store = AgentToolCapabilityStore(
        tmp_path / "capabilities-eager.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: now,
        adaptive_query_store=frozen,
        adaptive_query_preparer=lambda **_kwargs: prepared_query,
        stage_materialization_finalizer=stage_finalizer,
    )
    prepared = store.prepare(
        _request("energy"),
        materializer=lambda tool_id, **_kwargs: json.dumps(
            {"tool": tool_id, "snapshot": True}, sort_keys=True
        ),
    )

    result = store.call_tool_result(
        prepared["capability"], "get_indicators", indicator_args
    )

    assert json.loads(result["text"]) == expected
    assert result["audit"]["result_authority_type"] == "FROZEN_QUERY"
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM tool_result_events").fetchone()[0] == 1
    with sqlite3.connect(frozen.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM frozen_query_calls").fetchone()[0] == 1


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


def test_multi_tool_capability_has_one_atomic_use_slot_per_tool(tmp_path, monkeypatch):
    now = [datetime(2026, 7, 9, tzinfo=timezone.utc)]
    monkeypatch.setitem(
        capability_module.AGENT_TOOL_MATRIX,
        "cro",
        ("get_cro_risk_snapshot", "get_role_event_snapshot"),
    )
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
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert tables == {
            "snapshot_bundles",
            "materialization_requests",
            "capabilities",
            "capability_events",
            "capability_tool_uses",
            "snapshot_bundle_audit_contexts",
            "capability_audit_contexts",
            "tool_result_events",
            "binding_signal_projections",
            "accepted_knot_history_materializations_v2",
            "trusted_counterevidence_evaluations_v2",
            "knot_binding_observations_v2",
            "tool_security_rejections",
            "snapshot_bundle_adaptive_queries",
            "capability_adaptive_sessions",
            "sector_model_usage_events",
            "sector_model_usage_summaries",
        }
        for table in (
            "snapshot_bundles",
            "materialization_requests",
            "capabilities",
            "capability_events",
            "capability_tool_uses",
            "snapshot_bundle_audit_contexts",
            "capability_audit_contexts",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                conn.execute(f"DELETE FROM {table}")


def test_capability_store_has_no_knot_authority_compatibility_ports(tmp_path):
    now = [datetime(2026, 7, 9, tzinfo=timezone.utc)]
    store = _store(tmp_path, now)
    removed_ports = {
        "verify_and_reserve_knot_pair_root",
        "classify_and_reserve_knot_regime",
        "bind_knot_private_pair",
        "record_knot_sector_model_usage",
        "mint_knot_sector_inference_usage_receipt",
        "mint_knot_strict_output_validation_receipt",
        "resolve_knot_pair_side_capability",
    }
    assert all(not hasattr(store, port) for port in removed_ports)














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
    assert "pair_root_reservation_id" not in summary
    assert "pair_side" not in summary
    assert "budget_contract_ref" not in summary
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

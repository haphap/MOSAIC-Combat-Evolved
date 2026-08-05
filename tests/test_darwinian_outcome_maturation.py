from __future__ import annotations

import json
import sqlite3
import importlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

import pytest

from mosaic.dataflows.outcome_runtime_inputs import (
    OUTCOME_PROJECTION_SCHEMA_VERSION,
    expected_qualification_predicate_version,
)
from mosaic.scorecard.darwinian_updates import (
    append_outcome_eligibility_revision,
    freeze_evaluation_opportunity_set,
    materialize_due_outcomes,
)
from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import (
    OUTCOME_CONTRACTS,
    OUTCOME_METRIC_SCHEMAS_HASH,
    OUTCOME_PROJECTION_SCHEMA_HASH,
    OUTCOME_REALIZED_METRIC_SCHEMAS_HASH,
    OUTCOME_REGISTRY_HASH,
)
from mosaic.scorecard.store import ScorecardStore
from tests.outcome_source_authority_helpers import (
    EphemeralOutcomeSourceAuthority,
    authority_projection_pins,
    provision_test_outcome_source_authority,
    seal_test_outcome_source_batch,
)


CUTOFF_AT = "2026-07-17T15:00:00+08:00"


def _bindings() -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        dimensions = contract["track_contract_dimensions"]
        result[agent_id] = {
            "agent_contract_version": f"{agent_id}_agent_v2",
            "prompt_behavior_version": f"{agent_id}_prompt_v2",
            "execution_behavior_version": f"{agent_id}_execution_v2",
            "component_weight_contract_version": (
                "macro_component_weights_v2"
                if dimensions["component_weight_contract"] == "REQUIRED"
                else None
            ),
            "reliability_adapter_contract_version": (
                f"{agent_id}_adapter_v2"
                if dimensions["reliability_adapter_contract"] == "REQUIRED"
                else None
            ),
            "confidence_semantics_contract_version": (
                f"{agent_id}_confidence_v2"
                if dimensions["confidence_semantics_contract"] == "REQUIRED"
                else None
            ),
        }
    return result


def _trading_dates() -> list[str]:
    values: list[str] = []
    current = date(2026, 5, 1)
    end = date.fromisoformat(CUTOFF_AT[:10])
    while current <= end:
        if current.weekday() < 5:
            values.append(current.isoformat())
        current += timedelta(days=1)
    return values


def _long_trading_dates() -> list[str]:
    values: list[str] = []
    current = date(2010, 1, 4)
    end = date.fromisoformat(CUTOFF_AT[:10])
    while current <= end:
        if current.weekday() < 5:
            values.append(current.isoformat())
        current += timedelta(days=1)
    return values


def _track_by_agent(conn: sqlite3.Connection, revision: Mapping[str, Any]) -> dict[str, str]:
    placeholders = ",".join("?" for _ in revision["evaluation_track_key_hashes"])
    rows = conn.execute(
        f"SELECT agent_id, track_key_hash FROM darwinian_v2_evaluation_tracks "
        f"WHERE track_key_hash IN ({placeholders})",
        tuple(revision["evaluation_track_key_hashes"]),
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _member_refs(agent_id: str) -> list[dict[str, Any]]:
    contract = OUTCOME_CONTRACTS[agent_id]
    object_type = contract["evaluation_object_type"]
    if object_type == "MACRO_TRANSMISSION":
        field = (
            "event_id"
            if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
            else "path_snapshot_id"
        )
        return [{field: f"maturity-member:{agent_id}"}]
    family = contract["metric_family"]
    if family == "STANDARD_SECTOR":
        return [
            {
                "subindustry_id": "direction:preferred",
                "security_shortlist_id": "shortlist:preferred",
                "security_shortlist_hash": "sha256:" + "1" * 64,
                "security_ts_codes": ["600001.SH"],
            },
            {
                "subindustry_id": "direction:least",
                "security_shortlist_id": "shortlist:least",
                "security_shortlist_hash": "sha256:" + "2" * 64,
                "security_ts_codes": ["600002.SH"],
            },
        ]
    if family == "RELATIONSHIP":
        return [{"edge_candidate_id": "edge:1", "materiality_weight": 1.0}]
    if family == "SUPERINVESTOR":
        return [{"candidate_ref": "candidate:1", "ts_code": "600003.SH"}]
    if family == "CRO":
        return [
            {
                "risk_candidate_id": "candidate:1",
                "ts_code": "600004.SH",
                "proposed_target_weight": 0.1,
            }
        ]
    if family == "ALPHA":
        return [{"candidate_ref": "candidate:1", "ts_code": "600005.SH"}]
    if family == "EXECUTION":
        return [
            {
                "order_intent_id": "order:1",
                "ts_code": "600006.SH",
                "action": "BUY",
                "requested_delta_weight": 0.1,
            }
        ]
    if family == "CIO":
        return [
            {
                "controlled_target_set_id": "controlled-targets:maturity",
                "baseline_cash_weight": 0.3,
                "positions": [
                    {
                        "position_ref": "position:maturity:600007.SH",
                        "ts_code": "600007.SH",
                        "baseline_weight": 0.7,
                        "controlled_target_weight": 0.8,
                    }
                ],
            }
        ]
    raise AssertionError(f"unsupported metric family: {family}")


def _runtime_authority_binding(agent_id: str) -> dict[str, str] | None:
    from mosaic.scorecard.darwinian_updates import LIVE_SOURCE_TOOL_BY_AGENT

    live_tool_id = LIVE_SOURCE_TOOL_BY_AGENT.get(agent_id)
    if live_tool_id is not None:
        return {
            "source_tool_id": live_tool_id,
            "source_snapshot_hash": canonical_hash(
                {"agent_id": agent_id, "kind": "source"}
            ),
            "domain_hash": canonical_hash(
                {"agent_id": agent_id, "kind": "domain"}
            ),
        }
    tool_id = {
        "alpha_discovery": "get_alpha_candidate_snapshot",
        "cro": "get_cro_risk_snapshot",
        "autonomous_execution": "get_execution_snapshot",
        "cio": "get_cio_decision_snapshot",
    }.get(agent_id)
    if tool_id is None:
        return None
    return {
        "source_tool_id": tool_id,
        "source_snapshot_hash": canonical_hash({"agent_id": agent_id, "kind": "source"}),
        "candidate_scope_hash": canonical_hash({"agent_id": agent_id, "kind": "scope"}),
        "candidate_universe_hash": canonical_hash(
            {"agent_id": agent_id, "kind": "universe"}
        ),
        "upstream_accepted_output_refs_hash": canonical_hash(
            {"agent_id": agent_id, "kind": "upstream"}
        ),
    }


def _required_source_evidence(agent_id: str) -> dict[str, list[str]]:
    return {
        source_id: [f"maturity-source:{agent_id}:{index}"]
        for index, source_id in enumerate(
            OUTCOME_CONTRACTS[agent_id]["required_source_ids"]
        )
    }


def _as_of_for_due_agent(agent_id: str, due_at: str = CUTOFF_AT) -> str:
    dates = _trading_dates()
    horizon = OUTCOME_CONTRACTS[agent_id]["maturity"]["horizon_trading_days"]
    due_index = dates.index(due_at[:10])
    return f"{dates[due_index - horizon]}T15:00:00+08:00"


def _insert_schedule_slot(
    conn: sqlite3.Connection,
    *,
    revision: Mapping[str, Any],
    track_hash: str,
    agent_id: str,
    as_of_at: str,
    outcome_due_at: str = CUTOFF_AT,
    forge_slot_hash: bool = False,
    stored_slot_agent_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan_id = f"maturity-plan:{agent_id}"
    graph_run_id = f"maturity-graph:{agent_id}"
    sample_id = f"maturity-sample:{agent_id}"
    slot_without_hash = {
        "outcome_schedule_slot_id": f"maturity-slot:{agent_id}",
        "schema_version": "outcome_schedule_slot_v2",
        "outcome_schedule_plan_id": plan_id,
        "graph_run_id": graph_run_id,
        "agent_id": agent_id,
        "track_key_hash": track_hash,
        "run_slot_id": f"maturity-run-slot:{agent_id}",
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": sample_id,
        "outcome_due_at": outcome_due_at,
        "trigger_event": None,
        "excluded_events": [],
        "sample_schedule": OUTCOME_CONTRACTS[agent_id]["sample_schedule"],
        "sample_schedule_contract_version": OUTCOME_CONTRACTS[agent_id][
            "sample_schedule_contract_version"
        ],
    }
    slot = {
        **slot_without_hash,
        "outcome_schedule_slot_hash": canonical_hash(slot_without_hash),
    }
    if forge_slot_hash:
        slot["outcome_schedule_slot_hash"] = "sha256:" + "0" * 64
    plan_without_hash = {
        "outcome_schedule_plan_id": plan_id,
        "schema_version": "outcome_schedule_plan_v2",
        "graph_run_id": graph_run_id,
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": revision[
            "production_variant_roster_revision_id"
        ],
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": revision["cohort_id"],
        "language": revision["language"],
        "trading_calendar_id": "cn_a_share_trading_calendar_v1",
        "trading_calendar_snapshot_hash": canonical_hash(_trading_dates()),
        "event_candidate_input_hash": canonical_hash({}),
        "as_of": as_of_at,
        "prepared_at": as_of_at,
        "slots": [slot],
    }
    plan = {
        **plan_without_hash,
        "outcome_schedule_plan_hash": canonical_hash(plan_without_hash),
    }
    conn.execute(
        "INSERT INTO outcome_schedule_plans_v2 ("
        "outcome_schedule_plan_id, outcome_schedule_plan_hash, graph_run_id, "
        "production_variant_roster_id, production_variant_roster_revision_id, "
        "execution_behavior_release_id, cohort_id, language, trading_calendar_id, "
        "trading_calendar_snapshot_hash, as_of, prepared_at, record_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            plan_id,
            plan["outcome_schedule_plan_hash"],
            graph_run_id,
            revision["production_variant_roster_id"],
            revision["production_variant_roster_revision_id"],
            revision["execution_behavior_release_id"],
            revision["cohort_id"],
            revision["language"],
            plan["trading_calendar_id"],
            plan["trading_calendar_snapshot_hash"],
            as_of_at,
            as_of_at,
            json.dumps(plan),
        ),
    )
    conn.execute(
        "INSERT INTO outcome_schedule_slots_v2 ("
        "outcome_schedule_slot_id, outcome_schedule_slot_hash, "
        "outcome_schedule_plan_id, graph_run_id, agent_id, track_key_hash, "
        "run_slot_id, run_slot_kind, scheduled_sample_id, trigger_event_id, record_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, 'OUTCOME_SCHEDULED', ?, NULL, ?)",
        (
            slot["outcome_schedule_slot_id"],
            slot["outcome_schedule_slot_hash"],
            plan_id,
            graph_run_id,
            stored_slot_agent_id or agent_id,
            track_hash,
            slot["run_slot_id"],
            sample_id,
            json.dumps(slot),
        ),
    )
    return plan, slot


def _insert_acceptance(
    conn: sqlite3.Connection,
    *,
    revision: Mapping[str, Any],
    track_hash: str,
    agent_id: str,
    scheduled_sample_id: str,
    as_of_at: str,
    opportunity: Mapping[str, Any],
) -> dict[str, Any]:
    contract = OUTCOME_CONTRACTS[agent_id]
    accepted_id = f"maturity-accepted:{agent_id}"
    without_hash = {
        "accepted_output_id": accepted_id,
        "graph_run_id": f"maturity-graph:{agent_id}",
        "run_id": f"maturity-run:{agent_id}",
        "run_slot_id": f"maturity-run-slot:{agent_id}",
        "operational_opportunity_audit_id": f"maturity-operational:{agent_id}",
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": revision[
            "production_variant_roster_revision_id"
        ],
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": revision["cohort_id"],
        "language": revision["language"],
        "track_key_hash": track_hash,
        "agent_id": agent_id,
        "accepted_output_kind": contract["accepted_output_kind"],
        "sample_origin": "PRODUCTION_ACTIVE",
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": scheduled_sample_id,
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "frozen_object_set_id": opportunity.get("frozen_object_set_id"),
        "frozen_object_set_hash": opportunity.get("frozen_object_set_hash"),
        **(
            {
                "runtime_opportunity_authority": opportunity[
                    "runtime_authority_binding"
                ]
            }
            if opportunity.get("runtime_authority_binding") is not None
            else {}
        ),
        "as_of": as_of_at,
        "accepted_at": as_of_at,
        "output": {"payload": _accepted_payload(agent_id)},
    }
    record = {**without_hash, "accepted_output_hash": canonical_hash(without_hash)}
    conn.execute(
        "INSERT INTO accepted_agent_outputs_v2 ("
        "accepted_output_id, accepted_output_hash, graph_run_id, run_id, run_slot_id, "
        "operational_opportunity_audit_id, production_variant_roster_id, "
        "production_variant_roster_revision_id, execution_behavior_release_id, "
        "cohort_id, language, track_key_hash, agent_id, accepted_output_kind, "
        "sample_origin, run_slot_kind, scheduled_sample_id, as_of, accepted_at, record_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            accepted_id,
            record["accepted_output_hash"],
            record["graph_run_id"],
            record["run_id"],
            record["run_slot_id"],
            record["operational_opportunity_audit_id"],
            revision["production_variant_roster_id"],
            revision["production_variant_roster_revision_id"],
            revision["execution_behavior_release_id"],
            revision["cohort_id"],
            revision["language"],
            track_hash,
            agent_id,
            contract["accepted_output_kind"],
            "PRODUCTION_ACTIVE",
            "OUTCOME_SCHEDULED",
            scheduled_sample_id,
            as_of_at,
            as_of_at,
            json.dumps(record),
        ),
    )
    return record


def _seed_pending(
    conn: sqlite3.Connection,
    *,
    revision: Mapping[str, Any],
    tracks: Mapping[str, str],
    agent_id: str,
    due_at: str = CUTOFF_AT,
    as_of_at_override: str | None = None,
    forge_slot_hash: bool = False,
    stored_slot_agent_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    as_of_at = as_of_at_override or _as_of_for_due_agent(agent_id, due_at)
    _, slot = _insert_schedule_slot(
        conn,
        revision=revision,
        track_hash=tracks[agent_id],
        agent_id=agent_id,
        as_of_at=as_of_at,
        outcome_due_at=due_at,
        forge_slot_hash=forge_slot_hash,
        stored_slot_agent_id=stored_slot_agent_id,
    )
    opportunity = freeze_evaluation_opportunity_set(
        conn,
        production_variant_roster_revision_id=revision[
            "production_variant_roster_revision_id"
        ],
        track_key_hash=tracks[agent_id],
        scheduled_sample_id=slot["scheduled_sample_id"],
        sample_origin="PRODUCTION_ACTIVE",
        as_of=as_of_at,
        member_refs=_member_refs(agent_id),
        required_source_evidence_ids=[f"opportunity-evidence:{agent_id}"],
        qualification_predicate_version=expected_qualification_predicate_version(
            agent_id
        ),
        runtime_authority_binding=_runtime_authority_binding(agent_id),
    )
    accepted = _insert_acceptance(
        conn,
        revision=revision,
        track_hash=tracks[agent_id],
        agent_id=agent_id,
        scheduled_sample_id=slot["scheduled_sample_id"],
        as_of_at=as_of_at,
        opportunity=opportunity,
    )
    pending = append_outcome_eligibility_revision(
        conn,
        track_key_hash=tracks[agent_id],
        scheduled_sample_id=slot["scheduled_sample_id"],
        sample_origin="PRODUCTION_ACTIVE",
        disposition="PENDING",
        recorded_at=as_of_at,
        evaluation_opportunity_set_id=opportunity["evaluation_opportunity_set_id"],
        accepted_output_id=accepted["accepted_output_id"],
    )
    return slot, opportunity, pending


def _minimal_schema_value(schema: Mapping[str, Any]) -> Any:
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return _minimal_schema_value(schema["anyOf"][0])
    if "oneOf" in schema:
        return _minimal_schema_value(schema["oneOf"][0])
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next(item for item in schema_type if item != "null")
    if schema_type == "object":
        properties = schema.get("properties", {})
        return {
            field: _minimal_schema_value(properties[field])
            for field in schema.get("required", [])
        }
    if schema_type == "array":
        items = schema.get("items", {})
        if isinstance(items, list):
            return [_minimal_schema_value(item) for item in items]
        return [
            _minimal_schema_value(items)
            for _ in range(int(schema.get("minItems", 0)))
        ]
    if schema_type == "string":
        return "fixture"
    if schema_type == "boolean":
        return False
    if schema_type in {"number", "integer"}:
        if "exclusiveMinimum" in schema:
            value: float = float(schema["exclusiveMinimum"]) + 1
        else:
            value = float(schema.get("minimum", 0))
        return int(value) if schema_type == "integer" else value
    if schema_type == "null":
        return None
    raise AssertionError(f"unsupported test schema fragment: {schema}")


def _accepted_payload(agent_id: str) -> dict[str, Any]:
    family = OUTCOME_CONTRACTS[agent_id]["metric_family"]
    if family == "MACRO_TRANSMISSION":
        return {
            "agent_id": agent_id,
            "direction": "SUPPORTIVE",
            "strength": 1,
            "confidence": 0.5,
        }
    if family == "STANDARD_SECTOR":
        return {
            "sector_agent_id": agent_id,
            "selection": {
                "selection_status": "SELECTED",
                "preferred_direction": {
                    "direction_id": "direction:preferred",
                    "strength": 4,
                },
                "least_preferred_direction": {
                    "direction_id": "direction:least",
                    "strength": 3,
                },
                "preferred_security_status": "PICKS_PRESENT",
                "long_picks": [
                    {
                        "ts_code": "600001.SH",
                        "position_action": "LONG",
                        "conviction": 0.7,
                    }
                ],
                "least_preferred_security_status": "PICKS_PRESENT",
                "short_or_avoid_picks": [
                    {
                        "ts_code": "600002.SH",
                        "position_action": "SHORT",
                        "conviction": 0.6,
                    }
                ],
            },
            "preferred_security_shortlist_id": "shortlist:preferred",
            "preferred_security_shortlist_hash": "sha256:" + "1" * 64,
            "least_preferred_security_shortlist_id": "shortlist:least",
            "least_preferred_security_shortlist_hash": "sha256:" + "2" * 64,
            "directional_confidence": 0.5,
        }
    if family == "RELATIONSHIP":
        return {
            "relationship_agent_id": agent_id,
            "predictive_graph_status": "EDGES_PRESENT",
            "predictive_graph_abstention_confidence": None,
            "predictive_edges": [
                {
                    "edge_candidate_id": "edge:1",
                    "transmission_direction": "POSITIVE",
                    "calibrated_confidence": 0.7,
                }
            ],
        }
    if family == "SUPERINVESTOR":
        return {
            "superinvestor_agent_id": agent_id,
            "selection": {
                "selection_status": "SELECTED",
                "picks": [
                    {
                        "pick_local_id": "pick:1",
                        "ts_code": "600003.SH",
                        "position_action": "LONG",
                        "conviction": 0.8,
                    }
                ],
            },
            "model_confidence": 0.6,
        }
    if family == "CRO":
        return {
            "agent_id": "cro",
            "review": {
                "candidate_actions": [
                    {
                        "candidate_ref": "candidate:1",
                        "ts_code": "600004.SH",
                        "action": "CAP_WEIGHT",
                        "predicted_risk_probability": 0.8,
                    }
                ]
            },
        }
    if family == "ALPHA":
        return {
            "agent_id": "alpha_discovery",
            "selection": {
                "discovery_disposition": "CANDIDATES",
                "novel_picks": [
                    {
                        "candidate_ref": "candidate:1",
                        "ts_code": "600005.SH",
                        "conviction": 0.7,
                    }
                ],
            },
            "model_confidence": 0.6,
        }
    if family == "EXECUTION":
        return {
            "agent_id": "autonomous_execution",
            "execution_mode": "PAPER",
            "assessment": {
                "order_assessments": [
                    {
                        "order_intent_ref": "order:1",
                        "ts_code": "600006.SH",
                        "requested_delta_weight": 0.1,
                        "feasibility": "FEASIBLE",
                        "feasibility_confidence": 0.8,
                        "predicted_cost_bps": 8.0,
                    }
                ]
            },
        }
    if family == "CIO":
        return {
            "agent_id": "cio",
            "decision_stage": "FINAL",
            "decision": {
                "decision_disposition": "TARGET_PORTFOLIO",
                "cash_weight": 0.2,
                "target_positions": [
                    {"ts_code": "600007.SH", "target_weight": 0.8}
                ],
            },
        }
    raise AssertionError(f"unsupported metric family: {family}")


def _realized_metrics(agent_id: str) -> dict[str, Any]:
    family = OUTCOME_CONTRACTS[agent_id]["metric_family"]
    if family == "MACRO_TRANSMISSION":
        return {"role_path_metric": 0.1, "pit_volatility_scale": 1.0}
    if family == "STANDARD_SECTOR":
        return {
            "direction_paths": [
                {
                    "direction_id": "direction:preferred",
                    "realized_return_5d": 0.02,
                    "parent_sector_return_5d": 0.01,
                    "realized_scaled_path": 0.2,
                },
                {
                    "direction_id": "direction:least",
                    "realized_return_5d": -0.01,
                    "parent_sector_return_5d": 0.01,
                    "realized_scaled_path": -0.2,
                },
            ],
            "security_paths": [
                {
                    "side": "PREFERRED",
                    "direction_id": "direction:preferred",
                    "ts_code": "600001.SH",
                    "net_alpha_5d": 0.02,
                    "realized_scaled_alpha": 0.2,
                },
                {
                    "side": "LEAST_PREFERRED",
                    "direction_id": "direction:least",
                    "ts_code": "600002.SH",
                    "net_alpha_5d": -0.02,
                    "realized_scaled_alpha": -0.2,
                },
            ],
        }
    if family == "RELATIONSHIP":
        return {
            "edge_paths": [
                {
                    "edge_candidate_id": "edge:1",
                    "realized_edge_state": "POSITIVE",
                    "matched_non_edge_lift": 0.2,
                }
            ]
        }
    if family == "SUPERINVESTOR":
        return {
            "candidate_paths": [
                {
                    "candidate_ref": "candidate:1",
                    "ts_code": "600003.SH",
                    "realized_net_excess_return_21d": 0.1,
                }
            ]
        }
    if family == "CRO":
        return {
            "candidate_states": [
                {
                    "candidate_ref": "candidate:1",
                    "ts_code": "600004.SH",
                    "realized_risk_state": 1,
                    "realized_risk_evidence_ids": ["risk:evidence:1"],
                }
            ]
        }
    if family == "ALPHA":
        return {
            "candidate_paths": [
                {
                    "candidate_ref": "candidate:1",
                    "ts_code": "600005.SH",
                    "realized_net_excess_return_5d": 0.05,
                }
            ]
        }
    if family == "EXECUTION":
        return {
            "order_paths": [
                {
                    "order_intent_ref": "order:1",
                    "ts_code": "600006.SH",
                    "realized_feasibility": "FEASIBLE",
                    "realized_cost_bps": 9.0,
                    "pit_cost_scale_bps": 10.0,
                    "realized_delta_weight": 0.1,
                    "realized_policy_compliance": 1,
                    "outcome_evidence_ids": ["execution:evidence:1"],
                }
            ]
        }
    if family == "CIO":
        return {
            "position_paths": [
                {
                    "ts_code": "600007.SH",
                    "realized_weight": 0.8,
                    "realized_net_return_5d": 0.02,
                }
            ],
            "realized_cash_weight": 0.2,
            "accepted_portfolio_net_return_5d": 0.02,
            "baseline_portfolio_net_return_5d": 0.014,
            "accepted_portfolio_max_drawdown_5d": -0.01,
            "baseline_portfolio_max_drawdown_5d": -0.02,
            "accepted_portfolio_turnover_cost": 0.001,
            "baseline_portfolio_turnover_cost": 0.0,
            "realized_constraint_compliance": 1,
        }
    raise AssertionError(f"unsupported metric family: {family}")


def _write_projection(
    root: Path,
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    track_hash: str,
    slot: Mapping[str, Any],
    opportunity: Mapping[str, Any],
    pending: Mapping[str, Any],
    authority: EphemeralOutcomeSourceAuthority,
    status: str = "SCORE",
) -> None:
    contract = OUTCOME_CONTRACTS[agent_id]
    realized_metrics = _realized_metrics(agent_id) if status == "SCORE" else {}
    evaluation_context = {
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "accepted_output_id": pending["accepted_output_id"],
        "accepted_output_hash": pending["accepted_output_hash"],
        "track_key_hash": track_hash,
        "agent_id": agent_id,
        "opportunity_as_of": opportunity["as_of"],
        "outcome_due_at": slot["outcome_due_at"],
        "realized_metric_schema_id": contract["realized_metric_schema_id"],
    }
    source_batch = seal_test_outcome_source_batch(
        conn,
        authority=authority,
        evaluation_context=evaluation_context,
        realized_metrics=realized_metrics,
        at=CUTOFF_AT,
        projection_status=status,
        abstain_reason=None if status == "SCORE" else "OUTCOME_NOT_OBSERVABLE",
    )
    source_pins = authority_projection_pins(authority)
    payload = {
        "schema_version": OUTCOME_PROJECTION_SCHEMA_VERSION,
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "accepted_output_id": pending["accepted_output_id"],
        "accepted_output_hash": pending["accepted_output_hash"],
        "track_key_hash": track_hash,
        "agent_id": agent_id,
        "metric_family": contract["metric_family"],
        "metric_schema_id": contract["metric_schema_id"],
        "realized_metric_schema_id": contract["realized_metric_schema_id"],
        "outcome_registry_hash": OUTCOME_REGISTRY_HASH,
        "metric_schemas_hash": OUTCOME_METRIC_SCHEMAS_HASH,
        "realized_metric_schemas_hash": OUTCOME_REALIZED_METRIC_SCHEMAS_HASH,
        "outcome_projection_schema_hash": OUTCOME_PROJECTION_SCHEMA_HASH,
        "source_authority_registry_hash": source_pins[
            "authority_registry_hash"
        ],
        "source_authority_registry_schema_hash": source_pins[
            "authority_registry_schema_hash"
        ],
        "source_receipt_schema_hash": source_pins["receipt_schema_hash"],
        "source_batch_schema_hash": source_pins["batch_schema_hash"],
        "opportunity_as_of": opportunity["as_of"],
        "outcome_due_at": slot["outcome_due_at"],
        "generated_at": CUTOFF_AT,
        "pit_status": "VERIFIED",
        "source_batch_id": source_batch["source_batch_id"],
        "source_batch_hash": source_batch["source_batch_hash"],
    }
    record = {**payload, "snapshot_hash": canonical_hash(payload)}
    path = (
        root
        / slot["outcome_due_at"][:10]
        / "realized_outcomes"
        / f"{slot['scheduled_sample_id']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def test_freeze_revalidates_member_domain_and_qualification_predicate(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        track_hash = _track_by_agent(conn, revision)["china"]
        common = {
            "production_variant_roster_revision_id": revision[
                "production_variant_roster_revision_id"
            ],
            "track_key_hash": track_hash,
            "scheduled_sample_id": "forged-member-sample",
            "sample_origin": "PRODUCTION_ACTIVE",
            "as_of": "2026-07-10T15:00:00+08:00",
            "required_source_evidence_ids": ["official:china"],
        }
        with pytest.raises(ValueError, match="must contain exactly 'event_id'"):
            freeze_evaluation_opportunity_set(
                conn,
                **common,
                member_refs=[{"forged": "cn-cpi"}],
                qualification_predicate_version=(
                    expected_qualification_predicate_version("china")
                ),
            )
        with pytest.raises(ValueError, match="qualification predicate"):
            freeze_evaluation_opportunity_set(
                conn,
                **common,
                member_refs=[{"event_id": "cn-cpi"}],
                qualification_predicate_version="caller-selected-predicate",
            )


def test_server_authority_ledger_proves_freeze_precedes_accepted_output(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        track_hash = _track_by_agent(conn, revision)["china"]
        _, opportunity, _ = _seed_pending(
            conn,
            revision=revision,
            tracks={"china": track_hash},
            agent_id="china",
        )
        events_before_retry = conn.execute(
            "SELECT authority_event_sequence, event_kind, authority_recorded_at, "
            "evaluation_opportunity_set_id, evaluation_opportunity_set_hash "
            "FROM evaluation_authority_events_v2 "
            "WHERE scheduled_sample_id = ? ORDER BY authority_event_sequence",
            (opportunity["scheduled_sample_id"],),
        ).fetchall()
        retry = freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=track_hash,
            scheduled_sample_id=opportunity["scheduled_sample_id"],
            sample_origin="PRODUCTION_ACTIVE",
            as_of=opportunity["as_of"],
            member_refs=_member_refs("china"),
            required_source_evidence_ids=["opportunity-evidence:china"],
            qualification_predicate_version=(
                expected_qualification_predicate_version("china")
            ),
            runtime_authority_binding=_runtime_authority_binding("china"),
        )
        events_after_retry = conn.execute(
            "SELECT authority_event_sequence, event_kind, authority_recorded_at, "
            "evaluation_opportunity_set_id, evaluation_opportunity_set_hash "
            "FROM evaluation_authority_events_v2 "
            "WHERE scheduled_sample_id = ? ORDER BY authority_event_sequence",
            (opportunity["scheduled_sample_id"],),
        ).fetchall()
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute(
                "UPDATE evaluation_authority_events_v2 "
                "SET authority_recorded_at = authority_recorded_at"
            )

    assert retry == opportunity
    assert [row[1] for row in events_before_retry] == [
        "OPPORTUNITY_FROZEN",
        "ACCEPTED_OUTPUT_PERSISTED",
    ]
    assert events_before_retry[0][0] < events_before_retry[1][0]
    assert events_before_retry[0][2] <= events_before_retry[1][2]
    assert all(
        row[3] == opportunity["evaluation_opportunity_set_id"]
        and row[4] == opportunity["evaluation_opportunity_set_hash"]
        for row in events_before_retry
    )
    assert [tuple(row) for row in events_after_retry] == [
        tuple(row) for row in events_before_retry
    ]


def test_all_28_agents_materialize_role_owned_outcomes_without_cio_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "outcome-runtime"
    monkeypatch.setenv("MOSAIC_OUTCOME_RUNTIME_DIR", str(runtime_root))
    authority = provision_test_outcome_source_authority(tmp_path, monkeypatch)
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        for agent_id in sorted(OUTCOME_CONTRACTS):
            slot, opportunity, pending = _seed_pending(
                conn,
                revision=revision,
                tracks=tracks,
                agent_id=agent_id,
            )
            _write_projection(
                runtime_root,
                conn,
                agent_id=agent_id,
                track_hash=tracks[agent_id],
                slot=slot,
                opportunity=opportunity,
                pending=pending,
                authority=authority,
            )

        batch = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_trading_dates(),
        )

        assert batch["due_pending_count"] == 28
        assert batch["scored_count"] == 28
        assert batch["abstained_count"] == 0
        assert batch["unresolved_count"] == 0
        assert {OUTCOME_CONTRACTS[row["agent_id"]]["metric_family"] for row in batch["results"]} == {
            "MACRO_TRANSMISSION",
            "STANDARD_SECTOR",
            "RELATIONSHIP",
            "SUPERINVESTOR",
            "CRO",
            "ALPHA",
            "EXECUTION",
            "CIO",
        }
        assert sum(
            row["darwin_application_mode"] == "DOWNSTREAM_USAGE_WEIGHT"
            for row in batch["results"]
        ) == 24
        assert sum(
            row["darwin_application_mode"] == "EVOLUTION_ONLY"
            for row in batch["results"]
        ) == 4
        label_count = conn.execute(
            "SELECT COUNT(*) FROM agent_outcome_labels_v2"
        ).fetchone()[0]
        assert label_count == 28
        upstream_raw = [
            json.loads(row[0])["raw_metrics"]
            for row in conn.execute(
                "SELECT record_json FROM agent_outcome_labels_v2 WHERE agent_id != 'cio'"
            ).fetchall()
        ]
        assert all(
            not {
                "cio_portfolio_return",
                "cio_total_pnl",
                "downstream_portfolio_pnl",
            }
            & set(raw)
            for raw in upstream_raw
        )


@pytest.mark.parametrize(
    ("mutation", "error_match"),
    [
        ("batch_id", "server-selected source batch"),
        ("batch_hash", "server-selected source batch"),
    ],
)
def test_production_maturation_requires_exact_pit_source_receipt_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    error_match: str | None,
) -> None:
    runtime_root = tmp_path / "outcome-runtime"
    monkeypatch.setenv("MOSAIC_OUTCOME_RUNTIME_DIR", str(runtime_root))
    authority = provision_test_outcome_source_authority(tmp_path, monkeypatch)
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        slot, opportunity, pending = _seed_pending(
            conn,
            revision=revision,
            tracks=tracks,
            agent_id="china",
        )
        _write_projection(
            runtime_root,
            conn,
            agent_id="china",
            track_hash=tracks["china"],
            slot=slot,
            opportunity=opportunity,
            pending=pending,
            authority=authority,
        )
        path = (
            runtime_root
            / slot["outcome_due_at"][:10]
            / "realized_outcomes"
            / f"{slot['scheduled_sample_id']}.json"
        )
        projection = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "batch_id":
            projection["source_batch_id"] = "outcome-source-batch:forged"
        else:
            projection["source_batch_hash"] = "sha256:" + "f" * 64
        projection_without_hash = {
            key: value for key, value in projection.items() if key != "snapshot_hash"
        }
        projection["snapshot_hash"] = canonical_hash(projection_without_hash)
        path.write_text(json.dumps(projection), encoding="utf-8")

        with pytest.raises(ValueError, match=error_match):
            materialize_due_outcomes(
                conn,
                production_variant_roster_revision_id=revision[
                    "production_variant_roster_revision_id"
                ],
                cutoff_at=CUTOFF_AT,
                trading_dates=_trading_dates(),
            )


def test_callback_verified_source_receipt_api_is_removed() -> None:
    import mosaic.scorecard.outcome_source_receipts as source_receipts

    assert not hasattr(source_receipts, "append_verified_outcome_source_receipt")
    assert not hasattr(source_receipts, "source_receipt_ref")


def test_missing_projection_stays_pending_and_abstain_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "outcome-runtime"
    monkeypatch.setenv("MOSAIC_OUTCOME_RUNTIME_DIR", str(runtime_root))
    authority = provision_test_outcome_source_authority(tmp_path, monkeypatch)
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        china_slot, china_opportunity, _ = _seed_pending(
            conn,
            revision=revision,
            tracks=tracks,
            agent_id="china",
        )
        eu_slot, eu_opportunity, eu_pending = _seed_pending(
            conn,
            revision=revision,
            tracks=tracks,
            agent_id="eu_economy",
        )
        _write_projection(
            runtime_root,
            conn,
            agent_id="eu_economy",
            track_hash=tracks["eu_economy"],
            slot=eu_slot,
            opportunity=eu_opportunity,
            pending=eu_pending,
            authority=authority,
            status="ABSTAIN",
        )

        batch = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_trading_dates(),
        )

        assert batch["unresolved_count"] == 1
        assert batch["abstained_count"] == 1
        assert conn.execute(
            "SELECT disposition FROM agent_outcome_eligibility_revisions_v2 "
            "WHERE scheduled_sample_id = ? ORDER BY audit_sequence DESC LIMIT 1",
            (china_slot["scheduled_sample_id"],),
        ).fetchone()[0] == "PENDING"
        assert conn.execute(
            "SELECT disposition FROM agent_outcome_eligibility_revisions_v2 "
            "WHERE scheduled_sample_id = ? ORDER BY audit_sequence DESC LIMIT 1",
            (eu_slot["scheduled_sample_id"],),
        ).fetchone()[0] == "EXOGENOUS_EXCLUSION"
        assert conn.execute(
            "SELECT COUNT(*) FROM agent_outcome_labels_v2"
        ).fetchone()[0] == 0
        assert china_opportunity["agent_id"] == "china"

    with pytest.raises(ValueError, match="unresolved due outcome projections"):
        store.publish_darwinian_v2_weight_updates(
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_long_trading_dates(),
        )


def test_due_schedule_crash_gaps_block_weight_publication(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        dates = _trading_dates()
        china_horizon = OUTCOME_CONTRACTS["china"]["maturity"][
            "horizon_trading_days"
        ]
        china_as_of = (
            f"{dates[dates.index(CUTOFF_AT[:10]) - china_horizon]}"
            "T15:00:00+08:00"
        )
        _, china_slot = _insert_schedule_slot(
            conn,
            revision=revision,
            track_hash=tracks["china"],
            agent_id="china",
            as_of_at=china_as_of,
        )
        freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=tracks["china"],
            scheduled_sample_id=china_slot["scheduled_sample_id"],
            sample_origin="PRODUCTION_ACTIVE",
            as_of=china_as_of,
            member_refs=_member_refs("china"),
            required_source_evidence_ids=["opportunity-evidence:china"],
            qualification_predicate_version=(
                expected_qualification_predicate_version("china")
            ),
            runtime_authority_binding=_runtime_authority_binding("china"),
        )

        us_horizon = OUTCOME_CONTRACTS["us_economy"]["maturity"][
            "horizon_trading_days"
        ]
        us_as_of = (
            f"{dates[dates.index(CUTOFF_AT[:10]) - us_horizon]}"
            "T15:00:00+08:00"
        )
        _insert_schedule_slot(
            conn,
            revision=revision,
            track_hash=tracks["us_economy"],
            agent_id="us_economy",
            as_of_at=us_as_of,
        )

        batch = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=dates,
        )

    assert batch["due_pending_count"] == 2
    assert batch["unresolved_count"] == 2
    assert {
        (row["agent_id"], row["maturation_status"], row["failure_code"])
        for row in batch["results"]
    } == {
        (
            "china",
            "PENDING_ELIGIBILITY_AUDIT_MISSING",
            "REQUIRED_ELIGIBILITY_AUDIT_UNAVAILABLE",
        ),
        (
            "us_economy",
            "PENDING_PREPARATION_UNAVAILABLE",
            "REQUIRED_OUTCOME_PREPARATION_UNAVAILABLE",
        ),
    }
    with pytest.raises(ValueError, match="unresolved due outcome projections"):
        store.publish_darwinian_v2_weight_updates(
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_long_trading_dates(),
        )


@pytest.mark.parametrize(
    ("disposition", "accepted", "reason"),
    [
        ("SCORE", True, None),
        ("EXOGENOUS_EXCLUSION", True, "FORGED_EXCLUSION"),
        ("AGENT_FAILURE", False, "MODEL_FAILURE"),
    ],
)
def test_naked_terminal_eligibility_cannot_close_a_due_slot(
    tmp_path: Path,
    disposition: str,
    accepted: bool,
    reason: str | None,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        slot, opportunity, pending = _seed_pending(
            conn,
            revision=revision,
            tracks=tracks,
            agent_id="china",
        )
        append_outcome_eligibility_revision(
            conn,
            track_key_hash=tracks["china"],
            scheduled_sample_id=slot["scheduled_sample_id"],
            sample_origin="PRODUCTION_ACTIVE",
            disposition=disposition,
            recorded_at=CUTOFF_AT,
            evaluation_opportunity_set_id=opportunity[
                "evaluation_opportunity_set_id"
            ],
            accepted_output_id=(pending["accepted_output_id"] if accepted else None),
            exclusion_or_failure_reason=reason,
        )

        batch = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_trading_dates(),
        )

    assert batch["unresolved_count"] == 1
    assert batch["results"] == [
        {
            "agent_id": "china",
            "scheduled_sample_id": slot["scheduled_sample_id"],
            "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
            "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
            "outcome_due_at": CUTOFF_AT,
            "maturation_status": "PENDING_TERMINAL_COMPANION_UNAVAILABLE",
            "failure_code": "REQUIRED_TERMINAL_OUTCOME_COMPANION_UNAVAILABLE",
        }
    ]


def test_empty_opportunity_without_stage_skip_cannot_close_a_due_slot(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        as_of_at = _as_of_for_due_agent("druckenmiller")
        _, slot = _insert_schedule_slot(
            conn,
            revision=revision,
            track_hash=tracks["druckenmiller"],
            agent_id="druckenmiller",
            as_of_at=as_of_at,
        )
        opportunity = freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=tracks["druckenmiller"],
            scheduled_sample_id=slot["scheduled_sample_id"],
            sample_origin="PRODUCTION_ACTIVE",
            as_of=as_of_at,
            member_refs=[],
            required_source_evidence_ids=["opportunity-evidence:druckenmiller"],
            qualification_predicate_version=(
                expected_qualification_predicate_version("druckenmiller")
            ),
        )
        append_outcome_eligibility_revision(
            conn,
            track_key_hash=tracks["druckenmiller"],
            scheduled_sample_id=slot["scheduled_sample_id"],
            sample_origin="PRODUCTION_ACTIVE",
            disposition="EXOGENOUS_EXCLUSION",
            recorded_at=as_of_at,
            evaluation_opportunity_set_id=opportunity[
                "evaluation_opportunity_set_id"
            ],
            exclusion_or_failure_reason="NO_EVALUATION_OBJECT",
        )

        batch = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_trading_dates(),
        )

    assert batch["unresolved_count"] == 1
    assert batch["results"][0]["maturation_status"] == (
        "PENDING_TERMINAL_COMPANION_UNAVAILABLE"
    )


def test_registered_generation_failure_and_stage_skip_close_due_slots(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        china_plan, _ = _insert_schedule_slot(
            conn,
            revision=revision,
            track_hash=tracks["china"],
            agent_id="china",
            as_of_at=_as_of_for_due_agent("china"),
        )
        druckenmiller_plan, _ = _insert_schedule_slot(
            conn,
            revision=revision,
            track_hash=tracks["druckenmiller"],
            agent_id="druckenmiller",
            as_of_at=_as_of_for_due_agent("druckenmiller"),
        )

    store.record_scheduled_outcome_opportunity_failure(
        outcome_schedule_plan_id=china_plan["outcome_schedule_plan_id"],
        agent_id="china",
        qualification_predicate_version=expected_qualification_predicate_version(
            "china"
        ),
        source_evidence_by_required_source_id=_required_source_evidence("china"),
        error_codes=["REQUIRED_DATA_UNAVAILABLE"],
        attempted_at=china_plan["as_of"],
    )
    store.freeze_scheduled_outcome_opportunity(
        outcome_schedule_plan_id=druckenmiller_plan["outcome_schedule_plan_id"],
        agent_id="druckenmiller",
        qualification_predicate_version=expected_qualification_predicate_version(
            "druckenmiller"
        ),
        member_refs=[],
        source_evidence_by_required_source_id=_required_source_evidence(
            "druckenmiller"
        ),
        projection_snapshot_hash=canonical_hash(
            {"agent_id": "druckenmiller", "as_of": druckenmiller_plan["as_of"]}
        ),
    )
    store.create_no_evaluation_object_stage_skip(
        outcome_schedule_plan_id=druckenmiller_plan["outcome_schedule_plan_id"],
        agent_id="druckenmiller",
        recorded_at=druckenmiller_plan["as_of"],
    )

    with store._connect() as conn:
        batch = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_trading_dates(),
        )

    assert batch["due_pending_count"] == 0
    assert batch["unresolved_count"] == 0
    assert batch["results"] == []


def test_generation_failure_without_eligibility_audit_remains_unresolved(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        plan, slot = _insert_schedule_slot(
            conn,
            revision=revision,
            track_hash=tracks["china"],
            agent_id="china",
            as_of_at=_as_of_for_due_agent("china"),
        )
        contract = OUTCOME_CONTRACTS["china"]
        without_hash = {
            "generation_attempt_id": "maturity-generation-attempt:china",
            "schema_version": "evaluation_opportunity_set_generation_failure_v2",
            "outcome_schedule_plan_id": plan["outcome_schedule_plan_id"],
            "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
            "scheduled_sample_id": slot["scheduled_sample_id"],
            "track_key_hash": tracks["china"],
            "agent_id": "china",
            "opportunity_set_contract_version": contract[
                "opportunity_set_contract_version"
            ],
            "generator_contract_version": "evaluation_opportunity_generator_v2",
            "qualification_predicate_version": (
                expected_qualification_predicate_version("china")
            ),
            "attempted_at": plan["as_of"],
            "required_source_ids": list(contract["required_source_ids"]),
            "source_evidence_ids": ["maturity-source:china:failure"],
            "error_codes": ["REQUIRED_DATA_UNAVAILABLE"],
        }
        failure = {
            **without_hash,
            "generation_attempt_hash": canonical_hash(without_hash),
        }
        conn.execute(
            "INSERT INTO evaluation_opportunity_set_generation_failures_v2 ("
            "generation_attempt_id, generation_attempt_hash, "
            "outcome_schedule_plan_id, outcome_schedule_slot_id, "
            "scheduled_sample_id, track_key_hash, agent_id, attempted_at, record_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                failure["generation_attempt_id"],
                failure["generation_attempt_hash"],
                plan["outcome_schedule_plan_id"],
                slot["outcome_schedule_slot_id"],
                slot["scheduled_sample_id"],
                tracks["china"],
                "china",
                plan["as_of"],
                json.dumps(failure),
            ),
        )

        batch = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_trading_dates(),
        )

    assert batch["unresolved_count"] == 1
    assert batch["results"][0]["maturation_status"] == (
        "PENDING_ELIGIBILITY_AUDIT_MISSING"
    )


def test_refresh_rpc_path_materializes_before_building_all_28_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "outcome-runtime"
    monkeypatch.setenv("MOSAIC_OUTCOME_RUNTIME_DIR", str(runtime_root))
    authority = provision_test_outcome_source_authority(tmp_path, monkeypatch)
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        slot, opportunity, pending = _seed_pending(
            conn,
            revision=revision,
            tracks=tracks,
            agent_id="china",
        )
        _write_projection(
            runtime_root,
            conn,
            agent_id="china",
            track_hash=tracks["china"],
            slot=slot,
            opportunity=opportunity,
            pending=pending,
            authority=authority,
        )

    handler_module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    monkeypatch.setattr(handler_module, "_store", lambda: store)
    monkeypatch.setattr(
        handler_module,
        "_verified_darwinian_trading_dates",
        lambda cutoff_at: _long_trading_dates(),
    )
    result = handler_module._run_v2_outcome_update(
        production_variant_roster_revision_id=revision[
            "production_variant_roster_revision_id"
        ],
        cutoff_at=CUTOFF_AT,
        operation="REFRESH",
    )

    assert result["outcome_maturation"]["scored_count"] == 1
    assert len(result["evaluation_windows"]) == 28


def test_registered_trading_day_maturity_and_slot_hash_fail_closed(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        _seed_pending(
            conn,
            revision=revision,
            tracks=tracks,
            agent_id="china",
            due_at="2026-07-16T15:00:00+08:00",
            as_of_at_override="2026-07-10T15:00:00+08:00",
        )
        with pytest.raises(ValueError, match="due_at drift"):
            materialize_due_outcomes(
                conn,
                production_variant_roster_revision_id=revision[
                    "production_variant_roster_revision_id"
                ],
                cutoff_at=CUTOFF_AT,
                trading_dates=_trading_dates(),
            )


def test_authoritative_slot_hash_drift_fails_closed(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        _seed_pending(
            conn,
            revision=revision,
            tracks=tracks,
            agent_id="china",
            forge_slot_hash=True,
        )
        with pytest.raises(ValueError, match="identity/hash/owner mismatch"):
            materialize_due_outcomes(
                conn,
                production_variant_roster_revision_id=revision[
                    "production_variant_roster_revision_id"
                ],
                cutoff_at=CUTOFF_AT,
                trading_dates=_trading_dates(),
            )


def test_authoritative_slot_lookup_requires_sample_track_and_agent(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        _seed_pending(
            conn,
            revision=revision,
            tracks=tracks,
            agent_id="china",
            stored_slot_agent_id="us_economy",
        )
        with pytest.raises(ValueError, match="exactly one authoritative"):
            materialize_due_outcomes(
                conn,
                production_variant_roster_revision_id=revision[
                    "production_variant_roster_revision_id"
                ],
                cutoff_at=CUTOFF_AT,
                trading_dates=_trading_dates(),
            )

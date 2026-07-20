from __future__ import annotations

import copy
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

import pytest

from mosaic.dataflows.outcome_runtime_inputs import (
    expected_qualification_predicate_version,
)
from mosaic.scorecard.darwinian_v2 import (
    _authoritative_macro_input_gate,
    _validate_macro_attribution_authority,
    canonical_hash,
    deterministic_id,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.store import ScorecardStore


def _opportunity_member(agent_id: str) -> dict[str, Any]:
    contract = OUTCOME_CONTRACTS[agent_id]
    object_type = contract["evaluation_object_type"]
    if object_type == "MACRO_TRANSMISSION":
        field = (
            "event_id"
            if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
            else "path_snapshot_id"
        )
        return {field: f"member:{agent_id}"}
    if object_type == "SECTOR_TILT_PICKS":
        shortlist_id = f"shortlist:{agent_id}"
        return {
            "subindustry_id": f"member:{agent_id}",
            "security_shortlist_id": shortlist_id,
            "security_shortlist_hash": canonical_hash(
                {"security_shortlist_id": shortlist_id, "security_ts_codes": []}
            ),
            "security_ts_codes": [],
        }
    if object_type == "SUPERINVESTOR_PICKS":
        return {"candidate_ref": f"member:{agent_id}", "ts_code": "600003.SH"}
    if object_type == "RELATIONSHIP_EDGES":
        return {"edge_candidate_id": f"member:{agent_id}", "materiality_weight": 1.0}
    if object_type == "CRO_FROZEN_RISK_ACTIONS":
        return {
            "risk_candidate_id": f"member:{agent_id}",
            "ts_code": "600004.SH",
            "proposed_target_weight": 0.1,
        }
    if object_type == "ALPHA_FROZEN_NOVEL_PICKS":
        return {
            "candidate_ref": f"member:{agent_id}",
            "ts_code": "600005.SH",
        }
    if object_type == "EXECUTION_FROZEN_ORDER_INTENT":
        return {
            "order_intent_id": f"member:{agent_id}",
            "ts_code": "600006.SH",
            "action": "BUY",
            "requested_delta_weight": 0.1,
        }
    if object_type == "CIO_FROZEN_FINAL_PORTFOLIO":
        return {
            "controlled_target_set_id": f"member:{agent_id}",
            "baseline_cash_weight": 0.3,
            "positions": [
                {
                    "position_ref": "position:600007.SH",
                    "ts_code": "600007.SH",
                    "baseline_weight": 0.7,
                    "controlled_target_weight": 0.8,
                }
            ],
        }
    raise AssertionError(f"unsupported evaluation object type: {object_type}")


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


def _bindings() -> dict[str, dict[str, str | None]]:
    result = {}
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


def _component_runtime_input(agent_id: str) -> dict:
    composition = OUTCOME_CONTRACTS[agent_id]["component_composition_contract"]
    return {
        "agent_id": agent_id,
        "component_weight_contract_version": composition[
            "component_weight_contract_version"
        ],
        "components": [
            {
                "component": component,
                "direction": "SUPPORTIVE",
                "strength": 3,
                "persistence_horizon": "WEEKS",
                "evaluation_horizon_trading_days": 5,
                "confidence": 0.8,
                "channels": [f"channel:{component}"],
                "claim_refs": [f"claim-{agent_id}-MACRO_TRANSMISSION"],
                "deterministic_data_quality": 0.9,
            }
            for component in sorted(composition["components"])
        ],
    }


def _state() -> dict:
    cohort = "cohort_default"
    language = "zh"
    bindings = _bindings()
    roster_id = deterministic_id(
        "production-variant-roster",
        {"cohort_id": cohort, "language": language},
    )
    binding_without_hash = {
        "schema_version": "darwinian_runtime_binding_v2",
        "production_variant_roster_id": roster_id,
        "cohort_id": cohort,
        "language": language,
        "execution_behavior_release_id": "release-1",
        "prompt_repo_id": "private-prompts",
        "prompt_repo_revision": "a" * 40,
        "effective_at": "2026-07-17T09:00:00+08:00",
        "agent_behavior_bindings": bindings,
    }
    audits = []
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        if agent_id == "cio":
            stages = ("cio_proposal", "cio_final")
        elif contract["layer"] == "SECTOR" and agent_id != "relationship_mapper":
            stages = ("final_selection",)
        elif agent_id == "alpha_discovery":
            stages = ("alpha_discovery",)
        elif agent_id == "cro":
            stages = ("cro_review",)
        elif agent_id == "autonomous_execution":
            stages = ("execution_feasibility",)
        else:
            stages = ("agent_run",)
        for stage in stages:
            audits.append(
                {
                    "agent": agent_id,
                    "stage": stage,
                    "status": "accepted",
                    "run_id": "graph-run-1",
                    "output_hash": canonical_hash(
                        {"agent": agent_id, "stage": stage, "output": "fixture"}
                    ),
                }
            )
    return {
        "active_cohort": cohort,
        "as_of_date": "2026-07-17",
        "trace_id": "graph-run-1",
        "darwinian_runtime_binding": {
            **binding_without_hash,
            "binding_hash": canonical_hash(binding_without_hash),
        },
        "agent_run_audits": audits,
        "outcome_stage_skips": {},
        "outcome_opportunity_bindings": {},
        "component_calibration_inputs": {
            agent_id: _component_runtime_input(agent_id)
            for agent_id, contract in OUTCOME_CONTRACTS.items()
            if contract["component_composition_contract"] is not None
        },
    }


def _accepted_stage(agent_id: str, accepted_kind: str) -> str:
    if accepted_kind == "CIO_PROPOSAL":
        return "cio_proposal"
    if accepted_kind == "CIO_FINAL":
        return "cio_final"
    if agent_id == "alpha_discovery":
        return "alpha_discovery"
    if agent_id == "cro":
        return "cro_review"
    if agent_id == "autonomous_execution":
        return "execution_feasibility"
    contract = OUTCOME_CONTRACTS[agent_id]
    if contract["layer"] == "SECTOR" and agent_id != "relationship_mapper":
        return "final_selection"
    return "agent_run"


def _research_claim(agent_id: str, accepted_kind: str) -> dict:
    claim_id = f"claim-{agent_id}-{accepted_kind}"
    return {
        "claim_id": claim_id,
        "claim_kind": "FACT",
        "statement": f"Fixture claim for {agent_id}.",
        "structured_conclusion": {"direction": "supportive"},
        "evidence_ids": [f"evidence:{agent_id}:{accepted_kind}"],
        "research_rule_refs": [],
    }


def _accepted_macro_attributions(summary_body: Mapping[str, Any]) -> list[dict[str, Any]]:
    macro_agents = (
        "china",
        "us_economy",
        "eu_economy",
        "central_bank",
        "us_financial_conditions",
        "euro_area_financial_conditions",
        "commodities",
        "geopolitical",
        "market_breadth",
        "institutional_flow",
    )
    rows: list[dict[str, Any]] = []
    target_hash = canonical_hash(summary_body)
    for macro_agent in macro_agents:
        rows.append(
            {
                "agent_id": macro_agent,
                "usage_share": 0.1,
                "target_type": "SUBMISSION_SUMMARY",
                "target_ref": f"accepted-target:submission:{target_hash[7:]}",
                "target_hash": target_hash,
                "claim_refs_used": [],
                "effect": "NOT_MATERIAL",
            }
        )
    return rows


def _persistent_id(namespace: str, value: Any) -> str:
    return f"{namespace}:{canonical_hash(value)[7:]}"


def _raw_execution_assessment(claim_refs: list[str]) -> dict[str, Any]:
    return {
        "assessment_local_id": "assessment:fixture",
        "order_intent_ref": "order-intent:fixture",
        "ts_code": "600006.SH",
        "requested_delta_weight": 0.1,
        "feasibility": "BLOCKED",
        "feasibility_confidence": 0.8,
        "predicted_cost_bps": 12.0,
        "max_executable_delta_weight": 0.0,
        "recommended_slice_count": 0,
        "reason": "Fixture execution block.",
        "claim_refs": claim_refs,
    }


def _accepted_execution_assessment(
    claim_refs: list[str], *, accepted_execution_id: str
) -> dict[str, Any]:
    raw = _raw_execution_assessment(claim_refs)
    assessment_hash = canonical_hash(
        {
            "accepted_execution_assessment_id": accepted_execution_id,
            "assessment_local_id": raw["assessment_local_id"],
            "assessment": raw,
        }
    )
    return {
        **raw,
        "execution_assessment_ref": f"execution-assessment:{assessment_hash[7:]}",
        "execution_assessment_hash": assessment_hash,
    }


def _decision_source(state: dict, owner: str) -> dict:
    skip = state["outcome_stage_skips"].get(owner)
    if skip:
        return {
            "source_status": "NO_EVALUATION_OBJECT",
            "agent_id": owner,
            "accepted_output_id": None,
            "accepted_output_hash": None,
            "stage_skip_id": skip["stage_skip_id"],
            "stage_skip_hash": skip["stage_skip_hash"],
        }
    kind = {
        "alpha_discovery": "ALPHA_DISCOVERY",
        "cro": "CRO_RISK_REVIEW",
        "autonomous_execution": "EXECUTION_ASSESSMENT",
    }[owner]
    ref = state.get("accepted_output_refs", {}).get(f"{kind}:{owner}")
    if ref is None:
        raise AssertionError(f"fixture Decision source is unavailable: {owner}")
    return {
        "source_status": "ACCEPTED_OUTPUT",
        "agent_id": owner,
        "accepted_output_id": ref["accepted_output_id"],
        "accepted_output_hash": ref["accepted_output_hash"],
        "stage_skip_id": None,
        "stage_skip_hash": None,
    }


def _accepted_payload_from_state(
    state: dict, *, agent_id: str, accepted_kind: str
) -> dict[str, Any]:
    for record in state.get("accepted_output_records", []):
        if (
            record["agent_id"] == agent_id
            and record["accepted_output_kind"] == accepted_kind
        ):
            return record["output"]["payload"]
    raise AssertionError(
        f"fixture accepted payload is unavailable: {agent_id}:{accepted_kind}"
    )


def _accepted_payload_fixture(
    state: dict,
    *,
    agent_id: str,
    accepted_kind: str,
    opportunity: dict | None,
) -> dict:
    behavior = state["darwinian_runtime_binding"]["agent_behavior_bindings"][agent_id]
    claim = _research_claim(agent_id, accepted_kind)
    claim_refs = [claim["claim_id"]]
    versions = {
        "agent_contract_version": behavior["agent_contract_version"],
        "prompt_behavior_version": behavior["prompt_behavior_version"],
        "execution_behavior_version": behavior["execution_behavior_version"],
    }
    if accepted_kind == "MACRO_TRANSMISSION":
        runtime_input = state["component_calibration_inputs"].get(agent_id)
        return {
            "agent_id": agent_id,
            **versions,
            "component_weight_contract_version": behavior[
                "component_weight_contract_version"
            ],
            "direction": "SUPPORTIVE",
            "strength": 3,
            "persistence_horizon": "WEEKS",
            "evaluation_horizon_trading_days": 5,
            "model_confidence": 0.8,
            "deterministic_data_quality": 0.9,
            "confidence": 0.72,
            "channels": (
                sorted(
                    {
                        channel
                        for component in runtime_input["components"]
                        for channel in component["channels"]
                    }
                )
                if runtime_input is not None
                else ["fixture-channel"]
            ),
            "claims": [claim],
            "claim_refs": claim_refs,
            "key_drivers": ["fixture"],
        }
    if accepted_kind == "STANDARD_SECTOR_SELECTION":
        selection = {
            "selection_status": "SELECTED",
            "preferred_direction": {
                "selection_role": "PREFERRED",
                "direction_local_id": "direction:preferred",
                "direction_id": "preferred",
                "allocation_action": "OVERWEIGHT",
                "strength": 3,
                "thesis": "Fixture preferred direction.",
                "claim_refs": claim_refs,
            },
            "least_preferred_direction": {
                "selection_role": "LEAST_PREFERRED",
                "direction_local_id": "direction:least",
                "direction_id": "least",
                "allocation_action": "UNDERWEIGHT",
                "strength": 2,
                "thesis": "Fixture least-preferred direction.",
                "claim_refs": claim_refs,
            },
            "persistence_horizon": "WEEKS",
            "key_drivers": [
                {
                    "driver_local_id": "driver:sector",
                    "summary": "Fixture sector driver.",
                    "claim_refs": claim_refs,
                }
            ],
            "risks": [
                {
                    "risk_local_id": "risk:sector",
                    "summary": "Fixture sector risk.",
                    "claim_refs": claim_refs,
                }
            ],
            "claims": [claim],
            "claim_refs": claim_refs,
            "preferred_security_status": "NO_QUALIFIED_SECURITY",
            "long_picks": [],
            "least_preferred_security_status": "NO_QUALIFIED_SECURITY",
            "short_or_avoid_picks": [],
        }
        return {
            "sector_agent_id": agent_id,
            **versions,
            "sector_direction_registry_version": "sector_direction_registry_v1",
            "sector_direction_registry_hash": canonical_hash("direction-registry"),
            "selection": selection,
            "accepted_macro_input_attributions": _accepted_macro_attributions(selection),
            "direction_comparison_audit_id": "direction-comparison:fixture",
            "direction_comparison_audit_hash": canonical_hash("direction-comparison"),
            "preferred_security_shortlist_id": "shortlist:preferred",
            "preferred_security_shortlist_hash": canonical_hash("shortlist:preferred"),
            "least_preferred_security_shortlist_id": "shortlist:least",
            "least_preferred_security_shortlist_hash": canonical_hash("shortlist:least"),
            "security_scoring_contract_version": "security-scoring-v1",
            "security_scoring_contract_hash": canonical_hash("security-scoring"),
            "inference_cost_audit_id": "inference-cost:fixture",
            "inference_cost_audit_hash": canonical_hash("inference-cost"),
            "preferred_security_abstention_confidence": 0.8,
            "least_preferred_security_abstention_confidence": 0.8,
            "model_confidence": 0.8,
            "directional_confidence": 0.8,
        }
    if accepted_kind == "RELATIONSHIP_GRAPH":
        relationship = {
            "relationship_agent_id": "relationship_mapper",
            **versions,
            "relationship_snapshot_hash": canonical_hash("relationship-snapshot"),
            "frozen_holder_domain_hash": canonical_hash("holder-domain"),
            "frozen_security_domain_hash": canonical_hash("security-domain"),
            "opportunity_set_id": "relationship-opportunity:fixture",
            "opportunity_set_hash": canonical_hash("relationship-opportunity"),
            "factual_edges": [],
            "predictive_edges": [],
            "predictive_graph_status": "NO_QUALIFIED_PREDICTIVE_EDGE",
            "predictive_graph_abstention_confidence": 0.8,
            "key_drivers": [
                {
                    "driver_local_id": "driver:relationship",
                    "summary": "Fixture relationship driver.",
                    "claim_refs": claim_refs,
                }
            ],
            "risks": [
                {
                    "risk_local_id": "risk:relationship",
                    "summary": "Fixture relationship risk.",
                    "claim_refs": claim_refs,
                }
            ],
            "claims": [claim],
            "claim_refs": claim_refs,
            "directional_confidence": 0.0,
        }
        return {
            **relationship,
            "accepted_macro_input_attributions": _accepted_macro_attributions(relationship),
        }
    if accepted_kind == "SUPERINVESTOR_SELECTION":
        selection = {
            "selection_status": "NO_QUALIFIED_CANDIDATES",
            "holding_period": "MONTHS",
            "picks": [],
            "key_drivers": [
                {
                    "driver_local_id": "driver:superinvestor",
                    "summary": "Fixture Superinvestor driver.",
                    "claim_refs": claim_refs,
                }
            ],
            "risks": [
                {
                    "risk_local_id": "risk:superinvestor",
                    "summary": "Fixture Superinvestor risk.",
                    "claim_refs": claim_refs,
                }
            ],
            "claims": [claim],
            "claim_refs": claim_refs,
        }
        return {
            "superinvestor_agent_id": agent_id,
            **versions,
            "selection": selection,
            "accepted_macro_input_attributions": _accepted_macro_attributions(selection),
            "model_confidence": 0.8,
            "directional_confidence": 0.0,
            "abstention_confidence": 0.8,
        }
    frozen_id = opportunity["frozen_object_set_id"] if opportunity else "frozen:fixture"
    frozen_hash = (
        opportunity["frozen_object_set_hash"]
        if opportunity
        else canonical_hash("frozen:fixture")
    )
    if accepted_kind == "ALPHA_DISCOVERY":
        selection = {
            "discovery_disposition": "NONE_FOUND",
            "novel_picks": [],
            "key_drivers": [],
            "risks": [],
            "claims": [claim],
            "claim_refs": claim_refs,
        }
        without_identity = {
            "agent_id": "alpha_discovery",
            **versions,
            "frozen_novel_candidate_universe_id": frozen_id,
            "frozen_novel_candidate_universe_hash": frozen_hash,
            "selection": selection,
            "accepted_macro_input_attributions": _accepted_macro_attributions(selection),
            "model_confidence": 0.8,
        }
        accepted_id = _persistent_id("accepted-alpha-discovery", without_identity)
        hash_body = {
            **without_identity,
            "accepted_alpha_discovery_id": accepted_id,
        }
        return {
            **hash_body,
            "accepted_alpha_discovery_hash": canonical_hash(hash_body),
        }
    if accepted_kind == "CIO_PROPOSAL":
        decision = {
            "decision_disposition": "ALL_CASH",
            "target_positions": [],
            "cash_weight": 1.0,
            "decision_reason": "Fixture all-cash decision.",
            "claims": [claim],
            "claim_refs": claim_refs,
        }
        without_identity = {
            "agent_id": "cio",
            "decision_stage": "PROPOSAL",
            **versions,
            "frozen_pre_cio_input_id": "pre-cio:fixture",
            "frozen_pre_cio_input_hash": canonical_hash("pre-cio:fixture"),
            "alpha_source": _decision_source(state, "alpha_discovery"),
            "alpha_pick_resolutions": [],
            "decision": decision,
            "accepted_macro_input_attributions": _accepted_macro_attributions(decision),
            "model_confidence": 0.8,
        }
        proposal_id = _persistent_id("cio-proposal", without_identity)
        hash_body = {**without_identity, "proposal_id": proposal_id}
        return {**hash_body, "proposal_hash": canonical_hash(hash_body)}
    proposal = _accepted_payload_from_state(
        state,
        agent_id="cio",
        accepted_kind="CIO_PROPOSAL",
    )
    proposal_id = proposal["proposal_id"]
    proposal_hash = proposal["proposal_hash"]
    if accepted_kind == "CRO_RISK_REVIEW":
        review = {
            "review_disposition": "NO_OBJECTION",
            "candidate_actions": [],
            "correlated_risks": [],
            "black_swan_scenarios": [],
            "claims": [claim],
            "claim_refs": claim_refs,
        }
        attributions = _accepted_macro_attributions(review)
        accepted_id = _persistent_id(
            "accepted-cro-review",
            {
                "agent_id": "cro",
                "frozen_proposal_id": proposal_id,
                "frozen_proposal_hash": proposal_hash,
                "frozen_candidate_universe_id": frozen_id,
                "frozen_candidate_universe_hash": frozen_hash,
                "review": review,
                "accepted_macro_input_attributions": attributions,
            },
        )
        without_hash = {
            "agent_id": "cro",
            **versions,
            "accepted_cro_review_id": accepted_id,
            "frozen_proposal_id": proposal_id,
            "frozen_proposal_hash": proposal_hash,
            "frozen_candidate_universe_id": frozen_id,
            "frozen_candidate_universe_hash": frozen_hash,
            "review": review,
            "accepted_macro_input_attributions": attributions,
            "model_confidence": 0.8,
        }
        return {
            **without_hash,
            "accepted_cro_review_hash": canonical_hash(without_hash),
        }
    if accepted_kind == "EXECUTION_ASSESSMENT":
        raw_assessment = _raw_execution_assessment(claim_refs)
        raw_payload = {
            "execution_disposition": "BLOCKED",
            "order_assessments": [raw_assessment],
            "claims": [claim],
            "claim_refs": claim_refs,
        }
        cro_source = _decision_source(state, "cro")
        accepted_execution_id = _persistent_id(
            "accepted-execution-assessment",
            {
                "agent_id": "autonomous_execution",
                "frozen_proposal_id": proposal_id,
                "frozen_proposal_hash": proposal_hash,
                "cro_control_source": cro_source,
                "frozen_order_intent_set_id": frozen_id,
                "frozen_order_intent_set_hash": frozen_hash,
                "assessment": raw_payload,
            },
        )
        assessment = {
            **raw_payload,
            "order_assessments": [
                _accepted_execution_assessment(
                    claim_refs,
                    accepted_execution_id=accepted_execution_id,
                )
            ],
        }
        without_hash = {
            "agent_id": "autonomous_execution",
            **versions,
            "accepted_execution_assessment_id": accepted_execution_id,
            "execution_mode": "PAPER",
            "frozen_proposal_id": proposal_id,
            "frozen_proposal_hash": proposal_hash,
            "cro_control_source": cro_source,
            "frozen_order_intent_set_id": frozen_id,
            "frozen_order_intent_set_hash": frozen_hash,
            "assessment": assessment,
            "model_confidence": 0.8,
        }
        return {
            **without_hash,
            "accepted_execution_assessment_hash": canonical_hash(without_hash),
        }
    if accepted_kind == "CIO_FINAL":
        decision = {
            "decision_disposition": "ALL_CASH",
            "target_positions": [],
            "cash_weight": 1.0,
            "decision_reason": "Fixture all-cash decision.",
            "claims": [claim],
            "claim_refs": claim_refs,
        }
        execution_payload = (
            None
            if state["outcome_stage_skips"].get("autonomous_execution")
            else _accepted_payload_from_state(
                state,
                agent_id="autonomous_execution",
                accepted_kind="EXECUTION_ASSESSMENT",
            )
        )
        execution_assessment = (
            execution_payload["assessment"]["order_assessments"][0]
            if execution_payload is not None
            else None
        )
        execution_resolutions = (
            []
            if execution_assessment is None
            else [
                {
                    "execution_assessment_ref": execution_assessment[
                        "execution_assessment_ref"
                    ],
                    "execution_assessment_hash": execution_assessment[
                        "execution_assessment_hash"
                    ],
                    "resolution": "COMPLIED",
                    "reason": "Fixture execution control is respected.",
                    "claim_refs": claim_refs,
                }
            ]
        )
        without_identity = {
            "agent_id": "cio",
            "decision_stage": "FINAL",
            **versions,
            "frozen_proposal_id": proposal_id,
            "frozen_proposal_hash": proposal_hash,
            "cro_control_source": _decision_source(state, "cro"),
            "execution_control_source": _decision_source(
                state, "autonomous_execution"
            ),
            "frozen_controlled_target_set_id": frozen_id,
            "frozen_controlled_target_set_hash": frozen_hash,
            "decision": decision,
            "cro_control_resolutions": [],
            "execution_control_resolutions": execution_resolutions,
            "accepted_macro_input_attributions": _accepted_macro_attributions(decision),
            "model_confidence": 0.8,
        }
        final_id = _persistent_id("cio-final-portfolio", without_identity)
        hash_body = {**without_identity, "final_portfolio_id": final_id}
        return {
            **hash_body,
            "final_portfolio_hash": canonical_hash(hash_body),
        }
    raise AssertionError(f"unsupported accepted kind: {accepted_kind}")


def _attach_accepted_records(state: dict) -> None:
    plan = state["outcome_schedule_plan"]
    binding = state["darwinian_runtime_binding"]
    audits = state["agent_run_audits"]
    skipped = set(state["outcome_stage_skips"])
    records: list[dict] = []
    refs: dict[str, dict] = {}
    state["accepted_output_records"] = records
    state["accepted_output_refs"] = refs
    slot_by_agent = {slot["agent_id"]: slot for slot in plan["slots"]}
    decision_agents = {"alpha_discovery", "cro", "autonomous_execution", "cio"}
    work_groups = [
        (slot, (OUTCOME_CONTRACTS[slot["agent_id"]]["accepted_output_kind"],))
        for slot in plan["slots"]
        if slot["agent_id"] not in decision_agents
        and slot["agent_id"] not in skipped
    ]
    for agent_id, accepted_kind in (
        ("alpha_discovery", "ALPHA_DISCOVERY"),
        ("cio", "CIO_PROPOSAL"),
        ("cro", "CRO_RISK_REVIEW"),
        ("autonomous_execution", "EXECUTION_ASSESSMENT"),
        ("cio", "CIO_FINAL"),
    ):
        if agent_id not in skipped:
            work_groups.append((slot_by_agent[agent_id], (accepted_kind,)))
    for slot, accepted_kinds in work_groups:
        agent_id = slot["agent_id"]
        for accepted_kind in accepted_kinds:
            stage = _accepted_stage(agent_id, accepted_kind)
            audit = next(
                item
                for item in audits
                if item["agent"] == agent_id and item["stage"] == stage
            )
            accepted_output_id = deterministic_id(
                "accepted-output",
                {
                    "graph_run_id": plan["graph_run_id"],
                    "run_slot_id": slot["run_slot_id"],
                    "accepted_output_kind": accepted_kind,
                },
            )
            operational_id = deterministic_id(
                "operational-opportunity",
                {
                    "graph_run_id": plan["graph_run_id"],
                    "agent_id": agent_id,
                    "run_slot_id": slot["run_slot_id"],
                },
            )
            runtime_input = state["component_calibration_inputs"].get(agent_id)
            opportunity = state["outcome_opportunity_bindings"].get(agent_id)
            payload = _accepted_payload_fixture(
                state,
                agent_id=agent_id,
                accepted_kind=accepted_kind,
                opportunity=(
                    opportunity
                    if accepted_kind
                    == OUTCOME_CONTRACTS[agent_id]["accepted_output_kind"]
                    else None
                ),
            )
            runtime_audit = None
            if accepted_kind == "MACRO_TRANSMISSION" and runtime_input is not None:
                component_weights = dict(
                    sorted(
                        OUTCOME_CONTRACTS[agent_id][
                            "component_composition_contract"
                        ]["components"].items()
                    )
                )
                composition_body = {
                    "schema_version": "macro_component_composition_audit_v1",
                    "agent_id": agent_id,
                    "component_weight_contract_version": runtime_input[
                        "component_weight_contract_version"
                    ],
                    "component_weights": component_weights,
                    "components": copy.deepcopy(runtime_input["components"]),
                    "source_snapshot_hash": canonical_hash(
                        {"role": agent_id, "as_of": plan["as_of"]}
                    ),
                    "context_only_projection_hash": (
                        canonical_hash(
                            {
                                "role": agent_id,
                                "usage_mode": "CONTEXT_ONLY",
                            }
                        )
                        if agent_id
                        in {
                            "us_financial_conditions",
                            "euro_area_financial_conditions",
                        }
                        else None
                    ),
                    "composed_payload_hash": canonical_hash(payload),
                }
                runtime_audit = {
                    "macro_component_composition": {
                        **composition_body,
                        "component_composition_hash": canonical_hash(
                            composition_body
                        ),
                    }
                }
            snapshot_hash = canonical_hash(
                {"agent_id": agent_id, "accepted_output_kind": accepted_kind}
            )
            claim = _research_claim(agent_id, accepted_kind)
            claim_graph_body = {
                "schema_version": "accepted_claim_graph_lineage_v1",
                "run_id": plan["graph_run_id"],
                "snapshot_hash": snapshot_hash,
                "evidence": [
                    {
                        "evidence_id": claim["evidence_ids"][0],
                        "source_fingerprint": canonical_hash(agent_id),
                    }
                ],
                "claims": [
                    {
                        "claim_id": claim["claim_id"],
                        "evidence_ids": claim["evidence_ids"],
                    }
                ],
            }
            claim_graph_lineage = {
                **claim_graph_body,
                "claim_graph_lineage_hash": canonical_hash(claim_graph_body),
            }
            adapter_body = {
                "schema_version": "accepted_output_adapter_lineage_v1",
                "adapter_contract_version": "accepted_output_adapter_v1",
                "agent_id": agent_id,
                "accepted_output_kind": accepted_kind,
                "source_agent_output_hash": audit["output_hash"],
                "accepted_payload_hash": canonical_hash(payload),
                "claim_graph_lineage_hash": claim_graph_lineage[
                    "claim_graph_lineage_hash"
                ],
            }
            without_hash = {
                "accepted_output_id": accepted_output_id,
                "graph_run_id": plan["graph_run_id"],
                "run_id": audit["run_id"],
                "run_slot_id": slot["run_slot_id"],
                "operational_opportunity_audit_id": operational_id,
                "production_variant_roster_id": plan[
                    "production_variant_roster_id"
                ],
                "production_variant_roster_revision_id": plan[
                    "production_variant_roster_revision_id"
                ],
                "execution_behavior_release_id": plan[
                    "execution_behavior_release_id"
                ],
                "cohort_id": plan["cohort_id"],
                "language": plan["language"],
                "track_key_hash": slot["track_key_hash"],
                "agent_id": agent_id,
                "accepted_output_kind": accepted_kind,
                "sample_origin": "PRODUCTION_ACTIVE",
                "run_slot_kind": slot["run_slot_kind"],
                "scheduled_sample_id": slot["scheduled_sample_id"],
                **binding["agent_behavior_bindings"][agent_id],
                "as_of": plan["as_of"],
                "accepted_at": binding["effective_at"],
                "evaluation_opportunity_set_id": (
                    opportunity["evaluation_opportunity_set_id"]
                    if opportunity
                    and accepted_kind
                    == OUTCOME_CONTRACTS[agent_id]["accepted_output_kind"]
                    else None
                ),
                "evaluation_opportunity_set_hash": (
                    opportunity["evaluation_opportunity_set_hash"]
                    if opportunity
                    and accepted_kind
                    == OUTCOME_CONTRACTS[agent_id]["accepted_output_kind"]
                    else None
                ),
                "frozen_object_set_id": (
                    opportunity["frozen_object_set_id"]
                    if opportunity
                    and accepted_kind
                    == OUTCOME_CONTRACTS[agent_id]["accepted_output_kind"]
                    else None
                ),
                "frozen_object_set_hash": (
                    opportunity["frozen_object_set_hash"]
                    if opportunity
                    and accepted_kind
                    == OUTCOME_CONTRACTS[agent_id]["accepted_output_kind"]
                    else None
                ),
                "adapter_lineage": {
                    **adapter_body,
                    "adapter_lineage_hash": canonical_hash(adapter_body),
                },
                **(
                    {
                        "runtime_opportunity_authority": opportunity[
                            "runtime_authority_binding"
                        ]
                    }
                    if opportunity
                    and accepted_kind
                    == OUTCOME_CONTRACTS[agent_id]["accepted_output_kind"]
                    and opportunity.get("runtime_authority_binding") is not None
                    else {}
                ),
                "output": {
                    "payload": payload,
                    "evidence_bundle_ids": [
                        f"evidence-bundle:{plan['graph_run_id']}:{snapshot_hash[7:]}"
                    ],
                    "causal_dedupe_keys": [canonical_hash(agent_id)],
                    "claim_graph_lineage": claim_graph_lineage,
                },
                **({"runtime_audit": runtime_audit} if runtime_audit else {}),
            }
            record = {
                **without_hash,
                "accepted_output_hash": canonical_hash(without_hash),
            }
            ref_key = f"{accepted_kind}:{agent_id}"
            records.append(record)
            refs[ref_key] = {
                "accepted_output_kind": accepted_kind,
                "agent_id": agent_id,
                "accepted_output_id": accepted_output_id,
                "accepted_output_hash": record["accepted_output_hash"],
            }
    state["accepted_output_records"] = records
    state["accepted_output_refs"] = refs
    state["macro_input_gate"] = _authoritative_macro_input_gate(
        records,
        weight_snapshot=state["darwinian_weight_snapshot"],
    )[0]


def _reseal_record(state: dict, record: dict) -> None:
    payload = record["output"]["payload"]
    lineage = record["adapter_lineage"]
    lineage["accepted_payload_hash"] = canonical_hash(payload)
    lineage_body = {
        key: value for key, value in lineage.items() if key != "adapter_lineage_hash"
    }
    lineage["adapter_lineage_hash"] = canonical_hash(lineage_body)
    body = {key: value for key, value in record.items() if key != "accepted_output_hash"}
    record["accepted_output_hash"] = canonical_hash(body)
    state["accepted_output_refs"][
        f"{record['accepted_output_kind']}:{record['agent_id']}"
    ]["accepted_output_hash"] = record["accepted_output_hash"]


def _reseal_cio_final_record(state: dict, record: dict) -> None:
    payload = record["output"]["payload"]
    without_identity = {
        key: value
        for key, value in payload.items()
        if key not in {"final_portfolio_id", "final_portfolio_hash"}
    }
    final_id = _persistent_id("cio-final-portfolio", without_identity)
    hash_body = {**without_identity, "final_portfolio_id": final_id}
    payload.clear()
    payload.update(
        {
            **hash_body,
            "final_portfolio_hash": canonical_hash(hash_body),
        }
    )
    _reseal_record(state, record)


def _calendar_snapshot(as_of: str) -> dict:
    current = date(2010, 1, 4)
    end = date.fromisoformat(as_of[:10]) + timedelta(days=35)
    dates: list[str] = []
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current += timedelta(days=1)
    without_hash = {
        "schema_version": "verified_trading_calendar_snapshot_v1",
        "trading_calendar_id": "cn_a_share_trading_calendar_v1",
        "as_of": as_of,
        "pit_status": "VERIFIED",
        "source_evidence_ids": ["tushare:trade_cal:fixture"],
        "trading_dates": dates,
    }
    return {**without_hash, "snapshot_hash": canonical_hash(without_hash)}


def _event_coverage() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        schedule = contract["sample_schedule"]
        if schedule["kind"] != "EVENT_TRIGGERED":
            continue
        result[agent_id] = {
            "coverage_status": "COMPLETE",
            "coverage_evidence_ids": [f"event-coverage:{agent_id}"],
            "event_registry_version": schedule["event_registry_version"],
            "event_priority_version": schedule["event_priority_version"],
            "candidates": [],
        }
    return result


def _attach_schedule(
    store: ScorecardStore,
    state: dict,
    *,
    stage_skip_agent: str | None = None,
    force_event_agent: str | None = None,
) -> tuple[int, int]:
    binding = state["darwinian_runtime_binding"]
    as_of = f"{state['as_of_date']}T09:00:00+08:00"
    prepared = store.prepare_darwinian_v2_production_variant(
        binding=binding,
        as_of=as_of,
    )
    state["darwinian_weight_snapshot"] = prepared["weight_snapshot"]
    revision_id = prepared["roster_revision"][
        "production_variant_roster_revision_id"
    ]
    event_coverage = _event_coverage()
    if force_event_agent is not None:
        schedule = OUTCOME_CONTRACTS[force_event_agent]["sample_schedule"]
        event_coverage[force_event_agent]["candidates"] = [
            {
                "event_id": f"fixture-event:{force_event_agent}",
                "causal_dedupe_key": f"fixture-causal:{force_event_agent}",
                "event_registry_version": schedule["event_registry_version"],
                "event_priority_version": schedule["event_priority_version"],
                "priority_rank": 0,
                "published_at": as_of,
                "source_evidence_ids": [f"official:{force_event_agent}"],
                "pit_status": "VERIFIED",
            }
        ]
    plan = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id=state["trace_id"],
        as_of=as_of,
        prepared_at=as_of,
        trading_calendar_snapshot=_calendar_snapshot(as_of),
        verified_event_candidates=event_coverage,
    )
    scheduled = [
        slot for slot in plan["slots"] if slot["run_slot_kind"] == "OUTCOME_SCHEDULED"
    ]
    for slot in scheduled:
        agent_id = slot["agent_id"]
        source_evidence = {
            source_id: [f"evidence:{agent_id}:{index}"]
            for index, source_id in enumerate(
                OUTCOME_CONTRACTS[agent_id]["required_source_ids"]
            )
        }
        frozen_hash = (
            canonical_hash({"agent_id": agent_id, "as_of": as_of, "stage": "frozen"})
            if OUTCOME_CONTRACTS[agent_id]["layer"] == "DECISION"
            else None
        )
        frozen_id = f"fixture-frozen:{frozen_hash[7:]}" if frozen_hash else None
        frozen = store.freeze_scheduled_outcome_opportunity(
            outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
            agent_id=agent_id,
            qualification_predicate_version=expected_qualification_predicate_version(
                agent_id
            ),
            member_refs=(
                []
                if agent_id == stage_skip_agent
                else [_opportunity_member(agent_id)]
            ),
            source_evidence_by_required_source_id=source_evidence,
            projection_snapshot_hash=canonical_hash(
                {"projection_agent": agent_id, "as_of": as_of}
            ),
            frozen_object_set_id=frozen_id,
            frozen_object_set_hash=frozen_hash,
            runtime_authority_binding=_runtime_authority_binding(agent_id),
        )
        state["outcome_opportunity_bindings"][agent_id] = {
            "evaluation_opportunity_set_id": frozen[
                "evaluation_opportunity_set_id"
            ],
            "evaluation_opportunity_set_hash": frozen[
                "evaluation_opportunity_set_hash"
            ],
            "frozen_object_set_id": frozen_id,
            "frozen_object_set_hash": frozen_hash,
            **(
                {
                    "runtime_authority_binding": frozen[
                        "runtime_authority_binding"
                    ]
                }
                if frozen.get("runtime_authority_binding") is not None
                else {}
            ),
        }
        if agent_id == stage_skip_agent:
            skipped = store.create_no_evaluation_object_stage_skip(
                outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
                agent_id=agent_id,
                recorded_at=as_of,
            )
            state["outcome_stage_skips"][agent_id] = skipped["stage_skip"]
    state["outcome_schedule_plan"] = plan
    component_signal_count = sum(
        len(
            OUTCOME_CONTRACTS[slot["agent_id"]]["component_composition_contract"][
                "components"
            ]
        )
        for slot in scheduled
        if OUTCOME_CONTRACTS[slot["agent_id"]]["component_composition_contract"]
        is not None
    )
    return len(scheduled), component_signal_count


def test_accepted_cycle_writes_29_outputs_and_28_operational_audits(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "scorecard.db"
    store = ScorecardStore(db_path)
    state = _state()
    scheduled_count, component_signal_count = _attach_schedule(store, state)
    _attach_accepted_records(state)
    result = store.append_darwinian_v2_accepted_cycle(state)
    assert result["accepted_output_records"] == 29
    assert result["operational_opportunity_audits"] == 28
    assert result["evaluation_tracks_inserted"] == 0
    assert result["usage_tracks_inserted"] == 0
    assert result["cold_start_weights_inserted"] == 0
    assert result["outcome_eligibility_pending_revisions"] == scheduled_count
    assert result["component_calibration_signals"] == component_signal_count

    with sqlite3.connect(db_path) as conn:
        accepted = conn.execute(
            "SELECT agent_id, accepted_output_kind, operational_opportunity_audit_id, "
            "record_json FROM accepted_agent_outputs_v2"
        ).fetchall()
        operational = conn.execute(
            "SELECT agent_id, run_slot_kind, scheduled_sample_id "
            "FROM operational_opportunity_audits_v2"
        ).fetchall()
    assert len(accepted) == 29
    assert len(operational) == 28
    cio = [row for row in accepted if row[0] == "cio"]
    assert {row[1] for row in cio} == {"CIO_PROPOSAL", "CIO_FINAL"}
    assert len({row[2] for row in cio}) == 1
    for agent_id, _, _, record_json in accepted:
        envelope = json.loads(record_json)["output"]
        assert envelope["evidence_bundle_ids"]
        assert envelope["causal_dedupe_keys"] == [canonical_hash(agent_id)]
    assert {row[1] for row in operational} == {
        "DOWNSTREAM_ONLY",
        "OUTCOME_SCHEDULED",
    }
    assert sum(row[1] == "OUTCOME_SCHEDULED" for row in operational) == scheduled_count
    assert all(
        (row[1] == "OUTCOME_SCHEDULED") == (row[2] is not None)
        for row in operational
    )


def test_accepted_cycle_excludes_stage_skip_from_outputs_and_samples(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "scorecard.db"
    store = ScorecardStore(db_path)
    state = _state()
    scheduled_count, component_signal_count = _attach_schedule(
        store,
        state,
        stage_skip_agent="autonomous_execution",
    )
    state["agent_run_audits"] = [
        audit
        for audit in state["agent_run_audits"]
        if audit["agent"] != "autonomous_execution"
    ]
    _attach_accepted_records(state)

    result = store.append_darwinian_v2_accepted_cycle(state)
    assert result["accepted_output_records"] == 28
    assert result["operational_opportunity_audits"] == 27
    assert result["no_evaluation_object_stage_skips"] == 1
    assert result["outcome_eligibility_pending_revisions"] == scheduled_count - 1
    assert result["component_calibration_signals"] == component_signal_count
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM accepted_agent_outputs_v2 "
                "WHERE agent_id = 'autonomous_execution'"
            ).fetchone()[0]
            == 0
        )
        assert conn.execute(
            "SELECT disposition, accountable, production_reliability_eligible "
            "FROM operational_opportunity_audits_v2 "
            "WHERE agent_id = 'autonomous_execution'"
        ).fetchone() == ("EXOGENOUS_EXCLUSION", 0, 0)

    retry = store.append_darwinian_v2_accepted_cycle(state)
    assert retry["accepted_output_records"] == 0
    assert retry["operational_opportunity_audits"] == 0
    assert retry["evaluation_tracks_inserted"] == 0
    assert retry["cold_start_weights_inserted"] == 0
    assert retry["outcome_eligibility_pending_revisions"] == 0
    assert retry["component_calibration_signals"] == 0


def test_accepted_cycle_rejects_tampered_record_hash(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    state["accepted_output_records"][0]["accepted_output_hash"] = canonical_hash(
        "tampered"
    )
    first = state["accepted_output_records"][0]
    state["accepted_output_refs"][
        f"{first['accepted_output_kind']}:{first['agent_id']}"
    ]["accepted_output_hash"] = first["accepted_output_hash"]

    with pytest.raises(ValueError, match="accepted output hash mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_private_or_unknown_top_level_field(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = state["accepted_output_records"][0]
    record["private_prompt_blob"] = "must-not-cross-public-boundary"
    _reseal_record(state, record)

    with pytest.raises(ValueError, match=r"fields mismatch.*private_prompt_blob"):
        store.append_darwinian_v2_accepted_cycle(state)


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_accepted_cycle_rejects_payload_schema_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "MACRO_TRANSMISSION"
    )
    payload = record["output"]["payload"]
    if mutation == "extra":
        payload["caller_schema_extension"] = True
    else:
        payload.pop("key_drivers")
    _reseal_record(state, record)

    with pytest.raises(ValueError, match=r"Macro payload fields mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_fake_claim_evidence_id(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "MACRO_TRANSMISSION"
    )
    record["output"]["payload"]["claims"][0]["evidence_ids"] = [
        "evidence:forged"
    ]
    _reseal_record(state, record)

    with pytest.raises(ValueError, match="claim evidence mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_nested_payload_object_extension(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "STANDARD_SECTOR_SELECTION"
    )
    record["output"]["payload"]["selection"]["preferred_direction"][
        "caller_nested_extension"
    ] = True
    _reseal_record(state, record)

    with pytest.raises(ValueError, match=r"Sector direction fields mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_non_finite_nested_number(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "MACRO_TRANSMISSION"
    )
    record["output"]["payload"]["confidence"] = float("nan")

    with pytest.raises(ValueError, match=r"confidence must be in \[0, 1\]"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_unresolved_nested_claim_ref(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "STANDARD_SECTOR_SELECTION"
    )
    record["output"]["payload"]["selection"]["key_drivers"][0][
        "claim_refs"
    ] = ["claim:forged"]
    _reseal_record(state, record)

    with pytest.raises(ValueError, match=r"driver claim_refs has unresolved claim refs"):
        store.append_darwinian_v2_accepted_cycle(state)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("usage_share", 1.5, "attribution usage_share"),
        ("effect", "SUPPORTS", "effect/claim_refs_used contract mismatch"),
    ],
)
def test_accepted_cycle_rejects_invalid_macro_attribution_values(
    tmp_path: Path,
    field: str,
    value: Any,
    error: str,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "SUPERINVESTOR_SELECTION"
    )
    record["output"]["payload"]["accepted_macro_input_attributions"][0][field] = value
    _reseal_record(state, record)

    with pytest.raises(ValueError, match=error):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_well_formed_forged_attribution_target(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "SUPERINVESTOR_SELECTION"
    )
    row = record["output"]["payload"]["accepted_macro_input_attributions"][0]
    forged_hash = canonical_hash("forged-attribution-target")
    row["target_hash"] = forged_hash
    row["target_ref"] = f"accepted-target:submission:{forged_hash[7:]}"
    _reseal_record(state, record)

    with pytest.raises(ValueError, match="submission attribution target_hash mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_forged_macro_attribution_claim(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "SUPERINVESTOR_SELECTION"
    )
    row = record["output"]["payload"]["accepted_macro_input_attributions"][0]
    row["effect"] = "SUPPORTS"
    row["claim_refs_used"] = ["claim:forged"]
    _reseal_record(state, record)

    with pytest.raises(ValueError, match="uses unowned accepted Macro claims"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_cross_agent_macro_attribution_claim(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "SUPERINVESTOR_SELECTION"
    )
    us_record = next(
        row
        for row in state["accepted_output_records"]
        if row["agent_id"] == "us_economy"
        and row["accepted_output_kind"] == "MACRO_TRANSMISSION"
    )
    row = record["output"]["payload"]["accepted_macro_input_attributions"][0]
    row["effect"] = "SUPPORTS"
    row["claim_refs_used"] = [
        us_record["output"]["payload"]["claims"][0]["claim_id"]
    ]
    _reseal_record(state, record)

    with pytest.raises(ValueError, match="uses unowned accepted Macro claims"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_redistributed_macro_usage_shares(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "SUPERINVESTOR_SELECTION"
    )
    rows = record["output"]["payload"]["accepted_macro_input_attributions"]
    rows[0]["usage_share"] = 0.2
    rows[1]["usage_share"] = 0.0
    _reseal_record(state, record)

    with pytest.raises(
        ValueError,
        match="usage_share does not match the authoritative Macro gate",
    ):
        store.append_darwinian_v2_accepted_cycle(state)


def test_macro_attribution_authority_has_exact_required_kind_allowlist() -> None:
    required_kinds = {
        "STANDARD_SECTOR_SELECTION",
        "RELATIONSHIP_GRAPH",
        "SUPERINVESTOR_SELECTION",
        "ALPHA_DISCOVERY",
        "CRO_RISK_REVIEW",
        "CIO_PROPOSAL",
        "CIO_FINAL",
    }
    reliability = {
        agent_id: {"usage_share": 0.1} for agent_id in OUTCOME_CONTRACTS
        if OUTCOME_CONTRACTS[agent_id]["layer"] == "MACRO"
    }
    claim_ids_by_agent = {agent_id: set() for agent_id in reliability}
    attributions = [
        {
            "agent_id": agent_id,
            "usage_share": 0.1,
            "claim_refs_used": [],
        }
        for agent_id in reliability
    ]

    for accepted_kind in required_kinds:
        with pytest.raises(ValueError, match=rf"{accepted_kind} requires"):
            _validate_macro_attribution_authority(
                [
                    {
                        "accepted_output_kind": accepted_kind,
                        "output": {"payload": {}},
                    }
                ],
                macro_gate={"reliability_by_agent": reliability},
                claim_ids_by_agent=claim_ids_by_agent,
            )
        _validate_macro_attribution_authority(
            [
                {
                    "accepted_output_kind": accepted_kind,
                    "output": {
                        "payload": {
                            "accepted_macro_input_attributions": attributions,
                        }
                    },
                }
            ],
            macro_gate={"reliability_by_agent": reliability},
            claim_ids_by_agent=claim_ids_by_agent,
        )

    for accepted_kind in {"MACRO_TRANSMISSION", "EXECUTION_ASSESSMENT"}:
        _validate_macro_attribution_authority(
            [
                {
                    "accepted_output_kind": accepted_kind,
                    "output": {"payload": {}},
                }
            ],
            macro_gate={"reliability_by_agent": reliability},
            claim_ids_by_agent=claim_ids_by_agent,
        )
        with pytest.raises(ValueError, match=rf"{accepted_kind} forbids"):
            _validate_macro_attribution_authority(
                [
                    {
                        "accepted_output_kind": accepted_kind,
                        "output": {
                            "payload": {
                                "accepted_macro_input_attributions": attributions,
                            }
                        },
                    }
                ],
                macro_gate={"reliability_by_agent": reliability},
                claim_ids_by_agent=claim_ids_by_agent,
            )


def test_accepted_cycle_rejects_caller_modified_weight_snapshot(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    state["darwinian_weight_snapshot"]["weights"][0]["darwin_weight"] = 1.1

    with pytest.raises(ValueError, match="does not match server authority"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_well_formed_forged_decision_identity(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "ALPHA_DISCOVERY"
    )
    payload = record["output"]["payload"]
    payload["accepted_alpha_discovery_id"] = (
        f"accepted-alpha-discovery:{canonical_hash('forged-alpha')[7:]}"
    )
    payload["accepted_alpha_discovery_hash"] = canonical_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "accepted_alpha_discovery_hash"
        }
    )
    _reseal_record(state, record)

    with pytest.raises(ValueError, match="accepted Alpha discovery ID mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_forged_relationship_edge_identity(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "RELATIONSHIP_GRAPH"
    )
    payload = record["output"]["payload"]
    claim = payload["claims"][0]
    forged_hash = canonical_hash("forged-factual-edge")
    payload["factual_edges"] = [
        {
            "edge_id": f"relationship-factual-edge:{forged_hash[7:]}",
            "edge_hash": forged_hash,
            "edge_candidate_id": "relationship:fixture",
            "relationship_row_hash": canonical_hash("relationship-row"),
            "source_entity": "holder:fixture",
            "source_entity_type": "HOLDER",
            "target_entity": "600001.SH",
            "target_entity_type": "PIT_ELIGIBLE_SECURITY",
            "target_sector_id": "sector:fixture",
            "edge_type": "OWNS",
            "activation_trigger": "Fixture activation trigger.",
            "evidence_ids": claim["evidence_ids"],
            "claim_refs": [claim["claim_id"]],
        }
    ]
    _reseal_record(state, record)

    with pytest.raises(ValueError, match="factual relationship edge identity mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_duplicate_relationship_semantic_tuple(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "RELATIONSHIP_GRAPH"
    )
    payload = record["output"]["payload"]
    claim = payload["claims"][0]

    def edge(candidate_id: str) -> dict[str, Any]:
        body = {
            "edge_candidate_id": candidate_id,
            "relationship_row_hash": canonical_hash(f"row:{candidate_id}"),
            "source_entity": "holder:fixture",
            "source_entity_type": "HOLDER",
            "target_entity": "600001.SH",
            "target_entity_type": "PIT_ELIGIBLE_SECURITY",
            "target_sector_id": "sector:fixture",
            "edge_type": "OWNS",
            "activation_trigger": "Fixture activation trigger.",
            "evidence_ids": claim["evidence_ids"],
        }
        edge_hash = canonical_hash(body)
        return {
            "edge_id": f"relationship-factual-edge:{edge_hash[7:]}",
            "edge_hash": edge_hash,
            **body,
            "claim_refs": [claim["claim_id"]],
        }

    payload["factual_edges"] = [edge("relationship:one"), edge("relationship:two")]
    _reseal_record(state, record)

    with pytest.raises(ValueError, match=r"factual_edges\..* must be unique"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_swapped_agent_audit_output_hashes(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    left, right = state["agent_run_audits"][:2]
    left["output_hash"], right["output_hash"] = (
        right["output_hash"],
        left["output_hash"],
    )

    with pytest.raises(ValueError, match="output/audit adapter lineage mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_forged_stage_skip_control_source(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state, stage_skip_agent="autonomous_execution")
    state["agent_run_audits"] = [
        audit
        for audit in state["agent_run_audits"]
        if audit["agent"] != "autonomous_execution"
    ]
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "CIO_FINAL"
    )
    source = record["output"]["payload"]["execution_control_source"]
    source["stage_skip_id"] = "forged-stage-skip"
    source["stage_skip_hash"] = canonical_hash("forged-stage-skip")
    _reseal_cio_final_record(state, record)

    with pytest.raises(ValueError, match="control source closure mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_forged_accepted_control_source(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "CIO_FINAL"
    )
    source = record["output"]["payload"]["cro_control_source"]
    source["accepted_output_id"] = "accepted-output:forged"
    source["accepted_output_hash"] = canonical_hash("forged-cro-output")
    _reseal_cio_final_record(state, record)

    with pytest.raises(ValueError, match="cro Decision control source closure mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_forged_control_resolution_source(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "CIO_FINAL"
    )
    record["output"]["payload"]["execution_control_resolutions"][0][
        "execution_assessment_hash"
    ] = canonical_hash("forged-execution-assessment")
    _reseal_cio_final_record(state, record)

    with pytest.raises(ValueError, match="execution resolution source closure mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_namespace_ref_mismatch(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    ref = next(iter(state["accepted_output_refs"].values()))
    ref["accepted_output_hash"] = canonical_hash("wrong-ref")

    with pytest.raises(ValueError, match="accepted output reference .* mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_decision_frozen_object_mismatch(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row["accepted_output_kind"] == "EXECUTION_ASSESSMENT"
        and row["run_slot_kind"] == "OUTCOME_SCHEDULED"
    )
    record["frozen_object_set_hash"] = canonical_hash({"forged": True})
    without_hash = {
        key: value for key, value in record.items() if key != "accepted_output_hash"
    }
    record["accepted_output_hash"] = canonical_hash(without_hash)
    ref = state["accepted_output_refs"]["EXECUTION_ASSESSMENT:autonomous_execution"]
    ref["accepted_output_hash"] = record["accepted_output_hash"]

    with pytest.raises(ValueError, match="frozen_object_set_hash mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_accepted_cycle_rejects_decision_runtime_authority_mismatch(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    record = next(
        row
        for row in state["accepted_output_records"]
        if row.get("runtime_opportunity_authority") is not None
    )
    record["runtime_opportunity_authority"]["candidate_scope_hash"] = canonical_hash(
        {"forged": True}
    )
    without_hash = {
        key: value for key, value in record.items() if key != "accepted_output_hash"
    }
    record["accepted_output_hash"] = canonical_hash(without_hash)
    ref = state["accepted_output_refs"][
        f"{record['accepted_output_kind']}:{record['agent_id']}"
    ]
    ref["accepted_output_hash"] = record["accepted_output_hash"]

    with pytest.raises(ValueError, match="runtime authority mismatch"):
        store.append_darwinian_v2_accepted_cycle(state)


def test_component_calibration_rejects_runtime_tamper_with_same_aggregate(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state, force_event_agent="china")
    _attach_accepted_records(state)
    scheduled_component_agent = next(
        slot["agent_id"]
        for slot in state["outcome_schedule_plan"]["slots"]
        if slot["run_slot_kind"] == "OUTCOME_SCHEDULED"
        and OUTCOME_CONTRACTS[slot["agent_id"]]["component_composition_contract"]
        is not None
    )
    components = state["component_calibration_inputs"][scheduled_component_agent][
        "components"
    ]
    assert len(components) >= 2
    components[0]["confidence"] = 0.7
    components[1]["confidence"] = 0.9

    with pytest.raises(
        ValueError,
        match="runtime input does not match accepted audit",
    ):
        store.append_darwinian_v2_accepted_cycle(state)

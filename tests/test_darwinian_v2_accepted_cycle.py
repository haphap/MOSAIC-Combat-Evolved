from __future__ import annotations

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, local
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

import mosaic.dataflows.agent_materialization as agent_materialization
import mosaic.dataflows.agent_stage_preparer as agent_stage_preparer
from mosaic.dataflows.outcome_runtime_inputs import (
    expected_qualification_predicate_version,
)
from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.agent_stage_preparer import (
    prepare_bound_runtime_family,
    publish_ready_stage_materialization,
)
from mosaic.dataflows.bound_runtime_snapshots import compile_bound_runtime_snapshot
from mosaic.bridge.tool_capabilities import (
    _validate_bound_runtime_snapshot,
    materialize_tool_payload,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.scorecard.darwinian_v2 import (
    accepted_cycle_stage_outcome_refs,
    _authoritative_macro_input_gate,
    _validate_macro_attribution_authority,
    canonical_hash,
    deterministic_id,
)
from mosaic.scorecard.capability_preservation import load_capability_contract_bundle
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.store import ScorecardStore


_ROOT = Path(__file__).parents[1]
_CAPABILITY_BUNDLE = load_capability_contract_bundle(_ROOT)
_CAPABILITY_TRACK = _CAPABILITY_BUNDLE["accepted_output_capability_track"]
_EXECUTION_RELEASE_IDS = {
    row["execution_behavior_release_id"]
    for row in _CAPABILITY_BUNDLE["tool_environment_manifest"]["environments"]
}
assert len(_EXECUTION_RELEASE_IDS) == 1
_EXECUTION_RELEASE_ID = next(iter(_EXECUTION_RELEASE_IDS))


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
        "execution_behavior_release_id": _EXECUTION_RELEASE_ID,
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
        "institutional_flow",
    )
    rows: list[dict[str, Any]] = []
    target_hash = canonical_hash(summary_body)
    usage_share = 1.0 / len(macro_agents)
    for macro_agent in macro_agents:
        rows.append(
            {
                "agent_id": macro_agent,
                "usage_share": usage_share,
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
                "capability_track": copy.deepcopy(_CAPABILITY_TRACK),
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


def test_cycle_stage_outcome_refs_reuse_exact_accepted_output_authority(
    tmp_path: Path,
) -> None:
    state = _state()
    _attach_schedule(ScorecardStore(tmp_path / "scorecard.db"), state)
    _attach_accepted_records(state)

    outcomes = accepted_cycle_stage_outcome_refs(state)

    assert len(outcomes) == 26
    assert outcomes == sorted(outcomes, key=lambda row: (row["agent_id"], row["stage"]))
    assert {row["outcome_kind"] for row in outcomes} == {"ACCEPTED_OUTPUT"}
    accepted_hashes = {
        record["accepted_output_hash"] for record in state["accepted_output_records"]
    }
    assert {row["ref_hash"] for row in outcomes} == accepted_hashes

    state["accepted_output_records"][0]["accepted_output_hash"] = canonical_hash(
        "tampered"
    )
    with pytest.raises(ValueError, match="accepted output reference"):
        accepted_cycle_stage_outcome_refs(state)


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


def _superinvestor_bound_inputs(tmp_path: Path) -> tuple[dict, list[dict], list[dict], dict]:
    state = _state()
    state["as_of_date"] = "2026-08-06"
    binding = state["darwinian_runtime_binding"]
    binding["effective_at"] = "2026-08-06T09:00:00+08:00"
    binding["binding_hash"] = canonical_hash(
        {key: value for key, value in binding.items() if key != "binding_hash"}
    )
    _attach_schedule(ScorecardStore(tmp_path / "scorecard.db"), state)
    _attach_accepted_records(state)
    accepted_records = [
        record
        for record in state["accepted_output_records"]
        if record["accepted_output_kind"]
        in {"MACRO_TRANSMISSION", "STANDARD_SECTOR_SELECTION", "RELATIONSHIP_GRAPH"}
    ]
    accepted_refs = [
        state["accepted_output_refs"][
            f"{record['accepted_output_kind']}:{record['agent_id']}"
        ]
        for record in accepted_records
    ]
    current_positions = {
        "snapshot_status": "empty_confirmed",
        "position_source": "empty_confirmed",
        "source_error_code": None,
        "position_snapshot_hash": canonical_hash("empty-positions"),
        "positions": [],
    }
    return state, accepted_records, accepted_refs, current_positions


def test_compile_superinvestor_bound_snapshot_from_exact_accepted_records(
    tmp_path: Path,
) -> None:
    state, accepted_records, accepted_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )

    snapshot = compile_bound_runtime_snapshot(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=accepted_refs,
        accepted_output_records=accepted_records,
        runtime_state={
            "captured_at": "2026-08-06T14:00:00+08:00",
            "current_positions": current_positions,
        },
        generated_at="2026-08-06T14:01:00+08:00",
    )

    assert snapshot["candidate_status"] == "EMPTY_CONFIRMED"
    assert snapshot["candidate_universe"] == []
    assert snapshot["constraints"] == {
        "cash_only": False,
        "allow_new_positions": True,
        "max_pick_count": 10,
        "max_total_conviction": 1.0,
        "prohibited_ts_codes": [],
        "evidence_ids": ["position-authority"],
    }
    _validate_bound_runtime_snapshot(
        snapshot,
        tool_id="get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        expected_candidate_scope_hash=None,
    )


def test_prepare_bound_runtime_family_atomically_publishes_receipts_and_reuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_manifest = copy.deepcopy(
        agent_stage_preparer.load_agent_data_route_manifest()
    )
    route_manifest["bindings"] = [
        row
        for row in route_manifest["bindings"]
        if row["agent_id"] != "ackman"
        or row["stage"] != "ackman"
        or row["tool_id"] == "get_superinvestor_candidate_snapshot"
    ]
    monkeypatch.setattr(
        agent_stage_preparer,
        "load_agent_data_route_manifest",
        lambda: route_manifest,
    )
    monkeypatch.setattr(
        agent_materialization,
        "load_agent_data_route_manifest",
        lambda: route_manifest,
    )
    state, accepted_records, accepted_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    runtime_state = {
        "current_positions": current_positions,
    }
    request = {
        "agent_id": "ackman",
        "stage": "ackman",
        "as_of": "2026-08-06",
        "graph_run_id": state["trace_id"],
        "candidate_scope": {"accepted_output_refs": accepted_refs},
        "runtime_inputs": {
            "accepted_output_refs": accepted_refs,
            "accepted_output_records": accepted_records,
            "bound_runtime_state": runtime_state,
        },
    }
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    output_root = tmp_path / "runtime_snapshots"

    def clock() -> datetime:
        return datetime(2026, 8, 6, 6, 1, tzinfo=timezone.utc)

    first = prepare_bound_runtime_family(
        request,
        ledger,
        output_root=output_root,
        clock=clock,
    )
    second = prepare_bound_runtime_family(
        request,
        ledger,
        output_root=output_root,
        clock=lambda: datetime(2026, 8, 6, 7, 1, tzinfo=timezone.utc),
    )

    assert first["cache_status"] == "MISS"
    assert second["cache_status"] == "HIT"
    assert first["output_path"] == second["output_path"]
    snapshot_path = output_root / first["output_path"]
    assert snapshot_path.is_file()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["graph_run_id"] == state["trace_id"]
    monkeypatch.setenv("MOSAIC_RUNTIME_SNAPSHOT_DIR", str(output_root))
    rendered = materialize_tool_payload(
        "get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=accepted_refs,
    )
    assert json.loads(rendered) == snapshot
    assert first["output_hash"] == second["output_hash"]
    assert len(first["source_receipt_hashes"]) == 2
    ready = ledger.ready_snapshot_build_receipts(
        agent_id="ackman",
        stage="ackman",
        tool_id="get_superinvestor_candidate_snapshot",
        as_of="2026-08-06",
    )
    assert len(ready) == 1
    build = ready[0].as_dict()
    assert build["required_route_ids"] == [
        "runtime.accepted_outputs",
        "runtime.candidate_scope",
    ]
    assert build["source_receipt_hashes"] == first["source_receipt_hashes"]
    assert build["output_hash"] == first["output_hash"]
    finalization_request = {
        **request,
        "run_slot_id": "slot-bound-1",
        "run_id": "run-bound-1",
        "node_id": "ackman-node",
        "materialization_request_id": "materialize-bound-1",
        "tool_payload_hashes": {
            "get_superinvestor_candidate_snapshot": canonical_hash("wrong-payload")
        },
    }
    with pytest.raises(DataVendorUnavailable, match="no READY build"):
        publish_ready_stage_materialization(
            finalization_request,
            ledger=ledger,
            clock=clock,
            cache_status="HIT",
        )
    finalization_request["tool_payload_hashes"] = {
        "get_superinvestor_candidate_snapshot": first["output_hash"]
    }
    finalized = publish_ready_stage_materialization(
        finalization_request,
        ledger=ledger,
        clock=clock,
        cache_status="HIT",
    )
    assert finalized["status"] == "READY"
    assert finalized["build_receipt_hashes"] == {
        "get_superinvestor_candidate_snapshot": first["build_receipt_hash"]
    }


def test_prepare_bound_runtime_family_concurrent_retry_reuses_winning_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, accepted_records, accepted_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    request = {
        "agent_id": "ackman",
        "stage": "ackman",
        "as_of": "2026-08-06",
        "graph_run_id": state["trace_id"],
        "candidate_scope": {"accepted_output_refs": accepted_refs},
        "runtime_inputs": {
            "accepted_output_refs": accepted_refs,
            "accepted_output_records": accepted_records,
            "bound_runtime_state": {"current_positions": current_positions},
        },
    }
    output_root = tmp_path / "runtime_snapshots"
    ledger_path = tmp_path / "materialization.sqlite3"
    publish_barrier = Barrier(2)
    publish_calls = local()
    real_publish = agent_stage_preparer.publish_bound_runtime_snapshot

    def racing_publish(*args: Any, **kwargs: Any) -> dict[str, Any]:
        call_count = getattr(publish_calls, "count", 0)
        publish_calls.count = call_count + 1
        if call_count == 0:
            publish_barrier.wait(timeout=5)
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(
        agent_stage_preparer,
        "publish_bound_runtime_snapshot",
        racing_publish,
    )

    def prepare_at(hour: int) -> dict[str, Any]:
        return prepare_bound_runtime_family(
            request,
            AgentDataMaterializationLedger(ledger_path),
            output_root=output_root,
            clock=lambda: datetime(2026, 8, 6, hour, 1, tzinfo=timezone.utc),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(prepare_at, (6, 7)))

    assert sorted(result["cache_status"] for result in results) == ["HIT", "MISS"]
    assert len({result["output_path"] for result in results}) == 1
    assert len({result["output_hash"] for result in results}) == 1
    ready = AgentDataMaterializationLedger(ledger_path).ready_snapshot_build_receipts(
        agent_id="ackman",
        stage="ackman",
        tool_id="get_superinvestor_candidate_snapshot",
        as_of="2026-08-06",
    )
    assert len(ready) == 1


def test_prepare_bound_runtime_family_runs_all_nine_stages_without_live_calendar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _sector_records, _sector_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    candidate_runtime = _empty_candidate_runtime(state, current_positions)
    candidate = candidate_runtime["candidate_target_state"]
    cro_state = _accepted_cro_runtime(state, candidate)
    execution_state = _accepted_execution_runtime(state, candidate, cro_state)
    stage_inputs = {
        **{
            (agent_id, agent_id): (
                {"MACRO_TRANSMISSION", "STANDARD_SECTOR_SELECTION", "RELATIONSHIP_GRAPH"},
                {"current_positions": current_positions},
            )
            for agent_id in ("ackman", "burry", "druckenmiller", "munger")
        },
        ("alpha_discovery", "alpha_discovery"): (
            {
                "STANDARD_SECTOR_SELECTION",
                "RELATIONSHIP_GRAPH",
                "SUPERINVESTOR_SELECTION",
            },
            {"current_positions": current_positions},
        ),
        ("cio", "cio_proposal"): (
            {
                "MACRO_TRANSMISSION",
                "STANDARD_SECTOR_SELECTION",
                "RELATIONSHIP_GRAPH",
                "SUPERINVESTOR_SELECTION",
                "ALPHA_DISCOVERY",
            },
            {
                "current_positions": current_positions,
                "previous_target_state": {
                    "schema_version": "portfolio.previous_target_state.v1",
                    "snapshot_status": "empty_confirmed",
                    "final_target_hash": None,
                    "as_of_date": None,
                    "portfolio_actions": [],
                    "source_error_code": None,
                },
                "decision_policy_release": _decision_policy_release(),
            },
        ),
        ("cro", "cro"): (
            {"CIO_PROPOSAL"},
            {
                "current_positions": current_positions,
                "decision_policy_release": _decision_policy_release(),
                **candidate_runtime,
            },
        ),
        ("autonomous_execution", "autonomous_execution"): (
            {"CIO_PROPOSAL", "CRO_RISK_REVIEW"},
            {
                "current_positions": current_positions,
                "decision_policy_release": _decision_policy_release(),
                "candidate_target_state": candidate,
                "cro_review_state": cro_state,
                "resolved_source_statuses": [],
                "execution_mode": "PAPER",
            },
        ),
        ("cio", "cio_final"): (
            {"CIO_PROPOSAL", "CRO_RISK_REVIEW", "EXECUTION_ASSESSMENT"},
            {
                "current_positions": current_positions,
                "decision_policy_release": _decision_policy_release(),
                "candidate_target_state": candidate,
                "cro_review_state": cro_state,
                "execution_feasibility_state": execution_state,
            },
        ),
    }
    role_event_calls: list[tuple[str, ...]] = []

    class CompleteCoverage:
        @staticmethod
        def as_dict() -> dict[str, Any]:
            return {"coverage_complete": True}

    calendar = SimpleNamespace(coverage_receipt=CompleteCoverage())
    monkeypatch.setattr(agent_stage_preparer, "EconomicCalendarStore", lambda: object())
    monkeypatch.setattr(
        agent_stage_preparer,
        "archive_eco_calendar",
        lambda *_args, **_kwargs: calendar,
    )
    monkeypatch.setattr(
        agent_stage_preparer,
        "compile_role_event_builds",
        lambda **kwargs: role_event_calls.append(tuple(kwargs["agent_ids"])),
    )
    ledger = AgentDataMaterializationLedger(tmp_path / "all-bound-stages.sqlite3")
    output_root = tmp_path / "all-bound-snapshots"

    for (agent_id, stage), (accepted_kinds, runtime_state) in stage_inputs.items():
        records = [
            record
            for record in state["accepted_output_records"]
            if record["accepted_output_kind"] in accepted_kinds
        ]
        refs = [
            state["accepted_output_refs"][
                f"{record['accepted_output_kind']}:{record['agent_id']}"
            ]
            for record in records
        ]
        request = {
            "agent_id": agent_id,
            "stage": stage,
            "as_of": "2026-08-06",
            "graph_run_id": state["trace_id"],
            "candidate_scope": {"accepted_output_refs": refs},
            "runtime_inputs": {
                "accepted_output_refs": refs,
                "accepted_output_records": records,
                "bound_runtime_state": runtime_state,
            },
        }
        prepared = prepare_bound_runtime_family(
            request,
            ledger,
            output_root=output_root,
            clock=lambda: datetime(2026, 8, 6, 6, 1, tzinfo=timezone.utc),
        )
        assert prepared["cache_status"] in {"MISS", "MIXED"}
        assert (output_root / prepared["output_path"]).is_file()

    assert role_event_calls == [
        ("alpha_discovery",),
        ("cro",),
        ("autonomous_execution",),
    ]


def test_compile_superinvestor_bound_snapshot_projects_real_sector_pick(
    tmp_path: Path,
) -> None:
    state, accepted_records, accepted_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    sector_record = next(
        record
        for record in accepted_records
        if record["accepted_output_kind"] == "STANDARD_SECTOR_SELECTION"
        and record["agent_id"] == "energy"
    )
    payload = sector_record["output"]["payload"]
    selection = payload["selection"]
    preferred = selection["preferred_direction"]
    claim_ref = selection["claim_refs"][0]
    selection["preferred_security_status"] = "PICKS_PRESENT"
    selection["long_picks"] = [
        {
            "pick_local_id": "energy-long-1",
            "direction_local_id": preferred["direction_local_id"],
            "ts_code": "600028.SH",
            "position_action": "LONG",
            "conviction": 0.7,
            "thesis": "Fixture security thesis.",
            "claim_refs": [claim_ref],
        }
    ]
    payload["preferred_security_abstention_confidence"] = None
    payload["accepted_macro_input_attributions"] = _accepted_macro_attributions(selection)
    _reseal_record(state, sector_record)

    snapshot = compile_bound_runtime_snapshot(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=accepted_refs,
        accepted_output_records=accepted_records,
        runtime_state={
            "captured_at": "2026-08-06T14:00:00+08:00",
            "current_positions": current_positions,
        },
        generated_at="2026-08-06T14:01:00+08:00",
    )

    assert snapshot["candidate_status"] == "AVAILABLE"
    assert snapshot["candidate_universe"] == [
        {
            "candidate_ref": snapshot["candidate_universe"][0]["candidate_ref"],
            "ts_code": "600028.SH",
            "source_output_id": sector_record["accepted_output_id"],
            "source_output_hash": sector_record["accepted_output_hash"],
            "source_sector_agent_id": "energy",
            "source_direction_id": preferred["direction_id"],
            "source_direction": "PREFERRED",
            "metrics": {"conviction": 0.7},
            "evidence_ids": snapshot["candidate_universe"][0]["evidence_ids"],
        }
    ]
    _validate_bound_runtime_snapshot(
        snapshot,
        tool_id="get_superinvestor_candidate_snapshot",
        agent_id="ackman",
        stage="ackman",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        expected_candidate_scope_hash=None,
    )


def test_bound_snapshots_merge_same_ticker_without_losing_authority(
    tmp_path: Path,
) -> None:
    state, accepted_records, accepted_refs, _current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    sector_records = [
        record
        for record in accepted_records
        if record["accepted_output_kind"] == "STANDARD_SECTOR_SELECTION"
    ][:3]
    candidate_refs: list[tuple[float, str, dict]] = []
    for index, (sector_record, conviction) in enumerate(
        zip(sector_records, (0.9, 0.9, 0.7), strict=True)
    ):
        payload = sector_record["output"]["payload"]
        selection = payload["selection"]
        preferred = selection["preferred_direction"]
        pick_local_id = f"shared-ticker-{index}"
        selection["preferred_security_status"] = "PICKS_PRESENT"
        selection["long_picks"] = [
            {
                "pick_local_id": pick_local_id,
                "direction_local_id": preferred["direction_local_id"],
                "ts_code": "600028.SH",
                "position_action": "LONG",
                "conviction": conviction,
                "thesis": "Shared ticker fixture thesis.",
                "claim_refs": [selection["claim_refs"][0]],
            }
        ]
        payload["preferred_security_abstention_confidence"] = None
        payload["accepted_macro_input_attributions"] = _accepted_macro_attributions(
            selection
        )
        _reseal_record(state, sector_record)
        candidate_refs.append(
            (
                conviction,
                "runtime-candidate:"
                + canonical_hash(
                    {
                        "accepted_output_id": sector_record["accepted_output_id"],
                        "pick_local_id": pick_local_id,
                    }
                )[7:],
                sector_record,
            )
        )

    expected_ref, expected_record = min(
        (candidate_ref, record)
        for conviction, candidate_ref, record in candidate_refs
        if conviction == 0.9
    )
    accepted_evidence = {
        "accepted-evidence:" + record["accepted_output_hash"][7:]
        for record in sector_records
    }
    current_positions = {
        "snapshot_status": "loaded",
        "position_source": "broker",
        "source_error_code": None,
        "position_snapshot_hash": canonical_hash({"600028.SH": 0.23}),
        "positions": [{"ticker": "600028.SH", "current_weight": 0.23}],
    }

    superinvestor = compile_bound_runtime_snapshot(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=accepted_refs,
        accepted_output_records=accepted_records,
        runtime_state={
            "captured_at": "2026-08-06T14:00:00+08:00",
            "current_positions": current_positions,
        },
        generated_at="2026-08-06T14:01:00+08:00",
    )
    assert len(superinvestor["candidate_universe"]) == 1
    candidate = superinvestor["candidate_universe"][0]
    assert candidate["candidate_ref"] == expected_ref
    assert candidate["source_output_id"] == expected_record["accepted_output_id"]
    assert set(candidate["evidence_ids"]) == accepted_evidence
    assert len(superinvestor["upstream_accepted_output_refs"]) == len(accepted_refs)

    cio = compile_bound_runtime_snapshot(
        agent_id="cio",
        stage="cio_proposal",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=accepted_refs,
        accepted_output_records=accepted_records,
        runtime_state={
            "captured_at": "2026-08-06T14:20:00+08:00",
            "current_positions": current_positions,
            "previous_target_state": {
                "schema_version": "portfolio.previous_target_state.v1",
                "snapshot_status": "empty_confirmed",
                "final_target_hash": None,
                "as_of_date": None,
                "portfolio_actions": [],
                "source_error_code": None,
            },
            "decision_policy_release": _decision_policy_release(),
        },
        generated_at="2026-08-06T14:21:00+08:00",
    )
    assert len(cio["candidate_universe"]) == 1
    candidate = cio["candidate_universe"][0]
    assert candidate["current_weight"] == 0.23
    assert candidate["reference_target_weight"] == 0.9
    assert set(candidate["evidence_ids"]) == {
        *accepted_evidence,
        "position-authority",
    }
    assert len(cio["upstream_accepted_output_refs"]) == len(accepted_refs)


def test_compile_superinvestor_bound_snapshot_rejects_tampered_record(
    tmp_path: Path,
) -> None:
    state, accepted_records, accepted_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    accepted_records[0]["output"]["payload"]["model_confidence"] = 0.1

    with pytest.raises(DataVendorUnavailable, match="accepted output record"):
        compile_bound_runtime_snapshot(
            agent_id="ackman",
            stage="ackman",
            as_of="2026-08-06",
            graph_run_id=state["trace_id"],
            accepted_output_refs=accepted_refs,
            accepted_output_records=accepted_records,
            runtime_state={
                "captured_at": "2026-08-06T14:00:00+08:00",
                "current_positions": current_positions,
            },
            generated_at="2026-08-06T14:01:00+08:00",
        )


def test_compile_alpha_bound_snapshot_requires_all_superinvestor_outputs(
    tmp_path: Path,
) -> None:
    state, _sector_records, _sector_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    accepted_records = [
        record
        for record in state["accepted_output_records"]
        if record["accepted_output_kind"]
        in {
            "STANDARD_SECTOR_SELECTION",
            "RELATIONSHIP_GRAPH",
            "SUPERINVESTOR_SELECTION",
        }
    ]
    accepted_refs = [
        state["accepted_output_refs"][
            f"{record['accepted_output_kind']}:{record['agent_id']}"
        ]
        for record in accepted_records
    ]

    snapshot = compile_bound_runtime_snapshot(
        agent_id="alpha_discovery",
        stage="alpha_discovery",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=accepted_refs,
        accepted_output_records=accepted_records,
        runtime_state={
            "captured_at": "2026-08-06T14:10:00+08:00",
            "current_positions": current_positions,
        },
        generated_at="2026-08-06T14:11:00+08:00",
    )

    assert snapshot["candidate_status"] == "EMPTY_CONFIRMED"
    assert snapshot["candidate_universe"] == []
    assert snapshot["constraints"]["max_novel_pick_count"] == 10
    assert {
        ref["agent_id"]
        for ref in snapshot["upstream_accepted_output_refs"]
        if ref["accepted_output_kind"] == "SUPERINVESTOR_SELECTION"
    } == {"ackman", "burry", "druckenmiller", "munger"}
    _validate_bound_runtime_snapshot(
        snapshot,
        tool_id="get_alpha_candidate_snapshot",
        agent_id="alpha_discovery",
        stage="alpha_discovery",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        expected_candidate_scope_hash=None,
    )


def _decision_policy_release() -> dict[str, Any]:
    identity_body = {
        "schema_version": "deterministic_decision_policy_release_v1",
        "effective_at": "2026-08-05T00:00:00+08:00",
        "owner_revisions": {
            "cro": "cro_risk_policy_v1",
            "cio": "cio_portfolio_governance_policy_v1",
            "autonomous_execution": "autonomous_execution_policy_v1",
        },
        "policies": {
            "cro": {
                "stop_loss_pct": -0.08,
                "max_single_name_weight": 0.12,
                "max_sector_weight": 0.3,
            },
            "cio": {"stale_thesis_days": 20},
            "autonomous_execution": {
                "min_delta_trade_weight": 0.01,
                "slippage_cap": 0.003,
                "liquidity_floor": 0.6,
            },
        },
    }
    with_identity = {
        **identity_body,
        "policy_release_id": "decision-policy:"
        + canonical_hash(identity_body).removeprefix("sha256:"),
    }
    return {**with_identity, "release_hash": canonical_hash(with_identity)}


def test_compile_cio_proposal_bound_snapshot_from_preproposal_authority(
    tmp_path: Path,
) -> None:
    state, _sector_records, _sector_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    accepted_records = [
        record
        for record in state["accepted_output_records"]
        if record["accepted_output_kind"]
        in {
            "MACRO_TRANSMISSION",
            "STANDARD_SECTOR_SELECTION",
            "RELATIONSHIP_GRAPH",
            "SUPERINVESTOR_SELECTION",
            "ALPHA_DISCOVERY",
        }
    ]
    accepted_refs = [
        state["accepted_output_refs"][
            f"{record['accepted_output_kind']}:{record['agent_id']}"
        ]
        for record in accepted_records
    ]

    snapshot = compile_bound_runtime_snapshot(
        agent_id="cio",
        stage="cio_proposal",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=accepted_refs,
        accepted_output_records=accepted_records,
        runtime_state={
            "captured_at": "2026-08-06T14:20:00+08:00",
            "current_positions": current_positions,
            "previous_target_state": {
                "schema_version": "portfolio.previous_target_state.v1",
                "snapshot_status": "empty_confirmed",
                "final_target_hash": None,
                "as_of_date": None,
                "portfolio_actions": [],
                "source_error_code": None,
            },
            "decision_policy_release": _decision_policy_release(),
        },
        generated_at="2026-08-06T14:21:00+08:00",
    )

    assert snapshot["candidate_status"] == "EMPTY_CONFIRMED"
    assert snapshot["constraints"]["max_single_name_weight"] == 0.12
    assert snapshot["role_context"]["decision_stage"] == "PROPOSAL"
    _validate_bound_runtime_snapshot(
        snapshot,
        tool_id="get_cio_decision_snapshot",
        agent_id="cio",
        stage="cio_proposal",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        expected_candidate_scope_hash=None,
    )


def _empty_candidate_runtime(state: Mapping[str, Any], current_positions: Mapping[str, Any]) -> dict:
    proposal_record = next(
        record
        for record in state["accepted_output_records"]
        if record["accepted_output_kind"] == "CIO_PROPOSAL"
    )
    proposal = proposal_record["output"]["payload"]
    candidate_body = {
        "run_id": state["trace_id"],
        "cohort": state["active_cohort"],
        "as_of_date": "2026-08-06",
        "proposal_hash": proposal["proposal_hash"],
        "l4_run_snapshot_hash": canonical_hash("l4-run-snapshot"),
        "position_snapshot_hash": current_positions["position_snapshot_hash"],
        "previous_target_hash": None,
        "market_data_vintage_hash": canonical_hash("market-vintage"),
        "portfolio_actions": [],
        "confidence": 0.8,
    }
    candidate = {
        "schema_version": "portfolio.candidate_target_state.v1",
        **candidate_body,
        "candidate_target_hash": canonical_hash(candidate_body),
        "frozen": True,
    }
    exposure_body = {
        "candidate_target_hash": candidate["candidate_target_hash"],
        "l4_run_snapshot_hash": candidate["l4_run_snapshot_hash"],
        "gross_exposure": 0.0,
        "net_exposure": 0.0,
        "cash_weight": 1.0,
        "ticker_weights": {},
        "sector_weights": {},
    }
    exposure = {
        "schema_version": "portfolio.exposure_state.v1",
        **exposure_body,
        "exposure_hash": canonical_hash(exposure_body),
        "frozen": True,
    }
    return {"candidate_target_state": candidate, "portfolio_exposure_state": exposure}


def test_compile_cro_bound_snapshot_from_frozen_candidate_target(
    tmp_path: Path,
) -> None:
    state, _sector_records, _sector_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    proposal_record = next(
        record
        for record in state["accepted_output_records"]
        if record["accepted_output_kind"] == "CIO_PROPOSAL"
    )
    proposal_ref = state["accepted_output_refs"]["CIO_PROPOSAL:cio"]
    frozen_runtime = _empty_candidate_runtime(state, current_positions)

    snapshot = compile_bound_runtime_snapshot(
        agent_id="cro",
        stage="cro",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=[proposal_ref],
        accepted_output_records=[proposal_record],
        runtime_state={
            "captured_at": "2026-08-06T14:30:00+08:00",
            "current_positions": current_positions,
            "decision_policy_release": _decision_policy_release(),
            **frozen_runtime,
        },
        generated_at="2026-08-06T14:31:00+08:00",
    )

    assert snapshot["candidate_status"] == "EMPTY_CONFIRMED"
    assert snapshot["role_context"]["proposal_accepted_output_id"] == proposal_ref[
        "accepted_output_id"
    ]
    assert snapshot["constraints"]["max_sector_weight"] == 0.3
    _validate_bound_runtime_snapshot(
        snapshot,
        tool_id="get_cro_risk_snapshot",
        agent_id="cro",
        stage="cro",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        expected_candidate_scope_hash=None,
    )


def test_compile_cro_bound_snapshot_preserves_nonempty_weight_delta(
    tmp_path: Path,
) -> None:
    state, _sector_records, _sector_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    proposal_record = next(
        record
        for record in state["accepted_output_records"]
        if record["accepted_output_kind"] == "CIO_PROPOSAL"
    )
    proposal = proposal_record["output"]["payload"]
    decision = proposal["decision"]
    claim_ref = decision["claim_refs"][0]
    decision["decision_disposition"] = "TARGET_PORTFOLIO"
    decision["target_positions"] = [
        {
            "position_local_id": "position:600028.SH",
            "ts_code": "600028.SH",
            "target_weight": 0.1,
            "position_decision": "ADD",
            "holding_period": "WEEKS",
            "thesis_status": "INTACT",
            "risk_flags": [],
            "claim_refs": [claim_ref],
        }
    ]
    decision["cash_weight"] = 0.9
    proposal["accepted_macro_input_attributions"] = _accepted_macro_attributions(decision)
    proposal_without_identity = {
        key: value for key, value in proposal.items() if key not in {"proposal_id", "proposal_hash"}
    }
    proposal["proposal_id"] = _persistent_id("cio-proposal", proposal_without_identity)
    proposal["proposal_hash"] = canonical_hash(
        {**proposal_without_identity, "proposal_id": proposal["proposal_id"]}
    )
    _reseal_record(state, proposal_record)
    action = {
        "ticker": "600028.SH",
        "action": "BUY",
        "sector": "energy",
        "position_decision": "ADD",
        "current_weight": 0.0,
        "target_weight": 0.1,
        "delta_weight": 0.1,
        "holding_period": "1M",
        "dissent_notes": "",
    }
    candidate_body = {
        "run_id": state["trace_id"],
        "cohort": state["active_cohort"],
        "as_of_date": "2026-08-06",
        "proposal_hash": proposal["proposal_hash"],
        "l4_run_snapshot_hash": canonical_hash("l4-run-snapshot"),
        "position_snapshot_hash": current_positions["position_snapshot_hash"],
        "previous_target_hash": None,
        "market_data_vintage_hash": canonical_hash("market-vintage"),
        "portfolio_actions": [action],
        "confidence": 0.8,
    }
    candidate = {
        "schema_version": "portfolio.candidate_target_state.v1",
        **candidate_body,
        "candidate_target_hash": canonical_hash(candidate_body),
        "frozen": True,
    }
    exposure_body = {
        "candidate_target_hash": candidate["candidate_target_hash"],
        "l4_run_snapshot_hash": candidate["l4_run_snapshot_hash"],
        "gross_exposure": 0.1,
        "net_exposure": 0.1,
        "cash_weight": 0.9,
        "ticker_weights": {"600028.SH": 0.1},
        "sector_weights": {"energy": 0.1},
    }
    exposure = {
        "schema_version": "portfolio.exposure_state.v1",
        **exposure_body,
        "exposure_hash": canonical_hash(exposure_body),
        "frozen": True,
    }

    snapshot = compile_bound_runtime_snapshot(
        agent_id="cro",
        stage="cro",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=[state["accepted_output_refs"]["CIO_PROPOSAL:cio"]],
        accepted_output_records=[proposal_record],
        runtime_state={
            "captured_at": "2026-08-06T14:30:00+08:00",
            "current_positions": current_positions,
            "decision_policy_release": _decision_policy_release(),
            "candidate_target_state": candidate,
            "portfolio_exposure_state": exposure,
        },
        generated_at="2026-08-06T14:31:00+08:00",
    )

    assert snapshot["candidate_universe"][0]["proposed_delta_weight"] == 0.1
    assert snapshot["candidate_universe"][0]["sector_id"] == "energy"
    _validate_bound_runtime_snapshot(
        snapshot,
        tool_id="get_cro_risk_snapshot",
        agent_id="cro",
        stage="cro",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        expected_candidate_scope_hash=None,
    )


def _accepted_cro_runtime(
    state: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    payload = {
        "run_id": state["trace_id"],
        "candidate_target_hash": candidate["candidate_target_hash"],
        "l4_run_snapshot_hash": candidate["l4_run_snapshot_hash"],
        "source_status": "ACCEPTED_OUTPUT",
        "stage_skip_id": None,
        "stage_skip_hash": None,
        "output": {
            "agent": "cro",
            "review_disposition": "NO_OBJECTION",
            "rejected_picks": [],
            "required_adjustments": [],
            "correlated_risks": [],
            "black_swan_scenarios": [],
            "confidence": 0.8,
        },
    }
    return {
        "schema_version": "decision.cro_review_state.v1",
        **payload,
        "review_hash": canonical_hash(payload),
        "frozen": True,
    }


def test_compile_execution_bound_snapshot_from_frozen_cro_control(
    tmp_path: Path,
) -> None:
    state, _sector_records, _sector_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    proposal_record = next(
        record
        for record in state["accepted_output_records"]
        if record["accepted_output_kind"] == "CIO_PROPOSAL"
    )
    cro_record = next(
        record
        for record in state["accepted_output_records"]
        if record["accepted_output_kind"] == "CRO_RISK_REVIEW"
    )
    refs = [
        state["accepted_output_refs"]["CIO_PROPOSAL:cio"],
        state["accepted_output_refs"]["CRO_RISK_REVIEW:cro"],
    ]
    frozen_runtime = _empty_candidate_runtime(state, current_positions)
    candidate = frozen_runtime["candidate_target_state"]

    snapshot = compile_bound_runtime_snapshot(
        agent_id="autonomous_execution",
        stage="autonomous_execution",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=refs,
        accepted_output_records=[proposal_record, cro_record],
        runtime_state={
            "captured_at": "2026-08-06T14:40:00+08:00",
            "current_positions": current_positions,
            "decision_policy_release": _decision_policy_release(),
            "candidate_target_state": candidate,
            "cro_review_state": _accepted_cro_runtime(state, candidate),
            "resolved_source_statuses": [],
            "execution_mode": "PAPER",
        },
        generated_at="2026-08-06T14:41:00+08:00",
    )

    assert snapshot["candidate_status"] == "EMPTY_CONFIRMED"
    assert snapshot["constraints"]["max_slippage_bps"] == 30.0
    assert snapshot["role_context"]["cro_control_source"]["source_status"] == (
        "ACCEPTED_OUTPUT"
    )
    _validate_bound_runtime_snapshot(
        snapshot,
        tool_id="get_execution_snapshot",
        agent_id="autonomous_execution",
        stage="autonomous_execution",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        expected_candidate_scope_hash=None,
    )


def _accepted_execution_runtime(
    state: Mapping[str, Any],
    candidate: Mapping[str, Any],
    cro_state: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "run_id": state["trace_id"],
        "candidate_target_hash": candidate["candidate_target_hash"],
        "l4_run_snapshot_hash": candidate["l4_run_snapshot_hash"],
        "cro_review_hash": cro_state["review_hash"],
        "source_status": "ACCEPTED_OUTPUT",
        "stage_skip_id": None,
        "stage_skip_hash": None,
        "liquidity_vintage_hash": canonical_hash(
            {
                "source_id": "execution_liquidity_state",
                "as_of_date": "2026-08-06",
                "scopes": [],
            }
        ),
        "output": {
            "agent": "autonomous_execution",
            "execution_disposition": "NO_DELTA",
            "trades": [],
            "execution_checks": [],
            "confidence": 0.8,
        },
    }
    return {
        "schema_version": "decision.execution_feasibility_state.v1",
        **payload,
        "feasibility_hash": canonical_hash(payload),
        "frozen": True,
    }


def test_compile_cio_final_bound_snapshot_from_frozen_controls(
    tmp_path: Path,
) -> None:
    state, _sector_records, _sector_refs, current_positions = (
        _superinvestor_bound_inputs(tmp_path)
    )
    records = [
        next(
            record
            for record in state["accepted_output_records"]
            if record["accepted_output_kind"] == kind
        )
        for kind in ("CIO_PROPOSAL", "CRO_RISK_REVIEW", "EXECUTION_ASSESSMENT")
    ]
    refs = [
        state["accepted_output_refs"][key]
        for key in (
            "CIO_PROPOSAL:cio",
            "CRO_RISK_REVIEW:cro",
            "EXECUTION_ASSESSMENT:autonomous_execution",
        )
    ]
    candidate = _empty_candidate_runtime(state, current_positions)[
        "candidate_target_state"
    ]
    cro_state = _accepted_cro_runtime(state, candidate)
    execution_state = _accepted_execution_runtime(state, candidate, cro_state)

    snapshot = compile_bound_runtime_snapshot(
        agent_id="cio",
        stage="cio_final",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        accepted_output_refs=refs,
        accepted_output_records=records,
        runtime_state={
            "captured_at": "2026-08-06T14:50:00+08:00",
            "current_positions": current_positions,
            "decision_policy_release": _decision_policy_release(),
            "candidate_target_state": candidate,
            "cro_review_state": cro_state,
            "execution_feasibility_state": execution_state,
        },
        generated_at="2026-08-06T14:51:00+08:00",
    )

    assert snapshot["candidate_status"] == "EMPTY_CONFIRMED"
    assert snapshot["role_context"]["decision_stage"] == "FINAL"
    assert snapshot["role_context"]["execution_control_source"][
        "source_status"
    ] == "ACCEPTED_OUTPUT"
    _validate_bound_runtime_snapshot(
        snapshot,
        tool_id="get_cio_decision_snapshot",
        agent_id="cio",
        stage="cio_final",
        as_of="2026-08-06",
        graph_run_id=state["trace_id"],
        expected_candidate_scope_hash=None,
    )


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


def test_accepted_cycle_writes_26_outputs_and_25_operational_audits(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "scorecard.db"
    store = ScorecardStore(db_path)
    state = _state()
    scheduled_count, component_signal_count = _attach_schedule(store, state)
    _attach_accepted_records(state)
    result = store.append_darwinian_v2_accepted_cycle(state)
    assert result["accepted_output_records"] == 26
    assert result["operational_opportunity_audits"] == 25
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
    assert len(accepted) == 26
    assert len(operational) == 25
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


def test_accepted_cycle_keeps_pre_capability_track_record_labelable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "scorecard.db"
    store = ScorecardStore(db_path)
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    legacy_record = next(
        record
        for record in state["accepted_output_records"]
        if record["agent_id"] == "china"
    )
    legacy_record.pop("capability_track")
    _reseal_record(state, legacy_record)
    state["macro_input_gate"] = _authoritative_macro_input_gate(
        state["accepted_output_records"],
        weight_snapshot=state["darwinian_weight_snapshot"],
    )[0]

    result = store.append_darwinian_v2_accepted_cycle(state)

    assert result["accepted_output_records"] == 26
    with sqlite3.connect(db_path) as conn:
        stored = json.loads(
            conn.execute(
                "SELECT record_json FROM accepted_agent_outputs_v2 "
                "WHERE agent_id = 'china'"
            ).fetchone()[0]
        )
    assert "capability_track" not in stored


def test_accepted_cycle_keeps_cross_generation_capability_track_labelable(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    _attach_schedule(store, state)
    _attach_accepted_records(state)
    prior_generation_record = next(
        record
        for record in state["accepted_output_records"]
        if record["agent_id"] == "china"
    )
    track = prior_generation_record["capability_track"]
    track["knot_coverage_manifest_hash"] = "sha256:" + "d" * 64
    track_body = {
        key: value for key, value in track.items() if key != "capability_bundle_hash"
    }
    track["capability_bundle_hash"] = canonical_hash(track_body)
    _reseal_record(state, prior_generation_record)
    state["macro_input_gate"] = _authoritative_macro_input_gate(
        state["accepted_output_records"],
        weight_snapshot=state["darwinian_weight_snapshot"],
    )[0]

    result = store.append_darwinian_v2_accepted_cycle(state)

    assert result["accepted_output_records"] == 26


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
    assert result["accepted_output_records"] == 25
    assert result["operational_opportunity_audits"] == 24
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
    macro_agent_ids = [
        agent_id
        for agent_id in OUTCOME_CONTRACTS
        if OUTCOME_CONTRACTS[agent_id]["layer"] == "MACRO"
    ]
    reliability = {
        agent_id: {"usage_share": 1.0 / len(macro_agent_ids)}
        for agent_id in macro_agent_ids
    }
    claim_ids_by_agent = {agent_id: set() for agent_id in reliability}
    attributions = [
        {
            "agent_id": agent_id,
            "usage_share": reliability[agent_id]["usage_share"],
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

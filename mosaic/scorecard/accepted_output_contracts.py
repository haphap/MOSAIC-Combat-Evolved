"""Server-owned structural contracts for production accepted Agent outputs."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from mosaic.scorecard.canonical_json import canonical_hash


ACCEPTED_OUTPUT_ADAPTER_CONTRACT_VERSION = "accepted_output_adapter_v1"

_MACRO_AGENT_IDS = (
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
_ATTRIBUTION_TARGET_TYPES = {
    "SUBMISSION_SUMMARY",
    "SECTOR_THESIS",
    "SECURITY_PICK",
    "RISK_ACTION",
    "PORTFOLIO_DECISION",
}
_MATERIAL_ATTRIBUTION_EFFECTS = {"SUPPORTS", "OPPOSES", "RISK_ONLY", "MIXED"}
_TS_CODE = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")

_LIVE_SOURCE_TOOL_BY_AGENT = {
    "china": "get_china_macro_snapshot",
    "us_economy": "get_us_macro_snapshot",
    "eu_economy": "get_eu_macro_snapshot",
    "central_bank": "get_central_bank_snapshot",
    "us_financial_conditions": "get_us_financial_conditions_snapshot",
    "euro_area_financial_conditions": "get_euro_area_financial_conditions_snapshot",
    "commodities": "get_commodity_conditions_snapshot",
    "geopolitical": "get_geopolitical_events_snapshot",
    "market_breadth": "get_market_breadth_snapshot",
    "institutional_flow": "get_market_positioning_snapshot",
    "semiconductor": "get_sector_research_snapshot",
    "technology": "get_sector_research_snapshot",
    "energy": "get_sector_research_snapshot",
    "biotech": "get_sector_research_snapshot",
    "consumer": "get_sector_research_snapshot",
    "industrials": "get_sector_research_snapshot",
    "real_estate_construction": "get_sector_research_snapshot",
    "financials": "get_sector_research_snapshot",
    "agriculture": "get_sector_research_snapshot",
    "relationship_mapper": "get_relationship_graph_snapshot",
}
_DECISION_SOURCE_TOOL_BY_AGENT = {
    "alpha_discovery": "get_alpha_candidate_snapshot",
    "cro": "get_cro_risk_snapshot",
    "autonomous_execution": "get_execution_snapshot",
    "cio": "get_cio_decision_snapshot",
}

_BASE_RECORD_FIELDS = {
    "accepted_output_id",
    "accepted_output_hash",
    "graph_run_id",
    "run_id",
    "run_slot_id",
    "operational_opportunity_audit_id",
    "production_variant_roster_id",
    "production_variant_roster_revision_id",
    "execution_behavior_release_id",
    "cohort_id",
    "language",
    "track_key_hash",
    "agent_id",
    "accepted_output_kind",
    "sample_origin",
    "run_slot_kind",
    "scheduled_sample_id",
    "agent_contract_version",
    "prompt_behavior_version",
    "execution_behavior_version",
    "component_weight_contract_version",
    "reliability_adapter_contract_version",
    "confidence_semantics_contract_version",
    "as_of",
    "accepted_at",
    "evaluation_opportunity_set_id",
    "evaluation_opportunity_set_hash",
    "frozen_object_set_id",
    "frozen_object_set_hash",
    "adapter_lineage",
    "output",
}


def validate_accepted_output_record_schema(
    record: Mapping[str, Any],
    *,
    agent_id: str,
    accepted_kind: str,
    allow_runtime_authority: bool,
    require_runtime_audit: bool,
) -> None:
    """Reject fields outside the public accepted-output contract before persistence."""
    expected = set(_BASE_RECORD_FIELDS)
    if allow_runtime_authority:
        expected.add("runtime_opportunity_authority")
    if require_runtime_audit:
        expected.add("runtime_audit")
    _exact_object(record, expected, f"{agent_id}:{accepted_kind} accepted output")
    if allow_runtime_authority:
        _validate_runtime_authority(record, agent_id=agent_id)
    envelope = _object(record.get("output"), "accepted output envelope")
    _exact_object(
        envelope,
        {
            "payload",
            "evidence_bundle_ids",
            "causal_dedupe_keys",
            "claim_graph_lineage",
        },
        "accepted output envelope",
    )
    payload = _object(envelope.get("payload"), "accepted output payload")
    claim_ids = _validate_payload(payload, agent_id=agent_id, accepted_kind=accepted_kind)
    _validate_claim_graph_lineage(
        envelope,
        graph_run_id=_text(record.get("graph_run_id"), "graph_run_id"),
        payload_claim_evidence=claim_ids,
    )
    _validate_adapter_lineage(record, agent_id=agent_id, accepted_kind=accepted_kind)


def _validate_runtime_authority(
    record: Mapping[str, Any], *, agent_id: str
) -> None:
    authority = _object(
        record.get("runtime_opportunity_authority"),
        "runtime_opportunity_authority",
    )
    if agent_id in _LIVE_SOURCE_TOOL_BY_AGENT:
        _exact_object(
            authority,
            {"source_tool_id", "source_snapshot_hash", "domain_hash"},
            "live source authority",
        )
        expected_tool = _LIVE_SOURCE_TOOL_BY_AGENT[agent_id]
        hash_fields = ("source_snapshot_hash", "domain_hash")
    elif agent_id in _DECISION_SOURCE_TOOL_BY_AGENT:
        _exact_object(
            authority,
            {
                "source_tool_id",
                "source_snapshot_hash",
                "candidate_scope_hash",
                "candidate_universe_hash",
                "upstream_accepted_output_refs_hash",
            },
            "Decision runtime authority",
        )
        expected_tool = _DECISION_SOURCE_TOOL_BY_AGENT[agent_id]
        hash_fields = (
            "source_snapshot_hash",
            "candidate_scope_hash",
            "candidate_universe_hash",
            "upstream_accepted_output_refs_hash",
        )
    else:
        raise ValueError(f"{agent_id} cannot carry runtime opportunity authority")
    if authority.get("source_tool_id") != expected_tool:
        raise ValueError(f"{agent_id} runtime authority tool mismatch")
    for field in hash_fields:
        _sha256(authority.get(field), f"runtime_opportunity_authority.{field}")


def _validate_adapter_lineage(
    record: Mapping[str, Any], *, agent_id: str, accepted_kind: str
) -> None:
    lineage = _object(record.get("adapter_lineage"), "adapter_lineage")
    fields = {
        "schema_version",
        "adapter_contract_version",
        "agent_id",
        "accepted_output_kind",
        "source_agent_output_hash",
        "accepted_payload_hash",
        "claim_graph_lineage_hash",
        "adapter_lineage_hash",
    }
    _exact_object(lineage, fields, "adapter_lineage")
    if (
        lineage.get("schema_version") != "accepted_output_adapter_lineage_v1"
        or lineage.get("adapter_contract_version")
        != ACCEPTED_OUTPUT_ADAPTER_CONTRACT_VERSION
        or lineage.get("agent_id") != agent_id
        or lineage.get("accepted_output_kind") != accepted_kind
    ):
        raise ValueError("accepted output adapter lineage identity mismatch")
    for field in (
        "source_agent_output_hash",
        "accepted_payload_hash",
        "claim_graph_lineage_hash",
        "adapter_lineage_hash",
    ):
        _sha256(lineage.get(field), f"adapter_lineage.{field}")
    envelope = _object(record.get("output"), "accepted output envelope")
    payload = _object(envelope.get("payload"), "accepted output payload")
    graph = _object(envelope.get("claim_graph_lineage"), "claim_graph_lineage")
    if (
        lineage["accepted_payload_hash"] != canonical_hash(payload)
        or lineage["claim_graph_lineage_hash"]
        != graph.get("claim_graph_lineage_hash")
    ):
        raise ValueError("accepted output adapter lineage payload mismatch")
    body = {key: value for key, value in lineage.items() if key != "adapter_lineage_hash"}
    if lineage["adapter_lineage_hash"] != canonical_hash(body):
        raise ValueError("accepted output adapter lineage hash mismatch")


def _validate_claim_graph_lineage(
    envelope: Mapping[str, Any],
    *,
    graph_run_id: str,
    payload_claim_evidence: Mapping[str, list[str]],
) -> None:
    lineage = _object(envelope.get("claim_graph_lineage"), "claim_graph_lineage")
    _exact_object(
        lineage,
        {
            "schema_version",
            "run_id",
            "snapshot_hash",
            "evidence",
            "claims",
            "claim_graph_lineage_hash",
        },
        "claim_graph_lineage",
    )
    if (
        lineage.get("schema_version") != "accepted_claim_graph_lineage_v1"
        or lineage.get("run_id") != graph_run_id
    ):
        raise ValueError("accepted claim graph run identity mismatch")
    _sha256(lineage.get("snapshot_hash"), "claim_graph_lineage.snapshot_hash")
    evidence_rows = _list(lineage.get("evidence"), "claim_graph_lineage.evidence")
    if not evidence_rows:
        raise ValueError("accepted claim graph evidence must not be empty")
    evidence_by_id: dict[str, str] = {}
    for index, raw in enumerate(evidence_rows):
        row = _object(raw, f"claim_graph_lineage.evidence[{index}]")
        _exact_object(
            row,
            {"evidence_id", "source_fingerprint"},
            f"claim_graph_lineage.evidence[{index}]",
        )
        evidence_id = _text(row.get("evidence_id"), "evidence_id")
        if evidence_id in evidence_by_id:
            raise ValueError(f"duplicate accepted evidence ID: {evidence_id}")
        evidence_by_id[evidence_id] = _sha256(
            row.get("source_fingerprint"), "source_fingerprint"
        )
    if evidence_rows != sorted(evidence_rows, key=lambda row: row["evidence_id"]):
        raise ValueError("accepted claim graph evidence must be canonically ordered")

    claim_rows = _list(lineage.get("claims"), "claim_graph_lineage.claims")
    lineage_claim_ids: set[str] = set()
    lineage_claim_evidence: dict[str, list[str]] = {}
    for index, raw in enumerate(claim_rows):
        row = _object(raw, f"claim_graph_lineage.claims[{index}]")
        _exact_object(
            row,
            {"claim_id", "evidence_ids"},
            f"claim_graph_lineage.claims[{index}]",
        )
        claim_id = _text(row.get("claim_id"), "claim_id")
        if claim_id in lineage_claim_ids:
            raise ValueError(f"duplicate accepted claim lineage ID: {claim_id}")
        lineage_claim_ids.add(claim_id)
        evidence_ids = _sorted_unique_texts(
            row.get("evidence_ids"), f"{claim_id}.evidence_ids", nonempty=True
        )
        lineage_claim_evidence[claim_id] = evidence_ids
        unresolved = sorted(set(evidence_ids) - set(evidence_by_id))
        if unresolved:
            raise ValueError(f"accepted claim graph has unresolved evidence IDs: {unresolved}")
    if claim_rows != sorted(claim_rows, key=lambda row: row["claim_id"]):
        raise ValueError("accepted claim graph claims must be canonically ordered")
    if lineage_claim_evidence != dict(payload_claim_evidence):
        raise ValueError("accepted payload/claim graph claim evidence mismatch")
    body = {
        key: value for key, value in lineage.items() if key != "claim_graph_lineage_hash"
    }
    if lineage.get("claim_graph_lineage_hash") != canonical_hash(body):
        raise ValueError("accepted claim graph lineage hash mismatch")
    expected_bundle = (
        f"evidence-bundle:{graph_run_id}:"
        f"{str(lineage['snapshot_hash']).removeprefix('sha256:')}"
    )
    if envelope.get("evidence_bundle_ids") != [expected_bundle]:
        raise ValueError("accepted evidence bundle does not close the claim graph")
    expected_causal = sorted(set(evidence_by_id.values()))
    if envelope.get("causal_dedupe_keys") != expected_causal:
        raise ValueError("accepted causal keys do not close the claim graph")


def _validate_payload(
    payload: Mapping[str, Any], *, agent_id: str, accepted_kind: str
) -> dict[str, list[str]]:
    validators = {
        "MACRO_TRANSMISSION": _validate_macro,
        "STANDARD_SECTOR_SELECTION": _validate_sector,
        "RELATIONSHIP_GRAPH": _validate_relationship,
        "SUPERINVESTOR_SELECTION": _validate_superinvestor,
        "CRO_RISK_REVIEW": _validate_cro,
        "ALPHA_DISCOVERY": _validate_alpha,
        "EXECUTION_ASSESSMENT": _validate_execution,
        "CIO_PROPOSAL": _validate_cio_proposal,
        "CIO_FINAL": _validate_cio_final,
    }
    validator = validators.get(accepted_kind)
    if validator is None:
        raise ValueError(f"no server-owned accepted payload schema for {accepted_kind}")
    return validator(payload, agent_id)


def _validate_macro(payload: Mapping[str, Any], agent_id: str) -> dict[str, list[str]]:
    _exact_object(
        payload,
        {
            "agent_id",
            "agent_contract_version",
            "prompt_behavior_version",
            "execution_behavior_version",
            "component_weight_contract_version",
            "direction",
            "strength",
            "persistence_horizon",
            "evaluation_horizon_trading_days",
            "model_confidence",
            "deterministic_data_quality",
            "confidence",
            "channels",
            "claims",
            "claim_refs",
            "key_drivers",
        },
        f"{agent_id} Macro payload",
    )
    if payload.get("agent_id") != agent_id:
        raise ValueError(f"accepted Macro payload owner mismatch for {agent_id}")
    _versions(payload)
    if payload.get("component_weight_contract_version") is not None:
        _text(payload.get("component_weight_contract_version"), "component version")
    _enum(
        payload.get("direction"),
        {"SUPPORTIVE", "NEUTRAL", "ADVERSE"},
        "accepted Macro direction",
    )
    strength = payload.get("strength")
    if isinstance(strength, bool) or not isinstance(strength, int) or strength not in range(6):
        raise ValueError("accepted Macro strength is invalid")
    if (payload["direction"] == "NEUTRAL") != (strength == 0):
        raise ValueError("accepted Macro neutral/strength contract mismatch")
    _enum(payload.get("persistence_horizon"), {"DAYS", "WEEKS", "MONTHS"}, "horizon")
    if payload.get("evaluation_horizon_trading_days") != 5:
        raise ValueError("accepted Macro evaluation horizon must be five trading days")
    _number(payload.get("model_confidence"), "model_confidence", 0, 1)
    _number(payload.get("deterministic_data_quality"), "data_quality", 0, 1)
    _number(payload.get("confidence"), "confidence", 0, 1)
    _text_array(
        payload.get("channels"),
        "channels",
        minimum=1,
        maximum=8,
        text_maximum=96,
        unique=True,
    )
    _text_array(
        payload.get("key_drivers"),
        "key_drivers",
        minimum=1,
        maximum=8,
        text_maximum=160,
    )
    return _claims_and_refs(payload, "Macro payload", max_claims=8, max_refs=8)


def _validate_sector(payload: Mapping[str, Any], agent_id: str) -> dict[str, list[str]]:
    fields = {
        "sector_agent_id",
        "agent_contract_version",
        "prompt_behavior_version",
        "execution_behavior_version",
        "sector_direction_registry_version",
        "sector_direction_registry_hash",
        "selection",
        "accepted_macro_input_attributions",
        "direction_comparison_audit_id",
        "direction_comparison_audit_hash",
        "preferred_security_shortlist_id",
        "preferred_security_shortlist_hash",
        "least_preferred_security_shortlist_id",
        "least_preferred_security_shortlist_hash",
        "security_scoring_contract_version",
        "security_scoring_contract_hash",
        "inference_cost_audit_id",
        "inference_cost_audit_hash",
        "preferred_security_abstention_confidence",
        "least_preferred_security_abstention_confidence",
        "model_confidence",
        "directional_confidence",
    }
    _exact_object(payload, fields, f"{agent_id} Sector payload")
    if payload.get("sector_agent_id") != agent_id:
        raise ValueError(f"accepted Sector payload owner mismatch for {agent_id}")
    _versions(payload)
    for field in (
        "sector_direction_registry_version",
        "direction_comparison_audit_id",
        "preferred_security_shortlist_id",
        "least_preferred_security_shortlist_id",
        "security_scoring_contract_version",
        "inference_cost_audit_id",
    ):
        _text(payload.get(field), field)
    for field in fields:
        if field.endswith("_hash"):
            _sha256(payload.get(field), field)
    for field in ("model_confidence", "directional_confidence"):
        _number(payload.get(field), field, 0, 1)
    for field in (
        "preferred_security_abstention_confidence",
        "least_preferred_security_abstention_confidence",
    ):
        if payload.get(field) is not None:
            _number(payload.get(field), field, 0, 1)
    selection = _object(payload.get("selection"), "Sector selection")
    _exact_object(
        selection,
        {
            "selection_status",
            "preferred_direction",
            "least_preferred_direction",
            "persistence_horizon",
            "key_drivers",
            "risks",
            "claims",
            "claim_refs",
            "preferred_security_status",
            "long_picks",
            "least_preferred_security_status",
            "short_or_avoid_picks",
        },
        "Sector selection",
    )
    if selection.get("selection_status") != "SELECTED":
        raise ValueError("accepted Sector selection must be SELECTED")
    _enum(
        selection.get("persistence_horizon"), {"DAYS", "WEEKS", "MONTHS"}, "horizon"
    )
    claim_evidence = _claims_and_refs(
        selection, "Sector selection", max_claims=14, max_refs=14
    )
    claim_ids = set(claim_evidence)
    preferred = _validate_direction(
        selection.get("preferred_direction"), preferred=True, claim_ids=claim_ids
    )
    least = _validate_direction(
        selection.get("least_preferred_direction"), preferred=False, claim_ids=claim_ids
    )
    if preferred["direction_id"] == least["direction_id"]:
        raise ValueError("preferred and least-preferred Sector directions must differ")
    _validate_drivers(
        selection.get("key_drivers"),
        "driver",
        claim_ids=claim_ids,
        minimum=1,
        maximum=3,
        max_refs=14,
    )
    _validate_drivers(
        selection.get("risks"),
        "risk",
        claim_ids=claim_ids,
        minimum=1,
        maximum=3,
        max_refs=14,
    )
    long_picks = _validate_security_picks(
        selection.get("long_picks"),
        sector=True,
        claim_ids=claim_ids,
        maximum=5,
    )
    short_picks = _validate_security_picks(
        selection.get("short_or_avoid_picks"),
        sector=True,
        claim_ids=claim_ids,
        maximum=5,
    )
    _validate_sector_security_leg(
        status=selection.get("preferred_security_status"),
        abstention_confidence=payload.get("preferred_security_abstention_confidence"),
        picks=long_picks,
        direction_local_id=preferred["direction_local_id"],
        allowed_actions={"LONG"},
        label="preferred",
    )
    _validate_sector_security_leg(
        status=selection.get("least_preferred_security_status"),
        abstention_confidence=payload.get("least_preferred_security_abstention_confidence"),
        picks=short_picks,
        direction_local_id=least["direction_local_id"],
        allowed_actions={"SHORT", "AVOID"},
        label="least preferred",
    )
    combined = long_picks + short_picks
    _unique_field(combined, "pick_local_id", "Sector security picks")
    _unique_field(combined, "ts_code", "Sector security picks")
    if sum(float(row["conviction"]) for row in long_picks) > 1 + 1e-9:
        raise ValueError("preferred Sector conviction sum exceeds one")
    if sum(float(row["conviction"]) for row in short_picks) > 1 + 1e-9:
        raise ValueError("least-preferred Sector conviction sum exceeds one")
    _validate_attributions(
        payload.get("accepted_macro_input_attributions"),
        allowed_target_types={"SUBMISSION_SUMMARY", "SECTOR_THESIS", "SECURITY_PICK"},
        summary_body=selection,
        targets={
            "SECTOR_THESIS": [preferred, least],
            "SECURITY_PICK": combined,
        },
    )
    return claim_evidence


def _validate_relationship(payload: Mapping[str, Any], agent_id: str) -> dict[str, list[str]]:
    fields = {
        "relationship_agent_id",
        "agent_contract_version",
        "prompt_behavior_version",
        "execution_behavior_version",
        "relationship_snapshot_hash",
        "frozen_holder_domain_hash",
        "frozen_security_domain_hash",
        "opportunity_set_id",
        "opportunity_set_hash",
        "factual_edges",
        "predictive_edges",
        "predictive_graph_status",
        "predictive_graph_abstention_confidence",
        "key_drivers",
        "risks",
        "claims",
        "claim_refs",
        "accepted_macro_input_attributions",
        "directional_confidence",
    }
    _exact_object(payload, fields, "Relationship payload")
    if agent_id != "relationship_mapper" or payload.get("relationship_agent_id") != agent_id:
        raise ValueError("accepted Relationship payload owner mismatch")
    _versions(payload)
    _text(payload.get("opportunity_set_id"), "opportunity_set_id")
    for field in fields:
        if field.endswith("_hash"):
            _sha256(payload.get(field), field)
    claim_evidence = _claims_and_refs(
        payload, "Relationship payload", max_claims=14, max_refs=14
    )
    claim_ids = set(claim_evidence)
    _validate_drivers(
        payload.get("key_drivers"),
        "driver",
        claim_ids=claim_ids,
        minimum=1,
        maximum=8,
        max_refs=14,
    )
    _validate_drivers(
        payload.get("risks"),
        "risk",
        claim_ids=claim_ids,
        minimum=1,
        maximum=8,
        max_refs=14,
    )
    _number(payload.get("directional_confidence"), "directional_confidence", 0, 1)
    if payload.get("predictive_graph_abstention_confidence") is not None:
        _number(
            payload.get("predictive_graph_abstention_confidence"),
            "predictive_graph_abstention_confidence",
            0,
            1,
        )
    factual_edges: list[Mapping[str, Any]] = []
    for index, raw in enumerate(
        _bounded_list(payload.get("factual_edges"), "factual_edges", maximum=32)
    ):
        edge = _object(raw, f"factual_edges[{index}]")
        _exact_object(
            edge,
            {
                "edge_id",
                "edge_hash",
                "edge_candidate_id",
                "relationship_row_hash",
                "source_entity",
                "source_entity_type",
                "target_entity",
                "target_entity_type",
                "target_sector_id",
                "edge_type",
                "activation_trigger",
                "evidence_ids",
                "claim_refs",
            },
            f"factual_edges[{index}]",
        )
        edge_id = _text(edge.get("edge_id"), "edge_id")
        edge_hash = _sha256(edge.get("edge_hash"), "edge_hash")
        _text(edge.get("edge_candidate_id"), "edge_candidate_id", maximum=128)
        _sha256(edge.get("relationship_row_hash"), "relationship_row_hash")
        _text(edge.get("source_entity"), "source_entity", maximum=128)
        if edge.get("source_entity_type") != "HOLDER":
            raise ValueError("factual relationship source_entity_type must be HOLDER")
        _text(edge.get("target_entity"), "target_entity", maximum=128)
        if edge.get("target_entity_type") != "PIT_ELIGIBLE_SECURITY":
            raise ValueError(
                "factual relationship target_entity_type must be PIT_ELIGIBLE_SECURITY"
            )
        _text(edge.get("target_sector_id"), "target_sector_id", maximum=128)
        _text(edge.get("edge_type"), "edge_type", maximum=128)
        _text(edge.get("activation_trigger"), "activation_trigger", maximum=320)
        _text_array(
            edge.get("evidence_ids"),
            "edge evidence",
            minimum=1,
            maximum=16,
            text_maximum=256,
            unique=True,
        )
        _claim_refs(
            edge.get("claim_refs"),
            "factual edge claim_refs",
            claim_ids,
            minimum=1,
            maximum=14,
        )
        fact_body = {
            key: edge[key]
            for key in (
                "edge_candidate_id",
                "relationship_row_hash",
                "source_entity",
                "source_entity_type",
                "target_entity",
                "target_entity_type",
                "target_sector_id",
                "edge_type",
                "activation_trigger",
                "evidence_ids",
            )
        }
        if edge_hash != canonical_hash(fact_body) or edge_id != f"relationship-factual-edge:{edge_hash[7:]}":
            raise ValueError("factual relationship edge identity mismatch")
        factual_edges.append(edge)
    predictive_edges: list[Mapping[str, Any]] = []
    for index, raw in enumerate(
        _bounded_list(payload.get("predictive_edges"), "predictive_edges", maximum=32)
    ):
        edge = _object(raw, f"predictive_edges[{index}]")
        _exact_object(
            edge,
            {
                "edge_id",
                "edge_hash",
                "edge_candidate_id",
                "source_entity",
                "target_entity",
                "edge_type",
                "transmission_direction",
                "activation_trigger",
                "evaluation_horizon_trading_days",
                "model_confidence",
                "calibrated_confidence",
                "calibration_state_id",
                "calibration_state_effective_at",
                "claim_refs",
            },
            f"predictive_edges[{index}]",
        )
        edge_id = _text(edge.get("edge_id"), "edge_id")
        edge_hash = _sha256(edge.get("edge_hash"), "edge_hash")
        for field in ("edge_candidate_id", "source_entity", "target_entity", "edge_type"):
            _text(edge.get(field), field, maximum=128)
        _enum(
            edge.get("transmission_direction"),
            {"POSITIVE", "NEGATIVE", "MIXED"},
            "transmission_direction",
        )
        _text(edge.get("activation_trigger"), "activation_trigger", maximum=320)
        if edge.get("evaluation_horizon_trading_days") != 20:
            raise ValueError("relationship evaluation horizon must be 20 trading days")
        model_confidence = _number(edge.get("model_confidence"), "model_confidence", 0, 1)
        calibrated_confidence = _number(
            edge.get("calibrated_confidence"), "calibrated_confidence", 0, 1
        )
        if abs(model_confidence - calibrated_confidence) > 1e-12:
            raise ValueError("relationship cold-start calibrated confidence mismatch")
        _text(edge.get("calibration_state_id"), "calibration_state_id")
        _text(edge.get("calibration_state_effective_at"), "calibration_state_effective_at")
        _claim_refs(
            edge.get("claim_refs"),
            "predictive edge claim_refs",
            claim_ids,
            minimum=1,
            maximum=14,
        )
        predictive_body = {
            key: edge[key]
            for key in (
                "edge_candidate_id",
                "source_entity",
                "target_entity",
                "edge_type",
                "transmission_direction",
                "activation_trigger",
                "evaluation_horizon_trading_days",
                "model_confidence",
                "calibrated_confidence",
                "calibration_state_id",
                "calibration_state_effective_at",
                "claim_refs",
            )
        }
        if (
            edge_hash != canonical_hash(predictive_body)
            or edge_id != f"relationship-predictive-edge:{edge_hash[7:]}"
        ):
            raise ValueError("predictive relationship edge identity mismatch")
        predictive_edges.append(edge)
    _unique_field(factual_edges, "edge_id", "factual_edges")
    _unique_field(factual_edges, "edge_hash", "factual_edges")
    _unique_fields(
        factual_edges,
        ("source_entity", "target_entity", "edge_type"),
        "factual_edges",
    )
    _unique_field(predictive_edges, "edge_candidate_id", "predictive_edges")
    _unique_fields(
        predictive_edges,
        ("source_entity", "target_entity", "edge_type"),
        "predictive_edges",
    )
    graph_status = _enum(
        payload.get("predictive_graph_status"),
        {"EDGES_PRESENT", "NO_QUALIFIED_PREDICTIVE_EDGE"},
        "predictive_graph_status",
    )
    abstention = payload.get("predictive_graph_abstention_confidence")
    if graph_status == "EDGES_PRESENT":
        if not predictive_edges or abstention is not None:
            raise ValueError("EDGES_PRESENT requires predictive edges and null abstention")
    elif predictive_edges or abstention is None:
        raise ValueError(
            "NO_QUALIFIED_PREDICTIVE_EDGE requires no predictive edges and abstention confidence"
        )
    if not predictive_edges and payload.get("directional_confidence") != 0:
        raise ValueError("empty predictive graph must have zero directional confidence")
    _validate_attributions(
        payload.get("accepted_macro_input_attributions"),
        allowed_target_types={"SUBMISSION_SUMMARY"},
        summary_body={
            key: item
            for key, item in payload.items()
            if key != "accepted_macro_input_attributions"
        },
        targets={},
    )
    return claim_evidence


def _validate_superinvestor(payload: Mapping[str, Any], agent_id: str) -> dict[str, list[str]]:
    _exact_object(
        payload,
        {
            "superinvestor_agent_id",
            "agent_contract_version",
            "prompt_behavior_version",
            "execution_behavior_version",
            "selection",
            "accepted_macro_input_attributions",
            "model_confidence",
            "directional_confidence",
            "abstention_confidence",
        },
        f"{agent_id} Superinvestor payload",
    )
    if payload.get("superinvestor_agent_id") != agent_id:
        raise ValueError(f"accepted Superinvestor payload owner mismatch for {agent_id}")
    _versions(payload)
    for field in ("model_confidence", "directional_confidence", "abstention_confidence"):
        _number(payload.get(field), field, 0, 1)
    selection = _object(payload.get("selection"), "Superinvestor selection")
    _exact_object(
        selection,
        {
            "selection_status",
            "holding_period",
            "picks",
            "key_drivers",
            "risks",
            "claims",
            "claim_refs",
        },
        "Superinvestor selection",
    )
    claim_evidence = _claims_and_refs(
        selection, "Superinvestor selection", max_claims=10, max_refs=6
    )
    claim_ids = set(claim_evidence)
    _enum(selection.get("holding_period"), {"WEEKS", "MONTHS", "YEARS"}, "holding_period")
    picks = _validate_security_picks(
        selection.get("picks"),
        sector=False,
        claim_ids=claim_ids,
        maximum=10,
    )
    _validate_drivers(
        selection.get("key_drivers"),
        "driver",
        claim_ids=claim_ids,
        minimum=1,
        maximum=5,
        max_refs=6,
    )
    _validate_drivers(
        selection.get("risks"),
        "risk",
        claim_ids=claim_ids,
        minimum=1,
        maximum=5,
        max_refs=6,
    )
    _unique_field(picks, "pick_local_id", "Superinvestor picks")
    _unique_field(picks, "ts_code", "Superinvestor picks")
    if sum(float(row["conviction"]) for row in picks) > 1 + 1e-12:
        raise ValueError("Superinvestor conviction sum exceeds one")
    status = _enum(
        selection.get("selection_status"),
        {"SELECTED", "NO_QUALIFIED_CANDIDATES"},
        "Superinvestor selection_status",
    )
    if status == "SELECTED":
        if not picks:
            raise ValueError("selected Superinvestor output requires picks")
        if (
            payload.get("directional_confidence") != payload.get("model_confidence")
            or payload.get("abstention_confidence") != 0
        ):
            raise ValueError("selected Superinvestor confidence semantics mismatch")
    else:
        if picks:
            raise ValueError("abstaining Superinvestor output cannot contain picks")
        if (
            payload.get("directional_confidence") != 0
            or payload.get("abstention_confidence") != payload.get("model_confidence")
        ):
            raise ValueError("abstaining Superinvestor confidence semantics mismatch")
    _validate_attributions(
        payload.get("accepted_macro_input_attributions"),
        allowed_target_types={"SUBMISSION_SUMMARY", "SECURITY_PICK"},
        summary_body=selection,
        targets={"SECURITY_PICK": picks},
    )
    return claim_evidence


def _validate_cro(payload: Mapping[str, Any], agent_id: str) -> dict[str, list[str]]:
    _exact_object(
        payload,
        {
            "agent_id",
            "agent_contract_version",
            "prompt_behavior_version",
            "execution_behavior_version",
            "accepted_cro_review_id",
            "accepted_cro_review_hash",
            "frozen_proposal_id",
            "frozen_proposal_hash",
            "frozen_candidate_universe_id",
            "frozen_candidate_universe_hash",
            "review",
            "accepted_macro_input_attributions",
            "model_confidence",
        },
        "CRO payload",
    )
    _decision_owner_versions(payload, agent_id, "cro")
    for field in (
        "accepted_cro_review_id",
        "frozen_proposal_id",
        "frozen_candidate_universe_id",
    ):
        _text(payload.get(field), field)
    for field in (
        "accepted_cro_review_hash",
        "frozen_proposal_hash",
        "frozen_candidate_universe_hash",
    ):
        _sha256(payload.get(field), field)
    review = _object(payload.get("review"), "CRO review")
    _exact_object(
        review,
        {
            "review_disposition",
            "candidate_actions",
            "correlated_risks",
            "black_swan_scenarios",
            "claims",
            "claim_refs",
        },
        "CRO review",
    )
    claim_evidence = _claims_and_refs(review, "CRO review", max_claims=10, max_refs=10)
    claim_ids = set(claim_evidence)
    actions: list[Mapping[str, Any]] = []
    raw_actions: list[Mapping[str, Any]] = []
    for index, raw in enumerate(
        _bounded_list(review.get("candidate_actions"), "candidate_actions", maximum=50)
    ):
        action = _object(raw, f"candidate_actions[{index}]")
        _exact_object(
            action,
            {
                "action_local_id",
                "candidate_ref",
                "ts_code",
                "action",
                "predicted_risk_probability",
                "max_target_weight",
                "reason",
                "claim_refs",
                "cro_action_ref",
                "cro_action_hash",
            },
            f"candidate_actions[{index}]",
        )
        for field in ("action_local_id", "candidate_ref"):
            _text(action.get(field), field, maximum=128)
        _ts_code(action.get("ts_code"), "CRO action ts_code", strict_a_share=False)
        action_kind = _enum(
            action.get("action"),
            {"VETO", "CAP_WEIGHT", "REDUCE_WEIGHT", "REQUIRE_REVIEW", "NO_OBJECTION"},
            "CRO action",
        )
        _number(action.get("predicted_risk_probability"), "risk probability", 0, 1)
        max_weight = action.get("max_target_weight")
        if max_weight is not None:
            _number(max_weight, "max_target_weight", 0, 1)
        if action_kind == "VETO" and max_weight != 0:
            raise ValueError("CRO VETO requires max_target_weight=0")
        if action_kind in {"NO_OBJECTION", "REQUIRE_REVIEW"} and max_weight is not None:
            raise ValueError(f"CRO {action_kind} requires null max_target_weight")
        if action_kind in {"CAP_WEIGHT", "REDUCE_WEIGHT"} and max_weight is None:
            raise ValueError(f"CRO {action_kind} requires max_target_weight")
        _text(action.get("reason"), "CRO action reason", maximum=320)
        _claim_refs(
            action.get("claim_refs"),
            "CRO action claim_refs",
            claim_ids,
            minimum=1,
            maximum=10,
        )
        action_hash = _sha256(action.get("cro_action_hash"), "cro_action_hash")
        action_ref = _text(action.get("cro_action_ref"), "cro_action_ref")
        raw_action = {
            key: action[key]
            for key in action
            if key not in {"cro_action_ref", "cro_action_hash"}
        }
        expected_hash = canonical_hash(
            {
                "accepted_cro_review_id": payload["accepted_cro_review_id"],
                "action_local_id": action["action_local_id"],
                "action": raw_action,
            }
        )
        if action_hash != expected_hash or action_ref != f"cro-action:{expected_hash[7:]}":
            raise ValueError("accepted CRO action identity mismatch")
        actions.append(action)
        raw_actions.append(raw_action)
    for field in ("action_local_id", "candidate_ref", "ts_code"):
        _unique_field(actions, field, "CRO candidate_actions")
    if actions != sorted(actions, key=lambda row: str(row["action_local_id"])):
        raise ValueError("accepted CRO actions must be ordered by action_local_id")
    _validate_drivers(
        review.get("correlated_risks"),
        "risk",
        claim_ids=claim_ids,
        minimum=0,
        maximum=10,
        max_refs=10,
    )
    _validate_drivers(
        review.get("black_swan_scenarios"),
        "risk",
        claim_ids=claim_ids,
        minimum=0,
        maximum=10,
        max_refs=10,
    )
    derived = (
        "BLOCK_ALL"
        if actions and all(action["action"] == "VETO" for action in actions)
        else "NO_OBJECTION"
        if all(action["action"] == "NO_OBJECTION" for action in actions)
        else "REVIEW_ACTIONS"
    )
    if review.get("review_disposition") != derived:
        raise ValueError(f"CRO review_disposition must be {derived}")
    raw_review = {
        **review,
        "candidate_actions": raw_actions,
    }
    _validate_attributions(
        payload.get("accepted_macro_input_attributions"),
        allowed_target_types={"SUBMISSION_SUMMARY", "RISK_ACTION"},
        summary_body=raw_review,
        targets={"RISK_ACTION": raw_actions},
    )
    expected_id = _persistent_id(
        "accepted-cro-review",
        {
            "agent_id": "cro",
            "frozen_proposal_id": payload["frozen_proposal_id"],
            "frozen_proposal_hash": payload["frozen_proposal_hash"],
            "frozen_candidate_universe_id": payload["frozen_candidate_universe_id"],
            "frozen_candidate_universe_hash": payload[
                "frozen_candidate_universe_hash"
            ],
            "review": raw_review,
            "accepted_macro_input_attributions": payload[
                "accepted_macro_input_attributions"
            ],
        },
    )
    if payload["accepted_cro_review_id"] != expected_id:
        raise ValueError("accepted CRO review ID mismatch")
    if payload["accepted_cro_review_hash"] != canonical_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "accepted_cro_review_hash"
        }
    ):
        raise ValueError("accepted CRO review hash mismatch")
    return claim_evidence


def _validate_alpha(payload: Mapping[str, Any], agent_id: str) -> dict[str, list[str]]:
    _exact_object(
        payload,
        {
            "agent_id",
            "agent_contract_version",
            "prompt_behavior_version",
            "execution_behavior_version",
            "accepted_alpha_discovery_id",
            "accepted_alpha_discovery_hash",
            "frozen_novel_candidate_universe_id",
            "frozen_novel_candidate_universe_hash",
            "selection",
            "accepted_macro_input_attributions",
            "model_confidence",
        },
        "Alpha payload",
    )
    _decision_owner_versions(payload, agent_id, "alpha_discovery")
    _text(payload.get("accepted_alpha_discovery_id"), "accepted alpha id")
    _text(payload.get("frozen_novel_candidate_universe_id"), "frozen universe id")
    _sha256(payload.get("accepted_alpha_discovery_hash"), "accepted alpha hash")
    _sha256(payload.get("frozen_novel_candidate_universe_hash"), "frozen universe hash")
    selection = _object(payload.get("selection"), "Alpha selection")
    _exact_object(
        selection,
        {
            "discovery_disposition",
            "novel_picks",
            "key_drivers",
            "risks",
            "claims",
            "claim_refs",
        },
        "Alpha selection",
    )
    claim_evidence = _claims_and_refs(selection, "Alpha selection", max_claims=10, max_refs=10)
    claim_ids = set(claim_evidence)
    picks: list[Mapping[str, Any]] = []
    for index, raw in enumerate(
        _bounded_list(selection.get("novel_picks"), "novel_picks", maximum=10)
    ):
        pick = _object(raw, f"novel_picks[{index}]")
        _exact_object(
            pick,
            {"pick_local_id", "candidate_ref", "ts_code", "conviction", "thesis", "claim_refs"},
            f"novel_picks[{index}]",
        )
        _text(pick.get("pick_local_id"), "pick_local_id", maximum=128)
        _text(pick.get("candidate_ref"), "candidate_ref", maximum=128)
        _ts_code(pick.get("ts_code"), "Alpha pick ts_code", strict_a_share=False)
        _number(pick.get("conviction"), "Alpha conviction", 0, 1)
        _text(pick.get("thesis"), "Alpha thesis", maximum=320)
        _claim_refs(
            pick.get("claim_refs"),
            "Alpha pick claim_refs",
            claim_ids,
            minimum=1,
            maximum=10,
        )
        picks.append(pick)
    for field in ("pick_local_id", "candidate_ref", "ts_code"):
        _unique_field(picks, field, "Alpha novel_picks")
    disposition = _enum(
        selection.get("discovery_disposition"),
        {"CANDIDATES", "NONE_FOUND"},
        "Alpha discovery_disposition",
    )
    if (disposition == "CANDIDATES") != bool(picks):
        raise ValueError("Alpha discovery disposition/picks mismatch")
    _validate_drivers(
        selection.get("key_drivers"),
        "driver",
        claim_ids=claim_ids,
        minimum=0,
        maximum=10,
        max_refs=10,
    )
    _validate_drivers(
        selection.get("risks"),
        "risk",
        claim_ids=claim_ids,
        minimum=0,
        maximum=10,
        max_refs=10,
    )
    _validate_attributions(
        payload.get("accepted_macro_input_attributions"),
        allowed_target_types={"SUBMISSION_SUMMARY", "SECURITY_PICK"},
        summary_body=selection,
        targets={"SECURITY_PICK": picks},
    )
    expected_id = _persistent_id(
        "accepted-alpha-discovery",
        {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "accepted_alpha_discovery_id",
                "accepted_alpha_discovery_hash",
            }
        },
    )
    if payload["accepted_alpha_discovery_id"] != expected_id:
        raise ValueError("accepted Alpha discovery ID mismatch")
    if payload["accepted_alpha_discovery_hash"] != canonical_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "accepted_alpha_discovery_hash"
        }
    ):
        raise ValueError("accepted Alpha discovery hash mismatch")
    return claim_evidence


def _validate_execution(payload: Mapping[str, Any], agent_id: str) -> dict[str, list[str]]:
    _exact_object(
        payload,
        {
            "agent_id",
            "agent_contract_version",
            "prompt_behavior_version",
            "execution_behavior_version",
            "accepted_execution_assessment_id",
            "accepted_execution_assessment_hash",
            "execution_mode",
            "frozen_proposal_id",
            "frozen_proposal_hash",
            "cro_control_source",
            "frozen_order_intent_set_id",
            "frozen_order_intent_set_hash",
            "assessment",
            "model_confidence",
        },
        "Execution payload",
    )
    _decision_owner_versions(payload, agent_id, "autonomous_execution")
    for field in (
        "accepted_execution_assessment_id",
        "frozen_proposal_id",
        "frozen_order_intent_set_id",
    ):
        _text(payload.get(field), field)
    for field in (
        "accepted_execution_assessment_hash",
        "frozen_proposal_hash",
        "frozen_order_intent_set_hash",
    ):
        _sha256(payload.get(field), field)
    _enum(payload.get("execution_mode"), {"PAPER", "REAL"}, "execution_mode")
    _validate_control_source(payload.get("cro_control_source"), "cro", "CRO_RISK_REVIEW")
    assessment = _object(payload.get("assessment"), "Execution assessment")
    _exact_object(
        assessment,
        {"execution_disposition", "order_assessments", "claims", "claim_refs"},
        "Execution assessment",
    )
    claim_evidence = _claims_and_refs(
        assessment, "Execution assessment", max_claims=10, max_refs=10
    )
    claim_ids = set(claim_evidence)
    assessments: list[Mapping[str, Any]] = []
    raw_assessments: list[Mapping[str, Any]] = []
    for index, raw in enumerate(
        _bounded_list(
            assessment.get("order_assessments"),
            "order assessments",
            minimum=1,
            maximum=50,
        )
    ):
        row = _object(raw, f"order_assessments[{index}]")
        _exact_object(
            row,
            {
                "assessment_local_id",
                "order_intent_ref",
                "ts_code",
                "requested_delta_weight",
                "feasibility",
                "feasibility_confidence",
                "predicted_cost_bps",
                "max_executable_delta_weight",
                "recommended_slice_count",
                "reason",
                "claim_refs",
                "execution_assessment_ref",
                "execution_assessment_hash",
            },
            f"order_assessments[{index}]",
        )
        for field in ("assessment_local_id", "order_intent_ref"):
            _text(row.get(field), field, maximum=128)
        _ts_code(row.get("ts_code"), "execution ts_code", strict_a_share=False)
        requested = _number(row.get("requested_delta_weight"), "requested_delta_weight", -1, 1)
        if requested == 0:
            raise ValueError("requested_delta_weight must be non-zero")
        feasibility = _enum(
            row.get("feasibility"), {"FEASIBLE", "PARTIAL", "BLOCKED"}, "feasibility"
        )
        _number(row.get("feasibility_confidence"), "feasibility_confidence", 0, 1)
        _number(row.get("predicted_cost_bps"), "predicted_cost_bps", 0, 10_000)
        executable = row.get("max_executable_delta_weight")
        if executable is not None:
            executable = _number(executable, "max_executable_delta_weight", 0, 1)
        slices = _integer(row.get("recommended_slice_count"), "recommended_slice_count", 0, 100)
        if feasibility == "BLOCKED":
            if executable != 0 or slices != 0:
                raise ValueError("BLOCKED execution requires zero executable delta and slices")
        elif feasibility == "PARTIAL":
            if executable is None or executable <= 0 or executable >= abs(requested) or slices < 1:
                raise ValueError("PARTIAL execution has invalid executable delta or slice count")
        elif executable is None or executable < abs(requested) or slices < 1:
            raise ValueError("FEASIBLE execution has invalid executable delta or slice count")
        _text(row.get("reason"), "execution reason", maximum=320)
        _claim_refs(
            row.get("claim_refs"),
            "execution assessment claim_refs",
            claim_ids,
            minimum=1,
            maximum=10,
        )
        assessment_hash = _sha256(
            row.get("execution_assessment_hash"), "execution_assessment_hash"
        )
        assessment_ref = _text(
            row.get("execution_assessment_ref"), "execution_assessment_ref"
        )
        raw_assessment = {
            key: row[key]
            for key in row
            if key not in {"execution_assessment_ref", "execution_assessment_hash"}
        }
        expected_hash = canonical_hash(
            {
                "accepted_execution_assessment_id": payload[
                    "accepted_execution_assessment_id"
                ],
                "assessment_local_id": row["assessment_local_id"],
                "assessment": raw_assessment,
            }
        )
        if (
            assessment_hash != expected_hash
            or assessment_ref != f"execution-assessment:{expected_hash[7:]}"
        ):
            raise ValueError("accepted execution assessment identity mismatch")
        assessments.append(row)
        raw_assessments.append(raw_assessment)
    for field in ("assessment_local_id", "order_intent_ref", "ts_code"):
        _unique_field(assessments, field, "execution order_assessments")
    if assessments != sorted(assessments, key=lambda row: str(row["assessment_local_id"])):
        raise ValueError("accepted execution assessments must be ordered by assessment_local_id")
    disposition = _enum(
        assessment.get("execution_disposition"),
        {"ORDERS_ASSESSED", "BLOCKED"},
        "execution_disposition",
    )
    if (disposition == "BLOCKED") != all(row["feasibility"] == "BLOCKED" for row in assessments):
        raise ValueError("execution_disposition does not match order assessments")
    raw_payload = {**assessment, "order_assessments": raw_assessments}
    expected_id = _persistent_id(
        "accepted-execution-assessment",
        {
            "agent_id": "autonomous_execution",
            "frozen_proposal_id": payload["frozen_proposal_id"],
            "frozen_proposal_hash": payload["frozen_proposal_hash"],
            "cro_control_source": payload["cro_control_source"],
            "frozen_order_intent_set_id": payload["frozen_order_intent_set_id"],
            "frozen_order_intent_set_hash": payload["frozen_order_intent_set_hash"],
            "assessment": raw_payload,
        },
    )
    if payload["accepted_execution_assessment_id"] != expected_id:
        raise ValueError("accepted Execution assessment ID mismatch")
    if payload["accepted_execution_assessment_hash"] != canonical_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "accepted_execution_assessment_hash"
        }
    ):
        raise ValueError("accepted Execution assessment hash mismatch")
    return claim_evidence


def _validate_cio_proposal(payload: Mapping[str, Any], agent_id: str) -> dict[str, list[str]]:
    _exact_object(
        payload,
        {
            "agent_id",
            "decision_stage",
            "agent_contract_version",
            "prompt_behavior_version",
            "execution_behavior_version",
            "frozen_pre_cio_input_id",
            "frozen_pre_cio_input_hash",
            "alpha_source",
            "alpha_pick_resolutions",
            "proposal_id",
            "proposal_hash",
            "decision",
            "accepted_macro_input_attributions",
            "model_confidence",
        },
        "CIO proposal payload",
    )
    _decision_owner_versions(payload, agent_id, "cio")
    if payload.get("decision_stage") != "PROPOSAL":
        raise ValueError("CIO proposal stage mismatch")
    for field in ("frozen_pre_cio_input_id", "proposal_id"):
        _text(payload.get(field), field)
    _sha256(payload.get("frozen_pre_cio_input_hash"), "frozen_pre_cio_input_hash")
    _sha256(payload.get("proposal_hash"), "proposal_hash")
    _validate_control_source(payload.get("alpha_source"), "alpha_discovery", "ALPHA_DISCOVERY")
    decision = _object(payload.get("decision"), "CIO proposal decision")
    claim_evidence = _validate_cio_decision(decision, "CIO proposal decision")
    positions = decision.get("target_positions")
    position_rows = [
        _object(row, "CIO proposal target position")
        for row in _list(positions, "CIO proposal target positions")
    ]
    position_refs = {
        str(row["position_local_id"])
        for row in position_rows
    }
    resolutions: list[Mapping[str, Any]] = []
    for index, raw in enumerate(
        _bounded_list(payload.get("alpha_pick_resolutions"), "alpha resolutions", maximum=10)
    ):
        row = _object(raw, f"alpha_pick_resolutions[{index}]")
        _exact_object(
            row,
            {
                "alpha_pick_local_ref",
                "ts_code",
                "resolution",
                "target_position_local_ref",
                "reason",
            },
            f"alpha_pick_resolutions[{index}]",
        )
        _text(row.get("alpha_pick_local_ref"), "alpha_pick_local_ref", maximum=128)
        _ts_code(row.get("ts_code"), "Alpha resolution ts_code", strict_a_share=False)
        resolution = _enum(
            row.get("resolution"), {"INCLUDED", "NOT_INCLUDED"}, "Alpha resolution"
        )
        target_ref = row.get("target_position_local_ref")
        if target_ref is not None:
            _text(target_ref, "target_position_local_ref", maximum=128)
        if (resolution == "INCLUDED") != (target_ref is not None):
            raise ValueError("Alpha resolution/target position contract mismatch")
        if target_ref is not None and target_ref not in position_refs:
            raise ValueError("Alpha resolution target position is unresolved")
        _text(row.get("reason"), "Alpha resolution reason", maximum=320)
        resolutions.append(row)
    _unique_field(resolutions, "alpha_pick_local_ref", "alpha_pick_resolutions")
    _unique_field(resolutions, "ts_code", "alpha_pick_resolutions")
    if resolutions != sorted(resolutions, key=lambda row: str(row["alpha_pick_local_ref"])):
        raise ValueError("Alpha pick resolutions must be ordered by local ref")
    _validate_attributions(
        payload.get("accepted_macro_input_attributions"),
        allowed_target_types={"SUBMISSION_SUMMARY", "PORTFOLIO_DECISION"},
        summary_body=decision,
        targets={"PORTFOLIO_DECISION": position_rows},
    )
    expected_id = _persistent_id(
        "cio-proposal",
        {
            key: value
            for key, value in payload.items()
            if key not in {"proposal_id", "proposal_hash"}
        },
    )
    if payload["proposal_id"] != expected_id:
        raise ValueError("accepted CIO proposal ID mismatch")
    if payload["proposal_hash"] != canonical_hash(
        {key: value for key, value in payload.items() if key != "proposal_hash"}
    ):
        raise ValueError("accepted CIO proposal hash mismatch")
    return claim_evidence


def _validate_cio_final(payload: Mapping[str, Any], agent_id: str) -> dict[str, list[str]]:
    _exact_object(
        payload,
        {
            "agent_id",
            "decision_stage",
            "agent_contract_version",
            "prompt_behavior_version",
            "execution_behavior_version",
            "frozen_proposal_id",
            "frozen_proposal_hash",
            "cro_control_source",
            "execution_control_source",
            "frozen_controlled_target_set_id",
            "frozen_controlled_target_set_hash",
            "final_portfolio_id",
            "final_portfolio_hash",
            "decision",
            "cro_control_resolutions",
            "execution_control_resolutions",
            "accepted_macro_input_attributions",
            "model_confidence",
        },
        "CIO final payload",
    )
    _decision_owner_versions(payload, agent_id, "cio")
    if payload.get("decision_stage") != "FINAL":
        raise ValueError("CIO final stage mismatch")
    for field in (
        "frozen_proposal_id",
        "frozen_controlled_target_set_id",
        "final_portfolio_id",
    ):
        _text(payload.get(field), field)
    for field in (
        "frozen_proposal_hash",
        "frozen_controlled_target_set_hash",
        "final_portfolio_hash",
    ):
        _sha256(payload.get(field), field)
    _validate_control_source(payload.get("cro_control_source"), "cro", "CRO_RISK_REVIEW")
    _validate_control_source(
        payload.get("execution_control_source"),
        "autonomous_execution",
        "EXECUTION_ASSESSMENT",
    )
    decision = _object(payload.get("decision"), "CIO final decision")
    claim_evidence = _validate_cio_decision(decision, "CIO final decision")
    claim_ids = set(claim_evidence)
    _validate_control_resolutions(
        payload.get("cro_control_resolutions"), cro=True, claim_ids=claim_ids
    )
    _validate_control_resolutions(
        payload.get("execution_control_resolutions"), cro=False, claim_ids=claim_ids
    )
    position_rows = [
        _object(row, "CIO final target position")
        for row in _list(decision.get("target_positions"), "CIO final target positions")
    ]
    _validate_attributions(
        payload.get("accepted_macro_input_attributions"),
        allowed_target_types={"SUBMISSION_SUMMARY", "PORTFOLIO_DECISION"},
        summary_body=decision,
        targets={"PORTFOLIO_DECISION": position_rows},
    )
    expected_id = _persistent_id(
        "cio-final-portfolio",
        {
            key: value
            for key, value in payload.items()
            if key not in {"final_portfolio_id", "final_portfolio_hash"}
        },
    )
    if payload["final_portfolio_id"] != expected_id:
        raise ValueError("accepted CIO final portfolio ID mismatch")
    if payload["final_portfolio_hash"] != canonical_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "final_portfolio_hash"
        }
    ):
        raise ValueError("accepted CIO final portfolio hash mismatch")
    return claim_evidence


def _validate_cio_decision(value: Any, label: str) -> dict[str, list[str]]:
    decision = _object(value, label)
    _exact_object(
        decision,
        {
            "decision_disposition",
            "target_positions",
            "cash_weight",
            "decision_reason",
            "claims",
            "claim_refs",
        },
        label,
    )
    claim_evidence = _claims_and_refs(decision, label, max_claims=10, max_refs=10)
    claim_ids = set(claim_evidence)
    positions: list[Mapping[str, Any]] = []
    for index, raw in enumerate(
        _bounded_list(decision.get("target_positions"), "target positions", maximum=50)
    ):
        row = _object(raw, f"target_positions[{index}]")
        _exact_object(
            row,
            {
                "position_local_id",
                "ts_code",
                "target_weight",
                "position_decision",
                "holding_period",
                "thesis_status",
                "risk_flags",
                "claim_refs",
            },
            f"target_positions[{index}]",
        )
        _text(row.get("position_local_id"), "position_local_id", maximum=128)
        _ts_code(row.get("ts_code"), "CIO position ts_code", strict_a_share=False)
        target_weight = _number(row.get("target_weight"), "target_weight", 0, 1)
        position_decision = _enum(
            row.get("position_decision"),
            {"HOLD", "ADD", "REDUCE", "EXIT"},
            "position_decision",
        )
        if position_decision == "EXIT" and target_weight != 0:
            raise ValueError("CIO EXIT requires target_weight=0")
        _enum(row.get("holding_period"), {"DAYS", "WEEKS", "MONTHS"}, "holding_period")
        _enum(
            row.get("thesis_status"),
            {"INTACT", "WEAKENED", "BROKEN", "EXPIRED"},
            "thesis_status",
        )
        _text_array(
            row.get("risk_flags"),
            "risk_flags",
            maximum=20,
            text_maximum=128,
        )
        _claim_refs(
            row.get("claim_refs"),
            "CIO position claim_refs",
            claim_ids,
            minimum=1,
            maximum=10,
        )
        positions.append(row)
    _unique_field(positions, "position_local_id", "CIO target_positions")
    _unique_field(positions, "ts_code", "CIO target_positions")
    cash_weight = _number(decision.get("cash_weight"), "cash_weight", 0, 1)
    if abs(cash_weight + sum(float(row["target_weight"]) for row in positions) - 1) > 1e-9:
        raise ValueError("CIO target weights plus cash must equal one")
    disposition = _enum(
        decision.get("decision_disposition"),
        {"TARGET_PORTFOLIO", "HOLD_CURRENT", "ALL_CASH"},
        "decision_disposition",
    )
    if disposition == "TARGET_PORTFOLIO" and not positions:
        raise ValueError("TARGET_PORTFOLIO requires target positions")
    if disposition == "ALL_CASH" and (positions or cash_weight != 1):
        raise ValueError("ALL_CASH requires no positions and cash_weight=1")
    _text(decision.get("decision_reason"), "decision_reason", maximum=320)
    return claim_evidence


def _validate_control_source(value: Any, owner: str, kind: str) -> None:
    source = _object(value, f"{owner} control source")
    _exact_object(
        source,
        {
            "source_status",
            "agent_id",
            "accepted_output_id",
            "accepted_output_hash",
            "stage_skip_id",
            "stage_skip_hash",
        },
        f"{owner} control source",
    )
    if source.get("agent_id") != owner:
        raise ValueError(f"{owner} control source owner mismatch")
    if source.get("source_status") == "ACCEPTED_OUTPUT":
        _text(source.get("accepted_output_id"), "accepted_output_id")
        _sha256(source.get("accepted_output_hash"), "accepted_output_hash")
        if source.get("stage_skip_id") is not None or source.get("stage_skip_hash") is not None:
            raise ValueError(f"{owner} accepted control source carries a stage skip")
    elif source.get("source_status") == "NO_EVALUATION_OBJECT":
        _text(source.get("stage_skip_id"), "stage_skip_id")
        _sha256(source.get("stage_skip_hash"), "stage_skip_hash")
        if (
            source.get("accepted_output_id") is not None
            or source.get("accepted_output_hash") is not None
        ):
            raise ValueError(f"{owner} skipped control source carries an accepted output")
    else:
        raise ValueError(f"{owner} control source status is invalid")
    del kind  # Kind is fixed by the containing server-owned payload schema.


def _claims_and_refs(
    value: Mapping[str, Any],
    label: str,
    *,
    max_claims: int = 10,
    max_refs: int = 10,
) -> dict[str, list[str]]:
    claims = _bounded_list(
        value.get("claims"), f"{label}.claims", minimum=1, maximum=max_claims
    )
    claim_ids: set[str] = set()
    claim_evidence: dict[str, list[str]] = {}
    for index, raw in enumerate(claims):
        claim = _object(raw, f"{label}.claims[{index}]")
        _exact_object(
            claim,
            {
                "claim_id",
                "claim_kind",
                "statement",
                "structured_conclusion",
                "evidence_ids",
                "research_rule_refs",
            },
            f"{label}.claims[{index}]",
        )
        claim_id = _text(claim.get("claim_id"), "claim_id", maximum=128)
        if claim_id in claim_ids:
            raise ValueError(f"duplicate accepted claim ID: {claim_id}")
        claim_ids.add(claim_id)
        _enum(
            claim.get("claim_kind"),
            {"FACT", "EVENT", "INTERPRETATION", "RISK_FLAG"},
            "claim_kind",
        )
        _text(claim.get("statement"), "claim statement", maximum=320)
        evidence_ids = _text_array(
            claim.get("evidence_ids"),
            "claim evidence IDs",
            minimum=1,
            maximum=16,
            text_maximum=256,
            unique=True,
        )
        claim_evidence[claim_id] = sorted(evidence_ids)
        research_rule_refs = _text_array(
            claim.get("research_rule_refs"),
            "research rule refs",
            maximum=16,
            text_maximum=256,
        )
        if claim.get("claim_kind") == "INTERPRETATION" and not research_rule_refs:
            raise ValueError("INTERPRETATION claims require a research rule ref")
        conclusion = _object(claim.get("structured_conclusion"), "structured conclusion")
        if not conclusion or len(conclusion) > 12:
            raise ValueError("structured conclusion must contain 1 to 12 scalar fields")
        for key, item in conclusion.items():
            _text(key, "structured conclusion key", maximum=96)
            if isinstance(item, str):
                if item != item.strip() or len(item) > 256:
                    raise ValueError("structured conclusion text must be trimmed and at most 256")
            elif isinstance(item, bool) or item is None:
                continue
            elif isinstance(item, (int, float)):
                if not math.isfinite(float(item)):
                    raise ValueError("structured conclusion numbers must be finite")
            else:
                raise ValueError("structured conclusion must contain scalar fields")
    _claim_refs(
        value.get("claim_refs"),
        f"{label}.claim_refs",
        claim_ids,
        minimum=1,
        maximum=max_refs,
    )
    return claim_evidence


def _validate_attributions(
    value: Any,
    *,
    allowed_target_types: set[str],
    summary_body: Mapping[str, Any],
    targets: Mapping[str, list[Mapping[str, Any]]],
) -> None:
    rows = _bounded_list(
        value,
        "accepted macro input attributions",
        minimum=len(_MACRO_AGENT_IDS),
        maximum=16,
    )
    summary_agents: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    usage_by_agent: dict[str, float] = {}
    summary_hash = canonical_hash(summary_body)
    target_hashes = {
        target_type: {canonical_hash(target) for target in target_rows}
        for target_type, target_rows in targets.items()
    }
    for index, raw in enumerate(rows):
        row = _object(raw, f"accepted_macro_input_attributions[{index}]")
        _exact_object(
            row,
            {
                "agent_id",
                "usage_share",
                "target_type",
                "target_ref",
                "target_hash",
                "claim_refs_used",
                "effect",
            },
            f"accepted_macro_input_attributions[{index}]",
        )
        agent_id = _enum(row.get("agent_id"), set(_MACRO_AGENT_IDS), "attribution agent_id")
        usage_share = _number(row.get("usage_share"), "attribution usage_share", 0, 1)
        previous_usage = usage_by_agent.setdefault(agent_id, usage_share)
        if abs(previous_usage - usage_share) > 1e-12:
            raise ValueError(f"{agent_id} attribution usage_share is inconsistent")
        target_type = _enum(
            row.get("target_type"), _ATTRIBUTION_TARGET_TYPES, "attribution target_type"
        )
        if target_type not in allowed_target_types:
            raise ValueError(f"unsupported attribution target type: {target_type}")
        target_ref = _text(row.get("target_ref"), "attribution target_ref", maximum=256)
        _sha256(row.get("target_hash"), "attribution target hash")
        effect = _enum(
            row.get("effect"),
            _MATERIAL_ATTRIBUTION_EFFECTS | {"NOT_MATERIAL"},
            "attribution effect",
        )
        refs = _text_array(
            row.get("claim_refs_used"),
            "attribution claim_refs_used",
            maximum=6,
            text_maximum=128,
        )
        if (effect == "NOT_MATERIAL") != (len(refs) == 0):
            raise ValueError("attribution effect/claim_refs_used contract mismatch")
        key = (agent_id, target_type, target_ref)
        if key in seen:
            raise ValueError("duplicate accepted Macro attribution target")
        seen.add(key)
        if target_type == "SUBMISSION_SUMMARY":
            summary_agents.append(agent_id)
            if row.get("target_hash") != summary_hash:
                raise ValueError("submission attribution target_hash mismatch")
        elif row.get("target_hash") not in target_hashes.get(target_type, set()):
            raise ValueError("target attribution target_hash mismatch")
        expected_ref = (
            f"accepted-target:{'submission' if target_type == 'SUBMISSION_SUMMARY' else target_type.lower()}:"
            f"{str(row['target_hash'])[7:]}"
        )
        if target_ref != expected_ref:
            raise ValueError("accepted attribution target_ref/hash mismatch")
    if summary_agents != list(_MACRO_AGENT_IDS):
        raise ValueError("accepted Macro summary attributions must be roster ordered and complete")
    if abs(sum(usage_by_agent.values()) - 1) > 1e-9:
        raise ValueError("accepted Macro attribution usage shares must sum to one")


def _validate_direction(
    value: Any, *, preferred: bool, claim_ids: set[str]
) -> Mapping[str, Any]:
    direction = _object(value, "Sector direction")
    _exact_object(
        direction,
        {
            "selection_role",
            "direction_local_id",
            "direction_id",
            "allocation_action",
            "strength",
            "thesis",
            "claim_refs",
        },
        "Sector direction",
    )
    expected = ("PREFERRED", "OVERWEIGHT") if preferred else ("LEAST_PREFERRED", "UNDERWEIGHT")
    if (direction.get("selection_role"), direction.get("allocation_action")) != expected:
        raise ValueError("Sector direction role/action mismatch")
    _text(direction.get("direction_local_id"), "direction_local_id", maximum=128)
    _text(direction.get("direction_id"), "direction_id", maximum=128)
    _integer(direction.get("strength"), "Sector direction strength", 1, 5)
    _text(direction.get("thesis"), "Sector direction thesis", maximum=320)
    _claim_refs(
        direction.get("claim_refs"),
        "Sector direction claim_refs",
        claim_ids,
        minimum=1,
        maximum=14,
    )
    return direction


def _validate_drivers(
    value: Any,
    kind: str,
    *,
    claim_ids: set[str],
    minimum: int,
    maximum: int,
    max_refs: int,
) -> list[Mapping[str, Any]]:
    id_field = "driver_local_id" if kind == "driver" else "risk_local_id"
    rows: list[Mapping[str, Any]] = []
    for index, raw in enumerate(
        _bounded_list(value, f"{kind}s", minimum=minimum, maximum=maximum)
    ):
        row = _object(raw, f"{kind}s[{index}]")
        _exact_object(row, {id_field, "summary", "claim_refs"}, f"{kind}s[{index}]")
        _text(row.get(id_field), id_field, maximum=128)
        _text(row.get("summary"), f"{kind} summary", maximum=320)
        _claim_refs(
            row.get("claim_refs"),
            f"{kind} claim_refs",
            claim_ids,
            minimum=1,
            maximum=max_refs,
        )
        rows.append(row)
    _unique_field(rows, id_field, f"{kind}s")
    return rows


def _validate_security_picks(
    value: Any,
    *,
    sector: bool,
    claim_ids: set[str],
    maximum: int,
) -> list[Mapping[str, Any]]:
    fields = {"pick_local_id", "ts_code", "position_action", "conviction", "thesis", "claim_refs"}
    if sector:
        fields.add("direction_local_id")
    rows: list[Mapping[str, Any]] = []
    for index, raw in enumerate(_bounded_list(value, "security picks", maximum=maximum)):
        row = _object(raw, f"security_picks[{index}]")
        _exact_object(row, fields, f"security_picks[{index}]")
        _text(row.get("pick_local_id"), "pick_local_id", maximum=128)
        _ts_code(row.get("ts_code"), "security pick ts_code", strict_a_share=True)
        if sector:
            _text(row.get("direction_local_id"), "direction_local_id", maximum=128)
            _enum(row.get("position_action"), {"LONG", "SHORT", "AVOID"}, "position_action")
            max_refs = 14
        else:
            _enum(row.get("position_action"), {"LONG", "AVOID"}, "position_action")
            max_refs = 6
        conviction = _number(row.get("conviction"), "pick conviction", 0, 1)
        if conviction <= 0:
            raise ValueError("security pick conviction must be greater than zero")
        _text(row.get("thesis"), "security pick thesis", maximum=320)
        _claim_refs(
            row.get("claim_refs"),
            "security pick claim_refs",
            claim_ids,
            minimum=1,
            maximum=max_refs,
        )
        rows.append(row)
    return rows


def _validate_sector_security_leg(
    *,
    status: Any,
    abstention_confidence: Any,
    picks: list[Mapping[str, Any]],
    direction_local_id: Any,
    allowed_actions: set[str],
    label: str,
) -> None:
    status_text = _enum(
        status,
        {"PICKS_PRESENT", "NO_QUALIFIED_SECURITY"},
        f"{label} security status",
    )
    if status_text == "PICKS_PRESENT":
        if not picks or abstention_confidence is not None:
            raise ValueError(f"{label} PICKS_PRESENT requires picks and null abstention confidence")
    else:
        if picks or abstention_confidence is None:
            raise ValueError(
                f"{label} NO_QUALIFIED_SECURITY requires no picks and abstention confidence"
            )
        _number(abstention_confidence, f"{label} abstention confidence", 0, 1)
    for pick in picks:
        if (
            pick.get("direction_local_id") != direction_local_id
            or pick.get("position_action") not in allowed_actions
        ):
            raise ValueError(f"{label} security pick direction/action mismatch")


def _validate_control_resolutions(
    value: Any, *, cro: bool, claim_ids: set[str]
) -> list[Mapping[str, Any]]:
    identity = ("cro_action_ref", "cro_action_hash") if cro else (
        "execution_assessment_ref",
        "execution_assessment_hash",
    )
    rows: list[Mapping[str, Any]] = []
    for index, raw in enumerate(
        _bounded_list(value, "control resolutions", maximum=50)
    ):
        row = _object(raw, f"control_resolutions[{index}]")
        _exact_object(
            row,
            {identity[0], identity[1], "resolution", "reason", "claim_refs"},
            f"control_resolutions[{index}]",
        )
        _text(row.get(identity[0]), identity[0])
        _sha256(row.get(identity[1]), identity[1])
        _enum(
            row.get("resolution"), {"COMPLIED", "MORE_CONSERVATIVE"}, "control resolution"
        )
        _text(row.get("reason"), "control resolution reason", maximum=320)
        _claim_refs(
            row.get("claim_refs"),
            "control resolution claim_refs",
            claim_ids,
            minimum=1,
            maximum=10,
        )
        rows.append(row)
    _unique_field(rows, identity[0], "control resolutions")
    if rows != sorted(rows, key=lambda row: str(row[identity[0]])):
        raise ValueError("accepted control resolutions must be canonically ordered")
    return rows


def _decision_owner_versions(
    payload: Mapping[str, Any], agent_id: str, expected_agent: str
) -> None:
    if agent_id != expected_agent or payload.get("agent_id") != expected_agent:
        raise ValueError(f"accepted Decision payload owner mismatch for {agent_id}")
    _versions(payload)
    _number(payload.get("model_confidence"), "model_confidence", 0, 1)


def _versions(value: Mapping[str, Any]) -> None:
    for field in (
        "agent_contract_version",
        "prompt_behavior_version",
        "execution_behavior_version",
    ):
        _text(value.get(field), field)


def _exact_object(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{label} fields mismatch; missing={missing}, extra={extra}"
        )


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _text(value: Any, label: str, *, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters")
    return value


def _enum(value: Any, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label} must be one of {sorted(allowed)}")
    return value


def _sha256(value: Any, label: str) -> str:
    text = _text(value, label)
    if len(text) != 71 or not text.startswith("sha256:") or any(
        character not in "0123456789abcdef" for character in text[7:]
    ):
        raise ValueError(f"{label} must be a canonical sha256")
    return text


def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
    ):
        raise ValueError(f"{label} must be in [{minimum}, {maximum}]")
    return float(value)


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer in [{minimum}, {maximum}]")
    return value


def _bounded_list(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> list[Any]:
    rows = _list(value, label)
    if len(rows) < minimum or (maximum is not None and len(rows) > maximum):
        upper = "unbounded" if maximum is None else str(maximum)
        raise ValueError(f"{label} must contain between {minimum} and {upper} items")
    return rows


def _text_array(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
    text_maximum: int | None = None,
    unique: bool = False,
) -> list[str]:
    rows = _bounded_list(value, label, minimum=minimum, maximum=maximum)
    texts = [_text(row, label, maximum=text_maximum) for row in rows]
    if unique and len(set(texts)) != len(texts):
        raise ValueError(f"{label} must be unique")
    return texts


def _claim_refs(
    value: Any,
    label: str,
    claim_ids: set[str],
    *,
    minimum: int,
    maximum: int,
) -> list[str]:
    refs = _text_array(
        value,
        label,
        minimum=minimum,
        maximum=maximum,
        text_maximum=128,
    )
    unresolved = sorted(set(refs) - claim_ids)
    if unresolved:
        raise ValueError(f"{label} has unresolved claim refs: {unresolved}")
    return refs


def _unique_field(rows: list[Mapping[str, Any]], field: str, label: str) -> None:
    values = [row.get(field) for row in rows]
    if len(set(values)) != len(values):
        raise ValueError(f"{label}.{field} must be unique")


def _unique_fields(
    rows: list[Mapping[str, Any]], fields: tuple[str, ...], label: str
) -> None:
    values = [tuple(row.get(field) for field in fields) for row in rows]
    if len(set(values)) != len(values):
        raise ValueError(f"{label}.{'+'.join(fields)} must be unique")


def _persistent_id(namespace: str, value: Any) -> str:
    return f"{namespace}:{canonical_hash(value)[7:]}"


def _ts_code(value: Any, label: str, *, strict_a_share: bool) -> str:
    text = _text(value, label, maximum=32)
    if strict_a_share and _TS_CODE.fullmatch(text) is None:
        raise ValueError(f"{label} must be an A-share ts_code")
    return text


def _text_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    rows = _list(value, label)
    if nonempty and not rows:
        raise ValueError(f"{label} must not be empty")
    return [_text(row, label) for row in rows]


def _sorted_unique_texts(value: Any, label: str, *, nonempty: bool) -> list[str]:
    rows = _text_list(value, label, nonempty=nonempty)
    if rows != sorted(set(rows)):
        raise ValueError(f"{label} must be sorted and unique")
    return rows


__all__ = [
    "ACCEPTED_OUTPUT_ADAPTER_CONTRACT_VERSION",
    "validate_accepted_output_record_schema",
]

"""Authoritative source reconstruction for scheduled evaluation opportunities."""

from __future__ import annotations

import json
from typing import Any, Mapping

from mosaic.dataflows.outcome_runtime_inputs import (
    validate_evaluation_opportunity_members,
)
from mosaic.dataflows.sector_snapshots import SECTOR_UNIVERSE_MANIFEST
from mosaic.scorecard.darwinian_v2 import canonical_hash, deterministic_id
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS


AUTHORITY_CONTRACT_VERSION = "evaluation_opportunity_source_authority_v1"
LIVE_L1_L2_AGENT_IDS = frozenset(
    {
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
        "semiconductor",
        "technology",
        "energy",
        "biotech",
        "consumer",
        "industrials",
        "real_estate_construction",
        "financials",
        "agriculture",
        "relationship_mapper",
    }
)
SUPERINVESTOR_AGENT_IDS = frozenset(
    {"druckenmiller", "munger", "burry", "ackman"}
)


def assert_authoritative_member_match(
    *,
    agent_id: str,
    projected_members: Any,
    authoritative_members: Any,
) -> None:
    """Reject any field, value, ordering, insertion, or deletion difference."""
    if projected_members != authoritative_members:
        raise ValueError(
            f"{agent_id} opportunity members differ from authoritative source"
        )


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _payload(rendered: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _source_snapshot_hash(payload: Mapping[str, Any], label: str) -> str:
    return _required_text(payload.get("snapshot_hash"), f"{label}.snapshot_hash")


def macro_authority_members(
    *,
    agent_id: str,
    snapshot: Mapping[str, Any],
    schedule_slot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Derive the one exact Macro evaluation member from source and schedule."""
    contract = OUTCOME_CONTRACTS.get(agent_id)
    if contract is None or contract["evaluation_object_type"] != "MACRO_TRANSMISSION":
        raise ValueError(f"{agent_id} is not a Macro outcome Agent")
    snapshot_hash = _source_snapshot_hash(snapshot, agent_id)
    if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED":
        trigger = schedule_slot.get("trigger_event")
        if not isinstance(trigger, Mapping):
            raise ValueError(f"{agent_id} scheduled Macro slot has no trigger event")
        members = [{"event_id": _required_text(trigger.get("event_id"), "trigger event_id")}]
    else:
        if schedule_slot.get("trigger_event") is not None:
            raise ValueError(f"{agent_id} fixed Macro slot cannot carry a trigger event")
        members = [
            {
                "path_snapshot_id": deterministic_id(
                    "macro-path-snapshot",
                    {"agent_id": agent_id, "snapshot_hash": snapshot_hash},
                )
            }
        ]
    return validate_evaluation_opportunity_members(
        agent_id,
        contract["opportunity_set_contract_version"],
        members,
    )


def sector_authority_members(
    *, agent_id: str, snapshot: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Rebuild every Sector direction shortlist using the runtime selection rule."""
    contract = OUTCOME_CONTRACTS.get(agent_id)
    if contract is None or contract["evaluation_object_type"] != "SECTOR_TILT_PICKS":
        raise ValueError(f"{agent_id} is not a standard Sector outcome Agent")
    if snapshot.get("sector_agent_id") != agent_id:
        raise ValueError(f"{agent_id} Sector source identity mismatch")
    direction_ids = snapshot.get("direction_ids")
    scoring_rows = snapshot.get("security_scoring_rows")
    if not isinstance(direction_ids, list) or not isinstance(scoring_rows, list):
        raise ValueError(f"{agent_id} Sector source rows are unavailable")
    scoring_contract = SECTOR_UNIVERSE_MANIFEST["security_scoring_contract"]
    version = _required_text(
        snapshot.get("security_scoring_contract_version"),
        "security scoring contract version",
    )
    contract_hash = _required_text(
        snapshot.get("security_scoring_contract_hash"),
        "security scoring contract hash",
    )
    if (
        version != scoring_contract["scoring_contract_version"]
        or contract_hash != scoring_contract["scoring_contract_hash"]
    ):
        raise ValueError(f"{agent_id} security scoring contract mismatch")
    limit = int(scoring_contract["shortlist_maximum_size_per_direction"])
    members: list[dict[str, Any]] = []
    for direction_id_value in direction_ids:
        direction_id = _required_text(direction_id_value, "Sector direction_id")
        rows = sorted(
            (
                dict(row)
                for row in scoring_rows
                if isinstance(row, Mapping)
                and row.get("direction_id") == direction_id
                and row.get("availability_status") == "AVAILABLE"
            ),
            key=lambda row: (
                -float(row["median_amount_20d_cny"]),
                str(row["ts_code"]),
            ),
        )[:limit]
        shortlist_hash = canonical_hash(
            {
                "direction_id": direction_id,
                "security_scoring_contract_version": version,
                "security_scoring_contract_hash": contract_hash,
                "rows": rows,
            }
        )
        members.append(
            {
                "subindustry_id": direction_id,
                "security_shortlist_id": (
                    f"sector-shortlist:{direction_id}:{shortlist_hash[-16:]}"
                ),
                "security_shortlist_hash": shortlist_hash,
                "security_ts_codes": [
                    _required_text(row.get("ts_code"), "Sector scoring ts_code")
                    for row in rows
                ],
            }
        )
    return validate_evaluation_opportunity_members(
        agent_id,
        contract["opportunity_set_contract_version"],
        members,
    )


def relationship_authority_members(
    snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project the exact run-bound Relationship edge denominator."""
    opportunity = snapshot.get("prediction_opportunity_set")
    if not isinstance(opportunity, Mapping):
        raise ValueError("Relationship prediction opportunity set is unavailable")
    rows = opportunity.get("ordered_opportunities")
    if not isinstance(rows, list):
        raise ValueError("Relationship ordered opportunities are unavailable")
    members = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"Relationship opportunity {index} must be an object")
        members.append(
            {
                "edge_candidate_id": _required_text(
                    row.get("edge_candidate_id"),
                    f"Relationship opportunity {index}.edge_candidate_id",
                ),
                "materiality_weight": row.get("materiality_weight"),
            }
        )
    contract = OUTCOME_CONTRACTS["relationship_mapper"]
    return validate_evaluation_opportunity_members(
        "relationship_mapper",
        contract["opportunity_set_contract_version"],
        members,
    )


def superinvestor_authority_members(
    *, agent_id: str, snapshot: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Project the exact server-validated runtime candidate universe."""
    if agent_id not in SUPERINVESTOR_AGENT_IDS:
        raise ValueError(f"{agent_id} is not a Superinvestor outcome Agent")
    rows = snapshot.get("candidate_universe")
    if not isinstance(rows, list):
        raise ValueError("Superinvestor candidate universe is unavailable")
    members = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"Superinvestor candidate {index} must be an object")
        members.append(
            {
                "candidate_ref": _required_text(
                    row.get("candidate_ref"),
                    f"Superinvestor candidate {index}.candidate_ref",
                ),
                "ts_code": _required_text(
                    row.get("ts_code"),
                    f"Superinvestor candidate {index}.ts_code",
                ),
            }
        )
    contract = OUTCOME_CONTRACTS[agent_id]
    return validate_evaluation_opportunity_members(
        agent_id,
        contract["opportunity_set_contract_version"],
        members,
    )


def materialize_pre_run_authority(
    *,
    agent_id: str,
    as_of: str,
    graph_run_id: str,
    schedule_slot: Mapping[str, Any],
) -> dict[str, Any]:
    """Materialize and rebuild one scheduled L1/L2 denominator."""
    from mosaic.bridge.tool_capabilities import (
        MACRO_AGENT_TO_TOOL,
        STANDARD_SECTOR_AGENTS,
        materialize_tool_payload,
    )

    as_of_date = as_of[:10]
    if agent_id in MACRO_AGENT_TO_TOOL:
        tool_id = MACRO_AGENT_TO_TOOL[agent_id]
        snapshot = _payload(
            materialize_tool_payload(
                tool_id,
                agent_id=agent_id,
                stage=agent_id,
                as_of=as_of_date,
                graph_run_id=graph_run_id,
            ),
            f"{agent_id} Macro snapshot",
        )
        members = macro_authority_members(
            agent_id=agent_id,
            snapshot=snapshot,
            schedule_slot=schedule_slot,
        )
    elif agent_id in STANDARD_SECTOR_AGENTS:
        tool_id = "get_sector_research_snapshot"
        snapshot = _payload(
            materialize_tool_payload(
                tool_id,
                agent_id=agent_id,
                stage=agent_id,
                as_of=as_of_date,
                graph_run_id=graph_run_id,
            ),
            f"{agent_id} Sector snapshot",
        )
        members = sector_authority_members(agent_id=agent_id, snapshot=snapshot)
    elif agent_id == "relationship_mapper":
        tool_id = "get_relationship_graph_snapshot"
        snapshot = _payload(
            materialize_tool_payload(
                tool_id,
                agent_id=agent_id,
                stage=agent_id,
                as_of=as_of_date,
                graph_run_id=graph_run_id,
            ),
            "Relationship snapshot",
        )
        members = relationship_authority_members(snapshot)
    else:
        raise ValueError(f"{agent_id} has no pre-run source authority")
    source_hash = _source_snapshot_hash(snapshot, agent_id)
    authority_body = {
        "contract_version": AUTHORITY_CONTRACT_VERSION,
        "agent_id": agent_id,
        "source_tool_id": tool_id,
        "source_snapshot_hash": source_hash,
        "schedule_slot_hash": schedule_slot.get("outcome_schedule_slot_hash"),
        "member_refs": members,
    }
    domain_hash = canonical_hash(authority_body)
    return {
        **authority_body,
        "domain_hash": domain_hash,
        # Retained as a compatibility alias for existing audit fixtures.  The
        # runtime binding uses the explicit domain_hash field below.
        "authority_hash": domain_hash,
        "runtime_authority_binding": {
            "source_tool_id": tool_id,
            "source_snapshot_hash": source_hash,
            "domain_hash": domain_hash,
        },
    }


def materialize_superinvestor_authority(
    *,
    agent_id: str,
    as_of: str,
    graph_run_id: str,
    accepted_output_refs: Any,
) -> dict[str, Any]:
    """Materialize the exact L2-derived candidate authority at the L3 boundary."""
    from mosaic.bridge.tool_capabilities import materialize_tool_payload

    snapshot = _payload(
        materialize_tool_payload(
            "get_superinvestor_candidate_snapshot",
            agent_id=agent_id,
            stage=agent_id,
            as_of=as_of[:10],
            graph_run_id=graph_run_id,
            accepted_output_refs=accepted_output_refs,
        ),
        f"{agent_id} Superinvestor candidate snapshot",
    )
    members = superinvestor_authority_members(agent_id=agent_id, snapshot=snapshot)
    body = {
        "contract_version": AUTHORITY_CONTRACT_VERSION,
        "agent_id": agent_id,
        "tool_id": "get_superinvestor_candidate_snapshot",
        "source_snapshot_hash": _source_snapshot_hash(snapshot, agent_id),
        "candidate_scope_hash": _required_text(
            snapshot.get("candidate_scope_hash"), "candidate_scope_hash"
        ),
        "candidate_universe_id": _required_text(
            snapshot.get("candidate_universe_id"), "candidate_universe_id"
        ),
        "candidate_universe_hash": _required_text(
            snapshot.get("candidate_universe_hash"), "candidate_universe_hash"
        ),
        "member_refs": members,
    }
    return {**body, "authority_hash": canonical_hash(body)}


__all__ = [
    "AUTHORITY_CONTRACT_VERSION",
    "LIVE_L1_L2_AGENT_IDS",
    "SUPERINVESTOR_AGENT_IDS",
    "assert_authoritative_member_match",
    "macro_authority_members",
    "materialize_pre_run_authority",
    "materialize_superinvestor_authority",
    "relationship_authority_members",
    "sector_authority_members",
    "superinvestor_authority_members",
]

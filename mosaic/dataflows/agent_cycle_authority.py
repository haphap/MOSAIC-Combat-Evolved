"""Atomic lifecycle authority for production/shadow Agent cycles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.darwinian_v2 import accepted_cycle_stage_outcome_refs

from .agent_materialization import (
    AgentCycleEvent,
    AgentCyclePublication,
    AgentDataMaterializationLedger,
    RuntimeRouteNotRequiredReceipt,
    load_agent_data_route_manifest,
)
from .route_eligibility import evaluate_agent_source_admission


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("cycle timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def final_decision_projection(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical public decision subset sealed by cycle commit."""
    actions = state.get("portfolio_actions")
    if not isinstance(actions, list):
        raise ValueError("cycle final state portfolio_actions must be an array")
    disposition = _required_text(
        state.get("decision_disposition"), "decision_disposition"
    )
    final_target = state.get("final_target_state")
    if final_target is not None and not isinstance(final_target, Mapping):
        raise ValueError("final_target_state must be an object or null")
    return {
        "run_id": _required_text(state.get("trace_id"), "trace_id"),
        "target_date": _required_text(state.get("as_of_date"), "as_of_date"),
        "cohort": _required_text(state.get("active_cohort"), "active_cohort"),
        "decision_disposition": disposition,
        "final_target_state": dict(final_target) if final_target is not None else None,
        "portfolio_actions": actions,
    }


def final_decision_hash(state: Mapping[str, Any]) -> str:
    return canonical_hash(final_decision_projection(state))


def open_agent_cycle(
    *,
    ledger: AgentDataMaterializationLedger,
    target_date: str,
    run_id: str,
    cohort: str,
    mode: str,
    cycle_kind: str,
    execution_behavior_release_hash: str,
    knot_coverage_manifest_v2_hash: str,
    opened_at: str,
    lease_seconds: int = 3600,
) -> dict[str, Any]:
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    opened = _timestamp(opened_at)
    admission = evaluate_agent_source_admission(
        ledger=ledger,
        target_date=target_date,
        evaluated_at=opened.isoformat(),
        cycle_run_id=run_id,
    )
    if admission["status"] != "SOURCE_READY_PENDING_RUNTIME":
        blocked = ",".join(row["route_id"] for row in admission["blocked_routes"])
        raise ValueError(f"Agent cycle source admission BLOCKED: {blocked}")
    manifest = load_agent_data_route_manifest()
    event = AgentCycleEvent.seal(
        {
            "schema_version": "agent_cycle_event_v1",
            "event_id": f"cycle-event:{run_id}:open",
            "run_id": run_id,
            "target_date": target_date,
            "cohort": cohort,
            "mode": mode,
            "cycle_kind": cycle_kind,
            "state": "OPEN",
            "authority_hashes": {
                "route_manifest_hash": manifest["manifest_hash"],
                "agent_tool_contract_manifest_hash": manifest[
                    "agent_tool_contract_manifest_hash"
                ],
                "execution_behavior_release_hash": execution_behavior_release_hash,
                "knot_coverage_manifest_v2_hash": knot_coverage_manifest_v2_hash,
            },
            "source_eligibility_receipt_hashes": admission[
                "eligibility_receipt_hashes"
            ],
            "runtime_route_closure_refs": {},
            "stage_outcomes": [],
            "accepted_output_closure_hash": None,
            "final_decision_hash": None,
            "lease": {
                "opened_at": opened.isoformat(),
                "expires_at": (opened + timedelta(seconds=lease_seconds)).isoformat(),
            },
            "terminal_reason": None,
            "event_at": opened.isoformat(),
        }
    )
    ledger.append_cycle_open(event)
    return {
        "status": "OPEN",
        "event": event.as_dict(),
        "source_admission": admission,
    }


def commit_agent_cycle(
    *,
    ledger: AgentDataMaterializationLedger,
    state: Mapping[str, Any],
    committed_at: str,
) -> dict[str, Any]:
    projection = final_decision_projection(state)
    run_id = projection["run_id"]
    opened = ledger.open_cycle_event(run_id=run_id)
    if opened is None:
        raise ValueError("Agent cycle has no active OPEN event")
    opened_payload = opened.as_dict()
    committed_time = _timestamp(committed_at)
    if committed_time > _timestamp(opened_payload["lease"]["expires_at"]):
        raise ValueError("Agent cycle OPEN lease expired before commit")
    if (
        projection["target_date"] != opened_payload["target_date"]
        or projection["cohort"] != opened_payload["cohort"]
    ):
        raise ValueError("Agent cycle final decision differs from OPEN identity")
    if state.get("day_outcome_status") != "accepted":
        raise ValueError("Agent cycle commit requires an accepted day outcome")
    stage_outcomes = accepted_cycle_stage_outcome_refs(state)
    manifest = load_agent_data_route_manifest()
    runtime_routes = [
        route
        for route in manifest["routes"]
        if route["pit_strategy"] == "LOCAL_RUNTIME_AUTHORITY"
    ]
    runtime_receipts = ledger.route_eligibility_receipts_for_cycle(
        cycle_run_id=run_id
    )
    runtime_refs = {
        route["route_id"]: runtime_receipts[route["route_id"]].receipt_hash
        for route in runtime_routes
        if route["route_id"] in runtime_receipts
    }
    outcome_by_stage = {
        (row["agent_id"], row["stage"]): row for row in stage_outcomes
    }
    for route in runtime_routes:
        route_id = route["route_id"]
        if route_id in runtime_refs:
            continue
        consumers = sorted(
            {
                (binding["agent_id"], binding["stage"])
                for binding in manifest["bindings"]
                if route_id in binding["required_route_ids"]
            }
        )
        skipped = [outcome_by_stage.get(stage_key) for stage_key in consumers]
        if not skipped or any(
            outcome is None or outcome["outcome_kind"] != "STAGE_SKIP"
            for outcome in skipped
        ):
            raise ValueError(
                f"runtime route has no READY eligibility but is required: {route_id}"
            )
        not_required = RuntimeRouteNotRequiredReceipt.seal(
            {
                "schema_version": "runtime_route_not_required_v1",
                "receipt_id": f"runtime-not-required:{run_id}:{route_id}",
                "route_id": route_id,
                "contract_version": route["contract_version"],
                "target_date": projection["target_date"],
                "run_id": run_id,
                "unexecuted_stages": [
                    {
                        "agent_id": agent_id,
                        "stage": stage,
                        "skip_receipt_hash": outcome_by_stage[(agent_id, stage)][
                            "ref_hash"
                        ],
                    }
                    for agent_id, stage in consumers
                ],
                "upstream_authority_hashes": opened_payload["authority_hashes"],
                "evaluated_at": committed_time.isoformat(),
            }
        )
        ledger.append_runtime_route_not_required(not_required)
        runtime_refs[route_id] = not_required.receipt_hash
    accepted_refs = [
        row for row in stage_outcomes if row["outcome_kind"] == "ACCEPTED_OUTPUT"
    ]
    decision_hash = canonical_hash(projection)
    event = AgentCycleEvent.seal(
        {
            **opened_payload,
            "event_id": f"cycle-event:{run_id}:committed",
            "state": "COMMITTED",
            "runtime_route_closure_refs": runtime_refs,
            "stage_outcomes": stage_outcomes,
            "accepted_output_closure_hash": canonical_hash(accepted_refs),
            "final_decision_hash": decision_hash,
            "event_at": committed_time.isoformat(),
        }
    )
    publication = AgentCyclePublication.seal(
        {
            "schema_version": "agent_cycle_publication_v1",
            "publication_id": f"cycle-publication:{run_id}",
            "run_id": run_id,
            "target_date": projection["target_date"],
            "cohort": projection["cohort"],
            "cycle_kind": opened_payload["cycle_kind"],
            "committed_event_hash": event.receipt_hash,
            "final_decision_hash": decision_hash,
            "published_at": committed_time.isoformat(),
        }
    )
    event_hash, publication_hash = ledger.commit_cycle(event, publication)
    return {
        "status": "COMMITTED",
        "event_hash": event_hash,
        "publication_hash": publication_hash,
        "final_decision_hash": decision_hash,
    }


def abort_agent_cycle(
    *,
    ledger: AgentDataMaterializationLedger,
    run_id: str,
    reason: str,
    aborted_at: str,
) -> dict[str, Any]:
    opened = ledger.open_cycle_event(run_id=run_id)
    if opened is None:
        raise ValueError("Agent cycle has no active OPEN event")
    event = AgentCycleEvent.seal(
        {
            **opened.as_dict(),
            "event_id": f"cycle-event:{run_id}:aborted",
            "state": "ABORTED",
            "terminal_reason": _required_text(reason, "reason"),
            "event_at": _timestamp(aborted_at).isoformat(),
        }
    )
    event_hash = ledger.append_cycle_abort(event)
    return {"status": "ABORTED", "event_hash": event_hash}


def require_committed_agent_cycle(
    *,
    ledger: AgentDataMaterializationLedger,
    state: Mapping[str, Any],
    publication_hash: str,
) -> AgentCyclePublication:
    run_id = _required_text(state.get("trace_id"), "trace_id")
    publication = ledger.committed_cycle_publication(run_id=run_id)
    if publication is None or publication.receipt_hash != publication_hash:
        raise ValueError("production consumer requires a COMMITTED Agent cycle")
    payload = publication.as_dict()
    if payload["final_decision_hash"] != final_decision_hash(state):
        raise ValueError("COMMITTED Agent cycle final decision hash mismatch")
    return publication


__all__ = [
    "abort_agent_cycle",
    "commit_agent_cycle",
    "final_decision_hash",
    "final_decision_projection",
    "open_agent_cycle",
    "require_committed_agent_cycle",
]

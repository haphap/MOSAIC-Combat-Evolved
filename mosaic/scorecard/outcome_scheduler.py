"""Deterministic pre-run scheduling for Darwinian v2 outcome samples."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence, TypeVar

from mosaic.scorecard.darwinian_updates import (
    EMPTY_OPPORTUNITY_ALLOWED,
    append_outcome_eligibility_revision,
    freeze_evaluation_opportunity_set,
)
from mosaic.scorecard.darwinian_v2 import (
    canonical_hash,
    canonical_json,
    deterministic_id,
)
from mosaic.scorecard.outcome_contracts import (
    OPPORTUNITY_GENERATION_FAILURE_CODES,
    OPPORTUNITY_GENERATOR_CONTRACT_VERSION,
    OUTCOME_CONTRACTS,
)


_CALENDAR_SCHEMA_VERSION = "verified_trading_calendar_snapshot_v1"
_PLAN_SCHEMA_VERSION = "outcome_schedule_plan_v2"
_SLOT_SCHEMA_VERSION = "outcome_schedule_slot_v2"
_T = TypeVar("_T")


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _insert_immutable(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
    record_id: str,
    columns: Sequence[str],
    values: Sequence[Any],
    record_json: str,
) -> bool:
    cursor = conn.execute(
        f"INSERT OR IGNORE INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        tuple(values),
    )
    if cursor.rowcount == 1:
        return True
    row = conn.execute(
        f"SELECT record_json FROM {table} WHERE {id_column} = ?",
        (record_id,),
    ).fetchone()
    if row is None or row[0] != record_json:
        raise ValueError(f"immutable record collision in {table}: {record_id}")
    return False


def _run_terminal_write(
    conn: sqlite3.Connection,
    operation: Callable[[], _T],
) -> _T:
    """Serialize one terminal read/write when this function owns the transaction."""
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        result = operation()
        if owns_transaction:
            conn.commit()
        return result
    except Exception:
        if owns_transaction and conn.in_transaction:
            conn.rollback()
        raise


def _verified_calendar(
    snapshot: Mapping[str, Any],
    *,
    as_of: str,
) -> tuple[list[str], str, str]:
    without_hash = {
        key: value for key, value in snapshot.items() if key != "snapshot_hash"
    }
    if snapshot.get("schema_version") != _CALENDAR_SCHEMA_VERSION:
        raise ValueError("unsupported trading calendar snapshot schema")
    if snapshot.get("snapshot_hash") != canonical_hash(without_hash):
        raise ValueError("trading calendar snapshot hash mismatch")
    if snapshot.get("pit_status") != "VERIFIED":
        raise ValueError("trading calendar snapshot must be PIT VERIFIED")
    calendar_id = _required_text(snapshot.get("trading_calendar_id"), "calendar id")
    if snapshot.get("as_of") != as_of:
        raise ValueError("trading calendar snapshot as_of mismatch")
    evidence_ids = snapshot.get("source_evidence_ids")
    if (
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or any(not isinstance(item, str) or not item for item in evidence_ids)
        or len(evidence_ids) != len(set(evidence_ids))
    ):
        raise ValueError("trading calendar snapshot requires unique source evidence")
    dates = snapshot.get("trading_dates")
    if (
        not isinstance(dates, list)
        or not dates
        or any(not isinstance(item, str) or len(item) != 10 for item in dates)
        or dates != sorted(set(dates))
    ):
        raise ValueError("trading_dates must be a non-empty sorted unique calendar")
    as_of_date = as_of[:10]
    if as_of_date not in dates:
        raise ValueError("as_of must be an open session in the frozen calendar")
    return dates, calendar_id, str(snapshot["snapshot_hash"])


def _revision_and_tracks(
    conn: sqlite3.Connection,
    revision_id: str,
) -> tuple[dict[str, Any], dict[str, tuple[str, dict[str, Any]]]]:
    row = conn.execute(
        "SELECT record_json FROM darwinian_v2_production_variant_roster_revisions "
        "WHERE production_variant_roster_revision_id = ? AND readiness = 'READY'",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise ValueError("READY production roster revision is unavailable")
    revision = json.loads(row[0])
    track_hashes = revision.get("evaluation_track_key_hashes")
    if not isinstance(track_hashes, list) or len(track_hashes) != 28:
        raise ValueError("roster revision must contain exactly 28 evaluation tracks")
    placeholders = ",".join("?" for _ in track_hashes)
    rows = conn.execute(
        f"SELECT agent_id, track_key_hash, contract_json "
        f"FROM darwinian_v2_evaluation_tracks "
        f"WHERE track_key_hash IN ({placeholders})",
        tuple(track_hashes),
    ).fetchall()
    by_agent = {
        str(agent_id): (str(track_hash), json.loads(contract_json))
        for agent_id, track_hash, contract_json in rows
    }
    if set(by_agent) != set(OUTCOME_CONTRACTS):
        raise ValueError("roster revision does not resolve the exact 28-Agent roster")
    return revision, by_agent


def _parse_timestamp(value: Any, label: str) -> datetime:
    text = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _event_candidates(
    raw: Any,
    *,
    agent_id: str,
    contract: Mapping[str, Any],
    as_of: str,
) -> list[dict[str, Any]]:
    schedule = contract["sample_schedule"]
    if not isinstance(raw, Mapping):
        raise ValueError(f"event coverage for {agent_id} must be an object")
    if raw.get("coverage_status") != "COMPLETE":
        raise ValueError(f"event coverage for {agent_id} is not COMPLETE")
    if raw.get("event_registry_version") != schedule["event_registry_version"]:
        raise ValueError(f"{agent_id} event coverage registry version mismatch")
    if raw.get("event_priority_version") != schedule["event_priority_version"]:
        raise ValueError(f"{agent_id} event coverage priority version mismatch")
    coverage_evidence_ids = raw.get("coverage_evidence_ids")
    if (
        not isinstance(coverage_evidence_ids, list)
        or not coverage_evidence_ids
        or any(not isinstance(item, str) or not item for item in coverage_evidence_ids)
        or len(coverage_evidence_ids) != len(set(coverage_evidence_ids))
    ):
        raise ValueError(f"event coverage for {agent_id} requires evidence")
    raw_candidates = raw.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError(f"event candidates for {agent_id} must be an array")
    as_of_cutoff = _parse_timestamp(as_of, "as_of")
    candidates: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    causal_keys: set[str] = set()
    for index, item in enumerate(raw_candidates):
        if not isinstance(item, Mapping):
            raise ValueError(f"{agent_id}.event_candidates[{index}] must be an object")
        event_id = _required_text(item.get("event_id"), f"{agent_id}.event_id")
        causal_key = _required_text(
            item.get("causal_dedupe_key"), f"{agent_id}.causal_dedupe_key"
        )
        if event_id in event_ids or causal_key in causal_keys:
            raise ValueError(f"{agent_id} event candidates contain a duplicate event")
        event_ids.add(event_id)
        causal_keys.add(causal_key)
        if item.get("pit_status") != "VERIFIED":
            raise ValueError(f"{agent_id} event candidate is not PIT VERIFIED")
        if item.get("event_registry_version") != schedule["event_registry_version"]:
            raise ValueError(f"{agent_id} event registry version mismatch")
        if item.get("event_priority_version") != schedule["event_priority_version"]:
            raise ValueError(f"{agent_id} event priority version mismatch")
        priority_rank = item.get("priority_rank")
        if (
            not isinstance(priority_rank, int)
            or isinstance(priority_rank, bool)
            or priority_rank < 0
        ):
            raise ValueError(f"{agent_id}.priority_rank must be a non-negative integer")
        published_at = _parse_timestamp(
            item.get("published_at"), f"{agent_id}.published_at"
        )
        if published_at > as_of_cutoff:
            raise ValueError(f"{agent_id} event candidate is future information")
        evidence_ids = item.get("source_evidence_ids")
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or any(not isinstance(value, str) or not value for value in evidence_ids)
            or len(evidence_ids) != len(set(evidence_ids))
        ):
            raise ValueError(f"{agent_id} event candidate requires source evidence")
        candidates.append(
            {
                "event_id": event_id,
                "causal_dedupe_key": causal_key,
                "event_registry_version": item["event_registry_version"],
                "event_priority_version": item["event_priority_version"],
                "priority_rank": priority_rank,
                "published_at": item["published_at"],
                "source_evidence_ids": sorted(evidence_ids),
                "pit_status": "VERIFIED",
            }
        )
    return sorted(
        candidates,
        key=lambda item: (
            item["priority_rank"],
            item["published_at"],
            item["event_id"],
        ),
    )


def _logical_run_slot(agent_id: str, contract: Mapping[str, Any]) -> str:
    if agent_id == "cio":
        return "cio"
    if contract["layer"] == "SECTOR" and agent_id != "relationship_mapper":
        return "final_selection"
    if agent_id == "alpha_discovery":
        return "alpha_discovery"
    if agent_id == "cro":
        return "cro_review"
    if agent_id == "autonomous_execution":
        return "execution_feasibility"
    return "agent_run"


def prepare_outcome_schedule_plan(
    conn: sqlite3.Connection,
    *,
    production_variant_roster_revision_id: str,
    graph_run_id: str,
    as_of: str,
    prepared_at: str,
    trading_calendar_snapshot: Mapping[str, Any],
    verified_event_candidates: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Freeze all 28 run-slot decisions before the daily graph starts."""
    revision_id = _required_text(
        production_variant_roster_revision_id,
        "production_variant_roster_revision_id",
    )
    graph_run_id = _required_text(graph_run_id, "graph_run_id")
    as_of = _required_text(as_of, "as_of")
    prepared_at = _required_text(prepared_at, "prepared_at")
    as_of_timestamp = _parse_timestamp(as_of, "as_of")
    prepared_timestamp = _parse_timestamp(prepared_at, "prepared_at")
    if prepared_timestamp < as_of_timestamp or prepared_at[:10] != as_of[:10]:
        raise ValueError("prepared_at must be on the as_of date and not precede as_of")
    dates, calendar_id, calendar_hash = _verified_calendar(
        trading_calendar_snapshot,
        as_of=as_of,
    )
    revision, tracks = _revision_and_tracks(conn, revision_id)
    event_agent_ids = {
        agent_id
        for agent_id, contract in OUTCOME_CONTRACTS.items()
        if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
    }
    if set(verified_event_candidates) != event_agent_ids:
        raise ValueError("event coverage must cover the exact event-triggered Agent roster")
    event_candidate_input_hash = canonical_hash(verified_event_candidates)
    existing_plan_row = conn.execute(
        "SELECT record_json FROM outcome_schedule_plans_v2 WHERE graph_run_id = ?",
        (graph_run_id,),
    ).fetchone()
    if existing_plan_row is not None:
        existing_plan = json.loads(existing_plan_row[0])
        for field, expected in (
            ("production_variant_roster_revision_id", revision_id),
            ("as_of", as_of),
            ("prepared_at", prepared_at),
            ("trading_calendar_snapshot_hash", calendar_hash),
            ("event_candidate_input_hash", event_candidate_input_hash),
        ):
            if existing_plan.get(field) != expected:
                raise ValueError(f"outcome schedule plan retry changed {field}")
        return existing_plan

    as_of_date = as_of[:10]
    as_of_index = dates.index(as_of_date)
    slots: list[dict[str, Any]] = []
    for agent_id in sorted(OUTCOME_CONTRACTS):
        contract = OUTCOME_CONTRACTS[agent_id]
        schedule = contract["sample_schedule"]
        if schedule["trading_calendar_id"] != calendar_id:
            raise ValueError(f"{agent_id} schedule trading calendar mismatch")
        track_hash, track = tracks[agent_id]
        run_slot_id = deterministic_id(
            "run-slot",
            {
                "graph_run_id": graph_run_id,
                "agent_id": agent_id,
                "slot": _logical_run_slot(agent_id, contract),
            },
        )
        scheduled_sample_id: str | None = None
        trigger_event: dict[str, Any] | None = None
        excluded_events: list[dict[str, Any]] = []
        if schedule["kind"] == "FIXED_NON_OVERLAP":
            epoch = schedule["epoch"]
            if epoch not in dates:
                raise ValueError(f"{agent_id} schedule epoch is absent from calendar")
            epoch_index = dates.index(epoch)
            step = schedule["step_trading_days"]
            if as_of_index >= epoch_index and (as_of_index - epoch_index) % step == 0:
                scheduled_sample_id = deterministic_id(
                    "scheduled-sample",
                    {
                        "track_key_hash": track_hash,
                        "sample_schedule_contract_version": track[
                            "outcome_contract"
                        ]["sample_schedule_contract_version"],
                        "as_of": as_of_date,
                    },
                )
        else:
            candidates = _event_candidates(
                verified_event_candidates.get(agent_id),
                agent_id=agent_id,
                contract=contract,
                as_of=as_of,
            )
            eligible: list[dict[str, Any]] = []
            for candidate in candidates:
                seen = conn.execute(
                    "SELECT 1 FROM outcome_event_schedule_decisions_v2 "
                    "WHERE track_key_hash = ? "
                    "AND (event_id = ? OR causal_dedupe_key = ?) LIMIT 1",
                    (
                        track_hash,
                        candidate["event_id"],
                        candidate["causal_dedupe_key"],
                    ),
                ).fetchone()
                if seen is None:
                    eligible.append(candidate)
                else:
                    excluded_events.append(
                        {**candidate, "exclusion_reason": "ALREADY_SCHEDULED"}
                    )
            if eligible:
                trigger_event = eligible[0]
                excluded_events.extend(
                    {**candidate, "exclusion_reason": "OVERLAPPING_WINDOW"}
                    for candidate in eligible[1:]
                )
                scheduled_sample_id = deterministic_id(
                    "scheduled-sample",
                    {
                        "track_key_hash": track_hash,
                        "sample_schedule_contract_version": track[
                            "outcome_contract"
                        ]["sample_schedule_contract_version"],
                        "event_id": trigger_event["event_id"],
                        "causal_dedupe_key": trigger_event["causal_dedupe_key"],
                    },
                )

        slot_without_hash = {
            "schema_version": _SLOT_SCHEMA_VERSION,
            "outcome_schedule_plan_id": None,
            "graph_run_id": graph_run_id,
            "agent_id": agent_id,
            "track_key_hash": track_hash,
            "run_slot_id": run_slot_id,
            "run_slot_kind": (
                "OUTCOME_SCHEDULED" if scheduled_sample_id else "DOWNSTREAM_ONLY"
            ),
            "scheduled_sample_id": scheduled_sample_id,
            "outcome_due_at": (
                f"{dates[as_of_index + contract['maturity']['horizon_trading_days']]}"
                "T15:00:00+08:00"
                if scheduled_sample_id
                and as_of_index + contract["maturity"]["horizon_trading_days"]
                < len(dates)
                else None
            ),
            "trigger_event": trigger_event,
            "excluded_events": excluded_events,
            "sample_schedule": schedule,
            "sample_schedule_contract_version": track["outcome_contract"][
                "sample_schedule_contract_version"
            ],
        }
        if scheduled_sample_id and slot_without_hash["outcome_due_at"] is None:
            raise ValueError(f"{agent_id} schedule calendar does not cover maturity")
        slots.append(slot_without_hash)

    plan_identity = {
        "graph_run_id": graph_run_id,
        "production_variant_roster_revision_id": revision_id,
        "as_of": as_of,
        "trading_calendar_snapshot_hash": calendar_hash,
        "event_candidate_input_hash": event_candidate_input_hash,
    }
    plan_id = deterministic_id("outcome-schedule-plan", plan_identity)
    final_slots: list[dict[str, Any]] = []
    for slot in slots:
        without_hash = {**slot, "outcome_schedule_plan_id": plan_id}
        slot_id = deterministic_id(
            "outcome-schedule-slot",
            {"outcome_schedule_plan_id": plan_id, "agent_id": slot["agent_id"]},
        )
        with_id = {"outcome_schedule_slot_id": slot_id, **without_hash}
        final_slots.append(
            {**with_id, "outcome_schedule_slot_hash": canonical_hash(with_id)}
        )
    plan_without_hash = {
        "outcome_schedule_plan_id": plan_id,
        "schema_version": _PLAN_SCHEMA_VERSION,
        "graph_run_id": graph_run_id,
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": revision_id,
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": revision["cohort_id"],
        "language": revision["language"],
        "trading_calendar_id": calendar_id,
        "trading_calendar_snapshot_hash": calendar_hash,
        "event_candidate_input_hash": event_candidate_input_hash,
        "as_of": as_of,
        "prepared_at": prepared_at,
        "slots": final_slots,
    }
    plan = {
        **plan_without_hash,
        "outcome_schedule_plan_hash": canonical_hash(plan_without_hash),
    }
    plan_json = canonical_json(plan)
    _insert_immutable(
        conn,
        table="outcome_schedule_plans_v2",
        id_column="outcome_schedule_plan_id",
        record_id=plan_id,
        columns=(
            "outcome_schedule_plan_id",
            "outcome_schedule_plan_hash",
            "graph_run_id",
            "production_variant_roster_id",
            "production_variant_roster_revision_id",
            "execution_behavior_release_id",
            "cohort_id",
            "language",
            "trading_calendar_id",
            "trading_calendar_snapshot_hash",
            "as_of",
            "prepared_at",
            "record_json",
        ),
        values=(
            plan_id,
            plan["outcome_schedule_plan_hash"],
            graph_run_id,
            revision["production_variant_roster_id"],
            revision_id,
            revision["execution_behavior_release_id"],
            revision["cohort_id"],
            revision["language"],
            calendar_id,
            calendar_hash,
            as_of,
            prepared_at,
            plan_json,
        ),
        record_json=plan_json,
    )
    for slot in final_slots:
        slot_json = canonical_json(slot)
        _insert_immutable(
            conn,
            table="outcome_schedule_slots_v2",
            id_column="outcome_schedule_slot_id",
            record_id=slot["outcome_schedule_slot_id"],
            columns=(
                "outcome_schedule_slot_id",
                "outcome_schedule_slot_hash",
                "outcome_schedule_plan_id",
                "graph_run_id",
                "agent_id",
                "track_key_hash",
                "run_slot_id",
                "run_slot_kind",
                "scheduled_sample_id",
                "trigger_event_id",
                "record_json",
            ),
            values=(
                slot["outcome_schedule_slot_id"],
                slot["outcome_schedule_slot_hash"],
                plan_id,
                graph_run_id,
                slot["agent_id"],
                slot["track_key_hash"],
                slot["run_slot_id"],
                slot["run_slot_kind"],
                slot["scheduled_sample_id"],
                (
                    slot["trigger_event"]["event_id"]
                    if slot["trigger_event"] is not None
                    else None
                ),
                slot_json,
            ),
            record_json=slot_json,
        )
        event_decisions: list[tuple[str, Mapping[str, Any]]] = []
        if slot["trigger_event"] is not None:
            event_decisions.append(("SELECTED", slot["trigger_event"]))
        event_decisions.extend(
            ("OVERLAPPING_WINDOW", event)
            for event in slot["excluded_events"]
            if event["exclusion_reason"] == "OVERLAPPING_WINDOW"
        )
        for disposition, event in event_decisions:
            decision_id = deterministic_id(
                "outcome-event-schedule-decision",
                {
                    "track_key_hash": slot["track_key_hash"],
                    "event_id": event["event_id"],
                    "causal_dedupe_key": event["causal_dedupe_key"],
                },
            )
            decision_without_hash = {
                "event_schedule_decision_id": decision_id,
                "schema_version": "outcome_event_schedule_decision_v2",
                "outcome_schedule_plan_id": plan_id,
                "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
                "track_key_hash": slot["track_key_hash"],
                "agent_id": slot["agent_id"],
                "event_id": event["event_id"],
                "causal_dedupe_key": event["causal_dedupe_key"],
                "disposition": disposition,
                "event": dict(event),
            }
            decision = {
                **decision_without_hash,
                "event_schedule_decision_hash": canonical_hash(
                    decision_without_hash
                ),
            }
            decision_json = canonical_json(decision)
            _insert_immutable(
                conn,
                table="outcome_event_schedule_decisions_v2",
                id_column="event_schedule_decision_id",
                record_id=decision_id,
                columns=(
                    "event_schedule_decision_id",
                    "event_schedule_decision_hash",
                    "outcome_schedule_plan_id",
                    "outcome_schedule_slot_id",
                    "track_key_hash",
                    "agent_id",
                    "event_id",
                    "causal_dedupe_key",
                    "disposition",
                    "record_json",
                ),
                values=(
                    decision_id,
                    decision["event_schedule_decision_hash"],
                    plan_id,
                    slot["outcome_schedule_slot_id"],
                    slot["track_key_hash"],
                    slot["agent_id"],
                    event["event_id"],
                    event["causal_dedupe_key"],
                    disposition,
                    decision_json,
                ),
                record_json=decision_json,
            )
    return plan


def _slot(
    conn: sqlite3.Connection,
    *,
    plan_id: str,
    agent_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan_row = conn.execute(
        "SELECT record_json FROM outcome_schedule_plans_v2 "
        "WHERE outcome_schedule_plan_id = ?",
        (plan_id,),
    ).fetchone()
    if plan_row is None:
        raise ValueError("outcome schedule plan is unavailable")
    slot_row = conn.execute(
        "SELECT record_json FROM outcome_schedule_slots_v2 "
        "WHERE outcome_schedule_plan_id = ? AND agent_id = ?",
        (plan_id, agent_id),
    ).fetchone()
    if slot_row is None:
        raise ValueError("outcome schedule slot is unavailable")
    return json.loads(plan_row[0]), json.loads(slot_row[0])


def _source_evidence(
    contract: Mapping[str, Any],
    raw: Mapping[str, Sequence[str]],
) -> list[str]:
    required = set(contract["required_source_ids"])
    if set(raw) != required:
        raise ValueError("source evidence must cover the exact required_source_ids")
    evidence: list[str] = []
    for source_id in sorted(required):
        values = raw[source_id]
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes))
            or not values
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise ValueError(f"required source {source_id} needs non-empty evidence")
        evidence.extend(values)
    if len(evidence) != len(set(evidence)):
        raise ValueError("source evidence IDs must be globally unique")
    return sorted(evidence)


def _freeze_scheduled_opportunity_locked(
    conn: sqlite3.Connection,
    *,
    outcome_schedule_plan_id: str,
    agent_id: str,
    qualification_predicate_version: str,
    member_refs: Sequence[Mapping[str, Any]],
    source_evidence_by_required_source_id: Mapping[str, Sequence[str]],
    projection_snapshot_hash: str,
    frozen_object_set_id: str | None = None,
    frozen_object_set_hash: str | None = None,
    runtime_authority_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze an AVAILABLE denominator immediately before one Agent call."""
    plan, slot = _slot(
        conn,
        plan_id=outcome_schedule_plan_id,
        agent_id=agent_id,
    )
    if slot["run_slot_kind"] != "OUTCOME_SCHEDULED":
        raise ValueError("DOWNSTREAM_ONLY slot cannot freeze an outcome opportunity")
    failure = conn.execute(
        "SELECT 1 FROM evaluation_opportunity_set_generation_failures_v2 "
        "WHERE outcome_schedule_slot_id = ?",
        (slot["outcome_schedule_slot_id"],),
    ).fetchone()
    if failure is not None:
        raise ValueError("scheduled opportunity already ended as UNAVAILABLE")
    contract = OUTCOME_CONTRACTS[agent_id]
    evidence_ids = _source_evidence(
        contract,
        source_evidence_by_required_source_id,
    )
    if not (
        isinstance(projection_snapshot_hash, str)
        and projection_snapshot_hash.startswith("sha256:")
        and len(projection_snapshot_hash) == 71
    ):
        raise ValueError("scheduled opportunity requires projection_snapshot_hash")
    record = freeze_evaluation_opportunity_set(
        conn,
        production_variant_roster_revision_id=plan[
            "production_variant_roster_revision_id"
        ],
        track_key_hash=slot["track_key_hash"],
        scheduled_sample_id=slot["scheduled_sample_id"],
        sample_origin="PRODUCTION_ACTIVE",
        as_of=plan["as_of"],
        member_refs=member_refs,
        required_source_evidence_ids=evidence_ids,
        qualification_predicate_version=_required_text(
            qualification_predicate_version,
            "qualification_predicate_version",
        ),
        generator_input_snapshot_hash=projection_snapshot_hash,
        frozen_object_set_id=frozen_object_set_id,
        frozen_object_set_hash=frozen_object_set_hash,
        runtime_authority_binding=runtime_authority_binding,
    )
    return {
        "run_allowed": True,
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "evaluation_opportunity_set_id": record["evaluation_opportunity_set_id"],
        "evaluation_opportunity_set_hash": record["evaluation_opportunity_set_hash"],
        "frozen_object_set_id": record["frozen_object_set_id"],
        "frozen_object_set_hash": record["frozen_object_set_hash"],
        "runtime_authority_binding": record.get("runtime_authority_binding"),
        "generation_attempt_id": None,
        "generation_attempt_hash": None,
    }


def freeze_scheduled_opportunity(
    conn: sqlite3.Connection,
    *,
    outcome_schedule_plan_id: str,
    agent_id: str,
    qualification_predicate_version: str,
    member_refs: Sequence[Mapping[str, Any]],
    source_evidence_by_required_source_id: Mapping[str, Sequence[str]],
    projection_snapshot_hash: str,
    frozen_object_set_id: str | None = None,
    frozen_object_set_hash: str | None = None,
    runtime_authority_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically commit the AVAILABLE terminal for one scheduled slot."""
    return _run_terminal_write(
        conn,
        lambda: _freeze_scheduled_opportunity_locked(
            conn,
            outcome_schedule_plan_id=outcome_schedule_plan_id,
            agent_id=agent_id,
            qualification_predicate_version=qualification_predicate_version,
            member_refs=member_refs,
            source_evidence_by_required_source_id=(
                source_evidence_by_required_source_id
            ),
            projection_snapshot_hash=projection_snapshot_hash,
            frozen_object_set_id=frozen_object_set_id,
            frozen_object_set_hash=frozen_object_set_hash,
            runtime_authority_binding=runtime_authority_binding,
        ),
    )


def create_no_evaluation_object_stage_skip(
    conn: sqlite3.Connection,
    *,
    outcome_schedule_plan_id: str,
    agent_id: str,
    recorded_at: str,
) -> dict[str, Any]:
    """Close one allowed empty opportunity without invoking or accepting an Agent."""
    if agent_id not in EMPTY_OPPORTUNITY_ALLOWED:
        raise ValueError(f"{agent_id} cannot use a no-evaluation-object stage skip")
    plan, slot = _slot(
        conn,
        plan_id=outcome_schedule_plan_id,
        agent_id=agent_id,
    )
    if slot["run_slot_kind"] != "OUTCOME_SCHEDULED":
        raise ValueError("DOWNSTREAM_ONLY slot cannot create an outcome stage skip")
    row = conn.execute(
        "SELECT record_json FROM evaluation_opportunity_sets_v2 "
        "WHERE scheduled_sample_id = ? AND opportunity_set_status = 'AVAILABLE'",
        (slot["scheduled_sample_id"],),
    ).fetchone()
    if row is None:
        raise ValueError("stage skip requires an AVAILABLE opportunity set")
    opportunity = json.loads(row[0])
    if opportunity.get("member_state") != "EMPTY" or opportunity.get("member_refs") != []:
        raise ValueError("stage skip requires the frozen opportunity set to be EMPTY")
    for field, expected in (
        ("agent_id", agent_id),
        ("track_key_hash", slot["track_key_hash"]),
        ("scheduled_sample_id", slot["scheduled_sample_id"]),
        ("sample_origin", "PRODUCTION_ACTIVE"),
    ):
        if opportunity.get(field) != expected:
            raise ValueError(f"stage skip opportunity {field} mismatch")
    recorded_at = _required_text(recorded_at, "recorded_at")
    _parse_timestamp(recorded_at, "recorded_at")
    if recorded_at != plan["prepared_at"]:
        raise ValueError("stage skip recorded_at must equal the frozen plan prepared_at")
    eligibility = append_outcome_eligibility_revision(
        conn,
        track_key_hash=slot["track_key_hash"],
        scheduled_sample_id=slot["scheduled_sample_id"],
        sample_origin="PRODUCTION_ACTIVE",
        disposition="EXOGENOUS_EXCLUSION",
        recorded_at=recorded_at,
        evaluation_opportunity_set_id=opportunity["evaluation_opportunity_set_id"],
        exclusion_or_failure_reason="NO_EVALUATION_OBJECT",
    )
    identity = {
        "graph_run_id": plan["graph_run_id"],
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
    }
    stage_skip_id = deterministic_id("no-evaluation-object-stage-skip", identity)
    without_hash = {
        "stage_skip_id": stage_skip_id,
        "schema_version": "no_evaluation_object_stage_skip_v2",
        "graph_run_id": plan["graph_run_id"],
        "outcome_schedule_plan_id": outcome_schedule_plan_id,
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "track_key_hash": slot["track_key_hash"],
        "agent_id": agent_id,
        "skip_reason": "NO_EVALUATION_OBJECT",
        "frozen_object_set_id": opportunity.get("frozen_object_set_id")
        or opportunity["evaluation_opportunity_set_id"],
        "frozen_object_set_hash": opportunity.get("frozen_object_set_hash")
        or opportunity["evaluation_opportunity_set_hash"],
        "member_count": 0,
        "model_invoked": False,
        "eligibility_audit_id": eligibility["audit_id"],
        "eligibility_audit_revision_id": eligibility["audit_revision_id"],
        "eligibility_audit_revision_hash": eligibility["audit_revision_hash"],
        "evidence_ids": opportunity["required_source_evidence_ids"],
        "causal_dedupe_key": canonical_hash(
            {
                "agent_id": agent_id,
                "scheduled_sample_id": slot["scheduled_sample_id"],
                "frozen_object_set_hash": opportunity[
                    "evaluation_opportunity_set_hash"
                ],
            }
        ),
        "recorded_at": recorded_at,
    }
    stage_skip = {**without_hash, "stage_skip_hash": canonical_hash(without_hash)}
    record_json = canonical_json(stage_skip)
    _insert_immutable(
        conn,
        table="no_evaluation_object_stage_skips_v2",
        id_column="stage_skip_id",
        record_id=stage_skip_id,
        columns=(
            "stage_skip_id",
            "stage_skip_hash",
            "graph_run_id",
            "outcome_schedule_plan_id",
            "outcome_schedule_slot_id",
            "scheduled_sample_id",
            "track_key_hash",
            "agent_id",
            "evaluation_opportunity_set_id",
            "eligibility_audit_revision_id",
            "recorded_at",
            "record_json",
        ),
        values=(
            stage_skip_id,
            stage_skip["stage_skip_hash"],
            plan["graph_run_id"],
            outcome_schedule_plan_id,
            slot["outcome_schedule_slot_id"],
            slot["scheduled_sample_id"],
            slot["track_key_hash"],
            agent_id,
            opportunity["evaluation_opportunity_set_id"],
            eligibility["audit_revision_id"],
            recorded_at,
            record_json,
        ),
        record_json=record_json,
    )
    operational = _append_stage_skip_operational_audit(
        conn,
        plan=plan,
        slot=slot,
        stage_skip=stage_skip,
        recorded_at=recorded_at,
    )
    return {
        "run_allowed": False,
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "stage_skip": stage_skip,
        "operational_opportunity_audit_id": operational[
            "operational_opportunity_audit_id"
        ],
        "operational_opportunity_audit_hash": operational[
            "operational_opportunity_audit_hash"
        ],
    }


def _append_stage_skip_operational_audit(
    conn: sqlite3.Connection,
    *,
    plan: Mapping[str, Any],
    slot: Mapping[str, Any],
    stage_skip: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    track_row = conn.execute(
        "SELECT contract_json FROM darwinian_v2_evaluation_tracks "
        "WHERE track_key_hash = ?",
        (slot["track_key_hash"],),
    ).fetchone()
    if track_row is None:
        raise ValueError("evaluation track is unavailable")
    track = json.loads(track_row[0])
    operational_id = deterministic_id(
        "operational-opportunity",
        {
            "graph_run_id": plan["graph_run_id"],
            "agent_id": slot["agent_id"],
            "run_slot_id": slot["run_slot_id"],
        },
    )
    without_hash = {
        "operational_opportunity_audit_id": operational_id,
        "graph_run_id": plan["graph_run_id"],
        "run_slot_id": slot["run_slot_id"],
        "production_variant_roster_id": plan["production_variant_roster_id"],
        "production_variant_roster_revision_id": plan[
            "production_variant_roster_revision_id"
        ],
        "execution_behavior_release_id": plan["execution_behavior_release_id"],
        "cohort_id": plan["cohort_id"],
        "language": plan["language"],
        "agent_id": slot["agent_id"],
        "track_key_hash": slot["track_key_hash"],
        "agent_contract_version": track["agent_contract_version"],
        "prompt_behavior_version": track["prompt_behavior_version"],
        "execution_behavior_version": track["execution_behavior_version"],
        "sample_origin": "PRODUCTION_ACTIVE",
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "production_reliability_eligible": False,
        "disposition": "EXOGENOUS_EXCLUSION",
        "accountable": False,
        "run_id": None,
        "accepted_output_kind": None,
        "accepted_output_id": None,
        "accepted_output_hash": None,
        "stage_skip_id": stage_skip["stage_skip_id"],
        "stage_skip_hash": stage_skip["stage_skip_hash"],
        "failure_reason": "NO_EVALUATION_OBJECT",
        "fallback_used": False,
        "as_of": plan["as_of"],
        "recorded_at": recorded_at,
    }
    record = {
        **without_hash,
        "operational_opportunity_audit_hash": canonical_hash(without_hash),
    }
    record_json = canonical_json(record)
    _insert_immutable(
        conn,
        table="operational_opportunity_audits_v2",
        id_column="operational_opportunity_audit_id",
        record_id=operational_id,
        columns=(
            "operational_opportunity_audit_id",
            "operational_opportunity_audit_hash",
            "graph_run_id",
            "run_slot_id",
            "production_variant_roster_id",
            "production_variant_roster_revision_id",
            "execution_behavior_release_id",
            "cohort_id",
            "language",
            "agent_id",
            "track_key_hash",
            "sample_origin",
            "run_slot_kind",
            "scheduled_sample_id",
            "production_reliability_eligible",
            "disposition",
            "accountable",
            "run_id",
            "accepted_output_id",
            "failure_reason",
            "fallback_used",
            "as_of",
            "recorded_at",
            "record_json",
        ),
        values=(
            operational_id,
            record["operational_opportunity_audit_hash"],
            plan["graph_run_id"],
            slot["run_slot_id"],
            plan["production_variant_roster_id"],
            plan["production_variant_roster_revision_id"],
            plan["execution_behavior_release_id"],
            plan["cohort_id"],
            plan["language"],
            slot["agent_id"],
            slot["track_key_hash"],
            "PRODUCTION_ACTIVE",
            "OUTCOME_SCHEDULED",
            slot["scheduled_sample_id"],
            0,
            "EXOGENOUS_EXCLUSION",
            0,
            None,
            None,
            "NO_EVALUATION_OBJECT",
            0,
            plan["as_of"],
            recorded_at,
            record_json,
        ),
        record_json=record_json,
    )
    return record


def _record_scheduled_opportunity_failure_locked(
    conn: sqlite3.Connection,
    *,
    outcome_schedule_plan_id: str,
    agent_id: str,
    qualification_predicate_version: str,
    source_evidence_by_required_source_id: Mapping[str, Sequence[str]],
    error_codes: Sequence[str],
    attempted_at: str,
) -> dict[str, Any]:
    """Persist a fail-closed pre-run generation attempt and exclusion audits."""
    plan, slot = _slot(
        conn,
        plan_id=outcome_schedule_plan_id,
        agent_id=agent_id,
    )
    if slot["run_slot_kind"] != "OUTCOME_SCHEDULED":
        raise ValueError("DOWNSTREAM_ONLY slot cannot record generation failure")
    existing_set = conn.execute(
        "SELECT 1 FROM evaluation_opportunity_sets_v2 WHERE scheduled_sample_id = ?",
        (slot["scheduled_sample_id"],),
    ).fetchone()
    if existing_set is not None:
        raise ValueError("scheduled opportunity is already AVAILABLE")
    errors = sorted(set(error_codes))
    if not errors or any(
        code not in OPPORTUNITY_GENERATION_FAILURE_CODES for code in errors
    ):
        raise ValueError("generation failure requires registered error_codes")
    attempted_at = _required_text(attempted_at, "attempted_at")
    _parse_timestamp(attempted_at, "attempted_at")
    if attempted_at != plan["prepared_at"]:
        raise ValueError(
            "generation failure attempted_at must equal the frozen plan prepared_at"
        )
    predicate_version = _required_text(
        qualification_predicate_version,
        "qualification_predicate_version",
    )
    contract = OUTCOME_CONTRACTS[agent_id]
    if predicate_version != contract["opportunity_set_contract_version"]:
        raise ValueError("generation failure qualification predicate version drift")
    evidence_ids = _source_evidence(
        contract,
        source_evidence_by_required_source_id,
    )
    identity = {
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "track_key_hash": slot["track_key_hash"],
    }
    attempt_id = deterministic_id("opportunity-generation-attempt", identity)
    without_hash = {
        "generation_attempt_id": attempt_id,
        "schema_version": "evaluation_opportunity_set_generation_failure_v2",
        "outcome_schedule_plan_id": outcome_schedule_plan_id,
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "track_key_hash": slot["track_key_hash"],
        "agent_id": agent_id,
        "opportunity_set_contract_version": contract[
            "opportunity_set_contract_version"
        ],
        "generator_contract_version": OPPORTUNITY_GENERATOR_CONTRACT_VERSION,
        "qualification_predicate_version": predicate_version,
        "attempted_at": attempted_at,
        "required_source_ids": list(contract["required_source_ids"]),
        "source_evidence_ids": evidence_ids,
        "error_codes": errors,
    }
    attempt = {
        **without_hash,
        "generation_attempt_hash": canonical_hash(without_hash),
    }
    attempt_json = canonical_json(attempt)
    _insert_immutable(
        conn,
        table="evaluation_opportunity_set_generation_failures_v2",
        id_column="generation_attempt_id",
        record_id=attempt_id,
        columns=(
            "generation_attempt_id",
            "generation_attempt_hash",
            "outcome_schedule_plan_id",
            "outcome_schedule_slot_id",
            "scheduled_sample_id",
            "track_key_hash",
            "agent_id",
            "attempted_at",
            "record_json",
        ),
        values=(
            attempt_id,
            attempt["generation_attempt_hash"],
            outcome_schedule_plan_id,
            slot["outcome_schedule_slot_id"],
            slot["scheduled_sample_id"],
            slot["track_key_hash"],
            agent_id,
            attempted_at,
            attempt_json,
        ),
        record_json=attempt_json,
    )
    eligibility = append_outcome_eligibility_revision(
        conn,
        track_key_hash=slot["track_key_hash"],
        scheduled_sample_id=slot["scheduled_sample_id"],
        sample_origin="PRODUCTION_ACTIVE",
        disposition="EXOGENOUS_EXCLUSION",
        recorded_at=attempted_at,
        evaluation_opportunity_set_id=None,
        exclusion_or_failure_reason="OPPORTUNITY_SET_UNAVAILABLE",
    )
    operational = _append_generation_failure_operational_audit(
        conn,
        plan=plan,
        slot=slot,
        recorded_at=attempted_at,
    )
    return {
        "run_allowed": False,
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "evaluation_opportunity_set_id": None,
        "evaluation_opportunity_set_hash": None,
        "generation_attempt_id": attempt_id,
        "generation_attempt_hash": attempt["generation_attempt_hash"],
        "eligibility_audit_revision_id": eligibility["audit_revision_id"],
        "eligibility_audit_revision_hash": eligibility["audit_revision_hash"],
        "operational_opportunity_audit_id": operational[
            "operational_opportunity_audit_id"
        ],
        "operational_opportunity_audit_hash": operational[
            "operational_opportunity_audit_hash"
        ],
    }


def record_scheduled_opportunity_failure(
    conn: sqlite3.Connection,
    *,
    outcome_schedule_plan_id: str,
    agent_id: str,
    qualification_predicate_version: str,
    source_evidence_by_required_source_id: Mapping[str, Sequence[str]],
    error_codes: Sequence[str],
    attempted_at: str,
) -> dict[str, Any]:
    """Atomically commit the GENERATION_FAILURE terminal for one scheduled slot."""
    return _run_terminal_write(
        conn,
        lambda: _record_scheduled_opportunity_failure_locked(
            conn,
            outcome_schedule_plan_id=outcome_schedule_plan_id,
            agent_id=agent_id,
            qualification_predicate_version=qualification_predicate_version,
            source_evidence_by_required_source_id=(
                source_evidence_by_required_source_id
            ),
            error_codes=error_codes,
            attempted_at=attempted_at,
        ),
    )


def _append_generation_failure_operational_audit(
    conn: sqlite3.Connection,
    *,
    plan: Mapping[str, Any],
    slot: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    track_row = conn.execute(
        "SELECT contract_json FROM darwinian_v2_evaluation_tracks "
        "WHERE track_key_hash = ?",
        (slot["track_key_hash"],),
    ).fetchone()
    if track_row is None:
        raise ValueError("evaluation track is unavailable")
    track = json.loads(track_row[0])
    operational_id = deterministic_id(
        "operational-opportunity",
        {
            "graph_run_id": plan["graph_run_id"],
            "agent_id": slot["agent_id"],
            "run_slot_id": slot["run_slot_id"],
        },
    )
    without_hash = {
        "operational_opportunity_audit_id": operational_id,
        "graph_run_id": plan["graph_run_id"],
        "run_slot_id": slot["run_slot_id"],
        "production_variant_roster_id": plan["production_variant_roster_id"],
        "production_variant_roster_revision_id": plan[
            "production_variant_roster_revision_id"
        ],
        "execution_behavior_release_id": plan["execution_behavior_release_id"],
        "cohort_id": plan["cohort_id"],
        "language": plan["language"],
        "agent_id": slot["agent_id"],
        "track_key_hash": slot["track_key_hash"],
        "agent_contract_version": track["agent_contract_version"],
        "prompt_behavior_version": track["prompt_behavior_version"],
        "execution_behavior_version": track["execution_behavior_version"],
        "sample_origin": "PRODUCTION_ACTIVE",
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "production_reliability_eligible": True,
        "disposition": "EXOGENOUS_EXCLUSION",
        "accountable": False,
        "run_id": None,
        "accepted_output_kind": None,
        "accepted_output_id": None,
        "accepted_output_hash": None,
        "stage_skip_id": None,
        "stage_skip_hash": None,
        "failure_reason": "OPPORTUNITY_SET_UNAVAILABLE",
        "fallback_used": False,
        "as_of": plan["as_of"],
        "recorded_at": recorded_at,
    }
    record = {
        **without_hash,
        "operational_opportunity_audit_hash": canonical_hash(without_hash),
    }
    record_json = canonical_json(record)
    _insert_immutable(
        conn,
        table="operational_opportunity_audits_v2",
        id_column="operational_opportunity_audit_id",
        record_id=operational_id,
        columns=(
            "operational_opportunity_audit_id",
            "operational_opportunity_audit_hash",
            "graph_run_id",
            "run_slot_id",
            "production_variant_roster_id",
            "production_variant_roster_revision_id",
            "execution_behavior_release_id",
            "cohort_id",
            "language",
            "agent_id",
            "track_key_hash",
            "sample_origin",
            "run_slot_kind",
            "scheduled_sample_id",
            "production_reliability_eligible",
            "disposition",
            "accountable",
            "run_id",
            "accepted_output_id",
            "failure_reason",
            "fallback_used",
            "as_of",
            "recorded_at",
            "record_json",
        ),
        values=(
            operational_id,
            record["operational_opportunity_audit_hash"],
            plan["graph_run_id"],
            slot["run_slot_id"],
            plan["production_variant_roster_id"],
            plan["production_variant_roster_revision_id"],
            plan["execution_behavior_release_id"],
            plan["cohort_id"],
            plan["language"],
            slot["agent_id"],
            slot["track_key_hash"],
            "PRODUCTION_ACTIVE",
            "OUTCOME_SCHEDULED",
            slot["scheduled_sample_id"],
            1,
            "EXOGENOUS_EXCLUSION",
            0,
            None,
            None,
            "OPPORTUNITY_SET_UNAVAILABLE",
            0,
            plan["as_of"],
            recorded_at,
            record_json,
        ),
        record_json=record_json,
    )
    return record


__all__ = [
    "create_no_evaluation_object_stage_skip",
    "freeze_scheduled_opportunity",
    "prepare_outcome_schedule_plan",
    "record_scheduled_opportunity_failure",
]

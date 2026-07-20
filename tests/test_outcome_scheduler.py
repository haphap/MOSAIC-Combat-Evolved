from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from mosaic.dataflows.outcome_runtime_inputs import (
    expected_qualification_predicate_version,
)
from mosaic.scorecard.darwinian_v2 import canonical_hash, deterministic_id
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.store import ScorecardStore


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


def _registered(tmp_path: Path) -> tuple[ScorecardStore, dict, str]:
    store = ScorecardStore(tmp_path / "scorecard.db")
    cohort = "cohort_default"
    language = "zh"
    effective_at = "2026-07-17T09:00:00+08:00"
    roster_id = deterministic_id(
        "production-variant-roster",
        {"cohort_id": cohort, "language": language},
    )
    without_hash = {
        "schema_version": "darwinian_runtime_binding_v2",
        "production_variant_roster_id": roster_id,
        "cohort_id": cohort,
        "language": language,
        "execution_behavior_release_id": "release-1",
        "prompt_repo_id": "private-prompts",
        "prompt_repo_revision": "a" * 40,
        "effective_at": effective_at,
        "agent_behavior_bindings": _bindings(),
    }
    binding = {**without_hash, "binding_hash": canonical_hash(without_hash)}
    prepared = store.prepare_darwinian_v2_production_variant(
        binding=binding,
        as_of=effective_at,
    )
    return (
        store,
        binding,
        prepared["roster_revision"]["production_variant_roster_revision_id"],
    )


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


def _source_evidence(agent_id: str) -> dict[str, list[str]]:
    return {
        source_id: [f"evidence:{agent_id}:{index}"]
        for index, source_id in enumerate(
            OUTCOME_CONTRACTS[agent_id]["required_source_ids"]
        )
    }


def _projection_hash(agent_id: str) -> str:
    return canonical_hash({"projection_agent": agent_id})


def _execution_freeze_kwargs(plan: dict) -> dict:
    return {
        "outcome_schedule_plan_id": plan["outcome_schedule_plan_id"],
        "agent_id": "autonomous_execution",
        "qualification_predicate_version": (
            expected_qualification_predicate_version("autonomous_execution")
        ),
        "member_refs": [
            {
                "order_intent_id": "intent-concurrent",
                "ts_code": "600006.SH",
                "action": "BUY",
                "requested_delta_weight": 0.1,
            }
        ],
        "source_evidence_by_required_source_id": _source_evidence(
            "autonomous_execution"
        ),
        "projection_snapshot_hash": _projection_hash("autonomous_execution"),
        "runtime_authority_binding": _runtime_authority_binding(
            "autonomous_execution"
        ),
    }


def _execution_failure_kwargs(plan: dict, as_of: str) -> dict:
    return {
        "outcome_schedule_plan_id": plan["outcome_schedule_plan_id"],
        "agent_id": "autonomous_execution",
        "qualification_predicate_version": (
            expected_qualification_predicate_version("autonomous_execution")
        ),
        "source_evidence_by_required_source_id": _source_evidence(
            "autonomous_execution"
        ),
        "error_codes": ["REQUIRED_DATA_UNAVAILABLE"],
        "attempted_at": as_of,
    }


def _runtime_authority_binding(agent_id: str) -> dict[str, str]:
    return {
        "source_tool_id": {
            "alpha_discovery": "get_alpha_candidate_snapshot",
            "cro": "get_cro_risk_snapshot",
            "autonomous_execution": "get_execution_snapshot",
            "cio": "get_cio_decision_snapshot",
        }[agent_id],
        "source_snapshot_hash": canonical_hash({"agent_id": agent_id, "kind": "source"}),
        "candidate_scope_hash": canonical_hash({"agent_id": agent_id, "kind": "scope"}),
        "candidate_universe_hash": canonical_hash(
            {"agent_id": agent_id, "kind": "universe"}
        ),
        "upstream_accepted_output_refs_hash": canonical_hash(
            {"agent_id": agent_id, "kind": "upstream"}
        ),
    }


def _event(event_id: str, causal_key: str, priority_rank: int) -> dict:
    return {
        "event_id": event_id,
        "causal_dedupe_key": causal_key,
        "event_registry_version": "china_verified_event_registry_v2",
        "event_priority_version": "china_event_priority_v2",
        "priority_rank": priority_rank,
        "published_at": "2026-07-17T08:00:00+08:00",
        "source_evidence_ids": [f"official:{event_id}"],
        "pit_status": "VERIFIED",
    }


def _event_coverage(
    candidates_by_agent: dict[str, list[dict]] | None = None,
) -> dict[str, dict]:
    candidates_by_agent = candidates_by_agent or {}
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
            "candidates": candidates_by_agent.get(agent_id, []),
        }
    return result


def test_schedule_plan_covers_28_and_event_exclusions_do_not_reenter(
    tmp_path: Path,
) -> None:
    store, _, revision_id = _registered(tmp_path)
    as_of = "2026-07-17T09:00:00+08:00"
    events = _event_coverage({
        "china": [
            _event("china-low-priority", "causal:low", 5),
            _event("china-high-priority", "causal:high", 0),
        ]
    })
    plan = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id="graph-1",
        as_of=as_of,
        prepared_at=as_of,
        trading_calendar_snapshot=_calendar_snapshot(as_of),
        verified_event_candidates=events,
    )
    assert len(plan["slots"]) == 28
    assert {slot["agent_id"] for slot in plan["slots"]} == set(OUTCOME_CONTRACTS)
    china = next(slot for slot in plan["slots"] if slot["agent_id"] == "china")
    assert china["run_slot_kind"] == "OUTCOME_SCHEDULED"
    assert china["trigger_event"]["event_id"] == "china-high-priority"
    assert china["excluded_events"][0]["event_id"] == "china-low-priority"
    assert china["excluded_events"][0]["exclusion_reason"] == "OVERLAPPING_WINDOW"

    retry = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id="graph-1",
        as_of=as_of,
        prepared_at=as_of,
        trading_calendar_snapshot=_calendar_snapshot(as_of),
        verified_event_candidates=events,
    )
    assert retry == plan

    next_as_of = "2026-07-20T09:00:00+08:00"
    next_plan = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id="graph-2",
        as_of=next_as_of,
        prepared_at=next_as_of,
        trading_calendar_snapshot=_calendar_snapshot(next_as_of),
        verified_event_candidates=events,
    )
    next_china = next(
        slot for slot in next_plan["slots"] if slot["agent_id"] == "china"
    )
    assert next_china["run_slot_kind"] == "DOWNSTREAM_ONLY"
    assert next_china["scheduled_sample_id"] is None
    assert {item["exclusion_reason"] for item in next_china["excluded_events"]} == {
        "ALREADY_SCHEDULED"
    }

    with store._connect() as conn:
        decisions = conn.execute(
            "SELECT event_id, disposition FROM outcome_event_schedule_decisions_v2 "
            "ORDER BY event_id"
        ).fetchall()
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute("DELETE FROM outcome_schedule_plans_v2")
    assert [tuple(row) for row in decisions] == [
        ("china-high-priority", "SELECTED"),
        ("china-low-priority", "OVERLAPPING_WINDOW"),
    ]


def test_scheduled_opportunity_failure_is_audited_and_blocks_freeze(
    tmp_path: Path,
) -> None:
    store, _, revision_id = _registered(tmp_path)
    as_of = "2026-07-17T09:00:00+08:00"
    plan = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id="graph-failure",
        as_of=as_of,
        prepared_at=as_of,
        trading_calendar_snapshot=_calendar_snapshot(as_of),
        verified_event_candidates=_event_coverage(),
    )
    execution = next(
        slot
        for slot in plan["slots"]
        if slot["agent_id"] == "autonomous_execution"
    )
    assert execution["run_slot_kind"] == "OUTCOME_SCHEDULED"

    with pytest.raises(ValueError, match="frozen plan prepared_at"):
        store.record_scheduled_outcome_opportunity_failure(
            outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
            agent_id="autonomous_execution",
            qualification_predicate_version=expected_qualification_predicate_version(
                "autonomous_execution"
            ),
            source_evidence_by_required_source_id=_source_evidence(
                "autonomous_execution"
            ),
            error_codes=["REQUIRED_DATA_UNAVAILABLE"],
            attempted_at="2026-07-17T10:00:00+08:00",
        )

    with pytest.raises(ValueError, match="qualification predicate version drift"):
        store.record_scheduled_outcome_opportunity_failure(
            outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
            agent_id="autonomous_execution",
            qualification_predicate_version="forged-predicate-v1",
            source_evidence_by_required_source_id=_source_evidence(
                "autonomous_execution"
            ),
            error_codes=["REQUIRED_DATA_UNAVAILABLE"],
            attempted_at=as_of,
        )

    failure = store.record_scheduled_outcome_opportunity_failure(
        outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
        agent_id="autonomous_execution",
        qualification_predicate_version=expected_qualification_predicate_version(
            "autonomous_execution"
        ),
        source_evidence_by_required_source_id=_source_evidence(
            "autonomous_execution"
        ),
        error_codes=["REQUIRED_DATA_UNAVAILABLE"],
        attempted_at=as_of,
    )
    assert failure["run_allowed"] is False
    assert failure["evaluation_opportunity_set_id"] is None
    retry = store.record_scheduled_outcome_opportunity_failure(
        outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
        agent_id="autonomous_execution",
        qualification_predicate_version=expected_qualification_predicate_version(
            "autonomous_execution"
        ),
        source_evidence_by_required_source_id=_source_evidence(
            "autonomous_execution"
        ),
        error_codes=["REQUIRED_DATA_UNAVAILABLE"],
        attempted_at=as_of,
    )
    assert retry == failure
    with pytest.raises(ValueError, match="already ended as UNAVAILABLE"):
        store.freeze_scheduled_outcome_opportunity(
            outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
            agent_id="autonomous_execution",
            qualification_predicate_version=expected_qualification_predicate_version(
                "autonomous_execution"
            ),
            member_refs=[
                {
                    "order_intent_id": "intent-1",
                    "ts_code": "600006.SH",
                    "action": "BUY",
                    "requested_delta_weight": 0.1,
                }
            ],
            source_evidence_by_required_source_id=_source_evidence(
                "autonomous_execution"
            ),
            projection_snapshot_hash=_projection_hash("autonomous_execution"),
            runtime_authority_binding=_runtime_authority_binding(
                "autonomous_execution"
            ),
        )

    with store._connect() as conn:
        attempts = conn.execute(
            "SELECT COUNT(*) FROM evaluation_opportunity_set_generation_failures_v2"
        ).fetchone()[0]
        eligibility = conn.execute(
            "SELECT disposition, opportunity_set_status "
            "FROM agent_outcome_eligibility_revisions_v2"
        ).fetchall()
        operational = conn.execute(
            "SELECT disposition, accountable, failure_reason "
            "FROM operational_opportunity_audits_v2"
        ).fetchall()
    assert attempts == 1
    assert [tuple(row) for row in eligibility] == [
        ("EXOGENOUS_EXCLUSION", "UNAVAILABLE")
    ]
    assert [tuple(row) for row in operational] == [
        ("EXOGENOUS_EXCLUSION", 0, "OPPORTUNITY_SET_UNAVAILABLE")
    ]


def test_concurrent_identical_available_terminal_retries_are_idempotent(
    tmp_path: Path,
) -> None:
    store, _, revision_id = _registered(tmp_path)
    as_of = "2026-07-17T09:00:00+08:00"
    plan = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id="graph-concurrent-available",
        as_of=as_of,
        prepared_at=as_of,
        trading_calendar_snapshot=_calendar_snapshot(as_of),
        verified_event_candidates=_event_coverage(),
    )
    barrier = Barrier(2)

    def freeze() -> dict:
        barrier.wait(timeout=5)
        return store.freeze_scheduled_outcome_opportunity(
            **_execution_freeze_kwargs(plan)
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: freeze(), range(2)))

    assert results[0] == results[1]
    with store._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM evaluation_opportunity_sets_v2 "
            "WHERE scheduled_sample_id = ?",
            (results[0]["scheduled_sample_id"],),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM evaluation_authority_events_v2 "
            "WHERE event_kind = 'OPPORTUNITY_FROZEN' "
            "AND scheduled_sample_id = ?",
            (results[0]["scheduled_sample_id"],),
        ).fetchone()[0] == 1
        slot = conn.execute(
            "SELECT outcome_schedule_plan_id, track_key_hash, agent_id "
            "FROM outcome_schedule_slots_v2 WHERE outcome_schedule_slot_id = ?",
            (results[0]["outcome_schedule_slot_id"],),
        ).fetchone()
        with pytest.raises(
            sqlite3.IntegrityError,
            match="scheduled_opportunity_terminal_conflict",
        ):
            conn.execute(
                "INSERT INTO evaluation_opportunity_set_generation_failures_v2 ("
                "generation_attempt_id, generation_attempt_hash, "
                "outcome_schedule_plan_id, outcome_schedule_slot_id, "
                "scheduled_sample_id, track_key_hash, agent_id, attempted_at, "
                "record_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "forged-opposite-terminal",
                    "sha256:" + "0" * 64,
                    slot[0],
                    results[0]["outcome_schedule_slot_id"],
                    results[0]["scheduled_sample_id"],
                    slot[1],
                    slot[2],
                    as_of,
                    "{}",
                ),
            )


def test_concurrent_opposite_terminals_commit_exactly_one_outcome(
    tmp_path: Path,
) -> None:
    store, _, revision_id = _registered(tmp_path)
    as_of = "2026-07-17T09:00:00+08:00"
    plan = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id="graph-concurrent-opposite",
        as_of=as_of,
        prepared_at=as_of,
        trading_calendar_snapshot=_calendar_snapshot(as_of),
        verified_event_candidates=_event_coverage(),
    )
    barrier = Barrier(2)

    def terminate(kind: str) -> tuple[str, str, dict | None]:
        barrier.wait(timeout=5)
        try:
            if kind == "AVAILABLE":
                result = store.freeze_scheduled_outcome_opportunity(
                    **_execution_freeze_kwargs(plan)
                )
            else:
                result = store.record_scheduled_outcome_opportunity_failure(
                    **_execution_failure_kwargs(plan, as_of)
                )
            return "COMMITTED", kind, result
        except ValueError as exc:
            return "CONFLICT", kind, {"message": str(exc)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(terminate, ("AVAILABLE", "GENERATION_FAILURE")))

    assert [result[0] for result in results].count("COMMITTED") == 1
    assert [result[0] for result in results].count("CONFLICT") == 1
    conflict = next(result for result in results if result[0] == "CONFLICT")
    assert (
        "already AVAILABLE" in conflict[2]["message"]
        or "already ended as UNAVAILABLE" in conflict[2]["message"]
    )
    with store._connect() as conn:
        available_count = conn.execute(
            "SELECT COUNT(*) FROM evaluation_opportunity_sets_v2 "
            "WHERE agent_id = 'autonomous_execution'"
        ).fetchone()[0]
        failure_count = conn.execute(
            "SELECT COUNT(*) FROM evaluation_opportunity_set_generation_failures_v2 "
            "WHERE agent_id = 'autonomous_execution'"
        ).fetchone()[0]
        trigger_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }
    assert available_count + failure_count == 1
    assert {
        "opportunity_available_excludes_generation_failure_v2",
        "generation_failure_excludes_opportunity_available_v2",
    } <= trigger_names


def test_allowed_empty_opportunity_creates_unique_stage_skip_without_output(
    tmp_path: Path,
) -> None:
    store, _, revision_id = _registered(tmp_path)
    as_of = "2026-07-17T09:00:00+08:00"
    plan = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id="graph-stage-skip",
        as_of=as_of,
        prepared_at=as_of,
        trading_calendar_snapshot=_calendar_snapshot(as_of),
        verified_event_candidates=_event_coverage(),
    )
    frozen = store.freeze_scheduled_outcome_opportunity(
        outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
        agent_id="autonomous_execution",
        qualification_predicate_version=expected_qualification_predicate_version(
            "autonomous_execution"
        ),
        member_refs=[],
        source_evidence_by_required_source_id=_source_evidence(
            "autonomous_execution"
        ),
        projection_snapshot_hash=_projection_hash("autonomous_execution"),
        runtime_authority_binding=_runtime_authority_binding(
            "autonomous_execution"
        ),
    )
    assert frozen["run_allowed"] is True
    with store._connect() as conn:
        frozen_record = json.loads(
            conn.execute(
                "SELECT record_json FROM evaluation_opportunity_sets_v2 "
                "WHERE evaluation_opportunity_set_id = ?",
                (frozen["evaluation_opportunity_set_id"],),
            ).fetchone()[0]
        )
    assert frozen_record["generator_input_snapshot_hash"] == _projection_hash(
        "autonomous_execution"
    )

    with pytest.raises(ValueError, match="frozen plan prepared_at"):
        store.create_no_evaluation_object_stage_skip(
            outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
            agent_id="autonomous_execution",
            recorded_at="2026-07-17T10:00:00+08:00",
        )

    skipped = store.create_no_evaluation_object_stage_skip(
        outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
        agent_id="autonomous_execution",
        recorded_at=as_of,
    )
    retry = store.create_no_evaluation_object_stage_skip(
        outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
        agent_id="autonomous_execution",
        recorded_at=as_of,
    )
    assert retry == skipped
    assert skipped["run_allowed"] is False
    assert skipped["stage_skip"]["model_invoked"] is False
    assert skipped["stage_skip"]["member_count"] == 0
    assert skipped["stage_skip"]["skip_reason"] == "NO_EVALUATION_OBJECT"
    assert (
        skipped["stage_skip"]["frozen_object_set_id"]
        == frozen["evaluation_opportunity_set_id"]
    )

    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM accepted_agent_outputs_v2").fetchone()[0] == 0
        eligibility = dict(
            conn.execute(
                "SELECT disposition, opportunity_set_status, record_json "
                "FROM agent_outcome_eligibility_revisions_v2"
            ).fetchone()
        )
        operational = dict(
            conn.execute(
                "SELECT disposition, accountable, production_reliability_eligible, "
                "failure_reason, record_json FROM operational_opportunity_audits_v2"
            ).fetchone()
        )
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute("DELETE FROM no_evaluation_object_stage_skips_v2")
    assert eligibility["disposition"] == "EXOGENOUS_EXCLUSION"
    assert eligibility["opportunity_set_status"] == "AVAILABLE"
    assert operational["disposition"] == "EXOGENOUS_EXCLUSION"
    assert operational["accountable"] == 0
    assert operational["production_reliability_eligible"] == 0
    assert operational["failure_reason"] == "NO_EVALUATION_OBJECT"


def test_nonempty_or_unapproved_agent_cannot_stage_skip(tmp_path: Path) -> None:
    store, _, revision_id = _registered(tmp_path)
    as_of = "2026-07-17T09:00:00+08:00"
    plan = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id="graph-invalid-stage-skip",
        as_of=as_of,
        prepared_at=as_of,
        trading_calendar_snapshot=_calendar_snapshot(as_of),
        verified_event_candidates=_event_coverage(),
    )
    execution_member = [
        {
            "order_intent_id": "intent-1",
            "ts_code": "600006.SH",
            "action": "BUY",
            "requested_delta_weight": 0.1,
        }
    ]
    with pytest.raises(ValueError, match="server-owned runtime authority"):
        store.freeze_scheduled_outcome_opportunity(
            outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
            agent_id="autonomous_execution",
            qualification_predicate_version=expected_qualification_predicate_version(
                "autonomous_execution"
            ),
            member_refs=execution_member,
            source_evidence_by_required_source_id=_source_evidence(
                "autonomous_execution"
            ),
            projection_snapshot_hash=_projection_hash("autonomous_execution"),
        )
    store.freeze_scheduled_outcome_opportunity(
        outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
        agent_id="autonomous_execution",
        qualification_predicate_version=expected_qualification_predicate_version(
            "autonomous_execution"
        ),
        member_refs=execution_member,
        source_evidence_by_required_source_id=_source_evidence(
            "autonomous_execution"
        ),
        projection_snapshot_hash=_projection_hash("autonomous_execution"),
        runtime_authority_binding=_runtime_authority_binding(
            "autonomous_execution"
        ),
    )
    with pytest.raises(ValueError, match="to be EMPTY"):
        store.create_no_evaluation_object_stage_skip(
            outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
            agent_id="autonomous_execution",
            recorded_at=as_of,
        )
    with pytest.raises(ValueError, match="cannot use"):
        store.create_no_evaluation_object_stage_skip(
            outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
            agent_id="cio",
            recorded_at=as_of,
        )


def test_calendar_snapshot_is_hash_and_pit_checked(tmp_path: Path) -> None:
    store, _, revision_id = _registered(tmp_path)
    as_of = "2026-07-17T09:00:00+08:00"
    snapshot = _calendar_snapshot(as_of)
    snapshot["pit_status"] = "UNVERIFIED"
    with pytest.raises(ValueError, match="hash mismatch"):
        store.prepare_outcome_schedule_plan(
            production_variant_roster_revision_id=revision_id,
            graph_run_id="graph-invalid-calendar",
            as_of=as_of,
            prepared_at=as_of,
            trading_calendar_snapshot=snapshot,
            verified_event_candidates=_event_coverage(),
        )


def test_schedule_plan_preparation_is_bound_to_the_as_of_session(
    tmp_path: Path,
) -> None:
    store, _, revision_id = _registered(tmp_path)
    as_of = "2026-07-17T09:00:00+08:00"
    for prepared_at in (
        "2026-07-17T08:59:59+08:00",
        "2026-07-18T09:00:00+08:00",
    ):
        with pytest.raises(ValueError, match="on the as_of date"):
            store.prepare_outcome_schedule_plan(
                production_variant_roster_revision_id=revision_id,
                graph_run_id=f"graph-invalid-preparation:{prepared_at}",
                as_of=as_of,
                prepared_at=prepared_at,
                trading_calendar_snapshot=_calendar_snapshot(as_of),
                verified_event_candidates=_event_coverage(),
            )

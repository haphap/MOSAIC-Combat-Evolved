from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from mosaic.scorecard.darwinian_v2 import (
    canonical_hash,
    deterministic_id,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.store import ScorecardStore


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
                "claim_refs": [f"claim-{agent_id}"],
                "deterministic_data_quality": 0.9,
            }
            for component in composition["components"]
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


def _attach_accepted_records(state: dict) -> None:
    plan = state["outcome_schedule_plan"]
    binding = state["darwinian_runtime_binding"]
    audits = state["agent_run_audits"]
    skipped = set(state["outcome_stage_skips"])
    records: list[dict] = []
    refs: dict[str, dict] = {}
    for slot in plan["slots"]:
        agent_id = slot["agent_id"]
        if agent_id in skipped:
            continue
        accepted_kinds = (
            ("CIO_PROPOSAL", "CIO_FINAL")
            if agent_id == "cio"
            else (OUTCOME_CONTRACTS[agent_id]["accepted_output_kind"],)
        )
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
            owner_field = {
                "STANDARD_SECTOR_SELECTION": "sector_agent_id",
                "RELATIONSHIP_GRAPH": "relationship_agent_id",
                "SUPERINVESTOR_SELECTION": "superinvestor_agent_id",
            }.get(accepted_kind, "agent_id")
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
                "output": {
                    "payload": {
                        owner_field: agent_id,
                        "fixture_output_kind": accepted_kind,
                    },
                    "evidence_bundle_ids": [
                        f"evidence-bundle:fixture:{agent_id}:{accepted_kind}"
                    ],
                    "causal_dedupe_keys": [canonical_hash(agent_id)],
                },
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
) -> tuple[int, int]:
    binding = state["darwinian_runtime_binding"]
    as_of = "2026-07-17T09:00:00+08:00"
    prepared = store.prepare_darwinian_v2_production_variant(
        binding=binding,
        as_of=as_of,
    )
    revision_id = prepared["roster_revision"][
        "production_variant_roster_revision_id"
    ]
    plan = store.prepare_outcome_schedule_plan(
        production_variant_roster_revision_id=revision_id,
        graph_run_id=state["trace_id"],
        as_of=as_of,
        prepared_at=as_of,
        trading_calendar_snapshot=_calendar_snapshot(as_of),
        verified_event_candidates=_event_coverage(),
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
        store.freeze_scheduled_outcome_opportunity(
            outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
            agent_id=agent_id,
            qualification_predicate_version=f"{agent_id}_qualification_v2",
            member_refs=(
                []
                if agent_id == stage_skip_agent
                else [{"member_id": f"member:{agent_id}"}]
            ),
            source_evidence_by_required_source_id=source_evidence,
            projection_snapshot_hash=canonical_hash(
                {"projection_agent": agent_id, "as_of": as_of}
            ),
        )
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
    state["accepted_output_records"][0]["output"]["payload"][
        "fixture_output_kind"
    ] = "TAMPERED"

    with pytest.raises(ValueError, match="accepted output hash mismatch"):
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

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from mosaic.dataflows.outcome_runtime_inputs import (
    expected_qualification_predicate_version,
)
from mosaic.scorecard.darwinian_updates import (
    LIVE_SOURCE_TOOL_BY_AGENT,
    append_agent_outcome_label,
    append_outcome_eligibility_revision,
    append_realized_outcome_observation,
    compute_outcome_utility,
    derive_darwin_calendar_window,
    freeze_evaluation_opportunity_set,
    publish_usage_weight_updates,
    refresh_evaluation_windows,
)
from mosaic.scorecard.darwinian_v2 import (
    canonical_hash,
    deterministic_id,
    get_production_weight_snapshot,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.outcome_contracts import (
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


def _darwin_trading_calendar() -> tuple[list[str], str]:
    dates: list[str] = []
    current = date(2010, 1, 4)
    end = date(2025, 1, 31)
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current += timedelta(days=1)
    cutoff_index = max(
        index
        for index, value in enumerate(dates)
        if value >= "2025-01-01" and (index + 1) % 5 == 0
    )
    return dates, f"{dates[cutoff_index]}T15:00:00+08:00"


def test_darwin_update_calendar_is_fixed_to_1260_days_and_five_day_slots() -> None:
    trading_dates, cutoff_at = _darwin_trading_calendar()
    window = derive_darwin_calendar_window(
        trading_dates=trading_dates,
        cutoff_at=cutoff_at,
        require_update_slot=True,
    )
    assert window["maximum_lookback_trading_days"] == 1260
    assert window["update_slot_id"].startswith(
        "darwin-update-slot:cn_a_share_trading_calendar_v1:"
    )
    cutoff_index = trading_dates.index(cutoff_at[:10])
    with pytest.raises(ValueError, match="not a registered five-session"):
        derive_darwin_calendar_window(
            trading_dates=trading_dates,
            cutoff_at=f"{trading_dates[cutoff_index - 1]}T15:00:00+08:00",
            require_update_slot=True,
        )
    with pytest.raises(ValueError, match="fewer than 1260"):
        derive_darwin_calendar_window(
            trading_dates=trading_dates[:100],
            cutoff_at=f"{trading_dates[99]}T15:00:00+08:00",
            require_update_slot=False,
        )


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


def _registered(tmp_path: Path) -> tuple[ScorecardStore, dict]:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2020-01-01T00:00:00+08:00",
    )
    return store, revision


def _track_by_agent(conn: sqlite3.Connection, revision: dict) -> dict[str, str]:
    placeholders = ",".join("?" for _ in revision["evaluation_track_key_hashes"])
    rows = conn.execute(
        f"SELECT agent_id, track_key_hash FROM darwinian_v2_evaluation_tracks "
        f"WHERE track_key_hash IN ({placeholders})",
        tuple(revision["evaluation_track_key_hashes"]),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _insert_scheduled_acceptance(
    conn: sqlite3.Connection,
    *,
    revision: dict,
    track_hash: str,
    agent_id: str,
    scheduled_sample_id: str,
    opportunity: dict,
) -> str:
    contract = OUTCOME_CONTRACTS[agent_id]
    accepted_id = f"accepted:{scheduled_sample_id}"
    record_without_hash = {
        "accepted_output_id": accepted_id,
        "graph_run_id": f"graph:{scheduled_sample_id}",
        "run_id": f"run:{scheduled_sample_id}",
        "run_slot_id": f"slot:{scheduled_sample_id}",
        "operational_opportunity_audit_id": f"operational:{scheduled_sample_id}",
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": revision[
            "production_variant_roster_revision_id"
        ],
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": "cohort_default",
        "language": "zh",
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
        "runtime_opportunity_authority": opportunity.get(
            "runtime_authority_binding"
        ),
        "as_of": "2024-01-02",
        "accepted_at": "2024-01-02T15:00:00+08:00",
        "output": {
            "payload": {
                "agent_id": agent_id,
                "direction": "SUPPORTIVE",
                "strength": 5,
                "confidence": 0.8,
            }
        },
    }
    record = {
        **record_without_hash,
        "accepted_output_hash": canonical_hash(record_without_hash),
    }
    conn.execute(
        """
        INSERT INTO accepted_agent_outputs_v2 (
            accepted_output_id, accepted_output_hash, graph_run_id, run_id,
            run_slot_id, operational_opportunity_audit_id,
            production_variant_roster_id, production_variant_roster_revision_id,
            execution_behavior_release_id, cohort_id, language, track_key_hash,
            agent_id, accepted_output_kind, sample_origin, run_slot_kind,
            scheduled_sample_id, as_of, accepted_at, record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
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
            "cohort_default",
            "zh",
            track_hash,
            agent_id,
            contract["accepted_output_kind"],
            "PRODUCTION_ACTIVE",
            "OUTCOME_SCHEDULED",
            scheduled_sample_id,
            record["as_of"],
            record["accepted_at"],
            json.dumps(record, separators=(",", ":"), sort_keys=True),
        ),
    )
    return accepted_id


def _write_realized_projection(
    root: Path,
    conn: sqlite3.Connection,
    *,
    authority: EphemeralOutcomeSourceAuthority,
    opportunity: dict,
    accepted_output_id: str,
    outcome_due_at: str,
    matured_at: str,
    realized_metrics: dict,
) -> tuple[str, list[str]]:
    slot_row = conn.execute(
        "SELECT record_json FROM outcome_schedule_slots_v2 "
        "WHERE scheduled_sample_id = ?",
        (opportunity["scheduled_sample_id"],),
    ).fetchone()
    assert slot_row is not None
    slot = json.loads(slot_row[0])
    plan_row = conn.execute(
        "SELECT record_json FROM outcome_schedule_plans_v2 "
        "WHERE outcome_schedule_plan_id = ?",
        (slot["outcome_schedule_plan_id"],),
    ).fetchone()
    assert plan_row is not None
    plan = json.loads(plan_row[0])
    accepted_row = conn.execute(
        "SELECT accepted_output_hash FROM accepted_agent_outputs_v2 "
        "WHERE accepted_output_id = ?",
        (accepted_output_id,),
    ).fetchone()
    assert accepted_row is not None
    contract = OUTCOME_CONTRACTS[opportunity["agent_id"]]
    evaluation_context = {
        "scheduled_sample_id": opportunity["scheduled_sample_id"],
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "accepted_output_id": accepted_output_id,
        "accepted_output_hash": accepted_row[0],
        "track_key_hash": opportunity["track_key_hash"],
        "agent_id": opportunity["agent_id"],
        "opportunity_as_of": plan["as_of"],
        "outcome_due_at": outcome_due_at,
        "realized_metric_schema_id": contract["realized_metric_schema_id"],
    }
    source_batch = seal_test_outcome_source_batch(
        conn,
        authority=authority,
        evaluation_context=evaluation_context,
        realized_metrics=realized_metrics,
        at=matured_at,
    )
    source_pins = authority_projection_pins(authority)
    body = {
        "schema_version": "realized_outcome_projection_v2",
        "scheduled_sample_id": opportunity["scheduled_sample_id"],
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "accepted_output_id": accepted_output_id,
        "accepted_output_hash": accepted_row[0],
        "track_key_hash": opportunity["track_key_hash"],
        "agent_id": opportunity["agent_id"],
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
        "opportunity_as_of": plan["as_of"],
        "outcome_due_at": outcome_due_at,
        "generated_at": matured_at,
        "pit_status": "VERIFIED",
        "source_batch_id": source_batch["source_batch_id"],
        "source_batch_hash": source_batch["source_batch_hash"],
    }
    payload = {**body, "snapshot_hash": canonical_hash(body)}
    path = (
        root
        / outcome_due_at[:10]
        / "realized_outcomes"
        / f"{opportunity['scheduled_sample_id']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload["snapshot_hash"], source_batch["source_evidence_ids"]


def test_macro_outcome_label_uses_sealed_forecast_and_registry_owned_scale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome_root = tmp_path / "outcome-runtime"
    monkeypatch.setenv("MOSAIC_OUTCOME_RUNTIME_DIR", str(outcome_root))
    authority = provision_test_outcome_source_authority(tmp_path, monkeypatch)
    store, revision = _registered(tmp_path)
    with store._connect() as conn:
        track_hash = _track_by_agent(conn, revision)["china"]
        scheduled_sample_id, _ = _seed_schedule_slot(
            conn,
            track_hash=track_hash,
            agent_id="china",
            sequence=1,
            outcome_due_at="2024-01-09T15:00:00+08:00",
            as_of="2024-01-02T08:00:00+08:00",
        )
        opportunity = freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=track_hash,
            scheduled_sample_id=scheduled_sample_id,
            sample_origin="PRODUCTION_ACTIVE",
            as_of="2024-01-02T08:00:00+08:00",
            member_refs=[{"event_id": "cn-gdp-2024q1"}],
            required_source_evidence_ids=["official:cn-gdp-2024q1"],
            qualification_predicate_version=expected_qualification_predicate_version(
                "china"
            ),
            runtime_authority_binding={
                "source_tool_id": LIVE_SOURCE_TOOL_BY_AGENT["china"],
                "source_snapshot_hash": canonical_hash(
                    {"agent_id": "china", "kind": "source"}
                ),
                "domain_hash": canonical_hash(
                    {"agent_id": "china", "kind": "domain"}
                ),
            },
        )
        accepted_id = _insert_scheduled_acceptance(
            conn,
            revision=revision,
            track_hash=track_hash,
            agent_id="china",
            scheduled_sample_id=scheduled_sample_id,
            opportunity=opportunity,
        )
        pending = append_outcome_eligibility_revision(
            conn,
            track_key_hash=track_hash,
            scheduled_sample_id=scheduled_sample_id,
            sample_origin="PRODUCTION_ACTIVE",
            disposition="PENDING",
            recorded_at="2024-01-02T15:00:00+08:00",
            evaluation_opportunity_set_id=opportunity[
                "evaluation_opportunity_set_id"
            ],
            accepted_output_id=accepted_id,
        )
        realized_metrics = {
            "role_path_metric": 0.5,
            "pit_volatility_scale": 1.0,
        }
        realized_projection_hash, source_evidence_ids = _write_realized_projection(
            outcome_root,
            conn,
            authority=authority,
            opportunity=opportunity,
            accepted_output_id=accepted_id,
            outcome_due_at="2024-01-09T15:00:00+08:00",
            matured_at="2024-01-09T16:00:00+08:00",
            realized_metrics=realized_metrics,
        )
        with pytest.raises(ValueError, match="cannot use external schedule authority"):
            append_realized_outcome_observation(
                conn,
                evaluation_opportunity_set_id=opportunity[
                    "evaluation_opportunity_set_id"
                ],
                outcome_due_at="2024-01-09T15:00:00+08:00",
                matured_at="2024-01-09T16:00:00+08:00",
                realized_metrics=realized_metrics,
                source_evidence_ids=source_evidence_ids,
                realized_projection_hash=realized_projection_hash,
                production_cutoff_at="2024-01-09T16:00:00+08:00",
                external_schedule_authority={},
                external_schedule_authority_verifier=lambda value: value,
            )
        with pytest.raises(ValueError, match="realized_projection_hash"):
            append_realized_outcome_observation(
                conn,
                evaluation_opportunity_set_id=opportunity[
                    "evaluation_opportunity_set_id"
                ],
                outcome_due_at="2024-01-09T15:00:00+08:00",
                matured_at="2024-01-09T16:00:00+08:00",
                realized_metrics={
                    "role_path_metric": 0.5,
                    "pit_volatility_scale": 1.0,
                },
                source_evidence_ids=source_evidence_ids,
                production_cutoff_at="2024-01-09T16:00:00+08:00",
            )
        with pytest.raises(ValueError, match="later than production_cutoff"):
            append_realized_outcome_observation(
                conn,
                evaluation_opportunity_set_id=opportunity[
                    "evaluation_opportunity_set_id"
                ],
                outcome_due_at="2024-01-09T15:00:00+08:00",
                matured_at="2024-01-09T16:00:00+08:00",
                realized_metrics={
                    "role_path_metric": 0.5,
                    "pit_volatility_scale": 1.0,
                },
                source_evidence_ids=source_evidence_ids,
                realized_projection_hash=realized_projection_hash,
                production_cutoff_at="2024-01-09T15:30:00+08:00",
            )
        with pytest.raises(ValueError, match="at or after"):
            append_realized_outcome_observation(
                conn,
                evaluation_opportunity_set_id=opportunity[
                    "evaluation_opportunity_set_id"
                ],
                outcome_due_at="2024-01-09T15:00:00+08:00",
                matured_at="2024-01-09T14:59:59+08:00",
                realized_metrics={
                    "role_path_metric": 0.5,
                    "pit_volatility_scale": 1.0,
                },
                source_evidence_ids=source_evidence_ids,
                realized_projection_hash=realized_projection_hash,
                production_cutoff_at="2024-01-09T16:00:00+08:00",
            )
        with pytest.raises(ValueError, match="forecast"):
            append_realized_outcome_observation(
                conn,
                evaluation_opportunity_set_id=opportunity[
                    "evaluation_opportunity_set_id"
                ],
                outcome_due_at="2024-01-09T15:00:00+08:00",
                matured_at="2024-01-09T16:00:00+08:00",
                realized_metrics={
                    "role_path_metric": 0.5,
                    "pit_volatility_scale": 1.0,
                    "wrapper": {"forecast_value": 0.5},
                },
                source_evidence_ids=source_evidence_ids,
                realized_projection_hash=realized_projection_hash,
                production_cutoff_at="2024-01-09T16:00:00+08:00",
            )
        with pytest.raises(ValueError, match="authoritative source batch"):
            append_realized_outcome_observation(
                conn,
                evaluation_opportunity_set_id=opportunity[
                    "evaluation_opportunity_set_id"
                ],
                outcome_due_at="2024-01-09T15:00:00+08:00",
                matured_at="2024-01-09T16:00:00+08:00",
                realized_metrics=realized_metrics,
                source_evidence_ids=source_evidence_ids,
                realized_projection_hash=canonical_hash({"forged": True}),
                production_cutoff_at="2024-01-09T16:00:00+08:00",
            )
        observation = append_realized_outcome_observation(
            conn,
            evaluation_opportunity_set_id=opportunity[
                "evaluation_opportunity_set_id"
            ],
            outcome_due_at="2024-01-09T15:00:00+08:00",
            matured_at="2024-01-09T16:00:00+08:00",
            realized_metrics={
                "role_path_metric": 0.5,
                "pit_volatility_scale": 1.0,
            },
            source_evidence_ids=source_evidence_ids,
            realized_projection_hash=realized_projection_hash,
            production_cutoff_at="2024-01-09T16:00:00+08:00",
        )
        score = append_outcome_eligibility_revision(
            conn,
            track_key_hash=track_hash,
            scheduled_sample_id=scheduled_sample_id,
            sample_origin="PRODUCTION_ACTIVE",
            disposition="SCORE",
            recorded_at="2024-01-09T16:00:00+08:00",
            evaluation_opportunity_set_id=opportunity[
                "evaluation_opportunity_set_id"
            ],
            accepted_output_id=accepted_id,
        )
        assert score["supersedes_revision_id"] == pending["audit_revision_id"]
        with pytest.raises(ValueError, match="realized_projection_hash"):
            append_agent_outcome_label(
                conn,
                audit_revision_id=score["audit_revision_id"],
                realized_outcome_observation_id=observation[
                    "realized_outcome_observation_id"
                ],
                realized_projection_hash="sha256:" + "0" * 64,
            )
        accepted_row = conn.execute(
            "SELECT accepted_output_hash, record_json FROM accepted_agent_outputs_v2 "
            "WHERE accepted_output_id = ?",
            (accepted_id,),
        ).fetchone()
        assert accepted_row is not None
        _, original_json = accepted_row
        for field, value in (("direction", "ADVERSE"), ("confidence", 0.1)):
            mutated = json.loads(original_json)
            mutated["output"]["payload"][field] = value
            mutated_body = {
                key: item
                for key, item in mutated.items()
                if key != "accepted_output_hash"
            }
            mutated["accepted_output_hash"] = canonical_hash(mutated_body)
            with pytest.raises(sqlite3.IntegrityError, match="append_only"):
                conn.execute(
                    "UPDATE accepted_agent_outputs_v2 SET accepted_output_hash = ?, "
                    "record_json = ? WHERE accepted_output_id = ?",
                    (
                        mutated["accepted_output_hash"],
                        json.dumps(mutated),
                        accepted_id,
                    ),
                )
        label = append_agent_outcome_label(
            conn,
            audit_revision_id=score["audit_revision_id"],
            realized_outcome_observation_id=observation[
                "realized_outcome_observation_id"
            ],
            realized_projection_hash=realized_projection_hash,
        )
        assert label["utility_delta"] == pytest.approx(0.16)
        assert label["normalized_score"] == pytest.approx(0.16)
        assert label["raw_metrics"]["confidence"] == pytest.approx(0.8)
        assert label["normalization_reference"]["scale"] == 1.0
        assert append_agent_outcome_label(
            conn,
            audit_revision_id=score["audit_revision_id"],
            realized_outcome_observation_id=observation[
                "realized_outcome_observation_id"
            ],
            realized_projection_hash=realized_projection_hash,
        )["outcome_label_id"] == label["outcome_label_id"]


def test_knot_outcome_requires_unchanged_hash_bound_external_schedule_authority(
    tmp_path: Path,
) -> None:
    store, revision = _registered(tmp_path)
    with store._connect() as conn:
        track_hash = _track_by_agent(conn, revision)["china"]
        opportunity = freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=track_hash,
            scheduled_sample_id="knot:china:external-authority",
            sample_origin="KNOT_RESEARCH_SHADOW",
            as_of="2024-01-02T08:00:00+08:00",
            member_refs=[{"event_id": "cn-release-external-authority"}],
            required_source_evidence_ids=["official:cn-release-external-authority"],
            qualification_predicate_version=expected_qualification_predicate_version(
                "china"
            ),
        )
        due_at = "2024-01-09T15:00:00+08:00"
        matured_at = "2024-01-09T16:00:00+08:00"
        authority_identity = {
            "authority_namespace": "test-private-runtime",
            "external_schedule_manifest_id": "private-manifest:china:1",
            "external_schedule_manifest_hash": canonical_hash(
                {"private_manifest": 1}
            ),
            "external_schedule_slot_id": "private-slot:china:1",
            "external_schedule_slot_hash": canonical_hash({"private_slot": 1}),
            "external_run_id": "private-run:china:1",
            "external_run_hash": canonical_hash({"private_run": 1}),
            "evaluation_opportunity_set_id": opportunity[
                "evaluation_opportunity_set_id"
            ],
            "evaluation_opportunity_set_hash": opportunity[
                "evaluation_opportunity_set_hash"
            ],
            "outcome_due_at": due_at,
            "trading_calendar_snapshot_hash": canonical_hash(
                ["2024-01-02", "2024-01-09"]
            ),
        }
        authority_without_hash = {
            "schema_version": "external_outcome_schedule_authority_v1",
            "schedule_authority_id": deterministic_id(
                "external-outcome-schedule-authority", authority_identity
            ),
            **authority_identity,
            "sample_origin": "KNOT_RESEARCH_SHADOW",
            "scheduled_sample_id": opportunity["scheduled_sample_id"],
            "track_key_hash": track_hash,
            "agent_id": "china",
            "opportunity_as_of": opportunity["as_of"],
            "trading_calendar_id": "cn_a_share_trading_calendar_v1",
            "authority_published_at": "2024-01-02T07:00:00+08:00",
            "external_run_frozen_at": "2024-01-02T09:00:00+08:00",
            "verified_at": matured_at,
        }
        authority = {
            **authority_without_hash,
            "schedule_authority_hash": canonical_hash(authority_without_hash),
        }
        call = {
            "evaluation_opportunity_set_id": opportunity[
                "evaluation_opportunity_set_id"
            ],
            "outcome_due_at": due_at,
            "matured_at": matured_at,
            "realized_metrics": {
                "role_path_metric": 0.5,
                "pit_volatility_scale": 1.0,
            },
            "source_evidence_ids": ["official:china:realized"],
        }
        with pytest.raises(ValueError, match="requires external schedule authority"):
            append_realized_outcome_observation(conn, **call)
        with pytest.raises(ValueError, match="verifier changed"):
            append_realized_outcome_observation(
                conn,
                **call,
                external_schedule_authority=authority,
                external_schedule_authority_verifier=lambda value: {
                    **value,
                    "external_schedule_slot_id": "private-slot:forged",
                },
            )
        forged = {**authority, "outcome_due_at": "2024-01-10T15:00:00+08:00"}
        with pytest.raises(ValueError, match="outcome_due_at mismatch"):
            append_realized_outcome_observation(
                conn,
                **call,
                external_schedule_authority=forged,
                external_schedule_authority_verifier=lambda value: value,
            )
        observation = append_realized_outcome_observation(
            conn,
            **call,
            external_schedule_authority=authority,
            external_schedule_authority_verifier=lambda value: value,
        )
        assert observation["outcome_schedule_slot_id"] == "private-slot:china:1"
        assert observation["external_schedule_authority"] == authority


def test_decision_components_are_closed_and_weighted() -> None:
    components = []
    for component_id, weight in (
        ("COST_ERROR", 0.4),
        ("FEASIBILITY", 0.3),
        ("TARGET_DELTA", 0.2),
        ("POLICY_COMPLIANCE", 0.1),
    ):
        components.append(
            {
                "component_id": component_id,
                "component_weight": weight,
                "scale": 1.0,
                "output_utility": 0.5,
                "null_utility": 0.1,
                "utility_delta": 0.4,
            }
        )
    utility, _ = compute_outcome_utility(
        "EXECUTION",
        {
            "components": components,
            "combined_output_utility": 0.5,
            "combined_null_utility": 0.1,
            "combined_utility_delta": 0.4,
        },
    )
    assert utility == pytest.approx(0.4)
    components[0]["component_weight"] = 0.5
    with pytest.raises(ValueError, match="component_weight drift"):
        compute_outcome_utility(
            "EXECUTION",
            {
                "components": components,
                "combined_output_utility": 0.5,
                "combined_null_utility": 0.1,
                "combined_utility_delta": 0.4,
            },
        )


def _standard_sector_raw_metrics() -> dict[str, object]:
    return {
        "output_confidence": 0.8,
        "confidence_semantics": "DIRECTIONAL_UTILITY",
        "direction_metrics": [],
        "security_metrics": [],
        "security_leg_metrics": [
            {
                "side": "PREFERRED",
                "direction_id": "preferred-direction",
                "security_status": "PICKS_PRESENT",
                "shortlist_size": 1,
                "side_security_utility_delta": 0.2,
            },
            {
                "side": "LEAST_PREFERRED",
                "direction_id": "least-direction",
                "security_status": "NO_QUALIFIED_SECURITY_EMPTY_SHORTLIST",
                "shortlist_size": 0,
                "side_security_utility_delta": 0.0,
            },
        ],
        "direction_forecast_loss": 0.1,
        "direction_null_loss": 0.3,
        "security_forecast_loss": 0.1,
        "security_null_loss": 0.2,
        "direction_utility_delta": 0.2,
        "security_utility_delta": 0.1,
        "combined_utility_delta": 0.15,
        "unit_confidence_utility_delta": 0.1875,
        "confidence_calibration_target": 1,
    }


def test_standard_sector_utility_has_no_overall_or_nonempty_abstention_branch() -> None:
    metrics = _standard_sector_raw_metrics()
    utility, _ = compute_outcome_utility("STANDARD_SECTOR", metrics)
    assert utility == pytest.approx(0.15)

    overall_abstention = dict(metrics)
    overall_abstention["confidence_semantics"] = "ABSTENTION_WARRANTED"
    overall_abstention["abstention_forecast_loss"] = 0.1
    with pytest.raises(ValueError, match="retired abstention fields"):
        compute_outcome_utility("STANDARD_SECTOR", overall_abstention)

    nonempty_abstention = _standard_sector_raw_metrics()
    nonempty_abstention["security_leg_metrics"][0][
        "security_status"
    ] = "NO_QUALIFIED_SECURITY_NONEMPTY_SHORTLIST"
    with pytest.raises(ValueError, match="unknown Standard Sector security leg status"):
        compute_outcome_utility("STANDARD_SECTOR", nonempty_abstention)

    nonzero_empty_leg = _standard_sector_raw_metrics()
    nonzero_empty_leg["security_leg_metrics"][1][
        "side_security_utility_delta"
    ] = 0.1
    with pytest.raises(ValueError, match="empty Standard Sector security leg"):
        compute_outcome_utility("STANDARD_SECTOR", nonzero_empty_leg)


def _seed_schedule_slot(
    conn: sqlite3.Connection,
    *,
    track_hash: str,
    agent_id: str,
    sequence: int,
    outcome_due_at: str | None = None,
    as_of: str | None = None,
) -> tuple[str, str]:
    revision_row = conn.execute(
        "SELECT record_json FROM darwinian_v2_production_variant_roster_revisions "
        "WHERE readiness = 'READY' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    assert revision_row is not None
    revision = json.loads(revision_row[0])
    if outcome_due_at is None:
        ordinal = (sequence - 1) % 30
        boundary = date(2024, 2, 1) + timedelta(days=ordinal)
        outcome_due_at = f"{boundary.isoformat()}T15:00:00+08:00"
    if as_of is None:
        as_of = outcome_due_at
    graph_run_id = f"graph:{agent_id}:{sequence}"
    plan_id = f"plan:{agent_id}:{sequence}"
    sample_id = f"sample:{agent_id}:{sequence}"
    slot_id = f"slot:{agent_id}:{sequence}"
    slot_with_id = {
        "outcome_schedule_slot_id": slot_id,
        "schema_version": "outcome_schedule_slot_v2",
        "outcome_schedule_plan_id": plan_id,
        "graph_run_id": graph_run_id,
        "agent_id": agent_id,
        "track_key_hash": track_hash,
        "run_slot_id": f"run-slot:{agent_id}:{sequence}",
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
        **slot_with_id,
        "outcome_schedule_slot_hash": canonical_hash(slot_with_id),
    }
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
        "trading_calendar_snapshot_hash": canonical_hash(["2024-01-01"]),
        "event_candidate_input_hash": canonical_hash({}),
        "as_of": as_of,
        "prepared_at": outcome_due_at,
        "slots": [slot],
    }
    plan = {
        **plan_without_hash,
        "outcome_schedule_plan_hash": canonical_hash(plan_without_hash),
    }
    conn.execute(
        """
        INSERT INTO outcome_schedule_plans_v2 (
            outcome_schedule_plan_id, outcome_schedule_plan_hash, graph_run_id,
            production_variant_roster_id, production_variant_roster_revision_id,
            execution_behavior_release_id, cohort_id, language,
            trading_calendar_id, trading_calendar_snapshot_hash, as_of,
            prepared_at, record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            plan["outcome_schedule_plan_hash"],
            graph_run_id,
            revision["production_variant_roster_id"],
            revision["production_variant_roster_revision_id"],
            revision["execution_behavior_release_id"],
            revision["cohort_id"],
            revision["language"],
            "cn_a_share_trading_calendar_v1",
            plan["trading_calendar_snapshot_hash"],
            outcome_due_at,
            outcome_due_at,
            json.dumps(plan),
        ),
    )
    conn.execute(
        """
        INSERT INTO outcome_schedule_slots_v2 (
            outcome_schedule_slot_id, outcome_schedule_slot_hash,
            outcome_schedule_plan_id, graph_run_id, agent_id, track_key_hash,
            run_slot_id, run_slot_kind, scheduled_sample_id, trigger_event_id,
            record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OUTCOME_SCHEDULED', ?, NULL, ?)
        """,
        (
            slot_id,
            slot["outcome_schedule_slot_hash"],
            plan_id,
            graph_run_id,
            agent_id,
            track_hash,
            slot["run_slot_id"],
            sample_id,
            json.dumps(slot),
        ),
    )
    return sample_id, outcome_due_at


def _seed_score(
    conn: sqlite3.Connection,
    *,
    track_hash: str,
    agent_id: str,
    sequence: int,
    score: float,
    outcome_due_at: str | None = None,
) -> None:
    sample_id, outcome_due_at = _seed_schedule_slot(
        conn,
        track_hash=track_hash,
        agent_id=agent_id,
        sequence=sequence,
        outcome_due_at=outcome_due_at,
    )
    audit_id = f"audit:{agent_id}:{sequence}"
    revision_id = f"audit-revision:{agent_id}:{sequence}"
    conn.execute(
        """
        INSERT INTO agent_outcome_eligibility_revisions_v2 (
            audit_revision_id, audit_revision_hash, audit_id,
            supersedes_revision_id, scheduled_sample_id, track_key_hash,
            agent_id, sample_origin, disposition, accepted_output_id,
            opportunity_set_status, audit_sequence, recorded_at, record_json
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, 'PRODUCTION_ACTIVE', 'SCORE',
                  NULL, 'AVAILABLE', 1, ?, ?)
        """,
        (
            revision_id,
            canonical_hash({"revision": revision_id}),
            audit_id,
            sample_id,
            track_hash,
            agent_id,
            f"2024-01-{min(sequence, 28):02d}T15:00:00+08:00",
            json.dumps({"audit_revision_id": revision_id}),
        ),
    )
    conn.execute(
        """
        INSERT INTO agent_outcome_labels_v2 (
            outcome_sequence, outcome_label_id, outcome_label_hash,
            audit_revision_id, scheduled_sample_id, track_key_hash, agent_id,
            primary_label_id, sample_origin, darwin_evaluation_eligible,
            usage_weight_eligible, normalized_score, outcome_due_at,
            matured_at, record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PRODUCTION_ACTIVE', 1, ?, ?, ?, ?, ?)
        """,
        (
            sequence,
            f"label:{agent_id}:{sequence}",
            canonical_hash({"label": agent_id, "sequence": sequence}),
            revision_id,
            sample_id,
            track_hash,
            agent_id,
            OUTCOME_CONTRACTS[agent_id]["primary_label_id"],
            int(
                OUTCOME_CONTRACTS[agent_id]["darwin_application_mode"]
                == "DOWNSTREAM_USAGE_WEIGHT"
            ),
            score,
            outcome_due_at,
            outcome_due_at,
            json.dumps({"outcome_sequence": sequence, "normalized_score": score}),
        ),
    )


def _seed_failure(
    conn: sqlite3.Connection,
    *,
    track_hash: str,
    agent_id: str,
    sequence: int,
    outcome_due_at: str,
) -> None:
    sample_id, _ = _seed_schedule_slot(
        conn,
        track_hash=track_hash,
        agent_id=agent_id,
        sequence=sequence,
        outcome_due_at=outcome_due_at,
    )
    revision_id = f"audit-revision:{agent_id}:{sequence}"
    conn.execute(
        """
        INSERT INTO agent_outcome_eligibility_revisions_v2 (
            audit_revision_id, audit_revision_hash, audit_id,
            supersedes_revision_id, scheduled_sample_id, track_key_hash,
            agent_id, sample_origin, disposition, accepted_output_id,
            opportunity_set_status, audit_sequence, recorded_at, record_json
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, 'PRODUCTION_ACTIVE', 'AGENT_FAILURE',
                  NULL, 'UNAVAILABLE', 1, ?, ?)
        """,
        (
            revision_id,
            canonical_hash({"revision": revision_id}),
            f"audit:{agent_id}:{sequence}",
            sample_id,
            track_hash,
            agent_id,
            outcome_due_at,
            json.dumps(
                {
                    "audit_revision_id": revision_id,
                    "disposition": "AGENT_FAILURE",
                }
            ),
        ),
    )


def test_window_coverage_uses_the_selected_scores_schedule_interval(
    tmp_path: Path,
) -> None:
    store, revision = _registered(tmp_path)
    trading_dates, cutoff_at = _darwin_trading_calendar()
    with store._connect() as conn:
        track_by_agent = _track_by_agent(conn, revision)
        base = date(2023, 1, 2)
        for index in range(40):
            boundary = base + timedelta(days=index)
            _seed_score(
                conn,
                track_hash=track_by_agent["china"],
                agent_id="china",
                sequence=index + 1,
                score=0.5,
                outcome_due_at=f"{boundary.isoformat()}T15:00:00+08:00",
            )
        recent = date(2024, 6, 3)
        for index in range(20):
            boundary = recent + timedelta(days=index)
            _seed_score(
                conn,
                track_hash=track_by_agent["china"],
                agent_id="china",
                sequence=41 + index,
                score=0.5,
                outcome_due_at=f"{boundary.isoformat()}T15:00:00+08:00",
            )
        for index in range(10):
            boundary = recent + timedelta(days=index * 2)
            _seed_failure(
                conn,
                track_hash=track_by_agent["china"],
                agent_id="china",
                sequence=61 + index,
                outcome_due_at=f"{boundary.isoformat()}T15:00:00+08:00",
            )

        windows = refresh_evaluation_windows(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        by_track = {row["track_key_hash"]: row for row in windows}
        china = by_track[track_by_agent["china"]]
        empty = by_track[track_by_agent["us_economy"]]

        assert china["n_eligible_scores"] == 30
        assert china["total_score_count"] == 30
        assert china["agent_failure_count"] == 10
        assert china["window_coverage"] == pytest.approx(0.75)
        assert china["maturity_state"] == "COLD_START"
        assert empty["n_eligible_scores"] == 0
        assert empty["window_coverage"] == 0
        assert empty["maturity_state"] == "COLD_START"


def test_failure_only_window_change_does_not_reapply_weight_multiplier(
    tmp_path: Path,
) -> None:
    store, revision = _registered(tmp_path)
    trading_dates, cutoff_at = _darwin_trading_calendar()
    with store._connect() as conn:
        track_by_agent = _track_by_agent(conn, revision)
        china_track = track_by_agent["china"]
        for sequence in range(1, 31):
            _seed_score(
                conn,
                track_hash=china_track,
                agent_id="china",
                sequence=sequence,
                score=0.5,
            )

        first_batches = publish_usage_weight_updates(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        first_china = next(
            batch for batch in first_batches if batch["rank_scope"] == "macro_china"
        )
        mature_weight_count = conn.execute(
            "SELECT COUNT(*) FROM darwinian_v2_usage_weight_records "
            "WHERE record_kind = 'MATURE_UPDATE'"
        ).fetchone()[0]

        _seed_failure(
            conn,
            track_hash=china_track,
            agent_id="china",
            sequence=31,
            outcome_due_at="2024-03-01T15:00:00+08:00",
        )
        second_batches = publish_usage_weight_updates(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        second_china = next(
            batch for batch in second_batches if batch["rank_scope"] == "macro_china"
        )
        assert second_china["update_event_id"] != first_china["update_event_id"]
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM darwinian_v2_usage_weight_records "
                "WHERE record_kind = 'MATURE_UPDATE'"
            ).fetchone()[0]
            == mature_weight_count
        )
        usage_track_hash = conn.execute(
            "SELECT usage_track_key_hash FROM darwinian_v2_usage_tracks "
            "WHERE agent_id = 'china'"
        ).fetchone()[0]
        checkpoint = json.loads(
            conn.execute(
                "SELECT record_json FROM darwinian_v2_usage_weight_update_checkpoints "
                "WHERE usage_track_key_hash = ? ORDER BY rowid DESC LIMIT 1",
                (usage_track_hash,),
            ).fetchone()[0]
        )
        assert checkpoint["update_disposition"] == "NO_NEW_OUTCOME"
        assert checkpoint["previous_weight_record_id"] == checkpoint[
            "resulting_weight_record_id"
        ]


def test_30_sample_peer_and_self_updates_are_atomic_and_idempotent(
    tmp_path: Path,
) -> None:
    store, revision = _registered(tmp_path)
    trading_dates, cutoff_at = _darwin_trading_calendar()
    with store._connect() as conn:
        track_by_agent = _track_by_agent(conn, revision)
        seeded_agents = [
            "semiconductor",
            "technology",
            "energy",
            "biotech",
            "consumer",
            "industrials",
            "real_estate_construction",
            "financials",
            "agriculture",
            "druckenmiller",
            "munger",
            "burry",
            "ackman",
            "china",
            "cio",
        ]
        next_sequence = 1
        for agent_index, agent_id in enumerate(seeded_agents):
            mean_score = (
                0.5
                if agent_id == "china"
                else -0.3
                if agent_id == "cio"
                else 0.8 - agent_index * 0.08
            )
            for _ in range(30):
                _seed_score(
                    conn,
                    track_hash=track_by_agent[agent_id],
                    agent_id=agent_id,
                    sequence=next_sequence,
                    score=mean_score,
                )
                next_sequence += 1

        windows = refresh_evaluation_windows(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        by_agent = {}
        for row in windows:
            agent = conn.execute(
                "SELECT agent_id FROM darwinian_v2_evaluation_tracks "
                "WHERE track_key_hash = ?",
                (row["track_key_hash"],),
            ).fetchone()[0]
            by_agent[agent] = row
        assert by_agent["semiconductor"]["performance_band"] == "Q1"
        assert by_agent["agriculture"]["performance_band"] == "Q4"
        assert by_agent["china"]["performance_band"] == "Q1"
        assert by_agent["cio"]["maturity_state"] == "MATURE"
        assert by_agent["cio"]["performance_band"] in {"Q1", "Q2", "Q3", "Q4"}

        batches = publish_usage_weight_updates(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        assert all(batch["status"] == "PUBLISHED" for batch in batches)
        weights = {
            row[0]: row[1]
            for row in conn.execute(
                """
                SELECT u.agent_id, w.darwin_weight
                FROM darwinian_v2_usage_tracks u
                JOIN darwinian_v2_usage_weight_records w
                  ON w.usage_track_key_hash = u.usage_track_key_hash
                WHERE w.record_kind = 'MATURE_UPDATE'
                """
            ).fetchall()
        }
        assert weights["semiconductor"] == pytest.approx(1.05)
        assert weights["agriculture"] == pytest.approx(0.95)
        assert weights["china"] == pytest.approx(1.05)
        assert "cio" not in weights
        before = conn.execute(
            "SELECT COUNT(*) FROM darwinian_v2_usage_weight_records"
        ).fetchone()[0]
        retry = publish_usage_weight_updates(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        after = conn.execute(
            "SELECT COUNT(*) FROM darwinian_v2_usage_weight_records"
        ).fetchone()[0]
        assert [row["update_event_id"] for row in retry] == [
            row["update_event_id"] for row in batches
        ]
        assert after == before


def test_later_publication_cannot_rewrite_historical_weight_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, revision = _registered(tmp_path)
    trading_dates, cutoff_at = _darwin_trading_calendar()
    first_published_at = datetime(2025, 2, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "mosaic.scorecard.darwinian_updates._server_now",
        lambda: first_published_at,
    )

    with store._connect() as conn:
        china_track = _track_by_agent(conn, revision)["china"]
        for sequence in range(1, 31):
            _seed_score(
                conn,
                track_hash=china_track,
                agent_id="china",
                sequence=sequence,
                score=0.5,
            )

        published = publish_usage_weight_updates(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        receipts = conn.execute(
            "SELECT published_at FROM "
            "darwinian_v2_usage_weight_batch_publications ORDER BY rowid"
        ).fetchall()
        assert len(receipts) == len(published)
        assert {row[0] for row in receipts} == {first_published_at.isoformat()}

        historical = get_production_weight_snapshot(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            as_of="2025-02-01T00:00:00+08:00",
        )
        historical_weights = {
            row["agent_id"]: row["darwin_weight"] for row in historical["weights"]
        }
        assert historical_weights["china"] == pytest.approx(1.0)

        prospective = get_production_weight_snapshot(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            as_of="2025-02-11T00:00:00+08:00",
        )
        prospective_weights = {
            row["agent_id"]: row["darwin_weight"] for row in prospective["weights"]
        }
        assert prospective_weights["china"] == pytest.approx(1.05)

        monkeypatch.setattr(
            "mosaic.scorecard.darwinian_updates._server_now",
            lambda: datetime(2025, 3, 1, tzinfo=timezone.utc),
        )
        retry = publish_usage_weight_updates(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        assert [row["update_event_id"] for row in retry] == [
            row["update_event_id"] for row in published
        ]
        retry_receipts = conn.execute(
            "SELECT published_at FROM "
            "darwinian_v2_usage_weight_batch_publications ORDER BY rowid"
        ).fetchall()
        assert retry_receipts == receipts
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute(
                "UPDATE darwinian_v2_usage_weight_batch_publications "
                "SET published_at = published_at"
            )


def test_empty_opportunity_set_is_restricted_to_explicit_skip_roles(
    tmp_path: Path,
) -> None:
    store, revision = _registered(tmp_path)
    with store._connect() as conn:
        tracks = _track_by_agent(conn, revision)
        with pytest.raises(ValueError, match="cannot .* empty"):
            freeze_evaluation_opportunity_set(
                conn,
                production_variant_roster_revision_id=revision[
                    "production_variant_roster_revision_id"
                ],
                track_key_hash=tracks["china"],
                scheduled_sample_id="china:empty",
                sample_origin="PRODUCTION_ACTIVE",
                as_of="2024-01-02T08:00:00+08:00",
                member_refs=[],
                required_source_evidence_ids=["official:calendar"],
                qualification_predicate_version=expected_qualification_predicate_version(
                    "china"
                ),
            )
        record = freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=tracks["cro"],
            scheduled_sample_id="cro:empty",
            sample_origin="PRODUCTION_ACTIVE",
            as_of="2024-01-02T08:00:00+08:00",
            member_refs=[],
            required_source_evidence_ids=["frozen:pre-cro-universe"],
            qualification_predicate_version=expected_qualification_predicate_version(
                "cro"
            ),
            runtime_authority_binding={
                "source_tool_id": "get_cro_risk_snapshot",
                "source_snapshot_hash": canonical_hash(
                    "cro:empty:source-snapshot"
                ),
                "candidate_scope_hash": canonical_hash(
                    "cro:empty:candidate-scope"
                ),
                "candidate_universe_hash": canonical_hash(
                    "cro:empty:candidate-universe"
                ),
                "upstream_accepted_output_refs_hash": canonical_hash(
                    "cro:empty:upstream-accepted-output-refs"
                ),
            },
        )
        assert record["member_state"] == "EMPTY"

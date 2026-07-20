from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from mosaic.dataflows.outcome_runtime_inputs import (
    expected_qualification_predicate_version,
)
import mosaic.scorecard.component_calibration as component_calibration
from mosaic.scorecard.component_calibration import (
    append_component_shadow_checkpoint,
    build_component_regime_snapshot,
    publish_component_weight_release,
    resolve_component_weights,
    rollback_component_weight_release,
    run_component_calibration,
)
from mosaic.scorecard.darwinian_updates import (
    LIVE_SOURCE_TOOL_BY_AGENT,
    freeze_evaluation_opportunity_set,
)
from mosaic.scorecard.darwinian_v2 import (
    canonical_hash,
    canonical_json,
    deterministic_id,
    prepare_production_variant,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.store import ScorecardStore


@pytest.fixture(autouse=True)
def _opaque_private_regime_classifier(monkeypatch) -> None:
    def classify(snapshot, *, as_of):
        observation = next(
            item for item in snapshot["observations"] if item["as_of"] == as_of
        )
        return {
            "regime_label": (
                "stress" if observation["private_fixture_sequence"] % 2 else "normal"
            ),
            "classifier_contract_id": "opaque-private-classifier",
            "classifier_contract_version": "opaque-private-classifier-v1",
            "classifier_contract_hash": f"sha256:{'7' * 64}",
            "pit_snapshot_hash": snapshot["snapshot_hash"],
        }

    monkeypatch.setattr(component_calibration, "_classify_private_regime", classify)


def _trading_dates(start: date, end: date) -> list[str]:
    result: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _calendar_snapshot(dates: list[str], as_of: str) -> dict:
    without_hash = {
        "schema_version": "verified_trading_calendar_snapshot_v1",
        "trading_calendar_id": "cn_a_share_trading_calendar_v1",
        "as_of": as_of,
        "coverage_start": dates[0],
        "coverage_end": dates[-1],
        "pit_status": "VERIFIED",
        "source_evidence_ids": ["tushare:trade_cal:SSE:test-fixture"],
        "trading_dates": dates,
    }
    return {**without_hash, "snapshot_hash": canonical_hash(without_hash)}


def _bindings() -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        dimensions = contract["track_contract_dimensions"]
        composition = contract["component_composition_contract"]
        result[agent_id] = {
            "agent_contract_version": f"{agent_id}_agent_v2",
            "prompt_behavior_version": f"{agent_id}_prompt_v2",
            "execution_behavior_version": f"{agent_id}_execution_v2",
            "component_weight_contract_version": (
                composition["component_weight_contract_version"]
                if composition is not None
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


def _registered(tmp_path: Path) -> tuple[ScorecardStore, dict, dict]:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-component-v2",
        behavior_bindings=_bindings(),
        effective_at="2020-01-01T00:00:00+08:00",
    )
    with store._connect() as conn:
        placeholders = ",".join("?" for _ in revision["evaluation_track_key_hashes"])
        row = conn.execute(
            f"SELECT contract_json FROM darwinian_v2_evaluation_tracks "
            f"WHERE track_key_hash IN ({placeholders}) AND agent_id = 'us_economy'",
            tuple(revision["evaluation_track_key_hashes"]),
        ).fetchone()
    assert row is not None
    return store, revision, json.loads(row[0])


def _runtime_binding(*, effective_at: str = "2020-01-01T00:00:00+08:00") -> dict:
    cohort_id = "cohort_default"
    language = "zh"
    without_hash = {
        "schema_version": "darwinian_runtime_binding_v2",
        "production_variant_roster_id": deterministic_id(
            "production-variant-roster",
            {"cohort_id": cohort_id, "language": language},
        ),
        "cohort_id": cohort_id,
        "language": language,
        "execution_behavior_release_id": "release-component-v2",
        "prompt_repo_id": "private-prompts",
        "prompt_repo_revision": "a" * 40,
        "effective_at": effective_at,
        "agent_behavior_bindings": _bindings(),
    }
    return {**without_hash, "binding_hash": canonical_hash(without_hash)}


def _insert(
    conn: sqlite3.Connection,
    sql: str,
    values: tuple,
) -> None:
    conn.execute(sql, values)


def _seed_component_sample(
    conn: sqlite3.Connection,
    *,
    revision: dict,
    track: dict,
    as_of: str,
    outcome_due_at: str,
    sequence: int,
    target: float,
    cached_target: float | None = None,
) -> None:
    agent_id = "us_economy"
    contract = OUTCOME_CONTRACTS[agent_id]
    composition = contract["component_composition_contract"]
    assert composition is not None
    sample_id = f"component-sample:{as_of}"
    accepted_id = f"accepted:{sample_id}"
    operational_id = f"operational:{sample_id}"
    run_id = f"run:{sample_id}"
    graph_run_id = f"graph:{sample_id}"
    run_slot_id = f"slot:{sample_id}"
    common = {
        "graph_run_id": graph_run_id,
        "run_slot_id": run_slot_id,
        "run_id": run_id,
        "scheduled_sample_id": sample_id,
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": revision[
            "production_variant_roster_revision_id"
        ],
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": "cohort_default",
        "language": "zh",
        "agent_id": agent_id,
        "track_key_hash": track["track_key_hash"],
    }
    member_key = (
        "event_id"
        if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
        else "path_snapshot_id"
    )
    opportunity = freeze_evaluation_opportunity_set(
        conn,
        production_variant_roster_revision_id=revision[
            "production_variant_roster_revision_id"
        ],
        track_key_hash=track["track_key_hash"],
        scheduled_sample_id=sample_id,
        sample_origin="PRODUCTION_ACTIVE",
        as_of=as_of,
        member_refs=[{member_key: sample_id}],
        required_source_evidence_ids=[f"official:{sample_id}"],
        qualification_predicate_version=expected_qualification_predicate_version(
            agent_id
        ),
        runtime_authority_binding={
            "source_tool_id": LIVE_SOURCE_TOOL_BY_AGENT[agent_id],
            "source_snapshot_hash": canonical_hash(
                {"sample_id": sample_id, "kind": "source"}
            ),
            "domain_hash": canonical_hash(
                {"sample_id": sample_id, "kind": "domain"}
            ),
        },
    )
    opportunity_id = opportunity["evaluation_opportunity_set_id"]
    accepted_without_hash = {
        "accepted_output_id": accepted_id,
        **common,
        "operational_opportunity_audit_id": operational_id,
        "agent_contract_version": track["agent_contract_version"],
        "prompt_behavior_version": track["prompt_behavior_version"],
        "execution_behavior_version": track["execution_behavior_version"],
        "component_weight_contract_version": track[
            "component_weight_contract_version"
        ],
        "accepted_output_kind": "MACRO_TRANSMISSION",
        "sample_origin": "PRODUCTION_ACTIVE",
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "as_of": as_of,
        "accepted_at": f"{as_of}T15:00:00+08:00",
        "output": {"payload": {"direction": "NEUTRAL"}},
    }
    accepted = {
        **accepted_without_hash,
        "accepted_output_hash": canonical_hash(accepted_without_hash),
    }
    _insert(
        conn,
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
            accepted["accepted_output_hash"],
            graph_run_id,
            run_id,
            run_slot_id,
            operational_id,
            revision["production_variant_roster_id"],
            revision["production_variant_roster_revision_id"],
            revision["execution_behavior_release_id"],
            "cohort_default",
            "zh",
            track["track_key_hash"],
            agent_id,
            "MACRO_TRANSMISSION",
            "PRODUCTION_ACTIVE",
            "OUTCOME_SCHEDULED",
            sample_id,
            as_of,
            accepted_without_hash["accepted_at"],
            canonical_json(accepted),
        ),
    )

    operational_without_hash = {
        "operational_opportunity_audit_id": operational_id,
        **common,
        "sample_origin": "PRODUCTION_ACTIVE",
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "production_reliability_eligible": True,
        "disposition": "ACCEPTED",
        "accountable": True,
        "accepted_output_id": accepted_id,
        "accepted_output_hash": accepted["accepted_output_hash"],
        "fallback_used": False,
        "failure_reason": None,
        "as_of": as_of,
        "recorded_at": f"{as_of}T15:00:00+08:00",
    }
    operational = {
        **operational_without_hash,
        "operational_opportunity_audit_hash": canonical_hash(
            operational_without_hash
        ),
    }
    _insert(
        conn,
        """
        INSERT INTO operational_opportunity_audits_v2 (
            operational_opportunity_audit_id, operational_opportunity_audit_hash,
            graph_run_id, run_slot_id, production_variant_roster_id,
            production_variant_roster_revision_id, execution_behavior_release_id,
            cohort_id, language, agent_id, track_key_hash, sample_origin,
            run_slot_kind, scheduled_sample_id, production_reliability_eligible,
            disposition, accountable, run_id, accepted_output_id, failure_reason,
            fallback_used, as_of, recorded_at, record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            operational_id,
            operational["operational_opportunity_audit_hash"],
            graph_run_id,
            run_slot_id,
            revision["production_variant_roster_id"],
            revision["production_variant_roster_revision_id"],
            revision["execution_behavior_release_id"],
            "cohort_default",
            "zh",
            agent_id,
            track["track_key_hash"],
            "PRODUCTION_ACTIVE",
            "OUTCOME_SCHEDULED",
            sample_id,
            1,
            "ACCEPTED",
            1,
            run_id,
            accepted_id,
            None,
            0,
            as_of,
            operational_without_hash["recorded_at"],
            canonical_json(operational),
        ),
    )

    versions = {
        key: contract[key]
        for key in (
            "outcome_contract_version",
            "scoring_contract_version",
            "sample_schedule_contract_version",
            "rank_scope_contract_version",
        )
    }
    audit_id = f"eligibility:{sample_id}"
    audit_without_hash = {
        "audit_revision_id": audit_id,
        "audit_id": audit_id,
        "supersedes_revision_id": None,
        "audit_sequence": 1,
        "scheduled_sample_id": sample_id,
        "track_key_hash": track["track_key_hash"],
        "agent_id": agent_id,
        "sample_origin": "PRODUCTION_ACTIVE",
        "disposition": "SCORE",
        "accepted_output_id": accepted_id,
        "accepted_output_hash": accepted["accepted_output_hash"],
        "evaluation_opportunity_set_id": opportunity_id,
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "opportunity_set_status": "AVAILABLE",
        "exclusion_or_failure_reason": None,
        "darwin_evaluation_eligible": True,
        "usage_weight_eligible": True,
        "contract_versions": versions,
        "recorded_at": outcome_due_at,
    }
    audit = {
        **audit_without_hash,
        "audit_revision_hash": canonical_hash(audit_without_hash),
    }
    _insert(
        conn,
        """
        INSERT INTO agent_outcome_eligibility_revisions_v2 (
            audit_revision_id, audit_revision_hash, audit_id,
            supersedes_revision_id, scheduled_sample_id, track_key_hash,
            agent_id, sample_origin, research_pair_side, disposition,
            accepted_output_id, opportunity_set_status, audit_sequence,
            recorded_at, record_json
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, 'PRODUCTION_ACTIVE', NULL,
                  'SCORE', ?, 'AVAILABLE', 1, ?, ?)
        """,
        (
            audit_id,
            audit["audit_revision_hash"],
            audit_id,
            sample_id,
            track["track_key_hash"],
            agent_id,
            accepted_id,
            outcome_due_at,
            canonical_json(audit),
        ),
    )

    raw_metrics = {
        "direction_sign": 1 if target > 0 else -1,
        "strength": 5,
        "confidence": 1.0,
        "role_path_metric": target,
        "pit_volatility_scale": 1.0,
        "point_forecast": 1.0 if target > 0 else -1.0,
        "realized_scaled_path": target if cached_target is None else cached_target,
        "forecast_loss": 0.0,
        "null_loss": 1.0,
        "combined_utility_delta": 1.0,
    }
    label_without_hash = {
        "outcome_sequence": sequence,
        "outcome_label_id": f"label:{sample_id}",
        "audit_revision_id": audit_id,
        "audit_revision_hash": audit["audit_revision_hash"],
        "scheduled_sample_id": sample_id,
        "track_key_hash": track["track_key_hash"],
        "agent_id": agent_id,
        "primary_label_id": contract["primary_label_id"],
        "sample_origin": "PRODUCTION_ACTIVE",
        "darwin_evaluation_eligible": True,
        "usage_weight_eligible": True,
        "realized_outcome_observation_id": f"observation:{sample_id}",
        "realized_outcome_observation_hash": canonical_hash(sample_id),
        "raw_metrics": raw_metrics,
        "utility_delta": 1.0,
        "normalization_reference": {"fixture": True},
        "normalized_score": 1.0,
        "outcome_due_at": outcome_due_at,
        "matured_at": outcome_due_at.replace("T15:00:00", "T16:00:00"),
        "contract_versions": versions,
    }
    label = {
        **label_without_hash,
        "outcome_label_hash": canonical_hash(label_without_hash),
    }
    _insert(
        conn,
        """
        INSERT INTO agent_outcome_labels_v2 (
            outcome_sequence, outcome_label_id, outcome_label_hash,
            audit_revision_id, scheduled_sample_id, track_key_hash, agent_id,
            primary_label_id, sample_origin, darwin_evaluation_eligible,
            usage_weight_eligible, normalized_score, outcome_due_at, matured_at,
            record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PRODUCTION_ACTIVE', 1, 1, 1, ?, ?, ?)
        """,
        (
            sequence,
            label["outcome_label_id"],
            label["outcome_label_hash"],
            audit_id,
            sample_id,
            track["track_key_hash"],
            agent_id,
            contract["primary_label_id"],
            outcome_due_at,
            label_without_hash["matured_at"],
            canonical_json(label),
        ),
    )

    components = sorted(composition["components"])
    base_signals = [1.0, -0.2, -0.2, -0.4]
    signed = [value if target > 0 else -value for value in base_signals]
    for component, signal_value in zip(components, signed, strict=True):
        signal_without_hash = {
            "component_calibration_signal_id": f"signal:{sample_id}:{component}",
            "sample_origin": "PRODUCTION_ACTIVE",
            **common,
            "accepted_output_id": accepted_id,
            "accepted_output_hash": accepted["accepted_output_hash"],
            "operational_opportunity_audit_id": operational_id,
            "operational_opportunity_audit_hash": operational[
                "operational_opportunity_audit_hash"
            ],
            "calibration_sample_role": "FIT_REFERENCE",
            "agent_contract_version": track["agent_contract_version"],
            "prompt_behavior_version": track["prompt_behavior_version"],
            "execution_behavior_version": track["execution_behavior_version"],
            "component_weight_contract_version": track[
                "component_weight_contract_version"
            ],
            "outcome_contract_version": contract["outcome_contract_version"],
            "scoring_contract_version": contract["scoring_contract_version"],
            "primary_label_id": contract["primary_label_id"],
            "sample_schedule_contract_version": contract[
                "sample_schedule_contract_version"
            ],
            "rank_scope_contract_version": contract[
                "rank_scope_contract_version"
            ],
            "rank_scope": contract["rank_scope"],
            "as_of": as_of,
            "component": component,
            "component_weight": composition["components"][component],
            "signal": signal_value,
            "model_confidence": 1.0,
            "deterministic_data_quality": 1.0,
            "effective_confidence": 1.0,
            "live_persistence_horizon": "WEEKS",
            "evaluation_horizon_trading_days": 5,
            "evidence_bundle_ids": [f"evidence:{sample_id}:{component}"],
            "outcome_due_at": outcome_due_at,
        }
        signal = {
            **signal_without_hash,
            "component_calibration_signal_hash": canonical_hash(signal_without_hash),
        }
        _insert(
            conn,
            """
            INSERT INTO component_calibration_signals_v2 (
                component_calibration_signal_id,
                component_calibration_signal_hash, accepted_output_id,
                operational_opportunity_audit_id, production_variant_roster_id,
                production_variant_roster_revision_id,
                execution_behavior_release_id, cohort_id, language,
                calibration_sample_role, agent_id, track_key_hash, component,
                scheduled_sample_id, as_of, outcome_due_at, record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal["component_calibration_signal_id"],
                signal["component_calibration_signal_hash"],
                accepted_id,
                operational_id,
                revision["production_variant_roster_id"],
                revision["production_variant_roster_revision_id"],
                revision["execution_behavior_release_id"],
                "cohort_default",
                "zh",
                "FIT_REFERENCE",
                agent_id,
                track["track_key_hash"],
                component,
                sample_id,
                as_of,
                outcome_due_at,
                canonical_json(signal),
            ),
        )


def _regime_snapshot(as_of_dates: list[str], generated_at: str) -> dict:
    observations = []
    for index, as_of in enumerate(as_of_dates):
        observations.append(
            {
                "as_of": as_of,
                "available_at": f"{as_of}T15:00:00+08:00",
                "private_fixture_sequence": index,
                "source_evidence_ids": [f"market:volatility:{as_of}"],
            }
        )
    return build_component_regime_snapshot(
        observations=observations,
        generated_at=generated_at,
        source_evidence_ids=["market:a-share-volatility-regime"],
    )


def test_component_calibration_contract_is_shared_by_exactly_seven_macro_agents() -> None:
    rows = [
        contract["component_composition_contract"]
        for contract in OUTCOME_CONTRACTS.values()
        if contract["component_composition_contract"] is not None
    ]
    assert len(rows) == 7
    hashes = {canonical_hash(row["calibration_contract"]) for row in rows}
    assert len(hashes) == 1
    calibration = rows[0]["calibration_contract"]
    assert calibration["minimum_fit_samples"] == 60
    assert calibration["minimum_production_samples"] == 100
    assert calibration["minimum_shadow_samples"] == 20
    assert calibration["semiannual_slot_months"] == [6, 12]


def test_component_calibration_shadow_release_and_rollback_are_append_only(
    tmp_path: Path,
) -> None:
    store, revision, track = _registered(tmp_path)
    dates = _trading_dates(date(2018, 1, 1), date(2026, 12, 31))
    first_cutoff = "2025-06-30"
    first_index = dates.index(first_cutoff)
    training_dates = dates[first_index - 500 : first_index : 5]
    assert len(training_dates) == 100
    with store._connect() as conn:
        for sequence, as_of in enumerate(training_dates, start=1):
            as_of_index = dates.index(as_of)
            _seed_component_sample(
                conn,
                revision=revision,
                track=track,
                as_of=as_of,
                outcome_due_at=f"{dates[as_of_index + 5]}T15:00:00+08:00",
                sequence=sequence,
                target=1.0 if sequence % 2 else -1.0,
            )
        candidate = run_component_calibration(
            conn,
            reference_track_key_hash=track["track_key_hash"],
            cutoff_at=f"{first_cutoff}T17:00:00+08:00",
            trading_calendar_snapshot=_calendar_snapshot(
                dates, f"{first_cutoff}T17:00:00+08:00"
            ),
            regime_snapshot=_regime_snapshot(
                training_dates, f"{first_cutoff}T17:00:00+08:00"
            ),
        )
        assert candidate["candidate_status"] == "SHADOW_CANDIDATE"
        assert candidate["fit_sample_count"] == 100
        assert candidate["validation_metrics"]["mse_improvement_ratio"] >= 0.05
        assert candidate["candidate_weights"] != candidate["previous_weights"]
        assert candidate["production_sample_threshold_met"] is True
        assert run_component_calibration(
            conn,
            reference_track_key_hash=track["track_key_hash"],
            cutoff_at=f"{first_cutoff}T17:00:00+08:00",
            trading_calendar_snapshot=_calendar_snapshot(
                dates, f"{first_cutoff}T17:00:00+08:00"
            ),
            regime_snapshot=_regime_snapshot(
                training_dates, f"{first_cutoff}T17:00:00+08:00"
            ),
        )["component_calibration_candidate_id"] == candidate[
            "component_calibration_candidate_id"
        ]

        shadow_dates = dates[first_index + 5 : first_index + 105 : 5]
        assert len(shadow_dates) == 20
        for offset, as_of in enumerate(shadow_dates, start=101):
            as_of_index = dates.index(as_of)
            _seed_component_sample(
                conn,
                revision=revision,
                track=track,
                as_of=as_of,
                outcome_due_at=f"{dates[as_of_index + 5]}T15:00:00+08:00",
                sequence=offset,
                target=1.0 if offset % 2 else -1.0,
            )
        second_cutoff = "2025-12-31"
        checkpoint = append_component_shadow_checkpoint(
            conn,
            component_calibration_candidate_id=candidate[
                "component_calibration_candidate_id"
            ],
            cutoff_at=f"{second_cutoff}T17:00:00+08:00",
            trading_calendar_snapshot=_calendar_snapshot(
                dates, f"{second_cutoff}T17:00:00+08:00"
            ),
            regime_snapshot=_regime_snapshot(
                [*training_dates, *shadow_dates],
                f"{second_cutoff}T17:00:00+08:00",
            ),
        )
        assert checkpoint["new_shadow_sample_count"] == 20
        assert checkpoint["checkpoint_status"] == "PROMOTION_ELIGIBLE"
        release = publish_component_weight_release(
            conn,
            component_calibration_candidate_id=candidate[
                "component_calibration_candidate_id"
            ],
            component_calibration_shadow_checkpoint_id=checkpoint[
                "component_calibration_shadow_checkpoint_id"
            ],
            recorded_at="2025-12-31T18:00:00+08:00",
            effective_at="2026-01-05T00:00:00+08:00",
        )
        before = resolve_component_weights(
            conn,
            agent_id="us_economy",
            at="2026-01-04T23:59:59+08:00",
        )
        after = resolve_component_weights(
            conn,
            agent_id="us_economy",
            at="2026-01-05T00:00:00+08:00",
        )
        assert before["component_weights"] == candidate["previous_weights"]
        assert after["component_weights"] == candidate["candidate_weights"]
        prepared_before = prepare_production_variant(
            conn,
            binding=_runtime_binding(),
            as_of="2026-01-04T23:59:59+08:00",
        )
        prepared_after = prepare_production_variant(
            conn,
            binding=_runtime_binding(),
            as_of="2026-01-05T00:00:00+08:00",
        )
        prepared_after_retry = prepare_production_variant(
            conn,
            binding=_runtime_binding(),
            as_of="2026-01-06T00:00:00+08:00",
        )
        assert prepared_before["runtime_binding"] == _runtime_binding()
        resolved_after = {
            row["agent_id"]: row
            for row in prepared_after["component_weight_snapshot"]["resolutions"]
        }
        assert resolved_after["us_economy"] == after
        assert prepared_after["runtime_binding"]["agent_behavior_bindings"][
            "us_economy"
        ]["component_weight_contract_version"] == after[
            "component_weight_contract_version"
        ]
        assert prepared_after["runtime_binding"]["execution_behavior_release_id"] != (
            _runtime_binding()["execution_behavior_release_id"]
        )
        assert prepared_after_retry["runtime_binding"][
            "execution_behavior_release_id"
        ] == prepared_after["runtime_binding"]["execution_behavior_release_id"]
        assert len(prepared_after["weight_snapshot"]["weights"]) == 24
        active_revision = prepared_after["roster_revision"]
        placeholders = ",".join(
            "?" for _ in active_revision["evaluation_track_key_hashes"]
        )
        active_track_hash = conn.execute(
            f"SELECT track_key_hash FROM darwinian_v2_evaluation_tracks "
            f"WHERE track_key_hash IN ({placeholders}) AND agent_id = 'us_economy'",
            tuple(active_revision["evaluation_track_key_hashes"]),
        ).fetchone()[0]
        continued = run_component_calibration(
            conn,
            reference_track_key_hash=active_track_hash,
            cutoff_at="2026-06-30T17:00:00+08:00",
            trading_calendar_snapshot=_calendar_snapshot(
                dates, "2026-06-30T17:00:00+08:00"
            ),
            regime_snapshot=_regime_snapshot(
                [*training_dates, *shadow_dates],
                "2026-06-30T17:00:00+08:00",
            ),
        )
        assert continued["fit_sample_count"] == 120
        assert continued["previous_component_weight_contract_version"] == after[
            "component_weight_contract_version"
        ]
        assert continued["previous_weights"] == after["component_weights"]
        rollback = rollback_component_weight_release(
            conn,
            agent_id="us_economy",
            rollback_to_revision_id=release["component_weight_release_revision_id"],
            recorded_at="2026-01-06T00:00:00+08:00",
            effective_at="2026-01-07T00:00:00+08:00",
        )
        assert rollback["action"] == "ROLLBACK"
        restored = resolve_component_weights(
            conn,
            agent_id="us_economy",
            at="2026-01-07T00:00:00+08:00",
        )
        assert restored["component_weights"] == candidate["previous_weights"]
        prepared_rollback = prepare_production_variant(
            conn,
            binding=_runtime_binding(),
            as_of="2026-01-07T00:00:00+08:00",
        )
        rollback_resolution = {
            row["agent_id"]: row
            for row in prepared_rollback["component_weight_snapshot"]["resolutions"]
        }["us_economy"]
        assert rollback_resolution == restored
        assert prepared_rollback["runtime_binding"]["agent_behavior_bindings"][
            "us_economy"
        ]["component_weight_contract_version"] == restored[
            "component_weight_contract_version"
        ]
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute(
                "UPDATE component_calibration_candidates_v2 SET fit_sample_count = 0"
            )


def test_component_calibration_rejects_non_slot_and_target_cache_drift(
    tmp_path: Path,
) -> None:
    store, revision, track = _registered(tmp_path)
    dates = _trading_dates(date(2024, 1, 1), date(2025, 12, 31))
    cutoff = "2025-06-30"
    as_of = dates[dates.index(cutoff) - 5]
    with store._connect() as conn:
        _seed_component_sample(
            conn,
            revision=revision,
            track=track,
            as_of=as_of,
            outcome_due_at=f"{cutoff}T15:00:00+08:00",
            sequence=1,
            target=1.0,
            cached_target=-1.0,
        )
        regime = _regime_snapshot([as_of], f"{cutoff}T17:00:00+08:00")
        with pytest.raises(ValueError, match="fixed semiannual"):
            run_component_calibration(
                conn,
                reference_track_key_hash=track["track_key_hash"],
                cutoff_at="2025-06-27T17:00:00+08:00",
                trading_calendar_snapshot=_calendar_snapshot(
                    dates, "2025-06-27T17:00:00+08:00"
                ),
                regime_snapshot=regime,
            )
        result = run_component_calibration(
            conn,
            reference_track_key_hash=track["track_key_hash"],
            cutoff_at=f"{cutoff}T17:00:00+08:00",
            trading_calendar_snapshot=_calendar_snapshot(
                dates, f"{cutoff}T17:00:00+08:00"
            ),
            regime_snapshot=regime,
        )
        assert result["candidate_status"] == "HELD_INSUFFICIENT_SAMPLES"
        assert result["fit_sample_count"] == 0
        assert any(
            "target audit cache mismatch" in row["reason"]
            for row in result["excluded_samples"]
        )

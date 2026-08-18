from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.darwinian_v2 import (
    validate_production_variant_roster_revision,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.store import ScorecardStore


def _bindings() -> dict[str, dict[str, str | None]]:
    rows: dict[str, dict[str, str | None]] = {}
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        dimensions = contract["track_contract_dimensions"]
        rows[agent_id] = {
            "agent_contract_version": f"{agent_id}_agent_v2",
            "prompt_behavior_version": f"{agent_id}_prompt_v2",
            "execution_behavior_version": f"{agent_id}_execution_v2",
            "component_weight_contract_version": (
                "macro_component_weights_v2"
                if dimensions["component_weight_contract"] == "REQUIRED"
                else None
            ),
            "reliability_adapter_contract_version": (
                f"{agent_id}_reliability_adapter_v2"
                if dimensions["reliability_adapter_contract"] == "REQUIRED"
                else None
            ),
            "confidence_semantics_contract_version": (
                f"{agent_id}_confidence_semantics_v2"
                if dimensions["confidence_semantics_contract"] == "REQUIRED"
                else None
            ),
        }
    return rows


def _register(store: ScorecardStore, release: str, effective_at: str):
    return store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id=release,
        behavior_bindings=_bindings(),
        effective_at=effective_at,
    )


def test_new_variant_registers_25_evaluation_and_21_usage_tracks(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = _register(store, "release-1", "2026-07-17T09:00:00+08:00")
    assert revision["inserted_evaluation_tracks"] == 25
    assert revision["inserted_usage_tracks"] == 21
    assert revision["inserted_cold_start_weights"] == 21
    assert len(revision["evaluation_track_key_hashes"]) == 25
    assert len(revision["usage_track_key_hashes"]) == 21
    assert len(revision["decision_evaluation_track_key_hashes"]) == 4
    assert revision["prepared_at"] == "2026-07-17T09:00:00+08:00"
    assert revision["recorded_at"] == "2026-07-17T09:00:00+08:00"
    assert revision["effective_slot_sequence"] == 1

    snapshot = store.get_darwinian_v2_weight_snapshot(
        production_variant_roster_revision_id=revision[
            "production_variant_roster_revision_id"
        ],
        as_of="2026-07-17T23:59:59+08:00",
    )
    assert len(snapshot["weights"]) == 21
    assert {row["darwin_weight"] for row in snapshot["weights"]} == {1.0}
    assert {row["record_kind"] for row in snapshot["weights"]} == {
        "COLD_START_INITIALIZATION"
    }
    assert not {
        "cro",
        "alpha_discovery",
        "autonomous_execution",
        "cio",
    } & {row["agent_id"] for row in snapshot["weights"]}


def test_registration_is_idempotent_and_unchanged_tracks_survive_new_release(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    first = _register(store, "release-1", "2026-07-17T09:00:00+08:00")
    retry = _register(store, "release-1", "2026-07-17T09:00:00+08:00")
    assert retry["production_variant_roster_revision_id"] == first[
        "production_variant_roster_revision_id"
    ]
    assert retry["inserted_evaluation_tracks"] == 0
    assert retry["inserted_usage_tracks"] == 0
    assert retry["inserted_cold_start_weights"] == 0
    assert retry["inserted_roster_revision"] is False

    second = _register(store, "release-2", "2026-07-18T09:00:00+08:00")
    assert second["production_variant_roster_id"] == first[
        "production_variant_roster_id"
    ]
    assert second["production_variant_roster_revision_id"] != first[
        "production_variant_roster_revision_id"
    ]
    assert second["evaluation_track_key_hashes"] == first[
        "evaluation_track_key_hashes"
    ]
    assert second["inserted_evaluation_tracks"] == 0
    assert second["inserted_cold_start_weights"] == 0
    assert second["effective_slot_sequence"] == 2


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("production_variant_roster_id", " roster:test"),
        ("language", "fr"),
        ("effective_slot_sequence", 0),
        ("recorded_at", "2026-07-18T09:00:00+08:00"),
    ],
)
def test_roster_revision_validator_rejects_resealed_semantic_tamper(
    tmp_path: Path,
    field: str,
    invalid: object,
) -> None:
    revision = _register(
        ScorecardStore(tmp_path / "scorecard.db"),
        "release-1",
        "2026-07-17T09:00:00+08:00",
    )
    record = {
        key: value for key, value in revision.items() if not key.startswith("inserted_")
    }
    record[field] = invalid
    body = {
        key: value
        for key, value in record.items()
        if key != "production_variant_roster_revision_hash"
    }
    record["production_variant_roster_revision_hash"] = canonical_hash(body)
    with pytest.raises(ValueError, match="production roster revision"):
        validate_production_variant_roster_revision(record)


def test_roster_revision_validator_requires_exact_sha256_track_hashes(
    tmp_path: Path,
) -> None:
    revision = _register(
        ScorecardStore(tmp_path / "scorecard.db"),
        "release-1",
        "2026-07-17T09:00:00+08:00",
    )
    record = {
        key: value for key, value in revision.items() if not key.startswith("inserted_")
    }
    record["evaluation_track_key_hashes"][0] = "sha256:short"
    body = {
        key: value
        for key, value in record.items()
        if key != "production_variant_roster_revision_hash"
    }
    record["production_variant_roster_revision_hash"] = canonical_hash(body)
    with pytest.raises(ValueError, match="track hash"):
        validate_production_variant_roster_revision(record)


def test_registration_binds_authoritative_revision_timing_and_sequence(
    tmp_path: Path,
) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    first = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-1",
        behavior_bindings=_bindings(),
        prepared_at="2026-07-17T08:00:00+08:00",
        recorded_at="2026-07-17T08:30:00+08:00",
        effective_at="2026-07-17T09:00:00+08:00",
        effective_slot_sequence=1,
    )
    assert first["effective_slot_sequence"] == 1

    with pytest.raises(ValueError, match="prepared_at <= recorded_at <= effective_at"):
        store.register_darwinian_production_variant(
            cohort_id="cohort_default",
            language="zh",
            execution_behavior_release_id="release-backdated",
            behavior_bindings=_bindings(),
            prepared_at="2026-07-17T08:45:00+08:00",
            recorded_at="2026-07-17T09:15:00+08:00",
            effective_at="2026-07-17T09:00:00+08:00",
            effective_slot_sequence=2,
        )

    with pytest.raises(ValueError, match="next roster sequence"):
        store.register_darwinian_production_variant(
            cohort_id="cohort_default",
            language="zh",
            execution_behavior_release_id="release-gap",
            behavior_bindings=_bindings(),
            prepared_at="2026-07-18T08:00:00+08:00",
            recorded_at="2026-07-18T08:30:00+08:00",
            effective_at="2026-07-18T09:00:00+08:00",
            effective_slot_sequence=3,
        )


def test_registration_rejects_nullable_track_dimension_drift(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    bindings = _bindings()
    bindings["institutional_flow"]["component_weight_contract_version"] = "forbidden"
    with pytest.raises(ValueError, match="institutional_flow.*must be null"):
        store.register_darwinian_production_variant(
            cohort_id="cohort_default",
            language="zh",
            execution_behavior_release_id="release-1",
            behavior_bindings=bindings,
            effective_at="2026-07-17T09:00:00+08:00",
        )


def test_v2_ledgers_reject_update_and_delete_at_database_boundary(tmp_path: Path) -> None:
    db_path = tmp_path / "scorecard.db"
    store = ScorecardStore(db_path)
    revision = _register(store, "release-1", "2026-07-17T09:00:00+08:00")
    track_hash = revision["evaluation_track_key_hashes"][0]
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute(
                "UPDATE darwinian_v2_evaluation_tracks SET agent_id = 'x' "
                "WHERE track_key_hash = ?",
                (track_hash,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute(
                "DELETE FROM darwinian_v2_evaluation_tracks WHERE track_key_hash = ?",
                (track_hash,),
            )

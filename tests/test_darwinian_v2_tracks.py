from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

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


def test_new_variant_registers_28_evaluation_and_24_usage_tracks(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = _register(store, "release-1", "2026-07-17T09:00:00+08:00")
    assert revision["inserted_evaluation_tracks"] == 28
    assert revision["inserted_usage_tracks"] == 24
    assert revision["inserted_cold_start_weights"] == 24
    assert len(revision["evaluation_track_key_hashes"]) == 28
    assert len(revision["usage_track_key_hashes"]) == 24
    assert len(revision["decision_evaluation_track_key_hashes"]) == 4

    snapshot = store.get_darwinian_v2_weight_snapshot(
        production_variant_roster_revision_id=revision[
            "production_variant_roster_revision_id"
        ],
        as_of="2026-07-17T23:59:59+08:00",
    )
    assert len(snapshot["weights"]) == 24
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


def test_registration_rejects_nullable_track_dimension_drift(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    bindings = _bindings()
    bindings["geopolitical"]["component_weight_contract_version"] = "forbidden"
    with pytest.raises(ValueError, match="geopolitical.*must be null"):
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

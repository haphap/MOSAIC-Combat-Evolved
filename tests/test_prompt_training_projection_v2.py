from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Sequence

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from mosaic.bridge.handlers import prompt_optimizer
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.capability_preservation import (
    build_knot_capability_use_aggregate,
    load_capability_contract_bundle,
    validate_capability_contract_bundle,
)
from mosaic.scorecard.darwinian_updates import materialize_due_outcomes
from mosaic.scorecard.prompt_optimizer_store import PromptOptimizerStore
from mosaic.scorecard.store import ScorecardStore
from tests.outcome_source_authority_helpers import (
    provision_test_outcome_source_authority,
)
from tests.test_darwinian_outcome_maturation import (
    CUTOFF_AT,
    _bindings,
    _seed_pending,
    _track_by_agent,
    _trading_dates,
    _write_projection,
)


_ROOT = Path(__file__).parents[1]


def _current_knot_partition(
    accepted_output_hashes: Sequence[str],
    *,
    cutoff_at: str,
    excluded: bool = False,
) -> dict[str, Any]:
    bundle = load_capability_contract_bundle(_ROOT)
    tool_manifest = json.loads(
        (_ROOT / "registry/prompt_checks/agent_tool_contract_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    validate_capability_contract_bundle(
        bundle,
        current_tool_manifest=tool_manifest,
    )
    accepted_track = bundle["accepted_output_capability_track"]
    audit_track = bundle["knot_audit_capability_track_v2"]
    coverage = bundle["knot_coverage_manifest_v2"]
    fixed_point = {
        "tool_environment_hash": accepted_track["tool_environment_hash"],
        "execution_behavior_release_hash": audit_track[
            "execution_behavior_release_hash"
        ],
        "capability_bundle_hash": accepted_track["capability_bundle_hash"],
        "knot_coverage_manifest_v2_hash": coverage["manifest_hash"],
        "knot_audit_capability_track_v2_hash": audit_track["track_hash"],
    }
    aggregates = [
        build_knot_capability_use_aggregate(
            binding_id=str(row["binding_id"]),
            observations=[],
        )
        for row in coverage["coverage"]
    ]
    materialization_refs = []
    excluded_refs = []
    for accepted_output_hash in sorted(accepted_output_hashes):
        if excluded:
            excluded_body = {
                "accepted_output_hash": accepted_output_hash,
                "materialization_hash": canonical_hash(
                    {"accepted_output_hash": accepted_output_hash}
                ),
                "reasons": ["LEGACY_KNOT_CAPTURE_MISSING"],
            }
            excluded_refs.append(
                {
                    "accepted_output_hash": accepted_output_hash,
                    "sample_ref_hash": canonical_hash(excluded_body),
                    "reasons": excluded_body["reasons"],
                }
            )
        else:
            materialization_refs.append(
                {
                    "accepted_output_hash": accepted_output_hash,
                    "materialization_hash": canonical_hash(
                        {"accepted_output_hash": accepted_output_hash}
                    ),
                }
            )
    body = {
        "schema_version": "knot_training_history_partition_v2",
        "cutoff_at": cutoff_at,
        **fixed_point,
        "history_partition_hash": canonical_hash(fixed_point),
        "sample_count": len(materialization_refs),
        "excluded_sample_count": len(excluded_refs),
        "materialization_refs": materialization_refs,
        "excluded_sample_refs": excluded_refs,
        "binding_aggregates": aggregates,
        "materialization_set_hash": canonical_hash(materialization_refs),
        "excluded_sample_set_hash": canonical_hash(excluded_refs),
        "binding_aggregate_set_hash": canonical_hash(
            [row["aggregate_hash"] for row in aggregates]
        ),
    }
    return {**body, "partition_hash": canonical_hash(body)}


class _KnotHistoryStore:
    def __init__(self, *, excluded: bool = False) -> None:
        self.excluded = excluded
        self.selected_hashes: list[str] | None = None

    def build_knot_history_partition_v2(
        self,
        *,
        cutoff_at: str,
        accepted_output_hashes: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        assert accepted_output_hashes is not None
        self.selected_hashes = list(accepted_output_hashes)
        return _current_knot_partition(
            accepted_output_hashes,
            cutoff_at=cutoff_at,
            excluded=self.excluded,
        )


def _mature_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ScorecardStore, dict[str, Any], dict[str, Any], dict[str, Any]]:
    runtime_root = tmp_path / "outcome-runtime"
    monkeypatch.setenv("MOSAIC_OUTCOME_RUNTIME_DIR", str(runtime_root))
    authority = provision_test_outcome_source_authority(tmp_path, monkeypatch)
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        track_hash = _track_by_agent(conn, revision)["geopolitical"]
        slot, opportunity, pending = _seed_pending(
            conn,
            revision=revision,
            tracks={"geopolitical": track_hash},
            agent_id="geopolitical",
        )
        _write_projection(
            runtime_root,
            conn,
            agent_id="geopolitical",
            track_hash=track_hash,
            slot=slot,
            opportunity=opportunity,
            pending=pending,
            authority=authority,
        )
        result = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_trading_dates(),
        )
    assert result["scored_count"] == 1
    assert result["unresolved_count"] == 0
    return store, pending, slot, revision


def test_prompt_training_projection_v2_joins_maturity_and_knot_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, pending, slot, revision = _mature_sample(tmp_path, monkeypatch)
    knot_store = _KnotHistoryStore()

    projection = store.build_prompt_training_projection_v2(
        agent_id="geopolitical",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at=CUTOFF_AT,
        knot_history_store=knot_store,
    )

    assert knot_store.selected_hashes == [pending["accepted_output_hash"]]
    assert projection["schemaVersion"] == "prompt_training_projection_v2"
    assert projection["matureSampleCount"] == 1
    assert projection["eligibleSampleIdsHash"] == canonical_hash(
        [slot["scheduled_sample_id"]]
    )
    assert projection["excludedSampleIdsHash"] == canonical_hash([])
    roster_refs = [
        {
            "revisionId": revision["production_variant_roster_revision_id"],
            "revisionHash": revision["production_variant_roster_revision_hash"],
        }
    ]
    assert projection["productionVariantRosterRevisions"] == roster_refs
    assert projection["productionVariantRosterRevisionSetHash"] == canonical_hash(
        roster_refs
    )
    coverage = load_capability_contract_bundle(_ROOT)["knot_coverage_manifest_v2"]["coverage"]
    assert len(projection["capabilityUseAggregates"]) == len(coverage)
    assert projection["projectionHash"] == canonical_hash(
        {key: value for key, value in projection.items() if key != "projectionHash"}
    )
    assert "evidenceGapSummaries" not in projection
    assert "record_json" not in json.dumps(projection)

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        plan = conn.execute(
            "SELECT trading_calendar_snapshot_hash FROM outcome_schedule_plans_v2 "
            "WHERE outcome_schedule_plan_id = ("
            "SELECT outcome_schedule_plan_id FROM outcome_schedule_slots_v2 "
            "WHERE scheduled_sample_id = ?)",
            (slot["scheduled_sample_id"],),
        ).fetchone()
        label = json.loads(
            conn.execute(
                "SELECT record_json FROM agent_outcome_labels_v2 "
                "WHERE scheduled_sample_id = ?",
                (slot["scheduled_sample_id"],),
            ).fetchone()[0]
        )
        observation = json.loads(
            conn.execute(
                "SELECT record_json FROM realized_outcome_observations_v2 "
                "WHERE realized_outcome_observation_id = ?",
                (label["realized_outcome_observation_id"],),
            ).fetchone()[0]
        )
        batch = json.loads(
            conn.execute(
                "SELECT record_json FROM outcome_source_batches_v1 "
                "WHERE source_batch_id = ?",
                (observation["source_batch_id"],),
            ).fetchone()[0]
        )
    assert projection["maturityContract"]["tradingCalendarHash"] == canonical_hash(
        [
            {
                "sampleId": slot["scheduled_sample_id"],
                "tradingCalendarSnapshotHash": plan[
                    "trading_calendar_snapshot_hash"
                ],
            }
        ]
    )
    receipt_hashes = sorted(
        ref["source_receipt_hash"]
        for ref in batch["receipt_refs_by_required_source_id"].values()
    )
    assert projection["maturityContract"]["labelReceiptSetHash"] == canonical_hash(
        [
            {
                "sampleId": slot["scheduled_sample_id"],
                "acceptedOutputHash": pending["accepted_output_hash"],
                "outcomeLabelHash": label["outcome_label_hash"],
                "realizedOutcomeObservationHash": observation[
                    "realized_outcome_observation_hash"
                ],
                "sourceBatchHash": batch["source_batch_hash"],
                "sourceReceiptHashes": receipt_hashes,
            }
        ]
    )
    schema = json.loads(
        (_ROOT / "schemas/prompt_training_projection_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(projection)

    optimizer_store = PromptOptimizerStore(store.db_path)
    assert optimizer_store.put_training_projection_v2(projection) == projection
    assert optimizer_store.put_training_projection_v2(projection) == projection
    assert (
        optimizer_store.get_training_projection_v2(projection["projectionHash"])
        == projection
    )
    monkeypatch.setattr(prompt_optimizer, "_store", lambda: optimizer_store)
    assert prompt_optimizer.put_training_projection_v2({"record": projection}) == projection
    assert prompt_optimizer.get_training_projection_v2(
        {"projection_hash": projection["projectionHash"]}
    ) == {"record": projection}
    with sqlite3.connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute(
                "UPDATE prompt_training_projections_v2 SET stage = 'tampered'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute("DELETE FROM prompt_training_projections_v2")


def test_prompt_training_projection_v2_excludes_knot_ineligible_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, pending, slot, _ = _mature_sample(tmp_path, monkeypatch)
    knot_store = _KnotHistoryStore(excluded=True)

    projection = store.build_prompt_training_projection_v2(
        agent_id="geopolitical",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at=CUTOFF_AT,
        knot_history_store=knot_store,
    )

    assert knot_store.selected_hashes == [pending["accepted_output_hash"]]
    assert projection["matureSampleCount"] == 0
    assert projection["productionVariantRosterRevisions"] == []
    assert projection["productionVariantRosterRevisionSetHash"] == canonical_hash([])
    assert projection["eligibleSampleIdsHash"] == canonical_hash([])
    assert projection["excludedSampleIdsHash"] == canonical_hash(
        [slot["scheduled_sample_id"]]
    )
    assert projection["knotExcludedSampleSetHash"] != canonical_hash([])


def test_prompt_training_projection_v2_rejects_forged_knot_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, _, _ = _mature_sample(tmp_path, monkeypatch)

    class ForgedKnotHistoryStore(_KnotHistoryStore):
        def build_knot_history_partition_v2(
            self,
            *,
            cutoff_at: str,
            accepted_output_hashes: Sequence[str] | None = None,
        ) -> dict[str, Any]:
            partition = super().build_knot_history_partition_v2(
                cutoff_at=cutoff_at,
                accepted_output_hashes=accepted_output_hashes,
            )
            partition["sample_count"] = 2
            return partition

    with pytest.raises(ValueError, match="KNOT history partition hash mismatch"):
        store.build_prompt_training_projection_v2(
            agent_id="geopolitical",
            stage="agent_run",
            cohort="cohort_default",
            cutoff_at=CUTOFF_AT,
            knot_history_store=ForgedKnotHistoryStore(),
        )


def test_prompt_training_projection_v2_revalidates_historical_source_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, _, _ = _mature_sample(tmp_path, monkeypatch)
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT source_batch_id, record_json FROM outcome_source_batches_v1"
        ).fetchone()
        batch = json.loads(row[1])
        batch["sealed_at"] = "2026-07-17T14:59:59+08:00"
        conn.execute("DROP TRIGGER no_update_outcome_source_batches_v1")
        conn.execute(
            "UPDATE outcome_source_batches_v1 SET record_json = ? "
            "WHERE source_batch_id = ?",
            (json.dumps(batch), row[0]),
        )

    with pytest.raises(ValueError, match="stored outcome source batch hash mismatch"):
        store.build_prompt_training_projection_v2(
            agent_id="geopolitical",
            stage="agent_run",
            cohort="cohort_default",
            cutoff_at=CUTOFF_AT,
            knot_history_store=_KnotHistoryStore(),
        )

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.dataflows.outcome_runtime_inputs import (
    EVENT_COVERAGE_SCHEMA_VERSION,
    OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
    load_evaluation_opportunity_projection,
    load_verified_event_coverage,
)
from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS


AS_OF = "2026-07-17T15:00:00+08:00"


def _write_hashed(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {**payload, "snapshot_hash": canonical_hash(payload)}
    path.write_text(json.dumps(record), encoding="utf-8")


def _event_coverage() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        schedule = contract["sample_schedule"]
        if schedule["kind"] != "EVENT_TRIGGERED":
            continue
        result[agent_id] = {
            "coverage_status": "COMPLETE",
            "coverage_evidence_ids": [f"coverage:{agent_id}"],
            "event_registry_version": schedule["event_registry_version"],
            "event_priority_version": schedule["event_priority_version"],
            "candidates": [],
        }
    return result


def test_event_coverage_requires_hashed_exact_pit_roster(tmp_path: Path) -> None:
    root = tmp_path / "outcome-runtime"
    payload = {
        "schema_version": EVENT_COVERAGE_SCHEMA_VERSION,
        "as_of": AS_OF,
        "generated_at": "2026-07-17T14:59:00+08:00",
        "pit_status": "VERIFIED",
        "event_coverage": _event_coverage(),
    }
    path = root / "2026-07-17" / "event_coverage.json"
    _write_hashed(path, payload)
    assert load_verified_event_coverage(AS_OF, root=root) == payload["event_coverage"]

    corrupted = json.loads(path.read_text(encoding="utf-8"))
    corrupted["event_coverage"].pop(next(iter(corrupted["event_coverage"])))
    corrupted_without_hash = {
        key: value for key, value in corrupted.items() if key != "snapshot_hash"
    }
    corrupted["snapshot_hash"] = canonical_hash(corrupted_without_hash)
    path.write_text(json.dumps(corrupted), encoding="utf-8")
    with pytest.raises(ValueError, match="exact event-triggered"):
        load_verified_event_coverage(AS_OF, root=root)


@pytest.mark.parametrize("status", ["AVAILABLE", "GENERATION_FAILURE"])
def test_opportunity_projection_closes_required_sources_and_status(
    tmp_path: Path,
    status: str,
) -> None:
    root = tmp_path / "outcome-runtime"
    agent_id = "us_economy"
    source_evidence = {
        source_id: [f"evidence:{index}:{source_id}"]
        for index, source_id in enumerate(OUTCOME_CONTRACTS[agent_id]["required_source_ids"])
    }
    payload = {
        "schema_version": OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
        "agent_id": agent_id,
        "as_of": AS_OF,
        "generated_at": "2026-07-17T14:58:00+08:00",
        "pit_status": "VERIFIED",
        "projection_status": status,
        "qualification_predicate_version": "us_macro_release_qualification_v2",
        "member_refs": [{"release_id": "us-cpi-2026-06"}] if status == "AVAILABLE" else [],
        "source_evidence_by_required_source_id": source_evidence,
        "error_codes": [] if status == "AVAILABLE" else ["REQUIRED_DATA_UNAVAILABLE"],
    }
    _write_hashed(
        root / "2026-07-17" / "opportunities" / f"{agent_id}.json",
        payload,
    )
    assert load_evaluation_opportunity_projection(
        AS_OF,
        agent_id,
        root=root,
    )["projection_status"] == status


def test_missing_runtime_input_is_not_reinterpreted_as_no_event(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="unavailable"):
        load_verified_event_coverage(AS_OF, root=tmp_path)

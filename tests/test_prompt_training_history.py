from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.prompt_optimizer_store import PromptOptimizerStore
from mosaic.scorecard.prompt_training_history import _cio_proposal
from mosaic.scorecard.store import ScorecardStore
from tests.test_component_calibration import _registered, _seed_component_sample
from tests.test_prompt_optimizer_store import advance_complete


def _stage(agent_id: str) -> str:
    return {
        "cro": "cro_review",
        "alpha_discovery": "alpha_discovery",
        "autonomous_execution": "execution_feasibility",
        "cio": "cio_final",
    }.get(agent_id, "agent_run")


def _weekdays(start: date, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values


def test_training_history_declares_all_28_role_owned_targets(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.sqlite3")
    assert len(OUTCOME_CONTRACTS) == 28
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        history = store.build_prompt_training_history(
            agent_id=agent_id,
            stage=_stage(agent_id),
            cohort="cohort_default",
            cutoff_at="2026-08-01T00:00:00+08:00",
        )
        assert history["target"] == {
            "agentId": agent_id,
            "stage": _stage(agent_id),
            "cohort": "cohort_default",
        }
        assert history["outcomeContractVersion"] == contract["outcome_contract_version"]
        assert history["primaryLabelId"] == contract["primary_label_id"]
        assert history["records"] == []
        assert history["validationExperiments"] == []
        assert history["historyHash"] == canonical_hash(
            {key: value for key, value in history.items() if key != "historyHash"}
        )
    with pytest.raises(ValueError, match="stage does not belong"):
        store.build_prompt_training_history(
            agent_id="cio",
            stage="agent_run",
            cohort="cohort_default",
            cutoff_at="2026-08-01T00:00:00+08:00",
        )


def test_training_history_exports_pit_component_records_and_exclusions(
    tmp_path: Path,
) -> None:
    store, revision, track = _registered(tmp_path)
    days = _weekdays(date(2024, 1, 2), 31)
    with store._connect() as conn:
        for index, as_of_day in enumerate(days):
            due_day = as_of_day + timedelta(days=10)
            _seed_component_sample(
                conn,
                revision=revision,
                track=track,
                as_of=as_of_day.isoformat(),
                outcome_due_at=f"{due_day.isoformat()}T15:00:00+08:00",
                sequence=index + 1,
                target=0.2 if index % 2 == 0 else -0.2,
            )
    excluded_sample = f"component-sample:{days[0].isoformat()}"
    history = store.build_prompt_training_history(
        agent_id="us_economy",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at="2024-04-30T23:59:59+08:00",
        excluded_sample_ids=[excluded_sample],
    )
    assert len(history["records"]) == 30
    assert excluded_sample not in {record["sampleId"] for record in history["records"]}
    assert history["excludedSampleIds"] == [excluded_sample]
    assert {
        signal["component"] for signal in history["records"][0]["componentSignals"]
    } == {"growth_production", "prices", "employment", "demand_trade"}
    assert all("acceptedPayload" not in record for record in history["records"])
    assert all(
        record["supportingAcceptedOutputs"] == {} for record in history["records"]
    )
    assert all(
        record["maturedAt"] <= history["cutoffAt"] for record in history["records"]
    )

    historical = store.build_prompt_training_history(
        agent_id="us_economy",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at=f"{(days[10] + timedelta(days=10)).isoformat()}T23:59:59+08:00",
    )
    assert 0 < len(historical["records"]) < len(history["records"])
    assert all(
        record["maturedAt"] <= historical["cutoffAt"]
        for record in historical["records"]
    )


def test_training_history_exports_validation_only_without_holdout(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scorecard.sqlite3"
    scorecard = ScorecardStore(database)
    optimizer = PromptOptimizerStore(database)
    advance_complete(optimizer)
    history = scorecard.build_prompt_training_history(
        agent_id="china",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at="2025-04-02T00:00:00Z",
    )
    assert len(history["validationExperiments"]) == 1
    validation = history["validationExperiments"][0]
    assert validation["candidatePrivateLineageHash"].startswith("sha256:")
    assert validation["validationPairCount"] == 1
    assert validation["validationPairDeltas"] == pytest.approx([0.1])
    assert "holdout" not in json.dumps(history).lower()

    reserved = scorecard.build_prompt_training_history(
        agent_id="china",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at="2025-04-02T00:00:00Z",
        excluded_sample_ids=["validation-1"],
    )
    assert reserved["validationExperiments"] == []

    before_validation = scorecard.build_prompt_training_history(
        agent_id="china",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at="2025-03-31T00:00:00Z",
    )
    assert before_validation["validationExperiments"] == []

    with scorecard._connect() as conn:
        row = conn.execute(
            "SELECT experiment_id, record_json FROM prompt_experiments_v3 "
            "WHERE status = 'COMPLETE'"
        ).fetchone()
        experiment = json.loads(row["record_json"])
        experiment["metrics"]["validation_candidate_mean"] += 0.01
        conn.execute(
            "UPDATE prompt_experiments_v3 SET record_json = ? WHERE experiment_id = ?",
            (json.dumps(experiment), row["experiment_id"]),
        )
    with pytest.raises(ValueError, match="validation aggregate mismatch"):
        scorecard.build_prompt_training_history(
            agent_id="china",
            stage="agent_run",
            cohort="cohort_default",
            cutoff_at="2025-04-02T00:00:00Z",
        )


def test_training_history_binds_cio_proposal_to_the_same_run() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE accepted_agent_outputs_v2 ("
        "graph_run_id TEXT, cohort_id TEXT, language TEXT, agent_id TEXT, "
        "accepted_output_kind TEXT, sample_origin TEXT, record_json TEXT)"
    )
    shared = {
        "graph_run_id": "graph-cio-1",
        "run_slot_id": "slot-cio-1",
        "operational_opportunity_audit_id": "audit-cio-1",
        "production_variant_roster_id": "roster-1",
        "production_variant_roster_revision_id": "revision-1",
        "execution_behavior_release_id": "release-1",
        "cohort_id": "cohort_default",
        "language": "zh",
        "track_key_hash": "sha256:" + "1" * 64,
        "prompt_behavior_version": "cio-prompt-v2",
        "execution_behavior_version": "cio-execution-v2",
        "as_of": "2026-07-17",
    }
    proposal_body = {
        **shared,
        "accepted_output_id": "accepted-cio-proposal",
        "agent_id": "cio",
        "accepted_output_kind": "CIO_PROPOSAL",
        "sample_origin": "PRODUCTION_ACTIVE",
        "output": {
            "payload": {
                "agent_id": "cio",
                "decision_stage": "PROPOSAL",
                "decision": {"decision_disposition": "ALL_CASH"},
            }
        },
    }
    proposal = {
        **proposal_body,
        "accepted_output_hash": canonical_hash(proposal_body),
    }
    conn.execute(
        "INSERT INTO accepted_agent_outputs_v2 VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            proposal["graph_run_id"],
            proposal["cohort_id"],
            proposal["language"],
            proposal["agent_id"],
            proposal["accepted_output_kind"],
            proposal["sample_origin"],
            json.dumps(proposal),
        ),
    )
    final = {**shared, "agent_id": "cio"}
    supporting = _cio_proposal(conn, final)
    assert supporting == {
        "agentOutputRef": "accepted-cio-proposal",
        "agentOutputHash": proposal["accepted_output_hash"],
    }

    forged_final = {**final, "run_slot_id": "slot-cio-forged"}
    with pytest.raises(ValueError, match="proposal/final behavior binding mismatch"):
        _cio_proposal(conn, forged_final)

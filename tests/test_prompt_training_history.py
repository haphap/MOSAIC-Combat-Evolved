from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.prompt_training_history import (
    _build_direct_components,
    _cio_proposal,
    _format_timestamp,
    _timestamp,
)
from mosaic.scorecard.store import ScorecardStore
from tests.test_component_calibration import _registered, _seed_component_sample
from tests.test_prompt_optimizer_store import advance_complete, store as optimizer_store


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


def _seed_one_prompt_training_sample(
    tmp_path: Path,
    *,
    eligibility_disposition: str = "SCORE",
    audit_darwin_evaluation_eligible: bool = True,
    label_darwin_evaluation_eligible: bool = True,
) -> ScorecardStore:
    store, revision, track = _registered(tmp_path)
    with store._connect() as conn:
        _seed_component_sample(
            conn,
            revision=revision,
            track=track,
            as_of="2024-01-02",
            outcome_due_at="2024-01-12T15:00:00+08:00",
            sequence=1,
            target=0.2,
            eligibility_disposition=eligibility_disposition,
            audit_darwin_evaluation_eligible=audit_darwin_evaluation_eligible,
            label_darwin_evaluation_eligible=label_darwin_evaluation_eligible,
        )
    return store


def test_training_timestamp_round_trip_keeps_millisecond_precision() -> None:
    completed_at = _timestamp(
        "2025-04-01T02:00:00.123Z", "Prompt experiment completedAt"
    )

    assert _format_timestamp(completed_at) == "2025-04-01T02:00:00.123Z"


EXPECTED_DIRECT_ORDINALS = {
    "china": [0, 1, 2, 3, 4, 5],
    "us_economy": [0, 1, 2, 3, 4],
    "eu_economy": [0, 1, 2, 3, 4],
    "central_bank": [0, 1, 2, 3, 4],
    "us_financial_conditions": [0, 1, 2, 3, 4],
    "euro_area_financial_conditions": [0, 1, 2, 3, 4],
    "commodities": [0, 1, 2, 3, 4],
    "geopolitical": [5],
    "market_breadth": [5],
    "institutional_flow": [5],
    "semiconductor": [2, 3, 4, 5],
    "technology": [2, 3, 4, 5],
    "energy": [2, 3, 4, 5],
    "biotech": [2, 3, 4, 5],
    "consumer": [2, 3, 4, 5],
    "industrials": [2, 3, 4, 5],
    "real_estate_construction": [2, 3, 4, 5],
    "financials": [2, 3, 4, 5],
    "agriculture": [2, 3, 4, 5],
    "druckenmiller": [4],
    "munger": [4],
    "burry": [4],
    "ackman": [4],
    "cro": [0, 1, 4],
    "alpha_discovery": [2, 3, 4],
    "autonomous_execution": [0, 1, 2, 4],
    "cio": [3, 4],
}


def test_training_projection_declares_all_27_role_owned_targets(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.sqlite3")
    assert len(OUTCOME_CONTRACTS) == 27
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        projection = store.build_prompt_training_projection(
            agent_id=agent_id,
            stage=_stage(agent_id),
            cohort="cohort_default",
            cutoff_at="2026-08-01T00:00:00+08:00",
        )
        assert projection["target"] == {
            "agentId": agent_id,
            "stage": _stage(agent_id),
            "cohort": "cohort_default",
        }
        assert projection["outcomeContract"]["outcomeContractVersion"] == contract[
            "outcome_contract_version"
        ]
        assert projection["outcomeContract"]["primaryLabelId"] == contract[
            "primary_label_id"
        ]
        assert projection["matureSampleCount"] == 0
        assert projection["controlledExperiments"] == []
        assert [
            component["componentRef"] for component in projection["directComponents"]
        ] == [
            f"role_component_v1:{agent_id}:{ordinal:03d}"
            for ordinal in EXPECTED_DIRECT_ORDINALS[agent_id]
        ]
        assert projection["projectionHash"] == canonical_hash(
            {
                key: value
                for key, value in projection.items()
                if key != "projectionHash"
            }
        )
    with pytest.raises(ValueError, match="stage does not belong"):
        store.build_prompt_training_projection(
            agent_id="cio",
            stage="agent_run",
            cohort="cohort_default",
            cutoff_at="2026-08-01T00:00:00+08:00",
        )


def test_role_component_scoring_keeps_china_and_sector_components_distinct() -> None:
    macro_selectors = [
        "growth_production",
        "prices",
        "credit",
        "external_demand_trade",
        "fiscal",
    ]
    china = _build_direct_components(
        "china",
        [
            {
                "normalizedScore": 0.8,
                "rawMetrics": {"realized_scaled_path": 0.5},
                "componentSignals": [
                    {
                        "component": selector,
                        "signal": signal,
                        "effective_confidence": 1.0,
                    }
                    for selector, signal in zip(
                        macro_selectors, [-1.0, -0.5, 0.0, 0.25, 0.8], strict=True
                    )
                ],
            }
        ],
    )
    assert len(china) == 6
    assert len({component["meanScore"] for component in china}) == 6

    sector = _build_direct_components(
        "semiconductor",
        [
            {
                "normalizedScore": 0.0,
                "rawMetrics": {
                    "direction_metrics": [
                        {
                            "selected_role": "PREFERRED",
                            "realized_scaled_path": 0.5,
                            "predicted_tilt": 0.5,
                        },
                        {
                            "selected_role": "LEAST_PREFERRED",
                            "realized_scaled_path": -0.5,
                            "predicted_tilt": 0.5,
                        },
                    ],
                    "security_leg_metrics": [
                        {
                            "side": "PREFERRED",
                            "side_security_utility_delta": 0.4,
                        },
                        {
                            "side": "LEAST_PREFERRED",
                            "side_security_utility_delta": -0.4,
                        },
                    ],
                },
                "componentSignals": [],
            }
        ],
    )
    assert [component["componentRef"] for component in sector] == [
        "role_component_v1:semiconductor:002",
        "role_component_v1:semiconductor:003",
        "role_component_v1:semiconductor:004",
        "role_component_v1:semiconductor:005",
    ]
    assert len({component["meanScore"] for component in sector}) == 4


def test_training_projection_exports_pit_scores_and_exclusions(
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
    projection = store.build_prompt_training_projection(
        agent_id="us_economy",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at="2024-04-30T23:59:59+08:00",
        excluded_sample_ids=[excluded_sample],
    )
    assert projection["matureSampleCount"] == 30
    assert projection["excludedSampleIdsHash"] == canonical_hash([excluded_sample])
    assert projection["directComponents"][0]["componentRef"] == (
        "role_component_v1:us_economy:000"
    )
    assert projection["directComponents"][0]["directMatureSampleCount"] == 30
    assert projection["scoreSummary"]["mean"] == pytest.approx(1.0)
    assert "records" not in projection
    assert "componentSignals" not in json.dumps(projection)

    historical = store.build_prompt_training_projection(
        agent_id="us_economy",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at=f"{(days[10] + timedelta(days=10)).isoformat()}T23:59:59+08:00",
    )
    assert 0 < historical["matureSampleCount"] < projection["matureSampleCount"]


def test_training_projection_includes_the_exact_pit_maturity_boundary(
    tmp_path: Path,
) -> None:
    store = _seed_one_prompt_training_sample(tmp_path)

    before = store.build_prompt_training_projection(
        agent_id="us_economy",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at="2024-01-12T15:59:59+08:00",
    )
    at_boundary = store.build_prompt_training_projection(
        agent_id="us_economy",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at="2024-01-12T16:00:00+08:00",
    )

    assert before["matureSampleCount"] == 0
    assert at_boundary["matureSampleCount"] == 1


@pytest.mark.parametrize(
    "seed_options",
    [
        {"eligibility_disposition": "PENDING"},
        {"audit_darwin_evaluation_eligible": False},
    ],
    ids=["non_score_disposition", "audit_not_darwin_eligible"],
)
def test_training_projection_rejects_non_score_or_ineligible_audit_lineage(
    tmp_path: Path,
    seed_options: dict[str, object],
) -> None:
    store = _seed_one_prompt_training_sample(tmp_path, **seed_options)

    with pytest.raises(ValueError, match="Prompt training history lineage mismatch"):
        store.build_prompt_training_projection(
            agent_id="us_economy",
            stage="agent_run",
            cohort="cohort_default",
            cutoff_at="2024-01-12T16:00:00+08:00",
        )


def test_training_projection_excludes_a_label_not_marked_darwin_eligible(
    tmp_path: Path,
) -> None:
    store = _seed_one_prompt_training_sample(
        tmp_path,
        label_darwin_evaluation_eligible=False,
    )

    projection = store.build_prompt_training_projection(
        agent_id="us_economy",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at="2024-01-12T16:00:00+08:00",
    )

    assert projection["matureSampleCount"] == 0


def test_training_projection_exports_validation_only_without_holdout(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scorecard.sqlite3"
    scorecard = ScorecardStore(database)
    optimizer = optimizer_store(tmp_path)
    completed, _, _ = advance_complete(optimizer)
    cutoff_at = _format_timestamp(
        _timestamp(completed["completedAt"], "completedAt")
        + timedelta(seconds=1)
    )
    projection = scorecard.build_prompt_training_projection(
        agent_id="china",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at=cutoff_at,
    )
    assert len(projection["controlledExperiments"]) == 1
    validation = projection["controlledExperiments"][0]
    assert validation["candidatePrivateLineageHash"].startswith("sha256:")
    assert validation["pairDeltas"] == pytest.approx([0.1] * 60)
    assert validation["status"] == "COMPLETE"
    assert validation["evaluatorVersion"] == OUTCOME_CONTRACTS["china"][
        "scoring_contract_version"
    ]
    assert validation["evaluatorConfigHash"].startswith("sha256:")
    assert validation["executorAdapterHash"].startswith("sha256:")
    assert validation["evaluatorAdapterHash"].startswith("sha256:")
    assert len(validation["codeCommit"]) == 40
    assert "holdout" not in json.dumps(projection).lower()
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/prompt_training_projection_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(projection)

    frozen_split = optimizer.get_split(str(completed["datasetSplitId"]))
    assert frozen_split is not None
    reserved_sample_id = frozen_split["validation"]["samples"][0]["sampleId"]
    reserved = scorecard.build_prompt_training_projection(
        agent_id="china",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at=cutoff_at,
        excluded_sample_ids=[reserved_sample_id],
    )
    assert reserved["controlledExperiments"] == []

    before_validation = scorecard.build_prompt_training_projection(
        agent_id="china",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at="2025-03-31T00:00:00Z",
    )
    assert before_validation["controlledExperiments"] == []

    with scorecard._connect() as conn:
        row = conn.execute(
            "SELECT experiment_id, record_json FROM prompt_experiments_v3 "
            "WHERE status = 'COMPLETE'"
        ).fetchone()
        experiment = json.loads(row["record_json"])
        experiment["status"] = "VALIDATION_COMPLETE"
        conn.execute(
            "UPDATE prompt_experiments_v3 SET status = ?, record_json = ? "
            "WHERE experiment_id = ?",
            ("VALIDATION_COMPLETE", json.dumps(experiment), row["experiment_id"]),
        )
    validation_only = scorecard.build_prompt_training_projection(
        agent_id="china",
        stage="agent_run",
        cohort="cohort_default",
        cutoff_at=cutoff_at,
    )
    assert validation_only["controlledExperiments"] == []

    with scorecard._connect() as conn:
        row = conn.execute(
            "SELECT experiment_id, record_json FROM prompt_experiments_v3 "
            "WHERE status = 'VALIDATION_COMPLETE'"
        ).fetchone()
        experiment = json.loads(row["record_json"])
        experiment["status"] = "COMPLETE"
        experiment["metrics"]["validation_candidate_mean"] += 0.01
        conn.execute(
            "UPDATE prompt_experiments_v3 SET status = ?, record_json = ? "
            "WHERE experiment_id = ?",
            ("COMPLETE", json.dumps(experiment), row["experiment_id"]),
        )
    with pytest.raises(ValueError, match="validation aggregate mismatch"):
        scorecard.build_prompt_training_projection(
            agent_id="china",
            stage="agent_run",
            cohort="cohort_default",
            cutoff_at=cutoff_at,
        )


def test_training_projection_binds_cio_proposal_to_the_same_run() -> None:
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

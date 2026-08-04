from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mosaic.scorecard.prompt_optimizer_store import PromptOptimizerStore


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
COMMIT = "c" * 40
NOW = "2025-04-01T00:00:00Z"
TARGET = {"agentId": "china", "stage": "agent_run", "cohort": "cohort_default"}


def candidate() -> dict[str, object]:
    return {
        "schemaVersion": "prompt_candidate_v1",
        "candidateId": "candidate-1",
        "parentId": "champion-1",
        "target": TARGET,
        "promptRefs": {
            "zh": "private://candidate-1.zh",
            "en": "private://candidate-1.en",
        },
        "promptHashes": {"zh": HASH_A, "en": HASH_B},
        "trainingSnapshotId": "training-1",
        "trainingSnapshotHash": HASH_A,
        "mutatorConfigHash": HASH_A,
        "mutatorCommit": COMMIT,
        "mutationSummary": "test counter-evidence first",
        "hypothesis": "counter-evidence ordering improves normalized score",
        "createdAt": NOW,
    }


def experiment(status: str = "PENDING") -> dict[str, object]:
    holdout_opened_at = (
        "2025-04-01T01:00:00Z" if status in {"HOLDOUT_RUNNING", "COMPLETE"} else None
    )
    completed_at = "2025-04-01T02:00:00Z" if status in {"COMPLETE", "FAILED"} else None
    return {
        "schemaVersion": "prompt_experiment_v1",
        "experimentId": "experiment-1",
        "candidateId": "candidate-1",
        "championId": "champion-1",
        "target": TARGET,
        "championPromptHashes": {"zh": HASH_B, "en": HASH_A},
        "candidatePromptHashes": {"zh": HASH_A, "en": HASH_B},
        "datasetSplitManifestHash": HASH_A,
        "validationSnapshotHash": HASH_B,
        "holdoutSnapshotHash": HASH_A,
        "modelConfigHash": HASH_A,
        "toolConfigHash": HASH_A,
        "evaluatorVersion": "agent-outcome-v2",
        "evaluatorConfigHash": HASH_B,
        "codeCommit": COMMIT,
        "repeatSeeds": [1, 2],
        "runIds": [],
        "metrics": {},
        "tailFailureCaseRefs": [],
        "status": status,
        "holdoutOpenedAt": holdout_opened_at,
        "createdAt": NOW,
        "completedAt": completed_at,
    }


def complete_run() -> dict[str, object]:
    return {
        "schemaVersion": "prompt_experiment_run_v1",
        "runId": "run-1",
        "experimentId": "experiment-1",
        "partition": "VALIDATION",
        "side": "CHAMPION",
        "sampleId": "sample-1",
        "seed": 1,
        "status": "COMPLETE",
        "agentOutputRef": "accepted://run-1",
        "metrics": {"normalized_score": 0.25},
        "failureCaseRefs": [],
        "traceRef": None,
        "effectiveInputHash": HASH_A,
        "errorCode": None,
        "startedAt": NOW,
        "completedAt": "2025-04-01T00:01:00Z",
    }


def decision() -> dict[str, object]:
    return {
        "schemaVersion": "prompt_promotion_decision_v1",
        "decisionId": "decision-1",
        "experimentId": "experiment-1",
        "candidateId": "candidate-1",
        "policyVersion": "prompt-promotion-v1",
        "policyConfigHash": HASH_A,
        "decision": "ELIGIBLE",
        "reasons": ["all_validation_and_holdout_gates_passed"],
        "metricSummary": {"paired_delta": 0.1},
        "decidedAt": "2025-04-01T03:00:00Z",
    }


def store(tmp_path: Path) -> PromptOptimizerStore:
    return PromptOptimizerStore(tmp_path / "scorecard.sqlite3")


def test_four_minimal_tables_and_idempotent_round_trip(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    prompt_store.put_candidate(candidate())
    prompt_store.put_candidate(candidate())
    prompt_store.put_experiment(experiment())
    prompt_store.put_experiment(experiment("VALIDATION_RUNNING"))
    prompt_store.put_run(complete_run())
    prompt_store.put_run(complete_run())

    prompt_store.put_experiment(experiment("VALIDATION_COMPLETE"))
    prompt_store.put_experiment(experiment("HOLDOUT_RUNNING"))
    prompt_store.put_experiment(experiment("COMPLETE"))
    prompt_store.put_decision(decision())
    prompt_store.put_decision(decision())

    assert prompt_store.get_candidate("candidate-1") == candidate()
    assert prompt_store.get_experiment("experiment-1") == experiment("COMPLETE")
    assert prompt_store.list_runs("experiment-1") == [complete_run()]
    assert prompt_store.get_decision("decision-1") == decision()

    with sqlite3.connect(tmp_path / "scorecard.sqlite3") as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'prompt_%_v2'"
            )
        }
    assert tables == {
        "prompt_candidates_v2",
        "prompt_experiments_v2",
        "prompt_experiment_runs_v2",
        "prompt_promotion_decisions_v2",
    }


def test_generated_schema_rejects_private_prompt_body_and_extra_fields(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    leaked = {**candidate(), "zh_prompt": "private prompt body"}
    with pytest.raises(ValueError, match="Additional properties are not allowed"):
        prompt_store.put_candidate(leaked)


def test_environment_and_identity_drift_fail_closed(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    prompt_store.put_candidate(candidate())
    prompt_store.put_experiment(experiment())
    prompt_store.put_experiment(experiment("VALIDATION_RUNNING"))

    drifted = {**experiment("VALIDATION_COMPLETE"), "modelConfigHash": HASH_B}
    with pytest.raises(ValueError, match="environment_drift"):
        prompt_store.put_experiment(drifted)

    prompt_store.put_run(complete_run())
    drifted_run = {**complete_run(), "sampleId": "different-sample"}
    with pytest.raises(ValueError, match="identity_drift"):
        prompt_store.put_run(drifted_run)


def test_decision_requires_completed_matching_experiment(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    prompt_store.put_candidate(candidate())
    prompt_store.put_experiment(experiment())
    with pytest.raises(ValueError, match="not_complete"):
        prompt_store.put_decision(decision())


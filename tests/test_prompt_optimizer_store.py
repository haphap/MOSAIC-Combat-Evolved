from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from mosaic.scorecard.prompt_optimizer_store import PromptOptimizerStore


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
COMMIT = "c" * 40
NOW = "2025-04-01T00:00:00Z"
TARGET = {"agentId": "china", "stage": "agent_run", "cohort": "cohort_default"}


def canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def candidate() -> dict[str, object]:
    prompt_hashes = {"zh": HASH_A, "en": HASH_B}
    alignment = {
        "alignmentVerifierVersion": "bilingual-alignment-v1",
        "promptHashes": prompt_hashes,
    }
    return {
        "schemaVersion": "prompt_candidate_v1",
        "candidateId": "candidate-1",
        "parentId": "champion-1",
        "parentPromptCommit": COMMIT,
        "parentPromptHashes": {"zh": HASH_B, "en": HASH_A},
        "target": TARGET,
        "promptRefs": {"zh": "private://candidate-1.zh", "en": "private://candidate-1.en"},
        "promptHashes": prompt_hashes,
        "trainingSnapshotId": "training-1",
        "trainingSnapshotHash": HASH_A,
        "mutatorConfigHash": HASH_A,
        "mutatorCommit": COMMIT,
        "mutationCategories": ["CONFLICT_RESOLUTION"],
        "mutationSummary": "Behavior focus: CONFLICT_RESOLUTION.",
        "hypothesis": (
            "Preregistered hypothesis: CONFLICT_RESOLUTION improves the frozen "
            "Agent outcome score."
        ),
        "alignmentVerifierVersion": "bilingual-alignment-v1",
        "behaviorAlignmentHash": canonical_hash(alignment),
        "behaviorContractHash": HASH_A,
        "createdAt": NOW,
    }


def sample(sample_id: str, start: str, end: str) -> dict[str, object]:
    return {
        "sampleId": sample_id,
        "inputRef": f"snapshot://{sample_id}",
        "outcomeRef": f"outcome://{sample_id}",
        "eventWindow": {"startAt": start, "endAt": end},
        "maturedAt": end,
    }


def split() -> dict[str, object]:
    return {
        "schemaVersion": "prompt_dataset_split_v1",
        "splitId": "split-1",
        "target": TARGET,
        "cutoffAt": "2025-01-31T00:00:00Z",
        "training": {
            "snapshotId": "training-1",
            "snapshotHash": HASH_A,
            "windowStartAt": "2025-01-01T00:00:00Z",
            "windowEndAt": "2025-01-31T00:00:00Z",
            "samples": [sample("training-1", "2025-01-10T00:00:00Z", "2025-01-11T00:00:00Z")],
        },
        "validation": {
            "snapshotId": "validation-1",
            "snapshotHash": HASH_B,
            "windowStartAt": "2025-02-01T00:00:00Z",
            "windowEndAt": "2025-02-28T00:00:00Z",
            "samples": [sample("validation-1", "2025-02-10T00:00:00Z", "2025-02-11T00:00:00Z")],
        },
        "holdout": {
            "snapshotId": "holdout-1",
            "snapshotHash": HASH_A,
            "windowStartAt": "2025-03-01T00:00:00Z",
            "windowEndAt": "2025-03-31T00:00:00Z",
            "samples": [sample("holdout-1", "2025-03-10T00:00:00Z", "2025-03-11T00:00:00Z")],
        },
        "evaluatorVersion": "agent-outcome-v2",
        "createdAt": NOW,
    }


def family(status: str = "REGISTERED") -> dict[str, object]:
    selected = status != "REGISTERED"
    return {
        "schemaVersion": "prompt_candidate_family_v1",
        "familyId": "family-1",
        "target": TARGET,
        "championReleaseId": "champion-1",
        "championPromptCommit": COMMIT,
        "championPromptRefs": {"zh": "private://champion.zh", "en": "private://champion.en"},
        "championPromptHashes": {"zh": HASH_B, "en": HASH_A},
        "datasetSplitId": "split-1",
        "datasetSplitManifestHash": canonical_hash(split()),
        "candidateIds": ["candidate-1"],
        "validationExperimentIds": ["experiment-1"] if selected else [],
        "selectedCandidateId": "candidate-1" if selected else None,
        "selectedExperimentId": "experiment-1" if selected else None,
        "holdoutExperimentId": "experiment-1" if status == "COMPLETE" else None,
        "status": status,
        "createdAt": NOW,
        "updatedAt": "2025-04-01T01:00:00Z" if selected else NOW,
    }


def aggregate_metrics(partition: str, candidate_score: float = 0.6) -> dict[str, float | int]:
    prefix = partition.lower()
    champion_score = 0.5
    return {
        f"{prefix}_candidate_mean": candidate_score,
        f"{prefix}_champion_mean": champion_score,
        f"{prefix}_paired_delta": candidate_score - champion_score,
        f"{prefix}_pair_count": 1,
    }


def experiment(status: str = "PENDING", run_ids: list[str] | None = None) -> dict[str, object]:
    holdout_open = status in {"HOLDOUT_RUNNING", "COMPLETE"}
    return {
        "schemaVersion": "prompt_experiment_v1",
        "experimentId": "experiment-1",
        "familyId": "family-1",
        "candidateId": "candidate-1",
        "championId": "champion-1",
        "target": TARGET,
        "championPromptCommit": COMMIT,
        "championPromptRefs": {"zh": "private://champion.zh", "en": "private://champion.en"},
        "championPromptHashes": {"zh": HASH_B, "en": HASH_A},
        "candidatePromptRefs": candidate()["promptRefs"],
        "candidatePromptHashes": candidate()["promptHashes"],
        "datasetSplitId": "split-1",
        "datasetSplitManifestHash": canonical_hash(split()),
        "validationSnapshotHash": HASH_B,
        "holdoutSnapshotHash": HASH_A,
        "modelConfigHash": HASH_A,
        "toolConfigHash": HASH_A,
        "evaluatorVersion": "agent-outcome-v2",
        "evaluatorConfigHash": HASH_B,
        "codeCommit": COMMIT,
        "repeatSeeds": [1],
        "runIds": sorted(run_ids or []),
        "metrics": (
            {}
            if status in {"PENDING", "VALIDATION_RUNNING"}
            else aggregate_metrics("VALIDATION")
        ),
        "tailFailureCaseRefs": [],
        "status": status,
        "holdoutOpenedAt": "2025-04-01T01:00:00Z" if holdout_open else None,
        "createdAt": NOW,
        "completedAt": "2025-04-01T02:00:00Z" if status in {"COMPLETE", "FAILED"} else None,
    }


def running_run(partition: str, side: str, sample_id: str) -> dict[str, object]:
    run_id = f"run-{partition.lower()}-{side.lower()}"
    return {
        "schemaVersion": "prompt_experiment_run_v1",
        "runId": run_id,
        "experimentId": "experiment-1",
        "partition": partition,
        "side": side,
        "sampleId": sample_id,
        "seed": 1,
        "status": "RUNNING",
        "agentOutputRef": None,
        "metrics": {},
        "failureCaseRefs": [],
        "traceRef": None,
        "effectiveInputHash": None,
        "errorCode": None,
        "startedAt": NOW,
        "completedAt": None,
    }


def complete_run(partition: str, side: str, sample_id: str) -> dict[str, object]:
    value = running_run(partition, side, sample_id)
    return {
        **value,
        "status": "COMPLETE",
        "agentOutputRef": f"accepted://{value['runId']}",
        "metrics": {"normalized_score": 0.6 if side == "CANDIDATE" else 0.5},
        "effectiveInputHash": HASH_A,
        "completedAt": "2025-04-01T00:01:00Z",
    }


def store(tmp_path: Path) -> PromptOptimizerStore:
    return PromptOptimizerStore(
        tmp_path / "scorecard.sqlite3", authorized_policy_hashes={HASH_A}
    )


def advance_complete(prompt_store: PromptOptimizerStore) -> tuple[dict[str, object], list[dict[str, object]]]:
    prompt_store.put_candidate(candidate())
    prompt_store.put_split(split())
    prompt_store.put_family(family())
    prompt_store.put_experiment(experiment())
    prompt_store.put_experiment(experiment("VALIDATION_RUNNING"))
    validation_runs = [
        complete_run("VALIDATION", side, "validation-1")
        for side in ("CHAMPION", "CANDIDATE")
    ]
    for run in validation_runs:
        assert prompt_store.claim_run({**run, "status": "RUNNING", "agentOutputRef": None, "metrics": {}, "effectiveInputHash": None, "completedAt": None})
        prompt_store.put_run(run)
    validation_ids = [str(run["runId"]) for run in validation_runs]
    prompt_store.put_experiment(experiment("VALIDATION_COMPLETE", validation_ids))
    prompt_store.put_family(family("SELECTED"))
    prompt_store.put_experiment(experiment("HOLDOUT_RUNNING", validation_ids))
    holdout_runs = [complete_run("HOLDOUT", side, "holdout-1") for side in ("CHAMPION", "CANDIDATE")]
    for run in holdout_runs:
        assert prompt_store.claim_run({**run, "status": "RUNNING", "agentOutputRef": None, "metrics": {}, "effectiveInputHash": None, "completedAt": None})
        prompt_store.put_run(run)
    all_runs = validation_runs + holdout_runs
    completed = experiment("COMPLETE", [str(run["runId"]) for run in all_runs])
    completed["metrics"] = {
        **aggregate_metrics("VALIDATION"),
        **aggregate_metrics("HOLDOUT"),
    }
    prompt_store.put_experiment(completed)
    return completed, all_runs


def test_authority_closed_round_trip(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    completed, runs = advance_complete(prompt_store)
    persisted_family = prompt_store.get_family("family-1")
    assert persisted_family is not None
    evidence = {
        "experiment": completed,
        "family": persisted_family,
        "split": split(),
        "runs": sorted(runs, key=lambda row: str(row["runId"])),
        "policyConfigHash": HASH_A,
    }
    decision_id = "decision-" + canonical_hash(
        {"experimentId": "experiment-1", "policyHash": HASH_A}
    )[len("sha256:") : len("sha256:") + 24]
    decision = {
        "schemaVersion": "prompt_promotion_decision_v1",
        "decisionId": decision_id,
        "experimentId": "experiment-1",
        "familyId": "family-1",
        "candidateId": "candidate-1",
        "policyVersion": "prompt-promotion-v1",
        "policyConfigHash": HASH_A,
        "decision": "ELIGIBLE",
        "reasons": ["all_promotion_gates_passed"],
        "metricSummary": {"paired_delta": 0.1},
        "evidenceHash": canonical_hash(evidence),
        "decidedAt": "2025-04-01T03:00:00Z",
    }
    prompt_store.put_decision(decision)
    assert prompt_store.get_decision(decision_id) == decision

    with sqlite3.connect(tmp_path / "scorecard.sqlite3") as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'prompt_%_v3'"
            )
        }
    assert {"prompt_dataset_splits_v3", "prompt_candidate_families_v3"} <= tables


def test_complete_experiment_cannot_be_inserted_without_runs(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    prompt_store.put_candidate(candidate())
    prompt_store.put_split(split())
    prompt_store.put_family(family())
    with pytest.raises(ValueError, match="initial_status_invalid"):
        prompt_store.put_experiment(experiment("COMPLETE"))


def test_atomic_run_claim_has_one_winner(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    prompt_store.put_candidate(candidate())
    prompt_store.put_split(split())
    prompt_store.put_family(family())
    prompt_store.put_experiment(experiment())
    prompt_store.put_experiment(experiment("VALIDATION_RUNNING"))
    claim = running_run("VALIDATION", "CHAMPION", "validation-1")
    assert prompt_store.claim_run(claim) == claim
    assert prompt_store.claim_run(claim) is None


def test_validation_aggregate_is_recomputed_from_accepted_runs(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    prompt_store.put_candidate(candidate())
    prompt_store.put_split(split())
    prompt_store.put_family(family())
    prompt_store.put_experiment(experiment())
    prompt_store.put_experiment(experiment("VALIDATION_RUNNING"))
    runs = [
        complete_run("VALIDATION", side, "validation-1")
        for side in ("CHAMPION", "CANDIDATE")
    ]
    for run in runs:
        claim = {
            **run,
            "status": "RUNNING",
            "agentOutputRef": None,
            "metrics": {},
            "effectiveInputHash": None,
            "completedAt": None,
        }
        assert prompt_store.claim_run(claim)
        prompt_store.put_run(run)
    completed = experiment(
        "VALIDATION_COMPLETE", [str(run["runId"]) for run in runs]
    )
    completed["metrics"] = {**aggregate_metrics("VALIDATION"), "injected": 1.0}
    with pytest.raises(ValueError, match="validation_aggregate_mismatch"):
        prompt_store.put_experiment(completed)


def test_family_selection_recomputes_deterministic_winner(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    first = candidate()
    second = {**candidate(), "candidateId": "candidate-2"}
    prompt_store.put_candidate(first)
    prompt_store.put_candidate(second)
    prompt_store.put_split(split())
    registered = {
        **family(),
        "candidateIds": ["candidate-1", "candidate-2"],
    }
    prompt_store.put_family(registered)

    validation_ids: list[str] = []
    for candidate_id, experiment_id, candidate_score in (
        ("candidate-1", "experiment-1", 0.6),
        ("candidate-2", "experiment-2", 0.7),
    ):
        pending = {
            **experiment(),
            "experimentId": experiment_id,
            "candidateId": candidate_id,
        }
        prompt_store.put_experiment(pending)
        prompt_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
        runs: list[dict[str, object]] = []
        for side in ("CHAMPION", "CANDIDATE"):
            run = {
                **complete_run("VALIDATION", side, "validation-1"),
                "runId": f"run-{experiment_id}-{side.lower()}",
                "experimentId": experiment_id,
                "metrics": {
                    "normalized_score": candidate_score if side == "CANDIDATE" else 0.5
                },
            }
            claim = {
                **run,
                "status": "RUNNING",
                "agentOutputRef": None,
                "metrics": {},
                "effectiveInputHash": None,
                "completedAt": None,
            }
            assert prompt_store.claim_run(claim)
            prompt_store.put_run(run)
            runs.append(run)
        run_ids = sorted(str(run["runId"]) for run in runs)
        completed = {
            **pending,
            "status": "VALIDATION_COMPLETE",
            "runIds": run_ids,
            "metrics": aggregate_metrics("VALIDATION", candidate_score),
        }
        prompt_store.put_experiment(completed)
        validation_ids.append(experiment_id)

    selected_wrong_winner = {
        **registered,
        "validationExperimentIds": sorted(validation_ids),
        "selectedCandidateId": "candidate-1",
        "selectedExperimentId": "experiment-1",
        "status": "SELECTED",
        "updatedAt": "2025-04-01T01:00:00Z",
    }
    with pytest.raises(ValueError, match="winner_not_deterministic"):
        prompt_store.put_family(selected_wrong_winner)


def test_v3_store_leaves_prior_v2_audit_tables_untouched(tmp_path: Path) -> None:
    db_path = tmp_path / "scorecard.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE prompt_experiments_v2 (experiment_id TEXT PRIMARY KEY)"
        )
        conn.execute("INSERT INTO prompt_experiments_v2 VALUES ('legacy-experiment')")
    PromptOptimizerStore(db_path, authorized_policy_hashes={HASH_A})
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT experiment_id FROM prompt_experiments_v2"
        ).fetchone() == ("legacy-experiment",)
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'prompt_experiments_v3'"
        ).fetchone() == ("prompt_experiments_v3",)


def test_generated_schema_and_semantics_reject_private_or_free_form_text(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    with pytest.raises(ValueError, match="Additional properties are not allowed"):
        prompt_store.put_candidate({**candidate(), "zh_prompt": "private prompt body"})
    with pytest.raises(ValueError, match="summary_not_safe_projection"):
        prompt_store.put_candidate({**candidate(), "mutationSummary": "private evidence prose"})


def test_decision_rejects_evidence_hash_drift(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    advance_complete(prompt_store)
    value = {
        "schemaVersion": "prompt_promotion_decision_v1",
        "decisionId": "decision-"
        + canonical_hash({"experimentId": "experiment-1", "policyHash": HASH_A})[
            len("sha256:") : len("sha256:") + 24
        ],
        "experimentId": "experiment-1",
        "familyId": "family-1",
        "candidateId": "candidate-1",
        "policyVersion": "prompt-promotion-v1",
        "policyConfigHash": HASH_A,
        "decision": "ELIGIBLE",
        "reasons": ["all_promotion_gates_passed"],
        "metricSummary": {"paired_delta": 0.1},
        "evidenceHash": HASH_B,
        "decidedAt": "2025-04-01T03:00:00Z",
    }
    with pytest.raises(ValueError, match="evidence_hash_mismatch"):
        prompt_store.put_decision(value)


def test_eligible_decision_requires_installed_private_policy_hash(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    advance_complete(prompt_store)
    value = {
        "schemaVersion": "prompt_promotion_decision_v1",
        "decisionId": "decision-"
        + canonical_hash({"experimentId": "experiment-1", "policyHash": HASH_B})[
            len("sha256:") : len("sha256:") + 24
        ],
        "experimentId": "experiment-1",
        "familyId": "family-1",
        "candidateId": "candidate-1",
        "policyVersion": "uninstalled-policy-v1",
        "policyConfigHash": HASH_B,
        "decision": "ELIGIBLE",
        "reasons": ["all_promotion_gates_passed"],
        "metricSummary": {"paired_delta": 0.1},
        "evidenceHash": HASH_A,
        "decidedAt": "2025-04-01T03:00:00Z",
    }
    with pytest.raises(ValueError, match="policy_not_authorized"):
        prompt_store.put_decision(value)

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import mosaic.scorecard.prompt_optimizer_store as prompt_optimizer_store_module
from mosaic.scorecard.canonical_json import (
    canonical_hash,
    canonical_json,
    canonical_string_sort_key,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.prompt_optimizer_store import PromptOptimizerStore
from mosaic.scorecard.prompt_training_history import prompt_role_component_refs


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
COMMIT = "c" * 40
NOW = "2025-04-01T00:00:00Z"
TARGET = {"agentId": "china", "stage": "agent_run", "cohort": "cohort_default"}
CHINA_OUTCOME = OUTCOME_CONTRACTS["china"]
EXECUTION_RELEASE = {
    "release_id": "execution-behavior-release:" + "e" * 64,
    "release_hash": "sha256:" + "f" * 64,
    "archive_ref": (
        "registry/prompt_checks/execution_behavior_releases/"
        + "e" * 64
        + "--"
        + "f" * 64
        + ".json"
    ),
}


def content_id(prefix: str, value: object) -> str:
    return f"{prefix}-{canonical_hash(value).removeprefix('sha256:')}"


def ordered_mean(values: list[float]) -> float:
    total = 0.0
    for value in values:
        total += value
    return total / len(values)


def sample(label: str, start: str, end: str) -> dict[str, object]:
    body = {
        "inputRef": f"snapshot://{label}",
        "inputHash": HASH_A,
        "outcomeRef": f"outcome://{label}",
        "outcomeHash": HASH_B,
        "eventWindow": {"startAt": start, "endAt": end},
        "maturedAt": end,
    }
    identity = {
        key: body[key]
        for key in ("eventWindow", "inputHash", "maturedAt", "outcomeHash")
    }
    return {**body, "sampleId": content_id("sample", identity)}


def split(*, training_projection_hash: str | None = None) -> dict[str, object]:
    training = sample(
        "training-1", "2025-01-10T00:00:00Z", "2025-01-11T00:00:00Z"
    )
    validation = partition_samples("validation", "02")
    holdout = partition_samples("holdout", "03")
    body: dict[str, object] = {
        "schemaVersion": "prompt_dataset_split_v1",
        "target": TARGET,
        "trainingProjectionHash": (
            training_projection_hash
            if training_projection_hash is not None
            else training_projection()["projectionHash"]
        ),
        "cutoffAt": "2025-01-31T00:00:00Z",
        "training": {
            "snapshotHash": canonical_hash([training["sampleId"]]),
            "windowStartAt": "2025-01-01T00:00:00Z",
            "windowEndAt": "2025-01-31T00:00:00Z",
            "samples": [training],
        },
        "validation": {
            "snapshotHash": canonical_hash(
                sorted(value["sampleId"] for value in validation)
            ),
            "windowStartAt": "2025-02-01T00:00:00Z",
            "windowEndAt": "2025-02-28T00:00:00Z",
            "samples": validation,
        },
        "holdout": {
            "snapshotHash": canonical_hash(
                sorted(value["sampleId"] for value in holdout)
            ),
            "windowStartAt": "2025-03-01T00:00:00Z",
            "windowEndAt": "2025-03-31T00:00:00Z",
            "samples": holdout,
        },
        "evaluatorVersion": CHINA_OUTCOME["scoring_contract_version"],
        "createdAt": NOW,
    }
    identity = {key: value for key, value in body.items() if key != "createdAt"}
    return {**body, "splitId": content_id("split", identity)}


def partition_samples(prefix: str, month: str) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for index in range(30):
        day = 5 + index // 12
        start_hour = (index % 12) * 2
        values.append(
            sample(
                f"{prefix}-{index + 1}",
                f"2025-{month}-{day:02d}T{start_hour:02d}:00:00Z",
                f"2025-{month}-{day:02d}T{start_hour + 1:02d}:00:00Z",
            )
        )
    return values


def training_projection(
    *,
    projection_id: str | None = None,
    dataset_snapshot_hash: str = HASH_A,
    target: dict[str, str] | None = None,
) -> dict[str, object]:
    target_value = TARGET if target is None else target
    agent_id = target_value["agentId"]
    outcome_contract = OUTCOME_CONTRACTS[agent_id]
    if projection_id is None:
        projection_id = (
            "projection-china-default"
            if target_value == TARGET
            else f"projection-{agent_id}-{target_value['stage']}"
        )
    excluded_hash = canonical_hash(
        sorted(
            str(value["sampleId"])
            for value in [
                *partition_samples("validation", "02"),
                *partition_samples("holdout", "03"),
            ]
        )
    )
    evaluator = {
        "version": "prompt_role_component_evaluator_v1",
        "configHash": HASH_A,
        "executorAdapterHash": HASH_A,
        "evaluatorAdapterHash": HASH_B,
    }
    evaluator["implementationHash"] = canonical_hash(
        {
            "executorAdapterHash": evaluator["executorAdapterHash"],
            "evaluatorAdapterHash": evaluator["evaluatorAdapterHash"],
            "configHash": evaluator["configHash"],
        }
    )
    body: dict[str, object] = {
        "schemaVersion": "prompt_training_projection_v1",
        "target": target_value,
        "projectionId": projection_id,
        "datasetSnapshotHash": dataset_snapshot_hash,
        "excludedSampleIdsHash": excluded_hash,
        "cutoffAt": "2025-01-31T00:00:00Z",
        "outcomeContract": {
            "evaluationObject": outcome_contract["evaluation_object"],
            "outcomeContractVersion": outcome_contract["outcome_contract_version"],
            "primaryLabelId": outcome_contract["primary_label_id"],
            "maturityHorizon": outcome_contract["maturity_horizon"],
            "maturityTradingDays": outcome_contract["maturity"][
                "horizon_trading_days"
            ],
        },
        "evaluator": evaluator,
        "matureSampleCount": 30,
        "scoreSummary": {"mean": 0.1, "lower_tail": 0.05},
        "failureCategoryCounts": {},
        "tailFailureCaseRefs": [],
        "evidenceGapSummaries": [],
        "directComponents": [
            {
                "componentRef": component_ref,
                "directMatureSampleCount": 30,
                "meanScore": 0.1,
                "lowerTailScore": 0.05,
                "failureCategoryCounts": {},
            }
            for component_ref in prompt_role_component_refs(agent_id)
        ],
        "controlledExperiments": [],
    }
    return {**body, "projectionHash": canonical_hash(body)}


def recanonicalize_split(value: dict[str, object]) -> dict[str, object]:
    result = json.loads(json.dumps(value))
    for partition_name in ("training", "validation", "holdout"):
        partition = result[partition_name]
        for sample_record in partition["samples"]:
            identity = {
                key: sample_record[key]
                for key in ("eventWindow", "inputHash", "maturedAt", "outcomeHash")
            }
            sample_record["sampleId"] = content_id("sample", identity)
        partition["snapshotHash"] = canonical_hash(
            sorted(item["sampleId"] for item in partition["samples"])
        )
    identity = {
        key: item
        for key, item in result.items()
        if key not in {"splitId", "createdAt"}
    }
    result["splitId"] = content_id("split", identity)
    return result


def candidate(
    candidate_id: str = "candidate-1", *, split_record: dict[str, object] | None = None
) -> dict[str, object]:
    split_value = split_record or split()
    validation = split_value["validation"]
    holdout = split_value["holdout"]
    assert isinstance(validation, dict) and isinstance(holdout, dict)
    excluded = [
        row["sampleId"]
        for partition in (validation, holdout)
        for row in partition["samples"]
    ]
    return {
        "schemaVersion": "prompt_candidate_v1",
        "candidateId": candidate_id,
        "parentId": "champion-1",
        "parentPromptCommit": COMMIT,
        "parentPromptHashes": {"zh": HASH_B, "en": HASH_A},
        "target": TARGET,
        "promptRefs": {
            "zh": f"private://{candidate_id}.zh",
            "en": f"private://{candidate_id}.en",
        },
        "promptHashes": {"zh": HASH_A, "en": HASH_B},
        "trainingProjectionHash": split_value["trainingProjectionHash"],
        "excludedSampleIdsHash": canonical_hash(sorted(excluded)),
        "mutatorConfigHash": HASH_A,
        "mutatorCommit": COMMIT,
        "mutationCategories": ["CONFLICT_RESOLUTION"],
        "mutationSummary": "Behavior focus: CONFLICT_RESOLUTION.",
        "hypothesis": (
            "Preregistered hypothesis: CONFLICT_RESOLUTION improves the frozen "
            "Agent outcome score."
        ),
        "behaviorContractHash": HASH_A,
        "privateLineageHash": HASH_A,
        "privateStateArtifactHash": HASH_A,
        "createdAt": NOW,
    }


def candidate_publication(
    candidate_record: dict[str, object] | None = None,
) -> dict[str, object]:
    candidate_value = candidate_record or candidate()
    body: dict[str, object] = {
        "schemaVersion": "prompt_candidate_publication_v1",
        "candidateId": candidate_value["candidateId"],
        "candidateHash": canonical_hash(candidate_value),
        "promptSourceId": "private-prompts-primary",
        "candidatePromptCommit": "d" * 40,
    }
    return {**body, "publicationHash": canonical_hash(body)}


def promotion_policy(
    split_record: dict[str, object], *, minimum_paired_delta: float = 0.05
) -> dict[str, object]:
    return {
        "policyVersion": "prompt-promotion-test-v1",
        "minimumMatureSamples": 30,
        "minimumRepeatSeeds": 2,
        "minimumPairedDelta": minimum_paired_delta,
        "familyAlpha": 0.05,
        "bootstrapSamples": 99,
        "blockLength": 1,
        "tailQuantile": 0.25,
        "minimumTailDelta": 0.05,
        "maximumFailureRateIncrease": 0,
        "criticalValidationSampleIds": [
            split_record["validation"]["samples"][0]["sampleId"]
        ],
        "criticalHoldoutSampleIds": [
            split_record["holdout"]["samples"][0]["sampleId"]
        ],
        "minimumCriticalSampleDelta": 0,
    }


def family(
    split_record: dict[str, object],
    candidate_ids: list[str] | None = None,
    *,
    policy_record: dict[str, object] | None = None,
) -> dict[str, object]:
    ids = sorted(candidate_ids or ["candidate-1"])
    policy = policy_record or promotion_policy(split_record)
    body: dict[str, object] = {
        "schemaVersion": "prompt_candidate_family_v2",
        "target": TARGET,
        "championReleaseId": "champion-1",
        "championPromptSourceId": "private-prompts-primary",
        "championPromptCommit": COMMIT,
        "championPromptRefs": {
            "zh": "private://champion.zh",
            "en": "private://champion.en",
        },
        "championPromptHashes": {"zh": HASH_B, "en": HASH_A},
        "datasetSplitId": split_record["splitId"],
        "datasetSplitManifestHash": canonical_hash(split_record),
        "promotionPolicyVersion": policy["policyVersion"],
        "promotionPolicyConfigHash": canonical_hash(policy),
        "candidateIds": ids,
        "createdAt": NOW,
    }
    identity = {key: value for key, value in body.items() if key != "createdAt"}
    return {**body, "familyId": content_id("family", identity)}


def recanonicalize_family(value: dict[str, object]) -> dict[str, object]:
    result = json.loads(json.dumps(value))
    identity = {
        key: item
        for key, item in result.items()
        if key not in {"familyId", "createdAt"}
    }
    result["familyId"] = content_id("family", identity)
    return result


def aggregate_metrics(
    partition: str, candidate_score: float = 0.6, pair_count: int = 60
) -> dict[str, float | int]:
    prefix = partition.lower()
    champion_score = 0.5
    candidate_scores = [candidate_score] * pair_count
    champion_scores = [champion_score] * pair_count
    return {
        f"{prefix}_candidate_mean": ordered_mean(candidate_scores),
        f"{prefix}_champion_mean": ordered_mean(champion_scores),
        f"{prefix}_paired_delta": ordered_mean(
            [candidate - champion for candidate, champion in zip(candidate_scores, champion_scores)]
        ),
        f"{prefix}_pair_count": pair_count,
    }


def experiment(
    family_record: dict[str, object],
    candidate_record: dict[str, object],
    status: str = "PENDING",
    run_ids: list[str] | None = None,
    *,
    candidate_score: float = 0.6,
) -> dict[str, object]:
    holdout_open = status in {"HOLDOUT_RUNNING", "COMPLETE"}
    if status in {"PENDING", "VALIDATION_RUNNING"}:
        metrics: dict[str, float | int] = {}
    elif status in {"VALIDATION_COMPLETE", "HOLDOUT_RUNNING"}:
        metrics = aggregate_metrics("VALIDATION", candidate_score)
    else:
        metrics = {
            **aggregate_metrics("VALIDATION", candidate_score),
            **aggregate_metrics("HOLDOUT", candidate_score),
        }
    body: dict[str, object] = {
        "schemaVersion": "prompt_experiment_v2",
        "familyId": family_record["familyId"],
        "candidateId": candidate_record["candidateId"],
        "championId": "champion-1",
        "target": TARGET,
        "championPromptSourceId": family_record["championPromptSourceId"],
        "championPromptCommit": COMMIT,
        "championPromptRefs": family_record["championPromptRefs"],
        "championPromptHashes": family_record["championPromptHashes"],
        "candidatePromptRefs": candidate_record["promptRefs"],
        "candidatePromptHashes": candidate_record["promptHashes"],
        "candidatePromptSourceId": candidate_publication(candidate_record)[
            "promptSourceId"
        ],
        "candidatePromptCommit": candidate_publication(candidate_record)[
            "candidatePromptCommit"
        ],
        "candidatePublicationHash": candidate_publication(candidate_record)[
            "publicationHash"
        ],
        "datasetSplitId": family_record["datasetSplitId"],
        "datasetSplitManifestHash": family_record["datasetSplitManifestHash"],
        "promotionPolicyVersion": family_record["promotionPolicyVersion"],
        "promotionPolicyConfigHash": family_record["promotionPolicyConfigHash"],
        "modelConfigHash": HASH_A,
        "toolConfigHash": HASH_A,
        "componentCalibrationSnapshotHash": HASH_B,
        "darwinianUsageSnapshotHash": HASH_A,
        "executorAdapterHash": HASH_A,
        "evaluatorAdapterHash": HASH_B,
        "evaluationBinding": {
            "evaluationObject": CHINA_OUTCOME["evaluation_object"],
            "evaluationObjectSchemaVersion": CHINA_OUTCOME[
                "evaluation_object_schema_version"
            ],
            "primaryLabelId": CHINA_OUTCOME["primary_label_id"],
            "scoringContractVersion": CHINA_OUTCOME[
                "scoring_contract_version"
            ],
            "outcomeContractVersion": CHINA_OUTCOME[
                "outcome_contract_version"
            ],
        },
        "evaluatorVersion": CHINA_OUTCOME["scoring_contract_version"],
        "evaluatorConfigHash": HASH_B,
        "codeCommit": COMMIT,
        "executionBehaviorRelease": EXECUTION_RELEASE,
        "repeatSeeds": [1, 2],
        "runIds": sorted(run_ids or []),
        "metrics": metrics,
        "tailFailureCaseRefs": [],
        "status": status,
        "holdoutOpenedAt": "2025-04-01T01:00:00Z" if holdout_open else None,
        "createdAt": NOW,
        "completedAt": "2025-04-01T02:00:00Z" if status in {"COMPLETE", "FAILED"} else None,
    }
    identity = {
        key: value
        for key, value in body.items()
        if key
        not in {
            "runIds",
            "metrics",
            "tailFailureCaseRefs",
            "status",
            "holdoutOpenedAt",
            "createdAt",
            "completedAt",
        }
    }
    return {**body, "experimentId": content_id("experiment", identity)}


def recanonicalize_experiment(value: dict[str, object]) -> dict[str, object]:
    result = json.loads(json.dumps(value))
    identity = {
        key: item
        for key, item in result.items()
        if key
        not in {
            "experimentId",
            "runIds",
            "metrics",
            "tailFailureCaseRefs",
            "status",
            "holdoutOpenedAt",
            "createdAt",
            "completedAt",
        }
    }
    result["experimentId"] = content_id("experiment", identity)
    return result


def run_id(
    experiment_id: str, partition: str, side: str, sample_id: str, seed: int = 1
) -> str:
    return content_id(
        "run",
        {
            "experimentId": experiment_id,
            "partition": partition,
            "sampleId": sample_id,
            "seed": seed,
            "side": side,
        },
    )


def run_proposal(
    experiment_id: str,
    partition: str,
    side: str,
    sample_id: str,
    *,
    seed: int = 1,
    attempt: int = 1,
    lease_owner: str = "python-test-worker",
    attempt_failure_codes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": "prompt_experiment_run_v1",
        "runId": run_id(experiment_id, partition, side, sample_id, seed),
        "experimentId": experiment_id,
        "partition": partition,
        "side": side,
        "sampleId": sample_id,
        "seed": seed,
        "status": "RUNNING",
        "leaseOwner": lease_owner,
        "leaseExpiresAt": "2099-04-01T00:05:00Z",
        "attempt": attempt,
        "retryable": False,
        "attemptFailureCodes": list(attempt_failure_codes or []),
        "agentOutputRef": None,
        "metrics": {},
        "failureCaseRefs": [],
        "traceRef": None,
        "effectiveInputHash": None,
        "errorCode": None,
        "startedAt": NOW,
        "completedAt": None,
    }


def complete_run(claimed: dict[str, object], candidate_score: float = 0.6) -> dict[str, object]:
    return {
        **claimed,
        "status": "COMPLETE",
        "agentOutputRef": f"accepted://{claimed['runId']}",
        "metrics": {
            "normalized_score": candidate_score if claimed["side"] == "CANDIDATE" else 0.5
        },
        "effectiveInputHash": HASH_A,
        "completedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }


def failed_run(claimed: dict[str, object], *, retryable: bool) -> dict[str, object]:
    code = "transient_transport"
    return {
        **claimed,
        "status": "FAILED",
        "retryable": retryable,
        "attemptFailureCodes": [*claimed["attemptFailureCodes"], code],
        "errorCode": code,
        "completedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }


def store(
    tmp_path: Path,
    *,
    authorized: bool = True,
    minimum_paired_delta: float = 0.05,
) -> PromptOptimizerStore:
    policy_hash = canonical_hash(
        promotion_policy(split(), minimum_paired_delta=minimum_paired_delta)
    )
    result = PromptOptimizerStore(
        tmp_path / "scorecard.sqlite3",
        authorized_policy_hashes={policy_hash} if authorized else set(),
    )
    result.put_training_projection(training_projection())
    return result


def register(
    prompt_store: PromptOptimizerStore,
    *,
    candidate_ids: list[str] | None = None,
    minimum_paired_delta: float = 0.05,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    prompt_store.put_training_projection(training_projection())
    split_record = split()
    policy = promotion_policy(
        split_record, minimum_paired_delta=minimum_paired_delta
    )
    candidates = [candidate(value, split_record=split_record) for value in (candidate_ids or ["candidate-1"])]
    for candidate_record in candidates:
        prompt_store.put_candidate(candidate_record)
        prompt_store.put_candidate_publication(candidate_publication(candidate_record))
    prompt_store.put_split(split_record)
    family_record = family(
        split_record,
        [str(value["candidateId"]) for value in candidates],
        policy_record=policy,
    )
    prompt_store.put_family(family_record)
    return split_record, family_record, candidates


def test_training_projection_is_content_addressed_and_reopened(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    projection = training_projection()

    assert prompt_store.put_training_projection(projection) == projection
    assert prompt_store.get_training_projection(projection["projectionHash"]) == projection

    forged_hash = {**projection, "projectionHash": HASH_A}
    with pytest.raises(ValueError, match="projection_hash_mismatch"):
        prompt_store.put_training_projection(forged_hash)

    incomplete_body = {
        key: value for key, value in projection.items() if key != "projectionHash"
    }
    incomplete_body["directComponents"] = projection["directComponents"][:1]
    incomplete = {
        **incomplete_body,
        "projectionHash": canonical_hash(incomplete_body),
    }
    with pytest.raises(ValueError, match="component_roster_mismatch"):
        prompt_store.put_training_projection(incomplete)


def test_candidate_and_split_require_the_persisted_projection(tmp_path: Path) -> None:
    prompt_store = PromptOptimizerStore(tmp_path / "scorecard.sqlite3")
    split_record = split()
    candidate_record = candidate(split_record=split_record)

    with pytest.raises(ValueError, match="training_projection_not_found"):
        prompt_store.put_candidate(candidate_record)
    with pytest.raises(ValueError, match="training_projection_not_found"):
        prompt_store.put_split(split_record)

    projection = training_projection()
    prompt_store.put_training_projection(projection)
    assert prompt_store.put_candidate(candidate_record) == candidate_record
    assert prompt_store.put_split(split_record) == split_record


def test_split_rejects_persisted_projection_with_inconsistent_exclusions(
    tmp_path: Path,
) -> None:
    prompt_store = PromptOptimizerStore(tmp_path / "scorecard.sqlite3")
    projection = training_projection(
        projection_id="projection-china-exclusion-drift",
        dataset_snapshot_hash=HASH_B,
    )
    body = {key: value for key, value in projection.items() if key != "projectionHash"}
    body["excludedSampleIdsHash"] = HASH_A
    drifted_projection = {**body, "projectionHash": canonical_hash(body)}
    prompt_store.put_training_projection(drifted_projection)
    split_record = split(
        training_projection_hash=str(drifted_projection["projectionHash"])
    )

    with pytest.raises(ValueError, match="split_training_projection_mismatch"):
        prompt_store.put_split(split_record)


def test_candidate_split_and_family_reopen_projection_on_every_write(
    tmp_path: Path,
) -> None:
    prompt_store = store(tmp_path)
    split_record = split()
    candidate_record = candidate(split_record=split_record)
    family_record = family(split_record)
    prompt_store.put_candidate(candidate_record)
    prompt_store.put_split(split_record)
    with sqlite3.connect(prompt_store.db_path) as conn:
        conn.execute("DELETE FROM prompt_training_projections_v1")

    for write in (
        lambda: prompt_store.put_candidate(candidate_record),
        lambda: prompt_store.put_split(split_record),
        lambda: prompt_store.put_family(family_record),
    ):
        with pytest.raises(ValueError, match="training_projection_not_found"):
            write()


def test_candidate_publication_is_hash_bound_idempotent_and_one_to_one(
    tmp_path: Path,
) -> None:
    prompt_store = store(tmp_path)
    candidate_record = candidate()
    publication = candidate_publication(candidate_record)

    with pytest.raises(ValueError, match="publication_candidate_not_found"):
        prompt_store.put_candidate_publication(publication)

    prompt_store.put_candidate(candidate_record)
    assert prompt_store.put_candidate_publication(publication) == publication
    assert prompt_store.put_candidate_publication(publication) == publication
    assert prompt_store.get_candidate_publication("candidate-1") == publication

    changed_body = {
        **publication,
        "candidatePromptCommit": "e" * 40,
    }
    changed = {
        **changed_body,
        "publicationHash": canonical_hash(
            {key: value for key, value in changed_body.items() if key != "publicationHash"}
        ),
    }
    with pytest.raises(ValueError, match="prompt_optimizer_id_conflict:candidate-1"):
        prompt_store.put_candidate_publication(changed)


def test_candidate_publication_rejects_candidate_or_publication_hash_drift(
    tmp_path: Path,
) -> None:
    prompt_store = store(tmp_path)
    candidate_record = candidate()
    prompt_store.put_candidate(candidate_record)
    publication = candidate_publication(candidate_record)

    stale_candidate_body = {**publication, "candidateHash": HASH_A}
    stale_candidate = {
        **stale_candidate_body,
        "publicationHash": canonical_hash(
            {
                key: value
                for key, value in stale_candidate_body.items()
                if key != "publicationHash"
            }
        ),
    }
    with pytest.raises(ValueError, match="publication_candidate_hash_mismatch"):
        prompt_store.put_candidate_publication(stale_candidate)

    with pytest.raises(ValueError, match="publication_hash_mismatch"):
        prompt_store.put_candidate_publication(
            {**publication, "publicationHash": HASH_B}
        )


def test_experiment_requires_the_persisted_candidate_publication(
    tmp_path: Path,
) -> None:
    prompt_store = store(tmp_path)
    split_record = split()
    candidate_record = candidate(split_record=split_record)
    family_record = family(split_record)
    prompt_store.put_candidate(candidate_record)
    prompt_store.put_split(split_record)
    prompt_store.put_family(family_record)
    experiment_record = experiment(family_record, candidate_record)

    with pytest.raises(ValueError, match="candidate_publication_not_found"):
        prompt_store.put_experiment(experiment_record)

    prompt_store.put_candidate_publication(candidate_publication(candidate_record))
    drifted = recanonicalize_experiment(
        {**experiment_record, "candidatePromptCommit": "e" * 40}
    )
    with pytest.raises(ValueError, match="candidate_publication_mismatch"):
        prompt_store.put_experiment(drifted)


def validation_sample_id(split_record: dict[str, object]) -> str:
    return str(split_record["validation"]["samples"][0]["sampleId"])


def holdout_sample_id(split_record: dict[str, object]) -> str:
    return str(split_record["holdout"]["samples"][0]["sampleId"])


def complete_partition(
    prompt_store: PromptOptimizerStore,
    experiment_record: dict[str, object],
    partition: str,
    samples: list[dict[str, object]],
    *,
    candidate_score: float = 0.6,
    candidate_scores: list[float] | None = None,
) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    for sample_index, sample_record in enumerate(samples):
        score = (
            candidate_scores[sample_index]
            if candidate_scores is not None
            else candidate_score
        )
        for seed in (1, 2):
            for side in ("CHAMPION", "CANDIDATE"):
                claimed = prompt_store.claim_run(
                    run_proposal(
                        str(experiment_record["experimentId"]),
                        partition,
                        side,
                        str(sample_record["sampleId"]),
                        seed=seed,
                    ),
                    60_000,
                )
                assert claimed is not None
                completed = complete_run(claimed, score)
                runs.append(prompt_store.put_run(completed))
    return runs


def aggregate_metrics_from_runs(
    partition: str, runs: list[dict[str, object]]
) -> dict[str, float | int]:
    pairs: dict[tuple[str, int], dict[str, dict[str, object]]] = {}
    for run in runs:
        pairs.setdefault((str(run["sampleId"]), int(run["seed"])), {})[
            str(run["side"])
        ] = run
    champion_scores: list[float] = []
    candidate_scores: list[float] = []
    deltas: list[float] = []
    for key in sorted(
        pairs, key=lambda item: (canonical_string_sort_key(item[0]), item[1])
    ):
        pair = pairs[key]
        champion = float(pair["CHAMPION"]["metrics"]["normalized_score"])
        candidate_value = float(
            pair["CANDIDATE"]["metrics"]["normalized_score"]
        )
        champion_scores.append(champion)
        candidate_scores.append(candidate_value)
        deltas.append(candidate_value - champion)
    prefix = partition.lower()
    return {
        f"{prefix}_candidate_mean": ordered_mean(candidate_scores),
        f"{prefix}_champion_mean": ordered_mean(champion_scores),
        f"{prefix}_paired_delta": ordered_mean(deltas),
        f"{prefix}_pair_count": len(pairs),
    }


def advance_complete(
    prompt_store: PromptOptimizerStore,
    *,
    requested_holdout_opened_at: str = "2025-04-01T01:00:00Z",
    requested_completed_at: str = "2025-04-01T02:00:00Z",
) -> tuple[dict[str, object], list[dict[str, object]], dict[str, object]]:
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    running = {**pending, "status": "VALIDATION_RUNNING"}
    prompt_store.put_experiment(running)
    validation_runs = complete_partition(
        prompt_store, running, "VALIDATION", split_record["validation"]["samples"]
    )
    validation_ids = sorted(str(value["runId"]) for value in validation_runs)
    validation_complete = experiment(
        family_record, candidates[0], "VALIDATION_COMPLETE", validation_ids
    )
    validation_complete = prompt_store.put_experiment(validation_complete)
    holdout_running = experiment(
        family_record, candidates[0], "HOLDOUT_RUNNING", validation_ids
    )
    holdout_running["holdoutOpenedAt"] = requested_holdout_opened_at
    holdout_running = prompt_store.put_experiment(
        holdout_running, promotion_policy(split_record)
    )
    holdout_runs = complete_partition(
        prompt_store, holdout_running, "HOLDOUT", split_record["holdout"]["samples"]
    )
    all_runs = validation_runs + holdout_runs
    completed = experiment(
        family_record,
        candidates[0],
        "COMPLETE",
        [str(value["runId"]) for value in all_runs],
    )
    completed["holdoutOpenedAt"] = holdout_running["holdoutOpenedAt"]
    completed["completedAt"] = requested_completed_at
    completed = prompt_store.put_experiment(completed)
    return completed, all_runs, family_record


def test_experiment_evidence_round_trip_has_no_caller_written_decision(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    completed, _, family_record = advance_complete(prompt_store)
    assert prompt_store.get_experiment(str(completed["experimentId"])) == completed
    assert prompt_store.get_family(str(family_record["familyId"])) == family_record
    assert "status" not in family_record
    assert not hasattr(prompt_store, "put_decision")
    assert not hasattr(prompt_store, "get_decision")

    with sqlite3.connect(tmp_path / "scorecard.sqlite3") as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'prompt_%_v3'"
            )
        }
    assert {"prompt_dataset_splits_v3", "prompt_candidate_families_v3"} <= tables
    assert "prompt_promotion_decisions_v3" not in tables


def test_complete_experiment_cannot_be_inserted_without_runs(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    _, family_record, candidates = register(prompt_store)
    with pytest.raises(ValueError, match="initial_status_invalid"):
        prompt_store.put_experiment(experiment(family_record, candidates[0], "COMPLETE"))


@pytest.mark.parametrize(
    "invalid_status",
    ["VALIDATION_COMPLETE", "HOLDOUT_RUNNING", "COMPLETE"],
)
def test_pending_experiment_rejects_non_adjacent_transitions(
    tmp_path: Path,
    invalid_status: str,
) -> None:
    prompt_store = store(tmp_path)
    _, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)

    with pytest.raises(
        ValueError,
        match=f"transition_invalid:PENDING:{invalid_status}",
    ):
        prompt_store.put_experiment(
            experiment(family_record, candidates[0], invalid_status)
        )


def test_run_cannot_complete_without_a_persisted_claim(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    prompt_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
    unclaimed = run_proposal(
        str(pending["experimentId"]),
        "VALIDATION",
        "CHAMPION",
        validation_sample_id(split_record),
    )

    with pytest.raises(ValueError, match="run_must_be_claimed"):
        prompt_store.put_run(complete_run(unclaimed))


def test_atomic_run_claim_uses_database_clock_and_has_one_winner(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    running = {**pending, "status": "VALIDATION_RUNNING"}
    prompt_store.put_experiment(running)
    proposal = run_proposal(
        str(pending["experimentId"]),
        "VALIDATION",
        "CHAMPION",
        validation_sample_id(split_record),
    )
    proposal["startedAt"] = "1900-01-01T00:00:00Z"
    proposal["leaseExpiresAt"] = "2999-01-01T00:00:00Z"
    before = datetime.now(timezone.utc)
    claimed = prompt_store.claim_run(proposal, 60_000)
    after = datetime.now(timezone.utc)
    assert claimed is not None
    started = datetime.fromisoformat(str(claimed["startedAt"]).replace("Z", "+00:00"))
    expires = datetime.fromisoformat(str(claimed["leaseExpiresAt"]).replace("Z", "+00:00"))
    assert before - timedelta(seconds=1) <= started <= after
    assert 59 <= (expires - started).total_seconds() <= 61
    assert prompt_store.claim_run(proposal, 60_000) is None


def test_run_finish_and_reclaim_are_serialized_without_stale_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_store = store(tmp_path)
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    prompt_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
    proposal = run_proposal(
        str(pending["experimentId"]),
        "VALIDATION",
        "CHAMPION",
        validation_sample_id(split_record),
    )
    claimed = prompt_store.claim_run(proposal, 60_000)
    assert claimed is not None
    competing_store = PromptOptimizerStore(prompt_store.db_path)
    finisher_holds_lock = threading.Event()
    release_finisher = threading.Event()
    reclaimer_started = threading.Event()
    original_db_now = prompt_optimizer_store_module._db_now

    def controlled_db_now(conn: sqlite3.Connection) -> datetime:
        if threading.current_thread().name == "stale-finisher":
            finisher_holds_lock.set()
            if not release_finisher.wait(5):
                raise RuntimeError("test did not release stale finisher")
        if threading.current_thread().name == "reclaimer":
            return datetime(2100, 1, 1, tzinfo=timezone.utc)
        return original_db_now(conn)

    monkeypatch.setattr(prompt_optimizer_store_module, "_db_now", controlled_db_now)
    errors: list[BaseException] = []
    reclaim_results: list[dict[str, object] | None] = []

    def finish() -> None:
        try:
            prompt_store.put_run(complete_run(claimed))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def reclaim() -> None:
        reclaimer_started.set()
        try:
            reclaim_results.append(
                competing_store.claim_run(
                    run_proposal(
                        str(pending["experimentId"]),
                        "VALIDATION",
                        "CHAMPION",
                        validation_sample_id(split_record),
                        attempt=2,
                        lease_owner="reclaimer",
                    ),
                    60_000,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    finisher = threading.Thread(target=finish, name="stale-finisher")
    reclaimer = threading.Thread(target=reclaim, name="reclaimer")
    finisher.start()
    assert finisher_holds_lock.wait(5)
    reclaimer.start()
    assert reclaimer_started.wait(5)
    release_finisher.set()
    finisher.join(5)
    reclaimer.join(5)
    assert not finisher.is_alive() and not reclaimer.is_alive()
    assert errors == []
    assert reclaim_results == [None]
    final = prompt_store.list_runs(str(pending["experimentId"]))[0]
    assert final["status"] == "COMPLETE"
    assert final["attempt"] == 1


def test_experiment_transitions_are_serialized_without_lost_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_store = store(tmp_path)
    _, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    competing_store = PromptOptimizerStore(prompt_store.db_path)
    validator_holds_lock = threading.Event()
    release_validator = threading.Event()
    failure_started = threading.Event()
    original_closure = PromptOptimizerStore._assert_experiment_transition_closure

    def guarded_closure(
        self: PromptOptimizerStore,
        conn: sqlite3.Connection,
        current: dict[str, object],
        value: dict[str, object],
        family_record: dict[str, object],
        promotion_policy_record: dict[str, object] | None,
    ) -> None:
        original_closure(
            self,
            conn,
            current,
            value,
            family_record,
            promotion_policy_record,
        )
        if threading.current_thread().name == "validation-transition":
            validator_holds_lock.set()
            if not release_validator.wait(5):
                raise RuntimeError("test did not release validation transition")

    monkeypatch.setattr(
        PromptOptimizerStore,
        "_assert_experiment_transition_closure",
        guarded_closure,
    )
    errors: list[BaseException] = []

    def start_validation() -> None:
        try:
            prompt_store.put_experiment(
                {**pending, "status": "VALIDATION_RUNNING"}
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def fail_experiment() -> None:
        failure_started.set()
        try:
            competing_store.put_experiment(
                {
                    **pending,
                    "status": "FAILED",
                    "completedAt": "1900-01-01T00:00:00Z",
                }
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    validator = threading.Thread(
        target=start_validation, name="validation-transition"
    )
    failure = threading.Thread(target=fail_experiment, name="failure-transition")
    validator.start()
    assert validator_holds_lock.wait(5)
    failure.start()
    assert failure_started.wait(5)
    release_validator.set()
    validator.join(5)
    failure.join(5)
    assert not validator.is_alive() and not failure.is_alive()
    assert errors == []
    final = prompt_store.get_experiment(str(pending["experimentId"]))
    assert final is not None
    assert final["status"] == "FAILED"
    assert final["completedAt"] != "1900-01-01T00:00:00Z"


def test_store_owns_run_and_experiment_transition_timestamps(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    prompt_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
    sample_id = validation_sample_id(split_record)
    stored_runs: list[dict[str, object]] = []
    for side, caller_timestamp in (
        ("CHAMPION", "1900-01-01T00:00:00Z"),
        ("CANDIDATE", "2999-01-01T00:00:00Z"),
    ):
        claimed = prompt_store.claim_run(
            run_proposal(
                str(pending["experimentId"]),
                "VALIDATION",
                side,
                sample_id,
            ),
            60_000,
        )
        assert claimed is not None
        requested = {**complete_run(claimed), "completedAt": caller_timestamp}
        before = datetime.now(timezone.utc)
        stored = prompt_store.put_run(requested)
        after = datetime.now(timezone.utc)
        completed_at = datetime.fromisoformat(
            str(stored["completedAt"]).replace("Z", "+00:00")
        )
        started_at = datetime.fromisoformat(
            str(stored["startedAt"]).replace("Z", "+00:00")
        )
        assert started_at <= completed_at
        assert before - timedelta(seconds=1) <= completed_at <= after
        assert stored["completedAt"] != caller_timestamp
        stored_runs.append(stored)

    duplicate = {
        **stored_runs[0],
        "completedAt": "2999-01-01T00:00:00Z",
    }
    assert prompt_store.put_run(duplicate) == stored_runs[0]

    lifecycle_store = store(tmp_path / "experiment-lifecycle")
    completed, runs, _ = advance_complete(
        lifecycle_store,
        requested_holdout_opened_at="2999-01-01T00:00:00Z",
        requested_completed_at="1900-01-01T00:00:00Z",
    )
    holdout_opened_at = datetime.fromisoformat(
        str(completed["holdoutOpenedAt"]).replace("Z", "+00:00")
    )
    completed_at = datetime.fromisoformat(
        str(completed["completedAt"]).replace("Z", "+00:00")
    )
    run_completed_at = max(
        datetime.fromisoformat(str(run["completedAt"]).replace("Z", "+00:00"))
        for run in runs
    )
    assert holdout_opened_at <= completed_at
    assert run_completed_at <= completed_at
    assert completed["holdoutOpenedAt"] != "2999-01-01T00:00:00Z"
    assert completed["completedAt"] != "1900-01-01T00:00:00Z"


def test_expired_run_lease_is_reclaimed_and_stale_owner_cannot_finish(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    prompt_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
    first = prompt_store.claim_run(
        run_proposal(
            str(pending["experimentId"]),
            "VALIDATION",
            "CHAMPION",
            validation_sample_id(split_record),
        ),
        60_000,
    )
    assert first is not None
    expired = {**first, "leaseExpiresAt": "2000-01-01T00:00:00Z"}
    with sqlite3.connect(tmp_path / "scorecard.sqlite3") as conn:
        conn.execute(
            "UPDATE prompt_experiment_runs_v3 SET record_json = ? WHERE run_id = ?",
            (json.dumps(expired, sort_keys=True, separators=(",", ":")), first["runId"]),
        )
    with pytest.raises(ValueError, match="run_lease_expired"):
        prompt_store.put_run(complete_run(first))
    reclaimed = prompt_store.claim_run(
        run_proposal(
            str(pending["experimentId"]),
            "VALIDATION",
            "CHAMPION",
            validation_sample_id(split_record),
            attempt=2,
            lease_owner="python-test-worker-2",
        ),
        60_000,
    )
    assert reclaimed is not None
    assert reclaimed["attemptFailureCodes"] == ["prompt_experiment_lease_expired"]
    with pytest.raises(ValueError, match="lease_owner_mismatch"):
        prompt_store.put_run(complete_run(first))


def test_store_recomputes_authorized_validation_winner_with_jcs_policy_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_store = store(tmp_path, minimum_paired_delta=1e-7)
    split_record, family_record, candidates = register(
        prompt_store,
        candidate_ids=["candidate-1", "candidate-2"],
        minimum_paired_delta=1e-7,
    )
    validation_complete: list[dict[str, object]] = []
    score_series = (
        [0.3] * 8 + [1.0] * 22,
        [0.7] * 30,
    )
    for candidate_record, scores in zip(candidates, score_series):
        pending = experiment(family_record, candidate_record)
        prompt_store.put_experiment(pending)
        running = {**pending, "status": "VALIDATION_RUNNING"}
        prompt_store.put_experiment(running)
        runs = complete_partition(
            prompt_store,
            running,
            "VALIDATION",
            split_record["validation"]["samples"],
            candidate_scores=scores,
        )
        complete = experiment(
            family_record,
            candidate_record,
            "VALIDATION_COMPLETE",
            [str(value["runId"]) for value in runs],
        )
        complete["metrics"] = aggregate_metrics_from_runs("VALIDATION", runs)
        prompt_store.put_experiment(complete)
        validation_complete.append(complete)
    policy = promotion_policy(split_record, minimum_paired_delta=1e-7)
    assert "1e-7" in canonical_json(policy)
    loser = {
        **validation_complete[0],
        "status": "HOLDOUT_RUNNING",
        "holdoutOpenedAt": "2025-04-01T01:00:00Z",
    }
    with pytest.raises(ValueError, match="holdout_winner_required"):
        prompt_store.put_experiment(loser, policy)
    winner = {
        **validation_complete[1],
        "status": "HOLDOUT_RUNNING",
        "holdoutOpenedAt": "2025-04-01T01:00:00Z",
    }
    monkeypatch.delenv("MOSAIC_PROMPT_PROMOTION_POLICY_HASHES", raising=False)
    unauthorized_store = PromptOptimizerStore(prompt_store.db_path)
    assert unauthorized_store.authorized_policy_hashes == frozenset()
    with pytest.raises(ValueError, match="policy_not_authorized"):
        unauthorized_store.put_experiment(winner, policy)
    critical = policy["criticalValidationSampleIds"][0]
    padded_policy = {
        **policy,
        "criticalValidationSampleIds": [critical, f" {critical} "],
    }
    with pytest.raises(ValueError, match="policy_schema_invalid"):
        prompt_store.put_experiment(winner, padded_policy)
    stored_winner = prompt_store.put_experiment(winner, policy)
    assert stored_winner["experimentId"] == winner["experimentId"]
    assert stored_winner["status"] == "HOLDOUT_RUNNING"
    assert stored_winner["holdoutOpenedAt"] != winner["holdoutOpenedAt"]


def test_complete_experiment_rejects_a_second_holdout_consumer(
    tmp_path: Path,
) -> None:
    prompt_store = store(tmp_path)
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    running = {**pending, "status": "VALIDATION_RUNNING"}
    prompt_store.put_experiment(running)
    validation_runs = complete_partition(
        prompt_store,
        running,
        "VALIDATION",
        split_record["validation"]["samples"],
    )
    validation_ids = sorted(str(run["runId"]) for run in validation_runs)
    validation_complete = experiment(
        family_record,
        candidates[0],
        "VALIDATION_COMPLETE",
        validation_ids,
    )
    prompt_store.put_experiment(validation_complete)
    holdout_running = experiment(
        family_record,
        candidates[0],
        "HOLDOUT_RUNNING",
        validation_ids,
    )
    holdout_running = prompt_store.put_experiment(
        holdout_running,
        promotion_policy(split_record),
    )
    holdout_runs = complete_partition(
        prompt_store,
        holdout_running,
        "HOLDOUT",
        split_record["holdout"]["samples"],
    )
    conflicting_candidate = candidate(
        "candidate-conflicting-consumer",
        split_record=split_record,
    )
    prompt_store.put_candidate(conflicting_candidate)
    prompt_store.put_candidate_publication(
        candidate_publication(conflicting_candidate)
    )
    conflicting_experiment = experiment(
        family_record,
        conflicting_candidate,
        "HOLDOUT_RUNNING",
        validation_ids,
    )
    with sqlite3.connect(prompt_store.db_path) as conn:
        conn.execute(
            """
            INSERT INTO prompt_experiments_v3 (
                experiment_id, candidate_id, family_id, status,
                dataset_split_manifest_hash, model_config_hash, tool_config_hash,
                evaluator_version, evaluator_config_hash, code_commit,
                record_json, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                conflicting_experiment["experimentId"],
                conflicting_candidate["candidateId"],
                family_record["familyId"],
                conflicting_experiment["status"],
                conflicting_experiment["datasetSplitManifestHash"],
                conflicting_experiment["modelConfigHash"],
                conflicting_experiment["toolConfigHash"],
                conflicting_experiment["evaluatorVersion"],
                conflicting_experiment["evaluatorConfigHash"],
                conflicting_experiment["codeCommit"],
                canonical_json(conflicting_experiment),
                conflicting_experiment["createdAt"],
            ),
        )
    completed = experiment(
        family_record,
        candidates[0],
        "COMPLETE",
        [str(run["runId"]) for run in validation_runs + holdout_runs],
    )
    completed["holdoutOpenedAt"] = holdout_running["holdoutOpenedAt"]

    with pytest.raises(ValueError, match="holdout_consumer_conflict"):
        prompt_store.put_experiment(completed)


def test_validation_aggregate_is_recomputed_from_accepted_runs(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    running = {**pending, "status": "VALIDATION_RUNNING"}
    prompt_store.put_experiment(running)
    runs = complete_partition(
        prompt_store, running, "VALIDATION", split_record["validation"]["samples"]
    )
    completed = experiment(
        family_record,
        candidates[0],
        "VALIDATION_COMPLETE",
        [str(value["runId"]) for value in runs],
    )
    completed["metrics"] = {**completed["metrics"], "injected": 1.0}
    with pytest.raises(ValueError, match="validation_aggregate_mismatch"):
        prompt_store.put_experiment(completed)


def test_family_is_an_immutable_manifest_not_a_mutable_selection_record(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    _, family_record, _ = register(prompt_store)
    assert prompt_store.put_family(family_record) == family_record
    with pytest.raises(ValueError, match="Additional properties are not allowed"):
        prompt_store.put_family({**family_record, "selectedCandidateId": "candidate-1"})


def test_holdout_snapshot_cannot_be_reused_under_a_changed_training_split(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    register(prompt_store)
    changed_projection = training_projection(
        projection_id="projection-china-changed-split",
        dataset_snapshot_hash=HASH_B,
    )
    prompt_store.put_training_projection(changed_projection)
    changed_split = split(
        training_projection_hash=str(changed_projection["projectionHash"])
    )
    changed_candidate = candidate("candidate-2", split_record=changed_split)
    prompt_store.put_candidate(changed_candidate)
    prompt_store.put_split(changed_split)
    with pytest.raises(ValueError, match="holdout_already_registered"):
        prompt_store.put_family(family(changed_split, ["candidate-2"]))


def test_family_rejects_candidate_training_or_reserved_sample_drift(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    split_record = split()
    prompt_store.put_split(split_record)
    changed_projection = training_projection(
        projection_id="projection-china-family-drift",
        dataset_snapshot_hash=HASH_B,
    )
    prompt_store.put_training_projection(changed_projection)
    training_drift = {
        **candidate("candidate-training-drift", split_record=split_record),
        "trainingProjectionHash": changed_projection["projectionHash"],
    }
    prompt_store.put_candidate(training_drift)
    with pytest.raises(ValueError, match="training_split_mismatch"):
        prompt_store.put_family(family(split_record, ["candidate-training-drift"]))
    exclusion_drift = {
        **candidate("candidate-exclusion-drift", split_record=split_record),
        "excludedSampleIdsHash": HASH_A,
    }
    with pytest.raises(ValueError, match="candidate_training_projection_mismatch"):
        prompt_store.put_candidate(exclusion_drift)


def test_python_boundary_replays_split_experiment_and_run_semantics(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    overlapping = split()
    first = overlapping["validation"]["samples"][0]
    second = overlapping["validation"]["samples"][1]
    second["eventWindow"] = dict(first["eventWindow"])
    with pytest.raises(ValueError, match="sample_windows_overlap"):
        prompt_store.put_split(recanonicalize_split(overlapping))

    split_record = split()
    family_record = family(split_record)
    candidate_record = candidate(split_record=split_record)
    invalid_experiment = {
        **experiment(family_record, candidate_record, "COMPLETE"),
        "completedAt": None,
    }
    with pytest.raises(ValueError, match="completion_timestamp_invalid"):
        prompt_store.put_experiment(invalid_experiment)

    invalid_run = run_proposal(
        str(experiment(family_record, candidate_record)["experimentId"]),
        "VALIDATION",
        "CHAMPION",
        validation_sample_id(split_record),
    )
    invalid_run["retryable"] = True
    with pytest.raises(ValueError, match="retryable_state_invalid"):
        prompt_store.claim_run(invalid_run, 60_000)


def test_alias_ids_and_future_split_creation_are_rejected(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    split_record = split()
    aliased_partition = {**split_record["training"], "snapshotId": "training-alias"}
    with pytest.raises(ValueError, match="Additional properties are not allowed"):
        prompt_store.put_split({**split_record, "training": aliased_partition})
    with pytest.raises(ValueError, match="created_in_future"):
        prompt_store.put_split({**split_record, "createdAt": "2999-01-01T00:00:00Z"})

    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    prompt_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
    alias_run = run_proposal(
        str(pending["experimentId"]),
        "VALIDATION",
        "CHAMPION",
        validation_sample_id(split_record),
    )
    alias_run["runId"] = "run-alias"
    with pytest.raises(ValueError, match="run_id_mismatch"):
        prompt_store.claim_run(alias_run, 60_000)


def test_store_accepts_only_manifest_owned_agent_stages(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    manifest = json.loads(
        (
            Path(__file__).parents[1]
            / "registry/prompt_checks/runtime_agent_manifest_v5.json"
        ).read_text(encoding="utf-8")
    )
    accepted = 0
    for agent in manifest["agents"]:
        for stage in agent["stages"]:
            if agent["agent"] == "cio" and stage["stage"] == "cio_proposal":
                continue
            candidate_id = f"candidate-{agent['agent']}-{stage['stage']}"
            target = {
                "agentId": agent["agent"],
                "stage": stage["stage"],
                "cohort": "cohort_default",
            }
            projection = training_projection(target=target)
            prompt_store.put_training_projection(projection)
            record = {
                **candidate(candidate_id),
                "target": target,
                "trainingProjectionHash": projection["projectionHash"],
            }
            assert prompt_store.put_candidate(record) == record
            accepted += 1
    assert accepted == 25

    for candidate_id, target in (
        (
            "candidate-wrong-owner",
            {
                "agentId": "china",
                "stage": "cio_final",
                "cohort": "cohort_default",
            },
        ),
        (
            "candidate-cio-proposal",
            {
                "agentId": "cio",
                "stage": "cio_proposal",
                "cohort": "cohort_default",
            },
        ),
    ):
        with pytest.raises(ValueError, match="target_stage_invalid"):
            prompt_store.put_candidate(
                {**candidate(candidate_id), "target": target}
            )


def test_store_binds_evaluator_and_sibling_experiment_environment(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    _, family_record, candidates = register(
        prompt_store, candidate_ids=["candidate-1", "candidate-2"]
    )
    first = experiment(family_record, candidates[0])
    prompt_store.put_experiment(first)

    evaluator_drift = recanonicalize_experiment(
        {**experiment(family_record, candidates[1]), "evaluatorVersion": "wrong-v1"}
    )
    with pytest.raises(ValueError, match="evaluator_binding_mismatch"):
        prompt_store.put_experiment(evaluator_drift)

    binding = dict(first["evaluationBinding"])
    binding["primaryLabelId"] = "wrong-label"
    binding_drift = recanonicalize_experiment(
        {**experiment(family_record, candidates[1]), "evaluationBinding": binding}
    )
    with pytest.raises(ValueError, match="evaluator_binding_mismatch"):
        prompt_store.put_experiment(binding_drift)

    environment_drift = recanonicalize_experiment(
        {**experiment(family_record, candidates[1]), "modelConfigHash": HASH_B}
    )
    with pytest.raises(ValueError, match="family_environment_drift"):
        prompt_store.put_experiment(environment_drift)

    execution_release_drift = recanonicalize_experiment(
        {
            **experiment(family_record, candidates[1]),
            "executionBehaviorRelease": {
                "release_id": f"execution-behavior-release:{'b' * 64}",
                "release_hash": HASH_B,
                "archive_ref": (
                    "registry/prompt_checks/execution_behavior_releases/"
                    f"{'b' * 64}--{'b' * 64}.json"
                ),
            },
        }
    )
    with pytest.raises(ValueError, match="family_environment_drift"):
        prompt_store.put_experiment(execution_release_drift)


def test_store_rejects_noncanonical_family_order_and_unfrozen_run_coordinates(
    tmp_path: Path,
) -> None:
    prompt_store = store(tmp_path)
    split_record = split()
    candidates = [
        candidate(candidate_id, split_record=split_record)
        for candidate_id in ("candidate-Z", "candidate-a")
    ]
    for record in candidates:
        prompt_store.put_candidate(record)
        prompt_store.put_candidate_publication(candidate_publication(record))
    prompt_store.put_split(split_record)
    canonical_family = family(
        split_record, [str(record["candidateId"]) for record in candidates]
    )
    noncanonical_family = recanonicalize_family(
        {**canonical_family, "candidateIds": list(reversed(canonical_family["candidateIds"]))}
    )
    with pytest.raises(ValueError, match="candidate_ids_not_canonical"):
        prompt_store.put_family(noncanonical_family)
    prompt_store.put_family(canonical_family)

    pending = experiment(canonical_family, candidates[0])
    prompt_store.put_experiment(pending)
    prompt_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
    wrong_sample = run_proposal(
        str(pending["experimentId"]),
        "VALIDATION",
        "CHAMPION",
        holdout_sample_id(split_record),
    )
    with pytest.raises(ValueError, match="coordinates_not_frozen"):
        prompt_store.claim_run(wrong_sample, 60_000)
    wrong_seed = run_proposal(
        str(pending["experimentId"]),
        "VALIDATION",
        "CHAMPION",
        validation_sample_id(split_record),
        seed=999,
    )
    with pytest.raises(ValueError, match="coordinates_not_frozen"):
        prompt_store.claim_run(wrong_seed, 60_000)
    assert prompt_store.list_runs(str(pending["experimentId"])) == []


@pytest.mark.parametrize(
    "created_at",
    ["2025-04-01T00:00Z", "2025-04-01T00:00:00.000499Z"],
)
def test_store_rejects_noncanonical_authority_timestamps(
    tmp_path: Path, created_at: str
) -> None:
    prompt_store = store(tmp_path)
    with pytest.raises(
        ValueError,
        match="prompt_optimizer_(?:schema_invalid|timestamp_precision_invalid)",
    ):
        prompt_store.put_candidate({**candidate(), "createdAt": created_at})


@pytest.mark.parametrize(
    "created_at",
    [
        "2025-04-01T00:00:00Z",
        "2025-04-01T00:00:00.1Z",
        "2025-04-01T00:00:00.12Z",
        "2025-04-01T00:00:00.123Z",
    ],
)
def test_store_accepts_canonical_authority_timestamp_precisions(
    tmp_path: Path, created_at: str
) -> None:
    prompt_store = store(tmp_path)
    record = {**candidate(), "createdAt": created_at}

    assert prompt_store.put_candidate(record) == record


def test_retryable_failures_are_bounded_to_three_attempts(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    prompt_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
    sample_id = validation_sample_id(split_record)
    failure_codes: list[str] = []
    last_failed: dict[str, object] | None = None
    for attempt in (1, 2, 3):
        claimed = prompt_store.claim_run(
            run_proposal(
                str(pending["experimentId"]),
                "VALIDATION",
                "CHAMPION",
                sample_id,
                attempt=attempt,
                lease_owner=f"worker-{attempt}",
                attempt_failure_codes=failure_codes,
            ),
            60_000,
        )
        assert claimed is not None
        last_failed = failed_run(claimed, retryable=attempt < 3)
        prompt_store.put_run(last_failed)
        failure_codes = list(last_failed["attemptFailureCodes"])
    assert last_failed is not None and last_failed["retryable"] is False
    assert (
        prompt_store.claim_run(
            run_proposal(
                str(pending["experimentId"]),
                "VALIDATION",
                "CHAMPION",
                sample_id,
                attempt=3,
                lease_owner="worker-4",
                attempt_failure_codes=failure_codes,
            ),
            60_000,
        )
        is None
    )


def test_expired_third_attempt_is_terminalized_once(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    split_record, family_record, candidates = register(prompt_store)
    pending = experiment(family_record, candidates[0])
    prompt_store.put_experiment(pending)
    prompt_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
    sample_id = validation_sample_id(split_record)
    failure_codes: list[str] = []
    for attempt in (1, 2, 3):
        claimed = prompt_store.claim_run(
            run_proposal(
                str(pending["experimentId"]),
                "VALIDATION",
                "CHAMPION",
                sample_id,
                attempt=attempt,
                lease_owner=f"expired-worker-{attempt}",
                attempt_failure_codes=failure_codes,
            ),
            60_000,
        )
        assert claimed is not None
        expired = {**claimed, "leaseExpiresAt": "2000-01-01T00:00:00Z"}
        with sqlite3.connect(prompt_store.db_path) as conn:
            conn.execute(
                "UPDATE prompt_experiment_runs_v3 SET record_json = ? WHERE run_id = ?",
                (canonical_json(expired), expired["runId"]),
            )
        failure_codes = list(claimed["attemptFailureCodes"])

    assert (
        prompt_store.claim_run(
            run_proposal(
                str(pending["experimentId"]),
                "VALIDATION",
                "CHAMPION",
                sample_id,
                attempt=3,
                lease_owner="expired-worker-3",
                attempt_failure_codes=failure_codes,
            ),
            60_000,
        )
        is None
    )
    terminal = prompt_store.list_runs(str(pending["experimentId"]))[0]
    assert terminal["status"] == "FAILED"
    assert terminal["attempt"] == 3
    assert terminal["retryable"] is False
    assert terminal["errorCode"] == "prompt_experiment_lease_expired_max_attempts"
    assert terminal["attemptFailureCodes"] == [
        "prompt_experiment_lease_expired",
        "prompt_experiment_lease_expired",
        "prompt_experiment_lease_expired_max_attempts",
    ]


def test_v3_store_leaves_prior_v2_audit_tables_untouched(tmp_path: Path) -> None:
    db_path = tmp_path / "scorecard.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE prompt_experiments_v2 (experiment_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO prompt_experiments_v2 VALUES ('legacy-experiment')")
    PromptOptimizerStore(db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT experiment_id FROM prompt_experiments_v2").fetchone() == (
            "legacy-experiment",
        )
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'prompt_experiments_v3'"
        ).fetchone() == ("prompt_experiments_v3",)


def test_generated_schema_and_semantics_reject_private_or_free_form_text(tmp_path: Path) -> None:
    prompt_store = store(tmp_path)
    with pytest.raises(ValueError, match="Additional properties are not allowed"):
        prompt_store.put_candidate({**candidate(), "zh_prompt": "private prompt body"})
    with pytest.raises(ValueError, match="summary_not_safe_projection"):
        prompt_store.put_candidate(
            {**candidate(), "mutationSummary": "private evidence prose"}
        )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {
                "mutationCategories": [
                    "CONFLICT_RESOLUTION",
                    "CONFLICT_RESOLUTION",
                ]
            },
            "mutation_categories_not_canonical",
        ),
        ({"hypothesis": "free-form private hypothesis"}, "hypothesis_not_safe_projection"),
        ({"privateLineageHash": "not-a-sha256"}, "schema_invalid"),
        ({"privateStateArtifactHash": "sha256:short"}, "schema_invalid"),
        (
            {"promptHashes": {"zh": "sha256:" + "A" * 64, "en": HASH_B}},
            "schema_invalid",
        ),
    ],
    ids=[
        "duplicate_mutation_category",
        "free_form_hypothesis",
        "invalid_private_lineage_hash",
        "invalid_private_state_hash",
        "invalid_prompt_hash",
    ],
)
def test_candidate_rejects_invalid_mutation_or_hash_contracts(
    tmp_path: Path,
    changes: dict[str, object],
    reason: str,
) -> None:
    prompt_store = store(tmp_path)

    with pytest.raises(ValueError, match=reason):
        prompt_store.put_candidate({**candidate(), **changes})


def test_store_rejects_surrounding_whitespace_without_normalizing_ids_or_refs(
    tmp_path: Path,
) -> None:
    prompt_store = store(tmp_path)
    with pytest.raises(ValueError, match="schema_invalid|noncanonical_string"):
        prompt_store.put_candidate({**candidate(), "candidateId": " candidate-1 "})
    padded_ref = candidate()
    padded_ref["promptRefs"] = {
        **padded_ref["promptRefs"],
        "zh": " private://candidate-1.zh ",
    }
    with pytest.raises(ValueError, match="schema_invalid|noncanonical_string"):
        prompt_store.put_candidate(padded_ref)

    split_record, family_record, candidates = register(prompt_store)
    padded_family = recanonicalize_family(
        {**family_record, "championReleaseId": " champion-1 "}
    )
    with pytest.raises(ValueError, match="schema_invalid|noncanonical_string"):
        prompt_store.put_family(padded_family)

    padded_experiment = recanonicalize_experiment(
        {
            **experiment(family_record, candidates[0]),
            "championId": " champion-1 ",
        }
    )
    with pytest.raises(ValueError, match="schema_invalid|noncanonical_string"):
        prompt_store.put_experiment(padded_experiment)

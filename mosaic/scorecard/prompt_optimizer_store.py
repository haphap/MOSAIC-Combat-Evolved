"""Minimal persistence for Prompt Candidate experiments.

The TypeScript Zod contracts are the source of truth.  This module validates
against their generated JSON schemas and stores only public hashes, refs, and
metrics in the existing scorecard SQLite database.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from jsonschema import Draft7Validator, FormatChecker

from mosaic.scorecard.canonical_json import (
    canonical_hash as _canonical_hash,
    canonical_json as _canonical_json,
    canonical_string_sort_key as _canonical_string_sort_key,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.prompt_training_history import prompt_role_component_refs
from mosaic.scorecard.store import DEFAULT_DB_PATH


_SCHEMA_FILE_BY_VERSION = {
    "prompt_training_projection_v1": "prompt_training_projection_v1.schema.json",
    "prompt_training_projection_v2": "prompt_training_projection_v2.schema.json",
    "prompt_candidate_v1": "prompt_candidate_v1.schema.json",
    "prompt_candidate_publication_v1": "prompt_candidate_publication_v1.schema.json",
    "prompt_candidate_family_v1": "prompt_candidate_family_v1.schema.json",
    "prompt_candidate_family_v2": "prompt_candidate_family_v2.schema.json",
    "prompt_dataset_split_v1": "prompt_dataset_split_v1.schema.json",
    "prompt_experiment_v1": "prompt_experiment_v1.schema.json",
    "prompt_experiment_v2": "prompt_experiment_v2.schema.json",
    "prompt_experiment_run_v1": "prompt_experiment_run_v1.schema.json",
}

_DDL = """
CREATE TABLE IF NOT EXISTS prompt_training_projections_v1 (
    projection_hash TEXT PRIMARY KEY,
    projection_id TEXT NOT NULL UNIQUE,
    agent_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    cohort TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    persisted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_training_projections_v2 (
    projection_hash TEXT PRIMARY KEY,
    projection_id TEXT NOT NULL UNIQUE,
    agent_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    cohort TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    persisted_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS no_update_prompt_training_projections_v2
BEFORE UPDATE ON prompt_training_projections_v2
BEGIN SELECT RAISE(ABORT, 'append_only'); END;

CREATE TRIGGER IF NOT EXISTS no_delete_prompt_training_projections_v2
BEFORE DELETE ON prompt_training_projections_v2
BEGIN SELECT RAISE(ABORT, 'append_only'); END;

CREATE TABLE IF NOT EXISTS prompt_candidates_v3 (
    candidate_id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    cohort TEXT NOT NULL,
    zh_prompt_hash TEXT NOT NULL,
    en_prompt_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_candidate_publications_v1 (
    candidate_id TEXT PRIMARY KEY REFERENCES prompt_candidates_v3(candidate_id),
    candidate_hash TEXT NOT NULL,
    prompt_source_id TEXT NOT NULL,
    candidate_prompt_commit TEXT NOT NULL,
    publication_hash TEXT NOT NULL UNIQUE,
    record_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_dataset_splits_v3 (
    split_id TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL UNIQUE,
    agent_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    cohort TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_candidate_families_v3 (
    family_id TEXT PRIMARY KEY,
    champion_release_id TEXT NOT NULL,
    dataset_split_id TEXT NOT NULL REFERENCES prompt_dataset_splits_v3(split_id),
    dataset_split_manifest_hash TEXT NOT NULL,
    holdout_snapshot_hash TEXT NOT NULL UNIQUE,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_experiments_v3 (
    experiment_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES prompt_candidates_v3(candidate_id),
    family_id TEXT NOT NULL REFERENCES prompt_candidate_families_v3(family_id),
    status TEXT NOT NULL CHECK(status IN (
        'PENDING', 'VALIDATION_RUNNING', 'VALIDATION_COMPLETE',
        'HOLDOUT_RUNNING', 'COMPLETE', 'FAILED'
    )),
    dataset_split_manifest_hash TEXT NOT NULL,
    model_config_hash TEXT NOT NULL,
    tool_config_hash TEXT NOT NULL,
    evaluator_version TEXT NOT NULL,
    evaluator_config_hash TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS prompt_experiment_runs_v3 (
    run_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES prompt_experiments_v3(experiment_id),
    partition_name TEXT NOT NULL CHECK(partition_name IN ('VALIDATION', 'HOLDOUT')),
    side TEXT NOT NULL CHECK(side IN ('CHAMPION', 'CANDIDATE')),
    sample_id TEXT NOT NULL,
    seed INTEGER NOT NULL CHECK(seed >= 0),
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'RUNNING', 'COMPLETE', 'FAILED')),
    record_json TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(experiment_id, partition_name, side, sample_id, seed)
);

CREATE INDEX IF NOT EXISTS idx_prompt_candidates_v3_target
    ON prompt_candidates_v3(cohort, agent_id, stage, created_at);
CREATE INDEX IF NOT EXISTS idx_prompt_experiments_v3_candidate
    ON prompt_experiments_v3(candidate_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prompt_runs_v3_experiment
    ON prompt_experiment_runs_v3(experiment_id, partition_name, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_families_v3_split
    ON prompt_candidate_families_v3(dataset_split_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_experiments_v3_family_candidate
    ON prompt_experiments_v3(family_id, candidate_id);
"""

_MAX_RUN_ATTEMPTS = 3

_ECMASCRIPT_TRIM_CHARS = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)

_RUNTIME_AGENT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "registry"
    / "prompt_checks"
    / "runtime_agent_manifest_v5.json"
)


def _load_runtime_agent_stages() -> dict[str, frozenset[str]]:
    payload = json.loads(_RUNTIME_AGENT_MANIFEST_PATH.read_text(encoding="utf-8"))
    rows = payload.get("agents") if isinstance(payload, dict) else None
    if (
        payload.get("schema_version") != "runtime_agent_manifest_v5"
        or not isinstance(rows, list)
        or payload.get("runtime_agent_count") != len(rows)
    ):
        raise RuntimeError("prompt optimizer runtime Agent manifest is invalid")
    result: dict[str, frozenset[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("prompt optimizer runtime Agent row is invalid")
        agent_id = row.get("agent")
        stages = row.get("stages")
        if (
            not isinstance(agent_id, str)
            or not isinstance(stages, list)
            or agent_id in result
        ):
            raise RuntimeError("prompt optimizer runtime Agent binding is invalid")
        stage_ids = {
            stage.get("stage")
            for stage in stages
            if isinstance(stage, dict) and isinstance(stage.get("stage"), str)
        }
        if len(stage_ids) != len(stages) or not stage_ids:
            raise RuntimeError("prompt optimizer runtime stage binding is invalid")
        result[agent_id] = frozenset(stage_ids)
    if set(result) != set(OUTCOME_CONTRACTS):
        raise RuntimeError("prompt optimizer runtime and outcome rosters differ")
    return result


_RUNTIME_AGENT_STAGES_BY_AGENT = _load_runtime_agent_stages()
_PROMPT_OPTIMIZER_STAGES_BY_AGENT = {
    agent_id: frozenset(
        stage
        for stage in stages
        if not (agent_id == "cio" and stage == "cio_proposal")
    )
    for agent_id, stages in _RUNTIME_AGENT_STAGES_BY_AGENT.items()
}

_EXPERIMENT_TRANSITIONS = {
    "PENDING": {"VALIDATION_RUNNING", "FAILED"},
    "VALIDATION_RUNNING": {"VALIDATION_COMPLETE", "FAILED"},
    "VALIDATION_COMPLETE": {"HOLDOUT_RUNNING", "FAILED"},
    "HOLDOUT_RUNNING": {"COMPLETE", "FAILED"},
    "COMPLETE": set(),
    "FAILED": set(),
}

_RUN_TRANSITIONS = {
    "PENDING": {"RUNNING"},
    "RUNNING": {"COMPLETE", "FAILED"},
    "COMPLETE": set(),
    "FAILED": set(),
}


def _content_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_canonical_hash(value).removeprefix('sha256:')}"


def _assert_target_semantics(value: Mapping[str, Any]) -> None:
    target = value["target"]
    agent_id = str(target["agentId"])
    stage = str(target["stage"])
    if stage not in _PROMPT_OPTIMIZER_STAGES_BY_AGENT.get(agent_id, frozenset()):
        raise ValueError("prompt_optimizer_target_stage_invalid")


def _assert_training_projection_v2_semantics(value: Mapping[str, Any]) -> None:
    target = value.get("target")
    if not isinstance(target, Mapping) or set(target) != {
        "agentId",
        "stage",
        "cohort",
    }:
        raise ValueError("prompt_training_projection_v2_target_invalid")
    agent_id = target.get("agentId")
    stage = target.get("stage")
    cohort = target.get("cohort")
    if (
        not isinstance(agent_id, str)
        or not isinstance(stage, str)
        or not isinstance(cohort, str)
        or not cohort
        or stage not in _RUNTIME_AGENT_STAGES_BY_AGENT.get(agent_id, frozenset())
    ):
        raise ValueError("prompt_training_projection_v2_target_invalid")
    body = {key: item for key, item in value.items() if key != "projectionHash"}
    if value.get("projectionHash") != _canonical_hash(body):
        raise ValueError("prompt_training_projection_v2_hash_mismatch")
    roster_refs = value.get("productionVariantRosterRevisions")
    if not isinstance(roster_refs, list):
        raise ValueError("prompt_training_projection_v2_roster_refs_invalid")
    roster_ids = [
        ref.get("revisionId") if isinstance(ref, Mapping) else None
        for ref in roster_refs
    ]
    if roster_ids != sorted(set(roster_ids)):
        raise ValueError("prompt_training_projection_v2_roster_refs_invalid")
    if value.get("productionVariantRosterRevisionSetHash") != _canonical_hash(
        roster_refs
    ):
        raise ValueError("prompt_training_projection_v2_roster_hash_mismatch")


def _experiment_family_environment(value: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "target",
        "championId",
        "championPromptSourceId",
        "championPromptCommit",
        "championPromptRefs",
        "championPromptHashes",
        "datasetSplitId",
        "datasetSplitManifestHash",
        "promotionPolicyVersion",
        "promotionPolicyConfigHash",
        "modelConfigHash",
        "toolConfigHash",
        "componentCalibrationSnapshotHash",
        "darwinianUsageSnapshotHash",
        "executorAdapterHash",
        "evaluatorAdapterHash",
        "evaluationBinding",
        "evaluatorVersion",
        "evaluatorConfigHash",
        "codeCommit",
        "executionBehaviorRelease",
        "repeatSeeds",
    )
    return {key: value[key] for key in keys}


def _without_keys(value: Mapping[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in keys}


def _sample_id(value: Mapping[str, Any]) -> str:
    return _content_id(
        "sample",
        {
            "eventWindow": value["eventWindow"],
            "inputHash": value["inputHash"],
            "maturedAt": value["maturedAt"],
            "outcomeHash": value["outcomeHash"],
        },
    )


def _assert_split_semantics(value: Mapping[str, Any]) -> None:
    seen: set[str] = set()
    created_at = _instant(str(value["createdAt"]))
    for partition_name in ("training", "validation", "holdout"):
        partition = value[partition_name]
        window_start = _instant(str(partition["windowStartAt"]))
        window_end = _instant(str(partition["windowEndAt"]))
        if window_start > window_end:
            raise ValueError("prompt_dataset_partition_window_invalid")
        windows: list[tuple[datetime, datetime]] = []
        for sample in partition["samples"]:
            if sample["sampleId"] != _sample_id(sample):
                raise ValueError("prompt_dataset_sample_id_mismatch")
            sample_id = str(sample["sampleId"])
            if sample_id in seen:
                raise ValueError("prompt_dataset_sample_partition_overlap")
            seen.add(sample_id)
            event_start = _instant(str(sample["eventWindow"]["startAt"]))
            event_end = _instant(str(sample["eventWindow"]["endAt"]))
            matured_at = _instant(str(sample["maturedAt"]))
            if event_start > event_end:
                raise ValueError("prompt_dataset_sample_window_invalid")
            if event_start < window_start or event_end > window_end:
                raise ValueError("prompt_dataset_sample_outside_partition")
            if matured_at < event_end:
                raise ValueError("prompt_dataset_sample_matured_before_window_end")
            if matured_at > created_at:
                raise ValueError("prompt_dataset_split_contains_immature_outcome")
            windows.append((event_start, event_end))
        windows.sort()
        if any(current[0] < previous[1] for previous, current in zip(windows, windows[1:])):
            raise ValueError("prompt_dataset_sample_windows_overlap")
        expected_hash = _canonical_hash(
            sorted(
                (sample["sampleId"] for sample in partition["samples"]),
                key=_canonical_string_sort_key,
            )
        )
        if partition["snapshotHash"] != expected_hash:
            raise ValueError("prompt_dataset_partition_snapshot_hash_mismatch")
    training = value["training"]
    validation = value["validation"]
    holdout = value["holdout"]
    cutoff_at = _instant(str(value["cutoffAt"]))
    if _instant(str(training["windowEndAt"])) != cutoff_at:
        raise ValueError("prompt_dataset_split_cutoff_mismatch")
    if (
        _instant(str(training["windowEndAt"]))
        >= _instant(str(validation["windowStartAt"]))
        or _instant(str(validation["windowEndAt"]))
        >= _instant(str(holdout["windowStartAt"]))
    ):
        raise ValueError("prompt_dataset_split_partitions_not_strictly_ordered")
    expected_id = _content_id(
        "split", _without_keys(value, {"splitId", "createdAt"})
    )
    if value["splitId"] != expected_id:
        raise ValueError("prompt_dataset_split_id_mismatch")
    if cutoff_at > created_at:
        raise ValueError("prompt_dataset_split_created_before_cutoff")


def _assert_family_semantics(value: Mapping[str, Any]) -> None:
    expected_id = _content_id(
        "family",
        _without_keys(value, {"familyId", "createdAt"}),
    )
    if value["familyId"] != expected_id:
        raise ValueError("prompt_candidate_family_id_mismatch")
    candidate_ids = list(value["candidateIds"])
    if candidate_ids != sorted(
        set(candidate_ids), key=_canonical_string_sort_key
    ):
        raise ValueError("prompt_candidate_family_candidate_ids_not_canonical")


def _assert_experiment_semantics(value: Mapping[str, Any]) -> None:
    expected_id = _content_id(
        "experiment",
        _without_keys(
            value,
            {
                "experimentId",
                "runIds",
                "metrics",
                "tailFailureCaseRefs",
                "status",
                "holdoutOpenedAt",
                "createdAt",
                "completedAt",
            },
        ),
    )
    if value["experimentId"] != expected_id:
        raise ValueError("prompt_experiment_id_mismatch")
    if len(set(value["repeatSeeds"])) != len(value["repeatSeeds"]):
        raise ValueError("prompt_experiment_repeat_seeds_not_unique")
    holdout_open = value["status"] in {"HOLDOUT_RUNNING", "COMPLETE"}
    holdout_closed = value["status"] in {
        "PENDING",
        "VALIDATION_RUNNING",
        "VALIDATION_COMPLETE",
    }
    if (holdout_open and value["holdoutOpenedAt"] is None) or (
        holdout_closed and value["holdoutOpenedAt"] is not None
    ):
        raise ValueError("prompt_experiment_holdout_timestamp_invalid")
    terminal = value["status"] in {"COMPLETE", "FAILED"}
    if terminal != (value["completedAt"] is not None):
        raise ValueError("prompt_experiment_completion_timestamp_invalid")
    execution_release = value["executionBehaviorRelease"]
    expected_archive_ref = (
        "registry/prompt_checks/execution_behavior_releases/"
        f"{str(execution_release['release_id']).removeprefix('execution-behavior-release:')}--"
        f"{str(execution_release['release_hash']).removeprefix('sha256:')}.json"
    )
    if execution_release["archive_ref"] != expected_archive_ref:
        raise ValueError("prompt_experiment_execution_behavior_binding_mismatch")


def _assert_experiment_evaluator_binding(
    value: Mapping[str, Any], split: Mapping[str, Any]
) -> None:
    agent_id = str(value["target"]["agentId"])
    contract = OUTCOME_CONTRACTS.get(agent_id)
    if contract is None:
        raise ValueError("prompt_experiment_outcome_contract_missing")
    expected_binding = {
        "evaluationObject": contract["evaluation_object"],
        "evaluationObjectSchemaVersion": contract[
            "evaluation_object_schema_version"
        ],
        "primaryLabelId": contract["primary_label_id"],
        "scoringContractVersion": contract["scoring_contract_version"],
        "outcomeContractVersion": contract["outcome_contract_version"],
    }
    if (
        split["target"] != value["target"]
        or split["evaluatorVersion"] != contract["scoring_contract_version"]
        or value["evaluatorVersion"] != contract["scoring_contract_version"]
        or value["evaluationBinding"] != expected_binding
    ):
        raise ValueError("prompt_experiment_evaluator_binding_mismatch")


def _run_id(value: Mapping[str, Any]) -> str:
    return _content_id(
        "run",
        {
            "experimentId": value["experimentId"],
            "partition": value["partition"],
            "sampleId": value["sampleId"],
            "seed": value["seed"],
            "side": value["side"],
        },
    )


def _assert_run_semantics(value: Mapping[str, Any]) -> None:
    if value["runId"] != _run_id(value):
        raise ValueError("prompt_experiment_run_id_mismatch")
    status = str(value["status"])
    if status == "PENDING" and (
        value["startedAt"] is not None
        or value["completedAt"] is not None
        or value["leaseOwner"] is not None
        or value["leaseExpiresAt"] is not None
        or int(value["attempt"]) != 0
        or bool(value["retryable"])
    ):
        raise ValueError("prompt_experiment_pending_run_has_execution_state")
    if len(value["attemptFailureCodes"]) > int(value["attempt"]):
        raise ValueError("prompt_experiment_run_failure_history_invalid")
    if value["retryable"] and status != "FAILED":
        raise ValueError("prompt_experiment_run_retryable_state_invalid")
    if status != "PENDING" and (
        value["startedAt"] is None
        or value["leaseOwner"] is None
        or value["leaseExpiresAt"] is None
        or int(value["attempt"]) < 1
    ):
        raise ValueError("prompt_experiment_started_run_lease_missing")
    if status == "RUNNING" and (
        value["completedAt"] is not None
        or _instant(str(value["leaseExpiresAt"]))
        <= _instant(str(value["startedAt"]))
    ):
        raise ValueError("prompt_experiment_running_run_lease_invalid")
    if status == "COMPLETE":
        normalized_score = value["metrics"].get("normalized_score")
        if (
            value["completedAt"] is None
            or value["agentOutputRef"] is None
            or value["effectiveInputHash"] is None
            or isinstance(normalized_score, bool)
            or not isinstance(normalized_score, (int, float))
            or not math.isfinite(normalized_score)
            or not -1 <= normalized_score <= 1
            or value["errorCode"] is not None
            or value["retryable"]
        ):
            raise ValueError("prompt_experiment_complete_run_evidence_invalid")
    if status == "FAILED" and (
        value["completedAt"] is None
        or value["errorCode"] is None
        or not value["attemptFailureCodes"]
        or value["attemptFailureCodes"][-1] != value["errorCode"]
        or (value["retryable"] and int(value["attempt"]) >= _MAX_RUN_ATTEMPTS)
    ):
        raise ValueError("prompt_experiment_failed_run_evidence_invalid")


def _instant(value: str) -> datetime:
    match = re.search(
        r"T\d{2}:\d{2}:\d{2}(?:\.(?P<fraction>\d+))?"
        r"(?:Z|[+-]\d{2}:\d{2})$",
        value,
    )
    if match is None or len(match.group("fraction") or "") > 3:
        raise ValueError("prompt_optimizer_timestamp_precision_invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("prompt_optimizer_timestamp_timezone_required")
    return parsed


def _db_now(conn: sqlite3.Connection) -> datetime:
    row = conn.execute(
        "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now') AS db_now"
    ).fetchone()
    if row is None:
        raise RuntimeError("prompt_optimizer_database_clock_unavailable")
    return _instant(str(row["db_now"]))


def _format_instant(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _partition_aggregate(
    conn: sqlite3.Connection, experiment_id: str, partition: str
) -> tuple[dict[str, float | int], list[str]]:
    rows = conn.execute(
        """
        SELECT record_json FROM prompt_experiment_runs_v3
        WHERE experiment_id = ? AND partition_name = ?
        ORDER BY sample_id, seed, side
        """,
        (experiment_id, partition),
    ).fetchall()
    pairs: dict[tuple[str, int], dict[str, Mapping[str, Any]]] = {}
    failure_refs: set[str] = set()
    for row in rows:
        run = json.loads(str(row["record_json"]))
        if run["status"] != "COMPLETE":
            raise ValueError(
                f"prompt_experiment_{partition.lower()}_aggregate_incomplete"
            )
        key = (str(run["sampleId"]), int(run["seed"]))
        side = str(run["side"])
        pair = pairs.setdefault(key, {})
        if side in pair:
            raise ValueError("prompt_experiment_aggregate_duplicate_pair_side")
        pair[side] = run
        failure_refs.update(str(value) for value in run["failureCaseRefs"])
    if not pairs:
        raise ValueError(f"prompt_experiment_{partition.lower()}_aggregate_empty")
    champion_scores: list[float] = []
    candidate_scores: list[float] = []
    deltas: list[float] = []
    for key in sorted(
        pairs, key=lambda item: (_canonical_string_sort_key(item[0]), item[1])
    ):
        pair = pairs[key]
        if set(pair) != {"CHAMPION", "CANDIDATE"}:
            raise ValueError("prompt_experiment_aggregate_pair_incomplete")
        champion = float(pair["CHAMPION"]["metrics"]["normalized_score"])
        candidate = float(pair["CANDIDATE"]["metrics"]["normalized_score"])
        champion_scores.append(champion)
        candidate_scores.append(candidate)
        deltas.append(candidate - champion)
    prefix = partition.lower()
    return (
        {
            f"{prefix}_candidate_mean": _mean(candidate_scores),
            f"{prefix}_champion_mean": _mean(champion_scores),
            f"{prefix}_paired_delta": _mean(deltas),
            f"{prefix}_pair_count": len(pairs),
        },
        sorted(failure_refs, key=_canonical_string_sort_key),
    )


def _validated_promotion_policy(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        raise ValueError("prompt_experiment_holdout_policy_required")
    required = {
        "policyVersion",
        "minimumMatureSamples",
        "minimumRepeatSeeds",
        "minimumPairedDelta",
        "familyAlpha",
        "bootstrapSamples",
        "blockLength",
        "tailQuantile",
        "minimumTailDelta",
        "maximumFailureRateIncrease",
        "criticalValidationSampleIds",
        "criticalHoldoutSampleIds",
        "minimumCriticalSampleDelta",
    }
    if set(value) != required:
        raise ValueError("prompt_experiment_holdout_policy_schema_invalid")
    policy = dict(value)
    if (
        not isinstance(policy["policyVersion"], str)
        or not policy["policyVersion"]
        or policy["policyVersion"]
        != policy["policyVersion"].strip(_ECMASCRIPT_TRIM_CHARS)
        or len(policy["policyVersion"]) > 256
    ):
        raise ValueError("prompt_experiment_holdout_policy_schema_invalid")
    integer_limits = {
        "minimumMatureSamples": 30,
        "minimumRepeatSeeds": 2,
        "bootstrapSamples": 99,
        "blockLength": 1,
    }
    for key, minimum in integer_limits.items():
        item = policy[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < minimum:
            raise ValueError("prompt_experiment_holdout_policy_schema_invalid")
    for key in (
        "minimumPairedDelta",
        "familyAlpha",
        "tailQuantile",
        "minimumTailDelta",
        "maximumFailureRateIncrease",
        "minimumCriticalSampleDelta",
    ):
        item = policy[key]
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
        ):
            raise ValueError("prompt_experiment_holdout_policy_schema_invalid")
    if not 0 < policy["familyAlpha"] <= 0.5 or not 0 < policy["tailQuantile"] <= 0.5:
        raise ValueError("prompt_experiment_holdout_policy_schema_invalid")
    if policy["maximumFailureRateIncrease"] < 0:
        raise ValueError("prompt_experiment_holdout_policy_schema_invalid")
    for key in ("criticalValidationSampleIds", "criticalHoldoutSampleIds"):
        items = policy[key]
        if (
            not isinstance(items, list)
            or any(
                not isinstance(item, str)
                or not item
                or item != item.strip(_ECMASCRIPT_TRIM_CHARS)
                or len(item) > 256
                for item in items
            )
        ):
            raise ValueError("prompt_experiment_holdout_policy_schema_invalid")
        if len(set(items)) != len(items):
            raise ValueError("prompt_experiment_holdout_policy_schema_invalid")
    return policy


def _mulberry32(seed: int) -> Callable[[], float]:
    state = seed & 0xFFFFFFFF

    def random() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        value = state
        value = ((value ^ (value >> 15)) * (value | 1)) & 0xFFFFFFFF
        value ^= (
            value
            + (((value ^ (value >> 7)) * (value | 61)) & 0xFFFFFFFF)
        ) & 0xFFFFFFFF
        return ((value ^ (value >> 14)) & 0xFFFFFFFF) / 4_294_967_296

    return random


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("prompt_promotion_empty_metric_series")
    total = 0.0
    for value in values:
        total += value
    return total / len(values)


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("prompt_promotion_quantile_empty")
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _block_bootstrap(
    deltas: list[float], *, samples: int, block_length: int, alpha: float, seed: str
) -> tuple[float, float, float]:
    seed_value = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    random = _mulberry32(seed_value)
    means: list[float] = []
    for _ in range(samples):
        total = 0.0
        count = 0
        while count < len(deltas):
            start = math.floor(random() * len(deltas))
            for offset in range(block_length):
                if count >= len(deltas):
                    break
                total += deltas[(start + offset) % len(deltas)]
                count += 1
        means.append(total / len(deltas))
    means.sort()
    lower = _quantile(means, alpha)
    upper = _quantile(means, 1 - alpha)
    p_value = (sum(value <= 0 for value in means) + 1) / (len(means) + 1)
    return lower, upper, p_value


def _evaluate_promotion_series(
    *,
    deltas: list[float],
    champion_failures: list[bool],
    candidate_failures: list[bool],
    critical_deltas: list[float],
    repeat_seed_count: int,
    family_candidate_count: int,
    policy: Mapping[str, Any],
    seed: str,
) -> dict[str, Any]:
    """Evaluate the pure statistical gate shared by persistence and parity tests."""
    if (
        not deltas
        or not champion_failures
        or len(champion_failures) != len(candidate_failures)
        or family_candidate_count < 1
    ):
        raise ValueError("prompt_promotion_series_shape_invalid")
    adjusted_alpha = float(policy["familyAlpha"]) / family_candidate_count
    confidence_lower, confidence_upper, bootstrap_p_value = _block_bootstrap(
        deltas,
        samples=int(policy["bootstrapSamples"]),
        block_length=int(policy["blockLength"]),
        alpha=adjusted_alpha,
        seed=seed,
    )
    tail_count = max(1, math.ceil(len(deltas) * float(policy["tailQuantile"])))
    tail_delta = _mean(sorted(deltas)[:tail_count])
    champion_failure_rate = _mean([float(failed) for failed in champion_failures])
    candidate_failure_rate = _mean([float(failed) for failed in candidate_failures])
    critical_minimum = min(critical_deltas) if critical_deltas else 0
    paired_delta = _mean(deltas)
    reasons: list[str] = []
    if len(deltas) < int(policy["minimumMatureSamples"]):
        reasons.append("sample_count")
    if repeat_seed_count < int(policy["minimumRepeatSeeds"]):
        reasons.append("repeat_seed_count")
    if paired_delta < float(policy["minimumPairedDelta"]):
        reasons.append("paired_delta")
    if confidence_lower < float(policy["minimumPairedDelta"]):
        reasons.append("confidence_lower")
    if bootstrap_p_value > adjusted_alpha:
        reasons.append("multiple_comparison")
    if tail_delta < float(policy["minimumTailDelta"]):
        reasons.append("tail_regression")
    if (
        candidate_failure_rate - champion_failure_rate
        > float(policy["maximumFailureRateIncrease"])
    ):
        reasons.append("failure_rate_regression")
    if critical_deltas and critical_minimum < float(
        policy["minimumCriticalSampleDelta"]
    ):
        reasons.append("critical_suite_regression")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "metrics": {
            "sampleCount": len(deltas),
            "repeatSeedCount": repeat_seed_count,
            "pairedDelta": paired_delta,
            "confidenceLower": confidence_lower,
            "confidenceUpper": confidence_upper,
            "bootstrapPValue": bootstrap_p_value,
            "adjustedAlpha": adjusted_alpha,
            "tailDelta": tail_delta,
            "championFailureRate": champion_failure_rate,
            "candidateFailureRate": candidate_failure_rate,
            "criticalMinimum": critical_minimum,
        },
    }


def _validation_gate_eligible(
    conn: sqlite3.Connection,
    experiment: Mapping[str, Any],
    family: Mapping[str, Any],
    split: Mapping[str, Any],
    policy: Mapping[str, Any],
    policy_hash: str,
) -> bool:
    rows = conn.execute(
        """
        SELECT record_json FROM prompt_experiment_runs_v3
        WHERE experiment_id = ? AND partition_name = 'VALIDATION'
        ORDER BY sample_id, seed, side
        """,
        (experiment["experimentId"],),
    ).fetchall()
    runs = [json.loads(str(row["record_json"])) for row in rows]
    if any(run["status"] != "COMPLETE" for run in runs):
        raise ValueError("prompt_experiment_family_validation_run_incomplete")
    samples = split["validation"]["samples"]
    expected_samples = {str(sample["sampleId"]) for sample in samples}
    expected_count = len(expected_samples) * len(experiment["repeatSeeds"]) * 2
    if len(runs) != expected_count:
        raise ValueError("prompt_experiment_family_validation_run_count_mismatch")
    pairs: dict[tuple[str, int], dict[str, Mapping[str, Any]]] = {}
    for run in runs:
        if (
            run["sampleId"] not in expected_samples
            or run["seed"] not in experiment["repeatSeeds"]
        ):
            raise ValueError("prompt_experiment_family_validation_run_identity_mismatch")
        pair = pairs.setdefault((str(run["sampleId"]), int(run["seed"])), {})
        if run["side"] in pair:
            raise ValueError("prompt_experiment_family_validation_pair_duplicate")
        pair[str(run["side"])] = run
    grouped: dict[str, list[float]] = {}
    champion_failures: list[float] = []
    candidate_failures: list[float] = []
    failure_metrics = ("schema_failure", "contract_failure", "tool_failure")
    for (sample_id, _seed), pair in sorted(
        pairs.items(),
        key=lambda item: (
            _canonical_string_sort_key(item[0][0]),
            item[0][1],
        ),
    ):
        if set(pair) != {"CHAMPION", "CANDIDATE"}:
            raise ValueError("prompt_experiment_family_validation_pair_incomplete")
        champion = pair["CHAMPION"]
        candidate = pair["CANDIDATE"]
        champion_score = champion["metrics"].get("normalized_score")
        candidate_score = candidate["metrics"].get("normalized_score")
        if champion_score is None or candidate_score is None:
            raise ValueError("prompt_experiment_family_validation_score_missing")
        grouped.setdefault(sample_id, []).append(
            float(candidate_score) - float(champion_score)
        )
        champion_failures.append(
            float(any(float(champion["metrics"].get(key, 0)) > 0 for key in failure_metrics))
        )
        candidate_failures.append(
            float(any(float(candidate["metrics"].get(key, 0)) > 0 for key in failure_metrics))
        )
    ordered_samples = sorted(
        samples,
        key=lambda sample: (
            _instant(str(sample["eventWindow"]["startAt"])),
            _instant(str(sample["eventWindow"]["endAt"])),
        ),
    )
    sample_deltas = [
        (str(sample["sampleId"]), _mean(grouped[str(sample["sampleId"])]))
        for sample in ordered_samples
    ]
    deltas = [value for _, value in sample_deltas]
    critical_by_id = dict(sample_deltas)
    try:
        critical_deltas = [
            critical_by_id[sample_id]
            for sample_id in policy["criticalValidationSampleIds"]
        ]
    except KeyError as exc:
        raise ValueError("prompt_experiment_holdout_policy_critical_sample_missing") from exc
    evidence = _evaluate_promotion_series(
        deltas=deltas,
        champion_failures=[bool(value) for value in champion_failures],
        candidate_failures=[bool(value) for value in candidate_failures],
        critical_deltas=critical_deltas,
        repeat_seed_count=len(experiment["repeatSeeds"]),
        family_candidate_count=len(family["candidateIds"]),
        policy=policy,
        seed=f"{experiment['experimentId']}:VALIDATION:{policy_hash}",
    )
    return bool(evidence["eligible"])


def _assert_candidate_semantics(value: Mapping[str, Any]) -> None:
    categories = value["mutationCategories"]
    if categories != sorted(set(categories)):
        raise ValueError("prompt_candidate_mutation_categories_not_canonical")
    joined = ", ".join(categories)
    if value["mutationSummary"] != f"Behavior focus: {joined}.":
        raise ValueError("prompt_candidate_summary_not_safe_projection")
    if value["hypothesis"] != (
        f"Preregistered hypothesis: {joined} improves the frozen Agent outcome score."
    ):
        raise ValueError("prompt_candidate_hypothesis_not_safe_projection")
    if not str(value.get("privateLineageHash", "")).startswith("sha256:"):
        raise ValueError("prompt_candidate_private_lineage_hash_missing")
    if not str(value.get("privateStateArtifactHash", "")).startswith("sha256:"):
        raise ValueError("prompt_candidate_private_state_artifact_hash_missing")


def _assert_training_projection_semantics(value: Mapping[str, Any]) -> None:
    body = {key: item for key, item in value.items() if key != "projectionHash"}
    if value["projectionHash"] != _canonical_hash(body):
        raise ValueError("prompt_training_projection_hash_mismatch")
    agent_id = str(value["target"]["agentId"])
    expected_refs = prompt_role_component_refs(agent_id)
    actual_refs = tuple(
        str(component["componentRef"]) for component in value["directComponents"]
    )
    if actual_refs != expected_refs:
        raise ValueError("prompt_training_projection_component_roster_mismatch")
    mature_count = int(value["matureSampleCount"])
    if any(
        int(component["directMatureSampleCount"]) != mature_count
        for component in value["directComponents"]
    ):
        raise ValueError("prompt_training_projection_component_sample_count_mismatch")
    experiment_ids = [
        str(experiment["experimentId"])
        for experiment in value["controlledExperiments"]
    ]
    if len(experiment_ids) != len(set(experiment_ids)):
        raise ValueError("prompt_training_projection_experiment_duplicate")
    cutoff = _instant(str(value["cutoffAt"]))
    if any(
        _instant(str(experiment["completedAt"])) > cutoff
        for experiment in value["controlledExperiments"]
    ):
        raise ValueError("prompt_training_projection_experiment_after_cutoff")
    contract = OUTCOME_CONTRACTS[agent_id]
    expected_outcome = {
        "evaluationObject": contract["evaluation_object"],
        "outcomeContractVersion": contract["outcome_contract_version"],
        "primaryLabelId": contract["primary_label_id"],
        "maturityHorizon": contract["maturity_horizon"],
        "maturityTradingDays": contract["maturity"]["horizon_trading_days"],
    }
    if value["outcomeContract"] != expected_outcome:
        raise ValueError("prompt_training_projection_outcome_contract_mismatch")
    evaluator = value["evaluator"]
    expected_implementation_hash = _canonical_hash(
        {
            "executorAdapterHash": evaluator["executorAdapterHash"],
            "evaluatorAdapterHash": evaluator["evaluatorAdapterHash"],
            "configHash": evaluator["configHash"],
        }
    )
    if evaluator["implementationHash"] != expected_implementation_hash:
        raise ValueError("prompt_training_projection_evaluator_binding_mismatch")


def _load_training_projection(
    conn: sqlite3.Connection, projection_hash: str
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT record_json FROM prompt_training_projections_v1
        WHERE projection_hash = ?
        """,
        (projection_hash,),
    ).fetchone()
    if row is None:
        raise ValueError("prompt_training_projection_not_found")
    return json.loads(str(row["record_json"]))


def _excluded_split_sample_ids_hash(split: Mapping[str, Any]) -> str:
    return _canonical_hash(
        sorted(
            (
                str(sample["sampleId"])
                for partition_name in ("validation", "holdout")
                for sample in split[partition_name]["samples"]
            ),
            key=_canonical_string_sort_key,
        )
    )


def _assert_candidate_training_projection_binding(
    candidate: Mapping[str, Any], projection: Mapping[str, Any]
) -> None:
    if int(projection["matureSampleCount"]) < 30:
        raise ValueError("prompt_candidate_training_sample_count_insufficient")
    if (
        candidate["target"] != projection["target"]
        or candidate["trainingProjectionHash"] != projection["projectionHash"]
        or candidate["excludedSampleIdsHash"] != projection["excludedSampleIdsHash"]
    ):
        raise ValueError("prompt_candidate_training_projection_mismatch")


def _assert_split_training_projection_binding(
    split: Mapping[str, Any], projection: Mapping[str, Any]
) -> None:
    if (
        split["target"] != projection["target"]
        or split["trainingProjectionHash"] != projection["projectionHash"]
        or _instant(str(split["cutoffAt"])) != _instant(str(projection["cutoffAt"]))
        or _excluded_split_sample_ids_hash(split)
        != projection["excludedSampleIdsHash"]
    ):
        raise ValueError("prompt_dataset_split_training_projection_mismatch")


def _assert_candidate_publication_semantics(value: Mapping[str, Any]) -> None:
    body = {key: item for key, item in value.items() if key != "publicationHash"}
    if value["publicationHash"] != _canonical_hash(body):
        raise ValueError("prompt_candidate_publication_hash_mismatch")


class PromptOptimizerStore:
    """Transactional, authority-closed storage for Prompt optimizer experiments."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        schema_root: Path | str | None = None,
        authorized_policy_hashes: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.schema_root = (
            Path(schema_root)
            if schema_root is not None
            else Path(__file__).resolve().parents[2] / "schemas"
        )
        self.authorized_policy_hashes = frozenset(
            authorized_policy_hashes
            if authorized_policy_hashes is not None
            else {
                value.strip()
                for value in os.environ.get(
                    "MOSAIC_PROMPT_PROMOTION_POLICY_HASHES", ""
                ).split(",")
                if value.strip()
            }
        )
        self._validators = self._load_validators()
        with self._connect() as conn:
            conn.executescript(_DDL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _load_validators(self) -> dict[str, Draft7Validator]:
        validators: dict[str, Draft7Validator] = {}
        for version, filename in _SCHEMA_FILE_BY_VERSION.items():
            schema = json.loads((self.schema_root / filename).read_text(encoding="utf-8"))
            Draft7Validator.check_schema(schema)
            validators[version] = Draft7Validator(schema, format_checker=FormatChecker())
        return validators

    def _validate(self, expected_version: str, record: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(record)
        if value.get("schemaVersion") != expected_version:
            raise ValueError(f"prompt_optimizer_schema_version_mismatch:{expected_version}")
        errors = sorted(
            self._validators[expected_version].iter_errors(value),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            first = errors[0]
            path = ".".join(str(part) for part in first.absolute_path) or "$"
            raise ValueError(f"prompt_optimizer_schema_invalid:{expected_version}:{path}:{first.message}")
        self._assert_canonical_strings(value)
        self._assert_timestamp_precision(value)
        return value

    @staticmethod
    def _assert_canonical_strings(value: Any) -> None:
        if isinstance(value, str):
            if value != value.strip(_ECMASCRIPT_TRIM_CHARS):
                raise ValueError("prompt_optimizer_noncanonical_string")
        elif isinstance(value, Mapping):
            for key, item in value.items():
                PromptOptimizerStore._assert_canonical_strings(key)
                PromptOptimizerStore._assert_canonical_strings(item)
        elif isinstance(value, list):
            for item in value:
                PromptOptimizerStore._assert_canonical_strings(item)

    @staticmethod
    def _assert_timestamp_precision(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(item, str) and str(key).endswith("At"):
                    _instant(item)
                else:
                    PromptOptimizerStore._assert_timestamp_precision(item)
        elif isinstance(value, list):
            for item in value:
                PromptOptimizerStore._assert_timestamp_precision(item)

    @staticmethod
    def _load_json(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return None if row is None else json.loads(str(row["record_json"]))

    @staticmethod
    def _assert_idempotent(existing: sqlite3.Row, record: Mapping[str, Any], object_id: str) -> None:
        if str(existing["record_json"]) != _canonical_json(record):
            raise ValueError(f"prompt_optimizer_id_conflict:{object_id}")

    def put_training_projection(
        self, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        value = self._validate("prompt_training_projection_v1", record)
        _assert_target_semantics(value)
        _assert_training_projection_semantics(value)
        target = value["target"]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            db_now = _db_now(conn)
            if _instant(str(value["cutoffAt"])) > db_now:
                raise ValueError("prompt_training_projection_cutoff_in_future")
            existing = conn.execute(
                """
                SELECT record_json FROM prompt_training_projections_v1
                WHERE projection_hash = ?
                """,
                (value["projectionHash"],),
            ).fetchone()
            if existing is not None:
                self._assert_idempotent(
                    existing, value, str(value["projectionHash"])
                )
                return value
            conflicting_id = conn.execute(
                """
                SELECT record_json FROM prompt_training_projections_v1
                WHERE projection_id = ?
                """,
                (value["projectionId"],),
            ).fetchone()
            if conflicting_id is not None:
                raise ValueError(
                    f"prompt_optimizer_id_conflict:{value['projectionId']}"
                )
            conn.execute(
                """
                INSERT INTO prompt_training_projections_v1 (
                    projection_hash, projection_id, agent_id, stage, cohort,
                    cutoff_at, record_json, persisted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["projectionHash"],
                    value["projectionId"],
                    target["agentId"],
                    target["stage"],
                    target["cohort"],
                    value["cutoffAt"],
                    _canonical_json(value),
                    _format_instant(db_now),
                ),
            )
        return value

    def get_training_projection(
        self, projection_hash: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    """
                    SELECT record_json FROM prompt_training_projections_v1
                    WHERE projection_hash = ?
                    """,
                    (projection_hash,),
                ).fetchone()
            )

    def put_training_projection_v2(
        self, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        value = self._validate("prompt_training_projection_v2", record)
        _assert_training_projection_v2_semantics(value)
        target = value["target"]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            db_now = _db_now(conn)
            if _instant(str(value["cutoffAt"])) > db_now:
                raise ValueError("prompt_training_projection_v2_cutoff_in_future")
            existing = conn.execute(
                "SELECT record_json FROM prompt_training_projections_v2 "
                "WHERE projection_hash = ?",
                (value["projectionHash"],),
            ).fetchone()
            if existing is not None:
                self._assert_idempotent(
                    existing, value, str(value["projectionHash"])
                )
                return value
            conflicting_id = conn.execute(
                "SELECT record_json FROM prompt_training_projections_v2 "
                "WHERE projection_id = ?",
                (value["projectionId"],),
            ).fetchone()
            if conflicting_id is not None:
                raise ValueError(
                    f"prompt_optimizer_id_conflict:{value['projectionId']}"
                )
            conn.execute(
                """
                INSERT INTO prompt_training_projections_v2 (
                    projection_hash, projection_id, agent_id, stage, cohort,
                    cutoff_at, record_json, persisted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["projectionHash"],
                    value["projectionId"],
                    target["agentId"],
                    target["stage"],
                    target["cohort"],
                    value["cutoffAt"],
                    _canonical_json(value),
                    _format_instant(db_now),
                ),
            )
        return value

    def get_training_projection_v2(
        self, projection_hash: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    "SELECT record_json FROM prompt_training_projections_v2 "
                    "WHERE projection_hash = ?",
                    (projection_hash,),
                ).fetchone()
            )

    def put_candidate(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_candidate_v1", record)
        _assert_target_semantics(value)
        _assert_candidate_semantics(value)
        target = value["target"]
        with self._connect() as conn:
            projection = _load_training_projection(
                conn, str(value["trainingProjectionHash"])
            )
            _assert_candidate_training_projection_binding(value, projection)
            existing = conn.execute(
                "SELECT record_json FROM prompt_candidates_v3 WHERE candidate_id = ?",
                (value["candidateId"],),
            ).fetchone()
            if existing is not None:
                self._assert_idempotent(existing, value, value["candidateId"])
                return value
            conn.execute(
                """
                INSERT INTO prompt_candidates_v3 (
                    candidate_id, parent_id, agent_id, stage, cohort,
                    zh_prompt_hash, en_prompt_hash, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["candidateId"],
                    value["parentId"],
                    target["agentId"],
                    target["stage"],
                    target["cohort"],
                    value["promptHashes"]["zh"],
                    value["promptHashes"]["en"],
                    _canonical_json(value),
                    value["createdAt"],
                ),
            )
        return value

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    "SELECT record_json FROM prompt_candidates_v3 WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
            )

    def put_candidate_publication(
        self, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        value = self._validate("prompt_candidate_publication_v1", record)
        _assert_candidate_publication_semantics(value)
        with self._connect() as conn:
            candidate = conn.execute(
                "SELECT record_json FROM prompt_candidates_v3 WHERE candidate_id = ?",
                (value["candidateId"],),
            ).fetchone()
            if candidate is None:
                raise ValueError("prompt_candidate_publication_candidate_not_found")
            candidate_record = json.loads(str(candidate["record_json"]))
            if value["candidateHash"] != _canonical_hash(candidate_record):
                raise ValueError("prompt_candidate_publication_candidate_hash_mismatch")
            existing = conn.execute(
                """
                SELECT record_json FROM prompt_candidate_publications_v1
                WHERE candidate_id = ?
                """,
                (value["candidateId"],),
            ).fetchone()
            if existing is not None:
                self._assert_idempotent(existing, value, value["candidateId"])
                return value
            conn.execute(
                """
                INSERT INTO prompt_candidate_publications_v1 (
                    candidate_id, candidate_hash, prompt_source_id,
                    candidate_prompt_commit, publication_hash, record_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    value["candidateId"],
                    value["candidateHash"],
                    value["promptSourceId"],
                    value["candidatePromptCommit"],
                    value["publicationHash"],
                    _canonical_json(value),
                ),
            )
        return value

    def get_candidate_publication(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    """
                    SELECT record_json FROM prompt_candidate_publications_v1
                    WHERE candidate_id = ?
                    """,
                    (candidate_id,),
                ).fetchone()
            )

    def put_split(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_dataset_split_v1", record)
        _assert_target_semantics(value)
        _assert_split_semantics(value)
        manifest_hash = _canonical_hash(value)
        target = value["target"]
        with self._connect() as conn:
            if _instant(str(value["createdAt"])) > _db_now(conn):
                raise ValueError("prompt_dataset_split_created_in_future")
            projection = _load_training_projection(
                conn, str(value["trainingProjectionHash"])
            )
            _assert_split_training_projection_binding(value, projection)
            existing = conn.execute(
                "SELECT record_json FROM prompt_dataset_splits_v3 WHERE split_id = ?",
                (value["splitId"],),
            ).fetchone()
            if existing is not None:
                self._assert_idempotent(existing, value, value["splitId"])
                return value
            conn.execute(
                """
                INSERT INTO prompt_dataset_splits_v3 (
                    split_id, manifest_hash, agent_id, stage, cohort, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["splitId"],
                    manifest_hash,
                    target["agentId"],
                    target["stage"],
                    target["cohort"],
                    _canonical_json(value),
                    value["createdAt"],
                ),
            )
        return value

    def get_split(self, split_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    "SELECT record_json FROM prompt_dataset_splits_v3 WHERE split_id = ?",
                    (split_id,),
                ).fetchone()
            )

    def put_family(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_candidate_family_v2", record)
        _assert_target_semantics(value)
        _assert_family_semantics(value)
        with self._connect() as conn:
            split_row = conn.execute(
                "SELECT manifest_hash, record_json FROM prompt_dataset_splits_v3 WHERE split_id = ?",
                (value["datasetSplitId"],),
            ).fetchone()
            if split_row is None:
                raise ValueError("prompt_candidate_family_split_not_found")
            split = json.loads(str(split_row["record_json"]))
            if (
                str(split_row["manifest_hash"]) != value["datasetSplitManifestHash"]
                or split["target"] != value["target"]
            ):
                raise ValueError("prompt_candidate_family_split_mismatch")
            projection = _load_training_projection(
                conn, str(split["trainingProjectionHash"])
            )
            _assert_split_training_projection_binding(split, projection)
            candidates = conn.execute(
                "SELECT candidate_id, record_json FROM prompt_candidates_v3 WHERE candidate_id IN ({})".format(
                    ",".join("?" for _ in value["candidateIds"])
                ),
                tuple(value["candidateIds"]),
            ).fetchall()
            if len(candidates) != len(value["candidateIds"]):
                raise ValueError("prompt_candidate_family_candidate_not_found")
            excluded_sample_ids_hash = _canonical_hash(
                sorted(
                    (
                        str(sample["sampleId"])
                        for partition_name in ("validation", "holdout")
                        for sample in split[partition_name]["samples"]
                    ),
                    key=_canonical_string_sort_key,
                )
            )
            for row in candidates:
                candidate = json.loads(str(row["record_json"]))
                if (
                    candidate["target"] != value["target"]
                    or candidate["parentId"] != value["championReleaseId"]
                    or candidate["parentPromptCommit"] != value["championPromptCommit"]
                    or candidate["parentPromptHashes"] != value["championPromptHashes"]
                ):
                    raise ValueError("prompt_candidate_family_champion_mismatch")
                if (
                    candidate["trainingProjectionHash"]
                    != split["trainingProjectionHash"]
                    or candidate["excludedSampleIdsHash"]
                    != excluded_sample_ids_hash
                ):
                    raise ValueError("prompt_candidate_family_training_split_mismatch")
            existing = conn.execute(
                "SELECT record_json FROM prompt_candidate_families_v3 WHERE family_id = ?",
                (value["familyId"],),
            ).fetchone()
            if existing is not None:
                self._assert_idempotent(existing, value, value["familyId"])
                return value
            holdout_snapshot_hash = str(split["holdout"]["snapshotHash"])
            split_owner = conn.execute(
                """
                SELECT family_id FROM prompt_candidate_families_v3
                WHERE dataset_split_id = ? OR holdout_snapshot_hash = ?
                """,
                (value["datasetSplitId"], holdout_snapshot_hash),
            ).fetchone()
            if split_owner is not None:
                raise ValueError("prompt_candidate_family_holdout_already_registered")
            conn.execute(
                """
                INSERT INTO prompt_candidate_families_v3 (
                    family_id, champion_release_id, dataset_split_id,
                    dataset_split_manifest_hash, holdout_snapshot_hash,
                    record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["familyId"],
                    value["championReleaseId"],
                    value["datasetSplitId"],
                    value["datasetSplitManifestHash"],
                    holdout_snapshot_hash,
                    _canonical_json(value),
                    value["createdAt"],
                ),
            )
        return value

    def get_family(self, family_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    "SELECT record_json FROM prompt_candidate_families_v3 WHERE family_id = ?",
                    (family_id,),
                ).fetchone()
            )

    def put_experiment(
        self,
        record: Mapping[str, Any],
        promotion_policy: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = self._validate("prompt_experiment_v2", record)
        _assert_target_semantics(value)
        _assert_experiment_semantics(value)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            db_now = _db_now(conn)
            candidate_row = conn.execute(
                "SELECT record_json FROM prompt_candidates_v3 WHERE candidate_id = ?",
                (value["candidateId"],),
            ).fetchone()
            if candidate_row is None:
                raise ValueError("prompt_experiment_candidate_not_found")
            candidate = json.loads(str(candidate_row["record_json"]))
            if (
                candidate["target"] != value["target"]
                or candidate["parentId"] != value["championId"]
                or candidate["parentPromptCommit"] != value["championPromptCommit"]
                or candidate["parentPromptHashes"] != value["championPromptHashes"]
                or candidate["promptRefs"] != value["candidatePromptRefs"]
                or candidate["promptHashes"] != value["candidatePromptHashes"]
            ):
                raise ValueError("prompt_experiment_candidate_mismatch")
            publication_row = conn.execute(
                """
                SELECT record_json FROM prompt_candidate_publications_v1
                WHERE candidate_id = ?
                """,
                (value["candidateId"],),
            ).fetchone()
            if publication_row is None:
                raise ValueError("prompt_experiment_candidate_publication_not_found")
            publication = json.loads(str(publication_row["record_json"]))
            if (
                publication["candidateHash"] != _canonical_hash(candidate)
                or publication["promptSourceId"] != value["candidatePromptSourceId"]
                or publication["candidatePromptCommit"]
                != value["candidatePromptCommit"]
                or publication["publicationHash"]
                != value["candidatePublicationHash"]
            ):
                raise ValueError("prompt_experiment_candidate_publication_mismatch")
            family_row = conn.execute(
                "SELECT record_json FROM prompt_candidate_families_v3 WHERE family_id = ?",
                (value["familyId"],),
            ).fetchone()
            if family_row is None:
                raise ValueError("prompt_experiment_family_not_found")
            family = json.loads(str(family_row["record_json"]))
            if (
                value["candidateId"] not in family["candidateIds"]
                or family["target"] != value["target"]
                or family["championReleaseId"] != value["championId"]
                or family["championPromptSourceId"]
                != value["championPromptSourceId"]
                or family["championPromptCommit"] != value["championPromptCommit"]
                or family["championPromptRefs"] != value["championPromptRefs"]
                or family["championPromptHashes"] != value["championPromptHashes"]
                or family["datasetSplitId"] != value["datasetSplitId"]
                or family["datasetSplitManifestHash"] != value["datasetSplitManifestHash"]
                or family["promotionPolicyVersion"] != value["promotionPolicyVersion"]
                or family["promotionPolicyConfigHash"]
                != value["promotionPolicyConfigHash"]
            ):
                raise ValueError("prompt_experiment_family_mismatch")
            split_row = conn.execute(
                "SELECT manifest_hash, record_json FROM prompt_dataset_splits_v3 WHERE split_id = ?",
                (value["datasetSplitId"],),
            ).fetchone()
            if split_row is None:
                raise ValueError("prompt_experiment_split_not_found")
            split = json.loads(str(split_row["record_json"]))
            if str(split_row["manifest_hash"]) != value["datasetSplitManifestHash"]:
                raise ValueError("prompt_experiment_split_mismatch")
            _assert_experiment_evaluator_binding(value, split)
            sibling_environment_row = conn.execute(
                """
                SELECT record_json FROM prompt_experiments_v3
                WHERE family_id = ? AND experiment_id != ?
                ORDER BY experiment_id LIMIT 1
                """,
                (value["familyId"], value["experimentId"]),
            ).fetchone()
            if sibling_environment_row is not None:
                sibling_environment = json.loads(
                    str(sibling_environment_row["record_json"])
                )
                if _experiment_family_environment(sibling_environment) != (
                    _experiment_family_environment(value)
                ):
                    raise ValueError(
                        "prompt_experiment_family_environment_drift"
                    )
            existing = conn.execute(
                "SELECT status, record_json FROM prompt_experiments_v3 WHERE experiment_id = ?",
                (value["experimentId"],),
            ).fetchone()
            if existing is not None:
                current = json.loads(str(existing["record_json"]))
                if current == value:
                    return value
                if (
                    current["status"] == value["status"]
                    and current["status"]
                    in {"HOLDOUT_RUNNING", "COMPLETE", "FAILED"}
                    and _without_keys(
                        current, {"holdoutOpenedAt", "completedAt"}
                    )
                    == _without_keys(value, {"holdoutOpenedAt", "completedAt"})
                ):
                    return current
                immutable = (
                    "familyId",
                    "candidateId",
                    "championId",
                    "target",
                    "championPromptCommit",
                    "championPromptRefs",
                    "championPromptHashes",
                    "candidatePromptRefs",
                    "candidatePromptHashes",
                    "datasetSplitId",
                    "datasetSplitManifestHash",
                    "promotionPolicyVersion",
                    "promotionPolicyConfigHash",
                    "modelConfigHash",
                    "toolConfigHash",
                    "componentCalibrationSnapshotHash",
                    "darwinianUsageSnapshotHash",
                    "executorAdapterHash",
                    "evaluatorAdapterHash",
                    "evaluationBinding",
                    "evaluatorVersion",
                    "evaluatorConfigHash",
                    "codeCommit",
                    "executionBehaviorRelease",
                    "repeatSeeds",
                    "createdAt",
                )
                if any(current[key] != value[key] for key in immutable):
                    raise ValueError("prompt_experiment_environment_drift")
                old_status = str(existing["status"])
                if value["status"] not in _EXPERIMENT_TRANSITIONS[old_status]:
                    raise ValueError(
                        f"prompt_experiment_transition_invalid:{old_status}:{value['status']}"
                    )
                if value["status"] == "HOLDOUT_RUNNING":
                    value = {
                        **value,
                        "holdoutOpenedAt": _format_instant(db_now),
                    }
                elif value["holdoutOpenedAt"] != current["holdoutOpenedAt"]:
                    raise ValueError("prompt_experiment_holdout_reopened")
                if value["status"] in {"COMPLETE", "FAILED"}:
                    value = {**value, "completedAt": _format_instant(db_now)}
                _assert_experiment_semantics(value)
                self._assert_experiment_transition_closure(
                    conn, current, value, family, promotion_policy
                )
                conn.execute(
                    """
                    UPDATE prompt_experiments_v3
                    SET status = ?, record_json = ?, completed_at = ?
                    WHERE experiment_id = ?
                    """,
                    (
                        value["status"],
                        _canonical_json(value),
                        value["completedAt"],
                        value["experimentId"],
                    ),
                )
                return value
            if value["status"] != "PENDING":
                raise ValueError("prompt_experiment_initial_status_invalid")
            if _instant(str(value["createdAt"])) > db_now:
                raise ValueError("prompt_experiment_created_in_future")
            if value["runIds"] or value["metrics"] or value["tailFailureCaseRefs"]:
                raise ValueError("prompt_experiment_initial_evidence_not_empty")
            conn.execute(
                """
                INSERT INTO prompt_experiments_v3 (
                    experiment_id, candidate_id, family_id, status, dataset_split_manifest_hash,
                    model_config_hash, tool_config_hash, evaluator_version,
                    evaluator_config_hash, code_commit, record_json, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["experimentId"],
                    value["candidateId"],
                    value["familyId"],
                    value["status"],
                    value["datasetSplitManifestHash"],
                    value["modelConfigHash"],
                    value["toolConfigHash"],
                    value["evaluatorVersion"],
                    value["evaluatorConfigHash"],
                    value["codeCommit"],
                    _canonical_json(value),
                    value["createdAt"],
                    value["completedAt"],
                ),
            )
        return value

    def _assert_experiment_transition_closure(
        self,
        conn: sqlite3.Connection,
        current: Mapping[str, Any],
        value: Mapping[str, Any],
        family: Mapping[str, Any],
        promotion_policy: Mapping[str, Any] | None,
    ) -> None:
        old_status = str(current["status"])
        new_status = str(value["status"])
        evidence_fields = ("runIds", "metrics", "tailFailureCaseRefs")
        if new_status == "FAILED":
            if any(current[key] != value[key] for key in evidence_fields):
                raise ValueError("prompt_experiment_failed_evidence_drift")
        elif old_status == "PENDING" and new_status == "VALIDATION_RUNNING":
            if any(current[key] != value[key] for key in evidence_fields):
                raise ValueError("prompt_experiment_running_evidence_drift")
        elif old_status == "VALIDATION_RUNNING" and new_status == "VALIDATION_COMPLETE":
            self._assert_exact_run_matrix(conn, value, "VALIDATION")
            metrics, failure_refs = _partition_aggregate(
                conn, str(value["experimentId"]), "VALIDATION"
            )
            if value["metrics"] != metrics or value["tailFailureCaseRefs"] != failure_refs:
                raise ValueError("prompt_experiment_validation_aggregate_mismatch")
        elif old_status == "VALIDATION_COMPLETE" and new_status == "HOLDOUT_RUNNING":
            self._assert_holdout_winner(
                conn, value, family, promotion_policy
            )
            self._assert_exact_run_matrix(conn, value, "VALIDATION")
            if any(current[key] != value[key] for key in evidence_fields):
                raise ValueError("prompt_experiment_holdout_open_evidence_drift")
        elif old_status == "HOLDOUT_RUNNING" and new_status == "COMPLETE":
            holdout_consumers = conn.execute(
                """
                SELECT experiment_id FROM prompt_experiments_v3
                WHERE family_id = ? AND status IN ('HOLDOUT_RUNNING', 'COMPLETE')
                """,
                (value["familyId"],),
            ).fetchall()
            if [str(row["experiment_id"]) for row in holdout_consumers] != [
                value["experimentId"]
            ]:
                raise ValueError("prompt_experiment_holdout_consumer_conflict")
            self._assert_exact_run_matrix(conn, value, "VALIDATION")
            self._assert_exact_run_matrix(conn, value, "HOLDOUT")
            validation_metrics, validation_refs = _partition_aggregate(
                conn, str(value["experimentId"]), "VALIDATION"
            )
            holdout_metrics, holdout_refs = _partition_aggregate(
                conn, str(value["experimentId"]), "HOLDOUT"
            )
            expected_metrics = {**validation_metrics, **holdout_metrics}
            expected_refs = sorted(
                set(validation_refs + holdout_refs),
                key=_canonical_string_sort_key,
            )
            if (
                value["metrics"] != expected_metrics
                or value["tailFailureCaseRefs"] != expected_refs
            ):
                raise ValueError("prompt_experiment_complete_aggregate_mismatch")

    def _assert_holdout_winner(
        self,
        conn: sqlite3.Connection,
        requested: Mapping[str, Any],
        family: Mapping[str, Any],
        raw_policy: Mapping[str, Any] | None,
    ) -> None:
        policy = _validated_promotion_policy(raw_policy)
        policy_hash = _canonical_hash(policy)
        if policy_hash not in self.authorized_policy_hashes:
            raise ValueError("prompt_experiment_holdout_policy_not_authorized")
        if (
            family["promotionPolicyVersion"] != policy["policyVersion"]
            or family["promotionPolicyConfigHash"] != policy_hash
            or requested["promotionPolicyVersion"] != policy["policyVersion"]
            or requested["promotionPolicyConfigHash"] != policy_hash
        ):
            raise ValueError("prompt_experiment_holdout_policy_drift")
        split_row = conn.execute(
            "SELECT manifest_hash, record_json FROM prompt_dataset_splits_v3 WHERE split_id = ?",
            (family["datasetSplitId"],),
        ).fetchone()
        if split_row is None:
            raise ValueError("prompt_experiment_split_not_found")
        split = json.loads(str(split_row["record_json"]))
        if (
            str(split_row["manifest_hash"]) != family["datasetSplitManifestHash"]
            or requested["datasetSplitManifestHash"]
            != family["datasetSplitManifestHash"]
        ):
            raise ValueError("prompt_experiment_holdout_split_drift")
        sibling_rows = conn.execute(
            """
            SELECT record_json FROM prompt_experiments_v3
            WHERE family_id = ? ORDER BY candidate_id, experiment_id
            """,
            (requested["familyId"],),
        ).fetchall()
        siblings = [json.loads(str(row["record_json"])) for row in sibling_rows]
        if (
            {str(item["candidateId"]) for item in siblings}
            != set(family["candidateIds"])
            or len(siblings) != len(family["candidateIds"])
            or any(item["status"] != "VALIDATION_COMPLETE" for item in siblings)
        ):
            raise ValueError("prompt_experiment_family_validation_incomplete")
        if len(
            {
                _canonical_hash(_experiment_family_environment(sibling))
                for sibling in siblings
            }
        ) != 1:
            raise ValueError("prompt_experiment_family_environment_drift")
        eligible: list[Mapping[str, Any]] = []
        for sibling in siblings:
            if (
                sibling["promotionPolicyVersion"] != policy["policyVersion"]
                or sibling["promotionPolicyConfigHash"] != policy_hash
                or sibling["datasetSplitId"] != family["datasetSplitId"]
                or sibling["datasetSplitManifestHash"]
                != family["datasetSplitManifestHash"]
            ):
                raise ValueError("prompt_experiment_family_validation_binding_drift")
            self._assert_exact_run_matrix(conn, sibling, "VALIDATION")
            if _validation_gate_eligible(
                conn, sibling, family, split, policy, policy_hash
            ):
                eligible.append(sibling)
        if not eligible:
            raise ValueError("prompt_experiment_family_no_validation_eligible_candidate")
        winner = sorted(
            eligible,
            key=lambda item: (
                -float(item["metrics"]["validation_paired_delta"]),
                _canonical_string_sort_key(str(item["candidateId"])),
            ),
        )[0]
        if winner["experimentId"] != requested["experimentId"]:
            raise ValueError("prompt_experiment_holdout_winner_required")

    @staticmethod
    def _assert_exact_run_matrix(
        conn: sqlite3.Connection, experiment: Mapping[str, Any], partition: str
    ) -> None:
        split_row = conn.execute(
            "SELECT record_json FROM prompt_dataset_splits_v3 WHERE split_id = ?",
            (experiment["datasetSplitId"],),
        ).fetchone()
        if split_row is None:
            raise ValueError("prompt_experiment_split_not_found")
        split = json.loads(str(split_row["record_json"]))
        samples = split[partition.lower()]["samples"]
        expected = {
            (side, sample["sampleId"], seed)
            for sample in samples
            for seed in experiment["repeatSeeds"]
            for side in ("CHAMPION", "CANDIDATE")
        }
        rows = conn.execute(
            """
            SELECT run_id, side, sample_id, seed, status
            FROM prompt_experiment_runs_v3
            WHERE experiment_id = ? AND partition_name = ?
            """,
            (experiment["experimentId"], partition),
        ).fetchall()
        actual = {(str(row["side"]), str(row["sample_id"]), int(row["seed"])) for row in rows}
        if actual != expected or any(str(row["status"]) != "COMPLETE" for row in rows):
            raise ValueError(f"prompt_experiment_{partition.lower()}_run_matrix_incomplete")
        complete_ids = sorted(
            str(row["run_id"])
            for row in conn.execute(
                """
                SELECT run_id FROM prompt_experiment_runs_v3
                WHERE experiment_id = ? AND status = 'COMPLETE'
                """,
                (experiment["experimentId"],),
            ).fetchall()
        )
        if complete_ids != experiment["runIds"]:
            raise ValueError("prompt_experiment_run_manifest_mismatch")

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    "SELECT record_json FROM prompt_experiments_v3 WHERE experiment_id = ?",
                    (experiment_id,),
                ).fetchone()
            )

    def list_experiments(self, family_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT record_json FROM prompt_experiments_v3
                WHERE family_id = ? ORDER BY candidate_id, experiment_id
                """,
                (family_id,),
            ).fetchall()
        return [json.loads(str(row["record_json"])) for row in rows]

    def claim_run(
        self, record: Mapping[str, Any], lease_duration_ms: int
    ) -> dict[str, Any] | None:
        if (
            isinstance(lease_duration_ms, bool)
            or not isinstance(lease_duration_ms, int)
            or not 1 <= lease_duration_ms <= 86_400_000
        ):
            raise ValueError("prompt_experiment_run_lease_duration_invalid")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            db_now = _db_now(conn)
            proposal = {
                **record,
                "startedAt": _format_instant(db_now),
                "leaseExpiresAt": _format_instant(
                    db_now + timedelta(milliseconds=lease_duration_ms)
                ),
            }
            value = self._validate("prompt_experiment_run_v1", proposal)
            _assert_run_semantics(value)
            if value["status"] != "RUNNING":
                raise ValueError("prompt_experiment_run_claim_requires_running")
            experiment = conn.execute(
                "SELECT status, record_json FROM prompt_experiments_v3 WHERE experiment_id = ?",
                (value["experimentId"],),
            ).fetchone()
            if experiment is None:
                raise ValueError("prompt_experiment_run_parent_not_found")
            experiment_status = str(experiment["status"])
            allowed = (
                value["partition"] == "VALIDATION" and experiment_status == "VALIDATION_RUNNING"
            ) or (value["partition"] == "HOLDOUT" and experiment_status == "HOLDOUT_RUNNING")
            if not allowed:
                raise ValueError("prompt_experiment_run_partition_not_open")
            experiment_record = json.loads(str(experiment["record_json"]))
            split_row = conn.execute(
                "SELECT record_json FROM prompt_dataset_splits_v3 WHERE split_id = ?",
                (experiment_record["datasetSplitId"],),
            ).fetchone()
            if split_row is None:
                raise ValueError("prompt_experiment_split_not_found")
            split = json.loads(str(split_row["record_json"]))
            sample_ids = {
                str(sample["sampleId"])
                for sample in split[value["partition"].lower()]["samples"]
            }
            if (
                value["sampleId"] not in sample_ids
                or value["seed"] not in experiment_record["repeatSeeds"]
            ):
                raise ValueError("prompt_experiment_run_coordinates_not_frozen")
            existing = conn.execute(
                "SELECT status, record_json FROM prompt_experiment_runs_v3 WHERE run_id = ?",
                (value["runId"],),
            ).fetchone()
            if existing is not None:
                current = json.loads(str(existing["record_json"]))
                immutable = ("experimentId", "partition", "side", "sampleId", "seed")
                if any(current[key] != value[key] for key in immutable):
                    raise ValueError("prompt_experiment_run_identity_drift")
                old_status = str(existing["status"])
                if old_status == "COMPLETE":
                    return None
                if old_status == "RUNNING" and _instant(
                    str(current["leaseExpiresAt"])
                ) > db_now:
                    return None
                if (
                    old_status == "RUNNING"
                    and int(current["attempt"]) >= _MAX_RUN_ATTEMPTS
                ):
                    if value["attempt"] != current["attempt"]:
                        raise ValueError("prompt_experiment_run_attempt_invalid")
                    error_code = "prompt_experiment_lease_expired_max_attempts"
                    terminal = self._validate(
                        "prompt_experiment_run_v1",
                        {
                            **current,
                            "status": "FAILED",
                            "retryable": False,
                            "attemptFailureCodes": [
                                *current["attemptFailureCodes"],
                                error_code,
                            ],
                            "errorCode": error_code,
                            "completedAt": _format_instant(db_now),
                        },
                    )
                    _assert_run_semantics(terminal)
                    conn.execute(
                        """
                        UPDATE prompt_experiment_runs_v3
                        SET status = 'FAILED', record_json = ?, completed_at = ?
                        WHERE run_id = ? AND status = 'RUNNING'
                        """,
                        (
                            _canonical_json(terminal),
                            terminal["completedAt"],
                            terminal["runId"],
                        ),
                    )
                    return None
                if old_status not in {"RUNNING", "FAILED"}:
                    return None
                if old_status == "FAILED" and (
                    not current["retryable"]
                    or int(current["attempt"]) >= _MAX_RUN_ATTEMPTS
                ):
                    return None
                if value["attempt"] != int(current["attempt"]) + 1:
                    raise ValueError("prompt_experiment_run_attempt_invalid")
                failure_codes = list(current["attemptFailureCodes"])
                if old_status == "RUNNING":
                    failure_codes.append("prompt_experiment_lease_expired")
                value = self._validate(
                    "prompt_experiment_run_v1",
                    {
                        **value,
                        "agentOutputRef": None,
                        "metrics": {},
                        "failureCaseRefs": [],
                        "traceRef": None,
                        "effectiveInputHash": None,
                        "retryable": False,
                        "attemptFailureCodes": failure_codes,
                        "errorCode": None,
                        "completedAt": None,
                    },
                )
                conn.execute(
                    """
                    UPDATE prompt_experiment_runs_v3
                    SET status = 'RUNNING', record_json = ?, completed_at = NULL
                    WHERE run_id = ? AND status IN ('RUNNING', 'FAILED')
                    """,
                    (_canonical_json(value), value["runId"]),
                )
                return value if conn.execute("SELECT changes()").fetchone()[0] == 1 else None
            if value["attempt"] != 1:
                raise ValueError("prompt_experiment_run_initial_attempt_invalid")
            if value["attemptFailureCodes"]:
                raise ValueError("prompt_experiment_run_initial_failure_history_invalid")
            conn.execute(
                """
                INSERT INTO prompt_experiment_runs_v3 (
                    run_id, experiment_id, partition_name, side, sample_id,
                    seed, status, record_json, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', ?, NULL)
                """,
                (
                    value["runId"],
                    value["experimentId"],
                    value["partition"],
                    value["side"],
                    value["sampleId"],
                    value["seed"],
                    _canonical_json(value),
                ),
            )
        return value

    def put_run(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_experiment_run_v1", record)
        _assert_run_semantics(value)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            db_now = _db_now(conn)
            experiment = conn.execute(
                "SELECT status, record_json FROM prompt_experiments_v3 WHERE experiment_id = ?",
                (value["experimentId"],),
            ).fetchone()
            if experiment is None:
                raise ValueError("prompt_experiment_run_parent_not_found")
            experiment_status = str(experiment["status"])
            allowed_partition = (
                value["partition"] == "VALIDATION"
                and experiment_status in {"VALIDATION_RUNNING", "VALIDATION_COMPLETE"}
            ) or (
                value["partition"] == "HOLDOUT"
                and experiment_status in {"HOLDOUT_RUNNING", "COMPLETE"}
            )
            if not allowed_partition:
                raise ValueError("prompt_experiment_run_partition_not_open")
            existing = conn.execute(
                "SELECT status, record_json FROM prompt_experiment_runs_v3 WHERE run_id = ?",
                (value["runId"],),
            ).fetchone()
            if existing is not None:
                current = json.loads(str(existing["record_json"]))
                if current == value:
                    return value
                if (
                    current["status"] == value["status"]
                    and current["status"] in {"COMPLETE", "FAILED"}
                    and _without_keys(current, {"completedAt"})
                    == _without_keys(value, {"completedAt"})
                ):
                    return current
                immutable = ("experimentId", "partition", "side", "sampleId", "seed")
                if any(current[key] != value[key] for key in immutable):
                    raise ValueError("prompt_experiment_run_identity_drift")
                old_status = str(existing["status"])
                if old_status == "RUNNING" and _instant(
                    str(current["leaseExpiresAt"])
                ) <= db_now:
                    raise ValueError("prompt_experiment_run_lease_expired")
                if (
                    current["leaseOwner"] != value["leaseOwner"]
                    or current["leaseExpiresAt"] != value["leaseExpiresAt"]
                    or current["attempt"] != value["attempt"]
                    or current["startedAt"] != value["startedAt"]
                ):
                    raise ValueError("prompt_experiment_run_lease_owner_mismatch")
                if value["status"] not in _RUN_TRANSITIONS[old_status]:
                    raise ValueError(
                        f"prompt_experiment_run_transition_invalid:{old_status}:{value['status']}"
                    )
                if value["status"] in {"COMPLETE", "FAILED"}:
                    value = {**value, "completedAt": _format_instant(db_now)}
                    _assert_run_semantics(value)
                conn.execute(
                    """
                    UPDATE prompt_experiment_runs_v3
                    SET status = ?, record_json = ?, completed_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        value["status"],
                        _canonical_json(value),
                        value["completedAt"],
                        value["runId"],
                    ),
                )
                return value
            raise ValueError("prompt_experiment_run_must_be_claimed")
        return value

    def list_runs(self, experiment_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT record_json FROM prompt_experiment_runs_v3
                WHERE experiment_id = ?
                ORDER BY partition_name, sample_id, seed, side
                """,
                (experiment_id,),
            ).fetchall()
        return [json.loads(str(row["record_json"])) for row in rows]

    def latest_summary(self, cohort: str) -> dict[str, Any]:
        if not cohort.strip():
            raise ValueError("prompt_optimizer_cohort_required")
        with self._connect() as conn:
            candidate_row = conn.execute(
                """
                SELECT record_json FROM prompt_candidates_v3
                WHERE cohort = ? ORDER BY created_at DESC, candidate_id DESC LIMIT 1
                """,
                (cohort,),
            ).fetchone()
            candidate = self._load_json(candidate_row)
            if candidate is None:
                return {"candidate": None, "experiment": None}
            experiment_row = conn.execute(
                """
                SELECT record_json FROM prompt_experiments_v3
                WHERE candidate_id = ? ORDER BY created_at DESC, experiment_id DESC LIMIT 1
                """,
                (candidate["candidateId"],),
            ).fetchone()
            experiment = self._load_json(experiment_row)
        return {"candidate": candidate, "experiment": experiment}


    def get_production_variant_roster_revision(
        self, revision_id: str
    ) -> dict[str, Any] | None:
        from mosaic.scorecard.darwinian_v2 import (
            get_production_variant_roster_revision,
        )

        with self._connect() as conn:
            return get_production_variant_roster_revision(conn, revision_id)


__all__ = ["PromptOptimizerStore"]

"""Minimal persistence for Prompt Candidate experiments.

The TypeScript Zod contracts are the source of truth.  This module validates
against their generated JSON schemas and stores only public hashes, refs, and
metrics in the existing scorecard SQLite database.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from jsonschema import Draft7Validator, FormatChecker

from mosaic.scorecard.store import DEFAULT_DB_PATH


_SCHEMA_FILE_BY_VERSION = {
    "prompt_candidate_v1": "prompt_candidate_v1.schema.json",
    "prompt_candidate_family_v1": "prompt_candidate_family_v1.schema.json",
    "prompt_dataset_split_v1": "prompt_dataset_split_v1.schema.json",
    "prompt_experiment_v1": "prompt_experiment_v1.schema.json",
    "prompt_experiment_run_v1": "prompt_experiment_run_v1.schema.json",
    "prompt_promotion_decision_v1": "prompt_promotion_decision_v1.schema.json",
}

_DDL = """
CREATE TABLE IF NOT EXISTS prompt_candidates_v3 (
    candidate_id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    cohort TEXT NOT NULL,
    training_snapshot_id TEXT NOT NULL,
    training_snapshot_hash TEXT NOT NULL,
    zh_prompt_hash TEXT NOT NULL,
    en_prompt_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
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
    status TEXT NOT NULL CHECK(status IN ('REGISTERED', 'SELECTED', 'COMPLETE')),
    champion_release_id TEXT NOT NULL,
    dataset_split_id TEXT NOT NULL REFERENCES prompt_dataset_splits_v3(split_id),
    dataset_split_manifest_hash TEXT NOT NULL,
    selected_candidate_id TEXT,
    selected_experiment_id TEXT,
    holdout_experiment_id TEXT,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS prompt_promotion_decisions_v3 (
    decision_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL UNIQUE REFERENCES prompt_experiments_v3(experiment_id),
    candidate_id TEXT NOT NULL REFERENCES prompt_candidates_v3(candidate_id),
    decision TEXT NOT NULL CHECK(decision IN ('ELIGIBLE', 'REJECTED')),
    policy_version TEXT NOT NULL,
    policy_config_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    decided_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompt_candidates_v3_target
    ON prompt_candidates_v3(cohort, agent_id, stage, created_at);
CREATE INDEX IF NOT EXISTS idx_prompt_experiments_v3_candidate
    ON prompt_experiments_v3(candidate_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prompt_runs_v3_experiment
    ON prompt_experiment_runs_v3(experiment_id, partition_name, status);
"""

_FAMILY_TRANSITIONS = {"REGISTERED": {"SELECTED"}, "SELECTED": set(), "COMPLETE": set()}

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
    "FAILED": {"RUNNING"},
}


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode()).hexdigest()


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
    for key in sorted(pairs):
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
            f"{prefix}_candidate_mean": sum(candidate_scores) / len(candidate_scores),
            f"{prefix}_champion_mean": sum(champion_scores) / len(champion_scores),
            f"{prefix}_paired_delta": sum(deltas) / len(deltas),
            f"{prefix}_pair_count": len(pairs),
        },
        sorted(failure_refs),
    )


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
    alignment = {
        "alignmentVerifierVersion": value["alignmentVerifierVersion"],
        "promptHashes": value["promptHashes"],
    }
    if value["behaviorAlignmentHash"] != _canonical_hash(alignment):
        raise ValueError("prompt_candidate_alignment_hash_mismatch")
    if not str(value.get("privateLineageHash", "")).startswith("sha256:"):
        raise ValueError("prompt_candidate_private_lineage_hash_missing")
    if not str(value.get("privateStateArtifactHash", "")).startswith("sha256:"):
        raise ValueError("prompt_candidate_private_state_artifact_hash_missing")


class PromptOptimizerStore:
    """Transactional, authority-closed storage for Prompt optimizer experiments."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        schema_root: Path | str | None = None,
        authorized_policy_hashes: set[str] | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.schema_root = (
            Path(schema_root)
            if schema_root is not None
            else Path(__file__).resolve().parents[2] / "schemas"
        )
        self.authorized_policy_hashes = (
            set(authorized_policy_hashes)
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
        return value

    @staticmethod
    def _load_json(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return None if row is None else json.loads(str(row["record_json"]))

    @staticmethod
    def _assert_idempotent(existing: sqlite3.Row, record: Mapping[str, Any], object_id: str) -> None:
        if str(existing["record_json"]) != _canonical_json(record):
            raise ValueError(f"prompt_optimizer_id_conflict:{object_id}")

    def put_candidate(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_candidate_v1", record)
        _assert_candidate_semantics(value)
        target = value["target"]
        with self._connect() as conn:
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
                    training_snapshot_id, training_snapshot_hash,
                    zh_prompt_hash, en_prompt_hash, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["candidateId"],
                    value["parentId"],
                    target["agentId"],
                    target["stage"],
                    target["cohort"],
                    value["trainingSnapshotId"],
                    value["trainingSnapshotHash"],
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

    def put_split(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_dataset_split_v1", record)
        manifest_hash = _canonical_hash(value)
        target = value["target"]
        with self._connect() as conn:
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
        value = self._validate("prompt_candidate_family_v1", record)
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
            candidates = conn.execute(
                "SELECT candidate_id, record_json FROM prompt_candidates_v3 WHERE candidate_id IN ({})".format(
                    ",".join("?" for _ in value["candidateIds"])
                ),
                tuple(value["candidateIds"]),
            ).fetchall()
            if len(candidates) != len(value["candidateIds"]):
                raise ValueError("prompt_candidate_family_candidate_not_found")
            for row in candidates:
                candidate = json.loads(str(row["record_json"]))
                if (
                    candidate["target"] != value["target"]
                    or candidate["parentId"] != value["championReleaseId"]
                    or candidate["parentPromptCommit"] != value["championPromptCommit"]
                    or candidate["parentPromptHashes"] != value["championPromptHashes"]
                ):
                    raise ValueError("prompt_candidate_family_champion_mismatch")
            existing = conn.execute(
                "SELECT status, record_json FROM prompt_candidate_families_v3 WHERE family_id = ?",
                (value["familyId"],),
            ).fetchone()
            if existing is not None:
                current = json.loads(str(existing["record_json"]))
                if current == value:
                    return value
                immutable = (
                    "target",
                    "championReleaseId",
                    "championPromptCommit",
                    "championPromptRefs",
                    "championPromptHashes",
                    "datasetSplitId",
                    "datasetSplitManifestHash",
                    "candidateIds",
                    "createdAt",
                )
                if any(current[key] != value[key] for key in immutable):
                    raise ValueError("prompt_candidate_family_definition_drift")
                old_status = str(existing["status"])
                if value["status"] not in _FAMILY_TRANSITIONS[old_status]:
                    raise ValueError(
                        f"prompt_candidate_family_transition_invalid:{old_status}:{value['status']}"
                    )
                self._assert_family_selection(conn, value)
                conn.execute(
                    """
                    UPDATE prompt_candidate_families_v3
                    SET status = ?, selected_candidate_id = ?, selected_experiment_id = ?,
                        record_json = ?, updated_at = ?
                    WHERE family_id = ?
                    """,
                    (
                        value["status"],
                        value["selectedCandidateId"],
                        value["selectedExperimentId"],
                        _canonical_json(value),
                        value["updatedAt"],
                        value["familyId"],
                    ),
                )
                return value
            if value["status"] != "REGISTERED":
                raise ValueError("prompt_candidate_family_initial_status_invalid")
            conn.execute(
                """
                INSERT INTO prompt_candidate_families_v3 (
                    family_id, status, champion_release_id, dataset_split_id,
                    dataset_split_manifest_hash, selected_candidate_id,
                    selected_experiment_id, holdout_experiment_id, record_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["familyId"],
                    value["status"],
                    value["championReleaseId"],
                    value["datasetSplitId"],
                    value["datasetSplitManifestHash"],
                    None,
                    None,
                    None,
                    _canonical_json(value),
                    value["createdAt"],
                    value["updatedAt"],
                ),
            )
        return value

    @staticmethod
    def _assert_family_selection(conn: sqlite3.Connection, value: Mapping[str, Any]) -> None:
        if value["status"] != "SELECTED":
            raise ValueError("prompt_candidate_family_selection_required")
        rows = conn.execute(
            "SELECT experiment_id, candidate_id, status, record_json FROM prompt_experiments_v3 WHERE family_id = ?",
            (value["familyId"],),
        ).fetchall()
        by_candidate: dict[str, sqlite3.Row] = {}
        for row in rows:
            if str(row["status"]) != "VALIDATION_COMPLETE":
                continue
            candidate_id = str(row["candidate_id"])
            if candidate_id in by_candidate:
                raise ValueError("prompt_candidate_family_duplicate_validation_experiment")
            by_candidate[candidate_id] = row
        if set(by_candidate) != set(value["candidateIds"]):
            raise ValueError("prompt_candidate_family_validation_incomplete")
        experiment_ids = sorted(str(row["experiment_id"]) for row in by_candidate.values())
        if experiment_ids != value["validationExperimentIds"]:
            raise ValueError("prompt_candidate_family_validation_manifest_mismatch")
        winner = by_candidate.get(str(value["selectedCandidateId"]))
        if winner is None or str(winner["experiment_id"]) != value["selectedExperimentId"]:
            raise ValueError("prompt_candidate_family_winner_mismatch")
        ranked: list[tuple[float, str, str]] = []
        for candidate_id, row in by_candidate.items():
            metrics, _ = _partition_aggregate(
                conn, str(row["experiment_id"]), "VALIDATION"
            )
            experiment = json.loads(str(row["record_json"]))
            if experiment["metrics"] != metrics:
                raise ValueError("prompt_candidate_family_validation_metrics_mismatch")
            ranked.append(
                (
                    -float(metrics["validation_paired_delta"]),
                    candidate_id,
                    str(row["experiment_id"]),
                )
            )
        _, expected_candidate_id, expected_experiment_id = min(ranked)
        if (
            value["selectedCandidateId"] != expected_candidate_id
            or value["selectedExperimentId"] != expected_experiment_id
        ):
            raise ValueError("prompt_candidate_family_winner_not_deterministic")

    def get_family(self, family_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    "SELECT record_json FROM prompt_candidate_families_v3 WHERE family_id = ?",
                    (family_id,),
                ).fetchone()
            )

    def put_experiment(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_experiment_v1", record)
        with self._connect() as conn:
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
            family_row = conn.execute(
                "SELECT status, record_json FROM prompt_candidate_families_v3 WHERE family_id = ?",
                (value["familyId"],),
            ).fetchone()
            if family_row is None:
                raise ValueError("prompt_experiment_family_not_found")
            family = json.loads(str(family_row["record_json"]))
            if (
                value["candidateId"] not in family["candidateIds"]
                or family["target"] != value["target"]
                or family["championReleaseId"] != value["championId"]
                or family["championPromptCommit"] != value["championPromptCommit"]
                or family["championPromptRefs"] != value["championPromptRefs"]
                or family["championPromptHashes"] != value["championPromptHashes"]
                or family["datasetSplitId"] != value["datasetSplitId"]
                or family["datasetSplitManifestHash"] != value["datasetSplitManifestHash"]
            ):
                raise ValueError("prompt_experiment_family_mismatch")
            existing = conn.execute(
                "SELECT status, record_json FROM prompt_experiments_v3 WHERE experiment_id = ?",
                (value["experimentId"],),
            ).fetchone()
            if existing is not None:
                current = json.loads(str(existing["record_json"]))
                if current == value:
                    return value
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
                    "validationSnapshotHash",
                    "holdoutSnapshotHash",
                    "modelConfigHash",
                    "toolConfigHash",
                    "evaluatorVersion",
                    "evaluatorConfigHash",
                    "codeCommit",
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
                if current["holdoutOpenedAt"] is not None and (
                    value["holdoutOpenedAt"] != current["holdoutOpenedAt"]
                ):
                    raise ValueError("prompt_experiment_holdout_reopened")
                self._assert_experiment_transition_closure(conn, current, value, family)
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
                if old_status == "VALIDATION_COMPLETE" and value["status"] == "HOLDOUT_RUNNING":
                    consumed = {
                        **family,
                        "status": "COMPLETE",
                        "holdoutExperimentId": value["experimentId"],
                        "updatedAt": value["holdoutOpenedAt"],
                    }
                    conn.execute(
                        """
                        UPDATE prompt_candidate_families_v3
                        SET status = 'COMPLETE', holdout_experiment_id = ?,
                            record_json = ?, updated_at = ?
                        WHERE family_id = ? AND status = 'SELECTED'
                        """,
                        (
                            value["experimentId"],
                            _canonical_json(consumed),
                            value["holdoutOpenedAt"],
                            value["familyId"],
                        ),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0] != 1:
                        raise ValueError("prompt_candidate_family_holdout_already_consumed")
                return value
            if value["status"] != "PENDING":
                raise ValueError("prompt_experiment_initial_status_invalid")
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

    @staticmethod
    def _assert_experiment_transition_closure(
        conn: sqlite3.Connection,
        current: Mapping[str, Any],
        value: Mapping[str, Any],
        family: Mapping[str, Any],
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
            PromptOptimizerStore._assert_exact_run_matrix(conn, value, "VALIDATION")
            metrics, failure_refs = _partition_aggregate(
                conn, str(value["experimentId"]), "VALIDATION"
            )
            if value["metrics"] != metrics or value["tailFailureCaseRefs"] != failure_refs:
                raise ValueError("prompt_experiment_validation_aggregate_mismatch")
        elif old_status == "VALIDATION_COMPLETE" and new_status == "HOLDOUT_RUNNING":
            if (
                family["status"] != "SELECTED"
                or family["selectedCandidateId"] != value["candidateId"]
                or family["selectedExperimentId"] != value["experimentId"]
                or family["holdoutExperimentId"] is not None
            ):
                raise ValueError("prompt_experiment_not_selected_for_holdout")
            PromptOptimizerStore._assert_exact_run_matrix(conn, value, "VALIDATION")
            if any(current[key] != value[key] for key in evidence_fields):
                raise ValueError("prompt_experiment_holdout_open_evidence_drift")
        elif old_status == "HOLDOUT_RUNNING" and new_status == "COMPLETE":
            PromptOptimizerStore._assert_exact_run_matrix(conn, value, "VALIDATION")
            PromptOptimizerStore._assert_exact_run_matrix(conn, value, "HOLDOUT")
            validation_metrics, validation_refs = _partition_aggregate(
                conn, str(value["experimentId"]), "VALIDATION"
            )
            holdout_metrics, holdout_refs = _partition_aggregate(
                conn, str(value["experimentId"]), "HOLDOUT"
            )
            expected_metrics = {**validation_metrics, **holdout_metrics}
            expected_refs = sorted(set(validation_refs + holdout_refs))
            if (
                value["metrics"] != expected_metrics
                or value["tailFailureCaseRefs"] != expected_refs
            ):
                raise ValueError("prompt_experiment_complete_aggregate_mismatch")

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

    def claim_run(self, record: Mapping[str, Any]) -> dict[str, Any] | None:
        value = self._validate("prompt_experiment_run_v1", record)
        if value["status"] != "RUNNING":
            raise ValueError("prompt_experiment_run_claim_requires_running")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            experiment = conn.execute(
                "SELECT status FROM prompt_experiments_v3 WHERE experiment_id = ?",
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
            existing = conn.execute(
                "SELECT status, record_json FROM prompt_experiment_runs_v3 WHERE run_id = ?",
                (value["runId"],),
            ).fetchone()
            if existing is not None:
                current = json.loads(str(existing["record_json"]))
                immutable = ("experimentId", "partition", "side", "sampleId", "seed")
                if any(current[key] != value[key] for key in immutable):
                    raise ValueError("prompt_experiment_run_identity_drift")
                if str(existing["status"]) != "FAILED":
                    return None
                conn.execute(
                    """
                    UPDATE prompt_experiment_runs_v3
                    SET status = 'RUNNING', record_json = ?, completed_at = NULL
                    WHERE run_id = ? AND status = 'FAILED'
                    """,
                    (_canonical_json(value), value["runId"]),
                )
                return value if conn.execute("SELECT changes()").fetchone()[0] == 1 else None
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
        with self._connect() as conn:
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
                immutable = ("experimentId", "partition", "side", "sampleId", "seed")
                if any(current[key] != value[key] for key in immutable):
                    raise ValueError("prompt_experiment_run_identity_drift")
                old_status = str(existing["status"])
                if value["status"] not in _RUN_TRANSITIONS[old_status]:
                    raise ValueError(
                        f"prompt_experiment_run_transition_invalid:{old_status}:{value['status']}"
                    )
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

    def put_decision(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_promotion_decision_v1", record)
        expected_id = "decision-" + _canonical_hash(
            {
                "experimentId": value["experimentId"],
                "policyHash": value["policyConfigHash"],
            }
        )[len("sha256:") : len("sha256:") + 24]
        if value["decisionId"] != expected_id:
            raise ValueError("prompt_promotion_decision_id_mismatch")
        if value["decision"] == "ELIGIBLE":
            if value["reasons"] != ["all_promotion_gates_passed"]:
                raise ValueError("prompt_promotion_eligible_reasons_invalid")
            if value["policyConfigHash"] not in self.authorized_policy_hashes:
                raise ValueError("prompt_promotion_policy_not_authorized")
        elif "all_promotion_gates_passed" in value["reasons"]:
            raise ValueError("prompt_promotion_rejected_reasons_invalid")
        with self._connect() as conn:
            experiment_row = conn.execute(
                "SELECT status, candidate_id, family_id, record_json FROM prompt_experiments_v3 WHERE experiment_id = ?",
                (value["experimentId"],),
            ).fetchone()
            if experiment_row is None:
                raise ValueError("prompt_promotion_experiment_not_found")
            if str(experiment_row["status"]) != "COMPLETE":
                raise ValueError("prompt_promotion_experiment_not_complete")
            if str(experiment_row["candidate_id"]) != value["candidateId"]:
                raise ValueError("prompt_promotion_candidate_mismatch")
            if str(experiment_row["family_id"]) != value["familyId"]:
                raise ValueError("prompt_promotion_family_mismatch")
            family_row = conn.execute(
                "SELECT status, holdout_experiment_id, record_json FROM prompt_candidate_families_v3 WHERE family_id = ?",
                (value["familyId"],),
            ).fetchone()
            if (
                family_row is None
                or str(family_row["status"]) != "COMPLETE"
                or str(family_row["holdout_experiment_id"]) != value["experimentId"]
            ):
                raise ValueError("prompt_promotion_family_not_complete")
            experiment = json.loads(str(experiment_row["record_json"]))
            split_row = conn.execute(
                "SELECT record_json FROM prompt_dataset_splits_v3 WHERE split_id = ?",
                (experiment["datasetSplitId"],),
            ).fetchone()
            if split_row is None:
                raise ValueError("prompt_promotion_split_not_found")
            family = json.loads(str(family_row["record_json"]))
            split = json.loads(str(split_row["record_json"]))
            runs = [
                json.loads(str(row["record_json"]))
                for row in conn.execute(
                    "SELECT record_json FROM prompt_experiment_runs_v3 WHERE experiment_id = ? ORDER BY run_id",
                    (value["experimentId"],),
                ).fetchall()
            ]
            evidence = {
                "experiment": experiment,
                "family": family,
                "split": split,
                "runs": runs,
                "policyConfigHash": value["policyConfigHash"],
            }
            if _canonical_hash(evidence) != value["evidenceHash"]:
                raise ValueError("prompt_promotion_evidence_hash_mismatch")
            existing = conn.execute(
                """
                SELECT record_json FROM prompt_promotion_decisions_v3
                WHERE decision_id = ? OR experiment_id = ?
                """,
                (value["decisionId"], value["experimentId"]),
            ).fetchone()
            if existing is not None:
                self._assert_idempotent(existing, value, value["decisionId"])
                return value
            conn.execute(
                """
                INSERT INTO prompt_promotion_decisions_v3 (
                    decision_id, experiment_id, candidate_id, decision,
                    policy_version, policy_config_hash, record_json, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["decisionId"],
                    value["experimentId"],
                    value["candidateId"],
                    value["decision"],
                    value["policyVersion"],
                    value["policyConfigHash"],
                    _canonical_json(value),
                    value["decidedAt"],
                ),
            )
        return value

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    "SELECT record_json FROM prompt_promotion_decisions_v3 WHERE decision_id = ?",
                    (decision_id,),
                ).fetchone()
            )

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
                return {"candidate": None, "experiment": None, "decision": None}
            experiment_row = conn.execute(
                """
                SELECT record_json FROM prompt_experiments_v3
                WHERE candidate_id = ? ORDER BY created_at DESC, experiment_id DESC LIMIT 1
                """,
                (candidate["candidateId"],),
            ).fetchone()
            experiment = self._load_json(experiment_row)
            decision = None
            if experiment is not None:
                decision = self._load_json(
                    conn.execute(
                        """
                        SELECT record_json FROM prompt_promotion_decisions_v3
                        WHERE experiment_id = ? LIMIT 1
                        """,
                        (experiment["experimentId"],),
                    ).fetchone()
                )
        return {"candidate": candidate, "experiment": experiment, "decision": decision}


__all__ = ["PromptOptimizerStore"]

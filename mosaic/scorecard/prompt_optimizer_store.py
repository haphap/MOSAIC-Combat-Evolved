"""Minimal persistence for Prompt Candidate experiments.

The TypeScript Zod contracts are the source of truth.  This module validates
against their generated JSON schemas and stores only public hashes, refs, and
metrics in the existing scorecard SQLite database.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from jsonschema import Draft7Validator, FormatChecker

from mosaic.scorecard.store import DEFAULT_DB_PATH


_SCHEMA_FILE_BY_VERSION = {
    "prompt_candidate_v1": "prompt_candidate_v1.schema.json",
    "prompt_experiment_v1": "prompt_experiment_v1.schema.json",
    "prompt_experiment_run_v1": "prompt_experiment_run_v1.schema.json",
    "prompt_promotion_decision_v1": "prompt_promotion_decision_v1.schema.json",
}

_DDL = """
CREATE TABLE IF NOT EXISTS prompt_candidates_v2 (
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

CREATE TABLE IF NOT EXISTS prompt_experiments_v2 (
    experiment_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES prompt_candidates_v2(candidate_id),
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

CREATE TABLE IF NOT EXISTS prompt_experiment_runs_v2 (
    run_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES prompt_experiments_v2(experiment_id),
    partition_name TEXT NOT NULL CHECK(partition_name IN ('VALIDATION', 'HOLDOUT')),
    side TEXT NOT NULL CHECK(side IN ('CHAMPION', 'CANDIDATE')),
    sample_id TEXT NOT NULL,
    seed INTEGER NOT NULL CHECK(seed >= 0),
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'RUNNING', 'COMPLETE', 'FAILED')),
    record_json TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(experiment_id, partition_name, side, sample_id, seed)
);

CREATE TABLE IF NOT EXISTS prompt_promotion_decisions_v2 (
    decision_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL UNIQUE REFERENCES prompt_experiments_v2(experiment_id),
    candidate_id TEXT NOT NULL REFERENCES prompt_candidates_v2(candidate_id),
    decision TEXT NOT NULL CHECK(decision IN ('ELIGIBLE', 'REJECTED')),
    policy_version TEXT NOT NULL,
    policy_config_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    decided_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompt_candidates_v2_target
    ON prompt_candidates_v2(cohort, agent_id, stage, created_at);
CREATE INDEX IF NOT EXISTS idx_prompt_experiments_v2_candidate
    ON prompt_experiments_v2(candidate_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prompt_runs_v2_experiment
    ON prompt_experiment_runs_v2(experiment_id, partition_name, status);
"""

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


class PromptOptimizerStore:
    """Transactional, idempotent storage for the four Prompt optimizer objects."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        schema_root: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.schema_root = (
            Path(schema_root)
            if schema_root is not None
            else Path(__file__).resolve().parents[2] / "schemas"
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
        target = value["target"]
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT record_json FROM prompt_candidates_v2 WHERE candidate_id = ?",
                (value["candidateId"],),
            ).fetchone()
            if existing is not None:
                self._assert_idempotent(existing, value, value["candidateId"])
                return value
            conn.execute(
                """
                INSERT INTO prompt_candidates_v2 (
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
                    "SELECT record_json FROM prompt_candidates_v2 WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
            )

    def put_experiment(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_experiment_v1", record)
        with self._connect() as conn:
            candidate_row = conn.execute(
                "SELECT record_json FROM prompt_candidates_v2 WHERE candidate_id = ?",
                (value["candidateId"],),
            ).fetchone()
            if candidate_row is None:
                raise ValueError("prompt_experiment_candidate_not_found")
            candidate = json.loads(str(candidate_row["record_json"]))
            if (
                candidate["target"] != value["target"]
                or candidate["promptHashes"] != value["candidatePromptHashes"]
            ):
                raise ValueError("prompt_experiment_candidate_mismatch")
            existing = conn.execute(
                "SELECT status, record_json FROM prompt_experiments_v2 WHERE experiment_id = ?",
                (value["experimentId"],),
            ).fetchone()
            if existing is not None:
                current = json.loads(str(existing["record_json"]))
                if current == value:
                    return value
                immutable = (
                    "candidateId",
                    "championId",
                    "target",
                    "championPromptHashes",
                    "candidatePromptHashes",
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
                conn.execute(
                    """
                    UPDATE prompt_experiments_v2
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
            conn.execute(
                """
                INSERT INTO prompt_experiments_v2 (
                    experiment_id, candidate_id, status, dataset_split_manifest_hash,
                    model_config_hash, tool_config_hash, evaluator_version,
                    evaluator_config_hash, code_commit, record_json, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["experimentId"],
                    value["candidateId"],
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

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_json(
                conn.execute(
                    "SELECT record_json FROM prompt_experiments_v2 WHERE experiment_id = ?",
                    (experiment_id,),
                ).fetchone()
            )

    def put_run(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_experiment_run_v1", record)
        with self._connect() as conn:
            experiment = conn.execute(
                "SELECT status, record_json FROM prompt_experiments_v2 WHERE experiment_id = ?",
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
                "SELECT status, record_json FROM prompt_experiment_runs_v2 WHERE run_id = ?",
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
                    UPDATE prompt_experiment_runs_v2
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
            conn.execute(
                """
                INSERT INTO prompt_experiment_runs_v2 (
                    run_id, experiment_id, partition_name, side, sample_id,
                    seed, status, record_json, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value["runId"],
                    value["experimentId"],
                    value["partition"],
                    value["side"],
                    value["sampleId"],
                    value["seed"],
                    value["status"],
                    _canonical_json(value),
                    value["completedAt"],
                ),
            )
        return value

    def list_runs(self, experiment_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT record_json FROM prompt_experiment_runs_v2
                WHERE experiment_id = ?
                ORDER BY partition_name, sample_id, seed, side
                """,
                (experiment_id,),
            ).fetchall()
        return [json.loads(str(row["record_json"])) for row in rows]

    def put_decision(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate("prompt_promotion_decision_v1", record)
        with self._connect() as conn:
            experiment_row = conn.execute(
                "SELECT status, candidate_id FROM prompt_experiments_v2 WHERE experiment_id = ?",
                (value["experimentId"],),
            ).fetchone()
            if experiment_row is None:
                raise ValueError("prompt_promotion_experiment_not_found")
            if str(experiment_row["status"]) != "COMPLETE":
                raise ValueError("prompt_promotion_experiment_not_complete")
            if str(experiment_row["candidate_id"]) != value["candidateId"]:
                raise ValueError("prompt_promotion_candidate_mismatch")
            existing = conn.execute(
                """
                SELECT record_json FROM prompt_promotion_decisions_v2
                WHERE decision_id = ? OR experiment_id = ?
                """,
                (value["decisionId"], value["experimentId"]),
            ).fetchone()
            if existing is not None:
                self._assert_idempotent(existing, value, value["decisionId"])
                return value
            conn.execute(
                """
                INSERT INTO prompt_promotion_decisions_v2 (
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
                    "SELECT record_json FROM prompt_promotion_decisions_v2 WHERE decision_id = ?",
                    (decision_id,),
                ).fetchone()
            )

    def latest_summary(self, cohort: str) -> dict[str, Any]:
        if not cohort.strip():
            raise ValueError("prompt_optimizer_cohort_required")
        with self._connect() as conn:
            candidate_row = conn.execute(
                """
                SELECT record_json FROM prompt_candidates_v2
                WHERE cohort = ? ORDER BY created_at DESC, candidate_id DESC LIMIT 1
                """,
                (cohort,),
            ).fetchone()
            candidate = self._load_json(candidate_row)
            if candidate is None:
                return {"candidate": None, "experiment": None, "decision": None}
            experiment_row = conn.execute(
                """
                SELECT record_json FROM prompt_experiments_v2
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
                        SELECT record_json FROM prompt_promotion_decisions_v2
                        WHERE experiment_id = ? LIMIT 1
                        """,
                        (experiment["experimentId"],),
                    ).fetchone()
                )
        return {"candidate": candidate, "experiment": experiment, "decision": decision}


__all__ = ["PromptOptimizerStore"]

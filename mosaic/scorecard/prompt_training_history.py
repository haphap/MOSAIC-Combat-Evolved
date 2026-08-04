"""PIT export of sealed Agent outcomes for the private Prompt optimizer.

This module deliberately knows nothing about private behavior-facet semantics.
It exports immutable accepted outputs, role-owned outcome metrics, Macro
component signals, and past validation-only experiment aggregates.  The
private KNOT package owns the facet projection and mutation decision.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from math import isclose
from typing import Any

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS


PROMPT_TRAINING_HISTORY_VERSION = "prompt_training_history_v1"
PROMPT_TRAINING_HISTORY_EXPORTER_VERSION = "prompt_training_history_exporter_v1"

_STAGE_BY_AGENT = {
    "cro": "cro_review",
    "alpha_discovery": "alpha_discovery",
    "autonomous_execution": "execution_feasibility",
    "cio": "cio_final",
}


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _as_of_timestamp(value: Any, cutoff: datetime) -> datetime:
    if isinstance(value, str) and len(value) == 10:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("accepted as_of must be an ISO date or timestamp") from exc
        return parsed.replace(tzinfo=cutoff.tzinfo)
    return _timestamp(value, "accepted as_of")


def _hashed_record(raw: str, hash_field: str, label: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    supplied = value.get(hash_field)
    if supplied != canonical_hash(
        {key: item for key, item in value.items() if key != hash_field}
    ):
        raise ValueError(f"{label} hash mismatch")
    return value


def _target_stage(agent_id: str) -> str:
    return _STAGE_BY_AGENT.get(agent_id, "agent_run")


def _component_signals(
    conn: sqlite3.Connection, accepted: Mapping[str, Any], agent_id: str
) -> list[dict[str, Any]]:
    accepted_output_id = str(accepted["accepted_output_id"])
    rows = conn.execute(
        "SELECT record_json FROM component_calibration_signals_v2 "
        "WHERE accepted_output_id = ? ORDER BY component",
        (accepted_output_id,),
    ).fetchall()
    signals = [
        _hashed_record(row[0], "component_calibration_signal_hash", "component signal")
        for row in rows
    ]
    if any(
        signal.get("accepted_output_id") != accepted_output_id
        or signal.get("agent_id") != agent_id
        or signal.get("accepted_output_hash") != accepted.get("accepted_output_hash")
        or signal.get("scheduled_sample_id") != accepted.get("scheduled_sample_id")
        or signal.get("prompt_behavior_version")
        != accepted.get("prompt_behavior_version")
        or signal.get("as_of") != accepted.get("as_of")
        or signal.get("calibration_sample_role")
        not in {"FIT_REFERENCE", "CROSS_VARIANT_DIAGNOSTIC"}
        for signal in signals
    ):
        raise ValueError("component signal ownership mismatch")
    expected = OUTCOME_CONTRACTS[agent_id].get("component_composition_contract")
    expected_components = (
        set(expected.get("components", {})) if isinstance(expected, Mapping) else set()
    )
    if expected_components != {str(signal.get("component")) for signal in signals}:
        raise ValueError("component signal coverage mismatch")
    for signal in signals:
        component_signal = signal.get("signal")
        confidence = signal.get("effective_confidence")
        if (
            isinstance(component_signal, bool)
            or not isinstance(component_signal, (int, float))
            or not -1 <= component_signal <= 1
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError("component signal value is invalid")
    return [
        {
            "component": str(signal["component"]),
            "signal": float(signal["signal"]),
            "effective_confidence": float(signal["effective_confidence"]),
        }
        for signal in signals
    ]


def _cio_proposal(
    conn: sqlite3.Connection, accepted: Mapping[str, Any]
) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT record_json FROM accepted_agent_outputs_v2 "
        "WHERE graph_run_id = ? AND cohort_id = ? AND language = ? "
        "AND agent_id = 'cio' AND accepted_output_kind = 'CIO_PROPOSAL' "
        "AND sample_origin = 'PRODUCTION_ACTIVE'",
        (
            accepted.get("graph_run_id"),
            accepted.get("cohort_id"),
            accepted.get("language"),
        ),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("CIO training history requires one same-run proposal")
    proposal = _hashed_record(rows[0][0], "accepted_output_hash", "CIO proposal")
    shared_fields = (
        "graph_run_id",
        "run_slot_id",
        "operational_opportunity_audit_id",
        "production_variant_roster_id",
        "production_variant_roster_revision_id",
        "execution_behavior_release_id",
        "cohort_id",
        "language",
        "track_key_hash",
        "prompt_behavior_version",
        "execution_behavior_version",
        "as_of",
    )
    if (
        proposal.get("agent_id") != "cio"
        or proposal.get("accepted_output_kind") != "CIO_PROPOSAL"
        or proposal.get("sample_origin") != "PRODUCTION_ACTIVE"
        or any(proposal.get(field) != accepted.get(field) for field in shared_fields)
    ):
        raise ValueError("CIO proposal/final behavior binding mismatch")
    return {
        "agentOutputRef": str(proposal["accepted_output_id"]),
        "agentOutputHash": str(proposal["accepted_output_hash"]),
    }


def _validation_experiments(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    stage: str,
    cohort: str,
    cutoff: datetime,
    excluded_sample_ids: set[str],
) -> list[dict[str, Any]]:
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'prompt_experiments_v3'"
    ).fetchone()
    if table is None:
        return []
    rows = conn.execute(
        "SELECT e.record_json, c.record_json "
        "FROM prompt_experiments_v3 e "
        "JOIN prompt_candidates_v3 c ON c.candidate_id = e.candidate_id "
        "WHERE c.agent_id = ? AND c.stage = ? AND c.cohort = ? "
        "AND e.status IN ('VALIDATION_COMPLETE', 'HOLDOUT_RUNNING', 'COMPLETE') "
        "ORDER BY e.created_at, e.experiment_id",
        (agent_id, stage, cohort),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for experiment_raw, candidate_raw in rows:
        experiment = json.loads(experiment_raw)
        candidate = json.loads(candidate_raw)
        if not isinstance(experiment, dict) or not isinstance(candidate, dict):
            raise ValueError("Prompt experiment history must contain objects")
        target = {"agentId": agent_id, "stage": stage, "cohort": cohort}
        if (
            experiment.get("candidateId") != candidate.get("candidateId")
            or experiment.get("target") != target
            or candidate.get("target") != target
        ):
            raise ValueError("Prompt experiment history ownership mismatch")
        metrics = experiment.get("metrics")
        if not isinstance(metrics, Mapping):
            raise ValueError("Prompt experiment validation metrics are unavailable")
        validation_keys = {
            "validation_candidate_mean",
            "validation_champion_mean",
            "validation_paired_delta",
            "validation_pair_count",
        }
        if not validation_keys.issubset(metrics):
            raise ValueError("Prompt experiment validation aggregate is incomplete")
        run_rows = conn.execute(
            "SELECT record_json FROM prompt_experiment_runs_v3 "
            "WHERE experiment_id = ? AND partition_name = 'VALIDATION' "
            "ORDER BY sample_id, seed, side",
            (experiment.get("experimentId"),),
        ).fetchall()
        runs = [json.loads(row[0]) for row in run_rows]
        if not runs or any(
            not isinstance(run, dict)
            or run.get("status") != "COMPLETE"
            or run.get("partition") != "VALIDATION"
            or run.get("experimentId") != experiment.get("experimentId")
            for run in runs
        ):
            raise ValueError("Prompt validation run history is incomplete")
        if any(str(run.get("sampleId")) in excluded_sample_ids for run in runs):
            continue
        completed = [
            _timestamp(run.get("completedAt"), "validation completedAt") for run in runs
        ]
        if max(completed) > cutoff:
            continue
        pair_keys = {(str(run["sampleId"]), int(run["seed"])) for run in runs}
        if len(runs) != len(pair_keys) * 2 or int(
            metrics["validation_pair_count"]
        ) != len(pair_keys):
            raise ValueError("Prompt validation pair cardinality mismatch")
        pairs: dict[tuple[str, int], dict[str, float]] = {}
        for run in runs:
            score = run.get("metrics", {}).get("normalized_score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ValueError("Prompt validation run normalized score is invalid")
            pair = pairs.setdefault((str(run["sampleId"]), int(run["seed"])), {})
            side = str(run["side"])
            if side in pair or side not in {"CHAMPION", "CANDIDATE"}:
                raise ValueError("Prompt validation pair side is invalid")
            pair[side] = float(score)
        pair_deltas = [
            pair["CANDIDATE"] - pair["CHAMPION"]
            for _, pair in sorted(pairs.items())
            if set(pair) == {"CHAMPION", "CANDIDATE"}
        ]
        if len(pair_deltas) != len(pair_keys):
            raise ValueError("Prompt validation pair is incomplete")
        candidate_mean = sum(pair["CANDIDATE"] for pair in pairs.values()) / len(
            pairs
        )
        champion_mean = sum(pair["CHAMPION"] for pair in pairs.values()) / len(pairs)
        paired_delta = sum(pair_deltas) / len(pair_deltas)
        stored_aggregates = (
            metrics["validation_candidate_mean"],
            metrics["validation_champion_mean"],
            metrics["validation_paired_delta"],
        )
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in stored_aggregates
        ) or not all(
            isclose(float(stored), computed, rel_tol=0.0, abs_tol=1e-12)
            for stored, computed in zip(
                stored_aggregates,
                (candidate_mean, champion_mean, paired_delta),
                strict=True,
            )
        ):
            raise ValueError("Prompt validation aggregate mismatch")
        result.append(
            {
                "candidateId": str(experiment["candidateId"]),
                "candidatePrivateLineageHash": str(candidate["privateLineageHash"]),
                "experimentId": str(experiment["experimentId"]),
                "evaluatorVersion": str(experiment["evaluatorVersion"]),
                "evaluatorConfigHash": str(experiment["evaluatorConfigHash"]),
                "codeCommit": str(experiment["codeCommit"]),
                "validationPairCount": int(metrics["validation_pair_count"]),
                "validationCandidateMean": candidate_mean,
                "validationChampionMean": champion_mean,
                "validationPairedDelta": paired_delta,
                "validationPairDeltas": pair_deltas,
                "validationFailureCaseRefs": sorted(
                    {str(ref) for run in runs for ref in run.get("failureCaseRefs", [])}
                ),
                "validationCompletedAt": max(completed).isoformat(),
            }
        )
    return result


def build_prompt_training_history(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    stage: str,
    cohort: str,
    cutoff_at: str,
    excluded_sample_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Export training-only sealed history for one private Prompt target."""
    contract = OUTCOME_CONTRACTS.get(agent_id)
    if contract is None:
        raise ValueError("unknown Prompt training Agent")
    if stage != _target_stage(agent_id):
        raise ValueError("Prompt training stage does not belong to Agent")
    if not isinstance(cohort, str) or not cohort.startswith("cohort_"):
        raise ValueError("Prompt training cohort is invalid")
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    exclusions = list(excluded_sample_ids)
    if any(not isinstance(value, str) or not value.strip() for value in exclusions):
        raise ValueError("excluded sample IDs must be non-empty strings")
    if len(exclusions) != len(set(exclusions)):
        raise ValueError("excluded sample IDs must be unique")
    excluded = set(exclusions)
    rows = conn.execute(
        "SELECT l.record_json, a.record_json, o.record_json "
        "FROM agent_outcome_labels_v2 l "
        "JOIN agent_outcome_eligibility_revisions_v2 a "
        "ON a.audit_revision_id = l.audit_revision_id "
        "JOIN accepted_agent_outputs_v2 o "
        "ON o.accepted_output_id = a.accepted_output_id "
        "WHERE l.agent_id = ? AND o.cohort_id = ? "
        "AND l.sample_origin = 'PRODUCTION_ACTIVE' "
        "AND l.darwin_evaluation_eligible = 1 "
        "ORDER BY l.outcome_sequence",
        (agent_id, cohort),
    ).fetchall()
    records: list[dict[str, Any]] = []
    seen_samples: set[str] = set()
    for label_raw, audit_raw, accepted_raw in rows:
        label = _hashed_record(label_raw, "outcome_label_hash", "outcome label")
        audit = _hashed_record(audit_raw, "audit_revision_hash", "outcome eligibility")
        accepted = _hashed_record(
            accepted_raw, "accepted_output_hash", "accepted output"
        )
        sample_id = str(label.get("scheduled_sample_id") or "")
        if sample_id in excluded:
            continue
        if not sample_id or sample_id in seen_samples:
            raise ValueError("Prompt training sample identity is invalid")
        seen_samples.add(sample_id)
        if (
            label.get("audit_revision_id") != audit.get("audit_revision_id")
            or label.get("audit_revision_hash") != audit.get("audit_revision_hash")
            or audit.get("accepted_output_id") != accepted.get("accepted_output_id")
            or audit.get("accepted_output_hash") != accepted.get("accepted_output_hash")
            or label.get("agent_id") != agent_id
            or audit.get("agent_id") != agent_id
            or accepted.get("agent_id") != agent_id
            or label.get("scheduled_sample_id") != audit.get("scheduled_sample_id")
            or label.get("scheduled_sample_id") != accepted.get("scheduled_sample_id")
            or label.get("track_key_hash") != accepted.get("track_key_hash")
            or audit.get("track_key_hash") != accepted.get("track_key_hash")
            or accepted.get("accepted_output_kind") != contract["accepted_output_kind"]
            or label.get("primary_label_id") != contract["primary_label_id"]
            or label.get("sample_origin") != "PRODUCTION_ACTIVE"
            or audit.get("sample_origin") != "PRODUCTION_ACTIVE"
            or accepted.get("sample_origin") != "PRODUCTION_ACTIVE"
            or accepted.get("cohort_id") != cohort
            or audit.get("disposition") != "SCORE"
            or audit.get("darwin_evaluation_eligible") is not True
            or label.get("darwin_evaluation_eligible") is not True
        ):
            raise ValueError("Prompt training history lineage mismatch")
        matured = _timestamp(label.get("matured_at"), "matured_at")
        as_of = _as_of_timestamp(accepted.get("as_of"), cutoff)
        if as_of > matured:
            raise ValueError("Prompt training outcome precedes its accepted output")
        if matured > cutoff:
            continue
        versions = label.get("contract_versions")
        audit_versions = audit.get("contract_versions")
        if (
            not isinstance(versions, Mapping)
            or versions.get("outcome_contract_version")
            != contract["outcome_contract_version"]
            or not isinstance(audit_versions, Mapping)
            or audit_versions.get("outcome_contract_version")
            != contract["outcome_contract_version"]
        ):
            raise ValueError("Prompt training outcome contract drift")
        raw_metrics = label.get("raw_metrics")
        if not isinstance(raw_metrics, Mapping):
            raise ValueError("Prompt training raw metrics are unavailable")
        normalized_score = label.get("normalized_score")
        if (
            isinstance(normalized_score, bool)
            or not isinstance(normalized_score, (int, float))
            or not -1 <= normalized_score <= 1
        ):
            raise ValueError("Prompt training normalized score is invalid")
        prompt_behavior_version = accepted.get("prompt_behavior_version")
        if not isinstance(prompt_behavior_version, str) or not prompt_behavior_version:
            raise ValueError("Prompt training behavior version is unavailable")
        record = {
            "sampleId": sample_id,
            "agentOutputRef": str(accepted["accepted_output_id"]),
            "agentOutputHash": str(accepted["accepted_output_hash"]),
            "outcomeLabelRef": str(label["outcome_label_id"]),
            "outcomeLabelHash": str(label["outcome_label_hash"]),
            "asOf": str(accepted["as_of"]),
            "maturedAt": str(label["matured_at"]),
            "promptBehaviorVersion": prompt_behavior_version,
            "normalizedScore": float(normalized_score),
            "rawMetrics": dict(raw_metrics),
            "componentSignals": _component_signals(conn, accepted, agent_id),
            "supportingAcceptedOutputs": {},
        }
        if agent_id == "cio":
            record["supportingAcceptedOutputs"] = {
                "cioProposal": _cio_proposal(conn, accepted)
            }
        records.append(record)
    experiments = _validation_experiments(
        conn,
        agent_id=agent_id,
        stage=stage,
        cohort=cohort,
        cutoff=cutoff,
        excluded_sample_ids=excluded,
    )
    without_hash = {
        "schemaVersion": PROMPT_TRAINING_HISTORY_VERSION,
        "exporterVersion": PROMPT_TRAINING_HISTORY_EXPORTER_VERSION,
        "target": {"agentId": agent_id, "stage": stage, "cohort": cohort},
        "cutoffAt": cutoff_at,
        "outcomeContractVersion": str(contract["outcome_contract_version"]),
        "metricFamily": str(contract["metric_family"]),
        "primaryLabelId": str(contract["primary_label_id"]),
        "excludedSampleIds": sorted(excluded),
        "records": records,
        "validationExperiments": experiments,
    }
    return {**without_hash, "historyHash": canonical_hash(without_hash)}


__all__ = [
    "PROMPT_TRAINING_HISTORY_EXPORTER_VERSION",
    "PROMPT_TRAINING_HISTORY_VERSION",
    "build_prompt_training_history",
]

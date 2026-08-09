"""Build the public PIT evaluation projection consumed by Prompt optimization.

Raw accepted outputs and component signals remain internal to this builder.
Only opaque role aggregates and past validation-only experiment metadata cross
the bridge; private KNOT owns facet semantics and mutation decisions.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from math import isclose, isfinite
from pathlib import Path
from typing import Any

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS


PROMPT_TRAINING_PROJECTION_VERSION = "prompt_training_projection_v1"
PROMPT_TRAINING_PROJECTION_V2_VERSION = "prompt_training_projection_v2"
PROMPT_ROLE_COMPONENT_EVALUATOR_VERSION = "prompt_role_component_evaluator_v1"
MATURE_SAMPLE_ELIGIBILITY_VERSION = "mature_sample_eligibility_v1"

_STAGE_BY_AGENT = {
    "cro": "cro_review",
    "alpha_discovery": "alpha_discovery",
    "autonomous_execution": "execution_feasibility",
    "cio": "cio_final",
}

# Public, role-owned outcome components.  The ordinal is stable and is the only
# identity exported to the private Prompt optimizer.  Selectors below refer to
# public outcome/calibration fields; they are never included in the projection.
_SECTOR_AGENTS = {
    "semiconductor",
    "technology",
    "energy",
    "biotech",
    "consumer",
    "industrials",
    "real_estate_construction",
    "financials",
    "agriculture",
}
_ROLE_COMPONENT_SPECS: dict[str, tuple[tuple[int, str, str | None], ...]] = {
    "china": (
        (0, "MACRO_COMPONENT", "growth_production"),
        (1, "MACRO_COMPONENT", "prices"),
        (2, "MACRO_COMPONENT", "credit"),
        (3, "MACRO_COMPONENT", "external_demand_trade"),
        (4, "MACRO_COMPONENT", "fiscal"),
        (5, "NORMALIZED_SCORE", None),
    ),
    "us_economy": (
        (0, "MACRO_COMPONENT", "growth_production"),
        (1, "MACRO_COMPONENT", "prices"),
        (2, "MACRO_COMPONENT", "employment"),
        (3, "MACRO_COMPONENT", "demand_trade"),
        (4, "NORMALIZED_SCORE", None),
    ),
    "eu_economy": (
        (0, "MACRO_COMPONENT", "growth_production"),
        (1, "MACRO_COMPONENT", "prices"),
        (2, "MACRO_COMPONENT", "employment"),
        (3, "MACRO_COMPONENT", "demand_trade"),
        (4, "NORMALIZED_SCORE", None),
    ),
    "central_bank": (
        (0, "MACRO_COMPONENT", "pboc_policy_bias"),
        (1, "MACRO_COMPONENT", "liquidity_money_market"),
        (2, "MACRO_COMPONENT", "china_curve"),
        (3, "MACRO_COMPONENT", "credit_conditions"),
        (4, "NORMALIZED_SCORE", None),
    ),
    "us_financial_conditions": (
        (0, "MACRO_COMPONENT", "fed_liquidity"),
        (1, "MACRO_COMPONENT", "us_curve"),
        (2, "MACRO_COMPONENT", "credit_financial_stress"),
        (3, "MACRO_COMPONENT", "usd_rmb"),
        (4, "NORMALIZED_SCORE", None),
    ),
    "euro_area_financial_conditions": (
        (0, "MACRO_COMPONENT", "ecb_liquidity"),
        (1, "MACRO_COMPONENT", "euro_area_curve"),
        (2, "MACRO_COMPONENT", "bank_credit"),
        (3, "MACRO_COMPONENT", "eur_financial_stress"),
        (4, "NORMALIZED_SCORE", None),
    ),
    "commodities": (
        (0, "MACRO_COMPONENT", "energy"),
        (1, "MACRO_COMPONENT", "industrial_metals"),
        (2, "MACRO_COMPONENT", "gold"),
        (3, "MACRO_COMPONENT", "agriculture_food"),
        (4, "NORMALIZED_SCORE", None),
    ),
    "geopolitical": ((5, "NORMALIZED_SCORE", None),),
    "market_breadth": ((5, "NORMALIZED_SCORE", None),),
    "institutional_flow": ((5, "NORMALIZED_SCORE", None),),
    "relationship_mapper": (
        (1, "EDGE_MEAN", "edge_utility_delta"),
        (2, "EDGE_MEAN", "activation_direction_brier_skill"),
        (4, "EDGE_MEAN", "path_lift_utility_delta"),
    ),
    "druckenmiller": ((4, "NORMALIZED_SCORE", None),),
    "munger": ((4, "NORMALIZED_SCORE", None),),
    "burry": ((4, "NORMALIZED_SCORE", None),),
    "ackman": ((4, "NORMALIZED_SCORE", None),),
    "cro": (
        (0, "DECISION_COMPONENT", "RECALL"),
        (1, "DECISION_COMPONENT", "PRECISION"),
        (4, "DECISION_COMPONENT", "SPECIFICITY"),
    ),
    "alpha_discovery": (
        (2, "DECISION_COMPONENT", "INCREMENTAL_OPPORTUNITY_UTILITY"),
        (3, "DECISION_COMPONENT", "SELECTED_PICK_UTILITY"),
        (4, "ALPHA_ABSTENTION", None),
    ),
    "autonomous_execution": (
        (0, "DECISION_COMPONENT", "FEASIBILITY"),
        (1, "DECISION_COMPONENT", "COST_ERROR"),
        (2, "DECISION_COMPONENT", "TARGET_DELTA"),
        (4, "DECISION_COMPONENT", "POLICY_COMPLIANCE"),
    ),
    "cio": (
        (3, "DECISION_COMPONENT", "CONSTRAINT_COMPLIANCE"),
        (4, "NORMALIZED_SCORE", None),
    ),
}
for _sector_agent in _SECTOR_AGENTS:
    _ROLE_COMPONENT_SPECS[_sector_agent] = (
        (2, "SECTOR_DIRECTION", "PREFERRED"),
        (3, "SECTOR_DIRECTION", "LEAST_PREFERRED"),
        (4, "SECTOR_LEG", "PREFERRED"),
        (5, "SECTOR_LEG", "LEAST_PREFERRED"),
    )


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


def _format_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _object_rows(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise ValueError(f"{label} must be an array of objects")
    return list(value)


def _clip_score(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _mean(values: Sequence[float], label: str) -> float:
    if not values:
        raise ValueError(f"{label} must not be empty")
    return sum(values) / len(values)


def _lower_tail(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return _mean(ordered[: max(1, (len(ordered) + 9) // 10)], "lower tail")


def _failure_counts(values: Sequence[float]) -> dict[str, int]:
    return {
        key: count
        for key, count in (
            ("facet_underperformed", sum(value < -0.2 for value in values)),
            ("facet_lower_tail_failure", sum(value < -0.6 for value in values)),
        )
        if count
    }


def _role_component_ref(agent_id: str, ordinal: int) -> str:
    return f"role_component_v1:{agent_id}:{ordinal:03d}"


def prompt_role_component_refs(agent_id: str) -> tuple[str, ...]:
    """Return the exact public role-component roster owned by an Agent."""

    try:
        specs = _ROLE_COMPONENT_SPECS[agent_id]
    except KeyError as exc:
        raise ValueError(f"unknown Prompt role component Agent: {agent_id}") from exc
    return tuple(_role_component_ref(agent_id, ordinal) for ordinal, _, _ in specs)


def _validate_role_component_specs() -> None:
    if set(_ROLE_COMPONENT_SPECS) != set(OUTCOME_CONTRACTS):
        raise ValueError("Prompt role component contract must cover all 28 Agents")
    for agent_id, specs in _ROLE_COMPONENT_SPECS.items():
        ordinals = [ordinal for ordinal, _, _ in specs]
        if not specs or len(ordinals) != len(set(ordinals)) or ordinals != sorted(ordinals):
            raise ValueError(f"Prompt role component ordinals are invalid for {agent_id}")
        composition = OUTCOME_CONTRACTS[agent_id].get("component_composition_contract")
        public_components = {
            str(selector)
            for _, scorer, selector in specs
            if scorer == "MACRO_COMPONENT"
        }
        expected_components = (
            set(composition.get("components", {}))
            if isinstance(composition, Mapping)
            else set()
        )
        if public_components != expected_components:
            raise ValueError(f"Prompt role component source coverage drift for {agent_id}")


def _component_utility(raw_metrics: Mapping[str, Any], component_id: str) -> float:
    component = next(
        (
            row
            for row in _object_rows(raw_metrics.get("components"), "decision components")
            if row.get("component_id") == component_id
        ),
        None,
    )
    if component is None:
        raise ValueError(f"decision component missing: {component_id}")
    return _clip_score(
        _finite_number(component.get("utility_delta"), "decision component utility")
    )


def _sector_direction_score(raw_metrics: Mapping[str, Any], role: str) -> float:
    metric = next(
        (
            row
            for row in _object_rows(raw_metrics.get("direction_metrics"), "direction metrics")
            if row.get("selected_role") == role
        ),
        None,
    )
    if metric is None:
        raise ValueError(f"sector direction metric missing: {role}")
    actual = _finite_number(metric.get("realized_scaled_path"), "sector direction actual")
    predicted = _finite_number(metric.get("predicted_tilt"), "sector direction prediction")
    return _clip_score(actual**2 - (predicted - actual) ** 2)


def _sector_leg_score(raw_metrics: Mapping[str, Any], side: str) -> float:
    metric = next(
        (
            row
            for row in _object_rows(
                raw_metrics.get("security_leg_metrics"), "security leg metrics"
            )
            if row.get("side") == side
        ),
        None,
    )
    if metric is None:
        raise ValueError(f"sector security leg missing: {side}")
    return _clip_score(
        _finite_number(
            metric.get("side_security_utility_delta"), "sector security leg utility"
        )
    )


def _score_role_component(
    record: Mapping[str, Any], scorer: str, selector: str | None
) -> float:
    raw_metrics = record.get("rawMetrics")
    if not isinstance(raw_metrics, Mapping):
        raise ValueError("Prompt role component raw metrics are unavailable")
    if scorer == "NORMALIZED_SCORE":
        return _clip_score(
            _finite_number(record.get("normalizedScore"), "normalized score")
        )
    if scorer == "MACRO_COMPONENT":
        signal = next(
            (
                row
                for row in _object_rows(
                    record.get("componentSignals"), "component signals"
                )
                if row.get("component") == selector
            ),
            None,
        )
        if signal is None:
            raise ValueError(f"macro component signal missing: {selector}")
        actual = _finite_number(
            raw_metrics.get("realized_scaled_path"), "macro realized path"
        )
        prediction = _finite_number(signal.get("signal"), "macro component signal") * _finite_number(
            signal.get("effective_confidence"), "macro component confidence"
        )
        return _clip_score(actual**2 - (prediction - actual) ** 2)
    if scorer == "SECTOR_DIRECTION" and selector is not None:
        return _sector_direction_score(raw_metrics, selector)
    if scorer == "SECTOR_LEG" and selector is not None:
        return _sector_leg_score(raw_metrics, selector)
    if scorer == "EDGE_MEAN" and selector is not None:
        values = [
            _finite_number(row.get(selector), f"relationship edge {selector}")
            for row in _object_rows(raw_metrics.get("edge_metrics"), "edge metrics")
        ]
        return _clip_score(_mean(values, "relationship edge metrics"))
    if scorer == "DECISION_COMPONENT" and selector is not None:
        return _component_utility(raw_metrics, selector)
    if scorer == "ALPHA_ABSTENTION":
        return _clip_score(
            _finite_number(raw_metrics.get("output_confidence_null_loss"), "alpha null loss")
            - _finite_number(
                raw_metrics.get("output_confidence_forecast_loss"), "alpha forecast loss"
            )
        )
    raise ValueError(f"unsupported Prompt role component scorer: {scorer}")


def _build_direct_components(
    agent_id: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for ordinal, scorer, selector in _ROLE_COMPONENT_SPECS[agent_id]:
        scores = [_score_role_component(record, scorer, selector) for record in records]
        result.append(
            {
                "componentRef": _role_component_ref(agent_id, ordinal),
                "directMatureSampleCount": len(scores),
                "meanScore": _mean(scores, "role component scores") if scores else None,
                "lowerTailScore": _lower_tail(scores) if scores else None,
                "failureCategoryCounts": _failure_counts(scores),
            }
        )
    return result


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
            "componentSignalHash": str(signal["component_calibration_signal_hash"]),
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
        "AND e.status = 'COMPLETE' "
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
        private_lineage_hash = candidate.get("privateLineageHash")
        if (
            experiment.get("candidateId") != candidate.get("candidateId")
            or experiment.get("target") != target
            or candidate.get("target") != target
            or experiment.get("status") != "COMPLETE"
            or not isinstance(private_lineage_hash, str)
            or len(private_lineage_hash) != 71
            or not private_lineage_hash.startswith("sha256:")
            or any(
                character not in "0123456789abcdef"
                for character in private_lineage_hash[7:]
            )
        ):
            raise ValueError("Prompt experiment history ownership mismatch")
        completed_at = _timestamp(
            experiment.get("completedAt"), "Prompt experiment completedAt"
        )
        if completed_at > cutoff:
            continue
        evaluator_version = experiment.get("evaluatorVersion")
        code_commit = experiment.get("codeCommit")
        frozen_hash_fields = {
            "evaluatorConfigHash": experiment.get("evaluatorConfigHash"),
            "executorAdapterHash": experiment.get("executorAdapterHash"),
            "evaluatorAdapterHash": experiment.get("evaluatorAdapterHash"),
        }
        if (
            not isinstance(evaluator_version, str)
            or not evaluator_version.strip()
            or not isinstance(code_commit, str)
            or len(code_commit) != 40
            or any(character not in "0123456789abcdef" for character in code_commit)
            or any(
                not isinstance(value, str)
                or len(value) != 71
                or not value.startswith("sha256:")
                or any(character not in "0123456789abcdef" for character in value[7:])
                for value in frozen_hash_fields.values()
            )
        ):
            raise ValueError("Prompt experiment frozen environment is invalid")
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
        pair_count = metrics["validation_pair_count"]
        if (
            isinstance(pair_count, bool)
            or not isinstance(pair_count, int)
            or pair_count <= 0
            or len(runs) != len(pair_keys) * 2
            or pair_count != len(pair_keys)
        ):
            raise ValueError("Prompt validation pair cardinality mismatch")
        pairs: dict[tuple[str, int], dict[str, float]] = {}
        for run in runs:
            run_metrics = run.get("metrics")
            if not isinstance(run_metrics, Mapping):
                raise ValueError("Prompt validation run normalized score is invalid")
            score = _finite_number(
                run_metrics.get("normalized_score"),
                "Prompt validation run normalized score",
            )
            if not -1 <= score <= 1:
                raise ValueError("Prompt validation run normalized score is invalid")
            failure_refs = run.get("failureCaseRefs")
            if (
                not isinstance(failure_refs, list)
                or any(
                    not isinstance(ref, str) or not ref.strip() or "\n" in ref or "\r" in ref
                    for ref in failure_refs
                )
            ):
                raise ValueError("Prompt validation failure refs are invalid")
            pair = pairs.setdefault((str(run["sampleId"]), int(run["seed"])), {})
            side = str(run["side"])
            if side in pair or side not in {"CHAMPION", "CANDIDATE"}:
                raise ValueError("Prompt validation pair side is invalid")
            pair[side] = score
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
                "candidatePrivateLineageHash": private_lineage_hash,
                "experimentId": str(experiment["experimentId"]),
                "status": "COMPLETE",
                "evaluatorVersion": evaluator_version,
                "evaluatorConfigHash": str(frozen_hash_fields["evaluatorConfigHash"]),
                "executorAdapterHash": str(frozen_hash_fields["executorAdapterHash"]),
                "evaluatorAdapterHash": str(frozen_hash_fields["evaluatorAdapterHash"]),
                "codeCommit": code_commit,
                "pairDeltas": pair_deltas,
                "failureCaseRefs": sorted(
                    {str(ref) for run in runs for ref in run.get("failureCaseRefs", [])}
                ),
                "completedAt": _format_timestamp(completed_at),
            }
        )
    return result


def _collect_prompt_training_inputs(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    stage: str,
    cohort: str,
    cutoff_at: str,
    excluded_sample_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Collect sealed inputs for the public projection; never export this shape."""
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
        roster_revision_id = accepted.get("production_variant_roster_revision_id")
        if not isinstance(roster_revision_id, str) or not roster_revision_id:
            raise ValueError("Prompt training production roster revision is unavailable")
        record = {
            "sampleId": sample_id,
            "agentOutputRef": str(accepted["accepted_output_id"]),
            "agentOutputHash": str(accepted["accepted_output_hash"]),
            "outcomeLabelRef": str(label["outcome_label_id"]),
            "outcomeLabelHash": str(label["outcome_label_hash"]),
            "asOf": str(accepted["as_of"]),
            "maturedAt": str(label["matured_at"]),
            "promptBehaviorVersion": prompt_behavior_version,
            "productionVariantRosterRevisionId": roster_revision_id,
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
    return {
        "target": {"agentId": agent_id, "stage": stage, "cohort": cohort},
        "cutoffAt": cutoff_at,
        "excludedSampleIds": sorted(excluded),
        "records": records,
        "validationExperiments": experiments,
    }


def _source_hash(path: str) -> str:
    body = (Path(__file__).resolve().parent / path).read_bytes()
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _maturity_trading_days(horizon: str) -> int:
    if horizon == "T1_CLOSE":
        return 1
    prefix = "TRADING_DAYS_"
    if horizon.startswith(prefix) and horizon[len(prefix) :].isdigit():
        return int(horizon[len(prefix) :])
    raise ValueError("Prompt training maturity horizon is unsupported")


def build_prompt_training_projection(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    stage: str,
    cohort: str,
    cutoff_at: str,
    excluded_sample_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Freeze public role-owned outcomes without exposing private facet semantics."""
    _validate_role_component_specs()
    source = _collect_prompt_training_inputs(
        conn,
        agent_id=agent_id,
        stage=stage,
        cohort=cohort,
        cutoff_at=cutoff_at,
        excluded_sample_ids=excluded_sample_ids,
    )
    contract = OUTCOME_CONTRACTS[agent_id]
    records = source["records"]
    scores = [float(record["normalizedScore"]) for record in records]
    lower_tail = _lower_tail(scores) if scores else None
    mean_score = _mean(scores, "normalized scores") if scores else None
    dataset_snapshot = [
        {
            "sampleId": record["sampleId"],
            "agentOutputHash": record["agentOutputHash"],
            "outcomeLabelHash": record["outcomeLabelHash"],
            "componentSignalHashes": sorted(
                str(signal["componentSignalHash"])
                for signal in record["componentSignals"]
            ),
            "supportingAcceptedOutputHashes": sorted(
                str(value["agentOutputHash"])
                for value in record["supportingAcceptedOutputs"].values()
            ),
            "maturedAt": record["maturedAt"],
        }
        for record in records
    ]
    executor_adapter_hash = _source_hash("outcome_metric_derivation.py")
    evaluator_adapter_hash = _source_hash("prompt_training_history.py")
    role_component_contract_hash = canonical_hash(
        [
            {"ordinal": ordinal, "scorer": scorer, "selector": selector}
            for ordinal, scorer, selector in _ROLE_COMPONENT_SPECS[agent_id]
        ]
    )
    evaluator_config_hash = canonical_hash(
        {
            "evaluatorVersion": PROMPT_ROLE_COMPONENT_EVALUATOR_VERSION,
            "evaluationObject": contract["evaluation_object"],
            "primaryLabelId": contract["primary_label_id"],
            "scoringContractVersion": contract["scoring_contract_version"],
            "outcomeContractVersion": contract["outcome_contract_version"],
            "roleComponentContractHash": role_component_contract_hash,
        }
    )
    target = source["target"]
    without_hash = {
        "schemaVersion": PROMPT_TRAINING_PROJECTION_VERSION,
        "target": target,
        "projectionId": "projection-"
        + canonical_hash(
            {
                "target": target,
                "cutoffAt": cutoff_at,
                "datasetSnapshot": dataset_snapshot,
                "excludedSampleIds": source["excludedSampleIds"],
            }
        )[len("sha256:") : len("sha256:") + 24],
        "datasetSnapshotHash": canonical_hash(dataset_snapshot),
        "excludedSampleIdsHash": canonical_hash(source["excludedSampleIds"]),
        "cutoffAt": cutoff_at,
        "outcomeContract": {
            "evaluationObject": str(contract["evaluation_object"]),
            "outcomeContractVersion": str(contract["outcome_contract_version"]),
            "primaryLabelId": str(contract["primary_label_id"]),
            "maturityHorizon": str(contract["maturity_horizon"]),
            "maturityTradingDays": _maturity_trading_days(
                str(contract["maturity_horizon"])
            ),
        },
        "evaluator": {
            "version": PROMPT_ROLE_COMPONENT_EVALUATOR_VERSION,
            "configHash": evaluator_config_hash,
            "implementationHash": canonical_hash(
                {
                    "executorAdapterHash": executor_adapter_hash,
                    "evaluatorAdapterHash": evaluator_adapter_hash,
                    "configHash": evaluator_config_hash,
                }
            ),
            "executorAdapterHash": executor_adapter_hash,
            "evaluatorAdapterHash": evaluator_adapter_hash,
        },
        "matureSampleCount": len(records),
        "scoreSummary": (
            {
                "mean": mean_score,
                "lower_tail": lower_tail,
                "minimum": min(scores),
                "maximum": max(scores),
            }
            if scores
            else {}
        ),
        "tailFailureCaseRefs": [
            str(record["outcomeLabelRef"])
            for record in sorted(records, key=lambda row: float(row["normalizedScore"]))[
                :100
            ]
        ],
        "evidenceGapSummaries": [],
        "failureCategoryCounts": _failure_counts(scores),
        "directComponents": _build_direct_components(agent_id, records),
        "controlledExperiments": source["validationExperiments"],
    }
    return {**without_hash, "projectionHash": canonical_hash(without_hash)}


def _required_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{label} must be a sha256 hash")
    return value


def _validate_knot_history_partition_v2(
    partition: Mapping[str, Any],
    *,
    selected_accepted_output_hashes: Sequence[str],
    cutoff_at: str,
) -> tuple[dict[str, Any], set[str], set[str]]:
    from mosaic.scorecard.capability_preservation import (
        load_capability_contract_bundle,
        validate_capability_contract_bundle,
        validate_knot_capability_use_aggregate,
        validate_public_safe_projection,
    )

    root = Path(__file__).resolve().parents[2]
    current_tool_manifest = json.loads(
        (
            root / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
        ).read_text(encoding="utf-8")
    )
    bundle = load_capability_contract_bundle(root)
    validate_capability_contract_bundle(
        bundle,
        current_tool_manifest=current_tool_manifest,
    )
    expected_fields = {
        "schema_version",
        "cutoff_at",
        "tool_environment_hash",
        "execution_behavior_release_hash",
        "capability_bundle_hash",
        "knot_coverage_manifest_v2_hash",
        "knot_audit_capability_track_v2_hash",
        "history_partition_hash",
        "sample_count",
        "excluded_sample_count",
        "materialization_refs",
        "excluded_sample_refs",
        "binding_aggregates",
        "materialization_set_hash",
        "excluded_sample_set_hash",
        "binding_aggregate_set_hash",
        "partition_hash",
    }
    if set(partition) != expected_fields:
        raise ValueError("KNOT history partition fields mismatch")
    body = {key: value for key, value in partition.items() if key != "partition_hash"}
    if partition.get("partition_hash") != canonical_hash(body):
        raise ValueError("KNOT history partition hash mismatch")
    if (
        partition.get("schema_version") != "knot_training_history_partition_v2"
        or partition.get("cutoff_at") != cutoff_at
    ):
        raise ValueError("KNOT history partition contract mismatch")

    accepted_track = bundle["accepted_output_capability_track"]
    audit_track = bundle["knot_audit_capability_track_v2"]
    coverage = bundle["knot_coverage_manifest_v2"]
    fixed_point = {
        "tool_environment_hash": accepted_track["tool_environment_hash"],
        "execution_behavior_release_hash": audit_track[
            "execution_behavior_release_hash"
        ],
        "capability_bundle_hash": accepted_track["capability_bundle_hash"],
        "knot_coverage_manifest_v2_hash": coverage["manifest_hash"],
        "knot_audit_capability_track_v2_hash": audit_track["track_hash"],
    }
    if any(partition.get(field) != value for field, value in fixed_point.items()):
        raise ValueError("KNOT history partition fixed-point mismatch")
    if partition.get("history_partition_hash") != canonical_hash(fixed_point):
        raise ValueError("KNOT history fixed-point hash mismatch")

    selected = list(selected_accepted_output_hashes)
    if (
        selected != sorted(set(selected))
        or any(_required_sha256(value, "selected accepted-output hash") != value for value in selected)
    ):
        raise ValueError("KNOT history selected accepted-output hashes are invalid")
    materialization_refs = _object_rows(
        partition.get("materialization_refs"), "KNOT materialization refs"
    )
    excluded_refs = _object_rows(
        partition.get("excluded_sample_refs"), "KNOT excluded sample refs"
    )
    if materialization_refs != sorted(
        materialization_refs, key=lambda row: str(row.get("accepted_output_hash"))
    ) or excluded_refs != sorted(
        excluded_refs, key=lambda row: str(row.get("sample_ref_hash"))
    ):
        raise ValueError("KNOT history sample refs are not canonical")
    materialized_hashes: set[str] = set()
    for ref in materialization_refs:
        if set(ref) != {"accepted_output_hash", "materialization_hash"}:
            raise ValueError("KNOT materialization ref fields mismatch")
        accepted_hash = _required_sha256(
            ref.get("accepted_output_hash"), "KNOT materialized accepted-output hash"
        )
        _required_sha256(ref.get("materialization_hash"), "KNOT materialization hash")
        if accepted_hash in materialized_hashes:
            raise ValueError("KNOT materialization refs are duplicated")
        materialized_hashes.add(accepted_hash)
    excluded_hashes: set[str] = set()
    for ref in excluded_refs:
        if set(ref) != {"accepted_output_hash", "sample_ref_hash", "reasons"}:
            raise ValueError("KNOT excluded sample ref fields mismatch")
        accepted_hash = _required_sha256(
            ref.get("accepted_output_hash"), "KNOT excluded accepted-output hash"
        )
        _required_sha256(ref.get("sample_ref_hash"), "KNOT excluded sample ref hash")
        reasons = ref.get("reasons")
        if (
            not isinstance(reasons, list)
            or not reasons
            or reasons != sorted(set(reasons))
            or any(not isinstance(reason, str) or not reason for reason in reasons)
        ):
            raise ValueError("KNOT excluded sample reasons are invalid")
        if accepted_hash in excluded_hashes:
            raise ValueError("KNOT excluded sample refs are duplicated")
        excluded_hashes.add(accepted_hash)
    if (
        materialized_hashes & excluded_hashes
        or materialized_hashes | excluded_hashes != set(selected)
    ):
        raise ValueError("KNOT history selected sample closure mismatch")
    for field, value in (
        ("sample_count", len(materialization_refs)),
        ("excluded_sample_count", len(excluded_refs)),
    ):
        supplied = partition.get(field)
        if isinstance(supplied, bool) or supplied != value:
            raise ValueError(f"KNOT history {field} mismatch")
    if partition.get("materialization_set_hash") != canonical_hash(
        materialization_refs
    ) or partition.get("excluded_sample_set_hash") != canonical_hash(excluded_refs):
        raise ValueError("KNOT history sample set hash mismatch")

    aggregates = _object_rows(
        partition.get("binding_aggregates"), "KNOT binding aggregates"
    )
    for aggregate in aggregates:
        validate_knot_capability_use_aggregate(aggregate)
    expected_binding_ids = [str(row["binding_id"]) for row in coverage["coverage"]]
    actual_binding_ids = [str(row.get("binding_id")) for row in aggregates]
    if (
        len(expected_binding_ids) != 187
        or expected_binding_ids != sorted(set(expected_binding_ids))
        or actual_binding_ids != expected_binding_ids
    ):
        raise ValueError("KNOT history aggregate binding exact closure mismatch")
    if partition.get("binding_aggregate_set_hash") != canonical_hash(
        [row["aggregate_hash"] for row in aggregates]
    ):
        raise ValueError("KNOT history aggregate set hash mismatch")
    validate_public_safe_projection(partition)
    return bundle, materialized_hashes, excluded_hashes


def _collect_maturity_authority_v2(
    conn: sqlite3.Connection,
    *,
    records: Sequence[Mapping[str, Any]],
    agent_id: str,
    cohort: str,
    cutoff_at: str,
) -> tuple[list[str], list[dict[str, str]], list[dict[str, Any]]]:
    from mosaic.scorecard.outcome_source_receipts import (
        load_historical_outcome_source_batch,
    )

    cutoff = _timestamp(cutoff_at, "cutoff_at")
    sample_ids: list[str] = []
    calendar_refs: list[dict[str, str]] = []
    label_receipt_refs: list[dict[str, Any]] = []
    for record in records:
        sample_id = str(record["sampleId"])
        label_row = conn.execute(
            "SELECT record_json, outcome_label_hash, scheduled_sample_id, agent_id "
            "FROM agent_outcome_labels_v2 WHERE outcome_label_id = ?",
            (record["outcomeLabelRef"],),
        ).fetchone()
        if label_row is None:
            raise ValueError("Prompt v2 outcome label authority is unavailable")
        label = _hashed_record(label_row[0], "outcome_label_hash", "outcome label")
        if (
            label_row[1] != label["outcome_label_hash"]
            or label_row[2] != sample_id
            or label_row[3] != agent_id
            or label.get("outcome_label_hash") != record["outcomeLabelHash"]
            or label.get("scheduled_sample_id") != sample_id
            or label.get("agent_id") != agent_id
            or label.get("matured_at") != record["maturedAt"]
        ):
            raise ValueError("Prompt v2 outcome label authority mismatch")
        observation_id = label.get("realized_outcome_observation_id")
        observation_row = conn.execute(
            "SELECT record_json, realized_outcome_observation_hash, "
            "scheduled_sample_id, agent_id FROM realized_outcome_observations_v2 "
            "WHERE realized_outcome_observation_id = ?",
            (observation_id,),
        ).fetchone()
        if observation_row is None:
            raise ValueError("Prompt v2 realized observation authority is unavailable")
        observation = _hashed_record(
            observation_row[0],
            "realized_outcome_observation_hash",
            "realized outcome observation",
        )
        if (
            observation_row[1] != observation["realized_outcome_observation_hash"]
            or observation_row[2] != sample_id
            or observation_row[3] != agent_id
            or observation.get("realized_outcome_observation_id") != observation_id
            or observation.get("realized_outcome_observation_hash")
            != label.get("realized_outcome_observation_hash")
            or observation.get("scheduled_sample_id") != sample_id
            or observation.get("agent_id") != agent_id
            or observation.get("matured_at") != record["maturedAt"]
            or observation.get("projection_status") != "SCORE"
        ):
            raise ValueError("Prompt v2 realized observation authority mismatch")
        batch = load_historical_outcome_source_batch(
            conn,
            scheduled_sample_id=sample_id,
            accepted_output_id=str(record["agentOutputRef"]),
            accepted_output_hash=str(record["agentOutputHash"]),
            agent_id=agent_id,
            source_batch_id=str(observation.get("source_batch_id")),
            source_batch_hash=str(observation.get("source_batch_hash")),
            matured_at=str(record["maturedAt"]),
            cutoff_at=cutoff_at,
        )
        if (
            observation.get("realized_metrics") != batch.get("realized_metrics")
            or observation.get("source_evidence_ids") != batch.get("source_evidence_ids")
        ):
            raise ValueError("Prompt v2 realized observation source batch mismatch")

        schedule_row = conn.execute(
            "SELECT s.record_json, p.record_json "
            "FROM outcome_schedule_slots_v2 s "
            "JOIN outcome_schedule_plans_v2 p "
            "ON p.outcome_schedule_plan_id = s.outcome_schedule_plan_id "
            "WHERE s.scheduled_sample_id = ?",
            (sample_id,),
        ).fetchone()
        if schedule_row is None:
            raise ValueError("Prompt v2 outcome schedule authority is unavailable")
        slot = _hashed_record(
            schedule_row[0], "outcome_schedule_slot_hash", "outcome schedule slot"
        )
        plan = _hashed_record(
            schedule_row[1], "outcome_schedule_plan_hash", "outcome schedule plan"
        )
        calendar_hash = _required_sha256(
            plan.get("trading_calendar_snapshot_hash"),
            "trading calendar snapshot hash",
        )
        if (
            slot.get("scheduled_sample_id") != sample_id
            or slot.get("agent_id") != agent_id
            or slot.get("outcome_schedule_plan_id")
            != plan.get("outcome_schedule_plan_id")
            or plan.get("cohort_id") != cohort
            or _timestamp(plan.get("prepared_at"), "schedule prepared_at") > cutoff
        ):
            raise ValueError("Prompt v2 outcome schedule authority mismatch")
        receipt_refs = batch.get("receipt_refs_by_required_source_id")
        if not isinstance(receipt_refs, Mapping):
            raise ValueError("Prompt v2 source receipt authority is unavailable")
        receipt_hashes = sorted(
            _required_sha256(ref.get("source_receipt_hash"), "source receipt hash")
            for ref in receipt_refs.values()
            if isinstance(ref, Mapping)
        )
        if len(receipt_hashes) != len(receipt_refs):
            raise ValueError("Prompt v2 source receipt authority is invalid")
        sample_ids.append(sample_id)
        calendar_refs.append(
            {
                "sampleId": sample_id,
                "tradingCalendarSnapshotHash": calendar_hash,
            }
        )
        label_receipt_refs.append(
            {
                "sampleId": sample_id,
                "acceptedOutputHash": str(record["agentOutputHash"]),
                "outcomeLabelHash": str(record["outcomeLabelHash"]),
                "realizedOutcomeObservationHash": str(
                    observation["realized_outcome_observation_hash"]
                ),
                "sourceBatchHash": str(batch["source_batch_hash"]),
                "sourceReceiptHashes": receipt_hashes,
            }
        )
    if sample_ids != sorted(set(sample_ids)):
        raise ValueError("Prompt v2 eligible sample IDs are not canonical")
    return sample_ids, calendar_refs, label_receipt_refs


def build_prompt_training_projection_v2(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    stage: str,
    cohort: str,
    cutoff_at: str,
    knot_history_store: Any,
    excluded_sample_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Join trusted outcome maturity with the current server KNOT history partition."""
    initial = _collect_prompt_training_inputs(
        conn,
        agent_id=agent_id,
        stage=stage,
        cohort=cohort,
        cutoff_at=cutoff_at,
        excluded_sample_ids=excluded_sample_ids,
    )
    accepted_hash_to_sample = {
        str(record["agentOutputHash"]): str(record["sampleId"])
        for record in initial["records"]
    }
    if len(accepted_hash_to_sample) != len(initial["records"]):
        raise ValueError("Prompt v2 accepted-output history is duplicated")
    selected_hashes = sorted(accepted_hash_to_sample)
    partition = knot_history_store.build_knot_history_partition_v2(
        cutoff_at=cutoff_at,
        accepted_output_hashes=selected_hashes,
    )
    if not isinstance(partition, Mapping):
        raise ValueError("KNOT history partition must be an object")
    bundle, materialized_hashes, excluded_hashes = _validate_knot_history_partition_v2(
        partition,
        selected_accepted_output_hashes=selected_hashes,
        cutoff_at=cutoff_at,
    )
    final_exclusions = sorted(
        set(excluded_sample_ids)
        | {accepted_hash_to_sample[value] for value in excluded_hashes}
    )
    final_source = _collect_prompt_training_inputs(
        conn,
        agent_id=agent_id,
        stage=stage,
        cohort=cohort,
        cutoff_at=cutoff_at,
        excluded_sample_ids=final_exclusions,
    )
    final_hashes = {str(record["agentOutputHash"]) for record in final_source["records"]}
    if final_hashes != materialized_hashes:
        raise ValueError("Prompt v2 outcome and KNOT eligible sample closure mismatch")
    v1 = build_prompt_training_projection(
        conn,
        agent_id=agent_id,
        stage=stage,
        cohort=cohort,
        cutoff_at=cutoff_at,
        excluded_sample_ids=final_exclusions,
    )
    sample_ids, calendar_refs, label_receipt_refs = _collect_maturity_authority_v2(
        conn,
        records=final_source["records"],
        agent_id=agent_id,
        cohort=cohort,
        cutoff_at=cutoff_at,
    )
    if v1["matureSampleCount"] != len(sample_ids):
        raise ValueError("Prompt v2 mature sample count mismatch")
    from mosaic.scorecard.darwinian_v2 import (
        get_production_variant_roster_revision,
    )

    roster_revisions = []
    for revision_id in sorted(
        {
            str(record["productionVariantRosterRevisionId"])
            for record in final_source["records"]
        }
    ):
        revision = get_production_variant_roster_revision(conn, revision_id)
        if revision is None:
            raise ValueError("Prompt v2 production roster revision is unavailable")
        roster_revisions.append(
            {
                "revisionId": revision_id,
                "revisionHash": revision[
                    "production_variant_roster_revision_hash"
                ],
            }
        )
    roster_revision_set_hash = canonical_hash(roster_revisions)
    outcome_contract_hash = canonical_hash(v1["outcomeContract"])
    horizon_id = str(v1["outcomeContract"]["maturityHorizon"])
    maturity_contract = {
        "horizonId": horizon_id,
        "horizonContractHash": canonical_hash(
            {
                "horizonId": horizon_id,
                "maturityTradingDays": v1["outcomeContract"][
                    "maturityTradingDays"
                ],
                "outcomeContractHash": outcome_contract_hash,
                "eligibilityEvaluatorVersion": MATURE_SAMPLE_ELIGIBILITY_VERSION,
            }
        ),
        "outcomeContractHash": outcome_contract_hash,
        "tradingCalendarHash": canonical_hash(calendar_refs),
        "labelReceiptSetHash": canonical_hash(label_receipt_refs),
        "eligibilityEvaluatorVersion": MATURE_SAMPLE_ELIGIBILITY_VERSION,
    }
    target = v1["target"]
    projection_identity = {
        "target": target,
        "cutoffAt": cutoff_at,
        "datasetSnapshotHash": v1["datasetSnapshotHash"],
        "eligibleSampleIdsHash": canonical_hash(sample_ids),
        "excludedSampleIdsHash": v1["excludedSampleIdsHash"],
        "knotHistoryPartitionHash": partition["partition_hash"],
        "productionVariantRosterRevisionSetHash": roster_revision_set_hash,
        "maturityContract": maturity_contract,
    }
    without_hash = {
        "schemaVersion": PROMPT_TRAINING_PROJECTION_V2_VERSION,
        "target": target,
        "projectionId": "projection-"
        + canonical_hash(projection_identity)[len("sha256:") : len("sha256:") + 24],
        "datasetSnapshotHash": v1["datasetSnapshotHash"],
        "eligibleSampleIdsHash": canonical_hash(sample_ids),
        "excludedSampleIdsHash": v1["excludedSampleIdsHash"],
        "cutoffAt": cutoff_at,
        "outcomeContract": v1["outcomeContract"],
        "evaluator": v1["evaluator"],
        "capabilityTrack": bundle["accepted_output_capability_track"],
        "knotAuditCapabilityTrack": bundle["knot_audit_capability_track_v2"],
        "knotHistoryPartitionHash": partition["partition_hash"],
        "knotMaterializationSetHash": partition["materialization_set_hash"],
        "knotExcludedSampleSetHash": partition["excluded_sample_set_hash"],
        "capabilityUseAggregates": partition["binding_aggregates"],
        "productionVariantRosterRevisions": roster_revisions,
        "productionVariantRosterRevisionSetHash": roster_revision_set_hash,
        "maturityContract": maturity_contract,
        "matureSampleCount": v1["matureSampleCount"],
        "scoreSummary": v1["scoreSummary"],
        "tailFailureCaseRefs": v1["tailFailureCaseRefs"],
        "failureCategoryCounts": v1["failureCategoryCounts"],
        "directComponents": v1["directComponents"],
        "controlledExperiments": v1["controlledExperiments"],
    }
    projection = {**without_hash, "projectionHash": canonical_hash(without_hash)}
    from mosaic.scorecard.capability_preservation import validate_public_safe_projection

    validate_public_safe_projection(projection)
    return projection


__all__ = [
    "PROMPT_TRAINING_PROJECTION_VERSION",
    "PROMPT_TRAINING_PROJECTION_V2_VERSION",
    "PROMPT_ROLE_COMPONENT_EVALUATOR_VERSION",
    "build_prompt_training_projection",
    "build_prompt_training_projection_v2",
    "prompt_role_component_refs",
]

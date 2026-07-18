"""Deterministic outcome maturation and Darwinian v2 weight publication.

The legacy scorecard computes portfolio-level Sharpe.  This module deliberately
does not: every label is bound to one role-matched evaluation track, and only
the 24 upstream information roles can publish downstream usage weights.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import date
from typing import Any, Mapping, Sequence

from jsonschema import Draft7Validator

from mosaic.scorecard.darwinian_v2 import (
    canonical_hash,
    canonical_json,
    deterministic_id,
)
from mosaic.scorecard.outcome_contracts import (
    OUTCOME_CONTRACTS,
    OUTCOME_METRIC_SCHEMAS,
)


WINDOW_SIZE = 30
MAXIMUM_LOOKBACK_TRADING_DAYS = 1260
MINIMUM_WINDOW_COVERAGE = 0.8
WEIGHT_MIN = 0.3
WEIGHT_MAX = 2.5
Q1_MULTIPLIER = 1.05
Q4_MULTIPLIER = 0.95
TIE_EPSILON = 1e-9
PEER_MINIMUMS = {"sector_selection": 7, "superinvestor_selection": 3}
UPDATE_CALENDAR_ID = "cn_a_share_trading_calendar_v1"
UPDATE_CALENDAR_EPOCH = "2010-01-04"
UPDATE_SLOT_STEP_TRADING_DAYS = 5
EMPTY_OPPORTUNITY_ALLOWED = {
    "druckenmiller",
    "munger",
    "burry",
    "ackman",
    "cro",
    "alpha_discovery",
    "autonomous_execution",
}
TERMINAL_ELIGIBILITY_DISPOSITIONS = {
    "SCORE",
    "AGENT_FAILURE",
    "EXOGENOUS_EXCLUSION",
}
DECISION_COMPONENTS: dict[str, tuple[tuple[str, float], ...]] = {
    "CRO": (
        ("PRECISION", 0.35),
        ("RECALL", 0.35),
        ("SPECIFICITY", 0.2),
        ("CALIBRATION", 0.1),
    ),
    "ALPHA": (
        ("SELECTED_PICK_UTILITY", 0.7),
        ("INCREMENTAL_OPPORTUNITY_UTILITY", 0.3),
    ),
    "EXECUTION": (
        ("COST_ERROR", 0.4),
        ("FEASIBILITY", 0.3),
        ("TARGET_DELTA", 0.2),
        ("POLICY_COMPLIANCE", 0.1),
    ),
    "CIO": (
        ("RELATIVE_RETURN", 0.5),
        ("DRAWDOWN", 0.25),
        ("TURNOVER_COST", 0.15),
        ("CONSTRAINT_COMPLIANCE", 0.1),
    ),
}


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _probability(value: Any, field: str) -> float:
    number = _finite_number(value, field)
    if not 0 <= number <= 1:
        raise ValueError(f"{field} must be in [0, 1]")
    return number


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def derive_darwin_calendar_window(
    *,
    trading_dates: Sequence[str],
    cutoff_at: str,
    require_update_slot: bool,
) -> dict[str, Any]:
    """Derive the fixed 1260-day window and optional five-session slot."""
    dates = list(trading_dates)
    if not dates or dates != sorted(set(dates)):
        raise ValueError("trading_dates must be a non-empty sorted unique calendar")
    try:
        for value in dates:
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError
            date.fromisoformat(value)
        cutoff_date = date.fromisoformat(cutoff_at[:10]).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("trading calendar contains an invalid ISO date") from exc
    if UPDATE_CALENDAR_EPOCH not in dates:
        raise ValueError("trading calendar does not contain the registered update epoch")
    if cutoff_date not in dates:
        raise ValueError("Darwinian cutoff must be an A-share trading date")
    epoch_index = dates.index(UPDATE_CALENDAR_EPOCH)
    cutoff_index = dates.index(cutoff_date)
    if cutoff_index < epoch_index:
        raise ValueError("Darwinian cutoff precedes the registered update epoch")
    lookback_index = cutoff_index - (MAXIMUM_LOOKBACK_TRADING_DAYS - 1)
    if lookback_index < epoch_index:
        raise ValueError("trading calendar has fewer than 1260 sessions at cutoff")
    elapsed = cutoff_index - epoch_index + 1
    update_slot_id: str | None = None
    if require_update_slot:
        if elapsed % UPDATE_SLOT_STEP_TRADING_DAYS != 0:
            raise ValueError("cutoff is not a registered five-session update slot close")
        update_slot_id = (
            f"darwin-update-slot:{UPDATE_CALENDAR_ID}:"
            f"{elapsed // UPDATE_SLOT_STEP_TRADING_DAYS}:{cutoff_date}"
        )
    window_dates = dates[lookback_index : cutoff_index + 1]
    return {
        "trading_calendar_id": UPDATE_CALENDAR_ID,
        "trading_calendar_epoch": UPDATE_CALENDAR_EPOCH,
        "trading_calendar_hash": canonical_hash(dates[: cutoff_index + 1]),
        "lookback_start": f"{window_dates[0]}T00:00:00+08:00",
        "cutoff_trading_date": cutoff_date,
        "maximum_lookback_trading_days": MAXIMUM_LOOKBACK_TRADING_DAYS,
        "update_slot_id": update_slot_id,
    }


def _track_record(conn: sqlite3.Connection, track_key_hash: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT contract_json FROM darwinian_v2_evaluation_tracks WHERE track_key_hash = ?",
        (track_key_hash,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown Darwinian evaluation track: {track_key_hash}")
    record = json.loads(row[0])
    contract = record.get("outcome_contract")
    if not isinstance(contract, dict):
        raise ValueError("evaluation track has no frozen outcome contract")
    canonical = OUTCOME_CONTRACTS.get(str(record.get("agent_id")))
    if canonical is None or contract != canonical:
        raise ValueError("evaluation track outcome contract drift")
    return record


def _insert_immutable(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
    record_id: str,
    columns: Sequence[str],
    values: Sequence[Any],
    record_json: str,
) -> bool:
    cursor = conn.execute(
        f"INSERT OR IGNORE INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        tuple(values),
    )
    if cursor.rowcount == 1:
        return True
    existing = conn.execute(
        f"SELECT record_json FROM {table} WHERE {id_column} = ?",
        (record_id,),
    ).fetchone()
    if existing is None or existing[0] != record_json:
        raise ValueError(f"immutable record collision in {table}: {record_id}")
    return False


def freeze_evaluation_opportunity_set(
    conn: sqlite3.Connection,
    *,
    production_variant_roster_revision_id: str,
    track_key_hash: str,
    scheduled_sample_id: str,
    sample_origin: str,
    as_of: str,
    member_refs: Sequence[Mapping[str, Any]],
    required_source_evidence_ids: Sequence[str],
    qualification_predicate_version: str,
    generator_input_snapshot_hash: str | None = None,
) -> dict[str, Any]:
    """Freeze the complete pre-run denominator for one scheduled sample."""
    track = _track_record(conn, track_key_hash)
    agent_id = str(track["agent_id"])
    revision_row = conn.execute(
        "SELECT record_json FROM darwinian_v2_production_variant_roster_revisions "
        "WHERE production_variant_roster_revision_id = ? AND readiness = 'READY'",
        (production_variant_roster_revision_id,),
    ).fetchone()
    if revision_row is None:
        raise ValueError("READY production roster revision is unavailable")
    revision = json.loads(revision_row[0])
    if track_key_hash not in revision["evaluation_track_key_hashes"]:
        raise ValueError("evaluation track is outside the roster revision")
    if sample_origin not in {
        "PRODUCTION_ACTIVE",
        "KNOT_RESEARCH_SHADOW",
        "KNOT_POST_PROMOTION_CHAMPION_SHADOW",
    }:
        raise ValueError("outcome opportunity set has invalid sample_origin")
    if not required_source_evidence_ids or any(
        not isinstance(item, str) or not item for item in required_source_evidence_ids
    ):
        raise ValueError("opportunity set requires non-empty source evidence")
    members = [dict(member) for member in member_refs]
    if not members and agent_id not in EMPTY_OPPORTUNITY_ALLOWED:
        raise ValueError(f"{agent_id} cannot freeze an empty opportunity set")
    if len({canonical_hash(member) for member in members}) != len(members):
        raise ValueError("opportunity set contains duplicate members")
    member_state = "NON_EMPTY" if members else "EMPTY"
    qualification_predicate_version = _required_text(
        qualification_predicate_version,
        "qualification_predicate_version",
    )
    if generator_input_snapshot_hash is not None and not (
        isinstance(generator_input_snapshot_hash, str)
        and generator_input_snapshot_hash.startswith("sha256:")
        and len(generator_input_snapshot_hash) == 71
    ):
        raise ValueError("generator_input_snapshot_hash must be sha256 when present")
    outcome_contract = track["outcome_contract"]
    identity = {
        "scheduled_sample_id": _required_text(scheduled_sample_id, "scheduled_sample_id"),
        "track_key_hash": track_key_hash,
        "sample_origin": sample_origin,
        "as_of": _required_text(as_of, "as_of"),
        "members": members,
        "required_source_evidence_ids": sorted(set(required_source_evidence_ids)),
        "qualification_predicate_version": qualification_predicate_version,
        "generator_input_snapshot_hash": generator_input_snapshot_hash,
    }
    set_id = deterministic_id("evaluation-opportunity-set", identity)
    without_hash = {
        "evaluation_opportunity_set_id": set_id,
        "schema_version": "evaluation_opportunity_set_v2",
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": production_variant_roster_revision_id,
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": revision["cohort_id"],
        "language": revision["language"],
        "track_key_hash": track_key_hash,
        "agent_id": agent_id,
        "sample_origin": sample_origin,
        "opportunity_set_status": "AVAILABLE",
        "opportunity_set_contract_version": outcome_contract[
            "opportunity_set_contract_version"
        ],
        "outcome_contract_version": outcome_contract["outcome_contract_version"],
        "scoring_contract_version": outcome_contract["scoring_contract_version"],
        "sample_schedule_contract_version": outcome_contract[
            "sample_schedule_contract_version"
        ],
        "rank_scope_contract_version": outcome_contract[
            "rank_scope_contract_version"
        ],
        "rank_scope": outcome_contract["rank_scope"],
        "primary_label_id": outcome_contract["primary_label_id"],
        "darwin_application_mode": track["darwin_application_mode"],
        "member_state": member_state,
        "member_refs": members,
        "member_evidence_ids": sorted(set(required_source_evidence_ids)),
        "required_source_evidence_ids": sorted(set(required_source_evidence_ids)),
        "scheduled_sample_id": scheduled_sample_id,
        "as_of": as_of,
        "generated_at": as_of,
        "frozen_at": as_of,
        "qualification_predicate_version": qualification_predicate_version,
        "generator_input_snapshot_hash": generator_input_snapshot_hash,
        "pit_status": "VERIFIED",
        "contract_versions": {
            key: outcome_contract[key]
            for key in (
                "outcome_contract_version",
                "scoring_contract_version",
                "sample_schedule_contract_version",
                "rank_scope_contract_version",
                "opportunity_set_contract_version",
            )
        },
    }
    record = {
        **without_hash,
        "evaluation_opportunity_set_hash": canonical_hash(without_hash),
    }
    record_json = canonical_json(record)
    _insert_immutable(
        conn,
        table="evaluation_opportunity_sets_v2",
        id_column="evaluation_opportunity_set_id",
        record_id=set_id,
        columns=(
            "evaluation_opportunity_set_id",
            "evaluation_opportunity_set_hash",
            "scheduled_sample_id",
            "production_variant_roster_id",
            "production_variant_roster_revision_id",
            "execution_behavior_release_id",
            "cohort_id",
            "language",
            "track_key_hash",
            "agent_id",
            "sample_origin",
            "opportunity_set_status",
            "member_state",
            "frozen_at",
            "record_json",
        ),
        values=(
            set_id,
            record["evaluation_opportunity_set_hash"],
            scheduled_sample_id,
            revision["production_variant_roster_id"],
            production_variant_roster_revision_id,
            revision["execution_behavior_release_id"],
            revision["cohort_id"],
            revision["language"],
            track_key_hash,
            agent_id,
            sample_origin,
            "AVAILABLE",
            member_state,
            as_of,
            record_json,
        ),
        record_json=record_json,
    )
    return record


def append_outcome_eligibility_revision(
    conn: sqlite3.Connection,
    *,
    track_key_hash: str,
    scheduled_sample_id: str,
    sample_origin: str,
    disposition: str,
    recorded_at: str,
    evaluation_opportunity_set_id: str | None,
    accepted_output_id: str | None = None,
    exclusion_or_failure_reason: str | None = None,
    research_pair_side: str | None = None,
) -> dict[str, Any]:
    """Append one immutable audit revision; terminal revisions cannot be replaced."""
    if disposition not in {"PENDING", *TERMINAL_ELIGIBILITY_DISPOSITIONS}:
        raise ValueError(f"unsupported eligibility disposition: {disposition}")
    track = _track_record(conn, track_key_hash)
    agent_id = str(track["agent_id"])
    knot_origin = sample_origin in {
        "KNOT_RESEARCH_SHADOW",
        "KNOT_POST_PROMOTION_CHAMPION_SHADOW",
    }
    if knot_origin and research_pair_side not in {"CHAMPION", "CANDIDATE"}:
        raise ValueError("KNOT outcome eligibility requires research_pair_side")
    if not knot_origin and research_pair_side is not None:
        raise ValueError("production outcome eligibility cannot carry research_pair_side")
    set_record: dict[str, Any] | None = None
    if evaluation_opportunity_set_id is not None:
        row = conn.execute(
            "SELECT record_json FROM evaluation_opportunity_sets_v2 "
            "WHERE evaluation_opportunity_set_id = ?",
            (evaluation_opportunity_set_id,),
        ).fetchone()
        if row is None:
            raise ValueError("evaluation opportunity set is unavailable")
        set_record = json.loads(row[0])
        for field, expected in (
            ("scheduled_sample_id", scheduled_sample_id),
            ("track_key_hash", track_key_hash),
            ("agent_id", agent_id),
            ("sample_origin", sample_origin),
        ):
            if set_record.get(field) != expected:
                raise ValueError(f"opportunity set {field} mismatch")
    elif disposition in {"PENDING", "SCORE"}:
        raise ValueError(f"{disposition} requires an AVAILABLE opportunity set")

    accepted_record: dict[str, Any] | None = None
    if accepted_output_id is not None:
        row = conn.execute(
            "SELECT record_json FROM accepted_agent_outputs_v2 WHERE accepted_output_id = ?",
            (accepted_output_id,),
        ).fetchone()
        if row is None:
            raise ValueError("accepted output is unavailable")
        accepted_record = json.loads(row[0])
        for field, expected in (
            ("scheduled_sample_id", scheduled_sample_id),
            ("track_key_hash", track_key_hash),
            ("agent_id", agent_id),
            ("sample_origin", sample_origin),
            ("run_slot_kind", "OUTCOME_SCHEDULED"),
        ):
            if accepted_record.get(field) != expected:
                raise ValueError(f"accepted output {field} mismatch")
        if accepted_record.get("accepted_output_kind") != track["outcome_contract"][
            "accepted_output_kind"
        ]:
            raise ValueError("accepted output kind is not the evaluation object")
    if disposition in {"PENDING", "SCORE"} and accepted_record is None:
        raise ValueError(f"{disposition} requires the role-matched accepted output")
    if disposition == "AGENT_FAILURE" and accepted_record is not None:
        raise ValueError("AGENT_FAILURE cannot carry an accepted output")
    if disposition in {"AGENT_FAILURE", "EXOGENOUS_EXCLUSION"} and not (
        isinstance(exclusion_or_failure_reason, str) and exclusion_or_failure_reason
    ):
        raise ValueError(f"{disposition} requires an explicit reason")

    audit_identity = {
        "scheduled_sample_id": scheduled_sample_id,
        "track_key_hash": track_key_hash,
        "sample_origin": sample_origin,
        "research_pair_side": research_pair_side,
    }
    audit_id = deterministic_id("outcome-eligibility-audit", audit_identity)
    previous_rows = conn.execute(
        "SELECT audit_revision_id, audit_sequence, disposition FROM "
        "agent_outcome_eligibility_revisions_v2 WHERE audit_id = ? "
        "ORDER BY audit_sequence",
        (audit_id,),
    ).fetchall()
    if previous_rows and previous_rows[-1][2] == "PENDING" and disposition == "PENDING":
        existing_row = conn.execute(
            "SELECT record_json FROM agent_outcome_eligibility_revisions_v2 "
            "WHERE audit_revision_id = ?",
            (previous_rows[-1][0],),
        ).fetchone()
        if existing_row is not None:
            existing = json.loads(existing_row[0])
            if (
                existing.get("accepted_output_id") == accepted_output_id
                and existing.get("evaluation_opportunity_set_id")
                == evaluation_opportunity_set_id
                and existing.get("exclusion_or_failure_reason")
                == exclusion_or_failure_reason
            ):
                return existing
        raise ValueError("PENDING eligibility retry changed immutable inputs")
    if previous_rows and previous_rows[-1][2] in TERMINAL_ELIGIBILITY_DISPOSITIONS:
        terminal = conn.execute(
            "SELECT record_json FROM agent_outcome_eligibility_revisions_v2 "
            "WHERE audit_revision_id = ?",
            (previous_rows[-1][0],),
        ).fetchone()
        if terminal is not None:
            existing = json.loads(terminal[0])
            if (
                existing.get("disposition") == disposition
                and existing.get("accepted_output_id") == accepted_output_id
                and existing.get("exclusion_or_failure_reason")
                == exclusion_or_failure_reason
            ):
                return existing
        raise ValueError("terminal eligibility audit revision is immutable")
    if previous_rows and previous_rows[-1][2] != "PENDING":
        raise ValueError("invalid eligibility audit transition")
    audit_sequence = len(previous_rows) + 1
    supersedes = previous_rows[-1][0] if previous_rows else None
    accepted_hash = accepted_record.get("accepted_output_hash") if accepted_record else None
    versions = {
        key: track["outcome_contract"][key]
        for key in (
            "outcome_contract_version",
            "scoring_contract_version",
            "sample_schedule_contract_version",
            "rank_scope_contract_version",
        )
    }
    revision_id = deterministic_id(
        "outcome-eligibility-revision",
        {**audit_identity, "audit_sequence": audit_sequence, "disposition": disposition},
    )
    without_hash = {
        "audit_revision_id": revision_id,
        "audit_id": audit_id,
        "supersedes_revision_id": supersedes,
        "audit_sequence": audit_sequence,
        "scheduled_sample_id": scheduled_sample_id,
        "track_key_hash": track_key_hash,
        "agent_id": agent_id,
        "sample_origin": sample_origin,
        "research_pair_side": research_pair_side,
        "disposition": disposition,
        "accepted_output_id": accepted_output_id,
        "accepted_output_hash": accepted_hash,
        "evaluation_opportunity_set_id": evaluation_opportunity_set_id,
        "evaluation_opportunity_set_hash": (
            set_record.get("evaluation_opportunity_set_hash") if set_record else None
        ),
        "opportunity_set_status": "AVAILABLE" if set_record else "UNAVAILABLE",
        "exclusion_or_failure_reason": exclusion_or_failure_reason,
        "darwin_evaluation_eligible": (
            sample_origin == "PRODUCTION_ACTIVE"
            and disposition != "EXOGENOUS_EXCLUSION"
        ),
        "usage_weight_eligible": (
            sample_origin == "PRODUCTION_ACTIVE"
            and disposition != "EXOGENOUS_EXCLUSION"
            and track["darwin_application_mode"] == "DOWNSTREAM_USAGE_WEIGHT"
        ),
        "contract_versions": versions,
        "recorded_at": recorded_at,
    }
    record = {**without_hash, "audit_revision_hash": canonical_hash(without_hash)}
    record_json = canonical_json(record)
    _insert_immutable(
        conn,
        table="agent_outcome_eligibility_revisions_v2",
        id_column="audit_revision_id",
        record_id=revision_id,
        columns=(
            "audit_revision_id",
            "audit_revision_hash",
            "audit_id",
            "supersedes_revision_id",
            "scheduled_sample_id",
            "track_key_hash",
            "agent_id",
            "sample_origin",
            "research_pair_side",
            "disposition",
            "accepted_output_id",
            "opportunity_set_status",
            "audit_sequence",
            "recorded_at",
            "record_json",
        ),
        values=(
            revision_id,
            record["audit_revision_hash"],
            audit_id,
            supersedes,
            scheduled_sample_id,
            track_key_hash,
            agent_id,
            sample_origin,
            research_pair_side,
            disposition,
            accepted_output_id,
            without_hash["opportunity_set_status"],
            audit_sequence,
            recorded_at,
            record_json,
        ),
        record_json=record_json,
    )
    return record


def append_realized_outcome_observation(
    conn: sqlite3.Connection,
    *,
    evaluation_opportunity_set_id: str,
    outcome_due_at: str,
    matured_at: str,
    realized_metrics: Mapping[str, Any],
    source_evidence_ids: Sequence[str],
) -> dict[str, Any]:
    """Persist shared market/event realization without Agent forecasts or utility."""
    row = conn.execute(
        "SELECT record_json FROM evaluation_opportunity_sets_v2 "
        "WHERE evaluation_opportunity_set_id = ? AND opportunity_set_status = 'AVAILABLE'",
        (evaluation_opportunity_set_id,),
    ).fetchone()
    if row is None:
        raise ValueError("AVAILABLE evaluation opportunity set is required")
    opportunity = json.loads(row[0])
    forbidden = {
        "agent_output",
        "prediction",
        "forecast_loss",
        "utility_delta",
        "normalized_score",
    }
    if forbidden & set(realized_metrics):
        raise ValueError("realized observation cannot contain Agent predictions or scores")
    if not source_evidence_ids or any(not isinstance(item, str) or not item for item in source_evidence_ids):
        raise ValueError("realized observation requires source evidence")
    identity = {
        "scheduled_sample_id": opportunity["scheduled_sample_id"],
        "evaluation_opportunity_set_hash": opportunity["evaluation_opportunity_set_hash"],
        "outcome_due_at": outcome_due_at,
        "matured_at": matured_at,
        "realized_metrics": dict(realized_metrics),
        "source_evidence_ids": sorted(set(source_evidence_ids)),
    }
    observation_id = deterministic_id("realized-outcome-observation", identity)
    without_hash = {
        "realized_outcome_observation_id": observation_id,
        "schema_version": "realized_outcome_observation_v2",
        "scheduled_sample_id": opportunity["scheduled_sample_id"],
        "evaluation_opportunity_set_id": evaluation_opportunity_set_id,
        "evaluation_opportunity_set_hash": opportunity["evaluation_opportunity_set_hash"],
        "agent_id": opportunity["agent_id"],
        "outcome_due_at": _required_text(outcome_due_at, "outcome_due_at"),
        "matured_at": _required_text(matured_at, "matured_at"),
        "realized_metrics": dict(realized_metrics),
        "source_evidence_ids": sorted(set(source_evidence_ids)),
        "source_evidence_hash": canonical_hash(sorted(set(source_evidence_ids))),
    }
    record = {
        **without_hash,
        "realized_outcome_observation_hash": canonical_hash(without_hash),
    }
    record_json = canonical_json(record)
    _insert_immutable(
        conn,
        table="realized_outcome_observations_v2",
        id_column="realized_outcome_observation_id",
        record_id=observation_id,
        columns=(
            "realized_outcome_observation_id",
            "realized_outcome_observation_hash",
            "scheduled_sample_id",
            "evaluation_opportunity_set_id",
            "agent_id",
            "outcome_due_at",
            "matured_at",
            "source_evidence_hash",
            "record_json",
        ),
        values=(
            observation_id,
            record["realized_outcome_observation_hash"],
            opportunity["scheduled_sample_id"],
            evaluation_opportunity_set_id,
            opportunity["agent_id"],
            outcome_due_at,
            matured_at,
            without_hash["source_evidence_hash"],
            record_json,
        ),
        record_json=record_json,
    )
    return record


def _macro_utility(raw_metrics: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    direction_sign = _finite_number(raw_metrics.get("direction_sign"), "direction_sign")
    if direction_sign not in {-1, 0, 1}:
        raise ValueError("direction_sign must be -1, 0, or 1")
    strength = _finite_number(raw_metrics.get("strength"), "strength")
    if strength not in {0, 1, 2, 3, 4, 5}:
        raise ValueError("strength must be an integer in [0, 5]")
    if (direction_sign == 0) != (strength == 0):
        raise ValueError("neutral direction and zero strength must coincide")
    confidence = _probability(raw_metrics.get("confidence"), "confidence")
    role_path = _finite_number(raw_metrics.get("role_path_metric"), "role_path_metric")
    volatility = _finite_number(raw_metrics.get("pit_volatility_scale"), "pit_volatility_scale")
    if volatility <= 0:
        raise ValueError("pit_volatility_scale must be positive")
    forecast = confidence * direction_sign * strength / 5
    realized = _clip(role_path / volatility, -1, 1)
    forecast_loss = (forecast - realized) ** 2
    null_loss = realized**2
    utility_delta = null_loss - forecast_loss
    return utility_delta, {
        **dict(raw_metrics),
        "point_forecast": forecast,
        "realized_scaled_path": realized,
        "forecast_loss": forecast_loss,
        "null_loss": null_loss,
        "combined_utility_delta": utility_delta,
    }


def _decision_utility(
    metric_family: str,
    raw_metrics: Mapping[str, Any],
) -> tuple[float, dict[str, Any]]:
    expected = DECISION_COMPONENTS[metric_family]
    components = raw_metrics.get("components")
    if not isinstance(components, list) or len(components) != len(expected):
        raise ValueError(f"{metric_family} components must match the frozen tuple")
    output = 0.0
    null = 0.0
    for index, ((expected_id, expected_weight), component) in enumerate(
        zip(expected, components, strict=True)
    ):
        if not isinstance(component, Mapping):
            raise ValueError(f"components[{index}] must be an object")
        if component.get("component_id") != expected_id:
            raise ValueError(f"components[{index}] component_id drift")
        weight = _finite_number(component.get("component_weight"), "component_weight")
        if not math.isclose(weight, expected_weight, abs_tol=1e-12):
            raise ValueError(f"{expected_id} component_weight drift")
        output_utility = _finite_number(component.get("output_utility"), "output_utility")
        null_utility = _finite_number(component.get("null_utility"), "null_utility")
        utility_delta = _finite_number(component.get("utility_delta"), "utility_delta")
        if not math.isclose(utility_delta, output_utility - null_utility, abs_tol=1e-10):
            raise ValueError(f"{expected_id} utility_delta is inconsistent")
        scale = _finite_number(component.get("scale"), "scale")
        if scale <= 0:
            raise ValueError(f"{expected_id} scale must be positive")
        output += weight * output_utility
        null += weight * null_utility
    delta = output - null
    for key, expected_value in (
        ("combined_output_utility", output),
        ("combined_null_utility", null),
        ("combined_utility_delta", delta),
    ):
        supplied = _finite_number(raw_metrics.get(key), key)
        if not math.isclose(supplied, expected_value, abs_tol=1e-10):
            raise ValueError(f"{key} is inconsistent with frozen components")
    return delta, dict(raw_metrics)


def _standard_sector_utility(
    raw_metrics: Mapping[str, Any],
) -> tuple[float, dict[str, Any]]:
    direction_forecast = _finite_number(
        raw_metrics.get("direction_forecast_loss"), "direction_forecast_loss"
    )
    direction_null = _finite_number(
        raw_metrics.get("direction_null_loss"), "direction_null_loss"
    )
    direction_delta = direction_null - direction_forecast
    supplied_direction_delta = _finite_number(
        raw_metrics.get("direction_utility_delta"), "direction_utility_delta"
    )
    if not math.isclose(direction_delta, supplied_direction_delta, abs_tol=1e-10):
        raise ValueError("direction_utility_delta is inconsistent")
    security_delta = _finite_number(
        raw_metrics.get("security_utility_delta"), "security_utility_delta"
    )
    semantics = raw_metrics.get("confidence_semantics")
    if semantics == "DIRECTIONAL_UTILITY":
        combined = 0.5 * direction_delta + 0.5 * security_delta
        forbidden_abstention = (
            "abstention_forecast_loss",
            "abstention_null_loss",
            "abstention_utility_delta",
            "abstention_warranted_label",
            "abstention_missed_opportunity_regret",
        )
        if any(raw_metrics.get(field) is not None for field in forbidden_abstention):
            raise ValueError("selected Sector branch cannot carry abstention utility")
    elif semantics == "ABSTENTION_WARRANTED":
        forecast = _finite_number(
            raw_metrics.get("abstention_forecast_loss"),
            "abstention_forecast_loss",
        )
        null = _finite_number(
            raw_metrics.get("abstention_null_loss"), "abstention_null_loss"
        )
        regret = _finite_number(
            raw_metrics.get("abstention_missed_opportunity_regret"),
            "abstention_missed_opportunity_regret",
        )
        combined = null - forecast - regret
        supplied = _finite_number(
            raw_metrics.get("abstention_utility_delta"),
            "abstention_utility_delta",
        )
        if not math.isclose(combined, supplied, abs_tol=1e-10):
            raise ValueError("abstention_utility_delta is inconsistent")
        if not math.isclose(direction_delta, 0.0, abs_tol=1e-10) or not math.isclose(
            security_delta, 0.0, abs_tol=1e-10
        ):
            raise ValueError("overall Sector abstention cannot carry directional skill")
        if raw_metrics.get("confidence_calibration_target") != raw_metrics.get(
            "abstention_warranted_label"
        ):
            raise ValueError("Sector abstention confidence target mismatch")
    else:
        raise ValueError("unknown Sector confidence semantics")
    supplied_combined = _finite_number(
        raw_metrics.get("combined_utility_delta"), "combined_utility_delta"
    )
    if not math.isclose(combined, supplied_combined, abs_tol=1e-10):
        raise ValueError("combined_utility_delta is inconsistent with Sector branch")
    return combined, dict(raw_metrics)


def _relationship_utility(
    raw_metrics: Mapping[str, Any],
) -> tuple[float, dict[str, Any]]:
    metrics = raw_metrics.get("edge_metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("Relationship opportunity metrics must be non-empty")
    candidate_ids: set[str] = set()
    total_weight = 0.0
    weighted_delta = 0.0
    for index, metric in enumerate(metrics):
        if not isinstance(metric, Mapping):
            raise ValueError(f"edge_metrics[{index}] must be an object")
        candidate_id = _required_text(
            metric.get("edge_candidate_id"), f"edge_metrics[{index}].edge_candidate_id"
        )
        if candidate_id in candidate_ids:
            raise ValueError("Relationship edge candidate IDs must be unique")
        candidate_ids.add(candidate_id)
        weight = _finite_number(
            metric.get("materiality_weight"),
            f"edge_metrics[{index}].materiality_weight",
        )
        if weight <= 0:
            raise ValueError("Relationship materiality weights must be positive")
        delta = _finite_number(
            metric.get("edge_utility_delta"),
            f"edge_metrics[{index}].edge_utility_delta",
        )
        total_weight += weight
        weighted_delta += weight * delta
    status = raw_metrics.get("predictive_graph_status")
    if status == "EDGES_PRESENT":
        combined = weighted_delta / total_weight
        supplied_weighted = _finite_number(
            raw_metrics.get("weighted_edge_utility_delta"),
            "weighted_edge_utility_delta",
        )
        if not math.isclose(combined, supplied_weighted, abs_tol=1e-10):
            raise ValueError("weighted_edge_utility_delta is inconsistent")
    elif status == "NO_QUALIFIED_PREDICTIVE_EDGE":
        if any(bool(metric.get("submitted")) for metric in metrics):
            raise ValueError("empty Relationship graph cannot contain submitted edges")
        null = _finite_number(
            raw_metrics.get("graph_abstention_null_loss"),
            "graph_abstention_null_loss",
        )
        forecast = _finite_number(
            raw_metrics.get("graph_abstention_forecast_loss"),
            "graph_abstention_forecast_loss",
        )
        regret = _finite_number(
            raw_metrics.get("graph_abstention_missed_opportunity_regret"),
            "graph_abstention_missed_opportunity_regret",
        )
        combined = null - forecast - regret
    else:
        raise ValueError("unknown Relationship graph status")
    supplied = _finite_number(
        raw_metrics.get("combined_utility_delta"), "combined_utility_delta"
    )
    if not math.isclose(combined, supplied, abs_tol=1e-10):
        raise ValueError("combined_utility_delta is inconsistent with Relationship branch")
    return combined, dict(raw_metrics)


def compute_outcome_utility(
    metric_family: str,
    raw_metrics: Mapping[str, Any],
) -> tuple[float, dict[str, Any]]:
    if metric_family == "MACRO_TRANSMISSION":
        return _macro_utility(raw_metrics)
    if metric_family == "STANDARD_SECTOR":
        return _standard_sector_utility(raw_metrics)
    if metric_family == "RELATIONSHIP":
        return _relationship_utility(raw_metrics)
    if metric_family in DECISION_COMPONENTS:
        return _decision_utility(metric_family, raw_metrics)
    if metric_family != "SUPERINVESTOR":
        raise ValueError(f"unsupported metric family: {metric_family}")
    utility_delta = _finite_number(
        raw_metrics.get("combined_utility_delta"),
        "combined_utility_delta",
    )
    required = {"output_confidence", "pick_metrics", "missed_opportunity_utility"}
    missing = sorted(required - set(raw_metrics))
    if missing:
        raise ValueError(f"{metric_family} raw metrics missing: {', '.join(missing)}")
    return utility_delta, dict(raw_metrics)


def append_agent_outcome_label(
    conn: sqlite3.Connection,
    *,
    audit_revision_id: str,
    realized_outcome_observation_id: str,
    raw_metrics: Mapping[str, Any],
    normalization_reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute and append one deterministic, role-owned normalized score."""
    audit_row = conn.execute(
        "SELECT record_json FROM agent_outcome_eligibility_revisions_v2 "
        "WHERE audit_revision_id = ? AND disposition = 'SCORE'",
        (audit_revision_id,),
    ).fetchone()
    if audit_row is None:
        raise ValueError("outcome label requires a final SCORE audit revision")
    audit = json.loads(audit_row[0])
    newer = conn.execute(
        "SELECT 1 FROM agent_outcome_eligibility_revisions_v2 "
        "WHERE audit_id = ? AND audit_sequence > ? LIMIT 1",
        (audit["audit_id"], audit["audit_sequence"]),
    ).fetchone()
    if newer is not None:
        raise ValueError("outcome label must reference the final audit revision")
    observation_row = conn.execute(
        "SELECT record_json FROM realized_outcome_observations_v2 "
        "WHERE realized_outcome_observation_id = ?",
        (realized_outcome_observation_id,),
    ).fetchone()
    if observation_row is None:
        raise ValueError("realized outcome observation is unavailable")
    observation = json.loads(observation_row[0])
    if observation["scheduled_sample_id"] != audit["scheduled_sample_id"]:
        raise ValueError("realized observation scheduled sample mismatch")
    track = _track_record(conn, audit["track_key_hash"])
    if track["agent_id"] != audit["agent_id"]:
        raise ValueError("label owner does not match evaluation track")
    if track["agent_id"] != "cio" and {
        "cio_portfolio_return",
        "cio_total_pnl",
        "downstream_portfolio_pnl",
    } & set(raw_metrics):
        raise ValueError("CIO outcome cannot label an upstream Agent")
    contract = track["outcome_contract"]
    metric_schema_id = str(contract["metric_schema_id"])
    metric_schema = OUTCOME_METRIC_SCHEMAS.get(metric_schema_id)
    if metric_schema is None:
        raise ValueError(f"unknown outcome metric schema: {metric_schema_id}")
    schema_errors = sorted(
        Draft7Validator(dict(metric_schema)).iter_errors(dict(raw_metrics)),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        first = schema_errors[0]
        path = ".".join(str(item) for item in first.absolute_path) or "$"
        raise ValueError(f"raw outcome metrics schema violation at {path}: {first.message}")
    utility_delta, computed_raw = compute_outcome_utility(
        str(contract["metric_family"]),
        raw_metrics,
    )
    normalization = dict(normalization_reference)
    supplied_hash = normalization.pop("normalization_reference_hash", None)
    if supplied_hash != canonical_hash(normalization):
        raise ValueError("normalization reference hash mismatch")
    if normalization.get("normalization_contract_version") != contract[
        "normalization_contract_version"
    ]:
        raise ValueError("normalization contract version mismatch")
    scale = _finite_number(normalization.get("scale"), "normalization.scale")
    if scale <= 0:
        raise ValueError("normalization scale must be positive")
    normalized_score = _clip(utility_delta / scale, -1, 1)
    existing = conn.execute(
        "SELECT record_json FROM agent_outcome_labels_v2 WHERE audit_revision_id = ?",
        (audit_revision_id,),
    ).fetchone()
    if existing is not None:
        existing_record = json.loads(existing[0])
        immutable_fields = {
            "realized_outcome_observation_id": realized_outcome_observation_id,
            "raw_metrics": computed_raw,
            "utility_delta": utility_delta,
            "normalization_reference": dict(normalization_reference),
            "normalized_score": normalized_score,
        }
        if any(existing_record.get(key) != value for key, value in immutable_fields.items()):
            raise ValueError("immutable outcome label retry mismatch")
        return existing_record
    next_sequence = conn.execute(
        "SELECT COALESCE(MAX(outcome_sequence), 0) + 1 FROM agent_outcome_labels_v2"
    ).fetchone()[0]
    label_identity = {
        "audit_revision_hash": audit["audit_revision_hash"],
        "realized_outcome_observation_hash": observation[
            "realized_outcome_observation_hash"
        ],
        "primary_label_id": contract["primary_label_id"],
    }
    label_id = deterministic_id("agent-outcome-label", label_identity)
    without_hash = {
        "outcome_sequence": next_sequence,
        "outcome_label_id": label_id,
        "audit_revision_id": audit_revision_id,
        "audit_revision_hash": audit["audit_revision_hash"],
        "scheduled_sample_id": audit["scheduled_sample_id"],
        "track_key_hash": audit["track_key_hash"],
        "agent_id": audit["agent_id"],
        "primary_label_id": contract["primary_label_id"],
        "sample_origin": audit["sample_origin"],
        "darwin_evaluation_eligible": audit["darwin_evaluation_eligible"],
        "usage_weight_eligible": audit["usage_weight_eligible"],
        "realized_outcome_observation_id": realized_outcome_observation_id,
        "realized_outcome_observation_hash": observation[
            "realized_outcome_observation_hash"
        ],
        "raw_metrics": computed_raw,
        "utility_delta": utility_delta,
        "normalization_reference": dict(normalization_reference),
        "normalized_score": normalized_score,
        "outcome_due_at": observation["outcome_due_at"],
        "matured_at": observation["matured_at"],
        "contract_versions": audit["contract_versions"],
    }
    record = {**without_hash, "outcome_label_hash": canonical_hash(without_hash)}
    record_json = canonical_json(record)
    _insert_immutable(
        conn,
        table="agent_outcome_labels_v2",
        id_column="outcome_label_id",
        record_id=label_id,
        columns=(
            "outcome_sequence",
            "outcome_label_id",
            "outcome_label_hash",
            "audit_revision_id",
            "scheduled_sample_id",
            "track_key_hash",
            "agent_id",
            "primary_label_id",
            "sample_origin",
            "darwin_evaluation_eligible",
            "usage_weight_eligible",
            "normalized_score",
            "outcome_due_at",
            "matured_at",
            "record_json",
        ),
        values=(
            next_sequence,
            label_id,
            record["outcome_label_hash"],
            audit_revision_id,
            audit["scheduled_sample_id"],
            audit["track_key_hash"],
            audit["agent_id"],
            contract["primary_label_id"],
            audit["sample_origin"],
            int(audit["darwin_evaluation_eligible"]),
            int(audit["usage_weight_eligible"]),
            normalized_score,
            observation["outcome_due_at"],
            observation["matured_at"],
            record_json,
        ),
        record_json=record_json,
    )
    return record


def _window_for_track(
    conn: sqlite3.Connection,
    *,
    track_key_hash: str,
    cutoff_at: str,
    lookback_start: str,
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT outcome_sequence, outcome_label_id, normalized_score,
               outcome_due_at, matured_at
        FROM agent_outcome_labels_v2
        WHERE track_key_hash = ?
          AND sample_origin = 'PRODUCTION_ACTIVE'
          AND darwin_evaluation_eligible = 1
          AND outcome_due_at >= ? AND outcome_due_at <= ?
          AND matured_at <= ?
        ORDER BY outcome_due_at DESC, outcome_sequence DESC
        LIMIT ?
        """,
        (track_key_hash, lookback_start, cutoff_at, cutoff_at, WINDOW_SIZE),
    ).fetchall()
    selected = [
        {
            "outcome_sequence": int(row[0]),
            "outcome_label_id": row[1],
            "normalized_score": float(row[2]),
            "outcome_due_at": row[3],
            "matured_at": row[4],
        }
        for row in reversed(rows)
    ]
    failures = conn.execute(
        """
        SELECT COUNT(*)
        FROM agent_outcome_eligibility_revisions_v2 current
        WHERE current.track_key_hash = ?
          AND current.sample_origin = 'PRODUCTION_ACTIVE'
          AND current.disposition = 'AGENT_FAILURE'
          AND current.recorded_at >= ? AND current.recorded_at <= ?
          AND NOT EXISTS (
            SELECT 1 FROM agent_outcome_eligibility_revisions_v2 newer
            WHERE newer.audit_id = current.audit_id
              AND newer.audit_sequence > current.audit_sequence
          )
        """,
        (track_key_hash, lookback_start, cutoff_at),
    ).fetchone()[0]
    score_count = conn.execute(
        """
        SELECT COUNT(*) FROM agent_outcome_labels_v2
        WHERE track_key_hash = ?
          AND sample_origin = 'PRODUCTION_ACTIVE'
          AND darwin_evaluation_eligible = 1
          AND outcome_due_at >= ? AND outcome_due_at <= ?
          AND matured_at <= ?
        """,
        (track_key_hash, lookback_start, cutoff_at, cutoff_at),
    ).fetchone()[0]
    denominator = score_count + failures
    coverage = score_count / denominator if denominator else 0.0
    mean_score = (
        sum(item["normalized_score"] for item in selected) / len(selected)
        if selected
        else None
    )
    return {
        "scores": selected,
        "n_eligible_scores": len(selected),
        "total_score_count": score_count,
        "agent_failure_count": failures,
        "window_coverage": coverage,
        "mean_normalized_score": mean_score,
        "scoring_window_hash": canonical_hash(selected),
        "max_consumed_outcome_sequence": max(
            (item["outcome_sequence"] for item in selected),
            default=0,
        ),
        "max_consumed_matured_at": max(
            (item["matured_at"] for item in selected),
            default="",
        ),
        "maturity_state": (
            "MATURE"
            if len(selected) == WINDOW_SIZE and coverage >= MINIMUM_WINDOW_COVERAGE
            else "COLD_START"
        ),
    }


def _peer_bands(
    states: Sequence[tuple[str, dict[str, Any]]],
) -> dict[str, str | None]:
    if not states:
        return {}
    ordered = sorted(states, key=lambda item: (-item[1]["mean_normalized_score"], item[0]))
    groups: list[list[tuple[str, dict[str, Any]]]] = []
    for item in ordered:
        if not groups or abs(
            item[1]["mean_normalized_score"] - groups[-1][0][1]["mean_normalized_score"]
        ) > TIE_EPSILON:
            groups.append([item])
        else:
            groups[-1].append(item)
    n = len(ordered)
    result: dict[str, str | None] = {}
    rank_start = 1
    for group in groups:
        rank_end = rank_start + len(group) - 1
        midrank = (rank_start + rank_end) / 2
        if len(groups) == 1:
            quartile = "Q2"
        elif n == 3:
            quartile = ("Q1", "Q2", "Q4")[round(midrank) - 1]
        else:
            quartile = f"Q{min(math.floor((midrank - 1) * 4 / n) + 1, 4)}"
        for track_hash, _ in group:
            result[track_hash] = quartile
        rank_start = rank_end + 1
    return result


def _self_band(mean_score: float) -> str:
    if mean_score >= 0.25:
        return "Q1"
    if mean_score >= 0:
        return "Q2"
    if mean_score > -0.25:
        return "Q3"
    return "Q4"


def refresh_evaluation_windows(
    conn: sqlite3.Connection,
    *,
    production_variant_roster_revision_id: str,
    cutoff_at: str,
    trading_dates: Sequence[str],
) -> list[dict[str, Any]]:
    """Refresh all 28 evaluation windows without creating Decision weights."""
    revision_row = conn.execute(
        "SELECT record_json FROM darwinian_v2_production_variant_roster_revisions "
        "WHERE production_variant_roster_revision_id = ? AND readiness = 'READY'",
        (production_variant_roster_revision_id,),
    ).fetchone()
    if revision_row is None:
        raise ValueError("READY roster revision is unavailable")
    revision = json.loads(revision_row[0])
    calendar_window = derive_darwin_calendar_window(
        trading_dates=trading_dates,
        cutoff_at=cutoff_at,
        require_update_slot=False,
    )
    lookback_start = str(calendar_window["lookback_start"])
    by_scope: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    records: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for track_hash in revision["evaluation_track_key_hashes"]:
        track = _track_record(conn, track_hash)
        state = _window_for_track(
            conn,
            track_key_hash=track_hash,
            cutoff_at=cutoff_at,
            lookback_start=lookback_start,
        )
        records[track_hash] = (track, state)
        if state["maturity_state"] == "MATURE":
            by_scope[track["rank_scope"]].append((track_hash, state))

    bands: dict[str, str | None] = {}
    for scope, states in by_scope.items():
        if scope in PEER_MINIMUMS:
            if len(states) >= PEER_MINIMUMS[scope]:
                bands.update(_peer_bands(states))
        else:
            for track_hash, state in states:
                bands[track_hash] = _self_band(state["mean_normalized_score"])

    output: list[dict[str, Any]] = []
    for track_hash in revision["evaluation_track_key_hashes"]:
        track, state = records[track_hash]
        performance_band = bands.get(track_hash)
        checkpoint_id = deterministic_id(
            "darwin-evaluation-window",
            {
                "track_key_hash": track_hash,
                "cutoff_at": cutoff_at,
                "scoring_window_hash": state["scoring_window_hash"],
            },
        )
        without_hash = {
            "evaluation_checkpoint_id": checkpoint_id,
            "track_key_hash": track_hash,
            "production_variant_roster_revision_id": production_variant_roster_revision_id,
            "rank_scope": track["rank_scope"],
            "darwin_application_mode": track["darwin_application_mode"],
            "cutoff_at": cutoff_at,
            **calendar_window,
            **state,
            "performance_band": performance_band,
            "knot_deficit": (
                max(0.0, -state["mean_normalized_score"])
                if track["darwin_application_mode"] == "EVOLUTION_ONLY"
                and state["maturity_state"] == "MATURE"
                else None
            ),
            "recorded_at": cutoff_at,
        }
        checkpoint = {
            **without_hash,
            "evaluation_checkpoint_hash": canonical_hash(without_hash),
        }
        record_json = canonical_json(checkpoint)
        _insert_immutable(
            conn,
            table="darwinian_v2_evaluation_window_checkpoints",
            id_column="evaluation_checkpoint_id",
            record_id=checkpoint_id,
            columns=(
                "evaluation_checkpoint_id",
                "evaluation_checkpoint_hash",
                "track_key_hash",
                "production_variant_roster_revision_id",
                "rank_scope",
                "cutoff_at",
                "maturity_state",
                "performance_band",
                "n_eligible_scores",
                "window_coverage",
                "mean_normalized_score",
                "scoring_window_hash",
                "max_consumed_outcome_sequence",
                "recorded_at",
                "record_json",
            ),
            values=(
                checkpoint_id,
                checkpoint["evaluation_checkpoint_hash"],
                track_hash,
                production_variant_roster_revision_id,
                track["rank_scope"],
                cutoff_at,
                state["maturity_state"],
                performance_band,
                state["n_eligible_scores"],
                state["window_coverage"],
                state["mean_normalized_score"],
                state["scoring_window_hash"],
                state["max_consumed_outcome_sequence"],
                cutoff_at,
                record_json,
            ),
            record_json=record_json,
        )
        output.append(checkpoint)
    return output


def _current_weight_record(
    conn: sqlite3.Connection,
    usage_track_key_hash: str,
    cutoff_at: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT record_json
        FROM darwinian_v2_usage_weight_records w
        WHERE usage_track_key_hash = ? AND effective_at <= ?
          AND (
            update_event_id IS NULL OR EXISTS (
              SELECT 1 FROM darwinian_v2_usage_weight_batch_revisions b
              WHERE b.update_event_id = w.update_event_id AND b.status = 'PUBLISHED'
            )
          )
        ORDER BY effective_at DESC, rowid DESC LIMIT 1
        """,
        (usage_track_key_hash, cutoff_at),
    ).fetchone()
    if row is None:
        raise ValueError(f"no published weight for {usage_track_key_hash}")
    return json.loads(row[0])


def _next_weight(previous: float, band: str) -> float:
    if band == "Q1":
        return _clip(previous * Q1_MULTIPLIER, WEIGHT_MIN, WEIGHT_MAX)
    if band == "Q4":
        return _clip(previous * Q4_MULTIPLIER, WEIGHT_MIN, WEIGHT_MAX)
    return previous


def publish_usage_weight_updates(
    conn: sqlite3.Connection,
    *,
    production_variant_roster_revision_id: str,
    cutoff_at: str,
    trading_dates: Sequence[str],
) -> list[dict[str, Any]]:
    """Atomically publish at most one deterministic batch per usage rank scope."""
    calendar_window = derive_darwin_calendar_window(
        trading_dates=trading_dates,
        cutoff_at=cutoff_at,
        require_update_slot=True,
    )
    update_slot_id = str(calendar_window["update_slot_id"])
    checkpoints = refresh_evaluation_windows(
        conn,
        production_variant_roster_revision_id=production_variant_roster_revision_id,
        cutoff_at=cutoff_at,
        trading_dates=trading_dates,
    )
    revision_row = conn.execute(
        "SELECT record_json FROM darwinian_v2_production_variant_roster_revisions "
        "WHERE production_variant_roster_revision_id = ?",
        (production_variant_roster_revision_id,),
    ).fetchone()
    if revision_row is None:
        raise ValueError("roster revision is unavailable")
    revision = json.loads(revision_row[0])
    checkpoint_by_track = {row["track_key_hash"]: row for row in checkpoints}
    usage_rows = conn.execute(
        "SELECT usage_track_key_hash, evaluation_track_key_hash, agent_id "
        "FROM darwinian_v2_usage_tracks WHERE production_variant_roster_id = ?",
        (revision["production_variant_roster_id"],),
    ).fetchall()
    revision_usage = set(revision["usage_track_key_hashes"])
    if {row[0] for row in usage_rows if row[0] in revision_usage} != revision_usage:
        raise ValueError("roster revision usage tracks do not resolve exactly")
    by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for usage_hash, track_hash, agent_id in usage_rows:
        if usage_hash not in revision_usage:
            continue
        track = _track_record(conn, track_hash)
        if track["darwin_application_mode"] != "DOWNSTREAM_USAGE_WEIGHT":
            raise ValueError("Decision evaluation track cannot enter a usage batch")
        by_scope[track["rank_scope"]].append(
            {
                "usage_track_key_hash": usage_hash,
                "track_key_hash": track_hash,
                "agent_id": agent_id,
                "track": track,
                "window": checkpoint_by_track[track_hash],
            }
        )

    published: list[dict[str, Any]] = []
    for scope in sorted(by_scope):
        members = sorted(by_scope[scope], key=lambda item: item["usage_track_key_hash"])
        previous_records = {
            item["usage_track_key_hash"]: _current_weight_record(
                conn, item["usage_track_key_hash"], cutoff_at
            )
            for item in members
        }
        prior_sequences: dict[str, int] = {}
        for item in members:
            row = conn.execute(
                "SELECT max_consumed_outcome_sequence FROM "
                "darwinian_v2_usage_weight_update_checkpoints "
                "WHERE usage_track_key_hash = ? ORDER BY recorded_at DESC, rowid DESC LIMIT 1",
                (item["usage_track_key_hash"],),
            ).fetchone()
            prior_sequences[item["usage_track_key_hash"]] = int(row[0]) if row else 0
        scope_has_new = any(
            item["window"]["max_consumed_outcome_sequence"]
            > prior_sequences[item["usage_track_key_hash"]]
            for item in members
        )
        mature_count = sum(item["window"]["maturity_state"] == "MATURE" for item in members)
        decisions: list[dict[str, Any]] = []
        for item in members:
            usage_hash = item["usage_track_key_hash"]
            window = item["window"]
            previous = previous_records[usage_hash]
            if window["maturity_state"] != "MATURE":
                disposition = "HELD_INSUFFICIENT_WINDOW"
            elif scope in PEER_MINIMUMS and mature_count < PEER_MINIMUMS[scope]:
                disposition = "HELD_INSUFFICIENT_PEERS"
            elif not scope_has_new:
                disposition = "NO_NEW_OUTCOME"
            else:
                disposition = "UPDATED"
            band = window["performance_band"]
            new_weight = (
                _next_weight(float(previous["darwin_weight"]), str(band))
                if disposition == "UPDATED" and band is not None
                else float(previous["darwin_weight"])
            )
            decisions.append(
                {
                    **item,
                    "previous": previous,
                    "update_disposition": disposition,
                    "resulting_weight": new_weight,
                }
            )
        event_identity = {
            "production_variant_roster_id": revision["production_variant_roster_id"],
            "rank_scope": scope,
            "rank_scope_contract_version": members[0]["track"][
                "rank_scope_contract_version"
            ],
            "update_slot_id": update_slot_id,
            "member_usage_track_key_hashes": [
                item["usage_track_key_hash"] for item in members
            ],
            "outcome_sequences": [
                item["window"]["max_consumed_outcome_sequence"] for item in members
            ],
            "scoring_window_hashes": [
                item["window"]["scoring_window_hash"] for item in members
            ],
        }
        update_event_id = deterministic_id("darwin-weight-update", event_identity)
        existing = conn.execute(
            "SELECT record_json FROM darwinian_v2_usage_weight_batch_revisions "
            "WHERE update_event_id = ? AND status = 'PUBLISHED'",
            (update_event_id,),
        ).fetchone()
        if existing is not None:
            published.append(json.loads(existing[0]))
            continue

        for decision in decisions:
            if decision["update_disposition"] != "UPDATED":
                decision["new_weight_record_id"] = decision["previous"]["weight_record_id"]
                continue
            decision["new_weight_record_id"] = deterministic_id(
                "darwin-weight-mature-update",
                {
                    "usage_track_key_hash": decision["usage_track_key_hash"],
                    "update_event_id": update_event_id,
                },
            )
        result_weight_ids = [item["new_weight_record_id"] for item in decisions]
        snapshot_without_hash = {
            "schema_version": "darwinian_usage_weight_update_snapshot_v2",
            "update_event_id": update_event_id,
            "production_variant_roster_id": revision["production_variant_roster_id"],
            "production_variant_roster_revision_id": production_variant_roster_revision_id,
            "rank_scope": scope,
            "update_slot_id": update_slot_id,
            "effective_at": cutoff_at,
            "resulting_weight_record_ids": result_weight_ids,
        }
        snapshot_id = deterministic_id("darwin-update-snapshot", snapshot_without_hash)
        snapshot_with_id = {"darwinian_snapshot_id": snapshot_id, **snapshot_without_hash}
        snapshot = {
            **snapshot_with_id,
            "darwinian_snapshot_hash": canonical_hash(snapshot_with_id),
        }
        prepared_without_hash = {
            "update_event_id": update_event_id,
            "production_variant_roster_id": revision["production_variant_roster_id"],
            "production_variant_roster_revision_id": production_variant_roster_revision_id,
            "rank_scope": scope,
            "update_slot_id": update_slot_id,
            "rank_scope_contract_version": members[0]["track"][
                "rank_scope_contract_version"
            ],
            "member_usage_track_key_hashes": [
                item["usage_track_key_hash"] for item in members
            ],
            "consumed_outcome_set_hash": canonical_hash(
                [
                    score["outcome_label_id"]
                    for item in members
                    for score in item["window"]["scores"]
                ]
            ),
            "previous_weight_record_ids": [
                item["previous"]["weight_record_id"] for item in decisions
            ],
            "new_weight_record_ids": result_weight_ids,
            "darwinian_snapshot_id": snapshot_id,
            "recorded_at": cutoff_at,
        }
        prepared_id = deterministic_id(
            "darwin-weight-batch-revision",
            {"update_event_id": update_event_id, "status": "PREPARED"},
        )
        prepared_body = {
            "batch_revision_id": prepared_id,
            "supersedes_revision_id": None,
            **prepared_without_hash,
            "status": "PREPARED",
        }
        prepared = {
            **prepared_body,
            "batch_revision_hash": canonical_hash(prepared_body),
        }
        prepared_json = canonical_json(prepared)
        _insert_immutable(
            conn,
            table="darwinian_v2_usage_weight_batch_revisions",
            id_column="batch_revision_id",
            record_id=prepared_id,
            columns=(
                "batch_revision_id",
                "batch_revision_hash",
                "update_event_id",
                "supersedes_revision_id",
                "production_variant_roster_id",
                "production_variant_roster_revision_id",
                "rank_scope",
                "update_slot_id",
                "status",
                "recorded_at",
                "record_json",
            ),
            values=(
                prepared_id,
                prepared["batch_revision_hash"],
                update_event_id,
                None,
                revision["production_variant_roster_id"],
                production_variant_roster_revision_id,
                scope,
                update_slot_id,
                "PREPARED",
                cutoff_at,
                prepared_json,
            ),
            record_json=prepared_json,
        )
        conn.execute("SAVEPOINT publish_darwinian_scope")
        try:
            for decision in decisions:
                if decision["update_disposition"] == "UPDATED":
                    weight_without_hash = {
                        "weight_record_id": decision["new_weight_record_id"],
                        "usage_track_key_hash": decision["usage_track_key_hash"],
                        "record_kind": "MATURE_UPDATE",
                        "darwin_weight": decision["resulting_weight"],
                        "previous_weight_record_id": decision["previous"]["weight_record_id"],
                        "n_eligible_scores": decision["window"]["n_eligible_scores"],
                        "scoring_window_hash": decision["window"]["scoring_window_hash"],
                        "update_event_id": update_event_id,
                        "effective_at": cutoff_at,
                    }
                    weight = {
                        **weight_without_hash,
                        "weight_record_hash": canonical_hash(weight_without_hash),
                    }
                    weight_json = canonical_json(weight)
                    _insert_immutable(
                        conn,
                        table="darwinian_v2_usage_weight_records",
                        id_column="weight_record_id",
                        record_id=weight["weight_record_id"],
                        columns=(
                            "weight_record_id",
                            "weight_record_hash",
                            "usage_track_key_hash",
                            "record_kind",
                            "darwin_weight",
                            "previous_weight_record_id",
                            "n_eligible_scores",
                            "scoring_window_hash",
                            "update_event_id",
                            "effective_at",
                            "record_json",
                        ),
                        values=(
                            weight["weight_record_id"],
                            weight["weight_record_hash"],
                            weight["usage_track_key_hash"],
                            "MATURE_UPDATE",
                            weight["darwin_weight"],
                            weight["previous_weight_record_id"],
                            weight["n_eligible_scores"],
                            weight["scoring_window_hash"],
                            update_event_id,
                            cutoff_at,
                            weight_json,
                        ),
                        record_json=weight_json,
                    )
                checkpoint_without_hash = {
                    "checkpoint_id": deterministic_id(
                        "darwin-weight-checkpoint",
                        {
                            "usage_track_key_hash": decision["usage_track_key_hash"],
                            "update_event_id": update_event_id,
                        },
                    ),
                    "usage_track_key_hash": decision["usage_track_key_hash"],
                    "production_variant_roster_id": revision[
                        "production_variant_roster_id"
                    ],
                    "production_variant_roster_revision_id": production_variant_roster_revision_id,
                    "rank_scope": scope,
                    "update_slot_id": update_slot_id,
                    "update_disposition": decision["update_disposition"],
                    "scoring_window_hash": decision["window"]["scoring_window_hash"],
                    "max_consumed_outcome_sequence": decision["window"][
                        "max_consumed_outcome_sequence"
                    ],
                    "consumed_outcome_set_hash": canonical_hash(
                        [score["outcome_label_id"] for score in decision["window"]["scores"]]
                    ),
                    "max_consumed_matured_at": decision["window"][
                        "max_consumed_matured_at"
                    ],
                    "previous_weight_record_id": decision["previous"]["weight_record_id"],
                    "resulting_weight_record_id": decision["new_weight_record_id"],
                    "update_event_id": update_event_id,
                    "performance_band": decision["window"]["performance_band"],
                    "recorded_at": cutoff_at,
                }
                checkpoint = {
                    **checkpoint_without_hash,
                    "checkpoint_hash": canonical_hash(checkpoint_without_hash),
                }
                checkpoint_json = canonical_json(checkpoint)
                _insert_immutable(
                    conn,
                    table="darwinian_v2_usage_weight_update_checkpoints",
                    id_column="checkpoint_id",
                    record_id=checkpoint["checkpoint_id"],
                    columns=(
                        "checkpoint_id",
                        "checkpoint_hash",
                        "usage_track_key_hash",
                        "production_variant_roster_revision_id",
                        "rank_scope",
                        "update_slot_id",
                        "update_disposition",
                        "max_consumed_outcome_sequence",
                        "update_event_id",
                        "recorded_at",
                        "record_json",
                    ),
                    values=(
                        checkpoint["checkpoint_id"],
                        checkpoint["checkpoint_hash"],
                        checkpoint["usage_track_key_hash"],
                        production_variant_roster_revision_id,
                        scope,
                        update_slot_id,
                        checkpoint["update_disposition"],
                        checkpoint["max_consumed_outcome_sequence"],
                        update_event_id,
                        cutoff_at,
                        checkpoint_json,
                    ),
                    record_json=checkpoint_json,
                )
            snapshot_json = canonical_json(snapshot)
            _insert_immutable(
                conn,
                table="darwinian_v2_usage_weight_snapshots",
                id_column="darwinian_snapshot_id",
                record_id=snapshot_id,
                columns=(
                    "darwinian_snapshot_id",
                    "darwinian_snapshot_hash",
                    "update_event_id",
                    "production_variant_roster_id",
                    "production_variant_roster_revision_id",
                    "rank_scope",
                    "update_slot_id",
                    "effective_at",
                    "record_json",
                ),
                values=(
                    snapshot_id,
                    snapshot["darwinian_snapshot_hash"],
                    update_event_id,
                    revision["production_variant_roster_id"],
                    production_variant_roster_revision_id,
                    scope,
                    update_slot_id,
                    cutoff_at,
                    snapshot_json,
                ),
                record_json=snapshot_json,
            )
            published_id = deterministic_id(
                "darwin-weight-batch-revision",
                {"update_event_id": update_event_id, "status": "PUBLISHED"},
            )
            published_body = {
                "batch_revision_id": published_id,
                "supersedes_revision_id": prepared_id,
                **prepared_without_hash,
                "status": "PUBLISHED",
            }
            published_record = {
                **published_body,
                "batch_revision_hash": canonical_hash(published_body),
            }
            published_json = canonical_json(published_record)
            _insert_immutable(
                conn,
                table="darwinian_v2_usage_weight_batch_revisions",
                id_column="batch_revision_id",
                record_id=published_id,
                columns=(
                    "batch_revision_id",
                    "batch_revision_hash",
                    "update_event_id",
                    "supersedes_revision_id",
                    "production_variant_roster_id",
                    "production_variant_roster_revision_id",
                    "rank_scope",
                    "update_slot_id",
                    "status",
                    "recorded_at",
                    "record_json",
                ),
                values=(
                    published_id,
                    published_record["batch_revision_hash"],
                    update_event_id,
                    prepared_id,
                    revision["production_variant_roster_id"],
                    production_variant_roster_revision_id,
                    scope,
                    update_slot_id,
                    "PUBLISHED",
                    cutoff_at,
                    published_json,
                ),
                record_json=published_json,
            )
            conn.execute("RELEASE SAVEPOINT publish_darwinian_scope")
            published.append(published_record)
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT publish_darwinian_scope")
            conn.execute("RELEASE SAVEPOINT publish_darwinian_scope")
            aborted_id = deterministic_id(
                "darwin-weight-batch-revision",
                {"update_event_id": update_event_id, "status": "ABORTED"},
            )
            aborted_body = {
                "batch_revision_id": aborted_id,
                "supersedes_revision_id": prepared_id,
                **prepared_without_hash,
                "status": "ABORTED",
            }
            aborted = {
                **aborted_body,
                "batch_revision_hash": canonical_hash(aborted_body),
            }
            conn.execute(
                """
                INSERT OR IGNORE INTO darwinian_v2_usage_weight_batch_revisions (
                    batch_revision_id, batch_revision_hash, update_event_id,
                    supersedes_revision_id, production_variant_roster_id,
                    production_variant_roster_revision_id, rank_scope,
                    update_slot_id, status, recorded_at, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ABORTED', ?, ?)
                """,
                (
                    aborted_id,
                    aborted["batch_revision_hash"],
                    update_event_id,
                    prepared_id,
                    revision["production_variant_roster_id"],
                    production_variant_roster_revision_id,
                    scope,
                    update_slot_id,
                    cutoff_at,
                    canonical_json(aborted),
                ),
            )
            raise
    return published


__all__ = [
    "MAXIMUM_LOOKBACK_TRADING_DAYS",
    "MINIMUM_WINDOW_COVERAGE",
    "PEER_MINIMUMS",
    "WINDOW_SIZE",
    "append_agent_outcome_label",
    "append_outcome_eligibility_revision",
    "append_realized_outcome_observation",
    "compute_outcome_utility",
    "derive_darwin_calendar_window",
    "freeze_evaluation_opportunity_set",
    "publish_usage_weight_updates",
    "refresh_evaluation_windows",
]

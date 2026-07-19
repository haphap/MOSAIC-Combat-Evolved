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
KNOT_SAMPLE_ORIGINS = {
    "KNOT_RESEARCH_SHADOW",
    "KNOT_POST_PROMOTION_CHAMPION_SHADOW",
}
KNOT_LINEAGE_FIELDS = (
    "knot_pair_id",
    "knot_pair_input_hash",
    "research_pair_side",
    "capability_id",
    "capability_signature_hash",
    "snapshot_bundle_id",
    "snapshot_bundle_hash",
    "runtime_input_hash",
    "prompt_behavior_version",
    "execution_behavior_version",
    "evaluation_object_hash",
)
KNOT_EXECUTION_CONTEXT_FIELDS = frozenset(
    {
        "production_variant_roster_id",
        "production_variant_roster_revision_id",
        "execution_behavior_release_id",
        "cohort_id",
        "language",
        "track_key_hash",
        "agent_id",
    }
)
EVALUATION_TRACK_KEY_FIELDS = (
    "production_variant_roster_id",
    "cohort_id",
    "language",
    "agent_id",
    "darwin_application_mode",
    "agent_contract_version",
    "prompt_behavior_version",
    "execution_behavior_version",
    "component_weight_contract_version",
    "reliability_adapter_contract_version",
    "confidence_semantics_contract_version",
    "outcome_contract_version",
    "scoring_contract_version",
    "sample_schedule_contract_version",
    "rank_scope_contract_version",
    "rank_scope",
    "primary_label_id",
)
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


def _required_sha256(value: Any, field: str) -> str:
    text = _required_text(value, field)
    digest = text.removeprefix("sha256:")
    if (
        not text.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{field} must be a sha256 identifier")
    return text


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
    track_key_hash = _required_sha256(track_key_hash, "track_key_hash")
    stored_fields = (
        "track_key_hash",
        *EVALUATION_TRACK_KEY_FIELDS,
        "first_registered_roster_revision_id",
        "registered_at",
    )
    row = conn.execute(
        f"SELECT {', '.join(stored_fields)}, contract_json "
        "FROM darwinian_v2_evaluation_tracks WHERE track_key_hash = ?",
        (track_key_hash,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown Darwinian evaluation track: {track_key_hash}")
    record = json.loads(row[len(stored_fields)])
    if not isinstance(record, dict):
        raise ValueError("evaluation track contract must be an object")
    if record.get("track_key_hash") != track_key_hash:
        raise ValueError("evaluation track record identity mismatch")
    if canonical_hash(
        {field: record.get(field) for field in EVALUATION_TRACK_KEY_FIELDS}
    ) != track_key_hash:
        raise ValueError("evaluation track key hash mismatch")
    for index, field in enumerate(stored_fields):
        if row[index] != record.get(field):
            raise ValueError(f"evaluation track {field} column/record mismatch")
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


def _load_record_json(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
    record_id: str,
) -> dict[str, Any]:
    try:
        row = conn.execute(
            f"SELECT record_json FROM {table} WHERE {id_column} = ?",
            (record_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise ValueError(f"required KNOT ledger is unavailable: {table}") from exc
    if row is None:
        raise ValueError(f"unknown immutable record in {table}: {record_id}")
    record = json.loads(row[0])
    if not isinstance(record, dict):
        raise ValueError(f"invalid immutable record in {table}: {record_id}")
    return record


def _load_ready_roster_revision(
    conn: sqlite3.Connection,
    *,
    execution_context: Mapping[str, Any],
    context_name: str,
) -> dict[str, Any]:
    revision_id = _required_text(
        execution_context.get("production_variant_roster_revision_id"),
        f"{context_name}.production_variant_roster_revision_id",
    )
    revision = _load_record_json(
        conn,
        table="darwinian_v2_production_variant_roster_revisions",
        id_column="production_variant_roster_revision_id",
        record_id=revision_id,
    )
    if revision.get("production_variant_roster_revision_id") != revision_id:
        raise ValueError(f"{context_name} roster revision identity mismatch")
    revision_hash = _required_sha256(
        revision.get("production_variant_roster_revision_hash"),
        "production_variant_roster_revision_hash",
    )
    if revision_hash != canonical_hash(
        {
            key: value
            for key, value in revision.items()
            if key != "production_variant_roster_revision_hash"
        }
    ):
        raise ValueError(f"{context_name} roster revision hash mismatch")
    if revision.get("readiness") != "READY":
        raise ValueError(f"{context_name} roster revision is not READY")
    for field in (
        "production_variant_roster_id",
        "production_variant_roster_revision_id",
        "execution_behavior_release_id",
        "cohort_id",
        "language",
    ):
        if revision.get(field) != execution_context.get(field):
            raise ValueError(f"{context_name} execution context {field} mismatch")
    evaluation_track_hashes = revision.get("evaluation_track_key_hashes")
    if not isinstance(evaluation_track_hashes, list) or (
        execution_context.get("track_key_hash") not in evaluation_track_hashes
    ):
        raise ValueError(f"{context_name} execution track is outside the roster")
    return revision


def _load_knot_pair_context(
    conn: sqlite3.Connection,
    *,
    knot_pair_id: str,
    research_pair_side: str,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    if research_pair_side not in {"CHAMPION", "CANDIDATE"}:
        raise ValueError("KNOT research_pair_side must be CHAMPION or CANDIDATE")
    knot_pair_id = _required_text(knot_pair_id, "knot_pair_id")
    pair = _load_record_json(
        conn,
        table="knot_pair_input_sets_v2",
        id_column="knot_pair_id",
        record_id=knot_pair_id,
    )
    if pair.get("knot_pair_id") != knot_pair_id:
        raise ValueError("KNOT pair record identity mismatch")
    pair_hash = _required_sha256(
        pair.get("knot_pair_input_hash"), "knot_pair_input_hash"
    )
    if pair_hash != canonical_hash(
        {key: value for key, value in pair.items() if key != "knot_pair_input_hash"}
    ):
        raise ValueError("KNOT pair input hash mismatch")
    sample_origin = pair.get("sample_origin")
    if sample_origin not in KNOT_SAMPLE_ORIGINS:
        raise ValueError("KNOT pair has an invalid sample origin")
    research_track = _load_record_json(
        conn,
        table="knot_research_tracks_v2",
        id_column="knot_research_track_id",
        record_id=_required_text(
            pair.get("knot_research_track_id"), "knot_research_track_id"
        ),
    )
    if research_track.get("knot_research_track_id") != pair.get(
        "knot_research_track_id"
    ):
        raise ValueError("KNOT research track record identity mismatch")
    research_track_hash = _required_sha256(
        research_track.get("knot_research_track_hash"),
        "knot_research_track_hash",
    )
    if research_track_hash != canonical_hash(
        {
            key: value
            for key, value in research_track.items()
            if key != "knot_research_track_hash"
        }
    ):
        raise ValueError("KNOT research track hash mismatch")
    if pair.get("knot_research_track_hash") != research_track_hash:
        raise ValueError("KNOT pair research track hash mismatch")
    original_context = {
        "production_variant_roster_id": research_track.get(
            "production_variant_roster_id"
        ),
        "production_variant_roster_revision_id": research_track.get(
            "production_variant_roster_revision_id"
        ),
        "execution_behavior_release_id": research_track.get(
            "execution_behavior_release_id"
        ),
        "cohort_id": research_track.get("cohort_id"),
        "language": research_track.get("language"),
        "track_key_hash": research_track.get(
            "target_evaluation_track_key_hash"
        ),
        "agent_id": research_track.get("agent_id"),
    }
    for field in KNOT_EXECUTION_CONTEXT_FIELDS - {"track_key_hash"}:
        _required_text(original_context.get(field), f"research_track.{field}")
    _required_sha256(
        original_context.get("track_key_hash"),
        "research_track.target_evaluation_track_key_hash",
    )
    if original_context["language"] not in {"en", "zh"}:
        raise ValueError("KNOT research track language is invalid")
    _load_ready_roster_revision(
        conn,
        execution_context=original_context,
        context_name="KNOT research",
    )
    original_evaluation_track = _track_record(
        conn, str(original_context["track_key_hash"])
    )
    for field in (
        "production_variant_roster_id",
        "cohort_id",
        "language",
        "agent_id",
    ):
        if original_evaluation_track.get(field) != original_context.get(field):
            raise ValueError(f"KNOT research evaluation track {field} mismatch")
    if (
        research_track.get("champion_prompt_behavior_version")
        != original_evaluation_track.get("prompt_behavior_version")
        or research_track.get("champion_execution_behavior_version")
        != original_evaluation_track.get("execution_behavior_version")
    ):
        raise ValueError("KNOT champion behavior does not match the research track")
    pair_phase = pair.get("pair_phase", "RESEARCH")
    raw_context = pair.get("execution_context")
    if raw_context is None:
        if pair_phase != "RESEARCH":
            raise ValueError("post-promotion KNOT pair has no execution context")
        execution_context = original_context
    else:
        if not isinstance(raw_context, Mapping) or set(raw_context) != (
            KNOT_EXECUTION_CONTEXT_FIELDS
        ):
            raise ValueError("KNOT pair execution context fields mismatch")
        execution_context = dict(raw_context)
        for field in KNOT_EXECUTION_CONTEXT_FIELDS - {"track_key_hash"}:
            _required_text(
                execution_context.get(field), f"execution_context.{field}"
            )
        _required_sha256(
            execution_context.get("track_key_hash"),
            "execution_context.track_key_hash",
        )
        if execution_context["language"] not in {"en", "zh"}:
            raise ValueError("KNOT pair execution context language is invalid")
    if execution_context.get("agent_id") != research_track.get("agent_id"):
        raise ValueError("KNOT pair execution context Agent mismatch")
    if pair_phase == "RESEARCH":
        if sample_origin != "KNOT_RESEARCH_SHADOW":
            raise ValueError("research KNOT pair sample origin mismatch")
        if execution_context != original_context:
            raise ValueError("research KNOT pair changed its execution context")
        if pair.get("promotion_revision_id") not in {None, ""}:
            raise ValueError("research KNOT pair cannot carry a promotion revision")
    elif pair_phase == "POST_PROMOTION_SHADOW":
        if sample_origin != "KNOT_POST_PROMOTION_CHAMPION_SHADOW":
            raise ValueError("post-promotion KNOT pair sample origin mismatch")
        for field in (
            "production_variant_roster_id",
            "cohort_id",
            "language",
            "agent_id",
        ):
            if execution_context.get(field) != original_context.get(field):
                raise ValueError(
                    f"post-promotion KNOT pair changed {field} identity"
                )
        promotion_revision_id = _required_text(
            pair.get("promotion_revision_id"), "promotion_revision_id"
        )
        promotion = _load_record_json(
            conn,
            table="knot_promotion_revisions_v2",
            id_column="knot_promotion_revision_id",
            record_id=promotion_revision_id,
        )
        promotion_hash = _required_sha256(
            promotion.get("knot_promotion_revision_hash"),
            "knot_promotion_revision_hash",
        )
        if promotion_hash != canonical_hash(
            {
                key: value
                for key, value in promotion.items()
                if key != "knot_promotion_revision_hash"
            }
        ):
            raise ValueError("KNOT promotion revision hash mismatch")
        for field, expected in (
            ("knot_promotion_revision_id", promotion_revision_id),
            ("knot_research_track_id", research_track["knot_research_track_id"]),
            ("knot_research_track_hash", research_track_hash),
            ("disposition", "PROMOTE"),
            (
                "new_production_variant_roster_revision_id",
                execution_context["production_variant_roster_revision_id"],
            ),
            (
                "new_execution_behavior_release_id",
                execution_context["execution_behavior_release_id"],
            ),
        ):
            if promotion.get(field) != expected:
                raise ValueError(f"KNOT promotion revision {field} mismatch")
        promoted_revision = _load_ready_roster_revision(
            conn,
            execution_context=execution_context,
            context_name="KNOT promoted",
        )
        promoted_revision_hash = _required_sha256(
            promoted_revision.get("production_variant_roster_revision_hash"),
            "production_variant_roster_revision_hash",
        )
        if promotion.get("new_production_variant_roster_revision_hash") != (
            promoted_revision_hash
        ):
            raise ValueError("KNOT promotion revision roster hash mismatch")
    else:
        raise ValueError("KNOT pair has an invalid pair phase")
    track_key_hash = _required_sha256(
        execution_context.get("track_key_hash"), "execution_context.track_key_hash"
    )
    evaluation_track = _track_record(conn, track_key_hash)
    for field in (
        "production_variant_roster_id",
        "cohort_id",
        "language",
        "agent_id",
    ):
        if evaluation_track.get(field) != execution_context.get(field):
            raise ValueError(f"KNOT execution/evaluation track {field} mismatch")
    for field in EVALUATION_TRACK_KEY_FIELDS:
        if field in {"prompt_behavior_version", "execution_behavior_version"}:
            continue
        if evaluation_track.get(field) != original_evaluation_track.get(field):
            raise ValueError(f"KNOT promoted evaluation track changed {field}")
    capability_key = f"{research_pair_side.lower()}_capability"
    capability = pair.get(capability_key)
    if not isinstance(capability, dict):
        raise ValueError(f"KNOT pair has no {research_pair_side} capability")
    for field in ("snapshot_bundle_id", "snapshot_bundle_hash"):
        if capability.get(field) != pair.get(field):
            raise ValueError(f"KNOT {research_pair_side} capability {field} mismatch")
    _required_text(capability.get("capability_id"), "capability_id")
    _required_sha256(
        capability.get("capability_signature_hash"),
        "capability_signature_hash",
    )
    _required_text(
        research_track.get(
            f"{research_pair_side.lower()}_prompt_behavior_version"
        ),
        "prompt_behavior_version",
    )
    _required_text(
        research_track.get(
            f"{research_pair_side.lower()}_execution_behavior_version"
        ),
        "execution_behavior_version",
    )
    if pair_phase == "POST_PROMOTION_SHADOW" and (
        research_track.get("candidate_prompt_behavior_version")
        != evaluation_track.get("prompt_behavior_version")
        or research_track.get("candidate_execution_behavior_version")
        != evaluation_track.get("execution_behavior_version")
    ):
        raise ValueError("KNOT promoted behavior does not match the execution track")
    opportunity = _load_record_json(
        conn,
        table="evaluation_opportunity_sets_v2",
        id_column="evaluation_opportunity_set_id",
        record_id=_required_text(
            pair.get("evaluation_opportunity_set_id"),
            "evaluation_opportunity_set_id",
        ),
    )
    for field, expected in (
        ("evaluation_opportunity_set_id", pair.get("evaluation_opportunity_set_id")),
        ("evaluation_opportunity_set_hash", pair.get("evaluation_opportunity_set_hash")),
        ("scheduled_sample_id", pair.get("scheduled_sample_id")),
        ("sample_origin", sample_origin),
        ("opportunity_set_status", "AVAILABLE"),
        *tuple(execution_context.items()),
    ):
        if opportunity.get(field) != expected:
            raise ValueError(f"KNOT opportunity set {field} mismatch")
    opportunity_hash = _required_sha256(
        opportunity.get("evaluation_opportunity_set_hash"),
        "evaluation_opportunity_set_hash",
    )
    if opportunity_hash != canonical_hash(
        {
            key: value
            for key, value in opportunity.items()
            if key != "evaluation_opportunity_set_hash"
        }
    ):
        raise ValueError("KNOT evaluation opportunity set hash mismatch")
    if opportunity.get("member_state") == "EMPTY":
        raise ValueError("KNOT accepted output cannot use an empty opportunity set")
    return pair, research_track, evaluation_track, capability, execution_context


def _knot_lineage(
    *,
    pair: Mapping[str, Any],
    research_track: Mapping[str, Any],
    capability: Mapping[str, Any],
    research_pair_side: str,
    evaluation_object_hash: str | None,
) -> dict[str, Any]:
    return {
        "knot_pair_id": pair["knot_pair_id"],
        "knot_pair_input_hash": pair["knot_pair_input_hash"],
        "research_pair_side": research_pair_side,
        "capability_id": capability["capability_id"],
        "capability_signature_hash": capability["capability_signature_hash"],
        "snapshot_bundle_id": pair["snapshot_bundle_id"],
        "snapshot_bundle_hash": pair["snapshot_bundle_hash"],
        "runtime_input_hash": pair["runtime_input_hash"],
        "prompt_behavior_version": research_track[
            f"{research_pair_side.lower()}_prompt_behavior_version"
        ],
        "execution_behavior_version": research_track[
            f"{research_pair_side.lower()}_execution_behavior_version"
        ],
        "evaluation_object_hash": evaluation_object_hash,
    }


def _validated_knot_operational_audit(
    conn: sqlite3.Connection,
    *,
    operational_opportunity_audit_id: str,
    knot_lineage: Mapping[str, Any],
    expected_fields: Mapping[str, Any],
) -> dict[str, Any]:
    operational = _load_record_json(
        conn,
        table="operational_opportunity_audits_v2",
        id_column="operational_opportunity_audit_id",
        record_id=_required_text(
            operational_opportunity_audit_id,
            "operational_opportunity_audit_id",
        ),
    )
    operational_hash = _required_sha256(
        operational.get("operational_opportunity_audit_hash"),
        "operational_opportunity_audit_hash",
    )
    if operational_hash != canonical_hash(
        {
            key: value
            for key, value in operational.items()
            if key != "operational_opportunity_audit_hash"
        }
    ):
        raise ValueError("KNOT operational audit hash mismatch")
    for field, expected in {**knot_lineage, **expected_fields}.items():
        if operational.get(field) != expected:
            raise ValueError(f"KNOT operational audit {field} mismatch")
    stored_lineage = conn.execute(
        "SELECT "
        + ", ".join(KNOT_LINEAGE_FIELDS)
        + " FROM operational_opportunity_audits_v2 "
        "WHERE operational_opportunity_audit_id = ?",
        (operational_opportunity_audit_id,),
    ).fetchone()
    if stored_lineage is None or any(
        stored_lineage[index] != operational.get(field)
        for index, field in enumerate(KNOT_LINEAGE_FIELDS)
    ):
        raise ValueError("KNOT operational columns/record lineage mismatch")
    return operational


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
    knot_pair_id: str | None = None,
    operational_opportunity_audit_id: str | None = None,
) -> dict[str, Any]:
    """Append one immutable audit revision; terminal revisions cannot be replaced."""
    if disposition not in {"PENDING", *TERMINAL_ELIGIBILITY_DISPOSITIONS}:
        raise ValueError(f"unsupported eligibility disposition: {disposition}")
    track = _track_record(conn, track_key_hash)
    agent_id = str(track["agent_id"])
    knot_origin = sample_origin in KNOT_SAMPLE_ORIGINS
    if knot_origin and research_pair_side not in {"CHAMPION", "CANDIDATE"}:
        raise ValueError("KNOT outcome eligibility requires research_pair_side")
    if knot_origin and knot_pair_id is None:
        raise ValueError("KNOT outcome eligibility requires knot_pair_id")
    if knot_origin and operational_opportunity_audit_id is None:
        raise ValueError("KNOT outcome eligibility requires an operational audit")
    if not knot_origin and (
        research_pair_side is not None
        or knot_pair_id is not None
        or operational_opportunity_audit_id is not None
    ):
        raise ValueError("production outcome eligibility cannot carry KNOT lineage")
    knot_context: tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ] | None = None
    knot_lineage: dict[str, Any] = {}
    if knot_origin:
        knot_context = _load_knot_pair_context(
            conn,
            knot_pair_id=str(knot_pair_id),
            research_pair_side=str(research_pair_side),
        )
        pair, research_track, evaluation_track, capability, _ = knot_context
        for field, expected in (
            ("scheduled_sample_id", scheduled_sample_id),
            ("sample_origin", sample_origin),
        ):
            if pair.get(field) != expected:
                raise ValueError(f"KNOT pair {field} mismatch")
        if evaluation_track.get("track_key_hash") != track_key_hash:
            raise ValueError("KNOT pair evaluation track mismatch")
        if evaluation_opportunity_set_id != pair.get("evaluation_opportunity_set_id"):
            raise ValueError("KNOT eligibility opportunity set mismatch")
        knot_lineage = _knot_lineage(
            pair=pair,
            research_track=research_track,
            capability=capability,
            research_pair_side=str(research_pair_side),
            evaluation_object_hash=None,
        )
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
        accepted_hash = _required_sha256(
            accepted_record.get("accepted_output_hash"), "accepted_output_hash"
        )
        if accepted_hash != canonical_hash(
            {
                key: value
                for key, value in accepted_record.items()
                if key != "accepted_output_hash"
            }
        ):
            raise ValueError("accepted output hash mismatch")
        if knot_context is not None:
            pair, research_track, _, capability, execution_context = knot_context
            for field, expected in (
                (
                    "production_variant_roster_id",
                    execution_context.get("production_variant_roster_id"),
                ),
                (
                    "production_variant_roster_revision_id",
                    execution_context.get("production_variant_roster_revision_id"),
                ),
                (
                    "execution_behavior_release_id",
                    execution_context.get("execution_behavior_release_id"),
                ),
                ("cohort_id", execution_context.get("cohort_id")),
                ("language", execution_context.get("language")),
                ("as_of", pair.get("as_of")),
            ):
                if accepted_record.get(field) != expected:
                    raise ValueError(f"KNOT accepted output {field} mismatch")
            evaluation_object_hash = _required_sha256(
                accepted_record.get("evaluation_object_hash"),
                "evaluation_object_hash",
            )
            knot_lineage = _knot_lineage(
                pair=pair,
                research_track=research_track,
                capability=capability,
                research_pair_side=str(research_pair_side),
                evaluation_object_hash=evaluation_object_hash,
            )
            for field, expected in knot_lineage.items():
                if accepted_record.get(field) != expected:
                    raise ValueError(f"KNOT accepted output {field} mismatch")
            stored_lineage = conn.execute(
                "SELECT "
                + ", ".join(KNOT_LINEAGE_FIELDS)
                + " FROM accepted_agent_outputs_v2 WHERE accepted_output_id = ?",
                (accepted_output_id,),
            ).fetchone()
            if stored_lineage is None or any(
                stored_lineage[index] != accepted_record.get(field)
                for index, field in enumerate(KNOT_LINEAGE_FIELDS)
            ):
                raise ValueError("KNOT accepted output columns/record lineage mismatch")
            if (
                accepted_record.get("operational_opportunity_audit_id")
                != operational_opportunity_audit_id
            ):
                raise ValueError("KNOT accepted output operational audit mismatch")
    if disposition in {"PENDING", "SCORE"} and accepted_record is None:
        raise ValueError(f"{disposition} requires the role-matched accepted output")
    if disposition == "AGENT_FAILURE" and accepted_record is not None:
        raise ValueError("AGENT_FAILURE cannot carry an accepted output")
    if disposition in {"AGENT_FAILURE", "EXOGENOUS_EXCLUSION"} and not (
        isinstance(exclusion_or_failure_reason, str) and exclusion_or_failure_reason
    ):
        raise ValueError(f"{disposition} requires an explicit reason")

    operational_record: dict[str, Any] | None = None
    if knot_origin:
        operational_record = _validated_knot_operational_audit(
            conn,
            operational_opportunity_audit_id=str(
                operational_opportunity_audit_id
            ),
            knot_lineage=knot_lineage,
            expected_fields={
                "accepted_output_id": accepted_output_id,
                "accepted_output_hash": (
                    accepted_record.get("accepted_output_hash")
                    if accepted_record
                    else None
                ),
                "scheduled_sample_id": scheduled_sample_id,
                "track_key_hash": track_key_hash,
                "agent_id": agent_id,
                "sample_origin": sample_origin,
                "run_slot_kind": "OUTCOME_SCHEDULED",
                "production_reliability_eligible": False,
                "disposition": (
                    "ACCEPTED"
                    if disposition in {"PENDING", "SCORE"}
                    else disposition
                ),
                "production_variant_roster_id": knot_context[4][
                    "production_variant_roster_id"
                ],
                "production_variant_roster_revision_id": knot_context[4][
                    "production_variant_roster_revision_id"
                ],
                "execution_behavior_release_id": knot_context[4][
                    "execution_behavior_release_id"
                ],
                "cohort_id": knot_context[4]["cohort_id"],
                "language": knot_context[4]["language"],
                "as_of": knot_context[0]["as_of"],
            },
        )

    audit_identity = {
        "scheduled_sample_id": scheduled_sample_id,
        "track_key_hash": track_key_hash,
        "sample_origin": sample_origin,
        "research_pair_side": research_pair_side,
    }
    if knot_origin:
        audit_identity["knot_pair_id"] = knot_pair_id
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
                and existing.get("accepted_output_hash")
                == (
                    accepted_record.get("accepted_output_hash")
                    if accepted_record
                    else None
                )
                and existing.get("evaluation_opportunity_set_id")
                == evaluation_opportunity_set_id
                and existing.get("exclusion_or_failure_reason")
                == exclusion_or_failure_reason
                and existing.get("operational_opportunity_audit_id")
                == operational_opportunity_audit_id
                and existing.get("operational_opportunity_audit_hash")
                == (
                    operational_record.get("operational_opportunity_audit_hash")
                    if operational_record
                    else None
                )
                and all(
                    existing.get(field) == knot_lineage.get(field)
                    for field in KNOT_LINEAGE_FIELDS
                )
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
                and existing.get("accepted_output_hash")
                == (
                    accepted_record.get("accepted_output_hash")
                    if accepted_record
                    else None
                )
                and existing.get("evaluation_opportunity_set_id")
                == evaluation_opportunity_set_id
                and existing.get("exclusion_or_failure_reason")
                == exclusion_or_failure_reason
                and existing.get("operational_opportunity_audit_id")
                == operational_opportunity_audit_id
                and existing.get("operational_opportunity_audit_hash")
                == (
                    operational_record.get("operational_opportunity_audit_hash")
                    if operational_record
                    else None
                )
                and all(
                    existing.get(field) == knot_lineage.get(field)
                    for field in KNOT_LINEAGE_FIELDS
                )
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
        **knot_lineage,
        "disposition": disposition,
        "accepted_output_id": accepted_output_id,
        "accepted_output_hash": accepted_hash,
        **(
            {
                "operational_opportunity_audit_id": (
                    operational_opportunity_audit_id
                ),
                "operational_opportunity_audit_hash": operational_record[
                    "operational_opportunity_audit_hash"
                ],
            }
            if operational_record
            else {}
        ),
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
            "knot_pair_id",
            "knot_pair_input_hash",
            "capability_id",
            "capability_signature_hash",
            "snapshot_bundle_id",
            "snapshot_bundle_hash",
            "runtime_input_hash",
            "prompt_behavior_version",
            "execution_behavior_version",
            "evaluation_object_hash",
            "accepted_output_hash",
            "operational_opportunity_audit_id",
            "operational_opportunity_audit_hash",
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
            knot_lineage.get("knot_pair_id"),
            knot_lineage.get("knot_pair_input_hash"),
            knot_lineage.get("capability_id"),
            knot_lineage.get("capability_signature_hash"),
            knot_lineage.get("snapshot_bundle_id"),
            knot_lineage.get("snapshot_bundle_hash"),
            knot_lineage.get("runtime_input_hash"),
            knot_lineage.get("prompt_behavior_version"),
            knot_lineage.get("execution_behavior_version"),
            knot_lineage.get("evaluation_object_hash"),
            accepted_hash,
            operational_opportunity_audit_id,
            (
                operational_record.get("operational_opportunity_audit_hash")
                if operational_record
                else None
            ),
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
    legacy_abstention_fields = {
        "security_abstention_metrics",
        "abstention_forecast_loss",
        "abstention_null_loss",
        "abstention_utility_delta",
        "abstention_warranted_label",
        "abstention_null_probability",
        "abstention_base_rate_record_id",
        "abstention_base_rate_record_hash",
        "abstention_missed_opportunity_regret",
        "abstention_raw_opportunity_utility",
        "abstention_opportunity_utility",
        "abstention_opportunity_search_calibration_id",
        "abstention_opportunity_search_calibration_hash",
    }
    stale_fields = sorted(legacy_abstention_fields & set(raw_metrics))
    if stale_fields:
        raise ValueError(
            "Standard Sector outcome contains retired abstention fields: "
            + ", ".join(stale_fields)
        )
    if raw_metrics.get("confidence_semantics") != "DIRECTIONAL_UTILITY":
        raise ValueError("Standard Sector confidence semantics must be directional")

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
    security_forecast = _finite_number(
        raw_metrics.get("security_forecast_loss"), "security_forecast_loss"
    )
    security_null = _finite_number(
        raw_metrics.get("security_null_loss"), "security_null_loss"
    )
    security_delta = security_null - security_forecast
    supplied_security_delta = _finite_number(
        raw_metrics.get("security_utility_delta"), "security_utility_delta"
    )
    if not math.isclose(security_delta, supplied_security_delta, abs_tol=1e-10):
        raise ValueError("security_utility_delta is inconsistent")

    legs = raw_metrics.get("security_leg_metrics")
    if not isinstance(legs, list) or len(legs) != 2:
        raise ValueError("Standard Sector security_leg_metrics must contain two rows")
    by_side: dict[str, Mapping[str, Any]] = {}
    for index, leg in enumerate(legs):
        if not isinstance(leg, Mapping):
            raise ValueError(f"security_leg_metrics[{index}] must be an object")
        side = leg.get("side")
        if side not in {"PREFERRED", "LEAST_PREFERRED"} or side in by_side:
            raise ValueError("Standard Sector security leg sides must be exact and unique")
        status = leg.get("security_status")
        shortlist_size = leg.get("shortlist_size")
        if (
            isinstance(shortlist_size, bool)
            or not isinstance(shortlist_size, int)
            or shortlist_size < 0
        ):
            raise ValueError("Standard Sector shortlist_size must be a nonnegative integer")
        side_delta = _finite_number(
            leg.get("side_security_utility_delta"),
            f"security_leg_metrics[{index}].side_security_utility_delta",
        )
        if status == "NO_QUALIFIED_SECURITY_EMPTY_SHORTLIST":
            if shortlist_size != 0 or not math.isclose(side_delta, 0.0, abs_tol=1e-10):
                raise ValueError("empty Standard Sector security leg must have zero utility")
        elif status == "PICKS_PRESENT":
            if shortlist_size == 0:
                raise ValueError("Standard Sector picks require a non-empty shortlist")
        else:
            raise ValueError("unknown Standard Sector security leg status")
        by_side[str(side)] = leg
    side_delta = sum(
        _finite_number(row.get("side_security_utility_delta"), "side_security_utility_delta")
        for row in by_side.values()
    ) / 2
    if not math.isclose(security_delta, side_delta, abs_tol=1e-10):
        raise ValueError("security_utility_delta does not match the two security legs")

    combined = 0.5 * direction_delta + 0.5 * security_delta
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
        SELECT labels.outcome_sequence, labels.outcome_label_id,
               labels.normalized_score, labels.outcome_due_at,
               labels.matured_at, current.audit_revision_id,
               current.audit_revision_hash, slots.outcome_schedule_slot_id,
               slots.outcome_schedule_slot_hash, slots.record_json
        FROM agent_outcome_labels_v2 labels
        JOIN agent_outcome_eligibility_revisions_v2 current
          ON current.audit_revision_id = labels.audit_revision_id
         AND current.disposition = 'SCORE'
        JOIN outcome_schedule_slots_v2 slots
          ON slots.scheduled_sample_id = labels.scheduled_sample_id
         AND slots.track_key_hash = labels.track_key_hash
         AND slots.run_slot_kind = 'OUTCOME_SCHEDULED'
        WHERE labels.track_key_hash = ?
          AND labels.sample_origin = 'PRODUCTION_ACTIVE'
          AND labels.darwin_evaluation_eligible = 1
          AND labels.outcome_due_at >= ? AND labels.outcome_due_at <= ?
          AND labels.matured_at <= ?
          AND NOT EXISTS (
            SELECT 1 FROM agent_outcome_eligibility_revisions_v2 newer
            WHERE newer.audit_id = current.audit_id
              AND newer.audit_sequence > current.audit_sequence
          )
        ORDER BY labels.outcome_due_at DESC, labels.outcome_sequence DESC
        """,
        (track_key_hash, lookback_start, cutoff_at, cutoff_at),
    ).fetchall()
    orphaned_score_count = conn.execute(
        """
        SELECT COUNT(*) FROM agent_outcome_labels_v2 labels
        LEFT JOIN outcome_schedule_slots_v2 slots
          ON slots.scheduled_sample_id = labels.scheduled_sample_id
         AND slots.track_key_hash = labels.track_key_hash
         AND slots.run_slot_kind = 'OUTCOME_SCHEDULED'
        WHERE labels.track_key_hash = ?
          AND labels.sample_origin = 'PRODUCTION_ACTIVE'
          AND labels.darwin_evaluation_eligible = 1
          AND labels.outcome_due_at >= ? AND labels.outcome_due_at <= ?
          AND labels.matured_at <= ?
          AND slots.outcome_schedule_slot_id IS NULL
        """,
        (track_key_hash, lookback_start, cutoff_at, cutoff_at),
    ).fetchone()[0]
    if orphaned_score_count:
        raise ValueError("Darwinian score is not bound to an immutable schedule slot")

    score_rows: list[dict[str, Any]] = []
    for row in rows:
        slot = json.loads(row[9])
        if not isinstance(slot, dict):
            raise ValueError("Darwinian score schedule binding is invalid")
        expected_slot_hash = canonical_hash(
            {
                key: value
                for key, value in slot.items()
                if key != "outcome_schedule_slot_hash"
            }
        )
        if (
            slot.get("outcome_schedule_slot_id") != row[7]
            or slot.get("outcome_schedule_slot_hash") != row[8]
            or row[8] != expected_slot_hash
            or slot.get("scheduled_sample_id") is None
            or slot.get("outcome_due_at") != row[3]
        ):
            raise ValueError("Darwinian score schedule binding is invalid")
        score_rows.append(
            {
                "outcome_sequence": int(row[0]),
                "outcome_label_id": row[1],
                "normalized_score": float(row[2]),
                "outcome_due_at": row[3],
                "matured_at": row[4],
                "audit_revision_id": row[5],
                "audit_revision_hash": row[6],
                "scheduled_sample_id": slot["scheduled_sample_id"],
                "outcome_schedule_slot_id": row[7],
                "outcome_schedule_slot_hash": row[8],
                "schedule_opportunity_boundary": slot["outcome_due_at"],
            }
        )
    selected = list(reversed(score_rows[:WINDOW_SIZE]))
    coverage_interval_start = (
        min(item["schedule_opportunity_boundary"] for item in selected)
        if selected
        else lookback_start
    )

    failure_rows = conn.execute(
        """
        SELECT current.audit_revision_id, current.audit_revision_hash,
               current.scheduled_sample_id, current.recorded_at,
               slots.outcome_schedule_slot_id,
               slots.outcome_schedule_slot_hash, slots.record_json
        FROM agent_outcome_eligibility_revisions_v2 current
        LEFT JOIN outcome_schedule_slots_v2 slots
          ON slots.scheduled_sample_id = current.scheduled_sample_id
         AND slots.track_key_hash = current.track_key_hash
         AND slots.run_slot_kind = 'OUTCOME_SCHEDULED'
        WHERE current.track_key_hash = ?
          AND current.sample_origin = 'PRODUCTION_ACTIVE'
          AND current.disposition = 'AGENT_FAILURE'
          AND current.recorded_at <= ?
          AND NOT EXISTS (
            SELECT 1 FROM agent_outcome_eligibility_revisions_v2 newer
            WHERE newer.audit_id = current.audit_id
              AND newer.audit_sequence > current.audit_sequence
          )
        """,
        (track_key_hash, cutoff_at),
    ).fetchall()
    failures: list[dict[str, Any]] = []
    for row in failure_rows:
        if row[4] is None:
            raise ValueError("Darwinian failure is not bound to an immutable schedule slot")
        slot = json.loads(row[6])
        if not isinstance(slot, dict):
            raise ValueError("Darwinian failure schedule binding is invalid")
        expected_slot_hash = canonical_hash(
            {
                key: value
                for key, value in slot.items()
                if key != "outcome_schedule_slot_hash"
            }
        )
        if (
            slot.get("outcome_schedule_slot_id") != row[4]
            or slot.get("outcome_schedule_slot_hash") != row[5]
            or row[5] != expected_slot_hash
            or slot.get("scheduled_sample_id") != row[2]
            or not isinstance(slot.get("outcome_due_at"), str)
        ):
            raise ValueError("Darwinian failure schedule binding is invalid")
        boundary = slot["outcome_due_at"]
        if coverage_interval_start <= boundary <= cutoff_at:
            failures.append(
                {
                    "audit_revision_id": row[0],
                    "audit_revision_hash": row[1],
                    "scheduled_sample_id": row[2],
                    "outcome_schedule_slot_id": row[4],
                    "outcome_schedule_slot_hash": row[5],
                    "schedule_opportunity_boundary": boundary,
                    "disposition": "AGENT_FAILURE",
                }
            )
    coverage_scores = [
        item
        for item in score_rows
        if coverage_interval_start <= item["schedule_opportunity_boundary"] <= cutoff_at
    ]
    score_count = len(coverage_scores)
    failure_count = len(failures)
    denominator = score_count + failure_count
    coverage = score_count / denominator if denominator else 0.0
    mean_score = (
        sum(item["normalized_score"] for item in selected) / len(selected)
        if selected
        else None
    )
    coverage_opportunities = sorted(
        [
            {
                "audit_revision_id": item["audit_revision_id"],
                "audit_revision_hash": item["audit_revision_hash"],
                "scheduled_sample_id": item["scheduled_sample_id"],
                "outcome_schedule_slot_id": item["outcome_schedule_slot_id"],
                "outcome_schedule_slot_hash": item["outcome_schedule_slot_hash"],
                "schedule_opportunity_boundary": item[
                    "schedule_opportunity_boundary"
                ],
                "disposition": "SCORE",
                "outcome_label_id": item["outcome_label_id"],
                "outcome_sequence": item["outcome_sequence"],
            }
            for item in coverage_scores
        ]
        + failures,
        key=lambda item: (
            item["schedule_opportunity_boundary"],
            item["scheduled_sample_id"],
            item["disposition"],
        ),
    )
    consumed_opportunity_set_hash = canonical_hash(coverage_opportunities)
    scoring_window_hash = canonical_hash(
        {
            "selected_scores": selected,
            "coverage_interval_start": coverage_interval_start,
            "coverage_opportunities": coverage_opportunities,
        }
    )
    return {
        "scores": selected,
        "n_eligible_scores": len(selected),
        "total_score_count": score_count,
        "agent_failure_count": failure_count,
        "window_coverage": coverage,
        "coverage_interval_start": coverage_interval_start,
        "mean_normalized_score": mean_score,
        "scoring_window_hash": scoring_window_hash,
        "consumed_opportunity_set_hash": consumed_opportunity_set_hash,
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
        scope_has_new_score = any(
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
            elif not scope_has_new_score:
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
                [item["window"]["consumed_opportunity_set_hash"] for item in members]
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
                    "consumed_outcome_set_hash": decision["window"][
                        "consumed_opportunity_set_hash"
                    ],
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

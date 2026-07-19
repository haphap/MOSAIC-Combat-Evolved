"""Append-only component-level calibration inputs for composed Macro Agents."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime
from typing import Any, Mapping, Sequence

from mosaic.scorecard.darwinian_v2 import (
    canonical_hash,
    canonical_json,
    deterministic_id,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS


_HORIZON_ORDER = {"DAYS": 0, "WEEKS": 1, "MONTHS": 2}
_CALENDAR_ID = "cn_a_share_trading_calendar_v1"


def _finite(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _probability(value: Any, label: str) -> float:
    parsed = _finite(value, label)
    if not 0 <= parsed <= 1:
        raise ValueError(f"{label} must be in [0,1]")
    return parsed


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _direction_sign(direction: Any) -> int:
    if direction == "SUPPORTIVE":
        return 1
    if direction == "ADVERSE":
        return -1
    if direction == "NEUTRAL":
        return 0
    raise ValueError("component direction is invalid")


def _direction_and_strength(score: float) -> tuple[str, int]:
    if abs(score) < 0.1:
        return "NEUTRAL", 0
    strength = max(1, min(5, math.floor(5 * abs(score) + 0.5)))
    return ("SUPPORTIVE" if score > 0 else "ADVERSE"), strength


def _insert_immutable(
    conn: sqlite3.Connection,
    *,
    record: Mapping[str, Any],
) -> bool:
    record_json = canonical_json(record)
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO component_calibration_signals_v2 (
            component_calibration_signal_id,
            component_calibration_signal_hash,
            accepted_output_id,
            operational_opportunity_audit_id,
            production_variant_roster_id,
            production_variant_roster_revision_id,
            execution_behavior_release_id,
            cohort_id,
            language,
            calibration_sample_role,
            agent_id,
            track_key_hash,
            component,
            scheduled_sample_id,
            as_of,
            outcome_due_at,
            record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["component_calibration_signal_id"],
            record["component_calibration_signal_hash"],
            record["accepted_output_id"],
            record["operational_opportunity_audit_id"],
            record["production_variant_roster_id"],
            record["production_variant_roster_revision_id"],
            record["execution_behavior_release_id"],
            record["cohort_id"],
            record["language"],
            record["calibration_sample_role"],
            record["agent_id"],
            record["track_key_hash"],
            record["component"],
            record["scheduled_sample_id"],
            record["as_of"],
            record["outcome_due_at"],
            record_json,
        ),
    )
    if cursor.rowcount == 1:
        return True
    row = conn.execute(
        "SELECT record_json FROM component_calibration_signals_v2 "
        "WHERE component_calibration_signal_id = ?",
        (record["component_calibration_signal_id"],),
    ).fetchone()
    if row is None or row[0] != record_json:
        raise ValueError("immutable component calibration signal collision")
    return False


def _load_record(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    value: str,
    *,
    json_column: str = "record_json",
) -> dict:
    row = conn.execute(
        f"SELECT {json_column} FROM {table} WHERE {column} = ?",
        (value,),
    ).fetchone()
    if row is None:
        raise ValueError(f"{table} record is unavailable")
    return json.loads(row[0])


def _component_rows(
    runtime_input: Mapping[str, Any],
    expected_weights: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw = runtime_input.get("components")
    if not isinstance(raw, list) or len(raw) != len(expected_weights):
        raise ValueError("component calibration input has the wrong component count")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("component calibration input rows must be objects")
        component = _required_text(item.get("component"), "component")
        if component in seen or component not in expected_weights:
            raise ValueError("component calibration input set mismatch")
        seen.add(component)
        direction = item.get("direction")
        sign = _direction_sign(direction)
        strength = _finite(item.get("strength"), f"{component}.strength")
        if strength not in {0, 1, 2, 3, 4, 5}:
            raise ValueError(f"{component}.strength must be in [0,5]")
        if (sign == 0) != (strength == 0):
            raise ValueError(f"{component} direction/strength invariant failed")
        horizon = item.get("persistence_horizon")
        if horizon not in _HORIZON_ORDER:
            raise ValueError(f"{component}.persistence_horizon is invalid")
        if item.get("evaluation_horizon_trading_days") != 5:
            raise ValueError(f"{component} evaluation horizon must be five")
        channels = item.get("channels")
        claim_refs = item.get("claim_refs")
        if (
            not isinstance(channels, list)
            or not channels
            or any(not isinstance(value, str) or not value for value in channels)
            or not isinstance(claim_refs, list)
            or not claim_refs
            or any(not isinstance(value, str) or not value for value in claim_refs)
        ):
            raise ValueError(f"{component} channels/claim_refs must be non-empty")
        confidence = _probability(item.get("confidence"), f"{component}.confidence")
        quality = _probability(
            item.get("deterministic_data_quality"),
            f"{component}.deterministic_data_quality",
        )
        weight = _probability(expected_weights[component], f"{component}.weight")
        x = sign * strength / 5
        rows.append(
            {
                "component": component,
                "direction": direction,
                "strength": int(strength),
                "persistence_horizon": horizon,
                "evaluation_horizon_trading_days": 5,
                "confidence": confidence,
                "channels": list(channels),
                "claim_refs": list(claim_refs),
                "deterministic_data_quality": quality,
                "component_weight": weight,
                "signal": x,
                "effective_confidence": confidence * quality,
                "b": weight * confidence * quality,
                "model_b": weight * confidence,
            }
        )
    if seen != set(expected_weights):
        raise ValueError("component calibration input set mismatch")
    return rows


def _validate_composition(
    rows: Sequence[Mapping[str, Any]],
    accepted_payload: Mapping[str, Any],
) -> None:
    b_sum = sum(float(row["b"]) for row in rows)
    model_b_sum = sum(float(row["model_b"]) for row in rows)
    if b_sum <= 0 or model_b_sum <= 0:
        raise ValueError("zero effective component weight")
    score = sum(float(row["b"]) * float(row["signal"]) for row in rows) / b_sum
    model_score = (
        sum(float(row["model_b"]) * float(row["signal"]) for row in rows)
        / model_b_sum
    )
    dispersion = (
        sum(float(row["b"]) * abs(float(row["signal"]) - score) for row in rows)
        / b_sum
    )
    model_dispersion = (
        sum(
            float(row["model_b"]) * abs(float(row["signal"]) - model_score)
            for row in rows
        )
        / model_b_sum
    )
    direction, strength = _direction_and_strength(score)
    horizon_totals = {horizon: 0.0 for horizon in _HORIZON_ORDER}
    for row in rows:
        horizon_totals[str(row["persistence_horizon"])] += float(row["b"])
    horizon = sorted(
        horizon_totals,
        key=lambda item: (-horizon_totals[item], _HORIZON_ORDER[item]),
    )[0]
    model_confidence = max(
        0.0,
        min(
            1.0,
            sum(
                float(row["component_weight"]) * float(row["confidence"])
                for row in rows
            )
            * (1 - model_dispersion),
        ),
    )
    data_quality = max(
        0.0,
        min(
            1.0,
            sum(
                float(row["component_weight"])
                * float(row["deterministic_data_quality"])
                for row in rows
            ),
        ),
    )
    confidence = max(
        0.0,
        min(
            1.0,
            sum(
                float(row["component_weight"])
                * float(row["confidence"])
                * float(row["deterministic_data_quality"])
                for row in rows
            )
            * (1 - dispersion),
        ),
    )
    for field, expected in (
        ("direction", direction),
        ("strength", strength),
        ("persistence_horizon", horizon),
        ("evaluation_horizon_trading_days", 5),
    ):
        if accepted_payload.get(field) != expected:
            raise ValueError(f"accepted Macro {field} does not match component composer")
    for field, expected in (
        ("model_confidence", model_confidence),
        ("deterministic_data_quality", data_quality),
        ("confidence", confidence),
    ):
        actual = _finite(accepted_payload.get(field), f"accepted.{field}")
        if not math.isclose(actual, expected, abs_tol=1e-12):
            raise ValueError(f"accepted Macro {field} does not match component composer")
    expected_channels = {
        value for row in rows for value in row["channels"] if isinstance(value, str)
    }
    expected_claim_refs = {
        value for row in rows for value in row["claim_refs"] if isinstance(value, str)
    }
    if set(accepted_payload.get("channels") or ()) != expected_channels:
        raise ValueError("accepted Macro channels do not match component union")
    if set(accepted_payload.get("claim_refs") or ()) != expected_claim_refs:
        raise ValueError("accepted Macro claim_refs do not match component union")


def _component_runtime_input_from_accepted_audit(
    accepted: Mapping[str, Any],
    *,
    payload: Mapping[str, Any],
    active_component_weights: Mapping[str, Any],
) -> dict[str, Any]:
    runtime_audit = accepted.get("runtime_audit")
    if not isinstance(runtime_audit, Mapping) or set(runtime_audit) != {
        "macro_component_composition"
    }:
        raise ValueError("accepted Macro component composition audit is missing")
    composition = runtime_audit.get("macro_component_composition")
    required_fields = {
        "schema_version",
        "agent_id",
        "component_weight_contract_version",
        "component_weights",
        "components",
        "source_snapshot_hash",
        "context_only_projection_hash",
        "composed_payload_hash",
        "component_composition_hash",
    }
    if not isinstance(composition, Mapping) or set(composition) != required_fields:
        raise ValueError("accepted Macro component composition audit schema is invalid")
    if composition.get("schema_version") != "macro_component_composition_audit_v1":
        raise ValueError("accepted Macro component composition audit version is invalid")
    _verify_hash(
        composition,
        "component_composition_hash",
        "accepted Macro component composition audit",
    )
    if composition.get("composed_payload_hash") != canonical_hash(payload):
        raise ValueError("accepted Macro component composition payload hash mismatch")
    source_snapshot_hash = composition.get("source_snapshot_hash")
    if not isinstance(source_snapshot_hash, str) or re.fullmatch(
        r"sha256:[0-9a-f]{64}", source_snapshot_hash
    ) is None:
        raise ValueError("accepted Macro source snapshot hash is invalid")
    context_projection_hash = composition.get("context_only_projection_hash")
    financial_context_role = accepted.get("agent_id") in {
        "us_financial_conditions",
        "euro_area_financial_conditions",
    }
    if financial_context_role:
        if (
            not isinstance(context_projection_hash, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", context_projection_hash)
            is None
        ):
            raise ValueError(
                "accepted Macro financial context projection hash is invalid"
            )
    elif context_projection_hash is not None:
        raise ValueError("accepted Macro unexpected context projection hash")
    if (
        composition.get("agent_id") != accepted.get("agent_id")
        or composition.get("component_weight_contract_version")
        != accepted.get("component_weight_contract_version")
    ):
        raise ValueError("accepted Macro component composition owner/version mismatch")
    frozen_weights = composition.get("component_weights")
    if not isinstance(frozen_weights, Mapping) or canonical_hash(
        dict(frozen_weights)
    ) != canonical_hash(dict(active_component_weights)):
        raise ValueError("accepted Macro component weights do not match active release")
    components = composition.get("components")
    if not isinstance(components, list):
        raise ValueError("accepted Macro component composition rows are invalid")
    runtime_input = {
        "agent_id": composition["agent_id"],
        "component_weight_contract_version": composition[
            "component_weight_contract_version"
        ],
        "components": components,
    }
    rows = _component_rows(runtime_input, active_component_weights)
    if [row["component"] for row in rows] != sorted(
        row["component"] for row in rows
    ):
        raise ValueError("accepted Macro component composition must be canonically ordered")
    _validate_composition(rows, payload)
    return runtime_input


def validate_accepted_macro_component_composition(
    conn: sqlite3.Connection,
    *,
    accepted: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and return the exact runtime input frozen into an acceptance."""
    agent_id = _required_text(accepted.get("agent_id"), "accepted.agent_id")
    contract = OUTCOME_CONTRACTS.get(agent_id)
    composition_contract = (
        contract.get("component_composition_contract") if contract else None
    )
    if not isinstance(composition_contract, Mapping):
        raise ValueError(f"{agent_id} does not own a component calibration contract")
    envelope = accepted.get("output")
    payload = envelope.get("payload") if isinstance(envelope, Mapping) else None
    if not isinstance(payload, Mapping):
        raise ValueError("accepted Macro evidence envelope is invalid")
    active_component_weights = resolve_component_weights(
        conn,
        agent_id=agent_id,
        at=_required_text(accepted.get("accepted_at"), "accepted.accepted_at"),
    )
    component_version = active_component_weights[
        "component_weight_contract_version"
    ]
    if accepted.get("component_weight_contract_version") != component_version:
        raise ValueError("component weight contract version mismatch")
    return _component_runtime_input_from_accepted_audit(
        accepted,
        payload=payload,
        active_component_weights=active_component_weights["component_weights"],
    )


def append_component_calibration_signals(
    conn: sqlite3.Connection,
    *,
    accepted_output_id: str,
    operational_opportunity_audit_id: str,
    runtime_input: Mapping[str, Any],
    outcome_due_at: str,
) -> dict[str, Any]:
    """Append one immutable signal per component after accepted persistence."""
    accepted = _load_record(
        conn,
        "accepted_agent_outputs_v2",
        "accepted_output_id",
        accepted_output_id,
    )
    operational = _load_record(
        conn,
        "operational_opportunity_audits_v2",
        "operational_opportunity_audit_id",
        operational_opportunity_audit_id,
    )
    if (
        accepted.get("sample_origin") != "PRODUCTION_ACTIVE"
        or accepted.get("run_slot_kind") != "OUTCOME_SCHEDULED"
        or accepted.get("accepted_output_kind") != "MACRO_TRANSMISSION"
        or operational.get("disposition") != "ACCEPTED"
        or operational.get("accepted_output_id") != accepted_output_id
        or operational.get("operational_opportunity_audit_id")
        != operational_opportunity_audit_id
    ):
        raise ValueError("component calibration requires one scheduled production acceptance")
    for field in (
        "graph_run_id",
        "run_slot_id",
        "run_id",
        "scheduled_sample_id",
        "production_variant_roster_id",
        "production_variant_roster_revision_id",
        "execution_behavior_release_id",
        "cohort_id",
        "language",
        "agent_id",
        "track_key_hash",
    ):
        if operational.get(field) != accepted.get(field):
            raise ValueError(f"component calibration operational {field} mismatch")
    agent_id = str(accepted["agent_id"])
    contract = OUTCOME_CONTRACTS[agent_id]
    composition = contract.get("component_composition_contract")
    if not isinstance(composition, Mapping):
        raise ValueError(f"{agent_id} does not own a component calibration contract")
    envelope = accepted.get("output")
    if not isinstance(envelope, Mapping):
        raise ValueError("accepted Macro evidence envelope is unavailable")
    payload = envelope.get("payload")
    evidence_bundle_ids = envelope.get("evidence_bundle_ids")
    if (
        not isinstance(payload, Mapping)
        or not isinstance(evidence_bundle_ids, list)
        or not evidence_bundle_ids
        or any(not isinstance(value, str) or not value for value in evidence_bundle_ids)
    ):
        raise ValueError("accepted Macro evidence envelope is invalid")
    accepted_runtime_input = validate_accepted_macro_component_composition(
        conn, accepted=accepted
    )
    if canonical_hash(dict(runtime_input)) != canonical_hash(accepted_runtime_input):
        raise ValueError("component calibration runtime input does not match accepted audit")
    component_version = accepted_runtime_input["component_weight_contract_version"]
    active_component_weights = resolve_component_weights(
        conn,
        agent_id=agent_id,
        at=str(accepted["accepted_at"]),
    )
    rows = _component_rows(
        accepted_runtime_input,
        active_component_weights["component_weights"],
    )
    if not math.isclose(
        sum(float(row["component_weight"]) for row in rows),
        1.0,
        abs_tol=1e-12,
    ):
        raise ValueError("component weights do not sum to one")

    reference_roster_id = deterministic_id(
        "production-variant-roster",
        {"cohort_id": "cohort_default", "language": "zh"},
    )
    current_reference = conn.execute(
        "SELECT production_variant_roster_revision_id "
        "FROM darwinian_v2_production_variant_roster_revisions "
        "WHERE production_variant_roster_id = ? AND readiness = 'READY' "
        "AND effective_at <= ? ORDER BY effective_at DESC, rowid DESC LIMIT 1",
        (reference_roster_id, accepted["accepted_at"]),
    ).fetchone()
    fit_reference = (
        accepted["production_variant_roster_id"] == reference_roster_id
        and accepted["cohort_id"] == "cohort_default"
        and accepted["language"] == "zh"
        and current_reference is not None
        and current_reference[0]
        == accepted["production_variant_roster_revision_id"]
    )
    sample_role = "FIT_REFERENCE" if fit_reference else "CROSS_VARIANT_DIAGNOSTIC"
    track = _load_record(
        conn,
        "darwinian_v2_evaluation_tracks",
        "track_key_hash",
        str(accepted["track_key_hash"]),
        json_column="contract_json",
    )
    outcome_contract = track["outcome_contract"]
    inserted = 0
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item["component"])):
        identity = {
            "accepted_output_hash": accepted["accepted_output_hash"],
            "component": row["component"],
            "component_weight_contract_version": component_version,
        }
        signal_id = deterministic_id("component-calibration-signal", identity)
        without_hash = {
            "component_calibration_signal_id": signal_id,
            "sample_origin": "PRODUCTION_ACTIVE",
            "graph_run_id": accepted["graph_run_id"],
            "run_slot_id": accepted["run_slot_id"],
            "run_id": accepted["run_id"],
            "scheduled_sample_id": accepted["scheduled_sample_id"],
            "accepted_output_id": accepted_output_id,
            "accepted_output_hash": accepted["accepted_output_hash"],
            "operational_opportunity_audit_id": operational_opportunity_audit_id,
            "operational_opportunity_audit_hash": operational[
                "operational_opportunity_audit_hash"
            ],
            "production_variant_roster_id": accepted[
                "production_variant_roster_id"
            ],
            "production_variant_roster_revision_id": accepted[
                "production_variant_roster_revision_id"
            ],
            "execution_behavior_release_id": accepted[
                "execution_behavior_release_id"
            ],
            "cohort_id": accepted["cohort_id"],
            "language": accepted["language"],
            "calibration_sample_role": sample_role,
            "agent_id": agent_id,
            "track_key_hash": accepted["track_key_hash"],
            "agent_contract_version": accepted["agent_contract_version"],
            "prompt_behavior_version": accepted["prompt_behavior_version"],
            "execution_behavior_version": accepted["execution_behavior_version"],
            "component_weight_contract_version": component_version,
            "outcome_contract_version": outcome_contract["outcome_contract_version"],
            "scoring_contract_version": outcome_contract["scoring_contract_version"],
            "primary_label_id": outcome_contract["primary_label_id"],
            "sample_schedule_contract_version": outcome_contract[
                "sample_schedule_contract_version"
            ],
            "rank_scope_contract_version": outcome_contract[
                "rank_scope_contract_version"
            ],
            "rank_scope": outcome_contract["rank_scope"],
            "as_of": accepted["as_of"],
            "component": row["component"],
            "component_weight": row["component_weight"],
            "signal": row["signal"],
            "model_confidence": row["confidence"],
            "deterministic_data_quality": row["deterministic_data_quality"],
            "effective_confidence": row["effective_confidence"],
            "live_persistence_horizon": row["persistence_horizon"],
            "evaluation_horizon_trading_days": 5,
            "evidence_bundle_ids": sorted(set(evidence_bundle_ids)),
            "outcome_due_at": _required_text(outcome_due_at, "outcome_due_at"),
        }
        record = {
            **without_hash,
            "component_calibration_signal_hash": canonical_hash(without_hash),
        }
        inserted += int(_insert_immutable(conn, record=record))
        records.append(record)
    return {"inserted": inserted, "signals": records}


def _timestamp(value: Any, label: str) -> datetime:
    text = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _verify_hash(record: Mapping[str, Any], hash_field: str, label: str) -> None:
    supplied = record.get(hash_field)
    without_hash = {key: value for key, value in record.items() if key != hash_field}
    if supplied != canonical_hash(without_hash):
        raise ValueError(f"{label} hash mismatch")


def _calibration_contract(agent_id: str) -> tuple[dict[str, float], Mapping[str, Any]]:
    contract = OUTCOME_CONTRACTS.get(agent_id)
    composition = contract.get("component_composition_contract") if contract else None
    if not isinstance(composition, Mapping):
        raise ValueError(f"{agent_id} has no component calibration contract")
    weights = composition.get("components")
    calibration = composition.get("calibration_contract")
    if not isinstance(weights, Mapping) or not isinstance(calibration, Mapping):
        raise ValueError("component calibration contract is incomplete")
    return ({str(key): float(value) for key, value in weights.items()}, calibration)


def build_component_regime_snapshot(
    *,
    observations: Sequence[Mapping[str, Any]],
    generated_at: str,
    source_evidence_ids: Sequence[str],
) -> dict[str, Any]:
    """Build a redacted PIT snapshot from pinned-private opaque classifications."""
    generated = _timestamp(generated_at, "generated_at")
    if not source_evidence_ids or any(
        not isinstance(item, str) or not item for item in source_evidence_ids
    ):
        raise ValueError("component regime snapshot requires source evidence")
    private_observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in observations:
        as_of = _required_text(item.get("as_of"), "regime.as_of")
        if as_of in seen:
            raise ValueError("component regime snapshot contains duplicate dates")
        seen.add(as_of)
        available_at = _timestamp(item.get("available_at"), "regime.available_at")
        if available_at > generated:
            raise ValueError("component regime observation was unavailable at generation")
        if available_at > _timestamp(f"{as_of}T15:00:00+08:00", "regime.as_of_close"):
            raise ValueError("component regime observation is not PIT at as_of")
        evidence_ids = item.get("source_evidence_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids or any(
            not isinstance(value, str) or not value for value in evidence_ids
        ):
            raise ValueError("component regime observation requires source evidence")
        if "regime" in item:
            raise ValueError("component regime must be derived, not supplied")
        private_observations.append(
            {
                **dict(item),
                "as_of": as_of,
                "available_at": available_at.isoformat(),
                "pit_status": "VERIFIED",
                "source_evidence_ids": sorted(set(evidence_ids)),
            }
        )
    private_observations.sort(key=lambda row: row["as_of"])
    private_body = {
        "schema_version": "component_calibration_regime_snapshot_v1",
        "generated_at": generated.isoformat(),
        "pit_status": "VERIFIED",
        "source_evidence_ids": sorted(set(source_evidence_ids)),
        "observations": private_observations,
    }
    private_snapshot = {
        **private_body,
        "snapshot_hash": canonical_hash(private_body),
    }
    classified: list[dict[str, Any]] = []
    classifier_contract: dict[str, str] | None = None
    for item in private_observations:
        result = _classify_private_regime(private_snapshot, as_of=item["as_of"])
        contract = {
            "classifier_contract_id": _required_text(
                result.get("classifier_contract_id"), "classifier_contract_id"
            ),
            "classifier_contract_version": _required_text(
                result.get("classifier_contract_version"),
                "classifier_contract_version",
            ),
            "classifier_contract_hash": _required_text(
                result.get("classifier_contract_hash"), "classifier_contract_hash"
            ),
        }
        if not contract["classifier_contract_hash"].startswith("sha256:"):
            raise ValueError("private classifier contract hash is invalid")
        if classifier_contract is None:
            classifier_contract = contract
        elif classifier_contract != contract:
            raise ValueError("private classifier contract changed within one snapshot")
        if result.get("pit_snapshot_hash") != private_snapshot["snapshot_hash"]:
            raise ValueError("private classifier source snapshot binding mismatch")
        label = result.get("regime_label")
        if label not in {"normal", "stress"}:
            raise ValueError("private classifier returned an invalid regime label")
        classified.append(
            {
                "as_of": item["as_of"],
                "available_at": item["available_at"],
                "regime": str(label).upper(),
                "pit_status": "VERIFIED",
                "source_evidence_ids": item["source_evidence_ids"],
                "classifier_source_snapshot_hash": private_snapshot["snapshot_hash"],
            }
        )
    if classifier_contract is None:
        raise ValueError("component regime snapshot requires at least one observation")
    without_hash = {
        "schema_version": "component_calibration_regime_snapshot_v2",
        "generated_at": generated.isoformat(),
        "pit_status": "VERIFIED",
        "source_evidence_ids": sorted(set(source_evidence_ids)),
        "classifier_contract": classifier_contract,
        "classifier_source_snapshot_hash": private_snapshot["snapshot_hash"],
        "observations": classified,
    }
    return {**without_hash, "snapshot_hash": canonical_hash(without_hash)}


def _classify_private_regime(
    snapshot: Mapping[str, Any], *, as_of: str
) -> Mapping[str, Any]:
    from mosaic.scorecard import knot_v2 as private_knot

    result = private_knot.classify_knot_regime(snapshot, as_of=as_of)
    if not isinstance(result, Mapping) or set(result) != {
        "regime_label",
        "classifier_contract_id",
        "classifier_contract_version",
        "classifier_contract_hash",
        "pit_snapshot_hash",
    }:
        raise ValueError("private classifier output contract mismatch")
    return result


def _verified_calendar(
    snapshot: Mapping[str, Any],
    *,
    cutoff_at: str,
) -> tuple[list[str], dict[str, int], int]:
    if (
        snapshot.get("schema_version") != "verified_trading_calendar_snapshot_v1"
        or snapshot.get("trading_calendar_id") != _CALENDAR_ID
        or snapshot.get("pit_status") != "VERIFIED"
    ):
        raise ValueError("component calibration requires a verified A-share calendar")
    _verify_hash(snapshot, "snapshot_hash", "trading calendar snapshot")
    dates = snapshot.get("trading_dates")
    evidence = snapshot.get("source_evidence_ids")
    if (
        not isinstance(dates, list)
        or not dates
        or dates != sorted(set(dates))
        or not isinstance(evidence, list)
        or not evidence
    ):
        raise ValueError("component calibration calendar is incomplete")
    cutoff_date = _timestamp(cutoff_at, "cutoff_at").date().isoformat()
    if cutoff_date not in dates:
        raise ValueError("component calibration cutoff must be a trading day")
    positions = {value: index for index, value in enumerate(dates)}
    return dates, positions, positions[cutoff_date]


def _semiannual_slot(
    dates: Sequence[str],
    positions: Mapping[str, int],
    cutoff_at: str,
) -> str:
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    year = cutoff.year
    half = 1 if cutoff.month <= 6 else 2
    boundary = f"{year}-{'06-30' if half == 1 else '12-31'}"
    eligible = [value for value in dates if value[:4] == str(year) and value <= boundary]
    if not eligible or cutoff.date().isoformat() != eligible[-1] or eligible[-1] not in positions:
        raise ValueError("component calibration is limited to fixed semiannual closes")
    return f"{year}-H{half}"


def _regime_map(snapshot: Mapping[str, Any], cutoff_at: str) -> dict[str, dict[str, Any]]:
    if (
        snapshot.get("schema_version")
        != "component_calibration_regime_snapshot_v2"
        or snapshot.get("pit_status") != "VERIFIED"
    ):
        raise ValueError("component calibration regime snapshot is invalid")
    _verify_hash(snapshot, "snapshot_hash", "component regime snapshot")
    if _timestamp(snapshot.get("generated_at"), "regime.generated_at") > _timestamp(
        cutoff_at, "cutoff_at"
    ):
        raise ValueError("component regime snapshot is from the future")
    observations = snapshot.get("observations")
    if not isinstance(observations, list):
        raise ValueError("component regime observations are invalid")
    classifier_contract = snapshot.get("classifier_contract")
    if (
        not isinstance(classifier_contract, Mapping)
        or set(classifier_contract)
        != {
            "classifier_contract_id",
            "classifier_contract_version",
            "classifier_contract_hash",
        }
        or any(
            not isinstance(classifier_contract.get(field), str)
            or not classifier_contract[field]
            for field in classifier_contract
        )
        or not str(classifier_contract["classifier_contract_hash"]).startswith(
            "sha256:"
        )
    ):
        raise ValueError("component regime classifier contract is invalid")
    source_snapshot_hash = snapshot.get("classifier_source_snapshot_hash")
    if (
        not isinstance(source_snapshot_hash, str)
        or not source_snapshot_hash.startswith("sha256:")
    ):
        raise ValueError("component regime classifier source hash is invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in observations:
        if not isinstance(item, Mapping):
            raise ValueError("component regime observation must be an object")
        as_of = _required_text(item.get("as_of"), "regime.as_of")
        if as_of in result or item.get("pit_status") != "VERIFIED":
            raise ValueError("component regime observation identity is invalid")
        if item.get("regime") not in {"NORMAL", "STRESS"}:
            raise ValueError("component regime label is invalid")
        if item.get("classifier_source_snapshot_hash") != source_snapshot_hash:
            raise ValueError("component regime source binding mismatch")
        available_at = _timestamp(item.get("available_at"), "regime.available_at")
        if available_at > _timestamp(f"{as_of}T15:00:00+08:00", "regime.as_of_close"):
            raise ValueError("component regime observation is not PIT")
        evidence = item.get("source_evidence_ids")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("component regime observation lacks evidence")
        result[as_of] = dict(item)
    return result


def _target_for_signal_group(
    conn: sqlite3.Connection,
    *,
    signals: Sequence[Mapping[str, Any]],
    cutoff_at: str,
) -> dict[str, Any]:
    first = signals[0]
    accepted = _load_record(
        conn,
        "accepted_agent_outputs_v2",
        "accepted_output_id",
        str(first["accepted_output_id"]),
    )
    operational = _load_record(
        conn,
        "operational_opportunity_audits_v2",
        "operational_opportunity_audit_id",
        str(first["operational_opportunity_audit_id"]),
    )
    _verify_hash(accepted, "accepted_output_hash", "accepted component output")
    _verify_hash(
        operational,
        "operational_opportunity_audit_hash",
        "component operational audit",
    )
    if (
        accepted.get("accepted_output_hash") != first.get("accepted_output_hash")
        or operational.get("operational_opportunity_audit_hash")
        != first.get("operational_opportunity_audit_hash")
        or operational.get("accepted_output_id") != accepted.get("accepted_output_id")
        or operational.get("disposition") != "ACCEPTED"
        or operational.get("fallback_used") is not False
    ):
        raise ValueError("component calibration acceptance/audit join mismatch")
    identity_fields = (
        "graph_run_id",
        "run_slot_id",
        "run_id",
        "scheduled_sample_id",
        "production_variant_roster_id",
        "production_variant_roster_revision_id",
        "execution_behavior_release_id",
        "cohort_id",
        "language",
        "agent_id",
        "track_key_hash",
    )
    for field in identity_fields:
        if accepted.get(field) != first.get(field) or operational.get(field) != first.get(field):
            raise ValueError(f"component calibration {field} join mismatch")
    label_rows = conn.execute(
        """
        SELECT label.record_json, audit.record_json
        FROM agent_outcome_labels_v2 AS label
        JOIN agent_outcome_eligibility_revisions_v2 AS audit
          ON audit.audit_revision_id = label.audit_revision_id
        WHERE audit.accepted_output_id = ?
          AND label.track_key_hash = ?
          AND label.agent_id = ?
        """,
        (
            first["accepted_output_id"],
            first["track_key_hash"],
            first["agent_id"],
        ),
    ).fetchall()
    if len(label_rows) != 1:
        raise ValueError("component calibration requires exactly one primary outcome label")
    label = json.loads(label_rows[0][0])
    audit = json.loads(label_rows[0][1])
    _verify_hash(label, "outcome_label_hash", "component outcome label")
    _verify_hash(audit, "audit_revision_hash", "component outcome eligibility")
    if (
        audit.get("disposition") != "SCORE"
        or audit.get("accepted_output_id") != first.get("accepted_output_id")
        or label.get("sample_origin") != "PRODUCTION_ACTIVE"
        or label.get("darwin_evaluation_eligible") is not True
        or label.get("scheduled_sample_id") != first.get("scheduled_sample_id")
        or label.get("primary_label_id") != first.get("primary_label_id")
        or label.get("outcome_due_at") != first.get("outcome_due_at")
    ):
        raise ValueError("component calibration outcome label join mismatch")
    opportunity_id = audit.get("evaluation_opportunity_set_id")
    opportunity = _load_record(
        conn,
        "evaluation_opportunity_sets_v2",
        "evaluation_opportunity_set_id",
        _required_text(opportunity_id, "evaluation_opportunity_set_id"),
    )
    _verify_hash(
        opportunity,
        "evaluation_opportunity_set_hash",
        "component evaluation opportunity set",
    )
    if (
        opportunity.get("evaluation_opportunity_set_hash")
        != audit.get("evaluation_opportunity_set_hash")
        or opportunity.get("opportunity_set_status") != "AVAILABLE"
        or opportunity.get("sample_origin") != "PRODUCTION_ACTIVE"
        or opportunity.get("scheduled_sample_id") != first.get("scheduled_sample_id")
        or opportunity.get("track_key_hash") != first.get("track_key_hash")
        or opportunity.get("agent_id") != first.get("agent_id")
        or opportunity.get("production_variant_roster_id")
        != first.get("production_variant_roster_id")
        or opportunity.get("production_variant_roster_revision_id")
        != first.get("production_variant_roster_revision_id")
    ):
        raise ValueError("component calibration opportunity-set join mismatch")
    versions = label.get("contract_versions")
    expected_versions = {
        "outcome_contract_version": first["outcome_contract_version"],
        "scoring_contract_version": first["scoring_contract_version"],
        "sample_schedule_contract_version": first[
            "sample_schedule_contract_version"
        ],
        "rank_scope_contract_version": first["rank_scope_contract_version"],
    }
    if not isinstance(versions, Mapping) or any(
        versions.get(key) != value for key, value in expected_versions.items()
    ):
        raise ValueError("component calibration outcome contract version mismatch")
    matured_at = _timestamp(label.get("matured_at"), "label.matured_at")
    due_at = _timestamp(label.get("outcome_due_at"), "label.outcome_due_at")
    if matured_at < due_at or matured_at > _timestamp(cutoff_at, "cutoff_at"):
        raise ValueError("component calibration outcome is not mature at cutoff")
    raw_metrics = label.get("raw_metrics")
    if not isinstance(raw_metrics, Mapping):
        raise ValueError("component calibration label raw_metrics are unavailable")
    role_path = _finite(raw_metrics.get("role_path_metric"), "role_path_metric")
    scale = _finite(raw_metrics.get("pit_volatility_scale"), "pit_volatility_scale")
    if scale <= 0:
        raise ValueError("component calibration PIT scale must be positive")
    target = max(-1.0, min(1.0, role_path / scale))
    cached = _finite(raw_metrics.get("realized_scaled_path"), "realized_scaled_path")
    if not math.isclose(target, cached, abs_tol=1e-12):
        raise ValueError("component calibration target audit cache mismatch")
    return {
        "target": target,
        "outcome_label_id": label["outcome_label_id"],
        "outcome_label_hash": label["outcome_label_hash"],
        "matured_at": label["matured_at"],
    }


def _compose_forecast(
    components: Mapping[str, Mapping[str, Any]],
    weights: Mapping[str, float],
) -> dict[str, Any]:
    if set(components) != set(weights):
        raise ValueError("component forecast set mismatch")
    weighted: list[tuple[float, float]] = []
    for component in sorted(weights):
        row = components[component]
        signal = _finite(row.get("signal"), f"{component}.signal")
        model_confidence = _probability(
            row.get("model_confidence"), f"{component}.model_confidence"
        )
        quality = _probability(
            row.get("deterministic_data_quality"),
            f"{component}.deterministic_data_quality",
        )
        weighted.append((float(weights[component]) * model_confidence * quality, signal))
    denominator = sum(weight for weight, _ in weighted)
    if denominator <= 0:
        raise ValueError("component forecast has zero effective confidence")
    score = sum(weight * signal for weight, signal in weighted) / denominator
    dispersion = (
        sum(weight * abs(signal - score) for weight, signal in weighted) / denominator
    )
    base_confidence = sum(
        float(weights[component])
        * float(components[component]["model_confidence"])
        * float(components[component]["deterministic_data_quality"])
        for component in weights
    )
    confidence = max(0.0, min(1.0, base_confidence * (1 - dispersion)))
    direction, strength = _direction_and_strength(score)
    sign = _direction_sign(direction)
    return {
        "continuous_score": score,
        "direction": direction,
        "strength": strength,
        "confidence": confidence,
        "point_forecast": confidence * sign * strength / 5,
    }


def _sample_groups(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    sample_role: str,
    cutoff_at: str,
    dates: Sequence[str],
    positions: Mapping[str, int],
    cutoff_index: int,
    regime_by_date: Mapping[str, Mapping[str, Any]],
    weights: Mapping[str, float],
    reference_track_key_hash: str,
    reference_versions: Mapping[str, Any],
    lookback_trading_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows = conn.execute(
        "SELECT record_json FROM component_calibration_signals_v2 "
        "WHERE agent_id = ? AND calibration_sample_role = ? AND as_of <= ? "
        "ORDER BY as_of, accepted_output_id, component",
        (agent_id, sample_role, _timestamp(cutoff_at, "cutoff_at").date().isoformat()),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        signal = json.loads(row[0])
        _verify_hash(signal, "component_calibration_signal_hash", "component signal")
        if sample_role == "FIT_REFERENCE":
            if (
                signal.get("cohort_id") != "cohort_default"
                or signal.get("language") != "zh"
                or any(
                    signal.get(field) != reference_versions.get(field)
                    for field in (
                        "agent_contract_version",
                        "prompt_behavior_version",
                        "execution_behavior_version",
                        "outcome_contract_version",
                        "scoring_contract_version",
                        "sample_schedule_contract_version",
                        "rank_scope_contract_version",
                    )
                )
            ):
                continue
        grouped.setdefault(str(signal["accepted_output_id"]), []).append(signal)

    samples: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    minimum_index = max(0, cutoff_index - lookback_trading_days + 1)
    for accepted_output_id, signals in grouped.items():
        try:
            first = signals[0]
            if len(signals) != len(weights) or {
                str(signal.get("component")) for signal in signals
            } != set(weights):
                raise ValueError("incomplete required component set")
            common_fields = (
                "accepted_output_id",
                "accepted_output_hash",
                "operational_opportunity_audit_id",
                "operational_opportunity_audit_hash",
                "graph_run_id",
                "run_slot_id",
                "run_id",
                "scheduled_sample_id",
                "production_variant_roster_id",
                "production_variant_roster_revision_id",
                "execution_behavior_release_id",
                "cohort_id",
                "language",
                "agent_id",
                "track_key_hash",
                "as_of",
                "outcome_due_at",
            )
            if any(
                signal.get(field) != first.get(field)
                for signal in signals[1:]
                for field in common_fields
            ):
                raise ValueError("component signal identity mismatch")
            as_of = str(first["as_of"])
            if as_of not in positions:
                raise ValueError("as_of is outside the verified trading calendar")
            as_of_index = positions[as_of]
            if not minimum_index <= as_of_index <= cutoff_index:
                continue
            due_index = as_of_index + 5
            if due_index >= len(dates):
                raise ValueError("calendar does not cover component outcome maturity")
            expected_due = f"{dates[due_index]}T15:00:00+08:00"
            if first.get("outcome_due_at") != expected_due:
                raise ValueError("component outcome maturity does not match calendar")
            regime = regime_by_date.get(as_of)
            if regime is None:
                raise ValueError("PIT market regime is unavailable")
            accepted_for_weights = _load_record(
                conn,
                "accepted_agent_outputs_v2",
                "accepted_output_id",
                accepted_output_id,
            )
            historical_weights = resolve_component_weights(
                conn,
                agent_id=agent_id,
                at=_required_text(
                    accepted_for_weights.get("accepted_at"),
                    "accepted.accepted_at",
                ),
            )
            if first.get("component_weight_contract_version") != historical_weights[
                "component_weight_contract_version"
            ]:
                raise ValueError("component signal weight version drift")
            historical_weight_values = historical_weights["component_weights"]
            if set(historical_weight_values) != set(weights):
                raise ValueError("component signal set drift")
            components: dict[str, dict[str, Any]] = {}
            for signal in signals:
                component = str(signal["component"])
                if not math.isclose(
                    _finite(signal.get("component_weight"), "component_weight"),
                    float(historical_weight_values[component]),
                    abs_tol=1e-12,
                ):
                    raise ValueError("component signal weight drift")
                confidence = _probability(
                    signal.get("model_confidence"), "model_confidence"
                )
                quality = _probability(
                    signal.get("deterministic_data_quality"),
                    "deterministic_data_quality",
                )
                if quality <= 0:
                    raise ValueError("component is below its required coverage threshold")
                effective = _probability(
                    signal.get("effective_confidence"), "effective_confidence"
                )
                if not math.isclose(effective, confidence * quality, abs_tol=1e-12):
                    raise ValueError("component effective confidence mismatch")
                components[component] = {
                    "signal": _finite(signal.get("signal"), "signal"),
                    "model_confidence": confidence,
                    "deterministic_data_quality": quality,
                    "component_calibration_signal_id": signal[
                        "component_calibration_signal_id"
                    ],
                    "component_calibration_signal_hash": signal[
                        "component_calibration_signal_hash"
                    ],
                }
            _compose_forecast(components, weights)
            target = _target_for_signal_group(
                conn,
                signals=signals,
                cutoff_at=cutoff_at,
            )
            samples.append(
                {
                    "accepted_output_id": accepted_output_id,
                    "accepted_output_hash": first["accepted_output_hash"],
                    "scheduled_sample_id": first["scheduled_sample_id"],
                    "production_variant_roster_id": first[
                        "production_variant_roster_id"
                    ],
                    "track_key_hash": first["track_key_hash"],
                    "as_of": as_of,
                    "as_of_index": as_of_index,
                    "outcome_due_at": expected_due,
                    "outcome_due_index": due_index,
                    "regime": regime["regime"],
                    "regime_evidence_ids": regime["source_evidence_ids"],
                    "components": components,
                    **target,
                }
            )
        except ValueError as exc:
            exclusions.append(
                {
                    "accepted_output_id": accepted_output_id,
                    "reason": str(exc),
                }
            )
    samples.sort(key=lambda sample: (sample["as_of_index"], sample["accepted_output_id"]))
    deduplicated: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    last_due_by_variant: dict[str, int] = {}
    for sample in samples:
        variant = str(sample["production_variant_roster_id"])
        key = (variant, str(sample["as_of"]))
        if key in seen_keys:
            exclusions.append(
                {
                    "accepted_output_id": str(sample["accepted_output_id"]),
                    "reason": "duplicate agent/as_of calibration opportunity",
                }
            )
            continue
        seen_keys.add(key)
        previous_due = last_due_by_variant.get(variant)
        if previous_due is not None and sample["as_of_index"] < previous_due:
            exclusions.append(
                {
                    "accepted_output_id": str(sample["accepted_output_id"]),
                    "reason": "overlapping five-session outcome window",
                }
            )
            continue
        last_due_by_variant[variant] = int(sample["outcome_due_index"])
        deduplicated.append(sample)
    return deduplicated, exclusions


def _candidate_weight_grid(
    previous: Mapping[str, float],
    calibration: Mapping[str, Any],
) -> list[dict[str, float]]:
    step = float(calibration["solver_grid_step"])
    total_units = round(1 / step)
    lower_bound = float(calibration["component_weight_lower_bound"])
    upper_bound = float(calibration["component_weight_upper_bound"])
    maximum_delta = float(calibration["maximum_component_delta"])
    components = sorted(previous)
    ranges: list[range] = []
    for component in components:
        value = float(previous[component])
        lower = max(lower_bound, value - maximum_delta)
        upper = min(upper_bound, value + maximum_delta)
        lower_units = math.ceil((lower - 1e-12) / step)
        upper_units = math.floor((upper + 1e-12) / step)
        ranges.append(range(lower_units, upper_units + 1))
    candidates: list[dict[str, float]] = []

    def visit(index: int, chosen: list[int], remaining: int) -> None:
        if index == len(components) - 1:
            if remaining in ranges[index]:
                units = [*chosen, remaining]
                candidates.append(
                    {
                        component: round(unit * step, 12)
                        for component, unit in zip(components, units, strict=True)
                    }
                )
            return
        minimum_tail = sum(item.start for item in ranges[index + 1 :])
        maximum_tail = sum(item.stop - 1 for item in ranges[index + 1 :])
        for unit in ranges[index]:
            next_remaining = remaining - unit
            if minimum_tail <= next_remaining <= maximum_tail:
                visit(index + 1, [*chosen, unit], next_remaining)

    visit(0, [], total_units)
    if not candidates:
        raise ValueError("component calibration constraint set is empty")
    return candidates


def _mean_loss(samples: Sequence[Mapping[str, Any]], weights: Mapping[str, float]) -> float:
    if not samples:
        raise ValueError("component calibration loss requires samples")
    return sum(
        (
            _compose_forecast(sample["components"], weights)["point_forecast"]
            - float(sample["target"])
        )
        ** 2
        for sample in samples
    ) / len(samples)


def _fit_weights(
    samples: Sequence[Mapping[str, Any]],
    previous: Mapping[str, float],
    calibration: Mapping[str, Any],
) -> dict[str, float]:
    regularization = float(calibration["regularization_lambda"])
    components = sorted(previous)
    best: dict[str, float] | None = None
    best_objective = math.inf
    for candidate in _candidate_weight_grid(previous, calibration):
        objective = _mean_loss(samples, candidate) + regularization * sum(
            (float(candidate[component]) - float(previous[component])) ** 2
            for component in components
        )
        candidate_key = tuple(candidate[component] for component in components)
        best_key = tuple(best[component] for component in components) if best else ()
        if objective < best_objective - 1e-15 or (
            math.isclose(objective, best_objective, abs_tol=1e-15)
            and (best is None or candidate_key < best_key)
        ):
            best = candidate
            best_objective = objective
    if best is None:
        raise ValueError("component calibration solver produced no candidate")
    return best


def _direction_hit(forecast: Mapping[str, Any], target: float) -> bool:
    target_direction = (
        "SUPPORTIVE" if target >= 0.1 else "ADVERSE" if target <= -0.1 else "NEUTRAL"
    )
    return forecast["direction"] == target_direction


def _ratio_improvement(current: float, candidate: float) -> float:
    if current <= 1e-15:
        return 0.0 if candidate <= 1e-15 else -math.inf
    return (current - candidate) / current


def _metrics_from_predictions(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    current_mse = sum(float(row["current_loss"]) for row in rows) / len(rows)
    candidate_mse = sum(float(row["candidate_loss"]) for row in rows) / len(rows)
    metrics: dict[str, Any] = {
        "sample_count": len(rows),
        "current_mse": current_mse,
        "candidate_mse": candidate_mse,
        "mse_improvement_ratio": _ratio_improvement(current_mse, candidate_mse),
        "current_direction_hit_rate": sum(bool(row["current_direction_hit"]) for row in rows)
        / len(rows),
        "candidate_direction_hit_rate": sum(
            bool(row["candidate_direction_hit"]) for row in rows
        )
        / len(rows),
        "regimes": {},
    }
    for regime in ("NORMAL", "STRESS"):
        subset = [row for row in rows if row["regime"] == regime]
        if subset:
            current = sum(float(row["current_loss"]) for row in subset) / len(subset)
            candidate = sum(float(row["candidate_loss"]) for row in subset) / len(subset)
            metrics["regimes"][regime] = {
                "sample_count": len(subset),
                "current_mse": current,
                "candidate_mse": candidate,
                "mse_degradation_ratio": -_ratio_improvement(current, candidate),
            }
    return metrics


def _rolling_validation(
    samples: Sequence[Mapping[str, Any]],
    previous: Mapping[str, float],
    calibration: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, float]]]:
    fold_count = int(calibration["minimum_rolling_folds"])
    validation_size = int(calibration["minimum_validation_samples_per_fold"])
    validation_total = fold_count * validation_size
    if len(samples) < validation_total:
        return [], []
    start = len(samples) - validation_total
    folds: list[dict[str, Any]] = []
    fold_weights: list[dict[str, float]] = []
    purge = int(calibration["purge_trading_days"])
    for fold_index in range(fold_count):
        validation_start = start + fold_index * validation_size
        validation = list(samples[validation_start : validation_start + validation_size])
        first_validation_index = int(validation[0]["as_of_index"])
        training = [
            sample
            for sample in samples[:validation_start]
            if int(sample["outcome_due_index"]) <= first_validation_index - purge
        ]
        if len(training) < validation_size:
            continue
        candidate = _fit_weights(training, previous, calibration)
        rows: list[dict[str, Any]] = []
        for sample in validation:
            current_forecast = _compose_forecast(sample["components"], previous)
            candidate_forecast = _compose_forecast(sample["components"], candidate)
            target = float(sample["target"])
            rows.append(
                {
                    "accepted_output_id": sample["accepted_output_id"],
                    "as_of": sample["as_of"],
                    "regime": sample["regime"],
                    "current_loss": (current_forecast["point_forecast"] - target) ** 2,
                    "candidate_loss": (candidate_forecast["point_forecast"] - target)
                    ** 2,
                    "current_direction_hit": _direction_hit(current_forecast, target),
                    "candidate_direction_hit": _direction_hit(candidate_forecast, target),
                }
            )
        folds.append(
            {
                "fold_index": fold_index + 1,
                "training_sample_count": len(training),
                "validation_sample_count": len(validation),
                "training_cutoff_as_of": training[-1]["as_of"],
                "validation_start_as_of": validation[0]["as_of"],
                "validation_end_as_of": validation[-1]["as_of"],
                "candidate_weights": candidate,
                "metrics": _metrics_from_predictions(rows),
                "prediction_rows": rows,
            }
        )
        fold_weights.append(candidate)
    return folds, fold_weights


def _candidate_gates(
    *,
    folds: Sequence[Mapping[str, Any]],
    fold_weights: Sequence[Mapping[str, float]],
    previous: Mapping[str, float],
    candidate: Mapping[str, float],
    calibration: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    rows = [row for fold in folds for row in fold["prediction_rows"]]
    metrics = _metrics_from_predictions(rows)
    failures: list[str] = []
    if metrics["mse_improvement_ratio"] < float(
        calibration["minimum_oos_mse_improvement_ratio"]
    ):
        failures.append("OOS_MSE_IMPROVEMENT_BELOW_GATE")
    if metrics["candidate_direction_hit_rate"] < metrics["current_direction_hit_rate"]:
        failures.append("OOS_DIRECTION_HIT_RATE_DECLINED")
    for regime, values in metrics["regimes"].items():
        if (
            values["sample_count"]
            >= int(calibration["minimum_regime_validation_samples"])
            and values["mse_degradation_ratio"]
            > float(calibration["maximum_regime_mse_degradation_ratio"])
        ):
            failures.append(f"{regime}_MSE_DEGRADATION_EXCEEDED")
    adjustment_agreement: dict[str, float] = {}
    bound_hit_ratios: dict[str, float] = {}
    lower = float(calibration["component_weight_lower_bound"])
    upper = float(calibration["component_weight_upper_bound"])
    for component in sorted(previous):
        delta = float(candidate[component]) - float(previous[component])
        if not math.isclose(delta, 0.0, abs_tol=1e-12):
            expected_sign = 1 if delta > 0 else -1
            agreement = sum(
                (
                    1
                    if (float(weights[component]) - float(previous[component]))
                    * expected_sign
                    > 1e-12
                    else 0
                )
                for weights in fold_weights
            ) / len(fold_weights)
            adjustment_agreement[component] = agreement
            if agreement < float(
                calibration["minimum_fold_adjustment_agreement_ratio"]
            ):
                failures.append(f"{component}:FOLD_ADJUSTMENT_AGREEMENT_BELOW_GATE")
        bound_ratio = sum(
            math.isclose(float(weights[component]), lower, abs_tol=1e-12)
            or math.isclose(float(weights[component]), upper, abs_tol=1e-12)
            for weights in fold_weights
        ) / len(fold_weights)
        bound_hit_ratios[component] = bound_ratio
        if bound_ratio > float(calibration["maximum_bound_hit_fold_ratio"]):
            failures.append(f"{component}:BOUND_HIT_RATIO_EXCEEDED")
    metrics["fold_adjustment_agreement"] = adjustment_agreement
    metrics["bound_hit_ratios"] = bound_hit_ratios
    return metrics, failures


def _insert_candidate(conn: sqlite3.Connection, record: Mapping[str, Any]) -> dict[str, Any]:
    record_json = canonical_json(record)
    existing = conn.execute(
        "SELECT record_json FROM component_calibration_candidates_v2 "
        "WHERE agent_id = ? AND calibration_half_year_slot = ?",
        (record["agent_id"], record["calibration_half_year_slot"]),
    ).fetchone()
    if existing is not None:
        if existing[0] != record_json:
            raise ValueError("component calibration semiannual slot is already frozen")
        return json.loads(existing[0])
    conn.execute(
        """
        INSERT INTO component_calibration_candidates_v2 (
            component_calibration_candidate_id,
            component_calibration_candidate_hash,
            agent_id,
            previous_component_weight_contract_version,
            calibration_contract_version,
            calibration_solver_version,
            calibration_half_year_slot,
            cutoff_at,
            fit_sample_count,
            candidate_status,
            candidate_weight_set_hash,
            record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["component_calibration_candidate_id"],
            record["component_calibration_candidate_hash"],
            record["agent_id"],
            record["previous_component_weight_contract_version"],
            record["calibration_contract_version"],
            record["calibration_solver_version"],
            record["calibration_half_year_slot"],
            record["cutoff_at"],
            record["fit_sample_count"],
            record["candidate_status"],
            record.get("candidate_weight_set_hash"),
            record_json,
        ),
    )
    return dict(record)


def run_component_calibration(
    conn: sqlite3.Connection,
    *,
    reference_track_key_hash: str,
    cutoff_at: str,
    trading_calendar_snapshot: Mapping[str, Any],
    regime_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Run one deterministic, semiannual, component-weight calibration audit."""
    track = _load_record(
        conn,
        "darwinian_v2_evaluation_tracks",
        "track_key_hash",
        reference_track_key_hash,
        json_column="contract_json",
    )
    agent_id = _required_text(track.get("agent_id"), "track.agent_id")
    _, calibration = _calibration_contract(agent_id)
    active_weights = resolve_component_weights(conn, agent_id=agent_id, at=cutoff_at)
    previous = {
        str(component): float(weight)
        for component, weight in active_weights["component_weights"].items()
    }
    if (
        track.get("cohort_id") != calibration["reference_cohort_id"]
        or track.get("language") != calibration["reference_language"]
        or track.get("component_weight_contract_version")
        != active_weights["component_weight_contract_version"]
    ):
        raise ValueError("component calibration requires the stable reference track")
    reference_roster_id = deterministic_id(
        "production-variant-roster",
        {
            "cohort_id": calibration["reference_cohort_id"],
            "language": calibration["reference_language"],
        },
    )
    current_revision_row = conn.execute(
        "SELECT record_json FROM darwinian_v2_production_variant_roster_revisions "
        "WHERE production_variant_roster_id = ? AND readiness = 'READY' "
        "AND effective_at <= ? ORDER BY effective_at DESC, rowid DESC LIMIT 1",
        (reference_roster_id, _timestamp(cutoff_at, "cutoff_at").isoformat()),
    ).fetchone()
    if current_revision_row is None:
        raise ValueError("component calibration reference variant is not READY")
    current_revision = json.loads(current_revision_row[0])
    if reference_track_key_hash not in current_revision.get(
        "evaluation_track_key_hashes", []
    ):
        raise ValueError("component calibration reference track is not current")
    dates, positions, cutoff_index = _verified_calendar(
        trading_calendar_snapshot,
        cutoff_at=cutoff_at,
    )
    slot = _semiannual_slot(dates, positions, cutoff_at)
    regimes = _regime_map(regime_snapshot, cutoff_at)
    reference_versions = {
        field: track[field]
        for field in (
            "agent_contract_version",
            "prompt_behavior_version",
            "execution_behavior_version",
            "outcome_contract_version",
            "scoring_contract_version",
            "sample_schedule_contract_version",
            "rank_scope_contract_version",
        )
    }
    samples, exclusions = _sample_groups(
        conn,
        agent_id=agent_id,
        sample_role="FIT_REFERENCE",
        cutoff_at=cutoff_at,
        dates=dates,
        positions=positions,
        cutoff_index=cutoff_index,
        regime_by_date=regimes,
        weights=previous,
        reference_track_key_hash=reference_track_key_hash,
        reference_versions=reference_versions,
        lookback_trading_days=int(calibration["maximum_lookback_trading_days"]),
    )
    candidate_weights: dict[str, float] | None = None
    folds: list[dict[str, Any]] = []
    validation_metrics: dict[str, Any] | None = None
    gate_failures: list[str] = []
    if len(samples) < int(calibration["minimum_fit_samples"]):
        status = "HELD_INSUFFICIENT_SAMPLES"
    else:
        folds, fold_weights = _rolling_validation(samples, previous, calibration)
        if len(folds) < int(calibration["minimum_rolling_folds"]):
            status = "HELD_INSUFFICIENT_FOLDS"
        else:
            candidate_weights = _fit_weights(samples, previous, calibration)
            validation_metrics, gate_failures = _candidate_gates(
                folds=folds,
                fold_weights=fold_weights,
                previous=previous,
                candidate=candidate_weights,
                calibration=calibration,
            )
            status = "REJECTED_GATES" if gate_failures else "SHADOW_CANDIDATE"

    diagnostics: dict[str, Any] = {}
    if candidate_weights is not None:
        diagnostic_samples, diagnostic_exclusions = _sample_groups(
            conn,
            agent_id=agent_id,
            sample_role="CROSS_VARIANT_DIAGNOSTIC",
            cutoff_at=cutoff_at,
            dates=dates,
            positions=positions,
            cutoff_index=cutoff_index,
            regime_by_date=regimes,
            weights=previous,
            reference_track_key_hash=reference_track_key_hash,
            reference_versions=reference_versions,
            lookback_trading_days=int(calibration["maximum_lookback_trading_days"]),
        )
        exclusions.extend(diagnostic_exclusions)
        by_variant: dict[str, list[dict[str, Any]]] = {}
        for sample in diagnostic_samples:
            by_variant.setdefault(str(sample["production_variant_roster_id"]), []).append(
                sample
            )
        for variant, variant_samples in sorted(by_variant.items()):
            rows: list[dict[str, Any]] = []
            for sample in variant_samples:
                current = _compose_forecast(sample["components"], previous)
                candidate = _compose_forecast(sample["components"], candidate_weights)
                target = float(sample["target"])
                rows.append(
                    {
                        "regime": sample["regime"],
                        "current_loss": (current["point_forecast"] - target) ** 2,
                        "candidate_loss": (candidate["point_forecast"] - target) ** 2,
                        "current_direction_hit": _direction_hit(current, target),
                        "candidate_direction_hit": _direction_hit(candidate, target),
                    }
                )
            metrics = _metrics_from_predictions(rows)
            blocking = metrics["sample_count"] >= int(
                calibration["minimum_diagnostic_paired_samples"]
            )
            rejected = blocking and -metrics["mse_improvement_ratio"] > float(
                calibration["maximum_diagnostic_mse_degradation_ratio"]
            )
            diagnostics[variant] = {
                **metrics,
                "blocking_eligibility": blocking,
                "gate_status": "REJECT" if rejected else "PASS" if blocking else "AUDIT_ONLY",
            }
            if rejected:
                gate_failures.append(f"{variant}:DIAGNOSTIC_MSE_DEGRADATION_EXCEEDED")
        if gate_failures and status == "SHADOW_CANDIDATE":
            status = "REJECTED_GATES"

    sample_snapshot = [
        {
            "accepted_output_id": sample["accepted_output_id"],
            "accepted_output_hash": sample["accepted_output_hash"],
            "outcome_label_id": sample["outcome_label_id"],
            "outcome_label_hash": sample["outcome_label_hash"],
            "as_of": sample["as_of"],
            "target": sample["target"],
            "regime": sample["regime"],
            "component_signal_hashes": sorted(
                row["component_calibration_signal_hash"]
                for row in sample["components"].values()
            ),
        }
        for sample in samples
    ]
    candidate_weight_set_hash = (
        canonical_hash(candidate_weights) if candidate_weights is not None else None
    )
    identity = {
        "agent_id": agent_id,
        "reference_track_key_hash": reference_track_key_hash,
        "calibration_half_year_slot": slot,
        "calibration_contract_version": calibration["calibration_contract_version"],
        "sample_snapshot_hash": canonical_hash(sample_snapshot),
        "regime_snapshot_hash": regime_snapshot["snapshot_hash"],
        "trading_calendar_snapshot_hash": trading_calendar_snapshot["snapshot_hash"],
    }
    candidate_id = deterministic_id("component-calibration-candidate", identity)
    without_hash = {
        "component_calibration_candidate_id": candidate_id,
        "schema_version": "component_calibration_candidate_v2",
        "agent_id": agent_id,
        "reference_track_key_hash": reference_track_key_hash,
        "previous_component_weight_contract_version": active_weights[
            "component_weight_contract_version"
        ],
        "calibration_contract_version": calibration["calibration_contract_version"],
        "calibration_solver_version": calibration["calibration_solver_version"],
        "calibration_contract": dict(calibration),
        "calibration_half_year_slot": slot,
        "cutoff_at": _timestamp(cutoff_at, "cutoff_at").isoformat(),
        "trading_calendar_snapshot_hash": trading_calendar_snapshot["snapshot_hash"],
        "regime_snapshot_hash": regime_snapshot["snapshot_hash"],
        "previous_weights": previous,
        "candidate_weights": candidate_weights,
        "candidate_weight_set_hash": candidate_weight_set_hash,
        "fit_sample_count": len(samples),
        "fit_sample_snapshot": sample_snapshot,
        "fit_sample_snapshot_hash": canonical_hash(sample_snapshot),
        "excluded_samples": sorted(
            exclusions,
            key=lambda row: (row["accepted_output_id"], row["reason"]),
        ),
        "rolling_folds": folds,
        "validation_metrics": validation_metrics,
        "cross_variant_diagnostics": diagnostics,
        "gate_failures": sorted(set(gate_failures)),
        "candidate_status": status,
        "production_sample_threshold_met": len(samples)
        >= int(calibration["minimum_production_samples"]),
    }
    record = {
        **without_hash,
        "component_calibration_candidate_hash": canonical_hash(without_hash),
    }
    return _insert_candidate(conn, record)


def _load_candidate(
    conn: sqlite3.Connection,
    candidate_id: str,
) -> dict[str, Any]:
    candidate = _load_record(
        conn,
        "component_calibration_candidates_v2",
        "component_calibration_candidate_id",
        candidate_id,
    )
    _verify_hash(
        candidate,
        "component_calibration_candidate_hash",
        "component calibration candidate",
    )
    return candidate


def append_component_shadow_checkpoint(
    conn: sqlite3.Connection,
    *,
    component_calibration_candidate_id: str,
    cutoff_at: str,
    trading_calendar_snapshot: Mapping[str, Any],
    regime_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate every matured post-cutoff reference sample for one frozen candidate."""
    candidate = _load_candidate(conn, component_calibration_candidate_id)
    if candidate.get("candidate_status") != "SHADOW_CANDIDATE":
        raise ValueError("only a passed shadow candidate can accumulate shadow evidence")
    if _timestamp(cutoff_at, "cutoff_at") <= _timestamp(
        candidate["cutoff_at"], "candidate.cutoff_at"
    ):
        raise ValueError("shadow cutoff must be later than the calibration cutoff")
    agent_id = str(candidate["agent_id"])
    previous, calibration = _calibration_contract(agent_id)
    if previous != candidate.get("previous_weights"):
        raise ValueError("component calibration source weights drifted")
    candidate_weights = candidate.get("candidate_weights")
    if not isinstance(candidate_weights, Mapping):
        raise ValueError("component shadow candidate has no weight set")
    dates, positions, cutoff_index = _verified_calendar(
        trading_calendar_snapshot,
        cutoff_at=cutoff_at,
    )
    regimes = _regime_map(regime_snapshot, cutoff_at)
    track = _load_record(
        conn,
        "darwinian_v2_evaluation_tracks",
        "track_key_hash",
        str(candidate["reference_track_key_hash"]),
        json_column="contract_json",
    )
    reference_versions = {
        field: track[field]
        for field in (
            "agent_contract_version",
            "prompt_behavior_version",
            "execution_behavior_version",
            "outcome_contract_version",
            "scoring_contract_version",
            "sample_schedule_contract_version",
            "rank_scope_contract_version",
        )
    }
    samples, exclusions = _sample_groups(
        conn,
        agent_id=agent_id,
        sample_role="FIT_REFERENCE",
        cutoff_at=cutoff_at,
        dates=dates,
        positions=positions,
        cutoff_index=cutoff_index,
        regime_by_date=regimes,
        weights=previous,
        reference_track_key_hash=str(candidate["reference_track_key_hash"]),
        reference_versions=reference_versions,
        lookback_trading_days=int(calibration["maximum_lookback_trading_days"]),
    )
    new_samples = [
        sample
        for sample in samples
        if _timestamp(f"{sample['as_of']}T15:00:00+08:00", "sample.as_of")
        > _timestamp(candidate["cutoff_at"], "candidate.cutoff_at")
    ]
    inserted = 0
    for sample in new_samples:
        current_forecast = _compose_forecast(sample["components"], previous)
        shadow_forecast = _compose_forecast(sample["components"], candidate_weights)
        target = float(sample["target"])
        current_loss = (current_forecast["point_forecast"] - target) ** 2
        shadow_loss = (shadow_forecast["point_forecast"] - target) ** 2
        identity = {
            "component_calibration_candidate_hash": candidate[
                "component_calibration_candidate_hash"
            ],
            "accepted_output_hash": sample["accepted_output_hash"],
            "outcome_label_hash": sample["outcome_label_hash"],
        }
        evaluation_id = deterministic_id("component-calibration-shadow", identity)
        without_hash = {
            "component_calibration_shadow_evaluation_id": evaluation_id,
            "schema_version": "component_calibration_shadow_evaluation_v2",
            "component_calibration_candidate_id": component_calibration_candidate_id,
            "component_calibration_candidate_hash": candidate[
                "component_calibration_candidate_hash"
            ],
            "accepted_output_id": sample["accepted_output_id"],
            "accepted_output_hash": sample["accepted_output_hash"],
            "outcome_label_id": sample["outcome_label_id"],
            "outcome_label_hash": sample["outcome_label_hash"],
            "production_variant_roster_id": sample[
                "production_variant_roster_id"
            ],
            "agent_id": agent_id,
            "as_of": sample["as_of"],
            "outcome_due_at": sample["outcome_due_at"],
            "matured_at": sample["matured_at"],
            "regime": sample["regime"],
            "target": target,
            "current_point_forecast": current_forecast["point_forecast"],
            "candidate_point_forecast": shadow_forecast["point_forecast"],
            "current_direction_hit": _direction_hit(current_forecast, target),
            "candidate_direction_hit": _direction_hit(shadow_forecast, target),
            "current_loss": current_loss,
            "candidate_loss": shadow_loss,
            "component_signal_hashes": sorted(
                row["component_calibration_signal_hash"]
                for row in sample["components"].values()
            ),
            "regime_evidence_ids": sample["regime_evidence_ids"],
        }
        record = {
            **without_hash,
            "component_calibration_shadow_evaluation_hash": canonical_hash(
                without_hash
            ),
        }
        record_json = canonical_json(record)
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO component_calibration_shadow_evaluations_v2 (
                component_calibration_shadow_evaluation_id,
                component_calibration_shadow_evaluation_hash,
                component_calibration_candidate_id,
                accepted_output_id,
                outcome_label_id,
                production_variant_roster_id,
                agent_id,
                as_of,
                regime,
                current_loss,
                candidate_loss,
                record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id,
                record["component_calibration_shadow_evaluation_hash"],
                component_calibration_candidate_id,
                sample["accepted_output_id"],
                sample["outcome_label_id"],
                sample["production_variant_roster_id"],
                agent_id,
                sample["as_of"],
                sample["regime"],
                current_loss,
                shadow_loss,
                record_json,
            ),
        )
        if cursor.rowcount == 1:
            inserted += 1
        else:
            existing = conn.execute(
                "SELECT record_json FROM component_calibration_shadow_evaluations_v2 "
                "WHERE component_calibration_candidate_id = ? AND accepted_output_id = ?",
                (component_calibration_candidate_id, sample["accepted_output_id"]),
            ).fetchone()
            if existing is None or existing[0] != record_json:
                raise ValueError("immutable component shadow evaluation collision")

    persisted_rows = conn.execute(
        "SELECT record_json FROM component_calibration_shadow_evaluations_v2 "
        "WHERE component_calibration_candidate_id = ? AND as_of <= ? ORDER BY as_of",
        (
            component_calibration_candidate_id,
            _timestamp(cutoff_at, "cutoff_at").date().isoformat(),
        ),
    ).fetchall()
    evaluations = [json.loads(row[0]) for row in persisted_rows]
    metrics = _metrics_from_predictions(evaluations) if evaluations else None
    failures: list[str] = []
    if len(evaluations) < int(calibration["minimum_shadow_samples"]):
        status = "HELD_INSUFFICIENT_SAMPLES"
    else:
        if metrics is None:
            raise ValueError("component shadow metrics are unavailable")
        if metrics["mse_improvement_ratio"] < float(
            calibration["minimum_oos_mse_improvement_ratio"]
        ):
            failures.append("SHADOW_MSE_IMPROVEMENT_BELOW_GATE")
        if metrics["candidate_direction_hit_rate"] < metrics[
            "current_direction_hit_rate"
        ]:
            failures.append("SHADOW_DIRECTION_HIT_RATE_DECLINED")
        for regime, values in metrics["regimes"].items():
            if (
                values["sample_count"]
                >= int(calibration["minimum_regime_validation_samples"])
                and values["mse_degradation_ratio"]
                > float(calibration["maximum_regime_mse_degradation_ratio"])
            ):
                failures.append(f"SHADOW_{regime}_MSE_DEGRADATION_EXCEEDED")
        total_reference_samples = int(candidate["fit_sample_count"]) + len(evaluations)
        if total_reference_samples < int(calibration["minimum_production_samples"]):
            failures.append("PRODUCTION_SAMPLE_THRESHOLD_NOT_MET")
        status = "REJECTED_GATES" if failures else "PROMOTION_ELIGIBLE"
    identity = {
        "component_calibration_candidate_hash": candidate[
            "component_calibration_candidate_hash"
        ],
        "cutoff_at": _timestamp(cutoff_at, "cutoff_at").isoformat(),
        "shadow_evaluation_hashes": [
            row["component_calibration_shadow_evaluation_hash"] for row in evaluations
        ],
        "trading_calendar_snapshot_hash": trading_calendar_snapshot["snapshot_hash"],
        "regime_snapshot_hash": regime_snapshot["snapshot_hash"],
    }
    checkpoint_id = deterministic_id("component-calibration-shadow-checkpoint", identity)
    without_hash = {
        "component_calibration_shadow_checkpoint_id": checkpoint_id,
        "schema_version": "component_calibration_shadow_checkpoint_v2",
        "component_calibration_candidate_id": component_calibration_candidate_id,
        "component_calibration_candidate_hash": candidate[
            "component_calibration_candidate_hash"
        ],
        "agent_id": agent_id,
        "cutoff_at": identity["cutoff_at"],
        "trading_calendar_snapshot_hash": trading_calendar_snapshot["snapshot_hash"],
        "regime_snapshot_hash": regime_snapshot["snapshot_hash"],
        "new_shadow_sample_count": len(evaluations),
        "new_shadow_evaluation_ids": [
            row["component_calibration_shadow_evaluation_id"] for row in evaluations
        ],
        "new_shadow_evaluation_hashes": identity["shadow_evaluation_hashes"],
        "excluded_samples": exclusions,
        "shadow_metrics": metrics,
        "gate_failures": failures,
        "checkpoint_status": status,
    }
    checkpoint = {
        **without_hash,
        "component_calibration_shadow_checkpoint_hash": canonical_hash(without_hash),
        "inserted_shadow_evaluations": inserted,
    }
    persisted_without_runtime = {
        key: value for key, value in checkpoint.items() if key != "inserted_shadow_evaluations"
    }
    record_json = canonical_json(persisted_without_runtime)
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO component_calibration_shadow_checkpoints_v2 (
            component_calibration_shadow_checkpoint_id,
            component_calibration_shadow_checkpoint_hash,
            component_calibration_candidate_id,
            agent_id,
            cutoff_at,
            new_shadow_sample_count,
            checkpoint_status,
            record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            checkpoint_id,
            persisted_without_runtime[
                "component_calibration_shadow_checkpoint_hash"
            ],
            component_calibration_candidate_id,
            agent_id,
            identity["cutoff_at"],
            len(evaluations),
            status,
            record_json,
        ),
    )
    if cursor.rowcount == 0:
        existing = conn.execute(
            "SELECT record_json FROM component_calibration_shadow_checkpoints_v2 "
            "WHERE component_calibration_candidate_id = ? AND cutoff_at = ?",
            (component_calibration_candidate_id, identity["cutoff_at"]),
        ).fetchone()
        if existing is None or existing[0] != record_json:
            raise ValueError("immutable component shadow checkpoint collision")
    return checkpoint


def _latest_component_release(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    at: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT record_json FROM component_weight_release_revisions_v2 "
        "WHERE agent_id = ? AND effective_at <= ? "
        "ORDER BY effective_at DESC, release_sequence DESC LIMIT 1",
        (agent_id, _timestamp(at, "at").isoformat()),
    ).fetchone()
    if row is None:
        return None
    record = json.loads(row[0])
    _verify_hash(
        record,
        "component_weight_release_revision_hash",
        "component weight release",
    )
    return record


def resolve_component_weights(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    at: str,
) -> dict[str, Any]:
    """Resolve immutable structural weights without consulting Darwinian/KNOT state."""
    default_weights, _ = _calibration_contract(agent_id)
    default_version = OUTCOME_CONTRACTS[agent_id]["component_composition_contract"][
        "component_weight_contract_version"
    ]
    release = _latest_component_release(conn, agent_id=agent_id, at=at)
    if release is None:
        return {
            "agent_id": agent_id,
            "component_weight_contract_version": default_version,
            "component_weights": default_weights,
            "release_revision_id": None,
            "release_revision_hash": None,
            "effective_at": None,
        }
    return {
        "agent_id": agent_id,
        "component_weight_contract_version": release[
            "target_component_weight_contract_version"
        ],
        "component_weights": release["target_component_weights"],
        "release_revision_id": release["component_weight_release_revision_id"],
        "release_revision_hash": release["component_weight_release_revision_hash"],
        "effective_at": release["effective_at"],
    }


def publish_component_weight_release(
    conn: sqlite3.Connection,
    *,
    component_calibration_candidate_id: str,
    component_calibration_shadow_checkpoint_id: str,
    recorded_at: str,
    effective_at: str,
) -> dict[str, Any]:
    """Publish a passed candidate prospectively for every production variant."""
    candidate = _load_candidate(conn, component_calibration_candidate_id)
    checkpoint = _load_record(
        conn,
        "component_calibration_shadow_checkpoints_v2",
        "component_calibration_shadow_checkpoint_id",
        component_calibration_shadow_checkpoint_id,
    )
    _verify_hash(
        checkpoint,
        "component_calibration_shadow_checkpoint_hash",
        "component shadow checkpoint",
    )
    if (
        checkpoint.get("component_calibration_candidate_id")
        != component_calibration_candidate_id
        or checkpoint.get("checkpoint_status") != "PROMOTION_ELIGIBLE"
    ):
        raise ValueError("component weight release requires a promotion-eligible checkpoint")
    recorded = _timestamp(recorded_at, "recorded_at")
    effective = _timestamp(effective_at, "effective_at")
    if effective <= recorded or recorded < _timestamp(
        checkpoint["cutoff_at"], "checkpoint.cutoff_at"
    ):
        raise ValueError("component weight release must be prospective")
    agent_id = str(candidate["agent_id"])
    active = resolve_component_weights(conn, agent_id=agent_id, at=recorded.isoformat())
    if active["component_weight_contract_version"] != candidate[
        "previous_component_weight_contract_version"
    ]:
        raise ValueError("component weight release base version is no longer active")
    latest_row = conn.execute(
        "SELECT record_json FROM component_weight_release_revisions_v2 "
        "WHERE agent_id = ? ORDER BY release_sequence DESC LIMIT 1",
        (agent_id,),
    ).fetchone()
    latest = json.loads(latest_row[0]) if latest_row else None
    sequence = int(latest["release_sequence"]) + 1 if latest else 1
    target_version = (
        f"{agent_id}_component_weights_"
        f"{candidate['candidate_weight_set_hash'].removeprefix('sha256:')[:16]}_v1"
    )
    identity = {
        "agent_id": agent_id,
        "release_sequence": sequence,
        "component_calibration_candidate_hash": candidate[
            "component_calibration_candidate_hash"
        ],
        "component_calibration_shadow_checkpoint_hash": checkpoint[
            "component_calibration_shadow_checkpoint_hash"
        ],
        "target_component_weight_contract_version": target_version,
        "effective_at": effective.isoformat(),
    }
    release_id = deterministic_id("component-weight-release", identity)
    without_hash = {
        "component_weight_release_revision_id": release_id,
        "schema_version": "component_weight_release_revision_v2",
        "agent_id": agent_id,
        "release_sequence": sequence,
        "supersedes_revision_id": (
            latest["component_weight_release_revision_id"] if latest else None
        ),
        "action": "PUBLISH",
        "component_calibration_candidate_id": component_calibration_candidate_id,
        "component_calibration_candidate_hash": candidate[
            "component_calibration_candidate_hash"
        ],
        "component_calibration_shadow_checkpoint_id": (
            component_calibration_shadow_checkpoint_id
        ),
        "component_calibration_shadow_checkpoint_hash": checkpoint[
            "component_calibration_shadow_checkpoint_hash"
        ],
        "previous_component_weight_contract_version": active[
            "component_weight_contract_version"
        ],
        "previous_component_weights": active["component_weights"],
        "target_component_weight_contract_version": target_version,
        "target_component_weights": candidate["candidate_weights"],
        "activation_scope": "ALL_PRODUCTION_COHORT_LANGUAGE_VARIANTS",
        "recorded_at": recorded.isoformat(),
        "effective_at": effective.isoformat(),
    }
    record = {
        **without_hash,
        "component_weight_release_revision_hash": canonical_hash(without_hash),
    }
    conn.execute(
        """
        INSERT INTO component_weight_release_revisions_v2 (
            component_weight_release_revision_id,
            component_weight_release_revision_hash,
            agent_id,
            release_sequence,
            supersedes_revision_id,
            action,
            component_calibration_candidate_id,
            component_calibration_shadow_checkpoint_id,
            previous_component_weight_contract_version,
            target_component_weight_contract_version,
            effective_at,
            record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            release_id,
            record["component_weight_release_revision_hash"],
            agent_id,
            sequence,
            without_hash["supersedes_revision_id"],
            "PUBLISH",
            component_calibration_candidate_id,
            component_calibration_shadow_checkpoint_id,
            without_hash["previous_component_weight_contract_version"],
            target_version,
            effective.isoformat(),
            canonical_json(record),
        ),
    )
    return record


def rollback_component_weight_release(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    rollback_to_revision_id: str,
    recorded_at: str,
    effective_at: str,
) -> dict[str, Any]:
    """Append a prospective rollback to a previously published structural version."""
    recorded = _timestamp(recorded_at, "recorded_at")
    effective = _timestamp(effective_at, "effective_at")
    if effective <= recorded:
        raise ValueError("component weight rollback must be prospective")
    current = _latest_component_release(conn, agent_id=agent_id, at=recorded.isoformat())
    if current is None:
        raise ValueError("component weight rollback has no active release")
    target = _load_record(
        conn,
        "component_weight_release_revisions_v2",
        "component_weight_release_revision_id",
        rollback_to_revision_id,
    )
    _verify_hash(
        target,
        "component_weight_release_revision_hash",
        "rollback target release",
    )
    if (
        target.get("agent_id") != agent_id
        or int(target.get("release_sequence", 0)) > int(current["release_sequence"])
    ):
        raise ValueError("component rollback target must be an active/prior release for this Agent")
    latest_row = conn.execute(
        "SELECT record_json FROM component_weight_release_revisions_v2 "
        "WHERE agent_id = ? ORDER BY release_sequence DESC LIMIT 1",
        (agent_id,),
    ).fetchone()
    if latest_row is None:
        raise ValueError("component release ledger is unavailable")
    latest = json.loads(latest_row[0])
    if latest["component_weight_release_revision_id"] != current[
        "component_weight_release_revision_id"
    ]:
        raise ValueError("component rollback cannot bypass a pending future release")
    sequence = int(latest["release_sequence"]) + 1
    undo_current = (
        rollback_to_revision_id == current["component_weight_release_revision_id"]
    )
    target_version = (
        target["previous_component_weight_contract_version"]
        if undo_current
        else target["target_component_weight_contract_version"]
    )
    target_weights = (
        target["previous_component_weights"]
        if undo_current
        else target["target_component_weights"]
    )
    if target_version == current["target_component_weight_contract_version"]:
        raise ValueError("component rollback target is already active")
    identity = {
        "agent_id": agent_id,
        "release_sequence": sequence,
        "rollback_to_revision_id": rollback_to_revision_id,
        "effective_at": effective.isoformat(),
    }
    release_id = deterministic_id("component-weight-release", identity)
    without_hash = {
        "component_weight_release_revision_id": release_id,
        "schema_version": "component_weight_release_revision_v2",
        "agent_id": agent_id,
        "release_sequence": sequence,
        "supersedes_revision_id": latest["component_weight_release_revision_id"],
        "action": "ROLLBACK",
        "component_calibration_candidate_id": None,
        "component_calibration_shadow_checkpoint_id": None,
        "rollback_to_revision_id": rollback_to_revision_id,
        "previous_component_weight_contract_version": current[
            "target_component_weight_contract_version"
        ],
        "previous_component_weights": current["target_component_weights"],
        "target_component_weight_contract_version": target_version,
        "target_component_weights": target_weights,
        "activation_scope": "ALL_PRODUCTION_COHORT_LANGUAGE_VARIANTS",
        "recorded_at": recorded.isoformat(),
        "effective_at": effective.isoformat(),
    }
    record = {
        **without_hash,
        "component_weight_release_revision_hash": canonical_hash(without_hash),
    }
    conn.execute(
        """
        INSERT INTO component_weight_release_revisions_v2 (
            component_weight_release_revision_id,
            component_weight_release_revision_hash,
            agent_id,
            release_sequence,
            supersedes_revision_id,
            action,
            component_calibration_candidate_id,
            component_calibration_shadow_checkpoint_id,
            previous_component_weight_contract_version,
            target_component_weight_contract_version,
            effective_at,
            record_json
        ) VALUES (?, ?, ?, ?, ?, 'ROLLBACK', NULL, NULL, ?, ?, ?, ?)
        """,
        (
            release_id,
            record["component_weight_release_revision_hash"],
            agent_id,
            sequence,
            latest["component_weight_release_revision_id"],
            without_hash["previous_component_weight_contract_version"],
            without_hash["target_component_weight_contract_version"],
            effective.isoformat(),
            canonical_json(record),
        ),
    )
    return record


__all__ = [
    "append_component_calibration_signals",
    "append_component_shadow_checkpoint",
    "build_component_regime_snapshot",
    "publish_component_weight_release",
    "resolve_component_weights",
    "rollback_component_weight_release",
    "run_component_calibration",
    "validate_accepted_macro_component_composition",
]

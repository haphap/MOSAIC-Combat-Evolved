"""Append-only Darwinian v2 track registration and production reads."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from typing import Any, Mapping

from mosaic.scorecard.canonical_json import canonical_hash, canonical_json
from mosaic.scorecard.accepted_output_contracts import (
    validate_accepted_output_record_schema,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS


_VERSION_FIELDS = (
    "agent_contract_version",
    "prompt_behavior_version",
    "execution_behavior_version",
)
_NULLABLE_TRACK_DIMENSIONS = {
    "component_weight_contract_version": "component_weight_contract",
    "reliability_adapter_contract_version": "reliability_adapter_contract",
    "confidence_semantics_contract_version": "confidence_semantics_contract",
}
_MACRO_AGENT_IDS = tuple(
    agent_id
    for agent_id, contract in OUTCOME_CONTRACTS.items()
    if contract["layer"] == "MACRO"
)
_MACRO_ATTRIBUTION_REQUIRED_ACCEPTED_KINDS = frozenset(
    {
        "STANDARD_SECTOR_SELECTION",
        "RELATIONSHIP_GRAPH",
        "SUPERINVESTOR_SELECTION",
        "ALPHA_DISCOVERY",
        "CRO_RISK_REVIEW",
        "CIO_PROPOSAL",
        "CIO_FINAL",
    }
)


def deterministic_id(namespace: str, value: Any) -> str:
    return f"{namespace}:{canonical_hash(value).removeprefix('sha256:')}"


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _timestamp(value: Any, label: str) -> datetime:
    text = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _validated_behavior_binding(
    agent_id: str,
    raw: Mapping[str, Any],
) -> dict[str, str | None]:
    contract = OUTCOME_CONTRACTS[agent_id]
    result: dict[str, str | None] = {}
    for field in _VERSION_FIELDS:
        result[field] = _required_text(raw.get(field), f"{agent_id}.{field}")
    dimensions = contract["track_contract_dimensions"]
    for field, dimension in _NULLABLE_TRACK_DIMENSIONS.items():
        value = raw.get(field)
        if dimensions[dimension] == "REQUIRED":
            result[field] = _required_text(value, f"{agent_id}.{field}")
        elif value is not None:
            raise ValueError(f"{agent_id}.{field} must be null")
        else:
            result[field] = None
    return result


def _insert_record_or_verify(
    conn: sqlite3.Connection,
    *,
    table: str,
    key_column: str,
    key: str,
    columns: tuple[str, ...],
    values: tuple[Any, ...],
    json_column: str,
    record_json: str,
) -> bool:
    placeholders = ", ".join("?" for _ in columns)
    cursor = conn.execute(
        f"INSERT OR IGNORE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    if cursor.rowcount == 1:
        return True
    existing = conn.execute(
        f"SELECT {json_column} FROM {table} WHERE {key_column} = ?",
        (key,),
    ).fetchone()
    if existing is None or existing[0] != record_json:
        raise ValueError(f"immutable record collision in {table}: {key}")
    return False


def register_production_variant(
    conn: sqlite3.Connection,
    *,
    cohort_id: str,
    language: str,
    execution_behavior_release_id: str,
    behavior_bindings: Mapping[str, Mapping[str, Any]],
    effective_at: str,
    prepared_at: str | None = None,
    recorded_at: str | None = None,
    effective_slot_sequence: int | None = None,
) -> dict[str, Any]:
    cohort_id = _required_text(cohort_id, "cohort_id")
    if language not in {"en", "zh"}:
        raise ValueError("language must be en or zh")
    release_id = _required_text(
        execution_behavior_release_id,
        "execution_behavior_release_id",
    )
    effective_at = _required_text(effective_at, "effective_at")
    prepared_at = _required_text(
        effective_at if prepared_at is None else prepared_at,
        "prepared_at",
    )
    recorded_at = _required_text(
        effective_at if recorded_at is None else recorded_at,
        "recorded_at",
    )
    if not (
        _timestamp(prepared_at, "prepared_at")
        <= _timestamp(recorded_at, "recorded_at")
        <= _timestamp(effective_at, "effective_at")
    ):
        raise ValueError(
            "roster revision timestamps must satisfy "
            "prepared_at <= recorded_at <= effective_at"
        )
    if effective_slot_sequence is not None and (
        isinstance(effective_slot_sequence, bool)
        or not isinstance(effective_slot_sequence, int)
        or effective_slot_sequence < 1
    ):
        raise ValueError("effective_slot_sequence must be a positive integer")
    if set(behavior_bindings) != set(OUTCOME_CONTRACTS):
        raise ValueError("behavior_bindings must cover the exact 28-Agent roster")

    roster_id = deterministic_id(
        "production-variant-roster",
        {"cohort_id": cohort_id, "language": language},
    )
    track_rows: list[dict[str, Any]] = []
    for agent_id in sorted(OUTCOME_CONTRACTS):
        outcome = OUTCOME_CONTRACTS[agent_id]
        behavior = _validated_behavior_binding(agent_id, behavior_bindings[agent_id])
        track_key = {
            "production_variant_roster_id": roster_id,
            "cohort_id": cohort_id,
            "language": language,
            "agent_id": agent_id,
            "darwin_application_mode": outcome["darwin_application_mode"],
            **behavior,
            "outcome_contract_version": outcome["outcome_contract_version"],
            "scoring_contract_version": outcome["scoring_contract_version"],
            "sample_schedule_contract_version": outcome[
                "sample_schedule_contract_version"
            ],
            "rank_scope_contract_version": outcome["rank_scope_contract_version"],
            "rank_scope": outcome["rank_scope"],
            "primary_label_id": outcome["primary_label_id"],
        }
        track_key_hash = canonical_hash(track_key)
        usage_track_key_hash = None
        if outcome["darwin_application_mode"] == "DOWNSTREAM_USAGE_WEIGHT":
            usage_track_key_hash = canonical_hash(
                {
                    "production_variant_roster_id": roster_id,
                    "evaluation_track_key_hash": track_key_hash,
                    "darwin_application_mode": "DOWNSTREAM_USAGE_WEIGHT",
                }
            )
        track_rows.append(
            {
                "agent_id": agent_id,
                "outcome": outcome,
                "behavior": behavior,
                "track_key": track_key,
                "track_key_hash": track_key_hash,
                "usage_track_key_hash": usage_track_key_hash,
            }
        )

    evaluation_hashes = [row["track_key_hash"] for row in track_rows]
    usage_hashes = [
        row["usage_track_key_hash"]
        for row in track_rows
        if row["usage_track_key_hash"] is not None
    ]
    decision_hashes = [
        row["track_key_hash"]
        for row in track_rows
        if row["outcome"]["darwin_application_mode"] == "EVOLUTION_ONLY"
    ]
    if len(evaluation_hashes) != 28 or len(usage_hashes) != 24 or len(decision_hashes) != 4:
        raise ValueError("Darwinian production roster must have 28/24/4 tracks")

    natural_revision = conn.execute(
        """
        SELECT record_json
        FROM darwinian_v2_production_variant_roster_revisions
        WHERE production_variant_roster_id = ?
          AND execution_behavior_release_id = ?
          AND cohort_id = ? AND language = ? AND effective_at = ?
          AND evaluation_track_key_hashes_json = ?
          AND usage_track_key_hashes_json = ?
          AND decision_evaluation_track_key_hashes_json = ?
          AND prepared_at IS NOT NULL AND recorded_at IS NOT NULL
          AND effective_slot_sequence IS NOT NULL
        """,
        (
            roster_id,
            release_id,
            cohort_id,
            language,
            effective_at,
            canonical_json(evaluation_hashes),
            canonical_json(usage_hashes),
            canonical_json(decision_hashes),
        ),
    ).fetchone()
    if natural_revision is not None:
        existing = json.loads(natural_revision[0])
        if (
            existing.get("prepared_at") != prepared_at
            or existing.get("recorded_at") != recorded_at
            or (
                effective_slot_sequence is not None
                and existing.get("effective_slot_sequence") != effective_slot_sequence
            )
        ):
            raise ValueError("production roster revision timing collision")
        return {
            **existing,
            "inserted_evaluation_tracks": 0,
            "inserted_usage_tracks": 0,
            "inserted_cold_start_weights": 0,
            "inserted_roster_revision": False,
        }

    previous_sequence = conn.execute(
        """
        SELECT COALESCE(MAX(effective_slot_sequence), 0)
        FROM darwinian_v2_production_variant_roster_revisions
        WHERE production_variant_roster_id = ?
        """,
        (roster_id,),
    ).fetchone()[0]
    next_sequence = int(previous_sequence) + 1
    if effective_slot_sequence is None:
        effective_slot_sequence = next_sequence
    elif effective_slot_sequence != next_sequence:
        raise ValueError("effective_slot_sequence must be the next roster sequence")

    revision_identity = {
        "production_variant_roster_id": roster_id,
        "execution_behavior_release_id": release_id,
        "cohort_id": cohort_id,
        "language": language,
        "evaluation_track_key_hashes": evaluation_hashes,
        "usage_track_key_hashes": usage_hashes,
        "decision_evaluation_track_key_hashes": decision_hashes,
        "prepared_at": prepared_at,
        "recorded_at": recorded_at,
        "effective_at": effective_at,
        "effective_slot_sequence": effective_slot_sequence,
    }
    revision_id = deterministic_id("production-variant-roster-revision", revision_identity)
    revision_without_hash = {
        "production_variant_roster_revision_id": revision_id,
        **revision_identity,
        "readiness": "READY",
    }
    revision_hash = canonical_hash(revision_without_hash)
    revision = {
        **revision_without_hash,
        "production_variant_roster_revision_hash": revision_hash,
    }

    inserted_tracks = 0
    inserted_usage_tracks = 0
    inserted_weights = 0
    for row in track_rows:
        track_record = {
            **row["track_key"],
            "track_key_hash": row["track_key_hash"],
            "first_registered_roster_revision_id": revision_id,
            "outcome_contract": dict(row["outcome"]),
            "registered_at": recorded_at,
        }
        track_json = canonical_json(track_record)
        existing = conn.execute(
            "SELECT track_key_hash FROM darwinian_v2_evaluation_tracks WHERE track_key_hash = ?",
            (row["track_key_hash"],),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO darwinian_v2_evaluation_tracks (
                    track_key_hash, production_variant_roster_id,
                    first_registered_roster_revision_id, cohort_id, language,
                    agent_id, darwin_application_mode, agent_contract_version,
                    prompt_behavior_version, execution_behavior_version,
                    component_weight_contract_version,
                    reliability_adapter_contract_version,
                    confidence_semantics_contract_version,
                    outcome_contract_version, scoring_contract_version,
                    sample_schedule_contract_version, rank_scope_contract_version,
                    rank_scope, primary_label_id, contract_json, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["track_key_hash"],
                    roster_id,
                    revision_id,
                    cohort_id,
                    language,
                    row["agent_id"],
                    row["outcome"]["darwin_application_mode"],
                    row["behavior"]["agent_contract_version"],
                    row["behavior"]["prompt_behavior_version"],
                    row["behavior"]["execution_behavior_version"],
                    row["behavior"]["component_weight_contract_version"],
                    row["behavior"]["reliability_adapter_contract_version"],
                    row["behavior"]["confidence_semantics_contract_version"],
                    row["outcome"]["outcome_contract_version"],
                    row["outcome"]["scoring_contract_version"],
                    row["outcome"]["sample_schedule_contract_version"],
                    row["outcome"]["rank_scope_contract_version"],
                    row["outcome"]["rank_scope"],
                    row["outcome"]["primary_label_id"],
                    track_json,
                    recorded_at,
                ),
            )
            inserted_tracks += 1

        usage_hash = row["usage_track_key_hash"]
        if usage_hash is None:
            continue
        usage_cursor = conn.execute(
            """
            INSERT OR IGNORE INTO darwinian_v2_usage_tracks (
                usage_track_key_hash, production_variant_roster_id,
                evaluation_track_key_hash, agent_id, registered_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                usage_hash,
                roster_id,
                row["track_key_hash"],
                row["agent_id"],
                recorded_at,
            ),
        )
        inserted_usage_tracks += int(usage_cursor.rowcount == 1)

        existing_cold_start = conn.execute(
            """
            SELECT weight_record_id
            FROM darwinian_v2_usage_weight_records
            WHERE usage_track_key_hash = ?
              AND record_kind = 'COLD_START_INITIALIZATION'
            """,
            (usage_hash,),
        ).fetchone()
        if existing_cold_start is not None:
            continue

        weight_id = deterministic_id(
            "darwin-weight-cold-start",
            {"usage_track_key_hash": usage_hash},
        )
        weight_without_hash = {
            "weight_record_id": weight_id,
            "usage_track_key_hash": usage_hash,
            "record_kind": "COLD_START_INITIALIZATION",
            "darwin_weight": 1.0,
            "previous_weight_record_id": None,
            "n_eligible_scores": 0,
            "scoring_window_hash": canonical_hash([]),
            "update_event_id": None,
            "effective_at": effective_at,
        }
        weight_record = {
            **weight_without_hash,
            "weight_record_hash": canonical_hash(weight_without_hash),
        }
        inserted_weights += int(
            _insert_record_or_verify(
                conn,
                table="darwinian_v2_usage_weight_records",
                key_column="weight_record_id",
                key=weight_id,
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
                    weight_id,
                    weight_record["weight_record_hash"],
                    usage_hash,
                    "COLD_START_INITIALIZATION",
                    1.0,
                    None,
                    0,
                    weight_without_hash["scoring_window_hash"],
                    None,
                    effective_at,
                    canonical_json(weight_record),
                ),
                json_column="record_json",
                record_json=canonical_json(weight_record),
            )
        )

    revision_json = canonical_json(revision)
    inserted_revision = _insert_record_or_verify(
        conn,
        table="darwinian_v2_production_variant_roster_revisions",
        key_column="production_variant_roster_revision_id",
        key=revision_id,
        columns=(
            "production_variant_roster_revision_id",
            "production_variant_roster_revision_hash",
            "production_variant_roster_id",
            "execution_behavior_release_id",
            "cohort_id",
            "language",
            "evaluation_track_key_hashes_json",
            "usage_track_key_hashes_json",
            "decision_evaluation_track_key_hashes_json",
            "readiness",
            "prepared_at",
            "recorded_at",
            "effective_at",
            "effective_slot_sequence",
            "record_json",
        ),
        values=(
            revision_id,
            revision_hash,
            roster_id,
            release_id,
            cohort_id,
            language,
            canonical_json(evaluation_hashes),
            canonical_json(usage_hashes),
            canonical_json(decision_hashes),
            "READY",
            prepared_at,
            recorded_at,
            effective_at,
            effective_slot_sequence,
            revision_json,
        ),
        json_column="record_json",
        record_json=revision_json,
    )
    return {
        **revision,
        "inserted_evaluation_tracks": inserted_tracks,
        "inserted_usage_tracks": inserted_usage_tracks,
        "inserted_cold_start_weights": inserted_weights,
        "inserted_roster_revision": inserted_revision,
    }


def get_production_weight_snapshot(
    conn: sqlite3.Connection,
    *,
    production_variant_roster_revision_id: str,
    as_of: str,
) -> dict[str, Any]:
    revision_row = conn.execute(
        """
        SELECT record_json
        FROM darwinian_v2_production_variant_roster_revisions
        WHERE production_variant_roster_revision_id = ?
          AND readiness = 'READY' AND effective_at <= ?
        """,
        (production_variant_roster_revision_id, as_of),
    ).fetchone()
    if revision_row is None:
        raise ValueError("READY Darwinian roster revision is unavailable as of cutoff")
    revision = json.loads(revision_row[0])
    weights: list[dict[str, Any]] = []
    for usage_hash in revision["usage_track_key_hashes"]:
        row = conn.execute(
            """
            SELECT u.agent_id, w.record_json
            FROM darwinian_v2_usage_tracks u
            JOIN darwinian_v2_usage_weight_records w
              ON w.usage_track_key_hash = u.usage_track_key_hash
            WHERE u.usage_track_key_hash = ? AND w.effective_at <= ?
              AND (
                w.update_event_id IS NULL OR EXISTS (
                  SELECT 1
                  FROM darwinian_v2_usage_weight_batch_revisions b
                  JOIN darwinian_v2_usage_weight_batch_publications p
                    ON p.update_event_id = b.update_event_id
                   AND p.published_batch_revision_id = b.batch_revision_id
                   AND p.published_batch_revision_hash = b.batch_revision_hash
                  WHERE b.update_event_id = w.update_event_id
                    AND b.status = 'PUBLISHED'
                    AND julianday(p.published_at) <= julianday(?)
                )
              )
            ORDER BY w.effective_at DESC, w.rowid DESC
            LIMIT 1
            """,
            (usage_hash, as_of, as_of),
        ).fetchone()
        if row is None:
            raise ValueError(f"missing published Darwinian weight for {usage_hash}")
        record = json.loads(row[1])
        weight = record.get("darwin_weight")
        if (
            not isinstance(weight, (int, float))
            or isinstance(weight, bool)
            or not math.isfinite(weight)
            or not 0.3 <= float(weight) <= 2.5
        ):
            raise ValueError(f"invalid Darwinian weight for {usage_hash}")
        evaluation_track = conn.execute(
            """
            SELECT evaluation_track_key_hash
            FROM darwinian_v2_usage_tracks
            WHERE usage_track_key_hash = ?
            """,
            (usage_hash,),
        ).fetchone()
        if evaluation_track is None:
            raise ValueError(f"missing evaluation track for {usage_hash}")
        reliability = _operational_reliability_record(
            conn,
            track_key_hash=evaluation_track[0],
            cutoff_at=as_of,
        )
        weights.append(
            {
                "agent_id": row[0],
                "usage_track_key_hash": usage_hash,
                **reliability,
                **record,
            }
        )
    if len(weights) != 24 or len({row["agent_id"] for row in weights}) != 24:
        raise ValueError("Darwinian weight snapshot must contain exactly 24 upstream Agents")
    weights.sort(key=lambda row: row["agent_id"])
    snapshot_without_hash = {
        "schema_version": "darwinian_usage_weight_snapshot_v2",
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": production_variant_roster_revision_id,
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": revision["cohort_id"],
        "language": revision["language"],
        "as_of": as_of,
        "weights": weights,
    }
    snapshot_id = deterministic_id("darwinian-snapshot", snapshot_without_hash)
    with_id = {"darwinian_snapshot_id": snapshot_id, **snapshot_without_hash}
    return {**with_id, "darwinian_snapshot_hash": canonical_hash(with_id)}


def _authoritative_macro_input_gate(
    accepted_records: list[Mapping[str, Any]],
    *,
    weight_snapshot: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, set[str]]]:
    """Rebuild the production Macro gate from server-validated inputs."""
    macro_records: dict[str, Mapping[str, Any]] = {}
    claim_ids_by_agent: dict[str, set[str]] = {}
    for record in accepted_records:
        if record.get("accepted_output_kind") != "MACRO_TRANSMISSION":
            continue
        agent_id = str(record.get("agent_id") or "")
        if agent_id not in _MACRO_AGENT_IDS or agent_id in macro_records:
            raise ValueError("accepted cycle has invalid duplicate Macro output ownership")
        payload = record["output"]["payload"]
        claims = payload["claims"]
        macro_records[agent_id] = record
        claim_ids_by_agent[agent_id] = {str(claim["claim_id"]) for claim in claims}
    if tuple(agent_id for agent_id in _MACRO_AGENT_IDS if agent_id in macro_records) != (
        _MACRO_AGENT_IDS
    ) or len(macro_records) != len(_MACRO_AGENT_IDS):
        raise ValueError("accepted cycle requires the exact accepted Macro roster")

    weights = weight_snapshot.get("weights")
    if not isinstance(weights, list):
        raise ValueError("authoritative Darwinian snapshot lacks weights")
    weight_by_agent = {
        str(row.get("agent_id") or ""): row
        for row in weights
        if isinstance(row, Mapping)
    }
    if len(weights) != 24 or len(weight_by_agent) != 24:
        raise ValueError("authoritative Darwinian snapshot must contain 24 Agents")

    reliability_by_agent: dict[str, dict[str, Any]] = {}
    for agent_id in _MACRO_AGENT_IDS:
        row = weight_by_agent.get(agent_id)
        if row is None:
            raise ValueError(f"authoritative Darwinian weight is missing for {agent_id}")
        payload = macro_records[agent_id]["output"]["payload"]
        confidence = float(payload["confidence"])
        darwin_weight = float(row["darwin_weight"])
        operational_reliability = float(row["operational_reliability_if_accepted"])
        effective_reliability = confidence * darwin_weight * operational_reliability
        if not math.isfinite(effective_reliability) or effective_reliability < 0:
            raise ValueError(f"invalid effective Macro reliability for {agent_id}")
        reliability_by_agent[agent_id] = {
            "effective_reliability": effective_reliability,
            "usage_share": 0.0,
            "weight_record_id": row["weight_record_id"],
            "reliability_record_id": row["reliability_record_id"],
        }
    denominator = sum(
        row["effective_reliability"] for row in reliability_by_agent.values()
    )
    if not math.isfinite(denominator) or denominator <= 0:
        raise ValueError("authoritative Macro gate has zero effective reliability")
    for agent_id in _MACRO_AGENT_IDS:
        reliability_by_agent[agent_id]["usage_share"] = (
            reliability_by_agent[agent_id]["effective_reliability"] / denominator
        )

    accepted_refs = [
        {
            "accepted_output_kind": "MACRO_TRANSMISSION",
            "agent_id": agent_id,
            "accepted_output_id": macro_records[agent_id]["accepted_output_id"],
            "accepted_output_hash": macro_records[agent_id]["accepted_output_hash"],
        }
        for agent_id in _MACRO_AGENT_IDS
    ]
    source_layer_body = {
        "accepted_outputs": accepted_refs,
        "usage_shares": {
            agent_id: reliability_by_agent[agent_id]["usage_share"]
            for agent_id in _MACRO_AGENT_IDS
        },
        "darwinian_snapshot_id": weight_snapshot["darwinian_snapshot_id"],
        "darwinian_snapshot_hash": weight_snapshot["darwinian_snapshot_hash"],
    }
    source_layer_hash = canonical_hash(source_layer_body)
    return (
        {
            "schema_version": "macro_input_gate_receipt_v1",
            "accepted_agent_ids": list(_MACRO_AGENT_IDS),
            "accepted_count": len(_MACRO_AGENT_IDS),
            "input_hash": source_layer_hash,
            "source_layer_snapshot_id": (
                f"macro-source-layer:{source_layer_hash.removeprefix('sha256:')}"
            ),
            "source_layer_snapshot_hash": source_layer_hash,
            "darwinian_snapshot_id": weight_snapshot["darwinian_snapshot_id"],
            "darwinian_snapshot_hash": weight_snapshot["darwinian_snapshot_hash"],
            "reliability_by_agent": reliability_by_agent,
        },
        claim_ids_by_agent,
    )


def _validate_macro_attribution_authority(
    accepted_records: list[Mapping[str, Any]],
    *,
    macro_gate: Mapping[str, Any],
    claim_ids_by_agent: Mapping[str, set[str]],
) -> None:
    reliability = macro_gate["reliability_by_agent"]
    for record in accepted_records:
        payload = record["output"]["payload"]
        accepted_kind = record["accepted_output_kind"]
        requires_attributions = (
            accepted_kind in _MACRO_ATTRIBUTION_REQUIRED_ACCEPTED_KINDS
        )
        has_attributions = "accepted_macro_input_attributions" in payload
        if has_attributions != requires_attributions:
            requirement = "requires" if requires_attributions else "forbids"
            raise ValueError(
                f"{accepted_kind} {requirement} accepted Macro input attributions"
            )
        if not requires_attributions:
            continue
        rows = payload["accepted_macro_input_attributions"]
        for row in rows:
            agent_id = row["agent_id"]
            expected_share = reliability[agent_id]["usage_share"]
            if not math.isclose(
                float(row["usage_share"]),
                float(expected_share),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    f"{agent_id} attribution usage_share does not match "
                    "the authoritative Macro gate"
                )
            unknown_claims = set(row["claim_refs_used"]) - claim_ids_by_agent[agent_id]
            if unknown_claims:
                raise ValueError(
                    f"{agent_id} attribution uses unowned accepted Macro claims: "
                    f"{sorted(unknown_claims)}"
                )


def prepare_production_variant(
    conn: sqlite3.Connection,
    *,
    binding: Mapping[str, Any],
    as_of: str,
) -> dict[str, Any]:
    without_hash = {key: value for key, value in binding.items() if key != "binding_hash"}
    if binding.get("schema_version") != "darwinian_runtime_binding_v2":
        raise ValueError("unsupported darwinian_runtime_binding schema")
    if binding.get("binding_hash") != canonical_hash(without_hash):
        raise ValueError("darwinian_runtime_binding hash mismatch")
    from mosaic.scorecard.component_calibration import resolve_component_weights

    resolved_components = [
        resolve_component_weights(conn, agent_id=agent_id, at=as_of)
        for agent_id, contract in sorted(OUTCOME_CONTRACTS.items())
        if contract.get("component_composition_contract") is not None
    ]
    runtime_without_hash = json.loads(canonical_json(without_hash))
    behavior_bindings = runtime_without_hash.get("agent_behavior_bindings")
    if not isinstance(behavior_bindings, dict):
        raise ValueError("darwinian_runtime_binding lacks behavior bindings")
    active_release_times: list[datetime] = []
    for resolution in resolved_components:
        agent_id = resolution["agent_id"]
        behavior = behavior_bindings.get(agent_id)
        if not isinstance(behavior, dict):
            raise ValueError(f"runtime binding lacks component Agent {agent_id}")
        behavior["component_weight_contract_version"] = resolution[
            "component_weight_contract_version"
        ]
        if resolution["effective_at"] is not None:
            active_release_times.append(
                datetime.fromisoformat(
                    str(resolution["effective_at"]).replace("Z", "+00:00")
                )
            )
    component_snapshot_without_hash = {
        "schema_version": "component_weight_runtime_snapshot_v2",
        "as_of": as_of,
        "resolutions": resolved_components,
    }
    component_snapshot_id = deterministic_id(
        "component-weight-runtime-snapshot", component_snapshot_without_hash
    )
    component_snapshot_with_id = {
        "component_weight_snapshot_id": component_snapshot_id,
        **component_snapshot_without_hash,
    }
    component_snapshot = {
        **component_snapshot_with_id,
        "component_weight_snapshot_hash": canonical_hash(component_snapshot_with_id),
    }
    if active_release_times:
        base_effective = datetime.fromisoformat(
            str(runtime_without_hash.get("effective_at") or "").replace("Z", "+00:00")
        )
        runtime_without_hash["effective_at"] = max(
            [base_effective, *active_release_times]
        ).isoformat()
        runtime_without_hash["execution_behavior_release_id"] = deterministic_id(
            "component-weight-aware-execution-release",
            {
                "base_execution_behavior_release_id": without_hash[
                    "execution_behavior_release_id"
                ],
                "component_activation_hash": canonical_hash(resolved_components),
            },
        )
    runtime_binding = {
        **runtime_without_hash,
        "binding_hash": canonical_hash(runtime_without_hash),
    }
    registration = register_production_variant(
        conn,
        cohort_id=str(runtime_binding.get("cohort_id") or ""),
        language=str(runtime_binding.get("language") or ""),
        execution_behavior_release_id=str(
            runtime_binding.get("execution_behavior_release_id") or ""
        ),
        behavior_bindings=runtime_binding.get("agent_behavior_bindings") or {},
        effective_at=str(runtime_binding.get("effective_at") or ""),
    )
    if runtime_binding.get("production_variant_roster_id") != registration[
        "production_variant_roster_id"
    ]:
        raise ValueError("runtime binding production_variant_roster_id mismatch")
    snapshot = get_production_weight_snapshot(
        conn,
        production_variant_roster_revision_id=registration[
            "production_variant_roster_revision_id"
        ],
        as_of=as_of,
    )
    return {
        "runtime_binding": runtime_binding,
        "roster_revision": registration,
        "weight_snapshot": snapshot,
        "component_weight_snapshot": component_snapshot,
    }


def _operational_reliability_record(
    conn: sqlite3.Connection,
    *,
    track_key_hash: str,
    cutoff_at: str,
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT operational_opportunity_audit_id, disposition
        FROM operational_opportunity_audits_v2
        WHERE track_key_hash = ?
          AND sample_origin = 'PRODUCTION_ACTIVE'
          AND production_reliability_eligible = 1
          AND accountable = 1
          AND recorded_at < ?
        ORDER BY recorded_at DESC, rowid DESC
        LIMIT 30
        """,
        (track_key_hash, cutoff_at),
    ).fetchall()
    opportunity_ids = [row[0] for row in rows]
    accountable_count = len(rows)
    accepted_count = sum(row[1] == "ACCEPTED" for row in rows)
    reliability = (
        accepted_count / accountable_count if accountable_count > 0 else 1.0
    )
    if_accepted = (accepted_count + 1) / (accountable_count + 1)
    state = "OBSERVED" if accountable_count > 0 else "COLD_START"
    opportunity_set_hash = canonical_hash(opportunity_ids)
    record_id = deterministic_id(
        "operational-reliability",
        {
            "track_key_hash": track_key_hash,
            "cutoff_at": cutoff_at,
            "opportunity_set_hash": opportunity_set_hash,
        },
    )
    without_hash = {
        "reliability_record_id": record_id,
        "track_key_hash": track_key_hash,
        "cutoff_at": cutoff_at,
        "window_size": accountable_count,
        "accepted_count": accepted_count,
        "accountable_count": accountable_count,
        "operational_reliability": reliability,
        "operational_reliability_if_accepted": if_accepted,
        "reliability_state": state,
        "opportunity_set_hash": opportunity_set_hash,
        "recorded_at": cutoff_at,
    }
    record = {
        **without_hash,
        "reliability_record_hash": canonical_hash(without_hash),
    }
    record_json = canonical_json(record)
    _insert_record_or_verify(
        conn,
        table="darwinian_v2_operational_reliability_records",
        key_column="reliability_record_id",
        key=record_id,
        columns=(
            "reliability_record_id",
            "reliability_record_hash",
            "track_key_hash",
            "cutoff_at",
            "window_size",
            "accepted_count",
            "accountable_count",
            "operational_reliability",
            "reliability_state",
            "opportunity_set_hash",
            "recorded_at",
            "record_json",
        ),
        values=(
            record_id,
            record["reliability_record_hash"],
            track_key_hash,
            cutoff_at,
            accountable_count,
            accepted_count,
            accountable_count,
            reliability,
            state,
            opportunity_set_hash,
            cutoff_at,
            record_json,
        ),
        json_column="record_json",
        record_json=record_json,
    )
    return record


def append_accepted_cycle(
    conn: sqlite3.Connection,
    *,
    state: Mapping[str, Any],
) -> dict[str, Any]:
    binding = state.get("darwinian_runtime_binding")
    if not isinstance(binding, Mapping):
        raise ValueError("accepted v2 cycle requires darwinian_runtime_binding")
    binding_without_hash = {
        key: value for key, value in binding.items() if key != "binding_hash"
    }
    if binding.get("schema_version") != "darwinian_runtime_binding_v2":
        raise ValueError("unsupported darwinian_runtime_binding schema")
    if binding.get("binding_hash") != canonical_hash(binding_without_hash):
        raise ValueError("darwinian_runtime_binding hash mismatch")
    registration = register_production_variant(
        conn,
        cohort_id=str(binding.get("cohort_id") or ""),
        language=str(binding.get("language") or ""),
        execution_behavior_release_id=str(
            binding.get("execution_behavior_release_id") or ""
        ),
        behavior_bindings=binding.get("agent_behavior_bindings") or {},
        effective_at=str(binding.get("effective_at") or ""),
    )
    if (
        binding.get("production_variant_roster_id")
        != registration["production_variant_roster_id"]
    ):
        raise ValueError("runtime binding production_variant_roster_id mismatch")
    if state.get("active_cohort") != binding.get("cohort_id"):
        raise ValueError("state/binding cohort mismatch")

    graph_run_id = _required_text(state.get("trace_id"), "state.trace_id")
    as_of = _required_text(state.get("as_of_date"), "state.as_of_date")
    schedule_ref = state.get("outcome_schedule_plan")
    if not isinstance(schedule_ref, Mapping):
        raise ValueError("accepted v2 cycle requires outcome_schedule_plan")
    schedule_plan_id = _required_text(
        schedule_ref.get("outcome_schedule_plan_id"),
        "outcome_schedule_plan.outcome_schedule_plan_id",
    )
    schedule_plan_hash = _required_text(
        schedule_ref.get("outcome_schedule_plan_hash"),
        "outcome_schedule_plan.outcome_schedule_plan_hash",
    )
    plan_row = conn.execute(
        "SELECT record_json FROM outcome_schedule_plans_v2 "
        "WHERE outcome_schedule_plan_id = ?",
        (schedule_plan_id,),
    ).fetchone()
    if plan_row is None:
        raise ValueError("outcome schedule plan is unavailable")
    schedule_plan = json.loads(plan_row[0])
    if schedule_plan.get("outcome_schedule_plan_hash") != schedule_plan_hash:
        raise ValueError("outcome schedule plan hash mismatch")
    for field, expected in (
        ("graph_run_id", graph_run_id),
        (
            "production_variant_roster_id",
            registration["production_variant_roster_id"],
        ),
        (
            "production_variant_roster_revision_id",
            registration["production_variant_roster_revision_id"],
        ),
        ("execution_behavior_release_id", registration["execution_behavior_release_id"]),
        ("cohort_id", binding["cohort_id"]),
        ("language", binding["language"]),
    ):
        if schedule_plan.get(field) != expected:
            raise ValueError(f"outcome schedule plan {field} mismatch")
    if str(schedule_plan.get("as_of", ""))[:10] != as_of[:10]:
        raise ValueError("outcome schedule plan as_of mismatch")
    authoritative_weight_snapshot = get_production_weight_snapshot(
        conn,
        production_variant_roster_revision_id=registration[
            "production_variant_roster_revision_id"
        ],
        as_of=schedule_plan["as_of"],
    )
    supplied_weight_snapshot = state.get("darwinian_weight_snapshot")
    if not isinstance(supplied_weight_snapshot, Mapping):
        raise ValueError("accepted v2 cycle requires darwinian_weight_snapshot")
    if canonical_json(supplied_weight_snapshot) != canonical_json(
        authoritative_weight_snapshot
    ):
        raise ValueError(
            "state Darwinian weight snapshot does not match server authority"
        )
    slot_rows = conn.execute(
        "SELECT agent_id, record_json FROM outcome_schedule_slots_v2 "
        "WHERE outcome_schedule_plan_id = ?",
        (schedule_plan_id,),
    ).fetchall()
    schedule_by_agent = {row[0]: json.loads(row[1]) for row in slot_rows}
    if set(schedule_by_agent) != set(OUTCOME_CONTRACTS):
        raise ValueError("outcome schedule plan must contain the exact 28-Agent roster")
    stage_skips = _accepted_stage_skips(
        conn,
        state=state,
        graph_run_id=graph_run_id,
        outcome_schedule_plan_id=schedule_plan_id,
        schedule_by_agent=schedule_by_agent,
    )
    skip_stage_keys = {(_audit_stage(agent_id), agent_id) for agent_id in stage_skips}
    audits = state.get("agent_run_audits")
    if not isinstance(audits, list):
        raise ValueError("accepted v2 cycle requires an Agent stage audit array")
    audit_by_agent: dict[str, list[Mapping[str, Any]]] = {}
    audit_stage_keys: set[tuple[str, str]] = set()
    for audit in audits:
        if not isinstance(audit, Mapping):
            raise ValueError("Agent run audit must be an object")
        if audit.get("status") not in {"accepted", "accepted_empty"}:
            raise ValueError("accepted v2 cycle cannot persist failed Agent output")
        agent_id = _required_text(audit.get("agent"), "audit.agent")
        stage = _required_text(audit.get("stage"), "audit.stage")
        key = (stage, agent_id)
        if key in audit_stage_keys:
            raise ValueError(f"duplicate Agent stage audit: {agent_id}:{stage}")
        if agent_id in stage_skips:
            raise ValueError(f"stage-skipped Agent cannot carry a run audit: {agent_id}")
        audit_stage_keys.add(key)
        audit_by_agent.setdefault(agent_id, []).append(audit)
    if audit_stage_keys | skip_stage_keys != _required_runtime_stage_keys():
        raise ValueError("accepted v2 cycle must resolve the exact 29 Agent stages")

    revision_hashes = set(registration["evaluation_track_key_hashes"])
    placeholders = ",".join("?" for _ in revision_hashes)
    track_rows = conn.execute(
        f"""
        SELECT agent_id, track_key_hash, contract_json
        FROM darwinian_v2_evaluation_tracks
        WHERE track_key_hash IN ({placeholders})
        """,
        tuple(sorted(revision_hashes)),
    ).fetchall()
    track_by_agent = {row[0]: (row[1], json.loads(row[2])) for row in track_rows}
    if set(track_by_agent) != set(OUTCOME_CONTRACTS):
        raise ValueError("roster revision does not resolve all 28 evaluation tracks")

    output_entries = _accepted_cycle_outputs(state, skipped_agents=set(stage_skips))
    if len(output_entries) + len(stage_skips) != 29:
        raise ValueError("accepted v2 cycle must resolve 29 accepted-or-skipped stages")
    accepted_records: list[dict[str, Any]] = []
    operational_ids: dict[str, str] = {}
    for agent_id, accepted_kind, stage, supplied_record in output_entries:
        track_hash, track_record = track_by_agent[agent_id]
        schedule_slot = schedule_by_agent[agent_id]
        if schedule_slot.get("track_key_hash") != track_hash:
            raise ValueError(f"outcome schedule track mismatch for {agent_id}")
        run_slot_kind = schedule_slot.get("run_slot_kind")
        scheduled_sample_id = schedule_slot.get("scheduled_sample_id")
        opportunity: dict[str, Any] | None = None
        if run_slot_kind == "OUTCOME_SCHEDULED":
            failure = conn.execute(
                "SELECT 1 FROM evaluation_opportunity_set_generation_failures_v2 "
                "WHERE outcome_schedule_slot_id = ?",
                (schedule_slot["outcome_schedule_slot_id"],),
            ).fetchone()
            if failure is not None:
                raise ValueError(
                    f"scheduled Agent cannot run after opportunity failure: {agent_id}"
                )
            opportunity_row = conn.execute(
                "SELECT record_json FROM evaluation_opportunity_sets_v2 "
                "WHERE scheduled_sample_id = ? AND opportunity_set_status = 'AVAILABLE'",
                (scheduled_sample_id,),
            ).fetchone()
            if opportunity_row is None:
                raise ValueError(
                    f"scheduled Agent requires a frozen opportunity set: {agent_id}"
                )
            opportunity = json.loads(opportunity_row[0])
            for field, expected in (
                ("agent_id", agent_id),
                ("track_key_hash", track_hash),
                ("scheduled_sample_id", scheduled_sample_id),
                ("sample_origin", "PRODUCTION_ACTIVE"),
                (
                    "production_variant_roster_revision_id",
                    registration["production_variant_roster_revision_id"],
                ),
            ):
                if opportunity.get(field) != expected:
                    raise ValueError(f"opportunity set {field} mismatch for {agent_id}")
            if opportunity.get("member_state") == "EMPTY":
                raise ValueError(
                    f"scheduled empty opportunity requires a pre-run stage skip: {agent_id}"
                )
            if opportunity.get("generator_input_snapshot_hash") is None:
                raise ValueError(
                    f"scheduled Agent opportunity lacks generator input binding: {agent_id}"
                )
        elif run_slot_kind == "DOWNSTREAM_ONLY":
            if scheduled_sample_id is not None:
                raise ValueError(f"DOWNSTREAM_ONLY slot has a sample ID: {agent_id}")
        else:
            raise ValueError(f"invalid outcome schedule slot kind for {agent_id}")
        behavior = binding["agent_behavior_bindings"][agent_id]
        if any(track_record.get(key) != behavior.get(key) for key in _VERSION_FIELDS):
            raise ValueError(f"accepted track behavior mismatch for {agent_id}")
        run_audits = audit_by_agent.get(agent_id, [])
        matching_audits = [audit for audit in run_audits if audit.get("stage") == stage]
        if len(matching_audits) != 1:
            raise ValueError(f"missing unique accepted audit for {agent_id}:{stage}")
        matching_audit = matching_audits[0]
        run_id = _required_text(matching_audit.get("run_id"), f"{agent_id}.run_id")
        run_slot_id = schedule_slot["run_slot_id"]
        operational_id = operational_ids.setdefault(
            agent_id,
            deterministic_id(
                "operational-opportunity",
                {"graph_run_id": graph_run_id, "agent_id": agent_id, "run_slot_id": run_slot_id},
            ),
        )
        accepted_id = deterministic_id(
            "accepted-output",
            {
                "graph_run_id": graph_run_id,
                "run_slot_id": run_slot_id,
                "accepted_output_kind": accepted_kind,
            },
        )
        expected_fields = {
            "accepted_output_id": accepted_id,
            "graph_run_id": graph_run_id,
            "run_id": run_id,
            "run_slot_id": run_slot_id,
            "operational_opportunity_audit_id": operational_id,
            "production_variant_roster_id": registration[
                "production_variant_roster_id"
            ],
            "production_variant_roster_revision_id": registration[
                "production_variant_roster_revision_id"
            ],
            "execution_behavior_release_id": registration[
                "execution_behavior_release_id"
            ],
            "cohort_id": binding["cohort_id"],
            "language": binding["language"],
            "track_key_hash": track_hash,
            "agent_id": agent_id,
            "accepted_output_kind": accepted_kind,
            "sample_origin": "PRODUCTION_ACTIVE",
            "run_slot_kind": run_slot_kind,
            "scheduled_sample_id": scheduled_sample_id,
            **behavior,
            "as_of": schedule_plan["as_of"],
            "accepted_at": binding["effective_at"],
            "evaluation_opportunity_set_id": (
                opportunity.get("evaluation_opportunity_set_id")
                if opportunity is not None
                and accepted_kind == track_record["outcome_contract"]["accepted_output_kind"]
                else None
            ),
            "evaluation_opportunity_set_hash": (
                opportunity.get("evaluation_opportunity_set_hash")
                if opportunity is not None
                and accepted_kind == track_record["outcome_contract"]["accepted_output_kind"]
                else None
            ),
            "frozen_object_set_id": (
                opportunity.get("frozen_object_set_id")
                if opportunity is not None
                and accepted_kind == track_record["outcome_contract"]["accepted_output_kind"]
                else None
            ),
            "frozen_object_set_hash": (
                opportunity.get("frozen_object_set_hash")
                if opportunity is not None
                and accepted_kind == track_record["outcome_contract"]["accepted_output_kind"]
                else None
            ),
        }
        for field, expected in expected_fields.items():
            if supplied_record.get(field) != expected:
                raise ValueError(
                    f"accepted output {field} mismatch for {agent_id}:{accepted_kind}"
                )
        requires_runtime_audit = (
            accepted_kind == "MACRO_TRANSMISSION"
            and isinstance(
                OUTCOME_CONTRACTS[agent_id].get("component_composition_contract"),
                Mapping,
            )
        )
        allow_runtime_authority = (
            opportunity is not None
            and accepted_kind
            == track_record["outcome_contract"]["accepted_output_kind"]
            and isinstance(opportunity.get("runtime_authority_binding"), Mapping)
        )
        validate_accepted_output_record_schema(
            supplied_record,
            agent_id=agent_id,
            accepted_kind=accepted_kind,
            allow_runtime_authority=allow_runtime_authority,
            require_runtime_audit=requires_runtime_audit,
        )
        source_output_hash = supplied_record["adapter_lineage"][
            "source_agent_output_hash"
        ]
        if matching_audit.get("output_hash") != source_output_hash:
            raise ValueError(
                f"accepted output/audit adapter lineage mismatch for "
                f"{agent_id}:{accepted_kind}"
            )
        payload = supplied_record["output"]["payload"]
        for field in _VERSION_FIELDS:
            if payload.get(field) != supplied_record.get(field):
                raise ValueError(
                    f"accepted payload {field} mismatch for {agent_id}:{accepted_kind}"
                )
        if (
            accepted_kind == "MACRO_TRANSMISSION"
            and payload.get("component_weight_contract_version")
            != supplied_record.get("component_weight_contract_version")
        ):
            raise ValueError(
                f"accepted payload component contract mismatch for {agent_id}"
            )
        _validate_evidence_lineage_envelope(
            supplied_record.get("output"),
            agent_id=agent_id,
            accepted_kind=accepted_kind,
        )
        if opportunity is not None and isinstance(
            opportunity.get("runtime_authority_binding"), Mapping
        ) and (
            accepted_kind == track_record["outcome_contract"]["accepted_output_kind"]
        ):
            authority = opportunity.get("runtime_authority_binding")
            if supplied_record.get("runtime_opportunity_authority") != authority:
                raise ValueError(
                    f"accepted output runtime authority mismatch for {agent_id}"
                )
        if opportunity is not None and agent_id in {
            "alpha_discovery",
            "cro",
            "autonomous_execution",
            "cio",
        } and (
            accepted_kind == track_record["outcome_contract"]["accepted_output_kind"]
        ):
            if not isinstance(
                opportunity.get("runtime_authority_binding"), Mapping
            ):
                raise ValueError(
                    f"Decision opportunity lacks runtime authority: {agent_id}"
                )
            frozen_id = opportunity.get("frozen_object_set_id")
            frozen_hash = opportunity.get("frozen_object_set_hash")
            if not isinstance(frozen_id, str) or not isinstance(frozen_hash, str):
                raise ValueError(
                    f"Decision opportunity lacks a frozen stage object: {agent_id}"
                )
            payload_fields = {
                "alpha_discovery": (
                    "frozen_novel_candidate_universe_id",
                    "frozen_novel_candidate_universe_hash",
                ),
                "cro": (
                    "frozen_candidate_universe_id",
                    "frozen_candidate_universe_hash",
                ),
                "autonomous_execution": (
                    "frozen_order_intent_set_id",
                    "frozen_order_intent_set_hash",
                ),
                "cio": (
                    "frozen_controlled_target_set_id",
                    "frozen_controlled_target_set_hash",
                ),
            }[agent_id]
            if (
                payload.get(payload_fields[0]) != frozen_id
                or payload.get(payload_fields[1]) != frozen_hash
            ):
                raise ValueError(
                    f"Decision accepted output frozen object mismatch for {agent_id}"
                )
        without_hash = {
            key: value
            for key, value in supplied_record.items()
            if key != "accepted_output_hash"
        }
        expected_hash = canonical_hash(without_hash)
        if supplied_record.get("accepted_output_hash") != expected_hash:
            raise ValueError(
                f"accepted output hash mismatch for {agent_id}:{accepted_kind}"
            )
        record = dict(supplied_record)
        if accepted_kind == "MACRO_TRANSMISSION":
            composition_contract = OUTCOME_CONTRACTS[agent_id].get(
                "component_composition_contract"
            )
            if isinstance(composition_contract, Mapping):
                from mosaic.scorecard.component_calibration import (
                    validate_accepted_macro_component_composition,
                )

                validate_accepted_macro_component_composition(conn, accepted=record)
            elif record.get("runtime_audit") is not None:
                raise ValueError(
                    f"direct Macro accepted output has unexpected runtime audit: {agent_id}"
                )
        accepted_records.append(record)

    authoritative_macro_gate, macro_claim_ids = _authoritative_macro_input_gate(
        accepted_records,
        weight_snapshot=authoritative_weight_snapshot,
    )
    supplied_macro_gate = state.get("macro_input_gate")
    if not isinstance(supplied_macro_gate, Mapping):
        raise ValueError("accepted v2 cycle requires macro_input_gate")
    if canonical_json(supplied_macro_gate) != canonical_json(
        authoritative_macro_gate
    ):
        raise ValueError("state Macro input gate does not match server authority")
    _validate_macro_attribution_authority(
        accepted_records,
        macro_gate=authoritative_macro_gate,
        claim_ids_by_agent=macro_claim_ids,
    )

    _validate_decision_control_source_closure(
        accepted_records,
        stage_skips=stage_skips,
    )

    inserted_accepted = 0
    for record in accepted_records:
        record_json = canonical_json(record)
        inserted_accepted += int(
            _insert_record_or_verify(
                conn,
                table="accepted_agent_outputs_v2",
                key_column="accepted_output_id",
                key=record["accepted_output_id"],
                columns=(
                    "accepted_output_id",
                    "accepted_output_hash",
                    "graph_run_id",
                    "run_id",
                    "run_slot_id",
                    "operational_opportunity_audit_id",
                    "production_variant_roster_id",
                    "production_variant_roster_revision_id",
                    "execution_behavior_release_id",
                    "cohort_id",
                    "language",
                    "track_key_hash",
                    "agent_id",
                    "accepted_output_kind",
                    "sample_origin",
                    "run_slot_kind",
                    "scheduled_sample_id",
                    "as_of",
                    "accepted_at",
                    "record_json",
                ),
                values=(
                    record["accepted_output_id"],
                    record["accepted_output_hash"],
                    record["graph_run_id"],
                    record["run_id"],
                    record["run_slot_id"],
                    record["operational_opportunity_audit_id"],
                    record["production_variant_roster_id"],
                    record["production_variant_roster_revision_id"],
                    record["execution_behavior_release_id"],
                    record["cohort_id"],
                    record["language"],
                    record["track_key_hash"],
                    record["agent_id"],
                    record["accepted_output_kind"],
                    record["sample_origin"],
                    record["run_slot_kind"],
                    record["scheduled_sample_id"],
                    record["as_of"],
                    record["accepted_at"],
                    record_json,
                ),
                json_column="record_json",
                record_json=record_json,
            )
        )

    records_by_agent: dict[str, list[dict[str, Any]]] = {}
    for record in accepted_records:
        records_by_agent.setdefault(record["agent_id"], []).append(record)
    inserted_operational = 0
    for agent_id in sorted(records_by_agent):
        agent_records = records_by_agent[agent_id]
        accepted_record = (
            next(
                record
                for record in agent_records
                if record["accepted_output_kind"] == "CIO_FINAL"
            )
            if agent_id == "cio"
            else agent_records[0]
        )
        track_hash, _ = track_by_agent[agent_id]
        behavior = binding["agent_behavior_bindings"][agent_id]
        without_hash = {
            "operational_opportunity_audit_id": operational_ids[agent_id],
            "graph_run_id": graph_run_id,
            "run_slot_id": accepted_record["run_slot_id"],
            "production_variant_roster_id": registration[
                "production_variant_roster_id"
            ],
            "production_variant_roster_revision_id": registration[
                "production_variant_roster_revision_id"
            ],
            "execution_behavior_release_id": registration[
                "execution_behavior_release_id"
            ],
            "cohort_id": binding["cohort_id"],
            "language": binding["language"],
            "agent_id": agent_id,
            "track_key_hash": track_hash,
            **behavior,
            "sample_origin": "PRODUCTION_ACTIVE",
            "run_slot_kind": accepted_record["run_slot_kind"],
            "scheduled_sample_id": accepted_record["scheduled_sample_id"],
            "production_reliability_eligible": True,
            "disposition": "ACCEPTED",
            "accountable": True,
            "run_id": accepted_record["run_id"],
            "accepted_output_kind": accepted_record["accepted_output_kind"],
            "accepted_output_id": accepted_record["accepted_output_id"],
            "accepted_output_hash": accepted_record["accepted_output_hash"],
            "stage_skip_id": None,
            "stage_skip_hash": None,
            "failure_reason": None,
            "fallback_used": False,
            "as_of": as_of,
            "recorded_at": binding["effective_at"],
        }
        audit_record = {
            **without_hash,
            "operational_opportunity_audit_hash": canonical_hash(without_hash),
        }
        record_json = canonical_json(audit_record)
        inserted_operational += int(
            _insert_record_or_verify(
                conn,
                table="operational_opportunity_audits_v2",
                key_column="operational_opportunity_audit_id",
                key=audit_record["operational_opportunity_audit_id"],
                columns=(
                    "operational_opportunity_audit_id",
                    "operational_opportunity_audit_hash",
                    "graph_run_id",
                    "run_slot_id",
                    "production_variant_roster_id",
                    "production_variant_roster_revision_id",
                    "execution_behavior_release_id",
                    "cohort_id",
                    "language",
                    "agent_id",
                    "track_key_hash",
                    "sample_origin",
                    "run_slot_kind",
                    "scheduled_sample_id",
                    "production_reliability_eligible",
                    "disposition",
                    "accountable",
                    "run_id",
                    "accepted_output_id",
                    "failure_reason",
                    "fallback_used",
                    "as_of",
                    "recorded_at",
                    "record_json",
                ),
                values=(
                    audit_record["operational_opportunity_audit_id"],
                    audit_record["operational_opportunity_audit_hash"],
                    graph_run_id,
                    audit_record["run_slot_id"],
                    audit_record["production_variant_roster_id"],
                    audit_record["production_variant_roster_revision_id"],
                    audit_record["execution_behavior_release_id"],
                    audit_record["cohort_id"],
                    audit_record["language"],
                    agent_id,
                    track_hash,
                    "PRODUCTION_ACTIVE",
                    audit_record["run_slot_kind"],
                    audit_record["scheduled_sample_id"],
                    1,
                    "ACCEPTED",
                    1,
                    audit_record["run_id"],
                    audit_record["accepted_output_id"],
                    None,
                    0,
                    as_of,
                    audit_record["recorded_at"],
                    record_json,
                ),
                json_column="record_json",
                record_json=record_json,
            )
        )
    from mosaic.scorecard.darwinian_updates import append_outcome_eligibility_revision

    pending_revisions = 0
    for agent_id in sorted(records_by_agent):
        accepted_record = (
            next(
                record
                for record in records_by_agent[agent_id]
                if record["accepted_output_kind"] == "CIO_FINAL"
            )
            if agent_id == "cio"
            else records_by_agent[agent_id][0]
        )
        if accepted_record["run_slot_kind"] != "OUTCOME_SCHEDULED":
            continue
        opportunity_row = conn.execute(
            "SELECT evaluation_opportunity_set_id FROM evaluation_opportunity_sets_v2 "
            "WHERE scheduled_sample_id = ? AND opportunity_set_status = 'AVAILABLE'",
            (accepted_record["scheduled_sample_id"],),
        ).fetchone()
        if opportunity_row is None:
            raise ValueError("scheduled accepted output lost its opportunity set")
        previous_count = conn.execute(
            "SELECT COUNT(*) FROM agent_outcome_eligibility_revisions_v2 "
            "WHERE scheduled_sample_id = ? AND track_key_hash = ?",
            (accepted_record["scheduled_sample_id"], accepted_record["track_key_hash"]),
        ).fetchone()[0]
        append_outcome_eligibility_revision(
            conn,
            track_key_hash=accepted_record["track_key_hash"],
            scheduled_sample_id=accepted_record["scheduled_sample_id"],
            sample_origin="PRODUCTION_ACTIVE",
            disposition="PENDING",
            recorded_at=binding["effective_at"],
            evaluation_opportunity_set_id=opportunity_row[0],
            accepted_output_id=accepted_record["accepted_output_id"],
        )
        current_count = conn.execute(
            "SELECT COUNT(*) FROM agent_outcome_eligibility_revisions_v2 "
            "WHERE scheduled_sample_id = ? AND track_key_hash = ?",
            (accepted_record["scheduled_sample_id"], accepted_record["track_key_hash"]),
        ).fetchone()[0]
        pending_revisions += int(current_count > previous_count)
    component_inputs = state.get("component_calibration_inputs")
    component_agent_ids = {
        agent_id
        for agent_id, contract in OUTCOME_CONTRACTS.items()
        if contract.get("component_composition_contract") is not None
    }
    if not isinstance(component_inputs, Mapping) or set(component_inputs) != component_agent_ids:
        raise ValueError(
            "accepted v2 cycle requires runtime component inputs for seven Macro Agents"
        )
    from mosaic.scorecard.component_calibration import (
        append_component_calibration_signals,
    )

    inserted_component_signals = 0
    for agent_id in sorted(component_agent_ids):
        runtime_input = component_inputs[agent_id]
        if not isinstance(runtime_input, Mapping):
            raise ValueError(f"component calibration input for {agent_id} must be an object")
        accepted_record = records_by_agent[agent_id][0]
        if accepted_record["run_slot_kind"] != "OUTCOME_SCHEDULED":
            if runtime_input.get("agent_id") != agent_id:
                raise ValueError(f"component calibration runtime owner mismatch for {agent_id}")
            continue
        slot = schedule_by_agent[agent_id]
        outcome_due_at = slot.get("outcome_due_at")
        if not isinstance(outcome_due_at, str) or not outcome_due_at:
            raise ValueError(f"scheduled component Agent has no outcome_due_at: {agent_id}")
        result = append_component_calibration_signals(
            conn,
            accepted_output_id=accepted_record["accepted_output_id"],
            operational_opportunity_audit_id=operational_ids[agent_id],
            runtime_input=runtime_input,
            outcome_due_at=outcome_due_at,
        )
        inserted_component_signals += int(result["inserted"])
    return {
        "production_variant_roster_revision_id": registration[
            "production_variant_roster_revision_id"
        ],
        "accepted_output_records": inserted_accepted,
        "operational_opportunity_audits": inserted_operational,
        "outcome_eligibility_pending_revisions": pending_revisions,
        "component_calibration_signals": inserted_component_signals,
        "no_evaluation_object_stage_skips": len(stage_skips),
        "evaluation_tracks_inserted": registration["inserted_evaluation_tracks"],
        "usage_tracks_inserted": registration["inserted_usage_tracks"],
        "cold_start_weights_inserted": registration["inserted_cold_start_weights"],
    }


def _accepted_cycle_outputs(
    state: Mapping[str, Any],
    *,
    skipped_agents: set[str],
) -> list[tuple[str, str, str, Mapping[str, Any]]]:
    supplied = state.get("accepted_output_records")
    refs = state.get("accepted_output_refs")
    if not isinstance(supplied, list):
        raise ValueError("accepted v2 cycle requires accepted_output_records")
    if not isinstance(refs, Mapping):
        raise ValueError("accepted v2 cycle requires accepted_output_refs")

    rows: list[tuple[str, str, str, Mapping[str, Any]]] = []
    seen_record_ids: set[str] = set()
    seen_keys: set[str] = set()
    records_by_agent: dict[str, list[str]] = {}
    for record in supplied:
        if not isinstance(record, Mapping):
            raise ValueError("accepted output record must be an object")
        agent_id = _required_text(record.get("agent_id"), "accepted_output.agent_id")
        accepted_kind = _required_text(
            record.get("accepted_output_kind"),
            "accepted_output.accepted_output_kind",
        )
        record_id = _required_text(
            record.get("accepted_output_id"),
            "accepted_output.accepted_output_id",
        )
        if record_id in seen_record_ids:
            raise ValueError(f"duplicate accepted output record: {record_id}")
        seen_record_ids.add(record_id)
        if agent_id not in OUTCOME_CONTRACTS:
            raise ValueError(f"accepted output has unknown owner: {agent_id}")
        if agent_id in skipped_agents:
            raise ValueError(f"stage-skipped Agent has an accepted output: {agent_id}")
        expected_kind = str(OUTCOME_CONTRACTS[agent_id]["accepted_output_kind"])
        if agent_id == "cio":
            if accepted_kind not in {"CIO_PROPOSAL", "CIO_FINAL"}:
                raise ValueError(f"CIO accepted output kind is invalid: {accepted_kind}")
        elif accepted_kind != expected_kind:
            raise ValueError(f"accepted output kind mismatch for {agent_id}")
        stage = _accepted_output_stage(agent_id, accepted_kind)
        ref_key = f"{accepted_kind}:{agent_id}"
        ref = refs.get(ref_key)
        if not isinstance(ref, Mapping):
            raise ValueError(f"accepted output reference is missing: {ref_key}")
        for field, expected in (
            ("accepted_output_kind", accepted_kind),
            ("agent_id", agent_id),
            ("accepted_output_id", record_id),
            ("accepted_output_hash", record.get("accepted_output_hash")),
        ):
            if ref.get(field) != expected:
                raise ValueError(f"accepted output reference {field} mismatch: {ref_key}")
        seen_keys.add(ref_key)
        records_by_agent.setdefault(agent_id, []).append(accepted_kind)
        rows.append((agent_id, accepted_kind, stage, record))

    if set(refs) != seen_keys:
        raise ValueError("accepted_output_refs contains an unresolved or duplicate namespace")
    for agent_id in OUTCOME_CONTRACTS:
        kinds = sorted(records_by_agent.get(agent_id, []))
        if agent_id in skipped_agents:
            if kinds:
                raise ValueError(f"stage-skipped Agent has accepted records: {agent_id}")
            continue
        expected = ["CIO_FINAL", "CIO_PROPOSAL"] if agent_id == "cio" else [
            str(OUTCOME_CONTRACTS[agent_id]["accepted_output_kind"])
        ]
        if kinds != expected:
            raise ValueError(f"accepted output roster mismatch for {agent_id}")
    return sorted(rows, key=lambda row: (row[0], row[2], row[1]))


def _accepted_output_stage(agent_id: str, accepted_kind: str) -> str:
    if accepted_kind == "CIO_PROPOSAL":
        return "cio_proposal"
    if accepted_kind == "CIO_FINAL":
        return "cio_final"
    if accepted_kind == "CRO_RISK_REVIEW":
        return "cro_review"
    if accepted_kind == "ALPHA_DISCOVERY":
        return "alpha_discovery"
    if accepted_kind == "EXECUTION_ASSESSMENT":
        return "execution_feasibility"
    return _audit_stage(agent_id)


def _validate_evidence_lineage_envelope(
    value: Any,
    *,
    agent_id: str,
    accepted_kind: str,
) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"accepted output lineage envelope is missing for {agent_id}")
    payload = value.get("payload")
    bundles = value.get("evidence_bundle_ids")
    causal_keys = value.get("causal_dedupe_keys")
    if not isinstance(payload, Mapping):
        raise ValueError(f"accepted output payload must be an object for {agent_id}")
    owner_field = {
        "STANDARD_SECTOR_SELECTION": "sector_agent_id",
        "RELATIONSHIP_GRAPH": "relationship_agent_id",
        "SUPERINVESTOR_SELECTION": "superinvestor_agent_id",
    }.get(accepted_kind, "agent_id")
    if payload.get(owner_field) != agent_id:
        raise ValueError(f"accepted output payload owner mismatch for {agent_id}")
    for field, supplied in (
        ("evidence_bundle_ids", bundles),
        ("causal_dedupe_keys", causal_keys),
    ):
        if (
            not isinstance(supplied, list)
            or not supplied
            or any(not isinstance(item, str) or not item.strip() for item in supplied)
            or supplied != sorted(set(supplied))
        ):
            raise ValueError(
                f"accepted output {field} must be a sorted non-empty unique list "
                f"for {agent_id}:{accepted_kind}"
            )
    forbidden = {
        "verified_claim_graph",
        "verified_claim_audit",
        "private_knot_audit",
        "runtime_fallback_audit",
    }
    if forbidden.intersection(payload):
        raise ValueError(f"accepted output payload leaks runtime audit fields for {agent_id}")


def _validate_decision_control_source_closure(
    records: list[dict[str, Any]],
    *,
    stage_skips: Mapping[str, Mapping[str, Any]],
) -> None:
    """Close every Decision-internal source against this immutable cycle."""
    payloads: dict[tuple[str, str], Mapping[str, Any]] = {}
    records_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        key = (str(record["agent_id"]), str(record["accepted_output_kind"]))
        if key in payloads:
            raise ValueError(f"duplicate accepted Decision source: {key[0]}:{key[1]}")
        payloads[key] = record["output"]["payload"]
        records_by_key[key] = record

    def identity(owner: str, kind: str) -> tuple[str, str] | None:
        record = records_by_key.get((owner, kind))
        if record is None:
            return None
        return str(record["accepted_output_id"]), str(record["accepted_output_hash"])

    def assert_source(source: Any, *, owner: str, kind: str) -> None:
        if not isinstance(source, Mapping):
            raise ValueError(f"{owner} Decision control source must be an object")
        accepted = identity(owner, kind)
        skipped = stage_skips.get(owner)
        if source.get("source_status") == "ACCEPTED_OUTPUT":
            if accepted is None or skipped is not None:
                raise ValueError(f"{owner} Decision accepted control source is unavailable")
            expected = {
                "source_status": "ACCEPTED_OUTPUT",
                "agent_id": owner,
                "accepted_output_id": accepted[0],
                "accepted_output_hash": accepted[1],
                "stage_skip_id": None,
                "stage_skip_hash": None,
            }
        elif source.get("source_status") == "NO_EVALUATION_OBJECT":
            if skipped is None or accepted is not None:
                raise ValueError(f"{owner} Decision stage-skip control source is unavailable")
            expected = {
                "source_status": "NO_EVALUATION_OBJECT",
                "agent_id": owner,
                "accepted_output_id": None,
                "accepted_output_hash": None,
                "stage_skip_id": skipped["stage_skip_id"],
                "stage_skip_hash": skipped["stage_skip_hash"],
            }
        else:
            raise ValueError(f"{owner} Decision control source status is invalid")
        if dict(source) != expected:
            raise ValueError(f"{owner} Decision control source closure mismatch")

    proposal = payloads.get(("cio", "CIO_PROPOSAL"))
    if proposal is None:
        raise ValueError("Decision control closure requires the accepted CIO proposal")
    proposal_identity = (str(proposal["proposal_id"]), str(proposal["proposal_hash"]))
    for owner, kind in (
        ("cro", "CRO_RISK_REVIEW"),
        ("autonomous_execution", "EXECUTION_ASSESSMENT"),
        ("cio", "CIO_FINAL"),
    ):
        payload = payloads.get((owner, kind))
        if payload is None:
            if owner in stage_skips:
                continue
            raise ValueError(f"Decision control output is unavailable: {owner}:{kind}")
        if (
            payload.get("frozen_proposal_id") != proposal_identity[0]
            or payload.get("frozen_proposal_hash") != proposal_identity[1]
        ):
            raise ValueError(f"{owner} frozen CIO proposal source mismatch")

    assert_source(
        proposal.get("alpha_source"),
        owner="alpha_discovery",
        kind="ALPHA_DISCOVERY",
    )
    execution = payloads.get(("autonomous_execution", "EXECUTION_ASSESSMENT"))
    if execution is not None:
        assert_source(
            execution.get("cro_control_source"),
            owner="cro",
            kind="CRO_RISK_REVIEW",
        )
    final = payloads[("cio", "CIO_FINAL")]
    assert_source(
        final.get("cro_control_source"),
        owner="cro",
        kind="CRO_RISK_REVIEW",
    )
    assert_source(
        final.get("execution_control_source"),
        owner="autonomous_execution",
        kind="EXECUTION_ASSESSMENT",
    )

    alpha = payloads.get(("alpha_discovery", "ALPHA_DISCOVERY"))
    expected_alpha = sorted(
        (
            str(pick["pick_local_id"]),
            str(pick["ts_code"]),
        )
        for pick in (
            alpha.get("selection", {}).get("novel_picks", []) if alpha is not None else []
        )
    )
    actual_alpha = sorted(
        (
            str(row["alpha_pick_local_ref"]),
            str(row["ts_code"]),
        )
        for row in proposal.get("alpha_pick_resolutions", [])
    )
    if actual_alpha != expected_alpha:
        raise ValueError("CIO proposal Alpha resolution source closure mismatch")

    cro = payloads.get(("cro", "CRO_RISK_REVIEW"))
    expected_cro = sorted(
        (str(action["cro_action_ref"]), str(action["cro_action_hash"]))
        for action in (
            cro.get("review", {}).get("candidate_actions", []) if cro is not None else []
        )
        if action.get("action") != "NO_OBJECTION"
    )
    actual_cro = sorted(
        (str(row["cro_action_ref"]), str(row["cro_action_hash"]))
        for row in final.get("cro_control_resolutions", [])
    )
    if actual_cro != expected_cro:
        raise ValueError("CIO final CRO resolution source closure mismatch")

    expected_execution = sorted(
        (
            str(row["execution_assessment_ref"]),
            str(row["execution_assessment_hash"]),
        )
        for row in (
            execution.get("assessment", {}).get("order_assessments", [])
            if execution is not None
            else []
        )
    )
    actual_execution = sorted(
        (
            str(row["execution_assessment_ref"]),
            str(row["execution_assessment_hash"]),
        )
        for row in final.get("execution_control_resolutions", [])
    )
    if actual_execution != expected_execution:
        raise ValueError("CIO final execution resolution source closure mismatch")


def _accepted_stage_skips(
    conn: sqlite3.Connection,
    *,
    state: Mapping[str, Any],
    graph_run_id: str,
    outcome_schedule_plan_id: str,
    schedule_by_agent: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    raw = state.get("outcome_stage_skips")
    if not isinstance(raw, Mapping):
        raise ValueError("outcome_stage_skips must be an object")
    result: dict[str, dict[str, Any]] = {}
    for agent_id, supplied in raw.items():
        if not isinstance(agent_id, str) or not isinstance(supplied, Mapping):
            raise ValueError("outcome stage-skip entries must be Agent-owned objects")
        row = conn.execute(
            "SELECT record_json FROM no_evaluation_object_stage_skips_v2 "
            "WHERE stage_skip_id = ?",
            (supplied.get("stage_skip_id"),),
        ).fetchone()
        if row is None:
            raise ValueError(f"outcome stage skip is unavailable: {agent_id}")
        persisted = json.loads(row[0])
        if dict(supplied) != persisted:
            raise ValueError(f"outcome stage skip payload mismatch: {agent_id}")
        without_hash = {
            key: value for key, value in persisted.items() if key != "stage_skip_hash"
        }
        if persisted.get("stage_skip_hash") != canonical_hash(without_hash):
            raise ValueError(f"outcome stage skip hash mismatch: {agent_id}")
        slot = schedule_by_agent.get(agent_id)
        for field, expected in (
            ("agent_id", agent_id),
            ("graph_run_id", graph_run_id),
            ("outcome_schedule_plan_id", outcome_schedule_plan_id),
            ("outcome_schedule_slot_id", slot.get("outcome_schedule_slot_id") if slot else None),
            ("scheduled_sample_id", slot.get("scheduled_sample_id") if slot else None),
            ("track_key_hash", slot.get("track_key_hash") if slot else None),
            ("skip_reason", "NO_EVALUATION_OBJECT"),
            ("member_count", 0),
            ("model_invoked", False),
        ):
            if persisted.get(field) != expected:
                raise ValueError(f"outcome stage skip {field} mismatch: {agent_id}")
        if not slot or slot.get("run_slot_kind") != "OUTCOME_SCHEDULED":
            raise ValueError(f"stage skip requires OUTCOME_SCHEDULED slot: {agent_id}")
        result[agent_id] = persisted
    return result


def _required_runtime_stage_keys() -> set[tuple[str, str]]:
    keys = {(_audit_stage(agent_id), agent_id) for agent_id in OUTCOME_CONTRACTS}
    keys.remove(("agent_run", "cio"))
    keys.update({("cio_proposal", "cio"), ("cio_final", "cio")})
    return keys


def validate_runtime_stage_completion(
    audits: object,
    stage_skips: object,
) -> None:
    """Validate the disjoint accepted-output/stage-skip union for 29 stages."""
    if not isinstance(audits, list) or not isinstance(stage_skips, Mapping):
        raise ValueError("cycle completion requires audit array and stage-skip object")
    skip_keys: set[tuple[str, str]] = set()
    for agent_id, record in stage_skips.items():
        if not isinstance(agent_id, str) or not isinstance(record, Mapping):
            raise ValueError("cycle stage skip must be an Agent-owned object")
        if record.get("agent_id") != agent_id or record.get("model_invoked") is not False:
            raise ValueError(f"invalid cycle stage skip: {agent_id}")
        skip_keys.add((_audit_stage(agent_id), agent_id))
    audit_keys: set[tuple[str, str]] = set()
    for audit in audits:
        if not isinstance(audit, Mapping):
            raise ValueError("cycle Agent audit must be an object")
        if audit.get("status") not in {"accepted", "accepted_empty"}:
            raise ValueError("cycle Agent audit is not accepted")
        key = (
            _required_text(audit.get("stage"), "audit.stage"),
            _required_text(audit.get("agent"), "audit.agent"),
        )
        if key in audit_keys:
            raise ValueError(f"duplicate cycle Agent stage: {key[1]}:{key[0]}")
        audit_keys.add(key)
    if audit_keys & skip_keys:
        raise ValueError("cycle stage cannot be both accepted and skipped")
    if audit_keys | skip_keys != _required_runtime_stage_keys():
        raise ValueError("cycle must resolve the exact 29 Agent stages")


def _audit_stage(agent_id: str) -> str:
    decision_stages = {
        "alpha_discovery": "alpha_discovery",
        "cro": "cro_review",
        "autonomous_execution": "execution_feasibility",
    }
    if agent_id in decision_stages:
        return decision_stages[agent_id]
    contract = OUTCOME_CONTRACTS[agent_id]
    if contract["layer"] == "SECTOR" and agent_id != "relationship_mapper":
        return "final_selection"
    return "agent_run"


def evidence_lineage_envelope(output: Mapping[str, Any]) -> dict[str, Any]:
    claims = output.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("accepted output must contain non-empty claims")
    graph = output.get("verified_claim_graph")
    if not isinstance(graph, Mapping):
        raise ValueError("accepted output must contain verified_claim_graph")
    ledger = graph.get("evidence_ledger")
    if not isinstance(ledger, list) or not ledger:
        raise ValueError("verified_claim_graph must contain a non-empty evidence ledger")
    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    for entry in ledger:
        if not isinstance(entry, Mapping):
            raise ValueError("verified evidence ledger entry must be an object")
        evidence_id = entry.get("evidence_id")
        source_fingerprint = entry.get("source_fingerprint")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError("verified evidence ledger entry has no evidence_id")
        if evidence_id in evidence_by_id:
            raise ValueError(f"duplicate verified evidence id: {evidence_id}")
        if not _is_sha256(source_fingerprint):
            raise ValueError(f"invalid source fingerprint for evidence: {evidence_id}")
        evidence_by_id[evidence_id] = entry
    evidence_ids = sorted(
        {
            evidence_id
            for claim in claims
            if isinstance(claim, Mapping)
            for evidence_id in claim.get("evidence_ids", [])
            if isinstance(evidence_id, str) and evidence_id
        }
    )
    if not evidence_ids:
        raise ValueError("accepted output claims must resolve non-empty evidence IDs")
    unresolved_ids = [
        evidence_id for evidence_id in evidence_ids if evidence_id not in evidence_by_id
    ]
    if unresolved_ids:
        raise ValueError(f"accepted output has unresolved evidence IDs: {unresolved_ids}")
    run_id = graph.get("run_id")
    snapshot_hash = graph.get("snapshot_hash")
    if not isinstance(run_id, str) or not run_id or not _is_sha256(snapshot_hash):
        raise ValueError("verified_claim_graph run/snapshot identity is invalid")
    bundle_id = f"evidence-bundle:{run_id}:{snapshot_hash.removeprefix('sha256:')}"
    causal_keys = sorted(
        {str(evidence_by_id[evidence_id]["source_fingerprint"]) for evidence_id in evidence_ids}
    )
    return {
        "payload": dict(output),
        "evidence_bundle_ids": [bundle_id],
        "causal_dedupe_keys": causal_keys,
    }


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


__all__ = [
    "canonical_hash",
    "canonical_json",
    "deterministic_id",
    "evidence_lineage_envelope",
    "get_production_weight_snapshot",
    "prepare_production_variant",
    "append_accepted_cycle",
    "register_production_variant",
    "validate_runtime_stage_completion",
]

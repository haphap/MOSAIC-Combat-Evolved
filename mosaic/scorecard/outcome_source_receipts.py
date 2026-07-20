"""Cryptographic source authority for deterministic realized outcomes.

Private projection files carry only an immutable batch reference.  The public
Scorecard assembles realized metrics from an exact set of source-owned,
Ed25519-signed observations and re-verifies every receipt on every read.
"""

from __future__ import annotations

import base64
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker

from mosaic.scorecard.darwinian_v2 import (
    canonical_hash,
    canonical_json,
    deterministic_id,
)
from mosaic.scorecard.outcome_contracts import (
    OUTCOME_CONTRACTS,
    OUTCOME_REALIZED_METRIC_SCHEMAS,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
OUTCOME_SOURCE_AUTHORITY_REGISTRY_PATH = (
    _REPO_ROOT
    / "registry"
    / "prompt_checks"
    / "outcome_source_authority_registry_v1.json"
)
OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH = (
    _REPO_ROOT / "schemas" / "outcome_source_authority_registry_v1.schema.json"
)
OUTCOME_SOURCE_RECEIPT_SCHEMA_PATH = (
    _REPO_ROOT / "schemas" / "outcome_source_receipt_v1.schema.json"
)
OUTCOME_SOURCE_BATCH_SCHEMA_PATH = (
    _REPO_ROOT / "schemas" / "outcome_source_batch_v1.schema.json"
)

AUTHORITY_REGISTRY_VERSION = "outcome_source_authority_registry_v1"
AUTHORITY_ENTRY_VERSION = "outcome_source_authority_entry_v1"
AUTHORITY_REGISTRY_HISTORY_VERSION = "outcome_source_authority_registry_history_v1"
SOURCE_ATTESTATION_SCHEMA_VERSION = "outcome_source_attestation_v1"
SOURCE_RECEIPT_SCHEMA_VERSION = "outcome_source_receipt_v1"
SOURCE_BATCH_SCHEMA_VERSION = "outcome_source_batch_v1"
SOURCE_SIGNATURE_DOMAIN = "MOSAIC_OUTCOME_SOURCE_ATTESTATION_V1"
_SIGNATURE_DOMAIN_PREFIX = b"MOSAIC_OUTCOME_SOURCE_ATTESTATION_V1\x00"
_ABSTAIN_REASONS = {
    "EXOGENOUS_MARKET_DISRUPTION",
    "OUTCOME_NOT_OBSERVABLE",
}
_ATTESTATION_FIELDS = {
    "schema_version",
    "signature_domain",
    "scheduled_sample_id",
    "outcome_schedule_slot_id",
    "outcome_schedule_slot_hash",
    "evaluation_opportunity_set_id",
    "evaluation_opportunity_set_hash",
    "accepted_output_id",
    "accepted_output_hash",
    "track_key_hash",
    "agent_id",
    "required_source_id",
    "source_owner",
    "adapter_contract_id",
    "adapter_contract_version",
    "verifier_id",
    "signing_key_id",
    "opportunity_as_of",
    "outcome_due_at",
    "projection_status",
    "realized_metric_schema_id",
    "source_observation",
    "evidence_artifact_hashes",
    "observed_through_at",
    "released_at",
    "vintage_at",
    "verified_at",
    "abstain_reason",
}


class OutcomeSourceBatchUnavailable(FileNotFoundError):
    """The exact source batch has not been atomically sealed yet."""


def _server_now() -> datetime:
    """Read the Scorecard host clock; callers cannot supply audit timestamps."""
    return datetime.now(timezone.utc)


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


def _timestamp(value: Any, field: str) -> datetime:
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return payload


def _assert_finite_json(value: Any, label: str, path: str = "$") -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label} contains a non-finite number at {path}")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_finite_json(child, label, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _assert_finite_json(child, label, f"{path}[{index}]")


def _validate_schema(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    label: str,
) -> None:
    _assert_finite_json(payload, label)
    errors = sorted(
        Draft202012Validator(
            dict(schema),
            format_checker=FormatChecker(),
        ).iter_errors(dict(payload)),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.absolute_path) or "$"
        raise ValueError(f"{label} schema violation at {location}: {first.message}")


def _base64url_decode(value: Any, field: str, *, expected_bytes: int) -> bytes:
    text = _required_text(value, field)
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as exc:
        raise ValueError(f"{field} must be unpadded base64url") from exc
    if len(decoded) != expected_bytes:
        raise ValueError(f"{field} has the wrong decoded length")
    if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != text:
        raise ValueError(f"{field} is not canonical unpadded base64url")
    return decoded


def _validated_authority_registry(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(payload)
    schema = dict(schema)
    _validate_schema(payload, schema, label="outcome source authority registry")
    if payload.get("registry_schema_hash") != canonical_hash(schema):
        raise RuntimeError("outcome source authority registry schema hash mismatch")
    body = {key: value for key, value in payload.items() if key != "registry_hash"}
    if payload.get("registry_hash") != canonical_hash(body):
        raise RuntimeError("outcome source authority registry hash mismatch")

    expected_source_ids = {
        source_id
        for contract in OUTCOME_CONTRACTS.values()
        for source_id in contract["required_source_ids"]
    }
    entries = payload.get("entries")
    by_source = {
        str(entry["required_source_id"]): entry
        for entry in entries
        if isinstance(entry, dict)
    }
    if len(by_source) != len(entries) or set(by_source) != expected_source_ids:
        raise RuntimeError("outcome source authority registry source coverage drift")

    schemas_by_source: dict[str, set[str]] = {
        source_id: set() for source_id in expected_source_ids
    }
    for contract in OUTCOME_CONTRACTS.values():
        schema_id = str(contract["realized_metric_schema_id"])
        for source_id in contract["required_source_ids"]:
            schemas_by_source[str(source_id)].add(schema_id)
    for source_id, entry in by_source.items():
        if entry.get("entry_version") != AUTHORITY_ENTRY_VERSION:
            raise RuntimeError("outcome source authority entry version drift")
        entry_body = {
            key: value for key, value in entry.items() if key != "entry_hash"
        }
        if entry.get("entry_hash") != canonical_hash(entry_body):
            raise RuntimeError(f"outcome source authority entry hash drift: {source_id}")
        _base64url_decode(
            entry.get("ed25519_public_key_base64url"),
            f"{source_id}.ed25519_public_key_base64url",
            expected_bytes=32,
        )
        effective_from = _timestamp(entry.get("effective_from"), "effective_from")
        effective_until_raw = entry.get("effective_until")
        if effective_until_raw is not None and _timestamp(
            effective_until_raw, "effective_until"
        ) <= effective_from:
            raise RuntimeError(f"outcome source authority window is empty: {source_id}")
        owned = entry.get("owned_realized_fields_by_schema_id")
        if not isinstance(owned, dict) or set(owned) != schemas_by_source[source_id]:
            raise RuntimeError(f"outcome source schema ownership drift: {source_id}")

    signing_key_ids = [str(entry["signing_key_id"]) for entry in entries]
    public_keys = [str(entry["ed25519_public_key_base64url"]) for entry in entries]
    if len(set(signing_key_ids)) != len(signing_key_ids):
        raise RuntimeError("outcome source signing_key_id values must be unique")
    if len(set(public_keys)) != len(public_keys):
        raise RuntimeError("outcome source Ed25519 public keys must be unique")

    for agent_id, contract in OUTCOME_CONTRACTS.items():
        schema_id = str(contract["realized_metric_schema_id"])
        realized_schema = OUTCOME_REALIZED_METRIC_SCHEMAS[schema_id]
        required_fields = set(realized_schema.get("required", []))
        claimed: list[str] = []
        for source_id in contract["required_source_ids"]:
            fields = by_source[str(source_id)][
                "owned_realized_fields_by_schema_id"
            ][schema_id]
            if any(field not in required_fields for field in fields):
                raise RuntimeError(f"unknown realized field owner for Agent {agent_id}")
            claimed.extend(fields)
        if len(claimed) != len(set(claimed)) or set(claimed) != required_fields:
            raise RuntimeError(f"realized field ownership is not exact for Agent {agent_id}")
    return payload


def load_outcome_source_authority_registry(
    registry_path: Path | None = None,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    """Load and close the public 26-source trust-root registry."""
    registry_path = registry_path or OUTCOME_SOURCE_AUTHORITY_REGISTRY_PATH
    schema_path = schema_path or OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH
    return _validated_authority_registry(
        _load_json(registry_path),
        _load_json(schema_path),
    )


def _authority_pins(
    registry: Mapping[str, Any],
    registry_schema: Mapping[str, Any],
) -> dict[str, str]:
    return {
        "authority_registry_version": str(registry["registry_version"]),
        "authority_registry_hash": str(registry["registry_hash"]),
        "authority_registry_schema_hash": canonical_hash(dict(registry_schema)),
        "receipt_schema_hash": canonical_hash(
            _load_json(OUTCOME_SOURCE_RECEIPT_SCHEMA_PATH)
        ),
        "batch_schema_hash": canonical_hash(
            _load_json(OUTCOME_SOURCE_BATCH_SCHEMA_PATH)
        ),
    }


def outcome_source_authority_pins(
    registry_path: Path | None = None,
    registry_schema_path: Path | None = None,
) -> dict[str, str]:
    registry = load_outcome_source_authority_registry(
        registry_path,
        registry_schema_path,
    )
    schema_path = (
        registry_schema_path or OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH
    )
    return _authority_pins(registry, _load_json(schema_path))


def outcome_source_attestation_signing_bytes(
    attestation: Mapping[str, Any],
) -> bytes:
    """Return the only bytes an enrolled source authority may sign."""
    if set(attestation) != _ATTESTATION_FIELDS:
        raise ValueError("outcome source attestation fields drift")
    if (
        attestation.get("schema_version") != SOURCE_ATTESTATION_SCHEMA_VERSION
        or attestation.get("signature_domain") != SOURCE_SIGNATURE_DOMAIN
    ):
        raise ValueError("outcome source attestation domain drift")
    _assert_finite_json(attestation, "outcome source attestation")
    return _SIGNATURE_DOMAIN_PREFIX + canonical_json(dict(attestation)).encode("utf-8")


def build_outcome_source_attestation(
    *,
    evaluation_context: Mapping[str, Any],
    required_source_id: str,
    source_observation: Mapping[str, Any],
    evidence_artifact_hashes: Sequence[str],
    observed_through_at: str,
    released_at: str,
    vintage_at: str,
    verified_at: str,
    projection_status: str = "SCORE",
    abstain_reason: str | None = None,
    registry_path: Path | None = None,
    registry_schema_path: Path | None = None,
) -> dict[str, Any]:
    """Build an unsigned, registry-owned source attestation for external signing."""
    registry = load_outcome_source_authority_registry(
        registry_path,
        registry_schema_path,
    )
    if registry.get("provisioning_status") != "ACTIVE":
        raise ValueError("outcome source authority registry provisioning is required")
    entries = {
        entry["required_source_id"]: entry for entry in registry["entries"]
    }
    source_id = _required_text(required_source_id, "required_source_id")
    entry = entries.get(source_id)
    if entry is None:
        raise ValueError("required_source_id is not enrolled")
    _assert_finite_json(source_observation, "outcome source observation")
    hashes = sorted(
        _required_sha256(value, "evidence_artifact_hashes")
        for value in evidence_artifact_hashes
    )
    if not hashes or len(hashes) != len(set(hashes)):
        raise ValueError("evidence_artifact_hashes must be non-empty and unique")
    context_fields = {
        "scheduled_sample_id",
        "outcome_schedule_slot_id",
        "outcome_schedule_slot_hash",
        "evaluation_opportunity_set_id",
        "evaluation_opportunity_set_hash",
        "accepted_output_id",
        "accepted_output_hash",
        "track_key_hash",
        "agent_id",
        "opportunity_as_of",
        "outcome_due_at",
        "realized_metric_schema_id",
    }
    if set(evaluation_context) != context_fields:
        raise ValueError("outcome source evaluation context fields drift")
    return {
        "schema_version": SOURCE_ATTESTATION_SCHEMA_VERSION,
        "signature_domain": SOURCE_SIGNATURE_DOMAIN,
        **dict(evaluation_context),
        "required_source_id": source_id,
        "source_owner": entry["source_owner"],
        "adapter_contract_id": entry["adapter_contract_id"],
        "adapter_contract_version": entry["adapter_contract_version"],
        "verifier_id": entry["verifier_id"],
        "signing_key_id": entry["signing_key_id"],
        "projection_status": projection_status,
        "source_observation": dict(source_observation),
        "evidence_artifact_hashes": hashes,
        "observed_through_at": observed_through_at,
        "released_at": released_at,
        "vintage_at": vintage_at,
        "verified_at": verified_at,
        "abstain_reason": abstain_reason,
    }


def _verified_signature(
    attestation: Mapping[str, Any],
    signature: Any,
    entry: Mapping[str, Any],
) -> str:
    signature_text = _required_text(signature, "detached_signature_base64url")
    signature_bytes = _base64url_decode(
        signature_text,
        "detached_signature_base64url",
        expected_bytes=64,
    )
    public_key = Ed25519PublicKey.from_public_bytes(
        _base64url_decode(
            entry.get("ed25519_public_key_base64url"),
            "ed25519_public_key_base64url",
            expected_bytes=32,
        )
    )
    try:
        public_key.verify(
            signature_bytes,
            outcome_source_attestation_signing_bytes(attestation),
        )
    except InvalidSignature as exc:
        raise ValueError("outcome source Ed25519 signature is invalid") from exc
    return signature_text


def _validate_attestation(
    *,
    attestation: Mapping[str, Any],
    signature: Any,
    entry: Mapping[str, Any],
    expected_context: Mapping[str, Any],
    ingested_at: str,
) -> str:
    for field, expected in expected_context.items():
        if attestation.get(field) != expected:
            raise ValueError(f"outcome source attestation {field} drift")
    for field in (
        "required_source_id",
        "source_owner",
        "adapter_contract_id",
        "adapter_contract_version",
        "verifier_id",
        "signing_key_id",
    ):
        expected = (
            entry["required_source_id"] if field == "required_source_id" else entry[field]
        )
        if attestation.get(field) != expected:
            raise ValueError(f"outcome source attestation {field} is not registry-owned")

    schema_id = str(attestation.get("realized_metric_schema_id"))
    owned_fields = set(entry["owned_realized_fields_by_schema_id"][schema_id])
    observation = attestation.get("source_observation")
    if not isinstance(observation, dict):
        raise ValueError("outcome source observation must be an object")
    _assert_finite_json(observation, "outcome source observation")
    status = attestation.get("projection_status")
    abstain_reason = attestation.get("abstain_reason")
    if status == "SCORE":
        if set(observation) != owned_fields or abstain_reason is not None:
            raise ValueError("SCORE source observation field ownership drift")
    elif status == "ABSTAIN":
        if observation or abstain_reason not in _ABSTAIN_REASONS:
            raise ValueError("ABSTAIN source observation semantics drift")
    else:
        raise ValueError("outcome source projection_status is invalid")

    evidence = attestation.get("evidence_artifact_hashes")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("outcome source evidence artifact hashes are required")
    normalized_evidence = [
        _required_sha256(value, "evidence_artifact_hashes") for value in evidence
    ]
    if evidence != sorted(normalized_evidence) or len(evidence) != len(set(evidence)):
        raise ValueError("outcome source evidence artifact hashes are not canonical")

    due = _timestamp(attestation.get("outcome_due_at"), "outcome_due_at")
    observed = _timestamp(
        attestation.get("observed_through_at"), "observed_through_at"
    )
    released = _timestamp(attestation.get("released_at"), "released_at")
    vintage = _timestamp(attestation.get("vintage_at"), "vintage_at")
    verified = _timestamp(attestation.get("verified_at"), "verified_at")
    ingested = _timestamp(ingested_at, "ingested_at")
    if not due <= observed <= released <= vintage <= verified <= ingested:
        raise ValueError(
            "outcome source PIT order must satisfy due <= observed-through <= "
            "released <= vintage <= verified <= ingested"
        )
    effective_from = _timestamp(entry.get("effective_from"), "effective_from")
    effective_until_raw = entry.get("effective_until")
    if ingested < effective_from or (
        effective_until_raw is not None
        and ingested >= _timestamp(effective_until_raw, "effective_until")
    ):
        raise ValueError("outcome source signing authority is outside its effective window")
    return _verified_signature(attestation, signature, entry)


def _validated_evaluation_context(
    conn: sqlite3.Connection,
    evaluation_opportunity_set_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    opportunity_row = conn.execute(
        "SELECT record_json FROM evaluation_opportunity_sets_v2 "
        "WHERE evaluation_opportunity_set_id = ? AND opportunity_set_status = 'AVAILABLE'",
        (evaluation_opportunity_set_id,),
    ).fetchone()
    if opportunity_row is None:
        raise ValueError("AVAILABLE evaluation opportunity set is required")
    opportunity = json.loads(opportunity_row[0])
    if opportunity.get("evaluation_opportunity_set_hash") != canonical_hash(
        {
            key: value
            for key, value in opportunity.items()
            if key != "evaluation_opportunity_set_hash"
        }
    ):
        raise ValueError("evaluation opportunity set hash mismatch")
    schedule_row = conn.execute(
        "SELECT s.record_json, p.record_json FROM outcome_schedule_slots_v2 s "
        "JOIN outcome_schedule_plans_v2 p USING(outcome_schedule_plan_id) "
        "WHERE s.scheduled_sample_id = ?",
        (opportunity["scheduled_sample_id"],),
    ).fetchone()
    if schedule_row is None:
        raise ValueError("outcome source schedule context is unavailable")
    slot = json.loads(schedule_row[0])
    plan = json.loads(schedule_row[1])
    if slot.get("outcome_schedule_slot_hash") != canonical_hash(
        {
            key: value
            for key, value in slot.items()
            if key != "outcome_schedule_slot_hash"
        }
    ) or plan.get("outcome_schedule_plan_hash") != canonical_hash(
        {
            key: value
            for key, value in plan.items()
            if key != "outcome_schedule_plan_hash"
        }
    ):
        raise ValueError("outcome source schedule hash mismatch")
    if any(
        slot.get(field) != opportunity.get(field)
        for field in ("scheduled_sample_id", "track_key_hash", "agent_id")
    ) or plan.get("as_of") != opportunity.get("as_of"):
        raise ValueError("outcome source schedule/opportunity binding drift")

    audit_rows = conn.execute(
        "SELECT current.record_json FROM agent_outcome_eligibility_revisions_v2 current "
        "WHERE current.scheduled_sample_id = ? AND current.track_key_hash = ? "
        "AND current.agent_id = ? AND current.sample_origin = 'PRODUCTION_ACTIVE' "
        "AND NOT EXISTS (SELECT 1 FROM agent_outcome_eligibility_revisions_v2 newer "
        "WHERE newer.audit_id = current.audit_id "
        "AND newer.audit_sequence > current.audit_sequence)",
        (
            opportunity["scheduled_sample_id"],
            opportunity["track_key_hash"],
            opportunity["agent_id"],
        ),
    ).fetchall()
    if len(audit_rows) != 1:
        raise ValueError("outcome source batch requires one current eligibility revision")
    audit = json.loads(audit_rows[0][0])
    if (
        audit.get("audit_revision_hash")
        != canonical_hash(
            {
                key: value
                for key, value in audit.items()
                if key != "audit_revision_hash"
            }
        )
        or audit.get("disposition") != "PENDING"
        or audit.get("evaluation_opportunity_set_id")
        != opportunity["evaluation_opportunity_set_id"]
        or audit.get("evaluation_opportunity_set_hash")
        != opportunity["evaluation_opportunity_set_hash"]
    ):
        raise ValueError("outcome source batch requires the hash-bound PENDING revision")
    accepted_row = conn.execute(
        "SELECT record_json FROM accepted_agent_outputs_v2 WHERE accepted_output_id = ?",
        (audit["accepted_output_id"],),
    ).fetchone()
    if accepted_row is None:
        raise ValueError("outcome source accepted output is unavailable")
    accepted = json.loads(accepted_row[0])
    if (
        accepted.get("accepted_output_hash")
        != canonical_hash(
            {
                key: value
                for key, value in accepted.items()
                if key != "accepted_output_hash"
            }
        )
        or accepted.get("accepted_output_hash") != audit.get("accepted_output_hash")
    ):
        raise ValueError("outcome source accepted output hash mismatch")
    context = {
        "scheduled_sample_id": opportunity["scheduled_sample_id"],
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "evaluation_opportunity_set_id": opportunity["evaluation_opportunity_set_id"],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "accepted_output_id": audit["accepted_output_id"],
        "accepted_output_hash": audit["accepted_output_hash"],
        "track_key_hash": opportunity["track_key_hash"],
        "agent_id": opportunity["agent_id"],
        "opportunity_as_of": plan["as_of"],
        "outcome_due_at": slot["outcome_due_at"],
        "realized_metric_schema_id": OUTCOME_CONTRACTS[opportunity["agent_id"]][
            "realized_metric_schema_id"
        ],
    }
    return context, opportunity, audit


def _build_receipt(
    *,
    signed_envelope: Mapping[str, Any],
    entry: Mapping[str, Any],
    expected_context: Mapping[str, Any],
    ingested_at: str,
    pins: Mapping[str, str],
) -> dict[str, Any]:
    if set(signed_envelope) != {"attestation", "detached_signature_base64url"}:
        raise ValueError("signed outcome source envelope fields drift")
    attestation = signed_envelope.get("attestation")
    if not isinstance(attestation, Mapping) or set(attestation) != _ATTESTATION_FIELDS:
        raise ValueError("signed outcome source attestation fields drift")
    signature = _validate_attestation(
        attestation=attestation,
        signature=signed_envelope.get("detached_signature_base64url"),
        entry=entry,
        expected_context=expected_context,
        ingested_at=ingested_at,
    )
    attestation_hash = canonical_hash(dict(attestation))
    receipt_id = deterministic_id(
        "outcome-source-receipt",
        {
            "authority_entry_hash": entry["entry_hash"],
            "attestation_hash": attestation_hash,
            "detached_signature_base64url": signature,
        },
    )
    without_hash = {
        "schema_version": SOURCE_RECEIPT_SCHEMA_VERSION,
        "source_receipt_id": receipt_id,
        "authority_registry_version": pins["authority_registry_version"],
        "authority_registry_hash": pins["authority_registry_hash"],
        "authority_registry_schema_hash": pins[
            "authority_registry_schema_hash"
        ],
        "authority_entry_hash": entry["entry_hash"],
        "attestation_hash": attestation_hash,
        "signed_attestation": dict(attestation),
        "detached_signature_base64url": signature,
        "ingested_at": _required_text(ingested_at, "ingested_at"),
    }
    record = {**without_hash, "source_receipt_hash": canonical_hash(without_hash)}
    _validate_schema(
        record,
        _load_json(OUTCOME_SOURCE_RECEIPT_SCHEMA_PATH),
        label="outcome source receipt",
    )
    return record


def _receipt_ref(receipt: Mapping[str, Any]) -> dict[str, Any]:
    attestation = receipt["signed_attestation"]
    return {
        "required_source_id": attestation["required_source_id"],
        "source_receipt_id": receipt["source_receipt_id"],
        "source_receipt_hash": receipt["source_receipt_hash"],
        "authority_entry_hash": receipt["authority_entry_hash"],
        "vintage_at": attestation["vintage_at"],
        "ingested_at": receipt["ingested_at"],
    }


def _fetchone_mapping(
    conn: sqlite3.Connection,
    sql: str,
    parameters: Sequence[Any],
) -> dict[str, Any] | None:
    cursor = conn.execute(sql, tuple(parameters))
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        str(description[0]): row[index]
        for index, description in enumerate(cursor.description or ())
    }


def _row_value(row: Mapping[str, Any], field: str) -> Any:
    try:
        return row[field]
    except (KeyError, TypeError):
        raise ValueError(f"outcome source SQLite row lacks {field}") from None


def _registry_history_record(
    registry: Mapping[str, Any],
    registry_schema: Mapping[str, Any],
    *,
    recorded_at: str,
) -> dict[str, Any]:
    without_hash = {
        "history_version": AUTHORITY_REGISTRY_HISTORY_VERSION,
        "authority_registry_version": registry["registry_version"],
        "authority_registry_hash": registry["registry_hash"],
        "authority_registry_schema_hash": registry["registry_schema_hash"],
        "provisioning_status": registry["provisioning_status"],
        "recorded_at": _required_text(recorded_at, "recorded_at"),
        "registry_schema": dict(registry_schema),
        "registry": dict(registry),
    }
    return {
        **without_hash,
        "registry_history_record_hash": canonical_hash(without_hash),
    }


def _read_registry_snapshot_row(
    row: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    record = json.loads(_row_value(row, "record_json"))
    expected_fields = {
        "history_version",
        "authority_registry_version",
        "authority_registry_hash",
        "authority_registry_schema_hash",
        "provisioning_status",
        "recorded_at",
        "registry_schema",
        "registry",
        "registry_history_record_hash",
    }
    if not isinstance(record, dict) or set(record) != expected_fields:
        raise ValueError("stored outcome source authority registry history fields drift")
    _assert_finite_json(record, "outcome source authority registry history")
    without_hash = {
        key: value
        for key, value in record.items()
        if key != "registry_history_record_hash"
    }
    if record.get("registry_history_record_hash") != canonical_hash(without_hash):
        raise ValueError("stored outcome source authority registry history hash mismatch")
    _timestamp(record.get("recorded_at"), "registry history recorded_at")
    mirrors = {
        "authority_registry_hash": record["authority_registry_hash"],
        "authority_registry_version": record["authority_registry_version"],
        "authority_registry_schema_hash": record[
            "authority_registry_schema_hash"
        ],
        "provisioning_status": record["provisioning_status"],
        "recorded_at": record["recorded_at"],
        "registry_history_record_hash": record["registry_history_record_hash"],
        "record_json": canonical_json(record),
    }
    if any(_row_value(row, field) != value for field, value in mirrors.items()):
        raise ValueError("stored outcome source authority registry SQLite mirror drift")
    registry_raw = record["registry"]
    schema_raw = record["registry_schema"]
    if not isinstance(registry_raw, dict) or not isinstance(schema_raw, dict):
        raise ValueError("stored outcome source authority registry snapshot is invalid")
    registry = _validated_authority_registry(registry_raw, schema_raw)
    if (
        record["history_version"] != AUTHORITY_REGISTRY_HISTORY_VERSION
        or record["provisioning_status"] != "ACTIVE"
        or registry["provisioning_status"] != "ACTIVE"
        or record["authority_registry_version"] != registry["registry_version"]
        or record["authority_registry_hash"] != registry["registry_hash"]
        or record["authority_registry_schema_hash"]
        != registry["registry_schema_hash"]
    ):
        raise ValueError("stored outcome source authority registry history binding drift")
    return registry, schema_raw, _authority_pins(registry, schema_raw)


def _read_registry_snapshot(
    conn: sqlite3.Connection,
    authority_registry_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    row = _fetchone_mapping(
        conn,
        "SELECT * FROM outcome_source_authority_registry_history_v1 "
        "WHERE authority_registry_hash = ?",
        (_required_sha256(authority_registry_hash, "authority_registry_hash"),),
    )
    if row is None:
        raise ValueError(
            "trusted outcome source authority registry history is unavailable"
        )
    return _read_registry_snapshot_row(row)


def _insert_or_reuse_registry_snapshot(
    conn: sqlite3.Connection,
    *,
    registry: Mapping[str, Any],
    registry_schema: Mapping[str, Any],
    recorded_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    registry_hash = _required_sha256(
        registry.get("registry_hash"),
        "authority_registry_hash",
    )
    existing = _fetchone_mapping(
        conn,
        "SELECT * FROM outcome_source_authority_registry_history_v1 "
        "WHERE authority_registry_hash = ?",
        (registry_hash,),
    )
    if existing is not None:
        stored_registry, stored_schema, stored_pins = _read_registry_snapshot_row(
            existing
        )
        if stored_registry != dict(registry) or stored_schema != dict(registry_schema):
            raise ValueError("outcome source authority registry history hash collision")
        return stored_registry, stored_schema, stored_pins

    record = _registry_history_record(
        registry,
        registry_schema,
        recorded_at=recorded_at,
    )
    values = {
        "authority_registry_hash": record["authority_registry_hash"],
        "authority_registry_version": record["authority_registry_version"],
        "authority_registry_schema_hash": record[
            "authority_registry_schema_hash"
        ],
        "provisioning_status": record["provisioning_status"],
        "recorded_at": record["recorded_at"],
        "registry_history_record_hash": record["registry_history_record_hash"],
        "record_json": canonical_json(record),
    }
    columns = tuple(values)
    try:
        conn.execute(
            "INSERT INTO outcome_source_authority_registry_history_v1 "
            f"({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            "conflicting concurrent outcome source authority registry history"
        ) from exc
    return dict(registry), dict(registry_schema), _authority_pins(
        registry,
        registry_schema,
    )


def _read_receipt(
    row: Mapping[str, Any],
    *,
    entries: Mapping[str, Mapping[str, Any]],
    pins: Mapping[str, str],
) -> dict[str, Any]:
    receipt = json.loads(_row_value(row, "record_json"))
    if not isinstance(receipt, dict):
        raise ValueError("stored outcome source receipt must be an object")
    _validate_schema(
        receipt,
        _load_json(OUTCOME_SOURCE_RECEIPT_SCHEMA_PATH),
        label="stored outcome source receipt",
    )
    supplied_hash = _required_sha256(
        receipt.get("source_receipt_hash"), "source_receipt_hash"
    )
    without_hash = {
        key: value for key, value in receipt.items() if key != "source_receipt_hash"
    }
    if supplied_hash != canonical_hash(without_hash):
        raise ValueError("stored outcome source receipt hash mismatch")
    attestation = receipt["signed_attestation"]
    source_id = str(attestation["required_source_id"])
    entry = entries.get(source_id)
    if entry is None or receipt.get("authority_entry_hash") != entry.get("entry_hash"):
        raise ValueError("stored outcome source authority entry drift")
    for field in (
        "authority_registry_version",
        "authority_registry_hash",
        "authority_registry_schema_hash",
    ):
        if receipt.get(field) != pins[field]:
            raise ValueError(f"stored outcome source receipt {field} drift")
    expected_id = deterministic_id(
        "outcome-source-receipt",
        {
            "authority_entry_hash": receipt["authority_entry_hash"],
            "attestation_hash": canonical_hash(attestation),
            "detached_signature_base64url": receipt[
                "detached_signature_base64url"
            ],
        },
    )
    if (
        receipt.get("source_receipt_id") != expected_id
        or receipt.get("attestation_hash") != canonical_hash(attestation)
    ):
        raise ValueError("stored outcome source receipt identity mismatch")
    _validate_attestation(
        attestation=attestation,
        signature=receipt["detached_signature_base64url"],
        entry=entry,
        expected_context={
            field: attestation[field]
            for field in (
                "scheduled_sample_id",
                "outcome_schedule_slot_id",
                "outcome_schedule_slot_hash",
                "evaluation_opportunity_set_id",
                "evaluation_opportunity_set_hash",
                "accepted_output_id",
                "accepted_output_hash",
                "track_key_hash",
                "agent_id",
                "opportunity_as_of",
                "outcome_due_at",
                "realized_metric_schema_id",
            )
        },
        ingested_at=receipt["ingested_at"],
    )
    mirrors = {
        "source_receipt_id": receipt["source_receipt_id"],
        "source_receipt_hash": receipt["source_receipt_hash"],
        "scheduled_sample_id": attestation["scheduled_sample_id"],
        "evaluation_opportunity_set_id": attestation[
            "evaluation_opportunity_set_id"
        ],
        "accepted_output_id": attestation["accepted_output_id"],
        "agent_id": attestation["agent_id"],
        "required_source_id": source_id,
        "authority_registry_hash": receipt["authority_registry_hash"],
        "authority_entry_hash": receipt["authority_entry_hash"],
        "source_owner": attestation["source_owner"],
        "adapter_contract_id": attestation["adapter_contract_id"],
        "adapter_contract_version": attestation["adapter_contract_version"],
        "verifier_id": attestation["verifier_id"],
        "signing_key_id": attestation["signing_key_id"],
        "attestation_hash": receipt["attestation_hash"],
        "detached_signature_base64url": receipt[
            "detached_signature_base64url"
        ],
        "observed_through_at": attestation["observed_through_at"],
        "released_at": attestation["released_at"],
        "vintage_at": attestation["vintage_at"],
        "verified_at": attestation["verified_at"],
        "ingested_at": receipt["ingested_at"],
    }
    if any(_row_value(row, field) != value for field, value in mirrors.items()):
        raise ValueError("stored outcome source receipt SQLite mirror drift")
    return receipt


def _insert_or_reuse_receipt(
    conn: sqlite3.Connection,
    *,
    receipt: Mapping[str, Any],
    entries: Mapping[str, Mapping[str, Any]],
    pins: Mapping[str, str],
) -> dict[str, Any]:
    attestation = receipt["signed_attestation"]
    existing = _fetchone_mapping(
        conn,
        "SELECT * FROM outcome_source_receipts_v1 "
        "WHERE scheduled_sample_id = ? AND required_source_id = ?",
        (attestation["scheduled_sample_id"], attestation["required_source_id"]),
    )
    if existing is not None:
        stored = _read_receipt(existing, entries=entries, pins=pins)
        if (
            stored["signed_attestation"] != receipt["signed_attestation"]
            or stored["detached_signature_base64url"]
            != receipt["detached_signature_base64url"]
            or stored["authority_entry_hash"] != receipt["authority_entry_hash"]
        ):
            raise ValueError("conflicting outcome source receipt vintage or signature")
        return stored
    values = {
        "source_receipt_id": receipt["source_receipt_id"],
        "source_receipt_hash": receipt["source_receipt_hash"],
        "scheduled_sample_id": attestation["scheduled_sample_id"],
        "evaluation_opportunity_set_id": attestation[
            "evaluation_opportunity_set_id"
        ],
        "accepted_output_id": attestation["accepted_output_id"],
        "agent_id": attestation["agent_id"],
        "required_source_id": attestation["required_source_id"],
        "authority_registry_hash": receipt["authority_registry_hash"],
        "authority_entry_hash": receipt["authority_entry_hash"],
        "source_owner": attestation["source_owner"],
        "adapter_contract_id": attestation["adapter_contract_id"],
        "adapter_contract_version": attestation["adapter_contract_version"],
        "verifier_id": attestation["verifier_id"],
        "signing_key_id": attestation["signing_key_id"],
        "attestation_hash": receipt["attestation_hash"],
        "detached_signature_base64url": receipt[
            "detached_signature_base64url"
        ],
        "observed_through_at": attestation["observed_through_at"],
        "released_at": attestation["released_at"],
        "vintage_at": attestation["vintage_at"],
        "verified_at": attestation["verified_at"],
        "ingested_at": receipt["ingested_at"],
        "record_json": canonical_json(dict(receipt)),
    }
    columns = tuple(values)
    try:
        conn.execute(
            f"INSERT INTO outcome_source_receipts_v1 ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("conflicting concurrent outcome source receipt") from exc
    return dict(receipt)


def _assembled_metrics(
    receipts: Mapping[str, Mapping[str, Any]],
    *,
    schema_id: str,
    entries: Mapping[str, Mapping[str, Any]],
    status: str,
) -> dict[str, Any]:
    if status == "ABSTAIN":
        return {}
    assembled: dict[str, Any] = {}
    for source_id, receipt in receipts.items():
        observation = receipt["signed_attestation"]["source_observation"]
        _assert_finite_json(observation, "outcome source observation")
        expected_fields = set(
            entries[source_id]["owned_realized_fields_by_schema_id"][schema_id]
        )
        if set(observation) != expected_fields or set(assembled) & set(observation):
            raise ValueError("outcome source realized-field ownership conflict")
        assembled.update(observation)
    _assert_finite_json(assembled, "assembled realized metrics")
    return assembled


def _build_batch(
    *,
    context: Mapping[str, Any],
    receipts: Mapping[str, Mapping[str, Any]],
    entries: Mapping[str, Mapping[str, Any]],
    pins: Mapping[str, str],
    sealed_at: str,
) -> dict[str, Any]:
    attestations = [receipt["signed_attestation"] for receipt in receipts.values()]
    statuses = {attestation["projection_status"] for attestation in attestations}
    reasons = {attestation["abstain_reason"] for attestation in attestations}
    if len(statuses) != 1 or len(reasons) != 1:
        raise ValueError("outcome source batch status or abstain reason conflict")
    status = statuses.pop()
    abstain_reason = reasons.pop()
    schema_id = str(context["realized_metric_schema_id"])
    realized_metrics = _assembled_metrics(
        receipts,
        schema_id=schema_id,
        entries=entries,
        status=status,
    )
    from mosaic.dataflows.outcome_runtime_inputs import (
        validate_realized_outcome_metrics,
    )

    validate_realized_outcome_metrics(
        str(context["agent_id"]),
        realized_metrics,
        allow_empty=status == "ABSTAIN",
    )
    if status == "ABSTAIN" and realized_metrics:
        raise ValueError("ABSTAIN outcome source batch must not carry realized metrics")
    evidence_ids = sorted(
        {
            evidence_hash
            for attestation in attestations
            for evidence_hash in attestation["evidence_artifact_hashes"]
        }
    )
    observed = min(
        attestations,
        key=lambda item: _timestamp(item["observed_through_at"], "observed_through_at"),
    )["observed_through_at"]
    released = max(
        attestations,
        key=lambda item: _timestamp(item["released_at"], "released_at"),
    )["released_at"]
    vintage = max(
        attestations,
        key=lambda item: _timestamp(item["vintage_at"], "vintage_at"),
    )["vintage_at"]
    verified = max(
        attestations,
        key=lambda item: _timestamp(item["verified_at"], "verified_at"),
    )["verified_at"]
    ingested = max(
        receipts.values(),
        key=lambda item: _timestamp(item["ingested_at"], "ingested_at"),
    )["ingested_at"]
    if _timestamp(sealed_at, "sealed_at") < _timestamp(ingested, "ingested_at"):
        raise ValueError("outcome source batch sealed_at precedes ingested_at")
    refs = {
        source_id: _receipt_ref(receipt)
        for source_id, receipt in sorted(receipts.items())
    }
    identity = {
        "scheduled_sample_id": context["scheduled_sample_id"],
        "evaluation_opportunity_set_hash": context[
            "evaluation_opportunity_set_hash"
        ],
        "accepted_output_hash": context["accepted_output_hash"],
        "authority_registry_hash": pins["authority_registry_hash"],
        "receipt_refs_by_required_source_id": refs,
        "projection_status": status,
        "realized_metrics": realized_metrics,
    }
    batch_id = deterministic_id("outcome-source-batch", identity)
    without_hash = {
        "schema_version": SOURCE_BATCH_SCHEMA_VERSION,
        "source_batch_id": batch_id,
        **dict(pins),
        **dict(context),
        "matured_at": verified,
        "projection_status": status,
        "realized_metrics": realized_metrics,
        "source_evidence_ids": evidence_ids,
        "receipt_refs_by_required_source_id": refs,
        "observed_through_at": observed,
        "released_at": released,
        "vintage_at": vintage,
        "verified_at": verified,
        "ingested_at": ingested,
        "sealed_at": _required_text(sealed_at, "sealed_at"),
        "abstain_reason": abstain_reason,
    }
    record = {**without_hash, "source_batch_hash": canonical_hash(without_hash)}
    _validate_schema(
        record,
        _load_json(OUTCOME_SOURCE_BATCH_SCHEMA_PATH),
        label="outcome source batch",
    )
    return record


def append_and_seal_outcome_source_batch(
    conn: sqlite3.Connection,
    *,
    evaluation_opportunity_set_id: str,
    signed_attestations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Verify, append, assemble, and seal one exact source batch atomically."""
    if conn.in_transaction:
        raise ValueError(
            "outcome source batch append requires a fresh transaction boundary"
        )
    opportunity_set_id = _required_text(
        evaluation_opportunity_set_id,
        "evaluation_opportunity_set_id",
    )
    conn.execute("BEGIN IMMEDIATE")
    try:
        # BEGIN IMMEDIATE obtains the database write lock before either
        # server-owned timestamp is sampled.  The eligibility context is then
        # read from that same write snapshot, so neither lock wait nor a
        # concurrent terminal revision can be backdated into an accepted batch.
        context, _, _ = _validated_evaluation_context(
            conn,
            opportunity_set_id,
        )
        ingested_value = _server_now()
        if not isinstance(ingested_value, datetime) or ingested_value.tzinfo is None:
            raise ValueError("outcome source server clock must return an aware datetime")
        ingested_at = ingested_value.isoformat()

        # The formal append path resolves only the server-configured current
        # trust root.  Persist the exact validated registry and its schema in
        # the same write transaction before accepting any signed observation.
        registry_schema = _load_json(
            OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH
        )
        registry = _validated_authority_registry(
            _load_json(OUTCOME_SOURCE_AUTHORITY_REGISTRY_PATH),
            registry_schema,
        )
        if registry.get("provisioning_status") != "ACTIVE":
            raise ValueError(
                "outcome source authority registry provisioning is required"
            )
        registry, _, pins = _insert_or_reuse_registry_snapshot(
            conn,
            registry=registry,
            registry_schema=registry_schema,
            recorded_at=ingested_at,
        )
        entries = {
            str(entry["required_source_id"]): entry
            for entry in registry["entries"]
        }

        contract = OUTCOME_CONTRACTS[str(context["agent_id"])]
        required_sources = set(contract["required_source_ids"])
        if (
            not isinstance(signed_attestations, Sequence)
            or isinstance(signed_attestations, (str, bytes))
            or len(signed_attestations) != len(required_sources)
        ):
            raise ValueError("outcome source batch must cover the exact required sources")
        built: dict[str, dict[str, Any]] = {}
        for envelope in signed_attestations:
            if not isinstance(envelope, Mapping):
                raise ValueError("signed outcome source envelope must be an object")
            attestation = envelope.get("attestation")
            if not isinstance(attestation, Mapping):
                raise ValueError("signed outcome source attestation must be an object")
            source_id = str(attestation.get("required_source_id"))
            if source_id not in required_sources or source_id in built:
                raise ValueError("outcome source batch required-source coverage drift")
            built[source_id] = _build_receipt(
                signed_envelope=envelope,
                entry=entries[source_id],
                expected_context=context,
                ingested_at=ingested_at,
                pins=pins,
            )
        if set(built) != required_sources:
            raise ValueError("outcome source batch required-source coverage drift")

        stored = {
            source_id: _insert_or_reuse_receipt(
                conn,
                receipt=receipt,
                entries=entries,
                pins=pins,
            )
            for source_id, receipt in sorted(built.items())
        }
        existing_row = _fetchone_mapping(
            conn,
            "SELECT * FROM outcome_source_batches_v1 WHERE scheduled_sample_id = ?",
            (context["scheduled_sample_id"],),
        )
        if existing_row is not None:
            existing = _read_batch(
                conn,
                existing_row,
                cutoff_at=None,
            )
            expected_refs = {
                source_id: _receipt_ref(receipt)
                for source_id, receipt in sorted(stored.items())
            }
            if existing["receipt_refs_by_required_source_id"] != expected_refs:
                raise ValueError("conflicting immutable outcome source batch")
            conn.commit()
            return existing

        # sealed_at is sampled only after the exact receipt set has been
        # verified and persisted, immediately before deterministic assembly
        # and the final batch insert, while the same write lock is held.
        sealed_value = _server_now()
        if not isinstance(sealed_value, datetime) or sealed_value.tzinfo is None:
            raise ValueError("outcome source server clock must return an aware datetime")
        batch = _build_batch(
            context=context,
            receipts=stored,
            entries=entries,
            pins=pins,
            sealed_at=sealed_value.isoformat(),
        )
        values = {
            "source_batch_id": batch["source_batch_id"],
            "source_batch_hash": batch["source_batch_hash"],
            "scheduled_sample_id": batch["scheduled_sample_id"],
            "evaluation_opportunity_set_id": batch[
                "evaluation_opportunity_set_id"
            ],
            "accepted_output_id": batch["accepted_output_id"],
            "agent_id": batch["agent_id"],
            "authority_registry_hash": batch["authority_registry_hash"],
            "outcome_due_at": batch["outcome_due_at"],
            "matured_at": batch["matured_at"],
            "projection_status": batch["projection_status"],
            "realized_metric_schema_id": batch["realized_metric_schema_id"],
            "observed_through_at": batch["observed_through_at"],
            "released_at": batch["released_at"],
            "vintage_at": batch["vintage_at"],
            "verified_at": batch["verified_at"],
            "ingested_at": batch["ingested_at"],
            "sealed_at": batch["sealed_at"],
            "record_json": canonical_json(batch),
        }
        columns = tuple(values)
        try:
            conn.execute(
                f"INSERT INTO outcome_source_batches_v1 ({','.join(columns)}) "
                f"VALUES ({','.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("conflicting concurrent outcome source batch") from exc
        conn.commit()
        return batch
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def _read_batch(
    conn: sqlite3.Connection,
    row: Mapping[str, Any],
    *,
    cutoff_at: str | None,
) -> dict[str, Any]:
    batch = json.loads(_row_value(row, "record_json"))
    if not isinstance(batch, dict):
        raise ValueError("stored outcome source batch must be an object")
    _validate_schema(
        batch,
        _load_json(OUTCOME_SOURCE_BATCH_SCHEMA_PATH),
        label="stored outcome source batch",
    )
    supplied_hash = _required_sha256(batch.get("source_batch_hash"), "source_batch_hash")
    without_hash = {
        key: value for key, value in batch.items() if key != "source_batch_hash"
    }
    if supplied_hash != canonical_hash(without_hash):
        raise ValueError("stored outcome source batch hash mismatch")
    registry, _, pins = _read_registry_snapshot(
        conn,
        batch.get("authority_registry_hash"),
    )
    entries = {
        str(entry["required_source_id"]): entry for entry in registry["entries"]
    }
    for field, expected in pins.items():
        if batch.get(field) != expected:
            raise ValueError(f"stored outcome source batch {field} drift")
    mirrors = {
        field: batch[field]
        for field in (
            "source_batch_id",
            "source_batch_hash",
            "scheduled_sample_id",
            "evaluation_opportunity_set_id",
            "accepted_output_id",
            "agent_id",
            "authority_registry_hash",
            "outcome_due_at",
            "matured_at",
            "projection_status",
            "realized_metric_schema_id",
            "observed_through_at",
            "released_at",
            "vintage_at",
            "verified_at",
            "ingested_at",
            "sealed_at",
        )
    }
    if any(_row_value(row, field) != value for field, value in mirrors.items()):
        raise ValueError("stored outcome source batch SQLite mirror drift")
    required_sources = set(OUTCOME_CONTRACTS[batch["agent_id"]]["required_source_ids"])
    refs = batch.get("receipt_refs_by_required_source_id")
    if not isinstance(refs, dict) or set(refs) != required_sources:
        raise ValueError("stored outcome source batch receipt coverage drift")
    receipts: dict[str, dict[str, Any]] = {}
    for source_id in sorted(required_sources):
        if refs[source_id].get("required_source_id") != source_id:
            raise ValueError(
                "stored outcome source batch receipt source-key binding drift"
            )
        receipt_row = _fetchone_mapping(
            conn,
            "SELECT * FROM outcome_source_receipts_v1 WHERE source_receipt_id = ?",
            (refs[source_id]["source_receipt_id"],),
        )
        if receipt_row is None:
            raise ValueError("stored outcome source batch receipt is unavailable")
        receipt = _read_receipt(receipt_row, entries=entries, pins=pins)
        if _receipt_ref(receipt) != refs[source_id]:
            raise ValueError("stored outcome source batch receipt reference drift")
        attestation = receipt["signed_attestation"]
        if attestation.get("required_source_id") != source_id:
            raise ValueError(
                "stored outcome source batch receipt attestation source drift"
            )
        expected_context = {
            field: batch[field]
            for field in (
                "scheduled_sample_id",
                "outcome_schedule_slot_id",
                "outcome_schedule_slot_hash",
                "evaluation_opportunity_set_id",
                "evaluation_opportunity_set_hash",
                "accepted_output_id",
                "accepted_output_hash",
                "track_key_hash",
                "agent_id",
                "opportunity_as_of",
                "outcome_due_at",
                "realized_metric_schema_id",
            )
        }
        if any(attestation.get(field) != value for field, value in expected_context.items()):
            raise ValueError("stored outcome source batch cross-sample binding drift")
        receipts[source_id] = receipt
    rebuilt = _build_batch(
        context={
            field: batch[field]
            for field in (
                "scheduled_sample_id",
                "outcome_schedule_slot_id",
                "outcome_schedule_slot_hash",
                "evaluation_opportunity_set_id",
                "evaluation_opportunity_set_hash",
                "accepted_output_id",
                "accepted_output_hash",
                "track_key_hash",
                "agent_id",
                "opportunity_as_of",
                "outcome_due_at",
                "realized_metric_schema_id",
            )
        },
        receipts=receipts,
        entries=entries,
        pins=pins,
        sealed_at=batch["sealed_at"],
    )
    if rebuilt != batch:
        raise ValueError("stored outcome source batch deterministic assembly drift")
    if cutoff_at is not None:
        cutoff = _timestamp(cutoff_at, "cutoff_at")
        due = _timestamp(batch["outcome_due_at"], "outcome_due_at")
        observed = _timestamp(batch["observed_through_at"], "observed_through_at")
        released = _timestamp(batch["released_at"], "released_at")
        vintage = _timestamp(batch["vintage_at"], "vintage_at")
        verified = _timestamp(batch["verified_at"], "verified_at")
        ingested = _timestamp(batch["ingested_at"], "ingested_at")
        sealed = _timestamp(batch["sealed_at"], "sealed_at")
        if not due <= observed <= released <= vintage <= verified <= ingested <= sealed <= cutoff:
            raise ValueError(
                "outcome source batch violates due/observed/released/vintage/"
                "verified/ingested/sealed/cutoff PIT ordering"
            )
    return batch


def load_server_selected_outcome_source_batch(
    conn: sqlite3.Connection,
    *,
    scheduled_sample_id: str,
    projection_source_batch_id: str,
    projection_source_batch_hash: str,
    projection_source_authority_registry_hash: str,
    projection_source_authority_registry_schema_hash: str,
    projection_source_receipt_schema_hash: str,
    projection_source_batch_schema_hash: str,
    cutoff_at: str,
) -> dict[str, Any]:
    """Resolve the sole sealed batch selected by the public store for a sample."""
    row = _fetchone_mapping(
        conn,
        "SELECT * FROM outcome_source_batches_v1 WHERE scheduled_sample_id = ?",
        (_required_text(scheduled_sample_id, "scheduled_sample_id"),),
    )
    if row is None:
        raise OutcomeSourceBatchUnavailable(
            "required sealed outcome source batch is unavailable"
        )
    batch = _read_batch(
        conn,
        row,
        cutoff_at=cutoff_at,
    )
    if (
        batch["source_batch_id"]
        != _required_text(projection_source_batch_id, "projection_source_batch_id")
        or batch["source_batch_hash"]
        != _required_sha256(
            projection_source_batch_hash,
            "projection_source_batch_hash",
        )
    ):
        raise ValueError("projection does not reference the server-selected source batch")
    projection_pins = {
        "authority_registry_hash": projection_source_authority_registry_hash,
        "authority_registry_schema_hash": (
            projection_source_authority_registry_schema_hash
        ),
        "receipt_schema_hash": projection_source_receipt_schema_hash,
        "batch_schema_hash": projection_source_batch_schema_hash,
    }
    for field, value in projection_pins.items():
        if batch[field] != _required_sha256(value, f"projection_{field}"):
            raise ValueError(
                "projection source authority pins do not match the "
                "server-selected historical source batch"
            )
    return batch


__all__ = [
    "AUTHORITY_REGISTRY_VERSION",
    "OUTCOME_SOURCE_AUTHORITY_REGISTRY_PATH",
    "OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH",
    "OUTCOME_SOURCE_BATCH_SCHEMA_PATH",
    "OUTCOME_SOURCE_RECEIPT_SCHEMA_PATH",
    "OutcomeSourceBatchUnavailable",
    "SOURCE_ATTESTATION_SCHEMA_VERSION",
    "SOURCE_BATCH_SCHEMA_VERSION",
    "SOURCE_RECEIPT_SCHEMA_VERSION",
    "SOURCE_SIGNATURE_DOMAIN",
    "append_and_seal_outcome_source_batch",
    "build_outcome_source_attestation",
    "load_outcome_source_authority_registry",
    "load_server_selected_outcome_source_batch",
    "outcome_source_attestation_signing_bytes",
    "outcome_source_authority_pins",
]

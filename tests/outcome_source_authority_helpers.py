from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_source_receipts import (
    OUTCOME_SOURCE_AUTHORITY_REGISTRY_PATH,
    OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH,
    append_and_seal_outcome_source_batch,
    build_outcome_source_attestation,
    outcome_source_attestation_signing_bytes,
    outcome_source_authority_pins,
)


@dataclass(frozen=True)
class EphemeralOutcomeSourceAuthority:
    registry_path: Path
    private_keys: Mapping[str, Ed25519PrivateKey]


def provision_test_outcome_source_authority(
    tmp_path: Path,
    monkeypatch: Any,
) -> EphemeralOutcomeSourceAuthority:
    """Generate an ephemeral active trust root; no private key reaches disk."""
    registry = json.loads(
        OUTCOME_SOURCE_AUTHORITY_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    registry["provisioning_status"] = "ACTIVE"
    private_keys: dict[str, Ed25519PrivateKey] = {}
    for entry in registry["entries"]:
        source_id = str(entry["required_source_id"])
        private_key = Ed25519PrivateKey.generate()
        public_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        entry["ed25519_public_key_base64url"] = (
            base64.urlsafe_b64encode(public_bytes).decode("ascii").rstrip("=")
        )
        entry["entry_hash"] = canonical_hash(
            {key: value for key, value in entry.items() if key != "entry_hash"}
        )
        private_keys[source_id] = private_key
    registry["registry_schema_hash"] = canonical_hash(
        json.loads(
            OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH.read_text(
                encoding="utf-8"
            )
        )
    )
    registry["registry_hash"] = canonical_hash(
        {key: value for key, value in registry.items() if key != "registry_hash"}
    )
    registry_index = len(
        tuple(tmp_path.glob("active-outcome-source-authority-registry-*.json"))
    )
    registry_path = (
        tmp_path
        / f"active-outcome-source-authority-registry-{registry_index}.json"
    )
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    import mosaic.scorecard.outcome_source_receipts as source_authority

    monkeypatch.setattr(
        source_authority,
        "OUTCOME_SOURCE_AUTHORITY_REGISTRY_PATH",
        registry_path,
    )
    return EphemeralOutcomeSourceAuthority(registry_path, private_keys)


def authority_projection_pins(
    authority: EphemeralOutcomeSourceAuthority,
) -> dict[str, str]:
    return outcome_source_authority_pins(
        authority.registry_path,
        OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH,
    )


def seal_test_outcome_source_batch(
    conn: sqlite3.Connection,
    *,
    authority: EphemeralOutcomeSourceAuthority,
    evaluation_context: Mapping[str, Any],
    realized_metrics: Mapping[str, Any],
    at: str,
    projection_status: str = "SCORE",
    abstain_reason: str | None = None,
) -> dict[str, Any]:
    # Production sealing owns its BEGIN IMMEDIATE transaction.  Test setup
    # commonly prepares the immutable sample on the same connection, so make
    # that setup durable before crossing the public transaction boundary.
    if conn.in_transaction:
        conn.commit()
    envelopes = build_test_outcome_source_attestations(
        authority=authority,
        evaluation_context=evaluation_context,
        realized_metrics=realized_metrics,
        at=at,
        projection_status=projection_status,
        abstain_reason=abstain_reason,
    )
    with patch(
        "mosaic.scorecard.outcome_source_receipts._server_now",
        return_value=datetime.fromisoformat(at),
    ):
        return append_and_seal_outcome_source_batch(
            conn,
            evaluation_opportunity_set_id=str(
                evaluation_context["evaluation_opportunity_set_id"]
            ),
            signed_attestations=envelopes,
        )


def build_test_outcome_source_attestations(
    *,
    authority: EphemeralOutcomeSourceAuthority,
    evaluation_context: Mapping[str, Any],
    realized_metrics: Mapping[str, Any],
    at: str,
    projection_status: str = "SCORE",
    abstain_reason: str | None = None,
) -> list[dict[str, Any]]:
    registry = json.loads(authority.registry_path.read_text(encoding="utf-8"))
    entries = {
        str(entry["required_source_id"]): entry for entry in registry["entries"]
    }
    agent_id = str(evaluation_context["agent_id"])
    schema_id = str(evaluation_context["realized_metric_schema_id"])
    from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS

    envelopes: list[dict[str, Any]] = []
    for source_id in OUTCOME_CONTRACTS[agent_id]["required_source_ids"]:
        owned_fields = entries[source_id]["owned_realized_fields_by_schema_id"][
            schema_id
        ]
        observation = (
            {field: realized_metrics[field] for field in owned_fields}
            if projection_status == "SCORE"
            else {}
        )
        attestation = build_outcome_source_attestation(
            evaluation_context=evaluation_context,
            required_source_id=source_id,
            source_observation=observation,
            evidence_artifact_hashes=[
                canonical_hash(
                    {
                        "scheduled_sample_id": evaluation_context[
                            "scheduled_sample_id"
                        ],
                        "required_source_id": source_id,
                    }
                )
            ],
            observed_through_at=at,
            released_at=at,
            vintage_at=at,
            verified_at=at,
            projection_status=projection_status,
            abstain_reason=abstain_reason,
            registry_path=authority.registry_path,
            registry_schema_path=OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH,
        )
        signature = authority.private_keys[source_id].sign(
            outcome_source_attestation_signing_bytes(attestation)
        )
        envelopes.append(
            {
                "attestation": attestation,
                "detached_signature_base64url": base64.urlsafe_b64encode(signature)
                .decode("ascii")
                .rstrip("="),
            }
        )
    return envelopes


def resign_test_outcome_source_attestation(
    authority: EphemeralOutcomeSourceAuthority,
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    attestation = dict(envelope["attestation"])
    source_id = str(attestation["required_source_id"])
    signature = authority.private_keys[source_id].sign(
        outcome_source_attestation_signing_bytes(attestation)
    )
    return {
        "attestation": attestation,
        "detached_signature_base64url": base64.urlsafe_b64encode(signature)
        .decode("ascii")
        .rstrip("="),
    }

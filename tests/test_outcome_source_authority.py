from __future__ import annotations

import base64
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from inspect import signature
from pathlib import Path
from threading import Event
from typing import Callable
from unittest.mock import patch

import pytest

from mosaic.dataflows.outcome_runtime_inputs import (
    OUTCOME_PROJECTION_SCHEMA_VERSION,
    load_realized_outcome_projection,
)
from mosaic.scorecard.darwinian_updates import (
    append_outcome_eligibility_revision,
    materialize_due_outcomes,
)
from mosaic.scorecard.darwinian_v2 import canonical_hash, deterministic_id
from mosaic.scorecard.outcome_contracts import (
    OUTCOME_CONTRACTS,
    OUTCOME_METRIC_SCHEMAS_HASH,
    OUTCOME_PROJECTION_SCHEMA_HASH,
    OUTCOME_REALIZED_METRIC_SCHEMAS_HASH,
    OUTCOME_REGISTRY_HASH,
)
from mosaic.scorecard.outcome_source_receipts import (
    OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH,
    append_and_seal_outcome_source_batch,
    build_outcome_source_attestation,
    load_outcome_source_authority_registry,
    load_server_selected_outcome_source_batch,
    outcome_source_attestation_signing_bytes,
)
from mosaic.scorecard.store import ScorecardStore
from tests.outcome_source_authority_helpers import (
    EphemeralOutcomeSourceAuthority,
    authority_projection_pins,
    build_test_outcome_source_attestations,
    provision_test_outcome_source_authority,
    resign_test_outcome_source_attestation,
)
from tests.test_darwinian_outcome_maturation import (
    CUTOFF_AT,
    _bindings,
    _realized_metrics,
    _seed_pending,
    _track_by_agent,
    _trading_dates,
)


def _prepared_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    ScorecardStore,
    dict,
    dict,
    dict,
    EphemeralOutcomeSourceAuthority,
]:
    authority = provision_test_outcome_source_authority(tmp_path, monkeypatch)
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-05-01T15:00:00+08:00",
    )
    with store._connect() as conn:
        track_hash = _track_by_agent(conn, revision)["china"]
        slot, opportunity, pending = _seed_pending(
            conn,
            revision=revision,
            tracks={"china": track_hash},
            agent_id="china",
        )
    contract = OUTCOME_CONTRACTS["china"]
    context = {
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "accepted_output_id": pending["accepted_output_id"],
        "accepted_output_hash": pending["accepted_output_hash"],
        "track_key_hash": track_hash,
        "agent_id": "china",
        "opportunity_as_of": opportunity["as_of"],
        "outcome_due_at": slot["outcome_due_at"],
        "realized_metric_schema_id": contract["realized_metric_schema_id"],
    }
    return store, revision, context, pending, authority


def _pending_context_for_agent(
    store: ScorecardStore,
    revision: dict,
    agent_id: str,
) -> dict:
    with store._connect() as conn:
        track_hash = _track_by_agent(conn, revision)[agent_id]
        slot, opportunity, pending = _seed_pending(
            conn,
            revision=revision,
            tracks={agent_id: track_hash},
            agent_id=agent_id,
        )
    return {
        "scheduled_sample_id": slot["scheduled_sample_id"],
        "outcome_schedule_slot_id": slot["outcome_schedule_slot_id"],
        "outcome_schedule_slot_hash": slot["outcome_schedule_slot_hash"],
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "accepted_output_id": pending["accepted_output_id"],
        "accepted_output_hash": pending["accepted_output_hash"],
        "track_key_hash": track_hash,
        "agent_id": agent_id,
        "opportunity_as_of": opportunity["as_of"],
        "outcome_due_at": slot["outcome_due_at"],
        "realized_metric_schema_id": OUTCOME_CONTRACTS[agent_id][
            "realized_metric_schema_id"
        ],
    }


def _rewrite_authority_registry(
    authority: EphemeralOutcomeSourceAuthority,
    mutate: Callable[[dict], None],
) -> None:
    registry = json.loads(authority.registry_path.read_text(encoding="utf-8"))
    mutate(registry)
    for entry in registry["entries"]:
        entry["entry_hash"] = canonical_hash(
            {key: value for key, value in entry.items() if key != "entry_hash"}
        )
    registry["registry_hash"] = canonical_hash(
        {key: value for key, value in registry.items() if key != "registry_hash"}
    )
    authority.registry_path.write_text(json.dumps(registry), encoding="utf-8")


def test_source_batch_append_api_has_no_caller_clock_parameter() -> None:
    parameters = signature(append_and_seal_outcome_source_batch).parameters
    assert "_server_clock" not in parameters
    assert "registry_path" not in parameters
    assert "registry_schema_path" not in parameters
    read_parameters = signature(
        load_server_selected_outcome_source_batch
    ).parameters
    assert "registry_path" not in read_parameters
    assert "registry_schema_path" not in read_parameters


def _signed_envelopes(
    context: dict,
    authority: EphemeralOutcomeSourceAuthority,
) -> list[dict]:
    return build_test_outcome_source_attestations(
        authority=authority,
        evaluation_context=context,
        realized_metrics=_realized_metrics(context["agent_id"]),
        at=CUTOFF_AT,
    )


def _append(
    conn: sqlite3.Connection,
    context: dict,
    envelopes: list[dict],
    authority: EphemeralOutcomeSourceAuthority,
    *,
    at: str = CUTOFF_AT,
) -> dict:
    with patch(
        "mosaic.scorecard.outcome_source_receipts._server_now",
        return_value=datetime.fromisoformat(at),
    ):
        return append_and_seal_outcome_source_batch(
            conn,
            evaluation_opportunity_set_id=context["evaluation_opportunity_set_id"],
            signed_attestations=envelopes,
        )


def _load_selected(
    conn: sqlite3.Connection,
    context: dict,
    batch: dict,
    authority: EphemeralOutcomeSourceAuthority,
    *,
    cutoff_at: str = CUTOFF_AT,
) -> dict:
    pins = authority_projection_pins(authority)
    return load_server_selected_outcome_source_batch(
        conn,
        scheduled_sample_id=context["scheduled_sample_id"],
        projection_source_batch_id=batch["source_batch_id"],
        projection_source_batch_hash=batch["source_batch_hash"],
        projection_source_authority_registry_hash=pins[
            "authority_registry_hash"
        ],
        projection_source_authority_registry_schema_hash=pins[
            "authority_registry_schema_hash"
        ],
        projection_source_receipt_schema_hash=pins["receipt_schema_hash"],
        projection_source_batch_schema_hash=pins["batch_schema_hash"],
        cutoff_at=cutoff_at,
    )


def _assert_source_store_empty(conn: sqlite3.Connection) -> None:
    assert conn.execute(
        "SELECT COUNT(*) FROM outcome_source_authority_registry_history_v1"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM outcome_source_receipts_v1"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM outcome_source_batches_v1"
    ).fetchone()[0] == 0


def _assert_rejected_without_source_writes(
    store: ScorecardStore,
    context: dict,
    envelopes: list[dict],
    authority: EphemeralOutcomeSourceAuthority,
    *,
    match: str,
) -> None:
    with sqlite3.connect(store.db_path) as conn:
        with pytest.raises(ValueError, match=match):
            _append(conn, context, envelopes, authority)
        _assert_source_store_empty(conn)


def test_public_authority_registry_is_exact_and_fail_closed_until_provisioned() -> None:
    registry = load_outcome_source_authority_registry()
    required_sources = {
        source_id
        for contract in OUTCOME_CONTRACTS.values()
        for source_id in contract["required_source_ids"]
    }
    assert registry["provisioning_status"] == "PROVISIONING_REQUIRED"
    assert {entry["required_source_id"] for entry in registry["entries"]} == (
        required_sources
    )
    serialized = json.dumps(registry).casefold()
    assert "private_key" not in serialized
    assert "private seed" not in serialized
    with pytest.raises(ValueError, match="provisioning is required"):
        build_outcome_source_attestation(
            evaluation_context={},
            required_source_id=next(iter(required_sources)),
            source_observation={},
            evidence_artifact_hashes=["sha256:" + "0" * 64],
            observed_through_at=CUTOFF_AT,
            released_at=CUTOFF_AT,
            vintage_at=CUTOFF_AT,
            verified_at=CUTOFF_AT,
        )


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ("signing_key_id", "signing_key_id values must be unique"),
        (
            "ed25519_public_key_base64url",
            "Ed25519 public keys must be unique",
        ),
    ],
)
def test_authority_registry_rejects_cross_source_key_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    error: str,
) -> None:
    authority = provision_test_outcome_source_authority(tmp_path, monkeypatch)

    def duplicate(registry: dict) -> None:
        registry["entries"][1][field] = registry["entries"][0][field]

    _rewrite_authority_registry(authority, duplicate)
    with pytest.raises(RuntimeError, match=error):
        load_outcome_source_authority_registry(
            authority.registry_path,
            OUTCOME_SOURCE_AUTHORITY_REGISTRY_SCHEMA_PATH,
        )


def test_signed_exact_batch_is_idempotent_with_default_tuple_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    envelopes = _signed_envelopes(context, authority)
    with sqlite3.connect(store.db_path) as conn:
        first = _append(conn, context, envelopes, authority)
    with sqlite3.connect(store.db_path) as conn:
        second = _append(conn, context, envelopes, authority)
        selected = _load_selected(conn, context, first, authority)
        assert conn.execute(
            "SELECT COUNT(*) FROM outcome_source_batches_v1"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM outcome_source_receipts_v1"
        ).fetchone()[0] == len(OUTCOME_CONTRACTS["china"]["required_source_ids"])
        assert all(
            source_id == reference["required_source_id"]
            for source_id, reference in first[
                "receipt_refs_by_required_source_id"
            ].items()
        )
    assert first == second == selected


def test_registry_rotation_preserves_old_batch_and_retires_old_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, revision, china_context, _, authority_a = _prepared_sample(
        tmp_path,
        monkeypatch,
    )
    china_envelopes = _signed_envelopes(china_context, authority_a)
    with sqlite3.connect(store.db_path) as conn:
        batch_a = _append(conn, china_context, china_envelopes, authority_a)

    authority_b = provision_test_outcome_source_authority(tmp_path, monkeypatch)
    with sqlite3.connect(store.db_path) as conn:
        assert _load_selected(conn, china_context, batch_a, authority_a) == batch_a

    us_context = _pending_context_for_agent(store, revision, "us_economy")
    current_envelopes = _signed_envelopes(us_context, authority_b)
    old_key_envelopes = copy.deepcopy(current_envelopes)
    for envelope in old_key_envelopes:
        source_id = envelope["attestation"]["required_source_id"]
        old_signature = authority_a.private_keys[source_id].sign(
            outcome_source_attestation_signing_bytes(envelope["attestation"])
        )
        envelope["detached_signature_base64url"] = (
            base64.urlsafe_b64encode(old_signature).decode("ascii").rstrip("=")
        )

    with sqlite3.connect(store.db_path) as conn:
        receipt_count = conn.execute(
            "SELECT COUNT(*) FROM outcome_source_receipts_v1"
        ).fetchone()[0]
        with pytest.raises(ValueError, match="Ed25519 signature"):
            _append(conn, us_context, old_key_envelopes, authority_b)
        assert conn.execute(
            "SELECT COUNT(*) FROM outcome_source_receipts_v1"
        ).fetchone()[0] == receipt_count

    with sqlite3.connect(store.db_path) as conn:
        batch_b = _append(conn, us_context, current_envelopes, authority_b)
        assert _load_selected(conn, us_context, batch_b, authority_b) == batch_b
        assert conn.execute(
            "SELECT COUNT(*) FROM outcome_source_authority_registry_history_v1"
        ).fetchone()[0] == 2


def test_old_projection_resolves_its_batch_pinned_registry_after_rotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "outcome-runtime"
    monkeypatch.setenv("MOSAIC_OUTCOME_RUNTIME_DIR", str(runtime_root))
    store, _, context, _, authority_a = _prepared_sample(tmp_path, monkeypatch)
    with sqlite3.connect(store.db_path) as conn:
        batch = _append(
            conn,
            context,
            _signed_envelopes(context, authority_a),
            authority_a,
        )
    contract = OUTCOME_CONTRACTS[context["agent_id"]]
    pins = authority_projection_pins(authority_a)
    without_hash = {
        "schema_version": OUTCOME_PROJECTION_SCHEMA_VERSION,
        **context,
        "metric_family": contract["metric_family"],
        "metric_schema_id": contract["metric_schema_id"],
        "outcome_registry_hash": OUTCOME_REGISTRY_HASH,
        "metric_schemas_hash": OUTCOME_METRIC_SCHEMAS_HASH,
        "realized_metric_schemas_hash": OUTCOME_REALIZED_METRIC_SCHEMAS_HASH,
        "outcome_projection_schema_hash": OUTCOME_PROJECTION_SCHEMA_HASH,
        "source_authority_registry_hash": pins["authority_registry_hash"],
        "source_authority_registry_schema_hash": pins[
            "authority_registry_schema_hash"
        ],
        "source_receipt_schema_hash": pins["receipt_schema_hash"],
        "source_batch_schema_hash": pins["batch_schema_hash"],
        "generated_at": CUTOFF_AT,
        "pit_status": "VERIFIED",
        "source_batch_id": batch["source_batch_id"],
        "source_batch_hash": batch["source_batch_hash"],
    }
    projection = {
        **without_hash,
        "snapshot_hash": canonical_hash(without_hash),
    }
    projection_path = (
        runtime_root
        / context["outcome_due_at"][:10]
        / "realized_outcomes"
        / f"{context['scheduled_sample_id']}.json"
    )
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path.write_text(json.dumps(projection), encoding="utf-8")

    provision_test_outcome_source_authority(tmp_path, monkeypatch)
    loaded = load_realized_outcome_projection(
        scheduled_sample_id=context["scheduled_sample_id"],
        outcome_schedule_slot_id=context["outcome_schedule_slot_id"],
        outcome_schedule_slot_hash=context["outcome_schedule_slot_hash"],
        evaluation_opportunity_set_id=context["evaluation_opportunity_set_id"],
        evaluation_opportunity_set_hash=context[
            "evaluation_opportunity_set_hash"
        ],
        accepted_output_id=context["accepted_output_id"],
        accepted_output_hash=context["accepted_output_hash"],
        track_key_hash=context["track_key_hash"],
        agent_id=context["agent_id"],
        opportunity_as_of=context["opportunity_as_of"],
        outcome_due_at=context["outcome_due_at"],
        cutoff_at=CUTOFF_AT,
    )
    with sqlite3.connect(store.db_path) as conn:
        selected = load_server_selected_outcome_source_batch(
            conn,
            scheduled_sample_id=context["scheduled_sample_id"],
            projection_source_batch_id=loaded["source_batch_id"],
            projection_source_batch_hash=loaded["source_batch_hash"],
            projection_source_authority_registry_hash=loaded[
                "source_authority_registry_hash"
            ],
            projection_source_authority_registry_schema_hash=loaded[
                "source_authority_registry_schema_hash"
            ],
            projection_source_receipt_schema_hash=loaded[
                "source_receipt_schema_hash"
            ],
            projection_source_batch_schema_hash=loaded[
                "source_batch_schema_hash"
            ],
            cutoff_at=CUTOFF_AT,
        )
    assert selected == batch


@pytest.mark.parametrize("history_mutation", ["missing", "tampered"])
def test_historical_registry_snapshot_missing_or_tampered_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    history_mutation: str,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    with sqlite3.connect(store.db_path) as conn:
        batch = _append(conn, context, _signed_envelopes(context, authority), authority)
        if history_mutation == "missing":
            conn.execute(
                "DROP TRIGGER "
                "no_delete_outcome_source_authority_registry_history_v1"
            )
            conn.execute(
                "DELETE FROM outcome_source_authority_registry_history_v1"
            )
            error = "registry history is unavailable"
        else:
            conn.execute(
                "DROP TRIGGER "
                "no_update_outcome_source_authority_registry_history_v1"
            )
            conn.execute(
                "UPDATE outcome_source_authority_registry_history_v1 "
                "SET record_json = ?",
                ("{}",),
            )
            error = "registry history fields drift"
        with pytest.raises(ValueError, match=error):
            _load_selected(conn, context, batch, authority)


def test_invalid_signature_missing_source_and_pit_order_insert_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    original = _signed_envelopes(context, authority)
    cases: list[tuple[list[dict], str]] = []
    forged = copy.deepcopy(original)
    forged[0]["attestation"]["evidence_artifact_hashes"] = [
        "sha256:" + "f" * 64
    ]
    cases.append((forged, "Ed25519 signature"))
    cases.append((copy.deepcopy(original[:-1]), "exact required sources"))
    bad_pit = copy.deepcopy(original)
    bad_pit[0]["attestation"]["observed_through_at"] = (
        "2026-07-17T14:59:59+08:00"
    )
    bad_pit[0] = resign_test_outcome_source_attestation(authority, bad_pit[0])
    cases.append((bad_pit, "PIT order"))
    for envelopes, error in cases:
        _assert_rejected_without_source_writes(
            store,
            context,
            envelopes,
            authority,
            match=error,
        )
    with sqlite3.connect(store.db_path) as conn:
        _assert_source_store_empty(conn)


def test_signing_key_window_is_checked_at_server_ingest_not_signer_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)

    def expire_before_ingest(registry: dict) -> None:
        for entry in registry["entries"]:
            entry["effective_until"] = "2026-07-17T15:00:30+08:00"

    _rewrite_authority_registry(authority, expire_before_ingest)
    envelopes = _signed_envelopes(context, authority)
    with sqlite3.connect(store.db_path) as conn, pytest.raises(
        ValueError,
        match="outside its effective window",
    ):
        _append(
            conn,
            context,
            envelopes,
            authority,
            at="2026-07-17T15:01:00+08:00",
        )
    with sqlite3.connect(store.db_path) as conn:
        _assert_source_store_empty(conn)


def test_new_key_may_authorize_a_historical_release_at_current_ingest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)

    def activate_after_release(registry: dict) -> None:
        for entry in registry["entries"]:
            entry["effective_from"] = "2026-07-17T15:00:30+08:00"

    _rewrite_authority_registry(authority, activate_after_release)
    envelopes = _signed_envelopes(context, authority)
    with sqlite3.connect(store.db_path) as conn:
        batch = _append(
            conn,
            context,
            envelopes,
            authority,
            at="2026-07-17T15:01:00+08:00",
        )
        assert batch["released_at"] == CUTOFF_AT
        assert batch["ingested_at"] == "2026-07-17T15:01:00+08:00"


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_source_observation_is_rejected_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    nonfinite: float,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    forged = _signed_envelopes(context, authority)
    target = next(
        envelope
        for envelope in forged
        if envelope["attestation"]["source_observation"]
    )
    field = next(iter(target["attestation"]["source_observation"]))
    target["attestation"]["source_observation"][field] = nonfinite
    with pytest.raises(ValueError):
        canonical_hash({"nonfinite": nonfinite})
    _assert_rejected_without_source_writes(
        store,
        context,
        forged,
        authority,
        match="non-finite number",
    )


def test_registry_identity_fields_are_not_caller_or_signer_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    original = _signed_envelopes(context, authority)
    for field in (
        "source_owner",
        "adapter_contract_id",
        "adapter_contract_version",
        "verifier_id",
        "signing_key_id",
    ):
        forged = copy.deepcopy(original)
        forged[0]["attestation"][field] = f"forged.{field}"
        forged[0] = resign_test_outcome_source_attestation(authority, forged[0])
        _assert_rejected_without_source_writes(
            store,
            context,
            forged,
            authority,
            match=rf"{field} is not registry-owned",
        )


def test_another_enrolled_source_key_cannot_sign_for_its_peer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    forged = _signed_envelopes(context, authority)
    source_id = str(forged[0]["attestation"]["required_source_id"])
    other_source_id = next(
        candidate for candidate in authority.private_keys if candidate != source_id
    )
    signature = authority.private_keys[other_source_id].sign(
        outcome_source_attestation_signing_bytes(forged[0]["attestation"])
    )
    forged[0]["detached_signature_base64url"] = (
        base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    )
    _assert_rejected_without_source_writes(
        store,
        context,
        forged,
        authority,
        match="Ed25519 signature",
    )


def test_signed_attestation_cannot_be_replayed_across_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    replayed = _signed_envelopes(context, authority)
    for index, envelope in enumerate(replayed):
        envelope["attestation"]["scheduled_sample_id"] = (
            "maturity-sample:china:cross-sample-replay"
        )
        replayed[index] = resign_test_outcome_source_attestation(
            authority,
            envelope,
        )
    _assert_rejected_without_source_writes(
        store,
        context,
        replayed,
        authority,
        match="scheduled_sample_id drift",
    )


def test_resigned_observation_field_escalation_and_omission_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    original = _signed_envelopes(context, authority)
    target = next(
        index
        for index, envelope in enumerate(original)
        if envelope["attestation"]["source_observation"]
    )
    owned_field = next(
        iter(original[target]["attestation"]["source_observation"])
    )

    missing = copy.deepcopy(original)
    missing[target]["attestation"]["source_observation"].pop(owned_field)
    missing[target] = resign_test_outcome_source_attestation(
        authority,
        missing[target],
    )
    _assert_rejected_without_source_writes(
        store,
        context,
        missing,
        authority,
        match="observation field ownership drift",
    )

    escalated = copy.deepcopy(original)
    escalated[target]["attestation"]["source_observation"][
        "field_not_owned_by_source"
    ] = 0
    escalated[target] = resign_test_outcome_source_attestation(
        authority,
        escalated[target],
    )
    _assert_rejected_without_source_writes(
        store,
        context,
        escalated,
        authority,
        match="observation field ownership drift",
    )


def test_resigned_noncanonical_evidence_hash_set_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    forged = _signed_envelopes(context, authority)
    evidence_hash = forged[0]["attestation"]["evidence_artifact_hashes"][0]
    forged[0]["attestation"]["evidence_artifact_hashes"] = [
        evidence_hash,
        evidence_hash,
    ]
    forged[0] = resign_test_outcome_source_attestation(authority, forged[0])
    _assert_rejected_without_source_writes(
        store,
        context,
        forged,
        authority,
        match="evidence artifact hashes are not canonical",
    )


def test_conflicting_vintage_is_rejected_but_concurrent_exact_retry_converges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    envelopes = _signed_envelopes(context, authority)

    def seal() -> dict:
        with sqlite3.connect(store.db_path, timeout=10) as conn:
            return _append(conn, context, envelopes, authority)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: seal(), range(2)))
    assert results[0] == results[1]
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM outcome_source_batches_v1"
        ).fetchone()[0] == 1

    conflicting = copy.deepcopy(envelopes)
    conflicting[0]["attestation"]["vintage_at"] = "2026-07-17T15:01:00+08:00"
    conflicting[0]["attestation"]["verified_at"] = "2026-07-17T15:01:00+08:00"
    conflicting[0] = resign_test_outcome_source_attestation(
        authority,
        conflicting[0],
    )
    with sqlite3.connect(store.db_path) as conn, pytest.raises(
        ValueError,
        match="conflicting outcome source receipt vintage",
    ):
        _append(
            conn,
            context,
            conflicting,
            authority,
            at="2026-07-17T15:01:00+08:00",
        )


def test_superseded_pending_revision_cannot_be_sealed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, pending, authority = _prepared_sample(tmp_path, monkeypatch)
    envelopes = _signed_envelopes(context, authority)
    with store._connect() as conn:
        append_outcome_eligibility_revision(
            conn,
            track_key_hash=context["track_key_hash"],
            scheduled_sample_id=context["scheduled_sample_id"],
            sample_origin="PRODUCTION_ACTIVE",
            disposition="EXOGENOUS_EXCLUSION",
            recorded_at=CUTOFF_AT,
            evaluation_opportunity_set_id=context["evaluation_opportunity_set_id"],
            accepted_output_id=pending["accepted_output_id"],
            exclusion_or_failure_reason="TEST_SUPERSEDE_BEFORE_SEAL",
        )
    with sqlite3.connect(store.db_path) as conn, pytest.raises(
        ValueError,
        match="PENDING revision",
    ):
        _append(conn, context, envelopes, authority)
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM outcome_source_batches_v1"
        ).fetchone()[0] == 0


def test_server_clock_is_sampled_only_after_begin_immediate_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    envelopes = _signed_envelopes(context, authority)
    lock_attempted = Event()
    release_blocker = Event()
    clock_states: list[bool] = []
    late_at = "2026-07-17T15:01:00+08:00"

    def server_clock() -> datetime:
        clock_states.append(release_blocker.is_set())
        return datetime.fromisoformat(late_at)

    def seal_after_lock() -> dict:
        with sqlite3.connect(store.db_path, timeout=10) as conn:
            conn.set_trace_callback(
                lambda statement: (
                    lock_attempted.set()
                    if statement.strip().upper() == "BEGIN IMMEDIATE"
                    else None
                )
            )
            return append_and_seal_outcome_source_batch(
                conn,
                evaluation_opportunity_set_id=context[
                    "evaluation_opportunity_set_id"
                ],
                signed_attestations=envelopes,
            )

    blocker = sqlite3.connect(store.db_path)
    blocker.execute("BEGIN IMMEDIATE")
    with patch(
        "mosaic.scorecard.outcome_source_receipts._server_now",
        side_effect=server_clock,
    ), ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(seal_after_lock)
        try:
            assert lock_attempted.wait(timeout=2)
            assert clock_states == []
        finally:
            release_blocker.set()
            blocker.commit()
            blocker.close()
        batch = future.result(timeout=10)

    assert clock_states == [True, True]
    assert batch["ingested_at"] == late_at
    assert batch["sealed_at"] == late_at


def test_caller_transaction_is_rejected_before_server_clock_sampling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    envelopes = _signed_envelopes(context, authority)
    clock_calls: list[None] = []

    def server_clock() -> datetime:
        clock_calls.append(None)
        return datetime.fromisoformat(CUTOFF_AT)

    with sqlite3.connect(store.db_path) as conn:
        conn.execute("BEGIN")
        conn.execute("SELECT 1").fetchone()
        with patch(
            "mosaic.scorecard.outcome_source_receipts._server_now",
            side_effect=server_clock,
        ), pytest.raises(ValueError, match="fresh transaction boundary"):
            append_and_seal_outcome_source_batch(
                conn,
                evaluation_opportunity_set_id=context[
                    "evaluation_opportunity_set_id"
                ],
                signed_attestations=envelopes,
            )
        assert clock_calls == []
        conn.rollback()
        _assert_source_store_empty(conn)


def test_late_server_ingest_cannot_be_backdated_before_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    envelopes = _signed_envelopes(context, authority)
    late_at = "2026-07-17T15:01:00+08:00"
    with sqlite3.connect(store.db_path) as conn:
        batch = _append(
            conn,
            context,
            envelopes,
            authority,
            at=late_at,
        )
        assert batch["ingested_at"] == late_at
        with pytest.raises(ValueError, match="PIT ordering"):
            _load_selected(
                conn,
                context,
                batch,
                authority,
                cutoff_at=CUTOFF_AT,
            )


def test_batch_read_revalidates_receipt_sqlite_mirror_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    envelopes = _signed_envelopes(context, authority)
    with sqlite3.connect(store.db_path) as conn:
        batch = _append(conn, context, envelopes, authority)
        conn.execute("DROP TRIGGER no_update_outcome_source_receipts_v1")
        conn.execute(
            "UPDATE outcome_source_receipts_v1 SET source_owner = ? "
            "WHERE source_receipt_id = ("
            "SELECT source_receipt_id FROM outcome_source_receipts_v1 LIMIT 1)",
            ("forged.sqlite.owner",),
        )
        with pytest.raises(ValueError, match="SQLite mirror drift"):
            _load_selected(conn, context, batch, authority)


def test_batch_receipt_reference_is_bound_to_its_source_map_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    with sqlite3.connect(store.db_path) as conn:
        batch = _append(conn, context, _signed_envelopes(context, authority), authority)
        stored_json = conn.execute(
            "SELECT record_json FROM outcome_source_batches_v1 "
            "WHERE source_batch_id = ?",
            (batch["source_batch_id"],),
        ).fetchone()[0]
        forged = json.loads(stored_json)
        source_ids = sorted(forged["receipt_refs_by_required_source_id"])
        forged["receipt_refs_by_required_source_id"][source_ids[0]][
            "required_source_id"
        ] = source_ids[1]
        identity = {
            "scheduled_sample_id": forged["scheduled_sample_id"],
            "evaluation_opportunity_set_hash": forged[
                "evaluation_opportunity_set_hash"
            ],
            "accepted_output_hash": forged["accepted_output_hash"],
            "authority_registry_hash": forged["authority_registry_hash"],
            "receipt_refs_by_required_source_id": forged[
                "receipt_refs_by_required_source_id"
            ],
            "projection_status": forged["projection_status"],
            "realized_metrics": forged["realized_metrics"],
        }
        forged["source_batch_id"] = deterministic_id(
            "outcome-source-batch",
            identity,
        )
        forged["source_batch_hash"] = canonical_hash(
            {
                key: value
                for key, value in forged.items()
                if key != "source_batch_hash"
            }
        )
        conn.execute("DROP TRIGGER no_update_outcome_source_batches_v1")
        conn.execute(
            "UPDATE outcome_source_batches_v1 SET source_batch_id = ?, "
            "source_batch_hash = ?, record_json = ?",
            (
                forged["source_batch_id"],
                forged["source_batch_hash"],
                json.dumps(forged),
            ),
        )
        with pytest.raises(ValueError, match="source-key binding drift"):
            _load_selected(conn, context, batch, authority)


def test_projection_without_server_batch_remains_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "outcome-runtime"
    monkeypatch.setenv("MOSAIC_OUTCOME_RUNTIME_DIR", str(runtime_root))
    store, revision, context, _, authority = _prepared_sample(tmp_path, monkeypatch)
    contract = OUTCOME_CONTRACTS["china"]
    pins = authority_projection_pins(authority)
    payload = {
        "schema_version": OUTCOME_PROJECTION_SCHEMA_VERSION,
        **context,
        "metric_family": contract["metric_family"],
        "metric_schema_id": contract["metric_schema_id"],
        "outcome_registry_hash": OUTCOME_REGISTRY_HASH,
        "metric_schemas_hash": OUTCOME_METRIC_SCHEMAS_HASH,
        "realized_metric_schemas_hash": OUTCOME_REALIZED_METRIC_SCHEMAS_HASH,
        "outcome_projection_schema_hash": OUTCOME_PROJECTION_SCHEMA_HASH,
        "source_authority_registry_hash": pins["authority_registry_hash"],
        "source_authority_registry_schema_hash": pins[
            "authority_registry_schema_hash"
        ],
        "source_receipt_schema_hash": pins["receipt_schema_hash"],
        "source_batch_schema_hash": pins["batch_schema_hash"],
        "generated_at": CUTOFF_AT,
        "pit_status": "VERIFIED",
        "source_batch_id": "outcome-source-batch:not-yet-sealed",
        "source_batch_hash": "sha256:" + "e" * 64,
    }
    body = {key: value for key, value in payload.items() if key != "snapshot_hash"}
    record = {**body, "snapshot_hash": canonical_hash(body)}
    path = (
        runtime_root
        / context["outcome_due_at"][:10]
        / "realized_outcomes"
        / f"{context['scheduled_sample_id']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")

    with store._connect() as conn:
        result = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            cutoff_at=CUTOFF_AT,
            trading_dates=_trading_dates(),
        )
    assert result["unresolved_count"] == 1
    assert result["results"][0]["failure_code"] == (
        "REQUIRED_OUTCOME_SOURCE_BATCH_UNAVAILABLE"
    )

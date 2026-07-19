from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.geopolitical_events import (
    ALL_SOURCE_IDS,
    EVENT_TYPES,
    GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    OPTIONAL_SOURCE_IDS,
    REQUIRED_SOURCE_IDS,
    WATCHLIST_ACTORS,
    WATCHLIST_REGIONS,
    GeopoliticalEventStore,
    build_geopolitical_events_snapshot,
    coverage_query_key,
    runtime_geopolitical_manifest,
    scope_query_hash,
    validate_event_revision,
    validate_geopolitical_manifest,
)


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def rehash_manifest(payload: dict) -> dict:
    payload["coverage_scope_hash"] = canonical_hash(
        {
            "coverage_scope_version": payload["coverage_scope_version"],
            "watchlist_actor_ids": payload["watchlist_actor_ids"],
            "watchlist_region_ids": payload["watchlist_region_ids"],
            "coverage_routes": payload["coverage_routes"],
        }
    )
    without_hash = {
        key: value for key, value in payload.items() if key != "manifest_hash"
    }
    payload["manifest_hash"] = canonical_hash(without_hash)
    return payload


def preflight_complete_manifest() -> dict:
    payload = copy.deepcopy(GEOPOLITICAL_INITIAL_SOURCE_MANIFEST)
    for row in payload["registrations"]:
        if row["source_id"] in REQUIRED_SOURCE_IDS:
            row["registration_status"] = "ACTIVE_VERIFIED"
            row["preflight"] = {
                **row["preflight"],
                "status": "READY",
                "observed_continuous_days": 30,
                "window_started_at": "2026-06-17T00:00:00Z",
                "window_completed_at": "2026-07-17T00:00:00Z",
                "availability_ratio": 0.999,
                "p95_capture_lag_minutes": 12.0,
                "schema_verified": True,
                "pagination_verified": True,
                "publication_time_verified": True,
                "license_verified": True,
                "evidence_id": f"geo-preflight:{row['source_id']}:synthetic-ready",
            }
    for route in payload["coverage_routes"]:
        if route["applicability"] == "APPLICABLE":
            route["route_status"] = "ACTIVE_VERIFIED"
            without_hash = {
                key: value
                for key, value in route.items()
                if key != "coverage_route_hash"
            }
            route["coverage_route_hash"] = canonical_hash(without_hash)
    payload["manifest_readiness"] = "PREFLIGHT_REQUIRED"
    payload["readiness_blockers"] = [
        f"{source_id}:{reason}"
        for source_id in sorted(REQUIRED_SOURCE_IDS)
        for reason in (
            "source_specific_parser_missing",
            "continuous_preflight_receipt_verifier_missing",
        )
    ]
    return validate_geopolitical_manifest(rehash_manifest(payload))


def test_initial_manifest_is_exact_and_truthfully_fail_closed():
    manifest = GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    assert set(row["source_id"] for row in manifest["registrations"]) == ALL_SOURCE_IDS
    assert set(
        row["source_id"] for row in manifest["registrations"] if row["required"]
    ) == (REQUIRED_SOURCE_IDS)
    assert set(
        row["source_id"] for row in manifest["registrations"] if not row["required"]
    ) == (OPTIONAL_SOURCE_IDS)
    assert tuple(manifest["active_event_types"]) == EVENT_TYPES
    assert tuple(manifest["watchlist_actor_ids"]) == WATCHLIST_ACTORS
    assert tuple(manifest["watchlist_region_ids"]) == WATCHLIST_REGIONS
    assert len(manifest["coverage_routes"]) == len(EVENT_TYPES) * (
        len(WATCHLIST_ACTORS) + len(WATCHLIST_REGIONS) + 1
    )
    assert manifest["manifest_readiness"] == "PREFLIGHT_REQUIRED"
    assert all(
        row["preflight"]["observed_continuous_days"] == 0
        for row in manifest["registrations"]
    )
    assert set(manifest["readiness_blockers"]) == {
        f"{source_id}:{reason}"
        for source_id in REQUIRED_SOURCE_IDS
        for reason in (
            "30_day_preflight_required",
            "source_specific_parser_missing",
            "continuous_preflight_receipt_verifier_missing",
        )
    }


def test_runtime_manifest_override_is_explicit_and_fully_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = preflight_complete_manifest()
    path = tmp_path / "private-ready-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST", str(path))

    assert (
        runtime_geopolitical_manifest()["manifest_readiness"]
        == "PREFLIGHT_REQUIRED"
    )

    falsely_promoted = copy.deepcopy(manifest)
    falsely_promoted["manifest_readiness"] = "READY"
    falsely_promoted["readiness_blockers"] = []
    path.write_text(json.dumps(rehash_manifest(falsely_promoted)), encoding="utf-8")
    with pytest.raises(DataVendorUnavailable, match="readiness blockers mismatch"):
        runtime_geopolitical_manifest()

    path.write_text("{}", encoding="utf-8")
    with pytest.raises(DataVendorUnavailable, match="schema version mismatch"):
        runtime_geopolitical_manifest()


def test_manifest_rejects_hash_drift_and_tushare_permission_copy():
    bad = copy.deepcopy(GEOPOLITICAL_INITIAL_SOURCE_MANIFEST)
    bad["watchlist_actor_ids"].append("UNREGISTERED")
    with pytest.raises(DataVendorUnavailable, match="manifest hash mismatch"):
        validate_geopolitical_manifest(bad)

    bad = copy.deepcopy(GEOPOLITICAL_INITIAL_SOURCE_MANIFEST)
    bad["registrations"][0]["source_backend"] = "TUSHARE"
    bad["registrations"][0]["tushare_endpoint_id"] = "major_news"
    rehash_manifest(bad)
    with pytest.raises(DataVendorUnavailable, match="cannot copy Tushare"):
        validate_geopolitical_manifest(bad)


def make_poll(route: dict, source_id: str, adapter: dict, ordinal: int) -> dict:
    query_hash = scope_query_hash(route, adapter)
    query_key = coverage_query_key(route, source_id, query_hash)
    return {
        "observation_id": f"poll-{ordinal:04d}",
        "coverage_route_id": route["coverage_route_id"],
        "coverage_route_hash": route["coverage_route_hash"],
        "source_id": source_id,
        "scope_query_hash": query_hash,
        "coverage_query_key": query_key,
        "poll_started_at": "2026-07-17T06:44:00Z",
        "poll_completed_at": "2026-07-17T06:45:00Z",
        "http_status": 200,
        "row_count": 0,
        "pagination_complete": True,
        "truncated": False,
        "schema_hash": adapter["expected_response_schema_hash"],
        "response_content_hash": canonical_hash({"query": query_key, "rows": []}),
        "ingestion_mode": "PRODUCTION_REGISTERED_PARSER",
        "parse_result": "SUCCESS",
        "error_class": None,
        "coverage_evidence_id": f"coverage:{query_key}",
    }


def test_poll_ledger_is_idempotent_and_query_scope_bound(tmp_path: Path):
    manifest = preflight_complete_manifest()
    route = next(
        row
        for row in manifest["coverage_routes"]
        if row["applicability"] == "APPLICABLE"
    )
    source_id = route["required_source_ids"][0]
    adapter = next(
        row for row in manifest["adapter_contracts"] if row["source_id"] == source_id
    )
    poll = make_poll(route, source_id, adapter, 1)
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    store.append_poll_observation(poll, manifest=manifest)
    store.append_poll_observation(poll, manifest=manifest)
    assert len(store.polls_as_of(build_cutoff())) == 1

    bad = {**poll, "scope_query_hash": "sha256:" + "0" * 64}
    with pytest.raises(DataVendorUnavailable, match="query binding mismatch"):
        store.append_poll_observation(bad, manifest=manifest)


def build_cutoff():
    from datetime import datetime, timezone

    return datetime(2026, 7, 17, 16, 0, tzinfo=timezone.utc)


def test_discovery_only_cannot_prove_no_event_but_full_routes_can(tmp_path: Path):
    manifest = preflight_complete_manifest()
    adapters = {row["source_id"]: row for row in manifest["adapter_contracts"]}
    sanction_routes = [
        row
        for row in manifest["coverage_routes"]
        if row["event_type"] == "SANCTION" and row["applicability"] == "APPLICABLE"
    ]
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    ordinal = 0
    for route in sanction_routes:
        ordinal += 1
        store.append_poll_observation(
            make_poll(route, "gdelt_event_gkg", adapters["gdelt_event_gkg"], ordinal),
            manifest=manifest,
        )
    partial = build_geopolitical_events_snapshot(
        "2026-07-17", store=store, manifest=manifest
    )
    sanction = next(
        row
        for row in partial["coverage_by_event_type"]
        if row["event_type"] == "SANCTION"
    )
    assert sanction["status"] == "COVERAGE_UNAVAILABLE"
    assert sanction["unhealthy_query_keys"]

    for route in sanction_routes:
        for source_id in route["required_source_ids"]:
            if source_id == "gdelt_event_gkg":
                continue
            ordinal += 1
            store.append_poll_observation(
                make_poll(route, source_id, adapters[source_id], ordinal),
                manifest=manifest,
            )
    complete = build_geopolitical_events_snapshot(
        "2026-07-17", store=store, manifest=manifest
    )
    sanction = next(
        row
        for row in complete["coverage_by_event_type"]
        if row["event_type"] == "SANCTION"
    )
    assert sanction["status"] == "COVERAGE_CONFIRMED_NO_EVENT"
    assert sanction["query_complete"] is True
    assert complete["readiness"] == "REJECTED"  # other event families remain incomplete


def event_revision(**overrides):
    row = {
        "geopolitical_event_id": "geo-event-1",
        "event_revision_id": "geo-event-1:r1",
        "supersedes_revision_id": None,
        "event_type": "SANCTION",
        "lifecycle_status": "DISCOVERED",
        "verification_status": "UNCONFIRMED",
        "actors": ["RU"],
        "affected_regions": ["EU"],
        "affected_channels": ["trade"],
        "published_at": "2026-07-17T12:00:00Z",
        "effective_at": None,
        "first_seen_at": "2026-07-17T12:01:00Z",
        "retrieved_at": "2026-07-17T12:02:00Z",
        "time_status": "VERIFIED",
        "primary_source_tier": "STRUCTURED_DISCOVERY",
        "source_evidence_ids": ["evidence-gdelt"],
        "evidence_bundle_id": "bundle-1",
        "causal_dedupe_key": "cause-1",
        "normalized_content_hash": "sha256:" + "1" * 64,
        "evidence_catalog": [
            {
                "evidence_id": "evidence-gdelt",
                "source_id": "gdelt_event_gkg",
                "published_at": "2026-07-17T12:00:00Z",
                "content_hash": "sha256:" + "2" * 64,
            }
        ],
    }
    row.update(overrides)
    return row


def test_event_confirmation_is_evidence_derived_and_mirrors_do_not_count_twice():
    accepted = validate_event_revision(
        event_revision(), manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    )
    assert accepted["verification_status"] == "UNCONFIRMED"

    false_official = event_revision(verification_status="OFFICIAL_CONFIRMED")
    with pytest.raises(DataVendorUnavailable, match="requires official evidence"):
        validate_event_revision(
            false_official, manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
        )

    same_content = "sha256:" + "3" * 64
    mirrored = event_revision(
        verification_status="MULTISOURCE_CONFIRMED",
        primary_source_tier="OFFICIAL_PRIMARY",
        source_evidence_ids=["mfa", "ofac"],
        evidence_catalog=[
            {
                "evidence_id": "mfa",
                "source_id": "cn_mfa_releases",
                "published_at": "2026-07-17T12:00:00Z",
                "content_hash": same_content,
            },
            {
                "evidence_id": "ofac",
                "source_id": "ofac_recent_actions",
                "published_at": "2026-07-17T12:00:00Z",
                "content_hash": same_content,
            },
        ],
    )
    with pytest.raises(DataVendorUnavailable, match="Mirrored|mirrored"):
        validate_event_revision(mirrored, manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST)


def test_same_day_event_after_decision_cutoff_is_not_visible(tmp_path: Path):
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    store.append_event_revision(
        event_revision(), manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    )

    same_day = build_geopolitical_events_snapshot(
        "2026-07-17", store=store, manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    )
    next_day = build_geopolitical_events_snapshot(
        "2026-07-18", store=store, manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    )

    assert same_day["events"] == []
    assert [row["event_revision_id"] for row in next_day["events"]] == [
        "geo-event-1:r1"
    ]


def test_current_preflight_manifest_rejects_formal_snapshot(tmp_path: Path):
    snapshot = build_geopolitical_events_snapshot(
        "2026-07-17",
        store=GeopoliticalEventStore(tmp_path / "events.sqlite3"),
    )
    assert snapshot["readiness"] == "REJECTED"
    assert snapshot["empty_state"] == "COVERAGE_INCOMPLETE"
    assert all(
        row["status"] == "COVERAGE_UNAVAILABLE"
        for row in snapshot["coverage_by_event_type"]
    )

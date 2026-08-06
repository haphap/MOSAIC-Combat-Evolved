from __future__ import annotations

import copy
import sqlite3
from pathlib import Path

import pytest

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    MaterializationAttemptReceipt,
    RouteCoverageReceipt,
    SnapshotBuildReceipt,
    SourceCaptureReceipt,
    load_agent_data_route_manifest,
    materialization_lock_key,
    validate_agent_data_route_manifest,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


def _source_payload(
    *,
    pit_mode: str = "OBSERVED_LIVE",
    route_id: str = "tushare.eco_cal.cny",
    source_family: str = "tushare",
) -> dict:
    captured_at = (
        "2026-07-01T06:00:00+00:00"
        if pit_mode == "OBSERVED_LIVE"
        else "2026-08-01T06:00:00+00:00"
    )
    knowledge_available_at = (
        "2026-07-01T06:00:00+00:00"
        if pit_mode == "OBSERVED_LIVE"
        else "2026-07-01T05:30:00+00:00"
    )
    payload = {
        "schema_version": "source_capture_receipt_v1",
        "identity": {
            "source_family": source_family,
            "route_id": route_id,
            "request_hash": HASH_A,
            "capture_id": f"capture-20260701-{route_id}",
        },
        "transport": {
            "redacted_url": "https://api.tushare.pro/<redacted>",
            "method": "POST",
            "query_keys": ["country", "date"],
            "pagination_policy": "SINGLE_PAGE_EXACT_DATE",
            "page_count": 1,
        },
        "authority": {
            "provider": "tushare",
            "permission_tier": "token_preflight_verified",
            "api_version": "pro-v1",
            "parser_version": "eco_cal_parser_v2",
        },
        "time": {
            "released_at": "2026-07-01T05:00:00+00:00",
            "vintage_at": "2026-07-01T05:30:00+00:00",
            "captured_at": captured_at,
            "knowledge_available_at": knowledge_available_at,
        },
        "pit": {
            "pit_mode": pit_mode,
            "as_of_cutoff": "2026-07-01T07:00:00+00:00",
            "eligible": True,
            "blocker_codes": [],
            "vintage_query": (
                {"realtime_start": "2026-07-01", "realtime_end": "2026-07-01"}
                if pit_mode == "AUTHORITATIVE_VINTAGE_REPLAY"
                else None
            ),
        },
        "content": {
            "raw_content_hash": HASH_B,
            "normalized_row_count": 12,
            "schema_hash": HASH_C,
        },
        "coverage": {
            "requested_start": "2026-07-01",
            "requested_end": "2026-07-01",
            "observed_start": "2026-07-01",
            "observed_end": "2026-07-01",
            "dimensions": {"currency": ["CNY"], "country": ["中国"]},
        },
        "completeness": {
            "truncated": False,
            "next_page_token_present": False,
            "duplicate_count": 0,
            "empty_result_semantics": "NON_EMPTY",
        },
        "provenance": {
            "parent_capture_hash": None,
            "previous_revision_hash": None,
            "revision_reason": None,
        },
    }
    return SourceCaptureReceipt.seal(payload).as_dict()


def _coverage_payload(*, failed: bool = False, capture_hash: str = HASH_A) -> dict:
    status = "TRANSPORT_FAILED" if failed else "SUCCESS"
    payload = {
        "schema_version": "route_coverage_receipt_v1",
        "coverage_id": "coverage-cny-20260701",
        "window": {
            "start": "2026-07-01T00:00:00+08:00",
            "end": "2026-07-01T23:59:59+08:00",
            "timezone": "Asia/Shanghai",
        },
        "required_route_ids": ["tushare.eco_cal.cny"],
        "route_results": [
            {
                "route_id": "tushare.eco_cal.cny",
                "capture_receipt_hash": None if failed else capture_hash,
                "status": status,
            }
        ],
        "coverage_complete": not failed,
        "blocker_codes": ["TRANSPORT_FAILED"] if failed else [],
    }
    return RouteCoverageReceipt.seal(payload).as_dict()


def _build_payload(
    *,
    state: str = "READY",
    source_hashes: list[str] | None = None,
    build_id: str = "build-china-20260701",
    finished_at: str = "2026-07-01T15:00:02+08:00",
) -> dict:
    ready = state == "READY"
    required_routes = [
        "official.cn_macro",
        "tushare.cn_macro",
        "tushare.eco_cal.cny",
    ]
    payload = {
        "schema_version": "snapshot_build_receipt_v1",
        "build_id": build_id,
        "agent_id": "china",
        "stage": "china",
        "tool_id": "get_china_macro_snapshot",
        "as_of": "2026-07-01",
        "as_of_cutoff": "2026-07-01T15:00:00+08:00",
        "source_receipt_hashes": source_hashes
        if source_hashes is not None
        else ([HASH_A, HASH_C, HASH_D] if ready else [HASH_A, HASH_C]),
        "compiler_version": "china_macro_compiler_v1",
        "output_contract_version": "china_macro_snapshot_v1",
        "output_path": "runtime_snapshots/2026-07-01/china.json",
        "output_hash": HASH_B if ready else None,
        "pit_mode": "OBSERVED_LIVE",
        "earliest_trustworthy_date": "2026-07-01",
        "required_route_ids": required_routes,
        "missing_route_ids": [] if ready else ["tushare.cn_macro"],
        "terminal_state": state,
        "blocker_codes": [] if ready else ["REQUIRED_ROUTE_MISSING"],
        "build_started_at": "2026-07-01T15:00:01+08:00",
        "build_finished_at": finished_at,
    }
    return SnapshotBuildReceipt.seal(payload).as_dict()


def _attempt_payload(
    *,
    state: str = "READY",
    freshness: str = "FRESH",
    source_hashes: list[str] | None = None,
    build_hash: str = HASH_B,
) -> dict:
    ready = state == "READY"
    tools = ["get_china_macro_snapshot"]
    lock_key = materialization_lock_key(
        agent_id="china",
        stage="china",
        as_of="2026-07-01",
        requested_tool_ids=tools,
        candidate_scope_hash=HASH_C,
        runtime_input_hash=HASH_D,
        contract_version="agent_materialization_contract_v1",
    )
    payload = {
        "schema_version": "materialization_attempt_receipt_v1",
        "attempt_id": "attempt-china-20260701",
        "materialization_request_id": "materialize-china-20260701",
        "graph_run_id": "graph-run-20260701",
        "run_slot_id": "run-slot-20260701",
        "run_id": "run-20260701",
        "node_id": "china-node",
        "agent_id": "china",
        "stage": "china",
        "as_of": "2026-07-01",
        "requested_tool_ids": tools,
        "candidate_scope_hash": HASH_C,
        "runtime_input_hash": HASH_D,
        "contract_version": "agent_materialization_contract_v1",
        "source_receipts": {
            "get_china_macro_snapshot": source_hashes or [HASH_A]
        }
        if ready
        else {},
        "build_receipts": {"get_china_macro_snapshot": build_hash} if ready else {},
        "cache_status": "MISS",
        "lock": {
            "key": lock_key,
            "owner": "worker-1",
            "acquired_at": "2026-07-01T07:00:00+00:00",
            "lease_expires_at": "2026-07-01T07:05:00+00:00",
            "heartbeat_at": "2026-07-01T07:00:30+00:00",
            "retry_count": 0,
            "recovered_from_owner": None,
        },
        "freshness": {
            "policy_version": "route_freshness_v1",
            "max_age_seconds": 3600,
            "status": freshness,
            "checked_at": "2026-07-01T07:00:30+00:00",
        },
        "terminal_state": state,
        "blocker_codes": [] if ready else ["REQUIRED_ROUTE_MISSING"],
        "started_at": "2026-07-01T07:00:00+00:00",
        "finished_at": "2026-07-01T07:00:31+00:00",
    }
    return MaterializationAttemptReceipt.seal(payload).as_dict()


def test_source_capture_receipt_round_trips_both_pit_modes() -> None:
    live = SourceCaptureReceipt.from_dict(_source_payload())
    replay = SourceCaptureReceipt.from_dict(
        _source_payload(
            pit_mode="AUTHORITATIVE_VINTAGE_REPLAY",
            route_id="alfred.us_macro",
            source_family="alfred",
        )
    )
    assert live.receipt_hash == live.as_dict()["receipt_hash"]
    assert replay.as_dict()["time"]["captured_at"] > replay.as_dict()["pit"]["as_of_cutoff"]
    assert SourceCaptureReceipt.from_dict(live.as_dict()) == live


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("time", "released_at"), "2026-07-01T05:31:00+00:00", "time order"),
        (("time", "vintage_at"), "2026-07-01T06:01:00+00:00", "time order"),
        (("time", "knowledge_available_at"), "2026-07-01T07:01:00+00:00", "time order"),
        (("time", "captured_at"), "2026-07-01T06:01:00+00:00", "knowledge_available_at"),
        (("time", "captured_at"), "2026-07-01T06:00:00", "date-time"),
    ],
)
def test_source_capture_receipt_rejects_invalid_time_combinations(
    path: tuple[str, str], value: str, message: str
) -> None:
    payload = _source_payload()
    payload.pop("receipt_hash")
    payload[path[0]][path[1]] = value
    with pytest.raises(ValueError, match=message):
        SourceCaptureReceipt.seal(payload)


def test_authoritative_replay_requires_exact_vintage_query() -> None:
    payload = _source_payload(
        pit_mode="AUTHORITATIVE_VINTAGE_REPLAY",
        route_id="alfred.us_macro",
        source_family="alfred",
    )
    payload.pop("receipt_hash")
    payload["pit"]["vintage_query"] = None
    with pytest.raises(ValueError, match="vintage_query"):
        SourceCaptureReceipt.seal(payload)

    invented_knowledge = _source_payload(
        pit_mode="AUTHORITATIVE_VINTAGE_REPLAY",
        route_id="alfred.us_macro",
        source_family="alfred",
    )
    invented_knowledge.pop("receipt_hash")
    invented_knowledge["time"]["knowledge_available_at"] = "2026-07-01T06:30:00+00:00"
    with pytest.raises(ValueError, match="authoritative vintage"):
        SourceCaptureReceipt.seal(invented_knowledge)


def test_source_capture_pit_mode_must_match_manifest_strategy() -> None:
    forward = _source_payload(
        route_id="official.cn_macro",
        source_family="official_cn",
    )
    forward.pop("receipt_hash")
    forward["pit"]["pit_mode"] = "AUTHORITATIVE_VINTAGE_REPLAY"
    forward["pit"]["vintage_query"] = {"vintage": "2026-07-01"}
    forward["time"]["knowledge_available_at"] = forward["time"]["vintage_at"]
    with pytest.raises(ValueError, match="pit strategy"):
        SourceCaptureReceipt.seal(forward)

    authoritative = _source_payload(
        pit_mode="AUTHORITATIVE_VINTAGE_REPLAY",
        route_id="alfred.us_macro",
        source_family="alfred",
    )
    authoritative.pop("receipt_hash")
    authoritative["pit"]["pit_mode"] = "OBSERVED_LIVE"
    authoritative["pit"]["vintage_query"] = None
    authoritative["time"]["captured_at"] = "2026-07-01T06:00:00+00:00"
    authoritative["time"]["knowledge_available_at"] = "2026-07-01T06:00:00+00:00"
    with pytest.raises(ValueError, match="pit strategy"):
        SourceCaptureReceipt.seal(authoritative)


def test_source_capture_rejects_credentials_in_redacted_url() -> None:
    payload = _source_payload()
    payload.pop("receipt_hash")
    payload["transport"]["redacted_url"] = (
        "https://example.test/data?api_key=secret"
    )
    with pytest.raises(ValueError, match="credential"):
        SourceCaptureReceipt.seal(payload)


def test_receipts_reject_unknown_blocker_codes() -> None:
    source = _source_payload()
    source.pop("receipt_hash")
    source["pit"]["eligible"] = False
    source["pit"]["blocker_codes"] = ["FREE_FORM_BLOCKER"]

    coverage = _coverage_payload(failed=True)
    coverage.pop("receipt_hash")
    coverage["blocker_codes"] = ["FREE_FORM_BLOCKER"]

    build = _build_payload(state="BLOCKED")
    build.pop("receipt_hash")
    build["blocker_codes"] = ["FREE_FORM_BLOCKER"]

    attempt = _attempt_payload(state="BLOCKED")
    attempt.pop("receipt_hash")
    attempt["blocker_codes"] = ["FREE_FORM_BLOCKER"]

    for receipt_type, payload in (
        (SourceCaptureReceipt, source),
        (RouteCoverageReceipt, coverage),
        (SnapshotBuildReceipt, build),
        (MaterializationAttemptReceipt, attempt),
    ):
        with pytest.raises(ValueError, match="unknown blocker_codes"):
            receipt_type.seal(payload)


def test_route_manifest_has_exact_agent_stage_tool_coverage() -> None:
    manifest = load_agent_data_route_manifest()
    validated = validate_agent_data_route_manifest(manifest)
    assert len({binding["agent_id"] for binding in validated["bindings"]}) == 28
    assert len({(binding["agent_id"], binding["stage"]) for binding in validated["bindings"]}) == 29
    assert len({binding["tool_id"] for binding in validated["bindings"]}) == 18
    assert all(binding["required_route_ids"] for binding in validated["bindings"])


def test_coverage_receipt_distinguishes_success_from_transport_failure() -> None:
    complete = RouteCoverageReceipt.from_dict(_coverage_payload())
    blocked = RouteCoverageReceipt.from_dict(_coverage_payload(failed=True))
    assert complete.as_dict()["coverage_complete"] is True
    assert blocked.as_dict()["coverage_complete"] is False

    contradictory = _coverage_payload(failed=True)
    contradictory.pop("receipt_hash")
    contradictory["coverage_complete"] = True
    with pytest.raises(ValueError, match="coverage_complete"):
        RouteCoverageReceipt.seal(contradictory)


def test_snapshot_and_attempt_receipts_fail_closed() -> None:
    assert SnapshotBuildReceipt.from_dict(_build_payload()).as_dict()["terminal_state"] == "READY"
    assert MaterializationAttemptReceipt.from_dict(_attempt_payload()).as_dict()["terminal_state"] == "READY"

    stale = _attempt_payload()
    stale.pop("receipt_hash")
    stale["freshness"]["status"] = "STALE"
    with pytest.raises(ValueError, match="STALE"):
        MaterializationAttemptReceipt.seal(stale)

    wrong_lock = _attempt_payload()
    wrong_lock.pop("receipt_hash")
    wrong_lock["lock"]["key"] = HASH_A
    with pytest.raises(ValueError, match="canonical materialization key"):
        MaterializationAttemptReceipt.seal(wrong_lock)

    incomplete = _build_payload(state="BLOCKED")
    incomplete.pop("receipt_hash")
    incomplete["blocker_codes"] = []
    with pytest.raises(ValueError, match="requires blockers"):
        SnapshotBuildReceipt.seal(incomplete)

    expired_lease = _attempt_payload()
    expired_lease.pop("receipt_hash")
    expired_lease["lock"]["heartbeat_at"] = "2026-07-01T15:00:01+08:00"
    expired_lease["lock"]["lease_expires_at"] = "2026-07-01T15:00:02+08:00"
    expired_lease["freshness"]["checked_at"] = "2026-07-01T15:00:01+08:00"
    expired_lease["finished_at"] = "2026-07-01T15:00:03+08:00"
    with pytest.raises(ValueError, match="lease"):
        MaterializationAttemptReceipt.seal(expired_lease)


def test_ledger_is_append_only_idempotent_and_status_is_read_only(tmp_path: Path) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    sources = [
        SourceCaptureReceipt.from_dict(
            _source_payload(route_id="official.cn_macro", source_family="official_cn")
        ),
        SourceCaptureReceipt.from_dict(_source_payload(route_id="tushare.cn_macro")),
        SourceCaptureReceipt.from_dict(_source_payload()),
    ]
    source_hashes = sorted(source.receipt_hash for source in sources)
    eco_cal_hash = next(
        source.receipt_hash
        for source in sources
        if source.as_dict()["identity"]["route_id"] == "tushare.eco_cal.cny"
    )
    coverage = RouteCoverageReceipt.from_dict(
        _coverage_payload(capture_hash=eco_cal_hash)
    )
    build = SnapshotBuildReceipt.from_dict(_build_payload(source_hashes=source_hashes))
    attempt = MaterializationAttemptReceipt.from_dict(
        _attempt_payload(
            source_hashes=source_hashes,
            build_hash=build.receipt_hash,
        )
    )

    for source in sources:
        assert ledger.append_source_capture(source) == source.receipt_hash
        assert ledger.append_source_capture(source) == source.receipt_hash
    assert ledger.append_route_coverage(coverage) == coverage.receipt_hash
    assert ledger.append_snapshot_build(build) == build.receipt_hash
    mismatched_attempt = MaterializationAttemptReceipt.from_dict(
        _attempt_payload(
            source_hashes=source_hashes[:1],
            build_hash=build.receipt_hash,
        )
    )
    with pytest.raises(ValueError, match="does not close over"):
        ledger.append_materialization_attempt(mismatched_attempt)
    assert ledger.append_materialization_attempt(attempt) == attempt.receipt_hash

    before = ledger.row_counts()
    source_status = ledger.source_status(as_of="2026-07-01", route_id="tushare.eco_cal.cny")
    snapshot_status = ledger.snapshot_status(as_of="2026-07-01", agent_id="china", stage="china")
    dry_run = ledger.materialize_dry_run(as_of="2026-07-01", agent_id="china", stage="china")
    assert ledger.row_counts() == before
    assert source_status["status"] == "READY"
    assert snapshot_status["status"] == "READY"
    assert dry_run["dry_run"] is True
    assert dry_run["would_issue_capability"] is True

    with sqlite3.connect(ledger.path) as conn:
        for table in (
            "source_capture_receipts",
            "route_coverage_receipts",
            "snapshot_build_receipts",
            "materialization_attempt_receipts",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append_only"):
                conn.execute(f"DELETE FROM {table}")
            with pytest.raises(sqlite3.IntegrityError, match="append_only"):
                conn.execute(f"UPDATE {table} SET receipt_hash = receipt_hash")

    directory_entries = {path.name for path in ledger.path.parent.iterdir()}
    modified_at = ledger.path.stat().st_mtime_ns
    ledger.source_status(as_of="2026-07-01", route_id="tushare.eco_cal.cny")
    assert ledger.path.stat().st_mtime_ns == modified_at
    assert {path.name for path in ledger.path.parent.iterdir()} == directory_entries


def test_dry_run_reports_missing_routes_without_mutating_ledger(tmp_path: Path) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "empty.sqlite3")
    before = ledger.row_counts()
    report = ledger.materialize_dry_run(
        as_of="2026-07-01", agent_id="market_breadth", stage="market_breadth"
    )
    assert report["would_issue_capability"] is False
    assert report["status"] == "BLOCKED"
    assert report["missing_route_ids"]
    assert ledger.row_counts() == before


def test_read_only_status_does_not_create_a_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite3"
    ledger = AgentDataMaterializationLedger(path, create=False)
    report = ledger.materialize_dry_run(
        as_of="2026-07-01", agent_id="china", stage="china"
    )
    assert report["status"] == "BLOCKED"
    assert not path.exists()


def test_ledger_rejects_orphan_receipt_references(tmp_path: Path) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "orphan.sqlite3")
    coverage = RouteCoverageReceipt.from_dict(_coverage_payload())
    with pytest.raises(ValueError, match="unknown receipt hashes"):
        ledger.append_route_coverage(coverage)

    build = SnapshotBuildReceipt.from_dict(_build_payload())
    with pytest.raises(ValueError, match="unknown receipt hashes"):
        ledger.append_snapshot_build(build)

    attempt = MaterializationAttemptReceipt.from_dict(_attempt_payload())
    with pytest.raises(ValueError, match="unknown receipt hashes"):
        ledger.append_materialization_attempt(attempt)


def test_ready_build_must_close_over_eligible_required_routes(tmp_path: Path) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "build-closure.sqlite3")
    unrelated = SourceCaptureReceipt.from_dict(
        _source_payload(route_id="tushare.commodities")
    )
    ledger.append_source_capture(unrelated)
    build = SnapshotBuildReceipt.from_dict(
        _build_payload(source_hashes=[unrelated.receipt_hash])
    )
    with pytest.raises(ValueError, match="required route coverage"):
        ledger.append_snapshot_build(build)


def test_coverage_closes_over_matching_source_route_and_empty_semantics(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "coverage-closure.sqlite3")
    eco_source = SourceCaptureReceipt.from_dict(_source_payload())
    other_source = SourceCaptureReceipt.from_dict(
        _source_payload(route_id="tushare.cn_macro")
    )
    ledger.append_source_capture(eco_source)
    ledger.append_source_capture(other_source)

    wrong_route = RouteCoverageReceipt.from_dict(
        _coverage_payload(capture_hash=other_source.receipt_hash)
    )
    with pytest.raises(ValueError, match="route does not match"):
        ledger.append_route_coverage(wrong_route)

    claims_empty = _coverage_payload(capture_hash=eco_source.receipt_hash)
    claims_empty.pop("receipt_hash")
    claims_empty["route_results"][0]["status"] = "TRUE_EMPTY"
    with pytest.raises(ValueError, match="empty semantics"):
        ledger.append_route_coverage(RouteCoverageReceipt.seal(claims_empty))


def test_capture_group_rolls_back_partial_sources_and_retries_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "agent-data.sqlite3")
    routes = (
        "tushare.eco_cal.cny",
        "tushare.eco_cal.eur",
        "tushare.eco_cal.usd",
    )
    sources = tuple(
        SourceCaptureReceipt.from_dict(_source_payload(route_id=route_id))
        for route_id in routes
    )
    coverage = RouteCoverageReceipt.seal(
        {
            "schema_version": "route_coverage_receipt_v1",
            "coverage_id": "capture-group-coverage-20260701",
            "window": {
                "start": "2026-07-01T00:00:00+08:00",
                "end": "2026-07-01T23:59:59+08:00",
                "timezone": "Asia/Shanghai",
            },
            "required_route_ids": list(routes),
            "route_results": [
                {
                    "route_id": route_id,
                    "capture_receipt_hash": source.receipt_hash,
                    "status": "SUCCESS",
                }
                for route_id, source in zip(routes, sources, strict=True)
            ],
            "coverage_complete": True,
            "blocker_codes": [],
        }
    )

    original = AgentDataMaterializationLedger._append_on_connection
    insert_count = 0

    def crash_on_second_insert(self, *args, **kwargs):
        nonlocal insert_count
        insert_count += 1
        if insert_count == 2:
            raise RuntimeError("injected capture-group crash")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        AgentDataMaterializationLedger,
        "_append_on_connection",
        crash_on_second_insert,
    )
    with pytest.raises(RuntimeError, match="injected capture-group crash"):
        ledger.append_capture_group(sources, coverage)

    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT count(*) FROM source_capture_receipts").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM route_coverage_receipts").fetchone()[0] == 0

    monkeypatch.setattr(
        AgentDataMaterializationLedger,
        "_append_on_connection",
        original,
    )
    first = ledger.append_capture_group(sources, coverage)
    retry = ledger.append_capture_group(sources, coverage)
    assert retry == first
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT count(*) FROM source_capture_receipts").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM route_coverage_receipts").fetchone()[0] == 1


def test_status_queries_order_mixed_offsets_by_instant(tmp_path: Path) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "timezone-order.sqlite3")

    def source_at(capture_id: str, timestamp: str) -> SourceCaptureReceipt:
        payload = _source_payload()
        payload.pop("receipt_hash")
        payload["identity"]["capture_id"] = capture_id
        payload["time"] = {
            "released_at": timestamp,
            "vintage_at": timestamp,
            "captured_at": timestamp,
            "knowledge_available_at": timestamp,
        }
        payload["pit"]["as_of_cutoff"] = "2026-07-01T08:00:00+00:00"
        return SourceCaptureReceipt.seal(payload)

    older = source_at("capture-older", "2026-07-01T15:00:02+08:00")
    newer = source_at("capture-newer", "2026-07-01T07:00:03+00:00")
    ledger.append_source_capture(older)
    ledger.append_source_capture(newer)
    source_status = ledger.source_status(
        as_of="2026-07-01", route_id="tushare.eco_cal.cny"
    )
    assert source_status["capture_receipt_hash"] == newer.receipt_hash

    sources = [
        SourceCaptureReceipt.from_dict(
            _source_payload(route_id="official.cn_macro", source_family="official_cn")
        ),
        SourceCaptureReceipt.from_dict(_source_payload(route_id="tushare.cn_macro")),
        newer,
    ]
    for source in sources[:-1]:
        ledger.append_source_capture(source)
    hashes = sorted(source.receipt_hash for source in sources)
    older_build = SnapshotBuildReceipt.from_dict(
        _build_payload(
            source_hashes=hashes,
            build_id="build-older",
            finished_at="2026-07-01T15:00:02+08:00",
        )
    )
    newer_build = SnapshotBuildReceipt.from_dict(
        _build_payload(
            source_hashes=hashes,
            build_id="build-newer",
            finished_at="2026-07-01T07:00:03+00:00",
        )
    )
    ledger.append_snapshot_build(older_build)
    ledger.append_snapshot_build(newer_build)
    snapshot_status = ledger.snapshot_status(
        as_of="2026-07-01", agent_id="china", stage="china"
    )
    assert snapshot_status["build_receipt_hashes"][
        "get_china_macro_snapshot"
    ] == newer_build.receipt_hash


def test_receipt_hash_detects_tampering() -> None:
    payload = _source_payload()
    tampered = copy.deepcopy(payload)
    tampered["content"]["normalized_row_count"] = 13
    with pytest.raises(ValueError, match="receipt_hash"):
        SourceCaptureReceipt.from_dict(tampered)
    with pytest.raises(ValueError, match="receipt_hash"):
        SourceCaptureReceipt(tampered)


def test_receipt_set_fields_require_canonical_order() -> None:
    payload = _source_payload()
    payload.pop("receipt_hash")
    payload["pit"]["eligible"] = False
    payload["pit"]["blocker_codes"] = ["TRANSPORT_FAILED", "PERMISSION_DENIED"]
    with pytest.raises(ValueError, match="sorted"):
        SourceCaptureReceipt.seal(payload)

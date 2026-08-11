from __future__ import annotations

import copy
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import mosaic.dataflows.agent_stage_preparer as stage_preparer_module
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
from mosaic.dataflows.agent_stage_preparer import (
    TrustedAgentStageFinalizer,
    TrustedAgentStagePreparer,
    compile_adaptive_query_builds,
    compile_sector_role_event_builds,
    prepare_china_agent_family,
    prepare_europe_macro_family,
    prepare_geopolitical_family,
    prepare_market_breadth_family,
    prepare_sector_relationship_family,
    prepare_us_macro_family,
    publish_ready_stage_materialization,
    us_macro_observation_start,
)
from mosaic.dataflows.economic_calendar import EconomicCalendarStore
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.dataflows.role_events import build_role_event_snapshot
from mosaic.dataflows.source_archive import archive_eco_calendar
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.dataflows.staged_query_receipts import seal_staged_query_source_receipt
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.sector_relationship_preservation import (
    build_sector_relationship_preservation_overlay,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
ROOT = Path(__file__).parents[1]


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


def _ready_stage_build(
    *,
    agent_id: str,
    tool_id: str,
    required_route_ids: list[str],
    source_receipt_hashes: list[str],
) -> SnapshotBuildReceipt:
    return SnapshotBuildReceipt.seal(
        {
            "schema_version": "snapshot_build_receipt_v1",
            "build_id": f"build-{agent_id}-{tool_id}-20260701",
            "agent_id": agent_id,
            "stage": agent_id,
            "tool_id": tool_id,
            "as_of": "2026-07-01",
            "as_of_cutoff": "2026-07-01T15:00:00+08:00",
            "source_receipt_hashes": sorted(source_receipt_hashes),
            "compiler_version": "test_stage_compiler_v1",
            "output_contract_version": "test_stage_snapshot_v1",
            "output_path": f"runtime_snapshots/2026-07-01/{agent_id}-{tool_id}.json",
            "output_hash": canonical_hash(
                {"agent_id": agent_id, "tool_id": tool_id}
            ),
            "pit_mode": "OBSERVED_LIVE",
            "earliest_trustworthy_date": "2026-07-01",
            "required_route_ids": sorted(required_route_ids),
            "missing_route_ids": [],
            "terminal_state": "READY",
            "blocker_codes": [],
            "build_started_at": "2026-07-01T07:00:01+00:00",
            "build_finished_at": "2026-07-01T07:00:02+00:00",
        }
    )


def _ready_stage_attempt(
    *,
    agent_id: str,
    builds: dict[str, SnapshotBuildReceipt],
) -> MaterializationAttemptReceipt:
    tool_ids = sorted(builds)
    source_receipts = {
        tool_id: build.as_dict()["source_receipt_hashes"]
        for tool_id, build in builds.items()
    }
    lock_key = materialization_lock_key(
        agent_id=agent_id,
        stage=agent_id,
        as_of="2026-07-01",
        requested_tool_ids=tool_ids,
        candidate_scope_hash=HASH_C,
        runtime_input_hash=HASH_D,
        contract_version="agent_materialization_contract_v1",
    )
    return MaterializationAttemptReceipt.seal(
        {
            "schema_version": "materialization_attempt_receipt_v1",
            "attempt_id": f"attempt-{agent_id}-20260701",
            "materialization_request_id": f"materialize-{agent_id}-20260701",
            "graph_run_id": "graph-run-20260701",
            "run_slot_id": f"run-slot-{agent_id}-20260701",
            "run_id": "run-20260701",
            "node_id": f"{agent_id}-node",
            "agent_id": agent_id,
            "stage": agent_id,
            "as_of": "2026-07-01",
            "requested_tool_ids": tool_ids,
            "candidate_scope_hash": HASH_C,
            "runtime_input_hash": HASH_D,
            "contract_version": "agent_materialization_contract_v1",
            "source_receipts": source_receipts,
            "build_receipts": {
                tool_id: builds[tool_id].receipt_hash for tool_id in tool_ids
            },
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
                "status": "FRESH",
                "checked_at": "2026-07-01T07:00:30+00:00",
            },
            "terminal_state": "READY",
            "blocker_codes": [],
            "started_at": "2026-07-01T07:00:00+00:00",
            "finished_at": "2026-07-01T07:00:31+00:00",
        }
    )


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
        (
            ("time", "captured_at"),
            "2026-07-01T06:00:00",
            r"time\.captured_at.*(?:must include a timezone|not a 'date-time')",
        ),
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

    derived = _source_payload(
        pit_mode="AUTHORITATIVE_VINTAGE_REPLAY",
        route_id="private.rke_report_intelligence",
        source_family="local_private_rke",
    )
    assert SourceCaptureReceipt.from_dict(derived).as_dict() == derived
    derived.pop("receipt_hash")
    derived["pit"]["pit_mode"] = "OBSERVED_LIVE"
    derived["pit"]["vintage_query"] = None
    derived["time"]["captured_at"] = derived["time"]["knowledge_available_at"]
    with pytest.raises(ValueError, match="pit strategy"):
        SourceCaptureReceipt.seal(derived)


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
    assert len({binding["agent_id"] for binding in validated["bindings"]}) == 27
    assert len({(binding["agent_id"], binding["stage"]) for binding in validated["bindings"]}) == 28
    assert len({binding["tool_id"] for binding in validated["bindings"]}) == 31
    assert all(binding["required_route_ids"] for binding in validated["bindings"])


def test_route_manifest_replaces_yc_cb_curve_route_and_three_bindings_atomically() -> None:
    manifest = load_agent_data_route_manifest()
    routes = {route["route_id"]: route for route in manifest["routes"]}
    assert len(routes) == 29
    assert "tushare.shibor_yield_curve" not in routes
    assert routes["composite.cn_rates"] == {
        "contract_version": "composite_cn_rates_mof_chinabond_v1",
        "implementation_stage": "PR15",
        "pit_strategy": "OBSERVED_LIVE",
        "route_id": "composite.cn_rates",
        "source_family": "composite",
    }
    bound = [
        binding
        for binding in manifest["bindings"]
        if "composite.cn_rates" in binding["required_route_ids"]
    ]
    assert [
        (binding["agent_id"], binding["stage"], binding["tool_id"])
        for binding in bound
    ] == [
        ("central_bank", "central_bank", "get_central_bank_snapshot"),
        ("financials", "financials", "get_yield_curve_cn"),
        ("druckenmiller", "druckenmiller", "get_yield_curve_cn"),
    ]
    assert all(
        "tushare.shibor_yield_curve" not in binding["required_route_ids"]
        for binding in manifest["bindings"]
    )


def test_route_manifest_replaces_non_replayable_europe_sources_atomically() -> None:
    manifest = load_agent_data_route_manifest()
    routes = {route["route_id"]: route for route in manifest["routes"]}
    assert len(routes) == 29
    assert "eurostat.euro_macro" not in routes
    assert routes["ecb.eu_real_economy"] == {
        "contract_version": "ecb_eu_real_economy_history_v1",
        "implementation_stage": "PR15",
        "pit_strategy": "AUTHORITATIVE_VINTAGE_REPLAY",
        "route_id": "ecb.eu_real_economy",
        "source_family": "ecb",
    }
    assert routes["ecb.euro_macro"]["contract_version"] == "ecb_euro_macro_v2"
    bindings = {
        (binding["agent_id"], binding["stage"], binding["tool_id"]): binding[
            "required_route_ids"
        ]
        for binding in manifest["bindings"]
    }
    assert bindings[("eu_economy", "eu_economy", "get_eu_macro_snapshot")] == [
        "ecb.eu_real_economy",
        "ecb.euro_macro",
        "tushare.eco_cal.eur",
    ]
    assert bindings[
        (
            "euro_area_financial_conditions",
            "euro_area_financial_conditions",
            "get_euro_area_financial_conditions_snapshot",
        )
    ] == ["ecb.euro_macro", "market.euro_fx", "tushare.eco_cal.eur"]
    assert all(
        "eurostat.euro_macro" not in binding["required_route_ids"]
        for binding in manifest["bindings"]
    )


def test_default_curve_runtime_has_zero_yc_cb_reachability() -> None:
    runtime_paths = (
        "mosaic/dataflows/china_agent_data_archive.py",
        "mosaic/dataflows/macro_data.py",
        "mosaic/dataflows/china_archive_queries.py",
        "mosaic/dataflows/sector_relationship_queries.py",
        "mosaic/dataflows/route_eligibility.py",
        "mosaic/scorecard/macro_series_backfill.py",
        "mosaic/agents/utils/macro_tools.py",
        "scripts/build_structured_smoke_fixtures.py",
    )
    forbidden = ("yc_cb", "tushare.shibor_yield_curve", "tushare_shibor_yield_curve_v1")
    for relative_path in runtime_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert all(token not in source for token in forbidden), relative_path


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
    assert ledger.ready_snapshot_build_receipts(
        agent_id="china",
        stage="china",
        tool_id="get_china_macro_snapshot",
        as_of="2026-07-01",
    ) == (build,)
    assert ledger.ready_snapshot_build_receipts(
        agent_id="china",
        stage="china",
        tool_id="get_us_macro_snapshot",
        as_of="2026-07-01",
    ) == ()
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


def test_cycle_dry_run_covers_exact_28_stages_without_mutating_ledger(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "empty.sqlite3")
    before = ledger.row_counts()

    report = ledger.materialize_cycle_dry_run(as_of="2026-07-01")

    assert report["schema_version"] == "agent_cycle_materialization_dry_run_v1"
    assert report["dry_run"] is True
    assert report["status"] == "BLOCKED"
    assert report["stage_count"] == 28
    assert len(report["stages"]) == 28
    assert len({(row["agent_id"], row["stage"]) for row in report["stages"]}) == 28
    assert set(report["missing_route_ids"]) == {
        route["route_id"]
        for route in load_agent_data_route_manifest()["routes"]
    }
    assert ledger.row_counts() == before


def test_stage_status_requires_one_exact_ready_attempt_for_all_tools(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "stage-atomic.sqlite3")
    manifest = load_agent_data_route_manifest()
    routes = {row["route_id"]: row for row in manifest["routes"]}
    bindings = {
        row["tool_id"]: row
        for row in manifest["bindings"]
        if row["agent_id"] == "semiconductor" and row["stage"] == "semiconductor"
    }
    route_ids = {
        route_id
        for binding in bindings.values()
        for route_id in binding["required_route_ids"]
    }
    sources = {
        route_id: SourceCaptureReceipt.from_dict(
            _source_payload(
                route_id=route_id,
                source_family=routes[route_id]["source_family"],
                pit_mode=(
                    "AUTHORITATIVE_VINTAGE_REPLAY"
                    if routes[route_id]["pit_strategy"]
                    in {"AUTHORITATIVE_VINTAGE_REPLAY", "DERIVED_FROM_PIT_ARCHIVE"}
                    else "OBSERVED_LIVE"
                ),
            )
        )
        for route_id in route_ids
    }
    for source in sources.values():
        ledger.append_source_capture(source)

    builds = {
        tool_id: _ready_stage_build(
            agent_id="semiconductor",
            tool_id=tool_id,
            required_route_ids=binding["required_route_ids"],
            source_receipt_hashes=[
                sources[route_id].receipt_hash
                for route_id in binding["required_route_ids"]
            ],
        )
        for tool_id, binding in bindings.items()
    }
    for build in builds.values():
        ledger.append_snapshot_build(build)

    unpublished = ledger.snapshot_status(
        as_of="2026-07-01",
        agent_id="semiconductor",
        stage="semiconductor",
    )
    assert unpublished["status"] == "BLOCKED"
    assert unpublished["build_receipt_hashes"] == {}
    assert unpublished["materialization_attempt_receipt_hash"] is None

    partial = {
        tool_id: build
        for tool_id, build in builds.items()
        if tool_id in {"get_role_event_snapshot", "get_sector_research_snapshot"}
    }
    with pytest.raises(ValueError, match="exact active stage tool set"):
        ledger.append_materialization_attempt(
            _ready_stage_attempt(agent_id="semiconductor", builds=partial)
        )

    attempt = _ready_stage_attempt(agent_id="semiconductor", builds=builds)
    ledger.append_materialization_attempt(attempt)
    published = ledger.snapshot_status(
        as_of="2026-07-01",
        agent_id="semiconductor",
        stage="semiconductor",
    )
    assert published["status"] == "READY"
    assert published["build_receipt_hashes"] == {
        tool_id: build.receipt_hash for tool_id, build in builds.items()
    }
    assert published["materialization_attempt_receipt_hash"] == attempt.receipt_hash


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

    def attempt_for(
        build: SnapshotBuildReceipt,
        *,
        attempt_id: str,
        materialization_request_id: str,
        heartbeat_at: str,
        finished_at: str,
    ) -> MaterializationAttemptReceipt:
        payload = _attempt_payload(
            source_hashes=hashes,
            build_hash=build.receipt_hash,
        )
        payload.pop("receipt_hash")
        payload["attempt_id"] = attempt_id
        payload["materialization_request_id"] = materialization_request_id
        payload["lock"]["heartbeat_at"] = heartbeat_at
        payload["freshness"]["checked_at"] = heartbeat_at
        payload["finished_at"] = finished_at
        return MaterializationAttemptReceipt.seal(payload)

    older_attempt = attempt_for(
        older_build,
        attempt_id="attempt-older",
        materialization_request_id="materialize-older",
        heartbeat_at="2026-07-01T07:00:01+00:00",
        finished_at="2026-07-01T15:00:02+08:00",
    )
    newer_attempt = attempt_for(
        newer_build,
        attempt_id="attempt-newer",
        materialization_request_id="materialize-newer",
        heartbeat_at="2026-07-01T07:00:02+00:00",
        finished_at="2026-07-01T07:00:03+00:00",
    )
    older_hash = ledger.append_materialization_attempt(older_attempt)
    retry_attempt = attempt_for(
        older_build,
        attempt_id="attempt-retry",
        materialization_request_id="materialize-retry",
        heartbeat_at="2026-07-01T07:00:02+00:00",
        finished_at="2026-07-01T07:00:03+00:00",
    )
    assert ledger.append_materialization_attempt(retry_attempt) == older_hash
    with pytest.raises(ValueError, match="materialization result collision"):
        ledger.append_materialization_attempt(newer_attempt)
    snapshot_status = ledger.snapshot_status(
        as_of="2026-07-01", agent_id="china", stage="china"
    )
    assert snapshot_status["build_receipt_hashes"][
        "get_china_macro_snapshot"
    ] == older_build.receipt_hash
    assert (
        snapshot_status["materialization_attempt_receipt_hash"]
        == older_attempt.receipt_hash
    )
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM materialization_attempt_receipts "
            "WHERE lock_key = ? AND terminal_state = 'READY'",
            (older_attempt.as_dict()["lock"]["key"],),
        ).fetchone()[0] == 1


def test_concurrent_ready_attempts_publish_one_frozen_result(tmp_path: Path) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "concurrent-ready.sqlite3")
    sources = [
        SourceCaptureReceipt.from_dict(
            _source_payload(route_id="official.cn_macro", source_family="official_cn")
        ),
        SourceCaptureReceipt.from_dict(_source_payload(route_id="tushare.cn_macro")),
        SourceCaptureReceipt.from_dict(_source_payload()),
    ]
    for source in sources:
        ledger.append_source_capture(source)
    hashes = sorted(source.receipt_hash for source in sources)
    build = SnapshotBuildReceipt.from_dict(_build_payload(source_hashes=hashes))
    ledger.append_snapshot_build(build)

    attempts = []
    for index in range(2):
        payload = _attempt_payload(
            source_hashes=hashes,
            build_hash=build.receipt_hash,
        )
        payload.pop("receipt_hash")
        payload["attempt_id"] = f"attempt-concurrent-{index}"
        payload["materialization_request_id"] = f"materialize-concurrent-{index}"
        payload["lock"]["owner"] = f"worker-{index}"
        attempts.append(MaterializationAttemptReceipt.seal(payload))

    with ThreadPoolExecutor(max_workers=2) as pool:
        published_hashes = list(
            pool.map(ledger.append_materialization_attempt, attempts)
        )

    assert len(set(published_hashes)) == 1
    assert published_hashes[0] in {attempt.receipt_hash for attempt in attempts}
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM materialization_attempt_receipts "
            "WHERE lock_key = ? AND terminal_state = 'READY'",
            (attempts[0].as_dict()["lock"]["key"],),
        ).fetchone()[0] == 1


def _ready_stage_request(suffix: str) -> dict:
    return {
        "graph_run_id": f"graph-ready-stage-{suffix}",
        "run_slot_id": f"slot-ready-stage-{suffix}",
        "run_id": f"run-ready-stage-{suffix}",
        "node_id": f"node-ready-stage-{suffix}",
        "agent_id": "china",
        "stage": "china",
        "as_of": "2026-07-01",
        "materialization_request_id": f"materialize-ready-stage-{suffix}",
        "runtime_inputs": {"cycle": "daily"},
        "candidate_scope": None,
    }


def test_publish_ready_stage_materialization_closes_existing_builds(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "ready-stage.sqlite3")
    sources = [
        SourceCaptureReceipt.from_dict(
            _source_payload(route_id="official.cn_macro", source_family="official_cn")
        ),
        SourceCaptureReceipt.from_dict(_source_payload(route_id="tushare.cn_macro")),
        SourceCaptureReceipt.from_dict(_source_payload()),
    ]
    for source in sources:
        ledger.append_source_capture(source)
    build = SnapshotBuildReceipt.from_dict(
        _build_payload(source_hashes=sorted(source.receipt_hash for source in sources))
    )
    ledger.append_snapshot_build(build)
    request = {
        "graph_run_id": "graph-ready-stage",
        "run_slot_id": "slot-ready-stage",
        "run_id": "run-ready-stage",
        "node_id": "node-ready-stage",
        "agent_id": "china",
        "stage": "china",
        "as_of": "2026-07-01",
        "materialization_request_id": "materialize-ready-stage",
        "runtime_inputs": {"cycle": "daily"},
        "candidate_scope": None,
    }

    published = publish_ready_stage_materialization(
        request,
        ledger=ledger,
        clock=lambda: datetime(2026, 7, 1, 7, 0, 5, tzinfo=timezone.utc),
    )
    assert published["status"] == "READY"
    assert published["build_receipt_hashes"] == {
        "get_china_macro_snapshot": build.receipt_hash
    }
    retry = {**request, "materialization_request_id": "materialize-ready-stage-retry"}
    replay = publish_ready_stage_materialization(
        retry,
        ledger=ledger,
        clock=lambda: datetime(2026, 7, 1, 7, 0, 6, tzinfo=timezone.utc),
    )
    assert replay == published
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM materialization_attempt_receipts "
            "WHERE terminal_state = 'READY'"
        ).fetchone()[0] == 1


def test_trusted_stage_preparer_uses_warm_build_without_family_dispatch(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "warm-stage.sqlite3")
    sources = [
        SourceCaptureReceipt.from_dict(
            _source_payload(route_id="official.cn_macro", source_family="official_cn")
        ),
        SourceCaptureReceipt.from_dict(_source_payload(route_id="tushare.cn_macro")),
        SourceCaptureReceipt.from_dict(_source_payload()),
    ]
    for source in sources:
        ledger.append_source_capture(source)
    build = SnapshotBuildReceipt.from_dict(
        _build_payload(source_hashes=sorted(source.receipt_hash for source in sources))
    )
    ledger.append_snapshot_build(build)
    calls: list[str] = []
    preparer = TrustedAgentStagePreparer(
        ledger_factory=lambda: ledger,
        family_preparers={
            ("china", "china"): lambda _request, _ledger: calls.append("family")
        },
        clock=lambda: datetime(2026, 7, 1, 7, 0, 5, tzinfo=timezone.utc),
    )

    result = preparer(_ready_stage_request("warm"))

    assert result == {
        "agent_id": "china",
        "stage": "china",
        "as_of": "2026-07-01",
        "cache_status": "HIT",
    }
    assert calls == []
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM materialization_attempt_receipts"
        ).fetchone()[0] == 0


def test_trusted_stage_preparer_dispatches_cold_family_without_publishing(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "cold-stage.sqlite3")
    calls: list[str] = []

    def prepare_family(_request: dict, target: AgentDataMaterializationLedger) -> None:
        calls.append("family")
        sources = [
            SourceCaptureReceipt.from_dict(
                _source_payload(
                    route_id="official.cn_macro", source_family="official_cn"
                )
            ),
            SourceCaptureReceipt.from_dict(_source_payload(route_id="tushare.cn_macro")),
            SourceCaptureReceipt.from_dict(_source_payload()),
        ]
        for source in sources:
            target.append_source_capture(source)
        target.append_snapshot_build(
            SnapshotBuildReceipt.from_dict(
                _build_payload(
                    source_hashes=sorted(source.receipt_hash for source in sources)
                )
            )
        )

    preparer = TrustedAgentStagePreparer(
        ledger_factory=lambda: ledger,
        family_preparers={("china", "china"): prepare_family},
        clock=lambda: datetime(2026, 7, 1, 7, 0, 5, tzinfo=timezone.utc),
    )

    result = preparer(_ready_stage_request("cold"))

    assert result == {
        "agent_id": "china",
        "stage": "china",
        "as_of": "2026-07-01",
        "cache_status": "MISS",
    }
    assert calls == ["family"]
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM materialization_attempt_receipts"
        ).fetchone()[0] == 0


def test_trusted_stage_finalizer_publishes_after_payload_materialization(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "finalized-stage.sqlite3")
    sources = [
        SourceCaptureReceipt.from_dict(
            _source_payload(route_id="official.cn_macro", source_family="official_cn")
        ),
        SourceCaptureReceipt.from_dict(_source_payload(route_id="tushare.cn_macro")),
        SourceCaptureReceipt.from_dict(_source_payload()),
    ]
    for source in sources:
        ledger.append_source_capture(source)
    build = SnapshotBuildReceipt.from_dict(
        _build_payload(source_hashes=sorted(source.receipt_hash for source in sources))
    )
    ledger.append_snapshot_build(build)
    request = _ready_stage_request("finalized")
    finalizer = TrustedAgentStageFinalizer(
        ledger_factory=lambda: ledger,
        clock=lambda: datetime(2026, 7, 1, 7, 0, 5, tzinfo=timezone.utc),
    )

    result = finalizer(
        {
            **request,
            "stage_preparation": {"cache_status": "MISS"},
            "tool_payload_hashes": {"get_china_macro_snapshot": HASH_B},
            "adaptive_query": None,
        }
    )

    assert result["status"] == "READY"
    assert result["cache_status"] == "MISS"
    assert result["build_receipt_hashes"] == {
        "get_china_macro_snapshot": build.receipt_hash
    }
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM materialization_attempt_receipts"
        ).fetchone()[0] == 1


def test_trusted_stage_finalizer_compiles_adaptive_builds_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "adaptive-finalizer.sqlite3")
    adaptive_store = object()
    staged_store = object()
    events: list[str] = []

    def compile_builds(**kwargs: object) -> tuple:
        assert kwargs["ledger"] is ledger
        assert kwargs["adaptive_query_store"] is adaptive_store
        assert kwargs["staged_receipt_store"] is staged_store
        events.append("compile")
        return ()

    def publish(_context: dict, **kwargs: object) -> dict:
        assert kwargs["ledger"] is ledger
        events.append("publish")
        return {"status": "READY"}

    monkeypatch.setattr(stage_preparer_module, "compile_adaptive_query_builds", compile_builds)
    monkeypatch.setattr(stage_preparer_module, "publish_ready_stage_materialization", publish)
    finalizer = TrustedAgentStageFinalizer(
        ledger_factory=lambda: ledger,
        adaptive_query_store=adaptive_store,
        staged_receipt_store=staged_store,
    )

    result = finalizer(
        {
            **_ready_stage_request("adaptive-finalizer"),
            "stage_preparation": {"cache_status": "MISS"},
            "tool_payload_hashes": {"get_indicators": HASH_B},
            "adaptive_query": {"bundle_id": "frozen_bundle_test"},
        }
    )

    assert result == {"status": "READY"}
    assert events == ["compile", "publish"]


def test_trusted_stage_finalizer_rejects_adaptive_query_without_evidence_stores(
    tmp_path: Path,
) -> None:
    finalizer = TrustedAgentStageFinalizer(
        ledger_factory=lambda: AgentDataMaterializationLedger(
            tmp_path / "missing-adaptive-stores.sqlite3"
        )
    )

    with pytest.raises(DataVendorUnavailable, match="evidence stores"):
        finalizer(
            {
                **_ready_stage_request("missing-adaptive-stores"),
                "stage_preparation": {"cache_status": "MISS"},
                "tool_payload_hashes": {"get_indicators": HASH_B},
                "adaptive_query": {"bundle_id": "frozen_bundle_test"},
            }
        )


def _adaptive_financials_evidence(
    tmp_path: Path,
    *,
    upstream_hash: str,
) -> tuple[FrozenAdaptiveQueryStore, StagedQueryReceiptStore, dict]:
    frozen_store = FrozenAdaptiveQueryStore(
        tmp_path / "private/frozen.sqlite3",
        clock=lambda: datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc),
    )
    staged_store = StagedQueryReceiptStore(
        tmp_path / "private/staged.sqlite3",
        clock=lambda: datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc),
    )
    args = {
        "ticker": "600000.SH",
        "as_of": "2026-07-01",
        "lookback": 20,
        "indicator": "rsi",
    }
    payload = "frozen-indicator-payload"
    descriptor = {
        "tool_id": "get_indicators",
        "route_id": "tushare.sector_market",
        "as_of": "2026-07-01",
        "request_hash": canonical_hash(args),
        "content_hash": canonical_hash({"text": payload}),
        "pit_mode": "OBSERVED_LIVE",
    }
    staged = seal_staged_query_source_receipt(
        descriptor,
        knowledge_available_at="2026-07-01T06:00:00+00:00",
        captured_at="2026-07-01T06:00:00+00:00",
        upstream_evidence_hashes=(upstream_hash,),
    )
    staged_store.register(staged)
    prepared = frozen_store.prepare(
        agent_id="financials",
        stage="financials",
        as_of="2026-07-01",
        authorized_scope={
            "as_of": "2026-07-01",
            "earliest_date": "2026-06-01",
            "tickers": ["600000.SH"],
            "etfs": [],
            "sectors": ["银行"],
            "indicator_families": ["rsi"],
        },
        query_requests=[{"tool_id": "get_indicators", "args": args}],
        preservation_overlay=build_sector_relationship_preservation_overlay(ROOT),
        materializer=lambda _tool_id, _args: {
            "payload": payload,
            "source_receipt_hashes": [staged["receipt_hash"]],
        },
    )
    return frozen_store, staged_store, {
        "bundle_id": prepared["bundle_id"],
        "bundle_hash": prepared["public_projection"]["bundle_hash"],
        "public_projection": prepared["public_projection"],
    }


def test_compile_adaptive_query_builds_promotes_exact_route_lineage_and_replays(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "adaptive-ledger.sqlite3")
    source = SourceCaptureReceipt.from_dict(
        _source_payload(route_id="tushare.sector_market")
    )
    ledger.append_source_capture(source)
    frozen_store, staged_store, adaptive_ref = _adaptive_financials_evidence(
        tmp_path,
        upstream_hash=source.receipt_hash,
    )

    first = compile_adaptive_query_builds(
        agent_id="financials",
        stage="financials",
        as_of="2026-07-01",
        adaptive_query=adaptive_ref,
        ledger=ledger,
        adaptive_query_store=frozen_store,
        staged_receipt_store=staged_store,
        clock=lambda: datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc),
    )
    replay = compile_adaptive_query_builds(
        agent_id="financials",
        stage="financials",
        as_of="2026-07-01",
        adaptive_query=adaptive_ref,
        ledger=ledger,
        adaptive_query_store=frozen_store,
        staged_receipt_store=staged_store,
        clock=lambda: datetime(2026, 7, 1, 7, 1, tzinfo=timezone.utc),
    )

    assert replay == first
    assert len(first) == 1
    build = first[0].as_dict()
    assert build["tool_id"] == "get_indicators"
    assert build["required_route_ids"] == ["tushare.sector_market"]
    assert build["source_receipt_hashes"] == [source.receipt_hash]
    assert build["terminal_state"] == "READY"
    assert build["output_hash"].startswith("sha256:")
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM snapshot_build_receipts "
            "WHERE agent_id = 'financials' AND tool_id = 'get_indicators'"
        ).fetchone()[0] == 1


def test_compile_adaptive_query_builds_rejects_unregistered_upstream_source(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "adaptive-ledger.sqlite3")
    frozen_store, staged_store, adaptive_ref = _adaptive_financials_evidence(
        tmp_path,
        upstream_hash=canonical_hash({"missing": "source"}),
    )

    with pytest.raises(DataVendorUnavailable, match="upstream source receipt"):
        compile_adaptive_query_builds(
            agent_id="financials",
            stage="financials",
            as_of="2026-07-01",
            adaptive_query=adaptive_ref,
            ledger=ledger,
            adaptive_query_store=frozen_store,
            staged_receipt_store=staged_store,
        )


def test_trusted_stage_preparer_fails_closed_without_family_dispatch(
    tmp_path: Path,
) -> None:
    preparer = TrustedAgentStagePreparer(
        ledger_factory=lambda: AgentDataMaterializationLedger(
            tmp_path / "unknown-stage.sqlite3"
        ),
        family_preparers={},
    )

    with pytest.raises(DataVendorUnavailable, match="no registered family preparer"):
        preparer(_ready_stage_request("unknown"))


def test_china_family_reuses_calendar_archive_and_compiler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "china-family.sqlite3")
    calendar_store = object()
    china_store = object()
    archived = object()
    output_root = tmp_path / "macro-snapshots"
    events: list[tuple[str, dict]] = []
    calendar_requests: list[dict[str, str]] = []

    class CompleteCoverage:
        @staticmethod
        def as_dict() -> dict:
            return {"coverage_complete": True}

    def archive_calendar(fetch: object, **kwargs: object) -> SimpleNamespace:
        events.append(("calendar", {"fetch": fetch, **kwargs}))
        return SimpleNamespace(coverage_receipt=CompleteCoverage())

    def archive_china(**kwargs: object) -> object:
        events.append(("china", kwargs))
        return archived

    def compile_china(**kwargs: object) -> object:
        events.append(("compile", kwargs))
        return object()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        calendar_requests.append({"endpoint": endpoint, **params})
        return []

    monkeypatch.setattr(
        stage_preparer_module,
        "_stage_capture_now",
        lambda: datetime(2026, 7, 1, 6, 30, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(stage_preparer_module, "_china_tushare_fetch", fetch_tushare)
    monkeypatch.setattr(
        stage_preparer_module, "EconomicCalendarStore", lambda: calendar_store
    )
    monkeypatch.setattr(
        stage_preparer_module, "ChinaAgentDataArchiveStore", lambda: china_store
    )
    monkeypatch.setattr(stage_preparer_module, "archive_eco_calendar", archive_calendar)
    monkeypatch.setattr(
        stage_preparer_module, "archive_china_agent_sources", archive_china
    )
    monkeypatch.setattr(
        stage_preparer_module, "compile_china_agent_snapshots", compile_china
    )
    monkeypatch.setattr(
        stage_preparer_module, "snapshot_cache_root", lambda: output_root
    )

    prepare_china_agent_family(_ready_stage_request("china-family"), ledger)

    assert [name for name, _ in events] == ["calendar", "china", "compile"]
    calendar_fetch = events[0][1].pop("fetch")
    assert calendar_fetch(date="20260701", country="中国") == []
    assert calendar_requests == [
        {"endpoint": "eco_cal", "date": "20260701", "country": "中国"}
    ]
    assert events[0][1] == {
        "as_of_date": "2026-07-01",
        "captured_at": "2026-07-01T06:30:00+00:00",
        "store": calendar_store,
        "ledger": ledger,
    }
    assert events[1][1] == {
        "as_of_date": "2026-07-01",
        "cutoff_at": "2026-07-01T15:00:00+08:00",
        "market_session_date": "2026-07-01",
        "store": china_store,
        "ledger": ledger,
    }
    assert events[2][1] == {
        "archive": archived,
        "store": china_store,
        "ledger": ledger,
        "output_root": output_root,
    }


@pytest.mark.parametrize(
    ("route_id", "route_group"),
    (
        ("official.cn_macro", "official.cn_macro+tushare.cn_macro"),
        ("tushare.cn_macro", "official.cn_macro+tushare.cn_macro"),
        ("tushare.commodities", "tushare.commodities"),
        ("tushare.institutional_flow", "tushare.institutional_flow"),
        ("composite.cn_rates", "composite.cn_rates"),
    ),
)
def test_china_route_only_capture_skips_calendar_and_compile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_id: str,
    route_group: str,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / f"{route_id}-stage.sqlite3")
    china_store = object()
    calls: list[dict[str, object]] = []
    source = SourceCaptureReceipt.from_dict(
        _source_payload(
            route_id=route_id,
            source_family=(
                "official_cn"
                if route_id == "official.cn_macro"
                else "composite"
                if route_id == "composite.cn_rates"
                else "tushare"
            ),
        )
    )

    class CompleteCoverage:
        @staticmethod
        def as_dict() -> dict:
            return {"coverage_complete": True}

    def archive_china(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            routes={
                route_group: SimpleNamespace(
                    source_receipts=(source,),
                    coverage_receipt=CompleteCoverage(),
                )
            }
        )

    monkeypatch.setattr(
        stage_preparer_module, "ChinaAgentDataArchiveStore", lambda: china_store
    )
    monkeypatch.setattr(
        stage_preparer_module, "archive_china_agent_sources", archive_china
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_eco_calendar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("route-only China capture must not prepare calendar")
        ),
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_china_agent_snapshots",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("route-only China capture must not compile family snapshots")
        ),
    )
    request = _ready_stage_request(f"china-route-{route_id}")
    request["route_id"] = route_id

    prepare_china_agent_family(request, ledger)

    assert calls == [
        {
            "as_of_date": "2026-07-01",
            "cutoff_at": "2026-07-01T15:00:00+08:00",
            "market_session_date": "2026-07-01",
            "requested_route_ids": (route_id,),
            "store": china_store,
            "ledger": ledger,
        }
    ]


def test_china_route_only_forwards_historical_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "china-route-replay.sqlite3")
    calls: list[dict[str, object]] = []
    source = SourceCaptureReceipt.from_dict(
        _source_payload(
            route_id="tushare.institutional_flow",
            source_family="tushare",
        )
    )

    class CompleteCoverage:
        @staticmethod
        def as_dict() -> dict:
            return {"coverage_complete": True}

    def archive_china(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            routes={
                "tushare.institutional_flow": SimpleNamespace(
                    source_receipts=(source,),
                    coverage_receipt=CompleteCoverage(),
                )
            }
        )

    monkeypatch.setattr(
        stage_preparer_module, "ChinaAgentDataArchiveStore", lambda: object()
    )
    monkeypatch.setattr(
        stage_preparer_module, "archive_china_agent_sources", archive_china
    )
    request = _ready_stage_request("china-route-replay")
    request["route_id"] = "tushare.institutional_flow"
    request["historical_replay"] = True

    prepare_china_agent_family(request, ledger)

    assert calls[0]["historical_replay"] is True


def test_china_family_stops_when_calendar_coverage_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "china-calendar-blocked.sqlite3")

    class BlockedCoverage:
        @staticmethod
        def as_dict() -> dict:
            return {"coverage_complete": False, "blocker_codes": ["PERMISSION_DENIED"]}

    monkeypatch.setattr(stage_preparer_module, "EconomicCalendarStore", lambda: object())
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_eco_calendar",
        lambda *_args, **_kwargs: SimpleNamespace(
            coverage_receipt=BlockedCoverage()
        ),
    )

    with pytest.raises(DataVendorUnavailable, match="economic calendar archive is blocked"):
        prepare_china_agent_family(_ready_stage_request("china-blocked"), ledger)


def test_sector_role_event_compiler_seals_exact_ready_builds_and_replays(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "sector-role-events.sqlite3")
    calendar_store = EconomicCalendarStore(tmp_path / "sector-role-calendar.sqlite3")
    archive = archive_eco_calendar(
        lambda **_request: [],
        as_of_date="2026-07-01",
        captured_at="2026-07-01T10:00:00+08:00",
        store=calendar_store,
        ledger=ledger,
    )

    first = compile_sector_role_event_builds(
        archive=archive,
        store=calendar_store,
        ledger=ledger,
    )
    replay = compile_sector_role_event_builds(
        archive=archive,
        store=calendar_store,
        ledger=ledger,
    )

    expected_agents = {
        "semiconductor",
        "technology",
        "energy",
        "consumer",
        "industrials",
        "real_estate_construction",
        "financials",
        "agriculture",
    }
    assert {build.as_dict()["agent_id"] for build in first} == expected_agents
    assert [build.receipt_hash for build in replay] == [
        build.receipt_hash for build in first
    ]
    source_by_route = {
        receipt.as_dict()["identity"]["route_id"]: receipt.receipt_hash
        for receipt in archive.source_receipts
    }
    for build in first:
        payload = build.as_dict()
        agent_id = payload["agent_id"]
        binding = next(
            row
            for row in load_agent_data_route_manifest()["bindings"]
            if row["agent_id"] == agent_id
            and row["stage"] == agent_id
            and row["tool_id"] == "get_role_event_snapshot"
        )
        assert payload["terminal_state"] == "READY"
        assert payload["required_route_ids"] == binding["required_route_ids"]
        assert payload["source_receipt_hashes"] == sorted(
            source_by_route[route_id]
            for route_id in binding["required_route_ids"]
        )
        assert payload["output_hash"] == build_role_event_snapshot(
            agent_id, "2026-07-01", store=calendar_store
        )["role_event_snapshot_hash"]
        assert len(
            ledger.ready_snapshot_build_receipts(
                agent_id=agent_id,
                stage=agent_id,
                tool_id="get_role_event_snapshot",
                as_of="2026-07-01",
            )
        ) == 1


def test_sector_role_event_compiler_seals_blocked_builds_from_calendar_coverage(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "sector-role-blocked.sqlite3")
    calendar_store = EconomicCalendarStore(tmp_path / "sector-role-blocked-calendar.sqlite3")
    archive = archive_eco_calendar(
        lambda **_request: (_ for _ in ()).throw(PermissionError("denied")),
        as_of_date="2026-07-01",
        captured_at="2026-07-01T10:00:00+08:00",
        store=calendar_store,
        ledger=ledger,
    )

    builds = compile_sector_role_event_builds(
        archive=archive,
        store=calendar_store,
        ledger=ledger,
    )

    assert len(builds) == 8
    for build in builds:
        payload = build.as_dict()
        assert payload["terminal_state"] == "BLOCKED"
        assert payload["source_receipt_hashes"] == [
            archive.coverage_receipt.receipt_hash
        ]
        assert payload["missing_route_ids"] == payload["required_route_ids"]
        assert payload["blocker_codes"] == ["PERMISSION_DENIED"]


def test_sector_relationship_family_reuses_all_existing_archives_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "sector-family.sqlite3")
    calendar_store = object()
    sector_store = object()
    china_store = object()
    calendar_archive = SimpleNamespace(
        coverage_receipt=SimpleNamespace(
            as_dict=lambda: {"coverage_complete": True}
        )
    )
    sector_archive = SimpleNamespace(
        coverage_receipt=SimpleNamespace(
            as_dict=lambda: {"coverage_complete": True}
        )
    )
    events: list[tuple[str, dict]] = []

    def archive_china(**kwargs) -> SimpleNamespace:
        events.append(("china", kwargs))
        routes = {}
        for route_id in kwargs["requested_route_ids"]:
            receipt = SimpleNamespace(
                as_dict=lambda route_id=route_id: {
                    "identity": {"route_id": route_id}
                }
            )
            routes[route_id] = SimpleNamespace(
                source_receipts=(receipt,),
                coverage_receipt=SimpleNamespace(
                    as_dict=lambda: {"coverage_complete": True}
                ),
            )
        return SimpleNamespace(routes=routes)

    monkeypatch.setattr(
        stage_preparer_module,
        "_stage_capture_now",
        lambda: datetime(2026, 7, 1, 6, 30, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        stage_preparer_module, "EconomicCalendarStore", lambda: calendar_store
    )
    monkeypatch.setattr(stage_preparer_module, "SectorArchiveStore", lambda: sector_store)
    monkeypatch.setattr(
        stage_preparer_module, "ChinaAgentDataArchiveStore", lambda: china_store
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_eco_calendar",
        lambda fetch, **kwargs: events.append(
            ("calendar", {"fetch": fetch, **kwargs})
        )
        or calendar_archive,
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_sector_role_event_builds",
        lambda **kwargs: events.append(("role", kwargs)) or (),
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_a_share_breadth",
        lambda *_args, **_kwargs: pytest.fail(
            "Sector object preparation must not capture A-share breadth"
        ),
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "capture_a_share_parent_sources",
        lambda *_args, **_kwargs: pytest.fail(
            "Sector object preparation must not capture A-share parents"
        ),
        raising=False,
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_sector_relationship",
        lambda fetch, **kwargs: events.append(
            ("sector", {"fetch": fetch, **kwargs})
        )
        or sector_archive,
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_sector_relationship_core_snapshots",
        lambda archive, **kwargs: events.append(
            ("core", {"archive": archive, **kwargs})
        ),
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_china_agent_sources",
        archive_china,
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_china_agent_snapshots",
        lambda **kwargs: events.append(("china_compile", kwargs)),
    )
    monkeypatch.setattr(
        stage_preparer_module, "snapshot_cache_root", lambda: tmp_path / "snapshots"
    )

    prepare_sector_relationship_family(
        {
            **_ready_stage_request("sector-family"),
            "agent_id": "semiconductor",
            "stage": "semiconductor",
        },
        ledger,
    )

    assert [name for name, _ in events] == [
        "calendar",
        "role",
        "sector",
        "core",
        "china",
    ]
    assert events[0][1]["store"] is calendar_store
    assert events[1][1] == {
        "archive": calendar_archive,
        "store": calendar_store,
        "ledger": ledger,
    }
    assert events[2][1]["store"] is sector_store
    assert "base_store" not in events[2][1]
    assert events[2][1]["requested_route_ids"] == (
        "tushare.sector_fundamentals",
        "tushare.sector_market",
    )
    assert events[2][1]["requested_agent_ids"] == ("semiconductor",)
    assert "requested_security_codes" not in events[2][1]
    assert events[3][1]["archive"] is sector_archive
    assert events[4][1]["store"] is china_store
    assert events[4][1]["requested_route_ids"] == (
        "tushare.institutional_flow",
    )


@pytest.mark.parametrize(
    ("route_id", "agent_id", "sector_agent_ids"),
    (
        (
            "tushare.sector_fundamentals",
            "semiconductor",
            ("semiconductor",),
        ),
        (
            "tushare.sector_market",
            "semiconductor",
            ("semiconductor",),
        ),
    ),
)
def test_sector_route_only_historical_replay_skips_parent_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_id: str,
    agent_id: str,
    sector_agent_ids: tuple[str, ...],
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "sector-route-only.sqlite3")
    sector_store = object()
    sector_archive = SimpleNamespace(
        coverage_receipt=SimpleNamespace(
            as_dict=lambda: {"coverage_complete": True}
        )
    )
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(stage_preparer_module, "SectorArchiveStore", lambda: sector_store)
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_a_share_breadth",
        lambda *_args, **_kwargs: pytest.fail(
            "route-only Sector object preparation must not capture A-share breadth"
        ),
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "capture_a_share_parent_sources",
        lambda *_args, **_kwargs: pytest.fail(
            "route-only Sector object preparation must not capture A-share parents"
        ),
        raising=False,
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_sector_relationship",
        lambda fetch, **kwargs: events.append(("sector", {"fetch": fetch, **kwargs}))
        or sector_archive,
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_eco_calendar",
        lambda *_args, **_kwargs: pytest.fail("route-only capture must skip calendar"),
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_sector_relationship_core_snapshots",
        lambda *_args, **_kwargs: pytest.fail("route-only capture must skip compilers"),
    )

    prepare_sector_relationship_family(
        {
            **_ready_stage_request(f"sector-route-only-{route_id}"),
            "agent_id": agent_id,
            "stage": agent_id,
            "route_id": route_id,
            "historical_replay": True,
            "candidate_scope": None,
        },
        ledger,
    )

    assert [name for name, _ in events] == ["sector"]
    assert events[0][1]["historical_replay"] is True
    assert "base_store" not in events[0][1]
    assert events[0][1]["requested_route_ids"] == (route_id,)
    assert events[0][1]["requested_agent_ids"] == sector_agent_ids
    assert "requested_security_codes" not in events[0][1]


def test_sector_relationship_family_stops_after_blocked_calendar_builds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "sector-blocked-family.sqlite3")
    events: list[str] = []
    blocked = SimpleNamespace(
        coverage_receipt=SimpleNamespace(
            as_dict=lambda: {"coverage_complete": False}
        )
    )
    monkeypatch.setattr(stage_preparer_module, "EconomicCalendarStore", lambda: object())
    monkeypatch.setattr(
        stage_preparer_module, "archive_eco_calendar", lambda *_args, **_kwargs: blocked
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_sector_role_event_builds",
        lambda **_kwargs: events.append("role"),
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_a_share_breadth",
        lambda *_args, **_kwargs: pytest.fail("A-share capture must not start"),
    )

    with pytest.raises(DataVendorUnavailable, match="economic calendar archive is blocked"):
        prepare_sector_relationship_family(
            {
                **_ready_stage_request("sector-blocked"),
                "agent_id": "semiconductor",
                "stage": "semiconductor",
            },
            ledger,
        )

    assert events == ["role"]


def test_us_family_reuses_calendar_archive_and_compiler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "us-family.sqlite3")
    calendar_store = object()
    us_store = object()
    output_root = tmp_path / "macro-snapshots"
    events: list[tuple[str, dict]] = []
    calendar_requests: list[dict[str, str]] = []

    class CompleteCoverage:
        @staticmethod
        def as_dict() -> dict:
            return {"coverage_complete": True}

    def archive_calendar(fetch: object, **kwargs: object) -> SimpleNamespace:
        events.append(("calendar", {"fetch": fetch, **kwargs}))
        return SimpleNamespace(coverage_receipt=CompleteCoverage())

    def archive_us(**kwargs: object) -> SimpleNamespace:
        events.append(("us", kwargs))
        return SimpleNamespace(
            coverage_receipt=CompleteCoverage(),
            group={"capture_key": "us-capture-key"},
        )

    def compile_us(**kwargs: object) -> object:
        events.append(("compile", kwargs))
        return object()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        calendar_requests.append({"endpoint": endpoint, **params})
        return []

    monkeypatch.setattr(
        stage_preparer_module,
        "_stage_capture_now",
        lambda: datetime(2026, 7, 1, 6, 30, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(stage_preparer_module, "_us_tushare_fetch", fetch_tushare)
    monkeypatch.setattr(
        stage_preparer_module, "EconomicCalendarStore", lambda: calendar_store
    )
    monkeypatch.setattr(stage_preparer_module, "USMacroArchiveStore", lambda: us_store)
    monkeypatch.setattr(stage_preparer_module, "archive_eco_calendar", archive_calendar)
    monkeypatch.setattr(stage_preparer_module, "archive_us_macro_sources", archive_us)
    monkeypatch.setattr(stage_preparer_module, "compile_us_macro_snapshots", compile_us)
    monkeypatch.setattr(
        stage_preparer_module, "snapshot_cache_root", lambda: output_root
    )

    prepare_us_macro_family(_ready_stage_request("us-family"), ledger)

    assert us_macro_observation_start("2026-07-01") == "2025-01-01"
    assert [name for name, _ in events] == ["calendar", "us", "compile"]
    calendar_fetch = events[0][1]["fetch"]
    assert calendar_fetch(date="20260701", country="美国") == []
    assert calendar_requests == [
        {"endpoint": "eco_cal", "date": "20260701", "country": "美国"}
    ]
    assert events[1][1] == {
        "as_of_date": "2026-07-01",
        "cutoff_at": "2026-07-01T15:00:00+08:00",
        "observation_start": "2025-01-01",
        "store": us_store,
        "ledger": ledger,
    }
    assert events[2][1] == {
        "capture_key": "us-capture-key",
        "store": us_store,
        "ledger": ledger,
        "output_root": output_root,
    }


def test_us_macro_observation_start_crosses_year_boundary() -> None:
    assert us_macro_observation_start("2026-01-01") == "2025-01-01"
    assert us_macro_observation_start("2026-12-31") == "2025-01-01"


@pytest.mark.parametrize(
    "route_id",
    (
        "alfred.us_macro",
        "market.us_conditions",
        "official.us_policy",
        "tushare.fx_daily",
        "tushare.us_tycr",
    ),
)
def test_us_family_route_only_capture_skips_unrelated_calendar_and_compile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_id: str,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "us-replay-route.sqlite3")
    us_store = object()
    events: list[tuple[str, dict]] = []

    def archive_us(**kwargs: object) -> SimpleNamespace:
        events.append(("us", kwargs))
        return SimpleNamespace(
            source_receipts=(
                SimpleNamespace(
                    as_dict=lambda: {"identity": {"route_id": route_id}}
                ),
            ),
            coverage_receipt=SimpleNamespace(
                as_dict=lambda: {"coverage_complete": False}
            ),
            group={"capture_key": "historical-us-replay"},
        )

    monkeypatch.setattr(stage_preparer_module, "USMacroArchiveStore", lambda: us_store)
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_eco_calendar",
        lambda *_args, **_kwargs: pytest.fail("calendar must not gate route-only capture"),
    )
    monkeypatch.setattr(stage_preparer_module, "archive_us_macro_sources", archive_us)
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_us_macro_snapshots",
        lambda **_kwargs: pytest.fail("route-only replay must not compile the family"),
    )

    request = {
        **_ready_stage_request("us-replay-route"),
        "route_id": route_id,
    }
    prepare_us_macro_family(request, ledger)

    assert events == [
        (
            "us",
            {
                "as_of_date": "2026-07-01",
                "cutoff_at": "2026-07-01T15:00:00+08:00",
                "observation_start": "2025-01-01",
                "requested_route_ids": (route_id,),
                "store": us_store,
                "ledger": ledger,
            },
        )
    ]


def test_us_family_route_only_forwards_historical_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "us-historical-replay.sqlite3")
    archive_calls: list[dict[str, object]] = []

    def archive_us(**kwargs: object) -> SimpleNamespace:
        archive_calls.append(kwargs)
        return SimpleNamespace(
            source_receipts=(
                SimpleNamespace(
                    as_dict=lambda: {
                        "identity": {"route_id": "tushare.us_tycr"}
                    }
                ),
            ),
            coverage_receipt=SimpleNamespace(
                as_dict=lambda: {"coverage_complete": True}
            ),
            group={"capture_key": "historical-us-replay"},
        )

    monkeypatch.setattr(
        stage_preparer_module, "USMacroArchiveStore", lambda: "us-store"
    )
    monkeypatch.setattr(stage_preparer_module, "archive_us_macro_sources", archive_us)

    request = {
        **_ready_stage_request("us-historical-replay"),
        "route_id": "tushare.us_tycr",
        "historical_replay": True,
    }
    prepare_us_macro_family(request, ledger)

    assert archive_calls == [
        {
            "as_of_date": "2026-07-01",
            "cutoff_at": "2026-07-01T15:00:00+08:00",
            "observation_start": "2025-01-01",
            "requested_route_ids": ("tushare.us_tycr",),
            "historical_replay": True,
            "store": "us-store",
            "ledger": ledger,
        }
    ]


def test_europe_family_reuses_calendar_archive_and_compiler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "europe-family.sqlite3")
    calendar_store = object()
    europe_store = object()
    output_root = tmp_path / "macro-snapshots"
    events: list[tuple[str, dict]] = []
    calendar_requests: list[dict[str, str]] = []

    class CompleteCoverage:
        @staticmethod
        def as_dict() -> dict:
            return {"coverage_complete": True}

    def archive_calendar(fetch: object, **kwargs: object) -> SimpleNamespace:
        events.append(("calendar", {"fetch": fetch, **kwargs}))
        return SimpleNamespace(coverage_receipt=CompleteCoverage())

    def archive_europe(**kwargs: object) -> SimpleNamespace:
        events.append(("europe", kwargs))
        return SimpleNamespace(
            coverage_receipt=CompleteCoverage(),
            group={"capture_key": "europe-capture-key"},
        )

    def compile_europe(**kwargs: object) -> object:
        events.append(("compile", kwargs))
        return object()

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        calendar_requests.append({"endpoint": endpoint, **params})
        return []

    monkeypatch.setattr(
        stage_preparer_module,
        "_stage_capture_now",
        lambda: datetime(2026, 7, 1, 6, 30, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(stage_preparer_module, "_europe_tushare_fetch", fetch_tushare)
    monkeypatch.setattr(
        stage_preparer_module, "EconomicCalendarStore", lambda: calendar_store
    )
    monkeypatch.setattr(
        stage_preparer_module, "EuropeMacroArchiveStore", lambda: europe_store
    )
    monkeypatch.setattr(stage_preparer_module, "archive_eco_calendar", archive_calendar)
    monkeypatch.setattr(
        stage_preparer_module, "archive_europe_macro_sources", archive_europe
    )
    monkeypatch.setattr(
        stage_preparer_module, "compile_europe_macro_snapshots", compile_europe
    )
    monkeypatch.setattr(
        stage_preparer_module, "snapshot_cache_root", lambda: output_root
    )

    prepare_europe_macro_family(_ready_stage_request("europe-family"), ledger)

    assert [name for name, _ in events] == ["calendar", "europe", "compile"]
    calendar_fetch = events[0][1]["fetch"]
    assert calendar_fetch(date="20260701", country="欧盟") == []
    assert calendar_requests == [
        {"endpoint": "eco_cal", "date": "20260701", "country": "欧盟"}
    ]
    assert events[1][1] == {
        "as_of_date": "2026-07-01",
        "cutoff_at": "2026-07-01T15:00:00+08:00",
        "observation_start": "2025-01-01",
        "store": europe_store,
        "ledger": ledger,
    }
    assert events[2][1] == {
        "capture_key": "europe-capture-key",
        "store": europe_store,
        "ledger": ledger,
        "output_root": output_root,
    }


@pytest.mark.parametrize(
    "route_id",
    ("ecb.eu_real_economy", "ecb.euro_macro", "market.euro_fx"),
)
def test_europe_family_route_only_capture_skips_unrelated_calendar_and_compile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_id: str,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "europe-replay-route.sqlite3")
    europe_store = object()
    events: list[tuple[str, dict]] = []

    def archive_europe(**kwargs: object) -> SimpleNamespace:
        events.append(("europe", kwargs))
        return SimpleNamespace(
            source_receipts=(
                SimpleNamespace(
                    as_dict=lambda: {"identity": {"route_id": route_id}}
                ),
            ),
            coverage_receipt=SimpleNamespace(
                as_dict=lambda: {"coverage_complete": False}
            ),
            group={"capture_key": "historical-europe-replay"},
        )

    monkeypatch.setattr(
        stage_preparer_module, "EuropeMacroArchiveStore", lambda: europe_store
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_eco_calendar",
        lambda *_args, **_kwargs: pytest.fail("calendar must not gate route-only capture"),
    )
    monkeypatch.setattr(
        stage_preparer_module, "archive_europe_macro_sources", archive_europe
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_europe_macro_snapshots",
        lambda **_kwargs: pytest.fail("route-only replay must not compile the family"),
    )

    request = {
        **_ready_stage_request("europe-replay-route"),
        "route_id": route_id,
    }
    prepare_europe_macro_family(request, ledger)

    assert events == [
        (
            "europe",
            {
                "as_of_date": "2026-07-01",
                "cutoff_at": "2026-07-01T15:00:00+08:00",
                "observation_start": "2025-01-01",
                "requested_route_ids": (route_id,),
                "store": europe_store,
                "ledger": ledger,
            },
        )
    ]


def test_europe_family_route_only_forwards_historical_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "europe-replay-forward.sqlite3")
    europe_store = object()
    calls: list[dict] = []

    def archive_europe(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            source_receipts=(
                SimpleNamespace(
                    as_dict=lambda: {
                        "identity": {"route_id": "market.euro_fx"}
                    }
                ),
            ),
            coverage_receipt=SimpleNamespace(
                as_dict=lambda: {"coverage_complete": True}
            ),
            group={"capture_key": "historical-europe-replay"},
        )

    monkeypatch.setattr(
        stage_preparer_module, "EuropeMacroArchiveStore", lambda: europe_store
    )
    monkeypatch.setattr(
        stage_preparer_module, "archive_europe_macro_sources", archive_europe
    )

    prepare_europe_macro_family(
        {
            **_ready_stage_request("europe-replay-forward"),
            "route_id": "market.euro_fx",
            "historical_replay": True,
        },
        ledger,
    )

    assert calls[0]["historical_replay"] is True


@pytest.mark.parametrize(
    ("preparer", "route_id", "unrelated_archive"),
    (
        (
            prepare_china_agent_family,
            "tushare.eco_cal.cny",
            "archive_china_agent_sources",
        ),
        (
            prepare_us_macro_family,
            "tushare.eco_cal.usd",
            "archive_us_macro_sources",
        ),
        (
            prepare_europe_macro_family,
            "tushare.eco_cal.eur",
            "archive_europe_macro_sources",
        ),
    ),
)
def test_calendar_route_only_capture_skips_unrelated_family_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preparer: Callable[..., None],
    route_id: str,
    unrelated_archive: str,
) -> None:
    ledger = AgentDataMaterializationLedger(
        tmp_path / f"{route_id.replace('.', '-')}.sqlite3"
    )
    captures: list[dict[str, object]] = []

    class CompleteCoverage:
        @staticmethod
        def as_dict() -> dict:
            return {"coverage_complete": True}

    def archive_calendar(_fetch: object, **kwargs: object) -> SimpleNamespace:
        captures.append(kwargs)
        return SimpleNamespace(coverage_receipt=CompleteCoverage())

    monkeypatch.setattr(
        stage_preparer_module,
        "_stage_capture_now",
        lambda: datetime(2026, 8, 10, 7, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(stage_preparer_module, "EconomicCalendarStore", object)
    monkeypatch.setattr(stage_preparer_module, "archive_eco_calendar", archive_calendar)
    monkeypatch.setattr(
        stage_preparer_module,
        unrelated_archive,
        lambda **_kwargs: pytest.fail(
            "calendar-only route must not invoke the unrelated family archive"
        ),
    )

    request = {
        **_ready_stage_request(f"calendar-only-{route_id}"),
        "route_id": route_id,
        "historical_replay": True,
    }
    preparer(request, ledger)

    assert len(captures) == 1
    assert captures[0]["captured_at"] == "2026-08-10T07:00:00+00:00"
    assert captures[0]["as_of_cutoff"] == captures[0]["captured_at"]
    assert captures[0]["requested_route_ids"] == (route_id,)


def test_geopolitical_family_captures_then_materializes_existing_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "geopolitical-family.sqlite3")
    event_store = object()
    event_store_path = tmp_path / "geopolitical-events.sqlite3"
    output_root = tmp_path / "macro-snapshots"
    events: list[tuple[str, dict]] = []

    def capture_geo(**kwargs: object) -> dict:
        events.append(("geo", kwargs))
        return {"all_sources_attempted": True}

    def materialize_geo(**kwargs: object) -> SimpleNamespace:
        events.append(("materialize", kwargs))
        return SimpleNamespace(
            build_receipt=SimpleNamespace(
                as_dict=lambda: {"terminal_state": "READY"}
            )
        )

    monkeypatch.setattr(
        stage_preparer_module,
        "geopolitical_store_path",
        lambda: event_store_path,
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "GeopoliticalEventStore",
        lambda path: event_store if path == event_store_path else None,
    )
    monkeypatch.setattr(
        stage_preparer_module, "capture_required_geopolitical_sources", capture_geo
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_eco_calendar",
        lambda *_args, **_kwargs: pytest.fail(
            "geopolitical route must not capture an unrelated economic calendar"
        ),
    )
    monkeypatch.setattr(
        stage_preparer_module, "materialize_geopolitical_snapshot", materialize_geo
    )
    monkeypatch.setattr(
        stage_preparer_module, "snapshot_cache_root", lambda: output_root
    )

    prepare_geopolitical_family(_ready_stage_request("geopolitical-family"), ledger)

    assert [name for name, _ in events] == ["geo", "materialize"]
    assert events[0][1] == {"store": event_store}
    assert events[1][1] == {
        "as_of_date": "2026-07-01",
        "event_store": event_store,
        "ledger": ledger,
        "output_root": output_root,
    }


def test_geopolitical_family_fails_closed_when_materialization_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "geopolitical-blocked.sqlite3")
    event_store = object()
    monkeypatch.setattr(
        stage_preparer_module, "GeopoliticalEventStore", lambda _path: event_store
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "capture_required_geopolitical_sources",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        stage_preparer_module, "archive_eco_calendar", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "materialize_geopolitical_snapshot",
        lambda **_kwargs: SimpleNamespace(
            build_receipt=SimpleNamespace(
                as_dict=lambda: {"terminal_state": "BLOCKED"}
            )
        ),
    )

    with pytest.raises(DataVendorUnavailable, match="geopolitical archive is blocked"):
        prepare_geopolitical_family(
            _ready_stage_request("geopolitical-blocked"), ledger
        )


def test_market_breadth_family_reuses_archive_adapter_and_compiler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "market-breadth-family.sqlite3")
    store = object()
    archived = object()
    events: list[tuple[str, dict]] = []

    def archive_breadth(fetch: object, **kwargs: object) -> object:
        events.append(("archive", {"fetch": fetch, **kwargs}))
        return archived

    def compile_breadth(archive: object, **kwargs: object) -> SimpleNamespace:
        events.append(("compile", {"archive": archive, **kwargs}))
        return SimpleNamespace(as_dict=lambda: {"terminal_state": "READY"})

    monkeypatch.setattr(stage_preparer_module, "AShareArchiveStore", lambda: store)
    monkeypatch.setattr(
        stage_preparer_module, "archive_a_share_breadth", archive_breadth
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_a_share_breadth_snapshot",
        compile_breadth,
    )

    prepare_market_breadth_family(
        {
            **_ready_stage_request("market-breadth-family"),
            "historical_replay": True,
        },
        ledger,
    )

    assert [name for name, _ in events] == ["archive", "compile"]
    assert events[0][1] == {
        "fetch": stage_preparer_module.fetch_a_share_tushare_endpoint,
        "as_of_date": "2026-07-01",
        "cutoff_at": "2026-07-01T16:00:00+08:00",
        "historical_replay": True,
        "store": store,
        "ledger": ledger,
    }
    assert events[1][1] == {
        "archive": archived,
        "as_of_date": "2026-07-01",
        "ledger": ledger,
    }


def test_market_breadth_family_fails_closed_when_build_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "market-breadth-blocked.sqlite3")
    monkeypatch.setattr(stage_preparer_module, "AShareArchiveStore", lambda: object())
    monkeypatch.setattr(
        stage_preparer_module,
        "archive_a_share_breadth",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        stage_preparer_module,
        "compile_a_share_breadth_snapshot",
        lambda *_args, **_kwargs: SimpleNamespace(
            as_dict=lambda: {"terminal_state": "BLOCKED"}
        ),
    )

    with pytest.raises(DataVendorUnavailable, match="A-share breadth archive is blocked"):
        prepare_market_breadth_family(
            _ready_stage_request("market-breadth-blocked"), ledger
        )


def test_production_registry_includes_market_breadth_and_sector_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class CapturingPreparer:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __call__(self, _request: dict) -> dict:
            return {"status": "CAPTURED"}

    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "enforce")
    monkeypatch.setattr(
        stage_preparer_module, "TrustedAgentStagePreparer", CapturingPreparer
    )

    assert stage_preparer_module.ensure_agent_stage_materialization(
        _ready_stage_request("production-registry")
    ) == {
        "ensure_mode": "enforce",
        "status": "CAPTURED",
    }
    family_preparers = captured["family_preparers"]
    assert isinstance(family_preparers, dict)
    assert family_preparers[("market_breadth", "market_breadth")] is (
        prepare_market_breadth_family
    )
    sector_stages = {
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
    assert {
        agent_id
        for agent_id in sector_stages
        if family_preparers[(agent_id, agent_id)]
        is prepare_sector_relationship_family
    } == sector_stages


def test_publish_ready_stage_materialization_rejects_ambiguous_builds(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "ambiguous-stage.sqlite3")
    sources = [
        SourceCaptureReceipt.from_dict(
            _source_payload(route_id="official.cn_macro", source_family="official_cn")
        ),
        SourceCaptureReceipt.from_dict(_source_payload(route_id="tushare.cn_macro")),
        SourceCaptureReceipt.from_dict(_source_payload()),
    ]
    for source in sources:
        ledger.append_source_capture(source)
    source_hashes = sorted(source.receipt_hash for source in sources)
    ledger.append_snapshot_build(
        SnapshotBuildReceipt.from_dict(
            _build_payload(source_hashes=source_hashes, build_id="build-first")
        )
    )
    ledger.append_snapshot_build(
        SnapshotBuildReceipt.from_dict(
            _build_payload(source_hashes=source_hashes, build_id="build-second")
        )
    )

    with pytest.raises(DataVendorUnavailable, match="ambiguous READY builds"):
        publish_ready_stage_materialization(
            {
                "graph_run_id": "graph-ambiguous-stage",
                "run_slot_id": "slot-ambiguous-stage",
                "run_id": "run-ambiguous-stage",
                "node_id": "node-ambiguous-stage",
                "agent_id": "china",
                "stage": "china",
                "as_of": "2026-07-01",
                "materialization_request_id": "materialize-ambiguous-stage",
                "runtime_inputs": {},
                "candidate_scope": None,
            },
            ledger=ledger,
            clock=lambda: datetime(2026, 7, 1, 7, 0, 5, tzinfo=timezone.utc),
        )


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

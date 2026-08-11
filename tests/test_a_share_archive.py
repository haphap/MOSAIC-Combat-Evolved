from __future__ import annotations

import json
import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest

import mosaic.dataflows.a_share_archive as a_share_archive
from mosaic.dataflows.a_share_archive import (
    ASharePaginationError,
    AShareArchiveStore,
    CAPTURE_LOCK_TIMEOUT_SECONDS,
    _paginate,
    archive_a_share_breadth,
    compile_a_share_breadth_snapshot,
)
from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.cross_runtime_json import canonical_hash
from mosaic.dataflows.market_breadth import render_market_breadth_snapshot


AS_OF = date(2026, 7, 1)
AS_OF_TEXT = AS_OF.isoformat()
CAPTURED_AT = "2026-07-01T15:05:00+08:00"
CUTOFF_AT = "2026-07-01T16:00:00+08:00"


@pytest.fixture(autouse=True)
def verified_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mosaic.dataflows.a_share_archive.assert_endpoint_capture_preflight_allowed",
        lambda _endpoint: None,
    )
    monkeypatch.setattr(
        "mosaic.dataflows.a_share_archive._capture_now",
        lambda: datetime.fromisoformat(CAPTURED_AT),
    )
    monkeypatch.setattr(
        "mosaic.dataflows.a_share_archive.wall_time.sleep",
        lambda _seconds: None,
    )


def _calendar(*, as_of_open: bool = True) -> tuple[list[dict[str, object]], list[str]]:
    start = AS_OF - timedelta(days=500)
    days = [start + timedelta(days=offset) for offset in range(501)]
    sessions = [day for day in days if day.weekday() < 5]
    if not as_of_open:
        sessions.remove(AS_OF)
    open_dates = {day.strftime("%Y%m%d") for day in sessions}
    rows = [
        {
            "exchange": "SSE",
            "cal_date": day.strftime("%Y%m%d"),
            "is_open": int(day.strftime("%Y%m%d") in open_dates),
            "pretrade_date": "",
        }
        for day in days
    ]
    return rows, sorted(open_dates)


class FakeTushare:
    def __init__(self, *, as_of_open: bool = True) -> None:
        self.calendar, self.sessions = _calendar(as_of_open=as_of_open)
        self.session_index = {
            trade_date: index for index, trade_date in enumerate(self.sessions)
        }
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, endpoint: str, **params: object) -> list[dict[str, object]]:
        self.calls.append((endpoint, dict(params)))
        if int(params.get("offset", 0)):
            return []
        if endpoint == "trade_cal":
            return self.calendar
        if endpoint == "stock_basic":
            if params["list_status"] != "L":
                return []
            return [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "A",
                    "list_date": "20200101",
                    "delist_date": None,
                },
                {
                    "ts_code": "600000.SH",
                    "symbol": "600000",
                    "name": "B",
                    "list_date": "20200101",
                    "delist_date": None,
                },
            ]
        trade_date = str(params["trade_date"])
        index = self.session_index[trade_date]
        if endpoint == "daily":
            return [
                {
                    "ts_code": code,
                    "trade_date": trade_date,
                    "close": base + index * step,
                    "pre_close": base + (index - 1) * step,
                    "amount": 1000.0 + index * multiplier,
                }
                for code, base, step, multiplier in (
                    ("000001.SZ", 10.0, 0.02, 2.0),
                    ("600000.SH", 20.0, -0.01, 1.0),
                )
            ]
        if endpoint == "adj_factor":
            return [
                {
                    "ts_code": code,
                    "trade_date": trade_date,
                    "adj_factor": 2.0 if code == "000001.SZ" and index >= 240 else 1.0,
                }
                for code in ("000001.SZ", "600000.SH")
            ]
        if endpoint == "daily_basic":
            return [
                {"ts_code": code, "trade_date": trade_date, "close": 1.0}
                for code in ("000001.SZ", "600000.SH")
            ]
        if endpoint == "suspend_d":
            return (
                [
                    {
                        "ts_code": "600000.SH",
                        "trade_date": trade_date,
                        "suspend_timing": "09:30",
                        "suspend_type": "全天停牌",
                    }
                ]
                if trade_date == AS_OF.strftime("%Y%m%d")
                else []
            )
        raise AssertionError(endpoint)


def _archive(tmp_path: Path, fetch) -> tuple[object, AShareArchiveStore, AgentDataMaterializationLedger]:
    store = AShareArchiveStore(tmp_path / "a_share_archive.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    result = archive_a_share_breadth(
        fetch,
        as_of_date=AS_OF_TEXT,
        cutoff_at=CUTOFF_AT,
        store=store,
        ledger=ledger,
    )
    return result, store, ledger


def test_empty_cache_capture_builds_breadth_and_reuses_frozen_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = FakeTushare()
    first, store, ledger = _archive(tmp_path, fetch)
    call_count = len(fetch.calls)

    assert first.snapshot is not None, (
        first.coverage_receipt.as_dict(),
        store.row_count(),
    )
    assert first.snapshot["as_of_date"] == AS_OF_TEXT
    assert first.snapshot["eligible_count"] == 1
    assert first.snapshot["observed_count"] == 1
    assert first.coverage_receipt.as_dict()["coverage_complete"] is True
    assert first.cache_hit is False
    assert store.row_count() == 1
    group = store.load_group(AS_OF_TEXT)
    assert {batch["endpoint"] for batch in group["batches"]} == {
        "trade_cal",
        "stock_basic",
        "daily",
        "adj_factor",
        "suspend_d",
        "daily_basic",
    }
    inputs = store.load_inputs(AS_OF_TEXT)
    assert float(inputs.adj_factor["adj_factor"].max()) == 2.0
    assert set(inputs.suspensions["ts_code"]) == {"600000.SH"}
    assert "000001.SZ" not in str(first.source_receipts[0].as_dict())
    assert ledger.source_status(
        as_of=AS_OF_TEXT, route_id="tushare.a_share_breadth"
    )["status"] == "READY"
    build = compile_a_share_breadth_snapshot(
        first,
        as_of_date=AS_OF_TEXT,
        ledger=ledger,
    )
    build_payload = build.as_dict()
    assert build_payload["terminal_state"] == "READY"
    assert build_payload["source_receipt_hashes"] == [
        first.source_receipts[0].receipt_hash
    ]
    assert build_payload["required_route_ids"] == ["tushare.a_share_breadth"]
    assert build_payload["missing_route_ids"] == []
    assert build_payload["output_hash"] == canonical_hash(first.snapshot)

    def denied(_endpoint: str) -> None:
        raise PermissionError("permission changed after sealed capture")

    monkeypatch.setattr(
        "mosaic.dataflows.a_share_archive.assert_endpoint_capture_preflight_allowed",
        denied,
    )
    retry = archive_a_share_breadth(
        fetch,
        as_of_date=AS_OF_TEXT,
        cutoff_at=CUTOFF_AT,
        store=store,
        ledger=ledger,
    )
    assert retry.cache_hit is True
    assert retry.snapshot["snapshot_hash"] == first.snapshot["snapshot_hash"]
    replayed_build = compile_a_share_breadth_snapshot(
        retry,
        as_of_date=AS_OF_TEXT,
        ledger=ledger,
    )
    assert replayed_build.receipt_hash == build.receipt_hash
    assert len(fetch.calls) == call_count
    rendered = json.loads(render_market_breadth_snapshot(AS_OF_TEXT, root=tmp_path))
    assert rendered["snapshot_hash"] == first.snapshot["snapshot_hash"]
    monkeypatch.setenv("MOSAIC_A_SHARE_ARCHIVE_DB", str(store.path))
    rendered_from_explicit_archive = json.loads(
        render_market_breadth_snapshot(AS_OF_TEXT)
    )
    assert (
        rendered_from_explicit_archive["snapshot_hash"]
        == first.snapshot["snapshot_hash"]
    )
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT count(*) FROM source_capture_receipts").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM route_coverage_receipts").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM snapshot_build_receipts").fetchone()[0] == 1


def test_non_trading_day_fails_closed_after_calendar_only(tmp_path: Path) -> None:
    fetch = FakeTushare(as_of_open=False)
    result, store, ledger = _archive(tmp_path, fetch)

    assert result.snapshot is None
    assert result.source_receipts == ()
    assert result.coverage_receipt.as_dict()["blocker_codes"] == ["NON_TRADING_DAY"]
    assert {endpoint for endpoint, _params in fetch.calls} == {"trade_cal"}
    assert store.row_count() == 0
    build = compile_a_share_breadth_snapshot(
        result,
        as_of_date=AS_OF_TEXT,
        ledger=ledger,
    )
    build_payload = build.as_dict()
    assert build_payload["terminal_state"] == "BLOCKED"
    assert build_payload["source_receipt_hashes"] == [
        result.coverage_receipt.receipt_hash
    ]
    assert build_payload["missing_route_ids"] == ["tushare.a_share_breadth"]
    assert build_payload["blocker_codes"] == ["NON_TRADING_DAY"]
    assert build_payload["output_hash"] is None
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT count(*) FROM source_capture_receipts").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM route_coverage_receipts").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM snapshot_build_receipts").fetchone()[0] == 1


def test_310_open_sessions_fail_before_downstream_capture(tmp_path: Path) -> None:
    fetch = FakeTushare()
    open_rows = [row for row in fetch.calendar if row["is_open"] == 1]
    for row in open_rows[: len(open_rows) - 310]:
        row["is_open"] = 0

    result, store, _ledger = _archive(tmp_path, fetch)

    assert result.snapshot is None
    assert result.coverage_receipt.as_dict()["blocker_codes"] == [
        "INCOMPLETE_COVERAGE"
    ]
    assert {endpoint for endpoint, _params in fetch.calls} == {"trade_cal"}
    assert store.row_count() == 0


def test_pagination_that_never_reaches_a_short_page_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mosaic.dataflows.a_share_archive.PAGE_SIZE", 2)
    monkeypatch.setattr("mosaic.dataflows.a_share_archive.MAX_PAGES_PER_QUERY", 1)

    def truncated(endpoint: str, **_params: object) -> list[dict[str, object]]:
        assert endpoint == "trade_cal"
        return [
            {"cal_date": "20260630", "is_open": 1},
            {"cal_date": "20260701", "is_open": 1},
        ]

    result, store, _ledger = _archive(tmp_path, truncated)
    assert result.snapshot is None
    assert result.coverage_receipt.as_dict()["blocker_codes"] == ["TRUNCATED"]
    assert result.coverage_receipt.as_dict()["route_results"][0]["status"] == "TRUNCATED"
    assert store.row_count() == 0


def test_pagination_freezes_all_pages_and_counts_exact_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mosaic.dataflows.a_share_archive.PAGE_SIZE", 2)
    pages = {
        0: [
            {"ts_code": "000001.SZ", "list_date": "20200101"},
            {"ts_code": "000002.SZ", "list_date": "20200101"},
        ],
        2: [
            {"ts_code": "000002.SZ", "list_date": "20200101"},
            {"ts_code": "000003.SZ", "list_date": "20200101"},
        ],
        4: [{"ts_code": "000004.SZ", "list_date": "20200101"}],
    }

    rows, page_count, duplicate_count = _paginate(
        lambda _endpoint, **params: pages.get(int(params["offset"]), []),
        "stock_basic",
        {"list_status": "L"},
    )

    assert [row["ts_code"] for row in rows] == [
        "000001.SZ",
        "000002.SZ",
        "000003.SZ",
        "000004.SZ",
    ]
    assert page_count == 6
    assert duplicate_count == 1


def test_rows_after_short_page_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mosaic.dataflows.a_share_archive.PAGE_SIZE", 10)
    pages = {
        0: [
            {"ts_code": f"{index:06d}.SZ", "list_date": "20200101"}
            for index in range(5)
        ],
        5: [
            {"ts_code": f"{index:06d}.SZ", "list_date": "20200101"}
            for index in range(5, 12)
        ],
    }

    with pytest.raises(ASharePaginationError, match="terminal short page"):
        _paginate(
            lambda _endpoint, **params: pages.get(int(params["offset"]), []),
            "stock_basic",
            {"list_status": "L"},
        )


@pytest.mark.parametrize("endpoint", ["daily", "adj_factor", "daily_basic"])
def test_cross_table_closure_rejects_a_missing_security_row(
    tmp_path: Path,
    endpoint: str,
) -> None:
    upstream = FakeTushare()
    target_date = upstream.sessions[-2]

    def fetch(name: str, **params: object) -> list[dict[str, object]]:
        rows = upstream(name, **params)
        if (
            name == endpoint
            and params.get("trade_date") == target_date
            and int(params.get("offset", 0)) == 0
        ):
            return rows[:1]
        return rows

    result, store, _ledger = _archive(tmp_path, fetch)

    assert result.snapshot is None
    assert result.coverage_receipt.as_dict()["blocker_codes"] == [
        "INCOMPLETE_COVERAGE"
    ]
    assert store.row_count() == 0


def test_transient_empty_required_leaf_is_retried(
    tmp_path: Path,
) -> None:
    upstream = FakeTushare()
    target_date = upstream.sessions[-2]
    empty_count = 0

    def fetch(name: str, **params: object) -> list[dict[str, object]]:
        nonlocal empty_count
        if (
            name == "adj_factor"
            and params.get("trade_date") == target_date
            and int(params.get("offset", 0)) == 0
            and empty_count == 0
        ):
            empty_count += 1
            return []
        return upstream(name, **params)

    result, store, _ledger = _archive(tmp_path, fetch)

    assert result.snapshot is not None
    assert result.coverage_receipt.as_dict()["coverage_complete"] is True
    assert empty_count == 1
    assert store.row_count() == 1


def test_persistent_empty_required_leaf_is_transport_failure(
    tmp_path: Path,
) -> None:
    upstream = FakeTushare()
    target_date = upstream.sessions[-2]

    def fetch(name: str, **params: object) -> list[dict[str, object]]:
        if (
            name == "adj_factor"
            and params.get("trade_date") == target_date
            and int(params.get("offset", 0)) == 0
        ):
            return []
        return upstream(name, **params)

    result, store, _ledger = _archive(tmp_path, fetch)

    assert result.snapshot is None
    assert result.coverage_receipt.as_dict()["blocker_codes"] == [
        "TRANSPORT_FAILED"
    ]
    assert result.coverage_receipt.as_dict()["route_results"][0]["status"] == (
        "TRANSPORT_FAILED"
    )
    assert store.row_count() == 0


def test_permission_guard_blocks_transport_and_seals_denial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def denied(_endpoint: str) -> None:
        raise PermissionError("not active")

    def fetch(_endpoint: str, **_params: object) -> list[dict[str, object]]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(
        "mosaic.dataflows.a_share_archive.assert_endpoint_capture_preflight_allowed",
        denied,
    )
    result, _store, _ledger = _archive(tmp_path, fetch)
    assert called is False
    assert result.coverage_receipt.as_dict()["blocker_codes"] == ["PERMISSION_DENIED"]
    assert result.coverage_receipt.as_dict()["route_results"][0]["status"] == (
        "PERMISSION_DENIED"
    )


@pytest.mark.parametrize(
    ("error", "status", "blocker"),
    [
        (TimeoutError("private timeout detail"), "TRANSPORT_FAILED", "TRANSPORT_TIMEOUT"),
        (ConnectionError("private connection detail"), "TRANSPORT_FAILED", "TRANSPORT_FAILED"),
        (RuntimeError("private vendor detail"), "CAPTURE_REJECTED", "CAPTURE_REJECTED"),
    ],
)
def test_transport_and_unknown_vendor_failures_are_sealed_without_details(
    tmp_path: Path,
    error: Exception,
    status: str,
    blocker: str,
) -> None:
    def fetch(_endpoint: str, **_params: object) -> list[dict[str, object]]:
        raise error

    result, store, _ledger = _archive(tmp_path, fetch)
    coverage = result.coverage_receipt.as_dict()
    assert coverage["blocker_codes"] == [blocker]
    assert coverage["route_results"][0]["status"] == status
    assert "private" not in str(coverage)
    assert store.row_count() == 0


def test_schema_drift_is_distinct_from_a_true_empty_route(tmp_path: Path) -> None:
    result, store, _ledger = _archive(
        tmp_path,
        lambda _endpoint, **_params: [{"cal_date": "20260701"}],
    )
    coverage = result.coverage_receipt.as_dict()
    assert coverage["blocker_codes"] == ["SCHEMA_DRIFT"]
    assert coverage["route_results"][0]["status"] == "SCHEMA_DRIFT"
    assert store.row_count() == 0


@pytest.mark.parametrize(
    ("now", "cutoff_at", "blocker"),
    [
        ("2026-07-01T14:59:59+08:00", CUTOFF_AT, "MARKET_SESSION_INCOMPLETE"),
        ("2026-07-01T16:00:01+08:00", CUTOFF_AT, "CAPTURE_AFTER_AS_OF_CUTOFF"),
        (CAPTURED_AT, "2026-07-01T15:00:00+08:00", "MARKET_SESSION_INCOMPLETE"),
    ],
)
def test_market_time_guards_run_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    now: str,
    cutoff_at: str,
    blocker: str,
) -> None:
    called = False
    store = AShareArchiveStore(tmp_path / "a_share_archive.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    monkeypatch.setattr(
        "mosaic.dataflows.a_share_archive._capture_now",
        lambda: datetime.fromisoformat(now),
    )

    def fetch(_endpoint: str, **_params: object) -> list[dict[str, object]]:
        nonlocal called
        called = True
        return []

    result = archive_a_share_breadth(
        fetch,
        as_of_date=AS_OF_TEXT,
        cutoff_at=cutoff_at,
        store=store,
        ledger=ledger,
    )
    assert called is False
    assert result.coverage_receipt.as_dict()["blocker_codes"] == [blocker]


def test_historical_as_of_cannot_inject_a_fake_capture_time(
    tmp_path: Path,
) -> None:
    assert "captured_at" not in inspect.signature(archive_a_share_breadth).parameters
    called = False

    def fetch(_endpoint: str, **_params: object) -> list[dict[str, object]]:
        nonlocal called
        called = True
        return []

    store = AShareArchiveStore(tmp_path / "a_share_archive.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    result = archive_a_share_breadth(
        fetch,
        as_of_date="2026-06-30",
        cutoff_at="2026-06-30T16:00:00+08:00",
        store=store,
        ledger=ledger,
    )

    assert called is False
    assert result.source_receipts == ()
    assert result.coverage_receipt.as_dict()["blocker_codes"] == [
        "CAPTURE_AFTER_AS_OF_CUTOFF"
    ]


def test_explicit_historical_replay_preserves_real_transport_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = "2026-08-10T15:05:00+08:00"
    completed_at = "2026-08-10T15:30:00+08:00"
    times = iter((started_at, completed_at))
    monkeypatch.setattr(
        "mosaic.dataflows.a_share_archive._capture_now",
        lambda: datetime.fromisoformat(next(times)),
    )
    store = AShareArchiveStore(tmp_path / "a_share_archive.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")

    result = archive_a_share_breadth(
        FakeTushare(),
        as_of_date=AS_OF_TEXT,
        cutoff_at=CUTOFF_AT,
        historical_replay=True,
        store=store,
        ledger=ledger,
    )

    assert result.coverage_receipt.as_dict()["coverage_complete"] is True
    receipt = result.source_receipts[0].as_dict()
    assert receipt["coverage"]["requested_end"] == AS_OF_TEXT
    assert receipt["time"]["captured_at"] == completed_at
    assert receipt["pit"]["as_of_cutoff"] == completed_at
    assert store.load_group(AS_OF_TEXT)["cutoff_at"] == completed_at


@pytest.mark.parametrize(
    ("requested_endpoints", "transport_endpoints"),
    [
        (("stock_basic",), {"stock_basic"}),
        (
            ("daily_basic", "stock_basic"),
            {"trade_cal", "stock_basic", "daily_basic"},
        ),
    ],
)
def test_parent_source_capture_queries_only_requested_endpoint_scope(
    tmp_path: Path,
    requested_endpoints: tuple[str, ...],
    transport_endpoints: set[str],
) -> None:
    fetch = FakeTushare()
    store = AShareArchiveStore(tmp_path / "a_share_archive.sqlite3")

    group, cache_hit = a_share_archive.capture_a_share_parent_sources(
        fetch,
        as_of_date=AS_OF_TEXT,
        cutoff_at=CUTOFF_AT,
        requested_endpoints=requested_endpoints,
        store=store,
    )
    call_count = len(fetch.calls)
    replay, replay_cache_hit = a_share_archive.capture_a_share_parent_sources(
        fetch,
        as_of_date=AS_OF_TEXT,
        cutoff_at=CUTOFF_AT,
        requested_endpoints=requested_endpoints,
        store=store,
    )

    assert cache_hit is False
    assert replay_cache_hit is True
    assert replay == group
    assert len(fetch.calls) == call_count
    assert {endpoint for endpoint, _params in fetch.calls} == transport_endpoints
    assert group["requested_endpoints"] == list(requested_endpoints)
    with pytest.raises(FileNotFoundError):
        store.load_group(AS_OF_TEXT)
    assert (
        store.load_group(AS_OF_TEXT, required_endpoints=requested_endpoints) == group
    )


def test_production_clock_records_transport_completion_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = FakeTushare()
    started_at = "2026-07-01T15:05:00+08:00"
    completed_at = "2026-07-01T15:30:00+08:00"
    times = iter((started_at, completed_at))
    monkeypatch.setattr(
        "mosaic.dataflows.a_share_archive._capture_now",
        lambda: datetime.fromisoformat(next(times)),
    )
    store = AShareArchiveStore(tmp_path / "a_share_archive.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    result = archive_a_share_breadth(
        fetch,
        as_of_date=AS_OF_TEXT,
        cutoff_at=CUTOFF_AT,
        store=store,
        ledger=ledger,
    )
    assert result.source_receipts[0].as_dict()["time"]["captured_at"] == completed_at


def test_store_payload_is_append_only(tmp_path: Path) -> None:
    store = AShareArchiveStore(tmp_path / "a_share_archive.sqlite3")
    store.get_or_capture(
        "capture-key",
        lambda: {"schema_version": "a_share_capture_group_v1", "value": 1},
    )
    with sqlite3.connect(store.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute("UPDATE a_share_capture_groups SET group_hash = group_hash")
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute("DELETE FROM a_share_capture_groups")


def test_store_serializes_concurrent_capture_and_reuses_first_result(
    tmp_path: Path,
) -> None:
    store = AShareArchiveStore(tmp_path / "a_share_archive.sqlite3")
    first_started = Event()
    second_started = Event()
    release_first = Event()
    build_count = 0
    payload = {"schema_version": "a_share_capture_group_v1", "value": 1}

    def build() -> dict[str, object]:
        nonlocal build_count
        build_count += 1
        first_started.set()
        assert release_first.wait(timeout=5)
        return payload

    def second() -> tuple[dict[str, object], bool]:
        second_started.set()
        return store.get_or_capture("capture-key", build)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(store.get_or_capture, "capture-key", build)
        assert first_started.wait(timeout=5)
        second_future = pool.submit(second)
        assert second_started.wait(timeout=5)
        release_first.set()
        first = first_future.result(timeout=5)
        retry = second_future.result(timeout=5)

    assert build_count == 1
    assert first == (payload, False)
    assert retry == (payload, True)
    assert store.row_count() == 1


def test_store_writer_wait_covers_bounded_live_capture(tmp_path: Path) -> None:
    store = AShareArchiveStore(tmp_path / "a_share_archive.sqlite3")

    with store._connect() as conn:
        busy_timeout_ms = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])

    assert busy_timeout_ms == CAPTURE_LOCK_TIMEOUT_SECONDS * 1000
    assert CAPTURE_LOCK_TIMEOUT_SECONDS >= 60 * 60


def test_provider_error_object_is_transport_failure_not_schema_drift(
    tmp_path: Path,
) -> None:
    result, store, _ledger = _archive(
        tmp_path,
        lambda _endpoint, **_params: {"code": 429, "msg": "private rate limit"},
    )

    coverage = result.coverage_receipt.as_dict()
    assert coverage["blocker_codes"] == ["TRANSPORT_FAILED"]
    assert coverage["route_results"][0]["status"] == "TRANSPORT_FAILED"
    assert "private rate limit" not in str(coverage)
    assert store.row_count() == 0

from __future__ import annotations

import sqlite3
import socket
from pathlib import Path

import pytest

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    load_agent_data_route_manifest,
)
from mosaic.dataflows.economic_calendar import (
    ECO_CAL_EXPECTED_COLUMNS,
    ECO_CAL_REGISTERED_ROUTES,
    EconomicCalendarStore,
)
from mosaic.dataflows.macro_snapshots import MACRO_EVENT_ROLES
from mosaic.dataflows.role_events import ROLE_EVENT_CURRENCIES
from mosaic.dataflows.source_archive import (
    ECO_CAL_LOGICAL_ROUTES,
    archive_eco_calendar,
)


@pytest.fixture
def network_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("test must use only its injected fetch fixture")

    monkeypatch.setattr(socket, "create_connection", deny_network)


def _row(currency: str, **overrides: object) -> dict[str, object]:
    country = dict(ECO_CAL_REGISTERED_ROUTES)[currency]
    values: dict[str, object] = {
        "date": "20260701",
        "time": "09:30",
        "currency": currency,
        "country": country,
        "event": "制造业 PMI",
        "value": "50.2",
        "pre_value": "49.8",
        "fore_value": "50.0",
    }
    values.update(overrides)
    return {column: values[column] for column in ECO_CAL_EXPECTED_COLUMNS}


def _stores(tmp_path: Path) -> tuple[EconomicCalendarStore, AgentDataMaterializationLedger]:
    return (
        EconomicCalendarStore(tmp_path / "eco-cal.sqlite3"),
        AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3"),
    )


def _archive(
    tmp_path: Path,
    fetch,
    *,
    captured_at: str = "2026-07-01T10:00:00+08:00",
    consumer_agent: str | None = None,
):
    store, ledger = _stores(tmp_path)
    result = archive_eco_calendar(
        fetch,
        as_of_date="2026-07-01",
        captured_at=captured_at,
        store=store,
        ledger=ledger,
        consumer_agent=consumer_agent,
    )
    return result, store, ledger


def test_fresh_empty_cache_captures_all_ten_leaves_and_builds_no_event_snapshot(
    tmp_path: Path,
    network_disabled: None,
) -> None:
    calls: list[dict[str, str]] = []

    def fetch(**request: str) -> list[dict[str, object]]:
        calls.append(request)
        return []

    result, _store, ledger = _archive(
        tmp_path,
        fetch,
        consumer_agent="eu_economy",
    )

    assert calls == [
        {"date": "20260701", "country": country}
        for _currency, country in ECO_CAL_REGISTERED_ROUTES
    ]
    assert len(result.source_receipts) == 3
    assert result.coverage_receipt.as_dict()["coverage_complete"] is True
    assert {
        row["status"]
        for row in result.coverage_receipt.as_dict()["route_results"]
    } == {"TRUE_EMPTY"}
    by_route = {
        receipt.as_dict()["identity"]["route_id"]: receipt.as_dict()
        for receipt in result.source_receipts
    }
    assert by_route["tushare.eco_cal.eur"]["coverage"]["dimensions"][
        "currency"
    ] == sorted(ECO_CAL_LOGICAL_ROUTES["tushare.eco_cal.eur"])
    assert all(
        receipt["completeness"]["empty_result_semantics"] == "TRUE_EMPTY"
        and receipt["content"]["normalized_row_count"] == 0
        and receipt["coverage"]["observed_start"] is None
        for receipt in by_route.values()
    )
    assert result.role_event_snapshot is not None
    assert result.role_event_snapshot["coverage"]["coverage_completeness"] == "COMPLETE"
    assert result.role_event_snapshot["coverage"]["coverage_state"] == (
        "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT"
    )
    assert result.role_event_snapshot["projections"] == []
    for route_id in sorted(ECO_CAL_LOGICAL_ROUTES):
        status = ledger.source_status(as_of="2026-07-01", route_id=route_id)
        assert status["status"] == "READY"
        assert status["capture_receipt_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    "route_id",
    tuple(sorted(ECO_CAL_LOGICAL_ROUTES)),
)
def test_route_only_capture_calls_only_requested_currency_leaves(
    tmp_path: Path,
    network_disabled: None,
    route_id: str,
) -> None:
    calls: list[dict[str, str]] = []

    def fetch(**request: str) -> list[dict[str, object]]:
        calls.append(request)
        return []

    store, ledger = _stores(tmp_path)
    result = archive_eco_calendar(
        fetch,
        as_of_date="2026-07-01",
        captured_at="2026-07-01T10:00:00+08:00",
        requested_route_ids=(route_id,),
        store=store,
        ledger=ledger,
    )

    expected_currencies = set(ECO_CAL_LOGICAL_ROUTES[route_id])
    assert calls == [
        {"date": "20260701", "country": country}
        for currency, country in ECO_CAL_REGISTERED_ROUTES
        if currency in expected_currencies
    ]
    assert [
        receipt.as_dict()["identity"]["route_id"]
        for receipt in result.source_receipts
    ] == [route_id]
    coverage = result.coverage_receipt.as_dict()
    assert coverage["required_route_ids"] == [route_id]
    assert [row["route_id"] for row in coverage["route_results"]] == [route_id]
    assert coverage["coverage_complete"] is True


def test_historical_route_only_reuses_exact_date_archive_without_transport(
    tmp_path: Path,
    network_disabled: None,
) -> None:
    route_id = "tushare.eco_cal.cny"
    store, ledger = _stores(tmp_path)
    first = archive_eco_calendar(
        lambda **_request: [],
        as_of_date="2026-07-01",
        captured_at="2026-08-10T15:00:00+08:00",
        as_of_cutoff="2026-08-10T15:00:00+08:00",
        requested_route_ids=(route_id,),
        store=store,
        ledger=ledger,
    )

    def fail_transport(**_request: str) -> list[dict[str, object]]:
        raise AssertionError("historical exact-date archive must be reused")

    replay = archive_eco_calendar(
        fail_transport,
        as_of_date="2026-07-01",
        captured_at="2026-08-10T15:00:01+08:00",
        as_of_cutoff="2026-08-10T15:00:01+08:00",
        requested_route_ids=(route_id,),
        store=store,
        ledger=ledger,
    )

    assert replay.batch is None
    assert [receipt.receipt_hash for receipt in replay.source_receipts] == [
        receipt.receipt_hash for receipt in first.source_receipts
    ]
    assert replay.coverage_receipt.as_dict()["required_route_ids"] == [route_id]


@pytest.mark.parametrize(
    ("error", "route_status", "blocker"),
    [
        (TimeoutError("timed out"), "TRANSPORT_FAILED", "TRANSPORT_TIMEOUT"),
        (PermissionError("denied"), "PERMISSION_DENIED", "PERMISSION_DENIED"),
        (ValueError("eco_cal schema drift"), "SCHEMA_DRIFT", "SCHEMA_DRIFT"),
    ],
)
def test_transport_permission_and_schema_failures_write_only_failed_coverage(
    tmp_path: Path,
    error: Exception,
    route_status: str,
    blocker: str,
) -> None:
    def fetch(**_request: str):
        raise error

    result, _store, ledger = _archive(tmp_path, fetch)

    assert result.batch is None
    assert result.source_receipts == ()
    coverage = result.coverage_receipt.as_dict()
    assert coverage["coverage_complete"] is False
    assert coverage["blocker_codes"] == [blocker]
    assert {row["status"] for row in coverage["route_results"]} == {route_status}
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT count(*) FROM source_capture_receipts").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM route_coverage_receipts").fetchone()[0] == 1


def test_truncated_leaf_fails_closed_without_source_receipts(tmp_path: Path) -> None:
    result, _store, _ledger = _archive(
        tmp_path,
        lambda **request: [
            _row("CNY", event=f"event-{index}") for index in range(100)
        ]
        if request["country"] == "中国"
        else [],
    )

    assert result.batch is not None
    assert result.batch["status"] == "REJECTED"
    assert result.source_receipts == ()
    coverage = result.coverage_receipt.as_dict()
    assert coverage["coverage_complete"] is False
    assert "TRUNCATED" in coverage["blocker_codes"]
    assert next(
        row
        for row in coverage["route_results"]
        if row["route_id"] == "tushare.eco_cal.cny"
    )["status"] == "TRUNCATED"
    assert {
        row["status"]
        for row in coverage["route_results"]
        if row["route_id"] != "tushare.eco_cal.cny"
    } == {"CAPTURE_REJECTED"}


def test_unclassified_vendor_failure_is_sealed_as_capture_rejected(
    tmp_path: Path,
) -> None:
    class VendorFailure(Exception):
        pass

    def fetch(**_request: str):
        raise VendorFailure("private vendor detail")

    result, _store, _ledger = _archive(tmp_path, fetch)

    coverage = result.coverage_receipt.as_dict()
    assert result.source_receipts == ()
    assert coverage["coverage_complete"] is False
    assert coverage["blocker_codes"] == ["CAPTURE_REJECTED"]
    assert {row["status"] for row in coverage["route_results"]} == {
        "CAPTURE_REJECTED"
    }
    assert "private vendor detail" not in str(coverage)


def test_unknown_endpoint_guard_is_not_misclassified_as_schema_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_unknown(_endpoint: str):
        raise ValueError("DENY_UNKNOWN_ENDPOINT:eco_cal")

    monkeypatch.setattr(
        "mosaic.dataflows.economic_calendar.assert_endpoint_runtime_enabled",
        deny_unknown,
    )
    result, _store, _ledger = _archive(tmp_path, lambda **_request: [])

    coverage = result.coverage_receipt.as_dict()
    assert coverage["blocker_codes"] == ["CAPTURE_REJECTED"]
    assert {row["status"] for row in coverage["route_results"]} == {
        "CAPTURE_REJECTED"
    }


def test_duplicate_rows_are_counted_without_changing_normalized_content(
    tmp_path: Path,
) -> None:
    def fetch(**request: str) -> list[dict[str, object]]:
        if request["country"] != "中国":
            return []
        row = _row("CNY")
        return [row, row]

    result, store, _ledger = _archive(tmp_path, fetch)
    cny = next(
        receipt.as_dict()
        for receipt in result.source_receipts
        if receipt.as_dict()["identity"]["route_id"] == "tushare.eco_cal.cny"
    )
    assert cny["content"]["normalized_row_count"] == 1
    assert cny["completeness"]["duplicate_count"] == 1
    assert len(store.events_as_of("2026-07-01T10:00:00+08:00")) == 1


def test_repeated_capture_is_idempotent_and_later_revision_is_append_only(
    tmp_path: Path,
) -> None:
    store, ledger = _stores(tmp_path)

    def scheduled(**request: str) -> list[dict[str, object]]:
        return [_row("CNY", value=None)] if request["country"] == "中国" else []

    first = archive_eco_calendar(
        scheduled,
        as_of_date="2026-07-01",
        captured_at="2026-07-01T08:00:00+08:00",
        store=store,
        ledger=ledger,
    )
    retry = archive_eco_calendar(
        scheduled,
        as_of_date="2026-07-01",
        captured_at="2026-07-01T08:00:00+08:00",
        store=store,
        ledger=ledger,
    )
    assert [item.receipt_hash for item in retry.source_receipts] == [
        item.receipt_hash for item in first.source_receipts
    ]

    def released(**request: str) -> list[dict[str, object]]:
        return [_row("CNY", value="50.2")] if request["country"] == "中国" else []

    later = archive_eco_calendar(
        released,
        as_of_date="2026-07-01",
        captured_at="2026-07-01T10:00:00+08:00",
        store=store,
        ledger=ledger,
    )
    first_cny = next(
        item.receipt_hash
        for item in first.source_receipts
        if item.as_dict()["identity"]["route_id"] == "tushare.eco_cal.cny"
    )
    later_cny = next(
        item.receipt_hash
        for item in later.source_receipts
        if item.as_dict()["identity"]["route_id"] == "tushare.eco_cal.cny"
    )
    assert later_cny != first_cny
    with sqlite3.connect(store.path) as conn:
        revisions = conn.execute(
            "SELECT record_json FROM event_revisions ORDER BY valid_from"
        ).fetchall()
        assert len(revisions) == 2
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT count(*) FROM source_capture_receipts").fetchone()[0] == 6


def test_eco_calendar_capture_group_crash_exposes_no_partial_ledger_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, ledger = _stores(tmp_path)
    original = AgentDataMaterializationLedger._append_on_connection
    insert_count = 0

    def crash_on_second_insert(self, *args, **kwargs):
        nonlocal insert_count
        insert_count += 1
        if insert_count == 2:
            raise RuntimeError("injected eco capture crash")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        AgentDataMaterializationLedger,
        "_append_on_connection",
        crash_on_second_insert,
    )
    with pytest.raises(RuntimeError, match="injected eco capture crash"):
        archive_eco_calendar(
            lambda **_request: [],
            as_of_date="2026-07-01",
            captured_at="2026-07-01T10:00:00+08:00",
            store=store,
            ledger=ledger,
        )
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT count(*) FROM source_capture_receipts").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM route_coverage_receipts").fetchone()[0] == 0

    monkeypatch.setattr(
        AgentDataMaterializationLedger,
        "_append_on_connection",
        original,
    )
    result = archive_eco_calendar(
        lambda **_request: [],
        as_of_date="2026-07-01",
        captured_at="2026-07-01T10:00:00+08:00",
        store=store,
        ledger=ledger,
    )
    assert len(result.source_receipts) == 3
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT count(*) FROM source_capture_receipts").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM route_coverage_receipts").fetchone()[0] == 1


def test_capture_after_decision_cutoff_does_not_call_transport_or_claim_pit(
    tmp_path: Path,
) -> None:
    called = False

    def fetch(**_request: str):
        nonlocal called
        called = True
        return []

    result, _store, _ledger = _archive(
        tmp_path,
        fetch,
        captured_at="2026-07-01T15:00:01+08:00",
    )
    assert called is False
    assert result.source_receipts == ()
    coverage = result.coverage_receipt.as_dict()
    assert coverage["blocker_codes"] == ["CAPTURE_AFTER_AS_OF_CUTOFF"]
    assert {row["status"] for row in coverage["route_results"]} == {
        "PIT_INELIGIBLE"
    }


def test_historical_retrieval_uses_explicit_replay_cutoff_without_backdating(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, str]] = []

    def fetch(**request: str) -> list[dict[str, object]]:
        calls.append(request)
        return []

    store, ledger = _stores(tmp_path)
    result = archive_eco_calendar(
        fetch,
        as_of_date="2026-07-01",
        captured_at="2026-08-10T15:00:00+08:00",
        as_of_cutoff="2026-08-10T15:00:00+08:00",
        store=store,
        ledger=ledger,
    )

    assert len(calls) == len(ECO_CAL_REGISTERED_ROUTES)
    assert result.coverage_receipt.as_dict()["coverage_complete"] is True
    for receipt in result.source_receipts:
        payload = receipt.as_dict()
        assert payload["coverage"]["requested_start"] == "2026-07-01"
        assert payload["coverage"]["requested_end"] == "2026-07-01"
        assert payload["time"]["captured_at"] == "2026-08-10T15:00:00+08:00"
        assert payload["pit"]["as_of_cutoff"] == "2026-08-10T15:00:00+08:00"
        assert payload["pit"]["pit_mode"] == "OBSERVED_LIVE"


def test_capture_after_cutoff_reuses_existing_pit_archive_without_transport(
    tmp_path: Path,
) -> None:
    store, ledger = _stores(tmp_path)
    first = archive_eco_calendar(
        lambda **_request: [],
        as_of_date="2026-07-01",
        captured_at="2026-07-01T10:00:00+08:00",
        store=store,
        ledger=ledger,
    )
    called = False

    def fetch(**_request: str) -> list[dict[str, object]]:
        nonlocal called
        called = True
        return []

    replay = archive_eco_calendar(
        fetch,
        as_of_date="2026-07-01",
        captured_at="2026-07-01T15:00:01+08:00",
        store=store,
        ledger=ledger,
    )

    assert called is False
    assert replay.batch is None
    assert [receipt.receipt_hash for receipt in replay.source_receipts] == [
        receipt.receipt_hash for receipt in first.source_receipts
    ]
    assert replay.coverage_receipt.as_dict()["coverage_complete"] is True


def test_role_event_manifest_bindings_cover_the_currencies_actually_read() -> None:
    manifest = load_agent_data_route_manifest()
    bindings = {
        row["agent_id"]: row["required_route_ids"]
        for row in manifest["bindings"]
        if row["tool_id"] == "get_role_event_snapshot"
    }

    def logical_routes(currencies: tuple[str, ...]) -> list[str]:
        return sorted(
            route_id
            for route_id, members in ECO_CAL_LOGICAL_ROUTES.items()
            if set(currencies) & set(members)
        )

    assert bindings == {
        agent_id: logical_routes(currencies)
        for agent_id, currencies in ROLE_EVENT_CURRENCIES.items()
        if agent_id in bindings
    }

    all_routes_by_agent: dict[str, set[str]] = {}
    for row in manifest["bindings"]:
        all_routes_by_agent.setdefault(row["agent_id"], set()).update(
            row["required_route_ids"]
        )
    event_consumers = set(bindings) | set(MACRO_EVENT_ROLES)
    assert event_consumers <= set(ROLE_EVENT_CURRENCIES)
    for agent_id in sorted(event_consumers):
        bound_eco_routes = sorted(
            route_id
            for route_id in all_routes_by_agent[agent_id]
            if route_id.startswith("tushare.eco_cal.")
        )
        assert bound_eco_routes == logical_routes(ROLE_EVENT_CURRENCIES[agent_id])

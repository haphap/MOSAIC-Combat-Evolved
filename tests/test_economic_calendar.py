from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mosaic.dataflows.economic_calendar import (
    ECO_CAL_EXPECTED_COLUMNS,
    EconomicCalendarStore,
    collect_eco_calendar,
)


def _row(**overrides):
    values = {
        "date": "20260701",
        "time": "09:30",
        "currency": "CNY",
        "country": "中国",
        "event": "2026年6月 制造业指标初值",
        "value": "50.2",
        "pre_value": "49.8",
        "fore_value": "50.0",
    }
    values.update(overrides)
    return {column: values[column] for column in ECO_CAL_EXPECTED_COLUMNS}


def test_collect_eco_cal_is_append_only_pit_and_idempotent(tmp_path: Path) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")
    rows = [_row()]
    first = collect_eco_calendar(
        lambda **_kwargs: rows,
        start_date="2026-07-01",
        end_date="2026-07-01",
        retrieved_at="2026-07-01T10:00:00+08:00",
        store=store,
        currencies=["CNY"],
    )
    retry = collect_eco_calendar(
        lambda **_kwargs: rows,
        start_date="2026-07-01",
        end_date="2026-07-01",
        retrieved_at="2026-07-01T10:00:00+08:00",
        store=store,
        currencies=["CNY"],
    )
    assert retry == first
    assert first["status"] == "COMPLETE"
    assert first["raw_row_count"] == first["deduplicated_row_count"] == 1
    assert len(first["event_revision_ids"]) == 1
    assert store.events_as_of("2026-07-01T09:59:59+08:00") == []
    events = store.events_as_of("2026-07-01T10:00:00+08:00")
    assert len(events) == 1
    assert events[0]["actual"] == pytest.approx(50.2)
    assert events[0]["event_phase"] == "RELEASED"
    assert events[0]["time_status"] == "UNVERIFIED"
    assert events[0]["scheduled_at"] is None
    assert events[0]["occurrence_key"] == "REFERENCE_PERIOD:2026-06"

    with sqlite3.connect(store.path) as conn:
        for table in (
            "retrieval_batches",
            "raw_rows",
            "event_revisions",
            "retrieval_observations",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append_only"):
                conn.execute(f"DELETE FROM {table}")


def test_revision_preserves_event_id_and_supersedes_without_backfill(tmp_path: Path) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")
    collect_eco_calendar(
        lambda **_kwargs: [_row(value=None)],
        start_date="2026-07-01",
        end_date="2026-07-01",
        retrieved_at="2026-07-01T08:00:00+08:00",
        store=store,
        currencies=["CNY"],
    )
    collect_eco_calendar(
        lambda **_kwargs: [_row(value="50.2")],
        start_date="2026-07-01",
        end_date="2026-07-01",
        retrieved_at="2026-07-01T10:00:00+08:00",
        store=store,
        currencies=["CNY"],
    )
    scheduled = store.events_as_of("2026-07-01T09:00:00+08:00")[0]
    revised = store.events_as_of("2026-07-01T10:00:00+08:00")[0]
    assert scheduled["calendar_event_id"] == revised["calendar_event_id"]
    assert scheduled["event_revision_id"] != revised["event_revision_id"]
    assert revised["supersedes_revision_id"] == scheduled["event_revision_id"]
    assert scheduled["actual"] is None
    assert revised["actual"] == pytest.approx(50.2)
    assert revised["event_phase"] == "REVISED"


def test_in_batch_conflict_and_truncation_fail_closed(tmp_path: Path) -> None:
    conflict_store = EconomicCalendarStore(tmp_path / "conflict.sqlite3")
    collect_eco_calendar(
        lambda **_kwargs: [_row(value="50.1"), _row(value="50.2")],
        start_date="2026-07-01",
        end_date="2026-07-01",
        retrieved_at="2026-07-01T10:00:00+08:00",
        store=conflict_store,
        currencies=["CNY"],
    )
    conflict = conflict_store.events_as_of("2026-07-01T10:00:00+08:00")[0]
    assert conflict["conflict_status"] == "CONFLICT"
    assert conflict["conflict_fields"] == ["ACTUAL"]
    assert conflict["actual"] is None

    truncated_store = EconomicCalendarStore(tmp_path / "truncated.sqlite3")
    rejected = collect_eco_calendar(
        lambda **_kwargs: [_row(event=f"event-{index}") for index in range(100)],
        start_date="2026-07-01",
        end_date="2026-07-01",
        retrieved_at="2026-07-01T10:00:00+08:00",
        store=truncated_store,
        currencies=["CNY"],
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["failure_reason"] == "TRUNCATED_LEAF:20260701:CNY:balance"
    assert truncated_store.events_as_of("2026-07-01T10:00:00+08:00") == []


def test_schema_drift_and_unregistered_currency_are_rejected(tmp_path: Path) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")
    with pytest.raises(ValueError, match="schema drift"):
        collect_eco_calendar(
            lambda **_kwargs: [{"date": "20260701"}],
            start_date="2026-07-01",
            end_date="2026-07-01",
            retrieved_at="2026-07-01T10:00:00+08:00",
            store=store,
            currencies=["CNY"],
        )
    with pytest.raises(ValueError, match="registered subset"):
        collect_eco_calendar(
            lambda **_kwargs: [],
            start_date="2026-07-01",
            end_date="2026-07-01",
            retrieved_at="2026-07-01T10:00:00+08:00",
            store=store,
            currencies=["JPY"],
        )

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.bridge.tool_capabilities import materialize_tool_payload
from mosaic.dataflows.economic_calendar import (
    ECO_CAL_EXPECTED_COLUMNS,
    EconomicCalendarStore,
    collect_eco_calendar,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.role_events import (
    build_role_event_snapshot,
    render_role_event_snapshot,
)


def _row(currency: str, event: str) -> dict:
    values = {
        "date": "20260701",
        "time": "09:30",
        "currency": currency,
        "country": "economic_activity",
        "event": event,
        "value": "1.2%",
        "pre_value": "1.0%",
        "fore_value": "1.1%",
    }
    return {column: values[column] for column in ECO_CAL_EXPECTED_COLUMNS}


def _collect(store: EconomicCalendarStore, currencies: list[str]) -> None:
    collect_eco_calendar(
        lambda **request: [
            _row(
                request["currency"],
                "原油库存" if request["currency"] == "USD" else "工业生产",
            )
        ],
        start_date="2026-07-01",
        end_date="2026-07-01",
        retrieved_at="2026-07-01T10:00:00+08:00",
        store=store,
        currencies=currencies,
    )


def test_role_projection_has_one_macro_owner_and_complete_route_denominator(
    tmp_path: Path,
) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")
    _collect(store, ["CNY", "USD", "EUR"])
    energy = build_role_event_snapshot("energy", "2026-07-01", store=store)
    assert energy["coverage"]["coverage_completeness"] == "COMPLETE"
    assert energy["coverage"]["coverage_state"] == "AVAILABLE_MATERIAL_EVENTS"
    assert len(energy["coverage"]["required_route_ids"]) == 3
    assert energy["coverage"]["unhealthy_route_ids"] == []
    oil = next(
        row for row in energy["projections"] if row["normalized_event"] == "原油库存"
    )
    assert oil["signal_owner"] == "energy"
    assert oil["usage_mode"] == "PRIMARY"
    assert oil["causal_dedupe_key"] == oil["evidence_bundle_id"]
    assert oil["surprise"] is None
    assert energy["role_event_snapshot_hash"].startswith("sha256:")


def test_unverified_calendar_time_cannot_become_decision_timing(tmp_path: Path) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")
    _collect(store, ["CNY", "USD", "EUR"])
    cro = build_role_event_snapshot("cro", "2026-07-01", store=store)
    assert cro["coverage"]["coverage_completeness"] == "COMPLETE"
    assert cro["projections"] == []
    assert cro["coverage"]["coverage_state"] == (
        "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT"
    )


def test_denied_or_incomplete_role_event_access_fails_closed(tmp_path: Path) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")
    _collect(store, ["CNY"])
    with pytest.raises(DataVendorUnavailable, match="denied"):
        build_role_event_snapshot("biotech", "2026-07-01", store=store)
    incomplete = build_role_event_snapshot("energy", "2026-07-01", store=store)
    assert incomplete["coverage"]["coverage_state"] == "SOURCE_UNAVAILABLE"
    assert set(incomplete["coverage"]["unhealthy_route_ids"]) == {
        "eco_cal:20260701:USD",
        "eco_cal:20260701:EUR",
    }


def test_capability_materializer_builds_bound_role_event_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "eco-cal.sqlite3"
    monkeypatch.setenv("MOSAIC_ECO_CAL_CACHE_PATH", str(path))
    _collect(EconomicCalendarStore(path), ["CNY", "USD", "EUR"])
    direct = render_role_event_snapshot("energy", "2026-07-01")
    materialized = materialize_tool_payload(
        "get_role_event_snapshot",
        agent_id="energy",
        stage="energy",
        as_of="2026-07-01",
    )
    assert materialized == direct
    with pytest.raises(DataVendorUnavailable, match="denied"):
        render_role_event_snapshot("biotech", "2026-07-01")

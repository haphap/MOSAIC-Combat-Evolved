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
    country = {"CNY": "中国", "USD": "美国", "EUR": "欧元区"}[currency]
    values = {
        "date": "20260701",
        "time": "09:30",
        "currency": currency,
        "country": country,
        "event": event,
        "value": "1.2%",
        "pre_value": "1.0%",
        "fore_value": "1.1%",
    }
    return {column: values[column] for column in ECO_CAL_EXPECTED_COLUMNS}


def _collect(
    store: EconomicCalendarStore,
    currencies: list[str],
    *,
    retrieved_at: str = "2026-07-01T10:00:00+08:00",
) -> None:
    currency_by_country = {"中国": "CNY", "美国": "USD", "欧元区": "EUR"}
    collect_eco_calendar(
        lambda **request: [
            _row(
                currency_by_country[request["country"]],
                "原油库存" if request["country"] == "美国" else "工业生产",
            )
        ],
        start_date="2026-07-01",
        end_date="2026-07-01",
        retrieved_at=retrieved_at,
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
    assert energy["coverage"]["required_route_ids"] == sorted(
        energy["coverage"]["required_route_ids"]
    )
    assert energy["coverage"]["healthy_route_ids"] == energy["coverage"][
        "required_route_ids"
    ]
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


def test_macro_owner_uses_event_family_not_country(tmp_path: Path) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")

    def fetch(**request):
        currency = {"中国": "CNY", "美国": "USD", "欧元区": "EUR"}[
            request["country"]
        ]
        event = {
            "CNY": "中国人民银行利率决议",
            "USD": "FOMC policy rate decision",
            "EUR": "ECB monetary policy decision",
        }[currency]
        return [_row(currency, event)]

    collect_eco_calendar(
        fetch,
        start_date="2026-07-01",
        end_date="2026-07-01",
        retrieved_at="2026-07-01T10:00:00+08:00",
        store=store,
        currencies=["CNY", "USD", "EUR"],
    )
    expected = {
        "central_bank": "CNY",
        "us_financial_conditions": "USD",
        "euro_area_financial_conditions": "EUR",
    }
    for agent, currency in expected.items():
        snapshot = build_role_event_snapshot(agent, "2026-07-01", store=store)
        primary = [row for row in snapshot["projections"] if row["usage_mode"] == "PRIMARY"]
        assert len(primary) == 1
        assert primary[0]["signal_owner"] == agent
        event = next(
            row
            for row in store.events_as_of("2026-07-01T15:00:00+08:00")
            if row["currency"] == currency
        )
        assert event["event_family"] == "central_banks"


def test_role_projection_rejects_tampered_event_family_lineage(tmp_path: Path) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")
    _collect(store, ["CNY"])

    class TamperedStore:
        def coverage_as_of(self, **kwargs):
            return store.coverage_as_of(**kwargs)

        def events_as_of(self, as_of):
            rows = store.events_as_of(as_of)
            rows[0]["event_family"] = "central_banks"
            return rows

    with pytest.raises(DataVendorUnavailable, match="classifier lineage mismatch"):
        build_role_event_snapshot(
            "china",
            "2026-07-01",
            store=TamperedStore(),  # type: ignore[arg-type]
        )

    class StaleClassifierStore:
        def coverage_as_of(self, **kwargs):
            return store.coverage_as_of(**kwargs)

        def events_as_of(self, as_of):
            rows = store.events_as_of(as_of)
            rows[0]["event_family_classifier_version"] = "legacy"
            return rows

    with pytest.raises(DataVendorUnavailable, match="classifier version mismatch"):
        build_role_event_snapshot(
            "china",
            "2026-07-01",
            store=StaleClassifierStore(),  # type: ignore[arg-type]
        )


def test_same_day_calendar_poll_after_decision_cutoff_is_not_visible(
    tmp_path: Path,
) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")
    _collect(
        store,
        ["CNY", "USD", "EUR"],
        retrieved_at="2026-07-01T15:00:01+08:00",
    )
    snapshot = build_role_event_snapshot("energy", "2026-07-01", store=store)
    assert snapshot["projections"] == []
    assert snapshot["coverage"]["coverage_completeness"] == "INCOMPLETE"


def test_denied_or_incomplete_role_event_access_fails_closed(tmp_path: Path) -> None:
    store = EconomicCalendarStore(tmp_path / "eco-cal.sqlite3")
    _collect(store, ["CNY"])
    with pytest.raises(DataVendorUnavailable, match="denied"):
        build_role_event_snapshot("biotech", "2026-07-01", store=store)
    incomplete = build_role_event_snapshot("energy", "2026-07-01", store=store)
    assert incomplete["coverage"]["coverage_state"] == "SOURCE_UNAVAILABLE"
    assert set(incomplete["coverage"]["unhealthy_route_ids"]) == {
        "eco_cal:20260701:USD:美国",
        "eco_cal:20260701:EUR:欧元区",
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

from __future__ import annotations

import base64
import hashlib
import sqlite3
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    SourceCaptureReceipt,
)
from mosaic.dataflows.europe_macro_archive import (
    ECB_SERIES_IDS,
    REAL_ECONOMY_ECB_SERIES_IDS,
    EuropeMacroArchiveStore,
    archive_europe_macro_sources,
    compile_europe_macro_snapshots,
    select_ecb_vintage_rows,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.scorecard.canonical_json import canonical_hash


AS_OF = "2026-08-08"
CUTOFF = "2026-08-08T15:00:00+08:00"
OBSERVATION_START = "2025-01-01"
CAPTURED_AT = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)


def _raw_result(
    *,
    provider: str,
    series_key: str,
    rows: list[dict],
    source: str,
    retrieved_at: str = "2026-08-08T05:55:00+00:00",
) -> dict:
    raw = f"{provider}:{series_key}:{rows!r}".encode()
    result = {
        "adapter_version": "official_macro_adapters_v1",
        "provider": provider,
        "series_key": series_key,
        "source": source,
        "usage_mode": "PRIMARY",
        "request_url": f"https://example.invalid/{provider}/{series_key}",
        "content_type": "text/csv",
        "retrieved_at": retrieved_at,
        "payload_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "raw_payload_b64": base64.b64encode(raw).decode("ascii"),
        "row_count": len(rows),
        "rows": rows,
        "pit_status": "AUTHORITATIVE_VINTAGE_HISTORY",
    }
    return result


def _callbacks(
    *,
    valid_from: str = "2026-08-08T05:00:00+00:00",
) -> tuple[dict[str, int], object, object]:
    counts = {"financial_ecb": 0, "real_economy_ecb": 0, "fx": 0}
    lock = threading.Lock()

    def increment(key: str) -> int:
        with lock:
            counts[key] += 1
            return counts[key]

    def fetch_official(
        *,
        provider: str,
        series_key: str,
        as_of: str,
        include_history: bool = False,
        include_raw_payload: bool = False,
        observation_start: str | None = None,
        observation_end: str | None = None,
    ) -> dict:
        assert as_of == CUTOFF
        assert include_raw_payload is True
        assert provider == "ECB"
        counter = (
            "financial_ecb"
            if series_key in ECB_SERIES_IDS
            else "real_economy_ecb"
        )
        assert series_key in {*ECB_SERIES_IDS, *REAL_ECONOMY_ECB_SERIES_IDS}
        ordinal = increment(counter)
        assert include_history is True
        assert observation_start == OBSERVATION_START
        assert observation_end == AS_OF
        rows = [
            {
                "KEY": series_key,
                "TIME_PERIOD": "2026-08-07",
                "OBS_VALUE": float(ordinal),
                "ACTION": "Replace",
                "VALID_FROM": valid_from,
                "VALID_TO": "",
                "OBS_STATUS": "A",
            }
        ]
        return _raw_result(
            provider=provider,
            series_key=series_key,
            rows=rows,
            source=f"ecb.{series_key}",
        )

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        increment("fx")
        assert endpoint == "fx_daily"
        assert params == {
            "ts_code": "EURUSD.FXCM",
            "start_date": OBSERVATION_START.replace("-", ""),
            "end_date": AS_OF.replace("-", ""),
        }
        return [
            {
                "ts_code": "EURUSD.FXCM",
                "trade_date": "20260807",
                "bid_close": 1.16,
                "ask_close": 1.18,
            }
        ]

    return counts, fetch_official, fetch_tushare


def _archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    captured_at: datetime = CAPTURED_AT,
    historical_replay: bool = False,
    requested_route_ids: tuple[str, ...] | None = None,
    callbacks: tuple[dict[str, int], object, object] | None = None,
):
    from mosaic.dataflows import europe_macro_archive

    monkeypatch.setattr(europe_macro_archive, "_capture_now", lambda: captured_at)
    store = EuropeMacroArchiveStore(tmp_path / "europe-macro.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, fetch_official, fetch_tushare = callbacks or _callbacks()
    result = archive_europe_macro_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        observation_start=OBSERVATION_START,
        requested_route_ids=requested_route_ids,
        store=store,
        ledger=ledger,
        historical_replay=historical_replay,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )
    return store, ledger, result, counts


def _calendar_receipt(
    *,
    captured_at: str = "2026-08-08T05:30:00+00:00",
    as_of_cutoff: str = CUTOFF,
) -> SourceCaptureReceipt:
    route_id = "tushare.eco_cal.eur"
    payload = {
        "schema_version": "source_capture_receipt_v1",
        "identity": {
            "source_family": "tushare",
            "route_id": route_id,
            "request_hash": canonical_hash({"route_id": route_id, "as_of": AS_OF}),
            "capture_id": f"test-calendar-{route_id}-{AS_OF}",
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
            "permission_tier": "test_fixture",
            "api_version": "pro-v1",
            "parser_version": "eco_cal_parser_v2",
        },
        "time": {
            "released_at": captured_at,
            "vintage_at": captured_at,
            "captured_at": captured_at,
            "knowledge_available_at": captured_at,
        },
        "pit": {
            "pit_mode": "OBSERVED_LIVE",
            "as_of_cutoff": as_of_cutoff,
            "eligible": True,
            "blocker_codes": [],
            "vintage_query": None,
        },
        "content": {
            "raw_content_hash": canonical_hash({"rows": [route_id]}),
            "normalized_row_count": 1,
            "schema_hash": canonical_hash({"schema": "eco-cal-v2"}),
        },
        "coverage": {
            "requested_start": AS_OF,
            "requested_end": AS_OF,
            "observed_start": AS_OF,
            "observed_end": AS_OF,
            "dimensions": {"route_id": [route_id]},
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
    return SourceCaptureReceipt.seal(payload)


@pytest.mark.parametrize(
    ("route_id", "expected_counts"),
    (
        (
            "ecb.eu_real_economy",
            {"real_economy_ecb": len(REAL_ECONOMY_ECB_SERIES_IDS)},
        ),
        ("ecb.euro_macro", {"financial_ecb": len(ECB_SERIES_IDS)}),
        ("market.euro_fx", {"fx": 1}),
    ),
)
def test_route_only_capture_calls_only_the_requested_europe_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_id: str,
    expected_counts: dict[str, int],
) -> None:
    from mosaic.dataflows import europe_macro_archive

    monkeypatch.setattr(europe_macro_archive, "_capture_now", lambda: CAPTURED_AT)
    store = EuropeMacroArchiveStore(tmp_path / "europe-route-only.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "europe-route-ledger.sqlite3")
    counts, fetch_official, fetch_tushare = _callbacks()

    result = archive_europe_macro_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        observation_start=OBSERVATION_START,
        requested_route_ids=(route_id,),
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert [
        receipt.as_dict()["identity"]["route_id"]
        for receipt in result.source_receipts
    ] == [route_id]
    assert result.coverage_receipt.as_dict()["required_route_ids"] == [route_id]
    assert result.coverage_receipt.as_dict()["coverage_complete"] is True
    if route_id == "ecb.eu_real_economy":
        assert result.source_receipts[0].as_dict()["coverage"]["dimensions"] == {
            "series_id": list(REAL_ECONOMY_ECB_SERIES_IDS)
        }
    elif route_id == "ecb.euro_macro":
        assert result.source_receipts[0].as_dict()["coverage"]["dimensions"] == {
            "series_id": list(ECB_SERIES_IDS)
        }
    assert counts == {
        "financial_ecb": expected_counts.get("financial_ecb", 0),
        "real_economy_ecb": expected_counts.get("real_economy_ecb", 0),
        "fx": expected_counts.get("fx", 0),
    }


def test_empty_cache_archives_three_physical_routes_with_exact_pit_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, counts = _archive(tmp_path, monkeypatch)

    assert result.cache_hit is False
    assert result.group is not None
    assert store.row_count() == 1
    assert counts == {
        "financial_ecb": len(ECB_SERIES_IDS),
        "real_economy_ecb": len(REAL_ECONOMY_ECB_SERIES_IDS),
        "fx": 1,
    }
    by_route = {
        receipt.as_dict()["identity"]["route_id"]: receipt.as_dict()
        for receipt in result.source_receipts
    }
    assert set(by_route) == {
        "ecb.eu_real_economy",
        "ecb.euro_macro",
        "market.euro_fx",
    }
    assert by_route["ecb.eu_real_economy"]["pit"]["pit_mode"] == (
        "AUTHORITATIVE_VINTAGE_REPLAY"
    )
    assert by_route["ecb.euro_macro"]["pit"]["pit_mode"] == (
        "AUTHORITATIVE_VINTAGE_REPLAY"
    )
    assert by_route["market.euro_fx"]["pit"]["pit_mode"] == "OBSERVED_LIVE"
    assert result.coverage_receipt.as_dict()["coverage_complete"] is True
    assert ledger.row_counts()["source_capture_receipts"] == 3


def test_warm_retry_is_zero_transport_and_hash_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, first, counts = _archive(tmp_path, monkeypatch)
    before = dict(counts)

    second = archive_europe_macro_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        observation_start=OBSERVATION_START,
        store=store,
        ledger=ledger,
        fetch_official=_callbacks()[1],
        fetch_tushare=_callbacks()[2],
    )

    assert second.cache_hit is True
    assert counts == before
    assert [row.receipt_hash for row in second.source_receipts] == [
        row.receipt_hash for row in first.source_receipts
    ]
    assert store.row_count() == 1


def test_concurrent_same_key_publishes_one_group_and_calls_transport_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import europe_macro_archive

    monkeypatch.setattr(europe_macro_archive, "_capture_now", lambda: CAPTURED_AT)
    store = EuropeMacroArchiveStore(tmp_path / "europe-macro.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    counts, fetch_official, fetch_tushare = _callbacks()

    def capture():
        return archive_europe_macro_sources(
            as_of_date=AS_OF,
            cutoff_at=CUTOFF,
            observation_start=OBSERVATION_START,
            store=store,
            ledger=ledger,
            fetch_official=fetch_official,
            fetch_tushare=fetch_tushare,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: capture(), range(4)))

    assert counts == {
        "financial_ecb": len(ECB_SERIES_IDS),
        "real_economy_ecb": len(REAL_ECONOMY_ECB_SERIES_IDS),
        "fx": 1,
    }
    assert sum(not result.cache_hit for result in results) == 1
    assert len(
        {
            tuple(receipt.receipt_hash for receipt in result.source_receipts)
            for result in results
        }
    ) == 1
    assert store.row_count() == 1


def test_historical_cache_miss_replays_both_ecb_routes_and_blocks_live_fx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    callbacks = _callbacks()
    store, ledger, result, counts = _archive(
        tmp_path,
        monkeypatch,
        captured_at=datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc),
        callbacks=callbacks,
    )

    assert counts == {
        "financial_ecb": len(ECB_SERIES_IDS),
        "real_economy_ecb": len(REAL_ECONOMY_ECB_SERIES_IDS),
        "fx": 0,
    }
    assert [
        receipt.as_dict()["identity"]["route_id"]
        for receipt in result.source_receipts
    ] == ["ecb.eu_real_economy", "ecb.euro_macro"]
    coverage = result.coverage_receipt.as_dict()
    assert coverage["coverage_complete"] is False
    assert coverage["blocker_codes"] == ["CAPTURE_AFTER_AS_OF_CUTOFF"]
    assert store.row_count() == 1
    assert ledger.row_counts()["source_capture_receipts"] == 2


@pytest.mark.parametrize(
    ("route_id", "expected_counts"),
    (
        (
            "ecb.eu_real_economy",
            {
                "financial_ecb": 0,
                "real_economy_ecb": len(REAL_ECONOMY_ECB_SERIES_IDS),
                "fx": 0,
            },
        ),
        (
            "ecb.euro_macro",
            {
                "financial_ecb": len(ECB_SERIES_IDS),
                "real_economy_ecb": 0,
                "fx": 0,
            },
        ),
        (
            "market.euro_fx",
            {"financial_ecb": 0, "real_economy_ecb": 0, "fx": 1},
        ),
    ),
)
def test_historical_replay_captures_one_europe_route_without_backdating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_id: str,
    expected_counts: dict[str, int],
) -> None:
    from mosaic.dataflows import europe_macro_archive

    captured_at = datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc)
    counts, fetch_official, fetch_tushare = _callbacks()
    monkeypatch.setattr(europe_macro_archive, "_capture_now", lambda: captured_at)
    store = EuropeMacroArchiveStore(tmp_path / "europe-replay.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "europe-replay-ledger.sqlite3")

    result = archive_europe_macro_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        observation_start=OBSERVATION_START,
        requested_route_ids=(route_id,),
        historical_replay=True,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert counts == expected_counts
    assert result.group is not None
    assert result.group["historical_replay"] is True
    assert result.group["requested_cutoff_at"] == CUTOFF
    assert result.group["cutoff_at"] == captured_at.isoformat()
    assert result.group["captured_at"] == captured_at.isoformat()
    assert [
        receipt.as_dict()["identity"]["route_id"]
        for receipt in result.source_receipts
    ] == [route_id]
    receipt = result.source_receipts[0].as_dict()
    assert receipt["time"]["captured_at"] == captured_at.isoformat()
    assert receipt["pit"]["as_of_cutoff"] == captured_at.isoformat()
    assert result.coverage_receipt.as_dict()["coverage_complete"] is True
    assert result.coverage_receipt.as_dict()["window"]["end"] == (
        captured_at.isoformat()
    )
    if route_id == "market.euro_fx":
        historical_fx = europe_macro_archive._fx_observation(
            result.group, result.source_receipts[0]
        )
        assert historical_fx["released_at"] == CUTOFF
        assert historical_fx["vintage_at"] == CUTOFF
        live_group = dict(result.group)
        live_group.pop("historical_replay", None)
        live_group.pop("historical_replay_time_policy_version", None)
        live_fx = europe_macro_archive._fx_observation(
            live_group, result.source_receipts[0]
        )
        assert live_fx["released_at"] == captured_at.isoformat()
        assert live_fx["vintage_at"] == captured_at.isoformat()
    assert store.row_count() == 1
    assert ledger.row_counts()["source_capture_receipts"] == 1


def test_historical_replay_uses_capture_time_for_ecb_selection_but_live_uses_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import europe_macro_archive

    captured_at = datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(europe_macro_archive, "_capture_now", lambda: captured_at)
    _, fetch_official, fetch_tushare = _callbacks(
        valid_from="2026-08-09T05:00:00+00:00"
    )

    replay = archive_europe_macro_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        observation_start=OBSERVATION_START,
        requested_route_ids=("ecb.eu_real_economy",),
        historical_replay=True,
        store=EuropeMacroArchiveStore(tmp_path / "replay.sqlite3"),
        ledger=AgentDataMaterializationLedger(tmp_path / "replay-ledger.sqlite3"),
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )
    assert replay.group is not None
    assert replay.coverage_receipt.as_dict()["coverage_complete"] is True

    live = archive_europe_macro_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        observation_start=OBSERVATION_START,
        requested_route_ids=("ecb.eu_real_economy",),
        store=EuropeMacroArchiveStore(tmp_path / "live.sqlite3"),
        ledger=AgentDataMaterializationLedger(tmp_path / "live-ledger.sqlite3"),
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )
    assert live.group is None
    assert live.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]


def test_future_as_of_rejects_before_transport_or_archive_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import europe_macro_archive

    monkeypatch.setattr(europe_macro_archive, "_capture_now", lambda: CAPTURED_AT)
    counts, fetch_official, fetch_tushare = _callbacks()
    store = EuropeMacroArchiveStore(tmp_path / "europe-macro.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")

    result = archive_europe_macro_sources(
        as_of_date="2026-08-09",
        cutoff_at="2026-08-09T15:00:00+08:00",
        observation_start=OBSERVATION_START,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert counts == {"financial_ecb": 0, "real_economy_ecb": 0, "fx": 0}
    assert result.group is None
    assert result.source_receipts == ()
    assert result.coverage_receipt.as_dict()["blocker_codes"] == [
        "CAPTURE_BEFORE_AS_OF_WINDOW"
    ]
    assert store.row_count() == 0


@pytest.mark.parametrize("route_id", ("ecb.eu_real_economy", "ecb.euro_macro"))
def test_ecb_history_without_a_cutoff_valid_row_rolls_back_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route_id: str
) -> None:
    from mosaic.dataflows import europe_macro_archive

    monkeypatch.setattr(europe_macro_archive, "_capture_now", lambda: CAPTURED_AT)
    store = EuropeMacroArchiveStore(tmp_path / "europe-macro.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    _, fetch_official, fetch_tushare = _callbacks(
        valid_from="2026-08-09T05:00:00+00:00"
    )
    result = archive_europe_macro_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        observation_start=OBSERVATION_START,
        requested_route_ids=(route_id,),
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )

    assert result.group is None
    assert result.source_receipts == ()
    assert result.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]
    assert store.row_count() == 0
    assert ledger.row_counts()["source_capture_receipts"] == 0


def test_wrapped_provider_timeout_is_classified_as_transport_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    callbacks = list(_callbacks())

    def timed_out_fetch(**kwargs):
        del kwargs
        try:
            raise requests.ReadTimeout("private timeout detail")
        except requests.ReadTimeout as exc:
            raise DataVendorUnavailable("redacted provider failure") from exc

    callbacks[1] = timed_out_fetch
    store, ledger, result, _ = _archive(
        tmp_path, monkeypatch, callbacks=tuple(callbacks)
    )

    assert result.group is None
    assert result.source_receipts == ()
    coverage = result.coverage_receipt.as_dict()
    assert coverage["blocker_codes"] == ["TRANSPORT_FAILED"]
    assert {row["status"] for row in coverage["route_results"]} == {
        "TRANSPORT_FAILED"
    }
    assert store.row_count() == 0
    assert ledger.row_counts()["source_capture_receipts"] == 0


def test_ecb_vintage_selector_applies_delete_tombstones_and_cutoff() -> None:
    rows = [
        {
            "TIME_PERIOD": "2026-01-01",
            "OBS_VALUE": 2.0,
            "ACTION": "Replace",
            "VALID_FROM": "2026-02-01T00:00:00+00:00",
            "VALID_TO": "",
        },
        {
            "TIME_PERIOD": "2026-01-01",
            "OBS_VALUE": None,
            "ACTION": "Delete",
            "VALID_FROM": "",
            "VALID_TO": "2026-03-01T00:00:00+00:00",
        },
        {
            "TIME_PERIOD": "2026-01-01",
            "OBS_VALUE": 3.0,
            "ACTION": "Replace",
            "VALID_FROM": "2026-09-01T00:00:00+00:00",
            "VALID_TO": "",
        },
    ]

    assert select_ecb_vintage_rows(
        rows, cutoff_at="2026-02-15T00:00:00+00:00"
    )[0]["OBS_VALUE"] == 2.0
    assert select_ecb_vintage_rows(
        rows, cutoff_at="2026-08-08T07:00:00+00:00"
    ) == []


def test_receipt_bound_compiler_builds_both_roles_without_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replay_captured_at = CAPTURED_AT + timedelta(days=1)
    store, ledger, result, counts = _archive(
        tmp_path,
        monkeypatch,
        captured_at=replay_captured_at,
        historical_replay=True,
    )
    ledger.append_source_capture(
        _calendar_receipt(
            captured_at=replay_captured_at.isoformat(),
            as_of_cutoff=replay_captured_at.isoformat(),
        )
    )
    before = dict(counts)
    status_calls: list[tuple[str, str]] = []
    source_status = ledger.source_status

    def spy_source_status(*, as_of: str, route_id: str) -> dict[str, object]:
        status_calls.append((as_of, route_id))
        return source_status(as_of=as_of, route_id=route_id)

    monkeypatch.setattr(ledger, "source_status", spy_source_status)

    built = compile_europe_macro_snapshots(
        capture_key=result.group["capture_key"],
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )
    from mosaic.dataflows import europe_macro_archive

    monkeypatch.setattr(
        europe_macro_archive,
        "_capture_now",
        lambda: CAPTURED_AT + timedelta(seconds=1),
    )
    replay = compile_europe_macro_snapshots(
        capture_key=result.group["capture_key"],
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )
    import json

    from mosaic.dataflows.macro_snapshots import validate_role_snapshot

    for role, snapshot in built.snapshots.items():
        persisted = json.loads(
            (tmp_path / "snapshots" / result.group["as_of_date"] / f"{role}.json").read_text(
                encoding="utf-8"
            )
        )
        assert validate_role_snapshot(
            persisted, role, result.group["as_of_date"]
        ) == snapshot

    assert counts == before
    assert status_calls == [
        ("2026-08-09", "tushare.eco_cal.eur"),
        ("2026-08-09", "tushare.eco_cal.eur"),
    ]
    assert set(built.snapshots) == {
        "eu_economy",
        "euro_area_financial_conditions",
    }
    economy_ids = {
        row["series_id"] for row in built.snapshots["eu_economy"]["observations"]
    }
    assert economy_ids == {
        "eu_exports_goods_services",
        "eu_gdp",
        "eu_hicp",
        "eu_household_consumption",
        "eu_imports_goods_services",
        "eu_unemployment",
        "euro_area_industrial_production",
    }
    financial_ids = {
        row["series_id"]
        for row in built.snapshots["euro_area_financial_conditions"]["observations"]
    }
    assert {
        "ecb_dfr",
        "euro_area_curve_10y",
        "euro_area_bank_credit_loans",
        "eu_large_bank_simultaneous_default_probability",
        "eu_sovereign_simultaneous_default_probability",
        "eur_usd_market",
    } <= financial_ids
    assert "eur_ciss" not in financial_ids
    assert all(
        receipt.as_dict()["earliest_trustworthy_date"] == AS_OF
        for receipt in built.build_receipts
    )
    assert [receipt.receipt_hash for receipt in replay.build_receipts] == [
        receipt.receipt_hash for receipt in built.build_receipts
    ]
    assert ledger.row_counts()["snapshot_build_receipts"] == 2


def test_financial_only_archive_closes_context_into_ecb_receipt_and_compiles_one_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, _ = _archive(
        tmp_path,
        monkeypatch,
        requested_route_ids=("ecb.euro_macro", "market.euro_fx"),
    )
    assert result.group is not None
    assert set(
        receipt.as_dict()["identity"]["route_id"]
        for receipt in result.source_receipts
    ) == {"ecb.euro_macro", "market.euro_fx"}
    ecb_receipt = next(
        receipt.as_dict()
        for receipt in result.source_receipts
        if receipt.as_dict()["identity"]["route_id"] == "ecb.euro_macro"
    )
    combined_series = (
        result.group["ecb"]["series"]
        + result.group["ecb_real_economy"]["series"]
    )
    combined_count = len(ECB_SERIES_IDS) + len(REAL_ECONOMY_ECB_SERIES_IDS)
    assert len(result.group["ecb_real_economy"]["series"]) == len(
        REAL_ECONOMY_ECB_SERIES_IDS
    )
    assert ecb_receipt["transport"]["page_count"] == combined_count
    assert ecb_receipt["content"]["normalized_row_count"] == combined_count
    assert set(ecb_receipt["coverage"]["dimensions"]["series_id"]) == {
        *ECB_SERIES_IDS,
        *REAL_ECONOMY_ECB_SERIES_IDS,
    }
    assert ecb_receipt["content"]["raw_content_hash"] == canonical_hash(
        {item["series_key"]: item["payload_hash"] for item in combined_series}
    )
    assert result.coverage_receipt.as_dict()["coverage_complete"] is True

    calendar = _calendar_receipt()
    ledger.append_source_capture(calendar)
    built = compile_europe_macro_snapshots(
        capture_key=result.group["capture_key"],
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
        requested_roles=("euro_area_financial_conditions",),
        exact_calendar_evidence_hash=calendar.receipt_hash,
    )

    assert set(built.snapshots) == {"euro_area_financial_conditions"}
    assert len(built.build_receipts) == 1
    build = built.build_receipts[0].as_dict()
    assert build["agent_id"] == "euro_area_financial_conditions"
    archive_hashes = {
        receipt.receipt_hash for receipt in result.source_receipts
    }
    assert set(build["source_receipt_hashes"]) == archive_hashes | {
        calendar.receipt_hash
    }
    assert not any(
        receipt.as_dict()["agent_id"] == "eu_economy"
        for receipt in built.build_receipts
    )


def test_historical_replay_compiler_uses_capture_cutoff_for_observation_knowledge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import europe_macro_archive

    captured_at = datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(europe_macro_archive, "_capture_now", lambda: captured_at)
    _, fetch_official, fetch_tushare = _callbacks(
        valid_from="2026-08-09T05:00:00+00:00"
    )
    store = EuropeMacroArchiveStore(tmp_path / "europe-replay.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "europe-replay-ledger.sqlite3")
    archive = archive_europe_macro_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        observation_start=OBSERVATION_START,
        requested_route_ids=("ecb.eu_real_economy", "ecb.euro_macro"),
        historical_replay=True,
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )
    assert archive.group is not None
    calendar = _calendar_receipt()
    ledger.append_source_capture(calendar)

    built = compile_europe_macro_snapshots(
        capture_key=archive.group["capture_key"],
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
        requested_roles=("eu_economy",),
        exact_calendar_evidence_hash=calendar.receipt_hash,
    )
    row = next(
        observation
        for observation in built.snapshots["eu_economy"]["observations"]
        if observation["series_id"] == "eu_exports_goods_services"
    )
    assert row["released_at"] == "2026-08-09T05:00:00+00:00"
    assert row["period_end"] <= AS_OF


def test_archive_recomputes_hash_when_loading_private_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, result, _ = _archive(tmp_path, monkeypatch)
    with sqlite3.connect(store.path) as conn:
        conn.execute("DROP TRIGGER europe_macro_capture_groups_no_update")
        conn.execute(
            "UPDATE europe_macro_capture_groups SET payload_zlib = ? WHERE capture_key = ?",
            (zlib.compress(b"{}"), result.group["capture_key"]),
        )

    with pytest.raises(ValueError, match="hash mismatch"):
        store.load_group(result.group["capture_key"])

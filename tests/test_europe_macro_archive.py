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
    EUROSTAT_SERIES_KEYS,
    EuropeMacroArchiveStore,
    archive_europe_macro_sources,
    compile_europe_macro_snapshots,
    select_ecb_vintage_rows,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_source_contracts import EU_SERIES_MAP
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
    dataset_updated: str | None = None,
) -> dict:
    raw = f"{provider}:{series_key}:{rows!r}".encode()
    result = {
        "adapter_version": "official_macro_adapters_v1",
        "provider": provider,
        "series_key": series_key,
        "source": source,
        "usage_mode": "PRIMARY",
        "request_url": f"https://example.invalid/{provider}/{series_key}",
        "content_type": "text/csv" if provider == "ECB" else "application/json",
        "retrieved_at": retrieved_at,
        "payload_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "raw_payload_b64": base64.b64encode(raw).decode("ascii"),
        "row_count": len(rows),
        "rows": rows,
        "pit_status": (
            "AUTHORITATIVE_VINTAGE_HISTORY"
            if provider == "ECB"
            else "CURRENT_RESPONSE_REQUIRES_RELEASE_VINTAGE_JOIN"
        ),
    }
    if dataset_updated is not None:
        result["dataset_updated"] = dataset_updated
    return result


def _callbacks(
    *,
    dataset_updated: str = "2026-08-07T09:00:00+00:00",
    eurostat_retrieved_at: str = "2026-08-08T05:55:00+00:00",
) -> tuple[dict[str, int], object, object]:
    counts = {"ecb": 0, "eurostat": 0, "fx": 0}
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
        if provider == "ECB":
            ordinal = increment("ecb")
            assert include_history is True
            assert observation_start == OBSERVATION_START
            assert observation_end == AS_OF
            rows = [
                {
                    "KEY": series_key,
                    "TIME_PERIOD": "2026-08-07",
                    "OBS_VALUE": float(ordinal),
                    "ACTION": "Replace",
                    "VALID_FROM": "2026-08-08T05:00:00+00:00",
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
        assert provider == "EUROSTAT"
        ordinal = increment("eurostat")
        assert include_history is False
        contract = EU_SERIES_MAP[series_key]
        dimensions = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in contract["dimensions"].split(",")
        }
        period = "2026-Q2" if series_key == "eu27_real_gdp" else "2026-07"
        rows = [{**dimensions, "time": period, "value": ordinal}]
        return _raw_result(
            provider=provider,
            series_key=series_key,
            rows=rows,
            source=f"eurostat.{contract['dataset']}",
            retrieved_at=eurostat_retrieved_at,
            dataset_updated=dataset_updated,
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
        store=store,
        ledger=ledger,
        fetch_official=fetch_official,
        fetch_tushare=fetch_tushare,
    )
    return store, ledger, result, counts


def _calendar_receipt() -> SourceCaptureReceipt:
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
            "released_at": "2026-08-08T05:30:00+00:00",
            "vintage_at": "2026-08-08T05:30:00+00:00",
            "captured_at": "2026-08-08T05:30:00+00:00",
            "knowledge_available_at": "2026-08-08T05:30:00+00:00",
        },
        "pit": {
            "pit_mode": "OBSERVED_LIVE",
            "as_of_cutoff": CUTOFF,
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


def test_empty_cache_archives_three_physical_routes_with_exact_pit_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, counts = _archive(tmp_path, monkeypatch)

    assert result.cache_hit is False
    assert result.group is not None
    assert store.row_count() == 1
    assert counts == {
        "ecb": len(ECB_SERIES_IDS),
        "eurostat": len(EUROSTAT_SERIES_KEYS),
        "fx": 1,
    }
    by_route = {
        receipt.as_dict()["identity"]["route_id"]: receipt.as_dict()
        for receipt in result.source_receipts
    }
    assert set(by_route) == {
        "ecb.euro_macro",
        "eurostat.euro_macro",
        "market.euro_fx",
    }
    assert by_route["ecb.euro_macro"]["pit"]["pit_mode"] == (
        "AUTHORITATIVE_VINTAGE_REPLAY"
    )
    assert by_route["eurostat.euro_macro"]["pit"]["pit_mode"] == "OBSERVED_LIVE"
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
        "ecb": len(ECB_SERIES_IDS),
        "eurostat": len(EUROSTAT_SERIES_KEYS),
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


def test_historical_cache_miss_replays_only_ecb_and_blocks_forward_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    callbacks = _callbacks()
    store, ledger, result, counts = _archive(
        tmp_path,
        monkeypatch,
        captured_at=datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc),
        callbacks=callbacks,
    )

    assert counts == {"ecb": len(ECB_SERIES_IDS), "eurostat": 0, "fx": 0}
    assert [
        receipt.as_dict()["identity"]["route_id"]
        for receipt in result.source_receipts
    ] == ["ecb.euro_macro"]
    coverage = result.coverage_receipt.as_dict()
    assert coverage["coverage_complete"] is False
    assert coverage["blocker_codes"] == ["CAPTURE_AFTER_AS_OF_CUTOFF"]
    assert store.row_count() == 1
    assert ledger.row_counts()["source_capture_receipts"] == 1


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

    assert counts == {"ecb": 0, "eurostat": 0, "fx": 0}
    assert result.group is None
    assert result.source_receipts == ()
    assert result.coverage_receipt.as_dict()["blocker_codes"] == [
        "CAPTURE_BEFORE_AS_OF_WINDOW"
    ]
    assert store.row_count() == 0


def test_forward_dataset_updated_after_cutoff_rolls_back_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, _ = _archive(
        tmp_path,
        monkeypatch,
        callbacks=_callbacks(dataset_updated="2026-08-08T08:00:00+00:00"),
    )

    assert result.group is None
    assert result.source_receipts == ()
    assert result.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]
    assert store.row_count() == 0
    assert ledger.row_counts()["source_capture_receipts"] == 0


def test_forward_dataset_updated_after_retrieval_rolls_back_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, _ = _archive(
        tmp_path,
        monkeypatch,
        callbacks=_callbacks(
            dataset_updated="2026-08-08T06:00:00+00:00",
            eurostat_retrieved_at="2026-08-08T05:55:00+00:00",
        ),
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
            "VALID_FROM": "2026-03-01T00:00:00+00:00",
            "VALID_TO": "",
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
    store, ledger, result, counts = _archive(tmp_path, monkeypatch)
    ledger.append_source_capture(_calendar_receipt())
    before = dict(counts)

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
    assert set(built.snapshots) == {
        "eu_economy",
        "euro_area_financial_conditions",
    }
    economy_ids = {
        row["series_id"] for row in built.snapshots["eu_economy"]["observations"]
    }
    assert {"eu_gdp", "eu_hicp", "eu_unemployment", "eu_retail_volume"} <= (
        economy_ids
    )
    financial_ids = {
        row["series_id"]
        for row in built.snapshots["euro_area_financial_conditions"]["observations"]
    }
    assert {
        "ecb_dfr",
        "euro_area_curve_10y",
        "euro_area_bank_credit_loans",
        "eur_ciss",
        "eur_usd_market",
    } <= financial_ids
    assert all(
        receipt.as_dict()["earliest_trustworthy_date"] == AS_OF
        for receipt in built.build_receipts
    )
    assert [receipt.receipt_hash for receipt in replay.build_receipts] == [
        receipt.receipt_hash for receipt in built.build_receipts
    ]
    assert ledger.row_counts()["snapshot_build_receipts"] == 2


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

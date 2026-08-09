from __future__ import annotations

import base64
import hashlib
import sqlite3
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    SourceCaptureReceipt,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_snapshots import ALFRED_SERIES_ROLE_MAP
from mosaic.dataflows.us_macro_archive import (
    ARCHIVE_LOCK_TIMEOUT_SECONDS,
    USMacroArchiveStore,
    archive_us_macro_sources,
    compile_us_macro_snapshots,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.macro_series_backfill import (
    project_alfred_capture_to_macro_series,
    project_tushare_capture_to_macro_series,
)


AS_OF = "2026-08-08"
CUTOFF = "2026-08-08T15:00:00+08:00"
OBSERVATION_START = "2025-01-01"
CAPTURED_AT = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)


def test_store_writer_wait_covers_bounded_us_macro_capture(tmp_path: Path) -> None:
    store = USMacroArchiveStore(tmp_path / "us-macro.sqlite3")

    with store._connect() as conn:
        busy_timeout_ms = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])

    assert busy_timeout_ms == ARCHIVE_LOCK_TIMEOUT_SECONDS * 1000
    assert ARCHIVE_LOCK_TIMEOUT_SECONDS >= 60 * 60


def _source_callbacks(
    *,
    as_of: str = AS_OF,
    cutoff: str = CUTOFF,
    observation_start: str = OBSERVATION_START,
    vintage: str = "2026-08-07",
    row_realtime_start: str | None = None,
    retrieved_at: str = "2026-08-08T05:55:00+00:00",
    fail_series: str | None = None,
    latest_treasury_partial: bool = False,
) -> tuple[dict[str, int], object, object, object, object, object]:
    counts = {
        "select": 0,
        "alfred": 0,
        "fomc": 0,
        "nyfed": 0,
        "us_tycr": 0,
        "fx_daily": 0,
    }
    lock = threading.Lock()

    def increment(key: str) -> None:
        with lock:
            counts[key] += 1

    def select_vintage(series_id: str, *, as_of_cutoff: str) -> str:
        increment("select")
        assert series_id in ALFRED_SERIES_ROLE_MAP
        assert as_of_cutoff == cutoff
        return vintage

    def fetch_vintage(
        series_id: str,
        *,
        observation_start: str,
        observation_end: str,
        vintage_date: str,
    ) -> dict:
        increment("alfred")
        assert observation_start == observation_start_value
        assert observation_end == as_of
        assert vintage_date == vintage
        if series_id == fail_series:
            return {"observations": []}
        value = float(sum(ord(char) for char in series_id) % 1000) / 10
        return {
            "realtime_start": vintage,
            "realtime_end": vintage,
            "observations": [
                {
                    "date": vintage,
                    "realtime_start": row_realtime_start or vintage,
                    "realtime_end": "9999-12-31",
                    "value": str(value),
                }
            ],
        }

    observation_start_value = observation_start

    def fetch_fomc(*, as_of: str) -> dict:
        increment("fomc")
        assert as_of == cutoff
        raw = f"<rss><as-of>{as_of_value}</as-of></rss>".encode()
        return {
            "adapter_version": "official_macro_adapters_v1",
            "provider": "FEDERAL_RESERVE",
            "series_key": "fomc_statement",
            "source": "official.fomc_statement",
            "request_url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
            "retrieved_at": retrieved_at,
            "payload_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "raw_payload_b64": base64.b64encode(raw).decode("ascii"),
            "row_count": 1,
            "rows": [
                {
                    "title": "Federal Reserve issues FOMC statement",
                    "published_at": "2026-07-29T18:00:00+00:00",
                    "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
                }
            ],
            "pit_status": "CURRENT_RESPONSE_REQUIRES_FORWARD_ARCHIVE",
        }

    def fetch_nyfed(
        *, rate_type: str, start_date: str, end_date: str, as_of: str
    ) -> dict:
        increment("nyfed")
        assert rate_type in {"EFFR", "SOFR"}
        assert start_date == market_start_value
        assert end_date == as_of_value
        assert as_of == cutoff
        raw = f'{{"rate":"{rate_type}","as_of":"{as_of_value}"}}'.encode()
        return {
            "adapter_version": "official_macro_adapters_v1",
            "provider": "NY_FED",
            "series_key": rate_type.casefold(),
            "source": f"official.nyfed_{rate_type.casefold()}",
            "request_url": f"https://markets.newyorkfed.org/api/rates/secured/{rate_type.casefold()}/search.json",
            "retrieved_at": retrieved_at,
            "payload_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "raw_payload_b64": base64.b64encode(raw).decode("ascii"),
            "row_count": 1,
            "rows": [
                {
                    "effective_date": vintage,
                    "rate_type": rate_type,
                    "percent_rate": 5.25 if rate_type == "EFFR" else 5.31,
                    "revision_indicator": "",
                }
            ],
            "pit_status": "CURRENT_RESPONSE_REQUIRES_OBSERVED_LIVE_ARCHIVE",
        }

    def fetch_tushare(*, endpoint: str, **params: str) -> list[dict]:
        increment(endpoint)
        expected_dates = {
            "start_date": observation_start_value.replace("-", ""),
            "end_date": as_of_value.replace("-", ""),
        }
        if endpoint == "us_tycr":
            assert params == expected_dates
            rows = [
                {
                    "date": vintage.replace("-", ""),
                    "m3": 5.41,
                    "y2": 4.75,
                    "y10": 4.03,
                    "y30": 4.21,
                }
            ]
            if latest_treasury_partial:
                previous = (
                    date.fromisoformat(vintage) - timedelta(days=1)
                ).strftime("%Y%m%d")
                rows.insert(0, {**rows[0], "date": previous})
                rows[-1]["y30"] = None
            return rows
        assert endpoint == "fx_daily"
        assert params == {"ts_code": "USDCNH.FXCM", **expected_dates}
        return [
            {
                "ts_code": "USDCNH.FXCM",
                "trade_date": vintage.replace("-", ""),
                "bid_close": 7.18,
                "ask_close": 7.20,
            }
        ]

    as_of_value = as_of
    market_start_value = max(
        date.fromisoformat(observation_start_value),
        date.fromisoformat(as_of_value) - timedelta(days=35),
    ).isoformat()
    return counts, select_vintage, fetch_vintage, fetch_fomc, fetch_nyfed, fetch_tushare


def _archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    captured_at: datetime = CAPTURED_AT,
    callbacks: tuple[dict[str, int], object, object, object, object, object] | None = None,
):
    from mosaic.dataflows import us_macro_archive

    monkeypatch.setattr(us_macro_archive, "_capture_now", lambda: captured_at)
    store = USMacroArchiveStore(tmp_path / "us-macro.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    selected = callbacks or _source_callbacks()
    counts, select_vintage, fetch_vintage, fetch_fomc, fetch_nyfed, fetch_tushare = selected
    result = archive_us_macro_sources(
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        observation_start=OBSERVATION_START,
        store=store,
        ledger=ledger,
        select_vintage=select_vintage,
        fetch_vintage=fetch_vintage,
        fetch_fomc=fetch_fomc,
        fetch_nyfed=fetch_nyfed,
        fetch_tushare=fetch_tushare,
    )
    return store, ledger, result, counts


def _calendar_receipt(route_id: str) -> SourceCaptureReceipt:
    request_hash = canonical_hash({"route_id": route_id, "as_of": AS_OF})
    payload = {
        "schema_version": "source_capture_receipt_v1",
        "identity": {
            "source_family": "tushare",
            "route_id": route_id,
            "request_hash": request_hash,
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


def test_empty_cache_calls_existing_adapters_and_atomically_publishes_five_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, counts = _archive(tmp_path, monkeypatch)

    assert result.cache_hit is False
    assert result.group is not None
    assert store.row_count() == 1
    assert counts == {
        "select": len(ALFRED_SERIES_ROLE_MAP),
        "alfred": len(ALFRED_SERIES_ROLE_MAP),
        "fomc": 1,
        "nyfed": 2,
        "us_tycr": 1,
        "fx_daily": 1,
    }
    by_route = {
        receipt.as_dict()["identity"]["route_id"]: receipt
        for receipt in result.source_receipts
    }
    assert set(by_route) == {
        "alfred.us_macro",
        "market.us_conditions",
        "official.us_policy",
        "tushare.fx_daily",
        "tushare.us_tycr",
    }
    assert by_route["alfred.us_macro"].as_dict()["pit"]["pit_mode"] == (
        "AUTHORITATIVE_VINTAGE_REPLAY"
    )
    assert by_route["market.us_conditions"].as_dict()["pit"]["pit_mode"] == (
        "OBSERVED_LIVE"
    )
    assert by_route["tushare.us_tycr"].as_dict()["pit"]["pit_mode"] == "OBSERVED_LIVE"
    assert by_route["tushare.fx_daily"].as_dict()["pit"]["pit_mode"] == "OBSERVED_LIVE"
    assert result.coverage_receipt.as_dict()["coverage_complete"] is True
    assert result.group["market_conditions"]["requested_start"] == "2026-07-04"
    latest_complete_date = "2026-08-07"
    vintage_queries = [
        {
            "path": "series/vintagedates",
            "params": {
                "api_key": "<redacted>",
                "file_type": "json",
                "limit": 1,
                "offset": 0,
                "realtime_end": latest_complete_date,
                "realtime_start": "1776-07-04",
                "series_id": item["series_id"],
                "sort_order": "desc",
            },
        }
        for item in result.group["alfred"]["series"]
    ]
    observation_queries = [
        {
            "path": "series/observations",
            "params": {
                "api_key": "<redacted>",
                "file_type": "json",
                "observation_end": AS_OF,
                "observation_start": OBSERVATION_START,
                "series_id": item["series_id"],
                "vintage_dates": item["vintage_date"],
            },
        }
        for item in result.group["alfred"]["series"]
    ]
    assert by_route["alfred.us_macro"].as_dict()["identity"]["request_hash"] == (
        canonical_hash(
            {
                "base_url": "https://api.stlouisfed.org/fred",
                "observation_queries": observation_queries,
                "route_id": "alfred.us_macro",
                "vintage_queries": vintage_queries,
            }
        )
    )
    assert by_route["alfred.us_macro"].as_dict()["transport"]["query_keys"] == [
        "api_key",
        "file_type",
        "limit",
        "observation_end",
        "observation_start",
        "offset",
        "realtime_end",
        "realtime_start",
        "series_id",
        "sort_order",
        "vintage_dates",
    ]
    assert by_route["official.us_policy"].as_dict()["identity"]["request_hash"] == (
        canonical_hash(
            {
                "as_of_date": AS_OF,
                "request_url": result.group["official_policy"]["request_url"],
                "route_id": "official.us_policy",
            }
        )
    )
    assert by_route["market.us_conditions"].as_dict()["identity"]["request_hash"] == (
        canonical_hash(
            {
                "as_of_date": AS_OF,
                "end_date": AS_OF,
                "rate_types": ["EFFR", "SOFR"],
                "request_urls": sorted(
                    source["request_url"]
                    for source in result.group["market_conditions"]["rates"]
                ),
                "route_id": "market.us_conditions",
                "start_date": "2026-07-04",
            }
        )
    )
    assert ledger.row_counts()["source_capture_receipts"] == 5
    assert ledger.row_counts()["route_coverage_receipts"] == 1


def test_warm_retry_and_concurrent_same_key_use_zero_additional_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    callbacks = _source_callbacks()
    store, ledger, first, counts = _archive(
        tmp_path, monkeypatch, callbacks=callbacks
    )
    initial_counts = dict(counts)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: archive_us_macro_sources(
                    as_of_date=AS_OF,
                    cutoff_at=CUTOFF,
                    observation_start=OBSERVATION_START,
                    store=store,
                    ledger=ledger,
                    select_vintage=callbacks[1],
                    fetch_vintage=callbacks[2],
                    fetch_fomc=callbacks[3],
                    fetch_nyfed=callbacks[4],
                    fetch_tushare=callbacks[5],
                ),
                range(4),
            )
        )

    assert counts == initial_counts
    assert all(result.cache_hit for result in results)
    assert {
        tuple(receipt.receipt_hash for receipt in result.source_receipts)
        for result in [first, *results]
    } == {tuple(receipt.receipt_hash for receipt in first.source_receipts)}
    assert store.row_count() == 1
    assert ledger.row_counts()["source_capture_receipts"] == 5


def test_historical_cache_miss_replays_alfred_but_never_calls_live_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    callbacks = _source_callbacks()
    store, ledger, result, counts = _archive(
        tmp_path,
        monkeypatch,
        captured_at=datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc),
        callbacks=callbacks,
    )

    assert counts["select"] == len(ALFRED_SERIES_ROLE_MAP)
    assert counts["alfred"] == len(ALFRED_SERIES_ROLE_MAP)
    assert counts["fomc"] == counts["nyfed"] == 0
    assert counts["us_tycr"] == counts["fx_daily"] == 0
    assert [
        receipt.as_dict()["identity"]["route_id"]
        for receipt in result.source_receipts
    ] == ["alfred.us_macro"]
    alfred = result.source_receipts[0].as_dict()
    assert alfred["time"]["captured_at"] > alfred["pit"]["as_of_cutoff"]
    coverage = result.coverage_receipt.as_dict()
    assert coverage["coverage_complete"] is False
    assert coverage["blocker_codes"] == ["CAPTURE_AFTER_AS_OF_CUTOFF"]
    assert {
        row["route_id"]: row["status"] for row in coverage["route_results"]
    } == {
        "alfred.us_macro": "SUCCESS",
        "market.us_conditions": "CAPTURE_REJECTED",
        "official.us_policy": "CAPTURE_REJECTED",
        "tushare.fx_daily": "CAPTURE_REJECTED",
        "tushare.us_tycr": "CAPTURE_REJECTED",
    }
    assert store.row_count() == 1
    assert ledger.row_counts()["source_capture_receipts"] == 1


def test_future_as_of_rejects_before_any_source_call_or_archive_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import us_macro_archive

    future_as_of = "2026-08-09"
    future_cutoff = "2026-08-09T15:00:00+08:00"
    callbacks = _source_callbacks(
        as_of=future_as_of,
        cutoff=future_cutoff,
        vintage="2026-08-08",
    )
    counts, select_vintage, fetch_vintage, fetch_fomc, fetch_nyfed, fetch_tushare = (
        callbacks
    )
    monkeypatch.setattr(us_macro_archive, "_capture_now", lambda: CAPTURED_AT)
    store = USMacroArchiveStore(tmp_path / "us-macro.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")

    result = archive_us_macro_sources(
        as_of_date=future_as_of,
        cutoff_at=future_cutoff,
        observation_start=OBSERVATION_START,
        store=store,
        ledger=ledger,
        select_vintage=select_vintage,
        fetch_vintage=fetch_vintage,
        fetch_fomc=fetch_fomc,
        fetch_nyfed=fetch_nyfed,
        fetch_tushare=fetch_tushare,
    )

    assert counts["select"] == counts["alfred"] == 0
    assert counts["fomc"] == counts["nyfed"] == 0
    assert counts["us_tycr"] == counts["fx_daily"] == 0
    assert result.group is None
    assert result.source_receipts == ()
    coverage = result.coverage_receipt.as_dict()
    assert coverage["coverage_complete"] is False
    assert coverage["blocker_codes"] == ["CAPTURE_BEFORE_AS_OF_WINDOW"]
    assert {
        row["route_id"]: row["status"] for row in coverage["route_results"]
    } == {
        "alfred.us_macro": "CAPTURE_REJECTED",
        "market.us_conditions": "CAPTURE_REJECTED",
        "official.us_policy": "CAPTURE_REJECTED",
        "tushare.fx_daily": "CAPTURE_REJECTED",
        "tushare.us_tycr": "CAPTURE_REJECTED",
    }
    assert store.row_count() == 0
    assert ledger.row_counts()["source_capture_receipts"] == 0


def test_malformed_required_alfred_series_rolls_back_without_partial_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed_series = sorted(ALFRED_SERIES_ROLE_MAP)[0]
    store, ledger, result, _ = _archive(
        tmp_path,
        monkeypatch,
        callbacks=_source_callbacks(fail_series=failed_series),
    )

    assert result.group is None
    assert result.source_receipts == ()
    assert result.coverage_receipt.as_dict()["blocker_codes"] == ["SCHEMA_DRIFT"]
    assert store.row_count() == 0
    counts = ledger.row_counts()
    assert counts["source_capture_receipts"] == 0
    assert counts["route_coverage_receipts"] == 1


def test_wrapped_provider_timeout_is_classified_as_transport_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    callbacks = list(_source_callbacks())

    def timed_out_fetch(*args, **kwargs):
        del args, kwargs
        try:
            raise requests.ReadTimeout("private timeout detail")
        except requests.ReadTimeout as exc:
            raise DataVendorUnavailable("redacted provider failure") from exc

    callbacks[2] = timed_out_fetch
    store, ledger, result, _ = _archive(
        tmp_path,
        monkeypatch,
        callbacks=tuple(callbacks),
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


def test_capture_vintages_append_by_exact_materialization_key_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaic.dataflows import us_macro_archive

    store, ledger, first, _ = _archive(tmp_path, monkeypatch)
    monkeypatch.setattr(
        us_macro_archive,
        "_capture_now",
        lambda: datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc),
    )
    second_callbacks = _source_callbacks(
        as_of="2026-08-09",
        cutoff="2026-08-09T15:00:00+08:00",
        vintage="2026-08-08",
        retrieved_at="2026-08-09T05:55:00+00:00",
    )
    second = archive_us_macro_sources(
        as_of_date="2026-08-09",
        cutoff_at="2026-08-09T15:00:00+08:00",
        observation_start=OBSERVATION_START,
        store=store,
        ledger=ledger,
        select_vintage=second_callbacks[1],
        fetch_vintage=second_callbacks[2],
        fetch_fomc=second_callbacks[3],
        fetch_nyfed=second_callbacks[4],
        fetch_tushare=second_callbacks[5],
    )

    assert store.row_count() == 2
    assert first.group["capture_key"] != second.group["capture_key"]
    assert first.group["alfred"]["vintage_dates"] == ["2026-08-07"]
    assert second.group["alfred"]["vintage_dates"] == ["2026-08-08"]
    assert store.load_group(first.group["capture_key"]) == first.group


def test_archive_recomputes_hash_when_loading_private_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, result, _ = _archive(tmp_path, monkeypatch)
    with sqlite3.connect(store.path) as conn:
        conn.execute("DROP TRIGGER us_macro_capture_groups_no_update")
        conn.execute(
            "UPDATE us_macro_capture_groups SET payload_zlib = ? WHERE capture_key = ?",
            (zlib.compress(b"{}"), result.group["capture_key"]),
        )
    with pytest.raises(ValueError, match="hash mismatch"):
        store.load_group(result.group["capture_key"])


def test_receipt_bound_compiler_builds_both_snapshots_without_fomc_invention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, _ = _archive(tmp_path, monkeypatch)
    for route_id in ("tushare.eco_cal.cny", "tushare.eco_cal.usd"):
        ledger.append_source_capture(_calendar_receipt(route_id))

    built = compile_us_macro_snapshots(
        capture_key=result.group["capture_key"],
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )
    from mosaic.dataflows import us_macro_archive

    monkeypatch.setattr(
        us_macro_archive,
        "_capture_now",
        lambda: CAPTURED_AT + timedelta(seconds=1),
    )
    replay = compile_us_macro_snapshots(
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

    assert set(built.snapshots) == {"us_economy", "us_financial_conditions"}
    economy = built.snapshots["us_economy"]
    financial = built.snapshots["us_financial_conditions"]
    assert {row["series_id"] for row in economy["observations"]} == {
        series_id
        for series_id, role in ALFRED_SERIES_ROLE_MAP.items()
        if role == "us_economy"
    }
    assert {
        "fed_effr",
        "fed_sofr",
        "DGS2",
        "DGS3MO",
        "DGS10",
        "DGS30",
        "DFII5",
        "DFII10",
        "DFII30",
        "BAA10Y",
        "NFCI",
        "VIXCLS",
        "DTWEXBGS",
        "USDCNH",
    } == {row["series_id"] for row in financial["observations"]}
    source_by_series = {
        row["series_id"]: row["source"] for row in financial["observations"]
    }
    assert {
        source_by_series[series_id]
        for series_id in ("DGS2", "DGS3MO", "DGS10", "DGS30")
    } == {"tushare.us_tycr_nominal_curve"}
    assert source_by_series["USDCNH"] == "tushare.fx_daily.USD_CNY"
    assert not {
        "DGS2",
        "DGS3MO",
        "DGS10",
        "DGS30",
        "DEXCHUS",
    } & set(result.group["alfred"]["series_ids"])
    assert "official.fomc_statement" not in {
        row["source"] for row in financial["observations"]
    }
    assert {
        evidence_id
        for summary in financial["context_only_projection"]["component_summaries"].values()
        for evidence_id in summary["evidence_ids"]
    } == {row["evidence_id"] for row in economy["observations"]}
    assert len(built.build_receipts) == 2
    assert [receipt.receipt_hash for receipt in replay.build_receipts] == [
        receipt.receipt_hash for receipt in built.build_receipts
    ]
    assert ledger.row_counts()["snapshot_build_receipts"] == 2
    assert all(
        (tmp_path / "snapshots" / AS_OF / f"{role}.json").is_file()
        for role in built.snapshots
    )


def test_compiler_uses_each_alfred_rows_availability_vintage_not_series_query_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, _ = _archive(
        tmp_path,
        monkeypatch,
        callbacks=_source_callbacks(row_realtime_start="2026-08-06"),
    )
    for route_id in ("tushare.eco_cal.cny", "tushare.eco_cal.usd"):
        ledger.append_source_capture(_calendar_receipt(route_id))

    built = compile_us_macro_snapshots(
        capture_key=result.group["capture_key"],
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )

    alfred_rows = [
        row
        for snapshot in built.snapshots.values()
        for row in snapshot["observations"]
        if row["source"] == "ALFRED"
    ]
    assert alfred_rows
    assert {row["released_at"] for row in alfred_rows} == {
        "2026-08-06T23:59:59+00:00"
    }
    assert {row["vintage_at"] for row in alfred_rows} == {
        "2026-08-06T23:59:59+00:00"
    }


def test_tushare_curve_uses_latest_usable_row_per_tenor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ledger, result, _ = _archive(
        tmp_path,
        monkeypatch,
        callbacks=_source_callbacks(latest_treasury_partial=True),
    )
    for route_id in ("tushare.eco_cal.cny", "tushare.eco_cal.usd"):
        ledger.append_source_capture(_calendar_receipt(route_id))

    built = compile_us_macro_snapshots(
        capture_key=result.group["capture_key"],
        store=store,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )

    curve = {
        row["series_id"]: row
        for row in built.snapshots["us_financial_conditions"]["observations"]
        if row["series_id"] in {"DGS2", "DGS3MO", "DGS10", "DGS30"}
    }
    assert curve["DGS10"]["period_end"] == "2026-08-07"
    assert curve["DGS30"]["period_end"] == "2026-08-06"


def test_receipt_bound_alfred_projection_reuses_existing_macro_series_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, result, _ = _archive(tmp_path, monkeypatch)
    alfred_receipt = next(
        receipt
        for receipt in result.source_receipts
        if receipt.as_dict()["identity"]["route_id"] == "alfred.us_macro"
    )
    db_path = tmp_path / "scorecard.sqlite3"

    projection = project_alfred_capture_to_macro_series(
        group=result.group,
        source_receipt=alfred_receipt,
        db_path=db_path,
    )

    assert projection["projected_series_ids"] == ["VIX"]
    tushare_projection = project_tushare_capture_to_macro_series(
        group=result.group,
        source_receipts=result.source_receipts,
        db_path=db_path,
    )
    assert tushare_projection["projected_series_ids"] == [
        "US10Y",
        "US2Y",
        "US3M",
        "USDCNY",
    ]
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT series_id, source, endpoint_name, instrument, as_of_date, metadata_json "
            "FROM macro_series ORDER BY series_id"
        ).fetchall()
    assert [(row[0], row[1], row[2], row[3], row[4]) for row in rows] == [
        ("US10Y", "tushare", "us_tycr", "DGS10", AS_OF),
        ("US2Y", "tushare", "us_tycr", "DGS2", AS_OF),
        ("US3M", "tushare", "us_tycr", "DGS3MO", AS_OF),
        ("USDCNY", "tushare", "fx_daily", "USDCNH.FXCM", AS_OF),
        ("VIX", "alfred", "fred_series_observations", "VIXCLS", AS_OF),
    ]
    assert alfred_receipt.receipt_hash in next(row[5] for row in rows if row[0] == "VIX")

    tampered = {**result.group, "alfred": {**result.group["alfred"], "series": []}}
    with pytest.raises(ValueError, match="receipt|raw content"):
        project_alfred_capture_to_macro_series(
            group=tampered,
            source_receipt=alfred_receipt,
            db_path=db_path,
        )

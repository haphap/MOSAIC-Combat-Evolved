from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.dataflows.staged_query_receipts import seal_staged_query_source_receipt
from mosaic.scorecard.canonical_json import canonical_hash


def _descriptor(*, pit_mode: str = "OBSERVED_LIVE", content: str = "v1") -> dict:
    return {
        "tool_id": "get_indicators",
        "route_id": "tushare.sector_market",
        "as_of": "2026-07-17",
        "request_hash": canonical_hash({"ticker": "600000.SH"}),
        "content_hash": canonical_hash({"content": content}),
        "pit_mode": pit_mode,
    }


def test_live_receipt_is_captured_once_and_reused_after_historical_cutoff(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)]
    store = StagedQueryReceiptStore(
        tmp_path / ".mosaic/private/query-receipts.sqlite3",
        clock=lambda: now[0],
    )
    first = store.resolve(_descriptor())
    assert len(first) == 1
    assert first[0]["upstream_evidence_hashes"] == []
    assert first[0]["captured_at"] == "2026-07-17T08:00:00+00:00"
    assert first[0]["captured_at"] == first[0]["knowledge_available_at"]

    now[0] = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    assert store.resolve(_descriptor()) == first
    with pytest.raises(DataVendorUnavailable, match="historical OBSERVED_LIVE"):
        store.resolve(_descriptor(content="changed-after-cutoff"))


def test_non_live_receipt_requires_authoritative_registration(tmp_path: Path) -> None:
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    store = StagedQueryReceiptStore(
        tmp_path / ".mosaic/private/query-receipts.sqlite3",
        clock=lambda: now,
    )
    descriptor = _descriptor(
        pit_mode="AUTHORITATIVE_VINTAGE_REPLAY", content="vintage"
    )
    with pytest.raises(DataVendorUnavailable, match="authoritative source receipt"):
        store.resolve(descriptor)

    receipt = seal_staged_query_source_receipt(
        descriptor,
        knowledge_available_at="2026-07-16T23:59:59.999999+08:00",
        captured_at=now.isoformat(),
        upstream_evidence_hashes=(canonical_hash({"vendor_vintage": "2026-07-16"}),),
    )
    assert receipt["upstream_evidence_hashes"] == [
        canonical_hash({"vendor_vintage": "2026-07-16"})
    ]
    assert store.register(receipt) == receipt["receipt_hash"]
    assert store.resolve(descriptor) == [receipt]


def test_receipts_are_append_only_and_concurrent_live_capture_is_singleton(
    tmp_path: Path,
) -> None:
    store = StagedQueryReceiptStore(
        tmp_path / ".mosaic/private/query-receipts.sqlite3",
        clock=lambda: datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc),
    )
    descriptor = _descriptor()
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda _index: store.resolve(descriptor), range(16)))
    assert all(receipt == receipts[0] for receipt in receipts)

    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM staged_query_receipts"
        ).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE staged_query_receipts SET created_at = created_at"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM staged_query_receipts")


def test_register_rejects_tampered_or_conflicting_receipt(tmp_path: Path) -> None:
    store = StagedQueryReceiptStore(
        tmp_path / ".mosaic/private/query-receipts.sqlite3"
    )
    descriptor = _descriptor(pit_mode="DERIVED_FROM_PIT_ARCHIVE")
    receipt = seal_staged_query_source_receipt(
        descriptor,
        knowledge_available_at="2026-07-16T12:00:00+08:00",
        captured_at="2026-07-17T08:00:00+08:00",
        upstream_evidence_hashes=(canonical_hash({"archive": "rke"}),),
    )
    tampered = dict(receipt)
    tampered["content_hash"] = canonical_hash({"content": "tampered"})
    with pytest.raises(ValueError, match="hash|descriptor"):
        store.register(tampered)

    store.register(receipt)
    conflicting = seal_staged_query_source_receipt(
        descriptor,
        knowledge_available_at="2026-07-16T13:00:00+08:00",
        captured_at="2026-07-17T08:00:00+08:00",
        upstream_evidence_hashes=(canonical_hash({"archive": "rke"}),),
    )
    with pytest.raises(ValueError, match="conflicting"):
        store.register(conflicting)

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.dataflows import geopolitical_archive
from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.geopolitical_archive import materialize_geopolitical_snapshot
from mosaic.dataflows.geopolitical_events import (
    GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    GeopoliticalEventStore,
)


def test_empty_archive_publishes_specific_blocked_receipts_without_snapshot(
    tmp_path: Path,
):
    event_store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    output_root = tmp_path / "snapshots"

    result = materialize_geopolitical_snapshot(
        as_of_date="2026-07-17",
        event_store=event_store,
        ledger=ledger,
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        output_root=output_root,
    )

    coverage = result.coverage_receipt.as_dict()
    build = result.build_receipt.as_dict()
    assert result.snapshot is None
    assert coverage["coverage_complete"] is False
    assert coverage["route_results"] == [
        {
            "route_id": "geopolitical.required_coverage",
            "capture_receipt_hash": None,
            "status": "CAPTURE_REJECTED",
        }
    ]
    assert coverage["blocker_codes"] == ["INCOMPLETE_COVERAGE"]
    assert build["terminal_state"] == "BLOCKED"
    assert build["output_hash"] is None
    assert build["missing_route_ids"] == [
        "geopolitical.required_coverage",
        "tushare.eco_cal.cny",
        "tushare.eco_cal.eur",
        "tushare.eco_cal.usd",
    ]
    assert build["blocker_codes"] == [
        "INCOMPLETE_COVERAGE",
        "REQUIRED_ROUTE_MISSING",
    ]
    assert not output_root.exists()
    assert ledger.row_counts() == {
        "source_capture_receipts": 0,
        "route_coverage_receipts": 1,
        "snapshot_build_receipts": 1,
        "materialization_attempt_receipts": 0,
    }


def test_blocked_materialization_is_deterministic_and_zero_transport(tmp_path: Path):
    event_store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")

    first = materialize_geopolitical_snapshot(
        as_of_date="2026-07-17",
        event_store=event_store,
        ledger=ledger,
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        output_root=tmp_path / "snapshots",
    )
    second = materialize_geopolitical_snapshot(
        as_of_date="2026-07-17",
        event_store=event_store,
        ledger=ledger,
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        output_root=tmp_path / "snapshots",
    )

    assert second.coverage_receipt.receipt_hash == first.coverage_receipt.receipt_hash
    assert second.build_receipt.receipt_hash == first.build_receipt.receipt_hash
    assert ledger.row_counts()["route_coverage_receipts"] == 1
    assert ledger.row_counts()["snapshot_build_receipts"] == 1


def test_ready_manifest_with_required_source_failure_publishes_blocked_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    event_store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    monkeypatch.setattr(
        geopolitical_archive,
        "promote_geopolitical_manifest",
        lambda *_args, **_kwargs: {"manifest_readiness": "READY"},
    )
    monkeypatch.setattr(
        geopolitical_archive,
        "build_geopolitical_role_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DataVendorUnavailable("required source latest poll failed")
        ),
    )

    result = materialize_geopolitical_snapshot(
        as_of_date="2026-07-17",
        event_store=event_store,
        ledger=ledger,
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        output_root=tmp_path / "snapshots",
    )

    assert result.snapshot is None
    assert result.source_receipt is None
    assert result.coverage_receipt.as_dict()["blocker_codes"] == [
        "INCOMPLETE_COVERAGE"
    ]
    assert result.build_receipt.as_dict()["terminal_state"] == "BLOCKED"

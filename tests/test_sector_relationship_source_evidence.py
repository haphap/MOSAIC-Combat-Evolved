from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.sector_relationship_queries import (
    SectorRelationshipQueryMaterializer,
)
from mosaic.dataflows.sector_relationship_source_evidence import (
    SectorRelationshipSourceEvidenceAuthority,
)
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.scorecard.canonical_json import canonical_hash


AS_OF = "2026-07-09"
CAPTURED_NOW = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)


def _descriptor(tool_id: str, raw_payload: str, *, pit_mode: str) -> dict:
    return {
        "tool_id": tool_id,
        "route_id": (
            "tushare.etf_holdings"
            if tool_id == "get_etf_holdings"
            else "private.rke_report_intelligence"
        ),
        "as_of": AS_OF,
        "request_hash": canonical_hash({"tool_id": tool_id}),
        "content_hash": canonical_hash({"text": raw_payload}),
        "pit_mode": pit_mode,
    }


def _authority(tmp_path: Path) -> tuple[
    SectorRelationshipSourceEvidenceAuthority,
    StagedQueryReceiptStore,
]:
    store = StagedQueryReceiptStore(
        tmp_path / ".mosaic/private/query-receipts.sqlite3",
        clock=lambda: CAPTURED_NOW,
    )
    return (
        SectorRelationshipSourceEvidenceAuthority(
            root=tmp_path,
            receipt_store=store,
            clock=lambda: CAPTURED_NOW,
        ),
        store,
    )


def test_etf_disclosure_date_seals_authoritative_vintage_and_registers_exact_replay(
    tmp_path: Path,
) -> None:
    authority, store = _authority(tmp_path)
    raw = (
        "# ETF holdings\nTicker: 512800.SH\nDisclosure Date: 20260701\n"
        "Report Date: 20260630\n\n"
        "ts_code,symbol,stk_name,stk_mkv_ratio,stk_float_ratio\n"
        "512800.SH,600000.SH,浦发银行,9.1,2.1\n"
    )
    descriptor = _descriptor(
        "get_etf_holdings", raw, pit_mode="AUTHORITATIVE_VINTAGE_REPLAY"
    )

    receipts = authority(
        "get_etf_holdings",
        {"etf": "512800.SH", "as_of": AS_OF, "top_n": 1},
        raw,
        descriptor,
        (),
    )

    assert len(receipts) == 1
    assert receipts[0]["knowledge_available_at"] == "2026-07-01T23:59:59.999999+08:00"
    assert receipts[0]["captured_at"] == CAPTURED_NOW.isoformat()
    assert receipts[0]["upstream_evidence_hashes"] == [
        canonical_hash(
            {
                "disclosure_date": "2026-07-01T23:59:59.999999+08:00",
                "raw_payload_hash": descriptor["content_hash"],
                "route_id": "tushare.etf_holdings",
            }
        )
    ]
    assert store.resolve(descriptor) == receipts


@pytest.mark.parametrize(
    "raw",
    [
        "Ticker: 512800.SH\nReport Date: 20260630",
        "Ticker: 512800.SH\nDisclosure Date: 20260710",
        "Ticker: 512800.SH\nDisclosure Date: not-a-date",
    ],
)
def test_etf_missing_invalid_or_future_disclosure_fails_closed(
    tmp_path: Path, raw: str
) -> None:
    authority, _store = _authority(tmp_path)
    descriptor = _descriptor(
        "get_etf_holdings", raw, pit_mode="AUTHORITATIVE_VINTAGE_REPLAY"
    )
    with pytest.raises(DataVendorUnavailable, match="ETF disclosure"):
        authority(
            "get_etf_holdings",
            {"etf": "512800.SH", "as_of": AS_OF, "top_n": 1},
            raw,
            descriptor,
            (),
        )


def test_rke_selected_sources_use_archive_publish_and_first_discovery_times(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "registry/sources"
    source_dir.mkdir(parents=True)
    (source_dir / "tushare_research_reports.jsonl").write_text(
        json.dumps(
            {
                "source_id": "SRC-TSRR-1",
                "publish_date": "2026-06-30",
                "discovered_at": "2026-07-01T03:00:00+00:00",
                "source_hash": canonical_hash({"source": 1}),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    registry_dir = tmp_path / "registry/report_intelligence"
    registry_dir.mkdir(parents=True)
    (registry_dir / "report_metadata.jsonl").write_text(
        json.dumps(
            {
                "source_id": "SRC-TSRR-1",
                "report_id": "RPT-1",
                "publish_datetime": "2026-06-30T15:00:00+08:00",
                "accessible_datetime": "2026-07-01T09:00:00+08:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    authority, store = _authority(tmp_path)
    raw = "public-safe-rke-context"
    descriptor = _descriptor(
        "get_rke_research_context", raw, pit_mode="DERIVED_FROM_PIT_ARCHIVE"
    )

    receipts = authority(
        "get_rke_research_context",
        {
            "agent_id": "financials",
            "as_of": AS_OF,
            "layer": "sector",
            "ticker": "",
            "sector": "银行",
            "max_items": 12,
        },
        raw,
        descriptor,
        ("SRC-TSRR-1",),
    )

    assert receipts[0]["knowledge_available_at"] == "2026-07-01T09:00:00+08:00"
    assert receipts[0]["captured_at"] == "2026-07-01T03:00:00+00:00"
    assert receipts[0]["upstream_evidence_hashes"] == [
        canonical_hash(
            {
                "metadata": {
                    "accessible_datetime": "2026-07-01T09:00:00+08:00",
                    "publish_datetime": "2026-06-30T15:00:00+08:00",
                    "report_id": "RPT-1",
                    "source_id": "SRC-TSRR-1",
                },
                "source": {
                    "discovered_at": "2026-07-01T03:00:00+00:00",
                    "publish_date": "2026-06-30",
                    "source_hash": canonical_hash({"source": 1}),
                    "source_id": "SRC-TSRR-1",
                },
            }
        )
    ]
    assert store.resolve(descriptor) == receipts


@pytest.mark.parametrize("source_ids", [(), ("SRC-MISSING",)])
def test_rke_empty_or_unclosed_source_lineage_fails_closed(
    tmp_path: Path, source_ids: tuple[str, ...]
) -> None:
    authority, _store = _authority(tmp_path)
    raw = "public-safe-rke-context"
    descriptor = _descriptor(
        "get_rke_research_context", raw, pit_mode="DERIVED_FROM_PIT_ARCHIVE"
    )
    with pytest.raises(DataVendorUnavailable, match="RKE source"):
        authority(
            "get_rke_research_context",
            {
                "agent_id": "financials",
                "as_of": AS_OF,
                "layer": "sector",
                "ticker": "",
                "sector": "银行",
                "max_items": 12,
            },
            raw,
            descriptor,
            source_ids,
        )


def test_materializer_uses_specialized_non_live_evidence_before_generic_authority(
    tmp_path: Path,
) -> None:
    authority, _store = _authority(tmp_path)
    raw = (
        "Ticker: 512800.SH\nDisclosure Date: 20260701\nReport Date: 20260630\n"
        "ts_code,symbol,stk_name,stk_mkv_ratio,stk_float_ratio\n"
        "512800.SH,600000.SH,浦发银行,9.1,2.1\n"
    )
    materializer = SectorRelationshipQueryMaterializer(
        receipt_authority=lambda descriptor: pytest.fail(
            f"generic authority must not attest non-live descriptor: {descriptor}"
        ),
        route_caller=lambda method, *args: raw,
        source_evidence_authority=authority,
    )

    result = materializer(
        "get_etf_holdings",
        {"etf": "512800.SH", "as_of": AS_OF, "top_n": 1},
    )

    assert len(result["source_receipt_hashes"]) == 1
    assert json.loads(result["payload"])["candidates"][0]["ticker"] == "600000.SH"

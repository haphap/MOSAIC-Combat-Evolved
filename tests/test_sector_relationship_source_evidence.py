from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mosaic.agents.utils.rke_research_tools import format_rke_runtime_context
import mosaic.dataflows.sector_relationship_source_evidence as source_evidence_module
from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.sector_relationship_queries import (
    SectorRelationshipQueryMaterializer,
)
from mosaic.dataflows.sector_relationship_source_evidence import (
    SectorRelationshipSourceEvidenceAuthority,
)
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.rke.agent_research_context import (
    RKE_AGENT_RESEARCH_INPUT_FILENAMES,
    build_rke_agent_research_materialization,
)
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
    AgentDataMaterializationLedger,
]:
    store = StagedQueryReceiptStore(
        tmp_path / ".mosaic/private/query-receipts.sqlite3",
        clock=lambda: CAPTURED_NOW,
    )
    ledger = AgentDataMaterializationLedger(
        tmp_path / ".mosaic/private/agent-data.sqlite3"
    )
    return (
        SectorRelationshipSourceEvidenceAuthority(
            root=tmp_path,
            receipt_store=store,
            agent_data_ledger=ledger,
            clock=lambda: CAPTURED_NOW,
        ),
        store,
        ledger,
    )


def _write_true_empty_rke_inputs(tmp_path: Path) -> Path:
    registry_dir = tmp_path / "registry/report_intelligence"
    registry_dir.mkdir(parents=True, exist_ok=True)
    for filename in RKE_AGENT_RESEARCH_INPUT_FILENAMES:
        (registry_dir / filename).write_text("", encoding="utf-8")
    return registry_dir


def test_etf_disclosure_date_seals_authoritative_vintage_and_registers_exact_replay(
    tmp_path: Path,
) -> None:
    authority, store, ledger = _authority(tmp_path)
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
    assert len(receipts[0]["upstream_evidence_hashes"]) == 1
    upstream = ledger.source_capture_receipt(
        receipt_hash=receipts[0]["upstream_evidence_hashes"][0]
    )
    assert upstream is not None
    upstream_payload = upstream.as_dict()
    assert upstream_payload["schema_version"] == "source_capture_receipt_v1"
    assert "schema_hash" in upstream_payload["content"]
    assert upstream_payload["identity"]["route_id"] == "tushare.etf_holdings"
    assert upstream_payload["pit"]["pit_mode"] == "AUTHORITATIVE_VINTAGE_REPLAY"
    assert upstream_payload["content"]["raw_content_hash"] == descriptor["content_hash"]
    assert store.resolve(descriptor) == receipts


def test_sector_source_receipt_loads_the_exact_ticker_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_at = "2026-07-09T15:00:00+08:00"
    archive_store = Mock()
    archive_store.load_group.return_value = {
        "as_of_date": AS_OF,
        "captured_at": observed_at,
        "batches": [{"endpoint": "daily", "rows": []}],
    }
    parent_hash = canonical_hash({"parent": "sector-archive"})
    monkeypatch.setattr(
        source_evidence_module,
        "sector_archive_source_receipt",
        lambda _group, _route_id: SimpleNamespace(
            receipt_hash=parent_hash,
            as_dict=lambda: {
                "time": {
                    "captured_at": observed_at,
                    "knowledge_available_at": observed_at,
                }
            },
        ),
    )
    receipt_store = StagedQueryReceiptStore(tmp_path / "staged.sqlite3")
    authority = SectorRelationshipSourceEvidenceAuthority(
        root=tmp_path,
        receipt_store=receipt_store,
        sector_archive_store=archive_store,
    )
    raw = "exact ticker payload"
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-07-01",
        "date_to": AS_OF,
    }
    descriptor = {
        "tool_id": "get_stock_data",
        "route_id": "tushare.sector_market",
        "as_of": AS_OF,
        "request_hash": canonical_hash(args),
        "content_hash": canonical_hash({"text": raw}),
        "pit_mode": "OBSERVED_LIVE",
    }

    authority("get_stock_data", args, raw, descriptor, ())

    archive_store.load_group.assert_called_once_with(
        AS_OF,
        required_security_code="600000.SH",
    )


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
    authority, _store, _ledger = _authority(tmp_path)
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
    authority, store, ledger = _authority(tmp_path)
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
    assert len(receipts[0]["upstream_evidence_hashes"]) == 1
    upstream = ledger.source_capture_receipt(
        receipt_hash=receipts[0]["upstream_evidence_hashes"][0]
    )
    assert upstream is not None
    upstream_payload = upstream.as_dict()
    assert upstream_payload["schema_version"] == "source_capture_receipt_v2"
    assert "schema_hash" not in upstream_payload["content"]
    assert upstream_payload["identity"]["route_id"] == "private.rke_report_intelligence"
    assert upstream_payload["pit"]["pit_mode"] == "AUTHORITATIVE_VINTAGE_REPLAY"
    assert upstream_payload["content"]["raw_content_hash"] == descriptor["content_hash"]
    assert store.resolve(descriptor) == receipts


@pytest.mark.parametrize("source_ids", [(), ("SRC-MISSING",)])
def test_rke_empty_or_unclosed_source_lineage_fails_closed(
    tmp_path: Path, source_ids: tuple[str, ...]
) -> None:
    authority, _store, _ledger = _authority(tmp_path)
    raw = "public-safe-rke-context"
    descriptor = _descriptor(
        "get_rke_research_context", raw, pit_mode="DERIVED_FROM_PIT_ARCHIVE"
    )
    with pytest.raises(DataVendorUnavailable):
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


@pytest.mark.parametrize("optional_contents", [None, "invalid json", "{}\n"])
def test_rke_true_empty_receipt_requires_exact_materialization_and_basic_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, optional_contents: str | None,
) -> None:
    registry_dir = _write_true_empty_rke_inputs(tmp_path)
    args = {
        "agent_id": "financials",
        "as_of": AS_OF,
        "layer": "sector",
        "ticker": "",
        "sector": "银行",
        "max_items": 12,
    }
    materialization = build_rke_agent_research_materialization(
        root=tmp_path,
        registry_dir=registry_dir,
        agent_id=args["agent_id"],
        as_of_date=args["as_of"],
        layer=args["layer"],
        ticker=args["ticker"],
        sector=args["sector"],
        max_items=args["max_items"],
    )
    raw = format_rke_runtime_context(materialization["context"])
    descriptor = _descriptor(
        "get_rke_research_context", raw, pit_mode="DERIVED_FROM_PIT_ARCHIVE"
    )
    descriptor["request_hash"] = canonical_hash(args)
    authority, store, ledger = _authority(tmp_path)

    if optional_contents is not None:
        for filename in (
            "report_outcome_labels.jsonl", "source_performance_profiles.jsonl",
            "viewpoint_performance_profiles.jsonl", "analysis_recipes.jsonl",
            "tool_gaps.jsonl", "weighted_research_contexts.jsonl",
            "stock_context_snapshots.jsonl", "industry_context_snapshots.jsonl",
        ):
            (registry_dir / filename).write_text(optional_contents, encoding="utf-8")
    hashed_files: list[str] = []
    read_bytes = Path.read_bytes

    def record_read(path: Path) -> bytes:
        if path.parent == registry_dir:
            hashed_files.append(path.name)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", record_read)

    receipts = authority("get_rke_research_context", args, raw, descriptor, ())
    assert hashed_files == ["forecast_claims.jsonl", "report_metadata.jsonl"]

    assert len(receipts) == 1
    upstream = ledger.source_capture_receipt(
        receipt_hash=receipts[0]["upstream_evidence_hashes"][0]
    )
    assert upstream is not None
    payload = upstream.as_dict()
    assert payload["authority"]["parser_version"] == "rke_source_evidence_v3"
    assert payload["schema_version"] == "source_capture_receipt_v2"
    assert "schema_hash" not in payload["content"]
    assert payload["content"]["normalized_row_count"] == 0
    assert payload["completeness"]["empty_result_semantics"] == "TRUE_EMPTY"
    assert payload["coverage"]["observed_start"] is None
    assert payload["coverage"]["observed_end"] is None
    assert payload["identity"]["request_hash"] == descriptor["request_hash"]
    assert payload["content"]["raw_content_hash"] == descriptor["content_hash"]
    assert payload["pit"]["vintage_query"]["archive_hash"].startswith("sha256:")
    assert store.resolve(descriptor) == receipts


@pytest.mark.parametrize("missing_filename", ["forecast_claims.jsonl", "report_metadata.jsonl"])
def test_rke_true_empty_receipt_rejects_missing_input_or_forged_payload(
    tmp_path: Path, missing_filename: str,
) -> None:
    registry_dir = _write_true_empty_rke_inputs(tmp_path)
    args = {
        "agent_id": "financials",
        "as_of": AS_OF,
        "layer": "sector",
        "ticker": "",
        "sector": "银行",
        "max_items": 12,
    }
    registry_dir.joinpath(missing_filename).unlink()
    authority, _store, _ledger = _authority(tmp_path)
    descriptor = _descriptor(
        "get_rke_research_context", "forged payload", pit_mode="DERIVED_FROM_PIT_ARCHIVE"
    )
    with pytest.raises(DataVendorUnavailable, match="RKE empty coverage"):
        authority("get_rke_research_context", args, "forged payload", descriptor, ())

    _write_true_empty_rke_inputs(tmp_path)
    with pytest.raises(DataVendorUnavailable, match="RKE empty coverage"):
        authority("get_rke_research_context", args, "forged payload", descriptor, ())


def test_materializer_uses_specialized_non_live_evidence_before_generic_authority(
    tmp_path: Path,
) -> None:
    authority, _store, _ledger = _authority(tmp_path)
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

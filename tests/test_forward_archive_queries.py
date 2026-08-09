from __future__ import annotations

import json
from pathlib import Path

import pytest

import mosaic.dataflows.forward_archive_queries as forward_module
from mosaic.dataflows.adaptive_query_archives import TrustedArchiveQueryRouter
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.forward_archive_queries import ForwardArchiveQueryReader
from mosaic.dataflows.sector_relationship_queries import (
    SectorRelationshipQueryMaterializer,
)
from mosaic.dataflows.sector_relationship_source_evidence import (
    SectorRelationshipSourceEvidenceAuthority,
)
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.scorecard.canonical_json import canonical_hash


class _SectorStore:
    def __init__(self, group: dict) -> None:
        self.group = group

    def load_group(self, as_of: str) -> dict:
        if self.group.get("as_of_date") != as_of:
            raise FileNotFoundError(as_of)
        return self.group


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _research_row(
    *,
    source_id: str,
    report_type: str,
    publish_date: str,
    discovered_at: str,
    title: str,
    ts_code: str = "",
    industry: str = "",
) -> dict:
    row = {
        "source_id": source_id,
        "source_span_id": f"{source_id}:abstract",
        "source_type": "tushare_research_report",
        "report_type": report_type,
        "query_key": ts_code or industry,
        "publish_date": publish_date,
        "discovered_at": discovered_at,
        "title": title,
        "abstract": f"{title} full abstract",
        "author": "Analyst",
        "institution": "Broker",
        "ts_code": ts_code,
        "industry": industry,
        "url": f"https://reports.example/{source_id}",
        "source_hash": canonical_hash({"source_id": source_id, "title": title}),
        "point_in_time_available": True,
        "license_status": "pending_review",
    }
    return row


def _policy_row(
    *, article_id: str, title: str, pub_date: str, discovered_at: str
) -> dict:
    return {
        "article_id": article_id,
        "source": "gov.cn policy document library",
        "category_id": "gongwen",
        "category": "国务院文件",
        "pub_date": pub_date,
        "puborg": "国务院",
        "pcode": "国发〔2026〕1号",
        "index": "",
        "childtype": "国土资源、能源",
        "title": title,
        "summary": f"{title} summary",
        "url": f"https://www.gov.cn/{article_id}",
        "raw_id": article_id,
        "raw_pubtime": None,
        "raw_ptime": None,
        "raw_sha256": canonical_hash({"article_id": article_id})[7:],
        "parsed_at": discovered_at,
        "discovered_at": discovered_at,
    }


def _reader(tmp_path: Path, research_rows: list[dict], policy_rows: list[dict]):
    root = tmp_path / "repo"
    source = root / "registry/sources/tushare_research_reports.jsonl"
    policy = tmp_path / "gov-policy"
    _write_jsonl(source, research_rows)
    _write_jsonl(policy / "parsed/policy_documents.jsonl", policy_rows)
    sector_store = _SectorStore(
        {
            "as_of_date": "2026-06-05",
            "captured_at": "2026-06-05T07:00:00+00:00",
            "batches": [
                {
                    "endpoint": "stock_basic",
                    "rows": [
                        {
                            "ts_code": "600000.SH",
                            "industry": "Semiconductors",
                        }
                    ],
                }
            ],
        }
    )
    return ForwardArchiveQueryReader(
        root=root,
        sector_archive_store=sector_store,
        policy_cache_dir=policy,
    )


def _descriptor(tool_id: str, route_id: str, args: dict, payload: str) -> dict:
    return {
        "tool_id": tool_id,
        "route_id": route_id,
        "as_of": args.get("as_of", args.get("date_to")),
        "request_hash": canonical_hash(args),
        "content_hash": canonical_hash({"text": payload}),
        "pit_mode": "DERIVED_FROM_PIT_ARCHIVE",
    }


def test_stock_research_reads_only_rows_discovered_by_as_of(tmp_path):
    eligible = _research_row(
        source_id="SRC-STOCK-1",
        report_type="个股研报",
        publish_date="2026-06-03",
        discovered_at="2026-06-03T06:00:00+00:00",
        title="Eligible stock report",
        ts_code="600000.SH",
        industry="Semiconductors",
    )
    late = _research_row(
        source_id="SRC-STOCK-2",
        report_type="个股研报",
        publish_date="2026-06-04",
        discovered_at="2026-06-06T06:00:00+00:00",
        title="Late-discovered stock report",
        ts_code="600000.SH",
        industry="Semiconductors",
    )
    reader = _reader(tmp_path, [eligible, late], [])

    payload = reader(
        "get_stock_research", "600000.SH", "2026-06-01", "2026-06-05", 30
    )

    assert "Individual Stock Research Reports for 600000.SH" in payload
    assert "Eligible stock report full abstract" in payload
    assert "Late-discovered stock report" not in payload
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-06-01",
        "date_to": "2026-06-05",
        "max_reports": 30,
    }
    receipt = reader.source_receipt(
        "get_stock_research",
        args,
        payload,
        _descriptor(
            "get_stock_research",
            "private.tushare_research_reports",
            args,
            payload,
        ),
    ).as_dict()
    assert receipt["identity"]["route_id"] == "private.tushare_research_reports"
    assert receipt["pit"]["pit_mode"] == "OBSERVED_LIVE"
    assert receipt["content"]["normalized_row_count"] == 1


def test_broker_research_reuses_archived_industry_resolution(tmp_path):
    rows = [
        _research_row(
            source_id="SRC-STOCK-IND",
            report_type="个股研报",
            publish_date="2026-05-20",
            discovered_at="2026-05-20T06:00:00+00:00",
            title="Industry resolver",
            ts_code="600000.SH",
            industry="Semiconductors",
        ),
        _research_row(
            source_id="SRC-IND-1",
            report_type="行业研报",
            publish_date="2026-06-02",
            discovered_at="2026-06-02T06:00:00+00:00",
            title="Industry deep dive",
            industry="Semiconductors",
        ),
    ]
    reader = _reader(tmp_path, rows, [])

    payload = reader(
        "get_broker_research", "600000.SH", "2026-06-01", "2026-06-05", 30
    )

    assert "Industry Research Reports for Semiconductors" in payload
    assert "Industry keyword source: stock-report ind_name" in payload
    assert "Industry deep dive full abstract" in payload


def test_broker_research_falls_back_to_archived_stock_basic_with_parent_lineage(
    tmp_path, monkeypatch
):
    reader = _reader(
        tmp_path,
        [
            _research_row(
                source_id="SRC-IND-FALLBACK",
                report_type="行业研报",
                publish_date="2026-06-02",
                discovered_at="2026-06-02T06:00:00+00:00",
                title="Fallback industry report",
                industry="Semiconductors",
            )
        ],
        [],
    )
    parent_hash = canonical_hash({"sector": "parent"})

    class _ParentReceipt:
        def as_dict(self):
            return {
                "receipt_hash": parent_hash,
                "time": {"captured_at": "2026-06-05T07:00:00+00:00"},
            }

    monkeypatch.setattr(
        forward_module,
        "sector_archive_source_receipt",
        lambda group, route_id: _ParentReceipt(),
    )

    payload = reader(
        "get_broker_research", "600000.SH", "2026-06-01", "2026-06-05", 30
    )
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-06-01",
        "date_to": "2026-06-05",
        "max_reports": 30,
    }
    receipt = reader.source_receipt(
        "get_broker_research",
        args,
        payload,
        _descriptor(
            "get_broker_research",
            "private.tushare_research_reports",
            args,
            payload,
        ),
    ).as_dict()

    assert "Industry keyword source: stock_basic industry" in payload
    assert receipt["provenance"]["parent_capture_hash"] == parent_hash


def test_policy_reader_preserves_window_and_discovery_cutoff(tmp_path):
    reader = _reader(
        tmp_path,
        [],
        [
            _policy_row(
                article_id="energy",
                title="能源政策",
                pub_date="2026-06-03",
                discovered_at="2026-06-03T06:00:00+00:00",
            ),
            _policy_row(
                article_id="late",
                title="能源政策 late",
                pub_date="2026-06-04",
                discovered_at="2026-06-06T06:00:00+00:00",
            ),
            _policy_row(
                article_id="agri",
                title="农业政策",
                pub_date="2026-06-03",
                discovered_at="2026-06-03T06:00:00+00:00",
            ),
        ],
    )

    payload = reader("get_industry_policy", "2026-06-05", 7, "govcn")

    assert "能源政策" in payload
    assert "能源政策 late" not in payload
    assert "农业政策" in payload
    assert "forward archive" in payload


def test_forward_archive_queries_fail_closed_without_eligible_rows(tmp_path):
    reader = _reader(
        tmp_path,
        [
            _research_row(
                source_id="SRC-LATE",
                report_type="个股研报",
                publish_date="2026-06-03",
                discovered_at="2026-06-06T06:00:00+00:00",
                title="Late",
                ts_code="600000.SH",
            )
        ],
        [],
    )

    with pytest.raises(DataVendorUnavailable, match="coverage"):
        reader(
            "get_stock_research", "600000.SH", "2026-06-01", "2026-06-05", 30
        )
    with pytest.raises(DataVendorUnavailable, match="coverage"):
        reader("get_industry_policy", "2026-06-05", 7, "govcn")


def test_forward_archive_receipt_is_bound_into_staged_query_evidence(tmp_path):
    row = _research_row(
        source_id="SRC-STAGED-1",
        report_type="个股研报",
        publish_date="2026-06-03",
        discovered_at="2026-06-03T06:00:00+00:00",
        title="Staged evidence report",
        ts_code="600000.SH",
    )
    reader = _reader(tmp_path, [row], [])
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-06-01",
        "date_to": "2026-06-05",
        "max_reports": 30,
    }
    payload = reader(
        "get_stock_research", "600000.SH", "2026-06-01", "2026-06-05", 30
    )
    descriptor = _descriptor(
        "get_stock_research",
        "private.tushare_research_reports",
        args,
        payload,
    )
    upstream = reader.source_receipt(
        "get_stock_research", args, payload, descriptor
    ).as_dict()
    store = StagedQueryReceiptStore(tmp_path / "staged.sqlite3")
    authority = SectorRelationshipSourceEvidenceAuthority(
        root=tmp_path,
        receipt_store=store,
        forward_archive_reader=reader,
    )

    receipts = authority(
        "get_stock_research", args, payload, descriptor, ()
    )

    assert receipts[0]["pit_mode"] == "DERIVED_FROM_PIT_ARCHIVE"
    assert receipts[0]["upstream_evidence_hashes"] == [upstream["receipt_hash"]]
    assert store.resolve(descriptor) == receipts


def test_materializer_uses_forward_archive_and_never_generic_live_authority(tmp_path):
    row = _research_row(
        source_id="SRC-MATERIALIZED-1",
        report_type="个股研报",
        publish_date="2026-06-03",
        discovered_at="2026-06-03T06:00:00+00:00",
        title="Materialized report",
        ts_code="600000.SH",
    )
    reader = _reader(tmp_path, [row], [])
    store = StagedQueryReceiptStore(tmp_path / "materialized-staged.sqlite3")
    authority = SectorRelationshipSourceEvidenceAuthority(
        root=tmp_path,
        receipt_store=store,
        forward_archive_reader=reader,
    )
    digest = "private-safe frozen digest"
    materializer = SectorRelationshipQueryMaterializer(
        receipt_authority=lambda descriptor: pytest.fail(
            f"generic authority must not attest forward archive: {descriptor}"
        ),
        route_caller=TrustedArchiveQueryRouter(
            {"get_stock_research": reader}
        ),
        digest_builder=lambda tool_id, raw, args: {
            "digest": digest,
            "model_hash": canonical_hash({"model": "fixture"}),
            "prompt_hash": canonical_hash({"prompt": "fixture"}),
        },
        source_evidence_authority=authority,
    )

    result = materializer(
        "get_stock_research",
        {
            "ticker": "600000.SH",
            "date_from": "2026-06-01",
            "date_to": "2026-06-05",
            "max_reports": 30,
        },
    )

    assert result["payload"] == digest
    assert len(result["source_receipt_hashes"]) == 1
    assert result["derivation"]["source_payload_hash"].startswith("sha256:")

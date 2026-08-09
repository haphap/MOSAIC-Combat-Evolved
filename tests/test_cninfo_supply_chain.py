from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.cninfo_supply_chain import (
    CninfoSupplyChainDisclosureCollector,
)
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.dataflows.supply_chain_disclosures import (
    OfficialSupplyChainDisclosureArchive,
)


AS_OF = "2026-07-09"


def test_cninfo_collector_captures_full_annual_reports_and_reuses_warm_archive(
    tmp_path: Path,
) -> None:
    archive = OfficialSupplyChainDisclosureArchive(
        tmp_path / ".mosaic/private/supply-chain.sqlite3"
    )
    agent_data_ledger = AgentDataMaterializationLedger(
        tmp_path / ".mosaic/private/agent-data-materialization.sqlite3"
    )
    receipt_store = StagedQueryReceiptStore(
        tmp_path / ".mosaic/private/staged-query-receipts.sqlite3"
    )
    get_calls: list[str] = []
    post_calls: list[dict] = []

    def get_bytes(url: str) -> bytes:
        get_calls.append(url)
        if url.endswith("/new/data/szse_stock.json"):
            return json.dumps(
                {
                    "stockList": [
                        {
                            "code": "600000",
                            "orgId": "gssh0600000",
                            "zwjc": "浦发银行",
                        },
                        {
                            "code": "601398",
                            "orgId": "gssh0601398",
                            "zwjc": "工商银行",
                        },
                    ]
                },
                ensure_ascii=False,
            ).encode()
        if url == "https://static.cninfo.com.cn/finalpage/2026-03-31/full.PDF":
            return b"%PDF-1.7 fake annual report"
        pytest.fail(f"unexpected GET {url}")

    def post_form(url: str, form: dict[str, str]) -> dict:
        assert url == "https://www.cninfo.com.cn/new/hisAnnouncement/query"
        post_calls.append(dict(form))
        if form["pageNum"] == "1":
            return {
                "totalAnnouncement": 2,
                "totalRecordNum": 2,
                "announcements": [
                    {
                        "announcementId": "full",
                        "secCode": "600000",
                        "orgId": "gssh0600000",
                        "announcementTitle": "浦发银行2025年年度报告",
                        "announcementTime": 1774886400000,
                        "adjunctUrl": "finalpage/2026-03-31/full.PDF",
                        "adjunctType": "PDF",
                    },
                    {
                        "announcementId": "summary",
                        "secCode": "600000",
                        "orgId": "gssh0600000",
                        "announcementTitle": "浦发银行2025年年度报告摘要",
                        "announcementTime": 1774886400000,
                        "adjunctUrl": "finalpage/2026-03-31/summary.PDF",
                        "adjunctType": "PDF",
                    },
                ],
            }
        assert form["pageNum"] == "2"
        return {
            "totalAnnouncement": 2,
            "totalRecordNum": 2,
            "announcements": [],
        }

    collector = CninfoSupplyChainDisclosureCollector(
        archive=archive,
        receipt_store=receipt_store,
        agent_data_ledger=agent_data_ledger,
        get_bytes=get_bytes,
        post_form=post_form,
        pdf_text_extractor=lambda content: (
            "主要供应商情况\n前五名供应商采购额\n1 工商银行 1000 12.3%\n"
        ),
    )

    result = collector.materialize(ticker="600000.SH", as_of=AS_OF)

    payload = json.loads(result["payload"])
    staged = receipt_store.receipt_by_hash(result["source_receipt_hashes"][0])
    source = agent_data_ledger.source_capture_receipt(
        receipt_hash=staged["upstream_evidence_hashes"][0]
    )
    assert source is not None
    assert source.as_dict()["identity"]["route_id"] == (
        "official.company_supply_chain_disclosures"
    )
    assert payload["status"] == "EVIDENCE_AVAILABLE"
    assert payload["edges"] == [
        {
            "announced_at": "2026-03-31T23:59:59.999999+08:00",
            "customer_ticker": "600000.SH",
            "document_hash": payload["edges"][0]["document_hash"],
            "document_id": "full",
            "edge_hash": payload["edges"][0]["edge_hash"],
            "report_period": "2025-12-31",
            "supplier_ticker": "601398.SH",
        }
    ]
    assert [call["pageNum"] for call in post_calls] == ["1", "2"]
    assert post_calls[0]["stock"] == "600000,gssh0600000"
    assert post_calls[0]["category"] == "category_ndbg_szsh"
    assert post_calls[0]["seDate"] == "2021-07-10~2026-07-09"
    assert not any("summary.PDF" in url for url in get_calls)
    with sqlite3.connect(archive.db_path) as connection:
        manifest = json.loads(
            connection.execute(
                "SELECT capture_manifest_json FROM supply_chain_captures"
            ).fetchone()[0]
        )
    assert manifest["query_contract"] == {
        "category": "category_ndbg_szsh",
        "column": "szse",
        "content_type": "application/x-www-form-urlencoded",
        "contract_version": "cninfo_annual_report_query_v1",
        "end_date": AS_OF,
        "endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
        "highlight_titles": True,
        "method": "POST",
        "page_size": 30,
        "plate": "",
        "search_key": "",
        "security_id": "",
        "sort_name": "time",
        "sort_type": "desc",
        "start_date": "2021-07-10",
        "stock": "600000,gssh0600000",
        "tab_name": "fulltext",
        "trade": "",
    }

    call_counts = (len(get_calls), len(post_calls))
    assert collector.materialize(ticker="600000.SH", as_of=AS_OF) == result
    assert (len(get_calls), len(post_calls)) == call_counts


def test_cninfo_collector_fails_closed_on_missing_identity_or_pdf_parse_failure(
    tmp_path: Path,
) -> None:
    archive = OfficialSupplyChainDisclosureArchive(
        tmp_path / ".mosaic/private/supply-chain.sqlite3"
    )
    missing = CninfoSupplyChainDisclosureCollector(
        archive=archive,
        get_bytes=lambda url: json.dumps({"stockList": []}).encode(),
        post_form=lambda url, form: pytest.fail("identity failure must precede search"),
        pdf_text_extractor=lambda content: "",
    )
    with pytest.raises(ValueError, match="identity"):
        missing.materialize(ticker="600000.SH", as_of=AS_OF)

    def get_bytes(url: str) -> bytes:
        if url.endswith("szse_stock.json"):
            return json.dumps(
                {
                    "stockList": [
                        {"code": "600000", "orgId": "org-1", "zwjc": "浦发银行"}
                    ]
                }
            ).encode()
        return b"%PDF-1.7 fake"

    def post_form(url: str, form: dict[str, str]) -> dict:
        if form["pageNum"] == "1":
            return {
                "totalAnnouncement": 1,
                "totalRecordNum": 1,
                "announcements": [
                    {
                        "announcementId": "full",
                        "secCode": "600000",
                        "orgId": "org-1",
                        "announcementTitle": "浦发银行2025年年度报告",
                        "announcementTime": 1774886400000,
                        "adjunctUrl": "finalpage/2026-03-31/full.PDF",
                        "adjunctType": "PDF",
                    }
                ],
            }
        return {"totalAnnouncement": 1, "totalRecordNum": 1, "announcements": []}

    broken_pdf = CninfoSupplyChainDisclosureCollector(
        archive=archive,
        get_bytes=get_bytes,
        post_form=post_form,
        pdf_text_extractor=lambda content: (_ for _ in ()).throw(
            ValueError("cannot extract")
        ),
    )
    with pytest.raises(ValueError, match="PDF text extraction"):
        broken_pdf.materialize(ticker="600000.SH", as_of=AS_OF)


def test_cninfo_collector_rejects_malformed_or_non_terminal_provider_pages(
    tmp_path: Path,
) -> None:
    archive = OfficialSupplyChainDisclosureArchive(
        tmp_path / ".mosaic/private/supply-chain.sqlite3"
    )
    stocks = json.dumps(
        {
            "stockList": [
                {"code": "600000", "orgId": "org-1", "zwjc": "浦发银行"}
            ]
        }
    ).encode()
    collector = CninfoSupplyChainDisclosureCollector(
        archive=archive,
        get_bytes=lambda url: stocks,
        post_form=lambda url, form: {
            "totalAnnouncement": 31,
            "totalRecordNum": 31,
            "announcements": [],
        },
        pdf_text_extractor=lambda content: "",
    )
    with pytest.raises(ValueError, match="non-empty|pagination"):
        collector.materialize(ticker="600000.SH", as_of=AS_OF)

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import mosaic.dataflows.cninfo_supply_chain as cninfo_supply_chain
from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.cninfo_supply_chain import (
    CninfoSupplyChainDisclosureCollector,
)
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.dataflows.supply_chain_disclosures import (
    OfficialSupplyChainDisclosureArchive,
)


AS_OF = "2026-07-09"
IDENTITY_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"
QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_URL = "https://static.cninfo.com.cn/finalpage/2026-03-31/full.PDF"
ORIGINAL_PDF_URL = "https://static.cninfo.com.cn/finalpage/2026-03-30/original.PDF"


def test_default_post_form_uses_query_params_only_for_identity(monkeypatch) -> None:
    post_calls = []

    class Response:
        def __init__(self, payload: object) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self.payload

    def post(url, **kwargs):
        post_calls.append((url, kwargs))
        if url == IDENTITY_URL:
            return Response(
                [{"code": "000951", "orgId": "gssz0000951", "zwjc": "中国重汽"}]
            )
        assert url == QUERY_URL
        return Response({"announcements": [], "totalRecordNum": 0})

    monkeypatch.setattr(cninfo_supply_chain.requests, "post", post)

    identity = cninfo_supply_chain._default_post_form(
        IDENTITY_URL,
        {"keyWord": "000951", "maxNum": "10"},
    )
    announcements = cninfo_supply_chain._default_post_form(
        QUERY_URL,
        {"pageNum": "1", "stock": "000951,gssz0000951"},
    )

    assert identity == [{"code": "000951", "orgId": "gssz0000951", "zwjc": "中国重汽"}]
    assert announcements == {"announcements": [], "totalRecordNum": 0}
    expected_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "mosaic-rke/0.1.0",
        "Referer": (
            "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?"
            "url=disclosure%2Flist%2Fsearch"
        ),
    }
    assert post_calls == [
        (
            IDENTITY_URL,
            {
                "params": {"keyWord": "000951", "maxNum": "10"},
                "headers": expected_headers,
                "timeout": 120,
            },
        ),
        (
            QUERY_URL,
            {
                "data": {"pageNum": "1", "stock": "000951,gssz0000951"},
                "headers": expected_headers,
                "timeout": 120,
            },
        ),
    ]


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
    post_calls: list[tuple[str, dict[str, str]]] = []

    def get_bytes(url: str) -> bytes:
        get_calls.append(url)
        if url == PDF_URL:
            return b"%PDF-1.7 fake annual report"
        pytest.fail(f"unexpected GET {url}")

    def post_form(url: str, form: dict[str, str]) -> object:
        post_calls.append((url, dict(form)))
        if url == IDENTITY_URL:
            assert form["maxNum"] == "10"
            if form["keyWord"] == "600000":
                row = {
                    "code": "600000",
                    "orgId": "gssh0600000",
                    "zwjc": "浦发银行",
                }
                return [
                    row,
                    dict(row),
                    {"code": "600001", "orgId": "other", "zwjc": "其他证券"},
                ]
            assert form["keyWord"] == "工商银行"
            row = {
                "code": "601398",
                "orgId": "gssh0601398",
                "zwjc": "工商银行",
            }
            return [
                row,
                dict(row),
                {"code": "600036", "orgId": "fuzzy", "zwjc": "工商银行A"},
            ]
        assert url == QUERY_URL
        if form["pageNum"] == "1":
            return {
                "totalAnnouncement": 3,
                "totalRecordNum": 3,
                "announcements": [
                    {
                        "announcementId": "original",
                        "secCode": "600000",
                        "orgId": "gssh0600000",
                        "announcementTitle": "浦发银行2025年年度报告",
                        "announcementTime": 1774800000000,
                        "adjunctUrl": "finalpage/2026-03-30/original.PDF",
                        "adjunctType": "PDF",
                    },
                    {
                        "announcementId": "full",
                        "secCode": "600000",
                        "orgId": "gssh0600000",
                        "announcementTitle": "浦发银行2025年年度报告（修订版）",
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
            "totalRecordNum": 0,
            "announcements": None,
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
    identity_calls = [form for url, form in post_calls if url == IDENTITY_URL]
    announcement_calls = [form for url, form in post_calls if url == QUERY_URL]
    assert [call["keyWord"] for call in identity_calls] == ["600000", "工商银行"]
    assert [call["pageNum"] for call in announcement_calls] == ["1", "2"]
    assert announcement_calls[0]["stock"] == "600000,gssh0600000"
    assert announcement_calls[0]["category"] == "category_ndbg_szsh"
    assert announcement_calls[0]["seDate"] == "2021-07-10~2026-07-09"
    assert len(post_calls) + len(get_calls) == 5
    assert (
        1
        + cninfo_supply_chain._MAX_SEARCH_PAGES
        + cninfo_supply_chain._MAX_REPORT_YEARS
        * (1 + cninfo_supply_chain._COUNTERPARTY_QUERY_LIMIT_PER_DOCUMENT)
        == 58
    )
    assert not any("szse_stock.json" in url for url in get_calls)
    assert ORIGINAL_PDF_URL not in get_calls
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
        "contract_version": "cninfo_annual_report_query_v2",
        "counterparty_match_policy": "UNIQUE_NORMALIZED_EXACT_NAME",
        "counterparty_query_limit_per_document": 10,
        "end_date": AS_OF,
        "endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
        "highlight_titles": True,
        "identity_endpoint": IDENTITY_URL,
        "identity_match_policy": "UNIQUE_EXACT_CODE",
        "identity_max_results": 10,
        "identity_method": "POST",
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
        get_bytes=lambda url: pytest.fail("identity lookup must not use GET"),
        post_form=lambda url, form: [],
        pdf_text_extractor=lambda content: "",
    )
    with pytest.raises(ValueError, match="identity"):
        missing.materialize(ticker="600000.SH", as_of=AS_OF)

    def get_bytes(url: str) -> bytes:
        assert url == PDF_URL
        return b"%PDF-1.7 fake"

    def post_form(url: str, form: dict[str, str]) -> object:
        if url == IDENTITY_URL:
            assert form == {"keyWord": "600000", "maxNum": "10"}
            return [{"code": "600000", "orgId": "org-1", "zwjc": "浦发银行"}]
        assert url == QUERY_URL
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

    def post_form(url: str, form: dict[str, str]) -> object:
        if url == IDENTITY_URL:
            return [{"code": "600000", "orgId": "org-1", "zwjc": "浦发银行"}]
        assert url == QUERY_URL
        return {
            "totalAnnouncement": 31,
            "totalRecordNum": 31,
            "announcements": [],
        }

    collector = CninfoSupplyChainDisclosureCollector(
        archive=archive,
        get_bytes=lambda url: pytest.fail("malformed page must precede PDF GET"),
        post_form=post_form,
        pdf_text_extractor=lambda content: "",
    )
    with pytest.raises(ValueError, match="candidate set exceeds one page"):
        collector.materialize(ticker="600000.SH", as_of=AS_OF)


def test_cninfo_pdf_explicit_code_does_not_query_counterparty_name(
    tmp_path: Path,
) -> None:
    collector = CninfoSupplyChainDisclosureCollector(
        archive=OfficialSupplyChainDisclosureArchive(
            tmp_path / ".mosaic/private/supply-chain.sqlite3"
        ),
        post_form=lambda url, form: pytest.fail(
            "explicit counterparty code must not query identity"
        ),
        pdf_text_extractor=lambda content: (
            "前五名供应商\n1 工商银行（601398） 1000 12.3%\n"
        ),
    )

    assert collector._parse_document(
        b"%PDF-1.7 fake", {"ticker": "600000.SH"}
    ) == [{"counterparty_ticker": "601398.SH", "counterparty_role": "supplier"}]


@pytest.mark.parametrize(
    "identity_rows",
    [
        [],
        [
            {"code": "601398", "orgId": "org-a", "zwjc": "工商银行"},
            {"code": "600036", "orgId": "org-b", "zwjc": "工商银行"},
        ],
    ],
)
def test_cninfo_counterparty_name_zero_or_ambiguous_abstains(
    tmp_path: Path, identity_rows: list[dict[str, str]]
) -> None:
    calls: list[dict[str, str]] = []

    def post_form(url: str, form: dict[str, str]) -> object:
        assert url == IDENTITY_URL
        calls.append(dict(form))
        return identity_rows

    collector = CninfoSupplyChainDisclosureCollector(
        archive=OfficialSupplyChainDisclosureArchive(
            tmp_path / ".mosaic/private/supply-chain.sqlite3"
        ),
        post_form=post_form,
        pdf_text_extractor=lambda content: "前五名供应商\n1 工商银行 1000 12.3%\n",
    )

    assert collector._parse_document(
        b"%PDF-1.7 fake", {"ticker": "600000.SH"}
    ) == []
    assert calls == [{"keyWord": "工商银行", "maxNum": "10"}]


def test_cninfo_pdf_limits_each_role_to_five_rows_and_ten_name_queries(
    tmp_path: Path,
) -> None:
    supplier_names = ["供应甲", "供应乙", "供应丙", "供应丁", "供应戊", "供应己"]
    customer_names = ["客户甲", "客户乙", "客户丙", "客户丁", "客户戊", "客户己"]
    lines = ["前五名供应商"]
    lines.extend(
        f"{rank} {name} {rank}000 {rank}.0%"
        for rank, name in enumerate(supplier_names, start=1)
    )
    lines.append("前五名客户")
    lines.extend(
        f"{rank} {name} {rank}000 {rank}.0%"
        for rank, name in enumerate(customer_names, start=1)
    )
    calls: list[str] = []

    def post_form(url: str, form: dict[str, str]) -> object:
        assert url == IDENTITY_URL
        calls.append(form["keyWord"])
        return []

    collector = CninfoSupplyChainDisclosureCollector(
        archive=OfficialSupplyChainDisclosureArchive(
            tmp_path / ".mosaic/private/supply-chain.sqlite3"
        ),
        post_form=post_form,
        pdf_text_extractor=lambda content: "\n".join(lines),
    )

    assert collector._parse_document(
        b"%PDF-1.7 fake", {"ticker": "600000.SH"}
    ) == []
    assert calls == supplier_names[:5] + customer_names[:5]

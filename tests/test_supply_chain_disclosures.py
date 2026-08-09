from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from mosaic.dataflows.staged_query_receipts import seal_staged_query_source_receipt
from mosaic.dataflows.supply_chain_disclosures import (
    OfficialSupplyChainDisclosureArchive,
    capture_official_supply_chain_disclosures,
)
import mosaic.dataflows.supply_chain_disclosures as supply_chain_disclosures
from mosaic.scorecard.canonical_json import canonical_hash


AS_OF = "2026-07-09"
PDF_BYTES = b"%PDF-1.7\nprivate official annual report\n%%EOF"
PDF_HASH = "sha256:" + hashlib.sha256(PDF_BYTES).hexdigest()


def _edge(*, role: str = "supplier", announced_at: str = "2026-04-30T18:00:00+08:00"):
    return {
        "issuer_ticker": "600000.SH",
        "counterparty_ticker": "601398.SH",
        "counterparty_role": role,
        "report_period": "2025-12-31",
        "announced_at": announced_at,
        "document_id": "CNINFO-600000-2025-ANNUAL",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-04-30/report.pdf",
        "document_hash": PDF_HASH,
    }


def _documents(edges: list[dict]) -> list[dict]:
    return [
        {
            "document_id": edge["document_id"],
            "document_url": edge["document_url"],
            "content": PDF_BYTES,
        }
        for edge in edges
    ]


def _query_contract() -> dict:
    return {
        "contract_version": "cninfo_annual_report_query_v1",
        "endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
        "method": "POST",
        "content_type": "application/x-www-form-urlencoded",
        "page_size": 30,
        "column": "szse",
        "tab_name": "fulltext",
        "plate": "",
        "stock": "600000,gssh0600000",
        "search_key": "",
        "security_id": "",
        "category": "category_ndbg_szsh",
        "trade": "",
        "start_date": "2021-07-10",
        "end_date": AS_OF,
        "sort_name": "time",
        "sort_type": "desc",
        "highlight_titles": True,
    }


def _manifest(edges: list[dict]) -> dict:
    announcement_ids = sorted({edge["document_id"] for edge in edges})
    return {
        "source": "CNINFO",
        "org_id": "gssh0600000",
        "parser_version": "supply-parser-test-v1",
        "query_contract": _query_contract(),
        "pages": [
            {
                "page_number": 1,
                "has_more": False,
                "announcement_ids": announcement_ids,
            },
            {"page_number": 2, "has_more": False, "announcement_ids": []},
        ],
        "documents": [
            {
                "document_id": edge["document_id"],
                "document_url": edge["document_url"],
                "document_hash": edge["document_hash"],
            }
            for edge in edges
        ],
    }


def _receipt(ticker: str, as_of: str, edges: list[dict], manifest: dict) -> dict:
    descriptor = {
        "tool_id": "get_supply_chain_evidence",
        "route_id": "official.company_supply_chain_disclosures",
        "as_of": as_of,
        "request_hash": canonical_hash({"ticker": ticker, "as_of": as_of}),
        "content_hash": canonical_hash(
            {
                "ticker": ticker,
                "as_of": as_of,
                "disclosures": edges,
                "capture_manifest": manifest,
            }
        ),
        "pit_mode": "AUTHORITATIVE_VINTAGE_REPLAY",
    }
    return seal_staged_query_source_receipt(
        descriptor,
        knowledge_available_at="2026-04-30T18:00:00+08:00",
        captured_at="2026-07-10T09:00:00+08:00",
        upstream_evidence_hashes=(canonical_hash(manifest),),
    )


def _append(archive: OfficialSupplyChainDisclosureArchive, edges: list[dict]) -> str:
    manifest = _manifest(edges)
    return archive.append_capture(
        ticker="600000.SH",
        as_of=AS_OF,
        disclosures=edges,
        source_manifest=manifest,
        documents=_documents(edges),
        source_receipt=_receipt("600000.SH", AS_OF, edges, manifest),
    )


def test_archive_is_private_and_rejects_holder_graph_or_nonofficial_documents(
    tmp_path: Path,
):
    with pytest.raises(ValueError, match="must not be stored in registry"):
        OfficialSupplyChainDisclosureArchive(tmp_path / "registry/supply.sqlite3")

    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    edge = _edge()
    manifest = _manifest([edge])
    bad_receipt = _receipt("600000.SH", AS_OF, [edge], manifest)
    bad_body = {key: value for key, value in bad_receipt.items() if key != "receipt_hash"}
    bad_body["route_id"] = "tushare.relationship_graph"
    bad_receipt = {**bad_body, "receipt_hash": canonical_hash(bad_body)}
    with pytest.raises(ValueError, match="official company disclosure route"):
        archive.append_capture(
            ticker="600000.SH",
            as_of=AS_OF,
            disclosures=[edge],
            source_manifest=manifest,
            documents=_documents([edge]),
            source_receipt=bad_receipt,
        )

    nonofficial = {**edge, "document_url": "https://example.com/report.pdf"}
    with pytest.raises(ValueError, match="CNINFO official document"):
        archive.append_capture(
            ticker="600000.SH",
            as_of=AS_OF,
            disclosures=[nonofficial],
            source_manifest=_manifest([nonofficial]),
            documents=_documents([nonofficial]),
            source_receipt=_receipt(
                "600000.SH", AS_OF, [nonofficial], _manifest([nonofficial])
            ),
        )


@pytest.mark.parametrize(
    ("role", "supplier", "customer"),
    [
        ("supplier", "601398.SH", "600000.SH"),
        ("customer", "600000.SH", "601398.SH"),
    ],
)
def test_reader_preserves_supplier_customer_direction_and_document_lineage(
    tmp_path: Path, role: str, supplier: str, customer: str
):
    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    edge = _edge(role=role)
    manifest = _manifest([edge])
    receipt = _receipt("600000.SH", AS_OF, [edge], manifest)
    _append(archive, [edge])

    result = archive.materialize(ticker="600000.SH", as_of=AS_OF)
    payload = json.loads(result["payload"])
    assert payload["status"] == "EVIDENCE_AVAILABLE"
    assert payload["edges"][0]["supplier_ticker"] == supplier
    assert payload["edges"][0]["customer_ticker"] == customer
    assert payload["edges"][0]["document_hash"] == edge["document_hash"]
    assert result["source_receipt_hashes"] == [receipt["receipt_hash"]]


def test_future_disclosure_is_rejected_and_missing_capture_does_not_fallback(
    tmp_path: Path,
):
    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    future = _edge(announced_at="2026-07-10T00:00:00+08:00")
    with pytest.raises(ValueError, match="announced after capture as_of"):
        archive.append_capture(
            ticker="600000.SH",
            as_of=AS_OF,
            disclosures=[future],
            source_manifest=_manifest([future]),
            documents=_documents([future]),
            source_receipt=_receipt(
                "600000.SH", AS_OF, [future], _manifest([future])
            ),
        )
    with pytest.raises(ValueError, match="no exact authoritative disclosure capture"):
        archive.materialize(ticker="600000.SH", as_of=AS_OF)


def test_exhaustive_empty_capture_returns_explicit_abstention(tmp_path: Path):
    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    manifest = _manifest([])
    receipt = _receipt("600000.SH", AS_OF, [], manifest)
    archive.append_capture(
        ticker="600000.SH",
        as_of=AS_OF,
        disclosures=[],
        source_manifest=manifest,
        documents=[],
        source_receipt=receipt,
    )
    result = archive.materialize(ticker="600000.SH", as_of=AS_OF)
    payload = json.loads(result["payload"])
    assert payload == {
        "as_of": AS_OF,
        "edges": [],
        "schema_version": "official_supply_chain_evidence_v1",
        "status": "ABSTAIN_NO_FACTUAL_EDGE",
        "ticker": "600000.SH",
    }
    assert result["source_receipt_hashes"] == [receipt["receipt_hash"]]


def test_archive_is_append_only_and_reader_detects_private_row_tampering(tmp_path: Path):
    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    edge = _edge()
    _append(archive, [edge])
    with sqlite3.connect(archive.db_path) as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute("UPDATE supply_chain_edges SET edge_json = '{}' ")

        connection.execute("DROP TRIGGER supply_chain_edges_no_update")
        connection.execute("UPDATE supply_chain_edges SET edge_json = '{}' ")
    with pytest.raises(ValueError, match="edge hash mismatch"):
        archive.materialize(ticker="600000.SH", as_of=AS_OF)


def test_trusted_capture_resolves_identity_confirms_terminal_and_persists_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    monkeypatch.setattr(
        supply_chain_disclosures,
        "_capture_now",
        lambda: datetime.fromisoformat("2026-07-10T09:00:00+08:00"),
    )
    page_calls: list[int] = []
    announcement = {
        "announcement_id": "CNINFO-600000-2025-ANNUAL",
        "ticker": "600000.SH",
        "title": "2025 annual report",
        "announced_at": "2026-04-30T18:00:00+08:00",
        "report_period": "2025-12-31",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-04-30/report.pdf",
    }

    def search_page(identity: dict, as_of: str, page_number: int) -> dict:
        assert identity == {"ticker": "600000.SH", "org_id": "gssh0600000"}
        assert as_of == AS_OF
        page_calls.append(page_number)
        if page_number == 1:
            return {"page_number": 1, "has_more": False, "announcements": [announcement]}
        return {"page_number": 2, "has_more": False, "announcements": []}

    capture_id = capture_official_supply_chain_disclosures(
        archive=archive,
        ticker="600000.SH",
        as_of=AS_OF,
        resolve_identity=lambda ticker: {"ticker": ticker, "org_id": "gssh0600000"},
        search_page=search_page,
        download_document=lambda url: PDF_BYTES,
        parse_document=lambda content, metadata: [
            {"counterparty_ticker": "601398.SH", "counterparty_role": "supplier"}
        ],
        parser_version="supply-parser-test-v1",
        build_query_contract=lambda identity, as_of: _query_contract(),
    )

    assert capture_id.startswith("supply_capture_")
    assert page_calls == [1, 2]
    payload = json.loads(archive.materialize(ticker="600000.SH", as_of=AS_OF)["payload"])
    assert payload["edges"][0]["document_hash"] == PDF_HASH
    with sqlite3.connect(archive.db_path) as connection:
        document = connection.execute(
            "SELECT document_hash, content FROM supply_chain_documents"
        ).fetchone()
        receipt = json.loads(
            connection.execute(
                "SELECT source_receipt_json FROM supply_chain_captures"
            ).fetchone()[0]
        )
    assert document == (PDF_HASH, PDF_BYTES)
    assert receipt["captured_at"] == "2026-07-10T09:00:00+08:00"


def test_trusted_capture_warm_retry_reuses_first_complete_capture_without_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    capture_times = iter(
        [
            datetime.fromisoformat("2026-07-10T09:00:00+08:00"),
            datetime.fromisoformat("2026-07-10T10:00:00+08:00"),
        ]
    )
    monkeypatch.setattr(supply_chain_disclosures, "_capture_now", lambda: next(capture_times))
    calls = {"identity": 0, "search": 0, "download": 0, "parse": 0}
    announcement = {
        "announcement_id": "CNINFO-600000-2025-ANNUAL",
        "ticker": "600000.SH",
        "title": "2025 annual report",
        "announced_at": "2026-04-30T18:00:00+08:00",
        "report_period": "2025-12-31",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-04-30/report.pdf",
    }

    def resolve_identity(ticker: str) -> dict:
        calls["identity"] += 1
        return {"ticker": ticker, "org_id": "gssh0600000"}

    def search_page(identity: dict, as_of: str, page_number: int) -> dict:
        calls["search"] += 1
        return {
            "page_number": page_number,
            "has_more": False,
            "announcements": [announcement] if page_number == 1 else [],
        }

    def download_document(url: str) -> bytes:
        calls["download"] += 1
        return PDF_BYTES

    def parse_document(content: bytes, metadata: dict) -> list[dict]:
        calls["parse"] += 1
        return [{"counterparty_ticker": "601398.SH", "counterparty_role": "supplier"}]

    kwargs = {
        "archive": archive,
        "ticker": "600000.SH",
        "as_of": AS_OF,
        "resolve_identity": resolve_identity,
        "search_page": search_page,
        "download_document": download_document,
        "parse_document": parse_document,
        "parser_version": "supply-parser-test-v1",
        "build_query_contract": lambda identity, as_of: _query_contract(),
    }
    first = capture_official_supply_chain_disclosures(**kwargs)
    second = capture_official_supply_chain_disclosures(**kwargs)

    assert first == second
    assert calls == {"identity": 1, "search": 2, "download": 1, "parse": 1}


def test_concurrent_same_supply_capture_transports_once(tmp_path: Path):
    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    entered = threading.Event()
    release = threading.Event()
    second_transport = threading.Event()
    count_lock = threading.Lock()
    identity_calls = 0
    search_calls = 0
    announcement = {
        "announcement_id": "CNINFO-600000-2025-ANNUAL",
        "ticker": "600000.SH",
        "title": "2025 annual report",
        "announced_at": "2026-04-30T18:00:00+08:00",
        "report_period": "2025-12-31",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-04-30/report.pdf",
    }

    def resolve_identity(ticker: str) -> dict:
        nonlocal identity_calls
        with count_lock:
            identity_calls += 1
            if identity_calls == 2:
                second_transport.set()
        entered.set()
        assert release.wait(timeout=5)
        return {"ticker": ticker, "org_id": "gssh0600000"}

    def search_page(identity: dict, as_of: str, page_number: int) -> dict:
        nonlocal search_calls
        with count_lock:
            search_calls += 1
        return {
            "page_number": page_number,
            "has_more": False,
            "announcements": [announcement] if page_number == 1 else [],
        }

    kwargs = {
        "archive": archive,
        "ticker": "600000.SH",
        "as_of": AS_OF,
        "resolve_identity": resolve_identity,
        "search_page": search_page,
        "download_document": lambda url: PDF_BYTES,
        "parse_document": lambda content, metadata: [
            {"counterparty_ticker": "601398.SH", "counterparty_role": "supplier"}
        ],
        "parser_version": "supply-parser-test-v1",
        "build_query_contract": lambda identity, as_of: _query_contract(),
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(capture_official_supply_chain_disclosures, **kwargs)
        assert entered.wait(timeout=5)
        second = executor.submit(capture_official_supply_chain_disclosures, **kwargs)
        assert not second_transport.wait(timeout=0.2)
        release.set()
        assert first.result(timeout=5) == second.result(timeout=5)

    assert identity_calls == 1
    assert search_calls == 2


def test_trusted_capture_rejects_hidden_page_after_terminal(tmp_path: Path):
    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    announcement = {
        "announcement_id": "CNINFO-600000-2025-ANNUAL",
        "ticker": "600000.SH",
        "title": "2025 annual report",
        "announced_at": "2026-04-30T18:00:00+08:00",
        "report_period": "2025-12-31",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-04-30/report.pdf",
    }

    with pytest.raises(ValueError, match="terminal confirmation"):
        capture_official_supply_chain_disclosures(
            archive=archive,
            ticker="600000.SH",
            as_of=AS_OF,
            resolve_identity=lambda ticker: {
                "ticker": ticker,
                "org_id": "gssh0600000",
            },
            search_page=lambda identity, as_of, page_number: {
                "page_number": page_number,
                "has_more": False,
                "announcements": [announcement],
            },
            download_document=lambda url: pytest.fail("pagination must close first"),
            parse_document=lambda content, metadata: [],
            parser_version="supply-parser-test-v1",
            build_query_contract=lambda identity, as_of: _query_contract(),
        )


def test_trusted_capture_can_seal_exhaustive_empty_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive = OfficialSupplyChainDisclosureArchive(tmp_path / ".mosaic/supply.sqlite3")
    monkeypatch.setattr(
        supply_chain_disclosures,
        "_capture_now",
        lambda: datetime.fromisoformat("2026-07-10T09:00:00+08:00"),
    )
    capture_official_supply_chain_disclosures(
        archive=archive,
        ticker="600000.SH",
        as_of=AS_OF,
        resolve_identity=lambda ticker: {"ticker": ticker, "org_id": "gssh0600000"},
        search_page=lambda identity, as_of, page_number: {
            "page_number": page_number,
            "has_more": False,
            "announcements": [],
        },
        download_document=lambda url: pytest.fail("empty capture must not download"),
        parse_document=lambda content, metadata: pytest.fail("empty capture must not parse"),
        parser_version="supply-parser-test-v1",
        build_query_contract=lambda identity, as_of: _query_contract(),
    )
    payload = json.loads(archive.materialize(ticker="600000.SH", as_of=AS_OF)["payload"])
    assert payload["status"] == "ABSTAIN_NO_FACTUAL_EDGE"

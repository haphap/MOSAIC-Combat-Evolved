"""Private authoritative company-disclosure archive for supply-chain facts.

The first complete exact ``(ticker, as_of)`` capture is immutable. Same-key
retries validate and reuse it without transport; a revised source requires a
new as-of slice rather than rewriting historical evidence.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from mosaic.dataflows.staged_query_receipts import (
    seal_staged_query_source_receipt,
    validate_staged_query_source_receipt,
)
from mosaic.scorecard.canonical_json import canonical_hash


ROUTE_ID = "official.company_supply_chain_disclosures"
PAYLOAD_SCHEMA_VERSION = "official_supply_chain_evidence_v1"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TICKER_SUFFIXES = (".SH", ".SZ", ".BJ")
_MAX_SEARCH_PAGES = 200
_DISCLOSURE_FIELDS = {
    "issuer_ticker",
    "counterparty_ticker",
    "counterparty_role",
    "report_period",
    "announced_at",
    "document_id",
    "document_url",
    "document_hash",
}
_IDENTITY_FIELDS = {"ticker", "org_id"}
_PAGE_FIELDS = {"page_number", "has_more", "announcements"}
_ANNOUNCEMENT_FIELDS = {
    "announcement_id",
    "ticker",
    "title",
    "announced_at",
    "report_period",
    "document_url",
}
_PARSED_FACT_FIELDS = {"counterparty_ticker", "counterparty_role"}
_DOCUMENT_INPUT_FIELDS = {"document_id", "document_url", "content"}
_MANIFEST_FIELDS = {"source", "org_id", "parser_version", "pages", "documents"}
_MANIFEST_PAGE_FIELDS = {"page_number", "has_more", "announcement_ids"}
_MANIFEST_DOCUMENT_FIELDS = {"document_id", "document_url", "document_hash"}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _ticker(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 9
        or not value[:6].isdigit()
        or not value.endswith(_TICKER_SUFFIXES)
    ):
        raise ValueError(f"{field} must be an A-share ticker")
    return value


def _sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{field} must be a sha256 identifier")
    return value


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _capture_now() -> datetime:
    return datetime.now(_SHANGHAI)


def _official_document_url(value: Any) -> str:
    document_url = _required_text(value, "document_url")
    parsed_url = urlparse(document_url)
    hostname = (parsed_url.hostname or "").lower()
    if parsed_url.scheme != "https" or not (
        hostname == "cninfo.com.cn" or hostname.endswith(".cninfo.com.cn")
    ):
        raise ValueError("document_url must be a CNINFO official document")
    return document_url


def _capture_descriptor(
    *,
    ticker: str,
    as_of: str,
    disclosures: Sequence[Mapping[str, Any]],
    capture_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "tool_id": "get_supply_chain_evidence",
        "route_id": ROUTE_ID,
        "as_of": as_of,
        "request_hash": canonical_hash({"ticker": ticker, "as_of": as_of}),
        "content_hash": canonical_hash(
            {
                "ticker": ticker,
                "as_of": as_of,
                "disclosures": list(disclosures),
                "capture_manifest": dict(capture_manifest),
            }
        ),
        "pit_mode": "AUTHORITATIVE_VINTAGE_REPLAY",
    }


def _validate_disclosure(
    value: Mapping[str, Any], *, capture_ticker: str, as_of: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _DISCLOSURE_FIELDS:
        raise ValueError("supply-chain disclosure fields do not match the contract")
    issuer = _ticker(value["issuer_ticker"], "issuer_ticker")
    if issuer != capture_ticker:
        raise ValueError("disclosure issuer must equal the capture ticker")
    counterparty = _ticker(value["counterparty_ticker"], "counterparty_ticker")
    if counterparty == issuer:
        raise ValueError("supply-chain counterparty must differ from issuer")
    role = value["counterparty_role"]
    if role not in {"supplier", "customer"}:
        raise ValueError("counterparty_role must be supplier or customer")
    report_period = str(value["report_period"])
    report_date = date.fromisoformat(report_period)
    announced = _timestamp(value["announced_at"], "announced_at")
    as_of_end = datetime.combine(date.fromisoformat(as_of), time.max, tzinfo=_SHANGHAI)
    if announced > as_of_end:
        raise ValueError("supply-chain disclosure was announced after capture as_of")
    if report_date > announced.date():
        raise ValueError("report_period cannot be after announcement date")
    document_id = _required_text(value["document_id"], "document_id")
    document_url = _official_document_url(value["document_url"])
    return {
        "issuer_ticker": issuer,
        "counterparty_ticker": counterparty,
        "counterparty_role": role,
        "report_period": report_period,
        "announced_at": announced.isoformat(),
        "document_id": document_id,
        "document_url": document_url,
        "document_hash": _sha256(value["document_hash"], "document_hash"),
    }


def _validate_capture_manifest(
    value: Mapping[str, Any], *, disclosures: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _MANIFEST_FIELDS:
        raise ValueError("supply-chain capture manifest fields do not match the contract")
    if value["source"] != "CNINFO":
        raise ValueError("supply-chain capture manifest source must be CNINFO")
    org_id = _required_text(value["org_id"], "org_id")
    parser_version = _required_text(value["parser_version"], "parser_version")
    raw_pages = value["pages"]
    if not isinstance(raw_pages, list) or len(raw_pages) < 2:
        raise ValueError("supply-chain capture requires a terminal confirmation page")
    pages: list[dict[str, Any]] = []
    announcement_ids: list[str] = []
    for expected_number, raw_page in enumerate(raw_pages, start=1):
        if not isinstance(raw_page, Mapping) or set(raw_page) != _MANIFEST_PAGE_FIELDS:
            raise ValueError("supply-chain capture manifest page is invalid")
        if raw_page["page_number"] != expected_number:
            raise ValueError("supply-chain capture pages must be contiguous")
        if not isinstance(raw_page["has_more"], bool):
            raise ValueError("supply-chain capture page has_more must be boolean")
        raw_ids = raw_page["announcement_ids"]
        if (
            not isinstance(raw_ids, list)
            or any(not isinstance(item, str) or not item for item in raw_ids)
            or raw_ids != sorted(set(raw_ids))
        ):
            raise ValueError("supply-chain announcement ids must be sorted and unique")
        announcement_ids.extend(raw_ids)
        pages.append(
            {
                "page_number": expected_number,
                "has_more": raw_page["has_more"],
                "announcement_ids": list(raw_ids),
            }
        )
    if pages[-1]["has_more"] or pages[-1]["announcement_ids"]:
        raise ValueError("supply-chain capture requires an empty terminal confirmation page")
    if pages[-2]["has_more"]:
        raise ValueError("supply-chain terminal page was not confirmed")
    if any(not page["has_more"] for page in pages[:-2]):
        raise ValueError("supply-chain capture continued after a terminal page")
    if len(announcement_ids) != len(set(announcement_ids)):
        raise ValueError("duplicate announcement id in supply-chain capture")

    raw_documents = value["documents"]
    if not isinstance(raw_documents, list):
        raise ValueError("supply-chain capture documents must be an array")
    documents: list[dict[str, Any]] = []
    for raw_document in raw_documents:
        if (
            not isinstance(raw_document, Mapping)
            or set(raw_document) != _MANIFEST_DOCUMENT_FIELDS
        ):
            raise ValueError("supply-chain capture document manifest is invalid")
        documents.append(
            {
                "document_id": _required_text(
                    raw_document["document_id"], "document_id"
                ),
                "document_url": _official_document_url(raw_document["document_url"]),
                "document_hash": _sha256(
                    raw_document["document_hash"], "document_hash"
                ),
            }
        )
    documents.sort(key=lambda row: row["document_id"])
    if len({row["document_id"] for row in documents}) != len(documents):
        raise ValueError("duplicate supply-chain capture document id")
    if set(announcement_ids) != {row["document_id"] for row in documents}:
        raise ValueError("announcement and document coverage do not match")
    document_by_id = {row["document_id"]: row for row in documents}
    for disclosure in disclosures:
        document = document_by_id.get(str(disclosure["document_id"]))
        if document is None or document != {
            "document_id": disclosure["document_id"],
            "document_url": disclosure["document_url"],
            "document_hash": disclosure["document_hash"],
        }:
            raise ValueError("disclosure document lineage is not in the capture manifest")
    return {
        "source": "CNINFO",
        "org_id": org_id,
        "parser_version": parser_version,
        "pages": pages,
        "documents": documents,
    }


def _validate_document_input(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _DOCUMENT_INPUT_FIELDS:
        raise ValueError("supply-chain document input fields do not match the contract")
    content = value["content"]
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise ValueError("supply-chain document content must be non-empty bytes")
    content_bytes = bytes(content)
    if not content_bytes.startswith(b"%PDF-"):
        raise ValueError("supply-chain document must be a PDF")
    return {
        "document_id": _required_text(value["document_id"], "document_id"),
        "document_url": _official_document_url(value["document_url"]),
        "document_hash": "sha256:" + hashlib.sha256(content_bytes).hexdigest(),
        "content": content_bytes,
    }


def _validate_announcement(
    value: Mapping[str, Any], *, ticker: str, as_of: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _ANNOUNCEMENT_FIELDS:
        raise ValueError("CNINFO announcement fields do not match the contract")
    announcement_ticker = _ticker(value["ticker"], "announcement ticker")
    if announcement_ticker != ticker:
        raise ValueError("CNINFO announcement ticker does not match capture ticker")
    announced = _timestamp(value["announced_at"], "announced_at")
    as_of_end = datetime.combine(date.fromisoformat(as_of), time.max, tzinfo=_SHANGHAI)
    if announced > as_of_end:
        raise ValueError("CNINFO announcement is after capture as_of")
    report_period = date.fromisoformat(str(value["report_period"]))
    if report_period > announced.date():
        raise ValueError("CNINFO report_period cannot be after announcement date")
    return {
        "announcement_id": _required_text(
            value["announcement_id"], "announcement_id"
        ),
        "ticker": ticker,
        "title": _required_text(value["title"], "announcement title"),
        "announced_at": announced.isoformat(),
        "report_period": report_period.isoformat(),
        "document_url": _official_document_url(value["document_url"]),
    }


def _validate_search_page(
    value: Mapping[str, Any], *, ticker: str, as_of: str, page_number: int
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PAGE_FIELDS:
        raise ValueError("CNINFO search page fields do not match the contract")
    if value["page_number"] != page_number:
        raise ValueError("CNINFO search page number mismatch")
    if not isinstance(value["has_more"], bool):
        raise ValueError("CNINFO search page has_more must be boolean")
    raw_announcements = value["announcements"]
    if not isinstance(raw_announcements, list):
        raise ValueError("CNINFO search page announcements must be an array")
    announcements = [
        _validate_announcement(row, ticker=ticker, as_of=as_of)
        for row in raw_announcements
    ]
    return {
        "page_number": page_number,
        "has_more": value["has_more"],
        "announcements": announcements,
    }


def capture_official_supply_chain_disclosures(
    *,
    archive: "OfficialSupplyChainDisclosureArchive",
    ticker: str,
    as_of: str,
    resolve_identity: Callable[[str], Mapping[str, Any]],
    search_page: Callable[[dict[str, str], str, int], Mapping[str, Any]],
    download_document: Callable[[str], bytes],
    parse_document: Callable[[bytes, dict[str, Any]], Sequence[Mapping[str, Any]]],
    parser_version: str,
) -> str:
    """Capture once or reuse the immutable first complete CNINFO ticker/as-of slice."""

    ticker = _ticker(ticker, "ticker")
    date.fromisoformat(as_of)
    parser_version = _required_text(parser_version, "parser_version")
    with archive._capture_lock(ticker=ticker, as_of=as_of):
        existing_capture_id = archive._existing_capture_id(ticker=ticker, as_of=as_of)
        if existing_capture_id is not None:
            return existing_capture_id
        return _capture_official_supply_chain_disclosures_locked(
            archive=archive,
            ticker=ticker,
            as_of=as_of,
            resolve_identity=resolve_identity,
            search_page=search_page,
            download_document=download_document,
            parse_document=parse_document,
            parser_version=parser_version,
        )


def _capture_official_supply_chain_disclosures_locked(
    *,
    archive: "OfficialSupplyChainDisclosureArchive",
    ticker: str,
    as_of: str,
    resolve_identity: Callable[[str], Mapping[str, Any]],
    search_page: Callable[[dict[str, str], str, int], Mapping[str, Any]],
    download_document: Callable[[str], bytes],
    parse_document: Callable[[bytes, dict[str, Any]], Sequence[Mapping[str, Any]]],
    parser_version: str,
) -> str:
    """Run trusted transport while the exact capture lock is held."""

    ticker = _ticker(ticker, "ticker")
    date.fromisoformat(as_of)
    parser_version = _required_text(parser_version, "parser_version")
    raw_identity = resolve_identity(ticker)
    if not isinstance(raw_identity, Mapping) or set(raw_identity) != _IDENTITY_FIELDS:
        raise ValueError("CNINFO identity fields do not match the contract")
    identity_ticker = _ticker(raw_identity["ticker"], "identity ticker")
    if identity_ticker != ticker:
        raise ValueError("CNINFO identity ticker does not match capture ticker")
    identity = {
        "ticker": identity_ticker,
        "org_id": _required_text(raw_identity["org_id"], "org_id"),
    }

    manifest_pages: list[dict[str, Any]] = []
    announcements: list[dict[str, Any]] = []
    announcement_ids: set[str] = set()
    terminal_pending = False
    for page_number in range(1, _MAX_SEARCH_PAGES + 1):
        page = _validate_search_page(
            search_page(dict(identity), as_of, page_number),
            ticker=ticker,
            as_of=as_of,
            page_number=page_number,
        )
        page_announcements = page["announcements"]
        manifest_pages.append(
            {
                "page_number": page_number,
                "has_more": page["has_more"],
                "announcement_ids": sorted(
                    item["announcement_id"] for item in page_announcements
                ),
            }
        )
        if terminal_pending:
            if page["has_more"] or page_announcements:
                raise ValueError("CNINFO terminal confirmation discovered a hidden page")
            break
        if page["has_more"] and not page_announcements:
            raise ValueError("CNINFO pagination cannot advance from an empty page")
        for announcement in page_announcements:
            announcement_id = announcement["announcement_id"]
            if announcement_id in announcement_ids:
                raise ValueError("duplicate CNINFO announcement id")
            announcement_ids.add(announcement_id)
            announcements.append(announcement)
        terminal_pending = not page["has_more"]
    else:
        raise ValueError("CNINFO search exceeded the bounded page limit")

    documents: list[dict[str, Any]] = []
    document_manifest: list[dict[str, Any]] = []
    disclosures: list[dict[str, Any]] = []
    disclosure_hashes: set[str] = set()
    for announcement in sorted(
        announcements, key=lambda item: item["announcement_id"]
    ):
        content = download_document(announcement["document_url"])
        document = _validate_document_input(
            {
                "document_id": announcement["announcement_id"],
                "document_url": announcement["document_url"],
                "content": content,
            }
        )
        documents.append(
            {key: document[key] for key in _DOCUMENT_INPUT_FIELDS}
        )
        document_manifest.append(
            {key: document[key] for key in _MANIFEST_DOCUMENT_FIELDS}
        )
        parsed_facts = parse_document(document["content"], dict(announcement))
        if not isinstance(parsed_facts, Sequence) or isinstance(
            parsed_facts, (str, bytes, bytearray)
        ):
            raise ValueError("supply-chain parser must return a fact array")
        for fact in parsed_facts:
            if not isinstance(fact, Mapping) or set(fact) != _PARSED_FACT_FIELDS:
                raise ValueError("parsed supply-chain fact fields do not match the contract")
            disclosure = _validate_disclosure(
                {
                    "issuer_ticker": ticker,
                    "counterparty_ticker": fact["counterparty_ticker"],
                    "counterparty_role": fact["counterparty_role"],
                    "report_period": announcement["report_period"],
                    "announced_at": announcement["announced_at"],
                    "document_id": announcement["announcement_id"],
                    "document_url": announcement["document_url"],
                    "document_hash": document["document_hash"],
                },
                capture_ticker=ticker,
                as_of=as_of,
            )
            disclosure_hash = canonical_hash(disclosure)
            if disclosure_hash in disclosure_hashes:
                raise ValueError("duplicate parsed supply-chain fact")
            disclosure_hashes.add(disclosure_hash)
            disclosures.append(disclosure)
    disclosures.sort(
        key=lambda item: (
            item["document_id"],
            item["counterparty_role"],
            item["counterparty_ticker"],
        )
    )
    document_manifest.sort(key=lambda item: item["document_id"])
    documents.sort(key=lambda item: item["document_id"])
    manifest = {
        "source": "CNINFO",
        "org_id": identity["org_id"],
        "parser_version": parser_version,
        "pages": manifest_pages,
        "documents": document_manifest,
    }
    manifest = _validate_capture_manifest(manifest, disclosures=disclosures)
    descriptor = _capture_descriptor(
        ticker=ticker,
        as_of=as_of,
        disclosures=disclosures,
        capture_manifest=manifest,
    )
    knowledge = (
        max(_timestamp(item["announced_at"], "announced_at") for item in announcements)
        if announcements
        else datetime.combine(date.fromisoformat(as_of), time.max, tzinfo=_SHANGHAI)
    )
    captured = _capture_now()
    source_receipt = seal_staged_query_source_receipt(
        descriptor,
        knowledge_available_at=knowledge.isoformat(),
        captured_at=captured.isoformat(),
    )
    return archive.append_capture(
        ticker=ticker,
        as_of=as_of,
        disclosures=disclosures,
        source_manifest=manifest,
        documents=documents,
        source_receipt=source_receipt,
    )


class OfficialSupplyChainDisclosureArchive:
    """Append-only first-complete-wins archive of official supply-chain facts."""

    _thread_locks_guard = threading.Lock()
    _thread_locks: dict[str, threading.Lock] = {}

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        if "registry" in db_path.parts:
            raise ValueError("supply-chain disclosure archive must not be stored in registry")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @classmethod
    def _thread_lock_for(cls, key: str) -> threading.Lock:
        with cls._thread_locks_guard:
            return cls._thread_locks.setdefault(key, threading.Lock())

    @contextmanager
    def _capture_lock(self, *, ticker: str, as_of: str) -> Iterator[None]:
        capture_key = canonical_hash({"ticker": ticker, "as_of": as_of})
        lock_identity = f"{self.db_path.resolve()}:{capture_key}"
        thread_lock = self._thread_lock_for(lock_identity)
        lock_dir = self.db_path.parent / f".{self.db_path.name}.locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f"{capture_key[7:]}.lock"
        with thread_lock, lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _existing_capture_id(self, *, ticker: str, as_of: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT capture_id FROM supply_chain_captures "
                "WHERE ticker = ? AND as_of = ?",
                (ticker, as_of),
            ).fetchone()
        if row is None:
            return None
        self.materialize(ticker=ticker, as_of=as_of)
        return str(row["capture_id"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS supply_chain_captures (
                    capture_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    source_receipt_hash TEXT NOT NULL,
                    source_receipt_json TEXT NOT NULL,
                    capture_manifest_json TEXT NOT NULL,
                    capture_hash TEXT NOT NULL,
                    UNIQUE(ticker, as_of)
                );
                CREATE TABLE IF NOT EXISTS supply_chain_documents (
                    document_id TEXT PRIMARY KEY,
                    document_hash TEXT NOT NULL,
                    document_url TEXT NOT NULL,
                    content BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS supply_chain_capture_documents (
                    capture_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    document_id TEXT NOT NULL,
                    PRIMARY KEY(capture_id, ordinal),
                    UNIQUE(capture_id, document_id),
                    FOREIGN KEY(capture_id) REFERENCES supply_chain_captures(capture_id),
                    FOREIGN KEY(document_id) REFERENCES supply_chain_documents(document_id)
                );
                CREATE TABLE IF NOT EXISTS supply_chain_edges (
                    capture_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    edge_hash TEXT NOT NULL,
                    edge_json TEXT NOT NULL,
                    PRIMARY KEY(capture_id, ordinal),
                    UNIQUE(capture_id, edge_hash),
                    FOREIGN KEY(capture_id) REFERENCES supply_chain_captures(capture_id)
                );
                CREATE TRIGGER IF NOT EXISTS supply_chain_captures_no_update
                  BEFORE UPDATE ON supply_chain_captures BEGIN
                    SELECT RAISE(ABORT, 'supply_chain_captures is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS supply_chain_captures_no_delete
                  BEFORE DELETE ON supply_chain_captures BEGIN
                    SELECT RAISE(ABORT, 'supply_chain_captures is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS supply_chain_edges_no_update
                  BEFORE UPDATE ON supply_chain_edges BEGIN
                    SELECT RAISE(ABORT, 'supply_chain_edges is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS supply_chain_edges_no_delete
                  BEFORE DELETE ON supply_chain_edges BEGIN
                    SELECT RAISE(ABORT, 'supply_chain_edges is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS supply_chain_documents_no_update
                  BEFORE UPDATE ON supply_chain_documents BEGIN
                    SELECT RAISE(ABORT, 'supply_chain_documents is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS supply_chain_documents_no_delete
                  BEFORE DELETE ON supply_chain_documents BEGIN
                    SELECT RAISE(ABORT, 'supply_chain_documents is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS supply_chain_capture_documents_no_update
                  BEFORE UPDATE ON supply_chain_capture_documents BEGIN
                    SELECT RAISE(ABORT, 'supply_chain_capture_documents is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS supply_chain_capture_documents_no_delete
                  BEFORE DELETE ON supply_chain_capture_documents BEGIN
                    SELECT RAISE(ABORT, 'supply_chain_capture_documents is append-only');
                  END;
                """
            )

    def append_capture(
        self,
        *,
        ticker: str,
        as_of: str,
        disclosures: Sequence[Mapping[str, Any]],
        source_manifest: Mapping[str, Any],
        documents: Sequence[Mapping[str, Any]],
        source_receipt: Mapping[str, Any],
    ) -> str:
        ticker = _ticker(ticker, "ticker")
        date.fromisoformat(as_of)
        if not isinstance(disclosures, Sequence) or isinstance(disclosures, (str, bytes)):
            raise ValueError("disclosures must be an array")
        normalized = [
            _validate_disclosure(row, capture_ticker=ticker, as_of=as_of)
            for row in disclosures
        ]
        manifest = _validate_capture_manifest(source_manifest, disclosures=normalized)
        if not isinstance(documents, Sequence) or isinstance(documents, (str, bytes)):
            raise ValueError("documents must be an array")
        normalized_documents = [_validate_document_input(row) for row in documents]
        normalized_documents.sort(key=lambda row: row["document_id"])
        if len({row["document_id"] for row in normalized_documents}) != len(
            normalized_documents
        ):
            raise ValueError("duplicate supply-chain document input")
        input_manifest = [
            {key: row[key] for key in _MANIFEST_DOCUMENT_FIELDS}
            for row in normalized_documents
        ]
        if input_manifest != manifest["documents"]:
            raise ValueError("raw documents do not match the capture manifest")
        if source_receipt.get("route_id") != ROUTE_ID:
            raise ValueError("source receipt must use the official company disclosure route")
        descriptor = _capture_descriptor(
            ticker=ticker,
            as_of=as_of,
            disclosures=normalized,
            capture_manifest=manifest,
        )
        receipt_hash = validate_staged_query_source_receipt(
            source_receipt,
            expected_descriptor=descriptor,
            require_eligible=True,
        )
        capture_body = {
            "ticker": ticker,
            "as_of": as_of,
            "source_receipt_hash": receipt_hash,
            "disclosures": normalized,
            "capture_manifest": manifest,
        }
        capture_hash = canonical_hash(capture_body)
        capture_id = "supply_capture_" + capture_hash[7:]
        encoded_receipt = _canonical_json(source_receipt)
        encoded_manifest = _canonical_json(manifest)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT capture_id, capture_hash FROM supply_chain_captures "
                    "WHERE ticker = ? AND as_of = ?",
                    (ticker, as_of),
                ).fetchone()
                if existing is not None:
                    if existing["capture_hash"] != capture_hash:
                        raise ValueError(
                            "supply-chain capture already exists with different frozen content"
                        )
                    connection.execute("ROLLBACK")
                    return str(existing["capture_id"])
                connection.execute(
                    "INSERT INTO supply_chain_captures VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        capture_id,
                        ticker,
                        as_of,
                        receipt_hash,
                        encoded_receipt,
                        encoded_manifest,
                        capture_hash,
                    ),
                )
                for ordinal, document in enumerate(normalized_documents):
                    existing_document = connection.execute(
                        "SELECT document_hash, document_url, content "
                        "FROM supply_chain_documents WHERE document_id = ?",
                        (document["document_id"],),
                    ).fetchone()
                    if existing_document is None:
                        connection.execute(
                            "INSERT INTO supply_chain_documents VALUES (?, ?, ?, ?)",
                            (
                                document["document_id"],
                                document["document_hash"],
                                document["document_url"],
                                document["content"],
                            ),
                        )
                    elif (
                        existing_document["document_hash"] != document["document_hash"]
                        or existing_document["document_url"] != document["document_url"]
                        or bytes(existing_document["content"]) != document["content"]
                    ):
                        raise ValueError("immutable supply-chain document identity collision")
                    connection.execute(
                        "INSERT INTO supply_chain_capture_documents VALUES (?, ?, ?)",
                        (capture_id, ordinal, document["document_id"]),
                    )
                for ordinal, row in enumerate(normalized):
                    edge_hash = canonical_hash(row)
                    connection.execute(
                        "INSERT INTO supply_chain_edges VALUES (?, ?, ?, ?)",
                        (capture_id, ordinal, edge_hash, _canonical_json(row)),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return capture_id

    def materialize(self, *, ticker: str, as_of: str) -> dict[str, Any]:
        ticker = _ticker(ticker, "ticker")
        date.fromisoformat(as_of)
        with self._connect() as connection:
            capture = connection.execute(
                "SELECT * FROM supply_chain_captures WHERE ticker = ? AND as_of = ?",
                (ticker, as_of),
            ).fetchone()
            if capture is None:
                raise ValueError("no exact authoritative disclosure capture for query")
            rows = connection.execute(
                "SELECT ordinal, edge_hash, edge_json FROM supply_chain_edges "
                "WHERE capture_id = ? ORDER BY ordinal",
                (capture["capture_id"],),
            ).fetchall()
            stored_documents = connection.execute(
                "SELECT linked.ordinal, documents.document_id, documents.document_url, "
                "documents.document_hash, documents.content "
                "FROM supply_chain_capture_documents AS linked "
                "JOIN supply_chain_documents AS documents "
                "ON documents.document_id = linked.document_id "
                "WHERE linked.capture_id = ? ORDER BY linked.ordinal",
                (capture["capture_id"],),
            ).fetchall()

        disclosures: list[dict[str, Any]] = []
        evidence_edges: list[dict[str, Any]] = []
        for stored in rows:
            try:
                raw = json.loads(stored["edge_json"])
            except json.JSONDecodeError as exc:
                raise ValueError("supply-chain edge hash mismatch") from exc
            if canonical_hash(raw) != stored["edge_hash"]:
                raise ValueError("supply-chain edge hash mismatch")
            row = _validate_disclosure(raw, capture_ticker=ticker, as_of=as_of)
            disclosures.append(row)
            if row["counterparty_role"] == "supplier":
                supplier, customer = row["counterparty_ticker"], row["issuer_ticker"]
            else:
                supplier, customer = row["issuer_ticker"], row["counterparty_ticker"]
            evidence_edges.append(
                {
                    "supplier_ticker": supplier,
                    "customer_ticker": customer,
                    "report_period": row["report_period"],
                    "announced_at": row["announced_at"],
                    "document_id": row["document_id"],
                    "document_hash": row["document_hash"],
                    "edge_hash": stored["edge_hash"],
                }
            )

        document_manifest: list[dict[str, Any]] = []
        for stored_document in stored_documents:
            content = bytes(stored_document["content"])
            document_hash = "sha256:" + hashlib.sha256(content).hexdigest()
            if document_hash != stored_document["document_hash"]:
                raise ValueError("supply-chain document hash mismatch")
            document_manifest.append(
                {
                    "document_id": stored_document["document_id"],
                    "document_url": stored_document["document_url"],
                    "document_hash": document_hash,
                }
            )
        try:
            raw_manifest = json.loads(capture["capture_manifest_json"])
        except json.JSONDecodeError as exc:
            raise ValueError("supply-chain capture manifest is invalid") from exc
        manifest = _validate_capture_manifest(raw_manifest, disclosures=disclosures)
        if document_manifest != manifest["documents"]:
            raise ValueError("supply-chain capture document manifest mismatch")
        descriptor = _capture_descriptor(
            ticker=ticker,
            as_of=as_of,
            disclosures=disclosures,
            capture_manifest=manifest,
        )
        receipt = json.loads(capture["source_receipt_json"])
        receipt_hash = validate_staged_query_source_receipt(
            receipt, expected_descriptor=descriptor, require_eligible=True
        )
        capture_body = {
            "ticker": ticker,
            "as_of": as_of,
            "source_receipt_hash": receipt_hash,
            "disclosures": disclosures,
            "capture_manifest": manifest,
        }
        if canonical_hash(capture_body) != capture["capture_hash"]:
            raise ValueError("supply-chain capture hash mismatch")
        evidence_edges.sort(
            key=lambda row: (
                row["announced_at"],
                row["document_id"],
                row["supplier_ticker"],
                row["customer_ticker"],
            )
        )
        payload = {
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "ticker": ticker,
            "as_of": as_of,
            "status": (
                "EVIDENCE_AVAILABLE"
                if evidence_edges
                else "ABSTAIN_NO_FACTUAL_EDGE"
            ),
            "edges": evidence_edges,
        }
        return {
            "payload": _canonical_json(payload),
            "source_receipt_hashes": [receipt_hash],
        }


__all__ = [
    "OfficialSupplyChainDisclosureArchive",
    "PAYLOAD_SCHEMA_VERSION",
    "ROUTE_ID",
    "capture_official_supply_chain_disclosures",
]

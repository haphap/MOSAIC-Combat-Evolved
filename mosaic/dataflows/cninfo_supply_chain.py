"""Official CNINFO transport for the supply-chain disclosure archive."""

from __future__ import annotations

import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.dataflows.supply_chain_disclosures import (
    OfficialSupplyChainDisclosureArchive,
    capture_official_supply_chain_disclosures,
)


IDENTITY_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
DOCUMENT_ROOT = "https://static.cninfo.com.cn/"
PARSER_VERSION = "cninfo_annual_report_listed_counterparties_v1"
_USER_AGENT = "mosaic-rke/0.1.0"
_REFERER = (
    "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?"
    "url=disclosure%2Flist%2Fsearch"
)
_PAGE_SIZE = 30
_LOOKBACK_DAYS = 5 * 365
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ANNUAL_REPORT = re.compile(r"(?P<year>20\d{2})年年度报告")
_ROLE_ANCHORS = {
    "supplier": ("前五名供应商", "前五大供应商", "主要供应商"),
    "customer": ("前五名客户", "前五大客户", "主要客户"),
}


def _default_get_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Referer": _REFERER},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read(_MAX_DOWNLOAD_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError("CNINFO GET request failed") from exc
    if not payload or len(payload) > _MAX_DOWNLOAD_BYTES:
        raise ValueError("CNINFO response is empty or exceeds the size limit")
    return payload


def _default_post_form(url: str, form: Mapping[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _USER_AGENT,
            "Referer": _REFERER,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("CNINFO announcement query failed") from exc
    if not isinstance(payload, dict):
        raise ValueError("CNINFO announcement response must be an object")
    return payload


def _default_pdf_text_extractor(content: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content), strict=True)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise ValueError("CNINFO PDF text extraction failed") from exc
    if not text.strip():
        raise ValueError("CNINFO PDF text extraction returned no text")
    return text


def _ticker_for_code(code: str) -> str:
    if code.startswith(("4", "8", "9")):
        suffix = "BJ"
    elif code.startswith("6"):
        suffix = "SH"
    else:
        suffix = "SZ"
    return f"{code}.{suffix}"


def _announced_at(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("CNINFO announcementTime must be epoch milliseconds")
    published_date = datetime.fromtimestamp(value / 1000, tz=timezone.utc).astimezone(
        _SHANGHAI
    ).date()
    return datetime.combine(published_date, time.max, tzinfo=_SHANGHAI).isoformat()


class CninfoSupplyChainDisclosureCollector:
    """Capture annual-report counterparty evidence into the immutable archive."""

    def __init__(
        self,
        *,
        archive: OfficialSupplyChainDisclosureArchive,
        receipt_store: StagedQueryReceiptStore | None = None,
        agent_data_ledger: AgentDataMaterializationLedger | None = None,
        get_bytes: Callable[[str], bytes] = _default_get_bytes,
        post_form: Callable[[str, Mapping[str, str]], Mapping[str, Any]] = (
            _default_post_form
        ),
        pdf_text_extractor: Callable[[bytes], str] = _default_pdf_text_extractor,
    ) -> None:
        if (receipt_store is None) != (agent_data_ledger is None):
            raise ValueError(
                "active supply-chain evidence requires both receipt store and ledger"
            )
        self.archive = archive
        self.db_path = archive.db_path
        self.receipt_store = receipt_store
        self.agent_data_ledger = agent_data_ledger
        self.get_bytes = get_bytes
        self.post_form = post_form
        self.pdf_text_extractor = pdf_text_extractor
        self._identity_by_code: dict[str, dict[str, str]] | None = None
        self._ticker_by_name: dict[str, str] | None = None

    def _load_identities(self) -> None:
        try:
            payload = json.loads(self.get_bytes(IDENTITY_URL).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("CNINFO identity response is malformed") from exc
        rows = payload.get("stockList") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError("CNINFO identity stockList is missing")
        identity_by_code: dict[str, dict[str, str]] = {}
        ticker_candidates_by_name: dict[str, set[str]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("CNINFO identity row must be an object")
            code = str(row.get("code") or "").strip()
            org_id = str(row.get("orgId") or "").strip()
            name = str(row.get("zwjc") or "").strip()
            if len(code) != 6 or not code.isdigit() or not org_id or not name:
                raise ValueError("CNINFO identity row is incomplete")
            identity = {"ticker": _ticker_for_code(code), "org_id": org_id}
            previous = identity_by_code.get(code)
            if previous is not None and previous != identity:
                raise ValueError("CNINFO identity code is ambiguous")
            identity_by_code[code] = identity
            if len(name) >= 3:
                ticker_candidates_by_name.setdefault(name, set()).add(identity["ticker"])
        self._identity_by_code = identity_by_code
        self._ticker_by_name = {
            name: next(iter(tickers))
            for name, tickers in ticker_candidates_by_name.items()
            if len(tickers) == 1
        }

    def _resolve_identity(self, ticker: str) -> dict[str, str]:
        if self._identity_by_code is None:
            self._load_identities()
        identity = (self._identity_by_code or {}).get(ticker[:6])
        if identity is None or identity["ticker"] != ticker:
            raise ValueError("CNINFO identity is unavailable for ticker")
        return dict(identity)

    def _search_page(
        self,
        identity: dict[str, str],
        as_of: str,
        page_number: int,
    ) -> dict[str, Any]:
        contract = self._query_contract(identity, as_of)
        form = {
            "pageNum": str(page_number),
            "pageSize": str(contract["page_size"]),
            "column": contract["column"],
            "tabName": contract["tab_name"],
            "plate": contract["plate"],
            "stock": contract["stock"],
            "searchkey": contract["search_key"],
            "secid": contract["security_id"],
            "category": contract["category"],
            "trade": contract["trade"],
            "seDate": f"{contract['start_date']}~{contract['end_date']}",
            "sortName": contract["sort_name"],
            "sortType": contract["sort_type"],
            "isHLtitle": "true" if contract["highlight_titles"] else "false",
        }
        raw = self.post_form(QUERY_URL, form)
        announcements = raw.get("announcements") if isinstance(raw, Mapping) else None
        total = raw.get("totalRecordNum") if isinstance(raw, Mapping) else None
        if (
            not isinstance(announcements, list)
            or isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
        ):
            raise ValueError("CNINFO announcement response fields are malformed")
        if total > (page_number - 1) * _PAGE_SIZE and not announcements:
            raise ValueError("CNINFO pagination advertised a non-empty page but returned none")

        normalized: list[dict[str, Any]] = []
        for row in announcements:
            if not isinstance(row, Mapping):
                raise ValueError("CNINFO announcement row must be an object")
            title = str(row.get("announcementTitle") or "").strip()
            match = _ANNUAL_REPORT.search(title)
            if (
                match is None
                or "摘要" in title
                or "英文" in title
                or str(row.get("adjunctType") or "").upper() != "PDF"
            ):
                continue
            adjunct_url = str(row.get("adjunctUrl") or "").lstrip("/")
            if not adjunct_url:
                raise ValueError("CNINFO annual report URL is missing")
            normalized.append(
                {
                    "announcement_id": str(row.get("announcementId") or ""),
                    "ticker": _ticker_for_code(str(row.get("secCode") or "")),
                    "title": title,
                    "announced_at": _announced_at(row.get("announcementTime")),
                    "report_period": f"{match.group('year')}-12-31",
                    "document_url": DOCUMENT_ROOT + adjunct_url,
                }
            )
        return {
            "page_number": page_number,
            "has_more": page_number * _PAGE_SIZE < total,
            "announcements": normalized,
        }

    @staticmethod
    def _query_contract(identity: dict[str, str], as_of: str) -> dict[str, Any]:
        as_of_date = date.fromisoformat(as_of)
        start_date = as_of_date - timedelta(days=_LOOKBACK_DAYS)
        return {
            "contract_version": "cninfo_annual_report_query_v1",
            "endpoint": QUERY_URL,
            "method": "POST",
            "content_type": "application/x-www-form-urlencoded",
            "page_size": _PAGE_SIZE,
            "column": "szse",
            "tab_name": "fulltext",
            "plate": "",
            "stock": f"{identity['ticker'][:6]},{identity['org_id']}",
            "search_key": "",
            "security_id": "",
            "category": "category_ndbg_szsh",
            "trade": "",
            "start_date": start_date.isoformat(),
            "end_date": as_of,
            "sort_name": "time",
            "sort_type": "desc",
            "highlight_titles": True,
        }

    def _download_document(self, url: str) -> bytes:
        payload = self.get_bytes(url)
        if not isinstance(payload, bytes):
            raise ValueError("CNINFO document transport must return bytes")
        return payload

    def _parse_document(
        self,
        content: bytes,
        announcement: dict[str, Any],
    ) -> list[dict[str, str]]:
        try:
            text = self.pdf_text_extractor(content)
        except Exception as exc:
            raise ValueError("CNINFO PDF text extraction failed") from exc
        if not isinstance(text, str) or not text.strip():
            raise ValueError("CNINFO PDF text extraction returned no text")
        if self._ticker_by_name is None:
            self._load_identities()
        lines = [line.strip() for line in text.replace("\r", "\n").splitlines()]
        facts: set[tuple[str, str]] = set()
        for role, anchors in _ROLE_ANCHORS.items():
            anchor_indexes = [
                index
                for index, line in enumerate(lines)
                if any(anchor in line for anchor in anchors)
            ]
            for anchor_index in anchor_indexes:
                window = lines[anchor_index : anchor_index + 80]
                for name, ticker in (self._ticker_by_name or {}).items():
                    if ticker == announcement["ticker"]:
                        continue
                    for line_index, line in enumerate(window):
                        if name not in line:
                            continue
                        nearby = " ".join(
                            window[max(0, line_index - 1) : line_index + 2]
                        )
                        if any(character.isdigit() for character in nearby):
                            facts.add((ticker, role))
                            break
        return [
            {"counterparty_ticker": ticker, "counterparty_role": role}
            for ticker, role in sorted(facts, key=lambda item: (item[1], item[0]))
        ]

    def materialize(self, *, ticker: str, as_of: str) -> dict[str, Any]:
        capture_official_supply_chain_disclosures(
            archive=self.archive,
            ticker=ticker,
            as_of=as_of,
            resolve_identity=self._resolve_identity,
            search_page=self._search_page,
            download_document=self._download_document,
            parse_document=self._parse_document,
            parser_version=PARSER_VERSION,
            build_query_contract=self._query_contract,
        )
        return self.archive.materialize(
            ticker=ticker,
            as_of=as_of,
            receipt_store=self.receipt_store,
            agent_data_ledger=self.agent_data_ledger,
        )


__all__ = ["CninfoSupplyChainDisclosureCollector"]

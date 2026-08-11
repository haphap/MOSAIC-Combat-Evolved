"""Official CNINFO transport for the supply-chain disclosure archive."""

from __future__ import annotations

import io
import re
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.dataflows.supply_chain_disclosures import (
    OfficialSupplyChainDisclosureArchive,
    capture_official_supply_chain_disclosures,
)


IDENTITY_QUERY_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"
QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
DOCUMENT_ROOT = "https://static.cninfo.com.cn/"
PARSER_VERSION = "cninfo_annual_report_listed_counterparties_v2"
_USER_AGENT = "mosaic-rke/0.1.0"
_REFERER = (
    "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?"
    "url=disclosure%2Flist%2Fsearch"
)
_PAGE_SIZE = 30
_LOOKBACK_DAYS = 5 * 365
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
_IDENTITY_MAX_RESULTS = 10
_COUNTERPARTY_QUERY_LIMIT_PER_DOCUMENT = 10
_ROLE_ROW_LIMIT = 5
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ANNUAL_REPORT = re.compile(r"(?P<year>20\d{2})年年度报告")
_RANKED_TABLE_ROW = re.compile(
    r"^\s*(?P<rank>[1-5])(?:[.、．:：)）]\s*|\s+)(?P<body>.+)$"
)
_EXPLICIT_SECURITY_CODE = re.compile(
    r"(?:股票|证券)?代码\s*[:：]?\s*(?P<labelled>\d{6})"
    r"|[（(]\s*(?P<parenthesized>\d{6})\s*[）)]"
)
_NUMERIC_COLUMN = re.compile(
    r"\s+(?=[-+]?\d[\d,]*(?:\.\d+)?(?:%|万|亿|元)?(?:\s|$))"
)
_NUMERIC_VALUE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?(?:%|万|亿|元)?")
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


def _default_post_form(url: str, form: Mapping[str, str]) -> Any:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": _USER_AGENT,
        "Referer": _REFERER,
    }
    try:
        if url == IDENTITY_QUERY_URL:
            response = requests.post(
                url,
                params=dict(form),
                headers=headers,
                timeout=120,
            )
        else:
            response = requests.post(
                url,
                data=dict(form),
                headers=headers,
                timeout=120,
            )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ValueError("CNINFO POST request failed") from exc


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
    if len(code) != 6 or not code.isdigit() or code[0] not in "034689":
        raise ValueError("CNINFO code must be a supported A-share code")
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


def _normalized_security_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", normalized).strip("()（）[]【】")


def _ranked_role_rows(
    lines: list[str], anchors: tuple[str, ...]
) -> list[tuple[int, str]]:
    for anchor_index, line in enumerate(lines):
        if not any(anchor in line for anchor in anchors):
            continue
        rows: list[tuple[int, str]] = []
        expected_rank = 1
        for candidate in lines[anchor_index + 1 : anchor_index + 81]:
            match = _RANKED_TABLE_ROW.fullmatch(candidate)
            if match is None:
                continue
            rank = int(match.group("rank"))
            if rank != expected_rank:
                continue
            body = match.group("body").strip()
            numeric_columns = _NUMERIC_VALUE.findall(body)
            if len(numeric_columns) < 2 and "%" not in body:
                continue
            rows.append((rank, body))
            expected_rank += 1
            if len(rows) == _ROLE_ROW_LIMIT:
                return rows
        if rows:
            return rows
    return []


def _row_security_candidate(body: str) -> tuple[str | None, str | None]:
    explicit = _EXPLICIT_SECURITY_CODE.search(body)
    if explicit is not None:
        labelled = explicit.group("labelled")
        numeric_columns = _NUMERIC_VALUE.findall(body)
        if labelled is not None or len(numeric_columns) >= 3:
            return labelled or explicit.group("parenthesized"), None
    name = _NUMERIC_COLUMN.split(body, maxsplit=1)[0].strip(" ,，;；:：")
    if len(_normalized_security_name(name)) < 2:
        return None, None
    return None, name


class CninfoSupplyChainDisclosureCollector:
    """Capture annual-report counterparty evidence into the immutable archive."""

    def __init__(
        self,
        *,
        archive: OfficialSupplyChainDisclosureArchive,
        receipt_store: StagedQueryReceiptStore | None = None,
        agent_data_ledger: AgentDataMaterializationLedger | None = None,
        get_bytes: Callable[[str], bytes] = _default_get_bytes,
        post_form: Callable[[str, Mapping[str, str]], Any] = _default_post_form,
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
        self._issuer_identity_cache: dict[str, dict[str, str]] = {}
        self._counterparty_ticker_cache: dict[str, str | None] = {}

    def _query_security_identities(self, keyword: str) -> list[dict[str, str]]:
        raw = self.post_form(
            IDENTITY_QUERY_URL,
            {"keyWord": keyword, "maxNum": str(_IDENTITY_MAX_RESULTS)},
        )
        if not isinstance(raw, list) or len(raw) > _IDENTITY_MAX_RESULTS:
            raise ValueError("CNINFO identity response must be a bounded array")
        identities: list[dict[str, str]] = []
        for row in raw:
            if not isinstance(row, Mapping):
                raise ValueError("CNINFO identity row must be an object")
            code = str(row.get("code") or "").strip()
            org_id = str(row.get("orgId") or "").strip()
            name = str(row.get("zwjc") or "").strip()
            if not code or not org_id or not name:
                raise ValueError("CNINFO identity row is incomplete")
            identities.append({"code": code, "org_id": org_id, "name": name})
        return identities

    def _resolve_identity(self, ticker: str) -> dict[str, str]:
        cached = self._issuer_identity_cache.get(ticker)
        if cached is not None:
            return dict(cached)
        matches = {
            (row["code"], row["org_id"], row["name"]): row
            for row in self._query_security_identities(ticker[:6])
            if row["code"] == ticker[:6]
        }
        if len(matches) != 1:
            raise ValueError("CNINFO identity is unavailable for ticker")
        match = next(iter(matches.values()))
        if _ticker_for_code(match["code"]) != ticker:
            raise ValueError("CNINFO identity is unavailable for ticker")
        identity = {"ticker": ticker, "org_id": match["org_id"]}
        self._issuer_identity_cache[ticker] = identity
        return dict(identity)

    def _resolve_counterparty_name(self, name: str) -> str | None:
        normalized = _normalized_security_name(name)
        if normalized in self._counterparty_ticker_cache:
            return self._counterparty_ticker_cache[normalized]
        matches: set[str] = set()
        for row in self._query_security_identities(name):
            if _normalized_security_name(row["name"]) != normalized:
                continue
            try:
                matches.add(_ticker_for_code(row["code"]))
            except ValueError:
                continue
        ticker = next(iter(matches)) if len(matches) == 1 else None
        self._counterparty_ticker_cache[normalized] = ticker
        return ticker

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
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError("CNINFO announcement response fields are malformed")
        if total == 0 and announcements is None:
            announcements = []
        if not isinstance(announcements, list):
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
            "contract_version": "cninfo_annual_report_query_v2",
            "endpoint": QUERY_URL,
            "method": "POST",
            "content_type": "application/x-www-form-urlencoded",
            "identity_endpoint": IDENTITY_QUERY_URL,
            "identity_method": "POST",
            "identity_max_results": _IDENTITY_MAX_RESULTS,
            "identity_match_policy": "UNIQUE_EXACT_CODE",
            "counterparty_match_policy": "UNIQUE_NORMALIZED_EXACT_NAME",
            "counterparty_query_limit_per_document": (
                _COUNTERPARTY_QUERY_LIMIT_PER_DOCUMENT
            ),
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
        lines = [
            line.strip()
            for line in text.replace("\r", "\n").splitlines()
            if line.strip()
        ]
        facts: set[tuple[str, str]] = set()
        queried_names: set[str] = set()
        for role, anchors in _ROLE_ANCHORS.items():
            for _, body in _ranked_role_rows(lines, anchors):
                code, name = _row_security_candidate(body)
                if code is not None:
                    ticker = _ticker_for_code(code)
                elif name is not None:
                    normalized = _normalized_security_name(name)
                    if normalized in queried_names:
                        ticker = self._counterparty_ticker_cache.get(normalized)
                    else:
                        queried_names.add(normalized)
                        if (
                            len(queried_names)
                            > _COUNTERPARTY_QUERY_LIMIT_PER_DOCUMENT
                        ):
                            raise ValueError("CNINFO counterparty query limit exceeded")
                        ticker = self._resolve_counterparty_name(name)
                    if ticker is None:
                        continue
                else:
                    continue
                if ticker != announcement["ticker"]:
                    facts.add((ticker, role))
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

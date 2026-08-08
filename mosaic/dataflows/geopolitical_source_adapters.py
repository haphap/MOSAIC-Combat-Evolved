"""Bounded transport and private-ledger ingestion for geopolitical sources.

Transport preflight only proves that a registered root is reachable.  Formal
event ingestion additionally requires a registered, source-specific parser to
prove publication time and terminal pagination.  Raw responses stay in memory
or in the operator's private cache; only hashes and normalized event metadata
are appended to the private event ledger.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import time
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .cross_runtime_json import canonical_hash, canonical_json
from .exceptions import DataVendorUnavailable
from .geopolitical_events import (
    BUILTIN_GEOPOLITICAL_PARSER_SOURCE_IDS,
    GEOPOLITICAL_TERMINAL_PROOF_KINDS,
    REQUIRED_SOURCE_IDS,
    VERIFIED_GEOPOLITICAL_PREFLIGHT_RECEIPT_SOURCE_IDS,
    GeopoliticalEventStore,
    coverage_query_key,
    geopolitical_store_path,
    load_geopolitical_manifest,
    scope_query_hash,
    validate_event_revision,
    validate_source_capture_observation,
)

GEOPOLITICAL_TRANSPORT_ADAPTER_VERSION = "geopolitical_transport_adapter_v1"
GEOPOLITICAL_INGESTION_VERSION = "geopolitical_private_ingestion_v2"
GEOPOLITICAL_SOURCE_PARSER_VERSION = "geopolitical_source_parser_v1"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_PAGES = 100
TERMINAL_PROOF_KINDS = GEOPOLITICAL_TERMINAL_PROOF_KINDS


@dataclass(frozen=True)
class GeopoliticalTransportResponse:
    request_url: str
    final_url: str
    content_type: str
    body: bytes
    retrieved_at: str


@dataclass(frozen=True)
class GeopoliticalParsedPublication:
    """Prose-free normalized output from one registered source parser."""

    source_record_id: str
    event_type: str
    lifecycle_status: str
    actors: tuple[str, ...]
    affected_regions: tuple[str, ...]
    affected_channels: tuple[str, ...]
    published_at: str
    effective_at: str | None
    causal_dedupe_key: str
    normalized_content_hash: str
    content_hash: str


@dataclass(frozen=True)
class GeopoliticalParsedPage:
    """One parsed page plus a positive proof that pagination terminated."""

    publications: tuple[GeopoliticalParsedPublication, ...]
    next_url: str | None
    terminal_marker_observed: bool
    truncated: bool = False
    terminal_proof_kind: str | None = None


Fetch = Callable[[str, tuple[str, ...]], GeopoliticalTransportResponse]
PageParser = Callable[
    [GeopoliticalTransportResponse, Mapping[str, object]], GeopoliticalParsedPage
]

_BUILTIN_PAGE_PARSERS: dict[str, PageParser] = {}

BUILTIN_SOURCE_PARSER_CONTRACTS: dict[str, dict[str, str]] = {
    "cn_mfa_releases": {"format": "CN_MFA_HTML", "marker": "list1"},
    "cn_mofcom_export_control": {
        "format": "CN_MOFCOM_HTML",
        "marker": "bjgList_01",
    },
    "un_sc_sanctions": {
        "format": "UNSC_CONSOLIDATED_XML",
        "marker": "CONSOLIDATED_LIST",
    },
    "ofac_recent_actions": {"format": "OFAC_HTML", "marker": "views-row"},
    "bis_federal_register": {
        "format": "BIS_NEXT_DATA",
        "marker": "__NEXT_DATA__",
    },
    "ustr_actions": {"format": "USTR_HTML", "marker": "field--name-body"},
    "eu_council_sanctions": {"format": "RSS", "marker": "rss"},
    "eurlex_official_journal": {
        "format": "SPARQL_JSON",
        "marker": "official-journal-act_date_publication",
    },
    "marad_msci": {"format": "RSS", "marker": "rss"},
    "ukmto_advisories": {"format": "UKMTO_JSON", "marker": "sitecoreId"},
    "gdelt_event_gkg": {"format": "JSON_FEED", "marker": "jsonfeed"},
    "un_conflict_releases": {
        "format": "RSS",
        "marker": "rss",
    },
    "us_state_releases": {"format": "HTML", "marker": "collection-result"},
    "eeas_releases": {"format": "EEAS_HTML", "marker": "card-footer"},
}

_DEFAULT_ACTOR_BY_SOURCE = {
    "cn_mfa_releases": "CN",
    "cn_mofcom_export_control": "CN",
    "ofac_recent_actions": "US",
    "bis_federal_register": "US",
    "ustr_actions": "US",
    "eu_council_sanctions": "EU",
    "eurlex_official_journal": "EU",
    "marad_msci": "US",
    "us_state_releases": "US",
    "eeas_releases": "EU",
}

_EVENT_CHANNELS = {
    "SANCTION": ("financial_conditions", "trade"),
    "EXPORT_CONTROL": ("technology", "trade"),
    "TARIFF_TRADE_RESTRICTION": ("trade",),
    "ARMED_CONFLICT": ("energy", "risk_premium"),
    "SHIPPING_DISRUPTION": ("shipping", "supply_chain"),
    "DIPLOMATIC_ESCALATION": ("risk_premium", "trade"),
    "DIPLOMATIC_DEESCALATION": ("risk_premium", "trade"),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_json(value: object) -> str:
    return canonical_json(value)


def _canonical_hash(value: object) -> str:
    return canonical_hash(value)


def _parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DataVendorUnavailable(f"geopolitical {field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"geopolitical {field} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None:
        raise DataVendorUnavailable(
            f"geopolitical {field} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _require_sha256(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise DataVendorUnavailable(
            f"geopolitical {field} must be a canonical sha256 hash"
        )
    try:
        int(value.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"geopolitical {field} must be a canonical sha256 hash"
        ) from exc
    return value


def _host_allowed(host: str | None, allowed_domains: tuple[str, ...]) -> bool:
    if not host:
        return False
    normalized = host.casefold().rstrip(".")
    return any(
        normalized == domain or normalized.endswith(f".{domain}")
        for domain in allowed_domains
    )


def _live_fetch(
    url: str, allowed_domains: tuple[str, ...]
) -> GeopoliticalTransportResponse:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not _host_allowed(parsed.hostname, allowed_domains):
        raise DataVendorUnavailable("geopolitical source URL is not allowlisted")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.1",
            "User-Agent": "MOSAIC-RKE-geopolitical-preflight/1",
        },
        method="GET",
    )
    last_error: Exception | None = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                final_url = response.geturl()
                final_host = urllib.parse.urlparse(final_url).hostname
                if not _host_allowed(final_host, allowed_domains):
                    raise DataVendorUnavailable(
                        "geopolitical source redirected outside its registered domain"
                    )
                raw_body = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(raw_body) > _MAX_RESPONSE_BYTES:
                    raise DataVendorUnavailable(
                        "geopolitical source response exceeds the preflight bound"
                    )
                content_encoding = str(
                    response.headers.get("Content-Encoding", "")
                ).casefold()
                if content_encoding in {"gzip", "x-gzip"}:
                    try:
                        with gzip.GzipFile(fileobj=io.BytesIO(raw_body)) as compressed:
                            body = compressed.read(_MAX_RESPONSE_BYTES + 1)
                    except (EOFError, OSError) as exc:
                        raise DataVendorUnavailable(
                            "geopolitical source returned invalid gzip content"
                        ) from exc
                elif content_encoding in {"", "identity"}:
                    body = raw_body
                else:
                    raise DataVendorUnavailable(
                        "geopolitical source returned an unsupported content encoding"
                    )
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise DataVendorUnavailable(
                        "geopolitical decompressed response exceeds the preflight bound"
                    )
                return GeopoliticalTransportResponse(
                    request_url=url,
                    final_url=final_url,
                    content_type=response.headers.get_content_type(),
                    body=body,
                    retrieved_at=_utc_now().isoformat(),
                )
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = min(30.0, max(0.5, float(retry_after or "1")))
                except ValueError:
                    delay = 1.0
                time.sleep(delay)
            else:
                time.sleep(0.5)
        except (OSError, TimeoutError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise DataVendorUnavailable(f"geopolitical source request failed: {last_error}")


def _manifest_sources(
    manifest: Mapping[str, object],
) -> dict[str, tuple[Mapping[str, object], Mapping[str, object], str]]:
    registrations = {
        str(row["source_id"]): row
        for row in manifest["registrations"]  # type: ignore[index]
        if isinstance(row, Mapping)
    }
    publishers = {
        str(row["publisher_organization_id"]): str(row["domain"])
        for row in manifest["approved_publishers"]  # type: ignore[index]
        if isinstance(row, Mapping)
    }
    sources = {}
    for adapter in manifest["adapter_contracts"]:  # type: ignore[index]
        if not isinstance(adapter, Mapping):
            continue
        source_id = str(adapter["source_id"])
        registration = registrations[source_id]
        domain = publishers[str(registration["publisher_organization_id"])]
        sources[source_id] = (registration, adapter, domain)
    return sources


def registered_geopolitical_source_ids() -> tuple[str, ...]:
    return tuple(sorted(_manifest_sources(load_geopolitical_manifest())))


def _request_url(
    source_id: str,
    canonical_url: str,
    *,
    window_end: datetime | None = None,
) -> str:
    if source_id == "eurlex_official_journal":
        end = (window_end or _utc_now()).astimezone(timezone.utc)
        start_date = (end - timedelta(days=1)).date().isoformat()
        end_date = end.date().isoformat()
        sparql = " ".join(
            (
                "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>",
                "PREFIX owl: <http://www.w3.org/2002/07/owl#>",
                "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>",
                "SELECT DISTINCT ?act ?date ?title WHERE {",
                "?cellarAct cdm:official-journal-act_date_publication ?date .",
                "?cellarAct owl:sameAs ?act .",
                "?expression cdm:expression_belongs_to_work ?cellarAct ;",
                "cdm:expression_uses_language",
                "<http://publications.europa.eu/resource/authority/language/ENG> ;",
                "cdm:expression_title ?title .",
                f'FILTER(?date >= "{start_date}"^^xsd:date',
                f'&& ?date <= "{end_date}"^^xsd:date)',
                'FILTER(regex(str(?act), "/(oj|celex)/"))',
                "FILTER(",
                'CONTAINS(LCASE(STR(?title)), "restrictive measure") ||',
                'CONTAINS(LCASE(STR(?title)), "economic sanction") ||',
                'CONTAINS(LCASE(STR(?title)), "international sanction") ||',
                'CONTAINS(LCASE(STR(?title)), "asset freeze") ||',
                'CONTAINS(LCASE(STR(?title)), "embargo") ||',
                'CONTAINS(LCASE(STR(?title)), "export control") ||',
                'CONTAINS(LCASE(STR(?title)), "dual-use") ||',
                'CONTAINS(LCASE(STR(?title)), "dual use") ||',
                'CONTAINS(LCASE(STR(?title)), "tariff") ||',
                'CONTAINS(LCASE(STR(?title)), "trade restriction")',
                ") } ORDER BY ?date ?act LIMIT 250",
            )
        )
        query = urllib.parse.urlencode(
            {
                "query": sparql,
                "format": "application/sparql-results+json",
            }
        )
        return f"{canonical_url}?{query}"
    if source_id == "gdelt_event_gkg":
        end = (window_end or _utc_now()).astimezone(timezone.utc)
        start = end - timedelta(minutes=30)
        query = urllib.parse.urlencode(
            {
                "query": (
                    '(sanction OR "export control" OR tariff OR "armed conflict" '
                    'OR "shipping disruption" OR "diplomatic escalation" OR '
                    '"diplomatic de-escalation")'
                ),
                "mode": "artlist",
                "maxrecords": "250",
                "format": "jsonfeed",
                "sort": "datedesc",
                "startdatetime": start.strftime("%Y%m%d%H%M%S"),
                "enddatetime": end.strftime("%Y%m%d%H%M%S"),
            }
        )
        return f"{canonical_url}?{query}"
    if source_id != "ocha_reliefweb":
        return canonical_url
    query = urllib.parse.urlencode(
        {
            "appname": "mosaic-rke",
            "limit": "1",
            "profile": "list",
            "preset": "latest",
        }
    )
    return f"{canonical_url}?{query}"


def _validate_broad_response(
    *, source_id: str, retrieval_mode: str, content_type: str, body: bytes
) -> str:
    if not body.strip():
        raise DataVendorUnavailable("geopolitical source returned an empty response")
    lowered = body[:4096].lower()
    if any(
        marker in lowered
        for marker in (
            b"<title>client challenge</title>",
            b"<title>technical difficulties</title>",
        )
    ):
        raise DataVendorUnavailable(
            "geopolitical source returned an access/error interstitial"
        )
    if retrieval_mode == "API":
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataVendorUnavailable(
                "geopolitical API response is not valid JSON"
            ) from exc
        if source_id == "ukmto_advisories" and isinstance(payload, list):
            return "JSON_ARRAY"
        if not isinstance(payload, Mapping):
            raise DataVendorUnavailable("geopolitical API response must be an object")
        if source_id == "gdelt_event_gkg" and not isinstance(
            payload.get("items"), list
        ):
            raise DataVendorUnavailable("GDELT JSONFeed response shape mismatch")
        if source_id == "eurlex_official_journal":
            results = payload.get("results")
            if not isinstance(results, Mapping) or not isinstance(
                results.get("bindings"), list
            ):
                raise DataVendorUnavailable(
                    "EUR-Lex CELLAR SPARQL response shape mismatch"
                )
        return "JSON_OBJECT"
    if retrieval_mode == "RSS":
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as exc:
            raise DataVendorUnavailable(
                "geopolitical RSS response is not valid XML"
            ) from exc
        if root.tag.rsplit("}", 1)[-1].casefold() not in {"rss", "feed"}:
            raise DataVendorUnavailable("geopolitical RSS root shape mismatch")
        return "RSS_DOCUMENT"
    if retrieval_mode == "FILE_FEED" and source_id == "un_sc_sanctions":
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as exc:
            raise DataVendorUnavailable(
                "UNSC consolidated list response is not valid XML"
            ) from exc
        if root.tag.rsplit("}", 1)[-1] != "CONSOLIDATED_LIST":
            raise DataVendorUnavailable("UNSC consolidated list root shape mismatch")
        return "UNSC_CONSOLIDATED_XML"
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise DataVendorUnavailable(
            "geopolitical directory response does not have an HTML document shape"
        )
    if "html" not in content_type and content_type not in {
        "application/octet-stream",
        "text/plain",
    }:
        raise DataVendorUnavailable(
            "geopolitical directory response has an unexpected content type"
        )
    return "HTML_DOCUMENT"


def _normalized_space(value: str) -> str:
    return " ".join(value.split())


def _parse_source_timestamp(value: str) -> str:
    text = _normalized_space(value)
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            parsed = None
    if parsed is None:
        for pattern in (
            r"^(\d{4})年(\d{1,2})月(\d{1,2})日$",
            r"^(\d{4})-(\d{2})-(\d{2})$",
        ):
            match = re.match(pattern, text)
            if match:
                parsed = datetime(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    tzinfo=timezone.utc,
                )
                break
    if parsed is None:
        match = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$", text)
        if match:
            parsed = datetime(
                int(match.group(3)),
                int(match.group(2)),
                int(match.group(1)),
                tzinfo=timezone.utc,
            )
    if parsed is None:
        for pattern in ("%B %d, %Y", "%b %d, %Y"):
            try:
                parsed = datetime.strptime(text, pattern).replace(
                    tzinfo=timezone.utc
                )
                break
            except ValueError:
                continue
    if parsed is None:
        raise DataVendorUnavailable(
            "geopolitical source publication timestamp is unparseable"
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _xml_child_text(node: ElementTree.Element, *names: str) -> str | None:
    expected = {name.casefold() for name in names}
    for child in node.iter():
        if child is node:
            continue
        if _local_name(child.tag) in expected and child.text and child.text.strip():
            return child.text.strip()
    return None


def _html_records(
    response: GeopoliticalTransportResponse, contract: Mapping[str, str]
) -> tuple[list[dict[str, str]], str | None, bool]:
    try:
        text = response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DataVendorUnavailable(
            "geopolitical source-specific schema requires UTF-8 HTML"
        ) from exc
    soup = BeautifulSoup(text, "html.parser")
    marker = contract["marker"]
    container = soup.find(class_=lambda value: value and marker in str(value).split())
    if container is None:
        raise DataVendorUnavailable(
            "geopolitical source-specific schema marker is missing"
        )
    candidates = container.select("article, li, tr") or [container]
    records: list[dict[str, str]] = []
    for item in candidates:
        anchor = item.find("a", href=True)
        timestamp = item.find("time")
        if anchor is None or timestamp is None:
            continue
        title = _normalized_space(anchor.get_text(" ", strip=True))
        published = timestamp.get("datetime") or timestamp.get_text(" ", strip=True)
        if not title or not published:
            continue
        record_url = urllib.parse.urljoin(response.final_url, str(anchor["href"]))
        records.append(
            {
                "source_record_id": record_url,
                "title": title,
                "published_at": str(published),
                "content_signature": _normalized_space(item.get_text(" ", strip=True)),
            }
        )
    next_anchor = soup.select_one(
        "a[rel='next'], a.pager__link--next, a.next, li.next > a"
    )
    next_url = (
        urllib.parse.urljoin(response.final_url, str(next_anchor["href"]))
        if next_anchor is not None and next_anchor.get("href")
        else None
    )
    return records, next_url, next_url is None


def _html_soup(response: GeopoliticalTransportResponse) -> BeautifulSoup:
    try:
        text = response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DataVendorUnavailable(
            "geopolitical source-specific schema requires UTF-8 HTML"
        ) from exc
    return BeautifulSoup(text, "html.parser")


_DATE_TEXT_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{4}\b"),
    re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},\s+\d{4}\b",
        re.IGNORECASE,
    ),
)


def _date_text(value: str) -> str | None:
    for pattern in _DATE_TEXT_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(0)
    return None


def _dedupe_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        identity = (record["source_record_id"], record["published_at"])
        if identity not in seen:
            deduped.append(record)
            seen.add(identity)
    return deduped


def _bounded_daily_directory_page(
    response: GeopoliticalTransportResponse,
    records: list[dict[str, str]],
    next_url: str | None,
) -> tuple[str | None, bool]:
    """Stop a sorted directory after it proves a full overlapping day."""
    if next_url is None:
        return None, True
    if not records:
        return next_url, False
    published = [
        _parse_utc(_parse_source_timestamp(row["published_at"]), "published_at")
        for row in records
    ]
    if any(later > earlier for earlier, later in zip(published, published[1:])):
        raise DataVendorUnavailable(
            "geopolitical bounded directory is not reverse chronological"
        )
    retrieved = _parse_utc(response.retrieved_at, "retrieved_at")
    if published[-1] <= retrieved - timedelta(hours=24):
        return None, True
    return next_url, False


def _bis_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    soup = _html_soup(response)
    node = soup.find("script", id="__NEXT_DATA__")
    if node is None or not node.string:
        raise DataVendorUnavailable(
            "geopolitical BIS schema requires __NEXT_DATA__"
        )
    try:
        rows = json.loads(node.string)["props"]["pageProps"]["frns"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            "geopolitical BIS schema lacks Federal Register rows"
        ) from exc
    if not isinstance(rows, list) or not rows:
        raise DataVendorUnavailable(
            "geopolitical BIS schema has no Federal Register rows"
        )
    records: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise DataVendorUnavailable(
                "geopolitical BIS schema has an invalid row"
            )
        title = row.get("frnTitle")
        date_value = row.get("frnPublicationDate")
        url_value = row.get("frnUrl")
        published = date_value.get("time") if isinstance(date_value, Mapping) else None
        record_url = url_value.get("url") if isinstance(url_value, Mapping) else None
        if not all(
            isinstance(value, str) and value.strip()
            for value in (title, published, record_url)
        ):
            raise DataVendorUnavailable(
                "geopolitical BIS schema has an incomplete row"
            )
        records.append(
            {
                "source_record_id": str(record_url),
                "title": _normalized_space(str(title)),
                "published_at": str(published),
                "content_signature": _canonical_json(
                    {
                        "citation": row.get("frnCitation"),
                        "document_type": row.get("frnDocumentType"),
                        "title": title,
                        "url": record_url,
                    }
                ),
            }
        )
    return _dedupe_records(records), None, True, False


def _cn_mfa_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    soup = _html_soup(response)
    records: list[dict[str, str]] = []
    for item in soup.select(".list1 li, .wjmt_list li"):
        anchor = item.find("a", href=True)
        if anchor is None:
            continue
        text = _normalized_space(anchor.get_text(" ", strip=True))
        published = _date_text(text)
        if published is None:
            continue
        title = re.sub(
            r"[（(]\s*" + re.escape(published) + r"\s*[）)]\s*$", "", text
        ).strip()
        if not title:
            continue
        records.append(
            {
                "source_record_id": urllib.parse.urljoin(
                    response.final_url, str(anchor["href"])
                ),
                "title": title,
                "published_at": published,
                "content_signature": text,
            }
        )
    if not records:
        raise DataVendorUnavailable(
            "geopolitical CN MFA schema has no dated release rows"
        )
    return _dedupe_records(records), None, True, False


def _cn_mofcom_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    soup = _html_soup(response)
    records: list[dict[str, str]] = []
    for item in soup.select(".bjgList_01 li"):
        anchor = item.find("a", href=True)
        if anchor is None:
            continue
        published = _date_text(item.get_text(" ", strip=True))
        title = _normalized_space(anchor.get_text(" ", strip=True))
        if published is None or not title:
            continue
        records.append(
            {
                "source_record_id": urllib.parse.urljoin(
                    response.final_url, str(anchor["href"])
                ),
                "title": title,
                "published_at": published,
                "content_signature": _normalized_space(
                    item.get_text(" ", strip=True)
                ),
            }
        )
    if not records:
        raise DataVendorUnavailable(
            "geopolitical CN MOFCOM schema has no dated release rows"
        )
    return _dedupe_records(records), None, True, False


def _eeas_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    soup = _html_soup(response)
    records: list[dict[str, str]] = []
    for card in soup.select(".card"):
        footer = card.select_one(".card-footer.node__meta, .card-footer")
        body = card.select_one(".card-body")
        anchor = body.find("a", href=True) if body is not None else None
        published = _date_text(footer.get_text(" ", strip=True)) if footer else None
        title = (
            _normalized_space(anchor.get_text(" ", strip=True))
            if anchor is not None
            else ""
        )
        if published is None or not title or anchor is None:
            continue
        records.append(
            {
                "source_record_id": urllib.parse.urljoin(
                    response.final_url, str(anchor["href"])
                ),
                "title": title,
                "published_at": published,
                "content_signature": _normalized_space(
                    card.get_text(" ", strip=True)
                ),
            }
        )
    records = _dedupe_records(records)
    if not records:
        raise DataVendorUnavailable(
            "geopolitical EEAS schema has no dated press cards"
        )
    next_anchor = soup.select_one("a[rel='next'], a.pager__link--next")
    next_url = (
        urllib.parse.urljoin(response.final_url, str(next_anchor["href"]))
        if next_anchor is not None and next_anchor.get("href")
        else None
    )
    next_url, terminal = _bounded_daily_directory_page(
        response, records, next_url
    )
    return records, next_url, terminal, False


def _ofac_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    soup = _html_soup(response)
    records: list[dict[str, str]] = []
    for item in soup.select(".views-row"):
        anchor = item.find("a", href=re.compile(r"/recent-actions/\d{8}$"))
        published = _date_text(item.get_text(" ", strip=True))
        title = (
            _normalized_space(anchor.get_text(" ", strip=True))
            if anchor is not None
            else ""
        )
        if published is None or not title or anchor is None:
            continue
        records.append(
            {
                "source_record_id": urllib.parse.urljoin(
                    response.final_url, str(anchor["href"])
                ),
                "title": title,
                "published_at": published,
                "content_signature": _normalized_space(
                    item.get_text(" ", strip=True)
                ),
            }
        )
    records = _dedupe_records(records)
    if not records:
        raise DataVendorUnavailable(
            "geopolitical OFAC schema has no dated recent-action rows"
        )
    next_anchor = soup.select_one("a[rel='next'], a.pager__link--next")
    next_url = (
        urllib.parse.urljoin(response.final_url, str(next_anchor["href"]))
        if next_anchor is not None and next_anchor.get("href")
        else None
    )
    next_url, terminal = _bounded_daily_directory_page(
        response, records, next_url
    )
    return records, next_url, terminal, False


def _unsc_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    try:
        root = ElementTree.fromstring(response.body)
    except ElementTree.ParseError as exc:
        raise DataVendorUnavailable(
            "geopolitical UNSC schema requires consolidated XML"
        ) from exc
    if root.tag.rsplit("}", 1)[-1] != "CONSOLIDATED_LIST":
        raise DataVendorUnavailable(
            "geopolitical UNSC schema has an invalid consolidated-list root"
        )
    generated_at = root.attrib.get("dateGenerated")
    containers = {
        child.tag.rsplit("}", 1)[-1]: child
        for child in root
        if child.tag.rsplit("}", 1)[-1] in {"INDIVIDUALS", "ENTITIES"}
    }
    if (
        not isinstance(generated_at, str)
        or not generated_at.strip()
        or set(containers) != {"INDIVIDUALS", "ENTITIES"}
        or any(not list(container) for container in containers.values())
    ):
        raise DataVendorUnavailable(
            "geopolitical UNSC schema has an incomplete consolidated list"
        )
    return (
        [
            {
                "source_record_id": "unsc-consolidated-list",
                "title": (
                    "United Nations Security Council consolidated sanctions list "
                    "revision"
                ),
                "published_at": generated_at,
                "content_signature": (
                    f"{generated_at} {_sha256_bytes(response.body)}"
                ),
            }
        ],
        None,
        True,
        False,
    )


def _eurlex_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            "geopolitical EUR-Lex schema requires SPARQL JSON"
        ) from exc
    results = payload.get("results") if isinstance(payload, Mapping) else None
    bindings = results.get("bindings") if isinstance(results, Mapping) else None
    if not isinstance(bindings, list):
        raise DataVendorUnavailable(
            "geopolitical EUR-Lex schema requires SPARQL bindings"
        )
    records: list[dict[str, str]] = []
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise DataVendorUnavailable(
                "geopolitical EUR-Lex schema has an invalid SPARQL binding"
            )
        act = binding.get("act")
        published = binding.get("date")
        title = binding.get("title")
        if (
            not isinstance(act, Mapping)
            or not isinstance(published, Mapping)
            or not isinstance(title, Mapping)
        ):
            raise DataVendorUnavailable(
                "geopolitical EUR-Lex schema has an incomplete SPARQL binding"
            )
        act_value = act.get("value")
        published_value = published.get("value")
        title_value = title.get("value")
        if (
            act.get("type") != "uri"
            or published.get("type") != "literal"
            or published.get("datatype")
            != "http://www.w3.org/2001/XMLSchema#date"
            or title.get("type") != "literal"
            or str(title.get("xml:lang", "")).casefold() != "en"
            or not all(
                isinstance(value, str) and value.strip()
                for value in (act_value, published_value, title_value)
            )
        ):
            raise DataVendorUnavailable(
                "geopolitical EUR-Lex schema has an invalid SPARQL binding"
            )
        records.append(
            {
                "source_record_id": str(act_value),
                "title": _normalized_space(str(title_value)),
                "published_at": str(published_value),
                "content_signature": _normalized_space(
                    f"{act_value} {published_value} {title_value}"
                ),
            }
        )
    records = _dedupe_records(records)
    truncated = len(bindings) >= 250
    return records, None, not truncated, truncated


def _ustr_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    soup = _html_soup(response)
    container = soup.select_one("article .field--name-body, .field--name-body")
    if container is None:
        raise DataVendorUnavailable(
            "geopolitical USTR schema lacks the Section 301 body"
        )
    records: list[dict[str, str]] = []
    for anchor in container.find_all("a", href=True):
        parent = anchor.find_parent(["p", "li"]) or anchor.parent
        text = _normalized_space(parent.get_text(" ", strip=True))
        published = _date_text(text)
        title = _normalized_space(anchor.get_text(" ", strip=True))
        if published is None or not title:
            continue
        records.append(
            {
                "source_record_id": urllib.parse.urljoin(
                    response.final_url, str(anchor["href"])
                ),
                "title": title,
                "published_at": published,
                "content_signature": text,
            }
        )
    if not records:
        raise DataVendorUnavailable(
            "geopolitical USTR schema has no dated Section 301 rows"
        )
    return _dedupe_records(records), None, True, False


def _ukmto_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    try:
        rows = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            "geopolitical UKMTO schema requires JSON"
        ) from exc
    if not isinstance(rows, list):
        raise DataVendorUnavailable(
            "geopolitical UKMTO schema requires an incident array"
        )
    records: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise DataVendorUnavailable(
                "geopolitical UKMTO schema has an invalid incident"
            )
        record_id = row.get("sitecoreId")
        published = row.get("utcDateOfIncident")
        incident_type = row.get("incidentTypeName")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (record_id, published, incident_type)
        ):
            raise DataVendorUnavailable(
                "geopolitical UKMTO schema has an incomplete incident"
            )
        place = row.get("place") if isinstance(row.get("place"), str) else ""
        region = row.get("region") if isinstance(row.get("region"), str) else ""
        records.append(
            {
                "source_record_id": f"ukmto:{record_id}",
                "title": _normalized_space(
                    f"Shipping disruption {incident_type} {place} {region}"
                ),
                "published_at": str(published),
                "event_type": "SHIPPING_DISRUPTION",
                "content_signature": _canonical_json(
                    {
                        "incident_issuer": row.get("incidentIssuer"),
                        "incident_number": row.get("incidentNumber"),
                        "incident_type": incident_type,
                        "place": place,
                        "region": region,
                        "sitecore_id": record_id,
                        "utc_date_of_incident": published,
                    }
                ),
            }
        )
    return _dedupe_records(records), None, True, False


def _rss_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool]:
    try:
        root = ElementTree.fromstring(response.body)
    except ElementTree.ParseError as exc:
        raise DataVendorUnavailable(
            "geopolitical source-specific schema requires valid RSS"
        ) from exc
    if _local_name(root.tag) not in {"rss", "feed"}:
        raise DataVendorUnavailable(
            "geopolitical source-specific schema requires an RSS root"
        )
    records: list[dict[str, str]] = []
    for item in root.iter():
        if _local_name(item.tag) not in {"item", "entry"}:
            continue
        title = _xml_child_text(item, "title")
        published = _xml_child_text(item, "pubdate", "published", "updated")
        record_id = _xml_child_text(item, "guid", "id", "link")
        if not title or not published or not record_id:
            raise DataVendorUnavailable(
                "geopolitical source-specific schema has an incomplete RSS item"
            )
        records.append(
            {
                "source_record_id": record_id,
                "title": _normalized_space(title),
                "published_at": published,
                "content_signature": _normalized_space(
                    " ".join(part for part in item.itertext() if part.strip())
                ),
            }
        )
    next_url = None
    for node in root.iter():
        if _local_name(node.tag) == "link" and node.attrib.get("rel") == "next":
            next_url = node.attrib.get("href") or (node.text or "").strip() or None
            break
    return records, next_url, next_url is None


def _json_feed_records(
    response: GeopoliticalTransportResponse,
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            "geopolitical source-specific schema requires JSONFeed"
        ) from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
        raise DataVendorUnavailable(
            "geopolitical source-specific schema requires JSONFeed items"
        )
    records: list[dict[str, str]] = []
    for item in payload["items"]:
        if not isinstance(item, Mapping):
            raise DataVendorUnavailable(
                "geopolitical source-specific schema has an invalid JSONFeed item"
            )
        record_id = item.get("id") or item.get("url")
        title = item.get("title")
        published = (
            item.get("date_published")
            or item.get("date_modified")
            or response.retrieved_at
        )
        if not all(
            isinstance(value, str) and value.strip()
            for value in (record_id, title, published)
        ):
            raise DataVendorUnavailable(
                "geopolitical source-specific schema has an incomplete JSONFeed item"
            )
        records.append(
            {
                "source_record_id": str(record_id),
                "title": _normalized_space(str(title)),
                "published_at": str(published),
                "content_signature": _normalized_space(
                    " ".join(
                        str(item.get(field, ""))
                        for field in ("title", "summary", "content_text", "url")
                    )
                ),
            }
        )
    next_url = payload.get("next_url")
    if next_url is not None and not isinstance(next_url, str):
        raise DataVendorUnavailable(
            "geopolitical source-specific schema has an invalid JSONFeed cursor"
        )
    truncated = len(records) >= 250
    return records, next_url, next_url is None and not truncated, truncated


_SOURCE_RECORD_BUILDERS: dict[
    str,
    Callable[
        [GeopoliticalTransportResponse],
        tuple[list[dict[str, str]], str | None, bool, bool],
    ],
] = {
    "bis_federal_register": _bis_records,
    "cn_mfa_releases": _cn_mfa_records,
    "cn_mofcom_export_control": _cn_mofcom_records,
    "eeas_releases": _eeas_records,
    "eurlex_official_journal": _eurlex_records,
    "ofac_recent_actions": _ofac_records,
    "un_sc_sanctions": _unsc_records,
    "ukmto_advisories": _ukmto_records,
    "ustr_actions": _ustr_records,
}


def _source_records(
    source_id: str,
    response: GeopoliticalTransportResponse,
    contract: Mapping[str, str],
) -> tuple[list[dict[str, str]], str | None, bool, bool]:
    builder = _SOURCE_RECORD_BUILDERS.get(source_id)
    if builder is not None:
        return builder(response)
    if contract["format"] == "RSS":
        records, next_url, terminal = _rss_records(response)
        return records, next_url, terminal, False
    if contract["format"] == "JSON_FEED":
        return _json_feed_records(response)
    records, next_url, terminal = _html_records(response, contract)
    return records, next_url, terminal, False


def _terminal_proof_kind(
    source_id: str,
    response: GeopoliticalTransportResponse,
    *,
    terminal: bool,
    truncated: bool,
) -> str | None:
    if not terminal or truncated:
        return None
    if source_id in {"eeas_releases", "ofac_recent_actions"}:
        next_anchor = _html_soup(response).select_one(
            "a[rel='next'], a.pager__link--next"
        )
        if next_anchor is not None and next_anchor.get("href"):
            return "WINDOW_LOWER_BOUND_REACHED"
        return "PAGINATION_EXHAUSTED"
    if source_id in {"eurlex_official_journal", "gdelt_event_gkg"}:
        return "QUERY_WINDOW_COMPLETE"
    if source_id in {
        "bis_federal_register",
        "ukmto_advisories",
        "un_sc_sanctions",
        "ustr_actions",
    }:
        return "COMPLETE_SNAPSHOT_RESPONSE"
    if source_id in {"eu_council_sanctions", "marad_msci", "un_conflict_releases"}:
        return "COMPLETE_FEED_RESPONSE"
    return "PAGINATION_EXHAUSTED"


def _validate_terminal_proof(page: GeopoliticalParsedPage) -> None:
    proof_kind = page.terminal_proof_kind
    if proof_kind is not None and proof_kind not in TERMINAL_PROOF_KINDS:
        raise DataVendorUnavailable(
            "geopolitical parser returned an invalid terminal proof kind"
        )
    if page.terminal_marker_observed != (proof_kind is not None):
        raise DataVendorUnavailable(
            "geopolitical parser terminal marker lacks a typed proof"
        )


def _event_type_for_title(title: str) -> str | None:
    lowered = title.casefold()
    if any(
        token in lowered
        for token in (
            "de-escalation",
            "deescalation",
            "détente",
            "局势缓和",
            "恢复外交关系",
        )
    ):
        return "DIPLOMATIC_DEESCALATION"
    if any(
        token in lowered
        for token in (
            "sanction",
            "designat",
            "restrictive measure",
            "asset freeze",
            "embargo",
            "制裁",
            "反制措施",
        )
    ):
        return "SANCTION"
    if any(
        token in lowered
        for token in (
            "export control",
            "entity list",
            "dual-use",
            "dual use",
            "出口管制",
            "管制清单",
            "两用物项",
        )
    ):
        return "EXPORT_CONTROL"
    if any(
        token in lowered
        for token in (
            "tariff",
            "trade restriction",
            "section 301",
            "关税",
            "贸易限制",
        )
    ):
        return "TARIFF_TRADE_RESTRICTION"
    if any(
        token in lowered
        for token in (
            "shipping",
            "maritime",
            "vessel",
            "red sea",
            "航运",
            "海事",
            "船舶",
            "红海",
        )
    ):
        return "SHIPPING_DISRUPTION"
    if any(
        token in lowered
        for token in (
            "armed conflict",
            "hostilities",
            "attack",
            " war ",
            "武装冲突",
            "敌对行动",
            "袭击",
            "战争",
        )
    ):
        return "ARMED_CONFLICT"
    if any(
        token in lowered
        for token in (
            "diplomatic escalation",
            "diplomatic tension",
            "expel",
            "外交升级",
            "外交紧张",
            "驱逐外交官",
        )
    ):
        return "DIPLOMATIC_ESCALATION"
    return None


def _actors_for_title(source_id: str, title: str) -> tuple[str, ...]:
    lowered = title.casefold()
    aliases = {
        "CN": ("china", "chinese", "中国", "中方"),
        "US": ("united states", "u.s.", "american", "美国", "美方"),
        "EU": ("european union", " eu ", "欧盟"),
        "RU": ("russia", "russian", "俄罗斯", "俄方"),
        "UA": ("ukraine", "ukrainian", "乌克兰"),
        "IR": ("iran", "iranian", "伊朗"),
        "IL": ("israel", "israeli", "以色列"),
        "KP": ("north korea", "dprk", "朝鲜"),
        "KR": ("south korea", "republic of korea", "韩国"),
    }
    actors = {
        actor
        for actor, tokens in aliases.items()
        if any(token.strip() in lowered for token in tokens)
    }
    default = _DEFAULT_ACTOR_BY_SOURCE.get(source_id)
    if default:
        actors.add(default)
    return tuple(sorted(actors or {"GLOBAL"}))


def _regions_for_title(title: str) -> tuple[str, ...]:
    lowered = title.casefold()
    regions = {
        region
        for region, tokens in {
            "TAIWAN_STRAIT": ("taiwan strait", "taiwan", "台海", "台湾"),
            "SOUTH_CHINA_SEA": ("south china sea", "南海"),
            "RED_SEA_BAB_EL_MANDEB": (
                "red sea",
                "bab el-mandeb",
                "红海",
                "曼德海峡",
            ),
            "STRAIT_OF_HORMUZ": (
                "strait of hormuz",
                "hormuz",
                "霍尔木兹",
            ),
            "BLACK_SEA": ("black sea", "黑海"),
            "KOREAN_PENINSULA": (
                "korean peninsula",
                "north korea",
                "south korea",
                "朝鲜半岛",
            ),
        }.items()
        if any(token in lowered for token in tokens)
    }
    return tuple(sorted(regions))


def _records_to_publications(
    source_id: str,
    records: list[dict[str, str]],
    *,
    allowed_event_types: set[str],
) -> tuple[GeopoliticalParsedPublication, ...]:
    publications: list[GeopoliticalParsedPublication] = []
    for record in records:
        event_type = record.get("event_type") or _event_type_for_title(
            record["title"]
        )
        if event_type is None or event_type not in allowed_event_types:
            continue
        published_at = _parse_source_timestamp(record["published_at"])
        normalized_title = _normalized_space(record["title"]).casefold()
        actors = _actors_for_title(source_id, record["title"])
        regions = _regions_for_title(record["title"])
        lifecycle = (
            "DEESCALATED"
            if event_type == "DIPLOMATIC_DEESCALATION"
            else "ESCALATED"
            if event_type in {"ARMED_CONFLICT", "DIPLOMATIC_ESCALATION"}
            else "ANNOUNCED"
        )
        normalized_content_hash = _canonical_hash(
            {
                "event_type": event_type,
                "title": normalized_title,
                "actors": actors,
                "regions": regions,
                "published_at": published_at,
            }
        )
        content_hash = _canonical_hash(
            {
                "source_id": source_id,
                "source_record_id": record["source_record_id"],
                "content_signature": record["content_signature"],
            }
        )
        publications.append(
            GeopoliticalParsedPublication(
                source_record_id=record["source_record_id"],
                event_type=event_type,
                lifecycle_status=lifecycle,
                actors=actors,
                affected_regions=regions,
                affected_channels=_EVENT_CHANNELS[event_type],
                published_at=published_at,
                effective_at=None,
                causal_dedupe_key=f"{source_id}:{record['source_record_id']}",
                normalized_content_hash=normalized_content_hash,
                content_hash=content_hash,
            )
        )
    return tuple(publications)


def parse_registered_geopolitical_page(
    source_id: str,
    response: GeopoliticalTransportResponse,
    *,
    manifest: Mapping[str, object] | None = None,
) -> GeopoliticalParsedPage:
    resolved = manifest or load_geopolitical_manifest()
    sources = _manifest_sources(resolved)
    if source_id not in BUILTIN_SOURCE_PARSER_CONTRACTS or source_id not in sources:
        raise DataVendorUnavailable(
            f"geopolitical source-specific parser is not implemented: {source_id}"
        )
    _, adapter, _ = sources[source_id]
    _validate_broad_response(
        source_id=source_id,
        retrieval_mode=str(adapter["retrieval_mode"]),
        content_type=response.content_type,
        body=response.body,
    )
    contract = BUILTIN_SOURCE_PARSER_CONTRACTS[source_id]
    records, next_url, terminal, truncated = _source_records(
        source_id, response, contract
    )
    retrieved_at = _parse_utc(response.retrieved_at, "retrieved_at")
    for record in records:
        published_at = _parse_source_timestamp(record["published_at"])
        if _parse_utc(published_at, "published_at") > retrieved_at:
            raise DataVendorUnavailable(
                "geopolitical publication time is later than retrieval time"
            )
        record["published_at"] = published_at
    publications = _records_to_publications(
        source_id,
        records,
        allowed_event_types=set(str(value) for value in adapter["covered_event_types"]),
    )
    return GeopoliticalParsedPage(
        publications=publications,
        next_url=next_url,
        terminal_marker_observed=terminal,
        truncated=truncated,
        terminal_proof_kind=_terminal_proof_kind(
            source_id,
            response,
            terminal=terminal,
            truncated=truncated,
        ),
    )


def _publication_matches_route(
    publication: GeopoliticalParsedPublication, route: Mapping[str, object]
) -> bool:
    if publication.event_type != route["event_type"]:
        return False
    if route["subject_type"] == "GLOBAL":
        return True
    if route["subject_type"] == "ACTOR":
        return route["actor_id"] in publication.actors
    return route["region_id"] in publication.affected_regions


def _registered_route_parser(source_id: str) -> PageParser:
    def parse(
        response: GeopoliticalTransportResponse, route: Mapping[str, object]
    ) -> GeopoliticalParsedPage:
        page = parse_registered_geopolitical_page(source_id, response)
        return GeopoliticalParsedPage(
            publications=tuple(
                publication
                for publication in page.publications
                if _publication_matches_route(publication, route)
            ),
            next_url=page.next_url,
            terminal_marker_observed=page.terminal_marker_observed,
            truncated=page.truncated,
            terminal_proof_kind=page.terminal_proof_kind,
        )

    return parse


_BUILTIN_PAGE_PARSERS.update(
    {
        source_id: _registered_route_parser(source_id)
        for source_id in BUILTIN_SOURCE_PARSER_CONTRACTS
    }
)
if set(_BUILTIN_PAGE_PARSERS) != set(BUILTIN_GEOPOLITICAL_PARSER_SOURCE_IDS):
    raise RuntimeError("geopolitical built-in parser registry drift")


def probe_geopolitical_source_transport(
    source_id: str,
    *,
    fetch: Fetch = _live_fetch,
    manifest: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Fetch one registered root and return metadata without source content."""
    resolved_manifest = manifest or load_geopolitical_manifest()
    sources = _manifest_sources(resolved_manifest)
    if source_id not in sources:
        raise DataVendorUnavailable(f"unregistered geopolitical source: {source_id}")
    registration, adapter, registered_domain = sources[source_id]
    canonical_url = str(adapter["canonical_url_or_api"])
    initial_host = urllib.parse.urlparse(canonical_url).hostname
    domains = tuple(
        sorted(
            {
                registered_domain.casefold(),
                str(initial_host).casefold(),
            }
        )
    )
    request_url = _request_url(source_id, canonical_url)
    started = time.monotonic()
    response = fetch(request_url, domains)
    schema_signal = _validate_broad_response(
        source_id=source_id,
        retrieval_mode=str(adapter["retrieval_mode"]),
        content_type=response.content_type,
        body=response.body,
    )
    return {
        "adapter_version": GEOPOLITICAL_TRANSPORT_ADAPTER_VERSION,
        "source_id": source_id,
        "provider_kind": registration["provider_kind"],
        "required": registration["required"],
        "request_url": response.request_url,
        "final_url": response.final_url,
        "content_type": response.content_type,
        "retrieved_at": response.retrieved_at,
        "payload_hash": _sha256_bytes(response.body),
        "payload_size_bytes": len(response.body),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "broad_schema_signal": schema_signal,
        "transport_status": "ACTIVE",
        "production_readiness": "PREFLIGHT_ONLY",
        "raw_source_content_committed": False,
    }


def _validate_publication(
    publication: GeopoliticalParsedPublication,
    *,
    route: Mapping[str, object],
    retrieved_at: datetime,
) -> None:
    for field, value in (
        ("source_record_id", publication.source_record_id),
        ("causal_dedupe_key", publication.causal_dedupe_key),
    ):
        if not isinstance(value, str) or not value.strip():
            raise DataVendorUnavailable(f"geopolitical {field} is required")
    if publication.event_type != route["event_type"]:
        raise DataVendorUnavailable(
            "geopolitical parsed event type is outside the polled route"
        )
    if not publication.actors or not publication.affected_channels:
        raise DataVendorUnavailable(
            "geopolitical parsed publication lacks actors or affected channels"
        )
    if any(not isinstance(value, str) or not value for value in publication.actors):
        raise DataVendorUnavailable("geopolitical parsed actors are invalid")
    if any(
        not isinstance(value, str) or not value
        for value in publication.affected_regions
    ):
        raise DataVendorUnavailable("geopolitical parsed regions are invalid")
    if any(
        not isinstance(value, str) or not value
        for value in publication.affected_channels
    ):
        raise DataVendorUnavailable("geopolitical parsed channels are invalid")
    if route["subject_type"] == "ACTOR" and route["actor_id"] not in publication.actors:
        raise DataVendorUnavailable(
            "geopolitical parsed publication does not match the actor route"
        )
    if (
        route["subject_type"] == "REGION"
        and route["region_id"] not in publication.affected_regions
    ):
        raise DataVendorUnavailable(
            "geopolitical parsed publication does not match the region route"
        )
    published_at = _parse_utc(publication.published_at, "published_at")
    if published_at > retrieved_at:
        raise DataVendorUnavailable(
            "geopolitical publication time is later than retrieval time"
        )
    if publication.effective_at is not None:
        _parse_utc(publication.effective_at, "effective_at")
    _require_sha256(publication.normalized_content_hash, "normalized_content_hash")
    _require_sha256(publication.content_hash, "content_hash")


def _verification_status(
    evidence_catalog: list[dict[str, object]],
    registrations: Mapping[str, Mapping[str, object]],
) -> tuple[str, str]:
    provider_kinds = [
        str(registrations[str(row["source_id"])]["provider_kind"])
        for row in evidence_catalog
    ]
    if "OFFICIAL_PRIMARY" in provider_kinds:
        return "OFFICIAL_CONFIRMED", "OFFICIAL_PRIMARY"
    independent = {
        (
            registrations[str(row["source_id"])]["publisher_organization_id"],
            registrations[str(row["source_id"])]["upstream_origin_family"],
        )
        for row in evidence_catalog
        if registrations[str(row["source_id"])]["provider_kind"]
        != "OPTIONAL_CONTEXT"
    }
    if len(independent) >= 2:
        return "MULTISOURCE_CONFIRMED", "STRUCTURED_DISCOVERY"
    if provider_kinds and set(provider_kinds) == {"STRUCTURED_DISCOVERY"}:
        return "UNCONFIRMED", "STRUCTURED_DISCOVERY"
    raise DataVendorUnavailable(
        "optional geopolitical context cannot create a standalone event"
    )


def _normalize_publication_time(
    publication: GeopoliticalParsedPublication,
) -> GeopoliticalParsedPublication:
    published = _parse_utc(publication.published_at, "published_at").isoformat()
    effective = (
        _parse_utc(publication.effective_at, "effective_at").isoformat()
        if publication.effective_at is not None
        else None
    )
    return GeopoliticalParsedPublication(
        source_record_id=publication.source_record_id,
        event_type=publication.event_type,
        lifecycle_status=publication.lifecycle_status,
        actors=publication.actors,
        affected_regions=publication.affected_regions,
        affected_channels=publication.affected_channels,
        published_at=published,
        effective_at=effective,
        causal_dedupe_key=publication.causal_dedupe_key,
        normalized_content_hash=publication.normalized_content_hash,
        content_hash=publication.content_hash,
    )


def _build_event_revisions(
    *,
    source_id: str,
    publications: list[tuple[GeopoliticalParsedPublication, datetime]],
    completed: datetime,
    ledger: GeopoliticalEventStore,
    manifest: Mapping[str, object],
) -> list[dict[str, Any]]:
    registrations = {
        str(row["source_id"]): row
        for row in manifest["registrations"]  # type: ignore[index]
        if isinstance(row, Mapping)
    }
    existing = ledger.events_as_of(completed)
    latest_by_event_id: dict[str, dict[str, Any]] = {}
    seen_evidence_hashes: set[str] = set()
    normalized_hash_owner: dict[str, str] = {}
    for row in existing:
        event_id = str(row["geopolitical_event_id"])
        current = latest_by_event_id.get(event_id)
        if current is None or row["retrieved_at"] > current["retrieved_at"]:
            latest_by_event_id[event_id] = row
        normalized_hash_owner[str(row["normalized_content_hash"])] = event_id
        for evidence in row.get("_evidence_catalog", ()):
            seen_evidence_hashes.add(str(evidence["content_hash"]))

    grouped: dict[str, list[tuple[GeopoliticalParsedPublication, datetime]]] = {}
    for publication, retrieved_at in publications:
        if publication.content_hash in seen_evidence_hashes:
            continue
        proposed_event_id = (
            "geo-event:"
            + _canonical_hash(publication.causal_dedupe_key).removeprefix("sha256:")
        )
        event_id = normalized_hash_owner.get(
            publication.normalized_content_hash, proposed_event_id
        )
        grouped.setdefault(event_id, []).append((publication, retrieved_at))
        seen_evidence_hashes.add(publication.content_hash)
        normalized_hash_owner[publication.normalized_content_hash] = event_id

    revisions: list[dict[str, Any]] = []
    for event_id, candidates in sorted(grouped.items()):
        candidates.sort(key=lambda item: (item[0].published_at, item[0].source_record_id))
        latest_publication, latest_retrieved = candidates[-1]
        previous = latest_by_event_id.get(event_id)
        catalog = (
            [dict(row) for row in previous.get("_evidence_catalog", ())]
            if previous
            else []
        )
        existing_evidence_ids = {str(row["evidence_id"]) for row in catalog}
        for publication, _ in candidates:
            evidence_id = (
                "geo-evidence:"
                + _canonical_hash(
                    {
                        "source_id": source_id,
                        "source_record_id": publication.source_record_id,
                        "content_hash": publication.content_hash,
                    }
                ).removeprefix("sha256:")
            )
            if evidence_id in existing_evidence_ids:
                continue
            catalog.append(
                {
                    "evidence_id": evidence_id,
                    "source_id": source_id,
                    "published_at": publication.published_at,
                    "content_hash": publication.content_hash,
                }
            )
            existing_evidence_ids.add(evidence_id)
        verification_status, primary_source_tier = _verification_status(
            catalog, registrations
        )
        published_at = min(
            (str(row["published_at"]) for row in catalog),
            key=lambda value: _parse_utc(value, "evidence published_at"),
        )
        evidence_bundle_id = "geo-evidence-bundle:" + _canonical_hash(
            catalog
        ).removeprefix("sha256:")
        core = {
            "geopolitical_event_id": event_id,
            "supersedes_revision_id": (
                previous["event_revision_id"] if previous else None
            ),
            "event_type": latest_publication.event_type,
            "lifecycle_status": latest_publication.lifecycle_status,
            "verification_status": verification_status,
            "actors": sorted(set(latest_publication.actors)),
            "affected_regions": sorted(set(latest_publication.affected_regions)),
            "affected_channels": sorted(set(latest_publication.affected_channels)),
            "published_at": published_at,
            "effective_at": latest_publication.effective_at,
            "first_seen_at": (
                previous["first_seen_at"] if previous else latest_retrieved.isoformat()
            ),
            "retrieved_at": completed.isoformat(),
            "time_status": "VERIFIED",
            "primary_source_tier": primary_source_tier,
            "source_evidence_ids": [str(row["evidence_id"]) for row in catalog],
            "evidence_bundle_id": evidence_bundle_id,
            "causal_dedupe_key": latest_publication.causal_dedupe_key,
            "normalized_content_hash": latest_publication.normalized_content_hash,
            "evidence_catalog": catalog,
        }
        revision = {
            **core,
            "event_revision_id": (
                event_id + ":" + _canonical_hash(core).removeprefix("sha256:")
            ),
        }
        validate_event_revision(revision, manifest=manifest)
        revisions.append(revision)
    return revisions


def _source_capture_row(
    *,
    source_id: str,
    adapter: Mapping[str, object],
    started: datetime,
    completed: datetime,
    ingestion_mode: str,
    page_archive_ids: list[str],
    response_content_hash: str,
    publication_count: int,
    route_poll_count: int,
    pagination_complete: bool,
    terminal_proof_kind: str | None,
    truncated: bool,
    success: bool,
    error_class: str | None,
) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": "geopolitical_source_capture_v1",
        "source_id": source_id,
        "adapter_contract_hash": adapter["adapter_contract_hash"],
        "poll_started_at": started.isoformat(),
        "poll_completed_at": completed.isoformat(),
        "ingestion_mode": ingestion_mode,
        "page_archive_ids": page_archive_ids,
        "response_content_hash": response_content_hash,
        "page_count": len(page_archive_ids),
        "publication_count": publication_count,
        "route_poll_count": route_poll_count,
        "pagination_complete": pagination_complete,
        "terminal_proof_kind": terminal_proof_kind,
        "truncated": truncated,
        "schema_verified": success,
        "publication_time_verified": success,
        "parse_result": "SUCCESS" if success else "FAILED",
        "error_class": error_class,
    }
    capture_hash = _canonical_hash(core)
    return {
        **core,
        "source_capture_id": (
            "geo-source-capture:" + capture_hash.removeprefix("sha256:")
        ),
        "capture_hash": capture_hash,
    }


def capture_geopolitical_source(
    source_id: str,
    *,
    fetch: Fetch | None = None,
    store: GeopoliticalEventStore | None = None,
    manifest: Mapping[str, object] | None = None,
    poll_started_at: str | None = None,
    nonproduction_transport_override: bool = False,
) -> dict[str, object]:
    """Capture one source once and project it into every registered route."""
    resolved_manifest = manifest or load_geopolitical_manifest()
    sources = _manifest_sources(resolved_manifest)
    if source_id not in BUILTIN_SOURCE_PARSER_CONTRACTS or source_id not in sources:
        raise DataVendorUnavailable(
            f"geopolitical source-specific parser is not implemented: {source_id}"
        )
    registration, adapter, registered_domain = sources[source_id]
    if nonproduction_transport_override:
        if fetch is None:
            raise DataVendorUnavailable(
                "geopolitical non-production transport override requires fetch"
            )
        transport = fetch
        started = _parse_utc(
            poll_started_at or _utc_now().isoformat(), "poll_started_at"
        )
        ingestion_mode = "NON_PRODUCTION_CALLBACK"
    else:
        if fetch is not None or poll_started_at is not None:
            raise DataVendorUnavailable(
                "geopolitical trusted runtime owns transport and clock"
            )
        transport = _live_fetch
        started = _utc_now().astimezone(timezone.utc)
        ingestion_mode = "TRUSTED_REGISTERED_PARSER"

    canonical_url = str(adapter["canonical_url_or_api"])
    initial_host = urllib.parse.urlparse(canonical_url).hostname
    domains = tuple(
        sorted({registered_domain.casefold(), str(initial_host).casefold()})
    )
    routes = sorted(
        (
            row
            for row in resolved_manifest["coverage_routes"]  # type: ignore[index]
            if isinstance(row, Mapping)
            and row.get("applicability") == "APPLICABLE"
            and source_id in row.get("required_source_ids", ())
        ),
        key=lambda row: str(row["coverage_route_id"]),
    )
    ledger = store or GeopoliticalEventStore(geopolitical_store_path())
    current_url: str | None = _request_url(
        source_id, canonical_url, window_end=started
    )
    visited_urls: set[str] = set()
    page_rows_without_capture: list[dict[str, object]] = []
    page_hashes: list[str] = []
    publications: list[tuple[GeopoliticalParsedPublication, datetime]] = []
    completed = started
    terminal = False
    terminal_proof_kind: str | None = None
    truncated = False
    failure: DataVendorUnavailable | None = None

    try:
        for page_ordinal in range(_MAX_PAGES):
            if current_url is None:
                break
            parsed_url = urllib.parse.urlparse(current_url)
            if (
                parsed_url.scheme != "https"
                or not _host_allowed(parsed_url.hostname, domains)
                or current_url in visited_urls
            ):
                raise DataVendorUnavailable(
                    "geopolitical pagination left the registered source or cycled"
                )
            visited_urls.add(current_url)
            response = transport(current_url, domains)
            final_host = urllib.parse.urlparse(response.final_url).hostname
            if not _host_allowed(final_host, domains):
                raise DataVendorUnavailable(
                    "geopolitical page redirected outside its registered domain"
                )
            retrieved_at = _parse_utc(response.retrieved_at, "retrieved_at")
            if retrieved_at < started:
                raise DataVendorUnavailable(
                    "geopolitical page retrieval precedes poll start"
                )
            completed = max(completed, retrieved_at)
            content_hash = _sha256_bytes(response.body)
            page_hashes.append(content_hash)
            page_core: dict[str, object] = {
                "source_id": source_id,
                "page_ordinal": page_ordinal,
                "request_url": response.request_url,
                "final_url": response.final_url,
                "content_type": response.content_type,
                "poll_started_at": started.isoformat(),
                "retrieved_at": retrieved_at.isoformat(),
                "content_hash": content_hash,
            }
            page_rows_without_capture.append(
                {
                    **page_core,
                    "page_archive_id": (
                        "geo-page:"
                        + _canonical_hash(page_core).removeprefix("sha256:")
                    ),
                    "body": response.body,
                }
            )
            page = parse_registered_geopolitical_page(
                source_id, response, manifest=resolved_manifest
            )
            _validate_terminal_proof(page)
            if page.truncated:
                truncated = True
                raise DataVendorUnavailable(
                    "geopolitical source reported truncated pagination"
                )
            if page.next_url is not None and page.terminal_marker_observed:
                raise DataVendorUnavailable(
                    "geopolitical pagination cannot be terminal and continue"
                )
            for publication in page.publications:
                normalized = _normalize_publication_time(publication)
                if normalized.event_type not in adapter["covered_event_types"]:
                    raise DataVendorUnavailable(
                        "geopolitical parsed event type is outside source scope"
                    )
                if not normalized.actors or not normalized.affected_channels:
                    raise DataVendorUnavailable(
                        "geopolitical parsed publication lacks actors or channels"
                    )
                if _parse_utc(normalized.published_at, "published_at") > retrieved_at:
                    raise DataVendorUnavailable(
                        "geopolitical publication time is later than retrieval time"
                    )
                _require_sha256(
                    normalized.normalized_content_hash,
                    "normalized_content_hash",
                )
                _require_sha256(normalized.content_hash, "content_hash")
                publications.append((normalized, retrieved_at))
            terminal = page.terminal_marker_observed
            terminal_proof_kind = page.terminal_proof_kind
            current_url = page.next_url
            if current_url is None:
                break
        else:
            truncated = True
            raise DataVendorUnavailable(
                "geopolitical pagination exceeded the bounded page limit"
            )
        if current_url is not None or not terminal:
            raise DataVendorUnavailable(
                "geopolitical pagination lacks a verified terminal marker"
            )
    except DataVendorUnavailable as exc:
        failure = exc

    success = failure is None
    response_content_hash = _canonical_hash(page_hashes)
    page_ids = [str(row["page_archive_id"]) for row in page_rows_without_capture]
    capture = _source_capture_row(
        source_id=source_id,
        adapter=adapter,
        started=started,
        completed=completed,
        ingestion_mode=ingestion_mode,
        page_archive_ids=page_ids,
        response_content_hash=response_content_hash,
        publication_count=len(publications),
        route_poll_count=len(routes),
        pagination_complete=success,
        terminal_proof_kind=terminal_proof_kind if success else None,
        truncated=truncated,
        success=success,
        error_class=type(failure).__name__ if failure is not None else None,
    )
    page_rows = [
        {
            **row,
            "source_capture_id": capture["source_capture_id"],
        }
        for row in page_rows_without_capture
    ]
    polls: list[dict[str, object]] = []
    for route in routes:
        query_hash = scope_query_hash(route, adapter)
        query_key = coverage_query_key(route, source_id, query_hash)
        matching = [
            publication
            for publication, _ in publications
            if _publication_matches_route(publication, route)
        ]
        poll_core: dict[str, object] = {
            "coverage_route_id": route["coverage_route_id"],
            "coverage_route_hash": route["coverage_route_hash"],
            "source_id": source_id,
            "scope_query_hash": query_hash,
            "coverage_query_key": query_key,
            "poll_started_at": started.isoformat(),
            "poll_completed_at": completed.isoformat(),
            "http_status": 200 if page_hashes else 0,
            "row_count": len(matching),
            "pagination_complete": success,
            "terminal_proof_kind": terminal_proof_kind if success else None,
            "truncated": truncated,
            "schema_hash": adapter["expected_response_schema_hash"],
            "response_content_hash": response_content_hash,
            "ingestion_mode": ingestion_mode,
            "parse_result": "SUCCESS" if success else "FAILED",
            "error_class": type(failure).__name__ if failure is not None else None,
            "coverage_evidence_id": (
                ("geo-coverage:" if success else "geo-coverage-failed:")
                + _canonical_hash(
                    {
                        "source_capture_id": capture["source_capture_id"],
                        "coverage_query_key": query_key,
                    }
                ).removeprefix("sha256:")
            ),
        }
        polls.append(
            {
                "observation_id": (
                    "geo-poll:" + _canonical_hash(poll_core).removeprefix("sha256:")
                ),
                **poll_core,
            }
        )
    revisions = (
        _build_event_revisions(
            source_id=source_id,
            publications=publications,
            completed=completed,
            ledger=ledger,
            manifest=resolved_manifest,
        )
        if success
        else []
    )
    ledger.append_source_capture_bundle(
        capture,
        pages=page_rows,
        polls=polls,
        event_revisions=revisions,
        manifest=resolved_manifest,
    )
    if failure is not None:
        failure.source_capture_id = capture["source_capture_id"]
        raise failure
    return {
        "ingestion_version": GEOPOLITICAL_INGESTION_VERSION,
        "parser_version": GEOPOLITICAL_SOURCE_PARSER_VERSION,
        "source_id": source_id,
        "source_capture_id": capture["source_capture_id"],
        "page_count": len(page_rows),
        "parsed_publication_count": len(publications),
        "event_revision_count": len(revisions),
        "route_poll_count": len(polls),
        "response_content_hash": response_content_hash,
        "pagination_complete": True,
        "terminal_proof_kind": terminal_proof_kind,
        "production_eligible": (
            ingestion_mode == "TRUSTED_REGISTERED_PARSER"
            and registration.get("registration_status") == "ACTIVE_VERIFIED"
        ),
        "raw_source_content_committed": False,
    }


def capture_required_geopolitical_sources(
    *,
    store: GeopoliticalEventStore | None = None,
    manifest: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Attempt every required source once without substitution or early abort."""
    resolved_manifest = manifest or load_geopolitical_manifest()
    ledger = store or GeopoliticalEventStore(geopolitical_store_path())
    results: list[dict[str, object]] = []
    for source_id in sorted(REQUIRED_SOURCE_IDS):
        try:
            captured = capture_geopolitical_source(
                source_id,
                store=ledger,
                manifest=resolved_manifest,
            )
            results.append(
                {
                    "source_id": source_id,
                    "status": "SUCCESS",
                    "source_capture_id": captured["source_capture_id"],
                    "error_class": None,
                }
            )
        except DataVendorUnavailable as exc:
            source_capture_id = getattr(exc, "source_capture_id", None)
            if not isinstance(source_capture_id, str):
                raise DataVendorUnavailable(
                    "required geopolitical source failure lacks exact archive identity"
                ) from exc
            failed = validate_source_capture_observation(
                ledger.source_capture(source_capture_id),
                manifest=resolved_manifest,
            )
            if (
                failed["source_id"] != source_id
                or failed["parse_result"] != "FAILED"
                or failed["source_capture_id"] != source_capture_id
            ):
                raise DataVendorUnavailable(
                    "required geopolitical source failure archive binding mismatch"
                ) from exc
            results.append(
                {
                    "source_id": source_id,
                    "status": "FAILED",
                    "source_capture_id": failed["source_capture_id"],
                    "error_class": failed["error_class"],
                }
            )
    successful = [
        str(row["source_id"]) for row in results if row["status"] == "SUCCESS"
    ]
    failed = [
        str(row["source_id"]) for row in results if row["status"] == "FAILED"
    ]
    core: dict[str, object] = {
        "schema_version": "geopolitical_required_source_capture_group_v1",
        "required_source_ids": sorted(REQUIRED_SOURCE_IDS),
        "source_results": results,
        "successful_source_ids": successful,
        "failed_source_ids": failed,
        "all_sources_attempted": len(results) == len(REQUIRED_SOURCE_IDS),
        "all_source_captures_succeeded": not failed,
        "substitution_used": False,
        "raw_source_content_committed": False,
    }
    return {**core, "capture_group_hash": _canonical_hash(core)}


def ingest_geopolitical_route(
    coverage_route_id: str,
    source_id: str,
    *,
    parse_page: PageParser | None = None,
    fetch: Fetch = _live_fetch,
    store: GeopoliticalEventStore | None = None,
    manifest: Mapping[str, object] | None = None,
    poll_started_at: str | None = None,
    nonproduction_parser_override: bool = False,
) -> dict[str, object]:
    """Fetch a complete registered route and append its prose-free audit chain.

    A caller-supplied ``parse_page`` is accepted only behind the explicit
    non-production override and its poll rows are permanently ineligible for
    formal coverage.  Production requires a built-in source parser plus a
    verified continuous-preflight receipt.
    """
    resolved_manifest = manifest or load_geopolitical_manifest()
    sources = _manifest_sources(resolved_manifest)
    if source_id not in sources:
        raise DataVendorUnavailable(f"unregistered geopolitical source: {source_id}")
    registration, adapter, registered_domain = sources[source_id]
    builtin_parser = _BUILTIN_PAGE_PARSERS.get(source_id)
    if nonproduction_parser_override:
        if parse_page is None:
            raise DataVendorUnavailable(
                "geopolitical non-production parser override requires a callback"
            )
        parser = parse_page
        ingestion_mode = "NON_PRODUCTION_CALLBACK"
    else:
        if parse_page is not None and parse_page is not builtin_parser:
            raise DataVendorUnavailable(
                "caller-supplied geopolitical parser is non-production only"
            )
        if fetch is not _live_fetch or poll_started_at is not None:
            raise DataVendorUnavailable(
                "geopolitical trusted runtime owns transport and clock"
            )
        if builtin_parser is None:
            raise DataVendorUnavailable(
                f"geopolitical source-specific parser is not implemented: {source_id}"
            )
        if (
            registration.get("registration_status") != "ACTIVE_VERIFIED"
            or source_id
            not in VERIFIED_GEOPOLITICAL_PREFLIGHT_RECEIPT_SOURCE_IDS
        ):
            raise DataVendorUnavailable(
                f"geopolitical source lacks verified continuous preflight: {source_id}"
            )
        parser = builtin_parser
        ingestion_mode = "PRODUCTION_REGISTERED_PARSER"
    routes = {
        str(row["coverage_route_id"]): row
        for row in resolved_manifest["coverage_routes"]  # type: ignore[index]
        if isinstance(row, Mapping)
    }
    route = routes.get(coverage_route_id)
    if (
        route is None
        or route.get("applicability") != "APPLICABLE"
        or source_id not in route.get("required_source_ids", ())
    ):
        raise DataVendorUnavailable(
            "geopolitical ingestion route/source pair is not registered"
        )

    canonical_url = str(adapter["canonical_url_or_api"])
    initial_host = urllib.parse.urlparse(canonical_url).hostname
    domains = tuple(
        sorted({registered_domain.casefold(), str(initial_host).casefold()})
    )
    started = _parse_utc(
        poll_started_at or datetime.now(timezone.utc).isoformat(),
        "poll_started_at",
    )
    ledger = store or GeopoliticalEventStore(geopolitical_store_path())
    query_hash = scope_query_hash(route, adapter)
    query_key = coverage_query_key(route, source_id, query_hash)
    current_url: str | None = _request_url(
        source_id, canonical_url, window_end=started
    )
    visited_urls: set[str] = set()
    page_hashes: list[str] = []
    publications: list[tuple[GeopoliticalParsedPublication, datetime]] = []
    completed = started
    terminal_marker_observed = False
    terminal_proof_kind: str | None = None
    truncated = False

    try:
        for _ in range(_MAX_PAGES):
            if current_url is None:
                break
            parsed_url = urllib.parse.urlparse(current_url)
            if (
                parsed_url.scheme != "https"
                or not _host_allowed(parsed_url.hostname, domains)
                or current_url in visited_urls
            ):
                raise DataVendorUnavailable(
                    "geopolitical pagination left the registered source or cycled"
                )
            visited_urls.add(current_url)
            response = fetch(current_url, domains)
            final_host = urllib.parse.urlparse(response.final_url).hostname
            if not _host_allowed(final_host, domains):
                raise DataVendorUnavailable(
                    "geopolitical page redirected outside its registered domain"
                )
            _validate_broad_response(
                source_id=source_id,
                retrieval_mode=str(adapter["retrieval_mode"]),
                content_type=response.content_type,
                body=response.body,
            )
            retrieved_at = _parse_utc(response.retrieved_at, "retrieved_at")
            if retrieved_at < started:
                raise DataVendorUnavailable(
                    "geopolitical page retrieval precedes poll start"
                )
            completed = max(completed, retrieved_at)
            page_hashes.append(_sha256_bytes(response.body))
            try:
                parsed_page = parser(response, route)
            except DataVendorUnavailable:
                raise
            except Exception as exc:
                raise DataVendorUnavailable(
                    f"geopolitical registered parser failed: {type(exc).__name__}"
                ) from exc
            if not isinstance(parsed_page, GeopoliticalParsedPage):
                raise DataVendorUnavailable(
                    "geopolitical registered parser returned an invalid page"
                )
            _validate_terminal_proof(parsed_page)
            if parsed_page.truncated:
                truncated = True
                raise DataVendorUnavailable(
                    "geopolitical source reported truncated pagination"
                )
            if parsed_page.next_url is not None and parsed_page.terminal_marker_observed:
                raise DataVendorUnavailable(
                    "geopolitical pagination cannot be terminal and continue"
                )
            for publication in parsed_page.publications:
                if not isinstance(publication, GeopoliticalParsedPublication):
                    raise DataVendorUnavailable(
                        "geopolitical registered parser returned an invalid publication"
                    )
                normalized = _normalize_publication_time(publication)
                _validate_publication(
                    normalized, route=route, retrieved_at=retrieved_at
                )
                publications.append((normalized, retrieved_at))
            terminal_marker_observed = parsed_page.terminal_marker_observed
            terminal_proof_kind = parsed_page.terminal_proof_kind
            current_url = parsed_page.next_url
            if current_url is None:
                break
        else:
            truncated = True
            raise DataVendorUnavailable(
                "geopolitical pagination exceeded the bounded page limit"
            )
        if current_url is not None or not terminal_marker_observed:
            raise DataVendorUnavailable(
                "geopolitical pagination lacks a verified terminal marker"
            )
    except DataVendorUnavailable as exc:
        # A failed or partial walk is never written as healthy no-event proof.
        response_content_hash = _canonical_hash(page_hashes)
        failure_core: dict[str, object] = {
            "coverage_route_id": coverage_route_id,
            "coverage_route_hash": route["coverage_route_hash"],
            "source_id": source_id,
            "scope_query_hash": query_hash,
            "coverage_query_key": query_key,
            "poll_started_at": started.isoformat(),
            "poll_completed_at": completed.isoformat(),
            "http_status": 200 if page_hashes else 0,
            "row_count": len(publications),
            "pagination_complete": False,
            "terminal_proof_kind": None,
            "truncated": truncated,
            "schema_hash": adapter["expected_response_schema_hash"],
            "response_content_hash": response_content_hash,
            "ingestion_mode": ingestion_mode,
            "parse_result": "FAILED",
            "error_class": type(exc).__name__,
            "coverage_evidence_id": (
                "geo-coverage-failed:"
                + _canonical_hash(
                    {
                        "coverage_query_key": query_key,
                        "poll_completed_at": completed.isoformat(),
                        "response_content_hash": response_content_hash,
                    }
                ).removeprefix("sha256:")
            ),
        }
        failure = {
            "observation_id": (
                "geo-poll:" + _canonical_hash(failure_core).removeprefix("sha256:")
            ),
            **failure_core,
        }
        ledger.append_poll_observation(failure, manifest=resolved_manifest)
        raise

    registrations = {
        str(row["source_id"]): row
        for row in resolved_manifest["registrations"]  # type: ignore[index]
        if isinstance(row, Mapping)
    }
    existing = ledger.events_as_of(completed)
    latest_by_event_id: dict[str, dict[str, Any]] = {}
    seen_evidence_hashes: set[str] = set()
    normalized_hash_owner: dict[str, str] = {}
    for row in existing:
        event_id = str(row["geopolitical_event_id"])
        current = latest_by_event_id.get(event_id)
        if current is None or row["retrieved_at"] > current["retrieved_at"]:
            latest_by_event_id[event_id] = row
        normalized_hash_owner[str(row["normalized_content_hash"])] = event_id
        for evidence in row.get("_evidence_catalog", ()):
            seen_evidence_hashes.add(str(evidence["content_hash"]))

    grouped: dict[str, list[tuple[GeopoliticalParsedPublication, datetime]]] = {}
    for publication, retrieved_at in publications:
        if publication.content_hash in seen_evidence_hashes:
            continue
        event_id = (
            "geo-event:"
            + _canonical_hash(publication.causal_dedupe_key).removeprefix("sha256:")
        )
        owner = normalized_hash_owner.get(publication.normalized_content_hash)
        if owner is not None and owner != event_id:
            continue
        grouped.setdefault(event_id, []).append((publication, retrieved_at))
        seen_evidence_hashes.add(publication.content_hash)
        normalized_hash_owner[publication.normalized_content_hash] = event_id

    revisions: list[dict[str, Any]] = []
    for event_id, candidates in sorted(grouped.items()):
        candidates.sort(key=lambda item: (item[0].published_at, item[0].source_record_id))
        latest_publication, latest_retrieved = candidates[-1]
        previous = latest_by_event_id.get(event_id)
        catalog = [dict(row) for row in previous.get("_evidence_catalog", ())] if previous else []
        existing_evidence_ids = {str(row["evidence_id"]) for row in catalog}
        for publication, _ in candidates:
            evidence_id = (
                "geo-evidence:"
                + _canonical_hash(
                    {
                        "source_id": source_id,
                        "source_record_id": publication.source_record_id,
                        "content_hash": publication.content_hash,
                    }
                ).removeprefix("sha256:")
            )
            if evidence_id in existing_evidence_ids:
                continue
            catalog.append(
                {
                    "evidence_id": evidence_id,
                    "source_id": source_id,
                    "published_at": publication.published_at,
                    "content_hash": publication.content_hash,
                }
            )
            existing_evidence_ids.add(evidence_id)
        verification_status, primary_source_tier = _verification_status(
            catalog, registrations
        )
        published_at = min(str(row["published_at"]) for row in catalog)
        evidence_bundle_id = "geo-evidence-bundle:" + _canonical_hash(
            catalog
        ).removeprefix("sha256:")
        core = {
            "geopolitical_event_id": event_id,
            "supersedes_revision_id": (
                previous["event_revision_id"] if previous else None
            ),
            "event_type": latest_publication.event_type,
            "lifecycle_status": latest_publication.lifecycle_status,
            "verification_status": verification_status,
            "actors": sorted(set(latest_publication.actors)),
            "affected_regions": sorted(set(latest_publication.affected_regions)),
            "affected_channels": sorted(set(latest_publication.affected_channels)),
            "published_at": published_at,
            "effective_at": latest_publication.effective_at,
            "first_seen_at": (
                previous["first_seen_at"] if previous else latest_retrieved.isoformat()
            ),
            "retrieved_at": completed.isoformat(),
            "time_status": "VERIFIED",
            "primary_source_tier": primary_source_tier,
            "source_evidence_ids": [str(row["evidence_id"]) for row in catalog],
            "evidence_bundle_id": evidence_bundle_id,
            "causal_dedupe_key": latest_publication.causal_dedupe_key,
            "normalized_content_hash": latest_publication.normalized_content_hash,
            "evidence_catalog": catalog,
        }
        revision = {
            **core,
            "event_revision_id": (
                event_id
                + ":"
                + _canonical_hash(core).removeprefix("sha256:")
            ),
        }
        validate_event_revision(revision, manifest=resolved_manifest)
        revisions.append(revision)

    for revision in revisions:
        ledger.append_event_revision(revision, manifest=resolved_manifest)

    response_content_hash = _canonical_hash(page_hashes)
    poll_core: dict[str, object] = {
        "coverage_route_id": coverage_route_id,
        "coverage_route_hash": route["coverage_route_hash"],
        "source_id": source_id,
        "scope_query_hash": query_hash,
        "coverage_query_key": query_key,
        "poll_started_at": started.isoformat(),
        "poll_completed_at": completed.isoformat(),
        "http_status": 200,
        "row_count": len(publications),
        "pagination_complete": True,
        "terminal_proof_kind": terminal_proof_kind,
        "truncated": truncated,
        "schema_hash": adapter["expected_response_schema_hash"],
        "response_content_hash": response_content_hash,
        "ingestion_mode": ingestion_mode,
        "parse_result": "SUCCESS",
        "error_class": None,
        "coverage_evidence_id": (
            "geo-coverage:"
            + _canonical_hash(
                {
                    "coverage_query_key": query_key,
                    "poll_completed_at": completed.isoformat(),
                    "response_content_hash": response_content_hash,
                }
            ).removeprefix("sha256:")
        ),
    }
    poll = {
        "observation_id": (
            "geo-poll:" + _canonical_hash(poll_core).removeprefix("sha256:")
        ),
        **poll_core,
    }
    ledger.append_poll_observation(poll, manifest=resolved_manifest)
    return {
        "ingestion_version": GEOPOLITICAL_INGESTION_VERSION,
        "source_id": source_id,
        "coverage_route_id": coverage_route_id,
        "page_count": len(page_hashes),
        "parsed_row_count": len(publications),
        "deduplicated_event_revision_count": len(revisions),
        "poll_observation_id": poll["observation_id"],
        "response_content_hash": response_content_hash,
        "pagination_complete": True,
        "terminal_proof_kind": terminal_proof_kind,
        "production_eligible": ingestion_mode == "PRODUCTION_REGISTERED_PARSER",
        "raw_source_content_committed": False,
    }


__all__ = [
    "BUILTIN_SOURCE_PARSER_CONTRACTS",
    "GEOPOLITICAL_INGESTION_VERSION",
    "GEOPOLITICAL_SOURCE_PARSER_VERSION",
    "GEOPOLITICAL_TRANSPORT_ADAPTER_VERSION",
    "TERMINAL_PROOF_KINDS",
    "GeopoliticalParsedPage",
    "GeopoliticalParsedPublication",
    "GeopoliticalTransportResponse",
    "capture_geopolitical_source",
    "capture_required_geopolitical_sources",
    "ingest_geopolitical_route",
    "parse_registered_geopolitical_page",
    "probe_geopolitical_source_transport",
    "registered_geopolitical_source_ids",
]

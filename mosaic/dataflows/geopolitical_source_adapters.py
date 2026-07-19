"""Bounded transport and private-ledger ingestion for geopolitical sources.

Transport preflight only proves that a registered root is reachable.  Formal
event ingestion additionally requires a registered, source-specific parser to
prove publication time and terminal pagination.  Raw responses stay in memory
or in the operator's private cache; only hashes and normalized event metadata
are appended to the private event ledger.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .exceptions import DataVendorUnavailable
from .geopolitical_events import (
    BUILTIN_GEOPOLITICAL_PARSER_SOURCE_IDS,
    VERIFIED_GEOPOLITICAL_PREFLIGHT_RECEIPT_SOURCE_IDS,
    GeopoliticalEventStore,
    coverage_query_key,
    geopolitical_store_path,
    load_geopolitical_manifest,
    scope_query_hash,
    validate_event_revision,
)

GEOPOLITICAL_TRANSPORT_ADAPTER_VERSION = "geopolitical_transport_adapter_v1"
GEOPOLITICAL_INGESTION_VERSION = "geopolitical_private_ingestion_v1"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_PAGES = 100


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


Fetch = Callable[[str, tuple[str, ...]], GeopoliticalTransportResponse]
PageParser = Callable[
    [GeopoliticalTransportResponse, Mapping[str, object]], GeopoliticalParsedPage
]

# Source-specific production parsers must be registered here.  The empty
# registry is intentional: the current implementation is transport plus a
# non-production callback harness, not a runnable production event collector.
_BUILTIN_PAGE_PARSERS: dict[str, PageParser] = {}
if set(_BUILTIN_PAGE_PARSERS) != set(BUILTIN_GEOPOLITICAL_PARSER_SOURCE_IDS):
    raise RuntimeError("geopolitical built-in parser registry drift")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_hash(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


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
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise DataVendorUnavailable(
                        "geopolitical source response exceeds the preflight bound"
                    )
                return GeopoliticalTransportResponse(
                    request_url=url,
                    final_url=final_url,
                    content_type=response.headers.get_content_type(),
                    body=body,
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                )
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


def _request_url(source_id: str, canonical_url: str) -> str:
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
    if source_id == "gdelt_event_gkg":
        try:
            lines = body.decode("utf-8").strip().splitlines()
        except UnicodeDecodeError as exc:
            raise DataVendorUnavailable("GDELT last-update feed is not UTF-8") from exc
        if len(lines) < 3 or not all(".zip" in line for line in lines[:3]):
            raise DataVendorUnavailable("GDELT last-update feed shape mismatch")
        return "GDELT_LAST_UPDATE_LIST"
    if retrieval_mode == "API":
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataVendorUnavailable(
                "geopolitical API response is not valid JSON"
            ) from exc
        if not isinstance(payload, Mapping):
            raise DataVendorUnavailable("geopolitical API response must be an object")
        return "JSON_OBJECT"
    lowered = body[:4096].lower()
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
    current_url: str | None = _request_url(source_id, canonical_url)
    visited_urls: set[str] = set()
    page_hashes: list[str] = []
    publications: list[tuple[GeopoliticalParsedPublication, datetime]] = []
    completed = started
    terminal_marker_observed = False
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
                _validate_publication(
                    publication, route=route, retrieved_at=retrieved_at
                )
                publications.append((publication, retrieved_at))
            terminal_marker_observed = parsed_page.terminal_marker_observed
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
        "production_eligible": ingestion_mode == "PRODUCTION_REGISTERED_PARSER",
        "raw_source_content_committed": False,
    }


__all__ = [
    "GEOPOLITICAL_INGESTION_VERSION",
    "GEOPOLITICAL_TRANSPORT_ADAPTER_VERSION",
    "GeopoliticalParsedPage",
    "GeopoliticalParsedPublication",
    "GeopoliticalTransportResponse",
    "ingest_geopolitical_route",
    "probe_geopolitical_source_transport",
    "registered_geopolitical_source_ids",
]

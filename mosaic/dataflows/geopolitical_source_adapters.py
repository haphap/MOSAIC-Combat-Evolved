"""Bounded transport preflight for registered geopolitical sources.

This module deliberately does not turn directory pages into event evidence.
It verifies only that a registered root can be fetched with the expected broad
media type. Route-complete polling, publication-time parsing, pagination and
the 30-day health window remain required before a source can become
``ACTIVE_VERIFIED``.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

from .exceptions import DataVendorUnavailable
from .geopolitical_events import load_geopolitical_manifest

GEOPOLITICAL_TRANSPORT_ADAPTER_VERSION = "geopolitical_transport_adapter_v1"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class GeopoliticalTransportResponse:
    request_url: str
    final_url: str
    content_type: str
    body: bytes
    retrieved_at: str


Fetch = Callable[[str, tuple[str, ...]], GeopoliticalTransportResponse]


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


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


__all__ = [
    "GEOPOLITICAL_TRANSPORT_ADAPTER_VERSION",
    "GeopoliticalTransportResponse",
    "probe_geopolitical_source_transport",
    "registered_geopolitical_source_ids",
]

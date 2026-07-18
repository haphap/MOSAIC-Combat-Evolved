"""Fail-closed adapters for public EU and World Bank macro APIs.

The adapters return raw provider observations plus provenance. They do not
invent release timestamps or convert a current response into a historical PIT
observation; that join remains the responsibility of the release/vintage
ledger before data can enter a role snapshot.
"""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .exceptions import DataVendorUnavailable
from .macro_source_contracts import (
    EURO_AREA_FINANCIAL_SERIES_MAP,
    EU_SERIES_MAP,
    WORLD_BANK_CONTEXT_MAP,
)

EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
WORLD_BANK_BASE = "https://api.worldbank.org/v2"
OFFICIAL_MACRO_ADAPTER_VERSION = "official_macro_adapters_v1"
_ALLOWED_HOSTS = {
    "ec.europa.eu",
    "data-api.ecb.europa.eu",
    "api.worldbank.org",
}
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024

WORLD_BANK_EU_CONTEXT_SERIES: dict[str, dict[str, str]] = {
    "eu_gdp_growth_context": {
        "country": "EUU",
        "indicator": "NY.GDP.MKTP.KD.ZG",
        "source": "2",
    },
    "eu_cpi_context": {
        "country": "EUU",
        "indicator": "FP.CPI.TOTL.ZG",
        "source": "2",
    },
    "eu_unemployment_context": {
        "country": "EUU",
        "indicator": "SL.UEM.TOTL.ZS",
        "source": "2",
    },
}


@dataclass(frozen=True)
class OfficialApiResponse:
    url: str
    content_type: str
    body: bytes
    retrieved_at: str


Fetch = Callable[[str], OfficialApiResponse]


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _live_fetch(url: str) -> OfficialApiResponse:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise DataVendorUnavailable("official macro adapter URL is not allowlisted")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MOSAIC-RKE-official-macro-adapter/1"},
        method="GET",
    )
    last_error: OSError | TimeoutError | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                final_url = response.geturl()
                final_host = urllib.parse.urlparse(final_url).hostname
                if final_host not in _ALLOWED_HOSTS:
                    raise DataVendorUnavailable(
                        "official macro adapter redirected off allowlist"
                    )
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise DataVendorUnavailable("official macro adapter response is too large")
                return OfficialApiResponse(
                    url=final_url,
                    content_type=response.headers.get_content_type(),
                    body=body,
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                )
        except (OSError, TimeoutError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.5)
    raise DataVendorUnavailable(f"official macro API request failed: {last_error}")


def _require_live_as_of(response: OfficialApiResponse, as_of: str) -> None:
    try:
        cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        retrieved = datetime.fromisoformat(response.retrieved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataVendorUnavailable("official macro timestamps must be ISO-8601") from exc
    if cutoff.tzinfo is None or retrieved.tzinfo is None:
        raise DataVendorUnavailable("official macro timestamps must include timezone")
    if retrieved > cutoff:
        raise DataVendorUnavailable(
            "live official API response cannot satisfy a historical as_of; use an archived vintage"
        )


def build_eurostat_url(series_key: str, *, last_periods: int = 8) -> str:
    contract = EU_SERIES_MAP.get(series_key)
    if contract is None:
        raise DataVendorUnavailable(f"unregistered Eurostat series: {series_key}")
    if last_periods < 1 or last_periods > 40:
        raise DataVendorUnavailable("Eurostat last_periods must be in 1..40")
    filters = {}
    for item in contract["dimensions"].split(","):
        key, separator, value = item.partition("=")
        if not separator or not key or not value:
            raise DataVendorUnavailable(f"invalid Eurostat dimension binding: {item}")
        filters[key] = value
    query = urllib.parse.urlencode(
        {
            "format": "JSON",
            "lang": "EN",
            "lastTimePeriod": str(last_periods),
            **filters,
        }
    )
    return f"{EUROSTAT_BASE}/{urllib.parse.quote(contract['dataset'])}?{query}"


def build_ecb_url(series_id: str, *, last_observations: int = 8) -> str:
    registered = {
        item
        for values in EURO_AREA_FINANCIAL_SERIES_MAP.values()
        for item in values
        if not item.startswith("official.") and not item.startswith("tushare.")
    }
    if series_id not in registered:
        raise DataVendorUnavailable(f"unregistered ECB series: {series_id}")
    if last_observations < 1 or last_observations > 40:
        raise DataVendorUnavailable("ECB last_observations must be in 1..40")
    flow, separator, key = series_id.partition(".")
    if not separator or not flow or not key:
        raise DataVendorUnavailable(f"invalid ECB series id: {series_id}")
    query = urllib.parse.urlencode(
        {
            "format": "csvdata",
            "detail": "full",
            # The live adapter is only a current-response transport probe. Full
            # revision history can make large daily series such as CISS time
            # out and still cannot establish historical PIT visibility. That
            # responsibility belongs to the archived release/vintage ledger.
            "includeHistory": "false",
            "lastNObservations": str(last_observations),
        }
    )
    return f"{ECB_BASE}/{urllib.parse.quote(flow)}/{urllib.parse.quote(key, safe='.+')}?{query}"


def build_world_bank_url(series_key: str, *, most_recent: int = 8) -> str:
    contract = WORLD_BANK_EU_CONTEXT_SERIES.get(series_key)
    if contract is None:
        raise DataVendorUnavailable(f"unregistered World Bank context series: {series_key}")
    if WORLD_BANK_CONTEXT_MAP["world_development_indicators"]["usage_mode"] != "CONTEXT_ONLY":
        raise DataVendorUnavailable("World Bank context contract is not fail-closed")
    if most_recent < 1 or most_recent > 40:
        raise DataVendorUnavailable("World Bank most_recent must be in 1..40")
    query = urllib.parse.urlencode(
        {
            "format": "json",
            "source": contract["source"],
            "mrnev": str(most_recent),
            "per_page": str(most_recent),
        }
    )
    return (
        f"{WORLD_BANK_BASE}/country/{contract['country']}/indicator/"
        f"{contract['indicator']}?{query}"
    )


def parse_eurostat_jsonstat(payload: bytes) -> list[dict[str, Any]]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable("Eurostat response is not valid JSON") from exc
    dimension_ids = document.get("id")
    sizes = document.get("size")
    dimensions = document.get("dimension")
    values = document.get("value")
    if (
        document.get("class") != "dataset"
        or not isinstance(dimension_ids, list)
        or not isinstance(sizes, list)
        or len(dimension_ids) != len(sizes)
        or not isinstance(dimensions, Mapping)
        or not isinstance(values, (list, Mapping))
    ):
        raise DataVendorUnavailable("Eurostat JSON-stat contract mismatch")
    codes_by_dimension: list[list[str]] = []
    for dimension_id, size in zip(dimension_ids, sizes, strict=True):
        category = dimensions.get(dimension_id, {}).get("category", {})
        index = category.get("index")
        if isinstance(index, list):
            codes = [str(item) for item in index]
        elif isinstance(index, Mapping):
            codes = [
                str(code)
                for code, _ in sorted(index.items(), key=lambda item: int(item[1]))
            ]
        else:
            raise DataVendorUnavailable("Eurostat dimension category index is missing")
        if isinstance(size, bool) or not isinstance(size, int) or len(codes) != size:
            raise DataVendorUnavailable("Eurostat dimension size mismatch")
        codes_by_dimension.append(codes)
    rows = []
    for flat_index, combination in enumerate(itertools.product(*codes_by_dimension)):
        value = values.get(str(flat_index)) if isinstance(values, Mapping) else values[flat_index]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DataVendorUnavailable("Eurostat observation value is not numeric")
        row = dict(zip((str(item) for item in dimension_ids), combination, strict=True))
        row["value"] = value
        rows.append(row)
    if not rows:
        raise DataVendorUnavailable("Eurostat response has no observations")
    return rows


def parse_ecb_csv(payload: bytes) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataVendorUnavailable("ECB response is not UTF-8 CSV") from exc
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("ACTION", "").casefold() == "delete" and not row.get("OBS_VALUE"):
            continue
        if not row.get("TIME_PERIOD") or not row.get("OBS_VALUE"):
            raise DataVendorUnavailable("ECB CSV is missing TIME_PERIOD/OBS_VALUE")
        try:
            value = float(row["OBS_VALUE"])
        except (TypeError, ValueError) as exc:
            raise DataVendorUnavailable("ECB observation value is not numeric") from exc
        rows.append({**row, "OBS_VALUE": value})
    if not rows:
        raise DataVendorUnavailable("ECB response has no observations")
    return rows


def parse_world_bank_json(payload: bytes) -> list[dict[str, Any]]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable("World Bank response is not valid JSON") from exc
    if (
        not isinstance(document, list)
        or len(document) != 2
        or not isinstance(document[0], Mapping)
        or not isinstance(document[1], list)
    ):
        raise DataVendorUnavailable("World Bank response contract mismatch")
    rows = [
        dict(row)
        for row in document[1]
        if isinstance(row, Mapping)
        and row.get("value") is not None
        and row.get("date") is not None
    ]
    if not rows:
        raise DataVendorUnavailable("World Bank response has no observations")
    return rows


def fetch_official_series(
    *,
    provider: str,
    series_key: str,
    as_of: str,
    fetch: Fetch = _live_fetch,
) -> dict[str, Any]:
    if provider == "EUROSTAT":
        url = build_eurostat_url(series_key)
        parser = parse_eurostat_jsonstat
        source = f"eurostat.{EU_SERIES_MAP[series_key]['dataset']}"
        usage_mode = "PRIMARY"
    elif provider == "ECB":
        url = build_ecb_url(series_key)
        parser = parse_ecb_csv
        source = f"ecb.{series_key}"
        usage_mode = "PRIMARY"
    elif provider == "WORLD_BANK":
        url = build_world_bank_url(series_key)
        parser = parse_world_bank_json
        source = f"world_bank.{series_key}"
        usage_mode = "CONTEXT_ONLY"
    else:
        raise DataVendorUnavailable(f"unsupported official macro provider: {provider}")
    started = time.monotonic()
    response = fetch(url)
    _require_live_as_of(response, as_of)
    rows = parser(response.body)
    return {
        "adapter_version": OFFICIAL_MACRO_ADAPTER_VERSION,
        "provider": provider,
        "series_key": series_key,
        "source": source,
        "usage_mode": usage_mode,
        "request_url": response.url,
        "content_type": response.content_type,
        "retrieved_at": response.retrieved_at,
        "payload_hash": _sha256_bytes(response.body),
        "row_count": len(rows),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "rows": rows,
        "pit_status": "CURRENT_RESPONSE_REQUIRES_RELEASE_VINTAGE_JOIN",
    }


__all__ = [
    "ECB_BASE",
    "EUROSTAT_BASE",
    "OFFICIAL_MACRO_ADAPTER_VERSION",
    "OfficialApiResponse",
    "WORLD_BANK_BASE",
    "WORLD_BANK_EU_CONTEXT_SERIES",
    "build_ecb_url",
    "build_eurostat_url",
    "build_world_bank_url",
    "fetch_official_series",
    "parse_ecb_csv",
    "parse_eurostat_jsonstat",
    "parse_world_bank_json",
]

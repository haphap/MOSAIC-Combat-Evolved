"""Fail-closed adapters for public EU and World Bank macro APIs.

The adapters return raw provider observations plus provenance. They do not
invent release timestamps or convert a current response into a historical PIT
observation; that join remains the responsibility of the release/vintage
ledger before data can enter a role snapshot.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import itertools
import json
import math
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

from .exceptions import DataVendorUnavailable
from .macro_source_contracts import (
    EURO_AREA_FINANCIAL_SERIES_MAP,
    EU_REAL_ECONOMY_SERIES_MAP,
    EU_SERIES_MAP,
    WORLD_BANK_CONTEXT_MAP,
)

EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
WORLD_BANK_BASE = "https://api.worldbank.org/v2"
FOMC_FEED_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
NY_FED_RATES_BASE = "https://markets.newyorkfed.org/api/rates"
OFFICIAL_MACRO_ADAPTER_VERSION = "official_macro_adapters_v1"
_ALLOWED_HOSTS = {
    "ec.europa.eu",
    "data-api.ecb.europa.eu",
    "api.worldbank.org",
    "markets.newyorkfed.org",
    "www.federalreserve.gov",
}
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_NY_FED_RATE_PATHS = {
    "EFFR": "unsecured/effr",
    "SOFR": "secured/sofr",
}

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
    raise DataVendorUnavailable(
        f"official macro API request failed: {last_error}"
    ) from last_error


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


def build_ecb_url(
    series_id: str,
    *,
    last_observations: int | None = 8,
    include_history: bool = False,
    observation_start: str | None = None,
    observation_end: str | None = None,
) -> str:
    registered = {
        item
        for values in EURO_AREA_FINANCIAL_SERIES_MAP.values()
        for item in values
        if not item.startswith("official.") and not item.startswith("tushare.")
    }
    registered.update(EU_REAL_ECONOMY_SERIES_MAP)
    if series_id not in registered:
        raise DataVendorUnavailable(f"unregistered ECB series: {series_id}")
    if (observation_start is None) != (observation_end is None):
        raise DataVendorUnavailable(
            "ECB observation_start and observation_end must be supplied together"
        )
    if observation_start is not None and observation_end is not None:
        try:
            start = date.fromisoformat(observation_start)
            end = date.fromisoformat(observation_end)
        except ValueError as exc:
            raise DataVendorUnavailable("ECB observation window must use ISO dates") from exc
        if end < start:
            raise DataVendorUnavailable("ECB observation_end precedes observation_start")
        if last_observations is not None:
            raise DataVendorUnavailable(
                "ECB explicit observation window cannot use last_observations"
            )
    elif (
        isinstance(last_observations, bool)
        or not isinstance(last_observations, int)
        or last_observations < 1
        or last_observations > 40
    ):
        raise DataVendorUnavailable("ECB last_observations must be in 1..40")
    flow, separator, key = series_id.partition(".")
    if not separator or not flow or not key:
        raise DataVendorUnavailable(f"invalid ECB series id: {series_id}")
    params = {
        "format": "csvdata",
        "detail": "full",
        "includeHistory": str(include_history).casefold(),
    }
    if observation_start is not None and observation_end is not None:
        params.update(
            {
                "startPeriod": observation_start,
                "endPeriod": observation_end,
            }
        )
    else:
        params["lastNObservations"] = str(last_observations)
    query = urllib.parse.urlencode(params)
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


def build_fomc_feed_url() -> str:
    return FOMC_FEED_URL


def build_ny_fed_rate_url(
    rate_type: str,
    *,
    start_date: str,
    end_date: str,
) -> str:
    normalized = str(rate_type or "").strip().upper()
    path = _NY_FED_RATE_PATHS.get(normalized)
    if path is None:
        raise DataVendorUnavailable(f"unsupported NY Fed rate: {normalized!r}")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise DataVendorUnavailable("NY Fed rate dates must be ISO dates") from exc
    if end < start:
        raise DataVendorUnavailable("NY Fed rate end_date precedes start_date")
    query = urllib.parse.urlencode(
        {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "type": "rate",
        }
    )
    return f"{NY_FED_RATES_BASE}/{path}/search.json?{query}"


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


def parse_ecb_history_csv(payload: bytes) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataVendorUnavailable("ECB response is not UTF-8 CSV") from exc
    rows: list[dict[str, Any]] = []
    for raw in csv.DictReader(io.StringIO(text)):
        action = str(raw.get("ACTION") or "").strip()
        if action.casefold() not in {"insert", "replace", "delete"}:
            raise DataVendorUnavailable("ECB history ACTION is missing or unsupported")
        valid_from_text = str(raw.get("VALID_FROM") or "").strip()
        valid_to_text = str(raw.get("VALID_TO") or "").strip()
        if not raw.get("TIME_PERIOD") or (
            not valid_from_text
            and not (action.casefold() == "delete" and valid_to_text)
        ):
            raise DataVendorUnavailable(
                "ECB history is missing TIME_PERIOD/validity timestamp"
            )
        try:
            valid_from = (
                datetime.fromisoformat(valid_from_text.replace("Z", "+00:00"))
                if valid_from_text
                else None
            )
            valid_to = (
                datetime.fromisoformat(valid_to_text.replace("Z", "+00:00"))
                if valid_to_text
                else None
            )
        except ValueError as exc:
            raise DataVendorUnavailable("ECB history validity timestamp is invalid") from exc
        if (valid_from is not None and valid_from.tzinfo is None) or (
            valid_to is not None and valid_to.tzinfo is None
        ):
            raise DataVendorUnavailable(
                "ECB history validity timestamp must include timezone"
            )
        if (
            valid_from is not None
            and valid_to is not None
            and valid_to < valid_from
        ):
            raise DataVendorUnavailable("ECB history VALID_TO precedes VALID_FROM")
        value_text = str(raw.get("OBS_VALUE") or "").strip()
        if action.casefold() == "delete":
            if value_text:
                raise DataVendorUnavailable("ECB Delete history row must not contain OBS_VALUE")
            value: float | None = None
        else:
            try:
                value = float(value_text)
            except (TypeError, ValueError) as exc:
                raise DataVendorUnavailable(
                    "ECB history observation value is not numeric"
                ) from exc
            if not math.isfinite(value):
                raise DataVendorUnavailable(
                    "ECB history observation value must be finite"
                )
        rows.append(
            {
                **raw,
                "ACTION": action.capitalize(),
                "VALID_FROM": valid_from.isoformat() if valid_from is not None else "",
                "VALID_TO": valid_to.isoformat() if valid_to is not None else "",
                "OBS_VALUE": value,
            }
        )
    if not rows:
        raise DataVendorUnavailable("ECB response has no history observations")
    rows.sort(
        key=lambda row: (
            str(row["TIME_PERIOD"]),
            str(row["VALID_FROM"]),
            str(row["ACTION"]),
        )
    )
    return rows


def _eurostat_dataset_updated(payload: bytes) -> str:
    try:
        document = json.loads(payload)
        updated = datetime.fromisoformat(str(document["updated"]))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            "Eurostat response is missing a valid dataset updated timestamp"
        ) from exc
    if updated.tzinfo is None:
        raise DataVendorUnavailable("Eurostat dataset updated timestamp must include timezone")
    return updated.isoformat()


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


def _official_federal_reserve_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "www.federalreserve.gov":
        raise DataVendorUnavailable("FOMC item must use an official Federal Reserve URL")
    return value


def parse_fomc_monetary_rss(payload: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DataVendorUnavailable("FOMC RSS is not valid XML") from exc
    rows: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        title = str(item.findtext("title") or "").strip()
        category = str(item.findtext("category") or "").strip()
        if "fomc statement" not in title.casefold():
            continue
        if category.casefold() != "monetary policy":
            raise DataVendorUnavailable("FOMC statement category mismatch")
        url = _official_federal_reserve_url(str(item.findtext("link") or "").strip())
        event_id = _official_federal_reserve_url(
            str(item.findtext("guid") or "").strip()
        )
        published_text = str(item.findtext("pubDate") or "").strip()
        try:
            published = parsedate_to_datetime(published_text)
        except (TypeError, ValueError) as exc:
            raise DataVendorUnavailable("FOMC RSS pubDate is invalid") from exc
        if published.tzinfo is None:
            raise DataVendorUnavailable("FOMC RSS pubDate must include timezone")
        rows.append(
            {
                "event_id": event_id,
                "title": title,
                "url": url,
                "category": category,
                "published_at": published.astimezone(timezone.utc).isoformat(),
            }
        )
    if not rows:
        raise DataVendorUnavailable("FOMC RSS has no statement items")
    rows.sort(key=lambda row: (row["published_at"], row["event_id"]))
    if len({row["event_id"] for row in rows}) != len(rows):
        raise DataVendorUnavailable("FOMC RSS contains duplicate statement ids")
    return rows


def parse_ny_fed_reference_rates(
    payload: bytes,
    *,
    expected_rate: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    expected = str(expected_rate or "").strip().upper()
    if expected not in _NY_FED_RATE_PATHS:
        raise DataVendorUnavailable(f"unsupported NY Fed rate: {expected!r}")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        document = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable("NY Fed response/date contract is invalid") from exc
    rows_value = document.get("refRates") if isinstance(document, Mapping) else None
    if not isinstance(rows_value, list) or not rows_value:
        raise DataVendorUnavailable("NY Fed response has no reference-rate observations")
    rows: list[dict[str, Any]] = []
    for row in rows_value:
        if not isinstance(row, Mapping):
            raise DataVendorUnavailable("NY Fed reference-rate row must be an object")
        rate_type = str(row.get("type") or "").strip().upper()
        if rate_type != expected:
            raise DataVendorUnavailable("NY Fed reference-rate type mismatch")
        try:
            effective = date.fromisoformat(str(row.get("effectiveDate") or ""))
            percent_rate = float(row.get("percentRate"))
        except (TypeError, ValueError) as exc:
            raise DataVendorUnavailable("NY Fed reference-rate row is malformed") from exc
        if not start <= effective <= end:
            raise DataVendorUnavailable("NY Fed reference-rate date is outside request window")
        if not math.isfinite(percent_rate):
            raise DataVendorUnavailable("NY Fed reference rate must be finite")
        rows.append(
            {
                "effective_date": effective.isoformat(),
                "rate_type": rate_type,
                "percent_rate": percent_rate,
                "revision_indicator": str(row.get("revisionIndicator") or "").strip(),
            }
        )
    rows.sort(
        key=lambda row: (
            row["effective_date"],
            row["rate_type"],
            row["revision_indicator"],
        )
    )
    return rows


def fetch_fomc_feed(
    *,
    as_of: str,
    fetch: Fetch = _live_fetch,
    include_raw_payload: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    response = fetch(build_fomc_feed_url())
    _require_live_as_of(response, as_of)
    rows = parse_fomc_monetary_rss(response.body)
    retrieved = datetime.fromisoformat(response.retrieved_at.replace("Z", "+00:00"))
    if any(
        datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
        > retrieved
        for row in rows
    ):
        raise DataVendorUnavailable("FOMC statement publication exceeds capture time")
    result = {
        "adapter_version": OFFICIAL_MACRO_ADAPTER_VERSION,
        "provider": "FEDERAL_RESERVE",
        "series_key": "fomc_statement",
        "source": "official.fomc_statement",
        "usage_mode": "PRIMARY",
        "request_url": response.url,
        "content_type": response.content_type,
        "retrieved_at": response.retrieved_at,
        "payload_hash": _sha256_bytes(response.body),
        "row_count": len(rows),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "rows": rows,
        "pit_status": "CURRENT_RESPONSE_REQUIRES_FORWARD_ARCHIVE",
    }
    if include_raw_payload:
        result["raw_payload_b64"] = base64.b64encode(response.body).decode("ascii")
    return result


def fetch_ny_fed_rate(
    *,
    rate_type: str,
    start_date: str,
    end_date: str,
    as_of: str,
    fetch: Fetch = _live_fetch,
    include_raw_payload: bool = False,
) -> dict[str, Any]:
    normalized = str(rate_type or "").strip().upper()
    url = build_ny_fed_rate_url(
        normalized, start_date=start_date, end_date=end_date
    )
    started = time.monotonic()
    response = fetch(url)
    _require_live_as_of(response, as_of)
    rows = parse_ny_fed_reference_rates(
        response.body,
        expected_rate=normalized,
        start_date=start_date,
        end_date=end_date,
    )
    result = {
        "adapter_version": OFFICIAL_MACRO_ADAPTER_VERSION,
        "provider": "NY_FED",
        "series_key": normalized.casefold(),
        "source": f"official.nyfed_{normalized.casefold()}",
        "usage_mode": "PRIMARY",
        "request_url": response.url,
        "content_type": response.content_type,
        "retrieved_at": response.retrieved_at,
        "payload_hash": _sha256_bytes(response.body),
        "row_count": len(rows),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "rows": rows,
        "pit_status": "CURRENT_RESPONSE_REQUIRES_OBSERVED_LIVE_ARCHIVE",
    }
    if include_raw_payload:
        result["raw_payload_b64"] = base64.b64encode(response.body).decode("ascii")
    return result


def _validate_authoritative_capture_timestamp(response: OfficialApiResponse) -> None:
    try:
        retrieved = datetime.fromisoformat(
            response.retrieved_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise DataVendorUnavailable(
            "official macro timestamps must be ISO-8601"
        ) from exc
    if retrieved.tzinfo is None:
        raise DataVendorUnavailable(
            "official macro timestamps must include timezone"
        )


def fetch_official_series(
    *,
    provider: str,
    series_key: str,
    as_of: str,
    fetch: Fetch = _live_fetch,
    include_history: bool = False,
    include_raw_payload: bool = False,
    observation_start: str | None = None,
    observation_end: str | None = None,
) -> dict[str, Any]:
    if provider != "ECB" and (
        observation_start is not None or observation_end is not None
    ):
        raise DataVendorUnavailable(
            "explicit observation windows are supported only for ECB series"
        )
    if provider == "EUROSTAT":
        if include_history:
            raise DataVendorUnavailable("Eurostat does not expose revision history")
        url = build_eurostat_url(series_key)
        parser = parse_eurostat_jsonstat
        source = f"eurostat.{EU_SERIES_MAP[series_key]['dataset']}"
        usage_mode = "PRIMARY"
    elif provider == "ECB":
        explicit_window = observation_start is not None or observation_end is not None
        url = build_ecb_url(
            series_key,
            last_observations=None if explicit_window else 8,
            include_history=include_history,
            observation_start=observation_start,
            observation_end=observation_end,
        )
        parser = parse_ecb_history_csv if include_history else parse_ecb_csv
        source = f"ecb.{series_key}"
        usage_mode = "PRIMARY"
    elif provider == "WORLD_BANK":
        url = build_world_bank_url(series_key)
        parser = parse_world_bank_json
        source = f"world_bank.{series_key}"
        usage_mode = "CONTEXT_ONLY"
    else:
        if include_history:
            raise DataVendorUnavailable(
                f"{provider} does not expose authoritative revision history"
            )
        raise DataVendorUnavailable(f"unsupported official macro provider: {provider}")
    started = time.monotonic()
    response = fetch(url)
    if provider == "ECB" and include_history:
        _validate_authoritative_capture_timestamp(response)
    else:
        _require_live_as_of(response, as_of)
    rows = parser(response.body)
    result = {
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
        "pit_status": (
            "AUTHORITATIVE_VINTAGE_HISTORY"
            if provider == "ECB" and include_history
            else "CURRENT_RESPONSE_REQUIRES_RELEASE_VINTAGE_JOIN"
        ),
    }
    if provider == "EUROSTAT":
        result["dataset_updated"] = _eurostat_dataset_updated(response.body)
    if include_raw_payload:
        result["raw_payload_b64"] = base64.b64encode(response.body).decode("ascii")
    return result


__all__ = [
    "ECB_BASE",
    "EUROSTAT_BASE",
    "FOMC_FEED_URL",
    "NY_FED_RATES_BASE",
    "OFFICIAL_MACRO_ADAPTER_VERSION",
    "OfficialApiResponse",
    "WORLD_BANK_BASE",
    "WORLD_BANK_EU_CONTEXT_SERIES",
    "build_ecb_url",
    "build_eurostat_url",
    "build_fomc_feed_url",
    "build_ny_fed_rate_url",
    "build_world_bank_url",
    "fetch_fomc_feed",
    "fetch_ny_fed_rate",
    "fetch_official_series",
    "parse_ecb_csv",
    "parse_ecb_history_csv",
    "parse_eurostat_jsonstat",
    "parse_fomc_monetary_rss",
    "parse_ny_fed_reference_rates",
    "parse_world_bank_json",
]

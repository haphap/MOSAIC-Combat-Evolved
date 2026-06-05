"""FRED (Federal Reserve Economic Data) API client.

Wraps the public FRED REST API (`https://api.stlouisfed.org/fred/`) with:

* Rate limiting — token bucket sized at the FRED public limit of **120
  requests per minute** (Plan §11, §13).
* Disk cache — JSON responses stashed under
  ``{data_cache_dir}/fred/{series_id}_{start}_{end}.json`` with a 24-hour TTL
  on writes; the cache is consulted before any network call.
* Vendor contract — ``get_fred_series(...)`` returns ``str`` (CSV) so it slots
  cleanly into ``mosaic.dataflows.interface.route_to_vendor`` and the bridge
  ``tools.call`` envelope. ``_fetch_series_dataframe(...)`` exposes the
  underlying ``pandas.DataFrame`` for tests and downstream macro tools.

Series of interest for Layer 1 macro agents (Plan §5.1):
  * ``FEDFUNDS`` — Effective federal funds rate (monthly)
  * ``DFF``      — Effective federal funds rate (daily)
  * ``DGS10``    — 10-Year Treasury constant maturity
  * ``DGS2``     — 2-Year Treasury constant maturity
  * ``DTWEXBGS`` — Trade-weighted U.S. dollar (broad)
  * ``DCOILWTICO`` — WTI crude oil
  * ``GOLDPMGBD228NLBM`` — London PM gold fix
  * ``VIXCLS``   — CBOE VIX

Set ``FRED_API_KEY`` (free at https://fredaccount.stlouisfed.org/apikey) before
calling. Without it the module raises :class:`DataVendorUnavailable` so the
caller's fallback chain in ``route_to_vendor`` keeps working.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .config import get_config
from .exceptions import DataVendorUnavailable

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- constants

FRED_BASE_URL = "https://api.stlouisfed.org/fred"
FRED_OBSERVATIONS_PATH = "/series/observations"
FRED_SERIES_INFO_PATH = "/series"

REQUEST_TIMEOUT = 15  # seconds
RATE_LIMIT_REQUESTS = 120
RATE_LIMIT_WINDOW_SECONDS = 60.0
CACHE_TTL_SECONDS = 24 * 3600  # 24 h — observations rarely revise within a day

_DATE_FORMAT = "%Y-%m-%d"


# --------------------------------------------------------------------- rate limiter


class _SlidingWindowLimiter:
    """Thread-safe sliding-window rate limiter.

    Tracks the timestamps of recent calls; if the window is full, sleeps until
    the oldest one falls out. Approximates a token bucket without the
    bookkeeping for fractional tokens.
    """

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self._max_calls = max_calls
        self._window = window_seconds
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            # Drop calls that are now outside the window
            while self._calls and now - self._calls[0] > self._window:
                self._calls.popleft()
            if len(self._calls) >= self._max_calls:
                sleep_for = self._window - (now - self._calls[0])
                if sleep_for > 0:
                    logger.debug("FRED rate limit hit, sleeping %.2fs", sleep_for)
                    time.sleep(sleep_for)
                    # Re-evict after sleeping
                    now = time.monotonic()
                    while self._calls and now - self._calls[0] > self._window:
                        self._calls.popleft()
            self._calls.append(time.monotonic())


_rate_limiter = _SlidingWindowLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)


# --------------------------------------------------------------------- helpers


def _get_api_key() -> str:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise DataVendorUnavailable(
            "FRED_API_KEY is not set. Register a free key at "
            "https://fredaccount.stlouisfed.org/apikey and export it as FRED_API_KEY."
        )
    return api_key


def _cache_dir() -> Path:
    config = get_config()
    cache_root = Path(config.get("data_cache_dir") or "")
    if not cache_root:
        # Fallback when config has not been initialized (e.g. unit tests)
        cache_root = Path(os.path.expanduser("~/.mosaic/cache"))
    fred_dir = cache_root / "fred"
    fred_dir.mkdir(parents=True, exist_ok=True)
    return fred_dir


def _cache_path(series_id: str, start_date: str, end_date: str) -> Path:
    safe_id = series_id.strip().upper().replace("/", "_")
    return _cache_dir() / f"{safe_id}_{start_date}_{end_date}.json"


def _load_cached(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
            return None
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("FRED cache read failed for %s: %s", path, exc)
        return None


def _store_cached(path: Path, payload: dict[str, Any]) -> None:
    try:
        with path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False)
    except OSError as exc:
        logger.warning("FRED cache write failed for %s: %s", path, exc)


def _validate_iso_date(value: str | None, label: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        datetime.strptime(value, _DATE_FORMAT)
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"FRED {label} must be in YYYY-MM-DD format, got {value!r}: {exc}"
        ) from exc
    return value


def _request_observations(
    series_id: str,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    """Issue the actual HTTP call; returns the parsed JSON payload."""
    params: dict[str, Any] = {
        "series_id": series_id,
        "api_key": _get_api_key(),
        "file_type": "json",
    }
    if start_date:
        params["observation_start"] = start_date
    if end_date:
        params["observation_end"] = end_date

    _rate_limiter.acquire()

    url = FRED_BASE_URL + FRED_OBSERVATIONS_PATH
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        status_code = getattr(locals().get("response", None), "status_code", None)
        if status_code in {400, 404}:
            return {
                "observations": [],
                "_fred_unavailable": _redact_http_error(exc),
            }
        raise DataVendorUnavailable(
            f"FRED request for series {series_id!r} failed: {_redact_http_error(exc)}"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"FRED returned non-JSON response for series {series_id!r}: {exc}"
        ) from exc

    if "error_code" in payload or "error_message" in payload:
        message = payload.get("error_message", "unknown error")
        code = str(payload.get("error_code") or "")
        if code in {"400", "404"}:
            return {
                "observations": [],
                "_fred_unavailable": _redact_http_error(str(message)),
            }
        raise DataVendorUnavailable(
            f"FRED returned error for series {series_id!r}: {message}"
        )

    return payload


def _redact_http_error(exc: BaseException) -> str:
    text = str(exc)
    return re.sub(
        r"([?&](?:api_key|apikey|token|access_token)=)[^\s&#]+",
        r"\1<redacted>",
        text,
        flags=re.IGNORECASE,
    )


def _observations_to_rows(payload: dict[str, Any]) -> list[tuple[str, float | None]]:
    """Extract ``[(date, value), ...]`` from the FRED JSON payload.

    FRED encodes missing data as ``"."``; those become ``None`` here.
    """
    rows: list[tuple[str, float | None]] = []
    for obs in payload.get("observations", []):
        date_str = obs.get("date")
        if not date_str:
            continue
        raw_value = obs.get("value", "")
        if raw_value in ("", "."):
            value: float | None = None
        else:
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = None
        rows.append((date_str, value))
    return rows


# --------------------------------------------------------------------- public API


def _fetch_series_dataframe(
    series_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """Fetch a FRED series as a ``pandas.DataFrame`` indexed by date.

    Returns a DataFrame with two columns: ``date`` and ``value``. Missing
    observations (FRED ``"."``) are returned as ``NaN``.

    Imports pandas lazily so this module can be imported in environments
    without pandas; the function will raise :class:`DataVendorUnavailable`
    in that case.
    """
    series_id = (series_id or "").strip().upper()
    if not series_id:
        raise DataVendorUnavailable("FRED series_id must be a non-empty string")
    start_date = _validate_iso_date(start_date, "start_date")
    end_date = _validate_iso_date(end_date, "end_date")

    try:
        import pandas as pd
    except ImportError as exc:
        raise DataVendorUnavailable(
            "pandas is required to materialise FRED series as DataFrames. "
            "Install via `uv pip install -e .[data]`."
        ) from exc

    payload = _get_payload_with_cache(series_id, start_date, end_date)
    rows = _observations_to_rows(payload)
    if not rows:
        return pd.DataFrame(columns=["date", "value"])

    df = pd.DataFrame(rows, columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).reset_index(drop=True)
    return df


def get_fred_series(
    series_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Fetch a FRED series and return it as CSV text (vendor contract).

    Output shape::

        # FRED series FEDFUNDS, 2024-01-01 to 2024-06-30
        date,value
        2024-01-01,5.33
        2024-02-01,5.33
        ...

    Missing observations are emitted as empty ``value`` cells. Missing,
    invalid, or temporarily unavailable FRED series return an empty CSV with an
    ``unavailable`` comment so agent tool loops can continue. Raises
    :class:`DataVendorUnavailable` on bad inputs or missing API key.
    """
    series_id = (series_id or "").strip().upper()
    if not series_id:
        raise DataVendorUnavailable("FRED series_id must be a non-empty string")
    start_date = _validate_iso_date(start_date, "start_date")
    end_date = _validate_iso_date(end_date, "end_date")

    try:
        payload = _get_payload_with_cache(series_id, start_date, end_date)
    except DataVendorUnavailable as exc:
        message = str(exc)
        if "FRED_API_KEY" in message:
            raise
        payload = {
            "observations": [],
            "_fred_unavailable": _redact_http_error(message),
        }
    rows = _observations_to_rows(payload)

    buffer = io.StringIO()
    label_start = start_date or (rows[0][0] if rows else "earliest")
    label_end = end_date or (rows[-1][0] if rows else "latest")
    buffer.write(f"# FRED series {series_id}, {label_start} to {label_end}\n")
    unavailable = payload.get("_fred_unavailable")
    if unavailable:
        buffer.write(f"# FRED unavailable: {_redact_http_error(str(unavailable))}\n")
    writer = csv.writer(buffer)
    writer.writerow(["date", "value"])
    for date_str, value in rows:
        writer.writerow([date_str, "" if value is None else f"{value}"])
    return buffer.getvalue()


def _get_payload_with_cache(
    series_id: str,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    cache_key_start = start_date or "open"
    cache_key_end = end_date or "open"
    cache_path = _cache_path(series_id, cache_key_start, cache_key_end)

    cached = _load_cached(cache_path)
    if cached is not None:
        logger.debug("FRED cache hit: %s", cache_path)
        return cached

    payload = _request_observations(series_id, start_date, end_date)
    _store_cached(cache_path, payload)
    return payload


def clear_cache() -> int:
    """Remove all cached FRED responses; returns count of files deleted.

    Useful for tests and for ``cache.clear`` integration in later phases.
    """
    cache_dir = _cache_dir()
    deleted = 0
    for entry in cache_dir.glob("*.json"):
        try:
            entry.unlink()
            deleted += 1
        except OSError:
            continue
    return deleted

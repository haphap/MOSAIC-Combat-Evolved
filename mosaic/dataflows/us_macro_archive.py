"""Trusted US macro capture built from the existing FRED and official adapters."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

import requests

from mosaic.scorecard.canonical_json import canonical_hash

from .agent_materialization import (
    AgentDataMaterializationLedger,
    RouteCoverageReceipt,
    SnapshotBuildReceipt,
    SourceCaptureReceipt,
    load_agent_data_route_manifest,
)
from .exceptions import DataVendorUnavailable
from .fred import get_alfred_vintage, select_alfred_vintage
from .macro_snapshots import (
    ALFRED_SERIES_MAP,
    ALFRED_SERIES_ROLE_MAP,
    MACRO_SNAPSHOT_SCHEMA_VERSION,
    validate_role_snapshot,
)
from .official_macro_adapters import fetch_fomc_feed, fetch_ny_fed_rate
from .tushare import _query_pro
from .tushare_catalog import assert_endpoint_capture_preflight_allowed


CAPTURE_SCHEMA_VERSION = "us_macro_capture_group_v1"
COMPILER_VERSION = "us_macro_compiler_v1"
ARCHIVE_LOCK_TIMEOUT_SECONDS = 60 * 60
MARKET_LOOKBACK_CALENDAR_DAYS = 35
LOGICAL_ROUTES = (
    "alfred.us_macro",
    "market.us_conditions",
    "official.us_policy",
    "tushare.fx_daily",
    "tushare.us_tycr",
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DECISION_CUTOFF = time(15, 0)
_ALFRED_METADATA = {
    mapping["series_id"]: mapping for mapping in ALFRED_SERIES_MAP.values()
}
_ALFRED_SERIES_IDS = tuple(sorted(ALFRED_SERIES_ROLE_MAP))
_TUSHARE_TREASURY_FIELDS = {
    "DGS2": "y2",
    "DGS3MO": "m3",
    "DGS10": "y10",
    "DGS30": "y30",
}
_SOURCE_SCHEMA_HASH = canonical_hash(
    {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "routes": list(LOGICAL_ROUTES),
        "alfred_series_ids": list(_ALFRED_SERIES_IDS),
        "official_series": ["fomc_statement", "EFFR", "SOFR"],
        "tushare_endpoints": ["fx_daily", "us_tycr"],
    }
)


class USMacroSchemaError(DataVendorUnavailable):
    """A provider response cannot satisfy the frozen US macro contract."""


class USMacroCaptureAfterCutoff(DataVendorUnavailable):
    """A live US route completed after the A-share decision cutoff."""


class USMacroCaptureBeforeWindow(DataVendorUnavailable):
    """A US macro materialization was requested before its as-of date."""


@dataclass(frozen=True)
class USMacroArchiveResult:
    source_receipts: tuple[SourceCaptureReceipt, ...]
    coverage_receipt: RouteCoverageReceipt
    cache_hit: bool
    group: dict[str, Any] | None


@dataclass(frozen=True)
class USMacroBuildResult:
    snapshots: dict[str, dict[str, Any]]
    build_receipts: tuple[SnapshotBuildReceipt, ...]


def us_macro_archive_path() -> Path:
    explicit = os.getenv("MOSAIC_US_MACRO_ARCHIVE_DB")
    if explicit:
        return Path(explicit).expanduser()
    cache_root = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache_root / "agent_data" / "us_macro.sqlite3"


def us_macro_snapshot_root() -> Path:
    explicit = os.getenv("MOSAIC_US_MACRO_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    cache_root = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache_root / "agent_data" / "us_macro_snapshots"


def _capture_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise USMacroSchemaError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise USMacroSchemaError(f"{field} must include timezone")
    return parsed


def _is_transport_failure(exc: BaseException) -> bool:
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(
            current,
            (
                TimeoutError,
                ConnectionError,
                requests.Timeout,
                requests.ConnectionError,
            ),
        ):
            return True
        for nested in (current.__cause__, current.__context__):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, allow_nan=False)
    )


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _private_fomc_fetch(*, as_of: str) -> dict[str, Any]:
    return fetch_fomc_feed(as_of=as_of, include_raw_payload=True)


def _private_nyfed_fetch(
    *, rate_type: str, start_date: str, end_date: str, as_of: str
) -> dict[str, Any]:
    return fetch_ny_fed_rate(
        rate_type=rate_type,
        start_date=start_date,
        end_date=end_date,
        as_of=as_of,
        include_raw_payload=True,
    )


def _private_tushare_fetch(*, endpoint: str, **params: str) -> Any:
    assert_endpoint_capture_preflight_allowed(endpoint)
    return _query_pro(endpoint, **params)


class USMacroArchiveStore:
    """Append-only compressed US macro groups using SQLite serialization."""

    def __init__(self, path: Path | None = None, *, create: bool = True) -> None:
        self.path = path or us_macro_archive_path()
        self._available = self.path.exists()
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialise()
            self._available = True

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if not self._available:
            raise FileNotFoundError(self.path)
        if read_only:
            conn = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro",
                timeout=30,
                isolation_level=None,
                uri=True,
            )
            conn.execute("PRAGMA query_only = ON")
        else:
            conn = sqlite3.connect(
                self.path,
                timeout=ARCHIVE_LOCK_TIMEOUT_SECONDS,
                isolation_level=None,
            )
            conn.execute(
                f"PRAGMA busy_timeout = {ARCHIVE_LOCK_TIMEOUT_SECONDS * 1000}"
            )
            conn.execute("PRAGMA journal_mode = DELETE")
        conn.row_factory = sqlite3.Row
        return conn

    def _initialise(self) -> None:
        self._available = True
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS us_macro_capture_groups (
                    capture_key TEXT PRIMARY KEY,
                    group_hash TEXT NOT NULL UNIQUE,
                    as_of_date TEXT NOT NULL,
                    cutoff_at TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    payload_zlib BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS us_macro_capture_as_of
                  ON us_macro_capture_groups(as_of_date, captured_at);
                CREATE TRIGGER IF NOT EXISTS us_macro_capture_groups_no_update
                  BEFORE UPDATE ON us_macro_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS us_macro_capture_groups_no_delete
                  BEFORE DELETE ON us_macro_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        try:
            payload = json.loads(zlib.decompress(row["payload_zlib"]).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("US macro archive payload is unreadable") from exc
        if canonical_hash(payload) != row["group_hash"]:
            raise ValueError("US macro archive group hash mismatch")
        return payload

    def get_or_capture(
        self,
        capture_key: str,
        builder: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT * FROM us_macro_capture_groups WHERE capture_key = ?",
                    (capture_key,),
                ).fetchone()
                if existing is not None:
                    payload = self._decode(existing)
                    conn.execute("COMMIT")
                    return payload, True
                payload = builder()
                encoded = _canonical_bytes(payload)
                conn.execute(
                    "INSERT INTO us_macro_capture_groups "
                    "(capture_key, group_hash, as_of_date, cutoff_at, captured_at, payload_zlib) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        capture_key,
                        canonical_hash(payload),
                        payload["as_of_date"],
                        payload["cutoff_at"],
                        payload["captured_at"],
                        zlib.compress(encoded, level=9),
                    ),
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return payload, False

    def load_group(self, capture_key: str) -> dict[str, Any]:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM us_macro_capture_groups WHERE capture_key = ?",
                (capture_key,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"no US macro capture group for {capture_key}")
            return self._decode(row)

    def row_count(self) -> int:
        with self._connect(read_only=True) as conn:
            return int(
                conn.execute("SELECT count(*) FROM us_macro_capture_groups").fetchone()[0]
            )


def _validate_alfred_payload(
    payload: Mapping[str, Any],
    *,
    series_id: str,
    vintage_date: str,
    observation_start: str,
    observation_end: str,
) -> dict[str, Any]:
    value = _json_copy(payload)
    rows = value.get("observations")
    if not isinstance(rows, list) or not rows:
        raise USMacroSchemaError(f"ALFRED {series_id} returned no observations")
    seen_dates: set[str] = set()
    numeric_count = 0
    for row in rows:
        if not isinstance(row, dict):
            raise USMacroSchemaError(f"ALFRED {series_id} observation is not an object")
        try:
            observed = date.fromisoformat(str(row["date"]))
            realtime_start = date.fromisoformat(str(row["realtime_start"]))
            realtime_end = date.fromisoformat(str(row["realtime_end"]))
        except (KeyError, ValueError) as exc:
            raise USMacroSchemaError(
                f"ALFRED {series_id} observation metadata is malformed"
            ) from exc
        if not date.fromisoformat(observation_start) <= observed <= date.fromisoformat(
            observation_end
        ):
            raise USMacroSchemaError(f"ALFRED {series_id} observation is outside window")
        vintage = date.fromisoformat(vintage_date)
        if not realtime_start <= vintage <= realtime_end:
            raise USMacroSchemaError(f"ALFRED {series_id} vintage metadata drift")
        observed_text = observed.isoformat()
        if observed_text in seen_dates:
            raise USMacroSchemaError(f"ALFRED {series_id} duplicate observation date")
        seen_dates.add(observed_text)
        raw = row.get("value")
        if raw not in {".", "", None}:
            try:
                numeric = float(raw)
            except (TypeError, ValueError) as exc:
                raise USMacroSchemaError(f"ALFRED {series_id} value is not numeric") from exc
            if not math.isfinite(numeric):
                raise USMacroSchemaError(f"ALFRED {series_id} value is not finite")
            numeric_count += 1
    if numeric_count == 0:
        raise USMacroSchemaError(f"ALFRED {series_id} has no usable numeric value")
    return value


def _decode_official_raw(payload: Mapping[str, Any], expected_source: str) -> bytes:
    if payload.get("source") != expected_source:
        raise USMacroSchemaError(f"official source identity drift for {expected_source}")
    encoded = payload.get("raw_payload_b64")
    if not isinstance(encoded, str) or not encoded:
        raise USMacroSchemaError(f"{expected_source} raw payload is missing")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise USMacroSchemaError(f"{expected_source} raw payload is malformed") from exc
    if _sha256_bytes(raw) != payload.get("payload_hash"):
        raise USMacroSchemaError(f"{expected_source} raw payload hash mismatch")
    return raw


def _validate_official_payload(
    payload: Mapping[str, Any],
    *,
    expected_source: str,
    cutoff: datetime,
    require_rows: bool,
) -> dict[str, Any]:
    value = _json_copy(payload)
    _decode_official_raw(value, expected_source)
    retrieved = _timestamp(str(value.get("retrieved_at")), f"{expected_source}.retrieved_at")
    if retrieved > cutoff:
        raise USMacroCaptureAfterCutoff(expected_source)
    rows = value.get("rows")
    if not isinstance(rows, list) or (require_rows and not rows):
        raise USMacroSchemaError(f"{expected_source} returned incomplete rows")
    if value.get("row_count") != len(rows):
        raise USMacroSchemaError(f"{expected_source} row_count drift")
    return value


def _response_rows(payload: Any, endpoint: str) -> list[dict[str, Any]]:
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict(orient="records")
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
        raise USMacroSchemaError(f"Tushare {endpoint} response is not tabular")
    rows = []
    for row in payload:
        if not isinstance(row, Mapping):
            raise USMacroSchemaError(f"Tushare {endpoint} row is malformed")
        rows.append(_json_copy(row))
    if not rows:
        raise USMacroSchemaError(f"Tushare {endpoint} returned no rows")
    return rows


def _tushare_date(value: Any, endpoint: str) -> date:
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise USMacroSchemaError(f"Tushare {endpoint} date is malformed") from exc


def _finite_number(value: Any, field: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise USMacroSchemaError(f"{field} is not numeric") from exc
    if not math.isfinite(numeric):
        raise USMacroSchemaError(f"{field} is not finite")
    return numeric


def _validate_tushare_payload(
    payload: Any,
    *,
    endpoint: str,
    observation_start: str,
    observation_end: str,
) -> dict[str, Any]:
    rows = _response_rows(payload, endpoint)
    start = date.fromisoformat(observation_start)
    end = date.fromisoformat(observation_end)
    date_field = "date" if endpoint == "us_tycr" else "trade_date"
    required = (
        {"date", *_TUSHARE_TREASURY_FIELDS.values()}
        if endpoint == "us_tycr"
        else {"ts_code", "trade_date", "bid_close", "ask_close"}
    )
    seen: set[tuple[str, str]] = set()
    validated: list[dict[str, Any]] = []
    usable_counts = {
        field: 0
        for field in (
            _TUSHARE_TREASURY_FIELDS.values()
            if endpoint == "us_tycr"
            else ("midpoint",)
        )
    }
    for row in rows:
        missing = sorted(required - set(row))
        if missing:
            raise USMacroSchemaError(
                f"Tushare {endpoint} response missing columns: {missing}"
            )
        observed = _tushare_date(row[date_field], endpoint)
        if not start <= observed <= end:
            raise USMacroSchemaError(f"Tushare {endpoint} row is outside window")
        instrument = str(row.get("ts_code") or endpoint)
        identity = (observed.isoformat(), instrument)
        if identity in seen:
            raise USMacroSchemaError(f"Tushare {endpoint} contains duplicate rows")
        seen.add(identity)
        if endpoint == "us_tycr":
            for field in _TUSHARE_TREASURY_FIELDS.values():
                if row[field] in {None, ""}:
                    continue
                _finite_number(row[field], f"Tushare us_tycr.{field}")
                usable_counts[field] += 1
        else:
            if instrument != "USDCNH.FXCM":
                raise USMacroSchemaError("Tushare fx_daily instrument drift")
            if row["bid_close"] not in {None, ""} and row["ask_close"] not in {
                None,
                "",
            }:
                _finite_number(row["bid_close"], "Tushare fx_daily.bid_close")
                _finite_number(row["ask_close"], "Tushare fx_daily.ask_close")
                usable_counts["midpoint"] += 1
        validated.append(row)
    missing_values = sorted(
        field for field, usable_count in usable_counts.items() if usable_count == 0
    )
    if missing_values:
        raise USMacroSchemaError(
            f"Tushare {endpoint} has no usable values for: {missing_values}"
        )
    validated.sort(key=lambda row: (str(row[date_field]), str(row.get("ts_code") or "")))
    params = {
        "start_date": observation_start.replace("-", ""),
        "end_date": observation_end.replace("-", ""),
    }
    if endpoint == "fx_daily":
        params["ts_code"] = "USDCNH.FXCM"
    return {
        "endpoint": endpoint,
        "params": params,
        "payload_hash": canonical_hash({"rows": validated}),
        "rows": validated,
    }


def _build_group(
    *,
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    observation_start: str,
    select_vintage: Callable[..., str],
    fetch_vintage: Callable[..., dict[str, Any]],
    fetch_fomc: Callable[..., dict[str, Any]],
    fetch_nyfed: Callable[..., dict[str, Any]],
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    started = _capture_now()
    if started.tzinfo is None:
        raise USMacroSchemaError("trusted capture clock must include timezone")
    if started.astimezone(_SHANGHAI).date() < date.fromisoformat(as_of_date):
        raise USMacroCaptureBeforeWindow(
            "US macro capture cannot start before the as-of date"
        )
    series: list[dict[str, Any]] = []
    for series_id in _ALFRED_SERIES_IDS:
        vintage_date = select_vintage(series_id, as_of_cutoff=cutoff_at)
        payload = fetch_vintage(
            series_id,
            observation_start=observation_start,
            observation_end=as_of_date,
            vintage_date=vintage_date,
        )
        validated = _validate_alfred_payload(
            payload,
            series_id=series_id,
            vintage_date=vintage_date,
            observation_start=observation_start,
            observation_end=as_of_date,
        )
        series.append(
            {
                "series_id": series_id,
                "vintage_date": vintage_date,
                "payload_hash": canonical_hash(validated),
                "payload": validated,
            }
        )

    historical_miss = started > cutoff
    official_policy: dict[str, Any] | None = None
    market_rates: list[dict[str, Any]] = []
    tushare_sources: dict[str, dict[str, Any]] | None = None
    if not historical_miss:
        market_start = max(
            date.fromisoformat(observation_start),
            date.fromisoformat(as_of_date)
            - timedelta(days=MARKET_LOOKBACK_CALENDAR_DAYS),
        ).isoformat()
        official_policy = _validate_official_payload(
            fetch_fomc(as_of=cutoff_at),
            expected_source="official.fomc_statement",
            cutoff=cutoff,
            require_rows=False,
        )
        for rate_type in ("EFFR", "SOFR"):
            market_rates.append(
                _validate_official_payload(
                    fetch_nyfed(
                        rate_type=rate_type,
                        start_date=market_start,
                        end_date=as_of_date,
                        as_of=cutoff_at,
                    ),
                    expected_source=f"official.nyfed_{rate_type.casefold()}",
                    cutoff=cutoff,
                    require_rows=True,
                )
            )
        tushare_sources = {
            endpoint: _validate_tushare_payload(
                fetch_tushare(
                    endpoint=endpoint,
                    start_date=observation_start.replace("-", ""),
                    end_date=as_of_date.replace("-", ""),
                    **({"ts_code": "USDCNH.FXCM"} if endpoint == "fx_daily" else {}),
                ),
                endpoint=endpoint,
                observation_start=observation_start,
                observation_end=as_of_date,
            )
            for endpoint in ("fx_daily", "us_tycr")
        }
    completed = _capture_now()
    if completed.tzinfo is None:
        raise USMacroSchemaError("trusted capture clock must include timezone")
    if not historical_miss and completed > cutoff:
        raise USMacroCaptureAfterCutoff("live US macro capture completed after cutoff")
    for payload in ([official_policy] if official_policy is not None else []) + market_rates:
        if _timestamp(payload["retrieved_at"], "retrieved_at") > completed:
            raise USMacroSchemaError("official retrieval timestamp exceeds capture time")

    route_states = {
        "alfred.us_macro": "SUCCESS",
        "market.us_conditions": "CAPTURE_REJECTED" if historical_miss else "SUCCESS",
        "official.us_policy": "CAPTURE_REJECTED" if historical_miss else "SUCCESS",
        "tushare.fx_daily": "CAPTURE_REJECTED" if historical_miss else "SUCCESS",
        "tushare.us_tycr": "CAPTURE_REJECTED" if historical_miss else "SUCCESS",
    }
    return {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "capture_key": capture_key,
        "as_of_date": as_of_date,
        "cutoff_at": cutoff_at,
        "captured_at": completed.isoformat(),
        "observation_start": observation_start,
        "observation_end": as_of_date,
        "alfred": {
            "series": series,
            "series_ids": [item["series_id"] for item in series],
            "vintage_dates": sorted({item["vintage_date"] for item in series}),
        },
        "official_policy": official_policy,
        "market_conditions": (
            {
                "requested_start": market_start,
                "requested_end": as_of_date,
                "rates": market_rates,
            }
            if market_rates
            else None
        ),
        "tushare": tushare_sources,
        "route_states": route_states,
    }


def _capture_id(capture_key: str, route_id: str) -> str:
    return f"us-macro:{capture_key.removeprefix('sha256:')}:{route_id}"


def _receipt_common(group: Mapping[str, Any], route_id: str) -> dict[str, Any]:
    return {
        "schema_version": "source_capture_receipt_v1",
        "identity": {
            "source_family": {
                "alfred.us_macro": "alfred",
                "market.us_conditions": "market",
                "official.us_policy": "official_us",
                "tushare.fx_daily": "tushare",
                "tushare.us_tycr": "tushare",
            }[route_id],
            "route_id": route_id,
            "request_hash": canonical_hash(
                {
                    "route_id": route_id,
                    "as_of_date": group["as_of_date"],
                    "cutoff_at": group["cutoff_at"],
                    "observation_start": group["observation_start"],
                    "observation_end": group["observation_end"],
                    "series_ids": group["alfred"]["series_ids"],
                }
            ),
            "capture_id": _capture_id(str(group["capture_key"]), route_id),
        },
        "pit": {
            "as_of_cutoff": group["cutoff_at"],
            "eligible": True,
            "blocker_codes": [],
        },
        "provenance": {
            "parent_capture_hash": None,
            "previous_revision_hash": None,
            "revision_reason": None,
        },
    }


def _alfred_receipt(group: Mapping[str, Any]) -> SourceCaptureReceipt:
    route_id = "alfred.us_macro"
    payload = _receipt_common(group, route_id)
    series = group["alfred"]["series"]
    observed_dates = sorted(
        str(row["date"])
        for item in series
        for row in item["payload"]["observations"]
    )
    vintage_dates = list(group["alfred"]["vintage_dates"])
    latest_vintage = max(vintage_dates) + "T23:59:59+00:00"
    latest_complete_date = (
        _timestamp(str(group["cutoff_at"]), "cutoff_at").date()
        - timedelta(days=1)
    ).isoformat()
    vintage_queries = [
        {
            "path": "series/vintagedates",
            "params": {
                "api_key": "<redacted>",
                "file_type": "json",
                "limit": 1,
                "offset": 0,
                "realtime_end": latest_complete_date,
                "realtime_start": "1776-07-04",
                "series_id": item["series_id"],
                "sort_order": "desc",
            },
        }
        for item in series
    ]
    observation_queries = [
        {
            "path": "series/observations",
            "params": {
                "api_key": "<redacted>",
                "file_type": "json",
                "observation_end": group["observation_end"],
                "observation_start": group["observation_start"],
                "series_id": item["series_id"],
                "vintage_dates": item["vintage_date"],
            },
        }
        for item in series
    ]
    payload["identity"]["request_hash"] = canonical_hash(
        {
            "base_url": "https://api.stlouisfed.org/fred",
            "observation_queries": observation_queries,
            "route_id": route_id,
            "vintage_queries": vintage_queries,
        }
    )
    payload.update(
        {
            "transport": {
                "redacted_url": (
                    "https://api.stlouisfed.org/fred/"
                    "<series/vintagedates,series/observations>"
                ),
                "method": "GET",
                "query_keys": [
                    "api_key",
                    "file_type",
                    "limit",
                    "observation_end",
                    "observation_start",
                    "offset",
                    "realtime_end",
                    "realtime_start",
                    "series_id",
                    "sort_order",
                    "vintage_dates",
                ],
                "pagination_policy": "EXACT_SERIES_VINTAGE_SET",
                "page_count": len(series) * 2,
            },
            "authority": {
                "provider": "ALFRED",
                "permission_tier": "api_key_env",
                "api_version": "fred-v1",
                "parser_version": "fred_exact_vintage_v1",
            },
            "time": {
                "released_at": latest_vintage,
                "vintage_at": latest_vintage,
                "captured_at": group["captured_at"],
                "knowledge_available_at": latest_vintage,
            },
            "content": {
                "raw_content_hash": canonical_hash(group["alfred"]),
                "normalized_row_count": len(observed_dates),
                "schema_hash": _SOURCE_SCHEMA_HASH,
            },
            "coverage": {
                "requested_start": group["observation_start"],
                "requested_end": group["observation_end"],
                "observed_start": min(observed_dates),
                "observed_end": max(observed_dates),
                "dimensions": {
                    "series_id": list(group["alfred"]["series_ids"]),
                    "vintage_date": vintage_dates,
                },
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": "NON_EMPTY",
            },
        }
    )
    payload["pit"].update(
        {
            "pit_mode": "AUTHORITATIVE_VINTAGE_REPLAY",
            "vintage_query": {
                "series_ids_hash": canonical_hash(
                    group["alfred"]["series_ids"]
                ),
                "vintage_dates_hash": canonical_hash(vintage_dates),
            },
        }
    )
    return SourceCaptureReceipt.seal(payload)


def _official_receipt(group: Mapping[str, Any]) -> SourceCaptureReceipt:
    route_id = "official.us_policy"
    payload = _receipt_common(group, route_id)
    source = group["official_policy"]
    rows = source["rows"]
    published = sorted(str(row["published_at"]) for row in rows)
    captured_at = str(group["captured_at"])
    release = max(published) if published else captured_at
    observed = sorted(value[:10] for value in published)
    payload["identity"]["request_hash"] = canonical_hash(
        {
            "as_of_date": group["as_of_date"],
            "request_url": source["request_url"],
            "route_id": route_id,
        }
    )
    payload.update(
        {
            "transport": {
                "redacted_url": source["request_url"],
                "method": "GET",
                "query_keys": [],
                "pagination_policy": "SINGLE_RSS_FEED",
                "page_count": 1,
            },
            "authority": {
                "provider": "FEDERAL_RESERVE",
                "permission_tier": "public",
                "api_version": "federal-reserve-rss",
                "parser_version": source["adapter_version"],
            },
            "time": {
                "released_at": release,
                "vintage_at": release,
                "captured_at": captured_at,
                "knowledge_available_at": captured_at,
            },
            "content": {
                "raw_content_hash": source["payload_hash"],
                "normalized_row_count": len(rows),
                "schema_hash": _SOURCE_SCHEMA_HASH,
            },
            "coverage": {
                "requested_start": min(observed) if observed else group["as_of_date"],
                "requested_end": group["observation_end"],
                "observed_start": min(observed) if observed else None,
                "observed_end": max(observed) if observed else None,
                "dimensions": {"document_type": ["FOMC_STATEMENT"]},
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": "NON_EMPTY" if rows else "TRUE_EMPTY",
            },
        }
    )
    payload["pit"].update({"pit_mode": "OBSERVED_LIVE", "vintage_query": None})
    return SourceCaptureReceipt.seal(payload)


def _market_receipt(group: Mapping[str, Any]) -> SourceCaptureReceipt:
    route_id = "market.us_conditions"
    payload = _receipt_common(group, route_id)
    rates = group["market_conditions"]["rates"]
    rows = [row for source in rates for row in source["rows"]]
    observed = sorted(str(row["effective_date"]) for row in rows)
    captured_at = str(group["captured_at"])
    payload["identity"]["request_hash"] = canonical_hash(
        {
            "as_of_date": group["as_of_date"],
            "end_date": group["market_conditions"]["requested_end"],
            "rate_types": ["EFFR", "SOFR"],
            "request_urls": sorted(source["request_url"] for source in rates),
            "route_id": route_id,
            "start_date": group["market_conditions"]["requested_start"],
        }
    )
    payload.update(
        {
            "transport": {
                "redacted_url": "https://markets.newyorkfed.org/api/rates/<EFFR,SOFR>",
                "method": "GET",
                "query_keys": ["endDate", "startDate", "type"],
                "pagination_policy": "TWO_EXACT_RATE_WINDOWS",
                "page_count": len(rates),
            },
            "authority": {
                "provider": "NY_FED",
                "permission_tier": "public",
                "api_version": "markets-rates-v1",
                "parser_version": rates[0]["adapter_version"],
            },
            "time": {
                "released_at": captured_at,
                "vintage_at": captured_at,
                "captured_at": captured_at,
                "knowledge_available_at": captured_at,
            },
            "content": {
                "raw_content_hash": canonical_hash(
                    [source["payload_hash"] for source in rates]
                ),
                "normalized_row_count": len(rows),
                "schema_hash": _SOURCE_SCHEMA_HASH,
            },
            "coverage": {
                "requested_start": group["market_conditions"]["requested_start"],
                "requested_end": group["market_conditions"]["requested_end"],
                "observed_start": min(observed),
                "observed_end": max(observed),
                "dimensions": {"rate_type": ["EFFR", "SOFR"]},
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": "NON_EMPTY",
            },
        }
    )
    payload["pit"].update({"pit_mode": "OBSERVED_LIVE", "vintage_query": None})
    return SourceCaptureReceipt.seal(payload)


def _tushare_receipt(
    group: Mapping[str, Any], endpoint: str
) -> SourceCaptureReceipt:
    route_id = f"tushare.{endpoint}"
    payload = _receipt_common(group, route_id)
    source = group["tushare"][endpoint]
    date_field = "date" if endpoint == "us_tycr" else "trade_date"
    observed = sorted(
        _tushare_date(row[date_field], endpoint).isoformat() for row in source["rows"]
    )
    captured_at = str(group["captured_at"])
    payload["identity"]["request_hash"] = canonical_hash(
        {"endpoint": endpoint, "params": source["params"], "route_id": route_id}
    )
    payload.update(
        {
            "transport": {
                "redacted_url": f"https://api.tushare.pro/{endpoint}",
                "method": "POST",
                "query_keys": sorted(source["params"]),
                "pagination_policy": "SINGLE_WINDOW_RESPONSE",
                "page_count": 1,
            },
            "authority": {
                "provider": "tushare",
                "permission_tier": "capture_preflight_verified",
                "api_version": "pro-v1",
                "parser_version": COMPILER_VERSION,
            },
            "time": {
                "released_at": captured_at,
                "vintage_at": captured_at,
                "captured_at": captured_at,
                "knowledge_available_at": captured_at,
            },
            "content": {
                "raw_content_hash": source["payload_hash"],
                "normalized_row_count": len(source["rows"]),
                "schema_hash": _SOURCE_SCHEMA_HASH,
            },
            "coverage": {
                "requested_start": group["observation_start"],
                "requested_end": group["observation_end"],
                "observed_start": min(observed),
                "observed_end": max(observed),
                "dimensions": {
                    "endpoint": [endpoint],
                    **(
                        {"instrument": ["USDCNH.FXCM"]}
                        if endpoint == "fx_daily"
                        else {"series_id": sorted(_TUSHARE_TREASURY_FIELDS)}
                    ),
                },
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": "NON_EMPTY",
            },
        }
    )
    payload["pit"].update({"pit_mode": "OBSERVED_LIVE", "vintage_query": None})
    return SourceCaptureReceipt.seal(payload)


def _source_receipts(group: Mapping[str, Any]) -> tuple[SourceCaptureReceipt, ...]:
    receipts = [_alfred_receipt(group)]
    if group["route_states"]["market.us_conditions"] == "SUCCESS":
        receipts.extend(
            (
                _market_receipt(group),
                _official_receipt(group),
                _tushare_receipt(group, "fx_daily"),
                _tushare_receipt(group, "us_tycr"),
            )
        )
    return tuple(
        sorted(receipts, key=lambda item: item.as_dict()["identity"]["route_id"])
    )


def _coverage_receipt(
    *,
    as_of_date: str,
    cutoff_at: str,
    source_receipts: tuple[SourceCaptureReceipt, ...],
    route_states: Mapping[str, str],
    blocker_codes: tuple[str, ...],
) -> RouteCoverageReceipt:
    hashes = {
        receipt.as_dict()["identity"]["route_id"]: receipt.receipt_hash
        for receipt in source_receipts
    }
    route_results = [
        {
            "route_id": route_id,
            "capture_receipt_hash": hashes.get(route_id),
            "status": route_states[route_id],
        }
        for route_id in LOGICAL_ROUTES
    ]
    complete = all(row["status"] in {"SUCCESS", "TRUE_EMPTY"} for row in route_results)
    coverage_id = "us-macro-coverage:" + canonical_hash(
        {
            "as_of_date": as_of_date,
            "cutoff_at": cutoff_at,
            "route_results": route_results,
            "blocker_codes": list(blocker_codes),
        }
    ).removeprefix("sha256:")
    return RouteCoverageReceipt.seal(
        {
            "schema_version": "route_coverage_receipt_v1",
            "coverage_id": coverage_id,
            "window": {
                "start": f"{as_of_date}T00:00:00+08:00",
                "end": cutoff_at,
                "timezone": "Asia/Shanghai",
            },
            "required_route_ids": list(LOGICAL_ROUTES),
            "route_results": route_results,
            "coverage_complete": complete,
            "blocker_codes": list(blocker_codes),
        }
    )


def _failed_result(
    *,
    as_of_date: str,
    cutoff_at: str,
    ledger: AgentDataMaterializationLedger,
    status: str,
    blocker: str,
) -> USMacroArchiveResult:
    coverage = _coverage_receipt(
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        source_receipts=(),
        route_states={route_id: status for route_id in LOGICAL_ROUTES},
        blocker_codes=(blocker,),
    )
    ledger.append_route_coverage(coverage)
    return USMacroArchiveResult((), coverage, False, None)


def archive_us_macro_sources(
    *,
    as_of_date: str,
    cutoff_at: str,
    observation_start: str,
    store: USMacroArchiveStore,
    ledger: AgentDataMaterializationLedger,
    select_vintage: Callable[..., str] = select_alfred_vintage,
    fetch_vintage: Callable[..., dict[str, Any]] = get_alfred_vintage,
    fetch_fomc: Callable[..., dict[str, Any]] = _private_fomc_fetch,
    fetch_nyfed: Callable[..., dict[str, Any]] = _private_nyfed_fetch,
    fetch_tushare: Callable[..., Any] = _private_tushare_fetch,
) -> USMacroArchiveResult:
    as_of = date.fromisoformat(as_of_date)
    start = date.fromisoformat(observation_start)
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    cutoff_local = cutoff.astimezone(_SHANGHAI)
    if start > as_of:
        raise ValueError("observation_start cannot exceed as_of_date")
    if cutoff_local.date() != as_of or cutoff_local.time() != _DECISION_CUTOFF:
        raise ValueError("US macro cutoff must be the as-of date at 15:00 Asia/Shanghai")
    normalized_cutoff = cutoff.isoformat()
    capture_key = canonical_hash(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "as_of_date": as_of_date,
            "cutoff_at": normalized_cutoff,
            "observation_start": observation_start,
            "observation_end": as_of_date,
            "series_ids": list(_ALFRED_SERIES_IDS),
            "tushare_endpoints": ["fx_daily", "us_tycr"],
        }
    )
    try:
        group, cache_hit = store.get_or_capture(
            capture_key,
            lambda: _build_group(
                capture_key=capture_key,
                as_of_date=as_of_date,
                cutoff_at=normalized_cutoff,
                observation_start=observation_start,
                select_vintage=select_vintage,
                fetch_vintage=fetch_vintage,
                fetch_fomc=fetch_fomc,
                fetch_nyfed=fetch_nyfed,
                fetch_tushare=fetch_tushare,
            ),
        )
        sources = _source_receipts(group)
        blockers = (
            ("CAPTURE_AFTER_AS_OF_CUTOFF",)
            if group["route_states"]["market.us_conditions"] != "SUCCESS"
            else ()
        )
        coverage = _coverage_receipt(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            source_receipts=sources,
            route_states=group["route_states"],
            blocker_codes=blockers,
        )
        ledger.append_capture_group(sources, coverage)
        return USMacroArchiveResult(sources, coverage, cache_hit, group)
    except PermissionError:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="PERMISSION_DENIED",
            blocker="PERMISSION_DENIED",
        )
    except (TimeoutError, ConnectionError):
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="TRANSPORT_FAILED",
            blocker="TRANSPORT_FAILED",
        )
    except USMacroCaptureAfterCutoff:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="CAPTURE_AFTER_AS_OF_CUTOFF",
        )
    except USMacroCaptureBeforeWindow:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="CAPTURE_BEFORE_AS_OF_WINDOW",
        )
    except DataVendorUnavailable as exc:
        if _is_transport_failure(exc):
            return _failed_result(
                as_of_date=as_of_date,
                cutoff_at=normalized_cutoff,
                ledger=ledger,
                status="TRANSPORT_FAILED",
                blocker="TRANSPORT_FAILED",
            )
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="SCHEMA_DRIFT",
            blocker="SCHEMA_DRIFT",
        )


def _alfred_observations(
    group: Mapping[str, Any],
    receipt: SourceCaptureReceipt,
) -> dict[str, list[dict[str, Any]]]:
    by_role = {"us_economy": [], "us_financial_conditions": []}
    as_of = date.fromisoformat(str(group["as_of_date"]))
    for item in group["alfred"]["series"]:
        series_id = str(item["series_id"])
        candidates = []
        for row in item["payload"]["observations"]:
            observed = date.fromisoformat(str(row["date"]))
            if observed <= as_of and row.get("value") not in {".", "", None}:
                candidates.append((observed, row))
        if not candidates:
            raise DataVendorUnavailable(f"no usable frozen ALFRED row for {series_id}")
        observed, row = max(candidates, key=lambda value: value[0])
        vintage_at = str(row["realtime_start"]) + "T23:59:59+00:00"
        by_role[ALFRED_SERIES_ROLE_MAP[series_id]].append(
            {
                "series_id": series_id,
                "period_start": observed.isoformat(),
                "period_end": observed.isoformat(),
                "released_at": vintage_at,
                "vintage_at": vintage_at,
                "actual": float(row["value"]),
                "previous": None,
                "expected": None,
                "unit": _ALFRED_METADATA[series_id]["unit"],
                "source": "ALFRED",
                "pit_status": "AVAILABLE_AS_OF",
                "evidence_id": (
                    f"{receipt.receipt_hash}:ALFRED:{series_id}:{observed.isoformat()}:"
                    f"{str(item['payload_hash']).removeprefix('sha256:')}"
                ),
            }
        )
    for rows in by_role.values():
        rows.sort(key=lambda row: row["series_id"])
    return by_role


def _market_observations(
    group: Mapping[str, Any],
    receipt: SourceCaptureReceipt,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    as_of = date.fromisoformat(str(group["as_of_date"]))
    for source in group["market_conditions"]["rates"]:
        candidates = [
            row
            for row in source["rows"]
            if date.fromisoformat(str(row["effective_date"])) <= as_of
        ]
        if not candidates:
            raise DataVendorUnavailable(
                f"no frozen {source['series_key']} rate on or before as-of"
            )
        row = max(candidates, key=lambda item: str(item["effective_date"]))
        effective_date = str(row["effective_date"])
        series_id = "fed_" + str(source["series_key"])
        observations.append(
            {
                "series_id": series_id,
                "period_start": effective_date,
                "period_end": effective_date,
                "released_at": group["captured_at"],
                "vintage_at": group["captured_at"],
                "actual": float(row["percent_rate"]),
                "previous": None,
                "expected": None,
                "unit": "Percent",
                "source": source["source"],
                "pit_status": "AVAILABLE_AS_OF",
                "evidence_id": (
                    f"{receipt.receipt_hash}:{series_id}:{effective_date}:"
                    f"{str(source['payload_hash']).removeprefix('sha256:')}"
                ),
            }
        )
    return sorted(observations, key=lambda row: row["series_id"])


def _tushare_observations(
    group: Mapping[str, Any],
    *,
    treasury_receipt: SourceCaptureReceipt,
    fx_receipt: SourceCaptureReceipt,
) -> list[dict[str, Any]]:
    as_of = date.fromisoformat(str(group["as_of_date"]))
    released_at = str(group["captured_at"])
    observations: list[dict[str, Any]] = []
    treasury = group["tushare"]["us_tycr"]
    for series_id, field in sorted(_TUSHARE_TREASURY_FIELDS.items()):
        candidates = [
            row
            for row in treasury["rows"]
            if _tushare_date(row["date"], "us_tycr") <= as_of
            and row.get(field) not in {None, ""}
        ]
        if not candidates:
            raise DataVendorUnavailable(
                f"no frozen Tushare {series_id} row on or before as-of"
            )
        treasury_row = max(candidates, key=lambda row: str(row["date"]))
        treasury_date = _tushare_date(
            treasury_row["date"], "us_tycr"
        ).isoformat()
        observations.append(
            {
                "series_id": series_id,
                "period_start": treasury_date,
                "period_end": treasury_date,
                "released_at": released_at,
                "vintage_at": released_at,
                "actual": _finite_number(
                    treasury_row[field], f"Tushare us_tycr.{field}"
                ),
                "previous": None,
                "expected": None,
                "unit": "Percent",
                "source": "tushare.us_tycr_nominal_curve",
                "pit_status": "AVAILABLE_AS_OF",
                "evidence_id": (
                    f"{treasury_receipt.receipt_hash}:{series_id}:{treasury_date}:"
                    f"{str(treasury['payload_hash']).removeprefix('sha256:')}"
                ),
            }
        )

    fx = group["tushare"]["fx_daily"]
    fx_rows = [
        row
        for row in fx["rows"]
        if _tushare_date(row["trade_date"], "fx_daily") <= as_of
        and row.get("bid_close") not in {None, ""}
        and row.get("ask_close") not in {None, ""}
    ]
    if not fx_rows:
        raise DataVendorUnavailable("no frozen Tushare USD/CNH row on or before as-of")
    fx_row = max(fx_rows, key=lambda row: str(row["trade_date"]))
    fx_date = _tushare_date(fx_row["trade_date"], "fx_daily").isoformat()
    midpoint = (
        _finite_number(fx_row["bid_close"], "Tushare fx_daily.bid_close")
        + _finite_number(fx_row["ask_close"], "Tushare fx_daily.ask_close")
    ) / 2
    observations.append(
        {
            "series_id": "USDCNH",
            "period_start": fx_date,
            "period_end": fx_date,
            "released_at": released_at,
            "vintage_at": released_at,
            "actual": midpoint,
            "previous": None,
            "expected": None,
            "unit": "CNY per USD",
            "source": "tushare.fx_daily.USD_CNY",
            "pit_status": "AVAILABLE_AS_OF",
            "evidence_id": (
                f"{fx_receipt.receipt_hash}:USDCNH:{fx_date}:"
                f"{str(fx['payload_hash']).removeprefix('sha256:')}"
            ),
        }
    )
    return sorted(observations, key=lambda row: row["series_id"])


def _required_routes(agent_id: str, tool_id: str) -> list[str]:
    matches = [
        binding["required_route_ids"]
        for binding in load_agent_data_route_manifest()["bindings"]
        if binding["agent_id"] == agent_id
        and binding["stage"] == agent_id
        and binding["tool_id"] == tool_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f"missing exact route binding for {agent_id}/{tool_id}")
    return list(matches[0])


def _calendar_hashes(
    ledger: AgentDataMaterializationLedger,
    *,
    as_of_date: str,
    route_ids: tuple[str, ...],
) -> list[str]:
    result = []
    for route_id in route_ids:
        status = ledger.source_status(as_of=as_of_date, route_id=route_id)
        if status["status"] != "READY" or not status["capture_receipt_hash"]:
            raise DataVendorUnavailable(f"required calendar route is blocked: {route_id}")
        result.append(str(status["capture_receipt_hash"]))
    return result


def _write_snapshot(root: Path, role: str, as_of_date: str, snapshot: Mapping[str, Any]) -> None:
    destination = root / as_of_date / f"{role}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_bytes(snapshot)
    if destination.exists():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataVendorUnavailable(
                f"existing US macro snapshot is unreadable: {destination}"
            ) from exc
        if existing != dict(snapshot):
            raise DataVendorUnavailable(
                f"refusing to replace a different US macro snapshot: {destination}"
            )
        return
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, destination)


def compile_us_macro_snapshots(
    *,
    capture_key: str,
    store: USMacroArchiveStore,
    ledger: AgentDataMaterializationLedger,
    output_root: Path | None = None,
) -> USMacroBuildResult:
    group = store.load_group(capture_key)
    if group.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        raise DataVendorUnavailable("US macro archive schema drift")
    if any(group["route_states"][route] != "SUCCESS" for route in LOGICAL_ROUTES):
        raise DataVendorUnavailable("US macro capture does not cover every required route")
    sources = _source_receipts(group)
    source_by_route = {
        receipt.as_dict()["identity"]["route_id"]: receipt for receipt in sources
    }
    for route_id, receipt in source_by_route.items():
        status = ledger.source_status(as_of=group["as_of_date"], route_id=route_id)
        if status["capture_receipt_hash"] != receipt.receipt_hash:
            raise DataVendorUnavailable(f"US macro source receipt drift: {route_id}")

    observations = _alfred_observations(group, source_by_route["alfred.us_macro"])
    market = _market_observations(group, source_by_route["market.us_conditions"])
    tushare = _tushare_observations(
        group,
        treasury_receipt=source_by_route["tushare.us_tycr"],
        fx_receipt=source_by_route["tushare.fx_daily"],
    )
    economy_raw = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": "us_economy",
        "as_of_date": group["as_of_date"],
        "observations": observations["us_economy"],
        "events": [],
    }
    financial_raw = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": "us_financial_conditions",
        "as_of_date": group["as_of_date"],
        "observations": observations["us_financial_conditions"] + market + tushare,
        "context_observations": observations["us_economy"],
        "events": [],
    }
    raw_snapshots = {
        "us_economy": economy_raw,
        "us_financial_conditions": financial_raw,
    }
    snapshots = {
        role: validate_role_snapshot(raw, role, group["as_of_date"])
        for role, raw in raw_snapshots.items()
    }
    calendar_hashes = {
        "cny": _calendar_hashes(
            ledger,
            as_of_date=group["as_of_date"],
            route_ids=("tushare.eco_cal.cny",),
        )[0],
        "usd": _calendar_hashes(
            ledger,
            as_of_date=group["as_of_date"],
            route_ids=("tushare.eco_cal.usd",),
        )[0],
    }
    now = _capture_now().isoformat()
    build_specs = (
        (
            "us_economy",
            "get_us_macro_snapshot",
            [
                source_by_route["alfred.us_macro"].receipt_hash,
                source_by_route["official.us_policy"].receipt_hash,
                calendar_hashes["usd"],
            ],
        ),
        (
            "us_financial_conditions",
            "get_us_financial_conditions_snapshot",
            [receipt.receipt_hash for receipt in sources]
            + [calendar_hashes["cny"], calendar_hashes["usd"]],
        ),
    )
    build_receipts = []
    for role, tool_id, source_hashes in build_specs:
        required_routes = _required_routes(role, tool_id)
        build_id = "us-macro-build:" + canonical_hash(
            {
                "role": role,
                "as_of_date": group["as_of_date"],
                "source_receipt_hashes": sorted(source_hashes),
                "snapshot_hash": snapshots[role]["snapshot_hash"],
            }
        ).removeprefix("sha256:")
        build_receipts.append(
            SnapshotBuildReceipt.seal(
                {
                    "schema_version": "snapshot_build_receipt_v1",
                    "build_id": build_id,
                    "agent_id": role,
                    "stage": role,
                    "tool_id": tool_id,
                    "as_of": group["as_of_date"],
                    "as_of_cutoff": group["cutoff_at"],
                    "source_receipt_hashes": sorted(set(source_hashes)),
                    "compiler_version": COMPILER_VERSION,
                    "output_contract_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
                    "output_path": (
                        f"us_macro_snapshots/{group['as_of_date']}/{role}.json"
                    ),
                    "output_hash": snapshots[role]["snapshot_hash"],
                    "pit_mode": "MIXED_AUTHORITY",
                    "earliest_trustworthy_date": group["as_of_date"],
                    "required_route_ids": required_routes,
                    "missing_route_ids": [],
                    "terminal_state": "READY",
                    "blocker_codes": [],
                    "build_started_at": now,
                    "build_finished_at": now,
                }
            )
        )
    destination_root = output_root or us_macro_snapshot_root()
    for role, raw in raw_snapshots.items():
        _write_snapshot(destination_root, role, group["as_of_date"], raw)
    persisted_receipts = tuple(
        ledger.append_or_reuse_snapshot_build(receipt) for receipt in build_receipts
    )
    return USMacroBuildResult(snapshots, persisted_receipts)


__all__ = [
    "CAPTURE_SCHEMA_VERSION",
    "COMPILER_VERSION",
    "LOGICAL_ROUTES",
    "MARKET_LOOKBACK_CALENDAR_DAYS",
    "USMacroArchiveResult",
    "USMacroArchiveStore",
    "USMacroBuildResult",
    "archive_us_macro_sources",
    "compile_us_macro_snapshots",
    "us_macro_archive_path",
    "us_macro_snapshot_root",
]

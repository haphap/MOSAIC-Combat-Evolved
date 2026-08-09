"""Trusted A-share source archive and market-breadth capture adapter."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time as wall_time
import zlib
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    RouteCoverageReceipt,
    SnapshotBuildReceipt,
    SourceCaptureReceipt,
)
from mosaic.dataflows.cross_runtime_json import canonical_hash
from mosaic.dataflows.market_breadth import (
    BREADTH_SCHEMA_VERSION,
    BreadthCoverageError,
    BreadthHistoryError,
    BreadthInputs,
    compute_market_breadth_snapshot,
)
from mosaic.dataflows.tushare_catalog import (
    assert_endpoint_capture_preflight_allowed,
    endpoint_registration,
)


ROUTE_ID = "tushare.a_share_breadth"
CAPTURE_SCHEMA_VERSION = "a_share_capture_group_v1"
PARSER_VERSION = "tushare_a_share_breadth_parser_v1"
BREADTH_COMPILER_VERSION = "a_share_breadth_compiler_v1"
BREADTH_TOOL_ID = "get_market_breadth_snapshot"
PAGE_SIZE = 6000
MAX_PAGES_PER_QUERY = 20
HISTORY_CALENDAR_DAYS = 500
MIN_CAPTURE_SESSIONS = 60 - 1 + 252
MAX_CAPTURE_WORKERS = 6
CAPTURE_LOCK_TIMEOUT_SECONDS = 60 * 60
EMPTY_RESPONSE_BACKOFF_SECONDS = (0.5, 1.5)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MARKET_CLOSE = time(15, 0)
_ENDPOINTS = (
    "trade_cal",
    "stock_basic",
    "daily",
    "adj_factor",
    "suspend_d",
    "daily_basic",
)
_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "trade_cal": frozenset({"cal_date", "is_open"}),
    "stock_basic": frozenset({"ts_code", "list_date"}),
    "daily": frozenset({"ts_code", "trade_date", "close", "pre_close", "amount"}),
    "adj_factor": frozenset({"ts_code", "trade_date", "adj_factor"}),
    "suspend_d": frozenset({"ts_code", "trade_date"}),
    "daily_basic": frozenset({"ts_code", "trade_date"}),
}
_SCHEMA_HASH = canonical_hash(
    {
        "parser_version": PARSER_VERSION,
        "required_columns": {
            endpoint: sorted(columns)
            for endpoint, columns in sorted(_REQUIRED_COLUMNS.items())
        },
    }
)


class AShareArchiveError(RuntimeError):
    """Base class for sealed capture failures."""


class AShareSchemaError(AShareArchiveError):
    """The provider response violated the frozen parser schema."""


class ASharePaginationError(AShareArchiveError):
    """A paginated query did not prove its terminal page."""


class AShareIncompleteCoverage(AShareArchiveError):
    """The captured source set cannot build the required breadth window."""


class AShareNonTradingDay(AShareArchiveError):
    """The requested as-of is not an open SSE session."""


class AShareCaptureAfterCutoff(AShareArchiveError):
    """The transport completed after the declared PIT cutoff."""


class AShareMarketSessionIncomplete(AShareArchiveError):
    """The transport completed before the A-share close."""


@dataclass(frozen=True)
class AShareArchiveResult:
    source_receipts: tuple[SourceCaptureReceipt, ...]
    coverage_receipt: RouteCoverageReceipt
    snapshot: dict[str, Any] | None
    cache_hit: bool


def a_share_archive_path(root: Path | None = None) -> Path:
    explicit = os.getenv("MOSAIC_A_SHARE_ARCHIVE_DB")
    if explicit and root is None:
        return Path(explicit).expanduser()
    if root is not None:
        return root / "a_share_archive.sqlite3"
    breadth_root = os.getenv("MOSAIC_MARKET_BREADTH_DATA_DIR")
    if breadth_root:
        return Path(breadth_root).expanduser() / "a_share_archive.sqlite3"
    cache_root = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache_root / "market_breadth" / "a_share_archive.sqlite3"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _api_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _capture_now() -> datetime:
    return datetime.now(_SHANGHAI)


def _row_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        return _row_value(item())
    if isinstance(value, Mapping):
        return {str(key): _row_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_row_value(item) for item in value]
    return str(value)


def _response_rows(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        records = value.to_dict(orient="records")
    elif isinstance(value, Mapping):
        raise ConnectionError("Tushare returned a non-tabular response")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        records = list(value)
    else:
        raise AShareSchemaError("Tushare response must be a table or row sequence")
    if not all(isinstance(row, Mapping) for row in records):
        raise AShareSchemaError("Tushare response rows must be objects")
    return [
        {str(key): _row_value(item) for key, item in row.items()}
        for row in records
    ]


class AShareArchiveStore:
    """Append-only compressed capture groups with a SQLite serialization lock."""

    def __init__(self, path: Path | None = None, *, create: bool = True) -> None:
        self.path = path or a_share_archive_path()
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
                timeout=CAPTURE_LOCK_TIMEOUT_SECONDS,
                isolation_level=None,
            )
            conn.execute(
                f"PRAGMA busy_timeout = {CAPTURE_LOCK_TIMEOUT_SECONDS * 1000}"
            )
            conn.execute("PRAGMA journal_mode = DELETE")
        conn.row_factory = sqlite3.Row
        return conn

    def _initialise(self) -> None:
        self._available = True
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS a_share_capture_groups (
                    capture_key TEXT PRIMARY KEY,
                    group_hash TEXT NOT NULL UNIQUE,
                    as_of_date TEXT,
                    cutoff_at TEXT,
                    captured_at TEXT,
                    payload_zlib BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS a_share_capture_as_of
                  ON a_share_capture_groups(as_of_date, captured_at);
                CREATE TRIGGER IF NOT EXISTS a_share_capture_groups_no_update
                  BEFORE UPDATE ON a_share_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS a_share_capture_groups_no_delete
                  BEFORE DELETE ON a_share_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(zlib.decompress(row["payload_zlib"]).decode("utf-8"))
        if canonical_hash(payload) != row["group_hash"]:
            raise ValueError("A-share archive group hash mismatch")
        return payload

    def get_or_capture(
        self,
        capture_key: str,
        builder: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        """Serialize one capture key; concurrent callers reuse the first commit."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT * FROM a_share_capture_groups WHERE capture_key = ?",
                    (capture_key,),
                ).fetchone()
                if existing is not None:
                    payload = self._decode(existing)
                    conn.execute("COMMIT")
                    return payload, True
                payload = builder()
                encoded = _canonical_json(payload).encode("utf-8")
                group_hash = canonical_hash(payload)
                conn.execute(
                    "INSERT INTO a_share_capture_groups "
                    "(capture_key, group_hash, as_of_date, cutoff_at, captured_at, payload_zlib) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        capture_key,
                        group_hash,
                        payload.get("as_of_date"),
                        payload.get("cutoff_at"),
                        payload.get("captured_at"),
                        zlib.compress(encoded, level=9),
                    ),
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return payload, False

    def row_count(self) -> int:
        with self._connect(read_only=True) as conn:
            return int(conn.execute("SELECT count(*) FROM a_share_capture_groups").fetchone()[0])

    def load_group(self, as_of_date: str) -> dict[str, Any]:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM a_share_capture_groups WHERE as_of_date = ? "
                "ORDER BY captured_at DESC LIMIT 1",
                (as_of_date,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"no A-share capture group for {as_of_date}")
            return self._decode(row)

    def load_inputs(self, as_of_date: str) -> BreadthInputs:
        import pandas as pd  # noqa: PLC0415

        group = self.load_group(as_of_date)
        rows = {batch["endpoint"]: batch["rows"] for batch in group["batches"]}
        return BreadthInputs(
            stock_basic=pd.DataFrame(rows["stock_basic"]),
            daily=pd.DataFrame(rows["daily"]),
            adj_factor=pd.DataFrame(rows["adj_factor"]),
            suspensions=pd.DataFrame(rows["suspend_d"]),
        )


def _fetch_page(
    fetch: Callable[..., Any],
    endpoint: str,
    request: Mapping[str, Any],
    *,
    offset: int,
    confirm_empty: bool,
) -> tuple[list[dict[str, Any]], int]:
    call_count = 0
    for attempt in range(len(EMPTY_RESPONSE_BACKOFF_SECONDS) + 1):
        page_rows = _response_rows(
            fetch(
                endpoint,
                **dict(request),
                limit=PAGE_SIZE,
                offset=offset,
            )
        )
        call_count += 1
        if page_rows or not confirm_empty or attempt == len(
            EMPTY_RESPONSE_BACKOFF_SECONDS
        ):
            return page_rows, call_count
        wall_time.sleep(EMPTY_RESPONSE_BACKOFF_SECONDS[attempt])
    raise AssertionError("empty-page confirmation attempts exhausted")


def _paginate(
    fetch: Callable[..., Any],
    endpoint: str,
    request: Mapping[str, Any],
    *,
    confirm_terminal: bool = True,
    confirm_empty: bool = True,
) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate_count = 0
    call_count = 0
    for page in range(MAX_PAGES_PER_QUERY):
        page_rows, page_calls = _fetch_page(
            fetch,
            endpoint,
            request,
            offset=page * PAGE_SIZE,
            confirm_empty=confirm_empty,
        )
        call_count += page_calls
        for row in page_rows:
            missing = _REQUIRED_COLUMNS[endpoint] - set(row)
            if missing:
                raise AShareSchemaError(
                    f"{endpoint} response missing columns: {sorted(missing)}"
                )
            row_hash = canonical_hash(row)
            if row_hash in seen:
                duplicate_count += 1
                continue
            seen.add(row_hash)
            rows.append(row)
        if len(page_rows) < PAGE_SIZE:
            if page_rows and confirm_terminal:
                probe_offset = page * PAGE_SIZE + len(page_rows)
                probe_rows, probe_calls = _fetch_page(
                    fetch,
                    endpoint,
                    request,
                    offset=probe_offset,
                    confirm_empty=True,
                )
                call_count += probe_calls
                if probe_rows:
                    raise ASharePaginationError(
                        f"{endpoint} returned rows after a terminal short page"
                    )
            return rows, call_count, duplicate_count
    raise ASharePaginationError(f"{endpoint} did not return a terminal short page")


def _seal_batch(
    *,
    endpoint: str,
    requests: Sequence[Mapping[str, Any]],
    fetch: Callable[..., Any],
    captured_at: str,
    require_each_nonempty: bool,
    confirm_terminal: bool,
) -> tuple[dict[str, Any], int, int]:
    rows: list[dict[str, Any]] = []
    page_count = 0
    duplicate_count = 0
    worker_count = min(MAX_CAPTURE_WORKERS, len(requests))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(
                _paginate,
                fetch,
                endpoint,
                request,
                confirm_terminal=confirm_terminal,
                confirm_empty=True,
            )
            for request in requests
        ]
        try:
            for request, future in zip(requests, futures, strict=True):
                leaf_rows, leaf_pages, leaf_duplicates = future.result()
                if require_each_nonempty and not leaf_rows:
                    raise ConnectionError(
                        f"{endpoint} returned an unconfirmed empty required leaf"
                    )
                if "trade_date" in request and any(
                    str(row.get("trade_date")) != str(request["trade_date"])
                    for row in leaf_rows
                ):
                    raise AShareSchemaError(
                        f"{endpoint} returned rows outside the requested date"
                    )
                rows.extend(leaf_rows)
                page_count += leaf_pages
                duplicate_count += leaf_duplicates
        except Exception:
            for future in futures:
                future.cancel()
            raise
    registration = endpoint_registration(endpoint)
    request_summary: dict[str, Any] = {
        "request_count": len(requests),
        "requests_hash": canonical_hash([dict(request) for request in requests]),
    }
    if requests:
        for field in ("exchange", "start_date", "end_date"):
            values = {str(request[field]) for request in requests if field in request}
            if len(values) == 1:
                request_summary[field] = values.pop()
    batch: dict[str, Any] = {
        "source_id": f"tushare.{endpoint}",
        "endpoint": endpoint,
        "schema_contract_version": registration.schema_contract_version,
        "request": request_summary,
        "captured_at": captured_at,
        "released_at": captured_at,
        "vintage_at": captured_at,
        "pit_status": "PIT_VERIFIED",
        "pagination_complete": True,
        "truncated": False,
        "query_count": len(requests),
        "completed_query_count": len(requests),
        "coverage_ratio": 1.0,
        "rows": rows,
        "rows_hash": canonical_hash(rows),
    }
    batch_body = dict(batch)
    batch_body.pop("rows")
    batch_hash = canonical_hash(batch_body)
    batch["source_batch_hash"] = batch_hash
    batch["source_batch_id"] = "sector-source-batch:" + batch_hash.removeprefix(
        "sha256:"
    )
    return batch, duplicate_count, page_count


def _retime_batch(batch: dict[str, Any], captured_at: str) -> None:
    batch["captured_at"] = captured_at
    batch["released_at"] = captured_at
    batch["vintage_at"] = captured_at
    batch.pop("source_batch_hash", None)
    batch.pop("source_batch_id", None)
    batch_body = dict(batch)
    batch_body.pop("rows")
    batch_hash = canonical_hash(batch_body)
    batch["source_batch_hash"] = batch_hash
    batch["source_batch_id"] = "sector-source-batch:" + batch_hash.removeprefix(
        "sha256:"
    )


def _require_unique_keys(
    batch: Mapping[str, Any],
    fields: Sequence[str],
) -> None:
    keys = [tuple(row.get(field) for field in fields) for row in batch["rows"]]
    if any(any(value in (None, "") for value in key) for key in keys):
        raise AShareSchemaError(
            f"{batch['endpoint']} contains an incomplete natural key"
        )
    if len(keys) != len(set(keys)):
        raise AShareSchemaError(
            f"{batch['endpoint']} contains conflicting duplicate keys"
        )


def _calendar_sessions(
    rows: Sequence[Mapping[str, Any]],
    *,
    start_date: date,
    as_of_date: date,
) -> list[str]:
    by_date: dict[date, int] = {}
    for row in rows:
        try:
            day = datetime.strptime(str(row["cal_date"]), "%Y%m%d").date()
            is_open = int(row["is_open"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AShareSchemaError("trade_cal contains invalid calendar rows") from exc
        if day in by_date or is_open not in {0, 1}:
            raise AShareSchemaError("trade_cal contains duplicate or invalid sessions")
        if start_date <= day <= as_of_date:
            by_date[day] = is_open
    expected = [
        start_date + timedelta(days=offset)
        for offset in range((as_of_date - start_date).days + 1)
    ]
    if set(by_date) != set(expected):
        raise AShareIncompleteCoverage("trade_cal is not calendar-date exhaustive")
    if by_date[as_of_date] != 1:
        raise AShareNonTradingDay(as_of_date.isoformat())
    sessions = [_api_date(day) for day in expected if by_date[day] == 1]
    if len(sessions) < MIN_CAPTURE_SESSIONS:
        raise AShareIncompleteCoverage("trade_cal has insufficient breadth history")
    return sessions


def _codes_by_session(batch: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in batch["rows"]:
        result.setdefault(str(row["trade_date"]), set()).add(str(row["ts_code"]))
    return result


def _validate_session_closure(
    batches: Sequence[Mapping[str, Any]],
    sessions: Sequence[str],
) -> None:
    by_endpoint = {str(batch["endpoint"]): batch for batch in batches}
    daily = _codes_by_session(by_endpoint["daily"])
    adjusted = _codes_by_session(by_endpoint["adj_factor"])
    daily_basic = _codes_by_session(by_endpoint["daily_basic"])
    for session in sessions:
        daily_codes = daily.get(session, set())
        if not daily_codes <= adjusted.get(session, set()):
            raise AShareIncompleteCoverage(
                "adjustment factors do not cover the daily market rows"
            )
        if daily_basic.get(session, set()) != daily_codes:
            raise AShareIncompleteCoverage(
                "daily-basic rows do not match the daily market rows"
            )


def _build_capture_group(
    fetch: Callable[..., Any],
    *,
    as_of_date: date,
    cutoff_at: str,
    capture_key: str,
) -> dict[str, Any]:
    for endpoint in _ENDPOINTS:
        assert_endpoint_capture_preflight_allowed(endpoint)
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    started = _capture_now()
    if started > cutoff:
        raise AShareCaptureAfterCutoff
    if (
        started.astimezone(_SHANGHAI).date() != as_of_date
        or started.astimezone(_SHANGHAI).time() < _MARKET_CLOSE
    ):
        raise AShareMarketSessionIncomplete
    started_at = started.isoformat()
    start_date = as_of_date - timedelta(days=HISTORY_CALENDAR_DAYS)
    trade_cal, trade_cal_duplicates, trade_cal_pages = _seal_batch(
        endpoint="trade_cal",
        requests=(
            {
                "exchange": "SSE",
                "start_date": _api_date(start_date),
                "end_date": _api_date(as_of_date),
            },
        ),
        fetch=fetch,
        captured_at=started_at,
        require_each_nonempty=True,
        confirm_terminal=False,
    )
    sessions = _calendar_sessions(
        trade_cal["rows"], start_date=start_date, as_of_date=as_of_date
    )
    stock_basic, stock_duplicates, stock_pages = _seal_batch(
        endpoint="stock_basic",
        requests=tuple(
            {
                "exchange": "",
                "list_status": status,
                "fields": (
                    "ts_code,symbol,name,area,industry,cnspell,market,list_date,"
                    "act_name,act_ent_type,delist_date,list_status,exchange,"
                    "curr_type,fullname,enname"
                ),
            }
            for status in ("D", "L", "P")
        ),
        fetch=fetch,
        captured_at=started_at,
        require_each_nonempty=False,
        confirm_terminal=True,
    )
    if not stock_basic["rows"]:
        raise AShareIncompleteCoverage("stock_basic returned no securities")
    _require_unique_keys(stock_basic, ("ts_code",))
    dated_requests = tuple({"trade_date": session} for session in sessions)
    batches = [trade_cal, stock_basic]
    page_counts = {
        "trade_cal": trade_cal_pages,
        "stock_basic": stock_pages,
    }
    duplicate_counts = {
        "trade_cal": trade_cal_duplicates,
        "stock_basic": stock_duplicates,
    }
    for endpoint in ("daily", "adj_factor", "suspend_d", "daily_basic"):
        batch, duplicates, pages = _seal_batch(
            endpoint=endpoint,
            requests=dated_requests,
            fetch=fetch,
            captured_at=started_at,
            require_each_nonempty=endpoint != "suspend_d",
            confirm_terminal=endpoint == "suspend_d",
        )
        if endpoint != "suspend_d":
            _require_unique_keys(batch, ("ts_code", "trade_date"))
        batches.append(batch)
        duplicate_counts[endpoint] = duplicates
        page_counts[endpoint] = pages
    _validate_session_closure(batches, sessions)
    completed = _capture_now()
    if completed > cutoff:
        raise AShareCaptureAfterCutoff
    if (
        completed.astimezone(_SHANGHAI).date() != as_of_date
        or completed.astimezone(_SHANGHAI).time() < _MARKET_CLOSE
    ):
        raise AShareMarketSessionIncomplete
    completed_at = completed.isoformat()
    for batch in batches:
        _retime_batch(batch, completed_at)
    group: dict[str, Any] = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "capture_key": capture_key,
        "route_id": ROUTE_ID,
        "as_of_date": as_of_date.isoformat(),
        "cutoff_at": cutoff_at,
        "captured_at": completed_at,
        "requested_start": start_date.isoformat(),
        "requested_end": as_of_date.isoformat(),
        "sessions": sessions,
        "duplicate_counts": duplicate_counts,
        "page_counts": page_counts,
        "page_count": sum(page_counts.values()),
        "batches": batches,
    }
    inputs = _group_inputs(group)
    try:
        compute_market_breadth_snapshot(inputs, as_of_date.isoformat())
    except (BreadthCoverageError, BreadthHistoryError) as exc:
        raise AShareIncompleteCoverage("captured tables cannot build breadth") from exc
    return group


def _group_inputs(group: Mapping[str, Any]) -> BreadthInputs:
    import pandas as pd  # noqa: PLC0415

    rows = {batch["endpoint"]: batch["rows"] for batch in group["batches"]}
    return BreadthInputs(
        stock_basic=pd.DataFrame(rows["stock_basic"]),
        daily=pd.DataFrame(rows["daily"]),
        adj_factor=pd.DataFrame(rows["adj_factor"]),
        suspensions=pd.DataFrame(rows["suspend_d"]),
    )


def _coverage_receipt(
    *,
    as_of_date: str,
    cutoff_at: str,
    capture_hash: str | None,
    status: str,
    blocker_codes: Sequence[str],
) -> RouteCoverageReceipt:
    route_result = {
        "route_id": ROUTE_ID,
        "capture_receipt_hash": capture_hash,
        "status": status,
    }
    coverage_id = "a-share-coverage:" + canonical_hash(
        {
            "as_of_date": as_of_date,
            "cutoff_at": cutoff_at,
            "route_result": route_result,
            "blocker_codes": sorted(blocker_codes),
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
            "required_route_ids": [ROUTE_ID],
            "route_results": [route_result],
            "coverage_complete": status == "SUCCESS",
            "blocker_codes": sorted(blocker_codes),
        }
    )


def _source_receipt(group: Mapping[str, Any]) -> SourceCaptureReceipt:
    request = {
        "as_of_date": group["as_of_date"],
        "requested_start": group["requested_start"],
        "requested_end": group["requested_end"],
        "endpoints": list(_ENDPOINTS),
    }
    capture_id = "a-share-capture:" + str(group["capture_key"]).removeprefix(
        "sha256:"
    )
    total_rows = sum(len(batch["rows"]) for batch in group["batches"])
    duplicate_count = sum(int(value) for value in group["duplicate_counts"].values())
    captured_at = str(group["captured_at"])
    return SourceCaptureReceipt.seal(
        {
            "schema_version": "source_capture_receipt_v1",
            "identity": {
                "source_family": "tushare",
                "route_id": ROUTE_ID,
                "request_hash": canonical_hash(request),
                "capture_id": capture_id,
            },
            "transport": {
                "redacted_url": "https://api.tushare.pro/a-share-base",
                "method": "POST",
                "query_keys": sorted(
                    {
                        "end_date",
                        "exchange",
                        "fields",
                        "limit",
                        "list_status",
                        "offset",
                        "start_date",
                        "trade_date",
                    }
                ),
                "pagination_policy": "OFFSET_UNTIL_SHORT_PAGE",
                "page_count": int(group["page_count"]),
            },
            "authority": {
                "provider": "tushare",
                "permission_tier": "route_preflight_verified",
                "api_version": "pro-v1",
                "parser_version": PARSER_VERSION,
            },
            "time": {
                "released_at": captured_at,
                "vintage_at": captured_at,
                "captured_at": captured_at,
                "knowledge_available_at": captured_at,
            },
            "pit": {
                "pit_mode": "OBSERVED_LIVE",
                "as_of_cutoff": group["cutoff_at"],
                "eligible": True,
                "blocker_codes": [],
                "vintage_query": None,
            },
            "content": {
                "raw_content_hash": canonical_hash(group),
                "normalized_row_count": total_rows,
                "schema_hash": _SCHEMA_HASH,
            },
            "coverage": {
                "requested_start": group["requested_start"],
                "requested_end": group["requested_end"],
                "observed_start": datetime.strptime(
                    group["sessions"][0], "%Y%m%d"
                ).date().isoformat(),
                "observed_end": datetime.strptime(
                    group["sessions"][-1], "%Y%m%d"
                ).date().isoformat(),
                "dimensions": {
                    "endpoint": sorted(_ENDPOINTS),
                    "market": ["BSE", "SSE", "SZSE"],
                },
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": duplicate_count,
                "empty_result_semantics": "NON_EMPTY",
            },
            "provenance": {
                "parent_capture_hash": None,
                "previous_revision_hash": None,
                "revision_reason": None,
            },
        }
    )


def _failed_result(
    *,
    as_of_date: str,
    cutoff_at: str,
    ledger: AgentDataMaterializationLedger,
    status: str,
    blocker: str,
) -> AShareArchiveResult:
    coverage = _coverage_receipt(
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        capture_hash=None,
        status=status,
        blocker_codes=[blocker],
    )
    ledger.append_route_coverage(coverage)
    return AShareArchiveResult(
        source_receipts=(),
        coverage_receipt=coverage,
        snapshot=None,
        cache_hit=False,
    )


def archive_a_share_breadth(
    fetch: Callable[..., Any],
    *,
    as_of_date: str,
    cutoff_at: str,
    store: AShareArchiveStore,
    ledger: AgentDataMaterializationLedger,
) -> AShareArchiveResult:
    """Capture the complete A-share base route using the trusted runtime clock."""
    as_of = date.fromisoformat(as_of_date)
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    cutoff_local = cutoff.astimezone(_SHANGHAI)
    if (
        cutoff_local.date() != as_of
        or cutoff_local.time() <= _MARKET_CLOSE
    ):
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="MARKET_SESSION_INCOMPLETE",
        )
    capture_key = canonical_hash(
        {
            "route_id": ROUTE_ID,
            "as_of_date": as_of_date,
            "cutoff_at": cutoff.isoformat(),
        }
    )
    try:
        group, cache_hit = store.get_or_capture(
            capture_key,
            lambda: _build_capture_group(
                fetch,
                as_of_date=as_of,
                cutoff_at=cutoff.isoformat(),
                capture_key=capture_key,
            ),
        )
        source = _source_receipt(group)
        coverage = _coverage_receipt(
            as_of_date=as_of_date,
            cutoff_at=cutoff.isoformat(),
            capture_hash=source.receipt_hash,
            status="SUCCESS",
            blocker_codes=[],
        )
        snapshot = compute_market_breadth_snapshot(_group_inputs(group), as_of_date)
        ledger.append_capture_group((source,), coverage)
        return AShareArchiveResult(
            source_receipts=(source,),
            coverage_receipt=coverage,
            snapshot=snapshot,
            cache_hit=cache_hit,
        )
    except PermissionError:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="PERMISSION_DENIED",
            blocker="PERMISSION_DENIED",
        )
    except TimeoutError:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="TRANSPORT_FAILED",
            blocker="TRANSPORT_TIMEOUT",
        )
    except ConnectionError:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="TRANSPORT_FAILED",
            blocker="TRANSPORT_FAILED",
        )
    except ASharePaginationError:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="TRUNCATED",
            blocker="TRUNCATED",
        )
    except AShareNonTradingDay:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="NON_TRADING_DAY",
        )
    except AShareCaptureAfterCutoff:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="PIT_INELIGIBLE",
            blocker="CAPTURE_AFTER_AS_OF_CUTOFF",
        )
    except AShareMarketSessionIncomplete:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="MARKET_SESSION_INCOMPLETE",
        )
    except AShareSchemaError:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="SCHEMA_DRIFT",
            blocker="SCHEMA_DRIFT",
        )
    except (AShareIncompleteCoverage, BreadthCoverageError, BreadthHistoryError):
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="INCOMPLETE_COVERAGE",
        )
    except Exception:  # noqa: BLE001 - seal unknown vendor failures without details
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="CAPTURE_REJECTED",
        )


def compile_a_share_breadth_snapshot(
    archive: AShareArchiveResult,
    *,
    as_of_date: str,
    ledger: AgentDataMaterializationLedger,
) -> SnapshotBuildReceipt:
    """Seal the deterministic breadth snapshot or its exact blocked closure."""
    date.fromisoformat(as_of_date)
    coverage = archive.coverage_receipt.as_dict()
    snapshot = archive.snapshot
    if bool(snapshot) != bool(coverage["coverage_complete"]):
        raise ValueError("breadth snapshot contradicts route coverage")
    if snapshot is not None and snapshot.get("as_of_date") != as_of_date:
        raise ValueError("breadth snapshot as_of_date mismatch")

    if snapshot is None:
        source_hashes = [archive.coverage_receipt.receipt_hash]
        output_hash = None
        missing_routes = [ROUTE_ID]
        blocker_codes = list(coverage["blocker_codes"])
        terminal_state = "BLOCKED"
        earliest_trustworthy_date = None
    else:
        if len(archive.source_receipts) != 1:
            raise ValueError("READY breadth snapshot requires one source receipt")
        source_hashes = [archive.source_receipts[0].receipt_hash]
        output_hash = canonical_hash(snapshot)
        missing_routes = []
        blocker_codes = []
        terminal_state = "READY"
        earliest_trustworthy_date = as_of_date

    as_of_cutoff = str(coverage["window"]["end"])
    identity = {
        "as_of_date": as_of_date,
        "as_of_cutoff": as_of_cutoff,
        "source_receipt_hashes": source_hashes,
        "output_hash": output_hash,
        "missing_route_ids": missing_routes,
        "blocker_codes": blocker_codes,
    }
    now = _capture_now().isoformat()
    receipt = SnapshotBuildReceipt.seal(
        {
            "schema_version": "snapshot_build_receipt_v1",
            "build_id": (
                "a-share-breadth-build:"
                + canonical_hash(identity).removeprefix("sha256:")
            ),
            "agent_id": "market_breadth",
            "stage": "market_breadth",
            "tool_id": BREADTH_TOOL_ID,
            "as_of": as_of_date,
            "as_of_cutoff": as_of_cutoff,
            "source_receipt_hashes": source_hashes,
            "compiler_version": BREADTH_COMPILER_VERSION,
            "output_contract_version": BREADTH_SCHEMA_VERSION,
            "output_path": "market_breadth/a_share_archive.sqlite3",
            "output_hash": output_hash,
            "pit_mode": "OBSERVED_LIVE",
            "earliest_trustworthy_date": earliest_trustworthy_date,
            "required_route_ids": [ROUTE_ID],
            "missing_route_ids": missing_routes,
            "terminal_state": terminal_state,
            "blocker_codes": blocker_codes,
            "build_started_at": now,
            "build_finished_at": now,
        }
    )
    return ledger.append_or_reuse_snapshot_build(receipt)


def fetch_a_share_tushare_endpoint(endpoint: str, **params: Any) -> Any:
    """Production transport adapter; endpoint authorization is checked by archive."""
    from mosaic.dataflows.tushare import _query_pro  # noqa: PLC0415

    return _query_pro(endpoint, **params)


__all__ = [
    "AShareArchiveResult",
    "AShareArchiveStore",
    "CAPTURE_SCHEMA_VERSION",
    "MAX_CAPTURE_WORKERS",
    "MAX_PAGES_PER_QUERY",
    "PAGE_SIZE",
    "ROUTE_ID",
    "a_share_archive_path",
    "archive_a_share_breadth",
    "compile_a_share_breadth_snapshot",
    "fetch_a_share_tushare_endpoint",
]

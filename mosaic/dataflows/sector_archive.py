"""Trusted archive for standard-sector and relationship source routes."""

from __future__ import annotations

import json
import os
import sqlite3
import time as wall_time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .a_share_archive import (
    AShareArchiveStore,
    ASharePaginationError,
    AShareSchemaError,
    _response_rows,
)
from .agent_materialization import (
    AgentDataMaterializationLedger,
    RouteCoverageReceipt,
    SourceCaptureReceipt,
    canonical_hash,
)
from .exceptions import DataVendorUnavailable
from .sector_snapshots import (
    RELATIONSHIP_REQUIRED_SOURCE_ENDPOINTS,
    PAGINATION_POLICY_OFFICIAL_CAP,
    PAGINATION_POLICY_TERMINAL_CONFIRMED,
    SECTOR_DIRECTION_IDS,
    SECTOR_ETF_SOURCE_ENDPOINTS,
    SECTOR_REQUIRED_SOURCE_ENDPOINTS,
    SECTOR_UNIVERSE_MANIFEST,
    SOURCE_BATCH_PAGINATION_POLICIES,
    _authoritative_etf_codes,
    compile_registered_relationship_snapshot,
    compile_registered_sector_snapshot,
)
from .tushare_catalog import (
    PREFLIGHT_ENDPOINT_CHECKS,
    assert_endpoint_capture_preflight_allowed,
    endpoint_registration,
)

CAPTURE_SCHEMA_VERSION = "sector_relationship_capture_group_v2"
PARSER_VERSION = "sector_relationship_archive_v2"
LOGICAL_ROUTES = (
    "tushare.relationship_graph",
    "tushare.sector_fundamentals",
    "tushare.sector_market",
)
_BASE_ENDPOINTS = frozenset(
    {
        "trade_cal",
        "stock_basic",
        "daily",
        "adj_factor",
        "suspend_d",
        "daily_basic",
    }
)
_INCREMENTAL_ENDPOINTS = frozenset(
    {
        "index_member_all",
        "income",
        "balancesheet",
        "cashflow",
        "moneyflow",
        "fund_basic",
        "fund_portfolio",
        "top10_holders",
    }
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MARKET_CLOSE = time(15, 0)
_MAX_WORKERS = 6
# A live capture can legally occupy the complete post-close-to-midnight window.
_LOCK_TIMEOUT_SECONDS = 9 * 60 * 60
_PAGE_SIZE = 6000
_MAX_PAGES_PER_QUERY = 20
_EMPTY_RESPONSE_BACKOFF_SECONDS = (0.5, 1.5)


def sector_archive_path(root: Path | None = None) -> Path:
    if root is not None:
        return root / "sector_relationship.sqlite3"
    configured = os.getenv("MOSAIC_SECTOR_ARCHIVE_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(".mosaic") / "agent_data" / "sector_relationship.sqlite3"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-qualified")
    return parsed


def _capture_now() -> datetime:
    return datetime.now(tz=_SHANGHAI)


def _fetch_page(
    fetch: Callable[..., Any],
    endpoint: str,
    request: Mapping[str, Any],
    *,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    for attempt in range(len(_EMPTY_RESPONSE_BACKOFF_SECONDS) + 1):
        rows = _response_rows(
            fetch(endpoint, **dict(request), limit=_PAGE_SIZE, offset=offset)
        )
        if rows or attempt == len(_EMPTY_RESPONSE_BACKOFF_SECONDS):
            return rows, attempt + 1
        wall_time.sleep(_EMPTY_RESPONSE_BACKOFF_SECONDS[attempt])
    raise AssertionError("empty-page confirmation attempts exhausted")


def _paginate_incremental(
    fetch: Callable[..., Any],
    endpoint: str,
    request: Mapping[str, Any],
    *,
    confirm_terminal: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    evidence = PREFLIGHT_ENDPOINT_CHECKS.get(endpoint)
    if evidence is None:
        raise AShareSchemaError(f"{endpoint} has no frozen preflight schema evidence")
    required_columns = frozenset(evidence["expected_columns"])
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate_count = 0
    call_count = 0
    for page in range(_MAX_PAGES_PER_QUERY):
        page_rows, page_calls = _fetch_page(
            fetch,
            endpoint,
            request,
            offset=page * _PAGE_SIZE,
        )
        call_count += page_calls
        for row in page_rows:
            missing = required_columns - set(row)
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
        if len(page_rows) < _PAGE_SIZE:
            if page_rows and confirm_terminal:
                probe_rows, probe_calls = _fetch_page(
                    fetch,
                    endpoint,
                    request,
                    offset=page * _PAGE_SIZE + len(page_rows),
                )
                call_count += probe_calls
                if probe_rows:
                    raise ASharePaginationError(
                        f"{endpoint} returned rows after a terminal short page"
                    )
            return rows, call_count, duplicate_count
    raise ASharePaginationError(f"{endpoint} did not return a terminal short page")


@dataclass(frozen=True)
class SectorArchiveResult:
    source_receipts: tuple[SourceCaptureReceipt, ...]
    coverage_receipt: RouteCoverageReceipt
    cache_hit: bool
    group: dict[str, Any] | None


class SectorArchiveStore:
    """Append-only compressed groups serialized by capture key."""

    def __init__(self, path: Path | None = None, *, create: bool = True) -> None:
        self.path = path or sector_archive_path()
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
                timeout=_LOCK_TIMEOUT_SECONDS,
                isolation_level=None,
            )
            conn.execute(f"PRAGMA busy_timeout = {_LOCK_TIMEOUT_SECONDS * 1000}")
            conn.execute("PRAGMA journal_mode = DELETE")
        conn.row_factory = sqlite3.Row
        return conn

    def _initialise(self) -> None:
        self._available = True
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sector_capture_groups (
                    capture_key TEXT PRIMARY KEY,
                    group_hash TEXT NOT NULL UNIQUE,
                    as_of_date TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    payload_zlib BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sector_capture_as_of
                  ON sector_capture_groups(as_of_date, captured_at);
                CREATE TRIGGER IF NOT EXISTS sector_capture_no_update
                  BEFORE UPDATE ON sector_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS sector_capture_no_delete
                  BEFORE DELETE ON sector_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(zlib.decompress(row["payload_zlib"]).decode("utf-8"))
        if canonical_hash(payload) != row["group_hash"]:
            raise ValueError("sector archive group hash mismatch")
        return payload

    def get_or_capture(
        self, capture_key: str, builder: Callable[[], dict[str, Any]]
    ) -> tuple[dict[str, Any], bool]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM sector_capture_groups WHERE capture_key = ?",
                    (capture_key,),
                ).fetchone()
                if row is not None:
                    payload = self._decode(row)
                    conn.execute("COMMIT")
                    return payload, True
                payload = builder()
                encoded = _canonical_json(payload).encode("utf-8")
                conn.execute(
                    "INSERT INTO sector_capture_groups "
                    "(capture_key, group_hash, as_of_date, captured_at, payload_zlib) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        capture_key,
                        canonical_hash(payload),
                        payload["as_of_date"],
                        payload["captured_at"],
                        zlib.compress(encoded, level=9),
                    ),
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return payload, False

    def load_group(self, as_of_date: str) -> dict[str, Any]:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM sector_capture_groups WHERE as_of_date = ? "
                "ORDER BY captured_at DESC LIMIT 1",
                (as_of_date,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"no sector capture group for {as_of_date}")
            return self._decode(row)

    def row_count(self) -> int:
        with self._connect(read_only=True) as conn:
            return int(conn.execute("SELECT count(*) FROM sector_capture_groups").fetchone()[0])


def _retime_batch(batch: dict[str, Any], captured_at: str) -> None:
    batch["captured_at"] = captured_at
    batch["released_at"] = captured_at
    batch["vintage_at"] = captured_at
    batch["rows_hash"] = canonical_hash(batch["rows"])
    body = {key: value for key, value in batch.items() if key not in {"rows", "source_batch_id", "source_batch_hash"}}
    batch_hash = canonical_hash(body)
    batch["source_batch_hash"] = batch_hash
    batch["source_batch_id"] = "sector-source-batch:" + batch_hash.removeprefix("sha256:")


def _seal_batch(
    *,
    endpoint: str,
    requests: Sequence[Mapping[str, Any]],
    request_contract: Mapping[str, Any],
    fetch: Callable[..., Any],
    captured_at: str,
    require_each_nonempty: bool,
    confirm_terminal: bool,
    row_filter: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[dict[str, Any], int, int]:
    if not requests:
        raise DataVendorUnavailable(f"{endpoint} capture requires at least one request")
    pagination_policy = (
        PAGINATION_POLICY_TERMINAL_CONFIRMED
        if confirm_terminal
        else PAGINATION_POLICY_OFFICIAL_CAP
    )
    if SOURCE_BATCH_PAGINATION_POLICIES.get(endpoint) != pagination_policy:
        raise ValueError(f"{endpoint} pagination proof does not match its contract")
    rows: list[dict[str, Any]] = []
    page_count = 0
    duplicate_count = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(requests))) as pool:
        futures = [
            pool.submit(
                _paginate_incremental,
                fetch,
                endpoint,
                request,
                confirm_terminal=confirm_terminal,
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
                for field in (
                    "ts_code",
                    "trade_date",
                    "market",
                    "is_new",
                    "l1_code",
                    "l2_code",
                    "l3_code",
                ):
                    if field in request and any(
                        str(row.get(field)) != str(request[field])
                        for row in leaf_rows
                    ):
                        raise AShareSchemaError(
                            f"{endpoint} returned rows outside requested {field}"
                        )
                rows.extend(
                    row
                    for row in leaf_rows
                    if row_filter is None or row_filter(row)
                )
                page_count += leaf_pages
                duplicate_count += leaf_duplicates
        except Exception:
            for future in futures:
                future.cancel()
            raise
    registration = endpoint_registration(endpoint)
    body: dict[str, Any] = {
        "source_id": f"tushare.{endpoint}",
        "endpoint": endpoint,
        "schema_contract_version": registration.schema_contract_version,
        "request": dict(request_contract),
        "captured_at": captured_at,
        "released_at": captured_at,
        "vintage_at": captured_at,
        "pit_status": "PIT_VERIFIED",
        "pagination_complete": True,
        "pagination_policy": pagination_policy,
        "truncated": False,
        "query_count": len(requests),
        "completed_query_count": len(requests),
        "coverage_ratio": 1.0,
        "rows": rows,
        "rows_hash": canonical_hash(rows),
    }
    hash_body = {key: value for key, value in body.items() if key != "rows"}
    batch_hash = canonical_hash(hash_body)
    body["source_batch_hash"] = batch_hash
    body["source_batch_id"] = "sector-source-batch:" + batch_hash.removeprefix("sha256:")
    return body, duplicate_count, page_count


def _validate_moneyflow_daily_closure(
    *,
    base_batches: Sequence[Mapping[str, Any]],
    moneyflow_batch: Mapping[str, Any],
    sessions: Sequence[str],
) -> None:
    daily = next(
        (batch for batch in base_batches if batch.get("endpoint") == "daily"), None
    )
    if daily is None:
        raise AShareSchemaError("moneyflow closure requires the parent daily batch")
    session_set = {str(session).replace("-", "") for session in sessions}
    daily_keys = {
        (str(row.get("trade_date", "")).replace("-", ""), str(row.get("ts_code", "")))
        for row in daily.get("rows", ())
    }
    moneyflow_keys = {
        (str(row.get("trade_date", "")).replace("-", ""), str(row.get("ts_code", "")))
        for row in moneyflow_batch.get("rows", ())
    }
    malformed = {
        key
        for key in moneyflow_keys
        if not key[0] or not key[1] or key[0] not in session_set
    }
    outside_daily = moneyflow_keys - daily_keys
    if malformed or outside_daily:
        raise AShareSchemaError(
            "moneyflow rows are outside the requested parent daily session/code domain"
        )


def _membership_batches(
    fetch: Callable[..., Any], captured_at: str
) -> tuple[list[dict[str, Any]], int, int]:
    specs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for plan in SECTOR_UNIVERSE_MANIFEST["membership_query_plans"]:
        for branch in plan["branches"]:
            specs.append(
                (
                    {
                        branch["parameter"]: branch["classification_code"],
                        "is_new": branch["is_new"],
                    },
                    {
                        "query_plan_hash": plan["query_plan_hash"],
                        "parameter": branch["parameter"],
                        "classification_code": branch["classification_code"],
                        "is_new": branch["is_new"],
                    },
                )
            )
    batches: list[dict[str, Any]] = []
    pages = 0
    duplicates = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = [
            pool.submit(
                _seal_batch,
                endpoint="index_member_all",
                requests=(transport,),
                request_contract=contract,
                fetch=fetch,
                captured_at=captured_at,
                require_each_nonempty=False,
                confirm_terminal=True,
            )
            for transport, contract in specs
        ]
        for future in futures:
            batch, duplicate_count, page_count = future.result()
            batches.append(batch)
            duplicates += duplicate_count
            pages += page_count
    return batches, duplicates, pages


def _active_security_codes(
    batches: Sequence[Mapping[str, Any]], as_of: date
) -> list[str]:
    codes: set[str] = set()
    for batch in batches:
        for row in batch["rows"]:
            in_date = datetime.strptime(str(row["in_date"]).replace("-", ""), "%Y%m%d").date()
            out_value = row.get("out_date")
            out_date = (
                datetime.strptime(str(out_value).replace("-", ""), "%Y%m%d").date()
                if out_value not in (None, "")
                else None
            )
            if in_date <= as_of and (out_date is None or out_date > as_of):
                codes.add(str(row["ts_code"]))
    if not codes:
        raise DataVendorUnavailable("sector membership capture has no active securities")
    return sorted(codes)


def _attach_parent_batches(
    group: Mapping[str, Any], base_group: Mapping[str, Any]
) -> dict[str, Any]:
    if group.get("base_group_hash") != canonical_hash(base_group):
        raise DataVendorUnavailable("sector raw group parent hash mismatch")
    parent_batches = {
        batch["endpoint"]: batch
        for batch in base_group.get("batches", ())
        if batch.get("endpoint") in _BASE_ENDPOINTS
    }
    if set(parent_batches) != _BASE_ENDPOINTS:
        raise DataVendorUnavailable("sector parent A-share batches are incomplete")
    batches = [dict(batch) for batch in group.get("batches", ())]
    observed = {batch["endpoint"]: batch for batch in batches}
    for endpoint, parent_batch in parent_batches.items():
        existing = observed.get(endpoint)
        if existing is not None and existing != parent_batch:
            raise DataVendorUnavailable("sector raw group parent batch mismatch")
        if existing is None:
            batches.append(dict(parent_batch))
    result = {**group, "batches": batches}
    result["normalized_row_count"] = sum(
        len(batch["rows"]) for batch in result["batches"]
    )
    return result


def _build_capture_group(
    fetch: Callable[..., Any],
    *,
    as_of_date: date,
    cutoff_at: str,
    capture_key: str,
    base_group: Mapping[str, Any],
) -> dict[str, Any]:
    for endpoint in _INCREMENTAL_ENDPOINTS:
        assert_endpoint_capture_preflight_allowed(endpoint)
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    started = _capture_now()
    local_started = started.astimezone(_SHANGHAI)
    if (
        started > cutoff
        or local_started.date() != as_of_date
        or local_started.time() <= _MARKET_CLOSE
    ):
        raise DataVendorUnavailable("sector capture is outside the post-close window")
    if base_group.get("as_of_date") != as_of_date.isoformat():
        raise DataVendorUnavailable("sector capture parent A-share group as_of mismatch")
    sessions = list(base_group.get("sessions", ()))
    base_batches = [
        dict(batch)
        for batch in base_group.get("batches", ())
        if batch.get("endpoint") in _BASE_ENDPOINTS
    ]
    if {batch["endpoint"] for batch in base_batches} != _BASE_ENDPOINTS:
        raise DataVendorUnavailable("sector capture parent A-share batches are incomplete")
    started_at = started.isoformat()
    membership, membership_duplicates, membership_pages = _membership_batches(
        fetch, started_at
    )
    security_codes = _active_security_codes(membership, as_of_date)
    statement_start = (as_of_date - timedelta(days=1100)).strftime("%Y%m%d")
    api_as_of = as_of_date.strftime("%Y%m%d")
    batches: list[dict[str, Any]] = [*base_batches, *membership]
    page_counts = {"index_member_all": membership_pages}
    duplicate_counts = {"index_member_all": membership_duplicates}

    specs = (
        (
            "moneyflow",
            tuple({"trade_date": session} for session in sessions),
            {"start_date": sessions[0], "end_date": sessions[-1]},
            True,
            True,
        ),
        (
            "income",
            tuple(
                {"ts_code": code, "start_date": statement_start, "end_date": api_as_of}
                for code in security_codes
            ),
            {"end_date": as_of_date.isoformat()},
            False,
            False,
        ),
        (
            "cashflow",
            tuple(
                {"ts_code": code, "start_date": statement_start, "end_date": api_as_of}
                for code in security_codes
            ),
            {"end_date": as_of_date.isoformat()},
            False,
            False,
        ),
        (
            "balancesheet",
            tuple(
                {"ts_code": code, "start_date": statement_start, "end_date": api_as_of}
                for code in security_codes
            ),
            {"end_date": as_of_date.isoformat()},
            False,
            False,
        ),
        (
            "fund_basic",
            ({"market": "E"},),
            {"market": "E"},
            True,
            True,
        ),
        (
            "top10_holders",
            tuple(
                {"ts_code": code, "start_date": statement_start, "end_date": api_as_of}
                for code in security_codes
            ),
            {"end_date": as_of_date.isoformat()},
            False,
            False,
        ),
    )
    for endpoint, requests, request_contract, require_nonempty, confirm_terminal in specs:
        batch, duplicates, pages = _seal_batch(
            endpoint=endpoint,
            requests=requests,
            request_contract=request_contract,
            fetch=fetch,
            captured_at=started_at,
            require_each_nonempty=require_nonempty,
            confirm_terminal=confirm_terminal,
        )
        if endpoint == "moneyflow":
            _validate_moneyflow_daily_closure(
                base_batches=base_batches,
                moneyflow_batch=batch,
                sessions=sessions,
            )
        if endpoint == "top10_holders" and not batch["rows"]:
            raise DataVendorUnavailable("relationship capture has no holder disclosures")
        batches.append(batch)
        page_counts[endpoint] = pages
        duplicate_counts[endpoint] = duplicates

    etf_codes = sorted(
        {
            code
            for role, direction_ids in SECTOR_DIRECTION_IDS.items()
            for direction_id in direction_ids
            for code in _authoritative_etf_codes(role, direction_id, as_of_date)
        }
    )
    if etf_codes:
        etf_code_set = set(etf_codes)

        def is_authority_etf(row: dict[str, Any]) -> bool:
            return str(row.get("ts_code")) in etf_code_set

        for endpoint in sorted(SECTOR_ETF_SOURCE_ENDPOINTS - {"fund_basic"}):
            assert_endpoint_capture_preflight_allowed(endpoint)
            if endpoint in {"fund_daily", "fund_adj"}:
                requests = tuple({"trade_date": session} for session in sessions)
                row_filter = is_authority_etf
            else:
                requests = tuple(
                    {"ts_code": code, "start_date": statement_start, "end_date": api_as_of}
                    for code in etf_codes
                )
                row_filter = None
            batch, duplicates, pages = _seal_batch(
                endpoint=endpoint,
                requests=requests,
                request_contract={"end_date": as_of_date.isoformat()},
                fetch=fetch,
                captured_at=started_at,
                require_each_nonempty=False,
                confirm_terminal=True,
                row_filter=row_filter,
            )
            batches.append(batch)
            page_counts[endpoint] = pages
            duplicate_counts[endpoint] = duplicates

        portfolio, duplicates, pages = _seal_batch(
            endpoint="fund_portfolio",
            requests=tuple({"ts_code": code} for code in etf_codes),
            request_contract={
                "end_date": as_of_date.isoformat(),
                "ts_codes": etf_codes,
            },
            fetch=fetch,
            captured_at=started_at,
            require_each_nonempty=True,
            confirm_terminal=True,
            row_filter=lambda row: str(row.get("ann_date", "")) <= api_as_of
            and str(row.get("end_date", "")) <= api_as_of,
        )
        batches.append(portfolio)
        page_counts["fund_portfolio"] = pages
        duplicate_counts["fund_portfolio"] = duplicates

    completed = _capture_now()
    local_completed = completed.astimezone(_SHANGHAI)
    if (
        completed > cutoff
        or local_completed.date() != as_of_date
        or local_completed.time() <= _MARKET_CLOSE
    ):
        raise DataVendorUnavailable("sector capture completed outside the post-close window")
    completed_at = completed.isoformat()
    for batch in batches:
        if batch["endpoint"] not in _BASE_ENDPOINTS:
            _retime_batch(batch, completed_at)
    group = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "capture_key": capture_key,
        "as_of_date": as_of_date.isoformat(),
        "cutoff_at": cutoff_at,
        "captured_at": completed_at,
        "base_group_hash": canonical_hash(base_group),
        "sessions": sessions,
        "batches": batches,
        "page_count": sum(page_counts.values()),
        "normalized_row_count": sum(len(batch["rows"]) for batch in batches),
        "page_counts": page_counts,
        "duplicate_counts": duplicate_counts,
    }
    return group


def sector_source_batches(
    group: Mapping[str, Any], role: str
) -> list[dict[str, Any]]:
    plan = next(
        row
        for row in SECTOR_UNIVERSE_MANIFEST["membership_query_plans"]
        if row["sector_agent_id"] == role
    )
    required = SECTOR_REQUIRED_SOURCE_ENDPOINTS
    if any(_authoritative_etf_codes(role, direction, date.fromisoformat(group["as_of_date"])) for direction in SECTOR_DIRECTION_IDS[role]):
        required = required | SECTOR_ETF_SOURCE_ENDPOINTS
    return [
        dict(batch)
        for batch in group["batches"]
        if batch["endpoint"] in required
        and (
            batch["endpoint"] != "index_member_all"
            or batch["request"].get("query_plan_hash") == plan["query_plan_hash"]
        )
    ]


def relationship_source_batches(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(batch)
        for batch in group["batches"]
        if batch["endpoint"] in RELATIONSHIP_REQUIRED_SOURCE_ENDPOINTS
    ]


def compile_sector_archive_group(group: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    as_of_date = str(group["as_of_date"])
    snapshots = {
        role: compile_registered_sector_snapshot(
            role=role,
            as_of_date=as_of_date,
            source_batches=sector_source_batches(group, role),
        )
        for role in SECTOR_DIRECTION_IDS
    }
    snapshots["relationship_mapper"] = compile_registered_relationship_snapshot(
        as_of_date=as_of_date,
        source_batches=relationship_source_batches(group),
    )
    return snapshots


def _source_receipt(group: Mapping[str, Any], route_id: str) -> SourceCaptureReceipt:
    captured_at = str(group["captured_at"])
    request = {
        "as_of_date": group["as_of_date"],
        "base_group_hash": group["base_group_hash"],
        "route_id": route_id,
    }
    return SourceCaptureReceipt.seal(
        {
            "schema_version": "source_capture_receipt_v1",
            "identity": {
                "source_family": "tushare",
                "route_id": route_id,
                "request_hash": canonical_hash(request),
                "capture_id": "sector-capture:"
                + canonical_hash({"capture_key": group["capture_key"], "route_id": route_id}).removeprefix("sha256:"),
            },
            "transport": {
                "redacted_url": "https://api.tushare.pro/sector-relationship",
                "method": "POST",
                "query_keys": [
                    "end_date",
                    "is_new",
                    "limit",
                    "market",
                    "offset",
                    "start_date",
                    "trade_date",
                    "ts_code",
                ],
                "pagination_policy": "ENDPOINT_SPECIFIC_COMPLETENESS_V1",
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
                "normalized_row_count": int(group["normalized_row_count"]),
                "schema_hash": canonical_hash(
                    {"schema_version": group["schema_version"], "route_id": route_id}
                ),
            },
            "coverage": {
                "requested_start": group["as_of_date"],
                "requested_end": group["as_of_date"],
                "observed_start": group["as_of_date"],
                "observed_end": group["as_of_date"],
                "dimensions": {"logical_route": [route_id]},
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": int(
                    sum(group.get("duplicate_counts", {}).values())
                ),
                "empty_result_semantics": "NON_EMPTY",
            },
            "provenance": {
                "parent_capture_hash": group["base_group_hash"],
                "previous_revision_hash": None,
                "revision_reason": None,
            },
        }
    )


def sector_archive_source_receipt(
    group: Mapping[str, Any], route_id: str
) -> SourceCaptureReceipt:
    """Rebuild and validate the logical receipt for one archived query route."""

    if route_id not in LOGICAL_ROUTES:
        raise ValueError(f"unsupported Sector archive route: {route_id}")
    return _source_receipt(group, route_id)


def _coverage_receipt(
    *,
    as_of_date: str,
    cutoff_at: str,
    source_receipts: Sequence[SourceCaptureReceipt],
    status: str,
    blocker_codes: Sequence[str],
) -> RouteCoverageReceipt:
    hashes = {
        receipt.as_dict()["identity"]["route_id"]: receipt.receipt_hash
        for receipt in source_receipts
    }
    route_results = [
        {
            "route_id": route_id,
            "capture_receipt_hash": hashes.get(route_id),
            "status": status,
        }
        for route_id in LOGICAL_ROUTES
    ]
    coverage_id = "sector-coverage:" + canonical_hash(
        {
            "as_of_date": as_of_date,
            "cutoff_at": cutoff_at,
            "route_results": route_results,
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
            "required_route_ids": list(LOGICAL_ROUTES),
            "route_results": route_results,
            "coverage_complete": status == "SUCCESS",
            "blocker_codes": sorted(blocker_codes),
        }
    )


def _failed_result(
    *,
    as_of_date: str,
    cutoff_at: str,
    ledger: AgentDataMaterializationLedger,
    status: str,
    blocker: str,
) -> SectorArchiveResult:
    coverage = _coverage_receipt(
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        source_receipts=(),
        status=status,
        blocker_codes=(blocker,),
    )
    ledger.append_route_coverage(coverage)
    return SectorArchiveResult((), coverage, False, None)


def archive_sector_relationship(
    fetch: Callable[..., Any],
    *,
    as_of_date: str,
    cutoff_at: str,
    base_store: AShareArchiveStore,
    store: SectorArchiveStore,
    ledger: AgentDataMaterializationLedger,
) -> SectorArchiveResult:
    """Capture all PR4 physical routes once and publish three logical receipts."""
    as_of = date.fromisoformat(as_of_date)
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    cutoff_local = cutoff.astimezone(_SHANGHAI)
    if cutoff_local.date() != as_of or cutoff_local.time() <= _MARKET_CLOSE:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="MARKET_SESSION_INCOMPLETE",
        )
    try:
        base_group = base_store.load_group(as_of_date)
        if (
            base_group.get("schema_version") != "a_share_capture_group_v1"
            or base_group.get("as_of_date") != as_of_date
        ):
            raise DataVendorUnavailable("invalid parent A-share capture group")
        capture_key = canonical_hash(
            {
                "schema_version": CAPTURE_SCHEMA_VERSION,
                "as_of_date": as_of_date,
                "cutoff_at": cutoff.isoformat(),
                "base_group_hash": canonical_hash(base_group),
                "manifest_hash": SECTOR_UNIVERSE_MANIFEST["manifest_hash"],
            }
        )
        group, cache_hit = store.get_or_capture(
            capture_key,
            lambda: _build_capture_group(
                fetch,
                as_of_date=as_of,
                cutoff_at=cutoff.isoformat(),
                capture_key=capture_key,
                base_group=base_group,
            ),
        )
        compile_group = _attach_parent_batches(group, base_group)
        snapshots = compile_sector_archive_group(compile_group)
        result_group = {
            **compile_group,
            "compiled_snapshot_hashes": {
                role: snapshot["snapshot_hash"]
                for role, snapshot in snapshots.items()
            },
        }
        sources = tuple(
            _source_receipt(compile_group, route_id) for route_id in LOGICAL_ROUTES
        )
        coverage = _coverage_receipt(
            as_of_date=as_of_date,
            cutoff_at=cutoff.isoformat(),
            source_receipts=sources,
            status="SUCCESS",
            blocker_codes=(),
        )
        ledger.append_capture_group(sources, coverage)
        return SectorArchiveResult(sources, coverage, cache_hit, result_group)
    except PermissionError:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="PERMISSION_DENIED",
            blocker="PERMISSION_DENIED",
        )
    except (TimeoutError, ConnectionError):
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
    except AShareSchemaError:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="SCHEMA_DRIFT",
            blocker="SCHEMA_DRIFT",
        )
    except (DataVendorUnavailable, FileNotFoundError):
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="INCOMPLETE_COVERAGE",
        )
    except Exception:  # noqa: BLE001 - redact unknown vendor failures
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="CAPTURE_REJECTED",
        )


__all__ = [
    "CAPTURE_SCHEMA_VERSION",
    "LOGICAL_ROUTES",
    "SectorArchiveResult",
    "SectorArchiveStore",
    "archive_sector_relationship",
    "compile_sector_archive_group",
    "relationship_source_batches",
    "sector_archive_path",
    "sector_archive_source_receipt",
    "sector_source_batches",
]

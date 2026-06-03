"""Permanent cache for agent tool data.

The cache is intentionally generic: it stores the exact result returned by
``route_to_vendor(method, *args, **kwargs)`` keyed by the method name, the
date-clamped arguments, the selected vendor fallback chain, and any active
runtime context such as a backtest as-of date. That makes every agent tool
cache-first without adding vendor-specific code to each dataflow module, while
still respecting vendor configuration changes and historical replay boundaries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from time import time
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 3
_DEFAULT_READ_TTL_SECONDS = 24 * 3600
_DEFAULT_MAX_ENTRIES = 50_000
_SCHEMA_INIT_LOCK = threading.Lock()
_SCHEMA_INITIALISED_PATHS: set[str] = set()
_EMPTY_TEXT_MARKERS = (
    "no data found",
    "no data returned",
    "no data available",
    "no rows",
    "no results",
    "no news found",
    "no relevant news found",
    "data unavailable",
    "not available",
)
_EMPTY_LINE_TERMS = (
    "available",
    "data",
    "entries",
    "found",
    "news",
    "observations",
    "recorded",
    "records",
    "results",
    "returned",
    "rows",
)


@dataclass(frozen=True)
class CacheLookup:
    hit: bool
    value: Any = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _as_ttl_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped in {"", "none", "null", "off", "disabled"}:
            return None
        value = stripped
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_READ_TTL_SECONDS
    return seconds if seconds >= 0 else None


def _as_max_entries(value: Any) -> int | None:
    if value is None:
        return _DEFAULT_MAX_ENTRIES
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped in {"", "none", "null", "off", "disabled"}:
            return None
        value = stripped
    try:
        entries = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_ENTRIES
    return entries if entries > 0 else None


def _is_empty_result(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return _is_empty_text_result(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    return False


def _is_empty_text_result(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if lowered in {"[]", "{}", "null", "none"}:
        return True

    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        decoded = None
    else:
        return _is_empty_result(decoded)

    non_comment_lines = [
        line.strip()
        for line in stripped.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not non_comment_lines:
        return True

    meaningful_lines = [
        line
        for line in non_comment_lines
        if not _is_empty_explanation_line(line) and not _is_non_data_disclaimer_line(line)
    ]
    if not meaningful_lines:
        return True

    if _looks_like_header_only_csv(stripped, meaningful_lines):
        return True

    return False


def _is_empty_explanation_line(line: str) -> bool:
    lowered = line.strip().lower().rstrip(".")
    if any(marker in lowered for marker in _EMPTY_TEXT_MARKERS):
        return True
    return lowered.startswith("no ") and any(term in lowered for term in _EMPTY_LINE_TERMS)


def _is_non_data_disclaimer_line(line: str) -> bool:
    lowered = line.strip().lower()
    return "数据说明" in lowered or "strictly only" in lowered


def _looks_like_header_only_csv(text: str, meaningful_lines: list[str]) -> bool:
    if len(meaningful_lines) != 1 or "," not in meaningful_lines[0]:
        return False
    if not any(line.strip().startswith("#") for line in text.splitlines()):
        return False
    fields = [field.strip().lower() for field in meaningful_lines[0].split(",")]
    if len(fields) < 2:
        return False
    known_columns = {
        "date",
        "trade_date",
        "value",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "symbol",
        "ticker",
        "ts_code",
    }
    return bool(set(fields) & known_columns)


def _normalise(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _normalise(value[k]) for k in sorted(value)}
    return repr(value)


def _canonical_request(
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    vendor_chain: list[str],
    runtime_context: dict[str, Any] | None = None,
) -> str:
    return json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "method": method,
            "args": _normalise(args),
            "kwargs": _normalise(kwargs),
            "vendor_chain": _normalise(vendor_chain),
            "runtime_context": _normalise(runtime_context or {}),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def cache_key(
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    vendor_chain: list[str],
    runtime_context: dict[str, Any] | None = None,
) -> str:
    request_json = _canonical_request(
        method,
        args,
        kwargs,
        vendor_chain=vendor_chain,
        runtime_context=runtime_context,
    )
    return hashlib.sha256(request_json.encode("utf-8")).hexdigest()


def _encode_result(value: Any) -> tuple[str, str] | None:
    if isinstance(value, str):
        return "text", value
    try:
        return (
            "json",
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
    except TypeError:
        return None


def _decode_result(result_format: str, payload: str) -> Any:
    if result_format == "text":
        return payload
    if result_format == "json":
        return json.loads(payload)
    raise ValueError(f"unknown cached result format: {result_format}")


class AgentDataCache:
    """SQLite-backed exact-call cache for routed agent data."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        read_ttl_seconds: int | None = _DEFAULT_READ_TTL_SECONDS,
        max_entries: int | None = _DEFAULT_MAX_ENTRIES,
        skip_empty_results: bool = True,
    ) -> None:
        self.db_path = Path(db_path).expanduser()
        self.read_ttl_seconds = read_ttl_seconds
        self.max_entries = max_entries
        self.skip_empty_results = skip_empty_results

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "AgentDataCache | None":
        cache_cfg = dict(config.get("agent_data_cache") or {})
        if not _as_bool(cache_cfg.get("enabled"), True):
            return None
        db_path = cache_cfg.get("db_path")
        if not db_path:
            db_path = Path(config["data_cache_dir"]) / "agent_data" / "cache.sqlite3"
        ttl = _as_ttl_seconds(cache_cfg.get("read_ttl_seconds", _DEFAULT_READ_TTL_SECONDS))
        max_entries = _as_max_entries(cache_cfg.get("max_entries", _DEFAULT_MAX_ENTRIES))
        skip_empty_results = _as_bool(cache_cfg.get("skip_empty_results"), True)
        return cls(
            db_path,
            read_ttl_seconds=ttl,
            max_entries=max_entries,
            skip_empty_results=skip_empty_results,
        )

    def get(
        self,
        method: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        vendor_chain: list[str],
        runtime_context: dict[str, Any] | None = None,
    ) -> CacheLookup:
        key = cache_key(
            method,
            args,
            kwargs,
            vendor_chain=vendor_chain,
            runtime_context=runtime_context,
        )
        now = _now_iso()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT result_format, result_payload, updated_at
                  FROM agent_data_cache
                 WHERE cache_key = ?
                """,
                (key,),
            ).fetchone()
            if row is None:
                return CacheLookup(hit=False)
            if self._is_stale(row["updated_at"], now):
                return CacheLookup(hit=False)
            conn.execute(
                """
                UPDATE agent_data_cache
                   SET access_count = access_count + 1,
                       last_accessed_at = ?
                 WHERE cache_key = ?
                """,
                (now, key),
            )
            return CacheLookup(hit=True, value=_decode_result(row["result_format"], row["result_payload"]))

    def _is_stale(self, updated_at: str, now_iso: str) -> bool:
        if self.read_ttl_seconds is None:
            return False
        try:
            updated = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
            now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        except ValueError:
            return True
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return (now - updated).total_seconds() >= self.read_ttl_seconds

    def set(
        self,
        method: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        value: Any,
        *,
        vendor: str | None,
        vendor_chain: list[str],
        runtime_context: dict[str, Any] | None = None,
    ) -> bool:
        if self.skip_empty_results and _is_empty_result(value):
            logger.debug("agent data cache skipped empty result for %s", method)
            return False

        encoded = _encode_result(value)
        if encoded is None:
            logger.debug("agent data cache skipped unsupported result for %s", method)
            return False

        result_format, payload = encoded
        request_json = _canonical_request(
            method,
            args,
            kwargs,
            vendor_chain=vendor_chain,
            runtime_context=runtime_context,
        )
        key = cache_key(
            method,
            args,
            kwargs,
            vendor_chain=vendor_chain,
            runtime_context=runtime_context,
        )
        now = _now_iso()
        payload_bytes = len(payload.encode("utf-8"))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_data_cache(
                    cache_key,
                    method,
                    request_json,
                    args_json,
                    kwargs_json,
                    result_format,
                    result_payload,
                    result_bytes,
                    vendor,
                    vendor_chain_json,
                    created_at,
                    updated_at,
                    last_accessed_at,
                    access_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)
                ON CONFLICT(cache_key) DO UPDATE SET
                    result_format = excluded.result_format,
                    result_payload = excluded.result_payload,
                    result_bytes = excluded.result_bytes,
                    vendor = excluded.vendor,
                    vendor_chain_json = excluded.vendor_chain_json,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    method,
                    request_json,
                    json.dumps(_normalise(args), ensure_ascii=False, sort_keys=True),
                    json.dumps(_normalise(kwargs), ensure_ascii=False, sort_keys=True),
                    result_format,
                    payload,
                    payload_bytes,
                    vendor,
                    json.dumps(vendor_chain, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._enforce_max_entries(conn)
        return True

    def _enforce_max_entries(self, conn: sqlite3.Connection) -> None:
        if self.max_entries is None:
            return
        count = conn.execute("SELECT COUNT(*) FROM agent_data_cache").fetchone()[0]
        overflow = int(count) - self.max_entries
        if overflow <= 0:
            return
        conn.execute(
            """
            DELETE FROM agent_data_cache
             WHERE cache_key IN (
                SELECT cache_key
                  FROM agent_data_cache
                 ORDER BY COALESCE(last_accessed_at, updated_at, created_at) ASC,
                          updated_at ASC,
                          cache_key ASC
                 LIMIT ?
             )
            """,
            (overflow,),
        )

    def stats(self) -> dict[str, Any]:
        if not self.db_path.is_file():
            return {"entries": 0, "size_mb": 0.0, "by_method": {}}
        with self._connect() as conn:
            entries = conn.execute("SELECT COUNT(*) FROM agent_data_cache").fetchone()[0]
            rows = conn.execute(
                "SELECT method, COUNT(*) AS n FROM agent_data_cache GROUP BY method ORDER BY method"
            ).fetchall()
        size_mb = self.db_path.stat().st_size / (1024 * 1024)
        return {
            "entries": entries,
            "size_mb": round(size_mb, 2),
            "by_method": {row["method"]: row["n"] for row in rows},
        }

    def clear(self) -> int:
        if not self.db_path.is_file():
            return 0
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM agent_data_cache").fetchone()[0]
            conn.execute("DELETE FROM agent_data_cache")
        return int(count)

    def cleanup(self, days: int) -> tuple[int, float]:
        if not self.db_path.is_file():
            return 0, 0.0
        if days == 0:
            return self.drop_database()
        cutoff = datetime.fromtimestamp(time() - days * 86400, timezone.utc).replace(microsecond=0).isoformat()
        before_bytes = self._database_size_bytes()
        with self._connect() as conn:
            before = conn.execute("SELECT COUNT(*) FROM agent_data_cache").fetchone()[0]
            conn.execute("DELETE FROM agent_data_cache WHERE updated_at < ?", (cutoff,))
            after = conn.execute("SELECT COUNT(*) FROM agent_data_cache").fetchone()[0]
            deleted = int(before - after)
            if deleted:
                conn.commit()
                conn.execute("VACUUM")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        after_bytes = self._database_size_bytes()
        return deleted, max(0, before_bytes - after_bytes) / (1024 * 1024)

    def drop_database(self) -> tuple[int, float]:
        count = 0
        total_bytes = 0
        if self.db_path.is_file():
            try:
                with self._connect() as conn:
                    count = int(conn.execute("SELECT COUNT(*) FROM agent_data_cache").fetchone()[0])
            except sqlite3.Error:
                count = 0
        for path in (self.db_path, self.db_path.with_suffix(self.db_path.suffix + "-wal"), self.db_path.with_suffix(self.db_path.suffix + "-shm")):
            try:
                if path.is_file():
                    total_bytes += path.stat().st_size
                    path.unlink()
            except OSError:
                continue
        return count, total_bytes / (1024 * 1024)

    def _database_size_bytes(self) -> int:
        total = 0
        for path in (
            self.db_path,
            self.db_path.with_suffix(self.db_path.suffix + "-wal"),
            self.db_path.with_suffix(self.db_path.suffix + "-shm"),
        ):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total

    def details(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        if not self.db_path.is_file():
            return {"total": 0, "page": page, "entries": []}
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM agent_data_cache").fetchone()[0]
            rows = conn.execute(
                """
                SELECT cache_key, method, vendor, result_bytes, updated_at, access_count
                  FROM agent_data_cache
                 ORDER BY updated_at DESC
                 LIMIT ? OFFSET ?
                """,
                (page_size, (page - 1) * page_size),
            ).fetchall()
        entries = [
            {
                "path": f"agent_data:{row['method']}:{row['cache_key'][:12]}",
                "size_kb": round(row["result_bytes"] / 1024, 2),
                "modified": row["updated_at"],
                "vendor": row["vendor"],
                "access_count": row["access_count"],
            }
            for row in rows
        ]
        return {"total": total, "page": page, "entries": entries}

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        db_existed = self.db_path.exists()
        schema_key = str(self.db_path.resolve())
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        if not db_existed or schema_key not in _SCHEMA_INITIALISED_PATHS:
            with _SCHEMA_INIT_LOCK:
                if not db_existed or schema_key not in _SCHEMA_INITIALISED_PATHS:
                    self._initialise_schema(conn)
                    _SCHEMA_INITIALISED_PATHS.add(schema_key)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialise_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_data_cache (
                cache_key TEXT PRIMARY KEY,
                method TEXT NOT NULL,
                request_json TEXT NOT NULL,
                args_json TEXT NOT NULL,
                kwargs_json TEXT NOT NULL,
                result_format TEXT NOT NULL,
                result_payload TEXT NOT NULL,
                result_bytes INTEGER NOT NULL,
                vendor TEXT,
                vendor_chain_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed_at TEXT,
                access_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_data_cache_method ON agent_data_cache(method)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_data_cache_updated ON agent_data_cache(updated_at)"
        )

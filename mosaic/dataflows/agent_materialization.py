"""Trusted contracts and append-only status ledger for Agent data materialization.

This module is deliberately network-free.  Collectors and compilers added by later
changes seal their evidence here; status and dry-run callers only read those sealed
records.  Model-visible ``tools.call`` never imports this module.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Mapping, Sequence, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker

from mosaic.scorecard.canonical_json import canonical_hash


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_ROOT = _REPO_ROOT / "schemas"
AGENT_DATA_ROUTE_MANIFEST_PATH = (
    _REPO_ROOT / "registry" / "data_sources" / "agent_data_route_manifest_v1.json"
)
AGENT_TOOL_CONTRACT_MANIFEST_PATH = (
    _REPO_ROOT / "registry" / "prompt_checks" / "agent_tool_contract_manifest_v1.json"
)

SUCCESSFUL_ROUTE_STATES = {"SUCCESS", "TRUE_EMPTY"}
BLOCKER_CODES = frozenset(
    {
        "CAPTURE_AFTER_AS_OF_CUTOFF",
        "CAPTURE_BEFORE_AS_OF_WINDOW",
        "CAPTURE_REJECTED",
        "INCOMPLETE_COVERAGE",
        "LEAF_AUDIT_INCOMPLETE",
        "LOCK_EXPIRED",
        "LOCK_LOST",
        "LOCK_TIMEOUT",
        "MARKET_SESSION_INCOMPLETE",
        "NO_BUILD_RECEIPT",
        "NO_CAPTURE_RECEIPT",
        "NON_TRADING_DAY",
        "PERMISSION_DENIED",
        "REQUIRED_ROUTE_MISSING",
        "SCHEMA_DRIFT",
        "SNAPSHOT_BUILD_FAILED",
        "STALE_SOURCE",
        "TRANSPORT_FAILED",
        "TRANSPORT_TIMEOUT",
        "TRUNCATED",
        "UNKNOWN_EMPTY_RESULT",
    }
)


def agent_data_materialization_db_path() -> Path:
    explicit = os.getenv("MOSAIC_AGENT_MATERIALIZATION_DB")
    if explicit:
        return Path(explicit).expanduser()
    cache_root = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache_root / "agent_materialization" / "materialization.sqlite3"


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _timestamp(value: Any, field: str) -> datetime:
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _required_sha256(value: Any, field: str) -> str:
    text = _required_text(value, field)
    digest = text.removeprefix("sha256:")
    if (
        not text.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{field} must be a sha256 identifier")
    return text


def _validate_blocker_codes(values: Sequence[str], field: str) -> None:
    unknown = sorted(set(values) - BLOCKER_CODES)
    if unknown:
        raise ValueError(f"{field} contains unknown blocker_codes: {unknown}")


def materialization_lock_key(
    *,
    agent_id: str,
    stage: str,
    as_of: str,
    requested_tool_ids: Sequence[str],
    candidate_scope_hash: str,
    runtime_input_hash: str,
    contract_version: str,
) -> str:
    """Return the canonical lock key shared by equivalent materialization work."""
    tools = list(requested_tool_ids)
    if tools != sorted(set(tools)) or not tools:
        raise ValueError("requested_tool_ids must be non-empty, sorted and unique")
    date.fromisoformat(as_of)
    return canonical_hash(
        {
            "agent_id": _required_text(agent_id, "agent_id"),
            "stage": _required_text(stage, "stage"),
            "as_of": as_of,
            "requested_tool_ids": tools,
            "candidate_scope_hash": _required_sha256(
                candidate_scope_hash, "candidate_scope_hash"
            ),
            "runtime_input_hash": _required_sha256(
                runtime_input_hash, "runtime_input_hash"
            ),
            "contract_version": _required_text(contract_version, "contract_version"),
        }
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return payload


@lru_cache(maxsize=None)
def _schema(name: str) -> dict[str, Any]:
    return _load_json(_SCHEMA_ROOT / f"{name}.schema.json")


def _validate_schema(payload: Mapping[str, Any], schema_name: str) -> None:
    errors = sorted(
        Draft202012Validator(
            _schema(schema_name),
            format_checker=FormatChecker(),
        ).iter_errors(dict(payload)),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "$"
        raise ValueError(
            f"{schema_name} schema violation at {location}: {first.message}"
        )


def _validate_source_capture(payload: Mapping[str, Any]) -> None:
    _validate_schema(payload, "source_capture_receipt_v1")
    identity = payload["identity"]
    route = next(
        (
            route
            for route in load_agent_data_route_manifest()["routes"]
            if route["route_id"] == identity["route_id"]
        ),
        None,
    )
    if route is None or route["source_family"] != identity["source_family"]:
        raise ValueError("source capture identity does not match the route manifest")
    transport = payload["transport"]
    redacted_url = str(transport["redacted_url"]).lower()
    if any(token in redacted_url for token in ("api_key=", "apikey=", "token=", "secret=")):
        raise ValueError("transport.redacted_url contains a credential value")
    query_keys = transport["query_keys"]
    if query_keys != sorted(set(query_keys)):
        raise ValueError("transport.query_keys must be sorted and unique")

    times = payload["time"]
    released_at = _timestamp(times["released_at"], "time.released_at")
    vintage_at = _timestamp(times["vintage_at"], "time.vintage_at")
    captured_at = _timestamp(times["captured_at"], "time.captured_at")
    knowledge_at = _timestamp(
        times["knowledge_available_at"], "time.knowledge_available_at"
    )
    cutoff = _timestamp(payload["pit"]["as_of_cutoff"], "pit.as_of_cutoff")
    if not released_at <= vintage_at <= knowledge_at <= cutoff:
        raise ValueError(
            "source capture time order must satisfy released_at <= vintage_at <= "
            "knowledge_available_at <= as_of_cutoff"
        )

    pit_mode = payload["pit"]["pit_mode"]
    allowed_pit_modes = {
        "AUTHORITATIVE_VINTAGE_REPLAY": {"AUTHORITATIVE_VINTAGE_REPLAY"},
        "FORWARD_ARCHIVE": {"OBSERVED_LIVE"},
        "LOCAL_RUNTIME_AUTHORITY": {"OBSERVED_LIVE"},
        "OBSERVED_LIVE": {"OBSERVED_LIVE"},
    }[route["pit_strategy"]]
    if pit_mode not in allowed_pit_modes:
        raise ValueError(
            "source capture pit mode does not match the route manifest pit strategy"
        )
    blockers = payload["pit"]["blocker_codes"]
    eligible = payload["pit"]["eligible"]
    if blockers != sorted(set(blockers)):
        raise ValueError("pit.blocker_codes must be sorted and unique")
    _validate_blocker_codes(blockers, "pit.blocker_codes")
    if eligible != (not blockers):
        raise ValueError("pit.eligible must be false exactly when blocker_codes exist")
    if pit_mode == "OBSERVED_LIVE":
        expected_knowledge = max(released_at, vintage_at, captured_at)
        if knowledge_at != expected_knowledge:
            raise ValueError(
                "OBSERVED_LIVE knowledge_available_at must equal the latest release, "
                "vintage and capture time"
            )
        if payload["pit"]["vintage_query"] is not None:
            raise ValueError("OBSERVED_LIVE must not declare pit.vintage_query")
    elif pit_mode == "AUTHORITATIVE_VINTAGE_REPLAY":
        vintage_query = payload["pit"]["vintage_query"]
        if not isinstance(vintage_query, dict) or not vintage_query:
            raise ValueError(
                "AUTHORITATIVE_VINTAGE_REPLAY requires a non-empty vintage_query"
            )
        if knowledge_at != max(released_at, vintage_at):
            raise ValueError(
                "AUTHORITATIVE_VINTAGE_REPLAY knowledge_available_at must equal "
                "the latest release or authoritative vintage time"
            )
    else:  # pragma: no cover - owned by JSON schema
        raise ValueError(f"unsupported pit mode: {pit_mode}")

    coverage = payload["coverage"]
    requested_start = date.fromisoformat(coverage["requested_start"])
    requested_end = date.fromisoformat(coverage["requested_end"])
    if requested_end < requested_start:
        raise ValueError("coverage requested_end precedes requested_start")
    observed_values = (coverage["observed_start"], coverage["observed_end"])
    if (observed_values[0] is None) != (observed_values[1] is None):
        raise ValueError("coverage observed dates must both be present or both be null")
    if observed_values[0] is not None and observed_values[1] is not None:
        observed_start = date.fromisoformat(observed_values[0])
        observed_end = date.fromisoformat(observed_values[1])
        if not requested_start <= observed_start <= observed_end <= requested_end:
            raise ValueError("coverage observed dates must fall within the requested range")
    for dimension, values in coverage["dimensions"].items():
        if values != sorted(set(values)):
            raise ValueError(f"coverage dimension {dimension} must be sorted and unique")

    completeness = payload["completeness"]
    row_count = payload["content"]["normalized_row_count"]
    empty_semantics = completeness["empty_result_semantics"]
    if (row_count > 0) != (empty_semantics == "NON_EMPTY"):
        raise ValueError("normalized row count contradicts empty-result semantics")
    if row_count == 0 and observed_values[0] is not None:
        raise ValueError("empty capture must not claim an observed date range")
    incomplete = completeness["truncated"] or completeness["next_page_token_present"]
    if (incomplete or empty_semantics == "UNKNOWN") and eligible:
        raise ValueError("incomplete or unknown-empty capture cannot be PIT eligible")


def _validate_route_coverage(payload: Mapping[str, Any]) -> None:
    _validate_schema(payload, "route_coverage_receipt_v1")
    start = _timestamp(payload["window"]["start"], "window.start")
    end = _timestamp(payload["window"]["end"], "window.end")
    if end < start:
        raise ValueError("route coverage window end precedes start")
    try:
        ZoneInfo(payload["window"]["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise ValueError("window.timezone must be an IANA timezone") from exc
    required = payload["required_route_ids"]
    if required != sorted(set(required)):
        raise ValueError("required_route_ids must be sorted and unique")
    if not set(required) <= _route_ids():
        raise ValueError("route coverage references an unknown route id")
    results = payload["route_results"]
    if [row["route_id"] for row in results] != sorted(
        row["route_id"] for row in results
    ):
        raise ValueError("route_results must be sorted by route_id")
    by_route = {row["route_id"]: row for row in results}
    if len(by_route) != len(results):
        raise ValueError("route_results contains duplicate route_id values")
    complete = set(required) <= set(by_route) and all(
        by_route[route_id]["status"] in SUCCESSFUL_ROUTE_STATES
        for route_id in required
    )
    if payload["coverage_complete"] != complete:
        raise ValueError("coverage_complete contradicts required route results")
    blockers = payload["blocker_codes"]
    if blockers != sorted(set(blockers)):
        raise ValueError("blocker_codes must be sorted and unique")
    _validate_blocker_codes(blockers, "blocker_codes")
    if complete == bool(blockers):
        raise ValueError("blocker_codes must be empty exactly for complete coverage")
    for row in results:
        if row["status"] in SUCCESSFUL_ROUTE_STATES:
            _required_sha256(
                row["capture_receipt_hash"],
                f"route_results[{row['route_id']}].capture_receipt_hash",
            )
        elif row["capture_receipt_hash"] is not None:
            raise ValueError("failed route result cannot claim a capture receipt")


def _validate_snapshot_build(payload: Mapping[str, Any]) -> None:
    _validate_schema(payload, "snapshot_build_receipt_v1")
    date.fromisoformat(payload["as_of"])
    _timestamp(payload["as_of_cutoff"], "as_of_cutoff")
    started_at = _timestamp(payload["build_started_at"], "build_started_at")
    finished_at = _timestamp(payload["build_finished_at"], "build_finished_at")
    if finished_at < started_at:
        raise ValueError("build_finished_at precedes build_started_at")
    source_hashes = payload["source_receipt_hashes"]
    required = payload["required_route_ids"]
    missing = payload["missing_route_ids"]
    if source_hashes != sorted(set(source_hashes)):
        raise ValueError("source_receipt_hashes must be sorted and unique")
    if required != sorted(set(required)) or missing != sorted(set(missing)):
        raise ValueError("required_route_ids and missing_route_ids must be sorted and unique")
    if not set(missing) <= set(required):
        raise ValueError("missing_route_ids must be a subset of required_route_ids")
    matching_bindings = [
        binding
        for binding in _bindings_for(agent_id=payload["agent_id"], stage=payload["stage"])
        if binding["tool_id"] == payload["tool_id"]
    ]
    if len(matching_bindings) != 1 or required != matching_bindings[0]["required_route_ids"]:
        raise ValueError("snapshot build required routes drift from the route manifest")
    output_path = Path(payload["output_path"])
    if output_path.is_absolute() or ".." in output_path.parts:
        raise ValueError("output_path must be a safe relative path")
    earliest = payload["earliest_trustworthy_date"]
    if earliest is not None and date.fromisoformat(earliest) > date.fromisoformat(payload["as_of"]):
        raise ValueError("earliest_trustworthy_date cannot be after as_of")
    state = payload["terminal_state"]
    blockers = payload["blocker_codes"]
    if blockers != sorted(set(blockers)):
        raise ValueError("blocker_codes must be sorted and unique")
    _validate_blocker_codes(blockers, "blocker_codes")
    if state == "READY":
        if (
            blockers
            or missing
            or payload["output_hash"] is None
            or earliest is None
            or not source_hashes
        ):
            raise ValueError("READY snapshot build must have output and no blockers")
    elif not blockers or payload["output_hash"] is not None:
        raise ValueError("non-READY snapshot build requires blockers and no output")


def _validate_materialization_attempt(payload: Mapping[str, Any]) -> None:
    _validate_schema(payload, "materialization_attempt_receipt_v1")
    date.fromisoformat(payload["as_of"])
    started_at = _timestamp(payload["started_at"], "started_at")
    finished_at = _timestamp(payload["finished_at"], "finished_at")
    if finished_at < started_at:
        raise ValueError("finished_at precedes started_at")
    lock = payload["lock"]
    lock_key = _required_sha256(lock["key"], "lock.key")
    acquired_at = _timestamp(lock["acquired_at"], "lock.acquired_at")
    heartbeat_at = _timestamp(lock["heartbeat_at"], "lock.heartbeat_at")
    lease_expires_at = _timestamp(lock["lease_expires_at"], "lock.lease_expires_at")
    if not acquired_at <= heartbeat_at <= lease_expires_at:
        raise ValueError("lock heartbeat must fall within its lease")
    if not started_at <= acquired_at <= heartbeat_at <= finished_at:
        raise ValueError("attempt and lock timestamps are inconsistent")
    freshness_at = _timestamp(payload["freshness"]["checked_at"], "freshness.checked_at")
    if not started_at <= freshness_at <= finished_at:
        raise ValueError("freshness.checked_at must fall within the attempt")
    state = payload["terminal_state"]
    blockers = payload["blocker_codes"]
    builds = payload["build_receipts"]
    sources = payload["source_receipts"]
    requested_tools = payload["requested_tool_ids"]
    if blockers != sorted(set(blockers)):
        raise ValueError("blocker_codes must be sorted and unique")
    _validate_blocker_codes(blockers, "blocker_codes")
    if requested_tools != sorted(set(requested_tools)):
        raise ValueError("requested_tool_ids must be sorted and unique")
    if not set(builds) <= set(requested_tools) or not set(sources) <= set(requested_tools):
        raise ValueError("source and build receipt maps must be limited to requested tools")
    for tool_id, source_hashes in sources.items():
        if source_hashes != sorted(set(source_hashes)):
            raise ValueError(f"source receipts for {tool_id} must be sorted and unique")
    expected_lock_key = materialization_lock_key(
        agent_id=payload["agent_id"],
        stage=payload["stage"],
        as_of=payload["as_of"],
        requested_tool_ids=requested_tools,
        candidate_scope_hash=payload["candidate_scope_hash"],
        runtime_input_hash=payload["runtime_input_hash"],
        contract_version=payload["contract_version"],
    )
    if lock_key != expected_lock_key:
        raise ValueError("lock.key does not match the canonical materialization key")
    if state == "READY":
        if finished_at > lease_expires_at:
            raise ValueError("READY materialization must finish within its lock lease")
        if blockers or payload["freshness"]["status"] == "STALE":
            raise ValueError("READY materialization cannot be STALE or blocked")
        if set(builds) != set(requested_tools) or set(sources) != set(requested_tools):
            raise ValueError("READY materialization requires source and build receipts per tool")
        if any(not source_hashes for source_hashes in sources.values()):
            raise ValueError("READY materialization requires source receipts per tool")
    elif not blockers:
        raise ValueError("non-READY materialization requires blocker_codes")


ReceiptT = TypeVar("ReceiptT", bound="_SealedReceipt")


@dataclass(frozen=True)
class _SealedReceipt:
    _payload: dict[str, Any]

    validator: ClassVar[Any]

    def __post_init__(self) -> None:
        value = _json_copy(self._payload)
        supplied = _required_sha256(value.get("receipt_hash"), "receipt_hash")
        body = {key: item for key, item in value.items() if key != "receipt_hash"}
        type(self).validator(value)
        if supplied != canonical_hash(body):
            raise ValueError("receipt_hash does not match the canonical receipt body")
        object.__setattr__(self, "_payload", value)

    @classmethod
    def seal(cls: type[ReceiptT], payload: Mapping[str, Any]) -> ReceiptT:
        body = _json_copy(payload)
        body.pop("receipt_hash", None)
        body["receipt_hash"] = canonical_hash(body)
        return cls(body)

    @classmethod
    def from_dict(cls: type[ReceiptT], payload: Mapping[str, Any]) -> ReceiptT:
        return cls(_json_copy(payload))

    @property
    def receipt_hash(self) -> str:
        return str(self._payload["receipt_hash"])

    def as_dict(self) -> dict[str, Any]:
        return _json_copy(self._payload)


@dataclass(frozen=True)
class SourceCaptureReceipt(_SealedReceipt):
    validator: ClassVar[Any] = _validate_source_capture


@dataclass(frozen=True)
class RouteCoverageReceipt(_SealedReceipt):
    validator: ClassVar[Any] = _validate_route_coverage


@dataclass(frozen=True)
class SnapshotBuildReceipt(_SealedReceipt):
    validator: ClassVar[Any] = _validate_snapshot_build


@dataclass(frozen=True)
class MaterializationAttemptReceipt(_SealedReceipt):
    validator: ClassVar[Any] = _validate_materialization_attempt


def validate_agent_data_route_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = _json_copy(payload)
    _validate_schema(value, "agent_data_route_manifest_v1")
    manifest_hash = _required_sha256(value["manifest_hash"], "manifest_hash")
    body = {key: item for key, item in value.items() if key != "manifest_hash"}
    if manifest_hash != canonical_hash(body):
        raise ValueError("agent data route manifest hash mismatch")

    tool_manifest = _load_json(AGENT_TOOL_CONTRACT_MANIFEST_PATH)
    if value["agent_tool_contract_manifest_hash"] != canonical_hash(tool_manifest):
        raise ValueError("agent tool contract manifest hash mismatch")
    routes = value["routes"]
    route_ids = [route["route_id"] for route in routes]
    if route_ids != sorted(set(route_ids)):
        raise ValueError("agent data route manifest routes must be sorted and unique")
    bindings = value["bindings"]
    actual_order = [
        (binding["agent_id"], binding["stage"], binding["tool_id"])
        for binding in bindings
    ]
    expected_order = [
        (agent["agent_id"], stage, tool_id)
        for agent in tool_manifest["agents"]
        for stage in agent["execution_stages"]
        for tool_id in sorted(agent["allowed_tools"])
    ]
    if actual_order != expected_order:
        raise ValueError("agent data route manifest binding coverage drift")
    known_routes = set(route_ids)
    for binding in bindings:
        required = binding["required_route_ids"]
        if required != sorted(set(required)) or not required:
            raise ValueError("binding required_route_ids must be non-empty, sorted and unique")
        if not set(required) <= known_routes:
            raise ValueError("binding references an unknown route id")
    return value


def load_agent_data_route_manifest(path: Path | None = None) -> dict[str, Any]:
    return validate_agent_data_route_manifest(
        _load_json(path or AGENT_DATA_ROUTE_MANIFEST_PATH)
    )


class AgentDataMaterializationLedger:
    """Append-only source/build/attempt receipt ledger with read-only status views."""

    _TABLES = (
        "source_capture_receipts",
        "route_coverage_receipts",
        "snapshot_build_receipts",
        "materialization_attempt_receipts",
    )

    def __init__(self, path: Path | None = None, *, create: bool = True) -> None:
        self.path = path or agent_data_materialization_db_path()
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
        else:
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if read_only:
            conn.execute("PRAGMA query_only = ON")
        else:
            conn.execute("PRAGMA journal_mode = DELETE")
        return conn

    def _initialise(self) -> None:
        self._available = True
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_capture_receipts (
                    receipt_hash TEXT PRIMARY KEY,
                    source_family TEXT NOT NULL,
                    route_id TEXT NOT NULL,
                    capture_id TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    knowledge_available_at TEXT NOT NULL,
                    eligible INTEGER NOT NULL CHECK(eligible IN (0, 1)),
                    receipt_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS source_capture_route_as_of
                  ON source_capture_receipts(route_id, as_of_date, knowledge_available_at);
                CREATE TABLE IF NOT EXISTS route_coverage_receipts (
                    receipt_hash TEXT PRIMARY KEY,
                    coverage_id TEXT NOT NULL UNIQUE,
                    window_end TEXT NOT NULL,
                    coverage_complete INTEGER NOT NULL CHECK(coverage_complete IN (0, 1)),
                    receipt_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshot_build_receipts (
                    receipt_hash TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL UNIQUE,
                    agent_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    terminal_state TEXT NOT NULL CHECK(terminal_state IN ('READY', 'BLOCKED', 'FAILED')),
                    finished_at TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS snapshot_build_status
                  ON snapshot_build_receipts(agent_id, stage, as_of, tool_id, finished_at);
                CREATE TABLE IF NOT EXISTS materialization_attempt_receipts (
                    receipt_hash TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL UNIQUE,
                    materialization_request_id TEXT NOT NULL UNIQUE,
                    graph_run_id TEXT NOT NULL,
                    run_slot_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    lock_key TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    terminal_state TEXT NOT NULL CHECK(terminal_state IN ('READY', 'BLOCKED', 'FAILED')),
                    finished_at TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS materialization_attempt_lock
                  ON materialization_attempt_receipts(lock_key, as_of, finished_at);
                """
            )
            for table in self._TABLES:
                conn.executescript(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS {table}_no_update
                      BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                    CREATE TRIGGER IF NOT EXISTS {table}_no_delete
                      BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                    """
                )

    def _append_on_connection(
        self,
        conn: sqlite3.Connection,
        table: str,
        columns: Sequence[str],
        values: Sequence[Any],
        receipt: _SealedReceipt,
    ) -> str:
        encoded = _canonical_json(receipt.as_dict())
        placeholders = ", ".join("?" for _ in range(len(columns) + 2))
        column_sql = ", ".join(("receipt_hash", *columns, "receipt_json"))
        existing = conn.execute(
            f"SELECT receipt_json FROM {table} WHERE receipt_hash = ?",
            (receipt.receipt_hash,),
        ).fetchone()
        if existing is not None:
            if existing[0] != encoded:
                raise ValueError(f"immutable {table} receipt collision")
            return receipt.receipt_hash
        try:
            conn.execute(
                f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                (receipt.receipt_hash, *values, encoded),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"immutable {table} identity collision") from exc
        return receipt.receipt_hash

    def _append(
        self,
        table: str,
        columns: Sequence[str],
        values: Sequence[Any],
        receipt: _SealedReceipt,
    ) -> str:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                receipt_hash = self._append_on_connection(
                    conn, table, columns, values, receipt
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return receipt_hash

    def _require_receipt_hashes(
        self,
        receipt_hashes: Sequence[str],
        *,
        tables: Sequence[str],
        field: str,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        if conn is None:
            with self._connect(read_only=True) as read_conn:
                self._require_receipt_hashes(
                    receipt_hashes,
                    tables=tables,
                    field=field,
                    conn=read_conn,
                )
            return
        missing = set(receipt_hashes)
        if not missing:
            return
        for table in tables:
            placeholders = ", ".join("?" for _ in missing)
            rows = conn.execute(
                f"SELECT receipt_hash FROM {table} "
                f"WHERE receipt_hash IN ({placeholders})",
                tuple(sorted(missing)),
            ).fetchall()
            missing.difference_update(str(row["receipt_hash"]) for row in rows)
            if not missing:
                return
        raise ValueError(f"{field} references unknown receipt hashes: {sorted(missing)}")

    def _append_source_on_connection(
        self,
        conn: sqlite3.Connection,
        value: SourceCaptureReceipt,
    ) -> str:
        payload = value.as_dict()
        identity = payload["identity"]
        cutoff = _timestamp(payload["pit"]["as_of_cutoff"], "pit.as_of_cutoff")
        return self._append_on_connection(
            conn,
            "source_capture_receipts",
            (
                "source_family",
                "route_id",
                "capture_id",
                "request_hash",
                "as_of_date",
                "knowledge_available_at",
                "eligible",
            ),
            (
                identity["source_family"],
                identity["route_id"],
                identity["capture_id"],
                identity["request_hash"],
                cutoff.date().isoformat(),
                payload["time"]["knowledge_available_at"],
                int(payload["pit"]["eligible"]),
            ),
            value,
        )

    def append_source_capture(self, receipt: SourceCaptureReceipt) -> str:
        value = SourceCaptureReceipt.from_dict(receipt.as_dict())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                receipt_hash = self._append_source_on_connection(conn, value)
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return receipt_hash

    def _validate_route_coverage_on_connection(
        self,
        conn: sqlite3.Connection,
        value: RouteCoverageReceipt,
    ) -> dict[str, Any]:
        payload = value.as_dict()
        successful = [
            row
            for row in payload["route_results"]
            if row["status"] in SUCCESSFUL_ROUTE_STATES
        ]
        self._require_receipt_hashes(
            [row["capture_receipt_hash"] for row in successful],
            tables=("source_capture_receipts",),
            field="route_results.capture_receipt_hash",
            conn=conn,
        )
        for result in successful:
            row = conn.execute(
                "SELECT receipt_json FROM source_capture_receipts "
                "WHERE receipt_hash = ?",
                (result["capture_receipt_hash"],),
            ).fetchone()
            if row is None:  # pragma: no cover - guarded above and append-only
                raise ValueError("source capture receipt disappeared")
            capture = SourceCaptureReceipt.from_dict(
                json.loads(row["receipt_json"])
            ).as_dict()
            if capture["identity"]["route_id"] != result["route_id"]:
                raise ValueError(
                    "coverage route does not match its source capture receipt"
                )
            if not capture["pit"]["eligible"]:
                raise ValueError(
                    "successful coverage route requires a PIT-eligible capture"
                )
            is_true_empty = (
                capture["content"]["normalized_row_count"] == 0
                and capture["completeness"]["empty_result_semantics"]
                == "TRUE_EMPTY"
            )
            if (result["status"] == "TRUE_EMPTY") != is_true_empty:
                raise ValueError(
                    "coverage route status contradicts source empty semantics"
                )
        return payload

    def _append_route_coverage_on_connection(
        self,
        conn: sqlite3.Connection,
        value: RouteCoverageReceipt,
    ) -> str:
        payload = self._validate_route_coverage_on_connection(conn, value)
        return self._append_on_connection(
            conn,
            "route_coverage_receipts",
            ("coverage_id", "window_end", "coverage_complete"),
            (
                payload["coverage_id"],
                payload["window"]["end"],
                int(payload["coverage_complete"]),
            ),
            value,
        )

    def append_route_coverage(self, receipt: RouteCoverageReceipt) -> str:
        value = RouteCoverageReceipt.from_dict(receipt.as_dict())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                receipt_hash = self._append_route_coverage_on_connection(conn, value)
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return receipt_hash

    def append_capture_group(
        self,
        source_receipts: Sequence[SourceCaptureReceipt],
        coverage_receipt: RouteCoverageReceipt,
    ) -> tuple[tuple[str, ...], str]:
        """Atomically publish a complete set of source receipts and its coverage."""
        sources = tuple(
            SourceCaptureReceipt.from_dict(receipt.as_dict())
            for receipt in source_receipts
        )
        coverage = RouteCoverageReceipt.from_dict(coverage_receipt.as_dict())
        source_hashes = tuple(receipt.receipt_hash for receipt in sources)
        if not sources or len(source_hashes) != len(set(source_hashes)):
            raise ValueError("capture group source receipts must be non-empty and unique")
        successful_hashes = {
            row["capture_receipt_hash"]
            for row in coverage.as_dict()["route_results"]
            if row["status"] in SUCCESSFUL_ROUTE_STATES
        }
        if successful_hashes != set(source_hashes):
            raise ValueError(
                "capture group coverage must close over every source receipt"
            )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for source in sources:
                    self._append_source_on_connection(conn, source)
                self._append_route_coverage_on_connection(conn, coverage)
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return source_hashes, coverage.receipt_hash

    def append_snapshot_build(self, receipt: SnapshotBuildReceipt) -> str:
        value = SnapshotBuildReceipt.from_dict(receipt.as_dict())
        payload = value.as_dict()
        self._require_receipt_hashes(
            payload["source_receipt_hashes"],
            tables=("source_capture_receipts", "route_coverage_receipts"),
            field="source_receipt_hashes",
        )
        required_routes = set(payload["required_route_ids"])
        covered_routes: set[str] = set()
        with self._connect(read_only=True) as conn:
            for receipt_hash in payload["source_receipt_hashes"]:
                source_row = conn.execute(
                    "SELECT receipt_json FROM source_capture_receipts "
                    "WHERE receipt_hash = ?",
                    (receipt_hash,),
                ).fetchone()
                if source_row is not None:
                    source = SourceCaptureReceipt.from_dict(
                        json.loads(source_row["receipt_json"])
                    ).as_dict()
                    route_id = str(source["identity"]["route_id"])
                    if route_id not in required_routes:
                        raise ValueError(
                            "snapshot build source is outside required route coverage"
                        )
                    if (
                        payload["terminal_state"] == "READY"
                        and not source["pit"]["eligible"]
                    ):
                        raise ValueError(
                            "READY snapshot build requires PIT-eligible sources"
                        )
                    covered_routes.add(route_id)
                    continue
                coverage_row = conn.execute(
                    "SELECT receipt_json FROM route_coverage_receipts "
                    "WHERE receipt_hash = ?",
                    (receipt_hash,),
                ).fetchone()
                if coverage_row is None:  # pragma: no cover - guarded above
                    raise ValueError("source evidence disappeared from the ledger")
                coverage = RouteCoverageReceipt.from_dict(
                    json.loads(coverage_row["receipt_json"])
                ).as_dict()
                coverage_routes = set(coverage["required_route_ids"])
                if not coverage_routes & required_routes:
                    raise ValueError(
                        "snapshot build coverage is outside required route coverage"
                    )
                if (
                    payload["terminal_state"] == "READY"
                    and not coverage["coverage_complete"]
                ):
                    raise ValueError(
                        "READY snapshot build requires complete route coverage"
                    )
                covered_routes.update(coverage_routes)
        if (
            payload["terminal_state"] == "READY"
            and not required_routes <= covered_routes
        ):
            raise ValueError(
                "READY snapshot build does not provide required route coverage"
            )
        return self._append(
            "snapshot_build_receipts",
            ("build_id", "agent_id", "stage", "tool_id", "as_of", "terminal_state", "finished_at"),
            tuple(payload[key] for key in ("build_id", "agent_id", "stage", "tool_id", "as_of", "terminal_state", "build_finished_at")),
            value,
        )

    def snapshot_build_receipt(
        self, *, build_id: str
    ) -> SnapshotBuildReceipt | None:
        if not build_id:
            raise ValueError("build_id must be non-empty")
        if not self._available:
            return None
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT receipt_json FROM snapshot_build_receipts "
                "WHERE build_id = ?",
                (build_id,),
            ).fetchone()
        if row is None:
            return None
        return SnapshotBuildReceipt.from_dict(json.loads(row["receipt_json"]))

    def append_or_reuse_snapshot_build(
        self, receipt: SnapshotBuildReceipt
    ) -> SnapshotBuildReceipt:
        candidate = SnapshotBuildReceipt.from_dict(receipt.as_dict())
        build_id = str(candidate.as_dict()["build_id"])

        def require_same_build(existing: SnapshotBuildReceipt) -> SnapshotBuildReceipt:
            existing_body = existing.as_dict()
            candidate_body = candidate.as_dict()
            for field in (
                "receipt_hash",
                "build_started_at",
                "build_finished_at",
            ):
                existing_body.pop(field, None)
                candidate_body.pop(field, None)
            if existing_body != candidate_body:
                raise ValueError("immutable snapshot build identity collision")
            return existing

        existing = self.snapshot_build_receipt(build_id=build_id)
        if existing is not None:
            return require_same_build(existing)
        try:
            self.append_snapshot_build(candidate)
        except ValueError:
            existing = self.snapshot_build_receipt(build_id=build_id)
            if existing is None:
                raise
            return require_same_build(existing)
        return candidate

    def append_materialization_attempt(self, receipt: MaterializationAttemptReceipt) -> str:
        value = MaterializationAttemptReceipt.from_dict(receipt.as_dict())
        payload = value.as_dict()
        source_hashes = sorted(
            {
                receipt_hash
                for hashes in payload["source_receipts"].values()
                for receipt_hash in hashes
            }
        )
        self._require_receipt_hashes(
            source_hashes,
            tables=("source_capture_receipts", "route_coverage_receipts"),
            field="source_receipts",
        )
        self._require_receipt_hashes(
            list(payload["build_receipts"].values()),
            tables=("snapshot_build_receipts",),
            field="build_receipts",
        )
        with self._connect(read_only=True) as conn:
            for tool_id, build_hash in payload["build_receipts"].items():
                row = conn.execute(
                    "SELECT receipt_json FROM snapshot_build_receipts "
                    "WHERE receipt_hash = ?",
                    (build_hash,),
                ).fetchone()
                if row is None:  # pragma: no cover - guarded above
                    raise ValueError("build receipt disappeared from the append-only ledger")
                build = SnapshotBuildReceipt.from_dict(json.loads(row["receipt_json"]))
                build_payload = build.as_dict()
                if (
                    build_payload["tool_id"] != tool_id
                    or build_payload["agent_id"] != payload["agent_id"]
                    or build_payload["stage"] != payload["stage"]
                    or build_payload["as_of"] != payload["as_of"]
                    or build_payload["source_receipt_hashes"]
                    != payload["source_receipts"].get(tool_id)
                ):
                    raise ValueError("attempt receipt does not close over its build receipt")
        return self._append(
            "materialization_attempt_receipts",
            (
                "attempt_id",
                "materialization_request_id",
                "graph_run_id",
                "run_slot_id",
                "run_id",
                "node_id",
                "lock_key",
                "agent_id",
                "stage",
                "as_of",
                "terminal_state",
                "finished_at",
            ),
            (
                payload["attempt_id"],
                payload["materialization_request_id"],
                payload["graph_run_id"],
                payload["run_slot_id"],
                payload["run_id"],
                payload["node_id"],
                payload["lock"]["key"],
                payload["agent_id"],
                payload["stage"],
                payload["as_of"],
                payload["terminal_state"],
                payload["finished_at"],
            ),
            value,
        )

    def row_counts(self) -> dict[str, int]:
        if not self._available:
            return {table: 0 for table in self._TABLES}
        with self._connect(read_only=True) as conn:
            return {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in self._TABLES
            }

    def source_status(self, *, as_of: str, route_id: str) -> dict[str, Any]:
        date.fromisoformat(as_of)
        if route_id not in _route_ids():
            raise ValueError(f"unknown Agent data route: {route_id}")
        if not self._available:
            return {
                "route_id": route_id,
                "as_of": as_of,
                "status": "BLOCKED",
                "blocker_codes": ["NO_CAPTURE_RECEIPT"],
                "capture_receipt_hash": None,
            }
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT receipt_hash, receipt_json, eligible FROM source_capture_receipts "
                "WHERE route_id = ? AND as_of_date <= ? "
                "ORDER BY as_of_date DESC, julianday(knowledge_available_at) DESC, "
                "rowid DESC LIMIT 1",
                (route_id, as_of),
            ).fetchone()
        if row is None:
            return {
                "route_id": route_id,
                "as_of": as_of,
                "status": "BLOCKED",
                "blocker_codes": ["NO_CAPTURE_RECEIPT"],
                "capture_receipt_hash": None,
            }
        receipt = json.loads(row["receipt_json"])
        return {
            "route_id": route_id,
            "as_of": as_of,
            "status": "READY" if row["eligible"] else "BLOCKED",
            "blocker_codes": receipt["pit"]["blocker_codes"],
            "capture_receipt_hash": row["receipt_hash"],
            "knowledge_available_at": receipt["time"]["knowledge_available_at"],
            "pit_mode": receipt["pit"]["pit_mode"],
        }

    def snapshot_status(self, *, as_of: str, agent_id: str, stage: str) -> dict[str, Any]:
        date.fromisoformat(as_of)
        bindings = _bindings_for(agent_id=agent_id, stage=stage)
        tool_ids = sorted(binding["tool_id"] for binding in bindings)
        if not self._available:
            return _missing_snapshot_status(as_of, agent_id, stage, tool_ids, bindings)
        with self._connect(read_only=True) as conn:
            rows = conn.execute(
                "SELECT tool_id, receipt_hash, terminal_state, receipt_json FROM "
                "snapshot_build_receipts WHERE agent_id = ? AND stage = ? AND as_of = ? "
                "ORDER BY julianday(finished_at) DESC, rowid DESC",
                (agent_id, stage, as_of),
            ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest.setdefault(str(row["tool_id"]), row)
        ready = all(
            tool_id in latest and latest[tool_id]["terminal_state"] == "READY"
            for tool_id in tool_ids
        )
        missing_tools = [
            tool_id
            for tool_id in tool_ids
            if tool_id not in latest or latest[tool_id]["terminal_state"] != "READY"
        ]
        return {
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of,
            "status": "READY" if ready else "BLOCKED",
            "tool_ids": tool_ids,
            "missing_tool_ids": missing_tools,
            "build_receipt_hashes": {
                tool_id: latest[tool_id]["receipt_hash"]
                for tool_id in tool_ids
                if tool_id in latest and latest[tool_id]["terminal_state"] == "READY"
            },
            "missing_route_ids": sorted(
                {
                    route_id
                    for binding in bindings
                    if binding["tool_id"] in missing_tools
                    for route_id in binding["required_route_ids"]
                }
            ),
        }

    def materialize_dry_run(self, *, as_of: str, agent_id: str, stage: str) -> dict[str, Any]:
        snapshot = self.snapshot_status(as_of=as_of, agent_id=agent_id, stage=stage)
        bindings = _bindings_for(agent_id=agent_id, stage=stage)
        required_routes = sorted(
            {route_id for binding in bindings for route_id in binding["required_route_ids"]}
        )
        sources = [self.source_status(as_of=as_of, route_id=route_id) for route_id in required_routes]
        missing_routes = [row["route_id"] for row in sources if row["status"] != "READY"]
        snapshot_ready = snapshot["status"] == "READY"
        source_ready = not missing_routes
        status = "READY" if snapshot_ready else ("READY_TO_BUILD" if source_ready else "BLOCKED")
        return {
            "dry_run": True,
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of,
            "status": status,
            "would_collect": not snapshot_ready and not source_ready,
            "would_build": not snapshot_ready and source_ready,
            "would_issue_capability": snapshot_ready,
            "required_route_ids": required_routes,
            "missing_route_ids": missing_routes if not snapshot_ready else [],
            "snapshot_status": snapshot,
            "source_statuses": sources,
        }


def _bindings_for(*, agent_id: str, stage: str) -> list[dict[str, Any]]:
    manifest = load_agent_data_route_manifest()
    bindings = [
        binding
        for binding in manifest["bindings"]
        if binding["agent_id"] == agent_id and binding["stage"] == stage
    ]
    if not bindings:
        raise ValueError(f"unknown Agent/stage materialization binding: {agent_id}/{stage}")
    return bindings


def _route_ids() -> set[str]:
    return {route["route_id"] for route in load_agent_data_route_manifest()["routes"]}


def _missing_snapshot_status(
    as_of: str,
    agent_id: str,
    stage: str,
    tool_ids: Sequence[str],
    bindings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "stage": stage,
        "as_of": as_of,
        "status": "BLOCKED",
        "tool_ids": list(tool_ids),
        "missing_tool_ids": list(tool_ids),
        "build_receipt_hashes": {},
        "missing_route_ids": sorted(
            {route_id for binding in bindings for route_id in binding["required_route_ids"]}
        ),
    }


def open_agent_data_materialization_ledger(*, create: bool = False) -> AgentDataMaterializationLedger:
    return AgentDataMaterializationLedger(create=create)


__all__ = [
    "AGENT_DATA_ROUTE_MANIFEST_PATH",
    "AgentDataMaterializationLedger",
    "BLOCKER_CODES",
    "MaterializationAttemptReceipt",
    "RouteCoverageReceipt",
    "SnapshotBuildReceipt",
    "SourceCaptureReceipt",
    "agent_data_materialization_db_path",
    "load_agent_data_route_manifest",
    "materialization_lock_key",
    "open_agent_data_materialization_ledger",
    "validate_agent_data_route_manifest",
]

"""Private, frozen adaptive-query bundles for staged Agent capabilities.

Trusted ``prepare`` code may call collectors through an injected materializer.
Model-visible calls only resolve an exact canonical request from the append-only
private bundle and therefore never have a transport or fallback path.
"""

from __future__ import annotations

import fcntl
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l3_l4_preservation import (
    L3_TOOL_ROSTER,
    L4_STAGE_ROSTER,
    QUERY_BUNDLE_CONTRACT_VERSION as BOUND_RUNTIME_QUERY_BUNDLE_CONTRACT_VERSION,
    validate_l3_l4_preservation_overlay,
)
from mosaic.scorecard.sector_relationship_preservation import (
    QUERY_BUNDLE_CONTRACT_VERSION as SECTOR_QUERY_BUNDLE_CONTRACT_VERSION,
    SECTOR_AGENT_IDS,
    validate_sector_relationship_preservation_overlay,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_PROJECTION_VERSION = "frozen_adaptive_query_public_projection_v1"
_SHA_PREFIX = "sha256:"
_A_SHARE_TICKER = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(_SHA_PREFIX)
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _validate_string_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{field} must be a string array")
    if not allow_empty and not value:
        raise ValueError(f"{field} must not be empty")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must contain unique values")
    return list(value)


class FrozenAdaptiveQueryStore:
    """SQLite authority for private finite query sets and bounded sessions."""

    _thread_locks_guard = threading.Lock()
    _thread_locks: dict[str, threading.Lock] = {}

    def __init__(
        self,
        db_path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = db_path
        if "registry" in db_path.parts:
            raise ValueError("frozen adaptive query payloads must not be stored in registry")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._materialization_state = threading.local()
        self._initialise()

    @classmethod
    def _thread_lock_for(cls, key: str) -> threading.Lock:
        with cls._thread_locks_guard:
            return cls._thread_locks.setdefault(key, threading.Lock())

    @contextmanager
    def _materialization_lock(self, materialization_key: str) -> Iterator[None]:
        lock_identity = f"{self.db_path.resolve()}:{materialization_key}"
        thread_lock = self._thread_lock_for(lock_identity)
        lock_dir = self.db_path.parent / f".{self.db_path.name}.locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f"{materialization_key[7:]}.lock"
        with thread_lock, lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS frozen_query_bundles (
                    bundle_id TEXT PRIMARY KEY,
                    materialization_key TEXT NOT NULL UNIQUE,
                    agent_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    overlay_hash TEXT NOT NULL,
                    authorized_scope_hash TEXT NOT NULL,
                    private_scope_json TEXT NOT NULL,
                    public_projection_json TEXT NOT NULL,
                    bundle_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    max_rounds INTEGER NOT NULL DEFAULT 3,
                    initial_request_refs_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS frozen_query_payloads (
                    bundle_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    binding_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    source_receipt_hashes_json TEXT NOT NULL,
                    derivation_json TEXT,
                    derivation_hash TEXT,
                    call_mode TEXT NOT NULL DEFAULT 'FOLLOW_UP',
                    PRIMARY KEY(bundle_id, tool_id, request_hash),
                    FOREIGN KEY(bundle_id) REFERENCES frozen_query_bundles(bundle_id)
                );
                CREATE TABLE IF NOT EXISTS frozen_query_sessions (
                    session_id TEXT PRIMARY KEY,
                    bundle_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    FOREIGN KEY(bundle_id) REFERENCES frozen_query_bundles(bundle_id)
                );
                CREATE TABLE IF NOT EXISTS frozen_query_calls (
                    session_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL CHECK(round_number BETWEEN 1 AND 3),
                    tool_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    called_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, round_number),
                    FOREIGN KEY(session_id) REFERENCES frozen_query_sessions(session_id)
                );
                CREATE TRIGGER IF NOT EXISTS frozen_query_bundles_no_update
                  BEFORE UPDATE ON frozen_query_bundles BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_bundles is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_bundles_no_delete
                  BEFORE DELETE ON frozen_query_bundles BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_bundles is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_payloads_no_update
                  BEFORE UPDATE ON frozen_query_payloads BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_payloads is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_payloads_no_delete
                  BEFORE DELETE ON frozen_query_payloads BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_payloads is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_sessions_no_update
                  BEFORE UPDATE ON frozen_query_sessions BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_sessions is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_sessions_no_delete
                  BEFORE DELETE ON frozen_query_sessions BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_sessions is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_calls_no_update
                  BEFORE UPDATE ON frozen_query_calls BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_calls is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_calls_no_delete
                  BEFORE DELETE ON frozen_query_calls BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_calls is append-only');
                  END;
                """
            )
            bundle_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(frozen_query_bundles)")
            }
            if "max_rounds" not in bundle_columns:
                connection.execute(
                    "ALTER TABLE frozen_query_bundles "
                    "ADD COLUMN max_rounds INTEGER NOT NULL DEFAULT 3"
                )
            if "initial_request_refs_json" not in bundle_columns:
                connection.execute(
                    "ALTER TABLE frozen_query_bundles "
                    "ADD COLUMN initial_request_refs_json TEXT NOT NULL DEFAULT '[]'"
                )
            payload_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(frozen_query_payloads)")
            }
            if "call_mode" not in payload_columns:
                connection.execute(
                    "ALTER TABLE frozen_query_payloads "
                    "ADD COLUMN call_mode TEXT NOT NULL DEFAULT 'FOLLOW_UP'"
                )

    def _existing_projection(self, materialization_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT bundle_id, public_projection_json FROM frozen_query_bundles "
                "WHERE materialization_key = ?",
                (materialization_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "bundle_id": row["bundle_id"],
            "public_projection": json.loads(row["public_projection_json"]),
        }

    def prepare(
        self,
        *,
        agent_id: str,
        stage: str,
        as_of: str,
        authorized_scope: Mapping[str, Any],
        query_requests: Sequence[Mapping[str, Any]],
        initial_query_requests: Sequence[Mapping[str, Any]] = (),
        preservation_overlay: Mapping[str, Any],
        materializer: Callable[[str, dict[str, Any]], Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Validate a finite scope, materialize it once, and publish its hashes."""

        agent_id = _required_text(agent_id, "agent_id")
        stage = _required_text(stage, "stage")
        as_of_date = date.fromisoformat(as_of)
        overlay_version = preservation_overlay.get("schema_version")
        if overlay_version == "sector_relationship_preservation_overlay_v1":
            validate_sector_relationship_preservation_overlay(
                preservation_overlay, root=_REPO_ROOT
            )
            if initial_query_requests:
                raise ValueError("PR6 frozen queries do not define deterministic initial calls")
            if stage != agent_id:
                raise ValueError(
                    "frozen query stage must equal the current Agent execution stage"
                )
            scope = self._validate_scope(authorized_scope, as_of=as_of)
            if agent_id not in {*SECTOR_AGENT_IDS, "relationship_mapper"}:
                raise ValueError("Agent is outside the PR6 frozen-query roster")
            bindings = {
                row["tool_id"]: row
                for row in preservation_overlay["bindings"]
                if row["agent_id"] == agent_id and row["stage"] == stage
            }
            follow_up_requests = self._validate_requests(
                query_requests,
                bindings=bindings,
                scope=scope,
                as_of=as_of_date,
                agent_id=agent_id,
            )
            initial_requests: list[tuple[str, dict[str, Any], str]] = []
            contract_version = SECTOR_QUERY_BUNDLE_CONTRACT_VERSION
            max_rounds = 3
        elif overlay_version == "l3_l4_preservation_overlay_v1":
            validate_l3_l4_preservation_overlay(preservation_overlay, root=_REPO_ROOT)
            if (agent_id, stage) not in {
                *((l3_agent, l3_agent) for l3_agent in L3_TOOL_ROSTER),
                *L4_STAGE_ROSTER,
            }:
                raise ValueError("Agent/stage is outside the PR7 frozen-query roster")
            scope = self._validate_bound_scope(
                authorized_scope,
                as_of=as_of,
                l3=agent_id in L3_TOOL_ROSTER,
            )
            bindings = {
                row["tool_id"]: row
                for row in preservation_overlay["bindings"]
                if row["agent_id"] == agent_id and row["stage"] == stage
            }
            initial_requests = self._validate_bound_requests(
                initial_query_requests,
                bindings=bindings,
                scope=scope,
                as_of=as_of_date,
                agent_id=agent_id,
                stage=stage,
                allow_empty=True,
                preserve_order=True,
            )
            follow_up_requests = self._validate_bound_requests(
                query_requests,
                bindings=bindings,
                scope=scope,
                as_of=as_of_date,
                agent_id=agent_id,
                stage=stage,
                allow_empty=True,
                preserve_order=False,
            )
            self._validate_bound_initial_calls(
                initial_requests,
                agent_id=agent_id,
                stage=stage,
                scope=scope,
                as_of=as_of,
                preservation_overlay=preservation_overlay,
            )
            if not initial_requests and not follow_up_requests:
                raise ValueError("bound runtime query bundle must not be empty")
            combined_keys = {
                (tool_id, request_hash)
                for tool_id, _, request_hash in [*initial_requests, *follow_up_requests]
            }
            if len(combined_keys) != len(initial_requests) + len(follow_up_requests):
                raise ValueError("initial and follow-up frozen requests must be unique")
            contract_version = BOUND_RUNTIME_QUERY_BUNDLE_CONTRACT_VERSION
            max_rounds = 3 if agent_id in L3_TOOL_ROSTER else 0
            if max_rounds == 0 and follow_up_requests:
                raise ValueError("L4 RKE prior does not permit adaptive follow-up requests")
        else:
            raise ValueError("unsupported frozen-query preservation overlay")
        if not bindings:
            raise ValueError("Agent has no staged frozen-query bindings")

        requests = [
            *((tool_id, request, request_hash, "INITIAL") for tool_id, request, request_hash in initial_requests),
            *((tool_id, request, request_hash, "FOLLOW_UP") for tool_id, request, request_hash in follow_up_requests),
        ]
        overlay_hash = preservation_overlay["manifest_hash"]
        private_request_descriptor = [
            {"tool_id": tool_id, "request": request, "call_mode": call_mode}
            for tool_id, request, _, call_mode in requests
        ]
        materialization_key = canonical_hash(
            {
                "contract_version": contract_version,
                "agent_id": agent_id,
                "stage": stage,
                "as_of": as_of,
                "authorized_scope": scope,
                "requests": private_request_descriptor,
                "max_rounds": max_rounds,
                "overlay_hash": overlay_hash,
            }
        )
        held_keys = getattr(self._materialization_state, "held_keys", None)
        if held_keys is None:
            held_keys = set()
            self._materialization_state.held_keys = held_keys
        if materialization_key not in held_keys:
            with self._materialization_lock(materialization_key):
                held_keys.add(materialization_key)
                try:
                    return self.prepare(
                        agent_id=agent_id,
                        stage=stage,
                        as_of=as_of,
                        authorized_scope=scope,
                        query_requests=query_requests,
                        initial_query_requests=initial_query_requests,
                        preservation_overlay=preservation_overlay,
                        materializer=materializer,
                    )
                finally:
                    held_keys.remove(materialization_key)
        existing = self._existing_projection(materialization_key)
        if existing is not None:
            return existing

        materialized: list[dict[str, Any]] = []
        for tool_id, request, request_hash, call_mode in requests:
            result = materializer(tool_id, dict(request))
            if not isinstance(result, Mapping):
                raise ValueError("trusted query materializer must return an object")
            if set(result) not in (
                {"payload", "source_receipt_hashes"},
                {"payload", "source_receipt_hashes", "derivation"},
            ):
                raise ValueError(
                    "trusted query materializer must return payload, source_receipt_hashes "
                    "and optional derivation"
                )
            payload = result.get("payload")
            if not isinstance(payload, str) or not payload:
                raise ValueError("trusted query materializer returned an empty payload")
            receipt_hashes = result.get("source_receipt_hashes")
            if not isinstance(receipt_hashes, list) or not receipt_hashes:
                raise ValueError("materialized query requires source receipt hashes")
            if receipt_hashes != sorted(set(receipt_hashes)) or not all(
                _is_sha256(value) for value in receipt_hashes
            ):
                raise ValueError(
                    "source receipt hashes must be sorted, unique sha256 identifiers"
                )
            derivation = result.get("derivation")
            derivation_contract = bindings[tool_id]["materializer_contract"][
                "derivation_contract"
            ]
            requires_digest_lineage = all(
                derivation_contract.get(field) is True
                for field in (
                    "model_hash_required",
                    "prompt_hash_required",
                    "source_payload_hash_required",
                )
            )
            if requires_digest_lineage and derivation is None:
                raise ValueError(
                    "trusted query materializer requires derivation lineage"
                )
            if derivation is not None:
                required_derivation = {
                    "derivation_contract_version",
                    "model_hash",
                    "prompt_hash",
                    "source_payload_hash",
                }
                if not isinstance(derivation, Mapping) or set(derivation) != required_derivation:
                    raise ValueError("trusted query derivation fields do not match the contract")
                if derivation["derivation_contract_version"] != derivation_contract.get(
                    "contract_version"
                ):
                    raise ValueError("trusted query derivation contract version mismatch")
                if not all(
                    _is_sha256(derivation[field])
                    for field in ("model_hash", "prompt_hash", "source_payload_hash")
                ):
                    raise ValueError("trusted query derivation hashes are invalid")
                derivation = dict(derivation)
            materialized.append(
                {
                    "tool_id": tool_id,
                    "request": request,
                    "request_hash": request_hash,
                    "call_mode": call_mode,
                    "binding_id": bindings[tool_id]["binding_id"],
                    "payload": payload,
                    "payload_hash": canonical_hash({"text": payload}),
                    "source_receipt_hashes": receipt_hashes,
                    "derivation": derivation,
                    "derivation_hash": (
                        canonical_hash(derivation) if derivation is not None else None
                    ),
                }
            )

        materialized.sort(key=lambda row: (row["tool_id"], row["request_hash"]))
        initial_request_refs = [
            {"tool_id": tool_id, "request_hash": request_hash}
            for tool_id, _, request_hash in initial_requests
        ]
        private_bundle_descriptor = {
            "contract_version": contract_version,
            "materialization_key": materialization_key,
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of,
            "authorized_scope_hash": canonical_hash(scope),
            "overlay_hash": overlay_hash,
            "max_rounds": max_rounds,
            "initial_request_refs": initial_request_refs,
            "entries": [
                {
                    "tool_id": row["tool_id"],
                    "request_hash": row["request_hash"],
                    "call_mode": row["call_mode"],
                    "binding_id": row["binding_id"],
                    "payload_hash": row["payload_hash"],
                    "source_receipt_set_hash": canonical_hash(
                        row["source_receipt_hashes"]
                    ),
                    "derivation_hash": row["derivation_hash"],
                }
                for row in materialized
            ],
        }
        bundle_hash = canonical_hash(private_bundle_descriptor)
        bundle_id = "frozen_bundle_" + materialization_key[7:]
        created_at = self.clock().astimezone(timezone.utc).isoformat()
        public_body = {
            "schema_version": PUBLIC_PROJECTION_VERSION,
            "bundle_id": bundle_id,
            "bundle_hash": bundle_hash,
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of,
            "authorized_scope_hash": canonical_hash(scope),
            "preservation_overlay_hash": overlay_hash,
            "query_bundle_contract_version": contract_version,
            "private_payload_count": len(materialized),
            "initial_payload_count": len(initial_request_refs),
            "adaptive_max_rounds": max_rounds,
            "entries": [
                {
                    "tool_id": row["tool_id"],
                    "request_hash": row["request_hash"],
                    "call_mode": row["call_mode"],
                    "binding_id": row["binding_id"],
                    "payload_hash": row["payload_hash"],
                    "source_receipt_set_hash": canonical_hash(
                        row["source_receipt_hashes"]
                    ),
                    "derivation_hash": row["derivation_hash"],
                }
                for row in materialized
            ],
        }
        public_projection = {
            **public_body,
            "projection_hash": canonical_hash(public_body),
        }

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing_row = connection.execute(
                    "SELECT bundle_id, public_projection_json FROM frozen_query_bundles "
                    "WHERE materialization_key = ?",
                    (materialization_key,),
                ).fetchone()
                if existing_row is not None:
                    connection.execute("ROLLBACK")
                    return {
                        "bundle_id": existing_row["bundle_id"],
                        "public_projection": json.loads(
                            existing_row["public_projection_json"]
                        ),
                    }
                connection.execute(
                    "INSERT INTO frozen_query_bundles VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        bundle_id,
                        materialization_key,
                        agent_id,
                        stage,
                        as_of,
                        overlay_hash,
                        canonical_hash(scope),
                        _canonical_json(scope),
                        _canonical_json(public_projection),
                        bundle_hash,
                        created_at,
                        max_rounds,
                        _canonical_json(initial_request_refs),
                    ),
                )
                for row in materialized:
                    connection.execute(
                        "INSERT INTO frozen_query_payloads VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            bundle_id,
                            row["tool_id"],
                            row["request_hash"],
                            _canonical_json(row["request"]),
                            row["binding_id"],
                            row["payload"],
                            row["payload_hash"],
                            _canonical_json(row["source_receipt_hashes"]),
                            (
                                _canonical_json(row["derivation"])
                                if row["derivation"] is not None
                                else None
                            ),
                            row["derivation_hash"],
                            row["call_mode"],
                        ),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return {"bundle_id": bundle_id, "public_projection": public_projection}

    def _validate_scope(
        self, authorized_scope: Mapping[str, Any], *, as_of: str
    ) -> dict[str, Any]:
        if not isinstance(authorized_scope, Mapping):
            raise ValueError("authorized_scope must be an object")
        required = {
            "as_of",
            "earliest_date",
            "tickers",
            "etfs",
            "sectors",
            "indicator_families",
        }
        if set(authorized_scope) != required:
            raise ValueError("authorized_scope fields do not match the frozen contract")
        if authorized_scope.get("as_of") != as_of:
            raise ValueError("authorized_scope as_of must equal bundle as_of")
        earliest = date.fromisoformat(_required_text(authorized_scope["earliest_date"], "earliest_date"))
        as_of_date = date.fromisoformat(as_of)
        if earliest > as_of_date:
            raise ValueError("authorized_scope earliest_date exceeds as_of")
        tickers = _validate_string_list(authorized_scope["tickers"], "tickers")
        etfs = _validate_string_list(
            authorized_scope["etfs"], "etfs", allow_empty=True
        )
        sectors = _validate_string_list(authorized_scope["sectors"], "sectors")
        indicators = _validate_string_list(
            authorized_scope["indicator_families"],
            "indicator_families",
            allow_empty=True,
        )
        return {
            "as_of": as_of,
            "earliest_date": earliest.isoformat(),
            "tickers": sorted(tickers),
            "etfs": sorted(etfs),
            "sectors": sorted(sectors),
            "indicator_families": sorted(indicators),
        }

    def _validate_bound_scope(
        self,
        authorized_scope: Mapping[str, Any],
        *,
        as_of: str,
        l3: bool,
    ) -> dict[str, Any]:
        if not isinstance(authorized_scope, Mapping):
            raise ValueError("authorized_scope must be an object")
        common = {"as_of", "accepted_candidate_tickers"}
        required = (
            common
            | {
                "earliest_date",
                "indicator_families",
                "candidate_scope_hash",
                "candidate_universe_hash",
                "source_snapshot_hash",
            }
            if l3
            else common
            | {
                "accepted_output_set_hash",
                "account_positions_policy_hash",
                "market_liquidity_vintage_hash",
            }
        )
        if set(authorized_scope) != required:
            raise ValueError("authorized_scope fields do not match the bound runtime contract")
        if authorized_scope.get("as_of") != as_of:
            raise ValueError("authorized_scope as_of must equal bundle as_of")
        date.fromisoformat(as_of)
        tickers = _validate_string_list(
            authorized_scope["accepted_candidate_tickers"],
            "accepted_candidate_tickers",
            allow_empty=not l3,
        )
        if any(_A_SHARE_TICKER.fullmatch(ticker) is None for ticker in tickers):
            raise ValueError("accepted candidate ticker is not a canonical A-share ticker")
        result: dict[str, Any] = {
            "as_of": as_of,
            "accepted_candidate_tickers": tickers,
        }
        hash_fields = (
            ("candidate_scope_hash", "candidate_universe_hash", "source_snapshot_hash")
            if l3
            else (
                "accepted_output_set_hash",
                "account_positions_policy_hash",
                "market_liquidity_vintage_hash",
            )
        )
        for field in hash_fields:
            value = authorized_scope[field]
            if not _is_sha256(value):
                raise ValueError(f"{field} must be a sha256 identifier")
            result[field] = value
        if l3:
            earliest = date.fromisoformat(
                _required_text(authorized_scope["earliest_date"], "earliest_date")
            )
            if earliest > date.fromisoformat(as_of):
                raise ValueError("authorized_scope earliest_date exceeds as_of")
            indicators = _validate_string_list(
                authorized_scope["indicator_families"],
                "indicator_families",
                allow_empty=True,
            )
            result["earliest_date"] = earliest.isoformat()
            result["indicator_families"] = sorted(indicators)
        return result

    def _validate_bound_requests(
        self,
        query_requests: Sequence[Mapping[str, Any]],
        *,
        bindings: Mapping[str, Mapping[str, Any]],
        scope: Mapping[str, Any],
        as_of: date,
        agent_id: str,
        stage: str,
        allow_empty: bool,
        preserve_order: bool,
    ) -> list[tuple[str, dict[str, Any], str]]:
        if not isinstance(query_requests, Sequence) or isinstance(
            query_requests, (str, bytes)
        ):
            raise ValueError("query_requests must be an array")
        if not query_requests and not allow_empty:
            raise ValueError("query_requests must be a non-empty array")
        validated: list[tuple[str, dict[str, Any], str]] = []
        seen: set[tuple[str, str]] = set()
        for index, row in enumerate(query_requests):
            if not isinstance(row, Mapping) or set(row) != {"tool_id", "args"}:
                raise ValueError(f"query_requests[{index}] must contain tool_id and args")
            tool_id = _required_text(row["tool_id"], "tool_id")
            binding = bindings.get(tool_id)
            if binding is None:
                raise ValueError(f"tool {tool_id} is outside the staged Agent whitelist")
            request = row["args"]
            if not isinstance(request, Mapping):
                raise ValueError("query args must be an object")
            request_copy = json.loads(_canonical_json(request))
            errors = sorted(
                Draft202012Validator(
                    binding["argument_schema"], format_checker=FormatChecker()
                ).iter_errors(request_copy),
                key=lambda error: list(error.absolute_path),
            )
            if errors:
                location = ".".join(str(part) for part in errors[0].absolute_path) or "$"
                raise ValueError(
                    f"query argument schema violation at {location}: {errors[0].message}"
                )
            self._validate_bound_authorized_request(
                tool_id,
                request_copy,
                scope=scope,
                as_of=as_of,
                agent_id=agent_id,
                stage=stage,
            )
            request_hash = canonical_hash(request_copy)
            key = (tool_id, request_hash)
            if key in seen:
                raise ValueError("frozen query requests must be unique")
            seen.add(key)
            validated.append((tool_id, request_copy, request_hash))
        if not preserve_order:
            validated.sort(key=lambda item: (item[0], item[2]))
        return validated

    def _validate_bound_authorized_request(
        self,
        tool_id: str,
        request: Mapping[str, Any],
        *,
        scope: Mapping[str, Any],
        as_of: date,
        agent_id: str,
        stage: str,
    ) -> None:
        ticker = request.get("ticker")
        if (
            isinstance(ticker, str)
            and ticker
            and ticker not in scope["accepted_candidate_tickers"]
        ):
            raise ValueError("ticker is outside the accepted candidate scope")
        earliest = date.fromisoformat(scope.get("earliest_date", scope["as_of"]))
        request_as_of = request.get("as_of")
        if isinstance(request_as_of, str):
            request_date = date.fromisoformat(request_as_of)
            if not earliest <= request_date <= as_of:
                raise ValueError("query as_of is outside the authorized date scope")
        if "date_from" in request or "date_to" in request:
            date_from = date.fromisoformat(str(request["date_from"]))
            date_to = date.fromisoformat(str(request["date_to"]))
            if not earliest <= date_from <= date_to <= as_of:
                raise ValueError("inclusive date interval is outside the authorized scope")
        indicator = request.get("indicator")
        if isinstance(indicator, str) and indicator not in scope.get(
            "indicator_families", []
        ):
            raise ValueError("indicator family is outside the authorized scope")
        if tool_id == "get_rke_research_context":
            if request.get("agent_id") != agent_id:
                raise ValueError("RKE agent_id is outside the authorized scope")
            expected_layer = "superinvestor" if agent_id in L3_TOOL_ROSTER else "decision"
            if request.get("layer") != expected_layer:
                raise ValueError("RKE layer is outside the authorized scope")
            if agent_id not in L3_TOOL_ROSTER and (agent_id, stage) not in L4_STAGE_ROSTER:
                raise ValueError("RKE prior stage is outside the authorized scope")

    def _validate_bound_initial_calls(
        self,
        initial_requests: Sequence[tuple[str, Mapping[str, Any], str]],
        *,
        agent_id: str,
        stage: str,
        scope: Mapping[str, Any],
        as_of: str,
        preservation_overlay: Mapping[str, Any],
    ) -> None:
        actual = [
            {"tool_id": tool_id, "args": dict(request)}
            for tool_id, request, _ in initial_requests
        ]
        if agent_id in L3_TOOL_ROSTER:
            templates = preservation_overlay["l3_runtime_contract"][
                "deterministic_initial_calls"
            ][agent_id]
            ticker = scope["accepted_candidate_tickers"][0]
            expected = []
            for template in templates:
                args: dict[str, Any] = {"ticker": ticker, "as_of": as_of}
                if "frequency" in template:
                    args["frequency"] = template["frequency"]
                expected.append({"tool_id": template["tool_id"], "args": args})
        else:
            expected = [
                {
                    "tool_id": "get_rke_research_context",
                    "args": {
                        "agent_id": agent_id,
                        "as_of": as_of,
                        "layer": "decision",
                        "max_items": 3,
                    },
                }
            ]
        if actual != expected:
            raise ValueError(
                f"{agent_id}/{stage} deterministic initial calls do not match the contract"
            )

    def _validate_requests(
        self,
        query_requests: Sequence[Mapping[str, Any]],
        *,
        bindings: Mapping[str, Mapping[str, Any]],
        scope: Mapping[str, Any],
        as_of: date,
        agent_id: str,
    ) -> list[tuple[str, dict[str, Any], str]]:
        if (
            not isinstance(query_requests, Sequence)
            or isinstance(query_requests, (str, bytes))
            or not query_requests
        ):
            raise ValueError("query_requests must be a non-empty array")
        validated: list[tuple[str, dict[str, Any], str]] = []
        seen: set[tuple[str, str]] = set()
        for index, row in enumerate(query_requests):
            if not isinstance(row, Mapping) or set(row) != {"tool_id", "args"}:
                raise ValueError(f"query_requests[{index}] must contain tool_id and args")
            tool_id = _required_text(row["tool_id"], "tool_id")
            binding = bindings.get(tool_id)
            if binding is None:
                raise ValueError(f"tool {tool_id} is outside the staged Agent whitelist")
            request = row["args"]
            if not isinstance(request, Mapping):
                raise ValueError("query args must be an object")
            request_copy = json.loads(_canonical_json(request))
            errors = sorted(
                Draft202012Validator(
                    binding["argument_schema"], format_checker=FormatChecker()
                ).iter_errors(request_copy),
                key=lambda error: list(error.absolute_path),
            )
            if errors:
                location = ".".join(str(part) for part in errors[0].absolute_path) or "$"
                raise ValueError(
                    f"query argument schema violation at {location}: {errors[0].message}"
                )
            self._validate_authorized_request(
                tool_id,
                request_copy,
                scope=scope,
                as_of=as_of,
                agent_id=agent_id,
            )
            request_hash = canonical_hash(request_copy)
            key = (tool_id, request_hash)
            if key in seen:
                raise ValueError("frozen query requests must be unique")
            seen.add(key)
            validated.append((tool_id, request_copy, request_hash))
        validated.sort(key=lambda item: (item[0], item[2]))
        return validated

    def _validate_authorized_request(
        self,
        tool_id: str,
        request: Mapping[str, Any],
        *,
        scope: Mapping[str, Any],
        as_of: date,
        agent_id: str,
    ) -> None:
        ticker = request.get("ticker")
        if isinstance(ticker, str) and ticker and ticker not in scope["tickers"]:
            raise ValueError("ticker is outside the authorized scope")
        etf = request.get("etf")
        if isinstance(etf, str) and etf not in scope["etfs"]:
            raise ValueError("ETF is outside the authorized scope")
        earliest = date.fromisoformat(scope["earliest_date"])
        request_as_of = request.get("as_of")
        if isinstance(request_as_of, str):
            request_date = date.fromisoformat(request_as_of)
            if not earliest <= request_date <= as_of:
                raise ValueError("query as_of is outside the authorized date scope")
        if "date_from" in request or "date_to" in request:
            date_from = date.fromisoformat(str(request["date_from"]))
            date_to = date.fromisoformat(str(request["date_to"]))
            if not earliest <= date_from <= date_to <= as_of:
                raise ValueError("inclusive date interval is outside the authorized scope")
        filters = request.get("industry_filters")
        if isinstance(filters, list) and not set(filters) <= set(scope["sectors"]):
            raise ValueError("industry filter is outside the authorized scope")
        indicator = request.get("indicator")
        if isinstance(indicator, str) and indicator not in scope["indicator_families"]:
            raise ValueError("indicator family is outside the authorized scope")
        if tool_id == "get_rke_research_context":
            if request.get("agent_id") != agent_id:
                raise ValueError("RKE agent_id is outside the authorized scope")
            expected_layer = "relationship" if agent_id == "relationship_mapper" else "sector"
            if request.get("layer") != expected_layer:
                raise ValueError("RKE layer is outside the authorized scope")
            sector = request.get("sector")
            if isinstance(sector, str) and sector and sector not in scope["sectors"]:
                raise ValueError("RKE sector is outside the authorized scope")

    def read_initial_payloads(
        self, *, bundle_id: str, agent_id: str, stage: str
    ) -> list[dict[str, str]]:
        """Read deterministic/proactive payloads in their frozen invocation order."""

        bundle_id = _required_text(bundle_id, "bundle_id")
        agent_id = _required_text(agent_id, "agent_id")
        stage = _required_text(stage, "stage")
        with self._connect() as connection:
            bundle = connection.execute(
                "SELECT agent_id, stage, initial_request_refs_json "
                "FROM frozen_query_bundles WHERE bundle_id = ?",
                (bundle_id,),
            ).fetchone()
            if bundle is None:
                raise ValueError("unknown frozen query bundle")
            if bundle["agent_id"] != agent_id or bundle["stage"] != stage:
                raise ValueError("frozen initial payload scope/stage does not match its bundle")
            refs = json.loads(bundle["initial_request_refs_json"])
            if not isinstance(refs, list):
                raise ValueError("frozen initial request refs are malformed")
            payloads: list[dict[str, str]] = []
            for ref in refs:
                if not isinstance(ref, Mapping) or set(ref) != {"tool_id", "request_hash"}:
                    raise ValueError("frozen initial request ref is malformed")
                row = connection.execute(
                    "SELECT tool_id, request_hash, payload, payload_hash, call_mode "
                    "FROM frozen_query_payloads "
                    "WHERE bundle_id = ? AND tool_id = ? AND request_hash = ?",
                    (bundle_id, ref["tool_id"], ref["request_hash"]),
                ).fetchone()
                if row is None or row["call_mode"] != "INITIAL":
                    raise ValueError("frozen initial payload is unavailable")
                if row["payload_hash"] != canonical_hash({"text": row["payload"]}):
                    raise ValueError("frozen initial payload hash mismatch")
                payloads.append(
                    {
                        "tool_id": row["tool_id"],
                        "request_hash": row["request_hash"],
                        "payload": row["payload"],
                        "payload_hash": row["payload_hash"],
                    }
                )
        return payloads

    def start_session(self, *, bundle_id: str, agent_id: str, stage: str) -> str:
        bundle_id = _required_text(bundle_id, "bundle_id")
        agent_id = _required_text(agent_id, "agent_id")
        stage = _required_text(stage, "stage")
        with self._connect() as connection:
            bundle = connection.execute(
                "SELECT agent_id, stage, max_rounds "
                "FROM frozen_query_bundles WHERE bundle_id = ?",
                (bundle_id,),
            ).fetchone()
            if bundle is None:
                raise ValueError("unknown frozen query bundle")
            if bundle["agent_id"] != agent_id or bundle["stage"] != stage:
                raise ValueError("frozen query session scope does not match its bundle")
            if int(bundle["max_rounds"]) == 0:
                raise ValueError("frozen query bundle does not permit adaptive model calls")
            session_id = "frozen_session_" + uuid.uuid4().hex
            connection.execute(
                "INSERT INTO frozen_query_sessions VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    bundle_id,
                    agent_id,
                    stage,
                    self.clock().astimezone(timezone.utc).isoformat(),
                ),
            )
        return session_id

    def call(
        self,
        *,
        session_id: str,
        round_number: int,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> str:
        """Resolve one exact frozen request; no collector is reachable here."""

        return self._call(
            session_id=session_id,
            round_number=round_number,
            tool_id=tool_id,
            args=args,
        )

    def call_next(
        self,
        *,
        session_id: str,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> str:
        """Atomically consume the next permitted call in one capability session."""

        return self._call(
            session_id=session_id,
            round_number=None,
            tool_id=tool_id,
            args=args,
        )

    def _call(
        self,
        *,
        session_id: str,
        round_number: int | None,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> str:

        session_id = _required_text(session_id, "session_id")
        tool_id = _required_text(tool_id, "tool_id")
        if round_number is not None and (
            isinstance(round_number, bool) or not isinstance(round_number, int)
        ):
            raise ValueError("round_number must be an integer")
        if round_number is not None and round_number > 3:
            raise ValueError("maximum 3 adaptive query rounds exceeded")
        if round_number is not None and round_number < 1:
            raise ValueError("round_number must be positive")
        if not isinstance(args, Mapping):
            raise ValueError("query args must be an object")
        request_json = _canonical_json(args)
        request_hash = canonical_hash(json.loads(request_json))

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                session = connection.execute(
                    "SELECT sessions.bundle_id, bundles.max_rounds "
                    "FROM frozen_query_sessions AS sessions "
                    "JOIN frozen_query_bundles AS bundles "
                    "ON bundles.bundle_id = sessions.bundle_id "
                    "WHERE sessions.session_id = ?",
                    (session_id,),
                ).fetchone()
                if session is None:
                    raise ValueError("unknown frozen query session")
                max_rounds = int(session["max_rounds"])
                count = connection.execute(
                    "SELECT COUNT(*) AS count FROM frozen_query_calls WHERE session_id = ?",
                    (session_id,),
                ).fetchone()["count"]
                expected_round = int(count) + 1
                actual_round = expected_round if round_number is None else round_number
                if actual_round > max_rounds:
                    raise ValueError(
                        f"maximum {max_rounds} adaptive query rounds exceeded"
                    )
                if actual_round != expected_round:
                    raise ValueError(f"next round must be {expected_round}")
                row = connection.execute(
                    "SELECT * FROM frozen_query_payloads "
                    "WHERE bundle_id = ? AND tool_id = ? AND request_hash = ? "
                    "AND call_mode = 'FOLLOW_UP'",
                    (session["bundle_id"], tool_id, request_hash),
                ).fetchone()
                if row is None or row["request_json"] != request_json:
                    raise ValueError("query is not present in the frozen query bundle")
                payload = row["payload"]
                if row["payload_hash"] != canonical_hash({"text": payload}):
                    raise ValueError("frozen query payload hash mismatch")
                connection.execute(
                    "INSERT INTO frozen_query_calls VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        actual_round,
                        tool_id,
                        request_hash,
                        row["payload_hash"],
                        self.clock().astimezone(timezone.utc).isoformat(),
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return str(payload)


__all__ = ["FrozenAdaptiveQueryStore", "PUBLIC_PROJECTION_VERSION"]

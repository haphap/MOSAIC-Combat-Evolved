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

from mosaic.scorecard.capability_preservation import (
    load_capability_contract_bundle,
    validate_capability_contract_bundle,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l3_l4_preservation import (
    L3_TOOL_ROSTER,
    L4_STAGE_ROSTER,
    QUERY_BUNDLE_CONTRACT_VERSION as BOUND_RUNTIME_QUERY_BUNDLE_CONTRACT_VERSION,
    validate_l3_l4_preservation_overlay,
)
from mosaic.scorecard.l3_l4_activation import (
    active_argument_schema_for_l3_l4_binding,
    active_stage_for_l3_l4_overlay,
)
from mosaic.scorecard.sector_relationship_preservation import (
    QUERY_BUNDLE_CONTRACT_VERSION as SECTOR_QUERY_BUNDLE_CONTRACT_VERSION,
    SECTOR_AGENT_IDS,
    validate_sector_relationship_preservation_overlay,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_PROJECTION_VERSION = "frozen_adaptive_query_public_projection_v1"
CALL_TIME_ARGUMENT_CONTRACT = "EXACT_CALL_TIME_ARGS_ONLY"
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


def deferred_query_bundle_hash(projection: Mapping[str, Any]) -> str:
    """Hash the request-only fields of one deferred v1 public projection."""

    required = {
        "schema_version",
        "call_contract",
        "agent_id",
        "stage",
        "as_of",
        "authorized_scope_hash",
        "preservation_overlay_hash",
        "query_bundle_contract_version",
        "private_payload_count",
        "initial_payload_count",
        "adaptive_max_rounds",
        "entries",
    }
    if not required.issubset(projection):
        raise ValueError("deferred query projection fields are incomplete")
    descriptor = {key: projection[key] for key in sorted(required)}
    if "preservation_stage" in projection:
        descriptor["preservation_stage"] = projection["preservation_stage"]
    return canonical_hash(descriptor)


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


def _load_active_sector_bindings(
    *,
    agent_id: str,
    stage: str,
    query_requests: Sequence[Mapping[str, Any]],
    preservation_overlay: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    current_tool_manifest_path = (
        _REPO_ROOT / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
    )
    try:
        current_tool_manifest = json.loads(
            current_tool_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("active Agent tool authority is unavailable") from exc
    bundle = load_capability_contract_bundle(_REPO_ROOT)
    validate_capability_contract_bundle(
        bundle, current_tool_manifest=current_tool_manifest
    )
    requested_tool_ids = {
        str(row["tool_id"])
        for row in query_requests
        if isinstance(row, Mapping) and isinstance(row.get("tool_id"), str)
    }
    rows_by_tool: dict[str, list[Mapping[str, Any]]] = {
        tool_id: [] for tool_id in requested_tool_ids
    }
    for row in bundle["binding_manifest"]["bindings"]:
        tool_id = str(row["tool_id"])
        if (
            row["agent_id"] == agent_id
            and row["stage"] == stage
            and tool_id in rows_by_tool
        ):
            rows_by_tool[tool_id].append(row)
    bindings: dict[str, dict[str, Any]] = {}
    for tool_id, rows in rows_by_tool.items():
        if len(rows) != 1:
            raise ValueError(
                f"active Sector binding is not unique for {agent_id}/{tool_id}"
            )
        full_rows = [
            row
            for row in preservation_overlay["bindings"]
            if row["agent_id"] == agent_id
            and row["stage"] == stage
            and row["tool_id"] == tool_id
        ]
        if tool_id == "get_supply_chain_evidence" and not full_rows:
            full_rows = [
                row
                for row in preservation_overlay["bindings"]
                if row["agent_id"] == "relationship_mapper"
                and row["stage"] == "relationship_mapper"
                and row["tool_id"] == tool_id
            ]
        if len(full_rows) != 1:
            raise ValueError(
                f"historical full binding is not unique for {agent_id}/{tool_id}"
            )
        full_binding = full_rows[0]
        schema = full_binding["argument_schema"]
        materializer_contract = full_binding["materializer_contract"]
        binding = rows[0]
        if (
            binding["argument_schema_hash"] != canonical_hash(schema)
            or binding["materializer_contract_hash"]
            != canonical_hash(materializer_contract)
            or binding["query_bundle_contract_version"]
            != SECTOR_QUERY_BUNDLE_CONTRACT_VERSION
        ):
            raise ValueError(
                f"active Sector binding contract drift for {agent_id}/{tool_id}"
            )
        bindings[tool_id] = {
            **binding,
            "argument_schema": schema,
            "materializer_contract": materializer_contract,
        }
    return bindings


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
                CREATE TABLE IF NOT EXISTS frozen_query_call_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL CHECK(round_number BETWEEN 1 AND 3),
                    tool_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    reservation_json TEXT NOT NULL,
                    reservation_hash TEXT NOT NULL UNIQUE,
                    reserved_at TEXT NOT NULL,
                    UNIQUE(session_id, round_number),
                    FOREIGN KEY(session_id) REFERENCES frozen_query_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS frozen_query_call_finalizations (
                    reservation_id TEXT PRIMARY KEY,
                    result_event_id TEXT NOT NULL UNIQUE,
                    result_event_hash TEXT NOT NULL UNIQUE,
                    finalization_json TEXT NOT NULL,
                    finalization_hash TEXT NOT NULL UNIQUE,
                    finalized_at TEXT NOT NULL,
                    FOREIGN KEY(reservation_id)
                      REFERENCES frozen_query_call_reservations(reservation_id)
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
                CREATE TRIGGER IF NOT EXISTS frozen_query_call_reservations_no_update
                  BEFORE UPDATE ON frozen_query_call_reservations BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_call_reservations is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_call_reservations_no_delete
                  BEFORE DELETE ON frozen_query_call_reservations BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_call_reservations is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_call_finalizations_no_update
                  BEFORE UPDATE ON frozen_query_call_finalizations BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_call_finalizations is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS frozen_query_call_finalizations_no_delete
                  BEFORE DELETE ON frozen_query_call_finalizations BEGIN
                    SELECT RAISE(ABORT, 'frozen_query_call_finalizations is append-only');
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

    def bundle_evidence(self, bundle_id: str) -> dict[str, Any]:
        """Return validated hash-only lineage for one frozen private bundle."""

        bundle_id = _required_text(bundle_id, "bundle_id")
        with self._connect() as connection:
            bundle = connection.execute(
                "SELECT * FROM frozen_query_bundles WHERE bundle_id = ?",
                (bundle_id,),
            ).fetchone()
            rows = connection.execute(
                "SELECT * FROM frozen_query_payloads WHERE bundle_id = ? "
                "ORDER BY tool_id, request_hash",
                (bundle_id,),
            ).fetchall()
        if bundle is None:
            raise ValueError("unknown frozen query bundle")

        try:
            projection = json.loads(bundle["public_projection_json"])
            initial_request_refs = json.loads(bundle["initial_request_refs_json"])
        except json.JSONDecodeError as exc:
            raise ValueError("frozen query bundle metadata is invalid") from exc
        if not isinstance(projection, dict):
            raise ValueError("frozen query public projection is invalid")
        projection_hash = projection.get("projection_hash")
        projection_body = {
            key: value for key, value in projection.items() if key != "projection_hash"
        }
        if not _is_sha256(projection_hash) or projection_hash != canonical_hash(
            projection_body
        ):
            raise ValueError("frozen query public projection hash mismatch")
        preservation_stage = projection.get("preservation_stage")
        if preservation_stage is not None and (
            not isinstance(preservation_stage, str)
            or not preservation_stage.strip()
            or preservation_stage == bundle["stage"]
        ):
            raise ValueError("frozen query preservation stage is invalid")

        private_entries: list[dict[str, Any]] = []
        evidence_entries: list[dict[str, Any]] = []
        public_entries: list[dict[str, Any]] = []
        for row in rows:
            try:
                request = json.loads(row["request_json"])
                receipt_hashes = json.loads(row["source_receipt_hashes_json"])
                derivation = (
                    json.loads(row["derivation_json"])
                    if row["derivation_json"] is not None
                    else None
                )
            except json.JSONDecodeError as exc:
                raise ValueError("frozen query private metadata is invalid") from exc
            if canonical_hash(request) != row["request_hash"]:
                raise ValueError("frozen query request hash mismatch")
            if canonical_hash({"text": row["payload"]}) != row["payload_hash"]:
                raise ValueError("frozen query payload hash mismatch")
            if (
                not isinstance(receipt_hashes, list)
                or receipt_hashes != sorted(set(receipt_hashes))
                or not receipt_hashes
                or not all(_is_sha256(value) for value in receipt_hashes)
            ):
                raise ValueError("frozen query source receipt hashes are invalid")
            if derivation is None:
                if row["derivation_hash"] is not None:
                    raise ValueError("frozen query derivation hash mismatch")
            elif canonical_hash(derivation) != row["derivation_hash"]:
                raise ValueError("frozen query derivation hash mismatch")
            call_mode = row["call_mode"]
            if call_mode not in {"INITIAL", "FOLLOW_UP"}:
                raise ValueError("frozen query call mode is invalid")
            source_receipt_set_hash = canonical_hash(receipt_hashes)
            private_entry = {
                "tool_id": row["tool_id"],
                "request_hash": row["request_hash"],
                "call_mode": call_mode,
                "binding_id": row["binding_id"],
                "payload_hash": row["payload_hash"],
                "source_receipt_set_hash": source_receipt_set_hash,
                "derivation_hash": row["derivation_hash"],
            }
            private_entries.append(private_entry)
            public_entries.append(dict(private_entry))
            evidence_entries.append(
                {
                    "tool_id": row["tool_id"],
                    "request_hash": row["request_hash"],
                    "call_mode": call_mode,
                    "payload_hash": row["payload_hash"],
                    "source_receipt_hashes": receipt_hashes,
                    "source_receipt_set_hash": source_receipt_set_hash,
                }
            )

        private_descriptor = {
            "contract_version": projection.get("query_bundle_contract_version"),
            "materialization_key": bundle["materialization_key"],
            "agent_id": bundle["agent_id"],
            "stage": bundle["stage"],
            **(
                {"preservation_stage": preservation_stage}
                if preservation_stage is not None
                else {}
            ),
            "as_of": bundle["as_of"],
            "authorized_scope_hash": bundle["authorized_scope_hash"],
            "overlay_hash": bundle["overlay_hash"],
            "max_rounds": bundle["max_rounds"],
            "initial_request_refs": initial_request_refs,
            "entries": private_entries,
        }
        computed_bundle_hash = canonical_hash(private_descriptor)
        if (
            computed_bundle_hash != bundle["bundle_hash"]
            or projection.get("bundle_hash") != computed_bundle_hash
            or projection.get("bundle_id") != bundle_id
            or projection.get("agent_id") != bundle["agent_id"]
            or projection.get("stage") != bundle["stage"]
            or projection.get("as_of") != bundle["as_of"]
            or projection.get("entries") != public_entries
            or projection.get("private_payload_count") != len(evidence_entries)
        ):
            raise ValueError("frozen query bundle hash or projection mismatch")
        return {
            "bundle_id": bundle_id,
            "bundle_hash": computed_bundle_hash,
            "agent_id": bundle["agent_id"],
            "stage": bundle["stage"],
            "as_of": bundle["as_of"],
            "entries": evidence_entries,
        }

    def argument_sets(
        self,
        *,
        bundle_id: str,
        tool_id: str,
        expected_bundle_hash: str,
    ) -> list[dict[str, Any]]:
        """Return exact validated request objects without private result payloads."""

        tool_id = _required_text(tool_id, "tool_id")
        expected_bundle_hash = _required_text(
            expected_bundle_hash, "expected_bundle_hash"
        )
        if not _is_sha256(expected_bundle_hash):
            raise ValueError("expected_bundle_hash must be a sha256 digest")
        evidence = self.bundle_evidence(bundle_id)
        if evidence["bundle_hash"] != expected_bundle_hash:
            raise ValueError("frozen query bundle hash mismatch")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT request_hash, request_json FROM frozen_query_payloads "
                "WHERE bundle_id = ? AND tool_id = ? ORDER BY request_hash",
                (bundle_id, tool_id),
            ).fetchall()
        requests: list[dict[str, Any]] = []
        for row in rows:
            try:
                request = json.loads(row["request_json"])
            except json.JSONDecodeError as exc:  # pragma: no cover - bundle validation owns this
                raise ValueError("frozen query request metadata is invalid") from exc
            if not isinstance(request, dict) or canonical_hash(request) != row["request_hash"]:
                raise ValueError("frozen query request hash mismatch")
            requests.append(request)
        return requests

    def prepare(
        self,
        *,
        agent_id: str,
        stage: str,
        preservation_stage: str | None = None,
        as_of: str,
        authorized_scope: Mapping[str, Any],
        query_requests: Sequence[Mapping[str, Any]],
        initial_query_requests: Sequence[Mapping[str, Any]] = (),
        preservation_overlay: Mapping[str, Any],
        materializer: Callable[[str, dict[str, Any]], Mapping[str, Any]],
        defer_materialization: bool = False,
    ) -> dict[str, Any]:
        """Validate a finite scope and publish eager or deferred request hashes."""

        agent_id = _required_text(agent_id, "agent_id")
        stage = _required_text(stage, "stage")
        if not isinstance(defer_materialization, bool):
            raise ValueError("defer_materialization must be a boolean")
        if preservation_stage is not None:
            preservation_stage = _required_text(
                preservation_stage, "preservation_stage"
            )
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
            if preservation_stage not in {None, stage}:
                raise ValueError(
                    "Sector/Relationship preservation stage must equal active stage"
                )
            scope = self._validate_scope(authorized_scope, as_of=as_of)
            if agent_id not in {*SECTOR_AGENT_IDS, "relationship_mapper"}:
                raise ValueError("Agent is outside the PR6 frozen-query roster")
            bindings = (
                _load_active_sector_bindings(
                    agent_id=agent_id,
                    stage=stage,
                    query_requests=query_requests,
                    preservation_overlay=preservation_overlay,
                )
                if agent_id in SECTOR_AGENT_IDS
                else {
                    row["tool_id"]: row
                    for row in preservation_overlay["bindings"]
                    if row["agent_id"] == agent_id and row["stage"] == stage
                }
            )
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
            overlay_stage = preservation_stage or stage
            if (agent_id, overlay_stage) not in {
                *((l3_agent, l3_agent) for l3_agent in L3_TOOL_ROSTER),
                *L4_STAGE_ROSTER,
            }:
                raise ValueError("Agent/stage is outside the PR7 frozen-query roster")
            if (
                preservation_stage is not None
                and active_stage_for_l3_l4_overlay(agent_id, overlay_stage) != stage
            ):
                raise ValueError(
                    "active stage does not match the explicit preservation stage"
                )
            scope = self._validate_bound_scope(
                authorized_scope,
                as_of=as_of,
                l3=agent_id in L3_TOOL_ROSTER,
            )
            bindings = {
                row["tool_id"]: {
                    **row,
                    "argument_schema": active_argument_schema_for_l3_l4_binding(
                        agent_id, stage, row["tool_id"]
                    ),
                }
                for row in preservation_overlay["bindings"]
                if row["agent_id"] == agent_id and row["stage"] == overlay_stage
            }
            if (
                agent_id in L3_TOOL_ROSTER
                and not scope["accepted_candidate_tickers"]
                and (initial_query_requests or query_requests)
            ):
                raise ValueError("L3 empty candidate scope does not permit private queries")
            initial_requests = self._validate_bound_requests(
                initial_query_requests,
                bindings=bindings,
                scope=scope,
                as_of=as_of_date,
                agent_id=agent_id,
                stage=overlay_stage,
                allow_empty=True,
                preserve_order=True,
            )
            follow_up_requests = self._validate_bound_requests(
                query_requests,
                bindings=bindings,
                scope=scope,
                as_of=as_of_date,
                agent_id=agent_id,
                stage=overlay_stage,
                allow_empty=True,
                preserve_order=False,
            )
            self._validate_bound_initial_calls(
                initial_requests,
                agent_id=agent_id,
                stage=overlay_stage,
                scope=scope,
                as_of=as_of,
                preservation_overlay=preservation_overlay,
            )
            empty_l3_scope = (
                agent_id in L3_TOOL_ROSTER
                and not scope["accepted_candidate_tickers"]
            )
            if empty_l3_scope and (initial_requests or follow_up_requests):
                raise ValueError("L3 empty candidate scope does not permit private queries")
            if (
                not empty_l3_scope
                and not initial_requests
                and not follow_up_requests
            ):
                raise ValueError("bound runtime query bundle must not be empty")
            combined_keys = {
                (tool_id, request_hash)
                for tool_id, _, request_hash in [*initial_requests, *follow_up_requests]
            }
            if len(combined_keys) != len(initial_requests) + len(follow_up_requests):
                raise ValueError("initial and follow-up frozen requests must be unique")
            contract_version = BOUND_RUNTIME_QUERY_BUNDLE_CONTRACT_VERSION
            max_rounds = (
                3
                if agent_id in L3_TOOL_ROSTER and not empty_l3_scope
                else 0
            )
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
                **(
                    {"preservation_stage": preservation_stage}
                    if preservation_stage is not None and preservation_stage != stage
                    else {}
                ),
                "as_of": as_of,
                "authorized_scope": scope,
                "requests": private_request_descriptor,
                **(
                    {
                        "binding_ids": {
                            tool_id: bindings[tool_id]["binding_id"]
                            for tool_id in sorted({row[0] for row in requests})
                        }
                    }
                    if overlay_version
                    == "sector_relationship_preservation_overlay_v1"
                    else {}
                ),
                "max_rounds": max_rounds,
                "overlay_hash": overlay_hash,
            }
        )
        if defer_materialization:
            entries = sorted(
                (
                    {
                        "tool_id": tool_id,
                        "request": request,
                        "request_hash": request_hash,
                        "call_mode": call_mode,
                        "binding_id": bindings[tool_id]["binding_id"],
                    }
                    for tool_id, request, request_hash, call_mode in requests
                ),
                key=lambda row: (row["tool_id"], row["request_hash"]),
            )
            deferred_body = {
                "schema_version": PUBLIC_PROJECTION_VERSION,
                "call_contract": CALL_TIME_ARGUMENT_CONTRACT,
                "agent_id": agent_id,
                "stage": stage,
                **(
                    {"preservation_stage": preservation_stage}
                    if preservation_stage is not None and preservation_stage != stage
                    else {}
                ),
                "as_of": as_of,
                "authorized_scope_hash": canonical_hash(scope),
                "preservation_overlay_hash": overlay_hash,
                "query_bundle_contract_version": contract_version,
                "private_payload_count": 0,
                "initial_payload_count": len(initial_requests),
                "adaptive_max_rounds": max_rounds,
                "entries": entries,
            }
            bundle_hash = deferred_query_bundle_hash(deferred_body)
            bundle_id = "frozen_bundle_" + bundle_hash[7:]
            public_body = {
                **deferred_body,
                "bundle_id": bundle_id,
                "bundle_hash": bundle_hash,
            }
            return {
                "bundle_id": bundle_id,
                "public_projection": {
                    **public_body,
                    "projection_hash": canonical_hash(public_body),
                },
            }
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
                        preservation_stage=preservation_stage,
                        as_of=as_of,
                        authorized_scope=scope,
                        query_requests=query_requests,
                        initial_query_requests=initial_query_requests,
                        preservation_overlay=preservation_overlay,
                        materializer=materializer,
                        defer_materialization=False,
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
            **(
                {"preservation_stage": preservation_stage}
                if preservation_stage is not None and preservation_stage != stage
                else {}
            ),
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
            **(
                {"preservation_stage": preservation_stage}
                if preservation_stage is not None and preservation_stage != stage
                else {}
            ),
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
            allow_empty=True,
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
            expected = []
            if scope["accepted_candidate_tickers"]:
                ticker = scope["accepted_candidate_tickers"][0]
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

    @staticmethod
    def _audited_result(
        *, bundle_hash: str, row: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            receipt_hashes = json.loads(str(row["source_receipt_hashes_json"]))
            derivation = (
                json.loads(str(row["derivation_json"]))
                if row["derivation_json"] is not None
                else None
            )
        except json.JSONDecodeError as exc:
            raise ValueError("frozen query result authority is malformed") from exc
        if (
            not isinstance(receipt_hashes, list)
            or receipt_hashes != sorted(set(receipt_hashes))
            or not receipt_hashes
            or not all(_is_sha256(value) for value in receipt_hashes)
        ):
            raise ValueError("frozen query result source receipt authority is invalid")
        if canonical_hash({"text": row["payload"]}) != row["payload_hash"]:
            raise ValueError("frozen query result payload hash mismatch")
        if derivation is None:
            if row["derivation_hash"] is not None:
                raise ValueError("frozen query result derivation hash mismatch")
        elif canonical_hash(derivation) != row["derivation_hash"]:
            raise ValueError("frozen query result derivation hash mismatch")
        authority = {
            "schema_version": "frozen_query_result_authority_v1",
            "authority_type": "FROZEN_QUERY",
            "frozen_bundle_hash": bundle_hash,
            "request_hash": row["request_hash"],
            "payload_hash": row["payload_hash"],
            "source_receipt_set_hash": canonical_hash(receipt_hashes),
            "derivation_hash": row["derivation_hash"],
        }
        return {
            "tool_id": row["tool_id"],
            "call_mode": row["call_mode"],
            "request_hash": row["request_hash"],
            "payload": row["payload"],
            "payload_hash": row["payload_hash"],
            "result_authority": {
                **authority,
                "authority_hash": canonical_hash(authority),
            },
        }

    def read_initial_results(
        self, *, bundle_id: str, agent_id: str, stage: str
    ) -> list[dict[str, Any]]:
        """Read deterministic payloads with immutable private result authority."""

        bundle_id = _required_text(bundle_id, "bundle_id")
        agent_id = _required_text(agent_id, "agent_id")
        stage = _required_text(stage, "stage")
        evidence = self.bundle_evidence(bundle_id)
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
            results: list[dict[str, Any]] = []
            for ref in refs:
                if not isinstance(ref, Mapping) or set(ref) != {"tool_id", "request_hash"}:
                    raise ValueError("frozen initial request ref is malformed")
                row = connection.execute(
                    "SELECT * FROM frozen_query_payloads "
                    "WHERE bundle_id = ? AND tool_id = ? AND request_hash = ?",
                    (bundle_id, ref["tool_id"], ref["request_hash"]),
                ).fetchone()
                if row is None or row["call_mode"] != "INITIAL":
                    raise ValueError("frozen initial payload is unavailable")
                results.append(
                    self._audited_result(
                        bundle_hash=evidence["bundle_hash"], row=row
                    )
                )
        return results

    def read_initial_payloads(
        self, *, bundle_id: str, agent_id: str, stage: str
    ) -> list[dict[str, str]]:
        """Compatibility projection of deterministic frozen results."""

        return [
            {
                "tool_id": str(row["tool_id"]),
                "request_hash": str(row["request_hash"]),
                "payload": str(row["payload"]),
                "payload_hash": str(row["payload_hash"]),
            }
            for row in self.read_initial_results(
                bundle_id=bundle_id, agent_id=agent_id, stage=stage
            )
        ]

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

    def _reserved_result_from_connection(
        self,
        connection: sqlite3.Connection,
        *,
        reservation_id: str,
    ) -> tuple[str, sqlite3.Row, dict[str, Any]]:
        reservation_row = connection.execute(
            "SELECT * FROM frozen_query_call_reservations WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if reservation_row is None:
            raise ValueError("unknown frozen query reservation")
        session = connection.execute(
            "SELECT bundle_id FROM frozen_query_sessions WHERE session_id = ?",
            (reservation_row["session_id"],),
        ).fetchone()
        if session is None:
            raise ValueError("frozen query reservation session is unavailable")
        payload_row = connection.execute(
            "SELECT * FROM frozen_query_payloads "
            "WHERE bundle_id = ? AND tool_id = ? AND request_hash = ? "
            "AND call_mode = 'FOLLOW_UP'",
            (
                session["bundle_id"],
                reservation_row["tool_id"],
                reservation_row["request_hash"],
            ),
        ).fetchone()
        if (
            payload_row is None
            or payload_row["request_json"] != reservation_row["request_json"]
            or payload_row["payload_hash"] != reservation_row["payload_hash"]
        ):
            raise ValueError("frozen query reservation payload authority mismatch")
        try:
            reservation = json.loads(reservation_row["reservation_json"])
        except json.JSONDecodeError as exc:
            raise ValueError("frozen query reservation authority is malformed") from exc
        expected = {
            "schema_version": "frozen_query_call_reservation_v1",
            "reservation_id": reservation_row["reservation_id"],
            "session_id": reservation_row["session_id"],
            "round_number": int(reservation_row["round_number"]),
            "tool_id": reservation_row["tool_id"],
            "request_hash": reservation_row["request_hash"],
            "payload_hash": reservation_row["payload_hash"],
            "reserved_at": reservation_row["reserved_at"],
        }
        expected_hash = canonical_hash(expected)
        if reservation != {**expected, "reservation_hash": expected_hash} or (
            reservation_row["reservation_hash"] != expected_hash
        ):
            raise ValueError("frozen query reservation authority mismatch")
        return str(session["bundle_id"]), payload_row, reservation

    def reserve_next_result(
        self,
        *,
        reservation_id: str,
        session_id: str,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Idempotently reserve one adaptive round without finalizing consumption."""

        reservation_id = _required_text(reservation_id, "reservation_id")
        session_id = _required_text(session_id, "session_id")
        tool_id = _required_text(tool_id, "tool_id")
        if not isinstance(args, Mapping):
            raise ValueError("query args must be an object")
        request_json = _canonical_json(args)
        request_hash = canonical_hash(json.loads(request_json))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT session_id, tool_id, request_hash, request_json "
                    "FROM frozen_query_call_reservations WHERE reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["session_id"] != session_id
                        or existing["tool_id"] != tool_id
                        or existing["request_hash"] != request_hash
                        or existing["request_json"] != request_json
                    ):
                        raise ValueError("frozen query reservation intent mismatch")
                    bundle_id, payload_row, reservation = (
                        self._reserved_result_from_connection(
                            connection, reservation_id=reservation_id
                        )
                    )
                else:
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
                    occupied_rounds = [
                        int(row["round_number"])
                        for row in connection.execute(
                            "SELECT round_number FROM frozen_query_calls "
                            "WHERE session_id = ? UNION SELECT round_number "
                            "FROM frozen_query_call_reservations WHERE session_id = ? "
                            "ORDER BY round_number",
                            (session_id, session_id),
                        ).fetchall()
                    ]
                    if occupied_rounds != list(range(1, len(occupied_rounds) + 1)):
                        raise ValueError("frozen query round authority is not contiguous")
                    actual_round = len(occupied_rounds) + 1
                    max_rounds = int(session["max_rounds"])
                    if actual_round > max_rounds:
                        raise ValueError(
                            f"maximum {max_rounds} adaptive query rounds exceeded"
                        )
                    payload_row = connection.execute(
                        "SELECT * FROM frozen_query_payloads "
                        "WHERE bundle_id = ? AND tool_id = ? AND request_hash = ? "
                        "AND call_mode = 'FOLLOW_UP'",
                        (session["bundle_id"], tool_id, request_hash),
                    ).fetchone()
                    if payload_row is None or payload_row["request_json"] != request_json:
                        raise ValueError("query is not present in the frozen query bundle")
                    if payload_row["payload_hash"] != canonical_hash(
                        {"text": payload_row["payload"]}
                    ):
                        raise ValueError("frozen query payload hash mismatch")
                    reserved_at = self.clock().astimezone(timezone.utc).isoformat()
                    reservation_body = {
                        "schema_version": "frozen_query_call_reservation_v1",
                        "reservation_id": reservation_id,
                        "session_id": session_id,
                        "round_number": actual_round,
                        "tool_id": tool_id,
                        "request_hash": request_hash,
                        "payload_hash": payload_row["payload_hash"],
                        "reserved_at": reserved_at,
                    }
                    reservation_hash = canonical_hash(reservation_body)
                    reservation = {
                        **reservation_body,
                        "reservation_hash": reservation_hash,
                    }
                    connection.execute(
                        "INSERT INTO frozen_query_call_reservations "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            reservation_id,
                            session_id,
                            actual_round,
                            tool_id,
                            request_hash,
                            request_json,
                            payload_row["payload_hash"],
                            _canonical_json(reservation),
                            reservation_hash,
                            reserved_at,
                        ),
                    )
                    bundle_id = str(session["bundle_id"])
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        evidence = self.bundle_evidence(bundle_id)
        return {
            **self._audited_result(
                bundle_hash=evidence["bundle_hash"], row=payload_row
            ),
            "reservation": reservation,
        }

    def read_reserved_result(self, *, reservation_id: str) -> dict[str, Any]:
        """Reload one immutable reservation for capability-side recovery."""

        reservation_id = _required_text(reservation_id, "reservation_id")
        with self._connect() as connection:
            bundle_id, payload_row, reservation = self._reserved_result_from_connection(
                connection, reservation_id=reservation_id
            )
        evidence = self.bundle_evidence(bundle_id)
        return {
            **self._audited_result(
                bundle_hash=evidence["bundle_hash"], row=payload_row
            ),
            "reservation": reservation,
        }

    def finalize_reserved_result(
        self,
        *,
        reservation_id: str,
        result_event_id: str,
        result_event_hash: str,
    ) -> dict[str, Any]:
        """Idempotently bind a reservation to its committed server result event."""

        reservation_id = _required_text(reservation_id, "reservation_id")
        result_event_id = _required_text(result_event_id, "result_event_id")
        if not _is_sha256(result_event_hash):
            raise ValueError("result_event_hash must be a sha256 hash")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _, _, reservation = self._reserved_result_from_connection(
                    connection, reservation_id=reservation_id
                )
                existing = connection.execute(
                    "SELECT * FROM frozen_query_call_finalizations "
                    "WHERE reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if existing is not None:
                    try:
                        finalization = json.loads(existing["finalization_json"])
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            "frozen query reservation finalization is malformed"
                        ) from exc
                    finalization_body = {
                        "schema_version": "frozen_query_call_finalization_v1",
                        "reservation_id": reservation_id,
                        "session_id": reservation["session_id"],
                        "round_number": reservation["round_number"],
                        "result_event_id": result_event_id,
                        "result_event_hash": result_event_hash,
                        "finalized_at": existing["finalized_at"],
                    }
                    finalization_hash = canonical_hash(finalization_body)
                    if (
                        existing["result_event_id"] != result_event_id
                        or existing["result_event_hash"] != result_event_hash
                        or existing["finalization_hash"] != finalization_hash
                        or finalization
                        != {**finalization_body, "finalization_hash": finalization_hash}
                    ):
                        raise ValueError("frozen query reservation finalization mismatch")
                else:
                    prior_call = connection.execute(
                        "SELECT 1 FROM frozen_query_calls "
                        "WHERE session_id = ? AND round_number = ?",
                        (reservation["session_id"], reservation["round_number"]),
                    ).fetchone()
                    if prior_call is not None:
                        raise ValueError("frozen query reservation call authority mismatch")
                    finalized_at = self.clock().astimezone(timezone.utc).isoformat()
                    finalization_body = {
                        "schema_version": "frozen_query_call_finalization_v1",
                        "reservation_id": reservation_id,
                        "session_id": reservation["session_id"],
                        "round_number": reservation["round_number"],
                        "result_event_id": result_event_id,
                        "result_event_hash": result_event_hash,
                        "finalized_at": finalized_at,
                    }
                    finalization_hash = canonical_hash(finalization_body)
                    finalization = {
                        **finalization_body,
                        "finalization_hash": finalization_hash,
                    }
                    connection.execute(
                        "INSERT INTO frozen_query_calls VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            reservation["session_id"],
                            reservation["round_number"],
                            reservation["tool_id"],
                            reservation["request_hash"],
                            reservation["payload_hash"],
                            reservation["reserved_at"],
                        ),
                    )
                    connection.execute(
                        "INSERT INTO frozen_query_call_finalizations "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            reservation_id,
                            result_event_id,
                            result_event_hash,
                            _canonical_json(finalization),
                            finalization_hash,
                            finalized_at,
                        ),
                    )
                call = connection.execute(
                    "SELECT tool_id, request_hash, payload_hash FROM frozen_query_calls "
                    "WHERE session_id = ? AND round_number = ?",
                    (reservation["session_id"], reservation["round_number"]),
                ).fetchone()
                if call is None or dict(call) != {
                    "tool_id": reservation["tool_id"],
                    "request_hash": reservation["request_hash"],
                    "payload_hash": reservation["payload_hash"],
                }:
                    raise ValueError("frozen query reservation call authority mismatch")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return finalization

    def read_reserved_finalization(
        self, *, reservation_id: str
    ) -> dict[str, Any] | None:
        """Read and fully revalidate an optional reservation finalization."""

        reservation_id = _required_text(reservation_id, "reservation_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_event_id, result_event_hash "
                "FROM frozen_query_call_finalizations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
        if row is None:
            return None
        return self.finalize_reserved_result(
            reservation_id=reservation_id,
            result_event_id=str(row["result_event_id"]),
            result_event_hash=str(row["result_event_hash"]),
        )

    def call(
        self,
        *,
        session_id: str,
        round_number: int,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> str:
        """Resolve one exact frozen request; no collector is reachable here."""

        return str(
            self.call_result(
                session_id=session_id,
                round_number=round_number,
                tool_id=tool_id,
                args=args,
            )["payload"]
        )

    def call_result(
        self,
        *,
        session_id: str,
        round_number: int,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resolve one exact frozen request with its immutable result authority."""

        return self._call_result(
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

        return str(
            self.call_next_result(
                session_id=session_id,
                tool_id=tool_id,
                args=args,
            )["payload"]
        )

    def call_next_result(
        self,
        *,
        session_id: str,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically consume the next call and return its result authority."""

        return self._call_result(
            session_id=session_id,
            round_number=None,
            tool_id=tool_id,
            args=args,
        )

    def _call_result(
        self,
        *,
        session_id: str,
        round_number: int | None,
        tool_id: str,
        args: Mapping[str, Any],
    ) -> dict[str, Any]:

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
                occupied_rounds = [
                    int(row["round_number"])
                    for row in connection.execute(
                        "SELECT round_number FROM frozen_query_calls "
                        "WHERE session_id = ? UNION SELECT round_number "
                        "FROM frozen_query_call_reservations WHERE session_id = ? "
                        "ORDER BY round_number",
                        (session_id, session_id),
                    ).fetchall()
                ]
                if occupied_rounds != list(range(1, len(occupied_rounds) + 1)):
                    raise ValueError("frozen query round authority is not contiguous")
                expected_round = len(occupied_rounds) + 1
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
        evidence = self.bundle_evidence(str(session["bundle_id"]))
        return self._audited_result(bundle_hash=evidence["bundle_hash"], row=row)


__all__ = [
    "CALL_TIME_ARGUMENT_CONTRACT",
    "FrozenAdaptiveQueryStore",
    "PUBLIC_PROJECTION_VERSION",
    "deferred_query_bundle_hash",
]

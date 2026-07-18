"""Server-enforced, bundle-bound capabilities for model-callable tools.

The model never receives the signed envelope.  The TypeScript runtime keeps it
out of band and only exposes zero-argument LangChain tools.  Every payload is
materialised before the model call, hashed into one immutable bundle, and read
back from the local ledger; ``tools.call`` never reaches a collector.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Final, Literal, Mapping, cast

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_snapshots import render_role_snapshot
from mosaic.dataflows.market_breadth import render_market_breadth_snapshot
from mosaic.dataflows.role_events import render_role_event_snapshot
from mosaic.dataflows.sector_snapshots import (
    render_relationship_snapshot,
    render_sector_snapshot,
)

AgentToolId = Literal[
    "get_china_macro_snapshot",
    "get_us_macro_snapshot",
    "get_eu_macro_snapshot",
    "get_central_bank_snapshot",
    "get_us_financial_conditions_snapshot",
    "get_euro_area_financial_conditions_snapshot",
    "get_commodity_conditions_snapshot",
    "get_geopolitical_events_snapshot",
    "get_market_breadth_snapshot",
    "get_market_positioning_snapshot",
    "get_sector_research_snapshot",
    "get_role_event_snapshot",
    "get_relationship_graph_snapshot",
    "get_superinvestor_candidate_snapshot",
    "get_cro_risk_snapshot",
    "get_alpha_candidate_snapshot",
    "get_execution_snapshot",
    "get_cio_decision_snapshot",
]

AGENT_TOOL_IDS: Final[tuple[AgentToolId, ...]] = (
    "get_china_macro_snapshot",
    "get_us_macro_snapshot",
    "get_eu_macro_snapshot",
    "get_central_bank_snapshot",
    "get_us_financial_conditions_snapshot",
    "get_euro_area_financial_conditions_snapshot",
    "get_commodity_conditions_snapshot",
    "get_geopolitical_events_snapshot",
    "get_market_breadth_snapshot",
    "get_market_positioning_snapshot",
    "get_sector_research_snapshot",
    "get_role_event_snapshot",
    "get_relationship_graph_snapshot",
    "get_superinvestor_candidate_snapshot",
    "get_cro_risk_snapshot",
    "get_alpha_candidate_snapshot",
    "get_execution_snapshot",
    "get_cio_decision_snapshot",
)


def _load_runtime_tool_contract() -> tuple[
    tuple[str, ...], dict[str, tuple[str, ...]], dict[str, tuple[AgentToolId, ...]]
]:
    """Load the TypeScript-generated roster and tool whitelist artifact."""
    path = (
        Path(__file__).resolve().parents[2]
        / "registry"
        / "prompt_checks"
        / "agent_tool_contract_manifest_v1.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load canonical Agent tool contract: {exc}") from exc
    if payload.get("schema_version") != "agent_tool_contract_manifest_v1":
        raise RuntimeError("canonical Agent tool contract version mismatch")
    rows = payload.get("agents")
    if not isinstance(rows, list) or len(rows) != 28:
        raise RuntimeError("canonical Agent tool contract must contain 28 agents")

    agent_ids: list[str] = []
    by_layer: dict[str, list[str]] = {
        "macro": [],
        "sector": [],
        "superinvestor": [],
        "decision": [],
    }
    matrix: dict[str, tuple[AgentToolId, ...]] = {}
    known_tools = set(AGENT_TOOL_IDS)
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Agent tool contract rows must be objects")
        agent = row.get("agent_id")
        layer = row.get("layer")
        tools = row.get("allowed_tools")
        if not isinstance(agent, str) or not agent or agent in matrix:
            raise RuntimeError("Agent tool contract has an invalid or duplicate agent")
        if layer not in by_layer:
            raise RuntimeError(f"Agent tool contract has unknown layer {layer!r}")
        if (
            not isinstance(tools, list)
            or not tools
            or any(not isinstance(tool, str) or tool not in known_tools for tool in tools)
            or len(tools) != len(set(tools))
        ):
            raise RuntimeError(f"Agent tool contract has invalid tools for {agent}")
        agent_ids.append(agent)
        by_layer[layer].append(agent)
        matrix[agent] = cast(tuple[AgentToolId, ...], tuple(tools))

    if len(agent_ids) != len(set(agent_ids)) or payload.get("agent_count") != 28:
        raise RuntimeError("Agent tool contract roster count mismatch")
    return (
        tuple(agent_ids),
        {layer: tuple(agents) for layer, agents in by_layer.items()},
        matrix,
    )


ALL_AGENT_IDS, AGENTS_BY_LAYER, AGENT_TOOL_MATRIX = _load_runtime_tool_contract()
STANDARD_SECTOR_AGENTS: Final[tuple[str, ...]] = tuple(
    agent for agent in AGENTS_BY_LAYER["sector"] if agent != "relationship_mapper"
)
SUPERINVESTOR_AGENTS: Final[tuple[str, ...]] = AGENTS_BY_LAYER["superinvestor"]
DECISION_AGENTS: Final[tuple[str, ...]] = AGENTS_BY_LAYER["decision"]
MACRO_AGENT_TO_TOOL: Final[dict[str, AgentToolId]] = {
    agent: AGENT_TOOL_MATRIX[agent][0] for agent in AGENTS_BY_LAYER["macro"]
}
if any(len(AGENT_TOOL_MATRIX[agent]) != 1 for agent in MACRO_AGENT_TO_TOOL):
    raise RuntimeError("every Macro agent must have exactly one role snapshot tool")

TOOL_DESCRIPTIONS: Final[dict[AgentToolId, str]] = {
    "get_china_macro_snapshot": "Return the frozen China macro snapshot for this run.",
    "get_us_macro_snapshot": "Return the frozen US real-economy snapshot for this run.",
    "get_eu_macro_snapshot": "Return the frozen EU real-economy snapshot for this run.",
    "get_central_bank_snapshot": "Return the frozen PBOC and China rates snapshot.",
    "get_us_financial_conditions_snapshot": "Return the frozen US financial-conditions snapshot.",
    "get_euro_area_financial_conditions_snapshot": "Return the frozen euro-area financial-conditions snapshot.",
    "get_commodity_conditions_snapshot": "Return the frozen commodity-conditions snapshot.",
    "get_geopolitical_events_snapshot": "Return the frozen verified geopolitical-event snapshot.",
    "get_market_breadth_snapshot": "Return the frozen deterministic A-share breadth snapshot.",
    "get_market_positioning_snapshot": "Return the frozen A-share positioning snapshot.",
    "get_sector_research_snapshot": "Return the frozen role-scoped Sector research snapshot.",
    "get_role_event_snapshot": "Return the frozen event projection for the bound role.",
    "get_relationship_graph_snapshot": "Return the frozen cross-sector relationship graph.",
    "get_superinvestor_candidate_snapshot": "Return the frozen candidate view for this investment philosophy.",
    "get_cro_risk_snapshot": "Return the frozen CRO risk and constraint snapshot.",
    "get_alpha_candidate_snapshot": "Return the frozen novel-alpha candidate snapshot.",
    "get_execution_snapshot": "Return the frozen execution-feasibility snapshot.",
    "get_cio_decision_snapshot": "Return the frozen CIO proposal or final decision snapshot.",
}
if set(TOOL_DESCRIPTIONS) != set(AGENT_TOOL_IDS):
    raise RuntimeError("tool description registry must exactly cover AgentToolId")

SNAPSHOT_BUNDLE_CONTRACT_VERSION: Final = "agent_snapshot_bundle_v1"
CAPABILITY_CONTRACT_VERSION: Final = "agent_tool_capability_v1"
DEFAULT_CAPABILITY_TTL_SECONDS: Final = 900


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def execution_stage_for_agent(agent_id: str, requested_stage: str | None = None) -> str:
    """Return one of the 29 closed execution-stage identifiers."""
    if agent_id not in ALL_AGENT_IDS:
        raise ValueError(f"unknown v3 agent_id {agent_id!r}")
    if agent_id != "cio":
        expected = agent_id
        if requested_stage not in (None, expected):
            raise ValueError(f"{agent_id} capability stage must be {expected!r}")
        return expected
    if requested_stage not in ("cio_proposal", "cio_final"):
        raise ValueError("cio capability stage must be 'cio_proposal' or 'cio_final'")
    return requested_stage


def allowed_tools_for_agent(agent_id: str) -> tuple[AgentToolId, ...]:
    try:
        return AGENT_TOOL_MATRIX[agent_id]
    except KeyError as exc:
        raise ValueError(f"unknown v3 agent_id {agent_id!r}") from exc


def _runtime_snapshot_root() -> Path:
    explicit = os.getenv("MOSAIC_RUNTIME_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache / "runtime_snapshots"


def _load_bound_snapshot(
    *, tool_id: AgentToolId, agent_id: str, stage: str, as_of: str
) -> str:
    """Load a collector-produced, role-bound payload for non-Macro tools."""
    root = _runtime_snapshot_root()
    candidates = (
        root / as_of / f"{agent_id}.{stage}.{tool_id}.json",
        root / as_of / f"{agent_id}.{tool_id}.json",
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise DataVendorUnavailable(
            f"no frozen runtime snapshot for {agent_id}/{stage}/{tool_id} on {as_of}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(f"cannot read runtime snapshot {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DataVendorUnavailable("runtime snapshot must be an object")
    if payload.get("agent_id") != agent_id or payload.get("as_of") != as_of:
        raise DataVendorUnavailable("runtime snapshot agent/as_of mismatch")
    payload_stage = payload.get("stage")
    if payload_stage is not None and payload_stage != stage:
        raise DataVendorUnavailable("runtime snapshot stage mismatch")
    if not isinstance(payload.get("contract_version"), str):
        raise DataVendorUnavailable("runtime snapshot contract_version is required")
    return _canonical_json(payload)


def materialize_tool_payload(
    tool_id: AgentToolId,
    *,
    agent_id: str,
    stage: str,
    as_of: str,
    graph_run_id: str = "standalone_tool_materialization",
) -> str:
    """Materialise one payload before capability issuance."""
    role_by_tool = {tool: role for role, tool in MACRO_AGENT_TO_TOOL.items()}
    if tool_id in role_by_tool:
        role = role_by_tool[tool_id]
        if role != agent_id:
            raise ValueError(f"{tool_id} cannot be materialised for {agent_id}")
        if tool_id == "get_market_breadth_snapshot":
            return render_market_breadth_snapshot(as_of)
        return render_role_snapshot(role, as_of)
    if tool_id == "get_sector_research_snapshot":
        return render_sector_snapshot(agent_id, as_of)
    if tool_id == "get_relationship_graph_snapshot":
        if agent_id != "relationship_mapper":
            raise ValueError("relationship graph is restricted to relationship_mapper")
        return render_relationship_snapshot(as_of, graph_run_id)
    if tool_id == "get_role_event_snapshot":
        return render_role_event_snapshot(agent_id, as_of)
    return _load_bound_snapshot(
        tool_id=tool_id,
        agent_id=agent_id,
        stage=stage,
        as_of=as_of,
    )


@dataclass(frozen=True)
class SignedCapability:
    manifest: dict[str, Any]
    signing_key_id: str
    signature: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest,
            "signing_key_id": self.signing_key_id,
            "signature": self.signature,
        }


class AgentToolCapabilityStore:
    """SQLite-backed append-only bundle, capability-event and use ledger."""

    def __init__(
        self,
        db_path: Path,
        *,
        signing_key: bytes,
        signing_key_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.signing_key = signing_key
        self.signing_key_id = signing_key_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialise(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshot_bundles (
                    snapshot_bundle_id TEXT PRIMARY KEY,
                    snapshot_bundle_hash TEXT NOT NULL UNIQUE,
                    materialization_request_id TEXT NOT NULL UNIQUE,
                    bundle_json TEXT NOT NULL,
                    payloads_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS materialization_requests (
                    materialization_request_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    requested_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capabilities (
                    capability_id TEXT PRIMARY KEY,
                    snapshot_bundle_id TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    signing_key_id TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(snapshot_bundle_id)
                      REFERENCES snapshot_bundles(snapshot_bundle_id)
                );
                CREATE TABLE IF NOT EXISTS capability_events (
                    event_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('ISSUED', 'TERMINATED')),
                    event_at TEXT NOT NULL,
                    reason TEXT,
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_termination_per_capability
                  ON capability_events(capability_id)
                  WHERE event_type = 'TERMINATED';
                CREATE TABLE IF NOT EXISTS capability_tool_uses (
                    capability_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    PRIMARY KEY(capability_id, tool_id),
                    FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id)
                );
                CREATE TRIGGER IF NOT EXISTS snapshot_bundles_no_update
                  BEFORE UPDATE ON snapshot_bundles BEGIN
                    SELECT RAISE(ABORT, 'snapshot_bundles is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS snapshot_bundles_no_delete
                  BEFORE DELETE ON snapshot_bundles BEGIN
                    SELECT RAISE(ABORT, 'snapshot_bundles is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS materialization_requests_no_update
                  BEFORE UPDATE ON materialization_requests BEGIN
                    SELECT RAISE(ABORT, 'materialization_requests is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS materialization_requests_no_delete
                  BEFORE DELETE ON materialization_requests BEGIN
                    SELECT RAISE(ABORT, 'materialization_requests is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capabilities_no_update
                  BEFORE UPDATE ON capabilities BEGIN
                    SELECT RAISE(ABORT, 'capabilities is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capabilities_no_delete
                  BEFORE DELETE ON capabilities BEGIN
                    SELECT RAISE(ABORT, 'capabilities is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_events_no_update
                  BEFORE UPDATE ON capability_events BEGIN
                    SELECT RAISE(ABORT, 'capability_events is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_events_no_delete
                  BEFORE DELETE ON capability_events BEGIN
                    SELECT RAISE(ABORT, 'capability_events is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_tool_uses_no_update
                  BEFORE UPDATE ON capability_tool_uses BEGIN
                    SELECT RAISE(ABORT, 'capability_tool_uses is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS capability_tool_uses_no_delete
                  BEFORE DELETE ON capability_tool_uses BEGIN
                    SELECT RAISE(ABORT, 'capability_tool_uses is append-only');
                  END;
                """
            )

    def _sign(self, manifest: Mapping[str, Any]) -> str:
        return "hmac-sha256:" + hmac.new(
            self.signing_key,
            _canonical_json(manifest).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def prepare(
        self,
        request: Mapping[str, Any],
        *,
        materializer: Callable[..., str] = materialize_tool_payload,
    ) -> dict[str, Any]:
        graph_run_id = _required_string(request, "graph_run_id")
        run_slot_id = _required_string(request, "run_slot_id")
        run_id = _required_string(request, "run_id")
        node_id = _required_string(request, "node_id")
        agent_id = _required_string(request, "agent_id")
        stage = execution_stage_for_agent(agent_id, request.get("stage"))
        as_of = _required_string(request, "as_of")
        date.fromisoformat(as_of)
        materialization_request_id = _required_string(
            request, "materialization_request_id"
        )
        runtime_inputs = request.get("runtime_inputs", {})
        candidate_scope = request.get("candidate_scope")
        if not isinstance(runtime_inputs, dict):
            raise ValueError("runtime_inputs must be an object")
        if candidate_scope is not None and not isinstance(candidate_scope, dict):
            raise ValueError("candidate_scope must be an object or null")

        now = self.clock().astimezone(timezone.utc)
        ttl = request.get("ttl_seconds", DEFAULT_CAPABILITY_TTL_SECONDS)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 3600:
            raise ValueError("ttl_seconds must be an integer in [1, 3600]")
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO materialization_requests VALUES (?, ?, ?, ?, ?)",
                    (materialization_request_id, agent_id, stage, as_of, now.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("materialization_request_id has already been used") from exc

        allowed_tools = allowed_tools_for_agent(agent_id)
        payloads = {
            tool_id: materializer(
                tool_id,
                agent_id=agent_id,
                stage=stage,
                as_of=as_of,
                graph_run_id=graph_run_id,
            )
            for tool_id in allowed_tools
        }
        if set(payloads) != set(allowed_tools):
            raise ValueError("materialized payload keys do not match allowed tools")
        if any(not isinstance(payload, str) or not payload for payload in payloads.values()):
            raise ValueError("every materialized tool payload must be a non-empty string")

        snapshot_bundle_id = f"bundle_{uuid.uuid4().hex}"
        payload_hashes = {
            tool_id: _sha256_text(payload) for tool_id, payload in payloads.items()
        }
        bundle_without_hash = {
            "snapshot_bundle_id": snapshot_bundle_id,
            "snapshot_bundle_contract_version": SNAPSHOT_BUNDLE_CONTRACT_VERSION,
            "materialization_request_id": materialization_request_id,
            "agent_id": agent_id,
            "stage": stage,
            "as_of": as_of,
            "candidate_scope_hash": _sha256(candidate_scope) if candidate_scope is not None else None,
            "runtime_input_hash": _sha256(runtime_inputs),
            "tool_payload_hashes": payload_hashes,
            "materialized_at": now.isoformat(),
        }
        snapshot_bundle_hash = _sha256(bundle_without_hash)
        bundle = {
            **bundle_without_hash,
            "snapshot_bundle_hash": snapshot_bundle_hash,
        }
        capability_id = f"cap_{uuid.uuid4().hex}"
        manifest = {
            "capability_contract_version": CAPABILITY_CONTRACT_VERSION,
            "capability_id": capability_id,
            "graph_run_id": graph_run_id,
            "run_slot_id": run_slot_id,
            "run_id": run_id,
            "node_id": node_id,
            "agent_id": agent_id,
            "stage": stage,
            "allowed_tools": list(allowed_tools),
            "as_of": as_of,
            "candidate_scope_hash": bundle["candidate_scope_hash"],
            "snapshot_bundle_id": snapshot_bundle_id,
            "snapshot_bundle_hash": snapshot_bundle_hash,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
            "nonce": secrets.token_hex(24),
        }
        signed = SignedCapability(
            manifest=manifest,
            signing_key_id=self.signing_key_id,
            signature=self._sign(manifest),
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO snapshot_bundles VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        snapshot_bundle_id,
                        snapshot_bundle_hash,
                        materialization_request_id,
                        _canonical_json(bundle),
                        _canonical_json(payloads),
                        now.isoformat(),
                    ),
                )
                conn.execute(
                    "INSERT INTO capabilities VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        capability_id,
                        snapshot_bundle_id,
                        _canonical_json(manifest),
                        self.signing_key_id,
                        signed.signature,
                        now.isoformat(),
                    ),
                )
                conn.execute(
                    "INSERT INTO capability_events VALUES (?, ?, 'ISSUED', ?, NULL)",
                    (f"evt_{uuid.uuid4().hex}", capability_id, now.isoformat()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {"bundle": bundle, "capability": signed.as_dict()}

    def issue_for_bundle(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Issue another node-bound capability without re-running collectors."""
        graph_run_id = _required_string(request, "graph_run_id")
        run_slot_id = _required_string(request, "run_slot_id")
        run_id = _required_string(request, "run_id")
        node_id = _required_string(request, "node_id")
        agent_id = _required_string(request, "agent_id")
        stage = execution_stage_for_agent(agent_id, request.get("stage"))
        as_of = _required_string(request, "as_of")
        date.fromisoformat(as_of)
        snapshot_bundle_id = _required_string(request, "snapshot_bundle_id")
        snapshot_bundle_hash = _required_string(request, "snapshot_bundle_hash")
        ttl = request.get("ttl_seconds", DEFAULT_CAPABILITY_TTL_SECONDS)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 3600:
            raise ValueError("ttl_seconds must be an integer in [1, 3600]")

        with self._connect() as conn:
            row = conn.execute(
                "SELECT bundle_json, payloads_json FROM snapshot_bundles WHERE snapshot_bundle_id = ?",
                (snapshot_bundle_id,),
            ).fetchone()
        if row is None:
            raise ValueError("unknown snapshot_bundle_id")
        bundle = json.loads(row["bundle_json"])
        if (
            bundle.get("snapshot_bundle_hash") != snapshot_bundle_hash
            or bundle.get("agent_id") != agent_id
            or bundle.get("stage") != stage
            or bundle.get("as_of") != as_of
        ):
            raise ValueError("requested capability does not match the snapshot bundle")
        bundle_without_hash = {
            key: value for key, value in bundle.items() if key != "snapshot_bundle_hash"
        }
        if snapshot_bundle_hash != _sha256(bundle_without_hash):
            raise ValueError("snapshot bundle hash mismatch")
        allowed_tools = allowed_tools_for_agent(agent_id)
        payload_hashes = bundle.get("tool_payload_hashes")
        payloads = json.loads(row["payloads_json"])
        if (
            not isinstance(payload_hashes, dict)
            or not isinstance(payloads, dict)
            or set(payload_hashes) != set(allowed_tools)
            or set(payloads) != set(allowed_tools)
        ):
            raise ValueError("snapshot bundle tools do not match the canonical role whitelist")
        for tool_id in allowed_tools:
            payload = payloads.get(tool_id)
            if not isinstance(payload, str) or payload_hashes.get(tool_id) != _sha256_text(payload):
                raise ValueError("snapshot bundle payload hash mismatch")

        now = self.clock().astimezone(timezone.utc)
        capability_id = f"cap_{uuid.uuid4().hex}"
        manifest = {
            "capability_contract_version": CAPABILITY_CONTRACT_VERSION,
            "capability_id": capability_id,
            "graph_run_id": graph_run_id,
            "run_slot_id": run_slot_id,
            "run_id": run_id,
            "node_id": node_id,
            "agent_id": agent_id,
            "stage": stage,
            "allowed_tools": list(allowed_tools),
            "as_of": as_of,
            "candidate_scope_hash": bundle.get("candidate_scope_hash"),
            "snapshot_bundle_id": snapshot_bundle_id,
            "snapshot_bundle_hash": snapshot_bundle_hash,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
            "nonce": secrets.token_hex(24),
        }
        signed = SignedCapability(
            manifest=manifest,
            signing_key_id=self.signing_key_id,
            signature=self._sign(manifest),
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO capabilities VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        capability_id,
                        snapshot_bundle_id,
                        _canonical_json(manifest),
                        self.signing_key_id,
                        signed.signature,
                        now.isoformat(),
                    ),
                )
                conn.execute(
                    "INSERT INTO capability_events VALUES (?, ?, 'ISSUED', ?, NULL)",
                    (f"evt_{uuid.uuid4().hex}", capability_id, now.isoformat()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {"bundle": bundle, "capability": signed.as_dict()}

    def _verify(self, envelope: Mapping[str, Any]) -> tuple[dict[str, Any], sqlite3.Row]:
        manifest = envelope.get("manifest")
        key_id = envelope.get("signing_key_id")
        signature = envelope.get("signature")
        if not isinstance(manifest, dict):
            raise ValueError("capability manifest must be an object")
        if key_id != self.signing_key_id or not isinstance(signature, str):
            raise ValueError("unknown capability signing key")
        expected = self._sign(manifest)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid capability signature")
        capability_id = _required_string(manifest, "capability_id")
        for field in ("graph_run_id", "run_slot_id", "run_id", "node_id", "nonce"):
            _required_string(manifest, field)
        agent_id = _required_string(manifest, "agent_id")
        stage = execution_stage_for_agent(agent_id, _required_string(manifest, "stage"))
        as_of = _required_string(manifest, "as_of")
        date.fromisoformat(as_of)
        if manifest.get("capability_contract_version") != CAPABILITY_CONTRACT_VERSION:
            raise ValueError("capability contract version mismatch")
        if not _is_sha256(manifest.get("snapshot_bundle_hash")):
            raise ValueError("capability snapshot_bundle_hash is invalid")
        candidate_scope_hash = manifest.get("candidate_scope_hash")
        if candidate_scope_hash is not None and not _is_sha256(candidate_scope_hash):
            raise ValueError("capability candidate_scope_hash is invalid")
        allowed = manifest.get("allowed_tools")
        if not isinstance(allowed, list) or tuple(allowed) != allowed_tools_for_agent(agent_id):
            raise ValueError("capability tools do not match the canonical role whitelist")
        issued_at = datetime.fromisoformat(_required_string(manifest, "issued_at"))
        expires_at = datetime.fromisoformat(_required_string(manifest, "expires_at"))
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("capability timestamps must be timezone-aware")
        issued_at = issued_at.astimezone(timezone.utc)
        expires_at = expires_at.astimezone(timezone.utc)
        if expires_at <= issued_at or expires_at - issued_at > timedelta(seconds=3600):
            raise ValueError("capability lifetime is invalid")
        now = self.clock().astimezone(timezone.utc)
        if now < issued_at:
            raise ValueError("capability is not yet valid")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT c.*, b.bundle_json, b.payloads_json
                FROM capabilities c
                JOIN snapshot_bundles b USING(snapshot_bundle_id)
                WHERE c.capability_id = ?
                """,
                (capability_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown capability_id")
            if (
                row["manifest_json"] != _canonical_json(manifest)
                or row["signature"] != signature
                or row["signing_key_id"] != key_id
            ):
                raise ValueError("capability does not match the issued ledger record")
            terminated = conn.execute(
                "SELECT 1 FROM capability_events WHERE capability_id = ? AND event_type = 'TERMINATED'",
                (capability_id,),
            ).fetchone()
            if terminated is not None:
                raise ValueError("capability is terminated")
        if now >= expires_at:
            raise ValueError("capability is expired")
        bundle = json.loads(row["bundle_json"])
        if (
            manifest.get("snapshot_bundle_id") != bundle.get("snapshot_bundle_id")
            or manifest.get("snapshot_bundle_hash") != bundle.get("snapshot_bundle_hash")
            or agent_id != bundle.get("agent_id")
            or stage != bundle.get("stage")
            or as_of != bundle.get("as_of")
            or manifest.get("candidate_scope_hash") != bundle.get("candidate_scope_hash")
        ):
            raise ValueError("capability/bundle binding mismatch")
        if bundle.get("snapshot_bundle_contract_version") != SNAPSHOT_BUNDLE_CONTRACT_VERSION:
            raise ValueError("snapshot bundle contract version mismatch")
        declared_bundle_hash = bundle.get("snapshot_bundle_hash")
        bundle_without_hash = {
            key: value for key, value in bundle.items() if key != "snapshot_bundle_hash"
        }
        if declared_bundle_hash != _sha256(bundle_without_hash):
            raise ValueError("snapshot bundle hash mismatch")
        if not _is_sha256(bundle.get("runtime_input_hash")):
            raise ValueError("snapshot bundle runtime_input_hash is invalid")
        payload_hashes = bundle.get("tool_payload_hashes")
        if not isinstance(payload_hashes, dict) or set(payload_hashes) != set(allowed):
            raise ValueError("capability tools do not match bundle payloads")
        payloads = json.loads(row["payloads_json"])
        if not isinstance(payloads, dict) or set(payloads) != set(allowed):
            raise ValueError("snapshot bundle payload keys mismatch")
        for tool_id in allowed:
            payload = payloads.get(tool_id)
            if not isinstance(payload, str) or not payload:
                raise ValueError("snapshot bundle payload is missing")
            if payload_hashes.get(tool_id) != _sha256_text(payload):
                raise ValueError("snapshot bundle payload hash mismatch")
        return manifest, row

    def list_tools(self, envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
        manifest, _ = self._verify(envelope)
        return [
            {
                "name": tool_id,
                "description": TOOL_DESCRIPTIONS[tool_id],
                "args_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            }
            for tool_id in manifest["allowed_tools"]
        ]

    def call_tool(
        self,
        envelope: Mapping[str, Any],
        tool_id: str,
        args: Mapping[str, Any],
    ) -> str:
        manifest, row = self._verify(envelope)
        if args:
            raise ValueError("role-scoped model tools accept no arguments")
        if tool_id not in manifest["allowed_tools"]:
            raise ValueError(f"tool {tool_id!r} is not allowed by this capability")
        payloads = json.loads(row["payloads_json"])
        payload = payloads.get(tool_id)
        if not isinstance(payload, str) or not payload:
            raise ValueError("bundle payload is missing")
        bundle = json.loads(row["bundle_json"])
        if bundle["tool_payload_hashes"].get(tool_id) != _sha256_text(payload):
            raise ValueError("bundle payload hash mismatch")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                terminated = conn.execute(
                    """
                    SELECT 1 FROM capability_events
                    WHERE capability_id = ? AND event_type = 'TERMINATED'
                    """,
                    (manifest["capability_id"],),
                ).fetchone()
                if terminated is not None:
                    raise ValueError("capability is terminated")
                conn.execute(
                    "INSERT INTO capability_tool_uses VALUES (?, ?, ?)",
                    (
                        manifest["capability_id"],
                        tool_id,
                        self.clock().astimezone(timezone.utc).isoformat(),
                    ),
                )
                conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise ValueError("capability tool has already been used") from exc
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return payload

    def terminate(self, envelope: Mapping[str, Any], reason: str) -> None:
        manifest, _ = self._verify(envelope)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("termination reason must be non-empty")
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO capability_events VALUES (?, ?, 'TERMINATED', ?, ?)",
                    (
                        f"evt_{uuid.uuid4().hex}",
                        manifest["capability_id"],
                        self.clock().astimezone(timezone.utc).isoformat(),
                        reason.strip(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("capability is already terminated") from exc


_STORE_LOCK = threading.Lock()
_STORE_BY_PATH: dict[Path, AgentToolCapabilityStore] = {}
_EPHEMERAL_SIGNING_KEY = secrets.token_bytes(32)


def capability_ledger_path() -> Path:
    explicit = os.getenv("MOSAIC_AGENT_TOOL_LEDGER_PATH")
    if explicit:
        return Path(explicit).expanduser().resolve()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return (cache / "runtime" / "agent_tool_capabilities.sqlite3").resolve()


def get_capability_store() -> AgentToolCapabilityStore:
    path = capability_ledger_path()
    with _STORE_LOCK:
        store = _STORE_BY_PATH.get(path)
        if store is None:
            raw_key = os.getenv("MOSAIC_AGENT_CAPABILITY_SIGNING_KEY")
            key = raw_key.encode("utf-8") if raw_key else _EPHEMERAL_SIGNING_KEY
            key_id = os.getenv(
                "MOSAIC_AGENT_CAPABILITY_SIGNING_KEY_ID", "runtime-ephemeral-v1"
            )
            store = AgentToolCapabilityStore(
                path,
                signing_key=key,
                signing_key_id=key_id,
            )
            _STORE_BY_PATH[path] = store
        return store


__all__ = [
    "AGENT_TOOL_MATRIX",
    "ALL_AGENT_IDS",
    "AgentToolCapabilityStore",
    "AgentToolId",
    "CAPABILITY_CONTRACT_VERSION",
    "MACRO_AGENT_TO_TOOL",
    "SNAPSHOT_BUNDLE_CONTRACT_VERSION",
    "TOOL_DESCRIPTIONS",
    "allowed_tools_for_agent",
    "capability_ledger_path",
    "execution_stage_for_agent",
    "get_capability_store",
    "materialize_tool_payload",
]

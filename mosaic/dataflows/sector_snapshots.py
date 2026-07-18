"""Private PIT sector snapshots exposed through zero-choice role tools.

The model cannot choose a sector, direction universe, ticker universe, or data
source.  Those are frozen by the runtime and validated here before any payload
crosses the bridge.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Any

from .exceptions import DataVendorUnavailable
from .role_events import ROLE_EVENT_CURRENCIES, build_role_event_snapshot

SECTOR_SNAPSHOT_SCHEMA_VERSION = "sector_research_snapshot_v2"
RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION = "relationship_research_snapshot_v2"
SECTOR_DIRECTION_CONTRACT_VERSION = "sector_direction_registry_v3"
SECTOR_UNIVERSE_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "registry"
    / "prompt_checks"
    / "sector_universe_manifest_v1.json"
)


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _load_sector_universe_manifest(path: Path = SECTOR_UNIVERSE_MANIFEST_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load Sector universe manifest {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "sector_universe_manifest_v1":
        raise RuntimeError("Sector universe manifest schema_version mismatch")
    content = {key: value for key, value in payload.items() if key != "manifest_hash"}
    if payload.get("manifest_hash") != _canonical_hash(content):
        raise RuntimeError("Sector universe manifest_hash mismatch")
    if payload.get("sector_count") != 9 or payload.get("direction_count") != 37:
        raise RuntimeError("Sector universe manifest roster count mismatch")
    metrics = payload.get("direction_metric_registry")
    if not isinstance(metrics, list) or len(metrics) != 26:
        raise RuntimeError("Sector metric registry must contain exactly 26 rows")
    if payload.get("direction_metric_registry_hash") != _canonical_hash(metrics):
        raise RuntimeError("Sector metric registry hash mismatch")
    plans = payload.get("membership_query_plans")
    if not isinstance(plans, list) or len(plans) != 9:
        raise RuntimeError("Sector membership query plan roster mismatch")
    plan_by_id: dict[str, dict[str, Any]] = {}
    for plan in plans:
        if not isinstance(plan, dict):
            raise RuntimeError("Sector membership query plan must be an object")
        plan_content = {key: value for key, value in plan.items() if key != "query_plan_hash"}
        if plan.get("query_plan_hash") != _canonical_hash(plan_content):
            raise RuntimeError("Sector membership query plan hash mismatch")
        branches = plan.get("branches")
        if not isinstance(branches, list) or not branches:
            raise RuntimeError("Sector membership query plan branches are missing")
        branch_keys = {
            (branch.get("parameter"), branch.get("classification_code"), branch.get("is_new"))
            for branch in branches
            if isinstance(branch, dict)
        }
        code_keys = {(parameter, code) for parameter, code, _is_new in branch_keys}
        if any(
            (parameter, code, "Y") not in branch_keys
            or (parameter, code, "N") not in branch_keys
            for parameter, code in code_keys
        ):
            raise RuntimeError("Sector membership plans require paired is_new Y/N branches")
        plan_id = plan.get("query_plan_id")
        if not isinstance(plan_id, str) or plan_id in plan_by_id:
            raise RuntimeError("Sector membership query_plan_id must be unique")
        plan_by_id[plan_id] = plan
    directions = payload.get("direction_contracts")
    if not isinstance(directions, list) or len(directions) != 37:
        raise RuntimeError("Sector direction contract roster mismatch")
    seen_directions: set[tuple[str, str]] = set()
    for direction in directions:
        if not isinstance(direction, dict):
            raise RuntimeError("Sector direction contract must be an object")
        content = {
            key: value
            for key, value in direction.items()
            if key != "direction_contract_hash"
        }
        if direction.get("direction_contract_hash") != _canonical_hash(content):
            raise RuntimeError("Sector direction contract hash mismatch")
        key = (direction.get("sector_agent_id"), direction.get("direction_id"))
        if not all(isinstance(value, str) and value for value in key) or key in seen_directions:
            raise RuntimeError("Sector direction IDs must be non-empty and role-unique")
        seen_directions.add(key)
        plan_id = direction.get("membership_query_plan_id")
        plan = plan_by_id.get(plan_id)
        if not plan or direction.get("membership_query_plan_hash") != plan.get("query_plan_hash"):
            raise RuntimeError("Sector direction membership plan binding mismatch")
    return payload


SECTOR_UNIVERSE_MANIFEST = _load_sector_universe_manifest()
SECTOR_DIRECTION_IDS: dict[str, tuple[str, ...]] = {
    agent_id: tuple(
        direction["direction_id"]
        for direction in SECTOR_UNIVERSE_MANIFEST["direction_contracts"]
        if direction["sector_agent_id"] == agent_id
    )
    for agent_id in SECTOR_UNIVERSE_MANIFEST["overlap_precedence"]
}


def sector_snapshot_root() -> Path:
    explicit = os.getenv("MOSAIC_SECTOR_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache / "sector_snapshots"


def _read(role: str, as_of_date: str, root: Path) -> Any:
    candidates = (
        root / as_of_date / f"{role}.json",
        root / f"{role}.{as_of_date}.json",
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise DataVendorUnavailable(
            f"no private PIT sector snapshot for {role} on {as_of_date} under {root}"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(f"cannot read sector snapshot {path}: {exc}") from exc


def validate_sector_snapshot(payload: Any, role: str, as_of_date: str) -> dict[str, Any]:
    if role not in SECTOR_DIRECTION_IDS:
        raise DataVendorUnavailable(f"unknown standard sector role {role!r}")
    if not isinstance(payload, dict):
        raise DataVendorUnavailable("sector snapshot must be an object")
    if payload.get("schema_version") != SECTOR_SNAPSHOT_SCHEMA_VERSION:
        raise DataVendorUnavailable("sector snapshot schema_version mismatch")
    if payload.get("sector_agent_id") != role or payload.get("as_of_date") != as_of_date:
        raise DataVendorUnavailable("sector snapshot role/as_of mismatch")
    date.fromisoformat(as_of_date)
    expected_directions = SECTOR_DIRECTION_IDS[role]
    if tuple(payload.get("direction_ids", ())) != expected_directions:
        raise DataVendorUnavailable(f"{role} direction registry mismatch")
    if payload.get("direction_contract_version") != SECTOR_DIRECTION_CONTRACT_VERSION:
        raise DataVendorUnavailable("sector direction contract version mismatch")
    cards = payload.get("direction_cards")
    if not isinstance(cards, list):
        raise DataVendorUnavailable("sector direction_cards must be an array")
    card_ids = [card.get("direction_id") for card in cards if isinstance(card, dict)]
    if sorted(card_ids) != sorted(expected_directions) or len(card_ids) != len(set(card_ids)):
        raise DataVendorUnavailable("sector snapshot requires one card per direction")
    required_card_fields = {
        "fundamentals",
        "valuation",
        "basket_technicals",
        "risk_asymmetry",
        "etf_price_confirmation",
        "etf_share_flow_confirmation",
        "evidence_ids",
    }
    for card in cards:
        if not isinstance(card, dict) or not required_card_fields.issubset(card):
            raise DataVendorUnavailable("sector direction card missing comparable fields")
        if not isinstance(card["evidence_ids"], list) or not card["evidence_ids"]:
            raise DataVendorUnavailable("sector direction card evidence_ids must be non-empty")
    universe = payload.get("eligible_security_universe")
    if not isinstance(universe, list):
        raise DataVendorUnavailable("eligible_security_universe must be an array")
    seen_tickers: set[str] = set()
    for security in universe:
        if not isinstance(security, dict):
            raise DataVendorUnavailable("sector security rows must be objects")
        ts_code = security.get("ts_code")
        direction_id = security.get("direction_id")
        if not isinstance(ts_code, str) or direction_id not in expected_directions:
            raise DataVendorUnavailable("sector security is outside the frozen role domain")
        if ts_code in seen_tickers:
            raise DataVendorUnavailable(f"duplicate sector security {ts_code}")
        seen_tickers.add(ts_code)
    evidence_catalog = payload.get("evidence_catalog")
    if not isinstance(evidence_catalog, list) or not evidence_catalog:
        raise DataVendorUnavailable("sector evidence_catalog must be non-empty")
    evidence_ids = [row.get("evidence_id") for row in evidence_catalog if isinstance(row, dict)]
    if len(evidence_ids) != len(evidence_catalog) or len(evidence_ids) != len(set(evidence_ids)):
        raise DataVendorUnavailable("sector evidence ids must be present and unique")
    canonical = {
        key: payload[key]
        for key in (
            "schema_version",
            "sector_agent_id",
            "as_of_date",
            "direction_contract_version",
            "direction_ids",
            "direction_cards",
            "eligible_security_universe",
            "event_coverage",
            "evidence_catalog",
        )
        if key in payload
    }
    canonical["snapshot_hash"] = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return canonical


def load_sector_snapshot(
    role: str, as_of_date: str, root: Path | None = None
) -> dict[str, Any]:
    source_root = root or sector_snapshot_root()
    snapshot = validate_sector_snapshot(
        _read(role, as_of_date, source_root), role, as_of_date
    )
    if role in ROLE_EVENT_CURRENCIES:
        role_events = build_role_event_snapshot(role, as_of_date)
        if role_events["coverage"]["coverage_completeness"] != "COMPLETE":
            raise DataVendorUnavailable("sector role-event required routes are incomplete")
        supplied_coverage = snapshot.get("event_coverage")
        if supplied_coverage is not None and supplied_coverage != role_events["coverage"]:
            raise DataVendorUnavailable("sector/event coverage snapshot mismatch")
        snapshot["event_coverage"] = role_events["coverage"]
        snapshot["role_event_snapshot_ref"] = {
            "role_event_snapshot_id": role_events["role_event_snapshot_id"],
            "role_event_snapshot_hash": role_events["role_event_snapshot_hash"],
        }
        without_hash = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
        snapshot["snapshot_hash"] = _canonical_hash(without_hash)
    return snapshot


def render_sector_snapshot(role: str, as_of_date: str) -> str:
    return json.dumps(
        load_sector_snapshot(role, as_of_date),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_relationship_snapshot(
    as_of_date: str, run_id: str = "standalone_relationship_snapshot"
) -> str:
    payload = _read("relationship_mapper", as_of_date, sector_snapshot_root())
    if not isinstance(payload, dict):
        raise DataVendorUnavailable("relationship snapshot must be an object")
    if payload.get("schema_version") != RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION:
        raise DataVendorUnavailable("relationship snapshot schema_version mismatch")
    if payload.get("as_of_date") != as_of_date:
        raise DataVendorUnavailable("relationship snapshot as_of mismatch")
    if not isinstance(run_id, str) or not run_id.strip():
        raise DataVendorUnavailable("relationship snapshot run_id is required")
    required = (
        "frozen_security_domain_hash",
        "relationships",
        "prediction_opportunity_set",
        "evidence_catalog",
    )
    if any(not payload.get(field) for field in required):
        raise DataVendorUnavailable("relationship snapshot missing required data")
    opportunity = payload["prediction_opportunity_set"]
    if not isinstance(opportunity, dict):
        raise DataVendorUnavailable("relationship prediction opportunity set must be an object")
    opportunities = opportunity.get("ordered_opportunities")
    if not isinstance(opportunities, list) or not opportunities:
        raise DataVendorUnavailable("relationship prediction opportunity set must be non-empty")
    candidate_ids: list[str] = []
    for row in opportunities:
        if not isinstance(row, dict):
            raise DataVendorUnavailable("relationship prediction opportunity must be an object")
        required_row = (
            "edge_candidate_id",
            "source_entity",
            "target_entity",
            "edge_type",
            "materiality_weight",
            "matched_non_edge_set_id",
            "matched_non_edge_set_hash",
        )
        if any(row.get(field) in (None, "") for field in required_row):
            raise DataVendorUnavailable("relationship prediction opportunity is incomplete")
        weight = row["materiality_weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise DataVendorUnavailable("relationship materiality weight must be numeric")
        if not math.isfinite(float(weight)) or float(weight) <= 0:
            raise DataVendorUnavailable("relationship materiality weight must be finite and positive")
        matched_hash = row["matched_non_edge_set_hash"]
        if not isinstance(matched_hash, str) or not matched_hash.startswith("sha256:"):
            raise DataVendorUnavailable("relationship matched non-edge hash is invalid")
        candidate_ids.append(str(row["edge_candidate_id"]))
    if len(set(candidate_ids)) != len(candidate_ids) or candidate_ids != sorted(candidate_ids):
        raise DataVendorUnavailable(
            "relationship opportunity ids must be unique and canonically ordered"
        )
    relationship_by_id = {
        row.get("edge_candidate_id"): row
        for row in payload["relationships"]
        if isinstance(row, dict) and isinstance(row.get("edge_candidate_id"), str)
    }
    for row in opportunities:
        source = relationship_by_id.get(row["edge_candidate_id"])
        if source is None or any(
            source.get(field) != row[field]
            for field in ("source_entity", "target_entity", "edge_type")
        ):
            raise DataVendorUnavailable(
                "relationship opportunity does not match the frozen relationship domain"
            )
    opportunity_body = {
        "run_id": run_id,
        "as_of": as_of_date,
        "candidate_generation_contract_version": opportunity.get(
            "candidate_generation_contract_version"
        ),
        "scoring_contract_version": opportunity.get("scoring_contract_version"),
        "ordered_opportunities": opportunities,
    }
    if not all(
        isinstance(opportunity_body[field], str) and opportunity_body[field]
        for field in ("candidate_generation_contract_version", "scoring_contract_version")
    ):
        raise DataVendorUnavailable("relationship opportunity contract versions are required")
    opportunity_hash = _canonical_hash(opportunity_body)
    frozen_opportunity = {
        "opportunity_set_id": f"relationship-opportunity:{opportunity_hash.removeprefix('sha256:')}",
        "opportunity_set_hash": opportunity_hash,
        **opportunity_body,
    }
    canonical = {
        key: payload[key]
        for key in ("schema_version", "as_of_date", "frozen_security_domain_hash", "relationships", "evidence_catalog")
    }
    canonical["prediction_opportunity_set"] = frozen_opportunity
    canonical["snapshot_hash"] = _canonical_hash(canonical)
    return json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION",
    "SECTOR_DIRECTION_CONTRACT_VERSION",
    "SECTOR_DIRECTION_IDS",
    "SECTOR_SNAPSHOT_SCHEMA_VERSION",
    "load_sector_snapshot",
    "render_relationship_snapshot",
    "render_sector_snapshot",
    "sector_snapshot_root",
    "validate_sector_snapshot",
]

"""Versioned RKE-shadow Agent migration inventory.

The migration routes data fields to the v2 research roles; it never aliases an
old Agent identity or promotes RKE-derived context into the production graph.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "rke_shadow_agent_migration_manifest_v1"
TOMBSTONED_AGENT_IDS = (
    "macro.dollar",
    "macro.yield_curve",
    "macro.volatility",
    "macro.emerging_markets",
    "macro.news_sentiment",
)
NEW_AGENT_IDS = (
    "macro.eu_economy",
    "macro.us_financial_conditions",
    "macro.euro_area_financial_conditions",
    "sector.technology",
    "sector.real_estate_construction",
    "sector.agriculture",
)
MIGRATION_INVENTORY_MODULES = (
    "mosaic/rke/agent_research_context.py",
    "mosaic/rke/report_intelligence.py",
    "mosaic/rke/macro_expansion.py",
    "mosaic/rke/phase_minus1.py",
)
LEGACY_REFERENCE_INVENTORY = {
    "mosaic/rke/agent_research_context.py": TOMBSTONED_AGENT_IDS,
    "mosaic/rke/report_intelligence.py": (
        "macro.dollar",
        "macro.yield_curve",
        "macro.volatility",
    ),
    "mosaic/rke/macro_expansion.py": (
        "macro.dollar",
        "macro.yield_curve",
        "macro.volatility",
    ),
    "mosaic/rke/phase_minus1.py": ("macro.dollar", "macro.volatility"),
}

_FIELD_ROUTE_ROWS = (
    ("china_nominal_yield_curve", "macro.central_bank", ("yield_curve.cn_nominal",)),
    ("china_money_market", "macro.central_bank", ("yield_curve.cn_money_market",)),
    ("china_credit_price_access", "macro.central_bank", ("yield_curve.cn_credit",)),
    ("fed_policy", "macro.us_financial_conditions", ("yield_curve.fed", "dollar.fed")),
    ("us_nominal_yield_curve", "macro.us_financial_conditions", ("yield_curve.us_nominal",)),
    ("us_real_yield_curve", "macro.us_financial_conditions", ("yield_curve.us_real",)),
    ("us_money_market", "macro.us_financial_conditions", ("yield_curve.us_money_market",)),
    ("us_credit_spreads", "macro.us_financial_conditions", ("yield_curve.us_credit",)),
    ("broad_us_dollar", "macro.us_financial_conditions", ("dollar.broad_usd",)),
    ("usd_cny", "macro.us_financial_conditions", ("dollar.usd_cny",)),
    ("us_financial_stress", "macro.us_financial_conditions", ("volatility.us_stress",)),
    ("vix", "macro.us_financial_conditions", ("volatility.vix",)),
    ("ecb_policy", "macro.euro_area_financial_conditions", ("yield_curve.ecb",)),
    ("euro_area_yield_curve", "macro.euro_area_financial_conditions", ("yield_curve.euro_area",)),
    ("euro_area_credit_money", "macro.euro_area_financial_conditions", ("yield_curve.euro_credit",)),
    ("euro_fx", "macro.euro_area_financial_conditions", ("dollar.euro_fx",)),
    ("euro_area_ciss", "macro.euro_area_financial_conditions", ("volatility.ciss",)),
    ("china_realized_volatility", "decision.cro", ("volatility.china_realized",)),
)


def build_rke_shadow_agent_migration_manifest() -> dict[str, Any]:
    routes = []
    for field_id, owner_agent_id, source_legacy_fields in _FIELD_ROUTE_ROWS:
        body = {
            "field_id": field_id,
            "owner_agent_id": owner_agent_id,
            "source_legacy_fields": list(source_legacy_fields),
            "identity_alias": False,
        }
        routes.append({**body, "route_hash": _canonical_hash(body)})
    without_hash = {
        "schema_version": SCHEMA_VERSION,
        "execution_mode": "RKE_SHADOW",
        "production_signal_allowed": False,
        "covered_modules": list(MIGRATION_INVENTORY_MODULES),
        "legacy_reference_inventory": [
            {
                "module_path": module_path,
                "legacy_agent_ids": list(LEGACY_REFERENCE_INVENTORY[module_path]),
                "legacy_artifact_status": "legacy_unverified",
                "current_routing_policy": "DATA_FIELD_ROUTES_ONLY_NO_IDENTITY_ALIAS",
            }
            for module_path in MIGRATION_INVENTORY_MODULES
        ],
        "tombstoned_agent_ids": [
            {"agent_id": agent_id, "status": "legacy_unverified"}
            for agent_id in TOMBSTONED_AGENT_IDS
        ],
        "new_agent_ids": [
            {
                "agent_id": agent_id,
                "identity_alias_from": None,
                "inherits_legacy_samples": False,
                "inherits_legacy_weight": False,
            }
            for agent_id in NEW_AGENT_IDS
        ],
        "identity_aliases": [],
        "data_field_routes": routes,
        "isolation_policy": {
            "production_graph_allowed": False,
            "production_tool_manifest_allowed": False,
            "decision_input_allowed": False,
            "darwinian_update_allowed": False,
        },
    }
    return {**without_hash, "manifest_hash": _canonical_hash(without_hash)}


def validate_rke_shadow_agent_migration_manifest(
    payload: dict[str, Any],
) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("RKE shadow migration schema version mismatch")
    if payload.get("execution_mode") != "RKE_SHADOW":
        raise ValueError("RKE shadow migration must remain shadow-only")
    if payload.get("production_signal_allowed") is not False:
        raise ValueError("RKE shadow migration cannot allow production signals")
    if payload.get("identity_aliases") != []:
        raise ValueError("RKE shadow migration cannot alias Agent identities")
    tombstoned = {
        str(row.get("agent_id"))
        for row in payload.get("tombstoned_agent_ids", [])
        if isinstance(row, dict)
        and row.get("status") == "legacy_unverified"
    }
    if tombstoned != set(TOMBSTONED_AGENT_IDS):
        raise ValueError("RKE shadow tombstone roster mismatch")
    new_agents = {
        str(row.get("agent_id"))
        for row in payload.get("new_agent_ids", [])
        if isinstance(row, dict)
        and row.get("identity_alias_from") is None
        and row.get("inherits_legacy_samples") is False
        and row.get("inherits_legacy_weight") is False
    }
    if new_agents != set(NEW_AGENT_IDS):
        raise ValueError("RKE shadow new-Agent roster mismatch")
    if set(payload.get("covered_modules", [])) != set(MIGRATION_INVENTORY_MODULES):
        raise ValueError("RKE shadow module inventory is incomplete")
    inventory = payload.get("legacy_reference_inventory")
    if not isinstance(inventory, list) or len(inventory) != len(
        MIGRATION_INVENTORY_MODULES
    ):
        raise ValueError("RKE shadow legacy reference inventory is incomplete")
    observed_inventory: dict[str, tuple[str, ...]] = {}
    for row in inventory:
        if not isinstance(row, dict):
            raise ValueError("RKE shadow legacy reference inventory row must be an object")
        module_path = str(row.get("module_path") or "")
        legacy_agent_ids = row.get("legacy_agent_ids")
        if (
            module_path in observed_inventory
            or not isinstance(legacy_agent_ids, list)
            or row.get("legacy_artifact_status") != "legacy_unverified"
            or row.get("current_routing_policy")
            != "DATA_FIELD_ROUTES_ONLY_NO_IDENTITY_ALIAS"
        ):
            raise ValueError("RKE shadow legacy reference inventory row is invalid")
        observed_inventory[module_path] = tuple(str(value) for value in legacy_agent_ids)
    if observed_inventory != LEGACY_REFERENCE_INVENTORY:
        raise ValueError("RKE shadow legacy reference inventory mismatch")
    routes = payload.get("data_field_routes")
    if not isinstance(routes, list) or len(routes) != len(_FIELD_ROUTE_ROWS):
        raise ValueError("RKE shadow data-field routes are incomplete")
    seen_fields: set[str] = set()
    for route in routes:
        if not isinstance(route, dict):
            raise ValueError("RKE shadow route must be an object")
        field_id = str(route.get("field_id") or "")
        if not field_id or field_id in seen_fields:
            raise ValueError("RKE shadow route field must be unique")
        seen_fields.add(field_id)
        body = {key: value for key, value in route.items() if key != "route_hash"}
        if route.get("route_hash") != _canonical_hash(body):
            raise ValueError(f"RKE shadow route hash mismatch: {field_id}")
        if route.get("identity_alias") is not False:
            raise ValueError(f"RKE shadow route aliases identity: {field_id}")
    without_hash = {key: value for key, value in payload.items() if key != "manifest_hash"}
    if payload.get("manifest_hash") != _canonical_hash(without_hash):
        raise ValueError("RKE shadow migration manifest hash mismatch")
    return payload


def write_rke_shadow_agent_migration_manifest(root: str | Path = ".") -> Path:
    payload = validate_rke_shadow_agent_migration_manifest(
        build_rke_shadow_agent_migration_manifest()
    )
    path = (
        Path(root)
        / "registry/prompt_checks/rke_shadow_agent_migration_manifest_v1.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "MIGRATION_INVENTORY_MODULES",
    "LEGACY_REFERENCE_INVENTORY",
    "NEW_AGENT_IDS",
    "SCHEMA_VERSION",
    "TOMBSTONED_AGENT_IDS",
    "build_rke_shadow_agent_migration_manifest",
    "validate_rke_shadow_agent_migration_manifest",
    "write_rke_shadow_agent_migration_manifest",
]

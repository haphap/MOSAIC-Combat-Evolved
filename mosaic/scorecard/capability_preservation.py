"""Staged preservation and Prompt-only KNOT contract authority.

This module does not activate tools.  It freezes the migration baseline and
validates the contracts that later activation PRs must close atomically.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from mosaic.scorecard.canonical_json import canonical_hash, canonical_json


PRESERVATION_SCHEMA_VERSION = "agent_capability_preservation_manifest_v1"
BINDING_SCHEMA_VERSION = "agent_capability_binding_manifest_v1"
TOOL_ENVIRONMENT_SCHEMA_VERSION = "tool_environment_manifest_v1"
KNOT_COVERAGE_SCHEMA_VERSION = "knot_tool_coverage_manifest_v1"
KNOT_COVERAGE_V2_SCHEMA_VERSION = "knot_tool_coverage_manifest_v2"
KNOT_AGGREGATE_SCHEMA_VERSION = "knot_capability_use_aggregate_v1"
ACCEPTED_OUTPUT_TRACK_SCHEMA_VERSION = "accepted_output_capability_track_v1"
KNOT_AUDIT_TRACK_V2_SCHEMA_VERSION = "knot_audit_capability_track_v2"
STAGED_TOOL_CONTRACT_SCHEMA_VERSION = "staged_agent_tool_contract_manifest_v2"
BASELINE_COMMIT = "b9ab1e444f691fb42e2caba81a345898482f22d8"
STAGED_CODE_COMMIT = "7b1c660b5f007e52d01aee9c1aaafc273a3c3836"

ACTIVE_TRACK_TAG_FIELDS = (
    "tool_environment_hash",
    "execution_behavior_release_hash",
    "capability_binding_manifest_hash",
    "knot_coverage_manifest_hash",
    "capability_bundle_hash",
)

_APPROVED_RESTORED_ROUTE_MIGRATIONS = {
    ("financials", "financials", "get_yield_curve_cn"): (
        ("tushare.shibor_yield_curve",),
        ("composite.cn_rates",),
    ),
    ("druckenmiller", "druckenmiller", "get_yield_curve_cn"): (
        ("tushare.shibor_yield_curve",),
        ("composite.cn_rates",),
    ),
}

_SHA_PREFIX = "sha256:"
_DISPOSITIONS = {
    "preserved",
    "equivalent",
    "partial",
    "scope_reduction_approved",
    "removed_approved",
    "introduced",
}
_APPROVED_REDUCTIONS = {"scope_reduction_approved", "removed_approved"}
_RESOLUTION_CODES = {
    "rebutted_with_evidence",
    "qualified",
    "abstained",
    "reversed",
}
_PUBLIC_FORBIDDEN_KEYS = {
    "abstract",
    "claim_text",
    "source_span",
    "source_span_ids",
    "report_title",
    "report_text",
    "query_text",
    "query_args",
    "canonical_args",
    "raw_prose",
    "licensed_text",
}

_TRUSTED_DIRECTION_KEYS = (
    "direction",
    "growth_direction",
    "momentum",
    "outlook",
    "signal",
    "stance",
    "trend",
)
_TRUSTED_NUMERIC_SIGNAL_SUFFIXES = (
    "_change",
    "_delta",
    "_growth",
    "_momentum",
    "_return",
)
_TRUSTED_DIRECTION_ENUM = {
    "bearish": "negative",
    "bullish": "positive",
    "down": "negative",
    "downward": "negative",
    "falling": "negative",
    "flat": "neutral",
    "improving": "positive",
    "negative": "negative",
    "neutral": "neutral",
    "positive": "positive",
    "rising": "positive",
    "stable": "neutral",
    "up": "positive",
    "upward": "positive",
    "weakening": "negative",
}

_BASELINE_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "semantic_capability_id": "china_macro",
        "baseline_tool_id": "get_china_macro_snapshot",
        "baseline_consumers": ["china"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["china"],
        "replacement_tools": ["get_china_macro_snapshot"],
        "disposition": "preserved",
    },
    {
        "semantic_capability_id": "us_macro",
        "baseline_tool_id": "get_us_macro_snapshot",
        "baseline_consumers": ["us_economy"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["us_economy"],
        "replacement_tools": ["get_us_macro_snapshot"],
        "disposition": "preserved",
    },
    {
        "semantic_capability_id": "central_bank_policy",
        "baseline_tool_id": "get_central_bank_snapshot",
        "baseline_consumers": ["central_bank"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["central_bank", "us_financial_conditions"],
        "replacement_tools": [
            "get_central_bank_snapshot",
            "get_us_financial_conditions_snapshot",
        ],
        "disposition": "partial",
    },
    {
        "semantic_capability_id": "fx_conditions",
        "baseline_tool_id": "get_fx_conditions_snapshot",
        "baseline_consumers": ["dollar"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["us_financial_conditions"],
        "replacement_tools": ["get_us_financial_conditions_snapshot"],
        "disposition": "partial",
    },
    {
        "semantic_capability_id": "rates_credit",
        "baseline_tool_id": "get_rates_credit_snapshot",
        "baseline_consumers": ["yield_curve"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["central_bank", "us_financial_conditions"],
        "replacement_tools": [
            "get_central_bank_snapshot",
            "get_us_financial_conditions_snapshot",
        ],
        "disposition": "partial",
    },
    {
        "semantic_capability_id": "commodity_conditions",
        "baseline_tool_id": "get_commodity_conditions_snapshot",
        "baseline_consumers": ["commodities"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["commodities"],
        "replacement_tools": ["get_commodity_conditions_snapshot"],
        "disposition": "preserved",
    },
    {
        "semantic_capability_id": "geopolitical_events",
        "baseline_tool_id": "get_geopolitical_events_snapshot",
        "baseline_consumers": ["geopolitical"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["geopolitical"],
        "replacement_tools": ["get_geopolitical_events_snapshot"],
        "disposition": "preserved",
    },
    {
        "semantic_capability_id": "volatility",
        "baseline_tool_id": "get_volatility_snapshot",
        "baseline_consumers": ["volatility"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["us_financial_conditions"],
        "replacement_tools": ["get_us_financial_conditions_snapshot"],
        "disposition": "partial",
    },
    {
        "semantic_capability_id": "market_breadth",
        "baseline_tool_id": "get_market_breadth_snapshot",
        "baseline_consumers": ["market_breadth"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["market_breadth"],
        "replacement_tools": ["get_market_breadth_snapshot"],
        "disposition": "preserved",
    },
    {
        "semantic_capability_id": "market_positioning",
        "baseline_tool_id": "get_market_positioning_snapshot",
        "baseline_consumers": ["institutional_flow"],
        "baseline_argument_fields": ["as_of"],
        "current_owners": ["institutional_flow"],
        "replacement_tools": ["get_market_positioning_snapshot"],
        "disposition": "preserved",
    },
    {
        "semantic_capability_id": "rke_research_context",
        "baseline_tool_id": "get_rke_research_context",
        "baseline_consumers": ["sector", "relationship", "superinvestor", "decision"],
        "baseline_argument_fields": [
            "agent_id",
            "as_of",
            "layer",
            "ticker",
            "sector",
            "max_items",
        ],
        "current_owners": [],
        "replacement_tools": [],
        "disposition": "partial",
        "privacy_class": "private_redacted",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "industry_policy_digest",
        "baseline_tool_id": "get_industry_policy_digest",
        "baseline_consumers": ["sector", "druckenmiller"],
        "baseline_argument_fields": ["as_of", "lookback_days", "source"],
        "current_owners": [],
        "replacement_tools": [],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "broker_research",
        "baseline_tool_id": "get_broker_research",
        "baseline_consumers": ["sector"],
        "baseline_argument_fields": ["ticker", "date_from", "date_to", "max_reports"],
        "current_owners": [],
        "replacement_tools": [],
        "disposition": "partial",
        "privacy_class": "licensed_private",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "etf_holdings",
        "baseline_tool_id": "get_etf_holdings",
        "baseline_consumers": ["sector"],
        "baseline_argument_fields": ["etf", "as_of", "top_n"],
        "current_owners": [],
        "replacement_tools": [],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "stock_data",
        "baseline_tool_id": "get_stock_data",
        "baseline_consumers": ["sector", "superinvestor"],
        "baseline_argument_fields": ["ticker", "date_from", "date_to"],
        "current_owners": ["sector"],
        "replacement_tools": ["get_sector_research_snapshot"],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "technical_indicators",
        "baseline_tool_id": "get_indicators",
        "baseline_consumers": ["sector", "druckenmiller"],
        "baseline_argument_fields": ["ticker", "as_of", "lookback", "indicators"],
        "current_owners": ["sector"],
        "replacement_tools": ["get_sector_research_snapshot"],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "industry_moneyflow",
        "baseline_tool_id": "get_industry_moneyflow",
        "baseline_consumers": ["sector"],
        "baseline_argument_fields": ["as_of", "lookback", "industry_filters"],
        "current_owners": [],
        "replacement_tools": [],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "china_yield_curve",
        "baseline_tool_id": "get_yield_curve_cn",
        "baseline_consumers": ["financials", "druckenmiller"],
        "baseline_argument_fields": ["as_of", "lookback"],
        "current_owners": ["central_bank"],
        "replacement_tools": ["get_central_bank_snapshot"],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "income_statement",
        "baseline_tool_id": "get_income_statement",
        "baseline_consumers": ["semiconductor", "ackman", "munger", "burry"],
        "baseline_argument_fields": ["ticker", "frequency", "as_of"],
        "current_owners": ["sector"],
        "replacement_tools": ["get_sector_research_snapshot"],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "balance_sheet",
        "baseline_tool_id": "get_balance_sheet",
        "baseline_consumers": ["semiconductor", "ackman", "munger", "burry"],
        "baseline_argument_fields": ["ticker", "frequency", "as_of"],
        "current_owners": [],
        "replacement_tools": [],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "cashflow_statement",
        "baseline_tool_id": "get_cashflow",
        "baseline_consumers": ["semiconductor", "ackman", "munger", "burry"],
        "baseline_argument_fields": ["ticker", "frequency", "as_of"],
        "current_owners": ["sector"],
        "replacement_tools": ["get_sector_research_snapshot"],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "stock_research",
        "baseline_tool_id": "get_stock_research",
        "baseline_consumers": ["relationship_mapper", "superinvestor"],
        "baseline_argument_fields": ["ticker", "date_from", "date_to", "max_reports"],
        "current_owners": [],
        "replacement_tools": [],
        "disposition": "partial",
        "privacy_class": "licensed_private",
        "adaptive_query_requirement": True,
    },
    {
        "semantic_capability_id": "fundamentals",
        "baseline_tool_id": "get_fundamentals",
        "baseline_consumers": ["superinvestor"],
        "baseline_argument_fields": ["ticker", "as_of"],
        "current_owners": ["sector"],
        "replacement_tools": ["get_sector_research_snapshot"],
        "disposition": "partial",
        "adaptive_query_requirement": True,
    },
)

_INTRODUCED_ROLES = (
    "eu_economy",
    "us_financial_conditions",
    "euro_area_financial_conditions",
    "technology",
    "real_estate_construction",
    "agriculture",
)

_INTRODUCED_CAPABILITIES: tuple[tuple[str, list[str], list[str]], ...] = (
    ("eu_macro", ["eu_economy"], ["get_eu_macro_snapshot"]),
    (
        "us_financial_conditions",
        ["us_financial_conditions"],
        ["get_us_financial_conditions_snapshot"],
    ),
    (
        "euro_area_financial_conditions",
        ["euro_area_financial_conditions"],
        ["get_euro_area_financial_conditions_snapshot"],
    ),
    ("technology_sector_snapshot", ["technology"], ["get_sector_research_snapshot"]),
    (
        "real_estate_sector_snapshot",
        ["real_estate_construction"],
        ["get_sector_research_snapshot"],
    ),
    ("agriculture_sector_snapshot", ["agriculture"], ["get_sector_research_snapshot"]),
    ("role_event_calendar", ["sector", "decision"], ["get_role_event_snapshot"]),
    (
        "relationship_ownership_graph",
        ["relationship_mapper"],
        ["get_relationship_graph_snapshot"],
    ),
    (
        "relationship_supply_chain_evidence",
        ["relationship_mapper"],
        ["get_supply_chain_evidence"],
    ),
    (
        "superinvestor_candidate_scope",
        ["superinvestor"],
        ["get_superinvestor_candidate_snapshot"],
    ),
    ("cro_bound_risk", ["cro"], ["get_cro_risk_snapshot"]),
    ("alpha_candidate_scope", ["alpha_discovery"], ["get_alpha_candidate_snapshot"]),
    (
        "execution_feasibility_scope",
        ["autonomous_execution"],
        ["get_execution_snapshot"],
    ),
    ("cio_decision_scope", ["cio"], ["get_cio_decision_snapshot"]),
)


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(_SHA_PREFIX):
        return False
    digest = value[len(_SHA_PREFIX) :]
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def _require_sha256(value: Any, field: str) -> str:
    if not _is_sha256(value):
        raise ValueError(f"{field} must be a canonical sha256")
    return str(value)


def _require_binding_id(value: Any, field: str = "binding_id") -> str:
    if not isinstance(value, str) or not value.startswith("binding:"):
        raise ValueError(f"{field} must be a canonical binding id")
    digest = value[len("binding:") :]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field} must be a canonical binding id")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _body_hash(value: Mapping[str, Any], *, hash_field: str = "manifest_hash") -> str:
    return canonical_hash({key: item for key, item in value.items() if key != hash_field})


def _validate_manifest_hash(value: Mapping[str, Any]) -> None:
    if value.get("manifest_hash") != _body_hash(value):
        raise ValueError(f"{value.get('schema_version', 'manifest')} hash mismatch")


def _output_owner_map(
    baseline_agent: str, current_agents: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    redistributed = {
        "central_bank": ["central_bank", "us_financial_conditions"],
        "dollar": ["us_financial_conditions"],
        "yield_curve": ["central_bank", "us_financial_conditions"],
        "volatility": ["us_financial_conditions"],
    }
    if baseline_agent in redistributed:
        return redistributed[baseline_agent]
    return [baseline_agent] if baseline_agent in current_agents else []


def _output_compatibility_inventory(
    baseline_runtime_manifest: Mapping[str, Any],
    current_runtime_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    current_agents = {row["agent"]: row for row in current_runtime_manifest["agents"]}
    inventory: list[dict[str, Any]] = []
    for baseline in baseline_runtime_manifest["agents"]:
        owners = _output_owner_map(baseline["agent"], current_agents)
        compatibility = "partial"
        if owners == [baseline["agent"]]:
            current = current_agents[baseline["agent"]]
            if (
                baseline["required_tools"] == current["required_tools"]
                and baseline["output_schema_fields"]
                == current["output_schema_fields"]
            ):
                compatibility = "preserved"
        inventory.append(
            {
                "baseline_agent_id": baseline["agent"],
                "baseline_stage_ids": [row["stage"] for row in baseline["stages"]],
                "baseline_required_tools": list(baseline["required_tools"]),
                "baseline_output_schema_fields": list(baseline["output_schema_fields"]),
                "current_owners": owners,
                "current_required_tools_by_owner": {
                    owner: list(current_agents[owner]["required_tools"]) for owner in owners
                },
                "current_output_schema_fields_by_owner": {
                    owner: list(current_agents[owner]["output_schema_fields"])
                    for owner in owners
                },
                "compatibility": compatibility,
                "consumer_refs": [
                    f"accepted-output-consumer:{owner}" for owner in owners
                ],
                "consumer_closure": "closed" if compatibility == "preserved" else "open",
            }
        )
    return inventory


def build_preservation_manifest(
    baseline_runtime_manifest: Mapping[str, Any],
    current_runtime_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    capabilities: list[dict[str, Any]] = []
    for source in _BASELINE_CAPABILITIES:
        row = {
            "semantic_capability_id": source["semantic_capability_id"],
            "baseline_tool_id": source["baseline_tool_id"],
            "baseline_consumers": list(source["baseline_consumers"]),
            "baseline_argument_fields": list(source["baseline_argument_fields"]),
            "baseline_argument_schema_hash": canonical_hash(
                {
                    "fields": source["baseline_argument_fields"],
                    "unknown_arguments": "rejected",
                }
            ),
            "current_owners": list(source["current_owners"]),
            "replacement_tools": list(source["replacement_tools"]),
            "disposition": source["disposition"],
            "equivalence_evidence_refs": (
                [f"current-tool:{tool}" for tool in source["replacement_tools"]]
                if source["disposition"] == "preserved"
                else []
            ),
            "privacy_class": source.get("privacy_class", "public_structured"),
            "adaptive_query_requirement": source.get(
                "adaptive_query_requirement", False
            ),
            "consumer_closure": (
                "closed" if source["disposition"] == "preserved" else "open"
            ),
            "approval_record": None,
        }
        capabilities.append(row)
    introduced = [
        {
            "semantic_capability_id": capability_id,
            "current_owners": owners,
            "replacement_tools": tools,
            "disposition": "introduced",
            "consumer_closure": "closed",
        }
        for capability_id, owners, tools in _INTRODUCED_CAPABILITIES
    ]
    body = {
        "schema_version": PRESERVATION_SCHEMA_VERSION,
        "baseline_commit": BASELINE_COMMIT,
        "baseline_runtime_manifest_hash": canonical_hash(baseline_runtime_manifest),
        "current_runtime_manifest_hash": canonical_hash(current_runtime_manifest),
        "baseline_agent_count": 25,
        "baseline_stage_count": 26,
        "baseline_capability_count": 23,
        "current_agent_count": 28,
        "current_stage_count": 29,
        "introduced_roles": list(_INTRODUCED_ROLES),
        "capabilities": capabilities,
        "introduced_capabilities": introduced,
        "output_compatibility_inventory": _output_compatibility_inventory(
            baseline_runtime_manifest, current_runtime_manifest
        ),
        "transition_freeze": {
            "state": "FROZEN_UNTIL_GATE_D",
            "allowed_actions": ["USE_ACTIVE_CHAMPION"],
            "blocked_actions": [
                "GENERATE_CANDIDATE",
                "RUN_EXPERIMENT",
                "JUDGE_EXPERIMENT",
                "PROMOTE_DECISION",
                "STAGE_PROMPT_RELEASE",
                "START_PROMPT_CANARY",
                "ACTIVATE_PROMPT_RELEASE",
            ],
        },
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def validate_preservation_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != PRESERVATION_SCHEMA_VERSION:
        raise ValueError("preservation manifest version mismatch")
    _validate_manifest_hash(manifest)
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list) or len(capabilities) != 23:
        raise ValueError("preservation manifest must contain 23 baseline capabilities")
    identities = [row.get("semantic_capability_id") for row in capabilities]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate preservation capability")
    for row in capabilities:
        disposition = row.get("disposition")
        if disposition not in _DISPOSITIONS - {"introduced"}:
            raise ValueError("invalid baseline capability disposition")
        if disposition == "equivalent" and (
            not row.get("equivalence_evidence_refs")
            or row.get("consumer_closure") != "closed"
        ):
            raise ValueError("equivalent capability lacks evidence or consumer closure")
        approval = row.get("approval_record")
        if disposition in _APPROVED_REDUCTIONS:
            required = {
                "decision_id",
                "actor",
                "decided_at",
                "lost_domain",
                "consumer_closure",
                "rollback_ref",
                "pi_review_ref",
            }
            if not isinstance(approval, dict) or set(approval) != required:
                raise ValueError("approved capability reduction requires named approval")
            if approval["consumer_closure"] != "closed":
                raise ValueError("approved capability reduction requires consumer closure")
        elif approval is not None:
            raise ValueError("approval record is only valid for an approved reduction")
    introduced = manifest.get("introduced_capabilities")
    if not isinstance(introduced, list) or not introduced:
        raise ValueError("introduced capabilities must be explicit")
    if any(row.get("disposition") != "introduced" for row in introduced):
        raise ValueError("introduced capability disposition mismatch")
    output_inventory = manifest.get("output_compatibility_inventory")
    if not isinstance(output_inventory, list) or len(output_inventory) != 25:
        raise ValueError("output compatibility inventory must cover 25 baseline agents")
    output_agents = [row.get("baseline_agent_id") for row in output_inventory]
    if len(set(output_agents)) != 25:
        raise ValueError("output compatibility inventory has duplicate agents")
    for row in output_inventory:
        if row.get("compatibility") not in {"preserved", "equivalent", "partial"}:
            raise ValueError("invalid output compatibility disposition")
        if row.get("compatibility") in {"preserved", "equivalent"} and row.get(
            "consumer_closure"
        ) != "closed":
            raise ValueError("preserved output compatibility requires consumer closure")


def rollout_blockers(manifest: Mapping[str, Any]) -> list[str]:
    validate_preservation_manifest(manifest)
    blockers: list[str] = []
    for row in manifest["capabilities"]:
        if row["disposition"] == "partial":
            blockers.append(f"capability_partial:{row['semantic_capability_id']}")
    for row in manifest["output_compatibility_inventory"]:
        if row["compatibility"] == "partial":
            blockers.append(f"output_partial:{row['baseline_agent_id']}")
    return sorted(blockers)


def _semantic_capabilities(agent_id: str, tool_id: str) -> tuple[str, ...]:
    direct = {
        "get_china_macro_snapshot": ("china_macro",),
        "get_us_macro_snapshot": ("us_macro",),
        "get_eu_macro_snapshot": ("eu_macro",),
        "get_central_bank_snapshot": (
            "central_bank_policy",
            "rates_credit",
            "china_yield_curve",
        ),
        "get_us_financial_conditions_snapshot": (
            "us_financial_conditions",
            "fx_conditions",
            "rates_credit",
            "volatility",
        ),
        "get_euro_area_financial_conditions_snapshot": (
            "euro_area_financial_conditions",
        ),
        "get_commodity_conditions_snapshot": ("commodity_conditions",),
        "get_geopolitical_events_snapshot": ("geopolitical_events",),
        "get_market_breadth_snapshot": ("market_breadth",),
        "get_market_positioning_snapshot": ("market_positioning",),
        "get_role_event_snapshot": ("role_event_calendar",),
        "get_relationship_graph_snapshot": ("relationship_ownership_graph",),
        "get_supply_chain_evidence": ("relationship_supply_chain_evidence",),
        "get_superinvestor_candidate_snapshot": ("superinvestor_candidate_scope",),
        "get_cro_risk_snapshot": ("cro_bound_risk",),
        "get_alpha_candidate_snapshot": ("alpha_candidate_scope",),
        "get_execution_snapshot": ("execution_feasibility_scope",),
        "get_cio_decision_snapshot": ("cio_decision_scope",),
    }
    if tool_id != "get_sector_research_snapshot":
        try:
            return direct[tool_id]
        except KeyError as exc:
            raise ValueError(f"no semantic capability mapping for {tool_id}") from exc
    values = [
        "stock_data",
        "technical_indicators",
        "income_statement",
        "cashflow_statement",
        "fundamentals",
    ]
    introduced_by_agent = {
        "technology": "technology_sector_snapshot",
        "real_estate_construction": "real_estate_sector_snapshot",
        "agriculture": "agriculture_sector_snapshot",
    }
    if agent_id in introduced_by_agent:
        values.append(introduced_by_agent[agent_id])
    return tuple(values)


def canonical_binding_id(binding_body: Mapping[str, Any]) -> str:
    return "binding:" + canonical_hash(binding_body)[len(_SHA_PREFIX) :]


def _route_contract_authority(
    current_tool_manifest: Mapping[str, Any],
    route_manifest: Mapping[str, Any],
) -> tuple[
    dict[tuple[str, str, str], tuple[str, ...]],
    dict[str, Mapping[str, Any]],
]:
    _validate_manifest_hash(route_manifest)
    if route_manifest.get("agent_tool_contract_manifest_hash") != canonical_hash(
        current_tool_manifest
    ):
        raise ValueError("agent data route manifest tool authority drift")
    routes = route_manifest.get("routes")
    route_bindings = route_manifest.get("bindings")
    if not isinstance(routes, list) or not isinstance(route_bindings, list):
        raise ValueError("agent data route manifest is malformed")
    routes_by_id = {str(row["route_id"]): row for row in routes}
    if len(routes_by_id) != len(routes):
        raise ValueError("agent data route manifest has duplicate routes")
    binding_routes: dict[tuple[str, str, str], tuple[str, ...]] = {}
    for row in route_bindings:
        key = (str(row["agent_id"]), str(row["stage"]), str(row["tool_id"]))
        route_ids = tuple(str(value) for value in row["required_route_ids"])
        if key in binding_routes:
            raise ValueError("agent data route manifest has duplicate bindings")
        if not route_ids or list(route_ids) != sorted(set(route_ids)):
            raise ValueError("agent data route binding must have sorted unique routes")
        if not set(route_ids) <= set(routes_by_id):
            raise ValueError("agent data route binding references an unknown route")
        binding_routes[key] = route_ids
    if set(binding_routes) != _surface(current_tool_manifest):
        raise ValueError("agent data route manifest active tool surface drift")
    return binding_routes, routes_by_id


def build_binding_manifest(
    current_tool_manifest: Mapping[str, Any],
    route_manifest: Mapping[str, Any],
    *,
    restored_bindings: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    bindings: list[dict[str, Any]] = []
    binding_routes, routes_by_id = _route_contract_authority(
        current_tool_manifest, route_manifest
    )
    restored_by_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in restored_bindings:
        key = (str(row["agent_id"]), str(row["stage"]), str(row["tool_id"]))
        if key in restored_by_key:
            raise ValueError("restored capability overlay has duplicate tool bindings")
        restored_by_key[key] = row
    if not set(restored_by_key) <= set(binding_routes):
        raise ValueError("restored capability overlay is outside the active tool surface")
    restored_fields = {
        "activation_state",
        "adaptive_query_contract",
        "agent_id",
        "argument_domain_selector_hash",
        "argument_schema_hash",
        "materializer_contract_hash",
        "output_semantics_hash",
        "phase",
        "privacy_contract_hash",
        "query_bundle_contract_version",
        "route_contract_hash",
        "semantic_capability_id",
        "source_route_ids",
        "stage",
        "tool_id",
    }
    argument_schema_hash = canonical_hash(
        {"type": "object", "properties": {}, "additionalProperties": False}
    )
    privacy_contract_hash = canonical_hash(
        {"contract": "PUBLIC_SAFE_REDACTED_V1", "source_prose": "forbidden"}
    )
    materializer_contract_hash = canonical_hash(
        {
            "snapshot_bundle_contract_version": "agent_snapshot_bundle_v1",
            "capability_contract_version": "agent_tool_capability_v1",
            "tools_call_transport": False,
        }
    )
    for agent in current_tool_manifest["agents"]:
        for stage in agent["execution_stages"]:
            for tool_id in agent["allowed_tools"]:
                key = (agent["agent_id"], stage, tool_id)
                source_route_ids = binding_routes[key]
                restored = restored_by_key.get(key)
                if restored is not None:
                    missing = restored_fields - set(restored)
                    if missing:
                        raise ValueError(
                            "restored capability overlay binding fields are incomplete"
                        )
                    restored_body = {
                        field: restored[field] for field in restored_fields
                    }
                    restored_source_route_ids = tuple(restored["source_route_ids"])
                    if source_route_ids != restored_source_route_ids:
                        if _APPROVED_RESTORED_ROUTE_MIGRATIONS.get(key) != (
                            restored_source_route_ids,
                            source_route_ids,
                        ):
                            raise ValueError(
                                "restored capability overlay source route binding drift"
                            )
                        restored_body["source_route_ids"] = list(source_route_ids)
                        restored_body["route_contract_hash"] = canonical_hash(
                            {
                                "routes": [
                                    routes_by_id[route_id]
                                    for route_id in source_route_ids
                                ]
                            }
                        )
                    restored_body["activation_state"] = "active"
                    bindings.append(
                        {
                            "binding_id": canonical_binding_id(restored_body),
                            **restored_body,
                        }
                    )
                    continue
                route_contract_hash = canonical_hash(
                    {
                        "source_routes": [
                            routes_by_id[route_id] for route_id in source_route_ids
                        ],
                        "query_bundle_contract_version": "frozen_snapshot_query_v1",
                        "unknown_route": "rejected",
                    }
                )
                domain_hash = canonical_hash(
                    {
                        "mode": "frozen_snapshot",
                        "agent_id": agent["agent_id"],
                        "stage": stage,
                        "tool_id": tool_id,
                    }
                )
                for semantic_capability_id in _semantic_capabilities(
                    agent["agent_id"], tool_id
                ):
                    body = {
                        "agent_id": agent["agent_id"],
                        "stage": stage,
                        "phase": "analysis",
                        "semantic_capability_id": semantic_capability_id,
                        "tool_id": tool_id,
                        "argument_schema_hash": argument_schema_hash,
                        "argument_domain_selector_hash": domain_hash,
                        "output_semantics_hash": canonical_hash(
                            {
                                "tool_id": tool_id,
                                "semantic_capability_id": semantic_capability_id,
                                "projection": "frozen_public_safe_v1",
                            }
                        ),
                        "source_route_ids": list(source_route_ids),
                        "route_contract_hash": route_contract_hash,
                        "materializer_contract_hash": materializer_contract_hash,
                        "query_bundle_contract_version": "frozen_snapshot_query_v1",
                        "privacy_contract_hash": privacy_contract_hash,
                        "adaptive_query_contract": {
                            "max_rounds": 0,
                            "model_selects_arguments": False,
                            "transport_allowed_during_call": False,
                        },
                        "activation_state": "active",
                    }
                    bindings.append(
                        {"binding_id": canonical_binding_id(body), **body}
                    )
    bindings.sort(key=lambda row: row["binding_id"])
    body = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "source_agent_tool_manifest_hash": canonical_hash(current_tool_manifest),
        "source_agent_data_route_manifest_hash": canonical_hash(route_manifest),
        "bindings": bindings,
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def build_staged_tool_contract_manifest(
    current_tool_manifest: Mapping[str, Any],
    route_manifest: Mapping[str, Any],
    binding_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    bindings = binding_manifest["bindings"]
    tools: list[dict[str, Any]] = []
    for agent in current_tool_manifest["agents"]:
        for stage in agent["execution_stages"]:
            for tool_id in agent["allowed_tools"]:
                rows = [
                    row
                    for row in bindings
                    if row["agent_id"] == agent["agent_id"]
                    and row["stage"] == stage
                    and row["tool_id"] == tool_id
                ]
                if not rows:
                    raise ValueError("staged tool lacks capability bindings")
                shared_fields = (
                    "argument_schema_hash",
                    "argument_domain_selector_hash",
                    "source_route_ids",
                    "route_contract_hash",
                    "materializer_contract_hash",
                    "query_bundle_contract_version",
                    "privacy_contract_hash",
                    "adaptive_query_contract",
                )
                for field in shared_fields:
                    if len({canonical_json(row[field]) for row in rows}) != 1:
                        raise ValueError(f"staged tool binding {field} drift")
                tools.append(
                    {
                        "agent_id": agent["agent_id"],
                        "stage": stage,
                        "phase": "analysis",
                        "tool_id": tool_id,
                        "activation_state": "staged",
                        "capability_binding_ids": sorted(
                            row["binding_id"] for row in rows
                        ),
                        "semantic_capability_ids": sorted(
                            row["semantic_capability_id"] for row in rows
                        ),
                        "argument_schema_hash": rows[0]["argument_schema_hash"],
                        "authorized_query_domain_hash": rows[0][
                            "argument_domain_selector_hash"
                        ],
                        "output_semantics_hash": canonical_hash(
                            {
                                row["semantic_capability_id"]: row[
                                    "output_semantics_hash"
                                ]
                                for row in sorted(
                                    rows, key=lambda item: item["semantic_capability_id"]
                                )
                            }
                        ),
                        "source_route_ids": rows[0]["source_route_ids"],
                        "route_contract_hash": rows[0]["route_contract_hash"],
                        "query_bundle_contract_version": rows[0][
                            "query_bundle_contract_version"
                        ],
                        "materializer_contract_hash": rows[0][
                            "materializer_contract_hash"
                        ],
                        "privacy_contract_hash": rows[0]["privacy_contract_hash"],
                        "adaptive_query_contract": rows[0]["adaptive_query_contract"],
                    }
                )
    tools.sort(key=lambda row: (row["agent_id"], row["stage"], row["tool_id"]))
    body = {
        "schema_version": STAGED_TOOL_CONTRACT_SCHEMA_VERSION,
        "base_active_agent_tool_manifest_hash": canonical_hash(current_tool_manifest),
        "base_agent_data_route_manifest_hash": canonical_hash(route_manifest),
        "capability_binding_manifest_hash": binding_manifest["manifest_hash"],
        "tools": tools,
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def _execution_release(root: Path) -> tuple[str, str]:
    pointer = _read_json(
        root / "registry/prompt_checks/prompt_release_contract_ref_v2.json"
    )
    if pointer.get("schema_version") != "prompt_release_contract_ref_v2":
        raise ValueError("execution release pointer schema mismatch")
    sources = pointer.get("sources")
    if not isinstance(sources, Mapping):
        raise ValueError("execution release pointer sources must be an object")
    source = sources.get("execution_behavior_release_archive")
    if not isinstance(source, Mapping):
        raise ValueError("execution release pointer source must be an object")
    release_id = source.get("release_id")
    if not isinstance(release_id, str) or not release_id.startswith(
        "execution-behavior-release:"
    ):
        raise ValueError("execution release ID is invalid")
    release_id_digest = release_id.removeprefix("execution-behavior-release:")
    if len(release_id_digest) != 64 or any(
        char not in "0123456789abcdef" for char in release_id_digest
    ):
        raise ValueError("execution release ID is invalid")
    release_hash = _require_sha256(source.get("release_hash"), "execution release hash")
    expected_ref = (
        "registry/prompt_checks/execution_behavior_releases/"
        f"{release_id_digest}--{release_hash.removeprefix(_SHA_PREFIX)}.json"
    )
    if source.get("path") != expected_ref:
        raise ValueError("content-addressed execution release path mismatch")
    archive_path = root / expected_ref
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("content-addressed execution release archive is unavailable")
    value = _read_json(archive_path)
    if value.get("schema_version") != "execution_behavior_release_manifest_v4":
        raise ValueError("execution release archive schema mismatch")
    if (
        value.get("execution_behavior_release_id") != release_id
        or value.get("execution_behavior_release_hash") != release_hash
    ):
        raise ValueError("execution release archive identity mismatch")
    if release_hash != canonical_hash(
        {
            key: item
            for key, item in value.items()
            if key != "execution_behavior_release_hash"
        }
    ):
        raise ValueError("execution release archive hash mismatch")
    return release_id, release_hash


def build_tool_environment_manifest(
    root: Path,
    current_tool_manifest: Mapping[str, Any],
    binding_manifest: Mapping[str, Any],
    staged_tool_contract_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    release_id, release_hash = _execution_release(root)
    bindings = binding_manifest["bindings"]
    environments: list[dict[str, Any]] = []
    for agent in current_tool_manifest["agents"]:
        for stage in agent["execution_stages"]:
            rows = [
                row
                for row in bindings
                if row["agent_id"] == agent["agent_id"] and row["stage"] == stage
            ]
            environments.append(
                {
                    "agent_id": agent["agent_id"],
                    "stage": stage,
                    "phase": "analysis",
                    "allowed_tools": list(agent["allowed_tools"]),
                    "binding_ids": sorted(row["binding_id"] for row in rows),
                    "argument_schema_hashes": {
                        tool: next(
                            row["argument_schema_hash"]
                            for row in rows
                            if row["tool_id"] == tool
                        )
                        for tool in agent["allowed_tools"]
                    },
                    "authorized_query_domain_hashes": {
                        tool: next(
                            row["argument_domain_selector_hash"]
                            for row in rows
                            if row["tool_id"] == tool
                        )
                        for tool in agent["allowed_tools"]
                    },
                    "snapshot_bundle_contract_version": "agent_snapshot_bundle_v1",
                    "query_bundle_contract_version": "frozen_snapshot_query_v1",
                    "materializer_contract_hash": rows[0]["materializer_contract_hash"],
                    "capability_contract_version": "agent_tool_capability_v1",
                    "privacy_contract_hash": rows[0]["privacy_contract_hash"],
                    "execution_behavior_release_id": release_id,
                    "execution_behavior_release_hash": release_hash,
                    "code_commit": STAGED_CODE_COMMIT,
                    "activation_state": "staged_contract_for_active_surface",
                }
            )
    environments.sort(key=lambda row: (row["agent_id"], row["stage"], row["phase"]))
    body = {
        "schema_version": TOOL_ENVIRONMENT_SCHEMA_VERSION,
        "source_agent_tool_manifest_hash": canonical_hash(current_tool_manifest),
        "capability_binding_manifest_hash": binding_manifest["manifest_hash"],
        "staged_agent_tool_contract_manifest_hash": staged_tool_contract_manifest[
            "manifest_hash"
        ],
        "environments": environments,
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def canonical_tool_environment_hash(environment_manifest: Mapping[str, Any]) -> str:
    return _body_hash(environment_manifest)


def build_knot_coverage_manifest(
    binding_manifest: Mapping[str, Any],
    tool_environment_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    environment_hash = canonical_tool_environment_hash(tool_environment_manifest)
    coverage: list[dict[str, Any]] = []
    for binding in binding_manifest["bindings"]:
        row = {
            key: binding[key]
            for key in (
                "binding_id",
                "agent_id",
                "stage",
                "phase",
                "semantic_capability_id",
                "tool_id",
                "argument_schema_hash",
                "argument_domain_selector_hash",
                "materializer_contract_hash",
                "privacy_contract_hash",
                "route_contract_hash",
            )
        }
        row.update(
            {
                "tool_environment_hash": environment_hash,
                "availability_evaluator_version": "tool_availability_v1",
                "call_evaluator_version": "tool_call_observation_v1",
                "success_evaluator_version": "tool_success_v1",
                "accepted_lineage_evaluator_version": "accepted_claim_lineage_v2",
                "counterevidence_evaluator_version": "counterevidence_rule_v1",
            }
        )
        row["coverage_row_hash"] = canonical_hash(row)
        coverage.append(row)
    coverage.sort(key=lambda row: row["binding_id"])
    body = {
        "schema_version": KNOT_COVERAGE_SCHEMA_VERSION,
        "capability_binding_manifest_hash": binding_manifest["manifest_hash"],
        "tool_environment_hash": environment_hash,
        "coverage": coverage,
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def _signal_selector_contract(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "selector_version": "trusted_structured_signal_selector_v1",
        "dimension_namespace": binding["semantic_capability_id"],
        "direction_keys": list(_TRUSTED_DIRECTION_KEYS),
        "direction_enum_version": "trusted_direction_enum_v1",
        "numeric_signal_suffixes": list(_TRUSTED_NUMERIC_SIGNAL_SUFFIXES),
        "numeric_normalization": "bounded_abs_v1",
        "unknown_policy": "explicit_unknown",
    }


def _claim_comparison_spec_contract(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "spec_version": "structured_conclusion_claim_spec_v1",
        "dimension_namespace": binding["semantic_capability_id"],
        "direction_keys": list(_TRUSTED_DIRECTION_KEYS),
        "direction_enum_version": "trusted_direction_enum_v1",
        "free_text_authority": False,
        "unknown_policy": "explicit_unknown",
    }


def _trusted_comparator_contract() -> dict[str, Any]:
    return {
        "comparator_version": "same_dimension_polarity_v1",
        "dimension_match": "exact",
        "aggregation": "max_strength_v1",
        "comparison": "support_minus_contradiction",
        "materiality_threshold": 0.25,
        "unknown_policy": "abstain",
    }


def build_knot_coverage_manifest_v2(
    binding_manifest: Mapping[str, Any],
    tool_environment_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    environment_hash = canonical_tool_environment_hash(tool_environment_manifest)
    coverage: list[dict[str, Any]] = []
    for binding in binding_manifest["bindings"]:
        selector = _signal_selector_contract(binding)
        claim_spec = _claim_comparison_spec_contract(binding)
        comparator = _trusted_comparator_contract()
        row = {
            key: binding[key]
            for key in (
                "binding_id",
                "agent_id",
                "stage",
                "phase",
                "semantic_capability_id",
                "tool_id",
                "argument_schema_hash",
                "argument_domain_selector_hash",
                "materializer_contract_hash",
                "privacy_contract_hash",
                "route_contract_hash",
            )
        }
        row.update(
            {
                "tool_environment_hash": environment_hash,
                "snapshot_audit_context_version": "snapshot_bundle_audit_context_v1",
                "capability_audit_context_version": "capability_audit_context_v1",
                "result_event_evaluator_version": "server_tool_result_event_v1",
                "binding_signal_projection_version": "binding_signal_projection_v1",
                "accepted_lineage_evaluator_version": "accepted_claim_lineage_v3",
                "runtime_blocker_policy_version": "runtime_blocker_exclusion_v1",
                "signal_selector_contract": selector,
                "signal_selector_contract_hash": canonical_hash(selector),
                "claim_comparison_spec_contract": claim_spec,
                "claim_comparison_spec_contract_hash": canonical_hash(claim_spec),
                "trusted_comparator_contract": comparator,
                "trusted_comparator_contract_hash": canonical_hash(comparator),
            }
        )
        row["coverage_row_hash"] = canonical_hash(row)
        coverage.append(row)
    coverage.sort(key=lambda row: row["binding_id"])
    body = {
        "schema_version": KNOT_COVERAGE_V2_SCHEMA_VERSION,
        "capability_binding_manifest_hash": binding_manifest["manifest_hash"],
        "tool_environment_hash": environment_hash,
        "coverage": coverage,
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def validate_knot_coverage_manifest_v2(
    manifest: Mapping[str, Any],
    *,
    binding_manifest: Mapping[str, Any],
    tool_environment_manifest: Mapping[str, Any],
) -> None:
    expected = build_knot_coverage_manifest_v2(
        binding_manifest, tool_environment_manifest
    )
    if canonical_json(manifest) != canonical_json(expected):
        raise ValueError("KNOT coverage v2 fixed-point mismatch")


def build_knot_audit_capability_track_v2(
    binding_manifest: Mapping[str, Any],
    tool_environment_manifest: Mapping[str, Any],
    knot_coverage_manifest_v2: Mapping[str, Any],
) -> dict[str, Any]:
    execution_release_hashes = {
        row["execution_behavior_release_hash"]
        for row in tool_environment_manifest["environments"]
    }
    if len(execution_release_hashes) != 1:
        raise ValueError("tool environment must bind exactly one execution release hash")
    body = {
        "schema_version": KNOT_AUDIT_TRACK_V2_SCHEMA_VERSION,
        "tool_environment_hash": canonical_tool_environment_hash(
            tool_environment_manifest
        ),
        "execution_behavior_release_hash": next(iter(execution_release_hashes)),
        "capability_binding_manifest_hash": binding_manifest["manifest_hash"],
        "knot_coverage_manifest_v2_hash": knot_coverage_manifest_v2["manifest_hash"],
        "snapshot_audit_context_version": "snapshot_bundle_audit_context_v1",
        "capability_audit_context_version": "capability_audit_context_v1",
        "result_event_schema_version": "server_tool_result_event_v1",
        "binding_signal_projection_version": "binding_signal_projection_v1",
        "claim_comparison_spec_version": "claim_comparison_spec_v1",
        "trusted_comparator_version": "same_dimension_polarity_v1",
    }
    return {**body, "track_hash": canonical_hash(body)}


def validate_knot_audit_capability_track_v2(
    track: Mapping[str, Any],
    *,
    binding_manifest: Mapping[str, Any],
    tool_environment_manifest: Mapping[str, Any],
    knot_coverage_manifest_v2: Mapping[str, Any],
) -> None:
    expected = build_knot_audit_capability_track_v2(
        binding_manifest, tool_environment_manifest, knot_coverage_manifest_v2
    )
    if canonical_json(track) != canonical_json(expected):
        raise ValueError("KNOT audit capability track v2 fixed-point mismatch")


def build_accepted_output_capability_track(
    binding_manifest: Mapping[str, Any],
    tool_environment_manifest: Mapping[str, Any],
    knot_coverage_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    execution_release_hashes = {
        row["execution_behavior_release_hash"]
        for row in tool_environment_manifest["environments"]
    }
    if len(execution_release_hashes) != 1:
        raise ValueError("tool environment must bind exactly one execution release hash")
    body = {
        "schema_version": ACCEPTED_OUTPUT_TRACK_SCHEMA_VERSION,
        "tool_environment_hash": canonical_tool_environment_hash(
            tool_environment_manifest
        ),
        "execution_behavior_release_hash": next(iter(execution_release_hashes)),
        "capability_binding_manifest_hash": binding_manifest["manifest_hash"],
        "knot_coverage_manifest_hash": knot_coverage_manifest["manifest_hash"],
    }
    return {**body, "capability_bundle_hash": canonical_hash(body)}


def _load_restored_bindings(root: Path) -> Sequence[Mapping[str, Any]]:
    from mosaic.scorecard.sector_relationship_preservation import (
        validate_sector_relationship_preservation_overlay,
    )

    sector_overlay = _read_json(
        root
        / "registry/prompt_checks/capability_preservation"
        / "sector_relationship_preservation_overlay_v1.json"
    )
    validate_sector_relationship_preservation_overlay(sector_overlay, root=root)
    sector_bindings = sector_overlay.get("bindings")
    if not isinstance(sector_bindings, list):
        raise ValueError("restored capability overlay bindings are malformed")

    from mosaic.scorecard.l3_l4_activation import active_stage_for_l3_l4_overlay
    from mosaic.scorecard.l3_l4_preservation import (
        validate_l3_l4_preservation_overlay,
    )

    l3_l4_overlay = _read_json(
        root
        / "registry/prompt_checks/capability_preservation"
        / "l3_l4_preservation_overlay_v1.json"
    )
    validate_l3_l4_preservation_overlay(l3_l4_overlay, root=root)
    l3_l4_bindings = l3_l4_overlay.get("bindings")
    if not isinstance(l3_l4_bindings, list):
        raise ValueError("L3/L4 restored capability overlay bindings are malformed")
    translated: list[Mapping[str, Any]] = [*sector_bindings]
    for binding in l3_l4_bindings:
        if not isinstance(binding, Mapping):
            raise ValueError("L3/L4 restored capability binding is malformed")
        row = dict(binding)
        row["stage"] = active_stage_for_l3_l4_overlay(
            str(row["agent_id"]), str(row["stage"])
        )
        translated.append(row)
    return translated


def _load_active_restored_bindings(
    root: Path, current_tool_manifest: Mapping[str, Any]
) -> Sequence[Mapping[str, Any]]:
    active_surface = _surface(current_tool_manifest)
    restored_bindings: list[Mapping[str, Any]] = []
    for row in _load_restored_bindings(root):
        key = (str(row["agent_id"]), str(row["stage"]), str(row["tool_id"]))
        if key in active_surface:
            restored_bindings.append(row)
        elif str(row["agent_id"]) != "relationship_mapper":
            raise ValueError(
                "restored capability overlay is outside the active tool surface"
            )
    return restored_bindings


def build_default_contract_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    directory = root / "registry/prompt_checks/capability_preservation"
    baseline = _read_json(directory / "runtime_agent_manifest_b9ab1e44_v2.json")
    current = _read_json(
        root / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
    )
    current_runtime = _read_json(
        root / "registry/prompt_checks/runtime_agent_manifest_v5.json"
    )
    routes = _read_json(root / "registry/data_sources/agent_data_route_manifest_v1.json")
    preservation = build_preservation_manifest(baseline, current_runtime)
    binding = build_binding_manifest(
        current,
        routes,
        restored_bindings=_load_active_restored_bindings(root, current),
    )
    staged = build_staged_tool_contract_manifest(current, routes, binding)
    environment = build_tool_environment_manifest(root, current, binding, staged)
    coverage = build_knot_coverage_manifest(binding, environment)
    track = build_accepted_output_capability_track(binding, environment, coverage)
    coverage_v2 = build_knot_coverage_manifest_v2(binding, environment)
    audit_track_v2 = build_knot_audit_capability_track_v2(
        binding, environment, coverage_v2
    )
    return {
        "current_runtime_agent_manifest_snapshot_v5.json": current_runtime,
        "agent_capability_preservation_manifest_v1.json": preservation,
        "agent_capability_binding_manifest_v1.json": binding,
        "staged_agent_tool_contract_manifest_v2.json": staged,
        "tool_environment_manifest_v1.json": environment,
        "knot_tool_coverage_manifest_v1.json": coverage,
        "accepted_output_capability_track_v1.json": track,
        "knot_tool_coverage_manifest_v2.json": coverage_v2,
        "knot_audit_capability_track_v2.json": audit_track_v2,
    }


def write_default_contract_artifacts(root: Path) -> None:
    directory = root / "registry/prompt_checks/capability_preservation"
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in build_default_contract_artifacts(root).items():
        (directory / name).write_text(canonical_json(value) + "\n", encoding="utf-8")


def load_capability_contract_bundle(root: Path) -> dict[str, Any]:
    directory = root / "registry/prompt_checks/capability_preservation"
    return {
        "baseline_runtime_manifest": _read_json(
            directory / "runtime_agent_manifest_b9ab1e44_v2.json"
        ),
        "current_runtime_manifest": _read_json(
            directory / "current_runtime_agent_manifest_snapshot_v5.json"
        ),
        "preservation_manifest": _read_json(
            directory / "agent_capability_preservation_manifest_v1.json"
        ),
        "binding_manifest": _read_json(
            directory / "agent_capability_binding_manifest_v1.json"
        ),
        "staged_tool_contract_manifest": _read_json(
            directory / "staged_agent_tool_contract_manifest_v2.json"
        ),
        "tool_environment_manifest": _read_json(
            directory / "tool_environment_manifest_v1.json"
        ),
        "knot_coverage_manifest": _read_json(
            directory / "knot_tool_coverage_manifest_v1.json"
        ),
        "accepted_output_capability_track": _read_json(
            directory / "accepted_output_capability_track_v1.json"
        ),
        "knot_coverage_manifest_v2": _read_json(
            directory / "knot_tool_coverage_manifest_v2.json"
        ),
        "knot_audit_capability_track_v2": _read_json(
            directory / "knot_audit_capability_track_v2.json"
        ),
    }


def load_active_capability_fixed_point(root: Path | None = None) -> dict[str, str]:
    """Load and validate the server-owned active capability/KNOT fixed point."""
    repo_root = root or Path(__file__).resolve().parents[2]
    current_tool_manifest = _read_json(
        repo_root / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
    )
    bundle = load_capability_contract_bundle(repo_root)
    validate_capability_contract_bundle(
        bundle,
        current_tool_manifest=current_tool_manifest,
    )
    coverage_v2 = bundle["knot_coverage_manifest_v2"]
    audit_track_v2 = bundle["knot_audit_capability_track_v2"]
    execution_hash = _require_sha256(
        audit_track_v2.get("execution_behavior_release_hash"),
        "execution_behavior_release_hash",
    )
    knot_v2_hash = _require_sha256(
        audit_track_v2.get("knot_coverage_manifest_v2_hash"),
        "knot_coverage_manifest_v2_hash",
    )
    if knot_v2_hash != coverage_v2.get("manifest_hash"):
        raise ValueError("active KNOT coverage v2 fixed-point mismatch")
    return {
        "execution_behavior_release_hash": execution_hash,
        "knot_coverage_manifest_v2_hash": knot_v2_hash,
    }


def _surface(manifest: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    return {
        (agent["agent_id"], stage, tool)
        for agent in manifest["agents"]
        for stage in agent["execution_stages"]
        for tool in agent["allowed_tools"]
    }


def validate_capability_contract_bundle(
    bundle: Mapping[str, Any], *, current_tool_manifest: Mapping[str, Any]
) -> None:
    preservation = bundle["preservation_manifest"]
    binding = bundle["binding_manifest"]
    staged = bundle["staged_tool_contract_manifest"]
    environment = bundle["tool_environment_manifest"]
    coverage = bundle["knot_coverage_manifest"]
    track = bundle["accepted_output_capability_track"]
    baseline = bundle["baseline_runtime_manifest"]
    current_runtime = bundle["current_runtime_manifest"]
    validate_preservation_manifest(preservation)
    for manifest in (binding, staged, environment, coverage):
        _validate_manifest_hash(manifest)
    if preservation["baseline_runtime_manifest_hash"] != canonical_hash(baseline):
        raise ValueError("baseline golden hash mismatch")
    current_runtime_path = (
        Path(__file__).resolve().parents[2]
        / "registry/prompt_checks/runtime_agent_manifest_v5.json"
    )
    active_current_runtime = _read_json(current_runtime_path)
    if canonical_hash(active_current_runtime) != canonical_hash(current_runtime):
        raise ValueError("runtime Agent/output contract drift from staged snapshot")
    if preservation["current_runtime_manifest_hash"] != canonical_hash(current_runtime):
        raise ValueError("preservation current runtime manifest hash mismatch")
    baseline_by_agent = {row["agent"]: row for row in baseline["agents"]}
    current_by_agent = {row["agent"]: row for row in current_runtime["agents"]}
    output_inventory = preservation["output_compatibility_inventory"]
    if set(baseline_by_agent) != {row["baseline_agent_id"] for row in output_inventory}:
        raise ValueError("output consumer inventory exact closure mismatch")
    for row in output_inventory:
        baseline_row = baseline_by_agent[row["baseline_agent_id"]]
        if (
            row["baseline_required_tools"] != baseline_row["required_tools"]
            or row["baseline_output_schema_fields"]
            != baseline_row["output_schema_fields"]
            or row["baseline_stage_ids"]
            != [stage["stage"] for stage in baseline_row["stages"]]
        ):
            raise ValueError("output consumer inventory baseline drift")
        owners = row["current_owners"]
        if set(owners) != set(row["current_required_tools_by_owner"]) or set(
            owners
        ) != set(row["current_output_schema_fields_by_owner"]):
            raise ValueError("output consumer inventory owner closure mismatch")
        if any(owner not in current_by_agent for owner in owners):
            raise ValueError("output consumer inventory has an unknown current owner")
        if any(
            row["current_required_tools_by_owner"][owner]
            != current_by_agent[owner]["required_tools"]
            or row["current_output_schema_fields_by_owner"][owner]
            != current_by_agent[owner]["output_schema_fields"]
            for owner in owners
        ):
            raise ValueError("output consumer inventory current runtime drift")
        if row["consumer_refs"] != [
            f"accepted-output-consumer:{owner}" for owner in owners
        ]:
            raise ValueError("output consumer inventory consumer reference drift")
        exact_preservation = False
        if owners == [row["baseline_agent_id"]]:
            exact_preservation = (
                row["baseline_required_tools"]
                == row["current_required_tools_by_owner"][owners[0]]
                and row["baseline_output_schema_fields"]
                == row["current_output_schema_fields_by_owner"][owners[0]]
            )
        if row["compatibility"] == "preserved" and not exact_preservation:
            raise ValueError("output compatibility preserved without exact contract")

    current_runtime_tools = {
        row["agent"]: tuple(row["required_tools"]) for row in current_runtime["agents"]
    }
    current_tool_rows = {
        row["agent_id"]: tuple(row["allowed_tools"])
        for row in current_tool_manifest["agents"]
    }
    if current_runtime_tools != current_tool_rows:
        raise ValueError("active tool surface: runtime call and Agent tool contract drift")

    if binding["source_agent_tool_manifest_hash"] != canonical_hash(current_tool_manifest):
        raise ValueError("binding source active tool surface hash mismatch")
    repository_root = Path(__file__).resolve().parents[2]
    route_manifest_path = (
        repository_root / "registry/data_sources/agent_data_route_manifest_v1.json"
    )
    route_manifest = _read_json(route_manifest_path)
    if binding["source_agent_data_route_manifest_hash"] != canonical_hash(
        route_manifest
    ):
        raise ValueError("binding source route manifest hash mismatch")
    bindings = binding["bindings"]
    binding_ids = [row["binding_id"] for row in bindings]
    if len(binding_ids) != len(set(binding_ids)):
        raise ValueError("duplicate binding id")
    known_semantics = {
        row["semantic_capability_id"] for row in preservation["capabilities"]
    } | {
        row["semantic_capability_id"]
        for row in preservation["introduced_capabilities"]
    }
    for row in bindings:
        body = {key: value for key, value in row.items() if key != "binding_id"}
        if row["binding_id"] != canonical_binding_id(body):
            raise ValueError("binding id hash mismatch")
        if row["semantic_capability_id"] not in known_semantics:
            raise ValueError("orphan semantic capability binding")
    bound_surface = {
        (row["agent_id"], row["stage"], row["tool_id"]) for row in bindings
    }
    if bound_surface != _surface(current_tool_manifest):
        raise ValueError("binding active tool surface exact closure mismatch")
    expected_binding = build_binding_manifest(
        current_tool_manifest,
        route_manifest,
        restored_bindings=_load_active_restored_bindings(
            repository_root, current_tool_manifest
        ),
    )
    if canonical_hash(binding) != canonical_hash(expected_binding):
        raise ValueError("binding whitelist/argument/route/capability contract drift")
    expected_staged = build_staged_tool_contract_manifest(
        current_tool_manifest, route_manifest, binding
    )
    if canonical_hash(staged) != canonical_hash(expected_staged):
        raise ValueError("staged agent tool/route/query contract drift")
    if environment["staged_agent_tool_contract_manifest_hash"] != staged[
        "manifest_hash"
    ]:
        raise ValueError("tool environment staged tool contract hash mismatch")

    expected_environments = {
        (agent["agent_id"], stage): tuple(agent["allowed_tools"])
        for agent in current_tool_manifest["agents"]
        for stage in agent["execution_stages"]
    }
    actual_environments: dict[tuple[str, str], tuple[str, ...]] = {}
    for row in environment["environments"]:
        key = (row["agent_id"], row["stage"])
        if key in actual_environments:
            raise ValueError("duplicate tool environment")
        actual_environments[key] = tuple(row["allowed_tools"])
        expected_binding_ids = sorted(
            binding_row["binding_id"]
            for binding_row in bindings
            if binding_row["agent_id"] == row["agent_id"]
            and binding_row["stage"] == row["stage"]
        )
        if row["binding_ids"] != expected_binding_ids:
            raise ValueError("tool environment binding closure mismatch")
    if actual_environments != expected_environments:
        raise ValueError("tool environment active stage closure mismatch")

    coverage_rows = coverage["coverage"]
    coverage_ids = [row["binding_id"] for row in coverage_rows]
    if len(coverage_ids) != len(set(coverage_ids)):
        raise ValueError("duplicate KNOT coverage binding")
    if set(coverage_ids) != set(binding_ids):
        raise ValueError("KNOT coverage exact closure mismatch")
    binding_by_id = {row["binding_id"]: row for row in bindings}
    for row in coverage_rows:
        binding_row = binding_by_id[row["binding_id"]]
        for field in (
            "agent_id",
            "stage",
            "phase",
            "semantic_capability_id",
            "tool_id",
            "argument_schema_hash",
            "argument_domain_selector_hash",
            "materializer_contract_hash",
            "privacy_contract_hash",
            "route_contract_hash",
        ):
            if row[field] != binding_row[field]:
                raise ValueError("KNOT coverage row binding drift")
        row_body = {
            key: value for key, value in row.items() if key != "coverage_row_hash"
        }
        if row["coverage_row_hash"] != canonical_hash(row_body):
            raise ValueError("KNOT coverage row hash mismatch")
    expected_environment_hash = canonical_tool_environment_hash(environment)
    if coverage["tool_environment_hash"] != expected_environment_hash or any(
        row["tool_environment_hash"] != expected_environment_hash
        for row in coverage_rows
    ):
        raise ValueError("KNOT coverage tool environment mismatch")
    validate_accepted_output_track_binding(track, bundle=bundle)
    coverage_v2 = bundle.get("knot_coverage_manifest_v2")
    audit_track_v2 = bundle.get("knot_audit_capability_track_v2")
    if (coverage_v2 is None) != (audit_track_v2 is None):
        raise ValueError("KNOT v2 coverage/track must be present together")
    if coverage_v2 is not None and audit_track_v2 is not None:
        validate_knot_coverage_manifest_v2(
            coverage_v2,
            binding_manifest=binding,
            tool_environment_manifest=environment,
        )
        validate_knot_audit_capability_track_v2(
            audit_track_v2,
            binding_manifest=binding,
            tool_environment_manifest=environment,
            knot_coverage_manifest_v2=coverage_v2,
        )


def validate_tool_config_hash(
    tool_config_hash: str, environment_manifest: Mapping[str, Any]
) -> None:
    if tool_config_hash != canonical_tool_environment_hash(environment_manifest):
        raise ValueError("toolConfigHash must equal canonical tool environment hash")


def validate_accepted_output_track_tags(
    tags: Mapping[str, Any], *, legacy_read_only: bool
) -> str:
    if legacy_read_only and not tags:
        return "LEGACY_READ_ONLY"
    if set(tags) != {"schema_version", *ACTIVE_TRACK_TAG_FIELDS}:
        raise ValueError("capture-time track tags are incomplete or contain drift")
    if tags["schema_version"] != ACCEPTED_OUTPUT_TRACK_SCHEMA_VERSION:
        raise ValueError("capture-time track version mismatch")
    for field in ACTIVE_TRACK_TAG_FIELDS:
        _require_sha256(tags[field], field)
    body = {
        "schema_version": tags["schema_version"],
        **{field: tags[field] for field in ACTIVE_TRACK_TAG_FIELDS[:-1]},
    }
    if tags["capability_bundle_hash"] != canonical_hash(body):
        raise ValueError("capability bundle hash mismatch")
    return "ACTIVE_TRACK"


def validate_accepted_output_track_binding(
    tags: Mapping[str, Any],
    *,
    bundle: Mapping[str, Any],
    execution_behavior_release_id: str | None = None,
) -> None:
    validate_accepted_output_track_tags(tags, legacy_read_only=False)
    expected = build_accepted_output_capability_track(
        bundle["binding_manifest"],
        bundle["tool_environment_manifest"],
        bundle["knot_coverage_manifest"],
    )
    if canonical_json(tags) != canonical_json(expected):
        raise ValueError("accepted output capability track fixed-point mismatch")
    if execution_behavior_release_id is not None:
        release_ids = {
            row["execution_behavior_release_id"]
            for row in bundle["tool_environment_manifest"]["environments"]
        }
        if release_ids != {execution_behavior_release_id}:
            raise ValueError("accepted output execution release is outside capability track")


def validate_capability_full_bundle(release: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "prompt_hash",
        "execution_behavior_release_hash",
        "production_variant_roster_hash",
        "runtime_agent_manifest_hash",
        "agent_tool_manifest_hash",
        "tool_environment_hash",
        "capability_binding_manifest_hash",
        "knot_coverage_manifest_hash",
        "knot_audit_capability_track_hash",
        "private_companion_pin_hash",
        "full_bundle_hash",
    }
    if set(release) != required:
        raise ValueError("capability full-bundle fields are incomplete")
    if release["schema_version"] != "capability_full_bundle_v1":
        raise ValueError("capability full-bundle version mismatch")
    for field in required - {"schema_version"}:
        _require_sha256(release[field], field)
    body = {key: value for key, value in release.items() if key != "full_bundle_hash"}
    if release["full_bundle_hash"] != canonical_hash(body):
        raise ValueError("capability full-bundle hash mismatch")


def tool_result_fingerprint(
    *,
    semantic_capability_id: str,
    binding_id: str,
    tool_id: str,
    canonical_args: Mapping[str, Any],
    payload: Any,
    build_receipt_hash: str,
    tool_environment_hash: str,
) -> str:
    return _tool_result_fingerprint_from_hashes(
        semantic_capability_id=semantic_capability_id,
        binding_id=binding_id,
        tool_id=tool_id,
        canonical_args_hash=canonical_hash(canonical_args),
        payload_hash=canonical_hash(payload),
        build_receipt_hash=build_receipt_hash,
        tool_environment_hash=tool_environment_hash,
    )


def _tool_result_fingerprint_from_hashes(
    *,
    semantic_capability_id: str,
    binding_id: str,
    tool_id: str,
    canonical_args_hash: str,
    payload_hash: str,
    build_receipt_hash: str,
    tool_environment_hash: str,
) -> str:
    if not semantic_capability_id or not tool_id:
        raise ValueError("tool result capability and tool identities are required")
    _require_binding_id(binding_id)
    for field, value in (
        ("canonical_args_hash", canonical_args_hash),
        ("payload_hash", payload_hash),
        ("build_receipt_hash", build_receipt_hash),
        ("tool_environment_hash", tool_environment_hash),
    ):
        _require_sha256(value, field)
    return canonical_hash(
        {
            "semantic_capability_id": semantic_capability_id,
            "binding_id": binding_id,
            "tool_id": tool_id,
            "canonical_args_hash": canonical_args_hash,
            "payload_hash": payload_hash,
            "build_receipt_hash": build_receipt_hash,
            "tool_environment_hash": tool_environment_hash,
        }
    )


def validate_evidence_claim_graph_v2(
    graph: Mapping[str, Any], *, bundle: Mapping[str, Any]
) -> None:
    required = {
        "schema_version",
        "run_id",
        "agent_id",
        "stage",
        "capability_track",
        "counterevidence_rule",
        "tool_results",
        "evidence_edges",
        "accepted_claims",
    }
    if set(graph) != required or graph.get("schema_version") != "evidence_claim_graph_v2":
        raise ValueError("evidence claim graph v2 shape mismatch")
    root = Path(__file__).resolve().parents[2]
    validate_capability_contract_bundle(
        bundle,
        current_tool_manifest=_read_json(
            root / "registry/prompt_checks/agent_tool_contract_manifest_v1.json"
        ),
    )
    capability_track = graph["capability_track"]
    validate_accepted_output_track_binding(capability_track, bundle=bundle)
    rule = graph["counterevidence_rule"]
    evaluate_counterevidence(rule, 0.0, 0.0)
    bindings = {
        row["binding_id"]: row for row in bundle["binding_manifest"]["bindings"]
    }
    successful: set[str] = set()
    result_fingerprints: set[str] = set()
    for result in graph["tool_results"]:
        if set(result) != {
            "fingerprint",
            "semantic_capability_id",
            "binding_id",
            "tool_id",
            "canonical_args_hash",
            "payload_hash",
            "build_receipt_hash",
            "tool_environment_hash",
            "status",
        }:
            raise ValueError("tool result lineage shape mismatch")
        binding = bindings.get(result["binding_id"])
        if binding is None or any(
            (
                binding["agent_id"] != graph["agent_id"],
                binding["stage"] != graph["stage"],
                binding["semantic_capability_id"] != result["semantic_capability_id"],
                binding["tool_id"] != result["tool_id"],
            )
        ):
            raise ValueError("tool result binding exact lookup mismatch")
        if result["tool_environment_hash"] != capability_track["tool_environment_hash"]:
            raise ValueError("tool result capability track environment mismatch")
        expected_fingerprint = _tool_result_fingerprint_from_hashes(
            semantic_capability_id=result["semantic_capability_id"],
            binding_id=result["binding_id"],
            tool_id=result["tool_id"],
            canonical_args_hash=result["canonical_args_hash"],
            payload_hash=result["payload_hash"],
            build_receipt_hash=result["build_receipt_hash"],
            tool_environment_hash=result["tool_environment_hash"],
        )
        if result["fingerprint"] != expected_fingerprint:
            raise ValueError("tool result fingerprint mismatch")
        if result["fingerprint"] in result_fingerprints:
            raise ValueError("duplicate tool result fingerprint")
        result_fingerprints.add(result["fingerprint"])
        if result["status"] not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("tool result status mismatch")
        if result["status"] == "SUCCEEDED":
            successful.add(result["fingerprint"])
    claims = {row["claim_id"]: row for row in graph["accepted_claims"]}
    if len(claims) != len(graph["accepted_claims"]):
        raise ValueError("duplicate accepted claim id")
    edges_by_claim: dict[str, list[Mapping[str, Any]]] = {
        claim_id: [] for claim_id in claims
    }
    edge_ids: set[str] = set()
    for edge in graph["evidence_edges"]:
        if set(edge) != {
            "edge_id",
            "claim_id",
            "tool_result_fingerprint",
            "relation",
            "polarity",
            "comparison_value",
        }:
            raise ValueError("typed evidence edge shape mismatch")
        if edge["edge_id"] in edge_ids:
            raise ValueError("duplicate evidence edge id")
        edge_ids.add(edge["edge_id"])
        if edge["tool_result_fingerprint"] not in successful:
            raise ValueError("evidence edge must reference a successful tool result")
        if edge["claim_id"] not in claims:
            raise ValueError("evidence edge references unknown accepted claim")
        if edge["relation"] not in {"supports", "contradicts", "bounds"}:
            raise ValueError("evidence relation is not typed")
        if edge["polarity"] not in {"supporting", "contradicting"}:
            raise ValueError("evidence polarity is not typed")
        if (
            edge["relation"] == "supports" and edge["polarity"] != "supporting"
        ) or (
            edge["relation"] == "contradicts"
            and edge["polarity"] != "contradicting"
        ):
            raise ValueError("evidence relation polarity mismatch")
        comparison_value = edge["comparison_value"]
        if (
            isinstance(comparison_value, bool)
            or not isinstance(comparison_value, (int, float))
            or not math.isfinite(float(comparison_value))
            or not 0 <= float(comparison_value) <= 1
        ):
            raise ValueError("evidence comparison value must be finite in [0, 1]")
        edges_by_claim[edge["claim_id"]].append(edge)
    for claim_id, claim in claims.items():
        if set(claim) != {
            "claim_id",
            "accepted",
            "comparison_witness",
            "resolution_code",
        }:
            raise ValueError("accepted claim lineage shape mismatch")
        if claim["accepted"] is not True or claim["resolution_code"] not in _RESOLUTION_CODES:
            raise ValueError("accepted claim resolution code mismatch")
        claim_edges = edges_by_claim[claim_id]
        if not claim_edges:
            raise ValueError("accepted claim lacks typed evidence lineage")
        supporting = sorted(
            (edge for edge in claim_edges if edge["polarity"] == "supporting"),
            key=lambda edge: edge["edge_id"],
        )
        contradicting = sorted(
            (edge for edge in claim_edges if edge["polarity"] == "contradicting"),
            key=lambda edge: edge["edge_id"],
        )
        supporting_value = (
            max(float(edge["comparison_value"]) for edge in supporting)
            if supporting
            else None
        )
        contradicting_value = (
            max(float(edge["comparison_value"]) for edge in contradicting)
            if contradicting
            else None
        )
        expected_witness = {
            "supporting_edge_ids": [edge["edge_id"] for edge in supporting],
            "contradicting_edge_ids": [edge["edge_id"] for edge in contradicting],
            "supporting_value": supporting_value,
            "contradicting_value": contradicting_value,
        }
        if claim["comparison_witness"] != expected_witness:
            raise ValueError("accepted claim comparison witness mismatch")
        expected_resolution = evaluate_counterevidence(
            rule, supporting_value, contradicting_value
        )
        if claim["resolution_code"] != expected_resolution:
            raise ValueError("accepted claim resolution derivation mismatch")


def evaluate_counterevidence(
    rule: Mapping[str, Any], supporting: float | None, contradicting: float | None
) -> str:
    required = {
        "rule_version",
        "dimension",
        "polarity_extractor_version",
        "aggregation",
        "comparison",
        "threshold",
        "unknown_policy",
    }
    if set(rule) != required or rule["rule_version"] != "counterevidence_rule_v1":
        raise ValueError("counterevidence rule contract mismatch")
    if (
        rule["polarity_extractor_version"] != "signed_numeric_v1"
        or rule["aggregation"] != "max_strength_v1"
        or rule["comparison"] != "support_minus_contradiction"
        or rule["unknown_policy"] != "abstain"
    ):
        raise ValueError("unsupported counterevidence evaluator contract")
    threshold = rule["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or threshold < 0:
        raise ValueError("counterevidence threshold must be non-negative")
    if supporting is None or contradicting is None:
        return "abstained"
    delta = float(supporting) - float(contradicting)
    if delta > float(threshold):
        return "rebutted_with_evidence"
    if delta < -float(threshold):
        return "reversed"
    return "qualified"


def _direction_polarity(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _TRUSTED_DIRECTION_ENUM.get(value.strip().casefold())


def _trusted_signal_rows(
    value: Any,
    *,
    dimension_namespace: str,
    path: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key in sorted(value):
            if not isinstance(key, str):
                continue
            item = value[key]
            item_path = (*path, key)
            normalized_key = key.casefold()
            polarity = (
                _direction_polarity(item)
                if normalized_key in _TRUSTED_DIRECTION_KEYS
                else None
            )
            strength: float | None = 1.0 if polarity is not None else None
            numeric_signal = normalized_key in _TRUSTED_DIRECTION_KEYS or any(
                normalized_key.endswith(suffix)
                for suffix in _TRUSTED_NUMERIC_SIGNAL_SUFFIXES
            )
            if (
                polarity is None
                and numeric_signal
                and not isinstance(item, bool)
                and isinstance(item, (int, float))
                and math.isfinite(float(item))
            ):
                numeric = float(item)
                polarity = (
                    "positive" if numeric > 0 else "negative" if numeric < 0 else "neutral"
                )
                strength = abs(numeric) / (1.0 + abs(numeric))
            if polarity is not None and strength is not None:
                signal = {
                    "dimension": f"{dimension_namespace}:{normalized_key}",
                    "polarity": polarity,
                    "strength": strength,
                    "source_path_hash": canonical_hash(list(item_path)),
                }
                signal["signal_id"] = canonical_hash(
                    {"schema_version": "trusted_signal_v1", **signal}
                )
                rows.append(signal)
            rows.extend(
                _trusted_signal_rows(
                    item,
                    dimension_namespace=dimension_namespace,
                    path=item_path,
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(
                _trusted_signal_rows(
                    item,
                    dimension_namespace=dimension_namespace,
                    path=(*path, str(index)),
                )
            )
    unique = {row["signal_id"]: row for row in rows}
    return sorted(unique.values(), key=lambda row: row["signal_id"])


def build_binding_signal_projection_v1(
    *,
    event: Mapping[str, Any],
    result_event_hash: str,
    binding_ref: Mapping[str, Any],
    payload_text: str,
    coverage_row: Mapping[str, Any],
) -> dict[str, Any]:
    if canonical_hash(event) != result_event_hash:
        raise ValueError("server result event hash mismatch")
    if (
        event.get("schema_version") != "server_tool_result_event_v1"
        or event.get("status") != "SUCCEEDED"
        or event.get("payload_hash") != canonical_hash({"text": payload_text})
    ):
        raise ValueError("server result event is not projection eligible")
    if not isinstance(event.get("binding_refs"), list) or not any(
        canonical_json(ref) == canonical_json(binding_ref)
        for ref in event["binding_refs"]
    ):
        raise ValueError("binding ref is outside the server result event")
    coverage_body = {
        key: value for key, value in coverage_row.items() if key != "coverage_row_hash"
    }
    selector = coverage_row.get("signal_selector_contract")
    if (
        coverage_row.get("coverage_row_hash") != canonical_hash(coverage_body)
        or not isinstance(selector, Mapping)
        or coverage_row.get("signal_selector_contract_hash")
        != canonical_hash(selector)
        or binding_ref.get("binding_id") != coverage_row.get("binding_id")
        or binding_ref.get("semantic_capability_id")
        != coverage_row.get("semantic_capability_id")
        or binding_ref.get("coverage_row_hash")
        != coverage_row.get("coverage_row_hash")
    ):
        raise ValueError("binding projection coverage authority mismatch")
    try:
        payload = json.loads(payload_text)
    except (TypeError, json.JSONDecodeError):
        payload = None
    signals = _trusted_signal_rows(
        payload,
        dimension_namespace=str(selector["dimension_namespace"]),
    )
    body = {
        "schema_version": "binding_signal_projection_v1",
        "result_event_id": event["result_event_id"],
        "result_event_hash": result_event_hash,
        "binding_id": binding_ref["binding_id"],
        "binding_result_fingerprint": binding_ref["binding_result_fingerprint"],
        "coverage_row_hash": coverage_row["coverage_row_hash"],
        "signal_selector_contract_hash": coverage_row[
            "signal_selector_contract_hash"
        ],
        "projection_status": "PROJECTED" if signals else "UNKNOWN",
        "unknown_reason": None if signals else "NO_TRUSTED_SIGNAL",
        "signals": signals,
    }
    return {**body, "projection_hash": canonical_hash(body)}


def _claims_from_accepted_output(value: Any) -> list[Mapping[str, Any]]:
    claims: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        candidate = value.get("claims")
        if isinstance(candidate, list):
            claims.extend(row for row in candidate if isinstance(row, Mapping))
        for key, item in value.items():
            if key != "claims":
                claims.extend(_claims_from_accepted_output(item))
    elif isinstance(value, list):
        for item in value:
            claims.extend(_claims_from_accepted_output(item))
    by_id: dict[str, Mapping[str, Any]] = {}
    for claim in claims:
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            raise ValueError("accepted claim id is missing")
        if claim_id in by_id and canonical_json(by_id[claim_id]) != canonical_json(claim):
            raise ValueError("accepted claim id is ambiguous")
        by_id[claim_id] = claim
    return [by_id[claim_id] for claim_id in sorted(by_id)]


def build_claim_comparison_specs_v1(
    *,
    accepted_output: Mapping[str, Any],
    accepted_output_hash: str,
    coverage_row: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if accepted_output_hash != canonical_hash(accepted_output):
        raise ValueError("accepted output hash mismatch")
    contract = coverage_row.get("claim_comparison_spec_contract")
    comparator = coverage_row.get("trusted_comparator_contract")
    if (
        not isinstance(contract, Mapping)
        or not isinstance(comparator, Mapping)
        or coverage_row.get("claim_comparison_spec_contract_hash")
        != canonical_hash(contract)
        or coverage_row.get("trusted_comparator_contract_hash")
        != canonical_hash(comparator)
    ):
        raise ValueError("claim comparison contract authority mismatch")
    specs: list[dict[str, Any]] = []
    allowed_keys = set(contract["direction_keys"])
    for claim in _claims_from_accepted_output(accepted_output):
        conclusion = claim.get("structured_conclusion")
        candidates: list[tuple[str, str]] = []
        if isinstance(conclusion, Mapping):
            for key in sorted(conclusion):
                polarity = (
                    _direction_polarity(conclusion[key])
                    if isinstance(key, str) and key.casefold() in allowed_keys
                    else None
                )
                if polarity is not None:
                    candidates.append((key.casefold(), polarity))
        ready = len(candidates) == 1
        body = {
            "schema_version": "claim_comparison_spec_v1",
            "accepted_output_hash": accepted_output_hash,
            "claim_id": claim["claim_id"],
            "binding_id": coverage_row["binding_id"],
            "semantic_capability_id": coverage_row["semantic_capability_id"],
            "claim_comparison_spec_contract_hash": coverage_row[
                "claim_comparison_spec_contract_hash"
            ],
            "trusted_comparator_contract": dict(comparator),
            "trusted_comparator_contract_hash": coverage_row[
                "trusted_comparator_contract_hash"
            ],
            "spec_status": "READY" if ready else "UNKNOWN",
            "dimension": (
                f"{contract['dimension_namespace']}:{candidates[0][0]}"
                if ready
                else None
            ),
            "target_polarity": candidates[0][1] if ready else "unknown",
            "unknown_reason": (
                None
                if ready
                else "NO_TRUSTED_TARGET"
                if not candidates
                else "AMBIGUOUS_TRUSTED_TARGET"
            ),
        }
        specs.append({**body, "spec_hash": canonical_hash(body)})
    return specs


def _validated_hashed_body(value: Mapping[str, Any], hash_field: str) -> None:
    if hash_field not in value:
        raise ValueError(f"{hash_field} is missing")
    body = {key: item for key, item in value.items() if key != hash_field}
    if value[hash_field] != canonical_hash(body):
        raise ValueError(f"{hash_field} mismatch")


def compare_binding_projection_v1(
    *,
    projection: Mapping[str, Any],
    claim_spec: Mapping[str, Any],
) -> dict[str, Any]:
    _validated_hashed_body(projection, "projection_hash")
    _validated_hashed_body(claim_spec, "spec_hash")
    comparator = claim_spec.get("trusted_comparator_contract")
    if (
        projection.get("binding_id") != claim_spec.get("binding_id")
        or not isinstance(comparator, Mapping)
        or claim_spec.get("trusted_comparator_contract_hash")
        != canonical_hash(comparator)
        or comparator.get("comparator_version") != "same_dimension_polarity_v1"
    ):
        raise ValueError("trusted comparator authority mismatch")
    dimension = claim_spec.get("dimension")
    signals = (
        [
            signal
            for signal in projection.get("signals", [])
            if isinstance(signal, Mapping) and signal.get("dimension") == dimension
        ]
        if projection.get("projection_status") == "PROJECTED"
        and claim_spec.get("spec_status") == "READY"
        else []
    )
    target = claim_spec.get("target_polarity")
    matched: list[dict[str, Any]] = []
    for signal in signals:
        polarity = signal.get("polarity")
        relation = (
            "supporting"
            if polarity == target
            else "contradicting"
            if polarity in {"positive", "negative", "neutral"}
            else None
        )
        if relation is not None:
            matched.append(
                {
                    "signal_id": signal["signal_id"],
                    "relation": relation,
                    "strength": signal["strength"],
                }
            )
    matched.sort(key=lambda row: row["signal_id"])
    evaluated = bool(matched)
    supporting = max(
        (float(row["strength"]) for row in matched if row["relation"] == "supporting"),
        default=0.0,
    )
    contradicting = max(
        (
            float(row["strength"])
            for row in matched
            if row["relation"] == "contradicting"
        ),
        default=0.0,
    )
    threshold = float(comparator["materiality_threshold"])
    delta = supporting - contradicting
    resolution = (
        "abstained"
        if not evaluated
        else "rebutted_with_evidence"
        if delta > threshold
        else "reversed"
        if delta < -threshold
        else "qualified"
    )
    counterevidence_available = evaluated and contradicting > 0
    body = {
        "schema_version": "trusted_counterevidence_evaluation_v2",
        "binding_id": projection["binding_id"],
        "binding_result_fingerprint": projection["binding_result_fingerprint"],
        "projection_hash": projection["projection_hash"],
        "spec_hash": claim_spec["spec_hash"],
        "claim_id": claim_spec["claim_id"],
        "dimension": dimension if evaluated else None,
        "target_polarity": target if evaluated else "unknown",
        "evaluation_status": "EVALUATED" if evaluated else "UNKNOWN",
        "unknown_reason": None if evaluated else "NO_SAME_DIMENSION_SIGNAL",
        "matched_signal_refs": matched,
        "supporting_strength": supporting if evaluated else None,
        "contradicting_strength": contradicting if evaluated else None,
        "resolution_code": resolution,
        "counterevidence_available": counterevidence_available,
        "counterevidence_handled": counterevidence_available and evaluated,
        "trusted_comparator_contract_hash": claim_spec[
            "trusted_comparator_contract_hash"
        ],
    }
    return {**body, "evaluation_hash": canonical_hash(body)}


def validate_trusted_counterevidence_evaluation_v2(
    evaluation: Mapping[str, Any],
    *,
    projection: Mapping[str, Any],
    claim_spec: Mapping[str, Any],
) -> None:
    expected = compare_binding_projection_v1(
        projection=projection,
        claim_spec=claim_spec,
    )
    if set(evaluation) != set(expected):
        raise ValueError("trusted counterevidence evaluation shape mismatch")
    if canonical_json(evaluation) != canonical_json(expected):
        raise ValueError("trusted counterevidence evaluation derivation mismatch")


def build_knot_capability_use_aggregate(
    *, binding_id: str, observations: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    counts = Counter[str]()
    gaps = Counter[str]()
    for observation in observations:
        if not observation.get("eligible"):
            counts["excluded"] += 1
            continue
        counts["eligible"] += 1
        if not observation.get("ready"):
            counts["runtime_blocker"] += 1
            continue
        counts["ready"] += 1
        if not observation.get("called"):
            gaps["not_called"] += 1
            continue
        counts["called"] += 1
        if not observation.get("succeeded"):
            gaps["call_failed"] += 1
            continue
        counts["succeeded"] += 1
        if not observation.get("used_in_accepted_evidence"):
            gaps["succeeded_not_used"] += 1
            continue
        counts["used"] += 1
        if observation.get("counterevidence_available"):
            counts["counterevidence_available"] += 1
            if observation.get("counterevidence_handled"):
                counts["counterevidence_handled"] += 1
            else:
                gaps["counterevidence_ignored"] += 1
    gap_counts = {
        name: gaps[name]
        for name in (
            "not_called",
            "call_failed",
            "succeeded_not_used",
            "counterevidence_ignored",
        )
    }
    body = {
        "schema_version": KNOT_AGGREGATE_SCHEMA_VERSION,
        "binding_id": binding_id,
        "eligible_count": counts["eligible"],
        "ready_count": counts["ready"],
        "called_count": counts["called"],
        "succeeded_count": counts["succeeded"],
        "used_in_accepted_evidence_count": counts["used"],
        "counterevidence_available_count": counts["counterevidence_available"],
        "counterevidence_handled_count": counts["counterevidence_handled"],
        "runtime_blocker_count": counts["runtime_blocker"],
        "excluded_count": counts["excluded"],
        "gap_counts": gap_counts,
        "model_controllable_gap_count": sum(gap_counts.values()),
        "opaque_failure_refs": [],
    }
    aggregate = {**body, "aggregate_hash": canonical_hash(body)}
    validate_knot_capability_use_aggregate(aggregate)
    return aggregate


def validate_knot_capability_use_aggregate(aggregate: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "binding_id",
        "eligible_count",
        "ready_count",
        "called_count",
        "succeeded_count",
        "used_in_accepted_evidence_count",
        "counterevidence_available_count",
        "counterevidence_handled_count",
        "runtime_blocker_count",
        "excluded_count",
        "gap_counts",
        "model_controllable_gap_count",
        "opaque_failure_refs",
        "aggregate_hash",
    }
    if set(aggregate) != required or aggregate.get("schema_version") != KNOT_AGGREGATE_SCHEMA_VERSION:
        raise ValueError("KNOT aggregate shape mismatch")
    _require_binding_id(aggregate["binding_id"])
    count_fields = required - {
        "schema_version",
        "binding_id",
        "gap_counts",
        "opaque_failure_refs",
        "aggregate_hash",
    }
    if any(
        isinstance(aggregate[field], bool)
        or not isinstance(aggregate[field], int)
        or aggregate[field] < 0
        for field in count_fields
    ):
        raise ValueError("KNOT aggregate counts must be non-negative integers")
    gaps = aggregate["gap_counts"]
    gap_names = {
        "not_called",
        "call_failed",
        "succeeded_not_used",
        "counterevidence_ignored",
    }
    if not isinstance(gaps, Mapping) or set(gaps) != gap_names or any(
        isinstance(gaps[name], bool)
        or not isinstance(gaps[name], int)
        or gaps[name] < 0
        for name in gap_names
    ):
        raise ValueError("KNOT aggregate gap counts are invalid")
    if (
        aggregate["eligible_count"]
        != aggregate["ready_count"] + aggregate["runtime_blocker_count"]
        or aggregate["ready_count"]
        != aggregate["called_count"] + gaps["not_called"]
        or aggregate["called_count"]
        != aggregate["succeeded_count"] + gaps["call_failed"]
        or aggregate["succeeded_count"]
        != aggregate["used_in_accepted_evidence_count"]
        + gaps["succeeded_not_used"]
        or aggregate["counterevidence_available_count"]
        != aggregate["counterevidence_handled_count"]
        + gaps["counterevidence_ignored"]
        or aggregate["counterevidence_available_count"]
        > aggregate["used_in_accepted_evidence_count"]
    ):
        raise ValueError("KNOT aggregate count conservation mismatch")
    if aggregate["model_controllable_gap_count"] != sum(gaps.values()):
        raise ValueError("KNOT aggregate gap total mismatch")
    refs = aggregate["opaque_failure_refs"]
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
        raise ValueError("KNOT aggregate opaque failure refs are invalid")
    body = {key: value for key, value in aggregate.items() if key != "aggregate_hash"}
    if aggregate["aggregate_hash"] != canonical_hash(body):
        raise ValueError("KNOT aggregate hash mismatch")


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an offset")
    return parsed


def is_mature_sample_eligible(
    sample: Mapping[str, Any], *, cutoff_at: str, outcome_contract_hash: str
) -> bool:
    try:
        return (
            _instant(sample.get("matured_at")) <= _instant(cutoff_at)
            and sample.get("outcome_contract_hash") == outcome_contract_hash
            and _is_sha256(sample.get("trading_calendar_hash"))
            and _is_sha256(sample.get("label_receipt_hash"))
        )
    except ValueError:
        return False


def validate_public_safe_projection(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _PUBLIC_FORBIDDEN_KEYS:
                raise ValueError("public projection contains private or licensed content")
            validate_public_safe_projection(item)
    elif isinstance(value, list):
        for item in value:
            validate_public_safe_projection(item)


def assert_knot_action(action: str, preservation_manifest: Mapping[str, Any]) -> None:
    freeze = preservation_manifest.get("transition_freeze")
    if not isinstance(freeze, dict) or freeze.get("state") != "FROZEN_UNTIL_GATE_D":
        raise ValueError("KNOT transition freeze contract missing")
    if action not in freeze.get("allowed_actions", []):
        raise ValueError(f"KNOT evolution frozen until Gate D: {action}")


__all__ = [
    "ACTIVE_TRACK_TAG_FIELDS",
    "assert_knot_action",
    "build_accepted_output_capability_track",
    "build_binding_signal_projection_v1",
    "build_claim_comparison_specs_v1",
    "build_default_contract_artifacts",
    "build_knot_audit_capability_track_v2",
    "build_knot_capability_use_aggregate",
    "build_knot_coverage_manifest_v2",
    "canonical_binding_id",
    "canonical_tool_environment_hash",
    "compare_binding_projection_v1",
    "evaluate_counterevidence",
    "is_mature_sample_eligible",
    "load_active_capability_fixed_point",
    "load_capability_contract_bundle",
    "rollout_blockers",
    "tool_result_fingerprint",
    "validate_accepted_output_track_tags",
    "validate_accepted_output_track_binding",
    "validate_capability_contract_bundle",
    "validate_evidence_claim_graph_v2",
    "validate_capability_full_bundle",
    "validate_knot_audit_capability_track_v2",
    "validate_knot_capability_use_aggregate",
    "validate_knot_coverage_manifest_v2",
    "validate_preservation_manifest",
    "validate_public_safe_projection",
    "validate_tool_config_hash",
    "validate_trusted_counterevidence_evaluation_v2",
    "write_default_contract_artifacts",
]

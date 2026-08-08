"""Staged L3/L4 capability-preservation contracts.

This overlay freezes the pre-migration Superinvestor due-diligence surface and
the five decision-stage RKE priors without changing the active tool manifest.
All ticker-bearing queries are constrained to the accepted candidate scope.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.sector_relationship_preservation import (
    build_sector_relationship_preservation_overlay,
    evaluate_sector_relationship_significance_fixture,
)


SCHEMA_VERSION = "l3_l4_preservation_overlay_v1"
ACTIVATION_GATE = "PR13_L3_L4_ATOMIC_ACTIVATION"
QUERY_BUNDLE_CONTRACT_VERSION = "frozen_bound_runtime_query_bundle_v1"
KNOT_EVALUATOR_CONTRACT_VERSION = "knot_binding_lineage_evaluator_v1"
SIGNIFICANCE_CONTRACT_VERSION = "paired_binding_significance_fixture_v1"

L3_TOOL_ROSTER: dict[str, tuple[str, ...]] = {
    "druckenmiller": (
        "get_rke_research_context",
        "get_yield_curve_cn",
        "get_industry_policy_digest",
        "get_stock_research",
        "get_fundamentals",
        "get_stock_data",
        "get_indicators",
    ),
    "munger": (
        "get_rke_research_context",
        "get_stock_research",
        "get_fundamentals",
        "get_income_statement",
        "get_cashflow",
        "get_balance_sheet",
        "get_stock_data",
    ),
    "burry": (
        "get_rke_research_context",
        "get_stock_research",
        "get_fundamentals",
        "get_income_statement",
        "get_cashflow",
        "get_balance_sheet",
        "get_stock_data",
    ),
    "ackman": (
        "get_rke_research_context",
        "get_stock_research",
        "get_fundamentals",
        "get_income_statement",
        "get_cashflow",
        "get_balance_sheet",
        "get_stock_data",
    ),
}

L4_STAGE_ROSTER: tuple[tuple[str, str], ...] = (
    ("alpha_discovery", "alpha_discovery"),
    ("cro", "cro_review"),
    ("autonomous_execution", "execution_feasibility"),
    ("cio", "cio_proposal"),
    ("cio", "cio_final"),
)

_TOOL_CAPABILITY = {
    "get_rke_research_context": "rke_research_context",
    "get_yield_curve_cn": "china_yield_curve",
    "get_industry_policy_digest": "industry_policy_digest",
    "get_stock_research": "stock_research",
    "get_fundamentals": "fundamentals",
    "get_income_statement": "income_statement",
    "get_cashflow": "cashflow_statement",
    "get_balance_sheet": "balance_sheet",
    "get_stock_data": "stock_data",
    "get_indicators": "technical_indicators",
}

_TOOL_ROUTES = {
    "get_rke_research_context": ("private.rke_report_intelligence",),
    "get_yield_curve_cn": ("tushare.shibor_yield_curve",),
    "get_industry_policy_digest": ("official.govcn_policy",),
    "get_stock_research": ("private.tushare_research_reports",),
    "get_fundamentals": ("tushare.sector_fundamentals",),
    "get_income_statement": ("tushare.sector_fundamentals",),
    "get_cashflow": ("tushare.sector_fundamentals",),
    "get_balance_sheet": ("tushare.sector_fundamentals",),
    "get_stock_data": ("tushare.sector_market",),
    "get_indicators": ("tushare.sector_market",),
}

_PRIVATE_TOOLS = {
    "get_rke_research_context": "private_redacted",
    "get_industry_policy_digest": "public_source_private_digest",
    "get_stock_research": "licensed_private",
}

_DIGEST_TOOLS = {"get_industry_policy_digest", "get_stock_research"}

_FORBIDDEN_PUBLIC_KEYS = {
    "abstract",
    "canonical_args",
    "claim_text",
    "licensed_text",
    "query_args",
    "query_text",
    "raw_prose",
    "report_text",
    "report_title",
    "source_span",
    "source_span_ids",
    "ticker_values",
}

_INITIAL_CALLS = {
    "ackman": [
        {"tool_id": "get_fundamentals", "ticker_source": "accepted_rank_1"},
        {
            "tool_id": "get_cashflow",
            "ticker_source": "accepted_rank_1",
            "frequency": "annual",
        },
    ],
    "munger": [
        {"tool_id": "get_fundamentals", "ticker_source": "accepted_rank_1"},
        {
            "tool_id": "get_cashflow",
            "ticker_source": "accepted_rank_1",
            "frequency": "annual",
        },
    ],
    "burry": [
        {"tool_id": "get_fundamentals", "ticker_source": "accepted_rank_1"},
        {
            "tool_id": "get_balance_sheet",
            "ticker_source": "accepted_rank_1",
            "frequency": "annual",
        },
    ],
    "druckenmiller": [],
}


def _object_schema(
    properties: dict[str, Any], *, required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


def _date_schema() -> dict[str, str]:
    return {"type": "string", "format": "date"}


def _ticker_schema() -> dict[str, str]:
    return {"type": "string", "pattern": r"^[0-9]{6}\.(SH|SZ|BJ)$"}


def argument_schema_for_binding(
    *, agent_id: str, stage: str, tool_id: str
) -> dict[str, Any]:
    date_schema = _date_schema()
    ticker_schema = _ticker_schema()
    if tool_id == "get_rke_research_context":
        layer = "superinvestor" if agent_id in L3_TOOL_ROSTER else "decision"
        properties: dict[str, Any] = {
            "agent_id": {"const": agent_id},
            "as_of": date_schema,
            "layer": {"const": layer},
        }
        if layer == "superinvestor":
            properties["ticker"] = ticker_schema
            properties["sector"] = {"type": "string"}
            properties["max_items"] = {
                "type": "integer",
                "minimum": 1,
                "maximum": 12,
                "default": 12,
            }
        else:
            properties["max_items"] = {"const": 3}
        return _object_schema(properties)
    if tool_id == "get_industry_policy_digest":
        return _object_schema(
            {
                "as_of": date_schema,
                "lookback_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "default": 7,
                },
                "source": {"const": "govcn"},
            }
        )
    if tool_id == "get_stock_research":
        return _object_schema(
            {
                "ticker": ticker_schema,
                "date_from": date_schema,
                "date_to": date_schema,
                "max_reports": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "default": 30,
                },
            }
        )
    if tool_id == "get_fundamentals":
        return _object_schema({"ticker": ticker_schema, "as_of": date_schema})
    if tool_id == "get_stock_data":
        return _object_schema(
            {"ticker": ticker_schema, "date_from": date_schema, "date_to": date_schema}
        )
    if tool_id == "get_indicators":
        return _object_schema(
            {
                "ticker": ticker_schema,
                "as_of": date_schema,
                "lookback": {"type": "integer", "minimum": 1, "maximum": 500},
                "indicator": {
                    "type": "string",
                    "enum": [
                        "atr",
                        "boll",
                        "boll_lb",
                        "boll_ub",
                        "close_10_ema",
                        "close_200_sma",
                        "close_50_sma",
                        "macd",
                        "macdh",
                        "macds",
                        "mfi",
                        "rsi",
                        "vwma",
                    ],
                },
            }
        )
    if tool_id == "get_yield_curve_cn":
        return _object_schema(
            {
                "as_of": date_schema,
                "lookback": {"type": "integer", "minimum": 1, "maximum": 365},
            }
        )
    if tool_id in {"get_income_statement", "get_balance_sheet", "get_cashflow"}:
        return _object_schema(
            {
                "ticker": ticker_schema,
                "frequency": {"type": "string", "enum": ["quarterly", "annual"]},
                "as_of": date_schema,
            }
        )
    raise ValueError(f"unknown L3/L4 restored tool: {tool_id} at {agent_id}/{stage}")


def _argument_semantics(tool_id: str) -> dict[str, Any]:
    aliases = {
        "get_rke_research_context": {"as_of_date": "as_of"},
        "get_industry_policy_digest": {
            "curr_date": "as_of",
            "look_back_days": "lookback_days",
            "src": "source",
        },
        "get_stock_research": {"start_date": "date_from", "end_date": "date_to"},
        "get_fundamentals": {"curr_date": "as_of"},
        "get_stock_data": {"symbol": "ticker", "start_date": "date_from", "end_date": "date_to"},
        "get_indicators": {
            "symbol": "ticker",
            "curr_date": "as_of",
            "look_back_days": "lookback",
        },
        "get_yield_curve_cn": {"curr_date": "as_of", "look_back_days": "lookback"},
        "get_income_statement": {"freq": "frequency", "curr_date": "as_of"},
        "get_balance_sheet": {"freq": "frequency", "curr_date": "as_of"},
        "get_cashflow": {"freq": "frequency", "curr_date": "as_of"},
    }.get(tool_id, {})
    semantics: dict[str, Any] = {
        "legacy_aliases": aliases,
        "unknown_arguments": "REJECT",
        "defaults_applied_during_prepare": True,
    }
    if tool_id in {"get_stock_research", "get_stock_data"}:
        semantics["date_interval"] = "inclusive"
    return semantics


def _domain_contract(
    *, agent_id: str, stage: str, tool_id: str, schema: Mapping[str, Any]
) -> dict[str, Any]:
    fields = list(schema["properties"])
    body: dict[str, Any] = {
        "scope_contract_version": "trusted_bound_runtime_query_scope_v1",
        "agent_id": agent_id,
        "stage": stage,
        "tool_id": tool_id,
        "authorized_scope_fields": fields,
        "exact_prepared_query_set": True,
        "as_of_ceiling": "bundle_as_of",
        "unknown_or_unmaterialized_arguments": "REJECT",
        "private_argument_values_in_public_projection": False,
        "candidate_scope_source": "trusted_prepare_scope.accepted_candidate_tickers",
        "candidate_expansion_allowed": False,
        "backup_candidate_source": "accepted_candidate_tickers",
    }
    if agent_id in L3_TOOL_ROSTER:
        body["runtime_authority_hashes"] = [
            "candidate_scope_hash",
            "candidate_universe_hash",
            "source_snapshot_hash",
        ]
    else:
        body["runtime_authority_hashes"] = [
            "accepted_output_set_hash",
            "account_positions_policy_hash",
            "market_liquidity_vintage_hash",
        ]
    if "ticker" in fields:
        body["ticker_source"] = "accepted_candidate_tickers"
    if "indicator" in fields:
        body["indicator_source"] = "trusted_prepare_scope.indicator_families"
    return body


def _binding_body(
    *,
    agent_id: str,
    stage: str,
    tool_id: str,
    routes_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    schema = argument_schema_for_binding(agent_id=agent_id, stage=stage, tool_id=tool_id)
    domain = _domain_contract(
        agent_id=agent_id, stage=stage, tool_id=tool_id, schema=schema
    )
    source_route_ids = sorted(_TOOL_ROUTES[tool_id])
    privacy_class = _PRIVATE_TOOLS.get(tool_id, "public_structured")
    if tool_id in _DIGEST_TOOLS:
        derivation_contract = {
            "contract_version": "frozen_research_digest_lineage_v1",
            "model_hash_required": True,
            "prompt_hash_required": True,
            "source_payload_hash_required": True,
        }
    else:
        derivation_contract = {"contract_version": "identity_projection_v1"}
    materializer_contract = {
        "contract_version": "trusted_bound_runtime_query_materializer_v1",
        "tool_id": tool_id,
        "prepare_transport_policy": "TRUSTED_ONLY",
        "call_transport": False,
        "payload_store": "gitignored_private_sqlite",
        "source_receipt_descriptor_binding": True,
        "no_implicit_fallback": True,
        "derivation_contract": derivation_contract,
    }
    privacy_contract = {
        "privacy_class": privacy_class,
        "source_prose_public": False,
        "argument_values_public": False,
        "public_projection": "hash_only",
    }
    l3 = agent_id in L3_TOOL_ROSTER
    evidence_usage = (
        {
            "candidate_expansion_allowed": False,
            "usage": "ANNOTATE_ONLY",
            "current_confirmation_required": True,
        }
        if tool_id in {"get_rke_research_context", "get_stock_research"}
        else {
            "candidate_expansion_allowed": False,
            "usage": "CURRENT_CONFIRMATION",
            "current_confirmation_required": False,
        }
    )
    if not l3:
        evidence_usage = {
            "candidate_expansion_allowed": False,
            "usage": "SHADOW_PRIOR",
            "current_confirmation_required": True,
        }
    output_contract = {
        "semantic_capability_id": _TOOL_CAPABILITY[tool_id],
        "projection": (
            "private_frozen_digest_ref_v1"
            if privacy_class != "public_structured"
            else "frozen_structured_result_v1"
        ),
        "source_prose_in_public_artifacts": False,
        "evidence_usage": evidence_usage,
    }
    adaptive = {
        "max_rounds": 3 if l3 else 0,
        "model_selects_arguments": l3,
        "transport_allowed_during_prepare": True,
        "transport_allowed_during_call": False,
    }
    return {
        "agent_id": agent_id,
        "stage": stage,
        "phase": "analysis",
        "semantic_capability_id": _TOOL_CAPABILITY[tool_id],
        "tool_id": tool_id,
        "disposition": "restored",
        "argument_schema": schema,
        "argument_schema_hash": canonical_hash(schema),
        "argument_semantics": _argument_semantics(tool_id),
        "authorized_domain_contract": domain,
        "argument_domain_selector_hash": canonical_hash(domain),
        "evidence_usage_contract": evidence_usage,
        "output_semantics_hash": canonical_hash(output_contract),
        "source_route_ids": source_route_ids,
        "route_contract_hash": canonical_hash(
            {"routes": [routes_by_id[route_id] for route_id in source_route_ids]}
        ),
        "materializer_contract": materializer_contract,
        "materializer_contract_hash": canonical_hash(materializer_contract),
        "query_bundle_contract_version": QUERY_BUNDLE_CONTRACT_VERSION,
        "privacy_class": privacy_class,
        "privacy_contract": privacy_contract,
        "privacy_contract_hash": canonical_hash(privacy_contract),
        "adaptive_query_contract": adaptive,
        "activation_state": "staged",
        "no_evidence_policy": "RETURN_TRUE_EMPTY",
    }


def _fixture(binding: Mapping[str, Any]) -> dict[str, Any]:
    binding_id = str(binding["binding_id"])
    fingerprint = canonical_hash(
        {"binding_id": binding_id, "canonical_args_hash": canonical_hash({"synthetic": "opaque"})}
    )
    lineage = {
        "tool_result_fingerprint": fingerprint,
        "typed_edge_hash": canonical_hash({"fingerprint": fingerprint, "edge_type": "supports"}),
        "accepted_claim_graph_hash": canonical_hash({"binding_id": binding_id, "fingerprint": fingerprint}),
        "counterevidence_rule_hash": canonical_hash({"rule": "support_minus_contradiction"}),
        "resolution_code": "qualified",
    }
    body = {
        "schema_version": SIGNIFICANCE_CONTRACT_VERSION,
        "binding_id": binding_id,
        "fixture_id": "fixture:" + canonical_hash({"binding_id": binding_id})[7:],
        "evaluator_contract_version": KNOT_EVALUATOR_CONTRACT_VERSION,
        "paired_sample_count": 32,
        "minimum_paired_sample_count": 30,
        "minimum_effect": 0.05,
        "confidence_interval_lower_bound": 0.05,
        "ready_used_handled": {"accepted_utility": 1.0},
        "not_called": {"accepted_utility": 0.35},
        "call_failed": {"accepted_utility": 0.30},
        "succeeded_not_used": {"accepted_utility": 0.40},
        "counterevidence_handled": {"accepted_utility": 0.80},
        "counterevidence_ignored": {"accepted_utility": 0.20},
        "lineage_fixture": lineage,
    }
    return {**body, "fixture_hash": canonical_hash(body)}


def _coverage(binding: Mapping[str, Any], fixture: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "binding_id": binding["binding_id"],
        "agent_id": binding["agent_id"],
        "stage": binding["stage"],
        "semantic_capability_id": binding["semantic_capability_id"],
        "tool_id": binding["tool_id"],
        "activation_state": "staged",
        "availability_evaluated": True,
        "called_evaluated": True,
        "succeeded_evaluated": True,
        "used_in_accepted_evidence_evaluated": True,
        "counterevidence_handled_evaluated": True,
        "lineage_evaluator_contract_version": KNOT_EVALUATOR_CONTRACT_VERSION,
        "significance_fixture_id": fixture["fixture_id"],
        "significance_fixture_hash": fixture["fixture_hash"],
        "candidate_generation_allowed": False,
    }
    return {**body, "coverage_hash": canonical_hash(body)}


def _binding_rows() -> list[tuple[str, str, str]]:
    rows = [
        (agent_id, agent_id, tool_id)
        for agent_id, tools in L3_TOOL_ROSTER.items()
        for tool_id in tools
    ]
    rows.extend(
        (agent_id, stage, "get_rke_research_context")
        for agent_id, stage in L4_STAGE_ROSTER
    )
    return rows


def _runtime_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    l3 = {
        "candidate_authority": "get_superinvestor_candidate_snapshot",
        "candidate_scope_policy": "ACCEPTED_SCOPE_ONLY_NO_EXPANSION",
        "backup_candidate_policy": "ACCEPTED_SCOPE_ONLY",
        "report_rke_usage": "ANNOTATE_ONLY_CURRENT_CONFIRMATION_REQUIRED",
        "deterministic_initial_calls": _INITIAL_CALLS,
        "adaptive_follow_up_rounds": 3,
    }
    l4 = {
        "injection_mode": "PROACTIVE_STAGE_BOUND_FROZEN_PRIOR",
        "layer": "decision",
        "max_items": 3,
        "shadow_only": True,
        "current_data_confirmation_required": True,
        "candidate_expansion_allowed": False,
        "transport_allowed_during_agent_run": False,
    }
    return l3, l4


def _walk_forbidden(value: Any, path: str = "$.") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"private prose field {path}{key} is forbidden")
            _walk_forbidden(item, f"{path}{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, f"{path}{index}.")


def build_l3_l4_preservation_overlay(root: Path) -> dict[str, Any]:
    active = json.loads(
        (root / "registry/prompt_checks/agent_tool_contract_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    route_manifest = json.loads(
        (root / "registry/data_sources/agent_data_route_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    parent_overlay = build_sector_relationship_preservation_overlay(root)
    required_routes = {route_id for values in _TOOL_ROUTES.values() for route_id in values}
    routes = [row for row in parent_overlay["routes"] if row["route_id"] in required_routes]
    routes.sort(key=lambda row: row["route_id"])
    routes_by_id = {row["route_id"]: row for row in routes}
    if set(routes_by_id) != required_routes:
        raise ValueError("PR7 parent overlay is missing a required source route")

    bindings = []
    for agent_id, stage, tool_id in _binding_rows():
        body = _binding_body(
            agent_id=agent_id,
            stage=stage,
            tool_id=tool_id,
            routes_by_id=routes_by_id,
        )
        bindings.append({"binding_id": "binding:" + canonical_hash(body)[7:], **body})
    bindings.sort(key=lambda row: row["binding_id"])
    fixtures = [_fixture(binding) for binding in bindings]
    fixtures.sort(key=lambda row: row["binding_id"])
    fixture_by_binding = {row["binding_id"]: row for row in fixtures}
    coverage = [
        _coverage(binding, fixture_by_binding[binding["binding_id"]])
        for binding in bindings
    ]
    coverage.sort(key=lambda row: row["binding_id"])
    l3_runtime, l4_runtime = _runtime_contracts()
    body = {
        "schema_version": SCHEMA_VERSION,
        "activation_state": "staged",
        "activation_gate": ACTIVATION_GATE,
        "base_active_agent_tool_manifest_hash": canonical_hash(active),
        "base_agent_data_route_manifest_hash": canonical_hash(route_manifest),
        "base_sector_relationship_overlay_hash": parent_overlay["manifest_hash"],
        "query_bundle_contract_version": QUERY_BUNDLE_CONTRACT_VERSION,
        "l3_runtime_contract": l3_runtime,
        "l4_rke_runtime_contract": l4_runtime,
        "routes": routes,
        "bindings": bindings,
        "knot_coverage": coverage,
        "significance_fixtures": fixtures,
    }
    overlay = {**body, "manifest_hash": canonical_hash(body)}
    validate_l3_l4_preservation_overlay(overlay, root=root)
    return overlay


def evaluate_l3_l4_significance_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    return evaluate_sector_relationship_significance_fixture(fixture)


def validate_l3_l4_preservation_overlay(
    overlay: Mapping[str, Any], *, root: Path
) -> None:
    _walk_forbidden(overlay)
    expected_top_fields = {
        "schema_version",
        "activation_state",
        "activation_gate",
        "base_active_agent_tool_manifest_hash",
        "base_agent_data_route_manifest_hash",
        "base_sector_relationship_overlay_hash",
        "query_bundle_contract_version",
        "l3_runtime_contract",
        "l4_rke_runtime_contract",
        "routes",
        "bindings",
        "knot_coverage",
        "significance_fixtures",
        "manifest_hash",
    }
    if set(overlay) != expected_top_fields:
        raise ValueError("L3/L4 overlay top-level fields drift")
    if overlay.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("L3/L4 overlay schema version mismatch")
    if overlay.get("activation_state") != "staged":
        raise ValueError("L3/L4 overlay must remain staged")
    if overlay.get("activation_gate") != ACTIVATION_GATE:
        raise ValueError("L3/L4 activation gate mismatch")
    body = {key: value for key, value in overlay.items() if key != "manifest_hash"}
    if overlay.get("manifest_hash") != canonical_hash(body):
        raise ValueError("L3/L4 overlay manifest hash mismatch")

    active = json.loads(
        (root / "registry/prompt_checks/agent_tool_contract_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    route_manifest = json.loads(
        (root / "registry/data_sources/agent_data_route_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    parent_overlay = build_sector_relationship_preservation_overlay(root)
    if overlay.get("base_active_agent_tool_manifest_hash") != canonical_hash(active):
        raise ValueError("base active Agent tool manifest drift")
    if overlay.get("base_agent_data_route_manifest_hash") != canonical_hash(route_manifest):
        raise ValueError("base Agent data route manifest drift")
    if overlay.get("base_sector_relationship_overlay_hash") != parent_overlay["manifest_hash"]:
        raise ValueError("base Sector/Relationship overlay drift")
    if overlay.get("query_bundle_contract_version") != QUERY_BUNDLE_CONTRACT_VERSION:
        raise ValueError("L3/L4 query bundle contract version mismatch")
    expected_l3, expected_l4 = _runtime_contracts()
    if overlay.get("l3_runtime_contract") != expected_l3:
        raise ValueError("L3 runtime contract drift")
    if overlay.get("l4_rke_runtime_contract") != expected_l4:
        raise ValueError("L4 RKE runtime contract drift")

    routes = overlay.get("routes")
    bindings = overlay.get("bindings")
    coverage = overlay.get("knot_coverage")
    fixtures = overlay.get("significance_fixtures")
    if not all(isinstance(value, list) for value in (routes, bindings, coverage, fixtures)):
        raise ValueError("L3/L4 overlay collections are malformed")
    required_routes = {route_id for values in _TOOL_ROUTES.values() for route_id in values}
    expected_routes = [
        row for row in parent_overlay["routes"] if row["route_id"] in required_routes
    ]
    expected_routes.sort(key=lambda row: row["route_id"])
    if routes != expected_routes:
        raise ValueError("L3/L4 route catalog drift")
    routes_by_id = {row["route_id"]: row for row in routes}

    if len(bindings) != 33:
        raise ValueError("L3/L4 overlay must contain 33 bindings")
    actual_roster = [
        (row.get("agent_id"), row.get("stage"), row.get("tool_id")) for row in bindings
    ]
    if len(actual_roster) != len(set(actual_roster)) or set(actual_roster) != set(
        _binding_rows()
    ):
        raise ValueError("L3/L4 binding roster drift")
    active_tools = {
        tool_id for agent in active["agents"] for tool_id in agent["allowed_tools"]
    }
    binding_ids = []
    for row in bindings:
        binding_ids.append(row.get("binding_id"))
        if row.get("activation_state") != "staged" or row.get("tool_id") in active_tools:
            raise ValueError("L3/L4 restored binding must remain staged outside active surface")
        domain = row.get("authorized_domain_contract")
        if not isinstance(domain, Mapping) or domain.get("candidate_expansion_allowed") is not False:
            raise ValueError("L3/L4 candidate scope expansion must remain forbidden")
        if domain.get("backup_candidate_source") != "accepted_candidate_tickers":
            raise ValueError("L3/L4 backup candidate scope must remain accepted-only")
        schema = row.get("argument_schema")
        Draft202012Validator.check_schema(schema)
        if row.get("argument_schema_hash") != canonical_hash(schema):
            raise ValueError("L3/L4 argument schema hash mismatch")
        if row.get("argument_domain_selector_hash") != canonical_hash(domain):
            raise ValueError("L3/L4 argument domain hash mismatch")
        materializer = row.get("materializer_contract")
        if row.get("materializer_contract_hash") != canonical_hash(materializer):
            raise ValueError("L3/L4 materializer contract hash mismatch")
        privacy = row.get("privacy_contract")
        if row.get("privacy_contract_hash") != canonical_hash(privacy):
            raise ValueError("L3/L4 privacy contract hash mismatch")
        expected_body = _binding_body(
            agent_id=row["agent_id"],
            stage=row["stage"],
            tool_id=row["tool_id"],
            routes_by_id=routes_by_id,
        )
        row_body = {key: value for key, value in row.items() if key != "binding_id"}
        if row_body != expected_body:
            raise ValueError("L3/L4 binding contract drift")
        if row.get("binding_id") != "binding:" + canonical_hash(row_body)[7:]:
            raise ValueError("L3/L4 binding id hash mismatch")

    if len(binding_ids) != len(set(binding_ids)):
        raise ValueError("L3/L4 binding ids must be unique")
    binding_id_set = set(binding_ids)
    coverage_ids = [row.get("binding_id") for row in coverage]
    fixture_ids = [row.get("binding_id") for row in fixtures]
    if len(coverage_ids) != len(set(coverage_ids)) or set(coverage_ids) != binding_id_set:
        raise ValueError("KNOT coverage exact closure mismatch")
    if len(fixture_ids) != len(set(fixture_ids)) or set(fixture_ids) != binding_id_set:
        raise ValueError("significance fixture exact closure mismatch")
    bindings_by_id = {row["binding_id"]: row for row in bindings}
    fixtures_by_id = {row["binding_id"]: row for row in fixtures}
    for row in coverage:
        binding = bindings_by_id[row["binding_id"]]
        fixture = fixtures_by_id[row["binding_id"]]
        for field in ("agent_id", "stage", "semantic_capability_id", "tool_id"):
            if row.get(field) != binding.get(field):
                raise ValueError("KNOT coverage binding metadata drift")
        if row.get("candidate_generation_allowed") is not False:
            raise ValueError("PR7 must not enable Candidate generation")
        if row.get("significance_fixture_hash") != fixture.get("fixture_hash"):
            raise ValueError("KNOT significance fixture drift")
        if row.get("significance_fixture_id") != fixture.get("fixture_id"):
            raise ValueError("KNOT significance fixture id drift")
        if row != _coverage(binding, fixture):
            raise ValueError("KNOT coverage contract drift")
    for row in fixtures:
        if row != _fixture(bindings_by_id[row["binding_id"]]):
            raise ValueError("significance fixture contract drift")
    failed = [
        row["binding_id"]
        for row in fixtures
        if not evaluate_l3_l4_significance_fixture(row)["passed"]
    ]
    if failed:
        raise ValueError(f"significance fixtures failed: {failed[:3]}")


def write_l3_l4_preservation_overlay(root: Path) -> Path:
    path = (
        root
        / "registry/prompt_checks/capability_preservation/"
        "l3_l4_preservation_overlay_v1.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            build_l3_l4_preservation_overlay(root),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return path


__all__ = [
    "L3_TOOL_ROSTER",
    "L4_STAGE_ROSTER",
    "QUERY_BUNDLE_CONTRACT_VERSION",
    "argument_schema_for_binding",
    "build_l3_l4_preservation_overlay",
    "evaluate_l3_l4_significance_fixture",
    "validate_l3_l4_preservation_overlay",
    "write_l3_l4_preservation_overlay",
]

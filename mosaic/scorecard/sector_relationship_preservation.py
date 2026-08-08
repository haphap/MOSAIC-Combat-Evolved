"""Staged Sector/Relationship capability-preservation overlay.

The overlay is deliberately not an active Agent tool manifest.  It freezes the
restored argument domains, source routes, private materialization boundary and
per-binding KNOT evaluation contract that PR12 may activate atomically later.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.capability_preservation import evaluate_counterevidence


SCHEMA_VERSION = "sector_relationship_preservation_overlay_v1"
ACTIVATION_GATE = "PR12_L1_L2_ATOMIC_ACTIVATION"
QUERY_BUNDLE_CONTRACT_VERSION = "frozen_adaptive_query_bundle_v1"
KNOT_EVALUATOR_CONTRACT_VERSION = "knot_binding_lineage_evaluator_v1"
SIGNIFICANCE_CONTRACT_VERSION = "paired_binding_significance_fixture_v1"

LEGACY_SECTOR_AGENT_IDS = (
    "semiconductor",
    "energy",
    "biotech",
    "consumer",
    "industrials",
    "financials",
)
NEW_SECTOR_AGENT_IDS = (
    "technology",
    "real_estate_construction",
    "agriculture",
)
SECTOR_AGENT_IDS = (*LEGACY_SECTOR_AGENT_IDS, *NEW_SECTOR_AGENT_IDS)
SECTOR_COMMON_TOOL_IDS = (
    "get_rke_research_context",
    "get_industry_policy_digest",
    "get_broker_research",
    "get_etf_holdings",
    "get_stock_data",
    "get_indicators",
    "get_industry_moneyflow",
)

_TOOL_CAPABILITY = {
    "get_rke_research_context": "rke_research_context",
    "get_industry_policy_digest": "industry_policy_digest",
    "get_broker_research": "broker_research",
    "get_etf_holdings": "etf_holdings",
    "get_stock_data": "stock_data",
    "get_indicators": "technical_indicators",
    "get_industry_moneyflow": "industry_moneyflow",
    "get_yield_curve_cn": "china_yield_curve",
    "get_income_statement": "income_statement",
    "get_balance_sheet": "balance_sheet",
    "get_cashflow": "cashflow_statement",
    "get_stock_research": "stock_research",
    "get_supply_chain_evidence": "relationship_supply_chain_evidence",
}

_TOOL_ROUTES = {
    "get_rke_research_context": ("private.rke_report_intelligence",),
    "get_industry_policy_digest": ("official.govcn_policy",),
    "get_broker_research": ("private.tushare_research_reports",),
    "get_etf_holdings": ("tushare.etf_holdings",),
    "get_stock_data": ("tushare.sector_market",),
    "get_indicators": ("tushare.sector_market",),
    "get_industry_moneyflow": ("tushare.sector_market",),
    "get_yield_curve_cn": ("tushare.shibor_yield_curve",),
    "get_income_statement": ("tushare.sector_fundamentals",),
    "get_balance_sheet": ("tushare.sector_fundamentals",),
    "get_cashflow": ("tushare.sector_fundamentals",),
    "get_stock_research": ("private.tushare_research_reports",),
    "get_supply_chain_evidence": ("official.company_supply_chain_disclosures",),
}

_PRIVATE_TOOLS = {
    "get_rke_research_context": "private_redacted",
    "get_industry_policy_digest": "public_source_private_digest",
    "get_broker_research": "licensed_private",
    "get_stock_research": "licensed_private",
}

_DIGEST_TOOLS = {
    "get_broker_research",
    "get_industry_policy_digest",
    "get_stock_research",
}

_ADDITIONAL_ROUTES: tuple[dict[str, str], ...] = (
    {
        "route_id": "official.company_supply_chain_disclosures",
        "source_family": "official_company_disclosures",
        "contract_version": "company_supply_chain_disclosures_v1",
        "pit_strategy": "AUTHORITATIVE_VINTAGE_REPLAY",
        "implementation_stage": "PR6",
    },
    {
        "route_id": "official.govcn_policy",
        "source_family": "govcn",
        "contract_version": "govcn_policy_forward_archive_v1",
        "pit_strategy": "FORWARD_ARCHIVE",
        "implementation_stage": "PR6",
    },
    {
        "route_id": "private.rke_report_intelligence",
        "source_family": "local_private_rke",
        "contract_version": "rke_agent_research_context_pit_v1",
        "pit_strategy": "DERIVED_FROM_PIT_ARCHIVE",
        "implementation_stage": "PR6",
    },
    {
        "route_id": "private.tushare_research_reports",
        "source_family": "tushare",
        "contract_version": "private_research_report_forward_archive_v1",
        "pit_strategy": "FORWARD_ARCHIVE",
        "implementation_stage": "PR6",
    },
    {
        "route_id": "tushare.etf_holdings",
        "source_family": "tushare",
        "contract_version": "tushare_etf_holdings_disclosure_v1",
        "pit_strategy": "AUTHORITATIVE_VINTAGE_REPLAY",
        "implementation_stage": "PR6",
    },
)

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


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _date_schema() -> dict[str, str]:
    return {"type": "string", "format": "date"}


def _ticker_schema() -> dict[str, str]:
    return {"type": "string", "pattern": r"^[0-9]{6}\.(SH|SZ|BJ)$"}


def argument_schema_for_tool(tool_id: str) -> dict[str, Any]:
    date_schema = _date_schema()
    ticker_schema = _ticker_schema()
    if tool_id == "get_rke_research_context":
        return _object_schema(
            {
                "agent_id": {"type": "string", "minLength": 1},
                "as_of": date_schema,
                "layer": {"type": "string", "enum": ["sector", "relationship"]},
                "ticker": {"type": "string"},
                "sector": {"type": "string"},
                "max_items": {"type": "integer", "minimum": 1, "default": 12},
            }
        )
    if tool_id == "get_industry_policy_digest":
        return _object_schema(
            {
                "as_of": date_schema,
                "lookback_days": {"type": "integer", "minimum": 1, "default": 7},
                "source": {"type": "string", "enum": ["govcn"], "default": "govcn"},
            }
        )
    if tool_id in {"get_broker_research", "get_stock_research"}:
        return _object_schema(
            {
                "ticker": ticker_schema,
                "date_from": date_schema,
                "date_to": date_schema,
                "max_reports": {"type": "integer", "minimum": 1, "default": 30},
            }
        )
    if tool_id == "get_etf_holdings":
        return _object_schema(
            {
                "etf": ticker_schema,
                "as_of": date_schema,
                "top_n": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 12,
                    "default": 8,
                },
            }
        )
    if tool_id == "get_stock_data":
        return _object_schema(
            {
                "ticker": ticker_schema,
                "date_from": date_schema,
                "date_to": date_schema,
            }
        )
    if tool_id == "get_indicators":
        return _object_schema(
            {
                "ticker": ticker_schema,
                "as_of": date_schema,
                "lookback": {"type": "integer", "minimum": 1},
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
    if tool_id == "get_industry_moneyflow":
        return _object_schema(
            {
                "as_of": date_schema,
                "lookback": {"type": "integer", "minimum": 1, "default": 5},
                "industry_filters": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "uniqueItems": True,
                },
            }
        )
    if tool_id == "get_yield_curve_cn":
        return _object_schema(
            {
                "as_of": date_schema,
                "lookback": {"type": "integer", "minimum": 1, "default": 30},
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
    if tool_id == "get_supply_chain_evidence":
        return _object_schema({"ticker": ticker_schema, "as_of": date_schema})
    raise ValueError(f"unknown Sector/Relationship restored tool: {tool_id}")


def _argument_semantics(tool_id: str) -> dict[str, Any]:
    semantics: dict[str, Any] = {
        "canonical_names": list(argument_schema_for_tool(tool_id)["properties"]),
        "unknown_arguments": "REJECT",
        "defaults_applied_during_prepare": True,
    }
    if tool_id in {"get_broker_research", "get_stock_research", "get_stock_data"}:
        semantics["date_interval"] = "inclusive"
    aliases = {
        "get_industry_policy_digest": {
            "curr_date": "as_of",
            "look_back_days": "lookback_days",
            "src": "source",
        },
        "get_etf_holdings": {"ticker": "etf", "curr_date": "as_of"},
        "get_industry_moneyflow": {
            "curr_date": "as_of",
            "look_back_days": "lookback",
            "industries": "industry_filters",
        },
        "get_yield_curve_cn": {"curr_date": "as_of", "look_back_days": "lookback"},
        "get_income_statement": {"freq": "frequency", "curr_date": "as_of"},
        "get_balance_sheet": {"freq": "frequency", "curr_date": "as_of"},
        "get_cashflow": {"freq": "frequency", "curr_date": "as_of"},
        "get_indicators": {
            "symbol": "ticker",
            "curr_date": "as_of",
            "look_back_days": "lookback",
            "indicators": "indicator",
        },
        "get_broker_research": {"start_date": "date_from", "end_date": "date_to"},
        "get_stock_research": {"start_date": "date_from", "end_date": "date_to"},
    }.get(tool_id, {})
    semantics["legacy_aliases"] = aliases
    return semantics


def _domain_contract(agent_id: str, stage: str, tool_id: str) -> dict[str, Any]:
    fields = list(argument_schema_for_tool(tool_id)["properties"])
    body: dict[str, Any] = {
        "scope_contract_version": "trusted_prepare_query_scope_v1",
        "agent_id": agent_id,
        "stage": stage,
        "tool_id": tool_id,
        "authorized_scope_fields": fields,
        "exact_prepared_query_set": True,
        "as_of_ceiling": "bundle_as_of",
        "unknown_or_unmaterialized_arguments": "REJECT",
        "private_argument_values_in_public_projection": False,
    }
    if "ticker" in fields:
        body["ticker_source"] = "trusted_prepare_scope.tickers"
    if "etf" in fields:
        body["etf_source"] = "trusted_prepare_scope.etfs"
    if "industry_filters" in fields:
        body["industry_filter_source"] = "trusted_prepare_scope.sectors"
        body["unmatched_filter_policy"] = "REJECT"
    if "indicator" in fields:
        body["indicator_source"] = "trusted_prepare_scope.indicator_families"
    if "max_reports" in fields:
        body["max_reports_source"] = "trusted_prepare_query_set"
    return body


def _binding_body(
    *, agent_id: str, stage: str, tool_id: str, routes_by_id: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    argument_schema = argument_schema_for_tool(tool_id)
    domain = _domain_contract(agent_id, stage, tool_id)
    source_route_ids = list(_TOOL_ROUTES[tool_id])
    privacy_class = _PRIVATE_TOOLS.get(tool_id, "public_structured")
    semantic_capability_id = _TOOL_CAPABILITY[tool_id]
    disposition = "introduced" if tool_id == "get_supply_chain_evidence" else "restored"
    output_contract = {
        "semantic_capability_id": semantic_capability_id,
        "projection": (
            "private_frozen_digest_ref_v1"
            if privacy_class != "public_structured"
            else "frozen_structured_result_v1"
        ),
        "source_prose_in_public_artifacts": False,
    }
    if tool_id in _DIGEST_TOOLS:
        derivation_contract = {
            "contract_version": "frozen_research_digest_lineage_v1",
            "model_hash_required": True,
            "prompt_hash_required": True,
            "source_payload_hash_required": True,
        }
    elif tool_id == "get_etf_holdings":
        derivation_contract = {
            "contract_version": "etf_holdings_compaction_v1",
            "strict_top_n_range": [1, 12],
        }
    elif tool_id == "get_supply_chain_evidence":
        derivation_contract = {
            "contract_version": "official_supply_chain_evidence_v1",
            "authoritative_document_hash_required": True,
            "holder_graph_fallback_allowed": False,
            "capture_revision_policy": "FIRST_COMPLETE_CAPTURE_WINS",
            "same_key_retry_policy": "REUSE_WITHOUT_TRANSPORT",
        }
    else:
        derivation_contract = {"contract_version": "identity_projection_v1"}
    materializer_contract = {
        "contract_version": "trusted_frozen_query_materializer_v1",
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
    return {
        "agent_id": agent_id,
        "stage": stage,
        "phase": "analysis",
        "semantic_capability_id": semantic_capability_id,
        "tool_id": tool_id,
        "disposition": disposition,
        "argument_schema": argument_schema,
        "argument_schema_hash": canonical_hash(argument_schema),
        "argument_semantics": _argument_semantics(tool_id),
        "authorized_domain_contract": domain,
        "argument_domain_selector_hash": canonical_hash(domain),
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
        "adaptive_query_contract": {
            "max_rounds": 3,
            "model_selects_arguments": True,
            "transport_allowed_during_prepare": True,
            "transport_allowed_during_call": False,
        },
        "activation_state": "staged",
        "no_evidence_policy": (
            "ABSTAIN_NO_FACTUAL_EDGE"
            if tool_id == "get_supply_chain_evidence"
            else "RETURN_TRUE_EMPTY"
        ),
    }


def _fixture(binding: Mapping[str, Any]) -> dict[str, Any]:
    binding_id = str(binding["binding_id"])
    fingerprint = canonical_hash(
        {
            "binding_id": binding_id,
            "canonical_args_hash": canonical_hash({"synthetic": "opaque"}),
            "payload_hash": canonical_hash({"payload": "synthetic"}),
        }
    )
    rule = {
        "rule_version": "counterevidence_rule_v1",
        "dimension": "binding_evidence_strength",
        "polarity_extractor_version": "signed_numeric_v1",
        "aggregation": "max_strength_v1",
        "comparison": "support_minus_contradiction",
        "threshold": 0.1,
        "unknown_policy": "abstain",
    }
    lineage = {
        "tool_result_fingerprint": fingerprint,
        "typed_edge_hash": canonical_hash(
            {"fingerprint": fingerprint, "edge_type": "supports", "polarity": 1}
        ),
        "accepted_claim_graph_hash": canonical_hash(
            {"binding_id": binding_id, "fingerprint": fingerprint}
        ),
        "counterevidence_rule_hash": canonical_hash(rule),
        "resolution_code": evaluate_counterevidence(rule, 0.55, 0.50),
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


def _route_catalog(root: Path) -> list[dict[str, Any]]:
    route_manifest = json.loads(
        (root / "registry/data_sources/agent_data_route_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    required_existing = {
        route_id
        for route_ids in _TOOL_ROUTES.values()
        for route_id in route_ids
        if not route_id.startswith(("private.", "official.company", "official.govcn"))
        and route_id != "tushare.etf_holdings"
    }
    existing = {
        row["route_id"]: row
        for row in route_manifest["routes"]
        if row["route_id"] in required_existing
    }
    if set(existing) != required_existing:
        raise ValueError("base route manifest is missing a PR6 parent route")
    rows = [*existing.values(), *[dict(row) for row in _ADDITIONAL_ROUTES]]
    return sorted(rows, key=lambda row: row["route_id"])


def _binding_tool_rows() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for agent_id in SECTOR_AGENT_IDS:
        rows.extend((agent_id, tool_id) for tool_id in SECTOR_COMMON_TOOL_IDS)
    rows.extend(
        ("semiconductor", tool_id)
        for tool_id in ("get_income_statement", "get_balance_sheet", "get_cashflow")
    )
    rows.append(("financials", "get_yield_curve_cn"))
    rows.extend(
        ("relationship_mapper", tool_id)
        for tool_id in (
            "get_rke_research_context",
            "get_stock_research",
            "get_supply_chain_evidence",
        )
    )
    return rows


def build_sector_relationship_preservation_overlay(root: Path) -> dict[str, Any]:
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
    routes = _route_catalog(root)
    routes_by_id = {row["route_id"]: row for row in routes}

    bindings: list[dict[str, Any]] = []
    for agent_id, tool_id in _binding_tool_rows():
        body = _binding_body(
            agent_id=agent_id,
            stage=agent_id,
            tool_id=tool_id,
            routes_by_id=routes_by_id,
        )
        bindings.append(
            {"binding_id": "binding:" + canonical_hash(body)[7:], **body}
        )
    bindings.sort(key=lambda row: row["binding_id"])
    fixtures = [_fixture(binding) for binding in bindings]
    fixture_by_binding = {row["binding_id"]: row for row in fixtures}
    coverage = [
        _coverage(binding, fixture_by_binding[binding["binding_id"]])
        for binding in bindings
    ]
    fixtures.sort(key=lambda row: row["binding_id"])
    coverage.sort(key=lambda row: row["binding_id"])

    body = {
        "schema_version": SCHEMA_VERSION,
        "activation_state": "staged",
        "activation_gate": ACTIVATION_GATE,
        "base_active_agent_tool_manifest_hash": canonical_hash(active),
        "base_agent_data_route_manifest_hash": canonical_hash(route_manifest),
        "query_bundle_contract_version": QUERY_BUNDLE_CONTRACT_VERSION,
        "sector_adaptive_max_rounds": 3,
        "routes": routes,
        "bindings": bindings,
        "knot_coverage": coverage,
        "significance_fixtures": fixtures,
    }
    overlay = {**body, "manifest_hash": canonical_hash(body)}
    validate_sector_relationship_preservation_overlay(overlay, root=root)
    return overlay


def _walk_forbidden(value: Any, path: str = "$.") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"private prose field {path}{key} is forbidden")
            _walk_forbidden(item, f"{path}{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, f"{path}{index}.")


def evaluate_sector_relationship_significance_fixture(
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        if fixture.get("schema_version") != SIGNIFICANCE_CONTRACT_VERSION:
            raise ValueError("significance fixture version mismatch")
        body = {key: value for key, value in fixture.items() if key != "fixture_hash"}
        if fixture.get("fixture_hash") != canonical_hash(body):
            raise ValueError("significance fixture hash mismatch")
        if fixture.get("paired_sample_count", 0) < fixture.get(
            "minimum_paired_sample_count", 1
        ):
            raise ValueError("paired sample count is below the fixture minimum")
        minimum_effect = fixture.get("minimum_effect")
        lower_bound = fixture.get("confidence_interval_lower_bound")
        if not isinstance(minimum_effect, (int, float)) or isinstance(minimum_effect, bool):
            raise ValueError("minimum effect is invalid")
        if not isinstance(lower_bound, (int, float)) or isinstance(lower_bound, bool):
            raise ValueError("confidence interval is invalid")
        if not math.isfinite(float(minimum_effect)) or not math.isfinite(float(lower_bound)):
            raise ValueError("significance values must be finite")
        if float(lower_bound) <= 0:
            raise ValueError("paired confidence interval does not exclude zero")
        ready = float(fixture["ready_used_handled"]["accepted_utility"])
        for name in ("not_called", "call_failed", "succeeded_not_used"):
            if ready - float(fixture[name]["accepted_utility"]) < float(minimum_effect):
                raise ValueError(f"{name} counterfactual has no minimum paired effect")
        handled = float(fixture["counterevidence_handled"]["accepted_utility"])
        ignored = float(fixture["counterevidence_ignored"]["accepted_utility"])
        if handled - ignored < float(minimum_effect):
            raise ValueError("counterevidence handling has no minimum paired effect")
        lineage = fixture["lineage_fixture"]
        if lineage.get("resolution_code") not in {
            "qualified",
            "rebutted_with_evidence",
            "reversed",
            "abstained",
        }:
            raise ValueError("lineage resolution code is invalid")
        for key in (
            "tool_result_fingerprint",
            "typed_edge_hash",
            "accepted_claim_graph_hash",
            "counterevidence_rule_hash",
        ):
            value = lineage.get(key)
            if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
                raise ValueError("lineage fixture hash is invalid")
    except (KeyError, TypeError, ValueError) as exc:
        return {"passed": False, "reason": str(exc)}
    return {"passed": True, "reason": None}


def validate_sector_relationship_preservation_overlay(
    overlay: Mapping[str, Any], *, root: Path
) -> None:
    _walk_forbidden(overlay)
    if overlay.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Sector/Relationship overlay version mismatch")
    if overlay.get("activation_state") != "staged":
        raise ValueError("Sector/Relationship overlay must remain staged")
    if overlay.get("activation_gate") != ACTIVATION_GATE:
        raise ValueError("Sector/Relationship activation gate mismatch")
    if overlay.get("sector_adaptive_max_rounds") != 3:
        raise ValueError("Sector adaptive max_rounds must equal 3")
    body = {key: value for key, value in overlay.items() if key != "manifest_hash"}
    if overlay.get("manifest_hash") != canonical_hash(body):
        raise ValueError("Sector/Relationship overlay manifest hash mismatch")

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
    if overlay.get("base_active_agent_tool_manifest_hash") != canonical_hash(active):
        raise ValueError("base active Agent tool manifest drift")
    if overlay.get("base_agent_data_route_manifest_hash") != canonical_hash(route_manifest):
        raise ValueError("base Agent data route manifest drift")

    routes = overlay.get("routes")
    bindings = overlay.get("bindings")
    coverage = overlay.get("knot_coverage")
    fixtures = overlay.get("significance_fixtures")
    if not all(isinstance(value, list) for value in (routes, bindings, coverage, fixtures)):
        raise ValueError("Sector/Relationship overlay collections are malformed")
    if routes != _route_catalog(root):
        raise ValueError("Sector/Relationship route catalog drift")
    routes_by_id = {row["route_id"]: row for row in routes}
    if len(routes_by_id) != len(routes):
        raise ValueError("Sector/Relationship route ids must be unique")
    if len(bindings) != 70:
        raise ValueError("Sector/Relationship overlay must contain 70 bindings")
    actual_roster = [(row.get("agent_id"), row.get("tool_id")) for row in bindings]
    expected_roster = _binding_tool_rows()
    if len(actual_roster) != len(set(actual_roster)) or set(actual_roster) != set(
        expected_roster
    ):
        raise ValueError("Sector/Relationship binding roster drift")

    active_tools = {
        tool_id
        for agent in active["agents"]
        for tool_id in agent["allowed_tools"]
    }
    binding_ids: list[str] = []
    for row in bindings:
        binding_id = row.get("binding_id")
        binding_ids.append(binding_id)
        if row.get("activation_state") != "staged" or row.get("tool_id") in active_tools:
            raise ValueError("restored binding must remain staged outside active surface")
        if row.get("stage") != row.get("agent_id"):
            raise ValueError("restored binding must use the current execution stage id")
        schema = row.get("argument_schema")
        Draft202012Validator.check_schema(schema)
        if row.get("argument_schema_hash") != canonical_hash(schema):
            raise ValueError("restored binding argument schema hash mismatch")
        domain = row.get("authorized_domain_contract")
        if row.get("argument_domain_selector_hash") != canonical_hash(domain):
            raise ValueError("restored binding argument domain hash mismatch")
        materializer_contract = row.get("materializer_contract")
        if row.get("materializer_contract_hash") != canonical_hash(
            materializer_contract
        ):
            raise ValueError("restored binding materializer contract hash mismatch")
        privacy_contract = row.get("privacy_contract")
        if row.get("privacy_contract_hash") != canonical_hash(privacy_contract):
            raise ValueError("restored binding privacy contract hash mismatch")
        if row.get("adaptive_query_contract") != {
            "max_rounds": 3,
            "model_selects_arguments": True,
            "transport_allowed_during_prepare": True,
            "transport_allowed_during_call": False,
        }:
            raise ValueError("restored binding max_rounds/adaptive contract mismatch")
        source_route_ids = row.get("source_route_ids")
        if row.get("tool_id") == "get_supply_chain_evidence" and isinstance(
            source_route_ids, list
        ) and "tushare.relationship_graph" in source_route_ids:
            raise ValueError("supply-chain evidence must not reuse the holder graph route")
        if (
            not isinstance(source_route_ids, list)
            or source_route_ids != sorted(set(source_route_ids))
            or not set(source_route_ids) <= set(routes_by_id)
        ):
            raise ValueError("restored binding source route closure mismatch")
        binding_body = {key: value for key, value in row.items() if key != "binding_id"}
        if binding_id != "binding:" + canonical_hash(binding_body)[7:]:
            raise ValueError("Sector/Relationship binding id hash mismatch")
        expected_body = _binding_body(
            agent_id=row["agent_id"],
            stage=row["stage"],
            tool_id=row["tool_id"],
            routes_by_id=routes_by_id,
        )
        if binding_body != expected_body:
            raise ValueError("Sector/Relationship binding contract drift")

    if len(binding_ids) != len(set(binding_ids)):
        raise ValueError("Sector/Relationship binding ids must be unique")
    binding_id_set = set(binding_ids)
    coverage_ids = [row.get("binding_id") for row in coverage]
    fixture_ids = [row.get("binding_id") for row in fixtures]
    if len(coverage_ids) != len(set(coverage_ids)) or set(coverage_ids) != binding_id_set:
        raise ValueError("KNOT coverage exact closure mismatch")
    if len(fixture_ids) != len(set(fixture_ids)) or set(fixture_ids) != binding_id_set:
        raise ValueError("significance fixture exact closure mismatch")
    fixtures_by_binding = {row["binding_id"]: row for row in fixtures}
    bindings_by_id = {row["binding_id"]: row for row in bindings}
    for row in coverage:
        binding = bindings_by_id[row["binding_id"]]
        for field in ("agent_id", "stage", "semantic_capability_id", "tool_id"):
            if row.get(field) != binding.get(field):
                raise ValueError("KNOT coverage binding metadata drift")
        fixture = fixtures_by_binding[row["binding_id"]]
        if (
            row.get("significance_fixture_id") != fixture.get("fixture_id")
            or row.get("significance_fixture_hash") != fixture.get("fixture_hash")
        ):
            raise ValueError("KNOT coverage significance fixture drift")
        if row.get("candidate_generation_allowed") is not False:
            raise ValueError("PR6 must not enable Candidate generation")
    failed = [
        row["binding_id"]
        for row in fixtures
        if not evaluate_sector_relationship_significance_fixture(row)["passed"]
    ]
    if failed:
        raise ValueError(f"significance fixtures failed: {failed[:3]}")

    supply = next(
        row for row in bindings if row["tool_id"] == "get_supply_chain_evidence"
    )
    if "tushare.relationship_graph" in supply["source_route_ids"]:
        raise ValueError("supply-chain evidence must not reuse the holder graph route")
    if supply["source_route_ids"] != ["official.company_supply_chain_disclosures"]:
        raise ValueError("supply-chain authoritative route mismatch")
    if supply.get("no_evidence_policy") != "ABSTAIN_NO_FACTUAL_EDGE":
        raise ValueError("supply-chain no-evidence policy must abstain")
    supply_derivation = supply["materializer_contract"]["derivation_contract"]
    if (
        supply_derivation.get("capture_revision_policy")
        != "FIRST_COMPLETE_CAPTURE_WINS"
        or supply_derivation.get("same_key_retry_policy")
        != "REUSE_WITHOUT_TRANSPORT"
    ):
        raise ValueError("supply-chain immutable retry policy mismatch")


def write_sector_relationship_preservation_overlay(root: Path) -> Path:
    path = (
        root
        / "registry/prompt_checks/capability_preservation/"
        "sector_relationship_preservation_overlay_v1.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            build_sector_relationship_preservation_overlay(root),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return path


__all__ = [
    "LEGACY_SECTOR_AGENT_IDS",
    "NEW_SECTOR_AGENT_IDS",
    "QUERY_BUNDLE_CONTRACT_VERSION",
    "SECTOR_AGENT_IDS",
    "SECTOR_COMMON_TOOL_IDS",
    "argument_schema_for_tool",
    "build_sector_relationship_preservation_overlay",
    "evaluate_sector_relationship_significance_fixture",
    "validate_sector_relationship_preservation_overlay",
    "write_sector_relationship_preservation_overlay",
]

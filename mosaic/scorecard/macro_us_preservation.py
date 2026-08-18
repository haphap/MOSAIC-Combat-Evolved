"""Staged Macro/US source and capability-preservation contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from mosaic.dataflows.macro_snapshots import ALFRED_SERIES_MAP
from mosaic.dataflows.macro_source_contracts import (
    US_ECONOMY_SERIES_MAP,
    US_FINANCIAL_CONDITIONS_SERIES_MAP,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.preservation_snapshots import (
    build_preactivation_capability_binding_manifest,
    load_preactivation_agent_manifests,
)
from mosaic.scorecard.macro_series_backfill import ALFRED_SCORECARD_SERIES_MAP
from mosaic.scorecard.sector_relationship_preservation import (
    evaluate_sector_relationship_significance_fixture,
)


SCHEMA_VERSION = "macro_us_preservation_overlay_v1"
ACTIVATION_GATE = "PR12_L1_L2_ATOMIC_ACTIVATION"
QUERY_BUNDLE_CONTRACT_VERSION = "frozen_snapshot_query_v1"
KNOT_EVALUATOR_CONTRACT_VERSION = "knot_binding_lineage_evaluator_v1"
SIGNIFICANCE_CONTRACT_VERSION = "paired_binding_significance_fixture_v1"

MACRO_US_BINDING_ROSTER: tuple[tuple[str, str, str], ...] = (
    ("central_bank", "central_bank_policy", "get_central_bank_snapshot"),
    ("central_bank", "china_yield_curve", "get_central_bank_snapshot"),
    ("central_bank", "rates_credit", "get_central_bank_snapshot"),
    ("us_economy", "us_macro", "get_us_macro_snapshot"),
    (
        "us_financial_conditions",
        "fx_conditions",
        "get_us_financial_conditions_snapshot",
    ),
    (
        "us_financial_conditions",
        "rates_credit",
        "get_us_financial_conditions_snapshot",
    ),
    (
        "us_financial_conditions",
        "us_financial_conditions",
        "get_us_financial_conditions_snapshot",
    ),
    (
        "us_financial_conditions",
        "volatility",
        "get_us_financial_conditions_snapshot",
    ),
)

_COMPONENT_WEIGHTS = (
    ("central_bank", "pboc_policy_bias", "PR10_CHINA_SOURCE_ACTIVATION"),
    ("central_bank", "liquidity_money_market", "PR10_CHINA_SOURCE_ACTIVATION"),
    ("central_bank", "china_curve", "PR10_CHINA_SOURCE_ACTIVATION"),
    ("central_bank", "credit_conditions", "PR10_CHINA_SOURCE_ACTIVATION"),
    ("us_financial_conditions", "fed_liquidity", "PR12_L1_L2_ATOMIC_ACTIVATION"),
    ("us_financial_conditions", "us_curve", "PR12_L1_L2_ATOMIC_ACTIVATION"),
    (
        "us_financial_conditions",
        "credit_financial_stress",
        "PR12_L1_L2_ATOMIC_ACTIVATION",
    ),
    ("us_financial_conditions", "usd_rmb", "PR12_L1_L2_ATOMIC_ACTIVATION"),
)

_VOLATILITY_OWNERSHIP_CONTRACT = {
    "production_macro_owner": "us_financial_conditions",
    "us_implied_volatility_series": ["VIXCLS"],
    "cross_market_stress_series": ["BAA10Y", "NFCI", "VIXCLS"],
    "china_realized_volatility_consumer": "cro",
    "china_realized_volatility_usage": "RISK_INPUT_ONLY_NOT_MACRO_VOTE",
    "china_realized_volatility_materialization_gate": "PR12_TRUSTED_RISK_INPUT",
    "sector_per_security_volatility_usage": "SECURITY_LEVEL_CONTEXT_ONLY",
    "sector_per_security_volatility_substitution_allowed": False,
}

_COMPATIBILITY_DECISION = {
    "decision": "NO_COMPATIBILITY_PROJECTION",
    "retired_contract": "six_factor_macro_aggregate_and_stance",
    "legacy_status": "legacy_unverified",
    "current_contract": "ten_independent_accepted_transmissions",
    "aggregate_output_allowed": False,
    "stance_output_allowed": False,
    "audit_read_allowed": True,
    "approval_required_to_change": True,
}

_FORBIDDEN_PUBLIC_KEYS = {
    "abstract",
    "claim_text",
    "raw_payload",
    "raw_prose",
    "report_text",
    "source_span",
    "source_span_ids",
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _component_by_provider_series() -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for component, series_ids in US_ECONOMY_SERIES_MAP.items():
        for series_id in series_ids:
            result[series_id] = ("us_economy", component)
    for component, series_ids in US_FINANCIAL_CONDITIONS_SERIES_MAP.items():
        for series_id in series_ids:
            if series_id.startswith("official."):
                continue
            if series_id in result:
                raise ValueError(f"duplicate US series ownership: {series_id}")
            result[series_id] = ("us_financial_conditions", component)
    return result


def _source_series() -> list[dict[str, Any]]:
    component_by_series = _component_by_provider_series()
    rows: list[dict[str, Any]] = []
    for mapping in ALFRED_SERIES_MAP.values():
        series_id = mapping["series_id"]
        owner_role, component_id = component_by_series[series_id]
        rows.append(
            {
                "provider_series_id": series_id,
                "source_identity": f"ALFRED.{series_id}",
                "source_route_id": "alfred.us_macro",
                "owner_role": owner_role,
                "component_id": component_id,
                "unit": mapping["unit"],
                "observation_kind": "NUMERIC",
                "numeric_component_contribution": True,
                "scorecard_series_id": ALFRED_SCORECARD_SERIES_MAP.get(series_id),
            }
        )
    for series_id, field, scorecard_series_id in (
        ("DGS2", "y2", "US2Y"),
        ("DGS3MO", "m3", "US3M"),
        ("DGS10", "y10", "US10Y"),
        ("DGS30", "y30", None),
    ):
        rows.append(
            {
                "provider_series_id": series_id,
                "source_identity": f"tushare.us_tycr.{field}",
                "source_route_id": "tushare.us_tycr",
                "owner_role": "us_financial_conditions",
                "component_id": "us_curve",
                "unit": "Percent",
                "observation_kind": "NUMERIC",
                "numeric_component_contribution": True,
                "scorecard_series_id": scorecard_series_id,
            }
        )
    rows.append(
        {
            "provider_series_id": "USDCNH",
            "source_identity": "tushare.fx_daily.USDCNH.FXCM",
            "source_route_id": "tushare.fx_daily",
            "owner_role": "us_financial_conditions",
            "component_id": "usd_rmb",
            "unit": "CNY per USD",
            "observation_kind": "NUMERIC",
            "numeric_component_contribution": True,
            "scorecard_series_id": "USDCNY",
        }
    )
    rows.extend(
        [
            {
                "provider_series_id": "FOMC_RSS",
                "source_identity": "official.fomc_statement",
                "source_route_id": "official.us_policy",
                "owner_role": "us_financial_conditions",
                "component_id": "fed_liquidity",
                "unit": None,
                "observation_kind": "EVENT_LINEAGE_ONLY",
                "numeric_component_contribution": False,
                "scorecard_series_id": None,
            },
            {
                "provider_series_id": "EFFR",
                "source_identity": "official.nyfed_effr",
                "source_route_id": "market.us_conditions",
                "owner_role": "us_financial_conditions",
                "component_id": "fed_liquidity",
                "unit": "Percent",
                "observation_kind": "NUMERIC",
                "numeric_component_contribution": True,
                "scorecard_series_id": None,
            },
            {
                "provider_series_id": "SOFR",
                "source_identity": "official.nyfed_sofr",
                "source_route_id": "market.us_conditions",
                "owner_role": "us_financial_conditions",
                "component_id": "fed_liquidity",
                "unit": "Percent",
                "observation_kind": "NUMERIC",
                "numeric_component_contribution": True,
                "scorecard_series_id": None,
            },
        ]
    )
    rows.sort(key=lambda row: row["provider_series_id"])
    return rows


def _source_priority_contract() -> dict[str, Any]:
    return {
        "policy": "TUSHARE_FIRST_FIELD_LEVEL_NO_RUNTIME_SUBSTITUTION",
        "primary_sources": [
            {
                "semantic_field": "us_nominal_treasury_curve",
                "source_route_id": "tushare.us_tycr",
                "provider_series_ids": ["DGS2", "DGS3MO", "DGS10", "DGS30"],
            },
            {
                "semantic_field": "usd_cnh",
                "source_route_id": "tushare.fx_daily",
                "provider_series_ids": ["USDCNH"],
            },
        ],
        "supplemental_sources": [
            {
                "source_route_id": "alfred.us_macro",
                "reason": "TUSHARE_CATALOG_FIELD_ABSENT",
                "provider_series_ids": sorted(
                    mapping["series_id"] for mapping in ALFRED_SERIES_MAP.values()
                ),
            },
            {
                "source_route_id": "market.us_conditions",
                "reason": "TUSHARE_CATALOG_FIELD_ABSENT",
                "provider_series_ids": ["EFFR", "SOFR"],
            },
            {
                "source_route_id": "official.us_policy",
                "reason": "TUSHARE_CATALOG_FIELD_ABSENT",
                "provider_series_ids": ["FOMC_RSS"],
            },
        ],
        "historical_cache_miss_policy": "LIVE_ROUTES_FAIL_CLOSED_NO_BACKDATED_CAPTURE",
    }


def _component_weights() -> list[dict[str, Any]]:
    rows = [
        {
            "owner_role": owner_role,
            "component_id": component_id,
            "weight": 1,
            "weight_contract_version": "macro_component_weights_v2",
            "activation_dependency": dependency,
        }
        for owner_role, component_id, dependency in _COMPONENT_WEIGHTS
    ]
    rows.sort(key=lambda row: (row["owner_role"], row["component_id"]))
    return rows


def _binding_index(binding_manifest: Mapping[str, Any]) -> dict[tuple[str, str, str], dict]:
    return {
        (row["agent_id"], row["semantic_capability_id"], row["tool_id"]): row
        for row in binding_manifest["bindings"]
    }


def _bindings(binding_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    index = _binding_index(binding_manifest)
    rows: list[dict[str, Any]] = []
    for key in MACRO_US_BINDING_ROSTER:
        base = index.get(key)
        if base is None:
            raise ValueError(f"base binding is missing: {key}")
        rows.append(
            {
                "binding_id": base["binding_id"],
                "agent_id": base["agent_id"],
                "stage": base["stage"],
                "semantic_capability_id": base["semantic_capability_id"],
                "tool_id": base["tool_id"],
                "source_route_ids": base["source_route_ids"],
                "base_binding_hash": canonical_hash(base),
                "base_activation_state": base["activation_state"],
                "source_activation_state": "staged",
                "source_readiness_gate": (
                    "PR10_CHINA_SOURCE_ACTIVATION"
                    if base["agent_id"] == "central_bank"
                    else "PR12_L1_L2_ATOMIC_ACTIVATION"
                ),
                "query_bundle_contract_version": base[
                    "query_bundle_contract_version"
                ],
                "call_transport": False,
            }
        )
    rows.sort(key=lambda row: row["binding_id"])
    return rows


def _fixture(binding: Mapping[str, Any]) -> dict[str, Any]:
    binding_id = str(binding["binding_id"])
    fingerprint = canonical_hash(
        {
            "binding_id": binding_id,
            "canonical_args_hash": canonical_hash({"as_of_date": "opaque"}),
        }
    )
    lineage = {
        "tool_result_fingerprint": fingerprint,
        "typed_edge_hash": canonical_hash(
            {"fingerprint": fingerprint, "edge_type": "supports"}
        ),
        "accepted_claim_graph_hash": canonical_hash(
            {"binding_id": binding_id, "fingerprint": fingerprint}
        ),
        "counterevidence_rule_hash": canonical_hash(
            {"rule": "support_minus_contradiction"}
        ),
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
        "source_activation_state": "staged",
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


def _redistribution_closure(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_owner_capability = {
        (row["agent_id"], row["semantic_capability_id"]): row["binding_id"]
        for row in bindings
    }
    rows = [
        {
            "semantic_capability_id": "central_bank_policy",
            "baseline_tool_id": "get_central_bank_snapshot",
            "baseline_consumers": ["central_bank"],
            "current_owners": ["central_bank", "us_financial_conditions"],
            "replacement_tools": [
                "get_central_bank_snapshot",
                "get_us_financial_conditions_snapshot",
            ],
            "binding_ids": [
                by_owner_capability[("central_bank", "central_bank_policy")],
                by_owner_capability[
                    ("us_financial_conditions", "us_financial_conditions")
                ],
            ],
            "component_refs": [
                "central_bank:pboc_policy_bias",
                "us_financial_conditions:fed_liquidity",
            ],
            "legacy_vote_weight": 0,
            "disposition": "equivalent_staged",
        },
        {
            "semantic_capability_id": "fx_conditions",
            "baseline_tool_id": "get_fx_conditions_snapshot",
            "baseline_consumers": ["dollar"],
            "current_owners": ["us_financial_conditions"],
            "replacement_tools": ["get_us_financial_conditions_snapshot"],
            "binding_ids": [
                by_owner_capability[("us_financial_conditions", "fx_conditions")]
            ],
            "component_refs": ["us_financial_conditions:usd_rmb"],
            "legacy_vote_weight": 0,
            "disposition": "equivalent_staged",
        },
        {
            "semantic_capability_id": "rates_credit",
            "baseline_tool_id": "get_rates_credit_snapshot",
            "baseline_consumers": ["yield_curve"],
            "current_owners": ["central_bank", "us_financial_conditions"],
            "replacement_tools": [
                "get_central_bank_snapshot",
                "get_us_financial_conditions_snapshot",
            ],
            "binding_ids": [
                by_owner_capability[("central_bank", "rates_credit")],
                by_owner_capability[("us_financial_conditions", "rates_credit")],
            ],
            "component_refs": [
                "central_bank:liquidity_money_market",
                "central_bank:china_curve",
                "central_bank:credit_conditions",
                "us_financial_conditions:us_curve",
                "us_financial_conditions:credit_financial_stress",
            ],
            "legacy_vote_weight": 0,
            "disposition": "equivalent_staged",
        },
        {
            "semantic_capability_id": "volatility",
            "baseline_tool_id": "get_volatility_snapshot",
            "baseline_consumers": ["volatility"],
            "current_owners": ["us_financial_conditions"],
            "replacement_tools": ["get_us_financial_conditions_snapshot"],
            "binding_ids": [
                by_owner_capability[("us_financial_conditions", "volatility")]
            ],
            "component_refs": ["us_financial_conditions:credit_financial_stress"],
            "legacy_vote_weight": 0,
            "disposition": "equivalent_staged",
        },
    ]
    rows.sort(key=lambda row: row["semantic_capability_id"])
    return rows


def _walk_forbidden(value: Any, path: str = "$.") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"private prose field {path}{key} is forbidden")
            _walk_forbidden(item, f"{path}{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, f"{path}{index}.")


def _expected_overlay(root: Path) -> dict[str, Any]:
    active, route_manifest = load_preactivation_agent_manifests(root)
    binding_manifest = build_preactivation_capability_binding_manifest(root)
    required_route_ids = {
        "alfred.us_macro",
        "market.us_conditions",
        "official.us_policy",
        "tushare.fx_daily",
        "tushare.us_tycr",
    }
    routes = [
        row
        for row in route_manifest["routes"]
        if row["route_id"] in required_route_ids
    ]
    routes.sort(key=lambda row: row["route_id"])
    if {row["route_id"] for row in routes} != required_route_ids:
        raise ValueError("Macro/US route manifest closure is incomplete")

    bindings = _bindings(binding_manifest)
    fixtures = [_fixture(binding) for binding in bindings]
    fixtures.sort(key=lambda row: row["binding_id"])
    fixture_by_binding = {row["binding_id"]: row for row in fixtures}
    coverage = [
        _coverage(binding, fixture_by_binding[binding["binding_id"]])
        for binding in bindings
    ]
    coverage.sort(key=lambda row: row["binding_id"])
    body = {
        "schema_version": SCHEMA_VERSION,
        "activation_state": "staged",
        "activation_gate": ACTIVATION_GATE,
        "base_active_agent_tool_manifest_hash": canonical_hash(active),
        "base_capability_binding_manifest_hash": canonical_hash(binding_manifest),
        "base_agent_data_route_manifest_hash": canonical_hash(route_manifest),
        "query_bundle_contract_version": QUERY_BUNDLE_CONTRACT_VERSION,
        "routes": routes,
        "bindings": bindings,
        "source_series": _source_series(),
        "source_priority_contract": _source_priority_contract(),
        "component_weights": _component_weights(),
        "redistribution_closure": _redistribution_closure(bindings),
        "volatility_ownership_contract": _VOLATILITY_OWNERSHIP_CONTRACT,
        "compatibility_decision": _COMPATIBILITY_DECISION,
        "knot_coverage": coverage,
        "significance_fixtures": fixtures,
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def build_macro_us_preservation_overlay(root: Path) -> dict[str, Any]:
    overlay = _expected_overlay(root)
    validate_macro_us_preservation_overlay(overlay, root=root)
    return overlay


def evaluate_macro_us_significance_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    return evaluate_sector_relationship_significance_fixture(fixture)


def validate_macro_us_preservation_overlay(
    overlay: Mapping[str, Any], *, root: Path
) -> None:
    _walk_forbidden(overlay)
    if overlay.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Macro/US overlay schema version mismatch")
    if overlay.get("activation_state") != "staged":
        raise ValueError("Macro/US overlay must remain staged")
    if overlay.get("activation_gate") != ACTIVATION_GATE:
        raise ValueError("Macro/US activation gate mismatch")
    body = {key: value for key, value in overlay.items() if key != "manifest_hash"}
    if overlay.get("manifest_hash") != canonical_hash(body):
        raise ValueError("Macro/US overlay manifest hash mismatch")

    bindings = overlay.get("bindings")
    coverage = overlay.get("knot_coverage")
    fixtures = overlay.get("significance_fixtures")
    if not all(isinstance(value, list) for value in (bindings, coverage, fixtures)):
        raise ValueError("Macro/US KNOT collections must be arrays")
    binding_ids = {row.get("binding_id") for row in bindings}
    if binding_ids != {row.get("binding_id") for row in coverage}:
        raise ValueError("KNOT coverage exact closure mismatch")
    if binding_ids != {row.get("binding_id") for row in fixtures}:
        raise ValueError("KNOT significance exact closure mismatch")
    if not all(evaluate_macro_us_significance_fixture(row)["passed"] for row in fixtures):
        raise ValueError("Macro/US significance fixture failed")

    expected = _expected_overlay(root)
    for field, error in (
        ("bindings", "binding contract drift"),
        ("routes", "route contract drift"),
        ("source_series", "source series contract drift"),
        ("source_priority_contract", "source priority contract drift"),
        ("component_weights", "component weight contract drift"),
        ("redistribution_closure", "redistribution contract drift"),
        ("volatility_ownership_contract", "volatility ownership contract drift"),
        ("compatibility_decision", "compatibility decision drift"),
        ("knot_coverage", "KNOT coverage contract drift"),
        ("significance_fixtures", "significance fixture contract drift"),
    ):
        if overlay.get(field) != expected[field]:
            raise ValueError(error)
    for field in (
        "base_active_agent_tool_manifest_hash",
        "base_capability_binding_manifest_hash",
        "base_agent_data_route_manifest_hash",
        "query_bundle_contract_version",
    ):
        if overlay.get(field) != expected[field]:
            raise ValueError(f"Macro/US base contract drift: {field}")

    schema = _read_json(root / "schemas/macro_us_preservation_overlay_v1.schema.json")
    failures = sorted(
        Draft202012Validator(schema).iter_errors(dict(overlay)),
        key=lambda error: list(error.absolute_path),
    )
    if failures:
        raise ValueError(f"Macro/US overlay JSON Schema mismatch: {failures[0].message}")


def write_macro_us_preservation_overlay(root: Path) -> Path:
    path = (
        root
        / "registry/prompt_checks/capability_preservation/"
        "macro_us_preservation_overlay_v1.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_macro_us_preservation_overlay(root), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


__all__ = [
    "ACTIVATION_GATE",
    "MACRO_US_BINDING_ROSTER",
    "SCHEMA_VERSION",
    "build_macro_us_preservation_overlay",
    "evaluate_macro_us_significance_fixture",
    "validate_macro_us_preservation_overlay",
    "write_macro_us_preservation_overlay",
]

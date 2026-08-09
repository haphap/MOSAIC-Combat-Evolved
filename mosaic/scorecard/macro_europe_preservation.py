"""Staged Europe macro source and capability-preservation contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from mosaic.dataflows.macro_source_contracts import (
    EURO_AREA_FINANCIAL_SERIES_MAP,
    EU_SERIES_MAP,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.preservation_snapshots import (
    build_preactivation_capability_binding_manifest,
    load_preactivation_agent_manifests,
)
from mosaic.scorecard.sector_relationship_preservation import (
    evaluate_sector_relationship_significance_fixture,
)


SCHEMA_VERSION = "macro_europe_preservation_overlay_v1"
ACTIVATION_GATE = "PR12_L1_L2_ATOMIC_ACTIVATION"
QUERY_BUNDLE_CONTRACT_VERSION = "frozen_snapshot_query_v1"
KNOT_EVALUATOR_CONTRACT_VERSION = "knot_binding_lineage_evaluator_v1"
SIGNIFICANCE_CONTRACT_VERSION = "paired_binding_significance_fixture_v1"

MACRO_EUROPE_BINDING_ROSTER: tuple[tuple[str, str, str], ...] = (
    ("eu_economy", "eu_macro", "get_eu_macro_snapshot"),
    (
        "euro_area_financial_conditions",
        "euro_area_financial_conditions",
        "get_euro_area_financial_conditions_snapshot",
    ),
)

_COMPONENT_WEIGHTS = tuple(
    (role, component)
    for role, components in (
        (
            "eu_economy",
            ("growth_production", "prices", "employment", "demand_trade"),
        ),
        (
            "euro_area_financial_conditions",
            (
                "ecb_liquidity",
                "euro_area_curve",
                "bank_credit",
                "eur_financial_stress",
            ),
        ),
    )
    for component in components
)

_PIT_BOUNDARY_CONTRACT = {
    "ecb_history_mode": "AUTHORITATIVE_VINTAGE_REPLAY",
    "ecb_version_selector": "max(VALID_FROM)<=as_of_cutoff;Delete=tombstone",
    "eurostat_history_mode": "FORWARD_ARCHIVE_ONLY",
    "eurostat_earliest_trustworthy_date": "FIRST_SUCCESSFUL_ARCHIVED_CAPTURE",
    "market_fx_history_mode": "OBSERVED_LIVE_ONLY",
    "historical_without_forward_capture": "BLOCKED",
    "current_response_backfill_allowed": False,
}

_FX_IDENTITY_CONTRACT = {
    "materialized_pair": "EUR_USD",
    "instrument_id": "EURUSD.FXCM",
    "source_identity": "tushare.fx_daily.EURUSD.FXCM",
    "eur_cny_status": "UNRESOLVED",
    "eur_cny_instrument_id": None,
    "synthetic_cross_allowed": False,
    "offshore_cross_rename_allowed": False,
}

_POLICY_EVENT_CONTRACT = {
    "numeric_policy_route": "ecb.euro_macro",
    "numeric_policy_series": [
        "FM.B.U2.EUR.4F.KR.DFR.LEV",
        "FM.B.U2.EUR.4F.KR.MRR_FR.LEV",
        "EST.B.EU000A2X2A25.WT",
    ],
    "policy_event_route": "tushare.eco_cal.eur",
    "policy_event_semantics": "ECB_MONETARY_POLICY_DECISION_METADATA",
    "statement_text_source": None,
    "statement_text_invented": False,
    "numeric_series_may_impersonate_statement": False,
}

_PRESERVATION_DISPOSITION = [
    {
        "semantic_capability_id": "eu_macro",
        "baseline_status": "POST_MIGRATION_NEW",
        "current_owner": "eu_economy",
        "tool_id": "get_eu_macro_snapshot",
        "disposition": "post_migration_new_staged",
        "legacy_vote_weight": 0,
    },
    {
        "semantic_capability_id": "euro_area_financial_conditions",
        "baseline_status": "POST_MIGRATION_NEW",
        "current_owner": "euro_area_financial_conditions",
        "tool_id": "get_euro_area_financial_conditions_snapshot",
        "disposition": "post_migration_new_staged",
        "legacy_vote_weight": 0,
    },
]

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


def _source_series() -> list[dict[str, Any]]:
    rows = [
        {
            "provider_series_id": series_key,
            "source_identity": f"eurostat.{contract['dataset']}",
            "source_route_id": "eurostat.euro_macro",
            "owner_role": "eu_economy",
            "component_id": contract["component"],
            "observation_kind": "NUMERIC",
            "numeric_component_contribution": True,
            "pit_mode": "FORWARD_ARCHIVE_ONLY",
        }
        for series_key, contract in EU_SERIES_MAP.items()
    ]
    for component_id, series_ids in EURO_AREA_FINANCIAL_SERIES_MAP.items():
        for series_id in series_ids:
            if series_id.startswith("tushare."):
                continue
            rows.append(
                {
                    "provider_series_id": series_id,
                    "source_identity": f"ecb.{series_id}",
                    "source_route_id": "ecb.euro_macro",
                    "owner_role": "euro_area_financial_conditions",
                    "component_id": component_id,
                    "observation_kind": "NUMERIC",
                    "numeric_component_contribution": True,
                    "pit_mode": "AUTHORITATIVE_VINTAGE_REPLAY",
                }
            )
    rows.append(
        {
            "provider_series_id": "EURUSD.FXCM",
            "source_identity": "tushare.fx_daily.EURUSD.FXCM",
            "source_route_id": "market.euro_fx",
            "owner_role": "euro_area_financial_conditions",
            "component_id": "eur_financial_stress",
            "observation_kind": "NUMERIC",
            "numeric_component_contribution": True,
            "pit_mode": "OBSERVED_LIVE_ONLY",
        }
    )
    rows.sort(key=lambda row: row["provider_series_id"])
    return rows


def _binding_index(binding_manifest: Mapping[str, Any]) -> dict[tuple[str, str, str], dict]:
    return {
        (row["agent_id"], row["semantic_capability_id"], row["tool_id"]): row
        for row in binding_manifest["bindings"]
    }


def _bindings(binding_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    index = _binding_index(binding_manifest)
    rows = []
    for key in MACRO_EUROPE_BINDING_ROSTER:
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
                "source_readiness_gate": ACTIVATION_GATE,
                "query_bundle_contract_version": base[
                    "query_bundle_contract_version"
                ],
                "call_transport": False,
            }
        )
    rows.sort(key=lambda row: row["binding_id"])
    return rows


def _component_weights() -> list[dict[str, Any]]:
    rows = [
        {
            "owner_role": role,
            "component_id": component,
            "weight": 1,
            "weight_contract_version": "macro_component_weights_v2",
            "activation_dependency": ACTIVATION_GATE,
        }
        for role, component in _COMPONENT_WEIGHTS
    ]
    rows.sort(key=lambda row: (row["owner_role"], row["component_id"]))
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
        "ecb.euro_macro",
        "eurostat.euro_macro",
        "market.euro_fx",
        "tushare.eco_cal.eur",
    }
    routes = [
        row for row in route_manifest["routes"] if row["route_id"] in required_route_ids
    ]
    routes.sort(key=lambda row: row["route_id"])
    if {row["route_id"] for row in routes} != required_route_ids:
        raise ValueError("Macro/Europe route manifest closure is incomplete")
    bindings = _bindings(binding_manifest)
    fixtures = sorted((_fixture(row) for row in bindings), key=lambda row: row["binding_id"])
    fixture_by_binding = {row["binding_id"]: row for row in fixtures}
    coverage = sorted(
        (
            _coverage(binding, fixture_by_binding[binding["binding_id"]])
            for binding in bindings
        ),
        key=lambda row: row["binding_id"],
    )
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
        "component_weights": _component_weights(),
        "pit_boundary_contract": _PIT_BOUNDARY_CONTRACT,
        "fx_identity_contract": _FX_IDENTITY_CONTRACT,
        "policy_event_contract": _POLICY_EVENT_CONTRACT,
        "preservation_disposition": _PRESERVATION_DISPOSITION,
        "knot_coverage": coverage,
        "significance_fixtures": fixtures,
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def build_macro_europe_preservation_overlay(root: Path) -> dict[str, Any]:
    overlay = _expected_overlay(root)
    validate_macro_europe_preservation_overlay(overlay, root=root)
    return overlay


def evaluate_macro_europe_significance_fixture(
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    return evaluate_sector_relationship_significance_fixture(fixture)


def validate_macro_europe_preservation_overlay(
    overlay: Mapping[str, Any], *, root: Path
) -> None:
    _walk_forbidden(overlay)
    if overlay.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Macro/Europe overlay schema version mismatch")
    if overlay.get("activation_state") != "staged":
        raise ValueError("Macro/Europe overlay must remain staged")
    if overlay.get("activation_gate") != ACTIVATION_GATE:
        raise ValueError("Macro/Europe activation gate mismatch")
    body = {key: value for key, value in overlay.items() if key != "manifest_hash"}
    if overlay.get("manifest_hash") != canonical_hash(body):
        raise ValueError("Macro/Europe overlay manifest hash mismatch")
    expected = _expected_overlay(root)
    for field, message in (
        ("routes", "route contract drift"),
        ("bindings", "binding contract drift"),
        ("source_series", "source series contract drift"),
        ("component_weights", "component weight contract drift"),
        ("pit_boundary_contract", "PIT boundary contract drift"),
        ("fx_identity_contract", "FX identity contract drift"),
        ("policy_event_contract", "policy event contract drift"),
        ("preservation_disposition", "preservation disposition drift"),
    ):
        if overlay.get(field) != expected[field]:
            raise ValueError(f"Macro/Europe {message}")
    for field in (
        "base_active_agent_tool_manifest_hash",
        "base_capability_binding_manifest_hash",
        "base_agent_data_route_manifest_hash",
        "query_bundle_contract_version",
    ):
        if overlay.get(field) != expected[field]:
            raise ValueError(f"Macro/Europe parent contract drift: {field}")
    binding_ids = {row["binding_id"] for row in expected["bindings"]}
    if {row.get("binding_id") for row in overlay.get("knot_coverage", [])} != binding_ids:
        raise ValueError("Macro/Europe KNOT coverage exact closure mismatch")
    if {
        row.get("binding_id") for row in overlay.get("significance_fixtures", [])
    } != binding_ids:
        raise ValueError("Macro/Europe significance fixture exact closure mismatch")
    if overlay.get("knot_coverage") != expected["knot_coverage"]:
        raise ValueError("Macro/Europe KNOT coverage drift")
    if overlay.get("significance_fixtures") != expected["significance_fixtures"]:
        raise ValueError("Macro/Europe significance fixture drift")
    schema = _read_json(
        root / "schemas/macro_europe_preservation_overlay_v1.schema.json"
    )
    failures = sorted(
        Draft202012Validator(schema).iter_errors(dict(overlay)),
        key=lambda error: list(error.absolute_path),
    )
    if failures:
        raise ValueError(
            f"Macro/Europe overlay JSON Schema mismatch: {failures[0].message}"
        )


def write_macro_europe_preservation_overlay(root: Path) -> Path:
    destination = (
        root
        / "registry/prompt_checks/capability_preservation/"
        "macro_europe_preservation_overlay_v1.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(build_macro_europe_preservation_overlay(root), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


__all__ = [
    "ACTIVATION_GATE",
    "MACRO_EUROPE_BINDING_ROSTER",
    "SCHEMA_VERSION",
    "build_macro_europe_preservation_overlay",
    "evaluate_macro_europe_significance_fixture",
    "validate_macro_europe_preservation_overlay",
    "write_macro_europe_preservation_overlay",
]

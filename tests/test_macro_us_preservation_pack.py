from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mosaic.rke.schema_validation import validate_json_schema_artifact
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.macro_us_preservation import (
    MACRO_US_BINDING_ROSTER,
    build_macro_us_preservation_overlay,
    evaluate_macro_us_significance_fixture,
    validate_macro_us_preservation_overlay,
)


ROOT = Path(__file__).parents[1]
ARTIFACT = (
    ROOT
    / "registry/prompt_checks/capability_preservation/"
    "macro_us_preservation_overlay_v1.json"
)


def _reseal(value: dict) -> None:
    body = {key: item for key, item in value.items() if key != "manifest_hash"}
    value["manifest_hash"] = canonical_hash(body)


def test_generated_macro_us_overlay_is_current_and_schema_valid():
    expected = build_macro_us_preservation_overlay(ROOT)
    assert expected == json.loads(ARTIFACT.read_text(encoding="utf-8"))
    validate_macro_us_preservation_overlay(expected, root=ROOT)

    result = validate_json_schema_artifact(
        root=ROOT,
        schema_path="schemas/macro_us_preservation_overlay_v1.schema.json",
        artifact_path=(
            "registry/prompt_checks/capability_preservation/"
            "macro_us_preservation_overlay_v1.json"
        ),
        artifact_kind="json",
    )
    assert result.accepted, result.failures


def test_overlay_covers_exact_macro_us_binding_lineage_without_surface_change():
    overlay = build_macro_us_preservation_overlay(ROOT)
    active = json.loads(
        (ROOT / "registry/prompt_checks/agent_tool_contract_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    preactivation = json.loads(
        (ARTIFACT.parent / "current_agent_tool_contract_snapshot_v1.json").read_text(
            encoding="utf-8"
        )
    )
    active_bindings = json.loads(
        (
            ROOT
            / "registry/prompt_checks/capability_preservation/"
            "agent_capability_binding_manifest_v1.json"
        ).read_text(encoding="utf-8")
    )
    preactivation_tools = {
        tool_id
        for agent in preactivation["agents"]
        for tool_id in agent["allowed_tools"]
    }
    active_tools = {
        tool_id for agent in active["agents"] for tool_id in agent["allowed_tools"]
    }
    actual_roster = {
        (row["agent_id"], row["semantic_capability_id"], row["tool_id"])
        for row in overlay["bindings"]
    }
    overlay_binding_ids = {row["binding_id"] for row in overlay["bindings"]}
    active_binding_ids = {row["binding_id"] for row in active_bindings["bindings"]}
    approved_binding_migrations = {
        "binding:09a1f45221b66acbf024d00808aa5bf0312d58b2258061ab92442a10ac1c8586": (
            "binding:a33422a6e4676a1930db480f01de33e2402ed228f43b2841fc560b54ba849b16"
        ),
        "binding:9c0380d8e572a2014178bc01e1c8cc2f281591d2ffcd9e60ca366bdd9c2f27cb": (
            "binding:60207e0e897c66a971e4bbb49a23669307327fdd70056a1453287b6b03b47b7d"
        ),
        "binding:bd7d647d99fc1550c60456640bc4341943ee6601628f04849d3dabd6d1ec5fab": (
            "binding:c62ae5b4bd2d9e2811d16dd2f2a9c71121edcc1987350e8d52aa439ed68b890d"
        ),
    }

    assert len(preactivation_tools) == 18
    assert preactivation_tools < active_tools
    assert actual_roster == set(MACRO_US_BINDING_ROSTER)
    assert len(actual_roster) == 8
    assert approved_binding_migrations.keys() == overlay_binding_ids - active_binding_ids
    assert set(approved_binding_migrations.values()) <= active_binding_ids
    assert all(row["base_activation_state"] == "active" for row in overlay["bindings"])
    assert all(row["source_activation_state"] == "staged" for row in overlay["bindings"])
    assert overlay["activation_state"] == "staged"
    assert overlay["activation_gate"] == "PR12_L1_L2_ATOMIC_ACTIVATION"
    assert overlay["base_active_agent_tool_manifest_hash"] == canonical_hash(
        preactivation
    )


def test_series_component_weight_and_consumer_redistribution_have_exact_closure():
    overlay = build_macro_us_preservation_overlay(ROOT)
    series = overlay["source_series"]
    identities = [row["provider_series_id"] for row in series]
    assert len(identities) == len(set(identities)) == 25
    assert {"DGS2", "DGS3MO", "DGS10", "DGS30", "USDCNH", "VIXCLS"} <= set(
        identities
    )
    assert {row["source_route_id"] for row in series} == {
        "alfred.us_macro",
        "market.us_conditions",
        "official.us_policy",
        "tushare.fx_daily",
        "tushare.us_tycr",
    }
    fomc = next(row for row in series if row["provider_series_id"] == "FOMC_RSS")
    assert fomc["observation_kind"] == "EVENT_LINEAGE_ONLY"
    assert fomc["numeric_component_contribution"] is False

    scorecard = {
        row["provider_series_id"]: row["scorecard_series_id"]
        for row in series
        if row["scorecard_series_id"] is not None
    }
    assert scorecard == {
        "DGS10": "US10Y",
        "DGS2": "US2Y",
        "DGS3MO": "US3M",
        "USDCNH": "USDCNY",
        "VIXCLS": "VIX",
    }
    priority = overlay["source_priority_contract"]
    assert priority["policy"] == "TUSHARE_FIRST_FIELD_LEVEL_NO_RUNTIME_SUBSTITUTION"
    primary_ids = {
        series_id
        for source in priority["primary_sources"]
        for series_id in source["provider_series_ids"]
    }
    supplemental_ids = {
        series_id
        for source in priority["supplemental_sources"]
        for series_id in source["provider_series_ids"]
    }
    assert primary_ids == {"DGS2", "DGS3MO", "DGS10", "DGS30", "USDCNH"}
    assert primary_ids.isdisjoint(supplemental_ids)

    weights = overlay["component_weights"]
    assert len(weights) == 8
    assert len({(row["owner_role"], row["component_id"]) for row in weights}) == 8
    assert all(row["weight"] == 1 for row in weights)
    assert {row["owner_role"] for row in weights} == {
        "central_bank",
        "us_financial_conditions",
    }

    redistribution = {
        row["semantic_capability_id"]: row for row in overlay["redistribution_closure"]
    }
    assert set(redistribution) == {
        "central_bank_policy",
        "fx_conditions",
        "rates_credit",
        "volatility",
    }
    assert redistribution["fx_conditions"]["current_owners"] == [
        "us_financial_conditions"
    ]
    assert redistribution["rates_credit"]["current_owners"] == [
        "central_bank",
        "us_financial_conditions",
    ]
    assert all(row["legacy_vote_weight"] == 0 for row in redistribution.values())


def test_volatility_owner_contract_separates_us_china_and_sector_semantics():
    contract = build_macro_us_preservation_overlay(ROOT)["volatility_ownership_contract"]
    assert contract == {
        "production_macro_owner": "us_financial_conditions",
        "us_implied_volatility_series": ["VIXCLS"],
        "cross_market_stress_series": ["BAA10Y", "NFCI", "VIXCLS"],
        "china_realized_volatility_consumer": "cro",
        "china_realized_volatility_usage": "RISK_INPUT_ONLY_NOT_MACRO_VOTE",
        "china_realized_volatility_materialization_gate": "PR12_TRUSTED_RISK_INPUT",
        "sector_per_security_volatility_usage": "SECURITY_LEVEL_CONTEXT_ONLY",
        "sector_per_security_volatility_substitution_allowed": False,
    }


def test_retired_aggregate_and_stance_have_no_compatibility_projection():
    decision = build_macro_us_preservation_overlay(ROOT)["compatibility_decision"]
    assert decision == {
        "decision": "NO_COMPATIBILITY_PROJECTION",
        "retired_contract": "six_factor_macro_aggregate_and_stance",
        "legacy_status": "legacy_unverified",
        "current_contract": "ten_independent_accepted_transmissions",
        "aggregate_output_allowed": False,
        "stance_output_allowed": False,
        "audit_read_allowed": True,
        "approval_required_to_change": True,
    }


def test_knot_coverage_and_significance_have_exact_binding_closure():
    overlay = build_macro_us_preservation_overlay(ROOT)
    binding_ids = {row["binding_id"] for row in overlay["bindings"]}
    assert binding_ids == {row["binding_id"] for row in overlay["knot_coverage"]}
    assert binding_ids == {
        row["binding_id"] for row in overlay["significance_fixtures"]
    }
    assert all(
        evaluate_macro_us_significance_fixture(row)["passed"]
        for row in overlay["significance_fixtures"]
    )
    assert all(
        row["candidate_generation_allowed"] is False
        for row in overlay["knot_coverage"]
    )

    missing = copy.deepcopy(overlay)
    missing["knot_coverage"].pop()
    _reseal(missing)
    with pytest.raises(ValueError, match="KNOT coverage exact closure"):
        validate_macro_us_preservation_overlay(missing, root=ROOT)


def test_overlay_rejects_activation_source_drift_legacy_vote_and_sector_substitution():
    overlay = build_macro_us_preservation_overlay(ROOT)

    activated = copy.deepcopy(overlay)
    activated["activation_state"] = "active"
    _reseal(activated)
    with pytest.raises(ValueError, match="must remain staged"):
        validate_macro_us_preservation_overlay(activated, root=ROOT)

    source_drift = copy.deepcopy(overlay)
    next(
        row
        for row in source_drift["source_series"]
        if row["provider_series_id"] == "DGS10"
    )["source_route_id"] = "alfred.us_macro"
    _reseal(source_drift)
    with pytest.raises(ValueError, match="source series contract drift"):
        validate_macro_us_preservation_overlay(source_drift, root=ROOT)

    legacy_vote = copy.deepcopy(overlay)
    legacy_vote["redistribution_closure"][0]["legacy_vote_weight"] = 1
    _reseal(legacy_vote)
    with pytest.raises(ValueError, match="redistribution contract drift"):
        validate_macro_us_preservation_overlay(legacy_vote, root=ROOT)

    sector_substitute = copy.deepcopy(overlay)
    sector_substitute["volatility_ownership_contract"][
        "sector_per_security_volatility_substitution_allowed"
    ] = True
    _reseal(sector_substitute)
    with pytest.raises(ValueError, match="volatility ownership contract drift"):
        validate_macro_us_preservation_overlay(sector_substitute, root=ROOT)

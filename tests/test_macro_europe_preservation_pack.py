from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mosaic.rke.schema_validation import validate_json_schema_artifact
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.macro_europe_preservation import (
    MACRO_EUROPE_BINDING_ROSTER,
    build_macro_europe_preservation_overlay,
    evaluate_macro_europe_significance_fixture,
    validate_macro_europe_preservation_overlay,
)


ROOT = Path(__file__).parents[1]
ARTIFACT = (
    ROOT
    / "registry/prompt_checks/capability_preservation/"
    "macro_europe_preservation_overlay_v1.json"
)


def _reseal(value: dict) -> None:
    body = {key: item for key, item in value.items() if key != "manifest_hash"}
    value["manifest_hash"] = canonical_hash(body)


def test_generated_macro_europe_overlay_is_current_and_schema_valid() -> None:
    expected = build_macro_europe_preservation_overlay(ROOT)
    assert expected == json.loads(ARTIFACT.read_text(encoding="utf-8"))
    validate_macro_europe_preservation_overlay(expected, root=ROOT)
    result = validate_json_schema_artifact(
        root=ROOT,
        schema_path="schemas/macro_europe_preservation_overlay_v1.schema.json",
        artifact_path=(
            "registry/prompt_checks/capability_preservation/"
            "macro_europe_preservation_overlay_v1.json"
        ),
        artifact_kind="json",
    )
    assert result.accepted, result.failures


def test_overlay_covers_exact_europe_bindings_and_source_routes() -> None:
    overlay = build_macro_europe_preservation_overlay(ROOT)
    roster = {
        (row["agent_id"], row["semantic_capability_id"], row["tool_id"])
        for row in overlay["bindings"]
    }
    assert roster == set(MACRO_EUROPE_BINDING_ROSTER)
    assert overlay["activation_state"] == "staged"
    assert overlay["activation_gate"] == "PR12_L1_L2_ATOMIC_ACTIVATION"
    assert all(row["base_activation_state"] == "active" for row in overlay["bindings"])
    assert all(row["source_activation_state"] == "staged" for row in overlay["bindings"])
    assert {row["route_id"] for row in overlay["routes"]} == {
        "ecb.euro_macro",
        "eurostat.euro_macro",
        "market.euro_fx",
        "tushare.eco_cal.eur",
    }


def test_series_contract_uses_ecb_history_eurostat_forward_and_real_eurusd() -> None:
    overlay = build_macro_europe_preservation_overlay(ROOT)
    series = overlay["source_series"]
    identities = [row["provider_series_id"] for row in series]
    assert len(identities) == len(set(identities)) == 17
    assert {row["source_route_id"] for row in series} == {
        "ecb.euro_macro",
        "eurostat.euro_macro",
        "market.euro_fx",
    }
    fx = next(row for row in series if row["provider_series_id"] == "EURUSD.FXCM")
    assert fx["source_identity"] == "tushare.fx_daily.EURUSD.FXCM"
    assert fx["component_id"] == "eur_financial_stress"
    boundary = overlay["pit_boundary_contract"]
    assert boundary["ecb_history_mode"] == "AUTHORITATIVE_VINTAGE_REPLAY"
    assert boundary["eurostat_history_mode"] == "FORWARD_ARCHIVE_ONLY"
    assert boundary["historical_without_forward_capture"] == "BLOCKED"
    assert overlay["fx_identity_contract"]["synthetic_cross_allowed"] is False
    assert overlay["fx_identity_contract"]["eur_cny_status"] == "UNRESOLVED"
    assert overlay["policy_event_contract"]["statement_text_invented"] is False


def test_knot_coverage_and_significance_have_exact_binding_closure() -> None:
    overlay = build_macro_europe_preservation_overlay(ROOT)
    binding_ids = {row["binding_id"] for row in overlay["bindings"]}
    assert binding_ids == {row["binding_id"] for row in overlay["knot_coverage"]}
    assert binding_ids == {
        row["binding_id"] for row in overlay["significance_fixtures"]
    }
    assert all(
        evaluate_macro_europe_significance_fixture(row)["passed"]
        for row in overlay["significance_fixtures"]
    )
    assert all(
        row["candidate_generation_allowed"] is False
        for row in overlay["knot_coverage"]
    )


def test_overlay_rejects_activation_source_drift_and_fx_synthesis() -> None:
    overlay = build_macro_europe_preservation_overlay(ROOT)
    activated = copy.deepcopy(overlay)
    activated["activation_state"] = "active"
    _reseal(activated)
    with pytest.raises(ValueError, match="must remain staged"):
        validate_macro_europe_preservation_overlay(activated, root=ROOT)

    source_drift = copy.deepcopy(overlay)
    next(
        row
        for row in source_drift["source_series"]
        if row["provider_series_id"] == "EURUSD.FXCM"
    )["source_identity"] = "tushare.fx_daily.EUR_CNY"
    _reseal(source_drift)
    with pytest.raises(ValueError, match="source series contract drift"):
        validate_macro_europe_preservation_overlay(source_drift, root=ROOT)

    synthetic = copy.deepcopy(overlay)
    synthetic["fx_identity_contract"]["synthetic_cross_allowed"] = True
    _reseal(synthetic)
    with pytest.raises(ValueError, match="FX identity contract drift"):
        validate_macro_europe_preservation_overlay(synthetic, root=ROOT)

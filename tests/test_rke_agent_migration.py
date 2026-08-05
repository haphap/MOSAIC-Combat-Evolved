from __future__ import annotations

from mosaic.rke.agent_migration import (
    LEGACY_REFERENCE_INVENTORY,
    MIGRATION_INVENTORY_MODULES,
    NEW_AGENT_IDS,
    TOMBSTONED_AGENT_IDS,
    build_rke_shadow_agent_migration_manifest,
    validate_rke_shadow_agent_migration_manifest,
)
from mosaic.rke.agent_research_context import (
    build_rke_agent_research_context_from_rows,
)


def test_rke_shadow_migration_routes_fields_without_identity_aliases():
    manifest = validate_rke_shadow_agent_migration_manifest(
        build_rke_shadow_agent_migration_manifest()
    )

    assert manifest["execution_mode"] == "RKE_SHADOW"
    assert manifest["production_signal_allowed"] is False
    assert manifest["identity_aliases"] == []
    assert {row["agent_id"] for row in manifest["tombstoned_agent_ids"]} == set(
        TOMBSTONED_AGENT_IDS
    )
    assert {row["agent_id"] for row in manifest["new_agent_ids"]} == set(
        NEW_AGENT_IDS
    )
    assert set(manifest["covered_modules"]) == set(MIGRATION_INVENTORY_MODULES)
    assert {
        row["module_path"]: tuple(row["legacy_agent_ids"])
        for row in manifest["legacy_reference_inventory"]
    } == LEGACY_REFERENCE_INVENTORY
    assert all(
        row["legacy_artifact_status"] == "legacy_unverified"
        and row["current_routing_policy"]
        == "DATA_FIELD_ROUTES_ONLY_NO_IDENTITY_ALIAS"
        for row in manifest["legacy_reference_inventory"]
    )
    routes = {row["field_id"]: row for row in manifest["data_field_routes"]}
    assert routes["china_nominal_yield_curve"]["owner_agent_id"] == (
        "macro.central_bank"
    )
    assert routes["fed_policy"]["owner_agent_id"] == (
        "macro.us_financial_conditions"
    )
    assert routes["euro_area_ciss"]["owner_agent_id"] == (
        "macro.euro_area_financial_conditions"
    )
    assert routes["china_realized_volatility"]["owner_agent_id"] == "decision.cro"
    assert all(row["identity_alias"] is False for row in routes.values())


def test_rke_shadow_migration_rejects_old_identity_alias():
    manifest = build_rke_shadow_agent_migration_manifest()
    manifest["identity_aliases"] = [
        {"from": "macro.dollar", "to": "macro.us_financial_conditions"}
    ]

    try:
        validate_rke_shadow_agent_migration_manifest(manifest)
    except ValueError as exc:
        assert "cannot alias" in str(exc)
    else:
        raise AssertionError("identity alias must be rejected")


def test_rke_shadow_context_routes_fields_without_relabeling_legacy_identity():
    forecasts = [
        {
            "forecast_claim_id": "FC-FX-ROUTE",
            "report_id": "RPT-FX-ROUTE",
            "target": {
                "target_type": "macro_series",
                "target_id": "USDCNY",
                "metric_family": "fx_rate",
            },
            "direction": "positive",
        }
    ]
    metadata = [
        {
            "report_id": "RPT-FX-ROUTE",
            "report_type": "宏观策略",
            "publish_datetime": "2026-06-01T00:00:00+08:00",
        }
    ]

    current = build_rke_agent_research_context_from_rows(
        agent_id="us_financial_conditions",
        layer="macro",
        forecasts=forecasts,
        metadata=metadata,
    )
    legacy = build_rke_agent_research_context_from_rows(
        agent_id="dollar",
        layer="macro",
        forecasts=forecasts,
        metadata=metadata,
    )

    assert current["agent_id"] == "macro.us_financial_conditions"
    assert current["legacy_status"] is None
    assert current["summary"]["matched_item_count"] == 1
    assert legacy["agent_id"] == "macro.dollar"
    assert legacy["legacy_status"] == "legacy_unverified"
    assert legacy["summary"]["matched_item_count"] == 1
    assert current["production_signal_allowed"] is False
    assert legacy["production_signal_allowed"] is False

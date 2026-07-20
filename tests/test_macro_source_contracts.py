from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.dataflows.macro_source_contracts import (
    CHINA_MACRO_SERIES_MAP,
    COMMODITY_CONTRACT_MAP,
    COMMODITY_FAMILY_CONTRACTS,
    EURO_AREA_FINANCIAL_SERIES_MAP,
    EU_SERIES_MAP,
    FINANCIAL_REAL_ECONOMY_CONTEXT_MAP,
    FX_PAIR_ROLE_MAP,
    MACRO_ROLE_SOURCE_GAPS,
    MACRO_OBSERVATION_FRESHNESS_CONTRACTS,
    PBOC_SERIES_MAP,
    US_ECONOMY_SERIES_MAP,
    US_FINANCIAL_CONDITIONS_SERIES_MAP,
    WORLD_BANK_CONTEXT_MAP,
    assert_macro_role_sources_ready,
    macro_role_source_readiness,
    macro_observation_max_age_calendar_days,
    validate_macro_source_contracts,
)


def test_source_maps_have_exact_role_component_closure():
    validate_macro_source_contracts()
    assert set(CHINA_MACRO_SERIES_MAP) == {
        "growth_production",
        "prices",
        "credit",
        "external_demand_trade",
        "fiscal",
    }
    assert set(US_ECONOMY_SERIES_MAP) == {
        "growth_production",
        "prices",
        "employment",
        "demand_trade",
    }
    assert set(FINANCIAL_REAL_ECONOMY_CONTEXT_MAP) == {
        "us_financial_conditions",
        "euro_area_financial_conditions",
    }
    assert all(
        row["usage_mode"] == "CONTEXT_ONLY"
        and row["contributes_to_required_components"] is False
        and set(row["components"])
        == {"growth_production", "prices", "employment", "demand_trade"}
        for row in FINANCIAL_REAL_ECONOMY_CONTEXT_MAP.values()
    )
    assert set(US_FINANCIAL_CONDITIONS_SERIES_MAP) == {
        "fed_liquidity",
        "us_curve",
        "credit_financial_stress",
        "usd_rmb",
    }
    assert set(EURO_AREA_FINANCIAL_SERIES_MAP) == {
        "ecb_liquidity",
        "euro_area_curve",
        "bank_credit",
        "eur_financial_stress",
    }
    assert {row["component"] for row in EU_SERIES_MAP.values()} == {
        "growth_production",
        "prices",
        "employment",
        "demand_trade",
    }


def test_us_entity_and_financial_series_are_non_overlapping():
    entity = {series for rows in US_ECONOMY_SERIES_MAP.values() for series in rows}
    financial = {
        series
        for rows in US_FINANCIAL_CONDITIONS_SERIES_MAP.values()
        for series in rows
    }
    assert entity.isdisjoint(financial)
    assert {"GDPC1", "INDPRO", "PAYEMS", "UNRATE", "BOPGSTB"} <= entity
    assert {"DFII5", "DFII10", "BAA10Y", "NFCI", "VIXCLS", "DTWEXBGS"} <= (financial)


def test_all_macro_roles_fail_closed_without_operational_pit_proof():
    assert PBOC_SERIES_MAP["pboc_policy_stance"]["required_branches"] == (
        "official.pboc_mpc_meeting_catalog",
        "official.pboc_monetary_policy_report_catalog",
    )
    assert (
        "expected_next_release_at+15_calendar_days"
        in PBOC_SERIES_MAP["pboc_policy_stance"]["freshness_formula"]
    )
    assert FX_PAIR_ROLE_MAP["USD_CNY"]["instrument_id"] is None
    assert FX_PAIR_ROLE_MAP["EUR_CNY"]["instrument_id"] is None
    assert FX_PAIR_ROLE_MAP["EUR_USD"]["instrument_id"] == "EURUSD.FXCM"
    assert FX_PAIR_ROLE_MAP["USD_CNY"]["observed_excluded_candidates"] == (
        {
            "instrument_id": "USDCNH.FXCM",
            "reason": "offshore_CNH_is_not_onshore_CNY",
        },
    )
    assert all(
        row["status"] == "PREFLIGHT_REQUIRED" for row in FX_PAIR_ROLE_MAP.values()
    )
    assert FX_PAIR_ROLE_MAP["USD_CNY"]["role"] == "us_financial_conditions"
    assert FX_PAIR_ROLE_MAP["EUR_CNY"]["role"] == "euro_area_financial_conditions"
    assert set(MACRO_ROLE_SOURCE_GAPS) == {
        "china",
        "us_economy",
        "eu_economy",
        "central_bank",
        "us_financial_conditions",
        "euro_area_financial_conditions",
        "commodities",
        "institutional_flow",
    }
    for role in MACRO_ROLE_SOURCE_GAPS:
        assert macro_role_source_readiness(role) == {
            "role": role,
            "production_ready": False,
            "source_gaps": list(MACRO_ROLE_SOURCE_GAPS[role]),
            "implicit_fallback": False,
        }
        try:
            assert_macro_role_sources_ready(role)
        except RuntimeError as exc:
            assert str(exc).startswith(f"MACRO_ROLE_SOURCE_GAP:{role}:")
        else:
            raise AssertionError("required source gap must block production readiness")

    with pytest.raises(ValueError, match="unknown operational macro role"):
        macro_role_source_readiness("not_a_role")


def test_freshness_contracts_are_closed_and_pboc_hard_caps_are_executable():
    assert set(MACRO_OBSERVATION_FRESHNESS_CONTRACTS) == set(
        MACRO_ROLE_SOURCE_GAPS
    )
    assert macro_observation_max_age_calendar_days(
        "central_bank",
        source="official.pboc_omo_catalog",
        series_id="pboc_omo_net_injection",
    ) == 4
    assert macro_observation_max_age_calendar_days(
        "central_bank",
        source="official.pboc_lpr_catalog",
        series_id="pboc_lpr_1y",
    ) == 40
    assert macro_observation_max_age_calendar_days(
        "eu_economy",
        source="world_bank.eu_gdp_growth_context",
        series_id="world_bank_eu_gdp_growth",
    ) == 800
    with pytest.raises(ValueError, match="unregistered macro freshness contract"):
        macro_observation_max_age_calendar_days(
            "china",
            source="adjacent.current_feed",
            series_id="cn_gdp",
        )


def test_operational_gaps_match_committed_preflight_evidence():
    root = Path(__file__).resolve().parents[1]
    official = json.loads(
        (root / "registry/data_sources/official_macro_source_preflight_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert official["summary"]["production_snapshot_ready"] is False
    assert all(
        row.get("snapshot_readiness") != "PRODUCTION_READY"
        for row in official["checks"]
    )

    tushare = json.loads(
        (root / "registry/data_sources/tushare_endpoint_preflight_v2.json").read_text(
            encoding="utf-8"
        )
    )
    checks = {row["endpoint"]: row for row in tushare["checks"]}
    for endpoint in (
        "cn_gdp",
        "cn_pmi",
        "cn_cpi",
        "cn_ppi",
        "shibor",
        "us_tycr",
        "fx_daily",
        "fut_basic",
        "fut_daily",
        "fut_wsr",
        "moneyflow_ind_ths",
        "fund_share",
        "daily_basic",
    ):
        assert checks[endpoint]["status"] == "PRECHECK_REQUIRED"
        assert checks[endpoint]["pit_assessment"] == "LOCAL_CAPTURE_ONLY"
    assert set(checks["fut_wsr"]["expected_columns"]) == {
        "fut_name",
        "pre_vol",
        "symbol",
        "trade_date",
        "unit",
        "vol",
        "vol_chg",
        "warehouse",
    }
    assert checks["fut_wsr"]["observed_row_count"] > 0
    assert checks["fut_wsr"]["raw_payload_committed"] is False
    assert checks["yc_cb"]["status"] == "DISABLED_PERMISSION_DENIED"
    assert "moneyflow_hsgt" not in checks


def test_commodity_families_are_closed_and_world_bank_is_context_only():
    assert COMMODITY_CONTRACT_MAP["energy"]["required_families"] == ("SC@INE",)
    assert COMMODITY_CONTRACT_MAP["industrial_metals"]["required_families"] == (
        "CU@SHFE",
    )
    assert COMMODITY_CONTRACT_MAP["gold"]["required_families"] == ("AU@SHFE",)
    assert COMMODITY_CONTRACT_MAP["agriculture_food"]["required_families"] == (
        "C@DCE",
        "M@DCE",
    )
    all_families = {
        family
        for component in COMMODITY_CONTRACT_MAP.values()
        for family in (
            *component["required_families"],
            *component["optional_families"],
        )
    }
    assert set(COMMODITY_FAMILY_CONTRACTS) == all_families
    for family_id, contract in COMMODITY_FAMILY_CONTRACTS.items():
        assert contract["contract_metadata_endpoint"] == "fut_basic"
        assert contract["contract_metadata_source"] == (
            f"tushare.fut_basic.{family_id}"
        )
        assert contract["daily_settlement_endpoint"] == "fut_daily"
        assert contract["daily_settlement_source"] == (
            f"tushare.fut_daily.{family_id}"
        )
        assert contract["inventory_endpoint"] == "fut_wsr"
        assert contract["inventory_source"] == f"tushare.fut_wsr.{family_id}"
        assert contract["inventory_source_status"] == (
            "PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING"
        )
        assert contract["roll_rule"] == {
            "rule_id": "first_two_roll_eligible_by_delist_date_v1",
            "minimum_days_to_delist": 5,
            "minimum_tradable_contracts": 2,
            "price_field": "settle",
            "liquidity_fields": ("volume", "open_interest"),
        }
    assert all(
        row["required"] is False and row["usage_mode"] == "CONTEXT_ONLY"
        for row in WORLD_BANK_CONTEXT_MAP.values()
    )

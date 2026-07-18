from __future__ import annotations

from mosaic.dataflows.macro_source_contracts import (
    CHINA_MACRO_SERIES_MAP,
    COMMODITY_CONTRACT_MAP,
    EURO_AREA_FINANCIAL_SERIES_MAP,
    EU_SERIES_MAP,
    FX_PAIR_ROLE_MAP,
    PBOC_SERIES_MAP,
    US_ECONOMY_SERIES_MAP,
    US_FINANCIAL_CONDITIONS_SERIES_MAP,
    WORLD_BANK_CONTEXT_MAP,
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


def test_pboc_and_fx_contracts_fail_closed_without_verified_identity():
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
    assert all(
        row["required"] is False and row["usage_mode"] == "CONTEXT_ONLY"
        for row in WORLD_BANK_CONTEXT_MAP.values()
    )

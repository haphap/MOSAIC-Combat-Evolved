"""Closed source maps for the China-view macro roster.

These constants define identity and ownership only.  They do not activate a
source: runtime activation remains conditional on the endpoint/adapter
preflight ledger and point-in-time coverage for the requested date.
"""

from __future__ import annotations

from typing import Any, Final

MACRO_SOURCE_CONTRACT_VERSION: Final = "macro_source_contracts_v3"

CHINA_OFFICIAL_CATALOGS: Final = {
    "nbs_national_data": "https://data.stats.gov.cn/easyquery.htm",
    "china_customs_monthly": "https://english.customs.gov.cn/statics/report/monthly.html",
    "mof_fiscal_revenue_expenditure": "https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/",
}

PBOC_OFFICIAL_CATALOGS: Final = {
    "pboc_omo_catalog": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/index.html",
    "pboc_lpr_catalog": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/index.html",
    "pboc_mpc_meeting_catalog": "https://www.pbc.gov.cn/zhengcehuobisi/125207/3870933/3870936/index.html",
    "pboc_monetary_policy_report_catalog": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html",
    "pboc_statistics_release_catalog": "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html",
}

CHINA_MACRO_SERIES_MAP: Final[dict[str, dict[str, Any]]] = {
    "growth_production": {
        "series_family": "china_growth_production",
        "required_branches": (
            "tushare.cn_gdp",
            "tushare.cn_pmi",
            "official.nbs_industrial_value_added",
            "official.nbs_fixed_asset_investment",
            "official.nbs_retail_sales",
            "official.nbs_employment_release",
        ),
        "signal_owner": "china",
    },
    "prices": {
        "series_family": "china_prices",
        "required_branches": (
            "tushare.cn_cpi",
            "tushare.cn_ppi",
            "official.nbs_price_release_verification",
        ),
        "signal_owner": "china",
    },
    "credit": {
        "series_family": "china_credit_impulse_quantity",
        "required_branches": (
            "official.pboc_tsfin_flow_stock",
            "official.pboc_rmb_loans",
            "official.pboc_money_stock",
        ),
        "signal_owner": "china",
    },
    "external_demand_trade": {
        "series_family": "china_external_demand_trade",
        "required_branches": (
            "official.customs_total_trade",
            "official.customs_partner_trade",
            "official.customs_major_goods_trade",
        ),
        "signal_owner": "china",
    },
    "fiscal": {
        "series_family": "china_fiscal_impulse",
        "required_branches": (
            "official.mof_general_public_budget",
            "official.mof_government_fund_budget",
        ),
        "signal_owner": "china",
    },
}

PBOC_SERIES_MAP: Final[dict[str, dict[str, Any]]] = {
    "pboc_omo_operations": {
        "required_branches": ("official.pboc_omo_catalog",),
        "hard_cap": "next_pboc_workday_plus_2_workdays",
    },
    "pboc_lpr": {
        "required_branches": ("official.pboc_lpr_catalog",),
        "hard_cap": "40_calendar_days",
    },
    "pboc_policy_stance": {
        "required_branches": (
            "official.pboc_mpc_meeting_catalog",
            "official.pboc_monetary_policy_report_catalog",
        ),
        "freshness_formula": (
            "min(expected_next_release_at+15_calendar_days,"
            "first_published_at+150_calendar_days)"
        ),
    },
    "pboc_credit_money": {
        "required_branches": (
            "official.pboc_financial_statistics",
            "official.pboc_tsfin_flow_stock",
        ),
        "hard_cap": "50_calendar_days",
        "usage_mode": "CONTEXT_ONLY",
    },
    "china_money_market_curve": {
        "required_branches": (
            "tushare.shibor_overnight",
            "tushare.shibor_3m",
            "tushare.yc_cb_cn_government_2y",
            "tushare.yc_cb_cn_government_10y",
        ),
        "optional_branches": ("tushare.shibor_quote",),
    },
}

US_ECONOMY_SERIES_MAP: Final[dict[str, tuple[str, ...]]] = {
    "growth_production": ("GDPC1", "INDPRO"),
    "prices": ("CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE"),
    "employment": ("PAYEMS", "UNRATE"),
    "demand_trade": ("RSAFS", "BOPGSTB"),
}

US_FINANCIAL_CONDITIONS_SERIES_MAP: Final[dict[str, tuple[str, ...]]] = {
    "fed_liquidity": (
        "official.fomc_statement",
        "official.nyfed_effr",
        "official.nyfed_sofr",
    ),
    "us_curve": (
        "tushare.us_tycr_nominal_curve",
        "DFII5",
        "DFII10",
        "DFII30",
    ),
    "credit_financial_stress": ("BAA10Y", "NFCI", "VIXCLS"),
    "usd_rmb": ("DTWEXBGS", "tushare.fx_daily.USD_CNY"),
}

EU_SERIES_MAP: Final[dict[str, dict[str, str]]] = {
    "eu27_real_gdp": {
        "dataset": "namq_10_gdp",
        "dimensions": "geo=EU27_2020,na_item=B1GQ,unit=CLV10_MEUR,s_adj=SCA,freq=Q",
        "component": "growth_production",
    },
    "eu27_hicp": {
        "dataset": "prc_hicp_minr",
        "dimensions": "geo=EU27_2020,coicop18=TOTAL,unit=RCH_A,freq=M",
        "component": "prices",
    },
    "eu27_unemployment": {
        "dataset": "une_rt_m",
        "dimensions": "geo=EU27_2020,age=TOTAL,sex=T,unit=PC_ACT,s_adj=SA,freq=M",
        "component": "employment",
    },
    "eu27_industrial_production": {
        "dataset": "sts_inpr_m",
        "dimensions": "geo=EU27_2020,indic_bt=PRD,nace_r2=B-D,unit=I21,s_adj=SCA,freq=M",
        "component": "growth_production",
    },
    "eu27_retail_volume": {
        "dataset": "sts_trtu_m",
        "dimensions": "geo=EU27_2020,indic_bt=VOL_SLS,nace_r2=G47,unit=I21,s_adj=SCA,freq=M",
        "component": "demand_trade",
    },
    "eu27_external_exports": {
        "dataset": "ext_st_eu27_2020sitc",
        "dimensions": "geo=EU27_2020,partner=EXT_EU27_2020,sitc06=TOTAL,indic_et=TRD_VAL_SCA,stk_flow=EXP,freq=M",
        "component": "demand_trade",
    },
    "eu27_external_imports": {
        "dataset": "ext_st_eu27_2020sitc",
        "dimensions": "geo=EU27_2020,partner=EXT_EU27_2020,sitc06=TOTAL,indic_et=TRD_VAL_SCA,stk_flow=IMP,freq=M",
        "component": "demand_trade",
    },
}

EURO_AREA_FINANCIAL_SERIES_MAP: Final[dict[str, tuple[str, ...]]] = {
    "ecb_liquidity": (
        "official.ecb_decision_statement",
        "FM.B.U2.EUR.4F.KR.DFR.LEV",
        "FM.B.U2.EUR.4F.KR.MRR_FR.LEV",
        "EST.B.EU000A2X2A25.WT",
    ),
    "euro_area_curve": (
        "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y",
        "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
    ),
    "bank_credit": (
        "BSI.M.U2.Y.U.A20T.A.I.U2.2240.Z01.A",
        "MIR.M.U2.B.A2A.A.R.A.2240.EUR.N",
    ),
    "eur_financial_stress": (
        "EXR.D.USD.EUR.SP00.A",
        "CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX",
        "tushare.fx_daily.EUR_CNY",
    ),
}

FX_PAIR_ROLE_MAP: Final = {
    "USD_CNY": {
        "role": "us_financial_conditions",
        "base_currency": "USD",
        "quote_currency": "CNY",
        "instrument_id": None,
        "status": "PREFLIGHT_REQUIRED",
        "observed_excluded_candidates": (
            {
                "instrument_id": "USDCNH.FXCM",
                "reason": "offshore_CNH_is_not_onshore_CNY",
            },
        ),
    },
    "EUR_CNY": {
        "role": "euro_area_financial_conditions",
        "base_currency": "EUR",
        "quote_currency": "CNY",
        "instrument_id": None,
        "status": "PREFLIGHT_REQUIRED",
        "observed_excluded_candidates": (),
    },
    "EUR_USD": {
        "role": "euro_area_financial_conditions",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "instrument_id": "EURUSD.FXCM",
        "status": "PREFLIGHT_REQUIRED",
        "observed_excluded_candidates": (),
    },
}

COMMODITY_CONTRACT_MAP: Final = {
    "energy": {"required_families": ("SC@INE",), "optional_families": ("FU@SHFE",)},
    "industrial_metals": {
        "required_families": ("CU@SHFE",),
        "optional_families": ("AL@SHFE",),
    },
    "gold": {"required_families": ("AU@SHFE",), "optional_families": ()},
    "agriculture_food": {
        "required_families": ("C@DCE", "M@DCE"),
        "optional_families": (),
    },
}

WORLD_BANK_CONTEXT_MAP: Final = {
    "global_economic_monitor": {
        "source_id": 15,
        "required": False,
        "usage_mode": "CONTEXT_ONLY",
    },
    "world_development_indicators": {
        "source_id": 2,
        "required": False,
        "usage_mode": "CONTEXT_ONLY",
    },
    "quarterly_external_debt_statistics": {
        "source_id": "QEDS",
        "required": False,
        "usage_mode": "CONTEXT_ONLY",
    },
}


def validate_macro_source_contracts() -> None:
    if set(CHINA_MACRO_SERIES_MAP) != {
        "growth_production",
        "prices",
        "credit",
        "external_demand_trade",
        "fiscal",
    }:
        raise RuntimeError("China source map component closure mismatch")
    expected_four = {
        "growth_production",
        "prices",
        "employment",
        "demand_trade",
    }
    if set(US_ECONOMY_SERIES_MAP) != expected_four:
        raise RuntimeError("US economy source map component closure mismatch")
    if set(US_FINANCIAL_CONDITIONS_SERIES_MAP) != {
        "fed_liquidity",
        "us_curve",
        "credit_financial_stress",
        "usd_rmb",
    }:
        raise RuntimeError("US financial source map component closure mismatch")
    if {row["component"] for row in EU_SERIES_MAP.values()} != expected_four:
        raise RuntimeError("EU source map component closure mismatch")
    if set(EURO_AREA_FINANCIAL_SERIES_MAP) != {
        "ecb_liquidity",
        "euro_area_curve",
        "bank_credit",
        "eur_financial_stress",
    }:
        raise RuntimeError("euro-area source map component closure mismatch")
    if set(FX_PAIR_ROLE_MAP) != {"USD_CNY", "EUR_CNY", "EUR_USD"}:
        raise RuntimeError("FX pair role map closure mismatch")
    if any(
        row["required"] or row["usage_mode"] != "CONTEXT_ONLY"
        for row in WORLD_BANK_CONTEXT_MAP.values()
    ):
        raise RuntimeError("World Bank can only be optional context")
    forbidden = {"major_news", "news", "npr", "monetary_policy"}
    encoded = repr(
        (
            CHINA_MACRO_SERIES_MAP,
            PBOC_SERIES_MAP,
            US_ECONOMY_SERIES_MAP,
            US_FINANCIAL_CONDITIONS_SERIES_MAP,
            EU_SERIES_MAP,
            EURO_AREA_FINANCIAL_SERIES_MAP,
            COMMODITY_CONTRACT_MAP,
        )
    )
    if any(f"tushare.{source}" in encoded for source in forbidden):
        raise RuntimeError("permission-denied Tushare source leaked into required map")


validate_macro_source_contracts()


__all__ = [
    "CHINA_MACRO_SERIES_MAP",
    "CHINA_OFFICIAL_CATALOGS",
    "COMMODITY_CONTRACT_MAP",
    "EURO_AREA_FINANCIAL_SERIES_MAP",
    "EU_SERIES_MAP",
    "FX_PAIR_ROLE_MAP",
    "MACRO_SOURCE_CONTRACT_VERSION",
    "PBOC_OFFICIAL_CATALOGS",
    "PBOC_SERIES_MAP",
    "US_ECONOMY_SERIES_MAP",
    "US_FINANCIAL_CONDITIONS_SERIES_MAP",
    "WORLD_BANK_CONTEXT_MAP",
    "validate_macro_source_contracts",
]

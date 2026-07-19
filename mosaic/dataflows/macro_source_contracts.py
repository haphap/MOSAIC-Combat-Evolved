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

FINANCIAL_REAL_ECONOMY_CONTEXT_MAP: Final[dict[str, dict[str, Any]]] = {
    "us_financial_conditions": {
        "source_role": "us_economy",
        "usage_mode": "CONTEXT_ONLY",
        "required_for_snapshot": True,
        "contributes_to_required_components": False,
        "components": tuple(US_ECONOMY_SERIES_MAP),
    },
    "euro_area_financial_conditions": {
        "source_role": "eu_economy",
        "usage_mode": "CONTEXT_ONLY",
        "required_for_snapshot": True,
        "contributes_to_required_components": False,
        "components": (
            "growth_production",
            "prices",
            "employment",
            "demand_trade",
        ),
    },
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

def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


_CHINA_REQUIRED_BRANCHES = _ordered_unique(
    tuple(
        branch
        for contract in CHINA_MACRO_SERIES_MAP.values()
        for branch in contract["required_branches"]
    )
)
_PBOC_REQUIRED_BRANCHES = _ordered_unique(
    tuple(
        branch
        for contract in PBOC_SERIES_MAP.values()
        for branch in contract["required_branches"]
    )
)
_US_ECONOMY_REQUIRED_BRANCHES = tuple(
    series_id
    for series_ids in US_ECONOMY_SERIES_MAP.values()
    for series_id in series_ids
)
_US_FINANCIAL_REQUIRED_BRANCHES = _ordered_unique(
    tuple(
        branch
        for branches in US_FINANCIAL_CONDITIONS_SERIES_MAP.values()
        for branch in branches
    )
)
_EU_REQUIRED_BRANCHES = tuple(EU_SERIES_MAP)
_EURO_FINANCIAL_REQUIRED_BRANCHES = _ordered_unique(
    tuple(
        branch
        for branches in EURO_AREA_FINANCIAL_SERIES_MAP.values()
        for branch in branches
    )
)
_COMMODITY_REQUIRED_BRANCHES = tuple(
    family
    for contract in COMMODITY_CONTRACT_MAP.values()
    for family in contract["required_families"]
)

# A registered provider/series name is only an identity contract.  Production
# readiness additionally requires a concrete ingestion adapter and a
# release/vintage archive receipt.  No required role currently has that full
# proof chain in this public checkout, so every unresolved required branch is
# listed explicitly and formal snapshot construction remains fail closed.
MACRO_ROLE_SOURCE_GAPS: Final[dict[str, tuple[str, ...]]] = {
    "china": tuple(
        f"{branch}:"
        + (
            "PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING"
            if branch.startswith("tushare.")
            else "INGESTION_ADAPTER_AND_RELEASE_LEDGER_MISSING"
        )
        for branch in _CHINA_REQUIRED_BRANCHES
    ),
    "us_economy": tuple(
        f"ALFRED.{series_id}:ARCHIVED_VINTAGE_INGESTION_ADAPTER_MISSING"
        for series_id in _US_ECONOMY_REQUIRED_BRANCHES
    ),
    "eu_economy": tuple(
        f"eurostat.{series_key}:PREFLIGHT_ONLY_RELEASE_VINTAGE_JOIN_MISSING"
        for series_key in _EU_REQUIRED_BRANCHES
    ),
    "central_bank": tuple(
        f"{branch}:"
        + (
            "PERMISSION_DENIED"
            if branch.startswith("tushare.yc_cb_")
            else "PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING"
            if branch.startswith("tushare.")
            else "INGESTION_ADAPTER_AND_RELEASE_LEDGER_MISSING"
        )
        for branch in _PBOC_REQUIRED_BRANCHES
    ),
    "us_financial_conditions": tuple(
        f"{branch}:"
        + (
            "ARCHIVED_VINTAGE_INGESTION_ADAPTER_MISSING"
            if branch in {
                "DFII5",
                "DFII10",
                "DFII30",
                "BAA10Y",
                "NFCI",
                "VIXCLS",
                "DTWEXBGS",
            }
            else "PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING"
            if branch.startswith("tushare.")
            else "INGESTION_ADAPTER_AND_RELEASE_LEDGER_MISSING"
        )
        for branch in _US_FINANCIAL_REQUIRED_BRANCHES
    ),
    "euro_area_financial_conditions": tuple(
        f"{branch}:"
        + (
            "PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING"
            if branch.startswith("tushare.")
            else "INGESTION_ADAPTER_AND_RELEASE_LEDGER_MISSING"
            if branch.startswith("official.")
            else "PREFLIGHT_ONLY_RELEASE_VINTAGE_JOIN_MISSING"
        )
        for branch in _EURO_FINANCIAL_REQUIRED_BRANCHES
    ),
    "commodities": tuple(
        f"tushare.fut_daily.{family}:"
        "PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING"
        for family in _COMMODITY_REQUIRED_BRANCHES
    ),
    "institutional_flow": (
        "tushare.moneyflow_hsgt:ENDPOINT_NOT_IN_PREFLIGHT_REGISTRY",
        "tushare.moneyflow_ind_ths:PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING",
        "tushare.fund_share:PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING",
        "tushare.daily_basic:PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING",
    ),
}

# Exact provider/endpoint identities allowed to contribute an observation to
# each role component.  A provider root such as ``tushare`` or ``official`` is
# deliberately insufficient: snapshots must preserve the registered endpoint
# identity so an adjacent feed cannot be substituted silently.
MACRO_OBSERVATION_SOURCE_COMPONENTS: Final[
    dict[str, dict[str, frozenset[str]]]
] = {
    "china": {
        source: frozenset({component})
        for component, contract in CHINA_MACRO_SERIES_MAP.items()
        for source in contract["required_branches"]
    },
    "us_economy": {
        "ALFRED": frozenset(US_ECONOMY_SERIES_MAP),
    },
    "eu_economy": {
        f"eurostat.{contract['dataset']}": frozenset({contract["component"]})
        for contract in EU_SERIES_MAP.values()
    }
    | {
        "world_bank.eu_gdp_growth_context": frozenset(),
        "world_bank.eu_cpi_context": frozenset(),
        "world_bank.eu_unemployment_context": frozenset(),
    },
    "central_bank": {
        "official.pboc_omo_catalog": frozenset(
            {"pboc_policy_bias", "liquidity_money_market"}
        ),
        "official.pboc_lpr_catalog": frozenset({"pboc_policy_bias"}),
        "official.pboc_mpc_meeting_catalog": frozenset({"pboc_policy_bias"}),
        "official.pboc_monetary_policy_report_catalog": frozenset(
            {"pboc_policy_bias"}
        ),
        "official.pboc_financial_statistics": frozenset({"credit_conditions"}),
        "official.pboc_tsfin_flow_stock": frozenset({"credit_conditions"}),
        "tushare.shibor_overnight": frozenset({"liquidity_money_market"}),
        "tushare.shibor_3m": frozenset({"liquidity_money_market"}),
        "tushare.yc_cb_cn_government_2y": frozenset({"china_curve"}),
        "tushare.yc_cb_cn_government_10y": frozenset({"china_curve"}),
    },
    "us_financial_conditions": {
        source: frozenset({component})
        for component, sources in US_FINANCIAL_CONDITIONS_SERIES_MAP.items()
        for source in sources
        if source not in {"DFII5", "DFII10", "DFII30", "BAA10Y", "NFCI", "VIXCLS", "DTWEXBGS"}
    }
    | {"ALFRED": frozenset(US_FINANCIAL_CONDITIONS_SERIES_MAP)},
    "euro_area_financial_conditions": {
        (
            source
            if source.startswith(("official.", "tushare."))
            else f"ecb.{source}"
        ): frozenset({component})
        for component, sources in EURO_AREA_FINANCIAL_SERIES_MAP.items()
        for source in sources
    },
    "commodities": {
        f"tushare.fut_daily.{family}": frozenset({component})
        for component, contract in COMMODITY_CONTRACT_MAP.items()
        for family in (*contract["required_families"], *contract["optional_families"])
    },
    "institutional_flow": {
        "tushare.moneyflow_hsgt": frozenset({"market_wide_flow"}),
        "tushare.moneyflow_ind_ths": frozenset({"sector_rotation"}),
        "tushare.fund_share": frozenset({"etf_share"}),
        "tushare.daily_basic": frozenset({"crowding"}),
    },
}


def macro_role_source_readiness(role: str) -> dict[str, Any]:
    if role not in MACRO_ROLE_SOURCE_GAPS:
        raise ValueError(f"unknown operational macro role: {role!r}")
    gaps = MACRO_ROLE_SOURCE_GAPS[role]
    return {
        "role": role,
        "production_ready": not gaps,
        "source_gaps": list(gaps),
        "implicit_fallback": False,
    }


def assert_macro_role_sources_ready(role: str) -> None:
    readiness = macro_role_source_readiness(role)
    if not readiness["production_ready"]:
        raise RuntimeError(
            f"MACRO_ROLE_SOURCE_GAP:{role}:" + ",".join(readiness["source_gaps"])
        )


def validate_macro_source_contracts() -> None:
    operational_roles = {
        "china",
        "us_economy",
        "eu_economy",
        "central_bank",
        "us_financial_conditions",
        "euro_area_financial_conditions",
        "commodities",
        "institutional_flow",
    }
    if set(MACRO_ROLE_SOURCE_GAPS) != operational_roles:
        raise RuntimeError("macro operational readiness role closure mismatch")
    if any(
        not gaps or len(gaps) != len(set(gaps))
        for gaps in MACRO_ROLE_SOURCE_GAPS.values()
    ):
        raise RuntimeError("macro operational source gaps must be non-empty and unique")
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
    if set(FINANCIAL_REAL_ECONOMY_CONTEXT_MAP) != {
        "us_financial_conditions",
        "euro_area_financial_conditions",
    } or any(
        row["usage_mode"] != "CONTEXT_ONLY"
        or row["contributes_to_required_components"] is not False
        or set(row["components"]) != expected_four
        for row in FINANCIAL_REAL_ECONOMY_CONTEXT_MAP.values()
    ):
        raise RuntimeError("financial real-economy context-only contract mismatch")
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
    "FINANCIAL_REAL_ECONOMY_CONTEXT_MAP",
    "EU_SERIES_MAP",
    "FX_PAIR_ROLE_MAP",
    "MACRO_SOURCE_CONTRACT_VERSION",
    "MACRO_ROLE_SOURCE_GAPS",
    "MACRO_OBSERVATION_SOURCE_COMPONENTS",
    "PBOC_OFFICIAL_CATALOGS",
    "PBOC_SERIES_MAP",
    "US_ECONOMY_SERIES_MAP",
    "US_FINANCIAL_CONDITIONS_SERIES_MAP",
    "WORLD_BANK_CONTEXT_MAP",
    "assert_macro_role_sources_ready",
    "macro_role_source_readiness",
    "validate_macro_source_contracts",
]

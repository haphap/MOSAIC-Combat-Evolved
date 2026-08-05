from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_snapshots import (
    ALFRED_SERIES_MAP,
    ALFRED_SERIES_ROLE_MAP,
    MACRO_SNAPSHOT_SCHEMA_VERSION,
    mark_legacy_macro_output,
    load_role_snapshot,
    validate_role_snapshot,
    write_registered_role_snapshot,
)
from scripts.build_structured_smoke_fixtures import _synthetic_commodity_conditions


ROLE_SERIES = {
    "china": ("cn_gdp", "cn_cpi", "cn_credit", "cn_export", "cn_fiscal"),
    "us_economy": ("GDPC1", "CPIAUCSL", "PAYEMS", "RSAFS"),
    "eu_economy": ("eu_gdp", "eu_hicp", "eu_unemployment", "eu_retail"),
    "central_bank": (
        "pboc_omo_net_injection",
        "domestic_liquidity_dr007",
        "cn_curve_10y",
        "credit_condition_spread",
    ),
    "us_financial_conditions": (
        "fed_balance_sheet",
        "us_curve_2s10s",
        "BAA10Y",
        "DTWEXBGS",
    ),
    "euro_area_financial_conditions": (
        "ecb_deposit_rate",
        "euro_area_curve_2s10s",
        "euro_area_bank_credit_growth",
        "eur_financial_stress",
    ),
    "commodities": (
        "energy_crude_oil",
        "industrial_metal_copper",
        "gold_spot",
        "agriculture_food_basket",
    ),
    "geopolitical": ("geopolitical_event_severity",),
    "institutional_flow": (
        "market_flow_net_amount",
        "sector_rotation_net_amount",
        "etf_share_change",
        "crowding_concentration",
    ),
}

INSTITUTIONAL_FLOW_COVERAGE = {
    component: {"eligible_count": 100, "observed_count": 95, "coverage_ratio": 0.95}
    for component in ("market_wide_flow", "sector_rotation", "etf_share", "crowding")
}
FINANCIAL_CONTEXT_ROLE = {
    "central_bank": "china",
    "us_financial_conditions": "us_economy",
    "euro_area_financial_conditions": "eu_economy",
}

_SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"


def _role_event_snapshot(role: str) -> dict[str, object]:
    return {
        "role_event_snapshot_id": f"role-event-snapshot:{'1' * 64}",
        "schema_version": "role_event_snapshot_v2",
        "consumer_agent": role,
        "as_of": "2024-06-30T15:00:00+08:00",
        "contract_version": "role_event_coverage_v2",
        "coverage": {
            "coverage_state": "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT",
            "event_presence_state": "NO_MATERIAL_EVENT_OBSERVED",
            "coverage_completeness": "COMPLETE",
            "coverage_as_of": "2024-06-30T15:00:00+08:00",
            "query_complete": True,
            "required_route_ids": ["tushare.eco_cal"],
            "healthy_route_ids": ["tushare.eco_cal"],
            "unhealthy_route_ids": [],
            "coverage_evidence_ids": ["coverage:tushare.eco_cal:2024-06-30"],
            "material_event_revision_ids": [],
            "coverage_contract_version": "role_event_coverage_v2",
        },
        "projections": [],
        "role_event_snapshot_hash": f"sha256:{'2' * 64}",
    }


def _assert_active_snapshot_schema(snapshot: dict[str, object]) -> None:
    schema = json.loads(
        (_SCHEMA_ROOT / "macro_role_snapshot_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    role_event_schema = json.loads(
        (_SCHEMA_ROOT / "role_event_snapshot_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    commodity_schema = json.loads(
        (_SCHEMA_ROOT / "commodity_conditions_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    registry = (
        Registry()
        .with_resource(
            "role_event_snapshot_v2.schema.json",
            Resource.from_contents(role_event_schema),
        )
        .with_resource(
            "commodity_conditions_v1.schema.json",
            Resource.from_contents(commodity_schema),
        )
    )
    Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(snapshot)


def source_for(role: str, series_id: str) -> str:
    if role == "us_economy" or series_id in ALFRED_SERIES_ROLE_MAP:
        return "ALFRED"
    prefixes = {
        "china": {
            "cn_gdp": "tushare.cn_gdp",
            "cn_cpi": "tushare.cn_cpi",
            "cn_credit": "official.pboc_tsfin_flow_stock",
            "cn_export": "official.customs_total_trade",
            "cn_fiscal": "official.mof_general_public_budget",
        },
        "eu_economy": {
            "eu_gdp": "eurostat.namq_10_gdp",
            "eu_hicp": "eurostat.prc_hicp_minr",
            "eu_unemployment": "eurostat.une_rt_m",
            "eu_retail": "eurostat.sts_trtu_m",
        },
        "central_bank": {
            "pboc_": "official.pboc_omo_catalog",
            "domestic_liquidity_": "tushare.shibor_overnight",
            "cn_curve_": "tushare.yc_cb_cn_government_10y",
            "credit_condition_": "official.pboc_tsfin_flow_stock",
        },
        "us_financial_conditions": {
            "fed_": "official.fomc_statement",
            "us_curve_": "tushare.us_tycr_nominal_curve",
            "us_credit_": "ALFRED",
            "broad_dollar_": "ALFRED",
        },
        "euro_area_financial_conditions": {
            "ecb_": "official.ecb_decision_statement",
            "euro_area_curve_": "ecb.YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
            "euro_area_bank_credit_": "ecb.BSI.M.U2.Y.U.A20T.A.I.U2.2240.Z01.A",
            "eur_": "ecb.CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX",
        },
        "commodities": {
            "energy_": "tushare.fut_daily.SC@INE",
            "industrial_metal_": "tushare.fut_daily.CU@SHFE",
            "gold_": "tushare.fut_daily.AU@SHFE",
            "agriculture_": "tushare.fut_daily.C@DCE",
        },
        "institutional_flow": {
            "market_flow_": "tushare.moneyflow_hsgt",
            "sector_rotation_": "tushare.moneyflow_ind_ths",
            "etf_share_": "tushare.fund_share",
            "crowding_": "tushare.daily_basic",
        },
    }
    for prefix, source in prefixes[role].items():
        if series_id.casefold().startswith(prefix):
            return source
    raise AssertionError(f"no source fixture for {role}/{series_id}")


def observation(**overrides):
    row = {
        "series_id": "cn_cpi",
        "period_start": "2024-05-01",
        "period_end": "2024-05-31",
        "released_at": "2024-06-28T01:30:00Z",
        "vintage_at": "2024-06-28T01:30:00Z",
        "actual": 0.3,
        "previous": 0.3,
        "expected": 0.4,
        "unit": "percent_yoy",
        "source": "tushare.cn_cpi",
        "pit_status": "AVAILABLE_AS_OF",
        "evidence_id": "macro:cn_cpi:2024-05:20240628",
    }
    row.update(overrides)
    if "evidence_id" not in overrides:
        row["evidence_id"] = f"macro:{row['series_id']}:2024-05:20240628"
    return row


def payload(role="china", **overrides):
    observations = overrides.pop("observations", None)
    context_observations = overrides.pop("context_observations", None)
    if observations is None:
        observations = [
            observation(
                series_id=series_id,
                source=source_for(role, series_id),
            )
            for series_id in ROLE_SERIES[role]
        ]
    value = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": role,
        "as_of_date": "2024-06-30",
        "observations": observations,
        "events": [],
        **(
            {"commodity_conditions": _synthetic_commodity_conditions(date(2024, 6, 30))}
            if role == "commodities"
            else {}
        ),
        **(
            {"component_coverage": INSTITUTIONAL_FLOW_COVERAGE}
            if role == "institutional_flow"
            else {}
        ),
        **(
            {
                "context_observations": (
                    context_observations
                    if context_observations is not None
                    else [
                        observation(
                            series_id=series_id,
                            source=source_for(
                                FINANCIAL_CONTEXT_ROLE[role], series_id
                            ),
                        )
                        for series_id in (
                            ROLE_SERIES["china"][:3]
                            if role == "central_bank"
                            else ROLE_SERIES[FINANCIAL_CONTEXT_ROLE[role]]
                        )
                    ]
                )
            }
            if role in FINANCIAL_CONTEXT_ROLE
            else {}
        ),
    }
    value.update(overrides)
    return value


def test_snapshot_contract_keeps_release_vintage_surprise_and_evidence_fields():
    result = validate_role_snapshot(payload(), "china", "2024-06-30")
    row = result["observations"][0]
    assert set(row) == {
        "series_id",
        "period_start",
        "period_end",
        "released_at",
        "vintage_at",
        "actual",
        "previous",
        "expected",
        "unit",
        "source",
        "pit_status",
        "evidence_id",
    }
    assert result["snapshot_hash"].startswith("sha256:")
    assert len(result["snapshot_hash"]) == 71
    json.dumps(result)


def test_active_snapshot_schema_accepts_institutional_flow_tool_payload():
    snapshot = validate_role_snapshot(
        payload(role="institutional_flow"),
        "institutional_flow",
        "2024-06-30",
    )
    _assert_active_snapshot_schema(snapshot)


@pytest.mark.parametrize(
    "role",
    ["central_bank", "us_financial_conditions", "commodities"],
)
def test_active_snapshot_schema_accepts_loaded_event_bound_tool_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
):
    path = tmp_path / "2024-06-30" / f"{role}.json"
    path.parent.mkdir(parents=True)
    value = payload(role=role)
    value["fixture_class"] = "SYNTHETIC_NON_PRODUCTION"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    monkeypatch.setattr(
        "mosaic.dataflows.macro_snapshots.build_role_event_snapshot",
        lambda consumer_agent, _as_of_date: _role_event_snapshot(consumer_agent),
    )

    snapshot = load_role_snapshot(role, "2024-06-30", root=tmp_path)

    _assert_active_snapshot_schema(snapshot)


def test_commodities_snapshot_requires_deterministic_curve_and_inventory_inputs():
    missing = payload(role="commodities")
    del missing["commodity_conditions"]
    with pytest.raises(DataVendorUnavailable, match="top-level fields mismatch"):
        validate_role_snapshot(missing, "commodities", "2024-06-30")

    accepted = validate_role_snapshot(
        payload(role="commodities"), "commodities", "2024-06-30"
    )
    assert set(accepted["commodity_conditions"]["families"]) == {
        "SC@INE",
        "CU@SHFE",
        "AU@SHFE",
        "C@DCE",
        "M@DCE",
    }
    assert all(
        family["term_structure"]["state"] in {
            "CONTANGO",
            "BACKWARDATION",
            "FLAT",
        }
        for family in accepted["commodity_conditions"]["families"].values()
    )


@pytest.mark.parametrize("field", ["released_at", "vintage_at"])
def test_future_release_or_vintage_is_rejected(field):
    bad = payload(observations=[observation(**{field: "2024-07-01T00:00:00Z"})])
    with pytest.raises(DataVendorUnavailable, match="future macro observation"):
        validate_role_snapshot(bad, "china", "2024-06-30")


def test_observation_contract_rejects_extra_fields_future_period_and_bad_values():
    extra = observation()
    extra["claim_text"] = "must not cross the snapshot boundary"
    with pytest.raises(DataVendorUnavailable, match="fields mismatch"):
        validate_role_snapshot(payload(observations=[extra]), "china", "2024-06-30")

    with pytest.raises(DataVendorUnavailable, match="start <= end <= as_of"):
        validate_role_snapshot(
            payload(observations=[observation(period_end="2024-07-01")]),
            "china",
            "2024-06-30",
        )
    with pytest.raises(DataVendorUnavailable, match="finite number"):
        validate_role_snapshot(
            payload(observations=[observation(actual=float("nan"))]),
            "china",
            "2024-06-30",
        )


def test_release_must_not_follow_its_declared_vintage():
    with pytest.raises(DataVendorUnavailable, match="released_at <= vintage_at"):
        validate_role_snapshot(
            payload(
                observations=[
                    observation(
                        released_at="2024-06-12T02:00:00Z",
                        vintage_at="2024-06-12T01:30:00Z",
                    )
                ]
            ),
            "china",
            "2024-06-30",
        )


@pytest.mark.parametrize("field", ["released_at", "vintage_at"])
def test_next_china_local_day_is_rejected_even_when_utc_date_matches(field):
    bad = payload(observations=[observation(**{field: "2024-07-01T07:00:00+08:00"})])
    with pytest.raises(DataVendorUnavailable, match="future macro observation"):
        validate_role_snapshot(bad, "china", "2024-06-30")


@pytest.mark.parametrize("field", ["released_at", "vintage_at"])
def test_same_day_observation_after_a_share_decision_cutoff_is_rejected(field):
    rows = payload()["observations"]
    rows[0] = {**rows[0], field: "2024-06-30T15:00:01+08:00"}
    with pytest.raises(DataVendorUnavailable, match="future macro observation"):
        validate_role_snapshot(
            payload(observations=rows), "china", "2024-06-30"
        )


@pytest.mark.parametrize("field", ["released_at", "vintage_at"])
def test_release_and_vintage_require_explicit_timezone(field):
    bad = payload(observations=[observation(**{field: "2024-06-12T01:30:00"})])
    with pytest.raises(DataVendorUnavailable, match="timezone offset"):
        validate_role_snapshot(bad, "china", "2024-06-30")


def test_unregistered_alfred_series_has_no_implicit_fallback():
    bad = payload(
        role="us_economy",
        observations=[observation(series_id="UNREGISTERED", source="ALFRED")],
    )
    with pytest.raises(DataVendorUnavailable, match="unregistered ALFRED"):
        validate_role_snapshot(bad, "us_economy", "2024-06-30")
    assert {row["series_id"] for row in ALFRED_SERIES_MAP.values()} >= {
        "GDPC1",
        "PAYEMS",
        "CPIAUCSL",
        "PCEPI",
    }


def test_role_snapshot_rejects_cross_role_series():
    bad = payload(
        role="central_bank",
        observations=[
            observation(
                series_id="cn_cpi", source="official.pboc_omo_catalog"
            )
        ],
    )
    with pytest.raises(
        DataVendorUnavailable, match="outside the central_bank snapshot contract"
    ):
        validate_role_snapshot(bad, "central_bank", "2024-06-30")


@pytest.mark.parametrize(
    ("role", "foreign_series"),
    [
        ("china", "cn_policy_rate"),
        ("us_economy", "us_curve_2s10s"),
    ],
)
def test_complete_snapshot_rejects_extra_series_owned_by_another_role(
    role, foreign_series
):
    rows = payload(role=role)["observations"]
    rows.append(
        observation(
            series_id=foreign_series,
            source=source_for(role, ROLE_SERIES[role][0]),
        )
    )
    with pytest.raises(DataVendorUnavailable, match="outside|unregistered ALFRED"):
        validate_role_snapshot(
            payload(role=role, observations=rows), role, "2024-06-30"
        )


def test_central_bank_snapshot_is_pboc_and_domestic_liquidity_only():
    accepted = payload(role="central_bank")
    snapshot = validate_role_snapshot(accepted, "central_bank", "2024-06-30")
    assert snapshot["observations"]
    context = snapshot["context_only_projection"]
    assert context["source_role"] == "china"
    assert context["contributes_to_required_components"] is False
    assert set(context["component_summaries"]) == {
        "growth_production",
        "prices",
        "credit",
    }
    assert set(snapshot["component_data_quality"]) == {
        "pboc_policy_bias",
        "liquidity_money_market",
        "china_curve",
        "credit_conditions",
    }

    for forbidden in ("fed_policy_rate", "policy_divergence_index", "us_price_summary"):
        bad = payload(
            role="central_bank",
            observations=[
                observation(
                    series_id=forbidden,
                    source="official.pboc_omo_catalog",
                )
            ],
        )
        with pytest.raises(DataVendorUnavailable, match="outside|does not map"):
            validate_role_snapshot(bad, "central_bank", "2024-06-30")


def test_stale_required_macro_components_cannot_become_current_or_neutral():
    stale_china = payload(as_of_date="2026-07-20")
    with pytest.raises(DataVendorUnavailable, match="no fresh registered release"):
        validate_role_snapshot(stale_china, "china", "2026-07-20")

    stale_pboc = payload(role="central_bank", as_of_date="2024-07-05")
    with pytest.raises(DataVendorUnavailable, match="no fresh registered release"):
        validate_role_snapshot(stale_pboc, "central_bank", "2024-07-05")


def test_alfred_series_use_exact_role_ownership_without_cross_role_fallback():
    bad = payload(observations=[observation(series_id="GDPC1", source="ALFRED")])
    with pytest.raises(DataVendorUnavailable, match="belongs to us_economy, not china"):
        validate_role_snapshot(bad, "china", "2024-06-30")
    financial = payload(
        role="us_financial_conditions",
        observations=[
            observation(
                series_id="fed_balance_sheet", source="official.fomc_statement"
            ),
            observation(series_id="DFII10", source="ALFRED"),
            observation(series_id="NFCI", source="ALFRED"),
            observation(series_id="DTWEXBGS", source="ALFRED"),
        ],
    )
    accepted = validate_role_snapshot(
        financial, "us_financial_conditions", "2024-06-30"
    )
    assert {row["series_id"] for row in accepted["observations"]} == {
        "fed_balance_sheet",
        "DFII10",
        "NFCI",
        "DTWEXBGS",
    }
    assert ALFRED_SERIES_ROLE_MAP["VIXCLS"] == "us_financial_conditions"


@pytest.mark.parametrize(
    ("role", "source_role"),
    [
        ("us_financial_conditions", "us_economy"),
        ("euro_area_financial_conditions", "eu_economy"),
    ],
)
def test_financial_snapshots_expose_complete_real_economy_context_only(
    role, source_role
):
    accepted = validate_role_snapshot(payload(role=role), role, "2024-06-30")
    projection = accepted["context_only_projection"]
    assert projection["usage_mode"] == "CONTEXT_ONLY"
    assert projection["source_role"] == source_role
    assert projection["contributes_to_required_components"] is False
    assert set(projection["component_summaries"]) == {
        "growth_production",
        "prices",
        "employment",
        "demand_trade",
    }
    for component, summary in projection["component_summaries"].items():
        assert summary["component"] == component
        assert summary["source_role"] == source_role
        assert summary["usage_mode"] == "CONTEXT_ONLY"
        assert summary["contributes_to_required_components"] is False
    assert projection["projection_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("role", "forged_source_role"),
    [
        ("central_bank", "us_economy"),
        ("us_financial_conditions", "china"),
    ],
)
def test_context_projection_schema_rejects_source_family_component_mismatch(
    role, forged_source_role
):
    snapshot = validate_role_snapshot(payload(role=role), role, "2024-06-30")
    snapshot["role_event_snapshot"] = _role_event_snapshot(role)
    snapshot["context_only_projection"]["source_role"] = forged_source_role

    with pytest.raises(ValidationError):
        _assert_active_snapshot_schema(snapshot)


@pytest.mark.parametrize(
    "role", ["us_financial_conditions", "euro_area_financial_conditions"]
)
def test_context_only_economy_data_cannot_satisfy_financial_components(role):
    context = payload(role=role)["context_observations"]
    with pytest.raises(DataVendorUnavailable, match="no accepted evidence"):
        validate_role_snapshot(
            payload(role=role, observations=[], context_observations=context),
            role,
            "2024-06-30",
        )
    with pytest.raises(DataVendorUnavailable, match="missing required components"):
        validate_role_snapshot(
            payload(
                role=role,
                observations=payload(role=role)["observations"][:-1],
                context_observations=context,
            ),
            role,
            "2024-06-30",
        )


def test_generic_macro_snapshots_cannot_embed_event_prose():
    event = {
        "event_id": "event-1",
        "published_at": "2024-06-20T02:00:00Z",
        "source": "gdelt_event_gkg",
        "content_hash": "sha256:abc",
        "title": "policy event",
        "evidence_id": "event:event-1",
    }
    for role in ("geopolitical", "china"):
        denied = payload(role=role, observations=[], events=[event])
        with pytest.raises(DataVendorUnavailable, match="cannot embed event prose"):
            validate_role_snapshot(denied, role, "2024-06-30")


def test_geopolitical_uses_dedicated_registry_snapshot_contract():
    with pytest.raises(DataVendorUnavailable, match="GeopoliticalEventsSnapshot"):
        validate_role_snapshot(
            payload(role="geopolitical", observations=[], events=[]),
            "geopolitical",
            "2024-06-30",
        )


def test_observations_reject_news_and_unregistered_sources():
    news = payload(observations=[observation(source="gdelt_event_gkg")])
    with pytest.raises(DataVendorUnavailable, match="event library|unapproved"):
        validate_role_snapshot(news, "china", "2024-06-30")

    unknown = payload(observations=[observation(source="unregistered_vendor")])
    with pytest.raises(
        DataVendorUnavailable, match="unregistered macro observation source identity"
    ):
        validate_role_snapshot(unknown, "china", "2024-06-30")

    wrong_endpoint = payload(
        observations=[
            observation(series_id="cn_cpi", source="tushare.cn_gdp")
        ]
    )
    with pytest.raises(DataVendorUnavailable, match="not registered for china/prices"):
        validate_role_snapshot(wrong_endpoint, "china", "2024-06-30")


@pytest.mark.parametrize(
    "role",
    [
        "china",
        "us_economy",
        "eu_economy",
        "central_bank",
        "us_financial_conditions",
        "euro_area_financial_conditions",
        "commodities",
        "institutional_flow",
    ],
)
def test_registered_snapshot_builder_rejects_identity_only_sources(tmp_path, role):
    with pytest.raises(DataVendorUnavailable, match=f"MACRO_ROLE_SOURCE_GAP:{role}"):
        write_registered_role_snapshot(
            role=role,
            as_of_date="2024-06-30",
            observations=payload(role=role)["observations"],
            component_coverage=(
                INSTITUTIONAL_FLOW_COVERAGE
                if role == "institutional_flow"
                else None
            ),
            root=tmp_path,
        )
    assert not (tmp_path / "2024-06-30" / f"{role}.json").exists()


def test_institutional_flow_requires_all_four_market_components():
    accepted = validate_role_snapshot(
        payload(role="institutional_flow"), "institutional_flow", "2024-06-30"
    )
    assert accepted["direct_data_quality"] == pytest.approx(0.95)
    assert set(accepted["component_coverage"]) == set(INSTITUTIONAL_FLOW_COVERAGE)

    for series in (
        ["lhb_sampled_stock"],
        ["market_flow_net_amount"],
        [
            "market_flow_net_amount",
            "sector_rotation_net_amount",
            "etf_share_change",
        ],
    ):
        with pytest.raises(DataVendorUnavailable, match="missing required components|does not map"):
            validate_role_snapshot(
                payload(
                    role="institutional_flow",
                    observations=[
                        observation(
                            series_id=item,
                            source=(
                                "tushare.moneyflow_hsgt"
                                if item == "lhb_sampled_stock"
                                else source_for("institutional_flow", item)
                            ),
                        )
                        for item in series
                    ],
                ),
                "institutional_flow",
                "2024-06-30",
            )


def test_institutional_flow_coverage_is_exact_and_fail_closed():
    missing = dict(INSTITUTIONAL_FLOW_COVERAGE)
    missing.pop("crowding")
    with pytest.raises(DataVendorUnavailable, match="must match"):
        validate_role_snapshot(
            payload(role="institutional_flow", component_coverage=missing),
            "institutional_flow",
            "2024-06-30",
        )

    low = {key: dict(value) for key, value in INSTITUTIONAL_FLOW_COVERAGE.items()}
    low["etf_share"] = {
        "eligible_count": 100,
        "observed_count": 89,
        "coverage_ratio": 0.89,
    }
    with pytest.raises(DataVendorUnavailable, match="below readiness threshold"):
        validate_role_snapshot(
            payload(role="institutional_flow", component_coverage=low),
            "institutional_flow",
            "2024-06-30",
        )

    inconsistent = {
        key: dict(value) for key, value in INSTITUTIONAL_FLOW_COVERAGE.items()
    }
    inconsistent["market_wide_flow"]["coverage_ratio"] = 1.0
    with pytest.raises(DataVendorUnavailable, match="inconsistent"):
        validate_role_snapshot(
            payload(role="institutional_flow", component_coverage=inconsistent),
            "institutional_flow",
            "2024-06-30",
        )


def test_unverified_required_source_branch_blocks_production_load(tmp_path: Path):
    role = "central_bank"
    path = tmp_path / "2024-06-30" / f"{role}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload(role=role)), encoding="utf-8")
    with pytest.raises(DataVendorUnavailable, match="MACRO_ROLE_SOURCE_GAP:central_bank"):
        load_role_snapshot(role, "2024-06-30", root=tmp_path)


def test_structured_smoke_gap_bypass_requires_explicit_fixture_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    role = "central_bank"
    path = tmp_path / "2024-06-30" / f"{role}.json"
    path.parent.mkdir(parents=True)
    value = payload(role=role)
    value["fixture_class"] = "SYNTHETIC_NON_PRODUCTION"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    monkeypatch.setattr(
        "mosaic.dataflows.macro_snapshots.build_role_event_snapshot",
        lambda *_args: {
            "coverage": {"coverage_completeness": "COMPLETE"},
            "role_event_snapshot_hash": "sha256:fixture",
        },
    )
    assert load_role_snapshot(role, "2024-06-30", root=tmp_path)["role"] == role


def test_event_library_input_is_not_accepted_through_generic_macro_contract():
    first = {
        "event_id": "event-1",
        "published_at": "2024-06-20T02:00:00Z",
        "source": "gdelt_event_gkg",
        "content_hash": "sha256:abc",
        "title": "policy event",
        "evidence_id": "event:event-1",
    }
    duplicate = {**first, "event_id": "event-2", "evidence_id": "event:event-2"}
    with pytest.raises(DataVendorUnavailable, match="cannot embed event prose"):
        validate_role_snapshot(
            payload(role="geopolitical", observations=[], events=[first, duplicate]),
            "geopolitical",
            "2024-06-30",
        )


@pytest.mark.parametrize(
    "agent",
    ["dollar", "yield_curve", "volatility", "emerging_markets", "news_sentiment"],
)
def test_legacy_outputs_are_readable_but_unverified(agent):
    marked = mark_legacy_macro_output({"agent": agent, "old_value": 1})
    assert marked["legacy_status"] == "legacy_unverified"

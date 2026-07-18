from __future__ import annotations

import json

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_snapshots import (
    ALFRED_SERIES_MAP,
    ALFRED_SERIES_ROLE_MAP,
    MACRO_SNAPSHOT_SCHEMA_VERSION,
    mark_legacy_macro_output,
    validate_role_snapshot,
)


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
        "us_credit_spread",
        "broad_dollar_index",
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
    "institutional_flow": ("market_flow_net_amount",),
}


def observation(**overrides):
    row = {
        "series_id": "cn_cpi",
        "period_start": "2024-05-01",
        "period_end": "2024-05-31",
        "released_at": "2024-06-12T01:30:00Z",
        "vintage_at": "2024-06-12T01:30:00Z",
        "actual": 0.3,
        "previous": 0.3,
        "expected": 0.4,
        "unit": "percent_yoy",
        "source": "tushare",
        "pit_status": "AVAILABLE_AS_OF",
        "evidence_id": "macro:cn_cpi:2024-05:20240612",
    }
    row.update(overrides)
    if "evidence_id" not in overrides:
        row["evidence_id"] = f"macro:{row['series_id']}:2024-05:20240612"
    return row


def payload(role="china", **overrides):
    observations = [
        observation(
            series_id=series_id,
            source="ALFRED" if role == "us_economy" else "tushare",
        )
        for series_id in ROLE_SERIES[role]
    ]
    value = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": role,
        "as_of_date": "2024-06-30",
        "observations": observations,
        "events": [],
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
    assert len(result["snapshot_hash"]) == 64
    json.dumps(result)


@pytest.mark.parametrize("field", ["released_at", "vintage_at"])
def test_future_release_or_vintage_is_rejected(field):
    bad = payload(observations=[observation(**{field: "2024-07-01T00:00:00Z"})])
    with pytest.raises(DataVendorUnavailable, match="future macro observation"):
        validate_role_snapshot(bad, "china", "2024-06-30")


@pytest.mark.parametrize("field", ["released_at", "vintage_at"])
def test_next_china_local_day_is_rejected_even_when_utc_date_matches(field):
    bad = payload(observations=[observation(**{field: "2024-07-01T07:00:00+08:00"})])
    with pytest.raises(DataVendorUnavailable, match="future macro observation"):
        validate_role_snapshot(bad, "china", "2024-06-30")


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
    bad = payload(role="central_bank", observations=[observation(series_id="cn_cpi")])
    with pytest.raises(
        DataVendorUnavailable, match="outside the central_bank snapshot contract"
    ):
        validate_role_snapshot(bad, "central_bank", "2024-06-30")


def test_central_bank_snapshot_is_pboc_and_domestic_liquidity_only():
    accepted = payload(role="central_bank")
    assert validate_role_snapshot(accepted, "central_bank", "2024-06-30")[
        "observations"
    ]

    for forbidden in ("fed_policy_rate", "policy_divergence_index", "us_price_summary"):
        bad = payload(
            role="central_bank",
            observations=[observation(series_id=forbidden)],
        )
        with pytest.raises(
            DataVendorUnavailable,
            match="outside the central_bank snapshot contract",
        ):
            validate_role_snapshot(bad, "central_bank", "2024-06-30")


def test_alfred_series_use_exact_role_ownership_without_cross_role_fallback():
    bad = payload(observations=[observation(series_id="GDPC1", source="ALFRED")])
    with pytest.raises(DataVendorUnavailable, match="belongs to us_economy, not china"):
        validate_role_snapshot(bad, "china", "2024-06-30")
    financial = payload(
        role="us_financial_conditions",
        observations=[
            observation(series_id="fed_balance_sheet", source="official"),
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
        DataVendorUnavailable, match="unapproved macro observation source"
    ):
        validate_role_snapshot(unknown, "china", "2024-06-30")


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

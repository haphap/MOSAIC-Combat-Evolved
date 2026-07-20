from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from mosaic.dataflows.commodity_conditions import (
    COMMODITY_CONDITION_INPUT_SCHEMA_VERSION,
    validate_commodity_conditions_input,
    validate_commodity_family_condition,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_source_contracts import (
    COMMODITY_CONTRACT_MAP,
    COMMODITY_FAMILY_CONTRACTS,
    MACRO_ROLE_SOURCE_GAPS,
    macro_role_source_readiness,
)

_MARKET_SESSION_DATE = "2024-06-28"


def _validate_family(
    payload: object, *, as_of_date: str = "2024-06-30"
) -> dict[str, object]:
    return validate_commodity_family_condition(
        payload,
        as_of_date=as_of_date,
        market_session_date=_MARKET_SESSION_DATE,
    )


def _contract(family_id: str, expiry: str, settle: float) -> dict[str, object]:
    source = COMMODITY_FAMILY_CONTRACTS[family_id]
    year_month = expiry[:7]
    symbol = f"{source['product_code']}{year_month[2:4]}{year_month[5:7]}"
    suffix = source["ts_code_suffix"]
    evidence_suffix = f"{family_id}:{year_month}"
    return {
        "ts_code": f"{symbol}.{suffix}",
        "symbol": symbol,
        "exchange": source["exchange"],
        "name": f"{family_id} {year_month}",
        "fut_code": source["product_code"],
        "multiplier": 10,
        "trade_unit": "contract",
        "quote_unit": "cny_per_unit",
        "list_date": "2023-01-01",
        "delist_date": f"{year_month}-15",
        "delivery_month": year_month,
        "last_delivery_date": f"{year_month}-20",
        "trade_date": "2024-06-28",
        "settle": settle,
        "volume": 1000,
        "open_interest": 2000,
        "metadata_released_at": "2024-06-28T05:30:00Z",
        "metadata_vintage_at": "2024-06-28T05:30:00Z",
        "price_released_at": "2024-06-28T06:00:00Z",
        "price_vintage_at": "2024-06-28T06:00:00Z",
        "metadata_source": source["contract_metadata_source"],
        "price_source": source["daily_settlement_source"],
        "pit_status": "AVAILABLE_AS_OF",
        "metadata_evidence_id": f"metadata:{evidence_suffix}",
        "price_evidence_id": f"settlement:{evidence_suffix}",
    }


def commodity_family(family_id: str = "SC@INE") -> dict[str, object]:
    source = COMMODITY_FAMILY_CONTRACTS[family_id]
    return {
        "family_id": family_id,
        "component": source["component"],
        "contracts": [
            _contract(family_id, "2024-08-20", 100.0),
            _contract(family_id, "2024-10-20", 102.0),
        ],
        "inventory": {
            "series_id": f"inventory_{family_id.replace('@', '_')}",
            "family_id": family_id,
            "observation_date": "2024-06-28",
            "released_at": "2024-06-28T06:00:00Z",
            "vintage_at": "2024-06-28T06:00:00Z",
            "actual": 1200.0,
            "previous": 1250.0,
            "unit": "tonnes",
            "source": source["inventory_source"],
            "pit_status": "AVAILABLE_AS_OF",
            "evidence_id": f"inventory:{family_id}:2024-06-28",
        },
    }


def commodity_input() -> dict[str, object]:
    required = [
        family_id
        for component in COMMODITY_CONTRACT_MAP.values()
        for family_id in component["required_families"]
    ]
    return {
        "schema_version": COMMODITY_CONDITION_INPUT_SCHEMA_VERSION,
        "as_of_date": "2024-06-30",
        "market_session_date": _MARKET_SESSION_DATE,
        "families": [commodity_family(family_id) for family_id in required],
    }


def test_valid_real_contracts_build_auditable_term_structure_and_inventory():
    result = validate_commodity_conditions_input(
        commodity_input(), as_of_date="2024-06-30"
    )
    energy = result["families"]["SC@INE"]
    assert energy["selected_contracts"] == ["SC2408.INE", "SC2410.INE"]
    assert energy["term_structure"]["state"] == "CONTANGO"
    assert energy["term_structure"]["spread_ratio"] == pytest.approx(0.02)
    assert energy["source_identity"] == {
        "contract_metadata": "tushare.fut_basic.SC@INE",
        "daily_settlement": "tushare.fut_daily.SC@INE",
        "inventory": "tushare.fut_wsr.SC@INE",
    }
    assert result["conditions_hash"].startswith("sha256:")

    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/commodity_conditions_v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)


def test_curve_state_is_computed_not_supplied_by_the_model():
    raw = commodity_family()
    raw["contracts"][1]["settle"] = 98.0
    result = _validate_family(raw)
    assert result["term_structure"]["state"] == "BACKWARDATION"
    assert "term_structure" not in raw


def test_single_or_continuous_contract_cannot_claim_term_structure():
    single = commodity_family()
    single["contracts"] = single["contracts"][:1]
    with pytest.raises(DataVendorUnavailable, match="at least 2 real tradable"):
        _validate_family(single)

    continuous = commodity_family()
    continuous["contracts"][0]["ts_code"] = "SC@INE"
    continuous["contracts"][0]["symbol"] = "SC@INE"
    with pytest.raises(DataVendorUnavailable, match="real dated contract"):
        _validate_family(continuous)


def test_missing_contract_metadata_or_inventory_rejects_instead_of_neutralizing():
    missing_metadata = commodity_family()
    del missing_metadata["contracts"][0]["last_delivery_date"]
    with pytest.raises(DataVendorUnavailable, match="metadata fields mismatch"):
        _validate_family(missing_metadata)

    missing_inventory = commodity_family()
    missing_inventory["inventory"] = None
    with pytest.raises(DataVendorUnavailable, match="inventory fields mismatch"):
        _validate_family(missing_inventory)


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("contract", "metadata_vintage_at"),
        ("contract", "price_released_at"),
        ("inventory", "vintage_at"),
    ],
)
def test_future_release_or_vintage_is_rejected(target: str, field: str):
    raw = commodity_family()
    if target == "contract":
        raw["contracts"][0][field] = "2024-07-01T00:00:00Z"
    else:
        raw["inventory"][field] = "2024-07-01T00:00:00Z"
    with pytest.raises(DataVendorUnavailable, match="future commodity"):
        _validate_family(raw)


def test_market_and_inventory_observation_must_match_frozen_session():
    future_market = commodity_family()
    for contract in future_market["contracts"]:
        contract["trade_date"] = "2024-07-01"
    with pytest.raises(DataVendorUnavailable, match="must match market_session_date"):
        _validate_family(future_market)

    future_inventory = commodity_family()
    future_inventory["inventory"]["observation_date"] = "2024-07-01"
    with pytest.raises(DataVendorUnavailable, match="must match market_session_date"):
        _validate_family(future_inventory)


def test_roll_window_expiry_and_cross_family_rows_fail_closed():
    inside_roll = commodity_family()
    inside_roll["contracts"][0]["delist_date"] = "2024-07-01"
    inside_roll["contracts"][0]["last_delivery_date"] = "2024-07-20"
    inside_roll["contracts"][0]["delivery_month"] = "2024-07"
    with pytest.raises(DataVendorUnavailable, match="fixed roll window"):
        _validate_family(inside_roll)

    wrong_family = commodity_family()
    wrong_family["contracts"][0]["fut_code"] = "CU"
    with pytest.raises(DataVendorUnavailable, match="does not belong to family"):
        _validate_family(wrong_family)


def test_required_family_and_inventory_permission_readiness_are_fail_closed():
    raw = commodity_input()
    raw["families"] = raw["families"][:-1]
    with pytest.raises(DataVendorUnavailable, match="missing required families"):
        validate_commodity_conditions_input(raw, as_of_date="2024-06-30")

    unready_optional = commodity_input()
    unready_optional["families"].append(commodity_family("FU@SHFE"))
    with pytest.raises(DataVendorUnavailable, match="without readiness proof"):
        validate_commodity_conditions_input(
            unready_optional, as_of_date="2024-06-30"
        )

    readiness = macro_role_source_readiness("commodities")
    assert readiness["production_ready"] is False
    assert any(
        gap.endswith(
            "fut_wsr.SC@INE:"
            "PREFLIGHT_ONLY_ARCHIVED_PIT_INVENTORY_RECEIPT_MISSING"
        )
        for gap in MACRO_ROLE_SOURCE_GAPS["commodities"]
    )
    assert all(
        contract["inventory_source_status"]
        == "PREFLIGHT_ONLY_ARCHIVED_PIT_RECEIPT_MISSING"
        for contract in COMMODITY_FAMILY_CONTRACTS.values()
    )


def test_inventory_source_has_no_adjacent_endpoint_fallback():
    raw = copy.deepcopy(commodity_family())
    raw["inventory"]["source"] = "official.exchange_inventory"
    with pytest.raises(DataVendorUnavailable, match="source identity mismatch"):
        _validate_family(raw)


def test_market_session_freshness_and_exact_observation_alignment_fail_closed():
    stale = commodity_input()
    stale["as_of_date"] = "2026-07-20"
    with pytest.raises(DataVendorUnavailable, match="freshness window"):
        validate_commodity_conditions_input(stale, as_of_date="2026-07-20")

    mismatched_contract = commodity_input()
    mismatched_contract["families"][0]["contracts"][0]["trade_date"] = "2024-06-27"
    with pytest.raises(DataVendorUnavailable, match="must match market_session_date"):
        validate_commodity_conditions_input(
            mismatched_contract, as_of_date="2024-06-30"
        )

    mismatched_inventory = commodity_input()
    mismatched_inventory["families"][0]["inventory"]["observation_date"] = (
        "2024-06-27"
    )
    with pytest.raises(DataVendorUnavailable, match="must match market_session_date"):
        validate_commodity_conditions_input(
            mismatched_inventory, as_of_date="2024-06-30"
        )

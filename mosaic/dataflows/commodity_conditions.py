"""Deterministic PIT commodity term-structure and inventory contract.

The builder consumes normalized, already archived ``fut_basic`` metadata,
``fut_daily`` settlements, and inventory observations.  It never queries a
live endpoint or substitutes a continuous/main-contract symbol.  Production
readiness is gated separately by :mod:`macro_source_contracts`.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timezone
from typing import Any, Final
from zoneinfo import ZoneInfo

from .cross_runtime_json import canonical_hash
from .exceptions import DataVendorUnavailable
from .macro_source_contracts import (
    COMMODITY_CONTRACT_MAP,
    COMMODITY_FAMILY_CONTRACTS,
)

COMMODITY_CONDITION_INPUT_SCHEMA_VERSION: Final = "commodity_condition_inputs_v1"
COMMODITY_CONDITIONS_SCHEMA_VERSION: Final = "commodity_conditions_v1"
_PIT_STATUS: Final = "AVAILABLE_AS_OF"
_A_SHARE_TIMEZONE = ZoneInfo("Asia/Shanghai")
_A_SHARE_DECISION_CUTOFF = time(15, 0)

_INPUT_FIELDS = frozenset(
    {"schema_version", "as_of_date", "market_session_date", "families"}
)
_FAMILY_FIELDS = frozenset({"family_id", "component", "contracts", "inventory"})
_CONTRACT_FIELDS = frozenset(
    {
        "ts_code",
        "symbol",
        "exchange",
        "name",
        "fut_code",
        "multiplier",
        "trade_unit",
        "quote_unit",
        "list_date",
        "delist_date",
        "delivery_month",
        "last_delivery_date",
        "trade_date",
        "settle",
        "volume",
        "open_interest",
        "metadata_released_at",
        "metadata_vintage_at",
        "price_released_at",
        "price_vintage_at",
        "metadata_source",
        "price_source",
        "pit_status",
        "metadata_evidence_id",
        "price_evidence_id",
    }
)
_INVENTORY_FIELDS = frozenset(
    {
        "series_id",
        "family_id",
        "observation_date",
        "released_at",
        "vintage_at",
        "actual",
        "previous",
        "unit",
        "source",
        "pit_status",
        "evidence_id",
    }
)


def _canonical_hash(payload: object) -> str:
    return canonical_hash(payload)


def _as_of_cutoff(as_of_date: str) -> datetime:
    try:
        parsed = date.fromisoformat(as_of_date)
    except (TypeError, ValueError) as exc:
        raise DataVendorUnavailable(
            f"commodity as_of_date must be YYYY-MM-DD, got {as_of_date!r}"
        ) from exc
    return datetime.combine(
        parsed,
        _A_SHARE_DECISION_CUTOFF,
        tzinfo=_A_SHARE_TIMEZONE,
    ).astimezone(timezone.utc)


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise DataVendorUnavailable(f"commodity {field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DataVendorUnavailable(f"commodity {field} must be an ISO date") from exc


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DataVendorUnavailable(
            f"commodity {field} must be a non-empty ISO timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"commodity {field} must be an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise DataVendorUnavailable(f"commodity {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_release_vintage(
    *, released_at: Any, vintage_at: Any, cutoff: datetime, scope: str
) -> None:
    released = _parse_timestamp(released_at, f"{scope}.released_at")
    vintage = _parse_timestamp(vintage_at, f"{scope}.vintage_at")
    if released > cutoff or vintage > cutoff:
        raise DataVendorUnavailable(
            f"future commodity {scope} release/vintage rejected"
        )
    if released > vintage:
        raise DataVendorUnavailable(
            f"commodity {scope} must satisfy released_at <= vintage_at"
        )


def _text(value: Any, field: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DataVendorUnavailable(f"commodity {field} must be non-empty")
    return value.strip()


def _number(
    value: Any,
    field: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise DataVendorUnavailable(f"commodity {field} must be finite")
    normalized = float(value)
    if positive and normalized <= 0:
        raise DataVendorUnavailable(f"commodity {field} must be positive")
    if non_negative and normalized < 0:
        raise DataVendorUnavailable(f"commodity {field} must be non-negative")
    return normalized


def _validate_contract_row(
    row: Any,
    *,
    family_id: str,
    cutoff: datetime,
    market_session_date: date,
) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != _CONTRACT_FIELDS:
        missing = sorted(_CONTRACT_FIELDS - set(row)) if isinstance(row, dict) else []
        extra = sorted(set(row) - _CONTRACT_FIELDS) if isinstance(row, dict) else []
        raise DataVendorUnavailable(
            f"commodity contract metadata fields mismatch missing={missing} extra={extra}"
        )
    contract = COMMODITY_FAMILY_CONTRACTS[family_id]
    ts_code = _text(row["ts_code"], "contract.ts_code")
    symbol = _text(row["symbol"], "contract.symbol")
    product_code = contract["product_code"]
    ts_code_suffix = contract["ts_code_suffix"]
    if "@" in ts_code or re.fullmatch(
        rf"{re.escape(product_code)}\d{{3,4}}\.{re.escape(ts_code_suffix)}",
        ts_code,
        flags=re.IGNORECASE,
    ) is None:
        raise DataVendorUnavailable(
            f"commodity {family_id} requires a real dated contract, got {ts_code!r}"
        )
    if symbol.casefold() != ts_code.rsplit(".", 1)[0].casefold():
        raise DataVendorUnavailable("commodity contract symbol/ts_code mismatch")
    if (
        row["exchange"] != contract["exchange"]
        or str(row["fut_code"]).upper() != product_code
    ):
        raise DataVendorUnavailable(
            f"commodity contract does not belong to family {family_id}"
        )

    list_date = _parse_date(row["list_date"], "contract.list_date")
    delist_date = _parse_date(row["delist_date"], "contract.delist_date")
    last_delivery_date = _parse_date(
        row["last_delivery_date"], "contract.last_delivery_date"
    )
    trade_date = _parse_date(row["trade_date"], "contract.trade_date")
    delivery_month = _text(row["delivery_month"], "contract.delivery_month")
    if re.fullmatch(r"\d{4}-\d{2}", delivery_month) is None:
        raise DataVendorUnavailable(
            "commodity contract.delivery_month must be YYYY-MM"
        )
    if delivery_month != last_delivery_date.strftime("%Y-%m"):
        raise DataVendorUnavailable(
            "commodity delivery_month/last_delivery_date mismatch"
        )
    if not (list_date <= trade_date <= delist_date <= last_delivery_date):
        raise DataVendorUnavailable(
            "commodity contract must be listed and tradable on trade_date"
        )
    if trade_date != market_session_date:
        raise DataVendorUnavailable(
            "commodity contract trade_date must match market_session_date"
        )

    _validate_release_vintage(
        released_at=row["metadata_released_at"],
        vintage_at=row["metadata_vintage_at"],
        cutoff=cutoff,
        scope="contract_metadata",
    )
    _validate_release_vintage(
        released_at=row["price_released_at"],
        vintage_at=row["price_vintage_at"],
        cutoff=cutoff,
        scope="contract_price",
    )
    price_released = _parse_timestamp(
        row["price_released_at"], "contract_price.released_at"
    )
    if price_released.astimezone(_A_SHARE_TIMEZONE).date() < trade_date:
        raise DataVendorUnavailable(
            "commodity contract price cannot be released before trade_date"
        )
    if row["pit_status"] != _PIT_STATUS:
        raise DataVendorUnavailable("commodity contract is not point-in-time available")
    if row["metadata_source"] != contract["contract_metadata_source"]:
        raise DataVendorUnavailable(
            f"commodity metadata source identity mismatch for {family_id}"
        )
    if row["price_source"] != contract["daily_settlement_source"]:
        raise DataVendorUnavailable(
            f"commodity settlement source identity mismatch for {family_id}"
        )

    return {
        "ts_code": ts_code.upper(),
        "symbol": symbol.upper(),
        "exchange": contract["exchange"],
        "name": _text(row["name"], "contract.name"),
        "fut_code": product_code,
        "multiplier": _number(row["multiplier"], "contract.multiplier", positive=True),
        "trade_unit": _text(row["trade_unit"], "contract.trade_unit", maximum=64),
        "quote_unit": _text(row["quote_unit"], "contract.quote_unit", maximum=64),
        "list_date": list_date.isoformat(),
        "delist_date": delist_date.isoformat(),
        "delivery_month": delivery_month,
        "last_delivery_date": last_delivery_date.isoformat(),
        "trade_date": trade_date.isoformat(),
        "settle": _number(row["settle"], "contract.settle", positive=True),
        "volume": _number(row["volume"], "contract.volume", positive=True),
        "open_interest": _number(
            row["open_interest"], "contract.open_interest", positive=True
        ),
        "metadata_released_at": row["metadata_released_at"],
        "metadata_vintage_at": row["metadata_vintage_at"],
        "price_released_at": row["price_released_at"],
        "price_vintage_at": row["price_vintage_at"],
        "metadata_source": contract["contract_metadata_source"],
        "price_source": contract["daily_settlement_source"],
        "pit_status": _PIT_STATUS,
        "metadata_evidence_id": _text(
            row["metadata_evidence_id"], "contract.metadata_evidence_id"
        ),
        "price_evidence_id": _text(
            row["price_evidence_id"], "contract.price_evidence_id"
        ),
    }


def _validate_inventory(
    row: Any,
    *,
    family_id: str,
    cutoff: datetime,
    market_session_date: date,
) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != _INVENTORY_FIELDS:
        missing = sorted(_INVENTORY_FIELDS - set(row)) if isinstance(row, dict) else []
        extra = sorted(set(row) - _INVENTORY_FIELDS) if isinstance(row, dict) else []
        raise DataVendorUnavailable(
            f"commodity inventory fields mismatch missing={missing} extra={extra}"
        )
    contract = COMMODITY_FAMILY_CONTRACTS[family_id]
    observation_date = _parse_date(
        row["observation_date"], "inventory.observation_date"
    )
    if observation_date != market_session_date:
        raise DataVendorUnavailable(
            "commodity inventory observation_date must match market_session_date"
        )
    _validate_release_vintage(
        released_at=row["released_at"],
        vintage_at=row["vintage_at"],
        cutoff=cutoff,
        scope="inventory",
    )
    released = _parse_timestamp(row["released_at"], "inventory.released_at")
    if released.astimezone(_A_SHARE_TIMEZONE).date() < observation_date:
        raise DataVendorUnavailable(
            "commodity inventory cannot be released before observation_date"
        )
    if row["family_id"] != family_id:
        raise DataVendorUnavailable("commodity inventory family_id mismatch")
    if row["source"] != contract["inventory_source"]:
        raise DataVendorUnavailable(
            f"commodity inventory source identity mismatch for {family_id}"
        )
    if row["pit_status"] != _PIT_STATUS:
        raise DataVendorUnavailable("commodity inventory is not point-in-time available")
    previous = row["previous"]
    if previous is not None:
        previous = _number(
            previous, "inventory.previous", non_negative=True
        )
    return {
        "series_id": _text(row["series_id"], "inventory.series_id"),
        "family_id": family_id,
        "observation_date": observation_date.isoformat(),
        "released_at": row["released_at"],
        "vintage_at": row["vintage_at"],
        "actual": _number(row["actual"], "inventory.actual", non_negative=True),
        "previous": previous,
        "unit": _text(row["unit"], "inventory.unit", maximum=64),
        "source": contract["inventory_source"],
        "pit_status": _PIT_STATUS,
        "evidence_id": _text(row["evidence_id"], "inventory.evidence_id"),
    }


def _required_family_ids() -> frozenset[str]:
    return frozenset(
        family_id
        for component in COMMODITY_CONTRACT_MAP.values()
        for family_id in component["required_families"]
    )


def validate_commodity_family_condition(
    payload: Any,
    *,
    as_of_date: str,
    market_session_date: str,
) -> dict[str, Any]:
    """Validate one family and compute its curve state deterministically."""
    if not isinstance(payload, dict) or set(payload) != _FAMILY_FIELDS:
        raise DataVendorUnavailable("commodity family fields mismatch")
    family_id = payload.get("family_id")
    if family_id not in COMMODITY_FAMILY_CONTRACTS:
        raise DataVendorUnavailable(f"unregistered commodity family: {family_id!r}")
    source_contract = COMMODITY_FAMILY_CONTRACTS[family_id]
    if payload.get("component") != source_contract["component"]:
        raise DataVendorUnavailable("commodity family/component mismatch")
    cutoff = _as_of_cutoff(as_of_date)
    session_date = _parse_date(market_session_date, "market_session_date")
    as_of_local_date = cutoff.astimezone(_A_SHARE_TIMEZONE).date()
    session_lag = (as_of_local_date - session_date).days
    maximum_lag = source_contract["freshness_contract"][
        "maximum_market_session_lag_calendar_days"
    ]
    if session_lag < 0 or session_lag > maximum_lag:
        raise DataVendorUnavailable(
            "commodity market_session_date is outside the fixed freshness window"
        )
    raw_contracts = payload.get("contracts")
    if not isinstance(raw_contracts, list):
        raise DataVendorUnavailable("commodity contracts must be an array")
    contracts = [
        _validate_contract_row(
            row,
            family_id=family_id,
            cutoff=cutoff,
            market_session_date=session_date,
        )
        for row in raw_contracts
    ]
    minimum = source_contract["roll_rule"]["minimum_tradable_contracts"]
    if len(contracts) < minimum:
        raise DataVendorUnavailable(
            f"commodity {family_id} requires at least {minimum} real tradable contracts"
        )
    ts_codes = [row["ts_code"] for row in contracts]
    if len(ts_codes) != len(set(ts_codes)):
        raise DataVendorUnavailable("commodity contracts contain duplicate ts_code")
    trade_dates = {row["trade_date"] for row in contracts}
    if len(trade_dates) != 1:
        raise DataVendorUnavailable(
            "commodity term structure contracts must share one trade_date"
        )
    minimum_days = source_contract["roll_rule"]["minimum_days_to_delist"]
    trade_date = date.fromisoformat(next(iter(trade_dates)))
    for row in contracts:
        if (date.fromisoformat(row["delist_date"]) - trade_date).days < minimum_days:
            raise DataVendorUnavailable(
                f"commodity contract {row['ts_code']} is inside the fixed roll window"
            )
    contracts.sort(key=lambda row: (row["delist_date"], row["ts_code"]))
    near, far = contracts[:2]
    days_between = (
        date.fromisoformat(far["delist_date"])
        - date.fromisoformat(near["delist_date"])
    ).days
    if days_between <= 0:
        raise DataVendorUnavailable(
            "commodity near/far contracts require distinct increasing expiries"
        )
    spread_ratio = far["settle"] / near["settle"] - 1.0
    state = (
        "CONTANGO"
        if spread_ratio > 0
        else "BACKWARDATION"
        if spread_ratio < 0
        else "FLAT"
    )
    inventory = _validate_inventory(
        payload.get("inventory"),
        family_id=family_id,
        cutoff=cutoff,
        market_session_date=session_date,
    )
    evidence_ids = [
        evidence_id
        for row in contracts
        for evidence_id in (
            row["metadata_evidence_id"],
            row["price_evidence_id"],
        )
    ] + [inventory["evidence_id"]]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise DataVendorUnavailable(
            f"commodity {family_id} evidence_id values must be unique"
        )
    family = {
        "family_id": family_id,
        "component": source_contract["component"],
        "roll_rule_id": source_contract["roll_rule"]["rule_id"],
        "trade_date": trade_date.isoformat(),
        "contracts": contracts,
        "selected_contracts": [near["ts_code"], far["ts_code"]],
        "term_structure": {
            "state": state,
            "near_contract": near["ts_code"],
            "far_contract": far["ts_code"],
            "near_delist_date": near["delist_date"],
            "far_delist_date": far["delist_date"],
            "near_settle": near["settle"],
            "far_settle": far["settle"],
            "days_between_delist_dates": days_between,
            "spread_ratio": round(spread_ratio, 12),
            "annualized_carry": round(spread_ratio * 365.0 / days_between, 12),
        },
        "inventory": inventory,
        "source_identity": {
            "contract_metadata": source_contract["contract_metadata_source"],
            "daily_settlement": source_contract["daily_settlement_source"],
            "inventory": source_contract["inventory_source"],
        },
        "evidence_ids": sorted(evidence_ids),
    }
    return {**family, "family_hash": _canonical_hash(family)}


def validate_commodity_conditions_input(
    payload: Any,
    *,
    as_of_date: str,
) -> dict[str, Any]:
    """Build the model-visible commodity conditions from archived PIT rows."""
    if not isinstance(payload, dict) or set(payload) != _INPUT_FIELDS:
        raise DataVendorUnavailable("commodity condition input fields mismatch")
    if payload.get("schema_version") != COMMODITY_CONDITION_INPUT_SCHEMA_VERSION:
        raise DataVendorUnavailable("commodity condition input schema_version mismatch")
    if payload.get("as_of_date") != as_of_date:
        raise DataVendorUnavailable("commodity condition input as_of_date mismatch")
    market_session_date = payload.get("market_session_date")
    if not isinstance(market_session_date, str):
        raise DataVendorUnavailable(
            "commodity condition input market_session_date is required"
        )
    families = payload.get("families")
    if not isinstance(families, list) or not families:
        raise DataVendorUnavailable("commodity conditions require family inputs")
    if any(
        not isinstance(row, dict)
        or not isinstance(row.get("family_id"), str)
        or not row["family_id"].strip()
        for row in families
    ):
        raise DataVendorUnavailable(
            "commodity condition family entries require a registered family_id"
        )
    family_ids = [row["family_id"] for row in families]
    if len(family_ids) != len(set(family_ids)):
        raise DataVendorUnavailable("commodity conditions contain duplicate families")
    required_family_ids = _required_family_ids()
    missing = sorted(required_family_ids - set(family_ids))
    if missing:
        raise DataVendorUnavailable(
            "commodity conditions missing required families: " + ", ".join(missing)
        )
    extra = sorted(set(family_ids) - required_family_ids)
    if extra:
        raise DataVendorUnavailable(
            "commodity conditions contain non-required families without readiness proof: "
            + ", ".join(extra)
        )
    canonical_families = {
        family["family_id"]: family
        for family in (
            validate_commodity_family_condition(
                row,
                as_of_date=as_of_date,
                market_session_date=market_session_date,
            )
            for row in families
        )
    }
    all_evidence = [
        evidence_id
        for family in canonical_families.values()
        for evidence_id in family["evidence_ids"]
    ]
    if len(all_evidence) != len(set(all_evidence)):
        raise DataVendorUnavailable(
            "commodity evidence_id values must be unique across families"
        )
    conditions = {
        "schema_version": COMMODITY_CONDITIONS_SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "market_session_date": market_session_date,
        "families": {
            family_id: canonical_families[family_id]
            for family_id in sorted(canonical_families)
        },
    }
    return {**conditions, "conditions_hash": _canonical_hash(conditions)}


__all__ = [
    "COMMODITY_CONDITION_INPUT_SCHEMA_VERSION",
    "COMMODITY_CONDITIONS_SCHEMA_VERSION",
    "validate_commodity_conditions_input",
    "validate_commodity_family_condition",
]

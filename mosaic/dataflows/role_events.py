"""Deterministic, role-bound projections from the private economic calendar."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from typing import Any, Final
from zoneinfo import ZoneInfo

from mosaic.dataflows.economic_calendar import EconomicCalendarStore
from mosaic.dataflows.exceptions import DataVendorUnavailable

ROLE_EVENT_SNAPSHOT_VERSION = "role_event_snapshot_v2"
ROLE_EVENT_COVERAGE_VERSION = "role_event_coverage_v2"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_EU_CURRENCIES = ("EUR", "BGN", "CZK", "DKK", "HUF", "PLN", "RON", "SEK")

ROLE_EVENT_CURRENCIES: Final[dict[str, tuple[str, ...]]] = {
    "china": ("CNY",),
    "us_economy": ("USD",),
    "eu_economy": _EU_CURRENCIES,
    "central_bank": ("CNY",),
    "us_financial_conditions": ("USD", "CNY"),
    "euro_area_financial_conditions": ("EUR",),
    "commodities": ("USD", "CNY", "EUR"),
    "geopolitical": ("CNY", "USD", "EUR"),
    "semiconductor": ("CNY", "USD", "EUR"),
    "technology": ("CNY", "USD", "EUR"),
    "energy": ("CNY", "USD", "EUR"),
    "consumer": ("CNY", "USD", "EUR"),
    "industrials": ("CNY", "USD", "EUR"),
    "real_estate_construction": ("CNY",),
    "financials": ("CNY", "USD", "EUR"),
    "agriculture": ("CNY", "USD", "EUR"),
    "cro": ("CNY", "USD", "EUR"),
    "alpha_discovery": ("CNY", "USD", "EUR"),
    "autonomous_execution": ("CNY", "USD", "EUR"),
}

_SECTOR_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "semiconductor": ("半导体", "芯片", "semiconductor", "chip"),
    "technology": ("软件", "通信", "电子", "计算机", "software", "telecom"),
    "energy": ("原油", "天然气", "库存", "光伏", "风电", "电池", "oil", "gas", "energy"),
    "consumer": ("零售", "消费", "汽车", "收入", "retail", "consumer", "vehicle"),
    "industrials": ("工业", "制造", "pmi", "manufacturing", "production"),
    "real_estate_construction": ("房地产", "住宅", "建筑", "施工", "property", "housing"),
    "financials": ("利率", "信贷", "流动性", "银行", "rate", "credit", "liquidity"),
    "agriculture": ("农业", "粮食", "农产品", "food", "crop", "agri"),
}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _deterministic_id(namespace: str, value: Any) -> str:
    return f"{namespace}:{_canonical_hash(value).removeprefix('sha256:')}"


def _as_of_timestamp(as_of_date: str) -> str:
    parsed = date.fromisoformat(as_of_date)
    return datetime.combine(parsed, time.max, tzinfo=_SHANGHAI).isoformat()


def _macro_owner(event: dict[str, Any]) -> str:
    currency = str(event.get("currency") or "")
    family = str(event.get("country") or "")
    if currency == "CNY":
        return "central_bank" if family == "central_banks" else "china"
    if currency == "USD":
        return (
            "us_financial_conditions"
            if family == "central_banks"
            else "us_economy"
        )
    return (
        "euro_area_financial_conditions"
        if family == "central_banks"
        else "eu_economy"
    )


def _projection_policy(
    consumer: str,
    event: dict[str, Any],
) -> tuple[str, str, str, str]:
    macro_owner = _macro_owner(event)
    if consumer == "commodities":
        text = str(event.get("normalized_event") or "")
        if any(
            keyword in text
            for keyword in (
                "原油",
                "天然气",
                "库存",
                "黄金",
                "金属",
                "粮食",
                "oil",
                "gas",
                "inventory",
                "gold",
                "metal",
                "crop",
            )
        ):
            return consumer, "PRIMARY", "MACRO_FACTOR", "SIGNAL"
        return macro_owner, "CONTEXT_ONLY", "MACRO_FACTOR", "TRANSMISSION"
    if consumer in {
        "china",
        "us_economy",
        "eu_economy",
        "central_bank",
        "us_financial_conditions",
        "euro_area_financial_conditions",
    }:
        if consumer == macro_owner:
            return consumer, "PRIMARY", "MACRO_FACTOR", "SIGNAL"
        return macro_owner, "CONTEXT_ONLY", "MACRO_FACTOR", "TRANSMISSION"
    if consumer == "geopolitical":
        return macro_owner, "CONTEXT_ONLY", "MACRO_FACTOR", "TRANSMISSION"
    if consumer in _SECTOR_KEYWORDS:
        text = str(event.get("normalized_event") or "")
        if any(keyword in text for keyword in _SECTOR_KEYWORDS[consumer]):
            return consumer, "PRIMARY", "SECTOR_THESIS", "CATALYST"
        return macro_owner, "CONTEXT_ONLY", "SECTOR_THESIS", "TRANSMISSION"
    purpose = {
        "cro": "RISK_TIMING",
        "alpha_discovery": "CATALYST",
        "autonomous_execution": "EXECUTION_TIMING",
    }[consumer]
    return macro_owner, "CONTEXT_ONLY", "DECISION_CONTROL", purpose


def build_role_event_snapshot(
    consumer_agent: str,
    as_of_date: str,
    *,
    store: EconomicCalendarStore | None = None,
) -> dict[str, Any]:
    currencies = ROLE_EVENT_CURRENCIES.get(consumer_agent)
    if currencies is None:
        raise DataVendorUnavailable(f"role-event access is denied for {consumer_agent}")
    as_of = _as_of_timestamp(as_of_date)
    source = store or EconomicCalendarStore()
    coverage = source.coverage_as_of(
        as_of=as_of,
        occurrence_date=as_of_date,
        currencies=currencies,
    )
    events = [
        event
        for event in source.events_as_of(as_of)
        if event.get("currency") in currencies
        and event.get("occurrence_anchor_date") == as_of_date
    ]
    projections: list[dict[str, Any]] = []
    for event in events:
        signal_owner, usage_mode, signal_scope, purpose = _projection_policy(
            consumer_agent, event
        )
        if signal_scope == "DECISION_CONTROL" and event.get("time_status") != "VERIFIED":
            continue
        surprise = None
        if (
            event.get("time_status") == "VERIFIED"
            and event.get("conflict_status") in {"CLEAR", "RESOLVED"}
            and isinstance(event.get("actual"), (int, float))
            and isinstance(event.get("forecast"), (int, float))
        ):
            surprise = float(event["actual"]) - float(event["forecast"])
        projections.append(
            {
                "calendar_event_id": event["calendar_event_id"],
                "event_revision_id": event["event_revision_id"],
                "evidence_bundle_id": event["evidence_bundle_id"],
                "source_evidence_ids": [event["source_evidence_id"]],
                "fact_owner": "economic_calendar_pipeline",
                "signal_owner": signal_owner,
                "consumer_agent": consumer_agent,
                "usage_mode": usage_mode,
                "signal_scope": signal_scope,
                "allowed_purpose": purpose,
                "materiality_tier": 2,
                "normalized_event": event["normalized_event"],
                "reference_period": event["reference_period"],
                "release_stage": event["release_stage"],
                "scheduled_at": event["scheduled_at"],
                "released_at": event["released_at"],
                "event_phase": event["event_phase"],
                "actual": event["actual"],
                "previous": event["previous"],
                "forecast": event["forecast"],
                "surprise": surprise,
                "unit": event["unit"],
                "time_status": event["time_status"],
                "conflict_status": event["conflict_status"],
                "reconciliation_status": event["reconciliation_status"],
                "causal_dedupe_key": event["evidence_bundle_id"],
            }
        )
    projections.sort(key=lambda row: (row["calendar_event_id"], row["event_revision_id"]))
    material_ids = sorted({row["event_revision_id"] for row in projections})
    presence = "MATERIAL_EVENTS_PRESENT" if material_ids else "NO_MATERIAL_EVENT_OBSERVED"
    completeness = "COMPLETE" if coverage["query_complete"] else "INCOMPLETE"
    if completeness == "INCOMPLETE":
        coverage_state = "SOURCE_UNAVAILABLE"
    elif material_ids:
        coverage_state = "AVAILABLE_MATERIAL_EVENTS"
    else:
        coverage_state = "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT"
    coverage_summary = {
        "coverage_state": coverage_state,
        "event_presence_state": presence,
        "coverage_completeness": completeness,
        "coverage_as_of": as_of,
        "query_complete": coverage["query_complete"],
        "required_route_ids": coverage["required_route_ids"],
        "healthy_route_ids": coverage["healthy_route_ids"],
        "unhealthy_route_ids": coverage["unhealthy_route_ids"],
        "coverage_evidence_ids": coverage["coverage_evidence_ids"],
        "material_event_revision_ids": material_ids,
        "coverage_contract_version": ROLE_EVENT_COVERAGE_VERSION,
    }
    without_id = {
        "schema_version": ROLE_EVENT_SNAPSHOT_VERSION,
        "consumer_agent": consumer_agent,
        "as_of": as_of,
        "contract_version": ROLE_EVENT_COVERAGE_VERSION,
        "coverage": coverage_summary,
        "projections": projections,
    }
    snapshot_id = _deterministic_id("role-event-snapshot", without_id)
    with_id = {"role_event_snapshot_id": snapshot_id, **without_id}
    return {**with_id, "role_event_snapshot_hash": _canonical_hash(with_id)}


def render_role_event_snapshot(consumer_agent: str, as_of_date: str) -> str:
    snapshot = build_role_event_snapshot(consumer_agent, as_of_date)
    if snapshot["coverage"]["coverage_completeness"] != "COMPLETE":
        raise DataVendorUnavailable(
            f"role-event required routes are incomplete for {consumer_agent}/{as_of_date}"
        )
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ROLE_EVENT_COVERAGE_VERSION",
    "ROLE_EVENT_CURRENCIES",
    "ROLE_EVENT_SNAPSHOT_VERSION",
    "build_role_event_snapshot",
    "render_role_event_snapshot",
]

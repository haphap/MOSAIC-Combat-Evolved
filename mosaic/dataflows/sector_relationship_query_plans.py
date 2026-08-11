"""Trusted finite query plans derived from validated L2 snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from mosaic.dataflows.sector_snapshots import (
    validate_relationship_runtime_snapshot,
    validate_sector_runtime_snapshot,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.sector_relationship_preservation import argument_schema_for_tool


PLAN_CONTRACT_VERSION = "sector_relationship_query_plan_v1"
QUERY_WINDOW_PROFILES = (30, 90, 365)
REPORT_LIMIT_PROFILES = (10, 30)
INDICATOR_LOOKBACK_PROFILES = (30, 60, 120, 365)
MONEYFLOW_LOOKBACK_PROFILES = (5, 20, 60)
POLICY_LOOKBACK_PROFILES = (7, 30, 90)
CURVE_LOOKBACK_PROFILES = (30, 90, 365)
ETF_TOP_N_PROFILES = tuple(range(1, 13))
STATEMENT_FREQUENCIES = ("annual", "quarterly")
RKE_MAX_ITEMS = 12

THS_INDUSTRY_FILTERS: dict[str, tuple[str, ...]] = {
    "agriculture": ("农业", "种植", "养殖", "林业", "饲料", "动物保健"),
    "biotech": ("医药", "医疗", "生物制品", "中药"),
    "consumer": ("家电", "食品", "饮料", "纺织", "服装", "零售", "旅游", "美容", "汽车"),
    "energy": ("煤炭", "石油", "天然气", "电力", "光伏", "风电", "电池"),
    "financials": ("银行", "证券", "保险", "多元金融"),
    "industrials": ("化学", "钢铁", "有色", "机械", "军工", "电气设备", "交通运输", "环保"),
    "real_estate_construction": ("房地产", "建筑材料", "建筑装饰"),
    "semiconductor": ("半导体",),
    "technology": ("电子", "计算机", "传媒", "通信"),
}

_STANDARD_SECTOR_TOOLS = frozenset(
    {
        "get_broker_research",
        "get_etf_holdings",
        "get_indicators",
        "get_industry_moneyflow",
        "get_industry_policy_digest",
        "get_rke_research_context",
        "get_stock_data",
    }
)
_EXPECTED_TOOLS = {
    agent_id: _STANDARD_SECTOR_TOOLS
    for agent_id in THS_INDUSTRY_FILTERS
}
_EXPECTED_TOOLS["semiconductor"] = _STANDARD_SECTOR_TOOLS | {
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
}
_EXPECTED_TOOLS["financials"] = _STANDARD_SECTOR_TOOLS | {"get_yield_curve_cn"}
_EXPECTED_TOOLS["relationship_mapper"] = frozenset(
    {
        "get_rke_research_context",
        "get_stock_research",
        "get_supply_chain_evidence",
    }
)

_PROFILE_CONTRACT = {
    "contract_version": PLAN_CONTRACT_VERSION,
    "query_window_days": list(QUERY_WINDOW_PROFILES),
    "report_limits": list(REPORT_LIMIT_PROFILES),
    "indicator_lookbacks": list(INDICATOR_LOOKBACK_PROFILES),
    "moneyflow_lookbacks": list(MONEYFLOW_LOOKBACK_PROFILES),
    "policy_lookbacks": list(POLICY_LOOKBACK_PROFILES),
    "curve_lookbacks": list(CURVE_LOOKBACK_PROFILES),
    "etf_top_n": list(ETF_TOP_N_PROFILES),
    "statement_frequencies": list(STATEMENT_FREQUENCIES),
    "rke_max_items": RKE_MAX_ITEMS,
    "ths_industry_filters": {
        agent_id: list(values)
        for agent_id, values in sorted(THS_INDUSTRY_FILTERS.items())
    },
}
PROFILE_CONTRACT_HASH = canonical_hash(_PROFILE_CONTRACT)


def _decode_payload(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty JSON payload")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{field} must decode to an object")
    return payload


def _window_start(as_of: date, window_days: int) -> str:
    return (as_of - timedelta(days=window_days - 1)).isoformat()


def _append(
    requests: list[dict[str, Any]],
    allowed: frozenset[str],
    tool_id: str,
    args: Mapping[str, Any],
) -> None:
    if tool_id in allowed:
        requests.append({"tool_id": tool_id, "args": dict(args)})


def _sector_plan(
    *, agent_id: str, as_of: str, initial_payloads: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, str], list[tuple[str, str]]]:
    if "get_sector_research_snapshot" not in initial_payloads:
        raise ValueError("Sector query plan requires get_sector_research_snapshot")
    payload = validate_sector_runtime_snapshot(
        _decode_payload(
            initial_payloads["get_sector_research_snapshot"],
            "get_sector_research_snapshot",
        ),
        agent_id,
        as_of,
    )
    if payload.get("sector_agent_id") != agent_id:
        raise ValueError("Sector snapshot agent identity mismatch")
    tickers = sorted(row["ts_code"] for row in payload["eligible_security_universe"])
    directions = sorted(payload["direction_ids"])
    etfs = sorted(
        {
            ticker
            for card in payload["direction_cards"]
            for ticker in card["etf_family"]["etf_ts_codes"]
        }
    )
    filters = THS_INDUSTRY_FILTERS[agent_id]
    scope = {
        "tickers": tickers,
        "etfs": etfs,
        "sectors": sorted({*directions, *filters}),
        "indicator_families": list(
            argument_schema_for_tool("get_indicators")["properties"]["indicator"][
                "enum"
            ]
        ),
    }
    direction_by_ticker = {
        row["ts_code"]: row["direction_id"]
        for row in payload["eligible_security_universe"]
    }
    rke_pairs = sorted(direction_by_ticker.items())
    return scope, {"snapshot_hash": payload["snapshot_hash"]}, rke_pairs


def _relationship_plan(
    *, as_of: str, initial_payloads: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, str], list[tuple[str, str]]]:
    if "get_relationship_graph_snapshot" not in initial_payloads:
        raise ValueError(
            "Relationship query plan requires get_relationship_graph_snapshot"
        )
    payload = validate_relationship_runtime_snapshot(
        _decode_payload(
            initial_payloads["get_relationship_graph_snapshot"],
            "get_relationship_graph_snapshot",
        ),
        as_of,
    )
    rows = list(payload["relationships"])
    for opportunity in payload["prediction_opportunity_set"]["ordered_opportunities"]:
        rows.append(opportunity)
        rows.extend(opportunity["matched_non_edges"])
    rke_pairs = sorted(
        {(row["target_entity"], row["target_sector_id"]) for row in rows}
    )
    tickers = sorted({ticker for ticker, _sector in rke_pairs})
    sectors = sorted({sector for _ticker, sector in rke_pairs})
    scope = {
        "tickers": tickers,
        "etfs": [],
        "sectors": sectors,
        "indicator_families": [],
    }
    return scope, {"snapshot_hash": payload["snapshot_hash"]}, rke_pairs


def build_sector_relationship_query_plan(
    *,
    agent_id: str,
    stage: str,
    as_of: str,
    initial_payloads: Mapping[str, str],
    allowed_tools: Sequence[str],
) -> dict[str, Any]:
    """Build a deterministic finite request set from a validated initial snapshot."""

    if stage != agent_id:
        raise ValueError("Sector/Relationship query plan stage must equal agent_id")
    as_of_date = date.fromisoformat(as_of)
    expected = _EXPECTED_TOOLS.get(agent_id)
    if expected is None:
        raise ValueError("agent is outside the Sector/Relationship query-plan roster")
    if (
        not isinstance(allowed_tools, Sequence)
        or isinstance(allowed_tools, (str, bytes))
        or len(set(allowed_tools)) != len(allowed_tools)
        or frozenset(allowed_tools) != expected
    ):
        raise ValueError("allowed tools do not exact-close the query-plan roster")
    if not isinstance(initial_payloads, Mapping):
        raise ValueError("initial_payloads must be an object")
    allowed = frozenset(allowed_tools)
    if agent_id == "relationship_mapper":
        scope, source, rke_pairs = _relationship_plan(
            as_of=as_of, initial_payloads=initial_payloads
        )
        directions: list[str] = []
    else:
        scope, source, rke_pairs = _sector_plan(
            agent_id=agent_id, as_of=as_of, initial_payloads=initial_payloads
        )
        directions = sorted(
            sector
            for sector in scope["sectors"]
            if sector not in THS_INDUSTRY_FILTERS[agent_id]
        )
    scope = {
        "as_of": as_of,
        "earliest_date": (
            as_of_date - timedelta(days=max(QUERY_WINDOW_PROFILES))
        ).isoformat(),
        **scope,
    }

    requests: list[dict[str, Any]] = []
    for ticker in scope["tickers"]:
        for window_days in QUERY_WINDOW_PROFILES:
            interval = {
                "ticker": ticker,
                "date_from": _window_start(as_of_date, window_days),
                "date_to": as_of,
            }
            _append(requests, allowed, "get_stock_data", interval)
            for limit in REPORT_LIMIT_PROFILES:
                _append(
                    requests,
                    allowed,
                    "get_broker_research",
                    {**interval, "max_reports": limit},
                )
                _append(
                    requests,
                    allowed,
                    "get_stock_research",
                    {**interval, "max_reports": limit},
                )
        for indicator in scope["indicator_families"]:
            for lookback in INDICATOR_LOOKBACK_PROFILES:
                _append(
                    requests,
                    allowed,
                    "get_indicators",
                    {
                        "ticker": ticker,
                        "as_of": as_of,
                        "lookback": lookback,
                        "indicator": indicator,
                    },
                )
        for tool_id in (
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement",
        ):
            for frequency in STATEMENT_FREQUENCIES:
                _append(
                    requests,
                    allowed,
                    tool_id,
                    {"ticker": ticker, "frequency": frequency, "as_of": as_of},
                )
        _append(
            requests,
            allowed,
            "get_supply_chain_evidence",
            {"ticker": ticker, "as_of": as_of},
        )

    for etf in scope["etfs"]:
        for top_n in ETF_TOP_N_PROFILES:
            _append(
                requests,
                allowed,
                "get_etf_holdings",
                {"etf": etf, "as_of": as_of, "top_n": top_n},
            )

    if agent_id != "relationship_mapper":
        for lookback in MONEYFLOW_LOOKBACK_PROFILES:
            _append(
                requests,
                allowed,
                "get_industry_moneyflow",
                {
                    "as_of": as_of,
                    "lookback": lookback,
                    "industry_filters": list(THS_INDUSTRY_FILTERS[agent_id]),
                },
            )
        for lookback in POLICY_LOOKBACK_PROFILES:
            _append(
                requests,
                allowed,
                "get_industry_policy_digest",
                {"as_of": as_of, "lookback_days": lookback, "source": "govcn"},
            )
        for lookback in CURVE_LOOKBACK_PROFILES:
            _append(
                requests,
                allowed,
                "get_yield_curve_cn",
                {"as_of": as_of, "lookback": lookback},
            )
        for direction in directions:
            _append(
                requests,
                allowed,
                "get_rke_research_context",
                {
                    "agent_id": agent_id,
                    "as_of": as_of,
                    "layer": "sector",
                    "ticker": "",
                    "sector": direction,
                    "max_items": RKE_MAX_ITEMS,
                },
            )

    for ticker, sector in rke_pairs:
        _append(
            requests,
            allowed,
            "get_rke_research_context",
            {
                "agent_id": agent_id,
                "as_of": as_of,
                "layer": (
                    "relationship" if agent_id == "relationship_mapper" else "sector"
                ),
                "ticker": ticker,
                "sector": sector,
                "max_items": RKE_MAX_ITEMS,
            },
        )

    requests.sort(
        key=lambda row: (row["tool_id"], canonical_hash(row["args"]))
    )
    present_tools = {row["tool_id"] for row in requests}
    missing = allowed - present_tools
    if missing - {"get_etf_holdings"}:
        raise ValueError("query plan did not materialize every non-empty tool domain")
    if "get_etf_holdings" in missing and scope["etfs"]:
        raise ValueError("query plan omitted a non-empty ETF domain")

    body = {
        "plan_contract_version": PLAN_CONTRACT_VERSION,
        "profile_contract_hash": PROFILE_CONTRACT_HASH,
        "source_snapshot_hash": source["snapshot_hash"],
        "authorized_scope": scope,
        "query_requests": requests,
    }
    return {**body, "plan_hash": canonical_hash(body)}


__all__ = [
    "INDICATOR_LOOKBACK_PROFILES",
    "PLAN_CONTRACT_VERSION",
    "PROFILE_CONTRACT_HASH",
    "QUERY_WINDOW_PROFILES",
    "THS_INDUSTRY_FILTERS",
    "build_sector_relationship_query_plan",
]

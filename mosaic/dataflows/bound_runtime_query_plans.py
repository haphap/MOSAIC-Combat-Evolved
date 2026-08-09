"""Finite L3/L4 query plans derived from validated bound runtime snapshots."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from mosaic.dataflows.sector_relationship_query_plans import (
    CURVE_LOOKBACK_PROFILES,
    INDICATOR_LOOKBACK_PROFILES,
    POLICY_LOOKBACK_PROFILES,
    QUERY_WINDOW_PROFILES,
    REPORT_LIMIT_PROFILES,
    STATEMENT_FREQUENCIES,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l3_l4_activation import l3_l4_overlay_stage_for_active
from mosaic.scorecard.l3_l4_preservation import (
    L3_TOOL_ROSTER,
    argument_schema_for_binding,
)


PLAN_CONTRACT_VERSION = "bound_runtime_query_plan_v1"
_A_SHARE_TICKER = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_BOUND_TOOL_BY_STAGE = {
    **{
        (agent_id, agent_id): "get_superinvestor_candidate_snapshot"
        for agent_id in L3_TOOL_ROSTER
    },
    ("alpha_discovery", "alpha_discovery"): "get_alpha_candidate_snapshot",
    ("cro", "cro"): "get_cro_risk_snapshot",
    ("autonomous_execution", "autonomous_execution"): "get_execution_snapshot",
    ("cio", "cio_proposal"): "get_cio_decision_snapshot",
    ("cio", "cio_final"): "get_cio_decision_snapshot",
}


def _decode_snapshot(
    *,
    agent_id: str,
    stage: str,
    as_of: str,
    initial_payloads: Mapping[str, str],
) -> dict[str, Any]:
    try:
        tool_id = _BOUND_TOOL_BY_STAGE[(agent_id, stage)]
    except KeyError as exc:
        raise ValueError(f"Agent/stage is outside the bound query-plan roster: {agent_id}/{stage}") from exc
    if not isinstance(initial_payloads, Mapping):
        raise ValueError("initial_payloads must be an object")
    raw = initial_payloads.get(tool_id)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"bound runtime payload {tool_id} is unavailable")
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("bound runtime payload must be valid JSON") from exc
    if not isinstance(snapshot, dict):
        raise ValueError("bound runtime payload must decode to an object")
    if (
        snapshot.get("agent_id") != agent_id
        or snapshot.get("stage") != stage
        or snapshot.get("as_of") != as_of
        or snapshot.get("pit_status") != "VERIFIED"
    ):
        raise ValueError("bound runtime snapshot identity is invalid")
    body = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    if snapshot.get("snapshot_hash") != canonical_hash(body):
        raise ValueError("bound runtime snapshot hash mismatch")
    candidate_scope = snapshot.get("candidate_scope")
    candidates = snapshot.get("candidate_universe")
    constraints = snapshot.get("constraints")
    role_context = snapshot.get("role_context")
    refs = snapshot.get("upstream_accepted_output_refs")
    if not all(
        isinstance(value, dict)
        for value in (candidate_scope, constraints, role_context)
    ) or not isinstance(candidates, list) or not isinstance(refs, list):
        raise ValueError("bound runtime snapshot query authorities are malformed")
    candidate_body = {
        "candidate_status": snapshot.get("candidate_status"),
        "candidate_universe": candidates,
    }
    if (
        snapshot.get("candidate_scope_hash") != canonical_hash(candidate_scope)
        or snapshot.get("candidate_universe_hash") != canonical_hash(candidate_body)
        or snapshot.get("constraint_set_hash") != canonical_hash(constraints)
        or snapshot.get("role_context_hash") != canonical_hash(role_context)
    ):
        raise ValueError("bound runtime snapshot authority hash mismatch")
    expected_candidate_status = "AVAILABLE" if candidates else "EMPTY_CONFIRMED"
    if snapshot.get("candidate_status") != expected_candidate_status:
        raise ValueError("bound runtime snapshot candidate status is inconsistent")
    date.fromisoformat(as_of)
    return snapshot


def _candidate_rows(snapshot: Mapping[str, Any], *, require_non_empty: bool) -> list[dict[str, str]]:
    raw_rows = snapshot["candidate_universe"]
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"candidate_universe[{index}] must be an object")
        ticker = raw.get("ts_code")
        if not isinstance(ticker, str) or _A_SHARE_TICKER.fullmatch(ticker) is None:
            raise ValueError(f"candidate_universe[{index}] has an invalid A-share ticker")
        if ticker in seen:
            raise ValueError("candidate_universe contains duplicate tickers")
        seen.add(ticker)
        sector = raw.get("source_sector_agent_id", "")
        if not isinstance(sector, str):
            raise ValueError("candidate source sector must be a string")
        rows.append({"ticker": ticker, "sector": sector})
    rows.sort(key=lambda row: row["ticker"])
    if require_non_empty and not rows:
        raise ValueError("L3 bound query plan requires an accepted candidate")
    return rows


def _append(
    rows: list[dict[str, Any]],
    allowed: set[str],
    tool_id: str,
    args: Mapping[str, Any],
) -> None:
    if tool_id in allowed:
        rows.append({"tool_id": tool_id, "args": dict(args)})


def _l3_plan(
    *,
    agent_id: str,
    stage: str,
    as_of: str,
    snapshot: Mapping[str, Any],
    allowed_tools: Sequence[str],
) -> dict[str, Any]:
    expected = tuple(L3_TOOL_ROSTER[agent_id])
    if tuple(allowed_tools) != expected:
        raise ValueError("allowed tools do not exact-close the L3 query-plan roster")
    candidates = _candidate_rows(snapshot, require_non_empty=False)
    as_of_date = date.fromisoformat(as_of)
    earliest = as_of_date - timedelta(days=max(QUERY_WINDOW_PROFILES) - 1)
    indicator_schema = argument_schema_for_binding(
        agent_id=agent_id,
        stage=stage,
        tool_id="get_indicators",
    )
    indicators = list(
        indicator_schema["properties"]["indicator"]["enum"]
    ) if "get_indicators" in expected else []
    scope = {
        "as_of": as_of,
        "earliest_date": earliest.isoformat(),
        "accepted_candidate_tickers": [row["ticker"] for row in candidates],
        "indicator_families": indicators,
        "candidate_scope_hash": snapshot["candidate_scope_hash"],
        "candidate_universe_hash": snapshot["candidate_universe_hash"],
        "source_snapshot_hash": snapshot["snapshot_hash"],
    }
    templates = {
        "ackman": (
            ("get_fundamentals", None),
            ("get_cashflow", "annual"),
        ),
        "munger": (
            ("get_fundamentals", None),
            ("get_cashflow", "annual"),
        ),
        "burry": (
            ("get_fundamentals", None),
            ("get_balance_sheet", "annual"),
        ),
        "druckenmiller": (),
    }[agent_id]
    initial: list[dict[str, Any]] = []
    if candidates:
        first_ticker = candidates[0]["ticker"]
        for tool_id, frequency in templates:
            args: dict[str, Any] = {"ticker": first_ticker, "as_of": as_of}
            if frequency is not None:
                args["frequency"] = frequency
            initial.append({"tool_id": tool_id, "args": args})

    allowed = set(expected)
    followups: list[dict[str, Any]] = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        _append(followups, allowed, "get_fundamentals", {"ticker": ticker, "as_of": as_of})
        for statement in ("get_income_statement", "get_balance_sheet", "get_cashflow"):
            for frequency in STATEMENT_FREQUENCIES:
                _append(
                    followups,
                    allowed,
                    statement,
                    {"ticker": ticker, "frequency": frequency, "as_of": as_of},
                )
        for window_days in QUERY_WINDOW_PROFILES:
            date_from = (as_of_date - timedelta(days=window_days - 1)).isoformat()
            interval = {"ticker": ticker, "date_from": date_from, "date_to": as_of}
            _append(followups, allowed, "get_stock_data", interval)
            for max_reports in REPORT_LIMIT_PROFILES:
                _append(
                    followups,
                    allowed,
                    "get_stock_research",
                    {**interval, "max_reports": max_reports},
                )
        for indicator in indicators:
            for lookback in INDICATOR_LOOKBACK_PROFILES:
                _append(
                    followups,
                    allowed,
                    "get_indicators",
                    {
                        "ticker": ticker,
                        "as_of": as_of,
                        "lookback": lookback,
                        "indicator": indicator,
                    },
                )
        _append(
            followups,
            allowed,
            "get_rke_research_context",
            {
                "agent_id": agent_id,
                "as_of": as_of,
                "layer": "superinvestor",
                "ticker": ticker,
                "sector": candidate["sector"],
                "max_items": 12,
            },
        )
    for lookback in POLICY_LOOKBACK_PROFILES:
        _append(
            followups,
            allowed,
            "get_industry_policy_digest",
            {"as_of": as_of, "lookback_days": lookback, "source": "govcn"},
        )
    for lookback in CURVE_LOOKBACK_PROFILES:
        _append(
            followups,
            allowed,
            "get_yield_curve_cn",
            {"as_of": as_of, "lookback": lookback},
        )

    initial_keys = {
        (row["tool_id"], canonical_hash(row["args"])) for row in initial
    }
    deduplicated = {
        (row["tool_id"], canonical_hash(row["args"])): row for row in followups
    }
    for key in initial_keys:
        deduplicated.pop(key, None)
    followups = [deduplicated[key] for key in sorted(deduplicated)]
    if candidates and {row["tool_id"] for row in [*initial, *followups]} != allowed:
        raise ValueError("finite L3 query set does not cover every allowed tool")
    return {
        "schema_version": PLAN_CONTRACT_VERSION,
        "preservation_stage": stage,
        "authorized_scope": scope,
        "initial_query_requests": initial,
        "query_requests": followups,
    }


def _l4_plan(
    *,
    agent_id: str,
    active_stage: str,
    preservation_stage: str,
    as_of: str,
    snapshot: Mapping[str, Any],
    allowed_tools: Sequence[str],
) -> dict[str, Any]:
    if tuple(allowed_tools) != ("get_rke_research_context",):
        raise ValueError("allowed tools do not exact-close the L4 query-plan roster")
    candidates = _candidate_rows(snapshot, require_non_empty=False)
    role_context = snapshot["role_context"]
    liquidity_hash = role_context.get("liquidity_vintage_hash")
    if not isinstance(liquidity_hash, str) or not liquidity_hash.startswith("sha256:"):
        liquidity_hash = canonical_hash(
            [
                row
                for row in snapshot.get("evidence_ledger", [])
                if isinstance(row, Mapping) and row.get("source_kind") == "MARKET_SNAPSHOT"
            ]
        )
    scope = {
        "as_of": as_of,
        "accepted_candidate_tickers": [row["ticker"] for row in candidates],
        "accepted_output_set_hash": canonical_hash(
            snapshot["upstream_accepted_output_refs"]
        ),
        "account_positions_policy_hash": canonical_hash(
            {
                "constraint_set_hash": snapshot["constraint_set_hash"],
                "position_snapshot_hash": role_context.get("position_snapshot_hash"),
                "constraint_evidence_ids": snapshot["constraints"].get("evidence_ids", []),
            }
        ),
        "market_liquidity_vintage_hash": liquidity_hash,
    }
    return {
        "schema_version": PLAN_CONTRACT_VERSION,
        "preservation_stage": preservation_stage,
        "authorized_scope": scope,
        "initial_query_requests": [
            {
                "tool_id": "get_rke_research_context",
                "args": {
                    "agent_id": agent_id,
                    "as_of": as_of,
                    "layer": "decision",
                    "max_items": 3,
                },
            }
        ],
        "query_requests": [],
    }


def build_bound_runtime_query_plan(
    *,
    agent_id: str,
    stage: str,
    as_of: str,
    initial_payloads: Mapping[str, str],
    allowed_tools: Sequence[str],
) -> dict[str, Any]:
    """Derive the exact private request domain from one bound initial snapshot."""
    if not isinstance(allowed_tools, Sequence) or isinstance(allowed_tools, (str, bytes)):
        raise ValueError("allowed_tools must be an array")
    if len(allowed_tools) != len(set(allowed_tools)):
        raise ValueError("allowed tools contain duplicates")
    snapshot = _decode_snapshot(
        agent_id=agent_id,
        stage=stage,
        as_of=as_of,
        initial_payloads=initial_payloads,
    )
    preservation_stage = l3_l4_overlay_stage_for_active(agent_id, stage)
    if agent_id in L3_TOOL_ROSTER:
        return _l3_plan(
            agent_id=agent_id,
            stage=preservation_stage,
            as_of=as_of,
            snapshot=snapshot,
            allowed_tools=allowed_tools,
        )
    return _l4_plan(
        agent_id=agent_id,
        active_stage=stage,
        preservation_stage=preservation_stage,
        as_of=as_of,
        snapshot=snapshot,
        allowed_tools=allowed_tools,
    )


__all__ = ["PLAN_CONTRACT_VERSION", "build_bound_runtime_query_plan"]

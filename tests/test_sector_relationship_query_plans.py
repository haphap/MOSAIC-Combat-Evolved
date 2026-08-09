from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.dataflows.sector_relationship_query_plans import (
    INDICATOR_LOOKBACK_PROFILES,
    QUERY_WINDOW_PROFILES,
    THS_INDUSTRY_FILTERS,
    build_sector_relationship_query_plan,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.sector_relationship_preservation import (
    build_sector_relationship_preservation_overlay,
)
from scripts.build_structured_smoke_fixtures import _build_sector_snapshots


ROOT = Path(__file__).parents[1]
AS_OF = "2026-07-17"


@pytest.fixture(scope="module")
def sector_payloads(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    root = tmp_path_factory.mktemp("sector-query-plan")
    _build_sector_snapshots(root, date.fromisoformat(AS_OF))
    snapshot_root = root / "sector_snapshots" / AS_OF
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in snapshot_root.glob("*.json")
    }


def _allowed_tools(agent_id: str) -> tuple[str, ...]:
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    return tuple(
        sorted(
            row["tool_id"]
            for row in overlay["bindings"]
            if row["agent_id"] == agent_id and row["stage"] == agent_id
        )
    )


def _requests_for(plan: dict, tool_id: str) -> list[dict]:
    return [
        row["args"] for row in plan["query_requests"] if row["tool_id"] == tool_id
    ]


def test_sector_plan_uses_full_validated_scope_and_versioned_parameter_profiles(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="semiconductor",
        stage="semiconductor",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads["semiconductor"],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=_allowed_tools("semiconductor"),
    )
    snapshot = json.loads(sector_payloads["semiconductor"])
    tickers = sorted(row["ts_code"] for row in snapshot["eligible_security_universe"])
    directions = sorted(snapshot["direction_ids"])
    etfs = sorted(
        {
            ticker
            for card in snapshot["direction_cards"]
            for ticker in card["etf_family"]["etf_ts_codes"]
        }
    )
    scope = plan["authorized_scope"]
    assert plan["plan_contract_version"] == "sector_relationship_query_plan_v1"
    assert scope == {
        "as_of": AS_OF,
        "earliest_date": "2025-07-17",
        "tickers": tickers,
        "etfs": etfs,
        "sectors": sorted({*directions, *THS_INDUSTRY_FILTERS["semiconductor"]}),
        "indicator_families": [
            "atr",
            "boll",
            "boll_lb",
            "boll_ub",
            "close_10_ema",
            "close_200_sma",
            "close_50_sma",
            "macd",
            "macdh",
            "macds",
            "mfi",
            "rsi",
            "vwma",
        ],
    }
    assert plan["source_snapshot_hash"] == snapshot["snapshot_hash"]
    assert plan["plan_hash"] == canonical_hash(
        {key: value for key, value in plan.items() if key != "plan_hash"}
    )

    reports = _requests_for(plan, "get_broker_research")
    assert {(row["ticker"], row["max_reports"]) for row in reports} == {
        (ticker, limit) for ticker in tickers for limit in (10, 30)
    }
    assert {row["date_to"] for row in reports} == {AS_OF}
    assert {row["date_from"] for row in reports} == {
        "2025-07-18",
        "2026-04-19",
        "2026-06-18",
    }

    indicators = _requests_for(plan, "get_indicators")
    assert len(indicators) == (
        len(tickers) * len(scope["indicator_families"]) * len(INDICATOR_LOOKBACK_PROFILES)
    )
    assert {row["ticker"] for row in indicators} == set(tickers)
    assert {row["indicator"] for row in indicators} == set(
        scope["indicator_families"]
    )
    assert {row["lookback"] for row in indicators} == set(
        INDICATOR_LOOKBACK_PROFILES
    )

    stock_data = _requests_for(plan, "get_stock_data")
    assert len(stock_data) == len(tickers) * len(QUERY_WINDOW_PROFILES)
    assert {row["date_from"] for row in stock_data} == {
        "2025-07-18",
        "2026-04-19",
        "2026-06-18",
    }

    for tool_id in ("get_balance_sheet", "get_cashflow", "get_income_statement"):
        statements = _requests_for(plan, tool_id)
        assert {(row["ticker"], row["frequency"]) for row in statements} == {
            (ticker, frequency)
            for ticker in tickers
            for frequency in ("annual", "quarterly")
        }

    moneyflow = _requests_for(plan, "get_industry_moneyflow")
    assert {tuple(row["industry_filters"]) for row in moneyflow} == {
        tuple(THS_INDUSTRY_FILTERS["semiconductor"])
    }
    assert {row["lookback"] for row in moneyflow} == {5, 20, 60}
    assert {row["lookback_days"] for row in _requests_for(
        plan, "get_industry_policy_digest"
    )} == {7, 30, 90}

    holdings = _requests_for(plan, "get_etf_holdings")
    assert len(holdings) == len(etfs) * 12
    assert {row["top_n"] for row in holdings} == (
        set(range(1, 13)) if etfs else set()
    )

    rke = _requests_for(plan, "get_rke_research_context")
    assert {row["layer"] for row in rke} == {"sector"}
    assert {row["agent_id"] for row in rke} == {"semiconductor"}
    assert {row["sector"] for row in rke if not row["ticker"]} == set(directions)
    assert {row["ticker"] for row in rke if row["ticker"]} == set(tickers)


def test_relationship_plan_authorizes_only_target_securities(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="relationship_mapper",
        stage="relationship_mapper",
        as_of=AS_OF,
        initial_payloads={
            "get_relationship_graph_snapshot": sector_payloads["relationship_mapper"]
        },
        allowed_tools=_allowed_tools("relationship_mapper"),
    )
    snapshot = json.loads(sector_payloads["relationship_mapper"])
    target_tickers = sorted(
        {
            row["target_entity"]
            for row in snapshot["relationships"]
        }
        | {
            row["target_entity"]
            for opportunity in snapshot["prediction_opportunity_set"][
                "ordered_opportunities"
            ]
            for row in opportunity["matched_non_edges"]
        }
    )
    source_holders = {
        row["source_entity"] for row in snapshot["relationships"]
    } | {
        row["source_entity"]
        for opportunity in snapshot["prediction_opportunity_set"][
            "ordered_opportunities"
        ]
        for row in opportunity["matched_non_edges"]
    }
    assert plan["authorized_scope"]["tickers"] == target_tickers
    assert not source_holders & set(plan["authorized_scope"]["tickers"])
    assert not plan["authorized_scope"]["etfs"]
    assert not plan["authorized_scope"]["indicator_families"]
    assert {row["ticker"] for row in _requests_for(plan, "get_stock_research")} == set(
        target_tickers
    )
    assert {
        row["ticker"] for row in _requests_for(plan, "get_supply_chain_evidence")
    } == set(target_tickers)
    assert {row["layer"] for row in _requests_for(
        plan, "get_rke_research_context"
    )} == {"relationship"}


def test_plan_rejects_tampered_or_foreign_initial_snapshot(
    sector_payloads: dict[str, str],
) -> None:
    tampered = json.loads(sector_payloads["energy"])
    tampered["eligible_security_universe"][0]["ts_code"] = "600999.SH"
    with pytest.raises(DataVendorUnavailable, match="hash"):
        build_sector_relationship_query_plan(
            agent_id="energy",
            stage="energy",
            as_of=AS_OF,
            initial_payloads={"get_sector_research_snapshot": json.dumps(tampered)},
            allowed_tools=_allowed_tools("energy"),
        )

    with pytest.raises(ValueError, match="stage"):
        build_sector_relationship_query_plan(
            agent_id="energy",
            stage="technology",
            as_of=AS_OF,
            initial_payloads={
                "get_sector_research_snapshot": sector_payloads["energy"]
            },
            allowed_tools=_allowed_tools("energy"),
        )


def test_frozen_store_accepts_valid_plan_with_empty_etf_authority(
    tmp_path: Path, sector_payloads: dict[str, str]
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="semiconductor",
        stage="semiconductor",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads["semiconductor"]
        },
        allowed_tools=_allowed_tools("semiconductor"),
    )
    assert plan["authorized_scope"]["etfs"] == []
    store = FrozenAdaptiveQueryStore(
        tmp_path / ".mosaic" / "private" / "frozen-queries.sqlite3"
    )
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    prepared = store.prepare(
        agent_id="semiconductor",
        stage="semiconductor",
        as_of=AS_OF,
        authorized_scope=plan["authorized_scope"],
        query_requests=plan["query_requests"],
        preservation_overlay=overlay,
        materializer=lambda tool_id, args: {
            "payload": json.dumps({"tool_id": tool_id, "args": args}),
            "source_receipt_hashes": [canonical_hash({"tool_id": tool_id, "args": args})],
            **(
                {
                    "derivation": {
                        "derivation_contract_version": "frozen_research_digest_lineage_v1",
                        "model_hash": canonical_hash({"model": "test"}),
                        "prompt_hash": canonical_hash({"prompt": "test"}),
                        "source_payload_hash": canonical_hash({"args": args}),
                    }
                }
                if tool_id
                in {
                    "get_broker_research",
                    "get_industry_policy_digest",
                    "get_stock_research",
                }
                else {}
            ),
        },
    )
    assert prepared["public_projection"]["private_payload_count"] == len(
        plan["query_requests"]
    )

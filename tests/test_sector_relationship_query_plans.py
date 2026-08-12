from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import mosaic.dataflows.sector_snapshots as sector_snapshots_module
import scripts.build_structured_smoke_fixtures as structured_smoke_fixtures
from mosaic.bridge.tool_capabilities import (
    INITIAL_SNAPSHOT_TOOL_IDS,
    allowed_tools_for_agent,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.dataflows.sector_snapshots import _build_sector_etf_direction_authority
from mosaic.dataflows.sector_relationship_production import (
    SectorRelationshipAdaptiveQueryPreparer,
)
from mosaic.dataflows.sector_relationship_query_plans import (
    INDICATOR_LOOKBACK_PROFILES,
    QUERY_WINDOW_PROFILES,
    THS_INDUSTRY_FILTERS,
    build_sector_relationship_query_plan,
)
from mosaic.scorecard.capability_preservation import load_capability_contract_bundle
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.sector_relationship_preservation import (
    SECTOR_AGENT_IDS,
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
    return tuple(
        tool_id
        for tool_id in allowed_tools_for_agent(agent_id)
        if tool_id not in INITIAL_SNAPSHOT_TOOL_IDS
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


def test_sector_plan_accepts_only_complete_hash_bound_runtime_snapshot(
    sector_payloads: dict[str, str],
) -> None:
    runtime = json.loads(sector_payloads["semiconductor"])
    runtime.pop("snapshot_hash")
    runtime["event_coverage"] = {"coverage_completeness": "COMPLETE"}
    runtime["role_event_snapshot_ref"] = {
        "role_event_snapshot_id": "role-event-snapshot:structured-smoke",
        "role_event_snapshot_hash": canonical_hash(
            {"role_event_snapshot_id": "role-event-snapshot:structured-smoke"}
        ),
    }
    runtime["snapshot_hash"] = canonical_hash(runtime)

    plan = build_sector_relationship_query_plan(
        agent_id="semiconductor",
        stage="semiconductor",
        as_of=AS_OF,
        initial_payloads={"get_sector_research_snapshot": json.dumps(runtime)},
        allowed_tools=_allowed_tools("semiconductor"),
    )
    assert plan["source_snapshot_hash"] == runtime["snapshot_hash"]

    incomplete = json.loads(json.dumps(runtime))
    incomplete["event_coverage"]["coverage_completeness"] = "INCOMPLETE"
    incomplete["snapshot_hash"] = canonical_hash(
        {key: value for key, value in incomplete.items() if key != "snapshot_hash"}
    )
    with pytest.raises(DataVendorUnavailable, match="event coverage.*complete"):
        build_sector_relationship_query_plan(
            agent_id="semiconductor",
            stage="semiconductor",
            as_of=AS_OF,
            initial_payloads={
                "get_sector_research_snapshot": json.dumps(incomplete)
            },
            allowed_tools=_allowed_tools("semiconductor"),
        )


@pytest.mark.parametrize("agent_id", SECTOR_AGENT_IDS)
def test_every_sector_stage_exactly_materializes_its_adaptive_tool_roster(
    sector_payloads: dict[str, str], agent_id: str
) -> None:
    allowed = set(_allowed_tools(agent_id))
    plan = build_sector_relationship_query_plan(
        agent_id=agent_id,
        stage=agent_id,
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads[agent_id],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=tuple(sorted(allowed)),
    )

    present = {row["tool_id"] for row in plan["query_requests"]}
    expected = set(allowed)
    if not plan["authorized_scope"]["etfs"]:
        expected.discard("get_etf_holdings")
    assert present == expected
    assert all(
        any(row["tool_id"] == tool_id for row in plan["query_requests"])
        for tool_id in expected
    )


@pytest.mark.parametrize("agent_id", SECTOR_AGENT_IDS)
def test_every_sector_relationship_stage_compiles_a_frozen_adaptive_bundle(
    tmp_path: Path,
    sector_payloads: dict[str, str],
    agent_id: str,
) -> None:
    store = FrozenAdaptiveQueryStore(tmp_path / f"{agent_id}-frozen.sqlite3")

    def materialize(tool_id: str, args: dict) -> dict:
        payload = json.dumps(
            {"tool_id": tool_id, "args_hash": canonical_hash(args)},
            sort_keys=True,
        )
        result = {
            "payload": payload,
            "source_receipt_hashes": [
                canonical_hash({"tool_id": tool_id, "args": args})
            ],
        }
        if tool_id in {
            "get_broker_research",
            "get_industry_policy_digest",
            "get_stock_research",
        }:
            result["derivation"] = {
                "derivation_contract_version": "frozen_research_digest_lineage_v1",
                "model_hash": canonical_hash({"model": "fixture"}),
                "prompt_hash": canonical_hash({"tool_id": tool_id, "args": args}),
                "source_payload_hash": canonical_hash({"text": payload}),
            }
        return result

    preparer = SectorRelationshipAdaptiveQueryPreparer(
        root=ROOT,
        frozen_store=store,
        materializer=materialize,
    )
    prepared = preparer(
        agent_id=agent_id,
        stage=agent_id,
        as_of=AS_OF,
        initial_payloads={"get_sector_research_snapshot": sector_payloads[agent_id]},
        runtime_inputs={"untrusted": True},
        candidate_scope={"tickers": ["OUTSIDE.SCOPE"]},
        allowed_tools=_allowed_tools(agent_id),
    )

    projection = prepared["public_projection"]
    prepared_tools = {row["tool_id"] for row in projection["entries"]}
    active_binding_ids = {
        row["tool_id"]: row["binding_id"]
        for row in load_capability_contract_bundle(ROOT)["binding_manifest"][
            "bindings"
        ]
        if row["agent_id"] == agent_id and row["stage"] == agent_id
    }
    expected_tools = set(_allowed_tools(agent_id))
    assert projection["private_payload_count"] == 0
    if not any(
        row["tool_id"] == "get_etf_holdings" for row in projection["entries"]
    ):
        expected_tools.discard("get_etf_holdings")
    assert prepared_tools == expected_tools
    assert {
        row["tool_id"]: row["binding_id"] for row in projection["entries"]
    } == {tool_id: active_binding_ids[tool_id] for tool_id in prepared_tools}
    assert projection["agent_id"] == agent_id
    assert projection["stage"] == agent_id
    assert projection["as_of"] == AS_OF
    assert projection["adaptive_max_rounds"] == 3


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_authority = _build_sector_etf_direction_authority()
    monkeypatch.setattr(
        sector_snapshots_module, "SECTOR_ETF_DIRECTION_AUTHORITY", empty_authority
    )
    monkeypatch.setattr(
        structured_smoke_fixtures,
        "SECTOR_ETF_DIRECTION_AUTHORITY",
        empty_authority,
    )
    fixture_root = tmp_path / "empty-etf-authority"
    _build_sector_snapshots(fixture_root, date.fromisoformat(AS_OF))
    sector_payload = (
        fixture_root / "sector_snapshots" / AS_OF / "semiconductor.json"
    ).read_text(encoding="utf-8")
    plan = build_sector_relationship_query_plan(
        agent_id="semiconductor",
        stage="semiconductor",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payload
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

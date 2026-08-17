from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
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


@pytest.mark.parametrize(
    ("agent_id", "direction_id", "etf_ts_code"),
    (
        ("agriculture", "livestock_aquaculture", "159865.SZ"),
        ("biotech", "biological_products", "512290.SH"),
        ("consumer", "food_beverage", "515170.SH"),
        ("energy", "coal", "515220.SH"),
        ("financials", "banking", "512800.SH"),
        ("industrials", "machinery", "516960.SH"),
        ("real_estate_construction", "real_estate", "512200.SH"),
        (
            "semiconductor",
            "semiconductor_equipment_materials",
            "512480.SH",
        ),
        ("technology", "computer", "515230.SH"),
    ),
)
def test_etf_candidate_snapshot_is_bounded_for_each_sector_authority(
    agent_id: str,
    direction_id: str,
    etf_ts_code: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str]] = []
    basket_calls: list[tuple[str, dict[str, str]]] = []

    def fake_get_etf_holdings(ticker: str, curr_date: str) -> str:
        calls.append((ticker, curr_date))
        return (
            f"Ticker: {ticker}\n"
            "Disclosure Date: 2026-06-30\n"
            "Report Date: 2026-06-30\n"
            "ts_code,symbol,stk_name,stk_mkv_ratio\n"
            "512000.SH,600001.SH,Example,10\n"
        )

    def fake_query(api_name: str, **params: str) -> pd.DataFrame:
        basket_calls.append((api_name, params))
        return pd.DataFrame(
            [
                {
                    "trade_date": "20260716",
                    "ts_code": "512480.SH",
                    "con_code": "600001.SH",
                    "con_name": "Example prior",
                    "qty": 1000,
                    "exchange": "SH",
                },
                {
                    "trade_date": "20260717",
                    "ts_code": "512480.SH",
                    "con_code": "600001.SH",
                    "con_name": "Example",
                    "qty": 2000,
                    "exchange": "SH",
                },
                {
                    "trade_date": "20260717",
                    "ts_code": "512480.SH",
                    "con_code": "688001.SH",
                    "con_name": "Example second",
                    "qty": 1000,
                    "exchange": "SH",
                },
                {
                    "trade_date": "20260716",
                    "ts_code": "512480.SH",
                    "con_code": "601000.SH",
                    "con_name": "Example earlier",
                    "qty": 3000,
                    "exchange": "SH",
                },
            ]
        )

    monkeypatch.setattr(
        sector_snapshots_module,
        "sector_snapshot_root",
        lambda: tmp_path / "missing-sector-snapshots",
    )
    monkeypatch.setattr(
        sector_snapshots_module, "get_etf_holdings", fake_get_etf_holdings
    )
    if agent_id == "semiconductor":
        monkeypatch.setattr(sector_snapshots_module, "_query_pro", fake_query)
    rendered = json.loads(
        sector_snapshots_module.render_sector_snapshot(agent_id, AS_OF)
    )
    assert rendered["kind"] == "etf_holdings_candidates"
    assert rendered["sector_agent_id"] == agent_id
    assert rendered["direction_id"] == direction_id
    assert rendered["etf_ts_code"] == etf_ts_code
    if agent_id == "semiconductor":
        assert rendered["trade_date"] == "2026-07-17"
        assert rendered["candidates"] == [
            {"ticker": "600001.SH", "basket_quantity": 2000},
            {"ticker": "688001.SH", "basket_quantity": 1000},
        ]
        assert basket_calls == [
            (
                "etf_sh_cons",
                {
                    "ts_code": "512480.SH",
                    "start_date": "20260711",
                    "end_date": "20260717",
                },
            )
        ]
    else:
        assert date.fromisoformat(rendered["disclosure_date"]) <= date.fromisoformat(AS_OF)
        assert date.fromisoformat(rendered["report_date"]) <= date.fromisoformat(AS_OF)
    assert rendered["snapshot_hash"] == canonical_hash(
        {key: value for key, value in rendered.items() if key != "snapshot_hash"}
    )
    if agent_id == "semiconductor":
        assert calls == []
    else:
        assert calls == [(etf_ts_code, AS_OF)]

    if agent_id == "semiconductor":
        future_response = pd.DataFrame(
            [
                {
                    "trade_date": "20260717",
                    "ts_code": "512480.SH",
                    "con_code": "600001.SH",
                    "con_name": "Example",
                    "qty": 1000,
                    "exchange": "SH",
                },
                {
                    "trade_date": "20260718",
                    "ts_code": "512480.SH",
                    "con_code": "601000.SH",
                    "con_name": "Future",
                    "qty": 3000,
                    "exchange": "SH",
                }
            ]
        )
        monkeypatch.setattr(
            sector_snapshots_module, "_query_pro", lambda _api_name, **_params: future_response
        )
        with pytest.raises(DataVendorUnavailable, match="trade date"):
            sector_snapshots_module.render_sector_snapshot(agent_id, AS_OF)

    plan = build_sector_relationship_query_plan(
        agent_id=agent_id,
        stage=agent_id,
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": json.dumps(rendered, sort_keys=True)
        },
        allowed_tools=_allowed_tools(agent_id),
    )
    expected_tickers = ["600001.SH", "688001.SH"] if agent_id == "semiconductor" else ["600001.SH"]
    assert plan["authorized_scope"]["tickers"] == expected_tickers
    assert plan["authorized_scope"]["etfs"] == [etf_ts_code]
    assert plan["authorized_scope"]["sectors"] == [direction_id]

    if agent_id == "semiconductor":
        future_raw = dict(rendered)
        future_raw["trade_date"] = "2026-07-18"
        future_raw["snapshot_hash"] = canonical_hash(
            {key: value for key, value in future_raw.items() if key != "snapshot_hash"}
        )
        with pytest.raises(ValueError, match="trade_date"):
            build_sector_relationship_query_plan(
                agent_id=agent_id,
                stage=agent_id,
                as_of=AS_OF,
                initial_payloads={
                    "get_sector_research_snapshot": json.dumps(
                        future_raw, sort_keys=True
                    )
                },
                allowed_tools=_allowed_tools(agent_id),
            )


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
    policy = _requests_for(plan, "get_industry_policy_digest")
    assert {row["lookback_days"] for row in policy} == {7, 30, 90}
    assert {row["topic"] for row in policy} == {"半导体"}

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


def test_technology_sector_plan_uses_only_software_policy_topic(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="technology",
        stage="technology",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads["technology"],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=_allowed_tools("technology"),
    )
    policy = _requests_for(plan, "get_industry_policy_digest")
    assert {row["lookback_days"] for row in policy} == {7, 30, 90}
    assert {row["topic"] for row in policy} == {"软件"}


def test_energy_sector_plan_uses_only_coal_policy_topic(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="energy",
        stage="energy",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads["energy"],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=_allowed_tools("energy"),
    )
    policy = _requests_for(plan, "get_industry_policy_digest")
    assert {row["lookback_days"] for row in policy} == {7, 30, 90}
    assert {row["topic"] for row in policy} == {"煤炭"}


def test_biotech_sector_plan_uses_only_biomedicine_policy_topic(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="biotech",
        stage="biotech",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads["biotech"],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=_allowed_tools("biotech"),
    )
    policy = _requests_for(plan, "get_industry_policy_digest")
    assert {row["lookback_days"] for row in policy} == {7, 30, 90}
    assert {row["topic"] for row in policy} == {"生物医药"}


def test_consumer_sector_plan_uses_only_food_policy_topic(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="consumer",
        stage="consumer",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads["consumer"],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=_allowed_tools("consumer"),
    )
    policy = _requests_for(plan, "get_industry_policy_digest")
    assert {row["lookback_days"] for row in policy} == {7, 30, 90}
    assert {row["topic"] for row in policy} == {"食品"}


def test_industrials_sector_plan_uses_only_machinery_policy_topic(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="industrials",
        stage="industrials",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads["industrials"],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=_allowed_tools("industrials"),
    )
    policy = _requests_for(plan, "get_industry_policy_digest")
    assert {row["lookback_days"] for row in policy} == {7, 30, 90}
    assert {row["topic"] for row in policy} == {"机械"}


def test_real_estate_sector_plan_uses_only_real_estate_policy_topic(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="real_estate_construction",
        stage="real_estate_construction",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads[
                "real_estate_construction"
            ],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=_allowed_tools("real_estate_construction"),
    )
    policy = _requests_for(plan, "get_industry_policy_digest")
    assert {row["lookback_days"] for row in policy} == {7, 30, 90}
    assert {row["topic"] for row in policy} == {"房地产"}


def test_financials_sector_plan_uses_only_banking_policy_topic(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="financials",
        stage="financials",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads["financials"],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=_allowed_tools("financials"),
    )
    policy = _requests_for(plan, "get_industry_policy_digest")
    assert {row["lookback_days"] for row in policy} == {7, 30, 90}
    assert {row["topic"] for row in policy} == {"银行"}


def test_agriculture_sector_plan_uses_only_agriculture_policy_topic(
    sector_payloads: dict[str, str],
) -> None:
    plan = build_sector_relationship_query_plan(
        agent_id="agriculture",
        stage="agriculture",
        as_of=AS_OF,
        initial_payloads={
            "get_sector_research_snapshot": sector_payloads["agriculture"],
            "get_role_event_snapshot": "opaque-event-payload",
        },
        allowed_tools=_allowed_tools("agriculture"),
    )
    policy = _requests_for(plan, "get_industry_policy_digest")
    assert {row["lookback_days"] for row in policy} == {7, 30, 90}
    assert {row["topic"] for row in policy} == {"农业"}


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
    if agent_id == "technology":
        assert {
            row["args"]["topic"]
            for row in plan["query_requests"]
            if row["tool_id"] == "get_industry_policy_digest"
        } == {"软件"}
    elif agent_id == "biotech":
        assert {
            row["args"]["topic"]
            for row in plan["query_requests"]
            if row["tool_id"] == "get_industry_policy_digest"
        } == {"生物医药"}
    elif agent_id == "energy":
        assert {
            row["args"]["topic"]
            for row in plan["query_requests"]
            if row["tool_id"] == "get_industry_policy_digest"
        } == {"煤炭"}
    elif agent_id == "financials":
        assert {
            row["args"]["topic"]
            for row in plan["query_requests"]
            if row["tool_id"] == "get_industry_policy_digest"
        } == {"银行"}
    elif agent_id == "agriculture":
        assert {
            row["args"]["topic"]
            for row in plan["query_requests"]
            if row["tool_id"] == "get_industry_policy_digest"
        } == {"农业"}
    elif agent_id == "consumer":
        assert {
            row["args"]["topic"]
            for row in plan["query_requests"]
            if row["tool_id"] == "get_industry_policy_digest"
        } == {"食品"}
    elif agent_id == "industrials":
        assert {
            row["args"]["topic"]
            for row in plan["query_requests"]
            if row["tool_id"] == "get_industry_policy_digest"
        } == {"机械"}
    elif agent_id == "real_estate_construction":
        assert {
            row["args"]["topic"]
            for row in plan["query_requests"]
            if row["tool_id"] == "get_industry_policy_digest"
        } == {"房地产"}


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

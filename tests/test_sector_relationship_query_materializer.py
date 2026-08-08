from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.dataflows.sector_relationship_queries import (
    SectorRelationshipQueryMaterializer,
)
from mosaic.dataflows.staged_query_receipts import (
    seal_staged_query_source_receipt,
    validate_staged_query_source_receipt,
)
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.sector_relationship_preservation import (
    build_sector_relationship_preservation_overlay,
)


ROOT = Path(__file__).parents[1]
AS_OF = "2026-07-09"


def _receipt_authority(seen: list[dict]):
    def attest(descriptor: dict) -> list[dict]:
        seen.append(descriptor)
        return [
            seal_staged_query_source_receipt(
                descriptor,
                knowledge_available_at="2026-07-09T15:30:00+08:00",
                captured_at="2026-07-09T15:30:00+08:00",
            )
        ]

    return attest


def _digest_builder(tool_id: str, raw: str, args: dict) -> dict:
    return {
        "digest": json.dumps(
            {"tool_id": tool_id, "raw_hash": canonical_hash({"text": raw})},
            sort_keys=True,
        ),
        "model_hash": canonical_hash({"model": "digest-model-v1"}),
        "prompt_hash": canonical_hash({"prompt": tool_id, "args": args}),
    }


def test_staged_receipt_records_real_capture_time_and_preserves_replay_semantics():
    live_descriptor = {
        "tool_id": "get_stock_data",
        "route_id": "tushare.sector_market",
        "as_of": AS_OF,
        "request_hash": canonical_hash({"ticker": "600000.SH"}),
        "content_hash": canonical_hash({"text": "payload"}),
        "pit_mode": "OBSERVED_LIVE",
    }
    live = seal_staged_query_source_receipt(
        live_descriptor,
        knowledge_available_at="2026-07-09T15:30:00+08:00",
        captured_at="2026-07-09T15:30:00+08:00",
    )
    assert live["captured_at"] == "2026-07-09T15:30:00+08:00"
    assert (
        validate_staged_query_source_receipt(
            live, expected_descriptor=live_descriptor
        )
        == live["receipt_hash"]
    )

    with pytest.raises(ValueError, match="OBSERVED_LIVE capture time"):
        seal_staged_query_source_receipt(
            live_descriptor,
            knowledge_available_at="2026-07-09T15:30:00+08:00",
            captured_at="2026-07-09T15:31:00+08:00",
        )

    replay_descriptor = {**live_descriptor, "pit_mode": "AUTHORITATIVE_VINTAGE_REPLAY"}
    replay = seal_staged_query_source_receipt(
        replay_descriptor,
        knowledge_available_at="2026-07-09T15:30:00+08:00",
        captured_at="2026-07-10T09:00:00+08:00",
    )
    assert replay["captured_at"] == "2026-07-10T09:00:00+08:00"


@pytest.mark.parametrize(
    ("tool_id", "args", "expected_method", "expected_args"),
    [
        (
            "get_industry_policy_digest",
            {"as_of": AS_OF, "lookback_days": 7, "source": "govcn"},
            "get_industry_policy",
            (AS_OF, 7, "govcn"),
        ),
        (
            "get_broker_research",
            {
                "ticker": "600000.SH",
                "date_from": "2026-06-01",
                "date_to": AS_OF,
                "max_reports": 30,
            },
            "get_broker_research",
            ("600000.SH", "2026-06-01", AS_OF, 30),
        ),
        (
            "get_etf_holdings",
            {"etf": "512800.SH", "as_of": AS_OF, "top_n": 2},
            "get_etf_holdings",
            ("512800.SH", AS_OF),
        ),
        (
            "get_stock_data",
            {"ticker": "600000.SH", "date_from": "2026-06-01", "date_to": AS_OF},
            "get_stock_data",
            ("600000.SH", "2026-06-01", AS_OF),
        ),
        (
            "get_indicators",
            {
                "ticker": "600000.SH",
                "indicator": "macd",
                "as_of": AS_OF,
                "lookback": 30,
            },
            "get_indicators",
            ("600000.SH", "macd", AS_OF, 30),
        ),
        (
            "get_industry_moneyflow",
            {
                "as_of": AS_OF,
                "lookback": 5,
                "industry_filters": ["银行", "证券"],
            },
            "get_industry_moneyflow",
            (AS_OF, 5, "银行,证券"),
        ),
        (
            "get_yield_curve_cn",
            {"as_of": AS_OF, "lookback": 30},
            "get_yield_curve_cn",
            (AS_OF, 30),
        ),
        (
            "get_income_statement",
            {"ticker": "600000.SH", "frequency": "quarterly", "as_of": AS_OF},
            "get_income_statement",
            ("600000.SH", "quarterly", AS_OF),
        ),
        (
            "get_balance_sheet",
            {"ticker": "600000.SH", "frequency": "annual", "as_of": AS_OF},
            "get_balance_sheet",
            ("600000.SH", "annual", AS_OF),
        ),
        (
            "get_cashflow",
            {"ticker": "600000.SH", "frequency": "quarterly", "as_of": AS_OF},
            "get_cashflow",
            ("600000.SH", "quarterly", AS_OF),
        ),
        (
            "get_stock_research",
            {
                "ticker": "600000.SH",
                "date_from": "2026-06-01",
                "date_to": AS_OF,
                "max_reports": 12,
            },
            "get_stock_research",
            ("600000.SH", "2026-06-01", AS_OF, 12),
        ),
    ],
)
def test_materializer_maps_normalized_arguments_to_legacy_routes_exactly(
    tool_id: str,
    args: dict,
    expected_method: str,
    expected_args: tuple,
):
    calls: list[tuple[str, tuple]] = []
    receipts: list[dict] = []

    def route_caller(method: str, *route_args: object) -> str:
        calls.append((method, route_args))
        if method == "get_etf_holdings":
            return (
                "# ETF holdings\nTicker: 512800.SH\nDisclosure Date: 20260701\n"
                "Report Date: 20260630\n\n"
                "ts_code,symbol,stk_name,stk_mkv_ratio,stk_float_ratio\n"
                "512800.SH,600000.SH,浦发银行,9.1,2.1\n"
                "512800.SH,601398.SH,工商银行,8.2,1.9\n"
                "512800.SH,601939.SH,建设银行,7.4,1.7\n"
            )
        return f"raw:{method}"

    materializer = SectorRelationshipQueryMaterializer(
        route_caller=route_caller,
        receipt_authority=_receipt_authority(receipts),
        digest_builder=_digest_builder,
        rke_renderer=lambda args: f"rke:{args['agent_id']}",
    )
    result = materializer(tool_id, args)

    assert calls == [(expected_method, expected_args)]
    assert len(result["source_receipt_hashes"]) == 1
    assert receipts[0]["tool_id"] == tool_id
    assert receipts[0]["request_hash"] == canonical_hash(args)
    if tool_id in {
        "get_broker_research",
        "get_stock_research",
        "get_industry_policy_digest",
    }:
        payload = json.loads(result["payload"])
        assert payload["tool_id"] == tool_id
        assert result["derivation"] == {
            "derivation_contract_version": "frozen_research_digest_lineage_v1",
            "model_hash": canonical_hash({"model": "digest-model-v1"}),
            "prompt_hash": canonical_hash({"prompt": tool_id, "args": args}),
            "source_payload_hash": canonical_hash({"text": f"raw:{expected_method}"}),
        }
        assert f"raw:{expected_method}" not in result["payload"]
    elif tool_id == "get_etf_holdings":
        payload = json.loads(result["payload"])
        assert payload["kind"] == "etf_holdings_candidates"
        assert [row["ticker"] for row in payload["candidates"]] == [
            "600000.SH",
            "601398.SH",
        ]
    else:
        assert result["payload"] == f"raw:{expected_method}"


def test_rke_uses_local_public_safe_renderer_and_never_routes_to_vendor():
    receipt_descriptors: list[dict] = []
    materializer = SectorRelationshipQueryMaterializer(
        route_caller=lambda *args: pytest.fail(f"unexpected route call: {args}"),
        receipt_authority=_receipt_authority(receipt_descriptors),
        digest_builder=_digest_builder,
        rke_renderer=lambda args: f"public-safe-rke:{args['agent_id']}:{args['as_of']}",
    )
    args = {
        "agent_id": "financials",
        "as_of": AS_OF,
        "layer": "sector",
        "ticker": "",
        "sector": "银行",
        "max_items": 12,
    }
    result = materializer("get_rke_research_context", args)
    assert result["payload"] == "public-safe-rke:financials:2026-07-09"
    assert receipt_descriptors[0]["route_id"] == "private.rke_report_intelligence"


def test_materializer_rejects_missing_mismatched_or_future_source_receipts():
    descriptor_seen: list[dict] = []

    def wrong_authority(descriptor: dict) -> list[dict]:
        descriptor_seen.append(descriptor)
        wrong = {**descriptor, "route_id": "tushare.relationship_graph"}
        return [
            seal_staged_query_source_receipt(
                wrong,
                knowledge_available_at="2026-07-09T15:30:00+08:00",
                captured_at="2026-07-09T15:30:00+08:00",
            )
        ]

    materializer = SectorRelationshipQueryMaterializer(
        route_caller=lambda method, *args: "payload",
        receipt_authority=wrong_authority,
        digest_builder=_digest_builder,
    )
    with pytest.raises(ValueError, match="receipt descriptor mismatch"):
        materializer(
            "get_stock_data",
            {"ticker": "600000.SH", "date_from": "2026-06-01", "date_to": AS_OF},
        )

    materializer = SectorRelationshipQueryMaterializer(
        route_caller=lambda method, *args: "payload",
        receipt_authority=lambda descriptor: [],
        digest_builder=_digest_builder,
    )
    with pytest.raises(ValueError, match="requires at least one eligible source receipt"):
        materializer(
            "get_stock_data",
            {"ticker": "600000.SH", "date_from": "2026-06-01", "date_to": AS_OF},
        )

    def future_authority(descriptor: dict) -> list[dict]:
        return [
            seal_staged_query_source_receipt(
                descriptor,
                knowledge_available_at="2026-07-10T00:00:00+08:00",
                captured_at="2026-07-10T00:00:00+08:00",
            )
        ]

    materializer = SectorRelationshipQueryMaterializer(
        route_caller=lambda method, *args: "payload",
        receipt_authority=future_authority,
        digest_builder=_digest_builder,
    )
    with pytest.raises(ValueError, match="after query as_of"):
        materializer(
            "get_stock_data",
            {"ticker": "600000.SH", "date_from": "2026-06-01", "date_to": AS_OF},
        )


def test_real_materializer_integrates_with_prepare_and_call_remains_zero_transport(
    tmp_path: Path,
):
    transports = 0

    def route_caller(method: str, *args: object) -> str:
        nonlocal transports
        transports += 1
        return "frozen-market-payload"

    materializer = SectorRelationshipQueryMaterializer(
        route_caller=route_caller,
        receipt_authority=_receipt_authority([]),
        digest_builder=_digest_builder,
    )
    store = FrozenAdaptiveQueryStore(
        tmp_path / ".mosaic/private/frozen.sqlite3",
        clock=lambda: datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc),
    )
    args = {"ticker": "600000.SH", "date_from": "2026-06-01", "date_to": AS_OF}
    prepared = store.prepare(
        agent_id="financials",
        stage="financials",
        as_of=AS_OF,
        authorized_scope={
            "as_of": AS_OF,
            "earliest_date": "2026-06-01",
            "tickers": ["600000.SH"],
            "etfs": ["512800.SH"],
            "sectors": ["银行"],
            "indicator_families": ["macd"],
        },
        query_requests=[{"tool_id": "get_stock_data", "args": args}],
        preservation_overlay=build_sector_relationship_preservation_overlay(ROOT),
        materializer=materializer,
    )
    assert transports == 1
    session = store.start_session(
        bundle_id=prepared["bundle_id"], agent_id="financials", stage="financials"
    )
    assert (
        store.call(
            session_id=session,
            round_number=1,
            tool_id="get_stock_data",
            args=args,
        )
        == "frozen-market-payload"
    )
    assert transports == 1


def test_prepare_keeps_digest_lineage_private_and_projects_only_its_hash(tmp_path: Path):
    materializer = SectorRelationshipQueryMaterializer(
        route_caller=lambda method, *args: "licensed raw source prose",
        receipt_authority=_receipt_authority([]),
        digest_builder=_digest_builder,
    )
    store = FrozenAdaptiveQueryStore(tmp_path / ".mosaic/private/digest.sqlite3")
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-06-01",
        "date_to": AS_OF,
        "max_reports": 30,
    }
    prepared = store.prepare(
        agent_id="financials",
        stage="financials",
        as_of=AS_OF,
        authorized_scope={
            "as_of": AS_OF,
            "earliest_date": "2026-06-01",
            "tickers": ["600000.SH"],
            "etfs": ["512800.SH"],
            "sectors": ["银行"],
            "indicator_families": ["macd"],
        },
        query_requests=[{"tool_id": "get_broker_research", "args": args}],
        preservation_overlay=build_sector_relationship_preservation_overlay(ROOT),
        materializer=materializer,
    )
    public = json.dumps(prepared["public_projection"], ensure_ascii=False)
    assert "licensed raw source prose" not in public
    assert "digest-model-v1" not in public
    assert prepared["public_projection"]["entries"][0]["derivation_hash"].startswith(
        "sha256:"
    )
    with sqlite3.connect(store.db_path) as connection:
        private_lineage = json.loads(
            connection.execute(
                "SELECT derivation_json FROM frozen_query_payloads"
            ).fetchone()[0]
        )
    assert private_lineage["model_hash"] == canonical_hash({"model": "digest-model-v1"})

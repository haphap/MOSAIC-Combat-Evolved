from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l3_l4_preservation import build_l3_l4_preservation_overlay


ROOT = Path(__file__).parents[1]


def _store(tmp_path: Path) -> FrozenAdaptiveQueryStore:
    return FrozenAdaptiveQueryStore(
        tmp_path / ".mosaic/private/l3-l4-frozen.sqlite3",
        clock=lambda: datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc),
    )


def _l3_scope() -> dict:
    return {
        "as_of": "2026-07-09",
        "earliest_date": "2026-06-01",
        "accepted_candidate_tickers": ["600519.SH", "000858.SZ"],
        "indicator_families": ["macd", "rsi"],
        "candidate_scope_hash": canonical_hash({"scope": "ackman"}),
        "candidate_universe_hash": canonical_hash({"universe": "accepted"}),
        "source_snapshot_hash": canonical_hash({"snapshot": "layer2"}),
    }


def _l4_scope() -> dict:
    return {
        "as_of": "2026-07-09",
        "accepted_candidate_tickers": ["600519.SH"],
        "accepted_output_set_hash": canonical_hash({"accepted": "l1-l3"}),
        "account_positions_policy_hash": canonical_hash({"positions": "current"}),
        "market_liquidity_vintage_hash": canonical_hash({"market": "2026-07-09"}),
    }


def _ackman_initial() -> list[dict]:
    return [
        {
            "tool_id": "get_fundamentals",
            "args": {"ticker": "600519.SH", "as_of": "2026-07-09"},
        },
        {
            "tool_id": "get_cashflow",
            "args": {
                "ticker": "600519.SH",
                "frequency": "annual",
                "as_of": "2026-07-09",
            },
        },
    ]


def _ackman_followups() -> list[dict]:
    return [
        {
            "tool_id": "get_income_statement",
            "args": {
                "ticker": "000858.SZ",
                "frequency": "quarterly",
                "as_of": "2026-07-09",
            },
        },
        {
            "tool_id": "get_balance_sheet",
            "args": {
                "ticker": "000858.SZ",
                "frequency": "annual",
                "as_of": "2026-07-09",
            },
        },
        {
            "tool_id": "get_stock_data",
            "args": {
                "ticker": "600519.SH",
                "date_from": "2026-06-01",
                "date_to": "2026-07-09",
            },
        },
    ]


def _materializer(tool_id: str, args: dict) -> dict:
    return {
        "payload": json.dumps(
            {"tool": tool_id, "args": args, "private_note": "synthetic"},
            ensure_ascii=False,
        ),
        "source_receipt_hashes": [canonical_hash({"tool": tool_id, "args": args})],
    }


def test_l3_bundle_restores_initial_calls_then_three_frozen_followups(tmp_path: Path):
    store = _store(tmp_path)
    prepared = store.prepare(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-07-09",
        authorized_scope=_l3_scope(),
        initial_query_requests=_ackman_initial(),
        query_requests=_ackman_followups(),
        preservation_overlay=build_l3_l4_preservation_overlay(ROOT),
        materializer=_materializer,
    )

    public = json.dumps(prepared["public_projection"], ensure_ascii=False)
    assert "600519.SH" not in public
    assert "000858.SZ" not in public
    assert "synthetic" not in public
    assert prepared["public_projection"]["initial_payload_count"] == 2
    assert prepared["public_projection"]["adaptive_max_rounds"] == 3

    initial = store.read_initial_payloads(
        bundle_id=prepared["bundle_id"], agent_id="ackman", stage="ackman"
    )
    assert [row["tool_id"] for row in initial] == ["get_fundamentals", "get_cashflow"]
    assert all("synthetic" in row["payload"] for row in initial)

    session = store.start_session(
        bundle_id=prepared["bundle_id"], agent_id="ackman", stage="ackman"
    )
    for round_number, query in enumerate(_ackman_followups(), start=1):
        payload = store.call(
            session_id=session,
            round_number=round_number,
            tool_id=query["tool_id"],
            args=query["args"],
        )
        assert "synthetic" in payload
    with pytest.raises(ValueError, match="maximum 3 adaptive query rounds"):
        store.call(
            session_id=session,
            round_number=4,
            tool_id=_ackman_followups()[0]["tool_id"],
            args=_ackman_followups()[0]["args"],
        )


def test_l3_bundle_rejects_unaccepted_backup_and_initial_call_drift(tmp_path: Path):
    store = _store(tmp_path)
    overlay = build_l3_l4_preservation_overlay(ROOT)
    outside = _ackman_followups()
    outside[0]["args"]["ticker"] = "601318.SH"
    with pytest.raises(ValueError, match="accepted candidate scope"):
        store.prepare(
            agent_id="ackman",
            stage="ackman",
            as_of="2026-07-09",
            authorized_scope=_l3_scope(),
            initial_query_requests=_ackman_initial(),
            query_requests=outside,
            preservation_overlay=overlay,
            materializer=_materializer,
        )

    drifted_initial = _ackman_initial()
    drifted_initial[1]["args"]["frequency"] = "quarterly"
    with pytest.raises(ValueError, match="deterministic initial calls"):
        store.prepare(
            agent_id="ackman",
            stage="ackman",
            as_of="2026-07-09",
            authorized_scope=_l3_scope(),
            initial_query_requests=drifted_initial,
            query_requests=_ackman_followups(),
            preservation_overlay=overlay,
            materializer=_materializer,
        )


def test_l3_empty_scope_publishes_zero_round_bundle_without_materialization(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    scope = {**_l3_scope(), "accepted_candidate_tickers": []}
    materialized: list[tuple[str, dict]] = []

    prepared = store.prepare(
        agent_id="ackman",
        stage="ackman",
        as_of="2026-07-09",
        authorized_scope=scope,
        initial_query_requests=[],
        query_requests=[],
        preservation_overlay=build_l3_l4_preservation_overlay(ROOT),
        materializer=lambda tool_id, args: materialized.append((tool_id, args)),
    )

    projection = prepared["public_projection"]
    assert projection["private_payload_count"] == 0
    assert projection["initial_payload_count"] == 0
    assert projection["adaptive_max_rounds"] == 0
    assert projection["entries"] == []
    assert materialized == []
    assert store.read_initial_payloads(
        bundle_id=prepared["bundle_id"], agent_id="ackman", stage="ackman"
    ) == []
    with pytest.raises(ValueError, match="does not permit adaptive model calls"):
        store.start_session(
            bundle_id=prepared["bundle_id"], agent_id="ackman", stage="ackman"
        )


def test_l3_empty_scope_rejects_any_private_query(tmp_path: Path) -> None:
    store = _store(tmp_path)
    scope = {**_l3_scope(), "accepted_candidate_tickers": []}

    with pytest.raises(ValueError, match="empty candidate scope"):
        store.prepare(
            agent_id="ackman",
            stage="ackman",
            as_of="2026-07-09",
            authorized_scope=scope,
            initial_query_requests=[],
            query_requests=[
                {
                    "tool_id": "get_industry_policy_digest",
                    "args": {
                        "as_of": "2026-07-09",
                        "lookback_days": 30,
                        "source": "govcn",
                    },
                }
            ],
            preservation_overlay=build_l3_l4_preservation_overlay(ROOT),
            materializer=_materializer,
        )


def test_l4_bundle_is_proactive_stage_bound_and_has_no_model_round(tmp_path: Path):
    store = _store(tmp_path)
    prepared = store.prepare(
        agent_id="cro",
        stage="cro_review",
        as_of="2026-07-09",
        authorized_scope=_l4_scope(),
        initial_query_requests=[
            {
                "tool_id": "get_rke_research_context",
                "args": {
                    "agent_id": "cro",
                    "as_of": "2026-07-09",
                    "layer": "decision",
                    "max_items": 3,
                },
            }
        ],
        query_requests=[],
        preservation_overlay=build_l3_l4_preservation_overlay(ROOT),
        materializer=_materializer,
    )
    assert prepared["public_projection"]["initial_payload_count"] == 1
    assert prepared["public_projection"]["adaptive_max_rounds"] == 0
    initial = store.read_initial_payloads(
        bundle_id=prepared["bundle_id"], agent_id="cro", stage="cro_review"
    )
    assert initial[0]["tool_id"] == "get_rke_research_context"
    with pytest.raises(ValueError, match="does not permit adaptive model calls"):
        store.start_session(
            bundle_id=prepared["bundle_id"], agent_id="cro", stage="cro_review"
        )

    with pytest.raises(ValueError, match="stage"):
        store.read_initial_payloads(
            bundle_id=prepared["bundle_id"], agent_id="cro", stage="cro"
        )


def test_l4_active_stage_keeps_explicit_preservation_stage_binding(tmp_path: Path):
    store = _store(tmp_path)
    prepared = store.prepare(
        agent_id="cro",
        stage="cro",
        preservation_stage="cro_review",
        as_of="2026-07-09",
        authorized_scope=_l4_scope(),
        initial_query_requests=[
            {
                "tool_id": "get_rke_research_context",
                "args": {
                    "agent_id": "cro",
                    "as_of": "2026-07-09",
                    "layer": "decision",
                    "max_items": 3,
                },
            }
        ],
        query_requests=[],
        preservation_overlay=build_l3_l4_preservation_overlay(ROOT),
        materializer=_materializer,
    )

    assert prepared["public_projection"]["stage"] == "cro"
    assert prepared["public_projection"]["preservation_stage"] == "cro_review"
    initial = store.read_initial_payloads(
        bundle_id=prepared["bundle_id"], agent_id="cro", stage="cro"
    )
    assert initial[0]["tool_id"] == "get_rke_research_context"
    with pytest.raises(ValueError, match="stage"):
        store.read_initial_payloads(
            bundle_id=prepared["bundle_id"], agent_id="cro", stage="cro_review"
        )

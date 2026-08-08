from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.sector_relationship_preservation import (
    build_sector_relationship_preservation_overlay,
)


ROOT = Path(__file__).parents[1]


def _scope() -> dict:
    return {
        "as_of": "2026-07-09",
        "earliest_date": "2026-06-01",
        "tickers": ["600000.SH", "601398.SH"],
        "etfs": ["512800.SH"],
        "sectors": ["银行", "证券"],
        "indicator_families": ["macd", "rsi"],
    }


def _queries() -> list[dict]:
    return [
        {
            "tool_id": "get_broker_research",
            "args": {
                "ticker": "600000.SH",
                "date_from": "2026-06-01",
                "date_to": "2026-07-09",
                "max_reports": 30,
            },
        },
        {
            "tool_id": "get_etf_holdings",
            "args": {"etf": "512800.SH", "as_of": "2026-07-09", "top_n": 8},
        },
        {
            "tool_id": "get_indicators",
            "args": {
                "ticker": "600000.SH",
                "as_of": "2026-07-09",
                "lookback": 30,
                "indicator": "macd",
            },
        },
    ]


def _store(tmp_path: Path) -> FrozenAdaptiveQueryStore:
    return FrozenAdaptiveQueryStore(
        tmp_path / ".mosaic/private/frozen-queries.sqlite3",
        clock=lambda: datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc),
    )


def _materialized_result(tool_id: str, args: dict, *, payload: str) -> dict:
    result = {
        "payload": payload,
        "source_receipt_hashes": [canonical_hash({"source": tool_id, "args": args})],
    }
    if tool_id == "get_broker_research":
        result["derivation"] = {
            "derivation_contract_version": "frozen_research_digest_lineage_v1",
            "model_hash": canonical_hash({"model": "test"}),
            "prompt_hash": canonical_hash({"prompt": "test"}),
            "source_payload_hash": canonical_hash({"source_payload": args}),
        }
    return result


def test_prepare_may_transport_but_calls_only_read_frozen_private_payloads(tmp_path: Path):
    store = _store(tmp_path)
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    transports: list[tuple[str, dict]] = []

    def materialize(tool_id: str, args: dict) -> dict:
        transports.append((tool_id, args))
        return _materialized_result(
            tool_id,
            args,
            payload=json.dumps(
                {
                    "tool": tool_id,
                    "licensed_abstract": "synthetic private prose",
                    "args": args,
                },
                ensure_ascii=False,
            ),
        )

    prepared = store.prepare(
        agent_id="financials",
        stage="financials",
        as_of="2026-07-09",
        authorized_scope=_scope(),
        query_requests=_queries(),
        preservation_overlay=overlay,
        materializer=materialize,
    )
    assert len(transports) == 3
    public = prepared["public_projection"]
    serialized_public = json.dumps(public, ensure_ascii=False)
    assert "synthetic private prose" not in serialized_public
    assert "600000.SH" not in serialized_public
    assert "512800.SH" not in serialized_public
    assert "args" not in serialized_public
    assert public["private_payload_count"] == 3

    session = store.start_session(
        bundle_id=prepared["bundle_id"],
        agent_id="financials",
        stage="financials",
    )
    first = store.call(
        session_id=session,
        round_number=1,
        tool_id="get_broker_research",
        args=_queries()[0]["args"],
    )
    second = store.call(
        session_id=session,
        round_number=2,
        tool_id="get_etf_holdings",
        args=_queries()[1]["args"],
    )
    assert "synthetic private prose" in first
    assert "synthetic private prose" in second
    assert len(transports) == 3


def test_prepare_requires_declared_digest_derivation_lineage(tmp_path: Path):
    store = _store(tmp_path)
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    query = _queries()[0]
    kwargs = {
        "agent_id": "financials",
        "stage": "financials",
        "as_of": "2026-07-09",
        "authorized_scope": _scope(),
        "query_requests": [query],
        "preservation_overlay": overlay,
    }

    with pytest.raises(ValueError, match="requires derivation lineage"):
        store.prepare(
            **kwargs,
            materializer=lambda tool_id, args: {
                "payload": "digest-without-lineage",
                "source_receipt_hashes": [canonical_hash({"source": tool_id})],
            },
        )

    prepared = store.prepare(
        **kwargs,
        materializer=lambda tool_id, args: _materialized_result(
            tool_id, args, payload="digest-with-lineage"
        ),
    )
    assert prepared["public_projection"]["entries"][0]["derivation_hash"].startswith(
        "sha256:"
    )


def test_three_round_limit_and_round_sequence_fail_closed(tmp_path: Path):
    store = _store(tmp_path)
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    prepared = store.prepare(
        agent_id="financials",
        stage="financials",
        as_of="2026-07-09",
        authorized_scope=_scope(),
        query_requests=_queries(),
        preservation_overlay=overlay,
        materializer=lambda tool_id, args: _materialized_result(
            tool_id,
            args,
            payload=f"payload:{tool_id}:{canonical_hash(args)}",
        ),
    )
    session = store.start_session(
        bundle_id=prepared["bundle_id"],
        agent_id="financials",
        stage="financials",
    )
    for index, query in enumerate(_queries(), start=1):
        store.call(
            session_id=session,
            round_number=index,
            tool_id=query["tool_id"],
            args=query["args"],
        )
    with pytest.raises(ValueError, match="maximum 3 adaptive query rounds"):
        store.call(
            session_id=session,
            round_number=4,
            tool_id=_queries()[0]["tool_id"],
            args=_queries()[0]["args"],
        )

    other_session = store.start_session(
        bundle_id=prepared["bundle_id"],
        agent_id="financials",
        stage="financials",
    )
    with pytest.raises(ValueError, match="next round must be 1"):
        store.call(
            session_id=other_session,
            round_number=2,
            tool_id=_queries()[0]["tool_id"],
            args=_queries()[0]["args"],
        )


@pytest.mark.parametrize(
    "query,match",
    [
        (
            {
                "tool_id": "get_broker_research",
                "args": {
                    "ticker": "000001.SZ",
                    "date_from": "2026-06-01",
                    "date_to": "2026-07-09",
                    "max_reports": 30,
                },
            },
            "ticker is outside the authorized scope",
        ),
        (
            {
                "tool_id": "get_broker_research",
                "args": {
                    "ticker": "600000.SH",
                    "date_from": "2026-07-10",
                    "date_to": "2026-07-09",
                    "max_reports": 30,
                },
            },
            "inclusive date interval",
        ),
        (
            {
                "tool_id": "get_etf_holdings",
                "args": {"etf": "512800.SH", "as_of": "2026-07-09", "top_n": 13},
            },
            "argument schema",
        ),
        (
            {
                "tool_id": "get_indicators",
                "args": {
                    "ticker": "600000.SH",
                    "as_of": "2026-07-09",
                    "lookback": 30,
                    "indicator": "adx",
                },
            },
            "argument schema",
        ),
    ],
)
def test_prepare_rejects_unauthorized_or_invalid_queries(
    tmp_path: Path, query: dict, match: str
):
    store = _store(tmp_path)
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    with pytest.raises(ValueError, match=match):
        store.prepare(
            agent_id="financials",
            stage="financials",
            as_of="2026-07-09",
            authorized_scope=_scope(),
            query_requests=[query],
            preservation_overlay=overlay,
            materializer=lambda tool_id, args: {
                "payload": "must not be called",
                "source_receipt_hashes": [canonical_hash({"source": tool_id})],
            },
        )


def test_call_rejects_unfrozen_args_and_detects_private_payload_tampering(tmp_path: Path):
    store = _store(tmp_path)
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    prepared = store.prepare(
        agent_id="financials",
        stage="financials",
        as_of="2026-07-09",
        authorized_scope=_scope(),
        query_requests=[_queries()[0]],
        preservation_overlay=overlay,
        materializer=lambda tool_id, args: _materialized_result(
            tool_id, args, payload="frozen-payload"
        ),
    )
    session = store.start_session(
        bundle_id=prepared["bundle_id"],
        agent_id="financials",
        stage="financials",
    )
    changed_args = {**_queries()[0]["args"], "max_reports": 29}
    with pytest.raises(ValueError, match="not present in the frozen query bundle"):
        store.call(
            session_id=session,
            round_number=1,
            tool_id="get_broker_research",
            args=changed_args,
        )

    with sqlite3.connect(store.db_path) as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute(
                "UPDATE frozen_query_payloads SET payload = ?",
                ("tampered",),
            )
        connection.execute("DROP TRIGGER frozen_query_payloads_no_update")
        connection.execute(
            "UPDATE frozen_query_payloads SET payload = ?",
            ("tampered",),
        )
    with pytest.raises(ValueError, match="payload hash mismatch"):
        store.call(
            session_id=session,
            round_number=1,
            tool_id="get_broker_research",
            args=_queries()[0]["args"],
        )


def test_same_materialization_key_reuses_one_frozen_result(tmp_path: Path):
    store = _store(tmp_path)
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    calls = 0

    def materialize(tool_id: str, args: dict) -> dict:
        nonlocal calls
        calls += 1
        return _materialized_result(tool_id, args, payload=f"payload-{calls}")

    kwargs = {
        "agent_id": "financials",
        "stage": "financials",
        "as_of": "2026-07-09",
        "authorized_scope": _scope(),
        "query_requests": [_queries()[0]],
        "preservation_overlay": overlay,
        "materializer": materialize,
    }
    first = store.prepare(**kwargs)
    second = store.prepare(**kwargs)
    assert first == second
    assert calls == 1


def test_concurrent_same_materialization_key_transports_once(tmp_path: Path):
    store = _store(tmp_path)
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    entered = threading.Event()
    release = threading.Event()
    second_transport = threading.Event()
    count_lock = threading.Lock()
    calls = 0

    def materialize(tool_id: str, args: dict) -> dict:
        nonlocal calls
        with count_lock:
            calls += 1
            if calls == 2:
                second_transport.set()
        entered.set()
        assert release.wait(timeout=5)
        return _materialized_result(tool_id, args, payload="single-frozen-result")

    kwargs = {
        "agent_id": "financials",
        "stage": "financials",
        "as_of": "2026-07-09",
        "authorized_scope": _scope(),
        "query_requests": [_queries()[0]],
        "preservation_overlay": overlay,
        "materializer": materialize,
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(store.prepare, **kwargs)
        assert entered.wait(timeout=5)
        second = executor.submit(store.prepare, **kwargs)
        assert not second_transport.wait(timeout=0.2)
        release.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert calls == 1

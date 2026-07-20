from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from mosaic.bridge.tool_capabilities import AGENTS_BY_LAYER, ALL_AGENT_IDS
from mosaic.scorecard import ScorecardStore
from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.store import (
    _display_pct,
    _display_truncate,
    render_agent_display_narrative_text,
)


def test_cross_runtime_percentage_and_unicode_truncation_contract():
    fixture_path = (
        Path(__file__).parent / "fixtures" / "agent_display_cross_runtime_cases.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for case in fixture["percent_cases"]:
        assert _display_pct(case["value"]) == case["expected"]
    for case in fixture["unicode_truncation_cases"]:
        rendered = _display_truncate(case["unit"] * case["repeat"], case["maximum"])
        assert rendered == case["unit"] * case["kept"] + "…"
        assert len(rendered) == case["maximum"]


def _accepted_kind(agent: str) -> str:
    if agent in AGENTS_BY_LAYER["macro"]:
        return "MACRO_TRANSMISSION"
    if agent == "relationship_mapper":
        return "RELATIONSHIP_GRAPH"
    if agent in AGENTS_BY_LAYER["sector"]:
        return "STANDARD_SECTOR_SELECTION"
    if agent in AGENTS_BY_LAYER["superinvestor"]:
        return "SUPERINVESTOR_SELECTION"
    if agent == "cro":
        return "CRO_RISK_REVIEW"
    if agent == "alpha_discovery":
        return "ALPHA_DISCOVERY"
    if agent == "autonomous_execution":
        return "EXECUTION_ASSESSMENT"
    return "CIO_FINAL"


def _empty_accepted_payload(kind: str) -> dict:
    nested_field = {
        "STANDARD_SECTOR_SELECTION": "selection",
        "SUPERINVESTOR_SELECTION": "selection",
        "CRO_RISK_REVIEW": "review",
        "ALPHA_DISCOVERY": "selection",
        "EXECUTION_ASSESSMENT": "assessment",
        "CIO_FINAL": "decision",
    }.get(kind)
    return {nested_field: {}, "model_confidence": None} if nested_field else {}


def _accepted_lineage() -> tuple[dict, list[dict]]:
    refs: dict[str, dict] = {}
    records: list[dict] = []
    for agent in ALL_AGENT_IDS:
        accepted_kind = _accepted_kind(agent)
        payload = _empty_accepted_payload(accepted_kind)
        record_id = f"accepted:{agent}"
        body = {
            "accepted_output_id": record_id,
            "graph_run_id": "trace-1",
            "cohort_id": "cohort_default",
            "language": "zh",
            "as_of": "2026-07-18T15:00:00+08:00",
            "agent_id": agent,
            "accepted_output_kind": accepted_kind,
            "output": {
                "payload": payload,
                "evidence_bundle_ids": [f"evidence:{agent}"],
                "causal_dedupe_keys": [f"causal:{agent}"],
            },
        }
        record = {**body, "accepted_output_hash": canonical_hash(body)}
        records.append(record)
        refs[f"{accepted_kind}:{agent}"] = {
            "accepted_output_id": record_id,
            "accepted_output_hash": record["accepted_output_hash"],
            "agent_id": agent,
            "accepted_output_kind": accepted_kind,
        }
    return refs, records


def _bundle(trace_id: str = "trace-1") -> dict:
    layer_by_agent = {
        agent: layer for layer, agents in AGENTS_BY_LAYER.items() for agent in agents
    }
    refs, records = _accepted_lineage()
    records_by_agent = {row["agent_id"]: row for row in records}
    narratives = []
    for agent in ALL_AGENT_IDS:
        ref = next(row for row in refs.values() if row["agent_id"] == agent)
        body = {
            "schema_version": "agent_display_narrative_v1",
            "agent_id": agent,
            "layer": layer_by_agent[agent],
            "language": "zh",
            "source": "ACCEPTED_OUTPUT",
            "source_output_id": ref["accepted_output_id"],
            "source_output_hash": ref["accepted_output_hash"],
            "narrative_text": render_agent_display_narrative_text(
                layer=layer_by_agent[agent],
                agent_id=agent,
                output=records_by_agent[agent]["output"]["payload"],
                language="zh",
                accepted_output_kind=ref["accepted_output_kind"],
            ),
            "ui_only": True,
        }
        narratives.append(
            {
                **body,
                "narrative_id": (
                    "agent-display:"
                    + canonical_hash(body).removeprefix("sha256:")
                ),
            }
        )
    body = {
        "schema_version": "agent_display_narrative_bundle_v1",
        "trace_id": trace_id,
        "cohort": "cohort_default",
        "as_of_date": "2026-07-18",
        "language": "zh",
        "narrative_count": 28,
        "narratives": narratives,
    }
    return {**body, "bundle_hash": canonical_hash(body)}


def _rehash_bundle(bundle: dict) -> None:
    for row in bundle["narratives"]:
        body = {key: value for key, value in row.items() if key != "narrative_id"}
        row["narrative_id"] = (
            "agent-display:" + canonical_hash(body).removeprefix("sha256:")
        )
    body = {key: value for key, value in bundle.items() if key != "bundle_hash"}
    bundle["bundle_hash"] = canonical_hash(body)


def _replace_accepted_payload(
    state: dict,
    agent: str,
    payload: dict,
    *,
    accepted_output_kind: str | None = None,
) -> None:
    record = next(
        row for row in state["accepted_output_records"] if row["agent_id"] == agent
    )
    if accepted_output_kind is not None:
        record["accepted_output_kind"] = accepted_output_kind
    record["output"]["payload"] = payload
    record_body = {
        key: value for key, value in record.items() if key != "accepted_output_hash"
    }
    record["accepted_output_hash"] = canonical_hash(record_body)
    ref = next(
        row for row in state["accepted_output_refs"].values() if row["agent_id"] == agent
    )
    ref["accepted_output_hash"] = record["accepted_output_hash"]
    if accepted_output_kind is not None:
        ref["accepted_output_kind"] = accepted_output_kind
    narrative = next(
        row
        for row in state["agent_display_narratives"]["narratives"]
        if row["agent_id"] == agent
    )
    narrative["source_output_hash"] = record["accepted_output_hash"]
    narrative["narrative_text"] = render_agent_display_narrative_text(
        layer=narrative["layer"],
        agent_id=agent,
        output=payload,
        language=narrative["language"],
        accepted_output_kind=accepted_output_kind,
    )
    _rehash_bundle(state["agent_display_narratives"])


def _state(trace_id: str = "trace-1") -> dict:
    refs, records = _accepted_lineage()
    for record in records:
        record["graph_run_id"] = trace_id
        record_body = {
            key: value
            for key, value in record.items()
            if key != "accepted_output_hash"
        }
        record["accepted_output_hash"] = canonical_hash(record_body)
        ref = next(
            row
            for row in refs.values()
            if row["accepted_output_id"] == record["accepted_output_id"]
        )
        ref["accepted_output_hash"] = record["accepted_output_hash"]
    return {
        "active_cohort": "cohort_default",
        "as_of_date": "2026-07-18",
        "trace_id": trace_id,
        "accepted_output_refs": refs,
        "accepted_output_records": records,
        "outcome_stage_skips": {},
        "agent_display_narratives": _bundle(trace_id),
    }


def test_unsealed_agent_display_narratives_are_not_latest(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")

    assert store.append_agent_display_narratives_from_state(_state()) == 28
    assert store.append_agent_display_narratives_from_state(_state()) == 28

    latest = store.get_latest_agent_display_narratives("cohort_default")
    assert latest["date"] is None
    assert latest["trace_id"] is None
    assert latest["narratives"] == []
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_display_narratives").fetchone()[0] == 28


@pytest.mark.parametrize(
    ("layer", "agent", "kind", "payload", "expected_fragments"),
    [
        (
            "macro",
            "china",
            "MACRO_TRANSMISSION",
            {
                "direction": "SUPPORTIVE",
                "strength": 4,
                "persistence_horizon": "WEEKS",
                "confidence": 0.8,
                "channels": ["A股流动性"],
                "key_drivers": ["数据改善"],
                "claims": [{"statement": "中国宏观证据"}],
            },
            ("SUPPORTIVE", "数据改善", "中国宏观证据"),
        ),
        (
            "sector",
            "relationship_mapper",
            "RELATIONSHIP_GRAPH",
            {
                "predictive_graph_status": "EDGES_PRESENT",
                "factual_edges": [{"source_entity": "原油", "target_entity": "化工"}],
                "predictive_edges": [
                    {
                        "source_entity": "原油",
                        "target_entity": "化工",
                        "transmission_direction": "NEGATIVE",
                        "activation_trigger": "油价突破阈值",
                    }
                ],
                "key_drivers": [{"summary": "供应链传导"}],
                "risks": [{"summary": "映射失效"}],
                "claims": [{"statement": "关系证据"}],
            },
            ("EDGES_PRESENT", "原油 → 化工", "供应链传导"),
        ),
        (
            "sector",
            "agriculture",
            "STANDARD_SECTOR_SELECTION",
            {
                "selection": {
                    "preferred_direction": {
                        "direction_id": "oilseeds",
                        "thesis": "供给收紧",
                    },
                    "least_preferred_direction": {
                        "direction_id": "feed",
                        "thesis": "成本承压",
                    },
                    "persistence_horizon": "MONTHS",
                    "key_drivers": [{"summary": "库存下降"}],
                    "risks": [{"summary": "天气反转"}],
                    "long_picks": [
                        {
                            "ts_code": "600000.SH",
                            "position_action": "LONG",
                            "conviction": 0.7,
                            "thesis": "龙头",
                        }
                    ],
                    "short_or_avoid_picks": [],
                    "claims": [{"statement": "行业证据"}],
                },
                "model_confidence": 0.75,
            },
            ("oilseeds", "600000.SH", "行业证据"),
        ),
        (
            "superinvestor",
            "munger",
            "SUPERINVESTOR_SELECTION",
            {
                "selection": {
                    "selection_status": "SELECTED",
                    "holding_period": "YEARS",
                    "picks": [
                        {
                            "ts_code": "600519.SH",
                            "position_action": "LONG",
                            "conviction": 0.8,
                            "thesis": "护城河",
                        }
                    ],
                    "key_drivers": [{"summary": "哲学匹配"}],
                    "risks": [{"summary": "兑现较慢"}],
                    "claims": [{"statement": "公司证据"}],
                },
                "model_confidence": 0.7,
            },
            ("SELECTED", "600519.SH", "公司证据"),
        ),
        (
            "decision",
            "cro",
            "CRO_RISK_REVIEW",
            {
                "review": {
                    "review_disposition": "REVIEW_ACTIONS",
                    "candidate_actions": [
                        {
                            "ts_code": "000001.SZ",
                            "action": "VETO",
                            "reason": "风险过高",
                        }
                    ],
                    "correlated_risks": [{"summary": "拥挤"}],
                    "black_swan_scenarios": [{"summary": "流动性骤降"}],
                    "claims": [{"statement": "风险审查证据"}],
                },
                "model_confidence": 0.9,
            },
            ("000001.SZ VETO 风险过高", "拥挤", "风险审查证据"),
        ),
        (
            "decision",
            "alpha_discovery",
            "ALPHA_DISCOVERY",
            {
                "selection": {
                    "discovery_disposition": "CANDIDATES",
                    "novel_picks": [{"ts_code": "000002.SZ", "thesis": "预期差"}],
                    "claims": [{"statement": "Alpha 证据"}],
                },
                "model_confidence": 0.65,
            },
            ("000002.SZ", "预期差", "Alpha 证据"),
        ),
        (
            "decision",
            "autonomous_execution",
            "EXECUTION_ASSESSMENT",
            {
                "assessment": {
                    "execution_disposition": "ORDERS_ASSESSED",
                    "order_assessments": [
                        {
                            "ts_code": "600000.SH",
                            "feasibility": "FEASIBLE",
                            "requested_delta_weight": 0.1,
                            "predicted_cost_bps": 8,
                            "reason": "流动性足够",
                        }
                    ],
                    "claims": [{"statement": "执行证据"}],
                },
                "model_confidence": 0.85,
            },
            ("600000.SH FEASIBLE 10% 8bps", "流动性足够", "执行证据"),
        ),
        (
            "decision",
            "cio",
            "CIO_FINAL",
            {
                "decision": {
                    "decision_disposition": "TARGET_PORTFOLIO",
                    "decision_reason": "风险收益占优",
                    "target_positions": [
                        {
                            "ts_code": "600000.SH",
                            "position_decision": "ADD",
                            "target_weight": 0.1,
                        }
                    ],
                    "claims": [{"statement": "组合证据"}],
                },
                "model_confidence": 0.8,
            },
            ("600000.SH ADD → 10%", "风险收益占优", "组合证据"),
        ),
    ],
)
def test_python_projection_unwraps_real_accepted_dtos(
    layer, agent, kind, payload, expected_fragments
):
    text = render_agent_display_narrative_text(
        layer=layer,
        agent_id=agent,
        output=payload,
        language="zh",
        accepted_output_kind=kind,
    )
    assert all(fragment in text for fragment in expected_fragments)


def test_append_verifies_nested_accepted_payload_projection(tmp_path):
    state = _state()
    payload = {
        "selection": {
            "preferred_direction": {"direction_id": "oilseeds"},
            "least_preferred_direction": {"direction_id": "feed"},
            "persistence_horizon": "MONTHS",
            "key_drivers": [{"summary": "库存下降"}],
            "risks": [],
            "long_picks": [{"ts_code": "600000.SH", "thesis": "龙头"}],
            "short_or_avoid_picks": [],
            "claims": [{"statement": "行业证据"}],
        },
        "model_confidence": 0.75,
    }
    _replace_accepted_payload(
        state,
        "agriculture",
        payload,
        accepted_output_kind="STANDARD_SECTOR_SELECTION",
    )
    store = ScorecardStore(tmp_path / "scorecard.db")
    assert store.append_agent_display_narratives_from_state(state) == 28
    with store._connect() as conn:
        row = dict(
            conn.execute(
                "SELECT narrative_text FROM agent_display_narratives "
                "WHERE cohort = ? AND agent = ?",
                ("cohort_default", "agriculture"),
            ).fetchone()
        )
    assert "oilseeds" in row["narrative_text"]
    assert "600000.SH" in row["narrative_text"]


def test_empty_agent_display_narrative_read_is_stable(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")
    latest = store.get_latest_agent_display_narratives("cohort_default")
    assert latest["date"] is None
    assert latest["narratives"] == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda bundle: bundle["narratives"].reverse(), "roster or order mismatch"),
        (
            lambda bundle: bundle["narratives"][0].__setitem__("ui_only", False),
            "UI contract mismatch",
        ),
        (
            lambda bundle: bundle["narratives"][0].__setitem__("narrative_text", ""),
            "narrative_text",
        ),
    ],
)
def test_agent_display_narrative_contract_fails_closed(tmp_path, mutation, message):
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = deepcopy(_state())
    mutation(state["agent_display_narratives"])
    _rehash_bundle(state["agent_display_narratives"])
    with pytest.raises(ValueError, match=message):
        store.append_agent_display_narratives_from_state(state)


def test_ui_sidecar_does_not_write_decision_or_evaluation_tables(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")
    store.append_agent_display_narratives_from_state(_state())
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM darwinian_weights").fetchone()[0] == 0
        private_tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'knot_%'"
        ).fetchall()
        assert private_tables == []


def test_agent_display_narrative_hash_and_lineage_are_verified(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")
    bad_bundle = deepcopy(_state())
    bad_bundle["agent_display_narratives"]["bundle_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="bundle_hash mismatch"):
        store.append_agent_display_narratives_from_state(bad_bundle)

    bad_lineage = deepcopy(_state())
    bad_lineage["agent_display_narratives"]["narratives"][0][
        "source_output_hash"
    ] = "sha256:" + "f" * 64
    _rehash_bundle(bad_lineage["agent_display_narratives"])
    with pytest.raises(ValueError, match="accepted narrative lineage mismatch"):
        store.append_agent_display_narratives_from_state(bad_lineage)


def test_agent_display_narrative_rejects_caller_rehashed_prose(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = deepcopy(_state())
    state["agent_display_narratives"]["narratives"][0][
        "narrative_text"
    ] = "调用方自行编写并重签名的结论"
    _rehash_bundle(state["agent_display_narratives"])

    with pytest.raises(ValueError, match="trusted structured output"):
        store.append_agent_display_narratives_from_state(state)


def test_agent_display_narrative_rejects_forged_kind_owner(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    record = next(
        item
        for item in state["accepted_output_records"]
        if item["agent_id"] == "agriculture"
    )
    record["accepted_output_kind"] = "MACRO_TRANSMISSION"
    record_body = {
        key: value for key, value in record.items() if key != "accepted_output_hash"
    }
    record["accepted_output_hash"] = canonical_hash(record_body)
    ref = next(
        item
        for item in state["accepted_output_refs"].values()
        if item["agent_id"] == "agriculture"
    )
    ref["accepted_output_kind"] = "MACRO_TRANSMISSION"
    ref["accepted_output_hash"] = record["accepted_output_hash"]
    narrative = next(
        item
        for item in state["agent_display_narratives"]["narratives"]
        if item["agent_id"] == "agriculture"
    )
    narrative["source_output_hash"] = record["accepted_output_hash"]
    _rehash_bundle(state["agent_display_narratives"])

    with pytest.raises(ValueError, match="kind/owner mismatch"):
        store.append_agent_display_narratives_from_state(state)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("graph_run_id", "other-trace"),
        ("cohort_id", "other-cohort"),
        ("language", "en"),
        ("as_of", "2026-07-17T15:00:00+08:00"),
    ],
)
def test_agent_display_narrative_rejects_cross_run_record(
    tmp_path, field, value
):
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    record = state["accepted_output_records"][0]
    record[field] = value
    record_body = {
        key: item for key, item in record.items() if key != "accepted_output_hash"
    }
    record["accepted_output_hash"] = canonical_hash(record_body)
    ref = next(
        item
        for item in state["accepted_output_refs"].values()
        if item["accepted_output_id"] == record["accepted_output_id"]
    )
    ref["accepted_output_hash"] = record["accepted_output_hash"]
    narrative = state["agent_display_narratives"]["narratives"][0]
    narrative["source_output_hash"] = record["accepted_output_hash"]
    _rehash_bundle(state["agent_display_narratives"])

    with pytest.raises(ValueError, match="run owner mismatch"):
        store.append_agent_display_narratives_from_state(state)


def test_agent_display_narrative_rejects_forged_ref_namespace(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")
    state = _state()
    ref = state["accepted_output_refs"].pop("MACRO_TRANSMISSION:china")
    state["accepted_output_refs"]["forged:china"] = ref

    with pytest.raises(ValueError, match="accepted ref key mismatch"):
        store.append_agent_display_narratives_from_state(state)


def test_agent_display_narratives_are_append_only(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")
    store.append_agent_display_narratives_from_state(_state())

    conflicting = deepcopy(_state())
    _replace_accepted_payload(
        conflicting,
        ALL_AGENT_IDS[0],
        {
            "direction": "ADVERSE",
            "strength": 3,
            "persistence_horizon": "WEEKS",
            "confidence": 0.75,
        },
    )
    with pytest.raises(ValueError, match="conflicting append-only"):
        store.append_agent_display_narratives_from_state(conflicting)

    with store._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE agent_display_narratives SET narrative_text = ? WHERE agent = ?",
                ("mutated", ALL_AGENT_IDS[0]),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "DELETE FROM agent_display_narratives WHERE agent = ?",
                (ALL_AGENT_IDS[0],),
            )

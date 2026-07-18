from __future__ import annotations

from copy import deepcopy

import pytest

from mosaic.bridge.tool_capabilities import AGENTS_BY_LAYER, ALL_AGENT_IDS
from mosaic.scorecard import ScorecardStore

HASH = "sha256:" + ("a" * 64)


def _bundle(trace_id: str = "trace-1") -> dict:
    layer_by_agent = {
        agent: layer for layer, agents in AGENTS_BY_LAYER.items() for agent in agents
    }
    return {
        "schema_version": "agent_display_narrative_bundle_v1",
        "trace_id": trace_id,
        "cohort": "cohort_default",
        "as_of_date": "2026-07-18",
        "language": "zh",
        "narrative_count": 28,
        "bundle_hash": HASH,
        "narratives": [
            {
                "schema_version": "agent_display_narrative_v1",
                "narrative_id": "agent-display:" + ("b" * 64),
                "agent_id": agent,
                "layer": layer_by_agent[agent],
                "language": "zh",
                "source": "ACCEPTED_OUTPUT",
                "source_output_id": f"accepted:{agent}",
                "source_output_hash": HASH,
                "narrative_text": f"{agent} 的结构化决策说明",
                "ui_only": True,
            }
            for agent in ALL_AGENT_IDS
        ],
    }


def _state(trace_id: str = "trace-1") -> dict:
    return {
        "active_cohort": "cohort_default",
        "as_of_date": "2026-07-18",
        "trace_id": trace_id,
        "agent_display_narratives": _bundle(trace_id),
    }


def test_append_and_read_latest_agent_display_narratives(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")

    assert store.append_agent_display_narratives_from_state(_state()) == 28
    assert store.append_agent_display_narratives_from_state(_state()) == 28

    latest = store.get_latest_agent_display_narratives("cohort_default")
    assert latest["date"] == "2026-07-18"
    assert latest["trace_id"] == "trace-1"
    assert [row["agent_id"] for row in latest["narratives"]] == list(ALL_AGENT_IDS)
    assert all(row["ui_only"] is True for row in latest["narratives"])
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_display_narratives").fetchone()[0] == 28


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
    with pytest.raises(ValueError, match=message):
        store.append_agent_display_narratives_from_state(state)


def test_ui_sidecar_does_not_write_decision_or_evaluation_tables(tmp_path):
    store = ScorecardStore(tmp_path / "scorecard.db")
    store.append_agent_display_narratives_from_state(_state())
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM darwinian_weights").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM knot_research_tracks_v2").fetchone()[0] == 0

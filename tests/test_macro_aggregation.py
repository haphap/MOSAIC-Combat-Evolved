from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.scorecard.macro_aggregation import (
    MACRO_FACTOR_GROUPS,
    MacroAggregationRejectedError,
    aggregate_macro_transmissions,
)


def fixture():
    path = Path(__file__).parent / "fixtures" / "macro_aggregation_case.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["outputs"] = {
        agent: {"agent": agent, **output}
        for agent, output in value["outputs"].items()
    }
    return value


def test_python_formula_matches_shared_typescript_fixture():
    case = fixture()
    result = aggregate_macro_transmissions(case["outputs"], case["darwinian_weights"])
    assert result["score"] == pytest.approx(case["expected_score"])
    assert result["stance"] == case["expected_stance"]


def test_group_sizes_do_not_create_more_base_weight():
    neutral = {
        agent: {
            "agent": agent,
            "direction": "NEUTRAL",
            "strength": 0,
            "confidence": 1.0,
        }
        for agents in MACRO_FACTOR_GROUPS.values()
        for agent in agents
    }
    result = aggregate_macro_transmissions(neutral)
    assert all(group["effective_weight"] == pytest.approx(1 / 6) for group in result["groups"])


def test_missing_or_direction_strength_inconsistent_agents_reject_formal_aggregation():
    case = fixture()
    missing = dict(case["outputs"])
    missing.pop("market_breadth")
    with pytest.raises(MacroAggregationRejectedError, match="missing"):
        aggregate_macro_transmissions(missing)
    inconsistent = dict(case["outputs"])
    inconsistent["china"] = {**inconsistent["china"], "direction": "NEUTRAL", "strength": 2}
    with pytest.raises(MacroAggregationRejectedError, match="strength=0"):
        aggregate_macro_transmissions(inconsistent)

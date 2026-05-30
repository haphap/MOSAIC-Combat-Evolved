"""Tests for mosaic.mirofish.swarm — the agent-to-agent engine (Plan §11.8.1 7M.1)."""

from __future__ import annotations

import copy
import math

import pytest

from mosaic import mirofish as mf
from mosaic.mirofish import scenarios as sc
from mosaic.mirofish.swarm import ACTOR_CLASSES, LocalSwarmEngine


@pytest.fixture
def engine() -> LocalSwarmEngine:
    return LocalSwarmEngine()


def test_deterministic(engine):
    a = engine.generate_scenario("bull", seed=42)
    b = engine.generate_scenario("bull", seed=42)
    assert a["price_paths"]["000300.SH"]["prices"] == b["price_paths"]["000300.SH"]["prices"]


def test_scenario_shape_matches_montecarlo(engine):
    s = engine.generate_scenario("base", seed=7)
    # Same keys score_recommendation + the trainer rely on.
    for k in ("scenario_type", "scenario_name", "probability", "num_days", "price_paths", "final_state"):
        assert k in s
    assert s["engine"] == "swarm"
    assert s["reflexive"] is True
    for path in s["price_paths"].values():
        assert {"ticker", "start_price", "prices", "cumulative_return", "volatility"} <= path.keys()


def test_score_recommendation_works_on_swarm_output(engine):
    s = engine.generate_scenario("bull", seed=7)
    score = mf.score_recommendation(
        {"recommendation": "BUY", "tickers": ["000300.SH"], "conviction": 0.6}, s
    )
    assert 0.0 <= score <= 1.0


def test_paths_finite_and_positive(engine):
    for st in mf.SCENARIO_TYPES:
        s = engine.generate_scenario(st, seed=3)
        for path in s["price_paths"].values():
            assert all(math.isfinite(p) and p > 0 for p in path["prices"])
            assert len(path["prices"]) == s["num_days"] + 1


def test_emergence_metrics_present(engine):
    s = engine.generate_scenario("tail_up", seed=7)
    em = s["emergence"]
    assert em["n_actor_classes"] == len(ACTOR_CLASSES)
    assert 0.0 <= em["herding_index"] <= 1.0


def test_generate_all_scenarios(engine):
    out = engine.generate_all_scenarios(seed=7)
    assert [s["scenario_type"] for s in out] == list(sc.SCENARIO_TYPES)


def test_unknown_scenario_raises(engine):
    with pytest.raises(ValueError, match="scenario_type"):
        engine.generate_scenario("nope", seed=1)


def test_agent_to_agent_coupling(engine):
    """Removing the momentum actor class changes the *herding* dynamics —
    proof that actors react to each other through the shared blackboard, not
    just their own price history (the kernel's limitation)."""
    orig = copy.deepcopy(ACTOR_CLASSES)
    try:
        with_mom = engine.generate_scenario("bull", seed=7)["emergence"]["herding_index"]
        ACTOR_CLASSES.pop("momentum")
        ACTOR_CLASSES["noise"]["share"] = 0.40  # rebalance the population
        without_mom = engine.generate_scenario("bull", seed=7)["emergence"]["herding_index"]
        assert with_mom != without_mom
    finally:
        ACTOR_CLASSES.clear()
        ACTOR_CLASSES.update(orig)

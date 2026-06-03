"""Tests for the gated Phase-9 Darwinian weight rewrite."""

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.scorecard.store import ScorecardStore
from mosaic.scorecard.weights import compute_weights


COHORT = "cohort_default"
MACRO_AGENTS = [
    "central_bank",
    "geopolitical",
    "china",
    "dollar",
    "yield_curve",
    "commodities",
    "volatility",
    "emerging_markets",
]
REC_AGENTS = [
    "semiconductor",
    "energy",
    "biotech",
    "consumer",
    "industrials",
    "financials",
    "ackman",
    "cio",
]


def _cfg(**overrides):
    darwinian = {
        "weight_rewrite_enabled": True,
        "weight_start": 1.0,
        "weight_floor": 0.3,
        "weight_ceiling": 2.5,
        "top_multiplier": 1.05,
        "bottom_multiplier": 0.95,
        "min_ranked_agents_per_scope": 8,
        "min_scored_observations_per_agent": 1,
        "min_matured_agents_for_update": 8,
    }
    darwinian.update(overrides)
    return {"darwinian": darwinian}


def _store(tmp_path: Path) -> ScorecardStore:
    return ScorecardStore(db_path=tmp_path / "scorecard.db")


def _add_macro_score(store: ScorecardStore, agent: str, raw: float, date: str = "2024-02-01"):
    store.append_macro_signals_from_state(
        {
            "active_cohort": COHORT,
            "as_of_date": date,
            "layer1_outputs": {agent: {"agent": agent, "confidence": 0.5}},
            "layer1_consensus": {},
        }
    )
    with store._connect() as conn:
        row_id = conn.execute(
            "SELECT id FROM macro_signals WHERE agent=? AND date=?",
            (agent, date),
        ).fetchone()["id"]
    store.update_macro_scoring(
        row_id,
        {
            "label_type": "benchmark_fallback_5d",
            "label_source_status": "fallback",
            "raw_macro_score_5d": raw,
            "scored_at": "2024-02-10",
        },
    )


def _add_recommendation_score(
    store: ScorecardStore,
    agent: str,
    alpha: float,
    date: str = "2024-02-01",
):
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO recommendations("
            "cohort, agent, ticker, date, action, alpha_5d, scored_at"
            ") VALUES (?, ?, ?, ?, 'BUY', ?, '2024-02-10')",
            (COHORT, agent, f"{agent[:4].upper()}.SH", date, alpha),
        )


def test_evolutionary_weights_update_quartiles_and_bounds(tmp_path: Path):
    store = _store(tmp_path)
    scores = [0.08, 0.07, 0.04, 0.02, -0.01, -0.02, -0.06, -0.08]
    for agent, score in zip(MACRO_AGENTS, scores):
        _add_macro_score(store, agent, score)
    store.upsert_darwinian_weights(
        [
            {
                "cohort": COHORT,
                "agent": MACRO_AGENTS[0],
                "date": "2024-01-31",
                "weight": 2.49,
                "layer": "macro",
                "rank_scope": "macro",
            },
            {
                "cohort": COHORT,
                "agent": MACRO_AGENTS[-1],
                "date": "2024-01-31",
                "weight": 0.31,
                "layer": "macro",
                "rank_scope": "macro",
            },
        ]
    )

    out = compute_weights(store, COHORT, "2024-02-10", config=_cfg())

    assert out == {"written": 8, "agents_uniform_fallback": 6}
    weights = store.get_darwinian_weights(COHORT, date="2024-02-10")
    assert weights[MACRO_AGENTS[0]]["weight"] == pytest.approx(2.5)
    assert weights[MACRO_AGENTS[0]]["quartile"] == 1
    assert weights[MACRO_AGENTS[0]]["update_action"] == "up"
    assert weights[MACRO_AGENTS[-1]]["weight"] == pytest.approx(0.3)
    assert weights[MACRO_AGENTS[-1]]["quartile"] == 4
    assert weights[MACRO_AGENTS[-1]]["update_action"] == "down"
    assert weights[MACRO_AGENTS[3]]["weight"] == pytest.approx(1.0)
    assert weights[MACRO_AGENTS[3]]["update_action"] == "unchanged"
    assert weights[MACRO_AGENTS[0]]["performance_metric"] == "raw_macro_score_5d"
    assert weights[MACRO_AGENTS[0]]["source_table"] == "macro_signals"


def test_evolutionary_weights_skip_small_macro_population(tmp_path: Path):
    store = _store(tmp_path)
    _add_macro_score(store, "volatility", -0.5)
    _add_macro_score(store, "dollar", 0.1)
    store.upsert_darwinian_weights(
        [
            {
                "cohort": COHORT,
                "agent": "volatility",
                "date": "2024-01-31",
                "weight": 1.4,
                "layer": "macro",
                "rank_scope": "macro",
            }
        ]
    )

    out = compute_weights(store, COHORT, "2024-02-10", config=_cfg())

    assert out == {"written": 2, "agents_uniform_fallback": 1}
    weights = store.get_darwinian_weights(COHORT, date="2024-02-10")
    assert weights["volatility"]["weight"] == pytest.approx(1.4)
    assert weights["volatility"]["update_action"] == "skipped"
    assert weights["dollar"]["weight"] == pytest.approx(1.0)
    assert weights["dollar"]["update_action"] == "skipped"
    assert weights["dollar"]["quartile"] is None


def test_evolutionary_weights_share_table_for_recommendation_agents(tmp_path: Path):
    store = _store(tmp_path)
    alphas = [0.09, 0.07, 0.03, 0.02, -0.01, -0.02, -0.05, -0.08]
    for agent, alpha in zip(REC_AGENTS, alphas):
        _add_recommendation_score(store, agent, alpha)

    out = compute_weights(store, COHORT, "2024-02-10", config=_cfg())

    assert out == {"written": 8, "agents_uniform_fallback": 8}
    weights = store.get_darwinian_weights(COHORT, date="2024-02-10")
    assert weights["semiconductor"]["layer"] == "sector"
    assert weights["semiconductor"]["rank_scope"] == "recommendation"
    assert weights["semiconductor"]["performance_metric"] == "alpha_5d_mean_30d"
    assert weights["semiconductor"]["quartile"] == 1
    assert weights["semiconductor"]["weight"] == pytest.approx(1.05)
    assert weights["cio"]["layer"] == "decision"
    assert weights["cio"]["source_table"] == "recommendations"

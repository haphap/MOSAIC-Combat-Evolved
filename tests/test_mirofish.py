"""Tests for mosaic.mirofish.scenarios (Plan §11.8 Phase 7)."""

from __future__ import annotations

import numpy as np
import pytest

from mosaic import mirofish as mf
from mosaic.mirofish import scenarios as sc


# ── correlation repair ──────────────────────────────────────────────────────


def test_nearest_pd_makes_factorable():
    raw = sc._correlation_matrix(list(sc.ASSET_PARAMS))
    # The hand-set matrix is NOT positive definite.
    assert np.linalg.eigvalsh(raw).min() < 0
    pd = sc._nearest_pd(raw)
    # Repaired matrix is PD (Cholesky succeeds) with a unit diagonal.
    np.linalg.cholesky(pd)  # must not raise
    assert np.allclose(np.diag(pd), 1.0)


# ── determinism ──────────────────────────────────────────────────────────────


def test_seed_is_deterministic():
    a = mf.generate_scenario("base", seed=42)
    b = mf.generate_scenario("base", seed=42)
    assert a["price_paths"]["000300.SH"]["prices"] == b["price_paths"]["000300.SH"]["prices"]


def test_different_seeds_differ():
    a = mf.generate_scenario("base", seed=1)["price_paths"]["000300.SH"]["prices"]
    b = mf.generate_scenario("base", seed=2)["price_paths"]["000300.SH"]["prices"]
    assert a != b


# ── scenario shape ───────────────────────────────────────────────────────────


def test_generate_all_scenarios():
    out = mf.generate_all_scenarios(seed=7)
    assert [s["scenario_type"] for s in out] == list(sc.SCENARIO_TYPES)
    for s in out:
        for path in s["price_paths"].values():
            assert len(path["prices"]) == s["num_days"] + 1  # start + num_days
        assert 0.0 < s["probability"] <= 0.5


def test_unknown_scenario_type_raises():
    with pytest.raises(ValueError, match="scenario_type"):
        mf.generate_scenario("nope", seed=1)


def test_bull_beats_bear_on_index():
    out = mf.generate_all_scenarios(seed=7)
    bull = next(s for s in out if s["scenario_type"] == "bull")
    bear = next(s for s in out if s["scenario_type"] == "bear")
    assert (
        bull["price_paths"]["000300.SH"]["cumulative_return"]
        > bear["price_paths"]["000300.SH"]["cumulative_return"]
    )


def test_tail_scenarios_inject_shock_event():
    s = mf.generate_scenario("tail_down", seed=3)
    assert any(e["impact"] == "EXTREME" for e in s["events"])


# ── scoring ──────────────────────────────────────────────────────────────────


def _scenario_with_return(ret: float) -> dict:
    """A minimal scenario whose 000300.SH path has a known cumulative return,
    so scoring assertions don't depend on a noisy single random path."""
    return {
        "scenario_type": "test",
        "price_paths": {
            "000300.SH": {
                "ticker": "000300.SH",
                "start_price": 3500.0,
                "prices": [3500.0, 3500.0 * (1 + ret)],
                "cumulative_return": ret,
                "volatility": 0.2,
            }
        },
    }


def test_score_rewards_correct_direction():
    up = _scenario_with_return(0.12)
    buy = mf.score_recommendation(
        {"recommendation": "BUY", "tickers": ["000300.SH"], "conviction": 0.7}, up
    )
    sell = mf.score_recommendation(
        {"recommendation": "SELL", "tickers": ["000300.SH"], "conviction": 0.7}, up
    )
    assert buy > 0.5 > sell


def test_hold_is_neutral_with_no_tickers():
    s = mf.generate_scenario("base", seed=7)
    assert mf.score_recommendation({"recommendation": "HOLD", "tickers": []}, s) == 0.5


def test_conviction_amplifies_correct_call():
    up = _scenario_with_return(0.12)
    lo = mf.score_recommendation({"recommendation": "BUY", "tickers": ["000300.SH"], "conviction": 0.1}, up)
    hi = mf.score_recommendation({"recommendation": "BUY", "tickers": ["000300.SH"], "conviction": 0.9}, up)
    assert hi >= lo  # higher conviction on a correct call scores at least as high


def test_score_clamped_and_error_zero():
    s = mf.generate_scenario("base", seed=7)
    assert mf.score_recommendation({"error": "x"}, s) == 0.0
    v = mf.score_recommendation(
        {"recommendation": "BUY", "tickers": list(s["price_paths"])[:1], "conviction": 1.0}, s
    )
    assert 0.0 <= v <= 1.0


# ── reflexivity overlay ──────────────────────────────────────────────────────


def test_reflexivity_off_by_default_and_unchanged():
    off = mf.generate_scenario("bull", seed=42)
    explicit_off = mf.generate_scenario("bull", seed=42, reflexivity=False)
    assert off["reflexive"] is False
    assert off["price_paths"]["000300.SH"]["prices"] == explicit_off["price_paths"]["000300.SH"]["prices"]


def test_reflexive_is_deterministic():
    a = mf.generate_scenario("bull", seed=42, reflexivity=True)
    b = mf.generate_scenario("bull", seed=42, reflexivity=True)
    assert a["reflexive"] is True
    assert a["price_paths"]["000300.SH"]["prices"] == b["price_paths"]["000300.SH"]["prices"]


def test_reflexive_paths_stay_finite():
    import math

    for st in mf.SCENARIO_TYPES:
        s = mf.generate_scenario(st, seed=3, reflexivity=True)
        for path in s["price_paths"].values():
            assert all(math.isfinite(p) and p > 0 for p in path["prices"])


def test_reflexive_amplifies_trend_dispersion():
    import statistics

    base = [mf.generate_scenario("tail_up", seed=s)["price_paths"]["000300.SH"]["cumulative_return"] for s in range(30)]
    refl = [mf.generate_scenario("tail_up", seed=s, reflexivity=True)["price_paths"]["000300.SH"]["cumulative_return"] for s in range(30)]
    # The price↔behavior feedback loop widens the trend (vs an i.i.d. walk).
    assert statistics.pstdev(refl) > statistics.pstdev(base)


def test_generate_all_threads_reflexivity():
    out = mf.generate_all_scenarios(seed=7, reflexivity=True)
    assert all(s["reflexive"] is True for s in out)

"""A/B structural comparison tests (Plan §11.8.1 gate).

Locks the decisive finding: the swarm engine *can* produce reflexive return
structure that i.i.d. Monte-Carlo cannot — lag-1 return autocorrelation — and
that this structure scales with the feedback strength (so it's a tuning knob,
not noise). Monte-Carlo's autocorrelation stays ≈ 0 by construction.
"""

from __future__ import annotations

from mosaic.mirofish import swarm as sw
from mosaic.mirofish.ab_compare import _collect, compare_engines


def test_montecarlo_returns_are_uncorrelated():
    """i.i.d. Monte-Carlo → lag-1 autocorrelation ≈ 0 (the null)."""
    mc = compare_engines(n_seeds=40, num_days=30)["montecarlo"]
    assert abs(mc["ret_autocorr_lag1"]) < 0.05


def test_swarm_autocorr_materially_exceeds_montecarlo():
    """At the 7M.1b working point (impact=0.16) the swarm's reflexive loop
    yields a MATERIAL lag-1 autocorrelation gap over i.i.d. MC — and positive
    volatility clustering, the ARCH signature MC cannot produce."""
    res = compare_engines(n_seeds=60, num_days=30)
    assert res["montecarlo"]["ret_autocorr_lag1"] < 0.05  # MC ~ 0
    assert res["swarm"]["ret_autocorr_lag1"] > 0.10       # swarm clearly non-MC
    assert res["autocorr_gap"] > 0.10
    assert res["swarm"]["vol_clustering"] > res["montecarlo"]["vol_clustering"]


def test_feedback_strength_drives_reflexive_structure():
    """Capability check: cranking price impact materially raises return
    autocorrelation — proof the swarm's reflexivity is a real, tunable
    mechanism, not an artifact. (Default impact is deliberately conservative
    for stability, which is why the baseline gap is small.)"""
    orig = sw._PRICE_IMPACT
    try:
        sw._PRICE_IMPACT = 0.04
        low = _collect("swarm", list(range(40)), 30, None)["ret_autocorr_lag1"]
        sw._PRICE_IMPACT = 0.20
        high = _collect("swarm", list(range(40)), 30, None)["ret_autocorr_lag1"]
    finally:
        sw._PRICE_IMPACT = orig
    assert high > low + 0.05  # higher feedback → materially more autocorrelation
    assert high > 0.10        # and it reaches a clearly non-MC regime

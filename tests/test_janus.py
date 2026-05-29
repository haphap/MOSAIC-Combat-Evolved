"""Tests for mosaic.janus.meta (Plan §11.7 Phase 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic import janus
from mosaic.scorecard.store import ScorecardStore

COHORTS = ["crisis_2008", "bull_2016", "euphoria_2021"]
NOW = "2008-09-15T00:00:00+00:00"


@pytest.fixture
def store(tmp_path: Path) -> ScorecardStore:
    return ScorecardStore(db_path=tmp_path / "scorecard.db")


def _add_cio(store: ScorecardStore, cohort, ticker, date, action, twp, ret5d=None):
    """Insert a CIO recommendation; if ret5d given, mark it scored."""
    with store._connect() as conn:
        cur = conn.execute(
            "INSERT INTO recommendations (cohort, agent, ticker, date, action, "
            "conviction, target_weight_pct) VALUES (?,?,?,?,?,?,?)",
            (cohort, "cio", ticker, date, action, None, twp),
        )
        rid = cur.lastrowid
    if ret5d is not None:
        store.update_scoring(rid, ret5d, None, ret5d, "2008-09-20")
    return rid


# ── softmax constraints ────────────────────────────────────────────────────


class TestSoftmaxConstraints:
    def test_empty(self):
        assert janus.softmax_with_constraints({}) == {}

    def test_n2_respects_atlas_floor(self):
        w = janus.softmax_with_constraints({"a": 5.0, "b": 0.0})
        assert sum(w.values()) == pytest.approx(1.0)
        # ATLAS floor 0.2 is feasible at N=2.
        assert min(w.values()) >= 0.2 - 1e-9
        assert w["a"] > w["b"]

    def test_n7_is_feasible_and_normalised(self):
        scores = {f"c{i}": i * 0.1 for i in range(7)}
        w = janus.softmax_with_constraints(scores)
        assert sum(w.values()) == pytest.approx(1.0)
        # floor = min(0.2, 0.5/7) = 0.0714; every weight ≥ floor.
        assert min(w.values()) >= 0.5 / 7 - 1e-6
        # highest score gets the most weight.
        assert max(w, key=lambda k: w[k]) == "c6"


# ── cohort accuracy ─────────────────────────────────────────────────────────


class TestCohortAccuracy:
    def test_neutral_prior_when_no_data(self, store):
        m = janus.cohort_accuracy(store, "crisis_2008", NOW)
        assert m == {"hit_rate": 0.5, "sharpe": 0.0, "n": 0}

    def test_hit_rate_long(self, store):
        # 2 wins, 1 loss for LONG picks (within 30d of NOW).
        _add_cio(store, "crisis_2008", "A", "2008-09-10", "BUY", 50, ret5d=0.02)
        _add_cio(store, "crisis_2008", "B", "2008-09-11", "BUY", 50, ret5d=0.03)
        _add_cio(store, "crisis_2008", "C", "2008-09-12", "BUY", 50, ret5d=-0.01)
        m = janus.cohort_accuracy(store, "crisis_2008", NOW)
        assert m["n"] == 3
        assert m["hit_rate"] == pytest.approx(2 / 3)

    def test_hit_rate_short_inverts(self, store):
        # SHORT/REDUCE wins when return is negative.
        _add_cio(store, "crisis_2008", "A", "2008-09-10", "REDUCE", 50, ret5d=-0.05)
        m = janus.cohort_accuracy(store, "crisis_2008", NOW)
        assert m["hit_rate"] == pytest.approx(1.0)

    def test_window_excludes_old(self, store):
        # 60 days before NOW → outside the 30d window.
        _add_cio(store, "crisis_2008", "A", "2008-07-01", "BUY", 50, ret5d=0.02)
        m = janus.cohort_accuracy(store, "crisis_2008", NOW, window_days=30)
        assert m["n"] == 0


# ── compute_cohort_weights ──────────────────────────────────────────────────


class TestComputeWeights:
    def test_equal_when_all_cold(self, store):
        w, acc = janus.compute_cohort_weights(store, COHORTS, NOW)
        assert sum(w.values()) == pytest.approx(1.0)
        assert max(w.values()) - min(w.values()) == pytest.approx(0.0)

    def test_accurate_cohort_gets_more_weight(self, store):
        # crisis_2008: all hits; euphoria_2021: all misses.
        for i, t in enumerate("ABCD"):
            _add_cio(store, "crisis_2008", t, f"2008-09-1{i}", "BUY", 50, ret5d=0.02)
            _add_cio(store, "euphoria_2021", t, f"2008-09-1{i}", "BUY", 50, ret5d=-0.02)
        w, _ = janus.compute_cohort_weights(store, COHORTS, NOW)
        assert w["crisis_2008"] > w["euphoria_2021"]


# ── regime signal ───────────────────────────────────────────────────────────


class TestRegime:
    def test_empty(self):
        r = janus.regime_signal({})
        assert r["dominant_cohort"] is None

    def test_dominant_and_concentration(self):
        weights = {"crisis_2008": 0.6, "bull_2016": 0.2, "euphoria_2021": 0.2}
        cfg = {"crisis_2008": {"description": "暴跌 70%"}}
        r = janus.regime_signal(weights, cfg)
        assert r["dominant_cohort"] == "crisis_2008"
        assert r["regime_label"] == "暴跌 70%"
        # 0.6 - 1/3 = 0.267 > 0.10 → concentrated.
        assert r["concentration_state"] == "CONCENTRATED"

    def test_diffuse(self):
        weights = {"a": 0.34, "b": 0.33, "c": 0.33}
        assert janus.regime_signal(weights)["concentration_state"] == "DIFFUSE"


# ── blend ───────────────────────────────────────────────────────────────────


class TestBlend:
    def test_agreement_sums_weighted(self, store):
        _add_cio(store, "crisis_2008", "600519.SH", "2008-09-15", "BUY", 80)
        _add_cio(store, "bull_2016", "600519.SH", "2008-09-15", "BUY", 60)
        weights = {"crisis_2008": 0.5, "bull_2016": 0.5}
        out = janus.blend_recommendations(store, weights, "2008-09-15")
        rec = out["blended_recommendations"][0]
        assert rec["ticker"] == "600519.SH"
        assert rec["direction"] == "LONG"
        assert not rec["contested"]
        # 80*0.5 + 60*0.5 = 70
        assert rec["blended_weight_pct"] == pytest.approx(70.0)
        assert out["contested_tickers"] == []

    def test_conflict_is_contested_and_penalised(self, store):
        _add_cio(store, "crisis_2008", "X.SH", "2008-09-15", "BUY", 80)
        _add_cio(store, "bull_2016", "X.SH", "2008-09-15", "SELL", 40)
        weights = {"crisis_2008": 0.5, "bull_2016": 0.5}
        out = janus.blend_recommendations(store, weights, "2008-09-15")
        rec = out["blended_recommendations"][0]
        assert rec["contested"]
        assert rec["direction"] == "LONG"  # 40 long > 20 short
        # long=40, short=20 → 40 - 20*0.5 = 30
        assert rec["blended_weight_pct"] == pytest.approx(30.0)
        assert "X.SH" in out["contested_tickers"]


# ── run_daily persists ──────────────────────────────────────────────────────


def test_run_daily_persists(store):
    _add_cio(store, "crisis_2008", "600519.SH", "2008-09-15", "BUY", 80)
    out = janus.run_daily(store, COHORTS, "2008-09-15", now_iso=NOW)
    assert sum(out["cohort_weights"].values()) == pytest.approx(1.0, abs=1e-3)
    assert "regime" in out
    hist = store.get_janus_history()
    assert len(hist) == 1
    assert hist[0]["date"] == "2008-09-15"

    # Idempotent on date.
    janus.run_daily(store, COHORTS, "2008-09-15", now_iso=NOW)
    assert len(store.get_janus_history()) == 1

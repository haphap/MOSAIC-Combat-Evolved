"""Tests for mosaic.scorecard.weights (Plan §11.3 sub-step 3C)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mosaic.scorecard import (
    ScorecardStore,
    WEIGHT_MAX,
    WEIGHT_MIN,
    compute_weights,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> ScorecardStore:
    return ScorecardStore(db_path=tmp_path / "scorecard.db")


def _seed_scored_row(
    store: ScorecardStore,
    *,
    cohort: str,
    agent: str,
    ticker: str,
    date_iso: str,
    alpha_5d: float,
) -> None:
    """Insert + score a single row directly. Bypasses expand_state_to_recommendations."""
    state = {
        "active_cohort": cohort,
        "as_of_date": date_iso,
        "layer4_outputs": {
            "cro": None,
            "alpha_discovery": None,
            "autonomous_execution": None,
            "cio": {
                "agent": "cio",
                "portfolio_actions": [
                    {
                        "ticker": ticker,
                        "action": "BUY",
                        "target_weight": 0.5,
                        "holding_period": "6M",
                        "dissent_notes": "",
                    }
                ],
                "confidence": 0.5,
            },
        },
        "layer1_outputs": {},
        "layer2_outputs": {},
        "layer3_outputs": {},
    }
    store.append_from_state(state)
    # Find the new row id and score it. We override 'agent' afterwards so a single
    # cohort can have multiple agents in tests.
    with store._connect() as conn:
        # Update agent name in-place (cio is the only one append_from_state adds)
        conn.execute(
            "UPDATE recommendations SET agent = ? WHERE cohort = ? AND ticker = ? AND date = ?",
            (agent, cohort, ticker, date_iso),
        )
        row_id = conn.execute(
            "SELECT id FROM recommendations WHERE cohort = ? AND agent = ? AND ticker = ? AND date = ?",
            (cohort, agent, ticker, date_iso),
        ).fetchone()["id"]
    store.update_scoring(
        row_id=row_id,
        forward_return_5d=alpha_5d + 0.01,  # arbitrary
        forward_return_21d=None,
        alpha_5d=alpha_5d,
        scored_at="2024-12-31",
    )


def _seed_alpha_series(
    store: ScorecardStore,
    *,
    cohort: str,
    agent: str,
    alphas: list[float],
    end_date_iso: str = "2024-07-31",
) -> None:
    """Seed N consecutive trading days (Mon-Fri, weekdays only) ending end_date.

    Length determined by len(alphas).
    """
    base = datetime.strptime(end_date_iso, "%Y-%m-%d").date()
    dates = []
    cur = base
    while len(dates) < len(alphas):
        if cur.weekday() < 5:
            dates.append(cur.isoformat())
        cur -= timedelta(days=1)
    dates.reverse()  # oldest first
    for date_iso, alpha in zip(dates, alphas):
        _seed_scored_row(
            store,
            cohort=cohort,
            agent=agent,
            ticker=f"{agent}.SH",  # unique per (agent, date) for UNIQUE constraint
            date_iso=date_iso,
            alpha_5d=alpha,
        )


# ---------------------------------------------------------------------------
# Empty / sparse data
# ---------------------------------------------------------------------------


class TestSparseData:
    def test_empty_store_writes_nothing(self, store: ScorecardStore):
        out = compute_weights(store, "cohort_default", "2024-07-31")
        assert out["written"] == 0
        assert out["agents_uniform_fallback"] == 0

    def test_below_min_obs_yields_uniform_weight(self, store: ScorecardStore):
        # 4 observations < MIN_OBS_FOR_SHARPE (5)
        _seed_alpha_series(
            store,
            cohort="cohort_default",
            agent="ackman",
            alphas=[0.01, 0.02, 0.0, 0.005],
        )
        out = compute_weights(store, "cohort_default", "2024-07-31")
        assert out["written"] == 1
        assert out["agents_uniform_fallback"] == 1

        weights = store.get_darwinian_weights("cohort_default", "2024-07-31")
        ackman = weights["ackman"]
        assert ackman["weight"] == pytest.approx(1.0)
        assert ackman["sharpe_30"] is None
        assert ackman["quartile"] == 4  # default fallback


# ---------------------------------------------------------------------------
# Sharpe + weight calculation
# ---------------------------------------------------------------------------


class TestSharpeAndWeight:
    def test_consistent_positive_alpha_yields_high_sharpe(self, store: ScorecardStore):
        # Constant +1% alpha → std=0 → Sharpe=0 (treated as neutral)
        # Use a slight variance so Sharpe is positive.
        alphas = [0.010, 0.011, 0.009, 0.012, 0.008, 0.011, 0.010]
        _seed_alpha_series(store, cohort="cohort_default", agent="ackman", alphas=alphas)
        out = compute_weights(store, "cohort_default", "2024-07-31")
        assert out["agents_uniform_fallback"] == 0

        weights = store.get_darwinian_weights("cohort_default", "2024-07-31")
        ackman = weights["ackman"]
        assert ackman["sharpe_30"] is not None
        assert ackman["sharpe_30"] > 5.0  # positive mean, low std → very high Sharpe
        assert ackman["weight"] == pytest.approx(WEIGHT_MAX)  # clipped at 2.5
        assert ackman["quartile"] == 1  # only agent → top quartile

    def test_negative_alpha_yields_low_weight(self, store: ScorecardStore):
        alphas = [-0.010, -0.012, -0.008, -0.011, -0.010, -0.009, -0.013]
        _seed_alpha_series(store, cohort="cohort_default", agent="ackman", alphas=alphas)
        compute_weights(store, "cohort_default", "2024-07-31")
        weights = store.get_darwinian_weights("cohort_default", "2024-07-31")
        ackman = weights["ackman"]
        assert ackman["sharpe_30"] is not None
        assert ackman["sharpe_30"] < 0
        # 0.5 + (large negative) → clipped to WEIGHT_MIN
        assert ackman["weight"] == pytest.approx(WEIGHT_MIN)

    def test_zero_variance_yields_neutral_sharpe(self, store: ScorecardStore):
        # All identical alphas → std=0 → _sharpe returns 0.0 (neutral)
        alphas = [0.005] * 6
        _seed_alpha_series(store, cohort="cohort_default", agent="ackman", alphas=alphas)
        compute_weights(store, "cohort_default", "2024-07-31")
        weights = store.get_darwinian_weights("cohort_default", "2024-07-31")
        ackman = weights["ackman"]
        assert ackman["sharpe_30"] == pytest.approx(0.0)
        # 0.5 + 0 = 0.5 → within bounds
        assert ackman["weight"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Quartile bucketing
# ---------------------------------------------------------------------------


class TestQuartiles:
    def test_quartile_assignment_across_agents(self, store: ScorecardStore):
        """Seed 4 agents with distinct Sharpe profiles; expect quartiles 1-4."""
        # Top: high positive
        _seed_alpha_series(
            store,
            cohort="cohort_default",
            agent="agent_top",
            alphas=[0.02, 0.022, 0.018, 0.021, 0.019, 0.02],
        )
        # Q2: moderate positive
        _seed_alpha_series(
            store,
            cohort="cohort_default",
            agent="agent_q2",
            alphas=[0.005, 0.006, 0.004, 0.005, 0.005, 0.006],
        )
        # Q3: ~0
        _seed_alpha_series(
            store,
            cohort="cohort_default",
            agent="agent_q3",
            alphas=[0.000, 0.001, -0.001, 0.000, 0.001, -0.001],
        )
        # Bottom: negative
        _seed_alpha_series(
            store,
            cohort="cohort_default",
            agent="agent_bot",
            alphas=[-0.01, -0.012, -0.008, -0.011, -0.009, -0.01],
        )

        compute_weights(store, "cohort_default", "2024-07-31")
        weights = store.get_darwinian_weights("cohort_default", "2024-07-31")

        assert weights["agent_top"]["quartile"] == 1
        assert weights["agent_bot"]["quartile"] == 4
        # Middle two land in 2 and 3
        assert weights["agent_q2"]["quartile"] in (2, 3)
        assert weights["agent_q3"]["quartile"] in (2, 3)
        assert weights["agent_q2"]["quartile"] != weights["agent_q3"]["quartile"]

        # Sharpe ranking sanity
        assert weights["agent_top"]["sharpe_30"] > weights["agent_bot"]["sharpe_30"]


# ---------------------------------------------------------------------------
# Window filtering
# ---------------------------------------------------------------------------


class TestWindowFilter:
    def test_only_recent_30d_used(self, store: ScorecardStore):
        # Old dates within 90d window but outside 30d window. Include slight
        # variance so 90d Sharpe is non-zero.
        # 30d cutoff from 2024-07-31 = 2024-07-01; 90d cutoff = 2024-05-02.
        old_dates = ["2024-06-01", "2024-06-04", "2024-06-05", "2024-06-06", "2024-06-07"]
        recent_dates = [
            "2024-07-22",
            "2024-07-23",
            "2024-07-24",
            "2024-07-25",
            "2024-07-26",
            "2024-07-29",
        ]
        # Old: very-positive alphas with slight variance
        for d, alpha in zip(old_dates, [0.05, 0.052, 0.048, 0.051, 0.049]):
            _seed_scored_row(
                store,
                cohort="cohort_default",
                agent="ackman",
                ticker=f"OLD-{d}",
                date_iso=d,
                alpha_5d=alpha,
            )
        # Recent: mild positive with slight variance
        for d, alpha in zip(
            recent_dates, [0.001, 0.0012, 0.0008, 0.001, 0.0011, 0.0009]
        ):
            _seed_scored_row(
                store,
                cohort="cohort_default",
                agent="ackman",
                ticker=f"REC-{d}",
                date_iso=d,
                alpha_5d=alpha,
            )

        compute_weights(store, "cohort_default", "2024-07-31")
        weights = store.get_darwinian_weights("cohort_default", "2024-07-31")
        ackman = weights["ackman"]
        # Both windows produce a Sharpe; they should differ since 90d sees the
        # high-mean / high-variance old data while 30d only sees the recent
        # mild data. Direction depends on mean-vs-std contributions, but
        # "the window filter actually filters" is the meaningful invariant.
        assert ackman["sharpe_30"] is not None
        assert ackman["sharpe_90"] is not None
        assert abs(ackman["sharpe_30"] - ackman["sharpe_90"]) > 1.0

    def test_idempotent_re_run_overwrites_same_date(self, store: ScorecardStore):
        _seed_alpha_series(
            store,
            cohort="cohort_default",
            agent="ackman",
            alphas=[0.01, 0.011, 0.009, 0.010, 0.012, 0.011],
        )
        compute_weights(store, "cohort_default", "2024-07-31")
        compute_weights(store, "cohort_default", "2024-07-31")  # re-run
        with store._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM darwinian_weights WHERE cohort='cohort_default'"
            ).fetchone()[0]
        assert count == 1  # UPSERT, not INSERT


# ---------------------------------------------------------------------------
# Annualization sanity
# ---------------------------------------------------------------------------


def test_annualization_factor():
    """Sanity check the annualization constant — 5d horizon."""
    from mosaic.scorecard.weights import ANNUALIZATION

    assert ANNUALIZATION == pytest.approx(math.sqrt(252.0 / 5.0))
    assert ANNUALIZATION == pytest.approx(7.099, abs=0.01)

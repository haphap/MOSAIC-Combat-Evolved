"""Tests for mosaic.scorecard.scorer (Plan §11.3 sub-step 3B)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.dataflows import calendar as cal
from mosaic.scorecard import ScorecardStore, Scorer
from mosaic.scorecard import scorer as scorer_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_state(date: str = "2024-06-24") -> dict:
    """Minimal state with two L4 cio rows (semi + consumer)."""
    return {
        "active_cohort": "cohort_default",
        "as_of_date": date,
        "layer1_outputs": {},
        "layer2_outputs": {},
        "layer3_outputs": {},
        "layer4_outputs": {
            "cro": None,
            "alpha_discovery": None,
            "autonomous_execution": None,
            "cio": {
                "agent": "cio",
                "portfolio_actions": [
                    {
                        "ticker": "688981.SH",
                        "action": "BUY",
                        "target_weight": 0.4,
                        "holding_period": "6M",
                        "dissent_notes": "",
                    },
                    {
                        "ticker": "600519.SH",
                        "action": "BUY",
                        "target_weight": 0.3,
                        "holding_period": "5Y+",
                        "dissent_notes": "",
                    },
                ],
                "confidence": 0.55,
            },
        },
    }


def _populate_calendar() -> None:
    """Pre-populate calendar with 30 weekdays starting Mon 2024-06-24."""
    from datetime import datetime, timedelta

    base = datetime.strptime("2024-06-24", "%Y-%m-%d").date()
    days = {}
    for i in range(40):
        d = base + timedelta(days=i)
        days[d.isoformat()] = d.weekday() < 5
    cal.populate_cache_for_test(days)


@pytest.fixture(autouse=True)
def _reset_calendar():
    cal.clear_cache()
    yield
    cal.clear_cache()


@pytest.fixture
def store(tmp_path: Path) -> ScorecardStore:
    return ScorecardStore(db_path=tmp_path / "scorecard.db")


@pytest.fixture
def populated_store(store: ScorecardStore) -> ScorecardStore:
    """Store with one ingested state."""
    store.append_from_state(_sample_state())
    return store


# ---------------------------------------------------------------------------
# Mock _fetch_close
# ---------------------------------------------------------------------------


def _make_fetcher(prices: dict[tuple[str, str], float | None]):
    """Closure factory for monkeypatching _fetch_close.

    ``prices`` maps (ticker, date_iso) → close (or None for missing data).
    """

    def fetch(ts_code: str, target_date_iso: str):
        return prices.get((ts_code, target_date_iso))

    return fetch


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class TestScorer:
    def test_skips_immature_rows(self, populated_store, monkeypatch):
        """If today is too close to the row date, skip without writing."""
        _populate_calendar()
        monkeypatch.setattr(scorer_module, "_fetch_close", _make_fetcher({}))

        scorer = Scorer(populated_store)
        # Today is the SAME day as the row → 5d horizon hasn't matured.
        out = scorer.score_pending("cohort_default", "2024-06-24")
        assert out["scored"] == 0
        assert out["skipped_immature"] == 0  # rows aren't even queried, list_pending filters

    def test_scores_5d_only_when_21d_immature(
        self, populated_store, monkeypatch
    ):
        """5d horizon scored, 21d horizon left NULL until matured."""
        _populate_calendar()
        # Mon 2024-06-24 + 5 trading days = Mon 2024-07-01
        # Mon 2024-06-24 + 21 trading days = Mon 2024-07-22 (NOT YET matured if today=07-02)
        prices = {
            # Stock prices
            ("688981.SH", "2024-06-24"): 100.0,
            ("688981.SH", "2024-07-01"): 105.0,  # +5%
            ("600519.SH", "2024-06-24"): 1000.0,
            ("600519.SH", "2024-07-01"): 1020.0,  # +2%
            # Benchmark
            ("000300.SH", "2024-06-24"): 3500.0,
            ("000300.SH", "2024-07-01"): 3535.0,  # +1%
        }
        monkeypatch.setattr(scorer_module, "_fetch_close", _make_fetcher(prices))

        scorer = Scorer(populated_store)
        out = scorer.score_pending("cohort_default", "2024-07-02")
        assert out["scored"] == 2

        scored = populated_store.list_scored("cohort_default")
        assert len(scored) == 2
        semi = next(r for r in scored if r["ticker"] == "688981.SH")
        assert semi["forward_return_5d"] == pytest.approx(0.05)
        assert semi["forward_return_21d"] is None  # 21d not matured
        assert semi["alpha_5d"] == pytest.approx(0.04)  # 5% - 1%
        assert semi["scored_at"] == "2024-07-02"

    def test_scores_both_horizons_when_matured(
        self, populated_store, monkeypatch
    ):
        _populate_calendar()
        # 21d from 2024-06-24 = Mon 2024-07-22
        prices = {
            ("688981.SH", "2024-06-24"): 100.0,
            ("688981.SH", "2024-07-01"): 105.0,
            ("688981.SH", "2024-07-23"): 110.0,
            ("600519.SH", "2024-06-24"): 1000.0,
            ("600519.SH", "2024-07-01"): 1020.0,
            ("600519.SH", "2024-07-23"): 1050.0,
            ("000300.SH", "2024-06-24"): 3500.0,
            ("000300.SH", "2024-07-01"): 3535.0,
            ("000300.SH", "2024-07-23"): 3570.0,
        }
        monkeypatch.setattr(scorer_module, "_fetch_close", _make_fetcher(prices))
        # Use a later "today" so the 21d horizon (Tue 2024-07-23) has matured.
        scorer = Scorer(populated_store)
        out = scorer.score_pending("cohort_default", "2024-07-25")
        assert out["scored"] == 2

        scored = populated_store.list_scored("cohort_default")
        semi = next(r for r in scored if r["ticker"] == "688981.SH")
        assert semi["forward_return_5d"] == pytest.approx(0.05)
        assert semi["forward_return_21d"] == pytest.approx(0.10)
        assert semi["alpha_5d"] == pytest.approx(0.04)

    def test_suspended_ticker_marked_scored_with_null_returns(
        self, populated_store, monkeypatch
    ):
        _populate_calendar()
        # 688981.SH suspended (no close on either date); 600519 normal
        prices = {
            ("688981.SH", "2024-06-24"): None,
            ("688981.SH", "2024-07-01"): None,
            ("600519.SH", "2024-06-24"): 1000.0,
            ("600519.SH", "2024-07-01"): 1020.0,
            ("000300.SH", "2024-06-24"): 3500.0,
            ("000300.SH", "2024-07-01"): 3535.0,
        }
        monkeypatch.setattr(scorer_module, "_fetch_close", _make_fetcher(prices))

        scorer = Scorer(populated_store)
        out = scorer.score_pending("cohort_default", "2024-07-02")
        assert out["scored"] == 2
        assert out["skipped_missing"] == 1

        # 688981 row marked scored but with NULL returns (drops from pending)
        pending = populated_store.list_pending(cohort="cohort_default")
        assert len(pending) == 0  # all moved out of pending

    def test_benchmark_missing_yields_null_alpha(
        self, populated_store, monkeypatch
    ):
        _populate_calendar()
        # Stock prices fine, benchmark missing → forward_return populated, alpha NULL
        prices = {
            ("688981.SH", "2024-06-24"): 100.0,
            ("688981.SH", "2024-07-01"): 105.0,
            ("600519.SH", "2024-06-24"): 1000.0,
            ("600519.SH", "2024-07-01"): 1020.0,
            # Benchmark not available
        }
        monkeypatch.setattr(scorer_module, "_fetch_close", _make_fetcher(prices))

        scorer = Scorer(populated_store)
        out = scorer.score_pending("cohort_default", "2024-07-02")
        assert out["scored"] == 2

        scored = populated_store.list_scored("cohort_default")
        assert all(r["forward_return_5d"] is not None for r in scored)
        # alpha_5d should still be NULL — but list_scored excludes alpha_5d IS NULL.
        # So we re-query with full SELECT.
        with populated_store._connect() as conn:
            rows = conn.execute(
                "SELECT alpha_5d FROM recommendations ORDER BY id"
            ).fetchall()
        assert all(r["alpha_5d"] is None for r in rows)

    def test_benchmark_override_via_env(
        self, populated_store, monkeypatch
    ):
        _populate_calendar()
        monkeypatch.setenv("MOSAIC_BENCHMARK_TICKER", "000016.SH")
        monkeypatch.setattr(scorer_module, "_fetch_close", _make_fetcher({}))

        scorer = Scorer(populated_store)
        assert scorer.benchmark == "000016.SH"

    def test_idempotent_scored_at_filter(self, populated_store, monkeypatch):
        """Re-running scorer should not re-score already-scored rows."""
        _populate_calendar()
        prices = {
            ("688981.SH", "2024-06-24"): 100.0,
            ("688981.SH", "2024-07-01"): 105.0,
            ("600519.SH", "2024-06-24"): 1000.0,
            ("600519.SH", "2024-07-01"): 1020.0,
            ("000300.SH", "2024-06-24"): 3500.0,
            ("000300.SH", "2024-07-01"): 3535.0,
        }
        monkeypatch.setattr(scorer_module, "_fetch_close", _make_fetcher(prices))

        scorer = Scorer(populated_store)
        out1 = scorer.score_pending("cohort_default", "2024-07-02")
        out2 = scorer.score_pending("cohort_default", "2024-07-02")
        assert out1["scored"] == 2
        assert out2["scored"] == 0  # nothing pending after first pass

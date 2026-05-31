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
# _fetch_close routing (stock / index / ETF)
# ---------------------------------------------------------------------------


class _FakePro:
    """Records which Tushare endpoint was hit and returns a 1-row close frame."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _frame(self, close: float):
        import pandas as pd

        return pd.DataFrame({"close": [close]})

    def daily(self, **kw):
        self.calls.append("daily")
        return self._frame(10.0)

    def index_daily(self, **kw):
        self.calls.append("index_daily")
        return self._frame(3500.0)

    def fund_daily(self, **kw):
        self.calls.append("fund_daily")
        return self._frame(4.2)


class TestFetchCloseRouting:
    @pytest.fixture
    def fake_pro(self, monkeypatch):
        pro = _FakePro()
        import mosaic.dataflows.tushare as tushare_mod

        monkeypatch.setattr(tushare_mod, "_get_pro_client", lambda: pro)
        return pro

    def test_etf_routes_to_fund_daily(self, fake_pro):
        # 510300.SH (沪深300 ETF) and 159915.SZ (创业板 ETF) are funds.
        assert scorer_module._fetch_close("510300.SH", "2024-06-24") == 4.2
        assert scorer_module._fetch_close("159915.SZ", "2024-06-24") == 4.2
        assert fake_pro.calls == ["fund_daily", "fund_daily"]

    def test_index_routes_to_index_daily(self, fake_pro):
        assert scorer_module._fetch_close("000300.SH", "2024-06-24") == 3500.0
        assert fake_pro.calls == ["index_daily"]

    def test_stock_routes_to_daily(self, fake_pro):
        # 600519.SH (Moutai) and 000001.SZ (Ping An Bank) are stocks, not ETFs.
        assert scorer_module._fetch_close("600519.SH", "2024-06-24") == 10.0
        assert scorer_module._fetch_close("000001.SZ", "2024-06-24") == 10.0
        assert fake_pro.calls == ["daily", "daily"]


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

    def test_weekend_today_snaps_backward(self, populated_store, monkeypatch):
        """PR #3 review hotfix #2: when today=Saturday/Sunday, scorer must
        snap BACKWARD to the previous trading day. Snapping forward would
        fetch nonexistent close prices and prematurely mark rows scored."""
        _populate_calendar()
        # Mon 06-24 + 5 trading days = Mon 07-01. To make the row maturity
        # check correct we need today's last_trading_day >= Mon 07-01.
        # Sunday 2024-07-07 → snap backward → Fri 07-05. But Mon 07-01 ≤ Fri
        # 07-05, so the 5d window IS matured.
        prices = {
            ("688981.SH", "2024-06-24"): 100.0,
            ("688981.SH", "2024-07-01"): 105.0,
            ("600519.SH", "2024-06-24"): 1000.0,
            ("600519.SH", "2024-07-01"): 1020.0,
            ("000300.SH", "2024-06-24"): 3500.0,
            ("000300.SH", "2024-07-01"): 3535.0,
        }
        monkeypatch.setattr(scorer_module, "_fetch_close", _make_fetcher(prices))

        # Sunday — would have snapped FORWARD to Mon 07-08 in the old code,
        # causing _fetch_close(t_5d) to fetch a future date.
        scorer = Scorer(populated_store)
        out = scorer.score_pending("cohort_default", "2024-07-07")
        assert out["scored"] == 2
        assert out["skipped_missing"] == 0  # no NULL'd rows

    def test_immature_row_when_today_is_weekend_too_close(
        self, populated_store, monkeypatch
    ):
        """If today is Saturday and last trading day < row.date + 5td, the
        row must remain pending — not be force-scored against future data."""
        _populate_calendar()
        # Row date = Mon 06-24. last_trading_day for Sat 06-29 = Fri 06-28.
        # cutoff_5d = previous_trading_day(Fri 06-28, 5) = Fri 06-21.
        # Row dated Mon 06-24 > 06-21 → not in pending list → out["scored"] = 0.
        monkeypatch.setattr(scorer_module, "_fetch_close", _make_fetcher({}))
        scorer = Scorer(populated_store)
        out = scorer.score_pending("cohort_default", "2024-06-29")  # Saturday
        assert out["scored"] == 0
        # Row should still be pending after this call
        pending = populated_store.list_pending(cohort="cohort_default")
        assert len(pending) > 0


# ---------------------------------------------------------------------------
# Index detection (PR #3 review hotfix #3)
# ---------------------------------------------------------------------------


class TestIndexDetection:
    def test_canonical_csi300_is_index(self):
        from mosaic.scorecard.scorer import _is_a_share_index

        assert _is_a_share_index("000300.SH") is True

    def test_sse_indices(self):
        from mosaic.scorecard.scorer import _is_a_share_index

        assert _is_a_share_index("000016.SH") is True  # 上证50
        assert _is_a_share_index("000905.SH") is True  # 中证500
        assert _is_a_share_index("000001.SH") is True  # 上证综指

    def test_szse_indices(self):
        from mosaic.scorecard.scorer import _is_a_share_index

        assert _is_a_share_index("399001.SZ") is True  # 深证成指
        assert _is_a_share_index("399006.SZ") is True  # 创业板指
        assert _is_a_share_index("399300.SZ") is True  # alt CSI300

    def test_csi_national_index(self):
        from mosaic.scorecard.scorer import _is_a_share_index

        assert _is_a_share_index("932000.SH") is True

    def test_szse_main_board_stock_is_not_index(self):
        """000001.SZ is Ping An Bank (a stock), NOT an index — same prefix
        as SSE 000001.SH (上证综指 / index). Market suffix disambiguates."""
        from mosaic.scorecard.scorer import _is_a_share_index

        assert _is_a_share_index("000001.SZ") is False

    def test_typical_stocks_are_not_indices(self):
        from mosaic.scorecard.scorer import _is_a_share_index

        assert _is_a_share_index("600519.SH") is False  # 茅台
        assert _is_a_share_index("688981.SH") is False  # 中芯国际
        assert _is_a_share_index("002371.SZ") is False  # 中创新航
        assert _is_a_share_index("300750.SZ") is False  # 宁德时代

    def test_invalid_format_rejected(self):
        from mosaic.scorecard.scorer import _is_a_share_index

        assert _is_a_share_index("000300") is False  # no market suffix
        assert _is_a_share_index("000300.HK") is False  # wrong market
        assert _is_a_share_index("0000300.SH") is False  # too long
        assert _is_a_share_index("00030.SH") is False  # too short

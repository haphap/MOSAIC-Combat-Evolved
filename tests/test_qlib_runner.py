"""Tests for mosaic.backtest.qlib_runner + qlib_strategy (Plan §11.4 sub-step 3.5D).

Focuses on:
  * Symbol conversion (ts_code → qlib instrument)
  * weights_by_date construction from SQLite
  * Metrics summarisation from a synthetic portfolio_dict

Full qlib.backtest is integration territory and exercised by the 3.5F
end-to-end CLI; here we don't spin up qlib's executor.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mosaic.backtest import (
    BacktestMetrics,
    QlibInitError,
    ts_code_to_qlib_instrument,
)
from mosaic.backtest.qlib_runner import _resolve_qlib_data_path, _summarise_portfolio
from mosaic.backtest.qlib_strategy import load_weights_from_store
from mosaic.scorecard import ScorecardStore


# ---------------------------------------------------------------------------
# Symbol conversion
# ---------------------------------------------------------------------------


class TestSymbolConversion:
    def test_sh_index(self):
        assert ts_code_to_qlib_instrument("000300.SH") == "SH000300"

    def test_sh_stock(self):
        assert ts_code_to_qlib_instrument("600519.SH") == "SH600519"
        assert ts_code_to_qlib_instrument("688981.SH") == "SH688981"

    def test_sz_stock(self):
        assert ts_code_to_qlib_instrument("000001.SZ") == "SZ000001"
        assert ts_code_to_qlib_instrument("002371.SZ") == "SZ002371"
        assert ts_code_to_qlib_instrument("300750.SZ") == "SZ300750"

    def test_bj_stock(self):
        assert ts_code_to_qlib_instrument("430017.BJ") == "BJ430017"

    def test_lowercase_suffix_normalized(self):
        assert ts_code_to_qlib_instrument("600519.sh") == "SH600519"

    def test_already_qlib_form_passthrough(self):
        # No dot → can't infer; pass through (caller decides)
        assert ts_code_to_qlib_instrument("SH600519") == "SH600519"
        assert ts_code_to_qlib_instrument("") == ""


# ---------------------------------------------------------------------------
# load_weights_from_store
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_store(tmp_path: Path) -> tuple[ScorecardStore, int]:
    store = ScorecardStore(db_path=tmp_path / "scorecard.db")
    run_id = store.create_backtest_run(
        cohort="cohort_default",
        start_date="2024-01-01",
        end_date="2024-03-31",
        prompt_commit_hash="test",
    )
    store.append_backtest_actions(
        run_id,
        "2024-01-15",
        [
            {"ticker": "688981.SH", "action": "BUY", "target_weight": 0.4},
            {"ticker": "600519.SH", "action": "BUY", "target_weight": 0.3},
        ],
    )
    store.append_backtest_actions(
        run_id,
        "2024-02-15",
        [
            {"ticker": "688981.SH", "action": "BUY", "target_weight": 0.5},
            {"ticker": "002371.SZ", "action": "BUY", "target_weight": 0.2},
        ],
    )
    return store, run_id


class TestLoadWeights:
    def test_basic_load(self, populated_store):
        store, run_id = populated_store
        weights = load_weights_from_store(store, run_id)
        assert set(weights.keys()) == {"2024-01-15", "2024-02-15"}
        # Tickers converted to qlib uppercase form
        jan = weights["2024-01-15"]
        assert "SH688981" in jan
        assert "SH600519" in jan
        assert jan["SH688981"] == pytest.approx(0.4)
        feb = weights["2024-02-15"]
        assert "SZ002371" in feb
        assert feb["SH688981"] == pytest.approx(0.5)

    def test_empty_run(self, tmp_path: Path):
        store = ScorecardStore(db_path=tmp_path / "scorecard.db")
        run_id = store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="empty",
        )
        weights = load_weights_from_store(store, run_id)
        assert weights == {}


# ---------------------------------------------------------------------------
# Metrics summariser
# ---------------------------------------------------------------------------


def _synth_portfolio_dict(returns: list[float], bench: list[float]) -> dict:
    """Build a fake portfolio_dict matching qlib's
    PortfolioMetrics.generate() output schema."""
    df = pd.DataFrame(
        {
            "return": returns,
            "bench": bench,
            "cost": [0.0] * len(returns),
            "turnover": [0.0] * len(returns),
        }
    )

    class _PortStub:
        def generate(self):
            return df

    return {"1day": _PortStub()}


class TestSummarisePortfolio:
    def test_zero_returns(self):
        port = _synth_portfolio_dict([0.0] * 10, [0.0] * 10)
        m = _summarise_portfolio(
            portfolio_dict=port,
            run_id=1,
            cohort="c",
            start_date="2024-01-01",
            end_date="2024-01-15",
            benchmark="SH000300",
            initial_cash=1_000_000.0,
        )
        assert m.n_trade_days == 10
        assert m.total_return == pytest.approx(0.0)
        assert m.benchmark_return == pytest.approx(0.0)
        assert m.alpha == pytest.approx(0.0)
        assert m.max_drawdown == pytest.approx(0.0)
        assert m.final_value == pytest.approx(1_000_000.0)

    def test_steady_positive_returns(self):
        # 10 days of +0.1% per day → cumulative ~1.0045
        returns = [0.001] * 10
        bench = [0.0005] * 10  # benchmark +0.05%/day
        port = _synth_portfolio_dict(returns, bench)
        m = _summarise_portfolio(
            portfolio_dict=port,
            run_id=1,
            cohort="c",
            start_date="2024-01-01",
            end_date="2024-01-15",
            benchmark="SH000300",
            initial_cash=1_000_000.0,
        )
        # Compounded 0.001 over 10 days
        expected_total = (1.001 ** 10) - 1.0
        assert m.total_return == pytest.approx(expected_total, abs=1e-6)
        # Bench compounded
        expected_bench = (1.0005 ** 10) - 1.0
        assert m.benchmark_return == pytest.approx(expected_bench, abs=1e-6)
        assert m.alpha == pytest.approx(expected_total - expected_bench, abs=1e-6)
        # Steady positive returns → max DD = 0 (each day a new peak)
        assert m.max_drawdown == pytest.approx(0.0, abs=1e-9)

    def test_drawdown_calc(self):
        # +5%, -10%, +2% → equity 1.05, 0.945, 0.96
        returns = [0.05, -0.10, 0.02]
        port = _synth_portfolio_dict(returns, [0.0, 0.0, 0.0])
        m = _summarise_portfolio(
            portfolio_dict=port,
            run_id=1,
            cohort="c",
            start_date="2024-01-01",
            end_date="2024-01-03",
            benchmark="SH000300",
            initial_cash=1_000_000.0,
        )
        # Peak = 1.05, trough = 0.945 → DD = -10%
        assert m.max_drawdown == pytest.approx(-0.10, abs=1e-6)

    def test_sharpe_calc(self):
        # Returns ~ Normal(0.001, 0.01) for sharpe ~= 0.001/0.01 * sqrt(252) ~ 1.587
        # Use deterministic values: 5 each of +0.011, +0.009 = mean 0.001, std ~0.001
        # Actually we want a simple known value. Use returns alternating +0.01/-0.005 → mean 0.0025, std ~0.0075
        # Sharpe = 0.0025/0.0075 * sqrt(252) ≈ 5.29
        returns = [0.01, -0.005, 0.01, -0.005, 0.01, -0.005, 0.01, -0.005, 0.01, -0.005]
        port = _synth_portfolio_dict(returns, [0.0] * 10)
        m = _summarise_portfolio(
            portfolio_dict=port,
            run_id=1,
            cohort="c",
            start_date="2024-01-01",
            end_date="2024-01-10",
            benchmark="SH000300",
            initial_cash=1_000_000.0,
        )
        assert m.sharpe > 0  # positive mean, finite std → positive Sharpe
        # Sanity: should be in single-digits annualised for this profile
        assert 1.0 < m.sharpe < 20.0

    def test_no_return_column_falls_back_to_value(self):
        df = pd.DataFrame({"value": [1_000_000, 1_010_000, 1_020_000, 1_015_000]})

        class _Stub:
            def generate(self):
                return df

        port = {"1day": _Stub()}
        m = _summarise_portfolio(
            portfolio_dict=port,
            run_id=1,
            cohort="c",
            start_date="2024-01-01",
            end_date="2024-01-04",
            benchmark="SH000300",
            initial_cash=1_000_000.0,
        )
        assert m.n_trade_days == 4
        # First row pct_change = NaN → treated as 0
        # remaining: +1%, +0.99%, -0.49%
        # Total = 1.015 / 1.000 - 1 = 0.015
        assert m.total_return == pytest.approx(0.015, abs=1e-6)

    def test_empty_dataframe_returns_zeros(self):
        class _Stub:
            def generate(self):
                return pd.DataFrame()

        port = {"1day": _Stub()}
        m = _summarise_portfolio(
            portfolio_dict=port,
            run_id=1,
            cohort="c",
            start_date="2024-01-01",
            end_date="2024-01-01",
            benchmark="SH000300",
            initial_cash=1_000_000.0,
        )
        assert m.n_trade_days == 0
        assert m.total_return == 0.0
        assert m.final_value == 1_000_000.0

    def test_to_dict_serialisable(self):
        m = BacktestMetrics(
            run_id=1,
            cohort="c",
            start_date="2024-01-01",
            end_date="2024-01-31",
            benchmark="SH000300",
            n_trade_days=20,
            total_return=0.05,
            annualized_return=0.6,
            sharpe=2.5,
            max_drawdown=-0.10,
            benchmark_return=0.02,
            alpha=0.03,
            initial_cash=1_000_000.0,
            final_value=1_050_000.0,
        )
        d = m.to_dict()
        assert d["sharpe"] == 2.5
        assert d["alpha"] == 0.03
        # JSON-serialisable
        import json

        json.dumps(d)


# ---------------------------------------------------------------------------
# qlib data path resolution
# ---------------------------------------------------------------------------


class TestQlibDataPath:
    def test_env_override_wins(self, tmp_path: Path, monkeypatch):
        # Build a minimal valid qlib layout
        target = tmp_path / "fake_cn_data"
        (target / "calendars").mkdir(parents=True)
        (target / "calendars" / "day.txt").write_text("2024-01-01\n")
        (target / "features").mkdir()
        monkeypatch.setenv("QLIB_CN_DATA_PATH", str(target))
        result = _resolve_qlib_data_path()
        assert result == target

    def test_missing_everywhere_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("QLIB_CN_DATA_PATH", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))
        with pytest.raises(QlibInitError, match="not found"):
            _resolve_qlib_data_path()


# ---------------------------------------------------------------------------
# Strategy class instantiation (no qlib.init required for class building)
# ---------------------------------------------------------------------------


class TestStrategyInstantiation:
    def test_from_actions_dict_with_empty_weights(self):
        from mosaic.backtest.qlib_strategy import MosaicCachedStrategy

        # Empty weights — should construct but produce empty signal
        strategy = MosaicCachedStrategy.from_actions_dict({})
        assert strategy is not None
        assert strategy._mosaic_weights_by_date == {}

    def test_from_actions_dict_with_data(self):
        from mosaic.backtest.qlib_strategy import MosaicCachedStrategy

        weights = {
            "2024-01-15": {"SH688981": 0.5, "SH600519": 0.3},
            "2024-02-15": {"SH688981": 0.4},
        }
        strategy = MosaicCachedStrategy.from_actions_dict(weights)
        assert strategy._mosaic_weights_by_date["2024-01-15"]["SH688981"] == 0.5
        assert strategy._mosaic_weights_by_date["2024-02-15"]["SH688981"] == 0.4

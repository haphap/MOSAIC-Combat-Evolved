"""Tests for the backtest results exporter (Plan §11.8.1 candidate #2).

Deps-light: synthesizes a BacktestMetrics + a qlib-style report DataFrame
directly (no qlib / no real backtest). Guards on pandas; the PNG path is
matplotlib-optional and asserted both ways.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HAS_PANDAS = importlib.util.find_spec("pandas") is not None
_HAS_MPL = importlib.util.find_spec("matplotlib") is not None

pytestmark = pytest.mark.skipif(not _HAS_PANDAS, reason="pandas required")


def _metrics():
    from mosaic.backtest.qlib_runner import BacktestMetrics

    return BacktestMetrics(
        run_id=7,
        cohort="crisis_2008",
        start_date="2008-01-02",
        end_date="2008-01-08",
        benchmark="SH000300",
        n_trade_days=4,
        total_return=0.012,
        annualized_return=0.9,
        sharpe=1.3,
        max_drawdown=-0.05,
        benchmark_return=0.004,
        alpha=0.008,
        initial_cash=1_000_000.0,
        final_value=1_012_000.0,
    )


def _report_df():
    import pandas as pd

    idx = pd.to_datetime(["2008-01-02", "2008-01-03", "2008-01-04", "2008-01-07"])
    return pd.DataFrame(
        {
            "return": [0.01, -0.02, 0.015, 0.007],
            "bench": [0.005, -0.01, 0.008, 0.001],
            "value": [1.01e6, 9.9e6, 1.0e6, 1.012e6],
            "cash": [5e5, 5e5, 5e5, 5e5],
            "cost": [10.0, 12.0, 8.0, 5.0],
            "turnover": [0.1, 0.2, 0.05, 0.03],
        },
        index=idx,
    )


def test_export_writes_summary_and_trajectory(tmp_path: Path):
    from mosaic.backtest.results_export import export_results

    manifest = export_results(_metrics(), _report_df(), tmp_path)

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == 7
    assert summary["cohort"] == "crisis_2008"
    assert summary["sharpe"] == 1.3

    csv_text = (tmp_path / "portfolio_trajectory.csv").read_text(encoding="utf-8")
    header = csv_text.splitlines()[0]
    for col in ("date", "return", "equity", "drawdown", "bench_return", "bench_equity"):
        assert col in header
    assert manifest["n_rows"] == 4


def test_trajectory_equity_and_drawdown_are_derived(tmp_path: Path):
    from mosaic.backtest.results_export import export_results

    export_results(_metrics(), _report_df(), tmp_path)
    import pandas as pd

    traj = pd.read_csv(tmp_path / "portfolio_trajectory.csv")
    # equity[0] = 1 + return[0]; equity is cumulative product of (1+return).
    assert abs(traj["equity"].iloc[0] - 1.01) < 1e-9
    assert abs(traj["equity"].iloc[-1] - (1.01 * 0.98 * 1.015 * 1.007)) < 1e-6
    # drawdown is <= 0 everywhere.
    assert (traj["drawdown"] <= 1e-12).all()


def test_png_behavior_matches_matplotlib_availability(tmp_path: Path):
    from mosaic.backtest.results_export import export_results

    manifest = export_results(_metrics(), _report_df(), tmp_path)
    if _HAS_MPL:
        assert manifest["equity_curve_png"] is not None
        assert (tmp_path / "equity_curve.png").is_file()
    else:
        assert manifest["equity_curve_png"] is None
        assert not (tmp_path / "equity_curve.png").exists()

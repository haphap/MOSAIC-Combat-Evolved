"""Backtest results exporter (Plan §11.8.1 deferred candidate #2).

Aggregates a completed backtest run into ATLAS-isomorphic artifacts:

  * ``summary.json``            — top-line metrics (BacktestMetrics.to_dict()).
  * ``portfolio_trajectory.csv`` — the per-day series (date, return, equity,
    drawdown, benchmark, value, cash, cost, turnover) qlib produced.
  * ``equity_curve.png``        — equity vs benchmark plot. matplotlib is an
    OPTIONAL dependency; when absent the PNG is skipped (the other two
    artifacts always write).

The per-day series comes from qlib's portfolio report DataFrame; ``run_backtest``
forwards it here when called with ``results_dir=...``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from mosaic.backtest.qlib_runner import BacktestMetrics

logger = logging.getLogger(__name__)


def _trajectory_frame(report_df: "pd.DataFrame") -> "pd.DataFrame":
    """Derive the per-day trajectory (date, return, equity, drawdown, ...) from
    qlib's report DataFrame. Column names are matched case-insensitively; missing
    optional columns are simply omitted."""
    import pandas as pd

    cols = {c.lower(): c for c in report_df.columns}
    return_col = cols.get("return") or cols.get("ret") or cols.get("portfolio_return")
    bench_col = cols.get("bench") or cols.get("benchmark") or cols.get("bench_return")

    if return_col:
        returns = report_df[return_col].fillna(0.0)
    else:
        equity_col = cols.get("value") or cols.get("asset")
        returns = report_df[equity_col].pct_change().fillna(0.0) if equity_col else pd.Series(
            [0.0] * len(report_df)
        )

    equity = (1.0 + returns).cumprod()
    drawdown = (equity / equity.cummax()) - 1.0

    out = pd.DataFrame(
        {
            "date": [str(idx) for idx in report_df.index],
            "return": returns.to_numpy(),
            "equity": equity.to_numpy(),
            "drawdown": drawdown.to_numpy(),
        }
    )
    if bench_col:
        bench_returns = report_df[bench_col].fillna(0.0)
        out["bench_return"] = bench_returns.to_numpy()
        out["bench_equity"] = (1.0 + bench_returns).cumprod().to_numpy()
    # Pass through any qlib bookkeeping columns that exist.
    for key in ("value", "cash", "cost", "turnover"):
        src = cols.get(key)
        if src:
            out[key] = report_df[src].to_numpy()
    return out


def _plot_equity_curve(traj: "pd.DataFrame", path: Path, title: str) -> bool:
    """Write equity_curve.png; return False (and log) if matplotlib is absent."""
    try:
        import matplotlib

        matplotlib.use("Agg")  # headless
        import matplotlib.pyplot as plt
    except ImportError:
        logger.info("matplotlib not installed; skipping equity_curve.png")
        return False

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(range(len(traj)), traj["equity"], label="strategy", linewidth=1.5)
    if "bench_equity" in traj.columns:
        ax.plot(range(len(traj)), traj["bench_equity"], label="benchmark", linewidth=1.0, alpha=0.7)
    ax.set_title(title)
    ax.set_xlabel("trading day")
    ax.set_ylabel("equity (normalized to 1.0)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return True


def export_results(
    metrics: "BacktestMetrics",
    report_df: "pd.DataFrame",
    out_dir: Path | str,
) -> dict[str, Any]:
    """Write summary.json + portfolio_trajectory.csv + equity_curve.png.

    Returns a manifest dict ``{out_dir, summary_json, trajectory_csv,
    equity_curve_png|None, n_rows}``. The PNG entry is None when matplotlib is
    unavailable.
    """
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    traj = _trajectory_frame(report_df)
    traj_path = out_dir / "portfolio_trajectory.csv"
    traj.to_csv(traj_path, index=False)

    png_path = out_dir / "equity_curve.png"
    title = f"{metrics.cohort} {metrics.start_date}→{metrics.end_date} (run {metrics.run_id})"
    png_written = _plot_equity_curve(traj, png_path, title) if not traj.empty else False

    return {
        "out_dir": str(out_dir),
        "summary_json": str(summary_path),
        "trajectory_csv": str(traj_path),
        "equity_curve_png": str(png_path) if png_written else None,
        "n_rows": int(len(traj)),
    }

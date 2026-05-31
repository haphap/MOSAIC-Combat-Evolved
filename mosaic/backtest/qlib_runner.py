"""Phase 3.5D qlib backtest runner.

Reads cached actions for a backtest run from SQLite, executes through
qlib's backtest engine, returns metrics dict suitable for autoresearch
ΔSharpe evaluation in Phase 4.

Backtest semantics (Plan §11.4 design decision #6):
  * Execution timing: next_open (T+1; A-share rule)
  * Slippage: 0.0008 (8 bps; qlib CN default)
  * Commission: 0.0003 buy + 0.0013 sell (3 bps + 13 bps including
                印花税 on the sell side; A-share retail)
  * Initial cash: configurable, default ¥1,000,000
  * Benchmark: SH000300 (沪深300; matches Phase 3 scorer)
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Defaults (Plan §11.4 design decision #6).
DEFAULT_BENCHMARK = "SH000300"
DEFAULT_INITIAL_CASH = 1_000_000.0
DEFAULT_COMMISSION = 0.0003  # buy
DEFAULT_DEAL_PRICE = "close"
DEFAULT_SLIPPAGE = 0.0008
DEFAULT_OPEN_COST = 0.0003
DEFAULT_CLOSE_COST = 0.0013  # sell + 印花税


class QlibInitError(RuntimeError):
    """Raised when qlib data dir or pyqlib is unavailable."""


@dataclass(frozen=True)
class BacktestMetrics:
    """Top-line metrics returned by ``run_backtest``.

    All Sharpe-like values are annualized (252 trading days). Returns are
    decimal (0.05 = 5%). max_drawdown is signed (-0.20 = -20%).
    """

    run_id: int
    cohort: str
    start_date: str
    end_date: str
    benchmark: str
    n_trade_days: int
    total_return: float
    annualized_return: float
    sharpe: float
    max_drawdown: float
    benchmark_return: float
    alpha: float
    """``total_return - benchmark_return`` (no CAPM beta adjustment)."""
    initial_cash: float
    final_value: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_qlib_data_path() -> Path:
    """Resolve the qlib cn_data dir, defaulting to ~/.qlib/qlib_data/cn_data.

    Honours the same ``QLIB_CN_DATA_PATH`` env override that
    ``mosaic.dataflows.qlib_local`` already uses.
    """
    env_path = os.environ.get("QLIB_CN_DATA_PATH")
    candidates = [
        env_path,
        "~/.qlib/qlib_data/cn_data",
        "~/qlib_data/cn_data",
    ]
    for c in candidates:
        if not c:
            continue
        p = Path(c).expanduser()
        if (p / "calendars" / "day.txt").exists() and (p / "features").is_dir():
            return p
    raise QlibInitError(
        "qlib cn_data not found. Set QLIB_CN_DATA_PATH or place data at "
        "~/.qlib/qlib_data/cn_data (e.g. via the user's tushare collector "
        "documented in plan §11.4)."
    )


def _ensure_qlib_initialised(provider_uri: Path) -> None:
    """Idempotent qlib.init(provider_uri=..., region=cn). Raises QlibInitError.

    qlib.init can be called multiple times; subsequent calls are no-ops
    (idempotent at the C++ side).
    """
    try:
        import qlib
    except ImportError as exc:
        raise QlibInitError(
            "pyqlib is not installed. Install via 'uv pip install -e <qlib repo>' "
            "(plan §11.4 sub-step 3.5A)."
        ) from exc
    try:
        qlib.init(provider_uri=str(provider_uri), region="cn")
    except Exception as exc:
        raise QlibInitError(f"qlib.init failed: {type(exc).__name__}: {exc}") from exc


def run_backtest(
    *,
    run_id: int,
    store=None,
    initial_cash: float = DEFAULT_INITIAL_CASH,
    benchmark: str = DEFAULT_BENCHMARK,
    open_cost: float = DEFAULT_OPEN_COST,
    close_cost: float = DEFAULT_CLOSE_COST,
    deal_price: str = DEFAULT_DEAL_PRICE,
    qlib_data_path: Optional[Path] = None,
    results_dir: Optional[Path] = None,
) -> BacktestMetrics:
    """Replay a cached backtest run through qlib's executor and report metrics.

    Parameters
    ----------
    run_id:
        Row id from ``backtest_runs``. Must be a completed run (i.e.
        stage-1 fill done; ``completed_at`` non-NULL — but we don't
        enforce this hard so partial runs can also be inspected).
    store:
        Optional ``ScorecardStore``; defaults to module-level singleton
        (``ScorecardStore()``).
    initial_cash, benchmark, open_cost, close_cost, deal_price:
        Backtest parameters per Plan §11.4 design decision #6.
    qlib_data_path:
        Override for the qlib data dir; defaults to ``QLIB_CN_DATA_PATH``
        env or ``~/.qlib/qlib_data/cn_data``.

    Returns
    -------
    BacktestMetrics
        Top-line metrics; serialise via ``.to_dict()`` for the bridge
        handler.
    """
    if store is None:
        from mosaic.scorecard import ScorecardStore

        store = ScorecardStore()

    run = store.get_backtest_run(run_id)
    if run is None:
        raise ValueError(f"backtest run {run_id} not found")

    qlib_data_path = qlib_data_path or _resolve_qlib_data_path()
    _ensure_qlib_initialised(qlib_data_path)

    # Lazy-import qlib backtest pieces (only available after qlib.init).
    from qlib.backtest import backtest as qlib_backtest

    from mosaic.backtest.qlib_strategy import (
        MosaicCachedStrategy,
        load_weights_from_store,
    )

    weights_by_date = load_weights_from_store(store, run_id)
    if not weights_by_date:
        raise ValueError(
            f"backtest run {run_id} has no cached actions; "
            f"run stage-1 fill via 'pnpm dev backtest-fill' first."
        )

    strategy = MosaicCachedStrategy.from_actions_dict(weights_by_date)

    executor_config = {
        "class": "SimulatorExecutor",
        "module_path": "qlib.backtest.executor",
        "kwargs": {
            "time_per_step": "day",
            "generate_portfolio_metrics": True,
        },
    }

    exchange_kwargs = {
        "freq": "day",
        "limit_threshold": 0.095,  # ±9.5% A-share daily limit
        "deal_price": deal_price,
        "open_cost": open_cost,
        "close_cost": close_cost,
        "min_cost": 5,  # ¥5 floor commission per trade (broker default)
    }

    portfolio_dict, _indicator_dict = qlib_backtest(
        start_time=run["start_date"],
        end_time=run["end_date"],
        strategy=strategy,
        executor=executor_config,
        benchmark=benchmark,
        account=initial_cash,
        exchange_kwargs=exchange_kwargs,
    )

    metrics = _summarise_portfolio(
        portfolio_dict=portfolio_dict,
        run_id=run_id,
        cohort=run["cohort"],
        start_date=run["start_date"],
        end_date=run["end_date"],
        benchmark=benchmark,
        initial_cash=initial_cash,
    )

    if results_dir is not None:
        # Export ATLAS-isomorphic artifacts (summary.json / trajectory.csv /
        # equity_curve.png) from the same portfolio report.
        try:
            from mosaic.backtest.results_export import export_results

            report_df = _extract_report_df(portfolio_dict)
            if report_df is not None:
                manifest = export_results(metrics, report_df, results_dir)
                logger.info("backtest results exported: %s", manifest)
        except Exception as exc:  # export must never fail the backtest
            logger.warning("results export skipped: %s: %s", type(exc).__name__, exc)

    return metrics


def _extract_report_df(portfolio_dict: dict):
    """Return qlib's per-day report DataFrame (the tuple[0]) or None.

    Mirrors ``_summarise_portfolio``'s freq-key handling: the executor runs with
    ``time_per_step="day"`` so qlib keys the report under ``"1day"``; we fall
    back to the first value if that key ever changes. The isinstance guard means
    a shape change yields None (export skipped) rather than a crash.
    """
    import pandas as pd

    port = portfolio_dict.get("1day") if "1day" in portfolio_dict else next(
        iter(portfolio_dict.values()), None
    )
    if isinstance(port, tuple) and port and isinstance(port[0], pd.DataFrame):
        return port[0]
    return None


def _summarise_portfolio(
    *,
    portfolio_dict: dict,
    run_id: int,
    cohort: str,
    start_date: str,
    end_date: str,
    benchmark: str,
    initial_cash: float,
) -> BacktestMetrics:
    """Boil ``portfolio_dict`` (from qlib.backtest) down to BacktestMetrics.

    qlib's ``portfolio_dict[<freq>]`` shape (verified on qlib 0.x editable
    install): ``tuple[pd.DataFrame, dict[Timestamp, position]]``. The
    DataFrame has columns: account / return / total_turnover / turnover /
    total_cost / cost / value / cash / bench (indexed by datetime).

    Pinned to this shape (PR #4 review #4): the previous defensive
    fallback chain (tuple / .generate() / DataFrame) was speculation —
    masked the bug where unit-test mocks used .generate() but real qlib
    returns tuple. Single shape + clear error if qlib ever changes.
    """
    import math

    import pandas as pd

    # qlib's portfolio_dict is keyed by step name — typically "1day".
    if "1day" in portfolio_dict:
        port = portfolio_dict["1day"]
    else:
        # Fallback to first available frequency
        port = next(iter(portfolio_dict.values()))

    if not isinstance(port, tuple) or len(port) < 1 or not isinstance(port[0], pd.DataFrame):
        raise ValueError(
            "Unexpected qlib portfolio_dict shape: expected "
            "tuple[pd.DataFrame, dict] (qlib 0.x convention) but got "
            f"{type(port).__name__}. qlib upstream may have changed; "
            "update _summarise_portfolio."
        )
    report_df = port[0]

    if not isinstance(report_df, pd.DataFrame) or report_df.empty:
        return BacktestMetrics(
            run_id=run_id,
            cohort=cohort,
            start_date=start_date,
            end_date=end_date,
            benchmark=benchmark,
            n_trade_days=0,
            total_return=0.0,
            annualized_return=0.0,
            sharpe=0.0,
            max_drawdown=0.0,
            benchmark_return=0.0,
            alpha=0.0,
            initial_cash=initial_cash,
            final_value=initial_cash,
        )

    # Try to resolve the equity/return columns. qlib's
    # PortfolioMetrics.generate() returns columns roughly like:
    #   ['return', 'bench', 'cost', 'turnover', 'value', 'cash', 'asset']
    cols = {c.lower(): c for c in report_df.columns}
    return_col = cols.get("return") or cols.get("ret") or cols.get("portfolio_return")
    bench_col = cols.get("bench") or cols.get("benchmark") or cols.get("bench_return")

    if not return_col:
        # Fallback: derive from equity if possible
        equity_col = cols.get("value") or cols.get("asset")
        if equity_col:
            equity = report_df[equity_col]
            returns = equity.pct_change().fillna(0.0)
        else:
            returns = pd.Series([0.0] * len(report_df))
    else:
        returns = report_df[return_col].fillna(0.0)

    if bench_col:
        bench_returns = report_df[bench_col].fillna(0.0)
    else:
        bench_returns = pd.Series([0.0] * len(report_df))

    # Compounded total return
    total_return = float((1.0 + returns).prod() - 1.0)
    benchmark_return = float((1.0 + bench_returns).prod() - 1.0)
    alpha = total_return - benchmark_return
    n_days = len(returns)

    # Annualized return — assume 252 trading days
    if n_days > 0 and total_return > -1.0:
        annualized_return = (1.0 + total_return) ** (252.0 / n_days) - 1.0
    else:
        annualized_return = 0.0

    # Sharpe — daily-cycle return Sharpe annualized
    if n_days > 1:
        mean = float(returns.mean())
        std = float(returns.std(ddof=1))
        sharpe = (mean / std) * math.sqrt(252) if std > 1e-12 else 0.0
    else:
        sharpe = 0.0

    # Max drawdown
    if n_days > 0:
        equity_curve = (1.0 + returns).cumprod()
        rolling_peak = equity_curve.cummax()
        drawdown = (equity_curve / rolling_peak) - 1.0
        max_drawdown = float(drawdown.min())
    else:
        max_drawdown = 0.0

    final_value = initial_cash * (1.0 + total_return)

    return BacktestMetrics(
        run_id=run_id,
        cohort=cohort,
        start_date=start_date,
        end_date=end_date,
        benchmark=benchmark,
        n_trade_days=n_days,
        total_return=total_return,
        annualized_return=annualized_return,
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        benchmark_return=benchmark_return,
        alpha=alpha,
        initial_cash=initial_cash,
        final_value=final_value,
    )

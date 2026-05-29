"""MOSAIC backtest package (Plan §11.4 sub-step 3.5D).

Stage-2 of the two-stage backtest pipeline. Stage-1 (TS, sub-step 3.5C)
fills the ``backtest_actions`` SQLite table; this package replays from
that table through qlib's strategy + executor against the local
``~/.qlib/qlib_data/cn_data`` dataset and computes portfolio metrics.

Public surface:
  * ``run_backtest(run_id, ...)`` — main entry; reads run + actions from
    SQLite, calls qlib.backtest, returns metrics dict.
  * ``MosaicCachedStrategy`` — qlib WeightStrategyBase subclass that
    sources its target weights from a pre-loaded dict keyed by
    trade-date.
"""

from mosaic.backtest.qlib_runner import (
    BacktestMetrics,
    QlibInitError,
    run_backtest,
)
from mosaic.backtest.qlib_strategy import (
    MosaicCachedStrategy,
    ts_code_to_qlib_instrument,
)

__all__ = [
    "BacktestMetrics",
    "MosaicCachedStrategy",
    "QlibInitError",
    "run_backtest",
    "ts_code_to_qlib_instrument",
]

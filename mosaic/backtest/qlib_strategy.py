"""qlib WeightStrategyBase adapter for MOSAIC cached backtest actions.

(Plan §11.4 sub-step 3.5D.)

Reads ``backtest_actions`` rows from SQLite (populated by stage-1 in 3.5C)
and exposes them to qlib's executor as a target-weight strategy. No LLM
calls happen during replay — the strategy is a pure deterministic
function of the cache + qlib's exchange data.

Symbol conversion:
    MOSAIC stores tickers in tushare ``ts_code`` form (``000300.SH``).
    qlib's instruments use the uppercase concatenated form (``SH000300``).
    ``ts_code_to_qlib_instrument`` handles the mapping including the
    Beijing exchange (``BJ``) special case.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def ts_code_to_qlib_instrument(ts_code: str) -> str:
    """Convert tushare ``000300.SH`` style → qlib ``SH000300``.

    Returns the input unchanged if it's already in qlib uppercase form
    or any other unrecognised shape (caller decides what to do).
    """
    if not ts_code or "." not in ts_code:
        return ts_code
    code, _, suffix = ts_code.partition(".")
    suffix = suffix.upper()
    if suffix in ("SH", "SZ", "BJ"):
        return f"{suffix}{code}"
    return ts_code


def _normalize_instrument(instrument: str) -> str:
    """Convert any qlib-style instrument to its uppercase form for lookup."""
    if "." in instrument:
        return ts_code_to_qlib_instrument(instrument)
    return instrument.upper()


class MosaicCachedStrategy:
    """qlib ``WeightStrategyBase`` subclass driven by cached MOSAIC actions.

    Defined as a regular class (not at-import-time subclass) so the module
    imports cleanly even when qlib isn't installed; the ``WeightStrategyBase``
    inheritance is wired in ``__init_subclass__``-style at first
    instantiation. This keeps unit tests fast.

    The class is dynamically rebuilt as a qlib subclass on first use; see
    ``_create_class``.
    """

    @classmethod
    def from_actions_dict(cls, weights_by_date: dict[str, dict[str, float]], **kwargs):
        """Factory: construct a qlib-compatible strategy instance.

        ``weights_by_date`` maps ``YYYY-MM-DD`` → ``{qlib_instrument:
        target_weight}``. The strategy converts this into a
        ``SignalWCache``-compatible ``pd.Series`` for qlib's signal
        infrastructure.

        Forwards ``**kwargs`` to the underlying ``WeightStrategyBase``
        constructor (e.g. ``trade_exchange``, ``risk_degree``).
        """
        # Build pd.Series with MultiIndex (instrument, datetime) for the
        # signal cache. Values are arbitrary (we use 1.0) — the strategy
        # ignores `score` in `generate_target_weight_position`.
        rows = []
        for date_iso, weights in weights_by_date.items():
            for instrument in weights.keys():
                rows.append((instrument, pd.Timestamp(date_iso), 1.0))
        if not rows:
            # Empty signal — strategy will produce no orders
            empty_idx = pd.MultiIndex.from_tuples([], names=["instrument", "datetime"])
            signal = pd.Series([], index=empty_idx, dtype=float)
        else:
            df = pd.DataFrame(rows, columns=["instrument", "datetime", "score"])
            df = df.set_index(["instrument", "datetime"]).sort_index()
            signal = df["score"]

        StrategyClass = _create_class()
        instance = StrategyClass(signal=signal, **kwargs)
        # Cache the dict on the instance for fast per-step lookup
        instance._mosaic_weights_by_date = {
            date_iso: dict(weights) for date_iso, weights in weights_by_date.items()
        }
        return instance


_CACHED_STRATEGY_CLASS: Optional[type] = None


def _create_class():
    """Lazily build the qlib subclass.

    Done at first instantiation rather than module import so that
    ``mosaic.backtest`` can be imported even in environments without qlib
    (the package surface — types, helpers — should always work).
    """
    global _CACHED_STRATEGY_CLASS
    if _CACHED_STRATEGY_CLASS is not None:
        return _CACHED_STRATEGY_CLASS

    try:
        from qlib.contrib.strategy.signal_strategy import WeightStrategyBase
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "qlib is not installed (or scripts/data_collector unavailable). "
            "Install via 'uv pip install -e <qlib repo>' to run MOSAIC backtests."
        ) from exc

    class _MosaicCachedStrategy(WeightStrategyBase):
        """Real qlib subclass — assembled at first call.

        Bug fix (PR #4 review #1, HIGH): originally
        ``_mosaic_weights_by_date`` was a class-level dict, which would
        be shared across all strategy instances created in the same
        process — running two backtests (e.g. base + mutation) would
        cross-contaminate weights. Moved to ``__init__`` so each
        instance has its own dict.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Per-instance cache — populated by ``from_actions_dict``.
            self._mosaic_weights_by_date: dict[str, dict[str, float]] = {}

        def generate_target_weight_position(
            self,
            score,
            current,
            trade_start_time,
            trade_end_time,
        ):
            """Lookup our cached weights for the trade date.

            qlib calls this once per trade step. We snap ``trade_start_time``
            to a date string (YYYY-MM-DD) and return the corresponding
            cached weight dict. Missing dates → empty dict (means liquidate
            to cash; qlib's order generator handles the diff vs current).
            """
            date_iso = pd.Timestamp(trade_start_time).strftime("%Y-%m-%d")
            weights = self._mosaic_weights_by_date.get(date_iso)
            if not weights:
                # No cached actions for this date — keep current position
                # by returning current weights (empty dict means "go to cash"
                # which would be too aggressive). We'll iterate the current
                # position and reproduce its weights to no-op the step.
                return self._current_position_to_weights(current)
            return dict(weights)

        @staticmethod
        def _current_position_to_weights(current) -> dict[str, float]:
            """Translate qlib Position object → {instrument: weight}.

            Used as the no-op return when our cache lacks a date — keeps the
            existing position rather than liquidating to cash.
            """
            try:
                stocks = current.get_stock_list()
            except Exception:
                return {}
            if not stocks:
                return {}
            try:
                total = current.calculate_value() if hasattr(current, "calculate_value") else 0.0
            except Exception:
                total = 0.0
            if total <= 0:
                return {}
            out: dict[str, float] = {}
            for s in stocks:
                try:
                    weight = current.get_stock_weight(s)
                except Exception:
                    weight = 0.0
                if weight > 0:
                    out[s] = weight
            return out

    _CACHED_STRATEGY_CLASS = _MosaicCachedStrategy
    return _MosaicCachedStrategy


def load_weights_from_store(store, run_id: int) -> dict[str, dict[str, float]]:
    """Read all backtest_actions for ``run_id`` and group by date.

    Output: ``{YYYY-MM-DD: {qlib_instrument: target_weight}}``
    """
    actions = store.get_backtest_actions(run_id)
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    for a in actions:
        date_iso = a["trade_date"]
        ticker = a["ticker"]
        target_weight = float(a["target_weight"])
        instrument = ts_code_to_qlib_instrument(ticker)
        # If multiple actions for same (date, instrument) — last write wins;
        # SQLite UNIQUE(run_id, trade_date, ticker) prevents this in practice.
        by_date[date_iso][instrument] = target_weight
    return dict(by_date)

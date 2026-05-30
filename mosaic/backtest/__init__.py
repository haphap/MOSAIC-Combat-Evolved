"""MOSAIC backtest package (Plan §11.4 sub-step 3.5D).

Stage-2 of the two-stage backtest pipeline. Stage-1 (TS, sub-step 3.5C)
fills the ``backtest_actions`` SQLite table; this package replays from
that table through qlib's strategy + executor against the local
``~/.qlib/qlib_data/cn_data`` dataset and computes portfolio metrics.

Public names are lazily imported (PEP 562 ``__getattr__``) so importing a
pure-Python sibling like ``mosaic.backtest.signals`` doesn't pull qlib/pandas.
"""

from __future__ import annotations

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "BacktestMetrics": (".qlib_runner", "BacktestMetrics"),
    "QlibInitError": (".qlib_runner", "QlibInitError"),
    "run_backtest": (".qlib_runner", "run_backtest"),
    "MosaicCachedStrategy": (".qlib_strategy", "MosaicCachedStrategy"),
    "ts_code_to_qlib_instrument": (".qlib_strategy", "ts_code_to_qlib_instrument"),
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib

        module_path, attr = _LAZY_IMPORTS[name]
        value = getattr(importlib.import_module(module_path, __package__), attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

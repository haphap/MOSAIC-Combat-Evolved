# Vendored data collectors — provenance & licensing

This directory vendors the qlib Tushare data-collection toolchain so MOSAIC's
A-share / ETF qlib-data ingest is **self-contained** (no external qlib source
checkout required at run time). It still imports `qlib.utils` from the
installed `pyqlib` package (the `backtest`/`ingest` extras).

## Third-party files — Microsoft qlib (MIT License)

Copied verbatim from https://github.com/microsoft/qlib (`scripts/`):

| Vendored path                              | Upstream path                              |
| ------------------------------------------ | ------------------------------------------ |
| `dump_bin.py`                              | `scripts/dump_bin.py`                      |
| `data_collector/base.py`                   | `scripts/data_collector/base.py`           |
| `data_collector/utils.py`                  | `scripts/data_collector/utils.py`          |

Each retains its original header: `Copyright (c) Microsoft Corporation.
Licensed under the MIT License.` See `LICENSE.qlib` for the full text.

## User-authored collectors

`data_collector/tushare/collector.py` and `data_collector/tushare_etf/collector.py`
(plus their `__init__.py`) are the project author's Tushare stock / ETF
collectors. They subclass the qlib `BaseCollector`/`BaseRun` and call
`dump_bin` above. The `source/` and `normalize/` data working-dirs from the
original location are **not** vendored (they are data, not code).

## Layout note

The collectors compute `SCRIPTS_DIR = CUR_DIR.parent.parent` and add it to
`sys.path` so `from dump_bin import ...` / `from data_collector.base import ...`
resolve. With `collector.py` at `collectors/data_collector/<vendor>/collector.py`,
`SCRIPTS_DIR` resolves to `collectors/`, where `dump_bin.py` + `data_collector/`
live — so the upstream import style works unchanged.

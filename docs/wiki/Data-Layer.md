# Data Layer

`mosaic/dataflows/` provides market + macro data to the agents, plus the qlib historical data base and ingest toolchain.

## Vendors

- **Tushare** (`tushare.py`) — primary A-share equity + ETF data (`pro.daily`, `pro.fund_daily`, `pro.index_daily`, financials) plus **research reports** (`pro.research_report`): `get_broker_reports` (行业研报, industry-level) and `get_stock_reports` (个股研报, stock-level). The LangChain `@tool` wrappers `get_broker_research` / `get_stock_research` live in `mosaic/agents/utils/research_report_tools.py` and are attached to the sector + superinvestor agents (see [Agents](Agents.md)).
- **akshare**, **yfinance**, **FRED** (`macro_data.py`, `fred.py`), Xueqiu heat, etc. — macro/global/sentiment tools.
- Tool selection is config-driven (`data_vendors` / `tool_vendors` in `MosaicConfig`).

## qlib local reader (`qlib_local.py`)

Reads OHLCV directly from qlib's binary feature files **without importing qlib**. Restores split-adjusted values to market scale (`original = adjusted / factor`). Provides `get_stock`, `get_indicator`, etc. matching the Tushare vendor signatures.

### Stock vs ETF routing

- **Stocks** → `cn_data` dataset (`~/.qlib/qlib_data/cn_data`), `QLIB_CN_DATA_PATH` override.
- **ETFs** → `cn_etf` dataset (`~/.qlib/qlib_data/cn_etf`), `QLIB_CN_ETF_PATH` override.
- An instrument is an ETF iff `sh5xxxxx` / `sz1xxxxx` (disjoint from stock prefixes sh6/sz0/sz3). Same routing is mirrored in the scorecard scorer (`_is_a_share_etf`) so ETF recommendations get forward-return scoring via `pro.fund_daily`.

## Ingest (`qlib_ingest.py`)

A thin orchestrator over the vendored collectors. Public API:

- `ingest_full(start, end, kind=...)` — pipeline: download → normalize → dump_to_bin.
- `ingest_incremental(end, kind=...)` — append latest days (`update_data_to_bin`).
- `sync_calendar(end, ...)` — refresh `calendars/day.txt` only.
- `validate_after_ingest(...)` — per-ticker gap report + skip manifest (`data/qlib_skipped.txt`).

`kind="stock"` drives cn_data, `kind="etf"` drives cn_etf. Exposed to the front-end via the `data.*` RPCs and the `pnpm dev data incremental|validate` CLI.

### Temp data stays out of the repo

The collectors' working dirs default to `~/.cache/mosaic_tushare_{raw,norm}` — **never** the project tree. Because the collectors are now vendored *inside* the repo, `ingest_incremental` / `sync_calendar` pass explicit `--source_dir`/`--normalize_dir` (and `.gitignore` ignores any stray `source/`/`normalize/`/`tmp/` under `collectors/`) so raw/normalized CSVs and `__inc_tmp__` never pollute the repo.

## Vendored collectors (`mosaic/dataflows/collectors/`)

So that ingest is self-contained (no external qlib checkout required at run time):

- `data_collector/tushare/collector.py` + `data_collector/tushare_etf/collector.py` — the stock + ETF collectors.
- `dump_bin.py`, `data_collector/base.py`, `data_collector/utils.py` — copied verbatim from **microsoft/qlib** (MIT), which the collectors build on.
- Run time still imports `qlib.utils` from `pyqlib` (the `backtest` extra). Subprocess deps are the `ingest` extra (fire/loguru/joblib/yahooquery/beautifulsoup4).

### Discovery

`find_qlib_collector(kind)` prefers the vendored copy; a *valid* `MOSAIC_QLIB_REPO` (stock) / `MOSAIC_QLIB_ETF_COLLECTOR` (etf) env override wins, with graceful fallback to the vendored copy if an env override is set-but-invalid.

### Licensing

MOSAIC is Apache-2.0; the three vendored qlib files remain **MIT** under Microsoft's copyright. See `mosaic/dataflows/collectors/NOTICE.md` + `LICENSE.qlib`. MIT is Apache-2.0-compatible.

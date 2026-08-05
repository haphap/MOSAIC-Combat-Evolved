# Data Layer

`mosaic/dataflows/` provides market + macro data to the agents, plus the qlib historical data base and ingest toolchain.

## Production source and tool boundary

- **Tushare** is the registered primary source for A-share/ETF prices, PIT
  membership, financial statements, fund shares, money flow, futures, FX, and
  the global `eco_cal` calendar when the endpoint has passed permission/schema
  preflight. `major_news`, `news`, `npr`, and `monetary_policy` are explicitly
  permission-denied and have no production client or fallback path.
- **China/PBOC** entity and policy observations come from registered NBS,
  Customs, MOF, and PBOC official directories plus verified Tushare series.
  **US** entity vintages use preregistered ALFRED/official series; Fed/NY Fed
  sources feed US financial conditions. **EU/euro-area** entity and financial
  observations use frozen Eurostat/ECB keys. World Bank is `CONTEXT_ONLY`.
- Raw responses remain in the private cache. Runtime collectors materialize a
  signed `AgentSnapshotBundle` before an Agent starts. The model can call only
  its zero-argument role snapshot; the bridge verifies Agent/stage/date/scope,
  consumes a single-use capability, and never recollects during `tools.call`.
- Sector, relationship, Superinvestor, and Decision nodes likewise use frozen
  role snapshots. Generic ticker search, OpenCLI/Caixin search, Xueqiu attention,
  research-report tools, and `get_rke_research_context` are absent from the
  production tool manifest. RKE remains shadow-only.
- Endpoint status, source mappings, and exact Agent/tool assignments are
  committed under `registry/data_sources/` and `registry/prompt_checks/`; missing
  required coverage fails closed instead of silently selecting another vendor.

### EU official API adapters

`official_macro_adapters.py` exposes closed, allowlisted URL builders and
bounded parsers for the frozen Eurostat, ECB, and World Bank series. Run
`uv run python scripts/probe_official_macro_sources.py` to refresh the
metadata-only transport preflight. Its public artifact records URLs, content
hashes, row counts, and readiness, but never provider observations. Live API
availability does not make a response point-in-time safe: production remains
blocked until the observations are joined to an archived append-only
release/vintage ledger satisfying `released_at/vintage_at <= as_of`.
This is not limited to EU/ECB: registered names for China, ALFRED, PBOC, US
financial conditions, commodities, and institutional flow are identity maps,
not production receipts. Every unresolved required branch is an explicit
source gap, so the formal builder rejects all currently unproved role
snapshots; only explicitly marked non-production smoke fixtures can bypass it.

### Geopolitical source preflight

`geopolitical_source_adapters.py` probes only the exact 15 roots in the closed
source manifest, with HTTPS/domain allowlists, response-size bounds, redirect
checks, and broad response-shape validation. Run
`uv run python scripts/probe_geopolitical_sources.py` to refresh its
metadata-only artifact. A successful root probe is not event evidence and
cannot activate a route. Production requires source-specific pagination,
publication-time parsing, complete route polling, and 30 continuous days of
availability/latency evidence; missing any required source keeps
`get_geopolitical_events_snapshot` fail-closed.
No built-in source-specific parser or verified continuous-preflight receipt
reader exists in the current checkout. The callback parser API is a
non-production harness and its poll rows cannot satisfy formal coverage;
transport success or a self-rehashed readiness manifest cannot promote it.
The private audit keeps route/query-level rows; the model receives a bounded
role projection with events and exact per-family coverage counts/hashes.

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

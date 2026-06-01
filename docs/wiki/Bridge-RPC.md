# Bridge RPC

The TypeScript front-end drives the Python sidecar over line-delimited JSON-RPC on stdio. Methods are registered by `@method("namespace.verb")` in `mosaic/bridge/handlers/*.py` and called from `mosaic-ts/src/bridge/types.ts` (`BridgeApi`).

Error envelopes map to `RpcError` with a numeric code (`mosaic/bridge/protocol.py`): `PARSE_ERROR -32700`, `INVALID_PARAMS -32602`, `METHOD_NOT_FOUND -32601`, `INTERNAL_ERROR -32603`, plus domain codes `CONFIG_ERROR -32010`, `PAPER_ERROR -32020`, `BACKTEST_ERROR -32030`, `SCORECARD_ERROR -32040`, `AUTORESEARCH_ERROR -32050`, `PRISM_ERROR -32060`, `JANUS_ERROR -32070`, `MIROFISH_ERROR -32080`, `DATA_ERROR -32090`.

## Full method surface

### tools
- `tools.list` — list registered sidecar tools.
- `tools.call` — invoke a tool by name + args.

Registered tool modules (`mosaic/bridge/handlers/tools.py` `_TOOL_MODULES`): `macro_tools` (8 Layer-1 macro tools) and `research_report_tools` (`get_broker_research` = 行业研报, `get_stock_research` = 个股研报). See [Agents](Agents.md) for which agents use which tools.

### config
- `config.default` — deep-copied `DEFAULT_CONFIG`.
- `config.get` — active runtime config for this process.
- `config.set` — replace active config (process-only).
- `config.save` — persist to `~/.mosaic/config.json` + apply (survives restarts).

### cache
- `cache.stats`, `cache.details`, `cache.cleanup`, `cache.clear`.

### calendar
- `calendar.list_trading_days`, `calendar.is_trading_day`, `calendar.next_trading_day`.

### scorecard
- `scorecard.append` — ingest a daily-cycle state's CIO actions.
- `scorecard.score_pending` — back-fill matured forward returns + alpha.
- `scorecard.list_skill` — per-agent skill rows.
- `scorecard.win_rate` — per-ticker directional hit rate.
- `scorecard.latest_cio_actions` — latest CIO portfolio for a cohort.

### darwinian
- `darwinian.compute`, `darwinian.get_weights`.

### prompts
- `prompts.read` (file at a git ref), `prompts.write` (commit on a branch via git_ops).

### autoresearch
- `autoresearch.trigger`, `autoresearch.evaluate_pending`, `autoresearch.record_mutation`,
  `autoresearch.revert_modification`, `autoresearch.get_log`, `autoresearch.list_active_branches`,
  `autoresearch.prepare_worktree`, `autoresearch.cleanup_worktree`.

### prism
- `prism.list_cohorts`, `prism.train_cohort`, `prism.cohort_status`, `prism.complete_cohort_run`, `prism.compare_cohorts`.

### janus
- `janus.run_daily`, `janus.get_weights`, `janus.regime`, `janus.get_history`.

### mirofish
- `mirofish.generate_scenarios`, `mirofish.score_recommendation`, `mirofish.record_run`,
  `mirofish.get_history`, `mirofish.save_context`, `mirofish.get_context`.

### backtest
- `backtest.create_run`, `backtest.append_actions`, `backtest.complete_run`,
  `backtest.get_run`, `backtest.list_runs`, `backtest.run_historical`.
- (The legacy backtrader `run_candidate_pool` path was removed; backtest is qlib-only.)
- `backtest.run_historical` accepts an optional `results_dir`: when set, the run also exports ATLAS-isomorphic artifacts (`summary.json` / `portfolio_trajectory.csv` / `equity_curve.png`) via `mosaic/backtest/results_export.py`. matplotlib is optional — the PNG is skipped if it's absent.

### paper
- `paper.register`, `paper.login`, `paper.logout`, `paper.current_user`,
  `paper.get_account`, `paper.reset_account`, `paper.buy`, `paper.sell`,
  `paper.get_positions`, `paper.get_trades`, `paper.suggest_order_from_signal`.

### data
- `data.incremental` — append latest trading days to cn_data/cn_etf (kind=stock|etf).
- `data.validate` — quality report + skip manifest for an ingested dataset.

## Adding a handler

1. Create `mosaic/bridge/handlers/<name>.py` with `@method("<name>.verb")` functions (validate params first, raise `RpcError`).
2. Import it in `mosaic/bridge/handlers/__init__.py` (import side-effect registers the methods).
3. Add a typed wrapper in `mosaic-ts/src/bridge/types.ts` (`BridgeApi`).

# Bridge RPC

The TypeScript front-end drives the Python sidecar over line-delimited JSON-RPC on stdio. Methods are registered by `@method("namespace.verb")` in `mosaic/bridge/handlers/*.py` and called from `mosaic-ts/src/bridge/types.ts` (`BridgeApi`).

Error envelopes map to `RpcError` with a numeric code (`mosaic/bridge/protocol.py`): `PARSE_ERROR -32700`, `INVALID_PARAMS -32602`, `METHOD_NOT_FOUND -32601`, `INTERNAL_ERROR -32603`, plus domain codes `CONFIG_ERROR -32010`, `PAPER_ERROR -32020`, `BACKTEST_ERROR -32030`, `SCORECARD_ERROR -32040`, `AUTORESEARCH_ERROR -32050`, `PRISM_ERROR -32060`, `JANUS_ERROR -32070`, `MIROFISH_ERROR -32080`, `DATA_ERROR -32090`.

## Full method surface

### tools
- `tools.prepare_capability` — materialize one frozen, role-bound snapshot bundle.
- `tools.issue_capability` — issue a stage-bound handle for an existing bundle.
- `tools.list` — list only the zero-argument snapshots authorized by a signed capability.
- `tools.call` — return one immutable authorized snapshot; it never runs a collector.
- `tools.terminate_capability` — close the stage capability after use.

`mosaic/bridge/handlers/tools.py` deliberately keeps `_TOOL_MODULES=()`. Generic macro, ETF, financial, technical, news, and research-report helpers are not registered on the model-visible RPC surface; raw collectors run only behind the controller's capability preparation boundary. See [Agents](Agents.md) for the exact role-to-snapshot matrix.

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
- Production v2: `darwinian.prepare_variant`,
  `darwinian.prepare_daily_cycle_outcomes`, `darwinian.refresh_v2_windows`, and
  `darwinian.publish_v2_updates`; calendar and opportunity-denominator inputs
  are server-owned.
- `darwinian.compute` and `darwinian.get_weights` require explicit
  `audit_only=true`, return `legacy_unverified`, and never feed production.

### prompts
- `prompts.read` (file at a git ref), `prompts.write` (commit on a branch via git_ops).

### autoresearch
- `autoresearch.trigger`, `autoresearch.evaluate_pending`, `autoresearch.record_mutation`,
  `autoresearch.revert_modification`, `autoresearch.get_log`, `autoresearch.list_active_branches`,
  `autoresearch.prepare_worktree`, `autoresearch.cleanup_worktree`,
  `autoresearch.historical_validate`, `autoresearch.historical_decide`.

`autoresearch.trigger` accepts a simulated `as_of_date`, run-scoped branch id, and pinned private
Prompt base only when `historical_sandbox=true`. `autoresearch.historical_decide` is restricted to
`history/*` candidates and copies kept files only to an isolated `history/*/active/*` branch; it
never merges or deletes the private Prompt default branch.

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

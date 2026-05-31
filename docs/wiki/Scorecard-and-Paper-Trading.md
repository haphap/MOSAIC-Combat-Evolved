# Scorecard & Paper Trading

## Scorecard (`mosaic/scorecard/`)

A SQLite-backed ledger of CIO recommendations and their realized performance.

### Scoring algorithm (`scorer.py`)

For each pending recommendation row:
1. Resolve the day-0 close and the day-N close (N = 5 and 21 **trading** days, not calendar days).
2. `forward_return_N = (close_N − close_d0) / close_d0`.
3. `alpha_5d = forward_return_5d − benchmark_return_5d` (default benchmark `000300.SH`, `MOSAIC_BENCHMARK_TICKER` override).

Price routing in `_fetch_close`:
- A-share **index** (e.g. `000300.SH`) → `pro.index_daily`.
- A-share **ETF** (`5xxxxx.SH` / `1xxxxx.SZ`) → `pro.fund_daily`.
- Otherwise **stock/HK/US** → `pro.daily` via `_fetch_price_data`.

This is what lets **ETF recommendations be scored** like stocks (so they show up in win-rate / skill).

### Anti-lookahead

`score_pending` snaps "today" backward to the last completed trading day and only scores rows whose forward horizon has matured; immature/missing rows are skipped (missing rows are still marked scored so they leave the pending set).

### Views / RPCs

- `scorecard.append` — ingest a daily-cycle state.
- `scorecard.score_pending(cohort, today)` — back-fill matured returns (idempotent; RPC, not a CLI subcommand).
- `scorecard.list_skill` — per-agent alpha / Sharpe / n.
- `scorecard.win_rate` — per-ticker directional hit rate: fraction where `sign(action) · future-5d-return > 0`, with sample size `n`.
- `scorecard.latest_cio_actions` — latest CIO portfolio.

### Honest interpretation of "win rate"

Win-rate is the directional hit rate of **this system's own CIO history** (over already-scored rows). It needs several days of daily-cycle + back-fill to be meaningful (small `n` is unreliable). It is **not** a universal "this stock will go up" prediction.

## Darwinian weights

`darwinian.compute` / `darwinian.get_weights` (`mosaic/scorecard/weights.py`) turn agent skill into evolutionary weights used downstream (e.g. by `autonomous_execution`).

## Paper trading (`mosaic/paper_trading/`)

A bespoke paper-trading engine (the project dropped backtrader; this is not backtrader-based).

- **Auth** — `register` / `login` / `logout` / `current_user` (bcrypt-hashed; the `trading` extra). Session at `~/.mosaic/paper_session.json`, DB at `~/.mosaic/paper_trading.db`.
- **Trading** — `buy` / `sell` with **T+1** settlement (bought shares aren't sellable same day), commission, and position tracking (`get_positions`, `get_trades`, `get_account`).
- **Signal → order** — `suggest_order_from_signal` turns an agent decision into a sized order (`paper.suggest_order_from_signal`).
- **Cross-user auth** is enforced on read + write paths.

CLI: `paper register|login|logout|account|buy|sell|positions|trades|suggest`.

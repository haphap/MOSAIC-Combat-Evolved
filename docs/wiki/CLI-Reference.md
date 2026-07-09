# CLI Reference

All commands run from `mosaic-ts/` via `pnpm dev <command>` (development) or `pnpm build && mosaic <command>` (after build). Commands are registered in `mosaic-ts/src/cli/index.ts`; each lives in `mosaic-ts/src/cli/commands/`.

Output defaults to Chinese reports; CLI flags stay English. `--lang zh|en|bilingual` switches report language where supported, and `--fake-llm` is the recommended zero-cost path.

## Core / plumbing

| Command | Purpose |
| --- | --- |
| `bridge-ping` | Spawn the Python sidecar and verify `tools.list` / `config.get`. |
| `tool-call <name> [argsJson]` | Invoke a single sidecar tool. |
| `tool-loop` | Run the tool-report loop. |

## Daily cycle

```bash
pnpm dev daily-cycle --cohort cohort_default --fake-llm
```
Options: `--cohort <name>`, `--date <YYYY-MM-DD>`, `--fake-llm`, `--llm-provider <name>`, `--model <name>`, `--base-url <url>`, `--prompts-repo <path>`, `--prompts-root <path>`, `--current-positions-json <json>`, `--current-positions-file <path>`, `--paper-positions`, `--paper-execute-deltas`, `--out <path>`. Runs all 25 agents through the LangGraph.js graph; the CIO writes `portfolio_actions` (persisted to the `recommendations` table).

Current-position fixture files may be a JSON array or an object with `current_positions`; each row must include ticker, current weight, cost basis, market price, unrealized PnL, holding days, entry date, source agent, entry thesis id, and last review date. `sector` is optional, but required for fixtures that exercise `max_sector_weight`. CIO validation rejects `position_decision` rows whose action or target/current/delta weights contradict `ADD`/`REDUCE`/`EXIT` semantics.
The resulting `position_audit` includes a `tool_status_summary` for the position source and market-price evidence scope.

Prompt source: by default agents load bundled prompts from `MOSAIC-Combat-Evolved/prompts/mosaic`. Set `MOSAIC_PROMPTS_REPO=/path/to/MOSAIC-Prompts` in `.env` to make all subsequent agent runs prefer a private prompt repo, or use `daily-cycle --prompts-repo <path>` / `--prompts-root <path>` for a single run.

## Scorecard / Darwinian

```bash
pnpm dev scorecard --cohort cohort_default --since 2024-01-01
pnpm dev darwinian --cohort cohort_default
```
- `scorecard` options: `--cohort <name>`, `--since <date>` (YYYY-MM-DD), `--out <path>`. `scorecard` is a single view command (no subcommands).
- `darwinian` options: `--cohort <name>`, `--date <YYYY-MM-DD>`, `--compute`, `--out <path>`.

> Forward-return back-fill is the `scorecard.score_pending` **RPC** (`BridgeApi.scorecardScorePending`), invoked programmatically / by the daily pipeline — it is not currently a standalone CLI subcommand. See [Scorecard & Paper Trading](Scorecard-and-Paper-Trading.md).

## Autoresearch (prompt self-evolution)

```bash
pnpm dev autoresearch trigger --cohort crisis_2008 --fake-llm --eval-days 5
pnpm dev autoresearch trigger --cohort cohort_default --agent cio --dry-run --fake-llm --mutation-mode knob_patch --eval-days 5
pnpm dev autoresearch log --cohort crisis_2008
```
Subcommands: `trigger`, `evaluate`, `log`, `branches`, `revert`.
`trigger` options include `--cohort`, `--agent`, `--max <n>`, `--dry-run`, `--fake-llm`, `--mutation-mode <auto|knob_patch|prompt_rewrite>`, `--eval-days <n>`, `--llm-provider/--model/--base-url`. `knob_patch` mode mutates Prompt IR/domain-knob paths, including position and MiroFish cards, without rewriting prompt prose.

## Prompt Operations

```bash
pnpm dev prompts init-private-repo ~/private-mosaic-prompts
pnpm dev prompts audit-versions --status keep
pnpm dev prompts verify-release --version-id 123
pnpm dev prompts gc-worktrees --repo-target all --max-age-hours 24
```

- `init-private-repo` creates the sparse private prompt repo. `--seed-baseline` is migration-only and creates broad override shadowing.
- `audit-versions` prints metadata only: ids, hashes, repo id, status, metrics, and branches. It does not show prompt content.
- `verify-release` checks the pinned release tuple (`code_commit_hash`, `prompt_repo_id`, `prompt_commit_hash`, `prompt_sha256`), recomputes the prompt SHA at the commit, and runs the tool compatibility gate.
- Before release, also run `pnpm prompt:drift -- --base-ref origin/main` or the scheduled drift check in the private operator environment.
- `gc-worktrees` removes stale managed worktrees under `data/worktrees` for the project and/or private prompt repo.
- Private prompt repos must use a private remote with least-privilege access and encrypted backup or encrypted-at-rest storage.

## PRISM (multi-regime training)

```bash
pnpm dev prism list
pnpm dev prism train --cohort crisis_2008 --fake-llm
```
Subcommands: `list`, `train`, `status`, `compare`. `train` options: `--cohort`/`--all`, `--start`/`--end`, `--dry-run`, `--fake-llm`, `--max-concurrent <n>`, `--max-mutations <n>`, LLM flags.

## JANUS (cross-cohort meta-weights)

```bash
pnpm dev janus run
pnpm dev janus weights
```
Subcommands: `run`, `weights`, `regime`, `history`. Options: `--date <date>`, `--window <n>`, `--days <n>`.

## MiroFish (reflexive simulation)

```bash
pnpm dev mirofish generate --swarm --seed 7      # generate scenarios
pnpm dev mirofish train --path-aware             # forward-train; --path-aware = drawdown-penalized scorer
pnpm dev mirofish train --current-positions-file .mosaic/tmp/mirofish-positions.json --fake-llm --dry-run
pnpm dev mirofish history
```
Subcommands: `generate`, `train`, `history`.
- `generate`: `--days <n>`, `--seed <n>`, `--print`, `--reflexive`, `--swarm`, `--engine <name>`, `--current-positions-json <json>`, `--current-positions-file <path>`, `--sector-exposure-json <json>`, `--theme-exposure-json <json>`.
- `train`: `--days`, `--seed`, `--agents <list>`, `--dry-run`, `--fake-llm`, `--reflexive`, `--engine <name>`, `--swarm`, `--scorer <name>`, `--path-aware`, the same portfolio-stress fixture flags, and LLM flags.
Portfolio-stress files may be either a JSON position array or an object with `current_positions`, `sector_exposure`, and `theme_exposure`; inline JSON flags override file values.

## Backtest

```bash
pnpm dev backtest --cohort cohort_default
```
Options: `--cohort`, `--prompt-commit-hash <hash>`, `--fake-llm`, LLM flags, `--veto-threshold <num>`, `--initial-cash <amount>`, `--benchmark <ticker>`, `--force-refill`, `--log-every <n>`, `--out <path>`. Plus `backtest-fill` for the cache-fill stage.
Stage-1 carry-over rebuilds `current_positions` from prior target weights and records holding days, entry thesis id, realized/unrealized PnL, residual drift, and closed-position exit reasons.

> The `--out` flag writes the metrics JSON. Full ATLAS-isomorphic artifacts (`summary.json` / `portfolio_trajectory.csv` / `equity_curve.png`) are produced by the `backtest.run_historical` **RPC** when called with a `results_dir` (see [Bridge RPC](Bridge-RPC.md)); not yet a `backtest` CLI flag.

## Paper trading

```bash
pnpm dev paper account
pnpm dev paper buy ...
```
Subcommands: `register`, `login`, `logout`, `account`, `buy`, `sell`, `positions`, `trades`, `suggest`. See [Scorecard & Paper Trading](Scorecard-and-Paper-Trading.md).

## Data ingest (vendored qlib collectors)

```bash
pnpm dev data incremental --kind stock|etf [--end YYYY-MM-DD]
pnpm dev data validate --kind stock|etf [--gap-threshold 0.01]
```
Long-running (minutes) — run as cron, not alongside latency-sensitive RPCs. See [Data Layer](Data-Layer.md).

## TUI

```bash
pnpm dev dashboard --cohort cohort_default [--user <name>]
```
See [TUI](TUI.md).

## Daily operation

The system is semi-automatic. A typical post-close cron pipeline:

```bash
cd mosaic-ts
pnpm dev daily-cycle --cohort cohort_default     # 25 agents → CIO portfolio (recommendations table)
# forward_return back-fill: call the scorecard.score_pending RPC (matures after T+5)
pnpm dev darwinian --cohort cohort_default
pnpm dev janus run
pnpm dev dashboard                               # review one screen
```

The `scorecard.score_pending` back-fill is an RPC rather than a CLI subcommand today; invoke it via the bridge (`BridgeApi.scorecardScorePending(cohort, today)`).

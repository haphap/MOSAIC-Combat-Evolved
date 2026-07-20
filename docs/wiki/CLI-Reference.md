# CLI Reference

All commands run from `mosaic-ts/` via `pnpm dev <command>` (development) or `pnpm build && mosaic <command>` (after build). Commands are registered in `mosaic-ts/src/cli/index.ts`; each lives in `mosaic-ts/src/cli/commands/`.

Output defaults to Chinese reports; CLI flags stay English. `--lang zh|en|bilingual` switches report language where supported, and `--fake-llm` is the recommended zero-cost path.

## Core / plumbing

| Command | Purpose |
| --- | --- |
| `bridge-ping` | Spawn the Python sidecar and verify `config.get`; report that tools are capability-bound. |
| `tool-loop` | Run the signed China Macro snapshot tool loop. |

## Daily cycle

```bash
cd ..
mkdir -p .mosaic/tmp
# Use an A-share trading day; this deterministic default is verified.
SMOKE_DATE="${SMOKE_DATE:-2026-07-17}"
SMOKE_ROOT="$(mktemp -d .mosaic/tmp/structured-smoke.XXXXXX)"
eval "$(uv run python scripts/build_structured_smoke_fixtures.py \
  --root "$SMOKE_ROOT" --date "$SMOKE_DATE" --shell-exports)"
pnpm --dir mosaic-ts dev daily-cycle \
  --cohort cohort_default --date "$SMOKE_DATE" --fake-llm
```
Options: `--cohort <name>`, `--date <YYYY-MM-DD>`, `--fake-llm`, `--structured-smoke`, `--llm-provider <name>`, `--model <name>`, `--base-url <url>`, `--max-tokens <count>`, `--prompts-repo <path>`, `--prompts-root <path>`, `--current-positions-json <json>`, `--current-positions-file <path>`, `--paper-positions`, `--paper-execute-deltas`, `--out <path>`. Runs all 28 logical agents through 29 LangGraph.js stages. Both smoke modes use bundled prompts and the explicitly marked synthetic PIT bundle; `--fake-llm` adds a canned model, while `--structured-smoke` uses a real structured-output provider with temperature 0 and a default 8192-token completion cap. Neither mode performs production release, scorecard, outcome, RKE, or paper-order writes.

The same fresh bundle can drive a real-model contract smoke without licensed payloads; replace `--fake-llm` with `--structured-smoke` and the desired provider options. The builder refuses a nonempty root and never deletes existing data.

The CLI enables the matching non-production gate only for those two flags and clears it for production. The hash-bound bundle is marked `SYNTHETIC_NON_PRODUCTION`, contains no vendor prose, and verifies graph/schema/tool wiring only. It does not replace the separate live Tushare permission/schema probe or source-readiness audits.

Current-position fixture files may be a JSON array or an object with `current_positions`; each row must include ticker, current weight, cost basis, market price, unrealized PnL, holding days, entry date, source agent, entry thesis id, and last review date. `sector` is optional, but required for fixtures that exercise `max_sector_weight`. CIO validation rejects `position_decision` rows whose action or target/current/delta weights contradict `ADD`/`REDUCE`/`EXIT` semantics.
The resulting `position_audit` includes a `tool_status_summary` for the position source and market-price evidence scope.
When the position snapshot is missing, runtime evidence audit records
`current_position_snapshot` as missing and marks unresolved market data as
`current_market_data:ticker_scope:unknown`; confirmed empty portfolios still use
an empty market-data scope and do not trigger the missing-data cap.

Prompt source: `--fake-llm` and `--structured-smoke` explicitly use bundled prompts. Formal paper/backtest/live runs require the hash-pinned private prompt repository and fail closed if it is unavailable or drifts; they never fall back to bundled prompts. Configure `MOSAIC_PROMPTS_REPO=/path/to/MOSAIC-Prompts` or use `daily-cycle --prompts-repo <path>`. `--prompts-root` is restricted to non-production smoke/authoring paths.

## Scorecard / Darwinian

```bash
pnpm dev scorecard --cohort cohort_default --since 2024-01-01
pnpm dev darwinian --cohort cohort_default
```
- `scorecard` options: `--cohort <name>`, `--since <date>` (YYYY-MM-DD), `--out <path>`. `scorecard` is a single view command (no subcommands).
- `darwinian` options: `--cohort <name>`, `--date <YYYY-MM-DD>`, `--compute`, `--out <path>`.
  This command exposes the `legacy_unverified`, audit-only v1 table; production
  weights come from a frozen Darwinian-v2 production variant.

> Forward-return back-fill is the `scorecard.score_pending` **RPC** (`BridgeApi.scorecardScorePending`), invoked programmatically / by the daily pipeline — it is not currently a standalone CLI subcommand. See [Scorecard & Paper Trading](Scorecard-and-Paper-Trading.md).

## Legacy Autoresearch diagnostics

```bash
pnpm dev autoresearch trigger --cohort crisis_2008 --dry-run --fake-llm --eval-days 5
pnpm dev autoresearch evaluate --cohort crisis_2008
pnpm dev autoresearch log --cohort crisis_2008
```
Subcommands: `trigger`, `evaluate`, `log`, `branches`, `revert`, and
`review-domain`. This surface is audit-only: evaluation terminates as
`legacy_unverified`, `review-domain` accepts only `--decision revert`, and no
command can publish a production behavior. Production evolution is KNOT-only
through the governed paired-research RPC/release workflow.

## Prompt Operations

```bash
pnpm dev prompts init-private-repo ~/private-mosaic-prompts
pnpm dev prompts audit-versions --status keep
pnpm dev prompts verify-release --version-id 123
pnpm dev prompts prompt-token-budget \
  --private-prompts-root /path/to/MOSAIC-Prompts/prompts/mosaic \
  --baseline ../registry/prompt_checks/prompt_token_budget_manifest_v1.json \
  --out ../.mosaic/prompt-token-budget-candidate.json
pnpm dev prompts gc-worktrees --repo-target all --max-age-hours 24
```

- `init-private-repo` creates the sparse private prompt repo. `--seed-baseline` is migration-only and creates broad override shadowing.
- `audit-versions` prints metadata only: ids, hashes, repo id, status, metrics, and branches. It does not show prompt content.
- `verify-release` checks the pinned release tuple (`code_commit_hash`, `prompt_repo_id`, `prompt_commit_hash`, `prompt_sha256`), recomputes the prompt SHA at the commit, and runs the tool compatibility gate.
- Domain/research-knob catalogs are generated and tested only in the private
  KNOT repository; the public CLI does not export their contents.
- `prompt-token-budget` measures all 116 private/bundled stage-language rows
  with the pinned tokenizer, validates semantic parity and absolute caps, and
  applies the 1.25x committed-baseline growth gate.
- Before release, also run `pnpm prompt:drift -- --base-ref origin/main` or the scheduled drift check in the private operator environment.
- `gc-worktrees` removes stale managed worktrees under `data/worktrees` for the project and/or private prompt repo.
- Private prompt repos must use a private remote with least-privilege access and encrypted backup or encrypted-at-rest storage.

Release lifecycle commands are separate from prompt asset commands:

```bash
pnpm dev prompt-release provision-baseline --manifest APPROVED_BASELINE.json \
  --private-prompts-repo "$MOSAIC_PROMPTS_REPO" --approved-by operator:NAME \
  --reason 'import previously approved baseline'
pnpm dev prompt-release canary --release-id RELEASE_ID --approved-by operator:NAME \
  --reason 'bounded canary' --traffic-percent 10
pnpm dev prompt-release summarize-slo --release-id RELEASE_ID \
  --observation-ended-at 2026-07-10T12:00:00Z \
  --out .mosaic/prompt-releases/RELEASE_ID-slo.json
pnpm dev prompt-release activate --release-id RELEASE_ID --approved-by operator:NAME \
  --reason 'closed canary SLO passed' \
  --slo-artifact .mosaic/prompt-releases/RELEASE_ID-slo.json
pnpm dev prompt-release rollback --release-id RELEASE_ID \
  --approved-by operator:NAME --reason 'operator rollback'
```

Set `MOSAIC_PROMPT_CANARY_EVENT_LOG` before canary traffic and keep it set for
summary and activation. Activation recomputes the assignment/terminal journal
closure; handwritten, stale, or subset measurements are rejected.

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
pnpm dev mirofish generate --swarm --seed 7      # generate + persist the agent context
pnpm dev mirofish generate --engine oasis --scenarios base --max-rounds 1  # real-service smoke
pnpm dev mirofish train --path-aware             # forward-train; --path-aware = drawdown-penalized scorer
pnpm dev mirofish train --current-positions-file .mosaic/tmp/mirofish-positions.json --fake-llm --dry-run
pnpm dev mirofish history
```
Subcommands: `generate`, `train`, `history`.
- `generate`: `--days <n>`, `--seed <n>`, `--print`, `--reflexive`, `--swarm`, `--engine <name>`, `--max-rounds <n>`, `--current-positions-json <json>`, `--current-positions-file <path>`, `--sector-exposure-json <json>`, `--theme-exposure-json <json>`.
- `train`: `--days`, `--seed`, `--agents <list>`, `--dry-run`, `--fake-llm`, `--reflexive`, `--engine <name>`, `--swarm`, `--scorer <name>`, `--path-aware`, the same portfolio-stress fixture flags, and LLM flags.
Portfolio-stress files and `--current-positions-json` may be either a JSON position array or an object with `current_positions`, `sector_exposure`, and `theme_exposure`; explicit exposure flags override file or inline fixture values. Each position must include a positive `market_price` or `current_price`.
`generate` and non-dry-run `train` automatically persist the scenario context consumed by the next Daily Cycle; `train --dry-run` persists neither context nor training rows.

## Backtest

```bash
pnpm dev backtest --cohort cohort_default
```
Options: `--cohort`, `--prompt-commit-hash <hash>`, `--fake-llm`, LLM flags, `--veto-threshold <num>`, `--initial-cash <amount>`, `--benchmark <ticker>`, `--force-refill`, `--log-every <n>`, `--out <path>`. Plus `backtest-fill` for the cache-fill stage.
Stage-1 carry-over rebuilds `current_positions` from prior target weights and records holding days, entry thesis id, realized/unrealized PnL, residual drift, and closed-position exit reasons.

For the resumable 2009→latest PIT walk-forward path, use `backtest-evolve` with a pinned
private Prompt commit and a `.mosaic/` run directory. It resolves the current sndr
`nvidia-qwen3.6-35b-a3b-nvfp4-5090` preset, keeps Fish context disabled, checkpoints every
trading day, rejects sndr settings outside the operational 128K/0.85 envelope, and evaluates
monthly historical Prompt candidates in isolated private branches. Sustained real-model runs
must use the runbook's VRAM guard so the 256 MiB compute-card floor is measured and enforced.
See [2009 Agents historical evolution runbook](../runbooks/agents_history_evolution_2009.md).

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
See [TUI](TUI.md). Key 8 shows the latest UI-only human-readable explanation for each Agent; `j/k` moves through the 28-Agent roster.

## Daily operation

The system is semi-automatic. A typical post-close cron pipeline:

```bash
cd mosaic-ts
pnpm dev daily-cycle --cohort cohort_default     # 28 agents / 29 stages → CIO portfolio
# forward_return back-fill: call the scorecard.score_pending RPC (matures after T+5)
pnpm dev darwinian --cohort cohort_default
pnpm dev janus run
pnpm dev dashboard                               # review one screen
```

The `scorecard.score_pending` back-fill is an RPC rather than a CLI subcommand today; invoke it via the bridge (`BridgeApi.scorecardScorePending(cohort, today)`).

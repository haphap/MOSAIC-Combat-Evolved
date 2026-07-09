# TUI

`pnpm dev dashboard` renders an Ink (React-in-terminal) dashboard that aggregates existing read RPCs into one screen, plus an editable settings page. Component: `mosaic-ts/src/tui/Dashboard.tsx`; command: `mosaic-ts/src/cli/commands/dashboard.ts`. Options: `--cohort <name>`, `--user <name>`.

Navigation: keys **1–7** switch tabs, **r** refresh (manual; no auto-poll), **q** quit. The `BridgeApi` is injected, so the component is unit-tested with fakes.

## Tabs

| Key | Tab | Shows |
| --- | --- | --- |
| 1 | today | Latest CIO plan with position review counts, warning labels, current/target/delta weights, thesis status, risk flags, and dissent notes. |
| 2 | winrate | Per-ticker directional hit rate (`win_rate`, `n`, avg 5d directional return). |
| 3 | skill | Per-agent `mean_alpha_5d` / `sharpe_window` / `n_obs`. |
| 4 | paper | Paper account, current positions, target-current execution deltas, latest submitted/filled paper trades, and recent backtest carry-over diagnostics. |
| 5 | cohorts | Per-cohort run count / branch / last-run date. |
| 6 | mirofish | Latest simulation-only scenario context, context hash/as-of metadata, per-position stress, and recent forward-training runs. |
| 7 | settings | Editable, persisted config (see below). |

## Settings tab (key 7)

A curated, editable view of the commonly-tuned config, persisted to `~/.mosaic/config.json` via `config.save`. Controls: **↑↓** select · **enter** edit (string/number) · **space** toggle bool / cycle enum · **s** save · **esc** cancel. While editing, the tab owns all keystrokes (so typing `q` doesn't quit).

Editable fields: `llm_provider`, `deep_think_llm`, `quick_think_llm`, `output_language`, `active_cohort`; the five `autoresearch.*` numbers; `autoresearch.git.push` / `remote`; `mirofish.engine` / `scorer` / `inject_context`.

See [Configuration](Configuration.md) for what these mean and how persistence works.

## Position-Aware Review

The dashboard surfaces the same position loop used by `daily-cycle`: loaded and
reviewed position counts, stale thesis and stop-loss override counts, explicit
warning labels, target-current deltas, per-action fired caps, declared knob
influence ids, decision-agent audit summaries, and MiroFish per-position stress.
Stale-thesis actions are expected to carry the `stale_thesis` risk flag and an
explicit review reason; stop-loss override counts read the normalized
`stop_loss_breached` risk flag. CIO action rows are also checked against
`position_decision` semantics, so `ADD`/`REDUCE`/`EXIT` must agree with action,
target, current, and delta weights.
Operator steps and migration checks live in
[`docs/runbooks/position_aware_prompt_evolution.md`](../runbooks/position_aware_prompt_evolution.md).

Backtest diagnostics are stage-1 cache summaries: turnover proxy, observed
holding-day proxy, stale-thesis proxy, and action mix come from cached
`backtest_actions`; alpha/drawdown opportunity metrics stay explicitly marked as
requiring stage-2 scored positions.

MiroFish context must carry a non-future `as_of_date`. Context missing that bound
or dated after the run is disabled before prompt injection.

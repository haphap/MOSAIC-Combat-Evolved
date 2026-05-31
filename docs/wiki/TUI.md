# TUI

`pnpm dev dashboard` renders an Ink (React-in-terminal) dashboard that aggregates existing read RPCs into one screen, plus an editable settings page. Component: `mosaic-ts/src/tui/Dashboard.tsx`; command: `mosaic-ts/src/cli/commands/dashboard.ts`. Options: `--cohort <name>`, `--user <name>`.

Navigation: keys **1–7** switch tabs, **r** refresh (manual; no auto-poll), **q** quit. The `BridgeApi` is injected, so the component is unit-tested with fakes.

## Tabs

| Key | Tab | Shows |
| --- | --- | --- |
| 1 | today | Latest CIO plan — ticker / action / target weight % / rationale. |
| 2 | winrate | Per-ticker directional hit rate (`win_rate`, `n`, avg 5d directional return). |
| 3 | skill | Per-agent `mean_alpha_5d` / `sharpe_window` / `n_obs`. |
| 4 | paper | Paper account (cash / market value / total / realized + unrealized PnL) + positions. |
| 5 | cohorts | Per-cohort run count / branch / last-run date. |
| 6 | mirofish | Latest scenario context (regime / highest-conviction direction / tail risk) + recent forward-training runs. |
| 7 | settings | Editable, persisted config (see below). |

## Settings tab (key 7)

A curated, editable view of the commonly-tuned config, persisted to `~/.mosaic/config.json` via `config.save`. Controls: **↑↓** select · **enter** edit (string/number) · **space** toggle bool / cycle enum · **s** save · **esc** cancel. While editing, the tab owns all keystrokes (so typing `q` doesn't quit).

Editable fields: `llm_provider`, `deep_think_llm`, `quick_think_llm`, `output_language`, `active_cohort`; the five `autoresearch.*` numbers; `autoresearch.git.push` / `remote`; `mirofish.engine` / `scorer` / `inject_context`.

See [Configuration](Configuration.md) for what these mean and how persistence works.

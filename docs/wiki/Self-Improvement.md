# Self-Improvement

MOSAIC's self-improvement stack has four parts: **Autoresearch** (prompt evolution), **PRISM** (multi-regime training), **JANUS** (cross-cohort meta-weighting), and **MiroFish** (reflexive simulation).

## Autoresearch — prompt self-evolution

`mosaic/autoresearch/` — selects an agent, has an LLM rewrite its prompt, commits the mutation on a git feature branch, runs a two-stage backtest to compute **ΔSharpe**, then keeps (merge to main) or reverts (delete branch) by threshold.

- **`git_ops.py`** (`GitOps`) — thin, fail-loud wrapper over `git`. Mutations are committed inside a throwaway `git worktree` so the operator's working tree is never touched. Keep = `merge_to_main`, revert = `delete_branch`.
- **`constraints.py`** — `check_cooldown` (24h per agent), `check_monthly_cap` (≤100/cohort/month), `check_keep_lockout` (3 days after a keep).
- **`evaluator.py`** — computes ΔSharpe over the evaluation horizon (default 5 trading days).
- **`decider.py`** — keep iff `delta_sharpe ≥ keep_threshold_delta_sharpe` (default 0.1).
- **`knob_patch` mode** — mutates Prompt IR/domain-knob paths, including position-aware and MiroFish cards, without rewriting prompt prose.

Branch naming: `cohort/{name}/auto/{agent}/{YYYY-MM-DD}`.

### Optional: mirror kept mutations to a self-hosted git server

`autoresearch.git` config (default **OFF**): when `push: true`, the keep-path runs `git push <remote> main` after a successful merge. A push failure is logged and swallowed (the keep decision still stands locally); a failed merge skips push. Credentials are the operator's responsibility (SSH key / credential helper). Config: `{ "push": false, "remote": "origin" }`.

Defaults (`mosaic/default_config.py` → `autoresearch`): `agent_mutation_cooldown_hours: 24`, `keep_revert_lockout_days: 3`, `keep_threshold_delta_sharpe: 0.1`, `monthly_modification_cap_per_cohort: 100`, `evaluation_horizon_trading_days: 5`.

## PRISM — multi-regime training

`mosaic/prism/` trains prompt evolution across **7 market-regime cohorts**, sequentially per cohort with bounded intra-layer concurrency. Cohorts (`prism/cohorts.py`):

| Cohort | Window | Regime |
| --- | --- | --- |
| `bull_2007` | 2006-01-04 → 2007-10-16 | 牛市顶 6124 |
| `crisis_2008` | 2007-10-17 → 2008-10-28 | 暴跌 70%, 1664 见底 |
| `bull_2016` | 2016-01-29 → 2017-12-29 | 慢牛 + 白酒 |
| `crisis_covid` | 2018-10-19 → 2020-03-23 | 贸易战 + 疫情合并 |
| `recovery_2020` | 2020-03-24 → 2020-12-31 | 疫后宽松反弹 |
| `euphoria_2021` | 2020-07-01 → 2021-02-18 | 茅指数高峰 (启动 cohort) |
| `rate_tightening` | 2022-04-01 → 2023-12-31 | 中特估 + 量化退潮 + Fed 加息 |

CLI: `prism list|train|status|compare`.

## JANUS — cross-cohort meta-weighting

`mosaic/janus/` computes softmax meta-weights across cohorts (so the live system blends regime-specialized prompts by current-regime fit). CLI: `janus run|weights|regime|history`; RPCs `janus.run_daily|get_weights|regime|get_history`.

## MiroFish — reflexive simulation

`mosaic/mirofish/` synthesizes forward scenarios from a behavioral agent swarm and grades recommendations against them.

- **engine** (`config.mirofish.engine`): `montecarlo` (default — i.i.d. correlated paths + optional reflexivity kernel) or `swarm` (agent-to-agent interaction). Swarm is opt-in.
- **scorer** (`config.mirofish.scorer`): `terminal` (default — direction × cumulative return) or `path_aware` (drawdown-penalized equity curve; the `--path-aware` shorthand on `mirofish train`).
- **inject_context** (`config.mirofish.inject_context`, default OFF): append one shared, simulation-only scenario context to the L4 CRO, autonomous execution, and CIO prompts for the run (see [Agents](Agents.md)).
- An OASIS adapter can drive a real external MiroFish engine over HTTP (`MOSAIC_MIROFISH_URL`).

CLI: `mirofish generate|train|history`; RPCs under `mirofish.*`.

> Memory/persona (7M.2/7M.3) is deferred/NO-GO per gain validation; documented in `docs/plans/mosaic-tsplan.md` §11.8.1.

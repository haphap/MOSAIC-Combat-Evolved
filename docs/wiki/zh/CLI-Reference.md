# CLI 参考

所有命令在 `mosaic-ts/` 下通过 `pnpm dev <command>`(开发期)或 `pnpm build && mosaic <command>`(构建后)运行。命令注册于 `mosaic-ts/src/cli/index.ts`,各自实现于 `mosaic-ts/src/cli/commands/`。

输出默认中文报告;CLI 选项保持英文。`--lang zh|en|bilingual` 可在支持处切换报告语言,`--fake-llm` 是推荐的零成本通道。

## 核心 / 管道

| 命令 | 用途 |
| --- | --- |
| `bridge-ping` | spawn Python sidecar 并验证 `tools.list` / `config.get`。 |
| `tool-call <name> [argsJson]` | 调用单个 sidecar 工具。 |
| `tool-loop` | 运行 tool-report 循环。 |

## 日循环

```bash
pnpm dev daily-cycle --cohort cohort_default --fake-llm
```
选项:`--cohort <name>`、`--date <YYYY-MM-DD>`、`--fake-llm`、`--llm-provider <name>`、`--model <name>`、`--base-url <url>`、`--out <path>`。跑全部 25 agents,CIO 写出 `portfolio_actions`(落库 `recommendations` 表)。

## 评分 / Darwinian

```bash
pnpm dev scorecard --cohort cohort_default --since 2024-01-01
pnpm dev darwinian --cohort cohort_default
```
- `scorecard` 选项:`--cohort <name>`、`--since <date>`(YYYY-MM-DD)、`--out <path>`。`scorecard` 是单一视图命令(无子命令)。
- `darwinian` 选项:`--cohort <name>`、`--date <YYYY-MM-DD>`、`--compute`、`--out <path>`。

> forward-return 回填是 `scorecard.score_pending` **RPC**(`BridgeApi.scorecardScorePending`),由程序/日常流水线调用 —— 目前不是独立 CLI 子命令。见[评分与纸上交易](Scorecard-and-Paper-Trading.md)。

## Autoresearch(提示词自进化)

```bash
pnpm dev autoresearch trigger --cohort crisis_2008 --fake-llm --eval-days 5
pnpm dev autoresearch log --cohort crisis_2008
```
子命令:`trigger`、`evaluate`、`log`、`branches`、`revert`。`trigger` 选项含 `--cohort`、`--agent`、`--max <n>`、`--dry-run`、`--fake-llm`、`--eval-days <n>`、`--llm-provider/--model/--base-url`。

## PRISM(多周期训练)

```bash
pnpm dev prism list
pnpm dev prism train --cohort crisis_2008 --fake-llm
```
子命令:`list`、`train`、`status`、`compare`。`train` 选项:`--cohort`/`--all`、`--start`/`--end`、`--dry-run`、`--fake-llm`、`--max-concurrent <n>`、`--max-mutations <n>`、LLM 选项。

## JANUS(跨 cohort 元权重)

```bash
pnpm dev janus run
pnpm dev janus weights
```
子命令:`run`、`weights`、`regime`、`history`。选项:`--date <date>`、`--window <n>`、`--days <n>`。

## MiroFish(反身性模拟)

```bash
pnpm dev mirofish generate --swarm --seed 7      # 生成情景
pnpm dev mirofish train --path-aware             # 前向训练;--path-aware = 回撤惩罚评分
pnpm dev mirofish history
```
子命令:`generate`、`train`、`history`。
- `generate`:`--days <n>`、`--seed <n>`、`--print`、`--reflexive`、`--swarm`、`--engine <name>`。
- `train`:`--days`、`--seed`、`--agents <list>`、`--dry-run`、`--fake-llm`、`--reflexive`、`--engine <name>`、`--swarm`、`--scorer <name>`、`--path-aware`、LLM 选项。

## 回测

```bash
pnpm dev backtest --cohort cohort_default
```
选项:`--cohort`、`--prompt-commit-hash <hash>`、`--fake-llm`、LLM 选项、`--veto-threshold <num>`、`--initial-cash <amount>`、`--benchmark <ticker>`、`--force-refill`、`--log-every <n>`、`--out <path>`。另有 `backtest-fill` 做缓存填充阶段。

> `--out` 写指标 JSON。完整 ATLAS 同构产物(`summary.json` / `portfolio_trajectory.csv` / `equity_curve.png`)由 `backtest.run_historical` **RPC** 在传入 `results_dir` 时产出(见[桥 RPC](Bridge-RPC.md));尚未做成 `backtest` CLI 标志。

## 纸上交易

```bash
pnpm dev paper account
pnpm dev paper buy ...
```
子命令:`register`、`login`、`logout`、`account`、`buy`、`sell`、`positions`、`trades`、`suggest`。见[评分与纸上交易](Scorecard-and-Paper-Trading.md)。

## 数据 ingest(vendored qlib 采集器)

```bash
pnpm dev data incremental --kind stock|etf [--end YYYY-MM-DD]
pnpm dev data validate --kind stock|etf [--gap-threshold 0.01]
```
长耗时(分钟级)—— 当作 cron 跑,不要与延迟敏感的 RPC 并行。见[数据层](Data-Layer.md)。

## TUI

```bash
pnpm dev dashboard --cohort cohort_default [--user <name>]
```
见 [TUI](TUI.md)。

## 日常运维

系统是半自动的。典型的收盘后 cron 流水线:

```bash
cd mosaic-ts
pnpm dev daily-cycle --cohort cohort_default     # 25 agents → CIO 组合(recommendations 表)
# forward_return 回填:调用 scorecard.score_pending RPC(T+5 后成熟)
pnpm dev darwinian --cohort cohort_default
pnpm dev janus run
pnpm dev dashboard                               # 看一屏
```
`scorecard.score_pending` 回填目前是 RPC 而非 CLI 子命令;经桥调用(`BridgeApi.scorecardScorePending(cohort, today)`)。

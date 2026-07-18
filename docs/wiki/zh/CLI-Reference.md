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
选项:`--cohort <name>`、`--date <YYYY-MM-DD>`、`--fake-llm`、`--structured-smoke`、`--llm-provider <name>`、`--model <name>`、`--base-url <url>`、`--max-tokens <count>`、`--prompts-repo <path>`、`--prompts-root <path>`、`--current-positions-json <json>`、`--current-positions-file <path>`、`--paper-positions`、`--paper-execute-deltas`、`--out <path>`。跑全部 28 个逻辑 Agent、29 个执行阶段。`--structured-smoke` 使用真实 structured-output provider 和 bundled prompt，固定 temperature 0、默认每次 completion 最多 6144 tokens，并关闭 production release、scorecard、outcome、RKE 与纸单写入。

如需在不使用许可数据正文的前提下复现真实模型合同 smoke，请先生成显式合成 PIT bundle：

```bash
cd ..
uv run python scripts/build_structured_smoke_fixtures.py \
  --root .mosaic/tmp/structured-smoke-cache --date 2026-07-17
```

运行 `daily-cycle --structured-smoke` 时使用生成器输出的两个环境变量。该 bundle 标记为 `SYNTHETIC_NON_PRODUCTION`，不含供应商正文，只验证图、schema 与工具接线；它不能替代独立的 Tushare 实时权限/schema probe 或数据源 readiness 审计。

current-position fixture 文件可以是 JSON 数组,也可以是包含 `current_positions` 的对象;每行必须包含 ticker、当前权重、成本、市场价格、未实现盈亏、持有天数、建仓日期、来源 agent、entry thesis id 和最近复盘日期。`sector` 可选,但用于测试 `max_sector_weight` 时必须提供。CIO 校验会拒绝 action 或 target/current/delta 权重与 `ADD`/`REDUCE`/`EXIT` 语义矛盾的 `position_decision` 行。
输出的 `position_audit` 会带 `tool_status_summary`,记录持仓来源与市场价格 evidence scope 状态。
当持仓快照缺失时,runtime evidence audit 会把 `current_position_snapshot` 记录为
missing,并把无法解析的行情 scope 标成
`current_market_data:ticker_scope:unknown`;确认空仓仍使用空行情 scope,不会触发
missing-data cap。

Prompt 来源:默认使用 `MOSAIC-Combat-Evolved/prompts/mosaic` 内置 prompts。在 `.env` 中设置 `MOSAIC_PROMPTS_REPO=/path/to/MOSAIC-Prompts` 后,后续 agent 运行会优先使用 private prompt repo;也可以用 `daily-cycle --prompts-repo <path>` / `--prompts-root <path>` 对单次运行覆盖。

## 评分 / Darwinian

```bash
pnpm dev scorecard --cohort cohort_default --since 2024-01-01
pnpm dev darwinian --cohort cohort_default
```
- `scorecard` 选项:`--cohort <name>`、`--since <date>`(YYYY-MM-DD)、`--out <path>`。`scorecard` 是单一视图命令(无子命令)。
- `darwinian` 选项:`--cohort <name>`、`--date <YYYY-MM-DD>`、`--compute`、`--out <path>`。

> forward-return 回填是 `scorecard.score_pending` **RPC**(`BridgeApi.scorecardScorePending`),由程序/日常流水线调用 —— 目前不是独立 CLI 子命令。见[评分与纸上交易](Scorecard-and-Paper-Trading.md)。

## 旧 Autoresearch 诊断

```bash
pnpm dev autoresearch trigger --cohort crisis_2008 --dry-run --fake-llm --eval-days 5
pnpm dev autoresearch evaluate --cohort crisis_2008
pnpm dev autoresearch log --cohort crisis_2008
```
子命令:`trigger`、`evaluate`、`log`、`branches`、`revert`、`review-domain`。
该接口只供审计：评价终态为 `legacy_unverified`，`review-domain` 只接受
`--decision revert`，任何子命令都不能发布生产行为。生产演化只能走 KNOT 配对研究与
受治理的 release RPC 流程。

## Prompt 运维

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

- `init-private-repo` 创建 sparse private prompt repo。`--seed-baseline` 仅用于迁移,会制造大面积 override shadowing。
- `audit-versions` 只打印 metadata: id、hash、repo id、状态、指标和分支,不展示 prompt 正文。
- `verify-release` 检查 pinned release tuple(`code_commit_hash`、`prompt_repo_id`、`prompt_commit_hash`、`prompt_sha256`),在 commit 上重算 prompt SHA,并运行工具兼容性 gate。
- `prompts export-domain-knob-catalog` 会渲染可执行 domain-card catalog,并校验 in-run dependency scope、数值边界/step、code-enforced validator/audit 字段等 schema 条件。
- `prompt-token-budget` 使用固定 tokenizer 测量 104 条
  private/bundled stage-language 记录,校验语义 parity、绝对上限及相对已提交
  baseline 的 1.25x 增长门槛。
- release 前还要在 private operator 环境运行 `pnpm prompt:drift -- --base-ref origin/main` 或 scheduled drift check。
- `gc-worktrees` 清理项目 repo / private prompt repo 的 `data/worktrees` 下过期托管 worktree。
- private prompt repo 必须配置 private remote、最小权限访问,并启用加密备份或静态加密存储。

Release lifecycle 使用独立命令:

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

Canary 流量、summary 与 activation 必须使用同一个
`MOSAIC_PROMPT_CANARY_EVENT_LOG`;activation 会重算 assignment/terminal journal
closure，拒绝手写、过期或抽样 measurements。

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
pnpm dev mirofish generate --swarm --seed 7      # 生成情景并持久化 agent context
pnpm dev mirofish generate --engine oasis --scenarios base --max-rounds 1  # 真实服务 smoke
pnpm dev mirofish train --path-aware             # 前向训练;--path-aware = 回撤惩罚评分
pnpm dev mirofish train --current-positions-file .mosaic/tmp/mirofish-positions.json --fake-llm --dry-run
pnpm dev mirofish history
```
子命令:`generate`、`train`、`history`。
- `generate`:`--days <n>`、`--seed <n>`、`--print`、`--reflexive`、`--swarm`、`--engine <name>`、`--max-rounds <n>`、`--current-positions-json <json>`、`--current-positions-file <path>`、`--sector-exposure-json <json>`、`--theme-exposure-json <json>`。
- `train`:`--days`、`--seed`、`--agents <list>`、`--dry-run`、`--fake-llm`、`--reflexive`、`--engine <name>`、`--swarm`、`--scorer <name>`、`--path-aware`、同样的 portfolio-stress fixture 参数、LLM 选项。
portfolio-stress 文件和 `--current-positions-json` 都可以是 JSON 持仓数组,也可以是包含 `current_positions`、`sector_exposure`、`theme_exposure` 的对象;显式 exposure 参数会覆盖文件或 inline fixture 值。每个持仓必须带正数 `market_price` 或 `current_price`。
`generate` 和非 dry-run `train` 会自动持久化供下一次 Daily Cycle 使用的情景 context;`train --dry-run` 不写 context 或训练记录。

## 回测

```bash
pnpm dev backtest --cohort cohort_default
```
选项:`--cohort`、`--prompt-commit-hash <hash>`、`--fake-llm`、LLM 选项、`--veto-threshold <num>`、`--initial-cash <amount>`、`--benchmark <ticker>`、`--force-refill`、`--log-every <n>`、`--out <path>`。另有 `backtest-fill` 做缓存填充阶段。
stage-1 carry-over 会用上一日 target weights 重建 `current_positions`,并记录 holding days、entry thesis id、realized/unrealized PnL、residual drift 和 closed-position exit reason。

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
pnpm dev daily-cycle --cohort cohort_default     # 28 agents / 29 stages → CIO 组合
# forward_return 回填:调用 scorecard.score_pending RPC(T+5 后成熟)
pnpm dev darwinian --cohort cohort_default
pnpm dev janus run
pnpm dev dashboard                               # 看一屏
```
`scorecard.score_pending` 回填目前是 RPC 而非 CLI 子命令;经桥调用(`BridgeApi.scorecardScorePending(cohort, today)`)。

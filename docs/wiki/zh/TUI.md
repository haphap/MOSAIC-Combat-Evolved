# TUI

`pnpm dev dashboard` 渲染一个 Ink(终端内 React)仪表盘,把现有只读 RPC 聚合到一屏,外加一个可编辑的设置页。组件:`mosaic-ts/src/tui/Dashboard.tsx`;命令:`mosaic-ts/src/cli/commands/dashboard.ts`。选项:`--cohort <name>`、`--user <name>`。

导航:**1–8** 切换标签,**r** 刷新(手动;无自动轮询),**q** 退出。在 Agents 标签中用 **j/↓**、**k/↑** 切换 Agent。`BridgeApi` 被注入,因此组件用 fake 做单测。

## 标签页

| 键 | 标签 | 展示 |
| --- | --- | --- |
| 1 | today | 最新 CIO 计划,含持仓审查计数、warning label、当前/目标/delta 权重、thesis 状态、风险标记和 dissent notes。 |
| 2 | winrate | 逐标的方向命中率(`win_rate`、`n`、平均 5 日方向收益)。 |
| 3 | skill | 逐 agent `mean_alpha_5d` / `sharpe_window` / `n_obs`。 |
| 4 | paper | 纸账户、当前持仓、target-current 执行 delta、最新提交/成交纸上交易和近期回测 carry-over 诊断。 |
| 5 | cohorts | 逐 cohort run 数 / 分支 / 最近运行日。 |
| 6 | mirofish | 最新 simulation-only 情景上下文、context hash/as-of 元数据、逐持仓压力和近期前向训练 run。 |
| 7 | settings | 可编辑、持久化的配置(见下)。 |
| 8 | agents | 每个逻辑 Agent 的人可读决策说明及 accepted-output 血缘状态。 |

## Agent 决策说明(键 8)

每次 live daily cycle 都从各 Agent 已接受的结构化输出中确定性生成精简说明,按角色展示结论、适用时的置信度/周期、驱动、风险、标的或组合动作以及证据结论。若某阶段因不存在评价对象而跳过,界面会明确说明,不会把它展示成中性判断。

说明文本作为独立持久化的 **UI-only sidecar**:它不是模型生成的思维链,不会形成第二条未经校验的事实通道,也不会进入下游 Agent 输入、accepted-output payload、Darwinian 评价或 KNOT 演化。`daily-cycle --out` 会附带该 sidecar 供人工审计,交易和评价消费者仍只读取结构化合同。

## 设置页(键 7)

常用配置的精选可编辑视图,经 `config.save` 持久化到 `~/.mosaic/config.json`。控制:**↑↓** 选择 · **enter** 编辑(字符串/数字)· **space** 切 bool / 循环枚举 · **s** 保存 · **esc** 取消。编辑态下该标签独占所有按键(故打 `q` 不会退出)。

可编辑字段:`llm_provider`、`deep_think_llm`、`quick_think_llm`、`output_language`、`active_cohort`;`autoresearch.*` 五个数值;`autoresearch.git.push` / `remote`;`mirofish.engine` / `scorer` / `inject_context`。

字段含义与持久化机制见[配置](Configuration.md)。

## 持仓感知审查

Dashboard 展示与 `daily-cycle` 同源的持仓循环:已加载/已审查持仓数、stale thesis 与 stop-loss override 计数、显式 warning label、target-current delta、逐 action fired caps、declared knob influence ids、决策 agent 审计摘要,以及 MiroFish 逐持仓压力。stale-thesis action 应带 `stale_thesis` risk flag 和明确复盘原因;stop-loss override 计数读取规范化后的 `stop_loss_breached` risk flag。CIO action 行也会校验 `position_decision` 语义,确保 `ADD`/`REDUCE`/`EXIT` 与 action、target/current/delta 权重一致。操作步骤和迁移检查见
[`docs/runbooks/position_aware_prompt_evolution.md`](../../runbooks/position_aware_prompt_evolution.md)。

回测诊断是 stage-1 cache 摘要:turnover proxy、observed holding-day proxy、stale-thesis proxy 和 action mix 来自缓存的 `backtest_actions`;alpha/drawdown opportunity 指标仍明确标记为需要 stage-2 scored positions。

MiroFish context 必须带非未来的 `as_of_date`。缺失该边界或日期晚于本次 run 的 context 会在 prompt injection 前被禁用。

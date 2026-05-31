# TUI

`pnpm dev dashboard` 渲染一个 Ink(终端内 React)仪表盘,把现有只读 RPC 聚合到一屏,外加一个可编辑的设置页。组件:`mosaic-ts/src/tui/Dashboard.tsx`;命令:`mosaic-ts/src/cli/commands/dashboard.ts`。选项:`--cohort <name>`、`--user <name>`。

导航:**1–7** 切换标签,**r** 刷新(手动;无自动轮询),**q** 退出。`BridgeApi` 被注入,因此组件用 fake 做单测。

## 标签页

| 键 | 标签 | 展示 |
| --- | --- | --- |
| 1 | today | 最新 CIO 计划 —— ticker / 方向 / 目标权重 % / 逻辑。 |
| 2 | winrate | 逐标的方向命中率(`win_rate`、`n`、平均 5 日方向收益)。 |
| 3 | skill | 逐 agent `mean_alpha_5d` / `sharpe_window` / `n_obs`。 |
| 4 | paper | 纸账户(现金 / 市值 / 总额 / 已实现 + 未实现盈亏)+ 持仓。 |
| 5 | cohorts | 逐 cohort run 数 / 分支 / 最近运行日。 |
| 6 | mirofish | 最新情景上下文(regime / 最高信念方向 / 尾部风险)+ 近期前向训练 run。 |
| 7 | settings | 可编辑、持久化的配置(见下)。 |

## 设置页(键 7)

常用配置的精选可编辑视图,经 `config.save` 持久化到 `~/.mosaic/config.json`。控制:**↑↓** 选择 · **enter** 编辑(字符串/数字)· **space** 切 bool / 循环枚举 · **s** 保存 · **esc** 取消。编辑态下该标签独占所有按键(故打 `q` 不会退出)。

可编辑字段:`llm_provider`、`deep_think_llm`、`quick_think_llm`、`output_language`、`active_cohort`;`autoresearch.*` 五个数值;`autoresearch.git.push` / `remote`;`mirofish.engine` / `scorer` / `inject_context`。

字段含义与持久化机制见[配置](Configuration.md)。

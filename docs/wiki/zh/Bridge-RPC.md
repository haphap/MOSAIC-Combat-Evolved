# 桥 RPC

TypeScript 前端经 stdio 上的行分隔 JSON-RPC 驱动 Python sidecar。方法由 `mosaic/bridge/handlers/*.py` 里的 `@method("namespace.verb")` 注册,从 `mosaic-ts/src/bridge/types.ts`(`BridgeApi`)调用。

错误信封映射为带数值码的 `RpcError`(`mosaic/bridge/protocol.py`):`PARSE_ERROR -32700`、`INVALID_PARAMS -32602`、`METHOD_NOT_FOUND -32601`、`INTERNAL_ERROR -32603`,以及域码 `CONFIG_ERROR -32010`、`PAPER_ERROR -32020`、`BACKTEST_ERROR -32030`、`SCORECARD_ERROR -32040`、`AUTORESEARCH_ERROR -32050`、`PRISM_ERROR -32060`、`JANUS_ERROR -32070`、`MIROFISH_ERROR -32080`、`DATA_ERROR -32090`。

## 完整方法面

### tools
- `tools.prepare_capability` —— 物化一个冻结且绑定角色的快照 bundle。
- `tools.issue_capability` —— 为已有 bundle 签发绑定执行阶段的 handle。
- `tools.list` —— 只列出签名 capability 授权的零参数快照。
- `tools.call` —— 返回一个不可变的授权快照；不会在调用时运行采集器。
- `tools.terminate_capability` —— 使用完毕后关闭阶段 capability。

`mosaic/bridge/handlers/tools.py` 有意保持 `_TOOL_MODULES=()`。通用宏观、ETF、财务、技术、新闻及研报 helper 均不注册到模型可见 RPC；原始采集器只能在 controller 的 capability 准备边界后运行。精确角色—快照矩阵见[智能体](Agents.md)。

### config
- `config.default` —— 深拷贝的 `DEFAULT_CONFIG`。
- `config.get` —— 本进程的活动运行时配置。
- `config.set` —— 替换活动配置(仅本进程)。
- `config.save` —— 持久化到 `~/.mosaic/config.json` 并应用(跨重启)。

### cache
- `cache.stats`、`cache.details`、`cache.cleanup`、`cache.clear`。

### calendar
- `calendar.list_trading_days`、`calendar.is_trading_day`、`calendar.next_trading_day`。

### scorecard
- `scorecard.append` —— 摄入一次 daily-cycle state 的 CIO 动作。
- `scorecard.score_pending` —— 回填已成熟的前向收益 + alpha。
- `scorecard.list_skill` —— 逐 agent 技能行。
- `scorecard.win_rate` —— 逐标的方向命中率。
- `scorecard.latest_cio_actions` —— cohort 的最新 CIO 组合。

### darwinian
- 生产 v2：`darwinian.prepare_variant`、
  `darwinian.prepare_daily_cycle_outcomes`、`darwinian.refresh_v2_windows` 和
  `darwinian.publish_v2_updates`；交易日历和评价机会分母输入由服务端持有。
- `darwinian.compute`、`darwinian.get_weights` 必须显式传入 `audit_only=true`，返回
  `legacy_unverified`，不得进入生产。

### prompts
- `prompts.read`(某 git ref 处的文件)、`prompts.write`(经 git_ops 在分支上提交)。

### autoresearch
- `autoresearch.trigger`、`autoresearch.evaluate_pending`、`autoresearch.record_mutation`、
  `autoresearch.revert_modification`、`autoresearch.get_log`、`autoresearch.list_active_branches`、
  `autoresearch.prepare_worktree`、`autoresearch.cleanup_worktree`。

### prism
- `prism.list_cohorts`、`prism.train_cohort`、`prism.cohort_status`、`prism.complete_cohort_run`、`prism.compare_cohorts`。

### janus
- `janus.run_daily`、`janus.get_weights`、`janus.regime`、`janus.get_history`。

### mirofish
- `mirofish.generate_scenarios`、`mirofish.score_recommendation`、`mirofish.record_run`、
  `mirofish.get_history`、`mirofish.save_context`、`mirofish.get_context`。

### backtest
- `backtest.create_run`、`backtest.append_actions`、`backtest.complete_run`、
  `backtest.get_run`、`backtest.list_runs`、`backtest.run_historical`。
- (旧的 backtrader `run_candidate_pool` 路径已移除;回测纯 qlib。)
- `backtest.run_historical` 接受可选 `results_dir`:设置后该 run 额外导出 ATLAS 同构产物(`summary.json` / `portfolio_trajectory.csv` / `equity_curve.png`,经 `mosaic/backtest/results_export.py`)。matplotlib 可选 —— 缺则跳过 PNG。

### paper
- `paper.register`、`paper.login`、`paper.logout`、`paper.current_user`、
  `paper.get_account`、`paper.reset_account`、`paper.buy`、`paper.sell`、
  `paper.get_positions`、`paper.get_trades`、`paper.suggest_order_from_signal`。

### data
- `data.incremental` —— 向 cn_data/cn_etf 追加最新交易日(kind=stock|etf)。
- `data.validate` —— ingest 数据集的质量报告 + skip 清单。

## 新增 handler

1. 建 `mosaic/bridge/handlers/<name>.py`,写 `@method("<name>.verb")` 函数(先校验参数,抛 `RpcError`)。
2. 在 `mosaic/bridge/handlers/__init__.py` 导入它(导入副作用即注册方法)。
3. 在 `mosaic-ts/src/bridge/types.ts`(`BridgeApi`)加类型化封装。

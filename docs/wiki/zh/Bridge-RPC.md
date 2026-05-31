# 桥 RPC

TypeScript 前端经 stdio 上的行分隔 JSON-RPC 驱动 Python sidecar。方法由 `mosaic/bridge/handlers/*.py` 里的 `@method("namespace.verb")` 注册,从 `mosaic-ts/src/bridge/types.ts`(`BridgeApi`)调用。

错误信封映射为带数值码的 `RpcError`(`mosaic/bridge/protocol.py`):`PARSE_ERROR -32700`、`INVALID_PARAMS -32602`、`METHOD_NOT_FOUND -32601`、`INTERNAL_ERROR -32603`,以及域码 `CONFIG_ERROR -32010`、`PAPER_ERROR -32020`、`BACKTEST_ERROR -32030`、`SCORECARD_ERROR -32040`、`AUTORESEARCH_ERROR -32050`、`PRISM_ERROR -32060`、`JANUS_ERROR -32070`、`MIROFISH_ERROR -32080`、`DATA_ERROR -32090`。

## 完整方法面

### tools
- `tools.list` —— 列出已注册的 sidecar 工具。
- `tools.call` —— 按名 + 参数调用工具。

已注册工具模块(`mosaic/bridge/handlers/tools.py` `_TOOL_MODULES`):`macro_tools`(8 个 Layer-1 宏观工具)与 `research_report_tools`(`get_broker_research` = 行业研报,`get_stock_research` = 个股研报)。哪些 agent 用哪些工具见[智能体](Agents.md)。

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
- `darwinian.compute`、`darwinian.get_weights`。

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

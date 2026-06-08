# RKE 个股研报评价与演化闭环计划

## 背景

当前 Report Intelligence 已经把行业研报接入 `industry_etf_proxy`：LLM 只抽取行业观点和方向，系统用行业 ETF 的 PIT 价格窗口生成非 LLM outcome label。

现存缺口是个股研报尚未进入同等评价通道。抽取 prompt 已经要求在 `metadata.ts_code` 支持时将个股观点抽成 `target_type=stock`，但派生刷新阶段没有把 `stock` target 接到 qlib `cn_data` 股票价格窗口，因此个股研报不能形成可审计的市场反馈。

第二个缺口是后续 prompt/agent 演化尚未真正开始。演化不能依赖 LLM 自评，应由 PIT outcome、人工 gold-set、schema/audit、工具覆盖缺口共同驱动。

## 原则

1. LLM 只负责抽取 source-grounded 的观点、方向、目标、目标价、方法和指标，不判断研报对错。
2. 个股和行业评价都必须使用 point-in-time 可得数据。
3. outcome label 保持 shadow-only，不直接进入生产交易决策。
4. 多窗口 evidence 不折叠成单一结论，允许“短期错、长期对”。
5. 任何无法确定股票映射、入场日、退出日或价格的数据都进入 readiness gap，不补造标签。

## P0：个股评价数据契约

新增 `--qlib-stock-dir` 配置，默认指向 `~/.qlib/qlib_data/cn_data`。

个股 claim 可评价条件：

- `target.target_type == "stock"`。
- `target.target_id` 是标准 `ts_code`，如 `000001.SZ`、`600000.SH`、`920xxx.BJ`。
- `direction` 是 `positive` 或 `negative`。
- `signal_datetime` 有效。
- qlib `cn_data` 存在该股票的 `adjclose.day.bin` 和交易日历。

目标解析优先级：

1. LLM 抽取出的 `target.target_id`。
2. Tushare 研报元数据里的 `ts_code`。
3. 标题/正文公司名映射暂不自动强推，先记为 `stock_target_mapping_missing`。

## P1：stock proxy outcome labeler

新增两组 builder：

- `build_stock_price_proxy_readiness()`
- `build_stock_price_proxy_outcome_labels()`

评价方式：

- 使用 qlib `cn_data` 的复权收盘价。
- 报告发布日期后的第一个交易日作为 T+1 入场日。
- 禁止使用报告当日收盘作为入场。
- 固定窗口建议为 `5/20/60/120` 个交易日。
- 每个窗口输出一条独立 outcome evidence。
- 标签来源固定为 `pit_stock_price_window`。
- `llm_outcome_labeling_allowed=false`。

## P2：个股研报评分逻辑

每个窗口记录：

- `stock_return`
- `benchmark_return`
- `relative_alpha = stock_return - benchmark_return`
- `after_cost_alpha = relative_alpha - round_trip_cost`
- `directional_after_cost_return`
- `directional_hit`
- `relative_directional_hit`

看多时，正收益或正 alpha 是支持证据；看空时方向相反。

如果原文抽到 source-grounded 目标价，则增加 `target_price_hit`，但不替代窗口 evidence。目标价命中只作为补充证据，因为很多研报只给评级、排序或相对强弱判断。

主 profile 指标建议双轨保留：

- `directional_after_cost_return`：判断方向性观点是否有效。
- `after_cost_alpha`：判断相对市场是否有增量。

## P3：artifact、schema 和 audit 扩展

`report_outcome_labels.jsonl` 增加：

- `label_type=stock_price_proxy`
- `proxy_symbol`
- `benchmark_symbol`
- `entry_datetime`
- `exit_datetime`
- `entry_lag_trading_days`
- `horizon_days`
- `stock_return`
- `benchmark_return`
- `relative_alpha`
- `after_cost_alpha`
- `target_resolution_source`

`outcome_labeling_readiness.json` 增加 `stock_price_proxy_readiness`。

PIT audit 增加 stock 标签检查：

- 拒绝 T+0 入场。
- 拒绝 exit 超过 qlib 最新交易日。
- entry/exit 价格缺失必须阻断。
- benchmark 缺失必须进入 readiness gap。

provenance audit 明确：LLM 输出只可作为抽取证据，市场数据负责 outcome label。

## P4：测试计划

构造 qlib stock fixture：

- 一只上涨股。
- 一只下跌股。
- 一个 benchmark。
- 一个价格缺失样本。

覆盖测试：

- 个股看多命中。
- 个股看空命中。
- 短期错、长期对必须保留。
- qlib 缺价格时进入 readiness gap。
- PIT audit 拒绝 T+0。
- `refresh-derived-only` 不在缺私有输入时覆盖公开 artifact。

最小验证：

```bash
uv run python -m pytest tests/test_rke_report_intelligence.py -q --basetemp /tmp/pytest-rke-ri
uvx ruff@0.15.15 check mosaic tests
```

## P5：演化闭环

演化输入：

- 行业 ETF proxy outcome。
- 个股 stock proxy outcome。
- 人工 gold-set review。
- schema/audit 失败。
- 工具覆盖缺口。
- runtime shadow 观察。

演化输出：

- prompt mutation candidates。
- target mapping 规则补强。
- horizon 规则补强。
- 指标和方法抽取规则补强。
- tool gap 和 data acquisition proposal。
- analysis recipe 更新候选。

演化不直接修改生产 prompt。推荐流程：

1. 生成 candidate。
2. 用 gold-set 和 PIT outcome 做离线评估。
3. 通过 schema、PIT、provenance、statistical robustness audit。
4. 进入 shadow recipe/profile。
5. promotion gate 和 lockbox 通过前不进入生产。

## P6：讨论决策点

待确认事项：

- 个股 benchmark 使用 qlib 指数还是 ETF 替代，建议优先 `CSI300`，缺数据时再讨论 fallback。
- 个股 round-trip cost，建议先用 20 bps。
- 个股窗口是否固定为 `5/20/60/120`。
- 目标价命中是否作为辅助字段，而不是主标签。
- 公司名到 ts_code 的自动映射是否先不上线，只记录 gap。

建议下一步先实现 P0 到 P2，让个股研报拥有与行业研报同等级别的 PIT outcome label。等行业和个股两类 outcome 都稳定后，再进入 P5 的 prompt/agent 演化闭环。

## P7：实施拆解

### P7.1 qlib `cn_data` 预检查

实施前先确认本机 qlib 股票数据布局：

- `~/.qlib/qlib_data/cn_data/calendars/day.txt`
- `~/.qlib/qlib_data/cn_data/features/sh600000/adjclose.day.bin`
- `~/.qlib/qlib_data/cn_data/features/sz000001/adjclose.day.bin`
- 北交所 920 代码是否使用 `bj920xxx` 或其他 qlib symbol 规则。

需要明确 benchmark 可用性：

- 如果 qlib `cn_data` 有指数数据，优先使用 `SH000300` 或等价 CSI300。
- 如果指数不在 `cn_data`，短期用 ETF benchmark，例如 `SH510300`，但必须在 label 中标明 `benchmark_source=etf_fallback`。
- benchmark 缺失时不生成 stock outcome label，只进入 readiness gap。

### P7.2 配置和 CLI

代码改动：

- 在 `ReportIntelligenceConfig` 增加 `qlib_stock_dir`。
- 在 `mosaic-rke report-intelligence` 增加 `--qlib-stock-dir`。
- 默认值为 `~/.qlib/qlib_data/cn_data`。
- `--refresh-derived-only` 同样使用该配置。

验收：

- CLI help 能看到 `--qlib-stock-dir`。
- 不传参数时默认不会访问 `/home/hap`。
- 显式传临时 fixture 目录时测试可控。

### P7.3 qlib 工具函数泛化

当前 ETF 逻辑已有：

- `_qlib_symbol()`
- `_read_trading_calendar()`
- `_read_qlib_series()`
- `_series_value_at_calendar_index()`
- `_entry_calendar_index()`

实施时优先复用，不新造一套读 bin 的逻辑。只新增必要的 stock 解析：

- `_resolve_qlib_data_dir()`
- `_stock_target_symbol()`
- `_is_stock_forecast_claim()`
- `_stock_benchmark_symbol()`

注意：

- `ts_code` 标准形态是 `000001.SZ`，qlib feature 目录通常是 `sz000001`。
- 北交所只接受 `920` 开头普通股票，不主动扩展老 `8` 开头代码。
- 不做公司名模糊匹配，避免把同名或简称误映射成错误股票。

### P7.4 readiness builder

新增 `build_stock_price_proxy_readiness()`。

输入：

- `forecast_rows`
- `metadata_rows`
- `qlib_stock_dir`
- `benchmark_symbol`
- `windows_days`

输出写入 `outcome_labeling_readiness.json` 的 `stock_price_proxy_readiness`：

- `policy`
- `outcome_label_source`
- `llm_outcome_labeling_allowed`
- `windows_days`
- `entry_lag_trading_days`
- `benchmark_symbol`
- `qlib_stock_dir_configured`
- `latest_calendar_date`
- `eligible_claim_count`
- `eligible_forecast_claim_ids`
- `labelable_forecast_claim_count`
- `labelable_forecast_claim_ids`
- `labelable_window_count`
- `pending_future_window_count`
- `data_gap_counts`

主要 gap：

- `stock_target_missing`
- `stock_target_mapping_missing`
- `stock_series_missing`
- `calendar_missing`
- `benchmark_series_missing`
- `entry_date_after_latest_calendar`
- `entry_price_missing`
- `exit_price_missing`
- `direction_missing_or_unsupported`

### P7.5 outcome label builder

新增 `build_stock_price_proxy_outcome_labels()`。

输出 label 必须包含：

- `label_type=stock_price_proxy`
- `outcome_label_source=pit_stock_price_window`
- `llm_outcome_labeling_allowed=false`
- `proxy_symbol`
- `benchmark_symbol`
- `entry_datetime`
- `exit_datetime`
- `entry_lag_trading_days=1`
- `horizon_days`
- `stock_return`
- `benchmark_return`
- `relative_alpha`
- `round_trip_cost`
- `after_cost_alpha`
- `directional_after_cost_return`
- `directional_hit`
- `relative_directional_hit`
- `source_horizon_days`
- `source_horizon_bucket`
- `claim_window_alignment`
- `evaluation_policy`
- `target_resolution_source`

推荐固定值：

- `STOCK_PRICE_PROXY_WINDOWS_DAYS = (5, 20, 60, 120)`
- `STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS = 1`
- `STOCK_PRICE_PROXY_ROUND_TRIP_COST = 0.002`
- `STOCK_PRICE_PROXY_OUTCOME_LABEL_SOURCE = "pit_stock_price_window"`
- `evaluation_policy = "stock_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"`

### P7.6 合并到 derived refresh

当前 derived refresh 流程是：

1. `build_report_forecast_ledger()`
2. `build_outcome_label_records()`
3. `build_industry_etf_proxy_readiness()`
4. `build_outcome_labeling_readiness_report()`
5. performance/profile/audit/coverage

调整为：

1. 先生成 industry readiness。
2. 再生成 stock readiness。
3. `build_outcome_label_records()` 合并 industry labels 和 stock labels。
4. `build_outcome_labeling_readiness_report()` 同时接收两类 readiness。
5. performance profile 继续按统一 outcome label rows 聚合。

readiness 计数逻辑要区分：

- `standard_ready`
- `industry_proxy_ready`
- `stock_proxy_ready`
- `blocked`

其中 industry/stock proxy ready 都不等于 standard label ready，但它们都能作为 governed proxy evidence 进入 shadow profile。

### P7.7 audit 扩展

PIT audit：

- stock outcome label 也必须验证 T+1。
- `entry_datetime` 必须晚于 `signal_datetime` 的交易日。
- `exit_datetime` 必须不晚于 qlib 最新 calendar。
- `entry_lag_trading_days < 1` 直接失败。

statistical robustness audit：

- `stock_price_proxy` 计入 outcome label source 分布。
- 多窗口权重不能让同一个 claim 的 evidence 权重超过 1。
- stock 和 industry 的 window set 都保留长周期 evidence。

extraction provenance audit：

- stock label 必须能追溯到 forecast claim。
- forecast claim 必须有 source span。
- `target_resolution_source=metadata_ts_code` 时，metadata `ts_code` 必须存在。

### P7.8 schema 更新

需要更新：

- `schemas/report_intelligence_report_outcome_label.schema.json`
- `schemas/report_intelligence_outcome_labeling_readiness.schema.json`
- 可能涉及 coverage/audit schema 的 enum 或 required 字段。

约束：

- 不把 `claim_text`、`source_span_ids` 或原文片段加入公开输出。
- 私有输出仍由 `PRIVATE_LOCAL_REGISTRY_FILES` 和 `REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS` 保护。

### P7.9 测试优先级

第一批测试只覆盖核心闭环：

1. `test_report_intelligence_labels_stock_claims_with_qlib_price_windows`
2. `test_report_intelligence_counts_stock_price_proxy_as_labelable_channel`
3. `test_report_intelligence_keeps_long_window_stock_hits`
4. `test_report_intelligence_labels_bearish_stock_claims`
5. `test_report_intelligence_pit_audit_rejects_t0_stock_entry`
6. `test_report_intelligence_stock_readiness_records_price_gaps`

第二批再扩展：

1. benchmark fallback。
2. 北交所 920 code symbol 规则。
3. 目标价命中辅助字段。
4. schema status 全量验证。

### P7.10 首轮不做的事

为控制风险，首轮明确不做：

- 公司名到 `ts_code` 的模糊匹配。
- LLM 判断研报是否正确。
- 把 stock outcome 推进生产交易。
- 用目标价命中替代价格窗口。
- 自动改 prompt 或 private prompt repo。

## P8：验收矩阵

最小本地验收：

```bash
uv run python -m pytest tests/test_rke_report_intelligence.py -q --basetemp /tmp/pytest-rke-ri
uv run python -m pytest tests/test_rke_schema_artifacts.py -q --basetemp /tmp/pytest-rke-schema
uvx ruff@0.15.15 check mosaic tests
git diff --check
```

功能验收：

- 个股看多/看空都能产生 `stock_price_proxy` label。
- 每个 claim 至少可产生 `5/20/60/120` 中可得窗口。
- 短期 miss、长期 hit 不被折叠。
- qlib 缺数据时只进入 readiness gap。
- PIT audit 拒绝 T+0。
- performance profile 能同时接收 industry 和 stock labels。

隐私验收：

```bash
git check-ignore registry/report_intelligence/forecast_claims.jsonl
git check-ignore registry/report_intelligence/report_outcome_labels.jsonl
git rev-list --objects origin/main HEAD | rg 'tushare_research_reports|report_intelligence/markdown|report_intelligence/pdfs' || true
```

讨论验收：

- benchmark 口径确定。
- round-trip cost 确定。
- 北交所 920 code qlib symbol 规则确认。
- 是否允许 ETF fallback benchmark 确认。

## P9：建议执行顺序

建议用两个 PR 或两个 commit 分离：

1. **Stock label core**：配置、builder、schema、tests、audit。
2. **Evolution loop preparation**：把 stock/industry outcome 反馈接入 prompt mutation candidate 和 tool-gap prioritization。

第一个改动完成后，先用 synthetic fixture 跑通，再用少量真实私有研报和 qlib `cn_data` 做 shadow dry-run。第二个改动必须等 outcome rows 足够稳定后再开始。

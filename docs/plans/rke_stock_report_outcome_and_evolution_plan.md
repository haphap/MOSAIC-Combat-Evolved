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
6. 个股评价必须显式处理停牌、涨跌停不可交易、退市和 qlib survivorship bias；首轮可以作为 readiness gap，但不能隐式当作可交易价格。

## P0：个股评价数据契约

新增 `--qlib-stock-dir` 配置，默认指向 `~/.qlib/qlib_data/cn_data`。

个股 claim 可评价条件：

- `target.target_type == "stock"`。
- `target.target_id` 是标准 `ts_code`，如 `000001.SZ`、`600000.SH`、`920xxx.BJ`。
- `direction` 是 `positive` 或 `negative`。
- `signal_datetime` 有效。
- qlib `cn_data` 存在该股票的 `adjclose.day.bin` 和交易日历。

目标解析优先级：

1. 如果 LLM `target.target_id` 和 Tushare 元数据 `ts_code` 都存在且一致，使用该 `ts_code`。
2. 如果元数据 `ts_code` 存在，且原文支持该公司投资观点，使用元数据 `ts_code`。
3. 如果元数据缺失，但 LLM 抽取出格式有效且 source-grounded 的 `ts_code`，使用 LLM `target.target_id`。
4. 如果 LLM `target.target_id` 和元数据 `ts_code` 都存在但不一致，记为 `stock_target_conflict` gap，不生成 label。
5. 标题/正文公司名映射暂不自动强推，先记为 `stock_target_mapping_missing`。

## P1：stock proxy outcome labeler

新增两组 builder：

- `build_stock_price_proxy_readiness()`
- `build_stock_price_proxy_outcome_labels()`

评价方式：

- 使用 qlib `cn_data` 的复权收盘价。
- 报告发布日期后的第一个交易日作为 T+1 入场日。
- 禁止使用报告当日收盘作为入场。
- 入场日停牌、可检测的涨停锁死不可买入、退市前无法完成退出窗口时不生成 label，只记录 readiness gap。
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

- benchmark 口径建议先统一使用 `SH510300` ETF，与行业 ETF proxy 保持同一 CSI300 proxy；`SH000300` 指数只作为后续单独 profile 或 feature flag，不混入默认统一 profile。
- 个股 round-trip cost，建议先用 20 bps；行业 ETF 维持 10 bps，但 profile 必须记录 `cost_model_id` 和 `label_type`，不能把不同成本口径当作同质样本。
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

- 默认 benchmark 使用 `SH510300` ETF，与现有行业 ETF proxy 一致。
- `SH510300` 来自 `cn_etf` 时，benchmark 必须用自己的 calendar 和 series 按日期对齐，不能复用 stock `cn_data` 的整数 calendar index。
- 如果后续启用 `SH000300` 指数 benchmark，必须设置 `benchmark_source=index`，并在 performance profile 中按 `benchmark_family` 或 `benchmark_source` 分组，避免和 ETF benchmark 的 `relative_alpha` 直接混算。
- benchmark 缺失时不生成 stock outcome label，只进入 readiness gap。

个股 PIT-realism 预检查：

- 检查 qlib 是否有 `volume`、`open`、`high`、`low`、`close` 字段；如果只有 `adjclose`，只能做价格窗口，不能宣称 entry tradability 已验证。
- 入场日价格缺失、成交量为 0 或可识别停牌时，记录 `stock_entry_suspended`。
- 窗口内连续缺价或成交量为 0 超过阈值时，记录 `stock_long_suspension_window`。
- 退出日前股票缺失或退市，记录 `stock_delisted_before_exit`。
- 可检测的涨停不可买入或跌停不可卖出，记录 `entry_limit_locked` 或 `exit_limit_locked`；首轮无法精确识别涨跌停制度时，记录 `entry_liquidity_unverified`。
- 不允许 hardcode `survivorship_safe=true`；若 qlib 股票 universe 可能缺退市股票，必须在 readiness 或 monitoring 中记录 `survivorship_unverified`。

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
- `_series_value_at_date()`
- `_entry_calendar_date()`
- `_exit_calendar_date()`

注意：

- `ts_code` 标准形态是 `000001.SZ`，qlib feature 目录通常是 `sz000001`。
- 北交所只接受 `920` 开头普通股票，不主动扩展老 `8` 开头代码。
- 不做公司名模糊匹配，避免把同名或简称误映射成错误股票。
- 如果 stock 和 benchmark 来自不同 qlib 目录，stock 入场/退出日期由 stock calendar 决定，benchmark 价格按相同日期查找；禁止用 stock calendar index 直接索引 benchmark series。

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
- `stock_target_conflict`
- `stock_series_missing`
- `calendar_missing`
- `benchmark_series_missing`
- `entry_date_after_latest_calendar`
- `entry_price_missing`
- `exit_price_missing`
- `stock_entry_suspended`
- `stock_long_suspension_window`
- `stock_delisted_before_exit`
- `entry_limit_locked`
- `exit_limit_locked`
- `entry_liquidity_unverified`
- `survivorship_unverified`
- `direction_missing_or_unsupported`

### P7.5 outcome label builder

新增 `build_stock_price_proxy_outcome_labels()`。

输出 label 必须包含：

- `label_type=stock_price_proxy`
- `outcome_label_source=pit_stock_price_window`
- `llm_outcome_labeling_allowed=false`
- `proxy_symbol`
- `benchmark_symbol`
- `benchmark_source`
- `benchmark_family`
- `cost_model_id`
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
- `STOCK_PRICE_PROXY_BENCHMARK_SYMBOL = "SH510300"`
- `STOCK_PRICE_PROXY_BENCHMARK_SOURCE = "cn_etf"`
- `STOCK_PRICE_PROXY_COST_MODEL_ID = "single_stock_round_trip_20bps_v1"`
- `evaluation_policy = "stock_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"`

成本语义：

- `round_trip_cost` 表示完整买入到退出窗口的一次往返成本，在 `relative_alpha - round_trip_cost` 中只扣一次。
- 行业 ETF 10 bps 和个股 20 bps 都是真实交易摩擦假设，但 profile 聚合必须保留 `label_type`、`cost_model_id` 和 `benchmark_family`，避免误把不同成本模型解释为同一类 alpha。

ID 语义：

- `outcome_id`、`claim_window_set_id`、`overlap_group_id` 必须包含 `label_type`，防止同一 claim 在 industry 和 stock 两条 proxy path 下发生 ID 碰撞。

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
5. performance profile 继续读统一 outcome label rows，但默认按 `label_type`、`benchmark_family` 和 `cost_model_id` 分层聚合；跨层总体指标只能作为摘要，不能替代分层 profile。

readiness 计数逻辑要区分：

- `standard_ready`
- `industry_proxy_ready`
- `stock_proxy_ready`
- `blocked`

其中 industry/stock proxy ready 都不等于 standard label ready，但它们都能作为 governed proxy evidence 进入 shadow profile。

窗口权重：

- industry 的 `20/60/120` 和 stock 的 `5/20/60/120` 分别在各自 channel 内满足 per-claim evidence weight <= 1。
- 跨 channel 不合并 effective weight；同一 claim 如果极端情况下同时命中 industry 和 stock path，profile 必须按 channel 分开计权。

### P7.7 audit 扩展

PIT audit：

- stock outcome label 也必须验证 T+1。
- `entry_datetime` 必须晚于 `signal_datetime` 的交易日。
- `exit_datetime` 必须不晚于 qlib 最新 calendar。
- `entry_lag_trading_days < 1` 直接失败。
- stock benchmark 来自不同 qlib dir 时，audit 必须验证 benchmark entry/exit 是按日期对齐，不是按 stock calendar index 对齐。
- 发现 `stock_entry_suspended`、`entry_limit_locked`、`stock_delisted_before_exit` 仍生成 label 时直接失败。

statistical robustness audit：

- `stock_price_proxy` 计入 outcome label source 分布。
- 多窗口权重不能让同一个 claim 的 evidence 权重超过 1。
- stock 和 industry 的 window set 都保留长周期 evidence。
- 跨 `label_type`、`benchmark_family`、`cost_model_id` 的合并统计必须同时输出分层样本数，避免异质 benchmark/cost 混算。

extraction provenance audit：

- stock label 必须能追溯到 forecast claim。
- forecast claim 必须有 source span。
- `target_resolution_source=metadata_ts_code` 时，metadata `ts_code` 必须存在。
- `target_resolution_source=llm_target_id` 时必须格式有效且 source-grounded；若 metadata `ts_code` 存在且不一致，必须进入 `stock_target_conflict` gap。

### P7.8 schema 更新

需要更新：

- `schemas/report_intelligence_report_outcome_label.schema.json`
- `schemas/report_intelligence_outcome_labeling_readiness.schema.json`
- 可能涉及 coverage/audit schema 的 enum 或 required 字段。

约束：

- 不把 `claim_text`、`source_span_ids` 或原文片段加入公开输出。
- 私有输出仍由 `PRIVATE_LOCAL_REGISTRY_FILES` 和 `REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS` 保护。
- 当前 schema validator 已支持 `minimum`、`maximum`、`exclusiveMinimum`、`exclusiveMaximum`、`maxItems`、`maxLength` 等约束，但 hard invariants 仍要在 PIT/provenance/statistical audit 中重复验证。
- 新增数值字段应同时有 schema 约束和 audit 约束，例如 `entry_lag_trading_days >= 1`、`round_trip_cost >= 0`、窗口权重不超过 1。

### P7.9 测试优先级

第一批测试只覆盖核心闭环：

1. `test_report_intelligence_labels_stock_claims_with_qlib_price_windows`
2. `test_report_intelligence_counts_stock_price_proxy_as_labelable_channel`
3. `test_report_intelligence_keeps_long_window_stock_hits`
4. `test_report_intelligence_labels_bearish_stock_claims`
5. `test_report_intelligence_pit_audit_rejects_t0_stock_entry`
6. `test_report_intelligence_stock_readiness_records_price_gaps`
7. `test_report_intelligence_stock_target_conflict_blocks_labeling`
8. `test_report_intelligence_stock_benchmark_aligns_by_date_across_qlib_dirs`
9. `test_report_intelligence_stock_entry_suspension_blocks_labeling`

第二批再扩展：

1. benchmark fallback。
2. 北交所 920 code symbol 规则。
3. 目标价命中辅助字段。
4. schema status 全量验证。
5. 涨跌停可交易性识别。
6. 退市或 survivorship bias 监控。

### P7.10 首轮不做的事

为控制风险，首轮明确不做：

- 公司名到 `ts_code` 的模糊匹配。
- LLM 判断研报是否正确。
- 把 stock outcome 推进生产交易。
- 用目标价命中替代价格窗口。
- 自动改 prompt 或 private prompt repo。
- 复杂涨跌停制度的完全精确成交模拟；首轮只做可检测 gap 和显式 limitation。

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
- 停牌、可检测涨跌停锁死、退市、target conflict 都只进入 readiness gap，不生成 label。
- stock benchmark 即使来自 `cn_etf`，也按日期对齐，不能按 stock calendar index 对齐。
- PIT audit 拒绝 T+0。
- performance profile 能同时接收 industry 和 stock labels，并按 `label_type`、`benchmark_family`、`cost_model_id` 分层输出。

隐私验收：

```bash
git check-ignore registry/report_intelligence/forecast_claims.jsonl
git check-ignore registry/report_intelligence/report_outcome_labels.jsonl
git rev-list --objects origin/main..HEAD | rg 'tushare_research_reports|report_intelligence/markdown|report_intelligence/pdfs' || true
```

讨论验收：

- benchmark 口径确定。
- round-trip cost 确定。
- 北交所 920 code qlib symbol 规则确认。
- 是否允许 ETF fallback benchmark 确认。
- 停牌入场是 roll 到下一可交易日还是直接 gap；首轮建议直接 gap。
- 涨跌停可交易性无法精确识别时，是否接受 `entry_liquidity_unverified` gap。

## P9：PDF 原文到 Markdown 覆盖率扩展

目标是把 Report Intelligence 从少量样本扩展到更稳定的真实研报样本池，但仍然保持私有原文、PDF、Markdown 和 source text 不进入 git。

### P9.1 样本扩展策略

真实样本选择必须分层，而不是只按最新研报顺序抽样：

- report_type：目标覆盖行业、公司、策略、宏观、固收、金融工程；其中 Tushare
  `research_report` 首轮只查询官方支持的 `个股研报` 和 `行业研报`，策略/宏观/固收/
  金融工程必须记录为 source gap，等接入其他合规来源后再计入覆盖。
- 时间：近 1 年、近 3 年、长周期历史样本。
- 机构：头部机构和长尾机构都要覆盖，避免 source profile 只学习头部风格。
- 行业：优先覆盖已有 ETF proxy 映射行业，再覆盖 mapping gap 行业。
- 个股：优先覆盖 `ts_code` 明确的公司研报。
- horizon：短期、中期、长期观点都要覆盖。
- 结果可评价性：优先选择 qlib 价格数据可用的报告，但保留一定 mapping gap 样本用于抽取和映射改进。

可执行抓取入口：

```bash
mosaic-rke fetch-tushare-reports \
  --root . \
  --start-date <YYYY-MM-DD> \
  --end-date <YYYY-MM-DD> \
  --p9-profile \
  --max-reports-per-query 6000
```

`--p9-profile` 会把 P9 的 Tushare 可查询 report_type 加入私有 source 查询集，并在
`registry/sources/tushare_research_reports.manifest.json` 记录 profile、覆盖阈值、
隐私边界和 `source_gaps`。随后用
`mosaic-rke report-intelligence --selection-order stratified` 从私有 source pool
中执行 Markdown/LLM 抽样。

首轮建议规模：

- PDF/Markdown 准备：不少于 300 篇真实研报。
- LLM extraction：先从其中抽取 100 篇，确认质量后再扩大。
- 行业研报：不少于 80 篇。
- 个股研报：不少于 80 篇。
- 每个高频行业至少 5 篇，低频行业先记录 coverage gap。

### P9.2 MinerU 转换流程

默认使用 `hybrid-auto-engine`，复杂图表或 OCR 质量不足时切到 `vlm-auto-engine`。

处理策略：

- 使用 batch conversion，控制 `mineru_batch_size` 和 `mineru_batch_max_bytes`。
- 每篇报告记录 conversion status、backend、bytes、sha256、耗时、stderr/stdout 脱敏尾部。
- 对 `mineru_timeout`、`mineru_markdown_not_found`、`mineru_failed` 做 retry queue。
- PDF 缺失、下载失败和 license review 未通过的样本不得进入 Markdown extraction。
- Markdown 存储仍在私有 cache 或 private registry 路径，不提交。

质量 gate：

- Markdown 非空且达到最小字节阈值。
- title/section/table markers 至少命中一个结构化信号。
- 乱码比例、重复页眉页脚比例、空表格比例低于阈值。
- 过短、纯目录、纯免责声明或图片未识别的 Markdown 进入 `markdown_quality_gap`。
- 同一 PDF 多次转换结果不一致时记录 `markdown_conversion_instability`。

### P9.3 覆盖率 artifact

私有 artifact：

- `registry/report_intelligence/processing_status.jsonl`
- `registry/report_intelligence/report_metadata.jsonl`
- `registry/report_intelligence/markdown/`
- `registry/report_intelligence/mineru/`

可提交的公开 artifact 只能是聚合报告，不包含 source prose、title、abstract、PDF URL、Markdown path 或 source-specific metadata。建议新增或扩展：

- `registry/report_intelligence/markdown_coverage_summary.json`

字段建议：

- `selected_report_count`
- `pdf_download_ready_count`
- `markdown_ready_count`
- `markdown_quality_pass_count`
- `markdown_quality_gap_counts`
- `report_type_counts`
- `sector_bucket_counts`
- `conversion_backend_counts`
- `retry_queue_count`
- `private_artifact_redaction_policy`

### P9.4 验收标准

- 真实 Markdown ready 样本数达到首轮阈值。
- Markdown coverage summary 不含原文、标题、摘要、URL、source span、PDF/Markdown 本地路径。
- `scripts/check_prompt_leaks.py` 和 privacy guard 通过。
- `refresh-derived-only` 在缺私有输入时仍不会覆盖公开派生 artifact。
- LLM extraction 只对 quality gate 通过的 Markdown 运行。

## P10：行业 ETF proxy 映射和 PIT 可用性

目标是把当前代码内 `INDUSTRY_ETF_PROXY_MAPPING` 扩展成可审计、可测试、可覆盖 gap 的行业映射 registry，并记录每个映射在 PIT 价格数据上的可用性。

### P10.1 映射表治理

建议将行业 ETF 映射从纯代码常量推进到 registry artifact，代码仍可加载默认 fallback：

- `registry/report_intelligence/industry_etf_proxy_map.jsonl`
- `schemas/report_intelligence_industry_etf_proxy_map.schema.json`

每条映射字段：

- `mapping_id`
- `sector_name`
- `sector_aliases`
- `taxonomy`
- `etf_symbol`
- `etf_name`
- `benchmark_symbol`
- `benchmark_source`
- `mapping_confidence`
- `mapping_rationale`
- `effective_from`
- `effective_to`
- `status`
- `review_required`

映射原则：

- 优先一行业一主 ETF，避免同一行业多 ETF 造成后验挑选。
- 多 ETF 可作为候选，但默认 labeler 只用 `status=primary` 的 mapping。
- 映射调整必须留下版本和 rationale。
- 没有高质量 ETF proxy 的行业必须保留 `sector_etf_mapping_missing`，不能强行映射。

### P10.2 PIT 可用性记录

新增聚合 artifact：

- `registry/report_intelligence/industry_etf_proxy_pit_availability.json`

每个 mapping 记录：

- `etf_symbol`
- `benchmark_symbol`
- `calendar_source`
- `earliest_price_date`
- `latest_price_date`
- `latest_calendar_date`
- `has_20d_window`
- `has_60d_window`
- `has_120d_window`
- `available_window_days`
- `missing_price_count`
- `stale_price_gap_count`
- `benchmark_available`
- `pit_available`
- `pit_gap_reasons`

对于历史报告，还要记录 labelability summary：

- `eligible_claim_count`
- `labelable_claim_count`
- `labelable_window_count`
- `pending_future_window_count`
- `sector_etf_mapping_missing_count`
- `proxy_series_missing_count`
- `benchmark_series_missing_count`

### P10.3 与 outcome labeler 的关系

`build_industry_etf_proxy_readiness()` 应从 mapping registry 和 PIT availability 中读取：

- sector 是否有 primary mapping。
- ETF series 是否存在。
- benchmark series 是否存在。
- 每个窗口是否可评价。

labeler 生成 outcome 时必须写入：

- `mapping_id`
- `mapping_version`
- `mapping_confidence`
- `pit_availability_status`
- `benchmark_family`
- `cost_model_id`

如果 mapping 或 PIT availability 缺失，claim 进入 readiness gap，不生成 label。

### P10.4 测试计划

新增测试：

1. mapping registry 能覆盖现有 `INDUSTRY_ETF_PROXY_MAPPING` 的关键行业。
2. 缺 ETF series 时记录 `proxy_series_missing`。
3. 缺 benchmark series 时记录 `benchmark_series_missing`。
4. 只有部分窗口可用时只生成可用窗口 label。
5. mapping status 非 `primary` 时默认不生成 label。
6. PIT availability artifact 不包含私有 report text。

### P10.5 验收标准

- 高频行业的 mapping coverage 达到首轮阈值。
- 每个 mapping 都有 PIT availability 状态。
- 行业 label readiness 不再只依赖硬编码 sector 字符串。
- 行业和个股 profile 都记录 `benchmark_family` 和 `cost_model_id`，便于分层比较。

## P11：analysis recipe paper-trading 验证

profile 权重只能说明历史 outcome 的相对表现，不能直接证明 recipe 可交易或可操作。每个 analysis recipe 在进入更强 runtime 使用前，必须通过 shadow paper-trading 验证。

### P11.1 验证对象

需要验证的 recipe 包括：

- 由研报 analytical footprint 生成的 analysis recipe。
- 由 tool gap / method pattern 生成的候选 recipe。
- 由高权重 source/viewpoint/method profile 派生的 recipe。
- 由 industry ETF 或 stock outcome label 反馈强化的 recipe。

recipe 必须明确：

- `recipe_id`
- `source_method_pattern_ids`
- `required_tools`
- `required_data`
- `decision_scope`
- `entry_condition`
- `exit_condition`
- `risk_controls`
- `expected_horizon_days`
- `promotion_state=shadow_candidate`

### P11.2 paper-trading protocol

验证不得只看 profile hit rate。每个 recipe 必须在固定 protocol 下跑 shadow paper-trading：

- 使用 point-in-time 数据。
- 使用 T+1 或更保守 entry 语义。
- 固定交易成本和滑点假设。
- 固定 benchmark。
- 固定回测窗口和 out-of-sample 窗口。
- 禁止在结果出来后改参数。
- 每个 recipe 有唯一 experiment id 和 pre-registration hash。

输出建议：

- `registry/report_intelligence/recipe_paper_trading_runs.jsonl`
- `registry/report_intelligence/recipe_paper_trading_summary.json`

公开 artifact 不得包含原文、claim text 或 source spans。

### P11.3 验证指标

每个 recipe 至少记录：

- `annualized_return`
- `benchmark_return`
- `alpha`
- `sharpe`
- `max_drawdown`
- `turnover`
- `hit_rate`
- `effective_n`
- `cost_adjusted_alpha`
- `alpha_decay_slope`
- `calibration_error`
- `drawdown_breach_count`

验收不能只看收益：

- after-cost alpha 为正。
- max drawdown 不超过预注册阈值。
- effective N 达标。
- 多窗口和多市场 regime 下没有单一 regime 垄断贡献。
- 与 profile 权重一致但 paper-trading 失败的 recipe 必须降级或进入 review。

### P11.4 与 profile 权重的关系

profile 权重只用于排序和优先级，不作为 recipe promotion 的充分条件。

promotion 条件：

- profile evidence 支持。
- paper-trading after-cost 通过。
- PIT/provenance/statistical audit 通过。
- runtime safety audit 通过。
- operator review 接受。

失败处理：

- profile 高但 paper-trading 失败：降低 recipe confidence，记录 `profile_paper_trade_disagreement`。
- paper-trading 通过但 profile 样本少：保留 shadow，等待更多 outcome。
- 指标不稳定：记录 `recipe_instability_gap`，不得 promotion。

## P12：confidence impact monitor

recipe 对 agent confidence 的影响必须进入 monitor。不能只在构建时根据历史 profile 调一次权重，后续还要持续检查 alpha decay 和 calibration drift。

### P12.1 monitor 输入

monitor 输入：

- recipe paper-trading summary。
- source/viewpoint/method performance profile。
- outcome label drift。
- runtime shadow observations。
- agent confidence deltas。
- market regime tags。

### P12.2 监控字段

建议扩展或新增：

- `registry/report_intelligence/confidence_impact_monitor.json`
- `registry/report_intelligence/confidence_impact_observations.jsonl`

字段：

- `recipe_id`
- `agent_id`
- `confidence_delta`
- `confidence_delta_source`
- `expected_alpha`
- `realized_alpha`
- `after_cost_realized_alpha`
- `alpha_decay_slope`
- `calibration_error`
- `brier_score`
- `hit_rate_recent`
- `hit_rate_baseline`
- `drawdown_since_activation`
- `regime`
- `drift_status`
- `recommended_action`

### P12.3 alpha decay 检查

alpha decay 规则：

- 最近窗口 alpha 明显低于历史窗口，标记 `alpha_decay_watch`。
- 连续多个窗口 after-cost alpha <= 0，标记 `alpha_decay_fail`。
- alpha 只在单一 regime 有效，标记 `regime_fragile_alpha`。
- 高 turnover 导致 after-cost alpha 转负，标记 `cost_decay_fail`。

action：

- `keep_shadow`
- `reduce_confidence_impact`
- `freeze_recipe`
- `send_to_manual_review`
- `retire_recipe`

### P12.4 calibration drift 检查

calibration drift 规则：

- agent confidence 上调后，realized hit rate 没有同步改善。
- confidence 分桶越高但 outcome 越差。
- confidence_delta 和 realized alpha 相关性转负。
- recipe 在新 regime 下误校准。

action：

- confidence impact 自动降级。
- recipe 进入 manual review。
- prompt mutation candidate 标记为 `calibration_fix_required`。
- promotion gate 阻断。

### P12.5 验收标准

- 每个会影响 confidence 的 recipe 都有 monitor row。
- monitor 能识别 alpha decay 和 calibration drift。
- confidence impact 不能绕过 paper-trading validation。
- lockbox 未打开前，monitor 只能影响 shadow weighting，不能改 production decision。

## P13：建议执行顺序

建议用六个 PR 或六组 commit 分离：

1. **Markdown coverage expansion**：扩大真实 PDF→Markdown 覆盖率，产出私有 processing status 和公开聚合 coverage summary。
2. **Industry ETF mapping registry**：扩展行业到 ETF proxy 映射表，并记录每个 mapping 的 PIT 可用性。
3. **Stock label core**：配置、builder、schema、tests、audit。
4. **Recipe paper-trading validation**：为 analysis recipe 建立 pre-registered shadow paper-trading 验证。
5. **Confidence impact monitor**：把 recipe 对 confidence 的影响纳入 monitor，并持续检查 alpha decay / calibration drift。
6. **Evolution loop preparation**：把 stock/industry outcome、paper-trading 和 monitor 反馈接入 prompt mutation candidate 和 tool-gap prioritization。

前五个改动完成后，先用 synthetic fixture 跑通，再用少量真实私有研报和 qlib 数据做 shadow dry-run。第六个改动必须等 outcome rows、paper-trading 和 confidence monitor 都足够稳定后再开始。

进入 evolution 改动的客观门槛：

- 至少 100 个唯一 forecast claim 形成完整或部分 outcome window set。
- stock 和 industry 两类 proxy 各不少于 30 个唯一 claim。
- 至少 20 个 analysis recipe 完成 pre-registered paper-trading。
- 进入 evolution 的 recipe 必须具备 after-cost paper-trading summary。
- confidence impact monitor 连续 3 次刷新无 blocker。
- 最近 3 次 derived refresh 的 schema、PIT、provenance、statistical robustness audit 全部通过。
- 人工 gold-set 中 forecast target/direction/horizon 抽取 precision 达到既定门槛，且 `stock_target_conflict` 可解释。
- outcome 分布和 missing gap 分布稳定，没有单一 gap 占比异常扩大。

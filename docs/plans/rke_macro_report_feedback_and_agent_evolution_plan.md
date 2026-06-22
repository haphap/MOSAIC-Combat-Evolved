# RKE 宏观研报市场反馈、评级与 Agent 演化闭环计划

## 背景

Report Intelligence 已经把宏观策略研报接入抽取链路，并且已经有首轮
`macro_asset_proxy` outcome label：LLM 只抽取宏观观点、方向、目标和机制，系统用
PIT 市场价格窗口生成非 LLM 市场反馈。

当前能力可以证明宏观研报观点已经“开始可评价”，但还没有达到“宏观观点全面可评级、可演化、
可供下游 macro agents 使用”的交付标准。主要限制是：

1. 当前宏观市场反馈主要是 ETF/资产代理，尚未把直接利率、收益率曲线、汇率、波动率、
   非黄金商品期货/现货序列接入 outcome labeler。
2. 多资产宏观观点常常包含“利率、美元、人民币、黄金、权益、债券”多个 leg，但当前
   `target` 更接近单目标映射，容易丢掉完整宏观策略观点中的一部分。
3. `claim_regime_trace` 已经作为 PIT 背景信息存在，但还没有形成稳定的
   agent-readable regime snapshot 和 agent prior 输出。
4. viewpoint performance profile 已经能读取 `macro_asset_proxy` label，但样本仍少，
   需要按 macro agent、metric family、regime bucket 分层，避免把异质资产和不同成本模型混算。
5. 下游 macro agents 需要的是可审计、可降级、无 source prose 泄漏的研究先验，而不是原始
   claim 文本或 LLM 自评。

本计划参考 `docs/plans/rke_stock_report_outcome_and_evolution_plan.md` 的结构：
先定义数据契约，再实现 labeler 和 readiness，再接 schema/audit/test，最后建立评级、演化和
agent 消费接口。

## 目标

最终目标是让宏观研报观点形成完整闭环：

```text
宏观研报 PDF/Markdown
  -> source-grounded macro claim / macro claim legs
  -> PIT claim_regime_trace and macro_regime_snapshot
  -> non-LLM market outcome labels
  -> claim rating and viewpoint performance profile
  -> macro agent research priors
  -> offline evolution candidates
  -> gated shadow adoption
```

交付后应满足：

- 宏观观点可评级：每条可评价 macro claim leg 都能产生 pending、blocked 或 completed 的
  PIT 市场反馈状态。
- 宏观观点可演化：错误、正确、低置信、mapping gap、数据缺口都能进入 evolution candidate
  输入，而不是只停留在人工审阅记录。
- 宏观观点可供 agents 使用：下游 macro agents 可以读取红线内的 summary/prior，不读取私有
  原文、source span 或 claim text。
- 宏观观点可审计：PIT、provenance、statistical robustness、privacy、schema gate 都能验证。

## 原则

1. LLM 只负责抽取观点、结构、机制和目标；不判断宏观观点是否正确。
2. claim correctness 只能来自非 LLM 的 PIT outcome label 或人工 gold-set。
3. `claim_regime_trace` 是背景信息，只用于回测后分层评价，不用于抽取阶段验证 claim。
4. 宏观 claim 的 `claim_horizon` 来自原文上下文；固定的 90/180/360 天只是 evaluation
   windows，不能伪装成原文预测期限。
5. 直接序列优先于 ETF 代理。收益率、汇率、波动率、商品价格有 PIT 序列时，不能悄悄用
   ETF proxy 反推。
6. 多资产宏观观点必须保留 parent claim 和 child claim legs，不能为了单目标 label 丢失
   原文策略逻辑。
7. 缺目标、缺方向、缺 quote convention、缺 PIT 序列、缺交易日或 exit 未到期时，只记录
   readiness gap 或 pending window，不补造 label。
8. RKE 继续 shadow-only；任何宏观研报研究先验都不能直接改变生产交易决策。
9. public artifact 不能包含 `claim_text`、`source_span_ids`、原文摘录、报告摘要或私有 licensed
   数据；agent prior 只能发布 redacted derived summary。

## 当前状态

当前已有能力：

- `forecast_claims.jsonl` 能承载宏观 claim、`analyst_claim`、`claim_regime_trace`、
  `metric_proxy_mapping` 和 pre-review。
- `macro_asset_proxy` 已进入 outcome label schema 和 readiness。
- `macro_asset_proxy` 使用 T+1 entry 和 90/180/360 evaluation windows。
- `outcome_label_source=pit_macro_asset_etf_price_window`。
- `decision_basis=directional_macro_asset_proxy_return`。
- PIT/provenance/statistical robustness/evolution readiness gate 已能覆盖首轮宏观 proxy label。
- 本分支已新增 `macro_series_directional` 与 `macro_curve_directional` label type，
  收益率、汇率、波动率、商品价格、期限利差等 direct PIT 序列优先于 ETF proxy。
- 本分支已新增 scorecard `macro_series` 只读适配器：
  `ReportIntelligenceConfig.scorecard_db_path` 指向已有 `scorecard.db` 时，refresh 会按
  claim 所需 series/curve leg 读取 PIT observations 并生成 `sha256:` data vintage hash；
  DB 或序列缺失时只进入 readiness gap，不补造 label。
- 本分支已新增 `mosaic-rke macro-series-backfill`：
  先用已有 `mosaic.dataflows.macro_data` adapter 拉取宏观序列并写入 scorecard
  `macro_series`，再运行 `mosaic-rke report-intelligence --refresh-derived-only
  --scorecard-db-path data/scorecard.db`。RKE refresh 仍只读 scorecard DB，不负责原始数据采集。
- 本分支已新增 public-safe `macro_regime_snapshots.jsonl` 与
  `macro_agent_research_priors.jsonl`：只包含 agent/date/regime/profile aggregate 和
  shadow-only policy，不包含 `claim_text`、`source_span_ids`、报告标题或原文。
- 本分支已新增 parent macro claim + child `macro_claim_legs` 契约：`forecast_claims.jsonl`
  仍是私有源头，不新增平行 raw claim 文件；宏观 outcome/readiness/profile 在内存中按 leg
  展开，并通过 `parent_forecast_claim_id`、`macro_claim_leg_id`、`macro_claim_leg_index`
  保持可追溯。
- 本分支已让 `macro_asset_proxy`、`macro_series_directional`、`macro_curve_directional`
  labels 写入 leg trace 字段；asset proxy 额外写入 `target_agent_candidates`、
  `quote_convention=price_return` 和 `proxy_or_direct=proxy`；curve label 额外写入
  `entry_spread_bps`、`exit_spread_bps` 和 `curve_direction`。
- 本分支已扩展 `macro_regime_snapshots.jsonl` 的 agent-readable 字段：
  `regime_family`、`regime_features`、`feature_units`、`source_series_ids`、
  `missing_feature_reasons`，且继续保持 `background_only=true`、
  `claim_validation_allowed=false`。
- 本分支已扩展 `macro_agent_research_priors.jsonl` 的 downstream 字段：
  `macro_claim_leg_ids_redacted`、`metric_family`、`target_series_family`、
  `expected_direction`、`latest_completed_exit_date`、`freshness_bucket`、
  `known_failure_mode_tags`、`tool_gap_ids`；并新增 `mosaic-rke export-macro-agent-priors`
  用于按 `agent_id`/`as_of_date` 输出 redacted shadow prior。
- 本分支已在 evolution readiness gate 中新增 RI-MACRO-01 至 RI-MACRO-07 分支：
  无宏观输入时作为 not-applicable 通过；存在宏观 claim/label/prior/snapshot 时检查 leg
  contract、PIT label coverage、regime snapshot background-only、market-feedback rating
  evidence、prior privacy、prior shadow-only policy 和 readiness gap audit。

## 复用优先级

本计划不是新建第二套宏观 RKE 系统。实施时必须优先复用现有结构，只有现有契约无法表达时才新增
artifact 或 builder。

必须复用的现有能力：

| 现有能力 | 复用方式 | 不重复造车约束 |
| --- | --- | --- |
| `forecast_claims.jsonl` | 继续作为 parent forecast claim 的私有源头 | 不新增平行的 raw macro claim 文件 |
| `claim_regime_trace` | 继续作为 claim as-of 背景 trace | 不把 regime trace 改成 claim validation |
| `build_macro_asset_proxy_readiness()` | 继续负责 ETF/资产代理 readiness | 只扩展字段和 mapping，不重写 ETF proxy labeler |
| `build_macro_asset_proxy_outcome_labels()` | 继续生成 `macro_asset_proxy` labels | 不为权益/债券/黄金 ETF 再建一套 macro price labeler |
| `build_outcome_labeling_readiness_report()` | 汇总 standard、industry、stock、macro readiness | 新增宏观 direct series readiness 时接入该总表 |
| `report_outcome_labels.jsonl` | 继续作为统一 outcome evidence 私有文件 | 不新增独立的 macro outcome 文件，除非只是 derived public aggregate |
| `build_viewpoint_performance_profiles()` | 继续做 viewpoint 层 performance profile | 增加 macro layer/agent 分层，不新造 profile 聚合器 |
| `build_report_intelligence_evolution_readiness_gate()` | 继续作为演化 gate | 增加 RI-MACRO 子检查，不建第二个 gate |
| `schema_validation.py` | 继续做 schema 之外的 hard invariant | 扩展 validator，不只依赖 JSON Schema |
| `macro-agent-data-source-plan.md` | 作为 macro series/evidence 数据源蓝图 | 序列接入沿用其中的 agent/source taxonomy |
| `mosaic/dataflows/macro_data.py` 和 `mosaic/scorecard/store.py` 的 `macro_series` | 作为已有宏观序列采集/存储能力 | RKE 不重复存 raw series；只保存 mapping、hash、label 和 readiness |
| `research_prior_not_current_data` 运行时语义 | 作为下游 agent 消费边界 | prior 只能是研究背景，不能变成 current signal |

新增内容的判断标准：

1. 如果只是新增 label type，优先扩展 `report_outcome_labels.jsonl` 和现有 profile/gate。
2. 如果只是新增数据源，优先接到现有 `macro_series`/dataflow/catalog 语义。
3. 如果只是给 agent 消费，优先复用 `research_prior_not_current_data` 和 weighted research context
   的 shadow-only 口径。
4. 如果 artifact 可能包含 source prose、claim text、source span 或 licensed raw data，默认 private。
5. 新 builder 必须回答：为什么现有 `macro_asset_proxy`、readiness、profile 或 scorecard
   macro series 不能承载。

当前主要缺口：

| 缺口 | 当前风险 | 本计划解决方式 |
| --- | --- | --- |
| 直接利率/收益率未 label | 利率下行 claim 只能 pending 或错误映射到债券 ETF | 新增 `macro_series_directional` label，bps change 直接评价 |
| 汇率 quote convention 不完整 | USD/CNY 上行和人民币贬值容易方向错配 | 每个 FX label 强制记录 quote convention 和 orientation |
| 商品非黄金 direct series 未接入 | 铜、油、黑色等 claim 只能 ETF proxy 或 pending | 新增 futures/spot mapping 和 commodity series family |
| 波动率可用但未纳入宏观 outcome | volatility agent 无法从研报观点获得评价 | 新增 volatility index/realized-vol label family |
| 多资产 claim 被压成单 target | 宏观策略观点的资产配置逻辑被截断 | 新增 parent claim + claim legs |
| agent 消费接口不明确 | 下游 agents 不能安全使用 RKE 研报经验 | 新增 redacted macro agent priors |
| regime trace 背景不够结构化 | 后续无法按 agent/regime 做归因 | 新增 PIT macro regime snapshot |

## P0：宏观 claim 数据契约

### P0.1 Parent claim 与 claim legs

保留现有 forecast claim 作为 parent claim，但宏观研报中只要出现多个可评价资产或宏观变量，
必须拆出 claim legs。

新增逻辑概念 `macro_claim_leg`：

```text
parent_forecast_claim_id
macro_claim_leg_id
leg_index
target_type
target_id
target_label
metric_family
metric_proxy
direction
quote_convention
orientation_rule
claim_horizon
evaluation_windows
source_grounding_status
target_agent_candidates
```

例子：

```text
parent claim:
  美联储转向更高更久，压制美股和黄金，推升美债收益率与美元。

claim legs:
  US_EQUITY_SP500, equity_index_forward_return, negative
  US_10Y_YIELD, bond_yield_level, positive, unit=bps
  DXY or USDCNY, fx_rate, positive for USD strength
  GOLD, commodity_price or gold_etf_forward_return, negative
```

parent claim 用于保留完整宏观逻辑，claim leg 用于市场反馈和评级。

### P0.2 Target type

首轮支持以下 target type：

| target_type | 用途 | outcome channel |
| --- | --- | --- |
| `macro_asset` | 权益、债券、黄金、港股、美股等资产方向 | `macro_asset_proxy` |
| `macro_series` | 利率、收益率、汇率、波动率、商品价格等直接序列 | `macro_series_directional` |
| `macro_curve` | 利差、期限利差、曲线陡峭/平坦化 | `macro_curve_directional` |
| `macro_policy_event` | 央行/财政/监管事件方向和强度 | 首轮只做 evidence/readiness，不直接打 completed label |
| `macro_regime` | 增长、通胀、流动性、美元、风险偏好 regime 判断 | 首轮只做 background trace，不直接判对错 |

不允许把 `macro_regime` 自身直接当作可交易 outcome，除非明确映射到可观察序列或资产路径。

### P0.3 Metric family

标准化 `metric_family`，避免每个 extractor 自由造词：

| metric_family | 例子 | 默认 agent |
| --- | --- | --- |
| `policy_rate_level` | Fed funds、MLF、OMO rate | `macro.central_bank` |
| `money_market_rate` | SHIBOR、DR007 proxy、SOFR | `macro.central_bank` |
| `bond_yield_level` | CN10Y、US10Y | `macro.yield_curve` |
| `yield_curve_slope` | 2s10s、3m10y、中美国债利差 | `macro.yield_curve` |
| `fx_rate` | USD/CNY、USD/CNH、DXY | `macro.dollar`, `macro.emerging_markets` |
| `equity_index_forward_return` | A 股、港股、美股、成长/价值 | `macro.china`, `macro.emerging_markets` |
| `bond_etf_forward_return` | 国债 ETF、信用债 ETF | `macro.central_bank`, `macro.yield_curve` |
| `commodity_price` | 黄金、铜、油、黑色 | `macro.commodities` |
| `volatility_index` | VIX、iVX、realized vol | `macro.volatility` |
| `risk_off_asset_path` | 黄金、美元、债券、权益回撤组合 | `macro.geopolitical`, `macro.volatility` |
| `growth_inflation_release` | PMI、CPI、PPI、GDP | `macro.china`, `macro.commodities` |

### P0.4 Agent trace policy

新增或规范 `target_agent_candidates`，但不要把它当作 correctness label。

规则：

- claim leg 可以映射到多个 agents。
- agent 映射用于后续 profile、prior、evolution candidate 分发。
- agent 映射来源必须记录：`metric_family_rule`、`target_type_rule`、`source_text_hint` 或
  `manual_review_override`。
- 如果 agent 映射不确定，记录 `agent_mapping_low_confidence` readiness gap，不阻断 claim
  extraction，但阻断 agent prior 发布。

## P1：PIT 宏观序列目录

### P1.1 扩展 macro market series catalog

RKE 侧只需要一个轻量 catalog/readiness 视图来说明哪些宏观序列可用于 claim outcome。
原始时间序列采集和存储优先复用 `macro-agent-data-source-plan.md`、`mosaic/dataflows/macro_data.py`
和 scorecard store 中已有的 `macro_series` 语义。不要在 `registry/report_intelligence/` 下复制
raw macro observations。

可新增或扩展 builder：

- `build_macro_market_series_catalog()`
- `write_macro_market_series_catalog()`

目标是记录“哪些 PIT 序列可用于评价宏观 claim”，不是存储大量原始行情。

字段：

```text
series_id
series_family
source
source_endpoint
instrument
quote_convention
unit
calendar
frequency
latest_observation_date
earliest_observation_date
point_in_time_policy
license_boundary
target_agent_candidates
implementation_status
readiness_status
gap_reason
```

如果底层数据来自 Tushare、AKShare、FRED、qlib 或本地私有缓存，catalog 可以公开记录
series metadata，但不能提交 raw licensed observations。

实现约束：

- 如果已有 dataflow 能返回该序列，RKE 只调用或读取其标准输出，不重写采集器。
- 如果已有 scorecard `macro_series` 表有同一 `series_id`，RKE labeler 只读 as-of safe
  observations 和 `data_vintage_hash`。
- 如果某序列当前只存在于 agent tool 而没有持久化历史，先记录
  `source_not_pit_safe` 或 `series_history_missing`，不能为了完成 label 即时抓当前数据。

### P1.2 首轮必须接入的序列

优先级按“能解决当前限制”和“能覆盖 macro agents”排序：

| 优先级 | series family | 示例 | 解决的问题 |
| --- | --- | --- | --- |
| 1 | CN/US yield level | CN10Y、US10Y、US2Y | 直接评价利率/收益率 claim |
| 1 | FX | USD/CNY、USD/CNH、DXY proxy | 直接评价美元/人民币 claim |
| 1 | volatility | VIX、iVX、A 股 realized vol | 评价 volatility claim |
| 1 | commodity | gold、copper、crude oil、black futures proxy | 评价商品 claim |
| 2 | curve slope | US 2s10s、CN 1y10y、中美利差 | 评价曲线 steepen/flatten claim |
| 2 | China macro release | PMI、CPI、PPI、社融、信贷 | 作为 regime/evidence，不直接替代市场 feedback |
| 2 | central bank operations | OMO、MLF、RRR、policy rate | 作为 regime/evidence 和 event follow-through |
| 3 | geopolitical event proxy | oil/gold/USDCNH/risk-off basket | 作为 geopolitical agent secondary label |
| 3 | institutional flow | fund flow、northbound proxy | 暂作为后续 agent evidence |
| 3 | news sentiment | persisted news sentiment | 暂作为后续 agent evidence |

### P1.3 Data source policy

首轮允许多来源，但必须每条序列记录来源和 PIT 规则：

- qlib/ETF price：用于 tradable proxy path。
- Tushare：宏观、外汇、期货、资金和债券数据，遵守 license boundary。
- AKShare：补充波动率、债券收益率、商品等公开序列；必须在 runbook 记录 endpoint。
- FRED：美国利率、美元、VIX 等公开序列；记录 vintage 或 observation as-of 规则。

任何来源如果只有当前值、没有历史 as-of 或更新时间，只能进入 evidence，不可进入 primary
outcome label。

## P2：宏观 outcome labeler

### P2.1 保留并扩展 `macro_asset_proxy`

现有 `macro_asset_proxy` 继续用于资产代理：

- A 股宽基、沪深300、创业板、港股、美股、债券 ETF、黄金 ETF。
- T+1 entry。
- 90/180/360 trading-day windows。
- `outcome_label_source=pit_macro_asset_etf_price_window`。
- `performance_value_basis=directional_after_cost_return`。

需要补充：

- `target_agent_candidates`
- `macro_claim_leg_id`
- `series_family`
- `quote_convention=price_return`
- `mapping_confidence`
- `proxy_or_direct=proxy`

### P2.2 新增 `macro_series_directional`

新增 direct-series builder，但必须接入统一 readiness/outcome/profile 流程：

- `build_macro_series_directional_readiness()`
- `build_macro_series_directional_outcome_labels()`

适用对象：

- 利率水平。
- 收益率。
- 汇率。
- 波动率。
- 商品 spot/futures/continuous contract。
- 其他有 PIT 序列的宏观变量。

输出 label：

```text
label_type=macro_series_directional
outcome_label_source=pit_macro_series_window
llm_outcome_labeling_allowed=false
parent_forecast_claim_id
macro_claim_leg_id
target_series_id
series_family
source
quote_convention
unit
direction
orientation_rule
entry_datetime
exit_datetime
entry_lag_trading_days=1
horizon_days
entry_value
exit_value
raw_change
pct_change
bps_change
directional_change
directional_hit
performance_value
performance_value_basis
data_vintage_hash
target_resolution_source
```

这些 label 写入现有 `report_outcome_labels.jsonl`，并由现有
`build_viewpoint_performance_profiles()`、schema validation 和 evolution gate 消费。不要新增
`macro_outcome_labels.jsonl`。

`performance_value_basis` 按 series family 固定：

| series_family | performance_value_basis |
| --- | --- |
| yield/rate | `directional_bps_change` |
| fx | `directional_fx_change` |
| volatility | `directional_volatility_change` |
| commodity | `directional_price_return` |
| macro release | 首轮不生成 completed label |

### P2.3 新增 `macro_curve_directional`

曲线观点不能只看单一利率。

支持：

- `US_2S10S`
- `US_3M10Y`
- `CN_1Y10Y`
- `CN_US_10Y_SPREAD`

字段同 `macro_series_directional`，但增加：

```text
long_leg_series_id
short_leg_series_id
entry_spread_bps
exit_spread_bps
spread_change_bps
curve_direction
```

方向约定：

- `steepen`：long-short spread 上行是 hit。
- `flatten`：long-short spread 下行是 hit。
- `invert_deepen`：倒挂加深需要显式 quote convention。

### P2.4 Pending 与 blocked

不满足条件时不生成 completed label，而是进入 readiness：

- `series_mapping_missing`
- `quote_convention_missing`
- `direction_missing_or_unsupported`
- `entry_value_missing`
- `exit_value_missing`
- `exit_after_latest_observation`
- `calendar_missing`
- `source_not_pit_safe`
- `direct_series_required_proxy_not_allowed`
- `agent_mapping_low_confidence`
- `multi_asset_leg_parse_missing`

## P3：宏观 claim 抽取增强

### P3.1 Full-report extraction

宏观研报必须继续按全文上下文抽取，不按单句截取。

抽取时必须识别：

- 宏观 regime：增长、通胀、政策、美元、流动性、风险偏好。
- 传导机制：利率、汇率、信用、估值、盈利、风险溢价、商品供需。
- 资产或序列 target：权益、债券、收益率、汇率、商品、波动率。
- 方向：上行、下行、走强、走弱、利差扩大/收窄、曲线陡峭/平坦。
- 期限：原文 claim horizon 或 report-level/section-level horizon。
- 失败条件：哪些宏观假设变化会使 claim 失效。

### P3.2 多资产 claim legs

抽取 prompt 和 parser 要求：

- 每个 parent macro claim 最多拆出 6 个首要 legs，避免一篇报告生成几十个重复标签。
- 每个 leg 必须有明确 target、metric_family、direction。
- parent claim 保留完整机制链。
- leg claim 可以复用 parent 的机制链，但不能凭空增加原文未支持的 asset。
- leg 没有明确方向时进入 `leg_direction_missing`，不能纳入 outcome。

### P3.3 Horizon extraction

继续沿用当前 horizon 优先级：

1. claim text explicit horizon。
2. section heading or nearby section context。
3. report title, abstract, or core-view temporal context。
4. rating definition or report-level investment-horizon definition。
5. report type default, low confidence。

新增约束：

- 宏观 comment/report 中“数据点评后市场当日反应”不能自动变成未来预测。
- “短期”“中期”“年内”“未来一段时间”必须映射成 confidence-bearing bucket。
- 如果原文只有当前事实，没有未来方向，不生成 forecast leg。

## P4：PIT macro regime snapshot

### P4.1 Snapshot 目标

`claim_regime_trace` 目前记录 claim as-of date 的 regime 背景。下一步要把它做成更稳定、
可审计、可供 profile 和 agents 读取的 PIT snapshot。

新增 builder：

- `build_macro_regime_snapshots()`
- `write_macro_regime_snapshots()`

### P4.2 Snapshot 字段

```text
snapshot_id
as_of_date
agent_id
regime_family
regime_bucket
regime_features
feature_units
source_series_ids
data_vintage_hash
missing_feature_reasons
background_only=true
claim_validation_allowed=false
```

### P4.3 Agent 覆盖

首轮必须覆盖：

| agent | snapshot 内容 |
| --- | --- |
| `macro.central_bank` | policy rate、OMO/MLF、money market rate、liquidity bucket |
| `macro.china` | PMI/CPI/PPI/credit/property/policy support bucket |
| `macro.commodities` | gold/oil/copper/industrial basket trend |
| `macro.dollar` | USD/CNY、DXY proxy、中美利差 |
| `macro.emerging_markets` | HK/EM proxy、USDCNH、risk appetite |
| `macro.geopolitical` | risk-off asset basket、oil/gold shock proxy |
| `macro.volatility` | realized vol、VIX/iVX、drawdown state |
| `macro.yield_curve` | CN/US yields、curve slope、term spread |

`macro.news_sentiment` 和 `macro.institutional_flow` 首轮可以只记录
`snapshot_status=deferred`, 因为它们需要持久化语料和资金流历史后才能 PIT-safe 使用。

### P4.4 使用边界

regime snapshot 只能用于：

- outcome 后分层评价。
- agent prior 解释背景。
- evolution candidate 归因。

不能用于：

- 抽取阶段判断 claim 对错。
- 人工 review 阶段替代原文证据。
- 直接覆盖 claim direction。

## P5：宏观观点评级

### P5.1 Rating 对象

评级优先扩展现有 viewpoint/source/method performance profile，不新建平行评分系统。需要额外对象时，
只增加 profile 的 macro-specific derived 字段或私有中间表。

评级分三层：

1. `macro_claim_leg_rating`：单个 leg 在每个 window 的市场反馈。
2. `macro_parent_claim_rating`：parent claim 下多个 legs 的聚合结果。
3. `macro_viewpoint_cluster_rating`：相似宏观观点在不同报告、不同 regime 下的历史表现。

### P5.2 Rating 状态

每个 rating 必须有状态，不允许只有分数：

| status | 含义 |
| --- | --- |
| `completed` | PIT exit 已到期且数据完整 |
| `pending_window` | exit 还在未来 |
| `blocked_mapping` | target/series/agent 映射缺失 |
| `blocked_data` | PIT 数据缺失或非 PIT-safe |
| `blocked_quality` | claim 质量不满足可评价条件 |
| `insufficient_sample` | 能评价但样本太少，不给稳定结论 |

### P5.3 Rating 指标

leg-level：

```text
directional_hit
performance_value
performance_value_basis
window_horizon_days
series_family
mapping_confidence
data_quality_bucket
```

parent-level：

```text
leg_count
completed_leg_count
weighted_hit_rate
weighted_performance_value
cross_asset_consistency
failed_leg_reasons
rating_status
```

viewpoint-level：

```text
n_nominal
n_effective
shrunk_hit_rate
shrunk_performance_value
regime_conditioned_performance
agent_conditioned_performance
known_failure_modes
statistical_reliability_bucket
```

### P5.4 评级口径

建议首轮不输出“买入/卖出式”评级，而输出审计型 rating：

| rating_bucket | 条件 |
| --- | --- |
| `supportive_evidence` | 方向命中且 performance_value 为正，样本未被 robustness gate 阻断 |
| `mixed_evidence` | 不同 windows 或 legs 明显分歧 |
| `contradictory_evidence` | 主要 windows/legs 与 claim 方向相反 |
| `pending_or_unrated` | 未到期、缺数据或样本不足 |

原因：宏观研报观点通常是多资产、多机制、多期限，不适合过早压缩成单一绝对分数。

## P6：Agent 可消费研究先验

### P6.1 新增 redacted agent prior

新增 artifact：

- `registry/report_intelligence/macro_agent_research_priors.jsonl`

如果该文件包含 claim 原文、source span、报告标题摘要或 licensed raw values，则必须列入
private local registry。首轮建议只输出 redacted derived summary，使其可公开验证 schema。

实现时先检查现有 `weighted_research_contexts.jsonl` 和运行时
`research_prior_not_current_data` 消费路径是否足够。如果能承载 agent prior，则
`macro_agent_research_priors.jsonl` 只作为 redacted export 或 compatibility view；不要让下游
agents 同时读取两套含义重复的 research prior。

字段：

```text
prior_id
agent_id
as_of_date
viewpoint_cluster_id
macro_claim_leg_ids_redacted
metric_family
target_series_family
expected_direction
regime_bucket
rating_bucket
shrunk_hit_rate
shrunk_performance_value
statistical_reliability_bucket
n_effective
latest_completed_exit_date
freshness_bucket
known_failure_mode_tags
tool_gap_ids
use_policy=shadow_research_prior_only
source_policy=no_source_prose
```

### P6.2 Agent 使用方式

下游 macro agents 只能把 prior 当作研究背景：

- 可以引用“历史上类似观点在某 regime 下表现较好/较差”。
- 可以调整 reasoning 中的信息权重。
- 不能直接变成交易信号。
- 不能绕过 macro agent 自己的数据工具。
- 不能读取原始 claim text 或研报 source span。

### P6.3 CLI/API

新增 CLI：

```bash
mosaic-rke report-intelligence export-macro-agent-priors \
  --root . \
  --as-of-date <YYYY-MM-DD> \
  --agent-id macro.central_bank \
  --no-source-prose
```

后续再接 TS bridge：

```text
rke.macroAgentPriors
```

bridge 只返回 redacted prior，不返回私有 forecast claims。

## P7：演化闭环

### P7.1 Evolution 输入

宏观演化输入：

- macro claim leg ratings。
- macro viewpoint cluster ratings。
- mapping/readiness gaps。
- PIT regime-conditioned performance。
- human gold-set review。
- extraction quality failure。
- agent prior consumption audit。
- tool/data gap coverage。

### P7.2 Evolution 输出

演化输出不是直接改 prompt，而是候选项：

- macro extraction prompt mutation candidate。
- macro target/series mapping rule candidate。
- quote convention rule candidate。
- horizon extraction rule candidate。
- macro agent tool requirement candidate。
- macro regime feature addition candidate。
- macro agent research prior weighting candidate。

候选项要进入现有 evolution readiness/report-intelligence action 体系；除非现有 gate schema
无法表达 RI-MACRO 子检查，否则不新增第二个宏观 evolution gate 文件。

### P7.3 Gate

新增或扩展 `evolution_readiness_gate` 的宏观分支：

```text
RI-MACRO-01 macro_claim_leg_contract
RI-MACRO-02 macro_series_pit_label_coverage
RI-MACRO-03 macro_regime_snapshot_background_only
RI-MACRO-04 macro_rating_profile_reliability
RI-MACRO-05 macro_agent_prior_privacy
RI-MACRO-06 macro_agent_prior_shadow_only
RI-MACRO-07 macro_evolution_candidate_audit
```

任何一项 blocker 存在时，不能把 prior 或 prompt mutation 提升到生产。

## P8：Schema、manifest 和隐私边界

需要新增或更新：

- `schemas/report_intelligence_report_outcome_label.schema.json`
- `schemas/report_intelligence_outcome_labeling_readiness.schema.json`
- `schemas/report_intelligence_forecast_claim.schema.json`
- `schemas/report_intelligence_macro_market_series_catalog.schema.json`
- `schemas/report_intelligence_macro_regime_snapshot.schema.json`
- `schemas/report_intelligence_macro_agent_research_prior.schema.json`
- `mosaic/rke/registry_manifest.py`
- `mosaic/rke/report_intelligence.py` 的 private path 常量。

隐私规则：

- `forecast_claims.jsonl` 继续 private。
- `report_outcome_labels.jsonl` 继续 private，因为可能包含 target/source provenance 和 claim ids。
- `macro_regime_snapshots.jsonl` 如果包含 licensed raw values，则 private；如果只包含 coarse buckets，
  可以作为 public aggregate，但首轮建议 private。
- `macro_agent_research_priors.jsonl` 首轮应设计为 public-safe redacted artifact；如果实现中需要
  claim 原文辅助，则拆成 private raw 和 public redacted 两份。

schema 约束：

- `llm_outcome_labeling_allowed=false`。
- `entry_lag_trading_days >= 1`。
- FX 必须有 `quote_convention`。
- yield/rate 必须有 `unit=bps` 或可转换单位。
- completed label 必须有 entry/exit value。
- pending label 不能伪造 performance value。
- public redacted prior 禁止 `claim_text`、`source_span_ids`、`abstract`、`source_excerpt`。

## P9：Audit 扩展

### P9.1 PIT audit

新增检查：

- 禁止 T+0 entry。
- exit date 不能超过 series 最新 observation。
- macro series label 必须使用 as-of safe series。
- yield claim 必须直接用 yield/rate series，不能静默反转 bond ETF。
- FX claim 必须记录 quote convention。
- commodity continuous contract 必须记录 roll policy。
- regime snapshot 必须 `background_only=true`。

### P9.2 Provenance audit

新增检查：

- 每个 claim leg 必须能追溯 parent forecast claim。
- parent claim 必须有 source-grounded extraction。
- leg target/direction 必须来自原文或结构化 rewrite，不允许无来源补全。
- agent prior 只能引用 redacted ids 和 derived stats。

### P9.3 Statistical robustness audit

新增检查：

- 多 window 不能让单 claim leg 权重超过 1。
- parent claim 多 legs 聚合必须记录 leg count 和 coverage。
- 不同 `series_family`、`label_type`、`cost_model_id`、`quote_convention` 分层统计。
- 样本不足时只能输出 `insufficient_sample`，不能输出稳定结论。

### P9.4 Privacy audit

新增检查：

- public prior 中禁止 claim 原文和 source span。
- public schema artifact 禁止 licensed raw observations。
- private outputs 必须被 gitignored。
- `git rev-list origin/main..HEAD` 不能包含宏观研报 PDF、Markdown、source prose 或 private JSONL。

## P10：测试计划

### P10.1 Unit fixture

构造小型 PIT fixture：

- yield series：一条上行、一条下行。
- FX series：USD/CNY 上行和下行。
- volatility series：VIX/iVX 上行和下行。
- commodity series：黄金、铜或原油价格。
- curve series：2s10s steepen 和 flatten。
- ETF proxy series：保留现有 macro asset proxy fixture。
- regime snapshot fixture：每个 agent 至少一个 snapshot bucket。

### P10.2 必测用例

1. `test_report_intelligence_splits_macro_parent_claim_into_legs`
2. `test_report_intelligence_labels_macro_yield_claim_with_direct_series`
3. `test_report_intelligence_rejects_bond_etf_inversion_for_yield_claim`
4. `test_report_intelligence_labels_fx_claim_with_quote_convention`
5. `test_report_intelligence_labels_volatility_claim_with_direct_series`
6. `test_report_intelligence_labels_commodity_claim_with_roll_policy`
7. `test_report_intelligence_keeps_macro_asset_proxy_for_asset_allocation_claim`
8. `test_report_intelligence_macro_series_readiness_records_pending_exit_window`
9. `test_report_intelligence_macro_regime_snapshot_is_background_only`
10. `test_report_intelligence_builds_redacted_macro_agent_priors`
11. `test_report_intelligence_public_macro_agent_priors_do_not_leak_source_prose`
12. `test_report_intelligence_macro_evolution_gate_blocks_unmapped_series`

### P10.3 验证命令

```bash
uvx ruff@0.15.15 check mosaic tests
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_rke_report_intelligence.py -q \
  --basetemp .mosaic/tmp/pytest-rke-ri
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_rke_schema_artifacts.py -q \
  --basetemp .mosaic/tmp/pytest-rke-schema
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python scripts/check_prompt_leaks.py
git diff --check
```

私有边界验证：

```bash
git check-ignore registry/report_intelligence/forecast_claims.jsonl
git check-ignore registry/report_intelligence/report_outcome_labels.jsonl
git rev-list --objects origin/main..HEAD | rg 'tushare_research_reports|report_intelligence/markdown|report_intelligence/pdfs|forecast_claims|report_outcome_labels' || true
```

## P11：实施拆解

### P11.1 阶段 A：契约和 schema

实施：

- 增加 macro claim leg 数据结构。
- 增加 macro market series catalog schema。
- 增加 macro regime snapshot schema。
- 增加 macro agent research prior schema。
- 扩展 outcome label schema。

验收：

- schema-status 通过。
- fixture 能构造 parent claim + claim legs。
- public-safe prior schema 禁止 source prose 字段。

### P11.2 阶段 B：直接序列 labeler

实施：

- `macro_series_directional` readiness。
- `macro_series_directional` outcome labeler。
- `macro_curve_directional` outcome labeler。
- quote convention/orientation rule。

验收：

- yield、FX、volatility、commodity fixture 都能 completed。
- exit 未到期进入 pending。
- 缺 quote convention 阻断 FX label。
- yield claim 不允许 ETF 反向代理。

### P11.3 阶段 C：regime snapshot

实施：

- 每个已启用 macro agent 的 PIT snapshot builder。
- snapshot data vintage hash。
- missing feature reason。
- background-only audit。

验收：

- central_bank、china、commodities、dollar、emerging_markets、geopolitical、
  volatility、yield_curve 都有 snapshot 或明确 deferred gap。
- `claim_validation_allowed=false`。
- PIT audit 能发现 snapshot 被误用为 correctness label。

### P11.4 阶段 D：评级和 profile

实施：

- leg rating。
- parent rating。
- viewpoint cluster rating 扩展。
- regime-conditioned performance。
- agent-conditioned performance。

验收：

- mixed legs 不被折叠成单一 hit。
- insufficient sample 输出 provisional。
- profile 按 `series_family` 和 `agent_id` 分层。

### P11.5 阶段 E：agent prior 输出

实施：

- `build_macro_agent_research_priors()`。
- `export-macro-agent-priors` CLI。
- redacted public/private boundary。
- 后续可选 TS bridge handler。

验收：

- 每个 agent prior 都有 `use_policy=shadow_research_prior_only`。
- 不包含 claim text/source span。
- downstream agent 能按 agent_id/as_of_date 读取 summary。
- 缺样本或 blocker 时 prior 降级为 `insufficient_sample` 或不输出。

### P11.6 阶段 F：演化 gate

实施：

- 宏观 mapping gap -> evolution candidate。
- 宏观低质量 extraction -> prompt candidate。
- 宏观 data gap -> tool/data acquisition candidate。
- 宏观 agent prior consumption -> shadow audit。

验收：

- evolution gate 有 RI-MACRO-01 到 RI-MACRO-07。
- 任一 blocker 存在时，不能 promotion。
- 通过后仍是 shadow-only。

## P12：交付条件

达到以下条件，才算完成本计划：

1. 至少 50 条宏观 parent claims 完成 pre-review，其中可评价 claim legs 不少于 80 条。
2. `macro_asset_proxy`、`macro_series_directional`、`macro_curve_directional` 三类 outcome
   至少各有 fixture 和真实样本路径。
3. 利率/收益率、FX、volatility、commodity 至少四类直接序列 labeler 可运行。
4. 至少 8 个 macro agents 有 regime snapshot 或明确 deferred gap。
5. 至少 6 个 macro agents 有 redacted research prior 输出；没有 prior 的 agent 必须有
   readiness gap。
6. outcome label 对 pending、blocked、completed 三种状态区分清楚。
7. claim rating 能输出 `supportive_evidence`、`mixed_evidence`、
   `contradictory_evidence`、`pending_or_unrated`。
8. PIT/provenance/statistical/privacy/schema gates 全部通过。
9. public artifacts 不包含 source prose、claim text、source span、PDF/Markdown/cache。
10. 运行 `export-macro-agent-priors` 能生成下游可消费的 shadow research prior。

### P12 当前验收状态（2026-06-22）

当前分支已经满足大部分宏观闭环的功能性条件，但还不能宣称本计划全部完成：

- 条件 1：已满足。当前 public-safe extraction summary 有 999 条 forecast claims；
  宏观演化检查中有 109 条 macro forecast/claim-leg rows，超过 50 条 parent claim 和
  80 条可评价 legs 的首轮门槛。
- 条件 2：已满足类型覆盖。`macro_asset_proxy=75`、`macro_series_directional=31`、
  `macro_curve_directional=3` 已进入 outcome label summary；测试中保留三类 fixture，
  真实样本通过当前私有 claim/outcome labels 路径生成。
- 条件 3：部分满足。利率/收益率、FX、commodity direct-series label 已有真实宏观样本；
  VIX 波动率序列已通过 `macro-series-backfill --series-id VIX` 写入本地
  `scorecard.db` 并在 `macro_market_series_catalog.jsonl` 标记为 ready。当前 claim pool
  尚未抽到可完成的真实 volatility claim leg，因此 volatility 还停留在数据/fixture ready，
  真实 completed label 需要后续宏观语料出现明确波动率方向观点。
- 条件 4：已满足。8 个 macro agents 都有 regime snapshot 或 deferred snapshot：
  `macro.central_bank`、`macro.china`、`macro.commodities`、`macro.dollar`、
  `macro.emerging_markets`、`macro.geopolitical`、`macro.volatility`、
  `macro.yield_curve`。
- 条件 5：已满足最低门槛。7 个 macro agents 已有 redacted research priors：
  `macro.central_bank`、`macro.china`、`macro.commodities`、`macro.dollar`、
  `macro.emerging_markets`、`macro.geopolitical`、`macro.yield_curve`。
  `macro.volatility` 当前无 prior 输出，原因是缺少可评价 volatility claim leg，而不是缺少
  VIX 数据。
- 条件 6：已满足。outcome/readiness 区分 completed、pending window 和 readiness gap；
  evolution gate 的 RI-MACRO-02 也记录 macro pending/gap counts。
- 条件 7：已满足。`macro_agent_research_priors.jsonl` 的 rating buckets 已标准化为
  `supportive_evidence`、`mixed_evidence`、`contradictory_evidence`、
  `pending_or_unrated`；当前分布为 supportive 40、mixed 66、contradictory 16、
  pending 3281。
- 条件 8：部分满足。当前 `schema-status --root . --failures-only --no-write`
  为 0 failure，PIT、provenance、statistical 检查也为 0 failure；
  analytical-footprint review 已完成 2588/2588 且 patch v1.5 coverage accepted。
  但 RI-EVOL-04 仍要求 3 个不同 `data_vintage_hash` 的 clean audit refresh；
  当前只有 1/3，仍需后续上游数据 vintage 变化后再积累 2 个 clean refresh。
- 条件 9：已验证当前宏观 public artifacts。`macro_agent_research_priors.jsonl`、
  `macro_market_series_catalog.jsonl`、`macro_regime_snapshots.jsonl`、
  `extraction_report.json`、`outcome_labeling_readiness.json` 未命中
  `claim_text`、`source_span_ids`、`abstract`、`pdf_url`、`markdown_path`。
- 条件 10：已满足。`export-macro-agent-priors --agent-id macro.dollar
  --as-of-date 2026-06-18 --no-source-prose` 可输出 491 条 shadow prior，
  `production_signal_allowed=false`，且不含 claim text/source span。

因此当前状态是：宏观研报观点已经可评级、可导出 shadow prior、可进入 evolution gate；
全局 schema/patch/manual review 阻塞已经清除。剩余交付限制是 RI-EVOL-04 的
distinct clean audit vintage history：在出现新的上游数据 vintage 前，重复
`refresh-derived-only` 不会增加有效计数，不能把本计划标记为 fully delivered，也不能让
宏观研报 prior 影响生产交易。

## P13：首轮不做的事

为控制风险，首轮明确不做：

- 不让宏观研报观点直接影响生产交易。
- 不让 LLM 判断 claim 正确性。
- 不实时联网补历史新闻作为 PIT evidence。
- 不把收益率 claim 静默映射成债券 ETF 反向结果。
- 不把 regime snapshot 当作 claim validation。
- 不把多资产 parent claim 强行压成单一 score。
- 不公开任何含 source prose 或 licensed raw data 的 artifact。

## P14：建议优先级

推荐实施顺序：

1. 先做 P0/P1/P2：解决直接序列 outcome label 的硬限制。
2. 再做 P3/P4：补 claim legs 和 PIT regime snapshot。
3. 再做 P5/P6：形成评级和 agent prior。
4. 最后做 P7/P9：让宏观抽取、映射、数据缺口进入演化 gate。

理由：

- 没有直接序列 label，宏观观点只能停留在 ETF proxy，评级会偏窄。
- 没有 claim legs，多资产宏观观点会被截断，agent 分发也不准。
- 没有 regime snapshot，评级无法解释“什么宏观背景下有效”。
- 没有 redacted prior，下游 agents 只能读取私有 claim 或完全不用 RKE 经验。
- 没有 gates，演化会变成不可审计的 prompt 调参。

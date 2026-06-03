# Macro Agent Data Source And Drawdown-Aware Scoring Plan

日期：2026-06-03

## 要解决的问题

PR #73 已经让 macro agent 可以进入 autoresearch：Layer 1 输出会进入
`macro_signals`，成熟后由 `MacroScorer` 打分，autoresearch selection 在 macro quota
允许时可以选择 macro prompt。当前剩下的问题不是 selection 或 Darwinian weight，而是：

1. 10 个 macro agent 还没有各自完整、可回测、可审计的数据源。
2. 当前 agent-specific scoring 只有 `volatility` 和 `geopolitical` 使用
   `max_drawdown_5d` 作为 primary label。
3. 其他 macro agent 仍然回落到 `benchmark_fallback_5d`，这能让 autoresearch 运转，
   但不能充分评价它们各自负责的宏观能力。
4. Tushare Pro 文档里的宏观、行情、资金、语料、期货、外汇、债券、ETF 等数据还没有被
   系统化盘点；OpenCLI 的新闻和社交采集能力也还没有变成可回测的历史事件源。

目标是补齐所有 macro agent 的数据源，让每个 agent 至少有一个 primary drawdown-aware
label，并且保留 fallback / missing provenance，避免把未验证数据悄悄混入主评分。

## 当前代码状态

本地已存在的 macro 工具主要在：

- `mosaic/dataflows/macro_data.py`
- `mosaic/dataflows/opencli_news.py`
- `mosaic/dataflows/sino_us.py`
- `mosaic/agents/utils/macro_tools.py`
- `mosaic/dataflows/interface.py`
- `mosaic/scorecard/macro_labels.py`
- `mosaic/scorecard/scorer.py`

当前 Layer 1 macro agent 和 TS required tools：

| Agent | 已接入工具 | 当前 scoring 状态 |
| --- | --- | --- |
| `central_bank` | `get_pboc_ops`, `get_fred_series`, `get_yield_curve_cn` | fallback |
| `china` | `get_industry_policy`, `get_pboc_ops`, `get_property_data` | fallback |
| `geopolitical` | `get_us_china_relations`, `get_xueqiu_heat`, `get_industry_policy` | `max_drawdown_5d` primary |
| `dollar` | `get_fred_series`, `get_usdcny`, `get_us_china_spread` | fallback |
| `yield_curve` | `get_yield_curve_cn`, `get_fred_series`, `get_us_china_spread` | fallback |
| `commodities` | `get_commodity_prices`, `get_fred_series`, `get_yield_curve_cn` | fallback |
| `volatility` | `get_fred_series`, `get_ivx`, `get_etf_indicator` | `max_drawdown_5d` primary |
| `emerging_markets` | `get_etf_price_data`, `get_us_china_spread`, `get_etf_info`, `get_etf_nav`, `get_etf_universe` | fallback |
| `news_sentiment` | `get_xueqiu_heat`, `get_news`, `get_caixin_sentiment`, `get_industry_policy` | fallback |
| `institutional_flow` | `get_lhb_ranking`, `get_fund_flow`, `get_stock_moneyflow` | fallback |

当前可用但未充分接入 scorecard label 的 Tushare/OpenCLI 能力：

- Tushare 行情路径：`daily`, `index_daily`, `fund_daily`, `fund_nav`, `fut_daily`,
  `fx_daily`, `cb_daily`。
- Tushare 宏观/利率：`cn_pmi`, `cn_gdp`, `cn_cpi`, `cn_ppi`, `shibor`,
  `shibor_quote`, `hibor`, `yc_cb`。
- Tushare 资金/热度：`moneyflow`, `moneyflow_ind_ths`, `fund_share`, `top_list`,
  `ths_hot`, `dc_hot`, `margin_secs`, `limit_list_ths`。
- Tushare 语料：`news`, `research_report`。
- OpenCLI 采集：Google News/Search、Xueqiu、Weibo、Xiaohongshu、Sina Finance、
  global news、Caixin query bundle。

## 设计原则

### 1. Tushare document 先 catalog 化，再接入评分

“用好 Tushare Pro/document 的全部数据”不能理解成把所有 endpoint 都直接塞进 agent
prompt 或 scoring。正确顺序是：

1. 从 Tushare Pro document 生成 endpoint catalog。
2. 记录每个 endpoint 的类别、参数、字段、时间字段、更新频率、是否 path-capable、是否
   point-in-time safe。
3. 把 endpoint 映射到 macro taxonomy：增长、通胀、流动性、利率、汇率、商品、资金流、
   风险偏好、文本事件。
4. 只有能形成 forward path 或可审计事件序列的数据，才进入 primary scoring。

这样可以真正覆盖“全部数据”的盘点，同时避免未验证接口污染主评分。

全量覆盖契约：

- catalog refresh 必须扫描 Tushare document 当前能发现的全部 endpoint，不只扫描本文列举的
  macro 常用接口。
- 每个 endpoint 都要被归类为 `scoring_candidate`、`evidence_candidate`、
  `deferred_unverified` 或 `not_macro_relevant`。
- `not_macro_relevant` 也要保留在 catalog 中，原因是后续 agent universe、ETF proxy、
  行业 basket、港股/美股 proxy 可能会从当前看似非宏观的行情或基础信息接口派生出来。
- 文档类别至少覆盖：沪深股票、指数、ETF、公募基金、期货、期权、外汇、债券、宏观经济、
  资金流、两融、港股、美股、热榜、新闻快讯、券商研报和大模型语料专题。
- LLM prompt 只能看到经过 tool/agent 映射后的必要工具；全量 catalog 是工程侧资产，不是
  让 agent 每次读取全部 Tushare endpoint。

### 2. 分清 agent 输入和 scorer 标签

Macro agent 可以看央行操作、政策新闻、研究报告、资金流和热榜，这些是分析输入。
Scorer 需要的是成熟后可客观评价的 label source，例如：

- 5 日价格路径。
- 5 日最大回撤。
- 5 日相对收益路径。
- 事件发生后的可回测冲击路径。
- 经 as-of 约束后的文本事件强度。

因此每个 agent 都要有两张表：

1. `evidence_sources`：给 prompt 使用的数据源。
2. `label_sources`：给 scorecard 使用的数据源。

### 3. 所有 primary label 都要 drawdown-aware

不再只看 endpoint return。每个 primary label 都应提供至少 2 个 forward path 点，最好提供
完整 5 个交易日路径，并计算：

- `terminal_return_5d`
- `max_drawdown_5d`
- `realized_volatility_5d`
- `path_metric_5d`
- `label_source_status`
- `source_series_id`

统一方向约定：

- label path 先转换成 risk-on orientation。
- 正值表示宏观环境支持 risk-on。
- 负值表示宏观环境支持 risk-off。
- agent vote 仍是 `+1 / 0 / -1`。

建议 scoring 公式：

```text
oriented_return = terminal_return_5d after risk-on orientation
adverse_drawdown = abs(min(max_drawdown_5d, 0))
vol_scale = max(trailing_realized_vol_5d, macro_vol_floor)
path_metric = oriented_return - drawdown_penalty_lambda * adverse_drawdown
path_metric_norm = clip(path_metric / vol_scale, -3, 3)

if vote != 0:
    raw_macro_score_5d = confidence * vote * path_metric_norm
else:
    raw_macro_score_5d = confidence * (neutral_band / vol_scale - abs(path_metric_norm))
```

这个公式保留 PR #73 的 `raw_macro_score_5d` 语义：selection 和 Darwinian ranking 仍使用
raw，不使用 influence-adjusted score。

### 4. OpenCLI 必须先持久化，不能实时回看

OpenCLI 的实时新闻/社交搜索对 prompt 很有价值，但直接在历史评分时搜索互联网会产生
look-ahead 和不可复现问题。计划里 OpenCLI 只能这样进入 scoring：

1. 每天按 agent query bundle 采集。
2. 写入 `macro_documents`，记录 `published_at`、`discovered_at`、`source`、`url`、
   `content_hash`、`query`、`agent_tags`。
3. 评分只读取信号日期当时已经持久化的 document。
4. 没有持久化历史时只能作为 prompt evidence，不能作为 primary label。

## 目标数据模型

新增或扩展以下结构。

### `tushare_endpoint_catalog`

从 Tushare Pro document 生成，不手写长期维护。

关键字段：

```text
endpoint_name
doc_path
doc_url
category
sub_category
params_json
default_fields_json
optional_fields_json
date_fields_json
update_frequency
min_points_or_permission
path_capable
event_capable
point_in_time_rule
agent_tags_json
label_candidate_tags_json
verified_at
verification_status
```

### `macro_series`

存可回测时间序列。

```text
series_id
source
endpoint_name
instrument
date
value
open
high
low
close
volume
metadata_json
fetched_at
as_of_date
```

### `macro_documents`

存 OpenCLI 和 Tushare 语料。

```text
document_id
source
channel
query
title
url
published_at
discovered_at
content_hash
content_excerpt
agent_tags_json
event_tags_json
sentiment_score
quality_score
```

### `macro_label_sources`

把 agent label 映射到实际 series/event。

```text
agent
label_type
primary_series_id
proxy_series_ids_json
orientation_rule
lookback_days
forward_horizon_trading_days
fallback_label
availability_status
implementation_status
```

## 每个 agent 的补齐计划

### `central_bank`

Evidence sources:

- Tushare `cb_op` 或 catalog 中验证后的央行公开市场操作 endpoint。
- Tushare `shibor`, `shibor_quote`, `yc_cb`。
- FRED `FEDFUNDS`, `DFF`, `SOFR` 相关利率序列。
- OpenCLI query bundle：PBOC、MLF、OMO、reserve requirement、Fed、FOMC。

Primary drawdown label:

- `rate_sensitive_path_5d`
- risk-on orientation：利率下行、流动性宽松、债券/成长相对走强为正。
- 价格路径候选：债券 ETF、成长 ETF、沪深300/创业板相对路径，具体 instrument 由
  `fund_basic` + `etf_index` + `index_basic` catalog 选择。

Implementation tasks:

- 增加 `get_money_market_rates`，聚合 `shibor`/`shibor_quote`。
- 增加 `get_rate_sensitive_proxy_path`，统一返回 5 日 forward path。
- `MacroLabelSpec("central_bank", "rate_sensitive_path_5d", ...)` 标为 primary。

### `china`

Evidence sources:

- Tushare `cn_pmi`, `cn_gdp`, `cn_cpi`, `cn_ppi`。
- Tushare `news`, `research_report`。
- 已有 `get_property_data`。
- OpenCLI query bundle：国务院、发改委、财政部、住建部、证监会、地产政策、财政刺激、
  消费刺激、出口管制。

Primary drawdown label:

- `china_growth_proxy_path_5d`
- risk-on orientation：中国增长代理资产相对沪深300走强为正。
- 价格路径候选：顺周期行业指数/ETF、地产链、基建链、消费链、沪深300/中证500/创业板相对
  路径。

Secondary labels:

- `policy_support_followthrough_5d`
- `property_chain_relative_path_5d`

Implementation tasks:

- 建 `china_macro_release_series`，低频宏观数据只作为 evidence/event，不直接当 5 日收益。
- 建 `policy_event_classifier`，从 Tushare news/research_report 和 OpenCLI 文档中抽取政策强度。
- 用政策事件后的行业/指数 forward path 做 drawdown-aware label。

### `geopolitical`

Evidence sources:

- 已有 Tsinghua Sino-US relations index。
- Tushare `news`, `research_report`, `fut_daily`, `fx_daily`。
- OpenCLI query bundle：US-China, tariffs, export controls, Taiwan, sanctions,
  Middle East, oil supply, geopolitics risk.

Primary drawdown label:

- 保留 `max_drawdown_5d`，但升级为 `risk_off_path_5d`。
- risk-on orientation：A-share/HK/EM risk assets 下跌、黄金/油价冲击、USDCNH 上行都转成负向。

Secondary labels:

- `oil_or_gold_shock_path_5d`
- `hk_em_risk_off_path_5d`

Implementation tasks:

- 当前 `max_drawdown_5d` 已 primary，但只是 benchmark path。
- 加入 commodity/FX shock path 作为更贴合 geopolitical 的 primary candidate。
- OpenCLI geopolitics 文档先进入 evidence，只有持久化历史足够后才进入 event label。

### `dollar`

Evidence sources:

- Tushare `fx_daily`：`USDCNH.FXCM`。
- FRED `DTWEXBGS`。
- `get_us_china_spread`。
- OpenCLI query bundle：dollar, yuan, CNH, Fed, Treasury yields, capital outflow。

Primary drawdown label:

- `cny_pressure_path_5d`
- risk-on orientation：USDCNH 下行、人民币走强、HK/China/EM proxy 走强为正。

Secondary labels:

- `hk_or_em_relative_path_5d`
- `dollar_pressure_path_5d`

Implementation tasks:

- 把 `fx_daily` 输出解析成 `macro_series`.
- 增加 FX path 的 orientation rule：`risk_on = -USDCNH_return`。
- 加入 HK/EM proxy 相对路径，避免只用汇率本身评价 dollar agent。

### `yield_curve`

Evidence sources:

- Tushare `yc_cb`, `shibor`, `hibor`。
- FRED `DGS10`, `DGS2`, `DGS3MO`。
- `get_us_china_spread`。

Primary drawdown label:

- `curve_sensitive_path_5d`
- risk-on orientation：曲线稳定/陡峭化且风险资产无大回撤为正；倒挂加深或长端快速上行引发
  风险资产回撤为负。

Secondary labels:

- `growth_vs_value_relative_path_5d`
- `recession_risk_path_5d`

Implementation tasks:

- 建 CN/US curve factor：`2s10s`, `3m10y`, `CN10Y-US10Y`。
- 用 rate-sensitive ETF/指数和 growth/value 相对路径作为 forward label。
- 低频曲线状态只作 state feature，不直接替代 forward market path。

### `commodities`

Evidence sources:

- Tushare `fut_daily`：SC、CU、AU、RB、I、M 等主连或主力映射。
- FRED `DCOILWTICO`, `GOLDPMGBD228NLBM`。
- Tushare `research_report` 行业研报。
- OpenCLI query bundle：oil, copper, gold, iron ore, China demand, supply shock。

Primary drawdown label:

- `commodity_basket_path_5d`
- risk-on orientation：工业品/能源在需求驱动下走强为正；黄金避险单边走强、油价供给冲击并
  压制风险资产时转为风险负向。

Secondary labels:

- `industrial_metals_path_5d`
- `cyclical_sector_relative_path_5d`

Implementation tasks:

- 将现有 `get_commodity_prices` 的 CSV 转为标准 `macro_series`。
- 增加主力合约 mapping 验证，避免连续合约代码变化造成断点。
- 商品 label 同时记录 commodity path 和 A-share cyclical forward path。

### `volatility`

Evidence sources:

- 当前 `get_ivx`。
- Tushare `fund_daily` / `get_etf_indicator`。
- FRED `VIXCLS`。
- Tushare 期权/期货 tick 或 option metadata，作为后续增强。

Primary drawdown label:

- 当前 `max_drawdown_5d` 可继续 primary。
- 目标升级为 `volatility_shock_path_5d`，同时使用 benchmark drawdown、
  realized volatility、VIX/iVX proxy jump。

Secondary labels:

- `realized_volatility_5d`
- `risk_off_shock_path_5d`

Implementation tasks:

- 把 `realized_volatility_5d` 从 deferred 改成 implemented。
- 评分中加入 vol spike penalty，不只看 benchmark MDD。
- 保证 benchmark series 少于 2 点时 `label_source_status="fallback"`。

### `emerging_markets`

Evidence sources:

- Tushare `fund_daily`, `fund_nav`, `fund_basic`, `etf_index`, `hk_basic`,
  `hk_tradecal`。
- Tushare `fx_daily`。
- FRED dollar/yield 序列。
- OpenCLI query bundle：HK, EM, Asia FX, capital flow, China ADR, offshore risk。

Primary drawdown label:

- `em_hk_relative_path_5d`
- risk-on orientation：HK/EM/China offshore proxy 相对沪深300走强为正，美元走强和 CNH 贬值
  作为负向压力。

Secondary labels:

- `risk_appetite_path_5d`
- `china_offshore_relative_path_5d`

Implementation tasks:

- 用 `get_etf_universe` + `fund_basic` + `etf_index` 自动选择 HK/EM proxy ETF。
- 用 `hk_tradecal` 做交易日对齐。
- 建相对路径 label：proxy return - benchmark return，并计算 proxy path drawdown。

### `news_sentiment`

Evidence sources:

- OpenCLI：Google News/Search、Caixin、Xueqiu、Weibo、Xiaohongshu、Sina Finance。
- Tushare `news`, `research_report`, `ths_hot`, `dc_hot`。
- 已有 `get_xueqiu_heat`, `get_caixin_sentiment`, `get_industry_policy`。

Primary drawdown label:

- `sentiment_followthrough_path_5d`
- risk-on orientation：正面情绪/热度扩散后的市场或热点 basket forward path 为正；过热后
  高回撤或反转为负。

Secondary labels:

- `short_term_reversal_path_5d`
- `market_heat_breadth_path_5d`

Implementation tasks:

- `macro_documents` 持久化是前置条件。
- 增加 sentiment/event classifier，输出每日 market sentiment index。
- 用 sentiment index 分位数触发的 forward path 评分，避免直接用 LLM 主观情绪当 label。

### `institutional_flow`

Evidence sources:

- Tushare `moneyflow`。
- Tushare `moneyflow_ind_ths`。
- Tushare `fund_share`。
- Tushare `top_list`。
- Tushare `margin_secs`, `limit_list_ths` 作为资金风险偏好辅助。

Primary drawdown label:

- `flow_followthrough_path_5d`
- risk-on orientation：主力净流入行业/股票 basket 后续 5 日相对收益、低回撤为正；净流出后继续
  下跌或高回撤为负。

Secondary labels:

- `sector_flow_followthrough_path_5d`
- `market_breadth_path_5d`

Implementation tasks:

- 不使用 northbound-flow fallback。
- 用 `moneyflow_ind_ths` 生成行业 flow rank。
- 用 top inflow industries/stocks 组 basket，5 日 forward path 评价 flow 是否延续。
- 单股 `moneyflow` 只在有 universe/basket 时进入 label，避免孤立 ticker 噪声。

## 统一实现阶段

### P0: Tushare endpoint catalog

交付：

- `mosaic/dataflows/tushare_catalog.py`
- catalog 生成命令，例如 `uv run python -m mosaic.dataflows.tushare_catalog refresh`
- catalog fixture 和 schema test。

验收：

- catalog 覆盖 Tushare document 中宏观、债券、外汇、期货、ETF、指数、资金流、语料等相关
  类别。
- catalog 中每个 endpoint 都有归类状态，未用于 macro 的 endpoint 也不能从 snapshot 中消失。
- 每个 endpoint 有 `path_capable` / `event_capable` / `point_in_time_rule`。
- 本地无法访问 Tushare document 时，使用上次生成的 tracked snapshot，不阻断 tests。

### P1: Macro series/document store

交付：

- `macro_series`
- `macro_documents`
- `macro_label_sources`
- backfill/import helpers。

验收：

- 所有时间序列都以 `as_of_date` 写入。
- OpenCLI 文档按 `discovered_at` 固化，历史评分不实时搜索互联网。
- 缺数据时状态写 `missing`，代理数据写 `fallback`，真实主源写 `primary`。

### P2: Common path-label engine

交付：

- `compute_drawdown_aware_path_label(series_id, d0, horizon=5, orientation_rule=...)`
- `compute_relative_path_label(proxy, benchmark, d0, horizon=5)`
- `compute_basket_path_label(members, weights, d0, horizon=5)`

验收：

- 支持 terminal return、max drawdown、realized vol、path metric。
- 少于 2 个 forward points 不能标 primary。
- 所有 label 统一 risk-on orientation。

### P3: Agent label implementation

先落最容易形成 path 的 labels：

1. `dollar.cny_pressure_path_5d`
2. `commodities.commodity_basket_path_5d`
3. `yield_curve.curve_sensitive_path_5d`
4. `central_bank.rate_sensitive_path_5d`
5. `emerging_markets.em_hk_relative_path_5d`
6. `institutional_flow.flow_followthrough_path_5d`
7. `china.china_growth_proxy_path_5d`
8. `news_sentiment.sentiment_followthrough_path_5d`
9. `volatility.volatility_shock_path_5d`
10. `geopolitical.risk_off_path_5d`

验收：

- `list_macro_label_inventory()` 中 10 个 agent 都有至少一个 `primary_ready=True` 的
  drawdown-aware label。
- 每个 primary label 有 fixture test 和 missing/fallback test。
- `MacroScorer` 对所有 10 个 agent 能写入 `label_type != benchmark_fallback_5d`，除非测试
  明确模拟缺数据。

### P4: OpenCLI event pipeline

交付：

- 每个 agent 的 query bundle。
- document dedupe/hash。
- event classifier。
- daily sentiment/event index。

验收：

- 历史 scoring 只读取已持久化 document。
- 无 `published_at` 的 document 只能作为 prompt evidence，不作为 primary event label。
- 事件分类失败不阻断 market path labels。

### P5: Prompt/tool updates

交付：

- 更新 macro prompts，让 agent 明确调用新工具。
- 更新 TS required tools，只加必要工具，不把 catalog 全部暴露给 LLM。
- 给 macro mutator context 展示 agent-specific label performance。

验收：

- agent prompt 中区分 evidence 和 realized scoring。
- prompt 不要求 agent 自己计算未来收益。
- autoresearch mutation context 显示 primary/fallback/missing 比例。

### P6: Backtest and rollout gate

交付：

- scorecard integration test：ingest -> score all 10 macro agents -> list skill ->
  autoresearch selection。
- 回测对比：benchmark fallback vs agent-specific drawdown-aware labels。
- feature flag：`autoresearch.macro_full_label_sources_enabled=false` 默认关闭，验证后再开。

验收：

- 默认行为可回滚到 PR #73。
- 开启新 flag 后 macro selection 频率稳定，不因某个新 label 的尺度异常而垄断 selection。
- keep/revert 仍只由 portfolio `delta_sharpe` 决定。

## 需要新增的测试

- `test_tushare_catalog_schema`
- `test_tushare_catalog_has_required_macro_categories`
- `test_macro_series_point_in_time`
- `test_opencli_documents_are_discovery_time_bound`
- `test_drawdown_label_requires_two_forward_points`
- `test_relative_path_label_orientation`
- `test_all_macro_agents_have_primary_drawdown_label`
- `test_macro_scorer_uses_agent_primary_label_when_available`
- `test_macro_scorer_falls_back_with_provenance_when_source_missing`
- `test_institutional_flow_does_not_use_northbound_fallback`
- `test_opencli_realtime_search_not_used_in_historical_scoring`

## 风险和约束

1. Tushare endpoint 名称和字段会变化，所以必须通过 catalog snapshot 和 adapter tests 管住。
2. 低频宏观数据不能直接当 5 日 label，只能作为 state/event feature。
3. OpenCLI 实时搜索不能用于历史评分，必须先持久化。
4. 每个 agent 的 primary label 尺度不同，selection 仍应在 macro layer 内按 percentile/rank
   使用 raw score，不跨层直接比绝对值。
5. influence score 继续只做 diagnostics，不进入 selection 或 Darwinian ranking。
6. 任何新 label 都必须写 `label_source_status`，否则 macro skill 会误读数据质量。

## 第一版落地切片

第一版不追求一次接完所有 endpoint，而是先让每个 agent 拿到一个可靠 primary label：

```text
P0: catalog + required categories snapshot
P1: macro_series + path-label engine
P2: dollar / commodities / yield_curve / central_bank / emerging_markets path labels
P3: institutional_flow basket label
P4: volatility / geopolitical label 升级
P5: china / news_sentiment document-event pipeline
P6: all-10-agent integration gate
```

完成 P2 后，已有一半 macro agent 会脱离 benchmark fallback；完成 P6 后，10 个 macro agent
都能使用 drawdown-aware primary scoring。

## 目标覆盖矩阵

| 用户目标 | 文件中的覆盖点 | 完成证据 |
| --- | --- | --- |
| 规划补齐所有宏观 agent 的数据源 | “每个 agent 的补齐计划”逐一覆盖 10 个 Layer 1 macro agent | `central_bank` 到 `institutional_flow` 每个 agent 都有 evidence sources、primary label、secondary labels、implementation tasks |
| 用好 `tushare.pro/document` 的全部数据 | “Tushare document 先 catalog 化”定义全量覆盖契约 | catalog refresh 扫描全部 endpoint，并把每个 endpoint 归类为 scoring/evidence/deferred/not macro relevant |
| 用好 OpenCLI 数据收集能力 | “OpenCLI 必须先持久化”与 P4 event pipeline | `macro_documents`、query bundle、dedupe/hash、event classifier、discovered_at 约束 |
| 将 plan 写入文件 | 本文件即交付物 | `docs/macro-agent-data-source-plan.md` |
| 确保所有 agent 能使用 drawdown-aware scoring | “所有 primary label 都要 drawdown-aware”与 P3/P6 验收 | 10 个 agent 都必须有 `primary_ready=True` 的 drawdown-aware label，且 `MacroScorer` 能写入非 fallback label |

## 参考来源

- Tushare Pro official site: https://tushare.pro/
- Tushare Pro document entry: https://tushare.pro/document/2
- 本地当前实现：`mosaic/dataflows/macro_data.py`
- 本地当前 OpenCLI 实现：`mosaic/dataflows/opencli_news.py`
- 本地当前 macro label inventory：`mosaic/scorecard/macro_labels.py`
- 本地当前 macro scorer：`mosaic/scorecard/scorer.py`

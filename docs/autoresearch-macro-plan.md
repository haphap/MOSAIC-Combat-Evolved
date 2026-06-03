# Autoresearch Macro Agent Plan

## 背景

当前要解决的问题是：macro agent 不产生投资建议，所以不会自然纳入现有 autoresearch 的绩效反馈框架。

这里的 "macro agent" 指 Layer 1 的宏观代理，例如：

- `central_bank`
- `china`
- `geopolitical`
- `dollar`
- `yield_curve`
- `commodities`
- `volatility`
- `emerging_markets`
- `news_sentiment`
- `institutional_flow`

这些 agent 的作用是输出宏观状态、风险偏好、资金流、政策方向等上游信号。它们不会输出 ticker、action、target weight，也不应该伪装成会下单的投资建议 agent。

## 当前代码里的实际状态

现有 scorecard 的核心表是 `recommendations`。它记录的是 ticker 级别的建议，并在未来 5 日、21 日后用价格数据评分。

现有展开规则大致是：

- Layer 1 macro agents 不进入 `recommendations`，因为没有 ticker。
- Layer 2 sector agents 的 longs 会变成 recommendation rows。
- Layer 3 superinvestor agents 的 picks 会变成 recommendation rows。
- Layer 4 CIO 的 portfolio_actions 会变成 recommendation rows。

这个边界是合理的。macro agent 不应该被强行写入 `recommendations`，否则会污染 recommendation alpha、Darwinian weight 和后续投资建议统计。

但是这带来一个副作用：macro agent 没有 `alpha_5d`，也没有 rolling Sharpe，因此 autoresearch 没有合适的历史表现数据来判断哪个 macro prompt 应该优先优化。

目前 autoresearch 的行为是：

- `autoresearch.trigger` 一次只选 1 个 agent。
- TS orchestrator 默认 `maxMutations = 1`，CLI `--max` 默认也是 1。
- 实际 agent selection 在 Python `mosaic/bridge/handlers/autoresearch.py::_select_agent`。
- TS orchestrator 只调用 `autoresearch.trigger`，并传入 `force_agent` / `maxMutations`。
- 如果手动指定 `--agent volatility`，macro prompt 可以被强制优化。
- 但自动选择时，macro 没有真正的绩效信号，只能被当作 cold start 或 neutral 处理。

因此问题不是 "macro prompt 不能被改"，而是 "macro 没有自己的可比较评分，所以不能被稳定、合理地纳入自动选择"。

## 设计原则

### 1. 不把 macro 伪装成投资建议

不能让 macro agent 生成假的 ticker/action，也不能把 macro 输出塞进 `recommendations`。

原因：

- macro 是上游 regime signal，不是交易建议。
- recommendation alpha 是 ticker/action 级别指标。
- 把两者混在一张表里会让 scorecard 统计含义变差。
- 后续 Darwinian weight 会误以为 macro 和 stock-picking agent 是同一种能力。

正确做法是新增 macro 自己的评分链路。

### 2. macro 评分评估方向判断，不评估股票推荐

macro agent 应该被评估的是：

- 它判断未来市场风险偏好是否正确。
- 它对 risk-on / risk-off / neutral 的判断是否对后续组合有帮助。
- 它的信号是否稳定、可复用、比随机判断更好。

最终目标仍然是第二版设计：不同 macro agent 使用各自负责的宏观标签评分，并记录该 agent 对 Layer 1 consensus 的影响力。

但首个可落地版本不应该一次性引入所有复杂度。MVP 先使用统一 benchmark 5d direction 作为主标签，只计算 `hit_rate_5d` 和 `raw_macro_score_5d`，让 macro agent 能干净进入 autoresearch。agent-specific labels、influence weighting、adaptive quota 和 Darwinian weight 单表迁移都作为独立 follow-up gate。

### 3. 选择阶段分层比较，保留阶段统一目标

macro 的评分标准和 recommendation alpha 不同，不能直接 raw score 混排。

选择谁去 mutate 时：

- macro agents 只和 macro agents 比。
- sector/superinvestor/decision agents 继续用 recommendation performance / Darwinian weight。
- 全局层面用 quota 和 normalized priority 控制频率。

决定是否 keep/revert 时：

- 仍然使用整体 backtest 的 `delta_sharpe`。
- 也就是说，macro prompt 即使 macro hit rate 变好，也必须证明最终组合 Sharpe 改善，才应该保留。

这个分工可以避免两个问题：

- 选择阶段不被不同指标尺度污染。
- 保留阶段仍然对最终投资目标负责。

## 落地切片

这份 plan 的目标方向不变，但落地顺序要分成 MVP 和 gated follow-ups。

### MVP

MVP 只解决一个核心问题：macro agent 有自己的绩效记录，并能被 autoresearch 自动选择。

MVP 范围：

```text
1. 新增 macro_signals。
2. 从 Layer 1 macro outputs 生成 vote/confidence。
3. 使用 benchmark 5d direction 作为主标签。
4. 计算 hit_rate_5d 和 raw_macro_score_5d。
5. 新增 scorecard.list_macro_skill。
6. Python autoresearch.trigger 在 macro quota 允许时按 macro skill 选择 macro agent。
7. TS mutator 给 macro agent 展示 macro performance context。
8. keep/revert 仍然只看 portfolio backtest delta_sharpe。
```

MVP 不做：

```text
1. 不接入 agent-specific labels。
2. 不使用 influence_weight 作为主评分。
3. 不改 Layer 1 consensus 公式。
4. 不迁移 darwinian_weights。
5. 不改变现有 recommendation agents 的 Darwinian weight 计算。
```

### Follow-ups

后续按独立 gate 增量加入：

```text
Follow-up A: agent-specific labels
  每个 label 必须先列出可用数据源；没有数据源的 label 不进入 primary path。

Follow-up B: influence diagnostics
  先作为 diagnostics，不作为 Darwinian ranking 输入。
  如果进入选择逻辑，必须保留 raw_macro_score track，避免低影响力坏 agent 永久不被选。

Follow-up C: adaptive macro quota
  在静态 quota 可用后再启用，并加入 per-agent recent-revert penalty。

Follow-up D: unified darwinian_weights migration
  单独 backtest/gate，不和 macro MVP 同 PR 落地。

Follow-up E: Layer 1 uses Darwinian weights
  只有在 unified darwinian_weights 通过回归验证后再打开。
```

## Layer 1 Consensus 生成与消费

当前 Layer 1 consensus 的生成链路是：

```text
daily_cycle
  -> layer1 subgraph
     -> 10 个 macro agents 并行运行
     -> 每个 macro agent 写入 state.layer1_outputs[agent]
     -> aggregate_l1 读取所有 macro outputs
     -> 写入 state.layer1_consensus
```

`aggregate_l1` 不是第二次 LLM 总结，而是确定性的 vote aggregator。当前代码里的公式是：

```text
score = sum(vote_i * confidence_i) / sum(confidence_i)
```

其中每个 macro agent 的结构化输出先被映射为：

```text
+1 = risk-on / bullish
 0 = neutral
-1 = risk-off / bearish
```

然后使用阈值生成 stance：

```text
score > +0.3 => BULLISH
score < -0.3 => BEARISH
otherwise    => NEUTRAL
```

同时生成：

```text
confidence = mean(confidence_i)
layer_1_consensus_score = mean_confidence * alignment_ratio
key_drivers = 各 macro agent 的高置信度 key driver 摘要
```

在后续 gated 阶段引入 macro Darwinian weight 后，Layer 1 consensus 的生产公式才改为：

```text
score =
  sum(vote_i * confidence_i * darwinian_weight_i)
  / sum(confidence_i * darwinian_weight_i)
```

MVP 保持当前等权公式不变。这样可以先验证 macro 评分和 autoresearch 选择链路，不同时改变下游 Layer 2/3/4 的输入分布。

`state.layer1_consensus` 的下游消费链路是：

```text
Layer 2 sector agents:
  在 prompt context 中读取 macro stance、confidence、score、key_drivers。
  用于约束 sector longs/shorts 的方向、风险偏好和题材选择。

Layer 3 superinvestor agents:
  在 prompt context 中读取 Layer 1 macro regime 和 Layer 2 sector picks。
  用于把投资哲学应用到候选池时考虑宏观环境。

Layer 4 decision agents:
  通过 shared user context 读取 Layer 1 macro regime。
  CRO/CIO/alpha_discovery/autonomous_execution 等都会看到宏观 regime。
```

所以 macro Darwinian weight 不是局部指标。它会先改变 Layer 1 consensus，再通过 prompt context 影响 Layer 2/3/4 的后续判断，最终影响组合建议和 backtest 表现。这也是为什么 Darwinian weight 单表迁移和 Layer 1 加权必须作为独立 gate，而不是和 macro MVP 同时落地。

## Macro 评分方案

### Step 1: 将 macro 输出映射成方向票

每个 macro agent 的结构化输出映射成一个方向票：

```text
+1 = risk-on / bullish
 0 = neutral
-1 = risk-off / bearish
```

项目里的 TS Layer 1 aggregator 已经有类似映射，可以作为 canonical vote mapping。

示例：

```text
central_bank:
  ACCOMMODATIVE -> +1
  TIGHTENING    -> -1
  其他           -> 0

china:
  PRO_GROWTH   -> +1
  RESTRAINING  -> -1
  其他          -> 0

geopolitical:
  escalation_level <= 2 -> +1
  escalation_level >= 4 -> -1
  其他                  -> 0

dollar:
  WEAKENING     -> +1
  STRENGTHENING -> -1
  其他           -> 0

yield_curve:
  GREEN -> +1
  RED   -> -1
  其他  -> 0

commodities:
  ACCELERATING -> +1
  DECELERATING -> -1
  其他          -> 0

volatility:
  RISK_ON  -> +1
  RISK_OFF -> -1
  其他      -> 0

emerging_markets:
  OUTPERFORMING  -> +1
  UNDERPERFORMING -> -1
  其他             -> 0

news_sentiment:
  contrarian retail euphoria -> -1
  retail_sentiment_score > 0.3 -> +1
  retail_sentiment_score < -0.3 -> -1
  其他 -> 0

institutional_flow:
  net flow > +1B CNY -> +1
  net flow < -1B CNY -> -1
  其他 -> 0
```

每条信号同时保留 `confidence`。

### Step 2: 生成未来标签

MVP 使用统一 benchmark 5d direction 作为主标签：

```text
MOSAIC_BENCHMARK_TICKER，默认 000300.SH
```

MVP fallback 规则就是主规则：

```text
benchmark_return_5d > +0.5%  => realized_label = +1
benchmark_return_5d < -0.5%  => realized_label = -1
否则                         => realized_label = 0
```

这样可以先验证 macro signal ingest、scoring、skill RPC、selection、mutation、keep/revert 这条主链路。

agent-specific labels 是 follow-up。不同 macro agent 负责的宏观维度不同，长期不应该全部用 CSI300 方向判断对错；但每个专属标签必须先有明确、已接入的数据源，不能默默 fallback 后仍被当成 agent-specific label。

建议标签：

```text
volatility:
  realized_volatility_5d
  max_drawdown_5d
  risk_off_label

geopolitical:
  max_drawdown_5d
  risk_off_label
  oil_or_gold_shock_label

central_bank:
  rate_sensitive_assets_return_5d
  growth_vs_value_relative_return_5d
  liquidity_condition_label

yield_curve:
  rate_sensitive_assets_return_5d
  growth_vs_value_relative_return_5d
  recession_risk_label

china:
  cyclical_sector_relative_return_5d
  china_growth_proxy_return_5d
  policy_support_label

commodities:
  commodity_index_return_5d
  industrial_metals_return_5d
  cyclical_sector_relative_return_5d

dollar:
  cnh_or_cny_move_5d
  hk_or_em_relative_return_5d
  dollar_pressure_label

emerging_markets:
  em_relative_return_5d
  hk_or_china_relative_return_5d
  risk_appetite_label

institutional_flow:
  flow_continuation_5d
  market_breadth_5d
  sector_flow_follow_through_5d

news_sentiment:
  sentiment_follow_through_5d
  short_term_reversal_label
  market_heat_or_breadth_5d
```

数据源 gate：

```text
label
agent
data_source
available_now
fallback_label
implementation_status
```

初步判断：

```text
benchmark_return_5d:
  data_source = existing price / benchmark return path
  available_now = yes
  implementation_status = MVP primary

realized_volatility_5d / max_drawdown_5d:
  data_source = benchmark OHLC/close series
  available_now = likely yes
  implementation_status = follow-up candidate

cyclical_sector_relative_return_5d:
  data_source = sector ETF/index mapping
  available_now = needs confirmation
  implementation_status = deferred until mapping exists

commodity_index_return_5d / industrial_metals_return_5d:
  data_source = commodity proxy instruments
  available_now = needs confirmation
  implementation_status = deferred

cnh_or_cny_move_5d / hk_or_em_relative_return_5d:
  data_source = FX/HK/EM proxy instruments
  available_now = needs confirmation
  implementation_status = deferred

flow_continuation_5d / sector_flow_follow_through_5d:
  data_source = 主力资金流 / 行业资金流
  available_now = needs reconciliation with current money-flow dataflow
  implementation_status = deferred

sentiment_follow_through_5d:
  data_source = news/sentiment time series
  available_now = needs confirmation
  implementation_status = deferred
```

特别注意：`institutional_flow` 和 `news_sentiment` 不能重新依赖已被弃用或存在时效问题的 northbound-flow 风格信号。后续实现必须对齐当前主力资金流/行业资金流方向。

实现上可以先把每个 agent 的标签归一成一个 realized label：

```text
+1 = 该 agent 负责的宏观维度验证了 risk-on / bullish 判断
 0 = 该维度结果中性或噪声不足
-1 = 该 agent 负责的宏观维度验证了 risk-off / bearish 判断
```

如果某个专属标签暂时没有数据，则明确写入 `label_type=benchmark_fallback_5d`，不能写成专属 label_type。

### Step 3: 计算 hit rate

方向命中率：

```text
hit_5d = vote == realized_label
```

这个指标直观，但比较粗：

- 它不能区分大涨、大跌和小涨、小跌。
- 它不能体现 confidence。
- 它适合作为可解释展示，不适合作为唯一排序依据。

### Step 4: 计算 raw macro score

每个 agent 根据 realized label 计算 `raw_macro_score_5d`。MVP 使用 benchmark label；follow-up agent-specific labels 使用同一字段。

如果标签是方向性收益，例如 benchmark、周期板块、商品指数、EM 相对收益：

先固定归一化口径（必须在 Phase 2 scorer 落地前定死，因为它决定入库的 `raw_macro_score_5d` 数值，事后改会让历史分数不可比）：

```text
forward_return_5d = label 标的未来 5 个交易日收益（MVP = benchmark 5d return，原始收益单位）
vol_scale_5d      = max(trailing_realized_daily_vol_20d * sqrt(5), vol_floor)   # vol_floor 默认 0.005
normalized_forward_move_5d = clip(forward_return_5d / vol_scale_5d, -3.0, +3.0) # 无量纲，按波动归一
neutral_band_norm = macro_neutral_band / vol_scale_5d   # 把 0.5% 原始阈值换算到同一归一化口径
```

```text
if vote != 0:
    raw_macro_score_5d = confidence * vote * normalized_forward_move_5d
else:
    raw_macro_score_5d = confidence * (neutral_band_norm - abs(normalized_forward_move_5d))
```

单位一致性：`macro_neutral_band`（默认 0.005）是**原始收益**阈值，只用于 Step 2 的 realized_label 分桶；在上面的分数公式里统一换算成 `neutral_band_norm`，使 move 与 band 都在归一化口径下比较，避免原始收益和归一化值混用。

如果标签是风险事件，例如未来最大回撤、realized volatility、risk-off shock：

```text
vote = -1 且 risk_off_event 发生 => 正分
vote = +1 且 risk_off_event 发生 => 负分
vote = 0 且没有明显事件 => 小正分
```

这个分数的目标是评价 "agent 负责的宏观维度有没有判断对"，而不是简单评价 "CSI300 涨跌有没有判断对"。

MVP 取舍：benchmark 方向标签较粗，在明显趋势行情里，长期投 neutral 的 macro agent 会因为 `neutral_band_norm - |move|` 变负而更容易被排成 "worst"，从而被优先 mutate。这是 MVP 的有意取舍（长期不表态的 channel 价值确实较低）；agent-specific labels（Phase 7）用更贴近各自维度的标签缓解这一偏向。

### Step 5: 计算 influence diagnostics

有些 macro agent 当天虽然有输出，但对 Layer 1 consensus 影响很小。第二版可以记录影响力 diagnostics，但 MVP 不把它作为主评分，也不把它喂给 Darwinian weight。

定义：

```text
influence_weight_equal = abs(equal_weight_consensus_with_agent - equal_weight_consensus_without_agent)
```

如果 Layer 1 后续已经使用 Darwinian weight，influence 也必须用以下两种方式之一计算，避免反馈环：

```text
方案 1: 使用 equal weights 计算 influence。
方案 2: 使用 signal_date as-of frozen weights 计算 influence。
```

不能用更新后的权重计算 influence 后再用该 influence 更新同一个 agent 的权重。否则会形成：

```text
weight -> consensus -> influence -> macro score -> weight
```

这是自强化反馈环，会导致 rich-get-richer 或震荡。

同时保留方向一致性信息：

```text
aligned_with_consensus = vote 是否和最终 Layer 1 stance 同向
```

诊断评分：

```text
effective_macro_score_5d = influence_weight_equal * raw_macro_score_5d
```

使用约束：

- `raw_macro_score_5d` 永远保留，并参与 macro skill 展示和选择。
- `effective_macro_score_5d` 初期只作为 diagnostics。
- Darwinian ranking 使用 `raw_macro_score_5d`，不使用 influence-scaled score。
- 如果后续把 influence 加入选择，必须设置 influence floor 或 raw-score fallback。

低影响力死区需要显式避免：一个 macro agent 如果长期判断很差但很少影响 consensus，`influence * raw` 会接近 0，反而可能永远不是 "worst"。选择逻辑不能只看 `effective_macro_score_5d`。

### Step 6: 聚合成 macro skill

对每个 macro agent 聚合历史已评分信号：

```text
agent
n_obs
mean_raw_macro_score_5d
mean_effective_macro_score_5d
hit_rate_5d
sharpe_window
mean_influence_weight_equal
latest_signal_date
```

其中：

```text
mean_raw_macro_score_5d = average(raw_macro_score_5d)
mean_effective_macro_score_5d = average(effective_macro_score_5d)
hit_rate_5d = average(hit_5d)
sharpe_window = annualized Sharpe of raw_macro_score_5d   # MVP 基于 raw（effective 在 MVP 为 null/diagnostics）
```

MVP 的主要排序字段是 `mean_raw_macro_score_5d`，`sharpe_window` 在 MVP 也基于 `raw_macro_score_5d`。`mean_effective_macro_score_5d` 可以返回但为 null/diagnostics，不作为默认选择依据；influence diagnostics（Phase 8）启用后再另算 effective 版本的 sharpe。

`sharpe_window` 和现有 `scorecard.list_skill` 的语义保持类似：窗口由调用方的 `since` 控制，不等同于 Darwinian rolling 30d，也不映射成 Darwinian weight。

## 数据结构草案

新增 SQLite 表 `macro_signals`。

建议字段：

```text
id INTEGER PRIMARY KEY AUTOINCREMENT
cohort TEXT NOT NULL
agent TEXT NOT NULL
date TEXT NOT NULL
vote INTEGER NOT NULL CHECK (vote IN (-1, 0, 1))
confidence REAL
raw_output_json TEXT
consensus_stance TEXT
consensus_score REAL
label_type TEXT
label_source_status TEXT
label_value_5d REAL
benchmark_return_5d REAL
realized_label INTEGER CHECK (realized_label IN (-1, 0, 1))
hit_5d INTEGER
raw_macro_score_5d REAL
influence_weight_equal REAL
effective_macro_score_5d REAL
prompt_repo_id TEXT
prompt_sha256 TEXT
scored_at TEXT
UNIQUE(cohort, agent, date)
```

说明：

- `raw_output_json` 保留原始结构化输出，便于以后回放和诊断。
- `vote` 是评分用的归一化方向。
- `label_type` 记录本次评分使用的标签，例如 MVP 的 `benchmark_5d`，以及 follow-up 的 `max_drawdown_5d`、`commodity_index_return_5d`、`benchmark_fallback_5d`。
- `label_source_status` 记录 `primary`、`fallback`、`missing`、`deferred`。
- `label_value_5d` 记录专属标签的原始数值。
- `benchmark_return_5d` 保留 fallback 或对照用途。
- `consensus_stance` 和 `consensus_score` 记录 Layer 1 聚合状态。
- `influence_weight_equal` 记录 equal-weight leave-one-out influence，避免权重反馈环。
- `effective_macro_score_5d` 是 influence diagnostics，不是 MVP 默认排序字段。
- `prompt_repo_id` / `prompt_sha256` 用于让后续 evaluator 按同一 prompt repo 比较 like-for-like。
- `scored_at IS NULL` 表示未来 5 日窗口尚未评分。

## Autoresearch 选择策略

### 当前行为

默认每次 autoresearch cycle 只改 1 个 agent。

如果 CLI 使用：

```bash
pnpm dev autoresearch trigger
```

则默认最多 1 个 mutation。

如果使用：

```bash
pnpm dev autoresearch trigger --max 3
```

则同一个 cycle 最多顺序尝试 3 个 mutation，但每次仍然是一个 agent。

当前默认约束：

```text
agent_mutation_cooldown_hours = 24
monthly_modification_cap_per_cohort = 100
```

因此在每天运行一次 autoresearch 的情况下，频率主要由选择策略和 quota 决定。

### 为什么不能直接混排

不能这样做：

```text
所有 agents 按 raw score 从差到好排序
```

因为：

- macro score 在 MVP 是 benchmark-label raw score；follow-up 可能加入 agent-specific label 和 influence diagnostics。
- recommendation alpha 是 ticker/action alpha。
- 两者尺度、分布、样本密度都不同。
- 直接比较会导致 macro 被过多或过少选择。

### 建议的 layer-aware 选择

MVP 先采用静态 macro quota：

```text
macro_quota = 20%
min_macro_interval_days = 5
```

含义：

- 正常情况下，每天跑一次 autoresearch 时，大约每 5 天优化一次 macro。
- macro agent 只在 macro 层内部比较表现。
- 非 macro agent 继续使用 recommendation performance / Darwinian weight。
- 如果 macro 最近已经被优化过，则优先选择其他层。
- dynamic quota 暂不进入 MVP，避免同时引入太多选择策略变量。

频率示例：

```text
每天跑 1 次 autoresearch，macro_quota = 20%:
  约每 5 天选择 1 次 macro

每天跑 1 次 autoresearch，macro_quota = 25%:
  约每 4 天选择 1 次 macro

每周跑 1 次 autoresearch，macro_quota = 20%:
  约每 5 周选择 1 次 macro

每天跑 2 次 autoresearch，macro_quota = 20%:
  约每 2.5 天选择 1 次 macro
```

### 约束组合

当前约束和新增 macro 约束的优先级：

```text
1. monthly_modification_cap_per_cohort
2. force_agent idempotency / branch idempotency
3. force_agent cooldown
4. macro quota / min_macro_interval_days
5. per-agent cooldown
6. per-agent recent-revert penalty
```

`monthly_modification_cap_per_cohort = 100` 在每天 1 次 autoresearch 时基本不绑定，但仍保留为全局 safety cap。

### 静态 quota 选择规则

选择时先判断 macro quota 是否允许，再在 macro 层内部选择最弱且不在 cooldown、且没有 recent-revert penalty 的 agent。

```text
if macro quota allows and macro has eligible weak candidate:
    choose worst eligible macro agent by mean_raw_macro_score_5d percentile
else:
    choose worst eligible non-macro agent by existing recommendation/Darwinian metric
```

这里的 "worst" 都是 within-layer ranking，不直接比较 macro score 和 recommendation alpha。

### 动态 quota follow-up

动态 quota 等 MVP 跑通后再启用。建议使用 trailing window，例如最近 30 次 autoresearch。

```text
base_macro_quota = 20%
min_macro_quota = 10%
max_macro_quota = 30%
```

```text
if macro_samples_insufficient:
    macro_quota = min_macro_quota
elif recent_macro_mutations_mostly_reverted:
    macro_quota = min_macro_quota
elif macro_layer_raw_score_is_bad and macro_influence_is_high:
    macro_quota = max_macro_quota
else:
    macro_quota = base_macro_quota
```

同时加入 per-agent recent-revert penalty，避免同一个 agent 在 cooldown 结束后被反复选中又反复 revert。

## Mutator 上下文

现有 TS mutator 会读取：

- `scorecard.list_skill`
- `darwinian.get_weights`

这对 macro agent 不合适，因为 macro 没有 recommendation score。

新增 macro 评分后，mutator 应该：

- 判断 agent 是否属于 macro layer。
- macro agent 使用 `scorecard.list_macro_skill`。
- 非 macro agent 继续使用现有 `scorecard.list_skill` 和 `darwinian.get_weights`。

macro prompt 的 performance blurb 示例：

```text
raw_macro_score_5d=-0.0041, hit_rate_5d=42%, n_obs=21,
effective_macro_score_5d=null, influence_equal=null
```

这样 LLM 看到的是 macro 自己的错误类型，而不是 misleading 的 "no recent data"。

## Keep/Revert 逻辑

不建议用 macro hit rate 或 effective macro score 直接决定 keep/revert。

建议保持：

```text
keep/revert = based on full portfolio backtest delta_sharpe
```

原因：

- macro 是上游信号，最终价值体现在组合行为。
- 一个 macro prompt 可能提高 hit rate，但让下游组合变差。
- 一个 macro prompt 可能方向命中率一般，但让极端风险处理更稳。
- 最终保留标准应该服务于 portfolio Sharpe，而不是局部 proxy。

因此：

- macro score 用于选择和 mutator 反馈。
- backtest delta Sharpe 用于最终保留。

## 通用 Darwinian Weight 表

长期目标改为和上游一致：所有 agent 共用一张 `darwinian_weights` 表。macro 不再新增单独的 weight 表；macro、sector、superinvestor、decision agents 都是同一套 Darwinian weight registry 里的 rows。

这不是 MVP 范围。它会改变现有 recommendation agents 的工作子系统，必须单独 backtest/gate 后再启用。

复核当前代码后，Layer 1 aggregator 的实际公式是：

```text
score = sum(vote_i * confidence_i) / sum(confidence_i)
```

这等价于：

```text
darwinian_weight_i = 1.0 for every macro agent
```

也就是说，当前 macro agents 的长期权重是固定等权的；当天影响力只由该 agent 自己输出的 `confidence` 决定。目标方案是让 Layer 1 也读取同一张 `darwinian_weights` 表。

### Darwinian weight 定义

Darwinian weight 不是 `weight = f(Sharpe)` 的确定函数。Sharpe、alpha score、macro score 都只是 performance ranking 的输入；最终权重是一个随时间逐步演化的 state。

统一更新规则采用上游公式：

```text
previous_weight = latest darwinian_weights[agent].weight or 1.0

if agent in top_quartile_performers:
    weight = min(2.5, previous_weight * 1.05)
elif agent in bottom_quartile_performers:
    weight = max(0.3, previous_weight * 0.95)
else:
    weight = previous_weight
```

边界：

```text
start = 1.0
floor = 0.3
ceiling = 2.5
```

这个规则本身是逐步演化的：

```text
持续 top quartile:    1.0 -> 2.5 约需 19 个交易日
持续 bottom quartile: 1.0 -> 0.3 约需 24 个交易日
```

启用条件：

```text
darwinian_weight_rewrite_enabled = false by default
```

打开前必须完成：

- 对现有 recommendation agents 做回归 backtest。
- 对比旧 `clip(0.5 + rolling_sharpe_30)` 和新乘法演化的权重分布。
- 验证 `autonomous_execution` sizing context 没有明显回归。
- 验证 Layer 1 加权开启后组合 backtest 没有明显回归。

### 单表 schema 语义

需要把当前 `darwinian_weights` 从 "recommendation Sharpe weight 表" 迁移成通用 agent Darwinian weight 表。表名保留，但字段语义扩大：

```text
darwinian_weights
  cohort
  agent
  layer                    -- macro / sector / superinvestor / decision
  date
  weight
  previous_weight
  performance_metric       -- raw_macro_score_5d / alpha_5d / portfolio_contribution 等
  performance_value        -- 当天用于排名的原始表现值
  normalized_performance   -- 可选，用于跨 metric/rank_scope 排名
  rank_scope               -- macro / recommendation / decision / global
  quartile                 -- 1 top ... 4 bottom
  update_action            -- up / down / unchanged / skipped
  n_obs
  source_table             -- macro_signals / recommendations / backtest_runs 等
  source_date
  updated_at
```

当前旧字段 `rolling_sharpe_30` / `rolling_sharpe_90` 可以为了兼容暂时保留为 nullable diagnostics，但不能再作为 weight 的定义公式。

### Performance ranking

同一张表不代表所有 agent 必须共用同一个原始 metric。每类 agent 可以有自己的 performance source，但都产出同一套 Darwinian update fields：

```text
macro agents:
  source_table = macro_signals
  performance_metric = raw_macro_score_5d
  performance_value = matured raw_macro_score_5d

recommendation agents:
  source_table = recommendations
  performance_metric = alpha_5d 或 rolling_alpha_score
  performance_value = 当天用于排名的 recommendation performance

decision agents:
  source_table = backtest_runs / portfolio attribution
  performance_metric = portfolio_contribution 或 delta_sharpe contribution
  performance_value = 当天用于排名的 decision performance
```

`top_quartile_performers` 和 `bottom_quartile_performers` 由 `performance_value` 或 `normalized_performance` 排名得到。初期建议使用 `rank_scope` 避免不同 raw metric 直接混排；如果后续实现了可比的 `normalized_performance`，可以把 `rank_scope` 扩展为 `global`，更接近上游的 flat `final_agent_weights`。

小样本保护：

```text
min_ranked_agents_per_scope = 8
min_scored_observations_per_agent = 10
min_matured_agents_for_update = 8
```

如果某个 `rank_scope` 里满足条件的 agent 太少，则不做 top/bottom quartile 更新，所有 agent 保持 previous weight。macro 层只有 10 个 agent，必须避免每天 2-3 个 agent 因噪声反复乘以 1.05/0.95。

更新节奏：benchmark 标签下 10 个 macro agent 每天同时产生信号、5 个交易日后同批成熟，所以 macro 层权重是**按批**更新而非每日连续更新；若某批成熟且可比的 agent 数 < `min_matured_agents_for_update`，则整批跳过、全部保持 previous weight。引入 agent-specific labels 后 neutral/missing 增多会让更新更稀疏——这只影响 Phase 9 的 Darwinian 演化速度，不影响 MVP（MVP 不迁移 darwinian_weights）。

反馈环保护：

```text
macro Darwinian ranking 使用 raw_macro_score_5d。
influence_weight_equal 只做 diagnostics。
如果未来要使用 influence-adjusted score，influence 必须按 equal weights 或 signal_date frozen weights 计算。
```

不能让同一天的链路变成：

```text
weight -> consensus -> influence -> performance -> weight
```

### 更新节奏

recommendation agents 的 performance 在 recommendation forward return 成熟后更新。macro agents 因为 `raw_macro_score_5d` / `effective_macro_score_5d` 都需要未来 5 个交易日标签，所以权重更新发生在 scoring pass 里，而不是信号产生当天立即更新：

```text
每天 ingest macro signal
未来 5 个交易日后评分 macro signal
评分成熟后，写入 performance_value
按 rank_scope 计算 top/bottom quartile
把所有 eligible agents 的新 weight upsert 到 darwinian_weights
```

样本尚未成熟或没有可比较 performance 时：

```text
weight = previous_weight
```

如果没有 previous weight，则使用 `1.0`。

### Keep/Revert 对 Darwinian weight 的影响

prompt mutation 的 keep/revert 不直接修改 Darwinian weight。

原因：

- keep/revert 是 prompt 变更的整体组合表现，不完全等同于 agent 原始信号质量。
- Darwinian weight 由成熟后的 performance ranking 自然演化。
- 如果 prompt 真的变好，后续 performance 会反映出来，weight 会自然上升。

### Layer 1 consensus 的使用方式

Layer 1 aggregator 从 `darwinian_weights` 读取 macro agents 在当前日期之前的最新 weight：

```text
score =
  sum(vote_i * confidence_i * darwinian_weight_i)
  / sum(confidence_i * darwinian_weight_i)
```

stance 规则：

```text
score > +0.3 => BULLISH
score < -0.3 => BEARISH
otherwise    => NEUTRAL
```

如果自然演化后的权重使 macro stance 翻转，这是允许的，因为它表达了不同 macro 信息渠道长期表现的差异。

同时保留原始 confidence 和 Darwinian weight，方便诊断：

```text
agent
vote
confidence
darwinian_weight
weighted_vote
score
```

这样可以看到一个 macro agent 影响 consensus 是因为：

- 它本身 confidence 高。
- 它长期表现好，所以 Darwinian weight 高。
- 它的 vote 和其他 agent 形成共识。

### 原则

Darwinian weight 的核心原则：

```text
一张表记录所有 agent 的演化权重；
不同 agent 可以有不同 performance source；
weight 统一按 top/bottom quartile 乘法演化；
不使用 Sharpe 或 macro score 直接映射成 weight；
不做额外压缩、总量固定或 stance flip guard。
```

## 初步实施计划

### Phase 1: 持久化 macro signal

改动：

- 在 Python scorecard store 中新增 `macro_signals` 表。
- 新增 `expand_state_to_macro_signals(state)`。
- 在 `scorecard.append` 中同时调用 recommendation ingest 和 macro signal ingest。
- 返回值保留 `ingested`，新增 `macro_ingested`。

测试：

- Layer 1 macro outputs 不进入 `recommendations`。
- Layer 1 macro outputs 进入 `macro_signals`。
- 重复 ingest 不产生重复行。
- 缺失 `as_of_date` 时报错。

### Phase 2: macro scoring

改动：

- 在 scorer 中新增 pending macro signal 查询。
- MVP 只计算 benchmark 5d direction label。
- 根据 benchmark label 计算 `realized_label`、`hit_5d`、`raw_macro_score_5d`。
- 写入 `label_type=benchmark_5d`、`label_source_status=primary`。
- 暂不计算 agent-specific primary label。
- 暂不把 influence-adjusted score 作为主评分。
- `score_pending` 同时返回 recommendation 和 macro scoring counts。

测试：

- bullish vote 遇到 benchmark 上行得正分。
- bearish vote 遇到 benchmark 下行得正分。
- neutral vote 遇到小幅波动得正分。
- neutral vote 遇到大幅波动得负分。
- benchmark 数据缺失时标记 skipped/missing，不无限 pending。

### Phase 3: macro skill RPC

改动：

- 新增 `scorecard.list_macro_skill`。
- 返回 `mean_raw_macro_score_5d`、`mean_effective_macro_score_5d`、`hit_rate_5d`、`mean_influence_weight_equal`、`sharpe_window`、`n_obs`。
- TS bridge 增加类型和 wrapper。

测试：

- 空表返回空 rows。
- 聚合结果正确。
- n_obs 小于最小样本时 Sharpe 为 null。

### Phase 4: autoresearch layer-aware selection

改动：

- 修改 Python `mosaic/bridge/handlers/autoresearch.py::_select_agent`。
- `_select_agent` 不再把 macro 的缺失 recommendation performance 当成 0 直接混排。
- 对 macro 使用 macro skill 在 macro 层内排序。
- 对非 macro 使用现有 Darwinian weights。
- MVP 增加 static quota config：

```text
autoresearch.macro_quota = 0.2
autoresearch.min_macro_interval_days = 5
autoresearch.macro_neutral_band = 0.005
autoresearch.recent_revert_penalty_days = 14
```

`autoresearch.macro_neutral_band` 是**唯一**口径来源：Phase 2 的 Python scorer（realized_label 分桶 + `neutral_band_norm` 换算）和 Phase 4 的 selection 都必须读同一个 config 键，不得各自硬编码 0.005，避免评分口径和选择口径漂移。

MVP 选择逻辑：

```text
if static macro quota allows and macro has eligible weak candidate:
    choose worst eligible macro agent by mean_raw_macro_score_5d percentile
else:
    choose worst eligible non-macro agent by existing metric
```

测试：

- static macro quota 允许时可以选择 macro。
- macro 最近刚优化过时不选 macro。
- recent-revert penalty 生效时不选同一个 macro agent。
- macro raw score 不直接和 recommendation raw performance 混排。
- force_agent 仍然可用，但仍受 cooldown 约束。

### Phase 5: TS mutator performance context

改动：

- 在 mutator 中识别 macro agent。
- macro agent 调 `scorecardListMacroSkill`。
- 非 macro agent 保持现状。

测试：

- macro agent 有 macro skill 时，performance blurb 包含 macro score/hit rate。
- macro agent 无数据时，返回 macro cold start 文案。
- 非 macro agent 行为不变。

### Phase 6: integration test and provenance

改动：

- 增加一条跨阶段集成测试：
  ingest -> mature/score -> list_macro_skill -> autoresearch.trigger 选择 macro -> mutate -> evaluate -> keep/revert by delta_sharpe。
- 确保 macro mutation 记录 `prompt_repo_id` 和 `prompt_sha256`。
- 确保 evaluator 按相同 `prompt_repo_id` 比较 baseline 和 mutation。

测试：

- `prompt_repo_id=private` 的 macro mutation 只和同 repo baseline 比较。
- macro skill rows 能驱动 Python `autoresearch.trigger` 选择目标 agent。
- keep/revert 不读取 macro hit rate，仍由 portfolio delta Sharpe 决定。

### Phase 7: agent-specific labels follow-up

改动：

- 为每个 agent-specific label 建立 data source inventory。
- 只有 `available_now=yes` 的 label 可以进入 primary path。
- 不可用 label 必须写 `label_source_status=deferred` 或走 `benchmark_fallback_5d`。
- `institutional_flow` / `news_sentiment` 对齐当前主力资金流/行业资金流，不回退到已知时效问题的 northbound-flow 风格信号。

测试：

- 每个 primary label 都能追溯到具体 data source。
- data source 缺失时写入 fallback label_type。
- fallback 不会被误记成 agent-specific label。

### Phase 8: influence diagnostics follow-up

改动：

- 计算 `influence_weight_equal`。
- 保留 `effective_macro_score_5d = influence_weight_equal * raw_macro_score_5d` 作为 diagnostics。
- 默认选择仍看 `mean_raw_macro_score_5d`。
- 如果启用 influence-aware selection，必须有 raw-score fallback 或 influence floor。

测试：

- influence 使用 equal weights 或 signal-date frozen weights。
- 低 influence 但 raw score 长期很差的 agent 仍能被选择。
- influence-adjusted score 不参与 Darwinian ranking。

### Phase 9: unified Darwinian weight table gated follow-up

改动：

- 迁移 `darwinian_weights` 为通用 agent Darwinian weight 表。
- 在同一张表里写入 macro、sector、superinvestor、decision agents 的 weights。
- 废弃 `weight = clip(0.5 + rolling_sharpe_30)` 作为目标定义。
- 按上游规则更新 weight:
  top quartile `* 1.05`，bottom quartile `* 0.95`，middle unchanged。
- weight 从 `1.0` 起步，限制在 `[0.3, 2.5]`。
- macro rows 使用 `performance_metric=raw_macro_score_5d`。
- recommendation rows 使用 recommendation performance metric。
- Layer 1 aggregator 从 `darwinian_weights` 读取 macro agents 的最新 weight。
- 输出 per-agent vote diagnostics，包含原始 confidence、Darwinian weight 和 weighted vote。
- 默认 feature flag 关闭。

建议配置：

```text
darwinian.weight_rewrite_enabled = false
darwinian.weight_start = 1.0
darwinian.weight_floor = 0.3
darwinian.weight_ceiling = 2.5
darwinian.top_multiplier = 1.05
darwinian.bottom_multiplier = 0.95
darwinian.min_ranked_agents_per_scope = 8
darwinian.min_scored_observations_per_agent = 10
darwinian.min_matured_agents_for_update = 8
```

测试：

- top quartile agent 的 Darwinian weight 乘以 1.05。
- bottom quartile agent 的 Darwinian weight 乘以 0.95。
- middle quartiles 不变。
- Darwinian weight 不低于 0.3、不高于 2.5。
- 样本不足且没有 previous weight 时使用 1.0。
- 样本不足但有 previous weight 时保持旧值。
- `darwinian.get_weights` 能返回 macro 和非 macro rows，并带 layer/metric metadata。
- Layer 1 aggregator 的 weighted score 正确。
- Darwinian weight 可以改变 Layer 1 stance。
- keep/revert 不会直接造成 weight 跳变。
- 新旧 recommendation weighting backtest 对比无明显回归。

## 风险和后续优化

### 风险 1: scope 过大

macro_signals、agent-specific labels、influence diagnostics、adaptive quota、Darwinian rewrite、Layer 1 加权都是独立风险点。MVP 只落 Phases 1-6；后续能力必须分 gate。

### 风险 2: feedback loop

如果 Layer 1 consensus 使用 Darwinian weight，而 influence 又从 weighted consensus 计算，再用 influence-adjusted score 更新 Darwinian weight，就会形成：

```text
weight -> consensus -> influence -> score -> weight
```

缓解方式：

- MVP 不使用 influence 作为主评分。
- Darwinian ranking 使用 `raw_macro_score_5d`。
- influence 只按 equal weights 或 signal-date frozen weights 计算。

### 风险 3: Darwinian rewrite 回归

把 recommendation agents 从 `clip(0.5 + rolling_sharpe_30)` 改成上游式 `*1.05/*0.95` 会改变现有 live subsystem。这个改动和 macro autoresearchable 是正交问题。

缓解方式：

- feature flag 默认关闭。
- 单独 backtest 新旧 recommendation weighting。
- 验证 `autonomous_execution` sizing context 没有明显回归。
- 验证 Layer 1 加权打开后组合表现没有明显回归。

### 风险 4: 小样本 quartile 噪声

macro 只有 10 个 agents；top/bottom quartile 每次大约 2-3 个 agent，容易被噪声驱动。

缓解方式：

```text
min_ranked_agents_per_scope = 8
min_scored_observations_per_agent = 10
min_matured_agents_for_update = 8
```

不满足条件时保持 previous weight。

### 风险 5: 低影响力死区

如果 selection 只看 `effective_macro_score_5d = influence * raw`，一个长期很差但很少影响 consensus 的 agent 会接近 0，可能永远不是最差。

缓解方式：

- MVP selection 使用 `mean_raw_macro_score_5d`。
- influence-aware selection 必须有 raw-score fallback 或 influence floor。

### 风险 6: agent-specific label 数据不可用

很多专属标签需要额外 instrument / series。没有数据源时不能静默 fallback 后仍标记成专属标签。

缓解方式：

- 每个 label 都必须列出 data source。
- `label_source_status` 必须写入 `primary`、`fallback`、`missing` 或 `deferred`。
- `institutional_flow` / `news_sentiment` 对齐当前主力资金流/行业资金流，不回退到已知时效问题的数据源。

### 风险 7: 频率控制叠加

当前已有 `agent_mutation_cooldown_hours=24` 和 `monthly_modification_cap_per_cohort=100`。新增 `min_macro_interval_days`、macro quota、recent-revert penalty 后，必须明确优先级。

缓解方式：

- Python `autoresearch.trigger` 是唯一 selection/constraint source of truth。
- monthly cap 先执行，macro quota 和 min interval 后执行。
- monthly cap 在 1/day 下基本不绑定，但作为 safety cap 保留。

### 风险 8: repeated revert

仅靠 layer-level quota 会反复选择同一个低分 agent，尤其在 cooldown 结束后。

缓解方式：

- selection 加 per-agent recent-revert penalty。
- penalty 不阻止 force_agent，但 force_agent 仍受 cooldown。

### 风险 9: 跨阶段 contract drift

单阶段测试可能覆盖不到 label_type、prompt_repo_id、selection、evaluator 的组合问题。

缓解方式：

- 增加 ingest -> score -> list_macro_skill -> trigger -> mutate -> evaluate -> keep/revert 集成测试。

### 风险 10: prompt provenance

evaluator 会按 `prompt_repo_id` 过滤 baseline。macro mutation 必须记录相同 prompt repo，否则比较对象不一致。

缓解方式：

- macro_signals、prompt_versions、backtest_runs 都保留 prompt provenance。
- `prompt_repo_id=private` 的 mutation 只和 private baseline 比较。

## 推荐决策

以 MVP-first 为准，采用以下原则：

```text
1. macro 不写 recommendations。
2. 新增 macro_signals。
3. MVP 使用 benchmark 5d direction 作为主标签。
4. MVP 计算 hit_rate_5d 和 raw_macro_score_5d。
5. MVP selection 使用 mean_raw_macro_score_5d，不使用 influence-adjusted score。
6. Python autoresearch.trigger/_select_agent 实现 layer-aware selection。
7. MVP 使用 static macro_quota=20% 和 min_macro_interval_days=5。
8. keep/revert 仍然只看 portfolio backtest delta_sharpe。
9. 默认每次 autoresearch 仍然只调整 1 个 agent。
10. agent-specific labels 是 follow-up，必须先通过 data source inventory。
11. influence diagnostics 是 follow-up，必须避免 weight -> influence -> weight 反馈环。
12. adaptive macro quota 是 follow-up，并加入 per-agent recent-revert penalty。
13. unified darwinian_weights 是 gated follow-up，不和 macro MVP 同时落地。
14. Darwinian rewrite 使用上游规则:
    start=1.0, top_quartile*=1.05, bottom_quartile*=0.95, floor=0.3, ceiling=2.5。
15. Layer 1 consensus 读取 darwinian_weights 是最后一个 gate，必须先验证 recommendation weighting 无回归。
```

这个方案先把 macro 纳入 autoresearch，避免一次性改动多个 live subsystem；后续再把权重语义迁移到上游式 flat `final_agent_weights`。

# MOSAIC Prompt Evolution × Research Knowledge Engine 落地主计划 v1.1

> Version: v1.1 integrated master plan  
> Date: 2026-06-05  
> Scope: Prompt Evolution, Research Knowledge Engine, Empirical Validation Hardening, Runtime Rule Aggregation, Confidence Policy, Production Promotion  
> Status: 主计划 / 可进入 Phase -1 和 Phase 0 落地

---

## 0. Executive Summary

MOSAIC 的下一阶段不应继续依赖“金融常识 + LLM 即兴推理”来判断市场走势、经济形势或投资机会。金融常识可以作为初始语言框架，但不能作为生产级研究规则。真正需要建设的是一个可审计、可验证、可回滚、可持续演化的研究规则系统。

本计划把三条线整合成一个主系统：

```text
Prompt Evolution
    解决 agent prompt 的职责边界、证据绑定、输出结构和 mutation 可控性。

Research Knowledge Engine, RKE
    把文献、研报、产业资料、政策文件和 MOSAIC 历史经验转成结构化研究资产。

Validation Hardening
    防止 empirical validator 自身过拟合，避免把 data-mining 噪声包装成“已验证规则”。
```

最终目标不是让 LLM “更像分析师”，而是让 LLM 成为研究框架的执行器：

```text
研究资料 → source-grounded claim → hypothesis → rule pack → parameter prior
        → pre-registered validation → paper trading → staged promotion
        → Prompt IR / Agent Runtime / Confidence Policy 更新
        → monitoring / alpha decay / rollback
```

v1.1 的核心变化是：

```text
先证明 validation 可信，
再冻结 schema，
再扩展 claim、rule、graph、mutator。
```

原先 RKE 计划的核心赌注是“把信任从 LLM 直觉转移到历史验证”。这个方向是对的，但如果 validator 没有统计显著性控制、有效样本量控制、overlap 控制、多重检验校正、walk-forward、lockbox 和成本约束，它会把随机噪声洗成高可信规则。因此，本主计划把 hardened empirical validation 设为 production promotion 的前置门槛。

---

## 1. 一句话原则

```text
文献不是结论。
研报不是交易信号。
LLM 不是研究规则的最终来源。
Backtest 不是最终真理。
Production forward monitoring 才是最终裁判。
```

进入 MOSAIC 生产系统的，必须是：

```text
被结构化的产业逻辑；
被标注适用条件和失效模式的经济规律；
被映射到可获得 PIT 数据的机制变量；
被 pre-registered validation 检验过的规则和参数；
被 runtime checker 约束过的 prompt / rule / output；
被 live monitoring 持续追踪的 production rule。
```

---

## 2. 当前问题与升级方向

### 2.1 当前问题

当前 MOSAIC prompt 已经具备角色说明、工具列表、工作流程、输出 schema 和写作约束，但很多 agent 的核心推理仍依赖 LLM 在运行时自行判断。这会带来五类问题：

1. **结论不稳定**：同一批数据可能在不同运行中被解释成不同方向。
2. **证据不可追踪**：输出结论不一定绑定到工具、指标、数值、日期和数据新鲜度。
3. **演化不可控**：autoresearch 无法判断 mutation 改善的是规则、阈值、fallback，还是只是文风。
4. **评价不闭环**：全文重写 prompt 无法积累“哪些规则有效、哪些规则无效”的经验。
5. **验证伪可靠**：如果 empirical validator 过拟合，系统会把 data-mining 噪声包装成可审计规则。

### 2.2 升级方向

MOSAIC 需要从：

```text
LLM 根据金融常识生成分析
```

升级为：

```text
研究资料和历史数据生成候选机制；
候选机制转成 rule pack 和 parameter prior；
规则和参数先通过受控实验验证；
验证通过后以 module-level patch 接入 Prompt IR 和 Agent Runtime；
生产表现持续监控，失效后降级或回滚。
```

### 2.3 信任层级

系统内的信任级别从低到高为：

```text
LLM free-form statement
    < LLM hypothesis with explicit uncertainty
    < source-grounded claim with span citation
    < rule pack compiled from multiple claims
    < parameter prior supported by literature and domain logic
    < pre-registered validation result
    < walk-forward / OOS result
    < paper-trading result
    < monitored production rule
```

任何模块不得把低信任对象伪装成高信任对象。

---

## 3. 系统总架构

### 3.1 Integrated Architecture

```text
Research Corpus
    ↓
Source Metadata Registry
    ↓
Claim Extraction Pipeline
    ├─ Source-Grounded Claim Ledger
    └─ Hypothesis Ledger
    ↓
Claim Checker + Span-Grounded Verifier + Gold Set Evaluation
    ↓
Rule Pack Compiler
    ↓
Parameter Prior Generator
    ↓
Data Availability Matrix Gate
    ↓
Validation Experiment Registry
    ↓
Hardened Empirical Validator
    ├─ pre-registration
    ├─ effective sample size
    ├─ overlap control
    ├─ multiple testing correction
    ├─ walk-forward validation
    ├─ lockbox test
    ├─ cost-aware acceptance
    └─ regime partial pooling
    ↓
Mutation Planner
    ↓
Patch Validator
    ↓
Prompt IR / Rule Pack Registry / Agent Runtime
    ↓
Runtime Rule Aggregation + Confidence Policy
    ↓
Paper Trading
    ↓
Staged Production Promotion
    ↓
Monitoring + Alpha Decay + Rollback
```

### 3.2 组件职责

| 组件 | 职责 | 不能做什么 |
|---|---|---|
| research_ingestor | 导入论文、研报、政策文件、产业材料，生成 metadata | 不得改变源文含义 |
| claim_extractor_agent | 提取 source-grounded claim 和 hypothesis | 不得把假设标成源文事实 |
| claim_checker | 检查 claim 字段、source span、变量映射 | 不得替代人工 gold set |
| span_grounded_verifier | 验证 claim 是否真的被 source span 支持 | 不得验证未提供 span 的字段 |
| rule_pack_compiler | 把 claims / hypotheses 编译成规则对象 | 不得 promotion 未验证规则 |
| parameter_prior_generator | 生成阈值、窗口、权重、cap 的候选范围 | 不得直接改生产参数 |
| empirical_validator | 受控验证规则和参数 | 不得忽略多重检验和成本 |
| mutation_planner | 生成 module-level patch proposal | 不得改 forbidden paths |
| prompt_checker | 验证 Prompt IR、output schema、evidence binding | 不得根据收益放松 schema |
| runtime_rule_aggregator | 合成多条 rule 输出，处理冲突和相关性 | 不得重复计算相关规则确认 |
| confidence_engine | 计算 conservative confidence 和 actionability | 不得让 research-only 直接 actionable |
| production_monitor | 监控 live 表现、alpha decay、rollback | 不得把 backtest 当最终真理 |

---

## 4. 设计原则

### 4.1 文献和研报只能作为 prior，不能直接作为 signal

研报中的一句“政策支持半导体国产替代”不能直接变成“看多半导体”。它必须拆成：

```text
机制链条
    → 变量映射
    → 适用条件
    → 失效模式
    → 可观测 proxy
    → 参数候选
    → validation experiment
```

### 4.2 Claim 分两层：源文支持 vs 假设补充

LLM 提取时必须区分：

```text
source_grounded_fields:
    源文直接支持，必须有 source_span_id，可逐句核对。

hypothesis_fields:
    分析师或 LLM 基于源文提出的补充假设，不声称来自源文。
```

例如 failure_modes 通常不是源文明确写出的内容，不能强迫 LLM “补完整”后伪装成源文事实。它应进入 hypothesis layer，并被单独验证。

### 4.3 受控推理优先于自然语言聪明

LLM 可以：

```text
- 抽取 claim；
- 组织证据；
- 总结分歧；
- 提出候选机制；
- 解释冲突和不确定性；
- 生成 experiment proposal。
```

LLM 不可以：

```text
- 直接 promotion 未验证规则；
- 直接提高 production confidence；
- 直接修改 CIO sizing；
- 删除 evidence ledger；
- 修改 output schema；
- 把回测噪声包装成规则。
```

### 4.4 PIT 是必要条件，不是充分条件

`source.publish_date <= decision_date` 只能防止数据侧 lookahead，不能消除规则设计侧 hindsight。

变量选择、metric proxy、failure mode 和参数候选范围，都可能被今天的后见之明污染。因此必须加入：

```text
pre-registration
specification freeze
out-of-time holdout
walk-forward validation
lockbox test
paper trading
production monitoring
```

### 4.5 Validation 是模型，不是过滤器

Empirical validator 自身也是一个会过拟合的模型。它必须接受与预测模型相同级别的治理：

```text
experiment family 管理
多重比较校正
有效样本量计算
overlap correction
成本和换手惩罚
OOS / walk-forward
lockbox 一次性使用
live degradation monitoring
```

---

## 5. 核心数据对象

### 5.1 Research Source Metadata

```json
{
  "source_id": "SRC-20260605-0001",
  "source_type": "sell_side_report",
  "title": "Semiconductor Equipment Localization Deep Dive",
  "institution": "example_securities",
  "author": "research_team",
  "publish_date": "2026-05-28",
  "ingest_time": "2026-06-05T10:00:00+09:00",
  "market": "A-share",
  "asset_class": "equity",
  "sector": "semiconductor",
  "coverage": ["equipment", "materials", "foundry"],
  "method": "industry_research",
  "has_data_table": true,
  "has_backtest": false,
  "license_status": "pending_review",
  "point_in_time_available": true,
  "source_hash": "sha256:..."
}
```

必填治理字段：

```text
source_id
source_type
publish_date
ingest_time
license_status
point_in_time_available
source_hash
```

### 5.2 Source-Grounded Claim

```json
{
  "claim_id": "CLAIM-SEMICON-20260605-0001",
  "source_id": "SRC-20260605-0001",
  "source_span_id": "PAGE-12-PARA-3",
  "claim_type": "causal_mechanism",
  "source_grounded": true,
  "claim_text": "出口限制提高国产设备验证优先级。",
  "source_grounded_fields": {
    "cause_variables": ["export_control_intensity"],
    "target_variables": ["domestic_equipment_validation_priority"],
    "direction": "positive",
    "expected_horizon_text": "中期"
  },
  "unsupported_fields": [],
  "extraction_confidence_bin": "medium",
  "verifier_status": "pending",
  "human_review_required": true
}
```

### 5.3 Hypothesis Object

```json
{
  "hypothesis_id": "HYP-SEMICON-20260605-0001",
  "derived_from_claim_ids": ["CLAIM-SEMICON-20260605-0001"],
  "hypothesis_type": "failure_mode",
  "statement": "如果估值分位已高于 90%，政策催化对未来 20d alpha 的增益可能下降。",
  "not_source_grounded": true,
  "requires_validation": true,
  "proposed_metric_proxies": [
    "valuation_percentile_3y",
    "sector_forward_alpha_20d"
  ],
  "status": "draft"
}
```

### 5.4 Data Availability Matrix

任何 metric proxy 在进入 validation 前，都必须先进入数据可用性矩阵。

```json
{
  "metric_proxy": "pboc_net_injection_7d",
  "data_source": "official_pbooc_or_vendor",
  "point_in_time_available": true,
  "history_start": "2015-01-01",
  "history_end": "2026-06-05",
  "vintage_handling": "as_reported",
  "restatement_risk": "low",
  "survivorship_bias_risk": "none",
  "timestamp_granularity": "daily",
  "known_biases": [],
  "allowed_for_validation": true,
  "allowed_for_production": true,
  "notes": "Use publication time, not calendar date only."
}
```

文本派生指标必须额外标注：

```text
是否有历史语料；
是否带原始时间戳；
是否能重建当时的可见文档集合；
是否存在后补标签；
是否存在 survivorship / coverage drift。
```

拿不到真实 PIT 的 proxy，对应规则只能停留在 paper / experiment mode，不能 promotion。

### 5.5 Rule Pack

```yaml
rule_id: sector.semiconductor.soft.014
rule_pack_id: sector.semiconductor.policy_substitution.v1
agent_id: sector.semiconductor
rule_type: soft
status: candidate
source_claim_ids:
  - CLAIM-SEMICON-20260605-0001
hypothesis_ids:
  - HYP-SEMICON-20260605-0001
mechanism_chain:
  - export_control_intensity
  - domestic_substitution_policy
  - equipment_validation_demand
  - semiconductor_equipment_revenue_expectation
predicate:
  all:
    - metric: policy_news_count_20d
      operator: ">"
      parameter: policy_news_threshold
  at_least_one:
    - metric: equipment_order_mentions_60d
      operator: ">"
      parameter: order_confirmation_threshold
    - metric: semiconductor_etf_flow_20d
      operator: ">"
      parameter: etf_flow_threshold
inference:
  target: semiconductor_sector_score
  direction: positive
  horizon:
    min_days: 20
    max_days: 60
confidence_policy:
  cap_if:
    - condition: only_policy_news_without_flow_or_order_confirmation
      confidence_cap: 0.60
learnable_parameters:
  policy_news_threshold:
    value: 3
    type: integer
  order_confirmation_threshold:
    value: 2
    type: integer
  etf_flow_threshold:
    value: 0.01
    type: float
  confirmation_window:
    value: 20
    unit: d
validation_status: pending
```

### 5.6 Parameter Prior

```json
{
  "parameter_proposal_id": "PARAM-CB-20260605-0001",
  "agent_id": "macro.central_bank",
  "target_path": "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value",
  "current_value": 5,
  "candidate_values": [5, 10, 20],
  "prior_source_claim_ids": ["CLAIM-CB-20260605-0001"],
  "prior_hypothesis_ids": [],
  "rationale": "多份研究资料认为公开市场操作对风险偏好的影响需要窗口确认。",
  "validation_required": true,
  "status": "candidate"
}
```

### 5.7 Validation Experiment v2

```json
{
  "experiment_id": "EXP-CB-20260605-0001",
  "experiment_family_id": "FAM-CB-LIQUIDITY-2026Q2",
  "pre_registered": true,
  "pre_registration_time": "2026-06-05T11:00:00+09:00",
  "frozen_spec_hash": "sha256:...",
  "agent_id": "macro.central_bank",
  "rule_ids": ["macro.central_bank.soft.001"],
  "parameter_paths": [
    "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value"
  ],
  "candidate_values": [5, 10, 20],
  "baseline_version": "prompt-ir-0.3.1",
  "candidate_version": "prompt-ir-0.3.2-exp",
  "data_requirements": {
    "point_in_time_required": true,
    "survivorship_bias_control_required": true,
    "as_reported_required": true,
    "metric_proxies": ["pboc_net_injection", "sector_return", "risk_appetite_proxy"]
  },
  "sampling_design": {
    "signal_unit": "independent_event",
    "horizon_days": 20,
    "overlap_policy": "non_overlapping_or_block_bootstrap",
    "minimum_effective_n": 60,
    "effective_n_method": "block_bootstrap"
  },
  "validation_design": {
    "walk_forward_required": true,
    "lockbox_required_for_final_promotion": true,
    "regime_evaluation_policy": "diagnostic_until_min_bucket_n",
    "partial_pooling_required": true
  },
  "multiple_testing_control": {
    "method": "benjamini_hochberg_fdr",
    "family_scope": "experiment_family",
    "max_fdr": 0.10
  },
  "acceptance_rule": {
    "primary_metric": "net_alpha_after_cost_20d",
    "min_effect_size": 0.01,
    "confidence_interval_must_exclude_zero": true,
    "cost_model_required": true,
    "turnover_not_worse_than": 0.20,
    "max_drawdown_not_worse_than": 0.02,
    "calibration_must_not_degrade": true
  },
  "promotion_policy": {
    "allow_direct_production": false,
    "next_state_if_pass": "paper_trading"
  }
}
```

### 5.8 Production Patch

```json
{
  "patch_id": "PATCH-CB-20260605-0001",
  "source_experiment_id": "EXP-CB-20260605-0001",
  "operation": "replace",
  "target_path": "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value",
  "old_value": 5,
  "new_value": 10,
  "allowed_by_evolution_targets": true,
  "validation_summary": {
    "net_alpha_after_cost_20d_delta": 0.013,
    "effective_n": 84,
    "fdr_adjusted_p_value": 0.07,
    "walk_forward_passed": true,
    "lockbox_passed": false,
    "promotion_state": "paper_trading"
  },
  "rollback_rule": {
    "metric": "live_net_alpha_after_cost_20d",
    "slow_decay_detection": true,
    "hard_trigger_delta_lt": -0.02,
    "review_window_trading_days": 60
  }
}
```

---

## 6. Prompt IR 与 Agent Runtime 集成

### 6.1 Prompt IR 新增字段

```yaml
agent_id: macro.central_bank
layer: macro
cohort: cohort_default
prompt_version: 0.3.2

role_contract:
  responsibility: Generate central-bank and liquidity regime signals.
  may_decide:
    - liquidity_regime
    - policy_window_signal
    - confidence_cap
  must_not_decide:
    - final_portfolio_sizing
    - single_stock_recommendation

tool_contract:
  required_tools:
    - name: get_pboc_ops
      freshness_max_days: 1
      required: true
  fallback_tools:
    - name: liquidity_proxy_from_rates
      confidence_cap: 0.60

research_rule_pack_refs:
  - macro.central_bank.liquidity.v1
  - macro.central_bank.policy_window.v1

confidence_policy_ref: confidence_policy.v1
rule_aggregation_policy_ref: rule_aggregation_policy.v1
output_schema_ref: agent_output_schema.v2
progress_event_schema_ref: progress_event.v1
handoff_schema_ref: downstream_handoff.v1

evolution_targets:
  allowed_paths:
    - /rule_packs/*/rules/*/learnable_parameters/*/value
    - /rule_packs/*/rules/*/confidence_policy/*
    - /rule_packs/*/rules/*/predicate/*
  forbidden_paths:
    - /role_contract
    - /tool_contract/required_tools
    - /output_schema_ref
    - /evidence_schema
    - /guardrails
```

### 6.2 Agent Runtime 输入

每次 agent 运行时，runtime 注入的是结构化上下文，而不是整篇研报：

```json
{
  "agent_id": "macro.central_bank",
  "runtime_date": "2026-06-05",
  "tool_outputs_normalized": [
    {
      "tool_call_id": "TC-001",
      "tool_name": "get_pboc_ops",
      "metric": "net_injection_7d",
      "value": 12500,
      "unit": "CNY 100mn",
      "as_of": "2026-06-05",
      "freshness_days": 0,
      "lookback_window_days": 7,
      "fallback": false,
      "quality_flags": []
    }
  ],
  "active_rule_packs": ["macro.central_bank.liquidity.v1"],
  "current_regime": {
    "risk_appetite": "neutral",
    "volatility": "normal",
    "liquidity": "supportive"
  },
  "rule_validation_scores": {
    "macro.central_bank.soft.001": {
      "validation_status": "paper_trading",
      "empirical_confidence_bin": "medium",
      "allowed_max_adjustment": 0.10
    }
  }
}
```

### 6.3 Agent 输出新增字段

```json
{
  "evidence_ledger": [],
  "research_rule_ids_used": [],
  "source_claim_ids_used": [],
  "hypothesis_ids_used": [],
  "inferences": [],
  "recommendations": [],
  "uncertainties": [],
  "confidence_components": {},
  "rule_aggregation_summary": {},
  "downstream_handoff": {},
  "progress_event": {}
}
```

---

## 7. Evidence Ledger 与 Claim Binding

### 7.1 Evidence Ledger

每个关键结论必须先进入 evidence ledger。

```json
{
  "evidence_id": "E1",
  "source_type": "tool_output",
  "source_tool": "get_pboc_ops",
  "metric": "net_injection_7d",
  "value": 12500,
  "unit": "CNY 100mn",
  "as_of": "2026-06-05",
  "lookback_window_days": 7,
  "freshness_days": 0,
  "direction": "liquidity_supportive",
  "fallback": false,
  "confidence_impact": "positive"
}
```

### 7.2 Claim-to-Inference-to-Recommendation Binding

输出必须形成链条：

```json
{
  "inferences": [
    {
      "inference_id": "I1",
      "statement": "流动性边际宽松，对风险偏好形成温和支持。",
      "evidence_ids": ["E1"],
      "rule_ids": ["macro.central_bank.soft.001"],
      "source_claim_ids": ["CLAIM-CB-20260605-0001"]
    }
  ],
  "recommendations": [
    {
      "recommendation_id": "R1",
      "statement": "允许下游 sector agent 对高 beta 成长风格给予小幅正向 prior，但必须等待资金或价格确认。",
      "inference_ids": ["I1"],
      "confidence": 0.61,
      "actionability": "watchlist_or_tiny_tilt"
    }
  ]
}
```

### 7.3 Claim Binding Validator

Reject output if:

```text
- any inference lacks evidence_ids;
- any inference lacks rule_ids;
- any recommendation lacks inference_ids;
- any high-confidence recommendation has fewer than two independent evidence sources;
- any evidence item lacks source_tool, metric, value, as_of, freshness, fallback;
- any final recommendation contains a claim absent from evidence ledger or inference list;
- any source_claim_id is cited as source-grounded without verifier_status passing required threshold.
```

---

## 8. Research Knowledge Pipeline

### 8.1 Research Corpus

资料库分层：

```text
1. 学术文献
2. 券商研报
3. 政策文件和监管资料
4. 行业协会和产业链资料
5. 上市公司公告、招股书、年报、调研纪要
6. 市场结构资料：ETF、资金流、持仓、交易所公告
7. MOSAIC 自有历史：agent 输出、mutation 记录、失败案例、人工复盘
```

### 8.2 Claim Extraction

抽取流程：

```text
source document
    → source spans
    → source-grounded claims
    → unsupported hypotheses
    → verifier
    → human review sample
    → gold set metrics
```

### 8.3 Claim Extraction Gold Set

Phase -1 必须建设人工标注 gold set。

```json
{
  "gold_set_id": "GOLD-CLAIM-2026Q2",
  "sample_size_documents": 50,
  "sample_size_claims": 500,
  "domains": ["central_bank", "dollar", "volatility", "semiconductor"],
  "metrics": {
    "claim_precision_min": 0.85,
    "source_span_support_precision_min": 0.90,
    "direction_accuracy_min": 0.85,
    "variable_mapping_accuracy_min": 0.80,
    "unsupported_field_false_grounding_max": 0.05
  },
  "gate": "schema_freeze_blocked_until_pass"
}
```

在 gold set 通过前，claim extraction 只能进入 research sandbox，不能影响 production prompt。

### 8.4 Rule Pack Compiler

Rule compiler 只能把下面对象编译成 candidate rule：

```text
- 至少一个 source-grounded claim；
- 零个或多个 explicitly marked hypotheses；
- 可用的 metric proxies；
- 明确的 valid conditions；
- 明确的 failure modes 或 unknown failure mode 标记；
- validation_required = true。
```

禁止：

```text
- 把单篇研报观点直接编译为 production rule；
- 把 hypothesis 标成 source-grounded；
- 把没有 PIT 数据的 proxy 编译到 production validation；
- 把 sparse structural event 当成高统计可信规则。
```

### 8.5 Causal & Industry Logic Graph

v1.1 不把 causal graph 作为 MVP 必需组件。

原因：

```text
- 2~3 条规则不需要图；
- 图构建成本高；
- 图最容易引入 speculative causal edges；
- 在 claim 数量不足时，图的稳定性很差。
```

策略：

```text
Phase 1-3: claim → rule 直连。
Phase 4+: 当某个 domain 有数百条已验证或已审核 claim 后，再构建 graph。
```

---

## 9. Hardened Empirical Validation

### 9.1 Experiment Family

所有实验必须归入 experiment family。

```json
{
  "experiment_family_id": "FAM-CB-LIQUIDITY-2026Q2",
  "scope": {
    "agent_id": "macro.central_bank",
    "rule_group": "liquidity_impulse",
    "candidate_parameters": ["net_injection_window_days", "liquidity_threshold"],
    "metrics": ["net_alpha_after_cost_20d", "hit_rate_20d", "calibration_error"],
    "regime_buckets": ["risk_on", "risk_off", "neutral"]
  },
  "planned_number_of_tests": 36,
  "multiple_testing_method": "benjamini_hochberg_fdr",
  "max_fdr": 0.10
}
```

Promotion 不能只看单个最佳实验，必须在 family 层面校正。

### 9.2 Minimum Effective Sample Size

样本量以独立信号或事件为单位，不以日历天数为单位。

```text
effective_n >= minimum_effective_n
```

默认门槛：

```text
macro high-frequency rules: effective_n >= 60
sector recurring-flow rules: effective_n >= 60
sparse event rules: effective_n >= 30 for diagnostic only, not production promotion
regime bucket gate: bucket_effective_n >= 30 before bucket-specific pass/fail
```

### 9.3 Overlapping Windows

20d forward return 按日滚动会产生严重重叠，相邻样本高度自相关。必须使用：

```text
- non-overlapping windows; or
- Newey-West corrected inference; or
- block bootstrap; and
- explicit effective N estimate.
```

Validation report 必须输出：

```json
{
  "nominal_n": 1000,
  "effective_n": 78,
  "overlap_policy": "block_bootstrap",
  "block_length_days": 20
}
```

### 9.4 Multiple Testing Control

允许方法：

```text
- Benjamini-Hochberg FDR for experiment family;
- Deflated Sharpe ratio when optimizing Sharpe-like metrics;
- White Reality Check / SPA style procedure for large strategy searches;
- permutation / bootstrap family-wise correction where appropriate.
```

禁止：

```text
- 只报告最好的 regime bucket；
- 只报告最好的 horizon；
- 只报告未校正 p-value；
- 只报告 hit_rate delta 而不报告 uncertainty。
```

### 9.5 Walk-Forward and Lockbox

每个 production promotion 必须经过：

```text
1. in-sample development
2. walk-forward validation
3. paper trading or live shadow
4. lockbox test for final promotion when material capital impact is expected
```

Lockbox 规则：

```text
- lockbox 不参与规则设计；
- lockbox 不参与参数选择；
- lockbox 不参与失败后反复调参；
- 每个 experiment family 的 lockbox 只能用于最终 promotion 判断；
- lockbox 打开失败后，family 进入 redesign，而不是继续在 lockbox 上搜索。
```

### 9.6 Cost-Aware Acceptance

默认 primary metric 应使用 after-cost 指标。

```text
net_alpha_after_cost_horizon = gross_alpha_horizon - estimated_transaction_cost - slippage - borrow_or_funding_cost
```

Acceptance rule 必须包含：

```text
- turnover 不显著恶化；
- transaction cost 模型；
- liquidity constraint；
- max drawdown 不恶化；
- calibration 不恶化；
- risk-adjusted metric 不恶化。
```

### 9.7 Regime Partial Pooling

Regime 分层用于诊断，但小样本 bucket 不能作为独立 gate。

政策：

```text
- bucket_effective_n < 30: insufficient_data, diagnostic only;
- bucket_effective_n >= 30: 可作为辅助证据；
- bucket_effective_n >= 60: 可作为 regime-specific gate；
- 推荐使用 partial pooling，避免小样本 bucket 估计极端化。
```

Partial pooling 输出对象：

```json
{
  "regime_effects": {
    "risk_on": {
      "raw_delta": 0.018,
      "shrunk_delta": 0.012,
      "effective_n": 44,
      "gate_status": "diagnostic_only"
    },
    "risk_off": {
      "raw_delta": -0.010,
      "shrunk_delta": -0.004,
      "effective_n": 23,
      "gate_status": "insufficient_data"
    }
  }
}
```

### 9.8 Specification Search Bias

Data PIT 不足以消除 hindsight。必须记录：

```text
- rule design date;
- metric proxy selection date;
- parameter candidate freeze date;
- failure mode definition date;
- pre-registration hash;
- who/what generated the hypothesis;
- whether any validation result was seen before freeze.
```

---

## 10. Runtime Rule Aggregation

### 10.1 Rule Output Object

每条 rule fire 后输出统一对象：

```json
{
  "rule_id": "macro.central_bank.soft.001",
  "rule_group_id": "macro.central_bank.liquidity",
  "direction": "positive",
  "raw_score_delta": 0.08,
  "horizon_days": 20,
  "confidence_contribution": "supportive",
  "evidence_ids": ["E1"],
  "source_claim_ids": ["CLAIM-CB-20260605-0001"],
  "validation_status": "paper_trading",
  "empirical_confidence_bin": "medium",
  "correlated_rule_ids": ["macro.central_bank.soft.002"],
  "failure_mode_flags": []
}
```

### 10.2 Aggregation Principles

```text
1. Directional deltas are summed only within max adjustment caps.
2. Related rules are grouped and de-duplicated.
3. Conflicting rules generate conflict objects; they do not silently cancel without explanation.
4. Research rules cannot override hard risk gates.
5. Total research-derived adjustment must be capped relative to base model.
6. Aggregation output, not just individual rule output, must be validated.
```

### 10.3 Suggested Aggregation Formula

```text
For each rule_group:
    group_delta = clipped_sum(weight_i * score_delta_i)
    group_delta = cap(group_delta, group_max_adjustment)

final_research_delta = clipped_sum(group_delta_j)
final_research_delta = cap(final_research_delta, global_research_adjustment_cap)
```

Default caps:

```text
single_rule_max_adjustment: 0.05
rule_group_max_adjustment: 0.10
global_research_adjustment_cap: 0.20
```

### 10.4 Conflict Handling

```json
{
  "conflict_id": "CONFLICT-CB-EPU-20260605",
  "positive_rules": ["macro.central_bank.soft.001"],
  "negative_rules": ["macro.china.soft.epu_001"],
  "conflict_type": "liquidity_support_vs_policy_uncertainty",
  "resolution": "reduce_confidence_cap_and_keep_direction_conditional",
  "confidence_cap_adjustment": -0.10,
  "actionability_adjustment": "downgrade_to_watchlist"
}
```

### 10.5 Group and Interaction Ablation

Validation 必须包含：

```text
- single-rule ablation;
- rule-group ablation;
- correlated-rule de-dup test;
- interaction test for rules using overlapping metric proxies;
- aggregation-level backtest.
```

禁止只因为单条 rule 在某个组合下边际贡献为正，就直接 promotion。

---

## 11. Confidence Policy v1

### 11.1 Components

```text
data_confidence:
    当前工具数据是否新鲜、完整、非 fallback、多源一致。

research_weight_confidence:
    source/viewpoint 表现权重、抽取质量、独立来源数量、分歧和 crowding 风险。

empirical_validation_confidence:
    规则是否通过 hardened validation、walk-forward、paper trading。

method_tool_confidence:
    工具覆盖、PIT 可用性、工具正确性、recipe validation 和 shadow runtime 状态。

regime_match_confidence:
    当前 regime 是否符合规则适用条件，是否触发 failure modes。
```

### 11.2 Safe Default Function

默认采用保守合成函数：

```text
pre_cap_confidence = min(
    data_confidence,
    research_weight_confidence,
    empirical_validation_confidence,
    method_tool_confidence,
    regime_match_confidence
)

final_confidence = min(pre_cap_confidence, confidence_cap)
```

理由：任何一条证据链短板都应限制最终 confidence。

### 11.3 Actionability Thresholds

```text
confidence < 0.55:
    narrative only / monitor only / no tilt

0.55 <= confidence < 0.65:
    watchlist or tiny tilt only if current data confirms

0.65 <= confidence < 0.75:
    modest tilt allowed, subject to risk and cost constraints

confidence >= 0.75:
    stronger action only if current data + validated rule + regime match + risk approval all pass
```

### 11.4 Research-Only Rule

如果只有研究资料支持、没有当前数据确认：

```text
data_confidence <= 0.50
final_confidence <= 0.50
actionability = no_trade / monitor_only
```

这解决“研报只是 prior，不是 signal”的一致性问题。

### 11.5 Confidence Calibration

Confidence 桶必须用实际命中率校准。

```json
{
  "confidence_bucket": "0.65-0.75",
  "expected_hit_rate": 0.65,
  "realized_hit_rate": 0.57,
  "calibration_error": -0.08,
  "status": "degraded",
  "required_action": "lower_confidence_mapping_or_revalidate"
}
```

校不准是系统缺陷，不只是日志指标。

---

## 12. Rule Identity、Path、Type、Horizon 标准

### 12.1 Rule ID

Canonical format:

```text
<layer>.<agent>.<rule_type>.<serial>
```

Examples:

```text
macro.central_bank.soft.001
macro.volatility.hard.002
sector.semiconductor.soft.014
decision.cio.guard.003
```

禁止同一规则同时出现多个 ID，例如：

```text
SEMI_SOFT_014
SEMI_POLICY_SOFT_014
SEMI_POLICY_SUBSTITUTION_V1
```

### 12.2 Rule Pack ID

```text
<layer>.<agent>.<theme>.v<major>
```

Example:

```text
sector.semiconductor.policy_substitution.v1
macro.central_bank.liquidity.v1
```

### 12.3 Absolute Target Path

所有 patch target_path 必须是绝对路径：

```text
/rule_packs/<rule_pack_id>/rules/<rule_id>/learnable_parameters/<parameter_name>/value
```

Example:

```text
/rule_packs/sector.semiconductor.policy_substitution.v1/rules/sector.semiconductor.soft.014/learnable_parameters/confirmation_window_days/value
```

### 12.4 Type Standards

```yaml
confirmation_window_days:
  value: 20
  type: integer
  unit: d

policy_news_threshold:
  value: 3
  type: integer

policy_catalyst_weight:
  value: 0.25
  type: float
  min: 0.0
  max: 1.0
```

禁止混用：

```text
"10d" vs 10
"20d-120d" without parseable min/max
```

### 12.5 Horizon-Metric Matching

规则 horizon 必须和验证 metric 对齐。

```yaml
horizon:
  min_days: 20
  max_days: 60
validation_metrics:
  primary: net_alpha_after_cost_20d
  secondary:
    - net_alpha_after_cost_60d
    - max_drawdown_after_signal_20d
```

如果规则声明 20d-120d horizon，却只验证 hit_rate_20d，validator 必须标记为 `horizon_metric_mismatch`。

### 12.6 Scoring Precision Policy

在有可靠校准前，source quality 和 research strength 使用粗分箱：

```text
high / medium / low / unknown
```

禁止无依据的小数精度：

```text
quality_score = 0.72
confidence_prior = 0.62
```

Production confidence 可以是数值，但必须来自 calibration mapping，而不是 LLM 任意填写。

---

## 13. Mutation 与 Promotion Governance

### 13.1 Evolution Targets

允许自动演化：

```text
- thresholds
- weights
- lookback windows
- signal priority
- fallback discounts
- confidence caps within allowed ranges
- sector mappings
- topic filters
- rule predicates within validated rule packs
```

禁止自动修改：

```text
- output schema field names
- role contract
- required tool contract
- evidence ledger requirements
- hard guardrails
- compliance gates
- lockbox policy
- validation acceptance standards
```

### 13.2 Mutation Proposal

```json
{
  "mutation_id": "MUT-CB-20260605-0001",
  "proposal_type": "parameter_update",
  "agent_id": "macro.central_bank",
  "target_path": "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value",
  "operation": "replace",
  "old_value": 5,
  "new_value": 10,
  "source_experiment_id": "EXP-CB-20260605-0001",
  "expected_effect": {
    "primary_metric": "net_alpha_after_cost_20d",
    "direction": "increase"
  },
  "risk": "May respond more slowly to short liquidity shocks.",
  "rollback_condition": {
    "metric": "live_net_alpha_after_cost_20d",
    "delta_lt": -0.02,
    "window_trading_days": 60
  }
}
```

### 13.3 Promotion States

```text
draft
    研究假设或 source claim 尚未完成检查。

candidate
    schema 合法，PIT 数据可用，等待验证。

validated
    通过 pre-registered validation，但未进入 paper trading。

paper_trading
    live shadow 运行，不影响实际决策或只影响 very small tilt。

staged_production
    小权重上线，有强监控和回滚。

production
    正式参与 agent runtime，但仍受 cap 和 monitoring 约束。

monitored
    持续评估 alpha decay、calibration、turnover、failure mode。

deprecated / rolled_back
    表现衰减、验证失败、数据不可用或合规原因下线。
```

### 13.4 Direct Production 禁止规则

以下情况禁止直接 production：

```text
- sparse structural event rules;
- no PIT data;
- no gold-set verified extraction;
- no effective sample size;
- uncorrected multiple testing;
- only in-sample improvement;
- no transaction cost model;
- lockbox reused multiple times;
- research-only without current data confirmation;
- output schema or guardrail changes.
```

---

## 14. Monitoring、Alpha Decay 与 Rollback

### 14.1 Production Monitoring Metrics

```text
- live net alpha after cost;
- hit rate by horizon;
- confidence calibration;
- turnover;
- drawdown after signal;
- signal frequency;
- rule firing rate;
- conflict rate;
- fallback rate;
- missing data rate;
- regime-specific performance;
- contribution to downstream decisions;
- realized vs expected actionability.
```

### 14.2 Slow Degradation Detection

Alpha 衰减通常是渐进的，不能只靠 hard tripwire。

```json
{
  "rule_id": "macro.central_bank.soft.001",
  "monitoring_window_days": 120,
  "decay_metrics": {
    "rolling_net_alpha_after_cost_20d": "declining",
    "half_life_estimate_days": 45,
    "calibration_error_trend": "worsening",
    "turnover_trend": "increasing"
  },
  "decay_status": "warning",
  "action": "reduce_weight_and_revalidate"
}
```

### 14.3 Rollback Policy

Rollback 分三类：

```text
soft rollback:
    降低 rule weight 或 actionability。

hard rollback:
    从 production 移回 candidate 或 deprecated。

compliance rollback:
    因数据授权、license、source usage 风险立即下线。
```

---

## 15. Compliance / License Gate

Sell-side 研报通常存在 seat 授权、再分发限制和派生数据使用边界。RKE 必须把合规作为真实运营风险处理。

### 15.1 Source License Fields

```json
{
  "source_id": "SRC-20260605-0001",
  "license_status": "approved | pending_review | restricted | prohibited",
  "allowed_uses": [
    "human_reading",
    "internal_research_summary",
    "machine_extraction",
    "derived_claim_storage",
    "model_training",
    "production_runtime_retrieval"
  ],
  "forbidden_uses": [],
  "review_owner": "compliance",
  "review_date": "2026-06-05"
}
```

### 15.2 Gate Rules

```text
- license_status = prohibited: 不得 ingest。
- license_status = restricted: 不得进入 production runtime。
- license_status = pending_review: 只允许 sandbox。
- derived claim 是否可存储，需要合规确认。
- 不得把原文大段内容写入 prompt 或 runtime output。
```

---

## 16. Revised MVP

### 16.1 为什么 MVP 不从半导体 export control 开始

半导体政策和出口限制案例适合展示 provenance 和产业逻辑，但不适合作为第一个 statistical validation MVP：

```text
- 独立事件少；
- regime 变化强；
- 事件定义容易 hindsight；
- 历史可验证性弱；
- 统计显著性很难成立。
```

这类规则可以标记为：

```text
low empirical confidence, theory-driven, capped impact
```

### 16.2 MVP 首选：central_bank / liquidity

首个 MVP 应选择高频、多事件、数据较标准的规则：

```text
agent: macro.central_bank
rule family: liquidity impulse / PBOC operations / policy window confirmation
metrics:
    pboc_net_injection_7d / 20d
    short-rate movement
    risk appetite proxy
    sector/style relative returns
```

可选第二个 macro agent：

```text
macro.volatility
    VIX / iVX / realized volatility / risk-off gate

或 macro.dollar
    DXY / CNY / CN-US spread / foreign flow pressure
```

Sector demo 可保留 semiconductor，但只作为 provenance demo 和 low empirical confidence rule，不作为首个 promotion proof。

### 16.3 MVP Deliverables

```text
D1. Data Availability Matrix for central_bank metrics.
D2. Claim extraction gold set for 50 documents / 100 claims.
D3. Source-grounded claim schema and verifier.
D4. One central_bank rule pack.
D5. One parameter prior family.
D6. One pre-registered validation experiment family.
D7. Effective N / overlap / multiple testing / cost-aware report.
D8. Runtime rule aggregation prototype.
D9. Confidence function v1 implementation.
D10. Paper trading output and audit viewer.
```

### 16.4 MVP Exit Criteria

MVP 通过必须满足：

```text
- claim extraction gold set precision 达标；
- all production candidate proxies have PIT data;
- validation experiment pre-registered;
- effective_n >= threshold;
- overlapping windows corrected;
- multiple testing corrected;
- after-cost metric positive and CI excludes zero;
- walk-forward passed;
- no lockbox misuse;
- paper trading plan ready;
- no direct production promotion;
- confidence function and actionability threshold enforced;
- research-only no-trade rule enforced。
```

---

## 17. 分阶段实施路线图

### Phase -1：Feasibility Spikes

目标：先验证最大未知，不先冻结复杂 schema。

#### Spike A：PIT Data Availability

Owner: Data Lead + Quant Research

交付：

```text
- data availability matrix 模板；
- central_bank / volatility / dollar 的核心 proxy 可用性；
- PIT、vintage、survivorship、timestamp、coverage drift 评估；
- 不可用 proxy 清单；
- paper-only proxy 清单。
```

Exit criteria:

```text
至少 1 个 macro rule family 有足够 PIT 数据进入 validation MVP。
```

#### Spike B：Claim Extraction Reliability

Owner: Research Lead + LLM/Agent Engineer

交付：

```text
- 50 documents / 100 claims gold set；
- source-grounded vs hypothesis 标注规范；
- span-grounded verifier；
- extraction precision/recall report；
- hallucinated field rate。
```

Exit criteria:

```text
claim precision、span support precision、direction accuracy、variable mapping accuracy 达到 gate。
```

### Phase 0：Baseline and Experiment Governance

Owner: Quant Research + Platform

交付：

```text
- baseline prompt versions；
- baseline agent outputs；
- historical daily-cycle snapshots；
- experiment family registry；
- pre-registration protocol；
- lockbox policy；
- cost model v1；
- minimum effective N policy；
- overlap correction policy。
```

### Phase 1：Hardened Schemas

Owner: Platform + Agent Runtime

交付：

```text
- source metadata schema；
- source-grounded claim schema；
- hypothesis schema；
- data availability matrix schema；
- rule pack schema；
- parameter prior schema；
- validation experiment v2 schema；
- production patch schema；
- confidence policy v1；
- rule aggregation policy v1；
- absolute path and ID standards。
```

### Phase 2：Central Bank Validation MVP

Owner: Quant Research + Macro Research

交付：

```text
- macro.central_bank.liquidity.v1 rule pack；
- parameter prior family；
- pre-registered experiment；
- hardened validation report；
- no-production promotion decision；
- paper trading setup。
```

### Phase 3：Runtime Integration

Owner: Agent Runtime + Platform

交付：

```text
- active rule pack injection；
- normalized tool output injection；
- rule output object；
- rule aggregation；
- confidence engine；
- evidence / inference / recommendation binding；
- progress event；
- downstream handoff。
```

### Phase 4：Paper Trading

Owner: Quant Research + Production Monitor

交付：

```text
- paper trading dashboard；
- live shadow comparison vs baseline；
- calibration tracking；
- turnover / cost tracking；
- alpha decay monitoring；
- rollback simulation。
```

### Phase 5：Sector Rule Demo

Owner: Sector Research + Agent Runtime

范围：

```text
sector.semiconductor.policy_substitution.v1
```

定位：

```text
- provenance demo；
- source-grounded claim demo；
- disagreement map demo；
- theory-driven low empirical confidence rule；
- capped impact；
- not first production statistical proof。
```

### Phase 6：Macro Expansion

扩展到：

```text
macro.volatility
macro.dollar
macro.yield_curve
macro.china
macro.institutional_flow
```

前提：

```text
central_bank MVP 通过 Phase 4 paper trading gate。
```

### Phase 7：Sector / Superinvestor / Decision Integration

重点：

```text
sector agents: 接入 macro handoff、行业 rule pack、资金/基本面/政策双确认。
superinvestor agents: 接入 style-fit rule、accepted/rejected candidates、风格约束。
decision agents: 接入 aggregation、risk discount、cash floor、override audit。
```

---

## 18. Agent 分层改造重点

### 18.1 Macro Agents

Macro agents 输出 regime signal，不直接做 portfolio sizing。

关键要求：

```text
- 工具数据证据；
- rule_ids_used；
- confidence cap；
- fallback / missing data impact；
- downstream handoff；
- conflict objects。
```

首批：

```text
central_bank: PBOC / Fed / liquidity / policy window
volatility: VIX / iVX / RV / risk-off gate
dollar: DXY / CNY / CN-US spread / foreign flow pressure
```

### 18.2 Sector Agents

Sector agents 处理行业相对选择，不替 CIO 做最终仓位。

高 confidence 至少需要：

```text
fundamental / policy / flow / price confirmation 中至少两个维度。
```

主题热度无资金或基本面确认时：

```text
confidence cap <= 0.60
actionability <= watchlist_or_tiny_tilt
```

### 18.3 Superinvestor Agents

Superinvestor agents 模拟特定投资风格，不做泛化选股。

输出必须包含：

```text
- accepted_candidates;
- rejected_candidates;
- style_fit_score;
- reason for rejection;
- mismatch with investor style;
- evidence binding。
```

### 18.4 Decision Agents

Decision agents 负责组合级约束、风险折扣、最终配置。

必须说明：

```text
- 覆盖了哪些上游 agent；
- 忽略了哪些信号以及原因；
- 风险折扣；
- cash floor；
- override 规则；
- correlated exposure；
- execution and turnover impact。
```

---

## 19. Checker 规则清单

### 19.1 Source Checker

```text
- source_id unique;
- publish_date present;
- license_status not prohibited;
- source_hash present;
- point_in_time_available marked;
- ingest_time present。
```

### 19.2 Claim Checker

```text
- source-grounded fields require source_span_id;
- hypothesis fields cannot be marked source-grounded;
- failure_modes can be unknown, not fabricated;
- variable mapping must use controlled vocabulary;
- verifier_status required before rule compilation;
- gold-set gate required before production use。
```

### 19.3 Rule Pack Checker

```text
- rule_id canonical;
- rule_pack_id canonical;
- source_claim_ids valid;
- hypothesis_ids explicitly marked;
- metric proxies exist in data availability matrix;
- horizon parseable;
- learnable parameter types valid;
- validation_required true for candidate rules;
- no production rule without validation state。
```

### 19.4 Experiment Checker

```text
- experiment_family_id present;
- pre_registered true;
- frozen_spec_hash present;
- effective_n policy defined;
- overlap policy defined;
- multiple testing correction defined;
- cost model required;
- walk_forward_required true;
- lockbox policy defined;
- regime bucket sample rules defined。
```

### 19.5 Patch Checker

```text
- target_path absolute;
- target_path within allowed evolution targets;
- forbidden paths unchanged;
- old_value matches current registry;
- new_value type valid;
- source_experiment_id valid;
- promotion state allows patch;
- rollback rule present。
```

### 19.6 Runtime Output Checker

```text
- evidence ledger complete;
- inference binds evidence_ids and rule_ids;
- recommendation binds inference_ids;
- confidence <= cap;
- research-only rule enforced;
- conflict object present when opposing rules fire;
- correlated rules not double-counted;
- downstream handoff schema valid。
```

---

## 20. Issue Backlog with Priority and Owner

### P0: Must Fix Before Schema Freeze

| Issue | Owner | Deliverable |
|---|---|---|
| Validator 过拟合风险 | Quant Research | experiment family + FDR/DSR + walk-forward + lockbox policy |
| Overlapping window 自相关 | Quant Research | non-overlap / NW / block bootstrap + effective N |
| PIT 数据可行性 | Data Lead | data availability matrix |
| Specification search bias | Research Lead | pre-registration + freeze protocol |
| Claim extraction 可靠性 | LLM/Agent Engineer | gold set + span verifier |
| Runtime 多规则聚合 | Agent Runtime | aggregation policy + conflict object |
| Confidence 函数未定义 | Quant + Runtime | confidence_policy.v1 |
| Research-only 可交易矛盾 | CIO/Risk + Runtime | actionability thresholds |
| MVP 对象选择 | Project Owner | central_bank-first MVP |

### P1: Fix Before Broad Rollout

| Issue | Owner | Deliverable |
|---|---|---|
| Regime 小样本碎片化 | Quant Research | partial pooling policy |
| Single-rule ablation 不够 | Quant Research | group/interaction ablation |
| Rule naming 漂移 | Platform | canonical ID/path standard |
| Type 混用 | Platform | schema type validation |
| Horizon-metric 错配 | Quant + Platform | horizon checker |
| False precision | Research Governance | quality rubric + confidence calibration |
| Transaction cost / turnover | Quant + Execution | cost-aware acceptance |
| Alpha decay | Production Monitor | slow degradation detector |

### P2: Improve After MVP Stability

| Issue | Owner | Deliverable |
|---|---|---|
| Causal graph | Research Platform | graph builder after sufficient claims |
| Disagreement map | Research Lead | disagreement cluster UI |
| Audit viewer | Platform | source → claim → rule → validation → output trace |
| Lockbox governance automation | Quant Platform | one-time unlock workflow |
| Cross-market analog validation | Quant Research | sparse-event auxiliary evidence framework |

---

## 21. Repository / Directory Structure

```text
MOSAIC-Research-Knowledge/
  docs/
    master_plan_v1_1.md
    validation_policy.md
    claim_extraction_guidelines.md
    confidence_policy.md
    compliance_policy.md

  schemas/
    source_metadata.schema.json
    source_grounded_claim.schema.json
    hypothesis.schema.json
    data_availability_matrix.schema.json
    rule_pack.schema.yaml
    parameter_prior.schema.json
    validation_experiment_v2.schema.json
    production_patch.schema.json
    confidence_policy.schema.yaml
    rule_aggregation_policy.schema.yaml

  registry/
    sources/
    claims/
    hypotheses/
    rule_packs/
    parameter_priors/
    experiments/
    patches/
    monitoring/

  pipelines/
    research_ingestor/
    claim_extractor/
    span_verifier/
    rule_pack_compiler/
    parameter_prior_generator/
    empirical_validator/
    mutation_planner/

  runtime/
    rule_aggregator/
    confidence_engine/
    evidence_binder/
    handoff_builder/
    output_checker/

  evaluation/
    experiment_family_registry/
    pre_registration/
    cost_model/
    overlap_correction/
    multiple_testing/
    walk_forward/
    lockbox/
    paper_trading/

  dashboards/
    audit_viewer/
    paper_trading_monitor/
    production_monitor/
```

Prompt repo 侧：

```text
MOSAIC-Prompts/
  prompt_ir/
  rendered_prompts/
  shared_contracts/
  agent_overlays/
  cohort_overlays/
  mutation_patches/
```

Agent repo 侧：

```text
MOSAIC-Agents/
  prompt_loader/
  runtime_context_builder/
  tool_output_normalizer/
  prompt_checker/
  output_checker/
  mutator/
  evaluator/
```

---

## 22. 最终验收标准

系统进入 broad rollout 前，必须满足：

```text
1. 至少一个 macro rule family 完成 Phase -1 到 Phase 4。
2. Claim extraction gold set 通过 gate。
3. Data availability matrix 覆盖首批 production candidate proxies。
4. Validation experiment v2 能跑出含 effective N、overlap correction、multiple testing、cost-aware metrics 的报告。
5. Runtime rule aggregation 已实现 correlated rule de-dup 和 conflict object。
6. Confidence policy v1 已实现 min-components safe function。
7. Research-only no-trade rule 已被 checker 强制执行。
8. Patch validator 能拒绝 forbidden path 和不一致 target_path。
9. Paper trading monitor 能输出 live vs baseline 差异。
10. Production monitor 能检测 alpha decay 和 calibration drift。
11. Compliance gate 能阻止未授权研报进入 production runtime。
12. Audit viewer 能追踪 source → claim → hypothesis → rule → parameter → experiment → patch → agent output。
```

---

## 23. 最终原则

MOSAIC 的演化目标不是“让模型更会讲投资故事”，而是让系统逐步沉淀：

```text
可追踪的研究来源；
可核验的 claim；
可区分的假设；
可测试的规则；
可校准的参数；
可约束的 confidence；
可解释的 runtime 聚合；
可回滚的生产变更。
```

最危险的系统不是没有验证的系统，而是把过拟合验证结果包装成制度可信的系统。

因此 v1.1 的最终执行顺序是：

```text
先做 PIT data spike 和 claim extraction spike；
再建 experiment governance；
再冻结 hardened schema；
再做 central_bank validation MVP；
再接入 runtime aggregation 和 confidence engine；
再 paper trading；
最后 staged production。
```

只有这样，MOSAIC 才能真正从“LLM 金融常识推理”升级为“研究资产驱动、统计验证约束、生产监控闭环”的 agent 投研系统。

```research-knobs
research-knobs:
  agent: macro.market_breadth
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - market_breadth_snapshot
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - market_breadth_snapshot
      trigger: missing_required_evidence
  evidence_registry:
    market_breadth_snapshot:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: market_breadth_snapshot_current
      primary: true
      tool: get_market_breadth_snapshot
  evidence_weights:
    market_breadth_snapshot: 1
  layer: macro
  lookbacks: {}
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/market_breadth_snapshot_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/advance_decline_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/trend_breadth_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/new_high_low_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/turnover_expansion_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/breadth_change_window_days/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/concentration_confirmation_weight/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 5d
      id: macro.market_breadth.soft.001
      target_variable: direction
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.market_breadth.advance_decline_weight.5d
      target_variable: advance_decline_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.market_breadth.trend_breadth_weight.5d
      target_variable: trend_breadth_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.market_breadth.new_high_low_weight.5d
      target_variable: new_high_low_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.market_breadth.turnover_expansion_weight.5d
      target_variable: turnover_expansion_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.market_breadth.breadth_change_window_days.5d
      target_variable: breadth_change_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.market_breadth.concentration_confirmation_weight.5d
      target_variable: concentration_confirmation_weight
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.market_breadth.advance_decline_weight.primary
              evidence_key: market_breadth_snapshot
              metric_ids:
                - market_breadth_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_market_breadth_snapshot
          evidence_dependency_policies:
            macro.market_breadth.advance_decline_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: advance_decline_weight
          owner_stage: agent_run
          path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/advance_decline_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.market_breadth.trend_breadth_weight.primary
              evidence_key: market_breadth_snapshot
              metric_ids:
                - market_breadth_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_market_breadth_snapshot
          evidence_dependency_policies:
            macro.market_breadth.trend_breadth_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: trend_breadth_weight
          owner_stage: agent_run
          path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/trend_breadth_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.market_breadth.new_high_low_weight.primary
              evidence_key: market_breadth_snapshot
              metric_ids:
                - market_breadth_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_market_breadth_snapshot
          evidence_dependency_policies:
            macro.market_breadth.new_high_low_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: new_high_low_weight
          owner_stage: agent_run
          path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/new_high_low_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.market_breadth.turnover_expansion_weight.primary
              evidence_key: market_breadth_snapshot
              metric_ids:
                - market_breadth_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_market_breadth_snapshot
          evidence_dependency_policies:
            macro.market_breadth.turnover_expansion_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: turnover_expansion_weight
          owner_stage: agent_run
          path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/turnover_expansion_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.market_breadth.breadth_change_window_days.primary
              evidence_key: market_breadth_snapshot
              metric_ids:
                - market_breadth_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_market_breadth_snapshot
          evidence_dependency_policies:
            macro.market_breadth.breadth_change_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: breadth_change_window_days
          owner_stage: agent_run
          path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/breadth_change_window_days/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.market_breadth.concentration_confirmation_weight.primary
              evidence_key: market_breadth_snapshot
              metric_ids:
                - market_breadth_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_market_breadth_snapshot
          evidence_dependency_policies:
            macro.market_breadth.concentration_confirmation_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: concentration_confirmation_weight
          owner_stage: agent_run
          path: /rule_packs/macro.market_breadth.runtime.v1/rules/macro.market_breadth.soft.001/learnable_parameters/concentration_confirmation_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: macro.market_breadth
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - channels
      - claim_refs
      - claims
      - direction
      - horizon
      - key_drivers
      - strength
    must_not_cover:
      - final_portfolio_sizing
      - single_stock_recommendation
  schema_version: research_knobs_v1
  thresholds:
    advance_decline_weight: 0.2
    breadth_change_window_days: 0.2
    concentration_confirmation_weight: 0.2
    new_high_low_weight: 0.2
    trend_breadth_weight: 0.2
    turnover_expansion_weight: 0.2
  tie_breaks: []
```

# market_breadth — Layer-1 宏观传导

## 运行时职责与工具合同（代码生成）
解释 A 股参与度、趋势广度、成交广度、新高新低与集中度的传导。

禁区：
- 不得读取新闻、资金流或波动率后重复判断
- 不得自行重算快照指标

只允许调用：get_market_breadth_snapshot。
以运行时 JSON Schema 为唯一输出字段与约束来源，不使用手写 JSON 示例。
检查 as-of 时间有效性、变化/预期差、证据冲突与 A 股传导。不得输出空壳、模糊空数组、跨角色结论或无证据百分比。
structured_conclusion 回显观测数值时必须带 series_id 或 evidence_id，且数值必须与固定快照完全一致。
direction=NEUTRAL 时 strength 必须为 0；否则 strength 必须为 1–5。claims、claim_refs、key_drivers、channels 均不得为空。

## 分析流程
1. 必须调用唯一允许的角色快照；工具失败、PIT 状态无效或覆盖不足时拒绝该阶段，不得改写为中性市场。
2. 逐项检查 released_at、vintage_at 与 as-of；比较实际值、前值、预期差和变化，明确冲突证据。
3. 只解释本角色负责的传导渠道，并落到 A 股风险溢价、盈利、流动性或行业敏感度。
4. 结论必须由非空 claims、结论级 claim_refs、key_drivers、channels 与 confidence 支持。

不得读取或推断新闻情绪；事件证据只属于 china 与 geopolitical。
不得调用 OpenCLI、Google/财新搜索或实时雪球关注数。不得虚构来源、数值、百分比、时间戳或快照字段。
commodities 仅在快照含真实期限结构时使用 contango/backwardation；volatility 必须区分美国隐含波动与中国实现波动。
legacy emerging_markets/news_sentiment 仅供旧审计，状态为 legacy_unverified，不能作为当前证据或 Darwinian 先验。

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime 提供本次调用唯一有效的 evidence catalog 与 research rule ids。

输出字段包括：`direction`, `strength`, `horizon`, `channels`, `key_drivers`, `confidence`, `claims`, `claim_refs`。

必需 runtime tools：`get_market_breadth_snapshot`。

本 agent 的 domain knob card ids：`advance_decline_weight`, `trend_breadth_weight`, `new_high_low_weight`, `turnover_expansion_weight`, `breadth_change_window_days`, `concentration_confirmation_weight`。

Knob influence 审计字段：`declared_knob_influence_ids`, `declared_influence_rationale`。

必须输出 `claims` 与 `claim_refs`。每个非 uncertainty claim 必须通过 `evidence_refs` 引用 catalog 中的 `evidence_id`；每个 inference claim 还必须通过 `research_rule_refs` 引用允许的 rule id。所有 recommendation、candidate、pick、position decision、portfolio action、risk adjustment 或 execution check 都必须用 `claim_refs` 引用支持它的 claim。证据不足时输出有证据支持的显式空 disposition 与 uncertainty claim，不得伪造 evidence id、fingerprint、rule id 或跨 run 引用。

<!-- runtime-evidence-contract:end -->

```research-knobs
research-knobs:
  agent: macro.china
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - china_macro_snapshot
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - china_macro_snapshot
      trigger: missing_required_evidence
  evidence_registry:
    china_macro_snapshot:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: china_macro_snapshot_current
      primary: true
      tool: get_china_macro_snapshot
  evidence_weights:
    china_macro_snapshot: 1
  layer: macro
  lookbacks:
    policy_confirmation_window_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/china_macro_snapshot_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/pmi_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/social_financing_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/property_cycle_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/consumption_weight/value
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/policy_confirmation_window_days/value
      step: 1
      type: integer
    - max: 0.75
      min: 0
      path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/a_share_beta_discount/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 5d
      id: macro.china.soft.001
      target_variable: direction
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.china.pmi_weight.5d
      target_variable: pmi_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.china.social_financing_weight.5d
      target_variable: social_financing_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.china.property_cycle_weight.5d
      target_variable: property_cycle_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.china.consumption_weight.5d
      target_variable: consumption_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.china.policy_confirmation_window_days.5d
      target_variable: policy_confirmation_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.china.a_share_beta_discount.5d
      target_variable: a_share_beta_discount
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.china.pmi_weight.primary
              evidence_key: china_macro_snapshot
              metric_ids:
                - china_macro_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_china_macro_snapshot
          evidence_dependency_policies:
            macro.china.pmi_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: pmi_weight
          owner_stage: agent_run
          path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/pmi_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.china.social_financing_weight.primary
              evidence_key: china_macro_snapshot
              metric_ids:
                - china_macro_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_china_macro_snapshot
          evidence_dependency_policies:
            macro.china.social_financing_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: social_financing_weight
          owner_stage: agent_run
          path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/social_financing_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.china.property_cycle_weight.primary
              evidence_key: china_macro_snapshot
              metric_ids:
                - china_macro_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_china_macro_snapshot
          evidence_dependency_policies:
            macro.china.property_cycle_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: property_cycle_weight
          owner_stage: agent_run
          path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/property_cycle_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.china.consumption_weight.primary
              evidence_key: china_macro_snapshot
              metric_ids:
                - china_macro_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_china_macro_snapshot
          evidence_dependency_policies:
            macro.china.consumption_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: consumption_weight
          owner_stage: agent_run
          path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/consumption_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.china.policy_confirmation_window_days.primary
              evidence_key: china_macro_snapshot
              metric_ids:
                - china_macro_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_china_macro_snapshot
          evidence_dependency_policies:
            macro.china.policy_confirmation_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: policy_confirmation_window_days
          owner_stage: agent_run
          path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/policy_confirmation_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.25
          evidence_dependencies:
            - dependency_id: macro.china.a_share_beta_discount.primary
              evidence_key: china_macro_snapshot
              metric_ids:
                - china_macro_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_china_macro_snapshot
          evidence_dependency_policies:
            macro.china.a_share_beta_discount.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: a_share_beta_discount
          owner_stage: agent_run
          path: /rule_packs/macro.china.runtime.v1/rules/macro.china.soft.001/learnable_parameters/a_share_beta_discount/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: macro.china
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
    a_share_beta_discount: 0.25
    consumption_weight: 0.2
    pmi_weight: 0.2
    property_cycle_weight: 0.2
    social_financing_weight: 0.2
  tie_breaks: []
```

# china — Layer-1 宏观传导

## 运行时职责与工具合同（代码生成）
判断中国增长、价格、信用、外需与财政脉冲对 A 股的传导。

禁区：
- 不得把地产作为每次分析的必选维度
- 不得判断 PBOC 立场

只允许调用：get_china_macro_snapshot。
以运行时 JSON Schema 为唯一输出字段与约束来源，不使用手写 JSON 示例。
检查 as-of 时间有效性、变化/预期差、证据冲突与 A 股传导。不得输出空壳、模糊空数组、跨角色结论或无证据百分比。
structured_conclusion 回显观测数值时必须带 series_id 或 evidence_id，且数值必须与固定快照完全一致。
direction=NEUTRAL 时 strength 必须为 0；否则 strength 必须为 1–5。claims、claim_refs、key_drivers、channels 均不得为空。

## 分析流程
1. 必须调用唯一允许的角色快照；工具失败、PIT 状态无效或覆盖不足时拒绝该阶段，不得改写为中性市场。
2. 逐项检查 released_at、vintage_at 与 as-of；比较实际值、前值、预期差和变化，明确冲突证据。
3. 只解释本角色负责的传导渠道，并落到 A 股风险溢价、盈利、流动性或行业敏感度。
4. 结论必须由非空 claims、结论级 claim_refs、key_drivers、channels 与 confidence 支持。

Tushare major_news 与官方政策文件只能作为去重、发布时间过滤后的事件证据；不得形成独立新闻情绪票。
不得调用 OpenCLI、Google/财新搜索或实时雪球关注数。不得虚构来源、数值、百分比、时间戳或快照字段。
commodities 仅在快照含真实期限结构时使用 contango/backwardation；volatility 必须区分美国隐含波动与中国实现波动。
legacy emerging_markets/news_sentiment 仅供旧审计，状态为 legacy_unverified，不能作为当前证据或 Darwinian 先验。

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime 提供本次调用唯一有效的 evidence catalog 与 research rule ids。

输出字段包括：`direction`, `strength`, `horizon`, `channels`, `key_drivers`, `confidence`, `claims`, `claim_refs`。

必需 runtime tools：`get_china_macro_snapshot`。

本 agent 的 domain knob card ids：`pmi_weight`, `social_financing_weight`, `property_cycle_weight`, `consumption_weight`, `policy_confirmation_window_days`, `a_share_beta_discount`。

Knob influence 审计字段：`declared_knob_influence_ids`, `declared_influence_rationale`。

必须输出 `claims` 与 `claim_refs`。每个非 uncertainty claim 必须通过 `evidence_refs` 引用 catalog 中的 `evidence_id`；每个 inference claim 还必须通过 `research_rule_refs` 引用允许的 rule id。所有 recommendation、candidate、pick、position decision、portfolio action、risk adjustment 或 execution check 都必须用 `claim_refs` 引用支持它的 claim。证据不足时输出有证据支持的显式空 disposition 与 uncertainty claim，不得伪造 evidence id、fingerprint、rule id 或跨 run 引用。

<!-- runtime-evidence-contract:end -->

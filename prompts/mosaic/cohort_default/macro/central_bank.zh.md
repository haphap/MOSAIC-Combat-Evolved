```research-knobs
research-knobs:
  agent: macro.central_bank
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - central_bank_snapshot
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - central_bank_snapshot
      trigger: missing_required_evidence
  evidence_registry:
    central_bank_snapshot:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: central_bank_snapshot_current
      primary: true
      tool: get_central_bank_snapshot
  evidence_weights:
    central_bank_snapshot: 1
  layer: macro
  lookbacks:
    liquidity_net_injection_window_days: 20
    omo_mlf_freshness_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/central_bank_snapshot_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_fed_policy_weight/value
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/liquidity_net_injection_window_days/value
      step: 1
      type: integer
    - max: 120
      min: 1
      path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/omo_mlf_freshness_days/value
      step: 1
      type: integer
    - max: 1
      min: 0
      path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/easing_threshold_bps/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/tightening_threshold_bps/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0
      path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/policy_conflict_cap/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 5d
      id: macro.central_bank.soft.001
      target_variable: direction
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.central_bank.pboc_fed_policy_weight.5d
      target_variable: pboc_fed_policy_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.central_bank.liquidity_net_injection_window_days.5d
      target_variable: liquidity_net_injection_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.central_bank.omo_mlf_freshness_days.5d
      target_variable: omo_mlf_freshness_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.central_bank.easing_threshold_bps.5d
      target_variable: easing_threshold_bps
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.central_bank.tightening_threshold_bps.5d
      target_variable: tightening_threshold_bps
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.central_bank.policy_conflict_cap.5d
      target_variable: policy_conflict_cap
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.central_bank.pboc_fed_policy_weight.primary
              evidence_key: central_bank_snapshot
              metric_ids:
                - central_bank_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_central_bank_snapshot
          evidence_dependency_policies:
            macro.central_bank.pboc_fed_policy_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: pboc_fed_policy_weight
          owner_stage: agent_run
          path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_fed_policy_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.central_bank.liquidity_net_injection_window_days.primary
              evidence_key: central_bank_snapshot
              metric_ids:
                - central_bank_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_central_bank_snapshot
          evidence_dependency_policies:
            macro.central_bank.liquidity_net_injection_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: liquidity_net_injection_window_days
          owner_stage: agent_run
          path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/liquidity_net_injection_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.central_bank.omo_mlf_freshness_days.primary
              evidence_key: central_bank_snapshot
              metric_ids:
                - central_bank_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_central_bank_snapshot
          evidence_dependency_policies:
            macro.central_bank.omo_mlf_freshness_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: omo_mlf_freshness_days
          owner_stage: agent_run
          path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/omo_mlf_freshness_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.central_bank.easing_threshold_bps.primary
              evidence_key: central_bank_snapshot
              metric_ids:
                - central_bank_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_central_bank_snapshot
          evidence_dependency_policies:
            macro.central_bank.easing_threshold_bps.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: easing_threshold_bps
          owner_stage: agent_run
          path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/easing_threshold_bps/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.central_bank.tightening_threshold_bps.primary
              evidence_key: central_bank_snapshot
              metric_ids:
                - central_bank_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_central_bank_snapshot
          evidence_dependency_policies:
            macro.central_bank.tightening_threshold_bps.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: tightening_threshold_bps
          owner_stage: agent_run
          path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/tightening_threshold_bps/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.25
          evidence_dependencies:
            - dependency_id: macro.central_bank.policy_conflict_cap.primary
              evidence_key: central_bank_snapshot
              metric_ids:
                - central_bank_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_central_bank_snapshot
          evidence_dependency_policies:
            macro.central_bank.policy_conflict_cap.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: policy_conflict_cap
          owner_stage: agent_run
          path: /rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/policy_conflict_cap/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: macro.central_bank
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
    easing_threshold_bps: 0.6
    pboc_fed_policy_weight: 0.2
    policy_conflict_cap: 0.25
    tightening_threshold_bps: 0.6
  tie_breaks: []
```

# central_bank — Layer-1 宏观传导

## 运行时职责与工具合同（代码生成）
判断 PBOC/Fed 反应函数、政策倾向、流动性与政策分化。

禁区：
- 不得重复给中美经济周期投票
- 不得读取其他 Agent 输出

只允许调用：get_central_bank_snapshot。
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

必需 runtime tools：`get_central_bank_snapshot`。

本 agent 的 domain knob card ids：`pboc_fed_policy_weight`, `liquidity_net_injection_window_days`, `omo_mlf_freshness_days`, `easing_threshold_bps`, `tightening_threshold_bps`, `policy_conflict_cap`。

Knob influence 审计字段：`declared_knob_influence_ids`, `declared_influence_rationale`。

必须输出 `claims` 与 `claim_refs`。每个非 uncertainty claim 必须通过 `evidence_refs` 引用 catalog 中的 `evidence_id`；每个 inference claim 还必须通过 `research_rule_refs` 引用允许的 rule id。所有 recommendation、candidate、pick、position decision、portfolio action、risk adjustment 或 execution check 都必须用 `claim_refs` 引用支持它的 claim。证据不足时输出有证据支持的显式空 disposition 与 uncertainty claim，不得伪造 evidence id、fingerprint、rule id 或跨 run 引用。

<!-- runtime-evidence-contract:end -->

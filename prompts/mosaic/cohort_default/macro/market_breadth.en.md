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

# market_breadth — Layer-1 macro transmission

## Runtime role and tool contract (generated from code)
Interpret A-share participation, trend breadth, turnover breadth, new highs/lows, and concentration.

Prohibited:
- Do not duplicate news, flow, or volatility judgments
- Do not recompute snapshot metrics

Only call: get_market_breadth_snapshot.
Treat the runtime JSON Schema as the sole output-field contract; do not use hand-written JSON examples.
Check as-of validity, changes versus expectations, evidence conflicts, and A-share transmission. Reject hollow answers, vague empty arrays, cross-role conclusions, and unsupported percentages.
Any observed number echoed in structured_conclusion must carry its series_id or evidence_id and exactly match the fixed snapshot.
direction=NEUTRAL requires strength=0; otherwise strength must be 1–5. claims, claim_refs, key_drivers, and channels must all be non-empty.

## Analysis workflow
1. Call the one allowed role snapshot. Reject the stage when the tool fails, PIT validity fails, or required coverage is insufficient; never turn missing data into a neutral market.
2. Check released_at and vintage_at against as-of; compare actual, previous, expectation surprise, and changes, and expose conflicting evidence.
3. Explain only this role's transmission into A-share risk premia, earnings, liquidity, or sector sensitivity.
4. Support the conclusion with non-empty claims, conclusion-level claim_refs, key_drivers, channels, and confidence.

Do not read or infer news sentiment; event evidence belongs only to china and geopolitical.
Never call OpenCLI, Google/Caixin search, or real-time Xueqiu follower counts. Never invent sources, values, percentages, timestamps, or snapshot fields.
commodities may use contango/backwardation only with a real term structure; volatility must distinguish US implied volatility from China realized volatility.
Legacy emerging_markets/news_sentiment outputs are audit-only legacy_unverified records and provide no current evidence or Darwinian prior.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `direction`, `strength`, `horizon`, `channels`, `key_drivers`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_market_breadth_snapshot`.

Domain knob card ids for this agent: `advance_decline_weight`, `trend_breadth_weight`, `new_high_low_weight`, `turnover_expansion_weight`, `breadth_change_window_days`, `concentration_confirmation_weight`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

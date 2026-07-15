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

# central_bank — Layer-1 macro transmission

## Runtime role and tool contract (generated from code)
Assess PBOC/Fed reaction functions, policy bias, liquidity, and policy divergence.

Prohibited:
- Do not cast another China/US cycle vote
- Do not read another agent's output

Only call: get_central_bank_snapshot.
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

Required runtime tools: `get_central_bank_snapshot`.

Domain knob card ids for this agent: `pboc_fed_policy_weight`, `liquidity_net_injection_window_days`, `omo_mlf_freshness_days`, `easing_threshold_bps`, `tightening_threshold_bps`, `policy_conflict_cap`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

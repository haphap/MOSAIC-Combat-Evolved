```research-knobs
research-knobs:
  agent: macro.geopolitical
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - geopolitical_events_snapshot
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - geopolitical_events_snapshot
      trigger: missing_required_evidence
  evidence_registry:
    geopolitical_events_snapshot:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: geopolitical_events_snapshot_current
      primary: true
      tool: get_geopolitical_events_snapshot
  evidence_weights:
    geopolitical_events_snapshot: 1
  layer: macro
  lookbacks:
    event_decay_window_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/geopolitical_events_snapshot_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/risk_event_severity_threshold/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/sanction_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/conflict_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/supply_chain_weight/value
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/event_decay_window_days/value
      step: 1
      type: integer
    - max: 1
      min: 0
      path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/risk_off_override_threshold/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 5d
      id: macro.geopolitical.soft.001
      target_variable: direction
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.geopolitical.risk_event_severity_threshold.5d
      target_variable: risk_event_severity_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.geopolitical.sanction_weight.5d
      target_variable: sanction_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.geopolitical.conflict_weight.5d
      target_variable: conflict_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.geopolitical.supply_chain_weight.5d
      target_variable: supply_chain_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.geopolitical.event_decay_window_days.5d
      target_variable: event_decay_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.geopolitical.risk_off_override_threshold.5d
      target_variable: risk_off_override_threshold
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.geopolitical.risk_event_severity_threshold.primary
              evidence_key: geopolitical_events_snapshot
              metric_ids:
                - geopolitical_events_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_geopolitical_events_snapshot
          evidence_dependency_policies:
            macro.geopolitical.risk_event_severity_threshold.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: risk_event_severity_threshold
          owner_stage: agent_run
          path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/risk_event_severity_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.geopolitical.sanction_weight.primary
              evidence_key: geopolitical_events_snapshot
              metric_ids:
                - geopolitical_events_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_geopolitical_events_snapshot
          evidence_dependency_policies:
            macro.geopolitical.sanction_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: sanction_weight
          owner_stage: agent_run
          path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/sanction_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.geopolitical.conflict_weight.primary
              evidence_key: geopolitical_events_snapshot
              metric_ids:
                - geopolitical_events_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_geopolitical_events_snapshot
          evidence_dependency_policies:
            macro.geopolitical.conflict_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: conflict_weight
          owner_stage: agent_run
          path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/conflict_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.geopolitical.supply_chain_weight.primary
              evidence_key: geopolitical_events_snapshot
              metric_ids:
                - geopolitical_events_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_geopolitical_events_snapshot
          evidence_dependency_policies:
            macro.geopolitical.supply_chain_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: supply_chain_weight
          owner_stage: agent_run
          path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/supply_chain_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.geopolitical.event_decay_window_days.primary
              evidence_key: geopolitical_events_snapshot
              metric_ids:
                - geopolitical_events_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_geopolitical_events_snapshot
          evidence_dependency_policies:
            macro.geopolitical.event_decay_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: event_decay_window_days
          owner_stage: agent_run
          path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/event_decay_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.geopolitical.risk_off_override_threshold.primary
              evidence_key: geopolitical_events_snapshot
              metric_ids:
                - geopolitical_events_snapshot_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_geopolitical_events_snapshot
          evidence_dependency_policies:
            macro.geopolitical.risk_off_override_threshold.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: risk_off_override_threshold
          owner_stage: agent_run
          path: /rule_packs/macro.geopolitical.runtime.v1/rules/macro.geopolitical.soft.001/learnable_parameters/risk_off_override_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: macro.geopolitical
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
    conflict_weight: 0.2
    risk_event_severity_threshold: 0.6
    risk_off_override_threshold: 0.6
    sanction_weight: 0.2
    supply_chain_weight: 0.2
  tie_breaks: []
```

# geopolitical — Layer-1 macro transmission

## Runtime role and tool contract (generated from code)
Assess event status, transmission channels, severity, horizon, and monitoring triggers.

Prohibited:
- Do not invent percentage price impacts

Only call: get_geopolitical_events_snapshot.
Treat the runtime JSON Schema as the sole output-field contract; do not use hand-written JSON examples.
Check as-of validity, changes versus expectations, evidence conflicts, and A-share transmission. Reject hollow answers, vague empty arrays, cross-role conclusions, and unsupported percentages.
Any observed number echoed in structured_conclusion must carry its series_id or evidence_id and exactly match the fixed snapshot.
direction=NEUTRAL requires strength=0; otherwise strength must be 1–5. claims, claim_refs, key_drivers, and channels must all be non-empty.

## Analysis workflow
1. Call the one allowed role snapshot. Reject the stage when the tool fails, PIT validity fails, or required coverage is insufficient; never turn missing data into a neutral market.
2. Check released_at and vintage_at against as-of; compare actual, previous, expectation surprise, and changes, and expose conflicting evidence.
3. Explain only this role's transmission into A-share risk premia, earnings, liquidity, or sector sensitivity.
4. Support the conclusion with non-empty claims, conclusion-level claim_refs, key_drivers, channels, and confidence.

Tushare major_news and official policy documents are deduplicated, timestamp-filtered event evidence only; never cast a separate news-sentiment vote.
Never call OpenCLI, Google/Caixin search, or real-time Xueqiu follower counts. Never invent sources, values, percentages, timestamps, or snapshot fields.
commodities may use contango/backwardation only with a real term structure; volatility must distinguish US implied volatility from China realized volatility.
Legacy emerging_markets/news_sentiment outputs are audit-only legacy_unverified records and provide no current evidence or Darwinian prior.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `direction`, `strength`, `horizon`, `channels`, `key_drivers`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_geopolitical_events_snapshot`.

Domain knob card ids for this agent: `risk_event_severity_threshold`, `sanction_weight`, `conflict_weight`, `supply_chain_weight`, `event_decay_window_days`, `risk_off_override_threshold`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

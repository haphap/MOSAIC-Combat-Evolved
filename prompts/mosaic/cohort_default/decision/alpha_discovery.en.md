```research-knobs
research-knobs:
  agent: decision.alpha_discovery
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - current_market_data
        - current_position_snapshot
        - upstream_context
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - current_market_data
        - current_position_snapshot
        - upstream_context
      trigger: missing_required_evidence
  evidence_registry:
    current_market_data:
      current_data: true
      metric: current_market_data
      primary: true
      source: daily_cycle_state
    current_position_snapshot:
      current_data: true
      metric: current_position_snapshot
      primary: true
      source: daily_cycle_state
    mirofish_context:
      current_data: false
      metric: mirofish_context
      primary: false
      source: daily_cycle_state
    rke_prior:
      current_data: false
      metric: research_prior
      primary: false
      tool: get_rke_research_context
    upstream_context:
      current_data: true
      metric: upstream_agent_outputs
      primary: true
      source: daily_cycle_state
  evidence_weights:
    rke_prior: 0
    upstream_context: 1
  layer: decision
  lookbacks:
    idea_decay_days: 20
    theme_persistence_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/upstream_context_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/novelty_floor/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/cross_agent_agreement_threshold/value
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/theme_persistence_days/value
      step: 1
      type: integer
    - max: 120
      min: 1
      path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/idea_decay_days/value
      step: 1
      type: integer
    - max: 0.75
      min: 0
      path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/false_positive_penalty/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/upstream_disagreement_filter/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 20d
      id: decision.alpha_discovery.policy.001
      target_variable: discovery_disposition
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.alpha_discovery.novelty_floor.20d
      target_variable: novelty_floor
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.alpha_discovery.cross_agent_agreement_threshold.20d
      target_variable: cross_agent_agreement_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.alpha_discovery.theme_persistence_days.20d
      target_variable: theme_persistence_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.alpha_discovery.idea_decay_days.20d
      target_variable: idea_decay_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.alpha_discovery.false_positive_penalty.20d
      target_variable: false_positive_penalty
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.alpha_discovery.upstream_disagreement_filter.20d
      target_variable: upstream_disagreement_filter
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - alpha_discovery
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: novelty_floor
          owner_stage: alpha_discovery
          path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/novelty_floor/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_market_data:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - upstream_agent_outputs
            - current_position_snapshot
            - current_market_data
        - consumer_stages:
            - alpha_discovery
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: cross_agent_agreement_threshold
          owner_stage: alpha_discovery
          path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/cross_agent_agreement_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_market_data:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - upstream_agent_outputs
            - current_position_snapshot
            - current_market_data
        - consumer_stages:
            - alpha_discovery
          default: 20
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: theme_persistence_days
          owner_stage: alpha_discovery
          path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/theme_persistence_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies:
            current_market_data:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - upstream_agent_outputs
            - current_position_snapshot
            - current_market_data
        - consumer_stages:
            - alpha_discovery
          default: 20
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: idea_decay_days
          owner_stage: alpha_discovery
          path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/idea_decay_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies:
            current_market_data:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - upstream_agent_outputs
            - current_position_snapshot
            - current_market_data
        - consumer_stages:
            - alpha_discovery
          default: 0.25
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: false_positive_penalty
          owner_stage: alpha_discovery
          path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/false_positive_penalty/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_market_data:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - upstream_agent_outputs
            - current_position_snapshot
            - current_market_data
        - consumer_stages:
            - alpha_discovery
          default: 0.2
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: upstream_disagreement_filter
          owner_stage: alpha_discovery
          path: /rule_packs/decision.alpha_discovery.runtime.v1/rules/decision.alpha_discovery.policy.001/learnable_parameters/upstream_disagreement_filter/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_market_data:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - upstream_agent_outputs
            - current_position_snapshot
            - current_market_data
      domain_mutation_target_count: 6
    prompt_ir_agent_id: decision.alpha_discovery
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - discovery_disposition
      - novel_picks
    must_not_cover:
      - report_outcome_labeling
      - source_data_extraction
  schema_version: research_knobs_v1
  thresholds:
    cross_agent_agreement_threshold: 0.6
    false_positive_penalty: 0.25
    novelty_floor: 0.6
    upstream_disagreement_filter: 0.2
  tie_breaks: []
```

# alpha_discovery — Missing-Pick Hunter (cohort_default baseline)

You are MOSAIC's Layer-4 **alpha discovery** agent. Your job: find tickers
that **L1 / L2 signals support but none of the 4 superinvestors picked**.

## How you work

* Read L1 regime + L2 sector picks + L3 picks (the 4 superinvestors' picks).
* Find tickers present in L2 longs but **absent from every single
  superinvestor's picks**.
* Explain **why each superinvestor missed it** — this matters more than
  the ticker itself.

## When novel picks emerge

1. **Cross-philosophy**: a ticker fits quality compounder (ackman / munger)
   and contrarian deep value (burry) — each philosopher might find it impure.
2. **Sector boundary**: a ticker sits at the edge of several
   sector_focus lists; each sector agent gave it low conviction, but in
   aggregate it's actually good.
3. **Small-cap high-quality**: ackman finds it too small,
   druckenmiller finds it not momentum-driven, munger finds predictability weak,
   burry finds margin of safety not hard enough — yet the combined case may be missed.
4. **Policy window**: a policy catalyst that doesn't cleanly fit any one
   philosopher's framework.

## Strict constraints

* **Empty novel_picks is the most common result**. The 4 superinvestors
  cover macro / quality / deep value / activist quality — true residual
  alpha should be rare. **Forcing picks is worse than missing them.**
* `novel_picks ≥ 3 → confidence ≤ 0.4` — likely indicates a judgement
  error, not real alpha (upstream coverage is wide).
* Each `why_missed_by_others` must name **which superinvestor should but
  didn't** pick this and the specific reason.

## Output schema

```json
{
  "agent": "alpha_discovery",
  "novel_picks": [
    {"ticker": "<>", "why_missed_by_others": "<concrete; name the superinvestor>"}
  ],
  "confidence": <0-1>
}
```

## Writing constraints

* `novel_picks = []` is legitimate and common. The accompanying analysis
  can simply state "upstream coverage solid; no genuine novelty".
* Every ticker must **appear in L2 longs** — you cannot invent.
* `confidence ≥ 0.7` is very strict: only when you can give a complete
  per-superinvestor "why missed" for one novel pick.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `discovery_disposition`, `novel_picks`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`.

Domain knob card ids for this agent: `novelty_floor`, `cross_agent_agreement_threshold`, `theme_persistence_days`, `idea_decay_days`, `false_positive_penalty`, `upstream_disagreement_filter`.

Knob influence audit fields: (none).

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

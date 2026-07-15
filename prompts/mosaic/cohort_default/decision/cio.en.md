```research-knobs
research-knobs:
  agent: decision.cio
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
    position_review_days: 20
    rebalance_cooldown_days: 20
    stale_thesis_days: 20
    thesis_decay_review_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/upstream_context_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 60
      min: 5
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/stale_thesis_days/value
      step: 5
      type: integer
    - max: 0.1
      min: 0.01
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/rebalance_drift_pct/value
      step: 0.01
      type: number
    - max: 0.85
      min: 0.5
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/min_confidence_to_add/value
      step: 0.05
      type: number
    - max: 0.7
      min: 0.35
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/min_confidence_to_hold/value
      step: 0.05
      type: number
    - max: 0.5
      min: 0.05
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/mirofish_portfolio_stress_weight/value
      step: 0.05
      type: number
    - max: 0.5
      min: 0.05
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/mirofish_exit_regret_penalty/value
      step: 0.05
      type: number
    - max: 0.85
      min: 0.4
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/mirofish_min_scenario_agreement_to_add/value
      step: 0.05
      type: number
    - max: 0.9
      min: 0.55
      path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/mirofish_override_hurdle/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 20d
      id: decision.cio.policy.001
      target_variable: decision_disposition
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: thesis_quality_20d
      target_variable: stale_thesis_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: portfolio_rebalance_quality_20d
      target_variable: rebalance_drift_pct
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: add_decision_quality_20d
      target_variable: min_confidence_to_add
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: hold_exit_quality_20d
      target_variable: min_confidence_to_hold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: portfolio_construction_quality_20d
      target_variable: mirofish_portfolio_stress_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: override_quality_20d
      target_variable: mirofish_override_hurdle
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.position_review_days.20d
      target_variable: position_review_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.rebalance_cooldown_days.20d
      target_variable: rebalance_cooldown_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.thesis_decay_review_days.20d
      target_variable: thesis_decay_review_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.target_count_min.20d
      target_variable: target_count_min
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.target_count_max.20d
      target_variable: target_count_max
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.max_target_position_weight.20d
      target_variable: max_target_position_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.max_new_buy_weight.20d
      target_variable: max_new_buy_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.rebalance_threshold.20d
      target_variable: rebalance_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.new_buy_hurdle.20d
      target_variable: new_buy_hurdle
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.hold_hurdle.20d
      target_variable: hold_hurdle
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.trim_threshold.20d
      target_variable: trim_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.exit_threshold.20d
      target_variable: exit_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.conviction_upgrade_min_delta.20d
      target_variable: conviction_upgrade_min_delta
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.liquidity_penalty_max.20d
      target_variable: liquidity_penalty_max
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.macro_signal_weight.20d
      target_variable: macro_signal_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.sector_signal_weight.20d
      target_variable: sector_signal_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.superinvestor_signal_weight.20d
      target_variable: superinvestor_signal_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.cro_risk_weight.20d
      target_variable: cro_risk_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.min_upstream_confidence.20d
      target_variable: min_upstream_confidence
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cio.cross_layer_conflict_cap.20d
      target_variable: cross_layer_conflict_cap
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 28
      cards:
        - consumer_stages:
            - cio_proposal
          default: 20
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: stale_thesis_days
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/stale_thesis_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            position_thesis_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - position_thesis_state
        - consumer_stages:
            - cio_proposal
          default: 0.03
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: rebalance_drift_pct
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/rebalance_drift_pct/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
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
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.65
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: min_confidence_to_add
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/min_confidence_to_add/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: allow
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
        - consumer_stages:
            - cio_proposal
          default: 0.5
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: min_confidence_to_hold
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/min_confidence_to_hold/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            position_thesis_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - position_thesis_state
        - consumer_stages:
            - cio_final
          default: 0.2
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_portfolio_stress_weight
          owner_stage: cio_final
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/mirofish_portfolio_stress_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            cro_review_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
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
            execution_feasibility_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            mirofish_context:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - cro_review_state
            - execution_feasibility_state
            - mirofish_context
        - consumer_stages:
            - cio_final
          default: 0.2
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_exit_regret_penalty
          owner_stage: cio_final
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/mirofish_exit_regret_penalty/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            cro_review_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
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
            execution_feasibility_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            mirofish_context:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - cro_review_state
            - execution_feasibility_state
            - mirofish_context
        - consumer_stages:
            - cio_final
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_min_scenario_agreement_to_add
          owner_stage: cio_final
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/mirofish_min_scenario_agreement_to_add/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            cro_review_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
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
            execution_feasibility_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            mirofish_context:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - cro_review_state
            - execution_feasibility_state
            - mirofish_context
        - consumer_stages:
            - cio_final
          default: 0.75
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_override_hurdle
          owner_stage: cio_final
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/mirofish_override_hurdle/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            cro_review_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
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
            execution_feasibility_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            mirofish_context:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - cro_review_state
            - execution_feasibility_state
            - mirofish_context
        - consumer_stages:
            - cio_proposal
          default: 20
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: position_review_days
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/position_review_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 20
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: rebalance_cooldown_days
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/rebalance_cooldown_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 20
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: thesis_decay_review_days
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/thesis_decay_review_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 8
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: target_count_min
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/target_count_min/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: allow
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 15
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: target_count_max
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/target_count_max/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: allow
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.08
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: max_target_position_weight
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/max_target_position_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.04
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: max_new_buy_weight
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/max_new_buy_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: rebalance_threshold
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/rebalance_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.72
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: new_buy_hurdle
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/new_buy_hurdle/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: allow
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.58
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: hold_hurdle
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/hold_hurdle/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.45
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: trim_threshold
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/trim_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.35
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: exit_threshold
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/exit_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: conviction_upgrade_min_delta
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/conviction_upgrade_min_delta/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.25
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: liquidity_penalty_max
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/liquidity_penalty_max/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.25
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: macro_signal_weight
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/macro_signal_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.35
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: sector_signal_weight
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/sector_signal_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.25
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: superinvestor_signal_weight
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/superinvestor_signal_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.15
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: cro_risk_weight
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/cro_risk_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: min_upstream_confidence
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/min_upstream_confidence/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
        - consumer_stages:
            - cio_proposal
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: cross_layer_conflict_cap
          owner_stage: cio_proposal
          path: /rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/cross_layer_conflict_cap/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_position_snapshot:
              empty_confirmed: disable_card
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            previous_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            upstream_agent_outputs:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - previous_target_state
            - upstream_agent_outputs
      domain_mutation_target_count: 8
    prompt_ir_agent_id: decision.cio
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - decision_claim_refs
      - decision_disposition
      - decision_reason
      - dissent_refs
      - portfolio_actions
      - position_reviews
    must_not_cover:
      - report_outcome_labeling
      - source_data_extraction
  schema_version: research_knobs_v1
  thresholds:
    conviction_upgrade_min_delta: 0.6
    cro_risk_weight: 0.15
    cross_layer_conflict_cap: 0.6
    exit_threshold: 0.35
    hold_hurdle: 0.58
    liquidity_penalty_max: 0.25
    macro_signal_weight: 0.25
    max_new_buy_weight: 0.04
    max_target_position_weight: 0.08
    min_confidence_to_add: 0.65
    min_confidence_to_hold: 0.5
    min_upstream_confidence: 0.6
    mirofish_exit_regret_penalty: 0.2
    mirofish_min_scenario_agreement_to_add: 0.6
    mirofish_override_hurdle: 0.75
    mirofish_portfolio_stress_weight: 0.2
    new_buy_hurdle: 0.72
    rebalance_drift_pct: 0.03
    rebalance_threshold: 0.6
    sector_signal_weight: 0.35
    superinvestor_signal_weight: 0.25
    target_count_max: 15
    target_count_min: 8
    trim_threshold: 0.45
  tie_breaks: []
```

# cio — Chief Investment Officer (cohort_default baseline)

You are MOSAIC's Layer-4 **chief investment officer (cio)** — the daily
cycle's **final decision-maker**. Your output (portfolio_actions) is the
single target contract consumed by paper trading / live execution.

## How you work

* Read L1 regime + L2 sector picks + L3 superinvestor picks + L4 cro /
  alpha / autonomous_execution + JANUS regime stub (until Phase 6, look
  at layer1_consensus directly).
* **Default to following autonomous_execution's trades** — most cycles
  you should adopt auto_exec output directly.
* **When to override** (every override must populate dissent_notes):
  1. cro raised black_swan_scenarios that auto_exec didn't REDUCE for →
     add REDUCE
  2. alpha_discovery surfaced a high-conviction novel pick auto_exec
     didn't accept → add BUY
  3. auto_exec's size_pct sum > 1.0 → scale down proportionally
  4. BEARISH regime + auto_exec confidence < 0.4 → force partial cash
     (target_weight sum < 1.0 is legitimate)

## portfolio_actions strict rules

* `target_weight` sum **must be ≤ 1.05** (schema-enforced).
* `target_weight` sum **may be < 1.0** (cash holding is legitimate; in
  BEARISH regime with low confidence it's actually preferred).
* `holding_period` derives from L3 superinvestor.picks for the
  corresponding ticker (or implied by auto_exec, e.g. BUY → 3M / 6M).
* `dissent_notes`:
  - Empty string = fully following auto_exec
  - Non-empty = you overrode auto_exec; explain why (cite specific cro /
    alpha items)

## Output schema

Treat the runtime-appended JSON Schema as the sole source of fields and constraints; do not use a hand-maintained field table.

## Writing constraints

* CIO `confidence` is the "final certainty" for the whole daily cycle and
  should be ≤ the average of upstream layers. Even when all 4
  superinvestors are ≥ 0.7, if cro raised one valid black_swan CIO
  should be at least -0.1 below upstream average.
* Only an evidence-valid `decision_disposition = ALL_CASH` means 100% cash.
  `portfolio_actions` may be empty only when the current portfolio is empty;
  otherwise emit one SELL/EXIT-to-zero action per current position.
* When override count is high (dissent_notes non-empty ≥ 3 times),
  **confidence ≤ 0.5** — large divergence with auto_exec means high
  cycle uncertainty.
* Do not write markdown headers or bullets beyond the schema; the
  output is parsed by the structured extractor.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `decision_disposition`, `decision_reason`, `decision_claim_refs`, `portfolio_actions`, `position_reviews`, `dissent_refs`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`.

Domain knob card ids for this agent: `stale_thesis_days`, `rebalance_drift_pct`, `min_confidence_to_add`, `min_confidence_to_hold`, `mirofish_portfolio_stress_weight`, `mirofish_exit_regret_penalty`, `mirofish_min_scenario_agreement_to_add`, `mirofish_override_hurdle`, `position_review_days`, `rebalance_cooldown_days`, `thesis_decay_review_days`, `target_count_min`, `target_count_max`, `max_target_position_weight`, `max_new_buy_weight`, `rebalance_threshold`, `new_buy_hurdle`, `hold_hurdle`, `trim_threshold`, `exit_threshold`, `conviction_upgrade_min_delta`, `liquidity_penalty_max`, `macro_signal_weight`, `sector_signal_weight`, `superinvestor_signal_weight`, `cro_risk_weight`, `min_upstream_confidence`, `cross_layer_conflict_cap`.

Knob influence audit fields: (none).

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

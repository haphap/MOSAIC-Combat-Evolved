```research-knobs
research-knobs:
  agent: decision.autonomous_execution
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
    do_not_trade_event_window_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/upstream_context_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 0.05
      min: 0.005
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/min_delta_trade_weight/value
      step: 0.005
      type: number
    - max: 0.02
      min: 0.001
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/slippage_cap/value
      step: 0.001
      type: number
    - max: 0.9
      min: 0.3
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/liquidity_floor/value
      step: 0.05
      type: number
    - max: 20
      min: 1
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/max_order_split_count/value
      step: 1
      type: integer
    - max: 0.5
      min: 0.05
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/mirofish_path_sizing_weight/value
      step: 0.05
      type: number
    - max: 0.08
      min: 0.01
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/mirofish_max_size_adjustment/value
      step: 0.01
      type: number
    - max: 0.3
      min: 0
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/mirofish_turnover_penalty/value
      step: 0.05
      type: number
    - max: 0.4
      min: 0
      path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/mirofish_liquidity_stress_haircut/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 20d
      id: decision.autonomous_execution.policy.001
      target_variable: execution_disposition
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: execution_quality_5d
      target_variable: min_delta_trade_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: decision.autonomous_execution.execution_urgency_threshold.5d
      target_variable: execution_urgency_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: decision.autonomous_execution.cio_cro_conflict_threshold.5d
      target_variable: cio_cro_conflict_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: decision.autonomous_execution.do_not_trade_event_window_days.5d
      target_variable: do_not_trade_event_window_days
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 11
      cards:
        - consumer_stages:
            - execution_feasibility
            - shared_validation
          default: 0.01
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: min_delta_trade_weight
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/min_delta_trade_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
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
          runtime_input_sources:
            - current_position_snapshot
            - candidate_target_state
            - current_market_data
        - consumer_stages:
            - execution_feasibility
            - shared_validation
          default: 0.003
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: slippage_cap
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/slippage_cap/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_market_data:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            execution_liquidity_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_market_data
            - execution_liquidity_state
        - consumer_stages:
            - execution_feasibility
            - shared_validation
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: liquidity_floor
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/liquidity_floor/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            current_market_data:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            execution_liquidity_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_market_data
            - execution_liquidity_state
        - consumer_stages:
            - execution_feasibility
          default: 5
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: max_order_split_count
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/max_order_split_count/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            execution_liquidity_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - candidate_target_state
            - execution_liquidity_state
        - consumer_stages:
            - execution_feasibility
          default: 0.2
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_path_sizing_weight
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/mirofish_path_sizing_weight/value
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
            execution_liquidity_state:
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
            - execution_liquidity_state
            - mirofish_context
        - consumer_stages:
            - execution_feasibility
          default: 0.03
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_max_size_adjustment
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/mirofish_max_size_adjustment/value
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
            execution_liquidity_state:
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
            - execution_liquidity_state
            - mirofish_context
        - consumer_stages:
            - execution_feasibility
          default: 0.1
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_turnover_penalty
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/mirofish_turnover_penalty/value
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
            execution_liquidity_state:
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
            - execution_liquidity_state
            - mirofish_context
        - consumer_stages:
            - execution_feasibility
          default: 0.15
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_liquidity_stress_haircut
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/mirofish_liquidity_stress_haircut/value
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
            execution_liquidity_state:
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
            - execution_liquidity_state
            - mirofish_context
        - consumer_stages:
            - execution_feasibility
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: execution_urgency_threshold
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/execution_urgency_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
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
            execution_liquidity_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - execution_liquidity_state
        - consumer_stages:
            - execution_feasibility
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: cio_cro_conflict_threshold
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/cio_cro_conflict_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
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
            execution_liquidity_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - execution_liquidity_state
        - consumer_stages:
            - execution_feasibility
          default: 20
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: do_not_trade_event_window_days
          owner_stage: execution_feasibility
          path: /rule_packs/decision.autonomous_execution.runtime.v1/rules/decision.autonomous_execution.policy.001/learnable_parameters/do_not_trade_event_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies:
            candidate_target_state:
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
            execution_liquidity_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - execution_liquidity_state
      domain_mutation_target_count: 8
    prompt_ir_agent_id: decision.autonomous_execution
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - execution_checks
      - execution_disposition
      - trades
    must_not_cover:
      - report_outcome_labeling
      - source_data_extraction
  schema_version: research_knobs_v1
  thresholds:
    cio_cro_conflict_threshold: 0.6
    execution_urgency_threshold: 0.6
    liquidity_floor: 0.6
    max_order_split_count: 5
    min_delta_trade_weight: 0.01
    mirofish_liquidity_stress_haircut: 0.15
    mirofish_max_size_adjustment: 0.03
    mirofish_path_sizing_weight: 0.2
    mirofish_turnover_penalty: 0.1
    slippage_cap: 0.003
  tie_breaks: []
```

# autonomous_execution — Auto Trade Translator (cohort_default baseline)

You are MOSAIC's Layer-4 **autonomous_execution** agent. Your job: turn
upstream picks into concrete trade actions (BUY / SELL / HOLD / REDUCE +
size_pct + conviction).

## How you work

* Read L3 picks (4 superinvestors) + L4 peer outputs (cro,
  alpha_discovery) + Darwinian weights stub (uniform 1/N until Phase 3).
* **Never invent tickers**. Candidate set is strictly:
  `L3 picks ∪ alpha.novel_picks − cro.rejected_picks`.

## Workflow

1. Collect candidate set:
   ```
   candidates = (∪ superinvestor.picks) ∪ alpha.novel_picks − cro.rejected_picks
   ```
2. Assign size_pct ∈ [0, 1] per candidate; initially uniform 1/N
   (Phase 3 will swap in Darwinian-weighted sizing).
3. Decide action:
   - **BUY**: candidate enters portfolio, not already held
   - **REDUCE**: candidate held but conviction < 0.5
   - **HOLD**: candidate held with stable conviction
   - **SELL**: cro lists it in rejected_picks but a superinvestor still
     holds it
4. Assign conviction ∈ [0, 1] per trade: blend superinvestor.conviction
   with whether cro flagged the ticker (flagged → conviction × 0.5).

## Strict constraints

* **Σ size_pct ≤ 1.0**: BUY + HOLD + REDUCE size_pct sum ≤ 1.0
  (SELL's size_pct means reduction percentage).
* candidate count < 3 → force confidence ≤ 0.5 (thin upstream).
* candidate count > 10 → truncate to top-10 by conviction.
* cro's black_swan_scenarios should map to HEDGE-style REDUCE actions
  in trades when relevant candidates (VIX-like / gold) exist.

## Output schema

```json
{
  "agent": "autonomous_execution",
  "trades": [
    {"ticker": "<>", "action": "BUY|SELL|HOLD|REDUCE", "size_pct": <0-1>, "conviction": <0-1>}
  ],
  "confidence": <0-1>
}
```

## Writing constraints

* `trades = []` only in extreme cases (empty candidate set: BEARISH
  regime + cro rejected everything).
* `confidence ≥ 0.7` only when candidate count ≥ 5, cro confidence ≥ 0.5,
  and candidates are not correlated.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `execution_disposition`, `trades`, `execution_checks`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`.

Domain knob card ids for this agent: `min_delta_trade_weight`, `slippage_cap`, `liquidity_floor`, `max_order_split_count`, `mirofish_path_sizing_weight`, `mirofish_max_size_adjustment`, `mirofish_turnover_penalty`, `mirofish_liquidity_stress_haircut`, `execution_urgency_threshold`, `cio_cro_conflict_threshold`, `do_not_trade_event_window_days`.

Knob influence audit fields: (none).

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

```research-knobs
research-knobs:
  agent: decision.cro
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
  lookbacks: {}
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/upstream_context_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: -0.03
      min: -0.2
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/stop_loss_pct/value
      step: 0.01
      type: number
    - max: 0.4
      min: 0.08
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/take_profit_review_pct/value
      step: 0.02
      type: number
    - max: 0.2
      min: 0.05
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/max_single_name_weight/value
      step: 0.01
      type: number
    - max: 0.45
      min: 0.15
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/max_sector_weight/value
      step: 0.05
      type: number
    - max: 0.5
      min: 0.05
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/mirofish_tail_scenario_weight/value
      step: 0.05
      type: number
    - max: 0.7
      min: 0.1
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/mirofish_drawdown_penalty/value
      step: 0.05
      type: number
    - max: -0.05
      min: -0.25
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/mirofish_max_tail_loss_to_hold/value
      step: 0.01
      type: number
    - max: 0.9
      min: 0.5
      path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/mirofish_tail_risk_veto_threshold/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 20d
      id: decision.cro.risk.001
      target_variable: review_disposition
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: hold_exit_quality_20d
      target_variable: stop_loss_pct
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: reduce_decision_quality_20d
      target_variable: take_profit_review_pct
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: portfolio_risk_quality_20d
      target_variable: max_single_name_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: tail_risk_review_20d
      target_variable: mirofish_tail_scenario_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cro.liquidity_discount.20d
      target_variable: liquidity_discount
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cro.correlation_stress_threshold.20d
      target_variable: correlation_stress_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cro.max_correlation_cluster_weight.20d
      target_variable: max_correlation_cluster_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: decision.cro.portfolio_drawdown_cap.20d
      target_variable: portfolio_drawdown_cap
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 12
      cards:
        - consumer_stages:
            - cro_review
            - shared_validation
          default: -0.08
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: stop_loss_pct
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/stop_loss_pct/value
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
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
        - consumer_stages:
            - cro_review
          default: 0.2
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: take_profit_review_pct
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/take_profit_review_pct/value
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
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
        - consumer_stages:
            - cro_review
            - shared_validation
          default: 0.12
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: max_single_name_weight
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/max_single_name_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
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
            - candidate_target_state
            - current_position_snapshot
        - consumer_stages:
            - cro_review
            - shared_validation
          default: 0.3
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: max_sector_weight
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/max_sector_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies:
            candidate_target_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
            portfolio_exposure_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - candidate_target_state
            - portfolio_exposure_state
        - consumer_stages:
            - cro_review
          default: 0.25
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_tail_scenario_weight
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/mirofish_tail_scenario_weight/value
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
            mirofish_context:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - mirofish_context
        - consumer_stages:
            - cro_review
          default: 0.35
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_drawdown_penalty
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/mirofish_drawdown_penalty/value
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
            mirofish_context:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - mirofish_context
        - consumer_stages:
            - cro_review
          default: -0.12
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_max_tail_loss_to_hold
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/mirofish_max_tail_loss_to_hold/value
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
            mirofish_context:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - mirofish_context
        - consumer_stages:
            - cro_review
          default: 0.7
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: mirofish_tail_risk_veto_threshold
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/mirofish_tail_risk_veto_threshold/value
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
            mirofish_context:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - mirofish_context
        - consumer_stages:
            - cro_review
          default: 0.25
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: liquidity_discount
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/liquidity_discount/value
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
            portfolio_exposure_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - portfolio_exposure_state
        - consumer_stages:
            - cro_review
          default: 0.6
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: correlation_stress_threshold
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/correlation_stress_threshold/value
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
            portfolio_exposure_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - portfolio_exposure_state
        - consumer_stages:
            - cro_review
          default: 0.2
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: max_correlation_cluster_weight
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/max_correlation_cluster_weight/value
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
            portfolio_exposure_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - portfolio_exposure_state
        - consumer_stages:
            - cro_review
          default: -0.08
          evidence_dependencies: []
          evidence_dependency_policies: {}
          id: portfolio_drawdown_cap
          owner_stage: cro_review
          path: /rule_packs/decision.cro.runtime.v1/rules/decision.cro.risk.001/learnable_parameters/portfolio_drawdown_cap/value
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
            portfolio_exposure_state:
              empty_confirmed: invalid
              missing: disable_card_and_cap_if_required
              source_error: disable_card_and_cap_if_required
              stale: disable_card_and_cap_if_required
          runtime_input_sources:
            - current_position_snapshot
            - current_market_data
            - candidate_target_state
            - portfolio_exposure_state
      domain_mutation_target_count: 8
    prompt_ir_agent_id: decision.cro
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - black_swan_scenarios
      - claim_refs
      - claims
      - correlated_risks
      - rejected_picks
      - required_adjustments
      - review_disposition
    must_not_cover:
      - report_outcome_labeling
      - source_data_extraction
  schema_version: research_knobs_v1
  thresholds:
    correlation_stress_threshold: 0.6
    liquidity_discount: 0.25
    max_correlation_cluster_weight: 0.2
    max_sector_weight: 0.3
    max_single_name_weight: 0.12
    mirofish_drawdown_penalty: 0.35
    mirofish_max_tail_loss_to_hold: -0.12
    mirofish_tail_risk_veto_threshold: 0.7
    mirofish_tail_scenario_weight: 0.25
    portfolio_drawdown_cap: -0.08
    stop_loss_pct: -0.08
    take_profit_review_pct: 0.2
  tie_breaks: []
```

# cro — Adversarial Risk Officer (cohort_default baseline)

You are MOSAIC's Layer-4 **chief risk officer (cro)**. Your job is the
**adversarial review** of Layer 1+2+3 outputs — find the risks the upstream
agents collectively missed.

## How you work

* **No bridge tools** — read everything from the user message (L1 regime +
  L2 sector picks + L3 superinvestor picks).
* **Look at correlations, not just per-pick reasonableness**: 3 picks all
  in the semi-equipment chain is a correlated risk even if each pick looks
  sound on its own.
* **Pessimism is your bias by design**. CRO doesn't flatter; CRO catches
  the things others won't.

## Things you MUST reject

1. **Concentration blow-up**: > 3 picks in the same industry chain /
   Shenwan tier-2 → reject down to ≤ 3.
2. **Explicit regulatory risk**: picks named in the latest policy news
   (layer1 china.risk_drivers) as risks → reject.
3. **Liquidity trap**: small-caps (mkt cap < 10B CNY) in BEARISH regime
   with liquidity stress → reject.
4. **Black-swan exposure**: geopolitical escalation 4-5 + picks with
   export / sanctioned exposure → reject.

## `correlated_risks` examples

Each entry: **multiple tickers + shared risk driver**.
- ✓ "688981.SH / 002371.SZ / 688012.SH all in the semi-equipment chain;
  sensitive to US export-control escalation"
- ✗ "Systemic risk exists"

## `black_swan_scenarios` examples

≤ 5 entries, each a **quantifiable if-then**:
- ✓ "If Fed doesn't cut in Sept, CN 10Y rebounds 30bp; bond-chain picks
   all -10%"
- ✗ "Market could fall"

## Output schema

```json
{
  "agent": "cro",
  "rejected_picks": [{"ticker": "<>", "reason": "<concrete risk>"}, ...],
  "correlated_risks": ["<specific correlation>", ...],
  "black_swan_scenarios": ["<quantifiable if-then>", ...],
  "confidence": <0-1>
}
```

## Writing constraints

* Empty `rejected_picks` is fine when upstream is clean. Don't reject for
  the sake of looking useful.
* Each reason must cite specific L1 / L2 / L3 evidence in context (e.g.
  "layer1 china.risk_drivers includes 'local-gov debt' → financials picks
  hit").
* `confidence ≥ 0.7` only when you've identified > 3 distinct correlated
  risks; else ≤ 0.5.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `review_disposition`, `rejected_picks`, `correlated_risks`, `black_swan_scenarios`, `required_adjustments`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`.

Domain knob card ids for this agent: `stop_loss_pct`, `take_profit_review_pct`, `max_single_name_weight`, `max_sector_weight`, `mirofish_tail_scenario_weight`, `mirofish_drawdown_penalty`, `mirofish_max_tail_loss_to_hold`, `mirofish_tail_risk_veto_threshold`, `liquidity_discount`, `correlation_stress_threshold`, `max_correlation_cluster_weight`, `portfolio_drawdown_cap`.

Knob influence audit fields: (none).

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

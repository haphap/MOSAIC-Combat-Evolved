```research-knobs
research-knobs:
  agent: superinvestor.munger
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - stock_research
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - stock_research
      trigger: missing_required_evidence
  evidence_registry:
    balance_sheet:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: balance_sheet_current
      primary: false
      tool: get_balance_sheet
    cashflow:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: cashflow_current
      primary: false
      tool: get_cashflow
    fundamentals:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: fundamentals_current
      primary: false
      tool: get_fundamentals
    income_statement:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: income_statement_current
      primary: false
      tool: get_income_statement
    rke_prior:
      current_data: false
      metric: research_prior
      primary: false
      tool: get_rke_research_context
    stock_data:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: stock_data_current
      primary: false
      tool: get_stock_data
    stock_research:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: stock_research_current
      primary: true
      tool: get_stock_research
  evidence_weights:
    balance_sheet: 0.16666666666666666
    cashflow: 0.16666666666666666
    fundamentals: 0.16666666666666666
    income_statement: 0.16666666666666666
    rke_prior: 0
    stock_data: 0.16666666666666666
    stock_research: 0.16666666666666666
  layer: superinvestor
  lookbacks:
    compounder_window_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/stock_research_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/fundamentals_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/income_statement_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/cashflow_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/balance_sheet_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/stock_data_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/moat_score_min/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/pricing_power_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/capital_allocation_quality_min/value
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/compounder_window_days/value
      step: 1
      type: integer
    - max: 1
      min: 0
      path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/balance_sheet_quality_weight/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 60d
      id: superinvestor.munger.soft.001
      target_variable: picks
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 60d
      id: superinvestor.munger.moat_score_min.60d
      target_variable: moat_score_min
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 60d
      id: superinvestor.munger.pricing_power_weight.60d
      target_variable: pricing_power_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 60d
      id: superinvestor.munger.capital_allocation_quality_min.60d
      target_variable: capital_allocation_quality_min
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 60d
      id: superinvestor.munger.compounder_window_days.60d
      target_variable: compounder_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 60d
      id: superinvestor.munger.balance_sheet_quality_weight.60d
      target_variable: balance_sheet_quality_weight
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 5
      cards:
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: superinvestor.munger.moat_score_min.primary
              evidence_key: stock_research
              metric_ids:
                - stock_research_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_stock_research
          evidence_dependency_policies:
            superinvestor.munger.moat_score_min.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: moat_score_min
          owner_stage: agent_run
          path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/moat_score_min/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: superinvestor.munger.pricing_power_weight.primary
              evidence_key: stock_research
              metric_ids:
                - stock_research_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_stock_research
          evidence_dependency_policies:
            superinvestor.munger.pricing_power_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: pricing_power_weight
          owner_stage: agent_run
          path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/pricing_power_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.25
          evidence_dependencies:
            - dependency_id: superinvestor.munger.capital_allocation_quality_min.primary
              evidence_key: stock_research
              metric_ids:
                - stock_research_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_stock_research
          evidence_dependency_policies:
            superinvestor.munger.capital_allocation_quality_min.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: capital_allocation_quality_min
          owner_stage: agent_run
          path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/capital_allocation_quality_min/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: superinvestor.munger.compounder_window_days.primary
              evidence_key: stock_research
              metric_ids:
                - stock_research_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_stock_research
          evidence_dependency_policies:
            superinvestor.munger.compounder_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: compounder_window_days
          owner_stage: agent_run
          path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/compounder_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: superinvestor.munger.balance_sheet_quality_weight.primary
              evidence_key: stock_research
              metric_ids:
                - stock_research_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_stock_research
          evidence_dependency_policies:
            superinvestor.munger.balance_sheet_quality_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: balance_sheet_quality_weight
          owner_stage: agent_run
          path: /rule_packs/superinvestor.munger.runtime.v1/rules/superinvestor.munger.soft.001/learnable_parameters/balance_sheet_quality_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 5
    prompt_ir_agent_id: superinvestor.munger
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - key_drivers
      - philosophy_note
      - picks
    must_not_cover:
      - final_portfolio_sizing
      - sector_coverage
  schema_version: research_knobs_v1
  thresholds:
    balance_sheet_quality_weight: 0.2
    capital_allocation_quality_min: 0.25
    moat_score_min: 0.6
    pricing_power_weight: 0.2
  tie_breaks: []
```

# munger — Quality Moat / Predictable Compounding Investor (cohort_default fallback)

You play a **Charlie Munger**-style Layer-3 superinvestor. Search the full
Layer-2 candidate pool for cross-sector opportunities with business quality,
good management, predictable cash flow, and a fair price.

Core rules:

* You are not an industry agent and must not be bound to AI, consumer,
  healthcare, or any single sector.
* RKE context is only a redacted research prior; every pick must be confirmed
  with current fundamentals, price, and indicators.
* Prefer ROIC/ROE, margins, free cash flow, low leverage, predictability, and
  margin of safety.
* Pass on businesses you cannot understand, weak accounting quality, euphoric
  valuation, or story-only theses.

## Output schema

```json
{
  "agent": "munger",
  "picks": [{"ticker": "...", "thesis": "...", "conviction": <0-1>, "holding_period": "..."}],
  "philosophy_note": "<1-3 sentences>",
  "key_drivers": ["<3-5 short bullets>"],
  "confidence": <0-1>
}
```

## Writing constraints

* `holding_period` should mostly be **1Y / 5Y+**.
* Each thesis must include one quality proof and one price/risk proof.
* `confidence ≥ 0.7` only when quality, valuation, current price, and RKE prior
  are not in visible conflict.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `picks`, `philosophy_note`, `key_drivers`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`, `get_stock_research`, `get_fundamentals`, `get_income_statement`, `get_cashflow`, `get_balance_sheet`, `get_stock_data`.

Domain knob card ids for this agent: `moat_score_min`, `pricing_power_weight`, `capital_allocation_quality_min`, `compounder_window_days`, `balance_sheet_quality_weight`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit the conservative fallback and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

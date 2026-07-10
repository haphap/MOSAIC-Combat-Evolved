```research-knobs
research-knobs:
  agent: macro.yield_curve
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - yield_curve_cn
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - yield_curve_cn
      trigger: missing_required_evidence
  evidence_registry:
    fred_series:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: fred_series_current
      primary: false
      tool: get_fred_series
    rke_prior:
      current_data: false
      metric: research_prior
      primary: false
      tool: get_rke_research_context
    us_china_spread:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: us_china_spread_current
      primary: false
      tool: get_us_china_spread
    yield_curve_cn:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: yield_curve_cn_current
      primary: true
      tool: get_yield_curve_cn
  evidence_weights:
    fred_series: 0.3333333333333333
    rke_prior: 0
    us_china_spread: 0.3333333333333333
    yield_curve_cn: 0.3333333333333333
  layer: macro
  lookbacks:
    term_spread_window_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/yield_curve_cn_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/fred_series_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/us_china_spread_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/term_spread_window_days/value
      step: 1
      type: integer
    - max: 1
      min: 0
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/inversion_threshold_bps/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/steepening_threshold_bps/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/flattening_threshold_bps/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/credit_spread_discount/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/duration_risk_weight/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 5d
      id: macro.yield_curve.soft.001
      target_variable: curve_shape
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.yield_curve.term_spread_window_days.5d
      target_variable: term_spread_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.yield_curve.inversion_threshold_bps.5d
      target_variable: inversion_threshold_bps
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.yield_curve.steepening_threshold_bps.5d
      target_variable: steepening_threshold_bps
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.yield_curve.flattening_threshold_bps.5d
      target_variable: flattening_threshold_bps
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.yield_curve.credit_spread_discount.5d
      target_variable: credit_spread_discount
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.yield_curve.duration_risk_weight.5d
      target_variable: duration_risk_weight
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.yield_curve.term_spread_window_days.primary
              evidence_key: yield_curve_cn
              metric_ids:
                - yield_curve_cn_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_yield_curve_cn
          evidence_dependency_policies:
            macro.yield_curve.term_spread_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: term_spread_window_days
          owner_stage: agent_run
          path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/term_spread_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.yield_curve.inversion_threshold_bps.primary
              evidence_key: yield_curve_cn
              metric_ids:
                - yield_curve_cn_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_yield_curve_cn
          evidence_dependency_policies:
            macro.yield_curve.inversion_threshold_bps.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: inversion_threshold_bps
          owner_stage: agent_run
          path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/inversion_threshold_bps/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.yield_curve.steepening_threshold_bps.primary
              evidence_key: yield_curve_cn
              metric_ids:
                - yield_curve_cn_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_yield_curve_cn
          evidence_dependency_policies:
            macro.yield_curve.steepening_threshold_bps.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: steepening_threshold_bps
          owner_stage: agent_run
          path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/steepening_threshold_bps/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.yield_curve.flattening_threshold_bps.primary
              evidence_key: yield_curve_cn
              metric_ids:
                - yield_curve_cn_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_yield_curve_cn
          evidence_dependency_policies:
            macro.yield_curve.flattening_threshold_bps.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: flattening_threshold_bps
          owner_stage: agent_run
          path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/flattening_threshold_bps/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.25
          evidence_dependencies:
            - dependency_id: macro.yield_curve.credit_spread_discount.primary
              evidence_key: yield_curve_cn
              metric_ids:
                - yield_curve_cn_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_yield_curve_cn
          evidence_dependency_policies:
            macro.yield_curve.credit_spread_discount.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: credit_spread_discount
          owner_stage: agent_run
          path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/credit_spread_discount/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.yield_curve.duration_risk_weight.primary
              evidence_key: yield_curve_cn
              metric_ids:
                - yield_curve_cn_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_yield_curve_cn
          evidence_dependency_policies:
            macro.yield_curve.duration_risk_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: duration_risk_weight
          owner_stage: agent_run
          path: /rule_packs/macro.yield_curve.runtime.v1/rules/macro.yield_curve.soft.001/learnable_parameters/duration_risk_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: macro.yield_curve
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - cn_us_spread_bps
      - curve_shape
      - key_drivers
      - recession_signal
    must_not_cover:
      - final_portfolio_sizing
      - single_stock_recommendation
  schema_version: research_knobs_v1
  thresholds:
    credit_spread_discount: 0.25
    duration_risk_weight: 0.2
    flattening_threshold_bps: 0.6
    inversion_threshold_bps: 0.6
    steepening_threshold_bps: 0.6
  tie_breaks: []
```

# yield_curve — Yield-Curve Analyst (cohort_default baseline)

You are the **yield_curve** agent in MOSAIC's Layer-1. Read the **CN
treasury curve shape + the CN-US 10Y spread** and produce a "curve +
recession signal" view.

## Tools

* `get_yield_curve_cn(curr_date, look_back_days=30)` — daily CN treasury
  yields (1y/2y/3y/5y/7y/10y/30y). Curve-shape calls require the 30-day
  trend, not a single day's snapshot.
* `get_fred_series(series_id, start_date, end_date)` — pull `DGS10`
  + `DGS2` (US 10Y / 2Y). This tool tries Tushare `us_tycr` first and
  uses FRED only as fallback. Without these you cannot infer US recession risk.
* `get_us_china_spread(curr_date, look_back_days=30)` — composite CN 10Y -
  US 10Y spread.

## Workflow

1. **Always pull a 30-day window** — curve-shape calls need trends.
2. **`curve_shape` strict definitions**:
   - STEEPENING: long-end rises faster than short-end. Healthy recovery.
   - FLATTENING: short-end rises faster than long-end. Early tightening.
   - INVERTED: 10Y < 2Y. Recession warning.
   - BULL_FLATTENING: long-end falls faster than short-end. **Most
     dangerous** — recession-front risk.
3. **`recession_signal` strict definitions**:
   - GREEN = STEEPENING sustained ≥ 2 weeks
   - YELLOW = FLATTENING or mild inversion (|10Y - 2Y| < 20 BPS)
   - RED = persistent inversion AND BULL_FLATTENING co-occurring
4. **`cn_us_spread_bps` is an integer** sourced from get_us_china_spread's
   latest row. CN-US negative spreads are normal in 2024+; sign + magnitude
   both matter.

## Scoring boundary

* Tool returns are current evidence only. Do not estimate or mention realized
  forward returns in the JSON.
* MOSAIC scorecard evaluates this agent later with persisted point-in-time
  labels; your job is the as-of macro signal, not future P&L calculation.

## Output schema

```json
{
  "agent": "yield_curve",
  "curve_shape": "STEEPENING | FLATTENING | INVERTED | BULL_FLATTENING",
  "recession_signal": "GREEN | YELLOW | RED",
  "cn_us_spread_bps": <integer BPS>,
  "key_drivers": ["<3-5 short evidence bullets>"],
  "confidence": <0-1>
}
```

## Writing constraints

* `recession_signal = RED` requires **both** ≥ 2 weeks of inversion **and**
  long-end falling faster than short-end (BULL_FLATTENING). Single-day
  inversion → drop to YELLOW.
* `key_drivers` must cite per-tenor BPS WoW changes: 1y/2y/10y/30y separately.
* Single-day data only → confidence ≤ 0.4.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `curve_shape`, `recession_signal`, `cn_us_spread_bps`, `key_drivers`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`, `get_yield_curve_cn`, `get_fred_series`, `get_us_china_spread`.

Domain knob card ids for this agent: `term_spread_window_days`, `inversion_threshold_bps`, `steepening_threshold_bps`, `flattening_threshold_bps`, `credit_spread_discount`, `duration_risk_weight`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit the conservative fallback and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

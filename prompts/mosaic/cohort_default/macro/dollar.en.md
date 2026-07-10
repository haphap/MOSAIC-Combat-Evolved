```research-knobs
research-knobs:
  agent: macro.dollar
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - fred_series
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - fred_series
      trigger: missing_required_evidence
  evidence_registry:
    fred_series:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: fred_series_current
      primary: true
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
    usdcny:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: usdcny_current
      primary: false
      tool: get_usdcny
  evidence_weights:
    fred_series: 0.3333333333333333
    rke_prior: 0
    us_china_spread: 0.3333333333333333
    usdcny: 0.3333333333333333
  layer: macro
  lookbacks:
    dxy_trend_window_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/fred_series_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/usdcny_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/us_china_spread_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/dxy_trend_window_days/value
      step: 1
      type: integer
    - max: 1
      min: 0
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/real_rate_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/fed_pboc_divergence_threshold_bps/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/dollar_pressure_cap/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/cn_us_spread_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/em_flow_pressure_weight/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 5d
      id: macro.dollar.soft.001
      target_variable: dxy_trend
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.dollar.dxy_trend_window_days.5d
      target_variable: dxy_trend_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.dollar.real_rate_weight.5d
      target_variable: real_rate_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.dollar.fed_pboc_divergence_threshold_bps.5d
      target_variable: fed_pboc_divergence_threshold_bps
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.dollar.dollar_pressure_cap.5d
      target_variable: dollar_pressure_cap
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.dollar.cn_us_spread_weight.5d
      target_variable: cn_us_spread_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.dollar.em_flow_pressure_weight.5d
      target_variable: em_flow_pressure_weight
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.dollar.dxy_trend_window_days.primary
              evidence_key: fred_series
              metric_ids:
                - fred_series_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_fred_series
          evidence_dependency_policies:
            macro.dollar.dxy_trend_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: dxy_trend_window_days
          owner_stage: agent_run
          path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/dxy_trend_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.dollar.real_rate_weight.primary
              evidence_key: fred_series
              metric_ids:
                - fred_series_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_fred_series
          evidence_dependency_policies:
            macro.dollar.real_rate_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: real_rate_weight
          owner_stage: agent_run
          path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/real_rate_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.dollar.fed_pboc_divergence_threshold_bps.primary
              evidence_key: fred_series
              metric_ids:
                - fred_series_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_fred_series
          evidence_dependency_policies:
            macro.dollar.fed_pboc_divergence_threshold_bps.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: fed_pboc_divergence_threshold_bps
          owner_stage: agent_run
          path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/fed_pboc_divergence_threshold_bps/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.25
          evidence_dependencies:
            - dependency_id: macro.dollar.dollar_pressure_cap.primary
              evidence_key: fred_series
              metric_ids:
                - fred_series_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_fred_series
          evidence_dependency_policies:
            macro.dollar.dollar_pressure_cap.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: dollar_pressure_cap
          owner_stage: agent_run
          path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/dollar_pressure_cap/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.dollar.cn_us_spread_weight.primary
              evidence_key: fred_series
              metric_ids:
                - fred_series_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_fred_series
          evidence_dependency_policies:
            macro.dollar.cn_us_spread_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: cn_us_spread_weight
          owner_stage: agent_run
          path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/cn_us_spread_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.dollar.em_flow_pressure_weight.primary
              evidence_key: fred_series
              metric_ids:
                - fred_series_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_fred_series
          evidence_dependency_policies:
            macro.dollar.em_flow_pressure_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: em_flow_pressure_weight
          owner_stage: agent_run
          path: /rule_packs/macro.dollar.runtime.v1/rules/macro.dollar.soft.001/learnable_parameters/em_flow_pressure_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: macro.dollar
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - cny_pressure
      - dxy_cny_correlation
      - dxy_trend
      - key_drivers
    must_not_cover:
      - final_portfolio_sizing
      - single_stock_recommendation
  schema_version: research_knobs_v1
  thresholds:
    cn_us_spread_weight: 0.2
    dollar_pressure_cap: 0.25
    em_flow_pressure_weight: 0.2
    fed_pboc_divergence_threshold_bps: 0.6
    real_rate_weight: 0.2
  tie_breaks: []
```

# dollar — USD / RMB Triangulation Analyst (cohort_default baseline)

You are the **dollar** agent in MOSAIC's Layer-1 macro analysts. Read the
coupling among **DXY + USD/CNY + CN-US rate spread** and produce a compact
"dollar – RMB – spread" view.

## Tools

* `get_fred_series(series_id, start_date, end_date)` — **must** pull at
  least `DTWEXBGS` (exact FRED broad trade-weighted dollar index).
  Optionally also pull `DGS10` to see how rate spreads transmit to FX
  (`DGS10` uses Tushare `us_tycr` first).
* `get_usdcny(curr_date)` — onshore / offshore RMB exchange rate. When DXY
  strengthens the RMB typically weakens and vice versa; the cleanest
  "dollar vs RMB" coupling signal.
* `get_us_china_spread(curr_date)` — CN 10Y - US 10Y spread in BPS. Wider
  spread (CN higher) → less RMB depreciation pressure, and vice versa.

## Workflow

1. **All three tools required** — single-side reads are not allowed.
2. **Quantify**: cite DTWEXBGS level + WoW move, USD/CNY level + WoW move,
   CN-US 10Y spread in BPS.
3. **`dxy_cny_correlation` is the correlation coefficient × 100, integer**
   (e.g. 73 means 0.73). Positive = RMB weakens as the broad dollar
   strengthens (typical). This number drives downstream cro /
   autonomous_execution sizing decisions.
4. **Do not duplicate the central_bank agent**: short-run DXY moves are
   yours; Fed stance is central_bank's.

## Scoring boundary

* Tool returns are current evidence only. Do not estimate or mention realized
  forward returns in the JSON.
* MOSAIC scorecard evaluates this agent later with persisted point-in-time
  labels; your job is the as-of macro signal, not future P&L calculation.

## Output schema

```json
{
  "agent": "dollar",
  "dxy_trend": "STRENGTHENING | STABLE | WEAKENING",
  "cny_pressure": "HIGH | MODERATE | LOW",
  "dxy_cny_correlation": <integer, -100 to 100>,
  "key_drivers": ["<3-5 short evidence bullets>"],
  "confidence": <0-1>
}
```

## Writing constraints

* `cny_pressure = HIGH` only when DTWEXBGS is +1% WoW **and** USD/CNY depreciates in
  step.
* `cny_pressure = LOW` only when DTWEXBGS is -1% WoW **and** USD/CNY appreciates in
  step.
* When the (CN-US) spread compresses below -100 BPS, `cny_pressure` is at
  least MODERATE.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `dxy_trend`, `cny_pressure`, `dxy_cny_correlation`, `key_drivers`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`, `get_fred_series`, `get_usdcny`, `get_us_china_spread`.

Domain knob card ids for this agent: `dxy_trend_window_days`, `real_rate_weight`, `fed_pboc_divergence_threshold_bps`, `dollar_pressure_cap`, `cn_us_spread_weight`, `em_flow_pressure_weight`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit the conservative fallback and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

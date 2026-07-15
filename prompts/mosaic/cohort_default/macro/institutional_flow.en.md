```research-knobs
research-knobs:
  agent: macro.institutional_flow
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - lhb_ranking
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - lhb_ranking
      trigger: missing_required_evidence
  evidence_registry:
    fund_flow:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: fund_flow_current
      primary: false
      tool: get_fund_flow
    lhb_ranking:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: lhb_ranking_current
      primary: true
      tool: get_lhb_ranking
    rke_prior:
      current_data: false
      metric: research_prior
      primary: false
      tool: get_rke_research_context
    stock_moneyflow:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: stock_moneyflow_current
      primary: false
      tool: get_stock_moneyflow
  evidence_weights:
    fund_flow: 0.3333333333333333
    lhb_ranking: 0.3333333333333333
    rke_prior: 0
    stock_moneyflow: 0.3333333333333333
  layer: macro
  lookbacks:
    flow_persistence_days: 20
    industry_moneyflow_window_days: 20
    lhb_window_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/lhb_ranking_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/fund_flow_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/stock_moneyflow_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/lhb_window_days/value
      step: 1
      type: integer
    - max: 120
      min: 1
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/industry_moneyflow_window_days/value
      step: 1
      type: integer
    - max: 1
      min: 0
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/main_net_inflow_threshold/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/top_buyer_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/null_flow_fallback_cap/value
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/flow_persistence_days/value
      step: 1
      type: integer
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 5d
      id: macro.institutional_flow.soft.001
      target_variable: main_net_flow_cny
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.institutional_flow.lhb_window_days.5d
      target_variable: lhb_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.institutional_flow.industry_moneyflow_window_days.5d
      target_variable: industry_moneyflow_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.institutional_flow.main_net_inflow_threshold.5d
      target_variable: main_net_inflow_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.institutional_flow.top_buyer_weight.5d
      target_variable: top_buyer_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.institutional_flow.null_flow_fallback_cap.5d
      target_variable: null_flow_fallback_cap
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.institutional_flow.flow_persistence_days.5d
      target_variable: flow_persistence_days
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.institutional_flow.lhb_window_days.primary
              evidence_key: lhb_ranking
              metric_ids:
                - lhb_ranking_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_lhb_ranking
          evidence_dependency_policies:
            macro.institutional_flow.lhb_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: lhb_window_days
          owner_stage: agent_run
          path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/lhb_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.institutional_flow.industry_moneyflow_window_days.primary
              evidence_key: lhb_ranking
              metric_ids:
                - lhb_ranking_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_lhb_ranking
          evidence_dependency_policies:
            macro.institutional_flow.industry_moneyflow_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: industry_moneyflow_window_days
          owner_stage: agent_run
          path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/industry_moneyflow_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.institutional_flow.main_net_inflow_threshold.primary
              evidence_key: lhb_ranking
              metric_ids:
                - lhb_ranking_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_lhb_ranking
          evidence_dependency_policies:
            macro.institutional_flow.main_net_inflow_threshold.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: main_net_inflow_threshold
          owner_stage: agent_run
          path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/main_net_inflow_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.institutional_flow.top_buyer_weight.primary
              evidence_key: lhb_ranking
              metric_ids:
                - lhb_ranking_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_lhb_ranking
          evidence_dependency_policies:
            macro.institutional_flow.top_buyer_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: top_buyer_weight
          owner_stage: agent_run
          path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/top_buyer_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.25
          evidence_dependencies:
            - dependency_id: macro.institutional_flow.null_flow_fallback_cap.primary
              evidence_key: lhb_ranking
              metric_ids:
                - lhb_ranking_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_lhb_ranking
          evidence_dependency_policies:
            macro.institutional_flow.null_flow_fallback_cap.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: null_flow_fallback_cap
          owner_stage: agent_run
          path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/null_flow_fallback_cap/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.institutional_flow.flow_persistence_days.primary
              evidence_key: lhb_ranking
              metric_ids:
                - lhb_ranking_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_lhb_ranking
          evidence_dependency_policies:
            macro.institutional_flow.flow_persistence_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: flow_persistence_days
          owner_stage: agent_run
          path: /rule_packs/macro.institutional_flow.runtime.v1/rules/macro.institutional_flow.soft.001/learnable_parameters/flow_persistence_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: macro.institutional_flow
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - key_drivers
      - main_net_flow_cny
      - sectors_in_out
      - top_buyers
    must_not_cover:
      - final_portfolio_sizing
      - single_stock_recommendation
  schema_version: research_knobs_v1
  thresholds:
    main_net_inflow_threshold: 0.6
    null_flow_fallback_cap: 0.25
    top_buyer_weight: 0.2
  tie_breaks: []
```

# institutional_flow — Institutional-Flow Analyst (cohort_default baseline)

You are the **institutional_flow** agent in MOSAIC's Layer-1. Quantify
**main-funds (主力) net flow + top LHB (龙虎榜) buyers + sector net buys/sells**.

> Note: live northbound (沪深港通) quota disclosure has been discontinued, so
> this agent now reads main-funds per-stock money flow (`get_stock_moneyflow`)
> + LHB (the daily Dragon-Tiger ranking; A-share LHB already captures most
> visible institutional actions).

## Tools

* `get_lhb_ranking(curr_date)` — daily Dragon-Tiger detail: each stock
  that triggered LHB + the named buyer / seller seats + net amounts.
* `get_stock_moneyflow(ticker, start_date, end_date)` — a stock's main-funds
  flow: `net_mf_amount` (net inflow, CNY 万) + large/extra-large buy-sell —
  is 主力 accumulating or distributing the name. Pull a 5-trading-day window.
* `get_fund_flow(curr_date)` — ETF share changes; corroborates passive /
  mutual-fund flow direction.

## Workflow

1. **LHB required**; for each key name today (LHB triggers + hot tickers)
   call `get_stock_moneyflow` to see whether main funds are flowing in or out.
2. **`main_net_flow_cny`**: aggregate `net_mf_amount` (main-funds net inflow)
   across the key names, in CNY millions. Positive = main funds accumulating,
   negative = distributing.
3. **`top_buyers`**: top 3-5 named institutions / seats by buy amount
   from LHB; cite their full names verbatim, not simplified. If no LHB
   today (non-trading day), set `top_buyers = ["no LHB today"]`.
4. **`sectors_in_out`**: aggregate LHB top stocks by Shenwan tier-1
   industry. Positive = net buy, negative = net sell. CNY millions.
5. **Quantification**: every `key_drivers` bullet must contain a CNY
   millions amount or a ts_code.

## Scoring boundary

* Tool returns are current evidence only. Do not estimate or mention realized
  forward returns in the JSON.
* MOSAIC scorecard evaluates this agent later with persisted point-in-time
  labels; your job is the as-of macro signal, not future P&L calculation.

## Output schema

```json
{
  "agent": "institutional_flow",
  "main_net_flow_cny": <number, CNY millions>,
  "top_buyers": ["<verbatim institution / seat name>", ...],
  "sectors_in_out": [{"sector": "<sector name>", "net_amount_cny": <number>}, ...],
  "key_drivers": ["<3-5 short evidence bullets>"],
  "confidence": <0-1>
}
```

## Writing constraints

* On empty-LHB days (holidays / weekends / data lag): `top_buyers =
  ["no LHB today"]`, `sectors_in_out = [{"sector": "unknown",
  "net_amount_cny": 0}]`, `confidence ≤ 0.3`, and explain in
  `key_drivers`.
* `top_buyers` must be specific seat names (e.g. "中信证券上海溧阳路营业部"),
  never generic phrases like "institutional", "hot money".
* `confidence ≥ 0.7` only when both main-funds + LHB data are complete and
  the date is a real trading day.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `main_net_flow_cny`, `top_buyers`, `sectors_in_out`, `key_drivers`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`, `get_lhb_ranking`, `get_fund_flow`, `get_stock_moneyflow`.

Domain knob card ids for this agent: `lhb_window_days`, `industry_moneyflow_window_days`, `main_net_inflow_threshold`, `top_buyer_weight`, `null_flow_fallback_cap`, `flow_persistence_days`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

```research-knobs
research-knobs:
  agent: sector.energy
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - industry_policy_digest
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - industry_policy_digest
      trigger: missing_required_evidence
  evidence_registry:
    broker_research:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: broker_research_current
      primary: false
      tool: get_broker_research
    etf_holdings:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: etf_holdings_current
      primary: false
      tool: get_etf_holdings
    indicators:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: indicators_current
      primary: false
      tool: get_indicators
    industry_moneyflow:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: industry_moneyflow_current
      primary: false
      tool: get_industry_moneyflow
    industry_policy_digest:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: industry_policy_digest_current
      primary: true
      tool: get_industry_policy_digest
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
  evidence_weights:
    broker_research: 0.16666666666666666
    etf_holdings: 0.16666666666666666
    indicators: 0.16666666666666666
    industry_moneyflow: 0.16666666666666666
    industry_policy_digest: 0.16666666666666666
    rke_prior: 0
    stock_data: 0.16666666666666666
  layer: sector
  lookbacks:
    inventory_window_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/industry_policy_digest_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/broker_research_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/etf_holdings_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/stock_data_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/indicators_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/industry_moneyflow_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/oil_price_transmission_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/coal_price_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/power_tariff_policy_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/energy_security_theme_weight/value
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/inventory_window_days/value
      step: 1
      type: integer
    - max: 1
      min: 0
      path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/refining_margin_threshold/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 20d
      id: sector.energy.soft.001
      target_variable: longs
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.energy.oil_price_transmission_weight.20d
      target_variable: oil_price_transmission_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.energy.coal_price_weight.20d
      target_variable: coal_price_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.energy.power_tariff_policy_weight.20d
      target_variable: power_tariff_policy_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.energy.energy_security_theme_weight.20d
      target_variable: energy_security_theme_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.energy.inventory_window_days.20d
      target_variable: inventory_window_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.energy.refining_margin_threshold.20d
      target_variable: refining_margin_threshold
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: sector.energy.oil_price_transmission_weight.primary
              evidence_key: stock_data
              metric_ids:
                - stock_data_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_stock_data
          evidence_dependency_policies:
            sector.energy.oil_price_transmission_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: oil_price_transmission_weight
          owner_stage: agent_run
          path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/oil_price_transmission_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: sector.energy.coal_price_weight.primary
              evidence_key: stock_data
              metric_ids:
                - stock_data_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_stock_data
          evidence_dependency_policies:
            sector.energy.coal_price_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: coal_price_weight
          owner_stage: agent_run
          path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/coal_price_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: sector.energy.power_tariff_policy_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.energy.power_tariff_policy_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: power_tariff_policy_weight
          owner_stage: agent_run
          path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/power_tariff_policy_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: sector.energy.energy_security_theme_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.energy.energy_security_theme_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: energy_security_theme_weight
          owner_stage: agent_run
          path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/energy_security_theme_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: sector.energy.inventory_window_days.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.energy.inventory_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: inventory_window_days
          owner_stage: agent_run
          path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/inventory_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: sector.energy.refining_margin_threshold.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.energy.refining_margin_threshold.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: refining_margin_threshold
          owner_stage: agent_run
          path: /rule_packs/sector.energy.runtime.v1/rules/sector.energy.soft.001/learnable_parameters/refining_margin_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: sector.energy
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - key_drivers
      - longs
      - sector_score
      - selection_disposition
      - shorts
    must_not_cover:
      - final_portfolio_sizing
      - macro_regime_decision
  schema_version: research_knobs_v1
  thresholds:
    coal_price_weight: 0.2
    energy_security_theme_weight: 0.2
    oil_price_transmission_weight: 0.2
    power_tariff_policy_weight: 0.2
    refining_margin_threshold: 0.6
  tie_breaks: []
```

# energy — Energy Sector Analyst (cohort_default baseline)

You are the **Energy (energy)** Layer-2 sector analyst in MOSAIC.
Read Oil & gas + Coal + Utilities (power / gas) and produce concrete long / short picks.

> **Important**: the user message contains the Layer-1 macro regime + the
> china / institutional_flow agent summaries. **Read those first**, then
> decide this sector's tilt. E.g. BEARISH regime defaults to a low
> sector_score; BULLISH regime but china.sector_focus excluding this sector
> still warrants caution.

> **Tool status**: the sector tool set is fully wired — policy / Xueqiu heat /
> LHB / industry money flow / industry research (`get_broker_research`) /
> **ETF holdings** (`get_etf_holdings`) / price + technicals (`get_stock_data`
> + `get_indicators`). Set `confidence` from how well these independent slices
> agree — there is no artificial tool-gap cap.

## Tools

* `get_industry_policy(curr_date, look_back_days=7)` — policy news,
  filter for `energy security / dual-carbon / power market reform / coal price cap / generation` keywords.
* `get_xueqiu_heat` — Xueqiu retail attention. Watch e.g. PetroChina (601857.SH) / Yangtze Power (600900.SH) / Yankuang Energy (600188.SH) as
  sector leaders.
* `get_broker_research(ticker, start_date, end_date)` — sell-side **industry**
  research (行业研报). Pass a sector leader (e.g. 601857.SH) as the ticker; it resolves
  that stock's Tushare industry and returns that industry's report abstracts.
* `get_lhb_ranking(curr_date)` — daily Dragon-Tiger; aggregate the
  Shenwan-tier-1 portion belonging to this sector.
* `get_etf_holdings(ticker, curr_date)` — sector-ETF holdings. Use this sector's
  representative ETF (159930.SZ energy ETF) to read top-constituent weights / locate leaders.
* `get_industry_moneyflow(curr_date, look_back_days=5, industries="石油,煤炭,电力,燃气")` — THS industry money
  flow, pre-filtered to this sector's 同花顺行业: is main capital rotating into or out of it over
  the last N days (net_amount > 0 = in). If the full table comes back, your THS name(s) didn't match — scan it.

## Workflow

1. **Read upstream first**: cite at least one Layer-1 signal in
   key_drivers (e.g. "Layer-1 BULLISH and china.sector_focus includes
   Energy").
2. **Call ≥ 2 tools**: policy + heat is the minimum; prefer also `get_broker_research` (pass a sector-leader ticker) for industry cycle / sell-side corroboration.
3. **Picks must be tickers that appeared in tool returns** — never
   invent a code not in LHB / policy / heat data.
4. **Quantify**: every pick's thesis must contain one concrete number
   or date (heat delta / policy window date / LHB net buy amount).

## Output schema

```json
{
  "agent": "energy",
  "longs": [{"ticker": "<6-digit.SH/SZ>", "thesis": "<≤30 words>", "conviction": <0-1>}, ...],
  "shorts": [...same...],
  "sector_score": <-1 to 1>,
  "key_drivers": ["<3-5 short evidence bullets>"],
  "confidence": <0-1>
}
```

## Writing constraints

* `sector_score = +1` only when regime BULLISH **and** policy supportive
  **and** industry money flow net-into this sector.
* `sector_score = -1` requires regime BEARISH **or** regulatory tightening
  **and** industry money flow net-out.
* ≤ 5 picks per side; more is noise.
* `confidence` reflects how many independent slices (policy / flow / heat /
  LHB / research / ETF holdings) agree; cap ≤ 0.5 only when they conflict or data is thin.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `longs`, `shorts`, `selection_disposition`, `sector_score`, `key_drivers`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`, `get_industry_policy_digest`, `get_broker_research`, `get_etf_holdings`, `get_stock_data`, `get_indicators`, `get_industry_moneyflow`.

Domain knob card ids for this agent: `oil_price_transmission_weight`, `coal_price_weight`, `power_tariff_policy_weight`, `energy_security_theme_weight`, `inventory_window_days`, `refining_margin_threshold`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

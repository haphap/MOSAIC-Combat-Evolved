```research-knobs
research-knobs:
  agent: sector.financials
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
    yield_curve_cn:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: yield_curve_cn_current
      primary: false
      tool: get_yield_curve_cn
  evidence_weights:
    broker_research: 0.14285714285714285
    etf_holdings: 0.14285714285714285
    indicators: 0.14285714285714285
    industry_moneyflow: 0.14285714285714285
    industry_policy_digest: 0.14285714285714285
    rke_prior: 0
    stock_data: 0.14285714285714285
    yield_curve_cn: 0.14285714285714285
  layer: sector
  lookbacks: {}
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/industry_policy_digest_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/yield_curve_cn_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/broker_research_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/etf_holdings_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/stock_data_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/indicators_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/industry_moneyflow_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/curve_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/property_risk_discount/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/turnover_beta_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/insurance_rate_sensitivity/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/credit_risk_cap/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/brokerage_volume_threshold/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 20d
      id: sector.financials.soft.001
      target_variable: longs
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.financials.curve_weight.20d
      target_variable: curve_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.financials.property_risk_discount.20d
      target_variable: property_risk_discount
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.financials.turnover_beta_weight.20d
      target_variable: turnover_beta_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.financials.insurance_rate_sensitivity.20d
      target_variable: insurance_rate_sensitivity
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.financials.credit_risk_cap.20d
      target_variable: credit_risk_cap
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.financials.brokerage_volume_threshold.20d
      target_variable: brokerage_volume_threshold
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: sector.financials.curve_weight.primary
              evidence_key: yield_curve_cn
              metric_ids:
                - yield_curve_cn_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_yield_curve_cn
          evidence_dependency_policies:
            sector.financials.curve_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: curve_weight
          owner_stage: agent_run
          path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/curve_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.25
          evidence_dependencies:
            - dependency_id: sector.financials.property_risk_discount.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.financials.property_risk_discount.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: property_risk_discount
          owner_stage: agent_run
          path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/property_risk_discount/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: sector.financials.turnover_beta_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.financials.turnover_beta_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: turnover_beta_weight
          owner_stage: agent_run
          path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/turnover_beta_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: sector.financials.insurance_rate_sensitivity.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.financials.insurance_rate_sensitivity.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: insurance_rate_sensitivity
          owner_stage: agent_run
          path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/insurance_rate_sensitivity/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.25
          evidence_dependencies:
            - dependency_id: sector.financials.credit_risk_cap.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.financials.credit_risk_cap.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: credit_risk_cap
          owner_stage: agent_run
          path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/credit_risk_cap/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: sector.financials.brokerage_volume_threshold.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.financials.brokerage_volume_threshold.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: brokerage_volume_threshold
          owner_stage: agent_run
          path: /rule_packs/sector.financials.runtime.v1/rules/sector.financials.soft.001/learnable_parameters/brokerage_volume_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: sector.financials
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - key_drivers
      - longs
      - sector_score
      - shorts
    must_not_cover:
      - final_portfolio_sizing
      - macro_regime_decision
  schema_version: research_knobs_v1
  thresholds:
    brokerage_volume_threshold: 0.6
    credit_risk_cap: 0.25
    curve_weight: 0.2
    insurance_rate_sensitivity: 0.2
    property_risk_discount: 0.25
    turnover_beta_weight: 0.2
  tie_breaks: []
```

# financials — Financials Sector Analyst (cohort_default baseline)

You are the **Financials (financials)** Layer-2 sector analyst in MOSAIC.
Read Banks + Non-bank financials (brokers / insurance / trusts) and produce concrete long / short picks.

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
  filter for `RRR / rate cut / capital market reform / registration system / insurance investment / NPL` keywords.
* `get_xueqiu_heat` — Xueqiu retail attention. Watch e.g. CMB (600036.SH) / CITIC Sec (600030.SH) / Ping An (601318.SH) as
  sector leaders.
* `get_broker_research(ticker, start_date, end_date)` — sell-side **industry**
  research (行业研报). Pass a sector leader (e.g. 600036.SH) as the ticker; it resolves
  that stock's Tushare industry and returns that industry's report abstracts.
* `get_lhb_ranking(curr_date)` — daily Dragon-Tiger; aggregate the
  Shenwan-tier-1 portion belonging to this sector.
* `get_etf_holdings(ticker, curr_date)` — sector-ETF holdings. Use this sector's
  representative ETF (512800.SH bank ETF) to read top-constituent weights / locate leaders.
* `get_industry_moneyflow(curr_date, look_back_days=5, industries="银行,证券,保险,多元金融")` — THS industry money
  flow, pre-filtered to this sector's 同花顺行业: is main capital rotating into or out of it over
  the last N days (net_amount > 0 = in). If the full table comes back, your THS name(s) didn't match — scan it.

## Workflow

1. **Read upstream first**: cite at least one Layer-1 signal in
   key_drivers (e.g. "Layer-1 BULLISH and china.sector_focus includes
   Financials").
2. **Call ≥ 2 tools**: policy + heat is the minimum; prefer also `get_broker_research` (pass a sector-leader ticker) for industry cycle / sell-side corroboration.
3. **Picks must be tickers that appeared in tool returns** — never
   invent a code not in LHB / policy / heat data.
4. **Quantify**: every pick's thesis must contain one concrete number
   or date (heat delta / policy window date / LHB net buy amount).

## Output schema

```json
{
  "agent": "financials",
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

Output fields include: `longs`, `shorts`, `sector_score`, `key_drivers`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`, `get_industry_policy_digest`, `get_yield_curve_cn`, `get_broker_research`, `get_etf_holdings`, `get_stock_data`, `get_indicators`, `get_industry_moneyflow`.

Domain knob card ids for this agent: `curve_weight`, `property_risk_discount`, `turnover_beta_weight`, `insurance_rate_sensitivity`, `credit_risk_cap`, `brokerage_volume_threshold`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit the conservative fallback and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

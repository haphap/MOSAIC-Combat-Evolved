```research-knobs
research-knobs:
  agent: sector.semiconductor
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
    balance_sheet:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: balance_sheet_current
      primary: false
      tool: get_balance_sheet
    broker_research:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: broker_research_current
      primary: false
      tool: get_broker_research
    cashflow:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: cashflow_current
      primary: false
      tool: get_cashflow
    etf_holdings:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: etf_holdings_current
      primary: false
      tool: get_etf_holdings
    income_statement:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: income_statement_current
      primary: false
      tool: get_income_statement
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
    balance_sheet: 0.1111111111111111
    broker_research: 0.1111111111111111
    cashflow: 0.1111111111111111
    etf_holdings: 0.1111111111111111
    income_statement: 0.1111111111111111
    indicators: 0.1111111111111111
    industry_moneyflow: 0.1111111111111111
    industry_policy_digest: 0.1111111111111111
    rke_prior: 0
    stock_data: 0.1111111111111111
  layer: sector
  lookbacks:
    broker_research_days: 60
    capex_cycle_quarters: 4
    financial_statement_quarters: 4
    industry_moneyflow_days: 20
    inventory_cycle_quarters: 4
    policy_digest_days: 30
    price_momentum_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/industry_policy_digest_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/broker_research_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/etf_holdings_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/stock_data_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/indicators_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/income_statement_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/balance_sheet_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/cashflow_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/industry_moneyflow_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 60
      min: 5
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/industry_moneyflow_days/value
      step: 5
      type: integer
    - max: 8
      min: 2
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/financial_statement_quarters/value
      step: 1
      type: integer
    - max: 8
      min: 2
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/inventory_cycle_quarters/value
      step: 1
      type: integer
    - max: 8
      min: 2
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/capex_cycle_quarters/value
      step: 1
      type: integer
    - max: 60
      min: 5
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/price_momentum_days/value
      step: 5
      type: integer
    - max: 90
      min: 7
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/policy_digest_days/value
      step: 1
      type: integer
    - max: 180
      min: 15
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/broker_research_days/value
      step: 5
      type: integer
    - max: 0.5
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/design_weight/value
      step: 0.01
      type: number
    - max: 0.5
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/equipment_weight/value
      step: 0.01
      type: number
    - max: 0.5
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/foundry_weight/value
      step: 0.01
      type: number
    - max: 0.5
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/packaging_weight/value
      step: 0.01
      type: number
    - max: 0.5
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/materials_weight/value
      step: 0.01
      type: number
    - max: 0.5
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/ai_compute_weight/value
      step: 0.01
      type: number
    - max: 0.6
      min: 0.1
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/inventory_to_revenue_risk/value
      step: 0.05
      type: number
    - max: 0.1
      min: -0.15
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/gross_margin_change_min/value
      step: 0.01
      type: number
    - max: 0.25
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/capex_to_revenue_min/value
      step: 0.01
      type: number
    - max: 0.15
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/price_confirmation_pct/value
      step: 0.01
      type: number
    - max: 0.95
      min: 0.3
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/valuation_risk_max/value
      step: 0.05
      type: number
    - max: 6
      min: 1
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/max_verified_constituents/value
      step: 1
      type: integer
    - max: 0.9
      min: 0.45
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/min_long_conviction/value
      step: 0.05
      type: number
    - max: 0.85
      min: 0.4
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/min_short_conviction/value
      step: 0.05
      type: number
    - max: 0.6
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/localization_policy_weight/value
      step: 0.05
      type: number
    - max: 0.6
      min: 0
      path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/export_control_discount/value
      step: 0.05
      type: number
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 20d
      id: sector.semiconductor.soft.001
      target_variable: longs
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.industry_moneyflow_days.20d
      target_variable: industry_moneyflow_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.financial_statement_quarters.20d
      target_variable: financial_statement_quarters
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.inventory_cycle_quarters.20d
      target_variable: inventory_cycle_quarters
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.capex_cycle_quarters.20d
      target_variable: capex_cycle_quarters
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.price_momentum_days.20d
      target_variable: price_momentum_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.policy_digest_days.20d
      target_variable: policy_digest_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.broker_research_days.20d
      target_variable: broker_research_days
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.design_weight.20d
      target_variable: design_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.equipment_weight.20d
      target_variable: equipment_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.foundry_weight.20d
      target_variable: foundry_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.packaging_weight.20d
      target_variable: packaging_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.materials_weight.20d
      target_variable: materials_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.ai_compute_weight.20d
      target_variable: ai_compute_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.inventory_to_revenue_risk.20d
      target_variable: inventory_to_revenue_risk
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.gross_margin_change_min.20d
      target_variable: gross_margin_change_min
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.capex_to_revenue_min.20d
      target_variable: capex_to_revenue_min
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.price_confirmation_pct.20d
      target_variable: price_confirmation_pct
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.valuation_risk_max.20d
      target_variable: valuation_risk_max
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.max_verified_constituents.20d
      target_variable: max_verified_constituents
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.min_long_conviction.20d
      target_variable: min_long_conviction
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.min_short_conviction.20d
      target_variable: min_short_conviction
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.localization_policy_weight.20d
      target_variable: localization_policy_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 20d
      id: sector.semiconductor.export_control_discount.20d
      target_variable: export_control_discount
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 23
      cards:
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: sector.semiconductor.industry_moneyflow_days.primary
              evidence_key: industry_moneyflow
              metric_ids:
                - industry_moneyflow_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_moneyflow
          evidence_dependency_policies:
            sector.semiconductor.industry_moneyflow_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: industry_moneyflow_days
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/industry_moneyflow_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 4
          evidence_dependencies:
            - dependency_id: sector.semiconductor.financial_statement_quarters.primary
              evidence_key: income_statement
              metric_ids:
                - income_statement_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_income_statement
          evidence_dependency_policies:
            sector.semiconductor.financial_statement_quarters.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: financial_statement_quarters
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/financial_statement_quarters/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 4
          evidence_dependencies:
            - dependency_id: sector.semiconductor.inventory_cycle_quarters.primary
              evidence_key: balance_sheet
              metric_ids:
                - inventory_to_revenue
                - inventory_turnover_days
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_balance_sheet
          evidence_dependency_policies:
            sector.semiconductor.inventory_cycle_quarters.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: inventory_cycle_quarters
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/inventory_cycle_quarters/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 4
          evidence_dependencies:
            - dependency_id: sector.semiconductor.capex_cycle_quarters.primary
              evidence_key: cashflow
              metric_ids:
                - capex_to_revenue
                - construction_in_progress_change
                - operating_cashflow_margin
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_cashflow
          evidence_dependency_policies:
            sector.semiconductor.capex_cycle_quarters.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: capex_cycle_quarters
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/capex_cycle_quarters/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: sector.semiconductor.price_momentum_days.primary
              evidence_key: stock_data
              metric_ids:
                - stock_data_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_stock_data
          evidence_dependency_policies:
            sector.semiconductor.price_momentum_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: price_momentum_days
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/price_momentum_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 30
          evidence_dependencies:
            - dependency_id: sector.semiconductor.policy_digest_days.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.policy_digest_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: policy_digest_days
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/policy_digest_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 60
          evidence_dependencies:
            - dependency_id: sector.semiconductor.broker_research_days.primary
              evidence_key: broker_research
              metric_ids:
                - broker_research_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_broker_research
          evidence_dependency_policies:
            sector.semiconductor.broker_research_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: broker_research_days
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/broker_research_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.18
          evidence_dependencies:
            - dependency_id: sector.semiconductor.design_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.design_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: design_weight
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/design_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.18
          evidence_dependencies:
            - dependency_id: sector.semiconductor.equipment_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.equipment_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: equipment_weight
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/equipment_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.16
          evidence_dependencies:
            - dependency_id: sector.semiconductor.foundry_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.foundry_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: foundry_weight
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/foundry_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.12
          evidence_dependencies:
            - dependency_id: sector.semiconductor.packaging_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.packaging_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: packaging_weight
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/packaging_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.1
          evidence_dependencies:
            - dependency_id: sector.semiconductor.materials_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.materials_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: materials_weight
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/materials_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.26
          evidence_dependencies:
            - dependency_id: sector.semiconductor.ai_compute_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.ai_compute_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: ai_compute_weight
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/ai_compute_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.3
          evidence_dependencies:
            - dependency_id: sector.semiconductor.inventory_to_revenue_risk.primary
              evidence_key: balance_sheet
              metric_ids:
                - inventory_to_revenue
                - inventory_turnover_days
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_balance_sheet
          evidence_dependency_policies:
            sector.semiconductor.inventory_to_revenue_risk.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: inventory_to_revenue_risk
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/inventory_to_revenue_risk/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: -0.03
          evidence_dependencies:
            - dependency_id: sector.semiconductor.gross_margin_change_min.primary
              evidence_key: income_statement
              metric_ids:
                - gross_margin_change
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_income_statement
          evidence_dependency_policies:
            sector.semiconductor.gross_margin_change_min.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: gross_margin_change_min
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/gross_margin_change_min/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.08
          evidence_dependencies:
            - dependency_id: sector.semiconductor.capex_to_revenue_min.primary
              evidence_key: cashflow
              metric_ids:
                - capex_to_revenue
                - construction_in_progress_change
                - operating_cashflow_margin
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_cashflow
          evidence_dependency_policies:
            sector.semiconductor.capex_to_revenue_min.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: capex_to_revenue_min
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/capex_to_revenue_min/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.03
          evidence_dependencies:
            - dependency_id: sector.semiconductor.price_confirmation_pct.primary
              evidence_key: stock_data
              metric_ids:
                - stock_data_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_stock_data
          evidence_dependency_policies:
            sector.semiconductor.price_confirmation_pct.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: price_confirmation_pct
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/price_confirmation_pct/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.7
          evidence_dependencies:
            - dependency_id: sector.semiconductor.valuation_risk_max.primary
              evidence_key: indicators
              metric_ids:
                - indicators_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_indicators
          evidence_dependency_policies:
            sector.semiconductor.valuation_risk_max.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: valuation_risk_max
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/valuation_risk_max/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 3
          evidence_dependencies:
            - dependency_id: sector.semiconductor.max_verified_constituents.candidate_validation
              empty_scope_behavior: exclude_sample
              evidence_key: stock_data
              max_scope_count: 6
              metric_ids:
                - close
                - volume
              min_scope_count: 1
              min_scope_coverage: 0.8
              scope_resolution: in_run_tool_derived
              scope_source_tool: get_etf_holdings
              tool: get_stock_data
          evidence_dependency_policies:
            sector.semiconductor.max_verified_constituents.candidate_validation:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: max_verified_constituents
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/max_verified_constituents/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.65
          evidence_dependencies:
            - dependency_id: sector.semiconductor.min_long_conviction.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.min_long_conviction.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: min_long_conviction
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/min_long_conviction/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: sector.semiconductor.min_short_conviction.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.min_short_conviction.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: min_short_conviction
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/min_short_conviction/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.25
          evidence_dependencies:
            - dependency_id: sector.semiconductor.localization_policy_weight.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.localization_policy_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: localization_policy_weight
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/localization_policy_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: sector.semiconductor.export_control_discount.primary
              evidence_key: industry_policy_digest
              metric_ids:
                - industry_policy_digest_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_industry_policy_digest
          evidence_dependency_policies:
            sector.semiconductor.export_control_discount.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: export_control_discount
          owner_stage: agent_run
          path: /rule_packs/sector.semiconductor.runtime.v1/rules/sector.semiconductor.soft.001/learnable_parameters/export_control_discount/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 23
    prompt_ir_agent_id: sector.semiconductor
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
    ai_compute_weight: 0.26
    capex_to_revenue_min: 0.08
    design_weight: 0.18
    equipment_weight: 0.18
    export_control_discount: 0.2
    foundry_weight: 0.16
    gross_margin_change_min: -0.03
    inventory_to_revenue_risk: 0.3
    localization_policy_weight: 0.25
    materials_weight: 0.1
    max_verified_constituents: 3
    min_long_conviction: 0.65
    min_short_conviction: 0.6
    packaging_weight: 0.12
    price_confirmation_pct: 0.03
    valuation_risk_max: 0.7
  tie_breaks: []
```

# semiconductor — Semiconductor Sector Analyst (cohort_default baseline)

You are the **Semiconductor (semiconductor)** Layer-2 sector analyst in MOSAIC.
Read Shenwan-tier-1 Electronics, semiconductor sub-segment (equipment / design / fab / packaging) and produce concrete long / short picks.

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
  filter for `semiconductor / integrated circuit / domestic substitution / export control / Big Fund` keywords.
* `get_broker_research(ticker, start_date, end_date)` — sell-side **industry**
  research (行业研报). Pass a sector leader (e.g. 688981.SH) as the ticker; it
  resolves that stock's Tushare industry and returns that industry's report
  abstracts (thesis / cycle / risks).
* `get_xueqiu_heat` — Xueqiu retail attention. Watch e.g. SMIC (688981.SH) / Naura (002371.SZ) / Will Semiconductor (603501.SH) as
  sector leaders.
* `get_lhb_ranking(curr_date)` — daily Dragon-Tiger; aggregate the
  Shenwan-tier-1 portion belonging to this sector.
* `get_etf_holdings(ticker, curr_date)` — sector-ETF holdings. Use this sector's
  representative ETF (512760.SH chip ETF) to read top-constituent weights / locate leaders.
* `get_industry_moneyflow(curr_date, look_back_days=5, industries="半导体,元器件")` — THS industry money
  flow, pre-filtered to this sector's 同花顺行业: is main capital rotating into or out of it over
  the last N days (net_amount > 0 = in). If the full table comes back, your THS name(s) didn't match — scan it.

## Workflow

1. **Read upstream first**: cite at least one Layer-1 signal in
   key_drivers (e.g. "Layer-1 BULLISH and china.sector_focus includes
   Semiconductor").
2. **Call ≥ 2 tools**: policy + heat is the minimum; prefer also
   `get_broker_research` (pass a sector-leader ticker) for industry cycle /
   sell-side corroboration.
3. **Picks must be tickers that appeared in tool returns** — never
   invent a code not in LHB / policy / heat data.
4. **Quantify**: every pick's thesis must contain one concrete number
   or date (heat delta / policy window date / LHB net buy amount).

## Output schema

```json
{
  "agent": "semiconductor",
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

Required runtime tools: `get_rke_research_context`, `get_industry_policy_digest`, `get_broker_research`, `get_etf_holdings`, `get_stock_data`, `get_indicators`, `get_income_statement`, `get_balance_sheet`, `get_cashflow`, `get_industry_moneyflow`.

Domain knob card ids for this agent: `industry_moneyflow_days`, `financial_statement_quarters`, `inventory_cycle_quarters`, `capex_cycle_quarters`, `price_momentum_days`, `policy_digest_days`, `broker_research_days`, `design_weight`, `equipment_weight`, `foundry_weight`, `packaging_weight`, `materials_weight`, `ai_compute_weight`, `inventory_to_revenue_risk`, `gross_margin_change_min`, `capex_to_revenue_min`, `price_confirmation_pct`, `valuation_risk_max`, `max_verified_constituents`, `min_long_conviction`, `min_short_conviction`, `localization_policy_weight`, `export_control_discount`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit the conservative fallback and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->

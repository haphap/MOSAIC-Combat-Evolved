import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import type { ResearchKnobs } from "../helpers/research_knobs.js";
import type { Layer } from "./cohorts.js";
import type { DomainKnobValueRegistry } from "./domain_knob_registry.js";
import { genericGovernanceTargetDefinitions } from "./generic_governance_targets.js";
import {
  RUNTIME_AGENT_SPEC_BY_AGENT,
  RUNTIME_AGENT_SPECS,
  RUNTIME_DAG_STAGE_ORDER,
  type RuntimeAgentSpec,
  type RuntimeAgentStageId,
  type RuntimeDagStageId,
} from "./runtime_agent_spec.js";

export const DOMAIN_KNOB_CATALOG_VERSION = "domain_knob_catalog_v1";
export const DOMAIN_KNOB_EVALUATION_CONTRACT_VERSION = "domain_knob_evaluation_contract_v1";

export type CoverageLevel = "direct_tool" | "derived_proxy" | "runtime_state" | "gap_pending_tool";
export const PROJECTION_BUCKETS = [
  "lookbacks",
  "thresholds",
  "tie_breaks",
  "evidence_weights",
  "confidence_caps",
] as const;
export type ProjectionBucket = (typeof PROJECTION_BUCKETS)[number];
export type KnobValueType = "number" | "integer" | "enum" | "boolean";

type RuntimeSourceStatus = "missing" | "stale" | "source_error" | "empty_confirmed";
type EvidenceDependencyStatus =
  | "missing"
  | "stale"
  | "fallback"
  | "tool_failed"
  | "partial_loaded"
  | "loaded";

export interface RuntimeSourceRegistryEntry {
  id: string;
  scope_schema: Record<string, "required" | "optional">;
  schema_ref: string;
  producer_mode: "eager" | "stage_output" | "on_demand_pre_stage";
  producer_stage: RuntimeDagStageId;
  available_from_stage: RuntimeDagStageId;
  finalized_at_stage: RuntimeDagStageId;
  refresh_policy: "frozen" | "versioned_per_call" | "carry_forward_if_fresh";
  provenance_adapter: string;
  retry_owner: string;
  cross_cycle_reuse: "forbidden" | "allowed_if_fresh" | "prior_cycle_only";
  max_age: string;
  trading_calendar: "cn_a_share" | "run_clock";
  pit_required: boolean;
  empty_allowed: boolean;
  empty_status: "empty_confirmed" | "invalid";
  empty_behavior: "allow_empty" | "disable_dependent_cards" | "invalid";
  stale_policy: "disable_card_and_cap_if_required" | "disable_card" | "invalid";
  source_error_policy: "disable_card_and_cap_if_required" | "disable_card" | "invalid";
}

export interface EvaluationMetricRegistryEntry {
  id: string;
  unit: "ratio" | "bps" | "count" | "score" | "currency" | "registered_custom_unit";
  value_convention:
    | "signed_return"
    | "nonnegative_loss_magnitude"
    | "rate_0_1"
    | "bps_cost"
    | "score"
    | "count";
  direction: "higher_is_better" | "lower_is_better";
  aggregation:
    | "mean"
    | "median"
    | "p50"
    | "p95"
    | "max"
    | "min"
    | "sum"
    | "hit_rate"
    | "calibration_error"
    | "rank_correlation";
  window: string;
  baseline: "previous_knob_snapshot" | "cohort_control" | "shadow_ab" | "rolling_window";
  calculator_id: string;
  calculator_version: string;
  valid_range: {
    minimum: number | null;
    maximum: number | null;
  };
  null_policy: "exclude_sample" | "reject_evaluation";
  non_finite_policy: "reject_evaluation";
  normalization_version: string;
  uncertainty_method: "paired_block_bootstrap" | "block_bootstrap" | "wilson_interval" | "fisher_z";
  overlapping_sample_policy: "inverse_overlap_weight" | "purged_nonoverlap" | "not_applicable";
  min_sample_size: number;
  pit_required: boolean;
  exclusion_rules: string[];
}

export interface EvaluationCalculatorRegistryEntry {
  id: string;
  version: string;
  implementation_language: "python";
  implementation_ref: string;
  input_schema_ref: string;
  output_schema_ref: string;
  deterministic: true;
  pit_enforced: true;
  supported_value_conventions: EvaluationMetricRegistryEntry["value_convention"][];
}

export interface DomainKnobCard {
  id: string;
  owner_agent: string;
  consumer_agents: string[];
  owner_stage: RuntimeAgentStageId;
  consumer_stages: RuntimeDagStageId[];
  projection_bucket: ProjectionBucket;
  path: string;
  type: KnobValueType;
  default: number | string | boolean;
  min?: number;
  max?: number;
  step?: number;
  allowed_values?: unknown[];
  coverage_level: CoverageLevel;
  activation_state: "active" | "read_only" | "backlog";
  runtime_input_sources: string[];
  runtime_input_source_policies: Record<string, Record<RuntimeSourceStatus, string>>;
  evidence_dependencies: EvidenceDependency[];
  evidence_dependency_policies: Record<string, Record<EvidenceDependencyStatus, string>>;
  learning_objective: string;
  prediction_target: string;
  evaluation_metric: string;
  secondary_metrics: string[];
  horizon: string;
  rollback_condition: {
    metric: string;
    worse_by: number;
    unit: EvaluationMetricRegistryEntry["unit"];
  };
  enforcement: "advisory" | "code";
  runtime_validator?: string;
  audit_field?: string;
  category: "domain";
  cross_field_group: string | null;
  weight_group: string | null;
  atomic_mutation_group: string | null;
  normalization: "none" | "sum_to_one";
}

export interface EvidenceDependency {
  dependency_id: string;
  evidence_key: string;
  tool: string;
  metric_ids: string[];
  freshness: string;
  required_for_prediction: boolean;
  dependency_type: Exclude<CoverageLevel, "runtime_state" | "gap_pending_tool">;
  scope_resolution: "pre_run" | "in_run_tool_derived";
  scope_schema: Record<string, "required" | "optional">;
  min_scope_coverage: number;
  scope_source_tool?: string;
  scope_source_evidence_key?: string;
  max_scope_count?: number;
  min_scope_count?: number;
  empty_scope_behavior?: "allow_empty" | "exclude_sample" | "invalid";
}

export interface DomainKnobCatalogAgent {
  layer: Layer;
  agent: string;
  prompt_ir_agent: string;
  min_mutable_domain_knobs: number;
  card_count: number;
  cards: DomainKnobCard[];
}

export interface DomainKnobCatalogArtifact {
  schema_version: typeof DOMAIN_KNOB_CATALOG_VERSION;
  catalog_version: typeof DOMAIN_KNOB_CATALOG_VERSION;
  runtime_agent_count: number;
  runtime_sources: Record<string, RuntimeSourceRegistryEntry>;
  evaluation_metrics: Record<string, EvaluationMetricRegistryEntry>;
  evaluation_calculators: Record<string, EvaluationCalculatorRegistryEntry>;
  agents: DomainKnobCatalogAgent[];
}

export interface DomainKnobEvaluationContractArtifact {
  schema_version: typeof DOMAIN_KNOB_EVALUATION_CONTRACT_VERSION;
  contract_version: typeof DOMAIN_KNOB_EVALUATION_CONTRACT_VERSION;
  catalog_version: typeof DOMAIN_KNOB_CATALOG_VERSION;
  schema_hash: string;
  catalog_hash: string;
  metric_registry_hash: string;
  calculator_registry_hash: string;
  contract_hash: string;
  evaluation_metrics: Record<string, EvaluationMetricRegistryEntry>;
  evaluation_calculators: Record<string, EvaluationCalculatorRegistryEntry>;
  generic_bindings: Array<{
    path: string;
    owner_agent: string;
    owner_stages: RuntimeAgentStageId[];
    target_type: "number";
    minimum: number;
    maximum: number;
    step: number;
    weight_group: "evidence_weights" | null;
    write_back_repo_id: "MOSAIC-Prompts";
    write_back_path_template: string;
    write_back_json_pointer: string;
    evaluation_metrics: string[];
    horizons: string[];
    rollback_metrics: string[];
  }>;
  card_bindings: Array<{
    path: string;
    card_id: string;
    owner_agent: string;
    owner_stage: RuntimeAgentStageId;
    activation_state: DomainKnobCard["activation_state"];
    prediction_target: string;
    evaluation_metric: string;
    secondary_metrics: string[];
    horizon: string;
    rollback_condition: DomainKnobCard["rollback_condition"];
  }>;
}

interface DomainSeed {
  id: string;
  bucket?: ProjectionBucket;
  type?: KnobValueType;
  default?: number;
  min?: number;
  max?: number;
  step?: number;
  metric?: string;
  horizon?: string;
  activation_state?: DomainKnobCard["activation_state"];
}

const LOOKBACK_DOMAIN_KNOB_IDS = new Set([
  "liquidity_net_injection_window_days",
  "omo_mlf_freshness_days",
  "policy_confirmation_window_days",
  "surprise_window_days",
  "broad_dollar_trend_window_days",
  "term_spread_window_days",
  "inventory_confirmation_window_days",
  "vol_amplification_window_days",
  "event_decay_window_days",
  "market_flow_window_days",
  "sector_rotation_window_days",
  "flow_persistence_days",
  "industry_moneyflow_days",
  "financial_statement_quarters",
  "inventory_cycle_quarters",
  "capex_cycle_quarters",
  "price_momentum_days",
  "policy_digest_days",
  "broker_research_days",
  "inventory_window_days",
  "approval_catalyst_window_days",
  "inventory_cycle_window_days",
  "military_order_confirmation_days",
  "policy_catalyst_window_days",
  "flow_diffusion_window_days",
  "trend_confirmation_window_days",
  "short_signal_window_days",
  "compounder_window_days",
  "activist_catalyst_window_days",
  "theme_persistence_days",
  "idea_decay_days",
  "stale_thesis_days",
  "position_review_days",
  "rebalance_cooldown_days",
  "thesis_decay_review_days",
  "do_not_trade_event_window_days",
]);

const RUNTIME_SOURCE_IDS = [
  "current_position_snapshot",
  "current_market_data",
  "previous_target_state",
  "candidate_target_state",
  "final_target_state",
  "position_review_state",
  "cro_review_state",
  "execution_feasibility_state",
  "position_thesis_state",
  "upstream_agent_outputs",
  "portfolio_exposure_state",
  "execution_liquidity_state",
  "mirofish_context",
] as const;

export const RUNTIME_SOURCE_REGISTRY: Record<
  (typeof RUNTIME_SOURCE_IDS)[number],
  RuntimeSourceRegistryEntry
> = {
  current_position_snapshot: runtimeSource("current_position_snapshot", {
    scope: { account_id: "required", cohort: "required", run_id: "required" },
    schema: "daily_cycle.current_positions.v1",
    empty: true,
    producerMode: "eager",
    producerStage: "cycle_input",
    availableFromStage: "alpha_discovery",
    finalizedAtStage: "cycle_input",
    refreshPolicy: "frozen",
    provenanceAdapter: "portfolio.current_positions_adapter.v1",
    retryOwner: "cycle_input",
    crossCycleReuse: "forbidden",
  }),
  current_market_data: runtimeSource("current_market_data", {
    scope: { ticker: "required" },
    schema: "market.snapshot.v1",
    producerMode: "on_demand_pre_stage",
    producerStage: "pre_stage_source_resolution",
    availableFromStage: "agent_run",
    finalizedAtStage: "order_adapter",
    refreshPolicy: "versioned_per_call",
    provenanceAdapter: "market.scoped_snapshot_adapter.v1",
    retryOwner: "requesting_stage",
    crossCycleReuse: "forbidden",
  }),
  previous_target_state: runtimeSource("previous_target_state", {
    scope: { account_id: "required", cohort: "required" },
    schema: "portfolio.previous_target_state.v1",
    empty: true,
    producerMode: "eager",
    producerStage: "cycle_input",
    availableFromStage: "cio_proposal",
    finalizedAtStage: "cycle_input",
    refreshPolicy: "carry_forward_if_fresh",
    provenanceAdapter: "portfolio.previous_target_adapter.v1",
    retryOwner: "cycle_input",
    crossCycleReuse: "prior_cycle_only",
  }),
  candidate_target_state: runtimeSource("candidate_target_state", {
    scope: { account_id: "required", cohort: "required", run_id: "required" },
    schema: "portfolio.candidate_target_state.v1",
    producerMode: "stage_output",
    producerStage: "cio_proposal",
    availableFromStage: "cro_review",
    finalizedAtStage: "cio_proposal",
    refreshPolicy: "frozen",
    provenanceAdapter: "decision.cio_proposal_adapter.v1",
    retryOwner: "cio_proposal",
    crossCycleReuse: "forbidden",
  }),
  final_target_state: runtimeSource("final_target_state", {
    scope: { account_id: "required", cohort: "required", run_id: "required" },
    schema: "portfolio.final_target_state.v1",
    empty: true,
    producerMode: "stage_output",
    producerStage: "shared_validation",
    availableFromStage: "order_adapter",
    finalizedAtStage: "shared_validation",
    refreshPolicy: "frozen",
    provenanceAdapter: "portfolio.shared_validation_adapter.v1",
    retryOwner: "shared_validation",
    crossCycleReuse: "prior_cycle_only",
  }),
  position_review_state: runtimeSource("position_review_state", {
    scope: { account_id: "required", cohort: "required", run_id: "required" },
    schema: "daily_cycle.position_review_state.v1",
    producerMode: "stage_output",
    producerStage: "cio_proposal",
    availableFromStage: "cro_review",
    finalizedAtStage: "cio_proposal",
    refreshPolicy: "frozen",
    provenanceAdapter: "decision.position_review_adapter.v1",
    retryOwner: "cio_proposal",
    crossCycleReuse: "forbidden",
  }),
  cro_review_state: runtimeSource("cro_review_state", {
    scope: {
      account_id: "required",
      cohort: "required",
      run_id: "required",
      candidate_target_hash: "required",
    },
    schema: "decision.cro_review_state.v1",
    producerMode: "stage_output",
    producerStage: "cro_review",
    availableFromStage: "execution_feasibility",
    finalizedAtStage: "cro_review",
    refreshPolicy: "frozen",
    provenanceAdapter: "decision.cro_review_adapter.v1",
    retryOwner: "cro_review",
    crossCycleReuse: "forbidden",
  }),
  execution_feasibility_state: runtimeSource("execution_feasibility_state", {
    scope: {
      account_id: "required",
      cohort: "required",
      run_id: "required",
      candidate_target_hash: "required",
      market_vintage_hash: "required",
    },
    schema: "decision.execution_feasibility_state.v1",
    empty: true,
    producerMode: "stage_output",
    producerStage: "execution_feasibility",
    availableFromStage: "cio_final",
    finalizedAtStage: "execution_feasibility",
    refreshPolicy: "frozen",
    provenanceAdapter: "decision.execution_feasibility_adapter.v1",
    retryOwner: "execution_feasibility",
    crossCycleReuse: "forbidden",
  }),
  position_thesis_state: runtimeSource("position_thesis_state", {
    scope: { ticker: "required" },
    schema: "portfolio.position_thesis_state.v1",
    producerMode: "eager",
    producerStage: "cycle_input",
    availableFromStage: "cio_proposal",
    finalizedAtStage: "cycle_input",
    refreshPolicy: "carry_forward_if_fresh",
    provenanceAdapter: "portfolio.position_thesis_adapter.v1",
    retryOwner: "cycle_input",
    crossCycleReuse: "allowed_if_fresh",
  }),
  upstream_agent_outputs: runtimeSource("upstream_agent_outputs", {
    scope: { agent_id: "required", cohort: "required", run_id: "required" },
    schema: "daily_cycle.upstream_agent_outputs.v1",
    producerMode: "stage_output",
    producerStage: "agent_run",
    availableFromStage: "alpha_discovery",
    finalizedAtStage: "alpha_discovery",
    refreshPolicy: "frozen",
    provenanceAdapter: "daily_cycle.agent_output_adapter.v1",
    retryOwner: "producing_agent_stage",
    crossCycleReuse: "forbidden",
  }),
  portfolio_exposure_state: runtimeSource("portfolio_exposure_state", {
    scope: { account_id: "required", cohort: "required", run_id: "required" },
    schema: "portfolio.exposure_state.v1",
    producerMode: "stage_output",
    producerStage: "cio_proposal",
    availableFromStage: "cro_review",
    finalizedAtStage: "cio_proposal",
    refreshPolicy: "frozen",
    provenanceAdapter: "portfolio.exposure_adapter.v1",
    retryOwner: "cio_proposal",
    crossCycleReuse: "forbidden",
  }),
  execution_liquidity_state: runtimeSource("execution_liquidity_state", {
    scope: { ticker: "required" },
    schema: "execution.liquidity_state.v1",
    producerMode: "on_demand_pre_stage",
    producerStage: "pre_stage_source_resolution",
    availableFromStage: "execution_feasibility",
    finalizedAtStage: "execution_feasibility",
    refreshPolicy: "versioned_per_call",
    provenanceAdapter: "execution.liquidity_adapter.v1",
    retryOwner: "execution_feasibility",
    crossCycleReuse: "forbidden",
  }),
  mirofish_context: runtimeSource("mirofish_context", {
    scope: { context_hash: "required" },
    schema: "mirofish.context.v1",
    producerMode: "eager",
    producerStage: "cycle_input",
    availableFromStage: "cro_review",
    finalizedAtStage: "cycle_input",
    refreshPolicy: "frozen",
    provenanceAdapter: "mirofish.context_adapter.v1",
    retryOwner: "cycle_input",
    crossCycleReuse: "forbidden",
  }),
};

const REQUIRED_EVALUATION_METRIC_EXCLUSION_RULES = [
  "missing_required_runtime_source",
  "stale_required_runtime_source",
  "runtime_source_error",
  "lookahead_risk",
  "incomplete_fill",
] as const;

export const EVALUATION_CALCULATOR_REGISTRY: Record<string, EvaluationCalculatorRegistryEntry> = {
  "pit.signed_return": calculator("pit.signed_return", "calculate_signed_return", [
    "signed_return",
  ]),
  "pit.nonnegative_loss": calculator("pit.nonnegative_loss", "calculate_nonnegative_loss", [
    "nonnegative_loss_magnitude",
  ]),
  "pit.rate": calculator("pit.rate", "calculate_rate", ["rate_0_1"]),
  "pit.bps_cost": calculator("pit.bps_cost", "calculate_bps_cost", ["bps_cost"]),
  "pit.rank_correlation": calculator("pit.rank_correlation", "calculate_rank_correlation", [
    "score",
  ]),
  "pit.calibration_error": calculator("pit.calibration_error", "calculate_calibration_error", [
    "rate_0_1",
  ]),
};

export const EVALUATION_METRIC_REGISTRY: Record<string, EvaluationMetricRegistryEntry> = {
  macro_signal_accuracy_5d: rateMetric("macro_signal_accuracy_5d", "higher_is_better", "5d"),
  sector_rank_correlation_20d: rankCorrelationMetric("sector_rank_correlation_20d", "20d"),
  style_pick_alpha_60d: signedReturnMetric("style_pick_alpha_60d", "60d"),
  portfolio_construction_quality_20d: signedReturnMetric(
    "portfolio_construction_quality_20d",
    "20d",
  ),
  portfolio_risk_quality_20d: signedReturnMetric("portfolio_risk_quality_20d", "20d"),
  alpha_discovery_quality_20d: signedReturnMetric("alpha_discovery_quality_20d", "20d"),
  execution_quality_5d: bpsCostMetric("execution_quality_5d", "5d"),
  stale_thesis_review_alpha_20d: signedReturnMetric("stale_thesis_review_alpha_20d", "20d"),
  turnover_adjusted_alpha_20d: signedReturnMetric("turnover_adjusted_alpha_20d", "20d"),
  incremental_alpha_after_add_20d: signedReturnMetric("incremental_alpha_after_add_20d", "20d"),
  max_drawdown_after_hold: lossMetric("max_drawdown_after_hold", "20d", "max"),
  opportunity_cost_after_reduce: lossMetric("opportunity_cost_after_reduce", "20d", "mean"),
  concentration_breach_rate: rateMetric("concentration_breach_rate", "lower_is_better", "20d"),
  sector_concentration_breach_rate: rateMetric(
    "sector_concentration_breach_rate",
    "lower_is_better",
    "20d",
  ),
  churn_adjusted_slippage: lossMetric("churn_adjusted_slippage", "5d", "mean"),
  realized_slippage_bps: bpsCostMetric("realized_slippage_bps", "5d"),
  failed_or_partial_fill_rate: rateMetric("failed_or_partial_fill_rate", "lower_is_better", "5d"),
  turnover_adjusted_slippage: lossMetric("turnover_adjusted_slippage", "5d", "mean"),
  drawdown_avoidance_after_tail_veto: signedReturnMetric(
    "drawdown_avoidance_after_tail_veto",
    "20d",
  ),
  tail_loss_after_hold: lossMetric("tail_loss_after_hold", "20d", "max"),
  false_veto_adjusted_drawdown_avoidance: signedReturnMetric(
    "false_veto_adjusted_drawdown_avoidance",
    "20d",
  ),
  scenario_adjusted_slippage: lossMetric("scenario_adjusted_slippage", "5d", "mean"),
  tail_stress_drawdown_after_sizing: lossMetric("tail_stress_drawdown_after_sizing", "5d", "max"),
  stress_adjusted_alpha_20d: signedReturnMetric("stress_adjusted_alpha_20d", "20d"),
  regret_after_exit: lossMetric("regret_after_exit", "20d", "mean"),
  override_realized_risk: lossMetric("override_realized_risk", "20d", "max"),
  confidence_calibration_error: calibrationErrorMetric("confidence_calibration_error", "5d"),
  fallback_rate: rateMetric("fallback_rate", "lower_is_better", "5d"),
  missing_rate: rateMetric("missing_rate", "lower_is_better", "5d"),
  hit_rate_5d: rateMetric("hit_rate_5d", "higher_is_better", "5d"),
};

const TOOL_METRIC_OVERRIDES: Record<string, string[]> = {
  get_rke_research_context: ["research_prior"],
  get_balance_sheet: ["inventory_to_revenue", "inventory_turnover_days", "total_assets"],
  get_income_statement: ["gross_margin_change"],
  get_cashflow: [
    "capex_to_revenue",
    "construction_in_progress_change",
    "operating_cashflow_margin",
  ],
  get_stock_data: ["close", "volume"],
};

export function registeredMetricIdsForTool(tool: string): ReadonlySet<string> {
  return new Set([`${evidenceKeyForTool(tool)}_current`, ...(TOOL_METRIC_OVERRIDES[tool] ?? [])]);
}

const DOMAIN_SEEDS_BY_AGENT: Record<string, DomainSeed[]> = {
  central_bank: seeds([
    "pboc_fed_policy_weight",
    "liquidity_net_injection_window_days",
    "omo_mlf_freshness_days",
    "easing_threshold_bps",
    "tightening_threshold_bps",
    "policy_conflict_cap",
  ]),
  china: seeds([
    "pmi_weight",
    "social_financing_weight",
    "property_cycle_weight",
    "consumption_weight",
    "policy_confirmation_window_days",
    "a_share_beta_discount",
  ]),
  us_economy: seeds([
    "growth_weight",
    "employment_weight",
    "inflation_weight",
    "demand_weight",
    "surprise_window_days",
    "a_share_external_demand_weight",
  ]),
  dollar: seeds([
    "broad_dollar_trend_window_days",
    "rmb_pressure_weight",
    "fx_volatility_weight",
    "onshore_offshore_spread_weight",
    "a_share_fx_liquidity_weight",
    "dollar_pressure_cap",
  ]),
  yield_curve: seeds([
    "term_spread_window_days",
    "inversion_threshold_bps",
    "steepening_threshold_bps",
    "flattening_threshold_bps",
    "credit_spread_discount",
    "duration_risk_weight",
  ]),
  commodities: seeds([
    "oil_weight",
    "industrial_metals_weight",
    "precious_metals_weight",
    "agriculture_weight",
    "inventory_confirmation_window_days",
    "inflation_shock_transmission_weight",
  ]),
  volatility: seeds([
    "vix_weight",
    "china_realized_vol_weight",
    "cross_market_stress_weight",
    "risk_off_threshold",
    "vol_amplification_window_days",
    "volatility_cap",
  ]),
  market_breadth: seeds([
    "breadth_composite_weight",
    "breadth_state_confirmation_weight",
    "breadth_change_confirmation_weight",
    "return_dispersion_weight",
    "concentration_confirmation_weight",
    "a_share_transmission_weight",
  ]),
  institutional_flow: seeds([
    "market_flow_window_days",
    "sector_rotation_window_days",
    "flow_persistence_days",
    "main_net_inflow_threshold",
    "etf_share_change_weight",
    "crowding_confirmation_weight",
    "null_flow_fallback_cap",
  ]),
  geopolitical: seeds([
    "risk_event_severity_threshold",
    "sanction_weight",
    "conflict_weight",
    "supply_chain_weight",
    "event_decay_window_days",
    "risk_off_override_threshold",
  ]),
  semiconductor: seeds([
    "industry_moneyflow_days",
    "financial_statement_quarters",
    "inventory_cycle_quarters",
    "capex_cycle_quarters",
    "price_momentum_days",
    "policy_digest_days",
    "broker_research_days",
    "design_weight",
    "equipment_weight",
    "foundry_weight",
    "packaging_weight",
    "materials_weight",
    "ai_compute_weight",
    "inventory_to_revenue_risk",
    "gross_margin_change_min",
    "capex_to_revenue_min",
    "price_confirmation_pct",
    "valuation_risk_max",
    "max_verified_constituents",
    "min_long_conviction",
    "min_short_conviction",
    "localization_policy_weight",
    "export_control_discount",
  ]),
  energy: seeds([
    "oil_price_transmission_weight",
    "coal_price_weight",
    "power_tariff_policy_weight",
    "energy_security_theme_weight",
    "inventory_window_days",
    "refining_margin_threshold",
  ]),
  biotech: seeds([
    "pipeline_stage_weight",
    "medical_insurance_discount",
    "approval_catalyst_window_days",
    "cxo_external_demand_weight",
    "clinical_failure_risk_cap",
    "valuation_risk_threshold",
  ]),
  consumer: seeds([
    "income_elasticity_weight",
    "property_chain_weight",
    "inventory_cycle_window_days",
    "consumption_policy_weight",
    "premium_brand_discount",
    "margin_recovery_threshold",
  ]),
  industrials: seeds([
    "capex_weight",
    "export_chain_weight",
    "military_order_confirmation_days",
    "policy_catalyst_window_days",
    "order_backlog_threshold",
    "capacity_utilization_weight",
  ]),
  financials: seeds([
    "curve_weight",
    "property_risk_discount",
    "turnover_beta_weight",
    "insurance_rate_sensitivity",
    "credit_risk_cap",
    "brokerage_volume_threshold",
  ]),
  relationship_mapper: seeds([
    "supply_chain_transmission_strength",
    "etf_overlap_threshold",
    "holding_overlap_threshold",
    "policy_resonance_weight",
    "flow_diffusion_window_days",
    "cross_sector_spillover_threshold",
  ]),
  druckenmiller: seeds([
    "trend_confirmation_window_days",
    "payoff_threshold",
    "error_cut_rule",
    "concentration_cap",
    "macro_weight",
  ]),
  burry: seeds([
    "valuation_mispricing_threshold",
    "distress_catalyst_weight",
    "downside_protection_min",
    "short_signal_window_days",
    "crowding_penalty",
  ]),
  munger: seeds([
    "moat_score_min",
    "pricing_power_weight",
    "capital_allocation_quality_min",
    "compounder_window_days",
    "balance_sheet_quality_weight",
  ]),
  ackman: seeds([
    "growth_quality_min",
    "free_cashflow_growth_weight",
    "operating_leverage_threshold",
    "activist_catalyst_window_days",
    "brand_quality_weight",
  ]),
  cro: seeds([
    "stop_loss_pct",
    "take_profit_review_pct",
    "max_single_name_weight",
    "max_sector_weight",
    "mirofish_tail_scenario_weight",
    "mirofish_drawdown_penalty",
    "mirofish_max_tail_loss_to_hold",
    "mirofish_tail_risk_veto_threshold",
  ]).concat(
    readOnlySeeds([
      "liquidity_discount",
      "correlation_stress_threshold",
      "max_correlation_cluster_weight",
      "portfolio_drawdown_cap",
    ]),
  ),
  alpha_discovery: seeds([
    "novelty_floor",
    "cross_agent_agreement_threshold",
    "theme_persistence_days",
    "idea_decay_days",
    "false_positive_penalty",
    "upstream_disagreement_filter",
  ]),
  autonomous_execution: seeds([
    "min_delta_trade_weight",
    "slippage_cap",
    "liquidity_floor",
    "max_order_split_count",
    "mirofish_path_sizing_weight",
    "mirofish_max_size_adjustment",
    "mirofish_turnover_penalty",
    "mirofish_liquidity_stress_haircut",
  ]).concat(
    readOnlySeeds([
      "execution_urgency_threshold",
      "cio_cro_conflict_threshold",
      "do_not_trade_event_window_days",
    ]),
  ),
  cio: seeds([
    "stale_thesis_days",
    "rebalance_drift_pct",
    "min_confidence_to_add",
    "min_confidence_to_hold",
    "mirofish_portfolio_stress_weight",
    "mirofish_exit_regret_penalty",
    "mirofish_min_scenario_agreement_to_add",
    "mirofish_override_hurdle",
  ]).concat(
    readOnlySeeds([
      "position_review_days",
      "rebalance_cooldown_days",
      "thesis_decay_review_days",
      "target_count_min",
      "target_count_max",
      "max_target_position_weight",
      "max_new_buy_weight",
      "rebalance_threshold",
      "new_buy_hurdle",
      "hold_hurdle",
      "trim_threshold",
      "exit_threshold",
      "conviction_upgrade_min_delta",
      "liquidity_penalty_max",
      "macro_signal_weight",
      "sector_signal_weight",
      "superinvestor_signal_weight",
      "cro_risk_weight",
      "min_upstream_confidence",
      "cross_layer_conflict_cap",
    ]),
  ),
};

const CUSTOM_RANGES_BY_ID: Record<
  string,
  { default: number; min: number; max: number; step: number }
> = {
  stale_thesis_days: { default: 20, min: 5, max: 60, step: 5 },
  rebalance_drift_pct: { default: 0.03, min: 0.01, max: 0.1, step: 0.01 },
  min_confidence_to_add: { default: 0.65, min: 0.5, max: 0.85, step: 0.05 },
  min_confidence_to_hold: { default: 0.5, min: 0.35, max: 0.7, step: 0.05 },
  target_count_min: { default: 8, min: 3, max: 20, step: 1 },
  target_count_max: { default: 15, min: 5, max: 30, step: 1 },
  max_target_position_weight: { default: 0.08, min: 0.02, max: 0.2, step: 0.01 },
  max_new_buy_weight: { default: 0.04, min: 0.01, max: 0.1, step: 0.01 },
  new_buy_hurdle: { default: 0.72, min: 0.5, max: 0.9, step: 0.01 },
  hold_hurdle: { default: 0.58, min: 0.4, max: 0.8, step: 0.01 },
  trim_threshold: { default: 0.45, min: 0.2, max: 0.7, step: 0.01 },
  exit_threshold: { default: 0.35, min: 0.1, max: 0.6, step: 0.01 },
  macro_signal_weight: { default: 0.25, min: 0, max: 0.6, step: 0.05 },
  sector_signal_weight: { default: 0.35, min: 0, max: 0.6, step: 0.05 },
  superinvestor_signal_weight: { default: 0.25, min: 0, max: 0.6, step: 0.05 },
  cro_risk_weight: { default: 0.15, min: 0, max: 0.5, step: 0.05 },
  cross_layer_conflict_cap: { default: 0.6, min: 0.3, max: 0.8, step: 0.05 },
  industry_moneyflow_days: { default: 20, min: 5, max: 60, step: 5 },
  financial_statement_quarters: { default: 4, min: 2, max: 8, step: 1 },
  inventory_cycle_quarters: { default: 4, min: 2, max: 8, step: 1 },
  capex_cycle_quarters: { default: 4, min: 2, max: 8, step: 1 },
  price_momentum_days: { default: 20, min: 5, max: 60, step: 5 },
  policy_digest_days: { default: 30, min: 7, max: 90, step: 1 },
  broker_research_days: { default: 60, min: 15, max: 180, step: 5 },
  design_weight: { default: 0.18, min: 0, max: 0.5, step: 0.01 },
  equipment_weight: { default: 0.18, min: 0, max: 0.5, step: 0.01 },
  foundry_weight: { default: 0.16, min: 0, max: 0.5, step: 0.01 },
  packaging_weight: { default: 0.12, min: 0, max: 0.5, step: 0.01 },
  materials_weight: { default: 0.1, min: 0, max: 0.5, step: 0.01 },
  ai_compute_weight: { default: 0.26, min: 0, max: 0.5, step: 0.01 },
  inventory_to_revenue_risk: { default: 0.3, min: 0.1, max: 0.6, step: 0.05 },
  gross_margin_change_min: { default: -0.03, min: -0.15, max: 0.1, step: 0.01 },
  capex_to_revenue_min: { default: 0.08, min: 0, max: 0.25, step: 0.01 },
  price_confirmation_pct: { default: 0.03, min: 0, max: 0.15, step: 0.01 },
  valuation_risk_max: { default: 0.7, min: 0.3, max: 0.95, step: 0.05 },
  max_verified_constituents: { default: 3, min: 1, max: 6, step: 1 },
  min_long_conviction: { default: 0.65, min: 0.45, max: 0.9, step: 0.05 },
  min_short_conviction: { default: 0.6, min: 0.4, max: 0.85, step: 0.05 },
  localization_policy_weight: { default: 0.25, min: 0, max: 0.6, step: 0.05 },
  export_control_discount: { default: 0.2, min: 0, max: 0.6, step: 0.05 },
  stop_loss_pct: { default: -0.08, min: -0.2, max: -0.03, step: 0.01 },
  take_profit_review_pct: { default: 0.2, min: 0.08, max: 0.4, step: 0.02 },
  max_single_name_weight: { default: 0.12, min: 0.05, max: 0.2, step: 0.01 },
  max_sector_weight: { default: 0.3, min: 0.15, max: 0.45, step: 0.05 },
  min_delta_trade_weight: { default: 0.01, min: 0.005, max: 0.05, step: 0.005 },
  slippage_cap: { default: 0.003, min: 0.001, max: 0.02, step: 0.001 },
  liquidity_floor: { default: 0.6, min: 0.3, max: 0.9, step: 0.05 },
  max_order_split_count: { default: 5, min: 1, max: 20, step: 1 },
  mirofish_tail_scenario_weight: { default: 0.25, min: 0.05, max: 0.5, step: 0.05 },
  mirofish_drawdown_penalty: { default: 0.35, min: 0.1, max: 0.7, step: 0.05 },
  mirofish_max_tail_loss_to_hold: { default: -0.12, min: -0.25, max: -0.05, step: 0.01 },
  mirofish_tail_risk_veto_threshold: { default: 0.7, min: 0.5, max: 0.9, step: 0.05 },
  mirofish_path_sizing_weight: { default: 0.2, min: 0.05, max: 0.5, step: 0.05 },
  mirofish_max_size_adjustment: { default: 0.03, min: 0.01, max: 0.08, step: 0.01 },
  mirofish_turnover_penalty: { default: 0.1, min: 0, max: 0.3, step: 0.05 },
  mirofish_liquidity_stress_haircut: { default: 0.15, min: 0, max: 0.4, step: 0.05 },
  mirofish_portfolio_stress_weight: { default: 0.2, min: 0.05, max: 0.5, step: 0.05 },
  mirofish_exit_regret_penalty: { default: 0.2, min: 0.05, max: 0.5, step: 0.05 },
  mirofish_min_scenario_agreement_to_add: { default: 0.6, min: 0.4, max: 0.85, step: 0.05 },
  mirofish_override_hurdle: { default: 0.75, min: 0.55, max: 0.9, step: 0.05 },
};

const METRIC_BY_ID: Record<string, string> = {
  stale_thesis_days: "stale_thesis_review_alpha_20d",
  rebalance_drift_pct: "turnover_adjusted_alpha_20d",
  min_confidence_to_add: "incremental_alpha_after_add_20d",
  min_confidence_to_hold: "max_drawdown_after_hold",
  stop_loss_pct: "max_drawdown_after_hold",
  take_profit_review_pct: "opportunity_cost_after_reduce",
  max_single_name_weight: "concentration_breach_rate",
  max_sector_weight: "sector_concentration_breach_rate",
  min_delta_trade_weight: "churn_adjusted_slippage",
  slippage_cap: "realized_slippage_bps",
  liquidity_floor: "failed_or_partial_fill_rate",
  max_order_split_count: "turnover_adjusted_slippage",
  mirofish_tail_scenario_weight: "drawdown_avoidance_after_tail_veto",
  mirofish_drawdown_penalty: "max_drawdown_after_hold",
  mirofish_max_tail_loss_to_hold: "tail_loss_after_hold",
  mirofish_tail_risk_veto_threshold: "false_veto_adjusted_drawdown_avoidance",
  mirofish_path_sizing_weight: "scenario_adjusted_slippage",
  mirofish_max_size_adjustment: "tail_stress_drawdown_after_sizing",
  mirofish_turnover_penalty: "turnover_adjusted_slippage",
  mirofish_liquidity_stress_haircut: "failed_or_partial_fill_rate",
  mirofish_portfolio_stress_weight: "stress_adjusted_alpha_20d",
  mirofish_exit_regret_penalty: "regret_after_exit",
  mirofish_min_scenario_agreement_to_add: "incremental_alpha_after_add_20d",
  mirofish_override_hurdle: "override_realized_risk",
};

const PREDICTION_TARGET_BY_ID: Record<string, string> = {
  stale_thesis_days: "thesis_quality_20d",
  rebalance_drift_pct: "portfolio_rebalance_quality_20d",
  min_confidence_to_add: "add_decision_quality_20d",
  min_confidence_to_hold: "hold_exit_quality_20d",
  stop_loss_pct: "hold_exit_quality_20d",
  take_profit_review_pct: "reduce_decision_quality_20d",
  max_single_name_weight: "portfolio_risk_quality_20d",
  max_sector_weight: "portfolio_risk_quality_20d",
  min_delta_trade_weight: "execution_quality_5d",
  slippage_cap: "execution_quality_5d",
  liquidity_floor: "execution_quality_5d",
  max_order_split_count: "execution_quality_5d",
  mirofish_tail_scenario_weight: "tail_risk_review_20d",
  mirofish_drawdown_penalty: "portfolio_risk_quality_20d",
  mirofish_max_tail_loss_to_hold: "hold_exit_quality_20d",
  mirofish_tail_risk_veto_threshold: "tail_risk_review_20d",
  mirofish_path_sizing_weight: "execution_quality_5d",
  mirofish_max_size_adjustment: "execution_quality_5d",
  mirofish_turnover_penalty: "execution_quality_5d",
  mirofish_liquidity_stress_haircut: "execution_quality_5d",
  mirofish_portfolio_stress_weight: "portfolio_construction_quality_20d",
  mirofish_exit_regret_penalty: "hold_exit_quality_20d",
  mirofish_min_scenario_agreement_to_add: "add_decision_quality_20d",
  mirofish_override_hurdle: "override_quality_20d",
};

const LEARNING_OBJECTIVE_BY_ID: Record<string, string> = {
  stale_thesis_days: "calibrate when CIO must refresh stale thesis before continuing hold",
  rebalance_drift_pct: "learn target-current drift tolerance before rebalance",
  min_confidence_to_add: "calibrate add hurdle for new or existing position expansion",
  min_confidence_to_hold: "calibrate hold versus exit threshold under uncertain thesis quality",
  stop_loss_pct: "calibrate risk exit threshold for losing positions",
  take_profit_review_pct: "learn when gains require risk review instead of automatic hold",
  max_single_name_weight: "calibrate single-name concentration ceiling",
  max_sector_weight: "calibrate sector concentration ceiling",
  min_delta_trade_weight: "learn minimum useful trade delta to avoid churn",
  slippage_cap: "calibrate maximum acceptable execution cost",
  liquidity_floor: "learn liquidity floor for executable target changes",
  max_order_split_count: "learn order splitting complexity versus execution benefit",
  mirofish_tail_scenario_weight: "learn how strongly tail scenarios should affect CRO risk review",
  mirofish_drawdown_penalty: "calibrate scenario drawdown penalty for risk holds",
  mirofish_max_tail_loss_to_hold: "learn tail-loss threshold for allowing hold",
  mirofish_tail_risk_veto_threshold: "calibrate CRO veto threshold from scenario tail risk",
  mirofish_path_sizing_weight: "learn how path stress should adjust execution sizing",
  mirofish_max_size_adjustment: "calibrate maximum scenario-driven size adjustment",
  mirofish_turnover_penalty: "learn turnover penalty when scenario stress changes trade path",
  mirofish_liquidity_stress_haircut: "learn liquidity haircut under stressed scenario paths",
  mirofish_portfolio_stress_weight: "learn how portfolio stress should affect final construction",
  mirofish_exit_regret_penalty: "calibrate regret penalty when scenario argues against exit",
  mirofish_min_scenario_agreement_to_add: "learn scenario agreement hurdle for adding exposure",
  mirofish_override_hurdle: "calibrate hurdle for overriding base decision with scenario stress",
};

export function domainKnobCardsForSpec(spec: RuntimeAgentSpec): DomainKnobCard[] {
  const seedsForAgent = DOMAIN_SEEDS_BY_AGENT[spec.agent] ?? [];
  return seedsForAgent.map((seed) => buildCard(spec, seed));
}

export function domainKnobDescriptorFromPath(
  path: string,
): { agent: string; id: string; projection_bucket: ProjectionBucket } | null {
  const match = path.match(
    /^\/rule_packs\/[^/]+\/rules\/[^/]+\/learnable_parameters\/([^/]+)\/value$/,
  );
  const agent = path.match(
    /^\/rule_packs\/(?:macro|sector|superinvestor|decision)\.([^.]+)\./,
  )?.[1];
  const id = match?.[1];
  if (!agent || !id) {
    return null;
  }
  const seed = (DOMAIN_SEEDS_BY_AGENT[agent] ?? []).find((item) => item.id === id);
  if (!seed) {
    return null;
  }
  return {
    agent,
    id,
    projection_bucket: seed.bucket ?? bucketForId(id),
  };
}

export function domainKnobCardFromPath(path: string): DomainKnobCard | null {
  const descriptor = domainKnobDescriptorFromPath(path);
  if (!descriptor) return null;
  const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(descriptor.agent);
  if (!spec) return null;
  return domainKnobCardsForSpec(spec).find((card) => card.path === path) ?? null;
}

export function minDomainTargetCount(layer: Layer, agent: string): number {
  if (agent === "semiconductor") return 12;
  if (layer === "superinvestor") return 4;
  return 6;
}

export function buildDomainKnobCatalogArtifact(
  specs: ReadonlyArray<RuntimeAgentSpec> = RUNTIME_AGENT_SPECS,
): DomainKnobCatalogArtifact {
  const agents = specs.map((spec) => {
    const cards = sortDomainKnobCards(domainKnobCardsForSpec(spec));
    return {
      layer: spec.layer,
      agent: spec.agent,
      prompt_ir_agent: spec.promptIrAgentId,
      min_mutable_domain_knobs: minDomainTargetCount(spec.layer, spec.agent),
      card_count: cards.length,
      cards,
    };
  });
  return {
    schema_version: DOMAIN_KNOB_CATALOG_VERSION,
    catalog_version: DOMAIN_KNOB_CATALOG_VERSION,
    runtime_agent_count: specs.length,
    runtime_sources: sortObjectRecord(RUNTIME_SOURCE_REGISTRY),
    evaluation_metrics: sortObjectRecord(EVALUATION_METRIC_REGISTRY),
    evaluation_calculators: sortObjectRecord(EVALUATION_CALCULATOR_REGISTRY),
    agents,
  };
}

export function renderDomainKnobCatalogArtifact(
  artifact: DomainKnobCatalogArtifact = buildDomainKnobCatalogArtifact(),
): string {
  return `${JSON.stringify(canonicalDomainKnobCatalogArtifact(artifact), null, 2)}\n`;
}

export function buildDomainKnobEvaluationContractArtifact(
  catalog: DomainKnobCatalogArtifact = buildDomainKnobCatalogArtifact(),
): DomainKnobEvaluationContractArtifact {
  const canonicalCatalog = canonicalDomainKnobCatalogArtifact(catalog);
  const evaluationMetrics = sortObjectRecord(canonicalCatalog.evaluation_metrics);
  const evaluationCalculators = sortObjectRecord(canonicalCatalog.evaluation_calculators);
  const genericBindings = RUNTIME_AGENT_SPECS.flatMap((spec) => {
    const metricIds = genericEvaluationMetricIds(spec);
    const horizons = [
      ...new Set(
        metricIds
          .map((metricId) => evaluationMetrics[metricId]?.window)
          .filter((window): window is string => Boolean(window)),
      ),
    ].sort();
    return genericGovernanceTargetDefinitions(spec).map((definition) => ({
      path: definition.path,
      owner_agent: spec.promptIrAgentId,
      owner_stages: spec.stages.map((stage) => stage.stage),
      target_type: definition.target.type,
      minimum: definition.target.min,
      maximum: definition.target.max,
      step: definition.target.step,
      weight_group: definition.weightGroup ?? null,
      write_back_repo_id: "MOSAIC-Prompts" as const,
      write_back_path_template: `registry/prompt_governance/{cohort}/${spec.agent}.json`,
      write_back_json_pointer: `/values_by_path/${escapeJsonPointer(definition.path)}`,
      evaluation_metrics: metricIds,
      horizons,
      rollback_metrics: metricIds,
    }));
  }).sort((left, right) => left.path.localeCompare(right.path));
  const cardBindings = canonicalCatalog.agents
    .flatMap((agent) =>
      agent.cards.map((card) => ({
        path: card.path,
        card_id: card.id,
        owner_agent: card.owner_agent,
        owner_stage: card.owner_stage,
        activation_state: card.activation_state,
        prediction_target: card.prediction_target,
        evaluation_metric: card.evaluation_metric,
        secondary_metrics: [...card.secondary_metrics].sort(),
        horizon: card.horizon,
        rollback_condition: card.rollback_condition,
      })),
    )
    .sort((left, right) => left.path.localeCompare(right.path));
  const contractWithoutHash: Omit<DomainKnobEvaluationContractArtifact, "contract_hash"> = {
    schema_version: DOMAIN_KNOB_EVALUATION_CONTRACT_VERSION,
    contract_version: DOMAIN_KNOB_EVALUATION_CONTRACT_VERSION,
    catalog_version: DOMAIN_KNOB_CATALOG_VERSION,
    schema_hash: domainKnobEvaluationContractSchemaHash(),
    catalog_hash: sha256Json(canonicalCatalog),
    metric_registry_hash: sha256Json(evaluationMetrics),
    calculator_registry_hash: sha256Json(evaluationCalculators),
    evaluation_metrics: evaluationMetrics,
    evaluation_calculators: evaluationCalculators,
    generic_bindings: genericBindings,
    card_bindings: cardBindings,
  };
  return {
    ...contractWithoutHash,
    contract_hash: sha256Json(contractWithoutHash),
  };
}

export function renderDomainKnobEvaluationContractArtifact(
  artifact: DomainKnobEvaluationContractArtifact = buildDomainKnobEvaluationContractArtifact(),
): string {
  return `${JSON.stringify(artifact, null, 2)}\n`;
}

export function validateDomainKnobEvaluationContractArtifact(
  artifact: DomainKnobEvaluationContractArtifact,
  catalog: DomainKnobCatalogArtifact = buildDomainKnobCatalogArtifact(),
): string[] {
  const reasons: string[] = [];
  if (artifact.schema_version !== DOMAIN_KNOB_EVALUATION_CONTRACT_VERSION) {
    reasons.push(`evaluation_contract_schema_version_mismatch:${artifact.schema_version}`);
  }
  if (artifact.contract_version !== DOMAIN_KNOB_EVALUATION_CONTRACT_VERSION) {
    reasons.push(`evaluation_contract_version_mismatch:${artifact.contract_version}`);
  }
  const { contract_hash: contractHash, ...contractPayload } = artifact;
  if (contractHash !== sha256Json(contractPayload)) {
    reasons.push("evaluation_contract_hash_mismatch:contract_hash");
  }
  const expected = buildDomainKnobEvaluationContractArtifact(catalog);
  for (const field of [
    "schema_hash",
    "catalog_hash",
    "metric_registry_hash",
    "calculator_registry_hash",
    "contract_hash",
  ] as const) {
    if (field !== "contract_hash" && artifact[field] !== expected[field]) {
      reasons.push(`evaluation_contract_hash_mismatch:${field}`);
    }
  }
  const expectedBindings = new Map(
    expected.card_bindings.map((binding) => [binding.path, binding]),
  );
  const seenPaths = new Set<string>();
  for (const binding of artifact.card_bindings) {
    if (seenPaths.has(binding.path)) {
      reasons.push(`evaluation_contract_duplicate_card_path:${binding.path}`);
    }
    seenPaths.add(binding.path);
    const expectedBinding = expectedBindings.get(binding.path);
    if (!expectedBinding || JSON.stringify(binding) !== JSON.stringify(expectedBinding)) {
      reasons.push(`evaluation_contract_card_binding_mismatch:${binding.path}`);
    }
    const metric = artifact.evaluation_metrics[binding.evaluation_metric];
    if (!metric) {
      reasons.push(
        `evaluation_contract_metric_missing:${binding.path}:${binding.evaluation_metric}`,
      );
      continue;
    }
    if (metric.window !== binding.horizon) {
      reasons.push(`evaluation_contract_metric_window_mismatch:${binding.path}`);
    }
    const calculator = artifact.evaluation_calculators[metric.calculator_id];
    if (!calculator || calculator.version !== metric.calculator_version) {
      reasons.push(`evaluation_contract_calculator_binding_missing:${binding.path}`);
    }
  }
  if (seenPaths.size !== expectedBindings.size) {
    reasons.push(
      `evaluation_contract_card_count_mismatch:${seenPaths.size}:expected:${expectedBindings.size}`,
    );
  }
  const expectedGenericBindings = new Map(
    expected.generic_bindings.map((binding) => [binding.path, binding]),
  );
  const seenGenericPaths = new Set<string>();
  for (const binding of artifact.generic_bindings) {
    if (seenGenericPaths.has(binding.path)) {
      reasons.push(`evaluation_contract_duplicate_generic_path:${binding.path}`);
    }
    seenGenericPaths.add(binding.path);
    const expectedBinding = expectedGenericBindings.get(binding.path);
    if (!expectedBinding || JSON.stringify(binding) !== JSON.stringify(expectedBinding)) {
      reasons.push(`evaluation_contract_generic_binding_mismatch:${binding.path}`);
    }
    for (const metricId of binding.evaluation_metrics) {
      const metric = artifact.evaluation_metrics[metricId];
      if (!metric || !binding.horizons.includes(metric.window)) {
        reasons.push(`evaluation_contract_generic_metric_mismatch:${binding.path}:${metricId}`);
      }
    }
  }
  if (seenGenericPaths.size !== expectedGenericBindings.size) {
    reasons.push(
      `evaluation_contract_generic_count_mismatch:${seenGenericPaths.size}:expected:${expectedGenericBindings.size}`,
    );
  }
  return reasons;
}

function genericEvaluationMetricIds(spec: RuntimeAgentSpec): string[] {
  const metrics = new Set([
    "confidence_calibration_error",
    "fallback_rate",
    "missing_rate",
    "hit_rate_5d",
  ]);
  const layerMetric =
    spec.layer === "macro"
      ? "macro_signal_accuracy_5d"
      : spec.layer === "sector"
        ? "sector_rank_correlation_20d"
        : spec.layer === "superinvestor"
          ? "style_pick_alpha_60d"
          : spec.agent === "cro"
            ? "portfolio_risk_quality_20d"
            : spec.agent === "autonomous_execution"
              ? "execution_quality_5d"
              : spec.agent === "alpha_discovery"
                ? "alpha_discovery_quality_20d"
                : "portfolio_construction_quality_20d";
  metrics.add(layerMetric);
  return [...metrics].sort();
}

function escapeJsonPointer(value: string): string {
  return value.replace(/~/g, "~0").replace(/\//g, "~1");
}

export function validateDomainKnobCatalogArtifact(
  artifact: DomainKnobCatalogArtifact,
  specs: ReadonlyArray<RuntimeAgentSpec> = RUNTIME_AGENT_SPECS,
): string[] {
  const reasons: string[] = [];
  if (artifact.schema_version !== DOMAIN_KNOB_CATALOG_VERSION) {
    reasons.push(`domain_catalog_schema_version_mismatch:${artifact.schema_version}`);
  }
  if (artifact.catalog_version !== DOMAIN_KNOB_CATALOG_VERSION) {
    reasons.push(`domain_catalog_version_mismatch:${artifact.catalog_version}`);
  }
  if (artifact.runtime_agent_count !== specs.length) {
    reasons.push(
      `domain_catalog_runtime_agent_count_mismatch:${artifact.runtime_agent_count}:expected:${specs.length}`,
    );
  }
  const expectedRuntimeSources = Object.keys(RUNTIME_SOURCE_REGISTRY).sort();
  const actualRuntimeSources = Object.keys(artifact.runtime_sources).sort();
  if (expectedRuntimeSources.join(",") !== actualRuntimeSources.join(",")) {
    reasons.push("domain_catalog_runtime_source_registry_mismatch");
  }
  for (const [sourceId, sourceEntry] of Object.entries(artifact.runtime_sources)) {
    reasons.push(...validateRuntimeSourceRegistryEntry(sourceId, sourceEntry));
  }
  const expectedMetrics = Object.keys(EVALUATION_METRIC_REGISTRY).sort();
  const actualMetrics = Object.keys(artifact.evaluation_metrics).sort();
  if (expectedMetrics.join(",") !== actualMetrics.join(",")) {
    reasons.push("domain_catalog_evaluation_metric_registry_mismatch");
  }
  for (const [metricId, metricEntry] of Object.entries(artifact.evaluation_metrics)) {
    reasons.push(...validateEvaluationMetricEntry(metricId, metricEntry));
  }
  const expectedCalculators = Object.keys(EVALUATION_CALCULATOR_REGISTRY).sort();
  const actualCalculators = Object.keys(artifact.evaluation_calculators).sort();
  if (expectedCalculators.join(",") !== actualCalculators.join(",")) {
    reasons.push("domain_catalog_evaluation_calculator_registry_mismatch");
  }
  for (const [calculatorId, calculatorEntry] of Object.entries(artifact.evaluation_calculators)) {
    reasons.push(...validateEvaluationCalculatorEntry(calculatorId, calculatorEntry));
  }
  const agentsById = new Map(artifact.agents.map((agent) => [agent.agent, agent]));
  const seenPaths = new Set<string>();
  for (const spec of specs) {
    const agent = agentsById.get(spec.agent);
    if (!agent) {
      reasons.push(`domain_catalog_agent_missing:${spec.agent}`);
      continue;
    }
    if (agent.layer !== spec.layer || agent.prompt_ir_agent !== spec.promptIrAgentId) {
      reasons.push(`domain_catalog_agent_identity_mismatch:${spec.agent}`);
    }
    const expectedCards = domainKnobCardsForSpec(spec);
    if (agent.card_count !== agent.cards.length || agent.cards.length !== expectedCards.length) {
      reasons.push(
        `domain_catalog_card_count_mismatch:${spec.agent}:${agent.cards.length}:expected:${expectedCards.length}`,
      );
    }
    if (
      agent.cards.filter(
        (card) => card.coverage_level !== "gap_pending_tool" && card.activation_state === "active",
      ).length < agent.min_mutable_domain_knobs
    ) {
      reasons.push(`domain_catalog_min_domain_count_mismatch:${spec.agent}`);
    }
    const expectedByPath = new Map(expectedCards.map((card) => [card.path, card]));
    for (const card of agent.cards) {
      const expected = expectedByPath.get(card.path);
      if (!expected) {
        reasons.push(`domain_catalog_unknown_card_path:${spec.agent}:${card.path}`);
        continue;
      }
      if (
        JSON.stringify(canonicalDomainCard(card)) !== JSON.stringify(canonicalDomainCard(expected))
      ) {
        reasons.push(`domain_catalog_card_stale:${spec.agent}:${card.id}`);
      }
      if (seenPaths.has(card.path)) {
        reasons.push(`domain_catalog_duplicate_path:${card.path}`);
      }
      seenPaths.add(card.path);
      reasons.push(...validateCardSourceBinding(card));
      for (const source of card.runtime_input_sources) {
        if (!Object.hasOwn(artifact.runtime_sources, source)) {
          reasons.push(`domain_catalog_card_runtime_source_unregistered:${card.id}:${source}`);
        }
      }
      if (!Object.hasOwn(artifact.evaluation_metrics, card.evaluation_metric)) {
        reasons.push(
          `domain_catalog_card_metric_unregistered:${card.id}:${card.evaluation_metric}`,
        );
      }
      if (!Object.hasOwn(artifact.evaluation_metrics, card.rollback_condition.metric)) {
        reasons.push(`domain_catalog_card_rollback_metric_unregistered:${card.id}`);
      }
      for (const metricId of card.secondary_metrics) {
        if (!Object.hasOwn(artifact.evaluation_metrics, metricId)) {
          reasons.push(`domain_catalog_card_secondary_metric_unregistered:${card.id}:${metricId}`);
        }
      }
      reasons.push(...validateCardMetricCompatibility(card, artifact.evaluation_metrics));
    }
  }
  for (const agent of artifact.agents) {
    if (!specs.some((spec) => spec.agent === agent.agent)) {
      reasons.push(`domain_catalog_unknown_agent:${agent.agent}`);
    }
  }
  return reasons;
}

export function validateDomainKnobClosure(
  spec: RuntimeAgentSpec,
  knobs: Pick<
    ResearchKnobs,
    | "evidence_registry"
    | "evidence_weights"
    | "lookbacks"
    | "thresholds"
    | "confidence_caps"
    | "tie_breaks"
    | "mutation_targets"
  >,
  opts: { domainRegistry?: DomainKnobValueRegistry | null | undefined; cohort?: string } = {},
): string[] {
  const reasons: string[] = [];
  const cards = domainKnobCardsForSpec(spec);
  const mutableCards = cards.filter(
    (card) =>
      card.category === "domain" &&
      card.coverage_level !== "gap_pending_tool" &&
      card.activation_state === "active",
  );
  const minCount = minDomainTargetCount(spec.layer, spec.agent);
  if (mutableCards.length < minCount) {
    reasons.push(`domain_knob_count_below_min:${mutableCards.length}:expected:${minCount}`);
  }
  const targetPaths = new Set(knobs.mutation_targets.map((target) => target.path));
  for (const card of cards.filter((candidate) => candidate.coverage_level !== "gap_pending_tool")) {
    reasons.push(
      ...validateCard(
        spec,
        card,
        knobs,
        targetPaths,
        opts.domainRegistry,
        card.activation_state === "active",
      ),
    );
  }
  return reasons;
}

function validateCard(
  spec: RuntimeAgentSpec,
  card: DomainKnobCard,
  knobs: Pick<
    ResearchKnobs,
    | "evidence_registry"
    | "evidence_weights"
    | "lookbacks"
    | "thresholds"
    | "confidence_caps"
    | "tie_breaks"
  >,
  targetPaths: ReadonlySet<string>,
  domainRegistry?: DomainKnobValueRegistry | null,
  requireMutationTarget = true,
): string[] {
  const reasons: string[] = [];
  if (card.owner_agent !== spec.promptIrAgentId) {
    reasons.push(`domain_card_owner_mismatch:${card.id}`);
  }
  if (!card.consumer_agents.includes(card.owner_agent)) {
    reasons.push(`domain_card_missing_owner_consumer:${card.id}`);
  }
  if (!spec.stages.some((stage) => stage.stage === card.owner_stage)) {
    reasons.push(`domain_card_owner_stage_mismatch:${card.id}:${card.owner_stage}`);
  }
  if (!card.consumer_stages.includes(card.owner_stage)) {
    reasons.push(`domain_card_missing_owner_consumer_stage:${card.id}:${card.owner_stage}`);
  }
  if (requireMutationTarget && !targetPaths.has(card.path)) {
    reasons.push(`domain_card_missing_mutation_target:${card.id}`);
  }
  if (!requireMutationTarget && targetPaths.has(card.path)) {
    reasons.push(`domain_card_inactive_mutation_target_present:${card.id}`);
  }
  if (card.learning_objective.trim().length < 12) {
    reasons.push(`domain_card_learning_objective_missing:${card.id}`);
  }
  if (!(card.evaluation_metric in EVALUATION_METRIC_REGISTRY)) {
    reasons.push(`domain_card_metric_unregistered:${card.id}:${card.evaluation_metric}`);
  }
  if (!(card.rollback_condition.metric in EVALUATION_METRIC_REGISTRY)) {
    reasons.push(`domain_card_rollback_metric_unregistered:${card.id}`);
  }
  for (const metricId of card.secondary_metrics) {
    if (!(metricId in EVALUATION_METRIC_REGISTRY)) {
      reasons.push(`domain_card_secondary_metric_unregistered:${card.id}:${metricId}`);
    }
  }
  reasons.push(...validateCardMetricCompatibility(card, EVALUATION_METRIC_REGISTRY));
  reasons.push(...validateCardSourceBinding(card));
  for (const source of card.runtime_input_sources) {
    if (!(source in RUNTIME_SOURCE_REGISTRY)) {
      reasons.push(`domain_card_runtime_source_unregistered:${card.id}:${source}`);
    }
    const policies = card.runtime_input_source_policies[source];
    for (const status of ["missing", "stale", "source_error", "empty_confirmed"] as const) {
      if (!policies?.[status])
        reasons.push(`domain_card_runtime_policy_missing:${card.id}:${source}:${status}`);
    }
  }
  for (const dependency of card.evidence_dependencies) {
    const registryEntry = knobs.evidence_registry[dependency.evidence_key];
    if (!registryEntry) {
      reasons.push(`domain_card_evidence_key_missing:${card.id}:${dependency.evidence_key}`);
    } else if (registryEntry.tool !== dependency.tool) {
      reasons.push(`domain_card_dependency_tool_mismatch:${card.id}:${dependency.tool}`);
    }
    const registeredMetricIds = registeredMetricIdsForTool(dependency.tool);
    for (const metricId of dependency.metric_ids) {
      if (!registeredMetricIds.has(metricId)) {
        reasons.push(`domain_card_dependency_metric_unregistered:${card.id}:${metricId}`);
      }
    }
    const policies = card.evidence_dependency_policies[dependency.dependency_id];
    for (const status of [
      "missing",
      "stale",
      "fallback",
      "tool_failed",
      "partial_loaded",
      "loaded",
    ] as const) {
      if (!policies?.[status])
        reasons.push(
          `domain_card_dependency_policy_missing:${card.id}:${dependency.dependency_id}:${status}`,
        );
    }
    if (dependency.scope_resolution === "in_run_tool_derived") {
      if (!dependency.scope_source_tool) {
        reasons.push(
          `domain_card_scope_source_tool_missing:${card.id}:${dependency.dependency_id}`,
        );
      }
      if (!dependency.scope_source_evidence_key) {
        reasons.push(
          `domain_card_scope_source_evidence_key_missing:${card.id}:${dependency.dependency_id}`,
        );
      } else if (!knobs.evidence_registry[dependency.scope_source_evidence_key]) {
        reasons.push(
          `domain_card_scope_source_evidence_key_unregistered:${card.id}:${dependency.scope_source_evidence_key}`,
        );
      }
      if (dependency.max_scope_count === undefined || dependency.min_scope_count === undefined) {
        reasons.push(`domain_card_scope_count_missing:${card.id}:${dependency.dependency_id}`);
      }
      if (!dependency.empty_scope_behavior) {
        reasons.push(
          `domain_card_empty_scope_behavior_missing:${card.id}:${dependency.dependency_id}`,
        );
      }
    }
  }
  const projected = projectedValueForCard(knobs, card);
  const expected =
    domainRegistry && Object.hasOwn(domainRegistry.values_by_path, card.path)
      ? domainRegistry.values_by_path[card.path]
      : card.default;
  if (!Object.is(projected, expected)) {
    reasons.push(`domain_card_projection_missing:${card.id}`);
  }
  if (card.enforcement === "code" && (!card.runtime_validator || !card.audit_field)) {
    reasons.push(`domain_card_code_enforcement_incomplete:${card.id}`);
  }
  return reasons;
}

function validateCardSourceBinding(card: DomainKnobCard): string[] {
  const reasons: string[] = [];
  if (card.coverage_level === "gap_pending_tool") return reasons;
  if (card.runtime_input_sources.length === 0 && card.evidence_dependencies.length === 0) {
    reasons.push(`domain_card_source_binding_missing:${card.id}`);
  }
  if (
    card.coverage_level === "direct_tool" &&
    !card.evidence_dependencies.some((dependency) => dependency.dependency_type === "direct_tool")
  ) {
    reasons.push(`domain_card_direct_tool_dependency_missing:${card.id}`);
  }
  if (
    card.coverage_level === "derived_proxy" &&
    !card.evidence_dependencies.some((dependency) => dependency.dependency_type === "derived_proxy")
  ) {
    reasons.push(`domain_card_derived_proxy_dependency_missing:${card.id}`);
  }
  if (card.coverage_level === "runtime_state" && card.runtime_input_sources.length === 0) {
    reasons.push(`domain_card_runtime_source_missing:${card.id}`);
  }
  if (
    card.owner_agent === "decision.cio" &&
    card.owner_stage === "cio_proposal" &&
    card.runtime_input_sources.includes("candidate_target_state")
  ) {
    reasons.push(`domain_card_cio_self_loop_source:${card.id}:candidate_target_state`);
  }
  const ownerOrder = RUNTIME_DAG_STAGE_ORDER[card.owner_stage];
  for (const sourceId of card.runtime_input_sources) {
    const source = RUNTIME_SOURCE_REGISTRY[sourceId as keyof typeof RUNTIME_SOURCE_REGISTRY];
    if (!source) continue;
    if (ownerOrder < RUNTIME_DAG_STAGE_ORDER[source.available_from_stage]) {
      reasons.push(
        `domain_card_source_unavailable_at_owner_stage:${card.id}:${sourceId}:${card.owner_stage}`,
      );
    }
  }
  return reasons;
}

function validateRuntimeSourceRegistryEntry(
  sourceId: string,
  source: RuntimeSourceRegistryEntry,
): string[] {
  const reasons: string[] = [];
  if (source.id !== sourceId) {
    reasons.push(`runtime_source_id_mismatch:${sourceId}:${source.id}`);
  }
  if (!source.provenance_adapter) {
    reasons.push(`runtime_source_provenance_adapter_missing:${sourceId}`);
  }
  if (!source.retry_owner) reasons.push(`runtime_source_retry_owner_missing:${sourceId}`);
  if (
    source.producer_mode === "on_demand_pre_stage" &&
    source.producer_stage !== "pre_stage_source_resolution"
  ) {
    reasons.push(`runtime_source_on_demand_producer_stage_invalid:${sourceId}`);
  }
  if (
    RUNTIME_DAG_STAGE_ORDER[source.producer_stage] >
    RUNTIME_DAG_STAGE_ORDER[source.available_from_stage]
  ) {
    reasons.push(`runtime_source_available_before_producer:${sourceId}`);
  }
  if (
    RUNTIME_DAG_STAGE_ORDER[source.finalized_at_stage] <
    RUNTIME_DAG_STAGE_ORDER[source.producer_stage]
  ) {
    reasons.push(`runtime_source_finalized_before_producer:${sourceId}`);
  }
  return reasons;
}

function validateCardMetricCompatibility(
  card: DomainKnobCard,
  registry: Record<string, EvaluationMetricRegistryEntry>,
): string[] {
  const reasons: string[] = [];
  const evaluationMetric = registry[card.evaluation_metric];
  if (evaluationMetric && evaluationMetric.window !== card.horizon) {
    reasons.push(
      `domain_card_metric_window_mismatch:${card.id}:${card.evaluation_metric}:${evaluationMetric.window}:expected:${card.horizon}`,
    );
  }
  const rollbackMetric = registry[card.rollback_condition.metric];
  if (rollbackMetric) {
    if (rollbackMetric.window !== card.horizon) {
      reasons.push(
        `domain_card_rollback_metric_window_mismatch:${card.id}:${card.rollback_condition.metric}:${rollbackMetric.window}:expected:${card.horizon}`,
      );
    }
    if (rollbackMetric.unit !== card.rollback_condition.unit) {
      reasons.push(
        `domain_card_rollback_metric_unit_mismatch:${card.id}:${card.rollback_condition.metric}:${rollbackMetric.unit}:expected:${card.rollback_condition.unit}`,
      );
    }
  }
  for (const metricId of card.secondary_metrics) {
    const secondaryMetric = registry[metricId];
    if (secondaryMetric && secondaryMetric.window !== card.horizon) {
      reasons.push(
        `domain_card_secondary_metric_window_mismatch:${card.id}:${metricId}:${secondaryMetric.window}:expected:${card.horizon}`,
      );
    }
  }
  return reasons;
}

function validateEvaluationMetricEntry(
  metricId: string,
  metricEntry: EvaluationMetricRegistryEntry,
): string[] {
  const reasons: string[] = [];
  if (metricEntry.id !== metricId) {
    reasons.push(`domain_catalog_metric_id_mismatch:${metricId}:${metricEntry.id}`);
  }
  if (!metricEntry.value_convention) {
    reasons.push(`domain_catalog_metric_value_convention_missing:${metricId}`);
  }
  if (!metricEntry.direction) {
    reasons.push(`domain_catalog_metric_direction_missing:${metricId}`);
  }
  if (!metricEntry.baseline) {
    reasons.push(`domain_catalog_metric_baseline_missing:${metricId}`);
  }
  if (!metricEntry.aggregation) {
    reasons.push(`domain_catalog_metric_aggregation_missing:${metricId}`);
  }
  if (!metricEntry.window) {
    reasons.push(`domain_catalog_metric_window_missing:${metricId}`);
  }
  const calculator = EVALUATION_CALCULATOR_REGISTRY[metricEntry.calculator_id];
  if (!calculator) {
    reasons.push(`domain_catalog_metric_calculator_unregistered:${metricId}`);
  } else {
    if (metricEntry.calculator_version !== calculator.version) {
      reasons.push(`domain_catalog_metric_calculator_version_mismatch:${metricId}`);
    }
    if (!calculator.supported_value_conventions.includes(metricEntry.value_convention)) {
      reasons.push(`domain_catalog_metric_calculator_convention_mismatch:${metricId}`);
    }
  }
  const validRange = metricEntry.valid_range;
  if (!validRange || typeof validRange !== "object") {
    reasons.push(`domain_catalog_metric_valid_range_missing:${metricId}`);
  } else {
    const { minimum, maximum } = validRange;
    if (minimum !== null && maximum !== null && minimum > maximum) {
      reasons.push(`domain_catalog_metric_valid_range_invalid:${metricId}`);
    }
    if (metricEntry.value_convention === "rate_0_1" && (minimum !== 0 || maximum !== 1)) {
      reasons.push(`domain_catalog_metric_rate_range_invalid:${metricId}`);
    }
  }
  if (metricEntry.null_policy !== "exclude_sample") {
    reasons.push(`domain_catalog_metric_null_policy_invalid:${metricId}`);
  }
  if (metricEntry.non_finite_policy !== "reject_evaluation") {
    reasons.push(`domain_catalog_metric_non_finite_policy_invalid:${metricId}`);
  }
  if (!metricEntry.normalization_version) {
    reasons.push(`domain_catalog_metric_normalization_version_missing:${metricId}`);
  }
  if (!metricEntry.uncertainty_method) {
    reasons.push(`domain_catalog_metric_uncertainty_method_missing:${metricId}`);
  }
  if (!metricEntry.overlapping_sample_policy) {
    reasons.push(`domain_catalog_metric_overlap_policy_missing:${metricId}`);
  }
  if (!Number.isInteger(metricEntry.min_sample_size) || metricEntry.min_sample_size < 1) {
    reasons.push(`domain_catalog_metric_min_sample_size_invalid:${metricId}`);
  }
  if (metricEntry.pit_required !== true) {
    reasons.push(`domain_catalog_metric_pit_not_required:${metricId}`);
  }
  const exclusionRules = Array.isArray(metricEntry.exclusion_rules)
    ? metricEntry.exclusion_rules
    : [];
  if (exclusionRules.length === 0) {
    reasons.push(`domain_catalog_metric_exclusion_rules_missing:${metricId}`);
  }
  for (const exclusionRule of REQUIRED_EVALUATION_METRIC_EXCLUSION_RULES) {
    if (!exclusionRules.includes(exclusionRule)) {
      reasons.push(`domain_catalog_metric_exclusion_rule_missing:${metricId}:${exclusionRule}`);
    }
  }
  const directionConventionMismatch =
    (metricEntry.direction === "lower_is_better" &&
      metricEntry.value_convention === "signed_return") ||
    (metricEntry.direction === "higher_is_better" &&
      (metricEntry.value_convention === "nonnegative_loss_magnitude" ||
        metricEntry.value_convention === "bps_cost"));
  if (directionConventionMismatch) {
    reasons.push(`domain_catalog_metric_value_convention_incompatible:${metricId}`);
  }
  return reasons;
}

function validateEvaluationCalculatorEntry(
  calculatorId: string,
  calculator: EvaluationCalculatorRegistryEntry,
): string[] {
  const reasons: string[] = [];
  if (calculator.id !== calculatorId) {
    reasons.push(`domain_catalog_calculator_id_mismatch:${calculatorId}:${calculator.id}`);
  }
  if (!calculator.version)
    reasons.push(`domain_catalog_calculator_version_missing:${calculatorId}`);
  if (!calculator.implementation_ref.startsWith("mosaic.autoresearch.domain_metrics:")) {
    reasons.push(`domain_catalog_calculator_implementation_invalid:${calculatorId}`);
  }
  if (calculator.deterministic !== true) {
    reasons.push(`domain_catalog_calculator_not_deterministic:${calculatorId}`);
  }
  if (calculator.pit_enforced !== true) {
    reasons.push(`domain_catalog_calculator_pit_not_enforced:${calculatorId}`);
  }
  if (calculator.supported_value_conventions.length === 0) {
    reasons.push(`domain_catalog_calculator_conventions_missing:${calculatorId}`);
  }
  return reasons;
}

export function validateCrossFieldInvariants(
  spec: RuntimeAgentSpec,
  knobs: Pick<ResearchKnobs, "lookbacks" | "thresholds">,
): string[] {
  if (spec.agent !== "cio") return [];
  const reasons: string[] = [];
  const value = (id: string): number | null => {
    const raw = knobs.thresholds[id] ?? knobs.lookbacks[id];
    return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
  };
  const minAdd = value("min_confidence_to_add");
  const minHold = value("min_confidence_to_hold");
  if (minAdd !== null && minHold !== null && minHold > minAdd) {
    reasons.push("domain_cross_field_violation:cio_min_hold_gt_add");
  }
  const targetMin = value("target_count_min");
  const targetMax = value("target_count_max");
  if (targetMin !== null && targetMax !== null && targetMin > targetMax) {
    reasons.push("domain_cross_field_violation:cio_target_count_min_gt_max");
  }
  const exit = value("exit_threshold");
  const trim = value("trim_threshold");
  const hold = value("hold_hurdle");
  const add = value("new_buy_hurdle");
  if (
    exit !== null &&
    trim !== null &&
    hold !== null &&
    add !== null &&
    !(exit <= trim && trim <= hold && hold <= add)
  ) {
    reasons.push("domain_cross_field_violation:cio_exit_trim_hold_add_order");
  }
  const maxNew = value("max_new_buy_weight");
  const maxTarget = value("max_target_position_weight");
  if (maxNew !== null && maxTarget !== null && maxNew > maxTarget) {
    reasons.push("domain_cross_field_violation:cio_max_new_gt_max_target");
  }
  return reasons;
}

export function validateWeightGroupInvariants(
  spec: RuntimeAgentSpec,
  knobs: Pick<
    ResearchKnobs,
    "evidence_weights" | "lookbacks" | "thresholds" | "confidence_caps" | "tie_breaks"
  >,
): string[] {
  const reasons: string[] = [];
  const groups = new Map<string, DomainKnobCard[]>();
  for (const card of domainKnobCardsForSpec(spec)) {
    if (!card.weight_group || card.normalization !== "sum_to_one") continue;
    const members = groups.get(card.weight_group) ?? [];
    members.push(card);
    groups.set(card.weight_group, members);
  }
  for (const [group, cards] of groups) {
    const values = cards.map((card) => {
      const raw = projectedValueForCard(knobs, card);
      return typeof raw === "number" && Number.isFinite(raw) ? raw : NaN;
    });
    if (values.some((item) => !Number.isFinite(item) || item < 0)) {
      reasons.push(`domain_weight_group_invalid_value:${group}`);
      continue;
    }
    const total = values.reduce((sum, item) => sum + item, 0);
    if (Math.abs(total - 1) > 1e-9) {
      reasons.push(`domain_weight_group_not_sum_to_one:${group}:${total.toFixed(6)}`);
    }
  }
  return reasons;
}

function projectedValueForCard(
  knobs: Pick<
    ResearchKnobs,
    "evidence_weights" | "lookbacks" | "thresholds" | "confidence_caps" | "tie_breaks"
  >,
  card: Pick<DomainKnobCard, "id" | "projection_bucket" | "default">,
): unknown {
  if (card.projection_bucket === "lookbacks") return knobs.lookbacks[card.id];
  if (card.projection_bucket === "thresholds") return knobs.thresholds[card.id];
  if (card.projection_bucket === "evidence_weights") return knobs.evidence_weights[card.id];
  if (card.projection_bucket === "confidence_caps") return knobs.confidence_caps[card.id]?.cap;
  const value = typeof card.default === "string" ? card.default : card.id;
  return knobs.tie_breaks.includes(value) ? value : undefined;
}

function buildCard(spec: RuntimeAgentSpec, seed: DomainSeed): DomainKnobCard {
  const id = seed.id;
  const bucket = seed.bucket ?? bucketForId(id);
  const type = seed.type ?? typeForId(id);
  const range = valueRangeForId(id, type, seed);
  const tool = toolForSeed(spec, id);
  const coverageLevel = spec.layer === "decision" ? "runtime_state" : coverageLevelForId(id);
  const runtimeSources =
    coverageLevel === "runtime_state" ? runtimeSourcesForCard(spec.agent, id) : [];
  const evidenceDependencies =
    coverageLevel === "direct_tool" || coverageLevel === "derived_proxy"
      ? [evidenceDependency(spec, id, tool, coverageLevel)]
      : [];
  const metricId = seed.metric ?? METRIC_BY_ID[id] ?? metricForSpec(spec);
  const enforcement = enforcementForId(id);
  const runtimeValidator = runtimeValidatorForId(id);
  const auditField = auditFieldForId(id);
  const weightGroup = weightGroupForId(spec.agent, id);
  const ownerStage = ownerStageForCard(spec, id);
  const consumerStages = consumerStagesForCard(ownerStage, enforcement);
  return {
    id,
    owner_agent: spec.promptIrAgentId,
    consumer_agents: [spec.promptIrAgentId],
    owner_stage: ownerStage,
    consumer_stages: consumerStages,
    projection_bucket: bucket,
    path: `/rule_packs/${spec.layer}.${spec.agent}.runtime.v1/rules/${canonicalRuleId(spec)}/learnable_parameters/${id}/value`,
    type,
    default: range.default,
    min: range.min,
    max: range.max,
    step: range.step,
    coverage_level: coverageLevel,
    activation_state: seed.activation_state ?? "active",
    runtime_input_sources: runtimeSources,
    runtime_input_source_policies: Object.fromEntries(
      runtimeSources.map((source) => [source, runtimeSourcePolicyForCard(id, source)]),
    ),
    evidence_dependencies: evidenceDependencies,
    evidence_dependency_policies: Object.fromEntries(
      evidenceDependencies.map((dependency) => [
        dependency.dependency_id,
        defaultEvidenceDependencyPolicy(),
      ]),
    ),
    learning_objective:
      LEARNING_OBJECTIVE_BY_ID[id] ??
      `calibrate ${id.replaceAll("_", " ")} for ${spec.promptIrAgentId} prediction quality`,
    prediction_target:
      PREDICTION_TARGET_BY_ID[id] ??
      `${spec.promptIrAgentId}.${id}.${seed.horizon ?? horizonForSpec(spec)}`,
    evaluation_metric: metricId,
    secondary_metrics: secondaryMetricsForCard(
      spec,
      metricId,
      seed.horizon ?? horizonForSpec(spec),
    ),
    horizon: seed.horizon ?? horizonForSpec(spec),
    rollback_condition: {
      metric: metricId,
      worse_by: EVALUATION_METRIC_REGISTRY[metricId]?.unit === "bps" ? 5 : 0.02,
      unit: EVALUATION_METRIC_REGISTRY[metricId]?.unit ?? "ratio",
    },
    enforcement,
    ...(runtimeValidator ? { runtime_validator: runtimeValidator } : {}),
    ...(auditField ? { audit_field: auditField } : {}),
    category: "domain",
    cross_field_group: crossFieldGroupForId(spec.agent, id),
    weight_group: weightGroup,
    atomic_mutation_group: weightGroup
      ? `weight_group:${spec.promptIrAgentId}:${weightGroup}`
      : null,
    normalization: weightGroup ? "sum_to_one" : "none",
  };
}

function ownerStageForCard(spec: RuntimeAgentSpec, id: string): RuntimeAgentStageId {
  if (spec.layer !== "decision") return "agent_run";
  if (spec.agent === "alpha_discovery") return "alpha_discovery";
  if (spec.agent === "cro") return "cro_review";
  if (spec.agent === "autonomous_execution") return "execution_feasibility";
  if (spec.agent === "cio") return id.startsWith("mirofish_") ? "cio_final" : "cio_proposal";
  throw new Error(`unsupported decision card owner stage: ${spec.agent}:${id}`);
}

function consumerStagesForCard(
  ownerStage: RuntimeAgentStageId,
  enforcement: DomainKnobCard["enforcement"],
): RuntimeDagStageId[] {
  return enforcement === "code" ? [ownerStage, "shared_validation"] : [ownerStage];
}

function seeds(ids: string[]): DomainSeed[] {
  return ids.map((id) => ({ id }));
}

function readOnlySeeds(ids: string[]): DomainSeed[] {
  return ids.map((id) => ({ id, activation_state: "read_only" }));
}

function runtimeSource(
  id: string,
  opts: {
    scope: Record<string, "required" | "optional">;
    schema: string;
    empty?: boolean;
    producerMode: RuntimeSourceRegistryEntry["producer_mode"];
    producerStage: RuntimeDagStageId;
    availableFromStage: RuntimeDagStageId;
    finalizedAtStage: RuntimeDagStageId;
    refreshPolicy: RuntimeSourceRegistryEntry["refresh_policy"];
    provenanceAdapter: string;
    retryOwner: string;
    crossCycleReuse: RuntimeSourceRegistryEntry["cross_cycle_reuse"];
  },
): RuntimeSourceRegistryEntry {
  return {
    id,
    scope_schema: opts.scope,
    schema_ref: opts.schema,
    producer_mode: opts.producerMode,
    producer_stage: opts.producerStage,
    available_from_stage: opts.availableFromStage,
    finalized_at_stage: opts.finalizedAtStage,
    refresh_policy: opts.refreshPolicy,
    provenance_adapter: opts.provenanceAdapter,
    retry_owner: opts.retryOwner,
    cross_cycle_reuse: opts.crossCycleReuse,
    max_age: "same_run_or_current_day",
    trading_calendar: "cn_a_share",
    pit_required: true,
    empty_allowed: opts.empty ?? false,
    empty_status: opts.empty ? "empty_confirmed" : "invalid",
    empty_behavior: opts.empty ? "disable_dependent_cards" : "invalid",
    stale_policy: "disable_card_and_cap_if_required",
    source_error_policy: "disable_card_and_cap_if_required",
  };
}

function calculator(
  id: string,
  implementation: string,
  supportedValueConventions: EvaluationMetricRegistryEntry["value_convention"][],
): EvaluationCalculatorRegistryEntry {
  return {
    id,
    version: "1",
    implementation_language: "python",
    implementation_ref: `mosaic.autoresearch.domain_metrics:${implementation}`,
    input_schema_ref: "autoresearch.domain_metric_sample.v1",
    output_schema_ref: "autoresearch.domain_metric_result.v1",
    deterministic: true,
    pit_enforced: true,
    supported_value_conventions: supportedValueConventions,
  };
}

function metricEntry(opts: {
  id: string;
  unit: EvaluationMetricRegistryEntry["unit"];
  valueConvention: EvaluationMetricRegistryEntry["value_convention"];
  direction: EvaluationMetricRegistryEntry["direction"];
  aggregation: EvaluationMetricRegistryEntry["aggregation"];
  window: string;
  calculatorId: string;
  validRange: EvaluationMetricRegistryEntry["valid_range"];
  uncertaintyMethod: EvaluationMetricRegistryEntry["uncertainty_method"];
  overlappingSamplePolicy: EvaluationMetricRegistryEntry["overlapping_sample_policy"];
}): EvaluationMetricRegistryEntry {
  return {
    id: opts.id,
    unit: opts.unit,
    value_convention: opts.valueConvention,
    direction: opts.direction,
    aggregation: opts.aggregation,
    window: opts.window,
    baseline: "previous_knob_snapshot",
    calculator_id: opts.calculatorId,
    calculator_version: EVALUATION_CALCULATOR_REGISTRY[opts.calculatorId]?.version ?? "missing",
    valid_range: opts.validRange,
    null_policy: "exclude_sample",
    non_finite_policy: "reject_evaluation",
    normalization_version: "1",
    uncertainty_method: opts.uncertaintyMethod,
    overlapping_sample_policy: opts.overlappingSamplePolicy,
    min_sample_size: 30,
    pit_required: true,
    exclusion_rules: [
      ...REQUIRED_EVALUATION_METRIC_EXCLUSION_RULES,
      "missing_required_evidence_dependency",
      "fallback_dependency_without_policy_allowance",
    ],
  };
}

function signedReturnMetric(id: string, window: string): EvaluationMetricRegistryEntry {
  return metricEntry({
    id,
    unit: "ratio",
    valueConvention: "signed_return",
    direction: "higher_is_better",
    aggregation: "mean",
    window,
    calculatorId: "pit.signed_return",
    validRange: { minimum: -1, maximum: null },
    uncertaintyMethod: "paired_block_bootstrap",
    overlappingSamplePolicy: "inverse_overlap_weight",
  });
}

function lossMetric(
  id: string,
  window: string,
  aggregation: "mean" | "max",
): EvaluationMetricRegistryEntry {
  return metricEntry({
    id,
    unit: "ratio",
    valueConvention: "nonnegative_loss_magnitude",
    direction: "lower_is_better",
    aggregation,
    window,
    calculatorId: "pit.nonnegative_loss",
    validRange: { minimum: 0, maximum: null },
    uncertaintyMethod: "paired_block_bootstrap",
    overlappingSamplePolicy: "inverse_overlap_weight",
  });
}

function bpsCostMetric(id: string, window: string): EvaluationMetricRegistryEntry {
  return metricEntry({
    id,
    unit: "bps",
    valueConvention: "bps_cost",
    direction: "lower_is_better",
    aggregation: "mean",
    window,
    calculatorId: "pit.bps_cost",
    validRange: { minimum: 0, maximum: null },
    uncertaintyMethod: "paired_block_bootstrap",
    overlappingSamplePolicy: "inverse_overlap_weight",
  });
}

function rateMetric(
  id: string,
  direction: EvaluationMetricRegistryEntry["direction"],
  window: string,
): EvaluationMetricRegistryEntry {
  return metricEntry({
    id,
    unit: "ratio",
    valueConvention: "rate_0_1",
    direction,
    aggregation: "hit_rate",
    window,
    calculatorId: "pit.rate",
    validRange: { minimum: 0, maximum: 1 },
    uncertaintyMethod: "wilson_interval",
    overlappingSamplePolicy: "inverse_overlap_weight",
  });
}

function rankCorrelationMetric(id: string, window: string): EvaluationMetricRegistryEntry {
  return metricEntry({
    id,
    unit: "ratio",
    valueConvention: "score",
    direction: "higher_is_better",
    aggregation: "rank_correlation",
    window,
    calculatorId: "pit.rank_correlation",
    validRange: { minimum: -1, maximum: 1 },
    uncertaintyMethod: "fisher_z",
    overlappingSamplePolicy: "inverse_overlap_weight",
  });
}

function calibrationErrorMetric(id: string, window: string): EvaluationMetricRegistryEntry {
  return metricEntry({
    id,
    unit: "ratio",
    valueConvention: "rate_0_1",
    direction: "lower_is_better",
    aggregation: "calibration_error",
    window,
    calculatorId: "pit.calibration_error",
    validRange: { minimum: 0, maximum: 1 },
    uncertaintyMethod: "block_bootstrap",
    overlappingSamplePolicy: "inverse_overlap_weight",
  });
}

function bucketForId(id: string): ProjectionBucket {
  return LOOKBACK_DOMAIN_KNOB_IDS.has(id) ? "lookbacks" : "thresholds";
}

function typeForId(id: string): KnobValueType {
  if (id === "max_verified_constituents") return "integer";
  return bucketForId(id) === "lookbacks" || id.includes("_count") ? "integer" : "number";
}

function valueRangeForId(
  id: string,
  type: KnobValueType,
  seed: DomainSeed,
): { default: number; min: number; max: number; step: number } {
  const custom = CUSTOM_RANGES_BY_ID[id];
  if (custom) return custom;
  if (seed.default !== undefined && seed.min !== undefined && seed.max !== undefined) {
    return {
      default: seed.default,
      min: seed.min,
      max: seed.max,
      step: seed.step ?? (type === "integer" ? 1 : 0.05),
    };
  }
  if (type === "integer") {
    if (id.includes("count")) return { default: 5, min: 1, max: 20, step: 1 };
    return { default: 20, min: 1, max: 120, step: 1 };
  }
  if (id.includes("pct") || id.includes("drawdown") || id.includes("loss")) {
    return { default: -0.08, min: -0.3, max: -0.01, step: 0.01 };
  }
  if (id.includes("cap") || id.includes("discount") || id.includes("penalty")) {
    return { default: 0.25, min: 0, max: 0.75, step: 0.05 };
  }
  if (id.includes("bps")) {
    return { default: 25, min: -200, max: 200, step: 5 };
  }
  if (id.includes("threshold") || id.includes("floor") || id.includes("min")) {
    return { default: 0.6, min: 0, max: 1, step: 0.05 };
  }
  return { default: 0.2, min: 0, max: 1, step: 0.05 };
}

function toolForSeed(spec: RuntimeAgentSpec, id: string): string {
  const tools = spec.requiredTools.filter((tool) => tool !== "get_rke_research_context");
  const preferred = [
    ["inventory", "get_balance_sheet"],
    ["gross_margin", "get_income_statement"],
    ["capex", "get_cashflow"],
    ["financial_statement", "get_income_statement"],
    ["verified_constituents", "get_stock_data"],
    ["policy", "get_industry_policy_digest"],
    ["moneyflow", "get_industry_moneyflow"],
    ["flow", "get_northbound_flow"],
    ["research", "get_broker_research"],
    ["etf", "get_etf_holdings"],
    ["valuation", "get_indicators"],
    ["technical", "get_indicators"],
    ["price", "get_stock_data"],
    ["stock", "get_stock_data"],
    ["fundamental", "get_fundamentals"],
    ["curve", "get_yield_curve_cn"],
    ["dxy", "get_fx_rates"],
    ["commodity", "get_commodity_prices"],
    ["vol", "get_volatility_indices"],
  ] as const;
  for (const [token, tool] of preferred) {
    if (id.includes(token) && tools.includes(tool)) return tool;
  }
  return tools[0] ?? "get_rke_research_context";
}

function coverageLevelForId(
  id: string,
): Exclude<CoverageLevel, "runtime_state" | "gap_pending_tool"> {
  return id.includes("policy") ||
    id.includes("research") ||
    id.includes("proxy") ||
    id.includes("export_control") ||
    id.includes("ai_compute") ||
    id.includes("valuation") ||
    id.includes("conviction")
    ? "derived_proxy"
    : "direct_tool";
}

function evidenceDependency(
  spec: RuntimeAgentSpec,
  id: string,
  tool: string,
  coverageLevel: Exclude<CoverageLevel, "runtime_state" | "gap_pending_tool">,
): EvidenceDependency {
  const evidenceKey = evidenceKeyForTool(tool);
  if (id === "max_verified_constituents") {
    return {
      dependency_id: `${spec.promptIrAgentId}.${id}.candidate_validation`,
      evidence_key: evidenceKey,
      tool,
      metric_ids: ["close", "volume"],
      freshness: "current_window",
      required_for_prediction: true,
      dependency_type: coverageLevel,
      scope_resolution: "in_run_tool_derived",
      scope_source_tool: "get_etf_holdings",
      scope_source_evidence_key: "etf_holdings",
      scope_schema: { ticker: "required" },
      max_scope_count: 6,
      min_scope_count: 1,
      min_scope_coverage: 0.8,
      empty_scope_behavior: "exclude_sample",
    };
  }
  return {
    dependency_id: `${spec.promptIrAgentId}.${id}.primary`,
    evidence_key: evidenceKey,
    tool,
    metric_ids: metricIdsForSeed(id, tool, evidenceKey),
    freshness: "current_window",
    required_for_prediction: true,
    dependency_type: coverageLevel,
    scope_resolution: "pre_run",
    scope_schema: { cohort: "required" },
    min_scope_coverage: 1,
  };
}

function metricIdsForSeed(id: string, tool: string, evidenceKey: string): string[] {
  if (tool === "get_balance_sheet" && id.includes("inventory")) {
    return ["inventory_to_revenue", "inventory_turnover_days"];
  }
  if (tool === "get_income_statement" && id.includes("gross_margin")) {
    return ["gross_margin_change"];
  }
  if (tool === "get_cashflow" && id.includes("capex")) {
    return ["capex_to_revenue", "construction_in_progress_change", "operating_cashflow_margin"];
  }
  return [`${evidenceKey}_current`];
}

function runtimeSourcesForCard(agent: string, id: string): string[] {
  if (id.startsWith("mirofish_")) {
    if (agent === "cro") {
      return [
        "current_position_snapshot",
        "current_market_data",
        "candidate_target_state",
        "mirofish_context",
      ];
    }
    if (agent === "autonomous_execution") {
      return [
        "current_position_snapshot",
        "current_market_data",
        "candidate_target_state",
        "cro_review_state",
        "execution_liquidity_state",
        "mirofish_context",
      ];
    }
    if (agent === "cio") {
      return [
        "current_position_snapshot",
        "current_market_data",
        "candidate_target_state",
        "cro_review_state",
        "execution_feasibility_state",
        "mirofish_context",
      ];
    }
  }
  if (agent === "cio") {
    if (id === "stale_thesis_days") {
      return ["current_position_snapshot", "position_thesis_state"];
    }
    if (id === "rebalance_drift_pct") {
      return ["current_position_snapshot", "previous_target_state", "upstream_agent_outputs"];
    }
    if (id === "min_confidence_to_add") {
      return ["upstream_agent_outputs", "current_position_snapshot"];
    }
    if (id === "min_confidence_to_hold") {
      return ["current_position_snapshot", "position_thesis_state"];
    }
  }
  if (agent === "cro") {
    if (id === "stop_loss_pct" || id === "take_profit_review_pct") {
      return ["current_position_snapshot", "current_market_data"];
    }
    if (id === "max_single_name_weight") {
      return ["candidate_target_state", "current_position_snapshot"];
    }
    if (id === "max_sector_weight") {
      return ["candidate_target_state", "portfolio_exposure_state"];
    }
  }
  if (agent === "autonomous_execution") {
    if (id === "min_delta_trade_weight") {
      return ["current_position_snapshot", "candidate_target_state", "current_market_data"];
    }
    if (id === "slippage_cap" || id === "liquidity_floor") {
      return ["current_market_data", "execution_liquidity_state"];
    }
    if (id === "max_order_split_count") {
      return ["candidate_target_state", "execution_liquidity_state"];
    }
  }
  if (agent === "cro") {
    return [
      "current_position_snapshot",
      "current_market_data",
      "candidate_target_state",
      "portfolio_exposure_state",
    ];
  }
  if (agent === "autonomous_execution") {
    return [
      "current_position_snapshot",
      "current_market_data",
      "candidate_target_state",
      "execution_liquidity_state",
    ];
  }
  if (agent === "cio") {
    return ["current_position_snapshot", "previous_target_state", "upstream_agent_outputs"];
  }
  if (agent === "alpha_discovery") {
    return ["upstream_agent_outputs", "current_position_snapshot", "current_market_data"];
  }
  return ["upstream_agent_outputs"];
}

function enforcementForId(id: string): DomainKnobCard["enforcement"] {
  return [
    "stop_loss_pct",
    "max_single_name_weight",
    "max_sector_weight",
    "min_delta_trade_weight",
    "slippage_cap",
    "liquidity_floor",
  ].includes(id)
    ? "code"
    : "advisory";
}

function runtimeValidatorForId(id: string): string | undefined {
  if (["stop_loss_pct", "max_single_name_weight", "max_sector_weight"].includes(id)) {
    return "portfolioRiskActionValidator";
  }
  if (["min_delta_trade_weight", "slippage_cap", "liquidity_floor"].includes(id)) {
    return "executionActionValidator";
  }
  return undefined;
}

function auditFieldForId(id: string): string | undefined {
  if (["stop_loss_pct", "max_single_name_weight", "max_sector_weight"].includes(id)) {
    return `risk_limit_enforcement.${id}`;
  }
  if (["min_delta_trade_weight", "slippage_cap", "liquidity_floor"].includes(id)) {
    return `execution_enforcement.${id}`;
  }
  return undefined;
}

function defaultRuntimeSourcePolicy(source: string): Record<RuntimeSourceStatus, string> {
  return {
    missing: "disable_card_and_cap_if_required",
    stale: "disable_card_and_cap_if_required",
    source_error: "disable_card_and_cap_if_required",
    empty_confirmed: source === "current_position_snapshot" ? "disable_card" : "invalid",
  };
}

function runtimeSourcePolicyForCard(
  cardId: string,
  source: string,
): Record<RuntimeSourceStatus, string> {
  const policy = defaultRuntimeSourcePolicy(source);
  if (
    source === "current_position_snapshot" &&
    ["min_confidence_to_add", "new_buy_hurdle", "target_count_min", "target_count_max"].includes(
      cardId,
    )
  ) {
    return { ...policy, empty_confirmed: "allow" };
  }
  if (source === "previous_target_state" && cardId === "rebalance_drift_pct") {
    return { ...policy, empty_confirmed: "disable_card" };
  }
  return policy;
}

function weightGroupForId(agent: string, id: string): string | null {
  if (
    agent === "semiconductor" &&
    [
      "design_weight",
      "equipment_weight",
      "foundry_weight",
      "packaging_weight",
      "materials_weight",
      "ai_compute_weight",
    ].includes(id)
  ) {
    return "subindustry_weights";
  }
  if (
    agent === "cio" &&
    [
      "macro_signal_weight",
      "sector_signal_weight",
      "superinvestor_signal_weight",
      "cro_risk_weight",
    ].includes(id)
  ) {
    return "upstream_signal_weights";
  }
  return null;
}

function crossFieldGroupForId(agent: string, id: string): string | null {
  if (agent === "cio" && ["min_confidence_to_add", "min_confidence_to_hold"].includes(id)) {
    return "cio_confidence_hurdles";
  }
  if (
    agent === "cio" &&
    [
      "target_count_min",
      "target_count_max",
      "exit_threshold",
      "trim_threshold",
      "hold_hurdle",
      "new_buy_hurdle",
      "max_new_buy_weight",
      "max_target_position_weight",
    ].includes(id)
  ) {
    return "cio_portfolio_construction";
  }
  return null;
}

function defaultEvidenceDependencyPolicy(): Record<EvidenceDependencyStatus, string> {
  return {
    missing: "exclude_sample_and_cap_if_required",
    stale: "exclude_sample_and_cap_if_required",
    fallback: "exclude_sample_and_cap_if_required",
    tool_failed: "exclude_sample_and_cap_if_required",
    partial_loaded: "exclude_sample_only",
    loaded: "allow",
  };
}

function metricForSpec(spec: RuntimeAgentSpec): string {
  if (spec.layer === "macro") return "macro_signal_accuracy_5d";
  if (spec.layer === "sector") return "sector_rank_correlation_20d";
  if (spec.layer === "superinvestor") return "style_pick_alpha_60d";
  if (spec.agent === "cro") return "portfolio_risk_quality_20d";
  if (spec.agent === "autonomous_execution") return "execution_quality_5d";
  if (spec.agent === "alpha_discovery") return "alpha_discovery_quality_20d";
  return "portfolio_construction_quality_20d";
}

function secondaryMetricsForCard(
  spec: RuntimeAgentSpec,
  primaryMetricId: string,
  horizon: string,
): string[] {
  const candidates = [
    primaryMetricId,
    metricForSpec(spec),
    horizon === "5d" ? "confidence_calibration_error" : null,
    horizon === "5d" ? "fallback_rate" : null,
    horizon === "5d" ? "missing_rate" : null,
    horizon === "20d" ? "max_drawdown_after_hold" : null,
    horizon === "20d" ? "portfolio_risk_quality_20d" : null,
    horizon === "60d" ? "style_pick_alpha_60d" : null,
  ];
  const seen = new Set<string>([primaryMetricId]);
  const result: string[] = [];
  for (const metricId of candidates) {
    if (!metricId || seen.has(metricId)) continue;
    const metricEntry = EVALUATION_METRIC_REGISTRY[metricId];
    if (metricEntry?.window !== horizon) continue;
    seen.add(metricId);
    result.push(metricId);
    if (result.length >= 2) break;
  }
  return result;
}

function horizonForSpec(spec: RuntimeAgentSpec): string {
  if (spec.layer === "macro") return "5d";
  if (spec.layer === "superinvestor") return "60d";
  if (spec.agent === "autonomous_execution") return "5d";
  return "20d";
}

function canonicalRuleId(spec: RuntimeAgentSpec): string {
  const kind = spec.layer === "decision" ? (spec.agent === "cro" ? "risk" : "policy") : "soft";
  return `${spec.layer}.${spec.agent}.${kind}.001`;
}

function evidenceKeyForTool(tool: string): string {
  return tool
    .replace(/^get_/, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/_+$/g, "");
}

function canonicalDomainKnobCatalogArtifact(
  artifact: DomainKnobCatalogArtifact,
): DomainKnobCatalogArtifact {
  return {
    schema_version: artifact.schema_version,
    catalog_version: artifact.catalog_version,
    runtime_agent_count: artifact.runtime_agent_count,
    runtime_sources: sortObjectRecord(artifact.runtime_sources),
    evaluation_metrics: sortObjectRecord(artifact.evaluation_metrics),
    evaluation_calculators: sortObjectRecord(artifact.evaluation_calculators),
    agents: artifact.agents.map((agent) => ({
      layer: agent.layer,
      agent: agent.agent,
      prompt_ir_agent: agent.prompt_ir_agent,
      min_mutable_domain_knobs: agent.min_mutable_domain_knobs,
      card_count: agent.card_count,
      cards: sortDomainKnobCards(agent.cards),
    })),
  };
}

function canonicalDomainCard(card: DomainKnobCard): DomainKnobCard {
  return {
    id: card.id,
    owner_agent: card.owner_agent,
    consumer_agents: [...card.consumer_agents].sort(),
    owner_stage: card.owner_stage,
    consumer_stages: [...card.consumer_stages].sort(
      (left, right) => RUNTIME_DAG_STAGE_ORDER[left] - RUNTIME_DAG_STAGE_ORDER[right],
    ),
    projection_bucket: card.projection_bucket,
    path: card.path,
    type: card.type,
    default: card.default,
    ...(card.min !== undefined ? { min: card.min } : {}),
    ...(card.max !== undefined ? { max: card.max } : {}),
    ...(card.step !== undefined ? { step: card.step } : {}),
    ...(card.allowed_values !== undefined ? { allowed_values: card.allowed_values } : {}),
    coverage_level: card.coverage_level,
    activation_state: card.activation_state,
    runtime_input_sources: [...card.runtime_input_sources].sort(),
    runtime_input_source_policies: sortObjectRecord(card.runtime_input_source_policies),
    evidence_dependencies: [...card.evidence_dependencies].sort((left, right) =>
      left.dependency_id.localeCompare(right.dependency_id),
    ),
    evidence_dependency_policies: sortObjectRecord(card.evidence_dependency_policies),
    learning_objective: card.learning_objective,
    prediction_target: card.prediction_target,
    evaluation_metric: card.evaluation_metric,
    secondary_metrics: [...card.secondary_metrics].sort(),
    horizon: card.horizon,
    rollback_condition: card.rollback_condition,
    enforcement: card.enforcement,
    ...(card.runtime_validator ? { runtime_validator: card.runtime_validator } : {}),
    ...(card.audit_field ? { audit_field: card.audit_field } : {}),
    category: card.category,
    cross_field_group: card.cross_field_group,
    weight_group: card.weight_group,
    atomic_mutation_group: card.atomic_mutation_group,
    normalization: card.normalization,
  };
}

function sortDomainKnobCards(cards: ReadonlyArray<DomainKnobCard>): DomainKnobCard[] {
  return [...cards]
    .sort((left, right) => left.path.localeCompare(right.path))
    .map((card) => canonicalDomainCard(card));
}

function sortObjectRecord<T>(record: Record<string, T>): Record<string, T> {
  return Object.fromEntries(
    Object.entries(record).sort(([left], [right]) => left.localeCompare(right)),
  );
}

function sha256Json(value: unknown): string {
  return `sha256:${createHash("sha256").update(JSON.stringify(value)).digest("hex")}`;
}

function domainKnobEvaluationContractSchemaHash(): string {
  const schema = readFileSync(
    new URL("../../../../schemas/domain_knob_evaluation_contract_v1.schema.json", import.meta.url),
  );
  return `sha256:${createHash("sha256").update(schema).digest("hex")}`;
}

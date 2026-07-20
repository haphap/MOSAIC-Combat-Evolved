/**
 * Output contracts for the 4-layer 28-agent daily cycle.
 *
 * Each layer-X agent produces a typed payload that gets written into
 * ``state.layer<X>_outputs[<agent_id>]`` by the dict-merge reducer in
 * ``state.ts``. Downstream stages consume the individual accepted outputs;
 * the runtime does not collapse a layer into a consensus bundle.
 *
 * Conventions:
 *   * All confidences are in [0, 1].
 *   * All dates are ISO yyyy-mm-dd strings.
 *   * Tickers follow the canonical MOSAIC form ``"600519.SH" | "300750.SZ" |
 *     "2800.HK"``. Numeric-only / Eastmoney prefixed forms ("SH600519") are
 *     normalised at the bridge boundary.
 *
 * State.ts uses these as TS interfaces (compile-time only). Each agent
 * additionally exports a Zod schema for runtime validation of the LLM
 * structured-output payload (``z.infer<typeof XSchema>`` matches the
 * interface here). The schemas live next to the agent node in
 * ``agents/<layer>/<agent>.ts``.
 */

import type { PromptReleaseCanaryEvent } from "../autoresearch/prompt_release_canary_slo.js";
import type { ClaimEvidenceGraph, LlmResearchClaim } from "./evidence_contract.js";
import type { AgentRunAudit } from "./helpers/agent_run_contract.js";
import type {
  AcceptedMacroInputAttribution,
  MacroInputAttributionSubmission,
} from "./helpers/macro_attribution.js";
import type {
  PrivateKnotSnapshot,
  RuntimeSourceEvidenceObservation,
  RuntimeSourceStatus,
} from "./helpers/private_knot_boundary.js";

// ============================================================ Layer 1: Macro

export interface RuntimeOutputAuditFields {
  claims?: LlmResearchClaim[] | undefined;
  claim_refs?: string[] | undefined;
  /** Runtime-owned fields, ignored by legacy consumers. */
  verified_claim_graph?: ClaimEvidenceGraph | undefined;
  verified_claim_audit?:
    | {
        raw_output_accepted: boolean;
        rejection_reasons: string[];
        fallback_reason_code?: string | undefined;
      }
    | undefined;
  runtime_fallback_audit?:
    | {
        fallback_factory_id: string;
        fallback_factory_version: string;
        reason_codes: string[];
      }
    | undefined;
}

export type MacroAgentId =
  | "china"
  | "us_economy"
  | "eu_economy"
  | "central_bank"
  | "us_financial_conditions"
  | "euro_area_financial_conditions"
  | "commodities"
  | "geopolitical"
  | "market_breadth"
  | "institutional_flow";

export type MacroDirection = "SUPPORTIVE" | "NEUTRAL" | "ADVERSE";
export type MacroPersistenceHorizon = "DAYS" | "WEEKS" | "MONTHS";

export interface DirectMacroSignal {
  direction: MacroDirection;
  strength: 0 | 1 | 2 | 3 | 4 | 5;
  persistence_horizon: MacroPersistenceHorizon;
  evaluation_horizon_trading_days: 5;
  confidence: number;
  channels: string[];
  claim_refs: string[];
}

export interface MacroComponentSignal extends DirectMacroSignal {
  component: string;
}

export interface MacroAgentSubmissionBase extends RuntimeOutputAuditFields {
  claims: LlmResearchClaim[];
  key_drivers: string[];
}

export type MacroAgentSubmission =
  | (MacroAgentSubmissionBase & {
      mode: "DIRECT";
      signal: DirectMacroSignal;
    })
  | (MacroAgentSubmissionBase & {
      mode: "COMPONENTS";
      components: MacroComponentSignal[];
    });

export interface AcceptedMacroTransmission extends RuntimeOutputAuditFields {
  agent_id: MacroAgentId;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string | null;
  direction: "SUPPORTIVE" | "NEUTRAL" | "ADVERSE";
  strength: 0 | 1 | 2 | 3 | 4 | 5;
  persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
  evaluation_horizon_trading_days: 5;
  model_confidence: number;
  deterministic_data_quality: number;
  confidence: number;
  channels: string[];
  claims: LlmResearchClaim[];
  claim_refs: string[];
  key_drivers: string[];
}

export interface ComponentCalibrationRuntimeInput {
  agent_id: MacroAgentId;
  component_weight_contract_version: string;
  components: Array<
    MacroComponentSignal & {
      deterministic_data_quality: number;
    }
  >;
}

/**
 * Runtime-only, immutable composition evidence for a composed Macro output.
 * It is hash-bound to the accepted record, but is never part of the payload
 * exposed to models or downstream voting consumers.
 */
export interface MacroComponentCompositionAudit extends ComponentCalibrationRuntimeInput {
  schema_version: "macro_component_composition_audit_v1";
  component_weights: Record<string, number>;
  source_snapshot_hash: string;
  context_only_projection_hash: string | null;
  composed_payload_hash: string;
  component_composition_hash: string;
}

export interface MacroInputGateReceipt {
  schema_version: "macro_input_gate_receipt_v1";
  accepted_agent_ids: MacroAgentId[];
  accepted_count: 10;
  input_hash: string;
  source_layer_snapshot_id: string;
  source_layer_snapshot_hash: string;
  darwinian_snapshot_id: string | null;
  darwinian_snapshot_hash: string | null;
  reliability_by_agent: Record<
    MacroAgentId,
    {
      effective_reliability: number;
      usage_share: number;
      weight_record_id: string | null;
      reliability_record_id: string | null;
    }
  >;
}

export type ChinaOutput = MacroAgentSubmission;
export type UsEconomyOutput = MacroAgentSubmission;
export type EuEconomyOutput = MacroAgentSubmission;
export type CentralBankOutput = MacroAgentSubmission;
export type UsFinancialConditionsOutput = MacroAgentSubmission;
export type EuroAreaFinancialConditionsOutput = MacroAgentSubmission;
export type CommoditiesOutput = MacroAgentSubmission;
export type GeopoliticalOutput = MacroAgentSubmission;
export type MarketBreadthOutput = MacroAgentSubmission;
export type InstitutionalFlowOutput = MacroAgentSubmission;
export type MacroAgentOutput = AcceptedMacroTransmission;

/** Old rows remain readable for audit only and never enter current aggregation or ranking. */
export interface LegacyMacroAgentOutput {
  agent: "dollar" | "yield_curve" | "volatility" | "emerging_markets" | "news_sentiment";
  legacy_status: "legacy_unverified";
  [key: string]: unknown;
}

// ============================================================ Layer 2: Sector

export type StandardSectorAgentId =
  | "semiconductor"
  | "technology"
  | "energy"
  | "biotech"
  | "consumer"
  | "industrials"
  | "real_estate_construction"
  | "financials"
  | "agriculture";

export type SectorAgentId = StandardSectorAgentId | "relationship_mapper";

export interface SectorSecurityPickSubmission {
  pick_local_id: string;
  ts_code: string;
  direction_local_id: string;
  position_action: "LONG" | "SHORT" | "AVOID";
  conviction: number;
  thesis: string;
  claim_refs: string[];
}

export interface SectorAgentOutputBase extends RuntimeOutputAuditFields {
  agent: StandardSectorAgentId;
  selection_status: "SELECTED";
  preferred_direction: {
    selection_role: "PREFERRED";
    direction_local_id: string;
    direction_id: string;
    allocation_action: "OVERWEIGHT";
    strength: 1 | 2 | 3 | 4 | 5;
    thesis: string;
    claim_refs: string[];
  };
  least_preferred_direction: {
    selection_role: "LEAST_PREFERRED";
    direction_local_id: string;
    direction_id: string;
    allocation_action: "UNDERWEIGHT";
    strength: 1 | 2 | 3 | 4 | 5;
    thesis: string;
    claim_refs: string[];
  };
  persistence_horizon: MacroPersistenceHorizon;
  confidence: number;
  key_drivers: Array<{ driver_local_id: string; summary: string; claim_refs: string[] }>;
  risks: Array<{ risk_local_id: string; summary: string; claim_refs: string[] }>;
  claims: LlmResearchClaim[];
  claim_refs: string[];
  preferred_security_status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
  preferred_security_abstention_confidence: number | null;
  long_picks: SectorSecurityPickSubmission[];
  least_preferred_security_status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
  least_preferred_security_abstention_confidence: number | null;
  short_or_avoid_picks: SectorSecurityPickSubmission[];
  macro_input_attributions: MacroInputAttributionSubmission[];
  /** Runtime-owned bindings. They are never part of the model final-selection schema. */
  sector_runtime_binding?: SectorRuntimeSelectionBinding | undefined;
}

export interface SectorRuntimeSelectionBinding {
  snapshot_bundle_id: string;
  snapshot_bundle_hash: string;
  direction_comparison_audit_hash: string;
  finalized_pair_matrix_hash: string;
  selection_status: "SELECTED";
  preferred_direction_id: string;
  least_preferred_direction_id: string;
  preferred_security_shortlist_id: string;
  preferred_security_shortlist_hash: string;
  least_preferred_security_shortlist_id: string;
  least_preferred_security_shortlist_hash: string;
  security_scoring_contract_version: string;
  security_scoring_contract_hash: string;
  required_preferred_evidence_ids: string[];
  required_least_preferred_evidence_ids: string[];
  required_final_evidence_ids: string[];
}

export interface RelationshipMapperOutput extends RuntimeOutputAuditFields {
  agent: "relationship_mapper";
  factual_edges: Array<{
    edge_local_id: string;
    source_entity: string;
    target_entity: string;
    edge_type: string;
    claim_refs: string[];
  }>;
  predictive_edges: Array<{
    edge_local_id: string;
    edge_candidate_id: string;
    source_entity: string;
    target_entity: string;
    edge_type: string;
    transmission_direction: "POSITIVE" | "NEGATIVE" | "MIXED";
    activation_trigger: string;
    evaluation_horizon_trading_days: 20;
    model_confidence: number;
    claim_refs: string[];
  }>;
  predictive_graph_status: "EDGES_PRESENT" | "NO_QUALIFIED_PREDICTIVE_EDGE";
  predictive_graph_abstention_confidence: number | null;
  key_drivers: Array<{ driver_local_id: string; summary: string; claim_refs: string[] }>;
  risks: Array<{ risk_local_id: string; summary: string; claim_refs: string[] }>;
  claims: LlmResearchClaim[];
  claim_refs: string[];
  macro_input_attributions: SectorAgentOutputBase["macro_input_attributions"];
}

export type { AcceptedMacroInputAttribution, MacroInputAttributionSubmission };

export type SectorAgentOutput =
  | SemiconductorOutput
  | TechnologyOutput
  | EnergyOutput
  | BiotechOutput
  | ConsumerOutput
  | IndustrialsOutput
  | RealEstateConstructionOutput
  | FinancialsOutput
  | AgricultureOutput
  | RelationshipMapperOutput;

export interface SemiconductorOutput extends SectorAgentOutputBase {
  agent: "semiconductor";
}
export interface TechnologyOutput extends SectorAgentOutputBase {
  agent: "technology";
}
export interface EnergyOutput extends SectorAgentOutputBase {
  agent: "energy";
}
export interface BiotechOutput extends SectorAgentOutputBase {
  agent: "biotech";
}
export interface ConsumerOutput extends SectorAgentOutputBase {
  agent: "consumer";
}
export interface IndustrialsOutput extends SectorAgentOutputBase {
  agent: "industrials";
}
export interface RealEstateConstructionOutput extends SectorAgentOutputBase {
  agent: "real_estate_construction";
}
export interface FinancialsOutput extends SectorAgentOutputBase {
  agent: "financials";
}
export interface AgricultureOutput extends SectorAgentOutputBase {
  agent: "agriculture";
}

// ============================================================ Layer 3: Superinvestor

/** Plan §5.3 — druckenmiller, munger, burry, ackman.
 *
 *  Each superinvestor applies a philosophy filter and produces a concentrated
 *  pick list (typically 3–5 names) with the philosophical rationale.
 */
export type SuperinvestorAgentId = "druckenmiller" | "munger" | "burry" | "ackman";

export interface SuperinvestorSecurityPickSubmission {
  pick_local_id: string;
  ts_code: string;
  position_action: "LONG" | "AVOID";
  conviction: number;
  thesis: string;
  claim_refs: string[];
}

export interface SuperinvestorDriverSubmission {
  driver_local_id: string;
  summary: string;
  claim_refs: string[];
}

export interface SuperinvestorRiskSubmission {
  risk_local_id: string;
  summary: string;
  claim_refs: string[];
}

interface SuperinvestorSubmissionBase extends RuntimeOutputAuditFields {
  agent: SuperinvestorAgentId;
  confidence: number;
  holding_period: "WEEKS" | "MONTHS" | "YEARS";
  key_drivers: SuperinvestorDriverSubmission[];
  risks: SuperinvestorRiskSubmission[];
  claims: LlmResearchClaim[];
  claim_refs: string[];
  macro_input_attributions: MacroInputAttributionSubmission[];
}

export type SuperinvestorOutput =
  | (SuperinvestorSubmissionBase & {
      selection_status: "SELECTED";
      picks: SuperinvestorSecurityPickSubmission[];
    })
  | (SuperinvestorSubmissionBase & {
      selection_status: "NO_QUALIFIED_CANDIDATES";
      picks: [];
    });

export type DruckenmillerOutput = SuperinvestorOutput & { agent: "druckenmiller" };
export type MungerOutput = SuperinvestorOutput & { agent: "munger" };
export type BurryOutput = SuperinvestorOutput & { agent: "burry" };
export type AckmanOutput = SuperinvestorOutput & { agent: "ackman" };

// ============================================================ Layer 4: Decision

/** Plan §5.4 — cro, alpha_discovery, autonomous_execution, cio. */

export interface CroOutput extends RuntimeOutputAuditFields {
  agent: "cro";
  review_disposition?: "REVIEW_ACTIONS" | "NO_OBJECTION" | "BLOCK_ALL" | undefined;
  rejected_picks: Array<{ ticker: string; reason: string; claim_refs?: string[] | undefined }>;
  required_adjustments?:
    | Array<{
        action_local_id?: string | undefined;
        candidate_ref?: string | undefined;
        ticker: string;
        adjustment: "VETO" | "CAP_WEIGHT" | "REDUCE_WEIGHT" | "REQUIRE_REVIEW";
        max_target_weight?: number | undefined;
        reason: string;
        claim_refs?: string[] | undefined;
      }>
    | undefined;
  correlated_risks: string[];
  black_swan_scenarios: string[];
  /** Self-rated confidence in [0, 1]. Same semantics as L1/L2/L3. */
  confidence: number;
}

export interface AlphaDiscoveryOutput extends RuntimeOutputAuditFields {
  agent: "alpha_discovery";
  discovery_disposition?: "CANDIDATES" | "NONE_FOUND" | undefined;
  novel_picks: Array<{
    ticker: string;
    why_missed_by_others: string;
    claim_refs?: string[] | undefined;
  }>;
  /** Self-rated confidence in [0, 1]. */
  confidence: number;
}

export interface AutoExecOutput extends RuntimeOutputAuditFields {
  agent: "autonomous_execution";
  execution_disposition?: "TRADES" | "NO_DELTA" | "BLOCKED" | undefined;
  trades: Array<{
    assessment_local_id?: string | undefined;
    order_intent_ref?: string | undefined;
    ticker: string;
    action: "BUY" | "SELL" | "HOLD" | "REDUCE";
    size_pct: number;
    delta_weight?: number | undefined;
    estimated_slippage_pct?: number | undefined;
    liquidity_score?: number | undefined;
    order_split_count?: number | undefined;
    conviction: number;
    claim_refs?: string[] | undefined;
  }>;
  execution_checks?:
    | Array<{
        assessment_local_id?: string | undefined;
        order_intent_ref?: string | undefined;
        ticker: string;
        requested_delta_weight?: number | undefined;
        status: "feasible" | "partial" | "blocked";
        estimated_cost_bps: number;
        max_executable_delta_weight?: number | undefined;
        reason: string;
        claim_refs?: string[] | undefined;
      }>
    | undefined;
  execution_enforcement?:
    | {
        checked_trade_count: number;
        active_policy_ids: string[];
        min_delta_trade_weight?: number | undefined;
        slippage_cap?: number | undefined;
        liquidity_floor?: number | undefined;
      }
    | undefined;
  /** Self-rated confidence in [0, 1]. */
  confidence: number;
}

export interface PortfolioAction {
  ticker: string;
  action: "BUY" | "SELL" | "HOLD" | "REDUCE";
  sector?: string | undefined;
  position_decision?: "HOLD" | "ADD" | "REDUCE" | "EXIT" | undefined;
  current_weight?: number | undefined;
  /** Target portfolio weight in [0, 1]. */
  target_weight: number;
  delta_weight?: number | undefined;
  holding_period: "1W" | "1M" | "3M" | "6M" | "1Y" | "5Y+";
  position_decision_reason?: string | undefined;
  override_reason?: string | undefined;
  thesis_status?: "intact" | "weakened" | "broken" | "expired" | undefined;
  risk_flags?: string[] | undefined;
  /** Runtime-owned provenance for position-review coverage accounting. */
  review_source?: "llm" | "runtime_safety_fallback" | undefined;
  /** CIO note explaining dissent against another agent's call, if any. */
  dissent_notes: string;
  claim_refs?: string[] | undefined;
}

export interface CioOutput extends RuntimeOutputAuditFields {
  agent: "cio";
  decision_disposition?: "TARGET_PORTFOLIO" | "HOLD_CURRENT" | "ALL_CASH" | undefined;
  decision_reason?: string | undefined;
  decision_claim_refs?: string[] | undefined;
  portfolio_actions: PortfolioAction[];
  position_reviews?: PositionReview[] | undefined;
  dissent_refs?: CioDissentReference[] | undefined;
  cro_control_resolutions?:
    | Array<{
        cro_action_local_ref: string;
        resolution: "COMPLIED" | "MORE_CONSERVATIVE";
        reason: string;
        claim_refs?: string[] | undefined;
      }>
    | undefined;
  execution_control_resolutions?:
    | Array<{
        execution_assessment_local_ref: string;
        resolution: "COMPLIED" | "MORE_CONSERVATIVE";
        reason: string;
        claim_refs?: string[] | undefined;
      }>
    | undefined;
  /** Self-rated confidence in [0, 1]. */
  confidence: number;
}

export interface CioDissentReference {
  ticker: string;
  source: "cro_review" | "execution_feasibility";
  source_hash: string;
  reason: string;
}

export interface CioProposalOutput extends CioOutput {
  position_reviews: PositionReview[];
}

export interface CioFinalOutput extends CioOutput {
  dissent_refs: CioDissentReference[];
}

export interface CurrentPosition {
  ticker: string;
  sector?: string | undefined;
  current_weight: number;
  cost_basis: number;
  market_price: number;
  unrealized_pnl_pct: number;
  realized_pnl_pct?: number | undefined;
  residual_drift_pct?: number | undefined;
  holding_days: number;
  entry_date: string;
  source_agent: string;
  entry_thesis_id: string;
  last_review_date: string;
}

export interface ClosedPosition {
  ticker: string;
  exit_date: string;
  exit_reason: string;
  realized_pnl_pct: number;
  residual_drift_pct: number;
  entry_thesis_id: string;
  holding_days: number;
}

export interface CurrentPositionsSnapshot {
  snapshot_status: "loaded" | "empty_confirmed" | "missing";
  position_source:
    | "paper_account"
    | "backtest_replay"
    | "cli_fixture"
    | "empty_confirmed"
    | "unknown";
  source_error_code: string | null;
  position_snapshot_hash?: string | undefined;
  positions: CurrentPosition[];
  closed_positions?: ClosedPosition[] | undefined;
}

export interface PositionReview {
  ticker: string;
  decision: "HOLD" | "ADD" | "REDUCE" | "EXIT";
  target_weight: number;
  reason: string;
  thesis_status: "intact" | "weakened" | "broken" | "expired";
  risk_flags: string[];
  confidence: number;
  review_source?: "llm" | "runtime_safety_fallback" | undefined;
  claim_refs?: string[] | undefined;
}

export interface CandidateTargetState {
  schema_version: "portfolio.candidate_target_state.v1";
  run_id: string;
  cohort: string;
  as_of_date: string;
  proposal_hash: string;
  l4_run_snapshot_hash: string;
  candidate_target_hash: string;
  position_snapshot_hash: string | null;
  previous_target_hash: string | null;
  market_data_vintage_hash: string;
  portfolio_actions: PortfolioAction[];
  confidence: number;
  frozen: true;
}

export interface PositionReviewState {
  schema_version: "portfolio.position_review_state.v1";
  run_id: string;
  candidate_target_hash: string;
  l4_run_snapshot_hash: string;
  position_review_hash: string;
  reviews: PositionReview[];
  llm_reviewed_tickers: string[];
  fallback_tickers: string[];
  frozen: true;
}

export interface PortfolioExposureState {
  schema_version: "portfolio.exposure_state.v1";
  candidate_target_hash: string;
  l4_run_snapshot_hash: string;
  exposure_hash: string;
  gross_exposure: number;
  net_exposure: number;
  cash_weight: number;
  ticker_weights: Record<string, number>;
  sector_weights: Record<string, number>;
  frozen: true;
}

export interface CroReviewState {
  schema_version: "decision.cro_review_state.v1";
  run_id: string;
  candidate_target_hash: string;
  l4_run_snapshot_hash: string;
  source_status: "ACCEPTED_OUTPUT" | "NO_EVALUATION_OBJECT";
  stage_skip_id: string | null;
  stage_skip_hash: string | null;
  review_hash: string;
  output: CroOutput;
  frozen: true;
}

export interface ExecutionFeasibilityState {
  schema_version: "decision.execution_feasibility_state.v1";
  run_id: string;
  candidate_target_hash: string;
  l4_run_snapshot_hash: string;
  cro_review_hash: string;
  source_status: "ACCEPTED_OUTPUT" | "NO_EVALUATION_OBJECT";
  stage_skip_id: string | null;
  stage_skip_hash: string | null;
  liquidity_vintage_hash: string;
  feasibility_hash: string;
  output: AutoExecOutput;
  frozen: true;
}

export interface FinalTargetState {
  schema_version: "portfolio.final_target_state.v1";
  run_id: string;
  cohort: string;
  as_of_date: string;
  candidate_target_hash: string;
  l4_run_snapshot_hash: string;
  cro_review_hash: string;
  execution_feasibility_hash: string;
  final_target_hash: string;
  position_snapshot_hash: string | null;
  previous_target_hash: string | null;
  market_data_vintage_hash: string;
  liquidity_vintage_hash: string;
  portfolio_actions: PortfolioAction[];
  confidence: number;
  validator_hashes: string[];
  frozen: true;
}

export interface PortfolioSummary {
  schema_version: "portfolio.summary.v1";
  l4_run_snapshot_hash: string;
  base_position_snapshot_hash: string | null;
  market_vintage_hash: string;
  liquidity_vintage_hash: string;
  candidate_target_hash: string;
  final_target_hash: string;
  cash_weight: number;
  gross_exposure: number;
  net_exposure: number;
  target_weight_sum: number;
  leverage_authorized: false;
  action_mapping_hash: string;
  validator_bundle_hash: string;
  validator_results: Array<{
    validator_hash: string;
    status: "accepted" | "fallback";
    reason_codes: string[];
  }>;
  summary_hash: string;
  frozen: true;
}

export interface PreviousTargetState {
  schema_version: "portfolio.previous_target_state.v1";
  snapshot_status: "loaded" | "empty_confirmed" | "missing";
  final_target_hash: string | null;
  as_of_date: string | null;
  portfolio_actions: PortfolioAction[];
  source_error_code: string | null;
}

export interface L4RunPromptSnapshot {
  agent: "alpha_discovery" | "cio" | "cro" | "autonomous_execution";
  stage: "alpha_discovery" | "cio_proposal" | "cro_review" | "execution_feasibility" | "cio_final";
  prompt_source_hash: string;
  private_knot_snapshot_hash: string | null;
}

export interface L4RunSnapshotBundle {
  schema_version: "decision.l4_run_snapshot_bundle.v1";
  run_id: string;
  cohort: string;
  as_of_date: string;
  prompt_snapshots: L4RunPromptSnapshot[];
  position_snapshot_hash: string;
  account_snapshot_hash: string;
  upstream_outputs_hash: string;
  base_market_data_vintage_hash: string;
  base_market_source_hashes: Record<string, string>;
  mirofish_context_hash: string | null;
  bundle_hash: string;
  frozen: true;
}

export interface Layer4RuntimeTraceEntry {
  sequence: number;
  stage:
    | "l4_snapshot_freeze"
    | "alpha_discovery"
    | "cio_proposal"
    | "cro_review"
    | "execution_feasibility"
    | "cio_final"
    | "shared_validation";
  operation: "agent_run" | "source_freeze" | "stage_skip" | "validation";
  status: "completed" | "skipped" | "fallback" | "rejected";
  reason_codes?: string[] | undefined;
  fallback_factory_id?: string | undefined;
  fallback_factory_version?: string | undefined;
  input_hashes: Record<string, string>;
  output_hashes: Record<string, string>;
}

export interface Layer4RuntimeState {
  l4_run_snapshot_bundle: L4RunSnapshotBundle | null;
  cio_proposal: CioOutput | null;
  candidate_target_state: CandidateTargetState | null;
  position_review_state: PositionReviewState | null;
  portfolio_exposure_state: PortfolioExposureState | null;
  cro_review_state: CroReviewState | null;
  execution_feasibility_state: ExecutionFeasibilityState | null;
  final_target_state: FinalTargetState | null;
  portfolio_summary: PortfolioSummary | null;
  cio_final_knob_snapshot: PrivateKnotSnapshot | null;
  resolved_source_statuses: RuntimeSourceStatus[];
  source_evidence_observations: RuntimeSourceEvidenceObservation[];
  stage_trace: Layer4RuntimeTraceEntry[];
}

export interface PositionAudit {
  position_snapshot_hash: string | null;
  snapshot_status: CurrentPositionsSnapshot["snapshot_status"];
  position_source: CurrentPositionsSnapshot["position_source"];
  source_error_code: string | null;
  tool_status_summary?: Record<string, string> | undefined;
  positions_loaded: number;
  positions_reviewed: number;
  positions_unreviewed: number;
  runtime_safety_hold_count?: number | undefined;
  cash_weight?: number | undefined;
  gross_exposure?: number | undefined;
  net_exposure?: number | undefined;
  hold_count: number;
  add_count: number;
  reduce_count: number;
  exit_count: number;
  stale_thesis_count: number;
  stop_loss_override_count: number;
  target_current_drift_count: number;
}

export interface Layer4Outputs {
  cro: CroOutput | null;
  alpha_discovery: AlphaDiscoveryOutput | null;
  autonomous_execution: AutoExecOutput | null;
  cio: CioOutput | null;
  /** Runtime-owned cross-stage envelopes; LLMs never author these hashes. */
  runtime?: Layer4RuntimeState | undefined;
  /** Prior cycle final target supplied as an explicit cycle input. */
  previous_target_state?: PreviousTargetState | undefined;
}

export type Layer4AgentOutputKey = "cro" | "alpha_discovery" | "autonomous_execution" | "cio";

// ============================================================ Observability

export interface LlmCallRecord {
  /** ISO timestamp of the call. */
  ts: string;
  /** Logical agent that triggered the call (e.g. "central_bank"). */
  agent: string;
  /** Model identifier from the bridge config (e.g. "claude-sonnet-4"). */
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  /** Provider as resolved by the LLM factory. */
  provider: string;
  /** Estimated USD cost; computed at the call site, may be 0 for local providers. */
  cost_usd: number;
  prompt_canary_event?: PromptReleaseCanaryEvent;
  agent_run_audit?: AgentRunAudit;
  sector_inference_audit?: SectorInferenceAuditRecord;
}

export interface SectorInferenceAuditRecord {
  schema_version: "sector_inference_audit_v1";
  sector_agent_id: StandardSectorAgentId;
  snapshot_bundle_hash: string;
  model_subcall_count: number;
  conflict_review_triggered: boolean;
  direction_research_audit: AgentRunAudit;
  conflict_review_audit: AgentRunAudit | null;
  final_selection_audit: AgentRunAudit;
  direction_comparison_audit_hash: string;
  direction_comparison_audit: Record<string, unknown>;
  inference_cost_audit_id: string;
  inference_cost_audit_hash: string;
  usage_summary_receipt_id: string;
  usage_summary_receipt_hash: string;
}

// ============================================================ Convenience

/** Complete final cycle output for downstream consumers (Phase 3 scorecard,
 *  TUI rendering, persistence). */
export interface DailyCycleResult {
  active_cohort: string;
  as_of_date: string;
  layer1_outputs: Record<string, MacroAgentOutput>;
  macro_input_gate: MacroInputGateReceipt | null;
  layer2_outputs: Record<string, SectorAgentOutput>;
  layer3_outputs: Record<string, SuperinvestorOutput>;
  layer4_outputs: Layer4Outputs;
  current_positions: CurrentPositionsSnapshot;
  position_reviews: PositionReview[];
  position_audit: PositionAudit;
  /** The CIO's final allocation, surfaced for convenience. */
  portfolio_actions: PortfolioAction[];
  llm_calls: LlmCallRecord[];
  trace_id: string;
}

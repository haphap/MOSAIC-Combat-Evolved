/**
 * Output contracts for the 4-layer 25-agent daily cycle (Plan §5).
 *
 * Each layer-X agent produces a typed payload that gets written into
 * ``state.layer<X>_outputs[<agent_id>]`` by the dict-merge reducer in
 * ``state.ts``. Aggregator nodes at the end of each layer collapse those
 * maps into a single consensus object (``layer<X>_consensus``).
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
  ResearchKnobsSnapshot,
  RuntimeSourceEvidenceObservation,
  RuntimeSourceStatus,
} from "./helpers/research_knobs.js";

// ============================================================ Layer 1: Macro

export interface KnobInfluenceDeclaration {
  declared_knob_influence_ids?: string[] | undefined;
  declared_influence_rationale?: string | undefined;
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
  | "central_bank"
  | "dollar"
  | "yield_curve"
  | "commodities"
  | "geopolitical"
  | "volatility"
  | "market_breadth"
  | "institutional_flow";

/** The sole directional contract shared by every Layer-1 macro role. */
export interface MacroTransmission {
  direction: "SUPPORTIVE" | "NEUTRAL" | "ADVERSE";
  strength: 0 | 1 | 2 | 3 | 4 | 5;
  horizon: "DAYS" | "WEEKS" | "MONTHS";
  channels: string[];
  claim_refs: string[];
}

export interface MacroAgentOutputBase extends KnobInfluenceDeclaration, MacroTransmission {
  agent: MacroAgentId;
  confidence: number;
  key_drivers: string[];
  claims: LlmResearchClaim[];
  claim_refs: string[];
}

export type CentralBankOutput = MacroAgentOutputBase & { agent: "central_bank" };
export type ChinaOutput = MacroAgentOutputBase & { agent: "china" };
export type UsEconomyOutput = MacroAgentOutputBase & { agent: "us_economy" };
export type DollarOutput = MacroAgentOutputBase & { agent: "dollar" };
export type YieldCurveOutput = MacroAgentOutputBase & { agent: "yield_curve" };
export type CommoditiesOutput = MacroAgentOutputBase & { agent: "commodities" };
export type GeopoliticalOutput = MacroAgentOutputBase & { agent: "geopolitical" };
export type VolatilityOutput = MacroAgentOutputBase & { agent: "volatility" };
export type MarketBreadthOutput = MacroAgentOutputBase & { agent: "market_breadth" };
export type InstitutionalFlowOutput = MacroAgentOutputBase & { agent: "institutional_flow" };

export type MacroAgentOutput =
  | ChinaOutput
  | UsEconomyOutput
  | CentralBankOutput
  | DollarOutput
  | YieldCurveOutput
  | CommoditiesOutput
  | GeopoliticalOutput
  | VolatilityOutput
  | MarketBreadthOutput
  | InstitutionalFlowOutput;

/** Old rows remain readable for audit only and never enter current aggregation or ranking. */
export interface LegacyMacroAgentOutput {
  agent: "emerging_markets" | "news_sentiment";
  legacy_status: "legacy_unverified";
  [key: string]: unknown;
}

/** Plan §5.1 — aggregated regime call after all 10 macro agents have written. */
export interface RegimeSignal {
  stance: "BULLISH" | "BEARISH" | "NEUTRAL";
  confidence: number;
  key_drivers: string[];
  /** Final six-group score S in [-1, 1]. */
  layer_1_consensus_score: number;
}

// ============================================================ Layer 2: Sector

/** Plan §5.2 — semiconductor, energy, biotech, consumer, industrials, financials,
 *  relationship_mapper.
 *
 *  Sector agents share a uniform shape: longs / shorts with thesis, plus a
 *  numeric sector_score. relationship_mapper deviates and uses
 *  ``RelationshipMapperOutput`` instead.
 */
export interface SectorPick {
  ticker: string;
  thesis: string;
  /** [0, 1]. */
  conviction: number;
  claim_refs?: string[] | undefined;
}

export interface SectorAgentOutputBase extends KnobInfluenceDeclaration {
  agent: string;
  selection_disposition?: "CANDIDATES" | "NO_QUALIFIED_CANDIDATES" | undefined;
  longs: SectorPick[];
  shorts: SectorPick[];
  /** [-1, 1], where +1 = max bullish on the sector. */
  sector_score: number;
  key_drivers: string[];
  /** Self-rated confidence in [0, 1]. Same semantics as Layer 1. */
  confidence: number;
}

export interface RelationshipMapperOutput extends KnobInfluenceDeclaration {
  agent: "relationship_mapper";
  supply_chains: Array<{ name: string; tickers: string[]; risk: string }>;
  ownership_clusters: Array<{ cluster_id: string; tickers: string[] }>;
  contagion_risks: string[];
  key_drivers: string[];
  /** Self-rated confidence in [0, 1]. */
  confidence: number;
}

export type SectorAgentOutput =
  | SemiconductorOutput
  | EnergyOutput
  | BiotechOutput
  | ConsumerOutput
  | IndustrialsOutput
  | FinancialsOutput
  | RelationshipMapperOutput;

export interface SemiconductorOutput extends SectorAgentOutputBase {
  agent: "semiconductor";
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
export interface FinancialsOutput extends SectorAgentOutputBase {
  agent: "financials";
}

/** Aggregated sector view written by the L2 aggregator. */
export interface SectorConsensus {
  /** Top 3 sectors with the strongest positive sector_score. */
  top_sectors: Array<{ sector: string; score: number }>;
  /** Top 3 sectors with the strongest negative sector_score. */
  bottom_sectors: Array<{ sector: string; score: number }>;
  /** Cross-sector contagion or relationship signals from relationship_mapper. */
  cross_sector_risks: string[];
}

// ============================================================ Layer 3: Superinvestor

/** Plan §5.3 — druckenmiller, munger, burry, ackman.
 *
 *  Each superinvestor applies a philosophy filter and produces a concentrated
 *  pick list (typically 3–5 names) with the philosophical rationale.
 */
export interface SuperinvestorPick {
  ticker: string;
  /** The investor-style rationale: macro asymmetry / quality moat / deep value / activist quality. */
  thesis: string;
  conviction: number;
  /** Suggested holding period bracket. */
  holding_period: "1W" | "1M" | "3M" | "6M" | "1Y" | "5Y+";
  claim_refs?: string[] | undefined;
}

export interface SuperinvestorOutput extends KnobInfluenceDeclaration {
  agent: "druckenmiller" | "munger" | "burry" | "ackman";
  selection_disposition?: "CANDIDATES" | "NO_QUALIFIED_CANDIDATES" | undefined;
  picks: SuperinvestorPick[];
  /** Why these 3-5 names + macro/sector regime fit. */
  philosophy_note: string;
  key_drivers: string[];
  /** Self-rated confidence in [0, 1]. Same semantics as L1/L2. */
  confidence: number;
}

export interface DruckenmillerOutput extends Omit<SuperinvestorOutput, "agent"> {
  agent: "druckenmiller";
}
export interface MungerOutput extends Omit<SuperinvestorOutput, "agent"> {
  agent: "munger";
}
export interface BurryOutput extends Omit<SuperinvestorOutput, "agent"> {
  agent: "burry";
}
export interface AckmanOutput extends Omit<SuperinvestorOutput, "agent"> {
  agent: "ackman";
}

// ============================================================ Layer 4: Decision

/** Plan §5.4 — cro, alpha_discovery, autonomous_execution, cio. */

export interface CroOutput extends KnobInfluenceDeclaration {
  agent: "cro";
  review_disposition?: "REVIEW_ACTIONS" | "NO_OBJECTION" | "BLOCK_ALL" | undefined;
  rejected_picks: Array<{ ticker: string; reason: string; claim_refs?: string[] | undefined }>;
  required_adjustments?:
    | Array<{
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

export interface AlphaDiscoveryOutput extends KnobInfluenceDeclaration {
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

export interface AutoExecOutput extends KnobInfluenceDeclaration {
  agent: "autonomous_execution";
  execution_disposition?: "TRADES" | "NO_DELTA" | "BLOCKED" | undefined;
  trades: Array<{
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
        ticker: string;
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
  holding_period: SuperinvestorPick["holding_period"];
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

export interface CioOutput extends KnobInfluenceDeclaration {
  agent: "cio";
  decision_disposition?: "TARGET_PORTFOLIO" | "HOLD_CURRENT" | "ALL_CASH" | undefined;
  decision_reason?: string | undefined;
  decision_claim_refs?: string[] | undefined;
  portfolio_actions: PortfolioAction[];
  position_reviews?: PositionReview[] | undefined;
  dissent_refs?: CioDissentReference[] | undefined;
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
  knob_snapshot_hash: string | null;
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
  operation: "agent_run" | "source_freeze" | "validation";
  status: "completed" | "fallback" | "rejected";
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
  cio_final_knob_snapshot: ResearchKnobsSnapshot | null;
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
}

// ============================================================ Convenience

/** Complete final cycle output for downstream consumers (Phase 3 scorecard,
 *  TUI rendering, persistence). */
export interface DailyCycleResult {
  active_cohort: string;
  as_of_date: string;
  layer1_outputs: Record<string, MacroAgentOutput>;
  layer1_consensus: RegimeSignal | null;
  layer2_outputs: Record<string, SectorAgentOutput>;
  layer2_consensus: SectorConsensus | null;
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

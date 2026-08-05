/**
 * MOSAIC daily-cycle state for LangGraph.js (Plan §5 + §11.2 Phase 2A design).
 *
 * Why per-layer maps instead of ETFAgents' flat-30-keys: 28 agents flat would
 * blow the state up to 40+ fields; grouping outputs per layer with a dict-merge
 * reducer lets multiple agents inside one layer write concurrently without
 * conflict (LangGraph.js merges parallel branch updates via the channel reducer).
 *
 * Reducer choices:
 *   * ``layer<N>_outputs``     dict-merge ``{...prev, ...next}`` — many writers
 *   * ``llm_calls``            append — concurrent writers, order is best-effort
 *   * scalar fields            replace — last-write-wins
 *
 * The MessagesAnnotation slice is included so individual agent nodes can
 * still leverage LangGraph's built-in messages reducer when they expose a
 * tool-calling sub-loop.
 *
 * Reducers are exported as named functions so they can be unit-tested in
 * isolation without depending on LangGraph's internal Annotation shape.
 */

import { Annotation, MessagesAnnotation } from "@langchain/langgraph";
import type {
  NoEvaluationObjectStageSkipAgentId,
  NoEvaluationObjectStageSkipRecord,
} from "../autoresearch/outcome_stage_skip.js";
import type {
  ComponentWeightRuntimeSnapshot,
  DarwinianRuntimeBinding,
  DarwinianUsageWeightSnapshot,
} from "../autoresearch/production_variant.js";
import type { AcceptedOutputRecordRef } from "./accepted_output.js";
import { buildPositionAuditToolStatusSummary } from "./helpers/position_audit.js";
import type {
  ComponentCalibrationRuntimeInput,
  CurrentPositionsSnapshot,
  Layer4Outputs,
  LlmCallRecord,
  MacroAgentOutput,
  MacroInputGateReceipt,
  PortfolioAction,
  PositionAudit,
  PositionReview,
  SectorAgentOutput,
  SuperinvestorOutput,
} from "./types.js";

export interface OutcomeRunSlot {
  schema_version: string;
  outcome_schedule_slot_id: string;
  outcome_schedule_slot_hash: string;
  outcome_schedule_plan_id: string;
  graph_run_id: string;
  agent_id: string;
  track_key_hash: string;
  run_slot_id: string;
  run_slot_kind: "OUTCOME_SCHEDULED" | "DOWNSTREAM_ONLY";
  scheduled_sample_id: string | null;
}

export interface OutcomeOpportunityBinding {
  agent_id: string;
  scheduled_sample_id: string;
  evaluation_opportunity_set_id: string;
  evaluation_opportunity_set_hash: string;
  frozen_object_set_id: string | null;
  frozen_object_set_hash: string | null;
  runtime_authority_binding?: OutcomeRuntimeAuthorityBinding;
  /** Runtime authority pins used to reject a changed candidate snapshot before extraction. */
  runtime_candidate_scope_hash?: string;
  runtime_candidate_universe_hash?: string;
  runtime_source_snapshot_hash?: string;
}

export interface OutcomeLiveSourceAuthorityBinding {
  source_tool_id:
    | "get_china_macro_snapshot"
    | "get_us_macro_snapshot"
    | "get_eu_macro_snapshot"
    | "get_central_bank_snapshot"
    | "get_us_financial_conditions_snapshot"
    | "get_euro_area_financial_conditions_snapshot"
    | "get_commodity_conditions_snapshot"
    | "get_geopolitical_events_snapshot"
    | "get_market_breadth_snapshot"
    | "get_market_positioning_snapshot"
    | "get_sector_research_snapshot"
    | "get_relationship_graph_snapshot";
  source_snapshot_hash: string;
  domain_hash: string;
}

export interface OutcomeDecisionRuntimeAuthorityBinding {
  source_tool_id:
    | "get_alpha_candidate_snapshot"
    | "get_cro_risk_snapshot"
    | "get_execution_snapshot"
    | "get_cio_decision_snapshot";
  source_snapshot_hash: string;
  candidate_scope_hash: string;
  candidate_universe_hash: string;
  upstream_accepted_output_refs_hash: string;
}

export type OutcomeRuntimeAuthorityBinding =
  | OutcomeLiveSourceAuthorityBinding
  | OutcomeDecisionRuntimeAuthorityBinding;

// ============================================================ Reducer functions

/** Generic last-write-wins reducer for scalar / nullable fields. */
export function replaceReducer<T>(_prev: T, next: T): T {
  return next;
}

/** Dict-merge reducer for ``Record<string, V>`` channels.
 *  Used by layer<N>_outputs (many agents writing concurrently into one map)
 *  and the memory contexts. New keys win on collision. */
export function dictMergeReducer<V>(
  prev: Record<string, V>,
  next: Record<string, V>,
): Record<string, V> {
  return { ...prev, ...next };
}

/** Per-key partial-update reducer for the Layer-4 quad. Each Layer-4 agent
 *  writes only its own key (cro / alpha_discovery / ...), the rest passes
 *  through unchanged. */
export function layer4Reducer(prev: Layer4Outputs, next: Partial<Layer4Outputs>): Layer4Outputs {
  return { ...prev, ...next };
}

/** Append reducer for the per-LLM-call ledger. */
export function appendReducer<T>(prev: T[], next: T[]): T[] {
  return [...prev, ...next];
}

/** Default factory for an empty Layer-4 quad (all four agents not-yet-written). */
export function emptyLayer4(): Layer4Outputs {
  return {
    cro: null,
    alpha_discovery: null,
    autonomous_execution: null,
    cio: null,
  };
}

export function emptyCurrentPositions(): CurrentPositionsSnapshot {
  return {
    snapshot_status: "empty_confirmed",
    position_source: "empty_confirmed",
    source_error_code: null,
    position_snapshot_hash: nullHash("empty_positions"),
    positions: [],
  };
}

export function emptyPositionAudit(): PositionAudit {
  const snapshot = emptyCurrentPositions();
  return {
    position_snapshot_hash: snapshot.position_snapshot_hash ?? null,
    snapshot_status: snapshot.snapshot_status,
    position_source: snapshot.position_source,
    source_error_code: snapshot.source_error_code,
    tool_status_summary: buildPositionAuditToolStatusSummary(snapshot),
    positions_loaded: 0,
    positions_reviewed: 0,
    positions_unreviewed: 0,
    runtime_safety_hold_count: 0,
    cash_weight: 1,
    gross_exposure: 0,
    net_exposure: 0,
    hold_count: 0,
    add_count: 0,
    reduce_count: 0,
    exit_count: 0,
    stale_thesis_count: 0,
    stop_loss_override_count: 0,
    target_current_drift_count: 0,
  };
}

function nullHash(label: string): string {
  return `sha256:${label}`;
}

// ============================================================ Annotation root

export const DailyCycleState = Annotation.Root({
  // ----- LangGraph built-in: per-call message threads. -----
  ...MessagesAnnotation.spec,

  // ----- Run identity (Plan §1, §9). -----
  active_cohort: Annotation<string>({
    reducer: replaceReducer,
    default: () => "cohort_default",
  }),
  /** ISO yyyy-mm-dd. Empty string ("") means live mode. */
  as_of_date: Annotation<string>({
    reducer: replaceReducer,
    default: () => "",
  }),
  mode: Annotation<"live" | "backtest">({
    reducer: replaceReducer,
    default: () => "live",
  }),
  /** Opaque correlation id for log/tracing across the 28-agent fan-out. */
  trace_id: Annotation<string>({
    reducer: replaceReducer,
    default: () => "",
  }),
  darwinian_runtime_binding: Annotation<DarwinianRuntimeBinding | null>({
    reducer: replaceReducer,
    default: () => null,
  }),
  darwinian_weight_snapshot: Annotation<DarwinianUsageWeightSnapshot | null>({
    reducer: replaceReducer,
    default: () => null,
  }),
  component_weight_snapshot: Annotation<ComponentWeightRuntimeSnapshot | null>({
    reducer: replaceReducer,
    default: () => null,
  }),
  outcome_schedule_plan: Annotation<{
    outcome_schedule_plan_id: string;
    outcome_schedule_plan_hash: string;
    schema_version: string;
    graph_run_id: string;
    production_variant_roster_id: string;
    production_variant_roster_revision_id: string;
    execution_behavior_release_id: string;
    cohort_id: string;
    language: "en" | "zh";
    as_of: string;
    prepared_at: string;
    slots: OutcomeRunSlot[];
  } | null>({
    reducer: replaceReducer,
    default: () => null,
  }),
  outcome_stage_skips: Annotation<
    Partial<Record<NoEvaluationObjectStageSkipAgentId, NoEvaluationObjectStageSkipRecord>>
  >({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),
  outcome_opportunity_bindings: Annotation<Record<string, OutcomeOpportunityBinding>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),
  accepted_output_refs: Annotation<Record<string, AcceptedOutputRecordRef>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),

  // ----- Memory contexts (sourced from Python AnalysisMemoryStore in 2D+). -----
  continuity_context: Annotation<Record<string, string>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),
  lesson_context: Annotation<Record<string, string>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),
  method_context: Annotation<Record<string, string>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),

  // ----- Layer 1 — 10 macro agents (Plan §5.1). -----
  layer1_outputs: Annotation<Record<string, MacroAgentOutput>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),
  component_calibration_inputs: Annotation<Record<string, ComponentCalibrationRuntimeInput>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),
  macro_input_gate: Annotation<MacroInputGateReceipt | null>({
    reducer: replaceReducer,
    default: () => null,
  }),

  // ----- Layer 2 — 10 sector agents (Plan v2 §2.2). -----
  layer2_outputs: Annotation<Record<string, SectorAgentOutput>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),
  // ----- Layer 3 — 4 superinvestor agents (Plan §5.3). -----
  layer3_outputs: Annotation<Record<string, SuperinvestorOutput>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),

  // ----- Layer 4 — 4 decision agents (Plan §5.4). -----
  layer4_outputs: Annotation<Layer4Outputs, Partial<Layer4Outputs>>({
    reducer: layer4Reducer,
    default: emptyLayer4,
  }),

  // ----- Position-aware daily loop state (Plan §12). -----
  current_positions: Annotation<CurrentPositionsSnapshot>({
    reducer: replaceReducer,
    default: emptyCurrentPositions,
  }),
  position_reviews: Annotation<PositionReview[]>({
    reducer: replaceReducer,
    default: () => [],
  }),
  position_audit: Annotation<PositionAudit>({
    reducer: replaceReducer,
    default: emptyPositionAudit,
  }),

  // ----- Final action surface (published only by shared validation). -----
  // ``replaceReducer`` matches the single-writer invariant: a validated final
  // target fully supersedes the previous channel value.
  portfolio_actions: Annotation<PortfolioAction[]>({
    reducer: replaceReducer,
    default: () => [],
  }),

  // ----- Deprecated replay provenance compatibility channel. -----
  // The canonical Layer-4 DAG has no asymmetric veto replay, so new runs leave
  // this false. Keep the field while stored run readers still expect it.
  replay_triggered: Annotation<boolean>({
    reducer: replaceReducer,
    default: () => false,
  }),

  // ----- Observability: per-LLM-call ledger (Plan §13). -----
  llm_calls: Annotation<LlmCallRecord[]>({
    reducer: appendReducer,
    default: () => [],
  }),
});

export type DailyCycleStateType = typeof DailyCycleState.State;
export type DailyCycleStateUpdate = typeof DailyCycleState.Update;

/**
 * MOSAIC daily-cycle state for LangGraph.js (Plan §5 + §11.2 Phase 2A design).
 *
 * Why per-layer maps instead of ETFAgents' flat-30-keys: 25 agents flat would
 * blow the state up to 40+ fields; aggregating per layer + dict-merge reducer
 * lets multiple agents inside one layer write concurrently without conflict
 * (LangGraph.js merges parallel branch updates via the channel reducer).
 *
 * Reducer choices:
 *   * ``layer<N>_outputs``     dict-merge ``{...prev, ...next}`` — many writers
 *   * ``layer<N>_consensus``   replace — single aggregator writer
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
  Layer4Outputs,
  LlmCallRecord,
  MacroAgentOutput,
  PortfolioAction,
  RegimeSignal,
  SectorAgentOutput,
  SectorConsensus,
  SuperinvestorOutput,
} from "./types.js";

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
  /** Opaque correlation id for log/tracing across the 25-agent fan-out. */
  trace_id: Annotation<string>({
    reducer: replaceReducer,
    default: () => "",
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
  layer1_consensus: Annotation<RegimeSignal | null>({
    reducer: replaceReducer,
    default: () => null,
  }),

  // ----- Layer 2 — 7 sector agents (Plan §5.2). -----
  layer2_outputs: Annotation<Record<string, SectorAgentOutput>>({
    reducer: dictMergeReducer,
    default: () => ({}),
  }),
  layer2_consensus: Annotation<SectorConsensus | null>({
    reducer: replaceReducer,
    default: () => null,
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

  // ----- Final action surface (CIO output, mirrored for downstream readers). -----
  portfolio_actions: Annotation<PortfolioAction[]>({
    reducer: replaceReducer,
    default: () => [],
  }),

  // ----- Observability: per-LLM-call ledger (Plan §13). -----
  llm_calls: Annotation<LlmCallRecord[]>({
    reducer: appendReducer,
    default: () => [],
  }),
});

export type DailyCycleStateType = typeof DailyCycleState.State;
export type DailyCycleStateUpdate = typeof DailyCycleState.Update;

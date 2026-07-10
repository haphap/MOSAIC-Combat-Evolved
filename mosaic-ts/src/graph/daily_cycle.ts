/**
 * Top-level daily cycle composite graph (Plan §11.2 sub-step 2E).
 *
 * Composes the 4 per-layer subgraphs into a single end-to-end pipeline:
 *
 *   START → layer1 → layer2 → layer3 → layer4 → END
 *
 * Per Plan §11.2 design decisions (revised after the first test run):
 *
 *   * **Wrapper-based subgraph nodes (revised from the original design)**:
 *     LangGraph.js v1's compiled subgraphs, when passed directly to
 *     ``addNode``, return their *full* output state. The parent's
 *     append reducers (llm_calls, messages) then double-count entries
 *     because ``[...prev, ...subgraph_full]`` re-includes everything
 *     the parent already had. We wrap each subgraph with
 *     ``invokeSubgraph`` which computes a delta for append-reducer
 *     channels and forwards dict-merge / replace channels verbatim
 *     (those reducers are idempotent under same-content updates).
 *   * Layer 4 owns the canonical alpha → CIO proposal → CRO → execution →
 *     CIO final → validators sequence. There is no asymmetric replay path;
 *     every executable target is reviewed by CRO exactly once.
 *
 * The CLI entry point lives in 2F (``cli/commands/daily-cycle.ts``);
 * this module is a pure factory.
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import {
  DailyCycleState,
  type DailyCycleStateType,
  type DailyCycleStateUpdate,
} from "../agents/state.js";
import type { BridgeApi, MosaicConfig } from "../bridge/index.js";
import type { LlmHandle } from "../llm/factory.js";
import { buildLayer1Graph } from "./layer1.js";
import { buildLayer2Graph } from "./layer2.js";
import { buildLayer3Graph } from "./layer3.js";
import { buildLayer4Graph } from "./layer4.js";

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface BuildDailyCycleGraphDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** @deprecated Retained for CLI compatibility; the canonical L4 DAG has no veto replay. */
  vetoThreshold?: number;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
}

export const DAILY_CYCLE_LAYER_NODES = ["layer1", "layer2", "layer3", "layer4"] as const;

/** Compiled-subgraph type. We rely on the structural ``invoke`` method
 *  rather than importing the heavy generic from ``@langchain/langgraph``. */
interface InvokeOnly {
  invoke: (state: DailyCycleStateType) => Promise<DailyCycleStateType>;
}

/**
 * Append-reducer channels in ``DailyCycleState`` (Plan §11.2 design decision
 * 2E #1). ``invokeSubgraph`` MUST slice these to a delta before forwarding
 * to the parent; otherwise the parent's appendReducer double-counts entries
 * already present in the subgraph's input state.
 *
 * If a new append-reducer channel is added to ``DailyCycleState``, append its
 * key here AND extend ``invokeSubgraph`` below. The ``satisfies`` clause
 * enforces every key resolves to ``ReadonlyArray<unknown>`` on the state
 * type so a non-array channel can't be added by mistake.
 */
const _APPEND_REDUCER_CHANNELS = ["messages", "llm_calls"] as const satisfies ReadonlyArray<
  keyof {
    [K in keyof DailyCycleStateType as DailyCycleStateType[K] extends ReadonlyArray<unknown>
      ? K
      : never]: DailyCycleStateType[K];
  }
>;

/**
 * Wrap a compiled subgraph as a parent-graph node, computing deltas for
 * append-reducer channels (``llm_calls``, ``messages``) so they don't
 * double-count when the subgraph's full output state flows back to the
 * parent's append reducer. Replace / dict-merge channels are forwarded
 * verbatim — those reducers are idempotent under same-content updates.
 *
 * IMPORTANT: when adding a new append-reducer channel to ``DailyCycleState``,
 * extend the explicit slice below. The ``APPEND_REDUCER_CHANNELS`` const
 * above is a documentation marker; TypeScript can't enforce that this
 * function handles every entry, so the convention is: same PR that adds
 * the channel must update both lists.
 */
function invokeSubgraph(
  subgraph: InvokeOnly,
): (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate> {
  return async (state) => {
    const result = await subgraph.invoke(state);
    const prevLlmLen = state.llm_calls?.length ?? 0;
    const prevMsgLen = state.messages?.length ?? 0;
    return {
      // ── append-reducer channels: must slice to delta (see APPEND_REDUCER_CHANNELS) ──
      // §14 R-T3: nullish-guard the slice — a subgraph that errored and
      // returned a partial state without these channels would otherwise NPE.
      messages: (result.messages ?? []).slice(prevMsgLen),
      llm_calls: (result.llm_calls ?? []).slice(prevLlmLen),
      // ── replace / dict-merge channels: idempotent under same-content updates ──
      layer1_outputs: result.layer1_outputs,
      layer1_consensus: result.layer1_consensus,
      layer2_outputs: result.layer2_outputs,
      layer2_consensus: result.layer2_consensus,
      layer3_outputs: result.layer3_outputs,
      layer4_outputs: result.layer4_outputs,
      current_positions: result.current_positions,
      position_reviews: result.position_reviews,
      position_audit: result.position_audit,
      portfolio_actions: result.portfolio_actions,
    } as DailyCycleStateUpdate;
  };
}

/** Build (and compile) the full 4-layer daily cycle graph. */
export function buildDailyCycleGraph(deps: BuildDailyCycleGraphDeps) {
  const l1 = buildLayer1Graph(deps);
  const l2 = buildLayer2Graph(deps);
  const l3 = buildLayer3Graph(deps);
  const l4 = buildLayer4Graph(deps);

  const graph = new StateGraph(DailyCycleState)
    .addNode("layer1", invokeSubgraph(l1 as InvokeOnly))
    .addNode("layer2", invokeSubgraph(l2 as InvokeOnly))
    .addNode("layer3", invokeSubgraph(l3 as InvokeOnly))
    .addNode("layer4", invokeSubgraph(l4 as InvokeOnly))
    .addEdge(START, "layer1")
    .addEdge("layer1", "layer2")
    .addEdge("layer2", "layer3")
    .addEdge("layer3", "layer4")
    .addEdge("layer4", END);

  return graph.compile();
}

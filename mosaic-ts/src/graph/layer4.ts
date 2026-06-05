/**
 * Layer-4 LangGraph subgraph (Plan §11.2 sub-step 2D.3).
 *
 * Topology is a deterministic serial chain:
 *
 *   START → cro → alpha_discovery → autonomous_execution → cio → END
 *
 * Dependency contract:
 *   * cro reads L1+L2+L3 first and writes risk objections.
 *   * alpha_discovery then reads the same upstream state plus CRO context.
 *   * autonomous_execution waits for CRO + alpha state.
 *   * cio is the final aggregator.
 *
 * Subgraph assumes Layer-1, Layer-2 and Layer-3 outputs are populated in
 * state. cio's output also writes ``state.portfolio_actions`` (top-level
 * convenience mirror handled by the factory).
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import { buildAlphaDiscoveryNode } from "../agents/decision/alpha_discovery.js";
import { buildAutonomousExecutionNode } from "../agents/decision/autonomous_execution.js";
import { buildCioNode } from "../agents/decision/cio.js";
import { buildCroNode } from "../agents/decision/cro.js";
import { DailyCycleState } from "../agents/state.js";
import type { BridgeApi, MosaicConfig } from "../bridge/index.js";
import type { LlmHandle } from "../llm/factory.js";
import { chainEdges, serialEdges } from "./_edges.js";

export interface BuildLayer4GraphDeps {
  llmHandle: LlmHandle;
  /** ``api`` is unused at runtime by L4 nodes, kept for symmetry. */
  api?: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
}

export const LAYER4_AGENT_NODES = [
  "cro",
  "alpha_discovery",
  "autonomous_execution",
  "cio",
] as const;

export const LAYER4_REPLAY_AGENT_NODES = [
  "alpha_discovery",
  "autonomous_execution",
  "cio",
] as const;

/** Build (and compile) the Layer-4 decision subgraph. */
export function buildLayer4Graph(deps: BuildLayer4GraphDeps) {
  const graph = new StateGraph(DailyCycleState)
    .addNode("cro", buildCroNode(deps))
    .addNode("alpha_discovery", buildAlphaDiscoveryNode(deps))
    .addNode("autonomous_execution", buildAutonomousExecutionNode(deps))
    .addNode("cio", buildCioNode(deps));

  // Serial L4: keep one LLM/tool stream active at a time.
  chainEdges(graph, serialEdges([START, ...LAYER4_AGENT_NODES, END] as const));

  return graph.compile();
}

/**
 * Layer-4 *replay* subgraph (Plan §11.2 sub-step 2E).
 *
 * Topology: START → alpha_discovery → autonomous_execution → cio → END.
 *
 * Used by the daily-cycle veto loop (max 1 replay): when the first L4
 * pass produced cro.rejected_picks > 50% of the L3 candidate pool, the
 * daily cycle re-runs alpha + auto_exec + cio (skipping cro — its
 * rejected_picks from the first pass remain in state and inform the
 * replay's alpha + auto_exec context).
 *
 * **Asymmetry vs buildLayer4Graph (intentional)**: the replay graph
 * deliberately omits the ``cro`` node so the topology can guarantee
 * max-1-replay (``layer4_replay → END`` is unconditional; if cro ran in
 * replay, a second veto could fire). Trade-off: if alpha_discovery
 * surfaces a *new* novel pick during replay, that ticker is never
 * adversarially reviewed by CRO. The implicit assumption is that the
 * replay's alpha is constrained by the first-pass cro context (renderer
 * surfaces rejected_picks + correlated_risks + black_swan_scenarios) and
 * tends toward consolidation, not exploration. Phase 3's scorecard will
 * track replay outcomes and surface this if it becomes a real risk.
 */
export function buildLayer4ReplayGraph(deps: BuildLayer4GraphDeps) {
  const graph = new StateGraph(DailyCycleState)
    .addNode("alpha_discovery", buildAlphaDiscoveryNode(deps))
    .addNode("autonomous_execution", buildAutonomousExecutionNode(deps))
    .addNode("cio", buildCioNode(deps));

  chainEdges(graph, serialEdges([START, ...LAYER4_REPLAY_AGENT_NODES, END] as const));

  return graph.compile();
}

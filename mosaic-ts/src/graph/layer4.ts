/**
 * Layer-4 LangGraph subgraph (Plan §11.2 sub-step 2D.3).
 *
 * Topology is a small DAG (NOT a simple parallel fan-out like Layer 1-3):
 *
 *   START ─┬→ cro ───────────────┐
 *          └→ alpha_discovery ───┴→ autonomous_execution → cio → END
 *
 * Dependency contract:
 *   * cro + alpha_discovery — both read L1+L2+L3, run in parallel.
 *   * autonomous_execution — waits for both cro + alpha (LangGraph
 *     superstep barrier handles this automatically when a node has
 *     multiple incoming edges).
 *   * cio — final aggregator, waits for autonomous_execution.
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

export interface BuildLayer4GraphDeps {
  llmHandle: LlmHandle;
  /** ``api`` is unused at runtime by L4 nodes, kept for symmetry. */
  api?: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
}

export const LAYER4_AGENT_NODES = [
  "cro",
  "alpha_discovery",
  "autonomous_execution",
  "cio",
] as const;

/** Build (and compile) the Layer-4 decision subgraph. */
export function buildLayer4Graph(deps: BuildLayer4GraphDeps) {
  // biome-ignore lint/suspicious/noExplicitAny: see graph/layer1.ts comment
  let graph: any = new StateGraph(DailyCycleState);
  graph = graph
    .addNode("cro", buildCroNode(deps))
    .addNode("alpha_discovery", buildAlphaDiscoveryNode(deps))
    .addNode("autonomous_execution", buildAutonomousExecutionNode(deps))
    .addNode("cio", buildCioNode(deps));

  // START → cro, alpha_discovery (parallel)
  graph = graph.addEdge(START, "cro").addEdge(START, "alpha_discovery");

  // cro, alpha_discovery → autonomous_execution (synchronisation point)
  graph = graph
    .addEdge("cro", "autonomous_execution")
    .addEdge("alpha_discovery", "autonomous_execution");

  // autonomous_execution → cio → END
  graph = graph.addEdge("autonomous_execution", "cio").addEdge("cio", END);

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
  // biome-ignore lint/suspicious/noExplicitAny: see graph/layer1.ts comment
  let graph: any = new StateGraph(DailyCycleState);
  graph = graph
    .addNode("alpha_discovery", buildAlphaDiscoveryNode(deps))
    .addNode("autonomous_execution", buildAutonomousExecutionNode(deps))
    .addNode("cio", buildCioNode(deps));

  graph = graph
    .addEdge(START, "alpha_discovery")
    .addEdge("alpha_discovery", "autonomous_execution")
    .addEdge("autonomous_execution", "cio")
    .addEdge("cio", END);

  return graph.compile();
}

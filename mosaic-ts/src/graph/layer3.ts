/**
 * Layer-3 LangGraph subgraph (Plan §11.2 sub-step 2D.2).
 *
 * Topology: START → druckenmiller → aschenbrenner → baker → ackman → END.
 * Assumes layer1_consensus + layer2_outputs are pre-populated.
 *
 * No Layer-3 aggregator — Layer-4's cio agent is the final aggregator
 * that consumes all 4 superinvestor outputs alongside cro / alpha_discovery /
 * autonomous_execution.
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import { DailyCycleState } from "../agents/state.js";
import { buildAckmanNode } from "../agents/superinvestor/ackman.js";
import { buildAschenbrennerNode } from "../agents/superinvestor/aschenbrenner.js";
import { buildBakerNode } from "../agents/superinvestor/baker.js";
import { buildDruckenmillerNode } from "../agents/superinvestor/druckenmiller.js";
import type { BridgeApi, MosaicConfig } from "../bridge/index.js";
import type { LlmHandle } from "../llm/factory.js";
import { chainEdges, serialEdges } from "./_edges.js";

export interface BuildLayer3GraphDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
}

export const LAYER3_AGENT_NODES = ["druckenmiller", "aschenbrenner", "baker", "ackman"] as const;

export function buildLayer3Graph(deps: BuildLayer3GraphDeps) {
  const graph = new StateGraph(DailyCycleState)
    .addNode("druckenmiller", buildDruckenmillerNode(deps))
    .addNode("aschenbrenner", buildAschenbrennerNode(deps))
    .addNode("baker", buildBakerNode(deps))
    .addNode("ackman", buildAckmanNode(deps));

  chainEdges(graph, serialEdges([START, ...LAYER3_AGENT_NODES, END] as const));
  return graph.compile();
}

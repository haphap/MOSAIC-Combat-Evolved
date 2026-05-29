/**
 * Layer-3 LangGraph subgraph (Plan §11.2 sub-step 2D.2).
 *
 * Topology: START → 4 superinvestor nodes (parallel) → END.
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

export interface BuildLayer3GraphDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
}

export const LAYER3_AGENT_NODES = ["druckenmiller", "aschenbrenner", "baker", "ackman"] as const;

export function buildLayer3Graph(deps: BuildLayer3GraphDeps) {
  // biome-ignore lint/suspicious/noExplicitAny: see graph/layer1.ts comment
  let graph: any = new StateGraph(DailyCycleState);
  graph = graph
    .addNode("druckenmiller", buildDruckenmillerNode(deps))
    .addNode("aschenbrenner", buildAschenbrennerNode(deps))
    .addNode("baker", buildBakerNode(deps))
    .addNode("ackman", buildAckmanNode(deps));

  for (const name of LAYER3_AGENT_NODES) {
    graph = graph.addEdge(START, name);
  }
  for (const name of LAYER3_AGENT_NODES) {
    graph = graph.addEdge(name, END);
  }
  return graph.compile();
}

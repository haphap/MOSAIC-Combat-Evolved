/**
 * Layer-2 LangGraph subgraph (Plan §11.2 sub-step 2D.1).
 *
 * Topology mirrors Layer-1 fan-out / fan-in:
 *
 *   START → 7 sector nodes (parallel) → END
 *
 * The subgraph assumes Layer-1 has already populated ``layer1_consensus``
 * and ``layer1_outputs.{china, institutional_flow}``. ``buildLayer1To2Graph``
 * chains the two subgraphs so the daily-cycle entry point can pump initial
 * state straight in.
 *
 * No Layer-2 aggregator yet — Plan §5.2 doesn't define one (each sector
 * agent's output is consumed independently by Layer-3 superinvestors).
 * ``state.layer2_consensus`` is reserved for a future top-sectors / cross-
 * sector summary if needed; currently null after this subgraph.
 *
 * 2D.2 will follow the same pattern with Layer-3 superinvestor nodes; 2E
 * stitches the four layer subgraphs into a single daily_cycle.ts entry.
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import { buildBiotechNode } from "../agents/sector/biotech.js";
import { buildConsumerNode } from "../agents/sector/consumer.js";
import { buildEnergyNode } from "../agents/sector/energy.js";
import { buildFinancialsNode } from "../agents/sector/financials.js";
import { buildIndustrialsNode } from "../agents/sector/industrials.js";
import { buildRelationshipMapperNode } from "../agents/sector/relationship_mapper.js";
import { buildSemiconductorNode } from "../agents/sector/semiconductor.js";
import { DailyCycleState } from "../agents/state.js";
import type { BridgeApi, MosaicConfig } from "../bridge/index.js";
import type { LlmHandle } from "../llm/factory.js";

export interface BuildLayer2GraphDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
}

export const LAYER2_AGENT_NODES = [
  "semiconductor",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "financials",
  "relationship_mapper",
] as const;

/** Build (and compile) the Layer-2 sector subgraph. */
export function buildLayer2Graph(deps: BuildLayer2GraphDeps) {
  // biome-ignore lint/suspicious/noExplicitAny: see graph/layer1.ts comment
  let graph: any = new StateGraph(DailyCycleState);
  graph = graph
    .addNode("semiconductor", buildSemiconductorNode(deps))
    .addNode("energy", buildEnergyNode(deps))
    .addNode("biotech", buildBiotechNode(deps))
    .addNode("consumer", buildConsumerNode(deps))
    .addNode("industrials", buildIndustrialsNode(deps))
    .addNode("financials", buildFinancialsNode(deps))
    .addNode("relationship_mapper", buildRelationshipMapperNode(deps));

  for (const name of LAYER2_AGENT_NODES) {
    graph = graph.addEdge(START, name);
  }
  for (const name of LAYER2_AGENT_NODES) {
    graph = graph.addEdge(name, END);
  }

  return graph.compile();
}

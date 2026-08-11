/**
 * Layer-2 LangGraph subgraph (Plan §11.2 sub-step 2D.1).
 *
 * Topology mirrors Layer-1's deterministic serial execution:
 *
 *   START → semiconductor → technology → energy → biotech → consumer
 *         → industrials → real_estate_construction → financials
 *         → agriculture → END
 *
 * The subgraph requires the ten accepted ``layer1_outputs`` and a READY
 * ``macro_input_gate``. Each consumer receives the ten independent Macro
 * transmissions plus authoritative usage shares; no Macro consensus exists.
 *
 * No Layer-2 aggregator yet — Plan §5.2 doesn't define one (each sector
 * agent's output is consumed independently by Layer-3 superinvestors).
 * Each standard Sector runs direction research and final selection, with one
 * conflict-only review when required.
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import { AcceptedAgentOutputStore } from "../agents/accepted_output.js";
import type { PromptReleaseLoadContext } from "../agents/prompts/release_prompt_loader.js";
import { buildAgricultureNode } from "../agents/sector/agriculture.js";
import { buildBiotechNode } from "../agents/sector/biotech.js";
import { buildConsumerNode } from "../agents/sector/consumer.js";
import { buildEnergyNode } from "../agents/sector/energy.js";
import { buildFinancialsNode } from "../agents/sector/financials.js";
import { buildIndustrialsNode } from "../agents/sector/industrials.js";
import { buildRealEstateConstructionNode } from "../agents/sector/real_estate_construction.js";
import { buildSemiconductorNode } from "../agents/sector/semiconductor.js";
import { buildTechnologyNode } from "../agents/sector/technology.js";
import { DailyCycleState } from "../agents/state.js";
import type { BridgeApi, MosaicConfig } from "../bridge/index.js";
import type { LlmHandle } from "../llm/factory.js";
import { chainEdges, serialEdges } from "./_edges.js";

export interface BuildLayer2GraphDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
  promptReleaseContext?: PromptReleaseLoadContext | null;
  acceptedOutputStore?: AcceptedAgentOutputStore;
}

export const LAYER2_AGENT_NODES = [
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
] as const;

/** Build (and compile) the Layer-2 sector subgraph. */
export function buildLayer2Graph(deps: BuildLayer2GraphDeps) {
  const acceptedOutputStore = deps.acceptedOutputStore ?? new AcceptedAgentOutputStore();
  const runDeps = { ...deps, acceptedOutputStore };
  const graph = new StateGraph(DailyCycleState)
    .addNode("semiconductor", buildSemiconductorNode(runDeps))
    .addNode("technology", buildTechnologyNode(runDeps))
    .addNode("energy", buildEnergyNode(runDeps))
    .addNode("biotech", buildBiotechNode(runDeps))
    .addNode("consumer", buildConsumerNode(runDeps))
    .addNode("industrials", buildIndustrialsNode(runDeps))
    .addNode("real_estate_construction", buildRealEstateConstructionNode(runDeps))
    .addNode("financials", buildFinancialsNode(runDeps))
    .addNode("agriculture", buildAgricultureNode(runDeps));

  chainEdges(graph, serialEdges([START, ...LAYER2_AGENT_NODES, END] as const));

  return graph.compile();
}

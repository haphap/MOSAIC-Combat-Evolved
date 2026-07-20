/**
 * Layer-1 LangGraph subgraph (Plan §11.2 sub-step 2C.3).
 *
 * Topology:
 *
 *   START → china → us_economy → eu_economy → central_bank
 *         → us_financial_conditions → euro_area_financial_conditions
 *         → commodities → geopolitical → market_breadth
 *         → institutional_flow → macro_input_gate → END
 *
 * The 10 macro nodes run serially in a deterministic order. This keeps one
 * LLM/tool call stream active at a time, avoiding provider rate-limit bursts
 * and Python bridge queue timeouts. State writes still converge through the
 * dict-merge reducer on ``layer1_outputs``.
 *
 * The daily-cycle graph continues from ``macro_input_gate`` into Layer 2.
 * There is no Macro stance or factor-bundle aggregation.
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import { AcceptedAgentOutputStore } from "../agents/accepted_output.js";
import { buildMacroInputGateNode } from "../agents/macro/_input_gate.js";
import { buildCentralBankNode } from "../agents/macro/central_bank.js";
import { buildChinaNode } from "../agents/macro/china.js";
import { buildCommoditiesNode } from "../agents/macro/commodities.js";
import { buildEuEconomyNode } from "../agents/macro/eu_economy.js";
import { buildEuroAreaFinancialConditionsNode } from "../agents/macro/euro_area_financial_conditions.js";
import { buildGeopoliticalNode } from "../agents/macro/geopolitical.js";
import { buildInstitutionalFlowNode } from "../agents/macro/institutional_flow.js";
import { buildMarketBreadthNode } from "../agents/macro/market_breadth.js";
import { buildUsEconomyNode } from "../agents/macro/us_economy.js";
import { buildUsFinancialConditionsNode } from "../agents/macro/us_financial_conditions.js";
import { DailyCycleState } from "../agents/state.js";
import type { BridgeApi, MosaicConfig } from "../bridge/index.js";
import type { LlmHandle } from "../llm/factory.js";
import { chainEdges, serialEdges } from "./_edges.js";

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface BuildLayer1GraphDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  /** Optional override LLM for the structured-output extractor stage (per
   *  agent factory's ``llmHandleStructured`` opt-in). */
  llmHandleStructured?: LlmHandle;
  /** Per-agent log channel forwarded into runAgentToolLoop. */
  onLog?: (msg: string) => void;
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
  acceptedOutputStore?: AcceptedAgentOutputStore;
}

/** Names of the 10 macro nodes in graph order. Exported for tests + 2D. */
export const LAYER1_AGENT_NODES = [
  "china",
  "us_economy",
  "eu_economy",
  "central_bank",
  "us_financial_conditions",
  "euro_area_financial_conditions",
  "commodities",
  "geopolitical",
  "market_breadth",
  "institutional_flow",
] as const;

// LangGraph forbids a node from sharing a name with a state channel.  The
// public state field remains `macro_input_gate`; this is only the internal
// graph-node identifier.
export const LAYER1_INPUT_GATE_NODE = "macro_input_gate_node" as const;

/** Build (and compile) the Layer-1 subgraph. */
export function buildLayer1Graph(deps: BuildLayer1GraphDeps) {
  const acceptedOutputStore = deps.acceptedOutputStore ?? new AcceptedAgentOutputStore();
  const runDeps = { ...deps, acceptedOutputStore };
  const graph = new StateGraph(DailyCycleState)
    .addNode("china", buildChinaNode(runDeps))
    .addNode("us_economy", buildUsEconomyNode(runDeps))
    .addNode("eu_economy", buildEuEconomyNode(runDeps))
    .addNode("central_bank", buildCentralBankNode(runDeps))
    .addNode("us_financial_conditions", buildUsFinancialConditionsNode(runDeps))
    .addNode("euro_area_financial_conditions", buildEuroAreaFinancialConditionsNode(runDeps))
    .addNode("commodities", buildCommoditiesNode(runDeps))
    .addNode("geopolitical", buildGeopoliticalNode(runDeps))
    .addNode("market_breadth", buildMarketBreadthNode(runDeps))
    .addNode("institutional_flow", buildInstitutionalFlowNode(runDeps))
    .addNode(LAYER1_INPUT_GATE_NODE, buildMacroInputGateNode(acceptedOutputStore));

  // Serial START → macro nodes → acceptance gate → END. The edge chain is derived
  // from LAYER1_AGENT_NODES so exported graph order and execution order stay aligned.
  chainEdges(
    graph,
    serialEdges([START, ...LAYER1_AGENT_NODES, LAYER1_INPUT_GATE_NODE, END] as const),
  );

  return graph.compile();
}

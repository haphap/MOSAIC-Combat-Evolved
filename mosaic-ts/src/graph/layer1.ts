/**
 * Layer-1 LangGraph subgraph (Plan §11.2 sub-step 2C.3).
 *
 * Topology:
 *
 *   START → central_bank → china → geopolitical → dollar → yield_curve
 *         → commodities → volatility → emerging_markets → news_sentiment
 *         → institutional_flow → aggregate_l1 → END
 *
 * The 10 macro nodes run serially in a deterministic order. This keeps one
 * LLM/tool call stream active at a time, avoiding provider rate-limit bursts
 * and Python bridge queue timeouts. State writes still converge through the
 * dict-merge reducer on ``layer1_outputs``.
 *
 * 2D will replace the ``aggregate_l1 → END`` edge with ``aggregate_l1 →
 * layer2_subgraph_entry`` so the daily cycle continues into Layer 2.
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import { buildAggregateLayer1Node } from "../agents/macro/_aggregator.js";
import { buildCentralBankNode } from "../agents/macro/central_bank.js";
import { buildChinaNode } from "../agents/macro/china.js";
import { buildCommoditiesNode } from "../agents/macro/commodities.js";
import { buildDollarNode } from "../agents/macro/dollar.js";
import { buildEmergingMarketsNode } from "../agents/macro/emerging_markets.js";
import { buildGeopoliticalNode } from "../agents/macro/geopolitical.js";
import { buildInstitutionalFlowNode } from "../agents/macro/institutional_flow.js";
import { buildNewsSentimentNode } from "../agents/macro/news_sentiment.js";
import { buildVolatilityNode } from "../agents/macro/volatility.js";
import { buildYieldCurveNode } from "../agents/macro/yield_curve.js";
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
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
}

/** Names of the 10 macro nodes in graph order. Exported for tests + 2D. */
export const LAYER1_AGENT_NODES = [
  "central_bank",
  "china",
  "geopolitical",
  "dollar",
  "yield_curve",
  "commodities",
  "volatility",
  "emerging_markets",
  "news_sentiment",
  "institutional_flow",
] as const;

export const LAYER1_AGGREGATOR_NODE = "aggregate_l1" as const;

/** Build (and compile) the Layer-1 subgraph. */
export function buildLayer1Graph(deps: BuildLayer1GraphDeps) {
  const graph = new StateGraph(DailyCycleState)
    .addNode("central_bank", buildCentralBankNode(deps))
    .addNode("china", buildChinaNode(deps))
    .addNode("geopolitical", buildGeopoliticalNode(deps))
    .addNode("dollar", buildDollarNode(deps))
    .addNode("yield_curve", buildYieldCurveNode(deps))
    .addNode("commodities", buildCommoditiesNode(deps))
    .addNode("volatility", buildVolatilityNode(deps))
    .addNode("emerging_markets", buildEmergingMarketsNode(deps))
    .addNode("news_sentiment", buildNewsSentimentNode(deps))
    .addNode("institutional_flow", buildInstitutionalFlowNode(deps))
    .addNode(LAYER1_AGGREGATOR_NODE, buildAggregateLayer1Node(deps));

  // Serial START → macro nodes → aggregator → END. The edge chain is derived
  // from LAYER1_AGENT_NODES so exported graph order and execution order stay aligned.
  chainEdges(
    graph,
    serialEdges([START, ...LAYER1_AGENT_NODES, LAYER1_AGGREGATOR_NODE, END] as const),
  );

  return graph.compile();
}

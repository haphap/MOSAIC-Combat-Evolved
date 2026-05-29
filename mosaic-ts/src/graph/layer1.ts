/**
 * Layer-1 LangGraph subgraph (Plan §11.2 sub-step 2C.3).
 *
 * Topology:
 *
 *   START ─┬→ central_bank ──┬→ aggregate_l1 → END
 *          ├→ china ─────────┤
 *          ├→ geopolitical ──┤
 *          ├→ dollar ────────┤
 *          ├→ yield_curve ───┤
 *          ├→ commodities ───┤
 *          ├→ volatility ────┤
 *          ├→ emerging_markets ┤
 *          ├→ news_sentiment ┤
 *          └→ institutional_flow ─┘
 *
 * LangGraph fans out automatically when a node has multiple outgoing edges
 * with no conditional gate; the 10 macro nodes run concurrently and the
 * aggregator runs after all of them finish (LangGraph waits on the
 * superstep barrier). State writes converge through the dict-merge reducer
 * on ``layer1_outputs``.
 *
 * 2D will replace the ``aggregate_l1 → END`` edge with ``aggregate_l1 →
 * layer2_subgraph_entry`` so the daily cycle continues into Layer 2.
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import { aggregateLayer1Node } from "../agents/macro/_aggregator.js";
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
  // LangGraph's StateGraph fluent type narrows on every .addNode() / .addEdge()
  // call; we accumulate edges in a loop where each .addEdge() returns a
  // differently-typed builder. Erasing to `any` for the chain — the compiled
  // graph at the end is what the tests exercise; intermediate fluent shape is
  // incidental.
  // biome-ignore lint/suspicious/noExplicitAny: see comment above
  let graph: any = new StateGraph(DailyCycleState);

  graph = graph
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
    .addNode(LAYER1_AGGREGATOR_NODE, aggregateLayer1Node);

  // Fan-out: START → all 10 macro nodes (concurrent).
  for (const name of LAYER1_AGENT_NODES) {
    graph = graph.addEdge(START, name);
  }

  // Fan-in: each macro node → aggregator.
  for (const name of LAYER1_AGENT_NODES) {
    graph = graph.addEdge(name, LAYER1_AGGREGATOR_NODE);
  }

  // Aggregator → END (replaced in 2D when Layer 2 lands).
  graph = graph.addEdge(LAYER1_AGGREGATOR_NODE, END);

  return graph.compile();
}

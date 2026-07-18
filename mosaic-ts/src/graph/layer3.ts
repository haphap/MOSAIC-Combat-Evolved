/**
 * Layer-3 LangGraph subgraph (Plan §11.2 sub-step 2D.2).
 *
 * Topology: START → druckenmiller → munger → burry → ackman → END.
 * Assumes the ten accepted Macro outputs, READY macro gate, and ten accepted
 * Sector/relationship outputs are pre-populated.
 *
 * No Layer-3 aggregator — Layer-4's cio agent is the final aggregator
 * that consumes all 4 superinvestor outputs alongside cro / alpha_discovery /
 * autonomous_execution.
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import { AcceptedAgentOutputStore } from "../agents/accepted_output.js";
import { AGENTS_BY_LAYER } from "../agents/prompts/cohorts.js";
import {
  DailyCycleState,
  type DailyCycleStateType,
  type DailyCycleStateUpdate,
} from "../agents/state.js";
import { buildAckmanNode } from "../agents/superinvestor/ackman.js";
import { buildBurryNode } from "../agents/superinvestor/burry.js";
import { buildDruckenmillerNode } from "../agents/superinvestor/druckenmiller.js";
import { buildMungerNode } from "../agents/superinvestor/munger.js";
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
  acceptedOutputStore?: AcceptedAgentOutputStore;
}

export const LAYER3_AGENT_NODES = AGENTS_BY_LAYER.superinvestor;

export function buildLayer3Graph(deps: BuildLayer3GraphDeps) {
  const acceptedOutputStore = deps.acceptedOutputStore ?? new AcceptedAgentOutputStore();
  const runDeps = { ...deps, acceptedOutputStore };
  const graph = new StateGraph(DailyCycleState)
    .addNode(
      "druckenmiller",
      withOutcomeStageSkip("druckenmiller", buildDruckenmillerNode(runDeps)),
    )
    .addNode("munger", withOutcomeStageSkip("munger", buildMungerNode(runDeps)))
    .addNode("burry", withOutcomeStageSkip("burry", buildBurryNode(runDeps)))
    .addNode("ackman", withOutcomeStageSkip("ackman", buildAckmanNode(runDeps)));

  chainEdges(graph, serialEdges([START, ...LAYER3_AGENT_NODES, END] as const));
  return graph.compile();
}

function withOutcomeStageSkip(
  agentId: "druckenmiller" | "munger" | "burry" | "ackman",
  node: (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>,
): (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate> {
  return async (state) => {
    if (state.outcome_stage_skips[agentId]) return {};
    return node(state);
  };
}

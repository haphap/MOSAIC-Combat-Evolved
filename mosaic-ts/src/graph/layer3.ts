/**
 * Layer-3 LangGraph subgraph (Plan §11.2 sub-step 2D.2).
 *
 * Each scheduled Agent is preceded by a server-authoritative opportunity freeze
 * after all required upstream accepted outputs exist.
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
import {
  type SuperinvestorAgentId,
  superinvestorAcceptedSnapshotRefs,
} from "../agents/superinvestor/_factory.js";
import { buildAckmanNode } from "../agents/superinvestor/ackman.js";
import { buildBurryNode } from "../agents/superinvestor/burry.js";
import { buildDruckenmillerNode } from "../agents/superinvestor/druckenmiller.js";
import { buildMungerNode } from "../agents/superinvestor/munger.js";
import { parseOutcomeStageSkips } from "../autoresearch/outcome_stage_skip.js";
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
      "druckenmiller_opportunity_freeze",
      buildSuperinvestorOpportunityFreezeNode("druckenmiller", runDeps),
    )
    .addNode(
      "druckenmiller",
      withOutcomeStageSkip("druckenmiller", buildDruckenmillerNode(runDeps)),
    )
    .addNode(
      "munger_opportunity_freeze",
      buildSuperinvestorOpportunityFreezeNode("munger", runDeps),
    )
    .addNode("munger", withOutcomeStageSkip("munger", buildMungerNode(runDeps)))
    .addNode("burry_opportunity_freeze", buildSuperinvestorOpportunityFreezeNode("burry", runDeps))
    .addNode("burry", withOutcomeStageSkip("burry", buildBurryNode(runDeps)))
    .addNode(
      "ackman_opportunity_freeze",
      buildSuperinvestorOpportunityFreezeNode("ackman", runDeps),
    )
    .addNode("ackman", withOutcomeStageSkip("ackman", buildAckmanNode(runDeps)));

  chainEdges(
    graph,
    serialEdges([
      START,
      "druckenmiller_opportunity_freeze",
      "druckenmiller",
      "munger_opportunity_freeze",
      "munger",
      "burry_opportunity_freeze",
      "burry",
      "ackman_opportunity_freeze",
      "ackman",
      END,
    ] as const),
  );
  return graph.compile();
}

function buildSuperinvestorOpportunityFreezeNode(
  agentId: SuperinvestorAgentId,
  deps: BuildLayer3GraphDeps,
): (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate> {
  return async (state) => {
    if (!state.darwinian_runtime_binding) return {};
    const schedule = state.outcome_schedule_plan;
    if (!schedule) throw new Error(`${agentId}: outcome schedule is unavailable`);
    const slots = schedule.slots.filter((slot) => slot.agent_id === agentId);
    if (slots.length !== 1) {
      throw new Error(`${agentId}: outcome schedule slot is ambiguous`);
    }
    const slot = slots[0];
    if (!slot) throw new Error(`${agentId}: outcome schedule slot is unavailable`);
    if (slot.run_slot_kind === "DOWNSTREAM_ONLY") return {};
    if (!slot.scheduled_sample_id) {
      throw new Error(`${agentId}: scheduled sample ID is missing`);
    }
    const acceptedOutputRefs = superinvestorAcceptedSnapshotRefs(state).map((ref) => ({
      ...ref,
    }));
    if (acceptedOutputRefs.length === 0) {
      throw new Error(`${agentId}: upstream accepted-output refs are unavailable`);
    }
    const result = await deps.api.darwinianFreezeSuperinvestorOutcomeOpportunity({
      outcome_schedule_plan_id: schedule.outcome_schedule_plan_id,
      scheduled_sample_id: slot.scheduled_sample_id,
      agent_id: agentId,
      recorded_at: schedule.prepared_at,
      accepted_output_refs: acceptedOutputRefs,
    });
    if (!result.run_allowed && !result.stage_skip) {
      throw new Error(`${agentId}: ${result.blocker_reason ?? "stage opportunity unavailable"}`);
    }
    const evaluationId = requiredText(
      result.evaluation_opportunity_set_id,
      `${agentId}.evaluation_opportunity_set_id`,
    );
    const evaluationHash = requiredSha256(
      result.evaluation_opportunity_set_hash,
      `${agentId}.evaluation_opportunity_set_hash`,
    );
    const frozenId = requiredText(result.frozen_object_set_id, `${agentId}.frozen_object_set_id`);
    const frozenHash = requiredSha256(
      result.frozen_object_set_hash,
      `${agentId}.frozen_object_set_hash`,
    );
    const candidateScopeHash = requiredSha256(
      result.runtime_candidate_scope_hash,
      `${agentId}.runtime_candidate_scope_hash`,
    );
    const candidateUniverseHash = requiredSha256(
      result.runtime_candidate_universe_hash,
      `${agentId}.runtime_candidate_universe_hash`,
    );
    const sourceSnapshotHash = requiredSha256(
      result.runtime_source_snapshot_hash,
      `${agentId}.runtime_source_snapshot_hash`,
    );
    if (candidateUniverseHash !== frozenHash) {
      throw new Error(`${agentId}: frozen candidate universe hash mismatch`);
    }
    const stageSkips = result.stage_skip
      ? parseOutcomeStageSkips({ [agentId]: result.stage_skip })
      : {};
    return {
      outcome_opportunity_bindings: {
        [agentId]: {
          agent_id: agentId,
          scheduled_sample_id: slot.scheduled_sample_id,
          evaluation_opportunity_set_id: evaluationId,
          evaluation_opportunity_set_hash: evaluationHash,
          frozen_object_set_id: frozenId,
          frozen_object_set_hash: frozenHash,
          runtime_candidate_scope_hash: candidateScopeHash,
          runtime_candidate_universe_hash: candidateUniverseHash,
          runtime_source_snapshot_hash: sourceSnapshotHash,
        },
      },
      ...(Object.keys(stageSkips).length > 0 ? { outcome_stage_skips: stageSkips } : {}),
    };
  };
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

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value.trim();
}

function requiredSha256(value: unknown, label: string): string {
  const normalized = requiredText(value, label);
  if (!/^sha256:[0-9a-f]{64}$/.test(normalized)) {
    throw new Error(`${label} must be lowercase sha256`);
  }
  return normalized;
}

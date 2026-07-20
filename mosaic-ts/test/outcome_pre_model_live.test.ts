import { describe, expect, it, vi } from "vitest";
import {
  assertLiveOutcomeSourceSnapshot,
  freezeLiveOutcomeOpportunity,
  LIVE_SOURCE_TOOL_BY_AGENT,
  liveOutcomeCapabilityRuntimeInput,
} from "../src/agents/helpers/outcome_pre_model.js";
import { buildChinaNode } from "../src/agents/macro/china.js";
import { buildEnergyNode } from "../src/agents/sector/energy.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { BridgeApi } from "../src/bridge/index.js";

const sha = (character: string) => `sha256:${character.repeat(64)}`;

function scheduledState(agentId: string): DailyCycleStateType {
  return {
    trace_id: "graph-live-freeze",
    darwinian_runtime_binding: {} as DailyCycleStateType["darwinian_runtime_binding"],
    outcome_schedule_plan: {
      outcome_schedule_plan_id: "plan-live-freeze",
      outcome_schedule_plan_hash: sha("1"),
      schema_version: "outcome_schedule_plan_v2",
      graph_run_id: "graph-live-freeze",
      production_variant_roster_id: "roster-live-freeze",
      production_variant_roster_revision_id: "revision-live-freeze",
      execution_behavior_release_id: "release-live-freeze",
      cohort_id: "cohort_default",
      language: "zh",
      as_of: "2026-07-20T09:00:00+08:00",
      prepared_at: "2026-07-20T09:00:00+08:00",
      slots: [
        {
          schema_version: "outcome_schedule_slot_v2",
          outcome_schedule_slot_id: `slot:${agentId}`,
          outcome_schedule_slot_hash: sha("2"),
          outcome_schedule_plan_id: "plan-live-freeze",
          graph_run_id: "graph-live-freeze",
          agent_id: agentId,
          track_key_hash: sha("3"),
          run_slot_id: `run-slot:${agentId}`,
          run_slot_kind: "OUTCOME_SCHEDULED",
          scheduled_sample_id: `sample:${agentId}`,
        },
      ],
    },
    outcome_opportunity_bindings: {},
  } as DailyCycleStateType;
}

describe.each(
  Object.entries(LIVE_SOURCE_TOOL_BY_AGENT),
)("%s live outcome pre-model authority", (agentId, sourceToolId) => {
  it("freezes and propagates the exact three-field source binding", async () => {
    const authority = {
      source_tool_id: sourceToolId,
      source_snapshot_hash: sha("4"),
      domain_hash: sha("5"),
    };
    const freeze = vi.fn(async () => ({
      run_allowed: true,
      scheduled_sample_id: `sample:${agentId}`,
      evaluation_opportunity_set_id: `opportunity:${agentId}`,
      evaluation_opportunity_set_hash: sha("6"),
      frozen_object_set_id: null,
      frozen_object_set_hash: null,
      runtime_authority_binding: authority,
    }));
    const result = await freezeLiveOutcomeOpportunity({
      api: { darwinianFreezeOutcomeOpportunity: freeze } as unknown as BridgeApi,
      state: scheduledState(agentId),
      agentId: agentId as keyof typeof LIVE_SOURCE_TOOL_BY_AGENT,
    });

    expect(freeze).toHaveBeenCalledOnce();
    expect(result.state.outcome_opportunity_bindings[agentId]?.runtime_authority_binding).toEqual(
      authority,
    );
    expect(result.update?.outcome_opportunity_bindings[agentId]).toEqual(
      result.state.outcome_opportunity_bindings[agentId],
    );
    expect(
      liveOutcomeCapabilityRuntimeInput(
        result.state,
        agentId as keyof typeof LIVE_SOURCE_TOOL_BY_AGENT,
      ),
    ).toEqual({ outcome_opportunity_authority: authority });
    expect(() =>
      assertLiveOutcomeSourceSnapshot({
        state: result.state,
        agentId: agentId as keyof typeof LIVE_SOURCE_TOOL_BY_AGENT,
        sourceToolId,
        sourceSnapshotHash: sha("7"),
      }),
    ).toThrow("model tool snapshot differs from live opportunity freeze");
  });
});

it.each([
  ["Macro", buildChinaNode, "china"],
  ["Sector", buildEnergyNode, "energy"],
] as const)("%s factory blocks at live freeze before prompt or model work", async (_layer, build, agentId) => {
  const freeze = vi.fn(async () => ({
    run_allowed: false,
    blocker_reason: "SOURCE_AUTHORITY_MISMATCH",
    scheduled_sample_id: `sample:${agentId}`,
  }));
  const node = build({
    api: { darwinianFreezeOutcomeOpportunity: freeze } as unknown as BridgeApi,
    llmHandle: undefined as never,
    config: undefined as never,
    promptsRoot: "/path/that/must/not/be-read",
  });

  await expect(node(scheduledState(agentId))).rejects.toThrow(
    `${agentId}: live opportunity freeze blocked: SOURCE_AUTHORITY_MISMATCH`,
  );
  expect(freeze).toHaveBeenCalledOnce();
});

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { AcceptedAgentOutputStore } from "../src/agents/accepted_output.js";
import { buildMacroInputGateNode } from "../src/agents/macro/_input_gate.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
import {
  checkpointCommitStageForNode,
  checkpointedStageNode,
  DailyCycleCheckpoint,
  type DailyCycleCheckpointIdentity,
} from "../src/graph/daily_cycle_checkpoint.js";
import { validateFinalTargetNode } from "../src/graph/layer4.js";

const CHECKPOINT_STAGES = ["stage_a", "stage_b"] as const;
const checkpointRoots: string[] = [];

function makeIdentity(): DailyCycleCheckpointIdentity {
  return {
    cycle_kind: "STRUCTURED_SMOKE",
    as_of_date: "2025-06-17",
    cohort: "cohort_default",
    stage_roster: CHECKPOINT_STAGES,
    graph_contract: "daily-cycle-test-graph-v1",
    prompt_release: "test-prompt-release",
    prompt_content_hash: `sha256:${"d".repeat(64)}`,
    prompt_contract: `sha256:${"a".repeat(64)}`,
    fixture_bundle_hash: `sha256:${"b".repeat(64)}`,
    current_positions_hash: `sha256:${"c".repeat(64)}`,
  };
}

function makeState(): DailyCycleStateType {
  return {
    messages: [],
    active_cohort: "cohort_default",
    as_of_date: "2025-06-17",
    mode: "live",
    trace_id: "checkpoint-test-run",
    darwinian_runtime_binding: null,
    darwinian_weight_snapshot: null,
    component_weight_snapshot: null,
    outcome_schedule_plan: null,
    outcome_stage_skips: {},
    outcome_opportunity_bindings: {},
    accepted_output_refs: {},
    continuity_context: {},
    lesson_context: {},
    method_context: {},
    layer1_outputs: {},
    component_calibration_inputs: {},
    macro_input_gate: null,
    layer2_outputs: {},
    layer3_outputs: {},
    layer4_outputs: {
      cro: null,
      alpha_discovery: null,
      autonomous_execution: null,
      cio: null,
    },
    current_positions: {
      snapshot_status: "empty_confirmed",
      position_source: "empty_confirmed",
      source_error_code: null,
      position_snapshot_hash: "sha256:positions",
      positions: [],
    },
    position_reviews: [],
    position_audit: {} as DailyCycleStateType["position_audit"],
    portfolio_actions: [],
    replay_triggered: false,
    llm_calls: [],
  };
}

function updateForStage(stageId: string, state: DailyCycleStateType): DailyCycleStateUpdate {
  return {
    continuity_context: {
      ...state.continuity_context,
      [stageId]: `output:${stageId};hash:sha256:${stageId};lineage:${stageId}-accepted`,
    },
  };
}

async function runStage(
  stageId: (typeof CHECKPOINT_STAGES)[number],
  state: DailyCycleStateType,
  checkpoint: DailyCycleCheckpoint,
  store: AcceptedAgentOutputStore,
  calls: Record<string, number>,
): Promise<DailyCycleStateType> {
  const node = checkpointedStageNode(
    stageId,
    async (current) => {
      calls[stageId] = (calls[stageId] ?? 0) + 1;
      return updateForStage(stageId, current);
    },
    checkpoint,
  );
  const update = await node(state);
  const next = {
    ...state,
    continuity_context: update.continuity_context ?? state.continuity_context,
  } as DailyCycleStateType;
  checkpoint.commit(stageId, next, store);
  return next;
}

afterEach(() => {
  for (const root of checkpointRoots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("daily-cycle Agent-stage checkpoint", () => {
  it("resumes only the interrupted stage and preserves the uninterrupted lineage", async () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-daily-cycle-checkpoint-"));
    checkpointRoots.push(root);
    const path = join(root, "checkpoint.json");
    const identity = makeIdentity();
    const store = new AcceptedAgentOutputStore();
    const first = DailyCycleCheckpoint.open({ path, identity });
    if (!first) throw new Error("expected a fresh checkpoint");
    const firstCalls: Record<string, number> = {};
    let state = await runStage("stage_a", makeState(), first, store, firstCalls);

    const interrupted = checkpointedStageNode(
      "stage_b",
      async () => {
        firstCalls.stage_b = (firstCalls.stage_b ?? 0) + 1;
        throw new Error("controlled interruption");
      },
      first,
    );
    await expect(interrupted(state)).rejects.toThrow("controlled interruption");
    expect(first.completedStages).toEqual(["stage_a"]);
    expect(JSON.parse(readFileSync(path, "utf-8")).completed_stages).toEqual(["stage_a"]);

    const resumed = DailyCycleCheckpoint.open({ path, resume: true, identity });
    if (!resumed) throw new Error("expected a resumed checkpoint");
    const resumedStore = new AcceptedAgentOutputStore();
    resumed.restoreAcceptedOutputStore(resumedStore);
    const resumedCalls: Record<string, number> = {};
    state = resumed.restoredState as DailyCycleStateType;
    state = await runStage("stage_a", state, resumed, resumedStore, resumedCalls);
    state = await runStage("stage_b", state, resumed, resumedStore, resumedCalls);

    const uninterruptedPath = join(root, "uninterrupted.json");
    const uninterrupted = DailyCycleCheckpoint.open({ path: uninterruptedPath, identity });
    if (!uninterrupted) throw new Error("expected an uninterrupted checkpoint");
    const uninterruptedStore = new AcceptedAgentOutputStore();
    const uninterruptedCalls: Record<string, number> = {};
    let uninterruptedState = await runStage(
      "stage_a",
      makeState(),
      uninterrupted,
      uninterruptedStore,
      uninterruptedCalls,
    );
    uninterruptedState = await runStage(
      "stage_b",
      uninterruptedState,
      uninterrupted,
      uninterruptedStore,
      uninterruptedCalls,
    );

    expect(firstCalls).toEqual({ stage_a: 1, stage_b: 1 });
    expect(resumedCalls).toEqual({ stage_b: 1 });
    expect(resumed.completedStages).toEqual([...CHECKPOINT_STAGES]);
    expect(state).toEqual(uninterruptedState);
    expect(resumed.restoredState).toEqual(uninterruptedState);
    expect(JSON.parse(readFileSync(path, "utf-8")).latest.state.continuity_context).toEqual(
      uninterruptedState.continuity_context,
    );
  });

  it("does not complete institutional_flow or cio_final before their barriers succeed", async () => {
    expect(checkpointCommitStageForNode("institutional_flow")).toBeNull();
    expect(checkpointCommitStageForNode("macro_input_gate_node")).toBe("institutional_flow");
    expect(checkpointCommitStageForNode("cio_final")).toBeNull();
    expect(checkpointCommitStageForNode("shared_validation")).toBe("cio_final");

    const root = mkdtempSync(join(tmpdir(), "mosaic-daily-cycle-checkpoint-barrier-"));
    checkpointRoots.push(root);
    const inputGateCheckpoint = DailyCycleCheckpoint.open({
      path: join(root, "input-gate.json"),
      identity: { ...makeIdentity(), stage_roster: ["institutional_flow"] },
    });
    if (!inputGateCheckpoint) throw new Error("expected a fresh input-gate checkpoint");
    const inputGate = checkpointedStageNode(
      "institutional_flow",
      buildMacroInputGateNode(),
      inputGateCheckpoint,
    );
    await expect(inputGate(makeState())).rejects.toThrow("macro_input_gate requires exactly");
    expect(inputGateCheckpoint.completedStages).toEqual([]);

    const sharedValidationCheckpoint = DailyCycleCheckpoint.open({
      path: join(root, "shared-validation.json"),
      identity: { ...makeIdentity(), stage_roster: ["cio_final"] },
    });
    if (!sharedValidationCheckpoint)
      throw new Error("expected a fresh shared-validation checkpoint");
    const sharedValidation = checkpointedStageNode(
      "cio_final",
      validateFinalTargetNode,
      sharedValidationCheckpoint,
    );
    await expect(sharedValidation(makeState())).rejects.toThrow(
      "shared_validation requires cio_final output",
    );
    expect(sharedValidationCheckpoint.completedStages).toEqual([]);
  });

  it("rejects partial writes and every identity drift before graph execution", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-daily-cycle-checkpoint-"));
    checkpointRoots.push(root);
    const identity = makeIdentity();
    const partialPath = join(root, "partial.json");
    writeFileSync(
      partialPath,
      '{"schema_version":"daily_cycle_agent_stage_checkpoint_v2"',
      "utf-8",
    );
    expect(() => DailyCycleCheckpoint.open({ path: partialPath, resume: true, identity })).toThrow(
      /unreadable|partially written/,
    );

    const validPath = join(root, "valid.json");
    const checkpoint = DailyCycleCheckpoint.open({ path: validPath, identity });
    if (!checkpoint) throw new Error("expected a fresh checkpoint");
    checkpoint.commit("stage_a", makeState(), new AcceptedAgentOutputStore());
    expect(() =>
      DailyCycleCheckpoint.open({
        path: validPath,
        resume: true,
        identity: { ...identity, prompt_content_hash: `sha256:${"e".repeat(64)}` },
      }),
    ).toThrow("identity drift");
  });
});

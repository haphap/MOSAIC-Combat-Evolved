import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { AcceptedAgentOutputStore } from "../src/agents/accepted_output.js";
import { buildMacroInputGateNode } from "../src/agents/macro/_input_gate.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
import { DAILY_CYCLE_STAGE_ROSTER } from "../src/cli/commands/daily-cycle.js";
import {
  checkpointCommitStageForNode,
  checkpointedStageNode,
  DailyCycleCheckpoint,
} from "../src/graph/daily_cycle_checkpoint.js";
import { validateFinalTargetNode } from "../src/graph/layer4.js";

const CHECKPOINT_STAGES = ["stage_a", "stage_b"] as const;
const CHECKPOINT_INPUT = {
  asOfDate: "2025-06-17",
  cohort: "cohort_default",
  stageRoster: CHECKPOINT_STAGES,
} as const;
const checkpointRoots: string[] = [];

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
    const store = new AcceptedAgentOutputStore();
    const first = DailyCycleCheckpoint.open({ path, ...CHECKPOINT_INPUT });
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

    const resumed = DailyCycleCheckpoint.open({ path, resume: true, ...CHECKPOINT_INPUT });
    if (!resumed) throw new Error("expected a resumed checkpoint");
    const resumedStore = new AcceptedAgentOutputStore();
    resumed.restoreAcceptedOutputStore(resumedStore);
    const resumedCalls: Record<string, number> = {};
    state = resumed.restoredState as DailyCycleStateType;
    state = await runStage("stage_a", state, resumed, resumedStore, resumedCalls);
    state = await runStage("stage_b", state, resumed, resumedStore, resumedCalls);

    const uninterruptedPath = join(root, "uninterrupted.json");
    const uninterrupted = DailyCycleCheckpoint.open({
      path: uninterruptedPath,
      ...CHECKPOINT_INPUT,
    });
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
    expect(JSON.parse(readFileSync(path, "utf-8")).state.continuity_context).toEqual(
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
      ...CHECKPOINT_INPUT,
      stageRoster: ["institutional_flow"],
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
      ...CHECKPOINT_INPUT,
      stageRoster: ["cio_final"],
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

  it("rejects partial writes, another day or cohort, and an invalid stage prefix", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-daily-cycle-checkpoint-"));
    checkpointRoots.push(root);
    const partialPath = join(root, "partial.json");
    writeFileSync(partialPath, '{"completed_stages":', "utf-8");
    expect(() =>
      DailyCycleCheckpoint.open({ path: partialPath, resume: true, ...CHECKPOINT_INPUT }),
    ).toThrow(/unreadable|partially written/);

    const validPath = join(root, "valid.json");
    const checkpoint = DailyCycleCheckpoint.open({ path: validPath, ...CHECKPOINT_INPUT });
    if (!checkpoint) throw new Error("expected a fresh checkpoint");
    checkpoint.commit("stage_a", makeState(), new AcceptedAgentOutputStore());
    expect(() =>
      DailyCycleCheckpoint.open({
        path: validPath,
        resume: true,
        ...CHECKPOINT_INPUT,
        asOfDate: "2025-06-18",
      }),
    ).toThrow("checkpoint date does not match --date");
    expect(() =>
      DailyCycleCheckpoint.open({
        path: validPath,
        resume: true,
        ...CHECKPOINT_INPUT,
        cohort: "cohort_crisis",
      }),
    ).toThrow("checkpoint cohort does not match --cohort");

    const invalidPrefix = JSON.parse(readFileSync(validPath, "utf-8"));
    invalidPrefix.completed_stages = ["stage_b"];
    writeFileSync(validPath, JSON.stringify(invalidPrefix), "utf-8");
    expect(() =>
      DailyCycleCheckpoint.open({ path: validPath, resume: true, ...CHECKPOINT_INPUT }),
    ).toThrow("checkpoint completed stage prefix is invalid");
  });

  it("restores a 21-stage prefix", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-daily-cycle-checkpoint-prefix-"));
    checkpointRoots.push(root);
    const path = join(root, "checkpoint.json");
    const checkpoint = DailyCycleCheckpoint.open({
      path,
      ...CHECKPOINT_INPUT,
      stageRoster: DAILY_CYCLE_STAGE_ROSTER,
    });
    if (!checkpoint) throw new Error("expected a fresh checkpoint");
    const acceptedPrefix = DAILY_CYCLE_STAGE_ROSTER.slice(0, 21);
    for (const stageId of acceptedPrefix) {
      checkpoint.commit(stageId, makeState(), new AcceptedAgentOutputStore());
    }

    const resumed = DailyCycleCheckpoint.open({
      path,
      resume: true,
      ...CHECKPOINT_INPUT,
      stageRoster: DAILY_CYCLE_STAGE_ROSTER,
    });
    if (!resumed) throw new Error("expected a resumed checkpoint");
    expect(resumed.completedStages).toEqual(acceptedPrefix);
    expect(resumed.completedStages.at(-1)).toBe("ackman");
  });
});

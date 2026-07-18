import { describe, expect, it, vi } from "vitest";
import {
  type KnotCioControlShadowBinding,
  type KnotCioControlShadowCallbacks,
  type KnotCioPairSide,
  type KnotControlDependencyAgentId,
  type KnotControlDependencyResult,
  runKnotCioControlShadowPair,
} from "../src/autoresearch/knot_cio_control_shadow.js";
import {
  type KnotControlNoEvaluationObjectStageSkipRecord,
  KnotControlNoEvaluationObjectStageSkipRecordSchema,
  NoEvaluationObjectStageSkipRecordSchema,
} from "../src/autoresearch/outcome_stage_skip.js";

type Payload = { value: string };

const digest = (character: string): string => `sha256:${character.repeat(64)}`;

const binding: KnotCioControlShadowBinding = {
  knot_pair_id: "knot-pair-1",
  graph_run_id: "graph-run-1",
  root_snapshot_bundle_id: "root-bundle-1",
  root_snapshot_bundle_hash: digest("a"),
  runtime_input_hash: digest("b"),
  evaluation_opportunity_set_id: "opportunity-1",
  evaluation_opportunity_set_hash: digest("c"),
  realized_outcome_observation_id: "realized-1",
  realized_outcome_observation_hash: digest("d"),
  control_track_key_hashes: {
    alpha_discovery: digest("1"),
    cro: digest("2"),
    autonomous_execution: digest("3"),
  },
};

function accepted(
  agentId: KnotControlDependencyAgentId,
  side: "SHARED" | KnotCioPairSide,
  value: string,
): KnotControlDependencyResult<Payload> {
  return {
    status: "ACCEPTED",
    agent_id: agentId,
    control_side: side,
    sample_origin: "KNOT_CONTROL_SHADOW",
    production_reliability_eligible: false,
    run_slot_kind: "DOWNSTREAM_ONLY",
    scheduled_sample_id: null,
    root_snapshot_bundle_id: binding.root_snapshot_bundle_id,
    root_snapshot_bundle_hash: binding.root_snapshot_bundle_hash,
    track_key_hash: binding.control_track_key_hashes[agentId],
    operational_opportunity_audit_id: `audit:${agentId}:${side}`,
    operational_opportunity_audit_hash: digest("4"),
    accepted_output_id: `accepted:${agentId}:${side}`,
    accepted_output_hash: digest("5"),
    model_input: { value },
    stage_skip: null,
    failure_reason: null,
  };
}

function stageSkip(
  agentId: "cro" | "autonomous_execution",
  side: KnotCioPairSide,
): KnotControlDependencyResult<Payload> {
  const skip: KnotControlNoEvaluationObjectStageSkipRecord = {
    stage_skip_id: `skip:${agentId}:${side}`,
    stage_skip_hash: digest("6"),
    schema_version: "knot_control_no_evaluation_object_stage_skip_v2",
    knot_pair_id: binding.knot_pair_id,
    graph_run_id: binding.graph_run_id,
    run_slot_id: `slot:${agentId}:${side}`,
    control_side: side,
    track_key_hash: binding.control_track_key_hashes[agentId],
    agent_id: agentId,
    sample_origin: "KNOT_CONTROL_SHADOW",
    skip_reason: "NO_EVALUATION_OBJECT",
    frozen_object_set_id: `empty:${agentId}:${side}`,
    frozen_object_set_hash: digest("7"),
    member_count: 0,
    model_invoked: false,
    operational_opportunity_audit_id: `audit:${agentId}:${side}`,
    operational_opportunity_audit_hash: digest("8"),
    evidence_ids: ["evidence:empty"],
    causal_dedupe_key: digest("9"),
    recorded_at: "2026-07-17T10:00:00+08:00",
  };
  return {
    status: "NO_EVALUATION_OBJECT",
    agent_id: agentId,
    control_side: side,
    sample_origin: "KNOT_CONTROL_SHADOW",
    production_reliability_eligible: false,
    run_slot_kind: "DOWNSTREAM_ONLY",
    scheduled_sample_id: null,
    root_snapshot_bundle_id: binding.root_snapshot_bundle_id,
    root_snapshot_bundle_hash: binding.root_snapshot_bundle_hash,
    track_key_hash: binding.control_track_key_hashes[agentId],
    operational_opportunity_audit_id: skip.operational_opportunity_audit_id,
    operational_opportunity_audit_hash: skip.operational_opportunity_audit_hash,
    accepted_output_id: null,
    accepted_output_hash: null,
    model_input: skip,
    stage_skip: skip,
    failure_reason: null,
  };
}

function dependencyFailure(
  agentId: KnotControlDependencyAgentId,
  side: "SHARED" | KnotCioPairSide,
): KnotControlDependencyResult<Payload> {
  return {
    status: "AGENT_FAILURE",
    agent_id: agentId,
    control_side: side,
    sample_origin: "KNOT_CONTROL_SHADOW",
    production_reliability_eligible: false,
    run_slot_kind: "DOWNSTREAM_ONLY",
    scheduled_sample_id: null,
    root_snapshot_bundle_id: binding.root_snapshot_bundle_id,
    root_snapshot_bundle_hash: binding.root_snapshot_bundle_hash,
    track_key_hash: binding.control_track_key_hashes[agentId],
    operational_opportunity_audit_id: `audit:${agentId}:${side}`,
    operational_opportunity_audit_hash: digest("e"),
    accepted_output_id: null,
    accepted_output_hash: null,
    model_input: null,
    stage_skip: null,
    failure_reason: "MODEL_FAILURE",
  };
}

function callbacks(): KnotCioControlShadowCallbacks<Payload, Payload, Payload, Payload, Payload> {
  return {
    runAlphaControl: vi.fn().mockResolvedValue(accepted("alpha_discovery", "SHARED", "alpha")),
    runCioProposal: vi.fn().mockImplementation(async ({ side }) => ({
      status: "ACCEPTED",
      output: { value: `proposal:${side}` },
      accepted_output_id: `proposal:${side}`,
      accepted_output_hash: side === "CHAMPION" ? digest("a") : digest("b"),
    })),
    runCroControl: vi
      .fn()
      .mockImplementation(async ({ side }) => accepted("cro", side, `cro:${side}`)),
    runExecutionControl: vi
      .fn()
      .mockImplementation(async ({ side }) =>
        accepted("autonomous_execution", side, `execution:${side}`),
      ),
    runCioFinal: vi.fn().mockImplementation(async ({ side }) => ({
      status: "ACCEPTED",
      output: { value: `final:${side}` },
      accepted_output_id: `final:${side}`,
      accepted_output_hash: side === "CHAMPION" ? digest("c") : digest("d"),
    })),
    recordDependencyBlocked: vi.fn().mockResolvedValue({
      audit_id: "dependency-blocked-1",
      audit_hash: digest("f"),
    }),
  };
}

describe("CIO KNOT control-shadow subgraph", () => {
  it("keeps control stage skips in a namespace distinct from outcome eligibility", () => {
    const skip = stageSkip("cro", "CHAMPION");
    if (skip.status !== "NO_EVALUATION_OBJECT") throw new Error("fixture mismatch");
    expect(KnotControlNoEvaluationObjectStageSkipRecordSchema.parse(skip.stage_skip)).toEqual(
      skip.stage_skip,
    );
    expect(() => NoEvaluationObjectStageSkipRecordSchema.parse(skip.stage_skip)).toThrow();
    expect(() =>
      KnotControlNoEvaluationObjectStageSkipRecordSchema.parse({
        ...skip.stage_skip,
        agent_id: "alpha_discovery",
        control_side: "CHAMPION",
      }),
    ).toThrow(/cannot use CHAMPION/);
  });

  it("samples Alpha once and runs side-specific proposal/CRO/Execution/final chains", async () => {
    const deps = callbacks();
    const result = await runKnotCioControlShadowPair(binding, deps);

    expect(result.pair_disposition).toBe("ACCOUNTABLE");
    expect(deps.runAlphaControl).toHaveBeenCalledTimes(1);
    expect(deps.runCioProposal).toHaveBeenCalledTimes(2);
    expect(deps.runCroControl).toHaveBeenCalledTimes(2);
    expect(deps.runExecutionControl).toHaveBeenCalledTimes(2);
    expect(deps.runCioFinal).toHaveBeenCalledTimes(2);
    expect(result.sides.map((side) => side.side)).toEqual(["CHAMPION", "CANDIDATE"]);
    expect(result.realized_outcome_observation_hash).toBe(
      binding.realized_outcome_observation_hash,
    );
    expect(vi.mocked(deps.runCioProposal).mock.calls[0]?.[0].alpha).toBe(
      vi.mocked(deps.runCioProposal).mock.calls[1]?.[0].alpha,
    );
  });

  it("continues through control stage skips without creating a CIO failure", async () => {
    const deps = callbacks();
    vi.mocked(deps.runCroControl).mockImplementation(async ({ side }) =>
      side === "CHAMPION" ? stageSkip("cro", side) : accepted("cro", side, `cro:${side}`),
    );
    const result = await runKnotCioControlShadowPair(binding, deps);

    expect(result.pair_disposition).toBe("ACCOUNTABLE");
    expect(result.sides.every((side) => side.score_disposition === "SCORE")).toBe(true);
    expect(deps.runExecutionControl).toHaveBeenCalledTimes(2);
  });

  it("marks a dependency failure as pair-blocked instead of a CIO -2", async () => {
    const deps = callbacks();
    vi.mocked(deps.runExecutionControl).mockImplementation(async ({ side }) =>
      side === "CHAMPION"
        ? dependencyFailure("autonomous_execution", side)
        : accepted("autonomous_execution", side, `execution:${side}`),
    );
    const result = await runKnotCioControlShadowPair(binding, deps);

    expect(result.pair_disposition).toBe("DEPENDENCY_BLOCKED");
    expect(result.sides).toEqual([]);
    expect(result.dependency_blocked_audit?.blocked_dependency_agent_id).toBe(
      "autonomous_execution",
    );
    expect(deps.runCioFinal).not.toHaveBeenCalled();
    expect(deps.recordDependencyBlocked).toHaveBeenCalledTimes(1);
  });

  it("attributes only proposal/final failures to CIO and still resolves both sides", async () => {
    const deps = callbacks();
    vi.mocked(deps.runCioProposal).mockImplementation(async ({ side }) =>
      side === "CHAMPION"
        ? {
            status: "AGENT_FAILURE",
            output: null,
            accepted_output_id: null,
            accepted_output_hash: null,
            operational_opportunity_audit_id: "cio-proposal-failure",
            operational_opportunity_audit_hash: digest("0"),
            failure_reason: "MODEL_FAILURE",
          }
        : {
            status: "ACCEPTED",
            output: { value: `proposal:${side}` },
            accepted_output_id: `proposal:${side}`,
            accepted_output_hash: digest("b"),
          },
    );
    const result = await runKnotCioControlShadowPair(binding, deps);

    expect(result.pair_disposition).toBe("ACCOUNTABLE");
    expect(result.sides[0]?.score_disposition).toBe("AGENT_FAILURE");
    expect(result.sides[1]?.score_disposition).toBe("SCORE");
    expect(deps.runCroControl).toHaveBeenCalledTimes(1);
    expect(deps.recordDependencyBlocked).not.toHaveBeenCalled();
  });
});

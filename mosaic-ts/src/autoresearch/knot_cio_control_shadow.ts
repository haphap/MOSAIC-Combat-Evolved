import { createHash } from "node:crypto";
import type { KnotControlNoEvaluationObjectStageSkipRecord } from "./outcome_stage_skip.js";

export type KnotCioPairSide = "CHAMPION" | "CANDIDATE";
export type KnotControlDependencyAgentId = "alpha_discovery" | "cro" | "autonomous_execution";

interface KnotControlRecordBase {
  agent_id: KnotControlDependencyAgentId;
  control_side: "SHARED" | KnotCioPairSide;
  sample_origin: "KNOT_CONTROL_SHADOW";
  production_reliability_eligible: false;
  run_slot_kind: "DOWNSTREAM_ONLY";
  scheduled_sample_id: null;
  root_snapshot_bundle_id: string;
  root_snapshot_bundle_hash: string;
  track_key_hash: string;
  operational_opportunity_audit_id: string;
  operational_opportunity_audit_hash: string;
}

export type KnotControlDependencyResult<T> =
  | (KnotControlRecordBase & {
      status: "ACCEPTED";
      accepted_output_id: string;
      accepted_output_hash: string;
      model_input: T;
      stage_skip: null;
      failure_reason: null;
    })
  | (KnotControlRecordBase & {
      status: "NO_EVALUATION_OBJECT";
      accepted_output_id: null;
      accepted_output_hash: null;
      model_input: KnotControlNoEvaluationObjectStageSkipRecord;
      stage_skip: KnotControlNoEvaluationObjectStageSkipRecord;
      failure_reason: null;
    })
  | (KnotControlRecordBase & {
      status: "AGENT_FAILURE" | "EXOGENOUS_EXCLUSION";
      accepted_output_id: null;
      accepted_output_hash: null;
      model_input: null;
      stage_skip: null;
      failure_reason: string;
    });

export type KnotCioPhaseResult<T> =
  | {
      status: "ACCEPTED";
      output: T;
      accepted_output_id: string;
      accepted_output_hash: string;
    }
  | {
      status: "AGENT_FAILURE";
      output: null;
      accepted_output_id: null;
      accepted_output_hash: null;
      operational_opportunity_audit_id: string;
      operational_opportunity_audit_hash: string;
      failure_reason: string;
    };

export interface KnotCioControlShadowBinding {
  knot_pair_id: string;
  graph_run_id: string;
  root_snapshot_bundle_id: string;
  root_snapshot_bundle_hash: string;
  runtime_input_hash: string;
  evaluation_opportunity_set_id: string;
  evaluation_opportunity_set_hash: string;
  realized_outcome_observation_id: string;
  realized_outcome_observation_hash: string;
  control_track_key_hashes: Record<KnotControlDependencyAgentId, string>;
}

export interface KnotCioControlShadowCallbacks<Alpha, Proposal, Cro, Execution, Final> {
  runAlphaControl(
    binding: KnotCioControlShadowBinding,
  ): Promise<KnotControlDependencyResult<Alpha>>;
  runCioProposal(input: {
    side: KnotCioPairSide;
    binding: KnotCioControlShadowBinding;
    alpha: Alpha | KnotControlNoEvaluationObjectStageSkipRecord;
  }): Promise<KnotCioPhaseResult<Proposal>>;
  runCroControl(input: {
    side: KnotCioPairSide;
    binding: KnotCioControlShadowBinding;
    alpha: Alpha | KnotControlNoEvaluationObjectStageSkipRecord;
    proposal: Proposal;
    proposal_bundle_hash: string;
  }): Promise<KnotControlDependencyResult<Cro>>;
  runExecutionControl(input: {
    side: KnotCioPairSide;
    binding: KnotCioControlShadowBinding;
    alpha: Alpha | KnotControlNoEvaluationObjectStageSkipRecord;
    proposal: Proposal;
    cro: Cro | KnotControlNoEvaluationObjectStageSkipRecord;
    cro_adjusted_bundle_hash: string;
  }): Promise<KnotControlDependencyResult<Execution>>;
  runCioFinal(input: {
    side: KnotCioPairSide;
    binding: KnotCioControlShadowBinding;
    alpha: Alpha | KnotControlNoEvaluationObjectStageSkipRecord;
    proposal: Proposal;
    cro: Cro | KnotControlNoEvaluationObjectStageSkipRecord;
    execution: Execution | KnotControlNoEvaluationObjectStageSkipRecord;
    final_bundle_hash: string;
  }): Promise<KnotCioPhaseResult<Final>>;
  recordDependencyBlocked(input: {
    binding: KnotCioControlShadowBinding;
    side: "SHARED" | KnotCioPairSide;
    blocked_dependency_agent_id: KnotControlDependencyAgentId;
    blocked_dependency_operational_audit_id: string;
    blocked_dependency_operational_audit_hash: string;
    failure_reason: string;
  }): Promise<{ audit_id: string; audit_hash: string }>;
}

export type KnotCioSideResult<Proposal, Final> =
  | {
      side: KnotCioPairSide;
      score_disposition: "SCORE";
      proposal: Proposal;
      final: Final;
      cio_failure: null;
    }
  | {
      side: KnotCioPairSide;
      score_disposition: "AGENT_FAILURE";
      proposal: Proposal | null;
      final: null;
      cio_failure: {
        failed_phase: "PROPOSAL" | "FINAL";
        operational_opportunity_audit_id: string;
        operational_opportunity_audit_hash: string;
        failure_reason: string;
      };
    };

export type KnotCioControlShadowPairResult<Proposal, Final> =
  | {
      pair_disposition: "ACCOUNTABLE";
      shared_alpha_invocations: 1;
      realized_outcome_observation_id: string;
      realized_outcome_observation_hash: string;
      sides: [KnotCioSideResult<Proposal, Final>, KnotCioSideResult<Proposal, Final>];
      dependency_blocked_audit: null;
    }
  | {
      pair_disposition: "DEPENDENCY_BLOCKED";
      shared_alpha_invocations: 1;
      realized_outcome_observation_id: string;
      realized_outcome_observation_hash: string;
      sides: [];
      dependency_blocked_audit: {
        audit_id: string;
        audit_hash: string;
        side: "SHARED" | KnotCioPairSide;
        blocked_dependency_agent_id: KnotControlDependencyAgentId;
        failure_reason: string;
      };
    };

/**
 * Execute the only KNOT target that has a dependency subgraph.
 *
 * Alpha is sampled once and reused byte-for-byte. Each side then gets its own
 * proposal -> CRO -> Execution -> final chain. Dependency failures consume the
 * frozen pair slot but are not scored as CIO failures; proposal/final failures
 * are the only failures attributed to CIO.
 */
export async function runKnotCioControlShadowPair<Alpha, Proposal, Cro, Execution, Final>(
  binding: KnotCioControlShadowBinding,
  callbacks: KnotCioControlShadowCallbacks<Alpha, Proposal, Cro, Execution, Final>,
): Promise<KnotCioControlShadowPairResult<Proposal, Final>> {
  assertBinding(binding);
  const alpha = await callbacks.runAlphaControl(binding);
  assertControlResult(alpha, binding, "alpha_discovery", "SHARED");
  if (isBlockingDependencyResult(alpha)) {
    return dependencyBlockedResult(binding, callbacks, "SHARED", alpha);
  }
  const alphaInput = alpha.model_input;
  const sides: Array<KnotCioSideResult<Proposal, Final>> = [];
  for (const side of ["CHAMPION", "CANDIDATE"] as const) {
    const proposal = await callbacks.runCioProposal({ side, binding, alpha: alphaInput });
    if (proposal.status === "AGENT_FAILURE") {
      sides.push(cioFailure<Proposal, Final>(side, "PROPOSAL", null, proposal));
      continue;
    }
    const proposalBundleHash = canonicalHash({
      schema_version: "knot.cio_proposal_bundle.v2",
      knot_pair_id: binding.knot_pair_id,
      side,
      root_snapshot_bundle_hash: binding.root_snapshot_bundle_hash,
      alpha_source_hash:
        alpha.accepted_output_hash ?? alpha.stage_skip?.stage_skip_hash ?? "unreachable",
      proposal_accepted_output_hash: proposal.accepted_output_hash,
    });
    const cro = await callbacks.runCroControl({
      side,
      binding,
      alpha: alphaInput,
      proposal: proposal.output,
      proposal_bundle_hash: proposalBundleHash,
    });
    assertControlResult(cro, binding, "cro", side);
    if (isBlockingDependencyResult(cro)) {
      return dependencyBlockedResult(binding, callbacks, side, cro);
    }
    const croAdjustedBundleHash = canonicalHash({
      schema_version: "knot.cio_cro_adjusted_bundle.v2",
      proposal_bundle_hash: proposalBundleHash,
      cro_source_hash: cro.accepted_output_hash ?? cro.stage_skip?.stage_skip_hash ?? "unreachable",
    });
    const execution = await callbacks.runExecutionControl({
      side,
      binding,
      alpha: alphaInput,
      proposal: proposal.output,
      cro: cro.model_input,
      cro_adjusted_bundle_hash: croAdjustedBundleHash,
    });
    assertControlResult(execution, binding, "autonomous_execution", side);
    if (isBlockingDependencyResult(execution)) {
      return dependencyBlockedResult(binding, callbacks, side, execution);
    }
    const finalBundleHash = canonicalHash({
      schema_version: "knot.cio_final_bundle.v2",
      cro_adjusted_bundle_hash: croAdjustedBundleHash,
      execution_source_hash:
        execution.accepted_output_hash ?? execution.stage_skip?.stage_skip_hash ?? "unreachable",
    });
    const final = await callbacks.runCioFinal({
      side,
      binding,
      alpha: alphaInput,
      proposal: proposal.output,
      cro: cro.model_input,
      execution: execution.model_input,
      final_bundle_hash: finalBundleHash,
    });
    if (final.status === "AGENT_FAILURE") {
      sides.push(cioFailure<Proposal, Final>(side, "FINAL", proposal.output, final));
      continue;
    }
    sides.push({
      side,
      score_disposition: "SCORE",
      proposal: proposal.output,
      final: final.output,
      cio_failure: null,
    });
  }
  if (sides.length !== 2 || sides[0]?.side !== "CHAMPION" || sides[1]?.side !== "CANDIDATE") {
    throw new Error("knot_cio_pair_did_not_resolve_both_sides");
  }
  return {
    pair_disposition: "ACCOUNTABLE",
    shared_alpha_invocations: 1,
    realized_outcome_observation_id: binding.realized_outcome_observation_id,
    realized_outcome_observation_hash: binding.realized_outcome_observation_hash,
    sides: sides as [KnotCioSideResult<Proposal, Final>, KnotCioSideResult<Proposal, Final>],
    dependency_blocked_audit: null,
  };
}

function assertBinding(binding: KnotCioControlShadowBinding): void {
  for (const [field, value] of Object.entries(binding)) {
    if (field === "control_track_key_hashes") continue;
    if (typeof value !== "string" || value.length === 0) throw new Error(`invalid_${field}`);
    if (field.endsWith("_hash") && !/^sha256:[0-9a-f]{64}$/.test(value)) {
      throw new Error(`invalid_${field}`);
    }
  }
  if (
    Object.keys(binding.control_track_key_hashes).sort().join(",") !==
    ["alpha_discovery", "autonomous_execution", "cro"].join(",")
  ) {
    throw new Error("invalid_knot_control_track_set");
  }
  if (
    Object.values(binding.control_track_key_hashes).some(
      (trackHash) => !/^sha256:[0-9a-f]{64}$/.test(trackHash),
    )
  ) {
    throw new Error("invalid_knot_control_track_hash");
  }
}

function assertControlResult<T>(
  result: KnotControlDependencyResult<T>,
  binding: KnotCioControlShadowBinding,
  agentId: KnotControlDependencyAgentId,
  side: "SHARED" | KnotCioPairSide,
): void {
  if (
    result.agent_id !== agentId ||
    result.control_side !== side ||
    result.sample_origin !== "KNOT_CONTROL_SHADOW" ||
    result.production_reliability_eligible !== false ||
    result.run_slot_kind !== "DOWNSTREAM_ONLY" ||
    result.scheduled_sample_id !== null ||
    result.root_snapshot_bundle_id !== binding.root_snapshot_bundle_id ||
    result.root_snapshot_bundle_hash !== binding.root_snapshot_bundle_hash ||
    result.track_key_hash !== binding.control_track_key_hashes[agentId]
  ) {
    throw new Error(`invalid_knot_control_result:${agentId}:${side}`);
  }
  if (result.status === "NO_EVALUATION_OBJECT") {
    if (
      result.stage_skip.agent_id !== agentId ||
      result.stage_skip.control_side !== side ||
      result.stage_skip.operational_opportunity_audit_id !==
        result.operational_opportunity_audit_id ||
      result.stage_skip.operational_opportunity_audit_hash !==
        result.operational_opportunity_audit_hash
    ) {
      throw new Error(`invalid_knot_control_stage_skip:${agentId}:${side}`);
    }
  }
}

function isBlockingDependencyResult<T>(
  result: KnotControlDependencyResult<T>,
): result is Extract<
  KnotControlDependencyResult<T>,
  { status: "AGENT_FAILURE" | "EXOGENOUS_EXCLUSION" }
> {
  return result.status === "AGENT_FAILURE" || result.status === "EXOGENOUS_EXCLUSION";
}

async function dependencyBlockedResult<Alpha, Proposal, Cro, Execution, Final>(
  binding: KnotCioControlShadowBinding,
  callbacks: KnotCioControlShadowCallbacks<Alpha, Proposal, Cro, Execution, Final>,
  side: "SHARED" | KnotCioPairSide,
  dependency: Extract<
    KnotControlDependencyResult<unknown>,
    { status: "AGENT_FAILURE" | "EXOGENOUS_EXCLUSION" }
  >,
): Promise<KnotCioControlShadowPairResult<Proposal, Final>> {
  const audit = await callbacks.recordDependencyBlocked({
    binding,
    side,
    blocked_dependency_agent_id: dependency.agent_id,
    blocked_dependency_operational_audit_id: dependency.operational_opportunity_audit_id,
    blocked_dependency_operational_audit_hash: dependency.operational_opportunity_audit_hash,
    failure_reason: dependency.failure_reason,
  });
  return {
    pair_disposition: "DEPENDENCY_BLOCKED",
    shared_alpha_invocations: 1,
    realized_outcome_observation_id: binding.realized_outcome_observation_id,
    realized_outcome_observation_hash: binding.realized_outcome_observation_hash,
    sides: [],
    dependency_blocked_audit: {
      ...audit,
      side,
      blocked_dependency_agent_id: dependency.agent_id,
      failure_reason: dependency.failure_reason,
    },
  };
}

function cioFailure<Proposal, Final>(
  side: KnotCioPairSide,
  failedPhase: "PROPOSAL" | "FINAL",
  proposal: Proposal | null,
  result: Extract<KnotCioPhaseResult<Final>, { status: "AGENT_FAILURE" }>,
): KnotCioSideResult<Proposal, Final> {
  return {
    side,
    score_disposition: "AGENT_FAILURE",
    proposal,
    final: null,
    cio_failure: {
      failed_phase: failedPhase,
      operational_opportunity_audit_id: result.operational_opportunity_audit_id,
      operational_opportunity_audit_hash: result.operational_opportunity_audit_hash,
      failure_reason: result.failure_reason,
    },
  };
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

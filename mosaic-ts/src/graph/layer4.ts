/**
 * Layer-4 LangGraph subgraph (Plan §11.2 sub-step 2D.3).
 *
 * Topology is the canonical stage-aware serial chain:
 *
 *   START → alpha_discovery → cio_proposal → candidate_freeze → cro
 *         → autonomous_execution → cio_final → shared_validation → END
 *
 * Dependency contract:
 *   * alpha_discovery runs before target construction.
 *   * cio_proposal emits a candidate which is frozen by deterministic code.
 *   * CRO and execution consume the exact same candidate hash.
 *   * cio_final consumes frozen CRO/execution envelopes.
 *   * shared_validation is the only node that publishes portfolio_actions.
 *
 * Subgraph assumes Layer-1, Layer-2 and Layer-3 outputs are populated in
 * state. Only shared_validation writes ``state.portfolio_actions``.
 */

import { END, START, StateGraph } from "@langchain/langgraph";
import { activeKnobValuesFromUpstreamDecisionAgents } from "../agents/decision/_factory.js";
import { buildAlphaDiscoveryNode } from "../agents/decision/alpha_discovery.js";
import { buildAutonomousExecutionNode } from "../agents/decision/autonomous_execution.js";
import { buildCioNode, buildCioProposalNode } from "../agents/decision/cio.js";
import { buildCroNode } from "../agents/decision/cro.js";
import {
  buildPortfolioSummary,
  freezeCioProposal,
  freezeFinalTarget,
  Layer4RuntimeContractError,
  runtimeStateForLayer4,
  stableRuntimeHash,
  updateLayer4Runtime,
  validateFinalTargetEnvelope,
} from "../agents/decision/layer4_runtime.js";
import {
  buildConservativeCioFinalFallback,
  PositionActionValidationError,
  validateCioPositionActions,
} from "../agents/decision/position_validator.js";
import {
  type Layer4SourceResolutionStage,
  resolveLayer4SourceBundle,
} from "../agents/helpers/layer4_source_adapters.js";
import {
  DailyCycleState,
  type DailyCycleStateType,
  type DailyCycleStateUpdate,
} from "../agents/state.js";
import type { CioOutput } from "../agents/types.js";
import type { BridgeApi, MosaicConfig } from "../bridge/index.js";
import type { LlmHandle } from "../llm/factory.js";
import { chainEdges, serialEdges } from "./_edges.js";

export interface BuildLayer4GraphDeps {
  llmHandle: LlmHandle;
  /** ``api`` is unused at runtime by L4 nodes, kept for symmetry. */
  api?: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
}

export const LAYER4_AGENT_NODES = [
  "alpha_discovery",
  "cio_proposal",
  "cro",
  "autonomous_execution",
  "cio_final",
] as const;

export const LAYER4_RUNTIME_NODES = [
  "pre_candidate_sources",
  "alpha_discovery",
  "cio_proposal_sources",
  "cio_proposal",
  "candidate_market_sources",
  "candidate_freeze",
  "cro",
  "execution_liquidity_sources",
  "autonomous_execution",
  "cio_final",
  "shared_validation",
] as const;

/** Build (and compile) the Layer-4 decision subgraph. */
export function buildLayer4Graph(deps: BuildLayer4GraphDeps) {
  const graph = new StateGraph(DailyCycleState)
    .addNode("pre_candidate_sources", buildSourceResolutionNode(deps, "pre_candidate"))
    .addNode("alpha_discovery", buildAlphaDiscoveryNode(deps))
    .addNode("cio_proposal_sources", buildSourceResolutionNode(deps, "pre_candidate"))
    .addNode("cio_proposal", buildCioProposalNode(deps))
    .addNode("candidate_market_sources", buildSourceResolutionNode(deps, "candidate_market"))
    .addNode("candidate_freeze", freezeCandidateTargetNode)
    .addNode("cro", buildCroNode(deps))
    .addNode("execution_liquidity_sources", buildSourceResolutionNode(deps, "execution_liquidity"))
    .addNode("autonomous_execution", buildAutonomousExecutionNode(deps))
    .addNode("cio_final", buildCioNode(deps))
    .addNode("shared_validation", validateFinalTargetNode);

  // Serial L4: keep one LLM/tool stream active at a time.
  chainEdges(graph, serialEdges([START, ...LAYER4_RUNTIME_NODES, END] as const));

  return graph.compile();
}

export function buildSourceResolutionNode(
  deps: BuildLayer4GraphDeps,
  stage: Layer4SourceResolutionStage,
): (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate> {
  return async (state) => {
    const currentRuntime = runtimeStateForLayer4(state);
    const resolved = await resolveLayer4SourceBundle(state, stage, deps.api);
    return {
      layer4_outputs: {
        runtime: {
          ...currentRuntime,
          resolved_source_statuses: resolved.statuses,
          source_evidence_observations: resolved.evidence,
        },
      },
    };
  };
}

export function freezeCandidateTargetNode(state: DailyCycleStateType): DailyCycleStateUpdate {
  const currentRuntime = runtimeStateForLayer4(state);
  if (!currentRuntime.cio_proposal) {
    throw new Error("candidate_freeze requires cio_proposal output");
  }
  const frozen = freezeCioProposal(state, currentRuntime.cio_proposal);
  const proposalFallback = frozen.proposal.runtime_fallback_audit;
  const fallbackReasonCodes = [
    ...(proposalFallback?.reason_codes ?? []),
    ...(frozen.reviews.fallback_tickers.length > 0 ? ["UNREVIEWED_POSITION"] : []),
  ];
  const runtime = updateLayer4Runtime(
    currentRuntime,
    {
      cio_proposal: frozen.proposal,
      candidate_target_state: frozen.candidate,
      position_review_state: frozen.reviews,
      portfolio_exposure_state: frozen.exposure,
    },
    {
      stage: "cio_proposal",
      operation: "source_freeze",
      status: fallbackReasonCodes.length > 0 ? "fallback" : "completed",
      ...(fallbackReasonCodes.length > 0
        ? {
            reason_codes: fallbackReasonCodes,
            fallback_factory_id:
              proposalFallback?.fallback_factory_id ??
              "portfolio.position_coverage.runtime_safety_hold.v1",
            fallback_factory_version: proposalFallback?.fallback_factory_version ?? "1",
          }
        : {}),
      input_hashes: { cio_proposal: frozen.candidate.proposal_hash },
      output_hashes: {
        candidate_target_state: frozen.candidate.candidate_target_hash,
        position_review_state: frozen.reviews.position_review_hash,
        portfolio_exposure_state: frozen.exposure.exposure_hash,
      },
    },
  );
  return {
    layer4_outputs: { runtime },
    position_reviews: frozen.reviews.reviews,
  };
}

export function validateFinalTargetNode(state: DailyCycleStateType): DailyCycleStateUpdate {
  const output = state.layer4_outputs.cio;
  if (!output) throw new Error("shared_validation requires cio_final output");
  const runtime = runtimeStateForLayer4(state);
  const sharedPolicyValues = activeKnobValuesFromUpstreamDecisionAgents(state.layer4_outputs);
  const validatorHash = stableRuntimeHash({
    validator: "validateCioPositionActions.v1",
    knob_snapshot_hash: runtime.cio_final_knob_snapshot?.hash ?? null,
    shared_policy_values: sharedPolicyValues,
  });
  let selectedOutput = output;
  let fallbackRejectionReasons: string[] = [];
  let validated: ReturnType<typeof validateCioPositionActions>;
  try {
    validated = validateCioPositionActions({
      output: selectedOutput,
      currentPositions: state.current_positions,
      knobSnapshot: runtime.cio_final_knob_snapshot,
      sharedPolicyValues,
    });
    const stateWithValidatedOutput: DailyCycleStateType = {
      ...state,
      layer4_outputs: { ...state.layer4_outputs, cio: validated.output },
    };
    validateFinalTargetEnvelope(stateWithValidatedOutput, validated.output);
  } catch (error) {
    if (
      !(error instanceof PositionActionValidationError) &&
      !(error instanceof Layer4RuntimeContractError)
    ) {
      throw error;
    }
    const candidate = runtime.candidate_target_state;
    const croReview = runtime.cro_review_state;
    if (!candidate || !croReview) throw error;
    fallbackRejectionReasons = [error.message];
    selectedOutput = buildConservativeCioFinalFallback({
      sourceOutput: output,
      currentPositions: state.current_positions,
      candidate,
      croReview,
      knobSnapshot: runtime.cio_final_knob_snapshot,
      sharedPolicyValues,
      rejectionReasons: fallbackRejectionReasons,
    });
    validated = validateCioPositionActions({
      output: selectedOutput,
      currentPositions: state.current_positions,
      knobSnapshot: runtime.cio_final_knob_snapshot,
      sharedPolicyValues,
    });
  }
  const stateWithValidatedOutput: DailyCycleStateType = {
    ...state,
    layer4_outputs: { ...state.layer4_outputs, cio: validated.output },
  };
  const finalTarget = freezeFinalTarget(
    stateWithValidatedOutput,
    validated.output,
    [validatorHash],
    { allowRuntimeSafetyFallback: fallbackRejectionReasons.length > 0 },
  );
  const portfolioSummary = buildPortfolioSummary({
    state,
    finalTarget,
    validationStatus: fallbackRejectionReasons.length > 0 ? "fallback" : "accepted",
    ...(fallbackRejectionReasons.length > 0
      ? { reasonCodes: ["FINAL_TARGET_VALIDATION_REJECTED"] }
      : {}),
  });
  const updatedRuntime = updateLayer4Runtime(
    runtime,
    { final_target_state: finalTarget, portfolio_summary: portfolioSummary },
    {
      stage: "shared_validation",
      operation: "validation",
      status: fallbackRejectionReasons.length > 0 ? "fallback" : "completed",
      ...(fallbackRejectionReasons.length > 0
        ? {
            reason_codes: ["FINAL_TARGET_VALIDATION_REJECTED"],
            fallback_factory_id: "portfolio.shared_validation.no_new_risk.v1",
            fallback_factory_version: "1",
          }
        : {}),
      input_hashes: {
        candidate_target_state: finalTarget.candidate_target_hash,
        cro_review_state: finalTarget.cro_review_hash,
        execution_feasibility_state: finalTarget.execution_feasibility_hash,
        cio_final: stableRuntimeHash(output),
      },
      output_hashes: {
        final_target_state: finalTarget.final_target_hash,
        portfolio_summary: portfolioSummary.summary_hash,
      },
    },
  );
  return {
    layer4_outputs: { cio: validated.output as CioOutput, runtime: updatedRuntime },
    position_reviews: validated.position_reviews,
    position_audit: validated.position_audit,
    portfolio_actions: validated.output.portfolio_actions,
  };
}

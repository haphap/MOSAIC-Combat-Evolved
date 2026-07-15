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
import {
  activeKnobValuesFromUpstreamDecisionAgents,
  layer4MirofishSnapshotHash,
  pickPromptLanguage,
  preloadLayer4MirofishContext,
} from "../agents/decision/_factory.js";
import { buildAlphaDiscoveryNode } from "../agents/decision/alpha_discovery.js";
import { buildAutonomousExecutionNode } from "../agents/decision/autonomous_execution.js";
import { buildCioNode, buildCioProposalNode } from "../agents/decision/cio.js";
import { buildCroNode } from "../agents/decision/cro.js";
import {
  buildPortfolioSummary,
  freezeCioProposal,
  freezeFinalTarget,
  freezeL4RunSnapshotBundle,
  Layer4RuntimeContractError,
  layer4PromptSourceHash,
  runtimeStateForLayer4,
  stableRuntimeHash,
  updateLayer4Runtime,
  validateFinalTargetEnvelope,
} from "../agents/decision/layer4_runtime.js";
import { validateCioPositionActions } from "../agents/decision/position_validator.js";
import {
  type Layer4SourceResolutionStage,
  mergeRuntimeSourceStatuses,
  resolveLayer4SourceBundle,
} from "../agents/helpers/layer4_source_adapters.js";
import { isResearchKnobsStageEnabled } from "../agents/helpers/research_knobs.js";
import { loadPrompt, loadPromptWithKnobs } from "../agents/prompts/loader.js";
import {
  DailyCycleState,
  type DailyCycleStateType,
  type DailyCycleStateUpdate,
} from "../agents/state.js";
import type { CioOutput, L4RunPromptSnapshot } from "../agents/types.js";
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
  "l4_snapshot_freeze",
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
  const strictDeps = { ...deps, requireL4SnapshotBundle: true };
  const graph = new StateGraph(DailyCycleState)
    .addNode("l4_snapshot_freeze", buildL4SnapshotFreezeNode(strictDeps))
    .addNode("alpha_discovery", buildAlphaDiscoveryNode(strictDeps))
    .addNode("cio_proposal_sources", buildSourceResolutionNode(deps, "pre_candidate"))
    .addNode("cio_proposal", buildCioProposalNode(strictDeps))
    .addNode("candidate_market_sources", buildSourceResolutionNode(deps, "candidate_market"))
    .addNode("candidate_freeze", freezeCandidateTargetNode)
    .addNode("cro", buildCroNode(strictDeps))
    .addNode("execution_liquidity_sources", buildSourceResolutionNode(deps, "execution_liquidity"))
    .addNode("autonomous_execution", buildAutonomousExecutionNode(strictDeps))
    .addNode("cio_final", buildCioNode(strictDeps))
    .addNode("shared_validation", validateFinalTargetNode);

  // Serial L4: keep one LLM/tool stream active at a time.
  chainEdges(graph, serialEdges([START, ...LAYER4_RUNTIME_NODES, END] as const));

  return graph.compile();
}

const L4_PROMPT_INVOCATIONS: ReadonlyArray<Pick<L4RunPromptSnapshot, "agent" | "stage">> = [
  { agent: "alpha_discovery", stage: "alpha_discovery" },
  { agent: "cio", stage: "cio_proposal" },
  { agent: "cro", stage: "cro_review" },
  { agent: "autonomous_execution", stage: "execution_feasibility" },
  { agent: "cio", stage: "cio_final" },
];

export function buildL4SnapshotFreezeNode(
  deps: BuildLayer4GraphDeps & { requireL4SnapshotBundle?: boolean },
): (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate> {
  return async (state) => {
    const currentRuntime = runtimeStateForLayer4(state);
    if (currentRuntime.l4_run_snapshot_bundle) {
      throw new Layer4RuntimeContractError("L4 run snapshot bundle was already frozen");
    }
    const resolved = await resolveLayer4SourceBundle(state, "pre_candidate", deps.api);
    const stateWithSources: DailyCycleStateType = {
      ...state,
      layer4_outputs: {
        ...state.layer4_outputs,
        runtime: {
          ...currentRuntime,
          resolved_source_statuses: resolved.statuses,
          source_evidence_observations: resolved.evidence,
        },
      },
    };
    const mirofish = await preloadLayer4MirofishContext(deps, stateWithSources);
    const sourceStatuses = mergeRuntimeSourceStatuses(
      resolved.statuses,
      mirofish.status ? [mirofish.status] : [],
    );
    const cohort = state.active_cohort || "cohort_default";
    const language = pickPromptLanguage(deps.config);
    const promptSnapshots = await Promise.all(
      L4_PROMPT_INVOCATIONS.map(async ({ agent, stage }): Promise<L4RunPromptSnapshot> => {
        if (isResearchKnobsStageEnabled(agent, stage, undefined, cohort)) {
          const loaded = await loadPromptWithKnobs({
            agent,
            cohort,
            stage,
            trafficAssignmentKey: state.trace_id || state.as_of_date,
            ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
          });
          return {
            agent,
            stage,
            prompt_source_hash: layer4PromptSourceHash(loaded.bodies),
            knob_snapshot_hash: loaded.snapshot.hash,
          };
        }
        const prompt = await loadPrompt({
          agent,
          cohort,
          language,
          ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
        });
        return {
          agent,
          stage,
          prompt_source_hash: layer4PromptSourceHash(prompt),
          knob_snapshot_hash: null,
        };
      }),
    );
    const bundle = freezeL4RunSnapshotBundle({
      state: stateWithSources,
      promptSnapshots,
      sourceStatuses,
      mirofishContextHash: layer4MirofishSnapshotHash(mirofish.context),
    });
    const runtime = updateLayer4Runtime(
      currentRuntime,
      {
        l4_run_snapshot_bundle: bundle,
        resolved_source_statuses: sourceStatuses,
        source_evidence_observations: resolved.evidence,
      },
      {
        stage: "l4_snapshot_freeze",
        operation: "source_freeze",
        status: "completed",
        input_hashes: {
          position_snapshot: bundle.position_snapshot_hash,
          upstream_outputs: bundle.upstream_outputs_hash,
          base_market_data: bundle.base_market_data_vintage_hash,
        },
        output_hashes: { l4_run_snapshot_bundle: bundle.bundle_hash },
      },
    );
    return { layer4_outputs: { runtime } };
  };
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
  if (!currentRuntime.l4_run_snapshot_bundle) {
    throw new Layer4RuntimeContractError("candidate_freeze requires L4 run snapshot bundle");
  }
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
  const validated = validateCioPositionActions({
    output,
    currentPositions: state.current_positions,
    knobSnapshot: runtime.cio_final_knob_snapshot,
    sharedPolicyValues,
  });
  const preflightState: DailyCycleStateType = {
    ...state,
    layer4_outputs: { ...state.layer4_outputs, cio: validated.output },
  };
  validateFinalTargetEnvelope(preflightState, validated.output);
  const stateWithValidatedOutput: DailyCycleStateType = {
    ...state,
    layer4_outputs: { ...state.layer4_outputs, cio: validated.output },
  };
  const finalTarget = freezeFinalTarget(stateWithValidatedOutput, validated.output, [
    validatorHash,
  ]);
  const portfolioSummary = buildPortfolioSummary({
    state,
    finalTarget,
    validationStatus: "accepted",
  });
  const updatedRuntime = updateLayer4Runtime(
    runtime,
    { final_target_state: finalTarget, portfolio_summary: portfolioSummary },
    {
      stage: "shared_validation",
      operation: "validation",
      status: "completed",
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

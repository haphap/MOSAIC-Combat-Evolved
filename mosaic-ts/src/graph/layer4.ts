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
import type { AcceptedAgentOutputStore } from "../agents/accepted_output.js";
import {
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
  freezeCroReview,
  freezeCroStageSkip,
  freezeExecutionFeasibility,
  freezeExecutionStageSkip,
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
import { expectedFrozenOrderIntents } from "../agents/decision/runtime_adapter.js";
import {
  authorityBindingFromFrozenObject,
  buildAuthorityStageFrozenObject,
  type DecisionOpportunityAgentId,
  type DecisionRuntimeAuthorityBinding,
  type DecisionSnapshotAuthority,
  type DecisionStageFrozenObject,
} from "../agents/decision/stage_opportunity.js";
import {
  type Layer4SourceResolutionStage,
  mergeRuntimeSourceStatuses,
  resolveLayer4SourceBundle,
} from "../agents/helpers/layer4_source_adapters.js";
import {
  isPrivateKnotStageEnabled,
  privateKnotInvocationContextForState,
} from "../agents/helpers/private_knot_boundary.js";
import { resolveRuntimeSourceStatusesForAgent } from "../agents/helpers/runtime_sources.js";
import {
  prepareAgentToolCapability,
  terminateAgentToolCapability,
} from "../agents/helpers/tool_capability.js";
import { loadPrompt, loadPromptWithPrivateKnot } from "../agents/prompts/loader.js";
import {
  DailyCycleState,
  type DailyCycleStateType,
  type DailyCycleStateUpdate,
} from "../agents/state.js";
import type { AutoExecOutput, CioOutput, CroOutput, L4RunPromptSnapshot } from "../agents/types.js";
import { parseOutcomeStageSkips } from "../autoresearch/outcome_stage_skip.js";
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
  acceptedOutputStore?: AcceptedAgentOutputStore;
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
  "alpha_opportunity_freeze",
  "alpha_discovery",
  "cio_proposal_sources",
  "cio_proposal",
  "candidate_market_sources",
  "candidate_freeze",
  "cro_opportunity_freeze",
  "cro",
  "execution_liquidity_sources",
  "execution_opportunity_freeze",
  "autonomous_execution",
  "cio_opportunity_freeze",
  "cio_final",
  "shared_validation",
] as const;

/** Build (and compile) the Layer-4 decision subgraph. */
export function buildLayer4Graph(deps: BuildLayer4GraphDeps) {
  const strictDeps = { ...deps, requireL4SnapshotBundle: true };
  const graph = new StateGraph(DailyCycleState)
    .addNode("l4_snapshot_freeze", buildL4SnapshotFreezeNode(strictDeps))
    .addNode(
      "alpha_opportunity_freeze",
      buildDecisionOpportunityFreezeNode("alpha_discovery", strictDeps),
    )
    .addNode(
      "alpha_discovery",
      withDecisionOutcomeStageSkip("alpha_discovery", buildAlphaDiscoveryNode(strictDeps)),
    )
    .addNode("cio_proposal_sources", buildSourceResolutionNode(deps, "pre_candidate"))
    .addNode("cio_proposal", buildCioProposalNode(strictDeps))
    .addNode("candidate_market_sources", buildSourceResolutionNode(deps, "candidate_market"))
    .addNode("candidate_freeze", freezeCandidateTargetNode)
    .addNode("cro_opportunity_freeze", buildDecisionOpportunityFreezeNode("cro", strictDeps))
    .addNode("cro", withDecisionOutcomeStageSkip("cro", buildCroNode(strictDeps)))
    .addNode("execution_liquidity_sources", buildSourceResolutionNode(deps, "execution_liquidity"))
    .addNode(
      "execution_opportunity_freeze",
      buildDecisionOpportunityFreezeNode("autonomous_execution", strictDeps),
    )
    .addNode(
      "autonomous_execution",
      withDecisionOutcomeStageSkip(
        "autonomous_execution",
        buildAutonomousExecutionNode(strictDeps),
      ),
    )
    .addNode("cio_opportunity_freeze", buildDecisionOpportunityFreezeNode("cio", strictDeps))
    .addNode("cio_final", buildCioNode(strictDeps))
    .addNode("shared_validation", validateFinalTargetNode);

  // Serial L4: keep one LLM/tool stream active at a time.
  chainEdges(graph, serialEdges([START, ...LAYER4_RUNTIME_NODES, END] as const));

  return graph.compile();
}

function buildDecisionOpportunityFreezeNode(
  agentId: DecisionOpportunityAgentId,
  deps: BuildLayer4GraphDeps,
): (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate> {
  return async (state) => {
    if (!state.darwinian_runtime_binding) return {};
    if (!deps.api) throw new Error(`${agentId}: stage opportunity bridge is unavailable`);
    const schedule = state.outcome_schedule_plan;
    if (!schedule) throw new Error(`${agentId}: outcome schedule is unavailable`);
    const slots = schedule.slots.filter((slot) => slot.agent_id === agentId);
    if (slots.length !== 1) throw new Error(`${agentId}: outcome schedule slot is ambiguous`);
    const slot = slots[0];
    if (!slot) throw new Error(`${agentId}: outcome schedule slot is unavailable`);
    if (slot.run_slot_kind === "DOWNSTREAM_ONLY") return {};
    if (agentId !== "cio" && state.outcome_stage_skips[agentId]) return {};
    if (!slot.scheduled_sample_id) throw new Error(`${agentId}: scheduled sample ID is missing`);
    const frozenObject = await stageFrozenObject(agentId, state, deps);
    const result = await deps.api.darwinianFreezeStageOutcomeOpportunity({
      outcome_schedule_plan_id: schedule.outcome_schedule_plan_id,
      scheduled_sample_id: slot.scheduled_sample_id,
      agent_id: agentId,
      recorded_at: schedule.prepared_at,
      ...(frozenObject ? { frozen_object: { ...frozenObject } } : {}),
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
    if (
      frozenObject &&
      (frozenObject.frozen_object_set_id !== frozenId ||
        frozenObject.frozen_object_set_hash !== frozenHash)
    ) {
      throw new Error(`${agentId}: stage opportunity changed the frozen runtime object`);
    }
    const expectedAuthority = authorityBindingFromFrozenObject(frozenObject);
    const runtimeAuthority = parseRuntimeAuthorityBinding(
      result.runtime_authority_binding,
      agentId,
    );
    if (
      Object.entries(expectedAuthority).some(
        ([field, expected]) =>
          runtimeAuthority[field as keyof DecisionRuntimeAuthorityBinding] !== expected,
      )
    ) {
      throw new Error(`${agentId}: stage opportunity changed the runtime authority binding`);
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
          runtime_authority_binding: runtimeAuthority,
          ...(agentId === "alpha_discovery" ? alphaRuntimeAuthorityPins(runtimeAuthority) : {}),
        },
      },
      ...(Object.keys(stageSkips).length > 0 ? { outcome_stage_skips: stageSkips } : {}),
    };
  };
}

async function stageFrozenObject(
  agentId: DecisionOpportunityAgentId,
  state: DailyCycleStateType,
  deps: BuildLayer4GraphDeps,
): Promise<DecisionStageFrozenObject> {
  return buildRuntimeDecisionStageFrozenObject(agentId, state, deps);
}

async function buildRuntimeDecisionStageFrozenObject(
  agentId: DecisionOpportunityAgentId,
  state: DailyCycleStateType,
  deps: BuildLayer4GraphDeps,
): Promise<DecisionStageFrozenObject> {
  if (!deps.api) throw new Error(`${agentId}: candidate authority bridge is unavailable`);
  const acceptedOutputRefs = acceptedRefsForPrefixes(state, authoritySourcePrefixes(agentId));
  const scope = { accepted_output_refs: acceptedOutputRefs };
  const prepared = await prepareAgentToolCapability({
    api: deps.api,
    state,
    agentId,
    stage: authorityStage(agentId),
    runtimeInputs: scope,
    candidateScope: scope,
  });
  try {
    const toolId = authorityToolId(agentId);
    const result = await deps.api.toolsCall(toolId, {}, prepared.capability);
    let snapshot: unknown;
    try {
      snapshot = JSON.parse(result.text);
    } catch (cause) {
      throw new Error(`${agentId}: candidate authority is not valid JSON`, { cause });
    }
    if (snapshot === null || typeof snapshot !== "object" || Array.isArray(snapshot)) {
      throw new Error(`${agentId}: candidate authority must be an object`);
    }
    return buildAuthorityStageFrozenObject(agentId, snapshot as DecisionSnapshotAuthority);
  } finally {
    await terminateAgentToolCapability(deps.api, prepared, `${agentId}_outcome_opportunity_frozen`);
  }
}

function authorityToolId(
  agentId: DecisionOpportunityAgentId,
): DecisionRuntimeAuthorityBinding["source_tool_id"] {
  return {
    alpha_discovery: "get_alpha_candidate_snapshot",
    cro: "get_cro_risk_snapshot",
    autonomous_execution: "get_execution_snapshot",
    cio: "get_cio_decision_snapshot",
  }[agentId] as DecisionRuntimeAuthorityBinding["source_tool_id"];
}

function authorityStage(
  agentId: DecisionOpportunityAgentId,
): Exclude<DecisionOpportunityAgentId, "cio"> | "cio_final" {
  return agentId === "cio" ? "cio_final" : agentId;
}

function authoritySourcePrefixes(agentId: DecisionOpportunityAgentId): readonly string[] {
  if (agentId === "alpha_discovery") {
    return ["STANDARD_SECTOR_SELECTION:", "RELATIONSHIP_GRAPH:", "SUPERINVESTOR_SELECTION:"];
  }
  if (agentId === "cro") return ["CIO_PROPOSAL:"];
  if (agentId === "autonomous_execution") {
    return ["CIO_PROPOSAL:", "CRO_RISK_REVIEW:"];
  }
  return ["CIO_PROPOSAL:", "CRO_RISK_REVIEW:", "EXECUTION_ASSESSMENT:"];
}

function acceptedRefsForPrefixes(
  state: DailyCycleStateType,
  prefixes: readonly string[],
): Array<Record<string, unknown>> {
  return Object.entries(state.accepted_output_refs)
    .filter(([key]) => prefixes.some((prefix) => key.startsWith(prefix)))
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, ref]) => ({ key, ...ref }));
}

function alphaRuntimeAuthorityPins(authority: DecisionRuntimeAuthorityBinding): {
  runtime_candidate_scope_hash: string;
  runtime_candidate_universe_hash: string;
} {
  return {
    runtime_candidate_scope_hash: authority.candidate_scope_hash,
    runtime_candidate_universe_hash: authority.candidate_universe_hash,
  };
}

function parseRuntimeAuthorityBinding(
  value: unknown,
  agentId: DecisionOpportunityAgentId,
): DecisionRuntimeAuthorityBinding {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${agentId}: runtime authority binding is unavailable`);
  }
  const record = value as Record<string, unknown>;
  const expectedFields = [
    "candidate_scope_hash",
    "candidate_universe_hash",
    "source_snapshot_hash",
    "source_tool_id",
    "upstream_accepted_output_refs_hash",
  ];
  if (Object.keys(record).sort().join("\0") !== expectedFields.join("\0")) {
    throw new Error(`${agentId}: runtime authority binding fields mismatch`);
  }
  const sourceToolId = authorityToolId(agentId);
  if (record.source_tool_id !== sourceToolId) {
    throw new Error(`${agentId}: runtime authority tool mismatch`);
  }
  return {
    source_tool_id: sourceToolId,
    source_snapshot_hash: requiredSha256(
      record.source_snapshot_hash,
      `${agentId}.source_snapshot_hash`,
    ),
    candidate_scope_hash: requiredSha256(
      record.candidate_scope_hash,
      `${agentId}.candidate_scope_hash`,
    ),
    candidate_universe_hash: requiredSha256(
      record.candidate_universe_hash,
      `${agentId}.candidate_universe_hash`,
    ),
    upstream_accepted_output_refs_hash: requiredSha256(
      record.upstream_accepted_output_refs_hash,
      `${agentId}.upstream_accepted_output_refs_hash`,
    ),
  };
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} is missing`);
  return value;
}

function requiredSha256(value: unknown, label: string): string {
  const text = requiredText(value, label);
  if (!/^sha256:[0-9a-f]{64}$/.test(text)) throw new Error(`${label} is not a sha256 hash`);
  return text;
}

function withDecisionOutcomeStageSkip(
  agentId: "alpha_discovery" | "cro" | "autonomous_execution",
  node: (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>,
): (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate> {
  return async (state) => {
    const stageSkip = state.outcome_stage_skips[agentId];
    const currentRuntime = runtimeStateForLayer4(state);
    const runId = state.trace_id || state.as_of_date || "current_run";
    if (!stageSkip) {
      if (!state.darwinian_runtime_binding && agentId === "cro") {
        const candidate = currentRuntime.candidate_target_state;
        if (candidate && candidate.portfolio_actions.length === 0) {
          const output: CroOutput = {
            agent: "cro",
            review_disposition: "NO_OBJECTION",
            rejected_picks: [],
            required_adjustments: [],
            correlated_risks: [],
            black_swan_scenarios: [],
            confidence: 0,
          };
          const review = freezeCroReview(runId, candidate, output);
          return {
            layer4_outputs: {
              cro: output,
              runtime: updateLayer4Runtime(
                currentRuntime,
                { cro_review_state: review },
                {
                  stage: "cro_review",
                  operation: "stage_skip",
                  status: "skipped",
                  reason_codes: ["NO_EVALUATION_OBJECT"],
                  input_hashes: layer4SkipInputHashes(currentRuntime),
                  output_hashes: { cro_review_state: review.review_hash },
                },
              ),
            },
          };
        }
      }
      if (!state.darwinian_runtime_binding && agentId === "autonomous_execution") {
        const candidate = currentRuntime.candidate_target_state;
        const croReview = currentRuntime.cro_review_state;
        if (
          candidate &&
          croReview &&
          expectedFrozenOrderIntents(candidate, croReview).order_intents.length === 0
        ) {
          const output: AutoExecOutput = {
            agent: "autonomous_execution",
            execution_disposition: "NO_DELTA",
            trades: [],
            execution_checks: [],
            confidence: 0,
          };
          const feasibility = freezeExecutionFeasibility(
            runId,
            currentRuntime.candidate_target_state,
            currentRuntime.cro_review_state,
            output,
            currentRuntime.resolved_source_statuses,
            state.as_of_date || "live",
          );
          return {
            layer4_outputs: {
              autonomous_execution: output,
              runtime: updateLayer4Runtime(
                currentRuntime,
                { execution_feasibility_state: feasibility },
                {
                  stage: "execution_feasibility",
                  operation: "stage_skip",
                  status: "skipped",
                  reason_codes: ["NO_EVALUATION_OBJECT"],
                  input_hashes: layer4SkipInputHashes(currentRuntime),
                  output_hashes: {
                    execution_feasibility_state: feasibility.feasibility_hash,
                  },
                },
              ),
            },
          };
        }
      }
      return node(state);
    }
    if (agentId === "alpha_discovery") {
      return {
        layer4_outputs: {
          runtime: updateLayer4Runtime(
            currentRuntime,
            {},
            {
              stage: "alpha_discovery",
              operation: "stage_skip",
              status: "skipped",
              reason_codes: ["NO_EVALUATION_OBJECT"],
              input_hashes: {},
              output_hashes: { stage_skip: stageSkip.stage_skip_hash },
            },
          ),
        },
      };
    }
    if (agentId === "cro") {
      const review = freezeCroStageSkip(runId, currentRuntime.candidate_target_state, stageSkip);
      return {
        layer4_outputs: {
          runtime: updateLayer4Runtime(
            currentRuntime,
            { cro_review_state: review },
            {
              stage: "cro_review",
              operation: "stage_skip",
              status: "skipped",
              reason_codes: ["NO_EVALUATION_OBJECT"],
              input_hashes: layer4SkipInputHashes(currentRuntime),
              output_hashes: {
                stage_skip: stageSkip.stage_skip_hash,
                cro_review_state: review.review_hash,
              },
            },
          ),
        },
      };
    }
    const feasibility = freezeExecutionStageSkip(
      runId,
      currentRuntime.candidate_target_state,
      currentRuntime.cro_review_state,
      stageSkip,
    );
    return {
      layer4_outputs: {
        runtime: updateLayer4Runtime(
          currentRuntime,
          { execution_feasibility_state: feasibility },
          {
            stage: "execution_feasibility",
            operation: "stage_skip",
            status: "skipped",
            reason_codes: ["NO_EVALUATION_OBJECT"],
            input_hashes: layer4SkipInputHashes(currentRuntime),
            output_hashes: {
              stage_skip: stageSkip.stage_skip_hash,
              execution_feasibility_state: feasibility.feasibility_hash,
            },
          },
        ),
      },
    };
  };
}

function layer4SkipInputHashes(runtime: ReturnType<typeof runtimeStateForLayer4>) {
  return {
    ...(runtime.candidate_target_state
      ? { candidate_target_state: runtime.candidate_target_state.candidate_target_hash }
      : {}),
    ...(runtime.cro_review_state ? { cro_review_state: runtime.cro_review_state.review_hash } : {}),
  };
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
        if (isPrivateKnotStageEnabled(agent, stage, cohort)) {
          const loaded = await loadPromptWithPrivateKnot({
            agent,
            cohort,
            stage,
            trafficAssignmentKey: state.trace_id || state.as_of_date,
            invocationContext: privateKnotInvocationContextForState(state),
            runtimeSourceStatuses: [
              ...resolveRuntimeSourceStatusesForAgent(stateWithSources, agent, stage),
              ...(mirofish.status ? [mirofish.status] : []),
            ],
            ...(state.darwinian_runtime_binding
              ? { requirePinnedPrivateRelease: true as const }
              : {}),
            ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
          });
          return {
            agent,
            stage,
            prompt_source_hash: layer4PromptSourceHash(loaded.bodies),
            private_knot_snapshot_hash: loaded.snapshot.snapshot_hash,
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
          private_knot_snapshot_hash: null,
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
  const validatorHash = stableRuntimeHash({
    validator: "validateCioPositionActions.v1",
    risk_policy: "fixed_public_risk_contract_v1",
  });
  const validated = validateCioPositionActions({
    output,
    currentPositions: state.current_positions,
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

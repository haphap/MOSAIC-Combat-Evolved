/**
 * Generic factory for Layer-4 decision agent nodes (Plan §11.2 sub-step 2D.3).
 *
 * Differs structurally from L1/L2/L3 factories:
 *   * Layer 4 primarily synthesises upstream state, but may expose a small
 *     required tool set such as RKE research context when deps.api is present.
 *   * **Each agent's user-context build is custom** — cro reads L1+L2+L3,
 *     alpha reads L1+L2+L3, autonomous_execution reads cro+alpha+L3, cio
 *     reads everything. The spec carries a ``buildUserContext`` function
 *     so each agent picks exactly what it needs.
 *
 * State writes:
 *   * ``layer4_outputs[<stateUpdateField>]`` (cro / alpha_discovery /
 *     autonomous_execution / cio).
 *   * shared validation, outside this factory, is the only writer of the
 *     top-level ``portfolio_actions`` channel.
 *   * ``llm_calls`` append.
 */

import { type BaseMessage, HumanMessage, SystemMessage } from "@langchain/core/messages";
import { type StructuredToolInterface, tool } from "@langchain/core/tools";
import { z } from "zod";
import {
  type PromptReleaseCanaryEvent,
  persistPromptReleaseCanaryEvents,
} from "../../autoresearch/prompt_release_canary_slo.js";
import {
  type BridgeApi,
  type MirofishContext,
  type MosaicConfig,
  pickBridgeTools,
} from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import { formatMirofishContext } from "../../mirofish/context.js";
import {
  type AcceptedAgentOutputRecord,
  type AcceptedAgentOutputStore,
  type AcceptedOutputKind,
  type AcceptedOutputRecordRef,
  acceptedOutputBuildContextFromState,
  acceptedOutputRefKey,
  buildAcceptedAgentOutputRecord,
  canonicalAcceptedOutputHash,
} from "../accepted_output.js";
import { runAgentToolLoop } from "../helpers/agent_loop.js";
import { type AgentRunAudit, invokeStrictStructured } from "../helpers/agent_run_contract.js";
import { evidenceLineageEnvelopeFromGraph } from "../helpers/causal_evidence_resolution.js";
import { extractTextContent } from "../helpers/content.js";
import {
  buildAgentInvocationId,
  buildRuntimeEvidenceSnapshot,
  type RuntimeEvidenceSnapshot,
} from "../helpers/evidence_runtime.js";
import {
  canonicalAcceptedSubmissionBody,
  MACRO_ATTRIBUTION_PROVIDER_INSTRUCTION,
  resolveMacroInputAttributions,
} from "../helpers/macro_attribution.js";
import { acceptedMacroOutputs } from "../helpers/macro_context.js";
import {
  type AgentCanaryEventContext,
  agentCanaryEventContext,
  beginAgentPromptCanaryInvocation,
  buildAgentPromptCanaryEvent,
} from "../helpers/prompt_canary.js";
import {
  isResearchKnobsStageEnabled,
  type ResearchKnobCapAudit,
  type ResearchKnobsSnapshot,
  type RuntimeSourceStatus,
  type ToolStatus,
} from "../helpers/research_knobs.js";
import {
  buildLlmCall,
  extractLlmTokenUsage,
  formatAgentEvent,
  formatDurationMs,
  formatTokenMetricFields,
  resolveAgentTimeoutMs,
  safeErrorMessage,
  summarizeAgentOutput,
  withAgentTimeout,
} from "../helpers/runtime.js";
import { resolveRuntimeSourceStatusesForAgent } from "../helpers/runtime_sources.js";
import { validateStrictAgentOutput } from "../helpers/strict_agent_validation.js";
import {
  type AgentExecutionStageId,
  prepareAgentToolCapability,
  terminateAgentToolCapability,
} from "../helpers/tool_capability.js";
import { type LoaderLanguage, loadPrompt, loadPromptWithKnobs } from "../prompts/loader.js";
import type { RuntimeAgentStageId } from "../prompts/runtime_agent_spec.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type {
  AutoExecOutput,
  CioOutput,
  CroOutput,
  Layer4AgentOutputKey,
  Layer4Outputs,
  Layer4RuntimeTraceEntry,
  LlmCallRecord,
} from "../types.js";
import {
  type AcceptedAlphaDiscovery,
  type AcceptedCioProposal,
  type AcceptedCroRiskReview,
  type AcceptedExecutionAssessment,
  type AutonomousExecutionSubmission,
  alphaDiscoveryPayload,
  buildAcceptedAlphaDiscovery,
  buildAcceptedCioFinal,
  buildAcceptedCioProposal,
  buildAcceptedCroRiskReview,
  buildAcceptedExecutionAssessment,
  type CioFinalSubmission,
  type CioProposalSubmission,
  type CroAgentSubmission,
  cioDecisionPayload,
  croRiskReviewPayload,
  type DecisionAgentSubmission,
  type DecisionControlSourceRef,
  type DecisionStageSourceRef,
  decisionMacroAttributionTargets,
} from "./accepted.js";
import {
  assertL4RunSnapshotStage,
  freezeCioProposal,
  freezeCroReview,
  freezeExecutionFeasibility,
  layer4PromptSourceHash,
  runtimeStateForLayer4,
  stableRuntimeHash,
  updateLayer4Runtime,
  validateFinalTargetEnvelope,
} from "./layer4_runtime.js";
import { validateCioPositionActions } from "./position_validator.js";
import {
  decisionSubmissionToRuntimeOutput,
  expectedFrozenOrderIntents,
  frozenCandidateRef,
} from "./runtime_adapter.js";
import {
  buildRuntimeAlphaDiscoverySubmissionSchema,
  CioFinalAllCashSubmissionSchema,
  CioFinalWithoutHoldSubmissionSchema,
  CioProposalAllCashSubmissionSchema,
  CioProposalWithoutHoldSubmissionSchema,
  type FrozenAlphaCandidate,
} from "./submission_schemas.js";

/** Union of the 4 Layer-4 outputs handled by this factory. */
export type Layer4AgentOutput = DecisionAgentSubmission;

export interface LayerFourAgentSpec<TOutput extends Layer4AgentOutput> {
  agentId: string;
  runtimeStage: RuntimeAgentStageId;
  stateWriteMode?: "agent_output" | "cio_proposal" | "cio_final";
  schema: z.ZodTypeAny;
  fieldNames: ReadonlyArray<string>;
  /** The Layer4Outputs slot this agent populates. */
  stateUpdateField: Layer4AgentOutputKey;
  /** Build the user-context prose; each L4 agent reads different upstream layers.
   *  May be async — autonomous_execution fetches Darwinian weights from the
   *  bridge (Plan §11.3 sub-step 3F). */
  buildUserContext: (
    state: DailyCycleStateType,
    acceptedOutputStore?: AcceptedAgentOutputStore,
  ) => string | Promise<string>;
  /** Bridge tools this decision agent may call during synthesis. */
  requiredTools?: ReadonlyArray<string>;
  render: (output: TOutput) => string;
  structuredOnlySentences?: ReadonlyArray<string>;
  buildExtractorSystem?: (lang: LoaderLanguage) => string;
}

export interface LayerFourAgentDeps {
  llmHandle: LlmHandle;
  /** Optional for tests; production daily-cycle passes it so L4 can use tools. */
  api?: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
  /** Per-run cache so CRO, execution, and CIO consume the same MiroFish context. */
  mirofishContextCache?: Map<string, Promise<MirofishContextLoadResult>>;
  /** Canonical graph sets this; direct unit nodes may omit the graph-level bundle. */
  requireL4SnapshotBundle?: boolean;
  /** Shared accepted-output resolver; required for formal production transport. */
  acceptedOutputStore?: AcceptedAgentOutputStore;
}

export type LayerFourAgentNode = (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>;

export interface MirofishContextLoadResult {
  context: MirofishContext | null;
  status: RuntimeSourceStatus | null;
}

export function buildLayerFourAgentNode<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  deps: LayerFourAgentDeps,
): LayerFourAgentNode {
  return async function layerFourAgentNode(state) {
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const timeoutMs = resolveAgentTimeoutMs(deps.agentTimeoutSeconds);
    const onLog = deps.onLog ?? (() => undefined);
    const startedAt = Date.now();
    let canaryContext: AgentCanaryEventContext | null = null;
    let canaryKnobSnapshot: ResearchKnobsSnapshot | null = null;
    let canaryToolStatuses: ReadonlyArray<ToolStatus> = [];
    onLog(
      formatAgentEvent("start", "L4", spec.agentId, [
        `timeout=${timeoutMs > 0 ? formatDurationMs(timeoutMs) : "off"}`,
      ]),
    );

    try {
      return await withAgentTimeout(
        async (signal) => {
          const cohort = state.active_cohort || "cohort_default";
          const language = pickPromptLanguage(deps.config);
          onLog(formatAgentEvent("phase", "L4", spec.agentId, ["prepare"]));
          const mirofish = await maybeLoadMirofishContext(spec, deps, state);

          // Phase 0: load prompt.
          let knobSnapshot: ResearchKnobsSnapshot | null = null;
          let systemPrompt: string;
          let promptSourceHash: string;
          if (isResearchKnobsStageEnabled(spec.agentId, spec.runtimeStage, undefined, cohort)) {
            const runtimeSourceStatuses = [
              ...resolveRuntimeSourceStatusesForAgent(state, spec.agentId, spec.runtimeStage),
              ...(mirofish.status ? [mirofish.status] : []),
            ];
            const loaded = await loadPromptWithKnobs({
              agent: spec.agentId,
              cohort,
              stage: spec.runtimeStage,
              trafficAssignmentKey: state.trace_id || state.as_of_date,
              runtimeSourceStatuses,
              onReleaseAssigned: async (release) => {
                canaryContext = await beginAgentPromptCanaryInvocation({
                  release,
                  state,
                  agent: spec.agentId,
                  stage: spec.runtimeStage,
                  cohort,
                });
              },
              ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
            });
            knobSnapshot = loaded.snapshot;
            systemPrompt = loaded.prompt;
            promptSourceHash = layer4PromptSourceHash(loaded.bodies);
            canaryKnobSnapshot = loaded.snapshot;
            canaryContext = agentCanaryEventContext({
              release: loaded.release,
              state,
              agentInvocationId:
                canaryContext?.agentInvocationId ??
                buildAgentInvocationId({
                  runId: state.trace_id || state.as_of_date || "current_run",
                  agent: spec.agentId,
                  stage: spec.runtimeStage,
                  cohort,
                  asOf: state.as_of_date || "live",
                  snapshotHash: loaded.snapshot.hash,
                }),
              systemPrompt,
            });
          } else {
            systemPrompt = await loadPrompt({
              agent: spec.agentId,
              cohort,
              language,
              ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
            });
            promptSourceHash = layer4PromptSourceHash(systemPrompt);
          }
          if (deps.requireL4SnapshotBundle || runtimeStateForLayer4(state).l4_run_snapshot_bundle) {
            assertL4RunSnapshotStage({
              state,
              agent: spec.agentId,
              stage: spec.runtimeStage,
              promptSourceHash,
              knobSnapshotHash: knobSnapshot?.hash ?? null,
              mirofishContextHash: layer4MirofishSnapshotHash(mirofish.context),
            });
          }

          // Phase 1: synthesis, with optional tools when the spec requires them.
          const userContext = await spec.buildUserContext(state, deps.acceptedOutputStore);
          const augmentedContext = await maybeAppendMirofishContext(
            spec,
            userContext,
            deps,
            language,
            mirofish.context,
          );
          let runtimeEvidence: RuntimeEvidenceSnapshot | null = buildRuntimeEvidenceSnapshot({
            state,
            agent: spec.agentId,
            stage: spec.runtimeStage,
            knobSnapshot,
          });
          const evidenceAugmentedContext = runtimeEvidence
            ? `${augmentedContext}\n\n${runtimeEvidence.visibleCatalog}`
            : augmentedContext;
          const requiredTools = spec.requiredTools ?? [];
          let analysisText = "";
          let analysisLlmInvocations = 1;
          let toolCalls = 0;
          let toolCacheHits = 0;
          let toolExecutions = 0;
          let promptTokens = 0;
          let completionTokens = 0;
          let llmElapsedMs = 0;
          let toolStatuses: ReadonlyArray<ToolStatus> = [];
          let toolLoopMessages: readonly BaseMessage[] = [];
          if (
            requiredTools.length > 0 &&
            (deps.llmHandle.provider === "fake" || hasToolApi(deps.api))
          ) {
            const preparedCapability =
              deps.llmHandle.provider === "fake"
                ? null
                : await prepareAgentToolCapability({
                    api: deps.api as BridgeApi,
                    state,
                    agentId: spec.agentId,
                    stage: decisionCapabilityStage(spec),
                    runtimeInputs: {
                      macro_input_gate: state.macro_input_gate,
                      ...(state.darwinian_runtime_binding
                        ? { accepted_output_refs: state.accepted_output_refs }
                        : {
                            layer1_outputs: state.layer1_outputs,
                            layer2_outputs: state.layer2_outputs,
                            layer3_outputs: state.layer3_outputs,
                          }),
                      layer4_outputs: state.layer4_outputs,
                      current_positions: state.current_positions,
                    },
                    candidateScope: decisionCandidateScope(state, spec),
                  });
            const tools = preparedCapability
              ? await pickBridgeTools(deps.api as BridgeApi, requiredTools, {
                  capability: preparedCapability.capability,
                })
              : requiredTools.map((name) =>
                  buildFakeDecisionSnapshotTool(name, spec.agentId, state.as_of_date),
                );
            let loopResult!: Awaited<ReturnType<typeof runAgentToolLoop>>;
            try {
              loopResult = await runAgentToolLoop({
                llm: deps.llmHandle.llm,
                tools: tools as StructuredToolInterface[],
                systemMessage: systemPrompt,
                initialMessages: [new HumanMessage(evidenceAugmentedContext)],
                initialToolCalls: requiredTools.map((name) => ({ name, args: {} })),
                allowModelToolCalls: false,
                ...(runtimeEvidence
                  ? { agentInvocationId: runtimeEvidence.agentInvocationId }
                  : {}),
                onLog: (msg) => onLog(formatAgentEvent("phase", "L4", spec.agentId, [msg])),
                signal,
              });
            } finally {
              if (preparedCapability) {
                await terminateAgentToolCapability(
                  deps.api as BridgeApi,
                  preparedCapability,
                  "decision_snapshot_research_completed",
                );
              }
            }
            analysisText = loopResult.analysisText;
            analysisLlmInvocations = loopResult.llmInvocations;
            toolCalls = loopResult.toolCalls;
            toolCacheHits = loopResult.toolCacheHits;
            toolExecutions = loopResult.toolExecutions;
            promptTokens = loopResult.promptTokens;
            completionTokens = loopResult.completionTokens;
            llmElapsedMs = loopResult.llmElapsedMs;
            toolStatuses = loopResult.toolStatuses;
            toolLoopMessages = loopResult.messages;
            canaryToolStatuses = toolStatuses;
            runtimeEvidence = buildRuntimeEvidenceSnapshot({
              state,
              agent: spec.agentId,
              stage: spec.runtimeStage,
              knobSnapshot,
              toolStatuses,
            });
          } else if (requiredTools.length === 0) {
            onLog(formatAgentEvent("phase", "L4", spec.agentId, ["synthesis_llm=1"]));
            const llmStartedAt = Date.now();
            const analysisResponse = await deps.llmHandle.llm.invoke(
              [new SystemMessage(systemPrompt), new HumanMessage(evidenceAugmentedContext)],
              signal ? { signal } : undefined,
            );
            llmElapsedMs = Date.now() - llmStartedAt;
            const usage = extractLlmTokenUsage(analysisResponse);
            promptTokens = usage.promptTokens;
            completionTokens = usage.completionTokens;
            analysisText =
              typeof analysisResponse.content === "string"
                ? analysisResponse.content
                : extractTextContent(analysisResponse.content);
          } else {
            throw new Error(`${spec.agentId}: required capability tool API is unavailable`);
          }

          // Phase 2: structured extraction.
          onLog(
            formatAgentEvent("phase", "L4", spec.agentId, [`extract chars=${analysisText.length}`]),
          );
          const extractorSystem = spec.buildExtractorSystem
            ? spec.buildExtractorSystem(language)
            : defaultExtractorSystem(spec, language);
          const emptyPortfolio = state.current_positions.positions.length === 0;
          const allCashRequired =
            spec.agentId === "cio" && cioAllCashRequired(state, spec.runtimeStage);
          const alphaSchema =
            spec.agentId === "alpha_discovery"
              ? buildRuntimeAlphaDiscoverySubmissionSchema(
                  frozenAlphaCandidatesFromToolLoop(toolLoopMessages, toolStatuses),
                )
              : null;
          const extractionSchema = alphaSchema
            ? (alphaSchema as z.ZodType<TOutput>)
            : allCashRequired
              ? ((spec.runtimeStage === "cio_proposal"
                  ? CioProposalAllCashSubmissionSchema
                  : CioFinalAllCashSubmissionSchema) as unknown as z.ZodType<TOutput>)
              : spec.agentId === "cio" && emptyPortfolio
                ? ((spec.runtimeStage === "cio_proposal"
                    ? CioProposalWithoutHoldSubmissionSchema
                    : CioFinalWithoutHoldSubmissionSchema) as unknown as z.ZodType<TOutput>)
                : (spec.schema as z.ZodType<TOutput>);
          const extractor = await invokeStrictStructured<TOutput>({
            llm: structuredHandle.llm,
            schema: extractionSchema,
            messages: [
              new SystemMessage(extractorSystem),
              new HumanMessage(
                [
                  analysisText || "(no analysis produced)",
                  "## Frozen Decision submission constraints",
                  augmentedContext,
                  runtimeEvidence?.visibleCatalog,
                ]
                  .filter((part): part is string => Boolean(part))
                  .join("\n\n"),
              ),
            ],
            agent: spec.agentId,
            stage: spec.runtimeStage,
            runId: state.trace_id || state.as_of_date || "current_run",
            evidenceSnapshot: runtimeEvidence,
            validate: (candidate) => {
              let validated = validateStrictAgentOutput({
                output: candidate,
                schema: spec.schema as z.ZodType<TOutput>,
                agent: spec.agentId,
                stage: spec.runtimeStage,
                runtimeEvidence,
                knobSnapshot,
                toolStatuses,
                currentPositions: state.current_positions,
              });
              if (validated.issues.length === 0) {
                try {
                  validateLayer4StageSemantics(spec, state, validated.output);
                } catch (error) {
                  validated = {
                    output: validated.output,
                    issues: [
                      {
                        validator: `decision.${spec.runtimeStage}.semantic_validator.v1`,
                        reason_code: "L4_SEMANTIC_REJECTED",
                        json_path: "$",
                        message: error instanceof Error ? error.message : String(error),
                      },
                    ],
                  };
                }
              }
              return validated;
            },
            isAcceptedEmpty: (candidate) => isAcceptedEmptyDecision(candidate),
            signal,
          });
          promptTokens += extractor.audit.attempts.reduce(
            (sum, attempt) => sum + attempt.prompt_tokens,
            0,
          );
          completionTokens += extractor.audit.attempts.reduce(
            (sum, attempt) => sum + attempt.completion_tokens,
            0,
          );

          const output = extractor.output;
          const canaryEvent = buildAgentPromptCanaryEvent({
            context: canaryContext,
            agent: spec.agentId,
            stage: spec.runtimeStage,
            startedAt,
            structuredAccepted: true,
            claimGraphAccepted: true,
            knobSnapshot,
            knobAudit:
              (output as TOutput & { verified_knob_audit?: ResearchKnobCapAudit })
                .verified_knob_audit ?? null,
            toolStatuses,
            output,
            validatorIds: [
              `${spec.agentId}.${spec.runtimeStage}.structured_output.v1`,
              "evidence_claim_graph_v1",
              "research_knobs_runtime_v1",
              ...(spec.stateUpdateField === "autonomous_execution"
                ? ["decision.execution_submission_semantics_v2"]
                : []),
            ],
          });
          if (canaryEvent) await persistPromptReleaseCanaryEvents([canaryEvent]);
          onLog(
            formatAgentEvent("done", "L4", spec.agentId, [
              `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
              `analysis_llm=${analysisLlmInvocations}`,
              `tools=${toolCalls}`,
              `tool_cache_hits=${toolCacheHits}`,
              `tool_executions=${toolExecutions}`,
              ...formatTokenMetricFields(promptTokens, completionTokens, llmElapsedMs),
              `source=${extractor.audit.output_source}`,
              ...(runtimeEvidence
                ? [
                    `evidence_entries=${runtimeEvidence.evidenceLedger.length}`,
                    "claim_output=accepted",
                    "claim_rejections=0",
                  ]
                : []),
              summarizeAgentOutput(output),
            ]),
          );

          return buildLayerFourUpdate(
            spec,
            output,
            buildLlmCall(spec.agentId, structuredHandle, { promptTokens, completionTokens }),
            {
              state,
              knobSnapshot,
              canaryEvent,
              audit: extractor.audit,
              acceptedOutputStore: deps.acceptedOutputStore,
            },
          );
        },
        timeoutMs,
        `L4 ${spec.agentId}`,
      );
    } catch (err) {
      onLog(
        formatAgentEvent("error", "L4", spec.agentId, [
          `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
          `message=${safeErrorMessage(err)}`,
        ]),
      );
      const failureEvent = buildAgentPromptCanaryEvent({
        context: canaryContext,
        agent: spec.agentId,
        stage: spec.runtimeStage,
        startedAt,
        structuredAccepted: false,
        claimGraphAccepted: false,
        knobSnapshot: canaryKnobSnapshot,
        knobAudit: null,
        toolStatuses: canaryToolStatuses,
        output: null,
        validatorIds: [
          `${spec.agentId}.${spec.runtimeStage}.structured_output.v1`,
          "evidence_claim_graph_v1",
          "research_knobs_runtime_v1",
        ],
        forceFallback: true,
        forceSourceFailure: true,
      });
      if (failureEvent) await persistPromptReleaseCanaryEvents([failureEvent]);
      throw err;
    }
  };
}

function validateLayer4StageSemantics<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  state: DailyCycleStateType,
  output: TOutput,
): void {
  const runtime = runtimeStateForLayer4(state);
  const runId = state.trace_id || state.as_of_date || "current_run";
  const runtimeOutput = decisionSubmissionToRuntimeOutput(output, state);
  if (spec.runtimeStage === "cio_proposal") {
    freezeCioProposal(state, runtimeOutput as CioOutput);
    return;
  }
  if (spec.runtimeStage === "cro_review") {
    validateCroFrozenUniverse(output as CroAgentSubmission, state);
    freezeCroReview(runId, runtime.candidate_target_state, runtimeOutput as CroOutput);
    return;
  }
  if (spec.runtimeStage === "execution_feasibility") {
    validateExecutionFrozenIntentSet(output as AutonomousExecutionSubmission, state);
    freezeExecutionFeasibility(
      runId,
      runtime.candidate_target_state,
      runtime.cro_review_state,
      runtimeOutput as AutoExecOutput,
      runtime.resolved_source_statuses,
      state.as_of_date || "live",
    );
    return;
  }
  if (spec.runtimeStage === "cio_final") {
    const validated = validateCioPositionActions({
      output: runtimeOutput as CioOutput,
      currentPositions: state.current_positions,
      knobSnapshot: runtime.cio_final_knob_snapshot,
      sharedPolicyValues: activeKnobValuesFromUpstreamDecisionAgents(state.layer4_outputs),
    });
    validateFinalTargetEnvelope(
      { ...state, layer4_outputs: { ...state.layer4_outputs, cio: validated.output } },
      validated.output,
    );
  }
}

function validateCroFrozenUniverse(
  submission: CroAgentSubmission,
  state: DailyCycleStateType,
): void {
  const candidate = state.layer4_outputs.runtime?.candidate_target_state;
  if (!candidate) throw new Error("CRO requires a frozen candidate universe");
  if (submission.candidate_actions.length !== candidate.portfolio_actions.length) {
    throw new Error("CRO candidate_actions must cover the frozen candidate universe one-to-one");
  }
  const expected = new Map(
    candidate.portfolio_actions.map((position) => [
      position.ticker,
      frozenCandidateRef(candidate.candidate_target_hash, position.ticker),
    ]),
  );
  for (const action of submission.candidate_actions) {
    if (expected.get(action.ts_code) !== action.candidate_ref) {
      throw new Error(`${action.ts_code}: CRO candidate_ref does not match the frozen universe`);
    }
  }
}

function validateExecutionFrozenIntentSet(
  submission: AutonomousExecutionSubmission,
  state: DailyCycleStateType,
): void {
  const expected = expectedFrozenOrderIntents(state);
  if (submission.order_assessments.length !== expected.length) {
    throw new Error("Execution assessments must cover the frozen order-intent set one-to-one");
  }
  const expectedByRef = new Map(expected.map((intent) => [intent.order_intent_ref, intent]));
  for (const assessment of submission.order_assessments) {
    const intent = expectedByRef.get(assessment.order_intent_ref);
    if (
      !intent ||
      intent.ts_code !== assessment.ts_code ||
      Math.abs(intent.requested_delta_weight - assessment.requested_delta_weight) > 1e-9
    ) {
      throw new Error(
        `${assessment.assessment_local_id}: execution assessment does not match a frozen order intent`,
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function cioAllCashRequired(state: DailyCycleStateType, stage: RuntimeAgentStageId): boolean {
  if (
    state.current_positions.snapshot_status !== "empty_confirmed" ||
    state.current_positions.positions.length !== 0
  ) {
    return false;
  }
  if (stage === "cio_proposal") {
    const hasSectorLong = Object.values(state.layer2_outputs).some(
      (output) => "long_picks" in output && output.long_picks.length > 0,
    );
    const hasSuperinvestorLong = Object.values(state.layer3_outputs).some((output) =>
      output.picks.some((pick) => pick.position_action === "LONG"),
    );
    const hasAlphaCandidate = (state.layer4_outputs.alpha_discovery?.novel_picks.length ?? 0) > 0;
    return !hasSectorLong && !hasSuperinvestorLong && !hasAlphaCandidate;
  }
  if (stage === "cio_final") {
    const candidateTarget = state.layer4_outputs.runtime?.candidate_target_state;
    return candidateTarget !== null && candidateTarget !== undefined
      ? candidateTarget.portfolio_actions.length === 0
      : false;
  }
  return false;
}

function hasToolApi(api: BridgeApi | undefined): api is BridgeApi {
  return (
    typeof api?.toolsPrepareCapability === "function" &&
    typeof api.toolsList === "function" &&
    typeof api.toolsCall === "function" &&
    typeof api.toolsTerminateCapability === "function"
  );
}

function decisionCapabilityStage<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
): AgentExecutionStageId {
  if (spec.agentId === "cio") {
    if (spec.runtimeStage === "cio_proposal" || spec.runtimeStage === "cio_final") {
      return spec.runtimeStage;
    }
    throw new Error(`cio cannot bind capability stage ${spec.runtimeStage}`);
  }
  if (
    spec.agentId === "alpha_discovery" ||
    spec.agentId === "cro" ||
    spec.agentId === "autonomous_execution"
  ) {
    return spec.agentId;
  }
  throw new Error(`unknown decision agent ${spec.agentId}`);
}

function decisionCandidateScope<TOutput extends Layer4AgentOutput>(
  state: DailyCycleStateType,
  spec: LayerFourAgentSpec<TOutput>,
): Record<string, unknown> {
  if (state.darwinian_runtime_binding) {
    return { accepted_output_refs: acceptedRefsForPrefixes(state, decisionSourcePrefixes(spec)) };
  }
  if (spec.agentId === "alpha_discovery") {
    return { layer2_outputs: state.layer2_outputs, layer3_outputs: state.layer3_outputs };
  }
  if (spec.agentId === "cio" && spec.runtimeStage === "cio_proposal") {
    return {
      layer3_outputs: state.layer3_outputs,
      alpha_discovery: state.layer4_outputs.alpha_discovery,
    };
  }
  return {
    cio_proposal: state.layer4_outputs.cio,
    cro: state.layer4_outputs.cro,
    autonomous_execution: state.layer4_outputs.autonomous_execution,
  };
}

function decisionSourcePrefixes<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
): readonly string[] {
  if (spec.agentId === "alpha_discovery") {
    return ["STANDARD_SECTOR_SELECTION:", "RELATIONSHIP_GRAPH:", "SUPERINVESTOR_SELECTION:"];
  }
  if (spec.agentId === "cio" && spec.runtimeStage === "cio_proposal") {
    return [
      "MACRO_TRANSMISSION:",
      "STANDARD_SECTOR_SELECTION:",
      "RELATIONSHIP_GRAPH:",
      "SUPERINVESTOR_SELECTION:",
      "ALPHA_DISCOVERY:",
    ];
  }
  return ["CIO_PROPOSAL:", "CRO_RISK_REVIEW:", "EXECUTION_ASSESSMENT:"];
}

function buildFakeDecisionSnapshotTool(
  name: string,
  agentId: string,
  asOf: string,
): StructuredToolInterface {
  return tool(
    async () =>
      JSON.stringify({
        schema_version: "fake_decision_snapshot_v1",
        agent_id: agentId,
        as_of: asOf,
        ...(agentId === "alpha_discovery" ? { candidate_universe: [] } : {}),
        fixture: "fake_llm_structural_smoke",
        evidence_id: `fake-${agentId}-${name}`,
      }),
    {
      name,
      description: "Deterministic frozen Decision snapshot for fake structural smoke runs.",
      schema: z.object({}).strict(),
    },
  );
}

export function frozenAlphaCandidatesFromToolLoop(
  messages: readonly BaseMessage[],
  toolStatuses: readonly ToolStatus[],
): FrozenAlphaCandidate[] {
  const status = [...toolStatuses]
    .reverse()
    .find(
      (row) =>
        row.name === "get_alpha_candidate_snapshot" &&
        row.called &&
        !row.failed &&
        !row.missing &&
        !row.fallback,
    );
  if (!status?.call_id) throw new Error("alpha candidate snapshot was not accepted");
  const message = [...messages]
    .reverse()
    .find(
      (row) =>
        row.getType() === "tool" &&
        (row as BaseMessage & { tool_call_id?: string }).tool_call_id === status.call_id,
    );
  if (typeof message?.content !== "string") {
    throw new Error("alpha candidate snapshot payload is unavailable");
  }
  let payload: unknown;
  try {
    payload = JSON.parse(message.content);
  } catch (cause) {
    throw new Error("alpha candidate snapshot payload is invalid", { cause });
  }
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("alpha candidate snapshot must be an object");
  }
  const record = payload as Record<string, unknown>;
  if (!Array.isArray(record.candidate_universe)) {
    throw new Error("alpha candidate snapshot lacks candidate_universe");
  }
  const candidates = record.candidate_universe.map((value, index) =>
    parseFrozenAlphaCandidate(value, index),
  );
  const refs = candidates.map((candidate) => candidate.candidate_ref);
  const tickers = candidates.map((candidate) => candidate.ts_code);
  if (new Set(refs).size !== refs.length || new Set(tickers).size !== tickers.length) {
    throw new Error("alpha candidate snapshot contains duplicate candidate refs or tickers");
  }
  const constraints =
    record.constraints !== null &&
    typeof record.constraints === "object" &&
    !Array.isArray(record.constraints)
      ? (record.constraints as Record<string, unknown>)
      : null;
  if (
    candidates.length > 0 &&
    (constraints?.cash_only === true || constraints?.allow_new_positions === false)
  ) {
    throw new Error("alpha candidate snapshot conflicts with its no-new-position constraints");
  }
  return candidates.sort((left, right) => left.candidate_ref.localeCompare(right.candidate_ref));
}

function parseFrozenAlphaCandidate(value: unknown, index: number): FrozenAlphaCandidate {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`alpha candidate ${index} must be an object`);
  }
  const record = value as Record<string, unknown>;
  const candidateRef = typeof record.candidate_ref === "string" ? record.candidate_ref.trim() : "";
  const rawTsCode = record.ts_code ?? record.ticker;
  const tsCode = typeof rawTsCode === "string" ? rawTsCode.trim().toUpperCase() : "";
  if (!candidateRef || !/^\d{6}\.(?:SH|SZ|BJ)$/.test(tsCode)) {
    throw new Error(`alpha candidate ${index} has an invalid candidate_ref or ts_code`);
  }
  return { candidate_ref: candidateRef, ts_code: tsCode };
}

function shouldLoadMirofishContext<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  deps: LayerFourAgentDeps,
): boolean {
  return (
    ["cro", "autonomous_execution", "cio"].includes(spec.agentId) &&
    Boolean(deps.api) &&
    Boolean(deps.config.mirofish?.inject_context)
  );
}

async function maybeLoadMirofishContext<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  deps: LayerFourAgentDeps,
  state: DailyCycleStateType,
): Promise<MirofishContextLoadResult> {
  if (!shouldLoadMirofishContext(spec, deps) || !deps.api) {
    return { context: null, status: null };
  }
  const cache = getMirofishContextCache(deps);
  const cacheKey = mirofishContextCacheKey(state);
  const existing = cache.get(cacheKey);
  if (existing) {
    return existing;
  }
  const loadPromise = fetchMirofishContext(deps, state);
  cache.set(cacheKey, loadPromise);
  return loadPromise;
}

function getMirofishContextCache(
  deps: LayerFourAgentDeps,
): Map<string, Promise<MirofishContextLoadResult>> {
  deps.mirofishContextCache ??= new Map();
  return deps.mirofishContextCache;
}

export async function preloadLayer4MirofishContext(
  deps: LayerFourAgentDeps,
  state: DailyCycleStateType,
): Promise<MirofishContextLoadResult> {
  if (!deps.api || !deps.config.mirofish?.inject_context) {
    return { context: null, status: null };
  }
  const cache = getMirofishContextCache(deps);
  const cacheKey = mirofishContextCacheKey(state);
  const existing = cache.get(cacheKey);
  if (existing) return existing;
  const loadPromise = fetchMirofishContext(deps, state);
  cache.set(cacheKey, loadPromise);
  return loadPromise;
}

export function layer4MirofishSnapshotHash(context: MirofishContext | null): string | null {
  if (!context) return null;
  return stableRuntimeHash({
    schema_version: "decision.l4_mirofish_context_snapshot.v1",
    context_hash: context.context_hash ?? null,
    as_of_date: context.as_of_date,
    scenario_count: context.scenario_count ?? null,
    horizon_days: context.horizon_days ?? null,
    generator_version: context.generator_version ?? null,
  });
}

function mirofishContextCacheKey(state: DailyCycleStateType): string {
  const asOf = state.as_of_date || "latest";
  const runId = state.trace_id || "current_run";
  const positionHash = state.current_positions?.position_snapshot_hash || "positions:unknown";
  return `as_of:${asOf}|run:${runId}|positions:${positionHash}`;
}

async function fetchMirofishContext(
  deps: LayerFourAgentDeps,
  state: DailyCycleStateType,
): Promise<MirofishContextLoadResult> {
  if (!deps.api) {
    return { context: null, status: null };
  }
  try {
    const { context } = await deps.api.mirofishGetContext(
      state.as_of_date ? { as_of_date: state.as_of_date } : {},
    );
    if (!context) {
      return {
        context: null,
        status: {
          source_id: "mirofish_context",
          scope: "context:latest",
          status: "missing",
          ...(state.as_of_date ? { as_of: state.as_of_date } : {}),
          error_code: "mirofish_context_missing",
        },
      };
    }
    if (!context.as_of_date) {
      deps.onLog?.("mirofish context disabled: missing as_of_date");
      return {
        context: null,
        status: {
          source_id: "mirofish_context",
          scope: "context:latest",
          status: "source_error",
          ...(state.as_of_date ? { as_of: state.as_of_date } : {}),
          error_code: "mirofish_context_missing_as_of_date",
        },
      };
    }
    if (state.as_of_date && context.as_of_date > state.as_of_date) {
      deps.onLog?.(
        `mirofish context disabled: as_of_date ${context.as_of_date} exceeds run date ${state.as_of_date}`,
      );
      return {
        context: null,
        status: {
          source_id: "mirofish_context",
          scope: `context:${context.context_hash ?? context.as_of_date}`,
          status: "source_error",
          as_of: context.as_of_date,
          error_code: "mirofish_context_lookahead",
        },
      };
    }
    const missingMetadata = missingMirofishContextMetadata(context);
    if (missingMetadata.length > 0) {
      deps.onLog?.(
        `mirofish context disabled: missing required metadata ${missingMetadata.join(",")}`,
      );
      return {
        context: null,
        status: {
          source_id: "mirofish_context",
          scope: `context:${context.context_hash ?? context.as_of_date}`,
          status: "source_error",
          as_of: context.as_of_date,
          error_code: `mirofish_context_missing_metadata:${missingMetadata.join(",")}`,
        },
      };
    }
    const contextHash = context.context_hash ?? context.as_of_date;
    return {
      context,
      status: {
        source_id: "mirofish_context",
        scope: `context:${contextHash}`,
        status: "loaded",
        as_of: context.as_of_date,
        snapshot_hash: contextHash.startsWith("sha256:") ? contextHash : `sha256:${contextHash}`,
      },
    };
  } catch (err) {
    deps.onLog?.(`mirofish context lookup failed: ${(err as Error).message}`);
    return {
      context: null,
      status: {
        source_id: "mirofish_context",
        scope: "context:latest",
        status: "source_error",
        ...(state.as_of_date ? { as_of: state.as_of_date } : {}),
        error_code: "mirofish_context_source_error",
      },
    };
  }
}

function missingMirofishContextMetadata(context: MirofishContext): string[] {
  const missing: string[] = [];
  if (!Number.isFinite(context.scenario_count) || (context.scenario_count ?? 0) <= 0) {
    missing.push("scenario_count");
  }
  if (!Number.isFinite(context.horizon_days) || (context.horizon_days ?? 0) <= 0) {
    missing.push("horizon_days");
  }
  if (!context.context_hash) {
    missing.push("context_hash");
  }
  if (!context.generator_version) {
    missing.push("generator_version");
  }
  return missing;
}

/** Opt-in injection of the latest MiroFish scenario context into L4 consumers.
 *  MiroFish remains simulation-only; it never replaces current-account or
 *  current-market evidence in the action validator. */
async function maybeAppendMirofishContext<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  userContext: string,
  deps: LayerFourAgentDeps,
  language: LoaderLanguage,
  context: MirofishContext | null,
): Promise<string> {
  if (!shouldLoadMirofishContext(spec, deps)) {
    return userContext;
  }
  try {
    const section = formatMirofishContext(context, language);
    return section ? `${userContext}\n${section}` : userContext;
  } catch (err) {
    deps.onLog?.(`mirofish context injection skipped: ${(err as Error).message}`);
    return userContext;
  }
}

export function pickPromptLanguage(config: MosaicConfig): LoaderLanguage {
  const raw = (config.output_language ?? "Chinese").toString().toLowerCase().trim();
  if (raw === "english" || raw === "en") return "en";
  if (raw === "bilingual") return "Bilingual";
  return "zh";
}

function defaultExtractorSystem<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  language: LoaderLanguage,
): string {
  const lang =
    language === "en"
      ? "Reply in English."
      : "Reply in Chinese. Numbers stay numeric; do not wrap them in 中文括号.";
  return (
    `You are a structured-output extractor for the ${spec.agentId} Layer-4 decision agent. ` +
    `The user message contains a free-form analysis. Populate every field in the ` +
    `runtime-supplied JSON Schema. Cite only tickers / numbers that appeared ` +
    `in the analysis text; never invent. If evidence supports no action, select the explicit ` +
    `schema disposition for an evidence-backed empty conclusion; never return an unclassified ` +
    `empty array. When a runtime evidence catalog is present, include ` +
    `claims and per-entry claim_refs using only its evidence_id and allowed research rule ids. ` +
    `For cio, every non-empty target_positions entry requires claim_refs and at least one ` +
    `supporting claim; omitting either is a schema failure, not a valid cash decision. ` +
    `${MACRO_ATTRIBUTION_PROVIDER_INSTRUCTION} ` +
    lang
  );
}

function buildLayerFourUpdate<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  output: TOutput,
  llmCall: LlmCallRecord,
  opts: {
    state: DailyCycleStateType;
    knobSnapshot: ResearchKnobsSnapshot | null;
    canaryEvent: PromptReleaseCanaryEvent | null;
    audit: AgentRunAudit;
    acceptedOutputStore: AcceptedAgentOutputStore | undefined;
  },
): DailyCycleStateUpdate {
  if (opts.canaryEvent) llmCall.prompt_canary_event = opts.canaryEvent;
  llmCall.agent_run_audit = opts.audit;
  const currentRuntime = runtimeStateForLayer4(opts.state);
  const runId = opts.state.trace_id || opts.state.as_of_date || "current_run";
  const mode = spec.stateWriteMode ?? "agent_output";
  const runtimeOutput = decisionSubmissionToRuntimeOutput(output, opts.state);
  const acceptedOutputRefs = materializeAcceptedDecisionOutput({
    spec,
    submission: output,
    state: opts.state,
    store: opts.acceptedOutputStore,
    sourceAgentRunId: opts.audit.run_id,
  });
  if (mode === "cio_proposal") {
    const proposal = runtimeOutput as CioOutput;
    const runtime = updateLayer4Runtime(
      currentRuntime,
      { cio_proposal: proposal },
      {
        stage: "cio_proposal",
        operation: "agent_run",
        ...stageResultTrace(spec, output),
        input_hashes: layer4InputHashes(currentRuntime),
        output_hashes: { cio_proposal: stableRuntimeHash(proposal) },
      },
    );
    return {
      layer4_outputs: { runtime },
      ...(acceptedOutputRefs ? { accepted_output_refs: acceptedOutputRefs } : {}),
      llm_calls: [llmCall],
    };
  }
  if (mode === "cio_final") {
    const finalOutput = runtimeOutput as CioOutput;
    const runtime = updateLayer4Runtime(
      currentRuntime,
      { cio_final_knob_snapshot: opts.knobSnapshot },
      {
        stage: "cio_final",
        operation: "agent_run",
        ...stageResultTrace(spec, output),
        input_hashes: layer4InputHashes(currentRuntime),
        output_hashes: { cio_final: stableRuntimeHash(finalOutput) },
      },
    );
    return {
      layer4_outputs: { cio: finalOutput, runtime },
      ...(acceptedOutputRefs ? { accepted_output_refs: acceptedOutputRefs } : {}),
      llm_calls: [llmCall],
    };
  }

  let runtime = currentRuntime;
  let selectedOutput = runtimeOutput;
  if (spec.stateUpdateField === "alpha_discovery") {
    runtime = updateLayer4Runtime(
      currentRuntime,
      {},
      {
        stage: "alpha_discovery",
        operation: "agent_run",
        ...stageResultTrace(spec, output),
        input_hashes: {},
        output_hashes: { alpha_discovery: stableRuntimeHash(runtimeOutput) },
      },
    );
  } else if (spec.stateUpdateField === "cro") {
    const review = freezeCroReview(
      runId,
      currentRuntime.candidate_target_state,
      runtimeOutput as CroOutput,
    );
    selectedOutput = review.output;
    runtime = updateLayer4Runtime(
      currentRuntime,
      { cro_review_state: review },
      {
        stage: "cro_review",
        operation: "agent_run",
        ...stageResultTrace(spec, output),
        input_hashes: layer4InputHashes(currentRuntime),
        output_hashes: { cro_review_state: review.review_hash },
      },
    );
  } else if (spec.stateUpdateField === "autonomous_execution") {
    const feasibility = freezeExecutionFeasibility(
      runId,
      currentRuntime.candidate_target_state,
      currentRuntime.cro_review_state,
      runtimeOutput as AutoExecOutput,
      currentRuntime.resolved_source_statuses,
      opts.state.as_of_date || "live",
    );
    selectedOutput = feasibility.output;
    runtime = updateLayer4Runtime(
      currentRuntime,
      { execution_feasibility_state: feasibility },
      {
        stage: "execution_feasibility",
        operation: "agent_run",
        ...stageResultTrace(spec, output),
        input_hashes: layer4InputHashes(currentRuntime),
        output_hashes: { execution_feasibility_state: feasibility.feasibility_hash },
      },
    );
  }
  return {
    layer4_outputs: {
      [spec.stateUpdateField]: selectedOutput,
      runtime,
    } as Partial<Layer4Outputs>,
    ...(acceptedOutputRefs ? { accepted_output_refs: acceptedOutputRefs } : {}),
    llm_calls: [llmCall],
  };
}

function materializeAcceptedDecisionOutput<TOutput extends Layer4AgentOutput>(input: {
  spec: LayerFourAgentSpec<TOutput>;
  submission: TOutput;
  state: DailyCycleStateType;
  store: AcceptedAgentOutputStore | undefined;
  sourceAgentRunId: string;
}): DailyCycleStateUpdate["accepted_output_refs"] | undefined {
  if (!input.state.darwinian_runtime_binding) return undefined;
  const store = input.store;
  const behavior =
    input.state.darwinian_runtime_binding.agent_behavior_bindings[input.spec.agentId];
  const claimGraph = input.submission.verified_claim_graph;
  if (!store || !behavior || !claimGraph) {
    throw new Error(`${input.spec.agentId}: production accepted Decision context is unavailable`);
  }

  let kind: AcceptedOutputKind;
  let accepted: unknown;
  if (input.submission.agent_id === "alpha_discovery") {
    const candidateSnapshotEvidence = claimGraph.evidence_ledger.find(
      (entry) =>
        entry.source_kind === "tool" && entry.tool_or_source === "get_alpha_candidate_snapshot",
    );
    if (!candidateSnapshotEvidence) {
      throw new Error("alpha_discovery: frozen candidate snapshot lineage is unavailable");
    }
    const universe = frozenObjectSet("alpha-novel-candidate-universe", {
      l4_run_snapshot_hash: requiredL4SnapshotHash(input.state),
      candidate_snapshot_source_fingerprint: candidateSnapshotEvidence.source_fingerprint,
      source_refs: acceptedRefsForPrefixes(input.state, [
        "STANDARD_SECTOR_SELECTION:",
        "RELATIONSHIP_GRAPH:",
        "SUPERINVESTOR_SELECTION:",
      ]),
    });
    const attributions = resolveDecisionMacroAttributions(
      input.state,
      store,
      input.submission,
      alphaDiscoveryPayload(input.submission),
    );
    kind = "ALPHA_DISCOVERY";
    accepted = buildAcceptedAlphaDiscovery({
      submission: input.submission,
      behavior,
      frozenNovelCandidateUniverseId: universe.id,
      frozenNovelCandidateUniverseHash: universe.hash,
      acceptedMacroInputAttributions: attributions,
    });
  } else if (
    input.submission.agent_id === "cio" &&
    input.submission.decision_stage === "PROPOSAL"
  ) {
    const preCioInput = frozenObjectSet("pre-cio-input", {
      l4_run_snapshot_hash: requiredL4SnapshotHash(input.state),
      macro_gate_hash: input.state.macro_input_gate?.input_hash ?? null,
      source_refs: acceptedRefsForPrefixes(input.state, [
        "MACRO_TRANSMISSION:",
        "STANDARD_SECTOR_SELECTION:",
        "RELATIONSHIP_GRAPH:",
        "SUPERINVESTOR_SELECTION:",
        "ALPHA_DISCOVERY:",
      ]),
      current_position_snapshot_hash: input.state.current_positions.position_snapshot_hash ?? null,
    });
    const attributions = resolveDecisionMacroAttributions(
      input.state,
      store,
      input.submission,
      cioDecisionPayload(input.submission),
    );
    const alphaSource = decisionStageSource(
      input.state,
      store,
      "ALPHA_DISCOVERY",
      "alpha_discovery",
    );
    const acceptedAlpha =
      alphaSource.source_status === "ACCEPTED_OUTPUT"
        ? requiredAcceptedPayload<"ALPHA_DISCOVERY", AcceptedAlphaDiscovery>(
            input.state,
            store,
            "ALPHA_DISCOVERY",
            "alpha_discovery",
          )
        : null;
    kind = "CIO_PROPOSAL";
    accepted = buildAcceptedCioProposal({
      submission: input.submission,
      behavior,
      frozenPreCioInputId: preCioInput.id,
      frozenPreCioInputHash: preCioInput.hash,
      alphaSource,
      acceptedAlphaDiscovery: acceptedAlpha,
      acceptedMacroInputAttributions: attributions,
    });
  } else if (input.submission.agent_id === "cro") {
    const proposal = requiredAcceptedPayload<"CIO_PROPOSAL", AcceptedCioProposal>(
      input.state,
      store,
      "CIO_PROPOSAL",
      "cio",
    );
    const candidate = input.state.layer4_outputs.runtime?.candidate_target_state;
    if (!candidate) throw new Error("cro: frozen candidate universe is unavailable");
    const universe = frozenObjectSet("cro-candidate-universe", {
      proposal_id: proposal.proposal_id,
      proposal_hash: proposal.proposal_hash,
      candidate_target_hash: candidate.candidate_target_hash,
      candidates: candidate.portfolio_actions
        .map((action) => ({
          candidate_ref: persistentObjectRef("candidate", {
            candidate_target_hash: candidate.candidate_target_hash,
            ts_code: action.ticker,
          }),
          ts_code: action.ticker,
          target_weight: action.target_weight,
        }))
        .sort((left, right) => left.ts_code.localeCompare(right.ts_code)),
    });
    const attributions = resolveDecisionMacroAttributions(
      input.state,
      store,
      input.submission,
      croRiskReviewPayload(input.submission),
    );
    kind = "CRO_RISK_REVIEW";
    accepted = buildAcceptedCroRiskReview({
      submission: input.submission,
      behavior,
      frozenProposalId: proposal.proposal_id,
      frozenProposalHash: proposal.proposal_hash,
      frozenCandidateUniverseId: universe.id,
      frozenCandidateUniverseHash: universe.hash,
      acceptedMacroInputAttributions: attributions,
    });
  } else if (input.submission.agent_id === "autonomous_execution") {
    const proposal = requiredAcceptedPayload<"CIO_PROPOSAL", AcceptedCioProposal>(
      input.state,
      store,
      "CIO_PROPOSAL",
      "cio",
    );
    const croSource = decisionStageSource(input.state, store, "CRO_RISK_REVIEW", "cro");
    const orderSet = frozenOrderIntentSet(input.state, proposal, croSource, store);
    kind = "EXECUTION_ASSESSMENT";
    accepted = buildAcceptedExecutionAssessment({
      submission: input.submission,
      behavior,
      executionMode:
        input.state.current_positions.position_source === "paper_account" ||
        input.state.mode === "backtest"
          ? "PAPER"
          : "REAL",
      frozenProposalId: proposal.proposal_id,
      frozenProposalHash: proposal.proposal_hash,
      croControlSource: croSource,
      frozenOrderIntentSetId: orderSet.id,
      frozenOrderIntentSetHash: orderSet.hash,
    });
  } else {
    const submission = input.submission as CioFinalSubmission;
    const proposal = requiredAcceptedPayload<"CIO_PROPOSAL", AcceptedCioProposal>(
      input.state,
      store,
      "CIO_PROPOSAL",
      "cio",
    );
    const croSource = decisionStageSource(input.state, store, "CRO_RISK_REVIEW", "cro");
    const executionSource = decisionStageSource(
      input.state,
      store,
      "EXECUTION_ASSESSMENT",
      "autonomous_execution",
    );
    const acceptedCro =
      croSource.source_status === "ACCEPTED_OUTPUT"
        ? requiredAcceptedPayload<"CRO_RISK_REVIEW", AcceptedCroRiskReview>(
            input.state,
            store,
            "CRO_RISK_REVIEW",
            "cro",
          )
        : null;
    const acceptedExecution =
      executionSource.source_status === "ACCEPTED_OUTPUT"
        ? requiredAcceptedPayload<"EXECUTION_ASSESSMENT", AcceptedExecutionAssessment>(
            input.state,
            store,
            "EXECUTION_ASSESSMENT",
            "autonomous_execution",
          )
        : null;
    const attributions = resolveDecisionMacroAttributions(
      input.state,
      store,
      submission,
      cioDecisionPayload(submission),
    );
    kind = "CIO_FINAL";
    accepted = buildAcceptedCioFinal({
      submission,
      behavior,
      frozenProposalId: proposal.proposal_id,
      frozenProposalHash: proposal.proposal_hash,
      croControlSource: croSource,
      executionControlSource: executionSource,
      acceptedCroReview: acceptedCro,
      acceptedExecutionAssessment: acceptedExecution,
      acceptedMacroInputAttributions: attributions,
    });
  }

  const lineage = evidenceLineageEnvelopeFromGraph(accepted, claimGraph);
  const record = buildAcceptedAgentOutputRecord({
    kind,
    agentId: input.spec.agentId as never,
    payload: accepted,
    evidenceBundleIds: lineage.evidence_bundle_ids,
    causalDedupeKeys: lineage.causal_dedupe_keys,
    context: acceptedOutputBuildContextFromState({
      state: input.state,
      agentId: input.spec.agentId as never,
      sourceAgentRunId: input.sourceAgentRunId,
    }),
  });
  const ref = store.put(record, claimGraph);
  return { [acceptedOutputRefKey(kind, input.spec.agentId as never)]: ref };
}

function resolveDecisionMacroAttributions(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
  submission:
    | CroAgentSubmission
    | CioProposalSubmission
    | CioFinalSubmission
    | {
        agent_id: "alpha_discovery";
        macro_input_attributions: CroAgentSubmission["macro_input_attributions"];
      },
  acceptedBody: unknown,
) {
  const gate = state.macro_input_gate;
  if (!gate) throw new Error(`${submission.agent_id}: production Macro gate is unavailable`);
  return resolveMacroInputAttributions({
    submissions: submission.macro_input_attributions,
    acceptedMacroOutputs: acceptedMacroOutputs(state, store),
    macroInputGate: gate,
    acceptedSubmissionBody: canonicalAcceptedSubmissionBody(acceptedBody),
    targets: decisionMacroAttributionTargets(
      submission as CroAgentSubmission | CioProposalSubmission | CioFinalSubmission | never,
    ),
  });
}

function requiredAcceptedPayload<K extends AcceptedOutputKind, T>(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
  kind: K,
  agentId: string,
): T {
  const key = acceptedOutputRefKey(kind, agentId as never);
  const ref = state.accepted_output_refs[key];
  if (!ref) throw new Error(`${agentId}: ${kind} accepted source is unavailable`);
  const record = store.resolve(ref as AcceptedOutputRecordRef<K>) as AcceptedAgentOutputRecord<
    K,
    T
  >;
  if (
    record.graph_run_id !== state.trace_id ||
    record.as_of !== (state.outcome_schedule_plan?.as_of ?? state.as_of_date) ||
    record.cohort_id !== state.active_cohort
  ) {
    throw new Error(`${agentId}: ${kind} accepted source binding mismatch`);
  }
  return record.output.payload;
}

function decisionStageSource<
  K extends "ALPHA_DISCOVERY" | "CRO_RISK_REVIEW" | "EXECUTION_ASSESSMENT",
  A extends "alpha_discovery" | "cro" | "autonomous_execution",
>(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
  kind: K,
  agentId: A,
): A extends "cro" | "autonomous_execution"
  ? DecisionControlSourceRef<A>
  : DecisionStageSourceRef<A> {
  const ref = state.accepted_output_refs[acceptedOutputRefKey(kind, agentId as never)];
  const skip = state.outcome_stage_skips[agentId];
  if (ref && skip)
    throw new Error(`${agentId}: accepted output and stage skip are mutually exclusive`);
  if (ref) {
    store.resolve(ref as AcceptedOutputRecordRef<K>);
    return {
      source_status: "ACCEPTED_OUTPUT",
      agent_id: agentId,
      accepted_output_id: ref.accepted_output_id,
      accepted_output_hash: ref.accepted_output_hash,
      stage_skip_id: null,
      stage_skip_hash: null,
    } as never;
  }
  if (!skip || skip.agent_id !== agentId || skip.member_count !== 0 || skip.model_invoked) {
    throw new Error(`${agentId}: accepted source or valid NO_EVALUATION_OBJECT skip is required`);
  }
  return {
    source_status: "NO_EVALUATION_OBJECT",
    agent_id: agentId,
    accepted_output_id: null,
    accepted_output_hash: null,
    stage_skip_id: skip.stage_skip_id,
    stage_skip_hash: skip.stage_skip_hash,
  } as never;
}

function frozenOrderIntentSet(
  state: DailyCycleStateType,
  proposal: AcceptedCioProposal,
  croSource: DecisionControlSourceRef<"cro">,
  store: AcceptedAgentOutputStore,
) {
  const candidate = state.layer4_outputs.runtime?.candidate_target_state;
  const croRuntime = state.layer4_outputs.runtime?.cro_review_state;
  if (!candidate || !croRuntime)
    throw new Error("execution: frozen candidate/CRO state is unavailable");
  const acceptedCro =
    croSource.source_status === "ACCEPTED_OUTPUT"
      ? requiredAcceptedPayload<"CRO_RISK_REVIEW", AcceptedCroRiskReview>(
          state,
          store,
          "CRO_RISK_REVIEW",
          "cro",
        )
      : null;
  const actionByTicker = new Map(
    (acceptedCro?.review.candidate_actions ?? []).map((action) => [action.ts_code, action]),
  );
  const intents = candidate.portfolio_actions.flatMap((position) => {
    const control = actionByTicker.get(position.ticker);
    if (control?.action === "REQUIRE_REVIEW") return [];
    const controlledTarget =
      control?.action === "VETO"
        ? 0
        : control?.action === "CAP_WEIGHT" || control?.action === "REDUCE_WEIGHT"
          ? Math.min(position.target_weight, control.max_target_weight ?? position.target_weight)
          : position.target_weight;
    const delta = controlledTarget - (position.current_weight ?? 0);
    if (Math.abs(delta) <= 1e-9) return [];
    return [
      {
        order_intent_ref: persistentObjectRef("order-intent", {
          candidate_target_hash: candidate.candidate_target_hash,
          cro_review_hash: croRuntime.review_hash,
          ts_code: position.ticker,
          requested_delta_weight: delta,
        }),
        ts_code: position.ticker,
        requested_delta_weight: delta,
      },
    ];
  });
  const frozen = frozenObjectSet("order-intent-set", {
    proposal_id: proposal.proposal_id,
    proposal_hash: proposal.proposal_hash,
    cro_control_source: croSource,
    intents: intents.sort((left, right) => left.ts_code.localeCompare(right.ts_code)),
  });
  return frozen;
}

function requiredL4SnapshotHash(state: DailyCycleStateType): string {
  const hash = state.layer4_outputs.runtime?.l4_run_snapshot_bundle?.bundle_hash;
  if (!hash) throw new Error("Decision accepted output requires frozen L4 run snapshot");
  return hash;
}

function acceptedRefsForPrefixes(state: DailyCycleStateType, prefixes: readonly string[]) {
  return Object.entries(state.accepted_output_refs)
    .filter(([key]) => prefixes.some((prefix) => key.startsWith(prefix)))
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, ref]) => ({ key, ...ref }));
}

function frozenObjectSet(namespace: string, payload: unknown): { id: string; hash: string } {
  const hash = canonicalAcceptedOutputHash(payload);
  return { id: `${namespace}:${hash.slice("sha256:".length)}`, hash };
}

function persistentObjectRef(namespace: string, payload: unknown): string {
  return `${namespace}:${canonicalAcceptedOutputHash(payload).slice("sha256:".length)}`;
}

function isAcceptedEmptyDecision(output: Layer4AgentOutput): boolean {
  if ("review_disposition" in output) return output.review_disposition === "NO_OBJECTION";
  if ("discovery_disposition" in output) return output.discovery_disposition === "NONE_FOUND";
  if ("execution_disposition" in output) {
    return output.execution_disposition === "BLOCKED";
  }
  return (
    "decision_disposition" in output &&
    output.decision_disposition === "ALL_CASH" &&
    output.target_positions.length === 0
  );
}

function stageResultTrace<TOutput extends Layer4AgentOutput>(
  _spec: LayerFourAgentSpec<TOutput>,
  _output: TOutput,
): Pick<
  Layer4RuntimeTraceEntry,
  "status" | "reason_codes" | "fallback_factory_id" | "fallback_factory_version"
> {
  return { status: "completed" };
}

function layer4InputHashes(
  runtime: ReturnType<typeof runtimeStateForLayer4>,
): Record<string, string> {
  return {
    ...(runtime.candidate_target_state
      ? { candidate_target_state: runtime.candidate_target_state.candidate_target_hash }
      : {}),
    ...(runtime.position_review_state
      ? { position_review_state: runtime.position_review_state.position_review_hash }
      : {}),
    ...(runtime.portfolio_exposure_state
      ? { portfolio_exposure_state: runtime.portfolio_exposure_state.exposure_hash }
      : {}),
    ...(runtime.cro_review_state ? { cro_review_state: runtime.cro_review_state.review_hash } : {}),
    ...(runtime.execution_feasibility_state
      ? { execution_feasibility_state: runtime.execution_feasibility_state.feasibility_hash }
      : {}),
  };
}

export function activeKnobValuesFromUpstreamDecisionAgents(
  outputs: Layer4Outputs,
): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const output of [outputs.cro, outputs.alpha_discovery, outputs.autonomous_execution]) {
    const audit = (output as { verified_knob_audit?: unknown } | null)?.verified_knob_audit;
    if (audit === null || typeof audit !== "object" || Array.isArray(audit)) continue;
    const activeKnobs = (audit as { active_knobs?: unknown }).active_knobs;
    if (!Array.isArray(activeKnobs)) continue;
    for (const item of activeKnobs) {
      if (item === null || typeof item !== "object" || Array.isArray(item)) continue;
      const cardId = (item as { card_id?: unknown }).card_id;
      if (typeof cardId !== "string") continue;
      values[cardId] = (item as { value?: unknown }).value;
    }
  }
  return values;
}

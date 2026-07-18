/**
 * Generic factory for Layer-2 sector agent nodes (Plan §11.2 sub-step 2D.1).
 *
 * Extends the Layer-1 factory pattern with two key adaptations:
 *
 *   1. **Reads upstream state**: each Layer-2 node consumes all ten accepted
 *      Macro transmissions through the READY ``macro_input_gate`` and receives
 *      only authoritative usage shares, never a Macro consensus or stance.
 *
 *   2. **Writes to ``layer2_outputs``** (vs Layer-1's ``layer1_outputs``).
 *
 * Standard sectors use direction research, an optional single conflict review,
 * and a separate final-selection call. Relationship mapping uses one strict
 * structured call.
 *
 * relationship_mapper agent uses this same factory — the schema is
 * different but the orchestration is identical.
 */

import { createHash } from "node:crypto";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { type StructuredToolInterface, tool } from "@langchain/core/tools";
import { z } from "zod";
import { persistPromptReleaseCanaryEvents } from "../../autoresearch/prompt_release_canary_slo.js";
import { type BridgeApi, type MosaicConfig, pickBridgeTools } from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import {
  type AcceptedAgentOutputStore,
  acceptedOutputBuildContextFromState,
  acceptedOutputRefKey,
  buildAcceptedAgentOutputRecord,
} from "../accepted_output.js";
import { runAgentToolLoop } from "../helpers/agent_loop.js";
import {
  type AgentContractIssue,
  type AgentRunAudit,
  invokeStrictStructured,
} from "../helpers/agent_run_contract.js";
import {
  evidenceLineageEnvelopeFromGraph,
  renderCausalEvidenceResolutionSet,
} from "../helpers/causal_evidence_resolution.js";
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
import { acceptedMacroOutputs, renderAcceptedMacroInputs } from "../helpers/macro_context.js";
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
  type ToolStatus,
} from "../helpers/research_knobs.js";
import {
  buildLlmCall,
  formatAgentEvent,
  formatDurationMs,
  formatTokenMetricFields,
  resolveAgentTimeoutMs,
  safeErrorMessage,
  summarizeAgentOutput,
  withAgentTimeout,
} from "../helpers/runtime.js";
import { resolveRuntimeSourceStatusesForAgent } from "../helpers/runtime_sources.js";
import { SECTOR_DIRECTION_PROVIDER_INSTRUCTION } from "../helpers/sector_direction_provider_adapter.js";
import { validateStrictAgentOutput } from "../helpers/strict_agent_validation.js";
import {
  RELATIONSHIP_MAPPER_PROVIDER_INSTRUCTION,
  SECTOR_ABSTENTION_PROVIDER_INSTRUCTION,
  SECTOR_SELECTED_PROVIDER_INSTRUCTION,
} from "../helpers/structured_provider_adapters.js";
import {
  prepareAgentToolCapability,
  terminateAgentToolCapability,
} from "../helpers/tool_capability.js";
import { type LoaderLanguage, loadPrompt, loadPromptWithKnobs } from "../prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type {
  RelationshipMapperOutput,
  SectorAgentId,
  SectorAgentOutput,
  SectorAgentOutputBase,
  StandardSectorAgentId,
} from "../types.js";
import { STANDARD_SECTOR_ROLE_CONTRACTS } from "./_contracts.js";
import { buildRelationshipMapperSchema, buildStandardSectorSchema } from "./_schemas.js";
import {
  acceptedSectorSelectionPayload,
  buildAcceptedSectorSelection,
  sectorMacroAttributionTargets,
} from "./accepted.js";
import {
  applyConflictReview,
  buildSectorConflictReviewSchema,
  buildSectorDirectionResearchSchema,
  determineLeastPreferredEligibility,
  reduceDirectionMatrix,
  resolveDirectionPair,
  resolveSingleDirectionQualification,
} from "./comparison.js";
import {
  buildAcceptedRelationshipGraph,
  relationshipFactualEdgeCandidatesFromToolLoop,
  relationshipFactualEdgeCapacityFromToolLoop,
  relationshipOpportunitySetFromToolLoop,
  validateRelationshipOutputAgainstOpportunitySet,
} from "./relationship_accepted.js";
import {
  attachSectorRuntimeBinding,
  buildPairwiseFinalDirective,
  buildSingleDirectionFinalDirective,
  directionComparisonAuditHash,
  modelVisibleDirective,
  type SectorFinalSelectionRuntimeDirective,
  type SectorSecurityUniverseRow,
  validateFinalSelectionAgainstDirective,
} from "./selection.js";

export interface LayerTwoAgentSpec<TOutput extends SectorAgentOutput> {
  agentId: SectorAgentId;
  schema: z.ZodType<TOutput>;
  fieldNames: ReadonlyArray<string>;
  requiredTools: ReadonlyArray<string>;
  render: (output: TOutput) => string;
  structuredOnlySentences?: ReadonlyArray<string>;
  buildExtractorSystem?: (lang: LoaderLanguage) => string;
}

export interface LayerTwoAgentDeps {
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

export type LayerTwoAgentNode = (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>;

export function buildLayerTwoAgentNode<TOutput extends SectorAgentOutput>(
  spec: LayerTwoAgentSpec<TOutput>,
  deps: LayerTwoAgentDeps,
): LayerTwoAgentNode {
  return async function layerTwoAgentNode(state) {
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const timeoutMs = resolveAgentTimeoutMs(deps.agentTimeoutSeconds);
    const onLog = deps.onLog ?? (() => undefined);
    const startedAt = Date.now();
    let canaryContext: AgentCanaryEventContext | null = null;
    let canaryKnobSnapshot: ResearchKnobsSnapshot | null = null;
    let canaryToolStatuses: ReadonlyArray<ToolStatus> = [];
    onLog(
      formatAgentEvent("start", "L2", spec.agentId, [
        `timeout=${timeoutMs > 0 ? formatDurationMs(timeoutMs) : "off"}`,
      ]),
    );

    try {
      return await withAgentTimeout(
        async (signal) => {
          const cohort = state.active_cohort || "cohort_default";
          const language = pickPromptLanguage(deps.config);
          onLog(formatAgentEvent("phase", "L2", spec.agentId, ["prepare"]));

          let knobSnapshot: ResearchKnobsSnapshot | null = null;
          let baseSystemPrompt: string;
          let release: Parameters<typeof agentCanaryEventContext>[0]["release"];
          if (isResearchKnobsStageEnabled(spec.agentId, "agent_run", undefined, cohort)) {
            const runtimeSourceStatuses = resolveRuntimeSourceStatusesForAgent(
              state,
              spec.agentId,
              "agent_run",
            );
            const loaded = await loadPromptWithKnobs({
              agent: spec.agentId,
              cohort,
              stage: "agent_run",
              trafficAssignmentKey: state.trace_id || state.as_of_date,
              runtimeSourceStatuses,
              onReleaseAssigned: async (assignedRelease) => {
                canaryContext = await beginAgentPromptCanaryInvocation({
                  release: assignedRelease,
                  state,
                  agent: spec.agentId,
                  stage: "agent_run",
                  cohort,
                });
              },
              ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
            });
            knobSnapshot = loaded.snapshot;
            baseSystemPrompt = loaded.prompt;
            canaryKnobSnapshot = loaded.snapshot;
            release = loaded.release;
          } else {
            baseSystemPrompt = await loadPrompt({
              agent: spec.agentId,
              cohort,
              language,
              ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
            });
          }
          const systemPrompt = `${baseSystemPrompt}\n\n${buildCurrentToolContract(spec.requiredTools)}`;
          if (knobSnapshot) {
            canaryContext = agentCanaryEventContext({
              release,
              state,
              agentInvocationId:
                canaryContext?.agentInvocationId ??
                buildAgentInvocationId({
                  runId: state.trace_id || state.as_of_date || "current_run",
                  agent: spec.agentId,
                  stage: "agent_run",
                  cohort,
                  asOf: state.as_of_date || "live",
                  snapshotHash: knobSnapshot.hash,
                }),
              systemPrompt,
            });
          }

          const preparedCapability =
            deps.llmHandle.provider === "fake"
              ? null
              : await prepareAgentToolCapability({
                  api: deps.api,
                  state,
                  agentId: spec.agentId,
                  stage: spec.agentId,
                  runtimeInputs: {
                    macro_input_gate: state.macro_input_gate,
                    ...(state.darwinian_runtime_binding
                      ? { accepted_output_refs: state.accepted_output_refs }
                      : { layer1_outputs: state.layer1_outputs }),
                  },
                  candidateScope: { role_scoped_sector_snapshot: spec.agentId },
                });
          const tools = preparedCapability
            ? await pickBridgeTools(deps.api, spec.requiredTools, {
                capability: preparedCapability.capability,
              })
            : spec.requiredTools.map((name) =>
                buildFakeSectorSnapshotTool(name, spec.agentId, state.as_of_date, state.trace_id),
              );

          if (spec.agentId !== "relationship_mapper") {
            const standard = await runStandardSectorPipeline({
              spec: spec as LayerTwoAgentSpec<TOutput> & { agentId: StandardSectorAgentId },
              state,
              tools,
              preparedCapability,
              deps,
              structuredHandle,
              systemPrompt,
              userContext: buildLayerTwoUserContext(state, spec.agentId, deps.acceptedOutputStore),
              knobSnapshot,
              canaryContext,
              startedAt,
              language,
              signal,
              onLog,
            });
            canaryToolStatuses = standard.toolStatuses;
            return standard.update;
          }

          // Phase 1: tool-bound analysis. User context now includes Layer-1
          // regime summary so sector agent's picks are regime-aware.
          const userContext = buildLayerTwoUserContext(
            state,
            spec.agentId,
            deps.acceptedOutputStore,
          );
          let runtimeEvidence: RuntimeEvidenceSnapshot | null = knobSnapshot
            ? buildRuntimeEvidenceSnapshot({
                state,
                agent: spec.agentId,
                stage: "agent_run",
                knobSnapshot,
              })
            : null;
          const evidenceUserContext = runtimeEvidence
            ? `${userContext}\n\n${runtimeEvidence.visibleCatalog}`
            : userContext;
          let loopResult!: Awaited<ReturnType<typeof runAgentToolLoop>>;
          try {
            loopResult = await runAgentToolLoop({
              llm: deps.llmHandle.llm,
              tools: tools as StructuredToolInterface[],
              systemMessage: systemPrompt,
              initialMessages: [new HumanMessage(evidenceUserContext)],
              initialToolCalls: spec.requiredTools.map((name) => ({ name, args: {} })),
              allowModelToolCalls: false,
              ...(runtimeEvidence ? { agentInvocationId: runtimeEvidence.agentInvocationId } : {}),
              maxLoops: 3,
              replayFullToolMaxChars: 80_000,
              onLog: (msg) => onLog(formatAgentEvent("phase", "L2", spec.agentId, [msg])),
              signal,
            });
          } finally {
            if (preparedCapability) {
              await terminateAgentToolCapability(
                deps.api,
                preparedCapability,
                "sector_direction_research_completed",
              );
            }
          }
          runtimeEvidence = buildRuntimeEvidenceSnapshot({
            state,
            agent: spec.agentId,
            stage: "agent_run",
            knobSnapshot,
            toolStatuses: loopResult.toolStatuses,
          });
          canaryToolStatuses = loopResult.toolStatuses;
          const relationshipOpportunitySet = state.darwinian_runtime_binding
            ? relationshipOpportunitySetFromToolLoop({
                messages: loopResult.messages,
                toolStatuses: loopResult.toolStatuses,
                runId: state.trace_id,
                asOf: state.as_of_date,
              })
            : null;
          const extractionSchema = relationshipOpportunitySet
            ? (buildRelationshipMapperSchema({
                maxFactualEdges: relationshipFactualEdgeCapacityFromToolLoop({
                  messages: loopResult.messages,
                  toolStatuses: loopResult.toolStatuses,
                }),
                factualRelationships: relationshipFactualEdgeCandidatesFromToolLoop({
                  messages: loopResult.messages,
                  toolStatuses: loopResult.toolStatuses,
                }),
                maxPredictiveEdges: relationshipOpportunitySet.ordered_opportunities.length,
                predictiveOpportunities: relationshipOpportunitySet.ordered_opportunities,
              }) as unknown as z.ZodType<TOutput>)
            : spec.schema;

          // Phase 2: structured extraction.
          onLog(
            formatAgentEvent("phase", "L2", spec.agentId, [
              `extract chars=${loopResult.analysisText.length}`,
            ]),
          );
          const extractorSystem = spec.buildExtractorSystem
            ? spec.buildExtractorSystem(language)
            : defaultExtractorSystem(spec, language);
          const extractionAnalysis =
            spec.agentId === "relationship_mapper"
              ? compactRelationshipExtractorAnalysis(loopResult.analysisText)
              : loopResult.analysisText;
          const extractor = await invokeStrictStructured<TOutput>({
            llm: structuredHandle.llm,
            schema: extractionSchema,
            messages: [
              new SystemMessage(extractorSystem),
              new HumanMessage(
                [extractionAnalysis || "(no analysis produced)", runtimeEvidence?.visibleCatalog]
                  .filter((part): part is string => Boolean(part))
                  .join("\n\n"),
              ),
            ],
            agent: spec.agentId,
            stage: "agent_run",
            runId: state.trace_id || state.as_of_date || "current_run",
            evidenceSnapshot: runtimeEvidence,
            validate: (output) => {
              const strict = validateStrictAgentOutput({
                output,
                schema: extractionSchema,
                agent: spec.agentId,
                stage: "agent_run",
                runtimeEvidence,
                knobSnapshot,
                toolStatuses: loopResult.toolStatuses,
                allowRiskFlagOnly:
                  ("selection_status" in output &&
                    output.selection_status === "NO_QUALIFIED_DIRECTION") ||
                  ("predictive_graph_status" in output &&
                    output.predictive_graph_status === "NO_QUALIFIED_PREDICTIVE_EDGE"),
              });
              const opportunityIssues = relationshipOpportunitySet
                ? validateRelationshipOutputAgainstOpportunitySet(
                    strict.output as RelationshipMapperOutput,
                    relationshipOpportunitySet,
                  ).map(
                    (message): AgentContractIssue => ({
                      validator: "relationship_prediction_opportunity_v1",
                      reason_code: "RELATIONSHIP_OPPORTUNITY_MISMATCH",
                      json_path: "$.predictive_edges",
                      message,
                    }),
                  )
                : [];
              return { output: strict.output, issues: [...strict.issues, ...opportunityIssues] };
            },
            isAcceptedEmpty: (output) =>
              ("selection_status" in output &&
                output.selection_status === "NO_QUALIFIED_DIRECTION") ||
              ("predictive_graph_status" in output &&
                output.predictive_graph_status === "NO_QUALIFIED_PREDICTIVE_EDGE"),
            signal,
          });

          const output = extractor.output;
          let acceptedOutputRefs: DailyCycleStateUpdate["accepted_output_refs"] | undefined;
          if (state.darwinian_runtime_binding) {
            const relationshipOutput = output as RelationshipMapperOutput;
            const gate = state.macro_input_gate;
            const behavior =
              state.darwinian_runtime_binding.agent_behavior_bindings.relationship_mapper;
            const claimGraph = relationshipOutput.verified_claim_graph;
            if (
              !gate ||
              !behavior ||
              !claimGraph ||
              !relationshipOpportunitySet ||
              !deps.acceptedOutputStore
            ) {
              throw new Error(
                "relationship_mapper: production accepted relationship context is unavailable",
              );
            }
            const preliminary = buildAcceptedRelationshipGraph({
              output: relationshipOutput,
              behavior,
              opportunitySet: relationshipOpportunitySet,
              acceptedMacroInputAttributions: [],
              calibrationEffectiveAt: state.darwinian_runtime_binding.effective_at,
            });
            const acceptedAttributions = resolveMacroInputAttributions({
              submissions: relationshipOutput.macro_input_attributions,
              acceptedMacroOutputs: acceptedMacroOutputs(state, deps.acceptedOutputStore),
              macroInputGate: gate,
              acceptedSubmissionBody: canonicalAcceptedSubmissionBody(preliminary),
            });
            const accepted = buildAcceptedRelationshipGraph({
              output: relationshipOutput,
              behavior,
              opportunitySet: relationshipOpportunitySet,
              acceptedMacroInputAttributions: acceptedAttributions,
              calibrationEffectiveAt: state.darwinian_runtime_binding.effective_at,
            });
            const lineage = evidenceLineageEnvelopeFromGraph(accepted, claimGraph);
            const record = buildAcceptedAgentOutputRecord({
              kind: "RELATIONSHIP_GRAPH",
              agentId: "relationship_mapper",
              payload: accepted,
              evidenceBundleIds: lineage.evidence_bundle_ids,
              causalDedupeKeys: lineage.causal_dedupe_keys,
              context: acceptedOutputBuildContextFromState({
                state,
                agentId: "relationship_mapper",
                sourceAgentRunId: extractor.audit.run_id,
              }),
            });
            const ref = deps.acceptedOutputStore.put(record, claimGraph);
            acceptedOutputRefs = {
              [acceptedOutputRefKey("RELATIONSHIP_GRAPH", "relationship_mapper")]: ref,
            };
          }
          const repairPromptTokens = extractor.audit.attempts.reduce(
            (sum, attempt) => sum + attempt.prompt_tokens,
            0,
          );
          const repairCompletionTokens = extractor.audit.attempts.reduce(
            (sum, attempt) => sum + attempt.completion_tokens,
            0,
          );
          const llmCall = buildLlmCall(spec.agentId, structuredHandle, {
            promptTokens: loopResult.promptTokens + repairPromptTokens,
            completionTokens: loopResult.completionTokens + repairCompletionTokens,
          });
          llmCall.agent_run_audit = extractor.audit;
          const canaryEvent = buildAgentPromptCanaryEvent({
            context: canaryContext,
            agent: spec.agentId,
            stage: "agent_run",
            startedAt,
            structuredAccepted: true,
            claimGraphAccepted: true,
            knobSnapshot,
            knobAudit:
              (output as TOutput & { verified_knob_audit?: ResearchKnobCapAudit })
                .verified_knob_audit ?? null,
            toolStatuses: loopResult.toolStatuses,
            output,
            validatorIds: [
              `${spec.agentId}.structured_output.v1`,
              "evidence_claim_graph_v1",
              "research_knobs_runtime_v1",
            ],
          });
          if (canaryEvent) {
            llmCall.prompt_canary_event = canaryEvent;
            await persistPromptReleaseCanaryEvents([canaryEvent]);
          }

          onLog(
            formatAgentEvent("done", "L2", spec.agentId, [
              `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
              `analysis_llm=${loopResult.llmInvocations}`,
              `tools=${loopResult.toolCalls}`,
              `tool_cache_hits=${loopResult.toolCacheHits}`,
              `tool_executions=${loopResult.toolExecutions}`,
              ...formatTokenMetricFields(
                loopResult.promptTokens,
                loopResult.completionTokens,
                loopResult.llmElapsedMs,
              ),
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

          return {
            ...(state.darwinian_runtime_binding
              ? {}
              : { layer2_outputs: { [spec.agentId]: output } }),
            ...(acceptedOutputRefs ? { accepted_output_refs: acceptedOutputRefs } : {}),
            llm_calls: [llmCall],
          };
        },
        timeoutMs,
        `L2 ${spec.agentId}`,
      );
    } catch (err) {
      onLog(
        formatAgentEvent("error", "L2", spec.agentId, [
          `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
          `message=${safeErrorMessage(err)}`,
        ]),
      );
      const failureEvent = buildAgentPromptCanaryEvent({
        context: canaryContext,
        agent: spec.agentId,
        stage: "agent_run",
        startedAt,
        structuredAccepted: false,
        claimGraphAccepted: false,
        knobSnapshot: canaryKnobSnapshot,
        knobAudit: null,
        toolStatuses: canaryToolStatuses,
        output: null,
        validatorIds: [
          `${spec.agentId}.structured_output.v1`,
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

export function compactRelationshipExtractorAnalysis(value: string, maxChars = 6_000): string {
  if (value.length <= maxChars) return value;
  const marker = "\n\n[... bounded relationship analysis omitted ...]\n\n";
  const retained = maxChars - marker.length;
  const headLength = Math.ceil(retained / 2);
  return `${value.slice(0, headLength)}${marker}${value.slice(-(retained - headLength))}`;
}

interface StandardSectorPipelineResult {
  update: DailyCycleStateUpdate;
  toolStatuses: ToolStatus[];
}

async function runStandardSectorPipeline<TOutput extends SectorAgentOutput>(input: {
  spec: LayerTwoAgentSpec<TOutput> & { agentId: StandardSectorAgentId };
  state: DailyCycleStateType;
  tools: StructuredToolInterface[];
  preparedCapability: Awaited<ReturnType<typeof prepareAgentToolCapability>> | null;
  deps: LayerTwoAgentDeps;
  structuredHandle: LlmHandle;
  systemPrompt: string;
  userContext: string;
  knobSnapshot: ResearchKnobsSnapshot | null;
  canaryContext: AgentCanaryEventContext | null;
  startedAt: number;
  language: LoaderLanguage;
  signal: AbortSignal;
  onLog: (message: string) => void;
}): Promise<StandardSectorPipelineResult> {
  let toolMaterialization: Awaited<ReturnType<typeof materializeStandardSectorTools>>;
  try {
    toolMaterialization = await materializeStandardSectorTools(
      input.tools,
      input.spec.agentId,
      input.state.as_of_date,
    );
  } catch (cause) {
    if (input.preparedCapability) {
      await terminateAgentToolCapability(
        input.deps.api,
        input.preparedCapability,
        "sector_direction_research_tool_failure",
      );
    }
    throw cause;
  }
  const runtimeEvidence = buildRuntimeEvidenceSnapshot({
    state: input.state,
    agent: input.spec.agentId,
    stage: "agent_run",
    knobSnapshot: input.knobSnapshot,
    toolStatuses: toolMaterialization.statuses,
  });
  const snapshot = parseSectorRuntimeSnapshot(
    toolMaterialization.payloads,
    input.spec.agentId,
    input.structuredHandle.provider === "fake",
  );
  const eligibleDirections = snapshot.eligibleDirectionIds;
  if (eligibleDirections.length === 0) {
    throw new Error(`${input.spec.agentId}: no eligible direction; stage rejected before model`);
  }
  const researchSchema = buildSectorDirectionResearchSchema(
    eligibleDirections as [string, ...string[]],
    eligibleDirections.length === 1 ? `single-null:${input.spec.agentId}` : undefined,
  );
  let research!: Awaited<ReturnType<typeof invokeStrictStructured<z.infer<typeof researchSchema>>>>;
  try {
    research = await invokeStrictStructured({
      llm: input.structuredHandle.llm,
      schema: researchSchema,
      messages: [
        new SystemMessage(
          `Runtime agent id: ${input.spec.agentId}\nRuntime substage: direction_research\n\n` +
            `${input.systemPrompt}\n\nYou are conducting direction research for the ${input.spec.agentId} sector agent. ` +
            `${SECTOR_DIRECTION_PROVIDER_INSTRUCTION} ` +
            `Submit only the runtime schema's pairwise comparison or single-direction qualification. ` +
            `comparison_claims[].evidence_ids may use only exact ids from the runtime-owned ` +
            `evidence catalog; source coverage ids belong only in criterion coverage_evidence_ids. ` +
            `For every comparison or qualification, top-level claim_refs must equal exactly the ` +
            `deduplicated union of criterion_results[].claim_refs; omit claims that no criterion uses. ` +
            `Do not submit preferred/least directions, security picks, final_selection, scores, or rankings.`,
        ),
        new HumanMessage(
          [
            input.userContext,
            renderSectorDirectionResearchPayloads(toolMaterialization.payloads),
            runtimeEvidence.visibleCatalog,
          ].join("\n\n"),
        ),
      ],
      agent: input.spec.agentId,
      stage: "direction_research",
      runId: input.state.trace_id || input.state.as_of_date || "current_run",
      evidenceSnapshot: runtimeEvidence,
      validate: (output) => ({
        output,
        issues: validateResearchEvidence(output.comparison_claims, runtimeEvidence),
      }),
      signal: input.signal,
    });
  } finally {
    if (input.preparedCapability) {
      await terminateAgentToolCapability(
        input.deps.api,
        input.preparedCapability,
        "sector_direction_research_completed",
      );
    }
  }

  let finalizedComparisons =
    research.output.research_mode === "PAIRWISE" ? [...research.output.direction_comparisons] : [];
  let comparisonClaims = [...research.output.comparison_claims];
  const initialResolutions = finalizedComparisons.map(resolveDirectionPair);
  let resolutions = initialResolutions;
  let reduction =
    research.output.research_mode === "PAIRWISE"
      ? reduceDirectionMatrix(eligibleDirections as [string, ...string[]], resolutions)
      : null;
  const initialMatrixHash = reduction?.finalized_pair_matrix_hash ?? canonicalHash([]);
  let conflictReviewAudit: AgentRunAudit | null = null;
  let conflictReviewTriggered = false;
  let conflictReviewId: string | null = null;

  if (
    research.output.research_mode === "PAIRWISE" &&
    reduction &&
    reduction.conflict_direction_ids.length >= 2
  ) {
    conflictReviewTriggered = true;
    const orderedConflictDirections = eligibleDirections.filter((direction) =>
      reduction?.conflict_direction_ids.includes(direction),
    ) as [string, string, ...string[]];
    conflictReviewId = `sector-review:${canonicalHash({
      run_id: input.state.trace_id || input.state.as_of_date,
      agent: input.spec.agentId,
      snapshot_bundle_hash:
        input.preparedCapability?.bundle.snapshot_bundle_hash ?? snapshot.snapshotHash,
      initial_matrix_hash: initialMatrixHash,
      conflict_direction_ids: [...orderedConflictDirections].sort(),
    }).slice(-24)}`;
    const reservedClaimIds = new Set(comparisonClaims.map((claim) => claim.claim_id));
    const reviewSchema = buildSectorConflictReviewSchema(
      orderedConflictDirections,
      reservedClaimIds,
    );
    const review = await invokeStrictStructured({
      llm: input.structuredHandle.llm,
      schema: reviewSchema,
      messages: [
        new SystemMessage(
          `Runtime agent id: ${input.spec.agentId}\nRuntime substage: conflict_review\n\n` +
            `You are performing the one permitted conflict review for the ${input.spec.agentId} sector agent. ` +
            `${SECTOR_DIRECTION_PROVIDER_INSTRUCTION} ` +
            `Use only the frozen projection below. Submit every conflict-internal pair exactly once. ` +
            `Create new review claims with claim_id values that do not reuse any reserved claim id. ` +
            `Do not use tools and do not submit a final selection, direction ranking, or security picks.`,
        ),
        new HumanMessage(
          JSON.stringify({
            review_id: conflictReviewId,
            conflict_direction_ids: orderedConflictDirections,
            reserved_claim_ids: [...reservedClaimIds].sort(),
            initial_comparisons: finalizedComparisons.filter(
              (row) =>
                orderedConflictDirections.includes(row.direction_a_id) &&
                orderedConflictDirections.includes(row.direction_b_id),
            ),
            evidence_catalog: runtimeEvidence.visibleCatalog,
          }),
        ),
      ],
      agent: input.spec.agentId,
      stage: "conflict_review",
      runId: input.state.trace_id || input.state.as_of_date || "current_run",
      evidenceSnapshot: {
        snapshot_hash: runtimeEvidence.snapshotHash,
        conflict_review_id: conflictReviewId,
      },
      validate: (output) => ({
        output,
        issues: validateResearchEvidence(output.comparison_claims, runtimeEvidence),
      }),
      signal: input.signal,
    });
    conflictReviewAudit = review.audit;
    finalizedComparisons = applyConflictReview(
      finalizedComparisons,
      review.output,
      orderedConflictDirections,
    );
    comparisonClaims = mergeComparisonClaims(comparisonClaims, review.output.comparison_claims);
    resolutions = finalizedComparisons.map(resolveDirectionPair);
    reduction = reduceDirectionMatrix(eligibleDirections as [string, ...string[]], resolutions);
  }

  const leastEligibility = reduction
    ? determineLeastPreferredEligibility(
        eligibleDirections as [string, ...string[]],
        reduction,
        resolutions,
      )
    : {
        status: "NOT_APPLICABLE" as const,
        reason: "SINGLE_ELIGIBLE_DIRECTION" as const,
        least_preferred_direction_id: null,
        qualifying_comparison_local_ids: [],
      };
  const singleQualification =
    research.output.research_mode === "SINGLE_DIRECTION_QUALIFICATION"
      ? resolveSingleDirectionQualification(research.output.single_direction_qualification)
      : null;
  let directive: SectorFinalSelectionRuntimeDirective;
  if (research.output.research_mode === "PAIRWISE") {
    if (!reduction) throw new Error("pairwise research requires a matrix reduction");
    directive = buildPairwiseFinalDirective({
      reduction,
      leastEligibility,
      finalizedComparisons,
      resolutions,
      comparisonClaims,
      securityUniverse: snapshot.securityUniverse,
    });
  } else {
    if (!singleQualification) throw new Error("single-direction qualification is missing");
    directive = buildSingleDirectionFinalDirective({
      qualification: singleQualification,
      submission: research.output.single_direction_qualification,
      comparisonClaims,
      securityUniverse: snapshot.securityUniverse,
    });
  }
  const finalizedMatrixHash = reduction?.finalized_pair_matrix_hash ?? canonicalHash([]);
  const comparisonAudit = {
    schema_version: "sector_direction_comparison_audit_v1",
    run_id: input.state.trace_id || input.state.as_of_date || "current_run",
    sector_agent_id: input.spec.agentId,
    research_mode: research.output.research_mode,
    snapshot_bundle_hash:
      input.preparedCapability?.bundle.snapshot_bundle_hash ?? snapshot.snapshotHash,
    initial_pair_matrix_hash: initialMatrixHash,
    conflict_type: reduction?.conflict_type ?? "NONE",
    conflict_direction_ids: reduction?.conflict_direction_ids ?? [],
    conflict_review_id: conflictReviewId,
    conflict_review_status: conflictReviewTriggered ? "COMPLETED" : "NOT_REQUIRED",
    finalized_pair_matrix_hash: finalizedMatrixHash,
    condorcet_winner_direction_id: reduction?.condorcet_winner_direction_id ?? null,
    condorcet_loser_direction_id: reduction?.condorcet_loser_direction_id ?? null,
    least_preferred_eligibility: leastEligibility,
    single_direction_qualification: singleQualification,
  };
  const comparisonAuditHash = directionComparisonAuditHash(comparisonAudit);
  const finalEnvelopeSchema = z
    .object({
      final_selection: buildStandardSectorSchema(
        input.spec.agentId,
        directive.selection_status,
        directive,
      ),
    })
    .strict() as unknown as z.ZodType<{ final_selection: TOutput }>;
  const final = await invokeStrictStructured({
    llm: input.structuredHandle.llm,
    schema: finalEnvelopeSchema,
    messages: [
      new SystemMessage(
        `Runtime agent id: ${input.spec.agentId}\nRuntime substage: final_selection\n\n` +
          `You are making the final selection for the ${input.spec.agentId} sector agent. ` +
          `Obey the runtime directive exactly. Do not submit comparisons, review rows, scores, hashes, ` +
          `rankings, or unlisted securities. Keep the payload compact: use one to three key drivers, ` +
          `one to three risks, no more than six reusable claims, and no more than five picks per side; ` +
          `do not restate the same evidence in multiple claims. Author only local Sector claims: upstream ` +
          `Macro claim ids may appear only in macro_input_attributions.claim_refs_used and must never be ` +
          `copied into claims or top-level claim_refs. Every claim_refs field outside ` +
          `macro_input_attributions—including directions, picks, drivers, risks, and the submission—must ` +
          `reference only ids authored in the local claims array. macro_input_attributions must contain exactly one ` +
          `SUBMISSION_SUMMARY row for each of the ten Macro agents with target_local_ref=$SUBMISSION; ` +
          `NOT_MATERIAL rows use an empty claim_refs_used array. Add target-specific rows only for material ` +
          `links to an exact directive target, with no more than six such rows. If the directive has no ` +
          `qualified direction, emit only the ten summary rows and no target-specific rows. ` +
          `${SECTOR_ABSTENTION_PROVIDER_INSTRUCTION} ` +
          `${SECTOR_SELECTED_PROVIDER_INSTRUCTION} ` +
          `${MACRO_ATTRIBUTION_PROVIDER_INSTRUCTION} ` +
          `${finalLanguageInstruction(input.language)}`,
      ),
      new HumanMessage(
        [
          `Runtime final-selection directive:\n${JSON.stringify(modelVisibleDirective(directive))}`,
          renderAcceptedMacroInputs(input.state, input.deps.acceptedOutputStore),
          renderCausalEvidenceResolutionSet({
            state: input.state,
            consumerAgentId: input.spec.agentId,
            sourceLayers: ["MACRO"],
            ...(input.deps.acceptedOutputStore
              ? { acceptedOutputStore: input.deps.acceptedOutputStore }
              : {}),
          }),
          runtimeEvidence.visibleCatalog,
        ].join("\n\n"),
      ),
    ],
    agent: input.spec.agentId,
    stage: "final_selection",
    runId: input.state.trace_id || input.state.as_of_date || "current_run",
    evidenceSnapshot: {
      snapshot_hash: runtimeEvidence.snapshotHash,
      directive: modelVisibleDirective(directive),
    },
    validate: async (envelope) => {
      const submitted = envelope.final_selection as TOutput & SectorAgentOutputBase;
      const strict = await validateStrictAgentOutput({
        output: submitted,
        schema: input.spec.schema,
        agent: input.spec.agentId,
        stage: "agent_run",
        runtimeEvidence,
        knobSnapshot: input.knobSnapshot,
        toolStatuses: toolMaterialization.statuses,
        allowRiskFlagOnly: submitted.selection_status === "NO_QUALIFIED_DIRECTION",
      });
      const directiveIssues = validateFinalSelectionAgainstDirective(
        strict.output as SectorAgentOutputBase,
        directive,
      ).map(
        (message): AgentContractIssue => ({
          validator: "sector_final_selection_directive_v1",
          reason_code: "SECTOR_FINAL_DIRECTIVE_MISMATCH",
          json_path: "$.final_selection",
          message,
        }),
      );
      return {
        output: { final_selection: strict.output },
        issues: [...strict.issues, ...directiveIssues],
      };
    },
    isAcceptedEmpty: (envelope) =>
      (envelope.final_selection as TOutput & SectorAgentOutputBase).selection_status ===
      "NO_QUALIFIED_DIRECTION",
    signal: input.signal,
  });
  const rawOutput = final.output.final_selection as TOutput & SectorAgentOutputBase;
  const snapshotBundleId =
    input.preparedCapability?.bundle.snapshot_bundle_id ??
    `fake-sector-bundle:${input.spec.agentId}:${input.state.as_of_date}`;
  const snapshotBundleHash =
    input.preparedCapability?.bundle.snapshot_bundle_hash ?? snapshot.snapshotHash;
  const output = attachSectorRuntimeBinding({
    output: rawOutput,
    directive,
    snapshotBundleId,
    snapshotBundleHash,
    directionComparisonAuditHash: comparisonAuditHash,
    finalizedPairMatrixHash: finalizedMatrixHash,
  });
  const audits = [
    research.audit,
    ...(conflictReviewAudit ? [conflictReviewAudit] : []),
    final.audit,
  ];
  const usage = sumAuditTokens(audits);
  const leastPreferredEligibilityAudit = {
    status: leastEligibility.status,
    reason: leastEligibility.reason,
    eligible_direction_ids: eligibleDirections,
    least_preferred_direction_id: leastEligibility.least_preferred_direction_id,
    qualifying_comparison_local_ids: leastEligibility.qualifying_comparison_local_ids,
    qualifying_claim_refs:
      leastEligibility.status === "REQUIRED"
        ? [
            ...new Set(
              finalizedComparisons
                .filter((row) =>
                  leastEligibility.qualifying_comparison_local_ids.includes(
                    row.comparison_local_id,
                  ),
                )
                .flatMap((row) => row.claim_refs),
            ),
          ].sort()
        : [],
    finalized_pair_matrix_hash: finalizedMatrixHash,
    qualification_contract_version: "least_preferred_eligibility_v1",
  };
  const singleDirectionQualificationAudit = singleQualification
    ? {
        ...singleQualification,
        null_benchmark_universe_hash: canonicalHash({
          snapshot_bundle_hash: snapshotBundleHash,
          direction_id: singleQualification.direction_id,
          null_benchmark_contract_id: singleQualification.null_benchmark_contract_id,
        }),
        required_final_evidence_ids: directive.required_final_evidence_ids,
      }
    : null;
  const inferenceCostAudit = {
    production_variant_roster_id:
      input.state.darwinian_runtime_binding?.production_variant_roster_id ?? "NON_PRODUCTION",
    production_variant_roster_revision_id:
      input.state.darwinian_weight_snapshot?.production_variant_roster_revision_id ??
      "NON_PRODUCTION",
    sector_agent_id: input.spec.agentId,
    snapshot_bundle_hash: snapshotBundleHash,
    inference_budget_contract_version: "sector_inference_budget_v1",
    model_subcall_count: conflictReviewTriggered ? 3 : 2,
    last_attempted_stage: "COMPLETED",
    conflict_review_triggered: conflictReviewTriggered,
    input_tokens: usage.promptTokens,
    output_tokens: usage.completionTokens,
    normalized_inference_cost: normalizedSectorInferenceCost(usage),
    budget_compliant: true,
    disposition: "SUCCESS",
  };
  let acceptedOutputRefs: DailyCycleStateUpdate["accepted_output_refs"] | undefined;
  if (input.state.darwinian_runtime_binding) {
    const gate = input.state.macro_input_gate;
    const claimGraph = output.verified_claim_graph;
    if (!gate || !claimGraph || !input.deps.acceptedOutputStore) {
      throw new Error(`${input.spec.agentId}: production accepted Sector context is unavailable`);
    }
    const selection = acceptedSectorSelectionPayload(output);
    const acceptedAttributions = resolveMacroInputAttributions({
      submissions: output.macro_input_attributions,
      acceptedMacroOutputs: acceptedMacroOutputs(input.state, input.deps.acceptedOutputStore),
      macroInputGate: gate,
      acceptedSubmissionBody: canonicalAcceptedSubmissionBody(selection),
      targets: sectorMacroAttributionTargets(output),
    });
    const behavior =
      input.state.darwinian_runtime_binding.agent_behavior_bindings[input.spec.agentId];
    if (!behavior) {
      throw new Error(`${input.spec.agentId}: production behavior binding is unavailable`);
    }
    const accepted = buildAcceptedSectorSelection({
      output,
      behavior,
      acceptedMacroInputAttributions: acceptedAttributions,
      auditBindings: {
        directionComparisonAudit: comparisonAudit,
        leastPreferredEligibilityAudit,
        singleDirectionQualificationAudit,
        inferenceCostAudit,
      },
    });
    const lineage = evidenceLineageEnvelopeFromGraph(accepted, claimGraph);
    const record = buildAcceptedAgentOutputRecord({
      kind: "STANDARD_SECTOR_SELECTION",
      agentId: input.spec.agentId,
      payload: accepted,
      evidenceBundleIds: lineage.evidence_bundle_ids,
      causalDedupeKeys: lineage.causal_dedupe_keys,
      context: acceptedOutputBuildContextFromState({
        state: input.state,
        agentId: input.spec.agentId,
        sourceAgentRunId: final.audit.run_id,
      }),
    });
    const ref = input.deps.acceptedOutputStore.put(record, claimGraph);
    acceptedOutputRefs = {
      [acceptedOutputRefKey("STANDARD_SECTOR_SELECTION", input.spec.agentId)]: ref,
    };
  }
  const llmCall = buildLlmCall(input.spec.agentId, input.structuredHandle, usage);
  llmCall.agent_run_audit = final.audit;
  llmCall.sector_inference_audit = {
    schema_version: "sector_inference_audit_v1",
    sector_agent_id: input.spec.agentId,
    snapshot_bundle_hash: snapshotBundleHash,
    model_subcall_count: conflictReviewTriggered ? 3 : 2,
    conflict_review_triggered: conflictReviewTriggered,
    direction_research_audit: research.audit,
    conflict_review_audit: conflictReviewAudit,
    final_selection_audit: final.audit,
    direction_comparison_audit_hash: comparisonAuditHash,
    direction_comparison_audit: comparisonAudit,
    normalized_inference_cost: inferenceCostAudit.normalized_inference_cost,
  };
  const canaryEvent = buildAgentPromptCanaryEvent({
    context: input.canaryContext,
    agent: input.spec.agentId,
    stage: "agent_run",
    startedAt: input.startedAt,
    structuredAccepted: true,
    claimGraphAccepted: true,
    knobSnapshot: input.knobSnapshot,
    knobAudit:
      (output as TOutput & { verified_knob_audit?: ResearchKnobCapAudit }).verified_knob_audit ??
      null,
    toolStatuses: toolMaterialization.statuses,
    output,
    validatorIds: [
      `${input.spec.agentId}.structured_output.v2`,
      "sector_direction_comparison_v2",
      "sector_final_selection_directive_v1",
      "evidence_claim_graph_v1",
    ],
  });
  if (canaryEvent) {
    llmCall.prompt_canary_event = canaryEvent;
    await persistPromptReleaseCanaryEvents([canaryEvent]);
  }
  input.onLog(
    formatAgentEvent("done", "L2", input.spec.agentId, [
      `elapsed=${formatDurationMs(Date.now() - input.startedAt)}`,
      `model_subcalls=${conflictReviewTriggered ? 3 : 2}`,
      `conflict_review=${conflictReviewTriggered}`,
      `tools=${toolMaterialization.statuses.length}`,
      ...formatTokenMetricFields(usage.promptTokens, usage.completionTokens, 0),
      summarizeAgentOutput(output),
    ]),
  );
  return {
    update: {
      ...(input.state.darwinian_runtime_binding
        ? {}
        : { layer2_outputs: { [input.spec.agentId]: output } }),
      ...(acceptedOutputRefs ? { accepted_output_refs: acceptedOutputRefs } : {}),
      llm_calls: [llmCall],
    },
    toolStatuses: toolMaterialization.statuses,
  };
}

async function materializeStandardSectorTools(
  tools: readonly StructuredToolInterface[],
  agentId: StandardSectorAgentId,
  asOf: string,
): Promise<{ payloads: Map<string, string>; statuses: ToolStatus[] }> {
  const payloads = new Map<string, string>();
  const statuses: ToolStatus[] = [];
  for (const registeredTool of tools) {
    const callId = `sector-tool:${agentId}:${registeredTool.name}`;
    try {
      const raw = await registeredTool.invoke({});
      const text = typeof raw === "string" ? raw : JSON.stringify(raw);
      payloads.set(registeredTool.name, text);
      statuses.push({
        name: registeredTool.name,
        call_id: callId,
        called: true,
        failed: false,
        missing: false,
        fallback: false,
        cache_hit: false,
        args: {},
        as_of: asOf,
        args_fingerprint: canonicalHash({}),
        result_fingerprint: canonicalHash(text),
        source_fingerprint: canonicalHash({ tool: registeredTool.name, as_of: asOf }),
      });
    } catch (cause) {
      statuses.push({
        name: registeredTool.name,
        call_id: callId,
        called: true,
        failed: true,
        missing: true,
        fallback: false,
        cache_hit: false,
        args: {},
        as_of: asOf,
      });
      throw new Error(`${agentId}: required Sector tool ${registeredTool.name} failed`, {
        cause,
      });
    }
  }
  return { payloads, statuses };
}

function parseSectorRuntimeSnapshot(
  payloads: ReadonlyMap<string, string>,
  agentId: StandardSectorAgentId,
  allowFakeFallback: boolean,
): {
  eligibleDirectionIds: string[];
  securityUniverse: SectorSecurityUniverseRow[];
  snapshotHash: string;
} {
  const raw = payloads.get("get_sector_research_snapshot");
  if (!raw) throw new Error(`${agentId}: missing sector snapshot payload`);
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(raw) as Record<string, unknown>;
  } catch (cause) {
    throw new Error(`${agentId}: invalid sector snapshot JSON`, { cause });
  }
  const registered = STANDARD_SECTOR_ROLE_CONTRACTS[agentId].directionIds;
  const candidateIds = Array.isArray(payload.eligible_direction_ids)
    ? payload.eligible_direction_ids
    : Array.isArray(payload.direction_ids)
      ? payload.direction_ids
      : allowFakeFallback
        ? registered
        : [];
  const eligibleDirectionIds = candidateIds.filter(
    (value): value is string => typeof value === "string" && registered.includes(value),
  );
  if (
    eligibleDirectionIds.length !== candidateIds.length ||
    new Set(eligibleDirectionIds).size !== eligibleDirectionIds.length
  ) {
    throw new Error(`${agentId}: eligible direction domain is invalid`);
  }
  const securityUniverse = Array.isArray(payload.eligible_security_universe)
    ? payload.eligible_security_universe.flatMap((row) => {
        if (!row || typeof row !== "object" || Array.isArray(row)) return [];
        const value = row as Record<string, unknown>;
        return typeof value.ts_code === "string" && typeof value.direction_id === "string"
          ? [{ ts_code: value.ts_code, direction_id: value.direction_id }]
          : [];
      })
    : [];
  const snapshotHash =
    typeof payload.snapshot_hash === "string" && /^sha256:[0-9a-f]{64}$/.test(payload.snapshot_hash)
      ? payload.snapshot_hash
      : canonicalHash(payload);
  return { eligibleDirectionIds, securityUniverse, snapshotHash };
}

export function renderSectorDirectionResearchPayloads(
  payloads: ReadonlyMap<string, string>,
): string {
  return [...payloads.entries()]
    .map(([name, payload]) => {
      if (name !== "get_sector_research_snapshot") return `## Frozen ${name}\n${payload}`;
      let parsed: unknown;
      try {
        parsed = JSON.parse(payload);
      } catch {
        return `## Frozen ${name}\n${payload}`;
      }
      return (
        `## Frozen ${name}\n` +
        `Source evidence ids are intentionally hidden here; claims must cite the runtime-owned catalog.\n` +
        JSON.stringify(withoutSourceEvidenceIds(parsed))
      );
    })
    .join("\n\n");
}

function withoutSourceEvidenceIds(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withoutSourceEvidenceIds);
  if (value === null || typeof value !== "object") return value;
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (key === "evidence_catalog" || key === "evidence_ids" || key.endsWith("_evidence_ids")) {
      continue;
    }
    result[key] = withoutSourceEvidenceIds(item);
  }
  return result;
}

function validateResearchEvidence(
  claims: ReadonlyArray<{ claim_id: string; evidence_ids: string[] }>,
  runtimeEvidence: RuntimeEvidenceSnapshot,
): AgentContractIssue[] {
  const issues: AgentContractIssue[] = [];
  for (const claim of claims) {
    for (const evidenceId of claim.evidence_ids) {
      if (!runtimeEvidence.evidenceById.has(evidenceId)) {
        issues.push({
          validator: "sector_direction_research_evidence_v1",
          reason_code: "UNKNOWN_RESEARCH_EVIDENCE",
          json_path: `$.comparison_claims[${claim.claim_id}].evidence_ids`,
          message: `unknown runtime evidence ${evidenceId}`,
        });
      }
    }
  }
  return issues;
}

function mergeComparisonClaims<T extends { claim_id: string }>(
  initial: readonly T[],
  review: readonly T[],
): T[] {
  const merged = new Map(initial.map((claim) => [claim.claim_id, claim]));
  for (const claim of review) {
    const prior = merged.get(claim.claim_id);
    if (prior && canonicalHash(prior) !== canonicalHash(claim)) {
      throw new Error(`conflict review redefined claim ${claim.claim_id}`);
    }
    merged.set(claim.claim_id, claim);
  }
  return [...merged.values()];
}

function sumAuditTokens(audits: readonly AgentRunAudit[]): {
  promptTokens: number;
  completionTokens: number;
} {
  return audits.reduce(
    (sum, audit) => ({
      promptTokens:
        sum.promptTokens +
        audit.attempts.reduce((value, attempt) => value + attempt.prompt_tokens, 0),
      completionTokens:
        sum.completionTokens +
        audit.attempts.reduce((value, attempt) => value + attempt.completion_tokens, 0),
    }),
    { promptTokens: 0, completionTokens: 0 },
  );
}

function normalizedSectorInferenceCost(usage: {
  promptTokens: number;
  completionTokens: number;
}): number {
  return Math.min(1, 0.5 * (usage.promptTokens / 30_000) + 0.5 * (usage.completionTokens / 10_500));
}

function finalLanguageInstruction(language: LoaderLanguage): string {
  return language === "en"
    ? "Write prose fields in English."
    : "Write prose fields in Chinese; keep numbers numeric.";
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
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function pickPromptLanguage(config: MosaicConfig): LoaderLanguage {
  const raw = (config.output_language ?? "Chinese").toString().toLowerCase().trim();
  if (raw === "english" || raw === "en") return "en";
  if (raw === "bilingual") return "Bilingual";
  return "zh";
}

/** Build user-context block that includes upstream Layer-1 summaries. */
export function buildLayerTwoUserContext(
  state: DailyCycleStateType,
  agentId: string,
  acceptedOutputStore?: AcceptedAgentOutputStore,
): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  const mode = state.mode || "live";
  const cohort = state.active_cohort || "cohort_default";
  const macroBlock = renderAcceptedMacroInputs(state, acceptedOutputStore);
  const causalResolutionBlock = renderCausalEvidenceResolutionSet({
    state,
    consumerAgentId: agentId as SectorAgentId,
    sourceLayers: ["MACRO"],
    ...(acceptedOutputStore ? { acceptedOutputStore } : {}),
  });

  return (
    `Cycle context for ${agentId} (Layer 2 sector analyst):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${mode}\n` +
    `* cohort:     ${cohort}\n\n` +
    `${macroBlock}\n\n` +
    `${causalResolutionBlock}\n\n` +
    `The runtime has already frozen the role's direction and security domains. ` +
    `Use the single role snapshot to compare every direction pair, select one preferred direction, ` +
    `and select a least-preferred direction only when the evidence qualifies it. ` +
    `Treat the ten Macro transmissions as distinct inputs and record all ten attributions.`
  );
}

function buildFakeSectorSnapshotTool(
  name: string,
  agentId: SectorAgentId,
  asOf: string,
  runId: string,
): StructuredToolInterface {
  return tool(
    async () => {
      if (agentId === "relationship_mapper" && name === "get_relationship_graph_snapshot") {
        const opportunityBody = {
          run_id: runId,
          as_of: asOf,
          candidate_generation_contract_version: "relationship_candidate_fixture_v2",
          scoring_contract_version: "relationship_scoring_fixture_v2",
          ordered_opportunities: [
            {
              edge_candidate_id: "relationship-candidate:fixture",
              source_entity: "sector:energy",
              target_entity: "sector:industrials",
              edge_type: "INPUT_COST_TRANSMISSION",
              materiality_weight: 1,
              matched_non_edge_set_id: "matched-non-edge:fixture",
              matched_non_edge_set_hash: canonicalHash({ fixture: "matched-non-edge" }),
            },
          ],
        };
        const opportunityHash = canonicalHash(opportunityBody);
        return JSON.stringify({
          schema_version: "relationship_research_snapshot_v2",
          agent_id: agentId,
          as_of_date: asOf,
          relationships: [],
          prediction_opportunity_set: {
            opportunity_set_id: `relationship-opportunity:${opportunityHash.slice(7)}`,
            opportunity_set_hash: opportunityHash,
            ...opportunityBody,
          },
          fixture: "fake_llm_structural_smoke",
          evidence_id: `fake-${agentId}-snapshot`,
        });
      }
      return JSON.stringify({
        schema_version: "fake_sector_snapshot_v1",
        agent_id: agentId,
        as_of: asOf,
        fixture: "fake_llm_structural_smoke",
        evidence_id: `fake-${agentId}-snapshot`,
      });
    },
    {
      name,
      description: "Deterministic frozen Sector snapshot for fake structural smoke runs.",
      schema: z.object({}).strict(),
    },
  );
}

function buildCurrentToolContract(requiredTools: ReadonlyArray<string>): string {
  return (
    `## Current tool contract\n` +
    `Only call these registered tools: ${requiredTools.join(", ")}.\n` +
    `Do not call older prompt names that are not listed above.\n` +
    `The runtime calls these tools once with the frozen role and as-of date; do not request extra data.`
  );
}

function defaultExtractorSystem<TOutput extends SectorAgentOutput>(
  spec: LayerTwoAgentSpec<TOutput>,
  language: LoaderLanguage,
): string {
  const lang =
    language === "en"
      ? "Reply in English."
      : "Reply in Chinese. Numbers stay numeric; do not wrap them in 中文括号.";
  return (
    `You are a structured-output extractor for the ${spec.agentId} sector agent. ` +
    `The user message contains a free-form analysis. Populate every field in the ` +
    `runtime-supplied JSON Schema. Only emit values supported by the ` +
    `analysis text; never invent ticker codes or net-flow numbers. ` +
    (spec.agentId === "relationship_mapper"
      ? `${RELATIONSHIP_MAPPER_PROVIDER_INSTRUCTION} ${MACRO_ATTRIBUTION_PROVIDER_INSTRUCTION} `
      : `If no direction qualifies, use selection_status=NO_QUALIFIED_DIRECTION with both pick ` +
        `arrays empty, confidence ≤ 0.4, and evidence-backed RISK_FLAG claims. When a runtime ` +
        `evidence catalog is present, include claims, top-level claim_refs, and per-pick claim_refs ` +
        `using only its evidence_id and allowed research rule ids. `) +
    lang
  );
}

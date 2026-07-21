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

import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { type StructuredToolInterface, tool } from "@langchain/core/tools";
import { z } from "zod";
import { persistPromptReleaseCanaryEvents } from "../../autoresearch/prompt_release_canary_slo.js";
import {
  type BridgeApi,
  type MosaicConfig,
  pickBridgeTools,
  type SectorModelUsageReport,
  type SectorModelUsageSummaryReceipt,
  type SignedAgentToolCapability,
} from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import {
  type AcceptedAgentOutputStore,
  acceptedOutputBuildContextFromState,
  acceptedOutputRefKey,
  buildAcceptedAgentOutputRecord,
  buildStructuredSmokeAcceptedOutputRef,
} from "../accepted_output.js";
import { runAgentToolLoop } from "../helpers/agent_loop.js";
import {
  type AgentAttemptAudit,
  type AgentContractIssue,
  type AgentRunAudit,
  invokeStrictStructured,
} from "../helpers/agent_run_contract.js";
import { canonicalJsonHash } from "../helpers/canonical_json.js";
import {
  evidenceLineageEnvelopeFromGraph,
  renderCausalEvidenceResolutionSet,
} from "../helpers/causal_evidence_resolution.js";
import {
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
  assertLiveOutcomeSourceSnapshot,
  freezeLiveOutcomeOpportunity,
  liveOutcomeCapabilityRuntimeInput,
} from "../helpers/outcome_pre_model.js";
import {
  finalizePrivateKnotSnapshot,
  isPrivateKnotStageEnabled,
  type PrivateKnotAuditSummary,
  type PrivateKnotSnapshot,
  preparePrivateKnotModelContext,
  privateKnotInvocationContextForState,
  type ToolStatus,
} from "../helpers/private_knot_boundary.js";
import {
  type AgentCanaryEventContext,
  agentCanaryEventContext,
  beginAgentPromptCanaryInvocation,
  buildAgentPromptCanaryEvent,
} from "../helpers/prompt_canary.js";
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
  SECTOR_SELECTED_PROVIDER_INSTRUCTION,
} from "../helpers/structured_provider_adapters.js";
import {
  hasAgentToolCapabilityApi,
  prepareAgentToolCapability,
  terminateAgentToolCapability,
} from "../helpers/tool_capability.js";
import {
  buildPromptReleaseAssignmentKey,
  type LoaderLanguage,
  loadPrompt,
  loadPromptWithPrivateKnot,
} from "../prompts/loader.js";
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
  MAX_SECTOR_COVERAGE_EVIDENCE_IDS,
  reduceDirectionMatrix,
  resolveDirectionPair,
  SECTOR_DIRECTION_COMPARISON_CONTRACT_VERSION,
  SECTOR_DIRECTION_REDUCER_CONTRACT_VERSION,
  type SectorCoverageDirective,
} from "./comparison.js";
import { SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT } from "./registry.js";
import {
  buildAcceptedRelationshipGraph,
  relationshipFactualEdgeCandidatesFromToolLoop,
  relationshipFactualEdgeCapacityFromToolLoop,
  relationshipResearchSnapshotFromToolLoop,
  validateRelationshipOutputAgainstSnapshot,
} from "./relationship_accepted.js";
import {
  attachSectorRuntimeBinding,
  buildPairwiseFinalDirective,
  directionComparisonAuditHash,
  modelVisibleDirective,
  SECURITY_SCORING_CONTRACT_HASH,
  SECURITY_SCORING_CONTRACT_VERSION,
  type SectorFinalSelectionRuntimeDirective,
  type SectorSecurityScoringRow,
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
    const liveFreeze = await freezeLiveOutcomeOpportunity({
      api: deps.api,
      state,
      agentId: spec.agentId,
    });
    state = liveFreeze.state;
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const timeoutMs = resolveAgentTimeoutMs(deps.agentTimeoutSeconds);
    const onLog = deps.onLog ?? (() => undefined);
    const startedAt = Date.now();
    let canaryContext: AgentCanaryEventContext | null = null;
    let canaryKnobSnapshot: PrivateKnotSnapshot | null = null;
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

          let knobSnapshot: PrivateKnotSnapshot | null = null;
          let baseSystemPrompt: string;
          let release: Parameters<typeof agentCanaryEventContext>[0]["release"];
          if (isPrivateKnotStageEnabled(spec.agentId, "agent_run", cohort)) {
            const runtimeSourceStatuses = resolveRuntimeSourceStatusesForAgent(
              state,
              spec.agentId,
              "agent_run",
            );
            const loaded = await loadPromptWithPrivateKnot({
              agent: spec.agentId,
              cohort,
              stage: "agent_run",
              trafficAssignmentKey: buildPromptReleaseAssignmentKey(cohort, state.as_of_date),
              runtimeSourceStatuses,
              invocationContext: privateKnotInvocationContextForState(state),
              ...(state.darwinian_runtime_binding
                ? { requirePinnedPrivateRelease: true as const }
                : {}),
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
              agentInvocationId: knobSnapshot.agent_invocation_id,
              systemPrompt,
            });
          }

          const capabilityApi = hasAgentToolCapabilityApi(deps.api) ? deps.api : null;
          if (!capabilityApi && deps.llmHandle.provider !== "fake") {
            throw new Error(`${spec.agentId}: bridge tool capability API is unavailable`);
          }
          const preparedCapability = capabilityApi
            ? await prepareAgentToolCapability({
                api: deps.api,
                state,
                agentId: spec.agentId,
                stage: spec.agentId,
                runtimeInputs: {
                  macro_input_gate: state.macro_input_gate,
                  ...(state.darwinian_runtime_binding
                    ? { accepted_output_refs: state.accepted_output_refs }
                    : { layer1_outputs: state.layer1_outputs }),
                  ...liveOutcomeCapabilityRuntimeInput(state, spec.agentId),
                },
                candidateScope: { role_scoped_sector_snapshot: spec.agentId },
              })
            : null;
          const tools = preparedCapability
            ? await pickBridgeTools(deps.api, spec.requiredTools, {
                capability: preparedCapability.capability,
              })
            : spec.requiredTools.map((name) =>
                buildFakeSectorSnapshotTool(name, spec.agentId, state.as_of_date, state.trace_id),
              );

          if (spec.agentId !== "relationship_mapper") {
            try {
              const standard = await runStandardSectorPipeline({
                spec: spec as LayerTwoAgentSpec<TOutput> & { agentId: StandardSectorAgentId },
                state,
                tools,
                preparedCapability,
                deps,
                structuredHandle,
                systemPrompt,
                userContext: buildLayerTwoUserContext(
                  state,
                  spec.agentId,
                  deps.acceptedOutputStore,
                ),
                knobSnapshot,
                canaryContext,
                startedAt,
                language,
                signal,
                onLog,
              });
              canaryToolStatuses = standard.toolStatuses;
              return { ...(liveFreeze.update ?? {}), ...standard.update };
            } catch (cause) {
              if (preparedCapability) {
                try {
                  await deps.api.toolsFinalizeModelUsage(preparedCapability.capability);
                } catch (finalizeCause) {
                  throw new AggregateError(
                    [cause, finalizeCause],
                    `${spec.agentId}: Sector pipeline and usage finalization both failed`,
                  );
                }
              }
              throw cause;
            } finally {
              if (preparedCapability) {
                await terminateAgentToolCapability(
                  deps.api,
                  preparedCapability,
                  "sector_pipeline_finished",
                );
              }
            }
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
              ...(knobSnapshot
                ? {
                    prepareModelContext: (initialToolResults) =>
                      preparePrivateKnotModelContext({
                        snapshot: knobSnapshot,
                        initialToolResults,
                      }),
                  }
                : {}),
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
            modelContext: loopResult.modelContext,
            effectiveModelInputHash: loopResult.effectiveModelInputHash,
          });
          canaryToolStatuses = loopResult.toolStatuses;
          const relationshipSnapshot = state.darwinian_runtime_binding
            ? relationshipResearchSnapshotFromToolLoop({
                messages: loopResult.messages,
                toolStatuses: loopResult.toolStatuses,
              })
            : null;
          const relationshipOpportunitySet =
            relationshipSnapshot?.prediction_opportunity_set ?? null;
          if (relationshipSnapshot) {
            assertLiveOutcomeSourceSnapshot({
              state,
              agentId: "relationship_mapper",
              sourceToolId: "get_relationship_graph_snapshot",
              sourceSnapshotHash: relationshipSnapshot.snapshot_hash,
            });
          }
          if (
            relationshipOpportunitySet &&
            (relationshipOpportunitySet.run_id !== state.trace_id ||
              relationshipOpportunitySet.as_of !== state.as_of_date ||
              relationshipSnapshot?.as_of_date !== state.as_of_date)
          ) {
            throw new Error("relationship opportunity snapshot run binding mismatch");
          }
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
                cohort: state.active_cohort,
                runtimeEvidence,
                knobSnapshot,
                toolStatuses: loopResult.toolStatuses,
                allowRiskFlagOnly:
                  "predictive_graph_status" in output &&
                  output.predictive_graph_status === "NO_QUALIFIED_PREDICTIVE_EDGE",
                validateBeforePrivatePolicy: (candidate) =>
                  relationshipSnapshot
                    ? validateRelationshipOutputAgainstSnapshot(
                        candidate as RelationshipMapperOutput,
                        relationshipSnapshot,
                      ).map(
                        (message): AgentContractIssue => ({
                          validator: "relationship_prediction_opportunity_v1",
                          reason_code: "RELATIONSHIP_OPPORTUNITY_MISMATCH",
                          json_path: "$.predictive_edges",
                          message,
                        }),
                      )
                    : [],
              });
              return strict;
            },
            isAcceptedEmpty: (output) =>
              "predictive_graph_status" in output &&
              output.predictive_graph_status === "NO_QUALIFIED_PREDICTIVE_EDGE",
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
              !relationshipSnapshot ||
              !deps.acceptedOutputStore
            ) {
              throw new Error(
                "relationship_mapper: production accepted relationship context is unavailable",
              );
            }
            const preliminary = buildAcceptedRelationshipGraph({
              output: relationshipOutput,
              behavior,
              relationshipSnapshot,
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
              relationshipSnapshot,
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
              claimGraph,
              sourceAgentOutputHash: requiredAcceptedAuditOutputHash(
                extractor.audit.output_hash,
                "relationship_mapper",
              ),
              context: acceptedOutputBuildContextFromState({
                state,
                agentId: "relationship_mapper",
                sourceAgentRunId: extractor.audit.run_id,
                acceptedOutputKind: "RELATIONSHIP_GRAPH",
              }),
            });
            const ref = deps.acceptedOutputStore.put(record, claimGraph);
            acceptedOutputRefs = {
              [acceptedOutputRefKey("RELATIONSHIP_GRAPH", "relationship_mapper")]: ref,
            };
          } else {
            const ref = buildStructuredSmokeAcceptedOutputRef({
              kind: "RELATIONSHIP_GRAPH",
              agentId: "relationship_mapper",
              payload: output,
              state,
            });
            if (ref) {
              acceptedOutputRefs = {
                [acceptedOutputRefKey("RELATIONSHIP_GRAPH", "relationship_mapper")]: ref,
              };
            }
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
              (output as TOutput & { private_knot_audit?: PrivateKnotAuditSummary })
                .private_knot_audit ?? null,
            toolStatuses: loopResult.toolStatuses,
            output,
            validatorIds: [
              `${spec.agentId}.structured_output.v1`,
              "evidence_claim_graph_v1",
              "private_knot_runtime_v1",
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
            ...(liveFreeze.update ?? {}),
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
          "private_knot_runtime_v1",
        ],
        forceFallback: true,
        forceSourceFailure: true,
      });
      if (failureEvent) await persistPromptReleaseCanaryEvents([failureEvent]);
      throw err;
    } finally {
      if (canaryKnobSnapshot) finalizePrivateKnotSnapshot(canaryKnobSnapshot);
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
  knobSnapshot: PrivateKnotSnapshot | null;
  canaryContext: AgentCanaryEventContext | null;
  startedAt: number;
  language: LoaderLanguage;
  signal: AbortSignal;
  onLog: (message: string) => void;
}): Promise<StandardSectorPipelineResult> {
  const toolMaterialization = await materializeStandardSectorTools(
    input.tools,
    input.spec.agentId,
    input.state.as_of_date,
  );
  const baseRuntimeEvidence = buildRuntimeEvidenceSnapshot({
    state: input.state,
    agent: input.spec.agentId,
    stage: "agent_run",
    knobSnapshot: input.knobSnapshot,
    toolStatuses: toolMaterialization.statuses,
  });
  const snapshot = parseSectorRuntimeSnapshot(
    toolMaterialization.payloads,
    input.spec.agentId,
    input.state.as_of_date,
    input.structuredHandle.provider === "fake",
  );
  assertLiveOutcomeSourceSnapshot({
    state: input.state,
    agentId: input.spec.agentId,
    sourceToolId: "get_sector_research_snapshot",
    sourceSnapshotHash: snapshot.snapshotHash,
  });
  const eligibleDirections = snapshot.eligibleDirectionIds;
  if (eligibleDirections.length < 3) {
    throw new Error(
      `${input.spec.agentId}: fewer than three eligible directions; stage rejected before model`,
    );
  }
  const coverageDirective = buildSectorCoverageDirective(
    toolMaterialization.payloads,
    input.spec.agentId,
    input.state.as_of_date,
    input.structuredHandle.provider === "fake",
  );
  validateSectorRoleEventCrossBinding(
    toolMaterialization.payloads,
    input.spec.agentId,
    input.structuredHandle.provider === "fake",
  );
  const runtimeEvidence = bindSectorCoverageEvidence(
    baseRuntimeEvidence,
    coverageDirective,
    input.spec.agentId,
  );
  const researchSchema = buildSectorDirectionResearchSchema(
    eligibleDirections as [string, string, string, ...string[]],
    coverageDirective,
  );
  const research = await invokeStrictStructured({
    llm: input.structuredHandle.llm,
    schema: researchSchema,
    messages: [
      new SystemMessage(
        `Runtime agent id: ${input.spec.agentId}\nRuntime substage: direction_research\n\n` +
          `${input.systemPrompt}\n\nYou are conducting direction research for the ${input.spec.agentId} sector agent. ` +
          `${SECTOR_DIRECTION_PROVIDER_INSTRUCTION} ` +
          `Submit only the runtime schema's complete pairwise comparison matrix. ` +
          `comparison_claims[].evidence_ids may use only exact ids from the runtime-owned ` +
          `evidence catalog. Each available or confirmed-no-event coverage criterion must reference ` +
          `claims whose evidence_ids collectively include every exact coverage_evidence_id. ` +
          `Copy the exact runtime-owned coverage states and complete ordered coverage evidence-id list. ` +
          `For every comparison, top-level claim_refs must equal exactly the ` +
          `deduplicated union of criterion_results[].claim_refs; omit claims that no criterion uses. ` +
          `Do not submit preferred/least directions, security picks, final_selection, scores, or rankings.`,
      ),
      new HumanMessage(
        [
          input.userContext,
          `Runtime-owned exact role-event coverage directive:\n${JSON.stringify(coverageDirective)}`,
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
    ...(input.preparedCapability
      ? {
          onAttempt: sectorUsageAttemptRecorder({
            api: input.deps.api,
            capability: input.preparedCapability.capability,
            agentId: input.spec.agentId,
            attemptedStage: "DIRECTION_RESEARCH",
            directionComparisonAudit: null,
            conflictReview: null,
          }),
        }
      : {}),
    signal: input.signal,
  });

  let finalizedComparisons = [...research.output.direction_comparisons];
  let comparisonClaims = [...research.output.comparison_claims];
  const initialResolutions = finalizedComparisons.map(resolveDirectionPair);
  let resolutions = initialResolutions;
  let reduction = reduceDirectionMatrix(
    eligibleDirections as [string, string, string, ...string[]],
    resolutions,
  );
  const initialMatrixHash = reduction.finalized_pair_matrix_hash;
  const initialConflictType = reduction.conflict_type;
  const initialConflictDirectionIds = [...reduction.conflict_direction_ids];
  let conflictReviewAudit: AgentRunAudit | null = null;
  let conflictReviewTriggered = false;
  let conflictReviewId: string | null = null;

  if (reduction.conflict_direction_ids.length >= 2) {
    conflictReviewTriggered = true;
    const orderedConflictDirections = eligibleDirections.filter((direction) =>
      reduction.conflict_direction_ids.includes(direction),
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
      coverageDirective,
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
          [
            JSON.stringify({
              review_id: conflictReviewId,
              conflict_direction_ids: orderedConflictDirections,
              reserved_claim_ids: [...reservedClaimIds].sort(),
              initial_comparisons: finalizedComparisons.filter(
                (row) =>
                  orderedConflictDirections.includes(row.direction_a_id) &&
                  orderedConflictDirections.includes(row.direction_b_id),
              ),
              coverage_directive: coverageDirective,
              evidence_catalog: runtimeEvidence.visibleCatalog,
            }),
            "Frozen direction-research projection used by the initial comparison:",
            renderSectorDirectionResearchPayloads(toolMaterialization.payloads),
          ].join("\n\n"),
        ),
      ],
      agent: input.spec.agentId,
      stage: "conflict_review",
      runId: input.state.trace_id || input.state.as_of_date || "current_run",
      evidenceSnapshot: {
        ...runtimeEvidence,
        snapshot_hash: runtimeEvidence.snapshotHash,
        conflict_review_id: conflictReviewId,
      },
      validate: (output) => ({
        output,
        issues: validateResearchEvidence(output.comparison_claims, runtimeEvidence),
      }),
      ...(input.preparedCapability
        ? {
            onAttempt: sectorUsageAttemptRecorder({
              api: input.deps.api,
              capability: input.preparedCapability.capability,
              agentId: input.spec.agentId,
              attemptedStage: "CONFLICT_REVIEW",
              directionComparisonAudit: null,
              conflictReview: null,
            }),
          }
        : {}),
      signal: input.signal,
    });
    conflictReviewAudit = review.audit;
    finalizedComparisons = applyConflictReview(
      finalizedComparisons,
      review.output,
      orderedConflictDirections,
      coverageDirective,
    );
    comparisonClaims = mergeComparisonClaims(comparisonClaims, review.output.comparison_claims);
    resolutions = finalizedComparisons.map(resolveDirectionPair);
    reduction = reduceDirectionMatrix(
      eligibleDirections as [string, string, string, ...string[]],
      resolutions,
    );
  }
  const directive: SectorFinalSelectionRuntimeDirective = buildPairwiseFinalDirective({
    reduction,
    finalizedComparisons,
    resolutions,
    comparisonClaims,
    securityScoringRows: snapshot.securityScoringRows,
  });
  const finalizedMatrixHash = reduction.finalized_pair_matrix_hash;
  const comparisonAudit = {
    schema_version: "sector_direction_comparison_audit_v1",
    resolver_contract_id: SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.resolver_contract_id,
    resolver_contract_version:
      SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.resolver_contract_version,
    resolver_contract_hash: SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.resolver_contract_hash,
    reducer_contract_version: SECTOR_DIRECTION_REDUCER_CONTRACT_VERSION,
    run_id: input.state.trace_id || input.state.as_of_date || "current_run",
    sector_agent_id: input.spec.agentId,
    research_mode: research.output.research_mode,
    snapshot_bundle_hash:
      input.preparedCapability?.bundle.snapshot_bundle_hash ?? snapshot.snapshotHash,
    initial_pair_matrix_hash: initialMatrixHash,
    conflict_type: initialConflictType,
    conflict_direction_ids: initialConflictDirectionIds,
    conflict_review_id: conflictReviewId,
    conflict_review_status: conflictReviewTriggered ? "COMPLETED" : "NOT_REQUIRED",
    finalized_pair_matrix_hash: finalizedMatrixHash,
    final_conflict_type: reduction.conflict_type,
    final_conflict_direction_ids: reduction.conflict_direction_ids,
    condorcet_winner_direction_id: reduction.condorcet_winner_direction_id,
    condorcet_loser_direction_id: reduction.condorcet_loser_direction_id,
  };
  const comparisonAuditHash = directionComparisonAuditHash(comparisonAudit);
  const comparisonAuditId = `sector-direction-comparison:${comparisonAuditHash.slice("sha256:".length)}`;
  const conflictReviewAuditRef =
    conflictReviewId && conflictReviewAudit
      ? { id: conflictReviewId, hash: canonicalHash(conflictReviewAudit) }
      : null;
  const finalGrounding = buildSectorFinalGroundingProjection({
    payloads: toolMaterialization.payloads,
    directive,
    finalizedComparisons,
    resolutions,
    comparisonClaims,
    finalizedPairMatrixHash: finalizedMatrixHash,
    runtimeEvidence,
  });
  const finalSelectionSchema = buildStandardSectorSchema(
    input.spec.agentId,
    directive.selection_status,
    directive,
  ) as unknown as z.ZodType<TOutput & SectorAgentOutputBase>;
  const finalEnvelopeSchema = z
    .object({
      final_selection: finalSelectionSchema,
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
          `one to three risks, no more than fourteen reusable claims, and no more than five picks per side; ` +
          `do not restate the same evidence in multiple claims. Author only local Sector claims: upstream ` +
          `Macro claim ids may appear only in macro_input_attributions.claim_refs_used and must never be ` +
          `copied into claims or top-level claim_refs. Every claim_refs field outside ` +
          `macro_input_attributions—including directions, picks, drivers, risks, and the submission—must ` +
          `reference only ids authored in the local claims array. macro_input_attributions must contain exactly one ` +
          `SUBMISSION_SUMMARY row for each of the ten Macro agents with target_local_ref=$SUBMISSION; ` +
          `NOT_MATERIAL rows use an empty claim_refs_used array. Add target-specific rows only for material ` +
          `links to an exact directive target, with no more than six such rows. ` +
          `${SECTOR_SELECTED_PROVIDER_INSTRUCTION} ` +
          `${MACRO_ATTRIBUTION_PROVIDER_INSTRUCTION} ` +
          `${finalLanguageInstruction(input.language)}`,
      ),
      new HumanMessage(
        [
          `Runtime final-selection directive:\n${JSON.stringify(modelVisibleDirective(directive))}`,
          `Runtime-owned finalized comparison and frozen market projection:\n${JSON.stringify(finalGrounding)}`,
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
      ...runtimeEvidence,
      snapshot_hash: runtimeEvidence.snapshotHash,
      directive: modelVisibleDirective(directive),
      final_grounding_hash: canonicalHash(finalGrounding),
      final_grounding: finalGrounding,
    },
    validate: async (envelope) => {
      const submitted = envelope.final_selection as TOutput & SectorAgentOutputBase;
      const strict = await validateStrictAgentOutput({
        output: submitted,
        schema: finalSelectionSchema,
        agent: input.spec.agentId,
        stage: "agent_run",
        cohort: input.state.active_cohort,
        runtimeEvidence,
        knobSnapshot: input.knobSnapshot,
        toolStatuses: toolMaterialization.statuses,
        allowRiskFlagOnly: false,
        validateBeforePrivatePolicy: (candidate) =>
          validateFinalSelectionAgainstDirective(candidate, directive).map(
            (message): AgentContractIssue => ({
              validator: "sector_final_selection_directive_v1",
              reason_code: "SECTOR_FINAL_DIRECTIVE_MISMATCH",
              json_path: "$.final_selection",
              message,
            }),
          ),
      });
      return {
        output: { final_selection: strict.output },
        issues: strict.issues,
      };
    },
    ...(input.preparedCapability
      ? {
          onAttempt: sectorUsageAttemptRecorder({
            api: input.deps.api,
            capability: input.preparedCapability.capability,
            agentId: input.spec.agentId,
            attemptedStage: "FINAL_SELECTION",
            directionComparisonAudit: {
              id: comparisonAuditId,
              hash: comparisonAuditHash,
            },
            conflictReview: conflictReviewAuditRef,
          }),
        }
      : {}),
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
  const usageSummary = input.preparedCapability
    ? await input.deps.api.toolsFinalizeModelUsage(input.preparedCapability.capability)
    : buildFakeSectorUsageSummary({
        agentId: input.spec.agentId,
        state: input.state,
        snapshotBundleId,
        snapshotBundleHash,
        audits,
        directionComparisonAudit: {
          id: comparisonAuditId,
          hash: comparisonAuditHash,
        },
        conflictReview: conflictReviewAuditRef,
      });
  if (
    usageSummary.model_path_disposition !== "COMPLETED" ||
    usageSummary.last_attempted_stage !== "COMPLETED" ||
    usageSummary.snapshot_bundle_hash !== snapshotBundleHash ||
    usageSummary.agent_id !== input.spec.agentId ||
    usageSummary.direction_comparison_audit_id !== comparisonAuditId ||
    usageSummary.direction_comparison_audit_hash !== comparisonAuditHash ||
    usageSummary.conflict_review_id !== (conflictReviewAuditRef?.id ?? null) ||
    usageSummary.conflict_review_hash !== (conflictReviewAuditRef?.hash ?? null)
  ) {
    throw new Error(`${input.spec.agentId}: signed model usage summary binding mismatch`);
  }
  const inferenceCostAudit = {
    schema_version: "sector_runtime_inference_cost_audit_v3",
    evidence_source: "SIGNED_SERVER_MODEL_USAGE_SUMMARY",
    sector_agent_id: input.spec.agentId,
    snapshot_bundle_hash: snapshotBundleHash,
    usage_summary_receipt_id: usageSummary.usage_summary_receipt_id,
    usage_summary_receipt_hash: usageSummary.usage_summary_receipt_hash,
    usage_summary_receipt: usageSummary,
    model_subcall_count: usageSummary.model_subcall_count,
    last_attempted_stage: usageSummary.last_attempted_stage,
    conflict_review_triggered: usageSummary.conflict_review_triggered,
    input_tokens: usageSummary.input_tokens,
    output_tokens: usageSummary.output_tokens,
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
      claimGraph,
      sourceAgentOutputHash: requiredAcceptedAuditOutputHash(
        final.audit.output_hash,
        input.spec.agentId,
      ),
      context: acceptedOutputBuildContextFromState({
        state: input.state,
        agentId: input.spec.agentId,
        sourceAgentRunId: final.audit.run_id,
        acceptedOutputKind: "STANDARD_SECTOR_SELECTION",
      }),
    });
    const ref = input.deps.acceptedOutputStore.put(record, claimGraph);
    acceptedOutputRefs = {
      [acceptedOutputRefKey("STANDARD_SECTOR_SELECTION", input.spec.agentId)]: ref,
    };
  } else {
    const ref = buildStructuredSmokeAcceptedOutputRef({
      kind: "STANDARD_SECTOR_SELECTION",
      agentId: input.spec.agentId,
      payload: output,
      state: input.state,
    });
    if (ref) {
      acceptedOutputRefs = {
        [acceptedOutputRefKey("STANDARD_SECTOR_SELECTION", input.spec.agentId)]: ref,
      };
    }
  }
  const llmCall = buildLlmCall(input.spec.agentId, input.structuredHandle, usage);
  llmCall.agent_run_audit = final.audit;
  llmCall.sector_inference_audit = {
    schema_version: "sector_inference_audit_v1",
    sector_agent_id: input.spec.agentId,
    snapshot_bundle_hash: snapshotBundleHash,
    model_subcall_count: usageSummary.model_subcall_count,
    conflict_review_triggered: conflictReviewTriggered,
    direction_research_audit: research.audit,
    conflict_review_audit: conflictReviewAudit,
    final_selection_audit: final.audit,
    direction_comparison_audit_hash: comparisonAuditHash,
    direction_comparison_audit: comparisonAudit,
    inference_cost_audit_id: `sector-inference-cost:${canonicalHash(inferenceCostAudit).slice("sha256:".length)}`,
    inference_cost_audit_hash: canonicalHash(inferenceCostAudit),
    usage_summary_receipt_id: usageSummary.usage_summary_receipt_id,
    usage_summary_receipt_hash: usageSummary.usage_summary_receipt_hash,
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
      (output as TOutput & { private_knot_audit?: PrivateKnotAuditSummary }).private_knot_audit ??
      null,
    toolStatuses: toolMaterialization.statuses,
    output,
    validatorIds: [
      `${input.spec.agentId}.structured_output.v2`,
      SECTOR_DIRECTION_COMPARISON_CONTRACT_VERSION,
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
      `model_subcalls=${usageSummary.model_subcall_count}`,
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

function requiredAcceptedAuditOutputHash(value: string | null, agentId: string): string {
  if (!value || !/^sha256:[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${agentId}: accepted output lacks an Agent-run output hash`);
  }
  return value;
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

export function buildSectorCoverageDirective(
  payloads: ReadonlyMap<string, string>,
  agentId: StandardSectorAgentId,
  asOf: string,
  allowFakeFallback = false,
): SectorCoverageDirective {
  const raw = payloads.get("get_role_event_snapshot");
  if (!raw) {
    if (agentId !== "biotech" && !allowFakeFallback) {
      throw new Error(`${agentId}: required role-event snapshot payload is missing`);
    }
    return unavailableSectorCoverageDirective(agentId, asOf);
  }

  let payload: Record<string, unknown>;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("payload is not an object");
    }
    payload = parsed as Record<string, unknown>;
  } catch (cause) {
    if (allowFakeFallback) return unavailableSectorCoverageDirective(agentId, asOf);
    throw new Error(`${agentId}: invalid role-event snapshot JSON`, { cause });
  }
  const coverage = objectRecord(payload.coverage);
  const projections = Array.isArray(payload.projections) ? payload.projections : null;
  const snapshotHash = payload.role_event_snapshot_hash;
  const snapshotBody = Object.fromEntries(
    Object.entries(payload).filter(([key]) => key !== "role_event_snapshot_hash"),
  );
  const snapshotWithoutId = Object.fromEntries(
    Object.entries(payload).filter(
      ([key]) => key !== "role_event_snapshot_id" && key !== "role_event_snapshot_hash",
    ),
  );
  const expectedSnapshotId = `role-event-snapshot:${canonicalHash(snapshotWithoutId).slice(
    "sha256:".length,
  )}`;
  if (
    payload.role_event_snapshot_id !== expectedSnapshotId ||
    payload.schema_version !== "role_event_snapshot_v2" ||
    payload.contract_version !== "role_event_coverage_v2" ||
    payload.consumer_agent !== agentId ||
    typeof payload.as_of !== "string" ||
    !payload.as_of.startsWith(asOf) ||
    typeof snapshotHash !== "string" ||
    snapshotHash !== canonicalHash(snapshotBody) ||
    !coverage ||
    !projections
  ) {
    throw new Error(`${agentId}: role-event snapshot identity/hash binding is invalid`);
  }
  const sourceState = coverage.coverage_state;
  if (
    sourceState !== "AVAILABLE_MATERIAL_EVENTS" &&
    sourceState !== "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT" &&
    sourceState !== "SOURCE_UNAVAILABLE"
  ) {
    throw new Error(`${agentId}: role-event coverage state is invalid`);
  }
  if (
    !Array.isArray(coverage.coverage_evidence_ids) ||
    !Array.isArray(coverage.material_event_revision_ids) ||
    !Array.isArray(coverage.required_route_ids) ||
    !Array.isArray(coverage.healthy_route_ids) ||
    !Array.isArray(coverage.unhealthy_route_ids)
  ) {
    throw new Error(`${agentId}: role-event coverage id arrays are missing`);
  }
  const requiredRouteIds = requireStringArray(
    coverage.required_route_ids,
    `${agentId}: role-event required_route_ids`,
  );
  const healthyRouteIds = requireStringArray(
    coverage.healthy_route_ids,
    `${agentId}: role-event healthy_route_ids`,
  );
  const unhealthyRouteIds = requireStringArray(
    coverage.unhealthy_route_ids,
    `${agentId}: role-event unhealthy_route_ids`,
    true,
  );
  if (
    coverage.coverage_completeness !== "COMPLETE" ||
    coverage.query_complete !== true ||
    coverage.coverage_contract_version !== "role_event_coverage_v2" ||
    typeof coverage.coverage_as_of !== "string" ||
    !coverage.coverage_as_of.startsWith(asOf) ||
    requiredRouteIds.join("\0") !== [...new Set(requiredRouteIds)].sort().join("\0") ||
    healthyRouteIds.join("\0") !== [...new Set(healthyRouteIds)].sort().join("\0") ||
    requiredRouteIds.join("\0") !== healthyRouteIds.join("\0") ||
    unhealthyRouteIds.length !== 0
  ) {
    throw new Error(`${agentId}: role-event route coverage is incomplete`);
  }
  const evidenceIds = requireStringArray(
    coverage.coverage_evidence_ids,
    `${agentId}: role-event coverage_evidence_ids`,
  );
  const materialEventIds = requireStringArray(
    coverage.material_event_revision_ids,
    `${agentId}: role-event material_event_revision_ids`,
    true,
  );
  if (evidenceIds.length > MAX_SECTOR_COVERAGE_EVIDENCE_IDS) {
    throw new Error(
      `${agentId}: role-event coverage_evidence_ids exceed ${MAX_SECTOR_COVERAGE_EVIDENCE_IDS}`,
    );
  }
  if (
    evidenceIds.length === 0 ||
    evidenceIds.join("\0") !== [...new Set(evidenceIds)].sort().join("\0") ||
    materialEventIds.join("\0") !== [...new Set(materialEventIds)].sort().join("\0")
  ) {
    throw new Error(`${agentId}: role-event coverage ids are invalid`);
  }
  const projectionEventIds = projections
    .map((projection) => objectRecord(projection)?.event_revision_id)
    .filter((value): value is string => typeof value === "string")
    .sort();
  if (
    projectionEventIds.length !== projections.length ||
    projectionEventIds.join("\0") !== materialEventIds.join("\0") ||
    (sourceState === "AVAILABLE_MATERIAL_EVENTS") !== materialEventIds.length > 0 ||
    (sourceState === "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT" && materialEventIds.length > 0) ||
    sourceState === "SOURCE_UNAVAILABLE"
  ) {
    throw new Error(`${agentId}: role-event material-event coverage binding is invalid`);
  }
  const expectedPresence =
    materialEventIds.length > 0 ? "MATERIAL_EVENTS_PRESENT" : "NO_MATERIAL_EVENT_OBSERVED";
  if (coverage.event_presence_state !== expectedPresence) {
    throw new Error(`${agentId}: role-event presence state is inconsistent`);
  }
  const hasCatalyst = projections.some(
    (projection) => objectRecord(projection)?.allowed_purpose === "CATALYST",
  );
  const orderedEvidenceIds = evidenceIds as [string, ...string[]];
  return {
    contract_version: "sector_role_event_coverage_directive_v1",
    macro_event_fit: {
      coverage_state: sourceState,
      coverage_evidence_ids: orderedEvidenceIds,
    },
    catalysts: {
      coverage_state: hasCatalyst
        ? "AVAILABLE_MATERIAL_CATALYSTS"
        : "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST",
      coverage_evidence_ids: orderedEvidenceIds,
    },
  };
}

function unavailableSectorCoverageDirective(
  agentId: StandardSectorAgentId,
  asOf: string,
): SectorCoverageDirective {
  const evidenceId = `coverage:role-event-not-authorized:${canonicalHash({
    contract_version: "sector_role_event_coverage_directive_v1",
    agent_id: agentId,
    as_of: asOf,
  }).slice("sha256:".length)}`;
  return {
    contract_version: "sector_role_event_coverage_directive_v1",
    macro_event_fit: {
      coverage_state: "SOURCE_UNAVAILABLE",
      coverage_evidence_ids: [evidenceId],
    },
    catalysts: {
      coverage_state: "SOURCE_UNAVAILABLE",
      coverage_evidence_ids: [evidenceId],
    },
  };
}

function validateSectorRoleEventCrossBinding(
  payloads: ReadonlyMap<string, string>,
  agentId: StandardSectorAgentId,
  allowFakeFallback: boolean,
): void {
  const sectorRaw = payloads.get("get_sector_research_snapshot");
  if (!sectorRaw) throw new Error(`${agentId}: missing sector snapshot payload`);
  let sector: Record<string, unknown>;
  try {
    const parsed = JSON.parse(sectorRaw);
    sector = objectRecord(parsed) ?? {};
  } catch (cause) {
    if (allowFakeFallback) return;
    throw new Error(`${agentId}: invalid sector snapshot JSON`, { cause });
  }
  if (sector.schema_version !== "sector_research_snapshot_v4") {
    if (allowFakeFallback) return;
    throw new Error(`${agentId}: sector snapshot version cannot bind role-event coverage`);
  }
  if (agentId === "biotech") {
    if (sector.role_event_snapshot_ref !== undefined || sector.event_coverage !== undefined) {
      throw new Error(`${agentId}: unauthorized role-event binding is present`);
    }
    return;
  }

  const roleEventRaw = payloads.get("get_role_event_snapshot");
  if (!roleEventRaw) throw new Error(`${agentId}: required role-event snapshot payload is missing`);
  let roleEvent: Record<string, unknown>;
  try {
    const parsed = JSON.parse(roleEventRaw);
    roleEvent = objectRecord(parsed) ?? {};
  } catch (cause) {
    throw new Error(`${agentId}: invalid role-event snapshot JSON`, { cause });
  }
  const reference = objectRecord(sector.role_event_snapshot_ref);
  const eventCoverage = objectRecord(sector.event_coverage);
  if (
    !reference ||
    Object.keys(reference).sort().join("\0") !==
      ["role_event_snapshot_hash", "role_event_snapshot_id"].join("\0") ||
    reference.role_event_snapshot_id !== roleEvent.role_event_snapshot_id ||
    reference.role_event_snapshot_hash !== roleEvent.role_event_snapshot_hash ||
    !eventCoverage ||
    canonicalHash(eventCoverage) !== canonicalHash(roleEvent.coverage)
  ) {
    throw new Error(`${agentId}: Sector/role-event snapshot cross-binding mismatch`);
  }
}

function bindSectorCoverageEvidence(
  runtime: RuntimeEvidenceSnapshot,
  directive: SectorCoverageDirective,
  agentId: StandardSectorAgentId,
): RuntimeEvidenceSnapshot {
  const coverageIds = [
    ...new Set([
      ...directive.macro_event_fit.coverage_evidence_ids,
      ...directive.catalysts.coverage_evidence_ids,
    ]),
  ].sort();
  const requiresClaimEvidence =
    directive.macro_event_fit.coverage_state !== "SOURCE_UNAVAILABLE" ||
    directive.catalysts.coverage_state !== "SOURCE_UNAVAILABLE";
  if (!requiresClaimEvidence) return runtime;
  const roleEventToolEvidence = runtime.evidenceLedger.find(
    (entry) => entry.source_kind === "tool" && entry.tool_or_source === "get_role_event_snapshot",
  );
  if (!roleEventToolEvidence) {
    throw new Error(`${agentId}: runtime role-event evidence binding is missing`);
  }
  const aliases = coverageIds.flatMap((evidenceId) => {
    const existing = runtime.evidenceById.get(evidenceId);
    if (existing) {
      if (existing.tool_or_source !== "get_role_event_snapshot") {
        throw new Error(`${agentId}: role-event coverage evidence id collides with another source`);
      }
      return [];
    }
    const sourceFingerprint = canonicalHash({
      schema_version: "sector_role_event_coverage_evidence_alias_v1",
      role_event_tool_evidence_id: roleEventToolEvidence.evidence_id,
      coverage_evidence_id: evidenceId,
    });
    return [
      {
        ...roleEventToolEvidence,
        evidence_id: evidenceId,
        metric: "role_event_coverage",
        value: {
          role_event_tool_evidence_id: roleEventToolEvidence.evidence_id,
          coverage_evidence_id: evidenceId,
        },
        source_fingerprint: sourceFingerprint,
      },
    ];
  });
  if (aliases.length === 0) return runtime;
  const evidenceLedger = [...runtime.evidenceLedger, ...aliases].sort((left, right) =>
    left.evidence_id.localeCompare(right.evidence_id),
  );
  return {
    ...runtime,
    evidenceLedger,
    evidenceById: new Map(evidenceLedger.map((entry) => [entry.evidence_id, entry])),
    visibleCatalog:
      `${runtime.visibleCatalog}\n` +
      `Runtime-owned role-event coverage aliases (also valid evidence_id values):\n` +
      JSON.stringify(
        aliases.map((entry) => ({
          evidence_id: entry.evidence_id,
          tool_or_source: entry.tool_or_source,
          metric: entry.metric,
          as_of: entry.as_of,
          freshness: entry.freshness,
        })),
      ),
  };
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function requireStringArray(value: unknown, label: string, allowEmpty = false): string[] {
  if (
    !Array.isArray(value) ||
    (!allowEmpty && value.length === 0) ||
    value.some((item) => typeof item !== "string" || item.length === 0)
  ) {
    throw new Error(
      `${label} must be a ${allowEmpty ? "possibly empty" : "non-empty"} string array`,
    );
  }
  return value as string[];
}

const SectorSecurityScoringRowSchema = z
  .object({
    ts_code: z.string().regex(/^\d{6}\.(?:SH|SZ|BJ)$/),
    direction_id: z.string().trim().min(1),
    availability_status: z.enum(["AVAILABLE", "UNAVAILABLE"]),
    unavailability_reason: z
      .enum(["INSUFFICIENT_PIT_OBSERVATIONS", "MISSING_ADJUSTMENT_FACTOR", "MISSING_MONEYFLOW"])
      .nullable(),
    observation_date: z.string().trim().min(1),
    released_at: z.string().trim().min(1),
    vintage_at: z.string().trim().min(1),
    pit_status: z.literal("PIT_VERIFIED"),
    adjusted_return_20d: z.number().finite().nullable(),
    realized_volatility_20d: z.number().finite().nonnegative().nullable(),
    median_amount_20d_cny: z.number().finite().nonnegative().nullable(),
    net_moneyflow_20d_cny: z.number().finite().nullable(),
    observation_count: z.number().int().min(0).max(20),
    required_observation_count: z.literal(20),
    coverage_ratio: z.number().finite().min(0).max(1),
    evidence_ids: z.array(z.string().trim().min(1)),
    security_scoring_row_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
  })
  .strict()
  .superRefine((row, ctx) => {
    const values = [
      row.adjusted_return_20d,
      row.realized_volatility_20d,
      row.median_amount_20d_cny,
      row.net_moneyflow_20d_cny,
    ];
    if (row.availability_status === "AVAILABLE") {
      if (row.unavailability_reason !== null || values.some((value) => value === null)) {
        ctx.addIssue({
          code: "custom",
          path: ["availability_status"],
          message: "AVAILABLE requires every score and no unavailability reason",
        });
      }
    } else if (row.unavailability_reason === null || values.some((value) => value !== null)) {
      ctx.addIssue({
        code: "custom",
        path: ["availability_status"],
        message: "UNAVAILABLE requires a reason and null scores",
      });
    }
  }) as z.ZodType<SectorSecurityScoringRow>;

function parseSectorRuntimeSnapshot(
  payloads: ReadonlyMap<string, string>,
  agentId: StandardSectorAgentId,
  expectedAsOf: string,
  allowFakeFallback: boolean,
): {
  eligibleDirectionIds: string[];
  securityScoringRows: SectorSecurityScoringRow[];
  snapshotHash: string;
} {
  const raw = payloads.get("get_sector_research_snapshot");
  if (!raw) throw new Error(`${agentId}: missing sector snapshot payload`);
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(raw) as Record<string, unknown>;
  } catch (cause) {
    if (!allowFakeFallback) {
      throw new Error(`${agentId}: invalid sector snapshot JSON`, { cause });
    }
    payload = {};
  }
  const syntheticFallback =
    allowFakeFallback && payload.schema_version !== "sector_research_snapshot_v4";
  const registered = STANDARD_SECTOR_ROLE_CONTRACTS[agentId].directionIds;
  const candidateIds = Array.isArray(payload.direction_ids)
    ? payload.direction_ids
    : syntheticFallback
      ? registered
      : [];
  const eligibleDirectionIds = candidateIds.filter(
    (value): value is string => typeof value === "string",
  );
  if (
    eligibleDirectionIds.length < 3 ||
    eligibleDirectionIds.length !== registered.length ||
    eligibleDirectionIds.some((value, index) => value !== registered[index])
  ) {
    throw new Error(`${agentId}: snapshot must expose the exact multi-direction registry`);
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
  let securityScoringRows = Array.isArray(payload.security_scoring_rows)
    ? payload.security_scoring_rows.flatMap((row) => {
        const parsed = SectorSecurityScoringRowSchema.safeParse(row);
        return parsed.success ? [parsed.data] : [];
      })
    : [];
  if (syntheticFallback && securityScoringRows.length === 0) {
    const fallbackUniverse =
      securityUniverse.length > 0
        ? securityUniverse
        : eligibleDirectionIds.map((directionId, index) => ({
            ts_code: `${String(600000 + index).padStart(6, "0")}.SH`,
            direction_id: directionId,
          }));
    securityScoringRows = fallbackUniverse.map((security, index) => {
      const body = {
        ts_code: security.ts_code,
        direction_id: security.direction_id,
        availability_status: "AVAILABLE" as const,
        unavailability_reason: null,
        observation_date: "1970-01-01",
        released_at: "1970-01-01",
        vintage_at: "1970-01-01",
        pit_status: "PIT_VERIFIED" as const,
        adjusted_return_20d: 0,
        realized_volatility_20d: 0,
        median_amount_20d_cny: 1_000_000 - index,
        net_moneyflow_20d_cny: 0,
        observation_count: 20,
        required_observation_count: 20,
        coverage_ratio: 1,
        evidence_ids: [],
      };
      return { ...body, security_scoring_row_hash: canonicalHash(body) };
    });
  }
  const membershipKeys = new Set(
    securityUniverse.map((row) => `${row.direction_id}\0${row.ts_code}`),
  );
  const membershipTickers = securityUniverse.map((row) => row.ts_code);
  const registeredDirectionSet = new Set(registered);
  const securityUniverseIsValid =
    securityUniverse.length > 0 &&
    new Set(membershipTickers).size === membershipTickers.length &&
    securityUniverse.every(
      (row) =>
        /^\d{6}\.(?:SH|SZ|BJ)$/.test(row.ts_code) && registeredDirectionSet.has(row.direction_id),
    ) &&
    registered.every((directionId) =>
      securityUniverse.some((row) => row.direction_id === directionId),
    );
  const scoringKeys = securityScoringRows.map((row) => `${row.direction_id}\0${row.ts_code}`);
  const scoringRowsAreCanonical = securityScoringRows.every(
    (row, index) =>
      index === 0 ||
      `${securityScoringRows[index - 1]?.direction_id}\0${securityScoringRows[index - 1]?.ts_code}` <
        `${row.direction_id}\0${row.ts_code}`,
  );
  const scoringRowsAreValid = securityScoringRows.every((row) => {
    const { security_scoring_row_hash: suppliedHash, ...body } = row;
    const observationAt = Date.parse(row.observation_date);
    const releasedAt = Date.parse(row.released_at);
    const vintageAt = Date.parse(row.vintage_at);
    const asOfEnd = Date.parse(`${expectedAsOf}T23:59:59.999Z`);
    const evidenceIdsAreValid =
      syntheticFallback ||
      (row.evidence_ids.length > 0 &&
        row.evidence_ids.join("\0") === [...new Set(row.evidence_ids)].sort().join("\0"));
    const temporalsAreValid =
      syntheticFallback ||
      (Number.isFinite(observationAt) &&
        Number.isFinite(releasedAt) &&
        Number.isFinite(vintageAt) &&
        Number.isFinite(asOfEnd) &&
        observationAt <= releasedAt &&
        releasedAt <= vintageAt &&
        vintageAt <= asOfEnd);
    return (
      suppliedHash === canonicalHash(body) &&
      registeredDirectionSet.has(row.direction_id) &&
      row.required_observation_count === 20 &&
      row.observation_count >= 0 &&
      row.observation_count <= 20 &&
      Math.abs(row.coverage_ratio - row.observation_count / 20) <= 1e-12 &&
      evidenceIdsAreValid &&
      temporalsAreValid &&
      (row.availability_status === "UNAVAILABLE" ||
        (row.observation_count === 20 && Math.abs(row.coverage_ratio - 1) <= 1e-12)) &&
      (row.availability_status === "AVAILABLE" || row.observation_count < 20)
    );
  });
  if (
    securityScoringRows.length === 0 ||
    (!syntheticFallback &&
      (payload.schema_version !== "sector_research_snapshot_v4" ||
        payload.sector_agent_id !== agentId ||
        payload.as_of_date !== expectedAsOf ||
        payload.eligible_count !== securityUniverse.length ||
        !securityUniverseIsValid ||
        securityUniverse.length !== membershipKeys.size ||
        payload.security_scoring_contract_version !== SECURITY_SCORING_CONTRACT_VERSION ||
        payload.security_scoring_contract_hash !== SECURITY_SCORING_CONTRACT_HASH ||
        payload.security_scoring_rows_hash !== canonicalHash(securityScoringRows) ||
        scoringKeys.length !== membershipKeys.size ||
        new Set(scoringKeys).size !== scoringKeys.length ||
        scoringKeys.some((key) => !membershipKeys.has(key)) ||
        !scoringRowsAreCanonical ||
        !scoringRowsAreValid))
  ) {
    throw new Error(`${agentId}: snapshot security scoring rows are not exact PIT bindings`);
  }
  const snapshotBody = Object.fromEntries(
    Object.entries(payload).filter(([key]) => key !== "snapshot_hash"),
  );
  const suppliedSnapshotHash = payload.snapshot_hash;
  if (
    !syntheticFallback &&
    (typeof suppliedSnapshotHash !== "string" ||
      suppliedSnapshotHash !== canonicalHash(snapshotBody))
  ) {
    throw new Error(`${agentId}: snapshot_hash is not bound to the runtime payload`);
  }
  const snapshotHash =
    !syntheticFallback &&
    typeof suppliedSnapshotHash === "string" &&
    /^sha256:[0-9a-f]{64}$/.test(suppliedSnapshotHash)
      ? suppliedSnapshotHash
      : canonicalHash(payload);
  return { eligibleDirectionIds, securityScoringRows, snapshotHash };
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

const FINAL_GROUNDING_METRIC_LIMIT = 26;
const FINAL_GROUNDING_SECURITY_LIMIT_PER_DIRECTION = 64;
const FINAL_GROUNDING_COMPARISON_LIMIT = 64;
const FINAL_GROUNDING_CLAIM_LIMIT = 512;

/**
 * Runtime-owned, bounded projection for the fresh final-selection invocation.
 * It preserves exact frozen numbers and the accepted comparison/claim closure,
 * while excluding source prose and source-owned evidence identifiers.
 */
export function buildSectorFinalGroundingProjection(input: {
  payloads: ReadonlyMap<string, string>;
  directive: SectorFinalSelectionRuntimeDirective;
  finalizedComparisons: readonly {
    comparison_local_id: string;
    direction_a_id: string;
    direction_b_id: string;
    criterion_results: readonly unknown[];
    claim_refs: string[];
  }[];
  resolutions: readonly unknown[];
  comparisonClaims: readonly {
    claim_id: string;
    evidence_ids: string[];
  }[];
  finalizedPairMatrixHash: string;
  runtimeEvidence: RuntimeEvidenceSnapshot;
}): Record<string, unknown> {
  const raw = input.payloads.get("get_sector_research_snapshot");
  let snapshot: Record<string, unknown> = {};
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        snapshot = parsed as Record<string, unknown>;
      }
    } catch {
      snapshot = {};
    }
  }
  const selectedDirections = new Set(
    [input.directive.preferred_direction_id, input.directive.least_preferred_direction_id].filter(
      (directionId): directionId is string => directionId !== null,
    ),
  );
  const directionCards = Array.isArray(snapshot.direction_cards)
    ? snapshot.direction_cards.flatMap((item) => {
        if (!item || typeof item !== "object" || Array.isArray(item)) return [];
        const card = item as Record<string, unknown>;
        if (typeof card.direction_id !== "string" || !selectedDirections.has(card.direction_id)) {
          return [];
        }
        const metrics = Array.isArray(card.metrics)
          ? card.metrics.slice(0, FINAL_GROUNDING_METRIC_LIMIT).flatMap((metricItem) => {
              if (!metricItem || typeof metricItem !== "object" || Array.isArray(metricItem)) {
                return [];
              }
              const metric = metricItem as Record<string, unknown>;
              return [
                withoutSourceEvidenceIds({
                  metric_id: metric.metric_id,
                  metric_family: metric.metric_family,
                  unit: metric.unit,
                  availability_status: metric.availability_status,
                  value: metric.value,
                  observation_date: metric.observation_date,
                  released_at: metric.released_at,
                  vintage_at: metric.vintage_at,
                  pit_status: metric.pit_status,
                  observation_count: metric.observation_count,
                  eligible_count: metric.eligible_count,
                  observed_count: metric.observed_count,
                  coverage_ratio: metric.coverage_ratio,
                  etf_family_id: metric.etf_family_id,
                  etf_family_hash: metric.etf_family_hash,
                  metric_observation_hash: metric.metric_observation_hash,
                }),
              ];
            })
          : [];
        return [
          withoutSourceEvidenceIds({
            direction_id: card.direction_id,
            eligible_count: card.eligible_count,
            readiness_status: card.readiness_status,
            membership_hash: card.membership_hash,
            etf_family: card.etf_family,
            metrics,
            direction_card_hash: card.direction_card_hash,
          }),
        ];
      })
    : [];
  const securitiesByDirection = new Map<string, Record<string, unknown>[]>();
  const allowedByDirection = new Map([
    [
      input.directive.preferred_direction_id,
      new Set(input.directive.allowed_preferred_security_ids),
    ],
    [
      input.directive.least_preferred_direction_id,
      new Set(input.directive.allowed_least_preferred_security_ids),
    ],
  ]);
  if (Array.isArray(snapshot.security_scoring_rows)) {
    for (const item of snapshot.security_scoring_rows) {
      if (!item || typeof item !== "object" || Array.isArray(item)) continue;
      const row = item as Record<string, unknown>;
      if (
        typeof row.direction_id !== "string" ||
        typeof row.ts_code !== "string" ||
        !selectedDirections.has(row.direction_id) ||
        !allowedByDirection.get(row.direction_id)?.has(row.ts_code)
      ) {
        continue;
      }
      const current = securitiesByDirection.get(row.direction_id) ?? [];
      if (current.length >= FINAL_GROUNDING_SECURITY_LIMIT_PER_DIRECTION) continue;
      current.push(
        withoutSourceEvidenceIds({
          ts_code: row.ts_code,
          direction_id: row.direction_id,
          availability_status: row.availability_status,
          unavailability_reason: row.unavailability_reason,
          adjusted_return_20d: row.adjusted_return_20d,
          realized_volatility_20d: row.realized_volatility_20d,
          median_amount_20d_cny: row.median_amount_20d_cny,
          net_moneyflow_20d_cny: row.net_moneyflow_20d_cny,
          observation_count: row.observation_count,
          required_observation_count: row.required_observation_count,
          coverage_ratio: row.coverage_ratio,
          observation_date: row.observation_date,
          released_at: row.released_at,
          vintage_at: row.vintage_at,
          pit_status: row.pit_status,
          security_scoring_row_hash: row.security_scoring_row_hash,
        }) as Record<string, unknown>,
      );
      securitiesByDirection.set(row.direction_id, current);
    }
  }
  const comparisons = input.finalizedComparisons.slice(0, FINAL_GROUNDING_COMPARISON_LIMIT);
  const referencedClaimIds = new Set(
    comparisons.flatMap((comparison) =>
      Array.isArray(comparison.claim_refs)
        ? comparison.claim_refs.filter((value): value is string => typeof value === "string")
        : [],
    ),
  );
  const comparisonClaims = input.comparisonClaims
    .filter((claim) => referencedClaimIds.has(claim.claim_id))
    .slice(0, FINAL_GROUNDING_CLAIM_LIMIT);
  const referencedEvidenceIds = new Set(comparisonClaims.flatMap((claim) => claim.evidence_ids));
  const evidenceAliases = input.runtimeEvidence.evidenceLedger
    .filter((entry) => referencedEvidenceIds.has(entry.evidence_id))
    .map((entry) => ({
      evidence_id: entry.evidence_id,
      tool_or_source: entry.tool_or_source,
      metric: entry.metric,
      value: entry.value,
      unit: entry.unit,
      as_of: entry.as_of,
      lookback: entry.lookback,
      freshness: entry.freshness,
      direction: entry.direction,
      source_fingerprint: entry.source_fingerprint,
    }));
  return {
    schema_version: "sector_final_grounding_projection_v1",
    snapshot_hash: snapshot.snapshot_hash ?? null,
    finalized_pair_matrix_hash: input.finalizedPairMatrixHash,
    selected_direction_cards: directionCards,
    selected_security_scoring_rows: [...selectedDirections].map((directionId) => {
      const allowedIds =
        directionId === input.directive.preferred_direction_id
          ? input.directive.allowed_preferred_security_ids
          : input.directive.allowed_least_preferred_security_ids;
      const rowByTicker = new Map(
        (securitiesByDirection.get(directionId) ?? []).map((row) => [row.ts_code, row]),
      );
      const rows = allowedIds.flatMap((tsCode) => {
        const row = rowByTicker.get(tsCode);
        return row ? [row] : [];
      });
      const allowedCount = allowedIds.length;
      return {
        direction_id: directionId,
        rows,
        eligible_count: allowedCount,
        truncated: allowedCount > rows.length,
      };
    }),
    finalized_comparisons: comparisons,
    finalized_resolutions: input.resolutions.slice(0, FINAL_GROUNDING_COMPARISON_LIMIT),
    comparison_claims: comparisonClaims,
    evidence_aliases: evidenceAliases,
    bounds: {
      metrics_per_direction: FINAL_GROUNDING_METRIC_LIMIT,
      securities_per_direction: FINAL_GROUNDING_SECURITY_LIMIT_PER_DIRECTION,
      comparisons: FINAL_GROUNDING_COMPARISON_LIMIT,
      claims: FINAL_GROUNDING_CLAIM_LIMIT,
    },
  };
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

function sectorUsageAttemptRecorder(input: {
  api: BridgeApi;
  capability: SignedAgentToolCapability;
  agentId: StandardSectorAgentId;
  attemptedStage: SectorModelUsageReport["attempted_stage"];
  directionComparisonAudit: { id: string; hash: string } | null;
  conflictReview: { id: string; hash: string } | null;
}): (audit: AgentAttemptAudit, rawOutput: unknown) => Promise<void> {
  return async (audit) => {
    const evidenceBody = {
      schema_version: "sector_provider_usage_evidence_v1",
      capability_id: input.capability.manifest.capability_id,
      sector_agent_id: input.agentId,
      attempted_stage: input.attemptedStage,
      attempt_index: audit.attempt,
      attempt_kind: audit.kind,
      accepted: audit.accepted,
      output_hash: audit.output_hash,
      prompt_tokens: audit.prompt_tokens,
      completion_tokens: audit.completion_tokens,
      elapsed_ms: audit.elapsed_ms,
      error_fingerprints: audit.error_fingerprints,
    };
    const evidenceHash = canonicalHash(evidenceBody);
    const report: SectorModelUsageReport = {
      model_subcall_id: `sector-model-subcall:${canonicalHash({
        capability_id: input.capability.manifest.capability_id,
        attempted_stage: input.attemptedStage,
        attempt_index: audit.attempt,
        provider_usage_evidence_hash: evidenceHash,
      }).slice("sha256:".length)}`,
      attempted_stage: input.attemptedStage,
      attempt_index: audit.attempt,
      attempt_status: audit.accepted
        ? "ACCEPTED"
        : audit.validation_issues.some((issue) => issue.validator === "model_runtime")
          ? "OPERATIONAL_FAILURE"
          : "REJECTED",
      input_tokens: audit.prompt_tokens,
      output_tokens: audit.completion_tokens,
      provider_usage_evidence_id: `sector-provider-usage:${evidenceHash.slice("sha256:".length)}`,
      provider_usage_evidence_hash: evidenceHash,
      direction_comparison_audit_id: input.directionComparisonAudit?.id ?? null,
      direction_comparison_audit_hash: input.directionComparisonAudit?.hash ?? null,
      conflict_review_id: input.conflictReview?.id ?? null,
      conflict_review_hash: input.conflictReview?.hash ?? null,
    };
    await input.api.toolsRecordModelUsage(input.capability, report);
  };
}

function buildFakeSectorUsageSummary(input: {
  agentId: StandardSectorAgentId;
  state: DailyCycleStateType;
  snapshotBundleId: string;
  snapshotBundleHash: string;
  audits: readonly AgentRunAudit[];
  directionComparisonAudit: { id: string; hash: string };
  conflictReview: { id: string; hash: string } | null;
}): SectorModelUsageSummaryReceipt {
  const attempts = input.audits.flatMap((audit) =>
    audit.attempts.map((attempt) => ({ stage: audit.stage, attempt })),
  );
  const usage = sumAuditTokens(input.audits);
  const runId = input.state.trace_id || input.state.as_of_date || "fake_run";
  const finalizedAt = `${input.state.as_of_date}T00:00:00.000Z`;
  const capabilityId = `fake-sector-capability:${input.agentId}:${runId}`;
  const ledgerBody = {
    schema_version: "server_owned_model_usage_ledger_v1",
    capability_id: capabilityId,
    attempts: attempts.map(({ stage, attempt }) => ({
      stage,
      attempt_index: attempt.attempt,
      accepted: attempt.accepted,
      input_tokens: attempt.prompt_tokens,
      output_tokens: attempt.completion_tokens,
      output_hash: attempt.output_hash,
    })),
  };
  const ledgerHash = canonicalHash(ledgerBody);
  const instrumentation = {
    instrumentation_contract_id: "sector_inference_usage_instrumentation",
    instrumentation_contract_version: "sector_inference_usage_instrumentation_v1",
    source_contract_version: "server_owned_model_usage_ledger_v1",
    measurement_rule: "sum_provider_reported_tokens_and_count_attempted_model_subcalls",
  };
  const unsigned = {
    schema_version: "sector_model_usage_summary_receipt_v1" as const,
    usage_summary_receipt_id: `fake-sector-usage-summary:${input.agentId}:${runId}`,
    capability_id: capabilityId,
    capability_manifest_hash: canonicalHash({ capability_id: capabilityId }),
    graph_run_id: runId,
    run_slot_id: `${runId}:${input.agentId}`,
    run_id: runId,
    node_id: `${input.agentId}:${input.agentId}`,
    agent_id: input.agentId,
    stage: input.agentId,
    as_of: input.state.as_of_date,
    snapshot_bundle_id: input.snapshotBundleId,
    snapshot_bundle_hash: input.snapshotBundleHash,
    pair_root_reservation_id: null,
    pair_side: null,
    budget_contract_ref: null,
    model_subcall_count: attempts.length,
    last_attempted_stage: "COMPLETED" as const,
    conflict_review_triggered: input.conflictReview !== null,
    input_tokens: usage.promptTokens,
    output_tokens: usage.completionTokens,
    model_path_disposition: "COMPLETED" as const,
    direction_comparison_audit_id: input.directionComparisonAudit.id,
    direction_comparison_audit_hash: input.directionComparisonAudit.hash,
    conflict_review_id: input.conflictReview?.id ?? null,
    conflict_review_hash: input.conflictReview?.hash ?? null,
    ...instrumentation,
    instrumentation_contract_hash: canonicalHash(instrumentation),
    usage_ledger_record_id: `fake-sector-usage-ledger:${input.agentId}:${runId}`,
    usage_ledger_record_hash: ledgerHash,
    measured_at: finalizedAt,
    finalized_at: finalizedAt,
    receipt_signing_key_id: "fake-runtime-only",
  };
  const receiptHash = canonicalHash(unsigned);
  return {
    ...unsigned,
    usage_summary_receipt_hash: receiptHash,
    receipt_signature: `fake-runtime-only:${receiptHash.slice("sha256:".length)}`,
  };
}

function finalLanguageInstruction(language: LoaderLanguage): string {
  return language === "en"
    ? "Write prose fields in English."
    : "Write prose fields in Chinese; keep numbers numeric.";
}

function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
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
    `and select one distinct least-preferred direction. Only a runtime-proven empty frozen shortlist ` +
    `may use NO_QUALIFIED_SECURITY for that security leg; a non-empty shortlist requires picks. ` +
    `Treat the ten Macro transmissions as distinct inputs; record all ten required submission summaries ` +
    `and only the applicable target-level attributions.`
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
        const evidence = {
          evidence_id: `fake-${agentId}-snapshot`,
          evidence_kind: "SYNTHETIC_RELATIONSHIP_RECORD",
          source_id: "fake_llm_structural_smoke",
          source_endpoint: "fake_relationship_fixture",
          observation_date: asOf,
          released_at: asOf,
          vintage_at: asOf,
          pit_status: "PIT_VERIFIED" as const,
          content_hash: canonicalHash({ fixture: "fake-relationship-source" }),
          evidence_record_hash: "",
        };
        evidence.evidence_record_hash = canonicalHash(
          Object.fromEntries(
            Object.entries(evidence).filter(([key]) => key !== "evidence_record_hash"),
          ),
        );
        const relationship = {
          edge_candidate_id: "relationship-candidate:fixture",
          source_entity: "synthetic-holder",
          source_entity_type: "HOLDER" as const,
          target_entity: "000001.SZ",
          target_entity_type: "PIT_ELIGIBLE_SECURITY" as const,
          target_sector_id: "sector:energy",
          edge_type: "SHAREHOLDING",
          activation_trigger: "Synthetic disclosed shareholding remains active.",
          observation_date: asOf,
          released_at: asOf,
          vintage_at: asOf,
          pit_status: "PIT_VERIFIED" as const,
          evidence_ids: [evidence.evidence_id],
          relationship_row_hash: "",
        };
        relationship.relationship_row_hash = canonicalHash(
          Object.fromEntries(
            Object.entries(relationship).filter(([key]) => key !== "relationship_row_hash"),
          ),
        );
        const matchedNonEdges = [
          {
            source_entity: "synthetic-holder",
            source_entity_type: "HOLDER" as const,
            target_entity: "000002.SZ",
            target_entity_type: "PIT_ELIGIBLE_SECURITY" as const,
            target_sector_id: "sector:energy",
            edge_type: "SHAREHOLDING",
            materiality_bucket: "MEDIUM" as const,
          },
        ];
        const opportunityBody = {
          run_id: runId,
          as_of: asOf,
          candidate_generation_contract_version: "relationship_candidate_fixture_v2",
          scoring_contract_version: "relationship_scoring_fixture_v2",
          ordered_opportunities: [
            {
              edge_candidate_id: "relationship-candidate:fixture",
              source_entity: "synthetic-holder",
              source_entity_type: "HOLDER" as const,
              target_entity: "000001.SZ",
              target_entity_type: "PIT_ELIGIBLE_SECURITY" as const,
              target_sector_id: "sector:energy",
              edge_type: "SHAREHOLDING",
              materiality_weight: 1,
              materiality_bucket: "MEDIUM" as const,
              matched_non_edge_set_id: "matched-non-edge:fixture",
              matched_non_edge_set_hash: canonicalHash(matchedNonEdges),
              matched_non_edges: matchedNonEdges,
            },
          ],
        };
        const opportunityHash = canonicalHash(opportunityBody);
        const snapshot = {
          schema_version: "relationship_research_snapshot_v3",
          as_of_date: asOf,
          frozen_holder_domain_hash: canonicalHash(["synthetic-holder"]),
          frozen_security_domain_hash: canonicalHash(["000001.SZ", "000002.SZ"]),
          relationships: [relationship],
          prediction_opportunity_set: {
            opportunity_set_id: `relationship-opportunity:${opportunityHash.slice(7)}`,
            opportunity_set_hash: opportunityHash,
            ...opportunityBody,
          },
          evidence_catalog: [evidence],
          evidence_catalog_hash: canonicalHash([evidence]),
          fixture_class: "SYNTHETIC_NON_PRODUCTION" as const,
          snapshot_hash: "",
        };
        snapshot.snapshot_hash = canonicalHash(
          Object.fromEntries(Object.entries(snapshot).filter(([key]) => key !== "snapshot_hash")),
        );
        return JSON.stringify(snapshot);
      }
      if (name === "get_role_event_snapshot") {
        return JSON.stringify(buildFakeRoleEventSnapshot(agentId, asOf));
      }
      return JSON.stringify(buildFakeStandardSectorSnapshot(agentId, asOf));
    },
    {
      name,
      description: "Deterministic frozen Sector snapshot for fake structural smoke runs.",
      schema: z.object({}).strict(),
    },
  );
}

function buildFakeRoleEventSnapshot(agentId: SectorAgentId, asOf: string) {
  const coverageEvidenceId = `coverage:tushare.eco_cal:${agentId}:${asOf}`;
  const coverage = {
    coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT",
    event_presence_state: "NO_MATERIAL_EVENT_OBSERVED",
    coverage_completeness: "COMPLETE",
    coverage_as_of: `${asOf}T15:00:00+08:00`,
    query_complete: true,
    required_route_ids: ["tushare.eco_cal"],
    healthy_route_ids: ["tushare.eco_cal"],
    unhealthy_route_ids: [],
    coverage_evidence_ids: [coverageEvidenceId],
    material_event_revision_ids: [],
    coverage_contract_version: "role_event_coverage_v2",
  };
  const withoutId = {
    schema_version: "role_event_snapshot_v2",
    consumer_agent: agentId,
    as_of: `${asOf}T15:00:00+08:00`,
    contract_version: "role_event_coverage_v2",
    coverage,
    projections: [],
  };
  const withId = {
    role_event_snapshot_id: `role-event-snapshot:${canonicalHash(withoutId).slice("sha256:".length)}`,
    ...withoutId,
  };
  return { ...withId, role_event_snapshot_hash: canonicalHash(withId) };
}

function buildFakeStandardSectorSnapshot(agentId: SectorAgentId, asOf: string) {
  if (agentId === "relationship_mapper") {
    throw new Error("relationship_mapper must use its dedicated fake snapshot");
  }
  const directionIds = STANDARD_SECTOR_ROLE_CONTRACTS[agentId].directionIds;
  const eligibleSecurityUniverse = directionIds.map((directionId, index) => ({
    ts_code: `${String(600000 + index).padStart(6, "0")}.SH`,
    direction_id: directionId,
  }));
  const securityScoringRows = eligibleSecurityUniverse
    .map((security, index) => {
      const evidenceId = `sector:${agentId}:${security.direction_id}:${security.ts_code}:${asOf}`;
      const body = {
        ...security,
        availability_status: "AVAILABLE" as const,
        unavailability_reason: null,
        observation_date: asOf,
        released_at: `${asOf}T00:00:00Z`,
        vintage_at: `${asOf}T00:00:00Z`,
        pit_status: "PIT_VERIFIED" as const,
        adjusted_return_20d: 0.01 - index * 0.001,
        realized_volatility_20d: 0.2 + index * 0.001,
        median_amount_20d_cny: 1_000_000 - index,
        net_moneyflow_20d_cny: 10_000 - index,
        observation_count: 20,
        required_observation_count: 20,
        coverage_ratio: 1,
        evidence_ids: [evidenceId],
      };
      return { ...body, security_scoring_row_hash: canonicalHash(body) };
    })
    .sort((left, right) =>
      `${left.direction_id}\0${left.ts_code}`.localeCompare(
        `${right.direction_id}\0${right.ts_code}`,
      ),
    );
  const roleEvent = agentId === "biotech" ? null : buildFakeRoleEventSnapshot(agentId, asOf);
  const body = {
    schema_version: "sector_research_snapshot_v4",
    sector_agent_id: agentId,
    as_of_date: asOf,
    direction_ids: [...directionIds],
    eligible_security_universe: eligibleSecurityUniverse,
    eligible_count: eligibleSecurityUniverse.length,
    security_scoring_contract_version: SECURITY_SCORING_CONTRACT_VERSION,
    security_scoring_contract_hash: SECURITY_SCORING_CONTRACT_HASH,
    security_scoring_rows: securityScoringRows,
    security_scoring_rows_hash: canonicalHash(securityScoringRows),
    ...(roleEvent
      ? {
          role_event_snapshot_ref: {
            role_event_snapshot_id: roleEvent.role_event_snapshot_id,
            role_event_snapshot_hash: roleEvent.role_event_snapshot_hash,
          },
          event_coverage: roleEvent.coverage,
        }
      : {}),
  };
  return { ...body, snapshot_hash: canonicalHash(body) };
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
      : `A standard Sector stage is accepted only when runtime has frozen two distinct, uniquely ` +
        `qualified preferred and least-preferred directions. Directional insufficiency rejects the ` +
        `stage. A security leg may use NO_QUALIFIED_SECURITY only for a runtime-proven empty frozen ` +
        `shortlist; a non-empty shortlist requires picks. When a runtime evidence ` +
        `catalog is present, include claims, top-level claim_refs, and per-pick claim_refs using only ` +
        `its evidence_id and opaque permitted citation identifiers. `) +
    lang
  );
}

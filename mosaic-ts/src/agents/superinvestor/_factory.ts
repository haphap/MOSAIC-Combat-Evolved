/**
 * Generic factory for Layer-3 superinvestor agent nodes (Plan §11.2 sub-step 2D.2).
 *
 * Reads upstream:
 *   - ten independent accepted Macro transmissions with usage shares
 *   - state.layer2_outputs.* (nine Sector selections plus relationship graph)
 *
 * Writes:
 *   - state.layer3_outputs[<agentId>] (SuperinvestorOutput)
 *   - state.llm_calls (append)
 *
 * Same two-phase semantics as L1/L2 factories. Each superinvestor has a
 * different philosophy filter (encoded in their prompt + supplementary
 * tools), but the orchestration is identical — schema-agnostic.
 */

import {
  type BaseMessage,
  HumanMessage,
  SystemMessage,
  type ToolMessage,
} from "@langchain/core/messages";
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
  buildStructuredSmokeAcceptedOutputRef,
  canonicalAcceptedOutputHash,
} from "../accepted_output.js";
import { type AgentInitialToolCall, runAgentToolLoop } from "../helpers/agent_loop.js";
import { invokeStrictStructured } from "../helpers/agent_run_contract.js";
import {
  evidenceLineageEnvelopeFromGraph,
  renderCausalEvidenceResolutionSet,
} from "../helpers/causal_evidence_resolution.js";
import { extractTextContent } from "../helpers/content.js";
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
import { preModelOutcomeDisposition } from "../helpers/outcome_pre_model.js";
import {
  isPrivateKnotStageEnabled,
  type PrivateKnotAuditSummary,
  type PrivateKnotSnapshot,
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
import { renderAcceptedSectorInputs } from "../helpers/source_layer_usage.js";
import { validateStrictAgentOutput } from "../helpers/strict_agent_validation.js";
import { SUPERINVESTOR_ABSTENTION_PROVIDER_INSTRUCTION } from "../helpers/structured_provider_adapters.js";
import {
  hasAgentToolCapabilityApi,
  prepareAgentToolCapability,
  terminateAgentToolCapability,
} from "../helpers/tool_capability.js";
import { MACRO_AGENT_IDS } from "../macro/_contracts.js";
import { type LoaderLanguage, loadPrompt, loadPromptWithPrivateKnot } from "../prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type { SuperinvestorOutput } from "../types.js";
import { buildRuntimeSuperinvestorSchema } from "./_schemas.js";
import {
  acceptedSuperinvestorSelectionPayload,
  buildAcceptedSuperinvestorSelection,
  superinvestorMacroAttributionTargets,
} from "./accepted.js";

export type SuperinvestorAgentId = "druckenmiller" | "munger" | "burry" | "ackman";

export interface LayerThreeAgentSpec<TOutput extends SuperinvestorOutput> {
  agentId: SuperinvestorAgentId;
  schema: z.ZodType<TOutput>;
  fieldNames: ReadonlyArray<string>;
  requiredTools: ReadonlyArray<string>;
  render: (output: TOutput) => string;
  structuredOnlySentences?: ReadonlyArray<string>;
  buildExtractorSystem?: (lang: LoaderLanguage) => string;
}

export interface LayerThreeAgentDeps {
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

export type LayerThreeAgentNode = (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>;

export function buildLayerThreeAgentNode<TOutput extends SuperinvestorOutput>(
  spec: LayerThreeAgentSpec<TOutput>,
  deps: LayerThreeAgentDeps,
): LayerThreeAgentNode {
  return async function layerThreeAgentNode(state) {
    if (
      preModelOutcomeDisposition({
        state,
        agentId: spec.agentId,
        stage: "agent_run",
        authorityKind: "SUPERINVESTOR",
      }) === "SKIP"
    ) {
      return {};
    }
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const timeoutMs = resolveAgentTimeoutMs(deps.agentTimeoutSeconds);
    const onLog = deps.onLog ?? (() => undefined);
    const startedAt = Date.now();
    let canaryContext: AgentCanaryEventContext | null = null;
    let canaryKnobSnapshot: PrivateKnotSnapshot | null = null;
    let canaryToolStatuses: ReadonlyArray<ToolStatus> = [];
    onLog(
      formatAgentEvent("start", "L3", spec.agentId, [
        `timeout=${timeoutMs > 0 ? formatDurationMs(timeoutMs) : "off"}`,
      ]),
    );

    try {
      return await withAgentTimeout(
        async (signal) => {
          const cohort = state.active_cohort || "cohort_default";
          const language = pickPromptLanguage(deps.config);
          onLog(formatAgentEvent("phase", "L3", spec.agentId, ["prepare"]));

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
              trafficAssignmentKey: state.trace_id || state.as_of_date,
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
          const systemPrompt = `${baseSystemPrompt}\n\n${buildLayerThreeCurrentToolContract(spec.requiredTools)}`;
          if (knobSnapshot) {
            canaryContext = agentCanaryEventContext({
              release,
              state,
              agentInvocationId: knobSnapshot.agent_invocation_id,
              systemPrompt,
            });
          }

          const availableAcceptedSnapshotRefs = superinvestorAcceptedSnapshotRefs(state);
          const acceptedSnapshotRefs =
            availableAcceptedSnapshotRefs.length > 0 ? availableAcceptedSnapshotRefs : null;
          const opportunityAuthority = superinvestorOpportunityAuthority(state, spec.agentId);
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
                runtimeInputs: acceptedSnapshotRefs
                  ? { accepted_output_refs: acceptedSnapshotRefs }
                  : {
                      macro_input_gate: state.macro_input_gate,
                      layer1_outputs: state.layer1_outputs,
                      layer2_outputs: state.layer2_outputs,
                    },
                candidateScope: acceptedSnapshotRefs
                  ? { accepted_output_refs: acceptedSnapshotRefs }
                  : { accepted_sector_outputs: state.layer2_outputs },
              })
            : null;
          if (
            opportunityAuthority &&
            preparedCapability?.bundle.candidate_scope_hash !==
              opportunityAuthority.candidateScopeHash
          ) {
            throw new Error(
              `${spec.agentId}: runtime candidate scope changed after opportunity freeze`,
            );
          }
          const tools = preparedCapability
            ? await pickBridgeTools(deps.api, spec.requiredTools, {
                capability: preparedCapability.capability,
              })
            : spec.requiredTools.map((name) =>
                buildFakeSuperinvestorSnapshotTool(name, spec.agentId, state.as_of_date),
              );

          const userContext = buildLayerThreeUserContext(
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
              ...(runtimeEvidence ? { agentInvocationId: runtimeEvidence.agentInvocationId } : {}),
              initialToolCalls: buildLayerThreeInitialToolCalls(state, spec.agentId),
              maxLoops: 3,
              replayFullToolMaxChars: 80_000,
              onLog: (msg) => onLog(formatAgentEvent("phase", "L3", spec.agentId, [msg])),
              signal,
            });
          } finally {
            if (preparedCapability) {
              await terminateAgentToolCapability(
                deps.api,
                preparedCapability,
                "superinvestor_candidate_research_completed",
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

          onLog(
            formatAgentEvent("phase", "L3", spec.agentId, [
              `extract chars=${loopResult.analysisText.length}`,
            ]),
          );
          const extractorSystem = spec.buildExtractorSystem
            ? spec.buildExtractorSystem(language)
            : defaultExtractorSystem(spec, language);
          const allowedTsCodes = frozenSuperinvestorCandidateCodes(
            loopResult.messages,
            opportunityAuthority,
          );
          const extractionSchema = buildRuntimeSuperinvestorSchema(
            spec.agentId,
            allowedTsCodes,
          ) as z.ZodType<TOutput>;
          const extractor = await invokeStrictStructured<TOutput>({
            llm: structuredHandle.llm,
            schema: extractionSchema,
            messages: [
              new SystemMessage(extractorSystem),
              new HumanMessage(
                [
                  loopResult.analysisText || "(no analysis produced)",
                  allowedTsCodes.length === 0
                    ? "Frozen candidate universe is empty. The only legal disposition is NO_QUALIFIED_CANDIDATES with picks=[]."
                    : `Frozen allowed ts_code values (exact closed set): ${JSON.stringify(allowedTsCodes)}`,
                  runtimeEvidence?.visibleCatalog,
                ]
                  .filter((part): part is string => Boolean(part))
                  .join("\n\n"),
              ),
            ],
            agent: spec.agentId,
            stage: "agent_run",
            runId: state.trace_id || state.as_of_date || "current_run",
            evidenceSnapshot: runtimeEvidence,
            validate: (output) =>
              validateStrictAgentOutput({
                output,
                schema: extractionSchema,
                agent: spec.agentId,
                stage: "agent_run",
                cohort: state.active_cohort,
                runtimeEvidence,
                knobSnapshot,
                toolStatuses: loopResult.toolStatuses,
              }),
            isAcceptedEmpty: (output) => output.selection_status === "NO_QUALIFIED_CANDIDATES",
            signal,
          });

          const output = extractor.output;
          let acceptedOutputRefs: DailyCycleStateUpdate["accepted_output_refs"] | undefined;
          if (state.darwinian_runtime_binding) {
            const gate = state.macro_input_gate;
            const claimGraph = output.verified_claim_graph;
            const behavior = state.darwinian_runtime_binding.agent_behavior_bindings[spec.agentId];
            if (!gate || !claimGraph || !behavior || !deps.acceptedOutputStore) {
              throw new Error(
                `${spec.agentId}: production accepted Superinvestor context is unavailable`,
              );
            }
            const selection = acceptedSuperinvestorSelectionPayload(output);
            const acceptedAttributions = resolveMacroInputAttributions({
              submissions: output.macro_input_attributions,
              acceptedMacroOutputs: acceptedMacroOutputs(state, deps.acceptedOutputStore),
              macroInputGate: gate,
              acceptedSubmissionBody: canonicalAcceptedSubmissionBody(selection),
              targets: superinvestorMacroAttributionTargets(output),
            });
            const accepted = buildAcceptedSuperinvestorSelection({
              output,
              behavior,
              acceptedMacroInputAttributions: acceptedAttributions,
            });
            const lineage = evidenceLineageEnvelopeFromGraph(accepted, claimGraph);
            const record = buildAcceptedAgentOutputRecord({
              kind: "SUPERINVESTOR_SELECTION",
              agentId: spec.agentId,
              payload: accepted,
              evidenceBundleIds: lineage.evidence_bundle_ids,
              causalDedupeKeys: lineage.causal_dedupe_keys,
              claimGraph,
              sourceAgentOutputHash: requiredAcceptedAuditOutputHash(
                extractor.audit.output_hash,
                spec.agentId,
              ),
              context: acceptedOutputBuildContextFromState({
                state,
                agentId: spec.agentId,
                sourceAgentRunId: extractor.audit.run_id,
                acceptedOutputKind: "SUPERINVESTOR_SELECTION",
              }),
            });
            const ref = deps.acceptedOutputStore.put(record, claimGraph);
            acceptedOutputRefs = {
              [acceptedOutputRefKey("SUPERINVESTOR_SELECTION", spec.agentId)]: ref,
            };
          } else {
            const ref = buildStructuredSmokeAcceptedOutputRef({
              kind: "SUPERINVESTOR_SELECTION",
              agentId: spec.agentId,
              payload: output,
              state,
            });
            if (ref) {
              acceptedOutputRefs = {
                [acceptedOutputRefKey("SUPERINVESTOR_SELECTION", spec.agentId)]: ref,
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
            formatAgentEvent("done", "L3", spec.agentId, [
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
              : { layer3_outputs: { [spec.agentId]: output } }),
            ...(acceptedOutputRefs ? { accepted_output_refs: acceptedOutputRefs } : {}),
            llm_calls: [llmCall],
          };
        },
        timeoutMs,
        `L3 ${spec.agentId}`,
      );
    } catch (err) {
      onLog(
        formatAgentEvent("error", "L3", spec.agentId, [
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
    }
  };
}

function requiredAcceptedAuditOutputHash(value: string | null, agentId: string): string {
  if (!value || !/^sha256:[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${agentId}: accepted output lacks an Agent-run output hash`);
  }
  return value;
}

export function superinvestorAcceptedSnapshotRefs(state: DailyCycleStateType) {
  return Object.entries(state.accepted_output_refs)
    .filter(
      ([key]) =>
        key.startsWith("MACRO_TRANSMISSION:") ||
        key.startsWith("STANDARD_SECTOR_SELECTION:") ||
        key === "RELATIONSHIP_GRAPH:relationship_mapper",
    )
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, ref]) => ({ key, ...ref }));
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

/** Build user-context block that surfaces L1 regime + L2 sector picks. */
export function buildLayerThreeUserContext(
  state: DailyCycleStateType,
  agentId: SuperinvestorAgentId,
  acceptedOutputStore?: AcceptedAgentOutputStore,
): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  const mode = state.mode || "live";
  const cohort = state.active_cohort || "cohort_default";
  const macroBlock = renderAcceptedMacroInputs(state, acceptedOutputStore);

  const sectorBlocks = renderAcceptedSectorInputs(state, acceptedOutputStore);
  const causalResolutionBlock = renderCausalEvidenceResolutionSet({
    state,
    consumerAgentId: agentId,
    sourceLayers: ["MACRO", "SECTOR"],
    ...(acceptedOutputStore ? { acceptedOutputStore } : {}),
  });

  return (
    `Cycle context for ${agentId} (Layer 3 superinvestor):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${mode}\n` +
    `* cohort:     ${cohort}\n\n` +
    `${macroBlock}\n` +
    `${sectorBlocks}\n` +
    `${causalResolutionBlock}\n` +
    `Use only the frozen candidate snapshot supplied for this role. ` +
    `Do not expand the candidate set or query report-derived research. ` +
    `Apply the role philosophy to the accepted candidates and evidence already present in that snapshot.`
  );
}

export function buildLayerThreeInitialToolCalls(
  _state: DailyCycleStateType,
  _agentId: string,
): AgentInitialToolCall[] {
  return [{ name: "get_superinvestor_candidate_snapshot", args: {} }];
}

export interface SuperinvestorOpportunityAuthority {
  candidateScopeHash: string;
  candidateUniverseHash: string;
  sourceSnapshotHash: string;
}

function superinvestorOpportunityAuthority(
  state: DailyCycleStateType,
  agentId: SuperinvestorAgentId,
): SuperinvestorOpportunityAuthority | null {
  if (!state.darwinian_runtime_binding) return null;
  const schedule = state.outcome_schedule_plan;
  if (!schedule) throw new Error(`${agentId}: outcome schedule is unavailable`);
  const slots = schedule.slots.filter((slot) => slot.agent_id === agentId);
  if (slots.length !== 1) throw new Error(`${agentId}: outcome schedule slot is ambiguous`);
  const slot = slots[0];
  if (!slot) throw new Error(`${agentId}: outcome schedule slot is unavailable`);
  if (slot.run_slot_kind === "DOWNSTREAM_ONLY") return null;
  const binding = state.outcome_opportunity_bindings[agentId];
  if (
    !binding ||
    binding.scheduled_sample_id !== slot.scheduled_sample_id ||
    !binding.runtime_candidate_scope_hash ||
    !binding.runtime_candidate_universe_hash ||
    !binding.runtime_source_snapshot_hash
  ) {
    throw new Error(`${agentId}: runtime opportunity authority is unavailable`);
  }
  return {
    candidateScopeHash: binding.runtime_candidate_scope_hash,
    candidateUniverseHash: binding.runtime_candidate_universe_hash,
    sourceSnapshotHash: binding.runtime_source_snapshot_hash,
  };
}

export function frozenSuperinvestorCandidateCodes(
  messages: ReadonlyArray<BaseMessage>,
  expectedAuthority: SuperinvestorOpportunityAuthority | null = null,
): string[] {
  const snapshotMessage = messages.find(
    (message) =>
      message.getType() === "tool" && (message as ToolMessage).tool_call_id === "initial_tool_1",
  ) as ToolMessage | undefined;
  if (!snapshotMessage) {
    throw new Error("superinvestor frozen candidate snapshot result is unavailable");
  }
  let payload: Record<string, unknown>;
  try {
    const parsed = JSON.parse(extractTextContent(snapshotMessage.content as unknown));
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("snapshot must be an object");
    }
    payload = parsed as Record<string, unknown>;
  } catch (cause) {
    throw new Error(
      `superinvestor frozen candidate snapshot is invalid JSON: ${cause instanceof Error ? cause.message : String(cause)}`,
    );
  }
  const universe = payload.candidate_universe ?? payload.candidates;
  if (!Array.isArray(universe)) {
    throw new Error("superinvestor frozen candidate snapshot requires candidate_universe");
  }
  if (expectedAuthority) {
    if (
      payload.candidate_scope_hash !== expectedAuthority.candidateScopeHash ||
      payload.candidate_universe_hash !== expectedAuthority.candidateUniverseHash ||
      payload.snapshot_hash !== expectedAuthority.sourceSnapshotHash
    ) {
      throw new Error("superinvestor candidate snapshot changed after opportunity freeze");
    }
    const candidateStatus = payload.candidate_status;
    if (candidateStatus !== "AVAILABLE" && candidateStatus !== "EMPTY_CONFIRMED") {
      throw new Error("superinvestor candidate snapshot has invalid candidate_status");
    }
    const computedUniverseHash = canonicalAcceptedOutputHash({
      candidate_status: candidateStatus,
      candidate_universe: universe,
    });
    if (computedUniverseHash !== expectedAuthority.candidateUniverseHash) {
      throw new Error("superinvestor candidate universe content hash mismatch");
    }
    const candidateScope = payload.candidate_scope;
    if (
      candidateScope === null ||
      typeof candidateScope !== "object" ||
      Array.isArray(candidateScope) ||
      canonicalAcceptedOutputHash(candidateScope) !== expectedAuthority.candidateScopeHash ||
      (candidateScope as Record<string, unknown>).candidate_universe_hash !==
        expectedAuthority.candidateUniverseHash
    ) {
      throw new Error("superinvestor candidate scope content hash mismatch");
    }
  }
  const constraints =
    payload.constraints !== null &&
    typeof payload.constraints === "object" &&
    !Array.isArray(payload.constraints)
      ? (payload.constraints as Record<string, unknown>)
      : {};
  const cashOnly = constraints.cash_only === true || constraints.allow_new_positions === false;
  if (cashOnly && universe.length > 0) {
    throw new Error("superinvestor candidate snapshot conflicts with its cash-only constraints");
  }
  const codes = universe.map((candidate, index) => {
    const record =
      candidate !== null && typeof candidate === "object" && !Array.isArray(candidate)
        ? (candidate as Record<string, unknown>)
        : null;
    const nestedSecurity =
      record?.security !== null &&
      typeof record?.security === "object" &&
      !Array.isArray(record.security)
        ? (record.security as Record<string, unknown>)
        : null;
    const code =
      typeof candidate === "string"
        ? candidate
        : typeof record?.ts_code === "string"
          ? record.ts_code
          : typeof record?.ticker === "string"
            ? record.ticker
            : typeof nestedSecurity?.ts_code === "string"
              ? nestedSecurity.ts_code
              : null;
    if (!code || !/^\d{6}\.(?:SH|SZ|BJ)$/.test(code)) {
      throw new Error(`superinvestor candidate_universe[${index}] has no valid A-share ts_code`);
    }
    return code;
  });
  if (new Set(codes).size !== codes.length) {
    throw new Error("superinvestor candidate_universe contains duplicate ts_code values");
  }
  return codes.sort();
}

function buildFakeSuperinvestorSnapshotTool(
  name: string,
  agentId: SuperinvestorAgentId,
  asOf: string,
): StructuredToolInterface {
  return tool(
    async () =>
      JSON.stringify({
        schema_version: "fake_superinvestor_candidate_snapshot_v1",
        agent_id: agentId,
        as_of: asOf,
        candidate_status: "EMPTY_CONFIRMED",
        candidates: [],
        evidence_id: `fake-${agentId}-snapshot`,
      }),
    {
      name,
      description: "Deterministic frozen candidate snapshot for fake structural smoke runs.",
      schema: z.object({}).strict(),
    },
  );
}

function buildLayerThreeCurrentToolContract(requiredTools: ReadonlyArray<string>): string {
  return (
    `## Current tool contract\n` +
    `Only call these registered tools: ${requiredTools.join(", ")}.\n` +
    `Do not call older prompt names that are not listed above.\n` +
    `The role snapshot is frozen before invocation; do not query outside its candidate or evidence scope.`
  );
}

function defaultExtractorSystem<TOutput extends SuperinvestorOutput>(
  spec: LayerThreeAgentSpec<TOutput>,
  language: LoaderLanguage,
): string {
  const lang =
    language === "en"
      ? "Reply in English."
      : "Reply in Chinese. Numbers stay numeric; do not wrap them in 中文括号.";
  return (
    `You are a structured-output extractor for the ${spec.agentId} superinvestor agent. ` +
    `The user message contains a free-form philosophy-driven analysis. Populate every field ` +
    `in the runtime-supplied JSON Schema. For SELECTED, submit 1-10 ` +
    `concrete A-share tickers (e.g. '600519.SH') sourced from the Layer-2 candidate ` +
    `universe in the analysis text — never invent codes. Each pick needs a stable local id, ` +
    `LONG/AVOID action, thesis, conviction in (0,1], and claim refs; total conviction must ` +
    `not exceed 1. holding_period is one of WEEKS, MONTHS, YEARS. ` +
    `If no pick is defensible, use NO_QUALIFIED_CANDIDATES with an evidence-backed claim. ` +
    `When a runtime evidence catalog is present, include claims, top-level claim_refs, ` +
    `and per-pick claim_refs using only its evidence_id and opaque permitted citation identifiers. ` +
    `Submit exactly ten SUBMISSION_SUMMARY macro_input_attributions, one for each named Macro ` +
    `Agent; use target_local_ref=$SUBMISSION and add SECURITY_PICK rows only for real pick ids. ` +
    `${SUPERINVESTOR_ABSTENTION_PROVIDER_INSTRUCTION} ` +
    `${MACRO_ATTRIBUTION_PROVIDER_INSTRUCTION} ` +
    lang
  );
}

export function fallbackSuperinvestorOutput(
  agent: SuperinvestorAgentId,
  text: string,
): SuperinvestorOutput {
  const statement = text.trim().slice(0, 320) || "No qualified candidate was established.";
  const claimId = `fallback-${agent}-claim`;
  return {
    agent,
    selection_status: "NO_QUALIFIED_CANDIDATES",
    confidence: 1,
    holding_period: "MONTHS",
    picks: [],
    key_drivers: [
      {
        driver_local_id: `fallback-${agent}-driver`,
        summary: statement,
        claim_refs: [claimId],
      },
    ],
    risks: [
      {
        risk_local_id: `fallback-${agent}-risk`,
        summary: "The candidate evidence was insufficient for an accountable activation.",
        claim_refs: [claimId],
      },
    ],
    claims: [
      {
        claim_id: claimId,
        claim_kind: "RISK_FLAG",
        statement,
        structured_conclusion: { selection_status: "NO_QUALIFIED_CANDIDATES" },
        evidence_ids: [`fallback-evidence:${agent}`],
        research_rule_refs: [],
      },
    ],
    claim_refs: [claimId],
    macro_input_attributions: MACRO_AGENT_IDS.map((agentId) => ({
      agent_id: agentId,
      target_type: "SUBMISSION_SUMMARY",
      target_local_ref: "$SUBMISSION",
      claim_refs_used: [],
      effect: "NOT_MATERIAL",
    })),
  };
}

/**
 * Generic factory for Layer-1 macro agent nodes (Plan §11.2 sub-step 2C-1).
 *
 * Wraps the two-phase execution pattern proven by ``central_bank`` in 2B:
 *
 *   1. **Tool-bound free-form analysis**
 *      - Load the bilingual prompt for the active cohort from disk
 *      - Resolve the agent's required tools via ``pickBridgeTools`` (with
 *        backtest context attached when ``state.mode === "backtest"``)
 *      - Run ``runAgentToolLoop`` until the model emits a tool-call-free
 *        response or maxLoops is reached
 *
 *   2. **Strict structured extraction**
 *      - Validate every answer against the Zod schema, frozen evidence,
 *        research knobs, and domain semantics, with at most three repairs.
 *      - Reject the stage when the repair budget is exhausted.
 *
 * Each Layer-1 macro agent file declares a ``LayerOneAgentSpec<TOutput>``
 * and a ``build<Agent>Node = (deps) => buildLayerOneAgentNode(spec, deps)``.
 *
 * Sector, superinvestor, and decision agents use their own factories. They
 * consume the ten accepted Macro records through the runtime input gate and
 * model-visible attribution DTOs; no Macro stance or consensus object exists.
 */

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
import { invokeStrictStructured } from "../helpers/agent_run_contract.js";
import { evidenceLineageEnvelopeFromGraph } from "../helpers/causal_evidence_resolution.js";
import {
  buildAgentInvocationId,
  buildRuntimeEvidenceSnapshot,
  type RuntimeEvidenceSnapshot,
} from "../helpers/evidence_runtime.js";
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
import { validateStrictAgentOutput } from "../helpers/strict_agent_validation.js";
import {
  prepareAgentToolCapability,
  terminateAgentToolCapability,
} from "../helpers/tool_capability.js";
import { type LoaderLanguage, loadPrompt, loadPromptWithKnobs } from "../prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type { AcceptedMacroTransmission, MacroAgentId, MacroAgentSubmission } from "../types.js";
import {
  composeAcceptedMacroTransmission,
  MACRO_ROLE_CONTRACTS,
  type MacroDataQualityInput,
  renderMacroRuntimeContract,
} from "./_contracts.js";
import {
  macroSnapshotEchoView,
  roleSnapshotFromToolLoop,
  validateMacroSnapshotEchoes,
} from "./_semantic_validation.js";

/**
 * Per-agent configuration for the Layer-1 factory. Each macro agent file
 * exports a ``LayerOneAgentSpec<TOutput>`` with the bits that vary across
 * the 10 agents.
 */
export interface LayerOneAgentSpec {
  /** Canonical agent ID, e.g. "central_bank". Must match the prompt filename. */
  agentId: MacroAgentId;
  /** Zod schema for the structured output. */
  schema: z.ZodType<MacroAgentSubmission>;
  /** Schema field names; surfaced to the structured-output extractor prompt. */
  fieldNames: ReadonlyArray<string>;
  /** Bridge tools this agent will call during phase 1. */
  requiredTools: readonly [string];
  /** Render structured output as readable prose for state inspection / logs. */
  render: (output: import("../types.js").AcceptedMacroTransmission) => string;
  /**
   * Optional structured-only sentences in the phase-1 system prompt. If
   * any prompt lines only make sense in structured-output mode, list them
   * here so they're stripped during free-text fallback. Default: empty.
   */
  structuredOnlySentences?: ReadonlyArray<string>;
  /**
   * Optional override for the structured-extractor system prompt. Default
   * is a generic "extract from the analysis below" template.
   */
  buildExtractorSystem?: (lang: LoaderLanguage) => string;
  /** Optional per-agent loop cap when broad candidate scans would exhaust context. */
  maxLoops?: number;
}

export interface LayerOneAgentDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  /** Optional structured-output LLM (defaults to ``llmHandle``). */
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** Override the prompt-root directory (tests inject a tmpdir). Defaults to
   *  ``findPromptsRoot()`` resolution. */
  promptsRoot?: string;
  /** Shared run-scoped accepted-record store. Required for production runs. */
  acceptedOutputStore?: AcceptedAgentOutputStore;
}

export type LayerOneAgentNode = (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>;

// ---------------------------------------------------------------------------
// Public factory
// ---------------------------------------------------------------------------

export function buildLayerOneAgentNode(
  spec: LayerOneAgentSpec,
  deps: LayerOneAgentDeps,
): LayerOneAgentNode {
  return async function layerOneAgentNode(state) {
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const timeoutMs = resolveAgentTimeoutMs(deps.agentTimeoutSeconds);
    const onLog = deps.onLog ?? (() => undefined);
    const startedAt = Date.now();
    let canaryContext: AgentCanaryEventContext | null = null;
    let canaryKnobSnapshot: ResearchKnobsSnapshot | null = null;
    let canaryToolStatuses: ReadonlyArray<ToolStatus> = [];
    onLog(
      formatAgentEvent("start", "L1", spec.agentId, [
        `timeout=${timeoutMs > 0 ? formatDurationMs(timeoutMs) : "off"}`,
      ]),
    );

    try {
      return await withAgentTimeout(
        async (signal) => {
          const cohort = state.active_cohort || "cohort_default";
          const language = pickPromptLanguage(deps.config);
          onLog(formatAgentEvent("phase", "L1", spec.agentId, ["prepare"]));

          // Phase 0: load prompt for this cohort. Research-knobs enabled
          // agents fail closed on zh/en parity and share one immutable snapshot
          // between prompt injection and runtime cap enforcement.
          let knobSnapshot: ResearchKnobsSnapshot | null = null;
          let systemPrompt: string;
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
              onReleaseAssigned: async (release) => {
                canaryContext = await beginAgentPromptCanaryInvocation({
                  release,
                  state,
                  agent: spec.agentId,
                  stage: "agent_run",
                  cohort,
                });
              },
              ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
            });
            knobSnapshot = loaded.snapshot;
            systemPrompt = loaded.prompt;
            canaryKnobSnapshot = loaded.snapshot;
            canaryContext = agentCanaryEventContext({
              release: loaded.release,
              state,
              agentInvocationId:
                canaryContext?.agentInvocationId ??
                buildAgentInvocationId({
                  runId: state.trace_id || state.as_of_date || "current_run",
                  agent: spec.agentId,
                  stage: "agent_run",
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
          }
          systemPrompt = `${systemPrompt}\n\n${renderMacroRuntimeContract(
            spec.agentId,
            language === "en" ? "en" : "zh",
          )}`;

          // Phase 0b: pull the agent's tools from the bridge (with backtest
          // context attached so date-bound tools clamp end_date correctly).
          const preparedCapability =
            deps.llmHandle.provider === "fake"
              ? null
              : await prepareAgentToolCapability({
                  api: deps.api,
                  state,
                  agentId: spec.agentId,
                  stage: spec.agentId,
                });
          const tools = preparedCapability
            ? await pickBridgeTools(deps.api, spec.requiredTools, {
                capability: preparedCapability.capability,
              })
            : [buildFakeRoleSnapshotTool(spec.agentId, spec.requiredTools[0], state.as_of_date)];

          // Phase 1: tool-bound free-form analysis loop.
          const userContext = buildUserContext(state, spec.agentId);
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
          let loopResult: Awaited<ReturnType<typeof runAgentToolLoop>>;
          try {
            loopResult = await runAgentToolLoop({
              llm: deps.llmHandle.llm,
              tools: tools as StructuredToolInterface[],
              systemMessage: systemPrompt,
              initialMessages: [new HumanMessage(evidenceUserContext)],
              initialToolCalls: [{ name: spec.requiredTools[0], args: {} }],
              allowModelToolCalls: false,
              ...(runtimeEvidence ? { agentInvocationId: runtimeEvidence.agentInvocationId } : {}),
              ...(spec.maxLoops !== undefined ? { maxLoops: spec.maxLoops } : {}),
              onLog: (msg) => onLog(formatAgentEvent("phase", "L1", spec.agentId, [msg])),
              signal,
            });
          } finally {
            if (preparedCapability) {
              await terminateAgentToolCapability(
                deps.api,
                preparedCapability,
                "macro_direction_research_completed",
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

          // Phase 2: structured extraction from the analysis text.
          onLog(
            formatAgentEvent("phase", "L1", spec.agentId, [
              `extract chars=${loopResult.analysisText.length}`,
            ]),
          );
          const extractorSystem = spec.buildExtractorSystem
            ? spec.buildExtractorSystem(language)
            : defaultExtractorSystem(spec, language);
          const roleSnapshot = roleSnapshotFromToolLoop({
            agent: spec.agentId,
            asOfDate: state.as_of_date,
            messages: loopResult.messages,
            requiredTool: spec.requiredTools[0],
            toolStatuses: loopResult.toolStatuses,
          });
          const extractor = await invokeStrictStructured<MacroAgentSubmission>({
            llm: structuredHandle.llm,
            schema: spec.schema,
            messages: [
              new SystemMessage(extractorSystem),
              new HumanMessage(
                [
                  loopResult.analysisText || "(no analysis produced)",
                  roleSnapshot.snapshot
                    ? `FROZEN_ROLE_SNAPSHOT_ECHO_CATALOG (numeric source of truth; snapshot_echo_id is only a structured_conclusion locator and is never a claim evidence_id):\n${JSON.stringify(
                        macroSnapshotEchoView(roleSnapshot.snapshot),
                      )}`
                    : undefined,
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
            validate: (output) => {
              const base = validateStrictAgentOutput({
                output,
                schema: spec.schema,
                agent: spec.agentId,
                stage: "agent_run",
                runtimeEvidence,
                knobSnapshot,
                toolStatuses: loopResult.toolStatuses,
                allowRiskFlagOnly: submissionIsNeutral(output),
              });
              return {
                output: base.output,
                issues: [
                  ...base.issues,
                  ...roleSnapshot.issues,
                  ...(roleSnapshot.snapshot
                    ? validateMacroSnapshotEchoes(output, roleSnapshot.snapshot)
                    : []),
                ],
              };
            },
            signal,
          });

          // Phase 3: assemble state update.
          const submission = extractor.output;
          if (!roleSnapshot.snapshot) {
            throw new Error(`${spec.agentId}: role snapshot unavailable after validation`);
          }
          const authoredSubmission = authoredMacroSubmission(submission);
          const dataQuality = macroDataQualityFromSnapshot(spec.agentId, roleSnapshot.snapshot);
          const acceptedTransmission = composeAcceptedMacroTransmission(
            spec.agentId,
            authoredSubmission,
            dataQuality,
            state.darwinian_runtime_binding?.agent_behavior_bindings[spec.agentId],
            state.component_weight_snapshot?.resolutions.find(
              (resolution) => resolution.agent_id === spec.agentId,
            ),
          );
          const output: AcceptedMacroTransmission = {
            ...acceptedTransmission,
            ...(submission.verified_claim_graph
              ? { verified_claim_graph: submission.verified_claim_graph }
              : {}),
            ...(submission.verified_claim_audit
              ? { verified_claim_audit: submission.verified_claim_audit }
              : {}),
          };
          let acceptedOutputRefs: DailyCycleStateUpdate["accepted_output_refs"] | undefined;
          if (state.darwinian_runtime_binding) {
            if (!deps.acceptedOutputStore) {
              throw new Error(`${spec.agentId}: production accepted-output store is unavailable`);
            }
            if (!runtimeEvidence) {
              throw new Error(`${spec.agentId}: production evidence lineage is unavailable`);
            }
            const claimGraph = submission.verified_claim_graph;
            if (!claimGraph) {
              throw new Error(`${spec.agentId}: production claim lineage is unavailable`);
            }
            const lineage = evidenceLineageEnvelopeFromGraph(acceptedTransmission, claimGraph);
            const record = buildAcceptedAgentOutputRecord({
              kind: "MACRO_TRANSMISSION",
              agentId: spec.agentId,
              payload: acceptedTransmission,
              evidenceBundleIds: lineage.evidence_bundle_ids,
              causalDedupeKeys: lineage.causal_dedupe_keys,
              context: acceptedOutputBuildContextFromState({
                state,
                agentId: spec.agentId,
                sourceAgentRunId: extractor.audit.run_id,
              }),
            });
            const ref = deps.acceptedOutputStore.put(record, claimGraph);
            acceptedOutputRefs = {
              [acceptedOutputRefKey("MACRO_TRANSMISSION", spec.agentId)]: ref,
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
              (submission as MacroAgentSubmission & { verified_knob_audit?: ResearchKnobCapAudit })
                .verified_knob_audit ?? null,
            toolStatuses: loopResult.toolStatuses,
            output,
            validatorIds: [
              `${spec.agentId}.structured_output.v1`,
              "evidence_claim_graph_v1",
              "macro_snapshot_semantics_v1",
              "research_knobs_runtime_v1",
            ],
          });
          if (canaryEvent) {
            llmCall.prompt_canary_event = canaryEvent;
            await persistPromptReleaseCanaryEvents([canaryEvent]);
          }

          onLog(
            formatAgentEvent("done", "L1", spec.agentId, [
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
              : { layer1_outputs: { [spec.agentId]: output } }),
            ...(acceptedOutputRefs ? { accepted_output_refs: acceptedOutputRefs } : {}),
            ...(authoredSubmission.mode === "COMPONENTS" && dataQuality.mode === "COMPONENTS"
              ? {
                  component_calibration_inputs: {
                    [spec.agentId]: {
                      agent_id: spec.agentId,
                      component_weight_contract_version:
                        acceptedTransmission.component_weight_contract_version as string,
                      components: authoredSubmission.components.map((component) => ({
                        ...component,
                        deterministic_data_quality: dataQuality.dataQualityByComponent[
                          component.component
                        ] as number,
                      })),
                    },
                  },
                }
              : {}),
            llm_calls: [llmCall],
          };
        },
        timeoutMs,
        `L1 ${spec.agentId}`,
      );
    } catch (err) {
      onLog(
        formatAgentEvent("error", "L1", spec.agentId, [
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

/**
 * Deterministic private-data substitute used only by ``--fake-llm`` structural
 * smoke runs. Production and real-model runs always execute the bridge tool and
 * remain fail-closed when the role snapshot is unavailable.
 */
function buildFakeRoleSnapshotTool(
  agent: MacroAgentId,
  name: string,
  asOfDate: string,
): StructuredToolInterface {
  return tool(
    async () =>
      JSON.stringify(
        agent === "market_breadth"
          ? {
              schema_version: "market_breadth_snapshot_v1",
              as_of_date: asOfDate,
              advance_decline_balance: 0,
              above_ma20_pct: 0.5,
              above_ma60_pct: 0.5,
              new_high_low_20d_balance: 0,
              turnover_expansion_pct: 0.5,
              return_dispersion: 0,
              top_decile_turnover_share: 0.1,
              eligible_count: 1,
              observed_count: 1,
              coverage_ratio: 1,
              breadth_composite: 0,
              breadth_composite_change_20d: 0,
              breadth_composite_q40_252d: 0,
              breadth_composite_q60_252d: 0,
              concentration_q20_252d: 0.1,
              concentration_q80_252d: 0.1,
              breadth_state: "MIXED",
              concentration_state: "NORMAL",
              direct_data_quality: 1,
              methodology: { fixture: "fake_llm_structural_smoke" },
              evidence_id: "fake-market-breadth-snapshot",
              snapshot_hash: "0".repeat(64),
            }
          : agent === "geopolitical"
            ? {
                schema_version: "geopolitical_role_snapshot_v2",
                role: agent,
                as_of_date: asOfDate,
                event_registry_version: "geopolitical_verified_event_registry_v2",
                source_registry_version: "geopolitical_source_registry_v2",
                coverage_scope_version: "geopolitical_watchlist_scope_v2",
                coverage_scope_hash: `sha256:${"0".repeat(64)}`,
                registration_statuses: [],
                coverage_by_event_type: [],
                events: [],
                empty_state: "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT",
                readiness: "READY",
                direct_data_quality: 1,
                evidence_id: "fake-geopolitical-role-snapshot",
                snapshot_hash: `sha256:${"0".repeat(64)}`,
              }
            : {
                schema_version: "macro_role_snapshot_v2",
                role: agent,
                as_of_date: asOfDate,
                observations: [],
                events: [],
                source_policy: {
                  primary: "tushare",
                  us_revision_source: "ALFRED/official fixed map",
                  implicit_fallback: false,
                },
                ...(MACRO_ROLE_CONTRACTS[agent].mode === "DIRECT"
                  ? { direct_data_quality: 1 }
                  : {
                      component_data_quality: Object.fromEntries(
                        Object.keys(MACRO_ROLE_CONTRACTS[agent].components).map((component) => [
                          component,
                          1,
                        ]),
                      ),
                    }),
                snapshot_hash: "0".repeat(64),
              },
      ),
    {
      name,
      description: "Deterministic role snapshot for --fake-llm structural smoke runs.",
      schema: z.object({}).strict(),
    },
  );
}

// ---------------------------------------------------------------------------
// Shared helpers (exported for tests + 2D layer factories)
// ---------------------------------------------------------------------------

export function pickPromptLanguage(config: MosaicConfig): LoaderLanguage {
  const raw = (config.output_language ?? "Chinese").toString().toLowerCase().trim();
  if (raw === "english" || raw === "en") return "en";
  if (raw === "bilingual") return "Bilingual";
  return "zh";
}

export function buildUserContext(state: DailyCycleStateType, agentId: string): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  const mode = state.mode || "live";
  const cohort = state.active_cohort || "cohort_default";
  return (
    `Cycle context for ${agentId}:\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${mode}\n` +
    `* cohort:     ${cohort}\n\n` +
    `The runtime will collect the single role-scoped snapshot at exactly this as_of_date. ` +
    `Analyze only that frozen result and the visible evidence catalog; do not request a ` +
    `different date or any additional tool.`
  );
}

function defaultExtractorSystem(spec: LayerOneAgentSpec, language: LoaderLanguage): string {
  const lang =
    language === "en"
      ? "Reply in English."
      : "Reply in Chinese. Numbers stay numeric; do not wrap them in 中文括号.";
  return (
    `You are a structured-output extractor for the ${spec.agentId} agent. ` +
    `The user message contains a free-form analysis written by a previous LLM call, the ` +
    `frozen role snapshot JSON, and the runtime evidence catalog. Read them carefully and ` +
    `populate every field in the runtime-supplied JSON Schema. Only emit values supported ` +
    `by those inputs; never invent numbers. ` +
    `If a field cannot be supported by the text, use the most conservative valid value ` +
    `(prefer NEUTRAL signals, 0 strength, and confidence ≤ 0.4), while still producing a complete analysis. Give every claim a unique ` +
    `claim_id. Top-level claim_refs must contain only claim_id values present in claims; ` +
    `evidence_id values belong only in evidence_ids and allowed rule ids belong only in ` +
    `research_rule_refs inside each claim. Every claim must cite at least one exact ` +
    `evidence_id from the visible catalog. Every INTERPRETATION claim must also cite at least ` +
    `one exact allowed research rule id; otherwise change it to FACT, EVENT, or RISK_FLAG as ` +
    `supported by the analysis. Never leave either required reference array empty. The ` +
    `claim structured_conclusion must not repeat signal fields such as direction, strength, ` +
    `persistence_horizon, evaluation_horizon_trading_days, confidence, or channels. Numeric ` +
    `snapshot values belong in the claim statement with their evidence citation; do not put any ` +
    `numeric value in claim structured_conclusion. Snapshot echo locators must never appear in ` +
    `claims.evidence_ids; that array accepts only ids from the runtime-owned evidence catalog. ` +
    `Never emit data_quality, direct_data_quality, component_data_quality, or any numeric ` +
    `data-quality assessment inside claim structured_conclusion; data quality is computed by ` +
    `the runtime and is not model-authored. ` +
    `Do not invent or restate weights, shares, scores, probabilities, or percentage impacts in ` +
    `claim structured_conclusion. ` +
    `direction/strength invariant applies to every signal and component: NEUTRAL always has strength 0, while SUPPORTIVE ` +
    `or ADVERSE always has strength from 1 through 5. Use the fixed mode and exact component set from the runtime contract. ` +
    lang
  );
}

function submissionIsNeutral(submission: MacroAgentSubmission): boolean {
  return submission.mode === "DIRECT"
    ? submission.signal.direction === "NEUTRAL" && submission.signal.strength === 0
    : submission.components.every(
        (component) => component.direction === "NEUTRAL" && component.strength === 0,
      );
}

function authoredMacroSubmission(submission: MacroAgentSubmission): MacroAgentSubmission {
  return submission.mode === "DIRECT"
    ? {
        mode: "DIRECT",
        claims: submission.claims,
        key_drivers: submission.key_drivers,
        signal: submission.signal,
      }
    : {
        mode: "COMPONENTS",
        claims: submission.claims,
        key_drivers: submission.key_drivers,
        components: submission.components,
      };
}

function macroDataQualityFromSnapshot(
  agent: MacroAgentId,
  snapshot: Record<string, unknown>,
): MacroDataQualityInput {
  const contract = MACRO_ROLE_CONTRACTS[agent];
  if (contract.mode === "DIRECT") {
    const value = snapshot.direct_data_quality;
    if (typeof value !== "number") {
      throw new Error(`${agent}: snapshot direct_data_quality missing`);
    }
    return { mode: "DIRECT", dataQuality: value };
  }
  const raw = snapshot.component_data_quality;
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error(`${agent}: snapshot component_data_quality missing`);
  }
  const values = raw as Record<string, unknown>;
  const dataQualityByComponent: Record<string, number> = {};
  for (const component of Object.keys(contract.components)) {
    const value = values[component];
    if (typeof value !== "number") {
      throw new Error(`${agent}:${component}: snapshot data quality missing`);
    }
    dataQualityByComponent[component] = value;
  }
  if (
    Object.keys(values).sort().join("\0") !== Object.keys(contract.components).sort().join("\0")
  ) {
    throw new Error(`${agent}: snapshot component_data_quality set mismatch`);
  }
  return { mode: "COMPONENTS", dataQualityByComponent };
}

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

import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import type { z } from "zod";
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
import { runAgentToolLoop } from "../helpers/agent_loop.js";
import { extractTextContent } from "../helpers/content.js";
import {
  attachDeterministicFallbackClaimGraph,
  buildAgentInvocationId,
  buildRuntimeEvidenceSnapshot,
  type RuntimeEvidenceSnapshot,
  selectOutputByClaimEvidence,
} from "../helpers/evidence_runtime.js";
import {
  type AgentCanaryEventContext,
  agentCanaryEventContext,
  buildAgentPromptCanaryEvent,
} from "../helpers/prompt_canary.js";
import {
  applyResearchKnobCapsWithFallback,
  assertResearchKnobCappedOutputSchema,
  formatResearchKnobAuditFields,
  isResearchKnobsStageEnabled,
  type ResearchKnobsSnapshot,
  type RuntimeSourceStatus,
  type ToolStatus,
} from "../helpers/research_knobs.js";
import {
  AgentTimeoutError,
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
import { invokeStructuredOrFreetext } from "../helpers/structured_output.js";
import { type LoaderLanguage, loadPrompt, loadPromptWithKnobs } from "../prompts/loader.js";
import type { RuntimeAgentStageId } from "../prompts/runtime_agent_spec.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type {
  AlphaDiscoveryOutput,
  AutoExecOutput,
  CioOutput,
  CroOutput,
  Layer4AgentOutputKey,
  Layer4Outputs,
  Layer4RuntimeTraceEntry,
  LlmCallRecord,
} from "../types.js";
import { validateAutonomousExecutionActions } from "./execution_validator.js";
import {
  assertL4RunSnapshotStage,
  freezeCroReview,
  freezeExecutionFeasibility,
  layer4PromptSourceHash,
  runtimeStateForLayer4,
  stableRuntimeHash,
  updateLayer4Runtime,
} from "./layer4_runtime.js";

/** Union of the 4 Layer-4 outputs handled by this factory. */
export type Layer4AgentOutput = CroOutput | AlphaDiscoveryOutput | AutoExecOutput | CioOutput;

export interface LayerFourAgentSpec<TOutput extends Layer4AgentOutput> {
  agentId: string;
  runtimeStage: RuntimeAgentStageId;
  stateWriteMode?: "agent_output" | "cio_proposal" | "cio_final";
  schema: z.ZodType<TOutput>;
  fieldNames: ReadonlyArray<string>;
  /** The Layer4Outputs slot this agent populates. */
  stateUpdateField: Layer4AgentOutputKey;
  /** Build the user-context prose; each L4 agent reads different upstream layers.
   *  May be async — autonomous_execution fetches Darwinian weights from the
   *  bridge (Plan §11.3 sub-step 3F). */
  buildUserContext: (state: DailyCycleStateType) => string | Promise<string>;
  /** Bridge tools this decision agent may call during synthesis. */
  requiredTools?: ReadonlyArray<string>;
  render: (output: TOutput) => string;
  fallback: (analysisText: string) => TOutput;
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
    let fallbackRuntimeEvidence: RuntimeEvidenceSnapshot | null = null;
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
              ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
            });
            knobSnapshot = loaded.snapshot;
            systemPrompt = loaded.prompt;
            promptSourceHash = layer4PromptSourceHash(loaded.bodies);
            canaryKnobSnapshot = loaded.snapshot;
            canaryContext = agentCanaryEventContext({
              release: loaded.release,
              state,
              agentInvocationId: buildAgentInvocationId({
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
          const userContext = await spec.buildUserContext(state);
          const rkeAugmentedContext = await maybeAppendRkeContext(spec, userContext, deps, state);
          const augmentedContext = await maybeAppendMirofishContext(
            spec,
            rkeAugmentedContext,
            deps,
            language,
            mirofish.context,
          );
          let runtimeEvidence: RuntimeEvidenceSnapshot | null = knobSnapshot
            ? buildRuntimeEvidenceSnapshot({
                state,
                agent: spec.agentId,
                stage: spec.runtimeStage,
                knobSnapshot,
              })
            : null;
          fallbackRuntimeEvidence = runtimeEvidence;
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
          if (requiredTools.length > 0 && hasToolApi(deps.api)) {
            const tools = await pickBridgeTools(deps.api, requiredTools, {
              ...(state.mode === "backtest" && state.as_of_date
                ? { context: { mode: "backtest", as_of_date: state.as_of_date } }
                : {}),
            });
            const loopResult = await runAgentToolLoop({
              llm: deps.llmHandle.llm,
              tools: tools as StructuredToolInterface[],
              systemMessage: systemPrompt,
              initialMessages: [new HumanMessage(evidenceAugmentedContext)],
              ...(runtimeEvidence ? { agentInvocationId: runtimeEvidence.agentInvocationId } : {}),
              onLog: (msg) => onLog(formatAgentEvent("phase", "L4", spec.agentId, [msg])),
              signal,
            });
            analysisText = loopResult.analysisText;
            analysisLlmInvocations = loopResult.llmInvocations;
            toolCalls = loopResult.toolCalls;
            toolCacheHits = loopResult.toolCacheHits;
            toolExecutions = loopResult.toolExecutions;
            promptTokens = loopResult.promptTokens;
            completionTokens = loopResult.completionTokens;
            llmElapsedMs = loopResult.llmElapsedMs;
            toolStatuses = loopResult.toolStatuses;
            canaryToolStatuses = toolStatuses;
            if (knobSnapshot) {
              runtimeEvidence = buildRuntimeEvidenceSnapshot({
                state,
                agent: spec.agentId,
                stage: spec.runtimeStage,
                knobSnapshot,
                toolStatuses,
              });
              fallbackRuntimeEvidence = runtimeEvidence;
            }
          } else {
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
          }

          // Phase 2: structured extraction.
          onLog(
            formatAgentEvent("phase", "L4", spec.agentId, [`extract chars=${analysisText.length}`]),
          );
          const extractorSystem = spec.buildExtractorSystem
            ? spec.buildExtractorSystem(language)
            : defaultExtractorSystem(spec, language);
          const extractor = await invokeStructuredOrFreetext<TOutput>({
            llm: structuredHandle.llm,
            schema: spec.schema,
            messages: [
              new SystemMessage(extractorSystem),
              new HumanMessage(
                [analysisText || "(no analysis produced)", runtimeEvidence?.visibleCatalog]
                  .filter((part): part is string => Boolean(part))
                  .join("\n\n"),
              ),
            ],
            render: spec.render,
            agentName: spec.agentId,
            structuredOnlySentences: spec.structuredOnlySentences ?? [],
            onLog: (msg) => onLog(formatAgentEvent("phase", "L4", spec.agentId, [msg])),
            signal,
          });

          const rawOutput = extractor.structured ?? spec.fallback(analysisText);
          const claimSelection = runtimeEvidence
            ? selectOutputByClaimEvidence(rawOutput, () => spec.fallback(""), runtimeEvidence)
            : null;
          const claimSelectedOutput = claimSelection?.output ?? rawOutput;
          const capped = knobSnapshot
            ? applyResearchKnobCapsWithFallback(
                claimSelectedOutput,
                () => spec.fallback(""),
                knobSnapshot,
                { toolStatuses },
              )
            : null;
          let output = capped
            ? assertResearchKnobCappedOutputSchema(capped.output, spec.schema, spec.agentId)
            : claimSelectedOutput;
          if (runtimeEvidence && capped?.audit.output_selection === "deterministic_fallback") {
            output = attachDeterministicFallbackClaimGraph(
              output,
              runtimeEvidence,
              claimSelection?.rejectionReasons ?? [],
              capped.audit.fallback_reason_code ?? "UNSUPPORTED_KNOB_INFLUENCE",
            ).output;
          }
          if (spec.stateUpdateField === "autonomous_execution") {
            output = validateAutonomousExecutionActions({
              output: output as unknown as AutoExecOutput,
              knobSnapshot,
            }) as TOutput;
          }
          const canaryEvent = buildAgentPromptCanaryEvent({
            context: canaryContext,
            agent: spec.agentId,
            stage: spec.runtimeStage,
            startedAt,
            structuredAccepted: extractor.structured !== null,
            claimGraphAccepted: claimSelection?.rawOutputAccepted ?? true,
            knobSnapshot,
            knobAudit: capped?.audit ?? null,
            toolStatuses,
            output,
            validatorIds: [
              `${spec.agentId}.${spec.runtimeStage}.structured_output.v1`,
              "evidence_claim_graph_v1",
              "research_knobs_runtime_v1",
              ...(spec.stateUpdateField === "autonomous_execution"
                ? ["decision.autonomous_execution.action_validator.v1"]
                : []),
            ],
          });
          onLog(
            formatAgentEvent("done", "L4", spec.agentId, [
              `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
              `analysis_llm=${analysisLlmInvocations}`,
              `tools=${toolCalls}`,
              `tool_cache_hits=${toolCacheHits}`,
              `tool_executions=${toolExecutions}`,
              ...formatTokenMetricFields(promptTokens, completionTokens, llmElapsedMs),
              `source=${extractor.structured ? "structured" : "fallback"}`,
              ...(runtimeEvidence
                ? [
                    `evidence_entries=${runtimeEvidence.evidenceLedger.length}`,
                    `claim_output=${claimSelection?.rawOutputAccepted ? "accepted" : "fallback"}`,
                    `claim_rejections=${claimSelection?.rejectionReasons.length ?? 0}`,
                  ]
                : []),
              ...(capped ? formatResearchKnobAuditFields(capped.audit) : []),
              summarizeAgentOutput(output),
            ]),
          );

          return buildLayerFourUpdate(spec, output, buildLlmCall(spec.agentId, structuredHandle), {
            state,
            knobSnapshot,
            canaryEvent,
          });
        },
        timeoutMs,
        `L4 ${spec.agentId}`,
      );
    } catch (err) {
      if (err instanceof AgentTimeoutError) {
        if (
          isResearchKnobsStageEnabled(
            spec.agentId,
            spec.runtimeStage,
            undefined,
            state.active_cohort || "cohort_default",
          ) &&
          !fallbackRuntimeEvidence
        ) {
          throw err;
        }
        const fallback = spec.fallback("");
        const output = fallbackRuntimeEvidence
          ? attachDeterministicFallbackClaimGraph(
              fallback,
              fallbackRuntimeEvidence,
              ["agent_timeout"],
              "AGENT_TIMEOUT",
            ).output
          : fallback;
        const canaryEvent = buildAgentPromptCanaryEvent({
          context: canaryContext,
          agent: spec.agentId,
          stage: spec.runtimeStage,
          startedAt,
          structuredAccepted: false,
          claimGraphAccepted: false,
          knobSnapshot: canaryKnobSnapshot,
          knobAudit: null,
          toolStatuses: canaryToolStatuses,
          output,
          validatorIds: [
            `${spec.agentId}.${spec.runtimeStage}.structured_output.v1`,
            "evidence_claim_graph_v1",
            "research_knobs_runtime_v1",
          ],
          forceFallback: true,
        });
        onLog(
          formatAgentEvent("timeout", "L4", spec.agentId, [
            `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
            summarizeAgentOutput(output),
          ]),
        );
        return buildLayerFourUpdate(spec, output, buildLlmCall(spec.agentId, structuredHandle), {
          state,
          knobSnapshot: null,
          canaryEvent,
        });
      }
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function maybeAppendRkeContext<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  userContext: string,
  deps: LayerFourAgentDeps,
  state: DailyCycleStateType,
): Promise<string> {
  if (!hasToolApi(deps.api) || !spec.requiredTools?.includes("get_rke_research_context")) {
    return userContext;
  }
  const asOfDate = state.as_of_date || new Date().toISOString().slice(0, 10);
  try {
    const { text } = await deps.api.toolsCall(
      "get_rke_research_context",
      { agent_id: spec.agentId, layer: "decision", as_of_date: asOfDate, max_items: 3 },
      state.mode === "backtest" ? { mode: "backtest", as_of_date: asOfDate } : undefined,
    );
    deps.onLog?.(`rke context injected for ${spec.agentId}`);
    return (
      `${userContext}\n\n` +
      "RKE research prior context (redacted; shadow-only; " +
      "no trade without current data confirmation):\n" +
      text
    );
  } catch (err) {
    const message = safeErrorMessage(err);
    deps.onLog?.(`rke context injection skipped for ${spec.agentId}: ${message}`);
    return `${userContext}\n\nRKE research prior context unavailable: ${message}`;
  }
}

function hasToolApi(api: BridgeApi | undefined): api is BridgeApi {
  return typeof api?.toolsList === "function" && typeof api.toolsCall === "function";
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
    `The user message contains a free-form analysis. Populate the required ${spec.agentId} ` +
    `schema fields (${spec.fieldNames.join(", ")}). Cite only tickers / numbers that appeared ` +
    `in the analysis text; never invent. If the analysis is missing key inputs (e.g. cio ` +
    `with no autonomous_execution trades to act on), return the conservative fallback ` +
    `(empty arrays / confidence ≤ 0.3). When a runtime evidence catalog is present, include ` +
    `claims and per-entry claim_refs using only its evidence_id and allowed research rule ids. ` +
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
  },
): DailyCycleStateUpdate {
  if (opts.canaryEvent) llmCall.prompt_canary_event = opts.canaryEvent;
  const currentRuntime = runtimeStateForLayer4(opts.state);
  const runId = opts.state.trace_id || opts.state.as_of_date || "current_run";
  const mode = spec.stateWriteMode ?? "agent_output";
  if (mode === "cio_proposal") {
    const proposal = output as unknown as CioOutput;
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
      llm_calls: [llmCall],
    };
  }
  if (mode === "cio_final") {
    const finalOutput = output as unknown as CioOutput;
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
      llm_calls: [llmCall],
    };
  }

  let runtime = currentRuntime;
  let selectedOutput = output;
  if (spec.stateUpdateField === "alpha_discovery") {
    runtime = updateLayer4Runtime(
      currentRuntime,
      {},
      {
        stage: "alpha_discovery",
        operation: "agent_run",
        ...stageResultTrace(spec, output),
        input_hashes: {},
        output_hashes: { alpha_discovery: stableRuntimeHash(output) },
      },
    );
  } else if (spec.stateUpdateField === "cro") {
    const review = freezeCroReview(
      runId,
      currentRuntime.candidate_target_state,
      output as unknown as CroOutput,
    );
    selectedOutput = review.output as unknown as TOutput;
    runtime = updateLayer4Runtime(
      currentRuntime,
      { cro_review_state: review },
      {
        stage: "cro_review",
        operation: "agent_run",
        ...stageResultTrace(spec, selectedOutput),
        input_hashes: layer4InputHashes(currentRuntime),
        output_hashes: { cro_review_state: review.review_hash },
      },
    );
  } else if (spec.stateUpdateField === "autonomous_execution") {
    const feasibility = freezeExecutionFeasibility(
      runId,
      currentRuntime.candidate_target_state,
      currentRuntime.cro_review_state,
      output as unknown as AutoExecOutput,
      currentRuntime.resolved_source_statuses,
      opts.state.as_of_date || "live",
    );
    selectedOutput = feasibility.output as unknown as TOutput;
    runtime = updateLayer4Runtime(
      currentRuntime,
      { execution_feasibility_state: feasibility },
      {
        stage: "execution_feasibility",
        operation: "agent_run",
        ...stageResultTrace(spec, selectedOutput),
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
    llm_calls: [llmCall],
  };
}

function stageResultTrace<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  output: TOutput,
): Pick<
  Layer4RuntimeTraceEntry,
  "status" | "reason_codes" | "fallback_factory_id" | "fallback_factory_version"
> {
  const runtimeFallback = output.runtime_fallback_audit;
  if (runtimeFallback) {
    return {
      status: "fallback",
      reason_codes: [...runtimeFallback.reason_codes],
      fallback_factory_id: runtimeFallback.fallback_factory_id,
      fallback_factory_version: runtimeFallback.fallback_factory_version,
    };
  }
  const audit = (output as { verified_knob_audit?: { fallback_reason_code?: unknown } | undefined })
    .verified_knob_audit;
  const knobFallbackReason =
    typeof audit?.fallback_reason_code === "string" ? audit.fallback_reason_code : null;
  const claimAudit = (
    output as {
      verified_claim_audit?: { fallback_reason_code?: unknown } | undefined;
    }
  ).verified_claim_audit;
  const claimFallbackReason =
    typeof claimAudit?.fallback_reason_code === "string" ? claimAudit.fallback_reason_code : null;
  const fallbackReason = knobFallbackReason ?? claimFallbackReason;
  if (output.confidence > 0 && !fallbackReason) return { status: "completed" };
  return {
    status: "fallback",
    reason_codes: [fallbackReason ?? "AGENT_CONSERVATIVE_FALLBACK"],
    fallback_factory_id: `decision.${spec.agentId}.${spec.runtimeStage}.fallback`,
    fallback_factory_version: "1",
  };
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

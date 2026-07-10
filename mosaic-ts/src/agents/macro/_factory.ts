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
 *   2. **Structured extraction**
 *      - Feed the analysis text into ``invokeStructuredOrFreetext`` with the
 *        agent's Zod schema; on failure fall back to free-text mode and
 *        finally to a confidence=0 conservative stub
 *
 * Each Layer-1 macro agent file declares a ``LayerOneAgentSpec<TOutput>``
 * and a ``build<Agent>Node = (deps) => buildLayerOneAgentNode(spec, deps)``.
 *
 * 2D's sector / superinvestor / decision agents will define their own
 * layer-specific factories — Layer 2 reads from layer1_consensus instead of
 * BridgeApi tools, Layer 3 applies a philosophy filter prompt, Layer 4
 * synthesises across all upstream layers. Sharing this Layer-1 factory
 * across layers is **not** the goal — Plan §5 deliberately gives each
 * layer a different shape.
 */

import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import type { z } from "zod";
import { type BridgeApi, type MosaicConfig, pickBridgeTools } from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import { runAgentToolLoop } from "../helpers/agent_loop.js";
import {
  attachDeterministicFallbackClaimGraph,
  buildRuntimeEvidenceSnapshot,
  type RuntimeEvidenceSnapshot,
  selectOutputByClaimEvidence,
} from "../helpers/evidence_runtime.js";
import {
  applyResearchKnobCapsWithFallback,
  assertResearchKnobCappedOutputSchema,
  formatResearchKnobAuditFields,
  isResearchKnobsStageEnabled,
  type ResearchKnobsSnapshot,
} from "../helpers/research_knobs.js";
import {
  AgentTimeoutError,
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
import { invokeStructuredOrFreetext } from "../helpers/structured_output.js";
import { type LoaderLanguage, loadPrompt, loadPromptWithKnobs } from "../prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type { MacroAgentOutput } from "../types.js";

/**
 * Per-agent configuration for the Layer-1 factory. Each macro agent file
 * exports a ``LayerOneAgentSpec<TOutput>`` with the bits that vary across
 * the 10 agents.
 */
export interface LayerOneAgentSpec<TOutput extends MacroAgentOutput> {
  /** Canonical agent ID, e.g. "central_bank". Must match the prompt filename. */
  agentId: string;
  /** Zod schema for the structured output. */
  schema: z.ZodType<TOutput>;
  /** Schema field names; surfaced to the structured-output extractor prompt. */
  fieldNames: ReadonlyArray<string>;
  /** Bridge tools this agent will call during phase 1. */
  requiredTools: ReadonlyArray<string>;
  /** Render structured output as readable prose for state inspection / logs. */
  render: (output: TOutput) => string;
  /**
   * Conservative output emitted when both structured extraction and free-text
   * fallback fail. Should set ``confidence = 0`` so the L1 aggregator can
   * downweight the run. ``analysisText`` is whatever the loop produced
   * (possibly empty) — useful for surfacing partial context in
   * ``key_drivers`` or ``qe_qt_balance_change``-style fields.
   */
  fallback: (analysisText: string) => TOutput;
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
}

export type LayerOneAgentNode = (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>;

// ---------------------------------------------------------------------------
// Public factory
// ---------------------------------------------------------------------------

export function buildLayerOneAgentNode<TOutput extends MacroAgentOutput>(
  spec: LayerOneAgentSpec<TOutput>,
  deps: LayerOneAgentDeps,
): LayerOneAgentNode {
  return async function layerOneAgentNode(state) {
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const timeoutMs = resolveAgentTimeoutMs(deps.agentTimeoutSeconds);
    const onLog = deps.onLog ?? (() => undefined);
    const startedAt = Date.now();
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
          if (isResearchKnobsStageEnabled(spec.agentId, "agent_run")) {
            const runtimeSourceStatuses = resolveRuntimeSourceStatusesForAgent(
              state,
              spec.agentId,
              "agent_run",
            );
            const loaded = await loadPromptWithKnobs({
              agent: spec.agentId,
              cohort,
              stage: "agent_run",
              runtimeSourceStatuses,
              ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
            });
            knobSnapshot = loaded.snapshot;
            systemPrompt = loaded.prompt;
          } else {
            systemPrompt = await loadPrompt({
              agent: spec.agentId,
              cohort,
              language,
              ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
            });
          }

          // Phase 0b: pull the agent's tools from the bridge (with backtest
          // context attached so date-bound tools clamp end_date correctly).
          const tools = await pickBridgeTools(deps.api, spec.requiredTools, {
            ...(state.mode === "backtest" && state.as_of_date
              ? { context: { mode: "backtest", as_of_date: state.as_of_date } }
              : {}),
          });

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
          const loopResult = await runAgentToolLoop({
            llm: deps.llmHandle.llm,
            tools: tools as StructuredToolInterface[],
            systemMessage: systemPrompt,
            initialMessages: [new HumanMessage(evidenceUserContext)],
            ...(runtimeEvidence ? { agentInvocationId: runtimeEvidence.agentInvocationId } : {}),
            ...(spec.maxLoops !== undefined ? { maxLoops: spec.maxLoops } : {}),
            onLog: (msg) => onLog(formatAgentEvent("phase", "L1", spec.agentId, [msg])),
            signal,
          });
          if (knobSnapshot) {
            runtimeEvidence = buildRuntimeEvidenceSnapshot({
              state,
              agent: spec.agentId,
              stage: "agent_run",
              knobSnapshot,
              toolStatuses: loopResult.toolStatuses,
            });
          }

          // Phase 2: structured extraction from the analysis text.
          onLog(
            formatAgentEvent("phase", "L1", spec.agentId, [
              `extract chars=${loopResult.analysisText.length}`,
            ]),
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
                [
                  loopResult.analysisText || "(no analysis produced)",
                  runtimeEvidence?.visibleCatalog,
                ]
                  .filter((part): part is string => Boolean(part))
                  .join("\n\n"),
              ),
            ],
            render: spec.render,
            agentName: spec.agentId,
            structuredOnlySentences: spec.structuredOnlySentences ?? [],
            onLog: (msg) => onLog(formatAgentEvent("phase", "L1", spec.agentId, [msg])),
            signal,
          });

          // Phase 3: assemble state update.
          const rawOutput = extractor.structured ?? spec.fallback(loopResult.analysisText);
          const claimSelection = runtimeEvidence
            ? selectOutputByClaimEvidence(rawOutput, () => spec.fallback(""), runtimeEvidence)
            : null;
          const claimSelectedOutput = claimSelection?.output ?? rawOutput;
          const capped = knobSnapshot
            ? applyResearchKnobCapsWithFallback(
                claimSelectedOutput,
                () => spec.fallback(""),
                knobSnapshot,
                { toolStatuses: loopResult.toolStatuses },
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
          const llmCall = buildLlmCall(spec.agentId, structuredHandle);

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

          return {
            layer1_outputs: { [spec.agentId]: output },
            llm_calls: [llmCall],
          };
        },
        timeoutMs,
        `L1 ${spec.agentId}`,
      );
    } catch (err) {
      if (err instanceof AgentTimeoutError) {
        const output = spec.fallback("");
        onLog(
          formatAgentEvent("timeout", "L1", spec.agentId, [
            `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
            summarizeAgentOutput(output),
          ]),
        );
        return {
          layer1_outputs: { [spec.agentId]: output },
          llm_calls: [buildLlmCall(spec.agentId, structuredHandle)],
        };
      }
      onLog(
        formatAgentEvent("error", "L1", spec.agentId, [
          `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
          `message=${safeErrorMessage(err)}`,
        ]),
      );
      throw err;
    }
  };
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
    `Use get_rke_research_context only as report-derived research prior. ` +
    `It is not a live signal and cannot raise confidence unless current data ` +
    `tools confirm it. Run the required tools, gather current data, and write ` +
    `your analysis.`
  );
}

function defaultExtractorSystem<TOutput extends MacroAgentOutput>(
  spec: LayerOneAgentSpec<TOutput>,
  language: LoaderLanguage,
): string {
  const lang =
    language === "en"
      ? "Reply in English."
      : "Reply in Chinese. Numbers stay numeric; do not wrap them in 中文括号.";
  return (
    `You are a structured-output extractor for the ${spec.agentId} agent. ` +
    `The user message contains a free-form analysis written by a previous LLM call. ` +
    `Read it carefully and populate the required ${spec.agentId} schema fields ` +
    `(${spec.fieldNames.join(", ")}). ` +
    `Only emit values supported by the analysis text; never invent numbers. ` +
    `If a field cannot be supported by the text, use the most conservative valid value ` +
    `(prefer NEUTRAL stances, 0 numeric values, 'unknown' for date windows, ` +
    `confidence ≤ 0.4). When a runtime evidence catalog is present, include claims and ` +
    `top-level claim_refs using only its evidence_id and allowed research rule ids. ` +
    lang
  );
}

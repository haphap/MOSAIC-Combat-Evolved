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
import { invokeStructuredOrFreetext } from "../helpers/structured_output.js";
import { type LoaderLanguage, loadPrompt } from "../prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type { LlmCallRecord, MacroAgentOutput } from "../types.js";

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
}

export interface LayerOneAgentDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  /** Optional structured-output LLM (defaults to ``llmHandle``). */
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
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
    const cohort = state.active_cohort || "cohort_default";
    const language = pickPromptLanguage(deps.config);

    // Phase 0: load bilingual prompt for this cohort.
    const systemPrompt = await loadPrompt({
      agent: spec.agentId,
      cohort,
      language,
      ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
    });

    // Phase 0b: pull the agent's tools from the bridge (with backtest context
    // attached so date-bound tools clamp end_date correctly).
    const tools = await pickBridgeTools(deps.api, spec.requiredTools, {
      ...(state.mode === "backtest" && state.as_of_date
        ? { context: { mode: "backtest", as_of_date: state.as_of_date } }
        : {}),
    });

    // Phase 1: tool-bound free-form analysis loop.
    const userContext = buildUserContext(state, spec.agentId);
    const loopResult = await runAgentToolLoop({
      llm: deps.llmHandle.llm,
      tools: tools as StructuredToolInterface[],
      systemMessage: systemPrompt,
      initialMessages: [new HumanMessage(userContext)],
      onLog: deps.onLog ?? (() => undefined),
    });

    // Phase 2: structured extraction from the analysis text.
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const extractorSystem = spec.buildExtractorSystem
      ? spec.buildExtractorSystem(language)
      : defaultExtractorSystem(spec, language);
    const extractor = await invokeStructuredOrFreetext<TOutput>({
      llm: structuredHandle.llm,
      schema: spec.schema,
      messages: [
        new SystemMessage(extractorSystem),
        new HumanMessage(loopResult.analysisText || "(no analysis produced)"),
      ],
      render: spec.render,
      agentName: spec.agentId,
      structuredOnlySentences: spec.structuredOnlySentences ?? [],
    });

    // Phase 3: assemble state update.
    const output = extractor.structured ?? spec.fallback(loopResult.analysisText);

    const llmCall: LlmCallRecord = {
      ts: new Date().toISOString(),
      agent: spec.agentId,
      model: structuredHandle.model,
      provider: structuredHandle.provider,
      // Token counts are 0 here — Phase 3 scorecard will plumb provider
      // callbacks for accurate counts.
      prompt_tokens: 0,
      completion_tokens: 0,
      cost_usd: 0,
    };

    return {
      layer1_outputs: { [spec.agentId]: output },
      llm_calls: [llmCall],
    };
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
    `Run the required tools, gather data, and write your analysis.`
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
    `confidence ≤ 0.4). ` +
    lang
  );
}

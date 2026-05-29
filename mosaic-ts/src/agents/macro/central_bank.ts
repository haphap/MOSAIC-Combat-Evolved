/**
 * central_bank Layer-1 macro agent (Plan §5.1, §11.2 sub-step 2B).
 *
 * Two-phase execution per Plan §11.2 design note 2B-1:
 *   Phase 1 — bind 3 macro tools (get_pboc_ops / get_fred_series /
 *             get_yield_curve_cn) to the LLM and run an iterative tool loop
 *             until the model emits a final tool-call-free analysis text.
 *   Phase 2 — feed that analysis into a structured-output extractor against
 *             ``CentralBankSchema``. Free-text fallback kicks in if the
 *             provider doesn't support structured output (handled inside
 *             ``invokeStructuredOrFreetext``).
 *
 * The result is written into ``state.layer1_outputs.central_bank`` plus an
 * ``LlmCallRecord`` entry on ``state.llm_calls``.
 *
 * 2B uses a concrete one-off implementation; 2C will extract the common
 * scaffolding into ``buildAgentNode<TOutput>(...)`` once 9 more macro nodes
 * exist to inform the abstraction (Plan §11.2 design note 2B-2).
 */

import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import { type BridgeApi, type MosaicConfig, pickBridgeTools } from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import { runAgentToolLoop } from "../helpers/agent_loop.js";
import { invokeStructuredOrFreetext } from "../helpers/structured_output.js";
import { type LoaderLanguage, loadPrompt } from "../prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type { CentralBankOutput, LlmCallRecord } from "../types.js";
import { CENTRAL_BANK_FIELD_NAMES, CentralBankSchema } from "./_schemas.js";

const AGENT_ID = "central_bank";
const REQUIRED_TOOLS = ["get_pboc_ops", "get_fred_series", "get_yield_curve_cn"] as const;

const STRUCTURED_EXTRACTOR_SYSTEM = (language: LoaderLanguage): string => {
  const lang =
    language === "zh"
      ? "Reply in Chinese. Numbers stay numeric; do not wrap them in 中文括号."
      : language === "en"
        ? "Reply in English."
        : "Reply in Chinese.";
  return (
    "You are a structured-output extractor for the central_bank agent. " +
    "The user message contains a free-form analysis written by a previous LLM call. " +
    "Read it carefully and populate the required CentralBank schema fields. " +
    "Only emit values supported by the analysis text; never invent numbers. " +
    "If a field cannot be supported by the text, use the most conservative valid value " +
    "(stance=NEUTRAL, key_rate_change_bps=0, qe_qt_balance_change='no material change', " +
    "next_window='unknown', confidence ≤ 0.4). " +
    lang
  );
};

const STRUCTURED_ONLY_SENTENCES = [
  // Currently empty; central_bank's phase-1 system prompt is read from the
  // bilingual .md and contains writing-style rules but no schema-only
  // instructions to strip on free-text fallback. Reserved for future schema
  // tightening when we mark some prompt lines as structured-only.
] as const;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface BuildCentralBankNodeDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  /** Override for tests — returns the agent's LLM directly without consulting deps.llmHandle.llm.invoke. */
  llmHandleStructured?: LlmHandle;
  /** Optional logger for the inner tool loop. */
  onLog?: (msg: string) => void;
}

export type CentralBankNode = (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>;

/** Build the LangGraph-ready node function for central_bank. */
export function buildCentralBankNode(deps: BuildCentralBankNodeDeps): CentralBankNode {
  return async function centralBankNode(state) {
    const cohort = state.active_cohort || "cohort_default";
    const language = pickPromptLanguage(deps.config);

    // Phase 0: load bilingual prompt for this cohort.
    const systemPrompt = await loadPrompt({
      agent: AGENT_ID,
      cohort,
      language,
    });

    // Phase 0b: pull the 3 required tools from the bridge in declared order.
    const tools = await pickBridgeTools(deps.api, REQUIRED_TOOLS, {
      ...(state.mode === "backtest" && state.as_of_date
        ? { context: { mode: "backtest", as_of_date: state.as_of_date } }
        : {}),
    });

    // Phase 1: tool-bound free-form analysis loop.
    const userContext = buildUserContext(state);
    const loopResult = await runAgentToolLoop({
      llm: deps.llmHandle.llm,
      tools: tools as StructuredToolInterface[],
      systemMessage: systemPrompt,
      initialMessages: [new HumanMessage(userContext)],
      onLog: deps.onLog ?? (() => undefined),
    });

    // Phase 2: structured extraction from the analysis text.
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const extractor = await invokeStructuredOrFreetext<CentralBankOutput>({
      llm: structuredHandle.llm,
      schema: CentralBankSchema,
      messages: [
        new SystemMessage(STRUCTURED_EXTRACTOR_SYSTEM(language)),
        new HumanMessage(loopResult.analysisText || "(no analysis produced)"),
      ],
      render: renderCentralBank,
      agentName: AGENT_ID,
      structuredOnlySentences: STRUCTURED_ONLY_SENTENCES,
    });

    // Phase 3: assemble state update.
    const output: CentralBankOutput =
      extractor.structured ?? fallbackOutputFromText(loopResult.analysisText);

    const llmCall: LlmCallRecord = {
      ts: new Date().toISOString(),
      agent: AGENT_ID,
      model: structuredHandle.model,
      provider: structuredHandle.provider,
      // We don't have token counts from the inner helpers; downstream
      // observability (Phase 3 scorecard) will attach them via callbacks.
      prompt_tokens: 0,
      completion_tokens: 0,
      cost_usd: 0,
    };

    return {
      layer1_outputs: { [AGENT_ID]: output },
      llm_calls: [llmCall],
    };
  };
}

// ---------------------------------------------------------------------------
// Helpers (exported so 2C / tests can reuse them)
// ---------------------------------------------------------------------------

export function pickPromptLanguage(config: MosaicConfig): LoaderLanguage {
  const raw = (config.output_language ?? "Chinese").toString().toLowerCase().trim();
  if (raw === "english" || raw === "en") return "en";
  if (raw === "bilingual") return "Bilingual";
  return "zh";
}

export function buildUserContext(state: DailyCycleStateType): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  const mode = state.mode || "live";
  const cohort = state.active_cohort || "cohort_default";
  return (
    `Cycle context:\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${mode}\n` +
    `* cohort:     ${cohort}\n\n` +
    `Run the central_bank tools, gather data, and write your analysis.`
  );
}

/** Render a CentralBankOutput as readable prose (used for state inspection / logs). */
export function renderCentralBank(o: CentralBankOutput): string {
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `central_bank analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  stance:                 ${o.stance}\n` +
    `  key_rate_change_bps:    ${o.key_rate_change_bps}\n` +
    `  qe_qt_balance_change:   ${o.qe_qt_balance_change}\n` +
    `  next_window:            ${o.next_window}\n` +
    `  key_drivers:\n${drivers}`
  );
}

/**
 * Conservative fallback when both structured extraction and free-text
 * recovery yielded no usable output. Marks confidence=0 so the layer-1
 * aggregator can downweight or filter this run.
 */
export function fallbackOutputFromText(text: string): CentralBankOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "central_bank",
    stance: "NEUTRAL",
    key_rate_change_bps: 0,
    qe_qt_balance_change: trimmed
      ? "extraction failed; free-text analysis preserved"
      : "no analysis produced",
    next_window: "unknown",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

// Re-export for downstream / test ergonomics.
export { CENTRAL_BANK_FIELD_NAMES, CentralBankSchema, REQUIRED_TOOLS };

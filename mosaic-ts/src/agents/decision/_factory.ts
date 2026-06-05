/**
 * Generic factory for Layer-4 decision agent nodes (Plan §11.2 sub-step 2D.3).
 *
 * Differs structurally from L1/L2/L3 factories:
 *   * **No BridgeApi tool calls** — Layer 4 is synthesis-only. Every L4
 *     agent reads upstream state and reasons about it; no fresh data fetch.
 *   * **No tool loop** — straight LLM invoke + structured extraction.
 *     Cheaper per node (1-2 LLM calls vs L1-3's 3-4).
 *   * **Each agent's user-context build is custom** — cro reads L1+L2+L3,
 *     alpha reads L1+L2+L3, autonomous_execution reads cro+alpha+L3, cio
 *     reads everything. The spec carries a ``buildUserContext`` function
 *     so each agent picks exactly what it needs.
 *
 * State writes:
 *   * ``layer4_outputs[<stateUpdateField>]`` (cro / alpha_discovery /
 *     autonomous_execution / cio).
 *   * cio additionally writes ``portfolio_actions`` (top-level convenience
 *     mirror, single-writer replace).
 *   * ``llm_calls`` append.
 */

import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import type { z } from "zod";
import type { BridgeApi, MosaicConfig } from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import { formatMirofishContext } from "../../mirofish/context.js";
import { extractTextContent } from "../helpers/content.js";
import {
  AgentTimeoutError,
  buildLlmCall,
  formatAgentEvent,
  formatDurationMs,
  resolveAgentTimeoutMs,
  safeErrorMessage,
  summarizeAgentOutput,
  withAgentTimeout,
} from "../helpers/runtime.js";
import { invokeStructuredOrFreetext } from "../helpers/structured_output.js";
import { type LoaderLanguage, loadPrompt } from "../prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type {
  AlphaDiscoveryOutput,
  AutoExecOutput,
  CioOutput,
  CroOutput,
  Layer4Outputs,
  LlmCallRecord,
  PortfolioAction,
} from "../types.js";

/** Union of the 4 Layer-4 outputs handled by this factory. */
export type Layer4AgentOutput = CroOutput | AlphaDiscoveryOutput | AutoExecOutput | CioOutput;

export interface LayerFourAgentSpec<TOutput extends Layer4AgentOutput> {
  agentId: string;
  schema: z.ZodType<TOutput>;
  fieldNames: ReadonlyArray<string>;
  /** The Layer4Outputs slot this agent populates. */
  stateUpdateField: keyof Layer4Outputs;
  /** Build the user-context prose; each L4 agent reads different upstream layers.
   *  May be async — autonomous_execution fetches Darwinian weights from the
   *  bridge (Plan §11.3 sub-step 3F). */
  buildUserContext: (state: DailyCycleStateType) => string | Promise<string>;
  render: (output: TOutput) => string;
  fallback: (analysisText: string) => TOutput;
  structuredOnlySentences?: ReadonlyArray<string>;
  buildExtractorSystem?: (lang: LoaderLanguage) => string;
}

export interface LayerFourAgentDeps {
  llmHandle: LlmHandle;
  /** ``api`` kept for symmetry with other layers; L4 doesn't actually call tools. */
  api?: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
}

export type LayerFourAgentNode = (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>;

export function buildLayerFourAgentNode<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  deps: LayerFourAgentDeps,
): LayerFourAgentNode {
  return async function layerFourAgentNode(state) {
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const timeoutMs = resolveAgentTimeoutMs(deps.agentTimeoutSeconds);
    const onLog = deps.onLog ?? (() => undefined);
    const startedAt = Date.now();
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

          // Phase 0: load prompt.
          const systemPrompt = await loadPrompt({
            agent: spec.agentId,
            cohort,
            language,
            ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
          });

          // Phase 1: synthesis (no tools, single invoke).
          const userContext = await spec.buildUserContext(state);
          const augmentedContext = await maybeAppendMirofishContext(
            spec,
            userContext,
            deps,
            state,
            language,
          );
          onLog(formatAgentEvent("phase", "L4", spec.agentId, ["synthesis_llm=1"]));
          const analysisResponse = await deps.llmHandle.llm.invoke(
            [new SystemMessage(systemPrompt), new HumanMessage(augmentedContext)],
            signal ? { signal } : undefined,
          );
          const analysisText =
            typeof analysisResponse.content === "string"
              ? analysisResponse.content
              : extractTextContent(analysisResponse.content);

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
              new HumanMessage(analysisText || "(no analysis produced)"),
            ],
            render: spec.render,
            agentName: spec.agentId,
            structuredOnlySentences: spec.structuredOnlySentences ?? [],
            onLog: (msg) => onLog(formatAgentEvent("phase", "L4", spec.agentId, [msg])),
            signal,
          });

          const output = extractor.structured ?? spec.fallback(analysisText);
          onLog(
            formatAgentEvent("done", "L4", spec.agentId, [
              `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
              "analysis_llm=1",
              "tools=0",
              `source=${extractor.structured ? "structured" : "fallback"}`,
              summarizeAgentOutput(output),
            ]),
          );

          return buildLayerFourUpdate(spec, output, buildLlmCall(spec.agentId, structuredHandle));
        },
        timeoutMs,
        `L4 ${spec.agentId}`,
      );
    } catch (err) {
      if (err instanceof AgentTimeoutError) {
        const output = spec.fallback("");
        onLog(
          formatAgentEvent("timeout", "L4", spec.agentId, [
            `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
            summarizeAgentOutput(output),
          ]),
        );
        return buildLayerFourUpdate(spec, output, buildLlmCall(spec.agentId, structuredHandle));
      }
      onLog(
        formatAgentEvent("error", "L4", spec.agentId, [
          `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
          `message=${safeErrorMessage(err)}`,
        ]),
      );
      throw err;
    }
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** 7M Step 2: opt-in injection of the latest MiroFish scenario context into the
 *  CIO prompt. Off unless ``config.mirofish.inject_context`` is true; only the
 *  cio agent (final synthesis) gets it; no-op when no context or no api. */
async function maybeAppendMirofishContext<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  userContext: string,
  deps: LayerFourAgentDeps,
  state: DailyCycleStateType,
  language: LoaderLanguage,
): Promise<string> {
  if (spec.agentId !== "cio" || !deps.api || !deps.config.mirofish?.inject_context) {
    return userContext;
  }
  try {
    const { context } = await deps.api.mirofishGetContext(
      state.as_of_date ? { as_of_date: state.as_of_date } : {},
    );
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
    `(empty arrays / confidence ≤ 0.3). ` +
    lang
  );
}

function buildLayerFourUpdate<TOutput extends Layer4AgentOutput>(
  spec: LayerFourAgentSpec<TOutput>,
  output: TOutput,
  llmCall: LlmCallRecord,
): DailyCycleStateUpdate {
  // Per-agent state update. cio additionally mirrors portfolio_actions to
  // the top-level field so Phase 3 scorecard / TUI consumers don't have
  // to dive through layer4_outputs.cio.
  const baseUpdate: DailyCycleStateUpdate = {
    layer4_outputs: { [spec.stateUpdateField]: output } as Partial<Layer4Outputs>,
    llm_calls: [llmCall],
  };
  if (spec.stateUpdateField === "cio") {
    const cioOut = output as unknown as CioOutput;
    (baseUpdate as { portfolio_actions: PortfolioAction[] }).portfolio_actions =
      cioOut.portfolio_actions;
  }
  return baseUpdate;
}

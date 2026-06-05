/**
 * Generic factory for Layer-2 sector agent nodes (Plan §11.2 sub-step 2D.1).
 *
 * Extends the Layer-1 factory pattern with two key adaptations:
 *
 *   1. **Reads upstream state**: each Layer-2 node reads
 *      ``state.layer1_consensus`` (RegimeSignal) and the relevant
 *      ``state.layer1_outputs.{china, institutional_flow}`` summaries to
 *      include in the phase-1 system message context. Sector picks must
 *      be aware of macro regime + which sectors policy is steering capital
 *      to.
 *
 *   2. **Writes to ``layer2_outputs``** (vs Layer-1's ``layer1_outputs``).
 *
 * Otherwise the factory follows the same two-phase semantics:
 *   Phase 1: tool-bound free-form analysis loop.
 *   Phase 2: structured extraction via invokeStructuredOrFreetext.
 *
 * relationship_mapper agent uses this same factory — the schema is
 * different but the orchestration is identical.
 */

import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import type { z } from "zod";
import { type BridgeApi, type MosaicConfig, pickBridgeTools } from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import { runAgentToolLoop } from "../helpers/agent_loop.js";
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
import type { RegimeSignal, SectorAgentOutput } from "../types.js";

export interface LayerTwoAgentSpec<TOutput extends SectorAgentOutput> {
  agentId: string;
  schema: z.ZodType<TOutput>;
  fieldNames: ReadonlyArray<string>;
  requiredTools: ReadonlyArray<string>;
  render: (output: TOutput) => string;
  fallback: (analysisText: string, regime: RegimeSignal | null) => TOutput;
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

          const systemPrompt = await loadPrompt({
            agent: spec.agentId,
            cohort,
            language,
            ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
          });

          const tools = await pickBridgeTools(deps.api, spec.requiredTools, {
            ...(state.mode === "backtest" && state.as_of_date
              ? { context: { mode: "backtest", as_of_date: state.as_of_date } }
              : {}),
          });

          // Phase 1: tool-bound analysis. User context now includes Layer-1
          // regime summary so sector agent's picks are regime-aware.
          const userContext = buildLayerTwoUserContext(state, spec.agentId);
          const loopResult = await runAgentToolLoop({
            llm: deps.llmHandle.llm,
            tools: tools as StructuredToolInterface[],
            systemMessage: systemPrompt,
            initialMessages: [new HumanMessage(userContext)],
            onLog: (msg) => onLog(formatAgentEvent("phase", "L2", spec.agentId, [msg])),
            signal,
          });

          // Phase 2: structured extraction.
          onLog(
            formatAgentEvent("phase", "L2", spec.agentId, [
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
              new HumanMessage(loopResult.analysisText || "(no analysis produced)"),
            ],
            render: spec.render,
            agentName: spec.agentId,
            structuredOnlySentences: spec.structuredOnlySentences ?? [],
            onLog: (msg) => onLog(formatAgentEvent("phase", "L2", spec.agentId, [msg])),
            signal,
          });

          const output =
            extractor.structured ?? spec.fallback(loopResult.analysisText, state.layer1_consensus);
          const llmCall = buildLlmCall(spec.agentId, structuredHandle);

          onLog(
            formatAgentEvent("done", "L2", spec.agentId, [
              `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
              `analysis_llm=${loopResult.llmInvocations}`,
              `tools=${loopResult.toolCalls}`,
              `source=${extractor.structured ? "structured" : "fallback"}`,
              summarizeAgentOutput(output),
            ]),
          );

          return {
            layer2_outputs: { [spec.agentId]: output },
            llm_calls: [llmCall],
          };
        },
        timeoutMs,
        `L2 ${spec.agentId}`,
      );
    } catch (err) {
      if (err instanceof AgentTimeoutError) {
        const output = spec.fallback("", state.layer1_consensus);
        onLog(
          formatAgentEvent("timeout", "L2", spec.agentId, [
            `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
            summarizeAgentOutput(output),
          ]),
        );
        return {
          layer2_outputs: { [spec.agentId]: output },
          llm_calls: [buildLlmCall(spec.agentId, structuredHandle)],
        };
      }
      onLog(
        formatAgentEvent("error", "L2", spec.agentId, [
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

export function pickPromptLanguage(config: MosaicConfig): LoaderLanguage {
  const raw = (config.output_language ?? "Chinese").toString().toLowerCase().trim();
  if (raw === "english" || raw === "en") return "en";
  if (raw === "bilingual") return "Bilingual";
  return "zh";
}

/** Build user-context block that includes upstream Layer-1 summaries. */
export function buildLayerTwoUserContext(state: DailyCycleStateType, agentId: string): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  const mode = state.mode || "live";
  const cohort = state.active_cohort || "cohort_default";
  const regime = state.layer1_consensus;

  const regimeBlock = regime
    ? `## Layer-1 macro regime\n` +
      `* stance: ${regime.stance}\n` +
      `* confidence: ${regime.confidence.toFixed(2)}\n` +
      `* layer_1_consensus_score: ${regime.layer_1_consensus_score.toFixed(2)}\n` +
      `* key_drivers:\n${regime.key_drivers.map((d) => `  - ${d}`).join("\n")}\n`
    : "## Layer-1 macro regime\n* (not available — state.layer1_consensus is null)\n";

  const chinaBlock = renderChinaSummary(state);
  const flowBlock = renderInstitutionalFlowSummary(state);

  return (
    `Cycle context for ${agentId} (Layer 2 sector analyst):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${mode}\n` +
    `* cohort:     ${cohort}\n\n` +
    `${regimeBlock}\n` +
    `${chinaBlock}\n` +
    `${flowBlock}\n` +
    `Pick longs and shorts in this sector taking the macro regime + policy ` +
    `direction + capital flow into account. Use the tools to gather sector-` +
    `specific evidence, then write your analysis.`
  );
}

function renderChinaSummary(state: DailyCycleStateType): string {
  const out = state.layer1_outputs?.china;
  if (out?.agent !== "china") return "## china (Layer 1)\n* (not available)\n";
  return (
    `## china (Layer 1) — policy direction\n` +
    `* policy_direction: ${out.policy_direction}\n` +
    `* sector_focus:     ${out.sector_focus.join(", ")}\n` +
    `* risk_drivers:     ${out.risk_drivers.join(", ")}\n`
  );
}

function renderInstitutionalFlowSummary(state: DailyCycleStateType): string {
  const out = state.layer1_outputs?.institutional_flow;
  if (out?.agent !== "institutional_flow")
    return "## institutional_flow (Layer 1)\n* (not available)\n";
  const sectors = out.sectors_in_out
    .map((s) => `${s.sector}=${s.net_amount_cny.toFixed(0)}`)
    .join(", ");
  return (
    `## institutional_flow (Layer 1)\n` +
    `* main_net_flow_cny: ${out.main_net_flow_cny.toFixed(0)} CNY mil\n` +
    `* sectors_in_out:     ${sectors}\n`
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
    `The user message contains a free-form analysis. Populate the required ${spec.agentId} ` +
    `schema fields (${spec.fieldNames.join(", ")}). Only emit values supported by the ` +
    `analysis text; never invent ticker codes or net-flow numbers. If a field cannot be ` +
    `supported, leave longs/shorts empty, sector_score=0, confidence ≤ 0.4. ` +
    lang
  );
}

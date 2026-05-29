/**
 * Generic factory for Layer-3 superinvestor agent nodes (Plan §11.2 sub-step 2D.2).
 *
 * Reads upstream:
 *   - state.layer1_consensus (RegimeSignal)
 *   - state.layer2_outputs.* (the 7 sector agents' picks → candidate universe)
 *
 * Writes:
 *   - state.layer3_outputs[<agentId>] (SuperinvestorOutput)
 *   - state.llm_calls (append)
 *
 * Same two-phase semantics as L1/L2 factories. Each superinvestor has a
 * different philosophy filter (encoded in their prompt + supplementary
 * tools), but the orchestration is identical — schema-agnostic.
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
import type { LlmCallRecord, RegimeSignal, SuperinvestorOutput } from "../types.js";

export interface LayerThreeAgentSpec<TOutput extends SuperinvestorOutput> {
  agentId: string;
  schema: z.ZodType<TOutput>;
  fieldNames: ReadonlyArray<string>;
  requiredTools: ReadonlyArray<string>;
  render: (output: TOutput) => string;
  fallback: (analysisText: string, regime: RegimeSignal | null) => TOutput;
  structuredOnlySentences?: ReadonlyArray<string>;
  buildExtractorSystem?: (lang: LoaderLanguage) => string;
}

export interface LayerThreeAgentDeps {
  llmHandle: LlmHandle;
  api: BridgeApi;
  config: MosaicConfig;
  llmHandleStructured?: LlmHandle;
  onLog?: (msg: string) => void;
}

export type LayerThreeAgentNode = (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>;

export function buildLayerThreeAgentNode<TOutput extends SuperinvestorOutput>(
  spec: LayerThreeAgentSpec<TOutput>,
  deps: LayerThreeAgentDeps,
): LayerThreeAgentNode {
  return async function layerThreeAgentNode(state) {
    const cohort = state.active_cohort || "cohort_default";
    const language = pickPromptLanguage(deps.config);

    const systemPrompt = await loadPrompt({
      agent: spec.agentId,
      cohort,
      language,
    });

    const tools = await pickBridgeTools(deps.api, spec.requiredTools, {
      ...(state.mode === "backtest" && state.as_of_date
        ? { context: { mode: "backtest", as_of_date: state.as_of_date } }
        : {}),
    });

    const userContext = buildLayerThreeUserContext(state, spec.agentId);
    const loopResult = await runAgentToolLoop({
      llm: deps.llmHandle.llm,
      tools: tools as StructuredToolInterface[],
      systemMessage: systemPrompt,
      initialMessages: [new HumanMessage(userContext)],
      onLog: deps.onLog ?? (() => undefined),
    });

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

    const output =
      extractor.structured ?? spec.fallback(loopResult.analysisText, state.layer1_consensus);

    const llmCall: LlmCallRecord = {
      ts: new Date().toISOString(),
      agent: spec.agentId,
      model: structuredHandle.model,
      provider: structuredHandle.provider,
      prompt_tokens: 0,
      completion_tokens: 0,
      cost_usd: 0,
    };

    return {
      layer3_outputs: { [spec.agentId]: output },
      llm_calls: [llmCall],
    };
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

/** Build user-context block that surfaces L1 regime + L2 sector picks. */
export function buildLayerThreeUserContext(state: DailyCycleStateType, agentId: string): string {
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

  const sectorBlocks = renderSectorPicks(state);

  return (
    `Cycle context for ${agentId} (Layer 3 superinvestor):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${mode}\n` +
    `* cohort:     ${cohort}\n\n` +
    `${regimeBlock}\n` +
    `${sectorBlocks}\n` +
    `Apply your investment philosophy to the candidate set above. Use your ` +
    `philosophy-specific tools only for spot-verification, never for stock ` +
    `discovery — discovery comes from the Layer-2 longs.`
  );
}

function renderSectorPicks(state: DailyCycleStateType): string {
  const sectors = state.layer2_outputs ?? {};
  const lines: string[] = ["## Layer-2 sector picks (candidate universe)"];

  for (const [sectorId, out] of Object.entries(sectors)) {
    if (out.agent === "relationship_mapper") {
      const chains = out.supply_chains.map((c) => `${c.name}=[${c.tickers.join(",")}]`).join("; ");
      const risks = out.contagion_risks.join(" | ");
      lines.push(`### ${sectorId} (cross-sector)`);
      lines.push(`* supply_chains: ${chains || "(none)"}`);
      lines.push(`* contagion_risks: ${risks || "(none)"}`);
    } else {
      const longs = out.longs
        .slice(0, 5)
        .map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`)
        .join(", ");
      const shorts = out.shorts
        .slice(0, 5)
        .map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`)
        .join(", ");
      lines.push(
        `### ${sectorId} (score=${out.sector_score.toFixed(2)}, conf=${out.confidence.toFixed(2)})`,
      );
      lines.push(`* longs:  ${longs || "(none)"}`);
      lines.push(`* shorts: ${shorts || "(none)"}`);
    }
  }

  if (Object.keys(sectors).length === 0) {
    lines.push("* (no Layer-2 outputs available — falling back to philosophy alone)");
  }
  return lines.join("\n");
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
    `The user message contains a free-form philosophy-driven analysis. Populate the required ` +
    `${spec.agentId} schema fields (${spec.fieldNames.join(", ")}). picks must be 3-5 ` +
    `concrete A-share tickers (e.g. '600519.SH') sourced from the Layer-2 candidate ` +
    `universe in the analysis text — never invent codes. Each pick needs a thesis, ` +
    `conviction (0-1), and holding_period from {1W, 1M, 3M, 6M, 1Y, 5Y+}. ` +
    `If the analysis cannot support 3 picks, return what's defensible and mark confidence ≤ 0.4. ` +
    lang
  );
}

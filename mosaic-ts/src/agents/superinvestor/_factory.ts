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
import type { BridgeApi, BridgeToolFactoryOptions, MosaicConfig } from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import { type AgentInitialToolCall, runAgentToolLoop } from "../helpers/agent_loop.js";
import { pickResearchDigestTools } from "../helpers/research_digest_tools.js";
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
import { invokeStructuredOrFreetext } from "../helpers/structured_output.js";
import { type LoaderLanguage, loadPrompt } from "../prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type { RegimeSignal, SuperinvestorOutput } from "../types.js";

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
  /** Per-agent wall-clock timeout in seconds. Default: 300; <=0 disables. */
  agentTimeoutSeconds?: number;
  /** Override prompt-root directory (tests inject a tmpdir). */
  promptsRoot?: string;
}

export type LayerThreeAgentNode = (state: DailyCycleStateType) => Promise<DailyCycleStateUpdate>;

export function buildLayerThreeAgentNode<TOutput extends SuperinvestorOutput>(
  spec: LayerThreeAgentSpec<TOutput>,
  deps: LayerThreeAgentDeps,
): LayerThreeAgentNode {
  return async function layerThreeAgentNode(state) {
    const structuredHandle = deps.llmHandleStructured ?? deps.llmHandle;
    const timeoutMs = resolveAgentTimeoutMs(deps.agentTimeoutSeconds);
    const onLog = deps.onLog ?? (() => undefined);
    const startedAt = Date.now();
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

          const baseSystemPrompt = await loadPrompt({
            agent: spec.agentId,
            cohort,
            language,
            ...(deps.promptsRoot ? { promptsRoot: deps.promptsRoot } : {}),
          });
          const systemPrompt = `${baseSystemPrompt}\n\n${buildLayerThreeCurrentToolContract(spec.requiredTools)}`;

          const toolOptions = {
            ...(state.mode === "backtest" && state.as_of_date
              ? { context: { mode: "backtest", as_of_date: state.as_of_date } }
              : {}),
          } satisfies BridgeToolFactoryOptions;
          const tools = await pickResearchDigestTools({
            api: deps.api,
            names: spec.requiredTools,
            options: toolOptions,
            llmHandle: deps.llmHandle,
            onLog: (msg) => onLog(formatAgentEvent("phase", "L3", spec.agentId, [msg])),
            signal,
          });

          const userContext = buildLayerThreeUserContext(state, spec.agentId);
          const loopResult = await runAgentToolLoop({
            llm: deps.llmHandle.llm,
            tools: tools as StructuredToolInterface[],
            systemMessage: systemPrompt,
            initialMessages: [new HumanMessage(userContext)],
            initialToolCalls: buildLayerThreeInitialToolCalls(state, spec.agentId),
            maxLoops: 3,
            replayFullToolMaxChars: 80_000,
            onLog: (msg) => onLog(formatAgentEvent("phase", "L3", spec.agentId, [msg])),
            signal,
          });

          onLog(
            formatAgentEvent("phase", "L3", spec.agentId, [
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
            onLog: (msg) => onLog(formatAgentEvent("phase", "L3", spec.agentId, [msg])),
            signal,
          });

          const output =
            extractor.structured ?? spec.fallback(loopResult.analysisText, state.layer1_consensus);
          const llmCall = buildLlmCall(spec.agentId, structuredHandle);

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
              `source=${extractor.structured ? "structured" : "fallback"}`,
              summarizeAgentOutput(output),
            ]),
          );

          return {
            layer3_outputs: { [spec.agentId]: output },
            llm_calls: [llmCall],
          };
        },
        timeoutMs,
        `L3 ${spec.agentId}`,
      );
    } catch (err) {
      if (err instanceof AgentTimeoutError) {
        const output = spec.fallback("", state.layer1_consensus);
        onLog(
          formatAgentEvent("timeout", "L3", spec.agentId, [
            `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
            summarizeAgentOutput(output),
          ]),
        );
        return {
          layer3_outputs: { [spec.agentId]: output },
          llm_calls: [buildLlmCall(spec.agentId, structuredHandle)],
        };
      }
      onLog(
        formatAgentEvent("error", "L3", spec.agentId, [
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
    buildLayerThreeToolPlan(agentId) +
    `\n` +
    `Use get_rke_research_context only as report-derived research prior and ` +
    `style-fit hint. It may expand or annotate the candidate set, but any pick ` +
    `must be confirmed by current stock research, fundamentals, financials, or price data. ` +
    `Apply your investment philosophy to the candidate set above. Use your ` +
    `philosophy-specific tools for current verification before selecting stocks.`
  );
}

export function buildLayerThreeInitialToolCalls(
  state: DailyCycleStateType,
  agentId: string,
): AgentInitialToolCall[] {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  if (agentId === "ackman") {
    return pickAckmanCandidateTickers(state)
      .slice(0, 2)
      .flatMap((ticker) => [
        { name: "get_fundamentals", args: { ticker, curr_date: date } },
        { name: "get_cashflow", args: { ticker, freq: "annual", curr_date: date } },
      ]);
  }
  if (agentId === "burry") {
    return pickBurryCandidateTickers(state)
      .slice(0, 2)
      .flatMap((ticker) => [
        { name: "get_fundamentals", args: { ticker, curr_date: date } },
        { name: "get_balance_sheet", args: { ticker, freq: "annual", curr_date: date } },
      ]);
  }
  return [];
}

function buildLayerThreeToolPlan(agentId: string): string {
  if (agentId === "ackman") {
    return (
      `## Tool plan\n` +
      `* Initial evidence: verify 1-2 consumer/financial quality candidates with fundamentals and cashflow.\n` +
      `* Round 1: judge pricing power, FCF conversion, balance-sheet durability, and candidate fit.\n` +
      `* Round 2: use stock research, income statement, balance sheet, or stock data only for catalyst/quality gaps.\n` +
      `* Round 3: fill one critical gap only; do not broaden beyond the quality-compounder candidate set.\n` +
      `* Round 4: no more tools; write the final analysis from gathered evidence.\n`
    );
  }
  return (
    `## Tool plan\n` +
    `* Round 1: pick at least 2 candidate tickers that fit your philosophy and verify them with stock research or fundamentals.\n` +
    `* Round 2: verify the strongest candidates with available financial, cashflow, balance-sheet, price, or indicator tools.\n` +
    `* Round 3: fill only critical gaps with stock research, cashflow, or policy evidence.\n` +
    `* Round 4: no more tools; write the final analysis from gathered evidence.\n`
  );
}

function buildLayerThreeCurrentToolContract(requiredTools: ReadonlyArray<string>): string {
  return (
    `## Current tool contract\n` +
    `Only call these registered tools: ${requiredTools.join(", ")}.\n` +
    `Do not call older prompt names that are not listed above.\n` +
    `Use current financial, stock research, price, policy, or RKE-prior tools according to your role; ` +
    `do not skip current verification for final picks.`
  );
}

function pickAckmanCandidateTickers(state: DailyCycleStateType): string[] {
  const outputs = state.layer2_outputs ?? {};
  const preferred = ["consumer", "financials"];
  const tickers: string[] = [];
  for (const agent of preferred) {
    const output = outputs[agent];
    if (output && "longs" in output) {
      tickers.push(...output.longs.map((pick) => pick.ticker));
    }
  }
  if (tickers.length === 0) {
    for (const output of Object.values(outputs)) {
      if (output && "longs" in output) tickers.push(...output.longs.map((pick) => pick.ticker));
    }
  }
  return [...new Set(tickers.filter(Boolean))];
}

function pickBurryCandidateTickers(state: DailyCycleStateType): string[] {
  const tickers: string[] = [];
  for (const output of Object.values(state.layer2_outputs ?? {})) {
    if (output && "shorts" in output) tickers.push(...output.shorts.map((pick) => pick.ticker));
  }
  for (const output of Object.values(state.layer2_outputs ?? {})) {
    if (output && "longs" in output) tickers.push(...output.longs.map((pick) => pick.ticker));
  }
  return [...new Set(tickers.filter(Boolean))];
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

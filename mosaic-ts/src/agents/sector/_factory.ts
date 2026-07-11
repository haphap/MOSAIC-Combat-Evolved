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
import { persistPromptReleaseCanaryEvents } from "../../autoresearch/prompt_release_canary_slo.js";
import type { BridgeApi, BridgeToolFactoryOptions, MosaicConfig } from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import { runAgentToolLoop } from "../helpers/agent_loop.js";
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
  beginAgentPromptCanaryInvocation,
  buildAgentPromptCanaryEvent,
} from "../helpers/prompt_canary.js";
import { pickResearchDigestTools } from "../helpers/research_digest_tools.js";
import {
  applyResearchKnobCapsWithFallback,
  assertResearchKnobCappedOutputSchema,
  formatResearchKnobAuditFields,
  isResearchKnobsStageEnabled,
  type ResearchKnobsSnapshot,
  type ToolStatus,
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
    let fallbackRuntimeEvidence: RuntimeEvidenceSnapshot | null = null;
    let canaryContext: AgentCanaryEventContext | null = null;
    let canaryKnobSnapshot: ResearchKnobsSnapshot | null = null;
    let canaryToolStatuses: ReadonlyArray<ToolStatus> = [];
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

          let knobSnapshot: ResearchKnobsSnapshot | null = null;
          let baseSystemPrompt: string;
          let release: Parameters<typeof agentCanaryEventContext>[0]["release"];
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
          const systemPrompt = `${baseSystemPrompt}\n\n${buildCurrentToolContract(spec.requiredTools)}`;
          if (knobSnapshot) {
            canaryContext = agentCanaryEventContext({
              release,
              state,
              agentInvocationId:
                canaryContext?.agentInvocationId ??
                buildAgentInvocationId({
                  runId: state.trace_id || state.as_of_date || "current_run",
                  agent: spec.agentId,
                  stage: "agent_run",
                  cohort,
                  asOf: state.as_of_date || "live",
                  snapshotHash: knobSnapshot.hash,
                }),
              systemPrompt,
            });
          }

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
            onLog: (msg) => onLog(formatAgentEvent("phase", "L2", spec.agentId, [msg])),
            signal,
          });

          // Phase 1: tool-bound analysis. User context now includes Layer-1
          // regime summary so sector agent's picks are regime-aware.
          const userContext = buildLayerTwoUserContext(state, spec.agentId);
          let runtimeEvidence: RuntimeEvidenceSnapshot | null = knobSnapshot
            ? buildRuntimeEvidenceSnapshot({
                state,
                agent: spec.agentId,
                stage: "agent_run",
                knobSnapshot,
              })
            : null;
          fallbackRuntimeEvidence = runtimeEvidence;
          const evidenceUserContext = runtimeEvidence
            ? `${userContext}\n\n${runtimeEvidence.visibleCatalog}`
            : userContext;
          const loopResult = await runAgentToolLoop({
            llm: deps.llmHandle.llm,
            tools: tools as StructuredToolInterface[],
            systemMessage: systemPrompt,
            initialMessages: [new HumanMessage(evidenceUserContext)],
            ...(runtimeEvidence ? { agentInvocationId: runtimeEvidence.agentInvocationId } : {}),
            maxLoops: 3,
            replayFullToolMaxChars: 80_000,
            onLog: (msg) => onLog(formatAgentEvent("phase", "L2", spec.agentId, [msg])),
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
            fallbackRuntimeEvidence = runtimeEvidence;
          }
          canaryToolStatuses = loopResult.toolStatuses;

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
            onLog: (msg) => onLog(formatAgentEvent("phase", "L2", spec.agentId, [msg])),
            signal,
          });

          const rawOutput =
            extractor.structured ?? spec.fallback(loopResult.analysisText, state.layer1_consensus);
          const claimSelection = runtimeEvidence
            ? selectOutputByClaimEvidence(
                rawOutput,
                () => spec.fallback("", state.layer1_consensus),
                runtimeEvidence,
              )
            : null;
          const claimSelectedOutput = claimSelection?.output ?? rawOutput;
          const capped = knobSnapshot
            ? applyResearchKnobCapsWithFallback(
                claimSelectedOutput,
                () => spec.fallback("", state.layer1_consensus),
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
          const canaryEvent = buildAgentPromptCanaryEvent({
            context: canaryContext,
            agent: spec.agentId,
            stage: "agent_run",
            startedAt,
            structuredAccepted: extractor.structured !== null,
            claimGraphAccepted: claimSelection?.rawOutputAccepted ?? true,
            knobSnapshot,
            knobAudit: capped?.audit ?? null,
            toolStatuses: loopResult.toolStatuses,
            output,
            validatorIds: [
              `${spec.agentId}.structured_output.v1`,
              "evidence_claim_graph_v1",
              "research_knobs_runtime_v1",
            ],
          });
          if (canaryEvent) {
            llmCall.prompt_canary_event = canaryEvent;
            await persistPromptReleaseCanaryEvents([canaryEvent]);
          }

          onLog(
            formatAgentEvent("done", "L2", spec.agentId, [
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
            layer2_outputs: { [spec.agentId]: output },
            llm_calls: [llmCall],
          };
        },
        timeoutMs,
        `L2 ${spec.agentId}`,
      );
    } catch (err) {
      if (err instanceof AgentTimeoutError) {
        if (
          isResearchKnobsStageEnabled(
            spec.agentId,
            "agent_run",
            undefined,
            state.active_cohort || "cohort_default",
          ) &&
          !fallbackRuntimeEvidence
        ) {
          throw err;
        }
        const fallback = spec.fallback("", state.layer1_consensus);
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
          stage: "agent_run",
          startedAt,
          structuredAccepted: false,
          claimGraphAccepted: false,
          knobSnapshot: canaryKnobSnapshot,
          knobAudit: null,
          toolStatuses: canaryToolStatuses,
          output,
          validatorIds: [
            `${spec.agentId}.structured_output.v1`,
            "evidence_claim_graph_v1",
            "research_knobs_runtime_v1",
          ],
          forceFallback: true,
        });
        const llmCall = buildLlmCall(spec.agentId, structuredHandle);
        if (canaryEvent) {
          llmCall.prompt_canary_event = canaryEvent;
          await persistPromptReleaseCanaryEvents([canaryEvent]);
        }
        onLog(
          formatAgentEvent("timeout", "L2", spec.agentId, [
            `elapsed=${formatDurationMs(Date.now() - startedAt)}`,
            summarizeAgentOutput(output),
          ]),
        );
        return {
          layer2_outputs: { [spec.agentId]: output },
          llm_calls: [llmCall],
        };
      }
      onLog(
        formatAgentEvent("error", "L2", spec.agentId, [
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
    `Tool plan for this sector agent:\n` +
    `* Round 1: use industry-level evidence only: RKE prior, broker research, policy digest, compact ETF candidate pool, and moneyflow.\n` +
    `* Round 2: verify only 2-3 highest-relevance ETF/research candidates with price/indicator tools.\n` +
    `* Round 3: fill one remaining evidence gap only if needed; do not expand the ticker list.\n` +
    `* Round 4: no more tools; write the final analysis from gathered evidence.\n\n` +
    `ETF holdings are candidate-pool evidence, not a checklist. Do not verify every ETF constituent. ` +
    `Use get_rke_research_context only as report-derived research prior; it ` +
    `does not replace current sector, flow, ETF, policy, price, or indicator ` +
    `confirmation. ` +
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

function buildCurrentToolContract(requiredTools: ReadonlyArray<string>): string {
  return (
    `## Current tool contract\n` +
    `Only call these registered tools: ${requiredTools.join(", ")}.\n` +
    `Do not call older prompt names that are not listed above.\n` +
    `Use get_broker_research for research evidence and get_industry_policy_digest for policy evidence when available.\n` +
    `get_etf_holdings returns a compact candidate pool. Treat ETF constituents as candidates, not as a checklist; ` +
    `verify at most 3 tickers with get_stock_data/get_indicators.`
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
    `When a runtime evidence catalog is present, include claims, top-level claim_refs, ` +
    `and per-pick claim_refs using only its evidence_id and allowed research rule ids. ` +
    lang
  );
}

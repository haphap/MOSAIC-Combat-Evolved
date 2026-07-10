import {
  buildPromptReleaseCanaryEvent,
  type PromptReleaseCanaryBinding,
  type PromptReleaseCanaryEvent,
} from "../../autoresearch/prompt_release_canary_slo.js";
import type { RuntimeAgentStageId } from "../prompts/runtime_agent_spec.js";
import type { DailyCycleStateType } from "../state.js";
import type { ResearchKnobCapAudit, ResearchKnobsSnapshot, ToolStatus } from "./research_knobs.js";

export interface AgentCanaryEventContext {
  release: PromptReleaseCanaryBinding;
  runId: string;
  agentInvocationId: string;
  systemPrompt: string;
}

export function agentCanaryEventContext(opts: {
  release: PromptReleaseCanaryBinding | undefined;
  state: DailyCycleStateType;
  agentInvocationId: string;
  systemPrompt: string;
}): AgentCanaryEventContext | null {
  if (opts.release?.lifecycle_state !== "canary") return null;
  const runId = opts.state.trace_id || opts.state.as_of_date;
  if (!runId) throw new Error("prompt_release_canary_runtime_identity_missing");
  return {
    release: opts.release,
    runId,
    agentInvocationId: opts.agentInvocationId,
    systemPrompt: opts.systemPrompt,
  };
}

export function buildAgentPromptCanaryEvent(opts: {
  context: AgentCanaryEventContext | null;
  agent: string;
  stage: RuntimeAgentStageId;
  startedAt: number;
  observedAt?: string;
  structuredAccepted: boolean;
  claimGraphAccepted: boolean;
  knobSnapshot: ResearchKnobsSnapshot | null;
  knobAudit: ResearchKnobCapAudit | null;
  toolStatuses: ReadonlyArray<ToolStatus>;
  output: unknown;
  validatorIds: ReadonlyArray<string>;
  validatorRejected?: boolean;
  forceFallback?: boolean;
  forceSourceFailure?: boolean;
  exposureBreachCount?: number;
}): PromptReleaseCanaryEvent | null {
  if (!opts.context) return null;
  const runtimeSources = opts.knobSnapshot?.consumptionSnapshot.runtimeSourceStatuses ?? [];
  const sourceFailed =
    Boolean(opts.forceSourceFailure) ||
    opts.toolStatuses.some((status) => status.failed || status.missing) ||
    runtimeSources.some((status) => ["missing", "stale", "source_error"].includes(status.status));
  const fallback =
    Boolean(opts.forceFallback) ||
    !opts.structuredAccepted ||
    !opts.claimGraphAccepted ||
    opts.knobAudit?.output_selection === "deterministic_fallback" ||
    hasRuntimeFallback(opts.output);
  const duplicateOrderIntentCount = duplicateTickerCount(opts.output);
  return buildPromptReleaseCanaryEvent({
    release: opts.context.release,
    runId: opts.context.runId,
    agentInvocationId: opts.context.agentInvocationId,
    agent: opts.agent,
    stage: opts.stage,
    observedAt: opts.observedAt ?? new Date().toISOString(),
    latencyMs: Date.now() - opts.startedAt,
    systemPrompt: opts.context.systemPrompt,
    schemaFailed: !opts.structuredAccepted,
    fallback,
    sourceFailed,
    unsupportedInfluenceRejected: (opts.knobAudit?.unsupported_knob_influence_ids.length ?? 0) > 0,
    validatorRejected: Boolean(opts.validatorRejected) || !opts.claimGraphAccepted,
    validatorIds: opts.validatorIds,
    duplicateOrderIntentCount,
    exposureBreachCount: opts.exposureBreachCount ?? 0,
  });
}

function hasRuntimeFallback(output: unknown): boolean {
  if (!output || typeof output !== "object" || Array.isArray(output)) return true;
  const record = output as Record<string, unknown>;
  if (record.runtime_fallback_audit) return true;
  const knobAudit = record.verified_knob_audit;
  if (knobAudit && typeof knobAudit === "object" && !Array.isArray(knobAudit)) {
    return Boolean((knobAudit as Record<string, unknown>).fallback_reason_code);
  }
  const claimAudit = record.verified_claim_audit;
  if (claimAudit && typeof claimAudit === "object" && !Array.isArray(claimAudit)) {
    return Boolean((claimAudit as Record<string, unknown>).fallback_reason_code);
  }
  return false;
}

function duplicateTickerCount(output: unknown): number {
  if (!output || typeof output !== "object" || Array.isArray(output)) return 0;
  const record = output as Record<string, unknown>;
  for (const field of ["trades", "portfolio_actions"]) {
    const rows = record[field];
    if (!Array.isArray(rows)) continue;
    const seen = new Set<string>();
    let duplicates = 0;
    for (const row of rows) {
      if (!row || typeof row !== "object" || Array.isArray(row)) continue;
      const ticker = (row as Record<string, unknown>).ticker;
      if (typeof ticker !== "string") continue;
      if (seen.has(ticker)) duplicates += 1;
      seen.add(ticker);
    }
    return duplicates;
  }
  return 0;
}

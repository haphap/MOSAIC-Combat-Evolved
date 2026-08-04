import type { RuntimeAgentStageId } from "../prompts/runtime_agent_spec.js";
import { canonicalJsonHash } from "./canonical_json.js";

export interface ToolStatus {
  name: string;
  call_id?: string;
  agent_invocation_id?: string;
  called: boolean;
  failed: boolean;
  missing: boolean;
  fallback: boolean;
  cache_hit: boolean;
  args?: unknown;
  as_of?: string;
  fingerprint?: string;
  args_fingerprint?: string;
  result_fingerprint?: string;
  source_fingerprint?: string;
}

export type RuntimeSourceState =
  | "loaded"
  | "empty_confirmed"
  | "missing"
  | "stale"
  | "source_error";

export interface RuntimeSourceStatus {
  source_id: string;
  scope: string;
  status: RuntimeSourceState;
  as_of?: string;
  snapshot_hash?: string;
  error_code?: string;
  producer_stage?: string;
  resolved_at_stage?: string;
  adapter_id?: string;
}

export interface RuntimeSourceEvidenceObservation {
  source_id: string;
  scope: string;
  metric: string;
  value: unknown;
  unit: string;
  as_of: string;
  lookback: string;
  freshness: "current" | "stale" | "missing" | "fallback" | "tool_failed";
  source_fingerprint: string;
  direction: "positive" | "negative" | "neutral" | "ambiguous";
  privacy_class: "public_structured" | "private_runtime" | "licensed_private";
  adapter_id: string;
  adapter_version: string;
}

export function buildAgentInvocationId(input: {
  runId: string;
  agent: string;
  stage: RuntimeAgentStageId;
  cohort: string;
  asOf: string;
  promptReleaseHash: string;
}): string {
  const digest = canonicalJsonHash({
    schema_version: "agent_invocation_id_v2",
    graph_run_id: input.runId,
    agent: input.agent,
    stage: input.stage,
    cohort: input.cohort,
    as_of: input.asOf,
    prompt_release_hash: input.promptReleaseHash,
  });
  return `agent-invocation:${digest.slice("sha256:".length)}`;
}

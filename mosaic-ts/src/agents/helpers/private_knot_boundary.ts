import { createHash } from "node:crypto";
import type { RuntimeAgentStageId } from "../prompts/runtime_agent_spec.js";

/** Public, value-free boundary for the private KNOT runtime. */
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

export interface PrivateKnotEvidenceBinding {
  evidence_key: string;
  metric: string;
  tool?: string;
  source?: string;
}

export type PrivateKnotInvocationMode =
  | "PRODUCTION"
  | "NON_PRODUCTION_TEST"
  | "NON_PRODUCTION_PREFLIGHT";

export interface PrivateKnotInvocationBinding {
  invocation_mode: PrivateKnotInvocationMode;
  graph_run_id: string;
  agent_invocation_id: string;
  as_of: string;
  execution_behavior_release_id: string;
  prompt_release_id: string;
  prompt_release_hash: string;
  prompt_pair_hash: string;
  prompt_commit: string;
}

export function buildAgentInvocationId(input: {
  runId: string;
  agent: string;
  stage: RuntimeAgentStageId;
  cohort: string;
  asOf: string;
  promptReleaseHash: string;
}): string {
  const digest = canonicalHash({
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

export type PrivateKnotInvocationContext = Omit<
  PrivateKnotInvocationBinding,
  | "agent_invocation_id"
  | "prompt_release_id"
  | "prompt_release_hash"
  | "prompt_pair_hash"
  | "prompt_commit"
>;

export function privateKnotInvocationContextForState(state: {
  trace_id: string;
  as_of_date: string;
  darwinian_runtime_binding?: { execution_behavior_release_id: string } | null;
}): PrivateKnotInvocationContext {
  if (!state.trace_id?.trim()) throw new Error("private_knot_graph_run_id_required");
  if (!state.as_of_date?.trim()) throw new Error("private_knot_as_of_required");
  const productionBinding = state.darwinian_runtime_binding;
  return {
    invocation_mode: productionBinding ? "PRODUCTION" : "NON_PRODUCTION_TEST",
    graph_run_id: state.trace_id,
    as_of: state.as_of_date,
    execution_behavior_release_id: productionBinding
      ? productionBinding.execution_behavior_release_id
      : "non-production-test",
  };
}

/**
 * Safe view returned across the public/private boundary. The private policy,
 * parameter values, mutation targets and evaluation rules remain inside the
 * private adapter and are addressed only by snapshot_id.
 */
export interface PrivateKnotSnapshot extends PrivateKnotInvocationBinding {
  snapshot_id: string;
  snapshot_hash: string;
  agent: string;
  stage: RuntimeAgentStageId;
  cohort: string;
  evidence_bindings: PrivateKnotEvidenceBinding[];
  allowed_research_rule_ids: string[];
  runtime_source_statuses: RuntimeSourceStatus[];
}

export interface PrivateKnotAuditSummary {
  snapshot_hash: string;
  accepted: boolean;
  output_selection: "raw" | "policy_adjusted" | "deterministic_fallback";
  reason_codes: string[];
  tool_status_summary: {
    called: number;
    failed: number;
    missing: number;
    fallback: number;
    cache_hit: number;
  };
  runtime_source_status_summary: {
    loaded: number;
    empty_confirmed: number;
    missing: number;
    stale: number;
    source_error: number;
  };
}

export interface PrivateKnotPolicyResult<T> {
  output: T;
  audit: PrivateKnotAuditSummary;
}

export interface PrivateKnotRuntimeDescriptor {
  knot_runtime_contract_manifest_hash: string;
  private_runtime_manifest_hash: string;
}

export interface PrivateKnotRuntimeAdapter {
  describe(): PrivateKnotRuntimeDescriptor;
  isStageEnabled(agent: string, stage: RuntimeAgentStageId, cohort: string): boolean;
  prepareSnapshot(
    input: PrivateKnotInvocationBinding & {
      agent: string;
      stage: RuntimeAgentStageId;
      cohort: string;
      runtimeSourceStatuses: ReadonlyArray<RuntimeSourceStatus>;
    },
  ): Promise<PrivateKnotSnapshot>;
  applyPolicy<T>(input: {
    snapshot: PrivateKnotSnapshot;
    output: T;
    toolStatuses: ReadonlyArray<ToolStatus>;
  }): PrivateKnotPolicyResult<T>;
}

let activeAdapter: PrivateKnotRuntimeAdapter | null = null;
const issuedSnapshots = new Map<string, { snapshot: PrivateKnotSnapshot; consumed: boolean }>();

export function installPrivateKnotRuntime(adapter: PrivateKnotRuntimeAdapter): void {
  activeAdapter = adapter;
  issuedSnapshots.clear();
}

export function clearPrivateKnotRuntime(): void {
  activeAdapter = null;
  issuedSnapshots.clear();
}

export const clearPrivateKnotRuntimeForTests = clearPrivateKnotRuntime;

export function privateKnotRuntimeInstalled(): boolean {
  return activeAdapter !== null;
}

export function isPrivateKnotStageEnabled(
  agent: string,
  stage: RuntimeAgentStageId,
  cohort: string,
): boolean {
  return activeAdapter?.isStageEnabled(agent, stage, cohort) ?? false;
}

export async function preparePrivateKnotSnapshot(
  input: PrivateKnotInvocationBinding & {
    agent: string;
    stage: RuntimeAgentStageId;
    cohort: string;
    runtimeSourceStatuses: ReadonlyArray<RuntimeSourceStatus>;
  },
): Promise<PrivateKnotSnapshot> {
  if (!activeAdapter) throw new Error("private_knot_runtime_not_initialized");
  validateInvocationBinding(input, input.agent, input.stage, input.cohort);
  const snapshot = await activeAdapter.prepareSnapshot(input);
  validateSnapshot(snapshot, input);
  if (issuedSnapshots.has(snapshot.snapshot_id)) {
    throw new Error("private_knot_snapshot_reissued");
  }
  issuedSnapshots.set(snapshot.snapshot_id, {
    snapshot: structuredClone(snapshot),
    consumed: false,
  });
  return snapshot;
}

export function applyPrivateKnotPolicy<T>(input: {
  snapshot: PrivateKnotSnapshot;
  output: T;
  toolStatuses: ReadonlyArray<ToolStatus>;
}): PrivateKnotPolicyResult<T> {
  if (!activeAdapter) throw new Error("private_knot_runtime_not_initialized");
  const issued = issuedSnapshots.get(input.snapshot.snapshot_id);
  if (!issued) throw new Error("private_knot_snapshot_not_issued");
  if (issued.consumed) throw new Error("private_knot_snapshot_already_consumed");
  issued.consumed = true;
  if (canonicalHash(issued.snapshot) !== canonicalHash(input.snapshot)) {
    throw new Error("private_knot_snapshot_binding_mismatch");
  }
  return activeAdapter.applyPolicy({
    snapshot: input.snapshot,
    output: input.output,
    toolStatuses: input.toolStatuses,
  });
}

function validateSnapshot(
  snapshot: PrivateKnotSnapshot,
  expected: PrivateKnotInvocationBinding & {
    agent: string;
    stage: RuntimeAgentStageId;
    cohort: string;
    runtimeSourceStatuses: ReadonlyArray<RuntimeSourceStatus>;
  },
): void {
  const exactFields = new Set([
    "snapshot_id",
    "snapshot_hash",
    "agent",
    "stage",
    "cohort",
    "invocation_mode",
    "graph_run_id",
    "agent_invocation_id",
    "as_of",
    "execution_behavior_release_id",
    "prompt_release_id",
    "prompt_release_hash",
    "prompt_pair_hash",
    "prompt_commit",
    "evidence_bindings",
    "allowed_research_rule_ids",
    "runtime_source_statuses",
  ]);
  if (
    !snapshot ||
    typeof snapshot !== "object" ||
    Object.keys(snapshot).length !== exactFields.size ||
    Object.keys(snapshot).some((field) => !exactFields.has(field))
  ) {
    throw new Error("private_knot_snapshot_schema_mismatch");
  }
  for (const field of [
    "invocation_mode",
    "graph_run_id",
    "agent_invocation_id",
    "as_of",
    "execution_behavior_release_id",
    "prompt_release_id",
    "prompt_release_hash",
    "prompt_pair_hash",
    "prompt_commit",
  ] as const) {
    if (snapshot[field] !== expected[field]) {
      throw new Error(`private_knot_snapshot_${field}_mismatch`);
    }
  }
  validateInvocationBinding(snapshot, expected.agent, expected.stage, expected.cohort);
  if (
    typeof snapshot.snapshot_id !== "string" ||
    !snapshot.snapshot_id ||
    !isSha256(snapshot.snapshot_hash) ||
    snapshot.snapshot_id !== snapshot.snapshot_hash ||
    !Array.isArray(snapshot.evidence_bindings) ||
    !Array.isArray(snapshot.allowed_research_rule_ids) ||
    !Array.isArray(snapshot.runtime_source_statuses) ||
    canonicalHash(canonicalRuntimeSourceStatuses(snapshot.runtime_source_statuses)) !==
      canonicalHash(canonicalRuntimeSourceStatuses(expected.runtimeSourceStatuses))
  ) {
    throw new Error("private_knot_snapshot_schema_mismatch");
  }
}

function validateInvocationBinding(
  binding: PrivateKnotInvocationBinding,
  agent: string,
  stage: RuntimeAgentStageId,
  cohort: string,
): void {
  for (const value of [
    agent,
    stage,
    cohort,
    binding.graph_run_id,
    binding.agent_invocation_id,
    binding.as_of,
    binding.execution_behavior_release_id,
    binding.prompt_release_id,
    binding.prompt_commit,
  ]) {
    if (typeof value !== "string" || !value.trim()) {
      throw new Error("private_knot_invocation_binding_incomplete");
    }
  }
  if (!isSha256(binding.prompt_release_hash) || !isSha256(binding.prompt_pair_hash)) {
    throw new Error("private_knot_invocation_binding_hash_invalid");
  }
  if (
    binding.agent_invocation_id !==
    buildAgentInvocationId({
      runId: binding.graph_run_id,
      agent,
      stage,
      cohort,
      asOf: binding.as_of,
      promptReleaseHash: binding.prompt_release_hash,
    })
  ) {
    throw new Error("private_knot_agent_invocation_id_mismatch");
  }
  if (
    !["PRODUCTION", "NON_PRODUCTION_TEST", "NON_PRODUCTION_PREFLIGHT"].includes(
      binding.invocation_mode,
    )
  ) {
    throw new Error("private_knot_invocation_mode_invalid");
  }
  if (binding.invocation_mode === "PRODUCTION" && !/^[0-9a-f]{40}$/.test(binding.prompt_commit)) {
    throw new Error("private_knot_production_prompt_commit_invalid");
  }
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
}

function canonicalRuntimeSourceStatuses(
  statuses: ReadonlyArray<RuntimeSourceStatus>,
): RuntimeSourceStatus[] {
  return statuses
    .map((status) => structuredClone(status))
    .sort((left, right) => canonicalJson(left).localeCompare(canonicalJson(right)));
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256").update(canonicalJson(value)).digest("hex")}`;
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, canonicalize(nested)]),
    );
  }
  return value;
}

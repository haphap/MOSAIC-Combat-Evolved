import type { RuntimeAgentStageId } from "../prompts/runtime_agent_spec.js";
import { canonicalJson, canonicalJsonHash } from "./canonical_json.js";

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

export interface PrivateKnotFrozenInitialToolResult {
  tool_name: string;
  tool_call_id: string;
  agent_invocation_id: string;
  args: Record<string, unknown>;
  payload: unknown;
  args_fingerprint: string;
  result_fingerprint: string;
  source_fingerprint: string;
  as_of: string;
  status: "CURRENT" | "FALLBACK" | "MISSING" | "TOOL_FAILED";
}

export interface KnotDerivedEconomicFeatureEnvelope {
  schema_version: "knot_derived_economic_feature_v1";
  public_feature_id: string;
  observation_period: string;
  as_of: string;
  value: number | string;
  unit: string;
  evidence_refs: string[];
  pit_status: "PIT_VERIFIED";
}

export interface PrivateKnotModelContextResult {
  context: KnotDerivedEconomicFeatureEnvelope[];
  context_hash: string;
  audit: {
    snapshot_hash: string;
    disposition: "APPLIED" | "NOT_TRIGGERED" | "NOT_APPLICABLE";
    envelope_hashes: string[];
  };
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
  prepareModelContext(input: {
    snapshot: PrivateKnotSnapshot;
    initialToolResults: ReadonlyArray<PrivateKnotFrozenInitialToolResult>;
  }): Promise<PrivateKnotModelContextResult>;
  applyPolicy<T>(input: {
    snapshot: PrivateKnotSnapshot;
    output: T;
    toolStatuses: ReadonlyArray<ToolStatus>;
  }): PrivateKnotPolicyResult<T>;
  finalize(snapshot: PrivateKnotSnapshot): void;
}

let activeAdapter: PrivateKnotRuntimeAdapter | null = null;
const issuedSnapshots = new Map<
  string,
  { snapshot: PrivateKnotSnapshot; contextConsumed: boolean; policyConsumed: boolean }
>();

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
    contextConsumed: false,
    policyConsumed: false,
  });
  return snapshot;
}

export async function preparePrivateKnotModelContext(input: {
  snapshot: PrivateKnotSnapshot;
  initialToolResults: ReadonlyArray<PrivateKnotFrozenInitialToolResult>;
}): Promise<PrivateKnotModelContextResult> {
  if (!activeAdapter) throw new Error("private_knot_runtime_not_initialized");
  const issued = issuedSnapshots.get(input.snapshot.snapshot_id);
  if (!issued) throw new Error("private_knot_snapshot_not_issued");
  if (issued.contextConsumed) throw new Error("private_knot_model_context_already_consumed");
  if (issued.policyConsumed) throw new Error("private_knot_model_context_out_of_order");
  issued.contextConsumed = true;
  assertPresentedSnapshot(issued.snapshot, input.snapshot);
  validateFrozenInitialToolResults(input.initialToolResults, input.snapshot);
  const result = await activeAdapter.prepareModelContext({
    snapshot: input.snapshot,
    initialToolResults: input.initialToolResults,
  });
  validateModelContextResult(result, input.snapshot);
  return result;
}

export function applyPrivateKnotPolicy<T>(input: {
  snapshot: PrivateKnotSnapshot;
  output: T;
  toolStatuses: ReadonlyArray<ToolStatus>;
}): PrivateKnotPolicyResult<T> {
  if (!activeAdapter) throw new Error("private_knot_runtime_not_initialized");
  const issued = issuedSnapshots.get(input.snapshot.snapshot_id);
  if (!issued) throw new Error("private_knot_snapshot_not_issued");
  if (!issued.contextConsumed) throw new Error("private_knot_policy_before_model_context");
  if (issued.policyConsumed) throw new Error("private_knot_snapshot_already_consumed");
  issued.policyConsumed = true;
  assertPresentedSnapshot(issued.snapshot, input.snapshot);
  try {
    return activeAdapter.applyPolicy({
      snapshot: input.snapshot,
      output: input.output,
      toolStatuses: input.toolStatuses,
    });
  } finally {
    issuedSnapshots.delete(input.snapshot.snapshot_id);
  }
}

export function finalizePrivateKnotSnapshot(snapshot: PrivateKnotSnapshot): void {
  const issued = issuedSnapshots.get(snapshot.snapshot_id);
  if (!issued) return;
  assertPresentedSnapshot(issued.snapshot, snapshot);
  issuedSnapshots.delete(snapshot.snapshot_id);
  activeAdapter?.finalize(snapshot);
}

function assertPresentedSnapshot(
  expected: PrivateKnotSnapshot,
  presented: PrivateKnotSnapshot,
): void {
  if (canonicalHash(expected) !== canonicalHash(presented)) {
    throw new Error("private_knot_snapshot_binding_mismatch");
  }
}

const PUBLIC_MODEL_CONTEXT_FEATURES: Readonly<Record<string, ReadonlySet<string>>> = {
  china: new Set(["china.activity.composite_observation"]),
  central_bank: new Set(["pboc.liquidity.composite_observation"]),
};

function validateFrozenInitialToolResults(
  results: ReadonlyArray<PrivateKnotFrozenInitialToolResult>,
  snapshot: PrivateKnotSnapshot,
): void {
  if (results.length === 0) {
    if (snapshot.agent === "china" || snapshot.agent === "central_bank") {
      throw new Error("private_knot_initial_tool_result_required");
    }
    return;
  }
  const seen = new Set<string>();
  for (const result of results) {
    if (
      !result ||
      typeof result !== "object" ||
      !result.tool_name?.trim() ||
      !result.tool_call_id?.trim() ||
      result.agent_invocation_id !== snapshot.agent_invocation_id ||
      !isSha256(result.args_fingerprint) ||
      !isSha256(result.result_fingerprint) ||
      !isSha256(result.source_fingerprint) ||
      !result.as_of?.trim() ||
      !["CURRENT", "FALLBACK", "MISSING", "TOOL_FAILED"].includes(result.status) ||
      !result.args ||
      typeof result.args !== "object" ||
      Array.isArray(result.args)
    ) {
      throw new Error("private_knot_initial_tool_result_schema_mismatch");
    }
    if (seen.has(result.tool_call_id)) {
      throw new Error("private_knot_initial_tool_result_duplicate");
    }
    seen.add(result.tool_call_id);
  }
}

function validateModelContextResult(
  result: PrivateKnotModelContextResult,
  snapshot: PrivateKnotSnapshot,
): void {
  if (
    !result ||
    typeof result !== "object" ||
    !Array.isArray(result.context) ||
    !isSha256(result.context_hash) ||
    result.audit?.snapshot_hash !== snapshot.snapshot_hash ||
    !["APPLIED", "NOT_TRIGGERED", "NOT_APPLICABLE"].includes(result.audit?.disposition) ||
    !Array.isArray(result.audit?.envelope_hashes)
  ) {
    throw new Error("private_knot_model_context_schema_mismatch");
  }
  const allowed = PUBLIC_MODEL_CONTEXT_FEATURES[snapshot.agent] ?? new Set<string>();
  const envelopeHashes: string[] = [];
  for (const envelope of result.context) {
    if (
      envelope.schema_version !== "knot_derived_economic_feature_v1" ||
      !allowed.has(envelope.public_feature_id) ||
      !envelope.observation_period?.trim() ||
      !envelope.as_of?.trim() ||
      (typeof envelope.value !== "number" && typeof envelope.value !== "string") ||
      (typeof envelope.value === "number" && !Number.isFinite(envelope.value)) ||
      !envelope.unit?.trim() ||
      !Array.isArray(envelope.evidence_refs) ||
      envelope.evidence_refs.length === 0 ||
      envelope.evidence_refs.some((reference) => !isSha256(reference)) ||
      envelope.pit_status !== "PIT_VERIFIED"
    ) {
      throw new Error("private_knot_model_context_envelope_invalid");
    }
    envelopeHashes.push(canonicalHash(envelope));
  }
  if (
    canonicalHash({
      schema_version: "private_knot_model_context_v1",
      snapshot_hash: snapshot.snapshot_hash,
      context: result.context,
    }) !== result.context_hash ||
    canonicalHash(envelopeHashes) !== canonicalHash(result.audit.envelope_hashes) ||
    (result.audit.disposition === "APPLIED") !== result.context.length > 0
  ) {
    throw new Error("private_knot_model_context_hash_mismatch");
  }
  const serialized = JSON.stringify(result.context).toLowerCase();
  if (
    [
      "mutation_target",
      "confidence_cap",
      "threshold",
      "lookback",
      "candidate",
      "champion",
      "prediction_targets",
      "research_knobs",
    ].some((marker) => serialized.includes(marker))
  ) {
    throw new Error("private_knot_model_context_private_content");
  }
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
    .sort((left, right) => compareCanonicalJson(left, right));
}

function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
}

function compareCanonicalJson(left: unknown, right: unknown): number {
  const leftJson = canonicalJson(left);
  const rightJson = canonicalJson(right);
  return leftJson < rightJson ? -1 : leftJson > rightJson ? 1 : 0;
}

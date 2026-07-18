import { createHash } from "node:crypto";
import type { ClaimEvidenceGraph } from "./evidence_contract.js";
import type { EvidenceLineageEnvelope } from "./helpers/causal_evidence_resolution.js";
import type { DailyCycleStateType } from "./state.js";
import type { AgentId } from "./tool_contract.js";

export const ACCEPTED_OUTPUT_KINDS = [
  "MACRO_TRANSMISSION",
  "STANDARD_SECTOR_SELECTION",
  "RELATIONSHIP_GRAPH",
  "SUPERINVESTOR_SELECTION",
  "CRO_RISK_REVIEW",
  "ALPHA_DISCOVERY",
  "EXECUTION_ASSESSMENT",
  "CIO_PROPOSAL",
  "CIO_FINAL",
] as const;

export type AcceptedOutputKind = (typeof ACCEPTED_OUTPUT_KINDS)[number];

export type OutcomeSampleOrigin =
  | "PRODUCTION_ACTIVE"
  | "KNOT_RESEARCH_SHADOW"
  | "KNOT_POST_PROMOTION_CHAMPION_SHADOW";

export type AcceptedOutputAgentByKind = {
  MACRO_TRANSMISSION:
    | "china"
    | "us_economy"
    | "eu_economy"
    | "central_bank"
    | "us_financial_conditions"
    | "euro_area_financial_conditions"
    | "commodities"
    | "geopolitical"
    | "market_breadth"
    | "institutional_flow";
  STANDARD_SECTOR_SELECTION:
    | "semiconductor"
    | "technology"
    | "energy"
    | "biotech"
    | "consumer"
    | "industrials"
    | "real_estate_construction"
    | "financials"
    | "agriculture";
  RELATIONSHIP_GRAPH: "relationship_mapper";
  SUPERINVESTOR_SELECTION: "druckenmiller" | "munger" | "burry" | "ackman";
  CRO_RISK_REVIEW: "cro";
  ALPHA_DISCOVERY: "alpha_discovery";
  EXECUTION_ASSESSMENT: "autonomous_execution";
  CIO_PROPOSAL: "cio";
  CIO_FINAL: "cio";
};

export interface AcceptedOutputRecordRef<K extends AcceptedOutputKind = AcceptedOutputKind> {
  accepted_output_kind: K;
  agent_id: AcceptedOutputAgentByKind[K];
  accepted_output_id: string;
  accepted_output_hash: string;
}

/** Namespace-safe state key. CIO has two accepted phases, so agent id alone is insufficient. */
export function acceptedOutputRefKey<K extends AcceptedOutputKind>(
  kind: K,
  agentId: AcceptedOutputAgentByKind[K],
): string {
  return `${kind}:${agentId}`;
}

export interface AcceptedAgentOutputRecordBase {
  accepted_output_id: string;
  accepted_output_hash: string;
  graph_run_id: string;
  run_id: string;
  run_slot_id: string;
  operational_opportunity_audit_id: string;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  track_key_hash: string;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string | null;
  reliability_adapter_contract_version: string | null;
  confidence_semantics_contract_version: string | null;
  as_of: string;
  accepted_at: string;
}

export type AcceptedOutputRunBinding =
  | {
      sample_origin: "PRODUCTION_ACTIVE";
      run_slot_kind: "OUTCOME_SCHEDULED";
      scheduled_sample_id: string;
    }
  | {
      sample_origin: "PRODUCTION_ACTIVE";
      run_slot_kind: "DOWNSTREAM_ONLY";
      scheduled_sample_id: null;
    }
  | {
      sample_origin: Exclude<OutcomeSampleOrigin, "PRODUCTION_ACTIVE">;
      run_slot_kind: "OUTCOME_SCHEDULED";
      scheduled_sample_id: string;
    }
  | {
      sample_origin: "KNOT_CONTROL_SHADOW";
      run_slot_kind: "DOWNSTREAM_ONLY";
      scheduled_sample_id: null;
    };

export type AcceptedAgentOutputRecord<
  K extends AcceptedOutputKind = AcceptedOutputKind,
  TPayload = unknown,
> = AcceptedAgentOutputRecordBase &
  AcceptedOutputRunBinding & {
    accepted_output_kind: K;
    agent_id: AcceptedOutputAgentByKind[K];
    output: EvidenceLineageEnvelope<TPayload>;
  };

export interface AcceptedOutputBuildContext {
  graph_run_id: string;
  run_id: string;
  run_slot_id: string;
  operational_opportunity_audit_id: string;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  track_key_hash: string;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string | null;
  reliability_adapter_contract_version: string | null;
  confidence_semantics_contract_version: string | null;
  as_of: string;
  accepted_at: string;
  run_binding: AcceptedOutputRunBinding;
}

export function acceptedOutputBuildContextFromState(input: {
  state: DailyCycleStateType;
  agentId: AgentId;
  sourceAgentRunId: string;
}): AcceptedOutputBuildContext {
  const binding = input.state.darwinian_runtime_binding;
  const weightSnapshot = input.state.darwinian_weight_snapshot;
  const schedule = input.state.outcome_schedule_plan;
  if (!binding || !weightSnapshot || !schedule) {
    throw new Error(`${input.agentId}: production accepted-output context is unavailable`);
  }
  if (
    schedule.graph_run_id !== input.state.trace_id ||
    schedule.cohort_id !== binding.cohort_id ||
    schedule.language !== binding.language ||
    schedule.production_variant_roster_id !== binding.production_variant_roster_id ||
    schedule.production_variant_roster_revision_id !==
      weightSnapshot.production_variant_roster_revision_id ||
    schedule.execution_behavior_release_id !== binding.execution_behavior_release_id
  ) {
    throw new Error(`${input.agentId}: accepted-output production binding mismatch`);
  }
  const slots = schedule.slots.filter((slot) => slot.agent_id === input.agentId);
  if (slots.length !== 1) {
    throw new Error(`${input.agentId}: accepted output requires exactly one run slot`);
  }
  const slot = slots[0];
  if (!slot) throw new Error(`${input.agentId}: accepted output run slot is unavailable`);
  const behavior = binding.agent_behavior_bindings[input.agentId];
  if (!behavior)
    throw new Error(`${input.agentId}: accepted output behavior binding is unavailable`);
  const runBinding: AcceptedOutputRunBinding =
    slot.run_slot_kind === "OUTCOME_SCHEDULED"
      ? {
          sample_origin: "PRODUCTION_ACTIVE",
          run_slot_kind: "OUTCOME_SCHEDULED",
          scheduled_sample_id: requiredText(slot.scheduled_sample_id ?? "", "scheduled_sample_id"),
        }
      : {
          sample_origin: "PRODUCTION_ACTIVE",
          run_slot_kind: "DOWNSTREAM_ONLY",
          scheduled_sample_id: null,
        };
  return {
    graph_run_id: schedule.graph_run_id,
    run_id: requiredText(input.sourceAgentRunId, "sourceAgentRunId"),
    run_slot_id: slot.run_slot_id,
    operational_opportunity_audit_id: deterministicId("operational-opportunity", {
      graph_run_id: schedule.graph_run_id,
      agent_id: input.agentId,
      run_slot_id: slot.run_slot_id,
    }),
    production_variant_roster_id: binding.production_variant_roster_id,
    production_variant_roster_revision_id: weightSnapshot.production_variant_roster_revision_id,
    execution_behavior_release_id: binding.execution_behavior_release_id,
    cohort_id: binding.cohort_id,
    language: binding.language,
    track_key_hash: slot.track_key_hash,
    agent_contract_version: behavior.agent_contract_version,
    prompt_behavior_version: behavior.prompt_behavior_version,
    execution_behavior_version: behavior.execution_behavior_version,
    component_weight_contract_version: behavior.component_weight_contract_version,
    reliability_adapter_contract_version: behavior.reliability_adapter_contract_version,
    confidence_semantics_contract_version: behavior.confidence_semantics_contract_version,
    as_of: schedule.as_of,
    accepted_at: binding.effective_at,
    run_binding: runBinding,
  };
}

export function buildAcceptedAgentOutputRecord<K extends AcceptedOutputKind, TPayload>(input: {
  kind: K;
  agentId: AcceptedOutputAgentByKind[K];
  payload: TPayload;
  evidenceBundleIds: readonly [string, ...string[]];
  causalDedupeKeys: readonly [string, ...string[]];
  context: AcceptedOutputBuildContext;
}): AcceptedAgentOutputRecord<K, TPayload> {
  validateOwner(input.kind, input.agentId);
  validateBuildContext(input.context);
  const evidenceBundleIds = sortedNonEmptyUnique(input.evidenceBundleIds, "evidence bundle");
  const causalDedupeKeys = sortedNonEmptyUnique(input.causalDedupeKeys, "causal dedupe key");
  const acceptedOutputId = deterministicId("accepted-output", {
    graph_run_id: input.context.graph_run_id,
    run_slot_id: input.context.run_slot_id,
    accepted_output_kind: input.kind,
  });
  const withoutHash = {
    accepted_output_id: acceptedOutputId,
    graph_run_id: requiredText(input.context.graph_run_id, "graph_run_id"),
    run_id: requiredText(input.context.run_id, "run_id"),
    run_slot_id: requiredText(input.context.run_slot_id, "run_slot_id"),
    operational_opportunity_audit_id: requiredText(
      input.context.operational_opportunity_audit_id,
      "operational_opportunity_audit_id",
    ),
    production_variant_roster_id: requiredText(
      input.context.production_variant_roster_id,
      "production_variant_roster_id",
    ),
    production_variant_roster_revision_id: requiredText(
      input.context.production_variant_roster_revision_id,
      "production_variant_roster_revision_id",
    ),
    execution_behavior_release_id: requiredText(
      input.context.execution_behavior_release_id,
      "execution_behavior_release_id",
    ),
    cohort_id: requiredText(input.context.cohort_id, "cohort_id"),
    language: input.context.language,
    track_key_hash: requiredText(input.context.track_key_hash, "track_key_hash"),
    agent_id: input.agentId,
    accepted_output_kind: input.kind,
    ...input.context.run_binding,
    agent_contract_version: requiredText(
      input.context.agent_contract_version,
      "agent_contract_version",
    ),
    prompt_behavior_version: requiredText(
      input.context.prompt_behavior_version,
      "prompt_behavior_version",
    ),
    execution_behavior_version: requiredText(
      input.context.execution_behavior_version,
      "execution_behavior_version",
    ),
    component_weight_contract_version: optionalContractVersion(
      input.context.component_weight_contract_version,
      "component_weight_contract_version",
    ),
    reliability_adapter_contract_version: optionalContractVersion(
      input.context.reliability_adapter_contract_version,
      "reliability_adapter_contract_version",
    ),
    confidence_semantics_contract_version: optionalContractVersion(
      input.context.confidence_semantics_contract_version,
      "confidence_semantics_contract_version",
    ),
    as_of: requiredText(input.context.as_of, "as_of"),
    accepted_at: requiredText(input.context.accepted_at, "accepted_at"),
    output: {
      payload: input.payload,
      evidence_bundle_ids: evidenceBundleIds,
      causal_dedupe_keys: causalDedupeKeys,
    },
  };
  return {
    ...withoutHash,
    accepted_output_hash: canonicalHash(withoutHash),
  } as AcceptedAgentOutputRecord<K, TPayload>;
}

export function acceptedOutputRecordRef<K extends AcceptedOutputKind>(
  record: AcceptedAgentOutputRecord<K>,
): AcceptedOutputRecordRef<K> {
  return {
    accepted_output_kind: record.accepted_output_kind,
    agent_id: record.agent_id,
    accepted_output_id: record.accepted_output_id,
    accepted_output_hash: record.accepted_output_hash,
  };
}

export class AcceptedAgentOutputStore {
  readonly #records = new Map<string, AcceptedAgentOutputRecord>();
  readonly #claimGraphs = new Map<string, ClaimEvidenceGraph>();

  put<K extends AcceptedOutputKind, TPayload>(
    record: AcceptedAgentOutputRecord<K, TPayload>,
    claimGraph?: ClaimEvidenceGraph,
  ): AcceptedOutputRecordRef<K> {
    validateAcceptedAgentOutputRecord(record);
    if (claimGraph) validateAcceptedOutputClaimGraph(record, claimGraph);
    const existing = this.#records.get(record.accepted_output_id);
    if (existing && existing.accepted_output_hash !== record.accepted_output_hash) {
      throw new Error(`accepted output retry changed payload: ${record.accepted_output_id}`);
    }
    const existingGraph = this.#claimGraphs.get(record.accepted_output_id);
    if (existingGraph && claimGraph && canonicalHash(existingGraph) !== canonicalHash(claimGraph)) {
      throw new Error(`accepted output retry changed claim lineage: ${record.accepted_output_id}`);
    }
    this.#records.set(record.accepted_output_id, record as AcceptedAgentOutputRecord);
    if (claimGraph) this.#claimGraphs.set(record.accepted_output_id, structuredClone(claimGraph));
    return acceptedOutputRecordRef(record);
  }

  resolve<K extends AcceptedOutputKind, TPayload = unknown>(
    ref: AcceptedOutputRecordRef<K>,
  ): AcceptedAgentOutputRecord<K, TPayload> {
    const record = this.#records.get(ref.accepted_output_id);
    if (!record) throw new Error(`accepted output is unavailable: ${ref.accepted_output_id}`);
    if (
      record.accepted_output_hash !== ref.accepted_output_hash ||
      record.accepted_output_kind !== ref.accepted_output_kind ||
      record.agent_id !== ref.agent_id
    ) {
      throw new Error(`accepted output reference mismatch: ${ref.accepted_output_id}`);
    }
    validateAcceptedAgentOutputRecord(record);
    return record as AcceptedAgentOutputRecord<K, TPayload>;
  }

  records(): AcceptedAgentOutputRecord[] {
    return [...this.#records.values()].sort((left, right) =>
      left.accepted_output_id.localeCompare(right.accepted_output_id),
    );
  }

  resolveClaimGraph<K extends AcceptedOutputKind>(
    ref: AcceptedOutputRecordRef<K>,
  ): ClaimEvidenceGraph {
    this.resolve(ref);
    const graph = this.#claimGraphs.get(ref.accepted_output_id);
    if (!graph) {
      throw new Error(`accepted output claim lineage is unavailable: ${ref.accepted_output_id}`);
    }
    return structuredClone(graph);
  }
}

function validateAcceptedOutputClaimGraph(
  record: AcceptedAgentOutputRecord,
  graph: ClaimEvidenceGraph,
): void {
  if (graph.run_id !== record.graph_run_id) {
    throw new Error(
      `accepted output claim lineage graph-run mismatch: ${record.accepted_output_id}`,
    );
  }
  const expectedBundleId = `evidence-bundle:${graph.run_id}:${graph.snapshot_hash.slice(7)}`;
  if (!record.output.evidence_bundle_ids.includes(expectedBundleId)) {
    throw new Error(`accepted output claim lineage bundle mismatch: ${record.accepted_output_id}`);
  }
  const graphKeys = [
    ...new Set(graph.evidence_ledger.map((entry) => entry.source_fingerprint)),
  ].sort((left, right) => left.localeCompare(right));
  if (graphKeys.length === 0) {
    throw new Error(`accepted output claim lineage is empty: ${record.accepted_output_id}`);
  }
  if (graphKeys.join("\0") !== record.output.causal_dedupe_keys.join("\0")) {
    throw new Error(
      `accepted output claim lineage causal-key mismatch: ${record.accepted_output_id}`,
    );
  }
}

export function validateAcceptedAgentOutputRecord(record: AcceptedAgentOutputRecord): void {
  validateOwner(record.accepted_output_kind, record.agent_id);
  validateRunBinding(record);
  const { accepted_output_hash: suppliedHash, ...withoutHash } = record;
  if (canonicalHash(withoutHash) !== suppliedHash) {
    throw new Error(`accepted output hash mismatch: ${record.accepted_output_id}`);
  }
  const expectedId = deterministicId("accepted-output", {
    graph_run_id: record.graph_run_id,
    run_slot_id: record.run_slot_id,
    accepted_output_kind: record.accepted_output_kind,
  });
  if (record.accepted_output_id !== expectedId) {
    throw new Error(`accepted output ID mismatch: ${record.accepted_output_id}`);
  }
  sortedNonEmptyUnique(record.output.evidence_bundle_ids, "evidence bundle");
  sortedNonEmptyUnique(record.output.causal_dedupe_keys, "causal dedupe key");
}

function validateOwner<K extends AcceptedOutputKind>(
  kind: K,
  agentId: AgentId | AcceptedOutputAgentByKind[K],
): void {
  const valid =
    kind === "MACRO_TRANSMISSION"
      ? [
          "china",
          "us_economy",
          "eu_economy",
          "central_bank",
          "us_financial_conditions",
          "euro_area_financial_conditions",
          "commodities",
          "geopolitical",
          "market_breadth",
          "institutional_flow",
        ].includes(agentId)
      : kind === "STANDARD_SECTOR_SELECTION"
        ? [
            "semiconductor",
            "technology",
            "energy",
            "biotech",
            "consumer",
            "industrials",
            "real_estate_construction",
            "financials",
            "agriculture",
          ].includes(agentId)
        : OWNER_BY_SINGLE_KIND[kind] === agentId ||
          (kind === "SUPERINVESTOR_SELECTION" &&
            ["druckenmiller", "munger", "burry", "ackman"].includes(agentId));
  if (!valid) throw new Error(`${kind} cannot be owned by ${agentId}`);
}

const OWNER_BY_SINGLE_KIND: Partial<Record<AcceptedOutputKind, AgentId>> = {
  RELATIONSHIP_GRAPH: "relationship_mapper",
  CRO_RISK_REVIEW: "cro",
  ALPHA_DISCOVERY: "alpha_discovery",
  EXECUTION_ASSESSMENT: "autonomous_execution",
  CIO_PROPOSAL: "cio",
  CIO_FINAL: "cio",
};

function validateBuildContext(context: AcceptedOutputBuildContext): void {
  if (!(["en", "zh"] as const).includes(context.language)) {
    throw new Error("accepted output language must be en or zh");
  }
  validateRunBinding(context.run_binding);
}

function optionalContractVersion(value: string | null, label: string): string | null {
  return value === null ? null : requiredText(value, label);
}

function validateRunBinding(binding: AcceptedOutputRunBinding): void {
  if (binding.run_slot_kind === "OUTCOME_SCHEDULED") {
    requiredText(binding.scheduled_sample_id, "scheduled_sample_id");
    return;
  }
  if (binding.scheduled_sample_id !== null) {
    throw new Error("DOWNSTREAM_ONLY requires scheduled_sample_id=null");
  }
  if (
    binding.sample_origin !== "PRODUCTION_ACTIVE" &&
    binding.sample_origin !== "KNOT_CONTROL_SHADOW"
  ) {
    throw new Error("research and post-promotion shadows must be outcome scheduled");
  }
}

function sortedNonEmptyUnique<T extends string>(
  values: readonly [T, ...T[]],
  label: string,
): [T, ...T[]] {
  if (values.some((value) => !value.trim())) throw new Error(`${label} must be non-empty`);
  const sorted = [...new Set(values)].sort((left, right) => left.localeCompare(right));
  if (sorted.length !== values.length) throw new Error(`${label} values must be unique`);
  return sorted as [T, ...T[]];
}

function requiredText(value: string, label: string): string {
  if (!value.trim()) throw new Error(`${label} must be non-empty`);
  return value.trim();
}

function deterministicId(namespace: string, value: unknown): string {
  return `${namespace}:${canonicalHash(value).slice("sha256:".length)}`;
}

export function canonicalAcceptedOutputHash(value: unknown): string {
  return canonicalHash(value);
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

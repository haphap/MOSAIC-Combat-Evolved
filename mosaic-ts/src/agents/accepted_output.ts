import {
  type CapabilityTrack,
  loadCurrentAcceptedOutputCapabilityTrack,
  validateAcceptedOutputCapabilityTrack,
  validateCurrentAcceptedOutputCapabilityTrack,
} from "../autoresearch/capability_preservation_contract.js";
import type { ClaimEvidenceGraph } from "./evidence_contract.js";
import { canonicalJsonHash } from "./helpers/canonical_json.js";
import type { EvidenceLineageEnvelope } from "./helpers/causal_evidence_resolution.js";
import { MACRO_CONTEXT_SOURCE_ROLES } from "./macro/_contracts.js";
import type { DailyCycleStateType, OutcomeRuntimeAuthorityBinding } from "./state.js";
import type { AgentId } from "./tool_contract.js";
import type { MacroComponentCompositionAudit } from "./types.js";

export const ACCEPTED_OUTPUT_KINDS = [
  "MACRO_TRANSMISSION",
  "STANDARD_SECTOR_SELECTION",
  "SUPERINVESTOR_SELECTION",
  "CRO_RISK_REVIEW",
  "ALPHA_DISCOVERY",
  "EXECUTION_ASSESSMENT",
  "CIO_PROPOSAL",
  "CIO_FINAL",
] as const;

export type AcceptedOutputKind = (typeof ACCEPTED_OUTPUT_KINDS)[number];

export type OutcomeSampleOrigin = "PRODUCTION_ACTIVE";

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

export function structuredSmokeFixtureBundleHash(): string | null {
  const bypass = process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS;
  const bundleHash = process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH;
  if (bypass === undefined && bundleHash === undefined) return null;
  if (bypass !== "structured_smoke" || !/^sha256:[0-9a-f]{64}$/.test(bundleHash ?? "")) {
    throw new Error("structured-smoke accepted-output binding is incomplete");
  }
  return bundleHash as string;
}

export function buildStructuredSmokeAcceptedOutputRef<K extends AcceptedOutputKind>(input: {
  kind: K;
  agentId: AcceptedOutputAgentByKind[K];
  payload: unknown;
  state: DailyCycleStateType;
}): AcceptedOutputRecordRef<K> | null {
  const fixtureBundleHash = structuredSmokeFixtureBundleHash();
  if (!fixtureBundleHash) return null;
  validateOwner(input.kind, input.agentId);
  const identity = {
    schema_version: "structured_smoke_accepted_output_ref_v1",
    fixture_bundle_hash: fixtureBundleHash,
    graph_run_id: requiredText(input.state.trace_id, "graph_run_id"),
    as_of: requiredText(input.state.as_of_date, "as_of"),
    accepted_output_kind: input.kind,
    agent_id: input.agentId,
    payload_hash: canonicalHash(input.payload),
  };
  const acceptedOutputId = deterministicId("structured-smoke-accepted-output", identity);
  return {
    accepted_output_kind: input.kind,
    agent_id: input.agentId,
    accepted_output_id: acceptedOutputId,
    accepted_output_hash: canonicalHash({ ...identity, accepted_output_id: acceptedOutputId }),
  };
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
  capability_track?: CapabilityTrack;
  as_of: string;
  accepted_at: string;
  evaluation_opportunity_set_id: string | null;
  evaluation_opportunity_set_hash: string | null;
  frozen_object_set_id: string | null;
  frozen_object_set_hash: string | null;
  adapter_lineage: AcceptedOutputAdapterLineage;
  runtime_opportunity_authority?: OutcomeRuntimeAuthorityBinding;
  /** Runtime-owned audit material. Consumers must read only output.payload. */
  runtime_audit?: {
    macro_component_composition: MacroComponentCompositionAudit;
  };
  knot_capture_v2?: AcceptedKnotCaptureV2;
}

export interface AcceptedClaimGraphLineage {
  schema_version: "accepted_claim_graph_lineage_v1";
  run_id: string;
  snapshot_hash: string;
  evidence: Array<{ evidence_id: string; source_fingerprint: string }>;
  claims: Array<{ claim_id: string; evidence_ids: string[] }>;
  claim_graph_lineage_hash: string;
}

export interface AcceptedKnotCaptureV2 {
  schema_version: "accepted_knot_capture_v2";
  accepted_lineage_evaluator_version: "accepted_claim_lineage_v3";
  eligibility: "ELIGIBLE" | "INELIGIBLE";
  ineligibility_reasons: string[];
  accepted_claim_graph_hash: string;
  tool_environment_hash: string | null;
  execution_behavior_release_hash: string | null;
  capability_bundle_hash: string | null;
  knot_coverage_manifest_v2_hash: string | null;
  knot_audit_capability_track_v2_hash: string | null;
  result_event_refs: Array<{
    result_event_id: string;
    result_event_hash: string;
    result_authority_type: "SNAPSHOT_BUILD" | "FROZEN_QUERY";
    result_authority_hash: string;
    evidence_ids: string[];
    binding_result_refs: Array<{
      binding_id: string;
      binding_result_fingerprint: string;
    }>;
  }>;
  claim_specs: Array<{
    claim_id: string;
    evidence_ids: string[];
    structured_conclusion: Record<string, string | number | boolean | null>;
    claim_spec_hash: string;
  }>;
  capture_hash: string;
}

export interface AcceptedOutputAdapterLineage {
  schema_version: "accepted_output_adapter_lineage_v1";
  adapter_contract_version: "accepted_output_adapter_v1";
  agent_id: AgentId;
  accepted_output_kind: AcceptedOutputKind;
  source_agent_output_hash: string;
  accepted_payload_hash: string;
  claim_graph_lineage_hash: string;
  adapter_lineage_hash: string;
}

export interface AcceptedEvidenceLineageEnvelope<TPayload>
  extends EvidenceLineageEnvelope<TPayload> {
  claim_graph_lineage: AcceptedClaimGraphLineage;
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
    };

export type AcceptedAgentOutputRecord<
  K extends AcceptedOutputKind = AcceptedOutputKind,
  TPayload = unknown,
> = AcceptedAgentOutputRecordBase &
  AcceptedOutputRunBinding & {
    accepted_output_kind: K;
    agent_id: AcceptedOutputAgentByKind[K];
    output: AcceptedEvidenceLineageEnvelope<TPayload>;
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
  evaluation_binding?: {
    evaluation_opportunity_set_id: string;
    evaluation_opportunity_set_hash: string;
    frozen_object_set_id: string | null;
    frozen_object_set_hash: string | null;
    runtime_authority_binding?: OutcomeRuntimeAuthorityBinding;
  } | null;
}

export function acceptedOutputBuildContextFromState(input: {
  state: DailyCycleStateType;
  agentId: AgentId;
  sourceAgentRunId: string;
  acceptedOutputKind: AcceptedOutputKind;
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
  const isEvaluationObject = input.acceptedOutputKind !== "CIO_PROPOSAL";
  const opportunityBinding = input.state.outcome_opportunity_bindings[input.agentId];
  const evaluationBinding =
    slot.run_slot_kind === "OUTCOME_SCHEDULED" && isEvaluationObject ? opportunityBinding : null;
  if (
    slot.run_slot_kind === "OUTCOME_SCHEDULED" &&
    isEvaluationObject &&
    (!evaluationBinding ||
      evaluationBinding.agent_id !== input.agentId ||
      evaluationBinding.scheduled_sample_id !== slot.scheduled_sample_id)
  ) {
    throw new Error(`${input.agentId}: accepted output opportunity binding is unavailable`);
  }
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
    evaluation_binding: evaluationBinding
      ? {
          evaluation_opportunity_set_id: evaluationBinding.evaluation_opportunity_set_id,
          evaluation_opportunity_set_hash: evaluationBinding.evaluation_opportunity_set_hash,
          frozen_object_set_id: evaluationBinding.frozen_object_set_id,
          frozen_object_set_hash: evaluationBinding.frozen_object_set_hash,
          ...(evaluationBinding.runtime_authority_binding
            ? { runtime_authority_binding: evaluationBinding.runtime_authority_binding }
            : {}),
        }
      : null,
  };
}

export function buildAcceptedAgentOutputRecord<K extends AcceptedOutputKind, TPayload>(input: {
  kind: K;
  agentId: AcceptedOutputAgentByKind[K];
  payload: TPayload;
  evidenceBundleIds: readonly [string, ...string[]];
  causalDedupeKeys: readonly [string, ...string[]];
  claimGraph: ClaimEvidenceGraph;
  sourceAgentOutputHash: string;
  context: AcceptedOutputBuildContext;
  runtimeAudit?: {
    macro_component_composition: MacroComponentCompositionAudit;
  };
}): AcceptedAgentOutputRecord<K, TPayload> & {
  capability_track: CapabilityTrack;
  knot_capture_v2: AcceptedKnotCaptureV2;
} {
  validateOwner(input.kind, input.agentId);
  validateBuildContext(input.context);
  const evidenceBundleIds = sortedNonEmptyUnique(input.evidenceBundleIds, "evidence bundle");
  const causalDedupeKeys = sortedNonEmptyUnique(input.causalDedupeKeys, "causal dedupe key");
  const sourceAgentOutputHash = requiredSha256(
    input.sourceAgentOutputHash,
    "source_agent_output_hash",
  );
  const claimGraphLineage = acceptedClaimGraphLineage(input.claimGraph);
  const knotCaptureV2 = acceptedKnotCaptureV2(input.claimGraph);
  const acceptedPayloadHash = canonicalHash(input.payload);
  const adapterLineageBody = {
    schema_version: "accepted_output_adapter_lineage_v1" as const,
    adapter_contract_version: "accepted_output_adapter_v1" as const,
    agent_id: input.agentId,
    accepted_output_kind: input.kind,
    source_agent_output_hash: sourceAgentOutputHash,
    accepted_payload_hash: acceptedPayloadHash,
    claim_graph_lineage_hash: claimGraphLineage.claim_graph_lineage_hash,
  };
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
    capability_track: loadCurrentAcceptedOutputCapabilityTrack(),
    as_of: requiredText(input.context.as_of, "as_of"),
    accepted_at: requiredText(input.context.accepted_at, "accepted_at"),
    evaluation_opportunity_set_id:
      input.context.evaluation_binding?.evaluation_opportunity_set_id ?? null,
    evaluation_opportunity_set_hash:
      input.context.evaluation_binding?.evaluation_opportunity_set_hash ?? null,
    frozen_object_set_id: input.context.evaluation_binding?.frozen_object_set_id ?? null,
    frozen_object_set_hash: input.context.evaluation_binding?.frozen_object_set_hash ?? null,
    adapter_lineage: {
      ...adapterLineageBody,
      adapter_lineage_hash: canonicalHash(adapterLineageBody),
    },
    ...(input.context.evaluation_binding?.runtime_authority_binding
      ? {
          runtime_opportunity_authority: input.context.evaluation_binding.runtime_authority_binding,
        }
      : {}),
    knot_capture_v2: knotCaptureV2,
    output: {
      payload: input.payload,
      evidence_bundle_ids: evidenceBundleIds,
      causal_dedupe_keys: causalDedupeKeys,
      claim_graph_lineage: claimGraphLineage,
    },
    ...(input.runtimeAudit ? { runtime_audit: structuredClone(input.runtimeAudit) } : {}),
  };
  return {
    ...withoutHash,
    accepted_output_hash: canonicalHash(withoutHash),
  } as AcceptedAgentOutputRecord<K, TPayload> & {
    capability_track: CapabilityTrack;
    knot_capture_v2: AcceptedKnotCaptureV2;
  };
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
    validateCurrentAcceptedAgentOutputRecord(record);
    return this.#putValidated(record, claimGraph);
  }

  putReadOnly<K extends AcceptedOutputKind, TPayload>(
    record: AcceptedAgentOutputRecord<K, TPayload>,
    claimGraph?: ClaimEvidenceGraph,
  ): AcceptedOutputRecordRef<K> {
    validateAcceptedAgentOutputRecord(record);
    return this.#putValidated(record, claimGraph);
  }

  #putValidated<K extends AcceptedOutputKind, TPayload>(
    record: AcceptedAgentOutputRecord<K, TPayload>,
    claimGraph?: ClaimEvidenceGraph,
  ): AcceptedOutputRecordRef<K> {
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
  const expectedLineage = acceptedClaimGraphLineage(graph);
  if (canonicalHash(expectedLineage) !== canonicalHash(record.output.claim_graph_lineage)) {
    throw new Error(
      `accepted output claim graph projection mismatch: ${record.accepted_output_id}`,
    );
  }
  if (
    record.knot_capture_v2 !== undefined &&
    canonicalHash(acceptedKnotCaptureV2(graph)) !== canonicalHash(record.knot_capture_v2)
  ) {
    throw new Error(`accepted output KNOT capture mismatch: ${record.accepted_output_id}`);
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
  validateEvaluationBinding(record);
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
  if (record.capability_track !== undefined) {
    validateAcceptedOutputCapabilityTrack(record.capability_track);
  }
  validateAdapterLineage(record);
  validateRuntimeAudit(record);
  if (record.knot_capture_v2 !== undefined) validateAcceptedKnotCaptureV2(record);
}

export function validateCurrentAcceptedAgentOutputRecord(record: AcceptedAgentOutputRecord): void {
  validateAcceptedAgentOutputRecord(record);
  if (record.capability_track === undefined) {
    throw new Error(`current capability track required: ${record.accepted_output_id}`);
  }
  validateCurrentAcceptedOutputCapabilityTrack(record.capability_track);
  if (record.knot_capture_v2 === undefined) {
    throw new Error(`current KNOT capture required: ${record.accepted_output_id}`);
  }
}

function validateAcceptedKnotCaptureV2(record: AcceptedAgentOutputRecord): void {
  const capture = record.knot_capture_v2;
  if (capture === undefined) return;
  const expectedFields = [
    "accepted_claim_graph_hash",
    "accepted_lineage_evaluator_version",
    "capability_bundle_hash",
    "capture_hash",
    "claim_specs",
    "eligibility",
    "execution_behavior_release_hash",
    "ineligibility_reasons",
    "knot_audit_capability_track_v2_hash",
    "knot_coverage_manifest_v2_hash",
    "result_event_refs",
    "schema_version",
    "tool_environment_hash",
  ];
  if (Object.keys(capture).sort().join("\0") !== expectedFields.join("\0")) {
    throw new Error(`accepted KNOT capture fields mismatch: ${record.accepted_output_id}`);
  }
  const { capture_hash: suppliedHash, ...body } = capture;
  if (
    capture.schema_version !== "accepted_knot_capture_v2" ||
    capture.accepted_lineage_evaluator_version !== "accepted_claim_lineage_v3" ||
    suppliedHash !== canonicalHash(body)
  ) {
    throw new Error(`accepted KNOT capture hash mismatch: ${record.accepted_output_id}`);
  }
  requiredSha256(capture.accepted_claim_graph_hash, "accepted_claim_graph_hash");
  const reasons = sortedStringArray(capture.ineligibility_reasons, "KNOT ineligibility reason");
  if (
    (capture.eligibility === "ELIGIBLE" && reasons.length !== 0) ||
    (capture.eligibility === "INELIGIBLE" && reasons.length === 0) ||
    (capture.eligibility !== "ELIGIBLE" && capture.eligibility !== "INELIGIBLE")
  ) {
    throw new Error(`accepted KNOT eligibility mismatch: ${record.accepted_output_id}`);
  }
  const fixedPointValues = [
    capture.tool_environment_hash,
    capture.execution_behavior_release_hash,
    capture.capability_bundle_hash,
    capture.knot_coverage_manifest_v2_hash,
    capture.knot_audit_capability_track_v2_hash,
  ];
  if (fixedPointValues.some((value) => value === null)) {
    if (fixedPointValues.some((value) => value !== null) || capture.result_event_refs.length > 0) {
      throw new Error(`accepted KNOT fixed point is partial: ${record.accepted_output_id}`);
    }
  } else {
    fixedPointValues.forEach((value) => {
      requiredSha256(value, "accepted KNOT fixed point");
    });
  }
  if (capture.eligibility === "ELIGIBLE" && capture.result_event_refs.length === 0) {
    throw new Error(
      `eligible accepted KNOT capture lacks result events: ${record.accepted_output_id}`,
    );
  }
  const eventIds = new Set<string>();
  for (const event of capture.result_event_refs) {
    const eventFields = [
      "binding_result_refs",
      "evidence_ids",
      "result_authority_hash",
      "result_authority_type",
      "result_event_hash",
      "result_event_id",
    ];
    if (Object.keys(event).sort().join("\0") !== eventFields.join("\0")) {
      throw new Error(`accepted KNOT event fields mismatch: ${record.accepted_output_id}`);
    }
    requiredText(event.result_event_id, "result_event_id");
    requiredSha256(event.result_event_hash, "result_event_hash");
    requiredSha256(event.result_authority_hash, "result_authority_hash");
    if (
      event.result_authority_type !== "SNAPSHOT_BUILD" &&
      event.result_authority_type !== "FROZEN_QUERY"
    ) {
      throw new Error(`accepted KNOT result authority type mismatch: ${record.accepted_output_id}`);
    }
    if (eventIds.has(event.result_event_id)) {
      throw new Error(`accepted KNOT result event duplicate: ${record.accepted_output_id}`);
    }
    eventIds.add(event.result_event_id);
    sortedStringArray(event.evidence_ids, "accepted KNOT event evidence ID", true);
    const bindingIds = new Set<string>();
    for (const ref of event.binding_result_refs) {
      if (!/^binding:[0-9a-f]{64}$/.test(ref.binding_id)) {
        throw new Error(`accepted KNOT binding ID mismatch: ${record.accepted_output_id}`);
      }
      requiredSha256(ref.binding_result_fingerprint, "binding_result_fingerprint");
      if (bindingIds.has(ref.binding_id)) {
        throw new Error(`accepted KNOT binding ref duplicate: ${record.accepted_output_id}`);
      }
      bindingIds.add(ref.binding_id);
    }
    if (bindingIds.size === 0) {
      throw new Error(`accepted KNOT binding refs empty: ${record.accepted_output_id}`);
    }
  }
  if (
    capture.result_event_refs.map((event) => event.result_event_id).join("\0") !==
    [...capture.result_event_refs]
      .sort((left, right) => left.result_event_id.localeCompare(right.result_event_id))
      .map((event) => event.result_event_id)
      .join("\0")
  ) {
    throw new Error(`accepted KNOT events are not ordered: ${record.accepted_output_id}`);
  }
  const lineageClaims = new Map(
    record.output.claim_graph_lineage.claims.map((claim) => [claim.claim_id, claim.evidence_ids]),
  );
  const payload = record.output.payload;
  const payloadClaims =
    payload !== null && typeof payload === "object" && !Array.isArray(payload)
      ? (payload as Record<string, unknown>).claims
      : undefined;
  const payloadById = new Map<string, unknown>();
  if (Array.isArray(payloadClaims)) {
    for (const rawClaim of payloadClaims) {
      if (rawClaim !== null && typeof rawClaim === "object" && !Array.isArray(rawClaim)) {
        const claim = rawClaim as Record<string, unknown>;
        if (typeof claim.claim_id === "string") {
          payloadById.set(claim.claim_id, claim.structured_conclusion);
        }
      }
    }
  }
  for (const spec of capture.claim_specs) {
    const specFields = ["claim_id", "claim_spec_hash", "evidence_ids", "structured_conclusion"];
    if (Object.keys(spec).sort().join("\0") !== specFields.join("\0")) {
      throw new Error(`accepted KNOT claim spec fields mismatch: ${record.accepted_output_id}`);
    }
    const { claim_spec_hash: claimSpecHash, ...claimSpecBody } = spec;
    if (claimSpecHash !== canonicalHash(claimSpecBody)) {
      throw new Error(`accepted KNOT claim spec hash mismatch: ${record.accepted_output_id}`);
    }
    const lineageEvidence = lineageClaims.get(spec.claim_id);
    if (
      lineageEvidence === undefined ||
      canonicalHash(lineageEvidence) !== canonicalHash(spec.evidence_ids) ||
      (payloadById.size > 0 &&
        (!payloadById.has(spec.claim_id) ||
          canonicalHash(payloadById.get(spec.claim_id)) !==
            canonicalHash(spec.structured_conclusion)))
    ) {
      throw new Error(`accepted KNOT claim spec lineage mismatch: ${record.accepted_output_id}`);
    }
  }
  if (capture.claim_specs.length !== lineageClaims.size) {
    throw new Error(`accepted KNOT claim spec closure mismatch: ${record.accepted_output_id}`);
  }
}

function validateAdapterLineage(record: AcceptedAgentOutputRecord): void {
  const lineage = record.adapter_lineage;
  const expectedFields = [
    "accepted_output_kind",
    "accepted_payload_hash",
    "adapter_contract_version",
    "adapter_lineage_hash",
    "agent_id",
    "claim_graph_lineage_hash",
    "schema_version",
    "source_agent_output_hash",
  ];
  if (Object.keys(lineage).sort().join("\0") !== expectedFields.join("\0")) {
    throw new Error(
      `accepted output adapter lineage fields mismatch: ${record.accepted_output_id}`,
    );
  }
  const { adapter_lineage_hash: suppliedHash, ...body } = lineage;
  if (
    lineage.schema_version !== "accepted_output_adapter_lineage_v1" ||
    lineage.adapter_contract_version !== "accepted_output_adapter_v1" ||
    lineage.agent_id !== record.agent_id ||
    lineage.accepted_output_kind !== record.accepted_output_kind ||
    requiredSha256(lineage.source_agent_output_hash, "source_agent_output_hash") !==
      lineage.source_agent_output_hash ||
    lineage.accepted_payload_hash !== canonicalHash(record.output.payload) ||
    lineage.claim_graph_lineage_hash !==
      record.output.claim_graph_lineage.claim_graph_lineage_hash ||
    suppliedHash !== canonicalHash(body)
  ) {
    throw new Error(`accepted output adapter lineage mismatch: ${record.accepted_output_id}`);
  }
}

function acceptedClaimGraphLineage(graph: ClaimEvidenceGraph): AcceptedClaimGraphLineage {
  const evidence = [...graph.evidence_ledger]
    .map((entry) => ({
      evidence_id: requiredText(entry.evidence_id, "evidence_id"),
      source_fingerprint: requiredSha256(entry.source_fingerprint, "source_fingerprint"),
    }))
    .sort((left, right) => left.evidence_id.localeCompare(right.evidence_id));
  const claims = [...graph.claims]
    .map((claim) => ({
      claim_id: requiredText(claim.claim_id, "claim_id"),
      evidence_ids: sortedClaimEvidenceIds(claim.evidence_ids),
    }))
    .sort((left, right) => left.claim_id.localeCompare(right.claim_id));
  if (new Set(evidence.map((entry) => entry.evidence_id)).size !== evidence.length) {
    throw new Error("accepted claim graph lineage has duplicate evidence IDs");
  }
  if (new Set(claims.map((claim) => claim.claim_id)).size !== claims.length) {
    throw new Error("accepted claim graph lineage has duplicate claim IDs");
  }
  const body = {
    schema_version: "accepted_claim_graph_lineage_v1" as const,
    run_id: requiredText(graph.run_id, "claim_graph.run_id"),
    snapshot_hash: requiredSha256(graph.snapshot_hash, "claim_graph.snapshot_hash"),
    evidence,
    claims,
  };
  return { ...body, claim_graph_lineage_hash: canonicalHash(body) };
}

function acceptedKnotCaptureV2(graph: ClaimEvidenceGraph): AcceptedKnotCaptureV2 {
  type EventRef = AcceptedKnotCaptureV2["result_event_refs"][number];
  type FixedPoint = Pick<
    AcceptedKnotCaptureV2,
    | "tool_environment_hash"
    | "execution_behavior_release_hash"
    | "capability_bundle_hash"
    | "knot_coverage_manifest_v2_hash"
    | "knot_audit_capability_track_v2_hash"
  >;
  const referencedEvidenceIds = new Set(graph.claims.flatMap((claim) => claim.evidence_ids));
  const ineligibilityReasons = new Set<string>();
  const fixedPoints = new Map<string, FixedPoint>();
  const events = new Map<
    string,
    { body: Omit<EventRef, "evidence_ids">; evidenceIds: Set<string> }
  >();
  for (const evidence of graph.evidence_ledger) {
    const audit = acceptedServerToolResult(evidence.value);
    if (audit === null) {
      if (evidence.source_kind === "tool" && referencedEvidenceIds.has(evidence.evidence_id)) {
        ineligibilityReasons.add("CLAIM_TOOL_EVIDENCE_SERVER_AUTHORITY_MISSING");
      }
      continue;
    }
    const fixedPoint: FixedPoint = {
      tool_environment_hash: audit.tool_environment_hash,
      execution_behavior_release_hash: audit.execution_behavior_release_hash,
      capability_bundle_hash: audit.capability_bundle_hash,
      knot_coverage_manifest_v2_hash: audit.knot_coverage_manifest_v2_hash,
      knot_audit_capability_track_v2_hash: audit.knot_audit_capability_track_v2_hash,
    };
    fixedPoints.set(canonicalHash(fixedPoint), fixedPoint);
    const body: Omit<EventRef, "evidence_ids"> = {
      result_event_id: audit.result_event_id,
      result_event_hash: audit.result_event_hash,
      result_authority_type: audit.result_authority_type,
      result_authority_hash: audit.result_authority_hash,
      binding_result_refs: audit.binding_result_refs,
    };
    const existing = events.get(body.result_event_id);
    if (existing) {
      if (canonicalHash(existing.body) !== canonicalHash(body)) {
        throw new Error(`accepted KNOT result event identity drift: ${body.result_event_id}`);
      }
      existing.evidenceIds.add(evidence.evidence_id);
    } else {
      events.set(body.result_event_id, {
        body,
        evidenceIds: new Set([requiredText(evidence.evidence_id, "evidence_id")]),
      });
    }
  }
  if (events.size === 0) ineligibilityReasons.add("NO_SERVER_TOOL_RESULT_AUTHORITY");
  if (fixedPoints.size > 1) {
    throw new Error("accepted KNOT fixed-point drift across result events");
  }
  const fixedPoint = fixedPoints.values().next().value as FixedPoint | undefined;
  const resultEventRefs = [...events.values()]
    .map(({ body, evidenceIds }) => ({
      ...body,
      evidence_ids: [...evidenceIds].sort((left, right) => left.localeCompare(right)),
    }))
    .sort((left, right) => left.result_event_id.localeCompare(right.result_event_id));
  const claimSpecs = [...graph.claims]
    .map((claim) => {
      const body = {
        claim_id: requiredText(claim.claim_id, "claim_id"),
        evidence_ids: sortedClaimEvidenceIds(claim.evidence_ids),
        structured_conclusion: Object.fromEntries(
          Object.entries(claim.structured_conclusion).sort(([left], [right]) =>
            left.localeCompare(right),
          ),
        ),
      };
      return { ...body, claim_spec_hash: canonicalHash(body) };
    })
    .sort((left, right) => left.claim_id.localeCompare(right.claim_id));
  const reasons = [...ineligibilityReasons].sort((left, right) => left.localeCompare(right));
  const body = {
    schema_version: "accepted_knot_capture_v2" as const,
    accepted_lineage_evaluator_version: "accepted_claim_lineage_v3" as const,
    eligibility: reasons.length === 0 ? ("ELIGIBLE" as const) : ("INELIGIBLE" as const),
    ineligibility_reasons: reasons,
    accepted_claim_graph_hash: canonicalHash(graph),
    tool_environment_hash: fixedPoint?.tool_environment_hash ?? null,
    execution_behavior_release_hash: fixedPoint?.execution_behavior_release_hash ?? null,
    capability_bundle_hash: fixedPoint?.capability_bundle_hash ?? null,
    knot_coverage_manifest_v2_hash: fixedPoint?.knot_coverage_manifest_v2_hash ?? null,
    knot_audit_capability_track_v2_hash: fixedPoint?.knot_audit_capability_track_v2_hash ?? null,
    result_event_refs: resultEventRefs,
    claim_specs: claimSpecs,
  };
  return { ...body, capture_hash: canonicalHash(body) };
}

function acceptedServerToolResult(value: unknown): {
  result_event_id: string;
  result_event_hash: string;
  result_authority_type: "SNAPSHOT_BUILD" | "FROZEN_QUERY";
  result_authority_hash: string;
  tool_environment_hash: string;
  execution_behavior_release_hash: string;
  capability_bundle_hash: string;
  knot_coverage_manifest_v2_hash: string;
  knot_audit_capability_track_v2_hash: string;
  binding_result_refs: Array<{
    binding_id: string;
    binding_result_fingerprint: string;
  }>;
} | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = (value as Record<string, unknown>).server_tool_result;
  if (raw === undefined) return null;
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("accepted KNOT server tool result must be an object");
  }
  const record = raw as Record<string, unknown>;
  const expectedKeys = [
    "binding_result_refs",
    "capability_bundle_hash",
    "execution_behavior_release_hash",
    "knot_audit_capability_track_v2_hash",
    "knot_coverage_manifest_v2_hash",
    "result_authority_hash",
    "result_authority_type",
    "result_event_hash",
    "result_event_id",
    "tool_environment_hash",
  ];
  if (Object.keys(record).sort().join("\0") !== expectedKeys.join("\0")) {
    throw new Error("accepted KNOT server tool result fields mismatch");
  }
  if (
    record.result_authority_type !== "SNAPSHOT_BUILD" &&
    record.result_authority_type !== "FROZEN_QUERY"
  ) {
    throw new Error("accepted KNOT result authority type is invalid");
  }
  if (!Array.isArray(record.binding_result_refs) || record.binding_result_refs.length === 0) {
    throw new Error("accepted KNOT binding result refs must not be empty");
  }
  const bindingResultRefs = record.binding_result_refs
    .map((rawRef) => {
      if (rawRef === null || typeof rawRef !== "object" || Array.isArray(rawRef)) {
        throw new Error("accepted KNOT binding result ref must be an object");
      }
      const ref = rawRef as Record<string, unknown>;
      if (Object.keys(ref).sort().join("\0") !== "binding_id\0binding_result_fingerprint") {
        throw new Error("accepted KNOT binding result ref fields mismatch");
      }
      const bindingId = requiredText(ref.binding_id, "binding_id");
      if (!/^binding:[0-9a-f]{64}$/.test(bindingId)) {
        throw new Error("accepted KNOT binding ID is invalid");
      }
      return {
        binding_id: bindingId,
        binding_result_fingerprint: requiredSha256(
          ref.binding_result_fingerprint,
          "binding_result_fingerprint",
        ),
      };
    })
    .sort((left, right) => left.binding_id.localeCompare(right.binding_id));
  if (new Set(bindingResultRefs.map((ref) => ref.binding_id)).size !== bindingResultRefs.length) {
    throw new Error("accepted KNOT binding result refs contain duplicates");
  }
  return {
    result_event_id: requiredText(record.result_event_id, "result_event_id"),
    result_event_hash: requiredSha256(record.result_event_hash, "result_event_hash"),
    result_authority_type: record.result_authority_type,
    result_authority_hash: requiredSha256(record.result_authority_hash, "result_authority_hash"),
    tool_environment_hash: requiredSha256(record.tool_environment_hash, "tool_environment_hash"),
    execution_behavior_release_hash: requiredSha256(
      record.execution_behavior_release_hash,
      "execution_behavior_release_hash",
    ),
    capability_bundle_hash: requiredSha256(record.capability_bundle_hash, "capability_bundle_hash"),
    knot_coverage_manifest_v2_hash: requiredSha256(
      record.knot_coverage_manifest_v2_hash,
      "knot_coverage_manifest_v2_hash",
    ),
    knot_audit_capability_track_v2_hash: requiredSha256(
      record.knot_audit_capability_track_v2_hash,
      "knot_audit_capability_track_v2_hash",
    ),
    binding_result_refs: bindingResultRefs,
  };
}

function sortedClaimEvidenceIds(values: readonly string[]): string[] {
  const first = values[0];
  if (first === undefined) throw new Error("claim evidence id must not be empty");
  return sortedNonEmptyUnique([first, ...values.slice(1)], "claim evidence id");
}

function validateEvaluationBinding(record: AcceptedAgentOutputRecord): void {
  const fields = [
    record.evaluation_opportunity_set_id,
    record.evaluation_opportunity_set_hash,
    record.frozen_object_set_id,
    record.frozen_object_set_hash,
  ] as const;
  if (
    record.run_slot_kind !== "OUTCOME_SCHEDULED" ||
    record.accepted_output_kind === "CIO_PROPOSAL" ||
    record.sample_origin !== "PRODUCTION_ACTIVE"
  ) {
    if (
      fields.some((value) => value !== null) ||
      record.runtime_opportunity_authority !== undefined
    ) {
      throw new Error(
        `accepted output has an unexpected opportunity binding: ${record.accepted_output_id}`,
      );
    }
    return;
  }
  const decision = [
    "ALPHA_DISCOVERY",
    "CRO_RISK_REVIEW",
    "EXECUTION_ASSESSMENT",
    "CIO_FINAL",
  ].includes(record.accepted_output_kind);
  if (fields.every((value) => value === null)) {
    if (decision) {
      throw new Error(
        `Decision accepted output lacks an opportunity binding: ${record.accepted_output_id}`,
      );
    }
    return;
  }
  requiredText(record.evaluation_opportunity_set_id ?? "", "evaluation_opportunity_set_id");
  requiredSha256(record.evaluation_opportunity_set_hash, "evaluation_opportunity_set_hash");
  if (decision) {
    requiredText(record.frozen_object_set_id ?? "", "frozen_object_set_id");
    requiredSha256(record.frozen_object_set_hash, "frozen_object_set_hash");
    validateRuntimeOpportunityAuthority(record.runtime_opportunity_authority);
  } else {
    if (record.frozen_object_set_id !== null || record.frozen_object_set_hash !== null) {
      throw new Error(
        `non-Decision accepted output has a frozen stage object: ${record.accepted_output_id}`,
      );
    }
    validateLiveRuntimeOpportunityAuthority(record.runtime_opportunity_authority, record.agent_id);
  }
}

function validateRuntimeOpportunityAuthority(
  authority: OutcomeRuntimeAuthorityBinding | undefined,
): void {
  if (!authority) throw new Error("Decision accepted output lacks runtime opportunity authority");
  const fields = [
    "candidate_scope_hash",
    "candidate_universe_hash",
    "source_snapshot_hash",
    "source_tool_id",
    "upstream_accepted_output_refs_hash",
  ];
  if (Object.keys(authority).sort().join("\0") !== fields.join("\0")) {
    throw new Error("Decision runtime opportunity authority fields mismatch");
  }
  if (!("candidate_scope_hash" in authority)) {
    throw new Error("Decision runtime opportunity authority shape mismatch");
  }
  if (
    ![
      "get_alpha_candidate_snapshot",
      "get_cro_risk_snapshot",
      "get_execution_snapshot",
      "get_cio_decision_snapshot",
    ].includes(authority.source_tool_id)
  ) {
    throw new Error("Decision runtime opportunity authority tool mismatch");
  }
  requiredSha256(authority.source_snapshot_hash, "source_snapshot_hash");
  requiredSha256(authority.candidate_scope_hash, "candidate_scope_hash");
  requiredSha256(authority.candidate_universe_hash, "candidate_universe_hash");
  requiredSha256(
    authority.upstream_accepted_output_refs_hash,
    "upstream_accepted_output_refs_hash",
  );
}

function validateLiveRuntimeOpportunityAuthority(
  authority: OutcomeRuntimeAuthorityBinding | undefined,
  agentId: string,
): void {
  if (!authority || !("domain_hash" in authority)) {
    throw new Error(`${agentId}: accepted output lacks live source authority`);
  }
  const fields = ["domain_hash", "source_snapshot_hash", "source_tool_id"];
  if (Object.keys(authority).sort().join("\0") !== fields.join("\0")) {
    throw new Error(`${agentId}: live source authority fields mismatch`);
  }
  const expectedTool = {
    china: "get_china_macro_snapshot",
    us_economy: "get_us_macro_snapshot",
    eu_economy: "get_eu_macro_snapshot",
    central_bank: "get_central_bank_snapshot",
    us_financial_conditions: "get_us_financial_conditions_snapshot",
    euro_area_financial_conditions: "get_euro_area_financial_conditions_snapshot",
    commodities: "get_commodity_conditions_snapshot",
    geopolitical: "get_geopolitical_events_snapshot",
    market_breadth: "get_market_breadth_snapshot",
    institutional_flow: "get_market_positioning_snapshot",
    semiconductor: "get_sector_research_snapshot",
    technology: "get_sector_research_snapshot",
    energy: "get_sector_research_snapshot",
    biotech: "get_sector_research_snapshot",
    consumer: "get_sector_research_snapshot",
    industrials: "get_sector_research_snapshot",
    real_estate_construction: "get_sector_research_snapshot",
    financials: "get_sector_research_snapshot",
    agriculture: "get_sector_research_snapshot",
  }[agentId];
  if (!expectedTool || authority.source_tool_id !== expectedTool) {
    throw new Error(`${agentId}: live source authority tool mismatch`);
  }
  requiredSha256(authority.source_snapshot_hash, "source_snapshot_hash");
  requiredSha256(authority.domain_hash, "domain_hash");
}

function validateRuntimeAudit(record: AcceptedAgentOutputRecord): void {
  const requiresCompositionAudit =
    record.accepted_output_kind === "MACRO_TRANSMISSION" &&
    record.component_weight_contract_version !== null;
  const runtimeAudit = record.runtime_audit;
  if (!requiresCompositionAudit) {
    if (runtimeAudit !== undefined) {
      throw new Error(
        `accepted output has an unexpected runtime audit: ${record.accepted_output_id}`,
      );
    }
    return;
  }
  if (
    !runtimeAudit ||
    Object.keys(runtimeAudit).length !== 1 ||
    !("macro_component_composition" in runtimeAudit)
  ) {
    throw new Error(`accepted Macro component audit is missing: ${record.accepted_output_id}`);
  }
  const composition = runtimeAudit.macro_component_composition;
  const expectedCompositionFields = [
    "agent_id",
    "component_composition_hash",
    "component_weight_contract_version",
    "component_weights",
    "components",
    "composed_payload_hash",
    "context_only_projection_hash",
    "schema_version",
    "source_snapshot_hash",
  ].sort();
  const requiresContextProjection = record.agent_id in MACRO_CONTEXT_SOURCE_ROLES;
  if (
    Object.keys(composition).sort().join("\0") !== expectedCompositionFields.join("\0") ||
    composition.schema_version !== "macro_component_composition_audit_v1" ||
    composition.agent_id !== record.agent_id ||
    composition.component_weight_contract_version !== record.component_weight_contract_version ||
    !/^sha256:[0-9a-f]{64}$/.test(composition.source_snapshot_hash) ||
    (requiresContextProjection &&
      !/^sha256:[0-9a-f]{64}$/.test(composition.context_only_projection_hash ?? "")) ||
    (!requiresContextProjection && composition.context_only_projection_hash !== null) ||
    !/^sha256:[0-9a-f]{64}$/.test(composition.composed_payload_hash) ||
    !/^sha256:[0-9a-f]{64}$/.test(composition.component_composition_hash)
  ) {
    throw new Error(
      `accepted Macro component audit binding is invalid: ${record.accepted_output_id}`,
    );
  }
  const { component_composition_hash: suppliedHash, ...withoutHash } = composition;
  if (
    suppliedHash !== canonicalHash(withoutHash) ||
    composition.composed_payload_hash !== canonicalHash(record.output.payload)
  ) {
    throw new Error(`accepted Macro component audit hash mismatch: ${record.accepted_output_id}`);
  }
  if (
    !Array.isArray(composition.components) ||
    composition.components.length === 0 ||
    composition.components.map((row) => row.component).join("\0") !==
      [...composition.components]
        .sort((left, right) => left.component.localeCompare(right.component))
        .map((row) => row.component)
        .join("\0") ||
    new Set(composition.components.map((row) => row.component)).size !==
      composition.components.length ||
    Object.keys(composition.component_weights).sort().join("\0") !==
      composition.components.map((row) => row.component).join("\0") ||
    !Object.values(composition.component_weights).every(
      (weight) => Number.isFinite(weight) && weight > 0,
    ) ||
    Math.abs(
      Object.values(composition.component_weights).reduce((sum, weight) => sum + weight, 0) - 1,
    ) > 1e-12
  ) {
    throw new Error(
      `accepted Macro component audit composition is invalid: ${record.accepted_output_id}`,
    );
  }
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
  if (binding.sample_origin !== "PRODUCTION_ACTIVE") {
    throw new Error("accepted output sample_origin must be PRODUCTION_ACTIVE");
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

function sortedStringArray(values: readonly string[], label: string, nonempty = false): string[] {
  if (nonempty && values.length === 0) throw new Error(`${label} must not be empty`);
  const normalized = values.map((value) => requiredText(value, label));
  const sorted = [...new Set(normalized)].sort((left, right) => left.localeCompare(right));
  if (sorted.length !== values.length || sorted.join("\0") !== normalized.join("\0")) {
    throw new Error(`${label} values must be unique and canonically ordered`);
  }
  return sorted;
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be non-empty`);
  }
  return value.trim();
}

function requiredSha256(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${label} must be a sha256 hash`);
  }
  return value;
}

function deterministicId(namespace: string, value: unknown): string {
  return `${namespace}:${canonicalHash(value).slice("sha256:".length)}`;
}

export function canonicalAcceptedOutputHash(value: unknown): string {
  return canonicalHash(value);
}

function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
}

import { createHash } from "node:crypto";
import type { NoEvaluationObjectStageSkipRecord } from "../../autoresearch/outcome_stage_skip.js";
import type { DarwinianUsageWeightSnapshot } from "../../autoresearch/production_variant.js";
import {
  type AcceptedAgentOutputRecord,
  type AcceptedAgentOutputStore,
  type AcceptedOutputRecordRef,
  acceptedOutputRefKey,
} from "../accepted_output.js";
import { SECTOR_AGENT_IDS } from "../sector/_contracts.js";
import {
  type AcceptedSectorSelection,
  modelVisibleAcceptedSectorSelection,
} from "../sector/accepted.js";
import {
  type AcceptedRelationshipGraph,
  modelVisibleAcceptedRelationshipGraph,
} from "../sector/relationship_accepted.js";
import type { DailyCycleStateType } from "../state.js";
import {
  type AcceptedSuperinvestorSelection,
  modelVisibleAcceptedSuperinvestorSelection,
} from "../superinvestor/accepted.js";
import type { RelationshipMapperOutput, SectorAgentOutput, SuperinvestorOutput } from "../types.js";

export const SUPERINVESTOR_AGENT_IDS = ["druckenmiller", "munger", "burry", "ackman"] as const;

export interface SourceLayerUsageEntry {
  agent_id: string;
  directional_confidence: number;
  abstention_confidence: number;
  effective_reliability: number;
  usage_share: number;
  weight_record_id: string | null;
  reliability_record_id: string | null;
  reliability_adapter_contract_version: string | null;
  calibration_state_id: string | null;
}

export interface SourceLayerUsageReceipt {
  schema_version: "source_layer_usage_receipt_v1";
  source_layer: "SECTOR" | "SUPERINVESTOR";
  source_layer_signal_state: "SIGNAL_SET_READY" | "NO_DIRECTIONAL_SIGNAL";
  accepted_agent_ids: string[];
  stage_skipped_agent_ids: string[];
  source_layer_snapshot_id: string;
  source_layer_snapshot_hash: string;
  darwinian_snapshot_id: string | null;
  darwinian_snapshot_hash: string | null;
  reliability_by_agent: Record<string, SourceLayerUsageEntry>;
}

export function deriveSectorUsageReceipt(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): SourceLayerUsageReceipt {
  if (state.darwinian_runtime_binding) {
    const outputs = acceptedSectorUsageInputs(state, requiredStore(store, "Sector"));
    validateRoster(Object.keys(outputs), SECTOR_AGENT_IDS, "Sector", true);
    return buildReceipt({
      sourceLayer: "SECTOR",
      agentIds: Object.keys(outputs).sort(),
      outputs,
      weightSnapshot: state.darwinian_weight_snapshot,
      adapterVersions: state.darwinian_runtime_binding.agent_behavior_bindings,
      confidenceFor: acceptedConfidence,
      agentIdFor: acceptedOrLegacyAgentId,
    });
  }
  const outputs = state.layer2_outputs;
  validateRoster(
    Object.keys(outputs),
    SECTOR_AGENT_IDS,
    "Sector",
    state.darwinian_runtime_binding !== null,
  );
  return buildReceipt({
    sourceLayer: "SECTOR",
    agentIds: Object.keys(outputs).sort(),
    outputs,
    weightSnapshot: state.darwinian_weight_snapshot,
    adapterVersions: undefined,
    confidenceFor: sectorConfidence,
    agentIdFor: acceptedOrLegacyAgentId,
  });
}

export function deriveSuperinvestorUsageReceipt(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): SourceLayerUsageReceipt {
  const outputs = state.darwinian_runtime_binding
    ? acceptedSuperinvestorUsageInputs(state, requiredStore(store, "Superinvestor"))
    : state.layer3_outputs;
  const stageSkips = Object.fromEntries(
    SUPERINVESTOR_AGENT_IDS.flatMap((agentId) => {
      const skip = state.outcome_stage_skips[agentId];
      return skip ? [[agentId, skip] as const] : [];
    }),
  );
  const outputIds = Object.keys(outputs);
  const skippedIds = Object.keys(stageSkips);
  if (outputIds.some((agentId) => skippedIds.includes(agentId))) {
    throw new Error("Superinvestor slot cannot contain both accepted output and stage skip");
  }
  validateRoster(
    [...outputIds, ...skippedIds],
    SUPERINVESTOR_AGENT_IDS,
    "Superinvestor",
    state.darwinian_runtime_binding !== null,
  );
  if (state.darwinian_runtime_binding) {
    return buildReceipt({
      sourceLayer: "SUPERINVESTOR",
      agentIds: outputIds.sort(),
      outputs: outputs as Record<string, AcceptedUsageInput>,
      stageSkips,
      weightSnapshot: state.darwinian_weight_snapshot,
      adapterVersions: state.darwinian_runtime_binding.agent_behavior_bindings,
      confidenceFor: acceptedConfidence,
      agentIdFor: acceptedOrLegacyAgentId,
    });
  }
  return buildReceipt({
    sourceLayer: "SUPERINVESTOR",
    agentIds: outputIds.sort(),
    outputs: outputs as Record<string, SuperinvestorOutput>,
    stageSkips,
    weightSnapshot: state.darwinian_weight_snapshot,
    adapterVersions: undefined,
    confidenceFor: superinvestorConfidence,
    agentIdFor: acceptedOrLegacyAgentId,
  });
}

export function renderAcceptedSectorInputs(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): string {
  const lines = ["## Layer-2 accepted sector inputs"];
  if (state.darwinian_runtime_binding === null && Object.keys(state.layer2_outputs).length === 0) {
    lines.push("* (not available — accepted Sector roster is empty)");
    return lines.join("\n");
  }
  const receipt = deriveSectorUsageReceipt(state, store);
  lines.push(`* source_layer_signal_state: ${receipt.source_layer_signal_state}`);
  lines.push(`* source_layer_snapshot_id: ${receipt.source_layer_snapshot_id}`);
  for (const agentId of receipt.accepted_agent_ids) {
    const reliability = receipt.reliability_by_agent[agentId];
    if (!reliability) throw new Error(`${agentId}: accepted Sector reliability is missing`);
    if (state.darwinian_runtime_binding) {
      const modelView = acceptedSectorModelView(state, requiredStore(store, "Sector"), agentId);
      lines.push(
        `### ${agentId}\n` +
          `* usage_share: ${reliability.usage_share.toFixed(6)}\n` +
          `* directional_confidence: ${reliability.directional_confidence.toFixed(6)}\n` +
          `* abstention_confidence: ${reliability.abstention_confidence.toFixed(6)}\n` +
          `* output: ${JSON.stringify(modelView)}`,
      );
      continue;
    }
    const output = state.layer2_outputs[agentId];
    if (!output) throw new Error(`${agentId}: accepted Sector input is missing`);
    if (output.agent === "relationship_mapper") {
      lines.push(
        `### ${agentId}\n` +
          `* usage_share: ${reliability.usage_share.toFixed(6)}\n` +
          `* directional_confidence: ${reliability.directional_confidence.toFixed(6)}\n` +
          `* abstention_confidence: ${reliability.abstention_confidence.toFixed(6)}\n` +
          `* output: ${JSON.stringify(modelVisibleRelationship(output))}`,
      );
      continue;
    }
    lines.push(
      `### ${agentId}\n` +
        `* usage_share: ${reliability.usage_share.toFixed(6)}\n` +
        `* directional_confidence: ${reliability.directional_confidence.toFixed(6)}\n` +
        `* abstention_confidence: ${reliability.abstention_confidence.toFixed(6)}\n` +
        `* output: ${JSON.stringify(modelVisibleStandardSector(output))}`,
    );
  }
  return lines.join("\n");
}

export function renderAcceptedSuperinvestorInputs(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): string {
  const lines = ["## Layer-3 accepted superinvestor inputs"];
  if (
    state.darwinian_runtime_binding === null &&
    Object.keys(state.layer3_outputs).length === 0 &&
    Object.keys(state.outcome_stage_skips).length === 0
  ) {
    lines.push("* (not available — accepted Superinvestor roster is empty)");
    return lines.join("\n");
  }
  const receipt = deriveSuperinvestorUsageReceipt(state, store);
  lines.push(`* source_layer_signal_state: ${receipt.source_layer_signal_state}`);
  lines.push(`* source_layer_snapshot_id: ${receipt.source_layer_snapshot_id}`);
  for (const agentId of SUPERINVESTOR_AGENT_IDS) {
    const stageSkip = state.outcome_stage_skips[agentId];
    if (stageSkip) {
      lines.push(
        `### ${agentId}\n` +
          "* source_entry_status: NO_EVALUATION_OBJECT\n" +
          "* usage_share: 0.000000\n" +
          `* output: ${JSON.stringify({
            agent_id: agentId,
            skip_reason: "NO_EVALUATION_OBJECT",
            member_count: 0,
          })}`,
      );
      continue;
    }
    if (!state.darwinian_runtime_binding && !state.layer3_outputs[agentId]) continue;
    const reliability = receipt.reliability_by_agent[agentId];
    if (!reliability) {
      throw new Error(`${agentId}: accepted Superinvestor input is missing`);
    }
    if (state.darwinian_runtime_binding) {
      const modelView = acceptedSuperinvestorModelView(
        state,
        requiredStore(store, "Superinvestor"),
        agentId,
      );
      lines.push(
        `### ${agentId}\n` +
          `* usage_share: ${reliability.usage_share.toFixed(6)}\n` +
          `* directional_confidence: ${reliability.directional_confidence.toFixed(6)}\n` +
          `* abstention_confidence: ${reliability.abstention_confidence.toFixed(6)}\n` +
          `* output: ${JSON.stringify(modelView)}`,
      );
      continue;
    }
    const output = state.layer3_outputs[agentId];
    if (!output) continue;
    lines.push(
      `### ${agentId}\n` +
        `* usage_share: ${reliability.usage_share.toFixed(6)}\n` +
        `* directional_confidence: ${reliability.directional_confidence.toFixed(6)}\n` +
        `* abstention_confidence: ${reliability.abstention_confidence.toFixed(6)}\n` +
        `* output: ${JSON.stringify({
          selection_status: output.selection_status,
          holding_period: output.holding_period,
          picks: output.picks,
          key_drivers: output.key_drivers,
          risks: output.risks,
          claims: output.claims ?? [],
          claim_refs: output.claim_refs ?? [],
        })}`,
    );
  }
  return lines.join("\n");
}

interface AcceptedUsageInput {
  agent: string;
  directional_confidence: number;
  abstention_confidence: number;
  model_view: unknown;
}

function acceptedSectorUsageInputs(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
): Record<string, AcceptedUsageInput> {
  return Object.fromEntries(
    SECTOR_AGENT_IDS.map((agentId) => {
      const projection = acceptedSectorProjection(state, store, agentId);
      return [
        agentId,
        {
          agent: agentId,
          directional_confidence: projection.directional,
          abstention_confidence: projection.abstention,
          model_view: projection.modelView,
        },
      ];
    }),
  );
}

function acceptedSuperinvestorUsageInputs(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
): Record<string, AcceptedUsageInput> {
  return Object.fromEntries(
    SUPERINVESTOR_AGENT_IDS.flatMap((agentId) => {
      if (state.outcome_stage_skips[agentId]) return [];
      const modelView = acceptedSuperinvestorModelView(state, store, agentId);
      return [
        [
          agentId,
          {
            agent: agentId,
            directional_confidence: modelView.directional_confidence,
            abstention_confidence: modelView.abstention_confidence,
            model_view: modelView,
          },
        ] as const,
      ];
    }),
  );
}

function acceptedSectorModelView(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
  agentId: string,
): unknown {
  return acceptedSectorProjection(state, store, agentId).modelView;
}

function acceptedSectorProjection(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
  agentId: string,
): { modelView: unknown; directional: number; abstention: number } {
  if (agentId === "relationship_mapper") {
    const accepted = resolveAcceptedPayload<AcceptedRelationshipGraph>(
      state,
      store,
      "RELATIONSHIP_GRAPH",
      agentId,
    );
    return {
      modelView: modelVisibleAcceptedRelationshipGraph(accepted),
      directional: accepted.directional_confidence,
      abstention: accepted.predictive_graph_abstention_confidence ?? 0,
    };
  }
  const accepted = resolveAcceptedPayload<AcceptedSectorSelection>(
    state,
    store,
    "STANDARD_SECTOR_SELECTION",
    agentId,
  );
  return {
    modelView: modelVisibleAcceptedSectorSelection(accepted),
    directional: accepted.directional_confidence,
    abstention: accepted.abstention_confidence,
  };
}

function acceptedSuperinvestorModelView(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
  agentId: (typeof SUPERINVESTOR_AGENT_IDS)[number],
) {
  const accepted = resolveAcceptedPayload<AcceptedSuperinvestorSelection>(
    state,
    store,
    "SUPERINVESTOR_SELECTION",
    agentId,
  );
  return modelVisibleAcceptedSuperinvestorSelection(accepted);
}

function resolveAcceptedPayload<T>(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
  kind: "STANDARD_SECTOR_SELECTION" | "RELATIONSHIP_GRAPH" | "SUPERINVESTOR_SELECTION",
  agentId: string,
): T {
  const key = acceptedOutputRefKey(kind, agentId as never);
  const ref = state.accepted_output_refs[key];
  if (!ref) throw new Error(`${agentId}: ${kind} accepted record ref is unavailable`);
  const record = store.resolve(
    ref as AcceptedOutputRecordRef<typeof kind>,
  ) as AcceptedAgentOutputRecord<typeof kind, T>;
  if (
    record.graph_run_id !== state.trace_id ||
    record.as_of !== (state.outcome_schedule_plan?.as_of ?? state.as_of_date) ||
    record.cohort_id !== state.active_cohort
  ) {
    throw new Error(`${agentId}: ${kind} accepted record binding mismatch`);
  }
  return record.output.payload;
}

function acceptedConfidence(output: AcceptedUsageInput) {
  return {
    directional: output.directional_confidence,
    abstention: output.abstention_confidence,
  };
}

function acceptedOrLegacyAgentId(output: unknown): string | undefined {
  const row = output as { agent?: unknown };
  return typeof row.agent === "string" ? row.agent : undefined;
}

function requiredStore(
  store: AcceptedAgentOutputStore | undefined,
  layer: string,
): AcceptedAgentOutputStore {
  if (!store) throw new Error(`${layer} accepted-output store is required in production`);
  return store;
}

function buildReceipt<TOutput>(input: {
  sourceLayer: "SECTOR" | "SUPERINVESTOR";
  agentIds: string[];
  outputs: Readonly<Record<string, TOutput>>;
  stageSkips?: Readonly<Record<string, NoEvaluationObjectStageSkipRecord>>;
  weightSnapshot: DarwinianUsageWeightSnapshot | null;
  adapterVersions:
    | Readonly<
        Record<
          string,
          {
            reliability_adapter_contract_version: string | null;
            confidence_semantics_contract_version: string | null;
          }
        >
      >
    | undefined;
  confidenceFor: (output: TOutput) => { directional: number; abstention: number };
  agentIdFor?: (output: TOutput) => string | undefined;
}): SourceLayerUsageReceipt {
  const skippedAgentIds = Object.keys(input.stageSkips ?? {}).sort();
  if (input.agentIds.length === 0 && skippedAgentIds.length === 0) {
    throw new Error(`${input.sourceLayer} roster is empty`);
  }
  const weights = new Map((input.weightSnapshot?.weights ?? []).map((row) => [row.agent_id, row]));
  if (input.weightSnapshot && (input.weightSnapshot.weights.length !== 24 || weights.size !== 24)) {
    throw new Error(`${input.sourceLayer} gate requires the exact 24-Agent Darwinian snapshot`);
  }
  const entries: Record<string, SourceLayerUsageEntry> = {};
  let denominator = 0;
  for (const agentId of input.agentIds) {
    const output = input.outputs[agentId];
    if (!output) throw new Error(`${agentId}: output slot is missing`);
    if ((input.agentIdFor?.(output) ?? (output as { agent?: unknown }).agent) !== agentId) {
      throw new Error(`${agentId}: accepted output owner mismatch`);
    }
    const confidence = input.confidenceFor(output);
    const weight = weights.get(agentId);
    if (input.weightSnapshot && !weight) throw new Error(`${agentId}: Darwinian weight is missing`);
    const adapter = input.adapterVersions?.[agentId];
    if (input.adapterVersions && !adapter?.reliability_adapter_contract_version) {
      throw new Error(`${agentId}: reliability adapter contract is missing`);
    }
    const darwinWeight = weight?.darwin_weight ?? 1;
    const operationalReliability = weight?.operational_reliability_if_accepted ?? 1;
    if (
      !Number.isFinite(darwinWeight) ||
      darwinWeight <= 0 ||
      !Number.isFinite(operationalReliability) ||
      operationalReliability < 0 ||
      operationalReliability > 1
    ) {
      throw new Error(`${agentId}: invalid Darwinian reliability metadata`);
    }
    const effective = confidence.directional * darwinWeight * operationalReliability;
    denominator += effective;
    entries[agentId] = {
      agent_id: agentId,
      directional_confidence: confidence.directional,
      abstention_confidence: confidence.abstention,
      effective_reliability: effective,
      usage_share: 0,
      weight_record_id: weight?.weight_record_id ?? null,
      reliability_record_id: weight?.reliability_record_id ?? null,
      reliability_adapter_contract_version:
        adapter?.reliability_adapter_contract_version ?? "explicit_identity_adapter_v1",
      calibration_state_id: "explicit_identity_cold_start_v1",
    };
  }
  const signalState = denominator > 0 ? "SIGNAL_SET_READY" : "NO_DIRECTIONAL_SIGNAL";
  if (signalState === "SIGNAL_SET_READY") {
    for (const agentId of input.agentIds) {
      const entry = requiredUsageEntry(entries, agentId);
      entry.usage_share = entry.effective_reliability / denominator;
    }
  }
  const snapshotBody = {
    source_layer: input.sourceLayer,
    source_layer_signal_state: signalState,
    accepted_outputs: input.agentIds.map((agentId) => input.outputs[agentId]),
    stage_skips: skippedAgentIds.map((agentId) => input.stageSkips?.[agentId]),
    usage_shares: Object.fromEntries(
      input.agentIds.map((agentId) => [agentId, requiredUsageEntry(entries, agentId).usage_share]),
    ),
    darwinian_snapshot_id: input.weightSnapshot?.darwinian_snapshot_id ?? null,
    darwinian_snapshot_hash: input.weightSnapshot?.darwinian_snapshot_hash ?? null,
    adapter_contract_versions: Object.fromEntries(
      input.agentIds.map((agentId) => [
        agentId,
        requiredUsageEntry(entries, agentId).reliability_adapter_contract_version,
      ]),
    ),
  };
  const snapshotHash = canonicalHash(snapshotBody);
  return {
    schema_version: "source_layer_usage_receipt_v1",
    source_layer: input.sourceLayer,
    source_layer_signal_state: signalState,
    accepted_agent_ids: [...input.agentIds],
    stage_skipped_agent_ids: skippedAgentIds,
    source_layer_snapshot_id: `${input.sourceLayer.toLowerCase()}-source-layer:${snapshotHash.slice(7)}`,
    source_layer_snapshot_hash: snapshotHash,
    darwinian_snapshot_id: input.weightSnapshot?.darwinian_snapshot_id ?? null,
    darwinian_snapshot_hash: input.weightSnapshot?.darwinian_snapshot_hash ?? null,
    reliability_by_agent: entries,
  };
}

function validateRoster(
  actual: string[],
  expected: readonly string[],
  label: string,
  strict: boolean,
): void {
  if (!strict) return;
  if ([...actual].sort().join("\0") !== [...expected].sort().join("\0")) {
    throw new Error(`${label} gate requires the exact ${expected.length}-Agent roster`);
  }
}

function requiredUsageEntry(
  entries: Record<string, SourceLayerUsageEntry>,
  agentId: string,
): SourceLayerUsageEntry {
  const entry = entries[agentId];
  if (!entry) throw new Error(`${agentId}: source-layer usage entry is missing`);
  return entry;
}

function sectorConfidence(output: SectorAgentOutput): { directional: number; abstention: number } {
  if (output.agent === "relationship_mapper") {
    if (output.predictive_graph_status === "NO_QUALIFIED_PREDICTIVE_EDGE") {
      return {
        directional: 0,
        abstention: output.predictive_graph_abstention_confidence ?? 0,
      };
    }
    if (output.predictive_edges.length === 0) {
      throw new Error("relationship_mapper EDGES_PRESENT requires predictive edges");
    }
    return {
      directional:
        output.predictive_edges.reduce((sum, edge) => sum + edge.model_confidence, 0) /
        output.predictive_edges.length,
      abstention: 0,
    };
  }
  return output.selection_status === "SELECTED"
    ? { directional: output.confidence, abstention: 0 }
    : { directional: 0, abstention: output.confidence };
}

function superinvestorConfidence(output: SuperinvestorOutput): {
  directional: number;
  abstention: number;
} {
  const selected = output.selection_status === "SELECTED";
  return selected
    ? { directional: output.confidence, abstention: 0 }
    : { directional: 0, abstention: output.confidence };
}

function modelVisibleStandardSector(output: Exclude<SectorAgentOutput, RelationshipMapperOutput>) {
  return {
    selection_status: output.selection_status,
    preferred_direction: output.preferred_direction,
    least_preferred_direction: output.least_preferred_direction,
    persistence_horizon: output.persistence_horizon,
    key_drivers: output.key_drivers,
    risks: output.risks,
    claims: output.claims,
    claim_refs: output.claim_refs,
    preferred_security_status: output.preferred_security_status,
    long_picks: output.long_picks,
    least_preferred_security_status: output.least_preferred_security_status,
    short_or_avoid_picks: output.short_or_avoid_picks,
  };
}

function modelVisibleRelationship(output: RelationshipMapperOutput) {
  return {
    factual_edges: output.factual_edges,
    predictive_edges: output.predictive_edges,
    predictive_graph_status: output.predictive_graph_status,
    key_drivers: output.key_drivers,
    risks: output.risks,
    claims: output.claims,
    claim_refs: output.claim_refs,
  };
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

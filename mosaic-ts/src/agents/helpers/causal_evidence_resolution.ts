import type {
  AcceptedAgentOutputRecord,
  AcceptedAgentOutputStore,
  AcceptedOutputKind,
  AcceptedOutputRecordRef,
} from "../accepted_output.js";
import type { Claim, ClaimEvidenceGraph } from "../evidence_contract.js";
import { MACRO_AGENT_IDS } from "../macro/_contracts.js";
import { SECTOR_AGENT_IDS } from "../sector/_contracts.js";
import type { DailyCycleStateType } from "../state.js";
import type { AgentId } from "../tool_contract.js";
import { canonicalJsonHash } from "./canonical_json.js";
import {
  deriveSectorUsageReceipt,
  deriveSuperinvestorUsageReceipt,
  SUPERINVESTOR_AGENT_IDS,
} from "./source_layer_usage.js";

export type CausalSourceLayer = "MACRO" | "SECTOR" | "SUPERINVESTOR" | "DECISION";

export interface EvidenceLineageEnvelope<T> {
  payload: T;
  evidence_bundle_ids: [string, ...string[]];
  causal_dedupe_keys: [string, ...string[]];
}

export interface ModelVisibleEvidenceLineageEnvelope<T> {
  payload: T;
  causal_dedupe_keys: [string, ...string[]];
}

export interface CausalEvidenceContributionResolution {
  causal_dedupe_key: string;
  evidence_bundle_ids: [string, ...string[]];
  independent_evidence_count: 1;
  contributing_agent_ids: [AgentId, ...AgentId[]];
  contributing_claim_refs: string[];
  interpretation_state: "CONSISTENT" | "CONFLICTING" | "FACT_ONLY";
  cross_layer_confidence_reducer: "NONE";
}

export interface SourceLayerSnapshotRef {
  source_layer: CausalSourceLayer;
  source_layer_snapshot_id: string;
  source_layer_snapshot_hash: string;
}

export interface CausalEvidenceResolutionSet {
  resolution_set_id: string;
  resolution_set_hash: string;
  consumer_agent_id: AgentId;
  consumer_input_snapshot_id: string;
  consumer_input_snapshot_hash: string;
  ordered_source_layer_snapshot_refs: [SourceLayerSnapshotRef, ...SourceLayerSnapshotRef[]];
  resolutions: [CausalEvidenceContributionResolution, ...CausalEvidenceContributionResolution[]];
}

export type ModelVisibleCausalEvidenceContributionResolution = Omit<
  CausalEvidenceContributionResolution,
  "evidence_bundle_ids"
>;

export interface ModelVisibleCausalEvidenceResolutionSet {
  resolution_set_id: string;
  resolution_set_hash: string;
  consumer_input_snapshot_id: string;
  consumer_input_snapshot_hash: string;
  ordered_source_layer_snapshot_refs: [SourceLayerSnapshotRef, ...SourceLayerSnapshotRef[]];
  resolutions: [
    ModelVisibleCausalEvidenceContributionResolution,
    ...ModelVisibleCausalEvidenceContributionResolution[],
  ];
}

interface EvidenceContribution {
  causalKey: string;
  evidenceBundleId: string;
  agentId: AgentId;
  claimRef: string;
  polarity: "POSITIVE" | "NEGATIVE" | "UNSPECIFIED" | null;
}

export function buildCausalEvidenceResolutionSet(input: {
  state: DailyCycleStateType;
  consumerAgentId: AgentId;
  sourceLayers: readonly CausalSourceLayer[];
  acceptedOutputStore?: AcceptedAgentOutputStore;
}): CausalEvidenceResolutionSet | null {
  const refs = sourceLayerRefs(input.state, input.sourceLayers, input.acceptedOutputStore);
  const contributions = input.sourceLayers.flatMap((layer) =>
    contributionsForLayer(input.state, layer, input.acceptedOutputStore),
  );
  if (refs.length === 0 || contributions.length === 0) {
    if (input.state.darwinian_runtime_binding !== null) {
      throw new Error(
        `${input.consumerAgentId}: production causal evidence resolution requires verified source evidence`,
      );
    }
    return null;
  }
  const grouped = new Map<string, EvidenceContribution[]>();
  for (const contribution of contributions) {
    const group = grouped.get(contribution.causalKey) ?? [];
    group.push(contribution);
    grouped.set(contribution.causalKey, group);
  }
  const resolutions = [...grouped]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([causalKey, group]): CausalEvidenceContributionResolution => {
      const polarities = new Set(
        group
          .map((item) => item.polarity)
          .filter(
            (value): value is Exclude<EvidenceContribution["polarity"], null> => value !== null,
          ),
      );
      const hasInterpretation = polarities.size > 0;
      return {
        causal_dedupe_key: causalKey,
        evidence_bundle_ids: tuple(sortedUnique(group.map((item) => item.evidenceBundleId))),
        independent_evidence_count: 1,
        contributing_agent_ids: tuple(sortedUnique(group.map((item) => item.agentId)) as AgentId[]),
        contributing_claim_refs: sortedUnique(group.map((item) => item.claimRef)),
        interpretation_state: !hasInterpretation
          ? "FACT_ONLY"
          : polarities.has("POSITIVE") && polarities.has("NEGATIVE")
            ? "CONFLICTING"
            : "CONSISTENT",
        cross_layer_confidence_reducer: "NONE",
      };
    });
  const orderedRefs = tuple(refs);
  const resolutionTuple = tuple(resolutions);
  const consumerInputBody = {
    contract: "consumer_input_snapshot_v1",
    consumer_agent_id: input.consumerAgentId,
    ordered_source_layer_snapshot_refs: orderedRefs,
  };
  const consumerInputHash = canonicalHash(consumerInputBody);
  const consumerInputId = `consumer-input:${input.consumerAgentId}:${consumerInputHash.slice(7)}`;
  const resolutionBody = {
    contract: "causal_evidence_resolution_set_v1",
    consumer_agent_id: input.consumerAgentId,
    consumer_input_snapshot_id: consumerInputId,
    consumer_input_snapshot_hash: consumerInputHash,
    ordered_source_layer_snapshot_refs: orderedRefs,
    resolutions: resolutionTuple,
  };
  const resolutionHash = canonicalHash(resolutionBody);
  return {
    resolution_set_id: `causal-resolution:${input.consumerAgentId}:${resolutionHash.slice(7)}`,
    resolution_set_hash: resolutionHash,
    consumer_agent_id: input.consumerAgentId,
    consumer_input_snapshot_id: consumerInputId,
    consumer_input_snapshot_hash: consumerInputHash,
    ordered_source_layer_snapshot_refs: orderedRefs,
    resolutions: resolutionTuple,
  };
}

export function modelVisibleCausalEvidenceResolutionSet(
  set: CausalEvidenceResolutionSet,
): ModelVisibleCausalEvidenceResolutionSet {
  return {
    resolution_set_id: set.resolution_set_id,
    resolution_set_hash: set.resolution_set_hash,
    consumer_input_snapshot_id: set.consumer_input_snapshot_id,
    consumer_input_snapshot_hash: set.consumer_input_snapshot_hash,
    ordered_source_layer_snapshot_refs: set.ordered_source_layer_snapshot_refs,
    resolutions: tuple(
      set.resolutions.map(
        ({ evidence_bundle_ids: _privateBundleIds, ...resolution }) => resolution,
      ),
    ),
  };
}

export function renderCausalEvidenceResolutionSet(input: {
  state: DailyCycleStateType;
  consumerAgentId: AgentId;
  sourceLayers: readonly CausalSourceLayer[];
  acceptedOutputStore?: AcceptedAgentOutputStore;
}): string {
  const set = buildCausalEvidenceResolutionSet(input);
  return [
    "## Causal evidence resolution",
    set
      ? JSON.stringify(modelVisibleCausalEvidenceResolutionSet(set))
      : "* (not available in this standalone fixture)",
  ].join("\n");
}

export function evidenceLineageEnvelope<T>(payload: T): EvidenceLineageEnvelope<T> {
  const graph = verifiedGraph(payload);
  if (!graph) throw new Error("accepted output is missing verified_claim_graph");
  return evidenceLineageEnvelopeFromGraph(payload, graph);
}

/** Build an accepted envelope after runtime-only claim lineage has been stripped from its payload. */
export function evidenceLineageEnvelopeFromGraph<T>(
  payload: T,
  graph: ClaimEvidenceGraph,
): EvidenceLineageEnvelope<T> {
  const keys = sortedUnique(graph.evidence_ledger.map((entry) => entry.source_fingerprint));
  if (keys.length === 0) throw new Error("accepted output has no causal evidence keys");
  return {
    payload,
    evidence_bundle_ids: [graphBundleId(graph)],
    causal_dedupe_keys: tuple(keys),
  };
}

function sourceLayerRefs(
  state: DailyCycleStateType,
  layers: readonly CausalSourceLayer[],
  acceptedOutputStore?: AcceptedAgentOutputStore,
): SourceLayerSnapshotRef[] {
  const refs: SourceLayerSnapshotRef[] = [];
  for (const layer of layers) {
    if (layer === "MACRO") {
      const gate = state.macro_input_gate;
      if (!gate) {
        if (state.darwinian_runtime_binding !== null) {
          throw new Error("MACRO causal source requires macro_input_gate");
        }
        return [];
      }
      refs.push({
        source_layer: layer,
        source_layer_snapshot_id: gate.source_layer_snapshot_id,
        source_layer_snapshot_hash: gate.source_layer_snapshot_hash,
      });
      continue;
    }
    if (layer === "SECTOR") {
      if (
        state.darwinian_runtime_binding === null &&
        Object.keys(state.layer2_outputs).length === 0
      ) {
        if (state.darwinian_runtime_binding !== null) {
          throw new Error("SECTOR causal source requires accepted outputs");
        }
        return [];
      }
      const receipt = deriveSectorUsageReceipt(state, acceptedOutputStore);
      refs.push({
        source_layer: layer,
        source_layer_snapshot_id: receipt.source_layer_snapshot_id,
        source_layer_snapshot_hash: receipt.source_layer_snapshot_hash,
      });
      continue;
    }
    if (layer === "SUPERINVESTOR") {
      const stageSkipCount = SUPERINVESTOR_AGENT_IDS.filter(
        (agentId) => state.outcome_stage_skips[agentId as keyof typeof state.outcome_stage_skips],
      ).length;
      if (
        state.darwinian_runtime_binding === null &&
        Object.keys(state.layer3_outputs).length === 0 &&
        stageSkipCount === 0
      ) {
        if (state.darwinian_runtime_binding !== null) {
          throw new Error("SUPERINVESTOR causal source requires accepted outputs");
        }
        return [];
      }
      const receipt = deriveSuperinvestorUsageReceipt(state, acceptedOutputStore);
      refs.push({
        source_layer: layer,
        source_layer_snapshot_id: receipt.source_layer_snapshot_id,
        source_layer_snapshot_hash: receipt.source_layer_snapshot_hash,
      });
      continue;
    }
    const decisionOutputs = state.darwinian_runtime_binding
      ? acceptedRefsForLayer(state, "DECISION")
      : state.layer4_outputs;
    if (state.darwinian_runtime_binding && Object.keys(decisionOutputs).length === 0) {
      throw new Error("DECISION causal source requires accepted outputs");
    }
    const decisionHash = canonicalHash({
      contract: "decision_source_layer_snapshot_v1",
      outputs: decisionOutputs,
    });
    refs.push({
      source_layer: layer,
      source_layer_snapshot_id: `decision-source-layer:${decisionHash.slice(7)}`,
      source_layer_snapshot_hash: decisionHash,
    });
  }
  return refs;
}

function contributionsForLayer(
  state: DailyCycleStateType,
  layer: CausalSourceLayer,
  acceptedOutputStore?: AcceptedAgentOutputStore,
): EvidenceContribution[] {
  if (state.darwinian_runtime_binding) {
    if (!acceptedOutputStore) {
      throw new Error(`${layer} causal source requires the accepted-output store`);
    }
    const refs = acceptedRefsForLayer(state, layer);
    assertProductionLayerRoster(state, layer, refs);
    const outputContributions = refs.flatMap((ref) => {
      const record = acceptedOutputStore.resolve(ref);
      validateAcceptedSourceBinding(state, record);
      return contributionsForGraph(record.agent_id, acceptedOutputStore.resolveClaimGraph(ref));
    });
    return layer === "SUPERINVESTOR"
      ? [...outputContributions, ...superinvestorSkipContributions(state)]
      : outputContributions;
  }
  const outputs: Array<[string, unknown]> =
    layer === "MACRO"
      ? MACRO_AGENT_IDS.map((agentId) => [agentId, state.layer1_outputs[agentId]])
      : layer === "SECTOR"
        ? Object.entries(state.layer2_outputs)
        : layer === "SUPERINVESTOR"
          ? Object.entries(state.layer3_outputs)
          : Object.entries(state.layer4_outputs).filter(([agentId]) => agentId !== "runtime");
  const outputContributions = outputs.flatMap(([agentId, output]) =>
    contributionsForOutput(agentId, output),
  );
  if (layer !== "SUPERINVESTOR") return outputContributions;
  return [...outputContributions, ...superinvestorSkipContributions(state)];
}

function superinvestorSkipContributions(state: DailyCycleStateType): EvidenceContribution[] {
  return SUPERINVESTOR_AGENT_IDS.flatMap((agentId) => {
    const skip = state.outcome_stage_skips[agentId as keyof typeof state.outcome_stage_skips];
    if (!skip) return [];
    return [
      {
        causalKey: skip.causal_dedupe_key,
        evidenceBundleId: `stage-skip-bundle:${skip.stage_skip_hash.slice(7)}`,
        agentId: agentId as AgentId,
        claimRef: `stage-skip:${skip.stage_skip_id}`,
        polarity: null,
      } satisfies EvidenceContribution,
    ];
  });
}

function contributionsForOutput(agentId: string, output: unknown): EvidenceContribution[] {
  const graph = verifiedGraph(output);
  if (!graph) return [];
  return contributionsForGraph(agentId, graph);
}

function contributionsForGraph(agentId: string, graph: ClaimEvidenceGraph): EvidenceContribution[] {
  const evidenceById = new Map(graph.evidence_ledger.map((entry) => [entry.evidence_id, entry]));
  const bundleId = graphBundleId(graph);
  return graph.claims.flatMap((claim) =>
    claim.evidence_ids.map((evidenceId) => {
      const evidence = evidenceById.get(evidenceId);
      if (!evidence)
        throw new Error(`${agentId}:${claim.claim_id}: unresolved evidence ${evidenceId}`);
      return {
        causalKey: evidence.source_fingerprint,
        evidenceBundleId: bundleId,
        agentId: agentId as AgentId,
        claimRef: claim.claim_id,
        polarity: interpretationPolarity(claim),
      };
    }),
  );
}

function acceptedRefsForLayer(
  state: DailyCycleStateType,
  layer: CausalSourceLayer,
): AcceptedOutputRecordRef[] {
  const kinds = ACCEPTED_KINDS_BY_CAUSAL_LAYER[layer];
  return Object.values(state.accepted_output_refs)
    .filter((ref) => kinds.has(ref.accepted_output_kind))
    .sort((left, right) => left.accepted_output_id.localeCompare(right.accepted_output_id));
}

const ACCEPTED_KINDS_BY_CAUSAL_LAYER: Readonly<
  Record<CausalSourceLayer, ReadonlySet<AcceptedOutputKind>>
> = {
  MACRO: new Set(["MACRO_TRANSMISSION"]),
  SECTOR: new Set(["STANDARD_SECTOR_SELECTION", "RELATIONSHIP_GRAPH"]),
  SUPERINVESTOR: new Set(["SUPERINVESTOR_SELECTION"]),
  DECISION: new Set([
    "CRO_RISK_REVIEW",
    "ALPHA_DISCOVERY",
    "EXECUTION_ASSESSMENT",
    "CIO_PROPOSAL",
    "CIO_FINAL",
  ]),
};

function assertProductionLayerRoster(
  state: DailyCycleStateType,
  layer: CausalSourceLayer,
  refs: ReadonlyArray<AcceptedOutputRecordRef>,
): void {
  const acceptedAgents = refs.map((ref) => ref.agent_id).sort();
  const expected =
    layer === "MACRO"
      ? [...MACRO_AGENT_IDS].sort()
      : layer === "SECTOR"
        ? [...SECTOR_AGENT_IDS].sort()
        : layer === "SUPERINVESTOR"
          ? SUPERINVESTOR_AGENT_IDS.filter((agentId) => !state.outcome_stage_skips[agentId]).sort()
          : null;
  if (expected && acceptedAgents.join("\0") !== expected.join("\0")) {
    throw new Error(`${layer} causal source accepted roster mismatch`);
  }
  if (layer === "DECISION" && refs.length === 0) {
    throw new Error("DECISION causal source accepted roster is empty");
  }
}

function validateAcceptedSourceBinding(
  state: DailyCycleStateType,
  record: AcceptedAgentOutputRecord,
): void {
  const binding = state.darwinian_runtime_binding;
  if (!binding) throw new Error("accepted source binding requires production runtime");
  if (
    record.graph_run_id !== state.trace_id ||
    record.as_of !== (state.outcome_schedule_plan?.as_of ?? state.as_of_date) ||
    record.cohort_id !== state.active_cohort ||
    record.language !== binding.language ||
    record.sample_origin !== "PRODUCTION_ACTIVE" ||
    record.production_variant_roster_id !== binding.production_variant_roster_id ||
    record.execution_behavior_release_id !== binding.execution_behavior_release_id
  ) {
    throw new Error(`${record.agent_id}: accepted causal source binding mismatch`);
  }
}

function verifiedGraph(output: unknown): ClaimEvidenceGraph | null {
  if (output === null || typeof output !== "object" || Array.isArray(output)) return null;
  const graph = (output as { verified_claim_graph?: ClaimEvidenceGraph }).verified_claim_graph;
  return graph ?? null;
}

function graphBundleId(graph: ClaimEvidenceGraph): string {
  return `evidence-bundle:${graph.run_id}:${graph.snapshot_hash.slice(7)}`;
}

function interpretationPolarity(claim: Claim): "POSITIVE" | "NEGATIVE" | "UNSPECIFIED" | null {
  if (claim.claim_kind !== "INTERPRETATION") return null;
  const values = flattenScalars(claim.structured_conclusion).map((value) =>
    String(value).trim().toLowerCase(),
  );
  const positive = values.some((value) => POSITIVE_VALUES.has(value));
  const negative = values.some((value) => NEGATIVE_VALUES.has(value));
  if (positive && !negative) return "POSITIVE";
  if (negative && !positive) return "NEGATIVE";
  return "UNSPECIFIED";
}

const POSITIVE_VALUES = new Set([
  "supportive",
  "positive",
  "bullish",
  "broadening",
  "easing",
  "expansionary",
  "improving",
  "upside",
  "risk_on",
  "overweight",
  "long",
  "buy",
]);

const NEGATIVE_VALUES = new Set([
  "adverse",
  "negative",
  "bearish",
  "narrowing",
  "tightening",
  "contractionary",
  "deteriorating",
  "downside",
  "risk_off",
  "underweight",
  "short",
  "sell",
]);

function flattenScalars(value: unknown): Array<string | number | boolean> {
  if (value === null || value === undefined) return [];
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return [value];
  }
  if (Array.isArray(value)) return value.flatMap(flattenScalars);
  if (typeof value === "object") return Object.values(value).flatMap(flattenScalars);
  return [];
}

function tuple<T>(values: T[]): [T, ...T[]] {
  const first = values[0];
  if (first === undefined) throw new Error("causal evidence tuple must be non-empty");
  return [first, ...values.slice(1)];
}

function sortedUnique<T extends string>(values: readonly T[]): T[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
}

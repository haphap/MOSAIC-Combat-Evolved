import type { BaseMessage } from "@langchain/core/messages";
import { z } from "zod";
import type { DarwinianAgentBehaviorBinding } from "../../autoresearch/production_variant.js";
import { canonicalJsonHash } from "../helpers/canonical_json.js";
import type { AcceptedMacroInputAttribution } from "../helpers/macro_attribution.js";
import type { ToolStatus } from "../helpers/private_knot_boundary.js";
import type { RelationshipMapperOutput } from "../types.js";

const Sha256 = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const NonEmpty = z
  .string()
  .min(1)
  .max(128)
  .refine((value) => value === value.trim(), "must already be trimmed");
const AShareSecurityCodePattern = /^\d{6}\.(?:SH|SZ|BJ)$/;
const IsoDatePattern = /^(\d{4})-(\d{2})-(\d{2})$/;
const ZonedTimestampPattern =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|[+-](\d{2}):(\d{2}))$/;
const HolderId = NonEmpty.refine(
  (value) => !AShareSecurityCodePattern.test(value),
  "must identify a holder, not a security",
);
const SecurityId = NonEmpty.refine(
  (value) => AShareSecurityCodePattern.test(value),
  "must be a canonical A-share security code",
);
const ConciseText = z
  .string()
  .min(1)
  .max(320)
  .refine((value) => value === value.trim(), "must already be trimmed");
const IsoDate = z
  .string()
  .regex(IsoDatePattern)
  .refine((value) => {
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
  }, "must be a valid ISO date");
const RELATIONSHIP_SNAPSHOT_MAX_EDGES = 32;
const RELATIONSHIP_SNAPSHOT_MAX_EVIDENCE = 128;

const RelationshipMatchedNonEdgeSchema = z
  .object({
    source_entity: HolderId,
    source_entity_type: z.literal("HOLDER"),
    target_entity: SecurityId,
    target_entity_type: z.literal("PIT_ELIGIBLE_SECURITY"),
    target_sector_id: NonEmpty,
    edge_type: NonEmpty,
    materiality_bucket: z.enum(["LOW", "MEDIUM", "HIGH"]),
  })
  .strict();

export const RelationshipPredictionOpportunitySchema = z
  .object({
    edge_candidate_id: NonEmpty,
    source_entity: HolderId,
    source_entity_type: z.literal("HOLDER"),
    target_entity: SecurityId,
    target_entity_type: z.literal("PIT_ELIGIBLE_SECURITY"),
    target_sector_id: NonEmpty,
    edge_type: NonEmpty,
    materiality_weight: z.number().finite().positive(),
    materiality_bucket: z.enum(["LOW", "MEDIUM", "HIGH"]),
    matched_non_edge_set_id: NonEmpty,
    matched_non_edge_set_hash: Sha256,
    matched_non_edges: z
      .array(RelationshipMatchedNonEdgeSchema)
      .min(1)
      .max(RELATIONSHIP_SNAPSHOT_MAX_EDGES),
  })
  .strict()
  .superRefine((opportunity, ctx) => {
    if (
      opportunity.materiality_bucket !==
      relationshipMaterialityBucket(opportunity.materiality_weight)
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["materiality_bucket"],
        message: "materiality bucket does not match weight",
      });
    }
    const tupleKeys = opportunity.matched_non_edges.map(relationshipTupleKey);
    if (
      new Set(tupleKeys).size !== tupleKeys.length ||
      tupleKeys.join("\0") !== [...tupleKeys].sort().join("\0")
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["matched_non_edges"],
        message: "matched non-edges must be unique and canonically ordered",
      });
    }
    const candidateKey = relationshipTupleKey(opportunity);
    if (tupleKeys.includes(candidateKey)) {
      ctx.addIssue({
        code: "custom",
        path: ["matched_non_edges"],
        message: "matched non-edges contain the candidate edge",
      });
    }
    opportunity.matched_non_edges.forEach((matched, index) => {
      if (
        matched.source_entity !== opportunity.source_entity ||
        matched.source_entity_type !== opportunity.source_entity_type ||
        matched.target_entity_type !== opportunity.target_entity_type ||
        matched.target_sector_id !== opportunity.target_sector_id ||
        matched.edge_type !== opportunity.edge_type ||
        matched.materiality_bucket !== opportunity.materiality_bucket ||
        matched.target_entity === opportunity.target_entity
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["matched_non_edges", index],
          message: "violates typed holder-to-security matching",
        });
      }
    });
    if (opportunity.matched_non_edge_set_hash !== canonicalHash(opportunity.matched_non_edges)) {
      ctx.addIssue({
        code: "custom",
        path: ["matched_non_edge_set_hash"],
        message: "matched non-edge set hash mismatch",
      });
    }
  });

export const FrozenRelationshipPredictionOpportunitySetSchema = z
  .object({
    opportunity_set_id: NonEmpty,
    opportunity_set_hash: Sha256,
    run_id: NonEmpty,
    as_of: IsoDate,
    candidate_generation_contract_version: NonEmpty,
    scoring_contract_version: NonEmpty,
    ordered_opportunities: z
      .array(RelationshipPredictionOpportunitySchema)
      .min(1)
      .max(RELATIONSHIP_SNAPSHOT_MAX_EDGES),
  })
  .strict()
  .superRefine((set, ctx) => {
    const ids = set.ordered_opportunities.map((row) => row.edge_candidate_id);
    if (new Set(ids).size !== ids.length) {
      ctx.addIssue({
        code: "custom",
        path: ["ordered_opportunities"],
        message: "duplicate candidate",
      });
    }
    if (ids.join("\0") !== [...ids].sort().join("\0")) {
      ctx.addIssue({
        code: "custom",
        path: ["ordered_opportunities"],
        message: "opportunities must use canonical candidate order",
      });
    }
    const { opportunity_set_id: _id, opportunity_set_hash: _hash, ...body } = set;
    const expectedHash = canonicalHash(body);
    if (set.opportunity_set_hash !== expectedHash) {
      ctx.addIssue({ code: "custom", path: ["opportunity_set_hash"], message: "hash mismatch" });
    }
    if (set.opportunity_set_id !== `relationship-opportunity:${expectedHash.slice(7)}`) {
      ctx.addIssue({ code: "custom", path: ["opportunity_set_id"], message: "id mismatch" });
    }
  });

const RelationshipEvidenceSchema = z
  .object({
    evidence_id: NonEmpty,
    evidence_kind: NonEmpty,
    source_id: NonEmpty,
    source_endpoint: NonEmpty,
    observation_date: NonEmpty,
    released_at: NonEmpty,
    vintage_at: NonEmpty,
    pit_status: z.literal("PIT_VERIFIED"),
    content_hash: Sha256,
    evidence_record_hash: Sha256,
  })
  .strict();

const RelationshipSnapshotRowSchema = z
  .object({
    edge_candidate_id: NonEmpty,
    source_entity: HolderId,
    source_entity_type: z.literal("HOLDER"),
    target_entity: SecurityId,
    target_entity_type: z.literal("PIT_ELIGIBLE_SECURITY"),
    target_sector_id: NonEmpty,
    edge_type: NonEmpty,
    activation_trigger: ConciseText,
    observation_date: NonEmpty,
    released_at: NonEmpty,
    vintage_at: NonEmpty,
    pit_status: z.literal("PIT_VERIFIED"),
    evidence_ids: z.array(NonEmpty).min(1).max(32),
    relationship_row_hash: Sha256,
  })
  .strict();

export const RelationshipResearchSnapshotSchema = z
  .object({
    schema_version: z.literal("relationship_research_snapshot_v3"),
    as_of_date: IsoDate,
    frozen_holder_domain_hash: Sha256,
    frozen_security_domain_hash: Sha256,
    relationships: z
      .array(RelationshipSnapshotRowSchema)
      .min(1)
      .max(RELATIONSHIP_SNAPSHOT_MAX_EDGES),
    prediction_opportunity_set: FrozenRelationshipPredictionOpportunitySetSchema,
    evidence_catalog: z
      .array(RelationshipEvidenceSchema)
      .min(1)
      .max(RELATIONSHIP_SNAPSHOT_MAX_EVIDENCE),
    evidence_catalog_hash: Sha256,
    snapshot_hash: Sha256,
    fixture_class: z.literal("SYNTHETIC_NON_PRODUCTION").optional(),
  })
  .strict()
  .superRefine((snapshot, ctx) => {
    const asOfCutoff = parseTemporal(`${snapshot.as_of_date}T07:00:00Z`);
    if (asOfCutoff === null) {
      ctx.addIssue({ code: "custom", path: ["as_of_date"], message: "invalid as_of_date" });
      return;
    }
    if (snapshot.prediction_opportunity_set.as_of !== snapshot.as_of_date) {
      ctx.addIssue({
        code: "custom",
        path: ["prediction_opportunity_set", "as_of"],
        message: "opportunity set as_of does not match snapshot as_of_date",
      });
    }
    const evidenceIds = snapshot.evidence_catalog.map((row) => row.evidence_id);
    if (
      new Set(evidenceIds).size !== evidenceIds.length ||
      evidenceIds.join("\0") !== [...evidenceIds].sort().join("\0")
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["evidence_catalog"],
        message: "evidence catalog must be unique and canonically ordered",
      });
    }
    snapshot.evidence_catalog.forEach((evidence, index) => {
      validatePitTemporals(evidence, asOfCutoff, ["evidence_catalog", index], ctx);
      const { evidence_record_hash: _hash, ...body } = evidence;
      if (evidence.evidence_record_hash !== canonicalHash(body)) {
        ctx.addIssue({
          code: "custom",
          path: ["evidence_catalog", index, "evidence_record_hash"],
          message: "evidence record hash mismatch",
        });
      }
    });
    if (snapshot.evidence_catalog_hash !== canonicalHash(snapshot.evidence_catalog)) {
      ctx.addIssue({
        code: "custom",
        path: ["evidence_catalog_hash"],
        message: "evidence catalog hash mismatch",
      });
    }
    const relationshipIds = snapshot.relationships.map((row) => row.edge_candidate_id);
    if (new Set(relationshipIds).size !== relationshipIds.length) {
      ctx.addIssue({
        code: "custom",
        path: ["relationships"],
        message: "duplicate frozen edge_candidate_id",
      });
    }
    if (relationshipIds.join("\0") !== [...relationshipIds].sort().join("\0")) {
      ctx.addIssue({
        code: "custom",
        path: ["relationships"],
        message: "relationships must use canonical candidate order",
      });
    }
    const relationshipTuples = snapshot.relationships.map(relationshipTupleKey);
    if (new Set(relationshipTuples).size !== relationshipTuples.length) {
      ctx.addIssue({
        code: "custom",
        path: ["relationships"],
        message: "duplicate factual relationship tuple",
      });
    }
    const referencedEvidence = new Set<string>();
    snapshot.relationships.forEach((relationship, index) => {
      validatePitTemporals(relationship, asOfCutoff, ["relationships", index], ctx);
      if (
        new Set(relationship.evidence_ids).size !== relationship.evidence_ids.length ||
        relationship.evidence_ids.join("\0") !== [...relationship.evidence_ids].sort().join("\0")
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["relationships", index, "evidence_ids"],
          message: "relationship evidence ids must be unique and canonically ordered",
        });
      }
      relationship.evidence_ids.forEach((id) => {
        referencedEvidence.add(id);
      });
      const { relationship_row_hash: _hash, ...body } = relationship;
      if (relationship.relationship_row_hash !== canonicalHash(body)) {
        ctx.addIssue({
          code: "custom",
          path: ["relationships", index, "relationship_row_hash"],
          message: "relationship row hash mismatch",
        });
      }
    });
    const holderDomain = [
      ...new Set([
        ...snapshot.relationships.map((row) => row.source_entity),
        ...snapshot.prediction_opportunity_set.ordered_opportunities.flatMap((row) =>
          row.matched_non_edges.map((matched) => matched.source_entity),
        ),
      ]),
    ].sort();
    const securityDomain = [
      ...new Set([
        ...snapshot.relationships.map((row) => row.target_entity),
        ...snapshot.prediction_opportunity_set.ordered_opportunities.flatMap((row) =>
          row.matched_non_edges.map((matched) => matched.target_entity),
        ),
      ]),
    ].sort();
    if (snapshot.frozen_holder_domain_hash !== canonicalHash(holderDomain)) {
      ctx.addIssue({
        code: "custom",
        path: ["frozen_holder_domain_hash"],
        message: "frozen holder domain hash mismatch",
      });
    }
    if (snapshot.frozen_security_domain_hash !== canonicalHash(securityDomain)) {
      ctx.addIssue({
        code: "custom",
        path: ["frozen_security_domain_hash"],
        message: "frozen security domain hash mismatch",
      });
    }
    const evidenceIdSet = new Set(evidenceIds);
    if (
      [...referencedEvidence].some((id) => !evidenceIdSet.has(id)) ||
      evidenceIds.some((id) => !referencedEvidence.has(id))
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["evidence_catalog"],
        message: "relationship evidence closure mismatch",
      });
    }
    const relationshipById = new Map(
      snapshot.relationships.map((row) => [row.edge_candidate_id, row]),
    );
    snapshot.prediction_opportunity_set.ordered_opportunities.forEach((opportunity, index) => {
      const relationship = relationshipById.get(opportunity.edge_candidate_id);
      if (
        !relationship ||
        relationship.source_entity !== opportunity.source_entity ||
        relationship.source_entity_type !== opportunity.source_entity_type ||
        relationship.target_entity !== opportunity.target_entity ||
        relationship.target_entity_type !== opportunity.target_entity_type ||
        relationship.target_sector_id !== opportunity.target_sector_id ||
        relationship.edge_type !== opportunity.edge_type
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["prediction_opportunity_set", "ordered_opportunities", index],
          message: "opportunity does not match the frozen relationship domain",
        });
      }
    });
    const { snapshot_hash: _snapshotHash, ...snapshotBody } = snapshot;
    if (snapshot.snapshot_hash !== canonicalHash(snapshotBody)) {
      ctx.addIssue({ code: "custom", path: ["snapshot_hash"], message: "snapshot hash mismatch" });
    }
  });

export type FrozenRelationshipPredictionOpportunitySet = z.infer<
  typeof FrozenRelationshipPredictionOpportunitySetSchema
>;
export type RelationshipResearchSnapshot = z.infer<typeof RelationshipResearchSnapshotSchema>;

export interface AcceptedRelationshipFactualEdge {
  edge_id: string;
  edge_hash: string;
  edge_candidate_id: string;
  relationship_row_hash: string;
  source_entity: string;
  source_entity_type: "HOLDER";
  target_entity: string;
  target_entity_type: "PIT_ELIGIBLE_SECURITY";
  target_sector_id: string;
  edge_type: string;
  activation_trigger: string;
  evidence_ids: string[];
  claim_refs: string[];
}

export interface AcceptedRelationshipPredictiveEdge {
  edge_id: string;
  edge_hash: string;
  edge_candidate_id: string;
  source_entity: string;
  target_entity: string;
  edge_type: string;
  transmission_direction: "POSITIVE" | "NEGATIVE" | "MIXED";
  activation_trigger: string;
  evaluation_horizon_trading_days: 20;
  model_confidence: number;
  calibrated_confidence: number;
  calibration_state_id: string;
  calibration_state_effective_at: string;
  claim_refs: string[];
}

export interface AcceptedRelationshipGraph {
  relationship_agent_id: "relationship_mapper";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  relationship_snapshot_hash: string;
  frozen_holder_domain_hash: string;
  frozen_security_domain_hash: string;
  opportunity_set_id: string;
  opportunity_set_hash: string;
  factual_edges: AcceptedRelationshipFactualEdge[];
  predictive_edges: AcceptedRelationshipPredictiveEdge[];
  predictive_graph_status: "EDGES_PRESENT" | "NO_QUALIFIED_PREDICTIVE_EDGE";
  predictive_graph_abstention_confidence: number | null;
  key_drivers: RelationshipMapperOutput["key_drivers"];
  risks: RelationshipMapperOutput["risks"];
  claims: RelationshipMapperOutput["claims"];
  claim_refs: string[];
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  directional_confidence: number;
}

export interface ModelVisibleAcceptedRelationshipGraph {
  relationship_agent_id: "relationship_mapper";
  factual_edges: Array<
    Omit<
      AcceptedRelationshipFactualEdge,
      "edge_id" | "edge_hash" | "edge_candidate_id" | "relationship_row_hash"
    >
  >;
  predictive_edges: Array<
    Omit<
      AcceptedRelationshipPredictiveEdge,
      | "edge_id"
      | "edge_hash"
      | "edge_candidate_id"
      | "model_confidence"
      | "calibration_state_id"
      | "calibration_state_effective_at"
    >
  >;
  predictive_graph_status: "EDGES_PRESENT" | "NO_QUALIFIED_PREDICTIVE_EDGE";
  key_drivers: RelationshipMapperOutput["key_drivers"];
  risks: RelationshipMapperOutput["risks"];
  claims: RelationshipMapperOutput["claims"];
  claim_refs: string[];
  directional_confidence: number;
}

export function relationshipOpportunitySetFromToolLoop(input: {
  messages: readonly BaseMessage[];
  toolStatuses: readonly ToolStatus[];
  runId: string;
  asOf: string;
}): FrozenRelationshipPredictionOpportunitySet {
  const parsed = relationshipResearchSnapshotFromToolLoop(input);
  if (
    parsed.as_of_date !== input.asOf ||
    parsed.prediction_opportunity_set.as_of !== input.asOf ||
    parsed.prediction_opportunity_set.run_id !== input.runId
  ) {
    throw new Error("relationship opportunity snapshot run binding mismatch");
  }
  return parsed.prediction_opportunity_set;
}

export function relationshipFactualEdgeCapacityFromToolLoop(input: {
  messages: readonly BaseMessage[];
  toolStatuses: readonly ToolStatus[];
}): number {
  return relationshipFactualEdgeCandidatesFromToolLoop(input).length;
}

export function relationshipFactualEdgeCandidatesFromToolLoop(input: {
  messages: readonly BaseMessage[];
  toolStatuses: readonly ToolStatus[];
}): Array<{ source_entity: string; target_entity: string; edge_type: string }> {
  const relationships = relationshipResearchSnapshotFromToolLoop(input).relationships.map(
    ({ source_entity, target_entity, edge_type }) => ({
      source_entity,
      target_entity,
      edge_type,
    }),
  );
  assertUniqueFactualRelationshipTuples(
    relationships,
    "frozen relationship snapshot contains duplicate factual relationship tuple",
  );
  return relationships;
}

export function relationshipResearchSnapshotFromToolLoop(input: {
  messages: readonly BaseMessage[];
  toolStatuses: readonly ToolStatus[];
}): RelationshipResearchSnapshot {
  return RelationshipResearchSnapshotSchema.parse(relationshipSnapshotPayloadFromToolLoop(input));
}

function relationshipSnapshotPayloadFromToolLoop(input: {
  messages: readonly BaseMessage[];
  toolStatuses: readonly ToolStatus[];
}): unknown {
  const status = [...input.toolStatuses]
    .reverse()
    .find(
      (row) =>
        row.name === "get_relationship_graph_snapshot" &&
        row.called &&
        !row.failed &&
        !row.missing &&
        !row.fallback,
    );
  if (!status?.call_id) throw new Error("relationship opportunity snapshot was not accepted");
  const message = [...input.messages]
    .reverse()
    .find(
      (row) =>
        row.getType() === "tool" &&
        (row as BaseMessage & { tool_call_id?: string }).tool_call_id === status.call_id,
    );
  if (typeof message?.content !== "string") {
    throw new Error("relationship opportunity snapshot payload is unavailable");
  }
  try {
    return JSON.parse(message.content);
  } catch (cause) {
    throw new Error("relationship opportunity snapshot payload is invalid", { cause });
  }
}

export function buildAcceptedRelationshipGraph(input: {
  output: RelationshipMapperOutput;
  behavior: DarwinianAgentBehaviorBinding;
  relationshipSnapshot: RelationshipResearchSnapshot;
  acceptedMacroInputAttributions: AcceptedMacroInputAttribution[];
  calibrationEffectiveAt: string;
}): AcceptedRelationshipGraph {
  const relationshipSnapshot = RelationshipResearchSnapshotSchema.parse(input.relationshipSnapshot);
  const opportunitySet = relationshipSnapshot.prediction_opportunity_set;
  const opportunityIssues = validateRelationshipOutputAgainstSnapshot(
    input.output,
    relationshipSnapshot,
  );
  if (opportunityIssues.length > 0) throw new Error(opportunityIssues.join("; "));
  const opportunityById = new Map(
    opportunitySet.ordered_opportunities.map((row) => [row.edge_candidate_id, row]),
  );
  const submittedFactualByTuple = new Map(
    input.output.factual_edges.map((edge) => [factualRelationshipTupleKey(edge), edge]),
  );
  const factualEdges = relationshipSnapshot.relationships.map((relationship) =>
    acceptedFactualEdge(
      relationship,
      submittedFactualByTuple.get(factualRelationshipTupleKey(relationship))?.claim_refs ?? [],
    ),
  );
  if (
    new Set(factualEdges.map((edge) => edge.edge_id)).size !== factualEdges.length ||
    new Set(factualEdges.map((edge) => edge.edge_hash)).size !== factualEdges.length
  ) {
    throw new Error("accepted factual relationship edge identity collision");
  }
  const predictiveEdges = input.output.predictive_edges.map((edge) => {
    const opportunity = opportunityById.get(edge.edge_candidate_id);
    if (
      !opportunity ||
      opportunity.source_entity !== edge.source_entity ||
      opportunity.target_entity !== edge.target_entity ||
      opportunity.edge_type !== edge.edge_type
    ) {
      throw new Error(
        `relationship edge is outside the frozen opportunity set: ${edge.edge_candidate_id}`,
      );
    }
    const body = {
      edge_candidate_id: edge.edge_candidate_id,
      source_entity: edge.source_entity,
      target_entity: edge.target_entity,
      edge_type: edge.edge_type,
      transmission_direction: edge.transmission_direction,
      activation_trigger: edge.activation_trigger,
      evaluation_horizon_trading_days: edge.evaluation_horizon_trading_days,
      model_confidence: edge.model_confidence,
      calibrated_confidence: edge.model_confidence,
      calibration_state_id: "relationship_edge_identity_cold_start_v1",
      calibration_state_effective_at: input.calibrationEffectiveAt,
      claim_refs: edge.claim_refs,
    };
    const edgeHash = canonicalHash(body);
    return {
      edge_id: `relationship-predictive-edge:${edgeHash.slice(7)}`,
      edge_hash: edgeHash,
      ...body,
    };
  });
  const weightedConfidence = predictiveEdges.reduce(
    (sum, edge) =>
      sum +
      edge.calibrated_confidence *
        (opportunityById.get(edge.edge_candidate_id)?.materiality_weight ?? 0),
    0,
  );
  const submittedWeight = predictiveEdges.reduce(
    (sum, edge) => sum + (opportunityById.get(edge.edge_candidate_id)?.materiality_weight ?? 0),
    0,
  );
  return {
    relationship_agent_id: "relationship_mapper",
    agent_contract_version: input.behavior.agent_contract_version,
    prompt_behavior_version: input.behavior.prompt_behavior_version,
    execution_behavior_version: input.behavior.execution_behavior_version,
    relationship_snapshot_hash: relationshipSnapshot.snapshot_hash,
    frozen_holder_domain_hash: relationshipSnapshot.frozen_holder_domain_hash,
    frozen_security_domain_hash: relationshipSnapshot.frozen_security_domain_hash,
    opportunity_set_id: opportunitySet.opportunity_set_id,
    opportunity_set_hash: opportunitySet.opportunity_set_hash,
    factual_edges: factualEdges,
    predictive_edges: predictiveEdges,
    predictive_graph_status: input.output.predictive_graph_status,
    predictive_graph_abstention_confidence: input.output.predictive_graph_abstention_confidence,
    key_drivers: input.output.key_drivers,
    risks: input.output.risks,
    claims: input.output.claims,
    claim_refs: input.output.claim_refs,
    accepted_macro_input_attributions: input.acceptedMacroInputAttributions,
    directional_confidence: submittedWeight > 0 ? weightedConfidence / submittedWeight : 0,
  };
}

export function validateRelationshipOutputAgainstSnapshot(
  output: RelationshipMapperOutput,
  snapshot: RelationshipResearchSnapshot,
): string[] {
  const parsed = RelationshipResearchSnapshotSchema.parse(snapshot);
  const issues = validateRelationshipOutputAgainstOpportunitySet(
    output,
    parsed.prediction_opportunity_set,
  );
  const factualDomain = new Set(parsed.relationships.map(factualRelationshipTupleKey));
  const submittedFactual = new Set(output.factual_edges.map(factualRelationshipTupleKey));
  for (const edge of output.factual_edges) {
    if (!factualDomain.has(factualRelationshipTupleKey(edge))) {
      issues.push(
        `factual relationship is outside the frozen snapshot domain: ${edge.source_entity}->${edge.target_entity}:${edge.edge_type}`,
      );
    }
  }
  if (
    submittedFactual.size !== factualDomain.size ||
    [...factualDomain].some((tuple) => !submittedFactual.has(tuple))
  ) {
    issues.push("factual relationships must exactly equal the frozen snapshot domain");
  }
  return issues;
}

export function validateRelationshipOutputAgainstOpportunitySet(
  output: RelationshipMapperOutput,
  opportunitySet: FrozenRelationshipPredictionOpportunitySet,
): string[] {
  const opportunityById = new Map(
    opportunitySet.ordered_opportunities.map((row) => [row.edge_candidate_id, row]),
  );
  const issues: string[] = [];
  const factualLocalIds = new Set<string>();
  const factualTuples = new Set<string>();
  for (const edge of output.factual_edges) {
    if (factualLocalIds.has(edge.edge_local_id)) {
      issues.push(`duplicate factual edge_local_id ${edge.edge_local_id}`);
    }
    factualLocalIds.add(edge.edge_local_id);
    const tuple = factualRelationshipTupleKey(edge);
    if (factualTuples.has(tuple)) {
      issues.push(
        `duplicate factual relationship tuple ${edge.source_entity}->${edge.target_entity}:${edge.edge_type}`,
      );
    }
    factualTuples.add(tuple);
  }
  const predictiveCandidateIds = new Set<string>();
  for (const edge of output.predictive_edges) {
    if (predictiveCandidateIds.has(edge.edge_candidate_id)) {
      issues.push(`duplicate predictive edge_candidate_id ${edge.edge_candidate_id}`);
    }
    predictiveCandidateIds.add(edge.edge_candidate_id);
    const opportunity = opportunityById.get(edge.edge_candidate_id);
    if (!opportunity) {
      issues.push(`unknown edge_candidate_id ${edge.edge_candidate_id}`);
      continue;
    }
    for (const field of ["source_entity", "target_entity", "edge_type"] as const) {
      if (edge[field] !== opportunity[field]) {
        issues.push(`${edge.edge_candidate_id}:${field} does not match frozen opportunity`);
      }
    }
  }
  return issues;
}

export function modelVisibleAcceptedRelationshipGraph(
  accepted: AcceptedRelationshipGraph,
): ModelVisibleAcceptedRelationshipGraph {
  return {
    relationship_agent_id: accepted.relationship_agent_id,
    factual_edges: accepted.factual_edges.map(
      ({
        edge_id: _id,
        edge_hash: _hash,
        edge_candidate_id: _candidate,
        relationship_row_hash: _rowHash,
        ...edge
      }) => edge,
    ),
    predictive_edges: accepted.predictive_edges.map(
      ({
        edge_id: _id,
        edge_hash: _hash,
        edge_candidate_id: _candidate,
        model_confidence: _model,
        calibration_state_id: _state,
        calibration_state_effective_at: _effectiveAt,
        ...edge
      }) => edge,
    ),
    predictive_graph_status: accepted.predictive_graph_status,
    key_drivers: accepted.key_drivers,
    risks: accepted.risks,
    claims: accepted.claims,
    claim_refs: accepted.claim_refs,
    directional_confidence: accepted.directional_confidence,
  };
}

function acceptedFactualEdge(
  relationship: RelationshipResearchSnapshot["relationships"][number],
  claimRefs: string[],
): AcceptedRelationshipFactualEdge {
  const immutableFact = {
    edge_candidate_id: relationship.edge_candidate_id,
    relationship_row_hash: relationship.relationship_row_hash,
    source_entity: relationship.source_entity,
    source_entity_type: relationship.source_entity_type,
    target_entity: relationship.target_entity,
    target_entity_type: relationship.target_entity_type,
    target_sector_id: relationship.target_sector_id,
    edge_type: relationship.edge_type,
    activation_trigger: relationship.activation_trigger,
    evidence_ids: relationship.evidence_ids,
  };
  const edgeHash = canonicalHash(immutableFact);
  return {
    edge_id: `relationship-factual-edge:${edgeHash.slice(7)}`,
    edge_hash: edgeHash,
    ...immutableFact,
    claim_refs: claimRefs,
  };
}

function assertUniqueFactualRelationshipTuples(
  relationships: readonly { source_entity: string; target_entity: string; edge_type: string }[],
  message: string,
): void {
  const tuples = relationships.map(factualRelationshipTupleKey);
  if (new Set(tuples).size !== tuples.length) throw new Error(message);
}

function factualRelationshipTupleKey(relationship: {
  source_entity: string;
  target_entity: string;
  edge_type: string;
}): string {
  return JSON.stringify([
    relationship.source_entity,
    relationship.target_entity,
    relationship.edge_type,
  ]);
}

function relationshipTupleKey(relationship: {
  source_entity: string;
  target_entity: string;
  edge_type: string;
}): string {
  return factualRelationshipTupleKey(relationship);
}

function relationshipMaterialityBucket(weight: number): "LOW" | "MEDIUM" | "HIGH" {
  if (weight < 1) return "LOW";
  if (weight < 5) return "MEDIUM";
  return "HIGH";
}

function parseTemporal(value: string): number | null {
  const dateMatch = IsoDatePattern.exec(value);
  if (dateMatch) {
    const [, year, month, day] = dateMatch;
    if (!validCalendarDate(year, month, day)) return null;
    return Date.parse(`${value}T00:00:00Z`);
  }
  const timestampMatch = ZonedTimestampPattern.exec(value);
  if (!timestampMatch) return null;
  const [, year, month, day, hour, minute, second, offsetHour, offsetMinute] = timestampMatch;
  if (
    !validCalendarDate(year, month, day) ||
    Number(hour) > 23 ||
    Number(minute) > 59 ||
    Number(second) > 59 ||
    (offsetHour !== undefined && Number(offsetHour) > 23) ||
    (offsetMinute !== undefined && Number(offsetMinute) > 59)
  ) {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function validCalendarDate(
  year: string | undefined,
  month: string | undefined,
  day: string | undefined,
) {
  const yearNumber = Number(year);
  const monthNumber = Number(month);
  const dayNumber = Number(day);
  if (
    !Number.isInteger(yearNumber) ||
    yearNumber < 1000 ||
    yearNumber > 9999 ||
    !Number.isInteger(monthNumber) ||
    monthNumber < 1 ||
    monthNumber > 12 ||
    !Number.isInteger(dayNumber) ||
    dayNumber < 1
  ) {
    return false;
  }
  return dayNumber <= new Date(Date.UTC(yearNumber, monthNumber, 0)).getUTCDate();
}

function validatePitTemporals(
  value: { observation_date: string; released_at: string; vintage_at: string },
  asOfEnd: number,
  path: Array<string | number>,
  ctx: z.RefinementCtx,
): void {
  const observation = parseTemporal(value.observation_date);
  const released = parseTemporal(value.released_at);
  const vintage = parseTemporal(value.vintage_at);
  if (
    observation === null ||
    released === null ||
    vintage === null ||
    observation > released ||
    released > vintage ||
    vintage > asOfEnd
  ) {
    ctx.addIssue({
      code: "custom",
      path,
      message: "violates observation <= release <= vintage <= as_of",
    });
  }
}

function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
}

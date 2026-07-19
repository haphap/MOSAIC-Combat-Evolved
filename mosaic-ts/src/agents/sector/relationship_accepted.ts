import { createHash } from "node:crypto";
import type { BaseMessage } from "@langchain/core/messages";
import { z } from "zod";
import type { DarwinianAgentBehaviorBinding } from "../../autoresearch/production_variant.js";
import type { AcceptedMacroInputAttribution } from "../helpers/macro_attribution.js";
import type { ToolStatus } from "../helpers/private_knot_boundary.js";
import type { RelationshipMapperOutput } from "../types.js";

const Sha256 = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const NonEmpty = z.string().trim().min(1);

export const RelationshipPredictionOpportunitySchema = z
  .object({
    edge_candidate_id: NonEmpty,
    source_entity: NonEmpty,
    target_entity: NonEmpty,
    edge_type: NonEmpty,
    materiality_weight: z.number().finite().positive(),
    matched_non_edge_set_id: NonEmpty,
    matched_non_edge_set_hash: Sha256,
  })
  .strict();

export const FrozenRelationshipPredictionOpportunitySetSchema = z
  .object({
    opportunity_set_id: NonEmpty,
    opportunity_set_hash: Sha256,
    run_id: NonEmpty,
    as_of: NonEmpty,
    candidate_generation_contract_version: NonEmpty,
    scoring_contract_version: NonEmpty,
    ordered_opportunities: z.array(RelationshipPredictionOpportunitySchema).min(1),
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

export type FrozenRelationshipPredictionOpportunitySet = z.infer<
  typeof FrozenRelationshipPredictionOpportunitySetSchema
>;

export interface AcceptedRelationshipFactualEdge {
  edge_id: string;
  edge_hash: string;
  source_entity: string;
  target_entity: string;
  edge_type: string;
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
  factual_edges: Array<Omit<AcceptedRelationshipFactualEdge, "edge_id" | "edge_hash">>;
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
  const raw = relationshipSnapshotPayloadFromToolLoop(input);
  const parsed = z
    .object({
      schema_version: z.literal("relationship_research_snapshot_v2"),
      as_of_date: NonEmpty,
      prediction_opportunity_set: FrozenRelationshipPredictionOpportunitySetSchema,
    })
    .passthrough()
    .parse(raw);
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
  const raw = relationshipSnapshotPayloadFromToolLoop(input);
  return z
    .object({
      relationships: z.array(
        z
          .object({
            source_entity: NonEmpty,
            target_entity: NonEmpty,
            edge_type: NonEmpty,
          })
          .passthrough(),
      ),
    })
    .passthrough()
    .parse(raw)
    .relationships.map(({ source_entity, target_entity, edge_type }) => ({
      source_entity,
      target_entity,
      edge_type,
    }));
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
  opportunitySet: FrozenRelationshipPredictionOpportunitySet;
  acceptedMacroInputAttributions: AcceptedMacroInputAttribution[];
  calibrationEffectiveAt: string;
}): AcceptedRelationshipGraph {
  const opportunityIssues = validateRelationshipOutputAgainstOpportunitySet(
    input.output,
    input.opportunitySet,
  );
  if (opportunityIssues.length > 0) throw new Error(opportunityIssues.join("; "));
  const opportunityById = new Map(
    input.opportunitySet.ordered_opportunities.map((row) => [row.edge_candidate_id, row]),
  );
  const factualEdges = input.output.factual_edges.map((edge) => acceptedFactualEdge(edge));
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
    opportunity_set_id: input.opportunitySet.opportunity_set_id,
    opportunity_set_hash: input.opportunitySet.opportunity_set_hash,
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

export function validateRelationshipOutputAgainstOpportunitySet(
  output: RelationshipMapperOutput,
  opportunitySet: FrozenRelationshipPredictionOpportunitySet,
): string[] {
  const opportunityById = new Map(
    opportunitySet.ordered_opportunities.map((row) => [row.edge_candidate_id, row]),
  );
  const issues: string[] = [];
  for (const edge of output.predictive_edges) {
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
      ({ edge_id: _id, edge_hash: _hash, ...edge }) => edge,
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
  edge: RelationshipMapperOutput["factual_edges"][number],
): AcceptedRelationshipFactualEdge {
  const body = {
    source_entity: edge.source_entity,
    target_entity: edge.target_entity,
    edge_type: edge.edge_type,
    claim_refs: edge.claim_refs,
  };
  const edgeHash = canonicalHash(body);
  return {
    edge_id: `relationship-factual-edge:${edgeHash.slice(7)}`,
    edge_hash: edgeHash,
    ...body,
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

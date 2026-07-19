import { createHash } from "node:crypto";
import { ToolMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import {
  buildAcceptedRelationshipGraph,
  modelVisibleAcceptedRelationshipGraph,
  relationshipOpportunitySetFromToolLoop,
} from "../src/agents/sector/relationship_accepted.js";
import type { RelationshipMapperOutput } from "../src/agents/types.js";

function canonicalHash(value: unknown): string {
  const canonicalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(canonicalize);
    if (item !== null && typeof item === "object") {
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, nested]) => [key, canonicalize(nested)]),
      );
    }
    return item;
  };
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function opportunitySet() {
  const body = {
    run_id: "graph-1",
    as_of: "2026-07-18",
    candidate_generation_contract_version: "relationship_candidates_v1",
    scoring_contract_version: "relationship_graph_validation_20d_v1",
    ordered_opportunities: [
      {
        edge_candidate_id: "edge-candidate-1",
        source_entity: "energy",
        target_entity: "industrials",
        edge_type: "INPUT_COST",
        materiality_weight: 2,
        matched_non_edge_set_id: "non-edge-1",
        matched_non_edge_set_hash: `sha256:${"1".repeat(64)}`,
      },
    ],
  };
  const hash = canonicalHash(body);
  return {
    opportunity_set_id: `relationship-opportunity:${hash.slice(7)}`,
    opportunity_set_hash: hash,
    ...body,
  };
}

function output(): RelationshipMapperOutput {
  return {
    agent: "relationship_mapper",
    factual_edges: [
      {
        edge_local_id: "fact-1",
        source_entity: "supplier-a",
        target_entity: "buyer-b",
        edge_type: "SUPPLY_CHAIN",
        claim_refs: ["claim-1"],
      },
    ],
    predictive_graph_status: "EDGES_PRESENT",
    predictive_edges: [
      {
        edge_local_id: "prediction-1",
        edge_candidate_id: "edge-candidate-1",
        source_entity: "energy",
        target_entity: "industrials",
        edge_type: "INPUT_COST",
        transmission_direction: "NEGATIVE",
        activation_trigger: "oil shock remains above the frozen threshold",
        evaluation_horizon_trading_days: 20,
        model_confidence: 0.7,
        claim_refs: ["claim-1"],
      },
    ],
    predictive_graph_abstention_confidence: null,
    key_drivers: [{ driver_local_id: "driver-1", summary: "input cost", claim_refs: ["claim-1"] }],
    risks: [{ risk_local_id: "risk-1", summary: "shock fades", claim_refs: ["claim-1"] }],
    claims: [
      {
        claim_id: "claim-1",
        claim_kind: "INTERPRETATION",
        statement: "The frozen edge can transmit the shock.",
        structured_conclusion: { transmission: "negative" },
        evidence_ids: ["relationship-evidence-1"],
        research_rule_refs: ["relationship-rule-1"],
      },
    ],
    claim_refs: ["claim-1"],
    macro_input_attributions: [],
  };
}

const behavior = {
  agent_contract_version: "relationship_graph_v2",
  prompt_behavior_version: "relationship_prompt_v2",
  execution_behavior_version: "relationship_execution_v2",
  component_weight_contract_version: null,
  reliability_adapter_contract_version: "relationship_edge_calibration_v1",
  confidence_semantics_contract_version: "relationship_confidence_v2",
};

describe("accepted relationship graph", () => {
  it("extracts an exact run-bound non-empty opportunity set from the frozen tool payload", () => {
    const set = opportunitySet();
    const snapshot = JSON.stringify({
      schema_version: "relationship_research_snapshot_v2",
      as_of_date: "2026-07-18",
      prediction_opportunity_set: set,
    });
    expect(
      relationshipOpportunitySetFromToolLoop({
        messages: [new ToolMessage({ content: snapshot, tool_call_id: "call-1" })],
        toolStatuses: [
          {
            name: "get_relationship_graph_snapshot",
            call_id: "call-1",
            called: true,
            failed: false,
            missing: false,
            fallback: false,
            cache_hit: false,
            args: {},
          },
        ],
        runId: "graph-1",
        asOf: "2026-07-18",
      }),
    ).toEqual(set);
  });

  it("resolves local edges and removes internal identity/calibration fields from model view", () => {
    const accepted = buildAcceptedRelationshipGraph({
      output: output(),
      behavior,
      opportunitySet: opportunitySet(),
      acceptedMacroInputAttributions: [],
      calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
    });
    expect(accepted.predictive_edges[0]?.edge_id).toMatch(/^relationship-predictive-edge:/);
    expect(accepted.directional_confidence).toBeCloseTo(0.7);
    const visible = modelVisibleAcceptedRelationshipGraph(accepted);
    expect(visible.predictive_edges[0]).not.toHaveProperty("edge_candidate_id");
    expect(visible.predictive_edges[0]).not.toHaveProperty("model_confidence");
    expect(visible.predictive_edges[0]).not.toHaveProperty("calibration_state_id");
    expect(visible.factual_edges[0]).not.toHaveProperty("edge_id");
  });

  it("rejects predictive edges outside or inconsistent with the frozen domain", () => {
    const invalid = output();
    const predictiveEdge = invalid.predictive_edges[0];
    if (!predictiveEdge) throw new Error("expected predictive edge fixture");
    invalid.predictive_edges[0] = {
      ...predictiveEdge,
      target_entity: "consumer",
    };
    expect(() =>
      buildAcceptedRelationshipGraph({
        output: invalid,
        behavior,
        opportunitySet: opportunitySet(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      }),
    ).toThrow(/frozen opportunity/);
  });
});

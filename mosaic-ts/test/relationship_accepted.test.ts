import { createHash } from "node:crypto";
import { ToolMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import {
  buildAcceptedRelationshipGraph,
  modelVisibleAcceptedRelationshipGraph,
  type RelationshipResearchSnapshot,
  RelationshipResearchSnapshotSchema,
  relationshipFactualEdgeCandidatesFromToolLoop,
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
  const matchedNonEdges = [
    {
      source_entity: "holder-a",
      source_entity_type: "HOLDER" as const,
      target_entity: "000002.SZ",
      target_entity_type: "PIT_ELIGIBLE_SECURITY" as const,
      target_sector_id: "sector-energy",
      edge_type: "SHAREHOLDING",
      materiality_bucket: "MEDIUM" as const,
    },
  ];
  const body = {
    run_id: "graph-1",
    as_of: "2026-07-18",
    candidate_generation_contract_version: "relationship_candidates_v1",
    scoring_contract_version: "relationship_graph_validation_20d_v1",
    ordered_opportunities: [
      {
        edge_candidate_id: "edge-candidate-1",
        source_entity: "holder-a",
        source_entity_type: "HOLDER" as const,
        target_entity: "000001.SZ",
        target_entity_type: "PIT_ELIGIBLE_SECURITY" as const,
        target_sector_id: "sector-energy",
        edge_type: "SHAREHOLDING",
        materiality_weight: 2,
        materiality_bucket: "MEDIUM" as const,
        matched_non_edge_set_id: "non-edge-1",
        matched_non_edge_set_hash: canonicalHash(matchedNonEdges),
        matched_non_edges: matchedNonEdges,
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

function relationshipSnapshot(set = opportunitySet()): RelationshipResearchSnapshot {
  const evidence = {
    evidence_id: "relationship-evidence-1",
    evidence_kind: "FROZEN_RELATIONSHIP_RECORD",
    source_id: "tushare.top10_holders",
    source_endpoint: "top10_holders",
    observation_date: "2026-07-17",
    released_at: "2026-07-17",
    vintage_at: "2026-07-17",
    pit_status: "PIT_VERIFIED",
    content_hash: canonicalHash({ source: "relationship-source-batch" }),
    evidence_record_hash: "",
  };
  evidence.evidence_record_hash = canonicalHash(
    Object.fromEntries(Object.entries(evidence).filter(([key]) => key !== "evidence_record_hash")),
  );
  const opportunity = set.ordered_opportunities[0];
  if (!opportunity) throw new Error("relationship fixture requires one opportunity");
  const relationship = {
    edge_candidate_id: opportunity.edge_candidate_id,
    source_entity: opportunity.source_entity,
    source_entity_type: opportunity.source_entity_type,
    target_entity: opportunity.target_entity,
    target_entity_type: opportunity.target_entity_type,
    target_sector_id: opportunity.target_sector_id,
    edge_type: opportunity.edge_type,
    activation_trigger: "Frozen input-cost transmission remains active.",
    observation_date: "2026-07-17",
    released_at: "2026-07-17",
    vintage_at: "2026-07-17",
    pit_status: "PIT_VERIFIED",
    evidence_ids: [evidence.evidence_id],
    relationship_row_hash: "",
  };
  relationship.relationship_row_hash = canonicalHash(
    Object.fromEntries(
      Object.entries(relationship).filter(([key]) => key !== "relationship_row_hash"),
    ),
  );
  const snapshot = {
    schema_version: "relationship_research_snapshot_v3",
    as_of_date: "2026-07-18",
    frozen_holder_domain_hash: canonicalHash([relationship.source_entity]),
    frozen_security_domain_hash: canonicalHash(
      [
        relationship.target_entity,
        ...set.ordered_opportunities.flatMap((row) =>
          row.matched_non_edges.map((matched) => matched.target_entity),
        ),
      ].sort(),
    ),
    relationships: [relationship],
    prediction_opportunity_set: set,
    evidence_catalog: [evidence],
    evidence_catalog_hash: canonicalHash([evidence]),
    snapshot_hash: "",
  };
  snapshot.snapshot_hash = canonicalHash(
    Object.fromEntries(Object.entries(snapshot).filter(([key]) => key !== "snapshot_hash")),
  );
  return RelationshipResearchSnapshotSchema.parse(snapshot);
}

function relationshipSnapshotWithTwoFacts(): RelationshipResearchSnapshot {
  const snapshot = relationshipSnapshot();
  const first = snapshot.relationships[0];
  if (!first) throw new Error("expected relationship fixture");
  const second = {
    ...first,
    edge_candidate_id: "edge-candidate-2",
    target_entity: "000003.SZ",
    activation_trigger: "Second frozen holder disclosure remains active.",
    relationship_row_hash: "",
  };
  second.relationship_row_hash = canonicalHash(
    Object.fromEntries(Object.entries(second).filter(([key]) => key !== "relationship_row_hash")),
  );
  snapshot.relationships.push(second);
  const secondMatched = [
    {
      source_entity: "holder-a",
      source_entity_type: "HOLDER" as const,
      target_entity: "000004.SZ",
      target_entity_type: "PIT_ELIGIBLE_SECURITY" as const,
      target_sector_id: "sector-energy",
      edge_type: "SHAREHOLDING",
      materiality_bucket: "MEDIUM" as const,
    },
  ];
  snapshot.prediction_opportunity_set.ordered_opportunities.push({
    edge_candidate_id: second.edge_candidate_id,
    source_entity: second.source_entity,
    source_entity_type: second.source_entity_type,
    target_entity: second.target_entity,
    target_entity_type: second.target_entity_type,
    target_sector_id: second.target_sector_id,
    edge_type: second.edge_type,
    materiality_weight: 2,
    materiality_bucket: "MEDIUM",
    matched_non_edge_set_id: "non-edge-2",
    matched_non_edge_set_hash: canonicalHash(secondMatched),
    matched_non_edges: secondMatched,
  });
  snapshot.frozen_holder_domain_hash = canonicalHash(["holder-a"]);
  snapshot.frozen_security_domain_hash = canonicalHash(
    ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"].sort(),
  );
  const {
    opportunity_set_id: _id,
    opportunity_set_hash: _hash,
    ...opportunityBody
  } = snapshot.prediction_opportunity_set;
  snapshot.prediction_opportunity_set.opportunity_set_hash = canonicalHash(opportunityBody);
  snapshot.prediction_opportunity_set.opportunity_set_id = `relationship-opportunity:${snapshot.prediction_opportunity_set.opportunity_set_hash.slice(7)}`;
  rehashSnapshot(snapshot);
  return RelationshipResearchSnapshotSchema.parse(snapshot);
}

function rehashSnapshot(snapshot: Record<string, unknown>): void {
  snapshot.snapshot_hash = canonicalHash(
    Object.fromEntries(Object.entries(snapshot).filter(([key]) => key !== "snapshot_hash")),
  );
}

function rehashOpportunitySetAndSnapshot(snapshot: RelationshipResearchSnapshot): void {
  const opportunitySet = snapshot.prediction_opportunity_set;
  const { opportunity_set_id: _id, opportunity_set_hash: _hash, ...body } = opportunitySet;
  opportunitySet.opportunity_set_hash = canonicalHash(body);
  opportunitySet.opportunity_set_id = `relationship-opportunity:${opportunitySet.opportunity_set_hash.slice(7)}`;
  rehashSnapshot(snapshot);
}

function output(): RelationshipMapperOutput {
  return {
    agent: "relationship_mapper",
    factual_edges: [
      {
        edge_local_id: "fact-1",
        source_entity: "holder-a",
        target_entity: "000001.SZ",
        edge_type: "SHAREHOLDING",
        claim_refs: ["claim-1"],
      },
    ],
    predictive_graph_status: "EDGES_PRESENT",
    predictive_edges: [
      {
        edge_local_id: "prediction-1",
        edge_candidate_id: "edge-candidate-1",
        source_entity: "holder-a",
        target_entity: "000001.SZ",
        edge_type: "SHAREHOLDING",
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

function parseToolSnapshot(snapshot: Record<string, unknown>) {
  return relationshipOpportunitySetFromToolLoop({
    messages: [
      new ToolMessage({ content: JSON.stringify(snapshot), tool_call_id: "relationship-call" }),
    ],
    toolStatuses: [
      {
        name: "get_relationship_graph_snapshot",
        call_id: "relationship-call",
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
  });
}

describe("accepted relationship graph", () => {
  it("extracts an exact run-bound non-empty opportunity set from the frozen tool payload", () => {
    const set = opportunitySet();
    const snapshot = JSON.stringify(relationshipSnapshot(set));
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

  it("rejects duplicate tuples in the frozen factual relationship domain", () => {
    const snapshot = relationshipSnapshot();
    const relationships = snapshot.relationships as Array<Record<string, unknown>>;
    const duplicate: Record<string, unknown> = {
      ...relationships[0],
      edge_candidate_id: "edge-candidate-2",
    };
    duplicate.relationship_row_hash = canonicalHash(
      Object.fromEntries(
        Object.entries(duplicate).filter(([key]) => key !== "relationship_row_hash"),
      ),
    );
    relationships.push(duplicate);
    rehashSnapshot(snapshot);
    expect(() =>
      relationshipFactualEdgeCandidatesFromToolLoop({
        messages: [
          new ToolMessage({
            content: JSON.stringify(snapshot),
            tool_call_id: "call-1",
          }),
        ],
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
      }),
    ).toThrow("duplicate factual relationship tuple");
  });

  it("rejects future evidence and every level of snapshot hash tampering", () => {
    const future = relationshipSnapshot();
    const evidence = (future.evidence_catalog as Array<Record<string, unknown>>)[0];
    if (!evidence) throw new Error("expected relationship evidence fixture");
    evidence.observation_date = "2026-07-19";
    evidence.released_at = "2026-07-19";
    evidence.vintage_at = "2026-07-19";
    evidence.evidence_record_hash = canonicalHash(
      Object.fromEntries(
        Object.entries(evidence).filter(([key]) => key !== "evidence_record_hash"),
      ),
    );
    future.evidence_catalog_hash = canonicalHash(future.evidence_catalog);
    rehashSnapshot(future);
    expect(() => parseToolSnapshot(future)).toThrow("as_of");

    const matchedSetTamper = relationshipSnapshot();
    const set = matchedSetTamper.prediction_opportunity_set as Record<string, unknown>;
    const opportunity = (set.ordered_opportunities as Array<Record<string, unknown>>)[0];
    if (!opportunity) throw new Error("expected relationship opportunity fixture");
    const matched = (opportunity.matched_non_edges as Array<Record<string, unknown>>)[0];
    if (!matched) throw new Error("expected matched non-edge fixture");
    matched.target_entity = "000003.SZ";
    rehashSnapshot(matchedSetTamper);
    expect(() => parseToolSnapshot(matchedSetTamper)).toThrow("matched non-edge set hash mismatch");

    const fullSnapshotTamper = relationshipSnapshot();
    fullSnapshotTamper.fixture_class = "SYNTHETIC_NON_PRODUCTION";
    expect(() => parseToolSnapshot(fullSnapshotTamper)).toThrow("snapshot hash mismatch");
  });

  it("rejects same-day vintages after the Asia/Shanghai 15:00 cutoff", () => {
    const lateEvidence = relationshipSnapshot();
    const evidence = lateEvidence.evidence_catalog[0];
    if (!evidence) throw new Error("expected relationship evidence fixture");
    evidence.released_at = "2026-07-18T07:00:01Z";
    evidence.vintage_at = "2026-07-18T07:00:01Z";
    evidence.evidence_record_hash = canonicalHash(
      Object.fromEntries(
        Object.entries(evidence).filter(([key]) => key !== "evidence_record_hash"),
      ),
    );
    lateEvidence.evidence_catalog_hash = canonicalHash(lateEvidence.evidence_catalog);
    rehashSnapshot(lateEvidence);
    expect(() => parseToolSnapshot(lateEvidence)).toThrow("as_of");

    const lateRelationship = relationshipSnapshot();
    const relationship = lateRelationship.relationships[0];
    if (!relationship) throw new Error("expected relationship row fixture");
    relationship.released_at = "2026-07-18T07:00:01Z";
    relationship.vintage_at = "2026-07-18T07:00:01Z";
    relationship.relationship_row_hash = canonicalHash(
      Object.fromEntries(
        Object.entries(relationship).filter(([key]) => key !== "relationship_row_hash"),
      ),
    );
    rehashSnapshot(lateRelationship);
    expect(() => parseToolSnapshot(lateRelationship)).toThrow("as_of");
  });

  it("requires timezone-qualified timestamps and accepts the exact Shanghai cutoff", () => {
    const timezoneLess = relationshipSnapshot();
    const timezoneLessEvidence = timezoneLess.evidence_catalog[0];
    if (!timezoneLessEvidence) throw new Error("expected relationship evidence fixture");
    timezoneLessEvidence.released_at = "2026-07-18T06:59:59";
    timezoneLessEvidence.vintage_at = "2026-07-18T06:59:59";
    timezoneLessEvidence.evidence_record_hash = canonicalHash(
      Object.fromEntries(
        Object.entries(timezoneLessEvidence).filter(([key]) => key !== "evidence_record_hash"),
      ),
    );
    timezoneLess.evidence_catalog_hash = canonicalHash(timezoneLess.evidence_catalog);
    rehashSnapshot(timezoneLess);
    expect(() => parseToolSnapshot(timezoneLess)).toThrow("as_of");

    for (const boundary of ["2026-07-18T07:00:00Z", "2026-07-18T15:00:00+08:00"]) {
      const atCutoff = relationshipSnapshot();
      const evidence = atCutoff.evidence_catalog[0];
      if (!evidence) throw new Error("expected relationship evidence fixture");
      evidence.released_at = boundary;
      evidence.vintage_at = boundary;
      evidence.evidence_record_hash = canonicalHash(
        Object.fromEntries(
          Object.entries(evidence).filter(([key]) => key !== "evidence_record_hash"),
        ),
      );
      atCutoff.evidence_catalog_hash = canonicalHash(atCutoff.evidence_catalog);
      rehashSnapshot(atCutoff);
      expect(() => parseToolSnapshot(atCutoff)).not.toThrow();
    }
  });

  it("rejects holder and security identities disguised only by type labels", () => {
    const disguisedHolderTarget = relationshipSnapshot();
    const relationship = disguisedHolderTarget.relationships[0];
    const opportunity = disguisedHolderTarget.prediction_opportunity_set.ordered_opportunities[0];
    if (!relationship || !opportunity) throw new Error("expected relationship fixture");
    relationship.target_entity = "holder-b";
    opportunity.target_entity = "holder-b";
    rehashOpportunitySetAndSnapshot(disguisedHolderTarget);
    expect(() => parseToolSnapshot(disguisedHolderTarget)).toThrow(
      "canonical A-share security code",
    );

    const disguisedSecuritySource = relationshipSnapshot();
    const securityRelationship = disguisedSecuritySource.relationships[0];
    const securityOpportunity =
      disguisedSecuritySource.prediction_opportunity_set.ordered_opportunities[0];
    if (!securityRelationship || !securityOpportunity) {
      throw new Error("expected relationship fixture");
    }
    securityRelationship.source_entity = "000005.SH";
    securityOpportunity.source_entity = "000005.SH";
    for (const matched of securityOpportunity.matched_non_edges) {
      matched.source_entity = "000005.SH";
    }
    rehashOpportunitySetAndSnapshot(disguisedSecuritySource);
    expect(() => parseToolSnapshot(disguisedSecuritySource)).toThrow(
      "must identify a holder, not a security",
    );
  });

  it("rejects reversed, holder-target, sector-mismatched, and materiality-mismatched controls", () => {
    const mutations: Array<(row: Record<string, unknown>) => void> = [
      (row) => {
        row.source_entity = "000001.SZ";
        row.source_entity_type = "PIT_ELIGIBLE_SECURITY";
        row.target_entity = "holder-b";
        row.target_entity_type = "HOLDER";
      },
      (row) => {
        row.target_entity = "holder-b";
        row.target_entity_type = "HOLDER";
      },
      (row) => {
        row.target_entity = "holder-b";
      },
      (row) => {
        row.source_entity = "000005.SH";
      },
      (row) => {
        row.target_sector_id = "sector-financials";
      },
      (row) => {
        row.materiality_bucket = "HIGH";
      },
    ];
    for (const mutate of mutations) {
      const snapshot = relationshipSnapshot();
      const opportunity = snapshot.prediction_opportunity_set.ordered_opportunities[0];
      const matched = opportunity?.matched_non_edges[0];
      if (!opportunity || !matched) throw new Error("expected matched non-edge fixture");
      mutate(matched as unknown as Record<string, unknown>);
      opportunity.matched_non_edge_set_hash = canonicalHash(opportunity.matched_non_edges);
      rehashOpportunitySetAndSnapshot(snapshot);
      expect(() => parseToolSnapshot(snapshot)).toThrow();
    }
  });

  it("rejects duplicate candidate ids, 33-row domains, and overlong ids before extraction", () => {
    const duplicateCandidate = relationshipSnapshot();
    const relationships = duplicateCandidate.relationships as Array<Record<string, unknown>>;
    const duplicate: Record<string, unknown> = {
      ...relationships[0],
      source_entity: "financials",
      target_entity: "000003.SZ",
      edge_type: "COMMON_OWNERSHIP",
    };
    duplicate.relationship_row_hash = canonicalHash(
      Object.fromEntries(
        Object.entries(duplicate).filter(([key]) => key !== "relationship_row_hash"),
      ),
    );
    relationships.push(duplicate);
    duplicateCandidate.frozen_holder_domain_hash = canonicalHash(["financials", "holder-a"].sort());
    duplicateCandidate.frozen_security_domain_hash = canonicalHash(
      ["000001.SZ", "000002.SZ", "000003.SZ"].sort(),
    );
    rehashSnapshot(duplicateCandidate);
    expect(() => parseToolSnapshot(duplicateCandidate)).toThrow(
      "duplicate frozen edge_candidate_id",
    );

    const oversizedFactual = relationshipSnapshot();
    const firstFactual = oversizedFactual.relationships[0];
    if (!firstFactual) throw new Error("expected relationship row fixture");
    oversizedFactual.relationships = Array.from({ length: 33 }, () => firstFactual);
    expect(() => parseToolSnapshot(oversizedFactual)).toThrow();

    const oversizedPredictive = relationshipSnapshot();
    const predictiveSet = oversizedPredictive.prediction_opportunity_set as Record<string, unknown>;
    predictiveSet.ordered_opportunities = Array.from(
      { length: 33 },
      () => (predictiveSet.ordered_opportunities as Array<Record<string, unknown>>)[0],
    );
    expect(() => parseToolSnapshot(oversizedPredictive)).toThrow();

    const overlong = relationshipSnapshot();
    const overlongRelationship = (overlong.relationships as Array<Record<string, unknown>>)[0];
    if (!overlongRelationship) throw new Error("expected relationship row fixture");
    overlongRelationship.source_entity = "x".repeat(129);
    expect(() => parseToolSnapshot(overlong)).toThrow();
  });

  it("binds exact factual edges to the frozen snapshot and hides internal identity fields", () => {
    const submitted = output();
    const snapshot = relationshipSnapshot();
    const accepted = buildAcceptedRelationshipGraph({
      output: submitted,
      behavior,
      relationshipSnapshot: snapshot,
      acceptedMacroInputAttributions: [],
      calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
    });
    expect(accepted.predictive_edges[0]?.edge_id).toMatch(/^relationship-predictive-edge:/);
    expect(accepted.relationship_snapshot_hash).toBe(snapshot.snapshot_hash);
    expect(accepted.frozen_holder_domain_hash).toBe(snapshot.frozen_holder_domain_hash);
    expect(accepted.frozen_security_domain_hash).toBe(snapshot.frozen_security_domain_hash);
    expect(new Set(accepted.factual_edges.map((edge) => edge.edge_id)).size).toBe(1);
    expect(new Set(accepted.factual_edges.map((edge) => edge.edge_hash)).size).toBe(1);
    expect(accepted.directional_confidence).toBeCloseTo(0.7);
    const visible = modelVisibleAcceptedRelationshipGraph(accepted);
    expect(visible.predictive_edges[0]).not.toHaveProperty("edge_candidate_id");
    expect(visible.predictive_edges[0]).not.toHaveProperty("model_confidence");
    expect(visible.predictive_edges[0]).not.toHaveProperty("calibration_state_id");
    expect(visible.factual_edges[0]).not.toHaveProperty("edge_id");
    expect(visible.factual_edges[0]).not.toHaveProperty("edge_candidate_id");
    expect(visible.factual_edges[0]).not.toHaveProperty("relationship_row_hash");
  });

  it("keeps factual identity independent of model-authored claim references", () => {
    const firstOutput = output();
    const secondOutput = output();
    const firstClaim = secondOutput.claims[0];
    const secondFact = secondOutput.factual_edges[0];
    if (!firstClaim || !secondFact) throw new Error("expected relationship output fixture");
    secondOutput.claims.push({ ...firstClaim, claim_id: "claim-2" });
    secondFact.claim_refs = ["claim-2"];

    const build = (candidate: RelationshipMapperOutput) =>
      buildAcceptedRelationshipGraph({
        output: candidate,
        behavior,
        relationshipSnapshot: relationshipSnapshot(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      });
    const first = build(firstOutput).factual_edges[0];
    const second = build(secondOutput).factual_edges[0];
    expect(first?.edge_id).toBe(second?.edge_id);
    expect(first?.edge_hash).toBe(second?.edge_hash);
    expect(first?.claim_refs).not.toEqual(second?.claim_refs);
  });

  it("rejects invented factual edges and exact-tuple edge-type mismatches", () => {
    const invented = output();
    invented.factual_edges[0] = {
      edge_local_id: "fact-1",
      source_entity: "supplier-c",
      target_entity: "buyer-d",
      edge_type: "SUPPLY_CHAIN",
      claim_refs: ["claim-1"],
    };
    expect(() =>
      buildAcceptedRelationshipGraph({
        output: invented,
        behavior,
        relationshipSnapshot: relationshipSnapshot(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      }),
    ).toThrow("outside the frozen snapshot domain");

    const wrongType = output();
    const frozenFact = wrongType.factual_edges[0];
    if (!frozenFact) throw new Error("expected factual edge fixture");
    wrongType.factual_edges[0] = {
      ...frozenFact,
      edge_type: "SUPPLY_CHAIN",
    };
    expect(() =>
      buildAcceptedRelationshipGraph({
        output: wrongType,
        behavior,
        relationshipSnapshot: relationshipSnapshot(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      }),
    ).toThrow("outside the frozen snapshot domain");
  });

  it("rejects empty and strict-subset factual submissions", () => {
    const empty = output();
    empty.factual_edges = [];
    expect(() =>
      buildAcceptedRelationshipGraph({
        output: empty,
        behavior,
        relationshipSnapshot: relationshipSnapshot(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      }),
    ).toThrow("exactly equal the frozen snapshot domain");

    expect(() =>
      buildAcceptedRelationshipGraph({
        output: output(),
        behavior,
        relationshipSnapshot: relationshipSnapshotWithTwoFacts(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      }),
    ).toThrow("exactly equal the frozen snapshot domain");
  });

  it("rejects factual edge local-id and tuple collisions before accepted ids are built", () => {
    const duplicateLocalId = output();
    duplicateLocalId.factual_edges.push({
      edge_local_id: "fact-1",
      source_entity: "supplier-c",
      target_entity: "buyer-d",
      edge_type: "SUPPLY_CHAIN",
      claim_refs: ["claim-1"],
    });
    expect(() =>
      buildAcceptedRelationshipGraph({
        output: duplicateLocalId,
        behavior,
        relationshipSnapshot: relationshipSnapshot(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      }),
    ).toThrow("duplicate factual edge_local_id");

    const duplicateTuple = output();
    const firstFactualEdge = duplicateTuple.factual_edges[0];
    if (!firstFactualEdge) throw new Error("expected factual edge fixture");
    duplicateTuple.factual_edges.push({ ...firstFactualEdge, edge_local_id: "fact-2" });
    expect(() =>
      buildAcceptedRelationshipGraph({
        output: duplicateTuple,
        behavior,
        relationshipSnapshot: relationshipSnapshot(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      }),
    ).toThrow("duplicate factual relationship tuple");
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
        relationshipSnapshot: relationshipSnapshot(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      }),
    ).toThrow(/frozen opportunity/);

    const duplicateCandidate = output();
    const firstPredictiveEdge = duplicateCandidate.predictive_edges[0];
    if (!firstPredictiveEdge) throw new Error("expected predictive edge fixture");
    duplicateCandidate.predictive_edges.push({
      ...firstPredictiveEdge,
      edge_local_id: "prediction-2",
    });
    expect(() =>
      buildAcceptedRelationshipGraph({
        output: duplicateCandidate,
        behavior,
        relationshipSnapshot: relationshipSnapshot(),
        acceptedMacroInputAttributions: [],
        calibrationEffectiveAt: "2026-07-18T15:00:00+08:00",
      }),
    ).toThrow("duplicate predictive edge_candidate_id");
  });
});

import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  adaptStrictProviderJsonSchema,
  normalizeStrictProviderPayload,
} from "../src/agents/helpers/structured_provider_adapters.js";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import {
  buildRelationshipMapperSchema,
  buildStandardSectorSchema,
} from "../src/agents/sector/_schemas.js";
import {
  buildSectorConflictReviewSchema,
  buildSectorDirectionResearchSchema,
} from "../src/agents/sector/comparison.js";
import {
  BurrySchema,
  buildRuntimeSuperinvestorSchema,
} from "../src/agents/superinvestor/_schemas.js";

describe("strict structured provider adapters", () => {
  it("extracts a bounded Sector abstention and materializes the canonical domain contract", () => {
    const domainSchema = z
      .object({
        final_selection: buildStandardSectorSchema("semiconductor", "NO_QUALIFIED_DIRECTION"),
      })
      .strict();
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(domainSchema)) as {
      properties: {
        final_selection: { properties: Record<string, unknown>; required: string[] };
      };
    };
    expect(providerSchema.properties.final_selection.required).toEqual([
      "agent",
      "least_preferred_reason",
      "persistence_horizon",
      "confidence",
      "abstention_summary",
      "evidence_id",
      "macro_input_attributions",
    ]);
    expect(providerSchema.properties.final_selection.properties).not.toHaveProperty("claims");

    const normalized = normalizeStrictProviderPayload({
      final_selection: {
        agent: "semiconductor",
        least_preferred_reason: "NO_UNIQUE_CONDORCET_LOSER",
        persistence_horizon: "WEEKS",
        confidence: 0.4,
        abstention_summary: "Evidence did not qualify a unique direction.",
        evidence_id: "evidence-1",
        macro_input_attributions: {
          submission_summaries: Object.fromEntries(
            MACRO_AGENT_IDS.map((agentId) => [
              agentId,
              { claim_ref_used: "NOT_MATERIAL", effect: "MIXED" },
            ]),
          ),
          target_attributions: [],
        },
      },
    });
    const parsed = domainSchema.parse(normalized);
    expect(parsed.final_selection.claims).toHaveLength(1);
    expect(parsed.final_selection.claims[0]?.evidence_ids).toEqual(["evidence-1"]);
    expect(parsed.final_selection.macro_input_attributions).toHaveLength(10);
    expect(parsed.final_selection.macro_input_attributions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ effect: "NOT_MATERIAL", claim_refs_used: [] }),
      ]),
    );
  });

  it("compacts a directive-bound selected Sector submission and restores the domain contract", () => {
    const directive = {
      selection_status: "SELECTED" as const,
      preferred_direction_id: "coal",
      least_preferred_status: "REQUIRED" as const,
      least_preferred_direction_id: "oil_gas",
      least_preferred_reason: "UNIQUE_CONDORCET_LOSER" as const,
      allowed_preferred_security_ids: [],
      allowed_least_preferred_security_ids: [],
    };
    const selected = z
      .object({
        final_selection: buildStandardSectorSchema("energy", "SELECTED", directive),
      })
      .strict();
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(selected)) as {
      properties: { final_selection: { properties: Record<string, unknown> } };
    };
    expect(providerSchema.properties.final_selection.properties.provider_contract).toEqual({
      type: "string",
      const: "SECTOR_SELECTED_COMPACT_V1",
    });
    expect(providerSchema.properties.final_selection.properties).not.toHaveProperty("claims");

    const normalized = normalizeStrictProviderPayload({
      final_selection: {
        provider_contract: "SECTOR_SELECTED_COMPACT_V1",
        agent: "energy",
        preferred_direction_id: "coal",
        preferred_direction_local_id: "coal",
        preferred_strength: 3,
        preferred_thesis: "Coal has the strongest relative direction evidence.",
        least_preferred_direction_id: "oil_gas",
        least_preferred_direction_local_id: "oil_gas",
        least_preferred_strength: 2,
        least_preferred_thesis: "Oil and gas has the weakest relative evidence.",
        persistence_horizon: "WEEKS",
        confidence: 0.7,
        driver_summary: "Relative fundamentals and technicals favor coal.",
        risk_summary: "The relative ranking can reverse as inputs change.",
        evidence_id: "evidence-1",
        research_rule_ref: "sector.energy.soft.001",
        preferred_security: {
          status: "NO_QUALIFIED_SECURITY",
          abstention_confidence: 0.8,
        },
        least_preferred_security: {
          status: "NO_QUALIFIED_SECURITY",
          abstention_confidence: 0.8,
        },
        macro_input_attributions: compactMacroAttributions(),
      },
    });
    const parsed = selected.parse(normalized);
    expect(parsed.final_selection.claims).toHaveLength(1);
    expect(
      "direction_id" in parsed.final_selection.preferred_direction &&
        parsed.final_selection.preferred_direction.direction_id,
    ).toBe("coal");
    expect(
      "direction_id" in parsed.final_selection.least_preferred_direction &&
        parsed.final_selection.least_preferred_direction.direction_id,
    ).toBe("oil_gas");
    expect(parsed.final_selection.macro_input_attributions).toHaveLength(MACRO_AGENT_IDS.length);
  });

  it("compacts pairwise Sector research and restores the exact domain matrix", () => {
    const domainSchema = buildSectorDirectionResearchSchema(["coal", "oil_gas", "solar"]);
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(domainSchema)) as {
      properties: { provider_contract: { const: string }; pairs: { prefixItems: unknown[] } };
    };
    expect(providerSchema.properties.provider_contract.const).toBe(
      "SECTOR_DIRECTION_RESEARCH_COMPACT_V1",
    );
    expect(providerSchema.properties.pairs.prefixItems).toHaveLength(3);

    const normalized = normalizeStrictProviderPayload({
      provider_contract: "SECTOR_DIRECTION_RESEARCH_COMPACT_V1",
      ...compactSharedEvidence(),
      pairs: [
        compactPair("coal", "oil_gas"),
        compactPair("coal", "solar"),
        compactPair("oil_gas", "solar"),
      ],
    });
    const parsed = domainSchema.parse(normalized);
    expect(parsed.comparison_claims).toHaveLength(3);
    expect(parsed.research_mode).toBe("PAIRWISE");
    if (parsed.research_mode === "PAIRWISE") {
      expect(parsed.direction_comparisons).toHaveLength(3);
      expect(parsed.direction_comparisons[0]?.criterion_results).toHaveLength(8);
    }
  });

  it("uses a separate immutable claim namespace for compact conflict review", () => {
    const domainSchema = buildSectorConflictReviewSchema(
      ["coal", "oil_gas"],
      new Set(["provider-direction-1-coal-vs-oil-gas"]),
    );
    const normalized = normalizeStrictProviderPayload({
      provider_contract: "SECTOR_CONFLICT_REVIEW_COMPACT_V1",
      ...compactSharedEvidence(),
      pairs: [compactPair("coal", "oil_gas")],
    });
    const parsed = domainSchema.parse(normalized);
    expect(parsed.comparison_claims[0]?.claim_id).toBe("provider-conflict-1-coal-vs-oil-gas");
  });

  it("materializes the exact claim-ref union for single-direction qualification", () => {
    const normalized = normalizeStrictProviderPayload({
      research_mode: "SINGLE_DIRECTION_QUALIFICATION",
      comparison_claims: [],
      direction_comparisons: [],
      single_direction_qualification: {
        criterion_results: [
          { criterion: "FUNDAMENTALS", claim_refs: ["claim-b", "claim-a"] },
          { criterion: "VALUATION", claim_refs: ["claim-a"] },
        ],
        claim_refs: ["claim-b"],
      },
    }) as {
      single_direction_qualification: { claim_refs: string[] };
    };
    expect(normalized.single_direction_qualification.claim_refs).toEqual(["claim-a", "claim-b"]);
  });

  it("compacts a single direction with runtime-owned direction and null benchmark literals", () => {
    const domainSchema = buildSectorDirectionResearchSchema(
      ["medicine_biotech"],
      "single-null:biotech",
    );
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(domainSchema)) as {
      properties: { provider_contract: { const: string } };
    };
    expect(providerSchema.properties.provider_contract.const).toBe(
      "SECTOR_SINGLE_DIRECTION_COMPACT_V1",
    );
    const { pair_key: _pairKey, ...decision } = compactPair(
      "medicine_biotech",
      "single-null:biotech",
    );
    const normalized = normalizeStrictProviderPayload({
      provider_contract: "SECTOR_SINGLE_DIRECTION_COMPACT_V1",
      qualification: {
        direction_id: "medicine_biotech",
        null_benchmark_contract_id: "single-null:biotech",
        summary: "The single direction has mixed comparative evidence.",
        ...compactSharedEvidence(),
        ...decision,
      },
    });
    const parsed = domainSchema.parse(normalized);
    expect(parsed.research_mode).toBe("SINGLE_DIRECTION_QUALIFICATION");
    expect(parsed.comparison_claims[0]?.evidence_ids).toEqual(["evidence-1"]);
  });

  it("compacts Relationship Mapper output and binds predictive edges to frozen candidates", () => {
    const domainSchema = buildRelationshipMapperSchema({
      maxFactualEdges: 1,
      maxPredictiveEdges: 1,
      factualRelationships: [
        {
          source_entity: "energy",
          target_entity: "industrials",
          edge_type: "INPUT_COST",
        },
      ],
      predictiveOpportunities: [
        {
          edge_candidate_id: "frozen-edge-1",
          source_entity: "energy",
          target_entity: "industrials",
          edge_type: "INPUT_COST",
        },
      ],
    });
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(domainSchema)) as {
      properties: { provider_contract: { const: string } };
    };
    expect(providerSchema.properties.provider_contract.const).toBe(
      "RELATIONSHIP_MAPPER_COMPACT_V1",
    );

    const normalized = normalizeStrictProviderPayload({
      provider_contract: "RELATIONSHIP_MAPPER_COMPACT_V1",
      agent: "relationship_mapper",
      factual_edges: [
        {
          source_entity: "energy",
          target_entity: "industrials",
          edge_type: "INPUT_COST",
        },
      ],
      predictive_graph_status: "EDGES_PRESENT",
      predictive_graph_abstention_confidence: 0,
      predictive_edges: [
        {
          edge_candidate_id: "frozen-edge-1",
          source_entity: "energy",
          target_entity: "industrials",
          edge_type: "INPUT_COST",
          transmission_direction: "NEGATIVE",
          activation_trigger: "Input costs rise materially.",
          evaluation_horizon_trading_days: 20,
          model_confidence: 0.7,
        },
      ],
      driver_summary: "The frozen input-cost edge is active.",
      risk_summary: "The input-cost relationship can weaken.",
      evidence_id: "evidence-1",
      research_rule_ref: "sector.relationship_mapper.soft.001",
      macro_input_attributions: compactMacroAttributions(),
    });
    const parsed = domainSchema.parse(normalized);
    expect(parsed.claims).toHaveLength(1);
    expect(parsed.predictive_edges[0]?.edge_candidate_id).toBe("frozen-edge-1");

    const wrongCandidate = structuredClone(normalized) as {
      predictive_edges: Array<{ edge_candidate_id: string }>;
    };
    const predictiveEdge = wrongCandidate.predictive_edges[0];
    if (!predictiveEdge) throw new Error("expected predictive edge fixture");
    predictiveEdge.edge_candidate_id = "invented-edge";
    expect(domainSchema.safeParse(wrongCandidate).success).toBe(false);
  });

  it("compacts an empty Superinvestor candidate disposition and closes local claim refs", () => {
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(BurrySchema)) as {
      oneOf: Array<{ properties: { provider_contract?: { const: string } } }>;
    };
    expect(
      providerSchema.oneOf.some(
        (branch) =>
          branch.properties.provider_contract?.const === "SUPERINVESTOR_ABSTENTION_COMPACT_V1",
      ),
    ).toBe(true);
    const normalized = normalizeStrictProviderPayload({
      provider_contract: "SUPERINVESTOR_ABSTENTION_COMPACT_V1",
      agent: "burry",
      confidence: 0.6,
      holding_period: "MONTHS",
      abstention_summary: "The frozen candidate universe contains no qualified candidate.",
      risk_summary: "Remaining in cash creates opportunity-cost risk.",
      evidence_id: "evidence-1",
      research_rule_ref: "superinvestor.burry.soft.001",
      macro_input_attributions: compactMacroAttributions(),
    });
    const parsed = BurrySchema.parse(normalized);
    expect(parsed.selection_status).toBe("NO_QUALIFIED_CANDIDATES");
    expect(parsed.risks[0]?.claim_refs).toEqual(parsed.claim_refs);
    expect(parsed.picks).toEqual([]);
  });

  it("exposes only the compact abstention provider contract for an empty frozen universe", () => {
    const providerSchema = adaptStrictProviderJsonSchema(
      z.toJSONSchema(buildRuntimeSuperinvestorSchema("ackman", [])),
    ) as { properties: { provider_contract: { const: string } }; oneOf?: unknown };
    expect(providerSchema.oneOf).toBeUndefined();
    expect(providerSchema.properties.provider_contract.const).toBe(
      "SUPERINVESTOR_ABSTENTION_COMPACT_V1",
    );
  });

  it("removes numeric snapshot echoes only from Macro structured conclusion text", () => {
    const normalized = normalizeStrictProviderPayload({
      claims: [
        {
          statement: "40% of stocks are above MA20.",
          structured_conclusion: {
            conclusion_type: "MACRO_INTERPRETATION",
            subject: "MA20 breadth",
            state: "40% MIXED",
            a_share_transmission: "40% breadth with -0.08125 change",
          },
        },
      ],
    }) as {
      claims: Array<{
        statement: string;
        structured_conclusion: { subject: string; state: string; a_share_transmission: string };
      }>;
    };
    expect(normalized.claims[0]?.statement).toBe("40% of stocks are above MA20.");
    expect(normalized.claims[0]?.structured_conclusion).toEqual({
      conclusion_type: "MACRO_INTERPRETATION",
      subject: "MA breadth",
      state: "MIXED",
      a_share_transmission: "breadth with change",
    });
  });
});

function compactPair(directionA: string, directionB: string) {
  return {
    pair_key: `${directionA}|${directionB}`,
    decisions: [
      "NEUTRAL",
      "NEUTRAL",
      "NEUTRAL",
      "NEUTRAL",
      "AVAILABLE_MATERIAL_EVENTS",
      "NEUTRAL",
      "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST",
      "FAVORS_A",
      "INCOMPARABLE",
      "NEUTRAL",
    ],
  };
}

function compactSharedEvidence() {
  return {
    evidence_id: "evidence-1",
    research_rule_ref: "sector.energy.soft.001",
    coverage_evidence_id: "coverage-1",
  };
}

function compactMacroAttributions() {
  return {
    submission_summaries: Object.fromEntries(
      MACRO_AGENT_IDS.map((agentId) => [agentId, { claim_ref_used: null, effect: "NOT_MATERIAL" }]),
    ),
    target_attributions: [],
  };
}

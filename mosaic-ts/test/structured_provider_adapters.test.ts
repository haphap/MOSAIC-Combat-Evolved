import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  adaptStrictProviderJsonSchema,
  normalizeStrictProviderPayload,
} from "../src/agents/helpers/structured_provider_adapters.js";
import { createMacroSubmissionSchema, MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
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
import { macroSubmission } from "./helpers/macro.js";

const sectorCoverageDirective = {
  contract_version: "sector_role_event_coverage_directive_v1" as const,
  macro_event_fit: {
    coverage_state: "AVAILABLE_MATERIAL_EVENTS" as const,
    coverage_evidence_ids: ["coverage-1"] as [string],
  },
  catalysts: {
    coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST" as const,
    coverage_evidence_ids: ["coverage-1"] as [string],
  },
};

describe("strict structured provider adapters", () => {
  it("compacts a directive-bound selected Sector submission and restores the domain contract", () => {
    const directive = {
      selection_status: "SELECTED" as const,
      preferred_direction_id: "coal",
      least_preferred_direction_id: "oil_gas",
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
      const: "SECTOR_SELECTED_COMPACT_V2",
    });
    expect(providerSchema.properties.final_selection.properties).not.toHaveProperty("claims");

    const normalized = normalizeStrictProviderPayload({
      final_selection: {
        provider_contract: "SECTOR_SELECTED_COMPACT_V2",
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
        preferred_evidence_ids: ["evidence-1"],
        least_preferred_evidence_ids: ["evidence-1"],
        final_evidence_ids: ["evidence-1"],
        claim_kind: "INTERPRETATION",
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
    expect(parsed.final_selection.claims).toHaveLength(4);
    expect(
      "direction_id" in parsed.final_selection.preferred_direction &&
        parsed.final_selection.preferred_direction.direction_id,
    ).toBe("coal");
    expect(
      "direction_id" in parsed.final_selection.least_preferred_direction &&
        parsed.final_selection.least_preferred_direction.direction_id,
    ).toBe("oil_gas");
    expect(parsed.final_selection.macro_input_attributions).toHaveLength(MACRO_AGENT_IDS.length);
    expect(parsed.final_selection.preferred_direction.claim_refs).not.toEqual(
      parsed.final_selection.least_preferred_direction.claim_refs,
    );
  });

  it("keeps SHORT reachable and closes every compact Sector judgment to its own claim", () => {
    const preferredTickers = ["600001.SH", "600002.SH", "600003.SH", "600004.SH", "600005.SH"];
    const leastTickers = ["600006.SH", "600007.SH", "600008.SH", "600009.SH", "600010.SH"];
    const selected = z
      .object({
        final_selection: buildStandardSectorSchema("energy", "SELECTED", {
          selection_status: "SELECTED",
          preferred_direction_id: "coal",
          least_preferred_direction_id: "oil_gas",
          allowed_preferred_security_ids: preferredTickers,
          allowed_least_preferred_security_ids: leastTickers,
        }),
      })
      .strict();
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(selected)) as {
      properties: {
        final_selection: {
          properties: {
            preferred_security: {
              properties: { picks: { items: { properties: Record<string, unknown> } } };
            };
            least_preferred_security: {
              properties: { picks: { items: { properties: Record<string, unknown> } } };
            };
          };
        };
      };
    };
    const finalProperties = providerSchema.properties.final_selection.properties;
    expect(
      finalProperties.preferred_security.properties.picks.items.properties.position_action,
    ).toEqual({ type: "string", const: "LONG" });
    expect(
      finalProperties.least_preferred_security.properties.picks.items.properties.position_action,
    ).toEqual({ type: "string", enum: ["SHORT", "AVOID"] });

    const payload = {
      final_selection: {
        provider_contract: "SECTOR_SELECTED_COMPACT_V2",
        agent: "energy",
        preferred_direction_id: "coal",
        preferred_direction_local_id: "coal",
        preferred_strength: 3,
        preferred_thesis: "Coal has the strongest relative evidence.",
        least_preferred_direction_id: "oil_gas",
        least_preferred_direction_local_id: "oil_gas",
        least_preferred_strength: 2,
        least_preferred_thesis: "Oil and gas has the weakest relative evidence.",
        persistence_horizon: "WEEKS",
        confidence: 0.7,
        driver_summary: "Relative fundamentals and technicals favor coal.",
        risk_summary: "The relative ranking can reverse as inputs change.",
        preferred_evidence_ids: ["evidence-1"],
        least_preferred_evidence_ids: ["evidence-1"],
        final_evidence_ids: ["evidence-1"],
        claim_kind: "INTERPRETATION",
        research_rule_ref: "sector.energy.soft.001",
        preferred_security: {
          status: "PICKS_PRESENT",
          picks: preferredTickers.map((ts_code) => ({
            ts_code,
            position_action: "LONG",
            conviction: 0.2,
            thesis: "The preferred security confirms the coal direction.",
          })),
        },
        least_preferred_security: {
          status: "PICKS_PRESENT",
          picks: leastTickers.map((ts_code, index) => ({
            ts_code,
            position_action: index % 2 === 0 ? "SHORT" : "AVOID",
            conviction: 0.2,
            thesis: "The least-preferred security confirms the weak direction.",
          })),
        },
        macro_input_attributions: compactMacroAttributions(),
      },
    };
    const normalized = normalizeStrictProviderPayload(payload);
    const parsed = selected.parse(normalized).final_selection;
    expect(parsed.short_or_avoid_picks[0]?.position_action).toBe("SHORT");
    expect(parsed.long_picks.map((pick) => pick.position_action)).toEqual(Array(5).fill("LONG"));
    expect(parsed.short_or_avoid_picks.map((pick) => pick.position_action)).toEqual([
      "SHORT",
      "AVOID",
      "SHORT",
      "AVOID",
      "SHORT",
    ]);
    expect(parsed.claims).toHaveLength(14);
    const claims = new Map(parsed.claims.map((claim) => [claim.claim_id, claim]));
    for (const target of [
      parsed.preferred_direction,
      parsed.least_preferred_direction,
      ...parsed.key_drivers,
      ...parsed.risks,
      ...parsed.long_picks,
      ...parsed.short_or_avoid_picks,
    ]) {
      expect(target.claim_refs).toHaveLength(1);
      const claim = claims.get(target.claim_refs[0] as string);
      expect(claim).toBeDefined();
      const targetLocalRef =
        "pick_local_id" in target
          ? target.pick_local_id
          : "direction_local_id" in target
            ? target.direction_local_id
            : "driver_local_id" in target
              ? target.driver_local_id
              : target.risk_local_id;
      expect(claim?.structured_conclusion.target_local_ref).toBe(targetLocalRef);
    }
    expect(new Set(parsed.claim_refs)).toEqual(
      new Set(parsed.claims.map((claim) => claim.claim_id)),
    );

    const illegal = structuredClone(payload);
    const illegalLeastPick = illegal.final_selection.least_preferred_security.picks[0];
    if (!illegalLeastPick) throw new Error("least-preferred pick fixture required");
    illegalLeastPick.position_action = "LONG";
    expect(selected.safeParse(normalizeStrictProviderPayload(illegal)).success).toBe(false);
  });

  it("compacts pairwise Sector research and restores the exact domain matrix", () => {
    const domainSchema = buildSectorDirectionResearchSchema(
      ["coal", "oil_gas", "solar"],
      sectorCoverageDirective,
    );
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(domainSchema)) as {
      properties: { provider_contract: { const: string }; pairs: { prefixItems: unknown[] } };
    };
    expect(providerSchema.properties.provider_contract.const).toBe(
      "SECTOR_DIRECTION_RESEARCH_COMPACT_V3",
    );
    expect(providerSchema.properties.pairs.prefixItems).toHaveLength(3);

    const normalized = normalizeStrictProviderPayload({
      provider_contract: "SECTOR_DIRECTION_RESEARCH_COMPACT_V3",
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
      ["coal", "oil_gas", "solar"],
      sectorCoverageDirective,
      new Set(["provider-direction-1-coal-vs-oil-gas"]),
    );
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(domainSchema)) as {
      properties: {
        provider_contract: { const: string };
        direction_order: { minItems: number; maxItems: number; items: { enum: string[] } };
      };
    };
    expect(providerSchema.properties.provider_contract.const).toBe(
      "SECTOR_CONFLICT_REVIEW_COMPACT_V4",
    );
    expect(providerSchema.properties.direction_order).toMatchObject({
      minItems: 3,
      maxItems: 3,
      items: { enum: ["coal", "oil_gas", "solar"] },
    });
    const normalized = normalizeStrictProviderPayload({
      provider_contract: "SECTOR_CONFLICT_REVIEW_COMPACT_V4",
      ...compactSharedEvidence(),
      direction_order: ["solar", "oil_gas", "coal"],
      pairs: [
        compactPair("coal", "oil_gas"),
        compactPair("coal", "solar"),
        compactPair("oil_gas", "solar"),
      ],
    });
    const parsed = domainSchema.parse(normalized);
    expect(parsed.comparison_claims[0]?.claim_id).toBe("provider-conflict-1-coal-vs-oil-gas");
    expect(
      parsed.revised_comparisons.map((comparison) =>
        comparison.criterion_results.slice(0, 4).map((criterion) => criterion.verdict),
      ),
    ).toEqual([
      ["FAVORS_B", "FAVORS_B", "FAVORS_B", "FAVORS_B"],
      ["FAVORS_B", "FAVORS_B", "FAVORS_B", "FAVORS_B"],
      ["FAVORS_B", "FAVORS_B", "FAVORS_B", "FAVORS_B"],
    ]);
    expect(() =>
      normalizeStrictProviderPayload({
        provider_contract: "SECTOR_CONFLICT_REVIEW_COMPACT_V4",
        ...compactSharedEvidence(),
        direction_order: ["solar", "solar", "coal"],
        pairs: [
          compactPair("coal", "oil_gas"),
          compactPair("coal", "solar"),
          compactPair("oil_gas", "solar"),
        ],
      }),
    ).toThrow("conflict direction_order must contain every reviewed direction exactly once");
  });

  it("compacts Relationship Mapper output and binds predictive edges to frozen candidates", () => {
    const domainSchema = buildRelationshipMapperSchema({
      maxFactualEdges: 2,
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
      properties: {
        provider_contract: { const: string };
        factual_edges: { maxItems: number; uniqueItems: boolean };
      };
    };
    expect(providerSchema.properties.provider_contract.const).toBe(
      "RELATIONSHIP_MAPPER_COMPACT_V2",
    );
    expect(providerSchema.properties.factual_edges).toMatchObject({
      maxItems: 1,
      uniqueItems: true,
    });

    const compactPayload = {
      provider_contract: "RELATIONSHIP_MAPPER_COMPACT_V2",
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
    };
    const normalized = normalizeStrictProviderPayload(compactPayload);
    const parsed = domainSchema.parse(normalized);
    expect(parsed.claims).toHaveLength(1);
    expect(parsed.predictive_edges[0]?.edge_candidate_id).toBe("frozen-edge-1");

    const duplicateFactualProviderPayload = structuredClone(compactPayload);
    duplicateFactualProviderPayload.factual_edges.push({
      source_entity: "energy",
      target_entity: "industrials",
      edge_type: "INPUT_COST",
    });
    const duplicateNormalized = normalizeStrictProviderPayload(duplicateFactualProviderPayload);
    const duplicateResult = domainSchema.safeParse(duplicateNormalized);
    expect(duplicateResult.success).toBe(false);
    if (duplicateResult.success) throw new Error("duplicate factual provider payload was accepted");
    expect(duplicateResult.error.issues.map((issue) => issue.message)).toContain(
      "duplicate factual relationship tuple first used at factual_edges[0]",
    );

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
          branch.properties.provider_contract?.const === "SUPERINVESTOR_ABSTENTION_COMPACT_V2",
      ),
    ).toBe(true);
    const normalized = normalizeStrictProviderPayload({
      provider_contract: "SUPERINVESTOR_ABSTENTION_COMPACT_V2",
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
      "SUPERINVESTOR_ABSTENTION_COMPACT_V2",
    );
  });

  it("does not silently rewrite unsupported numeric Macro prose", () => {
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
      subject: "MA20 breadth",
      state: "40% MIXED",
      a_share_transmission: "40% breadth with -0.08125 change",
    });
  });

  it("compacts COMPONENTS Macro extraction and materializes independent canonical claims", () => {
    const domainSchema = createMacroSubmissionSchema("us_economy");
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(domainSchema)) as {
      properties: {
        provider_contract: { const: string };
        components: {
          prefixItems: Array<{
            properties: {
              component: { const: string };
              statement: { maxLength: number; pattern: string; description: string };
            };
          }>;
        };
      };
    };
    expect(providerSchema.properties.provider_contract.const).toBe("MACRO_COMPONENTS_COMPACT_V1");
    expect(providerSchema.properties).not.toHaveProperty("claims");
    const components = providerSchema.properties.components.prefixItems.map(
      (item) => item.properties.component.const,
    );
    expect(components).toEqual(["demand_trade", "employment", "growth_production", "prices"]);
    expect(providerSchema.properties.components.prefixItems[0]?.properties.statement).toMatchObject(
      {
        minLength: 24,
        maxLength: 160,
        pattern: "^[^0-9０-９%％\\r\\n]{24,160}$",
        description: expect.stringContaining("do not spell numbers in Chinese or English"),
      },
    );
    const kinds = ["FACT", "EVENT", "INTERPRETATION", "RISK_FLAG"] as const;
    const normalized = normalizeStrictProviderPayload({
      provider_contract: "MACRO_COMPONENTS_COMPACT_V1",
      mode: "COMPONENTS",
      components: components.map((component, index) => ({
        component,
        signal: { direction: "NEUTRAL", strength: 0 },
        persistence_horizon: "WEEKS",
        confidence: 0.6,
        channel: "A-share earnings transmission",
        claim_kind: kinds[index],
        statement: "The component evidence supports a cautious assessment",
        state: "The component state is mixed",
        a_share_transmission: "The component has a balanced A-share transmission",
        evidence_id: `evidence:${String(index + 1).repeat(64)}`,
        research_rule_ref: index === 2 ? "macro.us_economy.soft.001" : null,
        snapshot_echo: null,
      })),
    });
    const parsed = domainSchema.parse(normalized);
    if (parsed.mode !== "COMPONENTS") throw new Error("component output required");
    expect(parsed.claims).toHaveLength(components.length);
    expect(parsed.key_drivers).toHaveLength(components.length);
    expect(new Set(parsed.components.flatMap((component) => component.claim_refs)).size).toBe(
      components.length,
    );
    const claims = new Map(parsed.claims.map((claim) => [claim.claim_id, claim]));
    for (const component of parsed.components) {
      expect(component.claim_refs).toHaveLength(1);
      expect(claims.get(component.claim_refs[0] as string)?.structured_conclusion.subject).toBe(
        component.component,
      );
    }
    expect(parsed.claims.map((claim) => claim.structured_conclusion.conclusion_type)).toEqual([
      "MACRO_FACT",
      "MACRO_EVENT",
      "MACRO_INTERPRETATION",
      "MACRO_RISK",
    ]);
    expect(parsed.claims.map((claim) => claim.research_rule_refs)).toEqual([
      [],
      [],
      ["macro.us_economy.soft.001"],
      [],
    ]);
    expect(
      parsed.claims.every((claim) => claim.structured_conclusion.snapshot_echo_id === null),
    ).toBe(true);
  });

  it("compacts DIRECT Macro extraction without losing its authored judgment", () => {
    const domainSchema = createMacroSubmissionSchema("geopolitical");
    const providerSchema = adaptStrictProviderJsonSchema(z.toJSONSchema(domainSchema)) as {
      properties: { provider_contract: { const: string }; judgment: unknown };
    };
    expect(providerSchema.properties.provider_contract.const).toBe("MACRO_DIRECT_COMPACT_V1");
    expect(providerSchema.properties).not.toHaveProperty("claims");
    const normalized = normalizeStrictProviderPayload({
      provider_contract: "MACRO_DIRECT_COMPACT_V1",
      mode: "DIRECT",
      judgment: {
        signal: { direction: "ADVERSE", strength: 3 },
        persistence_horizon: "WEEKS",
        confidence: 0.7,
        channel: "A-share risk premium",
        claim_kind: "EVENT",
        statement: "The registered event remains active",
        subject: "registered geopolitical event",
        state: "The event is escalating",
        a_share_transmission: "Risk appetite faces an adverse external shock",
        evidence_id: `evidence:${"a".repeat(64)}`,
        research_rule_ref: null,
        snapshot_echo: null,
      },
    });
    const parsed = domainSchema.parse(normalized);
    if (parsed.mode !== "DIRECT") throw new Error("direct output required");
    expect(parsed.signal).toMatchObject({
      direction: "ADVERSE",
      strength: 3,
      persistence_horizon: "WEEKS",
      confidence: 0.7,
      channels: ["A-share risk premium."],
    });
    expect(parsed.claims[0]).toMatchObject({
      claim_kind: "EVENT",
      statement: "The registered event remains active.",
      structured_conclusion: {
        conclusion_type: "MACRO_EVENT",
        subject: "registered geopolitical event",
        state: "The event is escalating.",
        a_share_transmission: "Risk appetite faces an adverse external shock.",
      },
      evidence_ids: [`evidence:${"a".repeat(64)}`],
      research_rule_refs: [],
    });
    expect(parsed.signal.claim_refs).toEqual([parsed.claims[0]?.claim_id]);
    expect(parsed.key_drivers).toEqual([parsed.claims[0]?.statement]);
  });

  it("rejects numeric prose and canonicalizes compact state labels and dangling tails", () => {
    const domainSchema = createMacroSubmissionSchema("geopolitical");
    const judgment = {
      signal: { direction: "ADVERSE", strength: 2 },
      persistence_horizon: "WEEKS",
      confidence: 0.6,
      channel: "A-share risk appetite",
      claim_kind: "EVENT",
      statement: "The registered event remains active",
      subject: "registered geopolitical event",
      state: "The event remains unresolved",
      a_share_transmission: "Risk appetite faces an adverse external shock",
      evidence_id: `evidence:${"b".repeat(64)}`,
      research_rule_ref: null,
      snapshot_echo: null,
    };
    const numeric = normalizeStrictProviderPayload({
      provider_contract: "MACRO_DIRECT_COMPACT_V1",
      mode: "DIRECT",
      judgment: { ...judgment, statement: "事件影响扩大至一百零二点一" },
    });
    expect(domainSchema.safeParse(numeric).success).toBe(false);
    const stateLabel = domainSchema.parse(
      normalizeStrictProviderPayload({
        provider_contract: "MACRO_DIRECT_COMPACT_V1",
        mode: "DIRECT",
        judgment: { ...judgment, state: "UNKNOWN" },
      }),
    );
    if (stateLabel.mode !== "DIRECT") throw new Error("direct output required");
    expect(stateLabel.claims[0]?.structured_conclusion.state).toBe(
      "The observed registered geopolitical event state is uncertain.",
    );
    const repaired = domainSchema.parse(
      normalizeStrictProviderPayload({
        provider_contract: "MACRO_DIRECT_COMPACT_V1",
        mode: "DIRECT",
        judgment: { ...judgment, a_share_transmission: "Risk appetite weakens and" },
      }),
    );
    if (repaired.mode !== "DIRECT") throw new Error("direct output required");
    expect(repaired.claims[0]?.structured_conclusion.a_share_transmission).toBe(
      "Risk appetite weakens.",
    );
    const tenorCanonicalized = domainSchema.parse(
      normalizeStrictProviderPayload({
        provider_contract: "MACRO_DIRECT_COMPACT_V1",
        mode: "DIRECT",
        judgment: {
          ...judgment,
          statement:
            "The ten-year government bond yield curve is repricing toward tighter conditions",
          channel: "十年期中国国债曲线压制风险偏好",
        },
      }),
    );
    if (tenorCanonicalized.mode !== "DIRECT") throw new Error("direct output required");
    expect(tenorCanonicalized.claims[0]?.statement).toContain("long-term government bond");
    expect(tenorCanonicalized.signal.channels[0]).toContain("长期中国国债");
  });

  it("round-trips four independently cited Macro components through the provider normalizer", () => {
    const base = macroSubmission("us_economy");
    if (base.mode !== "COMPONENTS") throw new Error("component fixture required");
    const templateClaim = base.claims[0];
    if (!templateClaim) throw new Error("claim fixture required");
    const claims = base.components.map((component) => ({
      ...templateClaim,
      claim_id: `us-economy-${component.component}-claim`,
      structured_conclusion: {
        ...templateClaim.structured_conclusion,
        subject: component.component,
      },
      evidence_ids: [`fixture:us_economy:${component.component}`],
    }));
    const providerPayload = {
      ...base,
      claims,
      components: base.components.map((component) => ({
        ...component,
        claim_refs: [`us-economy-${component.component}-claim`],
      })),
    };
    const normalized = normalizeStrictProviderPayload(structuredClone(providerPayload));
    expect(normalized).toEqual(providerPayload);
    expect(createMacroSubmissionSchema("us_economy").parse(normalized)).toEqual(providerPayload);
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
    claim_kind: "INTERPRETATION",
    research_rule_ref: "sector.energy.soft.001",
    macro_event_coverage_evidence_ids: ["coverage-1"],
    catalyst_coverage_evidence_ids: ["coverage-1"],
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

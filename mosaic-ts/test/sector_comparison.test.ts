import { describe, expect, it } from "vitest";
import { z } from "zod";
import { adaptStrictProviderJsonSchema } from "../src/agents/helpers/structured_provider_adapters.js";
import {
  applyConflictReview,
  buildSectorConflictReviewSchema,
  buildSectorDirectionResearchSchema,
  type DirectionCriterionResult,
  type DirectionPairwiseComparisonSubmission,
  DirectionPairwiseComparisonSubmissionSchema,
  MAX_SECTOR_COMPARISON_CLAIM_REFS,
  MAX_SECTOR_COVERAGE_EVIDENCE_IDS,
  reduceDirectionMatrix,
  resolveDirectionPair,
  type SectorCoverageDirective,
} from "../src/agents/sector/comparison.js";
import { SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT } from "../src/agents/sector/registry.js";
import {
  buildPairwiseFinalDirective,
  type SectorSecurityScoringRow,
} from "../src/agents/sector/selection.js";

const claim = (id: string) => ({
  claim_id: id,
  claim_kind: "FACT" as const,
  statement: `evidence for ${id}`,
  structured_conclusion: { id },
  evidence_ids: [`evidence:${id}`, "coverage:catalyst", "coverage:event"],
  research_rule_refs: [],
});

const coverageDirective: SectorCoverageDirective = {
  contract_version: "sector_role_event_coverage_directive_v1",
  macro_event_fit: {
    coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT",
    coverage_evidence_ids: ["coverage:event"],
  },
  catalysts: {
    coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST",
    coverage_evidence_ids: ["coverage:catalyst"],
  },
};

function criteria(
  verdicts: Partial<Record<string, "FAVORS_A" | "FAVORS_B" | "NEUTRAL">> = {},
  claimId = "claim-1",
): DirectionCriterionResult[] {
  const core: DirectionCriterionResult[] = [
    "FUNDAMENTALS",
    "VALUATION",
    "BASKET_TECHNICALS",
    "RISK_ASYMMETRY",
  ].map((criterion) => ({
    criterion,
    comparison_status: "COMPARABLE" as const,
    verdict: verdicts[criterion] ?? "NEUTRAL",
    claim_refs: [claimId],
  })) as DirectionCriterionResult[];
  const supplemental: DirectionCriterionResult[] = [
    {
      criterion: "MACRO_EVENT_FIT",
      coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT",
      comparison_status: "COMPARABLE",
      verdict: "NEUTRAL",
      claim_refs: [claimId],
      coverage_evidence_ids: ["coverage:event"],
    },
    {
      criterion: "CATALYSTS",
      coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST",
      comparison_status: "COMPARABLE",
      verdict: "NEUTRAL",
      claim_refs: [claimId],
      coverage_evidence_ids: ["coverage:catalyst"],
    },
    ...["ETF_PRICE_CONFIRMATION", "ETF_SHARE_FLOW_CONFIRMATION"].map((criterion) => ({
      criterion,
      comparison_status: "COMPARABLE" as const,
      verdict: verdicts[criterion] ?? "NEUTRAL",
      claim_refs: [claimId],
    })),
  ] as DirectionCriterionResult[];
  return [...core, ...supplemental];
}

function pair(
  a: string,
  b: string,
  verdicts: Partial<Record<string, "FAVORS_A" | "FAVORS_B" | "NEUTRAL">> = {
    FUNDAMENTALS: "FAVORS_A",
    VALUATION: "FAVORS_A",
  },
  id = `${a}-${b}`,
): DirectionPairwiseComparisonSubmission {
  return {
    comparison_local_id: id,
    direction_a_id: a,
    direction_b_id: b,
    criterion_results: criteria(verdicts),
    claim_refs: ["claim-1"],
  };
}

function pairWithClaimRefs(
  input: DirectionPairwiseComparisonSubmission,
  claimRefs: string[],
): DirectionPairwiseComparisonSubmission {
  return {
    ...input,
    criterion_results: input.criterion_results.map((result) =>
      result.claim_refs.length === 0
        ? result
        : ({ ...result, claim_refs: [...claimRefs] } as DirectionCriterionResult),
    ),
    claim_refs: [...claimRefs],
  };
}

describe("Sector direction research contract", () => {
  const directions = ["a", "b", "c"] as const;

  it("requires the exact ordered pair matrix and all eight criteria", () => {
    const schema = buildSectorDirectionResearchSchema(directions, coverageDirective);
    const valid = {
      research_mode: "PAIRWISE" as const,
      comparison_claims: [claim("claim-1")],
      direction_comparisons: [pair("a", "b"), pair("a", "c"), pair("b", "c")],
    };
    expect(schema.parse(valid).direction_comparisons).toHaveLength(3);
    expect(
      schema.safeParse({ ...valid, direction_comparisons: valid.direction_comparisons.slice(1) })
        .success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...valid,
        direction_comparisons: [pair("b", "a"), pair("a", "c"), pair("b", "c")],
      }).success,
    ).toBe(false);
    const missingCriterion = pair("a", "b");
    missingCriterion.criterion_results.pop();
    expect(
      schema.safeParse({
        ...valid,
        direction_comparisons: [missingCriterion, pair("a", "c"), pair("b", "c")],
      }).success,
    ).toBe(false);
  });

  it("rejects a direction universe smaller than three before schema construction", () => {
    expect(() =>
      buildSectorDirectionResearchSchema(["a", "b"] as never, coverageDirective),
    ).toThrow("requires at least three directions");
  });

  it("rejects coverage criteria whose claims cite unrelated evidence", () => {
    const schema = buildSectorDirectionResearchSchema(directions, coverageDirective);
    const unrelatedClaim = {
      ...claim("claim-1"),
      evidence_ids: ["evidence:unrelated"],
    };
    expect(
      schema.safeParse({
        research_mode: "PAIRWISE",
        comparison_claims: [unrelatedClaim],
        direction_comparisons: [pair("a", "b"), pair("a", "c"), pair("b", "c")],
      }).success,
    ).toBe(false);
  });

  it("requires unique research claims with exact reference closure", () => {
    const schema = buildSectorDirectionResearchSchema(directions, coverageDirective);
    const comparisons = [pair("a", "b"), pair("a", "c"), pair("b", "c")];
    expect(
      schema.safeParse({
        research_mode: "PAIRWISE",
        comparison_claims: [claim("claim-1"), claim("claim-1")],
        direction_comparisons: comparisons,
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        research_mode: "PAIRWISE",
        comparison_claims: [claim("claim-1"), claim("orphan")],
        direction_comparisons: comparisons,
      }).success,
    ).toBe(false);
  });

  it("bounds comparison claims, references, coverage ids, and provider tuples", () => {
    const schema = buildSectorDirectionResearchSchema(directions, coverageDirective);
    const threeClaims = [claim("claim-1"), claim("claim-2"), claim("claim-3")];
    const maximumValid = {
      research_mode: "PAIRWISE" as const,
      comparison_claims: threeClaims,
      direction_comparisons: [
        pairWithClaimRefs(pair("a", "b"), ["claim-1"]),
        pairWithClaimRefs(pair("a", "c"), ["claim-2"]),
        pairWithClaimRefs(pair("b", "c"), ["claim-3"]),
      ],
    };
    expect(schema.safeParse(maximumValid).success).toBe(true);

    const fourthClaim = claim("claim-4");
    expect(
      schema.safeParse({
        ...maximumValid,
        comparison_claims: [...threeClaims, fourthClaim],
        direction_comparisons: [
          pairWithClaimRefs(pair("a", "b"), ["claim-1", "claim-4"]),
          maximumValid.direction_comparisons[1],
          maximumValid.direction_comparisons[2],
        ],
      }).success,
    ).toBe(false);

    const excessiveRefs = Array.from(
      { length: MAX_SECTOR_COMPARISON_CLAIM_REFS + 1 },
      (_, index) => `claim-${index + 1}`,
    );
    expect(
      DirectionPairwiseComparisonSubmissionSchema.safeParse(
        pairWithClaimRefs(pair("a", "b"), excessiveRefs),
      ).success,
    ).toBe(false);

    const rawSchema = z.toJSONSchema(schema) as unknown as {
      properties: {
        comparison_claims: { maxItems: number };
        direction_comparisons: {
          prefixItems: Array<{ properties: { claim_refs: { maxItems: number } } }>;
        };
      };
    };
    expect(rawSchema.properties.comparison_claims.maxItems).toBe(3);
    expect(rawSchema.properties.direction_comparisons.prefixItems).toHaveLength(3);
    expect(
      rawSchema.properties.direction_comparisons.prefixItems[0]?.properties.claim_refs.maxItems,
    ).toBe(MAX_SECTOR_COMPARISON_CLAIM_REFS);

    const providerSchema = adaptStrictProviderJsonSchema(rawSchema) as {
      properties: {
        coverage_evidence_ids: { maxItems: number };
        pairs: {
          minItems: number;
          maxItems: number;
          items: false;
          prefixItems: Array<{
            properties: { decisions: { minItems: number; maxItems: number; items: false } };
          }>;
        };
      };
    };
    expect(providerSchema.properties.coverage_evidence_ids.maxItems).toBe(
      MAX_SECTOR_COVERAGE_EVIDENCE_IDS,
    );
    expect(providerSchema.properties.pairs).toMatchObject({
      minItems: 3,
      maxItems: 3,
      items: false,
    });
    expect(providerSchema.properties.pairs.prefixItems[0]?.properties.decisions).toMatchObject({
      minItems: 10,
      maxItems: 10,
      items: false,
    });
  });

  it("rejects a role-event coverage tuple above the provider-safe cap", () => {
    const coverageEvidenceIds = Array.from(
      { length: MAX_SECTOR_COVERAGE_EVIDENCE_IDS + 1 },
      (_, index) => `coverage:${String(index + 1).padStart(3, "0")}`,
    ) as [string, ...string[]];
    expect(() =>
      buildSectorDirectionResearchSchema(directions, {
        contract_version: "sector_role_event_coverage_directive_v1",
        macro_event_fit: {
          coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT",
          coverage_evidence_ids: coverageEvidenceIds,
        },
        catalysts: {
          coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST",
          coverage_evidence_ids: coverageEvidenceIds,
        },
      }),
    ).toThrow(`sector coverage evidence ids exceed ${MAX_SECTOR_COVERAGE_EVIDENCE_IDS}`);
  });
});

describe("deterministic weighted pair resolver", () => {
  it("requires two non-ETF votes and a weighted margin of one", () => {
    expect(resolveDirectionPair(pair("a", "b")).resolved_verdict).toBe("A");
    const etfOnly = resolveDirectionPair(
      pair("a", "b", {
        ETF_PRICE_CONFIRMATION: "FAVORS_A",
        ETF_SHARE_FLOW_CONFIRMATION: "FAVORS_A",
      }),
    );
    expect(etfOnly.weighted_support_a).toBe(1);
    expect(etfOnly.resolved_verdict).toBe("NO_CLEAR_WINNER");
    expect(etfOnly.decisive_voting_criteria).toEqual([]);
  });

  it("counts each comparable ETF criterion as one half vote", () => {
    const result = resolveDirectionPair(
      pair("a", "b", {
        FUNDAMENTALS: "FAVORS_A",
        VALUATION: "FAVORS_A",
        BASKET_TECHNICALS: "FAVORS_B",
        ETF_PRICE_CONFIRMATION: "FAVORS_A",
      }),
    );
    expect(result.base_support_count_a).toBe(2);
    expect(result.base_support_count_b).toBe(1);
    expect(result.optional_etf_support_weight_a).toBe(0.5);
    expect(result.resolved_verdict).toBe("A");
  });
});

describe("deterministic security shortlist", () => {
  it("ranks available PIT rows by liquidity and excludes unavailable rows", () => {
    const comparisons = [pair("a", "b"), pair("a", "c"), pair("b", "c")];
    const resolutions = comparisons.map(resolveDirectionPair);
    const directive = buildPairwiseFinalDirective({
      reduction: reduceDirectionMatrix(["a", "b", "c"], resolutions),
      finalizedComparisons: comparisons,
      resolutions,
      comparisonClaims: [claim("claim-1")],
      securityScoringRows: [
        scoringRow("600002.SH", "a", 100),
        scoringRow("600001.SH", "a", 200),
        scoringRow("600003.SH", "b", 50),
        scoringRow("600004.SH", "c", null),
      ],
    });
    expect(directive.allowed_preferred_security_ids).toEqual(["600001.SH", "600002.SH"]);
    expect(directive.allowed_least_preferred_security_ids).toEqual([]);
    expect(directive.preferred_security_shortlist_id).toMatch(/^sector-shortlist:/);
    expect(directive.least_preferred_security_shortlist_hash).toMatch(/^sha256:/);
  });
});

describe("Condorcet reduction and bounded review", () => {
  it("finds a unique strict winner and loser without review", () => {
    const rows = [pair("a", "b"), pair("a", "c"), pair("b", "c")].map(resolveDirectionPair);
    const reduction = reduceDirectionMatrix(["a", "b", "c"], rows);
    expect(reduction.condorcet_winner_direction_id).toBe("a");
    expect(reduction.condorcet_loser_direction_id).toBe("c");
    expect(reduction.conflict_type).toBe("NONE");
  });

  it("includes no-edge endpoints and a three-node cycle in the conflict set", () => {
    expect(SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.conflict_set_rule).toBe(
      "IF_UNIQUE_CONDORCET_WINNER_AND_LOSER_THEN_EMPTY_ELSE_SORTED_UNION_OF_CYCLE_NO_EDGE_AND_NONUNIQUE_EXTREME_COPELAND_TIES",
    );
    const noEdge = [
      resolveDirectionPair(pair("a", "b", {})),
      resolveDirectionPair(pair("a", "c")),
      resolveDirectionPair(pair("b", "c")),
    ];
    expect(reduceDirectionMatrix(["a", "b", "c"], noEdge).conflict_direction_ids).toEqual([
      "a",
      "b",
    ]);
    const cycle = [
      resolveDirectionPair(pair("a", "b")),
      resolveDirectionPair(pair("a", "c", { FUNDAMENTALS: "FAVORS_B", VALUATION: "FAVORS_B" })),
      resolveDirectionPair(pair("b", "c")),
    ];
    expect(reduceDirectionMatrix(["a", "b", "c"], cycle)).toMatchObject({
      conflict_type: "MULTIPLE",
      conflict_direction_ids: ["a", "b", "c"],
      condorcet_winner_direction_id: null,
      condorcet_loser_direction_id: null,
    });
  });

  it("allows one complete conflict-internal review and preserves outside rows", () => {
    const initial = [pair("a", "b", {}), pair("a", "c"), pair("b", "c")];
    const review = {
      review_round: 1 as const,
      comparison_claims: [claim("claim-1")],
      revised_comparisons: [
        pair("a", "b", { FUNDAMENTALS: "FAVORS_A", VALUATION: "FAVORS_A" }, "review-a-b"),
      ],
    };
    expect(
      buildSectorConflictReviewSchema(["a", "b"], coverageDirective).safeParse(review).success,
    ).toBe(true);
    const finalized = applyConflictReview(initial, review, ["a", "b"], coverageDirective);
    expect(finalized[0]?.comparison_local_id).toBe("review-a-b");
    expect(finalized[1]).toBe(initial[1]);
    expect(finalized[2]).toBe(initial[2]);
  });

  it("rejects conflict review claims that redefine immutable research claims", () => {
    const review = {
      review_round: 1 as const,
      comparison_claims: [claim("claim-1")],
      revised_comparisons: [
        pair("a", "b", { FUNDAMENTALS: "FAVORS_A", VALUATION: "FAVORS_A" }, "review-a-b"),
      ],
    };
    expect(
      buildSectorConflictReviewSchema(
        ["a", "b"],
        coverageDirective,
        new Set(["claim-1"]),
      ).safeParse(review).success,
    ).toBe(false);
  });
});

function scoringRow(
  tsCode: string,
  directionId: string,
  amount: number | null,
): SectorSecurityScoringRow {
  const available = amount !== null;
  return {
    ts_code: tsCode,
    direction_id: directionId,
    availability_status: available ? "AVAILABLE" : "UNAVAILABLE",
    unavailability_reason: available ? null : "MISSING_MONEYFLOW",
    observation_date: "2026-07-17",
    released_at: "2026-07-17",
    vintage_at: "2026-07-17",
    pit_status: "PIT_VERIFIED",
    adjusted_return_20d: available ? 0.1 : null,
    realized_volatility_20d: available ? 0.2 : null,
    median_amount_20d_cny: amount,
    net_moneyflow_20d_cny: available ? 10 : null,
    observation_count: available ? 20 : 0,
    required_observation_count: 20,
    coverage_ratio: available ? 1 : 0,
    evidence_ids: ["score-evidence"],
    security_scoring_row_hash: `sha256:${"a".repeat(64)}`,
  };
}

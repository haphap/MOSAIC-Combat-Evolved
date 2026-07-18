import { describe, expect, it } from "vitest";
import {
  applyConflictReview,
  buildSectorConflictReviewSchema,
  buildSectorDirectionResearchSchema,
  type DirectionCriterionResult,
  type DirectionPairwiseComparisonSubmission,
  determineLeastPreferredEligibility,
  reduceDirectionMatrix,
  resolveDirectionPair,
  resolveSingleDirectionQualification,
} from "../src/agents/sector/comparison.js";

const claim = (id: string) => ({
  claim_id: id,
  claim_kind: "FACT" as const,
  statement: `evidence for ${id}`,
  structured_conclusion: { id },
  evidence_ids: [`evidence:${id}`],
  research_rule_refs: [],
});

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

describe("Sector direction research contract", () => {
  const directions = ["a", "b", "c"] as const;

  it("requires the exact ordered pair matrix and all eight criteria", () => {
    const schema = buildSectorDirectionResearchSchema(directions);
    const valid = {
      research_mode: "PAIRWISE" as const,
      comparison_claims: [claim("claim-1")],
      direction_comparisons: [pair("a", "b"), pair("a", "c"), pair("b", "c")],
      single_direction_qualification: null,
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

  it("uses the single-direction discriminant when n=1", () => {
    const schema = buildSectorDirectionResearchSchema(["only"]);
    expect(
      schema.parse({
        research_mode: "SINGLE_DIRECTION_QUALIFICATION",
        comparison_claims: [claim("claim-1")],
        direction_comparisons: [],
        single_direction_qualification: {
          qualification_local_id: "q-1",
          direction_id: "only",
          null_benchmark_contract_id: "registered-null",
          criterion_results: criteria({ FUNDAMENTALS: "FAVORS_A", VALUATION: "FAVORS_A" }),
          claim_refs: ["claim-1"],
        },
      }).research_mode,
    ).toBe("SINGLE_DIRECTION_QUALIFICATION");
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

  it("applies the same resolver to the registered single-direction null", () => {
    const result = resolveSingleDirectionQualification({
      qualification_local_id: "q-1",
      direction_id: "only",
      null_benchmark_contract_id: "registered-null",
      criterion_results: criteria({ FUNDAMENTALS: "FAVORS_A", VALUATION: "FAVORS_A" }),
      claim_refs: ["claim-1"],
    });
    expect(result.status).toBe("QUALIFIED");
    expect(result.base_support_count_direction).toBe(2);
  });
});

describe("Condorcet reduction and bounded review", () => {
  it("finds a unique strict winner and loser without review", () => {
    const rows = [pair("a", "b"), pair("a", "c"), pair("b", "c")].map(resolveDirectionPair);
    const reduction = reduceDirectionMatrix(["a", "b", "c"], rows);
    expect(reduction.condorcet_winner_direction_id).toBe("a");
    expect(reduction.condorcet_loser_direction_id).toBe("c");
    expect(reduction.conflict_type).toBe("NONE");
    expect(determineLeastPreferredEligibility(["a", "b", "c"], reduction, rows)).toMatchObject({
      status: "REQUIRED",
      least_preferred_direction_id: "c",
    });
  });

  it("includes no-edge endpoints and a three-node cycle in the conflict set", () => {
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
    expect(buildSectorConflictReviewSchema(["a", "b"]).safeParse(review).success).toBe(true);
    const finalized = applyConflictReview(initial, review, ["a", "b"]);
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
      buildSectorConflictReviewSchema(["a", "b"], new Set(["claim-1"])).safeParse(review).success,
    ).toBe(false);
  });
});

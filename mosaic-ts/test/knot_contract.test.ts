import { describe, expect, it } from "vitest";
import {
  KNOT_RUNTIME_CONTRACT_MANIFEST,
  KnotRuntimeContractManifestSchema,
  knotResearchComparisonScore,
  normalizedSectorInferenceCost,
} from "../src/autoresearch/knot_contract.js";

describe("KNOT runtime contract", () => {
  it("freezes the single global score/scheduler contract", () => {
    expect(KnotRuntimeContractManifestSchema.parse(KNOT_RUNTIME_CONTRACT_MANIFEST)).toEqual(
      KNOT_RUNTIME_CONTRACT_MANIFEST,
    );
    expect(KNOT_RUNTIME_CONTRACT_MANIFEST.research_score_contract.agent_failure_score).toBe(-2);
    expect(KNOT_RUNTIME_CONTRACT_MANIFEST.scheduler_contract.minimum_accountable_pairs).toBe(30);
    expect(KNOT_RUNTIME_CONTRACT_MANIFEST.scheduler_contract.decision_usage_weight_enabled).toBe(
      false,
    );
  });

  it("uses the frozen Sector cost formula and keeps failure below every success", () => {
    const cost = normalizedSectorInferenceCost({
      inputTokens: 50,
      outputTokens: 25,
      totalStageInputTokenCap: 100,
      totalStageOutputTokenCap: 100,
    });
    expect(cost).toBeCloseTo(0.375);
    const score = knotResearchComparisonScore({
      disposition: "SCORE",
      agentKind: "STANDARD_SECTOR",
      normalizedScore: -1,
      normalizedInferenceCost: 1,
      conflictReviewTriggered: true,
    });
    expect(score.research_comparison_score).toBeCloseTo(-1.25);
    expect(
      knotResearchComparisonScore({
        disposition: "AGENT_FAILURE",
        agentKind: "STANDARD_SECTOR",
      }).research_comparison_score,
    ).toBe(-2);
  });

  it("does not impose Sector costs on other roles", () => {
    expect(
      knotResearchComparisonScore({
        disposition: "SCORE",
        agentKind: "NON_SECTOR",
        normalizedScore: 0.4,
      }),
    ).toEqual({
      raw_research_score: 0.4,
      sector_cost_adjusted_score: null,
      research_comparison_score: 0.4,
    });
  });
});

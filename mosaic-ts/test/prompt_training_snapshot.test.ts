import { describe, expect, it } from "vitest";
import { buildPromptTrainingSnapshot } from "../src/autoresearch/prompt_training_snapshot.js";

const HASH = `sha256:${"a".repeat(64)}`;
const target = { agentId: "china", stage: "agent_run", cohort: "cohort_default" } as const;
const facets = [
  "growth_production",
  "prices",
  "credit",
  "external_demand_trade",
  "fiscal",
  "a_share_transmission",
];

function observations() {
  return Array.from({ length: 30 }, (_, index) => ({
    schemaVersion: "prompt_behavior_evaluation_v1" as const,
    observationId: `china-${String(index).padStart(2, "0")}`,
    target,
    agentOutputRef: `accepted://china-${String(index).padStart(2, "0")}`,
    outcomeLabelRef: `outcome://china-${String(index).padStart(2, "0")}`,
    outcomeContractVersion: "china-outcome-v2",
    evaluatorVersion: "china-facet-evaluator-v1",
    maturedAt: `2025-01-${String(index + 1).padStart(2, "0")}T00:00:00Z`,
    normalizedScore: index === 0 ? -0.8 : 0.2,
    facetScores: Object.fromEntries(
      facets.map((facetId) => [facetId, facetId === "prices" && index < 3 ? -0.6 : 0.2]),
    ),
    failureCategories: index < 3 ? ["missed_turn"] : [],
    facetFailureCategories: Object.fromEntries(
      facets.map((facetId) => [facetId, facetId === "prices" && index < 3 ? ["missed_turn"] : []]),
    ),
    ...(index === 0
      ? {
          failureCaseRef: "failure://china-00",
          evidenceGapSummary: "Price turning evidence was underweighted.",
        }
      : {}),
  }));
}

function build(rows = observations()) {
  return buildPromptTrainingSnapshot({
    target,
    snapshotId: "training-china-1",
    cutoffAt: "2025-02-01T00:00:00Z",
    outcomeContractVersion: "china-outcome-v2",
    evaluatorVersion: "china-facet-evaluator-v1",
    behaviorContractHash: HASH,
    requiredFacetIds: facets,
    observations: rows,
  });
}

describe("Prompt behavior training snapshot", () => {
  it("aggregates exact role-facet feedback from mature observations", () => {
    const snapshot = build();
    expect(snapshot.matureSampleCount).toBe(30);
    expect(Object.keys(snapshot.behaviorFeedback.facets)).toEqual([...facets].sort());
    expect(snapshot.behaviorFeedback.facets.prices?.meanScore).toBeLessThan(
      snapshot.behaviorFeedback.facets.fiscal?.meanScore ?? -1,
    );
    expect(snapshot.behaviorFeedback.facets.prices?.failureCategoryCounts).toEqual({
      missed_turn: 3,
    });
    expect(snapshot.snapshotHash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(snapshot.datasetSnapshotHash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("rejects missing facets, future outcomes, duplicates and cold starts", () => {
    const missing = observations();
    delete missing[0]?.facetScores.fiscal;
    expect(() => build(missing)).toThrow(/facet_coverage_incomplete/);

    const future = observations();
    if (future[0]) future[0].maturedAt = "2025-02-02T00:00:00Z";
    expect(() => build(future)).toThrow(/not_mature_at_cutoff/);

    const duplicate = observations();
    if (duplicate[1] && duplicate[0]) duplicate[1].observationId = duplicate[0].observationId;
    expect(() => build(duplicate)).toThrow(/identity_invalid/);

    const driftedEvaluator = observations();
    if (driftedEvaluator[0]) driftedEvaluator[0].evaluatorVersion = "changed-evaluator";
    expect(() => build(driftedEvaluator)).toThrow(/evaluator_binding_mismatch/);
    expect(() => build(observations().slice(0, 29))).toThrow(/insufficient_mature_samples/);
  });
});

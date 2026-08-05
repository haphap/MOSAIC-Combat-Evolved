import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { compareCanonicalStrings } from "../src/agents/helpers/canonical_json.js";
import { PromptPromotionDecisionSchema } from "../src/autoresearch/prompt_optimizer_contract.js";
import {
  evaluatePromptPromotionSeries,
  promptOrderedMean,
} from "../src/autoresearch/prompt_promotion_policy.js";

interface PromotionGateExpectedMetrics {
  sampleCount: number;
  repeatSeedCount: number;
  pairedDelta: number;
  adjustedAlpha: number;
  confidenceLower: number;
  confidenceUpper: number;
  bootstrapPValue: number;
  tailDelta: number;
  championFailureRate: number;
  candidateFailureRate: number;
  criticalMinimum: number;
}

interface PromotionGateCase {
  name: string;
  familyCandidateCount: number;
  deltaSegments: Array<{ count: number; value: number }>;
  championFailureIndexes: number[];
  candidateFailureIndexes: number[];
  criticalIndexes: number[];
  expected: {
    eligible: boolean;
    reasons: string[];
    metrics: PromotionGateExpectedMetrics;
  };
}

interface ConformanceFixture {
  schemaVersion: "prompt_optimizer_cross_runtime_conformance_v1";
  numericSeedOrder: { input: number[]; expected: number[] };
  orderedAggregation: {
    repeatCount: number;
    candidateScore: number;
    championScore: number;
    expectedCandidateMean: number;
    expectedChampionMean: number;
    expectedPairedDelta: number;
  };
  unicodeRefOrder: { input: string[]; expected: string[] };
  equalScoreTie: {
    inputCandidateIds: string[];
    score: number;
    expectedWinner: string;
  };
  timestampPrecision: {
    accepted: string[];
    rejectedMinute: string;
    rejectedSubMillisecond: string;
  };
  promotionGates: {
    bootstrapSamples: number;
    blockLength: number;
    familyAlpha: number;
    tailQuantile: number;
    minimumPairedDelta: number;
    minimumTailDelta: number;
    maximumFailureRateIncrease: number;
    minimumCriticalSampleDelta: number;
    seed: string;
    cases: PromotionGateCase[];
  };
}

const fixture = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "../tests/fixtures/prompt_optimizer_cross_runtime_conformance_v1.json"),
    "utf8",
  ),
) as ConformanceFixture;

function promotionDecision(decidedAt: string) {
  const hash = `sha256:${"a".repeat(64)}`;
  return {
    schemaVersion: "prompt_promotion_decision_v1" as const,
    decisionId: "decision-conformance",
    experimentId: "experiment-conformance",
    familyId: "family-conformance",
    candidateId: "candidate-conformance",
    policyVersion: "policy-conformance-v1",
    policyConfigHash: hash,
    decision: "REJECTED" as const,
    reasons: ["conformance_fixture"],
    metricSummary: { paired_delta: 0 },
    evidenceHash: hash,
    decidedAt,
  };
}

describe("Prompt Optimizer cross-runtime conformance fixture", () => {
  it("uses the expected fixture version", () => {
    expect(fixture.schemaVersion).toBe("prompt_optimizer_cross_runtime_conformance_v1");
  });

  it("orders numeric repeat seeds numerically", () => {
    expect([...fixture.numericSeedOrder.input].sort((left, right) => left - right)).toEqual(
      fixture.numericSeedOrder.expected,
    );
  });

  it("uses explicit sequential means for aggregate parity", () => {
    const row = fixture.orderedAggregation;
    const candidateScores = Array.from({ length: row.repeatCount }, () => row.candidateScore);
    const championScores = Array.from({ length: row.repeatCount }, () => row.championScore);
    const deltas = Array.from(
      { length: row.repeatCount },
      () => row.candidateScore - row.championScore,
    );

    expect(promptOrderedMean(candidateScores)).toBe(row.expectedCandidateMean);
    expect(promptOrderedMean(championScores)).toBe(row.expectedChampionMean);
    expect(promptOrderedMean(deltas)).toBe(row.expectedPairedDelta);
  });

  it("matches the shared promotion-gate golden cases", () => {
    const contract = fixture.promotionGates;
    for (const scenario of contract.cases) {
      const deltas = scenario.deltaSegments.flatMap(({ count, value }) =>
        Array.from({ length: count }, () => value),
      );
      const championFailureIndexes = new Set(scenario.championFailureIndexes);
      const candidateFailureIndexes = new Set(scenario.candidateFailureIndexes);
      const evidence = evaluatePromptPromotionSeries({
        deltas,
        championFailures: deltas.map((_, index) => championFailureIndexes.has(index)),
        candidateFailures: deltas.map((_, index) => candidateFailureIndexes.has(index)),
        criticalDeltas: scenario.criticalIndexes.map((index) => deltas[index] ?? Number.NaN),
        repeatSeedCount: 2,
        familyCandidateCount: scenario.familyCandidateCount,
        policy: {
          minimumMatureSamples: 30,
          minimumRepeatSeeds: 2,
          minimumPairedDelta: contract.minimumPairedDelta,
          familyAlpha: contract.familyAlpha,
          bootstrapSamples: contract.bootstrapSamples,
          blockLength: contract.blockLength,
          tailQuantile: contract.tailQuantile,
          minimumTailDelta: contract.minimumTailDelta,
          maximumFailureRateIncrease: contract.maximumFailureRateIncrease,
          minimumCriticalSampleDelta: contract.minimumCriticalSampleDelta,
        },
        seed: contract.seed,
      });
      expect(
        {
          eligible: evidence.reasons.length === 0,
          reasons: evidence.reasons,
          metrics: evidence.metrics,
        },
        scenario.name,
      ).toEqual(scenario.expected);
    }
  });

  it("uses JCS UTF-16 order for refs and equal-score candidate ties", () => {
    expect([...fixture.unicodeRefOrder.input].sort(compareCanonicalStrings)).toEqual(
      fixture.unicodeRefOrder.expected,
    );

    const winner = [...fixture.equalScoreTie.inputCandidateIds].sort(compareCanonicalStrings)[0];
    expect(winner).toBe(fixture.equalScoreTie.expectedWinner);
  });

  it("requires seconds and rejects sub-millisecond timestamps", () => {
    for (const accepted of fixture.timestampPrecision.accepted) {
      expect(PromptPromotionDecisionSchema.safeParse(promotionDecision(accepted)).success).toBe(
        true,
      );
    }
    expect(
      PromptPromotionDecisionSchema.safeParse(
        promotionDecision(fixture.timestampPrecision.rejectedMinute),
      ).success,
    ).toBe(false);
    expect(
      PromptPromotionDecisionSchema.safeParse(
        promotionDecision(fixture.timestampPrecision.rejectedSubMillisecond),
      ).success,
    ).toBe(false);
  });
});

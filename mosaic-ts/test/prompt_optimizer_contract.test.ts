import { describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { RUNTIME_AGENT_STAGE_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";
import {
  assertCandidateMatchesSplit,
  assertCandidateMatchesTrainingSnapshot,
  DatasetSplitManifestSchema,
  PromptCandidateFamilySchema,
  PromptCandidateSchema,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
  PromptOptimizerTargetSchema,
  PromptPromotionDecisionSchema,
  PromptTrainingSnapshotSchema,
  promptBehaviorAlignmentHash,
  promptMutationHypothesis,
  promptMutationSummary,
} from "../src/autoresearch/prompt_optimizer_contract.js";

const HASH = `sha256:${"a".repeat(64)}`;
const OTHER_HASH = `sha256:${"b".repeat(64)}`;
const EXCLUDED_SAMPLE_IDS_HASH = canonicalJsonHash(["holdout-1", "validation-1"]);
const COMMIT = "c".repeat(40);
const target = { agentId: "china", stage: "agent_run", cohort: "cohort_default" } as const;

function sample(sampleId: string, startAt: string, endAt: string, maturedAt: string) {
  return {
    sampleId,
    inputRef: `snapshot://${sampleId}`,
    outcomeRef: `outcome://${sampleId}`,
    eventWindow: { startAt, endAt },
    maturedAt,
  };
}

function splitManifest() {
  return {
    schemaVersion: "prompt_dataset_split_v1" as const,
    splitId: "split-1",
    target,
    cutoffAt: "2025-01-31T00:00:00Z",
    training: {
      snapshotId: "training-1",
      snapshotHash: HASH,
      windowStartAt: "2025-01-01T00:00:00Z",
      windowEndAt: "2025-01-31T00:00:00Z",
      samples: [
        sample("train-1", "2025-01-10T00:00:00Z", "2025-01-11T00:00:00Z", "2025-01-20T00:00:00Z"),
      ],
    },
    validation: {
      snapshotId: "validation-1",
      snapshotHash: OTHER_HASH,
      windowStartAt: "2025-02-01T00:00:00Z",
      windowEndAt: "2025-02-28T00:00:00Z",
      samples: [
        sample(
          "validation-1",
          "2025-02-10T00:00:00Z",
          "2025-02-11T00:00:00Z",
          "2025-02-20T00:00:00Z",
        ),
      ],
    },
    holdout: {
      snapshotId: "holdout-1",
      snapshotHash: `sha256:${"d".repeat(64)}`,
      windowStartAt: "2025-03-01T00:00:00Z",
      windowEndAt: "2025-03-31T00:00:00Z",
      samples: [
        sample("holdout-1", "2025-03-10T00:00:00Z", "2025-03-11T00:00:00Z", "2025-03-20T00:00:00Z"),
      ],
    },
    evaluatorVersion: "agent-outcome-v2",
    createdAt: "2025-04-01T00:00:00Z",
  };
}

function candidate() {
  const promptHashes = { zh: HASH, en: OTHER_HASH };
  const mutationCategories = ["CONFLICT_RESOLUTION"] as const;
  return {
    schemaVersion: "prompt_candidate_v1" as const,
    candidateId: "candidate-1",
    parentId: "champion-1",
    parentPromptCommit: COMMIT,
    parentPromptHashes: { zh: OTHER_HASH, en: HASH },
    target,
    promptRefs: { zh: "private://candidate-1.zh", en: "private://candidate-1.en" },
    promptHashes,
    trainingSnapshotId: "training-1",
    trainingSnapshotHash: HASH,
    excludedSampleIdsHash: EXCLUDED_SAMPLE_IDS_HASH,
    mutatorConfigHash: HASH,
    mutatorCommit: COMMIT,
    mutationCategories,
    mutationSummary: promptMutationSummary(mutationCategories),
    hypothesis: promptMutationHypothesis(mutationCategories),
    alignmentVerifierVersion: "bilingual-alignment-v1",
    behaviorAlignmentHash: promptBehaviorAlignmentHash({
      promptHashes,
      alignmentVerifierVersion: "bilingual-alignment-v1",
    }),
    behaviorContractHash: HASH,
    privateLineageHash: HASH,
    privateStateArtifactHash: HASH,
    createdAt: "2025-04-01T00:00:00Z",
  };
}

describe("prompt optimizer public contracts", () => {
  it("covers every one of the 28 Agents and 29 stage bindings", () => {
    expect(new Set(RUNTIME_AGENT_STAGE_SPECS.map((row) => row.agent)).size).toBe(28);
    expect(RUNTIME_AGENT_STAGE_SPECS).toHaveLength(29);
    for (const row of RUNTIME_AGENT_STAGE_SPECS) {
      expect(
        PromptOptimizerTargetSchema.parse({
          agentId: row.agent,
          stage: row.stage,
          cohort: "cohort_default",
        }),
      ).toBeDefined();
    }
  });

  it("rejects a stage owned by a different Agent", () => {
    expect(() =>
      PromptOptimizerTargetSchema.parse({
        agentId: "china",
        stage: "cio_final",
        cohort: "cohort_default",
      }),
    ).toThrow(/does not belong/);
  });

  it("accepts the minimal public objects and rejects prompt bodies", () => {
    expect(PromptCandidateSchema.parse(candidate())).toBeDefined();
    expect(() =>
      PromptCandidateSchema.parse({ ...candidate(), zh_prompt: "private body" }),
    ).toThrow();
    expect(() =>
      PromptCandidateSchema.parse({
        ...candidate(),
        deterministic_policy: { "cro.stop_loss_pct": -0.2 },
      }),
    ).toThrow();
    expect(() =>
      PromptCandidateSchema.parse({
        ...candidate(),
        alignmentVerifierVersion: "private verifier rationale must not cross",
      }),
    ).toThrow();
    expect(
      PromptCandidateFamilySchema.parse({
        schemaVersion: "prompt_candidate_family_v1",
        familyId: "family-1",
        target,
        championReleaseId: "champion-1",
        championPromptCommit: COMMIT,
        championPromptRefs: { zh: "private://champion.zh", en: "private://champion.en" },
        championPromptHashes: { zh: OTHER_HASH, en: HASH },
        datasetSplitId: "split-1",
        datasetSplitManifestHash: HASH,
        candidateIds: ["candidate-1"],
        validationExperimentIds: [],
        selectedCandidateId: null,
        selectedExperimentId: null,
        holdoutExperimentId: null,
        status: "REGISTERED",
        createdAt: "2025-04-01T00:00:00Z",
        updatedAt: "2025-04-01T00:00:00Z",
      }),
    ).toBeDefined();
    expect(
      PromptExperimentSchema.parse({
        schemaVersion: "prompt_experiment_v1",
        experimentId: "experiment-1",
        familyId: "family-1",
        candidateId: "candidate-1",
        championId: "champion-1",
        target,
        championPromptCommit: COMMIT,
        championPromptRefs: { zh: "private://champion.zh", en: "private://champion.en" },
        championPromptHashes: { zh: HASH, en: OTHER_HASH },
        candidatePromptRefs: candidate().promptRefs,
        candidatePromptHashes: { zh: OTHER_HASH, en: HASH },
        datasetSplitId: "split-1",
        datasetSplitManifestHash: HASH,
        validationSnapshotHash: OTHER_HASH,
        holdoutSnapshotHash: HASH,
        modelConfigHash: HASH,
        toolConfigHash: HASH,
        componentCalibrationSnapshotHash: HASH,
        darwinianUsageSnapshotHash: OTHER_HASH,
        evaluatorVersion: "agent-outcome-v2",
        evaluatorConfigHash: HASH,
        codeCommit: COMMIT,
        repeatSeeds: [1, 2],
        runIds: [],
        metrics: {},
        tailFailureCaseRefs: [],
        status: "PENDING",
        holdoutOpenedAt: null,
        createdAt: "2025-04-01T00:00:00Z",
        completedAt: null,
      }),
    ).toBeDefined();
    expect(
      PromptPromotionDecisionSchema.parse({
        schemaVersion: "prompt_promotion_decision_v1",
        decisionId: "decision-1",
        experimentId: "experiment-1",
        familyId: "family-1",
        candidateId: "candidate-1",
        policyVersion: "policy-v1",
        policyConfigHash: HASH,
        decision: "REJECTED",
        reasons: ["validation_delta_below_threshold"],
        metricSummary: { paired_delta: 0 },
        evidenceHash: HASH,
        decidedAt: "2025-04-01T00:00:00Z",
      }),
    ).toBeDefined();
  });

  it("exposes only a strict training projection to KNOT", () => {
    const trainingBody = {
      schemaVersion: "prompt_training_snapshot_v1",
      target,
      snapshotId: "training-1",
      datasetSnapshotHash: OTHER_HASH,
      excludedSampleIdsHash: EXCLUDED_SAMPLE_IDS_HASH,
      cutoffAt: "2025-01-31T00:00:00Z",
      outcomeContractVersion: "china-outcome-v2",
      evaluatorVersion: "agent-outcome-v2",
      matureSampleCount: 30,
      scoreSummary: { mean: 0.1 },
      failureCategoryCounts: { missing_counter_evidence: 4 },
      tailFailureCaseRefs: ["failure://train-1"],
      evidenceGapSummaries: ["Counter-evidence was not checked before conclusion."],
      behaviorFeedback: {
        contractHash: HASH,
        facets: {
          growth_production: {
            evaluationMode: "DIRECT_OUTCOME",
            observationStatus: "OBSERVED",
            directMatureSampleCount: 30,
            experimentPairCount: 0,
            meanScore: 0.1,
            lowerTailScore: -0.2,
            failureCategoryCounts: { missing_counter_evidence: 4 },
          },
        },
      },
    } as const;
    const training = PromptTrainingSnapshotSchema.parse({
      ...trainingBody,
      snapshotHash: canonicalJsonHash(trainingBody),
    });
    const boundCandidate = PromptCandidateSchema.parse({
      ...candidate(),
      trainingSnapshotHash: training.snapshotHash,
    });
    assertCandidateMatchesTrainingSnapshot(boundCandidate, training);
    expect(() =>
      PromptTrainingSnapshotSchema.parse({ ...training, validationSnapshotHash: OTHER_HASH }),
    ).toThrow();
    expect(() =>
      assertCandidateMatchesTrainingSnapshot(
        { ...boundCandidate, behaviorContractHash: OTHER_HASH },
        training,
      ),
    ).toThrow("candidate_training_snapshot_mismatch");
    expect(() =>
      PromptTrainingSnapshotSchema.parse({
        ...training,
        behaviorFeedback: {
          ...training.behaviorFeedback,
          facets: {
            growth_production: {
              ...training.behaviorFeedback.facets.growth_production,
              directMatureSampleCount: 31,
            },
          },
        },
      }),
    ).toThrow(/complete mature training sample set/);
    expect(() =>
      PromptTrainingSnapshotSchema.parse({ ...training, evaluatorVersion: "changed-evaluator" }),
    ).toThrow(/hash must bind/);
  });

  it("rejects overlapping or future-leaking split samples", () => {
    expect(DatasetSplitManifestSchema.parse(splitManifest())).toBeDefined();
    const overlap = splitManifest();
    const overlapSample = overlap.holdout.samples.at(0);
    if (!overlapSample) throw new Error("missing overlap fixture sample");
    overlap.holdout.samples[0] = {
      ...overlapSample,
      sampleId: "validation-1",
    };
    expect(() => DatasetSplitManifestSchema.parse(overlap)).toThrow(/cannot overlap/);

    const future = splitManifest();
    const futureSample = future.holdout.samples.at(0);
    if (!futureSample) throw new Error("missing future fixture sample");
    future.holdout.samples[0] = {
      ...futureSample,
      maturedAt: "2025-05-01T00:00:00Z",
    };
    expect(() => DatasetSplitManifestSchema.parse(future)).toThrow(/immature/);
  });

  it("orders timestamp offsets by instant rather than source spelling", () => {
    const value = splitManifest();
    value.training.samples[0] = sample(
      "train-1",
      "2025-01-11T00:00:00-12:00",
      "2025-01-11T01:00:00-12:00",
      "2025-01-11T23:00:00+14:00",
    );
    expect(() => DatasetSplitManifestSchema.parse(value)).toThrow(/mature before/);
  });

  it("binds Candidate training identity to the frozen split", () => {
    const parsedCandidate = PromptCandidateSchema.parse(candidate());
    const parsedSplit = DatasetSplitManifestSchema.parse(splitManifest());
    expect(() => assertCandidateMatchesSplit(parsedCandidate, parsedSplit)).not.toThrow();
    expect(() =>
      assertCandidateMatchesSplit(
        { ...parsedCandidate, trainingSnapshotHash: OTHER_HASH },
        parsedSplit,
      ),
    ).toThrow("candidate_dataset_split_mismatch");
    expect(() =>
      assertCandidateMatchesSplit(
        { ...parsedCandidate, excludedSampleIdsHash: OTHER_HASH },
        parsedSplit,
      ),
    ).toThrow("candidate_dataset_split_mismatch");
  });

  it("requires complete runs to carry one normalized Agent-specific score", () => {
    const base = {
      schemaVersion: "prompt_experiment_run_v1" as const,
      runId: "run-1",
      experimentId: "experiment-1",
      partition: "VALIDATION" as const,
      side: "CHAMPION" as const,
      sampleId: "validation-1",
      seed: 1,
      status: "COMPLETE" as const,
      agentOutputRef: "accepted://output-1",
      metrics: { normalized_score: 0.2 },
      failureCaseRefs: [],
      traceRef: null,
      effectiveInputHash: HASH,
      errorCode: null,
      startedAt: "2025-04-01T00:00:00Z",
      completedAt: "2025-04-01T00:01:00Z",
    };
    expect(PromptExperimentRunSchema.parse(base)).toBeDefined();
    expect(() => PromptExperimentRunSchema.parse({ ...base, metrics: {} })).toThrow(/score/);
  });
});

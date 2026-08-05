import { describe, expect, it } from "vitest";
import {
  canonicalJsonHash,
  compareCanonicalStrings,
} from "../src/agents/helpers/canonical_json.js";
import { OUTCOME_LABEL_REGISTRY } from "../src/autoresearch/outcome_registry.js";
import { selectPromptCandidateFamily } from "../src/autoresearch/prompt_candidate_family.js";
import {
  DatasetSplitManifestSchema,
  type PromptCandidateFamily,
  PromptCandidateFamilySchema,
  PromptCandidateSchema,
  type PromptExperiment,
  type PromptExperimentRun,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
  promptCandidateFamilyId,
  promptDatasetPartitionSnapshotHash,
  promptDatasetSampleId,
  promptDatasetSplitId,
  promptExperimentId,
  promptExperimentRunId,
  promptMutationHypothesis,
  promptMutationSummary,
} from "../src/autoresearch/prompt_optimizer_contract.js";
import { authorizeStoredPromptPromotion } from "../src/autoresearch/prompt_promotion_authority.js";
import {
  createPromptPromotionDecision,
  type PromptPromotionPolicy,
  PromptPromotionPolicySchema,
  promptEvaluationBinding,
} from "../src/autoresearch/prompt_promotion_policy.js";
import type { BridgeApi } from "../src/bridge/types.js";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;
const COMMIT = "c".repeat(40);
const target = { agentId: "china", stage: "agent_run", cohort: "cohort_default" } as const;
const evaluatorVersion = OUTCOME_LABEL_REGISTRY.china?.scoring_contract_version;
if (!evaluatorVersion) throw new Error("missing china outcome fixture");

function sample(sampleId: string, month: string) {
  const ordinal = Number(sampleId.match(/(\d+)$/)?.[1] ?? "1");
  const day = String(Math.floor((ordinal - 1) / 12) + 1).padStart(2, "0");
  const startHour = String(((ordinal - 1) % 12) * 2).padStart(2, "0");
  const endHour = String(((ordinal - 1) % 12) * 2 + 1).padStart(2, "0");
  const value = {
    inputRef: `snapshot://${sampleId}`,
    inputHash: HASH_A,
    outcomeRef: `outcome://${sampleId}`,
    outcomeHash: HASH_B,
    eventWindow: {
      startAt: `2025-${month}-${day}T${startHour}:00:00Z`,
      endAt: `2025-${month}-${day}T${endHour}:00:00Z`,
    },
    maturedAt: `2025-${month}-10T00:00:00Z`,
  };
  return { ...value, sampleId: promptDatasetSampleId(value) };
}

function policy(
  split: ReturnType<typeof DatasetSplitManifestSchema.parse>,
  overrides: Partial<PromptPromotionPolicy> = {},
): PromptPromotionPolicy {
  return {
    policyVersion: "prompt-promotion-test-v1",
    minimumMatureSamples: 30,
    minimumRepeatSeeds: 2,
    minimumPairedDelta: 0.05,
    familyAlpha: 0.05,
    bootstrapSamples: 999,
    blockLength: 1,
    tailQuantile: 0.25,
    minimumTailDelta: 0.05,
    maximumFailureRateIncrease: 0,
    criticalValidationSampleIds: [split.validation.samples[0]?.sampleId ?? "missing"],
    criticalHoldoutSampleIds: [split.holdout.samples[0]?.sampleId ?? "missing"],
    minimumCriticalSampleDelta: 0,
    ...overrides,
  };
}

function buildFixture(
  options: {
    validationDeltas?: ReadonlyArray<number>;
    holdoutDeltas?: ReadonlyArray<number>;
    candidateFailure?: boolean;
    familySize?: number;
    policyOverrides?: Partial<PromptPromotionPolicy>;
  } = {},
) {
  const validationDeltas = options.validationDeltas ?? Array.from({ length: 30 }, () => 0.2);
  const holdoutDeltas = options.holdoutDeltas ?? Array.from({ length: 30 }, () => 0.2);
  const trainingSamples = [sample("train-1", "01")];
  const validationSamples = validationDeltas.map((_, index) =>
    sample(`validation-${index + 1}`, "02"),
  );
  const holdoutSamples = holdoutDeltas.map((_, index) => sample(`holdout-${index + 1}`, "03"));
  const splitBody = {
    schemaVersion: "prompt_dataset_split_v1",
    target,
    trainingProjectionHash: HASH_B,
    cutoffAt: "2025-01-31T00:00:00Z",
    training: {
      snapshotHash: promptDatasetPartitionSnapshotHash({ samples: trainingSamples }),
      windowStartAt: "2025-01-01T00:00:00Z",
      windowEndAt: "2025-01-31T00:00:00Z",
      samples: trainingSamples,
    },
    validation: {
      snapshotHash: promptDatasetPartitionSnapshotHash({ samples: validationSamples }),
      windowStartAt: "2025-02-01T00:00:00Z",
      windowEndAt: "2025-02-28T00:00:00Z",
      samples: validationSamples,
    },
    holdout: {
      snapshotHash: promptDatasetPartitionSnapshotHash({ samples: holdoutSamples }),
      windowStartAt: "2025-03-01T00:00:00Z",
      windowEndAt: "2025-03-31T00:00:00Z",
      samples: holdoutSamples,
    },
    evaluatorVersion,
    createdAt: "2025-04-01T00:00:00Z",
  };
  const split = DatasetSplitManifestSchema.parse({
    ...splitBody,
    splitId: promptDatasetSplitId(splitBody),
  });
  const promotionPolicy = policy(split, options.policyOverrides);
  const familySize = options.familySize ?? 1;
  const candidateIds = [
    "candidate-promotion",
    ...Array.from({ length: familySize - 1 }, (_, index) => `candidate-sibling-${index + 1}`),
  ].sort();
  const familyBody = {
    schemaVersion: "prompt_candidate_family_v1" as const,
    target,
    championReleaseId: "champion-promotion",
    championPromptCommit: COMMIT,
    championPromptRefs: { zh: "private://champion.zh", en: "private://champion.en" },
    championPromptHashes: { zh: HASH_A, en: HASH_A },
    datasetSplitId: split.splitId,
    datasetSplitManifestHash: canonicalJsonHash(split),
    promotionPolicyVersion: promotionPolicy.policyVersion,
    promotionPolicyConfigHash: canonicalJsonHash(promotionPolicy),
    candidateIds,
    createdAt: "2025-04-01T00:00:00Z",
  };
  const family = PromptCandidateFamilySchema.parse({
    ...familyBody,
    familyId: promptCandidateFamilyId(familyBody),
  });
  const experimentBody = {
    schemaVersion: "prompt_experiment_v1" as const,
    familyId: family.familyId,
    candidateId: "candidate-promotion",
    championId: family.championReleaseId,
    target,
    championPromptCommit: COMMIT,
    championPromptRefs: family.championPromptRefs,
    championPromptHashes: family.championPromptHashes,
    candidatePromptRefs: { zh: "private://candidate.zh", en: "private://candidate.en" },
    candidatePromptHashes: { zh: HASH_B, en: HASH_B },
    datasetSplitId: split.splitId,
    datasetSplitManifestHash: canonicalJsonHash(split),
    promotionPolicyVersion: promotionPolicy.policyVersion,
    promotionPolicyConfigHash: canonicalJsonHash(promotionPolicy),
    modelConfigHash: HASH_A,
    toolConfigHash: HASH_A,
    componentCalibrationSnapshotHash: HASH_B,
    darwinianUsageSnapshotHash: HASH_A,
    executorAdapterHash: HASH_A,
    evaluatorAdapterHash: HASH_B,
    evaluationBinding: {
      evaluationObject: "AcceptedMacroTransmission",
      evaluationObjectSchemaVersion: "accepted_macro_transmission_v2",
      primaryLabelId: "china_macro_transmission_a_share_path_5d",
      scoringContractVersion: evaluatorVersion,
      outcomeContractVersion: "macro_transmission_outcome_v2",
    },
    evaluatorVersion,
    evaluatorConfigHash: HASH_B,
    codeCommit: COMMIT,
    repeatSeeds: [1, 2],
    runIds: [],
    metrics: {},
    tailFailureCaseRefs: [],
    status: "COMPLETE" as const,
    holdoutOpenedAt: "2025-04-01T00:00:00Z",
    createdAt: "2025-04-01T00:00:00Z",
    completedAt: "2025-04-01T01:00:00Z",
  };
  const experimentId = promptExperimentId(experimentBody);
  const runs: PromptExperimentRun[] = [];
  for (const [partition, deltas] of [
    ["VALIDATION", validationDeltas],
    ["HOLDOUT", holdoutDeltas],
  ] as const) {
    for (const [index, delta] of deltas.entries()) {
      const sampleId =
        (partition === "VALIDATION" ? split.validation.samples : split.holdout.samples)[index]
          ?.sampleId ?? "missing";
      for (const seed of [1, 2]) {
        for (const side of ["CHAMPION", "CANDIDATE"] as const) {
          const failed =
            options.candidateFailure &&
            partition === "VALIDATION" &&
            index === 0 &&
            side === "CANDIDATE";
          runs.push(
            PromptExperimentRunSchema.parse({
              schemaVersion: "prompt_experiment_run_v1",
              runId: promptExperimentRunId({
                experimentId,
                partition,
                side,
                sampleId,
                seed,
              }),
              experimentId,
              partition,
              side,
              sampleId,
              seed,
              status: "COMPLETE",
              leaseOwner: "promotion-worker",
              leaseExpiresAt: "2025-04-01T00:05:00Z",
              attempt: 1,
              retryable: false,
              attemptFailureCodes: [],
              agentOutputRef: `accepted://${partition}/${index}/${seed}/${side}`,
              metrics: {
                normalized_score: side === "CANDIDATE" ? 0.5 + delta : 0.5,
                schema_failure: 0,
                contract_failure: 0,
                tool_failure: failed ? 1 : 0,
              },
              failureCaseRefs: failed ? ["failure://tool"] : [],
              traceRef: null,
              effectiveInputHash: HASH_A,
              errorCode: null,
              startedAt: "2025-04-01T00:00:00Z",
              completedAt: "2025-04-01T00:01:00Z",
            }),
          );
        }
      }
    }
  }
  const experiment = PromptExperimentSchema.parse({
    ...experimentBody,
    experimentId,
    runIds: runs.map((run) => run.runId).sort(),
    metrics: {
      validation_paired_delta:
        validationDeltas.reduce((sum, value) => sum + value, 0) / validationDeltas.length,
      holdout_paired_delta:
        holdoutDeltas.reduce((sum, value) => sum + value, 0) / holdoutDeltas.length,
    },
  });
  return { split, runs, experiment, family, promotionPolicy };
}

function decide(fixture: ReturnType<typeof buildFixture>) {
  return createPromptPromotionDecision({
    ...fixture,
    policy: fixture.promotionPolicy,
    decidedAt: "2025-04-01T02:00:00Z",
  });
}

function validationExperimentFor(
  fixture: ReturnType<typeof buildFixture>,
  family: PromptCandidateFamily,
  candidateId: string,
  environmentOverrides: Partial<PromptExperiment> = {},
) {
  const definition = {
    ...fixture.experiment,
    ...environmentOverrides,
    familyId: family.familyId,
    candidateId,
    candidatePromptRefs: {
      zh: `private://${candidateId}.zh`,
      en: `private://${candidateId}.en`,
    },
    candidatePromptHashes: { zh: HASH_B, en: HASH_B },
    runIds: [],
    metrics: {},
    tailFailureCaseRefs: [],
    status: "VALIDATION_COMPLETE" as const,
    holdoutOpenedAt: null,
    completedAt: null,
  };
  const experimentId = promptExperimentId(definition);
  const runs = fixture.runs
    .filter((run) => run.partition === "VALIDATION")
    .map((run) => {
      const coordinates = { ...run, experimentId };
      return PromptExperimentRunSchema.parse({
        ...coordinates,
        runId: promptExperimentRunId(coordinates),
      });
    });
  return {
    experiment: PromptExperimentSchema.parse({
      ...definition,
      experimentId,
      runIds: runs.map((run) => run.runId).sort(compareCanonicalStrings),
      metrics: {
        validation_paired_delta: fixture.experiment.metrics.validation_paired_delta,
      },
    }),
    runs,
  };
}

describe("Agent-specific Prompt promotion policy", () => {
  it("selects the best validation-eligible Candidate before opening holdout", () => {
    const highMean = buildFixture({
      validationDeltas: [
        ...Array.from({ length: 8 }, () => -0.2),
        ...Array.from({ length: 22 }, () => 0.5),
      ],
    });
    const viable = buildFixture({ validationDeltas: Array.from({ length: 30 }, () => 0.2) });
    const candidateIds = ["candidate-high-tail-risk", "candidate-viable"].sort();
    const familyBody = {
      ...highMean.family,
      candidateIds,
    };
    const family = PromptCandidateFamilySchema.parse({
      ...familyBody,
      familyId: promptCandidateFamilyId(familyBody),
    });
    const validationFixture = (fixture: ReturnType<typeof buildFixture>, candidateId: string) => {
      const experimentDefinition = {
        ...fixture.experiment,
        familyId: family.familyId,
        candidateId,
        status: "VALIDATION_COMPLETE" as const,
        holdoutOpenedAt: null,
        completedAt: null,
        runIds: [],
        metrics: {},
        tailFailureCaseRefs: [],
      };
      const canonicalExperimentId = promptExperimentId(experimentDefinition);
      const runs = fixture.runs
        .filter((run) => run.partition === "VALIDATION")
        .map((run) => {
          const coordinates = { ...run, experimentId: canonicalExperimentId };
          return {
            ...coordinates,
            runId: promptExperimentRunId(coordinates),
          };
        });
      const deltas = runs
        .filter((run) => run.side === "CANDIDATE")
        .map((candidateRun) => {
          const champion = runs.find(
            (run) =>
              run.side === "CHAMPION" &&
              run.sampleId === candidateRun.sampleId &&
              run.seed === candidateRun.seed,
          );
          if (!champion) throw new Error("missing validation pair fixture");
          return (
            (candidateRun.metrics.normalized_score ?? 0) - (champion.metrics.normalized_score ?? 0)
          );
        });
      const experiment = PromptExperimentSchema.parse({
        ...experimentDefinition,
        experimentId: canonicalExperimentId,
        runIds: runs.map((run) => run.runId).sort(),
        metrics: {
          validation_paired_delta:
            deltas.reduce((total, value) => total + value, 0) / deltas.length,
        },
      });
      return { experiment, runs };
    };
    const high = validationFixture(highMean, candidateIds[0] ?? "");
    const low = validationFixture(viable, candidateIds[1] ?? "");
    const selected = selectPromptCandidateFamily({
      family,
      validationExperiments: [high.experiment, low.experiment],
      validationRuns: [
        { experimentId: high.experiment.experimentId, runs: high.runs },
        { experimentId: low.experiment.experimentId, runs: low.runs },
      ],
      split: highMean.split,
      policy: highMean.promotionPolicy,
    });
    expect(high.experiment.metrics.validation_paired_delta).toBeGreaterThan(
      low.experiment.metrics.validation_paired_delta ?? 0,
    );
    expect(selected.selectedCandidateId).toBe("candidate-viable");
  });

  it("uses one frozen environment and JCS ordering for equal-score family siblings", () => {
    const fixture = buildFixture({ familySize: 2 });
    const candidateIds = ["candidate-Z", "candidate-a"].sort(compareCanonicalStrings);
    const familyBody = { ...fixture.family, candidateIds };
    const family = PromptCandidateFamilySchema.parse({
      ...familyBody,
      familyId: promptCandidateFamilyId(familyBody),
    });
    const upper = validationExperimentFor(fixture, family, "candidate-Z");
    const lower = validationExperimentFor(fixture, family, "candidate-a");
    expect(
      selectPromptCandidateFamily({
        family,
        validationExperiments: [lower.experiment, upper.experiment],
        validationRuns: [
          { experimentId: lower.experiment.experimentId, runs: lower.runs },
          { experimentId: upper.experiment.experimentId, runs: upper.runs },
        ],
        split: fixture.split,
        policy: fixture.promotionPolicy,
      }),
    ).toEqual({
      selectedCandidateId: "candidate-Z",
      selectedExperimentId: upper.experiment.experimentId,
    });

    const drifted = validationExperimentFor(fixture, family, "candidate-a", {
      modelConfigHash: HASH_B,
    });
    expect(() =>
      selectPromptCandidateFamily({
        family,
        validationExperiments: [upper.experiment, drifted.experiment],
        validationRuns: [
          { experimentId: upper.experiment.experimentId, runs: upper.runs },
          { experimentId: drifted.experiment.experimentId, runs: drifted.runs },
        ],
        split: fixture.split,
        policy: fixture.promotionPolicy,
      }),
    ).toThrow("prompt_candidate_family_validation_experiment_invalid");
  });

  it("rejects sub-millisecond timestamps and trimmed duplicate policy sample IDs", () => {
    const fixture = buildFixture();
    expect(
      PromptExperimentRunSchema.safeParse({
        ...fixture.runs[0],
        completedAt: "2025-04-01T00:01:00.000499Z",
      }).success,
    ).toBe(false);
    const critical = fixture.promotionPolicy.criticalValidationSampleIds[0];
    expect(
      PromptPromotionPolicySchema.safeParse({
        ...fixture.promotionPolicy,
        criticalValidationSampleIds: [critical, ` ${critical} `],
      }).success,
    ).toBe(false);
    expect(
      PromptPromotionPolicySchema.safeParse({
        ...fixture.promotionPolicy,
        policyVersion: ` ${fixture.promotionPolicy.policyVersion} `,
      }).success,
    ).toBe(false);
  });

  it("accepts only after validation and holdout pass every statistical guard", () => {
    const decision = decide(buildFixture());
    expect(decision.decision).toBe("ELIGIBLE");
    expect(decision.reasons).toEqual(["all_promotion_gates_passed"]);
    expect(decision.metricSummary.validation_confidence_lower).toBeGreaterThan(0.05);
    expect(decision.metricSummary.holdout_confidence_lower).toBeGreaterThan(0.05);
  });

  it("applies Bonferroni correction for a Candidate family", () => {
    const decision = decide(buildFixture({ familySize: 100 }));
    expect(decision.decision).toBe("REJECTED");
    expect(decision.reasons).toContain("validation_multiple_comparison");
    expect(decision.reasons).toContain("holdout_multiple_comparison");
  });

  it("keeps block-bootstrap evidence invariant to persisted run ordering", () => {
    const original = buildFixture({
      validationDeltas: [0.3, -0.1, 0.2, 0.1],
      holdoutDeltas: [0.2, -0.05, 0.15, 0.1],
      policyOverrides: {
        criticalValidationSampleIds: [],
        criticalHoldoutSampleIds: [],
      },
    });
    const originalDecision = decide(original);
    const reorderedDecision = decide({ ...original, runs: [...original.runs].reverse() });
    expect(reorderedDecision.decision).toBe(originalDecision.decision);
    expect(reorderedDecision.metricSummary).toEqual(originalDecision.metricSummary);
    expect(reorderedDecision.evidenceHash).toBe(originalDecision.evidenceHash);
  });

  it("enforces minimum mature samples and repeated seeds on both partitions", () => {
    const decision = decide(
      buildFixture({
        policyOverrides: { minimumMatureSamples: 31, minimumRepeatSeeds: 3 },
      }),
    );
    expect(decision.decision).toBe("REJECTED");
    expect(decision.reasons).toEqual(
      expect.arrayContaining([
        "validation_sample_count",
        "validation_repeat_seed_count",
        "holdout_sample_count",
        "holdout_repeat_seed_count",
      ]),
    );
  });

  it("rejects average improvement that hides tail or critical-suite regression", () => {
    const decision = decide(
      buildFixture({
        validationDeltas: [0.2, 0.3, 0.3, -0.2],
        holdoutDeltas: [-0.2, 0.3, 0.3, 0.3],
      }),
    );
    expect(decision.decision).toBe("REJECTED");
    expect(decision.reasons).toContain("validation_tail_regression");
    expect(decision.reasons).toContain("holdout_tail_regression");
    expect(decision.reasons).toContain("holdout_critical_suite_regression");
  });

  it("rejects schema, contract, or tool failure-rate regression", () => {
    const decision = decide(buildFixture({ candidateFailure: true }));
    expect(decision.decision).toBe("REJECTED");
    expect(decision.reasons).toContain("validation_failure_rate_regression");
  });

  it("binds China to its own outcome and rejects CIO evaluator attribution", () => {
    const binding = promptEvaluationBinding(target);
    expect(binding.evaluationObject).toBe("AcceptedMacroTransmission");
    expect(binding.primaryLabelId).toBe("china_macro_transmission_a_share_path_5d");
    expect(binding.primaryLabelId).not.toBe(OUTCOME_LABEL_REGISTRY.cio?.primary_label_id);

    const fixture = buildFixture();
    const cioEvaluator = OUTCOME_LABEL_REGISTRY.cio?.scoring_contract_version;
    if (!cioEvaluator) throw new Error("missing CIO evaluator fixture");
    const driftedExperimentBody = {
      ...fixture.experiment,
      evaluatorVersion: cioEvaluator,
      runIds: [],
    };
    const driftedExperimentId = promptExperimentId(driftedExperimentBody);
    const driftedRuns = fixture.runs.map((run) => {
      const coordinates = { ...run, experimentId: driftedExperimentId };
      return { ...coordinates, runId: promptExperimentRunId(coordinates) };
    });
    const driftedExperiment = PromptExperimentSchema.parse({
      ...driftedExperimentBody,
      experimentId: driftedExperimentId,
      runIds: driftedRuns.map((run) => run.runId).sort(),
    });
    expect(() =>
      decide({
        ...fixture,
        experiment: driftedExperiment,
        runs: driftedRuns,
      }),
    ).toThrow("prompt_promotion_agent_evaluator_drift");
  });

  it("reopens the persisted Candidate and rejects release-time Prompt rebinding", async () => {
    const fixture = buildFixture();
    const decision = decide(fixture);
    const mutationCategories = ["CONFLICT_RESOLUTION"] as const;
    const candidate = PromptCandidateSchema.parse({
      schemaVersion: "prompt_candidate_v1",
      candidateId: fixture.experiment.candidateId,
      parentId: fixture.experiment.championId,
      parentPromptCommit: fixture.experiment.championPromptCommit,
      parentPromptHashes: fixture.experiment.championPromptHashes,
      target,
      promptRefs: fixture.experiment.candidatePromptRefs,
      promptHashes: fixture.experiment.candidatePromptHashes,
      trainingProjectionHash: fixture.split.trainingProjectionHash,
      excludedSampleIdsHash: canonicalJsonHash(
        [...fixture.split.validation.samples, ...fixture.split.holdout.samples]
          .map((sample) => sample.sampleId)
          .sort(),
      ),
      mutatorConfigHash: HASH_A,
      mutatorCommit: COMMIT,
      mutationCategories,
      mutationSummary: promptMutationSummary(mutationCategories),
      hypothesis: promptMutationHypothesis(mutationCategories),
      behaviorContractHash: HASH_A,
      privateLineageHash: HASH_A,
      privateStateArtifactHash: HASH_A,
      createdAt: "2025-04-01T00:00:00Z",
    });
    const api = {
      promptOptimizerGetCandidate: async () => candidate,
      promptOptimizerGetExperiment: async () => fixture.experiment,
      promptOptimizerGetFamily: async () => fixture.family,
      promptOptimizerGetSplit: async () => fixture.split,
      promptOptimizerListExperiments: async () => [fixture.experiment],
      promptOptimizerListRuns: async () => fixture.runs,
    } as unknown as BridgeApi;
    await expect(
      authorizeStoredPromptPromotion({
        api,
        candidate,
        experimentId: fixture.experiment.experimentId,
        policy: fixture.promotionPolicy,
        authorizedPolicyHashes: new Set([decision.policyConfigHash]),
        decidedAt: decision.decidedAt,
      }),
    ).resolves.toEqual(decision);
    await expect(
      authorizeStoredPromptPromotion({
        api,
        candidate,
        experimentId: fixture.experiment.experimentId,
        policy: fixture.promotionPolicy,
        authorizedPolicyHashes: new Set(),
        decidedAt: decision.decidedAt,
      }),
    ).rejects.toThrow("prompt_promotion_policy_not_authorized");

    const reboundHashes = { zh: HASH_A, en: HASH_A };
    const rebound = PromptCandidateSchema.parse({
      ...candidate,
      promptHashes: reboundHashes,
    });
    await expect(
      authorizeStoredPromptPromotion({
        api,
        candidate: rebound,
        experimentId: fixture.experiment.experimentId,
        policy: fixture.promotionPolicy,
        authorizedPolicyHashes: new Set([decision.policyConfigHash]),
        decidedAt: decision.decidedAt,
      }),
    ).rejects.toThrow("prompt_promotion_authority_binding_mismatch");
  });
});

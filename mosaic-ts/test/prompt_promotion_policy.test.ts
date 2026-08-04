import { describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { OUTCOME_LABEL_REGISTRY } from "../src/autoresearch/outcome_registry.js";
import {
  DatasetSplitManifestSchema,
  type PromptExperimentRun,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
} from "../src/autoresearch/prompt_optimizer_contract.js";
import {
  createPromptPromotionDecision,
  type PromptPromotionPolicy,
  promptEvaluationBinding,
} from "../src/autoresearch/prompt_promotion_policy.js";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;
const COMMIT = "c".repeat(40);
const target = { agentId: "china", stage: "agent_run", cohort: "cohort_default" } as const;
const evaluatorVersion = OUTCOME_LABEL_REGISTRY.china?.scoring_contract_version;
if (!evaluatorVersion) throw new Error("missing china outcome fixture");

function sample(sampleId: string, month: string) {
  return {
    sampleId,
    inputRef: `snapshot://${sampleId}`,
    outcomeRef: `outcome://${sampleId}`,
    eventWindow: {
      startAt: `2025-${month}-05T00:00:00Z`,
      endAt: `2025-${month}-06T00:00:00Z`,
    },
    maturedAt: `2025-${month}-10T00:00:00Z`,
  };
}

function buildFixture(
  options: {
    validationDeltas?: ReadonlyArray<number>;
    holdoutDeltas?: ReadonlyArray<number>;
    candidateFailure?: boolean;
  } = {},
) {
  const validationDeltas = options.validationDeltas ?? [0.2, 0.2, 0.2, 0.2];
  const holdoutDeltas = options.holdoutDeltas ?? [0.2, 0.2, 0.2, 0.2];
  const split = DatasetSplitManifestSchema.parse({
    schemaVersion: "prompt_dataset_split_v1",
    splitId: "split-promotion",
    target,
    cutoffAt: "2025-01-31T00:00:00Z",
    training: {
      snapshotId: "training-promotion",
      snapshotHash: HASH_A,
      windowStartAt: "2025-01-01T00:00:00Z",
      windowEndAt: "2025-01-31T00:00:00Z",
      samples: [sample("train-1", "01")],
    },
    validation: {
      snapshotId: "validation-promotion",
      snapshotHash: HASH_B,
      windowStartAt: "2025-02-01T00:00:00Z",
      windowEndAt: "2025-02-28T00:00:00Z",
      samples: validationDeltas.map((_, index) => sample(`validation-${index + 1}`, "02")),
    },
    holdout: {
      snapshotId: "holdout-promotion",
      snapshotHash: HASH_A,
      windowStartAt: "2025-03-01T00:00:00Z",
      windowEndAt: "2025-03-31T00:00:00Z",
      samples: holdoutDeltas.map((_, index) => sample(`holdout-${index + 1}`, "03")),
    },
    evaluatorVersion,
    createdAt: "2025-04-01T00:00:00Z",
  });
  const runs: PromptExperimentRun[] = [];
  for (const [partition, deltas] of [
    ["VALIDATION", validationDeltas],
    ["HOLDOUT", holdoutDeltas],
  ] as const) {
    for (const [index, delta] of deltas.entries()) {
      const sampleId = `${partition.toLowerCase()}-${index + 1}`;
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
              runId: `run-${partition}-${index}-${seed}-${side}`,
              experimentId: "experiment-promotion",
              partition,
              side,
              sampleId,
              seed,
              status: "COMPLETE",
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
    schemaVersion: "prompt_experiment_v1",
    experimentId: "experiment-promotion",
    candidateId: "candidate-promotion",
    championId: "champion-promotion",
    target,
    championPromptHashes: { zh: HASH_A, en: HASH_A },
    candidatePromptHashes: { zh: HASH_B, en: HASH_B },
    datasetSplitManifestHash: canonicalJsonHash(split),
    validationSnapshotHash: split.validation.snapshotHash,
    holdoutSnapshotHash: split.holdout.snapshotHash,
    modelConfigHash: HASH_A,
    toolConfigHash: HASH_A,
    evaluatorVersion,
    evaluatorConfigHash: HASH_B,
    codeCommit: COMMIT,
    repeatSeeds: [1, 2],
    runIds: runs.map((run) => run.runId).sort(),
    metrics: {},
    tailFailureCaseRefs: [],
    status: "COMPLETE",
    holdoutOpenedAt: "2025-04-01T00:00:00Z",
    createdAt: "2025-04-01T00:00:00Z",
    completedAt: "2025-04-01T01:00:00Z",
  });
  return { split, runs, experiment };
}

function policy(overrides: Partial<PromptPromotionPolicy> = {}): PromptPromotionPolicy {
  return {
    policyVersion: "prompt-promotion-test-v1",
    minimumMatureSamples: 4,
    minimumRepeatSeeds: 2,
    minimumPairedDelta: 0.05,
    familyAlpha: 0.05,
    candidateFamilySize: 1,
    bootstrapSamples: 999,
    blockLength: 1,
    tailQuantile: 0.25,
    minimumTailDelta: 0.05,
    maximumFailureRateIncrease: 0,
    criticalValidationSampleIds: ["validation-1"],
    criticalHoldoutSampleIds: ["holdout-1"],
    minimumCriticalSampleDelta: 0,
    ...overrides,
  };
}

function decide(
  fixture: ReturnType<typeof buildFixture>,
  promotionPolicy: PromptPromotionPolicy = policy(),
) {
  return createPromptPromotionDecision({
    ...fixture,
    policy: promotionPolicy,
    decidedAt: "2025-04-01T02:00:00Z",
  });
}

describe("Agent-specific Prompt promotion policy", () => {
  it("accepts only after validation and holdout pass every statistical guard", () => {
    const decision = decide(buildFixture());
    expect(decision.decision).toBe("ELIGIBLE");
    expect(decision.reasons).toEqual(["all_promotion_gates_passed"]);
    expect(decision.metricSummary.validation_confidence_lower).toBeGreaterThan(0.05);
    expect(decision.metricSummary.holdout_confidence_lower).toBeGreaterThan(0.05);
  });

  it("applies Bonferroni correction for a Candidate family", () => {
    const decision = decide(buildFixture(), policy({ candidateFamilySize: 100 }));
    expect(decision.decision).toBe("REJECTED");
    expect(decision.reasons).toContain("validation_multiple_comparison");
    expect(decision.reasons).toContain("holdout_multiple_comparison");
  });

  it("enforces minimum mature samples and repeated seeds on both partitions", () => {
    const decision = decide(
      buildFixture(),
      policy({ minimumMatureSamples: 5, minimumRepeatSeeds: 3 }),
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
    const driftedSplit = { ...fixture.split, evaluatorVersion: cioEvaluator };
    expect(() =>
      decide({
        ...fixture,
        split: driftedSplit,
        experiment: {
          ...fixture.experiment,
          evaluatorVersion: cioEvaluator,
          datasetSplitManifestHash: canonicalJsonHash(driftedSplit),
        },
      }),
    ).toThrow("prompt_promotion_agent_evaluator_drift");
  });
});

import { describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { OUTCOME_LABEL_REGISTRY } from "../src/autoresearch/outcome_registry.js";
import {
  type PromptExperimentAgentExecutor,
  type PromptExperimentEvaluator,
  type PromptExperimentRepository,
  runPromptExperimentPartition,
} from "../src/autoresearch/prompt_experiment_runner.js";
import {
  DatasetSplitManifestSchema,
  type PromptCandidate,
  PromptCandidateSchema,
  type PromptExperiment,
  type PromptExperimentRun,
  PromptExperimentSchema,
} from "../src/autoresearch/prompt_optimizer_contract.js";
import { createPromptPromotionDecision } from "../src/autoresearch/prompt_promotion_policy.js";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;
const HASH_C = `sha256:${"c".repeat(64)}`;
const COMMIT = "d".repeat(40);
const NOW = "2025-05-01T00:00:00Z";
const target = { agentId: "china", stage: "agent_run", cohort: "cohort_default" } as const;
const evaluatorVersion = (() => {
  const value = OUTCOME_LABEL_REGISTRY.china?.scoring_contract_version;
  if (!value) throw new Error("missing china outcome fixture");
  return value;
})();

function sample(sampleId: string, startAt: string, endAt: string, maturedAt: string) {
  return {
    sampleId,
    inputRef: `snapshot://${sampleId}`,
    outcomeRef: `outcome://${sampleId}`,
    eventWindow: { startAt, endAt },
    maturedAt,
  };
}

function fixtures(experimentId = "experiment-1") {
  const split = DatasetSplitManifestSchema.parse({
    schemaVersion: "prompt_dataset_split_v1",
    splitId: "split-1",
    target,
    cutoffAt: "2025-01-31T00:00:00Z",
    training: {
      snapshotId: "training-1",
      snapshotHash: HASH_A,
      windowStartAt: "2025-01-01T00:00:00Z",
      windowEndAt: "2025-01-31T00:00:00Z",
      samples: [
        sample("train-1", "2025-01-10T00:00:00Z", "2025-01-11T00:00:00Z", "2025-01-20T00:00:00Z"),
      ],
    },
    validation: {
      snapshotId: "validation-1",
      snapshotHash: HASH_B,
      windowStartAt: "2025-02-01T00:00:00Z",
      windowEndAt: "2025-02-28T00:00:00Z",
      samples: [
        sample(
          "validation-1",
          "2025-02-05T00:00:00Z",
          "2025-02-06T00:00:00Z",
          "2025-02-10T00:00:00Z",
        ),
        sample(
          "validation-2",
          "2025-02-15T00:00:00Z",
          "2025-02-16T00:00:00Z",
          "2025-02-20T00:00:00Z",
        ),
      ],
    },
    holdout: {
      snapshotId: "holdout-1",
      snapshotHash: HASH_C,
      windowStartAt: "2025-03-01T00:00:00Z",
      windowEndAt: "2025-03-31T00:00:00Z",
      samples: [
        sample("holdout-1", "2025-03-10T00:00:00Z", "2025-03-11T00:00:00Z", "2025-03-20T00:00:00Z"),
      ],
    },
    evaluatorVersion,
    createdAt: "2025-04-01T00:00:00Z",
  });
  const candidate = PromptCandidateSchema.parse({
    schemaVersion: "prompt_candidate_v1",
    candidateId: "candidate-1",
    parentId: "champion-1",
    target,
    promptRefs: { zh: "private://candidate.zh", en: "private://candidate.en" },
    promptHashes: { zh: HASH_B, en: HASH_C },
    trainingSnapshotId: split.training.snapshotId,
    trainingSnapshotHash: split.training.snapshotHash,
    mutatorConfigHash: HASH_A,
    mutatorCommit: COMMIT,
    mutationSummary: "Checks counter-evidence before forming the conclusion.",
    hypothesis: "Counter-evidence ordering improves the Agent-specific score.",
    createdAt: "2025-04-01T00:00:00Z",
  });
  const experiment = PromptExperimentSchema.parse({
    schemaVersion: "prompt_experiment_v1",
    experimentId,
    candidateId: candidate.candidateId,
    championId: candidate.parentId,
    target,
    championPromptHashes: { zh: HASH_A, en: HASH_A },
    candidatePromptHashes: candidate.promptHashes,
    datasetSplitManifestHash: canonicalJsonHash(split),
    validationSnapshotHash: split.validation.snapshotHash,
    holdoutSnapshotHash: split.holdout.snapshotHash,
    modelConfigHash: HASH_A,
    toolConfigHash: HASH_B,
    evaluatorVersion: split.evaluatorVersion,
    evaluatorConfigHash: HASH_C,
    codeCommit: COMMIT,
    repeatSeeds: [1, 2],
    runIds: [],
    metrics: {},
    tailFailureCaseRefs: [],
    status: "PENDING",
    holdoutOpenedAt: null,
    createdAt: "2025-04-01T00:00:00Z",
    completedAt: null,
  });
  return { split, candidate, experiment };
}

class MemoryRepository implements PromptExperimentRepository {
  candidate: PromptCandidate | null = null;
  experiment: PromptExperiment | null = null;
  runs = new Map<string, PromptExperimentRun>();
  writeCount = 0;

  async putCandidate(record: PromptCandidate) {
    this.writeCount += 1;
    this.candidate = structuredClone(record);
    return structuredClone(record);
  }

  async getExperiment(experimentId: string) {
    return this.experiment?.experimentId === experimentId ? structuredClone(this.experiment) : null;
  }

  async putExperiment(record: PromptExperiment) {
    this.writeCount += 1;
    this.experiment = structuredClone(record);
    return structuredClone(record);
  }

  async listRuns(experimentId: string) {
    return [...this.runs.values()]
      .filter((run) => run.experimentId === experimentId)
      .map((run) => structuredClone(run));
  }

  async putRun(record: PromptExperimentRun) {
    this.writeCount += 1;
    this.runs.set(record.runId, structuredClone(record));
    return structuredClone(record);
  }
}

function environment() {
  return {
    modelConfigHash: HASH_A,
    toolConfigHash: HASH_B,
    evaluatorVersion,
    evaluatorConfigHash: HASH_C,
    codeCommit: COMMIT,
  };
}

function binding() {
  return {
    champion: {
      promptRefs: { zh: "private://champion.zh", en: "private://champion.en" },
      promptHashes: { zh: HASH_A, en: HASH_A },
    },
    candidate: {
      promptRefs: { zh: "private://candidate.zh", en: "private://candidate.en" },
      promptHashes: { zh: HASH_B, en: HASH_C },
    },
  };
}

function adapters(options: { failOnce?: boolean } = {}) {
  const calls = new Map<string, number>();
  const evaluatorInputs: unknown[] = [];
  let shouldFail = options.failOnce ?? false;
  const executor: PromptExperimentAgentExecutor = {
    async execute(input) {
      const side = input.promptRefs.zh.includes("candidate") ? "candidate" : "champion";
      const key = `${input.partition}:${input.sample.sampleId}:${input.seed}:${side}`;
      calls.set(key, (calls.get(key) ?? 0) + 1);
      if (shouldFail && side === "candidate") {
        shouldFail = false;
        throw new Error("transient_adapter_failure");
      }
      return {
        acceptedOutputRef: `accepted://${key}`,
        effectiveInputHash: canonicalJsonHash({ key }),
      };
    },
  };
  const evaluator: PromptExperimentEvaluator = {
    async evaluate(input) {
      evaluatorInputs.push(structuredClone(input));
      const candidate = input.acceptedOutputRef.endsWith(":candidate");
      return {
        normalizedScore: candidate ? 0.7 : 0.5,
        metrics: { contract_failure: 0, tool_failure: 0 },
        failureCaseRefs: candidate ? [] : [`failure://${input.sample.sampleId}`],
      };
    },
  };
  return { calls, evaluatorInputs, executor, evaluator };
}

async function runBoth(maxConcurrency: number, experimentId: string) {
  const values = fixtures(experimentId);
  const repository = new MemoryRepository();
  const adapter = adapters();
  const common = {
    ...values,
    environment: environment(),
    promptBinding: binding(),
    repository,
    executor: adapter.executor,
    evaluator: adapter.evaluator,
    maxConcurrency,
    now: () => NOW,
  };
  await runPromptExperimentPartition({ ...common, partition: "VALIDATION" });
  const complete = await runPromptExperimentPartition({ ...common, partition: "HOLDOUT" });
  return { complete, repository, adapter, common };
}

describe("frozen Prompt experiment runner", () => {
  it("runs a Candidate through paired shadow evaluation and an eligible Decision", async () => {
    const { complete, repository, adapter, common } = await runBoth(3, "experiment-success");
    expect(complete.status).toBe("COMPLETE");
    expect(repository.runs.size).toBe(12);
    expect(complete.metrics.validation_paired_delta).toBeCloseTo(0.2);
    expect(complete.metrics.holdout_paired_delta).toBeCloseTo(0.2);
    expect(adapter.evaluatorInputs).toHaveLength(12);
    for (const input of adapter.evaluatorInputs) {
      expect(Object.keys(input as object).sort()).toEqual([
        "acceptedOutputRef",
        "sample",
        "target",
      ]);
    }
    const decision = createPromptPromotionDecision({
      experiment: complete,
      split: common.split,
      runs: [...repository.runs.values()],
      policy: {
        policyVersion: "shadow-smoke-v1",
        minimumMatureSamples: 1,
        minimumRepeatSeeds: 2,
        minimumPairedDelta: 0.05,
        familyAlpha: 0.05,
        candidateFamilySize: 1,
        bootstrapSamples: 99,
        blockLength: 1,
        tailQuantile: 0.25,
        minimumTailDelta: 0.05,
        maximumFailureRateIncrease: 0,
        criticalValidationSampleIds: ["validation-1"],
        criticalHoldoutSampleIds: ["holdout-1"],
        minimumCriticalSampleDelta: 0,
      },
      decidedAt: NOW,
    });
    expect(decision.decision).toBe("ELIGIBLE");
    expect(decision.candidateId).toBe(common.candidate.candidateId);
    const before = [...adapter.calls.values()].reduce((sum, count) => sum + count, 0);
    await runPromptExperimentPartition({ ...common, partition: "HOLDOUT" });
    expect([...adapter.calls.values()].reduce((sum, count) => sum + count, 0)).toBe(before);
  });

  it("resumes a failed run without repeating completed run IDs", async () => {
    const values = fixtures("experiment-resume");
    const repository = new MemoryRepository();
    const adapter = adapters({ failOnce: true });
    const input = {
      ...values,
      partition: "VALIDATION" as const,
      environment: environment(),
      promptBinding: binding(),
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      maxConcurrency: 1,
      now: () => NOW,
    };
    await expect(runPromptExperimentPartition(input)).rejects.toThrow("transient_adapter_failure");
    expect([...repository.runs.values()].some((run) => run.status === "FAILED")).toBe(true);
    const completedBefore = new Map(
      [...adapter.calls].filter(([key]) => key !== "VALIDATION:validation-1:1:candidate"),
    );
    const resumed = await runPromptExperimentPartition(input);
    expect(resumed.status).toBe("VALIDATION_COMPLETE");
    for (const [key, count] of completedBefore) expect(adapter.calls.get(key)).toBe(count);
    expect(adapter.calls.get("VALIDATION:validation-1:1:candidate")).toBe(2);
  });

  it("rejects frozen-environment drift before any persistence or execution", async () => {
    const values = fixtures("experiment-drift");
    const repository = new MemoryRepository();
    const adapter = adapters();
    await expect(
      runPromptExperimentPartition({
        ...values,
        partition: "VALIDATION",
        environment: { ...environment(), toolConfigHash: HASH_C },
        promptBinding: binding(),
        repository,
        executor: adapter.executor,
        evaluator: adapter.evaluator,
      }),
    ).rejects.toThrow("prompt_experiment_environment_drift:toolConfigHash");
    expect(repository.writeCount).toBe(0);
    expect(adapter.calls.size).toBe(0);
  });

  it("produces identical aggregate metrics under serial and concurrent execution", async () => {
    const serial = await runBoth(1, "experiment-serial");
    const concurrent = await runBoth(4, "experiment-concurrent");
    expect(canonicalJsonHash(serial.complete.metrics)).toBe(
      canonicalJsonHash(concurrent.complete.metrics),
    );
    expect(serial.complete.tailFailureCaseRefs).toEqual(concurrent.complete.tailFailureCaseRefs);
  });
});

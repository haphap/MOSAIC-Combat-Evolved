import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { OUTCOME_LABEL_REGISTRY } from "../src/autoresearch/outcome_registry.js";
import { selectPromptCandidateFamily } from "../src/autoresearch/prompt_candidate_family.js";
import {
  type PromptExperimentAgentExecutor,
  type PromptExperimentEvaluator,
  type PromptExperimentRepository,
  PromptExperimentScoredFailure,
  PromptExperimentTransientInfrastructureError,
  runPromptExperimentPartition,
} from "../src/autoresearch/prompt_experiment_runner.js";
import {
  DatasetSplitManifestSchema,
  PROMPT_EXPERIMENT_MAX_ATTEMPTS,
  type PromptCandidate,
  type PromptCandidateFamily,
  PromptCandidateFamilySchema,
  PromptCandidateSchema,
  type PromptExperiment,
  type PromptExperimentRun,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
  PromptTrainingProjectionSchema,
  promptCandidateFamilyId,
  promptDatasetPartitionSnapshotHash,
  promptDatasetSampleId,
  promptDatasetSplitId,
  promptExperimentId,
  promptMutationHypothesis,
  promptMutationSummary,
} from "../src/autoresearch/prompt_optimizer_contract.js";
import { runPromptOptimizerShadowPlan } from "../src/autoresearch/prompt_optimizer_shadow_runner.js";
import { createPromptPromotionDecision } from "../src/autoresearch/prompt_promotion_policy.js";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;
const HASH_C = `sha256:${"c".repeat(64)}`;
const COMMIT = "d".repeat(40);
const NOW = "2025-05-01T00:00:00Z";
const target = { agentId: "china", stage: "agent_run", cohort: "cohort_default" } as const;
const semiconductorTarget = {
  agentId: "semiconductor",
  stage: "agent_run",
  cohort: "cohort_default",
} as const;
type TestTarget = typeof target | typeof semiconductorTarget;

const PRIVATE_HANDOFF_CASES = [
  { caseId: "china-direct-001", target },
  { caseId: "china-direct-002", target },
  { caseId: "china-direct-003", target },
  { caseId: "semiconductor-direct-001", target: semiconductorTarget },
] as const;

interface PromptCandidateHandoffCase {
  caseId: string;
  trainingProjection: unknown;
  candidate: unknown;
}

const PRIVATE_HANDOFF_FIXTURE = (() => {
  const fixture = JSON.parse(
    readFileSync(
      join(import.meta.dirname, "fixtures/private_prompt_candidate_handoff_v1.json"),
      "utf8",
    ),
  ) as {
    schemaVersion: string;
    cases: PromptCandidateHandoffCase[];
  };
  if (fixture.schemaVersion !== "public_prompt_candidate_handoff_fixture_v1") {
    throw new Error("private Prompt Candidate handoff fixture is invalid");
  }
  const expectedCaseIds = PRIVATE_HANDOFF_CASES.map((value) => value.caseId).sort();
  const actualCaseIds = fixture.cases.map((value) => value.caseId).sort();
  if (JSON.stringify(actualCaseIds) !== JSON.stringify(expectedCaseIds)) {
    throw new Error("private Prompt Candidate handoff fixture cases are invalid");
  }
  return fixture;
})();

function promptCandidateHandoffCase(caseId: string): PromptCandidateHandoffCase {
  const value = PRIVATE_HANDOFF_FIXTURE.cases.find((entry) => entry.caseId === caseId);
  if (!value || Object.keys(value).sort().join(",") !== "candidate,caseId,trainingProjection") {
    throw new Error(`private Prompt Candidate handoff case is invalid: ${caseId}`);
  }
  return value;
}

function evaluatorVersionFor(requestedTarget: TestTarget): string {
  const value = OUTCOME_LABEL_REGISTRY[requestedTarget.agentId]?.scoring_contract_version;
  if (!value) throw new Error(`missing ${requestedTarget.agentId} outcome fixture`);
  return value;
}

const evaluatorVersion = evaluatorVersionFor(target);

function sample(sampleId: string, startAt: string, endAt: string, maturedAt: string) {
  const value = {
    inputRef: `snapshot://${sampleId}`,
    inputHash: HASH_A,
    outcomeRef: `outcome://${sampleId}`,
    outcomeHash: HASH_B,
    eventWindow: { startAt, endAt },
    maturedAt,
  };
  return { ...value, sampleId: promptDatasetSampleId(value) };
}

function partitionSamples(prefix: "validation" | "holdout", month: "02" | "03") {
  return Array.from({ length: 30 }, (_, index) => {
    const ordinal = index + 1;
    const day = String(Math.floor(index / 12) + 5).padStart(2, "0");
    const startHour = String((index % 12) * 2).padStart(2, "0");
    const endHour = String((index % 12) * 2 + 1).padStart(2, "0");
    return sample(
      `${prefix}-${ordinal}`,
      `2025-${month}-${day}T${startHour}:00:00Z`,
      `2025-${month}-${day}T${endHour}:00:00Z`,
      `2025-${month}-20T00:00:00Z`,
    );
  });
}

function fixtures(
  candidateSuffix = "1",
  requestedTarget: TestTarget = target,
  handoff?: Pick<PromptCandidateHandoffCase, "trainingProjection" | "candidate">,
) {
  const requestedEvaluatorVersion = evaluatorVersionFor(requestedTarget);
  const contract = OUTCOME_LABEL_REGISTRY[requestedTarget.agentId];
  if (!contract) throw new Error("missing training projection fixture contract");
  const validationSamples = partitionSamples("validation", "02");
  const holdoutSamples = partitionSamples("holdout", "03");
  const excludedSampleIdsHash = canonicalJsonHash(
    [...validationSamples, ...holdoutSamples].map((value) => value.sampleId).sort(),
  );
  const maturityTradingDays =
    contract.maturity_horizon === "T1_CLOSE"
      ? 1
      : Number(contract.maturity_horizon.replace("TRADING_DAYS_", ""));
  const trainingProjectionBody = {
    schemaVersion: "prompt_training_projection_v1" as const,
    target: requestedTarget,
    projectionId: `projection-${requestedTarget.agentId}`,
    datasetSnapshotHash: HASH_A,
    excludedSampleIdsHash,
    cutoffAt: "2025-01-31T00:00:00Z",
    outcomeContract: {
      evaluationObject: contract.evaluation_object,
      outcomeContractVersion: contract.outcome_contract_version,
      primaryLabelId: contract.primary_label_id,
      maturityHorizon: contract.maturity_horizon,
      maturityTradingDays,
    },
    evaluator: {
      version: contract.scoring_contract_version,
      configHash: HASH_A,
      implementationHash: HASH_B,
      executorAdapterHash: HASH_A,
      evaluatorAdapterHash: HASH_A,
    },
    matureSampleCount: 30,
    scoreSummary: { mean: 0.1, lower_tail: 0.05 },
    failureCategoryCounts: {},
    tailFailureCaseRefs: [],
    evidenceGapSummaries: [],
    directComponents: [
      {
        componentRef: `role_component_v1:${requestedTarget.agentId}:001`,
        directMatureSampleCount: 30,
        meanScore: 0.1,
        lowerTailScore: 0.05,
        failureCategoryCounts: {},
      },
    ],
    controlledExperiments: [],
  };
  const trainingProjection = handoff
    ? PromptTrainingProjectionSchema.parse(handoff.trainingProjection)
    : PromptTrainingProjectionSchema.parse({
        ...trainingProjectionBody,
        projectionHash: canonicalJsonHash(trainingProjectionBody),
      });
  if (JSON.stringify(trainingProjection.target) !== JSON.stringify(requestedTarget)) {
    throw new Error("handoff training projection target mismatch");
  }
  const trainingSamples = [
    sample("train-1", "2025-01-10T00:00:00Z", "2025-01-11T00:00:00Z", "2025-01-20T00:00:00Z"),
  ];
  const splitBody = {
    schemaVersion: "prompt_dataset_split_v1",
    target: requestedTarget,
    trainingProjectionHash: trainingProjection.projectionHash,
    cutoffAt: trainingProjection.cutoffAt,
    training: {
      snapshotHash: promptDatasetPartitionSnapshotHash({ samples: trainingSamples }),
      windowStartAt: "2025-01-01T00:00:00Z",
      windowEndAt: trainingProjection.cutoffAt,
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
    evaluatorVersion: requestedEvaluatorVersion,
    createdAt: "2025-04-01T00:00:00Z",
  };
  const split = DatasetSplitManifestSchema.parse({
    ...splitBody,
    splitId: promptDatasetSplitId(splitBody),
  });
  const candidate = handoff
    ? PromptCandidateSchema.parse(handoff.candidate)
    : PromptCandidateSchema.parse({
        schemaVersion: "prompt_candidate_v1",
        candidateId: `candidate-${candidateSuffix}`,
        parentId: "champion-1",
        parentPromptCommit: COMMIT,
        parentPromptHashes: { zh: HASH_A, en: HASH_A },
        target: requestedTarget,
        promptRefs: { zh: "private://candidate.zh", en: "private://candidate.en" },
        promptHashes: { zh: HASH_B, en: HASH_C },
        trainingProjectionHash: split.trainingProjectionHash,
        excludedSampleIdsHash,
        mutatorConfigHash: HASH_A,
        mutatorCommit: COMMIT,
        mutationCategories: ["CONFLICT_RESOLUTION"],
        mutationSummary: promptMutationSummary(["CONFLICT_RESOLUTION"]),
        hypothesis: promptMutationHypothesis(["CONFLICT_RESOLUTION"]),
        behaviorContractHash: HASH_A,
        privateLineageHash: HASH_A,
        privateStateArtifactHash: HASH_A,
        createdAt: "2025-04-01T00:00:00Z",
      });
  if (JSON.stringify(candidate.target) !== JSON.stringify(requestedTarget)) {
    throw new Error("handoff Prompt Candidate target mismatch");
  }
  const policy = promotionPolicy(split);
  const familyBody = {
    schemaVersion: "prompt_candidate_family_v1",
    target: requestedTarget,
    championReleaseId: candidate.parentId,
    championPromptCommit: candidate.parentPromptCommit,
    championPromptRefs: { zh: "private://champion.zh", en: "private://champion.en" },
    championPromptHashes: candidate.parentPromptHashes,
    datasetSplitId: split.splitId,
    datasetSplitManifestHash: canonicalJsonHash(split),
    promotionPolicyVersion: policy.policyVersion,
    promotionPolicyConfigHash: canonicalJsonHash(policy),
    candidateIds: [candidate.candidateId],
    createdAt: "2025-04-01T00:00:00Z",
  };
  const family = PromptCandidateFamilySchema.parse({
    ...familyBody,
    familyId: promptCandidateFamilyId(familyBody),
  });
  const experimentBody = {
    schemaVersion: "prompt_experiment_v1",
    familyId: family.familyId,
    candidateId: candidate.candidateId,
    championId: candidate.parentId,
    target: requestedTarget,
    championPromptCommit: candidate.parentPromptCommit,
    championPromptRefs: family.championPromptRefs,
    championPromptHashes: candidate.parentPromptHashes,
    candidatePromptRefs: candidate.promptRefs,
    candidatePromptHashes: candidate.promptHashes,
    datasetSplitId: split.splitId,
    datasetSplitManifestHash: canonicalJsonHash(split),
    promotionPolicyVersion: policy.policyVersion,
    promotionPolicyConfigHash: canonicalJsonHash(policy),
    modelConfigHash: HASH_A,
    toolConfigHash: HASH_B,
    componentCalibrationSnapshotHash: HASH_C,
    darwinianUsageSnapshotHash: HASH_A,
    executorAdapterHash: HASH_A,
    evaluatorAdapterHash: HASH_A,
    evaluationBinding: (() => {
      const contract = OUTCOME_LABEL_REGISTRY[requestedTarget.agentId];
      if (!contract) throw new Error("missing evaluation binding fixture");
      return {
        evaluationObject: contract.evaluation_object,
        evaluationObjectSchemaVersion: contract.evaluation_object_schema_version,
        primaryLabelId: contract.primary_label_id,
        scoringContractVersion: contract.scoring_contract_version,
        outcomeContractVersion: contract.outcome_contract_version,
      };
    })(),
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
  };
  const experiment = PromptExperimentSchema.parse({
    ...experimentBody,
    experimentId: promptExperimentId(experimentBody),
  });
  return {
    trainingProjection,
    split,
    candidate,
    family,
    experiment,
    promotionPolicy: policy,
    authorizedPolicyHashes: new Set([canonicalJsonHash(policy)]),
    runOwnerId: "test-worker",
  };
}

class MemoryRepository implements PromptExperimentRepository {
  candidate: PromptCandidate | null = null;
  split = null as ReturnType<typeof DatasetSplitManifestSchema.parse> | null;
  family: PromptCandidateFamily | null = null;
  experiment: PromptExperiment | null = null;
  runs = new Map<string, PromptExperimentRun>();
  writeCount = 0;

  async putCandidate(record: PromptCandidate) {
    this.writeCount += 1;
    this.candidate = structuredClone(record);
    return structuredClone(record);
  }

  async putSplit(record: ReturnType<typeof DatasetSplitManifestSchema.parse>) {
    this.split = structuredClone(record);
    return structuredClone(record);
  }

  async putFamily(record: PromptCandidateFamily) {
    this.family = structuredClone(record);
    return structuredClone(record);
  }

  async getFamily(familyId: string) {
    return this.family?.familyId === familyId ? structuredClone(this.family) : null;
  }

  async getExperiment(experimentId: string) {
    return this.experiment?.experimentId === experimentId ? structuredClone(this.experiment) : null;
  }

  async listExperiments(familyId: string) {
    return this.experiment?.familyId === familyId ? [structuredClone(this.experiment)] : [];
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

  async claimRun(record: PromptExperimentRun, _leaseDurationMs: number) {
    const existing = this.runs.get(record.runId);
    if (existing?.status === "COMPLETE") return null;
    if (
      existing?.status === "RUNNING" &&
      Date.parse(existing.leaseExpiresAt ?? "") > Date.parse(record.startedAt ?? "")
    ) {
      return null;
    }
    if (
      existing?.status === "RUNNING" &&
      existing.attempt >= PROMPT_EXPERIMENT_MAX_ATTEMPTS &&
      record.attempt === existing.attempt
    ) {
      const errorCode = "prompt_experiment_lease_expired_max_attempts";
      this.runs.set(
        existing.runId,
        PromptExperimentRunSchema.parse({
          ...existing,
          status: "FAILED",
          retryable: false,
          attemptFailureCodes: [...existing.attemptFailureCodes, errorCode],
          errorCode,
          completedAt: record.startedAt,
        }),
      );
      return null;
    }
    if (existing?.status === "FAILED" && !existing.retryable) return null;
    this.runs.set(record.runId, structuredClone(record));
    return structuredClone(record);
  }
}

function environment(version = evaluatorVersion) {
  return {
    modelConfigHash: HASH_A,
    toolConfigHash: HASH_B,
    componentCalibrationSnapshotHash: HASH_C,
    darwinianUsageSnapshotHash: HASH_A,
    executorAdapterHash: HASH_A,
    evaluatorAdapterHash: HASH_A,
    evaluatorVersion: version,
    evaluatorConfigHash: HASH_C,
    codeCommit: COMMIT,
  };
}

function promotionPolicy(split: ReturnType<typeof DatasetSplitManifestSchema.parse>) {
  return {
    policyVersion: "shadow-plan-v1",
    minimumMatureSamples: 30,
    minimumRepeatSeeds: 2,
    minimumPairedDelta: 0.05,
    familyAlpha: 0.05,
    bootstrapSamples: 99,
    blockLength: 1,
    tailQuantile: 0.25,
    minimumTailDelta: 0.05,
    maximumFailureRateIncrease: 0,
    criticalValidationSampleIds: [split.validation.samples[0]?.sampleId ?? "missing"],
    criticalHoldoutSampleIds: [split.holdout.samples[0]?.sampleId ?? "missing"],
    minimumCriticalSampleDelta: 0,
  };
}

function adapters(
  options: {
    failOnce?: boolean;
    alwaysTransientFailure?: boolean;
    schemaFailure?: boolean;
    plainToolFailure?: boolean;
    invalidEffectiveInputHash?: boolean;
    evaluatorThrows?: boolean;
    invalidEvaluatorScore?: boolean;
    wrongPromptConsumption?: boolean;
    scoredFailureRefCount?: number;
    candidatePromptHashes?: PromptCandidate["promptHashes"];
  } = {},
) {
  const calls = new Map<string, number>();
  const executorInputs: unknown[] = [];
  const evaluatorInputs: unknown[] = [];
  let shouldFail = options.failOnce ?? false;
  const executor: PromptExperimentAgentExecutor = {
    async execute(input) {
      executorInputs.push(structuredClone(input));
      const side = options.candidatePromptHashes
        ? input.promptHashes.zh === options.candidatePromptHashes.zh &&
          input.promptHashes.en === options.candidatePromptHashes.en
          ? "candidate"
          : "champion"
        : input.promptRefs.zh.includes("candidate")
          ? "candidate"
          : "champion";
      const key = `${input.partition}:${input.sample.sampleId}:${input.seed}:${side}`;
      calls.set(key, (calls.get(key) ?? 0) + 1);
      if (options.alwaysTransientFailure || (shouldFail && side === "candidate")) {
        shouldFail = false;
        throw new PromptExperimentTransientInfrastructureError("transient_adapter_failure");
      }
      if (options.schemaFailure) {
        throw new PromptExperimentScoredFailure({
          failureCategory: "schema_failure",
          effectiveInputHash: canonicalJsonHash({ key }),
          failureCaseRefs: Array.from(
            { length: options.scoredFailureRefCount ?? 0 },
            (_, index) => `failure://adapter/${index.toString().padStart(3, "0")}`,
          ),
        });
      }
      if (options.plainToolFailure) throw new Error("deterministic_tool_failure");
      return {
        acceptedOutputRef: `accepted://${key}`,
        effectiveInputHash: options.invalidEffectiveInputHash
          ? "not-a-sha256"
          : canonicalJsonHash({ key }),
        consumedPromptHashes: options.wrongPromptConsumption
          ? { zh: HASH_C, en: HASH_C }
          : input.promptHashes,
      };
    },
  };
  const evaluator: PromptExperimentEvaluator = {
    async evaluate(input) {
      evaluatorInputs.push(structuredClone(input));
      if (options.evaluatorThrows) throw new Error("evaluator_contract_failure");
      const candidate = input.acceptedOutputRef.endsWith(":candidate");
      return {
        normalizedScore: options.invalidEvaluatorScore ? 2 : candidate ? 0.7 : 0.5,
        metrics: { contract_failure: 0, tool_failure: 0 },
        failureCaseRefs: candidate ? [] : [`failure://${input.sample.sampleId}`],
      };
    },
  };
  return { calls, executorInputs, evaluatorInputs, executor, evaluator };
}

async function runBoth(maxConcurrency: number, experimentId: string) {
  const values = fixtures(experimentId);
  const repository = new MemoryRepository();
  const adapter = adapters();
  const common = {
    ...values,
    environment: environment(),
    repository,
    executor: adapter.executor,
    evaluator: adapter.evaluator,
    maxConcurrency,
    runOwnerId: "test-worker",
    now: () => NOW,
  };
  await runPromptExperimentPartition({ ...common, partition: "VALIDATION" });
  const validation = repository.experiment;
  if (!validation) throw new Error("missing validation experiment");
  const selected = selectPromptCandidateFamily({
    family: values.family,
    validationExperiments: [validation],
    validationRuns: [
      {
        experimentId: validation.experimentId,
        runs: await repository.listRuns(validation.experimentId),
      },
    ],
    split: values.split,
    policy: values.promotionPolicy,
  });
  expect(selected.selectedExperimentId).toBe(validation.experimentId);
  const complete = await runPromptExperimentPartition({ ...common, partition: "HOLDOUT" });
  const family = await repository.getFamily(values.family.familyId);
  if (!family) throw new Error("missing completed family");
  return { complete, family, repository, adapter, common };
}

describe("frozen Prompt experiment runner", () => {
  it("runs the operational shadow plan through a recomputed Decision", async () => {
    const values = fixtures("experiment-shadow-plan");
    const repository = new MemoryRepository();
    const adapter = adapters();
    const plan = {
      schemaVersion: "prompt_optimizer_shadow_plan_v1" as const,
      trainingProjection: values.trainingProjection,
      family: values.family,
      split: values.split,
      candidates: [values.candidate],
      experiments: [values.experiment],
      environment: environment(),
      promotionPolicy: values.promotionPolicy,
      runOwnerId: "shadow-worker",
      leaseDurationMs: 300_000,
      maxConcurrency: 3,
    };
    const result = await runPromptOptimizerShadowPlan({
      plan,
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      authorizedPolicyHashes: values.authorizedPolicyHashes,
      now: () => NOW,
    });
    expect(result.family).toEqual(values.family);
    expect(result.decision.decision).toBe("ELIGIBLE");
    expect(result.decision.evidenceHash).toMatch(/^sha256:/);
    const calls = adapter.executorInputs.length;
    const replay = await runPromptOptimizerShadowPlan({
      plan,
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      authorizedPolicyHashes: values.authorizedPolicyHashes,
      now: () => NOW,
    });
    expect(replay.family).toEqual(values.family);
    expect(replay.decision.evidenceHash).toBe(result.decision.evidenceHash);
    expect(adapter.executorInputs).toHaveLength(calls);
  });

  it("rejects an unauthorized promotion policy before any shadow write or execution", async () => {
    const values = fixtures("experiment-unauthorized-policy");
    const repository = new MemoryRepository();
    const adapter = adapters();
    await expect(
      runPromptOptimizerShadowPlan({
        plan: {
          schemaVersion: "prompt_optimizer_shadow_plan_v1",
          trainingProjection: values.trainingProjection,
          family: values.family,
          split: values.split,
          candidates: [values.candidate],
          experiments: [values.experiment],
          environment: environment(),
          promotionPolicy: values.promotionPolicy,
          runOwnerId: "shadow-worker",
          leaseDurationMs: 300_000,
          maxConcurrency: 1,
        },
        repository,
        executor: adapter.executor,
        evaluator: adapter.evaluator,
        authorizedPolicyHashes: new Set(),
        now: () => NOW,
      }),
    ).rejects.toThrow("prompt_optimizer_shadow_policy_not_authorized");
    expect(repository.writeCount).toBe(0);
    expect(adapter.executorInputs).toHaveLength(0);
  });

  it.each(
    PRIVATE_HANDOFF_CASES,
  )("runs real private $caseId through the public paired shadow gate", async ({
    caseId,
    target: requestedTarget,
  }) => {
    const handoff = promptCandidateHandoffCase(caseId);
    const values = fixtures(`handoff-${caseId}`, requestedTarget, handoff);
    const repository = new MemoryRepository();
    const adapter = adapters({ candidatePromptHashes: values.candidate.promptHashes });
    const frozenEnvironment = environment(values.split.evaluatorVersion);
    const result = await runPromptOptimizerShadowPlan({
      plan: {
        schemaVersion: "prompt_optimizer_shadow_plan_v1",
        trainingProjection: values.trainingProjection,
        family: values.family,
        split: values.split,
        candidates: [values.candidate],
        experiments: [values.experiment],
        environment: frozenEnvironment,
        promotionPolicy: values.promotionPolicy,
        runOwnerId: `${caseId}-shadow-worker`,
        leaseDurationMs: 300_000,
        maxConcurrency: 4,
      },
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      authorizedPolicyHashes: values.authorizedPolicyHashes,
      now: () => NOW,
    });

    expect(repository.candidate).toEqual(values.candidate);
    expect(result.family.target).toEqual(requestedTarget);
    expect(result.family).toEqual(values.family);
    expect(result.decision).toMatchObject({
      candidateId: values.candidate.candidateId,
      decision: "ELIGIBLE",
    });
    expect(repository.runs.size).toBe(240);
    expect(
      adapter.executorInputs.every(
        (input) =>
          (input as { target: { agentId: string } }).target.agentId === requestedTarget.agentId,
      ),
    ).toBe(true);

    const candidateInputs = adapter.executorInputs.filter((input) => {
      const hashes = (input as { promptHashes: PromptCandidate["promptHashes"] }).promptHashes;
      return (
        hashes.zh === values.candidate.promptHashes.zh &&
        hashes.en === values.candidate.promptHashes.en
      );
    });
    expect(candidateInputs).toHaveLength(120);
    for (const input of candidateInputs) {
      expect(input).toMatchObject({
        promptRefs: values.candidate.promptRefs,
        promptHashes: values.candidate.promptHashes,
      });
    }
  });

  it("runs a Candidate through paired shadow evaluation and an eligible Decision", async () => {
    const { complete, family, repository, adapter, common } = await runBoth(
      3,
      "experiment-success",
    );
    expect(complete.status).toBe("COMPLETE");
    expect(repository.runs.size).toBe(240);
    expect(complete.metrics.validation_paired_delta).toBeCloseTo(0.2);
    expect(complete.metrics.holdout_paired_delta).toBeCloseTo(0.2);
    expect(adapter.executorInputs).toHaveLength(240);
    for (const input of adapter.executorInputs) {
      expect((input as { environment: unknown }).environment).toEqual(environment());
      const executorSample = (input as { sample: Record<string, unknown> }).sample;
      expect(Object.keys(executorSample).sort()).toEqual([
        "eventWindow",
        "inputHash",
        "inputRef",
        "sampleId",
      ]);
      expect(executorSample).not.toHaveProperty("outcomeRef");
      expect(executorSample).not.toHaveProperty("outcomeHash");
      expect(executorSample).not.toHaveProperty("maturedAt");
    }
    expect(adapter.evaluatorInputs).toHaveLength(240);
    for (const input of adapter.evaluatorInputs) {
      expect(Object.keys(input as object).sort()).toEqual([
        "acceptedOutputRef",
        "environment",
        "sample",
        "target",
      ]);
      expect((input as { environment: unknown }).environment).toEqual(environment());
      expect((input as { sample: Record<string, unknown> }).sample).toHaveProperty("outcomeHash");
    }
    const decision = createPromptPromotionDecision({
      experiment: complete,
      family,
      split: common.split,
      runs: [...repository.runs.values()],
      policy: common.promotionPolicy,
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
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      maxConcurrency: 1,
      now: () => NOW,
    };
    await expect(runPromptExperimentPartition(input)).rejects.toThrow("transient_adapter_failure");
    const failed = [...repository.runs.values()].find((run) => run.status === "FAILED");
    expect(failed?.retryable).toBe(true);
    if (!failed) throw new Error("missing failed run");
    const failedKey = `${failed.partition}:${failed.sampleId}:${failed.seed}:${failed.side.toLowerCase()}`;
    const completedBefore = new Map([...adapter.calls].filter(([key]) => key !== failedKey));
    const resumed = await runPromptExperimentPartition(input);
    expect(resumed.status).toBe("VALIDATION_COMPLETE");
    for (const [key, count] of completedBefore) expect(adapter.calls.get(key)).toBe(count);
    expect(adapter.calls.get(failedKey)).toBe(2);
    expect(repository.runs.get(failed.runId)?.attemptFailureCodes).toEqual([
      "transient_adapter_failure",
    ]);
  });

  it("bounds explicit transient retries at three attempts and then makes the run terminal", async () => {
    const values = fixtures("experiment-bounded-retry");
    const repository = new MemoryRepository();
    const adapter = adapters({ alwaysTransientFailure: true });
    const input = {
      ...values,
      partition: "VALIDATION" as const,
      environment: environment(),
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      maxConcurrency: 1,
      now: () => NOW,
    };
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      await expect(runPromptExperimentPartition(input)).rejects.toThrow(
        "transient_adapter_failure",
      );
      const failed = [...repository.runs.values()].find((run) => run.status === "FAILED");
      expect(failed?.attempt).toBe(attempt);
      expect(failed?.retryable).toBe(true);
      expect(failed?.attemptFailureCodes).toHaveLength(attempt);
    }
    await expect(runPromptExperimentPartition(input)).rejects.toThrow(
      "prompt_experiment_run_terminal",
    );
    const terminal = [...repository.runs.values()].find(
      (run) => run.status === "FAILED" && !run.retryable,
    );
    expect(terminal?.attempt).toBe(3);
    expect(terminal?.attemptFailureCodes).toHaveLength(3);
    expect(repository.experiment?.status).toBe("FAILED");
  });

  it("reclaims an expired RUNNING lease after a worker crash", async () => {
    class CrashAfterClaimRepository extends MemoryRepository {
      crashed = false;

      override async claimRun(record: PromptExperimentRun, leaseDurationMs: number) {
        const claimed = await super.claimRun(record, leaseDurationMs);
        if (claimed && !this.crashed) {
          this.crashed = true;
          throw new Error("simulated_worker_crash");
        }
        return claimed;
      }
    }
    const values = fixtures("experiment-expired-lease");
    const repository = new CrashAfterClaimRepository();
    const adapter = adapters();
    const input = {
      ...values,
      partition: "VALIDATION" as const,
      environment: environment(),
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      maxConcurrency: 1,
      leaseDurationMs: 60_000,
      now: () => NOW,
    };
    await expect(runPromptExperimentPartition(input)).rejects.toThrow("simulated_worker_crash");
    expect([...repository.runs.values()].some((run) => run.status === "RUNNING")).toBe(true);
    const resumed = await runPromptExperimentPartition({
      ...input,
      runOwnerId: "replacement-worker",
      now: () => "2025-05-01T00:02:00Z",
    });
    expect(resumed.status).toBe("VALIDATION_COMPLETE");
    expect(Math.max(...[...repository.runs.values()].map((run) => run.attempt))).toBe(2);
  });

  it("terminalizes an expired third-attempt lease and closes its Experiment", async () => {
    class CrashThreeClaimsRepository extends MemoryRepository {
      crashes = 0;

      override async claimRun(record: PromptExperimentRun, leaseDurationMs: number) {
        const claimed = await super.claimRun(record, leaseDurationMs);
        if (claimed && this.crashes < 3) {
          this.crashes += 1;
          throw new Error(`simulated_worker_crash_${this.crashes}`);
        }
        return claimed;
      }
    }
    const values = fixtures("experiment-expired-final-lease");
    const repository = new CrashThreeClaimsRepository();
    const adapter = adapters();
    const input = {
      ...values,
      partition: "VALIDATION" as const,
      environment: environment(),
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      maxConcurrency: 1,
      leaseDurationMs: 60_000,
    };
    for (const [index, now] of [
      "2025-05-01T00:00:00Z",
      "2025-05-01T00:02:00Z",
      "2025-05-01T00:04:00Z",
    ].entries()) {
      await expect(runPromptExperimentPartition({ ...input, now: () => now })).rejects.toThrow(
        `simulated_worker_crash_${index + 1}`,
      );
    }
    await expect(
      runPromptExperimentPartition({
        ...input,
        runOwnerId: "final-lease-recovery-worker",
        now: () => "2025-05-01T00:06:00Z",
      }),
    ).rejects.toThrow("prompt_experiment_run_terminal");
    const terminal = [...repository.runs.values()].find(
      (run) => run.errorCode === "prompt_experiment_lease_expired_max_attempts",
    );
    expect(terminal).toMatchObject({ status: "FAILED", attempt: 3, retryable: false });
    expect(repository.experiment?.status).toBe("FAILED");
  });

  it("scores an unconsumed Prompt as a terminal contract failure", async () => {
    const values = fixtures("experiment-unconsumed-prompt");
    const repository = new MemoryRepository();
    const adapter = adapters({ wrongPromptConsumption: true });
    const result = await runPromptExperimentPartition({
      ...values,
      partition: "VALIDATION",
      environment: environment(),
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      maxConcurrency: 1,
      now: () => NOW,
    });
    expect(result.status).toBe("VALIDATION_COMPLETE");
    expect(
      [...repository.runs.values()].every(
        (run) =>
          run.status === "COMPLETE" &&
          run.metrics.normalized_score === -1 &&
          run.metrics.contract_failure === 1 &&
          !run.retryable,
      ),
    ).toBe(true);
    expect(adapter.evaluatorInputs).toHaveLength(0);
  });

  it.each([
    [{ schemaFailure: true }, "schema_failure"],
    [{ plainToolFailure: true }, "tool_failure"],
    [{ invalidEffectiveInputHash: true }, "contract_failure"],
    [{ evaluatorThrows: true }, "contract_failure"],
    [{ invalidEvaluatorScore: true }, "contract_failure"],
  ] as const)("scores deterministic adapter/evaluator failure %j as terminal evidence", async (options, failureMetric) => {
    const values = fixtures(`experiment-scored-${failureMetric}-${Object.keys(options)[0]}`);
    const repository = new MemoryRepository();
    const adapter = adapters(options);
    const result = await runPromptExperimentPartition({
      ...values,
      partition: "VALIDATION",
      environment: environment(),
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      maxConcurrency: 4,
      now: () => NOW,
    });
    expect(result.status).toBe("VALIDATION_COMPLETE");
    expect(
      [...repository.runs.values()].every(
        (run) =>
          run.status === "COMPLETE" &&
          run.metrics.normalized_score === -1 &&
          run.metrics[failureMetric] === 1 &&
          run.effectiveInputHash?.startsWith("sha256:") &&
          !run.retryable,
      ),
    ).toBe(true);
  });

  it("reserves one failure-ref slot when an adapter supplies the schema maximum", async () => {
    const values = fixtures("experiment-scored-ref-bound");
    const repository = new MemoryRepository();
    const adapter = adapters({ schemaFailure: true, scoredFailureRefCount: 100 });
    const result = await runPromptExperimentPartition({
      ...values,
      partition: "VALIDATION",
      environment: environment(),
      repository,
      executor: adapter.executor,
      evaluator: adapter.evaluator,
      maxConcurrency: 4,
      now: () => NOW,
    });
    expect(result.status).toBe("VALIDATION_COMPLETE");
    for (const run of repository.runs.values()) {
      expect(run.failureCaseRefs).toHaveLength(100);
      expect(
        run.failureCaseRefs.filter((ref) => ref.startsWith("failure://adapter/")),
      ).toHaveLength(99);
      expect(
        run.failureCaseRefs.some((ref) =>
          ref.startsWith(`failure://prompt-experiment/${run.runId}/`),
        ),
      ).toBe(true);
    }
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
        repository,
        executor: adapter.executor,
        evaluator: adapter.evaluator,
      }),
    ).rejects.toThrow("prompt_experiment_environment_drift:toolConfigHash");
    expect(repository.writeCount).toBe(0);
    expect(adapter.calls.size).toBe(0);

    const darwinRepository = new MemoryRepository();
    const darwinAdapter = adapters();
    await expect(
      runPromptExperimentPartition({
        ...values,
        partition: "VALIDATION",
        environment: { ...environment(), darwinianUsageSnapshotHash: HASH_C },
        repository: darwinRepository,
        executor: darwinAdapter.executor,
        evaluator: darwinAdapter.evaluator,
      }),
    ).rejects.toThrow("prompt_experiment_environment_drift:darwinianUsageSnapshotHash");
    expect(darwinRepository.writeCount).toBe(0);
    expect(darwinAdapter.calls.size).toBe(0);

    const componentRepository = new MemoryRepository();
    const componentAdapter = adapters();
    await expect(
      runPromptExperimentPartition({
        ...values,
        partition: "VALIDATION",
        environment: { ...environment(), componentCalibrationSnapshotHash: HASH_A },
        repository: componentRepository,
        executor: componentAdapter.executor,
        evaluator: componentAdapter.evaluator,
      }),
    ).rejects.toThrow("prompt_experiment_environment_drift:componentCalibrationSnapshotHash");
    expect(componentRepository.writeCount).toBe(0);
    expect(componentAdapter.calls.size).toBe(0);
  });

  it("rejects a split manifest created after the runner clock before persistence", async () => {
    const values = fixtures("experiment-future-split");
    const repository = new MemoryRepository();
    const adapter = adapters();
    await expect(
      runPromptExperimentPartition({
        ...values,
        split: { ...values.split, createdAt: "2999-01-01T00:00:00Z" },
        partition: "VALIDATION",
        environment: environment(),
        repository,
        executor: adapter.executor,
        evaluator: adapter.evaluator,
        now: () => NOW,
      }),
    ).rejects.toThrow("prompt_experiment_split_created_in_future");
    expect(repository.writeCount).toBe(0);
    expect(adapter.executorInputs).toHaveLength(0);
  });

  it("rejects a Candidate whose reserved sample set differs from the frozen split", async () => {
    const values = fixtures("experiment-exclusion-drift");
    const repository = new MemoryRepository();
    const adapter = adapters();
    await expect(
      runPromptExperimentPartition({
        ...values,
        candidate: { ...values.candidate, excludedSampleIdsHash: HASH_C },
        partition: "VALIDATION",
        environment: environment(),
        repository,
        executor: adapter.executor,
        evaluator: adapter.evaluator,
      }),
    ).rejects.toThrow("candidate_dataset_split_mismatch");
    expect(repository.writeCount).toBe(0);
    expect(adapter.calls.size).toBe(0);

    const trainingRepository = new MemoryRepository();
    const trainingAdapter = adapters();
    await expect(
      runPromptExperimentPartition({
        ...values,
        candidate: { ...values.candidate, trainingProjectionHash: HASH_C },
        partition: "VALIDATION",
        environment: environment(),
        repository: trainingRepository,
        executor: trainingAdapter.executor,
        evaluator: trainingAdapter.evaluator,
      }),
    ).rejects.toThrow("candidate_dataset_split_mismatch");
    expect(trainingRepository.writeCount).toBe(0);
    expect(trainingAdapter.calls.size).toBe(0);
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

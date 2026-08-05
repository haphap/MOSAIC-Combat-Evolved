import { canonicalJsonHash, compareCanonicalStrings } from "../agents/helpers/canonical_json.js";
import type { PromptReleaseExecutionBehaviorBinding } from "../agents/prompts/prompt_release_contract.js";
import type { BridgeApi } from "../bridge/types.js";
import { selectPromptCandidateFamily } from "./prompt_candidate_family.js";
import {
  assertCandidateMatchesSplit,
  assertCandidatePublicationMatches,
  type DatasetSplitManifest,
  DatasetSplitManifestSchema,
  PROMPT_EXPERIMENT_MAX_ATTEMPTS,
  type PromptCandidate,
  type PromptCandidateFamily,
  PromptCandidateFamilySchema,
  type PromptCandidatePublication,
  PromptCandidatePublicationSchema,
  PromptCandidateSchema,
  type PromptDatasetSampleRef,
  type PromptExperiment,
  type PromptExperimentRun,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
  PromptOptimizerSha256Schema,
  type PromptOptimizerTarget,
  type PromptRefPair,
  type PromptTrainingProjection,
  promptExperimentRunId,
} from "./prompt_optimizer_contract.js";
import {
  type PromptPromotionPolicy,
  PromptPromotionPolicySchema,
  promptEvaluationBinding,
  promptOrderedMean,
} from "./prompt_promotion_policy.js";

export interface PromptExperimentRepository {
  putTrainingProjection(record: PromptTrainingProjection): Promise<PromptTrainingProjection>;
  putCandidate(record: PromptCandidate): Promise<PromptCandidate>;
  putCandidatePublication(record: PromptCandidatePublication): Promise<PromptCandidatePublication>;
  getCandidatePublication(candidateId: string): Promise<PromptCandidatePublication | null>;
  putSplit(record: DatasetSplitManifest): Promise<DatasetSplitManifest>;
  putFamily(record: PromptCandidateFamily): Promise<PromptCandidateFamily>;
  getFamily(familyId: string): Promise<PromptCandidateFamily | null>;
  getExperiment(experimentId: string): Promise<PromptExperiment | null>;
  listExperiments(familyId: string): Promise<PromptExperiment[]>;
  putExperiment(
    record: PromptExperiment,
    promotionPolicy?: PromptPromotionPolicy,
  ): Promise<PromptExperiment>;
  listRuns(experimentId: string): Promise<PromptExperimentRun[]>;
  putRun(record: PromptExperimentRun): Promise<PromptExperimentRun>;
  claimRun(
    record: PromptExperimentRun,
    leaseDurationMs: number,
  ): Promise<PromptExperimentRun | null>;
}

export class BridgePromptExperimentRepository implements PromptExperimentRepository {
  constructor(private readonly api: BridgeApi) {}

  putTrainingProjection(record: PromptTrainingProjection): Promise<PromptTrainingProjection> {
    return this.api.promptOptimizerPutTrainingProjection(record);
  }

  putCandidate(record: PromptCandidate): Promise<PromptCandidate> {
    return this.api.promptOptimizerPutCandidate(record);
  }

  putCandidatePublication(record: PromptCandidatePublication): Promise<PromptCandidatePublication> {
    return this.api.promptOptimizerPutCandidatePublication(record);
  }

  getCandidatePublication(candidateId: string): Promise<PromptCandidatePublication | null> {
    return this.api.promptOptimizerGetCandidatePublication(candidateId);
  }

  putSplit(record: DatasetSplitManifest): Promise<DatasetSplitManifest> {
    return this.api.promptOptimizerPutSplit(record);
  }

  putFamily(record: PromptCandidateFamily): Promise<PromptCandidateFamily> {
    return this.api.promptOptimizerPutFamily(record);
  }

  getFamily(familyId: string): Promise<PromptCandidateFamily | null> {
    return this.api.promptOptimizerGetFamily(familyId);
  }

  getExperiment(experimentId: string): Promise<PromptExperiment | null> {
    return this.api.promptOptimizerGetExperiment(experimentId);
  }

  listExperiments(familyId: string): Promise<PromptExperiment[]> {
    return this.api.promptOptimizerListExperiments(familyId);
  }

  putExperiment(
    record: PromptExperiment,
    promotionPolicy?: PromptPromotionPolicy,
  ): Promise<PromptExperiment> {
    return this.api.promptOptimizerPutExperiment(record, promotionPolicy);
  }

  listRuns(experimentId: string): Promise<PromptExperimentRun[]> {
    return this.api.promptOptimizerListRuns(experimentId);
  }

  putRun(record: PromptExperimentRun): Promise<PromptExperimentRun> {
    return this.api.promptOptimizerPutRun(record);
  }

  claimRun(
    record: PromptExperimentRun,
    leaseDurationMs: number,
  ): Promise<PromptExperimentRun | null> {
    return this.api.promptOptimizerClaimRun(record, leaseDurationMs);
  }
}

export interface FrozenPromptExperimentEnvironment {
  modelConfigHash: string;
  toolConfigHash: string;
  componentCalibrationSnapshotHash: string;
  darwinianUsageSnapshotHash: string;
  executorAdapterHash: string;
  evaluatorAdapterHash: string;
  evaluatorVersion: string;
  evaluatorConfigHash: string;
  codeCommit: string;
  executionBehaviorRelease: PromptReleaseExecutionBehaviorBinding;
}

export interface PromptExperimentAgentExecutor {
  execute(input: {
    target: PromptOptimizerTarget;
    partition: "VALIDATION" | "HOLDOUT";
    sample: Pick<PromptDatasetSampleRef, "sampleId" | "inputRef" | "inputHash" | "eventWindow">;
    seed: number;
    environment: Readonly<FrozenPromptExperimentEnvironment>;
    promptSourceId: string;
    promptCommit: string;
    promptRefs: PromptRefPair;
    promptHashes: { zh: string; en: string };
  }): Promise<{
    acceptedOutputRef: string;
    effectiveInputHash: string;
    consumedPromptHashes: { zh: string; en: string };
    traceRef?: string | null;
  }>;
}

/**
 * The evaluation protocol omits explicit side, Candidate identity, and Prompt
 * content. Evaluator adapters are still trusted code and may infer context from
 * an output reference, so this interface does not claim process-level blindness.
 */
export interface PromptExperimentEvaluator {
  evaluate(input: {
    target: PromptOptimizerTarget;
    sample: PromptDatasetSampleRef;
    environment: Readonly<FrozenPromptExperimentEnvironment>;
    acceptedOutputRef: string;
  }): Promise<{
    normalizedScore: number;
    metrics?: Readonly<Record<string, number>>;
    failureCaseRefs?: ReadonlyArray<string>;
  }>;
}

export interface RunPromptExperimentPartitionInput {
  candidate: PromptCandidate;
  candidatePublication: PromptCandidatePublication;
  family: PromptCandidateFamily;
  experiment: PromptExperiment;
  split: DatasetSplitManifest;
  partition: "VALIDATION" | "HOLDOUT";
  environment: FrozenPromptExperimentEnvironment;
  promotionPolicy: PromptPromotionPolicy;
  authorizedPolicyHashes: ReadonlySet<string>;
  repository: PromptExperimentRepository;
  executor: PromptExperimentAgentExecutor;
  evaluator: PromptExperimentEvaluator;
  maxConcurrency?: number;
  runOwnerId: string;
  leaseDurationMs?: number;
  now?: () => string;
}

function assertEnvironment(
  experiment: PromptExperiment,
  environment: FrozenPromptExperimentEnvironment,
): void {
  for (const key of [
    "modelConfigHash",
    "toolConfigHash",
    "componentCalibrationSnapshotHash",
    "darwinianUsageSnapshotHash",
    "executorAdapterHash",
    "evaluatorAdapterHash",
    "evaluatorVersion",
    "evaluatorConfigHash",
    "codeCommit",
    "executionBehaviorRelease",
  ] as const) {
    if (canonicalJsonHash(experiment[key]) !== canonicalJsonHash(environment[key])) {
      throw new Error(`prompt_experiment_environment_drift:${key}`);
    }
  }
}

function assertBindings(input: RunPromptExperimentPartitionInput): void {
  if (canonicalJsonHash(input.split) !== input.experiment.datasetSplitManifestHash) {
    throw new Error("prompt_experiment_split_manifest_drift");
  }
  assertCandidateMatchesSplit(input.candidate, input.split);
  assertCandidatePublicationMatches(input.candidate, input.candidatePublication);
  if (
    input.candidate.parentId !== input.experiment.championId ||
    input.candidate.parentPromptCommit !== input.experiment.championPromptCommit ||
    canonicalJsonHash(input.candidate.parentPromptHashes) !==
      canonicalJsonHash(input.experiment.championPromptHashes) ||
    canonicalJsonHash(input.candidate.target) !== canonicalJsonHash(input.experiment.target) ||
    input.candidate.candidateId !== input.experiment.candidateId ||
    canonicalJsonHash(input.candidate.promptHashes) !==
      canonicalJsonHash(input.experiment.candidatePromptHashes) ||
    canonicalJsonHash(input.candidate.promptRefs) !==
      canonicalJsonHash(input.experiment.candidatePromptRefs) ||
    input.candidatePublication.promptSourceId !== input.experiment.candidatePromptSourceId ||
    input.candidatePublication.candidatePromptCommit !== input.experiment.candidatePromptCommit ||
    input.candidatePublication.publicationHash !== input.experiment.candidatePublicationHash
  ) {
    throw new Error("prompt_experiment_prompt_binding_drift");
  }
  if (
    input.family.familyId !== input.experiment.familyId ||
    !input.family.candidateIds.includes(input.candidate.candidateId) ||
    input.family.championReleaseId !== input.experiment.championId ||
    input.family.championPromptSourceId !== input.experiment.championPromptSourceId ||
    input.family.championPromptCommit !== input.experiment.championPromptCommit ||
    canonicalJsonHash(input.family.championPromptRefs) !==
      canonicalJsonHash(input.experiment.championPromptRefs) ||
    canonicalJsonHash(input.family.championPromptHashes) !==
      canonicalJsonHash(input.experiment.championPromptHashes) ||
    input.family.datasetSplitId !== input.split.splitId ||
    input.family.datasetSplitManifestHash !== input.experiment.datasetSplitManifestHash ||
    input.family.promotionPolicyVersion !== input.experiment.promotionPolicyVersion ||
    input.family.promotionPolicyConfigHash !== input.experiment.promotionPolicyConfigHash
  ) {
    throw new Error("prompt_experiment_family_binding_drift");
  }
  if (input.split.evaluatorVersion !== input.experiment.evaluatorVersion) {
    throw new Error("prompt_experiment_split_environment_drift");
  }
  const policy = PromptPromotionPolicySchema.parse(input.promotionPolicy);
  const policyConfigHash = canonicalJsonHash(policy);
  if (
    !input.authorizedPolicyHashes.has(policyConfigHash) ||
    input.family.promotionPolicyVersion !== policy.policyVersion ||
    input.family.promotionPolicyConfigHash !== policyConfigHash ||
    input.experiment.promotionPolicyVersion !== policy.policyVersion ||
    input.experiment.promotionPolicyConfigHash !== policyConfigHash
  ) {
    throw new Error("prompt_experiment_promotion_policy_not_authorized");
  }
  const evaluationBinding = promptEvaluationBinding(input.experiment.target);
  const expectedBinding = {
    evaluationObject: evaluationBinding.evaluationObject,
    evaluationObjectSchemaVersion: evaluationBinding.evaluationObjectSchemaVersion,
    primaryLabelId: evaluationBinding.primaryLabelId,
    scoringContractVersion: evaluationBinding.scoringContractVersion,
    outcomeContractVersion: evaluationBinding.outcomeContractVersion,
  };
  if (
    canonicalJsonHash(input.experiment.evaluationBinding) !== canonicalJsonHash(expectedBinding)
  ) {
    throw new Error("prompt_experiment_evaluation_binding_drift");
  }
  assertEnvironment(input.experiment, input.environment);
}

function assertPersistedExperimentMatches(
  expected: PromptExperiment,
  persisted: PromptExperiment,
): void {
  for (const key of [
    "experimentId",
    "familyId",
    "candidateId",
    "championId",
    "target",
    "championPromptSourceId",
    "championPromptCommit",
    "championPromptRefs",
    "championPromptHashes",
    "candidatePromptRefs",
    "candidatePromptHashes",
    "candidatePromptSourceId",
    "candidatePromptCommit",
    "candidatePublicationHash",
    "datasetSplitId",
    "datasetSplitManifestHash",
    "promotionPolicyVersion",
    "promotionPolicyConfigHash",
    "modelConfigHash",
    "toolConfigHash",
    "componentCalibrationSnapshotHash",
    "darwinianUsageSnapshotHash",
    "executorAdapterHash",
    "evaluatorAdapterHash",
    "evaluationBinding",
    "evaluatorVersion",
    "evaluatorConfigHash",
    "codeCommit",
    "executionBehaviorRelease",
    "repeatSeeds",
    "createdAt",
  ] as const) {
    if (canonicalJsonHash(expected[key]) !== canonicalJsonHash(persisted[key])) {
      throw new Error(`prompt_experiment_persisted_definition_drift:${key}`);
    }
  }
}

function pendingRun(
  experimentId: string,
  partition: "VALIDATION" | "HOLDOUT",
  side: "CHAMPION" | "CANDIDATE",
  sampleId: string,
  seed: number,
): PromptExperimentRun {
  return PromptExperimentRunSchema.parse({
    schemaVersion: "prompt_experiment_run_v1",
    runId: promptExperimentRunId({ experimentId, partition, side, sampleId, seed }),
    experimentId,
    partition,
    side,
    sampleId,
    seed,
    status: "PENDING",
    agentOutputRef: null,
    metrics: {},
    failureCaseRefs: [],
    traceRef: null,
    effectiveInputHash: null,
    leaseOwner: null,
    leaseExpiresAt: null,
    attempt: 0,
    retryable: false,
    attemptFailureCodes: [],
    errorCode: null,
    startedAt: null,
    completedAt: null,
  });
}

async function mapLimit<T>(
  items: ReadonlyArray<T>,
  limit: number,
  task: (item: T) => Promise<void>,
): Promise<void> {
  let next = 0;
  const failures: Array<{ value: unknown }> = [];
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length && failures.length === 0) {
      const index = next;
      next += 1;
      const item = items[index];
      if (item === undefined) continue;
      try {
        await task(item);
      } catch (error) {
        if (failures.length === 0) failures.push({ value: error });
      }
    }
  });
  await Promise.all(workers);
  if (failures.length > 0) throw failures[0]?.value;
}

function errorCode(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  const normalized = raw.replace(/[^A-Za-z0-9_.:-]+/g, "_").slice(0, 200);
  return normalized || "prompt_experiment_execution_failed";
}

function safePublicRef(value: string | null | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed.length > 0 && trimmed.length <= 512 && !/[\r\n]/.test(trimmed) ? trimmed : null;
}

function boundedFailureCaseRefs(refs: ReadonlyArray<string>, syntheticRef: string): string[] {
  const supplied = refs
    .map((ref) => safePublicRef(ref))
    .filter((ref): ref is string => ref !== null && ref !== syntheticRef);
  return [...new Set(supplied)]
    .sort(compareCanonicalStrings)
    .slice(0, 99)
    .concat(syntheticRef)
    .sort(compareCanonicalStrings);
}

export type PromptExperimentScoredFailureCategory =
  | "schema_failure"
  | "contract_failure"
  | "tool_failure";

/** A model attempt that completed but must receive the deterministic worst score. */
export class PromptExperimentScoredFailure extends Error {
  readonly failureCategory: PromptExperimentScoredFailureCategory;
  readonly effectiveInputHash: string;
  readonly agentOutputRef: string | null;
  readonly failureCaseRefs: ReadonlyArray<string>;
  readonly traceRef: string | null;

  constructor(input: {
    failureCategory: PromptExperimentScoredFailureCategory;
    effectiveInputHash: string;
    agentOutputRef?: string | null;
    failureCaseRefs?: ReadonlyArray<string>;
    traceRef?: string | null;
  }) {
    super(input.failureCategory);
    this.name = "PromptExperimentScoredFailure";
    this.failureCategory = input.failureCategory;
    this.effectiveInputHash = input.effectiveInputHash;
    this.agentOutputRef = input.agentOutputRef ?? null;
    this.failureCaseRefs = input.failureCaseRefs ?? [];
    this.traceRef = input.traceRef ?? null;
  }
}

/** Only this explicit error class can authorize a bounded infrastructure retry. */
export class PromptExperimentTransientInfrastructureError extends Error {
  constructor(code: string) {
    super(code);
    this.name = "PromptExperimentTransientInfrastructureError";
  }
}

function mergedMetrics(
  normalizedScore: number,
  metrics: Readonly<Record<string, number>> | undefined,
): Record<string, number> {
  if (!Number.isFinite(normalizedScore) || normalizedScore < -1 || normalizedScore > 1) {
    throw new Error("prompt_experiment_score_out_of_range");
  }
  const result = { ...(metrics ?? {}), normalized_score: normalizedScore };
  if (Object.values(result).some((value) => !Number.isFinite(value))) {
    throw new Error("prompt_experiment_metric_not_finite");
  }
  return Object.fromEntries(
    Object.entries(result).sort(([left], [right]) => compareCanonicalStrings(left, right)),
  );
}

async function executeRun(input: {
  definition: PromptExperimentRun;
  sample: PromptDatasetSampleRef;
  experiment: PromptExperiment;
  environment: FrozenPromptExperimentEnvironment;
  repository: PromptExperimentRepository;
  executor: PromptExperimentAgentExecutor;
  evaluator: PromptExperimentEvaluator;
  runOwnerId: string;
  leaseDurationMs: number;
  now: () => string;
}): Promise<void> {
  const { definition } = input;
  const finalAttemptLeaseReclaim =
    definition.status === "RUNNING" && definition.attempt >= PROMPT_EXPERIMENT_MAX_ATTEMPTS;
  if (
    (definition.attempt >= PROMPT_EXPERIMENT_MAX_ATTEMPTS && !finalAttemptLeaseReclaim) ||
    (definition.status === "FAILED" && !definition.retryable)
  ) {
    return;
  }
  const startedAt = input.now();
  const leaseExpiresAt = new Date(Date.parse(startedAt) + input.leaseDurationMs).toISOString();
  const claimed = await input.repository.claimRun(
    PromptExperimentRunSchema.parse({
      ...definition,
      status: "RUNNING",
      agentOutputRef: null,
      metrics: {},
      failureCaseRefs: [],
      traceRef: null,
      effectiveInputHash: null,
      leaseOwner: input.runOwnerId,
      leaseExpiresAt,
      attempt: finalAttemptLeaseReclaim ? definition.attempt : definition.attempt + 1,
      retryable: false,
      attemptFailureCodes: definition.attemptFailureCodes,
      errorCode: null,
      startedAt,
      completedAt: null,
    }),
    input.leaseDurationMs,
  );
  if (claimed === null) return;
  const prompt =
    claimed.side === "CHAMPION"
      ? {
          promptSourceId: input.experiment.championPromptSourceId,
          promptCommit: input.experiment.championPromptCommit,
          promptRefs: input.experiment.championPromptRefs,
          promptHashes: input.experiment.championPromptHashes,
        }
      : {
          promptSourceId: input.experiment.candidatePromptSourceId,
          promptCommit: input.experiment.candidatePromptCommit,
          promptRefs: input.experiment.candidatePromptRefs,
          promptHashes: input.experiment.candidatePromptHashes,
        };
  let acceptedOutputRef: string | null = null;
  let effectiveInputHash: string | null = null;
  let traceRef: string | null = null;
  let deterministicFailureCategory: PromptExperimentScoredFailureCategory = "tool_failure";
  const requestedInputHash = canonicalJsonHash({
    environment: input.environment,
    partition: claimed.partition,
    promptHashes: prompt.promptHashes,
    promptSourceId: prompt.promptSourceId,
    promptCommit: prompt.promptCommit,
    promptRefs: prompt.promptRefs,
    sample: {
      sampleId: input.sample.sampleId,
      inputRef: input.sample.inputRef,
      inputHash: input.sample.inputHash,
      eventWindow: input.sample.eventWindow,
    },
    seed: claimed.seed,
    target: input.experiment.target,
  });
  let completeRecord: PromptExperimentRun;
  try {
    const execution = await input.executor.execute({
      target: input.experiment.target,
      partition: claimed.partition,
      sample: {
        sampleId: input.sample.sampleId,
        inputRef: input.sample.inputRef,
        inputHash: input.sample.inputHash,
        eventWindow: input.sample.eventWindow,
      },
      seed: claimed.seed,
      environment: input.environment,
      promptSourceId: prompt.promptSourceId,
      promptCommit: prompt.promptCommit,
      promptRefs: prompt.promptRefs,
      promptHashes: prompt.promptHashes,
    });
    deterministicFailureCategory = "contract_failure";
    acceptedOutputRef = safePublicRef(execution.acceptedOutputRef);
    if (acceptedOutputRef === null) throw new Error("prompt_experiment_agent_output_ref_invalid");
    effectiveInputHash = PromptOptimizerSha256Schema.parse(execution.effectiveInputHash);
    traceRef = safePublicRef(execution.traceRef);
    if (
      canonicalJsonHash(execution.consumedPromptHashes) !== canonicalJsonHash(prompt.promptHashes)
    ) {
      throw new PromptExperimentScoredFailure({
        failureCategory: "contract_failure",
        effectiveInputHash,
        agentOutputRef: acceptedOutputRef,
        traceRef,
      });
    }
    const evaluation = await input.evaluator.evaluate({
      target: input.experiment.target,
      sample: input.sample,
      environment: input.environment,
      acceptedOutputRef,
    });
    completeRecord = PromptExperimentRunSchema.parse({
      ...claimed,
      status: "COMPLETE",
      agentOutputRef: acceptedOutputRef,
      metrics: mergedMetrics(evaluation.normalizedScore, evaluation.metrics),
      failureCaseRefs: [...(evaluation.failureCaseRefs ?? [])].sort(compareCanonicalStrings),
      traceRef,
      effectiveInputHash,
      retryable: false,
      errorCode: null,
      startedAt: claimed.startedAt,
      completedAt: input.now(),
    });
  } catch (error) {
    const code = errorCode(error);
    if (error instanceof PromptExperimentTransientInfrastructureError) {
      const retryable = claimed.attempt < PROMPT_EXPERIMENT_MAX_ATTEMPTS;
      await input.repository.putRun(
        PromptExperimentRunSchema.parse({
          ...claimed,
          status: "FAILED",
          agentOutputRef: acceptedOutputRef,
          metrics: {},
          failureCaseRefs: [],
          traceRef,
          effectiveInputHash,
          retryable,
          attemptFailureCodes: [...claimed.attemptFailureCodes, code],
          errorCode: code,
          startedAt: claimed.startedAt,
          completedAt: input.now(),
        }),
      );
      if (retryable) throw error;
      return;
    }
    const scoredFailure = error instanceof PromptExperimentScoredFailure ? error : null;
    const suppliedInputHash = scoredFailure
      ? PromptOptimizerSha256Schema.safeParse(scoredFailure.effectiveInputHash)
      : null;
    const failureCategory = scoredFailure?.failureCategory ?? deterministicFailureCategory;
    const syntheticFailureRef = `failure://prompt-experiment/${claimed.runId}/${code}`;
    completeRecord = PromptExperimentRunSchema.parse({
      ...claimed,
      status: "COMPLETE",
      agentOutputRef:
        safePublicRef(scoredFailure?.agentOutputRef) ??
        acceptedOutputRef ??
        `failure://prompt-experiment/${claimed.runId}/attempt-${claimed.attempt}`,
      metrics: mergedMetrics(-1, { [failureCategory]: 1 }),
      failureCaseRefs: boundedFailureCaseRefs(
        scoredFailure?.failureCaseRefs ?? [],
        syntheticFailureRef,
      ),
      traceRef: safePublicRef(scoredFailure?.traceRef) ?? traceRef,
      effectiveInputHash:
        suppliedInputHash?.success === true
          ? suppliedInputHash.data
          : (effectiveInputHash ?? requestedInputHash),
      retryable: false,
      errorCode: null,
      startedAt: claimed.startedAt,
      completedAt: input.now(),
    });
  }
  await input.repository.putRun(completeRecord);
}

function aggregateRuns(
  partition: "VALIDATION" | "HOLDOUT",
  runs: ReadonlyArray<PromptExperimentRun>,
): { metrics: Record<string, number>; failureCaseRefs: string[] } {
  const complete = runs
    .filter((run) => run.partition === partition && run.status === "COMPLETE")
    .sort(
      (left, right) =>
        compareCanonicalStrings(left.sampleId, right.sampleId) ||
        left.seed - right.seed ||
        compareCanonicalStrings(left.side, right.side),
    );
  const pairs = new Map<string, Partial<Record<"CHAMPION" | "CANDIDATE", PromptExperimentRun>>>();
  for (const run of complete) {
    const key = `${run.sampleId}:${run.seed}`;
    const pair = pairs.get(key) ?? {};
    pair[run.side] = run;
    pairs.set(key, pair);
  }
  if ([...pairs.values()].some((pair) => !pair.CHAMPION || !pair.CANDIDATE)) {
    throw new Error("prompt_experiment_pair_incomplete");
  }
  const championScores: number[] = [];
  const candidateScores: number[] = [];
  const deltas: number[] = [];
  for (const pair of pairs.values()) {
    const champion = pair?.CHAMPION?.metrics.normalized_score;
    const candidate = pair?.CANDIDATE?.metrics.normalized_score;
    if (champion === undefined || candidate === undefined) {
      throw new Error("prompt_experiment_pair_score_missing");
    }
    championScores.push(champion);
    candidateScores.push(candidate);
    deltas.push(candidate - champion);
  }
  const prefix = partition.toLowerCase();
  return {
    metrics: {
      [`${prefix}_candidate_mean`]: promptOrderedMean(candidateScores),
      [`${prefix}_champion_mean`]: promptOrderedMean(championScores),
      [`${prefix}_paired_delta`]: promptOrderedMean(deltas),
      [`${prefix}_pair_count`]: pairs.size,
    },
    failureCaseRefs: [...new Set(complete.flatMap((run) => run.failureCaseRefs))].sort(
      compareCanonicalStrings,
    ),
  };
}

export async function runPromptExperimentPartition(
  rawInput: RunPromptExperimentPartitionInput,
): Promise<PromptExperiment> {
  const now = rawInput.now ?? (() => new Date().toISOString());
  const input = {
    ...rawInput,
    candidate: PromptCandidateSchema.parse(rawInput.candidate),
    candidatePublication: PromptCandidatePublicationSchema.parse(rawInput.candidatePublication),
    family: PromptCandidateFamilySchema.parse(rawInput.family),
    experiment: PromptExperimentSchema.parse(rawInput.experiment),
    split: DatasetSplitManifestSchema.parse(rawInput.split),
    promotionPolicy: PromptPromotionPolicySchema.parse(rawInput.promotionPolicy),
  };
  if (Date.parse(input.split.createdAt) > Date.parse(now())) {
    throw new Error("prompt_experiment_split_created_in_future");
  }
  assertBindings(input);
  await input.repository.putCandidate(input.candidate);
  const persistedPublication = await input.repository.getCandidatePublication(
    input.candidate.candidateId,
  );
  if (persistedPublication === null) {
    await input.repository.putCandidatePublication(input.candidatePublication);
  } else if (
    canonicalJsonHash(persistedPublication) !== canonicalJsonHash(input.candidatePublication)
  ) {
    throw new Error("prompt_candidate_publication_persisted_definition_drift");
  }
  await input.repository.putSplit(input.split);
  const persistedFamily = await input.repository.getFamily(input.family.familyId);
  if (persistedFamily === null) {
    await input.repository.putFamily(input.family);
  } else if (
    canonicalJsonHash({
      target: persistedFamily.target,
      championReleaseId: persistedFamily.championReleaseId,
      championPromptSourceId: persistedFamily.championPromptSourceId,
      championPromptCommit: persistedFamily.championPromptCommit,
      championPromptRefs: persistedFamily.championPromptRefs,
      championPromptHashes: persistedFamily.championPromptHashes,
      datasetSplitId: persistedFamily.datasetSplitId,
      datasetSplitManifestHash: persistedFamily.datasetSplitManifestHash,
      promotionPolicyVersion: persistedFamily.promotionPolicyVersion,
      promotionPolicyConfigHash: persistedFamily.promotionPolicyConfigHash,
      candidateIds: persistedFamily.candidateIds,
    }) !==
    canonicalJsonHash({
      target: input.family.target,
      championReleaseId: input.family.championReleaseId,
      championPromptSourceId: input.family.championPromptSourceId,
      championPromptCommit: input.family.championPromptCommit,
      championPromptRefs: input.family.championPromptRefs,
      championPromptHashes: input.family.championPromptHashes,
      datasetSplitId: input.family.datasetSplitId,
      datasetSplitManifestHash: input.family.datasetSplitManifestHash,
      promotionPolicyVersion: input.family.promotionPolicyVersion,
      promotionPolicyConfigHash: input.family.promotionPolicyConfigHash,
      candidateIds: input.family.candidateIds,
    })
  ) {
    throw new Error("prompt_experiment_family_definition_drift");
  }
  const persisted = await input.repository.getExperiment(input.experiment.experimentId);
  if (persisted !== null) assertPersistedExperimentMatches(input.experiment, persisted);
  let experiment =
    persisted ?? (await input.repository.putExperiment(input.experiment, input.promotionPolicy));
  if (input.partition === "VALIDATION") {
    if (experiment.status === "PENDING") {
      experiment = await input.repository.putExperiment(
        {
          ...experiment,
          status: "VALIDATION_RUNNING",
        },
        input.promotionPolicy,
      );
    } else if (["VALIDATION_COMPLETE", "HOLDOUT_RUNNING", "COMPLETE"].includes(experiment.status)) {
      return experiment;
    } else if (experiment.status !== "VALIDATION_RUNNING") {
      throw new Error(`prompt_experiment_validation_state_invalid:${experiment.status}`);
    }
  } else {
    const currentFamily = await input.repository.getFamily(experiment.familyId);
    if (currentFamily === null) {
      throw new Error("prompt_experiment_holdout_winner_required");
    }
    const familyExperiments = await input.repository.listExperiments(currentFamily.familyId);
    const validationRuns = await Promise.all(
      familyExperiments.map(async (sibling) => ({
        experimentId: sibling.experimentId,
        runs: (await input.repository.listRuns(sibling.experimentId)).filter(
          (run) => run.partition === "VALIDATION",
        ),
      })),
    );
    const selection = selectPromptCandidateFamily({
      family: currentFamily,
      validationExperiments: familyExperiments,
      validationRuns,
      split: input.split,
      policy: input.promotionPolicy,
    });
    if (
      selection.selectedExperimentId !== experiment.experimentId ||
      selection.selectedCandidateId !== experiment.candidateId
    ) {
      throw new Error("prompt_experiment_holdout_winner_required");
    }
    if (experiment.status === "VALIDATION_COMPLETE") {
      experiment = await input.repository.putExperiment(
        {
          ...experiment,
          status: "HOLDOUT_RUNNING",
          holdoutOpenedAt: now(),
        },
        input.promotionPolicy,
      );
    } else if (experiment.status === "COMPLETE") {
      return experiment;
    } else if (experiment.status !== "HOLDOUT_RUNNING") {
      throw new Error(`prompt_experiment_holdout_state_invalid:${experiment.status}`);
    }
  }

  const partitionRows =
    input.partition === "VALIDATION" ? input.split.validation : input.split.holdout;
  const existingRuns = await input.repository.listRuns(experiment.experimentId);
  const existingById = new Map(existingRuns.map((run) => [run.runId, run]));
  const tasks = partitionRows.samples.flatMap((sample) =>
    experiment.repeatSeeds.flatMap((seed) =>
      (["CHAMPION", "CANDIDATE"] as const).map((side) => ({
        sample,
        definition: pendingRun(
          experiment.experimentId,
          input.partition,
          side,
          sample.sampleId,
          seed,
        ),
      })),
    ),
  );
  let executionError: { value: unknown } | null = null;
  try {
    await mapLimit(tasks, Math.max(1, input.maxConcurrency ?? 1), async (task) => {
      const existing = existingById.get(task.definition.runId);
      if (existing?.status === "COMPLETE") return;
      await executeRun({
        definition: existing ?? task.definition,
        sample: task.sample,
        experiment,
        environment: input.environment,
        repository: input.repository,
        executor: input.executor,
        evaluator: input.evaluator,
        runOwnerId: input.runOwnerId,
        leaseDurationMs: input.leaseDurationMs ?? 300_000,
        now,
      });
    });
  } catch (error) {
    executionError = { value: error };
  }
  const allRuns = await input.repository.listRuns(experiment.experimentId);
  const expectedIds = new Set(tasks.map((task) => task.definition.runId));
  const partitionRuns = allRuns.filter((run) => expectedIds.has(run.runId));
  const terminalRun = partitionRuns
    .filter((run) => run.status === "FAILED" && !run.retryable)
    .sort((left, right) => compareCanonicalStrings(left.runId, right.runId))[0];
  if (terminalRun !== undefined) {
    await input.repository.putExperiment(
      PromptExperimentSchema.parse({
        ...experiment,
        status: "FAILED",
        completedAt: now(),
      }),
      input.promotionPolicy,
    );
    throw new Error(`prompt_experiment_run_terminal:${terminalRun.runId}`);
  }
  if (executionError !== null) throw executionError.value;
  if (
    partitionRuns.length !== expectedIds.size ||
    partitionRuns.some((run) => run.status !== "COMPLETE")
  ) {
    throw new Error("prompt_experiment_partition_incomplete");
  }
  const aggregate = aggregateRuns(input.partition, partitionRuns);
  const runIds = [
    ...new Set([...experiment.runIds, ...partitionRuns.map((run) => run.runId)]),
  ].sort(compareCanonicalStrings);
  return input.repository.putExperiment(
    PromptExperimentSchema.parse({
      ...experiment,
      runIds,
      metrics: {
        ...experiment.metrics,
        ...aggregate.metrics,
      },
      tailFailureCaseRefs: [
        ...new Set([...experiment.tailFailureCaseRefs, ...aggregate.failureCaseRefs]),
      ].sort(compareCanonicalStrings),
      status: input.partition === "VALIDATION" ? "VALIDATION_COMPLETE" : "COMPLETE",
      completedAt: input.partition === "HOLDOUT" ? now() : null,
    }),
    input.promotionPolicy,
  );
}

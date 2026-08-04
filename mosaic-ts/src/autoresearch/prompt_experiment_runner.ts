import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";
import type { BridgeApi } from "../bridge/types.js";
import {
  assertCandidateMatchesSplit,
  type DatasetSplitManifest,
  DatasetSplitManifestSchema,
  type PromptCandidate,
  PromptCandidateSchema,
  type PromptDatasetSampleRef,
  type PromptExperiment,
  type PromptExperimentRun,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
  PromptHashPairSchema,
  type PromptOptimizerTarget,
  type PromptRefPair,
  PromptRefPairSchema,
} from "./prompt_optimizer_contract.js";

export interface PromptExperimentRepository {
  putCandidate(record: PromptCandidate): Promise<PromptCandidate>;
  getExperiment(experimentId: string): Promise<PromptExperiment | null>;
  putExperiment(record: PromptExperiment): Promise<PromptExperiment>;
  listRuns(experimentId: string): Promise<PromptExperimentRun[]>;
  putRun(record: PromptExperimentRun): Promise<PromptExperimentRun>;
}

export class BridgePromptExperimentRepository implements PromptExperimentRepository {
  constructor(private readonly api: BridgeApi) {}

  putCandidate(record: PromptCandidate): Promise<PromptCandidate> {
    return this.api.promptOptimizerPutCandidate(record);
  }

  getExperiment(experimentId: string): Promise<PromptExperiment | null> {
    return this.api.promptOptimizerGetExperiment(experimentId);
  }

  putExperiment(record: PromptExperiment): Promise<PromptExperiment> {
    return this.api.promptOptimizerPutExperiment(record);
  }

  listRuns(experimentId: string): Promise<PromptExperimentRun[]> {
    return this.api.promptOptimizerListRuns(experimentId);
  }

  putRun(record: PromptExperimentRun): Promise<PromptExperimentRun> {
    return this.api.promptOptimizerPutRun(record);
  }
}

export interface FrozenPromptExperimentEnvironment {
  modelConfigHash: string;
  toolConfigHash: string;
  evaluatorVersion: string;
  evaluatorConfigHash: string;
  codeCommit: string;
}

export interface PromptExecutionBinding {
  champion: { promptRefs: PromptRefPair; promptHashes: { zh: string; en: string } };
  candidate: { promptRefs: PromptRefPair; promptHashes: { zh: string; en: string } };
}

export interface PromptExperimentAgentExecutor {
  execute(input: {
    target: PromptOptimizerTarget;
    partition: "VALIDATION" | "HOLDOUT";
    sample: PromptDatasetSampleRef;
    seed: number;
    promptRefs: PromptRefPair;
    promptHashes: { zh: string; en: string };
  }): Promise<{
    acceptedOutputRef: string;
    effectiveInputHash?: string | null;
    traceRef?: string | null;
  }>;
}

/** The evaluator never receives side, Candidate identity, or Prompt content. */
export interface PromptExperimentEvaluator {
  evaluate(input: {
    target: PromptOptimizerTarget;
    sample: PromptDatasetSampleRef;
    acceptedOutputRef: string;
  }): Promise<{
    normalizedScore: number;
    metrics?: Readonly<Record<string, number>>;
    failureCaseRefs?: ReadonlyArray<string>;
  }>;
}

export interface RunPromptExperimentPartitionInput {
  candidate: PromptCandidate;
  experiment: PromptExperiment;
  split: DatasetSplitManifest;
  partition: "VALIDATION" | "HOLDOUT";
  environment: FrozenPromptExperimentEnvironment;
  promptBinding: PromptExecutionBinding;
  repository: PromptExperimentRepository;
  executor: PromptExperimentAgentExecutor;
  evaluator: PromptExperimentEvaluator;
  maxConcurrency?: number;
  now?: () => string;
}

function assertEnvironment(
  experiment: PromptExperiment,
  environment: FrozenPromptExperimentEnvironment,
): void {
  for (const key of [
    "modelConfigHash",
    "toolConfigHash",
    "evaluatorVersion",
    "evaluatorConfigHash",
    "codeCommit",
  ] as const) {
    if (experiment[key] !== environment[key]) {
      throw new Error(`prompt_experiment_environment_drift:${key}`);
    }
  }
}

function assertBindings(input: RunPromptExperimentPartitionInput): void {
  if (canonicalJsonHash(input.split) !== input.experiment.datasetSplitManifestHash) {
    throw new Error("prompt_experiment_split_manifest_drift");
  }
  assertCandidateMatchesSplit(input.candidate, input.split);
  if (
    canonicalJsonHash(input.candidate.target) !== canonicalJsonHash(input.experiment.target) ||
    input.candidate.candidateId !== input.experiment.candidateId ||
    canonicalJsonHash(input.candidate.promptHashes) !==
      canonicalJsonHash(input.experiment.candidatePromptHashes) ||
    canonicalJsonHash(input.promptBinding.candidate.promptHashes) !==
      canonicalJsonHash(input.experiment.candidatePromptHashes) ||
    canonicalJsonHash(input.promptBinding.champion.promptHashes) !==
      canonicalJsonHash(input.experiment.championPromptHashes)
  ) {
    throw new Error("prompt_experiment_prompt_binding_drift");
  }
  if (
    input.split.validation.snapshotHash !== input.experiment.validationSnapshotHash ||
    input.split.holdout.snapshotHash !== input.experiment.holdoutSnapshotHash ||
    input.split.evaluatorVersion !== input.experiment.evaluatorVersion
  ) {
    throw new Error("prompt_experiment_split_environment_drift");
  }
  assertEnvironment(input.experiment, input.environment);
}

function assertPersistedExperimentMatches(
  expected: PromptExperiment,
  persisted: PromptExperiment,
): void {
  for (const key of [
    "experimentId",
    "candidateId",
    "championId",
    "target",
    "championPromptHashes",
    "candidatePromptHashes",
    "datasetSplitManifestHash",
    "validationSnapshotHash",
    "holdoutSnapshotHash",
    "modelConfigHash",
    "toolConfigHash",
    "evaluatorVersion",
    "evaluatorConfigHash",
    "codeCommit",
    "repeatSeeds",
    "createdAt",
  ] as const) {
    if (canonicalJsonHash(expected[key]) !== canonicalJsonHash(persisted[key])) {
      throw new Error(`prompt_experiment_persisted_definition_drift:${key}`);
    }
  }
}

function runId(input: {
  experimentId: string;
  partition: "VALIDATION" | "HOLDOUT";
  side: "CHAMPION" | "CANDIDATE";
  sampleId: string;
  seed: number;
}): string {
  return `run-${canonicalJsonHash(input).slice("sha256:".length, "sha256:".length + 24)}`;
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
    runId: runId({ experimentId, partition, side, sampleId, seed }),
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
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const index = next;
      next += 1;
      const item = items[index];
      if (item !== undefined) await task(item);
    }
  });
  await Promise.all(workers);
}

function errorCode(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  const normalized = raw.replace(/[^A-Za-z0-9_.:-]+/g, "_").slice(0, 200);
  return normalized || "prompt_experiment_execution_failed";
}

function mergedMetrics(
  normalizedScore: number,
  metrics: Readonly<Record<string, number>> | undefined,
): Record<string, number> {
  if (!Number.isFinite(normalizedScore)) throw new Error("prompt_experiment_score_not_finite");
  const result = { ...(metrics ?? {}), normalized_score: normalizedScore };
  if (Object.values(result).some((value) => !Number.isFinite(value))) {
    throw new Error("prompt_experiment_metric_not_finite");
  }
  return Object.fromEntries(
    Object.entries(result).sort(([left], [right]) => left.localeCompare(right)),
  );
}

async function executeRun(input: {
  definition: PromptExperimentRun;
  sample: PromptDatasetSampleRef;
  target: PromptOptimizerTarget;
  binding: PromptExecutionBinding;
  repository: PromptExperimentRepository;
  executor: PromptExperimentAgentExecutor;
  evaluator: PromptExperimentEvaluator;
  now: () => string;
}): Promise<void> {
  const { definition } = input;
  const startedAt = input.now();
  if (definition.status !== "RUNNING") {
    await input.repository.putRun(
      PromptExperimentRunSchema.parse({
        ...definition,
        status: "RUNNING",
        agentOutputRef: null,
        metrics: {},
        failureCaseRefs: [],
        traceRef: null,
        effectiveInputHash: null,
        errorCode: null,
        startedAt,
        completedAt: null,
      }),
    );
  }
  try {
    const prompt =
      definition.side === "CHAMPION" ? input.binding.champion : input.binding.candidate;
    const execution = await input.executor.execute({
      target: input.target,
      partition: definition.partition,
      sample: input.sample,
      seed: definition.seed,
      promptRefs: prompt.promptRefs,
      promptHashes: prompt.promptHashes,
    });
    const evaluation = await input.evaluator.evaluate({
      target: input.target,
      sample: input.sample,
      acceptedOutputRef: execution.acceptedOutputRef,
    });
    await input.repository.putRun(
      PromptExperimentRunSchema.parse({
        ...definition,
        status: "COMPLETE",
        agentOutputRef: execution.acceptedOutputRef,
        metrics: mergedMetrics(evaluation.normalizedScore, evaluation.metrics),
        failureCaseRefs: [...(evaluation.failureCaseRefs ?? [])].sort(),
        traceRef: execution.traceRef ?? null,
        effectiveInputHash: execution.effectiveInputHash ?? null,
        errorCode: null,
        startedAt,
        completedAt: input.now(),
      }),
    );
  } catch (error) {
    await input.repository.putRun(
      PromptExperimentRunSchema.parse({
        ...definition,
        status: "FAILED",
        agentOutputRef: null,
        metrics: {},
        failureCaseRefs: [],
        traceRef: null,
        effectiveInputHash: null,
        errorCode: errorCode(error),
        startedAt,
        completedAt: input.now(),
      }),
    );
    throw error;
  }
}

function aggregateRuns(
  partition: "VALIDATION" | "HOLDOUT",
  runs: ReadonlyArray<PromptExperimentRun>,
): { metrics: Record<string, number>; failureCaseRefs: string[] } {
  const complete = runs
    .filter((run) => run.partition === partition && run.status === "COMPLETE")
    .sort((left, right) =>
      `${left.sampleId}:${left.seed}:${left.side}`.localeCompare(
        `${right.sampleId}:${right.seed}:${right.side}`,
      ),
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
  for (const key of [...pairs.keys()].sort()) {
    const pair = pairs.get(key);
    const champion = pair?.CHAMPION?.metrics.normalized_score;
    const candidate = pair?.CANDIDATE?.metrics.normalized_score;
    if (champion === undefined || candidate === undefined) {
      throw new Error("prompt_experiment_pair_score_missing");
    }
    championScores.push(champion);
    candidateScores.push(candidate);
    deltas.push(candidate - champion);
  }
  const mean = (values: ReadonlyArray<number>) =>
    values.reduce((sum, value) => sum + value, 0) / values.length;
  const prefix = partition.toLowerCase();
  return {
    metrics: {
      [`${prefix}_candidate_mean`]: mean(candidateScores),
      [`${prefix}_champion_mean`]: mean(championScores),
      [`${prefix}_paired_delta`]: mean(deltas),
      [`${prefix}_pair_count`]: pairs.size,
    },
    failureCaseRefs: [...new Set(complete.flatMap((run) => run.failureCaseRefs))].sort(),
  };
}

export async function runPromptExperimentPartition(
  rawInput: RunPromptExperimentPartitionInput,
): Promise<PromptExperiment> {
  const input = {
    ...rawInput,
    candidate: PromptCandidateSchema.parse(rawInput.candidate),
    experiment: PromptExperimentSchema.parse(rawInput.experiment),
    split: DatasetSplitManifestSchema.parse(rawInput.split),
    promptBinding: {
      champion: {
        promptRefs: PromptRefPairSchema.parse(rawInput.promptBinding.champion.promptRefs),
        promptHashes: PromptHashPairSchema.parse(rawInput.promptBinding.champion.promptHashes),
      },
      candidate: {
        promptRefs: PromptRefPairSchema.parse(rawInput.promptBinding.candidate.promptRefs),
        promptHashes: PromptHashPairSchema.parse(rawInput.promptBinding.candidate.promptHashes),
      },
    },
  };
  assertBindings(input);
  await input.repository.putCandidate(input.candidate);
  const persisted = await input.repository.getExperiment(input.experiment.experimentId);
  if (persisted !== null) assertPersistedExperimentMatches(input.experiment, persisted);
  let experiment = persisted ?? (await input.repository.putExperiment(input.experiment));
  const now = input.now ?? (() => new Date().toISOString());
  if (input.partition === "VALIDATION") {
    if (experiment.status === "PENDING") {
      experiment = await input.repository.putExperiment({
        ...experiment,
        status: "VALIDATION_RUNNING",
      });
    } else if (experiment.status === "VALIDATION_COMPLETE") {
      return experiment;
    } else if (experiment.status !== "VALIDATION_RUNNING") {
      throw new Error(`prompt_experiment_validation_state_invalid:${experiment.status}`);
    }
  } else {
    if (experiment.status === "VALIDATION_COMPLETE") {
      experiment = await input.repository.putExperiment({
        ...experiment,
        status: "HOLDOUT_RUNNING",
        holdoutOpenedAt: now(),
      });
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
  await mapLimit(tasks, Math.max(1, input.maxConcurrency ?? 1), async (task) => {
    const existing = existingById.get(task.definition.runId);
    if (existing?.status === "COMPLETE") return;
    await executeRun({
      definition: existing ?? task.definition,
      sample: task.sample,
      target: experiment.target,
      binding: input.promptBinding,
      repository: input.repository,
      executor: input.executor,
      evaluator: input.evaluator,
      now,
    });
  });
  const allRuns = await input.repository.listRuns(experiment.experimentId);
  const expectedIds = new Set(tasks.map((task) => task.definition.runId));
  const partitionRuns = allRuns.filter((run) => expectedIds.has(run.runId));
  if (
    partitionRuns.length !== expectedIds.size ||
    partitionRuns.some((run) => run.status !== "COMPLETE")
  ) {
    throw new Error("prompt_experiment_partition_incomplete");
  }
  const aggregate = aggregateRuns(input.partition, partitionRuns);
  const runIds = [
    ...new Set([...experiment.runIds, ...partitionRuns.map((run) => run.runId)]),
  ].sort();
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
      ].sort(),
      status: input.partition === "VALIDATION" ? "VALIDATION_COMPLETE" : "COMPLETE",
      completedAt: input.partition === "HOLDOUT" ? now() : null,
    }),
  );
}

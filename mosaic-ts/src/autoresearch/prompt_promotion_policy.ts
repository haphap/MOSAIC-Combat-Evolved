import { createHash } from "node:crypto";
import { z } from "zod";
import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";
import { OUTCOME_LABEL_REGISTRY } from "./outcome_registry.js";
import {
  type DatasetSplitManifest,
  DatasetSplitManifestSchema,
  type PromptCandidateFamily,
  PromptCandidateFamilySchema,
  type PromptExperiment,
  type PromptExperimentRun,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
  type PromptOptimizerTarget,
  type PromptPromotionDecision,
  PromptPromotionDecisionSchema,
} from "./prompt_optimizer_contract.js";

const NonEmptyId = z.string().trim().min(1).max(256);
const Probability = z.number().finite().positive().max(0.5);

/** Values live in the private policy package; only its version and hash are persisted. */
export const PromptPromotionPolicySchema = z
  .object({
    policyVersion: NonEmptyId,
    minimumMatureSamples: z.number().int().min(30),
    minimumRepeatSeeds: z.number().int().min(2),
    minimumPairedDelta: z.number().finite(),
    familyAlpha: Probability,
    bootstrapSamples: z.number().int().min(99),
    blockLength: z.number().int().positive(),
    tailQuantile: z.number().finite().positive().max(0.5),
    minimumTailDelta: z.number().finite(),
    maximumFailureRateIncrease: z.number().finite().nonnegative(),
    criticalValidationSampleIds: z.array(NonEmptyId),
    criticalHoldoutSampleIds: z.array(NonEmptyId),
    minimumCriticalSampleDelta: z.number().finite(),
  })
  .strict()
  .superRefine((policy, ctx) => {
    for (const key of ["criticalValidationSampleIds", "criticalHoldoutSampleIds"] as const) {
      if (new Set(policy[key]).size !== policy[key].length) {
        ctx.addIssue({
          code: "custom",
          path: [key],
          message: "critical sample IDs must be unique",
        });
      }
    }
  });

export type PromptPromotionPolicy = z.infer<typeof PromptPromotionPolicySchema>;

export interface PromptEvaluationBinding {
  agentId: string;
  evaluationObject: string;
  evaluationObjectSchemaVersion: string;
  primaryLabelId: string;
  scoringContractVersion: string;
  outcomeContractVersion: string;
  maturityHorizon: string;
  rankScope: string;
  labelOwner: "DETERMINISTIC_RUNTIME";
}

export function promptEvaluationBinding(target: PromptOptimizerTarget): PromptEvaluationBinding {
  const contract = OUTCOME_LABEL_REGISTRY[target.agentId];
  if (!contract || contract.agent_id !== target.agentId) {
    throw new Error(`prompt_promotion_outcome_contract_missing:${target.agentId}`);
  }
  return {
    agentId: contract.agent_id,
    evaluationObject: contract.evaluation_object,
    evaluationObjectSchemaVersion: contract.evaluation_object_schema_version,
    primaryLabelId: contract.primary_label_id,
    scoringContractVersion: contract.scoring_contract_version,
    outcomeContractVersion: contract.outcome_contract_version,
    maturityHorizon: contract.maturity_horizon,
    rankScope: contract.rank_scope,
    labelOwner: contract.label_owner,
  };
}

const FAILURE_METRICS = ["schema_failure", "contract_failure", "tool_failure"] as const;

interface PairedRow {
  sampleId: string;
  seed: number;
  champion: PromptExperimentRun;
  candidate: PromptExperimentRun;
}

interface PartitionEvidence {
  metrics: Record<string, number>;
  reasons: string[];
}

function seedFromString(value: string): number {
  return Number.parseInt(createHash("sha256").update(value).digest("hex").slice(0, 8), 16);
}

function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function mean(values: ReadonlyArray<number>): number {
  if (values.length === 0) throw new Error("prompt_promotion_empty_metric_series");
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function quantile(sorted: ReadonlyArray<number>, probability: number): number {
  const position = (sorted.length - 1) * probability;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  const left = sorted[lower];
  const right = sorted[upper];
  if (left === undefined || right === undefined) throw new Error("prompt_promotion_quantile_empty");
  return left + (right - left) * (position - lower);
}

function blockBootstrap(input: {
  deltas: ReadonlyArray<number>;
  samples: number;
  blockLength: number;
  alpha: number;
  seed: string;
}): { lower: number; upper: number; pValue: number } {
  const random = mulberry32(seedFromString(input.seed));
  const means: number[] = [];
  for (let iteration = 0; iteration < input.samples; iteration += 1) {
    let sum = 0;
    let count = 0;
    while (count < input.deltas.length) {
      const start = Math.floor(random() * input.deltas.length);
      for (let offset = 0; offset < input.blockLength && count < input.deltas.length; offset += 1) {
        sum += input.deltas[(start + offset) % input.deltas.length] ?? 0;
        count += 1;
      }
    }
    means.push(sum / input.deltas.length);
  }
  means.sort((left, right) => left - right);
  return {
    lower: quantile(means, input.alpha),
    upper: quantile(means, 1 - input.alpha),
    pValue: (means.filter((value) => value <= 0).length + 1) / (means.length + 1),
  };
}

function pairedRows(input: {
  experiment: PromptExperiment;
  split: DatasetSplitManifest;
  runs: ReadonlyArray<PromptExperimentRun>;
  partition: "VALIDATION" | "HOLDOUT";
}): PairedRow[] {
  const samples =
    input.partition === "VALIDATION" ? input.split.validation.samples : input.split.holdout.samples;
  const expectedSamples = new Set(samples.map((sample) => sample.sampleId));
  const rows = input.runs.filter((run) => run.partition === input.partition);
  if (
    rows.some(
      (run) => run.experimentId !== input.experiment.experimentId || run.status !== "COMPLETE",
    )
  ) {
    throw new Error(`prompt_promotion_${input.partition.toLowerCase()}_run_incomplete`);
  }
  const expectedCount = expectedSamples.size * input.experiment.repeatSeeds.length * 2;
  if (rows.length !== expectedCount) {
    throw new Error(`prompt_promotion_${input.partition.toLowerCase()}_run_count_mismatch`);
  }
  const byKey = new Map<string, Partial<Record<"CHAMPION" | "CANDIDATE", PromptExperimentRun>>>();
  for (const run of rows) {
    if (!expectedSamples.has(run.sampleId) || !input.experiment.repeatSeeds.includes(run.seed)) {
      throw new Error(`prompt_promotion_${input.partition.toLowerCase()}_run_identity_mismatch`);
    }
    const key = `${run.sampleId}\0${run.seed}`;
    const pair = byKey.get(key) ?? {};
    if (pair[run.side]) throw new Error("prompt_promotion_duplicate_pair_side");
    pair[run.side] = run;
    byKey.set(key, pair);
  }
  return [...byKey.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, pair]) => {
      if (!pair.CHAMPION || !pair.CANDIDATE) throw new Error("prompt_promotion_pair_incomplete");
      const [sampleId, seedText] = key.split("\0");
      if (!sampleId || seedText === undefined) throw new Error("prompt_promotion_pair_key_invalid");
      return {
        sampleId,
        seed: Number(seedText),
        champion: pair.CHAMPION,
        candidate: pair.CANDIDATE,
      };
    });
}

function failureRate(runs: ReadonlyArray<PromptExperimentRun>): number {
  return mean(
    runs.map((run) => (FAILURE_METRICS.some((metric) => (run.metrics[metric] ?? 0) > 0) ? 1 : 0)),
  );
}

function evaluatePartition(input: {
  experiment: PromptExperiment;
  family: PromptCandidateFamily;
  split: DatasetSplitManifest;
  runs: ReadonlyArray<PromptExperimentRun>;
  policy: PromptPromotionPolicy;
  policyHash: string;
  partition: "VALIDATION" | "HOLDOUT";
}): PartitionEvidence {
  const prefix = input.partition.toLowerCase();
  const pairs = pairedRows(input);
  const grouped = new Map<string, number[]>();
  for (const pair of pairs) {
    const champion = pair.champion.metrics.normalized_score;
    const candidate = pair.candidate.metrics.normalized_score;
    if (champion === undefined || candidate === undefined) {
      throw new Error("prompt_promotion_normalized_score_missing");
    }
    const values = grouped.get(pair.sampleId) ?? [];
    values.push(candidate - champion);
    grouped.set(pair.sampleId, values);
  }
  const chronologicalSamples = [
    ...(input.partition === "VALIDATION"
      ? input.split.validation.samples
      : input.split.holdout.samples),
  ].sort((left, right) => {
    const start = Date.parse(left.eventWindow.startAt) - Date.parse(right.eventWindow.startAt);
    if (start !== 0) return start;
    return Date.parse(left.eventWindow.endAt) - Date.parse(right.eventWindow.endAt);
  });
  const sampleDeltas = chronologicalSamples.map((sample) => {
    const deltas = grouped.get(sample.sampleId);
    if (!deltas) throw new Error("prompt_promotion_sample_delta_missing");
    return { sampleId: sample.sampleId, delta: mean(deltas) };
  });
  const deltas = sampleDeltas.map((row) => row.delta);
  const adjustedAlpha = input.policy.familyAlpha / input.family.candidateIds.length;
  const bootstrap = blockBootstrap({
    deltas,
    samples: input.policy.bootstrapSamples,
    blockLength: input.policy.blockLength,
    alpha: adjustedAlpha,
    seed: `${input.experiment.experimentId}:${input.partition}:${input.policyHash}`,
  });
  const tailCount = Math.max(1, Math.ceil(deltas.length * input.policy.tailQuantile));
  const tailDelta = mean([...deltas].sort((left, right) => left - right).slice(0, tailCount));
  const championRuns = pairs.map((row) => row.champion);
  const candidateRuns = pairs.map((row) => row.candidate);
  const championFailureRate = failureRate(championRuns);
  const candidateFailureRate = failureRate(candidateRuns);
  const criticalIds =
    input.partition === "VALIDATION"
      ? input.policy.criticalValidationSampleIds
      : input.policy.criticalHoldoutSampleIds;
  const deltaBySample = new Map(sampleDeltas.map((row) => [row.sampleId, row.delta]));
  const criticalDeltas = criticalIds.map((sampleId) => {
    const delta = deltaBySample.get(sampleId);
    if (delta === undefined)
      throw new Error(`prompt_promotion_critical_sample_missing:${sampleId}`);
    return delta;
  });
  const criticalMinimum = criticalDeltas.length > 0 ? Math.min(...criticalDeltas) : 0;
  const reasons: string[] = [];
  if (sampleDeltas.length < input.policy.minimumMatureSamples)
    reasons.push(`${prefix}_sample_count`);
  if (input.experiment.repeatSeeds.length < input.policy.minimumRepeatSeeds) {
    reasons.push(`${prefix}_repeat_seed_count`);
  }
  if (mean(deltas) < input.policy.minimumPairedDelta) reasons.push(`${prefix}_paired_delta`);
  if (bootstrap.lower < input.policy.minimumPairedDelta) reasons.push(`${prefix}_confidence_lower`);
  if (bootstrap.pValue > adjustedAlpha) reasons.push(`${prefix}_multiple_comparison`);
  if (tailDelta < input.policy.minimumTailDelta) reasons.push(`${prefix}_tail_regression`);
  if (candidateFailureRate - championFailureRate > input.policy.maximumFailureRateIncrease) {
    reasons.push(`${prefix}_failure_rate_regression`);
  }
  if (criticalDeltas.length > 0 && criticalMinimum < input.policy.minimumCriticalSampleDelta) {
    reasons.push(`${prefix}_critical_suite_regression`);
  }
  return {
    reasons,
    metrics: {
      [`${prefix}_sample_count`]: sampleDeltas.length,
      [`${prefix}_repeat_seed_count`]: input.experiment.repeatSeeds.length,
      [`${prefix}_paired_delta`]: mean(deltas),
      [`${prefix}_confidence_lower`]: bootstrap.lower,
      [`${prefix}_confidence_upper`]: bootstrap.upper,
      [`${prefix}_bootstrap_p_value`]: bootstrap.pValue,
      [`${prefix}_adjusted_alpha`]: adjustedAlpha,
      [`${prefix}_tail_delta`]: tailDelta,
      [`${prefix}_champion_failure_rate`]: championFailureRate,
      [`${prefix}_candidate_failure_rate`]: candidateFailureRate,
      [`${prefix}_critical_min_delta`]: criticalMinimum,
    },
  };
}

export function createPromptPromotionDecision(input: {
  experiment: PromptExperiment;
  family: PromptCandidateFamily;
  split: DatasetSplitManifest;
  runs: ReadonlyArray<PromptExperimentRun>;
  policy: PromptPromotionPolicy;
  decidedAt: string;
}): PromptPromotionDecision {
  const experiment = PromptExperimentSchema.parse(input.experiment);
  const family = PromptCandidateFamilySchema.parse(input.family);
  const split = DatasetSplitManifestSchema.parse(input.split);
  const runs = input.runs.map((run) => PromptExperimentRunSchema.parse(run));
  const policy = PromptPromotionPolicySchema.parse(input.policy);
  if (experiment.status !== "COMPLETE" || experiment.holdoutOpenedAt === null) {
    throw new Error("prompt_promotion_experiment_not_complete");
  }
  if (
    family.status !== "COMPLETE" ||
    family.familyId !== experiment.familyId ||
    family.selectedCandidateId !== experiment.candidateId ||
    family.selectedExperimentId !== experiment.experimentId ||
    family.holdoutExperimentId !== experiment.experimentId
  ) {
    throw new Error("prompt_promotion_candidate_family_not_complete");
  }
  if (
    canonicalJsonHash(split) !== experiment.datasetSplitManifestHash ||
    canonicalJsonHash(split.target) !== canonicalJsonHash(experiment.target) ||
    split.validation.snapshotHash !== experiment.validationSnapshotHash ||
    split.holdout.snapshotHash !== experiment.holdoutSnapshotHash
  ) {
    throw new Error("prompt_promotion_split_drift");
  }
  const binding = promptEvaluationBinding(experiment.target);
  if (
    experiment.evaluatorVersion !== binding.scoringContractVersion ||
    split.evaluatorVersion !== binding.scoringContractVersion
  ) {
    throw new Error("prompt_promotion_agent_evaluator_drift");
  }
  if (runs.some((run) => !experiment.runIds.includes(run.runId))) {
    throw new Error("prompt_promotion_unbound_run");
  }
  if (new Set(experiment.runIds).size !== runs.length || experiment.runIds.length !== runs.length) {
    throw new Error("prompt_promotion_run_manifest_mismatch");
  }
  const policyHash = canonicalJsonHash(policy);
  const validation = evaluatePartition({
    experiment,
    family,
    split,
    runs,
    policy,
    policyHash,
    partition: "VALIDATION",
  });
  const holdout = evaluatePartition({
    experiment,
    family,
    split,
    runs,
    policy,
    policyHash,
    partition: "HOLDOUT",
  });
  const reasons = [...validation.reasons, ...holdout.reasons].sort();
  const decision = reasons.length === 0 ? "ELIGIBLE" : "REJECTED";
  const evidenceHash = canonicalJsonHash({
    experiment,
    family,
    split,
    runs: [...runs].sort((left, right) => left.runId.localeCompare(right.runId)),
    policyConfigHash: policyHash,
  });
  const decisionId = `decision-${canonicalJsonHash({ experimentId: experiment.experimentId, policyHash }).slice(7, 31)}`;
  return PromptPromotionDecisionSchema.parse({
    schemaVersion: "prompt_promotion_decision_v1",
    decisionId,
    experimentId: experiment.experimentId,
    familyId: family.familyId,
    candidateId: experiment.candidateId,
    policyVersion: policy.policyVersion,
    policyConfigHash: policyHash,
    decision,
    reasons: decision === "ELIGIBLE" ? ["all_promotion_gates_passed"] : reasons,
    metricSummary: { ...validation.metrics, ...holdout.metrics },
    evidenceHash,
    decidedAt: input.decidedAt,
  });
}

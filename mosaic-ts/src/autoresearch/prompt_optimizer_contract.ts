import { z } from "zod";
import {
  RUNTIME_AGENT_STAGE_IDS,
  RUNTIME_AGENT_STAGE_SPEC_BY_KEY,
  runtimeAgentStageKey,
} from "../agents/prompts/runtime_agent_spec.js";
import { AgentIdSchema } from "../agents/tool_contract.js";

export const PromptOptimizerSha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
export const PromptOptimizerGitCommitSchema = z.string().regex(/^[0-9a-f]{40}$/);
const IsoDateTimeSchema = z.iso.datetime({ offset: true });
const NonEmptyIdSchema = z.string().trim().min(1).max(256);
const PublicRefSchema = z
  .string()
  .trim()
  .min(1)
  .max(512)
  .regex(/^[^\r\n]+$/);
const PublicSummarySchema = z.string().trim().min(1).max(2_000);
const FiniteMetricRecordSchema = z.record(z.string().trim().min(1), z.number().finite());

export const PromptOptimizerTargetSchema = z
  .object({
    agentId: AgentIdSchema,
    stage: z.enum(RUNTIME_AGENT_STAGE_IDS),
    cohort: z.string().regex(/^cohort_[a-z0-9_]+$/),
  })
  .strict()
  .superRefine((target, ctx) => {
    if (!RUNTIME_AGENT_STAGE_SPEC_BY_KEY.has(runtimeAgentStageKey(target.agentId, target.stage))) {
      ctx.addIssue({
        code: "custom",
        path: ["stage"],
        message: `stage ${target.stage} does not belong to ${target.agentId}`,
      });
    }
  });

export type PromptOptimizerTarget = z.infer<typeof PromptOptimizerTargetSchema>;

export const PromptHashPairSchema = z
  .object({
    zh: PromptOptimizerSha256Schema,
    en: PromptOptimizerSha256Schema,
  })
  .strict();

export const PromptRefPairSchema = z
  .object({
    zh: PublicRefSchema,
    en: PublicRefSchema,
  })
  .strict();
export type PromptRefPair = z.infer<typeof PromptRefPairSchema>;

/**
 * The only KNOT input. It intentionally has no validation or holdout fields,
 * sample bodies, provider traces, Darwinian weights, or release authority.
 */
export const PromptTrainingSnapshotSchema = z
  .object({
    schemaVersion: z.literal("prompt_training_snapshot_v1"),
    target: PromptOptimizerTargetSchema,
    snapshotId: NonEmptyIdSchema,
    snapshotHash: PromptOptimizerSha256Schema,
    cutoffAt: IsoDateTimeSchema,
    outcomeContractVersion: NonEmptyIdSchema,
    evaluatorVersion: NonEmptyIdSchema,
    matureSampleCount: z.number().int().positive(),
    scoreSummary: FiniteMetricRecordSchema,
    failureCategoryCounts: z.record(z.string().trim().min(1), z.number().int().nonnegative()),
    tailFailureCaseRefs: z.array(PublicRefSchema).max(100),
    evidenceGapSummaries: z.array(PublicSummarySchema).max(100),
  })
  .strict();

export type PromptTrainingSnapshot = z.infer<typeof PromptTrainingSnapshotSchema>;

export const PromptCandidateSchema = z
  .object({
    schemaVersion: z.literal("prompt_candidate_v1"),
    candidateId: NonEmptyIdSchema,
    parentId: NonEmptyIdSchema,
    target: PromptOptimizerTargetSchema,
    promptRefs: PromptRefPairSchema,
    promptHashes: PromptHashPairSchema,
    trainingSnapshotId: NonEmptyIdSchema,
    trainingSnapshotHash: PromptOptimizerSha256Schema,
    mutatorConfigHash: PromptOptimizerSha256Schema,
    mutatorCommit: PromptOptimizerGitCommitSchema,
    mutationSummary: PublicSummarySchema,
    hypothesis: PublicSummarySchema,
    createdAt: IsoDateTimeSchema,
  })
  .strict();

export type PromptCandidate = z.infer<typeof PromptCandidateSchema>;

export const PromptDatasetSampleRefSchema = z
  .object({
    sampleId: NonEmptyIdSchema,
    inputRef: PublicRefSchema,
    outcomeRef: PublicRefSchema,
    eventWindow: z
      .object({ startAt: IsoDateTimeSchema, endAt: IsoDateTimeSchema })
      .strict()
      .refine((window) => window.startAt <= window.endAt, "event window must be ordered"),
    maturedAt: IsoDateTimeSchema,
  })
  .strict()
  .superRefine((sample, ctx) => {
    if (sample.maturedAt < sample.eventWindow.endAt) {
      ctx.addIssue({
        code: "custom",
        path: ["maturedAt"],
        message: "outcome cannot mature before its event window ends",
      });
    }
  });
export type PromptDatasetSampleRef = z.infer<typeof PromptDatasetSampleRefSchema>;

const DatasetPartitionSchema = z
  .object({
    snapshotId: NonEmptyIdSchema,
    snapshotHash: PromptOptimizerSha256Schema,
    windowStartAt: IsoDateTimeSchema,
    windowEndAt: IsoDateTimeSchema,
    samples: z.array(PromptDatasetSampleRefSchema).min(1),
  })
  .strict()
  .superRefine((partition, ctx) => {
    if (partition.windowStartAt > partition.windowEndAt) {
      ctx.addIssue({ code: "custom", message: "partition window must be ordered" });
    }
    for (const [index, sample] of partition.samples.entries()) {
      if (
        sample.eventWindow.startAt < partition.windowStartAt ||
        sample.eventWindow.endAt > partition.windowEndAt
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["samples", index, "eventWindow"],
          message: "sample event window must be contained in its partition",
        });
      }
    }
  });

export const DatasetSplitManifestSchema = z
  .object({
    schemaVersion: z.literal("prompt_dataset_split_v1"),
    splitId: NonEmptyIdSchema,
    target: PromptOptimizerTargetSchema,
    cutoffAt: IsoDateTimeSchema,
    training: DatasetPartitionSchema,
    validation: DatasetPartitionSchema,
    holdout: DatasetPartitionSchema,
    evaluatorVersion: NonEmptyIdSchema,
    createdAt: IsoDateTimeSchema,
  })
  .strict()
  .superRefine((manifest, ctx) => {
    if (manifest.training.windowEndAt !== manifest.cutoffAt) {
      ctx.addIssue({
        code: "custom",
        path: ["cutoffAt"],
        message: "cutoffAt must equal the training window end",
      });
    }
    if (
      manifest.training.windowEndAt >= manifest.validation.windowStartAt ||
      manifest.validation.windowEndAt >= manifest.holdout.windowStartAt
    ) {
      ctx.addIssue({
        code: "custom",
        message: "training, validation, and holdout windows must be strictly ordered",
      });
    }
    const seen = new Set<string>();
    for (const partition of ["training", "validation", "holdout"] as const) {
      for (const [index, sample] of manifest[partition].samples.entries()) {
        if (seen.has(sample.sampleId)) {
          ctx.addIssue({
            code: "custom",
            path: [partition, "samples", index, "sampleId"],
            message: "sample IDs cannot overlap across partitions",
          });
        }
        seen.add(sample.sampleId);
        if (sample.maturedAt > manifest.createdAt) {
          ctx.addIssue({
            code: "custom",
            path: [partition, "samples", index, "maturedAt"],
            message: "split manifest cannot include an immature outcome",
          });
        }
      }
    }
  });

export type DatasetSplitManifest = z.infer<typeof DatasetSplitManifestSchema>;

export const PromptExperimentStatusSchema = z.enum([
  "PENDING",
  "VALIDATION_RUNNING",
  "VALIDATION_COMPLETE",
  "HOLDOUT_RUNNING",
  "COMPLETE",
  "FAILED",
]);

export const PromptExperimentSchema = z
  .object({
    schemaVersion: z.literal("prompt_experiment_v1"),
    experimentId: NonEmptyIdSchema,
    candidateId: NonEmptyIdSchema,
    championId: NonEmptyIdSchema,
    target: PromptOptimizerTargetSchema,
    championPromptHashes: PromptHashPairSchema,
    candidatePromptHashes: PromptHashPairSchema,
    datasetSplitManifestHash: PromptOptimizerSha256Schema,
    validationSnapshotHash: PromptOptimizerSha256Schema,
    holdoutSnapshotHash: PromptOptimizerSha256Schema,
    modelConfigHash: PromptOptimizerSha256Schema,
    toolConfigHash: PromptOptimizerSha256Schema,
    evaluatorVersion: NonEmptyIdSchema,
    evaluatorConfigHash: PromptOptimizerSha256Schema,
    codeCommit: PromptOptimizerGitCommitSchema,
    repeatSeeds: z.array(z.number().int().nonnegative()).min(1),
    runIds: z.array(NonEmptyIdSchema),
    metrics: FiniteMetricRecordSchema,
    tailFailureCaseRefs: z.array(PublicRefSchema).max(500),
    status: PromptExperimentStatusSchema,
    holdoutOpenedAt: IsoDateTimeSchema.nullable(),
    createdAt: IsoDateTimeSchema,
    completedAt: IsoDateTimeSchema.nullable(),
  })
  .strict()
  .superRefine((experiment, ctx) => {
    if (new Set(experiment.repeatSeeds).size !== experiment.repeatSeeds.length) {
      ctx.addIssue({
        code: "custom",
        path: ["repeatSeeds"],
        message: "repeat seeds must be unique",
      });
    }
    const holdoutMustBeOpen = ["HOLDOUT_RUNNING", "COMPLETE"].includes(experiment.status);
    const holdoutMustBeClosed = ["PENDING", "VALIDATION_RUNNING", "VALIDATION_COMPLETE"].includes(
      experiment.status,
    );
    if (
      (holdoutMustBeOpen && experiment.holdoutOpenedAt === null) ||
      (holdoutMustBeClosed && experiment.holdoutOpenedAt !== null)
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["holdoutOpenedAt"],
        message: "holdout timestamp must match experiment state",
      });
    }
    const terminal = ["COMPLETE", "FAILED"].includes(experiment.status);
    if (terminal !== (experiment.completedAt !== null)) {
      ctx.addIssue({
        code: "custom",
        path: ["completedAt"],
        message: "completion timestamp must match terminal state",
      });
    }
  });

export type PromptExperiment = z.infer<typeof PromptExperimentSchema>;

export const PromptExperimentRunSchema = z
  .object({
    schemaVersion: z.literal("prompt_experiment_run_v1"),
    runId: NonEmptyIdSchema,
    experimentId: NonEmptyIdSchema,
    partition: z.enum(["VALIDATION", "HOLDOUT"]),
    side: z.enum(["CHAMPION", "CANDIDATE"]),
    sampleId: NonEmptyIdSchema,
    seed: z.number().int().nonnegative(),
    status: z.enum(["PENDING", "RUNNING", "COMPLETE", "FAILED"]),
    agentOutputRef: PublicRefSchema.nullable(),
    metrics: FiniteMetricRecordSchema,
    failureCaseRefs: z.array(PublicRefSchema).max(100),
    traceRef: PublicRefSchema.nullable(),
    effectiveInputHash: PromptOptimizerSha256Schema.nullable(),
    errorCode: NonEmptyIdSchema.nullable(),
    startedAt: IsoDateTimeSchema.nullable(),
    completedAt: IsoDateTimeSchema.nullable(),
  })
  .strict()
  .superRefine((run, ctx) => {
    if (run.status === "PENDING" && (run.startedAt !== null || run.completedAt !== null)) {
      ctx.addIssue({ code: "custom", message: "pending run cannot have timestamps" });
    }
    if (run.status === "RUNNING" && (run.startedAt === null || run.completedAt !== null)) {
      ctx.addIssue({ code: "custom", message: "running run requires only startedAt" });
    }
    if (run.status === "COMPLETE") {
      if (
        run.startedAt === null ||
        run.completedAt === null ||
        run.agentOutputRef === null ||
        !("normalized_score" in run.metrics) ||
        run.errorCode !== null
      ) {
        ctx.addIssue({
          code: "custom",
          message: "complete run is missing accepted output or score",
        });
      }
    }
    if (run.status === "FAILED") {
      if (run.startedAt === null || run.completedAt === null || run.errorCode === null) {
        ctx.addIssue({ code: "custom", message: "failed run requires timestamps and errorCode" });
      }
    }
  });

export type PromptExperimentRun = z.infer<typeof PromptExperimentRunSchema>;

export const PromptPromotionDecisionSchema = z
  .object({
    schemaVersion: z.literal("prompt_promotion_decision_v1"),
    decisionId: NonEmptyIdSchema,
    experimentId: NonEmptyIdSchema,
    candidateId: NonEmptyIdSchema,
    policyVersion: NonEmptyIdSchema,
    policyConfigHash: PromptOptimizerSha256Schema,
    decision: z.enum(["ELIGIBLE", "REJECTED"]),
    reasons: z.array(NonEmptyIdSchema).min(1),
    metricSummary: FiniteMetricRecordSchema,
    decidedAt: IsoDateTimeSchema,
  })
  .strict();

export type PromptPromotionDecision = z.infer<typeof PromptPromotionDecisionSchema>;

export function assertCandidateMatchesTrainingSnapshot(
  candidate: PromptCandidate,
  training: PromptTrainingSnapshot,
): void {
  if (
    JSON.stringify(candidate.target) !== JSON.stringify(training.target) ||
    candidate.trainingSnapshotId !== training.snapshotId ||
    candidate.trainingSnapshotHash !== training.snapshotHash
  ) {
    throw new Error("candidate_training_snapshot_mismatch");
  }
}

export function assertCandidateMatchesSplit(
  candidate: PromptCandidate,
  split: DatasetSplitManifest,
): void {
  if (
    JSON.stringify(candidate.target) !== JSON.stringify(split.target) ||
    candidate.trainingSnapshotId !== split.training.snapshotId ||
    candidate.trainingSnapshotHash !== split.training.snapshotHash
  ) {
    throw new Error("candidate_dataset_split_mismatch");
  }
}

export const PROMPT_OPTIMIZER_PUBLIC_SCHEMAS = Object.freeze({
  prompt_candidate_v1: PromptCandidateSchema,
  prompt_dataset_split_v1: DatasetSplitManifestSchema,
  prompt_experiment_v1: PromptExperimentSchema,
  prompt_experiment_run_v1: PromptExperimentRunSchema,
  prompt_promotion_decision_v1: PromptPromotionDecisionSchema,
});

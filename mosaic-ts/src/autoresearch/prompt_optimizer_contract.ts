import { z } from "zod";
import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";
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
const SafePublicVersionSchema = z
  .string()
  .trim()
  .regex(/^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$/);
const FiniteMetricRecordSchema = z.record(z.string().trim().min(1), z.number().finite());
const BehaviorFacetFeedbackSchema = z
  .object({
    matureSampleCount: z.number().int().min(30),
    meanScore: z.number().finite().min(-1).max(1),
    lowerTailScore: z.number().finite().min(-1).max(1),
    failureCategoryCounts: z.record(z.string().trim().min(1), z.number().int().nonnegative()),
  })
  .strict();

function instant(value: string): number {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) throw new Error(`invalid ISO datetime: ${value}`);
  return parsed;
}

export const PromptMutationCategorySchema = z.enum([
  "EVIDENCE_PRIORITY",
  "TEMPORAL_DISCIPLINE",
  "CONFLICT_RESOLUTION",
  "TRANSMISSION_CLARITY",
  "UNCERTAINTY_CALIBRATION",
  "TAIL_RISK_CONTROL",
]);
export type PromptMutationCategory = z.infer<typeof PromptMutationCategorySchema>;

export function promptMutationSummary(categories: ReadonlyArray<PromptMutationCategory>): string {
  return `Behavior focus: ${categories.join(", ")}.`;
}

export function promptMutationHypothesis(
  categories: ReadonlyArray<PromptMutationCategory>,
): string {
  return `Preregistered hypothesis: ${categories.join(", ")} improves the frozen Agent outcome score.`;
}

export function promptBehaviorAlignmentHash(input: {
  promptHashes: { zh: string; en: string };
  alignmentVerifierVersion: string;
}): string {
  return canonicalJsonHash({
    alignmentVerifierVersion: input.alignmentVerifierVersion,
    promptHashes: input.promptHashes,
  });
}

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
    datasetSnapshotHash: PromptOptimizerSha256Schema,
    cutoffAt: IsoDateTimeSchema,
    outcomeContractVersion: NonEmptyIdSchema,
    evaluatorVersion: NonEmptyIdSchema,
    matureSampleCount: z.number().int().min(30),
    scoreSummary: FiniteMetricRecordSchema,
    failureCategoryCounts: z.record(z.string().trim().min(1), z.number().int().nonnegative()),
    tailFailureCaseRefs: z.array(PublicRefSchema).max(100),
    evidenceGapSummaries: z.array(PublicSummarySchema).max(100),
    behaviorFeedback: z
      .object({
        contractHash: PromptOptimizerSha256Schema,
        facets: z.record(z.string().regex(/^[a-z][a-z0-9_]*$/), BehaviorFacetFeedbackSchema),
      })
      .strict(),
  })
  .strict()
  .superRefine((snapshot, ctx) => {
    const { snapshotHash, ...body } = snapshot;
    if (snapshotHash !== canonicalJsonHash(body)) {
      ctx.addIssue({
        code: "custom",
        path: ["snapshotHash"],
        message: "training snapshot hash must bind the complete training projection",
      });
    }
    if (Object.keys(snapshot.behaviorFeedback.facets).length === 0) {
      ctx.addIssue({
        code: "custom",
        path: ["behaviorFeedback", "facets"],
        message: "behavior feedback must cover at least one role facet",
      });
    }
    for (const [facetId, feedback] of Object.entries(snapshot.behaviorFeedback.facets)) {
      if (feedback.matureSampleCount !== snapshot.matureSampleCount) {
        ctx.addIssue({
          code: "custom",
          path: ["behaviorFeedback", "facets", facetId, "matureSampleCount"],
          message: "every facet must use the complete mature training sample set",
        });
      }
    }
  });

export type PromptTrainingSnapshot = z.infer<typeof PromptTrainingSnapshotSchema>;

export const PromptCandidateSchema = z
  .object({
    schemaVersion: z.literal("prompt_candidate_v1"),
    candidateId: NonEmptyIdSchema,
    parentId: NonEmptyIdSchema,
    parentPromptCommit: PromptOptimizerGitCommitSchema,
    parentPromptHashes: PromptHashPairSchema,
    target: PromptOptimizerTargetSchema,
    promptRefs: PromptRefPairSchema,
    promptHashes: PromptHashPairSchema,
    trainingSnapshotId: NonEmptyIdSchema,
    trainingSnapshotHash: PromptOptimizerSha256Schema,
    mutatorConfigHash: PromptOptimizerSha256Schema,
    mutatorCommit: PromptOptimizerGitCommitSchema,
    mutationCategories: z.array(PromptMutationCategorySchema).min(1).max(6),
    mutationSummary: PublicSummarySchema,
    hypothesis: PublicSummarySchema,
    alignmentVerifierVersion: SafePublicVersionSchema,
    behaviorAlignmentHash: PromptOptimizerSha256Schema,
    behaviorContractHash: PromptOptimizerSha256Schema,
    createdAt: IsoDateTimeSchema,
  })
  .strict()
  .superRefine((candidate, ctx) => {
    const sorted = [...new Set(candidate.mutationCategories)].sort();
    if (JSON.stringify(sorted) !== JSON.stringify(candidate.mutationCategories)) {
      ctx.addIssue({
        code: "custom",
        path: ["mutationCategories"],
        message: "mutation categories must be unique and sorted",
      });
    }
    if (candidate.mutationSummary !== promptMutationSummary(candidate.mutationCategories)) {
      ctx.addIssue({
        code: "custom",
        path: ["mutationSummary"],
        message: "mutation summary must be the safe category projection",
      });
    }
    if (candidate.hypothesis !== promptMutationHypothesis(candidate.mutationCategories)) {
      ctx.addIssue({
        code: "custom",
        path: ["hypothesis"],
        message: "hypothesis must be the safe category projection",
      });
    }
    if (
      candidate.behaviorAlignmentHash !==
      promptBehaviorAlignmentHash({
        promptHashes: candidate.promptHashes,
        alignmentVerifierVersion: candidate.alignmentVerifierVersion,
      })
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["behaviorAlignmentHash"],
        message: "alignment hash must bind the verifier and Prompt hashes",
      });
    }
  });

export type PromptCandidate = z.infer<typeof PromptCandidateSchema>;

export const PromptDatasetSampleRefSchema = z
  .object({
    sampleId: NonEmptyIdSchema,
    inputRef: PublicRefSchema,
    outcomeRef: PublicRefSchema,
    eventWindow: z
      .object({ startAt: IsoDateTimeSchema, endAt: IsoDateTimeSchema })
      .strict()
      .refine(
        (window) => instant(window.startAt) <= instant(window.endAt),
        "event window must be ordered",
      ),
    maturedAt: IsoDateTimeSchema,
  })
  .strict()
  .superRefine((sample, ctx) => {
    if (instant(sample.maturedAt) < instant(sample.eventWindow.endAt)) {
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
    if (instant(partition.windowStartAt) > instant(partition.windowEndAt)) {
      ctx.addIssue({ code: "custom", message: "partition window must be ordered" });
    }
    const eventWindows = new Set<string>();
    for (const [index, sample] of partition.samples.entries()) {
      if (
        instant(sample.eventWindow.startAt) < instant(partition.windowStartAt) ||
        instant(sample.eventWindow.endAt) > instant(partition.windowEndAt)
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["samples", index, "eventWindow"],
          message: "sample event window must be contained in its partition",
        });
      }
      const eventWindow = `${instant(sample.eventWindow.startAt)}:${instant(sample.eventWindow.endAt)}`;
      if (eventWindows.has(eventWindow)) {
        ctx.addIssue({
          code: "custom",
          path: ["samples", index, "eventWindow"],
          message: "sample event windows must define an unambiguous chronological order",
        });
      }
      eventWindows.add(eventWindow);
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
    if (instant(manifest.training.windowEndAt) !== instant(manifest.cutoffAt)) {
      ctx.addIssue({
        code: "custom",
        path: ["cutoffAt"],
        message: "cutoffAt must equal the training window end",
      });
    }
    if (
      instant(manifest.training.windowEndAt) >= instant(manifest.validation.windowStartAt) ||
      instant(manifest.validation.windowEndAt) >= instant(manifest.holdout.windowStartAt)
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
        if (instant(sample.maturedAt) > instant(manifest.createdAt)) {
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

export const PromptCandidateFamilyStatusSchema = z.enum(["REGISTERED", "SELECTED", "COMPLETE"]);

export const PromptCandidateFamilySchema = z
  .object({
    schemaVersion: z.literal("prompt_candidate_family_v1"),
    familyId: NonEmptyIdSchema,
    target: PromptOptimizerTargetSchema,
    championReleaseId: NonEmptyIdSchema,
    championPromptCommit: PromptOptimizerGitCommitSchema,
    championPromptRefs: PromptRefPairSchema,
    championPromptHashes: PromptHashPairSchema,
    datasetSplitId: NonEmptyIdSchema,
    datasetSplitManifestHash: PromptOptimizerSha256Schema,
    candidateIds: z.array(NonEmptyIdSchema).min(1),
    validationExperimentIds: z.array(NonEmptyIdSchema),
    selectedCandidateId: NonEmptyIdSchema.nullable(),
    selectedExperimentId: NonEmptyIdSchema.nullable(),
    holdoutExperimentId: NonEmptyIdSchema.nullable(),
    status: PromptCandidateFamilyStatusSchema,
    createdAt: IsoDateTimeSchema,
    updatedAt: IsoDateTimeSchema,
  })
  .strict()
  .superRefine((family, ctx) => {
    for (const key of ["candidateIds", "validationExperimentIds"] as const) {
      const sorted = [...new Set(family[key])].sort();
      if (JSON.stringify(sorted) !== JSON.stringify(family[key])) {
        ctx.addIssue({ code: "custom", path: [key], message: `${key} must be unique and sorted` });
      }
    }
    if (instant(family.updatedAt) < instant(family.createdAt)) {
      ctx.addIssue({
        code: "custom",
        path: ["updatedAt"],
        message: "updatedAt precedes createdAt",
      });
    }
    const selected = family.status !== "REGISTERED";
    if (
      selected !== (family.selectedCandidateId !== null && family.selectedExperimentId !== null)
    ) {
      ctx.addIssue({ code: "custom", message: "selected family state requires one winner" });
    }
    if (family.status === "REGISTERED" && family.validationExperimentIds.length !== 0) {
      ctx.addIssue({
        code: "custom",
        message: "registered family cannot claim validation completion",
      });
    }
    if (selected) {
      if (!family.candidateIds.includes(family.selectedCandidateId ?? "")) {
        ctx.addIssue({
          code: "custom",
          path: ["selectedCandidateId"],
          message: "winner not in family",
        });
      }
      if (!family.validationExperimentIds.includes(family.selectedExperimentId ?? "")) {
        ctx.addIssue({
          code: "custom",
          path: ["selectedExperimentId"],
          message: "winner experiment missing",
        });
      }
      if (family.validationExperimentIds.length !== family.candidateIds.length) {
        ctx.addIssue({
          code: "custom",
          message: "selection requires one validation experiment per Candidate",
        });
      }
    }
    if ((family.status === "COMPLETE") !== (family.holdoutExperimentId !== null)) {
      ctx.addIssue({
        code: "custom",
        path: ["holdoutExperimentId"],
        message: "complete family requires consumed holdout",
      });
    }
  });

export type PromptCandidateFamily = z.infer<typeof PromptCandidateFamilySchema>;

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
    familyId: NonEmptyIdSchema,
    candidateId: NonEmptyIdSchema,
    championId: NonEmptyIdSchema,
    target: PromptOptimizerTargetSchema,
    championPromptCommit: PromptOptimizerGitCommitSchema,
    championPromptRefs: PromptRefPairSchema,
    championPromptHashes: PromptHashPairSchema,
    candidatePromptRefs: PromptRefPairSchema,
    candidatePromptHashes: PromptHashPairSchema,
    datasetSplitId: NonEmptyIdSchema,
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
    familyId: NonEmptyIdSchema,
    candidateId: NonEmptyIdSchema,
    policyVersion: NonEmptyIdSchema,
    policyConfigHash: PromptOptimizerSha256Schema,
    decision: z.enum(["ELIGIBLE", "REJECTED"]),
    reasons: z.array(NonEmptyIdSchema).min(1),
    metricSummary: FiniteMetricRecordSchema,
    evidenceHash: PromptOptimizerSha256Schema,
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
    candidate.trainingSnapshotHash !== training.snapshotHash ||
    candidate.behaviorContractHash !== training.behaviorFeedback.contractHash
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
  prompt_training_snapshot_v1: PromptTrainingSnapshotSchema,
  prompt_candidate_v1: PromptCandidateSchema,
  prompt_candidate_family_v1: PromptCandidateFamilySchema,
  prompt_dataset_split_v1: DatasetSplitManifestSchema,
  prompt_experiment_v1: PromptExperimentSchema,
  prompt_experiment_run_v1: PromptExperimentRunSchema,
  prompt_promotion_decision_v1: PromptPromotionDecisionSchema,
});

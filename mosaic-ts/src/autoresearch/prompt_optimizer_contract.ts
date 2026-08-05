import { z } from "zod";
import { canonicalJsonHash, compareCanonicalStrings } from "../agents/helpers/canonical_json.js";
import {
  RUNTIME_AGENT_STAGE_IDS,
  RUNTIME_AGENT_STAGE_SPEC_BY_KEY,
  runtimeAgentStageKey,
} from "../agents/prompts/runtime_agent_spec.js";
import { AgentIdSchema } from "../agents/tool_contract.js";

export const PromptOptimizerSha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
export const PromptOptimizerGitCommitSchema = z.string().regex(/^[0-9a-f]{40}$/);
const IsoDateTimeSchema = z.union([
  z.iso.datetime({ offset: true, precision: 0 }),
  z.iso.datetime({ offset: true, precision: 1 }),
  z.iso.datetime({ offset: true, precision: 2 }),
  z.iso.datetime({ offset: true, precision: 3 }),
]);
const PROMPT_OPTIMIZER_CANONICAL_STRING_PATTERN_SOURCE = String.raw`^(?![\u0009-\u000d\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff])[\s\S]*[^\u0009-\u000d\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff](?![\s\S])`;
export const PROMPT_OPTIMIZER_CANONICAL_STRING_PATTERN = new RegExp(
  PROMPT_OPTIMIZER_CANONICAL_STRING_PATTERN_SOURCE,
);

function canonicalNonEmptyString(maxLength?: number) {
  const schema = maxLength === undefined ? z.string().min(1) : z.string().min(1).max(maxLength);
  return schema.regex(
    PROMPT_OPTIMIZER_CANONICAL_STRING_PATTERN,
    "surrounding whitespace is not canonical",
  );
}

const NonEmptyIdSchema = canonicalNonEmptyString(256);
const PublicRefSchema = canonicalNonEmptyString(512).regex(/^[^\r\n]+$/);
const PublicSummarySchema = canonicalNonEmptyString(2_000);
const SafePublicVersionSchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$/);
const FiniteMetricRecordSchema = z.record(canonicalNonEmptyString(), z.number().finite());
const UnitScoreSchema = z.number().finite().min(-1).max(1);

function instant(value: string): number {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) throw new Error(`invalid ISO datetime: ${value}`);
  return parsed;
}

function contentId(prefix: string, value: unknown): string {
  return `${prefix}-${canonicalJsonHash(value).slice("sha256:".length)}`;
}

function withoutKeys(value: object, keys: ReadonlySet<string>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([key]) => !keys.has(key)));
}

export function promptDatasetSampleId(sample: {
  inputHash: string;
  outcomeHash: string;
  eventWindow: { startAt: string; endAt: string };
  maturedAt: string;
}): string {
  return contentId("sample", {
    eventWindow: sample.eventWindow,
    inputHash: sample.inputHash,
    maturedAt: sample.maturedAt,
    outcomeHash: sample.outcomeHash,
  });
}

export function promptDatasetPartitionSnapshotHash(partition: {
  samples: ReadonlyArray<{ sampleId: string }>;
}): string {
  return canonicalJsonHash(partition.samples.map((sample) => sample.sampleId).sort());
}

export function promptDatasetSplitId(split: object): string {
  return contentId("split", withoutKeys(split, new Set(["splitId", "createdAt"])));
}

export function promptCandidateFamilyId(family: object): string {
  return contentId("family", withoutKeys(family, new Set(["familyId", "createdAt"])));
}

export function promptExperimentId(experiment: object): string {
  return contentId(
    "experiment",
    withoutKeys(
      experiment,
      new Set([
        "experimentId",
        "runIds",
        "metrics",
        "tailFailureCaseRefs",
        "status",
        "holdoutOpenedAt",
        "createdAt",
        "completedAt",
      ]),
    ),
  );
}

export function promptExperimentRunId(run: {
  experimentId: string;
  partition: "VALIDATION" | "HOLDOUT";
  side: "CHAMPION" | "CANDIDATE";
  sampleId: string;
  seed: number;
}): string {
  return contentId("run", {
    experimentId: run.experimentId,
    partition: run.partition,
    sampleId: run.sampleId,
    seed: run.seed,
    side: run.side,
  });
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

export const PromptOptimizerTargetSchema = z
  .object({
    agentId: AgentIdSchema,
    stage: z.enum(RUNTIME_AGENT_STAGE_IDS),
    cohort: z.string().regex(/^cohort_[a-z0-9_]+$/),
  })
  .strict()
  .superRefine((target, ctx) => {
    if (target.agentId === "cio" && target.stage === "cio_proposal") {
      ctx.addIssue({
        code: "custom",
        path: ["stage"],
        message: "cio_proposal shares the cio_final Prompt champion and is not a mutation target",
      });
      return;
    }
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

const PromptDirectEvaluationComponentSchema = z
  .object({
    componentRef: z.string().regex(/^role_component_v1:[a-z0-9_]+:[0-9]{3}$/),
    directMatureSampleCount: z.number().int().nonnegative(),
    meanScore: UnitScoreSchema.nullable(),
    lowerTailScore: UnitScoreSchema.nullable(),
    failureCategoryCounts: z.record(canonicalNonEmptyString(), z.number().int().nonnegative()),
  })
  .strict()
  .superRefine((component, ctx) => {
    const observed = component.directMatureSampleCount > 0;
    if (observed !== (component.meanScore !== null && component.lowerTailScore !== null)) {
      ctx.addIssue({
        code: "custom",
        message: "direct component scores must match its mature sample count",
      });
    }
  });

const PromptControlledExperimentProjectionSchema = z
  .object({
    candidateId: NonEmptyIdSchema,
    candidatePrivateLineageHash: PromptOptimizerSha256Schema,
    experimentId: NonEmptyIdSchema,
    status: z.literal("COMPLETE"),
    evaluatorVersion: NonEmptyIdSchema,
    evaluatorConfigHash: PromptOptimizerSha256Schema,
    executorAdapterHash: PromptOptimizerSha256Schema,
    evaluatorAdapterHash: PromptOptimizerSha256Schema,
    codeCommit: PromptOptimizerGitCommitSchema,
    pairDeltas: z.array(z.number().finite().min(-2).max(2)).min(1),
    failureCaseRefs: z.array(PublicRefSchema).max(500),
    completedAt: IsoDateTimeSchema,
  })
  .strict();

/**
 * The only KNOT input. Public outcome owners freeze scores into opaque role
 * components; private behavior-facet names and scoring formulas never cross.
 */
export const PromptTrainingProjectionSchema = z
  .object({
    schemaVersion: z.literal("prompt_training_projection_v1"),
    target: PromptOptimizerTargetSchema,
    projectionId: NonEmptyIdSchema,
    projectionHash: PromptOptimizerSha256Schema,
    datasetSnapshotHash: PromptOptimizerSha256Schema,
    excludedSampleIdsHash: PromptOptimizerSha256Schema,
    cutoffAt: IsoDateTimeSchema,
    outcomeContract: z
      .object({
        evaluationObject: NonEmptyIdSchema,
        outcomeContractVersion: NonEmptyIdSchema,
        primaryLabelId: NonEmptyIdSchema,
        maturityHorizon: NonEmptyIdSchema,
        maturityTradingDays: z.number().int().positive(),
      })
      .strict(),
    evaluator: z
      .object({
        version: NonEmptyIdSchema,
        configHash: PromptOptimizerSha256Schema,
        implementationHash: PromptOptimizerSha256Schema,
        executorAdapterHash: PromptOptimizerSha256Schema,
        evaluatorAdapterHash: PromptOptimizerSha256Schema,
      })
      .strict(),
    matureSampleCount: z.number().int().nonnegative(),
    scoreSummary: FiniteMetricRecordSchema,
    failureCategoryCounts: z.record(canonicalNonEmptyString(), z.number().int().nonnegative()),
    tailFailureCaseRefs: z.array(PublicRefSchema).max(100),
    evidenceGapSummaries: z.array(PublicSummarySchema).max(100),
    directComponents: z.array(PromptDirectEvaluationComponentSchema).min(1),
    controlledExperiments: z.array(PromptControlledExperimentProjectionSchema),
  })
  .strict()
  .superRefine((projection, ctx) => {
    const { projectionHash, ...body } = projection;
    if (projectionHash !== canonicalJsonHash(body)) {
      ctx.addIssue({
        code: "custom",
        path: ["projectionHash"],
        message: "training projection hash must bind the complete public projection",
      });
    }
    const componentRefs = projection.directComponents.map((value) => value.componentRef);
    if (new Set(componentRefs).size !== componentRefs.length) {
      ctx.addIssue({ code: "custom", path: ["directComponents"], message: "duplicate component" });
    }
    for (const [index, component] of projection.directComponents.entries()) {
      if (!component.componentRef.startsWith(`role_component_v1:${projection.target.agentId}:`)) {
        ctx.addIssue({
          code: "custom",
          path: ["directComponents", index, "componentRef"],
          message: "direct component must belong to the projection target",
        });
      }
      if (component.directMatureSampleCount !== projection.matureSampleCount) {
        ctx.addIssue({
          code: "custom",
          path: ["directComponents", index, "directMatureSampleCount"],
          message: "every direct component must use the complete mature sample set",
        });
      }
    }
    const experimentIds = projection.controlledExperiments.map((value) => value.experimentId);
    if (new Set(experimentIds).size !== experimentIds.length) {
      ctx.addIssue({
        code: "custom",
        path: ["controlledExperiments"],
        message: "controlled experiment IDs must be unique",
      });
    }
    for (const [index, experiment] of projection.controlledExperiments.entries()) {
      if (instant(experiment.completedAt) > instant(projection.cutoffAt)) {
        ctx.addIssue({
          code: "custom",
          path: ["controlledExperiments", index, "completedAt"],
          message: "controlled experiment was not complete at the projection cutoff",
        });
      }
    }
  });

export type PromptTrainingProjection = z.infer<typeof PromptTrainingProjectionSchema>;

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
    trainingProjectionHash: PromptOptimizerSha256Schema,
    excludedSampleIdsHash: PromptOptimizerSha256Schema,
    mutatorConfigHash: PromptOptimizerSha256Schema,
    mutatorCommit: PromptOptimizerGitCommitSchema,
    mutationCategories: z.array(PromptMutationCategorySchema).min(1).max(6),
    mutationSummary: PublicSummarySchema,
    hypothesis: PublicSummarySchema,
    behaviorContractHash: PromptOptimizerSha256Schema,
    privateLineageHash: PromptOptimizerSha256Schema,
    privateStateArtifactHash: PromptOptimizerSha256Schema,
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
  });

export type PromptCandidate = z.infer<typeof PromptCandidateSchema>;

export const PromptDatasetSampleRefSchema = z
  .object({
    sampleId: NonEmptyIdSchema,
    inputRef: PublicRefSchema,
    inputHash: PromptOptimizerSha256Schema,
    outcomeRef: PublicRefSchema,
    outcomeHash: PromptOptimizerSha256Schema,
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
    if (sample.sampleId !== promptDatasetSampleId(sample)) {
      ctx.addIssue({
        code: "custom",
        path: ["sampleId"],
        message: "sampleId must be derived from the immutable sample content",
      });
    }
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
    snapshotHash: PromptOptimizerSha256Schema,
    windowStartAt: IsoDateTimeSchema,
    windowEndAt: IsoDateTimeSchema,
    samples: z.array(PromptDatasetSampleRefSchema).min(1),
  })
  .strict()
  .superRefine((partition, ctx) => {
    if (partition.snapshotHash !== promptDatasetPartitionSnapshotHash(partition)) {
      ctx.addIssue({
        code: "custom",
        path: ["snapshotHash"],
        message: "partition snapshotHash must bind the sorted sample identities",
      });
    }
    if (instant(partition.windowStartAt) > instant(partition.windowEndAt)) {
      ctx.addIssue({ code: "custom", message: "partition window must be ordered" });
    }
    const orderedWindows: Array<{ start: number; end: number; index: number }> = [];
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
      orderedWindows.push({
        start: instant(sample.eventWindow.startAt),
        end: instant(sample.eventWindow.endAt),
        index,
      });
    }
    orderedWindows.sort((left, right) => left.start - right.start || left.end - right.end);
    for (let position = 1; position < orderedWindows.length; position += 1) {
      const previous = orderedWindows[position - 1];
      const current = orderedWindows[position];
      // Event windows are half-open [start, end): an end exactly equal to the
      // next start is allowed, while any positive-duration intersection is not.
      if (previous && current && current.start < previous.end) {
        ctx.addIssue({
          code: "custom",
          path: ["samples", current.index, "eventWindow"],
          message: "sample event windows cannot overlap; touching half-open boundaries are allowed",
        });
      }
    }
  });

export const DatasetSplitManifestSchema = z
  .object({
    schemaVersion: z.literal("prompt_dataset_split_v1"),
    splitId: NonEmptyIdSchema,
    target: PromptOptimizerTargetSchema,
    trainingProjectionHash: PromptOptimizerSha256Schema,
    cutoffAt: IsoDateTimeSchema,
    training: DatasetPartitionSchema,
    validation: DatasetPartitionSchema,
    holdout: DatasetPartitionSchema,
    evaluatorVersion: NonEmptyIdSchema,
    createdAt: IsoDateTimeSchema,
  })
  .strict()
  .superRefine((manifest, ctx) => {
    if (manifest.splitId !== promptDatasetSplitId(manifest)) {
      ctx.addIssue({
        code: "custom",
        path: ["splitId"],
        message: "splitId must be derived from the immutable split definition",
      });
    }
    if (instant(manifest.training.windowEndAt) !== instant(manifest.cutoffAt)) {
      ctx.addIssue({
        code: "custom",
        path: ["cutoffAt"],
        message: "cutoffAt must equal the training window end",
      });
    }
    if (instant(manifest.cutoffAt) > instant(manifest.createdAt)) {
      ctx.addIssue({
        code: "custom",
        path: ["createdAt"],
        message: "split manifest cannot be created before its training cutoff",
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

export function promptSplitExcludedSampleIdsHash(split: DatasetSplitManifest): string {
  return canonicalJsonHash(
    [...split.validation.samples, ...split.holdout.samples].map((sample) => sample.sampleId).sort(),
  );
}

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
    promotionPolicyVersion: NonEmptyIdSchema,
    promotionPolicyConfigHash: PromptOptimizerSha256Schema,
    candidateIds: z.array(NonEmptyIdSchema).min(1),
    createdAt: IsoDateTimeSchema,
  })
  .strict()
  .superRefine((family, ctx) => {
    if (family.familyId !== promptCandidateFamilyId(family)) {
      ctx.addIssue({
        code: "custom",
        path: ["familyId"],
        message: "familyId must be derived from the immutable family definition",
      });
    }
    const sorted = [...new Set(family.candidateIds)].sort(compareCanonicalStrings);
    if (JSON.stringify(sorted) !== JSON.stringify(family.candidateIds)) {
      ctx.addIssue({
        code: "custom",
        path: ["candidateIds"],
        message: "candidateIds must be unique and sorted",
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
    promotionPolicyVersion: NonEmptyIdSchema,
    promotionPolicyConfigHash: PromptOptimizerSha256Schema,
    modelConfigHash: PromptOptimizerSha256Schema,
    toolConfigHash: PromptOptimizerSha256Schema,
    componentCalibrationSnapshotHash: PromptOptimizerSha256Schema,
    darwinianUsageSnapshotHash: PromptOptimizerSha256Schema,
    executorAdapterHash: PromptOptimizerSha256Schema,
    evaluatorAdapterHash: PromptOptimizerSha256Schema,
    evaluationBinding: z
      .object({
        evaluationObject: NonEmptyIdSchema,
        evaluationObjectSchemaVersion: SafePublicVersionSchema,
        primaryLabelId: NonEmptyIdSchema,
        scoringContractVersion: NonEmptyIdSchema,
        outcomeContractVersion: NonEmptyIdSchema,
      })
      .strict(),
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
    if (experiment.experimentId !== promptExperimentId(experiment)) {
      ctx.addIssue({
        code: "custom",
        path: ["experimentId"],
        message: "experimentId must be derived from the immutable experiment definition",
      });
    }
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

/** Existing immutable fields that must be identical for every sibling experiment. */
export function promptExperimentFamilyEnvironment(experiment: PromptExperiment) {
  return {
    target: experiment.target,
    championId: experiment.championId,
    championPromptCommit: experiment.championPromptCommit,
    championPromptRefs: experiment.championPromptRefs,
    championPromptHashes: experiment.championPromptHashes,
    datasetSplitId: experiment.datasetSplitId,
    datasetSplitManifestHash: experiment.datasetSplitManifestHash,
    promotionPolicyVersion: experiment.promotionPolicyVersion,
    promotionPolicyConfigHash: experiment.promotionPolicyConfigHash,
    modelConfigHash: experiment.modelConfigHash,
    toolConfigHash: experiment.toolConfigHash,
    componentCalibrationSnapshotHash: experiment.componentCalibrationSnapshotHash,
    darwinianUsageSnapshotHash: experiment.darwinianUsageSnapshotHash,
    executorAdapterHash: experiment.executorAdapterHash,
    evaluatorAdapterHash: experiment.evaluatorAdapterHash,
    evaluationBinding: experiment.evaluationBinding,
    evaluatorVersion: experiment.evaluatorVersion,
    evaluatorConfigHash: experiment.evaluatorConfigHash,
    codeCommit: experiment.codeCommit,
    repeatSeeds: experiment.repeatSeeds,
  };
}

export const PROMPT_EXPERIMENT_MAX_ATTEMPTS = 3;

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
    leaseOwner: NonEmptyIdSchema.nullable(),
    leaseExpiresAt: IsoDateTimeSchema.nullable(),
    attempt: z.number().int().nonnegative().max(PROMPT_EXPERIMENT_MAX_ATTEMPTS),
    retryable: z.boolean(),
    attemptFailureCodes: z.array(NonEmptyIdSchema).max(10),
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
    if (run.runId !== promptExperimentRunId(run)) {
      ctx.addIssue({
        code: "custom",
        path: ["runId"],
        message: "runId must be derived from the immutable run coordinates",
      });
    }
    if (
      run.status === "PENDING" &&
      (run.startedAt !== null ||
        run.completedAt !== null ||
        run.leaseOwner !== null ||
        run.leaseExpiresAt !== null ||
        run.attempt !== 0 ||
        run.retryable)
    ) {
      ctx.addIssue({ code: "custom", message: "pending run cannot have a lease or timestamps" });
    }
    if (run.attemptFailureCodes.length > run.attempt) {
      ctx.addIssue({
        code: "custom",
        path: ["attemptFailureCodes"],
        message: "attempt failure history cannot exceed the attempt count",
      });
    }
    if (run.retryable && run.status !== "FAILED") {
      ctx.addIssue({
        code: "custom",
        path: ["retryable"],
        message: "only a failed run can be retryable",
      });
    }
    if (
      run.status !== "PENDING" &&
      (run.startedAt === null ||
        run.leaseOwner === null ||
        run.leaseExpiresAt === null ||
        run.attempt < 1)
    ) {
      ctx.addIssue({ code: "custom", message: "started run requires an owned lease attempt" });
    }
    if (
      run.status === "RUNNING" &&
      (run.completedAt !== null ||
        (run.startedAt !== null &&
          run.leaseExpiresAt !== null &&
          instant(run.leaseExpiresAt) <= instant(run.startedAt)))
    ) {
      ctx.addIssue({ code: "custom", message: "running run requires an unexpired initial lease" });
    }
    if (run.status === "COMPLETE") {
      if (
        run.startedAt === null ||
        run.completedAt === null ||
        run.agentOutputRef === null ||
        run.effectiveInputHash === null ||
        !("normalized_score" in run.metrics) ||
        run.errorCode !== null ||
        run.retryable
      ) {
        ctx.addIssue({
          code: "custom",
          message: "complete run is missing accepted output or score",
        });
      }
    }
    if (run.status === "FAILED") {
      if (
        run.startedAt === null ||
        run.completedAt === null ||
        run.errorCode === null ||
        run.attemptFailureCodes.at(-1) !== run.errorCode ||
        (run.retryable && run.attempt >= PROMPT_EXPERIMENT_MAX_ATTEMPTS)
      ) {
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
  training: PromptTrainingProjection,
): void {
  if (training.matureSampleCount < 30) {
    throw new Error("candidate_training_sample_count_insufficient");
  }
  if (
    JSON.stringify(candidate.target) !== JSON.stringify(training.target) ||
    candidate.trainingProjectionHash !== training.projectionHash ||
    candidate.excludedSampleIdsHash !== training.excludedSampleIdsHash
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
    candidate.trainingProjectionHash !== split.trainingProjectionHash ||
    candidate.excludedSampleIdsHash !== promptSplitExcludedSampleIdsHash(split)
  ) {
    throw new Error("candidate_dataset_split_mismatch");
  }
}

export function assertTrainingProjectionMatchesSplit(
  training: PromptTrainingProjection,
  split: DatasetSplitManifest,
): void {
  if (
    JSON.stringify(training.target) !== JSON.stringify(split.target) ||
    training.projectionHash !== split.trainingProjectionHash ||
    instant(training.cutoffAt) !== instant(split.cutoffAt) ||
    training.excludedSampleIdsHash !== promptSplitExcludedSampleIdsHash(split)
  ) {
    throw new Error("training_projection_dataset_split_mismatch");
  }
}

export const PROMPT_OPTIMIZER_PUBLIC_SCHEMAS = Object.freeze({
  prompt_training_projection_v1: PromptTrainingProjectionSchema,
  prompt_candidate_v1: PromptCandidateSchema,
  prompt_candidate_family_v1: PromptCandidateFamilySchema,
  prompt_dataset_split_v1: DatasetSplitManifestSchema,
  prompt_experiment_v1: PromptExperimentSchema,
  prompt_experiment_run_v1: PromptExperimentRunSchema,
  prompt_promotion_decision_v1: PromptPromotionDecisionSchema,
});

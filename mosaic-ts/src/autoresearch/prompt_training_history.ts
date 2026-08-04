import { z } from "zod";
import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";
import {
  PromptOptimizerSha256Schema,
  PromptOptimizerTargetSchema,
} from "./prompt_optimizer_contract.js";

const NonEmpty = z.string().trim().min(1);
const UnitScore = z.number().finite().min(-1).max(1);
const JsonObject = z.record(z.string(), z.unknown());

const PromptTrainingComponentSignalSchema = z
  .object({
    component: NonEmpty,
    signal: UnitScore,
    effective_confidence: z.number().finite().min(0).max(1),
  })
  .strict();

const PromptTrainingHistoryRecordSchema = z
  .object({
    sampleId: NonEmpty,
    agentOutputRef: NonEmpty,
    agentOutputHash: PromptOptimizerSha256Schema,
    outcomeLabelRef: NonEmpty,
    outcomeLabelHash: PromptOptimizerSha256Schema,
    asOf: z.union([z.iso.date(), z.iso.datetime({ offset: true })]),
    maturedAt: z.iso.datetime({ offset: true }),
    promptBehaviorVersion: NonEmpty,
    normalizedScore: UnitScore,
    rawMetrics: JsonObject,
    componentSignals: z.array(PromptTrainingComponentSignalSchema),
    supportingAcceptedOutputs: JsonObject,
  })
  .strict();

const PromptValidationExperimentHistorySchema = z
  .object({
    candidateId: NonEmpty,
    candidatePrivateLineageHash: PromptOptimizerSha256Schema,
    experimentId: NonEmpty,
    evaluatorVersion: NonEmpty,
    evaluatorConfigHash: PromptOptimizerSha256Schema,
    codeCommit: z.string().regex(/^[0-9a-f]{40}$/),
    validationPairCount: z.number().int().positive(),
    validationCandidateMean: z.number().finite(),
    validationChampionMean: z.number().finite(),
    validationPairedDelta: z.number().finite(),
    validationPairDeltas: z.array(z.number().finite()).min(1),
    validationFailureCaseRefs: z.array(NonEmpty),
    validationCompletedAt: z.iso.datetime({ offset: true }),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.validationPairCount !== value.validationPairDeltas.length) {
      ctx.addIssue({
        code: "custom",
        path: ["validationPairDeltas"],
        message: "validation pair count mismatch",
      });
    }
    const pairMean =
      value.validationPairDeltas.reduce((total, score) => total + score, 0) /
      value.validationPairDeltas.length;
    if (
      Math.abs(
        value.validationCandidateMean - value.validationChampionMean - value.validationPairedDelta,
      ) > 1e-12 ||
      Math.abs(pairMean - value.validationPairedDelta) > 1e-12
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["validationPairedDelta"],
        message: "validation aggregate mismatch",
      });
    }
  });

export const PromptTrainingHistorySchema = z
  .object({
    schemaVersion: z.literal("prompt_training_history_v1"),
    exporterVersion: z.literal("prompt_training_history_exporter_v1"),
    target: PromptOptimizerTargetSchema,
    cutoffAt: z.iso.datetime({ offset: true }),
    outcomeContractVersion: NonEmpty,
    metricFamily: NonEmpty,
    primaryLabelId: NonEmpty,
    excludedSampleIds: z.array(NonEmpty),
    records: z.array(PromptTrainingHistoryRecordSchema),
    validationExperiments: z.array(PromptValidationExperimentHistorySchema),
    historyHash: PromptOptimizerSha256Schema,
  })
  .strict()
  .superRefine((history, ctx) => {
    const { historyHash, ...body } = history;
    if (historyHash !== canonicalJsonHash(body)) {
      ctx.addIssue({ code: "custom", path: ["historyHash"], message: "history hash mismatch" });
    }
    const sampleIds = history.records.map((value) => value.sampleId);
    if (
      new Set(sampleIds).size !== sampleIds.length ||
      new Set(history.excludedSampleIds).size !== history.excludedSampleIds.length ||
      sampleIds.some((value) => history.excludedSampleIds.includes(value))
    ) {
      ctx.addIssue({ code: "custom", path: ["records"], message: "training sample overlap" });
    }
    if (
      history.records.some(
        (value) =>
          Date.parse(value.asOf) > Date.parse(value.maturedAt) ||
          Date.parse(value.maturedAt) > Date.parse(history.cutoffAt),
      )
    ) {
      ctx.addIssue({ code: "custom", path: ["records"], message: "future mature sample" });
    }
    const experimentIds = history.validationExperiments.map((value) => value.experimentId);
    if (
      new Set(experimentIds).size !== experimentIds.length ||
      history.validationExperiments.some(
        (value) => Date.parse(value.validationCompletedAt) > Date.parse(history.cutoffAt),
      )
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["validationExperiments"],
        message: "validation history identity or PIT mismatch",
      });
    }
  });

export type PromptTrainingHistory = z.infer<typeof PromptTrainingHistorySchema>;

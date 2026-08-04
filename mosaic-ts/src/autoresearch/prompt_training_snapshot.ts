import { z } from "zod";
import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";
import {
  type PromptOptimizerTarget,
  PromptOptimizerTargetSchema,
  type PromptTrainingSnapshot,
  PromptTrainingSnapshotSchema,
} from "./prompt_optimizer_contract.js";

const NonEmptyText = z.string().trim().min(1);
const UnitScore = z.number().finite().min(-1).max(1);

export const PromptBehaviorTrainingObservationSchema = z
  .object({
    schemaVersion: z.literal("prompt_behavior_evaluation_v1"),
    observationId: NonEmptyText,
    target: PromptOptimizerTargetSchema,
    agentOutputRef: NonEmptyText,
    outcomeLabelRef: NonEmptyText,
    outcomeContractVersion: NonEmptyText,
    evaluatorVersion: NonEmptyText,
    maturedAt: z.iso.datetime({ offset: true }),
    normalizedScore: UnitScore,
    facetScores: z.record(z.string().regex(/^[a-z][a-z0-9_]*$/), UnitScore),
    failureCategories: z.array(NonEmptyText),
    facetFailureCategories: z.record(z.string().regex(/^[a-z][a-z0-9_]*$/), z.array(NonEmptyText)),
    failureCaseRef: NonEmptyText.optional(),
    evidenceGapSummary: NonEmptyText.max(2_000).optional(),
  })
  .strict();

export type PromptBehaviorTrainingObservation = z.infer<
  typeof PromptBehaviorTrainingObservationSchema
>;

export interface BuildPromptTrainingSnapshotInput {
  target: PromptOptimizerTarget;
  snapshotId: string;
  cutoffAt: string;
  outcomeContractVersion: string;
  evaluatorVersion: string;
  behaviorContractHash: string;
  requiredFacetIds: ReadonlyArray<string>;
  observations: ReadonlyArray<PromptBehaviorTrainingObservation>;
}

function mean(values: ReadonlyArray<number>): number {
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function lowerTailMean(values: ReadonlyArray<number>): number {
  const sorted = [...values].sort((left, right) => left - right);
  const count = Math.max(1, Math.ceil(sorted.length * 0.1));
  return mean(sorted.slice(0, count));
}

function count(values: ReadonlyArray<string>): Record<string, number> {
  const result: Record<string, number> = {};
  for (const value of values) result[value] = (result[value] ?? 0) + 1;
  return Object.fromEntries(
    Object.entries(result).sort(([left], [right]) => left.localeCompare(right)),
  );
}

function assertFiniteUnitScore(value: number, label: string): void {
  if (!Number.isFinite(value) || value < -1 || value > 1) {
    throw new Error(`${label}_must_be_in_unit_interval`);
  }
}

function assertSameTarget(expected: PromptOptimizerTarget, actual: PromptOptimizerTarget): void {
  if (canonicalJsonHash(expected) !== canonicalJsonHash(actual)) {
    throw new Error("prompt_training_observation_target_mismatch");
  }
}

/**
 * Builds the only input accepted by the private Prompt mutator. The caller's
 * frozen evaluator owns each per-facet score; this function only enforces PIT
 * closure and produces deterministic, prose-minimal aggregates.
 */
export function buildPromptTrainingSnapshot(
  rawInput: BuildPromptTrainingSnapshotInput,
): PromptTrainingSnapshot {
  const target = PromptOptimizerTargetSchema.parse(rawInput.target);
  const cutoff = Date.parse(rawInput.cutoffAt);
  if (!Number.isFinite(cutoff)) throw new Error("prompt_training_cutoff_invalid");
  const requiredFacetIds = [...new Set(rawInput.requiredFacetIds)].sort();
  if (
    requiredFacetIds.length === 0 ||
    requiredFacetIds.length !== rawInput.requiredFacetIds.length ||
    requiredFacetIds.some((value) => !/^[a-z][a-z0-9_]*$/.test(value))
  ) {
    throw new Error("prompt_training_required_facets_invalid");
  }
  if (rawInput.observations.length < 30) {
    throw new Error("prompt_training_insufficient_mature_samples");
  }

  const seen = new Set<string>();
  const observations = rawInput.observations.map((rawObservation) => {
    const observation = PromptBehaviorTrainingObservationSchema.parse(rawObservation);
    if (!observation.observationId.trim() || seen.has(observation.observationId)) {
      throw new Error("prompt_training_observation_identity_invalid");
    }
    seen.add(observation.observationId);
    assertSameTarget(target, PromptOptimizerTargetSchema.parse(observation.target));
    if (
      observation.outcomeContractVersion !== rawInput.outcomeContractVersion ||
      observation.evaluatorVersion !== rawInput.evaluatorVersion
    ) {
      throw new Error("prompt_training_observation_evaluator_binding_mismatch");
    }
    const maturedAt = Date.parse(observation.maturedAt);
    if (!Number.isFinite(maturedAt) || maturedAt > cutoff) {
      throw new Error("prompt_training_observation_not_mature_at_cutoff");
    }
    assertFiniteUnitScore(observation.normalizedScore, "prompt_training_normalized_score");
    const facetIds = Object.keys(observation.facetScores).sort();
    if (JSON.stringify(facetIds) !== JSON.stringify(requiredFacetIds)) {
      throw new Error("prompt_training_observation_facet_coverage_incomplete");
    }
    const failureFacetIds = Object.keys(observation.facetFailureCategories).sort();
    if (JSON.stringify(failureFacetIds) !== JSON.stringify(requiredFacetIds)) {
      throw new Error("prompt_training_observation_facet_failure_coverage_incomplete");
    }
    for (const facetId of requiredFacetIds) {
      assertFiniteUnitScore(
        observation.facetScores[facetId] as number,
        `prompt_training_facet_score:${facetId}`,
      );
      for (const category of observation.facetFailureCategories[facetId] ?? []) {
        if (!category.trim()) throw new Error("prompt_training_failure_category_invalid");
      }
    }
    if (observation.failureCategories.some((category) => !category.trim())) {
      throw new Error("prompt_training_failure_category_invalid");
    }
    return observation;
  });

  const normalizedScores = observations.map((value) => value.normalizedScore);
  const datasetSnapshotHash = canonicalJsonHash(
    [...observations].sort((left, right) => left.observationId.localeCompare(right.observationId)),
  );
  const facets = Object.fromEntries(
    requiredFacetIds.map((facetId) => {
      const values = observations.map((value) => value.facetScores[facetId] as number);
      return [
        facetId,
        {
          matureSampleCount: values.length,
          meanScore: mean(values),
          lowerTailScore: lowerTailMean(values),
          failureCategoryCounts: count(
            observations.flatMap((value) => value.facetFailureCategories[facetId] ?? []),
          ),
        },
      ];
    }),
  );
  const tailCount = Math.max(1, Math.ceil(observations.length * 0.1));
  const tail = [...observations]
    .sort(
      (left, right) =>
        left.normalizedScore - right.normalizedScore ||
        left.observationId.localeCompare(right.observationId),
    )
    .slice(0, tailCount);
  const withoutHash = {
    schemaVersion: "prompt_training_snapshot_v1" as const,
    target,
    snapshotId: rawInput.snapshotId,
    datasetSnapshotHash,
    cutoffAt: rawInput.cutoffAt,
    outcomeContractVersion: rawInput.outcomeContractVersion,
    evaluatorVersion: rawInput.evaluatorVersion,
    matureSampleCount: observations.length,
    scoreSummary: {
      mean_normalized_score: mean(normalizedScores),
      lower_tail_score: lowerTailMean(normalizedScores),
    },
    failureCategoryCounts: count(observations.flatMap((value) => value.failureCategories)),
    tailFailureCaseRefs: tail.flatMap((value) =>
      value.failureCaseRef ? [value.failureCaseRef] : [],
    ),
    evidenceGapSummaries: tail.flatMap((value) =>
      value.evidenceGapSummary ? [value.evidenceGapSummary] : [],
    ),
    behaviorFeedback: {
      contractHash: rawInput.behaviorContractHash,
      facets,
    },
  };
  return PromptTrainingSnapshotSchema.parse({
    ...withoutHash,
    snapshotHash: canonicalJsonHash(withoutHash),
  });
}

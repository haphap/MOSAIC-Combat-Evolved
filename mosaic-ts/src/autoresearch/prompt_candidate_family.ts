import {
  type PromptCandidateFamily,
  PromptCandidateFamilySchema,
  type PromptExperiment,
  PromptExperimentSchema,
} from "./prompt_optimizer_contract.js";

/** Select exactly one validation winner before any holdout observation is opened. */
export function selectPromptCandidateFamily(input: {
  family: PromptCandidateFamily;
  validationExperiments: ReadonlyArray<PromptExperiment>;
  selectedAt: string;
}): PromptCandidateFamily {
  const family = PromptCandidateFamilySchema.parse(input.family);
  if (family.status !== "REGISTERED") {
    throw new Error("prompt_candidate_family_not_registered");
  }
  const experiments = input.validationExperiments.map((value) =>
    PromptExperimentSchema.parse(value),
  );
  if (experiments.length !== family.candidateIds.length) {
    throw new Error("prompt_candidate_family_validation_count_mismatch");
  }
  const byCandidate = new Map<string, PromptExperiment>();
  for (const experiment of experiments) {
    if (
      experiment.familyId !== family.familyId ||
      experiment.status !== "VALIDATION_COMPLETE" ||
      !family.candidateIds.includes(experiment.candidateId) ||
      typeof experiment.metrics.validation_paired_delta !== "number"
    ) {
      throw new Error("prompt_candidate_family_validation_experiment_invalid");
    }
    if (byCandidate.has(experiment.candidateId)) {
      throw new Error("prompt_candidate_family_duplicate_validation_experiment");
    }
    byCandidate.set(experiment.candidateId, experiment);
  }
  if (byCandidate.size !== family.candidateIds.length) {
    throw new Error("prompt_candidate_family_validation_manifest_incomplete");
  }
  const winner = [...experiments].sort((left, right) => {
    const delta =
      (right.metrics.validation_paired_delta ?? Number.NEGATIVE_INFINITY) -
      (left.metrics.validation_paired_delta ?? Number.NEGATIVE_INFINITY);
    return delta || left.candidateId.localeCompare(right.candidateId);
  })[0];
  if (!winner) throw new Error("prompt_candidate_family_winner_missing");
  return PromptCandidateFamilySchema.parse({
    ...family,
    validationExperimentIds: experiments.map((value) => value.experimentId).sort(),
    selectedCandidateId: winner.candidateId,
    selectedExperimentId: winner.experimentId,
    status: "SELECTED",
    updatedAt: input.selectedAt,
  });
}

import { canonicalJsonHash, compareCanonicalStrings } from "../agents/helpers/canonical_json.js";
import {
  type DatasetSplitManifest,
  DatasetSplitManifestSchema,
  type PromptCandidateFamily,
  PromptCandidateFamilySchema,
  type PromptExperiment,
  type PromptExperimentRun,
  PromptExperimentSchema,
  promptExperimentFamilyEnvironment,
} from "./prompt_optimizer_contract.js";
import {
  evaluatePromptValidationGates,
  type PromptPromotionPolicy,
  PromptPromotionPolicySchema,
} from "./prompt_promotion_policy.js";

/** Ephemeral selection; persisted Experiment states remain the only outcome record. */
export interface PromptCandidateFamilySelection {
  selectedCandidateId: string;
  selectedExperimentId: string;
}

/** Select exactly one validation winner before any holdout observation is opened. */
export function selectPromptCandidateFamily(input: {
  family: PromptCandidateFamily;
  validationExperiments: ReadonlyArray<PromptExperiment>;
  validationRuns: ReadonlyArray<{
    experimentId: string;
    runs: ReadonlyArray<PromptExperimentRun>;
  }>;
  split: DatasetSplitManifest;
  policy: PromptPromotionPolicy;
}): PromptCandidateFamilySelection {
  const family = PromptCandidateFamilySchema.parse(input.family);
  const split = DatasetSplitManifestSchema.parse(input.split);
  const policy = PromptPromotionPolicySchema.parse(input.policy);
  if (
    family.promotionPolicyVersion !== policy.policyVersion ||
    family.promotionPolicyConfigHash !== canonicalJsonHash(policy) ||
    family.datasetSplitId !== split.splitId ||
    family.datasetSplitManifestHash !== canonicalJsonHash(split) ||
    canonicalJsonHash(family.target) !== canonicalJsonHash(split.target)
  ) {
    throw new Error("prompt_candidate_family_policy_drift");
  }
  const experiments = input.validationExperiments.map((value) =>
    PromptExperimentSchema.parse(value),
  );
  if (experiments.length !== family.candidateIds.length) {
    throw new Error("prompt_candidate_family_validation_count_mismatch");
  }
  const byCandidate = new Map<string, PromptExperiment>();
  const familyEnvironmentHash = canonicalJsonHash(
    promptExperimentFamilyEnvironment(experiments[0] as PromptExperiment),
  );
  for (const experiment of experiments) {
    if (
      experiment.familyId !== family.familyId ||
      !["VALIDATION_COMPLETE", "HOLDOUT_RUNNING", "COMPLETE"].includes(experiment.status) ||
      !family.candidateIds.includes(experiment.candidateId) ||
      experiment.datasetSplitId !== split.splitId ||
      experiment.datasetSplitManifestHash !== family.datasetSplitManifestHash ||
      experiment.promotionPolicyVersion !== family.promotionPolicyVersion ||
      experiment.promotionPolicyConfigHash !== family.promotionPolicyConfigHash ||
      canonicalJsonHash(promptExperimentFamilyEnvironment(experiment)) !== familyEnvironmentHash ||
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
  const runsByExperiment = new Map(
    input.validationRuns.map((value) => [value.experimentId, value.runs] as const),
  );
  if (
    runsByExperiment.size !== experiments.length ||
    experiments.some((experiment) => !runsByExperiment.has(experiment.experimentId))
  ) {
    throw new Error("prompt_candidate_family_validation_run_manifest_incomplete");
  }
  const eligible = experiments.filter((experiment) => {
    const runs = runsByExperiment.get(experiment.experimentId);
    if (!runs) return false;
    return evaluatePromptValidationGates({
      experiment,
      family,
      split,
      runs,
      policy,
    }).eligible;
  });
  const winner = [...eligible].sort((left, right) => {
    const delta =
      (right.metrics.validation_paired_delta ?? Number.NEGATIVE_INFINITY) -
      (left.metrics.validation_paired_delta ?? Number.NEGATIVE_INFINITY);
    return delta || compareCanonicalStrings(left.candidateId, right.candidateId);
  })[0];
  if (!winner) throw new Error("prompt_candidate_family_no_validation_eligible_candidate");
  return {
    selectedCandidateId: winner.candidateId,
    selectedExperimentId: winner.experimentId,
  };
}

import { canonicalJsonHash, compareCanonicalStrings } from "../agents/helpers/canonical_json.js";
import type { BridgeApi } from "../bridge/types.js";
import { selectPromptCandidateFamily } from "./prompt_candidate_family.js";
import {
  DatasetSplitManifestSchema,
  type PromptCandidate,
  PromptCandidateFamilySchema,
  PromptCandidateSchema,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
} from "./prompt_optimizer_contract.js";
import {
  createPromptPromotionDecision,
  type PromptPromotionPolicy,
  PromptPromotionPolicySchema,
} from "./prompt_promotion_policy.js";

/** Re-open persisted evidence and recompute authority from an installed policy. */
export async function authorizeStoredPromptPromotion(input: {
  api: BridgeApi;
  candidate: PromptCandidate;
  experimentId: string;
  policy: PromptPromotionPolicy;
  authorizedPolicyHashes: ReadonlySet<string>;
  decidedAt: string;
}) {
  const candidate = PromptCandidateSchema.parse(input.candidate);
  const policy = PromptPromotionPolicySchema.parse(input.policy);
  const policyConfigHash = canonicalJsonHash(policy);
  if (!input.authorizedPolicyHashes.has(policyConfigHash)) {
    throw new Error("prompt_promotion_policy_not_authorized");
  }
  const persistedCandidate = PromptCandidateSchema.parse(
    await input.api.promptOptimizerGetCandidate(candidate.candidateId),
  );
  const experiment = PromptExperimentSchema.parse(
    await input.api.promptOptimizerGetExperiment(input.experimentId),
  );
  const family = PromptCandidateFamilySchema.parse(
    await input.api.promptOptimizerGetFamily(experiment.familyId),
  );
  const split = DatasetSplitManifestSchema.parse(
    await input.api.promptOptimizerGetSplit(experiment.datasetSplitId),
  );
  const runs = (await input.api.promptOptimizerListRuns(experiment.experimentId)).map((value) =>
    PromptExperimentRunSchema.parse(value),
  );
  const familyExperiments = (
    await input.api.promptOptimizerListExperiments(experiment.familyId)
  ).map((value) => PromptExperimentSchema.parse(value));
  if (
    canonicalJsonHash(persistedCandidate) !== canonicalJsonHash(candidate) ||
    experiment.status !== "COMPLETE" ||
    experiment.candidateId !== candidate.candidateId ||
    experiment.familyId !== family.familyId ||
    !family.candidateIds.includes(candidate.candidateId) ||
    candidate.parentId !== experiment.championId ||
    candidate.parentPromptCommit !== experiment.championPromptCommit ||
    canonicalJsonHash(candidate.parentPromptHashes) !==
      canonicalJsonHash(experiment.championPromptHashes) ||
    canonicalJsonHash(candidate.target) !== canonicalJsonHash(experiment.target) ||
    canonicalJsonHash(candidate.promptRefs) !== canonicalJsonHash(experiment.candidatePromptRefs) ||
    canonicalJsonHash(candidate.promptHashes) !==
      canonicalJsonHash(experiment.candidatePromptHashes) ||
    family.promotionPolicyVersion !== policy.policyVersion ||
    family.promotionPolicyConfigHash !== policyConfigHash ||
    experiment.promotionPolicyVersion !== policy.policyVersion ||
    experiment.promotionPolicyConfigHash !== policyConfigHash
  ) {
    throw new Error("prompt_promotion_authority_binding_mismatch");
  }
  const validationRuns = await Promise.all(
    familyExperiments.map(async (sibling) => ({
      experimentId: sibling.experimentId,
      runs: (await input.api.promptOptimizerListRuns(sibling.experimentId))
        .map((value) => PromptExperimentRunSchema.parse(value))
        .filter((run) => run.partition === "VALIDATION"),
    })),
  );
  const recomputedSelection = selectPromptCandidateFamily({
    family,
    validationExperiments: familyExperiments,
    validationRuns,
    split,
    policy,
  });
  const holdoutConsumers = familyExperiments.filter((value) =>
    ["HOLDOUT_RUNNING", "COMPLETE"].includes(value.status),
  );
  if (
    recomputedSelection.selectedCandidateId !== candidate.candidateId ||
    recomputedSelection.selectedExperimentId !== experiment.experimentId ||
    holdoutConsumers.length !== 1 ||
    holdoutConsumers[0]?.experimentId !== experiment.experimentId
  ) {
    throw new Error("prompt_promotion_authority_family_selection_drift");
  }
  const sortedRuns = [...runs].sort((left, right) =>
    compareCanonicalStrings(left.runId, right.runId),
  );
  if (
    sortedRuns.some((run) => run.status !== "COMPLETE") ||
    canonicalJsonHash(sortedRuns.map((run) => run.runId).sort(compareCanonicalStrings)) !==
      canonicalJsonHash(experiment.runIds)
  ) {
    throw new Error("prompt_promotion_authority_run_manifest_mismatch");
  }
  const decision = createPromptPromotionDecision({
    experiment,
    family,
    split,
    runs: sortedRuns,
    policy,
    decidedAt: input.decidedAt,
  });
  if (decision.decision !== "ELIGIBLE") {
    throw new Error(`prompt_promotion_authority_rejected:${decision.reasons.join(",")}`);
  }
  return decision;
}

import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";
import type { BridgeApi } from "../bridge/types.js";
import {
  DatasetSplitManifestSchema,
  type PromptCandidate,
  PromptCandidateFamilySchema,
  PromptCandidateSchema,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
  type PromptPromotionDecision,
  PromptPromotionDecisionSchema,
} from "./prompt_optimizer_contract.js";

/** Re-open persisted evidence before release; a standalone Decision DTO is never authority. */
export async function verifyStoredPromptPromotionDecision(input: {
  api: BridgeApi;
  candidate: PromptCandidate;
  decision: PromptPromotionDecision;
}): Promise<void> {
  const candidate = PromptCandidateSchema.parse(input.candidate);
  const decision = PromptPromotionDecisionSchema.parse(input.decision);
  const persistedCandidate = PromptCandidateSchema.parse(
    await input.api.promptOptimizerGetCandidate(candidate.candidateId),
  );
  const experiment = PromptExperimentSchema.parse(
    await input.api.promptOptimizerGetExperiment(decision.experimentId),
  );
  const family = PromptCandidateFamilySchema.parse(
    await input.api.promptOptimizerGetFamily(decision.familyId),
  );
  const split = DatasetSplitManifestSchema.parse(
    await input.api.promptOptimizerGetSplit(experiment.datasetSplitId),
  );
  const runs = (await input.api.promptOptimizerListRuns(experiment.experimentId)).map((value) =>
    PromptExperimentRunSchema.parse(value),
  );
  if (
    canonicalJsonHash(persistedCandidate) !== canonicalJsonHash(candidate) ||
    decision.decision !== "ELIGIBLE" ||
    canonicalJsonHash(decision.reasons) !== canonicalJsonHash(["all_promotion_gates_passed"]) ||
    experiment.status !== "COMPLETE" ||
    family.status !== "COMPLETE" ||
    experiment.candidateId !== candidate.candidateId ||
    experiment.familyId !== family.familyId ||
    family.selectedCandidateId !== candidate.candidateId ||
    family.selectedExperimentId !== experiment.experimentId ||
    family.holdoutExperimentId !== experiment.experimentId ||
    decision.candidateId !== candidate.candidateId ||
    candidate.parentId !== experiment.championId ||
    candidate.parentPromptCommit !== experiment.championPromptCommit ||
    canonicalJsonHash(candidate.parentPromptHashes) !==
      canonicalJsonHash(experiment.championPromptHashes) ||
    canonicalJsonHash(candidate.target) !== canonicalJsonHash(experiment.target) ||
    canonicalJsonHash(candidate.promptRefs) !== canonicalJsonHash(experiment.candidatePromptRefs) ||
    canonicalJsonHash(candidate.promptHashes) !==
      canonicalJsonHash(experiment.candidatePromptHashes)
  ) {
    throw new Error("prompt_promotion_authority_binding_mismatch");
  }
  const sortedRuns = [...runs].sort((left, right) => left.runId.localeCompare(right.runId));
  if (
    sortedRuns.some((run) => run.status !== "COMPLETE") ||
    canonicalJsonHash(sortedRuns.map((run) => run.runId).sort()) !==
      canonicalJsonHash(experiment.runIds)
  ) {
    throw new Error("prompt_promotion_authority_run_manifest_mismatch");
  }
  const evidenceHash = canonicalJsonHash({
    experiment,
    family,
    split,
    runs: sortedRuns,
    policyConfigHash: decision.policyConfigHash,
  });
  if (evidenceHash !== decision.evidenceHash) {
    throw new Error("prompt_promotion_authority_evidence_hash_mismatch");
  }
}

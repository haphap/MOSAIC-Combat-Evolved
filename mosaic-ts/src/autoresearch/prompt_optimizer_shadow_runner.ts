import { z } from "zod";
import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";
import { selectPromptCandidateFamily } from "./prompt_candidate_family.js";
import {
  type FrozenPromptExperimentEnvironment,
  type PromptExperimentAgentExecutor,
  type PromptExperimentEvaluator,
  type PromptExperimentRepository,
  runPromptExperimentPartition,
} from "./prompt_experiment_runner.js";
import {
  assertCandidateMatchesTrainingSnapshot,
  assertTrainingProjectionMatchesSplit,
  DatasetSplitManifestSchema,
  PromptCandidateFamilySchema,
  PromptCandidateSchema,
  PromptExperimentSchema,
  PromptOptimizerGitCommitSchema,
  PromptOptimizerSha256Schema,
  PromptPromotionDecisionSchema,
  PromptTrainingProjectionSchema,
} from "./prompt_optimizer_contract.js";
import {
  createPromptPromotionDecision,
  PromptPromotionPolicySchema,
} from "./prompt_promotion_policy.js";

export const PromptOptimizerShadowPlanSchema = z
  .object({
    schemaVersion: z.literal("prompt_optimizer_shadow_plan_v1"),
    trainingProjection: PromptTrainingProjectionSchema,
    family: PromptCandidateFamilySchema,
    split: DatasetSplitManifestSchema,
    candidates: z.array(PromptCandidateSchema).min(1),
    experiments: z.array(PromptExperimentSchema).min(1),
    environment: z
      .object({
        modelConfigHash: PromptOptimizerSha256Schema,
        toolConfigHash: PromptOptimizerSha256Schema,
        componentCalibrationSnapshotHash: PromptOptimizerSha256Schema,
        darwinianUsageSnapshotHash: PromptOptimizerSha256Schema,
        executorAdapterHash: PromptOptimizerSha256Schema,
        evaluatorAdapterHash: PromptOptimizerSha256Schema,
        evaluatorVersion: z.string().trim().min(1),
        evaluatorConfigHash: PromptOptimizerSha256Schema,
        codeCommit: PromptOptimizerGitCommitSchema,
      })
      .strict(),
    promotionPolicy: PromptPromotionPolicySchema,
    runOwnerId: z.string().trim().min(1).max(256),
    leaseDurationMs: z.number().int().positive().max(86_400_000).default(300_000),
    maxConcurrency: z.number().int().positive().max(64).default(1),
  })
  .strict();

export type PromptOptimizerShadowPlan = z.infer<typeof PromptOptimizerShadowPlanSchema>;

/** Execute the preregistered family in shadow mode; this function has no release activation path. */
export async function runPromptOptimizerShadowPlan(input: {
  plan: PromptOptimizerShadowPlan;
  repository: PromptExperimentRepository;
  executor: PromptExperimentAgentExecutor;
  evaluator: PromptExperimentEvaluator;
  authorizedPolicyHashes: ReadonlySet<string>;
  now?: () => string;
}) {
  const plan = PromptOptimizerShadowPlanSchema.parse(input.plan);
  const policyHash = canonicalJsonHash(plan.promotionPolicy);
  if (!input.authorizedPolicyHashes.has(policyHash)) {
    throw new Error("prompt_optimizer_shadow_policy_not_authorized");
  }
  assertTrainingProjectionMatchesSplit(plan.trainingProjection, plan.split);
  if (
    plan.candidates.length !== plan.family.candidateIds.length ||
    plan.experiments.length !== plan.family.candidateIds.length
  ) {
    throw new Error("prompt_optimizer_shadow_family_manifest_invalid");
  }
  const candidates = new Map(plan.candidates.map((value) => [value.candidateId, value]));
  for (const candidate of plan.candidates) {
    assertCandidateMatchesTrainingSnapshot(candidate, plan.trainingProjection);
  }
  const experiments = new Map(plan.experiments.map((value) => [value.candidateId, value]));
  const validationComplete = [];
  for (const candidateId of plan.family.candidateIds) {
    const candidate = candidates.get(candidateId);
    const experiment = experiments.get(candidateId);
    if (!candidate || !experiment) {
      throw new Error(`prompt_optimizer_shadow_candidate_manifest_missing:${candidateId}`);
    }
    validationComplete.push(
      await runPromptExperimentPartition({
        candidate,
        family: plan.family,
        experiment,
        split: plan.split,
        partition: "VALIDATION",
        environment: plan.environment as FrozenPromptExperimentEnvironment,
        promotionPolicy: plan.promotionPolicy,
        authorizedPolicyHashes: input.authorizedPolicyHashes,
        repository: input.repository,
        executor: input.executor,
        evaluator: input.evaluator,
        maxConcurrency: plan.maxConcurrency,
        runOwnerId: plan.runOwnerId,
        leaseDurationMs: plan.leaseDurationMs,
        ...(input.now ? { now: input.now } : {}),
      }),
    );
  }
  const validationRuns = await Promise.all(
    validationComplete.map(async (experiment) => ({
      experimentId: experiment.experimentId,
      runs: (await input.repository.listRuns(experiment.experimentId)).filter(
        (run) => run.partition === "VALIDATION",
      ),
    })),
  );
  const expectedSelection = selectPromptCandidateFamily({
    family: plan.family,
    validationExperiments: validationComplete,
    validationRuns,
    split: plan.split,
    policy: plan.promotionPolicy,
  });
  const persistedFamily = await input.repository.getFamily(plan.family.familyId);
  if (!persistedFamily) throw new Error("prompt_optimizer_shadow_family_missing");
  if (canonicalJsonHash(persistedFamily) !== canonicalJsonHash(plan.family)) {
    throw new Error("prompt_optimizer_shadow_family_drift");
  }
  const winnerCandidate = candidates.get(expectedSelection.selectedCandidateId);
  const winnerExperiment = validationComplete.find(
    (value) => value.experimentId === expectedSelection.selectedExperimentId,
  );
  if (!winnerCandidate || !winnerExperiment) {
    throw new Error("prompt_optimizer_shadow_winner_missing");
  }
  const complete = await runPromptExperimentPartition({
    candidate: winnerCandidate,
    family: persistedFamily,
    experiment: winnerExperiment,
    split: plan.split,
    partition: "HOLDOUT",
    environment: plan.environment,
    promotionPolicy: plan.promotionPolicy,
    authorizedPolicyHashes: input.authorizedPolicyHashes,
    repository: input.repository,
    executor: input.executor,
    evaluator: input.evaluator,
    maxConcurrency: plan.maxConcurrency,
    runOwnerId: plan.runOwnerId,
    leaseDurationMs: plan.leaseDurationMs,
    ...(input.now ? { now: input.now } : {}),
  });
  const runs = await input.repository.listRuns(complete.experimentId);
  const decision = PromptPromotionDecisionSchema.parse(
    createPromptPromotionDecision({
      experiment: complete,
      family: persistedFamily,
      split: plan.split,
      runs,
      policy: plan.promotionPolicy,
      decidedAt: input.now?.() ?? new Date().toISOString(),
    }),
  );
  return { family: persistedFamily, experiment: complete, decision };
}

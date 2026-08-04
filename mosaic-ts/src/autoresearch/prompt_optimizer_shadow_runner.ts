import { z } from "zod";
import { selectPromptCandidateFamily } from "./prompt_candidate_family.js";
import {
  type FrozenPromptExperimentEnvironment,
  type PromptExecutionBinding,
  type PromptExperimentAgentExecutor,
  type PromptExperimentEvaluator,
  type PromptExperimentRepository,
  runPromptExperimentPartition,
} from "./prompt_experiment_runner.js";
import {
  DatasetSplitManifestSchema,
  PromptCandidateFamilySchema,
  PromptCandidateSchema,
  PromptExperimentSchema,
  PromptHashPairSchema,
  PromptOptimizerGitCommitSchema,
  PromptOptimizerSha256Schema,
  PromptPromotionDecisionSchema,
  PromptRefPairSchema,
} from "./prompt_optimizer_contract.js";
import {
  createPromptPromotionDecision,
  PromptPromotionPolicySchema,
} from "./prompt_promotion_policy.js";

const PromptExecutionBindingSchema = z
  .object({
    champion: z
      .object({ promptRefs: PromptRefPairSchema, promptHashes: PromptHashPairSchema })
      .strict(),
    candidate: z
      .object({ promptRefs: PromptRefPairSchema, promptHashes: PromptHashPairSchema })
      .strict(),
  })
  .strict();

export const PromptOptimizerShadowPlanSchema = z
  .object({
    schemaVersion: z.literal("prompt_optimizer_shadow_plan_v1"),
    family: PromptCandidateFamilySchema,
    split: DatasetSplitManifestSchema,
    candidates: z.array(PromptCandidateSchema).min(1),
    experiments: z.array(PromptExperimentSchema).min(1),
    promptBindings: z.record(z.string().min(1), PromptExecutionBindingSchema),
    environment: z
      .object({
        modelConfigHash: PromptOptimizerSha256Schema,
        toolConfigHash: PromptOptimizerSha256Schema,
        evaluatorVersion: z.string().trim().min(1),
        evaluatorConfigHash: PromptOptimizerSha256Schema,
        codeCommit: PromptOptimizerGitCommitSchema,
      })
      .strict(),
    promotionPolicy: PromptPromotionPolicySchema,
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
  now?: () => string;
}) {
  const plan = PromptOptimizerShadowPlanSchema.parse(input.plan);
  if (
    plan.family.status !== "REGISTERED" ||
    plan.candidates.length !== plan.family.candidateIds.length ||
    plan.experiments.length !== plan.family.candidateIds.length
  ) {
    throw new Error("prompt_optimizer_shadow_family_manifest_invalid");
  }
  const candidates = new Map(plan.candidates.map((value) => [value.candidateId, value]));
  const experiments = new Map(plan.experiments.map((value) => [value.candidateId, value]));
  const validationComplete = [];
  for (const candidateId of plan.family.candidateIds) {
    const candidate = candidates.get(candidateId);
    const experiment = experiments.get(candidateId);
    const promptBinding = plan.promptBindings[candidateId] as PromptExecutionBinding | undefined;
    if (!candidate || !experiment || !promptBinding) {
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
        promptBinding,
        repository: input.repository,
        executor: input.executor,
        evaluator: input.evaluator,
        maxConcurrency: plan.maxConcurrency,
        ...(input.now ? { now: input.now } : {}),
      }),
    );
  }
  const selected = selectPromptCandidateFamily({
    family: plan.family,
    validationExperiments: validationComplete,
    selectedAt: input.now?.() ?? new Date().toISOString(),
  });
  await input.repository.putFamily(selected);
  const winnerCandidate = candidates.get(selected.selectedCandidateId ?? "");
  const winnerExperiment = validationComplete.find(
    (value) => value.experimentId === selected.selectedExperimentId,
  );
  const winnerBinding = selected.selectedCandidateId
    ? plan.promptBindings[selected.selectedCandidateId]
    : undefined;
  if (!winnerCandidate || !winnerExperiment || !winnerBinding) {
    throw new Error("prompt_optimizer_shadow_winner_missing");
  }
  const complete = await runPromptExperimentPartition({
    candidate: winnerCandidate,
    family: selected,
    experiment: winnerExperiment,
    split: plan.split,
    partition: "HOLDOUT",
    environment: plan.environment,
    promptBinding: winnerBinding,
    repository: input.repository,
    executor: input.executor,
    evaluator: input.evaluator,
    maxConcurrency: plan.maxConcurrency,
    ...(input.now ? { now: input.now } : {}),
  });
  const completedFamily = await input.repository.getFamily(selected.familyId);
  if (!completedFamily) throw new Error("prompt_optimizer_shadow_completed_family_missing");
  const runs = await input.repository.listRuns(complete.experimentId);
  const decision = PromptPromotionDecisionSchema.parse(
    createPromptPromotionDecision({
      experiment: complete,
      family: completedFamily,
      split: plan.split,
      runs,
      policy: plan.promotionPolicy,
      decidedAt: input.now?.() ?? new Date().toISOString(),
    }),
  );
  await input.repository.putDecision(decision);
  return { family: completedFamily, experiment: complete, decision };
}

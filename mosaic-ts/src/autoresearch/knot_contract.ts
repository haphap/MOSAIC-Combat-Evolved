import { createHash } from "node:crypto";
import { z } from "zod";

export const KnotResearchScoreContractSchema = z
  .object({
    research_score_contract_id: z.literal("knot-research-score"),
    research_score_contract_version: z.literal("knot_research_score_v2"),
    research_score_contract_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    normalized_inference_cost_formula: z.literal("HALF_INPUT_CAP_RATIO_PLUS_HALF_OUTPUT_CAP_RATIO"),
    input_token_cost_weight: z.literal(0.5),
    output_token_cost_weight: z.literal(0.5),
    sector_inference_cost_penalty_per_unit: z.literal(0.2),
    sector_conflict_review_penalty: z.literal(0.05),
    maximum_sector_success_penalty: z.literal(0.25),
    sector_success_score_range: z.tuple([z.literal(-1.25), z.literal(1)]),
    non_sector_success_score_range: z.tuple([z.literal(-1), z.literal(1)]),
    agent_failure_score: z.literal(-2),
    promotion_mean_delta_floor: z.literal(0.05),
    rollback_mean_delta_ceiling: z.literal(-0.05),
  })
  .strict();

export const KnotSchedulerContractSchema = z
  .object({
    scheduler_contract_id: z.literal("knot-scheduler"),
    scheduler_contract_version: z.literal("knot_scheduler_v2"),
    scheduler_contract_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    minimum_accountable_pairs: z.literal(30),
    block_bootstrap_resamples: z.literal(2000),
    block_bootstrap_block_length: z.literal(5),
    confidence_level: z.literal(0.95),
    benjamini_hochberg_q_max: z.literal(0.05),
    candidate_reliability_tolerance: z.literal(0.05),
    holdout_regime_degradation_max: z.literal(0.05),
    post_promotion_shadow_pairs: z.literal(20),
    rollback_reliability_gap: z.literal(0.1),
    self_scope_q2_minimum: z.literal(0),
    self_scope_operational_reliability_floor: z.literal(0.8),
    rollback_cooldown_research_slots: z.literal(20),
    layer_active_candidate_quotas: z
      .object({
        MACRO: z.literal(1),
        SECTOR: z.literal(1),
        SUPERINVESTOR: z.literal(1),
        DECISION: z.literal(1),
      })
      .strict(),
    source_window_kind: z.literal("FIRST_N_ACCOUNTABLE_NON_OVERLAPPING_PAIRS"),
    agent_failure_score_included: z.literal(true),
    exogenous_exclusion_included: z.literal(false),
    decision_usage_weight_enabled: z.literal(false),
  })
  .strict();

export const KnotRuntimeContractManifestSchema = z
  .object({
    knot_runtime_contract_manifest_id: z.literal("knot-runtime-contract"),
    knot_runtime_contract_manifest_version: z.literal("knot_runtime_contract_manifest_v2"),
    knot_runtime_contract_manifest_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    research_score_contract: KnotResearchScoreContractSchema,
    scheduler_contract: KnotSchedulerContractSchema,
  })
  .strict();

export type KnotRuntimeContractManifest = z.infer<typeof KnotRuntimeContractManifestSchema>;

export const KNOT_RESEARCH_SCORE_CONTRACT = withHash(
  {
    research_score_contract_id: "knot-research-score" as const,
    research_score_contract_version: "knot_research_score_v2" as const,
    normalized_inference_cost_formula: "HALF_INPUT_CAP_RATIO_PLUS_HALF_OUTPUT_CAP_RATIO" as const,
    input_token_cost_weight: 0.5 as const,
    output_token_cost_weight: 0.5 as const,
    sector_inference_cost_penalty_per_unit: 0.2 as const,
    sector_conflict_review_penalty: 0.05 as const,
    maximum_sector_success_penalty: 0.25 as const,
    sector_success_score_range: [-1.25, 1] as const,
    non_sector_success_score_range: [-1, 1] as const,
    agent_failure_score: -2 as const,
    promotion_mean_delta_floor: 0.05 as const,
    rollback_mean_delta_ceiling: -0.05 as const,
  },
  "research_score_contract_hash",
);

export const KNOT_SCHEDULER_CONTRACT = withHash(
  {
    scheduler_contract_id: "knot-scheduler" as const,
    scheduler_contract_version: "knot_scheduler_v2" as const,
    minimum_accountable_pairs: 30 as const,
    block_bootstrap_resamples: 2000 as const,
    block_bootstrap_block_length: 5 as const,
    confidence_level: 0.95 as const,
    benjamini_hochberg_q_max: 0.05 as const,
    candidate_reliability_tolerance: 0.05 as const,
    holdout_regime_degradation_max: 0.05 as const,
    post_promotion_shadow_pairs: 20 as const,
    rollback_reliability_gap: 0.1 as const,
    self_scope_q2_minimum: 0 as const,
    self_scope_operational_reliability_floor: 0.8 as const,
    rollback_cooldown_research_slots: 20 as const,
    layer_active_candidate_quotas: {
      MACRO: 1 as const,
      SECTOR: 1 as const,
      SUPERINVESTOR: 1 as const,
      DECISION: 1 as const,
    },
    source_window_kind: "FIRST_N_ACCOUNTABLE_NON_OVERLAPPING_PAIRS" as const,
    agent_failure_score_included: true as const,
    exogenous_exclusion_included: false as const,
    decision_usage_weight_enabled: false as const,
  },
  "scheduler_contract_hash",
);

export const KNOT_RUNTIME_CONTRACT_MANIFEST: KnotRuntimeContractManifest = (() => {
  const withoutHash = {
    knot_runtime_contract_manifest_id: "knot-runtime-contract" as const,
    knot_runtime_contract_manifest_version: "knot_runtime_contract_manifest_v2" as const,
    research_score_contract: KNOT_RESEARCH_SCORE_CONTRACT,
    scheduler_contract: KNOT_SCHEDULER_CONTRACT,
  };
  return KnotRuntimeContractManifestSchema.parse({
    ...withoutHash,
    knot_runtime_contract_manifest_hash: canonicalHash(withoutHash),
  });
})();

export function normalizedSectorInferenceCost(input: {
  inputTokens: number;
  outputTokens: number;
  totalStageInputTokenCap: number;
  totalStageOutputTokenCap: number;
}): number {
  for (const [field, value] of Object.entries(input)) {
    if (!Number.isFinite(value) || value < 0) throw new Error(`invalid_${field}`);
  }
  if (input.totalStageInputTokenCap <= 0 || input.totalStageOutputTokenCap <= 0) {
    throw new Error("knot_sector_token_caps_must_be_positive");
  }
  return (
    0.5 * Math.min(input.inputTokens / input.totalStageInputTokenCap, 1) +
    0.5 * Math.min(input.outputTokens / input.totalStageOutputTokenCap, 1)
  );
}

export function knotResearchComparisonScore(
  input:
    | { disposition: "AGENT_FAILURE"; agentKind: "STANDARD_SECTOR" | "NON_SECTOR" }
    | { disposition: "SCORE"; agentKind: "NON_SECTOR"; normalizedScore: number }
    | {
        disposition: "SCORE";
        agentKind: "STANDARD_SECTOR";
        normalizedScore: number;
        normalizedInferenceCost: number;
        conflictReviewTriggered: boolean;
      },
): {
  raw_research_score: number;
  sector_cost_adjusted_score: number | null;
  research_comparison_score: number;
} {
  if (input.disposition === "AGENT_FAILURE") {
    return {
      raw_research_score: -2,
      sector_cost_adjusted_score: null,
      research_comparison_score: -2,
    };
  }
  if (
    !Number.isFinite(input.normalizedScore) ||
    input.normalizedScore < -1 ||
    input.normalizedScore > 1
  ) {
    throw new Error("knot_normalized_score_out_of_range");
  }
  if (input.agentKind === "NON_SECTOR") {
    return {
      raw_research_score: input.normalizedScore,
      sector_cost_adjusted_score: null,
      research_comparison_score: input.normalizedScore,
    };
  }
  if (
    !Number.isFinite(input.normalizedInferenceCost) ||
    input.normalizedInferenceCost < 0 ||
    input.normalizedInferenceCost > 1
  ) {
    throw new Error("knot_normalized_inference_cost_out_of_range");
  }
  const adjusted =
    input.normalizedScore -
    0.2 * input.normalizedInferenceCost -
    0.05 * Number(input.conflictReviewTriggered);
  return {
    raw_research_score: input.normalizedScore,
    sector_cost_adjusted_score: adjusted,
    research_comparison_score: adjusted,
  };
}

export function renderKnotRuntimeContractManifestArtifact(): string {
  return `${JSON.stringify(KNOT_RUNTIME_CONTRACT_MANIFEST, null, 2)}\n`;
}

function withHash<T extends object, K extends string>(value: T, key: K): T & Record<K, string> {
  return { ...value, [key]: canonicalHash(value) } as T & Record<K, string>;
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

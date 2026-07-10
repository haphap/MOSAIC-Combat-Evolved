import { createHash } from "node:crypto";
import { z } from "zod";

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const CommitRefSchema = z.string().min(7);

export const ReleasePromptStageSchema = z.enum([
  "agent_run",
  "alpha_discovery",
  "cio_proposal",
  "cro_review",
  "execution_feasibility",
  "cio_final",
]);

const ReleasePromptFileSchema = z
  .object({
    path: z.string().min(1),
    sha256: Sha256Schema,
  })
  .strict();

export const ReleasePromptPairSchema = z
  .object({
    agent: z.string().min(1),
    layer: z.enum(["macro", "sector", "superinvestor", "decision"]),
    cohort: z.string().min(1),
    stages: z.array(ReleasePromptStageSchema).min(1),
    zh: ReleasePromptFileSchema,
    en: ReleasePromptFileSchema,
    pair_hash: Sha256Schema,
  })
  .strict();

export type ReleasePromptPair = z.infer<typeof ReleasePromptPairSchema>;

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value === undefined ? null : value;
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

export function releasePromptPairHash(pair: Omit<ReleasePromptPair, "pair_hash">): string {
  return canonicalHash({
    schema_version: "release_prompt_pair_v1",
    agent: pair.agent,
    layer: pair.layer,
    cohort: pair.cohort,
    stages: pair.stages,
    zh: pair.zh,
    en: pair.en,
  });
}

export function releasePromptSetHash(pairs: ReadonlyArray<ReleasePromptPair>): string {
  const ordered = [...pairs].sort((left, right) =>
    `${left.cohort}:${left.agent}`.localeCompare(`${right.cohort}:${right.agent}`),
  );
  return canonicalHash({
    schema_version: "release_prompt_set_v1",
    prompt_pairs: ordered,
  });
}

export interface RequiredReleasePromptStage {
  agent: string;
  layer: ReleasePromptPair["layer"];
  stage: ReleasePromptPair["stages"][number];
}

function missingStageKeys(
  pairs: ReadonlyArray<ReleasePromptPair>,
  cohort: string,
  required: ReadonlyArray<RequiredReleasePromptStage>,
): string[] {
  return required.flatMap((expected) => {
    const matches = pairs.filter(
      (pair) =>
        pair.cohort === cohort &&
        pair.agent === expected.agent &&
        pair.layer === expected.layer &&
        pair.stages.includes(expected.stage),
    );
    return matches.length === 1 ? [] : [`${expected.agent}:${expected.stage}:${matches.length}`];
  });
}

export function assertReleasePromptStageClosure(
  manifest: ActivePromptReleaseManifest,
  required: ReadonlyArray<RequiredReleasePromptStage>,
): void {
  ActivePromptReleaseManifestSchema.parse(manifest);
  const missing = missingStageKeys(
    manifest.prompt_pairs,
    manifest.activation_scope.cohort,
    required,
  );
  if (missing.length > 0) {
    throw new Error(`prompt_release_stage_closure_incomplete:${missing.join(",")}`);
  }
  if (manifest.bundled_fallback) {
    const fallbackMissing = missingStageKeys(
      manifest.bundled_fallback.prompt_pairs,
      manifest.activation_scope.cohort,
      required,
    );
    if (fallbackMissing.length > 0) {
      throw new Error(
        `prompt_release_fallback_stage_closure_incomplete:${fallbackMissing.join(",")}`,
      );
    }
  }
}

function validatePromptPairs(
  pairs: ReadonlyArray<ReleasePromptPair>,
  expectedCohort: string,
  ctx: z.RefinementCtx,
  path: Array<string | number>,
): void {
  const seenPairs = new Set<string>();
  const seenStages = new Set<string>();
  for (const [index, pair] of pairs.entries()) {
    const pairKey = `${pair.cohort}:${pair.agent}`;
    if (seenPairs.has(pairKey)) {
      ctx.addIssue({ code: "custom", path: [...path, index], message: "duplicate prompt pair" });
    }
    seenPairs.add(pairKey);
    if (pair.cohort !== expectedCohort) {
      ctx.addIssue({
        code: "custom",
        path: [...path, index, "cohort"],
        message: "prompt pair cohort must match activation scope",
      });
    }
    const expectedBase = `prompts/mosaic/${pair.cohort}/${pair.layer}/${pair.agent}`;
    if (pair.zh.path !== `${expectedBase}.zh.md` || pair.en.path !== `${expectedBase}.en.md`) {
      ctx.addIssue({
        code: "custom",
        path: [...path, index],
        message: "prompt pair paths do not match the declared cohort/agent/layer",
      });
    }
    if (pair.pair_hash !== releasePromptPairHash(pair)) {
      ctx.addIssue({
        code: "custom",
        path: [...path, index, "pair_hash"],
        message: "prompt pair hash mismatch",
      });
    }
    for (const stage of pair.stages) {
      const stageKey = `${pair.agent}:${stage}`;
      if (seenStages.has(stageKey)) {
        ctx.addIssue({
          code: "custom",
          path: [...path, index, "stages"],
          message: "duplicate agent stage binding",
        });
      }
      seenStages.add(stageKey);
    }
  }
}

export const MutationTransactionStateSchema = z.enum([
  "created",
  "prepared",
  "committed_log_pending",
  "committed",
  "aborted",
]);

export const MutationTransactionManifestSchema = z
  .object({
    schema_version: z.literal("prompt_mutation_transaction_v1"),
    mutation_id: z.string().min(1),
    transaction_id: z.string().min(1),
    experiment_id: z.string().min(1),
    state: MutationTransactionStateSchema,
    recovery_state: z.enum(["not_needed", "pending", "reconciled"]),
    base_release_id: z.string().min(1),
    catalog_hash: Sha256Schema,
    schema_hash: Sha256Schema,
    evaluation_contract_hash: Sha256Schema,
    target_paths: z.array(z.string().startsWith("/")).min(1),
    components: z
      .array(
        z
          .object({
            repo_id: z.string().min(1),
            base_commit: CommitRefSchema,
            new_commit: CommitRefSchema.nullable(),
            candidate_ref: z.string().min(1),
            prepare_status: z.enum(["pending", "prepared", "aborted"]),
            files: z
              .array(
                z
                  .object({
                    path: z.string().min(1),
                    old_hash: Sha256Schema,
                    new_hash: Sha256Schema,
                    staging_path_hash: Sha256Schema,
                  })
                  .strict(),
              )
              .min(1),
          })
          .strict(),
      )
      .min(1),
    metadata_log: z
      .object({
        path: z.string().min(1),
        entry_hash: Sha256Schema,
        appended: z.boolean(),
      })
      .strict(),
    created_at: z.string().min(1),
    prepared_at: z.string().min(1).nullable(),
    committed_at: z.string().min(1).nullable(),
    aborted_at: z.string().min(1).nullable(),
    recovery_decision: z.string().min(1).nullable(),
  })
  .strict()
  .superRefine((manifest, ctx) => {
    if (["prepared", "committed_log_pending", "committed"].includes(manifest.state)) {
      if (!manifest.prepared_at) {
        ctx.addIssue({ code: "custom", path: ["prepared_at"], message: "required by state" });
      }
      if (manifest.components.some((component) => component.prepare_status !== "prepared")) {
        ctx.addIssue({
          code: "custom",
          path: ["components"],
          message: "all components must be prepared",
        });
      }
    }
    if (["committed_log_pending", "committed"].includes(manifest.state)) {
      if (manifest.components.some((component) => !component.new_commit)) {
        ctx.addIssue({
          code: "custom",
          path: ["components"],
          message: "all committed components require new_commit",
        });
      }
    }
    if (manifest.state === "committed" && !manifest.metadata_log.appended) {
      ctx.addIssue({
        code: "custom",
        path: ["metadata_log", "appended"],
        message: "committed transaction requires durable metadata log",
      });
    }
    if (manifest.state === "committed_log_pending" && manifest.metadata_log.appended) {
      ctx.addIssue({
        code: "custom",
        path: ["metadata_log", "appended"],
        message: "log-pending state cannot claim append success",
      });
    }
    if (manifest.state === "aborted" && !manifest.aborted_at) {
      ctx.addIssue({ code: "custom", path: ["aborted_at"], message: "required by state" });
    }
    if (
      manifest.recovery_state === "reconciled" &&
      !["committed", "aborted"].includes(manifest.state)
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["recovery_state"],
        message: "reconciled transaction must have a final factual state",
      });
    }
  });

export const ActivePromptReleaseManifestSchema = z
  .object({
    schema_version: z.literal("active_prompt_release_manifest_v1"),
    release_id: z.string().min(1),
    base_release_id: z.string().min(1).nullable(),
    lifecycle_state: z.enum(["staged", "canary", "active", "rolled_back"]),
    prompt_commit: CommitRefSchema,
    code_commit: CommitRefSchema,
    prompt_hash: Sha256Schema,
    prompt_pairs: z.array(ReleasePromptPairSchema).min(1),
    catalog_hash: Sha256Schema,
    schema_hash: Sha256Schema,
    evaluation_contract_hash: Sha256Schema,
    keep_decision_hash: Sha256Schema,
    keep_decision_state: z.literal("kept"),
    activation_scope: z
      .object({
        cohort: z.string().min(1),
        account_mode: z.enum(["paper", "backtest", "live"]),
        traffic_percent: z.number().min(0).max(100),
      })
      .strict(),
    approval_policy_id: z.string().min(1),
    approved_by: z.string().min(1).nullable(),
    canary_started_at: z.string().min(1).nullable(),
    canary_ended_at: z.string().min(1).nullable(),
    runtime_slo_summary: z
      .object({
        passed: z.boolean(),
        schema_failure_rate: z.number().min(0).max(1),
        fallback_rate: z.number().min(0).max(1),
        source_failure_rate: z.number().min(0).max(1),
        validator_rejection_rate: z.number().min(0).max(1),
        duplicate_order_intent_count: z.number().int().min(0),
        exposure_breach_count: z.number().int().min(0),
      })
      .strict()
      .nullable(),
    rollback_triggers: z.array(z.string().min(1)).min(1),
    previous_approved_release_id: z.string().min(1).nullable(),
    bundled_fallback: z
      .object({
        prompt_commit: CommitRefSchema,
        prompt_hash: Sha256Schema,
        prompt_pairs: z.array(ReleasePromptPairSchema).min(1),
        schema_hash: Sha256Schema,
        catalog_hash: Sha256Schema,
      })
      .strict()
      .nullable(),
    created_at: z.string().min(1),
    activated_at: z.string().min(1).nullable(),
    rolled_back_at: z.string().min(1).nullable(),
  })
  .strict()
  .superRefine((manifest, ctx) => {
    validatePromptPairs(manifest.prompt_pairs, manifest.activation_scope.cohort, ctx, [
      "prompt_pairs",
    ]);
    if (manifest.prompt_hash !== releasePromptSetHash(manifest.prompt_pairs)) {
      ctx.addIssue({
        code: "custom",
        path: ["prompt_hash"],
        message: "release prompt set hash mismatch",
      });
    }
    if (manifest.bundled_fallback) {
      validatePromptPairs(
        manifest.bundled_fallback.prompt_pairs,
        manifest.activation_scope.cohort,
        ctx,
        ["bundled_fallback", "prompt_pairs"],
      );
      if (
        manifest.bundled_fallback.prompt_hash !==
        releasePromptSetHash(manifest.bundled_fallback.prompt_pairs)
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["bundled_fallback", "prompt_hash"],
          message: "bundled fallback prompt set hash mismatch",
        });
      }
    }
    if (["canary", "active", "rolled_back"].includes(manifest.lifecycle_state)) {
      if (!manifest.approved_by) {
        ctx.addIssue({ code: "custom", path: ["approved_by"], message: "approval required" });
      }
      if (!manifest.canary_started_at) {
        ctx.addIssue({
          code: "custom",
          path: ["canary_started_at"],
          message: "canary start required",
        });
      }
    }
    if (manifest.lifecycle_state === "active") {
      if (!manifest.canary_ended_at || !manifest.activated_at) {
        ctx.addIssue({
          code: "custom",
          path: ["activated_at"],
          message: "active release requires completed canary timestamps",
        });
      }
      if (!manifest.runtime_slo_summary?.passed) {
        ctx.addIssue({
          code: "custom",
          path: ["runtime_slo_summary"],
          message: "active release requires passing runtime SLOs",
        });
      }
      if (manifest.activation_scope.traffic_percent !== 100) {
        ctx.addIssue({
          code: "custom",
          path: ["activation_scope", "traffic_percent"],
          message: "active release requires full scoped activation",
        });
      }
    }
    if (manifest.lifecycle_state === "rolled_back" && !manifest.rolled_back_at) {
      ctx.addIssue({
        code: "custom",
        path: ["rolled_back_at"],
        message: "rolled-back release requires timestamp",
      });
    }
  });

export type MutationTransactionState = z.infer<typeof MutationTransactionStateSchema>;
export type MutationTransactionManifest = z.infer<typeof MutationTransactionManifestSchema>;
export type ActivePromptReleaseManifest = z.infer<typeof ActivePromptReleaseManifestSchema>;

const TRANSACTION_TRANSITIONS: Readonly<Record<MutationTransactionState, ReadonlySet<string>>> = {
  created: new Set(["prepared", "aborted"]),
  prepared: new Set(["committed_log_pending", "aborted"]),
  committed_log_pending: new Set(["committed"]),
  committed: new Set(),
  aborted: new Set(),
};

export function assertMutationTransactionTransition(
  previous: MutationTransactionManifest,
  next: MutationTransactionManifest,
): void {
  if (
    previous.transaction_id !== next.transaction_id ||
    previous.mutation_id !== next.mutation_id
  ) {
    throw new Error("mutation_transaction_identity_changed");
  }
  if (!TRANSACTION_TRANSITIONS[previous.state].has(next.state)) {
    throw new Error(`mutation_transaction_transition_invalid:${previous.state}:${next.state}`);
  }
  MutationTransactionManifestSchema.parse(next);
}

const RELEASE_TRANSITIONS: Readonly<
  Record<ActivePromptReleaseManifest["lifecycle_state"], ReadonlySet<string>>
> = {
  staged: new Set(["canary"]),
  canary: new Set(["active", "rolled_back"]),
  active: new Set(["rolled_back"]),
  rolled_back: new Set(),
};

export function assertPromptReleaseTransition(
  previous: ActivePromptReleaseManifest,
  next: ActivePromptReleaseManifest,
): void {
  if (previous.release_id !== next.release_id) throw new Error("prompt_release_identity_changed");
  if (!RELEASE_TRANSITIONS[previous.lifecycle_state].has(next.lifecycle_state)) {
    throw new Error(
      `prompt_release_transition_invalid:${previous.lifecycle_state}:${next.lifecycle_state}`,
    );
  }
  ActivePromptReleaseManifestSchema.parse(next);
}

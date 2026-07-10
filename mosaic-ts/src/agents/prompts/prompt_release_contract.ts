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
    recovery_descriptor_hash: Sha256Schema,
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
    stage_snapshot_hashes: z.record(z.string().min(1), Sha256Schema),
    catalog_hash: Sha256Schema,
    schema_hash: Sha256Schema,
    evaluation_contract_hash: Sha256Schema,
    keep_decision_hash: Sha256Schema,
    keep_decision_state: z.literal("kept"),
    release_evidence: z
      .object({
        version_id: z.number().int().min(1),
        mutation_id: z.string().min(1),
        experiment_id: z.string().min(1),
        mutated_agent: z.string().min(1),
        evaluation_result_hash: Sha256Schema,
        transaction_manifest_hash: Sha256Schema,
        prompt_pair_sha256: z.string().regex(/^[0-9a-f]{64}$/),
      })
      .strict(),
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
        sample_count: z.number().int().min(20),
        schema_failure_rate: z.number().min(0).max(1),
        fallback_rate: z.number().min(0).max(1),
        source_failure_rate: z.number().min(0).max(1),
        unsupported_influence_rejection_rate: z.number().min(0).max(1),
        validator_rejection_rate: z.number().min(0).max(1),
        latency_p95_ms: z.number().nonnegative(),
        token_budget_breach_count: z.number().int().min(0),
        duplicate_order_intent_count: z.number().int().min(0),
        exposure_breach_count: z.number().int().min(0),
      })
      .strict()
      .nullable(),
    runtime_slo_evidence: z
      .object({
        schema_version: z.literal("prompt_release_canary_slo_evidence_v1"),
        release_id: z.string().min(1),
        account_mode: z.enum(["paper", "backtest", "live"]),
        traffic_percent: z.number().gt(0).lt(100),
        canary_started_at: z.string().min(1),
        observation_ended_at: z.string().min(1),
        eligible_event_count: z.number().int().min(1),
        excluded_event_count: z.number().int().min(0),
        excluded_count_by_reason: z.record(z.string(), z.number().int().min(0)),
        event_set_hash: Sha256Schema,
        stage_snapshot_hashes_hash: Sha256Schema,
        aggregator_id: z.string().min(1),
        aggregator_version: z.string().min(1),
        artifact_hash: Sha256Schema,
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
    const expectedStageKeys = new Set(
      manifest.prompt_pairs.flatMap((pair) => pair.stages.map((stage) => `${pair.agent}:${stage}`)),
    );
    const actualStageKeys = new Set(Object.keys(manifest.stage_snapshot_hashes));
    if (
      expectedStageKeys.size !== actualStageKeys.size ||
      [...expectedStageKeys].some((key) => !actualStageKeys.has(key))
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["stage_snapshot_hashes"],
        message: "stage snapshot hashes must exactly cover every release stage",
      });
    }
    if (
      manifest.prompt_pairs.filter((pair) => pair.agent === manifest.release_evidence.mutated_agent)
        .length !== 1
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["release_evidence", "mutated_agent"],
        message: "release evidence must identify exactly one prompt pair",
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
      if (
        !manifest.runtime_slo_summary?.passed ||
        !promptReleaseRuntimeSloPasses(manifest.runtime_slo_summary)
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["runtime_slo_summary"],
          message: "active release requires passing runtime SLOs",
        });
      }
      const evidence = manifest.runtime_slo_evidence;
      if (
        !evidence ||
        evidence.release_id !== manifest.release_id ||
        evidence.account_mode !== manifest.activation_scope.account_mode ||
        evidence.traffic_percent >= 100 ||
        evidence.canary_started_at !== manifest.canary_started_at ||
        evidence.eligible_event_count !== manifest.runtime_slo_summary?.sample_count
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["runtime_slo_evidence"],
          message: "active release requires closed canary SLO evidence",
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
    if (
      manifest.runtime_slo_summary &&
      manifest.runtime_slo_summary.passed !==
        promptReleaseRuntimeSloPasses(manifest.runtime_slo_summary)
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["runtime_slo_summary", "passed"],
        message: "runtime SLO passed flag does not match the measured thresholds",
      });
    }
    if (manifest.lifecycle_state === "rolled_back" && !manifest.rolled_back_at) {
      ctx.addIssue({
        code: "custom",
        path: ["rolled_back_at"],
        message: "rolled-back release requires timestamp",
      });
    }
    if (!manifest.activated_at && manifest.runtime_slo_evidence !== null) {
      ctx.addIssue({
        code: "custom",
        path: ["runtime_slo_evidence"],
        message: "pre-activation release cannot contain SLO evidence",
      });
    }
  });

export type MutationTransactionState = z.infer<typeof MutationTransactionStateSchema>;
export type MutationTransactionManifest = z.infer<typeof MutationTransactionManifestSchema>;
export type ActivePromptReleaseManifest = z.infer<typeof ActivePromptReleaseManifestSchema>;

export function promptReleaseRuntimeSloPasses(
  summary: NonNullable<ActivePromptReleaseManifest["runtime_slo_summary"]>,
): boolean {
  return (
    summary.sample_count >= 20 &&
    summary.schema_failure_rate === 0 &&
    summary.fallback_rate <= 0.1 &&
    summary.source_failure_rate <= 0.05 &&
    summary.unsupported_influence_rejection_rate <= 0.05 &&
    summary.validator_rejection_rate <= 0.05 &&
    summary.latency_p95_ms <= 120_000 &&
    summary.token_budget_breach_count === 0 &&
    summary.duplicate_order_intent_count === 0 &&
    summary.exposure_breach_count === 0
  );
}

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

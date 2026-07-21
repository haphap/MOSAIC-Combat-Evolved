import { z } from "zod";
import { RuntimeBehaviorBundleRefSchema } from "../../autoresearch/runtime_behavior_bundle.js";
import { canonicalJsonHash } from "../helpers/canonical_json.js";

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

function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
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

const ActivePromptReleaseManifestV1ObjectSchema = z
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
        schema_version: z.enum([
          "prompt_release_canary_slo_evidence_v1",
          "prompt_release_canary_slo_evidence_v2",
        ]),
        release_id: z.string().min(1),
        account_mode: z.enum(["paper", "backtest", "live"]),
        traffic_percent: z.number().gt(0).lt(100),
        canary_started_at: z.string().min(1),
        observation_ended_at: z.string().min(1),
        eligible_event_count: z.number().int().min(1),
        excluded_event_count: z.number().int().min(0),
        excluded_count_by_reason: z.record(z.string(), z.number().int().min(0)),
        event_set_hash: Sha256Schema,
        journal_closure_hash: Sha256Schema.optional(),
        journal_record_count: z.number().int().min(1).optional(),
        stage_snapshot_hashes_hash: Sha256Schema,
        aggregator_id: z.string().min(1),
        aggregator_version: z.string().min(1),
        artifact_hash: Sha256Schema,
      })
      .strict()
      .superRefine((evidence, ctx) => {
        const isV2 = evidence.schema_version === "prompt_release_canary_slo_evidence_v2";
        const hasJournalClosure =
          evidence.journal_closure_hash !== undefined &&
          evidence.journal_record_count !== undefined;
        if (isV2 !== hasJournalClosure) {
          ctx.addIssue({
            code: "custom",
            path: ["journal_closure_hash"],
            message: "v2 SLO evidence requires a closed journal snapshot",
          });
        }
        if (
          evidence.aggregator_id !== "prompt_release_canary_slo" ||
          evidence.aggregator_version !== (isV2 ? "2" : "1")
        ) {
          ctx.addIssue({
            code: "custom",
            path: ["aggregator_version"],
            message: "SLO evidence aggregator identity does not match its schema version",
          });
        }
      })
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
  .strict();

export const ActivePromptReleaseManifestV1Schema =
  ActivePromptReleaseManifestV1ObjectSchema.superRefine((manifest, ctx) => {
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

const PromptBehaviorReleaseEvidenceSchema =
  ActivePromptReleaseManifestV1ObjectSchema.shape.release_evidence
    .extend({
      kind: z.literal("PROMPT_BEHAVIOR"),
      base_prompt_hash: Sha256Schema,
      candidate_prompt_hash: Sha256Schema,
    })
    .strict();

const PrivateExecutionPolicyReleaseEvidenceSchema = z
  .object({
    kind: z.literal("PRIVATE_EXECUTION_POLICY"),
    agent_id: z.string().min(1),
    effect_id: z.string().min(1),
    track_id: z.string().min(1),
    candidate_receipt_hash: Sha256Schema,
    promotion_gate_hash: Sha256Schema,
    base_prompt_hash: Sha256Schema,
    candidate_prompt_hash: Sha256Schema,
  })
  .strict();

const BaselineMigrationReleaseEvidenceSchema = z
  .object({
    kind: z.literal("BASELINE_MIGRATION"),
    migration_id: z.string().min(1),
    migration_evidence_hash: Sha256Schema,
  })
  .strict();

const ForwardRecoveryReleaseEvidenceSchema = z
  .object({
    kind: z.literal("FORWARD_RECOVERY"),
    rolled_back_release_id: z.string().min(1),
    recovery_evidence_hash: Sha256Schema,
  })
  .strict();

export const FullRuntimeReleaseEvidenceSchema = z.discriminatedUnion("kind", [
  PromptBehaviorReleaseEvidenceSchema,
  PrivateExecutionPolicyReleaseEvidenceSchema,
  BaselineMigrationReleaseEvidenceSchema,
  ForwardRecoveryReleaseEvidenceSchema,
]);

const ActivePromptReleaseManifestV2ObjectSchema = ActivePromptReleaseManifestV1ObjectSchema.omit({
  schema_version: true,
  release_evidence: true,
})
  .extend({
    schema_version: z.literal("active_prompt_release_manifest_v2"),
    release_evidence: FullRuntimeReleaseEvidenceSchema,
    runtime_behavior_bundle: RuntimeBehaviorBundleRefSchema,
  })
  .strict();

export const ActivePromptReleaseManifestV2Schema =
  ActivePromptReleaseManifestV2ObjectSchema.superRefine((manifest, ctx) => {
    const firstPair = manifest.prompt_pairs[0];
    if (!firstPair) return;
    const legacyEvidence =
      manifest.release_evidence.kind === "PROMPT_BEHAVIOR"
        ? {
            version_id: manifest.release_evidence.version_id,
            mutation_id: manifest.release_evidence.mutation_id,
            experiment_id: manifest.release_evidence.experiment_id,
            mutated_agent: manifest.release_evidence.mutated_agent,
            evaluation_result_hash: manifest.release_evidence.evaluation_result_hash,
            transaction_manifest_hash: manifest.release_evidence.transaction_manifest_hash,
            prompt_pair_sha256: manifest.release_evidence.prompt_pair_sha256,
          }
        : {
            version_id: 1,
            mutation_id: `v2:${manifest.release_evidence.kind}`,
            experiment_id: `v2:${manifest.release_evidence.kind}`,
            mutated_agent: firstPair.agent,
            evaluation_result_hash: manifest.keep_decision_hash,
            transaction_manifest_hash: manifest.keep_decision_hash,
            prompt_pair_sha256: firstPair.pair_hash.slice("sha256:".length),
          };
    const { runtime_behavior_bundle: _runtimeBundle, ...legacyManifest } = manifest;
    const legacyCheck = ActivePromptReleaseManifestV1Schema.safeParse({
      ...legacyManifest,
      schema_version: "active_prompt_release_manifest_v1",
      release_evidence: legacyEvidence,
    });
    if (!legacyCheck.success) {
      for (const issue of legacyCheck.error.issues) {
        ctx.addIssue({ code: "custom", path: issue.path, message: issue.message });
      }
    }

    const bundle = manifest.runtime_behavior_bundle;
    for (const [path, expected, actual] of [
      ["prompt_hash", manifest.prompt_hash, bundle.prompt_hash],
      ["catalog_hash", manifest.catalog_hash, bundle.catalog_hash],
      [
        "evaluation_contract_hash",
        manifest.evaluation_contract_hash,
        bundle.evaluation_contract_hash,
      ],
      ["schema_hash", manifest.schema_hash, bundle.schema_hash],
    ] as const) {
      if (expected !== actual) {
        ctx.addIssue({
          code: "custom",
          path: ["runtime_behavior_bundle", path],
          message: `runtime behavior bundle ${path} does not match release closure`,
        });
      }
    }

    const evidence = manifest.release_evidence;
    const origin = bundle.origin;
    const expectedOrigin =
      evidence.kind === "PROMPT_BEHAVIOR" || evidence.kind === "PRIVATE_EXECUTION_POLICY"
        ? "KNOT_PROMOTION"
        : evidence.kind;
    if (origin.kind !== expectedOrigin) {
      ctx.addIssue({
        code: "custom",
        path: ["runtime_behavior_bundle", "origin", "kind"],
        message: "runtime behavior bundle origin does not match release evidence",
      });
    }
    if (evidence.kind === "PROMPT_BEHAVIOR" || evidence.kind === "PRIVATE_EXECUTION_POLICY") {
      if (evidence.candidate_prompt_hash !== manifest.prompt_hash) {
        ctx.addIssue({
          code: "custom",
          path: ["release_evidence", "candidate_prompt_hash"],
          message: "candidate prompt hash does not match release prompt hash",
        });
      }
      if (
        evidence.kind === "PRIVATE_EXECUTION_POLICY" &&
        evidence.base_prompt_hash !== evidence.candidate_prompt_hash
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["release_evidence", "base_prompt_hash"],
          message: "private execution/policy releases must keep prompts byte-identical",
        });
      }
    }
    if (manifest.release_id !== deterministicFullRuntimeReleaseId(manifest)) {
      ctx.addIssue({
        code: "custom",
        path: ["release_id"],
        message: "full runtime release id mismatch",
      });
    }
  });

export const ActivePromptReleaseManifestSchema = z.union([
  ActivePromptReleaseManifestV1Schema,
  ActivePromptReleaseManifestV2Schema,
]);

export type ActivePromptReleaseManifest = z.infer<typeof ActivePromptReleaseManifestSchema>;
export type ActivePromptReleaseManifestV2 = z.infer<typeof ActivePromptReleaseManifestV2Schema>;

type FullRuntimeReleaseIdentityInput = Omit<
  ActivePromptReleaseManifestV2,
  | "release_id"
  | "lifecycle_state"
  | "approved_by"
  | "canary_started_at"
  | "canary_ended_at"
  | "runtime_slo_summary"
  | "runtime_slo_evidence"
  | "activated_at"
  | "rolled_back_at"
> & { release_id?: string };

export function deterministicFullRuntimeReleaseId(
  manifest: FullRuntimeReleaseIdentityInput,
): string {
  const identity = {
    schema_version: manifest.schema_version,
    base_release_id: manifest.base_release_id,
    prompt_commit: manifest.prompt_commit,
    code_commit: manifest.code_commit,
    prompt_hash: manifest.prompt_hash,
    prompt_pairs: manifest.prompt_pairs,
    stage_snapshot_hashes: manifest.stage_snapshot_hashes,
    catalog_hash: manifest.catalog_hash,
    schema_hash: manifest.schema_hash,
    evaluation_contract_hash: manifest.evaluation_contract_hash,
    keep_decision_hash: manifest.keep_decision_hash,
    keep_decision_state: manifest.keep_decision_state,
    release_evidence: manifest.release_evidence,
    activation_scope: {
      cohort: manifest.activation_scope.cohort,
      account_mode: manifest.activation_scope.account_mode,
    },
    approval_policy_id: manifest.approval_policy_id,
    rollback_triggers: manifest.rollback_triggers,
    previous_approved_release_id: manifest.previous_approved_release_id,
    bundled_fallback: manifest.bundled_fallback,
    created_at: manifest.created_at,
    runtime_behavior_bundle: manifest.runtime_behavior_bundle,
  };
  return `active-prompt-release:${canonicalHash(identity).slice("sha256:".length)}`;
}

export function assertFullRuntimePromptRelease(
  manifest: ActivePromptReleaseManifest,
): asserts manifest is ActivePromptReleaseManifestV2 {
  if (manifest.schema_version !== "active_prompt_release_manifest_v2") {
    throw new Error("prompt_release_runtime_requires_full_bundle_v2");
  }
  ActivePromptReleaseManifestV2Schema.parse(manifest);
}

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
  if (previous.schema_version !== next.schema_version) {
    throw new Error("prompt_release_schema_version_changed");
  }
  if (!RELEASE_TRANSITIONS[previous.lifecycle_state].has(next.lifecycle_state)) {
    throw new Error(
      `prompt_release_transition_invalid:${previous.lifecycle_state}:${next.lifecycle_state}`,
    );
  }
  ActivePromptReleaseManifestSchema.parse(next);
}

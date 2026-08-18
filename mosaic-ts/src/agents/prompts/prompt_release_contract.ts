import { z } from "zod";
import { CapabilityFullBundleV1Schema } from "../../autoresearch/capability_preservation_contract.js";
import { canonicalJsonHash, compareCanonicalStrings } from "../helpers/canonical_json.js";

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const CommitRefSchema = z.string().min(7);
const ExecutionBehaviorReleaseIdSchema = z
  .string()
  .regex(/^execution-behavior-release:[0-9a-f]{64}$/);

export const PromptReleaseExecutionBehaviorBindingSchema = z
  .object({
    release_id: ExecutionBehaviorReleaseIdSchema,
    release_hash: Sha256Schema,
    archive_ref: z
      .string()
      .regex(
        /^registry\/prompt_checks\/execution_behavior_releases\/[0-9a-f]{64}--[0-9a-f]{64}\.json$/,
      ),
  })
  .strict()
  .superRefine((binding, ctx) => {
    const expected =
      `registry/prompt_checks/execution_behavior_releases/` +
      `${binding.release_id.slice("execution-behavior-release:".length)}--` +
      `${binding.release_hash.slice("sha256:".length)}.json`;
    if (binding.archive_ref !== expected) {
      ctx.addIssue({
        code: "custom",
        path: ["archive_ref"],
        message: "execution behavior archive ref must match the bound release id and hash",
      });
    }
  });

export type PromptReleaseExecutionBehaviorBinding = z.infer<
  typeof PromptReleaseExecutionBehaviorBindingSchema
>;

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

export const PromptReleaseEvidenceSchema = z
  .object({
    candidate_id: z.string().min(1),
    candidate_hash: Sha256Schema,
    candidate_publication_hash: Sha256Schema,
    prompt_source_id: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$/),
    promotion_decision_id: z.string().min(1),
    promotion_decision_hash: Sha256Schema,
    experiment_id: z.string().min(1),
    mutated_agent: z.string().min(1),
    policy_version: z.string().min(1),
    policy_config_hash: Sha256Schema,
    candidate_prompt_hashes: z.object({ zh: Sha256Schema, en: Sha256Schema }).strict(),
    private_state_artifact_hash: Sha256Schema,
    behavior_contract_hash: Sha256Schema,
    mutator_commit: z.string().regex(/^[0-9a-f]{40}$/),
    mutator_config_hash: Sha256Schema,
  })
  .strict();

export const PromptReleaseRuntimeSloSummarySchema = z
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
  .strict();

export const PromptReleaseRuntimeSloEvidenceSchema = z
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
      evidence.journal_closure_hash !== undefined && evidence.journal_record_count !== undefined;
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
  });

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
    compareCanonicalStrings(`${left.cohort}:${left.agent}`, `${right.cohort}:${right.agent}`),
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

export const KnotGateDPairedEnvironmentV1Schema = z
  .object({
    model_config_hash: Sha256Schema,
    tool_config_hash: Sha256Schema,
    executor_adapter_hash: Sha256Schema,
    evaluator_adapter_hash: Sha256Schema,
    evaluator_config_hash: Sha256Schema,
    code_commit: z.string().regex(/^[0-9a-f]{40}$/),
    execution_behavior_release_hash: Sha256Schema,
    production_variant_roster_hash: Sha256Schema,
    repeat_seeds_hash: Sha256Schema,
    frozen_bundle_set_hash: Sha256Schema,
  })
  .strict();

export const KnotGateDStageEvidenceV1Schema = z
  .object({
    agent_id: z.string().min(1),
    stage: ReleasePromptStageSchema,
    experiment_target_stage: ReleasePromptStageSchema,
    experiment_id: z.string().min(1),
    experiment_hash: Sha256Schema,
    run_set_hash: Sha256Schema,
    training_projection_hash: Sha256Schema,
    paired_environment_hash: Sha256Schema,
  })
  .strict();

export const KnotGateDPublicPrivatePinV1Schema = z
  .object({
    public_commit: z.string().regex(/^[0-9a-f]{40}$/),
    public_tree_hash: Sha256Schema,
    private_commit: z.string().regex(/^[0-9a-f]{40}$/),
    private_tree_hash: Sha256Schema,
    private_companion_pin_hash: Sha256Schema,
    pair_hash: Sha256Schema,
  })
  .strict()
  .superRefine((pin, ctx) => {
    const { pair_hash: _, ...body } = pin;
    if (pin.pair_hash !== canonicalHash(body)) {
      ctx.addIssue({ code: "custom", path: ["pair_hash"], message: "paired pin hash mismatch" });
    }
  });

export const KnotGateDCandidateV1Schema = z
  .object({
    schema_version: z.literal("knot_gate_d_candidate_v1"),
    full_bundle_hash: Sha256Schema,
    runtime_agent_manifest_hash: Sha256Schema,
    runtime_stage_count: z.number().int().positive(),
    capability_binding_manifest_hash: Sha256Schema,
    binding_count: z.number().int().positive(),
    paired_environment: KnotGateDPairedEnvironmentV1Schema,
    paired_environment_hash: Sha256Schema,
    stage_evidence: z.array(KnotGateDStageEvidenceV1Schema).min(1),
    significance_fixture_hash: Sha256Schema,
    counterevidence_fixture_hash: Sha256Schema,
    cross_track_isolation_hash: Sha256Schema,
    public_safe_scan_hash: Sha256Schema,
    public_private_pin: KnotGateDPublicPrivatePinV1Schema,
    candidate_hash: Sha256Schema,
  })
  .strict()
  .superRefine((candidate, ctx) => {
    const expectedEnvironmentHash = canonicalHash(candidate.paired_environment);
    if (candidate.paired_environment_hash !== expectedEnvironmentHash) {
      ctx.addIssue({
        code: "custom",
        path: ["paired_environment_hash"],
        message: "paired environment hash mismatch",
      });
    }
    if (candidate.runtime_stage_count !== candidate.stage_evidence.length) {
      ctx.addIssue({
        code: "custom",
        path: ["runtime_stage_count"],
        message: "Gate D stage count mismatch",
      });
    }
    const stageKeys = candidate.stage_evidence.map((row) => `${row.agent_id}:${row.stage}`);
    if (new Set(stageKeys).size !== stageKeys.length) {
      ctx.addIssue({
        code: "custom",
        path: ["stage_evidence"],
        message: "duplicate Gate D stage evidence",
      });
    }
    if (
      candidate.stage_evidence.some(
        (row) => row.paired_environment_hash !== expectedEnvironmentHash,
      )
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["stage_evidence"],
        message: "Gate D stage environment drift",
      });
    }
    const { candidate_hash: _, ...body } = candidate;
    if (candidate.candidate_hash !== canonicalHash(body)) {
      ctx.addIssue({
        code: "custom",
        path: ["candidate_hash"],
        message: "Gate D candidate hash mismatch",
      });
    }
  });

export type KnotGateDCandidateV1 = z.infer<typeof KnotGateDCandidateV1Schema>;

const KnotGateDPiReviewV1Schema = z
  .object({
    repository: z.enum(["public", "private"]),
    reviewed_commit: z.string().regex(/^[0-9a-f]{40}$/),
    review_ref: z.string().min(1),
    disposition: z.literal("APPROVE"),
    reviewed_candidate_hash: Sha256Schema,
  })
  .strict();

export const KnotGateDReceiptV1Schema = z
  .object({
    schema_version: z.literal("knot_gate_d_receipt_v1"),
    candidate: KnotGateDCandidateV1Schema,
    pi_reviews: z
      .object({
        public: KnotGateDPiReviewV1Schema,
        private: KnotGateDPiReviewV1Schema,
      })
      .strict(),
    receipt_hash: Sha256Schema,
  })
  .strict()
  .superRefine((receipt, ctx) => {
    const { candidate, pi_reviews: reviews } = receipt;
    if (
      reviews.public.repository !== "public" ||
      reviews.private.repository !== "private" ||
      reviews.public.reviewed_commit !== candidate.public_private_pin.public_commit ||
      reviews.private.reviewed_commit !== candidate.public_private_pin.private_commit ||
      reviews.public.reviewed_candidate_hash !== candidate.candidate_hash ||
      reviews.private.reviewed_candidate_hash !== candidate.candidate_hash
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["pi_reviews"],
        message: "Gate D Pi review binding mismatch",
      });
    }
    const { receipt_hash: _, ...body } = receipt;
    if (receipt.receipt_hash !== canonicalHash(body)) {
      ctx.addIssue({
        code: "custom",
        path: ["receipt_hash"],
        message: "Gate D receipt hash mismatch",
      });
    }
  });

export type KnotGateDReceiptV1 = z.infer<typeof KnotGateDReceiptV1Schema>;

export const ActivePromptReleaseManifestV3Schema = z
  .object({
    schema_version: z.literal("active_prompt_release_manifest_v3"),
    release_id: z.string().min(1),
    base_release_id: z.string().min(1).nullable(),
    lifecycle_state: z.enum(["staged", "canary", "active", "rolled_back"]),
    prompt_commit: CommitRefSchema,
    code_commit: CommitRefSchema,
    execution_behavior_release: PromptReleaseExecutionBehaviorBindingSchema,
    prompt_hash: Sha256Schema,
    prompt_pairs: z.array(ReleasePromptPairSchema).min(1),
    stage_snapshot_hashes: z.record(z.string().min(1), Sha256Schema),
    catalog_hash: Sha256Schema,
    schema_hash: Sha256Schema,
    evaluation_contract_hash: Sha256Schema,
    release_evidence: PromptReleaseEvidenceSchema,
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
    runtime_slo_summary: PromptReleaseRuntimeSloSummarySchema.nullable(),
    runtime_slo_evidence: PromptReleaseRuntimeSloEvidenceSchema.nullable(),
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

export const ActivePromptReleaseManifestV4Schema = z
  .object({
    ...ActivePromptReleaseManifestV3Schema.shape,
    schema_version: z.literal("active_prompt_release_manifest_v4"),
    capability_full_bundle: CapabilityFullBundleV1Schema,
    gate_d_receipt: KnotGateDReceiptV1Schema,
  })
  .strict()
  .superRefine((manifest, ctx) => {
    const { capability_full_bundle: bundle, gate_d_receipt, ...common } = manifest;
    const commonResult = ActivePromptReleaseManifestV3Schema.safeParse({
      ...common,
      schema_version: "active_prompt_release_manifest_v3",
    });
    if (!commonResult.success) {
      ctx.addIssue({
        code: "custom",
        message: "Gate D release common manifest contract mismatch",
      });
    }
    const candidate = gate_d_receipt.candidate;
    if (
      bundle.prompt_hash !== manifest.prompt_hash ||
      bundle.execution_behavior_release_hash !== manifest.execution_behavior_release.release_hash ||
      candidate.full_bundle_hash !== bundle.full_bundle_hash ||
      candidate.runtime_agent_manifest_hash !== bundle.runtime_agent_manifest_hash ||
      candidate.capability_binding_manifest_hash !== bundle.capability_binding_manifest_hash ||
      candidate.public_private_pin.private_companion_pin_hash !==
        bundle.private_companion_pin_hash ||
      candidate.paired_environment.production_variant_roster_hash !==
        bundle.production_variant_roster_hash ||
      candidate.paired_environment.execution_behavior_release_hash !==
        bundle.execution_behavior_release_hash
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["capability_full_bundle"],
        message: "Gate D full-bundle fixed point mismatch",
      });
    }
  });

export const ActivePromptReleaseManifestSchema = z.union([
  ActivePromptReleaseManifestV3Schema,
  ActivePromptReleaseManifestV4Schema,
]);

export type ActivePromptReleaseManifest = z.infer<typeof ActivePromptReleaseManifestSchema>;

export interface KnotGateDReleaseFixedPointAuthority {
  execution_behavior_release_hash: string;
  runtime_agent_manifest_hash: string;
  agent_tool_manifest_hash: string;
  tool_environment_hash: string;
  capability_binding_manifest_hash: string;
  knot_coverage_manifest_hash: string;
  knot_audit_capability_track_hash: string;
  binding_count: number;
  stage_keys: ReadonlyArray<string>;
}

export function assertKnotGateDReleaseFixedPoint(
  rawManifest: unknown,
  authority: KnotGateDReleaseFixedPointAuthority,
): z.infer<typeof ActivePromptReleaseManifestV4Schema> {
  const manifest = ActivePromptReleaseManifestV4Schema.parse(rawManifest);
  const bundle = manifest.capability_full_bundle;
  const candidate = manifest.gate_d_receipt.candidate;
  const expectedStageKeys = [...authority.stage_keys].sort(compareCanonicalStrings);
  const actualStageKeys = candidate.stage_evidence
    .map((row) => `${row.agent_id}:${row.stage}`)
    .sort(compareCanonicalStrings);
  const fixedPointMatches =
    bundle.execution_behavior_release_hash === authority.execution_behavior_release_hash &&
    bundle.runtime_agent_manifest_hash === authority.runtime_agent_manifest_hash &&
    bundle.agent_tool_manifest_hash === authority.agent_tool_manifest_hash &&
    bundle.tool_environment_hash === authority.tool_environment_hash &&
    bundle.capability_binding_manifest_hash === authority.capability_binding_manifest_hash &&
    bundle.knot_coverage_manifest_hash === authority.knot_coverage_manifest_hash &&
    bundle.knot_audit_capability_track_hash === authority.knot_audit_capability_track_hash &&
    candidate.runtime_agent_manifest_hash === authority.runtime_agent_manifest_hash &&
    candidate.capability_binding_manifest_hash === authority.capability_binding_manifest_hash &&
    candidate.binding_count === authority.binding_count &&
    candidate.runtime_stage_count === expectedStageKeys.length &&
    canonicalHash(actualStageKeys) === canonicalHash(expectedStageKeys);
  if (!fixedPointMatches) {
    throw new Error("Gate D current fixed-point mismatch");
  }
  return manifest;
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
  if (!RELEASE_TRANSITIONS[previous.lifecycle_state].has(next.lifecycle_state)) {
    throw new Error(
      `prompt_release_transition_invalid:${previous.lifecycle_state}:${next.lifecycle_state}`,
    );
  }
  ActivePromptReleaseManifestSchema.parse(next);
}

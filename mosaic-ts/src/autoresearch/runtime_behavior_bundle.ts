import { z } from "zod";
import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const CommitSchema = z.string().regex(/^[0-9a-f]{40}$/);

export const RuntimeBehaviorBundleOriginSchema = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.literal("KNOT_PROMOTION"),
      track_id: z.string().min(1),
      promotion_receipt_hash: Sha256Schema,
    })
    .strict(),
  z
    .object({
      kind: z.literal("BASELINE_MIGRATION"),
      migration_id: z.string().min(1),
      migration_evidence_hash: Sha256Schema,
    })
    .strict(),
  z
    .object({
      kind: z.literal("FORWARD_RECOVERY"),
      rolled_back_release_id: z.string().min(1),
      recovery_evidence_hash: Sha256Schema,
    })
    .strict(),
]);

const RuntimeBehaviorBundleContentSchema = z
  .object({
    schema_version: z.literal("runtime_behavior_bundle_ref_v1"),
    prompt_hash: Sha256Schema,
    execution_behavior_release_id: z.string().regex(/^execution-behavior-release:[0-9a-f]{64}$/),
    execution_behavior_release_hash: Sha256Schema,
    production_variant_roster_revision_id: z
      .string()
      .regex(/^production-variant-roster-revision:[0-9a-f]{64}$/),
    production_variant_roster_revision_hash: Sha256Schema,
    origin: RuntimeBehaviorBundleOriginSchema,
    private_runtime_commit: CommitSchema,
    private_runtime_manifest_hash: Sha256Schema,
    private_policy_commit: CommitSchema,
    private_policy_hash: Sha256Schema,
    effect_registry_hash: Sha256Schema,
    consumer_registry_hash: Sha256Schema,
    fitness_registry_hash: Sha256Schema,
    catalog_hash: Sha256Schema,
    agent_contract_hash: Sha256Schema,
    evaluation_contract_hash: Sha256Schema,
    schema_hash: Sha256Schema,
    score_contract_hash: Sha256Schema,
    scheduler_contract_hash: Sha256Schema,
    earliest_activation_slot: z.string().datetime({ offset: true }),
  })
  .strict();

export const RuntimeBehaviorBundleRefSchema = RuntimeBehaviorBundleContentSchema.extend({
  full_bundle_id: z.string().regex(/^runtime-behavior-bundle:[0-9a-f]{64}$/),
  full_bundle_hash: Sha256Schema,
})
  .strict()
  .superRefine((bundle, ctx) => {
    const content = runtimeBehaviorBundleContent(bundle);
    if (bundle.full_bundle_hash !== canonicalJsonHash(content)) {
      ctx.addIssue({
        code: "custom",
        path: ["full_bundle_hash"],
        message: "runtime behavior bundle hash mismatch",
      });
    }
    if (bundle.full_bundle_id !== runtimeBehaviorBundleId(content)) {
      ctx.addIssue({
        code: "custom",
        path: ["full_bundle_id"],
        message: "runtime behavior bundle id mismatch",
      });
    }
  });

export type RuntimeBehaviorBundleContent = z.infer<typeof RuntimeBehaviorBundleContentSchema>;
export type RuntimeBehaviorBundleRef = z.infer<typeof RuntimeBehaviorBundleRefSchema>;

const RuntimeBehaviorRunPinsBodySchema = z
  .object({
    schema_version: z.literal("runtime_behavior_run_pins_v1"),
    active_prompt_release_id: z.string().regex(/^active-prompt-release:[0-9a-f]{64}$/),
    active_prompt_release_manifest_hash: Sha256Schema,
    full_bundle_id: z.string().regex(/^runtime-behavior-bundle:[0-9a-f]{64}$/),
    full_bundle_hash: Sha256Schema,
    execution_behavior_release_id: z.string().regex(/^execution-behavior-release:[0-9a-f]{64}$/),
    execution_behavior_release_hash: Sha256Schema,
    production_variant_roster_revision_id: z
      .string()
      .regex(/^production-variant-roster-revision:[0-9a-f]{64}$/),
    production_variant_roster_revision_hash: Sha256Schema,
    private_runtime_manifest_hash: Sha256Schema,
    private_policy_hash: Sha256Schema,
    effect_registry_hash: Sha256Schema,
    consumer_registry_hash: Sha256Schema,
    fitness_registry_hash: Sha256Schema,
    origin_kind: z.enum(["KNOT_PROMOTION", "BASELINE_MIGRATION", "FORWARD_RECOVERY"]),
  })
  .strict();

export const RuntimeBehaviorRunPinsSchema = RuntimeBehaviorRunPinsBodySchema.extend({
  run_pins_hash: Sha256Schema,
})
  .strict()
  .superRefine((pins, ctx) => {
    const { run_pins_hash: _hash, ...body } = pins;
    if (pins.run_pins_hash !== canonicalJsonHash(body)) {
      ctx.addIssue({ code: "custom", path: ["run_pins_hash"], message: "run pins hash mismatch" });
    }
  });

export type RuntimeBehaviorRunPins = z.infer<typeof RuntimeBehaviorRunPinsSchema>;

export function runtimeBehaviorBundleContent(
  bundle: RuntimeBehaviorBundleRef | RuntimeBehaviorBundleContent,
): RuntimeBehaviorBundleContent {
  const {
    full_bundle_id: _id,
    full_bundle_hash: _hash,
    ...content
  } = bundle as
    | RuntimeBehaviorBundleRef
    | (RuntimeBehaviorBundleContent & {
        full_bundle_id?: string;
        full_bundle_hash?: string;
      });
  return RuntimeBehaviorBundleContentSchema.parse(content);
}

export function runtimeBehaviorBundleId(content: RuntimeBehaviorBundleContent): string {
  return `runtime-behavior-bundle:${canonicalJsonHash(
    RuntimeBehaviorBundleContentSchema.parse(content),
  ).slice("sha256:".length)}`;
}

export function buildRuntimeBehaviorBundleRef(
  content: RuntimeBehaviorBundleContent,
): RuntimeBehaviorBundleRef {
  const parsed = RuntimeBehaviorBundleContentSchema.parse(content);
  return RuntimeBehaviorBundleRefSchema.parse({
    ...parsed,
    full_bundle_id: runtimeBehaviorBundleId(parsed),
    full_bundle_hash: canonicalJsonHash(parsed),
  });
}

export function buildRuntimeBehaviorRunPins(input: {
  activePromptReleaseId: string;
  activePromptReleaseManifestHash: string;
  bundle: RuntimeBehaviorBundleRef;
}): RuntimeBehaviorRunPins {
  const bundle = RuntimeBehaviorBundleRefSchema.parse(input.bundle);
  const body = {
    schema_version: "runtime_behavior_run_pins_v1" as const,
    active_prompt_release_id: input.activePromptReleaseId,
    active_prompt_release_manifest_hash: input.activePromptReleaseManifestHash,
    full_bundle_id: bundle.full_bundle_id,
    full_bundle_hash: bundle.full_bundle_hash,
    execution_behavior_release_id: bundle.execution_behavior_release_id,
    execution_behavior_release_hash: bundle.execution_behavior_release_hash,
    production_variant_roster_revision_id: bundle.production_variant_roster_revision_id,
    production_variant_roster_revision_hash: bundle.production_variant_roster_revision_hash,
    private_runtime_manifest_hash: bundle.private_runtime_manifest_hash,
    private_policy_hash: bundle.private_policy_hash,
    effect_registry_hash: bundle.effect_registry_hash,
    consumer_registry_hash: bundle.consumer_registry_hash,
    fitness_registry_hash: bundle.fitness_registry_hash,
    origin_kind: bundle.origin.kind,
  };
  return RuntimeBehaviorRunPinsSchema.parse({
    ...body,
    run_pins_hash: canonicalJsonHash(body),
  });
}

export function validateRuntimeBehaviorRunPins(pins: RuntimeBehaviorRunPins): void {
  RuntimeBehaviorRunPinsSchema.parse(pins);
}

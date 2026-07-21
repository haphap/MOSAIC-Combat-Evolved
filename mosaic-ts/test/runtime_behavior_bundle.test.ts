import { describe, expect, it } from "vitest";
import {
  ActivePromptReleaseManifestSchema,
  type ActivePromptReleaseManifestV2,
  assertFullRuntimePromptRelease,
  deterministicFullRuntimeReleaseId,
  type ReleasePromptPair,
  releasePromptPairHash,
  releasePromptSetHash,
} from "../src/agents/prompts/prompt_release_contract.js";
import {
  buildRuntimeBehaviorBundleRef,
  type RuntimeBehaviorBundleContent,
} from "../src/autoresearch/runtime_behavior_bundle.js";

const HASH = `sha256:${"1".repeat(64)}`;
const OTHER_HASH = `sha256:${"2".repeat(64)}`;

function promptPair(): ReleasePromptPair {
  const pair = {
    agent: "china",
    layer: "macro" as const,
    cohort: "cohort_default",
    stages: ["agent_run" as const],
    zh: {
      path: "prompts/mosaic/cohort_default/macro/china.zh.md",
      sha256: HASH,
    },
    en: {
      path: "prompts/mosaic/cohort_default/macro/china.en.md",
      sha256: HASH,
    },
  };
  return { ...pair, pair_hash: releasePromptPairHash(pair) };
}

function bundleContent(promptHash: string): RuntimeBehaviorBundleContent {
  return {
    schema_version: "runtime_behavior_bundle_ref_v1",
    prompt_hash: promptHash,
    execution_behavior_release_id: `execution-behavior-release:${"3".repeat(64)}`,
    execution_behavior_release_hash: `sha256:${"4".repeat(64)}`,
    production_variant_roster_revision_id: `production-variant-roster-revision:${"5".repeat(64)}`,
    production_variant_roster_revision_hash: `sha256:${"6".repeat(64)}`,
    origin: {
      kind: "BASELINE_MIGRATION",
      migration_id: "baseline-cutover-1",
      migration_evidence_hash: `sha256:${"7".repeat(64)}`,
    },
    private_runtime_commit: "8".repeat(40),
    private_runtime_manifest_hash: `sha256:${"9".repeat(64)}`,
    private_policy_commit: "a".repeat(40),
    private_policy_hash: `sha256:${"b".repeat(64)}`,
    effect_registry_hash: `sha256:${"c".repeat(64)}`,
    consumer_registry_hash: `sha256:${"d".repeat(64)}`,
    fitness_registry_hash: `sha256:${"e".repeat(64)}`,
    catalog_hash: HASH,
    agent_contract_hash: HASH,
    evaluation_contract_hash: HASH,
    schema_hash: HASH,
    score_contract_hash: `sha256:${"f".repeat(64)}`,
    scheduler_contract_hash: `sha256:${"0".repeat(64)}`,
    earliest_activation_slot: "2026-07-22T00:00:00Z",
  };
}

function release(): ActivePromptReleaseManifestV2 {
  const pair = promptPair();
  const promptHash = releasePromptSetHash([pair]);
  const withoutId = {
    schema_version: "active_prompt_release_manifest_v2" as const,
    base_release_id: null,
    lifecycle_state: "staged" as const,
    prompt_commit: "1".repeat(40),
    code_commit: "2".repeat(40),
    prompt_hash: promptHash,
    prompt_pairs: [pair],
    stage_snapshot_hashes: { "china:agent_run": OTHER_HASH },
    catalog_hash: HASH,
    schema_hash: HASH,
    evaluation_contract_hash: HASH,
    keep_decision_hash: HASH,
    keep_decision_state: "kept" as const,
    release_evidence: {
      kind: "BASELINE_MIGRATION" as const,
      migration_id: "baseline-cutover-1",
      migration_evidence_hash: `sha256:${"7".repeat(64)}`,
    },
    activation_scope: {
      cohort: "cohort_default",
      account_mode: "paper" as const,
      traffic_percent: 0,
    },
    approval_policy_id: "decision_release_manual_v1",
    approved_by: null,
    canary_started_at: null,
    canary_ended_at: null,
    runtime_slo_summary: null,
    runtime_slo_evidence: null,
    rollback_triggers: ["schema_failure_rate_gt_0"],
    previous_approved_release_id: null,
    bundled_fallback: null,
    created_at: "2026-07-21T00:00:00Z",
    activated_at: null,
    rolled_back_at: null,
    runtime_behavior_bundle: buildRuntimeBehaviorBundleRef(bundleContent(promptHash)),
  };
  return ActivePromptReleaseManifestSchema.parse({
    ...withoutId,
    release_id: deterministicFullRuntimeReleaseId(withoutId),
  }) as ActivePromptReleaseManifestV2;
}

describe("full runtime behavior bundle closure", () => {
  it("builds a content-addressed v2 release and changes identity with execution pins", () => {
    const first = release();
    assertFullRuntimePromptRelease(first);
    const changedBundle = buildRuntimeBehaviorBundleRef({
      ...bundleContent(first.prompt_hash),
      execution_behavior_release_hash: OTHER_HASH,
    });
    const changed = {
      ...first,
      runtime_behavior_bundle: changedBundle,
    };
    expect(deterministicFullRuntimeReleaseId(changed)).not.toBe(first.release_id);
    expect(ActivePromptReleaseManifestSchema.safeParse(changed).success).toBe(false);
  });

  it("rejects a tampered sub-pin and private-policy releases with prompt drift", () => {
    const valid = release();
    const tampered = {
      ...valid,
      runtime_behavior_bundle: {
        ...valid.runtime_behavior_bundle,
        fitness_registry_hash: OTHER_HASH,
      },
    };
    expect(ActivePromptReleaseManifestSchema.safeParse(tampered).success).toBe(false);

    const policy = {
      ...valid,
      release_evidence: {
        kind: "PRIVATE_EXECUTION_POLICY" as const,
        agent_id: "china",
        effect_id: "derived_feature",
        track_id: "track-1",
        candidate_receipt_hash: HASH,
        promotion_gate_hash: HASH,
        base_prompt_hash: HASH,
        candidate_prompt_hash: valid.prompt_hash,
      },
    };
    policy.release_id = deterministicFullRuntimeReleaseId(policy);
    expect(ActivePromptReleaseManifestSchema.safeParse(policy).success).toBe(false);
  });

  it("retains v1 parsing for audit but rejects it as a runtime release", () => {
    const valid = release();
    const legacy = {
      ...valid,
      schema_version: "active_prompt_release_manifest_v1" as const,
      release_id: "historical-release-1",
      release_evidence: {
        version_id: 1,
        mutation_id: "mutation-1",
        experiment_id: "experiment-1",
        mutated_agent: "china",
        evaluation_result_hash: HASH,
        transaction_manifest_hash: HASH,
        prompt_pair_sha256: "1".repeat(64),
      },
    };
    const { runtime_behavior_bundle: _bundle, ...historical } = legacy;
    const parsed = ActivePromptReleaseManifestSchema.parse(historical);
    expect(() => assertFullRuntimePromptRelease(parsed)).toThrow(
      "prompt_release_runtime_requires_full_bundle_v2",
    );
  });
});

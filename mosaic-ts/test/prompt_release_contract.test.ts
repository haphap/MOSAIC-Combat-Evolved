import { describe, expect, it } from "vitest";
import {
  type ActivePromptReleaseManifest,
  ActivePromptReleaseManifestSchema,
  assertPromptReleaseTransition,
  assertReleasePromptStageClosure,
  type ReleasePromptPair,
  releasePromptPairHash,
  releasePromptSetHash,
} from "../src/agents/prompts/prompt_release_contract.js";

const HASH = `sha256:${"1".repeat(64)}`;

function promptPairs(): ReleasePromptPair[] {
  const pair = {
    agent: "central_bank",
    layer: "macro" as const,
    cohort: "cohort_default",
    stages: ["agent_run" as const],
    zh: {
      path: "prompts/mosaic/cohort_default/macro/central_bank.zh.md",
      sha256: HASH,
    },
    en: {
      path: "prompts/mosaic/cohort_default/macro/central_bank.en.md",
      sha256: HASH,
    },
  };
  return [{ ...pair, pair_hash: releasePromptPairHash(pair) }];
}

function release(
  lifecycleState: ActivePromptReleaseManifest["lifecycle_state"],
): ActivePromptReleaseManifest {
  const canaryStarted = lifecycleState !== "staged";
  const active = lifecycleState === "active";
  const pairs = promptPairs();
  return {
    schema_version: "active_prompt_release_manifest_v1",
    release_id: "release-1",
    base_release_id: "release-0",
    lifecycle_state: lifecycleState,
    prompt_commit: "1234567",
    code_commit: "7654321",
    prompt_hash: releasePromptSetHash(pairs),
    prompt_pairs: pairs,
    stage_snapshot_hashes: { "central_bank:agent_run": HASH },
    catalog_hash: HASH,
    schema_hash: HASH,
    evaluation_contract_hash: HASH,
    keep_decision_hash: HASH,
    keep_decision_state: "kept",
    release_evidence: {
      version_id: 1,
      mutation_id: "mutation-1",
      experiment_id: "experiment-1",
      mutated_agent: "central_bank",
      evaluation_result_hash: HASH,
      transaction_manifest_hash: HASH,
      prompt_pair_sha256: "1".repeat(64),
    },
    activation_scope: {
      cohort: "cohort_default",
      account_mode: "paper",
      traffic_percent: active ? 100 : canaryStarted ? 10 : 0,
    },
    approval_policy_id: "decision_release_manual_v1",
    approved_by: canaryStarted ? "operator:test" : null,
    canary_started_at: canaryStarted ? "2026-07-10T01:00:00Z" : null,
    canary_ended_at: active ? "2026-07-10T02:00:00Z" : null,
    runtime_slo_summary: active
      ? {
          passed: true,
          sample_count: 20,
          schema_failure_rate: 0,
          fallback_rate: 0,
          source_failure_rate: 0,
          unsupported_influence_rejection_rate: 0,
          validator_rejection_rate: 0,
          latency_p95_ms: 100,
          token_budget_breach_count: 0,
          duplicate_order_intent_count: 0,
          exposure_breach_count: 0,
        }
      : null,
    runtime_slo_evidence: active
      ? {
          schema_version: "prompt_release_canary_slo_evidence_v1",
          release_id: "release-1",
          account_mode: "paper",
          traffic_percent: 10,
          canary_started_at: "2026-07-10T01:00:00Z",
          observation_ended_at: "2026-07-10T02:00:00Z",
          eligible_event_count: 20,
          excluded_event_count: 0,
          excluded_count_by_reason: {},
          event_set_hash: HASH,
          stage_snapshot_hashes_hash: HASH,
          aggregator_id: "prompt_release_canary_slo",
          aggregator_version: "1",
          artifact_hash: HASH,
        }
      : null,
    rollback_triggers: ["schema_failure_rate_gt_0"],
    previous_approved_release_id: "release-0",
    bundled_fallback: null,
    created_at: "2026-07-10T00:00:00Z",
    activated_at: active ? "2026-07-10T02:00:00Z" : null,
    rolled_back_at: lifecycleState === "rolled_back" ? "2026-07-10T02:00:00Z" : null,
  };
}

describe("aggregate prompt release contract", () => {
  it("allows staged to canary to active only with approval and passing SLOs", () => {
    const staged = ActivePromptReleaseManifestSchema.parse(release("staged"));
    const canary = ActivePromptReleaseManifestSchema.parse(release("canary"));
    const active = ActivePromptReleaseManifestSchema.parse(release("active"));

    expect(() => assertPromptReleaseTransition(staged, canary)).not.toThrow();
    expect(() => assertPromptReleaseTransition(canary, active)).not.toThrow();
  });

  it("rejects direct activation and active releases without approval or SLO evidence", () => {
    expect(() => assertPromptReleaseTransition(release("staged"), release("active"))).toThrow(
      "prompt_release_transition_invalid:staged:active",
    );
    const invalid = release("active");
    invalid.approved_by = null;
    invalid.runtime_slo_summary = null;
    expect(ActivePromptReleaseManifestSchema.safeParse(invalid).success).toBe(false);

    const assertedOnly = release("active");
    if (!assertedOnly.runtime_slo_summary) throw new Error("active fixture requires SLOs");
    assertedOnly.runtime_slo_summary.latency_p95_ms = 120_001;
    expect(ActivePromptReleaseManifestSchema.safeParse(assertedOnly).success).toBe(false);
  });

  it("binds requested runtime stages to hash-closed prompt pairs", () => {
    const active = release("active");
    expect(() =>
      assertReleasePromptStageClosure(active, [
        { agent: "central_bank", layer: "macro", stage: "agent_run" },
      ]),
    ).not.toThrow();
    expect(() =>
      assertReleasePromptStageClosure(active, [
        { agent: "cio", layer: "decision", stage: "cio_final" },
      ]),
    ).toThrow("prompt_release_stage_closure_incomplete:cio:cio_final:0");

    const drifted = release("active");
    const driftedPair = drifted.prompt_pairs[0];
    if (!driftedPair) throw new Error("test fixture prompt pair missing");
    driftedPair.zh.sha256 = `sha256:${"2".repeat(64)}`;
    expect(ActivePromptReleaseManifestSchema.safeParse(drifted).success).toBe(false);
  });

  it("binds SLO evidence versions to their journal and aggregator contracts", () => {
    const mismatched = release("active");
    if (!mismatched.runtime_slo_evidence) throw new Error("active fixture requires SLOs");
    mismatched.runtime_slo_evidence.aggregator_version = "2";
    expect(ActivePromptReleaseManifestSchema.safeParse(mismatched).success).toBe(false);

    const v2 = release("active");
    if (!v2.runtime_slo_evidence) throw new Error("active fixture requires SLOs");
    v2.runtime_slo_evidence = {
      ...v2.runtime_slo_evidence,
      schema_version: "prompt_release_canary_slo_evidence_v2",
      journal_closure_hash: HASH,
      journal_record_count: 40,
      aggregator_version: "2",
    };
    expect(ActivePromptReleaseManifestSchema.safeParse(v2).success).toBe(true);
  });
});

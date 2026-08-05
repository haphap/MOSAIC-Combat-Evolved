import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
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
import { ActivePromptReleaseRegistry } from "../src/autoresearch/release_registry.js";

const HASH = `sha256:${"1".repeat(64)}`;
const EXECUTION_RELEASE_ID = `execution-behavior-release:${"2".repeat(64)}`;
const EXECUTION_RELEASE_REF = `registry/prompt_checks/execution_behavior_releases/${"2".repeat(64)}--${"1".repeat(64)}.json`;

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
    schema_version: "active_prompt_release_manifest_v3",
    release_id: "release-1",
    base_release_id: "release-0",
    lifecycle_state: lifecycleState,
    prompt_commit: "1234567",
    code_commit: "7654321",
    execution_behavior_release: {
      release_id: EXECUTION_RELEASE_ID,
      release_hash: HASH,
      archive_ref: EXECUTION_RELEASE_REF,
    },
    prompt_hash: releasePromptSetHash(pairs),
    prompt_pairs: pairs,
    stage_snapshot_hashes: { "central_bank:agent_run": HASH },
    catalog_hash: HASH,
    schema_hash: HASH,
    evaluation_contract_hash: HASH,
    release_evidence: {
      candidate_id: "candidate-1",
      candidate_hash: HASH,
      candidate_publication_hash: HASH,
      prompt_source_id: "private-prompts",
      promotion_decision_id: "decision-1",
      promotion_decision_hash: HASH,
      experiment_id: "experiment-1",
      mutated_agent: "central_bank",
      policy_version: "policy-v1",
      policy_config_hash: HASH,
      candidate_prompt_hashes: { zh: HASH, en: HASH },
      private_state_artifact_hash: HASH,
      behavior_contract_hash: HASH,
      mutator_commit: "1".repeat(40),
      mutator_config_hash: HASH,
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

  it("requires a content-addressed execution archive binding", () => {
    const drifted = release("active");
    drifted.execution_behavior_release.archive_ref = `registry/prompt_checks/execution_behavior_releases/${"3".repeat(64)}--${"1".repeat(64)}.json`;
    expect(ActivePromptReleaseManifestSchema.safeParse(drifted).success).toBe(false);
  });

  it("rejects execution behavior binding changes during lifecycle transitions", async () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-release-registry-"));
    const registry = new ActivePromptReleaseRegistry(root);
    const audit = {
      operator: "operator:test",
      reason: "execution behavior binding must remain immutable",
    };
    const baseline = release("active");
    baseline.release_id = "release-0";
    baseline.base_release_id = null;
    baseline.previous_approved_release_id = null;
    if (!baseline.runtime_slo_evidence) throw new Error("active fixture requires SLO evidence");
    baseline.runtime_slo_evidence.release_id = baseline.release_id;

    try {
      await registry.provisionBaseline(baseline, audit);
      await registry.stage(release("staged"));
      const tampered = release("canary");
      tampered.execution_behavior_release = {
        release_id: `execution-behavior-release:${"3".repeat(64)}`,
        release_hash: `sha256:${"4".repeat(64)}`,
        archive_ref: `registry/prompt_checks/execution_behavior_releases/${"3".repeat(64)}--${"4".repeat(64)}.json`,
      };

      await expect(registry.transition(tampered, { audit })).rejects.toThrow(
        "prompt_release_immutable_closure_changed",
      );
      expect((await registry.load("release-1"))?.lifecycle_state).toBe("staged");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("serializes competing canaries and keeps identical activation retries idempotent", async () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-release-cas-race-"));
    const leftRegistry = new ActivePromptReleaseRegistry(root);
    const rightRegistry = new ActivePromptReleaseRegistry(root);
    const audit = { operator: "operator:test", reason: "CAS race fixture" };
    const withId = (state: ActivePromptReleaseManifest["lifecycle_state"], releaseId: string) => {
      const value = release(state);
      value.release_id = releaseId;
      value.base_release_id = "release-0";
      value.previous_approved_release_id = "release-0";
      if (value.runtime_slo_evidence) value.runtime_slo_evidence.release_id = releaseId;
      return value;
    };
    const baseline = release("active");
    baseline.release_id = "release-0";
    baseline.base_release_id = null;
    baseline.previous_approved_release_id = null;
    if (!baseline.runtime_slo_evidence) throw new Error("active fixture requires SLO evidence");
    baseline.runtime_slo_evidence.release_id = baseline.release_id;
    try {
      await leftRegistry.provisionBaseline(baseline, audit);
      await leftRegistry.stage(withId("staged", "release-left"));
      await rightRegistry.stage(withId("staged", "release-right"));
      const race = await Promise.allSettled([
        leftRegistry.transition(withId("canary", "release-left"), { audit }),
        rightRegistry.transition(withId("canary", "release-right"), { audit }),
      ]);
      expect(race.filter((result) => result.status === "fulfilled")).toHaveLength(1);
      const rejection = race.find((result) => result.status === "rejected");
      expect(rejection?.status === "rejected" ? String(rejection.reason) : "").toContain(
        "prompt_release_canary_pointer_conflict",
      );
      const canaryPointer = await leftRegistry.canaryPointer();
      expect(canaryPointer.pointer_version).toBe(1);
      const winner = canaryPointer.current_release_id;
      if (!winner) throw new Error("CAS race did not select a canary");
      const active = withId("active", winner);
      await Promise.all([
        leftRegistry.transition(active, { expectedBaseReleaseId: "release-0", audit }),
        rightRegistry.transition(active, { expectedBaseReleaseId: "release-0", audit }),
      ]);
      expect(await leftRegistry.pointer()).toMatchObject({
        current_release_id: winner,
        pointer_version: 2,
      });
      expect(await rightRegistry.canaryPointer()).toMatchObject({
        current_release_id: null,
        pointer_version: 2,
      });

      const successorStaged = withId("staged", "release-successor");
      successorStaged.base_release_id = winner;
      successorStaged.previous_approved_release_id = winner;
      await leftRegistry.stage(successorStaged);
      const successorCanary = withId("canary", "release-successor");
      successorCanary.base_release_id = winner;
      successorCanary.previous_approved_release_id = winner;
      await leftRegistry.transition(successorCanary, { audit });
      const successorActive = withId("active", "release-successor");
      successorActive.base_release_id = winner;
      successorActive.previous_approved_release_id = winner;
      await expect(
        rightRegistry.transition(successorActive, {
          expectedBaseReleaseId: "release-0",
          audit,
        }),
      ).rejects.toThrow("prompt_release_active_pointer_compare_and_swap_failed");
      expect(await leftRegistry.pointer()).toMatchObject({ current_release_id: winner });
      expect((await leftRegistry.load("release-successor"))?.lifecycle_state).toBe("canary");

      await leftRegistry.transition(successorActive, {
        expectedBaseReleaseId: winner,
        audit,
      });
      const staleRollback: ActivePromptReleaseManifest = {
        ...active,
        lifecycle_state: "rolled_back",
        rolled_back_at: "2026-07-10T03:00:00Z",
      };
      await expect(rightRegistry.transition(staleRollback, { audit })).rejects.toThrow(
        "prompt_release_rollback_pointer_compare_and_swap_failed",
      );
      expect(await leftRegistry.pointer()).toMatchObject({
        current_release_id: "release-successor",
      });
      expect((await leftRegistry.load(winner))?.lifecycle_state).toBe("active");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
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

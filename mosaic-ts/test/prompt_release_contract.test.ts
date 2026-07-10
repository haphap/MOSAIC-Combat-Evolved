import { describe, expect, it } from "vitest";
import {
  type ActivePromptReleaseManifest,
  ActivePromptReleaseManifestSchema,
  assertMutationTransactionTransition,
  assertPromptReleaseTransition,
  assertReleasePromptStageClosure,
  type MutationTransactionManifest,
  MutationTransactionManifestSchema,
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

function transaction(state: MutationTransactionManifest["state"]): MutationTransactionManifest {
  const prepared = ["prepared", "committed_log_pending", "committed"].includes(state);
  const committedComponent = ["committed_log_pending", "committed"].includes(state);
  return {
    schema_version: "prompt_mutation_transaction_v1",
    mutation_id: "mutation-1",
    transaction_id: "transaction-1",
    experiment_id: "experiment-1",
    state,
    recovery_state: "not_needed",
    base_release_id: "release-0",
    catalog_hash: HASH,
    schema_hash: HASH,
    evaluation_contract_hash: HASH,
    target_paths: ["/rule_packs/test/value"],
    components: [
      {
        repo_id: "MOSAIC-Prompts",
        base_commit: "1234567",
        new_commit: committedComponent ? "7654321" : null,
        candidate_ref: "refs/mosaic-candidates/mutation-1",
        prepare_status: prepared ? "prepared" : "pending",
        files: [
          {
            path: "registry/domain_knobs/cohort_default/cio.json",
            old_hash: HASH,
            new_hash: HASH,
            staging_path_hash: HASH,
          },
        ],
      },
    ],
    metadata_log: {
      path: "mutation_patches/knob_mutations.jsonl",
      entry_hash: HASH,
      appended: state === "committed",
    },
    created_at: "2026-07-10T00:00:00Z",
    prepared_at: prepared ? "2026-07-10T00:01:00Z" : null,
    committed_at: state === "committed" ? "2026-07-10T00:02:00Z" : null,
    aborted_at: state === "aborted" ? "2026-07-10T00:02:00Z" : null,
    recovery_decision: null,
  };
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
    catalog_hash: HASH,
    schema_hash: HASH,
    evaluation_contract_hash: HASH,
    keep_decision_hash: HASH,
    keep_decision_state: "kept",
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
          schema_failure_rate: 0,
          fallback_rate: 0,
          source_failure_rate: 0,
          validator_rejection_rate: 0,
          duplicate_order_intent_count: 0,
          exposure_breach_count: 0,
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

describe("prompt mutation transaction contract", () => {
  it("accepts the prepared and log-pending state sequence", () => {
    const created = MutationTransactionManifestSchema.parse(transaction("created"));
    const prepared = MutationTransactionManifestSchema.parse(transaction("prepared"));
    const logPending = MutationTransactionManifestSchema.parse(
      transaction("committed_log_pending"),
    );
    const committed = MutationTransactionManifestSchema.parse(transaction("committed"));

    expect(() => assertMutationTransactionTransition(created, prepared)).not.toThrow();
    expect(() => assertMutationTransactionTransition(prepared, logPending)).not.toThrow();
    expect(() => assertMutationTransactionTransition(logPending, committed)).not.toThrow();
  });

  it("rejects skipping the durable-log state or aborting after component commit", () => {
    expect(() =>
      assertMutationTransactionTransition(transaction("prepared"), transaction("committed")),
    ).toThrow("mutation_transaction_transition_invalid:prepared:committed");
    expect(() =>
      assertMutationTransactionTransition(
        transaction("committed_log_pending"),
        transaction("aborted"),
      ),
    ).toThrow("mutation_transaction_transition_invalid:committed_log_pending:aborted");
  });

  it("requires final factual state after reconciliation", () => {
    const invalid = { ...transaction("prepared"), recovery_state: "reconciled" as const };
    expect(MutationTransactionManifestSchema.safeParse(invalid).success).toBe(false);
  });
});

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
});

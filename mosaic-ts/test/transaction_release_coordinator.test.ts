import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  type ActivePromptReleaseManifest,
  type MutationTransactionManifest,
  type ReleasePromptPair,
  releasePromptPairHash,
  releasePromptSetHash,
} from "../src/agents/prompts/prompt_release_contract.js";
import type { KnobMutationMetadata } from "../src/autoresearch/mutator.js";
import {
  PromptMutationRecoveryDescriptorStore,
  reconcilePendingPromptMutationTransactions,
  reconcileTerminalPromptMutationLeases,
} from "../src/autoresearch/prompt_mutation_recovery.js";
import { ActivePromptReleaseRegistry } from "../src/autoresearch/release_registry.js";
import {
  type MutationMetadataLogWriter,
  MutationPathLeaseRegistry,
  type MutationRepositoryAdapter,
  MutationTransactionJournal,
  MutationTransactionPendingRecoveryError,
  PromptMutationTransactionCoordinator,
} from "../src/autoresearch/transaction_coordinator.js";
import type { BridgeApi } from "../src/bridge/types.js";

const HASH = `sha256:${"1".repeat(64)}`;
const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function tempRoot(name: string): string {
  const root = mkdtempSync(join(tmpdir(), `mosaic-${name}-`));
  roots.push(root);
  return root;
}

function transaction(
  mutationId = "mutation-1",
  transactionId = "transaction-1",
  path = "/rule_packs/test/value",
): MutationTransactionManifest {
  return {
    schema_version: "prompt_mutation_transaction_v1",
    mutation_id: mutationId,
    transaction_id: transactionId,
    experiment_id: `experiment-${mutationId}`,
    state: "created",
    recovery_state: "not_needed",
    base_release_id: "release-0",
    catalog_hash: HASH,
    schema_hash: HASH,
    evaluation_contract_hash: HASH,
    recovery_descriptor_hash: HASH,
    target_paths: [path],
    components: ["MOSAIC-RKE", "MOSAIC-Prompts"].map((repoId) => ({
      repo_id: repoId,
      base_commit: "1234567",
      new_commit: null,
      candidate_ref: `refs/mosaic-candidates/${mutationId}`,
      prepare_status: "pending" as const,
      files: [
        {
          path: `${repoId}/artifact.json`,
          old_hash: HASH,
          new_hash: HASH,
          staging_path_hash: HASH,
        },
      ],
    })),
    metadata_log: {
      path: "mutation_patches/knob_mutations.jsonl",
      entry_hash: HASH,
      appended: false,
    },
    created_at: "2026-07-10T00:00:00Z",
    prepared_at: null,
    committed_at: null,
    aborted_at: null,
    recovery_decision: null,
  };
}

class FakeRepoAdapter implements MutationRepositoryAdapter {
  readonly prepareCalls = vi.fn();
  readonly abort = vi.fn(async () => undefined);
  readonly commits = new Map<string, string>();
  failPrepare = false;
  failCommit = false;

  constructor(readonly repoId: string) {}

  async prepare(component: MutationTransactionManifest["components"][number]): Promise<void> {
    this.prepareCalls(component);
    if (this.failPrepare) throw new Error(`prepare failed: ${this.repoId}`);
  }

  async commit(component: MutationTransactionManifest["components"][number]): Promise<string> {
    if (this.failCommit) throw new Error(`commit failed: ${this.repoId}`);
    const commit = this.repoId === "MOSAIC-RKE" ? "aaaaaaa" : "bbbbbbb";
    this.commits.set(component.candidate_ref, commit);
    return commit;
  }

  async inspect(component: MutationTransactionManifest["components"][number]) {
    const commit = this.commits.get(component.candidate_ref) ?? null;
    return { candidate_visible: commit !== null, new_commit: commit };
  }
}

function adapters(): FakeRepoAdapter[] {
  return [new FakeRepoAdapter("MOSAIC-RKE"), new FakeRepoAdapter("MOSAIC-Prompts")];
}

class FakeMetadataLog implements MutationMetadataLogWriter {
  readonly entries = new Set<string>();
  fail = false;
  readonly appendCalls = vi.fn();

  async appendOnce(manifest: MutationTransactionManifest, manifestHash: string): Promise<void> {
    this.appendCalls(manifest.transaction_id, manifestHash);
    if (this.fail) throw new Error("metadata log unavailable");
    this.entries.add(manifest.mutation_id);
  }
}

function coordinator(root: string) {
  return new PromptMutationTransactionCoordinator(
    new MutationTransactionJournal(root),
    new MutationPathLeaseRegistry(root),
  );
}

function recoveryMetadata(): KnobMutationMetadata {
  return {
    schema_version: "knob_mutation_metadata_v1",
    mutation_id: "mutation-1",
    transaction_id: "transaction-1",
    experiment_id: "experiment-mutation-1",
    mutation_kind: "generic_knob",
    lifecycle_state: "proposed",
    created_at: "2026-07-10T00:00:00Z",
    agent: "central_bank",
    cohort: "cohort_default",
    prediction_target: "liquidity_regime_20d",
    evaluation_metric: "confidence_calibration_error",
    horizon: "20d",
    rollback_condition: {
      metric: "confidence_calibration_error",
      worse_by: 0.03,
      unit: "ratio",
    },
    base_knobs_sha256: HASH,
    new_knobs_sha256: HASH,
    catalog_version: "domain_knob_catalog_v1",
    catalog_hash: HASH,
    schema_hash: HASH,
    evaluation_contract_hash: HASH,
    metric_registry_hash: HASH,
    calculator_registry_hash: HASH,
    domain_card_ids: [],
    evaluation_policy: {
      baseline_id: "base_release",
      baseline: "active_release",
      min_effect_size: 0.01,
      min_sample_size: 20,
      uncertainty_method: "bootstrap",
      overlapping_sample_policy: "purged",
      require_uncertainty_bound: true,
    },
    changed_paths: ["/rule_packs/test/value"],
    patches: [
      {
        path: "/rule_packs/test/value",
        old_value: 0.5,
        new_value: 0.55,
        rationale: "test",
        expected_effect: "test",
      },
    ],
    renormalization: [],
    decision: "applied",
    expected_effect: "test",
    risk: "test",
  };
}

describe("cross-repo prompt mutation transaction coordinator", () => {
  it("prepares both repos, commits candidate refs, and appends metadata idempotently", async () => {
    const root = tempRoot("transaction-success");
    const tx = coordinator(root);
    const repoAdapters = adapters();
    const log = new FakeMetadataLog();

    const committed = await tx.execute(transaction(), repoAdapters, log);
    const repeated = await tx.execute(transaction(), repoAdapters, log);

    expect(committed.state).toBe("committed");
    expect(committed.components.every((component) => component.new_commit)).toBe(true);
    expect(repeated).toEqual(committed);
    expect(log.appendCalls).toHaveBeenCalledTimes(1);
    expect(repoAdapters.every((adapter) => adapter.prepareCalls.mock.calls.length === 1)).toBe(
      true,
    );
  });

  it("aborts all prepared components when prepare fails", async () => {
    const root = tempRoot("transaction-prepare-fail");
    const tx = coordinator(root);
    const repoAdapters = adapters();
    const failingAdapter = repoAdapters[1];
    if (!failingAdapter) throw new Error("test adapter missing");
    failingAdapter.failPrepare = true;

    await expect(tx.execute(transaction(), repoAdapters, new FakeMetadataLog())).rejects.toThrow(
      /prepare failed/,
    );
    const durable = await new MutationTransactionJournal(root).load("transaction-1");
    expect(durable?.state).toBe("aborted");
    expect(repoAdapters[0]?.abort).toHaveBeenCalledTimes(1);
  });

  it("reconciles a partial cross-repo commit by removing candidate refs and aborting", async () => {
    const root = tempRoot("transaction-partial-commit");
    const tx = coordinator(root);
    const repoAdapters = adapters();
    const failingAdapter = repoAdapters[1];
    if (!failingAdapter) throw new Error("test adapter missing");
    failingAdapter.failCommit = true;

    await expect(tx.execute(transaction(), repoAdapters, new FakeMetadataLog())).rejects.toThrow(
      MutationTransactionPendingRecoveryError,
    );
    const recovered = await tx.reconcile("transaction-1", repoAdapters, new FakeMetadataLog());
    expect(recovered).toMatchObject({
      state: "aborted",
      recovery_state: "reconciled",
      recovery_decision: "partial_candidate_refs_removed",
    });
    expect(repoAdapters.every((adapter) => adapter.abort.mock.calls.length === 1)).toBe(true);
  });

  it("recovers committed candidate refs after a metadata-log append failure", async () => {
    const root = tempRoot("transaction-log-fail");
    const tx = coordinator(root);
    const repoAdapters = adapters();
    const log = new FakeMetadataLog();
    log.fail = true;

    await expect(tx.execute(transaction(), repoAdapters, log)).rejects.toThrow(
      MutationTransactionPendingRecoveryError,
    );
    expect((await new MutationTransactionJournal(root).load("transaction-1"))?.state).toBe(
      "committed_log_pending",
    );
    log.fail = false;
    const recovered = await tx.reconcile("transaction-1", repoAdapters, log);
    expect(recovered).toMatchObject({ state: "committed", recovery_state: "reconciled" });
    expect(log.entries).toEqual(new Set(["mutation-1"]));
  });

  it("reconstructs adapters and metadata logging from a durable startup descriptor", async () => {
    const root = tempRoot("transaction-startup-recovery");
    const metadataLogPath = join(root, "knob-mutations.jsonl");
    const branch = "cohort/cohort_default/auto/central_bank/2026-07-10";
    const descriptorHash = await new PromptMutationRecoveryDescriptorStore(root).writeOnce({
      schema_version: "prompt_mutation_recovery_v1",
      transaction_id: "transaction-1",
      mutation_id: "mutation-1",
      version_id: 42,
      agent: "central_bank",
      cohort: "cohort_default",
      components: [
        { repo_id: "MOSAIC-Prompts", target: "private_git", branch },
        { repo_id: "MOSAIC-RKE", target: "project_git", branch },
      ],
      summary: "test mutation",
      prompt_sha256: "1".repeat(64),
      code_commit_hash: "c".repeat(40),
      metadata_log_path: metadataLogPath,
      mutation_metadata: recoveryMetadata(),
    });
    const journal = new MutationTransactionJournal(root);
    const base = transaction();
    const created: MutationTransactionManifest = {
      ...base,
      recovery_descriptor_hash: descriptorHash,
      components: base.components.map((component) => ({
        ...component,
        candidate_ref: `refs/heads/${branch}`,
      })),
    };
    await journal.create(created);
    const prepared: MutationTransactionManifest = {
      ...created,
      state: "prepared",
      prepared_at: "2026-07-10T00:01:00Z",
      components: created.components.map((component) => ({
        ...component,
        prepare_status: "prepared",
        new_commit: component.repo_id === "MOSAIC-Prompts" ? "b".repeat(40) : "a".repeat(40),
      })),
    };
    await journal.transition(created, prepared);
    const logPending: MutationTransactionManifest = {
      ...prepared,
      state: "committed_log_pending",
      recovery_state: "pending",
    };
    await journal.transition(prepared, logPending);
    const api = {
      autoresearchRecordMutation: vi.fn(async () => ({ ok: true })),
      promptsCandidateState: vi.fn(),
      promptsAbortCandidate: vi.fn(),
    } as unknown as BridgeApi;

    const recovered = await reconcilePendingPromptMutationTransactions({ root, api });
    const repeated = await reconcilePendingPromptMutationTransactions({ root, api });

    expect(recovered).toHaveLength(1);
    expect(recovered[0]).toMatchObject({ state: "committed", recovery_state: "reconciled" });
    expect(repeated).toEqual([]);
    expect(api.autoresearchRecordMutation).toHaveBeenCalledTimes(1);
    expect(api.autoresearchRecordMutation).toHaveBeenCalledWith(
      expect.objectContaining({
        commit_hash: "b".repeat(40),
        code_commit_hash: "a".repeat(40),
      }),
    );
    const row = JSON.parse(readFileSync(metadataLogPath, "utf-8")) as KnobMutationMetadata;
    expect(row.transaction_manifest_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("retains branch-only recovery descriptors for existing transactions", async () => {
    const root = tempRoot("transaction-legacy-recovery-descriptor");
    const descriptor = {
      schema_version: "prompt_mutation_recovery_v1" as const,
      transaction_id: "transaction-1",
      mutation_id: "mutation-1",
      version_id: 42,
      agent: "central_bank",
      cohort: "cohort_default",
      branch: "cohort/cohort_default/auto/central_bank/2026-07-10",
      summary: "legacy mutation",
      prompt_sha256: "1".repeat(64),
      code_commit_hash: "c".repeat(40),
      metadata_log_path: join(root, "knob-mutations.jsonl"),
      mutation_metadata: recoveryMetadata(),
    };

    await new PromptMutationRecoveryDescriptorStore(root).writeOnce(descriptor);

    await expect(
      new PromptMutationRecoveryDescriptorStore(root).load("transaction-1"),
    ).resolves.toEqual(descriptor);
  });

  it("fails closed when a recoverable transaction has no bound descriptor", async () => {
    const root = tempRoot("transaction-missing-recovery-descriptor");
    await new MutationTransactionJournal(root).create(transaction());
    const api = {} as BridgeApi;

    await expect(reconcilePendingPromptMutationTransactions({ root, api })).rejects.toThrow(
      "prompt_mutation_recovery_descriptor_missing",
    );
  });

  it("holds a path lease through evaluation and rejects a concurrent experiment", async () => {
    const root = tempRoot("transaction-lease");
    const tx = coordinator(root);
    await tx.execute(transaction(), adapters(), new FakeMetadataLog());

    await expect(
      tx.execute(transaction("mutation-2", "transaction-2"), adapters(), new FakeMetadataLog()),
    ).rejects.toThrow(/mutation_path_lease_conflict/);
    await tx.completeExperiment("mutation-1");
    await expect(
      tx.execute(transaction("mutation-3", "transaction-3"), adapters(), new FakeMetadataLog()),
    ).resolves.toMatchObject({ state: "committed" });
  });

  it("releases persisted leases when startup audit shows a terminal experiment", async () => {
    const root = tempRoot("transaction-terminal-lease");
    const tx = coordinator(root);
    await tx.execute(transaction(), adapters(), new FakeMetadataLog());
    const api = {
      promptsAuditVersions: vi.fn(async () => ({
        versions: [
          {
            id: 1,
            cohort: "cohort_default",
            agent: "central_bank",
            status: "keep",
            branch_name: "branch",
            base_commit_hash: "a".repeat(40),
            mutation_id: "mutation-1",
            mutation_lifecycle: "kept",
          },
        ],
      })),
    } as unknown as BridgeApi;

    expect(await reconcileTerminalPromptMutationLeases({ root, api })).toBe(1);
    await expect(
      tx.execute(transaction("mutation-2", "transaction-2"), adapters(), new FakeMetadataLog()),
    ).resolves.toMatchObject({ state: "committed" });
  });
});

function release(
  releaseId: string,
  baseReleaseId: string | null,
  lifecycleState: ActivePromptReleaseManifest["lifecycle_state"],
): ActivePromptReleaseManifest {
  const canaryStarted = lifecycleState !== "staged";
  const active = lifecycleState === "active" || lifecycleState === "rolled_back";
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
  const promptPairs: ReleasePromptPair[] = [{ ...pair, pair_hash: releasePromptPairHash(pair) }];
  return {
    schema_version: "active_prompt_release_manifest_v1",
    release_id: releaseId,
    base_release_id: baseReleaseId,
    lifecycle_state: lifecycleState,
    prompt_commit: "1234567",
    code_commit: "7654321",
    prompt_hash: releasePromptSetHash(promptPairs),
    prompt_pairs: promptPairs,
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
          release_id: releaseId,
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
    previous_approved_release_id: baseReleaseId,
    bundled_fallback: null,
    created_at: "2026-07-10T00:00:00Z",
    activated_at: active ? "2026-07-10T02:00:00Z" : null,
    rolled_back_at: lifecycleState === "rolled_back" ? "2026-07-10T03:00:00Z" : null,
  };
}

describe("aggregate active prompt release registry", () => {
  it("activates only through staged/canary with pointer CAS and supports audited rollback", async () => {
    const registry = new ActivePromptReleaseRegistry(tempRoot("release-registry"));
    await registry.stage(release("release-0", null, "staged"));
    await registry.transition(release("release-0", null, "canary"), {
      audit: { operator: "operator:test", reason: "start canary" },
    });
    await registry.transition(release("release-0", null, "active"), {
      expectedBaseReleaseId: null,
      audit: { operator: "operator:test", reason: "activate" },
    });
    expect((await registry.resolveActive())?.release_id).toBe("release-0");

    await registry.stage(release("release-1", "release-0", "staged"));
    await registry.transition(release("release-1", "release-0", "canary"), {
      audit: { operator: "operator:test", reason: "start canary" },
    });
    await registry.transition(release("release-1", "release-0", "active"), {
      expectedBaseReleaseId: "release-0",
      audit: { operator: "operator:test", reason: "activate" },
    });
    expect((await registry.resolveActive())?.release_id).toBe("release-1");

    await registry.transition(release("release-1", "release-0", "rolled_back"), {
      audit: { operator: "operator:test", reason: "rollback" },
    });
    expect((await registry.resolveActive())?.release_id).toBe("release-0");
    expect((await registry.pointer()).pointer_version).toBe(3);
  });

  it("rejects stale activation CAS and immutable component drift", async () => {
    const registry = new ActivePromptReleaseRegistry(tempRoot("release-stale"));
    await registry.stage(release("release-0", null, "staged"));
    await registry.transition(release("release-0", null, "canary"), {
      audit: { operator: "operator:test", reason: "start canary" },
    });
    await registry.transition(release("release-0", null, "active"), {
      expectedBaseReleaseId: null,
      audit: { operator: "operator:test", reason: "activate" },
    });
    await registry.stage(release("release-1", "release-0", "staged"));
    const drifted = release("release-1", "release-0", "canary");
    drifted.prompt_commit = "abcdefg";
    await expect(
      registry.transition(drifted, {
        audit: { operator: "operator:test", reason: "start canary" },
      }),
    ).rejects.toThrow(/immutable_closure_changed/);

    await registry.transition(release("release-1", "release-0", "canary"), {
      audit: { operator: "operator:test", reason: "start canary" },
    });
    await registry.transition(release("release-1", "release-0", "active"), {
      expectedBaseReleaseId: "release-0",
      audit: { operator: "operator:test", reason: "activate" },
    });
    await registry.stage(release("release-stale", "release-0", "staged"));
    await registry.transition(release("release-stale", "release-0", "canary"), {
      audit: { operator: "operator:test", reason: "start canary" },
    });
    await expect(
      registry.transition(release("release-stale", "release-0", "active"), {
        expectedBaseReleaseId: "release-0",
        audit: { operator: "operator:test", reason: "activate" },
      }),
    ).rejects.toThrow(/compare_and_swap_failed/);
  });

  it("reconciles manifest-first activation and rollback after a process crash", async () => {
    const root = tempRoot("release-recovery");
    const registry = new ActivePromptReleaseRegistry(root);
    const staged = release("release-0", null, "staged");
    const canary = release("release-0", null, "canary");
    const active = release("release-0", null, "active");
    await registry.stage(staged);
    await registry.transition(canary, {
      audit: { operator: "operator:test", reason: "start canary" },
    });
    const manifestPath = join(
      root,
      "releases",
      `${createHash("sha256").update("release-0").digest("hex")}.json`,
    );
    writeFileSync(manifestPath, `${JSON.stringify(active, null, 2)}\n`, "utf-8");

    await registry.transition(active, {
      expectedBaseReleaseId: null,
      audit: { operator: "operator:test", reason: "activate" },
    });
    expect((await registry.pointer()).current_release_id).toBe("release-0");

    const rolledBack: ActivePromptReleaseManifest = {
      ...active,
      lifecycle_state: "rolled_back",
      rolled_back_at: "2026-07-10T03:00:00Z",
    };
    writeFileSync(manifestPath, `${JSON.stringify(rolledBack, null, 2)}\n`, "utf-8");
    await registry.transition(rolledBack, {
      audit: { operator: "operator:test", reason: "rollback" },
    });
    expect((await registry.pointer()).current_release_id).toBeNull();
  });
});

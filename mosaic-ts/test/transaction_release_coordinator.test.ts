import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  ActivePromptReleaseManifest,
  MutationTransactionManifest,
} from "../src/agents/prompts/prompt_release_contract.js";
import { ActivePromptReleaseRegistry } from "../src/autoresearch/release_registry.js";
import {
  type MutationMetadataLogWriter,
  MutationPathLeaseRegistry,
  type MutationRepositoryAdapter,
  MutationTransactionJournal,
  MutationTransactionPendingRecoveryError,
  PromptMutationTransactionCoordinator,
} from "../src/autoresearch/transaction_coordinator.js";

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
});

function release(
  releaseId: string,
  baseReleaseId: string | null,
  lifecycleState: ActivePromptReleaseManifest["lifecycle_state"],
): ActivePromptReleaseManifest {
  const canaryStarted = lifecycleState !== "staged";
  const active = lifecycleState === "active" || lifecycleState === "rolled_back";
  return {
    schema_version: "active_prompt_release_manifest_v1",
    release_id: releaseId,
    base_release_id: baseReleaseId,
    lifecycle_state: lifecycleState,
    prompt_commit: "1234567",
    code_commit: "7654321",
    prompt_hash: HASH,
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
    await registry.transition(release("release-0", null, "canary"));
    await registry.transition(release("release-0", null, "active"), {
      expectedBaseReleaseId: null,
    });
    expect((await registry.resolveActive())?.release_id).toBe("release-0");

    await registry.stage(release("release-1", "release-0", "staged"));
    await registry.transition(release("release-1", "release-0", "canary"));
    await registry.transition(release("release-1", "release-0", "active"), {
      expectedBaseReleaseId: "release-0",
    });
    expect((await registry.resolveActive())?.release_id).toBe("release-1");

    await registry.transition(release("release-1", "release-0", "rolled_back"));
    expect((await registry.resolveActive())?.release_id).toBe("release-0");
    expect((await registry.pointer()).pointer_version).toBe(3);
  });

  it("rejects stale activation CAS and immutable component drift", async () => {
    const registry = new ActivePromptReleaseRegistry(tempRoot("release-stale"));
    await registry.stage(release("release-0", null, "staged"));
    await registry.transition(release("release-0", null, "canary"));
    await registry.transition(release("release-0", null, "active"), {
      expectedBaseReleaseId: null,
    });
    await registry.stage(release("release-1", "release-0", "staged"));
    const drifted = release("release-1", "release-0", "canary");
    drifted.prompt_commit = "abcdefg";
    await expect(registry.transition(drifted)).rejects.toThrow(/immutable_closure_changed/);

    await registry.transition(release("release-1", "release-0", "canary"));
    await registry.transition(release("release-1", "release-0", "active"), {
      expectedBaseReleaseId: "release-0",
    });
    await registry.stage(release("release-stale", "release-0", "staged"));
    await registry.transition(release("release-stale", "release-0", "canary"));
    await expect(
      registry.transition(release("release-stale", "release-0", "active"), {
        expectedBaseReleaseId: "release-0",
      }),
    ).rejects.toThrow(/compare_and_swap_failed/);
  });
});

import { createHash } from "node:crypto";
import { mkdir, open, readdir, readFile, rename, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";
import {
  assertMutationTransactionTransition,
  type MutationTransactionManifest,
  MutationTransactionManifestSchema,
} from "../agents/prompts/prompt_release_contract.js";

export interface MutationRepositoryAdapter {
  repoId: string;
  prepare(component: MutationTransactionManifest["components"][number]): Promise<void>;
  commit(component: MutationTransactionManifest["components"][number]): Promise<string>;
  inspect(component: MutationTransactionManifest["components"][number]): Promise<{
    candidate_visible: boolean;
    new_commit: string | null;
  }>;
  abort(component: MutationTransactionManifest["components"][number]): Promise<void>;
}

export interface MutationMetadataLogWriter {
  appendOnce(manifest: MutationTransactionManifest, manifestHash: string): Promise<void>;
}

export class MutationTransactionPendingRecoveryError extends Error {
  override readonly name = "MutationTransactionPendingRecoveryError";
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256").update(JSON.stringify(value)).digest("hex")}`;
}

function committedCandidateManifestHash(manifest: MutationTransactionManifest): string {
  return canonicalHash({
    ...manifest,
    state: "committed_log_pending",
    recovery_state: "not_needed",
    metadata_log: { ...manifest.metadata_log, appended: false },
    committed_at: null,
    recovery_decision: null,
  });
}

async function atomicWriteJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temp = `${path}.tmp-${process.pid}-${Date.now()}`;
  const file = await open(temp, "w", 0o600);
  try {
    await file.writeFile(`${JSON.stringify(value, null, 2)}\n`, "utf-8");
    await file.sync();
  } finally {
    await file.close();
  }
  await rename(temp, path);
  const directory = await open(dirname(path), "r");
  try {
    await directory.sync();
  } finally {
    await directory.close();
  }
}

async function readJson<T>(path: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(path, "utf-8")) as T;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

async function withFileLock<T>(path: string, action: () => Promise<T>): Promise<T> {
  await mkdir(dirname(path), { recursive: true });
  let lock: Awaited<ReturnType<typeof open>> | null = null;
  for (let attempt = 0; attempt < 200; attempt += 1) {
    try {
      lock = await open(path, "wx", 0o600);
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  }
  if (!lock) throw new Error(`transaction_lock_timeout:${path}`);
  try {
    return await action();
  } finally {
    await lock.close();
    await unlink(path).catch(() => undefined);
  }
}

export class MutationTransactionJournal {
  constructor(private readonly root: string) {}

  private manifestPath(transactionId: string): string {
    return join(this.root, "manifests", `${canonicalHash(transactionId).slice(7)}.json`);
  }

  private mutationIndexPath(mutationId: string): string {
    return join(this.root, "mutation-index", `${canonicalHash(mutationId).slice(7)}.json`);
  }

  private lockPath(): string {
    return join(this.root, ".journal.lock");
  }

  async load(transactionId: string): Promise<MutationTransactionManifest | null> {
    const raw = await readJson<unknown>(this.manifestPath(transactionId));
    return raw === null ? null : MutationTransactionManifestSchema.parse(raw);
  }

  async findByMutationId(mutationId: string): Promise<MutationTransactionManifest | null> {
    const index = await readJson<{ transaction_id: string }>(this.mutationIndexPath(mutationId));
    return index ? this.load(index.transaction_id) : null;
  }

  async create(manifest: MutationTransactionManifest): Promise<MutationTransactionManifest> {
    MutationTransactionManifestSchema.parse(manifest);
    if (manifest.state !== "created") throw new Error("new mutation transaction must be created");
    return withFileLock(this.lockPath(), async () => {
      const existing = await this.findByMutationId(manifest.mutation_id);
      if (existing) {
        if (existing.transaction_id !== manifest.transaction_id) {
          throw new Error("mutation_id_already_bound_to_transaction");
        }
        return existing;
      }
      await atomicWriteJson(this.manifestPath(manifest.transaction_id), manifest);
      await atomicWriteJson(this.mutationIndexPath(manifest.mutation_id), {
        mutation_id: manifest.mutation_id,
        transaction_id: manifest.transaction_id,
      });
      return manifest;
    });
  }

  async snapshot(manifest: MutationTransactionManifest): Promise<void> {
    MutationTransactionManifestSchema.parse(manifest);
    await withFileLock(this.lockPath(), async () => {
      const previous = await this.load(manifest.transaction_id);
      if (!previous) throw new Error("mutation_transaction_not_found");
      if (
        previous.mutation_id !== manifest.mutation_id ||
        previous.transaction_id !== manifest.transaction_id ||
        previous.state !== manifest.state
      ) {
        throw new Error("mutation_transaction_snapshot_identity_or_state_changed");
      }
      await atomicWriteJson(this.manifestPath(manifest.transaction_id), manifest);
    });
  }

  async transition(
    previous: MutationTransactionManifest,
    next: MutationTransactionManifest,
  ): Promise<void> {
    assertMutationTransactionTransition(previous, next);
    await withFileLock(this.lockPath(), async () => {
      const durable = await this.load(previous.transaction_id);
      if (!durable || canonicalHash(durable) !== canonicalHash(previous)) {
        throw new Error("mutation_transaction_compare_and_swap_failed");
      }
      await atomicWriteJson(this.manifestPath(next.transaction_id), next);
    });
  }

  async listRecoverable(): Promise<MutationTransactionManifest[]> {
    const directory = join(this.root, "manifests");
    let names: string[];
    try {
      names = await readdir(directory);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
      throw error;
    }
    const manifests = await Promise.all(
      names
        .filter((name) => name.endsWith(".json"))
        .map((name) => readJson<unknown>(join(directory, name))),
    );
    return manifests
      .filter((value): value is unknown => value !== null)
      .map((value) => MutationTransactionManifestSchema.parse(value))
      .filter((manifest) => !["committed", "aborted"].includes(manifest.state));
  }
}

interface PathLeaseState {
  schema_version: "prompt_mutation_path_leases_v1";
  leases: Record<
    string,
    { mutation_id: string; transaction_id: string; experiment_id: string; acquired_at: string }
  >;
}

export class MutationPathLeaseRegistry {
  constructor(private readonly root: string) {}

  private path(): string {
    return join(this.root, "path-leases.json");
  }

  private lockPath(): string {
    return join(this.root, ".leases.lock");
  }

  async acquire(manifest: MutationTransactionManifest): Promise<void> {
    await withFileLock(this.lockPath(), async () => {
      const state: PathLeaseState = (await readJson<PathLeaseState>(this.path())) ?? {
        schema_version: "prompt_mutation_path_leases_v1",
        leases: {},
      };
      for (const path of manifest.target_paths) {
        const existing = state.leases[path];
        if (existing && existing.mutation_id !== manifest.mutation_id) {
          throw new Error(`mutation_path_lease_conflict:${path}:${existing.mutation_id}`);
        }
      }
      for (const path of manifest.target_paths) {
        state.leases[path] = {
          mutation_id: manifest.mutation_id,
          transaction_id: manifest.transaction_id,
          experiment_id: manifest.experiment_id,
          acquired_at: manifest.created_at,
        };
      }
      await atomicWriteJson(this.path(), state);
    });
  }

  async release(mutationId: string): Promise<void> {
    await withFileLock(this.lockPath(), async () => {
      const state = await readJson<PathLeaseState>(this.path());
      if (!state) return;
      state.leases = Object.fromEntries(
        Object.entries(state.leases).filter(([, lease]) => lease.mutation_id !== mutationId),
      );
      await atomicWriteJson(this.path(), state);
    });
  }
}

function adapterMap(adapters: ReadonlyArray<MutationRepositoryAdapter>) {
  return new Map(adapters.map((adapter) => [adapter.repoId, adapter]));
}

function adapterFor(
  adapters: ReadonlyMap<string, MutationRepositoryAdapter>,
  component: MutationTransactionManifest["components"][number],
): MutationRepositoryAdapter {
  const adapter = adapters.get(component.repo_id);
  if (!adapter) throw new Error(`mutation_repository_adapter_missing:${component.repo_id}`);
  return adapter;
}

export class PromptMutationTransactionCoordinator {
  constructor(
    private readonly journal: MutationTransactionJournal,
    private readonly leases: MutationPathLeaseRegistry,
  ) {}

  async execute(
    created: MutationTransactionManifest,
    adaptersInput: ReadonlyArray<MutationRepositoryAdapter>,
    metadataLog: MutationMetadataLogWriter,
    now = () => new Date().toISOString(),
  ): Promise<MutationTransactionManifest> {
    const existing = await this.journal.findByMutationId(created.mutation_id);
    if (existing) {
      if (existing.transaction_id !== created.transaction_id) {
        throw new Error("mutation_id_already_bound_to_transaction");
      }
      if (["committed", "aborted"].includes(existing.state)) return existing;
      return this.reconcile(existing.transaction_id, adaptersInput, metadataLog, now);
    }
    let manifest = await this.journal.create(created);
    try {
      await this.leases.acquire(manifest);
    } catch (error) {
      const aborted: MutationTransactionManifest = {
        ...manifest,
        state: "aborted",
        aborted_at: now(),
        recovery_decision: "path_lease_conflict",
      };
      await this.journal.transition(manifest, aborted);
      throw error;
    }
    const adapters = adapterMap(adaptersInput);
    const preparedRepoIds: string[] = [];
    try {
      for (const [index, component] of manifest.components.entries()) {
        await adapterFor(adapters, component).prepare(component);
        preparedRepoIds.push(component.repo_id);
        manifest = {
          ...manifest,
          components: manifest.components.map((item, itemIndex) =>
            itemIndex === index ? { ...item, prepare_status: "prepared" as const } : item,
          ),
        };
        await this.journal.snapshot(manifest);
      }
    } catch (error) {
      for (const component of manifest.components) {
        if (preparedRepoIds.includes(component.repo_id)) {
          await adapterFor(adapters, component)
            .abort(component)
            .catch(() => undefined);
        }
      }
      const aborted: MutationTransactionManifest = {
        ...manifest,
        state: "aborted",
        components: manifest.components.map((component) => ({
          ...component,
          prepare_status: preparedRepoIds.includes(component.repo_id) ? "aborted" : "pending",
        })),
        aborted_at: now(),
        recovery_decision: "prepare_failed_abort",
      };
      await this.journal.transition(manifest, aborted);
      await this.leases.release(manifest.mutation_id);
      throw error;
    }

    const prepared: MutationTransactionManifest = {
      ...manifest,
      state: "prepared",
      prepared_at: now(),
    };
    await this.journal.transition(manifest, prepared);
    manifest = prepared;

    try {
      for (const [index, component] of manifest.components.entries()) {
        const newCommit = await adapterFor(adapters, component).commit(component);
        manifest = {
          ...manifest,
          components: manifest.components.map((item, itemIndex) =>
            itemIndex === index ? { ...item, new_commit: newCommit } : item,
          ),
        };
        await this.journal.snapshot(manifest);
      }
    } catch (error) {
      manifest = { ...manifest, recovery_state: "pending", recovery_decision: "commit_incomplete" };
      await this.journal.snapshot(manifest);
      throw new MutationTransactionPendingRecoveryError((error as Error).message);
    }

    const logPending: MutationTransactionManifest = {
      ...manifest,
      state: "committed_log_pending",
      recovery_state: "not_needed",
    };
    await this.journal.transition(manifest, logPending);
    manifest = logPending;
    try {
      await metadataLog.appendOnce(manifest, committedCandidateManifestHash(manifest));
    } catch (error) {
      const pending = { ...manifest, recovery_state: "pending" as const };
      await this.journal.snapshot(pending);
      throw new MutationTransactionPendingRecoveryError((error as Error).message);
    }
    const committed: MutationTransactionManifest = {
      ...manifest,
      state: "committed",
      metadata_log: { ...manifest.metadata_log, appended: true },
      committed_at: now(),
    };
    await this.journal.transition(manifest, committed);
    return committed;
  }

  async reconcile(
    transactionId: string,
    adaptersInput: ReadonlyArray<MutationRepositoryAdapter>,
    metadataLog: MutationMetadataLogWriter,
    now = () => new Date().toISOString(),
  ): Promise<MutationTransactionManifest> {
    let manifest = await this.journal.load(transactionId);
    if (!manifest) throw new Error("mutation_transaction_not_found");
    if (["committed", "aborted"].includes(manifest.state)) return manifest;
    const adapters = adapterMap(adaptersInput);

    if (manifest.state === "created") {
      const aborted: MutationTransactionManifest = {
        ...manifest,
        state: "aborted",
        recovery_state: "reconciled",
        aborted_at: now(),
        recovery_decision: "created_transaction_aborted_on_recovery",
      };
      await this.journal.transition(manifest, aborted);
      await this.leases.release(manifest.mutation_id);
      return aborted;
    }

    if (manifest.state === "prepared") {
      const inspections = await Promise.all(
        manifest.components.map((component) => adapterFor(adapters, component).inspect(component)),
      );
      const allVisible = inspections.every(
        (inspection) => inspection.candidate_visible && inspection.new_commit,
      );
      if (!allVisible) {
        await Promise.all(
          manifest.components.map((component) =>
            adapterFor(adapters, component)
              .abort(component)
              .catch(() => undefined),
          ),
        );
        const aborted: MutationTransactionManifest = {
          ...manifest,
          state: "aborted",
          recovery_state: "reconciled",
          components: manifest.components.map((component) => ({
            ...component,
            new_commit: null,
            prepare_status: "aborted",
          })),
          aborted_at: now(),
          recovery_decision: "partial_candidate_refs_removed",
        };
        await this.journal.transition(manifest, aborted);
        await this.leases.release(manifest.mutation_id);
        return aborted;
      }
      const completedPrepare: MutationTransactionManifest = {
        ...manifest,
        recovery_state: "pending",
        components: manifest.components.map((component, index) => {
          const inspection = inspections[index];
          if (!inspection?.new_commit) {
            throw new Error("mutation_transaction_inspection_result_missing");
          }
          return { ...component, new_commit: inspection.new_commit };
        }),
      };
      await this.journal.snapshot(completedPrepare);
      const logPending: MutationTransactionManifest = {
        ...completedPrepare,
        state: "committed_log_pending",
      };
      await this.journal.transition(completedPrepare, logPending);
      manifest = logPending;
    }

    if (manifest.state === "committed_log_pending") {
      await metadataLog.appendOnce(manifest, committedCandidateManifestHash(manifest));
      const committed: MutationTransactionManifest = {
        ...manifest,
        state: "committed",
        recovery_state: "reconciled",
        metadata_log: { ...manifest.metadata_log, appended: true },
        committed_at: now(),
        recovery_decision: "metadata_log_reconciled",
      };
      await this.journal.transition(manifest, committed);
      return committed;
    }
    throw new Error(`mutation_transaction_recovery_unsupported:${manifest.state}`);
  }

  async completeExperiment(mutationId: string): Promise<void> {
    await this.leases.release(mutationId);
  }
}

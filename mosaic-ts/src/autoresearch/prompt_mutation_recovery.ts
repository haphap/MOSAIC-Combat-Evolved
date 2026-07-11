import { createHash } from "node:crypto";
import { mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { MutationTransactionManifest } from "../agents/prompts/prompt_release_contract.js";
import type { BridgeApi } from "../bridge/types.js";
import { appendKnobMutationMetadataLog, type KnobMutationMetadata } from "./mutator.js";
import {
  type MutationMetadataLogWriter,
  MutationPathLeaseRegistry,
  type MutationRepositoryAdapter,
  MutationTransactionJournal,
  PromptMutationTransactionCoordinator,
} from "./transaction_coordinator.js";

const SHA256 = /^sha256:[0-9a-f]{64}$/;

export interface PromptMutationRecoveryDescriptor {
  schema_version: "prompt_mutation_recovery_v1";
  transaction_id: string;
  mutation_id: string;
  version_id: number;
  agent: string;
  cohort: string;
  branch?: string;
  components?: Array<{
    repo_id: "MOSAIC-Prompts" | "MOSAIC-RKE";
    target: "private_git" | "project_git";
    branch: string;
  }>;
  summary: string;
  prompt_sha256: string;
  code_commit_hash: string;
  metadata_log_path: string;
  mutation_metadata: KnobMutationMetadata;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value === undefined ? null : value;
}

export function promptMutationRecoveryDescriptorHash(
  descriptor: PromptMutationRecoveryDescriptor,
): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(descriptor)))
    .digest("hex")}`;
}

function descriptorPath(root: string, transactionId: string): string {
  const digest = createHash("sha256").update(transactionId).digest("hex");
  return join(root, "recovery-descriptors", `${digest}.json`);
}

async function atomicWrite(path: string, value: unknown): Promise<void> {
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

async function withFileLock<T>(path: string, action: () => Promise<T>): Promise<T> {
  await mkdir(dirname(path), { recursive: true });
  let handle: Awaited<ReturnType<typeof open>> | null = null;
  for (let attempt = 0; attempt < 200; attempt += 1) {
    try {
      handle = await open(path, "wx", 0o600);
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  }
  if (!handle) throw new Error("prompt_mutation_recovery_descriptor_lock_timeout");
  try {
    return await action();
  } finally {
    await handle.close();
    await unlink(path).catch(() => undefined);
  }
}

function parseDescriptor(value: unknown): PromptMutationRecoveryDescriptor {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("prompt_mutation_recovery_descriptor_invalid");
  }
  const descriptor = value as Partial<PromptMutationRecoveryDescriptor>;
  if (
    descriptor.schema_version !== "prompt_mutation_recovery_v1" ||
    !descriptor.transaction_id ||
    !descriptor.mutation_id ||
    !Number.isInteger(descriptor.version_id) ||
    (descriptor.version_id ?? 0) < 1 ||
    !descriptor.agent ||
    !descriptor.cohort ||
    (!descriptor.branch && !descriptor.components) ||
    (descriptor.branch !== undefined && descriptor.components !== undefined) ||
    (descriptor.components !== undefined &&
      (descriptor.components.length !== 2 ||
        new Set(descriptor.components.map((component) => component.repo_id)).size !==
          descriptor.components.length ||
        descriptor.components.some(
          (component) =>
            !component.branch ||
            (component.repo_id === "MOSAIC-Prompts" && component.target !== "private_git") ||
            (component.repo_id === "MOSAIC-RKE" && component.target !== "project_git") ||
            !["MOSAIC-Prompts", "MOSAIC-RKE"].includes(component.repo_id) ||
            !["private_git", "project_git"].includes(component.target),
        ))) ||
    typeof descriptor.summary !== "string" ||
    !/^[0-9a-f]{64}$/.test(descriptor.prompt_sha256 ?? "") ||
    !descriptor.code_commit_hash ||
    !descriptor.metadata_log_path ||
    !descriptor.mutation_metadata ||
    typeof descriptor.mutation_metadata !== "object" ||
    descriptor.mutation_metadata.schema_version !== "knob_mutation_metadata_v1"
  ) {
    throw new Error("prompt_mutation_recovery_descriptor_invalid");
  }
  return descriptor as PromptMutationRecoveryDescriptor;
}

export class PromptMutationRecoveryDescriptorStore {
  constructor(private readonly root: string) {}

  async writeOnce(descriptor: PromptMutationRecoveryDescriptor): Promise<string> {
    const parsed = parseDescriptor(descriptor);
    const path = descriptorPath(this.root, parsed.transaction_id);
    return withFileLock(`${path}.lock`, async () => {
      let existing: PromptMutationRecoveryDescriptor | null = null;
      try {
        existing = parseDescriptor(JSON.parse(await readFile(path, "utf-8")));
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
      if (existing) {
        if (
          promptMutationRecoveryDescriptorHash(existing) !==
          promptMutationRecoveryDescriptorHash(parsed)
        ) {
          throw new Error("prompt_mutation_recovery_descriptor_conflict");
        }
        return promptMutationRecoveryDescriptorHash(existing);
      }
      await atomicWrite(path, parsed);
      return promptMutationRecoveryDescriptorHash(parsed);
    });
  }

  async load(transactionId: string): Promise<PromptMutationRecoveryDescriptor | null> {
    try {
      return parseDescriptor(
        JSON.parse(await readFile(descriptorPath(this.root, transactionId), "utf-8")),
      );
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
  }
}

function promptComponent(manifest: MutationTransactionManifest) {
  const matches = manifest.components.filter((component) => component.repo_id === "MOSAIC-Prompts");
  if (matches.length !== 1) throw new Error("prompt_mutation_recovery_component_invalid");
  return matches[0] as MutationTransactionManifest["components"][number];
}

function descriptorComponents(
  descriptor: PromptMutationRecoveryDescriptor,
): NonNullable<PromptMutationRecoveryDescriptor["components"]> {
  return (
    descriptor.components ?? [
      {
        repo_id: "MOSAIC-Prompts",
        target: "private_git",
        branch: descriptor.branch as string,
      },
    ]
  );
}

function assertDescriptorClosure(
  manifest: MutationTransactionManifest,
  descriptor: PromptMutationRecoveryDescriptor,
): void {
  if (
    descriptor.transaction_id !== manifest.transaction_id ||
    descriptor.mutation_id !== manifest.mutation_id ||
    descriptor.mutation_metadata.transaction_id !== manifest.transaction_id ||
    descriptor.mutation_metadata.mutation_id !== manifest.mutation_id ||
    descriptor.mutation_metadata.experiment_id !== manifest.experiment_id ||
    descriptor.mutation_metadata.agent !== descriptor.agent ||
    descriptor.mutation_metadata.cohort !== descriptor.cohort ||
    descriptor.mutation_metadata.catalog_hash !== manifest.catalog_hash ||
    descriptor.mutation_metadata.schema_hash !== manifest.schema_hash ||
    descriptor.mutation_metadata.evaluation_contract_hash !== manifest.evaluation_contract_hash ||
    promptMutationRecoveryDescriptorHash(descriptor) !== manifest.recovery_descriptor_hash ||
    !SHA256.test(manifest.recovery_descriptor_hash)
  ) {
    throw new Error("prompt_mutation_recovery_descriptor_hash_or_identity_mismatch");
  }
  const components = descriptorComponents(descriptor);
  if (components.length !== manifest.components.length) {
    throw new Error("prompt_mutation_recovery_component_count_mismatch");
  }
  for (const descriptorComponent of components) {
    const matches = manifest.components.filter(
      (component) => component.repo_id === descriptorComponent.repo_id,
    );
    if (
      matches.length !== 1 ||
      matches[0]?.candidate_ref !== `refs/heads/${descriptorComponent.branch}`
    ) {
      throw new Error("prompt_mutation_recovery_candidate_ref_mismatch");
    }
  }
}

function recoveryAdapter(
  api: BridgeApi,
  descriptor: NonNullable<PromptMutationRecoveryDescriptor["components"]>[number],
): MutationRepositoryAdapter {
  return {
    repoId: descriptor.repo_id,
    prepare: async () => {
      throw new Error("prompt_mutation_recovery_cannot_prepare");
    },
    commit: async () => {
      throw new Error("prompt_mutation_recovery_cannot_commit");
    },
    inspect: async (component) => {
      const expectedHashes = Object.fromEntries(
        component.files.map((file) => [file.path, file.new_hash]),
      );
      const state = await api.promptsCandidateState({
        branch: descriptor.branch,
        target: descriptor.target,
        expected_hashes: expectedHashes,
      });
      return {
        candidate_visible: state.candidate_visible && state.hashes_match,
        new_commit: state.new_commit,
      };
    },
    abort: async () => {
      await api.promptsAbortCandidate({ branch: descriptor.branch, target: descriptor.target });
    },
  };
}

function recoveryMetadataLog(
  api: BridgeApi,
  descriptor: PromptMutationRecoveryDescriptor,
): MutationMetadataLogWriter {
  return {
    appendOnce: async (manifest, manifestHash) => {
      const component = promptComponent(manifest);
      const codeComponent = manifest.components.find(
        (candidate) => candidate.repo_id === "MOSAIC-RKE",
      );
      if (!component.new_commit) {
        throw new Error("prompt_mutation_recovery_candidate_commit_missing");
      }
      const metadata = {
        ...descriptor.mutation_metadata,
        transaction_manifest_hash: manifestHash,
      };
      await api.autoresearchRecordMutation({
        version_id: descriptor.version_id,
        commit_hash: component.new_commit,
        summary: descriptor.summary,
        prompt_repo_id: "private",
        prompt_base_commit_hash: component.base_commit,
        prompt_sha256: descriptor.prompt_sha256,
        code_commit_hash: codeComponent?.new_commit ?? descriptor.code_commit_hash,
        mutation_metadata: metadata,
      });
      await appendKnobMutationMetadataLog({
        logPath: descriptor.metadata_log_path,
        metadata,
      });
    },
  };
}

export async function reconcilePendingPromptMutationTransactions(opts: {
  root: string;
  api: BridgeApi;
  now?: () => string;
}): Promise<MutationTransactionManifest[]> {
  const journal = new MutationTransactionJournal(opts.root);
  const coordinator = new PromptMutationTransactionCoordinator(
    journal,
    new MutationPathLeaseRegistry(opts.root),
  );
  const descriptors = new PromptMutationRecoveryDescriptorStore(opts.root);
  const recoverable = await journal.listRecoverable();
  const reconciled: MutationTransactionManifest[] = [];
  for (const manifest of recoverable) {
    const descriptor = await descriptors.load(manifest.transaction_id);
    if (!descriptor) throw new Error("prompt_mutation_recovery_descriptor_missing");
    assertDescriptorClosure(manifest, descriptor);
    reconciled.push(
      await coordinator.reconcile(
        manifest.transaction_id,
        descriptorComponents(descriptor).map((component) => recoveryAdapter(opts.api, component)),
        recoveryMetadataLog(opts.api, descriptor),
        opts.now,
      ),
    );
  }
  return reconciled;
}

export async function reconcileTerminalPromptMutationLeases(opts: {
  root: string;
  api: BridgeApi;
}): Promise<number> {
  const leases = new MutationPathLeaseRegistry(opts.root);
  const activeMutationIds = await leases.activeMutationIds();
  if (activeMutationIds.size === 0 || typeof opts.api.promptsAuditVersions !== "function") return 0;
  const { versions } = await opts.api.promptsAuditVersions({ limit: 10_000 });
  const terminalMutationIds = new Set(
    versions
      .filter(
        (version) =>
          version.mutation_id &&
          activeMutationIds.has(version.mutation_id) &&
          (["kept", "reverted", "invalid"].includes(version.mutation_lifecycle ?? "") ||
            ["keep", "revert", "incompatible"].includes(version.status)),
      )
      .map((version) => version.mutation_id as string),
  );
  for (const mutationId of terminalMutationIds) await leases.release(mutationId);
  return terminalMutationIds.size;
}

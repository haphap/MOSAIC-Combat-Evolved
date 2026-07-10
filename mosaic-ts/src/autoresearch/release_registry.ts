import { createHash } from "node:crypto";
import { mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";
import {
  type ActivePromptReleaseManifest,
  ActivePromptReleaseManifestSchema,
  assertPromptReleaseTransition,
} from "../agents/prompts/prompt_release_contract.js";

export interface ActivePromptReleasePointer {
  schema_version: "active_prompt_release_pointer_v1";
  current_release_id: string | null;
  pointer_version: number;
  updated_at: string;
}

function idHash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
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

async function readJson<T>(path: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(path, "utf-8")) as T;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

async function lock<T>(path: string, action: () => Promise<T>): Promise<T> {
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
  if (!handle) throw new Error("active_release_registry_lock_timeout");
  try {
    return await action();
  } finally {
    await handle.close();
    await unlink(path).catch(() => undefined);
  }
}

function immutableReleaseClosure(manifest: ActivePromptReleaseManifest): unknown {
  return {
    release_id: manifest.release_id,
    base_release_id: manifest.base_release_id,
    prompt_commit: manifest.prompt_commit,
    code_commit: manifest.code_commit,
    prompt_hash: manifest.prompt_hash,
    prompt_pairs: manifest.prompt_pairs,
    catalog_hash: manifest.catalog_hash,
    schema_hash: manifest.schema_hash,
    evaluation_contract_hash: manifest.evaluation_contract_hash,
    keep_decision_hash: manifest.keep_decision_hash,
    keep_decision_state: manifest.keep_decision_state,
    cohort: manifest.activation_scope.cohort,
    account_mode: manifest.activation_scope.account_mode,
    approval_policy_id: manifest.approval_policy_id,
    rollback_triggers: manifest.rollback_triggers,
    previous_approved_release_id: manifest.previous_approved_release_id,
    bundled_fallback: manifest.bundled_fallback,
    created_at: manifest.created_at,
  };
}

export class ActivePromptReleaseRegistry {
  constructor(private readonly root: string) {}

  private manifestPath(releaseId: string): string {
    return join(this.root, "releases", `${idHash(releaseId)}.json`);
  }

  private pointerPath(): string {
    return join(this.root, "active-pointer.json");
  }

  private lockPath(): string {
    return join(this.root, ".release.lock");
  }

  private auditPath(): string {
    return join(this.root, "release-audit.jsonl");
  }

  async load(releaseId: string): Promise<ActivePromptReleaseManifest | null> {
    const value = await readJson<unknown>(this.manifestPath(releaseId));
    return value === null ? null : ActivePromptReleaseManifestSchema.parse(value);
  }

  async pointer(): Promise<ActivePromptReleasePointer> {
    return (
      (await readJson<ActivePromptReleasePointer>(this.pointerPath())) ?? {
        schema_version: "active_prompt_release_pointer_v1",
        current_release_id: null,
        pointer_version: 0,
        updated_at: new Date(0).toISOString(),
      }
    );
  }

  async stage(manifest: ActivePromptReleaseManifest): Promise<void> {
    ActivePromptReleaseManifestSchema.parse(manifest);
    if (manifest.lifecycle_state !== "staged") {
      throw new Error("prompt_release_must_start_staged");
    }
    await lock(this.lockPath(), async () => {
      if (await this.load(manifest.release_id)) throw new Error("prompt_release_already_exists");
      await atomicWrite(this.manifestPath(manifest.release_id), manifest);
      await this.appendAudit({ event: "staged", release_id: manifest.release_id });
    });
  }

  async transition(
    next: ActivePromptReleaseManifest,
    opts: { expectedBaseReleaseId?: string | null } = {},
  ): Promise<void> {
    ActivePromptReleaseManifestSchema.parse(next);
    await lock(this.lockPath(), async () => {
      const previous = await this.load(next.release_id);
      if (!previous) throw new Error("prompt_release_not_found");
      assertPromptReleaseTransition(previous, next);
      if (
        JSON.stringify(immutableReleaseClosure(previous)) !==
        JSON.stringify(immutableReleaseClosure(next))
      ) {
        throw new Error("prompt_release_immutable_closure_changed");
      }

      const pointer = await this.pointer();
      if (next.lifecycle_state === "active") {
        if (!next.activated_at) throw new Error("prompt_release_activation_timestamp_missing");
        if (opts.expectedBaseReleaseId === undefined) {
          throw new Error("prompt_release_activation_requires_compare_and_swap_base");
        }
        if (
          pointer.current_release_id !== opts.expectedBaseReleaseId ||
          next.base_release_id !== opts.expectedBaseReleaseId
        ) {
          throw new Error("prompt_release_active_pointer_compare_and_swap_failed");
        }
        await atomicWrite(this.pointerPath(), {
          schema_version: "active_prompt_release_pointer_v1",
          current_release_id: next.release_id,
          pointer_version: pointer.pointer_version + 1,
          updated_at: next.activated_at,
        } satisfies ActivePromptReleasePointer);
      }

      if (next.lifecycle_state === "rolled_back" && previous.lifecycle_state === "active") {
        if (!next.rolled_back_at) throw new Error("prompt_release_rollback_timestamp_missing");
        if (pointer.current_release_id !== next.release_id) {
          throw new Error("prompt_release_rollback_pointer_compare_and_swap_failed");
        }
        const rollbackTarget = next.previous_approved_release_id ?? next.base_release_id;
        if (rollbackTarget) {
          const target = await this.load(rollbackTarget);
          if (target?.lifecycle_state !== "active") {
            throw new Error("prompt_release_rollback_target_not_active");
          }
        }
        await atomicWrite(this.pointerPath(), {
          schema_version: "active_prompt_release_pointer_v1",
          current_release_id: rollbackTarget,
          pointer_version: pointer.pointer_version + 1,
          updated_at: next.rolled_back_at,
        } satisfies ActivePromptReleasePointer);
      }

      await atomicWrite(this.manifestPath(next.release_id), next);
      await this.appendAudit({
        event: next.lifecycle_state,
        release_id: next.release_id,
        previous_state: previous.lifecycle_state,
        pointer_version: (await this.pointer()).pointer_version,
      });
    });
  }

  async resolveActive(): Promise<ActivePromptReleaseManifest | null> {
    const pointer = await this.pointer();
    if (!pointer.current_release_id) return null;
    const manifest = await this.load(pointer.current_release_id);
    if (manifest?.lifecycle_state !== "active") {
      throw new Error("active_prompt_release_pointer_is_not_closed");
    }
    return manifest;
  }

  private async appendAudit(event: Record<string, unknown>): Promise<void> {
    await mkdir(dirname(this.auditPath()), { recursive: true });
    const file = await open(this.auditPath(), "a", 0o600);
    try {
      await file.writeFile(
        `${JSON.stringify({ ...event, recorded_at: new Date().toISOString() })}\n`,
      );
      await file.sync();
    } finally {
      await file.close();
    }
  }
}

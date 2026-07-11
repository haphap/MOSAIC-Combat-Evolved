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

export interface PromptReleaseCanaryPointer {
  schema_version: "prompt_release_canary_pointer_v1";
  current_release_id: string | null;
  traffic_percent: number;
  pointer_version: number;
  updated_at: string;
}

export interface PromptReleaseAuditContext {
  operator: string;
  reason: string;
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
    stage_snapshot_hashes: manifest.stage_snapshot_hashes,
    catalog_hash: manifest.catalog_hash,
    schema_hash: manifest.schema_hash,
    evaluation_contract_hash: manifest.evaluation_contract_hash,
    keep_decision_hash: manifest.keep_decision_hash,
    keep_decision_state: manifest.keep_decision_state,
    release_evidence: manifest.release_evidence,
    cohort: manifest.activation_scope.cohort,
    account_mode: manifest.activation_scope.account_mode,
    approval_policy_id: manifest.approval_policy_id,
    rollback_triggers: manifest.rollback_triggers,
    previous_approved_release_id: manifest.previous_approved_release_id,
    bundled_fallback: manifest.bundled_fallback,
    created_at: manifest.created_at,
  };
}

function expectedPreviousState(
  manifest: ActivePromptReleaseManifest,
): ActivePromptReleaseManifest["lifecycle_state"] {
  if (manifest.lifecycle_state === "canary") return "staged";
  if (manifest.lifecycle_state === "active") return "canary";
  if (manifest.lifecycle_state === "rolled_back") {
    return manifest.activated_at ? "active" : "canary";
  }
  return "staged";
}

export class ActivePromptReleaseRegistry {
  constructor(private readonly root: string) {}

  private manifestPath(releaseId: string): string {
    return join(this.root, "releases", `${idHash(releaseId)}.json`);
  }

  private pointerPath(): string {
    return join(this.root, "active-pointer.json");
  }

  private canaryPointerPath(): string {
    return join(this.root, "canary-pointer.json");
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

  async canaryPointer(): Promise<PromptReleaseCanaryPointer> {
    return (
      (await readJson<PromptReleaseCanaryPointer>(this.canaryPointerPath())) ?? {
        schema_version: "prompt_release_canary_pointer_v1",
        current_release_id: null,
        traffic_percent: 0,
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
      const existing = await this.load(manifest.release_id);
      if (existing) {
        if (JSON.stringify(existing) !== JSON.stringify(manifest)) {
          throw new Error("prompt_release_already_exists");
        }
        await this.appendAudit({
          event_id: `${manifest.release_id}:staged`,
          event: "staged",
          release_id: manifest.release_id,
        });
        return;
      }
      await atomicWrite(this.manifestPath(manifest.release_id), manifest);
      await this.appendAudit({
        event_id: `${manifest.release_id}:staged`,
        event: "staged",
        release_id: manifest.release_id,
      });
    });
  }

  async transition(
    next: ActivePromptReleaseManifest,
    opts: {
      expectedBaseReleaseId?: string | null;
      audit?: PromptReleaseAuditContext;
    } = {},
  ): Promise<void> {
    ActivePromptReleaseManifestSchema.parse(next);
    await lock(this.lockPath(), async () => {
      const previous = await this.load(next.release_id);
      if (!previous) throw new Error("prompt_release_not_found");
      const exactRetry = previous.lifecycle_state === next.lifecycle_state;
      if (exactRetry) {
        if (JSON.stringify(previous) !== JSON.stringify(next)) {
          throw new Error("prompt_release_transition_retry_conflict");
        }
      } else {
        assertPromptReleaseTransition(previous, next);
      }
      if (
        JSON.stringify(immutableReleaseClosure(previous)) !==
        JSON.stringify(immutableReleaseClosure(next))
      ) {
        throw new Error("prompt_release_immutable_closure_changed");
      }
      if (previous.lifecycle_state !== "staged" && previous.approved_by !== next.approved_by) {
        throw new Error("prompt_release_approval_identity_changed");
      }
      if (!opts.audit?.operator.trim() || !opts.audit.reason.trim()) {
        throw new Error("prompt_release_transition_audit_required");
      }
      if (
        ["canary", "active"].includes(next.lifecycle_state) &&
        opts.audit.operator !== next.approved_by
      ) {
        throw new Error("prompt_release_transition_operator_mismatch");
      }

      const pointer = await this.pointer();
      const canaryPointer = await this.canaryPointer();
      if (
        next.lifecycle_state === "canary" &&
        canaryPointer.current_release_id !== null &&
        canaryPointer.current_release_id !== next.release_id
      ) {
        throw new Error("prompt_release_canary_pointer_conflict");
      }
      if (
        next.lifecycle_state === "canary" &&
        pointer.current_release_id !== next.base_release_id
      ) {
        throw new Error("prompt_release_canary_base_pointer_mismatch");
      }
      if (next.lifecycle_state === "active") {
        if (!next.activated_at) throw new Error("prompt_release_activation_timestamp_missing");
        if (opts.expectedBaseReleaseId === undefined) {
          throw new Error("prompt_release_activation_requires_compare_and_swap_base");
        }
        const alreadyActivated = pointer.current_release_id === next.release_id;
        if (
          !alreadyActivated &&
          (pointer.current_release_id !== opts.expectedBaseReleaseId ||
            next.base_release_id !== opts.expectedBaseReleaseId)
        ) {
          throw new Error("prompt_release_active_pointer_compare_and_swap_failed");
        }
      }

      const activeRollback =
        next.lifecycle_state === "rolled_back" &&
        (previous.lifecycle_state === "active" || next.activated_at !== null);
      let rollbackTarget: string | null = null;
      if (activeRollback) {
        if (!next.rolled_back_at) throw new Error("prompt_release_rollback_timestamp_missing");
        rollbackTarget = next.previous_approved_release_id ?? next.base_release_id;
        const alreadyRolledBack = pointer.current_release_id === rollbackTarget;
        if (!alreadyRolledBack && pointer.current_release_id !== next.release_id) {
          throw new Error("prompt_release_rollback_pointer_compare_and_swap_failed");
        }
        if (rollbackTarget) {
          const target = await this.load(rollbackTarget);
          if (target?.lifecycle_state !== "active") {
            throw new Error("prompt_release_rollback_target_not_active");
          }
        }
      }

      if (!exactRetry) await atomicWrite(this.manifestPath(next.release_id), next);

      if (
        next.lifecycle_state === "canary" &&
        (canaryPointer.current_release_id !== next.release_id ||
          canaryPointer.traffic_percent !== next.activation_scope.traffic_percent)
      ) {
        await atomicWrite(this.canaryPointerPath(), {
          schema_version: "prompt_release_canary_pointer_v1",
          current_release_id: next.release_id,
          traffic_percent: next.activation_scope.traffic_percent,
          pointer_version: canaryPointer.pointer_version + 1,
          updated_at: next.canary_started_at as string,
        } satisfies PromptReleaseCanaryPointer);
      }

      if (next.lifecycle_state === "active" && pointer.current_release_id !== next.release_id) {
        await atomicWrite(this.pointerPath(), {
          schema_version: "active_prompt_release_pointer_v1",
          current_release_id: next.release_id,
          pointer_version: pointer.pointer_version + 1,
          updated_at: next.activated_at as string,
        } satisfies ActivePromptReleasePointer);
      }

      if (
        ["active", "rolled_back"].includes(next.lifecycle_state) &&
        canaryPointer.current_release_id === next.release_id
      ) {
        await atomicWrite(this.canaryPointerPath(), {
          schema_version: "prompt_release_canary_pointer_v1",
          current_release_id: null,
          traffic_percent: 0,
          pointer_version: canaryPointer.pointer_version + 1,
          updated_at: (next.lifecycle_state === "active"
            ? next.activated_at
            : next.rolled_back_at) as string,
        } satisfies PromptReleaseCanaryPointer);
      }

      if (activeRollback && pointer.current_release_id !== rollbackTarget) {
        await atomicWrite(this.pointerPath(), {
          schema_version: "active_prompt_release_pointer_v1",
          current_release_id: rollbackTarget,
          pointer_version: pointer.pointer_version + 1,
          updated_at: next.rolled_back_at as string,
        } satisfies ActivePromptReleasePointer);
      }

      await this.appendAudit({
        event_id: `${next.release_id}:${next.lifecycle_state}`,
        event: next.lifecycle_state,
        release_id: next.release_id,
        previous_state: exactRetry ? expectedPreviousState(next) : previous.lifecycle_state,
        pointer_version: (await this.pointer()).pointer_version,
        operator: opts.audit.operator,
        reason: opts.audit.reason,
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

  async resolveForRuntime(assignmentKey?: string): Promise<ActivePromptReleaseManifest | null> {
    const canaryPointer = await this.canaryPointer();
    if (canaryPointer.current_release_id) {
      if (!assignmentKey?.trim()) throw new Error("prompt_release_canary_assignment_key_required");
      const canary = await this.load(canaryPointer.current_release_id);
      if (
        canary?.lifecycle_state !== "canary" ||
        canary.activation_scope.traffic_percent !== canaryPointer.traffic_percent
      ) {
        throw new Error("prompt_release_canary_pointer_is_not_closed");
      }
      const bucket = Number.parseInt(
        createHash("sha256")
          .update(`${canary.release_id}\0${assignmentKey.trim()}`)
          .digest("hex")
          .slice(0, 8),
        16,
      );
      if ((bucket / 0x1_0000_0000) * 100 < canaryPointer.traffic_percent) {
        return canary;
      }
      const baseline = await this.resolveActive();
      if (!baseline) return null;
      if (baseline.release_id !== canary.base_release_id) {
        throw new Error("prompt_release_canary_base_pointer_mismatch");
      }
      return baseline;
    }
    return this.resolveActive();
  }

  private async appendAudit(event: Record<string, unknown>): Promise<void> {
    await mkdir(dirname(this.auditPath()), { recursive: true });
    const existing = await readFile(this.auditPath(), "utf-8").catch((error) => {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return "";
      throw error;
    });
    const eventId = event.event_id;
    const prior = existing
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as Record<string, unknown>)
      .find((row) => row.event_id === eventId);
    if (prior) {
      const { recorded_at: _recordedAt, ...priorEvent } = prior;
      if (JSON.stringify(priorEvent) !== JSON.stringify(event)) {
        throw new Error("prompt_release_audit_event_conflict");
      }
      return;
    }
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

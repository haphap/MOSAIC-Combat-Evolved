import { z } from "zod";

import type {
  ActivePromptReleaseManifest,
  ActivePromptReleaseManifestV4Schema,
} from "../agents/prompts/prompt_release_contract.js";
import { validateKnotGateDReleaseManifest } from "./knot_gate_d_manifest_validation.js";
import { ActivePromptReleaseRegistry } from "./release_registry.js";

function frozen(action: string): Error {
  return new Error(`KNOT evolution frozen until Gate D: ${action}`);
}

function assertGateDManifest(
  manifest: ActivePromptReleaseManifest,
): asserts manifest is ReturnType<typeof ActivePromptReleaseManifestV4Schema.parse> {
  validateKnotGateDReleaseManifest(manifest);
}

export async function assertCurrentKnotTransitionAction(
  action: string,
  registryRoot: string,
): Promise<void> {
  if (!registryRoot.trim()) throw frozen(action);
  try {
    const registry = new ActivePromptReleaseRegistry(registryRoot);
    let manifest = await registry.resolveActive();
    const seen = new Set<string>();
    for (let depth = 0; manifest && depth < 100; depth += 1) {
      if (seen.has(manifest.release_id)) throw new Error("Gate D release lineage cycle");
      seen.add(manifest.release_id);
      if (manifest.schema_version === "active_prompt_release_manifest_v4") {
        if (manifest.lifecycle_state !== "active") {
          throw new Error("Gate D anchor is not active");
        }
        assertGateDManifest(manifest);
        return;
      }
      const parentId = manifest.base_release_id;
      if (!parentId || manifest.previous_approved_release_id !== parentId) {
        throw new Error("Gate D release ancestry is incomplete");
      }
      manifest = await registry.load(parentId);
      if (manifest?.lifecycle_state !== "active") {
        throw new Error("Gate D release ancestor is not active");
      }
    }
  } catch {
    throw frozen(action);
  }
  throw frozen(action);
}

export async function assertKnotGateDBootstrapReleaseTransition(
  action: "START_PROMPT_CANARY" | "ACTIVATE_PROMPT_RELEASE",
  registryRoot: string,
  releaseId: string,
): Promise<void> {
  if (!registryRoot.trim()) throw frozen(action);
  const registry = new ActivePromptReleaseRegistry(registryRoot);
  const manifest = await registry.load(releaseId);
  if (!manifest) throw frozen(action);
  try {
    assertGateDManifest(manifest);
    const expectedState = action === "START_PROMPT_CANARY" ? "staged" : "canary";
    if (manifest.lifecycle_state !== expectedState || !manifest.base_release_id) {
      throw new Error("Gate D bootstrap release state is invalid");
    }
    const pointer = await registry.pointer();
    const base = await registry.load(manifest.base_release_id);
    if (
      pointer.current_release_id !== manifest.base_release_id ||
      base?.lifecycle_state !== "active" ||
      manifest.previous_approved_release_id !== manifest.base_release_id
    ) {
      throw new Error("Gate D bootstrap base release mismatch");
    }
  } catch {
    throw frozen(action);
  }
}

export async function stageKnotGateDBootstrapRelease(opts: {
  registryRoot: string;
  manifest: unknown;
}): Promise<void> {
  if (!opts.registryRoot.trim()) throw new Error("Gate D bootstrap registry root is required");
  const manifest = validateKnotGateDReleaseManifest(opts.manifest);
  if (
    manifest.lifecycle_state !== "staged" ||
    !manifest.base_release_id ||
    manifest.previous_approved_release_id !== manifest.base_release_id
  ) {
    throw new Error("Gate D bootstrap manifest lineage is invalid");
  }
  const registry = new ActivePromptReleaseRegistry(opts.registryRoot);
  const pointer = await registry.pointer();
  const base = await registry.load(manifest.base_release_id);
  if (
    pointer.current_release_id !== manifest.base_release_id ||
    base?.lifecycle_state !== "active"
  ) {
    throw new Error("Gate D bootstrap base release mismatch");
  }
  await registry.stage(manifest);
}

export async function buildKnotGateDBootstrapManifest(opts: {
  registryRoot: string;
  releaseId: string;
  createdAt: string;
  capabilityFullBundle: unknown;
  gateDReceipt: unknown;
}): Promise<ReturnType<typeof ActivePromptReleaseManifestV4Schema.parse>> {
  if (!opts.registryRoot.trim()) throw new Error("Gate D bootstrap registry root is required");
  if (!opts.releaseId.trim()) throw new Error("Gate D bootstrap release id is required");
  const createdAt = z.iso.datetime({ offset: true }).safeParse(opts.createdAt);
  if (!createdAt.success) {
    throw new Error("Gate D bootstrap created_at is invalid");
  }
  const registry = new ActivePromptReleaseRegistry(opts.registryRoot);
  const base = await registry.resolveActive();
  if (base?.schema_version !== "active_prompt_release_manifest_v3") {
    throw new Error("Gate D bootstrap requires one active legacy release");
  }
  if (await registry.load(opts.releaseId)) {
    throw new Error("Gate D bootstrap release id already exists");
  }
  const manifest = {
    ...base,
    schema_version: "active_prompt_release_manifest_v4" as const,
    release_id: opts.releaseId,
    base_release_id: base.release_id,
    lifecycle_state: "staged" as const,
    activation_scope: { ...base.activation_scope, traffic_percent: 0 },
    approved_by: null,
    canary_started_at: null,
    canary_ended_at: null,
    runtime_slo_summary: null,
    runtime_slo_evidence: null,
    previous_approved_release_id: base.release_id,
    created_at: createdAt.data,
    activated_at: null,
    rolled_back_at: null,
    capability_full_bundle: opts.capabilityFullBundle,
    gate_d_receipt: opts.gateDReceipt,
  };
  return validateKnotGateDReleaseManifest(manifest);
}

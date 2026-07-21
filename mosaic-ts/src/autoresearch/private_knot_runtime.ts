import { createHash } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import {
  clearPrivateKnotRuntime,
  installPrivateKnotRuntime,
  type PrivateKnotRuntimeAdapter,
} from "../agents/helpers/private_knot_boundary.js";
import { KNOT_RUNTIME_CONTRACT_REF } from "./knot_contract.js";
import {
  type RuntimeBehaviorBundleRef,
  RuntimeBehaviorBundleRefSchema,
} from "./runtime_behavior_bundle.js";

export interface PrivateRuntimeManifest {
  schema_version: "private_knot_runtime_manifest_v1";
  files: Record<string, { relative_path: string; sha256: string }>;
}

const ADAPTER_LOGICAL_NAME = "typescript_agent_policy_adapter";
const PUBLIC_ASSET_REF_PATH = resolve(
  import.meta.dirname,
  "../../../registry/prompt_checks/private_knot_assets_ref_v1.json",
);

export async function initializePrivateKnotRuntime(opts: {
  required: boolean;
  privateRoot?: string;
  expectedRuntimeBehaviorBundle?: RuntimeBehaviorBundleRef;
}): Promise<boolean> {
  const root = resolvePrivateRoot(opts.privateRoot);
  if (!root) {
    if (opts.required) throw new Error("private_knot_repository_required");
    clearPrivateKnotRuntime();
    return false;
  }

  const canonicalRoot = await realpath(root);
  const manifestRaw = (
    await readConfinedRegularFile(canonicalRoot, "registry/knot/private_runtime_manifest_v1.json")
  ).toString("utf-8");
  if (sha256(manifestRaw) !== KNOT_RUNTIME_CONTRACT_REF.private_runtime_manifest_hash) {
    throw new Error("private_knot_runtime_manifest_hash_mismatch");
  }
  const manifest = parsePrivateRuntimeManifest(JSON.parse(manifestRaw));
  const verifiedFiles = await verifyPrivateKnotRuntimeManifestFiles(canonicalRoot, manifest);
  const entry = manifest.files[ADAPTER_LOGICAL_NAME];
  if (!entry) throw new Error("private_knot_typescript_adapter_missing");
  const adapterPath = resolve(canonicalRoot, entry.relative_path);
  const adapterRaw = verifiedFiles.get(ADAPTER_LOGICAL_NAME);
  if (!adapterRaw) throw new Error("private_knot_typescript_adapter_missing");
  assertPrivateKnotAdapterClosedBundle(adapterRaw.toString("utf-8"));
  const assetRef = JSON.parse(await readFile(PUBLIC_ASSET_REF_PATH, "utf-8")) as {
    domain_knob_catalog: { private_relative_path: string; file_hash: string };
    evaluation_contract: { private_relative_path: string; file_hash: string };
    research_knob_projections: {
      private_manifest_relative_path: string;
      manifest_hash: string;
    };
  };
  await verifyPrivateAsset(
    canonicalRoot,
    assetRef.domain_knob_catalog.private_relative_path,
    assetRef.domain_knob_catalog.file_hash,
  );
  await verifyPrivateAsset(
    canonicalRoot,
    assetRef.evaluation_contract.private_relative_path,
    assetRef.evaluation_contract.file_hash,
  );
  await verifyPrivateAsset(
    canonicalRoot,
    assetRef.research_knob_projections.private_manifest_relative_path,
    assetRef.research_knob_projections.manifest_hash,
  );
  if (opts.expectedRuntimeBehaviorBundle) {
    assertRuntimeBehaviorBundlePrivateClosure({
      bundle: opts.expectedRuntimeBehaviorBundle,
      privateRuntimeManifestHash: sha256(manifestRaw),
      projectionManifestHash: assetRef.research_knob_projections.manifest_hash,
      verifiedFiles,
    });
  }
  const imported = (await import(
    `${pathToFileURL(adapterPath).href}?sha256=${entry.sha256.slice("sha256:".length)}`
  )) as {
    createPrivateKnotRuntimeAdapter?: (input: {
      privateRoot: string;
      privateRuntimeManifestHash: string;
      projectionManifestHash: string;
    }) => Promise<PrivateKnotRuntimeAdapter> | PrivateKnotRuntimeAdapter;
  };
  if (typeof imported.createPrivateKnotRuntimeAdapter !== "function") {
    throw new Error("private_knot_typescript_adapter_factory_missing");
  }
  const adapter = await imported.createPrivateKnotRuntimeAdapter({
    privateRoot: canonicalRoot,
    privateRuntimeManifestHash: KNOT_RUNTIME_CONTRACT_REF.private_runtime_manifest_hash,
    projectionManifestHash: assetRef.research_knob_projections.manifest_hash,
  });
  const descriptor = adapter.describe();
  if (
    descriptor.knot_runtime_contract_manifest_hash !==
      KNOT_RUNTIME_CONTRACT_REF.knot_runtime_contract_manifest_hash ||
    descriptor.private_runtime_manifest_hash !==
      KNOT_RUNTIME_CONTRACT_REF.private_runtime_manifest_hash
  ) {
    throw new Error("private_knot_typescript_adapter_contract_mismatch");
  }
  installPrivateKnotRuntime(adapter);
  return true;
}

export function assertRuntimeBehaviorBundlePrivateClosure(input: {
  bundle: RuntimeBehaviorBundleRef;
  privateRuntimeManifestHash: string;
  projectionManifestHash: string;
  verifiedFiles: ReadonlyMap<string, Buffer>;
}): void {
  const bundle = RuntimeBehaviorBundleRefSchema.parse(input.bundle);
  if (bundle.private_runtime_manifest_hash !== input.privateRuntimeManifestHash) {
    throw new Error("private_knot_runtime_bundle_manifest_mismatch");
  }
  if (bundle.private_policy_hash !== input.projectionManifestHash) {
    throw new Error("private_knot_runtime_bundle_policy_mismatch");
  }
  const registryPins = {
    knot_effect_registry: bundle.effect_registry_hash,
    knot_effect_consumer_registry: bundle.consumer_registry_hash,
    knot_effect_fitness_registry: bundle.fitness_registry_hash,
  } as const;
  for (const [logicalName, expectedHash] of Object.entries(registryPins)) {
    const raw = input.verifiedFiles.get(logicalName);
    if (!raw) throw new Error(`private_knot_runtime_bundle_registry_missing:${logicalName}`);
    const parsed = JSON.parse(raw.toString("utf-8")) as { registry_hash?: unknown };
    if (parsed.registry_hash !== expectedHash) {
      throw new Error(`private_knot_runtime_bundle_registry_mismatch:${logicalName}`);
    }
  }
}

export async function verifyPrivateKnotRuntimeManifestFiles(
  root: string,
  manifest: PrivateRuntimeManifest,
): Promise<Map<string, Buffer>> {
  const canonicalRoot = await realpath(root);
  const verified = new Map<string, Buffer>();
  const paths = new Set<string>();
  for (const [logicalName, entry] of Object.entries(manifest.files)) {
    const path = resolve(canonicalRoot, entry.relative_path);
    assertConfined(canonicalRoot, path);
    if (paths.has(path)) throw new Error("private_knot_runtime_manifest_duplicate_path");
    paths.add(path);
    const raw = await readConfinedRegularFile(canonicalRoot, entry.relative_path);
    if (sha256(raw) !== entry.sha256) {
      throw new Error(`private_knot_runtime_file_hash_mismatch:${logicalName}`);
    }
    verified.set(logicalName, raw);
  }
  return verified;
}

export function assertPrivateKnotAdapterClosedBundle(source: string): void {
  const staticImport = /^\s*import(?:\s+[^"'`]+?\s+from)?\s*["']([^"']+)["'];?\s*$/gm;
  const exportFrom = /^\s*export\s+[^"'`]+?\s+from\s+["']([^"']+)["'];?\s*$/gm;
  for (const expression of [staticImport, exportFrom]) {
    for (const match of source.matchAll(expression)) {
      if (!match[1]?.startsWith("node:")) {
        throw new Error("private_knot_typescript_adapter_external_import");
      }
    }
  }
  const withoutStaticImports = source.replace(staticImport, "").replace(exportFrom, "");
  if (/\bimport\b/.test(withoutStaticImports) || /\brequire\s*\(/.test(source)) {
    throw new Error("private_knot_typescript_adapter_dynamic_import");
  }
}

function resolvePrivateRoot(explicit?: string): string | null {
  const configured =
    explicit?.trim() ||
    process.env.MOSAIC_KNOT_RUNTIME_ROOT?.trim() ||
    process.env.MOSAIC_PROMPTS_REPO?.trim() ||
    process.env.MOSAIC_PRIVATE_PROMPT_REPO?.trim();
  if (!configured) return null;
  const root = resolve(configured);
  return root.endsWith("/prompts/mosaic") ? resolve(root, "../..") : root;
}

function sha256(value: string | Uint8Array): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

async function verifyPrivateAsset(
  root: string,
  relativePath: string,
  expectedHash: string,
): Promise<void> {
  if (sha256(await readConfinedRegularFile(root, relativePath)) !== expectedHash) {
    throw new Error("private_knot_asset_hash_mismatch");
  }
}

function parsePrivateRuntimeManifest(value: unknown): PrivateRuntimeManifest {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("private_knot_runtime_manifest_invalid");
  }
  const manifest = value as Partial<PrivateRuntimeManifest>;
  if (manifest.schema_version !== "private_knot_runtime_manifest_v1") {
    throw new Error("private_knot_runtime_manifest_version_mismatch");
  }
  if (!manifest.files || typeof manifest.files !== "object" || Array.isArray(manifest.files)) {
    throw new Error("private_knot_runtime_manifest_invalid");
  }
  for (const [logicalName, entry] of Object.entries(manifest.files)) {
    if (
      !logicalName.trim() ||
      !entry ||
      typeof entry !== "object" ||
      typeof entry.relative_path !== "string" ||
      !entry.relative_path.trim() ||
      isAbsolute(entry.relative_path) ||
      !/^sha256:[0-9a-f]{64}$/.test(entry.sha256)
    ) {
      throw new Error("private_knot_runtime_manifest_invalid");
    }
  }
  return manifest as PrivateRuntimeManifest;
}

async function readConfinedRegularFile(root: string, relativePath: string): Promise<Buffer> {
  if (!relativePath || isAbsolute(relativePath)) throw new Error("private_knot_path_escape");
  const path = resolve(root, relativePath);
  assertConfined(root, path);
  const rel = relative(root, path);
  let cursor = root;
  for (const component of rel.split(sep)) {
    cursor = resolve(cursor, component);
    const metadata = await lstat(cursor);
    if (metadata.isSymbolicLink()) throw new Error("private_knot_path_symlink");
  }
  const metadata = await lstat(path);
  if (!metadata.isFile()) throw new Error("private_knot_path_not_regular_file");
  const canonicalPath = await realpath(path);
  assertConfined(root, canonicalPath);
  return readFile(canonicalPath);
}

function assertConfined(root: string, path: string): void {
  const rel = relative(root, path);
  if (rel.startsWith("..") || isAbsolute(rel)) throw new Error("private_knot_path_escape");
}

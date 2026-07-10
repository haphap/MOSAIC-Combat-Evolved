import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ActivePromptReleaseRegistry } from "../../autoresearch/release_registry.js";
import { findRepoRoot } from "../../bridge/python.js";
import { getConfiguredPromptSource } from "./cohorts.js";
import {
  type ActivePromptReleaseManifest,
  ActivePromptReleaseManifestSchema,
  type ReleasePromptPair,
  releasePromptPairHash,
} from "./prompt_release_contract.js";
import type { RuntimeAgentStageId } from "./runtime_agent_spec.js";

type AccountMode = ActivePromptReleaseManifest["activation_scope"]["account_mode"];

export interface PromptReleaseLoadContext {
  manifest: ActivePromptReleaseManifest;
  privatePromptRepo?: string;
  bundledRepo?: string;
  accountMode?: AccountMode;
  expectedCatalogHash?: string;
  expectedSchemaHash?: string;
  expectedEvaluationContractHash?: string;
  expectedCodeCommit?: string;
}

export interface ReleasePinnedPromptPair {
  zh: string;
  en: string;
  paths: { zh: string; en: string };
  releaseId: string;
  source: "private" | "bundled_fallback";
  promptCommit: string;
  pairHash: string;
}

const pairCache = new Map<string, ReleasePinnedPromptPair>();

export function clearReleasePromptCache(): void {
  pairCache.clear();
}

export async function buildReleasePromptPairsAtCommit(opts: {
  repo: string;
  commit: string;
  cohort: string;
  specs: ReadonlyArray<{
    agent: string;
    layer: ReleasePromptPair["layer"];
    stages: ReadonlyArray<{ stage: RuntimeAgentStageId }>;
  }>;
}): Promise<ReleasePromptPair[]> {
  return Promise.all(
    opts.specs.map(async (spec) => {
      const base = `prompts/mosaic/${opts.cohort}/${spec.layer}/${spec.agent}`;
      const [zh, en] = await Promise.all([
        gitShow(opts.repo, opts.commit, `${base}.zh.md`),
        gitShow(opts.repo, opts.commit, `${base}.en.md`),
      ]);
      const pair = {
        agent: spec.agent,
        layer: spec.layer,
        cohort: opts.cohort,
        stages: spec.stages.map((stage) => stage.stage),
        zh: { path: `${base}.zh.md`, sha256: sha256(zh) },
        en: { path: `${base}.en.md`, sha256: sha256(en) },
      };
      return { ...pair, pair_hash: releasePromptPairHash(pair) };
    }),
  );
}

export async function promptPairVersionShaAtCommit(opts: {
  repo: string;
  commit: string;
  pair: ReleasePromptPair;
}): Promise<string> {
  const digest = createHash("sha256");
  for (const file of [opts.pair.zh, opts.pair.en].sort((left, right) =>
    left.path.localeCompare(right.path),
  )) {
    const content = await gitShow(opts.repo, opts.commit, file.path);
    digest.update(file.path, "utf-8");
    digest.update("\0");
    digest.update(content);
    digest.update("\0");
  }
  return digest.digest("hex");
}

function sha256(value: Buffer): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function gitShow(repo: string, commit: string, path: string): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    execFile(
      "git",
      ["-C", repo, "show", `${commit}:${path}`],
      { encoding: "buffer", maxBuffer: 4 * 1024 * 1024 },
      (error, stdout) => {
        if (error) reject(error);
        else resolve(stdout);
      },
    );
  });
}

function gitHead(repo: string): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile("git", ["-C", repo, "rev-parse", "HEAD"], { encoding: "utf-8" }, (error, stdout) => {
      if (error) reject(new Error("prompt_release_code_identity_unavailable", { cause: error }));
      else resolve(stdout.trim());
    });
  });
}

function findPair(
  pairs: ReadonlyArray<ReleasePromptPair>,
  agent: string,
  cohort: string,
  stage: RuntimeAgentStageId,
): ReleasePromptPair {
  const matches = pairs.filter(
    (pair) => pair.agent === agent && pair.cohort === cohort && pair.stages.includes(stage),
  );
  if (matches.length !== 1) {
    throw new Error(
      `prompt_release_stage_binding_invalid:${cohort}:${agent}:${stage}:${matches.length}`,
    );
  }
  return matches[0] as ReleasePromptPair;
}

function assertClosure(context: PromptReleaseLoadContext, cohort: string): void {
  const manifest = ActivePromptReleaseManifestSchema.parse(context.manifest);
  if (manifest.lifecycle_state !== "active") {
    throw new Error(`prompt_release_not_active:${manifest.lifecycle_state}`);
  }
  if (manifest.activation_scope.cohort !== cohort) {
    throw new Error("prompt_release_cohort_mismatch");
  }
  if (context.accountMode && manifest.activation_scope.account_mode !== context.accountMode) {
    throw new Error("prompt_release_account_mode_mismatch");
  }
  if (context.expectedCodeCommit && manifest.code_commit !== context.expectedCodeCommit) {
    throw new Error("prompt_release_code_commit_mismatch");
  }
  for (const [label, expected, actual] of [
    ["catalog", context.expectedCatalogHash, manifest.catalog_hash],
    ["schema", context.expectedSchemaHash, manifest.schema_hash],
    [
      "evaluation_contract",
      context.expectedEvaluationContractHash,
      manifest.evaluation_contract_hash,
    ],
  ] as const) {
    if (expected && expected !== actual) throw new Error(`prompt_release_${label}_hash_mismatch`);
  }
}

function verifyFile(buffer: Buffer, expectedHash: string, source: string): string {
  if (sha256(buffer) !== expectedHash) {
    throw new Error(`prompt_release_file_hash_mismatch:${source}`);
  }
  return buffer.toString("utf-8");
}

async function readPairAtCommit(opts: {
  repo: string;
  commit: string;
  pair: ReleasePromptPair;
  source: "private" | "bundled_fallback";
  releaseId: string;
}): Promise<ReleasePinnedPromptPair> {
  const [zhBuffer, enBuffer] = await Promise.all([
    gitShow(opts.repo, opts.commit, opts.pair.zh.path),
    gitShow(opts.repo, opts.commit, opts.pair.en.path),
  ]);
  return {
    zh: verifyFile(zhBuffer, opts.pair.zh.sha256, `${opts.source}:zh`),
    en: verifyFile(enBuffer, opts.pair.en.sha256, `${opts.source}:en`),
    paths: {
      zh: `${opts.source}@${opts.commit}:${opts.pair.zh.path}`,
      en: `${opts.source}@${opts.commit}:${opts.pair.en.path}`,
    },
    releaseId: opts.releaseId,
    source: opts.source,
    promptCommit: opts.commit,
    pairHash: opts.pair.pair_hash,
  };
}

export async function loadReleasePinnedPromptPair(opts: {
  context: PromptReleaseLoadContext;
  agent: string;
  cohort: string;
  stage: RuntimeAgentStageId;
  noCache?: boolean;
}): Promise<ReleasePinnedPromptPair> {
  assertClosure(opts.context, opts.cohort);
  const manifest = opts.context.manifest;
  const pair = findPair(manifest.prompt_pairs, opts.agent, opts.cohort, opts.stage);
  const privateKey = [manifest.release_id, "private", manifest.prompt_commit, pair.pair_hash].join(
    ":",
  );
  if (!opts.noCache) {
    const cached = pairCache.get(privateKey);
    if (cached) return cached;
  }

  if (opts.context.privatePromptRepo) {
    try {
      const loaded = await readPairAtCommit({
        repo: opts.context.privatePromptRepo,
        commit: manifest.prompt_commit,
        pair,
        source: "private",
        releaseId: manifest.release_id,
      });
      if (!opts.noCache) pairCache.set(privateKey, loaded);
      return loaded;
    } catch (error) {
      if ((error as Error).message.startsWith("prompt_release_file_hash_mismatch")) throw error;
    }
  }

  const fallback = manifest.bundled_fallback;
  if (!fallback) throw new Error("prompt_release_private_source_unavailable_without_fallback");
  if (
    (opts.context.expectedCatalogHash &&
      fallback.catalog_hash !== opts.context.expectedCatalogHash) ||
    (opts.context.expectedSchemaHash && fallback.schema_hash !== opts.context.expectedSchemaHash)
  ) {
    throw new Error("prompt_release_bundled_fallback_contract_hash_mismatch");
  }
  const fallbackPair = findPair(fallback.prompt_pairs, opts.agent, opts.cohort, opts.stage);
  const fallbackKey = [
    manifest.release_id,
    "bundled_fallback",
    fallback.prompt_commit,
    fallbackPair.pair_hash,
  ].join(":");
  if (!opts.noCache) {
    const cached = pairCache.get(fallbackKey);
    if (cached) return cached;
  }
  try {
    const loaded = await readPairAtCommit({
      repo: opts.context.bundledRepo ?? findRepoRoot(),
      commit: fallback.prompt_commit,
      pair: fallbackPair,
      source: "bundled_fallback",
      releaseId: manifest.release_id,
    });
    if (!opts.noCache) pairCache.set(fallbackKey, loaded);
    return loaded;
  } catch (error) {
    if ((error as Error).message.startsWith("prompt_release_file_hash_mismatch")) throw error;
    throw new Error("prompt_release_bundled_fallback_unavailable", { cause: error });
  }
}

export interface LocalEvaluationClosure {
  catalog_hash: string;
  schema_hash: string;
  contract_hash: string;
}

export async function loadLocalPromptReleaseClosure(): Promise<LocalEvaluationClosure> {
  const path = join(
    findRepoRoot(),
    "registry",
    "prompt_checks",
    "domain_knob_evaluation_contract_v1.json",
  );
  return JSON.parse(await readFile(path, "utf-8")) as LocalEvaluationClosure;
}

export async function loadPromptReleaseClosureAtCommit(opts: {
  repo: string;
  commit: string;
}): Promise<LocalEvaluationClosure> {
  const value = JSON.parse(
    (
      await gitShow(
        opts.repo,
        opts.commit,
        "registry/prompt_checks/domain_knob_evaluation_contract_v1.json",
      )
    ).toString("utf-8"),
  ) as Partial<LocalEvaluationClosure>;
  const hashes = [value.catalog_hash, value.schema_hash, value.contract_hash];
  if (hashes.some((hash) => typeof hash !== "string" || !/^sha256:[0-9a-f]{64}$/.test(hash))) {
    throw new Error("prompt_release_evaluation_closure_invalid");
  }
  return value as LocalEvaluationClosure;
}

export async function resolveConfiguredPromptReleaseContext(): Promise<PromptReleaseLoadContext | null> {
  const registryRoot = process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT?.trim();
  if (!registryRoot) return null;
  const manifest = await new ActivePromptReleaseRegistry(registryRoot).resolveActive();
  if (!manifest) throw new Error("active_prompt_release_missing");
  const source = getConfiguredPromptSource();
  const accountModeValue = process.env.MOSAIC_PROMPT_ACCOUNT_MODE?.trim();
  if (!accountModeValue) throw new Error("prompt_release_account_mode_required");
  if (!(["paper", "backtest", "live"] as const).includes(accountModeValue as AccountMode)) {
    throw new Error("prompt_release_account_mode_invalid");
  }
  const closure = await loadLocalPromptReleaseClosure();
  const expectedCodeCommit =
    process.env.MOSAIC_CODE_COMMIT?.trim() || (await gitHead(findRepoRoot()));
  return {
    manifest,
    ...(source?.kind === "private-repo" ? { privatePromptRepo: source.repo } : {}),
    bundledRepo: findRepoRoot(),
    accountMode: accountModeValue as AccountMode,
    expectedCatalogHash: closure.catalog_hash,
    expectedSchemaHash: closure.schema_hash,
    expectedEvaluationContractHash: closure.contract_hash,
    expectedCodeCommit,
  };
}

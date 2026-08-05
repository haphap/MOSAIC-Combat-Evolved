/**
 * Loads prompt markdown files for the 28 logical agents (plan v2 §12).
 *
 * Convention:
 *   * Returns the raw markdown text as a UTF-8 string. The caller's prompt
 *     builder (per-agent file) is responsible for formatting and templating.
 *   * For ``language: "Bilingual"``, returns ``zh + "\n\n---\n\n" + en``.
 *   * Caches by ``cohort/agent/language`` key; pass ``{ noCache: true }`` to
 *     bypass the cache (useful in tests + autoresearch mutation flows).
 *   * Missing prompts raise ``PromptNotFoundError`` with both candidate paths
 *     listed for debuggability.
 */

import { readFile } from "node:fs/promises";
import { redactSensitiveText } from "../../security/redaction.js";
import {
  findPrivatePromptsRoot,
  type Language,
  promptPathCandidates,
  resolvePromptPath,
} from "./cohorts.js";
import {
  clearReleasePromptCache,
  loadReleasePinnedPromptPair,
  type PromptReleaseLoadContext,
  type ReleasePinnedPromptPair,
  resolveConfiguredPromptReleaseContext,
} from "./release_prompt_loader.js";
import type { RuntimeAgentStageId } from "./runtime_agent_spec.js";

export type LoaderLanguage = Language | "Bilingual";

/** Thrown when no fallback candidate exists for the requested prompt. */
export class PromptNotFoundError extends Error {
  override readonly name = "PromptNotFoundError";

  constructor(
    public readonly agent: string,
    public readonly cohort: string,
    public readonly language: LoaderLanguage,
    public readonly triedPaths: string[],
    cause?: unknown,
  ) {
    const redactedTriedPaths = triedPaths.map((path) => redactSensitiveText(path));
    super(
      `Prompt not found for agent='${agent}', cohort='${cohort}', language='${language}'. ` +
        `Tried: ${redactedTriedPaths.join(" | ")}`,
      cause !== undefined ? { cause } : undefined,
    );
    this.triedPaths = redactedTriedPaths;
  }
}

interface LoadOptions {
  agent: string;
  cohort: string;
  language: LoaderLanguage;
  promptsRoot?: string;
  privatePromptsRoot?: string;
  noCache?: boolean;
  stage?: RuntimeAgentStageId;
  releaseContext?: PromptReleaseLoadContext | null;
  trafficAssignmentKey?: string;
  onReleaseAssigned?: (assignment: PromptReleaseRuntimeAssignment) => Promise<void> | void;
}

export interface PromptReleaseRuntimeAssignment {
  release_id: string;
  account_mode: "paper" | "backtest" | "live";
  traffic_percent: number;
  stage_snapshot_hash: string;
  lifecycle_state: "staged" | "canary" | "active" | "rolled_back";
}

const cache = new Map<string, string>();
const runtimePairCache = new Map<string, RuntimePromptPairResult>();

function releasePinnedPairCacheIdentity(pair: ReleasePinnedPromptPair): string {
  return JSON.stringify([
    "runtime-v2",
    pair.releaseId,
    pair.source,
    pair.promptCommit,
    pair.pairHash,
    pair.stageSnapshotHash,
    pair.accountMode,
    pair.trafficPercent,
    pair.lifecycleState,
  ]);
}

/** Drop the in-memory prompt cache. Used by tests and after autoresearch
 *  mutation rewrites prompt files on disk. */
export function clearPromptCache(): void {
  cache.clear();
  runtimePairCache.clear();
  clearReleasePromptCache();
}

function inferReleaseStage(agent: string, stage?: RuntimeAgentStageId): RuntimeAgentStageId {
  if (stage) return stage;
  if (["alpha_discovery", "cro", "autonomous_execution", "cio"].includes(agent)) {
    throw new Error(`prompt_release_stage_required:${agent}`);
  }
  return "agent_run";
}

async function releasePinnedPair(
  opts: Pick<
    LoadOptions,
    | "agent"
    | "cohort"
    | "stage"
    | "releaseContext"
    | "noCache"
    | "promptsRoot"
    | "privatePromptsRoot"
    | "trafficAssignmentKey"
    | "onReleaseAssigned"
  >,
): Promise<ReleasePinnedPromptPair | null> {
  const notifyAssignment = async (manifest: PromptReleaseLoadContext["manifest"]) => {
    const stage = inferReleaseStage(opts.agent, opts.stage);
    const stageSnapshotHash = manifest.stage_snapshot_hashes[`${opts.agent}:${stage}`];
    if (!stageSnapshotHash) {
      throw new Error(`prompt_release_stage_snapshot_missing:${opts.agent}:${stage}`);
    }
    await opts.onReleaseAssigned?.({
      release_id: manifest.release_id,
      account_mode: manifest.activation_scope.account_mode,
      traffic_percent: manifest.activation_scope.traffic_percent,
      stage_snapshot_hash: stageSnapshotHash,
      lifecycle_state: manifest.lifecycle_state,
    });
  };
  const context =
    opts.releaseContext === undefined
      ? opts.promptsRoot || opts.privatePromptsRoot
        ? null
        : await resolveConfiguredPromptReleaseContext(opts.trafficAssignmentKey, notifyAssignment)
      : opts.releaseContext;
  if (!context) return null;
  if (opts.releaseContext !== undefined) await notifyAssignment(context.manifest);
  const stage = inferReleaseStage(opts.agent, opts.stage);
  return loadReleasePinnedPromptPair({
    context,
    agent: opts.agent,
    cohort: opts.cohort,
    stage,
    ...(opts.noCache ? { noCache: true } : {}),
  });
}

/** Read one prompt file (no fallback merging here — done by ``loadPrompt``
 *  for the bilingual case). */
async function readSingle(opts: {
  agent: string;
  cohort: string;
  language: Language;
  promptsRoot?: string;
  privatePromptsRoot?: string;
}): Promise<{ text: string; path: string } | { text: null; triedPaths: string[] }> {
  const path = resolvePromptPath(opts);
  if (path === null) {
    return { text: null, triedPaths: promptPathCandidates(opts) };
  }
  try {
    const text = await readFile(path, { encoding: "utf-8" });
    return { text, path };
  } catch (err) {
    return {
      text: null,
      triedPaths: [`${path} (${(err as Error).message})`],
    };
  }
}

/**
 * Load a prompt for one agent at one language, applying the cohort fallback
 * chain. For ``Bilingual`` returns zh + "\n\n---\n\n" + en (Plan §10.2).
 */
export async function loadPrompt(opts: LoadOptions): Promise<string> {
  // The cache key includes the private root path but NOT a file content/mtime
  // fingerprint. That is correct only under the plan's worktree-per-commit model
  // (evaluation/production point the private root at a per-commit worktree, so a
  // different prompt commit ⇒ a different root path). If a long-lived process
  // reuses ONE private root and the checked-out branch/commit changes in place,
  // pass `noCache: true` to avoid a stale read.
  const pinnedPair = await releasePinnedPair(opts);
  const privateRoot =
    opts.privatePromptsRoot ?? (opts.promptsRoot ? "" : (findPrivatePromptsRoot() ?? ""));
  const cacheKey = [
    opts.promptsRoot ?? "",
    privateRoot,
    opts.cohort,
    opts.agent,
    opts.language,
    pinnedPair ? releasePinnedPairCacheIdentity(pinnedPair) : "unreleased",
  ].join("|");
  if (!opts.noCache) {
    const cached = cache.get(cacheKey);
    if (cached !== undefined) {
      return cached;
    }
  }

  if (pinnedPair) {
    const prompt =
      opts.language === "Bilingual"
        ? `${pinnedPair.zh}\n\n---\n\n${pinnedPair.en}`
        : pinnedPair[opts.language];
    if (!opts.noCache) cache.set(cacheKey, prompt);
    return prompt;
  }

  if (opts.language === "Bilingual") {
    const [zh, en] = await Promise.all([
      readSingle({ ...opts, language: "zh" }),
      readSingle({ ...opts, language: "en" }),
    ]);
    if (zh.text === null && en.text === null) {
      throw new PromptNotFoundError(opts.agent, opts.cohort, "Bilingual", [
        ...zh.triedPaths,
        ...en.triedPaths,
      ]);
    }
    // Tolerate one missing leg — emit just the available side. Hard-fail only
    // when both are missing, since that means the agent has no usable prompt
    // at all.
    const merged =
      zh.text !== null && en.text !== null
        ? `${zh.text}\n\n---\n\n${en.text}`
        : (zh.text ?? en.text ?? "");
    if (!opts.noCache) cache.set(cacheKey, merged);
    return merged;
  }

  const single = await readSingle({ ...opts, language: opts.language });
  if (single.text === null) {
    throw new PromptNotFoundError(opts.agent, opts.cohort, opts.language, single.triedPaths);
  }
  if (!opts.noCache) cache.set(cacheKey, single.text);
  return single.text;
}

export interface RuntimePromptPairResult {
  prompt: string;
  paths: { zh: string; en: string };
  bodies: { zh: string; en: string };
  release?: {
    release_id: string;
    source: "private" | "bundled_fallback";
    prompt_commit: string;
    prompt_pair_hash: string;
    stage_snapshot_hash: string;
    account_mode: "paper" | "backtest" | "live";
    traffic_percent: number;
    lifecycle_state: "staged" | "canary" | "active" | "rolled_back";
  };
}

/** Load the exact bilingual pair selected by the ordinary Prompt Release authority. */
export async function loadPromptWithReleaseMetadata(
  opts: Omit<LoadOptions, "language"> & { stage?: RuntimeAgentStageId },
): Promise<RuntimePromptPairResult> {
  const pinnedPair = await releasePinnedPair(opts);
  const cacheKey = [
    opts.promptsRoot ?? "",
    opts.privatePromptsRoot ?? "",
    opts.cohort,
    opts.agent,
    opts.stage ?? "agent_run",
    pinnedPair ? releasePinnedPairCacheIdentity(pinnedPair) : "unreleased",
  ].join("|");
  if (!opts.noCache) {
    const cached = runtimePairCache.get(cacheKey);
    if (cached) return cached;
  }
  let bodies: { zh: string; en: string };
  let paths: { zh: string; en: string };
  if (pinnedPair) {
    bodies = { zh: pinnedPair.zh.trim(), en: pinnedPair.en.trim() };
    paths = pinnedPair.paths;
  } else {
    const [zh, en] = await Promise.all([
      readSingle({ ...opts, language: "zh" }),
      readSingle({ ...opts, language: "en" }),
    ]);
    if (zh.text === null || en.text === null) {
      throw new PromptNotFoundError(opts.agent, opts.cohort, "Bilingual", [
        ...(zh.text === null ? zh.triedPaths : []),
        ...(en.text === null ? en.triedPaths : []),
      ]);
    }
    bodies = { zh: zh.text.trim(), en: en.text.trim() };
    paths = { zh: zh.path, en: en.path };
  }
  const result: RuntimePromptPairResult = {
    prompt: `${bodies.zh}\n\n---\n\n${bodies.en}`,
    bodies,
    paths,
    ...(pinnedPair
      ? {
          release: {
            release_id: pinnedPair.releaseId,
            source: pinnedPair.source,
            prompt_commit: pinnedPair.promptCommit,
            prompt_pair_hash: pinnedPair.pairHash,
            stage_snapshot_hash: pinnedPair.stageSnapshotHash,
            account_mode: pinnedPair.accountMode,
            traffic_percent: pinnedPair.trafficPercent,
            lifecycle_state: pinnedPair.lifecycleState,
          },
        }
      : {}),
  };
  if (!opts.noCache) runtimePairCache.set(cacheKey, result);
  return result;
}

/**
 * Loads prompt markdown files for the 25 agents (Plan §10).
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
import {
  findPrivatePromptsRoot,
  type Language,
  promptPathCandidates,
  resolvePromptPath,
} from "./cohorts.js";

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
    super(
      `Prompt not found for agent='${agent}', cohort='${cohort}', language='${language}'. ` +
        `Tried: ${triedPaths.join(" | ")}`,
      cause !== undefined ? { cause } : undefined,
    );
  }
}

interface LoadOptions {
  agent: string;
  cohort: string;
  language: LoaderLanguage;
  promptsRoot?: string;
  privatePromptsRoot?: string;
  noCache?: boolean;
}

const cache = new Map<string, string>();

/** Drop the in-memory prompt cache. Used by tests and after autoresearch
 *  mutation rewrites prompt files on disk. */
export function clearPromptCache(): void {
  cache.clear();
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
  const privateRoot =
    opts.privatePromptsRoot ?? (opts.promptsRoot ? "" : (findPrivatePromptsRoot() ?? ""));
  const cacheKey = [
    opts.promptsRoot ?? "",
    privateRoot,
    opts.cohort,
    opts.agent,
    opts.language,
  ].join("|");
  if (!opts.noCache) {
    const cached = cache.get(cacheKey);
    if (cached !== undefined) {
      return cached;
    }
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

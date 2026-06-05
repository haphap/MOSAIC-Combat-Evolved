/**
 * Cohort + prompt-path conventions for the 25 agents (Plan §10).
 *
 * Disk layout:
 *   prompts/mosaic/
 *     cohort_default/                 ← baseline; never deleted, fallback target
 *       macro/<agent>.{zh,en}.md
 *       sector/<agent>.{zh,en}.md
 *       superinvestor/<agent>.{zh,en}.md
 *       decision/<agent>.{zh,en}.md
 *     cohort_<name>/                  ← one per training cohort (PRISM, Phase 5)
 *       macro/<agent>.{zh,en}.md
 *       ...
 *
 * Resolution rule: bundled project prompts are the default. When an external
 * prompt repo/root is explicitly configured, its cohort/default files are
 * preferred, with bundled prompts remaining as fallback. For non-default
 * cohorts, ``cohort_default`` is the cohort fallback inside each root.
 */

import { existsSync } from "node:fs";
import { join } from "node:path";
import { findRepoRoot } from "../../bridge/python.js";

export type Layer = "macro" | "sector" | "superinvestor" | "decision";
export type Language = "zh" | "en";

/** Agent IDs grouped by their canonical layer (Plan §5). */
export const AGENTS_BY_LAYER: Record<Layer, ReadonlyArray<string>> = {
  macro: [
    "central_bank",
    "geopolitical",
    "china",
    "dollar",
    "yield_curve",
    "commodities",
    "volatility",
    "emerging_markets",
    "news_sentiment",
    "institutional_flow",
  ],
  sector: [
    "semiconductor",
    "energy",
    "biotech",
    "consumer",
    "industrials",
    "financials",
    "relationship_mapper",
  ],
  superinvestor: ["druckenmiller", "aschenbrenner", "baker", "ackman"],
  decision: ["cro", "alpha_discovery", "autonomous_execution", "cio"],
};

/** Inverse map: agent_id → its canonical layer. */
export const LAYER_BY_AGENT: Record<string, Layer> = (() => {
  const out: Record<string, Layer> = {};
  for (const [layer, agents] of Object.entries(AGENTS_BY_LAYER)) {
    for (const agent of agents) {
      out[agent] = layer as Layer;
    }
  }
  return out;
})();

/** All 25 agent IDs in a flat list (display order = layer order). */
export const ALL_AGENTS: ReadonlyArray<string> = [
  ...AGENTS_BY_LAYER.macro,
  ...AGENTS_BY_LAYER.sector,
  ...AGENTS_BY_LAYER.superinvestor,
  ...AGENTS_BY_LAYER.decision,
];

export const DEFAULT_COHORT = "cohort_default";

export type ConfiguredPromptSource =
  | { kind: "private-root"; root: string }
  | { kind: "private-repo"; repo: string; root: string };

/** Find the bundled ``<repoRoot>/prompts/mosaic/`` fallback prompt root. */
export function findBundledPromptsRoot(): string {
  return join(findRepoRoot(), "prompts", "mosaic");
}

export function getConfiguredPromptSource(): ConfiguredPromptSource | null {
  const explicitRoot = process.env.MOSAIC_PROMPTS_ROOT?.trim();
  if (explicitRoot) return { kind: "private-root", root: explicitRoot };

  const repo =
    process.env.MOSAIC_PROMPTS_REPO?.trim() ?? process.env.MOSAIC_PRIVATE_PROMPT_REPO?.trim();
  if (repo) return { kind: "private-repo", repo, root: join(repo, "prompts", "mosaic") };

  return null;
}

/** Find the configured private/external prompt root, if explicitly set. */
export function findConfiguredPrivatePromptsRoot(): string | undefined {
  return getConfiguredPromptSource()?.root;
}

export function formatPromptSourceLabel(source = getConfiguredPromptSource()): string {
  if (!source) return "bundled";
  if (source.kind === "private-root") return `private-root:${source.root}`;
  return `private-repo:${source.repo}`;
}

/** Find the default prompt root for all cohorts: the bundled project prompts. */
export function findPromptsRoot(): string {
  return findBundledPromptsRoot();
}

/** Find ``<privatePromptRepo>/prompts/mosaic/`` when configured. */
export function findPrivatePromptsRoot(): string | undefined {
  return findConfiguredPrivatePromptsRoot();
}

/** Path within a cohort to one agent's prompt file. */
export function promptPath(opts: {
  agent: string;
  layer?: Layer;
  cohort: string;
  language: Language;
  promptsRoot?: string;
}): string {
  const layer = opts.layer ?? LAYER_BY_AGENT[opts.agent];
  if (!layer) {
    throw new Error(
      `Unknown agent '${opts.agent}'. Known: ${ALL_AGENTS.slice(0, 5).join(", ")}, ...`,
    );
  }
  const root = opts.promptsRoot ?? findPromptsRoot();
  return join(root, opts.cohort, layer, `${opts.agent}.${opts.language}.md`);
}

/**
 * Resolution order for a single (agent, language) request:
 *   1. configured private root: ``<cohort>/<layer>/<agent>.<language>.md``
 *   2. configured private root: ``cohort_default/<layer>/<agent>.<language>.md``
 *   3. bundled root: ``<cohort>/<layer>/<agent>.<language>.md``
 *   4. bundled root: ``cohort_default/<layer>/<agent>.<language>.md``
 *
 * Returns the first candidate that exists on disk, or null if neither does.
 */
export function resolvePromptPath(opts: {
  agent: string;
  cohort: string;
  language: Language;
  promptsRoot?: string;
  privatePromptsRoot?: string;
}): string | null {
  for (const p of promptPathCandidates(opts)) {
    if (existsSync(p)) {
      return p;
    }
  }
  return null;
}

export function promptPathCandidates(opts: {
  agent: string;
  cohort: string;
  language: Language;
  promptsRoot?: string;
  privatePromptsRoot?: string;
}): string[] {
  const layer = LAYER_BY_AGENT[opts.agent];
  if (!layer) throw new Error(`Unknown agent '${opts.agent}'`);

  const candidates = [opts.cohort];
  if (opts.cohort !== DEFAULT_COHORT) {
    candidates.push(DEFAULT_COHORT);
  }
  const baselineRoot = opts.promptsRoot ?? findPromptsRoot();
  const privateRoot =
    opts.privatePromptsRoot ?? (opts.promptsRoot ? undefined : findPrivatePromptsRoot());
  const roots: string[] = [];
  for (const root of [privateRoot, baselineRoot]) {
    if (root && !roots.includes(root)) roots.push(root);
  }
  const paths: string[] = [];
  for (const root of roots) {
    for (const cohort of candidates) {
      paths.push(promptPath({ ...opts, cohort, layer, promptsRoot: root }));
    }
  }
  return paths;
}

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
 * Resolution rule: when an agent prompt is requested for a non-default cohort,
 * fall back to ``cohort_default`` if the cohort-specific file is missing.
 * This lets newly-created cohorts inherit the baseline until autoresearch
 * (Phase 4) overwrites individual agent prompts.
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

/** Find ``<repoRoot>/prompts/mosaic/`` — the prompt root for all cohorts. */
export function findPromptsRoot(): string {
  return join(findRepoRoot(), "prompts", "mosaic");
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
 *   1. ``<cohort>/<layer>/<agent>.<language>.md``    (cohort-specific)
 *   2. ``cohort_default/<layer>/<agent>.<language>.md`` (baseline fallback)
 *
 * Returns the first candidate that exists on disk, or null if neither does.
 */
export function resolvePromptPath(opts: {
  agent: string;
  cohort: string;
  language: Language;
  promptsRoot?: string;
}): string | null {
  const layer = LAYER_BY_AGENT[opts.agent];
  if (!layer) {
    throw new Error(`Unknown agent '${opts.agent}'`);
  }
  const candidates = [opts.cohort];
  if (opts.cohort !== DEFAULT_COHORT) {
    candidates.push(DEFAULT_COHORT);
  }
  for (const cohort of candidates) {
    const p = promptPath({ ...opts, cohort, layer });
    if (existsSync(p)) {
      return p;
    }
  }
  return null;
}

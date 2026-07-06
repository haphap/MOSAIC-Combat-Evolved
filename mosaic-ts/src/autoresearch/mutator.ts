/**
 * Prompt mutation generator (Plan §11.5 4B).
 *
 * Given a (cohort, agent), the mutator:
 *   1. loads the agent's current zh + en prompt (cohort → cohort_default
 *      fallback, ``noCache`` so a fresh rewrite always reads disk);
 *   2. fetches the agent's recent skill (scorecard) + Darwinian weight to feed
 *      the LLM "what to improve";
 *   3. asks an LLM (English meta-prompt — Plan §11.5 4B decision: reasoning in
 *      English, content stays per-language) for a *focused* rewrite producing
 *      ``{zh_prompt, en_prompt, modification_summary, rationale}`` in one call
 *      so the two languages stay semantically in sync;
 *   4. enforces guardrails via {@link assertPromptInvariants} (structure kept,
 *      length within ±40%, must be a real change).
 *
 * The mutator only *proposes*: it never writes to disk or touches git. The
 * orchestrator (4E) persists the result via ``prompts.write`` on a branch.
 */

import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { z } from "zod";
import { bindStructured } from "../agents/helpers/structured_output.js";
import { ALL_MACRO_AGENTS } from "../agents/macro/_aggregator.js";
import { loadPrompt } from "../agents/prompts/loader.js";
import type { BridgeApi } from "../bridge/types.js";

/** Layer-1 macro agents use their own skill metric (no recommendation alpha). */
const MACRO_AGENT_SET: ReadonlySet<string> = new Set(ALL_MACRO_AGENTS);

/** Max allowed length swing for a rewrite (Plan §11.5 4B decision #5). */
export const MAX_LENGTH_DELTA = 0.4;

export const PROMPT_CONTRACT_REQUIRED_SECTION_CATEGORIES = [
  "role_boundary",
  "required_inputs_tools",
  "rke_prior_policy",
  "workflow",
  "output_schema",
  "audit_footprint_contract",
  "privacy_boundary",
  "confidence_policy",
  "refusal_no_action",
  "autoresearch_evolution_contract",
] as const;

const REQUIRED_SECTIONS: ReadonlyArray<{
  category: (typeof PROMPT_CONTRACT_REQUIRED_SECTION_CATEGORIES)[number];
  variants: ReadonlyArray<string>;
}> = [
  { category: "role_boundary", variants: ["## Role boundary", "## 角色边界"] },
  {
    category: "required_inputs_tools",
    variants: ["## Required inputs/tools", "## Required inputs", "## 必需输入与工具"],
  },
  { category: "rke_prior_policy", variants: ["## RKE prior policy", "## RKE 先验政策"] },
  { category: "workflow", variants: ["## Workflow", "## 工作流程"] },
  { category: "output_schema", variants: ["## Output schema", "## 输出 schema"] },
  {
    category: "audit_footprint_contract",
    variants: [
      "## Audit and footprint contract",
      "## Audit/footprint contract",
      "## 审计与足迹契约",
    ],
  },
  { category: "privacy_boundary", variants: ["## Privacy boundary", "## 隐私边界"] },
  { category: "confidence_policy", variants: ["## Confidence policy", "## 置信度政策"] },
  {
    category: "refusal_no_action",
    variants: ["## Refusal and no-action behavior", "## Refusal/no-action", "## 拒绝与无操作行为"],
  },
  {
    category: "autoresearch_evolution_contract",
    variants: ["## Autoresearch evolution contract", "## 自研究演化契约"],
  },
];

const PRIVACY_TOKENS = [
  "report prose",
  "source spans",
  "prompt body",
  "local paths",
  "urls",
  "reviewer text",
  "licensed metadata",
] as const;

const IMMUTABLE_GUARDRAILS = [
  "role boundary",
  "output schema",
  "required tools",
  "current-data gate",
  "rke-prior policy",
  "privacy boundary",
  "audit/footprint contract",
  "shadow/promotion safety policy",
] as const;

export const MutationSchema = z.object({
  zh_prompt: z.string().min(1),
  en_prompt: z.string().min(1),
  modification_summary: z.string().min(1),
  rationale: z.string().min(1),
});
export type Mutation = z.infer<typeof MutationSchema>;

export class PromptInvariantError extends Error {
  override readonly name = "PromptInvariantError";
}

/** Normalize for the no-op check: collapse whitespace, trim. */
function normalize(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/**
 * Guardrails on one rewritten language variant. Throws
 * {@link PromptInvariantError} on any violation (Plan §11.5 4B decision #5).
 */
export function assertPromptInvariants(original: string, rewritten: string): void {
  const rewrittenLower = rewritten.toLowerCase();

  // 1. structure: every E0.5 required section must be present.
  for (const section of REQUIRED_SECTIONS) {
    if (!section.variants.some((h) => rewritten.includes(h))) {
      throw new PromptInvariantError(`rewrite dropped required section '${section.category}'`);
    }
  }

  // 2. schema field names: every key inside the original ```json block must
  //    still appear (renaming a field breaks the agent's structured output).
  for (const field of extractSchemaFields(original)) {
    if (!rewritten.includes(field)) {
      throw new PromptInvariantError(`rewrite dropped schema field '${field}'`);
    }
  }

  // 3. length cap.
  const lo = original.length * (1 - MAX_LENGTH_DELTA);
  const hi = original.length * (1 + MAX_LENGTH_DELTA);
  if (rewritten.length < lo || rewritten.length > hi) {
    throw new PromptInvariantError(
      `rewrite length ${rewritten.length} outside ±${MAX_LENGTH_DELTA * 100}% of ${original.length}`,
    );
  }

  // 4. must be a real change.
  if (normalize(original) === normalize(rewritten)) {
    throw new PromptInvariantError("rewrite is a no-op (identical after normalization)");
  }

  if (
    !(
      rewrittenLower.includes("research prior") &&
      (rewrittenLower.includes("not current data") ||
        rewrittenLower.includes("cannot replace current")) &&
      (rewrittenLower.includes("cannot directly create trades") ||
        rewrittenLower.includes("no trade without current data confirmation"))
    )
  ) {
    throw new PromptInvariantError("rewrite weakened RKE prior/current-data separation");
  }
  if (
    rewrittenLower.includes("rke prior is current data") ||
    rewrittenLower.includes("rke context is current data") ||
    rewrittenLower.includes("rke prior can directly create trades")
  ) {
    throw new PromptInvariantError("rewrite treats RKE prior as current data or trade trigger");
  }
  if (
    !rewrittenLower.includes("get_rke_research_context") ||
    !["missing tool", "tool unavailable", "fallback"].some((token) =>
      rewrittenLower.includes(token),
    ) ||
    !["confidence cap", "caps confidence"].some((token) => rewrittenLower.includes(token))
  ) {
    throw new PromptInvariantError("rewrite dropped required tool/fallback/confidence-cap policy");
  }
  for (const token of PRIVACY_TOKENS) {
    if (!rewrittenLower.includes(token)) {
      throw new PromptInvariantError(`rewrite dropped privacy token '${token}'`);
    }
  }
  if (!rewrittenLower.includes("no-action")) {
    throw new PromptInvariantError("rewrite dropped refusal/no-action behavior");
  }
  if (!rewrittenLower.includes("mutable") || !rewrittenLower.includes("immutable")) {
    throw new PromptInvariantError("rewrite blurred mutable/immutable boundaries");
  }
  for (const token of IMMUTABLE_GUARDRAILS) {
    if (!rewrittenLower.includes(token)) {
      throw new PromptInvariantError(`rewrite dropped immutable guardrail '${token}'`);
    }
  }
}

/** Pull JSON field keys out of the first ```json fenced block. */
function extractSchemaFields(prompt: string): string[] {
  const m = prompt.match(/```json\s*([\s\S]*?)```/);
  if (!m || m[1] === undefined) return [];
  const block = m[1];
  const keys = new Set<string>();
  for (const km of block.matchAll(/"([A-Za-z_][A-Za-z0-9_]*)"\s*:/g)) {
    keys.add(`"${km[1]}"`);
  }
  return [...keys];
}

const META_SYSTEM = [
  "You are a prompt engineer improving the system prompt of one analyst agent",
  "in a Chinese A-share multi-agent trading system. You will be given the",
  "agent's current Chinese (zh) and English (en) prompts plus its recent",
  "performance. Propose ONE focused improvement, rewriting BOTH languages so",
  "they stay semantically identical.",
  "",
  "Hard rules:",
  "- Keep every E0.5 section: role boundary, required inputs/tools, RKE prior",
  "  policy, workflow, output schema, audit/footprint contract, privacy",
  "  boundary, confidence policy, refusal/no-action behavior, and autoresearch",
  "  evolution contract.",
  "- Do not change the output schema's field names or structure.",
  "- Preserve required tools, missing-tool fallback, confidence caps,",
  "  current-data gate, RKE-prior-is-not-current-data rule, privacy/no-source",
  "  prose rule, and mutable versus immutable autoresearch boundaries.",
  "- Keep length within ±40% of the original; this is a focused edit, not a",
  "  rewrite from scratch.",
  "- zh_prompt must be Chinese, en_prompt must be English, same meaning.",
  "Return modification_summary (one line) and rationale.",
].join("\n");

export interface MutatorDeps {
  llm: BaseChatModel;
  api: BridgeApi;
}

export interface MutateOptions {
  cohort: string;
  agent: string;
  deps: MutatorDeps;
  /** Restrict skill lookup to rows since this date (YYYY-MM-DD). */
  since?: string;
  /** Override the prompts root (tests; defaults to the repo's prompts/mosaic). */
  promptsRoot?: string;
  /**
   * Deterministic canned mutation instead of an LLM call (Plan §11.5 4F):
   * appends a marker line to zh+en so ``--fake-llm`` smoke runs are
   * repeatable and zero-cost. The marker keeps every required section /
   * schema field intact, so it passes ``assertPromptInvariants``.
   */
  fakeLlm?: boolean;
}

/** Deterministic rewrite for ``--fake-llm`` mode (Plan §11.5 4F decision). */
function cannedMutation(zh: string, en: string): Mutation {
  const marker = "autoresearch fake-llm marker";
  return {
    zh_prompt: `${zh.replace(/\s+$/, "")}\n\n<!-- ${marker} -->\n`,
    en_prompt: `${en.replace(/\s+$/, "")}\n\n<!-- ${marker} -->\n`,
    modification_summary: "fake-llm: append deterministic marker",
    rationale: "fake-llm smoke mutation (no real LLM call)",
  };
}

/**
 * Generate a synchronized zh/en prompt rewrite for one agent. Returns the
 * validated {@link Mutation}; throws {@link PromptInvariantError} if the LLM's
 * rewrite violates a guardrail, or a plain Error if the provider can't do
 * structured output.
 */
export async function mutate(opts: MutateOptions): Promise<Mutation> {
  const { cohort, agent, deps, since, promptsRoot, fakeLlm } = opts;

  const rootOpt = promptsRoot !== undefined ? { promptsRoot } : {};
  const [zh, en] = await Promise.all([
    loadPrompt({ agent, cohort, language: "zh", noCache: true, ...rootOpt }),
    loadPrompt({ agent, cohort, language: "en", noCache: true, ...rootOpt }),
  ]);

  if (fakeLlm) {
    const mutation = cannedMutation(zh, en);
    assertPromptInvariants(zh, mutation.zh_prompt);
    assertPromptInvariants(en, mutation.en_prompt);
    assertPromptPairInvariants(mutation.zh_prompt, mutation.en_prompt);
    return mutation;
  }

  const perf = await describePerformance(deps.api, cohort, agent, since);

  const userText = [
    `Agent: ${agent}  Cohort: ${cohort}`,
    `Recent performance: ${perf}`,
    "",
    "=== Current zh prompt ===",
    zh,
    "",
    "=== Current en prompt ===",
    en,
  ].join("\n");

  const bound = bindStructured(deps.llm, MutationSchema, `mutator:${agent}`);
  if (bound === null) {
    throw new Error(`mutator:${agent}: provider does not support structured output`);
  }
  const raw = await bound.invoke([new SystemMessage(META_SYSTEM), new HumanMessage(userText)]);
  const mutation = MutationSchema.parse(raw);

  assertPromptInvariants(zh, mutation.zh_prompt);
  assertPromptInvariants(en, mutation.en_prompt);
  assertPromptPairInvariants(mutation.zh_prompt, mutation.en_prompt);
  return mutation;
}

function sectionPresence(prompt: string): Record<string, boolean> {
  return Object.fromEntries(
    REQUIRED_SECTIONS.map((section) => [
      section.category,
      section.variants.some((header) => prompt.includes(header)),
    ]),
  );
}

export function assertPromptPairInvariants(zhPrompt: string, enPrompt: string): void {
  const zh = sectionPresence(zhPrompt);
  const en = sectionPresence(enPrompt);
  for (const category of PROMPT_CONTRACT_REQUIRED_SECTION_CATEGORIES) {
    if (zh[category] !== en[category]) {
      throw new PromptInvariantError(`rewrite desynchronized section '${category}'`);
    }
  }
}

/** Build a one-line performance blurb; degrade gracefully on cold start. */
async function describePerformance(
  api: BridgeApi,
  cohort: string,
  agent: string,
  since?: string,
): Promise<string> {
  // Macro (Layer 1) agents have no recommendation alpha — show macro skill so
  // the LLM sees its own error type, not a misleading "no recent data".
  if (MACRO_AGENT_SET.has(agent)) {
    try {
      const { rows } = await api.scorecardListMacroSkill(cohort, since);
      const s = rows.find((r) => r.agent === agent);
      if (!s) {
        return "no recent macro data (cold start) — make a conservative clarity-focused edit";
      }
      const pct = (x: number | null) => (x == null ? "n/a" : `${(x * 100).toFixed(0)}%`);
      return [
        `raw_macro_score_5d=${s.mean_raw_macro_score_5d?.toFixed(4) ?? "n/a"}`,
        `hit_rate_5d=${pct(s.hit_rate_5d)}`,
        `label=${s.latest_label_type ?? "n/a"}`,
        `primary=${pct(s.primary_label_rate)}`,
        `fallback=${pct(s.fallback_label_rate)}`,
        `missing=${pct(s.missing_label_rate)}`,
        `n_obs=${s.n_obs}`,
        `effective_macro_score_5d=${s.mean_effective_macro_score_5d ?? "null"}`,
        `influence_equal=${s.mean_influence_weight_equal ?? "null"}`,
      ].join(", ");
    } catch {
      return "macro performance unavailable — make a conservative clarity-focused edit";
    }
  }

  try {
    const [{ rows }, { weights }] = await Promise.all([
      api.scorecardListSkill(cohort, since),
      api.darwinianGetWeights(cohort),
    ]);
    const skill = rows.find((r) => r.agent === agent);
    const w = weights[agent];
    if (!skill && !w) {
      return "no recent data (cold start) — make a conservative clarity-focused edit";
    }
    const parts: string[] = [];
    if (skill) {
      parts.push(
        `mean_alpha_5d=${skill.mean_alpha_5d.toFixed(4)}`,
        `sharpe_window=${skill.sharpe_window ?? "n/a"}`,
        `n_obs=${skill.n_obs}`,
      );
    }
    if (w) {
      parts.push(`weight=${w.weight.toFixed(2)}`, `sharpe_30=${w.sharpe_30 ?? "n/a"}`);
    }
    return parts.join(", ");
  } catch {
    return "performance unavailable — make a conservative clarity-focused edit";
  }
}

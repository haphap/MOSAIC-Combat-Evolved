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
import { loadPrompt } from "../agents/prompts/loader.js";
import type { BridgeApi } from "../bridge/types.js";

/** Max allowed length swing for a rewrite (Plan §11.5 4B decision #5). */
export const MAX_LENGTH_DELTA = 0.4;

/** Section headers that must survive a rewrite (zh + en variants). A prompt
 *  without its output-schema / workflow sections breaks structured parsing. */
const REQUIRED_SECTIONS: ReadonlyArray<ReadonlyArray<string>> = [
  ["## 输出 schema", "## Output schema"],
  ["## 工作流程", "## Workflow"],
];

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
  // 1. structure: every required section (in whichever language it appeared)
  //    must still be present.
  for (const variants of REQUIRED_SECTIONS) {
    const wasPresent = variants.some((h) => original.includes(h));
    if (wasPresent && !variants.some((h) => rewritten.includes(h))) {
      throw new PromptInvariantError(
        `rewrite dropped a required section (one of: ${variants.join(" / ")})`,
      );
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
  "- Keep every section header (e.g. '## 输出 schema' / '## Output schema',",
  "  '## 工作流程' / '## Workflow') and every JSON schema field name exactly.",
  "- Do not change the output schema's field names or structure.",
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
}

/**
 * Generate a synchronized zh/en prompt rewrite for one agent. Returns the
 * validated {@link Mutation}; throws {@link PromptInvariantError} if the LLM's
 * rewrite violates a guardrail, or a plain Error if the provider can't do
 * structured output.
 */
export async function mutate(opts: MutateOptions): Promise<Mutation> {
  const { cohort, agent, deps, since, promptsRoot } = opts;

  const rootOpt = promptsRoot !== undefined ? { promptsRoot } : {};
  const [zh, en] = await Promise.all([
    loadPrompt({ agent, cohort, language: "zh", noCache: true, ...rootOpt }),
    loadPrompt({ agent, cohort, language: "en", noCache: true, ...rootOpt }),
  ]);

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
  return mutation;
}

/** Build a one-line performance blurb; degrade gracefully on cold start. */
async function describePerformance(
  api: BridgeApi,
  cohort: string,
  agent: string,
  since?: string,
): Promise<string> {
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

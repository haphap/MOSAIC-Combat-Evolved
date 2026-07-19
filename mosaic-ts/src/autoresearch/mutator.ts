/** Public prompt-behavior rewriter; private KNOT policy mutation lives elsewhere. */

import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { z } from "zod";
import { bindStructured } from "../agents/helpers/structured_output.js";
import { MACRO_AGENT_IDS } from "../agents/macro/_contracts.js";
import {
  COHORT_BEHAVIOR_START,
  extractCohortBehavior,
  immutablePromptContractText,
  replaceCohortBehavior,
} from "../agents/prompts/cohort_behavior.js";
import { loadPrompt } from "../agents/prompts/loader.js";
import type { BridgeApi } from "../bridge/types.js";

const MACRO_AGENT_SET: ReadonlySet<string> = new Set(MACRO_AGENT_IDS);

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
  { category: "role_boundary", variants: ["## role boundary", "## 角色边界"] },
  {
    category: "required_inputs_tools",
    variants: ["## required inputs/tools", "## required inputs", "## 必需输入与工具"],
  },
  { category: "rke_prior_policy", variants: ["## rke prior policy", "## rke 先验策略"] },
  { category: "workflow", variants: ["## workflow", "## 工作流程"] },
  { category: "output_schema", variants: ["## output schema", "## 输出 schema", "## 输出结构"] },
  {
    category: "audit_footprint_contract",
    variants: [
      "## audit and footprint contract",
      "## audit/footprint contract",
      "## 审计与足迹契约",
      "## 审计/足迹契约",
    ],
  },
  { category: "privacy_boundary", variants: ["## privacy boundary", "## 隐私边界"] },
  { category: "confidence_policy", variants: ["## confidence policy", "## 置信度策略"] },
  {
    category: "refusal_no_action",
    variants: [
      "## refusal and no-action behavior",
      "## refusal and no-action",
      "## refusal/no-action",
      "## 拒绝与 no-action",
      "## 拒绝与不行动",
    ],
  },
  {
    category: "autoresearch_evolution_contract",
    variants: [
      "## autoresearch evolution contract",
      "## autoresearch 演化契约",
      "## 自动研究演化契约",
    ],
  },
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

export function assertPromptInvariants(original: string, rewritten: string): void {
  if (original.includes(COHORT_BEHAVIOR_START)) {
    assertV2PromptBehaviorInvariants(original, rewritten);
    return;
  }
  const rewrittenLower = rewritten.toLowerCase();
  for (const section of REQUIRED_SECTIONS) {
    if (!section.variants.some((header) => rewrittenLower.includes(header))) {
      throw new PromptInvariantError(`rewrite dropped required section '${section.category}'`);
    }
  }
  for (const field of extractSchemaFields(original)) {
    if (!rewritten.includes(field)) {
      throw new PromptInvariantError(`rewrite dropped schema field '${field}'`);
    }
  }
  assertLengthAndChange(original, rewritten);
}

function assertV2PromptBehaviorInvariants(original: string, rewritten: string): void {
  let originalBehavior: string;
  let rewrittenBehavior: string;
  try {
    originalBehavior = extractCohortBehavior(original);
    rewrittenBehavior = extractCohortBehavior(rewritten);
  } catch (error) {
    throw new PromptInvariantError((error as Error).message);
  }
  if (immutablePromptContractText(original) !== immutablePromptContractText(rewritten)) {
    throw new PromptInvariantError("rewrite changed the immutable prompt contract block");
  }
  if (normalize(originalBehavior) === normalize(rewrittenBehavior)) {
    throw new PromptInvariantError("rewrite is a no-op (cohort behavior did not change)");
  }
  assertLength(original, rewritten);
}

function assertLengthAndChange(original: string, rewritten: string): void {
  assertLength(original, rewritten);
  if (normalize(original) === normalize(rewritten)) {
    throw new PromptInvariantError("rewrite is a no-op (identical after normalization)");
  }
}

function assertLength(original: string, rewritten: string): void {
  const minimum = original.length * (1 - MAX_LENGTH_DELTA);
  const maximum = original.length * (1 + MAX_LENGTH_DELTA);
  if (rewritten.length < minimum || rewritten.length > maximum) {
    throw new PromptInvariantError(
      `rewrite length ${rewritten.length} outside ±${MAX_LENGTH_DELTA * 100}% of ${original.length}`,
    );
  }
}

function normalize(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function extractSchemaFields(prompt: string): string[] {
  const match = prompt.match(/```json\s*([\s\S]*?)```/);
  if (!match?.[1]) return [];
  const keys = new Set<string>();
  for (const key of match[1].matchAll(/"([A-Za-z_][A-Za-z0-9_]*)"\s*:/g)) {
    keys.add(`"${key[1]}"`);
  }
  return [...keys];
}

const META_SYSTEM = [
  "You improve one analyst prompt in a Chinese A-share multi-agent research system.",
  "Change only text inside the cohort-behavior markers; every byte outside is immutable.",
  "Improve reasoning order, counter-evidence checks, or expression strategy only.",
  "Do not mention private runtime state, parameters, scoring, scheduling, tools, schemas,",
  "endpoints, data-series catalogs, or implementation details.",
  "Keep length within ±40%; zh_prompt must be Chinese and en_prompt English with the same meaning.",
  "Return modification_summary and rationale.",
].join("\n");

export interface MutatorDeps {
  llm: BaseChatModel;
  api: BridgeApi;
}

export interface MutateOptions {
  cohort: string;
  agent: string;
  deps: MutatorDeps;
  since?: string;
  promptsRoot?: string;
  fakeLlm?: boolean;
}

function cannedMutation(zh: string, en: string): Mutation {
  if (!zh.includes(COHORT_BEHAVIOR_START) || !en.includes(COHORT_BEHAVIOR_START)) {
    const marker = "autoresearch fake-llm marker";
    return {
      zh_prompt: `${zh.replace(/\s+$/, "")}\n\n<!-- ${marker} -->\n`,
      en_prompt: `${en.replace(/\s+$/, "")}\n\n<!-- ${marker} -->\n`,
      modification_summary: "fake-llm: append deterministic marker",
      rationale: "fake-llm smoke mutation",
    };
  }
  return {
    zh_prompt: replaceCohortBehavior(
      zh,
      `${extractCohortBehavior(zh)} 先检查最强反证，再形成结论。`,
    ),
    en_prompt: replaceCohortBehavior(
      en,
      `${extractCohortBehavior(en)} Test the strongest counter-evidence before concluding.`,
    ),
    modification_summary: "fake-llm: add deterministic counter-evidence ordering",
    rationale: "fake-llm smoke mutation",
  };
}

export async function mutate(opts: MutateOptions): Promise<Mutation> {
  const root = opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {};
  const [zh, en] = await Promise.all([
    loadPrompt({ agent: opts.agent, cohort: opts.cohort, language: "zh", noCache: true, ...root }),
    loadPrompt({ agent: opts.agent, cohort: opts.cohort, language: "en", noCache: true, ...root }),
  ]);
  const mutation = opts.fakeLlm
    ? cannedMutation(zh, en)
    : await invokeMutationModel(opts, zh, en, await describePerformance(opts));
  assertPromptInvariants(zh, mutation.zh_prompt);
  assertPromptInvariants(en, mutation.en_prompt);
  assertPromptPairInvariants(mutation.zh_prompt, mutation.en_prompt);
  return mutation;
}

async function invokeMutationModel(
  opts: MutateOptions,
  zh: string,
  en: string,
  performance: string,
): Promise<Mutation> {
  const bound = bindStructured(opts.deps.llm, MutationSchema, `mutator:${opts.agent}`);
  if (!bound) throw new Error(`mutator:${opts.agent}: provider does not support structured output`);
  const raw = await bound.invoke([
    new SystemMessage(META_SYSTEM),
    new HumanMessage(
      [
        `Agent: ${opts.agent}  Cohort: ${opts.cohort}`,
        `Recent performance: ${performance}`,
        "",
        "=== Current zh prompt ===",
        zh,
        "",
        "=== Current en prompt ===",
        en,
      ].join("\n"),
    ),
  ]);
  return MutationSchema.parse(raw);
}

function sectionPresence(prompt: string): Record<string, boolean> {
  const lower = prompt.toLowerCase();
  return Object.fromEntries(
    REQUIRED_SECTIONS.map((section) => [
      section.category,
      section.variants.some((header) => lower.includes(header)),
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

async function describePerformance(opts: MutateOptions): Promise<string> {
  if (MACRO_AGENT_SET.has(opts.agent)) {
    try {
      const { rows } = await opts.deps.api.scorecardListMacroSkill(opts.cohort, opts.since);
      const score = rows.find((row) => row.agent === opts.agent);
      if (!score) return "no recent macro data; make a conservative clarity-focused edit";
      return [
        `raw_macro_score_5d=${score.mean_raw_macro_score_5d?.toFixed(4) ?? "n/a"}`,
        `hit_rate_5d=${score.hit_rate_5d ?? "n/a"}`,
        `n_obs=${score.n_obs}`,
      ].join(", ");
    } catch {
      return "macro performance unavailable; make a conservative clarity-focused edit";
    }
  }
  try {
    const [{ rows }, { weights }] = await Promise.all([
      opts.deps.api.scorecardListSkill(opts.cohort, opts.since),
      opts.deps.api.darwinianGetWeights(opts.cohort),
    ]);
    const skill = rows.find((row) => row.agent === opts.agent);
    const weight = weights[opts.agent];
    if (!skill && !weight) return "no recent data; make a conservative clarity-focused edit";
    return [
      ...(skill
        ? [
            `mean_alpha_5d=${skill.mean_alpha_5d.toFixed(4)}`,
            `sharpe_window=${skill.sharpe_window ?? "n/a"}`,
            `n_obs=${skill.n_obs}`,
          ]
        : []),
      ...(weight ? [`usage_weight=${weight.weight.toFixed(2)}`] : []),
    ].join(", ");
  } catch {
    return "performance unavailable; make a conservative clarity-focused edit";
  }
}

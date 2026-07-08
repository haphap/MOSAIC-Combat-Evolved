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

import { createHash } from "node:crypto";
import { appendFile, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { z } from "zod";
import {
  assertResearchKnobsParity,
  canonicalResearchKnobs,
  parseResearchKnobsPrompt,
  type ResearchKnobs,
  replaceResearchKnobsFence,
} from "../agents/helpers/research_knobs.js";
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

const PRIVACY_TOKEN_VARIANTS = [
  ["report prose", "报告原文"],
  ["source spans", "source_span_ids", "来源片段"],
  ["prompt body", "提示词正文"],
  ["local paths", "本地路径"],
  ["urls", "链接"],
  ["reviewer text", "评审文本"],
  ["licensed metadata", "许可元数据"],
] as const;

const IMMUTABLE_GUARDRAILS = [
  ["role boundary", "角色边界"],
  ["output schema", "输出 schema"],
  ["required tools", "必需工具"],
  ["current-data gate", "current data gate", "当前数据门槛"],
  ["rke-prior policy", "rke prior policy", "rke 先验策略"],
  ["privacy boundary", "隐私边界"],
  ["audit/footprint contract", "审计/足迹契约"],
  ["shadow/promotion safety policy", "shadow/promotion 安全策略"],
] as const;

export const MutationSchema = z.object({
  zh_prompt: z.string().min(1),
  en_prompt: z.string().min(1),
  modification_summary: z.string().min(1),
  rationale: z.string().min(1),
});
export type Mutation = z.infer<typeof MutationSchema>;

export const KnobPatchSchema = z.object({
  path: z.string().startsWith("/"),
  old_value: z.unknown(),
  new_value: z.unknown(),
  rationale: z.string().min(1),
  expected_effect: z.string().min(1),
});

export const KnobMutationSchema = z.object({
  prediction_target: z.string().min(1),
  evaluation_metric: z.string().min(1),
  knob_patches: z.array(KnobPatchSchema).min(1),
  renormalization: z.array(z.unknown()).default([]),
  risk: z.string().min(1),
});

export type KnobPatch = z.infer<typeof KnobPatchSchema>;
export type KnobMutation = z.infer<typeof KnobMutationSchema>;

export interface KnobMutationValidation {
  accepted: boolean;
  reasons: string[];
}

export interface KnobMutationMetadata {
  schema_version: "knob_mutation_metadata_v1";
  mutation_id: string;
  created_at: string;
  agent: string;
  cohort: string;
  prediction_target: string;
  evaluation_metric: string;
  base_knobs_sha256: string;
  new_knobs_sha256: string;
  changed_paths: string[];
  patches: KnobPatch[];
  renormalization: unknown[];
  decision: "dry_run" | "applied" | "rejected";
  expected_effect: string;
  risk: string;
}

export function validateKnobMutation(
  knobs: ResearchKnobs,
  candidate: unknown,
): KnobMutationValidation {
  const parsed = KnobMutationSchema.safeParse(candidate);
  if (!parsed.success) {
    return { accepted: false, reasons: parsed.error.issues.map((issue) => issue.message) };
  }
  const mutation = parsed.data;
  const reasons: string[] = [];
  if (!knobs.prediction_targets.some((target) => target.id === mutation.prediction_target)) {
    reasons.push("prediction_target is not declared in research knobs");
  }
  for (const patch of mutation.knob_patches) {
    reasons.push(...validateKnobPatch(knobs, patch));
  }
  const finalByPath = new Map<string, unknown>();
  for (const patch of mutation.knob_patches) finalByPath.set(patch.path, patch.new_value);
  if (
    mutation.knob_patches.every((patch) => Object.is(patch.old_value, finalByPath.get(patch.path)))
  ) {
    reasons.push("knob mutation is a no-op");
  }
  return { accepted: reasons.length === 0, reasons };
}

export function applyKnobPatchesToProjection(
  knobs: ResearchKnobs,
  candidate: unknown,
): ResearchKnobs {
  const parsed = KnobMutationSchema.parse(candidate);
  const validation = validateKnobMutation(knobs, parsed);
  if (!validation.accepted) {
    throw new PromptInvariantError(validation.reasons.join("; "));
  }
  const next = structuredClone(knobs) as ResearchKnobs;
  let evidenceWeightsChanged = false;
  for (const patch of parsed.knob_patches) {
    const capMatch = patch.path.match(/\/confidence_policy\/([^/]+)\/cap$/);
    const evidenceKey = evidenceKeyFromLearnableWeightPath(patch.path);
    if (!capMatch?.[1] && !evidenceKey) {
      throw new PromptInvariantError(
        `${patch.path}: projection apply supports confidence caps and evidence-channel learnable parameters only`,
      );
    }
    if (capMatch?.[1]) {
      const cap = next.confidence_caps[capMatch[1]];
      if (!cap) {
        throw new PromptInvariantError(`${patch.path}: confidence cap not found`);
      }
      if (typeof patch.new_value !== "number") {
        throw new PromptInvariantError(`${patch.path}: new_value must be number`);
      }
      cap.cap = patch.new_value;
      continue;
    }
    if (evidenceKey && !(evidenceKey in next.evidence_registry)) {
      throw new PromptInvariantError(`${patch.path}: evidence key not found in registry`);
    }
    evidenceWeightsChanged = true;
  }
  if (evidenceWeightsChanged) {
    next.evidence_weights = renormalizedEvidenceWeights(next, parsed);
  }
  return next;
}

export interface PromptPairKnobPatchResult {
  zh_prompt: string;
  en_prompt: string;
  knobs: ResearchKnobs;
}

export function applyKnobPatchesToPromptPair(
  zhPrompt: string,
  enPrompt: string,
  candidate: unknown,
): PromptPairKnobPatchResult {
  const zh = parseResearchKnobsPrompt(zhPrompt);
  const en = parseResearchKnobsPrompt(enPrompt);
  assertResearchKnobsParity(zh.knobs, en.knobs);
  const knobs = applyKnobPatchesToProjection(zh.knobs, candidate);
  return {
    zh_prompt: replaceResearchKnobsFence(zhPrompt, knobs),
    en_prompt: replaceResearchKnobsFence(enPrompt, knobs),
    knobs,
  };
}

export interface RegistryPatchApplyResult<T> {
  registry: T;
  changed_paths: string[];
}

export function applyKnobPatchesToGovernanceRegistry<T>(
  registry: T,
  knobs: ResearchKnobs,
  candidate: unknown,
): RegistryPatchApplyResult<T> {
  const parsed = KnobMutationSchema.parse(candidate);
  const validation = validateKnobMutation(knobs, parsed);
  if (!validation.accepted) {
    throw new PromptInvariantError(validation.reasons.join("; "));
  }
  const registryFailures: string[] = [];
  for (const patch of parsed.knob_patches) {
    const current = readJsonPointer(registry, patch.path);
    if (!current.found) {
      registryFailures.push(`${patch.path}: target_path not found in governance registry`);
    } else if (!Object.is(current.value, patch.old_value)) {
      registryFailures.push(`${patch.path}: old_value does not match governance registry`);
    }
  }
  if (registryFailures.length > 0) {
    throw new PromptInvariantError(registryFailures.join("; "));
  }
  const next = structuredClone(registry) as T;
  const changed: string[] = [];
  for (const patch of parsed.knob_patches) {
    writeJsonPointer(next, patch.path, patch.new_value);
    changed.push(patch.path);
  }
  return { registry: next, changed_paths: changed };
}

export async function applyKnobPatchesToGovernanceRegistryFile(opts: {
  registryPath: string;
  knobs: ResearchKnobs;
  mutation: unknown;
}): Promise<RegistryPatchApplyResult<unknown> & { registry_path: string }> {
  const raw = await readFile(opts.registryPath, { encoding: "utf-8" });
  const registry = JSON.parse(raw) as unknown;
  const applied = applyKnobPatchesToGovernanceRegistry(registry, opts.knobs, opts.mutation);
  const tmpPath = `${opts.registryPath}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(tmpPath, `${JSON.stringify(applied.registry, null, 2)}\n`, {
    encoding: "utf-8",
  });
  await rename(tmpPath, opts.registryPath);
  return { ...applied, registry_path: opts.registryPath };
}

export function buildKnobMutationMetadata(opts: {
  mutationId: string;
  agent: string;
  cohort: string;
  baseKnobs: ResearchKnobs;
  newKnobs: ResearchKnobs;
  mutation: KnobMutation;
  decision: KnobMutationMetadata["decision"];
  createdAt?: string;
}): KnobMutationMetadata {
  const changedPaths = opts.mutation.knob_patches.map((patch) => patch.path);
  return {
    schema_version: "knob_mutation_metadata_v1",
    mutation_id: opts.mutationId,
    created_at: opts.createdAt ?? new Date().toISOString(),
    agent: opts.agent,
    cohort: opts.cohort,
    prediction_target: opts.mutation.prediction_target,
    evaluation_metric: opts.mutation.evaluation_metric,
    base_knobs_sha256: hashKnobs(opts.baseKnobs),
    new_knobs_sha256: hashKnobs(opts.newKnobs),
    changed_paths: changedPaths,
    patches: opts.mutation.knob_patches,
    renormalization: opts.mutation.renormalization,
    decision: opts.decision,
    expected_effect: opts.mutation.knob_patches.map((patch) => patch.expected_effect).join("; "),
    risk: opts.mutation.risk,
  };
}

export async function appendKnobMutationMetadataLog(opts: {
  logPath: string;
  metadata: KnobMutationMetadata;
}): Promise<void> {
  await mkdir(dirname(opts.logPath), { recursive: true });
  await appendFile(opts.logPath, `${JSON.stringify(opts.metadata)}\n`, { encoding: "utf-8" });
}

function hashKnobs(knobs: ResearchKnobs): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalResearchKnobs(knobs)))
    .digest("hex")}`;
}

export class PromptInvariantError extends Error {
  override readonly name = "PromptInvariantError";
}

/** Normalize for the no-op check: collapse whitespace, trim. */
function normalize(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

function validateKnobPatch(knobs: ResearchKnobs, patch: KnobPatch): string[] {
  const reasons: string[] = [];
  if (patch.path.startsWith("/research_weighting/source_profiles/")) {
    reasons.push("evidence weight patch must not target report-source reliability paths");
  }
  const target = knobs.mutation_targets.find((item) => pathMatches(item.path, patch.path));
  if (!target) {
    reasons.push(`${patch.path}: not declared in mutation_targets`);
    return reasons;
  }
  const current = currentProjectionValue(knobs, patch.path);
  if (current !== undefined && !Object.is(current, patch.old_value)) {
    reasons.push(`${patch.path}: old_value does not match current knobs`);
  }
  if (Object.is(patch.old_value, patch.new_value)) {
    reasons.push(`${patch.path}: no-op patch`);
  }
  reasons.push(...validatePatchValue(target, patch.new_value));
  return reasons;
}

function pathMatches(pattern: string, path: string): boolean {
  if (pattern === path) return true;
  const patternParts = pattern.split("/").filter(Boolean);
  const pathParts = path.split("/").filter(Boolean);
  return (
    patternParts.length === pathParts.length &&
    patternParts.every((part, index) => part === "*" || part === pathParts[index])
  );
}

function currentProjectionValue(knobs: ResearchKnobs, path: string): unknown {
  const capMatch = path.match(/\/confidence_policy\/([^/]+)\/cap$/);
  if (capMatch?.[1]) return knobs.confidence_caps[capMatch[1]]?.cap;
  return undefined;
}

function evidenceKeyFromLearnableWeightPath(path: string): string | null {
  const match = path.match(/\/learnable_parameters\/([^/]+)_weight\/value$/);
  return match?.[1] ?? null;
}

function renormalizedEvidenceWeights(
  knobs: ResearchKnobs,
  mutation: KnobMutation,
): ResearchKnobs["evidence_weights"] {
  const rawValues: Record<string, number> = { ...knobs.evidence_weights };
  for (const entry of mutation.renormalization) {
    if (entry === null || typeof entry !== "object") continue;
    const record = entry as Record<string, unknown>;
    if (record.group !== "evidence_weights") continue;
    const raw = record.raw_values;
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) continue;
    for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
      if (typeof value === "number" && Number.isFinite(value)) rawValues[key] = value;
    }
  }
  for (const patch of mutation.knob_patches) {
    const evidenceKey = evidenceKeyFromLearnableWeightPath(patch.path);
    if (evidenceKey && typeof patch.new_value === "number" && Number.isFinite(patch.new_value)) {
      rawValues[evidenceKey] = patch.new_value;
    }
  }
  const registryKeys = Object.keys(knobs.evidence_registry);
  const total = registryKeys.reduce((sum, key) => sum + Math.max(0, rawValues[key] ?? 0), 0);
  if (total <= 0) {
    throw new PromptInvariantError("evidence_weights renormalization requires positive raw values");
  }
  return Object.fromEntries(
    registryKeys.map((key) => [key, Math.max(0, rawValues[key] ?? 0) / total]),
  );
}

function validatePatchValue(
  target: ResearchKnobs["mutation_targets"][number],
  value: unknown,
): string[] {
  const reasons: string[] = [];
  if (target.type === "number") {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return [`${target.path}: new_value must be a finite number`];
    }
    if (target.min !== undefined && value < target.min) reasons.push(`${target.path}: below min`);
    if (target.max !== undefined && value > target.max) reasons.push(`${target.path}: above max`);
    if (target.step !== undefined && target.min !== undefined) {
      const steps = (value - target.min) / target.step;
      if (Math.abs(steps - Math.round(steps)) > 1e-9) {
        reasons.push(`${target.path}: value is not aligned to step`);
      }
    }
  } else if (target.type === "integer") {
    if (!Number.isInteger(value)) return [`${target.path}: new_value must be integer`];
  } else if (target.type === "boolean") {
    if (typeof value !== "boolean") return [`${target.path}: new_value must be boolean`];
  } else if (target.type === "enum") {
    if (!target.allowed_values?.some((candidate) => Object.is(candidate, value))) {
      return [`${target.path}: new_value is outside allowed_values`];
    }
  }
  return reasons;
}

function pointerParts(path: string): string[] {
  if (!path.startsWith("/")) throw new PromptInvariantError("JSON Pointer path must be absolute");
  return path
    .split("/")
    .slice(1)
    .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"));
}

function readJsonPointer(root: unknown, path: string): { found: boolean; value?: unknown } {
  let cursor = root;
  for (const part of pointerParts(path)) {
    if (cursor === null || typeof cursor !== "object") return { found: false };
    if (!Object.hasOwn(cursor, part)) return { found: false };
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return { found: true, value: cursor };
}

function writeJsonPointer(root: unknown, path: string, value: unknown): void {
  const parts = pointerParts(path);
  let cursor = root;
  for (const part of parts.slice(0, -1)) {
    if (cursor === null || typeof cursor !== "object" || !Object.hasOwn(cursor, part)) {
      throw new PromptInvariantError(`${path}: target parent not found`);
    }
    cursor = (cursor as Record<string, unknown>)[part];
  }
  const leaf = parts.at(-1);
  if (!leaf || cursor === null || typeof cursor !== "object" || !Object.hasOwn(cursor, leaf)) {
    throw new PromptInvariantError(`${path}: target leaf not found`);
  }
  (cursor as Record<string, unknown>)[leaf] = value;
}

/**
 * Guardrails on one rewritten language variant. Throws
 * {@link PromptInvariantError} on any violation (Plan §11.5 4B decision #5).
 */
export function assertPromptInvariants(original: string, rewritten: string): void {
  const rewrittenLower = rewritten.toLowerCase();

  // 1. structure: every E0.5 required section must be present.
  for (const section of REQUIRED_SECTIONS) {
    if (!section.variants.some((header) => rewrittenLower.includes(header))) {
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
      (rewrittenLower.includes("research prior") || rewrittenLower.includes("研究先验")) &&
      (rewrittenLower.includes("not current data") ||
        rewrittenLower.includes("cannot replace current") ||
        rewrittenLower.includes("不是当前数据") ||
        rewrittenLower.includes("不能替代当前数据")) &&
      (rewrittenLower.includes("cannot directly create trades") ||
        rewrittenLower.includes("no trade without current data confirmation") ||
        rewrittenLower.includes("不能直接生成交易") ||
        rewrittenLower.includes("没有当前数据确认就不交易"))
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
    !["missing tool", "tool unavailable", "fallback", "工具缺失", "工具不可用"].some((token) =>
      rewrittenLower.includes(token),
    ) ||
    !["confidence cap", "caps confidence", "置信度上限"].some((token) =>
      rewrittenLower.includes(token),
    )
  ) {
    throw new PromptInvariantError("rewrite dropped required tool/fallback/confidence-cap policy");
  }
  for (const variants of PRIVACY_TOKEN_VARIANTS) {
    if (!variants.some((token) => rewrittenLower.includes(token))) {
      throw new PromptInvariantError(`rewrite dropped privacy token '${variants[0]}'`);
    }
  }
  if (!rewrittenLower.includes("no-action") && !rewrittenLower.includes("不行动")) {
    throw new PromptInvariantError("rewrite dropped refusal/no-action behavior");
  }
  if (
    !(rewrittenLower.includes("mutable") || rewrittenLower.includes("可变")) ||
    !(rewrittenLower.includes("immutable") || rewrittenLower.includes("不可变"))
  ) {
    throw new PromptInvariantError("rewrite blurred mutable/immutable boundaries");
  }
  for (const tokens of IMMUTABLE_GUARDRAILS) {
    if (!tokens.some((token) => rewrittenLower.includes(token))) {
      throw new PromptInvariantError(`rewrite dropped immutable guardrail '${tokens[0]}'`);
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

export interface ResearchKnobPromptMutation extends Mutation {
  knob_mutation: KnobMutation;
  base_knobs: ResearchKnobs;
  new_knobs: ResearchKnobs;
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

function cannedKnobMutation(knobs: ResearchKnobs): KnobMutation {
  const target = knobs.mutation_targets.find((item) =>
    item.path.includes("/confidence_policy/missing_current_data/cap"),
  );
  if (!target) {
    throw new PromptInvariantError("missing confidence-cap mutation target");
  }
  const oldValue = knobs.confidence_caps.missing_current_data?.cap;
  if (typeof oldValue !== "number") {
    throw new PromptInvariantError("missing_current_data cap is not numeric");
  }
  const step = target.step ?? 0.05;
  const min = target.min ?? 0;
  const max = target.max ?? 1;
  const tightened = Number((oldValue - step).toFixed(10));
  const relaxed = Number((oldValue + step).toFixed(10));
  const newValue = tightened >= min ? tightened : relaxed <= max ? relaxed : oldValue;
  return {
    prediction_target: knobs.prediction_targets[0]?.id ?? "primary",
    evaluation_metric: "confidence_calibration_error",
    knob_patches: [
      {
        path: target.path,
        old_value: oldValue,
        new_value: newValue,
        rationale: "Fake-LLM parameter-level mutation for research-knobs smoke coverage.",
        expected_effect: "Exercise code-enforced confidence cap evolution without rewriting prose.",
      },
    ],
    renormalization: [],
    risk: "May understate confidence if missing-data status is noisy.",
  };
}

/**
 * Generate a parameter-level research-knobs mutation and assemble updated prompt
 * projections without rewriting prompt prose.
 */
export async function mutateResearchKnobs(
  opts: MutateOptions,
): Promise<ResearchKnobPromptMutation> {
  const { cohort, agent, deps, since, promptsRoot, fakeLlm } = opts;
  const rootOpt = promptsRoot !== undefined ? { promptsRoot } : {};
  const [zhPrompt, enPrompt] = await Promise.all([
    loadPrompt({ agent, cohort, language: "zh", noCache: true, ...rootOpt }),
    loadPrompt({ agent, cohort, language: "en", noCache: true, ...rootOpt }),
  ]);
  const zh = parseResearchKnobsPrompt(zhPrompt);
  const en = parseResearchKnobsPrompt(enPrompt);
  assertResearchKnobsParity(zh.knobs, en.knobs);

  let knobMutation: KnobMutation;
  if (fakeLlm) {
    knobMutation = cannedKnobMutation(zh.knobs);
  } else {
    const perf = await describePerformance(deps.api, cohort, agent, since);
    const bound = bindStructured(deps.llm, KnobMutationSchema, `knob-mutator:${agent}`);
    if (bound === null) {
      throw new Error(`knob-mutator:${agent}: provider does not support structured output`);
    }
    const raw = await bound.invoke([
      new SystemMessage(
        [
          "You propose parameter-level research-knob mutations only.",
          "Return KnobMutationSchema JSON. Do not rewrite prompt prose.",
          "Use only paths declared in mutation_targets. Include old_value, new_value, rationale, expected_effect, risk.",
          "Choose an evaluation_metric tied to prediction quality, calibration, fallback rate, missing rate, rank correlation, or drawdown avoidance.",
        ].join("\n"),
      ),
      new HumanMessage(
        [
          `Agent: ${agent} Cohort: ${cohort}`,
          `Recent performance: ${perf}`,
          "Current research_knobs:",
          JSON.stringify(canonicalResearchKnobs(zh.knobs), null, 2),
        ].join("\n"),
      ),
    ]);
    knobMutation = KnobMutationSchema.parse(raw);
  }

  const assembled = applyKnobPatchesToPromptPair(zhPrompt, enPrompt, knobMutation);
  return {
    zh_prompt: assembled.zh_prompt,
    en_prompt: assembled.en_prompt,
    modification_summary: `knob patch: ${knobMutation.knob_patches.map((patch) => patch.path).join(", ")}`,
    rationale: knobMutation.knob_patches.map((patch) => patch.rationale).join("; "),
    knob_mutation: knobMutation,
    base_knobs: zh.knobs,
    new_knobs: assembled.knobs,
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

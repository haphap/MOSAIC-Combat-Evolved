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
import { mkdir, open, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { z } from "zod";
import {
  assertResearchKnobsParity,
  canonicalResearchKnobs,
  parseResearchKnobsPrompt,
  type ResearchKnobs,
  renderResearchKnobsFence,
  replaceResearchKnobsFence,
} from "../agents/helpers/research_knobs.js";
import { bindStructured } from "../agents/helpers/structured_output.js";
import { ALL_MACRO_AGENTS } from "../agents/macro/_aggregator.js";
import { findPrivatePromptsRoot } from "../agents/prompts/cohorts.js";
import {
  buildDomainKnobEvaluationContractArtifact,
  type DomainKnobCard,
  domainKnobCardFromPath,
  domainKnobCardsForSpec,
  domainKnobDescriptorFromPath,
  EVALUATION_CALCULATOR_REGISTRY,
  EVALUATION_METRIC_REGISTRY,
  validateCrossFieldInvariants,
  validateWeightGroupInvariants,
} from "../agents/prompts/domain_knob_catalog.js";
import {
  applyKnobPatchesToDomainKnobRegistry as applyDomainKnobRegistryPatches,
  applyDomainKnobValueToProjection,
  type DomainKnobRegistryPatchResult,
  type DomainKnobValueRegistry,
  domainKnobValueRegistryPath,
  projectionValueForDomainCard,
  readDomainKnobValueRegistryFile,
  renderDomainKnobValueRegistry,
  replaceDomainKnobValueInProjection,
  writeDomainKnobValueRegistryFile,
} from "../agents/prompts/domain_knob_registry.js";
import { loadPrompt } from "../agents/prompts/loader.js";
import { buildRuntimeResearchKnobs } from "../agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPEC_BY_AGENT } from "../agents/prompts/runtime_agent_spec.js";
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

export const RollbackConditionSchema = z
  .object({
    metric: z.string().min(1),
    worse_by: z.number().nonnegative(),
    unit: z.enum(["ratio", "bps", "count", "score", "currency", "registered_custom_unit"]),
  })
  .strict();

export const KnobMutationSchema = z.object({
  prediction_target: z.string().min(1),
  evaluation_metric: z.string().min(1),
  horizon: z.string().min(1),
  rollback_condition: RollbackConditionSchema,
  knob_patches: z.array(KnobPatchSchema).min(1),
  renormalization: z.array(z.unknown()).default([]),
  risk: z.string().min(1),
});

export type KnobPatch = z.infer<typeof KnobPatchSchema>;
export type KnobMutation = z.infer<typeof KnobMutationSchema>;

export interface DomainEvaluationPreregistration {
  schema_version: "domain_evaluation_preregistration_v1";
  experiment_id: string;
  experiment_family_id: string;
  registered_at: string;
  calendar_id: "cn_a_share";
  split_policy: {
    train: { start: string; end: string };
    evaluation: { start: string; end: string };
    holdout: {
      holdout_id: string;
      start: string;
      end: string;
      reuse_budget: 1;
    };
    purge_days: number;
    embargo_days: number;
  };
  primary_metric: string;
  secondary_guardrails: Array<{
    metric_id: string;
    direction: "higher_is_better" | "lower_is_better";
    max_degradation: number;
  }>;
  min_effect_size: number;
  min_samples_per_split: number;
  common_support_required: true;
  regime_guardrail: {
    required_regimes: ["normal", "stress"];
    min_samples_per_regime: number;
    max_degradation: number;
  };
  multiple_testing: {
    method: "bonferroni";
    family_size: number;
    attempt_index: number;
    alpha: number;
    adjusted_alpha: number;
  };
}

export interface KnobMutationValidation {
  accepted: boolean;
  reasons: string[];
}

export interface KnobMutationMetadata {
  schema_version: "knob_mutation_metadata_v1";
  mutation_id: string;
  transaction_id: string;
  transaction_manifest_hash?: string;
  experiment_id: string;
  mutation_kind: "domain_knob" | "generic_knob";
  lifecycle_state: "proposed";
  created_at: string;
  agent: string;
  owner_agent?: string;
  owner_stage?: string;
  cohort: string;
  prediction_target: string;
  evaluation_metric: string;
  horizon: string;
  rollback_condition: z.infer<typeof RollbackConditionSchema>;
  base_knobs_sha256: string;
  new_knobs_sha256: string;
  catalog_version: string;
  catalog_hash: string;
  schema_hash: string;
  evaluation_contract_hash: string;
  metric_registry_hash: string;
  calculator_registry_hash: string;
  domain_card_id?: string;
  domain_card_ids: string[];
  calculator_id?: string;
  calculator_version?: string;
  evaluation_policy: {
    baseline_id: string;
    baseline: string;
    min_effect_size: number;
    min_sample_size: number;
    uncertainty_method: string;
    overlapping_sample_policy: string;
    require_uncertainty_bound: boolean;
    preregistration?: DomainEvaluationPreregistration;
    preregistration_hash?: string;
  };
  changed_paths: string[];
  patches: KnobPatch[];
  renormalization: unknown[];
  decision: "dry_run" | "applied" | "rejected";
  expected_effect: string;
  risk: string;
}

export interface KnobTargetRegistryEntry {
  path: string;
  category: "generic" | "domain";
  type: ResearchKnobs["mutation_targets"][number]["type"];
  min?: number;
  max?: number;
  step?: number;
  allowed_values?: unknown[];
  write_back_source: "prompt_ir_governance_registry" | "domain_knob_value_registry";
  evaluation_metrics: string[];
  horizons: string[];
  rollback_metrics: string[];
  domain_card_id?: string;
  domain_card_path?: string;
}

interface ResolvedKnobTargetRegistryEntry {
  target: ResearchKnobs["mutation_targets"][number];
  category: "generic" | "domain";
  domainCard?: NonNullable<ReturnType<typeof domainKnobCardFromPath>>;
  allowedEvaluationMetrics: ReadonlySet<string>;
  allowedHorizons: ReadonlySet<string>;
  allowedRollbackMetrics: ReadonlySet<string>;
}

export function buildKnobTargetRegistry(knobs: ResearchKnobs): KnobTargetRegistryEntry[] {
  const genericPolicy = genericTargetPolicy(knobs);
  return knobs.mutation_targets.map((target) => {
    const domainCard = domainKnobCardFromPath(target.path);
    if (domainCard) {
      const metricClosure = domainCardMetricClosure(domainCard);
      return {
        path: target.path,
        category: "domain",
        type: target.type,
        ...(target.min !== undefined ? { min: target.min } : {}),
        ...(target.max !== undefined ? { max: target.max } : {}),
        ...(target.step !== undefined ? { step: target.step } : {}),
        ...(target.allowed_values !== undefined ? { allowed_values: target.allowed_values } : {}),
        write_back_source: "domain_knob_value_registry",
        evaluation_metrics: metricClosure,
        horizons: [domainCard.horizon],
        rollback_metrics: metricClosure,
        domain_card_id: domainCard.id,
        domain_card_path: domainCard.path,
      };
    }
    return {
      path: target.path,
      category: "generic",
      type: target.type,
      ...(target.min !== undefined ? { min: target.min } : {}),
      ...(target.max !== undefined ? { max: target.max } : {}),
      ...(target.step !== undefined ? { step: target.step } : {}),
      ...(target.allowed_values !== undefined ? { allowed_values: target.allowed_values } : {}),
      write_back_source: "prompt_ir_governance_registry",
      evaluation_metrics: [...genericPolicy.metrics].sort(),
      horizons: [...genericPolicy.horizons].sort(),
      rollback_metrics: [...genericPolicy.metrics].sort(),
    };
  });
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
    const targetEntry = lookupKnobTargetRegistryEntry(knobs, patch.path, reasons);
    if (!targetEntry) continue;
    reasons.push(...validateKnobPatch(knobs, patch, targetEntry.target));
    const domainCard = targetEntry.domainCard;
    if (domainCard && mutation.prediction_target !== domainCard.prediction_target) {
      reasons.push(
        `${patch.path}: prediction_target ${mutation.prediction_target} does not match domain card ${domainCard.prediction_target}`,
      );
    }
    if (domainCard) {
      reasons.push(...validateDomainEvaluationPolicy(targetEntry, mutation, patch.path));
    }
    if (!domainCard) {
      reasons.push(...validateGenericEvaluationPolicy(targetEntry, mutation, patch.path));
    }
  }
  const finalByPath = new Map<string, unknown>();
  for (const patch of mutation.knob_patches) finalByPath.set(patch.path, patch.new_value);
  if (
    mutation.knob_patches.every((patch) => Object.is(patch.old_value, finalByPath.get(patch.path)))
  ) {
    reasons.push("knob mutation is a no-op");
  }
  if (reasons.length === 0) {
    reasons.push(...validateProjectedMutationInvariants(knobs, mutation));
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
  const next = applyKnobPatchesToProjectionUnchecked(knobs, parsed);
  const invariantReasons = validateProjectionInvariants(next);
  if (invariantReasons.length > 0) {
    throw new PromptInvariantError(invariantReasons.join("; "));
  }
  return next;
}

function applyKnobPatchesToProjectionUnchecked(
  knobs: ResearchKnobs,
  parsed: KnobMutation,
): ResearchKnobs {
  const next = structuredClone(knobs) as ResearchKnobs;
  let evidenceWeightsChanged = false;
  const changedDomainCards: string[] = [];
  for (const patch of parsed.knob_patches) {
    const capMatch = patch.path.match(/\/confidence_policy\/([^/]+)\/cap$/);
    const evidenceKey = evidenceKeyFromLearnableWeightPath(patch.path);
    const domainKnob = domainKnobDescriptorFromPath(patch.path);
    if (!capMatch?.[1] && !evidenceKey && !domainKnob) {
      throw new PromptInvariantError(
        `${patch.path}: projection apply supports confidence caps, evidence-channel learnable parameters, and domain knobs only`,
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
    if (domainKnob) {
      replaceDomainKnobValueInProjection(next, domainKnob, patch.old_value, patch.new_value);
      changedDomainCards.push(patch.path);
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
  renormalizeDomainWeightGroups(next, changedDomainCards);
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

export function applyKnobPatchesToDomainKnobRegistry(
  registry: DomainKnobValueRegistry,
  knobs: ResearchKnobs,
  candidate: unknown,
  opts: { mutationId?: string | null } = {},
): DomainKnobRegistryPatchResult {
  const parsed = KnobMutationSchema.parse(candidate);
  const validation = validateKnobMutation(knobs, parsed);
  if (!validation.accepted) {
    throw new PromptInvariantError(validation.reasons.join("; "));
  }
  try {
    return applyDomainKnobRegistryPatches(registry, knobs, parsed, opts);
  } catch (err) {
    throw new PromptInvariantError((err as Error).message);
  }
}

export async function applyKnobPatchesToDomainKnobRegistryFile(opts: {
  registryPath: string;
  knobs: ResearchKnobs;
  mutation: unknown;
  mutationId?: string | null;
}): Promise<DomainKnobRegistryPatchResult & { registry_path: string }> {
  const registry = await readDomainKnobValueRegistryFile(opts.registryPath);
  if (!registry) {
    throw new PromptInvariantError(`${opts.registryPath}: domain knob registry not found`);
  }
  const applied = applyKnobPatchesToDomainKnobRegistry(
    registry,
    opts.knobs,
    opts.mutation,
    opts.mutationId === undefined ? {} : { mutationId: opts.mutationId },
  );
  await writeDomainKnobValueRegistryFile(opts.registryPath, applied.registry);
  return { ...applied, registry_path: opts.registryPath };
}

function canonicalizeJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalizeJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalizeJson(entry)]),
    );
  }
  return value === undefined ? null : value;
}

function hashCanonicalJson(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalizeJson(value)))
    .digest("hex")}`;
}

function horizonDays(horizon: string): number {
  const matched = /^(\d+)d$/.exec(horizon);
  const days = matched ? Number.parseInt(matched[1] ?? "", 10) : Number.NaN;
  if (!Number.isInteger(days) || days < 1) {
    throw new PromptInvariantError(`evaluation horizon must be positive trading days: ${horizon}`);
  }
  return days;
}

function addUtcDays(value: Date, days: number): Date {
  return new Date(value.getTime() + days * 86_400_000);
}

function isoDay(value: Date): string {
  return `${value.toISOString().slice(0, 10)}T00:00:00.000Z`;
}

function guardrailMaxDegradation(metricId: string): number {
  const metric = EVALUATION_METRIC_REGISTRY[metricId];
  if (!metric) throw new PromptInvariantError(`guardrail metric is not registered: ${metricId}`);
  if (metric.unit === "bps") return 5;
  if (metric.unit === "ratio" || metric.unit === "score") return 0.02;
  return 0;
}

function buildDomainEvaluationPreregistration(opts: {
  experimentId: string;
  agent: string;
  cohort: string;
  changedPaths: string[];
  metricId: string;
  card: DomainKnobCard;
  registeredAt: string;
  attemptIndex: number;
  familySize: number;
}): DomainEvaluationPreregistration {
  const registeredAt = new Date(opts.registeredAt);
  if (!Number.isFinite(registeredAt.getTime())) {
    throw new PromptInvariantError("mutation createdAt must be an ISO-8601 timestamp");
  }
  if (
    !Number.isInteger(opts.attemptIndex) ||
    opts.attemptIndex < 1 ||
    !Number.isInteger(opts.familySize) ||
    opts.familySize < opts.attemptIndex
  ) {
    throw new PromptInvariantError("evaluation attempt index must fit the FDR family size");
  }
  const purgeDays = horizonDays(opts.card.horizon);
  const embargoDays = purgeDays;
  const splitDuration = Math.max(90, purgeDays * 4);
  const trainEnd = addUtcDays(registeredAt, -(purgeDays + 1));
  const trainStart = addUtcDays(trainEnd, -730);
  const evaluationStart = addUtcDays(registeredAt, 1);
  const evaluationEnd = addUtcDays(evaluationStart, splitDuration - 1);
  const holdoutStart = addUtcDays(evaluationEnd, embargoDays + 1);
  const holdoutEnd = addUtcDays(holdoutStart, splitDuration - 1);
  const familyPayload = {
    schema_version: "domain_evaluation_family_v1",
    cohort: opts.cohort,
    agent: opts.agent,
    changed_paths: [...opts.changedPaths].sort(),
    primary_metric: opts.metricId,
  };
  const experimentFamilyId = hashCanonicalJson(familyPayload);
  const holdoutId = hashCanonicalJson({
    schema_version: "domain_holdout_v1",
    experiment_family_id: experimentFamilyId,
    start: isoDay(holdoutStart),
    end: isoDay(holdoutEnd),
  });
  const operationalGuardrails = ["fallback_rate", "missing_rate", "confidence_calibration_error"];
  const secondaryMetricIds = uniqueStrings([
    opts.card.evaluation_metric,
    ...opts.card.secondary_metrics,
    ...operationalGuardrails,
  ]).filter((metricId) => metricId !== opts.metricId);
  const alpha = 0.05;
  return {
    schema_version: "domain_evaluation_preregistration_v1",
    experiment_id: opts.experimentId,
    experiment_family_id: experimentFamilyId,
    registered_at: registeredAt.toISOString(),
    calendar_id: "cn_a_share",
    split_policy: {
      train: { start: isoDay(trainStart), end: isoDay(trainEnd) },
      evaluation: { start: isoDay(evaluationStart), end: isoDay(evaluationEnd) },
      holdout: {
        holdout_id: holdoutId,
        start: isoDay(holdoutStart),
        end: isoDay(holdoutEnd),
        reuse_budget: 1,
      },
      purge_days: purgeDays,
      embargo_days: embargoDays,
    },
    primary_metric: opts.metricId,
    secondary_guardrails: secondaryMetricIds.map((metricId) => {
      const guardrailMetric = EVALUATION_METRIC_REGISTRY[metricId];
      if (!guardrailMetric) {
        throw new PromptInvariantError(`guardrail metric is not registered: ${metricId}`);
      }
      return {
        metric_id: metricId,
        direction: guardrailMetric.direction,
        max_degradation: guardrailMaxDegradation(metricId),
      };
    }),
    min_effect_size: 0,
    min_samples_per_split: EVALUATION_METRIC_REGISTRY[opts.metricId]?.min_sample_size ?? 1,
    common_support_required: true,
    regime_guardrail: {
      required_regimes: ["normal", "stress"],
      min_samples_per_regime: Math.max(
        5,
        Math.ceil((EVALUATION_METRIC_REGISTRY[opts.metricId]?.min_sample_size ?? 1) / 4),
      ),
      max_degradation: guardrailMaxDegradation(opts.metricId),
    },
    multiple_testing: {
      method: "bonferroni",
      family_size: opts.familySize,
      attempt_index: opts.attemptIndex,
      alpha,
      adjusted_alpha: alpha / opts.familySize,
    },
  };
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
  transactionId?: string;
  experimentId?: string;
  attemptIndex?: number;
  experimentFamilySize?: number;
}): KnobMutationMetadata {
  const changedPaths = opts.mutation.knob_patches.map((patch) => patch.path);
  const domainCards = changedPaths
    .map((path) => domainKnobCardFromPath(path))
    .filter((card): card is DomainKnobCard => card !== null);
  if (domainCards.length > 0 && domainCards.length !== changedPaths.length) {
    throw new PromptInvariantError("domain and generic knob paths cannot share one mutation");
  }
  const firstDomainCard = domainCards[0];
  const evaluationContract = buildDomainKnobEvaluationContractArtifact();
  const metric = EVALUATION_METRIC_REGISTRY[opts.mutation.evaluation_metric];
  if (firstDomainCard && !metric) {
    throw new PromptInvariantError(
      `evaluation metric is not registered: ${opts.mutation.evaluation_metric}`,
    );
  }
  const calculator = metric ? EVALUATION_CALCULATOR_REGISTRY[metric.calculator_id] : undefined;
  if (firstDomainCard && !calculator) {
    throw new PromptInvariantError(
      `evaluation calculator is not registered: ${metric?.calculator_id ?? "unknown"}`,
    );
  }
  const baseKnobsSha256 = hashKnobs(opts.baseKnobs);
  const createdAt = opts.createdAt ?? new Date().toISOString();
  const experimentId = opts.experimentId ?? `EXP-${opts.mutationId}`;
  const preregistration =
    firstDomainCard && opts.decision === "applied"
      ? buildDomainEvaluationPreregistration({
          experimentId,
          agent: opts.agent,
          cohort: opts.cohort,
          changedPaths,
          metricId: opts.mutation.evaluation_metric,
          card: firstDomainCard,
          registeredAt: createdAt,
          attemptIndex: opts.attemptIndex ?? 1,
          familySize: opts.experimentFamilySize ?? 20,
        })
      : null;
  return {
    schema_version: "knob_mutation_metadata_v1",
    mutation_id: opts.mutationId,
    transaction_id: opts.transactionId ?? `TX-${opts.mutationId}`,
    experiment_id: experimentId,
    mutation_kind: firstDomainCard ? "domain_knob" : "generic_knob",
    lifecycle_state: "proposed",
    created_at: createdAt,
    agent: opts.agent,
    ...(firstDomainCard ? { owner_agent: firstDomainCard.owner_agent } : {}),
    ...(firstDomainCard ? { owner_stage: firstDomainCard.owner_stage } : {}),
    cohort: opts.cohort,
    prediction_target: opts.mutation.prediction_target,
    evaluation_metric: opts.mutation.evaluation_metric,
    horizon: opts.mutation.horizon,
    rollback_condition: opts.mutation.rollback_condition,
    base_knobs_sha256: baseKnobsSha256,
    new_knobs_sha256: hashKnobs(opts.newKnobs),
    catalog_version: evaluationContract.catalog_version,
    catalog_hash: evaluationContract.catalog_hash,
    schema_hash: evaluationContract.schema_hash,
    evaluation_contract_hash: evaluationContract.contract_hash,
    metric_registry_hash: evaluationContract.metric_registry_hash,
    calculator_registry_hash: evaluationContract.calculator_registry_hash,
    ...(firstDomainCard ? { domain_card_id: firstDomainCard.id } : {}),
    domain_card_ids: domainCards.map((card) => card.id).sort(),
    ...(calculator ? { calculator_id: calculator.id } : {}),
    ...(calculator ? { calculator_version: calculator.version } : {}),
    evaluation_policy: {
      baseline_id: baseKnobsSha256,
      baseline: metric?.baseline ?? "rolling_sharpe",
      min_effect_size: 0,
      min_sample_size: metric?.min_sample_size ?? 1,
      uncertainty_method: metric?.uncertainty_method ?? "not_applicable",
      overlapping_sample_policy: metric?.overlapping_sample_policy ?? "not_applicable",
      require_uncertainty_bound: Boolean(firstDomainCard),
      ...(preregistration
        ? {
            preregistration,
            preregistration_hash: hashCanonicalJson(preregistration),
          }
        : {}),
    },
    changed_paths: changedPaths,
    patches: opts.mutation.knob_patches,
    renormalization: opts.mutation.renormalization,
    decision: opts.decision,
    expected_effect: opts.mutation.knob_patches.map((patch) => patch.expected_effect).join("; "),
    risk: opts.mutation.risk,
  };
}

function preregistrationOf(metadata: KnobMutationMetadata): DomainEvaluationPreregistration | null {
  return metadata.evaluation_policy.preregistration ?? null;
}

function familyAttemptRows(
  rows: ReadonlyArray<KnobMutationMetadata>,
  familyId: string,
): Array<{ mutationId: string; attemptIndex: number; familySize: number }> {
  return rows.flatMap((row) => {
    const preregistration = preregistrationOf(row);
    if (!preregistration || preregistration.experiment_family_id !== familyId) return [];
    return [
      {
        mutationId: row.mutation_id,
        attemptIndex: preregistration.multiple_testing.attempt_index,
        familySize: preregistration.multiple_testing.family_size,
      },
    ];
  });
}

function parseMetadataRows(value: string): KnobMutationMetadata[] {
  return value
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as KnobMutationMetadata);
}

async function readMetadataRows(logPath: string): Promise<KnobMutationMetadata[]> {
  try {
    return parseMetadataRows(await readFile(logPath, "utf-8"));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

export async function assignDomainEvaluationAttemptIndex(opts: {
  logPath: string;
  metadata: KnobMutationMetadata;
}): Promise<KnobMutationMetadata> {
  const preregistration = preregistrationOf(opts.metadata);
  if (!preregistration) return opts.metadata;
  const rows = await readMetadataRows(opts.logPath);
  const familyRows = familyAttemptRows(rows, preregistration.experiment_family_id);
  const familySizes = new Set(familyRows.map((row) => row.familySize));
  if (
    familySizes.size > 1 ||
    (familySizes.size === 1 && !familySizes.has(preregistration.multiple_testing.family_size))
  ) {
    throw new Error("domain evaluation family_size drift");
  }
  const usedAttempts = new Set(familyRows.map((row) => row.attemptIndex));
  if (usedAttempts.size !== familyRows.length) {
    throw new Error("domain evaluation attempt history is not unique");
  }
  if (
    [...usedAttempts]
      .sort((left, right) => left - right)
      .some((value, index) => value !== index + 1)
  ) {
    throw new Error("domain evaluation attempt history is not contiguous");
  }
  const attemptIndex = familyRows.length + 1;
  const familySize = preregistration.multiple_testing.family_size;
  if (attemptIndex > familySize) {
    throw new Error("domain evaluation experiment family attempt budget exhausted");
  }
  const nextPreregistration: DomainEvaluationPreregistration = {
    ...preregistration,
    multiple_testing: {
      ...preregistration.multiple_testing,
      attempt_index: attemptIndex,
      adjusted_alpha: preregistration.multiple_testing.alpha / familySize,
    },
  };
  return {
    ...opts.metadata,
    evaluation_policy: {
      ...opts.metadata.evaluation_policy,
      preregistration: nextPreregistration,
      preregistration_hash: hashCanonicalJson(nextPreregistration),
    },
  };
}

function assertFamilyAttemptCanAppend(
  rows: ReadonlyArray<KnobMutationMetadata>,
  metadata: KnobMutationMetadata,
): void {
  const preregistration = preregistrationOf(metadata);
  if (!preregistration) return;
  const familyRows = familyAttemptRows(rows, preregistration.experiment_family_id);
  const expectedAttempt = familyRows.length + 1;
  if (preregistration.multiple_testing.attempt_index !== expectedAttempt) {
    throw new Error(
      `domain evaluation attempt conflict: expected ${expectedAttempt}, got ` +
        preregistration.multiple_testing.attempt_index,
    );
  }
  if (familyRows.some((row) => row.familySize !== preregistration.multiple_testing.family_size)) {
    throw new Error("domain evaluation family_size drift");
  }
}

export async function appendKnobMutationMetadataLog(opts: {
  logPath: string;
  metadata: KnobMutationMetadata;
}): Promise<void> {
  await mkdir(dirname(opts.logPath), { recursive: true });
  const lockPath = `${opts.logPath}.lock`;
  let lock: Awaited<ReturnType<typeof open>> | null = null;
  for (let attempt = 0; attempt < 200; attempt += 1) {
    try {
      lock = await open(lockPath, "wx", 0o600);
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  }
  if (!lock) throw new Error("knob mutation metadata log lock timeout");
  try {
    let existing = "";
    try {
      existing = await readFile(opts.logPath, "utf-8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    const existingLines = existing.split("\n").filter(Boolean);
    const existingRows = parseMetadataRows(existing);
    for (const [index, row] of existingRows.entries()) {
      if (row.mutation_id !== opts.metadata.mutation_id) continue;
      if (existingLines[index] !== JSON.stringify(opts.metadata)) {
        throw new Error(`mutation metadata conflict: ${opts.metadata.mutation_id}`);
      }
      return;
    }
    assertFamilyAttemptCanAppend(existingRows, opts.metadata);
    const file = await open(opts.logPath, "a", 0o600);
    try {
      await file.writeFile(`${JSON.stringify(opts.metadata)}\n`, "utf-8");
      await file.sync();
    } finally {
      await file.close();
    }
  } finally {
    await lock.close();
    await unlink(lockPath).catch(() => undefined);
  }
}

function hashKnobs(knobs: ResearchKnobs): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalResearchKnobs(knobs)))
    .digest("hex")}`;
}

function uniqueStrings(values: ReadonlyArray<string>): string[] {
  return [...new Set(values)];
}

function domainCardMetricClosure(card: DomainKnobCard): string[] {
  return uniqueStrings([
    card.evaluation_metric,
    card.rollback_condition.metric,
    ...card.secondary_metrics,
  ]);
}

export class PromptInvariantError extends Error {
  override readonly name = "PromptInvariantError";
}

/** Normalize for the no-op check: collapse whitespace, trim. */
function normalize(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

function lookupKnobTargetRegistryEntry(
  knobs: ResearchKnobs,
  path: string,
  reasons: string[],
): ResolvedKnobTargetRegistryEntry | null {
  if (path.includes("*")) {
    reasons.push(`${path}: patch path must be concrete`);
    return null;
  }
  if (path.startsWith("/research_weighting/source_profiles/")) {
    reasons.push("evidence weight patch must not target report-source reliability paths");
    return null;
  }
  const registry = buildKnobTargetRegistry(knobs);
  const matches = registry.filter((item) => pathMatches(item.path, path));
  if (matches.length === 0) {
    reasons.push(`${path}: not declared in KnobTargetRegistry`);
    return null;
  }
  if (matches.length > 1) {
    reasons.push(`${path}: matched multiple KnobTargetRegistry entries`);
    return null;
  }
  const entry = matches[0] as KnobTargetRegistryEntry;
  const target = knobs.mutation_targets.find((item) => item.path === entry.path);
  if (!target) {
    reasons.push(`${path}: KnobTargetRegistry entry has no mutation target`);
    return null;
  }
  const domainCard = entry.category === "domain" ? domainKnobCardFromPath(path) : null;
  if (domainCard) {
    return {
      target,
      category: "domain",
      domainCard,
      allowedEvaluationMetrics: new Set(entry.evaluation_metrics),
      allowedHorizons: new Set(entry.horizons),
      allowedRollbackMetrics: new Set(entry.rollback_metrics),
    };
  }
  return {
    target,
    category: "generic",
    allowedEvaluationMetrics: new Set(entry.evaluation_metrics),
    allowedHorizons: new Set(entry.horizons),
    allowedRollbackMetrics: new Set(entry.rollback_metrics),
  };
}

function genericTargetPolicy(knobs: ResearchKnobs): {
  metrics: ReadonlySet<string>;
  horizons: ReadonlySet<string>;
} {
  const metrics = new Set([
    "confidence_calibration_error",
    "fallback_rate",
    "missing_rate",
    "hit_rate_5d",
  ]);
  const layerMetric = defaultMetricForKnobs(knobs);
  if (layerMetric) metrics.add(layerMetric);
  const horizons = new Set(
    [...metrics]
      .map((metric) => EVALUATION_METRIC_REGISTRY[metric]?.window)
      .filter((window): window is string => typeof window === "string" && window.length > 0),
  );
  return { metrics, horizons };
}

function defaultMetricForKnobs(knobs: ResearchKnobs): string | null {
  if (knobs.layer === "macro") return "macro_signal_accuracy_5d";
  if (knobs.layer === "sector") return "sector_rank_correlation_20d";
  if (knobs.layer === "superinvestor") return "style_pick_alpha_60d";
  if (knobs.agent === "decision.cro") return "portfolio_risk_quality_20d";
  if (knobs.agent === "decision.autonomous_execution") return "execution_quality_5d";
  if (knobs.agent === "decision.alpha_discovery") return "alpha_discovery_quality_20d";
  if (knobs.layer === "decision") return "portfolio_construction_quality_20d";
  return null;
}

function validateGenericEvaluationPolicy(
  target: ResolvedKnobTargetRegistryEntry,
  mutation: KnobMutation,
  path: string,
): string[] {
  const reasons: string[] = [];
  if (!target.allowedEvaluationMetrics.has(mutation.evaluation_metric)) {
    reasons.push(
      `${path}: evaluation_metric ${mutation.evaluation_metric} is not allowed for generic target`,
    );
  }
  const metric = EVALUATION_METRIC_REGISTRY[mutation.evaluation_metric];
  if (!metric) {
    reasons.push(`evaluation_metric ${mutation.evaluation_metric} is not registered`);
  } else {
    if (mutation.horizon !== metric.window) {
      reasons.push(`${path}: horizon ${mutation.horizon} is not allowed for generic target`);
    }
  }
  if (!target.allowedRollbackMetrics.has(mutation.rollback_condition.metric)) {
    reasons.push(
      `${path}: rollback_condition.metric ${mutation.rollback_condition.metric} is not allowed for generic target`,
    );
  }
  const rollbackMetric = EVALUATION_METRIC_REGISTRY[mutation.rollback_condition.metric];
  if (!rollbackMetric) {
    reasons.push(
      `rollback_condition.metric ${mutation.rollback_condition.metric} is not registered`,
    );
  } else if (mutation.rollback_condition.unit !== rollbackMetric.unit) {
    reasons.push(
      `${path}: rollback_condition.unit ${mutation.rollback_condition.unit} does not match rollback metric ${rollbackMetric.unit}`,
    );
  }
  return reasons;
}

function validateDomainEvaluationPolicy(
  target: ResolvedKnobTargetRegistryEntry,
  mutation: KnobMutation,
  path: string,
): string[] {
  const reasons: string[] = [];
  if (!target.allowedEvaluationMetrics.has(mutation.evaluation_metric)) {
    reasons.push(
      `${path}: evaluation_metric ${mutation.evaluation_metric} is not allowed for domain card`,
    );
  }
  const metric = EVALUATION_METRIC_REGISTRY[mutation.evaluation_metric];
  if (!metric) {
    reasons.push(`evaluation_metric ${mutation.evaluation_metric} is not registered`);
  } else if (mutation.horizon !== metric.window || !target.allowedHorizons.has(mutation.horizon)) {
    reasons.push(`${path}: horizon ${mutation.horizon} is not allowed for domain card`);
  }
  if (!target.allowedRollbackMetrics.has(mutation.rollback_condition.metric)) {
    reasons.push(
      `${path}: rollback_condition.metric ${mutation.rollback_condition.metric} is not allowed for domain card`,
    );
  }
  const rollbackMetric = EVALUATION_METRIC_REGISTRY[mutation.rollback_condition.metric];
  if (!rollbackMetric) {
    reasons.push(
      `rollback_condition.metric ${mutation.rollback_condition.metric} is not registered`,
    );
  } else if (mutation.rollback_condition.unit !== rollbackMetric.unit) {
    reasons.push(
      `${path}: rollback_condition.unit ${mutation.rollback_condition.unit} does not match rollback metric ${rollbackMetric.unit}`,
    );
  }
  return reasons;
}

function validateProjectedMutationInvariants(
  knobs: ResearchKnobs,
  mutation: KnobMutation,
): string[] {
  let next: ResearchKnobs;
  try {
    next = applyKnobPatchesToProjectionUnchecked(knobs, mutation);
  } catch (err) {
    return [(err as Error).message];
  }
  return validateProjectionInvariants(next);
}

function validateProjectionInvariants(knobs: ResearchKnobs): string[] {
  const agent = knobs.agent.split(".").at(-1);
  const spec = agent ? RUNTIME_AGENT_SPEC_BY_AGENT.get(agent) : undefined;
  if (!spec) return [];
  return [
    ...validateCrossFieldInvariants(spec, knobs),
    ...validateWeightGroupInvariants(spec, knobs),
  ];
}

function validateKnobPatch(
  knobs: ResearchKnobs,
  patch: KnobPatch,
  target: ResearchKnobs["mutation_targets"][number],
): string[] {
  const reasons: string[] = [];
  if (patch.path.startsWith("/research_weighting/source_profiles/")) {
    reasons.push("evidence weight patch must not target report-source reliability paths");
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
  const domainCard = domainKnobCardFromPath(path);
  if (domainCard) return projectionValueForDomainCard(knobs, domainCard);
  const evidenceKey = evidenceKeyFromLearnableWeightPath(path);
  if (evidenceKey) return knobs.evidence_weights[evidenceKey];
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

function renormalizeDomainWeightGroups(knobs: ResearchKnobs, changedPaths: string[]): void {
  const changedCards = changedPaths
    .map((path) => domainKnobCardFromPath(path))
    .filter(
      (card): card is NonNullable<ReturnType<typeof domainKnobCardFromPath>> =>
        card !== null && card.normalization === "sum_to_one" && Boolean(card.weight_group),
    );
  const groups = new Set(changedCards.map((card) => `${card.owner_agent}:${card.weight_group}`));
  if (groups.size === 0) return;
  const agent = knobs.agent.split(".").at(-1);
  const spec = agent ? RUNTIME_AGENT_SPEC_BY_AGENT.get(agent) : undefined;
  if (!spec) return;
  for (const group of groups) {
    const groupName = group.split(":").at(1);
    if (!groupName) continue;
    const members = domainKnobCardsForSpec(spec).filter(
      (card) => card.weight_group === groupName && card.normalization === "sum_to_one",
    );
    const total = members.reduce(
      (sum, card) => sum + Math.max(0, readDomainProjectionNumber(knobs, card)),
      0,
    );
    if (total <= 0) continue;
    for (const card of members) {
      const normalized = Math.max(0, readDomainProjectionNumber(knobs, card)) / total;
      applyDomainKnobValueToProjection(knobs, card, normalized);
    }
  }
}

function readDomainProjectionNumber(knobs: ResearchKnobs, card: DomainKnobCard): number {
  const value = projectionValueForDomainCard(knobs, card);
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
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
    if (typeof value !== "number" || !Number.isInteger(value)) {
      return [`${target.path}: new_value must be integer`];
    }
    if (target.min !== undefined && value < target.min) reasons.push(`${target.path}: below min`);
    if (target.max !== undefined && value > target.max) reasons.push(`${target.path}: above max`);
    if (target.step !== undefined && target.min !== undefined) {
      const steps = (value - target.min) / target.step;
      if (Math.abs(steps - Math.round(steps)) > 1e-9) {
        reasons.push(`${target.path}: value is not aligned to step`);
      }
    }
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
  /** Stable id shared by registry write-back, transaction, metadata, and evaluation. */
  mutationId?: string;
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
  prompt_file_hashes: {
    zh: { old_sha256: string; new_sha256: string };
    en: { old_sha256: string; new_sha256: string };
  };
  domain_registry_update?: {
    relative_path: string;
    content: string;
    old_sha256: string;
    new_sha256: string;
  };
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
  const domainTarget = knobs.mutation_targets.find((item) =>
    [
      "/learnable_parameters/stop_loss_pct/value",
      "/learnable_parameters/mirofish_override_hurdle/value",
    ].some((suffix) => item.path.endsWith(suffix)),
  );
  const domainCard = domainTarget ? domainKnobCardFromPath(domainTarget.path) : null;
  if (domainTarget && domainCard) {
    const oldValue = currentProjectionValue(knobs, domainTarget.path);
    if (typeof oldValue !== "number") {
      throw new PromptInvariantError(`${domainTarget.path}: current domain knob value is missing`);
    }
    const step = domainTarget.step ?? 0.05;
    const min = domainTarget.min ?? 0;
    const max = domainTarget.max ?? 1;
    const lower = Number((oldValue - step).toFixed(10));
    const upper = Number((oldValue + step).toFixed(10));
    const newValue = lower >= min ? lower : upper <= max ? upper : oldValue;
    return {
      prediction_target: domainCard.prediction_target,
      evaluation_metric: domainCard.evaluation_metric,
      horizon: domainCard.horizon,
      rollback_condition: domainCard.rollback_condition,
      knob_patches: [
        {
          path: domainTarget.path,
          old_value: oldValue,
          new_value: newValue,
          rationale: "Fake-LLM position-aware domain knob mutation for smoke coverage.",
          expected_effect: "Exercise position-aware or MiroFish parameter evolution metadata.",
        },
      ],
      renormalization: [],
      risk: "May alter position review behavior until enough post-run samples accumulate.",
    };
  }
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
    horizon: EVALUATION_METRIC_REGISTRY.confidence_calibration_error?.window ?? "5d",
    rollback_condition: {
      metric: "confidence_calibration_error",
      worse_by: 0.03,
      unit: "ratio",
    },
    knob_patches: [
      {
        path: concreteMutationPath(knobs, target.path),
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

function concreteMutationPath(knobs: ResearchKnobs, path: string): string {
  if (!path.includes("*")) return path;
  const agent = knobs.agent.split(".").at(-1) ?? knobs.agent;
  const kind = knobs.layer === "decision" ? (agent === "cro" ? "risk" : "policy") : "soft";
  return path
    .replace("/rule_packs/*/", `/rule_packs/${knobs.agent}.runtime.v1/`)
    .replace("/rules/*/", `/rules/${knobs.layer}.${agent}.${kind}.001/`);
}

const RESEARCH_KNOBS_FENCE_RE = /```research-knobs\s*\n[\s\S]*?```/g;

function researchKnobsFenceCount(prompt: string): number {
  return [...prompt.matchAll(RESEARCH_KNOBS_FENCE_RE)].length;
}

function bootstrapResearchKnobsPrompts(
  agent: string,
  zhPrompt: string,
  enPrompt: string,
): { zhPrompt: string; enPrompt: string } {
  const zhCount = researchKnobsFenceCount(zhPrompt);
  const enCount = researchKnobsFenceCount(enPrompt);
  if (zhCount === 1 && enCount === 1) {
    return { zhPrompt, enPrompt };
  }
  if (zhCount !== 0 || enCount !== 0) {
    throw new Error(
      `expected zh/en prompts to have matching research-knobs fences, found zh=${zhCount} en=${enCount}`,
    );
  }
  const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
  if (!spec) {
    throw new Error(`cannot bootstrap research-knobs for unknown runtime agent: ${agent}`);
  }
  const fence = renderResearchKnobsFence(buildRuntimeResearchKnobs(spec));
  return {
    zhPrompt: `${zhPrompt.replace(/\s+$/, "")}\n\n${fence}\n`,
    enPrompt: `${enPrompt.replace(/\s+$/, "")}\n\n${fence}\n`,
  };
}

/**
 * Generate a parameter-level research-knobs mutation and assemble updated prompt
 * projections without rewriting prompt prose.
 */
export async function mutateResearchKnobs(
  opts: MutateOptions,
): Promise<ResearchKnobPromptMutation> {
  const { cohort, agent, deps, since, promptsRoot, fakeLlm, mutationId } = opts;
  const rootOpt = promptsRoot !== undefined ? { promptsRoot } : {};
  let [zhPrompt, enPrompt] = await Promise.all([
    loadPrompt({ agent, cohort, language: "zh", noCache: true, ...rootOpt }),
    loadPrompt({ agent, cohort, language: "en", noCache: true, ...rootOpt }),
  ]);
  const prompts = bootstrapResearchKnobsPrompts(agent, zhPrompt, enPrompt);
  zhPrompt = prompts.zhPrompt;
  enPrompt = prompts.enPrompt;
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
          "Use only paths declared in mutation_targets. Include horizon, rollback_condition, old_value, new_value, rationale, expected_effect, risk.",
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

  const domainPaths = knobMutation.knob_patches.filter((patch) =>
    domainKnobCardFromPath(patch.path),
  );
  if (domainPaths.length > 0 && domainPaths.length !== knobMutation.knob_patches.length) {
    throw new PromptInvariantError("domain and generic knob paths cannot share one mutation");
  }
  let domainRegistryUpdate: ResearchKnobPromptMutation["domain_registry_update"];
  if (domainPaths.length > 0) {
    if (!mutationId) {
      throw new PromptInvariantError("domain knob mutation requires a stable mutation_id");
    }
    const privatePromptsRoot = promptsRoot ?? findPrivatePromptsRoot();
    if (!privatePromptsRoot) {
      throw new PromptInvariantError(
        "domain knob mutation requires a configured private prompt repo",
      );
    }
    const registryPath = domainKnobValueRegistryPath({
      privatePromptsRoot,
      cohort,
      agent,
    });
    const registry = await readDomainKnobValueRegistryFile(registryPath);
    if (!registry) {
      throw new PromptInvariantError(`domain knob registry is missing for ${cohort}/${agent}`);
    }
    const applied = applyKnobPatchesToDomainKnobRegistry(registry, zh.knobs, knobMutation, {
      mutationId,
    });
    const oldContent = renderDomainKnobValueRegistry(registry);
    const newContent = renderDomainKnobValueRegistry(applied.registry);
    domainRegistryUpdate = {
      relative_path: `registry/domain_knobs/${cohort}/${agent}.json`,
      content: newContent,
      old_sha256: hashText(oldContent),
      new_sha256: hashText(newContent),
    };
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
    prompt_file_hashes: {
      zh: { old_sha256: hashText(zhPrompt), new_sha256: hashText(assembled.zh_prompt) },
      en: { old_sha256: hashText(enPrompt), new_sha256: hashText(assembled.en_prompt) },
    },
    ...(domainRegistryUpdate ? { domain_registry_update: domainRegistryUpdate } : {}),
  };
}

function hashText(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
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

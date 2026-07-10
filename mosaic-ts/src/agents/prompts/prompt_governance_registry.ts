import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { z } from "zod";
import type { ResearchKnobs } from "../helpers/research_knobs.js";
import { normalizePromptsRoot } from "./cohorts.js";
import { buildPromptIrContract, renderPromptIrContract } from "./prompt_ir_registry.js";
import type { RuntimeAgentSpec } from "./runtime_agent_spec.js";

export const PROMPT_GOVERNANCE_VALUES_VERSION = "prompt_governance_values_v1";
export const PROMPT_GOVERNANCE_GENERATOR_VERSION = "prompt_governance_projection_v1";

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);

export const PromptGovernanceValueRegistrySchema = z
  .object({
    schema_version: z.literal(PROMPT_GOVERNANCE_VALUES_VERSION),
    agent: z.string().min(1),
    cohort: z.string().min(1),
    prompt_ir_scope: z.literal("*"),
    prompt_ir_hash: Sha256Schema,
    generator_version: z.literal(PROMPT_GOVERNANCE_GENERATOR_VERSION),
    values_by_path: z.record(z.string().startsWith("/"), z.number().finite()),
    weight_groups: z.record(
      z.string(),
      z
        .object({
          normalization: z.literal("sum_to_one"),
          members: z.array(z.string().startsWith("/")).min(1),
        })
        .strict(),
    ),
    last_mutation_id: z.string().min(1).nullable(),
  })
  .strict();

export type PromptGovernanceValueRegistry = z.infer<typeof PromptGovernanceValueRegistrySchema>;

export interface GenericGovernanceTargetDefinition {
  path: string;
  target: {
    path: string;
    type: "number";
    min: number;
    max: number;
    step: number;
  };
  defaultValue: number;
  evidenceKey?: string;
  confidenceCapId?: string;
  weightGroup?: "evidence_weights";
}

function promptRepoRootFromPromptsRoot(promptsRoot: string): string {
  return dirname(dirname(normalizePromptsRoot(promptsRoot)));
}

export function promptGovernanceValueRegistryPath(opts: {
  privatePromptsRoot: string;
  cohort: string;
  agent: string;
}): string {
  return join(
    promptRepoRootFromPromptsRoot(opts.privatePromptsRoot),
    "registry",
    "prompt_governance",
    opts.cohort,
    `${opts.agent}.json`,
  );
}

export async function readPromptGovernanceValueRegistryFile(
  path: string,
): Promise<PromptGovernanceValueRegistry | null> {
  if (!existsSync(path)) return null;
  return PromptGovernanceValueRegistrySchema.parse(JSON.parse(await readFile(path, "utf-8")));
}

export async function writePromptGovernanceValueRegistryFile(
  path: string,
  registry: PromptGovernanceValueRegistry,
): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, renderPromptGovernanceValueRegistry(registry), "utf-8");
  await rename(temporary, path);
}

export function renderPromptGovernanceValueRegistry(
  registry: PromptGovernanceValueRegistry,
): string {
  const canonical: PromptGovernanceValueRegistry = {
    schema_version: registry.schema_version,
    agent: registry.agent,
    cohort: registry.cohort,
    prompt_ir_scope: registry.prompt_ir_scope,
    prompt_ir_hash: registry.prompt_ir_hash,
    generator_version: registry.generator_version,
    values_by_path: sortRecord(registry.values_by_path),
    weight_groups: sortRecord(registry.weight_groups),
    last_mutation_id: registry.last_mutation_id,
  };
  return `${JSON.stringify(canonical, null, 2)}\n`;
}

export function genericGovernanceTargetDefinitions(
  spec: RuntimeAgentSpec,
): GenericGovernanceTargetDefinition[] {
  const rulePackId = `${spec.layer}.${spec.agent}.runtime.v1`;
  const ruleId = canonicalRuntimeRuleId(spec);
  const nonRkeTools = spec.requiredTools.filter((tool) => tool !== "get_rke_research_context");
  const evidenceKeys =
    nonRkeTools.length > 0
      ? nonRkeTools.map((tool) => evidenceKeyForTool(tool))
      : ["upstream_context"];
  const unitWeight = 1 / evidenceKeys.length;
  const definitions: GenericGovernanceTargetDefinition[] = evidenceKeys.map((evidenceKey) => {
    const path = `/rule_packs/${rulePackId}/rules/${ruleId}/learnable_parameters/${evidenceKey}_weight/value`;
    return {
      path,
      target: { path, type: "number", min: 0, max: 1, step: 0.05 },
      defaultValue: unitWeight,
      evidenceKey,
      weightGroup: "evidence_weights",
    };
  });
  for (const [confidenceCapId, defaultValue] of [
    ["missing_current_data", 0.55],
    ["fallback_primary_tool", 0.6],
  ] as const) {
    const path = `/rule_packs/${rulePackId}/rules/${ruleId}/confidence_policy/${confidenceCapId}/cap`;
    definitions.push({
      path,
      target: { path, type: "number", min: 0.25, max: 0.75, step: 0.05 },
      defaultValue,
      confidenceCapId,
    });
  }
  return definitions;
}

export function buildPromptGovernanceValueRegistry(
  spec: RuntimeAgentSpec,
  cohort: string,
  opts: {
    existing?: PromptGovernanceValueRegistry | null;
    lastMutationId?: string | null;
  } = {},
): PromptGovernanceValueRegistry {
  const definitions = genericGovernanceTargetDefinitions(spec);
  const preserveExisting = Boolean(opts.existing?.last_mutation_id);
  const existingValues = preserveExisting ? (opts.existing?.values_by_path ?? {}) : {};
  const valuesByPath = Object.fromEntries(
    definitions.map((definition) => {
      const existing = existingValues[definition.path];
      return [
        definition.path,
        isTargetValueValid(definition, existing) ? existing : definition.defaultValue,
      ];
    }),
  );
  repairEvidenceWeights(definitions, valuesByPath);
  return {
    schema_version: PROMPT_GOVERNANCE_VALUES_VERSION,
    agent: spec.promptIrAgentId,
    cohort,
    prompt_ir_scope: "*",
    prompt_ir_hash: promptIrHash(spec),
    generator_version: PROMPT_GOVERNANCE_GENERATOR_VERSION,
    values_by_path: valuesByPath,
    weight_groups: weightGroupMetadata(definitions),
    last_mutation_id: opts.lastMutationId ?? opts.existing?.last_mutation_id ?? null,
  };
}

export function validatePromptGovernanceValueRegistry(
  spec: RuntimeAgentSpec,
  registry: PromptGovernanceValueRegistry,
  cohort = registry.cohort,
): string[] {
  const reasons: string[] = [];
  if (registry.agent !== spec.promptIrAgentId) {
    reasons.push(
      `prompt_governance_agent_mismatch:${registry.agent}:expected:${spec.promptIrAgentId}`,
    );
  }
  if (registry.cohort !== cohort) {
    reasons.push(`prompt_governance_cohort_mismatch:${registry.cohort}:expected:${cohort}`);
  }
  if (registry.prompt_ir_hash !== promptIrHash(spec)) {
    reasons.push("prompt_governance_prompt_ir_hash_mismatch");
  }
  const definitions = genericGovernanceTargetDefinitions(spec);
  const byPath = new Map(definitions.map((definition) => [definition.path, definition]));
  for (const definition of definitions) {
    if (!Object.hasOwn(registry.values_by_path, definition.path)) {
      reasons.push(`prompt_governance_path_missing:${definition.path}`);
      continue;
    }
    if (!isTargetValueValid(definition, registry.values_by_path[definition.path])) {
      reasons.push(`prompt_governance_value_invalid:${definition.path}`);
    }
  }
  for (const path of Object.keys(registry.values_by_path)) {
    if (!byPath.has(path)) reasons.push(`prompt_governance_path_stale:${path}`);
  }
  const weightDefinitions = definitions.filter(
    (definition) => definition.weightGroup === "evidence_weights",
  );
  const total = weightDefinitions.reduce(
    (sum, definition) => sum + (registry.values_by_path[definition.path] ?? Number.NaN),
    0,
  );
  if (!Number.isFinite(total) || Math.abs(total - 1) > 1e-9) {
    reasons.push(`prompt_governance_weight_group_not_sum_to_one:${total}`);
  }
  const expectedMembers = weightDefinitions.map((definition) => definition.path).sort();
  const actualMembers = [...(registry.weight_groups.evidence_weights?.members ?? [])].sort();
  if (expectedMembers.join("\n") !== actualMembers.join("\n")) {
    reasons.push("prompt_governance_weight_group_members_mismatch:evidence_weights");
  }
  for (const group of Object.keys(registry.weight_groups)) {
    if (group !== "evidence_weights") reasons.push(`prompt_governance_weight_group_stale:${group}`);
  }
  return reasons;
}

export function promptGovernanceValueForDefinition(
  definition: GenericGovernanceTargetDefinition,
  registry?: PromptGovernanceValueRegistry | null,
): number {
  return registry?.values_by_path[definition.path] ?? definition.defaultValue;
}

export function updatePromptGovernanceRegistryFromProjection(opts: {
  registry: PromptGovernanceValueRegistry;
  spec: RuntimeAgentSpec;
  baseKnobs: ResearchKnobs;
  newKnobs: ResearchKnobs;
  mutation: { knob_patches: ReadonlyArray<{ path: string; old_value: unknown }> };
  mutationId: string;
}): { registry: PromptGovernanceValueRegistry; changed_paths: string[] } {
  const definitions = genericGovernanceTargetDefinitions(opts.spec);
  const byPath = new Map(definitions.map((definition) => [definition.path, definition]));
  const changed = opts.mutation.knob_patches.map((patch) => patch.path);
  if (changed.length === 0 || changed.some((path) => !byPath.has(path))) {
    throw new Error("knob mutation did not target prompt governance registry paths");
  }
  for (const definition of definitions) {
    if (
      !Object.is(
        opts.registry.values_by_path[definition.path],
        projectionValue(definition, opts.baseKnobs),
      )
    ) {
      throw new Error(`${definition.path}: prompt governance registry projection mismatch`);
    }
  }
  for (const patch of opts.mutation.knob_patches) {
    if (!Object.is(opts.registry.values_by_path[patch.path], patch.old_value)) {
      throw new Error(`${patch.path}: old_value does not match prompt governance registry`);
    }
  }
  const next = structuredClone(opts.registry) as PromptGovernanceValueRegistry;
  for (const definition of definitions) {
    const value = projectionValue(definition, opts.newKnobs);
    if (!isTargetValueValid(definition, value)) {
      throw new Error(`${definition.path}: projected prompt governance value is invalid`);
    }
    next.values_by_path[definition.path] = value;
  }
  next.last_mutation_id = opts.mutationId;
  const reasons = validatePromptGovernanceValueRegistry(opts.spec, next, opts.registry.cohort);
  if (reasons.length > 0) throw new Error(reasons.join("; "));
  return { registry: next, changed_paths: changed };
}

function projectionValue(
  definition: GenericGovernanceTargetDefinition,
  knobs: ResearchKnobs,
): number {
  if (definition.evidenceKey) return knobs.evidence_weights[definition.evidenceKey] ?? Number.NaN;
  if (definition.confidenceCapId) {
    return knobs.confidence_caps[definition.confidenceCapId]?.cap ?? Number.NaN;
  }
  return Number.NaN;
}

function promptIrHash(spec: RuntimeAgentSpec): string {
  return `sha256:${createHash("sha256")
    .update(renderPromptIrContract(buildPromptIrContract(spec)))
    .digest("hex")}`;
}

function canonicalRuntimeRuleId(spec: RuntimeAgentSpec): string {
  const kind = spec.layer === "decision" ? (spec.agent === "cro" ? "risk" : "policy") : "soft";
  return `${spec.layer}.${spec.agent}.${kind}.001`;
}

export function evidenceKeyForTool(tool: string): string {
  return tool
    .replace(/^get_/, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/_+$/g, "");
}

function isTargetValueValid(
  definition: GenericGovernanceTargetDefinition,
  value: unknown,
): value is number {
  if (typeof value !== "number" || !Number.isFinite(value)) return false;
  if (value < definition.target.min || value > definition.target.max) return false;
  if (definition.weightGroup) return true;
  const steps = (value - definition.target.min) / definition.target.step;
  return Math.abs(steps - Math.round(steps)) <= 1e-9;
}

function repairEvidenceWeights(
  definitions: ReadonlyArray<GenericGovernanceTargetDefinition>,
  valuesByPath: Record<string, number>,
): void {
  const weights = definitions.filter((definition) => definition.weightGroup === "evidence_weights");
  const total = weights.reduce(
    (sum, definition) => sum + (valuesByPath[definition.path] ?? Number.NaN),
    0,
  );
  if (Number.isFinite(total) && Math.abs(total - 1) <= 1e-9) return;
  for (const definition of weights) valuesByPath[definition.path] = definition.defaultValue;
}

function weightGroupMetadata(
  definitions: ReadonlyArray<GenericGovernanceTargetDefinition>,
): PromptGovernanceValueRegistry["weight_groups"] {
  return {
    evidence_weights: {
      normalization: "sum_to_one",
      members: definitions
        .filter((definition) => definition.weightGroup === "evidence_weights")
        .map((definition) => definition.path),
    },
  };
}

function sortRecord<T>(record: Record<string, T>): Record<string, T> {
  return Object.fromEntries(
    Object.entries(record).sort(([left], [right]) => left.localeCompare(right)),
  );
}

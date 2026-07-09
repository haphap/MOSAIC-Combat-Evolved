import { existsSync } from "node:fs";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { z } from "zod";
import type { ResearchKnobs } from "../helpers/research_knobs.js";
import { normalizePromptsRoot } from "./cohorts.js";
import {
  DOMAIN_KNOB_CATALOG_VERSION,
  type DomainKnobCard,
  domainKnobCardFromPath,
  domainKnobCardsForSpec,
} from "./domain_knob_catalog.js";
import type { RuntimeAgentSpec } from "./runtime_agent_spec.js";

const JsonValueSchema: z.ZodType<unknown> = z.lazy(() =>
  z.union([
    z.string(),
    z.number(),
    z.boolean(),
    z.null(),
    z.array(JsonValueSchema),
    z.record(z.string(), JsonValueSchema),
  ]),
);

export const DomainKnobValueRegistrySchema = z
  .object({
    schema_version: z.literal("domain_knob_values_v1"),
    agent: z.string().min(1),
    cohort: z.string().min(1),
    catalog_version: z.literal(DOMAIN_KNOB_CATALOG_VERSION),
    values_by_path: z.record(z.string().startsWith("/"), JsonValueSchema),
    weight_groups: z.record(z.string(), JsonValueSchema),
    cross_field_groups: z.record(z.string(), JsonValueSchema),
    last_mutation_id: z.string().min(1).nullable(),
  })
  .strict();

export type DomainKnobValueRegistry = z.infer<typeof DomainKnobValueRegistrySchema>;

export interface DomainKnobRegistryPatchResult {
  registry: DomainKnobValueRegistry;
  changed_paths: string[];
}

type MutationTargetLike = {
  path: string;
  type: "number" | "integer" | "enum" | "boolean";
  min?: number | undefined;
  max?: number | undefined;
  step?: number | undefined;
  allowed_values?: unknown[] | undefined;
};

export function privatePromptRepoRootFromPromptsRoot(promptsRoot: string): string {
  return dirname(dirname(normalizePromptsRoot(promptsRoot)));
}

export function domainKnobValueRegistryPath(opts: {
  privatePromptsRoot: string;
  cohort: string;
  agent: string;
}): string {
  return join(
    privatePromptRepoRootFromPromptsRoot(opts.privatePromptsRoot),
    "registry",
    "domain_knobs",
    opts.cohort,
    `${opts.agent}.json`,
  );
}

export async function readDomainKnobValueRegistryFile(
  path: string,
): Promise<DomainKnobValueRegistry | null> {
  if (!existsSync(path)) return null;
  const raw = await readFile(path, "utf-8");
  return DomainKnobValueRegistrySchema.parse(JSON.parse(raw) as unknown);
}

export async function writeDomainKnobValueRegistryFile(
  path: string,
  registry: DomainKnobValueRegistry,
): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const tmpPath = `${path}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(tmpPath, renderDomainKnobValueRegistry(registry), "utf-8");
  await rename(tmpPath, path);
}

export function renderDomainKnobValueRegistry(registry: DomainKnobValueRegistry): string {
  return `${JSON.stringify(canonicalDomainKnobValueRegistry(registry), null, 2)}\n`;
}

export function buildDomainKnobValueRegistry(
  spec: RuntimeAgentSpec,
  cohort: string,
  opts: {
    existing?: DomainKnobValueRegistry | null;
    lastMutationId?: string | null;
  } = {},
): DomainKnobValueRegistry {
  const existingValues = opts.existing?.values_by_path ?? {};
  const values_by_path: Record<string, unknown> = {};
  const cards = mutableDomainCardsForSpec(spec);
  for (const card of cards) {
    const existingValue = existingValues[card.path];
    values_by_path[card.path] =
      Object.hasOwn(existingValues, card.path) &&
      validateDomainValue(card, existingValue, "domain_registry").length === 0
        ? existingValue
        : card.default;
  }
  repairDomainRegistryGroupDefaults(cards, values_by_path);
  return {
    schema_version: "domain_knob_values_v1",
    agent: spec.promptIrAgentId,
    cohort,
    catalog_version: DOMAIN_KNOB_CATALOG_VERSION,
    values_by_path,
    weight_groups: weightGroupMetadata(cards),
    cross_field_groups: crossFieldGroupMetadata(cards),
    last_mutation_id: opts.lastMutationId ?? opts.existing?.last_mutation_id ?? null,
  };
}

export function validateDomainKnobValueRegistry(
  spec: RuntimeAgentSpec,
  registry: DomainKnobValueRegistry,
  cohort = registry.cohort,
): string[] {
  const reasons: string[] = [];
  if (registry.agent !== spec.promptIrAgentId) {
    reasons.push(
      `domain_registry_agent_mismatch:${registry.agent}:expected:${spec.promptIrAgentId}`,
    );
  }
  if (registry.cohort !== cohort) {
    reasons.push(`domain_registry_cohort_mismatch:${registry.cohort}:expected:${cohort}`);
  }
  if (registry.catalog_version !== DOMAIN_KNOB_CATALOG_VERSION) {
    reasons.push(`domain_registry_catalog_version_mismatch:${registry.catalog_version}`);
  }
  const cardsByPath = new Map(mutableDomainCardsForSpec(spec).map((card) => [card.path, card]));
  for (const [path, card] of cardsByPath) {
    if (!Object.hasOwn(registry.values_by_path, path)) {
      reasons.push(`domain_registry_missing_path:${card.id}`);
      continue;
    }
    reasons.push(...validateDomainValue(card, registry.values_by_path[path], "domain_registry"));
  }
  for (const path of Object.keys(registry.values_by_path)) {
    if (!cardsByPath.has(path)) reasons.push(`domain_registry_stale_path:${path}`);
  }
  reasons.push(...validateDomainRegistryWeightGroups([...cardsByPath.values()], registry));
  reasons.push(...validateDomainRegistryCrossFields([...cardsByPath.values()], registry));
  return reasons;
}

export function domainKnobValueForCard(
  card: DomainKnobCard,
  registry?: DomainKnobValueRegistry | null,
): unknown {
  if (registry && Object.hasOwn(registry.values_by_path, card.path)) {
    return registry.values_by_path[card.path];
  }
  return card.default;
}

export function applyDomainKnobValueToProjection(
  knobs: Pick<
    ResearchKnobs,
    "evidence_weights" | "lookbacks" | "thresholds" | "confidence_caps" | "tie_breaks"
  >,
  card: Pick<DomainKnobCard, "id" | "projection_bucket">,
  value: unknown,
): void {
  if (card.projection_bucket === "lookbacks") {
    knobs.lookbacks[card.id] = value;
  } else if (card.projection_bucket === "thresholds") {
    knobs.thresholds[card.id] = value;
  } else if (card.projection_bucket === "evidence_weights") {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new Error(`${card.id}: evidence_weights projection value must be finite number`);
    }
    knobs.evidence_weights[card.id] = value;
  } else if (card.projection_bucket === "confidence_caps") {
    const cap = knobs.confidence_caps[card.id];
    if (!cap) throw new Error(`${card.id}: confidence cap projection target not found`);
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new Error(`${card.id}: confidence_caps projection value must be finite number`);
    }
    cap.cap = value;
  } else {
    if (typeof value !== "string" || value.length === 0) {
      throw new Error(`${card.id}: tie_breaks projection value must be non-empty string`);
    }
    if (!knobs.tie_breaks.includes(value)) knobs.tie_breaks.push(value);
  }
}

export function replaceDomainKnobValueInProjection(
  knobs: Pick<
    ResearchKnobs,
    "evidence_weights" | "lookbacks" | "thresholds" | "confidence_caps" | "tie_breaks"
  >,
  card: Pick<DomainKnobCard, "id" | "projection_bucket">,
  oldValue: unknown,
  newValue: unknown,
): void {
  if (card.projection_bucket !== "tie_breaks") {
    applyDomainKnobValueToProjection(knobs, card, newValue);
    return;
  }
  if (typeof oldValue !== "string" || typeof newValue !== "string" || newValue.length === 0) {
    throw new Error(`${card.id}: tie_breaks projection values must be non-empty strings`);
  }
  const index = knobs.tie_breaks.findIndex((value) => Object.is(value, oldValue));
  if (index < 0) throw new Error(`${card.id}: tie_breaks old value not found`);
  knobs.tie_breaks[index] = newValue;
}

export function projectionValueForDomainCard(
  knobs: Pick<
    ResearchKnobs,
    "evidence_weights" | "lookbacks" | "thresholds" | "confidence_caps" | "tie_breaks"
  >,
  card: Pick<DomainKnobCard, "id" | "projection_bucket"> & Partial<Pick<DomainKnobCard, "default">>,
): unknown {
  if (card.projection_bucket === "lookbacks") return knobs.lookbacks[card.id];
  if (card.projection_bucket === "thresholds") return knobs.thresholds[card.id];
  if (card.projection_bucket === "evidence_weights") return knobs.evidence_weights[card.id];
  if (card.projection_bucket === "confidence_caps") return knobs.confidence_caps[card.id]?.cap;
  const value = typeof card.default === "string" ? card.default : card.id;
  return knobs.tie_breaks.includes(value) ? value : undefined;
}

export function applyKnobPatchesToDomainKnobRegistry(
  registry: DomainKnobValueRegistry,
  knobs: ResearchKnobs,
  mutation: {
    knob_patches: ReadonlyArray<{ path: string; old_value: unknown; new_value: unknown }>;
  },
  opts: { mutationId?: string | null } = {},
): DomainKnobRegistryPatchResult {
  const targetByPath = new Map(knobs.mutation_targets.map((target) => [target.path, target]));
  const next = structuredClone(registry) as DomainKnobValueRegistry;
  const changed: string[] = [];
  for (const patch of mutation.knob_patches) {
    const target = targetByPath.get(patch.path);
    if (!target || !Object.hasOwn(next.values_by_path, patch.path)) continue;
    const current = next.values_by_path[patch.path];
    if (!Object.is(current, patch.old_value)) {
      throw new Error(`${patch.path}: old_value does not match domain knob registry`);
    }
    const valueReasons = validateTargetValue(target, patch.new_value);
    if (valueReasons.length > 0) {
      throw new Error(valueReasons.join("; "));
    }
    next.values_by_path[patch.path] = patch.new_value;
    changed.push(patch.path);
  }
  if (changed.length === 0) {
    throw new Error("knob mutation did not target domain knob registry paths");
  }
  const changedCards = changed.flatMap((path) => {
    const card = domainKnobCardFromPath(path);
    return card ? [card] : [];
  });
  renormalizeDomainRegistryWeightGroups(changedCards, next.values_by_path);
  const registryCards = Object.keys(next.values_by_path)
    .map((path) => domainKnobCardFromPath(path))
    .filter((card): card is DomainKnobCard => card !== null);
  const invariantReasons = [
    ...validateDomainRegistryWeightGroups(registryCards, next),
    ...validateDomainRegistryCrossFields(registryCards, next),
  ];
  if (invariantReasons.length > 0) {
    throw new Error(invariantReasons.join("; "));
  }
  next.last_mutation_id = opts.mutationId ?? next.last_mutation_id;
  return { registry: next, changed_paths: changed };
}

export function mutableDomainCardsForSpec(spec: RuntimeAgentSpec): DomainKnobCard[] {
  return domainKnobCardsForSpec(spec).filter((card) => card.coverage_level !== "gap_pending_tool");
}

function canonicalDomainKnobValueRegistry(
  registry: DomainKnobValueRegistry,
): DomainKnobValueRegistry {
  return {
    schema_version: registry.schema_version,
    agent: registry.agent,
    cohort: registry.cohort,
    catalog_version: registry.catalog_version,
    values_by_path: sortRecord(registry.values_by_path),
    weight_groups: sortRecord(registry.weight_groups),
    cross_field_groups: sortRecord(registry.cross_field_groups),
    last_mutation_id: registry.last_mutation_id,
  };
}

function sortRecord<T>(record: Record<string, T>): Record<string, T> {
  return Object.fromEntries(
    Object.entries(record).sort(([left], [right]) => left.localeCompare(right)),
  );
}

function weightGroupMetadata(cards: ReadonlyArray<DomainKnobCard>): Record<string, unknown> {
  const groups = new Map<string, DomainKnobCard[]>();
  for (const card of cards) {
    if (!card.weight_group) continue;
    const members = groups.get(card.weight_group) ?? [];
    members.push(card);
    groups.set(card.weight_group, members);
  }
  return Object.fromEntries(
    [...groups.entries()].map(([group, members]) => [
      group,
      {
        normalization: "sum_to_one",
        members: members.map((card) => card.path),
      },
    ]),
  );
}

function crossFieldGroupMetadata(cards: ReadonlyArray<DomainKnobCard>): Record<string, unknown> {
  const groups = new Map<string, DomainKnobCard[]>();
  for (const card of cards) {
    if (!card.cross_field_group) continue;
    const members = groups.get(card.cross_field_group) ?? [];
    members.push(card);
    groups.set(card.cross_field_group, members);
  }
  return Object.fromEntries(
    [...groups.entries()].map(([group, members]) => [
      group,
      { members: members.map((card) => card.path) },
    ]),
  );
}

function repairDomainRegistryGroupDefaults(
  cards: ReadonlyArray<DomainKnobCard>,
  valuesByPath: Record<string, unknown>,
): void {
  const groups = groupCards(cards, (card) => card.weight_group);
  for (const members of groups.values()) {
    if (!members.every((card) => card.normalization === "sum_to_one")) continue;
    const total = members.reduce((sum, card) => sum + numericValue(valuesByPath[card.path]), 0);
    const hasInvalid = members.some((card) => numericValue(valuesByPath[card.path]) < 0);
    if (hasInvalid || Math.abs(total - 1) > 1e-9) {
      for (const card of members) valuesByPath[card.path] = card.default;
    }
  }
  if (hasCioCrossFieldViolation(cards, valuesByPath)) {
    for (const card of cards.filter(
      (card) => card.cross_field_group === "cio_portfolio_construction",
    )) {
      valuesByPath[card.path] = card.default;
    }
  }
}

function validateDomainRegistryWeightGroups(
  cards: ReadonlyArray<DomainKnobCard>,
  registry: DomainKnobValueRegistry,
): string[] {
  const reasons: string[] = [];
  for (const [group, members] of groupCards(cards, (card) => card.weight_group)) {
    if (!members.every((card) => card.normalization === "sum_to_one")) continue;
    const values = members.map((card) => numericValue(registry.values_by_path[card.path]));
    if (values.some((value) => !Number.isFinite(value) || value < 0)) {
      reasons.push(`domain_registry_weight_group_invalid_value:${group}`);
      continue;
    }
    const total = values.reduce((sum, value) => sum + value, 0);
    if (Math.abs(total - 1) > 1e-9) {
      reasons.push(`domain_registry_weight_group_not_sum_to_one:${group}:${total.toFixed(6)}`);
    }
  }
  return reasons;
}

function validateDomainRegistryCrossFields(
  cards: ReadonlyArray<DomainKnobCard>,
  registry: DomainKnobValueRegistry,
): string[] {
  return hasCioCrossFieldViolation(cards, registry.values_by_path)
    ? ["domain_registry_cross_field_violation:cio_portfolio_construction"]
    : [];
}

function renormalizeDomainRegistryWeightGroups(
  changedCards: ReadonlyArray<DomainKnobCard>,
  valuesByPath: Record<string, unknown>,
): void {
  if (!changedCards.some((card) => card.weight_group && card.normalization === "sum_to_one")) {
    return;
  }
  const allCards = changedCards
    .flatMap((card) => (card.weight_group ? [card.weight_group] : []))
    .flatMap((group) =>
      Object.keys(valuesByPath)
        .map((path) => domainKnobCardFromPath(path))
        .filter(
          (card): card is DomainKnobCard =>
            card !== null && card.weight_group === group && card.normalization === "sum_to_one",
        ),
    );
  for (const [, members] of groupCards(allCards, (card) => card.weight_group)) {
    const total = members.reduce(
      (sum, card) => sum + Math.max(0, numericValue(valuesByPath[card.path])),
      0,
    );
    if (total <= 0) continue;
    for (const card of members) {
      valuesByPath[card.path] = Math.max(0, numericValue(valuesByPath[card.path])) / total;
    }
  }
}

function hasCioCrossFieldViolation(
  cards: ReadonlyArray<DomainKnobCard>,
  valuesByPath: Record<string, unknown>,
): boolean {
  const byId = new Map(cards.map((card) => [card.id, card]));
  const value = (id: string): number | null => {
    const card = byId.get(id);
    if (!card) return null;
    const raw = valuesByPath[card.path];
    return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
  };
  const targetMin = value("target_count_min");
  const targetMax = value("target_count_max");
  const exit = value("exit_threshold");
  const trim = value("trim_threshold");
  const hold = value("hold_hurdle");
  const add = value("new_buy_hurdle");
  const maxNew = value("max_new_buy_weight");
  const maxTarget = value("max_target_position_weight");
  return Boolean(
    (targetMin !== null && targetMax !== null && targetMin > targetMax) ||
      (exit !== null &&
        trim !== null &&
        hold !== null &&
        add !== null &&
        !(exit <= trim && trim <= hold && hold <= add)) ||
      (maxNew !== null && maxTarget !== null && maxNew > maxTarget),
  );
}

function groupCards(
  cards: ReadonlyArray<DomainKnobCard>,
  keyFn: (card: DomainKnobCard) => string | null,
): Map<string, DomainKnobCard[]> {
  const groups = new Map<string, DomainKnobCard[]>();
  for (const card of cards) {
    const key = keyFn(card);
    if (!key) continue;
    const members = groups.get(key) ?? [];
    members.push(card);
    groups.set(key, members);
  }
  return groups;
}

function numericValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : Number.NaN;
}

function validateDomainValue(card: DomainKnobCard, value: unknown, prefix: string): string[] {
  return validateTargetValue(
    {
      path: card.path,
      type: card.type,
      min: card.min,
      max: card.max,
      step: card.step,
      allowed_values: card.allowed_values,
    },
    value,
    `${prefix}:${card.id}`,
  );
}

function validateTargetValue(
  target: MutationTargetLike,
  value: unknown,
  label = target.path,
): string[] {
  if (target.type === "number") {
    if (typeof value !== "number" || !Number.isFinite(value))
      return [`${label}: value must be number`];
    return validateNumericRange(target, value, label);
  }
  if (target.type === "integer") {
    if (typeof value !== "number" || !Number.isInteger(value))
      return [`${label}: value must be integer`];
    return validateNumericRange(target, value, label);
  }
  if (target.type === "boolean") {
    return typeof value === "boolean" ? [] : [`${label}: value must be boolean`];
  }
  if (!target.allowed_values?.some((candidate) => Object.is(candidate, value))) {
    return [`${label}: value must be in allowed_values`];
  }
  return [];
}

function validateNumericRange(
  target: Pick<MutationTargetLike, "path" | "min" | "max" | "step">,
  value: number,
  label: string,
): string[] {
  const reasons: string[] = [];
  if (target.min !== undefined && value < target.min) reasons.push(`${label}: below min`);
  if (target.max !== undefined && value > target.max) reasons.push(`${label}: above max`);
  if (target.step !== undefined && target.min !== undefined) {
    const steps = (value - target.min) / target.step;
    if (Math.abs(steps - Math.round(steps)) > 1e-9) {
      reasons.push(`${label}: value is not aligned to step`);
    }
  }
  return reasons;
}

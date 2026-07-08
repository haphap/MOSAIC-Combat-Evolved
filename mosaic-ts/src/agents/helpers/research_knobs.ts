import { createHash } from "node:crypto";
import YAML from "yaml";
import { z } from "zod";

const SET_LIKE_LIST_KEYS = new Set([
  "allowed_outputs",
  "must_cover",
  "must_not_cover",
  "required_evidence",
]);

const EvidenceRegistryEntrySchema = z
  .object({
    tool: z.string().min(1).optional(),
    source: z.string().min(1).optional(),
    metric: z.string().min(1),
    current_data: z.boolean(),
    primary: z.boolean(),
    fallback_confidence_cap: z.number().min(0).max(1).optional(),
  })
  .strict()
  .superRefine((entry, ctx) => {
    if (!entry.tool && !entry.source) {
      ctx.addIssue({
        code: "custom",
        message: "evidence_registry entry requires tool or source",
        path: ["tool"],
      });
    }
  });

const ConfidenceCapSchema = z.object({
  cap: z.number().min(0).max(1),
  trigger: z.enum([
    "missing_required_evidence",
    "primary_tool_failed_or_fallback",
    "conflicting_evidence",
  ]),
  enforcement: z.literal("code"),
  required_evidence: z.array(z.string()),
  conflict_rule: z
    .object({
      evidence: z.array(z.string()),
      operator: z.string(),
    })
    .strict()
    .optional(),
}).strict();

const MutationTargetSchema = z
  .object({
    path: z.string().startsWith("/"),
    type: z.enum(["number", "integer", "enum", "boolean"]),
    min: z.number().optional(),
    max: z.number().optional(),
    step: z.number().optional(),
    allowed_values: z.array(z.unknown()).optional(),
  })
  .strict()
  .superRefine((target, ctx) => {
    if (target.path.startsWith("/research_weighting/source_profiles/")) {
      ctx.addIssue({
        code: "custom",
        message: "evidence weights must not target report-source reliability paths",
        path: ["path"],
      });
    }
  });

export const ResearchKnobsSchema = z
  .object({
    schema_version: z.literal("research_knobs_v1"),
    layer: z.enum(["macro", "sector", "superinvestor", "decision"]),
    agent: z.string().min(1),
    research_scope: z
      .object({
        must_cover: z.array(z.string()),
        must_not_cover: z.array(z.string()),
      })
      .strict(),
    prediction_targets: z.array(
      z
        .object({
          id: z.string().min(1),
          target_variable: z.string().min(1),
          horizon: z.string().min(1),
          allowed_outputs: z.array(z.string()),
        })
        .strict(),
    ),
    evidence_registry: z.record(z.string(), EvidenceRegistryEntrySchema),
    evidence_weights: z.record(z.string(), z.number().min(0).max(1)),
    lookbacks: z.record(z.string(), z.unknown()),
    thresholds: z.record(z.string(), z.unknown()),
    confidence_caps: z.record(z.string(), ConfidenceCapSchema),
    tie_breaks: z.array(z.string()),
    mutation_targets: z.array(MutationTargetSchema),
    projection_metadata: z.record(z.string(), z.unknown()).optional(),
  })
  .strict()
  .superRefine((knobs, ctx) => {
    const registryKeys = new Set(Object.keys(knobs.evidence_registry));
    for (const key of Object.keys(knobs.evidence_weights)) {
      if (!registryKeys.has(key)) {
        ctx.addIssue({
          code: "custom",
          message: `evidence_weights.${key} missing from evidence_registry`,
          path: ["evidence_weights", key],
        });
      }
    }
    const total = Object.values(knobs.evidence_weights).reduce((sum, value) => sum + value, 0);
    if (Math.abs(total - 1) > 1e-9) {
      ctx.addIssue({
        code: "custom",
        message: "evidence_weights must sum to 1.0",
        path: ["evidence_weights"],
      });
    }
  });

export type ResearchKnobs = z.infer<typeof ResearchKnobsSchema>;

export interface ParsedResearchKnobsPrompt {
  body: string;
  knobs: ResearchKnobs;
}

export interface ResearchKnobsSnapshot {
  agent: string;
  cohort: string;
  hash: string;
  knobs: ResearchKnobs;
  visibleContract: string;
}

export interface ToolStatus {
  name: string;
  called: boolean;
  failed: boolean;
  missing: boolean;
  fallback: boolean;
  cache_hit: boolean;
  args?: unknown;
  fingerprint?: string;
}

export interface KnobConsumptionContext {
  toolStatuses: ReadonlyArray<ToolStatus>;
  evidenceSignals?: Record<string, "positive" | "negative" | "neutral" | "ambiguous">;
}

export interface ResearchKnobCapAudit {
  knob_snapshot_hash: string;
  pre_cap_confidence: number | null;
  post_cap_confidence: number | null;
  fired_cap_ids: string[];
  cap_reasons: string[];
  tool_status_summary: {
    called: number;
    failed: number;
    missing: number;
    fallback: number;
    cache_hit: number;
  };
}

export function researchKnobsEnabledAgents(
  value = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS,
): ReadonlySet<string> {
  const configured = value?.trim();
  const defaultValue =
    process.env.MOSAIC_PROMPTS_ROOT?.trim() ||
    process.env.MOSAIC_PROMPTS_REPO?.trim() ||
    process.env.MOSAIC_PRIVATE_PROMPT_REPO?.trim()
      ? "*"
      : "";
  return new Set(
    (configured ?? defaultValue)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
}

export function isResearchKnobsEnabled(
  agent: string,
  enabled = researchKnobsEnabledAgents(),
): boolean {
  return enabled.has("*") || enabled.has(agent);
}

export function parseResearchKnobsPrompt(text: string): ParsedResearchKnobsPrompt {
  const matches = [...text.matchAll(/```research-knobs\s*\n([\s\S]*?)```/g)];
  if (matches.length !== 1) {
    throw new Error(`expected exactly one research-knobs fence, found ${matches.length}`);
  }
  const raw = matches[0]?.[1] ?? "";
  const parsed = YAML.parse(raw) as unknown;
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("research-knobs fence must contain a YAML object");
  }
  const root = parsed as Record<string, unknown>;
  const value = root["research-knobs"];
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("research-knobs fence must contain top-level research-knobs object");
  }
  const knobs = ResearchKnobsSchema.parse(value);
  return {
    body: text.replace(matches[0]?.[0] ?? "", "").trim(),
    knobs,
  };
}

export function renderResearchKnobsFence(knobs: ResearchKnobs): string {
  const rendered = YAML.stringify({ "research-knobs": canonicalResearchKnobs(knobs) });
  return `\`\`\`research-knobs\n${rendered}\`\`\``;
}

export function replaceResearchKnobsFence(text: string, knobs: ResearchKnobs): string {
  const matches = [...text.matchAll(/```research-knobs\s*\n([\s\S]*?)```/g)];
  if (matches.length !== 1) {
    throw new Error(`expected exactly one research-knobs fence, found ${matches.length}`);
  }
  return text.replace(matches[0]?.[0] ?? "", renderResearchKnobsFence(knobs));
}

export function canonicalResearchKnobs(value: unknown, parentKey = ""): unknown {
  if (Array.isArray(value)) {
    const items = value.map((item) => canonicalResearchKnobs(item, parentKey));
    if (SET_LIKE_LIST_KEYS.has(parentKey)) {
      return [...items].sort((left, right) =>
        JSON.stringify(left).localeCompare(JSON.stringify(right)),
      );
    }
    return items;
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalResearchKnobs(item, key)]),
    );
  }
  return value;
}

export function assertResearchKnobsParity(left: ResearchKnobs, right: ResearchKnobs): void {
  const leftJson = JSON.stringify(canonicalResearchKnobs(left));
  const rightJson = JSON.stringify(canonicalResearchKnobs(right));
  if (leftJson !== rightJson) {
    throw new Error("zh/en research-knobs parity mismatch");
  }
}

export function buildResearchKnobsSnapshot(opts: {
  agent: string;
  cohort: string;
  knobs: ResearchKnobs;
}): ResearchKnobsSnapshot {
  const canonical = JSON.stringify(canonicalResearchKnobs(opts.knobs));
  const hash = `sha256:${createHash("sha256").update(canonical).digest("hex")}`;
  return {
    agent: opts.agent,
    cohort: opts.cohort,
    hash,
    knobs: opts.knobs,
    visibleContract: renderVisibleResearchKnobsContract(opts.knobs, hash),
  };
}

export function renderVisibleResearchKnobsContract(knobs: ResearchKnobs, hash: string): string {
  const visible = {
    schema_version: knobs.schema_version,
    knob_snapshot_hash: hash,
    research_scope: knobs.research_scope,
    prediction_targets: knobs.prediction_targets,
    evidence_registry: knobs.evidence_registry,
    evidence_weights: knobs.evidence_weights,
    lookbacks: knobs.lookbacks,
    thresholds: knobs.thresholds,
    tie_breaks: knobs.tie_breaks,
    mutation_targets: knobs.mutation_targets.map((target) => ({
      path: target.path,
      type: target.type,
    })),
  };
  return `## Runtime Research Knobs Contract\n\n${JSON.stringify(visible, null, 2)}`;
}

export function applyResearchKnobCaps<T>(
  output: T,
  snapshot: ResearchKnobsSnapshot,
  context: KnobConsumptionContext,
): { output: T; audit: ResearchKnobCapAudit } {
  const pre = readConfidence(output);
  const fired: string[] = [];
  const reasons: string[] = [];
  let cap = pre ?? 1;
  for (const [capId, policy] of Object.entries(snapshot.knobs.confidence_caps)) {
    if (!capTriggered(policy, snapshot.knobs, context)) continue;
    fired.push(capId);
    reasons.push(`${capId}:${policy.trigger}`);
    cap = Math.min(cap, policy.cap);
  }
  const post = pre === null ? null : Math.min(pre, cap);
  const cappedOutput = post === null ? output : clampConfidenceFields(output, post);
  return {
    output: cappedOutput,
    audit: {
      knob_snapshot_hash: snapshot.hash,
      pre_cap_confidence: pre,
      post_cap_confidence: post,
      fired_cap_ids: fired,
      cap_reasons: reasons,
      tool_status_summary: summarizeToolStatuses(context.toolStatuses),
    },
  };
}

function capTriggered(
  policy: ResearchKnobs["confidence_caps"][string],
  knobs: ResearchKnobs,
  context: KnobConsumptionContext,
): boolean {
  if (policy.trigger === "conflicting_evidence") {
    const ruleEvidence = policy.conflict_rule?.evidence ?? policy.required_evidence;
    const directions = ruleEvidence.map((key) => context.evidenceSignals?.[key]).filter(Boolean);
    return directions.includes("positive") && directions.includes("negative");
  }
  const entries = policy.required_evidence.map((key) => ({
    key,
    registry: knobs.evidence_registry[key],
  }));
  if (policy.trigger === "missing_required_evidence") {
    return entries.some(({ registry }) => {
      if (!registry?.current_data) return false;
      if (!registry.tool) return false;
      const status = statusForTool(context.toolStatuses, registry.tool);
      return status === undefined || status.missing || status.failed || status.fallback;
    });
  }
  if (policy.trigger === "primary_tool_failed_or_fallback") {
    return entries.some(({ registry }) => {
      if (!registry?.primary) return false;
      if (!registry.tool) return false;
      const status = statusForTool(context.toolStatuses, registry.tool);
      return status === undefined || status.missing || status.failed || status.fallback;
    });
  }
  return false;
}

function statusForTool(
  statuses: ReadonlyArray<ToolStatus>,
  toolName: string,
): ToolStatus | undefined {
  return statuses.find((status) => status.name === toolName);
}

function readConfidence(output: unknown): number | null {
  if (output === null || typeof output !== "object" || Array.isArray(output)) return null;
  const value = (output as Record<string, unknown>).confidence;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function clampConfidenceFields<T>(value: T, cap: number): T {
  if (Array.isArray(value)) {
    return value.map((item) => clampConfidenceFields(item, cap)) as T;
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      if ((key === "confidence" || key === "confidence_impact") && typeof entry === "number") {
        out[key] = Math.min(entry, cap);
      } else {
        out[key] = clampConfidenceFields(entry, cap);
      }
    }
    return out as T;
  }
  return value;
}

function summarizeToolStatuses(
  statuses: ReadonlyArray<ToolStatus>,
): ResearchKnobCapAudit["tool_status_summary"] {
  return {
    called: statuses.filter((status) => status.called).length,
    failed: statuses.filter((status) => status.failed).length,
    missing: statuses.filter((status) => status.missing).length,
    fallback: statuses.filter((status) => status.fallback).length,
    cache_hit: statuses.filter((status) => status.cache_hit).length,
  };
}

import { createHash } from "node:crypto";
import YAML from "yaml";
import { z } from "zod";
import type { RuntimeAgentStageId, RuntimeDagStageId } from "../prompts/runtime_agent_spec.js";
import { configuredRuntimeResearchKnobsStageKeys } from "../prompts/runtime_stage_enablement.js";

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

const ConfidenceCapSchema = z
  .object({
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
  })
  .strict();

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
    for (const [capId, policy] of Object.entries(knobs.confidence_caps)) {
      if (policy.trigger !== "conflicting_evidence") continue;
      if (!policy.conflict_rule || policy.conflict_rule.evidence.length < 2) {
        ctx.addIssue({
          code: "custom",
          message: "conflicting_evidence requires conflict_rule with at least two evidence keys",
          path: ["confidence_caps", capId, "conflict_rule"],
        });
      }
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
  stage: RuntimeAgentStageId | "legacy_unscoped";
  hash: string;
  knobs: ResearchKnobs;
  consumptionSnapshot: KnobConsumptionSnapshot;
  visibleContract: string;
}

export interface ToolStatus {
  name: string;
  /** Provider/runtime call identity; unique even when a result is served from cache. */
  call_id?: string;
  /** Agent-stage invocation that owns this observation. */
  agent_invocation_id?: string;
  called: boolean;
  failed: boolean;
  missing: boolean;
  fallback: boolean;
  cache_hit: boolean;
  args?: unknown;
  as_of?: string;
  /** Short args-only memo used in logs and replay compaction. */
  fingerprint?: string;
  /** Full canonical SHA-256 values used by evidence provenance. */
  args_fingerprint?: string;
  result_fingerprint?: string;
  source_fingerprint?: string;
}

export interface KnobConsumptionContext {
  toolStatuses: ReadonlyArray<ToolStatus>;
  runtimeSourceStatuses?: ReadonlyArray<RuntimeSourceStatus>;
  evidenceDependencyStatuses?: ReadonlyArray<EvidenceDependencyStatus>;
  evidenceSignals?: Record<string, "positive" | "negative" | "neutral" | "ambiguous">;
}

export type RuntimeSourceState =
  | "loaded"
  | "empty_confirmed"
  | "missing"
  | "stale"
  | "source_error";

export interface RuntimeSourceStatus {
  source_id: string;
  scope: string;
  status: RuntimeSourceState;
  as_of?: string;
  snapshot_hash?: string;
  error_code?: string;
  producer_stage?: string;
  resolved_at_stage?: string;
  adapter_id?: string;
}

/** Normalized in-memory payload emitted by a registered runtime source adapter. */
export interface RuntimeSourceEvidenceObservation {
  source_id: string;
  scope: string;
  metric: string;
  value: unknown;
  unit: string;
  as_of: string;
  lookback: string;
  freshness: "current" | "stale" | "missing" | "fallback" | "tool_failed";
  source_fingerprint: string;
  direction: "positive" | "negative" | "neutral" | "ambiguous";
  privacy_class: "public_structured" | "private_runtime" | "licensed_private";
  adapter_id: string;
  adapter_version: string;
}

export type EvidenceDependencyState =
  | "loaded"
  | "partial_loaded"
  | "missing"
  | "stale"
  | "fallback"
  | "tool_failed";

type DomainProjectionBucket =
  | "lookbacks"
  | "thresholds"
  | "tie_breaks"
  | "evidence_weights"
  | "confidence_caps";

const DOMAIN_PROJECTION_BUCKETS = new Set<DomainProjectionBucket>([
  "lookbacks",
  "thresholds",
  "tie_breaks",
  "evidence_weights",
  "confidence_caps",
]);

export interface EvidenceDependencyStatus {
  card_id: string;
  dependency_id: string;
  evidence_key: string;
  scope: string;
  metric_id?: string;
  as_of?: string;
  status: EvidenceDependencyState;
  coverage_ratio?: number;
  min_scope_coverage?: number;
  required_scope_count?: number;
  loaded_scope_count?: number;
  missing_scopes?: string[];
  fallback_scopes?: string[];
  source_fingerprint?: string;
}

export interface ActiveKnobConsumption {
  card_id: string;
  path: string;
  projection_bucket: DomainProjectionBucket;
  value: unknown;
}

export interface DisabledKnobConsumption {
  card_id: string;
  path: string;
  projection_bucket: DomainProjectionBucket;
  disabled_reason: string;
  missing_runtime_sources: string[];
}

export interface KnobConsumptionSnapshot {
  active_knobs: ActiveKnobConsumption[];
  disabled_knobs: DisabledKnobConsumption[];
  runtimeSourceStatuses: RuntimeSourceStatus[];
}

export interface ResearchKnobCapAudit {
  knob_snapshot_hash: string;
  active_knobs: ActiveKnobConsumption[];
  disabled_knobs: DisabledKnobConsumption[];
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
  runtime_source_status_summary: {
    loaded: number;
    empty_confirmed: number;
    missing: number;
    stale: number;
    source_error: number;
  };
  runtime_source_statuses: RuntimeSourceStatus[];
  evidence_dependency_status_summary: {
    loaded: number;
    partial_loaded: number;
    missing: number;
    stale: number;
    fallback: number;
    tool_failed: number;
  };
  unsupported_knob_influence_ids: string[];
  coverage_ratio: number | null;
  missing_scopes: string[];
  fallback_scopes: string[];
  sample_exclusion_reason: string | null;
  output_selection: "raw" | "deterministic_fallback";
  fallback_reason_code: string | null;
}

export function formatResearchKnobAuditFields(audit: ResearchKnobCapAudit): string[] {
  return [
    `pre_cap_confidence=${audit.pre_cap_confidence ?? "null"}`,
    `post_cap_confidence=${audit.post_cap_confidence ?? "null"}`,
    `fired_caps=${audit.fired_cap_ids.join(",") || "none"}`,
    `knob_snapshot=${audit.knob_snapshot_hash}`,
    `tool_missing=${audit.tool_status_summary.missing}`,
    `tool_fallback=${audit.tool_status_summary.fallback}`,
    `runtime_missing=${audit.runtime_source_status_summary.missing}`,
    `runtime_stale=${audit.runtime_source_status_summary.stale}`,
    `runtime_source_error=${audit.runtime_source_status_summary.source_error}`,
    `dep_missing=${audit.evidence_dependency_status_summary.missing}`,
    `dep_fallback=${audit.evidence_dependency_status_summary.fallback}`,
    `dep_tool_failed=${audit.evidence_dependency_status_summary.tool_failed}`,
    `dep_partial=${audit.evidence_dependency_status_summary.partial_loaded}`,
    `coverage_ratio=${audit.coverage_ratio ?? "null"}`,
    `unsupported_knobs=${audit.unsupported_knob_influence_ids.join(",") || "none"}`,
    `missing_scopes=${audit.missing_scopes.length}`,
    `fallback_scopes=${audit.fallback_scopes.length}`,
    `sample_exclusion=${audit.sample_exclusion_reason ?? "none"}`,
    `output_selection=${audit.output_selection}`,
    `fallback_reason=${audit.fallback_reason_code ?? "none"}`,
  ];
}

export function researchKnobsEnabledAgents(
  value = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS,
): ReadonlySet<string> {
  const enabledAgents = new Set(
    [...configuredRuntimeResearchKnobsStageKeys()].map((key) => key.split(":", 1)[0] as string),
  );
  const configured = value?.trim();
  if (!configured || configured === "*") return enabledAgents;
  const requested = new Set(
    configured
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
  return new Set([...enabledAgents].filter((agent) => requested.has(agent)));
}

export function isResearchKnobsEnabled(
  agent: string,
  enabled = researchKnobsEnabledAgents(),
): boolean {
  return enabled.has("*") || enabled.has(agent);
}

export function researchKnobsEnabledAgentStages(
  value = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES,
  legacyAgentValue = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS,
): ReadonlySet<string> {
  const manifestEnabled = configuredRuntimeResearchKnobsStageKeys();
  const configured = value?.trim();
  if (configured) {
    const requested = configured
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    return new Set(
      [...manifestEnabled].filter((key) => {
        const agent = key.split(":", 1)[0];
        return requested.some(
          (pattern) => pattern === "*" || pattern === key || pattern === `${agent}:*`,
        );
      }),
    );
  }
  const legacyConfigured = legacyAgentValue?.trim();
  if (!legacyConfigured) return manifestEnabled;
  const legacy = researchKnobsEnabledAgents(legacyConfigured);
  return new Set([...manifestEnabled].filter((key) => legacy.has(key.split(":", 1)[0] as string)));
}

export function isResearchKnobsStageEnabled(
  agent: string,
  stage: RuntimeAgentStageId,
  enabled = researchKnobsEnabledAgentStages(),
): boolean {
  return enabled.has("*") || enabled.has(`${agent}:*`) || enabled.has(`${agent}:${stage}`);
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
  stage?: RuntimeAgentStageId;
  runtimeSourceStatuses?: ReadonlyArray<RuntimeSourceStatus>;
}): ResearchKnobsSnapshot {
  const canonical = JSON.stringify(canonicalResearchKnobs(opts.knobs));
  const hash = `sha256:${createHash("sha256").update(canonical).digest("hex")}`;
  const consumptionSnapshot = buildKnobConsumptionSnapshot(
    opts.knobs,
    opts.runtimeSourceStatuses ?? [],
    opts.stage,
  );
  return {
    agent: opts.agent,
    cohort: opts.cohort,
    stage: opts.stage ?? "legacy_unscoped",
    hash,
    knobs: opts.knobs,
    consumptionSnapshot,
    visibleContract: renderVisibleResearchKnobsContract(
      opts.knobs,
      hash,
      consumptionSnapshot,
      opts.stage,
    ),
  };
}

export function renderVisibleResearchKnobsContract(
  knobs: ResearchKnobs,
  hash: string,
  consumptionSnapshot = buildKnobConsumptionSnapshot(knobs, []),
  stage?: RuntimeAgentStageId,
): string {
  const domainCards = domainCardSummaries(knobs);
  const activeDomainPaths = new Set(consumptionSnapshot.active_knobs.map((knob) => knob.path));
  const allDomainPaths = new Set(domainCards.map((card) => card.path));
  const allDomainIds = new Set(domainCards.map((card) => card.id));
  const stageDomainIds = new Set(
    domainCards
      .filter((card) => !stage || card.consumer_stages.includes(stage))
      .map((card) => card.id),
  );
  const visible = {
    schema_version: knobs.schema_version,
    knob_snapshot_hash: hash,
    runtime_stage: stage ?? "legacy_unscoped",
    research_scope: knobs.research_scope,
    prediction_targets: knobs.prediction_targets.filter(
      (target) =>
        !allDomainIds.has(target.target_variable) || stageDomainIds.has(target.target_variable),
    ),
    evidence_registry: knobs.evidence_registry,
    evidence_weights: visibleEvidenceWeights(knobs, consumptionSnapshot),
    lookbacks: visibleProjectionBucket(knobs, "lookbacks", consumptionSnapshot),
    thresholds: visibleProjectionBucket(knobs, "thresholds", consumptionSnapshot),
    tie_breaks: visibleTieBreaks(knobs, consumptionSnapshot),
    active_knobs: consumptionSnapshot.active_knobs,
    disabled_knobs: consumptionSnapshot.disabled_knobs,
    mutation_targets: knobs.mutation_targets
      .filter((target) => !allDomainPaths.has(target.path) || activeDomainPaths.has(target.path))
      .map((target) => ({
        path: target.path,
        type: target.type,
      })),
  };
  return `## Runtime Research Knobs Contract\n\n${JSON.stringify(visible, null, 2)}`;
}

export function buildKnobConsumptionSnapshot(
  knobs: ResearchKnobs,
  runtimeSourceStatuses: ReadonlyArray<RuntimeSourceStatus>,
  stage?: RuntimeAgentStageId,
): KnobConsumptionSnapshot {
  const active_knobs: ActiveKnobConsumption[] = [];
  const disabled_knobs: DisabledKnobConsumption[] = [];
  for (const card of domainCardSummaries(knobs).filter(
    (candidate) => !stage || candidate.consumer_stages.includes(stage),
  )) {
    const value = projectionValueForCard(knobs, card);
    const disabled = disabledReasonForCard(card, runtimeSourceStatuses);
    if (disabled) {
      disabled_knobs.push({
        card_id: card.id,
        path: card.path,
        projection_bucket: card.projection_bucket,
        disabled_reason: disabled.reason,
        missing_runtime_sources: disabled.sources,
      });
    } else {
      active_knobs.push({
        card_id: card.id,
        path: card.path,
        projection_bucket: card.projection_bucket,
        value,
      });
    }
  }
  return {
    active_knobs,
    disabled_knobs,
    runtimeSourceStatuses: [...runtimeSourceStatuses],
  };
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
  const runtimeSourceStatuses =
    context.runtimeSourceStatuses ?? snapshot.consumptionSnapshot.runtimeSourceStatuses;
  const capContext = { ...context, runtimeSourceStatuses };
  for (const [capId, policy] of Object.entries(snapshot.knobs.confidence_caps)) {
    if (!capTriggered(policy, snapshot.knobs, capContext)) continue;
    fired.push(capId);
    reasons.push(`${capId}:${policy.trigger}`);
    cap = Math.min(cap, policy.cap);
  }
  const post = pre === null ? null : Math.min(pre, cap);
  const cappedOutput = post === null ? output : clampConfidenceFields(output, post);
  const evidenceDependencyStatuses =
    context.evidenceDependencyStatuses ??
    deriveEvidenceDependencyStatuses(snapshot.knobs, context.toolStatuses);
  const disabledInfluenceIds = disabledKnobInfluenceIds(cappedOutput, snapshot.consumptionSnapshot);
  if (disabledInfluenceIds.length > 0) {
    throw new Error(`disabled_knob_influence_declared:${disabledInfluenceIds.join(",")}`);
  }
  const unsupported = unsupportedKnobInfluenceIds(
    cappedOutput,
    snapshot.consumptionSnapshot,
    evidenceDependencyStatuses,
  );
  const coverageRatio = dependencyCoverageRatio(evidenceDependencyStatuses);
  const sampleExclusionReason =
    unsupported.length > 0 ? `unsupported_knob_influence:${unsupported.join(",")}` : null;
  const missingScopes = collectMissingScopes(
    snapshot.knobs,
    context.toolStatuses,
    runtimeSourceStatuses,
    evidenceDependencyStatuses,
  );
  const fallbackScopes = collectFallbackScopes(
    snapshot.knobs,
    context.toolStatuses,
    evidenceDependencyStatuses,
  );
  const audit: ResearchKnobCapAudit = {
    knob_snapshot_hash: snapshot.hash,
    active_knobs: snapshot.consumptionSnapshot.active_knobs,
    disabled_knobs: snapshot.consumptionSnapshot.disabled_knobs,
    pre_cap_confidence: pre,
    post_cap_confidence: post,
    fired_cap_ids: fired,
    cap_reasons: reasons,
    tool_status_summary: summarizeToolStatuses(context.toolStatuses),
    runtime_source_status_summary: summarizeRuntimeSourceStatuses(runtimeSourceStatuses),
    runtime_source_statuses: [...runtimeSourceStatuses],
    evidence_dependency_status_summary: summarizeEvidenceDependencyStatuses(
      evidenceDependencyStatuses,
    ),
    unsupported_knob_influence_ids: unsupported,
    coverage_ratio: coverageRatio,
    missing_scopes: missingScopes,
    fallback_scopes: fallbackScopes,
    sample_exclusion_reason: sampleExclusionReason,
    output_selection: "raw",
    fallback_reason_code: null,
  };
  return {
    output: attachVerifiedKnobAudit(cappedOutput, audit),
    audit,
  };
}

export function applyResearchKnobCapsWithFallback<T>(
  rawOutput: T,
  fallbackFactory: () => T,
  snapshot: ResearchKnobsSnapshot,
  context: KnobConsumptionContext,
): { output: T; audit: ResearchKnobCapAudit } {
  let rawResult: ReturnType<typeof applyResearchKnobCaps<T>>;
  try {
    rawResult = applyResearchKnobCaps(rawOutput, snapshot, context);
  } catch (error) {
    const disabledIds = disabledInfluenceIdsFromError(error);
    if (!disabledIds) throw error;
    return deterministicFallbackResult(
      fallbackFactory,
      snapshot,
      context,
      disabledIds,
      `disabled_knob_influence:${disabledIds.join(",")}`,
      null,
    );
  }
  if (rawResult.audit.unsupported_knob_influence_ids.length === 0) return rawResult;
  return deterministicFallbackResult(
    fallbackFactory,
    snapshot,
    context,
    rawResult.audit.unsupported_knob_influence_ids,
    rawResult.audit.sample_exclusion_reason ?? "unsupported_knob_influence",
    rawResult.audit,
  );
}

function deterministicFallbackResult<T>(
  fallbackFactory: () => T,
  snapshot: ResearchKnobsSnapshot,
  context: KnobConsumptionContext,
  rejectedInfluenceIds: string[],
  fallbackReasonCode: string,
  rejectedAudit: ResearchKnobCapAudit | null,
): { output: T; audit: ResearchKnobCapAudit } {
  const fallbackResult = applyResearchKnobCaps(fallbackFactory(), snapshot, context);
  if (fallbackResult.audit.unsupported_knob_influence_ids.length > 0) {
    throw new Error(
      `deterministic_fallback_unsupported_knob_influence:${fallbackResult.audit.unsupported_knob_influence_ids.join(",")}`,
    );
  }
  const audit: ResearchKnobCapAudit = {
    ...(rejectedAudit ?? fallbackResult.audit),
    post_cap_confidence: fallbackResult.audit.post_cap_confidence,
    unsupported_knob_influence_ids: [...rejectedInfluenceIds],
    sample_exclusion_reason: fallbackReasonCode,
    output_selection: "deterministic_fallback",
    fallback_reason_code: fallbackReasonCode,
  };
  return {
    output: attachVerifiedKnobAudit(fallbackResult.output, audit),
    audit,
  };
}

function disabledInfluenceIdsFromError(error: unknown): string[] | null {
  if (!(error instanceof Error)) return null;
  const prefix = "disabled_knob_influence_declared:";
  if (!error.message.startsWith(prefix)) return null;
  return error.message
    .slice(prefix.length)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function assertResearchKnobCappedOutputSchema<T>(
  output: T,
  schema: z.ZodTypeAny,
  agentName: string,
): T {
  const parsed = schema.safeParse(stripRuntimeOwnedOutputEnvelope(output));
  if (!parsed.success) {
    throw new Error(
      `research_knob_capped_output_schema_failed:${agentName}:${parsed.error.message}`,
    );
  }
  return output;
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
      if (registry.source) {
        return runtimeSourceMissing(
          context.runtimeSourceStatuses ?? [],
          runtimeSourceIdsForEvidence(registry.source, registry.metric),
        );
      }
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

interface DomainCardSummary {
  id: string;
  path: string;
  projection_bucket: DomainProjectionBucket;
  default?: unknown;
  owner_stage: RuntimeAgentStageId | "agent_run";
  consumer_stages: RuntimeDagStageId[];
  runtime_input_sources: string[];
  runtime_input_source_policies: Record<
    string,
    Partial<Record<"missing" | "stale" | "source_error" | "empty_confirmed", string>>
  >;
  evidence_dependencies: DomainCardEvidenceDependency[];
  evidence_dependency_policies: Record<string, Record<string, string>>;
}

interface DomainCardEvidenceDependency {
  dependency_id: string;
  evidence_key: string;
  tool: string;
  metric_ids: string[];
  scope_resolution?: "pre_run" | "in_run_tool_derived";
  scope_source_tool?: string;
  max_scope_count?: number;
  min_scope_count?: number;
  empty_scope_behavior?: "allow_empty" | "exclude_sample" | "invalid";
  min_scope_coverage?: number;
}

function domainCardSummaries(knobs: ResearchKnobs): DomainCardSummary[] {
  const metadata = knobs.projection_metadata?.domain_knob_catalog;
  if (metadata === null || typeof metadata !== "object" || Array.isArray(metadata)) return [];
  const cards = (metadata as Record<string, unknown>).cards;
  if (!Array.isArray(cards)) return [];
  return cards.flatMap((card): DomainCardSummary[] => {
    if (card === null || typeof card !== "object" || Array.isArray(card)) return [];
    const record = card as Record<string, unknown>;
    if (
      typeof record.id !== "string" ||
      typeof record.path !== "string" ||
      typeof record.projection_bucket !== "string" ||
      !DOMAIN_PROJECTION_BUCKETS.has(record.projection_bucket as DomainProjectionBucket)
    ) {
      return [];
    }
    const sources = Array.isArray(record.runtime_input_sources)
      ? record.runtime_input_sources.filter(
          (source): source is string => typeof source === "string",
        )
      : [];
    const ownerStage = isRuntimeAgentStage(record.owner_stage) ? record.owner_stage : "agent_run";
    const consumerStages = Array.isArray(record.consumer_stages)
      ? record.consumer_stages.filter(isRuntimeDagStage)
      : [ownerStage];
    return [
      {
        id: record.id,
        path: record.path,
        projection_bucket: record.projection_bucket as DomainProjectionBucket,
        default: record.default,
        owner_stage: ownerStage,
        consumer_stages: consumerStages,
        runtime_input_sources: sources,
        runtime_input_source_policies: runtimeInputSourcePolicies(
          record.runtime_input_source_policies,
        ),
        evidence_dependencies: evidenceDependencies(record.evidence_dependencies),
        evidence_dependency_policies: dependencyPolicies(record.evidence_dependency_policies),
      },
    ];
  });
}

function isRuntimeAgentStage(value: unknown): value is RuntimeAgentStageId {
  return [
    "agent_run",
    "alpha_discovery",
    "cio_proposal",
    "cro_review",
    "execution_feasibility",
    "cio_final",
  ].includes(String(value));
}

function isRuntimeDagStage(value: unknown): value is RuntimeDagStageId {
  return [
    "cycle_input",
    "pre_stage_source_resolution",
    "agent_run",
    "alpha_discovery",
    "cio_proposal",
    "cro_review",
    "execution_feasibility",
    "cio_final",
    "shared_validation",
    "order_adapter",
  ].includes(String(value));
}

function evidenceDependencies(value: unknown): DomainCardEvidenceDependency[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): DomainCardEvidenceDependency[] => {
    if (item === null || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    if (
      typeof record.dependency_id !== "string" ||
      typeof record.evidence_key !== "string" ||
      typeof record.tool !== "string" ||
      !Array.isArray(record.metric_ids)
    ) {
      return [];
    }
    return [
      {
        dependency_id: record.dependency_id,
        evidence_key: record.evidence_key,
        tool: record.tool,
        metric_ids: record.metric_ids.filter(
          (metric): metric is string => typeof metric === "string",
        ),
        ...(record.scope_resolution === "pre_run" ||
        record.scope_resolution === "in_run_tool_derived"
          ? { scope_resolution: record.scope_resolution }
          : {}),
        ...(typeof record.scope_source_tool === "string"
          ? { scope_source_tool: record.scope_source_tool }
          : {}),
        ...(typeof record.max_scope_count === "number"
          ? { max_scope_count: record.max_scope_count }
          : {}),
        ...(typeof record.min_scope_count === "number"
          ? { min_scope_count: record.min_scope_count }
          : {}),
        ...(record.empty_scope_behavior === "allow_empty" ||
        record.empty_scope_behavior === "exclude_sample" ||
        record.empty_scope_behavior === "invalid"
          ? { empty_scope_behavior: record.empty_scope_behavior }
          : {}),
        ...(typeof record.min_scope_coverage === "number"
          ? { min_scope_coverage: record.min_scope_coverage }
          : {}),
      },
    ];
  });
}

function dependencyPolicies(value: unknown): Record<string, Record<string, string>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return {};
  const out: Record<string, Record<string, string>> = {};
  for (const [dependencyId, rawPolicy] of Object.entries(value as Record<string, unknown>)) {
    if (rawPolicy === null || typeof rawPolicy !== "object" || Array.isArray(rawPolicy)) continue;
    out[dependencyId] = Object.fromEntries(
      Object.entries(rawPolicy as Record<string, unknown>).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    );
  }
  return out;
}

function runtimeInputSourcePolicies(
  value: unknown,
): DomainCardSummary["runtime_input_source_policies"] {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return {};
  const policies: DomainCardSummary["runtime_input_source_policies"] = {};
  for (const [source, rawPolicy] of Object.entries(value as Record<string, unknown>)) {
    if (rawPolicy === null || typeof rawPolicy !== "object" || Array.isArray(rawPolicy)) continue;
    const policy: Partial<
      Record<"missing" | "stale" | "source_error" | "empty_confirmed", string>
    > = {};
    for (const status of ["missing", "stale", "source_error", "empty_confirmed"] as const) {
      const action = (rawPolicy as Record<string, unknown>)[status];
      if (typeof action === "string") policy[status] = action;
    }
    policies[source] = policy;
  }
  return policies;
}

function visibleProjectionBucket(
  knobs: ResearchKnobs,
  bucket: "lookbacks" | "thresholds",
  consumptionSnapshot: KnobConsumptionSnapshot,
): Record<string, unknown> {
  const domainIds = new Set(
    domainCardSummaries(knobs)
      .filter((card) => card.projection_bucket === bucket)
      .map((card) => card.id),
  );
  const activeIds = new Set(
    consumptionSnapshot.active_knobs
      .filter((card) => card.projection_bucket === bucket)
      .map((card) => card.card_id),
  );
  return Object.fromEntries(
    Object.entries(knobs[bucket]).filter(([key]) => !domainIds.has(key) || activeIds.has(key)),
  );
}

function visibleEvidenceWeights(
  knobs: ResearchKnobs,
  consumptionSnapshot: KnobConsumptionSnapshot,
): ResearchKnobs["evidence_weights"] {
  const domainIds = new Set(
    domainCardSummaries(knobs)
      .filter((card) => card.projection_bucket === "evidence_weights")
      .map((card) => card.id),
  );
  const activeIds = new Set(
    consumptionSnapshot.active_knobs
      .filter((card) => card.projection_bucket === "evidence_weights")
      .map((card) => card.card_id),
  );
  return Object.fromEntries(
    Object.entries(knobs.evidence_weights).filter(
      ([key]) => !domainIds.has(key) || activeIds.has(key),
    ),
  );
}

function visibleTieBreaks(
  knobs: ResearchKnobs,
  consumptionSnapshot: KnobConsumptionSnapshot,
): ResearchKnobs["tie_breaks"] {
  const domainValues = new Set(
    domainCardSummaries(knobs)
      .filter((card) => card.projection_bucket === "tie_breaks")
      .map((card) => tieBreakValueForCard(card)),
  );
  const activeValues = new Set(
    consumptionSnapshot.active_knobs
      .filter((card) => card.projection_bucket === "tie_breaks" && typeof card.value === "string")
      .map((card) => card.value as string),
  );
  return knobs.tie_breaks.filter((value) => !domainValues.has(value) || activeValues.has(value));
}

function projectionValueForCard(knobs: ResearchKnobs, card: DomainCardSummary): unknown {
  if (card.projection_bucket === "lookbacks") return knobs.lookbacks[card.id];
  if (card.projection_bucket === "thresholds") return knobs.thresholds[card.id];
  if (card.projection_bucket === "evidence_weights") return knobs.evidence_weights[card.id];
  if (card.projection_bucket === "confidence_caps") return knobs.confidence_caps[card.id]?.cap;
  const value = tieBreakValueForCard(card);
  return knobs.tie_breaks.includes(value) ? value : undefined;
}

function tieBreakValueForCard(card: Pick<DomainCardSummary, "id" | "default">): string {
  return typeof card.default === "string" && card.default.length > 0 ? card.default : card.id;
}

function disabledReasonForCard(
  card: DomainCardSummary,
  runtimeSourceStatuses: ReadonlyArray<RuntimeSourceStatus>,
): { reason: string; sources: string[] } | null {
  const disabledSources: string[] = [];
  const reasons: string[] = [];
  for (const source of card.runtime_input_sources) {
    const statuses = runtimeSourceStatuses.filter((status) => status.source_id === source);
    if (statuses.length === 0) {
      disabledSources.push(source);
      reasons.push(`${source}:runtime_status_missing`);
      continue;
    }
    for (const status of statuses) {
      if (status.status === "loaded") continue;
      const action = card.runtime_input_source_policies[source]?.[status.status];
      if (!action) {
        disabledSources.push(source);
        reasons.push(`${source}:${status.status}:policy_missing`);
      } else if (!["allow", "exclude_sample_only"].includes(action)) {
        disabledSources.push(source);
        reasons.push(`${source}:${status.status}:${action}`);
      }
    }
  }
  if (reasons.length === 0) return null;
  return { reason: reasons.join(";"), sources: [...new Set(disabledSources)] };
}

function runtimeSourceIdsForEvidence(source: string, metric: string): string[] {
  if (source === "daily_cycle_state") {
    if (
      [
        "current_position_snapshot",
        "current_market_data",
        "upstream_agent_outputs",
        "previous_target_state",
        "candidate_target_state",
        "position_review_state",
        "position_thesis_state",
        "portfolio_exposure_state",
        "execution_liquidity_state",
        "mirofish_context",
      ].includes(metric)
    ) {
      return [metric];
    }
  }
  return [source];
}

function runtimeSourceMissing(
  statuses: ReadonlyArray<RuntimeSourceStatus>,
  sourceIds: ReadonlyArray<string>,
): boolean {
  return sourceIds.some((sourceId) => {
    const matching = statuses.filter((status) => status.source_id === sourceId);
    return (
      matching.length === 0 ||
      matching.some((status) => ["missing", "stale", "source_error"].includes(status.status))
    );
  });
}

function unsupportedKnobInfluenceIds(
  output: unknown,
  consumptionSnapshot: KnobConsumptionSnapshot,
  evidenceDependencyStatuses: ReadonlyArray<EvidenceDependencyStatus>,
): string[] {
  const activeIds = new Set(consumptionSnapshot.active_knobs.map((knob) => knob.card_id));
  const declared = readDeclaredKnobInfluenceIds(output);
  return declared.filter(
    (id) => !activeIds.has(id) || evidenceDependencyUnsupported(id, evidenceDependencyStatuses),
  );
}

function readDeclaredKnobInfluenceIds(output: unknown): string[] {
  if (output === null || typeof output !== "object" || Array.isArray(output)) return [];
  const raw = (output as Record<string, unknown>).declared_knob_influence_ids;
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function disabledKnobInfluenceIds(
  output: unknown,
  consumptionSnapshot: KnobConsumptionSnapshot,
): string[] {
  const disabledIds = new Set(consumptionSnapshot.disabled_knobs.map((knob) => knob.card_id));
  return readDeclaredKnobInfluenceIds(output).filter((id) => disabledIds.has(id));
}

function evidenceDependencyUnsupported(
  cardId: string,
  statuses: ReadonlyArray<EvidenceDependencyStatus>,
): boolean {
  return statuses
    .filter((status) => status.card_id === cardId)
    .some((status) => {
      if (status.status === "loaded") return false;
      if (status.status === "partial_loaded") {
        return (status.coverage_ratio ?? 0) < (status.min_scope_coverage ?? 1);
      }
      return true;
    });
}

function deriveEvidenceDependencyStatuses(
  knobs: ResearchKnobs,
  toolStatuses: ReadonlyArray<ToolStatus>,
): EvidenceDependencyStatus[] {
  const statuses: EvidenceDependencyStatus[] = [];
  for (const card of domainCardSummaries(knobs)) {
    for (const dependency of card.evidence_dependencies) {
      if (dependency.scope_resolution === "in_run_tool_derived") {
        statuses.push(...deriveInRunToolDerivedStatuses(dependency, toolStatuses));
        continue;
      }
      const toolStatus = statusForTool(toolStatuses, dependency.tool);
      const status: EvidenceDependencyStatus["status"] =
        toolStatus === undefined || toolStatus.missing
          ? "missing"
          : toolStatus.failed
            ? "tool_failed"
            : toolStatus.fallback
              ? "fallback"
              : "loaded";
      const metricIds = dependency.metric_ids.length > 0 ? dependency.metric_ids : [undefined];
      for (const metricId of metricIds) {
        statuses.push({
          card_id: card.id,
          dependency_id: dependency.dependency_id,
          evidence_key: dependency.evidence_key,
          scope: toolStatus?.fingerprint ?? `tool:${dependency.tool}`,
          ...(metricId ? { metric_id: metricId } : {}),
          ...(toolStatus?.as_of ? { as_of: toolStatus.as_of } : {}),
          status,
          coverage_ratio: status === "loaded" ? 1 : 0,
          min_scope_coverage: dependency.min_scope_coverage ?? 1,
          required_scope_count: 1,
          loaded_scope_count: status === "loaded" ? 1 : 0,
          ...(status === "missing" ? { missing_scopes: [dependency.tool] } : {}),
          ...(status === "fallback" ? { fallback_scopes: [dependency.tool] } : {}),
          ...(toolStatus?.fingerprint ? { source_fingerprint: toolStatus.fingerprint } : {}),
        });
      }
    }
  }
  return statuses;
}

function deriveInRunToolDerivedStatuses(
  dependency: DomainCardEvidenceDependency,
  toolStatuses: ReadonlyArray<ToolStatus>,
): EvidenceDependencyStatus[] {
  const sourceTool = dependency.scope_source_tool;
  const sourceStatus = sourceTool ? statusForTool(toolStatuses, sourceTool) : undefined;
  const sourceFailure = sourceToolDerivedFailure(sourceStatus, sourceTool);
  if (sourceFailure) return statusForAllDependencyMetrics(dependency, sourceFailure);

  const sourceScopes = scopedValuesFromArgs(sourceStatus?.args);
  if (sourceScopes.length === 0) {
    const emptyStatus: EvidenceDependencyStatus = {
      card_id: cardIdFromDependencyId(dependency.dependency_id),
      dependency_id: dependency.dependency_id,
      evidence_key: dependency.evidence_key,
      scope: `scope_source:${sourceTool ?? "unknown"}:empty`,
      status: dependency.empty_scope_behavior === "allow_empty" ? "loaded" : "partial_loaded",
      coverage_ratio: dependency.empty_scope_behavior === "allow_empty" ? 1 : 0,
      min_scope_coverage: dependency.min_scope_coverage ?? 1,
      required_scope_count: 0,
      loaded_scope_count: 0,
      ...(sourceStatus?.fingerprint ? { source_fingerprint: sourceStatus.fingerprint } : {}),
    };
    return statusForAllDependencyMetrics(dependency, emptyStatus);
  }

  const maxScopeCount = dependency.max_scope_count ?? sourceScopes.length;
  const selectedScopes = sourceScopes.slice(0, maxScopeCount);
  const overBudgetScopes = sourceScopes.slice(maxScopeCount);
  const validationStatus = statusForTool(toolStatuses, dependency.tool);
  const validationFailure = validationToolFailure(validationStatus, dependency);
  if (validationFailure) return statusForAllDependencyMetrics(dependency, validationFailure);

  const loadedScopes = scopedValuesFromArgs(validationStatus?.args, [
    "loaded_scopes",
    "scopes",
    "candidate_scopes",
    "tickers",
  ]);
  const explicitMissingScopes = scopedValuesFromArgs(validationStatus?.args, ["missing_scopes"]);
  const explicitFallbackScopes = scopedValuesFromArgs(validationStatus?.args, ["fallback_scopes"]);
  const loadedSet = new Set(loadedScopes.length > 0 ? loadedScopes : selectedScopes);
  const missingScopes = [
    ...new Set([
      ...explicitMissingScopes,
      ...selectedScopes.filter((scope) => !loadedSet.has(scope)),
      ...overBudgetScopes,
    ]),
  ];
  const fallbackScopes = [...new Set(explicitFallbackScopes)];
  const loadedCount = selectedScopes.filter((scope) => loadedSet.has(scope)).length;
  const requiredCount = Math.max(sourceScopes.length, dependency.min_scope_count ?? 0);
  const coverageRatio = requiredCount === 0 ? 1 : loadedCount / requiredCount;
  const budgetExhausted =
    overBudgetScopes.length > 0 ||
    booleanArg(validationStatus?.args, ["budget_exhausted", "verification_budget_exhausted"]);
  const hasPartialScope =
    missingScopes.length > 0 ||
    fallbackScopes.length > 0 ||
    budgetExhausted ||
    coverageRatio < (dependency.min_scope_coverage ?? 1);
  const derivedStatus: EvidenceDependencyStatus = {
    card_id: cardIdFromDependencyId(dependency.dependency_id),
    dependency_id: dependency.dependency_id,
    evidence_key: dependency.evidence_key,
    scope: selectedScopes.join(",") || `scope_source:${sourceTool ?? "unknown"}`,
    status: hasPartialScope ? "partial_loaded" : "loaded",
    coverage_ratio: coverageRatio,
    min_scope_coverage: dependency.min_scope_coverage ?? 1,
    required_scope_count: requiredCount,
    loaded_scope_count: loadedCount,
    ...(missingScopes.length > 0 ? { missing_scopes: missingScopes } : {}),
    ...(fallbackScopes.length > 0 ? { fallback_scopes: fallbackScopes } : {}),
    ...(validationStatus?.as_of ? { as_of: validationStatus.as_of } : {}),
    ...(validationStatus?.fingerprint ? { source_fingerprint: validationStatus.fingerprint } : {}),
  };
  return statusForAllDependencyMetrics(dependency, derivedStatus);
}

function sourceToolDerivedFailure(
  status: ToolStatus | undefined,
  toolName: string | undefined,
): EvidenceDependencyStatus | null {
  if (!toolName) {
    return {
      card_id: "",
      dependency_id: "",
      evidence_key: "",
      scope: "scope_source:missing",
      status: "missing",
      coverage_ratio: 0,
      required_scope_count: 1,
      loaded_scope_count: 0,
      missing_scopes: ["scope_source_tool"],
    };
  }
  if (status === undefined || status.missing) {
    return {
      card_id: "",
      dependency_id: "",
      evidence_key: "",
      scope: `tool:${toolName}`,
      status: "missing",
      coverage_ratio: 0,
      required_scope_count: 1,
      loaded_scope_count: 0,
      missing_scopes: [toolName],
    };
  }
  if (status.failed) {
    return {
      card_id: "",
      dependency_id: "",
      evidence_key: "",
      scope: status.fingerprint ?? `tool:${toolName}`,
      status: "tool_failed",
      coverage_ratio: 0,
      required_scope_count: 1,
      loaded_scope_count: 0,
      missing_scopes: [toolName],
      ...(status.as_of ? { as_of: status.as_of } : {}),
      ...(status.fingerprint ? { source_fingerprint: status.fingerprint } : {}),
    };
  }
  if (status.fallback) {
    return {
      card_id: "",
      dependency_id: "",
      evidence_key: "",
      scope: status.fingerprint ?? `tool:${toolName}`,
      status: "fallback",
      coverage_ratio: 0,
      required_scope_count: 1,
      loaded_scope_count: 0,
      fallback_scopes: [toolName],
      ...(status.as_of ? { as_of: status.as_of } : {}),
      ...(status.fingerprint ? { source_fingerprint: status.fingerprint } : {}),
    };
  }
  return null;
}

function validationToolFailure(
  status: ToolStatus | undefined,
  dependency: DomainCardEvidenceDependency,
): EvidenceDependencyStatus | null {
  if (status === undefined || status.missing) {
    return {
      card_id: "",
      dependency_id: "",
      evidence_key: "",
      scope: `tool:${dependency.tool}`,
      status: "missing",
      coverage_ratio: 0,
      required_scope_count: dependency.min_scope_count ?? 1,
      loaded_scope_count: 0,
      missing_scopes: [dependency.tool],
    };
  }
  if (status.failed) {
    return {
      card_id: "",
      dependency_id: "",
      evidence_key: "",
      scope: status.fingerprint ?? `tool:${dependency.tool}`,
      status: "tool_failed",
      coverage_ratio: 0,
      required_scope_count: dependency.min_scope_count ?? 1,
      loaded_scope_count: 0,
      missing_scopes: [dependency.tool],
      ...(status.as_of ? { as_of: status.as_of } : {}),
      ...(status.fingerprint ? { source_fingerprint: status.fingerprint } : {}),
    };
  }
  if (status.fallback) {
    return {
      card_id: "",
      dependency_id: "",
      evidence_key: "",
      scope: status.fingerprint ?? `tool:${dependency.tool}`,
      status: "fallback",
      coverage_ratio: 0,
      required_scope_count: dependency.min_scope_count ?? 1,
      loaded_scope_count: 0,
      fallback_scopes: [dependency.tool],
      ...(status.as_of ? { as_of: status.as_of } : {}),
      ...(status.fingerprint ? { source_fingerprint: status.fingerprint } : {}),
    };
  }
  return null;
}

function statusForAllDependencyMetrics(
  dependency: DomainCardEvidenceDependency,
  base: EvidenceDependencyStatus,
): EvidenceDependencyStatus[] {
  const metrics = dependency.metric_ids.length > 0 ? dependency.metric_ids : [undefined];
  return metrics.map((metricId) => ({
    ...base,
    card_id: cardIdFromDependencyId(dependency.dependency_id),
    dependency_id: dependency.dependency_id,
    evidence_key: dependency.evidence_key,
    ...(metricId ? { metric_id: metricId } : {}),
  }));
}

function scopedValuesFromArgs(
  args: unknown,
  keys = ["candidate_scopes", "scopes", "tickers"],
): string[] {
  if (args === null || typeof args !== "object" || Array.isArray(args)) return [];
  const record = args as Record<string, unknown>;
  for (const key of keys) {
    const values = record[key];
    if (!Array.isArray(values)) continue;
    return values
      .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
      .map((value) => (key === "tickers" && !value.includes(":") ? `ticker:${value}` : value));
  }
  return [];
}

function booleanArg(args: unknown, keys: ReadonlyArray<string>): boolean {
  if (args === null || typeof args !== "object" || Array.isArray(args)) return false;
  const record = args as Record<string, unknown>;
  return keys.some((key) => record[key] === true);
}

function cardIdFromDependencyId(dependencyId: string): string {
  const parts = dependencyId.split(".");
  return parts.length > 2 ? parts.slice(2, -1).join(".") : dependencyId;
}

function dependencyCoverageRatio(statuses: ReadonlyArray<EvidenceDependencyStatus>): number | null {
  const ratios = statuses
    .map((status) => status.coverage_ratio)
    .filter((ratio): ratio is number => typeof ratio === "number" && Number.isFinite(ratio));
  if (ratios.length === 0) return null;
  return Math.min(...ratios);
}

function collectMissingScopes(
  knobs: ResearchKnobs,
  toolStatuses: ReadonlyArray<ToolStatus>,
  runtimeSourceStatuses: ReadonlyArray<RuntimeSourceStatus>,
  evidenceDependencyStatuses: ReadonlyArray<EvidenceDependencyStatus>,
): string[] {
  const scopes = toolStatuses
    .filter((status) => status.missing || status.failed)
    .map((status) => `tool:${status.name}:${status.failed ? "failed" : "missing"}`);
  scopes.push(...requiredEvidenceMissingScopes(knobs, toolStatuses, runtimeSourceStatuses));
  scopes.push(
    ...runtimeSourceStatuses
      .filter((status) => ["missing", "stale", "source_error"].includes(status.status))
      .map((status) => `${status.source_id}:${status.scope}:${status.status}`),
  );
  for (const status of evidenceDependencyStatuses) {
    if (["missing", "stale", "tool_failed"].includes(status.status)) {
      scopes.push(
        ...(status.missing_scopes?.length
          ? status.missing_scopes.map((scope) => `${status.dependency_id}:${scope}`)
          : [`${status.dependency_id}:${status.scope}:${status.status}`]),
      );
    }
    if (status.status === "partial_loaded" && (status.coverage_ratio ?? 0) < 1) {
      scopes.push(
        ...(status.missing_scopes?.length
          ? status.missing_scopes.map((scope) => `${status.dependency_id}:${scope}`)
          : [`${status.dependency_id}:${status.scope}:partial_loaded`]),
      );
    }
  }
  return [...new Set(scopes)];
}

function collectFallbackScopes(
  knobs: ResearchKnobs,
  toolStatuses: ReadonlyArray<ToolStatus>,
  evidenceDependencyStatuses: ReadonlyArray<EvidenceDependencyStatus>,
): string[] {
  const scopes = toolStatuses
    .filter((status) => status.fallback)
    .map((status) => `tool:${status.name}:fallback`);
  scopes.push(...requiredEvidenceFallbackScopes(knobs, toolStatuses));
  for (const status of evidenceDependencyStatuses) {
    if (status.status === "fallback") {
      scopes.push(
        ...(status.fallback_scopes?.length
          ? status.fallback_scopes.map((scope) => `${status.dependency_id}:${scope}`)
          : [`${status.dependency_id}:${status.scope}:fallback`]),
      );
    }
    if (status.status === "partial_loaded" && status.fallback_scopes?.length) {
      scopes.push(...status.fallback_scopes.map((scope) => `${status.dependency_id}:${scope}`));
    }
  }
  return [...new Set(scopes)];
}

function requiredEvidenceMissingScopes(
  knobs: ResearchKnobs,
  toolStatuses: ReadonlyArray<ToolStatus>,
  runtimeSourceStatuses: ReadonlyArray<RuntimeSourceStatus>,
): string[] {
  const scopes: string[] = [];
  for (const key of requiredCurrentEvidenceKeys(knobs)) {
    const registry = knobs.evidence_registry[key];
    if (!registry) continue;
    if (registry.tool) {
      const status = statusForTool(toolStatuses, registry.tool);
      if (!status) scopes.push(`tool:${registry.tool}:missing`);
      if (status?.missing || status?.failed) {
        scopes.push(`tool:${registry.tool}:${status.failed ? "failed" : "missing"}`);
      }
    }
    if (registry.source) {
      for (const sourceId of runtimeSourceIdsForEvidence(registry.source, registry.metric)) {
        const matching = runtimeSourceStatuses.filter((status) => status.source_id === sourceId);
        if (matching.length === 0) scopes.push(`${sourceId}:*:missing`);
        for (const status of matching) {
          if (["missing", "stale", "source_error"].includes(status.status)) {
            scopes.push(`${sourceId}:${status.scope}:${status.status}`);
          }
        }
      }
    }
  }
  return scopes;
}

function requiredEvidenceFallbackScopes(
  knobs: ResearchKnobs,
  toolStatuses: ReadonlyArray<ToolStatus>,
): string[] {
  const scopes: string[] = [];
  for (const key of requiredCurrentEvidenceKeys(knobs)) {
    const registry = knobs.evidence_registry[key];
    if (!registry?.tool) continue;
    const status = statusForTool(toolStatuses, registry.tool);
    if (status?.fallback) scopes.push(`tool:${registry.tool}:fallback`);
  }
  return scopes;
}

function requiredCurrentEvidenceKeys(knobs: ResearchKnobs): string[] {
  return [
    ...new Set(
      Object.values(knobs.confidence_caps)
        .filter((policy) => policy.trigger === "missing_required_evidence")
        .flatMap((policy) => policy.required_evidence)
        .filter((key) => knobs.evidence_registry[key]?.current_data),
    ),
  ];
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

function attachVerifiedKnobAudit<T>(value: T, audit: ResearchKnobCapAudit): T {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  return {
    ...(value as Record<string, unknown>),
    verified_knob_audit: audit,
  } as T;
}

function stripRuntimeOwnedOutputEnvelope(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  const copy = { ...(value as Record<string, unknown>) };
  delete copy.verified_knob_audit;
  delete copy.verified_claim_graph;
  delete copy.verified_claim_audit;
  return copy;
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

function summarizeRuntimeSourceStatuses(
  statuses: ReadonlyArray<RuntimeSourceStatus>,
): ResearchKnobCapAudit["runtime_source_status_summary"] {
  return {
    loaded: statuses.filter((status) => status.status === "loaded").length,
    empty_confirmed: statuses.filter((status) => status.status === "empty_confirmed").length,
    missing: statuses.filter((status) => status.status === "missing").length,
    stale: statuses.filter((status) => status.status === "stale").length,
    source_error: statuses.filter((status) => status.status === "source_error").length,
  };
}

function summarizeEvidenceDependencyStatuses(
  statuses: ReadonlyArray<EvidenceDependencyStatus>,
): ResearchKnobCapAudit["evidence_dependency_status_summary"] {
  return {
    loaded: statuses.filter((status) => status.status === "loaded").length,
    partial_loaded: statuses.filter((status) => status.status === "partial_loaded").length,
    missing: statuses.filter((status) => status.status === "missing").length,
    stale: statuses.filter((status) => status.status === "stale").length,
    fallback: statuses.filter((status) => status.status === "fallback").length,
    tool_failed: statuses.filter((status) => status.status === "tool_failed").length,
  };
}

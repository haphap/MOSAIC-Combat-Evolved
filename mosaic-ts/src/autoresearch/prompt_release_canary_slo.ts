import { createHash } from "node:crypto";
import { z } from "zod";
import { ReleasePromptStageSchema } from "../agents/prompts/prompt_release_contract.js";

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);

export const PromptReleaseCanaryEventSchema = z
  .object({
    schema_version: z.literal("prompt_release_canary_event_v1"),
    event_id: z.string().min(1),
    release_id: z.string().min(1),
    account_mode: z.enum(["paper", "backtest", "live"]),
    traffic_percent: z.number().gt(0).lt(100),
    agent: z.string().min(1),
    stage: ReleasePromptStageSchema,
    stage_snapshot_hash: Sha256Schema,
    observed_at: z.string().datetime(),
    schema_failed: z.boolean(),
    fallback: z.boolean(),
    source_failed: z.boolean(),
    unsupported_influence_rejected: z.boolean(),
    validator_rejected: z.boolean(),
    latency_ms: z.number().nonnegative(),
    token_budget_breached: z.boolean(),
    duplicate_order_intent_count: z.number().int().min(0),
    exposure_breach_count: z.number().int().min(0),
  })
  .strict();

export type PromptReleaseCanaryEvent = z.infer<typeof PromptReleaseCanaryEventSchema>;

const CountByMetricSchema = z
  .object({
    schema_failure: z.number().int().min(0),
    fallback: z.number().int().min(0),
    source_failure: z.number().int().min(0),
    unsupported_influence_rejection: z.number().int().min(0),
    validator_rejection: z.number().int().min(0),
  })
  .strict();

const RuntimeSloMeasurementsSchema = z
  .object({
    sample_count: z.number().int().min(1),
    schema_failure_rate: z.number().min(0).max(1),
    fallback_rate: z.number().min(0).max(1),
    source_failure_rate: z.number().min(0).max(1),
    unsupported_influence_rejection_rate: z.number().min(0).max(1),
    validator_rejection_rate: z.number().min(0).max(1),
    latency_p95_ms: z.number().nonnegative(),
    token_budget_breach_count: z.number().int().min(0),
    duplicate_order_intent_count: z.number().int().min(0),
    exposure_breach_count: z.number().int().min(0),
  })
  .strict();

export const PromptReleaseCanarySloArtifactSchema = z
  .object({
    schema_version: z.literal("prompt_release_canary_slo_v1"),
    release_id: z.string().min(1),
    account_mode: z.enum(["paper", "backtest", "live"]),
    traffic_percent: z.number().gt(0).lt(100),
    canary_started_at: z.string().datetime(),
    observation_ended_at: z.string().datetime(),
    eligible_event_count: z.number().int().min(1),
    excluded_event_count: z.literal(0),
    excluded_count_by_reason: z.record(z.string(), z.number().int().min(0)),
    event_set_hash: Sha256Schema,
    stage_snapshot_hashes_hash: Sha256Schema,
    aggregator_id: z.literal("prompt_release_canary_slo"),
    aggregator_version: z.literal("1"),
    numerators: CountByMetricSchema,
    denominators: CountByMetricSchema,
    measurements: RuntimeSloMeasurementsSchema,
    artifact_hash: Sha256Schema,
  })
  .strict()
  .superRefine((artifact, ctx) => {
    if (artifact.eligible_event_count !== artifact.measurements.sample_count) {
      ctx.addIssue({
        code: "custom",
        path: ["eligible_event_count"],
        message: "eligible event count must equal measurement sample count",
      });
    }
    for (const value of Object.values(artifact.denominators)) {
      if (value !== artifact.eligible_event_count) {
        ctx.addIssue({
          code: "custom",
          path: ["denominators"],
          message: "every rate denominator must equal eligible event count",
        });
        break;
      }
    }
    if (artifact.artifact_hash !== promptReleaseCanarySloArtifactHash(artifact)) {
      ctx.addIssue({ code: "custom", path: ["artifact_hash"], message: "artifact hash mismatch" });
    }
  });

export type PromptReleaseCanarySloArtifact = z.infer<typeof PromptReleaseCanarySloArtifactSchema>;

export type PromptReleaseRuntimeSloMeasurements = z.infer<typeof RuntimeSloMeasurementsSchema>;

export function buildPromptReleaseCanarySloArtifact(opts: {
  releaseId: string;
  accountMode: "paper" | "backtest" | "live";
  trafficPercent: number;
  canaryStartedAt: string;
  observationEndedAt: string;
  stageSnapshotHashes: Readonly<Record<string, string>>;
  events: ReadonlyArray<unknown>;
}): PromptReleaseCanarySloArtifact {
  const events = opts.events.map((event) => PromptReleaseCanaryEventSchema.parse(event));
  if (events.length === 0) throw new Error("prompt_release_canary_slo_events_empty");
  const eventIds = new Set<string>();
  const canaryStart = Date.parse(opts.canaryStartedAt);
  const observationEnd = Date.parse(opts.observationEndedAt);
  if (
    !Number.isFinite(canaryStart) ||
    !Number.isFinite(observationEnd) ||
    observationEnd <= canaryStart
  ) {
    throw new Error("prompt_release_canary_slo_observation_window_invalid");
  }
  for (const event of events) {
    if (eventIds.has(event.event_id)) throw new Error("prompt_release_canary_slo_duplicate_event");
    eventIds.add(event.event_id);
    if (event.release_id !== opts.releaseId) {
      throw new Error("prompt_release_canary_slo_release_mismatch");
    }
    if (event.account_mode !== opts.accountMode) {
      throw new Error("prompt_release_canary_slo_account_mode_mismatch");
    }
    if (event.traffic_percent !== opts.trafficPercent) {
      throw new Error("prompt_release_canary_slo_traffic_mismatch");
    }
    const observedAt = Date.parse(event.observed_at);
    if (observedAt < canaryStart || observedAt > observationEnd) {
      throw new Error("prompt_release_canary_slo_event_outside_window");
    }
    const stageKey = `${event.agent}:${event.stage}`;
    if (opts.stageSnapshotHashes[stageKey] !== event.stage_snapshot_hash) {
      throw new Error(`prompt_release_canary_slo_stage_snapshot_mismatch:${stageKey}`);
    }
  }
  const sampleCount = events.length;
  const numerators = {
    schema_failure: count(events, (event) => event.schema_failed),
    fallback: count(events, (event) => event.fallback),
    source_failure: count(events, (event) => event.source_failed),
    unsupported_influence_rejection: count(events, (event) => event.unsupported_influence_rejected),
    validator_rejection: count(events, (event) => event.validator_rejected),
  };
  const denominators = {
    schema_failure: sampleCount,
    fallback: sampleCount,
    source_failure: sampleCount,
    unsupported_influence_rejection: sampleCount,
    validator_rejection: sampleCount,
  };
  const measurements: PromptReleaseRuntimeSloMeasurements = {
    sample_count: sampleCount,
    schema_failure_rate: numerators.schema_failure / sampleCount,
    fallback_rate: numerators.fallback / sampleCount,
    source_failure_rate: numerators.source_failure / sampleCount,
    unsupported_influence_rejection_rate: numerators.unsupported_influence_rejection / sampleCount,
    validator_rejection_rate: numerators.validator_rejection / sampleCount,
    latency_p95_ms: percentile95(events.map((event) => event.latency_ms)),
    token_budget_breach_count: count(events, (event) => event.token_budget_breached),
    duplicate_order_intent_count: events.reduce(
      (sum, event) => sum + event.duplicate_order_intent_count,
      0,
    ),
    exposure_breach_count: events.reduce((sum, event) => sum + event.exposure_breach_count, 0),
  };
  const withoutHash = {
    schema_version: "prompt_release_canary_slo_v1" as const,
    release_id: opts.releaseId,
    account_mode: opts.accountMode,
    traffic_percent: opts.trafficPercent,
    canary_started_at: new Date(canaryStart).toISOString(),
    observation_ended_at: new Date(observationEnd).toISOString(),
    eligible_event_count: sampleCount,
    excluded_event_count: 0 as const,
    excluded_count_by_reason: {},
    event_set_hash: canonicalHash(
      [...events].sort((left, right) => left.event_id.localeCompare(right.event_id)),
    ),
    stage_snapshot_hashes_hash: canonicalHash(opts.stageSnapshotHashes),
    aggregator_id: "prompt_release_canary_slo" as const,
    aggregator_version: "1" as const,
    numerators,
    denominators,
    measurements,
  };
  return PromptReleaseCanarySloArtifactSchema.parse({
    ...withoutHash,
    artifact_hash: canonicalHash(withoutHash),
  });
}

export function promptReleaseCanarySloArtifactHash(
  artifact: PromptReleaseCanarySloArtifact,
): string {
  const { artifact_hash: _ignored, ...withoutHash } = artifact;
  return canonicalHash(withoutHash);
}

export function stageSnapshotHashesHash(hashes: Readonly<Record<string, string>>): string {
  return canonicalHash(hashes);
}

function count(
  events: ReadonlyArray<PromptReleaseCanaryEvent>,
  predicate: (event: PromptReleaseCanaryEvent) => boolean,
): number {
  return events.reduce((total, event) => total + (predicate(event) ? 1 : 0), 0);
}

function percentile95(values: ReadonlyArray<number>): number {
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.max(0, Math.ceil(sorted.length * 0.95) - 1);
  return sorted[index] ?? 0;
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value === undefined ? null : value;
}

import { z } from "zod";

export const NO_EVALUATION_OBJECT_STAGE_SKIP_AGENT_IDS = [
  "druckenmiller",
  "munger",
  "burry",
  "ackman",
  "cro",
  "alpha_discovery",
  "autonomous_execution",
] as const;

export type NoEvaluationObjectStageSkipAgentId =
  (typeof NO_EVALUATION_OBJECT_STAGE_SKIP_AGENT_IDS)[number];

export const NoEvaluationObjectStageSkipRecordSchema = z
  .object({
    stage_skip_id: z.string().min(1),
    stage_skip_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    schema_version: z.literal("no_evaluation_object_stage_skip_v2"),
    graph_run_id: z.string().min(1),
    outcome_schedule_plan_id: z.string().min(1),
    outcome_schedule_slot_id: z.string().min(1),
    scheduled_sample_id: z.string().min(1),
    track_key_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    agent_id: z.enum(NO_EVALUATION_OBJECT_STAGE_SKIP_AGENT_IDS),
    skip_reason: z.literal("NO_EVALUATION_OBJECT"),
    frozen_object_set_id: z.string().min(1),
    frozen_object_set_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    member_count: z.literal(0),
    model_invoked: z.literal(false),
    eligibility_audit_id: z.string().min(1),
    eligibility_audit_revision_id: z.string().min(1),
    eligibility_audit_revision_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    evidence_ids: z.array(z.string().min(1)).min(1),
    causal_dedupe_key: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    recorded_at: z.string().min(1),
  })
  .strict();

export type NoEvaluationObjectStageSkipRecord = z.infer<
  typeof NoEvaluationObjectStageSkipRecordSchema
>;

export const KNOT_CONTROL_STAGE_SKIP_AGENT_IDS = [
  "alpha_discovery",
  "cro",
  "autonomous_execution",
] as const;

export type KnotControlStageSkipAgentId = (typeof KNOT_CONTROL_STAGE_SKIP_AGENT_IDS)[number];

export const KnotControlNoEvaluationObjectStageSkipRecordSchema = z
  .object({
    stage_skip_id: z.string().min(1),
    stage_skip_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    schema_version: z.literal("knot_control_no_evaluation_object_stage_skip_v2"),
    knot_pair_id: z.string().min(1),
    graph_run_id: z.string().min(1),
    run_slot_id: z.string().min(1),
    control_side: z.enum(["SHARED", "CHAMPION", "CANDIDATE"]),
    track_key_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    agent_id: z.enum(KNOT_CONTROL_STAGE_SKIP_AGENT_IDS),
    sample_origin: z.literal("KNOT_CONTROL_SHADOW"),
    skip_reason: z.literal("NO_EVALUATION_OBJECT"),
    frozen_object_set_id: z.string().min(1),
    frozen_object_set_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    member_count: z.literal(0),
    model_invoked: z.literal(false),
    operational_opportunity_audit_id: z.string().min(1),
    operational_opportunity_audit_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    evidence_ids: z.array(z.string().min(1)).min(1),
    causal_dedupe_key: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    recorded_at: z.string().min(1),
  })
  .strict()
  .superRefine((record, ctx) => {
    const expectedSides =
      record.agent_id === "alpha_discovery" ? ["SHARED"] : ["CHAMPION", "CANDIDATE"];
    if (!expectedSides.includes(record.control_side)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["control_side"],
        message: `${record.agent_id} cannot use ${record.control_side} control side`,
      });
    }
  });

export type KnotControlNoEvaluationObjectStageSkipRecord = z.infer<
  typeof KnotControlNoEvaluationObjectStageSkipRecordSchema
>;

export function parseOutcomeStageSkips(
  value: Readonly<Record<string, unknown>>,
): Partial<Record<NoEvaluationObjectStageSkipAgentId, NoEvaluationObjectStageSkipRecord>> {
  const result: Partial<
    Record<NoEvaluationObjectStageSkipAgentId, NoEvaluationObjectStageSkipRecord>
  > = {};
  for (const [agentId, raw] of Object.entries(value)) {
    const parsed = NoEvaluationObjectStageSkipRecordSchema.parse(raw);
    if (parsed.agent_id !== agentId) {
      throw new Error(`${agentId}: outcome stage-skip owner mismatch`);
    }
    result[parsed.agent_id] = parsed;
  }
  return result;
}

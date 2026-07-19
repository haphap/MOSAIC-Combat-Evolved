import { z } from "zod";
import { LlmResearchClaimSchema } from "../evidence_contract.js";
import { MacroInputAttributionSubmissionArraySchema } from "../helpers/macro_attribution.js";
import type {
  AlphaDiscoverySubmission,
  AutonomousExecutionSubmission,
  CioFinalSubmission,
  CioProposalSubmission,
  CroAgentSubmission,
} from "./accepted.js";

const LocalIdSchema = z.string().trim().min(1).max(128);
const TsCodeSchema = z.string().trim().min(1).max(32);
const ClaimRefsSchema = z.array(LocalIdSchema).min(1);
const ConfidenceSchema = z.number().min(0).max(1);

const DriverSchema = z
  .object({
    driver_local_id: LocalIdSchema,
    summary: z.string().trim().min(1),
    claim_refs: ClaimRefsSchema,
  })
  .strict();

const RiskSchema = z
  .object({
    risk_local_id: LocalIdSchema,
    summary: z.string().trim().min(1),
    claim_refs: ClaimRefsSchema,
  })
  .strict();

const ClaimsFields = {
  claims: z.array(LlmResearchClaimSchema).min(1),
  claim_refs: ClaimRefsSchema,
};

const CroActionSchema = z
  .object({
    action_local_id: LocalIdSchema,
    candidate_ref: LocalIdSchema,
    ts_code: TsCodeSchema,
    action: z.enum(["VETO", "CAP_WEIGHT", "REDUCE_WEIGHT", "REQUIRE_REVIEW", "NO_OBJECTION"]),
    predicted_risk_probability: ConfidenceSchema,
    max_target_weight: z.number().min(0).max(1).nullable(),
    reason: z.string().trim().min(1),
    claim_refs: ClaimRefsSchema,
  })
  .strict()
  .superRefine((action, ctx) => {
    if (action.action === "VETO" && action.max_target_weight !== 0) {
      issue(ctx, ["max_target_weight"], "VETO requires max_target_weight=0");
    }
    if (
      (action.action === "NO_OBJECTION" || action.action === "REQUIRE_REVIEW") &&
      action.max_target_weight !== null
    ) {
      issue(ctx, ["max_target_weight"], `${action.action} requires max_target_weight=null`);
    }
    if (
      (action.action === "CAP_WEIGHT" || action.action === "REDUCE_WEIGHT") &&
      action.max_target_weight === null
    ) {
      issue(ctx, ["max_target_weight"], `${action.action} requires a numeric max_target_weight`);
    }
  });

export const CroSubmissionSchema = z
  .object({
    agent_id: z.literal("cro"),
    review_disposition: z.enum(["REVIEW_ACTIONS", "NO_OBJECTION", "BLOCK_ALL"]),
    candidate_actions: z.array(CroActionSchema).max(50),
    correlated_risks: z.array(RiskSchema).max(10),
    black_swan_scenarios: z.array(RiskSchema).max(10),
    confidence: ConfidenceSchema,
    macro_input_attributions: MacroInputAttributionSubmissionArraySchema,
    ...ClaimsFields,
  })
  .strict()
  .superRefine((submission, ctx) => {
    uniqueFields(
      submission.candidate_actions,
      ["action_local_id", "candidate_ref", "ts_code"],
      "candidate_actions",
      ctx,
    );
    uniqueFields(submission.correlated_risks, ["risk_local_id"], "correlated_risks", ctx);
    uniqueFields(submission.black_swan_scenarios, ["risk_local_id"], "black_swan_scenarios", ctx);
    const derived =
      submission.candidate_actions.length > 0 &&
      submission.candidate_actions.every((action) => action.action === "VETO")
        ? "BLOCK_ALL"
        : submission.candidate_actions.every((action) => action.action === "NO_OBJECTION")
          ? "NO_OBJECTION"
          : "REVIEW_ACTIONS";
    if (submission.review_disposition !== derived) {
      issue(
        ctx,
        ["review_disposition"],
        `review_disposition must be deterministically derived as ${derived}`,
      );
    }
    validateClaimOwnership(submission, ctx);
  });

const AlphaPickSchema = z
  .object({
    pick_local_id: LocalIdSchema,
    candidate_ref: LocalIdSchema,
    ts_code: TsCodeSchema,
    conviction: ConfidenceSchema,
    thesis: z.string().trim().min(1),
    claim_refs: ClaimRefsSchema,
  })
  .strict();

export interface FrozenAlphaCandidate {
  candidate_ref: string;
  ts_code: string;
}

const AlphaBase = z.object({
  agent_id: z.literal("alpha_discovery"),
  confidence: ConfidenceSchema,
  key_drivers: z.array(DriverSchema).max(10),
  risks: z.array(RiskSchema).max(10),
  macro_input_attributions: MacroInputAttributionSubmissionArraySchema,
  ...ClaimsFields,
});

export const AlphaDiscoverySubmissionSchema = z
  .discriminatedUnion("discovery_disposition", [
    AlphaBase.extend({
      discovery_disposition: z.literal("CANDIDATES"),
      novel_picks: z.array(AlphaPickSchema).min(1).max(10),
    }).strict(),
    AlphaBase.extend({
      discovery_disposition: z.literal("NONE_FOUND"),
      novel_picks: z.tuple([]),
    }).strict(),
  ])
  .superRefine(validateAlphaSubmission);

/** Freeze Alpha picks to exact candidate_ref/ts_code pairs from the role snapshot. */
export function buildRuntimeAlphaDiscoverySubmissionSchema(
  candidates: readonly FrozenAlphaCandidate[],
): z.ZodType<AlphaDiscoverySubmission> {
  const noneFound = AlphaBase.extend({
    discovery_disposition: z.literal("NONE_FOUND"),
    novel_picks: z.tuple([]),
  }).strict();
  if (candidates.length === 0) {
    return noneFound.superRefine(validateAlphaSubmission) as z.ZodType<AlphaDiscoverySubmission>;
  }
  const variants = candidates.map((candidate) =>
    z
      .object({
        pick_local_id: LocalIdSchema,
        candidate_ref: z.literal(candidate.candidate_ref),
        ts_code: z.literal(candidate.ts_code),
        conviction: ConfidenceSchema,
        thesis: z.string().trim().min(1),
        claim_refs: ClaimRefsSchema,
      })
      .strict(),
  );
  const onlyVariant = variants.length === 1 ? variants[0] : undefined;
  const runtimePick = onlyVariant
    ? onlyVariant
    : z.union(
        variants as [
          (typeof variants)[number],
          (typeof variants)[number],
          ...(typeof variants)[number][],
        ],
      );
  const withCandidates = AlphaBase.extend({
    discovery_disposition: z.literal("CANDIDATES"),
    novel_picks: z.array(runtimePick).min(1).max(Math.min(10, candidates.length)),
  }).strict();
  return z
    .discriminatedUnion("discovery_disposition", [withCandidates, noneFound])
    .superRefine(validateAlphaSubmission) as z.ZodType<AlphaDiscoverySubmission>;
}

function validateAlphaSubmission(submission: unknown, ctx: z.RefinementCtx): void {
  const record = submission as {
    novel_picks: Array<Record<string, unknown>>;
    key_drivers: Array<Record<string, unknown>>;
    risks: Array<Record<string, unknown>>;
    claims: Array<{ claim_id: string }>;
    claim_refs: string[];
    [key: string]: unknown;
  };
  uniqueFields(
    record.novel_picks,
    ["pick_local_id", "candidate_ref", "ts_code"],
    "novel_picks",
    ctx,
  );
  uniqueFields(record.key_drivers, ["driver_local_id"], "key_drivers", ctx);
  uniqueFields(record.risks, ["risk_local_id"], "risks", ctx);
  validateClaimOwnership(record, ctx);
}

const ExecutionAssessmentSchema = z
  .object({
    assessment_local_id: LocalIdSchema,
    order_intent_ref: LocalIdSchema,
    ts_code: TsCodeSchema,
    requested_delta_weight: z
      .number()
      .min(-1)
      .max(1)
      .refine((value) => value !== 0, {
        message: "requested_delta_weight must be non-zero",
      }),
    feasibility: z.enum(["FEASIBLE", "PARTIAL", "BLOCKED"]),
    feasibility_confidence: ConfidenceSchema,
    predicted_cost_bps: z.number().min(0),
    max_executable_delta_weight: z.number().min(0).max(1).nullable(),
    recommended_slice_count: z.number().int().min(0),
    reason: z.string().trim().min(1),
    claim_refs: ClaimRefsSchema,
  })
  .strict()
  .superRefine((assessment, ctx) => {
    const requested = Math.abs(assessment.requested_delta_weight);
    const executable = assessment.max_executable_delta_weight;
    if (assessment.feasibility === "BLOCKED") {
      if (executable !== 0) {
        issue(ctx, ["max_executable_delta_weight"], "BLOCKED requires executable delta 0");
      }
      if (assessment.recommended_slice_count !== 0) {
        issue(ctx, ["recommended_slice_count"], "BLOCKED requires zero slices");
      }
    } else if (assessment.feasibility === "PARTIAL") {
      if (executable === null || executable <= 0 || executable >= requested) {
        issue(
          ctx,
          ["max_executable_delta_weight"],
          "PARTIAL executable delta must be strictly between zero and requested delta",
        );
      }
      if (assessment.recommended_slice_count < 1) {
        issue(ctx, ["recommended_slice_count"], "PARTIAL requires at least one slice");
      }
    } else {
      if (executable === null || executable < requested) {
        issue(
          ctx,
          ["max_executable_delta_weight"],
          "FEASIBLE executable delta cannot be below the requested delta",
        );
      }
      if (assessment.recommended_slice_count < 1) {
        issue(ctx, ["recommended_slice_count"], "FEASIBLE requires at least one slice");
      }
    }
  });

const ExecutionBase = z.object({
  agent_id: z.literal("autonomous_execution"),
  confidence: ConfidenceSchema,
  order_assessments: z
    .tuple([ExecutionAssessmentSchema])
    .rest(ExecutionAssessmentSchema)
    .refine((rows) => rows.length <= 50, { message: "order_assessments cannot exceed 50" }),
  ...ClaimsFields,
});

export const AutonomousExecutionSubmissionSchema = z
  .discriminatedUnion("execution_disposition", [
    ExecutionBase.extend({ execution_disposition: z.literal("ORDERS_ASSESSED") }).strict(),
    ExecutionBase.extend({ execution_disposition: z.literal("BLOCKED") }).strict(),
  ])
  .superRefine((submission, ctx) => {
    uniqueFields(
      submission.order_assessments,
      ["assessment_local_id", "order_intent_ref", "ts_code"],
      "order_assessments",
      ctx,
    );
    const allBlocked = submission.order_assessments.every(
      (assessment) => assessment.feasibility === "BLOCKED",
    );
    if ((submission.execution_disposition === "BLOCKED") !== allBlocked) {
      issue(
        ctx,
        ["execution_disposition"],
        "BLOCKED is required exactly when every order assessment is blocked",
      );
    }
    validateClaimOwnership(submission, ctx);
  });

const CioPositionSchema = z
  .object({
    position_local_id: LocalIdSchema,
    ts_code: TsCodeSchema,
    target_weight: z.number().min(0).max(1),
    position_decision: z.enum(["HOLD", "ADD", "REDUCE", "EXIT"]),
    holding_period: z.enum(["DAYS", "WEEKS", "MONTHS"]),
    thesis_status: z.enum(["INTACT", "WEAKENED", "BROKEN", "EXPIRED"]),
    risk_flags: z.array(z.string().trim().min(1)).max(20),
    claim_refs: ClaimRefsSchema,
  })
  .strict()
  .superRefine((position, ctx) => {
    if (position.position_decision === "EXIT" && position.target_weight !== 0) {
      issue(ctx, ["target_weight"], "EXIT requires target_weight=0");
    }
  });

const CioDecisionBase = z.object({
  agent_id: z.literal("cio"),
  confidence: ConfidenceSchema,
  cash_weight: z.number().min(0).max(1),
  decision_reason: z.string().trim().min(1),
  target_positions: z.array(CioPositionSchema).max(50),
  macro_input_attributions: MacroInputAttributionSubmissionArraySchema,
  ...ClaimsFields,
});

const CioProposalBase = CioDecisionBase.extend({ decision_stage: z.literal("PROPOSAL") });

const CioProposalTarget = CioProposalBase.extend({
  decision_disposition: z.literal("TARGET_PORTFOLIO"),
  target_positions: z.array(CioPositionSchema).min(1).max(50),
}).strict();
const CioProposalHold = CioProposalBase.extend({
  decision_disposition: z.literal("HOLD_CURRENT"),
}).strict();
const CioProposalCash = CioProposalBase.extend({
  decision_disposition: z.literal("ALL_CASH"),
  target_positions: z.tuple([]),
  cash_weight: z.literal(1),
}).strict();

export const CioProposalSubmissionSchema = z
  .discriminatedUnion("decision_disposition", [CioProposalTarget, CioProposalHold, CioProposalCash])
  .superRefine(validateCioSubmission);

export const CioProposalWithoutHoldSubmissionSchema = z
  .discriminatedUnion("decision_disposition", [CioProposalTarget, CioProposalCash])
  .superRefine(validateCioSubmission);

export const CioProposalAllCashSubmissionSchema =
  CioProposalCash.superRefine(validateCioSubmission);

const CroResolutionSchema = z
  .object({
    cro_action_local_ref: LocalIdSchema,
    resolution: z.enum(["COMPLIED", "MORE_CONSERVATIVE"]),
    reason: z.string().trim().min(1),
    claim_refs: ClaimRefsSchema,
  })
  .strict();

const ExecutionResolutionSchema = z
  .object({
    execution_assessment_local_ref: LocalIdSchema,
    resolution: z.enum(["COMPLIED", "MORE_CONSERVATIVE"]),
    reason: z.string().trim().min(1),
    claim_refs: ClaimRefsSchema,
  })
  .strict();

const CioFinalBase = CioDecisionBase.extend({
  decision_stage: z.literal("FINAL"),
  cro_control_resolutions: z.array(CroResolutionSchema).max(50),
  execution_control_resolutions: z.array(ExecutionResolutionSchema).max(50),
});

const CioFinalTarget = CioFinalBase.extend({
  decision_disposition: z.literal("TARGET_PORTFOLIO"),
  target_positions: z.array(CioPositionSchema).min(1).max(50),
}).strict();
const CioFinalHold = CioFinalBase.extend({
  decision_disposition: z.literal("HOLD_CURRENT"),
}).strict();
const CioFinalCash = CioFinalBase.extend({
  decision_disposition: z.literal("ALL_CASH"),
  target_positions: z.tuple([]),
  cash_weight: z.literal(1),
}).strict();

export const CioFinalSubmissionSchema = z
  .discriminatedUnion("decision_disposition", [CioFinalTarget, CioFinalHold, CioFinalCash])
  .superRefine((submission, ctx) => {
    validateCioSubmission(submission, ctx);
    uniqueFields(
      submission.cro_control_resolutions,
      ["cro_action_local_ref"],
      "cro_control_resolutions",
      ctx,
    );
    uniqueFields(
      submission.execution_control_resolutions,
      ["execution_assessment_local_ref"],
      "execution_control_resolutions",
      ctx,
    );
  });

export const CioFinalWithoutHoldSubmissionSchema = z
  .discriminatedUnion("decision_disposition", [CioFinalTarget, CioFinalCash])
  .superRefine((submission, ctx) => {
    validateCioSubmission(submission, ctx);
    uniqueFields(
      submission.cro_control_resolutions,
      ["cro_action_local_ref"],
      "cro_control_resolutions",
      ctx,
    );
    uniqueFields(
      submission.execution_control_resolutions,
      ["execution_assessment_local_ref"],
      "execution_control_resolutions",
      ctx,
    );
  });

export const CioFinalAllCashSubmissionSchema = CioFinalCash.superRefine((submission, ctx) => {
  validateCioSubmission(submission, ctx);
  uniqueFields(
    submission.cro_control_resolutions,
    ["cro_action_local_ref"],
    "cro_control_resolutions",
    ctx,
  );
  uniqueFields(
    submission.execution_control_resolutions,
    ["execution_assessment_local_ref"],
    "execution_control_resolutions",
    ctx,
  );
});

function validateCioSubmission(
  submission: z.infer<typeof CioDecisionBase> & { decision_disposition: string },
  ctx: z.RefinementCtx,
): void {
  uniqueFields(
    submission.target_positions,
    ["position_local_id", "ts_code"],
    "target_positions",
    ctx,
  );
  const total =
    submission.cash_weight +
    submission.target_positions.reduce((sum, position) => sum + position.target_weight, 0);
  if (Math.abs(total - 1) > 1e-9) {
    issue(ctx, ["cash_weight"], `target weights plus cash must equal 1, received ${total}`);
  }
  validateClaimOwnership(submission, ctx);
}

function validateClaimOwnership(
  submission: {
    claims: Array<{ claim_id: string }>;
    claim_refs: string[];
    [key: string]: unknown;
  },
  ctx: z.RefinementCtx,
): void {
  const owned = new Set(submission.claims.map((claim) => claim.claim_id));
  const refs = collectClaimRefs(submission);
  for (const ref of refs) {
    if (!owned.has(ref)) issue(ctx, ["claim_refs"], `unresolved submission claim ref ${ref}`);
  }
}

function collectClaimRefs(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap(collectClaimRefs);
  if (value === null || typeof value !== "object") return [];
  const refs: string[] = [];
  for (const [key, item] of Object.entries(value)) {
    if (key === "macro_input_attributions" || key === "claims") continue;
    if (key === "claim_refs" && Array.isArray(item)) {
      refs.push(...item.filter((ref): ref is string => typeof ref === "string"));
    } else {
      refs.push(...collectClaimRefs(item));
    }
  }
  return refs;
}

function uniqueFields<T extends Record<string, unknown>>(
  rows: readonly T[],
  fields: readonly (keyof T)[],
  path: string,
  ctx: z.RefinementCtx,
): void {
  for (const field of fields) {
    const seen = new Set<unknown>();
    rows.forEach((row, index) => {
      if (seen.has(row[field])) {
        issue(ctx, [path, index, String(field)], `${String(field)} must be unique`);
      }
      seen.add(row[field]);
    });
  }
}

function issue(ctx: z.RefinementCtx, path: PropertyKey[], message: string): void {
  ctx.addIssue({ code: "custom", path, message });
}

type Assignable<T, U> = T extends U ? true : never;
const croGuard: Assignable<z.infer<typeof CroSubmissionSchema>, CroAgentSubmission> = true;
const alphaGuard: Assignable<
  z.infer<typeof AlphaDiscoverySubmissionSchema>,
  AlphaDiscoverySubmission
> = true;
const executionGuard: Assignable<
  z.infer<typeof AutonomousExecutionSubmissionSchema>,
  AutonomousExecutionSubmission
> = true;
const proposalGuard: Assignable<
  z.infer<typeof CioProposalSubmissionSchema>,
  CioProposalSubmission
> = true;
const finalGuard: Assignable<z.infer<typeof CioFinalSubmissionSchema>, CioFinalSubmission> = true;
void croGuard;
void alphaGuard;
void executionGuard;
void proposalGuard;
void finalGuard;

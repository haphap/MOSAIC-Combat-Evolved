/**
 * Zod schemas for Layer-4 decision agents (Plan §5.4).
 *
 * 4 distinct shapes — no shared schema factory like Layer-3. Each agent has
 * different structure:
 *   - cro:                 rejected_picks + correlated_risks + black_swan_scenarios
 *   - alpha_discovery:     novel_picks
 *   - autonomous_execution: trades
 *   - cio:                 portfolio_actions (target_weight sum check)
 */

import { z } from "zod";
import { LlmResearchClaimSchema } from "../evidence_contract.js";
import type {
  AlphaDiscoveryOutput,
  AutoExecOutput,
  CioFinalOutput,
  CioOutput,
  CioProposalOutput,
  CroOutput,
} from "../types.js";

const KEY_DRIVERS_OPTIONAL_NOTE = "key_drivers may be omitted on Layer 4 (synthesis-only).";

const HOLDING_PERIOD = z.enum(["1W", "1M", "3M", "6M", "1Y", "5Y+"]);

const KNOB_INFLUENCE_FIELDS = {
  declared_knob_influence_ids: z
    .array(z.string().min(1))
    .optional()
    .describe("Visible domain knob card ids explicitly used in this conclusion."),
  declared_influence_rationale: z
    .string()
    .optional()
    .describe("Optional short rationale for declared knob influence ids."),
  claims: z
    .array(LlmResearchClaimSchema)
    .min(1)
    .describe("Claim declarations referencing only runtime-provided evidence ids."),
  claim_refs: z
    .array(z.string().min(1))
    .min(1)
    .describe("Claim ids supporting the top-level decision conclusion."),
};

const CLAIM_REFS = z
  .array(z.string().min(1))
  .min(1)
  .optional()
  .describe("Claim ids supporting this output entry; required by the enabled evidence gate.");

const REQUIRED_CLAIM_REFS = z
  .array(z.string().min(1))
  .min(1)
  .describe("Claim ids supporting this CIO decision entry.");

// ---------------------------------------------------------------------------
// 1. cro
// ---------------------------------------------------------------------------

export const CroSchema = z
  .object({
    agent: z.literal("cro"),
    review_disposition: z.enum(["REVIEW_ACTIONS", "NO_OBJECTION", "BLOCK_ALL"]),
    rejected_picks: z
      .array(
        z.object({
          ticker: z
            .string()
            .min(1)
            .describe(
              "MOSAIC ticker rejected from the upstream pick set. Must reference a ticker " +
                "that appeared in layer2_outputs.* or layer3_outputs.*.",
            ),
          reason: z
            .string()
            .min(1)
            .describe(
              "Concrete risk: regulatory / liquidity / valuation / correlation / black-swan exposure.",
            ),
          claim_refs: CLAIM_REFS,
        }),
      )
      .max(20)
      .describe("Picks rejected after risk review. Empty if upstream looks clean."),
    required_adjustments: z
      .array(
        z.object({
          ticker: z.string().min(1),
          adjustment: z.enum(["VETO", "CAP_WEIGHT", "REDUCE_WEIGHT", "REQUIRE_REVIEW"]),
          max_target_weight: z.number().min(0).max(1).optional(),
          reason: z.string().min(1),
          claim_refs: CLAIM_REFS,
        }),
      )
      .max(20)
      .optional(),
    correlated_risks: z
      .array(z.string().min(1))
      .max(10)
      .describe(
        "Cross-pick correlations the upstream agents missed (e.g. '3 picks all in semi-equipment chain').",
      ),
    black_swan_scenarios: z
      .array(z.string().min(1))
      .max(5)
      .describe("Tail-risk scenarios that would invalidate the current picks."),
    confidence: z.number().min(0).max(1),
    ...KNOB_INFLUENCE_FIELDS,
  })
  .describe(
    "Layer-4 chief risk officer adversarial review. Reads L1+L2+L3 fully and " +
      "raises objections. Empty rejected_picks is allowed when the upstream is clean.",
  )
  .superRefine((value, ctx) => {
    const actionCount = value.rejected_picks.length + (value.required_adjustments?.length ?? 0);
    if (value.review_disposition === "NO_OBJECTION" && actionCount !== 0) {
      ctx.addIssue({
        code: "custom",
        path: ["review_disposition"],
        message: "NO_OBJECTION requires no rejected picks or required adjustments",
      });
    }
    if (value.review_disposition !== "NO_OBJECTION" && actionCount === 0) {
      ctx.addIssue({
        code: "custom",
        path: ["review_disposition"],
        message: "REVIEW_ACTIONS/BLOCK_ALL requires at least one structured review action",
      });
    }
    addDuplicateTickerIssues(value.rejected_picks, "rejected_picks", ctx);
    addDuplicateTickerIssues(value.required_adjustments ?? [], "required_adjustments", ctx);
    for (const [index, adjustment] of (value.required_adjustments ?? []).entries()) {
      if (
        (adjustment.adjustment === "CAP_WEIGHT" || adjustment.adjustment === "REDUCE_WEIGHT") &&
        adjustment.max_target_weight === undefined
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["required_adjustments", index, "max_target_weight"],
          message: `${adjustment.adjustment} requires max_target_weight`,
        });
      }
      if (adjustment.adjustment === "VETO" && (adjustment.max_target_weight ?? 0) > 1e-9) {
        ctx.addIssue({
          code: "custom",
          path: ["required_adjustments", index, "max_target_weight"],
          message: "VETO max_target_weight must be zero when supplied",
        });
      }
      if (
        adjustment.adjustment === "REQUIRE_REVIEW" &&
        adjustment.max_target_weight !== undefined
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["required_adjustments", index, "max_target_weight"],
          message: "REQUIRE_REVIEW must not set max_target_weight",
        });
      }
    }
    if (!value.claims || value.rejected_picks.length === 0) return;
    const vetoed = new Set(
      (value.required_adjustments ?? [])
        .filter((adjustment) => adjustment.adjustment === "VETO")
        .map((adjustment) => adjustment.ticker),
    );
    for (const rejected of value.rejected_picks) {
      if (vetoed.has(rejected.ticker)) continue;
      ctx.addIssue({
        code: "custom",
        path: ["required_adjustments"],
        message: `rejected ticker ${rejected.ticker} requires a structured VETO adjustment`,
      });
    }
  });

export const CRO_FIELD_NAMES = [
  "review_disposition",
  "rejected_picks",
  "correlated_risks",
  "black_swan_scenarios",
  "required_adjustments",
  "confidence",
  "claims",
  "claim_refs",
] as const;

// ---------------------------------------------------------------------------
// 2. alpha_discovery
// ---------------------------------------------------------------------------

export const AlphaDiscoverySchema = z
  .object({
    agent: z.literal("alpha_discovery"),
    discovery_disposition: z.enum(["CANDIDATES", "NONE_FOUND"]),
    novel_picks: z
      .array(
        z.object({
          ticker: z
            .string()
            .min(1)
            .describe(
              "Ticker not in any of the 4 superinvestor outputs — but visible in L1/L2 signals.",
            ),
          why_missed_by_others: z
            .string()
            .min(1)
            .describe(
              "Why this pick fell through the philosophy filters above. Concrete reasoning, no fluff.",
            ),
          claim_refs: CLAIM_REFS,
        }),
      )
      .max(10)
      .describe("Cross-cutting picks the 4 superinvestors collectively missed."),
    confidence: z.number().min(0).max(1),
    ...KNOB_INFLUENCE_FIELDS,
  })
  .superRefine((value, ctx) => {
    if ((value.discovery_disposition === "CANDIDATES") !== value.novel_picks.length > 0) {
      ctx.addIssue({
        code: "custom",
        path: ["discovery_disposition"],
        message: "CANDIDATES requires novel_picks; empty novel_picks requires NONE_FOUND",
      });
    }
  })
  .describe(
    "Layer-4 alpha discovery — finds picks that fall between superinvestor philosophies. " +
      "Empty novel_picks is the most common outcome and is fine.",
  );

export const ALPHA_DISCOVERY_FIELD_NAMES = [
  "discovery_disposition",
  "novel_picks",
  "confidence",
  "claims",
  "claim_refs",
] as const;

// ---------------------------------------------------------------------------
// 3. autonomous_execution
// ---------------------------------------------------------------------------

export const AutonomousExecutionSchema = z
  .object({
    agent: z.literal("autonomous_execution"),
    execution_disposition: z.enum(["TRADES", "NO_DELTA", "BLOCKED"]),
    trades: z
      .array(
        z.object({
          ticker: z.string().min(1),
          action: z.enum(["BUY", "SELL", "HOLD", "REDUCE"]),
          size_pct: z
            .number()
            .min(0)
            .max(1)
            .describe("[0, 1] portion of the long sleeve to allocate. 0 = pass."),
          delta_weight: z
            .number()
            .min(-1)
            .max(1)
            .optional()
            .describe("Optional target-current trade delta when candidate target state exists."),
          estimated_slippage_pct: z
            .number()
            .min(0)
            .max(1)
            .optional()
            .describe("Optional expected execution slippage as a portfolio-weight ratio."),
          liquidity_score: z
            .number()
            .min(0)
            .max(1)
            .optional()
            .describe("Optional executable liquidity score; higher is more liquid."),
          order_split_count: z
            .number()
            .int()
            .min(1)
            .max(100)
            .optional()
            .describe("Optional number of order slices planned for this ticker."),
          conviction: z.number().min(0).max(1),
          claim_refs: CLAIM_REFS,
        }),
      )
      .max(20)
      .describe("Per-ticker trade decisions; HOLD picks at zero size also fine."),
    execution_checks: z
      .array(
        z.object({
          ticker: z.string().min(1),
          status: z.enum(["feasible", "partial", "blocked"]),
          estimated_cost_bps: z.number().min(0),
          max_executable_delta_weight: z.number().min(0).max(1).optional(),
          reason: z.string().min(1),
          claim_refs: CLAIM_REFS,
        }),
      )
      .max(20)
      .optional(),
    execution_enforcement: z
      .object({
        checked_trade_count: z.number().int().min(0),
        active_policy_ids: z.array(z.string().min(1)),
        min_delta_trade_weight: z.number().optional(),
        slippage_cap: z.number().optional(),
        liquidity_floor: z.number().optional(),
      })
      .optional(),
    confidence: z.number().min(0).max(1),
    ...KNOB_INFLUENCE_FIELDS,
  })
  .describe(
    "Layer-4 autonomous execution. Translates L3 picks + cro / alpha into concrete trade actions. " +
      "Darwinian weights are stubbed at uniform = 1/N until Phase 3 scorecard lands.",
  )
  .superRefine((value, ctx) => {
    if (value.execution_disposition === "TRADES" && value.trades.length === 0) {
      ctx.addIssue({
        code: "custom",
        path: ["execution_disposition"],
        message: "TRADES requires at least one trade",
      });
    }
    if (value.execution_disposition !== "TRADES" && value.trades.length !== 0) {
      ctx.addIssue({
        code: "custom",
        path: ["execution_disposition"],
        message: "NO_DELTA/BLOCKED requires an empty trades array",
      });
    }
    addDuplicateTickerIssues(value.trades, "trades", ctx);
    addDuplicateTickerIssues(value.execution_checks ?? [], "execution_checks", ctx);
    for (const [index, check] of (value.execution_checks ?? []).entries()) {
      if (check.status === "partial" && check.max_executable_delta_weight === undefined) {
        ctx.addIssue({
          code: "custom",
          path: ["execution_checks", index, "max_executable_delta_weight"],
          message: "partial execution requires max_executable_delta_weight",
        });
      }
      if (check.status === "blocked" && (check.max_executable_delta_weight ?? 0) > 1e-9) {
        ctx.addIssue({
          code: "custom",
          path: ["execution_checks", index, "max_executable_delta_weight"],
          message: "blocked execution must have zero executable delta",
        });
      }
    }
    if (!value.claims || value.trades.length === 0) return;
    const checked = new Set((value.execution_checks ?? []).map((check) => check.ticker));
    for (const trade of value.trades) {
      if (checked.has(trade.ticker)) continue;
      ctx.addIssue({
        code: "custom",
        path: ["execution_checks"],
        message: `trade ${trade.ticker} requires a structured execution check`,
      });
    }
  });

export const AUTONOMOUS_EXECUTION_FIELD_NAMES = [
  "execution_disposition",
  "trades",
  "execution_checks",
  "confidence",
  "claims",
  "claim_refs",
] as const;

// ---------------------------------------------------------------------------
// 4. cio (most strict)
// ---------------------------------------------------------------------------

const POSITION_REVIEW_SCHEMA = z.object({
  ticker: z.string().min(1),
  decision: z.enum(["HOLD", "ADD", "REDUCE", "EXIT"]),
  target_weight: z.number().min(0).max(1),
  reason: z.string().min(1),
  thesis_status: z.enum(["intact", "weakened", "broken", "expired"]),
  risk_flags: z.array(z.string().min(1)),
  confidence: z.number().min(0).max(1),
  review_source: z.literal("llm").optional(),
  claim_refs: REQUIRED_CLAIM_REFS,
});

const DISSENT_REF_SCHEMA = z.object({
  ticker: z.string().min(1),
  source: z.enum(["cro_review", "execution_feasibility"]),
  source_hash: z.string().min(1),
  reason: z.string().min(1),
});

const CIO_BASE_SCHEMA = z.object({
  agent: z.literal("cio"),
  decision_disposition: z.enum(["TARGET_PORTFOLIO", "HOLD_CURRENT", "ALL_CASH"]),
  decision_reason: z.string().min(1),
  decision_claim_refs: REQUIRED_CLAIM_REFS,
  portfolio_actions: z
    .array(
      z.object({
        ticker: z.string().min(1),
        action: z.enum(["BUY", "SELL", "HOLD", "REDUCE"]),
        sector: z.string().min(1).optional(),
        position_decision: z.enum(["HOLD", "ADD", "REDUCE", "EXIT"]).optional(),
        current_weight: z.number().min(0).max(1).optional(),
        target_weight: z
          .number()
          .min(0)
          .max(1)
          .describe("[0, 1] target portfolio weight after this action."),
        delta_weight: z.number().min(-1).max(1).optional(),
        holding_period: HOLDING_PERIOD,
        position_decision_reason: z.string().optional(),
        override_reason: z.string().optional(),
        thesis_status: z.enum(["intact", "weakened", "broken", "expired"]).optional(),
        risk_flags: z.array(z.string().min(1)).optional(),
        dissent_notes: z
          .string()
          .describe(
            "Empty when CIO matches autonomous_execution; non-empty when CIO overrides " +
              "(must explain why).",
          ),
        claim_refs: REQUIRED_CLAIM_REFS,
      }),
    )
    .max(15),
  confidence: z.number().min(0).max(1),
  ...KNOB_INFLUENCE_FIELDS,
  claims: z
    .array(LlmResearchClaimSchema)
    .min(1)
    .describe("CIO must explain both actions and intentional cash decisions with evidence claims."),
});

function validateCioWeights(
  val: {
    decision_disposition: "TARGET_PORTFOLIO" | "HOLD_CURRENT" | "ALL_CASH";
    portfolio_actions: Array<{ ticker: string; target_weight: number }>;
  },
  ctx: z.RefinementCtx,
): void {
  addDuplicateTickerIssues(val.portfolio_actions, "portfolio_actions", ctx);
  const total = val.portfolio_actions.reduce((sum, action) => sum + action.target_weight, 0);
  if (total > 1 + 1e-6) {
    ctx.addIssue({
      code: "custom",
      message: `portfolio_actions target_weight sum ${total.toFixed(6)} exceeds 1.0 + epsilon; reduce allocations.`,
    });
  }
  if (val.decision_disposition === "TARGET_PORTFOLIO" && val.portfolio_actions.length === 0) {
    ctx.addIssue({
      code: "custom",
      path: ["decision_disposition"],
      message: "TARGET_PORTFOLIO requires a complete non-empty target portfolio",
    });
  }
  if (
    val.decision_disposition === "ALL_CASH" &&
    val.portfolio_actions.some((action) => action.target_weight > 1e-9)
  ) {
    ctx.addIssue({
      code: "custom",
      path: ["portfolio_actions"],
      message: "ALL_CASH actions must target zero weight",
    });
  }
}

function addDuplicateTickerIssues(
  entries: ReadonlyArray<{ ticker: string }>,
  field: string,
  ctx: z.RefinementCtx,
): void {
  const seen = new Set<string>();
  entries.forEach((entry, index) => {
    if (seen.has(entry.ticker)) {
      ctx.addIssue({
        code: "custom",
        path: [field, index, "ticker"],
        message: `duplicate ticker ${entry.ticker}`,
      });
    }
    seen.add(entry.ticker);
  });
}

export const CioSchema = CIO_BASE_SCHEMA.superRefine(validateCioWeights).describe(
  "Layer-4 CIO final decision. portfolio_actions weights must not exceed 1.0 + 1e-6; " +
    "the CIO is intentionally holding cash (acceptable when regime BEARISH + low confidence).",
);

export const CioProposalSchema = CIO_BASE_SCHEMA.extend({
  position_reviews: z.array(POSITION_REVIEW_SCHEMA),
  dissent_refs: z.array(DISSENT_REF_SCHEMA).optional(),
})
  .superRefine((value, ctx) => {
    validateCioWeights(value, ctx);
    addDuplicateTickerIssues(value.position_reviews, "position_reviews", ctx);
  })
  .describe("CIO proposal with an explicit review for every current position.");

export const CioFinalSchema = CIO_BASE_SCHEMA.extend({
  dissent_refs: z.array(DISSENT_REF_SCHEMA).default([]),
  position_reviews: z.array(POSITION_REVIEW_SCHEMA).optional(),
})
  .superRefine((value, ctx) => {
    validateCioWeights(value, ctx);
    const seen = new Set<string>();
    value.dissent_refs.forEach((reference, index) => {
      const key = `${reference.ticker}:${reference.source}`;
      if (seen.has(key)) {
        ctx.addIssue({
          code: "custom",
          path: ["dissent_refs", index],
          message: `duplicate dissent reference ${key}`,
        });
      }
      seen.add(key);
    });
  })
  .describe("CIO final target with structured CRO/execution dissent references.");

export const CIO_FIELD_NAMES = [
  "decision_disposition",
  "decision_reason",
  "decision_claim_refs",
  "portfolio_actions",
  "position_reviews",
  "dissent_refs",
  "confidence",
  "claims",
  "claim_refs",
] as const;

// ---------------------------------------------------------------------------
// Type-check guards
// ---------------------------------------------------------------------------

type _GuardEqShape<T, U> = T extends U ? (U extends T ? true : never) : never;
type _GuardAssignable<T, U> = T extends U ? true : never;

const _croCheck: _GuardAssignable<z.infer<typeof CroSchema>, CroOutput> = true;
const _alphaCheck: _GuardAssignable<
  z.infer<typeof AlphaDiscoverySchema>,
  AlphaDiscoveryOutput
> = true;
const _autoCheck: _GuardAssignable<
  z.infer<typeof AutonomousExecutionSchema>,
  AutoExecOutput
> = true;
// Runtime CIO extraction is intentionally stricter than the state interface:
// persisted legacy/fallback states may omit evidence fields, but fresh model
// output must include them so post-extraction evidence validation cannot erase
// an otherwise valid action silently.
const _cioCheck: _GuardAssignable<z.infer<typeof CioSchema>, CioOutput> = true;
const _cioProposalCheck: _GuardAssignable<
  z.infer<typeof CioProposalSchema>,
  CioProposalOutput
> = true;
const _cioFinalCheck: _GuardAssignable<z.infer<typeof CioFinalSchema>, CioFinalOutput> = true;

void _croCheck;
void _alphaCheck;
void _autoCheck;
void _cioCheck;
void _cioProposalCheck;
void _cioFinalCheck;
void KEY_DRIVERS_OPTIONAL_NOTE;

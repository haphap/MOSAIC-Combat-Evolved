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
import type { AlphaDiscoveryOutput, AutoExecOutput, CioOutput, CroOutput } from "../types.js";

const KEY_DRIVERS_OPTIONAL_NOTE = "key_drivers may be omitted on Layer 4 (synthesis-only).";

const HOLDING_PERIOD = z.enum(["1W", "1M", "3M", "6M", "1Y", "5Y+"]);

// ---------------------------------------------------------------------------
// 1. cro
// ---------------------------------------------------------------------------

export const CroSchema = z
  .object({
    agent: z.literal("cro"),
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
        }),
      )
      .max(20)
      .describe("Picks rejected after risk review. Empty if upstream looks clean."),
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
  })
  .describe(
    "Layer-4 chief risk officer adversarial review. Reads L1+L2+L3 fully and " +
      "raises objections. Empty rejected_picks is allowed when the upstream is clean.",
  );

export const CRO_FIELD_NAMES = [
  "rejected_picks",
  "correlated_risks",
  "black_swan_scenarios",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 2. alpha_discovery
// ---------------------------------------------------------------------------

export const AlphaDiscoverySchema = z
  .object({
    agent: z.literal("alpha_discovery"),
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
        }),
      )
      .max(10)
      .describe("Cross-cutting picks the 4 superinvestors collectively missed."),
    confidence: z.number().min(0).max(1),
  })
  .describe(
    "Layer-4 alpha discovery — finds picks that fall between superinvestor philosophies. " +
      "Empty novel_picks is the most common outcome and is fine.",
  );

export const ALPHA_DISCOVERY_FIELD_NAMES = ["novel_picks", "confidence"] as const;

// ---------------------------------------------------------------------------
// 3. autonomous_execution
// ---------------------------------------------------------------------------

export const AutonomousExecutionSchema = z
  .object({
    agent: z.literal("autonomous_execution"),
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
          conviction: z.number().min(0).max(1),
        }),
      )
      .max(20)
      .describe("Per-ticker trade decisions; HOLD picks at zero size also fine."),
    confidence: z.number().min(0).max(1),
  })
  .describe(
    "Layer-4 autonomous execution. Translates L3 picks + cro / alpha into concrete trade actions. " +
      "Darwinian weights are stubbed at uniform = 1/N until Phase 3 scorecard lands.",
  );

export const AUTONOMOUS_EXECUTION_FIELD_NAMES = ["trades", "confidence"] as const;

// ---------------------------------------------------------------------------
// 4. cio (most strict)
// ---------------------------------------------------------------------------

export const CioSchema = z
  .object({
    agent: z.literal("cio"),
    portfolio_actions: z
      .array(
        z.object({
          ticker: z.string().min(1),
          action: z.enum(["BUY", "SELL", "HOLD", "REDUCE"]),
          target_weight: z
            .number()
            .min(0)
            .max(1)
            .describe("[0, 1] target portfolio weight after this action."),
          holding_period: HOLDING_PERIOD,
          dissent_notes: z
            .string()
            .describe(
              "Empty when CIO matches autonomous_execution; non-empty when CIO overrides " +
                "(must explain why).",
            ),
        }),
      )
      .max(15),
    confidence: z.number().min(0).max(1),
  })
  .describe(
    "Layer-4 CIO final decision. portfolio_actions weights should sum to 1.0 ± 0.05 unless " +
      "the CIO is intentionally holding cash (acceptable when regime BEARISH + low confidence).",
  )
  .superRefine((val, ctx) => {
    const total = val.portfolio_actions.reduce((sum, a) => sum + a.target_weight, 0);
    // Allow cash holdings: total < 1 is OK (CIO chose to hold cash).
    // But total > 1.05 is over-allocation → invalid.
    if (total > 1.05) {
      ctx.addIssue({
        code: "custom",
        message: `portfolio_actions target_weight sum ${total.toFixed(3)} exceeds 1.05; reduce allocations.`,
      });
    }
  });

export const CIO_FIELD_NAMES = ["portfolio_actions", "confidence"] as const;

// ---------------------------------------------------------------------------
// Type-check guards
// ---------------------------------------------------------------------------

type _GuardEqShape<T, U> = T extends U ? (U extends T ? true : never) : never;

const _croCheck: _GuardEqShape<z.infer<typeof CroSchema>, CroOutput> = true;
const _alphaCheck: _GuardEqShape<z.infer<typeof AlphaDiscoverySchema>, AlphaDiscoveryOutput> = true;
const _autoCheck: _GuardEqShape<z.infer<typeof AutonomousExecutionSchema>, AutoExecOutput> = true;
const _cioCheck: _GuardEqShape<z.infer<typeof CioSchema>, CioOutput> = true;

void _croCheck;
void _alphaCheck;
void _autoCheck;
void _cioCheck;
void KEY_DRIVERS_OPTIONAL_NOTE;

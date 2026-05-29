/**
 * Zod schemas for Layer-1 macro agents (Plan §5.1).
 *
 * Co-located in this file so a single agent-config table can reference all
 * 10 schemas once they exist. Phase 2B lands only ``CentralBankSchema``;
 * the remaining 9 land in 2C as each agent wires up.
 *
 * Schema-to-interface mapping is enforced by ``z.infer<typeof X> extends Y``
 * — see the type-check guards at the bottom of this file.
 */

import { z } from "zod";
import type { CentralBankOutput, ChinaOutput, MacroAgentOutput } from "../types.js";

// ---------------------------------------------------------------------------
// Shared base helpers
// ---------------------------------------------------------------------------

const KEY_DRIVERS = z
  .array(z.string().min(1).describe("≤ 30-char evidence bullet pulled from tool returns"))
  .min(1)
  .max(8)
  .describe(
    "3-5 concrete evidence bullets, each containing a number or date. " +
      "Vague phrases like '偏松' or 'turning hawkish' without a metric are not allowed.",
  );

const CONFIDENCE = z
  .number()
  .min(0)
  .max(1)
  .describe(
    "Self-rated certainty in [0, 1]. Use ≥ 0.7 only when every required tool returned " +
      "conclusive data; drop to ≤ 0.5 if any tool failed or returned thin data.",
  );

// ---------------------------------------------------------------------------
// 1. central_bank (Plan §5.1)
// ---------------------------------------------------------------------------

export const CentralBankSchema = z
  .object({
    agent: z.literal("central_bank"),
    stance: z
      .enum(["ACCOMMODATIVE", "NEUTRAL", "TIGHTENING"])
      .describe("Combined PBOC + Fed stance for the as_of_date window."),
    key_rate_change_bps: z
      .number()
      .describe(
        "Combined effective rate-change direction in basis points; negative = easing. " +
          "Synthesise PBOC + Fed actions into a single signed number.",
      ),
    qe_qt_balance_change: z
      .string()
      .min(1)
      .describe(
        "Free-form summary of OMO / MLF / QE balance shifts, e.g. " +
          "'OMO net injection +20B CNY, MLF -150B CNY'.",
      ),
    next_window: z
      .string()
      .describe(
        "Either an ISO yyyy-mm-dd date for the next material policy window, " +
          "or the literal token 'unknown'.",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Central-bank stance read for one daily-cycle date. Required: dual-bank (PBOC + Fed) " +
      "coupling explicitly assessed.",
  );

/** The four required field names for the structured-only fallback prompt. */
export const CENTRAL_BANK_FIELD_NAMES = [
  "stance",
  "key_rate_change_bps",
  "qe_qt_balance_change",
  "next_window",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 2. china (Plan §5.1)
// ---------------------------------------------------------------------------

export const ChinaSchema = z
  .object({
    agent: z.literal("china"),
    policy_direction: z
      .enum(["PRO_GROWTH", "BALANCED", "RESTRAINING"])
      .describe(
        "Aggregate Chinese policy posture for the as_of_date window. " +
          "PRO_GROWTH = stimulus / industry support; BALANCED = wait-and-see; " +
          "RESTRAINING = anti-speculation / regulation tightening.",
      ),
    sector_focus: z
      .array(z.string().min(1))
      .min(1)
      .max(8)
      .describe(
        "Sectors the policy text is steering capital toward (e.g. " +
          "'semiconductor', 'ai', 'new energy', '新质生产力'). Use the agent's tool " +
          "outputs verbatim; do not paraphrase into broader categories.",
      ),
    risk_drivers: z
      .array(z.string().min(1))
      .min(1)
      .max(8)
      .describe(
        "Domestic risks flagged by the latest policy / capital-flow signals " +
          "(e.g. 'property leverage', 'youth unemployment', 'local government debt').",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "China-domestic policy stance read for one daily-cycle date. Required: " +
      "blend industrial-policy + capital-flow signals; do not infer policy from " +
      "PBOC operations alone (that's the central_bank agent's territory).",
  );

export const CHINA_FIELD_NAMES = [
  "policy_direction",
  "sector_focus",
  "risk_drivers",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// Type-check guards: zod schema must produce the canonical TS interface.
// These are unused at runtime; they exist to make `tsc` reject schema drift.
// ---------------------------------------------------------------------------

type _CentralBankSchemaIsCentralBankOutput =
  z.infer<typeof CentralBankSchema> extends Omit<CentralBankOutput, "agent"> & {
    agent: "central_bank";
  }
    ? true
    : never;
const _centralBankSchemaCheck: _CentralBankSchemaIsCentralBankOutput = true;

type _ChinaSchemaIsChinaOutput =
  z.infer<typeof ChinaSchema> extends Omit<ChinaOutput, "agent"> & { agent: "china" }
    ? true
    : never;
const _chinaSchemaCheck: _ChinaSchemaIsChinaOutput = true;

export type _MacroSchemaGuards = MacroAgentOutput; // re-exported so unused-import lint stays quiet
void _centralBankSchemaCheck;
void _chinaSchemaCheck;

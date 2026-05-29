/**
 * Zod schemas for Layer-3 superinvestor agents (Plan §5.3).
 *
 * All 4 share the same shape (picks + philosophy_note + key_drivers +
 * confidence) — only the `agent` literal differs. Uses
 * `buildSuperinvestorSchema(literal)` factory to keep the 4 declarations
 * single-line.
 */

import { z } from "zod";
import type {
  AckmanOutput,
  AschenbrennerOutput,
  BakerOutput,
  DruckenmillerOutput,
  SuperinvestorOutput,
} from "../types.js";

const HOLDING_PERIOD = z
  .enum(["1W", "1M", "3M", "6M", "1Y", "5Y+"])
  .describe(
    "Holding-period bracket. 1W/1M = tactical; 3M/6M = swing; 1Y/5Y+ = long-term compounder.",
  );

const SUPER_PICK = z.object({
  ticker: z
    .string()
    .min(1)
    .describe(
      "MOSAIC ticker (e.g. '600519.SH'). Must be sourced from the Layer-2 candidate " +
        "universe in the user-context block.",
    ),
  thesis: z
    .string()
    .min(1)
    .describe(
      "Philosophy-grounded rationale (≤ 80 chars in Chinese / ≤ 25 words in English). " +
        "Tie to one concrete signal (regime / sector / policy / fundamental).",
    ),
  conviction: z.number().min(0).max(1).describe("[0, 1] strength of conviction."),
  holding_period: HOLDING_PERIOD,
});

const KEY_DRIVERS = z
  .array(z.string().min(1))
  .min(1)
  .max(8)
  .describe("3-5 short evidence bullets, each citing a number / ticker / regime signal.");

const CONFIDENCE = z.number().min(0).max(1);

function buildSuperinvestorSchema<L extends string>(literal: L) {
  return z
    .object({
      agent: z.literal(literal),
      picks: z
        .array(SUPER_PICK)
        .min(0)
        .max(8)
        .describe(
          "3-5 high-conviction picks; ≤ 8 hard cap. Empty allowed when philosophy + " +
            "regime do not support any candidate (rare; cap confidence ≤ 0.3).",
        ),
      philosophy_note: z
        .string()
        .min(1)
        .describe(
          "1-3 sentences explaining why the chosen picks fit this superinvestor's " +
            "philosophy under the current Layer-1 regime.",
        ),
      key_drivers: KEY_DRIVERS,
      confidence: CONFIDENCE,
    })
    .describe(`Layer-3 superinvestor (${literal}) philosophy-filtered picks.`);
}

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

export const DruckenmillerSchema = buildSuperinvestorSchema("druckenmiller");
export const AschenbrennerSchema = buildSuperinvestorSchema("aschenbrenner");
export const BakerSchema = buildSuperinvestorSchema("baker");
export const AckmanSchema = buildSuperinvestorSchema("ackman");

export const SUPERINVESTOR_FIELD_NAMES = [
  "picks",
  "philosophy_note",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// Type-check guards
// ---------------------------------------------------------------------------

type _GuardEqShape<T, U> = T extends U ? (U extends T ? true : never) : never;

const _drCheck: _GuardEqShape<z.infer<typeof DruckenmillerSchema>, DruckenmillerOutput> = true;
const _asCheck: _GuardEqShape<z.infer<typeof AschenbrennerSchema>, AschenbrennerOutput> = true;
const _baCheck: _GuardEqShape<z.infer<typeof BakerSchema>, BakerOutput> = true;
const _acCheck: _GuardEqShape<z.infer<typeof AckmanSchema>, AckmanOutput> = true;

export type _SuperinvestorSchemaGuards = SuperinvestorOutput;
void _drCheck;
void _asCheck;
void _baCheck;
void _acCheck;

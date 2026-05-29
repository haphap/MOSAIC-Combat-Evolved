/**
 * Zod schemas for Layer-2 sector agents (Plan §5.2).
 *
 * Six "standard" sector agents share the same shape (longs/shorts/sector_score/
 * key_drivers/confidence) but use ``z.literal`` to discriminate. The seventh,
 * relationship_mapper, has a different output shape (supply chains / ownership
 * clusters / contagion risks) but uses the same Layer-2 factory.
 */

import { z } from "zod";
import type {
  BiotechOutput,
  ConsumerOutput,
  EnergyOutput,
  FinancialsOutput,
  IndustrialsOutput,
  RelationshipMapperOutput,
  SectorAgentOutput,
  SemiconductorOutput,
} from "../types.js";

// ---------------------------------------------------------------------------
// Shared building blocks
// ---------------------------------------------------------------------------

const SECTOR_PICK = z.object({
  ticker: z
    .string()
    .min(1)
    .describe(
      "MOSAIC ticker form (e.g. '600519.SH'). Use exact tickers from tool returns; " +
        "do not invent.",
    ),
  thesis: z
    .string()
    .min(1)
    .describe(
      "Short rationale (≤ 50 chars) tying the pick to a concrete macro / policy / flow signal.",
    ),
  conviction: z.number().min(0).max(1).describe("[0, 1] strength of conviction."),
});

const KEY_DRIVERS = z
  .array(z.string().min(1).describe("≤ 30-char evidence bullet"))
  .min(1)
  .max(8)
  .describe("3-5 concrete evidence bullets, each citing a number / ticker / policy keyword.");

const CONFIDENCE = z
  .number()
  .min(0)
  .max(1)
  .describe(
    "Self-rated certainty. Phase 0/1 sector tools incomplete — cap ≤ 0.5 until Phase 4 ETF tools land.",
  );

/** Common shape factory for the 6 standard sector agents. */
function buildStandardSectorSchema<L extends string>(literal: L) {
  return z
    .object({
      agent: z.literal(literal),
      longs: z
        .array(SECTOR_PICK)
        .max(10)
        .describe("Up to 10 long picks; empty allowed when conviction is low."),
      shorts: z.array(SECTOR_PICK).max(10).describe("Up to 10 short picks; empty allowed."),
      sector_score: z
        .number()
        .min(-1)
        .max(1)
        .describe("[-1, 1] aggregate sector tilt; +1 = max bullish."),
      key_drivers: KEY_DRIVERS,
      confidence: CONFIDENCE,
    })
    .describe(
      `Layer-2 sector pick output for ${literal}. Picks must reference tickers from ` +
        `tool returns; speculation is not allowed.`,
    );
}

// ---------------------------------------------------------------------------
// 6 standard sector schemas
// ---------------------------------------------------------------------------

export const SemiconductorSchema = buildStandardSectorSchema("semiconductor");
export const EnergySchema = buildStandardSectorSchema("energy");
export const BiotechSchema = buildStandardSectorSchema("biotech");
export const ConsumerSchema = buildStandardSectorSchema("consumer");
export const IndustrialsSchema = buildStandardSectorSchema("industrials");
export const FinancialsSchema = buildStandardSectorSchema("financials");

export const STANDARD_SECTOR_FIELD_NAMES = [
  "longs",
  "shorts",
  "sector_score",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 7. relationship_mapper (different shape)
// ---------------------------------------------------------------------------

export const RelationshipMapperSchema = z
  .object({
    agent: z.literal("relationship_mapper"),
    supply_chains: z
      .array(
        z.object({
          name: z
            .string()
            .min(1)
            .describe("Industry chain name, e.g. '半导体设备', '新能源车整车'"),
          tickers: z.array(z.string().min(1)).min(1).max(10),
          risk: z.string().min(1).describe("Concrete contagion risk for this chain"),
        }),
      )
      .min(1)
      .max(8),
    ownership_clusters: z
      .array(
        z.object({
          cluster_id: z.string().min(1),
          tickers: z.array(z.string().min(1)).min(2).max(20),
        }),
      )
      .max(8)
      .describe(
        "Cross-holdings / common-shareholder clusters (Phase 4 ETF tools required for richer detection).",
      ),
    contagion_risks: z
      .array(z.string().min(1))
      .min(1)
      .max(8)
      .describe("Cross-sector contagion concerns inferred from shared exposures."),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Layer-2 cross-sector relationship mapper. Supply-chain + ownership data is " +
      "Phase-0-incomplete; until Phase 4 ETF holdings tools land, supply_chains uses a " +
      "small hard-coded reference set + tool-derived risk signals.",
  );

export const RELATIONSHIP_MAPPER_FIELD_NAMES = [
  "supply_chains",
  "ownership_clusters",
  "contagion_risks",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// Type-check guards
// ---------------------------------------------------------------------------

type _GuardEqShape<T, U> = T extends U ? (U extends T ? true : never) : never;

const _semiCheck: _GuardEqShape<z.infer<typeof SemiconductorSchema>, SemiconductorOutput> = true;
const _energyCheck: _GuardEqShape<z.infer<typeof EnergySchema>, EnergyOutput> = true;
const _bioCheck: _GuardEqShape<z.infer<typeof BiotechSchema>, BiotechOutput> = true;
const _consumerCheck: _GuardEqShape<z.infer<typeof ConsumerSchema>, ConsumerOutput> = true;
const _industrialsCheck: _GuardEqShape<z.infer<typeof IndustrialsSchema>, IndustrialsOutput> = true;
const _financialsCheck: _GuardEqShape<z.infer<typeof FinancialsSchema>, FinancialsOutput> = true;
const _relCheck: _GuardEqShape<
  z.infer<typeof RelationshipMapperSchema>,
  RelationshipMapperOutput
> = true;

export type _SectorSchemaGuards = SectorAgentOutput;
void _semiCheck;
void _energyCheck;
void _bioCheck;
void _consumerCheck;
void _industrialsCheck;
void _financialsCheck;
void _relCheck;

import { z } from "zod";
import { ClaimSchemaV2 } from "../evidence_contract.js";
import { MacroInputAttributionSubmissionArraySchema } from "../helpers/macro_attribution.js";
import type {
  AckmanOutput,
  BurryOutput,
  DruckenmillerOutput,
  MungerOutput,
  SuperinvestorOutput,
} from "../types.js";

const LocalId = z.string().trim().min(1).max(128);
const ConciseText = z.string().trim().min(1).max(320);
const ClaimRefs = z.array(LocalId).min(1).max(6);
const TsCode = z.string().regex(/^\d{6}\.(?:SH|SZ|BJ)$/);

function buildSecurityPick(tsCodeSchema: z.ZodType<string> = TsCode) {
  return z
    .object({
      pick_local_id: LocalId,
      ts_code: tsCodeSchema,
      position_action: z.enum(["LONG", "AVOID"]),
      conviction: z.number().gt(0).max(1),
      thesis: ConciseText,
      claim_refs: ClaimRefs,
    })
    .strict();
}

const SecurityPick = buildSecurityPick();

const Driver = z
  .object({
    driver_local_id: LocalId,
    summary: ConciseText,
    claim_refs: ClaimRefs,
  })
  .strict();

const Risk = z
  .object({
    risk_local_id: LocalId,
    summary: ConciseText,
    claim_refs: ClaimRefs,
  })
  .strict();

const common = {
  confidence: z.number().min(0).max(1),
  holding_period: z.enum(["WEEKS", "MONTHS", "YEARS"]),
  key_drivers: z.array(Driver).min(1).max(5),
  risks: z.array(Risk).min(1).max(5),
  claims: z.array(ClaimSchemaV2).min(1).max(10),
  claim_refs: ClaimRefs,
  macro_input_attributions: MacroInputAttributionSubmissionArraySchema,
};

function buildSuperinvestorSchema<L extends SuperinvestorOutput["agent"]>(literal: L) {
  return refineSuperinvestorSchema(
    z.discriminatedUnion("selection_status", [
      selectedBranch(literal, SecurityPick),
      abstentionBranch(literal),
    ]),
  );
}

export function buildRuntimeSuperinvestorSchema<L extends SuperinvestorOutput["agent"]>(
  literal: L,
  allowedTsCodes: ReadonlyArray<string>,
): z.ZodType<SuperinvestorOutput & { agent: L }> {
  const codes = [...new Set(allowedTsCodes)].sort();
  if (codes.length === 0) {
    return refineSuperinvestorSchema(abstentionBranch(literal)) as z.ZodType<
      SuperinvestorOutput & { agent: L }
    >;
  }
  const allowedTsCode = z.enum(codes as [string, ...string[]]);
  return refineSuperinvestorSchema(
    z.discriminatedUnion("selection_status", [
      selectedBranch(literal, buildSecurityPick(allowedTsCode)),
      abstentionBranch(literal),
    ]),
  ) as z.ZodType<SuperinvestorOutput & { agent: L }>;
}

function selectedBranch<L extends SuperinvestorOutput["agent"]>(
  literal: L,
  pickSchema: ReturnType<typeof buildSecurityPick>,
) {
  return z
    .object({
      agent: z.literal(literal),
      selection_status: z.literal("SELECTED"),
      ...common,
      picks: z.array(pickSchema).min(1).max(10),
    })
    .strict();
}

function abstentionBranch<L extends SuperinvestorOutput["agent"]>(literal: L) {
  return z
    .object({
      agent: z.literal(literal),
      selection_status: z.literal("NO_QUALIFIED_CANDIDATES"),
      ...common,
      picks: z.tuple([]),
    })
    .strict();
}

function refineSuperinvestorSchema<T extends z.ZodType<SuperinvestorOutput>>(schema: T) {
  return schema.superRefine((output: SuperinvestorOutput, ctx) => {
    const claimIds = new Set(output.claims.map((claim) => claim.claim_id));
    const allRefs = [
      ...output.claim_refs,
      ...output.picks.flatMap((pick) => pick.claim_refs),
      ...output.key_drivers.flatMap((driver) => driver.claim_refs),
      ...output.risks.flatMap((risk) => risk.claim_refs),
    ];
    for (const ref of allRefs) {
      if (!claimIds.has(ref)) {
        ctx.addIssue({
          code: "custom",
          path: ["claims"],
          message: `unknown claim_ref ${ref}`,
        });
      }
    }
    const pickIds = output.picks.map((pick) => pick.pick_local_id);
    const tickers = output.picks.map((pick) => pick.ts_code);
    if (new Set(pickIds).size !== pickIds.length || new Set(tickers).size !== tickers.length) {
      ctx.addIssue({
        code: "custom",
        path: ["picks"],
        message: "pick_local_id and ts_code must be unique",
      });
    }
    if (output.picks.reduce((sum, pick) => sum + pick.conviction, 0) > 1 + 1e-12) {
      ctx.addIssue({
        code: "custom",
        path: ["picks"],
        message: "pick conviction sum must not exceed 1",
      });
    }
    const targetRefs = new Set(output.picks.map((pick) => pick.pick_local_id));
    for (const row of output.macro_input_attributions) {
      if (row.target_type === "SUBMISSION_SUMMARY") continue;
      if (row.target_type !== "SECURITY_PICK" || !targetRefs.has(row.target_local_ref)) {
        ctx.addIssue({
          code: "custom",
          path: ["macro_input_attributions"],
          message: `unresolved attribution target ${row.target_type}:${row.target_local_ref}`,
        });
      }
    }
  });
}

export const DruckenmillerSchema = buildSuperinvestorSchema("druckenmiller");
export const MungerSchema = buildSuperinvestorSchema("munger");
export const BurrySchema = buildSuperinvestorSchema("burry");
export const AckmanSchema = buildSuperinvestorSchema("ackman");

export const SUPERINVESTOR_FIELD_NAMES = [
  "selection_status",
  "confidence",
  "holding_period",
  "picks",
  "key_drivers",
  "risks",
  "claims",
  "claim_refs",
  "macro_input_attributions",
] as const;

const _drCheck: z.ZodType<DruckenmillerOutput> = DruckenmillerSchema;
const _muCheck: z.ZodType<MungerOutput> = MungerSchema;
const _buCheck: z.ZodType<BurryOutput> = BurrySchema;
const _acCheck: z.ZodType<AckmanOutput> = AckmanSchema;
void _drCheck;
void _muCheck;
void _buCheck;
void _acCheck;

import { z } from "zod";
import { MACRO_AGENT_IDS } from "../macro/_contracts.js";
import type { MacroAgentId, MacroAgentOutput, MacroInputGateReceipt } from "../types.js";
import { canonicalJsonHash } from "./canonical_json.js";

const LocalRefSchema = z.string().trim().min(1).max(128);
const ClaimRefSchema = z.string().trim().min(1).max(128);

export const MacroInputAttributionTargetTypeSchema = z.enum([
  "SUBMISSION_SUMMARY",
  "SECTOR_THESIS",
  "SECURITY_PICK",
  "RISK_ACTION",
  "PORTFOLIO_DECISION",
]);

export const MacroInputAttributionEffectSchema = z.enum([
  "SUPPORTS",
  "OPPOSES",
  "RISK_ONLY",
  "MIXED",
  "NOT_MATERIAL",
]);

const MaterialMacroInputAttributionEffectSchema = z.enum([
  "SUPPORTS",
  "OPPOSES",
  "RISK_ONLY",
  "MIXED",
]);
const TargetMacroInputAttributionTypeSchema = z.enum([
  "SECTOR_THESIS",
  "SECURITY_PICK",
  "RISK_ACTION",
  "PORTFOLIO_DECISION",
]);
const materialAttributionFields = {
  claim_refs_used: z.array(ClaimRefSchema).min(1).max(6),
  effect: MaterialMacroInputAttributionEffectSchema,
};
const immaterialAttributionFields = {
  claim_refs_used: z.array(ClaimRefSchema).max(0),
  effect: z.literal("NOT_MATERIAL"),
};
const MacroProviderSummaryValueSchema = z.union([
  z
    .object({
      claim_ref_used: z.null(),
      effect: z.literal("NOT_MATERIAL"),
    })
    .strict(),
  z
    .object({
      claim_ref_used: ClaimRefSchema,
      effect: MaterialMacroInputAttributionEffectSchema,
    })
    .strict(),
]);

const MacroSummaryAttributionSchema = z.union([
  z
    .object({
      agent_id: z.enum(MACRO_AGENT_IDS),
      target_type: z.literal("SUBMISSION_SUMMARY"),
      target_local_ref: z.literal("$SUBMISSION"),
      ...materialAttributionFields,
    })
    .strict(),
  z
    .object({
      agent_id: z.enum(MACRO_AGENT_IDS),
      target_type: z.literal("SUBMISSION_SUMMARY"),
      target_local_ref: z.literal("$SUBMISSION"),
      ...immaterialAttributionFields,
    })
    .strict(),
]);
const MacroTargetAttributionSchema = z.union([
  z
    .object({
      agent_id: z.enum(MACRO_AGENT_IDS),
      target_type: TargetMacroInputAttributionTypeSchema,
      target_local_ref: LocalRefSchema.regex(/^[^$].*$/),
      ...materialAttributionFields,
    })
    .strict(),
  z
    .object({
      agent_id: z.enum(MACRO_AGENT_IDS),
      target_type: TargetMacroInputAttributionTypeSchema,
      target_local_ref: LocalRefSchema.regex(/^[^$].*$/),
      ...immaterialAttributionFields,
    })
    .strict(),
]);
const MacroProviderTargetAttributionSchema = z
  .object({
    agent_id: z.enum(MACRO_AGENT_IDS),
    target_type: TargetMacroInputAttributionTypeSchema,
    target_local_ref: LocalRefSchema.regex(/^[^$].*$/),
    claim_ref_used: ClaimRefSchema,
    effect: MaterialMacroInputAttributionEffectSchema,
  })
  .strict();

export const MacroInputAttributionSubmissionSchema = z.union([
  MacroSummaryAttributionSchema,
  MacroTargetAttributionSchema,
]);

export type MacroInputAttributionSubmission = z.infer<typeof MacroInputAttributionSubmissionSchema>;

export const MacroInputAttributionSubmissionArraySchema = z
  .array(MacroInputAttributionSubmissionSchema)
  .min(MACRO_AGENT_IDS.length)
  .max(16)
  .describe(
    "Begin with exactly one SUBMISSION_SUMMARY row for each of the ten Macro agents in roster order. " +
      "Use target_local_ref=$SUBMISSION for those rows. Add at most six material target rows; " +
      "NOT_MATERIAL rows must have an empty claim_refs_used array.",
  )
  .superRefine((rows, ctx) => {
    const summaries = rows.filter((row) => row.target_type === "SUBMISSION_SUMMARY");
    if (
      rows
        .slice(0, MACRO_AGENT_IDS.length)
        .map((row) => row.agent_id)
        .join("\0") !== MACRO_AGENT_IDS.join("\0") ||
      rows.slice(MACRO_AGENT_IDS.length).some((row) => row.target_type === "SUBMISSION_SUMMARY")
    ) {
      ctx.addIssue({
        code: "custom",
        path: [],
        message: "Macro submission summaries must be the ten-row roster-ordered prefix",
      });
    }
    for (const agentId of MACRO_AGENT_IDS) {
      if (summaries.filter((row) => row.agent_id === agentId).length !== 1) {
        ctx.addIssue({
          code: "custom",
          path: [],
          message: `${agentId} requires exactly one SUBMISSION_SUMMARY attribution`,
        });
      }
    }
    const keys = rows.map((row) => `${row.agent_id}\0${row.target_type}\0${row.target_local_ref}`);
    if (new Set(keys).size !== keys.length) {
      ctx.addIssue({
        code: "custom",
        path: [],
        message: "duplicate Macro attribution target",
      });
    }
  });

export const MacroInputAttributionProviderSchema = z
  .object({
    submission_summaries: z
      .object({
        china: MacroProviderSummaryValueSchema,
        us_economy: MacroProviderSummaryValueSchema,
        eu_economy: MacroProviderSummaryValueSchema,
        central_bank: MacroProviderSummaryValueSchema,
        us_financial_conditions: MacroProviderSummaryValueSchema,
        euro_area_financial_conditions: MacroProviderSummaryValueSchema,
        commodities: MacroProviderSummaryValueSchema,
        geopolitical: MacroProviderSummaryValueSchema,
        market_breadth: MacroProviderSummaryValueSchema,
        institutional_flow: MacroProviderSummaryValueSchema,
      })
      .strict(),
    target_attributions: z.array(MacroProviderTargetAttributionSchema).max(6),
  })
  .strict()
  .describe(
    "Provider extraction shape. Fill every named submission summary and add at most six target rows.",
  );

export const MACRO_ATTRIBUTION_PROVIDER_INSTRUCTION =
  "For structured extraction, macro_input_attributions is an object with submission_summaries " +
  "keyed by china, us_economy, eu_economy, central_bank, us_financial_conditions, " +
  "euro_area_financial_conditions, commodities, geopolitical, market_breadth, and " +
  "institutional_flow, plus target_attributions. Fill every summary key with effect and the " +
  "single claim_ref_used (null only for NOT_MATERIAL). The runtime converts " +
  "this bounded extraction object into the canonical MacroInputAttributionSubmission rows.";

const MacroInputAttributionProviderJsonSchema = (() => {
  const { $schema: _schemaDialect, ...nestedSchema } = z.toJSONSchema(
    MacroInputAttributionProviderSchema,
  );
  return nestedSchema;
})();

const STANDARD_SECTOR_AGENT_IDS = new Set([
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
]);

function macroInputAttributionProviderJsonSchema(properties: Record<string, unknown>): unknown {
  const macroField =
    properties.macro_input_attributions !== null &&
    typeof properties.macro_input_attributions === "object" &&
    !Array.isArray(properties.macro_input_attributions)
      ? (properties.macro_input_attributions as Record<string, unknown>)
      : null;
  const noTargetRows =
    macroField?.["x-mosaic-no-target-rows"] === true ||
    objectConst(properties.agent) === "relationship_mapper" ||
    [
      objectConst(properties.selection_status),
      objectConst(properties.predictive_graph_status),
    ].some((value) => value?.startsWith("NO_QUALIFIED"));
  const standardSector = STANDARD_SECTOR_AGENT_IDS.has(objectConst(properties.agent) ?? "");
  if (!noTargetRows && !standardSector) return MacroInputAttributionProviderJsonSchema;
  const schema = structuredClone(MacroInputAttributionProviderJsonSchema) as unknown as {
    properties: {
      target_attributions: {
        maxItems?: number;
        items?: { properties?: { target_type?: Record<string, unknown> } };
      };
    };
  };
  if (noTargetRows) {
    schema.properties.target_attributions.maxItems = 0;
  } else if (standardSector) {
    const targetType = schema.properties.target_attributions.items?.properties?.target_type;
    if (targetType) targetType.enum = ["SECTOR_THESIS", "SECURITY_PICK"];
  }
  return schema;
}

function objectConst(value: unknown): string | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const constant = (value as Record<string, unknown>).const;
  return typeof constant === "string" ? constant : null;
}

export function adaptMacroAttributionProviderJsonSchema(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(adaptMacroAttributionProviderJsonSchema);
  if (value === null || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  const properties = record.properties;
  if (
    properties !== null &&
    typeof properties === "object" &&
    !Array.isArray(properties) &&
    Object.hasOwn(properties, "macro_input_attributions")
  ) {
    const adaptedProperties = Object.fromEntries(
      Object.entries(properties as Record<string, unknown>).map(([key, nested]) => [
        key,
        key === "macro_input_attributions"
          ? macroInputAttributionProviderJsonSchema(properties as Record<string, unknown>)
          : adaptMacroAttributionProviderJsonSchema(nested),
      ]),
    );
    return Object.fromEntries(
      Object.entries(record).map(([key, nested]) => [
        key,
        key === "properties" ? adaptedProperties : adaptMacroAttributionProviderJsonSchema(nested),
      ]),
    );
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [
      key,
      adaptMacroAttributionProviderJsonSchema(nested),
    ]),
  );
}

export function normalizeMacroAttributionProviderPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeMacroAttributionProviderPayload);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, nested]) => {
      if (key !== "macro_input_attributions") {
        return [key, normalizeMacroAttributionProviderPayload(nested)];
      }
      const parsed = MacroInputAttributionProviderSchema.safeParse(nested);
      if (!parsed.success) return [key, nested];
      const summaries = MACRO_AGENT_IDS.map((agentId) => {
        const summary = parsed.data.submission_summaries[agentId];
        const notMaterial =
          summary.claim_ref_used === null || summary.claim_ref_used === "NOT_MATERIAL";
        return {
          agent_id: agentId,
          target_type: "SUBMISSION_SUMMARY" as const,
          target_local_ref: "$SUBMISSION" as const,
          claim_refs_used: notMaterial ? [] : [summary.claim_ref_used],
          effect: notMaterial ? ("NOT_MATERIAL" as const) : summary.effect,
        };
      });
      const targets = parsed.data.target_attributions.map((row) => ({
        agent_id: row.agent_id,
        target_type: row.target_type,
        target_local_ref: row.target_local_ref,
        claim_refs_used: [row.claim_ref_used],
        effect: row.effect,
      }));
      return [key, [...summaries, ...targets]];
    }),
  );
}

export interface AcceptedMacroInputAttribution {
  agent_id: MacroAgentId;
  usage_share: number;
  target_type: MacroInputAttributionSubmission["target_type"];
  target_ref: string;
  target_hash: string;
  claim_refs_used: string[];
  effect: MacroInputAttributionSubmission["effect"];
}

export interface MacroAttributionTarget {
  target_type: Exclude<MacroInputAttributionSubmission["target_type"], "SUBMISSION_SUMMARY">;
  target_local_ref: string;
  target: unknown;
}

export function resolveMacroInputAttributions(input: {
  submissions: readonly MacroInputAttributionSubmission[];
  acceptedMacroOutputs: Readonly<Record<string, MacroAgentOutput>>;
  macroInputGate: MacroInputGateReceipt;
  acceptedSubmissionBody: unknown;
  targets?: readonly MacroAttributionTarget[];
}): AcceptedMacroInputAttribution[] {
  const submissions = MacroInputAttributionSubmissionArraySchema.parse(input.submissions);
  validateMacroGate(input.acceptedMacroOutputs, input.macroInputGate);
  const summaryBody = canonicalAcceptedSubmissionBody(input.acceptedSubmissionBody);
  const summaryHash = canonicalHash(summaryBody);
  const targetByKey = new Map<string, MacroAttributionTarget>();
  for (const target of input.targets ?? []) {
    const key = targetKey(target.target_type, target.target_local_ref);
    if (targetByKey.has(key)) throw new Error(`duplicate accepted attribution target ${key}`);
    targetByKey.set(key, target);
  }

  return [...submissions].sort(compareAttributions).map((row): AcceptedMacroInputAttribution => {
    const macroOutput = input.acceptedMacroOutputs[row.agent_id];
    if (!macroOutput || macroOutput.agent_id !== row.agent_id) {
      throw new Error(`${row.agent_id}: accepted Macro output is unavailable`);
    }
    const ownedClaimIds = new Set(macroOutput.claims.map((claim) => claim.claim_id));
    for (const claimRef of row.claim_refs_used) {
      if (!ownedClaimIds.has(claimRef)) {
        throw new Error(`${row.agent_id}: attribution uses unowned claim ${claimRef}`);
      }
    }

    let targetHash: string;
    let targetRef: string;
    if (row.target_type === "SUBMISSION_SUMMARY") {
      targetHash = summaryHash;
      targetRef = `accepted-target:submission:${summaryHash.slice("sha256:".length)}`;
    } else {
      const target = targetByKey.get(targetKey(row.target_type, row.target_local_ref));
      if (!target) {
        throw new Error(
          `${row.agent_id}: unresolved attribution target ${row.target_type}:${row.target_local_ref}`,
        );
      }
      targetHash = canonicalHash(target.target);
      targetRef = `accepted-target:${row.target_type.toLowerCase()}:${targetHash.slice(
        "sha256:".length,
      )}`;
    }
    return {
      agent_id: row.agent_id,
      usage_share: input.macroInputGate.reliability_by_agent[row.agent_id].usage_share,
      target_type: row.target_type,
      target_ref: targetRef,
      target_hash: targetHash,
      claim_refs_used: [...row.claim_refs_used],
      effect: row.effect,
    };
  });
}

export function canonicalAcceptedSubmissionBody(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("accepted submission body must be an object");
  }
  const excluded = new Set([
    "macro_input_attributions",
    "accepted_macro_input_attributions",
    "accepted_at",
    "verified_claim_graph",
    "verified_claim_audit",
    "runtime_fallback_audit",
    "sector_runtime_binding",
  ]);
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).filter(([key]) => !excluded.has(key)),
  );
}

function validateMacroGate(
  outputs: Readonly<Record<string, MacroAgentOutput>>,
  gate: MacroInputGateReceipt,
): void {
  if (gate.accepted_count !== 10) throw new Error("Macro input gate is not complete");
  if ([...gate.accepted_agent_ids].sort().join("\0") !== [...MACRO_AGENT_IDS].sort().join("\0")) {
    throw new Error("Macro input gate roster mismatch");
  }
  for (const agentId of MACRO_AGENT_IDS) {
    const output = outputs[agentId];
    if (!output || output.agent_id !== agentId) {
      throw new Error(`${agentId}: accepted Macro output is unavailable`);
    }
    const usageShare = gate.reliability_by_agent[agentId]?.usage_share;
    if (!Number.isFinite(usageShare) || (usageShare ?? -1) < 0 || (usageShare ?? 2) > 1) {
      throw new Error(`${agentId}: invalid authoritative usage share`);
    }
  }
}

function targetKey(
  targetType: MacroAttributionTarget["target_type"],
  targetLocalRef: string,
): string {
  return `${targetType}\0${targetLocalRef}`;
}

function compareAttributions(
  left: MacroInputAttributionSubmission,
  right: MacroInputAttributionSubmission,
): number {
  const leftAgent = MACRO_AGENT_IDS.indexOf(left.agent_id);
  const rightAgent = MACRO_AGENT_IDS.indexOf(right.agent_id);
  return (
    leftAgent - rightAgent ||
    left.target_type.localeCompare(right.target_type) ||
    left.target_local_ref.localeCompare(right.target_local_ref)
  );
}

export function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
}

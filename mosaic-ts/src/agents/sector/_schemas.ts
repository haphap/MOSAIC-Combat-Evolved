import { z } from "zod";
import { ClaimSchemaV2 } from "../evidence_contract.js";
import { MacroInputAttributionSubmissionArraySchema } from "../helpers/macro_attribution.js";
import type {
  RelationshipMapperOutput,
  SectorAgentOutput,
  SectorAgentOutputBase,
  StandardSectorAgentId,
} from "../types.js";
import { STANDARD_SECTOR_ROLE_CONTRACTS } from "./_contracts.js";

const LocalId = z.string().trim().min(1).max(128);
const ConciseText = z.string().trim().min(1).max(320);
const ClaimRefs = z.array(LocalId).min(1).max(12);
const Strength = z.union([z.literal(1), z.literal(2), z.literal(3), z.literal(4), z.literal(5)]);
const SecurityPick = z
  .object({
    pick_local_id: LocalId,
    ts_code: z.string().regex(/^\d{6}\.(?:SH|SZ|BJ)$/),
    direction_local_id: LocalId,
    position_action: z.enum(["LONG", "SHORT", "AVOID"]),
    conviction: z.number().gt(0).max(1),
    thesis: ConciseText,
    claim_refs: ClaimRefs,
  })
  .strict();
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
const SectorFinalClaimSchema = ClaimSchemaV2.safeExtend({
  structured_conclusion: z
    .object({
      conclusion_type: z.enum([
        "SECTOR_DIRECTION",
        "SECTOR_SECURITY",
        "SECTOR_DRIVER",
        "SECTOR_RISK",
        "MACRO_ATTRIBUTION",
      ]),
      target_local_ref: LocalId.nullable(),
      selection_status: z.literal("SELECTED").nullable(),
      direction_id: z.string().trim().min(1).max(128).nullable(),
      position_action: z.enum(["LONG", "SHORT", "AVOID"]).nullable(),
      summary: ConciseText,
    })
    .strict(),
});

const common = {
  persistence_horizon: z.enum(["DAYS", "WEEKS", "MONTHS"]),
  confidence: z.number().min(0).max(1),
  key_drivers: z.array(Driver).min(1).max(3),
  risks: z.array(Risk).min(1).max(3),
  claims: z.array(SectorFinalClaimSchema).min(1).max(6),
  claim_refs: ClaimRefs,
  macro_input_attributions: MacroInputAttributionSubmissionArraySchema,
};

export function buildStandardSectorSchema<TAgent extends StandardSectorAgentId>(
  agent: TAgent,
  requiredSelectionStatus?: "SELECTED",
  directive?: {
    selection_status: "SELECTED";
    preferred_direction_id: string;
    least_preferred_direction_id: string;
    allowed_preferred_security_ids: string[];
    allowed_least_preferred_security_ids: string[];
  },
): z.ZodType<SectorAgentOutputBase & { agent: TAgent }> {
  void requiredSelectionStatus;
  const directionIds = STANDARD_SECTOR_ROLE_CONTRACTS[agent].directionIds;
  if (directive && directive.least_preferred_direction_id === directive.preferred_direction_id) {
    throw new Error(`${agent}: selected runtime directive requires two distinct directions`);
  }
  const direction = z.enum(directionIds);
  const preferredDirection = directive ? z.literal(directive.preferred_direction_id) : direction;
  const preferredSecurityUnavailable = directive?.allowed_preferred_security_ids.length === 0;
  const leastSecurityUnavailable = directive?.allowed_least_preferred_security_ids.length === 0;
  const leastPreferredDirection = z
    .object({
      selection_role: z.literal("LEAST_PREFERRED"),
      direction_local_id: directive ? z.literal(directive.least_preferred_direction_id) : LocalId,
      direction_id: directive ? z.literal(directive.least_preferred_direction_id) : direction,
      allocation_action: z.literal("UNDERWEIGHT"),
      strength: Strength,
      thesis: ConciseText,
      claim_refs: ClaimRefs,
    })
    .strict();
  return z
    .object({
      agent: z.literal(agent),
      selection_status: z.literal("SELECTED"),
      preferred_direction: z
        .object({
          selection_role: z.literal("PREFERRED"),
          direction_local_id: directive ? z.literal(directive.preferred_direction_id) : LocalId,
          direction_id: preferredDirection,
          allocation_action: z.literal("OVERWEIGHT"),
          strength: Strength,
          thesis: ConciseText,
          claim_refs: ClaimRefs,
        })
        .strict(),
      least_preferred_direction: leastPreferredDirection,
      ...common,
      preferred_security_status: preferredSecurityUnavailable
        ? z.literal("NO_QUALIFIED_SECURITY")
        : directive
          ? z.literal("PICKS_PRESENT")
          : z.enum(["PICKS_PRESENT", "NO_QUALIFIED_SECURITY"]),
      preferred_security_abstention_confidence: preferredSecurityUnavailable
        ? z.number().min(0).max(1)
        : directive
          ? z.null()
          : z.number().min(0).max(1).nullable(),
      long_picks: preferredSecurityUnavailable
        ? z.tuple([])
        : directive
          ? z.array(SecurityPick).min(1).max(5)
          : z.array(SecurityPick).max(5),
      least_preferred_security_status: leastSecurityUnavailable
        ? z.literal("NO_QUALIFIED_SECURITY")
        : directive
          ? z.literal("PICKS_PRESENT")
          : z.enum(["PICKS_PRESENT", "NO_QUALIFIED_SECURITY"]),
      least_preferred_security_abstention_confidence: leastSecurityUnavailable
        ? z.number().min(0).max(1)
        : directive
          ? z.null()
          : z.number().min(0).max(1).nullable(),
      short_or_avoid_picks: leastSecurityUnavailable
        ? z.tuple([])
        : directive
          ? z.array(SecurityPick).min(1).max(5)
          : z.array(SecurityPick).max(5),
    })
    .strict()
    .superRefine((output, ctx) => {
      const claimIds = new Set(output.claims.map((claim) => claim.claim_id));
      for (const ref of output.claim_refs) {
        if (!claimIds.has(ref))
          ctx.addIssue({
            code: "custom",
            path: ["claim_refs"],
            message: `unknown claim_ref ${ref}`,
          });
      }
      const validAttributionTargets = new Set<string>([
        `SECTOR_THESIS\0${output.preferred_direction.direction_local_id}`,
        `SECTOR_THESIS\0${output.least_preferred_direction.direction_local_id}`,
      ]);
      for (const pick of [...output.long_picks, ...output.short_or_avoid_picks]) {
        validAttributionTargets.add(`SECURITY_PICK\0${pick.pick_local_id}`);
      }
      for (const row of output.macro_input_attributions) {
        if (row.target_type === "SUBMISSION_SUMMARY") continue;
        if (!validAttributionTargets.has(`${row.target_type}\0${row.target_local_ref}`)) {
          ctx.addIssue({
            code: "custom",
            path: ["macro_input_attributions"],
            message: `unresolved attribution target ${row.target_type}:${row.target_local_ref}`,
          });
        }
      }
      if (
        output.least_preferred_direction.direction_id === output.preferred_direction.direction_id
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["least_preferred_direction"],
          message: "preferred and least-preferred must differ",
        });
      }
      {
        const picks = [...output.long_picks, ...output.short_or_avoid_picks];
        if (new Set(picks.map((pick) => pick.pick_local_id)).size !== picks.length) {
          ctx.addIssue({
            code: "custom",
            path: ["long_picks"],
            message: "pick_local_id must be unique across both security legs",
          });
        }
        if (new Set(picks.map((pick) => pick.ts_code)).size !== picks.length) {
          ctx.addIssue({
            code: "custom",
            path: ["long_picks"],
            message: "ts_code must be unique across both security legs",
          });
        }
        if (output.long_picks.reduce((sum, pick) => sum + pick.conviction, 0) > 1 + 1e-9) {
          ctx.addIssue({
            code: "custom",
            path: ["long_picks"],
            message: "preferred-leg conviction sum must not exceed 1",
          });
        }
        if (
          output.short_or_avoid_picks.reduce((sum, pick) => sum + pick.conviction, 0) >
          1 + 1e-9
        ) {
          ctx.addIssue({
            code: "custom",
            path: ["short_or_avoid_picks"],
            message: "least-preferred-leg conviction sum must not exceed 1",
          });
        }
        validateSecurityLeg(
          {
            status: output.preferred_security_status,
            abstentionConfidence: output.preferred_security_abstention_confidence,
            picks: output.long_picks,
            directionLocalId: output.preferred_direction.direction_local_id,
            allowedActions: new Set(["LONG"]),
          },
          ctx,
          "preferred_security_status",
        );
        validateSecurityLeg(
          {
            status: output.least_preferred_security_status,
            abstentionConfidence: output.least_preferred_security_abstention_confidence,
            picks: output.short_or_avoid_picks,
            directionLocalId: output.least_preferred_direction.direction_local_id,
            allowedActions: new Set(["SHORT", "AVOID"]),
          },
          ctx,
          "least_preferred_security_status",
        );
      }
      const entryRefs = [
        ...output.key_drivers.flatMap((entry) => entry.claim_refs),
        ...output.risks.flatMap((entry) => entry.claim_refs),
        ...output.long_picks.flatMap((entry) => entry.claim_refs),
        ...output.short_or_avoid_picks.flatMap((entry) => entry.claim_refs),
        ...output.preferred_direction.claim_refs,
        ...output.least_preferred_direction.claim_refs,
      ];
      for (const ref of entryRefs) {
        if (!claimIds.has(ref)) {
          ctx.addIssue({ code: "custom", path: ["claims"], message: `unknown entry claim ${ref}` });
        }
      }
    }) as z.ZodType<SectorAgentOutputBase & { agent: TAgent }>;
}

function validateSecurityLeg(
  input: {
    status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
    abstentionConfidence: number | null;
    picks: Array<z.infer<typeof SecurityPick>>;
    directionLocalId: string;
    allowedActions: ReadonlySet<string>;
  },
  ctx: z.core.$RefinementCtx,
  path: string,
): void {
  if (input.status === "PICKS_PRESENT") {
    if (input.picks.length === 0 || input.abstentionConfidence !== null) {
      ctx.addIssue({
        code: "custom",
        path: [path],
        message: "PICKS_PRESENT requires picks and null abstention confidence",
      });
    }
  } else if (input.status === "NO_QUALIFIED_SECURITY") {
    if (input.picks.length !== 0 || input.abstentionConfidence === null) {
      ctx.addIssue({
        code: "custom",
        path: [path],
        message: "NO_QUALIFIED_SECURITY requires no picks and an abstention confidence",
      });
    }
  }
  for (const pick of input.picks) {
    if (
      pick.direction_local_id !== input.directionLocalId ||
      !input.allowedActions.has(pick.position_action)
    ) {
      ctx.addIssue({
        code: "custom",
        path: [path],
        message: "pick direction/action does not match its selection leg",
      });
    }
  }
}

export const SemiconductorSchema = buildStandardSectorSchema("semiconductor");
export const TechnologySchema = buildStandardSectorSchema("technology");
export const EnergySchema = buildStandardSectorSchema("energy");
export const BiotechSchema = buildStandardSectorSchema("biotech");
export const ConsumerSchema = buildStandardSectorSchema("consumer");
export const IndustrialsSchema = buildStandardSectorSchema("industrials");
export const RealEstateConstructionSchema = buildStandardSectorSchema("real_estate_construction");
export const FinancialsSchema = buildStandardSectorSchema("financials");
export const AgricultureSchema = buildStandardSectorSchema("agriculture");

export const STANDARD_SECTOR_FIELD_NAMES = [
  "agent",
  "selection_status",
  "preferred_direction",
  "least_preferred_direction",
  "persistence_horizon",
  "confidence",
  "key_drivers",
  "risks",
  "claims",
  "claim_refs",
  "preferred_security_status",
  "preferred_security_abstention_confidence",
  "long_picks",
  "least_preferred_security_status",
  "least_preferred_security_abstention_confidence",
  "short_or_avoid_picks",
  "macro_input_attributions",
] as const;

export function buildRelationshipMapperSchema(bounds?: {
  maxFactualEdges: number;
  maxPredictiveEdges: number;
  factualRelationships?: readonly {
    source_entity: string;
    target_entity: string;
    edge_type: string;
  }[];
  predictiveOpportunities?: readonly {
    edge_candidate_id: string;
    source_entity: string;
    target_entity: string;
    edge_type: string;
  }[];
}) {
  const factualBase = relationshipGraphBase(bounds?.maxFactualEdges, bounds?.factualRelationships);
  const predictiveEdges = z
    .array(relationshipPredictiveEdge(bounds?.predictiveOpportunities))
    .min(1);
  const boundedPredictiveEdges =
    bounds === undefined ? predictiveEdges : predictiveEdges.max(bounds.maxPredictiveEdges);
  return z
    .discriminatedUnion("predictive_graph_status", [
      factualBase.extend({
        predictive_graph_status: z.literal("EDGES_PRESENT"),
        predictive_edges: boundedPredictiveEdges,
        predictive_graph_abstention_confidence: z.null(),
      }),
      factualBase.extend({
        predictive_graph_status: z.literal("NO_QUALIFIED_PREDICTIVE_EDGE"),
        predictive_edges: z.tuple([]),
        predictive_graph_abstention_confidence: z.number().min(0).max(1),
      }),
    ])
    .superRefine((output, ctx) => {
      const claimIds = new Set(output.claims.map((claim) => claim.claim_id));
      for (const ref of output.claim_refs) {
        if (!claimIds.has(ref)) {
          ctx.addIssue({
            code: "custom",
            path: ["claim_refs"],
            message: `unknown claim_ref ${ref}`,
          });
        }
      }
      const entryRefs = [
        ...output.factual_edges.flatMap((edge) => edge.claim_refs),
        ...output.predictive_edges.flatMap((edge) => edge.claim_refs),
        ...output.key_drivers.flatMap((driver) => driver.claim_refs),
        ...output.risks.flatMap((risk) => risk.claim_refs),
      ];
      for (const ref of entryRefs) {
        if (!claimIds.has(ref)) {
          ctx.addIssue({
            code: "custom",
            path: ["claims"],
            message: `unknown entry claim_ref ${ref}`,
          });
        }
      }
      const candidateIds = output.predictive_edges.map((edge) => edge.edge_candidate_id);
      if (new Set(candidateIds).size !== candidateIds.length) {
        ctx.addIssue({
          code: "custom",
          path: ["predictive_edges"],
          message: "duplicate edge_candidate_id",
        });
      }
      if (output.macro_input_attributions.some((row) => row.target_type !== "SUBMISSION_SUMMARY")) {
        ctx.addIssue({
          code: "custom",
          path: ["macro_input_attributions"],
          message: "relationship mapper supports submission-summary Macro attribution only",
        });
      }
    }) satisfies z.ZodType<RelationshipMapperOutput>;
}

export const RelationshipMapperSchema = buildRelationshipMapperSchema();

function relationshipGraphBase(
  maxFactualEdges?: number,
  factualRelationships?: readonly {
    source_entity: string;
    target_entity: string;
    edge_type: string;
  }[],
) {
  const factualEdges = z.array(relationshipFactualEdge(factualRelationships));
  return z
    .object({
      agent: z.literal("relationship_mapper"),
      factual_edges:
        maxFactualEdges === undefined ? factualEdges : factualEdges.max(maxFactualEdges),
      key_drivers: z.array(Driver).min(1).max(8),
      risks: z.array(Risk).min(1).max(8),
      claims: z.array(ClaimSchemaV2).min(1),
      claim_refs: ClaimRefs,
      macro_input_attributions: MacroInputAttributionSubmissionArraySchema,
    })
    .strict();
}

function relationshipFactualEdge(
  relationships?: readonly {
    source_entity: string;
    target_entity: string;
    edge_type: string;
  }[],
) {
  const commonFields = {
    edge_local_id: z.string().trim().min(1),
    claim_refs: ClaimRefs,
  };
  if (relationships && relationships.length > 0) {
    const variants = relationships.map((relationship) =>
      z
        .object({
          ...commonFields,
          source_entity: z.literal(relationship.source_entity),
          target_entity: z.literal(relationship.target_entity),
          edge_type: z.literal(relationship.edge_type),
        })
        .strict(),
    );
    const onlyVariant = variants.length === 1 ? variants[0] : undefined;
    if (onlyVariant) return onlyVariant;
    return z.union(
      variants as [
        (typeof variants)[number],
        (typeof variants)[number],
        ...(typeof variants)[number][],
      ],
    );
  }
  return z
    .object({
      ...commonFields,
      source_entity: z.string().trim().min(1),
      target_entity: z.string().trim().min(1),
      edge_type: z.string().trim().min(1),
    })
    .strict();
}

function relationshipPredictiveEdge(
  opportunities?: readonly {
    edge_candidate_id: string;
    source_entity: string;
    target_entity: string;
    edge_type: string;
  }[],
) {
  const decisionFields = {
    transmission_direction: z.enum(["POSITIVE", "NEGATIVE", "MIXED"]),
    activation_trigger: z.string().trim().min(1),
    evaluation_horizon_trading_days: z.literal(20),
    model_confidence: z.number().min(0).max(1),
    claim_refs: ClaimRefs,
  };
  if (opportunities && opportunities.length > 0) {
    const variants = opportunities.map((opportunity) =>
      z
        .object({
          edge_local_id: z.string().trim().min(1),
          edge_candidate_id: z.literal(opportunity.edge_candidate_id),
          source_entity: z.literal(opportunity.source_entity),
          target_entity: z.literal(opportunity.target_entity),
          edge_type: z.literal(opportunity.edge_type),
          ...decisionFields,
        })
        .strict(),
    );
    const onlyVariant = variants.length === 1 ? variants[0] : undefined;
    if (onlyVariant) return onlyVariant;
    return z.union(
      variants as [
        (typeof variants)[number],
        (typeof variants)[number],
        ...(typeof variants)[number][],
      ],
    );
  }
  return z
    .object({
      edge_local_id: z.string().trim().min(1),
      edge_candidate_id: z.string().trim().min(1),
      source_entity: z.string().trim().min(1),
      target_entity: z.string().trim().min(1),
      edge_type: z.string().trim().min(1),
      ...decisionFields,
    })
    .strict();
}

export const RELATIONSHIP_MAPPER_FIELD_NAMES = [
  "agent",
  "factual_edges",
  "predictive_edges",
  "predictive_graph_status",
  "predictive_graph_abstention_confidence",
  "key_drivers",
  "risks",
  "claims",
  "claim_refs",
  "macro_input_attributions",
] as const;

export type _SectorSchemaGuards = SectorAgentOutput;

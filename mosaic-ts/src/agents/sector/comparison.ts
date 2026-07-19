import { createHash } from "node:crypto";
import { z } from "zod";
import { ClaimSchemaV2 } from "../evidence_contract.js";
import {
  SECTOR_DIRECTION_COMPARISON_CONTRACT,
  SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT,
} from "./registry.js";

export const CORE_SECTOR_COMPARISON_CRITERIA = SECTOR_DIRECTION_COMPARISON_CONTRACT.core_criteria;
export const COVERAGE_GATED_SECTOR_COMPARISON_CRITERIA =
  SECTOR_DIRECTION_COMPARISON_CONTRACT.coverage_gated_criteria;
export const OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA =
  SECTOR_DIRECTION_COMPARISON_CONTRACT.optional_etf_criteria;
export const SECTOR_COMPARISON_CRITERIA = [
  ...CORE_SECTOR_COMPARISON_CRITERIA,
  ...COVERAGE_GATED_SECTOR_COMPARISON_CRITERIA,
  ...OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA,
] as const;

export const SECTOR_DIRECTION_COMPARISON_CONTRACT_VERSION =
  SECTOR_DIRECTION_COMPARISON_CONTRACT.comparison_contract_version;
export const SECTOR_DIRECTION_REDUCER_CONTRACT_VERSION =
  SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.resolver_contract_version;

export type SectorComparisonCriterion = (typeof SECTOR_COMPARISON_CRITERIA)[number];
export type ResolvedDirectionPairVerdict = "A" | "B" | "NO_CLEAR_WINNER";

export interface SectorCoverageDirective {
  contract_version: "sector_role_event_coverage_directive_v1";
  macro_event_fit: {
    coverage_state:
      | "AVAILABLE_MATERIAL_EVENTS"
      | "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT"
      | "SOURCE_UNAVAILABLE";
    coverage_evidence_ids: readonly [string, ...string[]];
  };
  catalysts: {
    coverage_state:
      | "AVAILABLE_MATERIAL_CATALYSTS"
      | "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST"
      | "SOURCE_UNAVAILABLE";
    coverage_evidence_ids: readonly [string, ...string[]];
  };
}

const Id = z.string().trim().min(1);
const ClaimRefs = z.array(Id).min(1);
const ComparableVerdict = z.enum(["FAVORS_A", "FAVORS_B", "NEUTRAL"]);

const CoreCriterionResultSchema = z
  .object({
    criterion: z.enum(CORE_SECTOR_COMPARISON_CRITERIA),
    comparison_status: z.literal("COMPARABLE"),
    verdict: ComparableVerdict,
    claim_refs: ClaimRefs,
  })
  .strict();

const MacroEventCriterionResultSchema = z.discriminatedUnion("coverage_state", [
  z
    .object({
      criterion: z.literal("MACRO_EVENT_FIT"),
      coverage_state: z.literal("AVAILABLE_MATERIAL_EVENTS"),
      comparison_status: z.literal("COMPARABLE"),
      verdict: ComparableVerdict,
      claim_refs: ClaimRefs,
      coverage_evidence_ids: ClaimRefs,
    })
    .strict(),
  z
    .object({
      criterion: z.literal("MACRO_EVENT_FIT"),
      coverage_state: z.literal("COVERAGE_CONFIRMED_NO_MATERIAL_EVENT"),
      comparison_status: z.literal("COMPARABLE"),
      verdict: z.literal("NEUTRAL"),
      claim_refs: ClaimRefs,
      coverage_evidence_ids: ClaimRefs,
    })
    .strict(),
  z
    .object({
      criterion: z.literal("MACRO_EVENT_FIT"),
      coverage_state: z.literal("SOURCE_UNAVAILABLE"),
      comparison_status: z.literal("UNAVAILABLE"),
      verdict: z.literal("NO_VOTE"),
      claim_refs: z.tuple([]),
      coverage_evidence_ids: ClaimRefs,
    })
    .strict(),
]);

const CatalystCriterionResultSchema = z.discriminatedUnion("coverage_state", [
  z
    .object({
      criterion: z.literal("CATALYSTS"),
      coverage_state: z.literal("AVAILABLE_MATERIAL_CATALYSTS"),
      comparison_status: z.literal("COMPARABLE"),
      verdict: ComparableVerdict,
      claim_refs: ClaimRefs,
      coverage_evidence_ids: ClaimRefs,
    })
    .strict(),
  z
    .object({
      criterion: z.literal("CATALYSTS"),
      coverage_state: z.literal("COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST"),
      comparison_status: z.literal("COMPARABLE"),
      verdict: z.literal("NEUTRAL"),
      claim_refs: ClaimRefs,
      coverage_evidence_ids: ClaimRefs,
    })
    .strict(),
  z
    .object({
      criterion: z.literal("CATALYSTS"),
      coverage_state: z.literal("SOURCE_UNAVAILABLE"),
      comparison_status: z.literal("UNAVAILABLE"),
      verdict: z.literal("NO_VOTE"),
      claim_refs: z.tuple([]),
      coverage_evidence_ids: ClaimRefs,
    })
    .strict(),
]);

const OptionalEtfCriterionResultSchema = z.union([
  z
    .object({
      criterion: z.enum(OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA),
      comparison_status: z.literal("COMPARABLE"),
      verdict: ComparableVerdict,
      claim_refs: ClaimRefs,
    })
    .strict(),
  z
    .object({
      criterion: z.enum(OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA),
      comparison_status: z.literal("INCOMPARABLE"),
      verdict: z.literal("INCOMPARABLE"),
      claim_refs: z.tuple([]),
    })
    .strict(),
]);

function exactCoreCriterionResultSchema(
  criterion: (typeof CORE_SECTOR_COMPARISON_CRITERIA)[number],
) {
  return CoreCriterionResultSchema.extend({ criterion: z.literal(criterion) });
}

function exactOptionalEtfCriterionResultSchema(
  criterion: (typeof OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA)[number],
) {
  return z.union([
    z
      .object({
        criterion: z.literal(criterion),
        comparison_status: z.literal("COMPARABLE"),
        verdict: ComparableVerdict,
        claim_refs: ClaimRefs,
      })
      .strict(),
    z
      .object({
        criterion: z.literal(criterion),
        comparison_status: z.literal("INCOMPARABLE"),
        verdict: z.literal("INCOMPARABLE"),
        claim_refs: z.tuple([]),
      })
      .strict(),
  ]);
}

const DirectionCriterionResultsSchema = z.tuple([
  exactCoreCriterionResultSchema("FUNDAMENTALS"),
  exactCoreCriterionResultSchema("VALUATION"),
  exactCoreCriterionResultSchema("BASKET_TECHNICALS"),
  exactCoreCriterionResultSchema("RISK_ASYMMETRY"),
  MacroEventCriterionResultSchema,
  CatalystCriterionResultSchema,
  exactOptionalEtfCriterionResultSchema("ETF_PRICE_CONFIRMATION"),
  exactOptionalEtfCriterionResultSchema("ETF_SHARE_FLOW_CONFIRMATION"),
]);

function exactCoverageEvidenceIds(ids: readonly [string, ...string[]]) {
  return z.tuple(
    ids.map((evidenceId) => z.literal(evidenceId)) as [
      z.ZodLiteral<string>,
      ...Array<z.ZodLiteral<string>>,
    ],
  );
}

function exactMacroEventCriterionResultSchema(
  directive: SectorCoverageDirective["macro_event_fit"],
) {
  const coverageEvidenceIds = exactCoverageEvidenceIds(directive.coverage_evidence_ids);
  if (directive.coverage_state === "SOURCE_UNAVAILABLE") {
    return z
      .object({
        criterion: z.literal("MACRO_EVENT_FIT"),
        coverage_state: z.literal("SOURCE_UNAVAILABLE"),
        comparison_status: z.literal("UNAVAILABLE"),
        verdict: z.literal("NO_VOTE"),
        claim_refs: z.tuple([]),
        coverage_evidence_ids: coverageEvidenceIds,
      })
      .strict();
  }
  return z
    .object({
      criterion: z.literal("MACRO_EVENT_FIT"),
      coverage_state: z.literal(directive.coverage_state),
      comparison_status: z.literal("COMPARABLE"),
      verdict:
        directive.coverage_state === "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT"
          ? z.literal("NEUTRAL")
          : ComparableVerdict,
      claim_refs: ClaimRefs,
      coverage_evidence_ids: coverageEvidenceIds,
    })
    .strict();
}

function exactCatalystCriterionResultSchema(directive: SectorCoverageDirective["catalysts"]) {
  const coverageEvidenceIds = exactCoverageEvidenceIds(directive.coverage_evidence_ids);
  if (directive.coverage_state === "SOURCE_UNAVAILABLE") {
    return z
      .object({
        criterion: z.literal("CATALYSTS"),
        coverage_state: z.literal("SOURCE_UNAVAILABLE"),
        comparison_status: z.literal("UNAVAILABLE"),
        verdict: z.literal("NO_VOTE"),
        claim_refs: z.tuple([]),
        coverage_evidence_ids: coverageEvidenceIds,
      })
      .strict();
  }
  return z
    .object({
      criterion: z.literal("CATALYSTS"),
      coverage_state: z.literal(directive.coverage_state),
      comparison_status: z.literal("COMPARABLE"),
      verdict:
        directive.coverage_state === "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST"
          ? z.literal("NEUTRAL")
          : ComparableVerdict,
      claim_refs: ClaimRefs,
      coverage_evidence_ids: coverageEvidenceIds,
    })
    .strict();
}

function exactDirectionCriterionResultsSchema(directive: SectorCoverageDirective) {
  return z.tuple([
    exactCoreCriterionResultSchema("FUNDAMENTALS"),
    exactCoreCriterionResultSchema("VALUATION"),
    exactCoreCriterionResultSchema("BASKET_TECHNICALS"),
    exactCoreCriterionResultSchema("RISK_ASYMMETRY"),
    exactMacroEventCriterionResultSchema(directive.macro_event_fit),
    exactCatalystCriterionResultSchema(directive.catalysts),
    exactOptionalEtfCriterionResultSchema("ETF_PRICE_CONFIRMATION"),
    exactOptionalEtfCriterionResultSchema("ETF_SHARE_FLOW_CONFIRMATION"),
  ]);
}

export const DirectionCriterionResultSchema = z.union([
  CoreCriterionResultSchema,
  MacroEventCriterionResultSchema,
  CatalystCriterionResultSchema,
  OptionalEtfCriterionResultSchema,
]);

export const DirectionPairwiseComparisonSubmissionSchema = z
  .object({
    comparison_local_id: Id,
    direction_a_id: Id,
    direction_b_id: Id,
    criterion_results: DirectionCriterionResultsSchema,
    claim_refs: ClaimRefs,
  })
  .strict()
  .superRefine((comparison, ctx) => {
    if (comparison.direction_a_id === comparison.direction_b_id) {
      ctx.addIssue({ code: "custom", path: ["direction_b_id"], message: "pair must be distinct" });
    }
    const criteria = comparison.criterion_results.map((result) => result.criterion);
    if (
      new Set(criteria).size !== SECTOR_COMPARISON_CRITERIA.length ||
      SECTOR_COMPARISON_CRITERIA.some((criterion) => !criteria.includes(criterion))
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["criterion_results"],
        message: "all eight comparison criteria are required exactly once",
      });
    }
    const expectedRefs = sortedUnique(
      comparison.criterion_results.flatMap((result) => result.claim_refs),
    );
    if (sortedUnique(comparison.claim_refs).join("\0") !== expectedRefs.join("\0")) {
      ctx.addIssue({
        code: "custom",
        path: ["claim_refs"],
        message: "comparison claim_refs must be the sorted criterion-ref union",
      });
    }
  });

export type DirectionCriterionResult = z.infer<typeof DirectionCriterionResultSchema>;

export interface DirectionPairwiseComparisonSubmission {
  comparison_local_id: string;
  direction_a_id: string;
  direction_b_id: string;
  criterion_results: DirectionCriterionResult[];
  claim_refs: string[];
}

export interface SectorDirectionResearchSubmission {
  research_mode: "PAIRWISE";
  comparison_claims: z.infer<typeof ClaimSchemaV2>[];
  direction_comparisons: DirectionPairwiseComparisonSubmission[];
}

export function buildSectorDirectionResearchSchema(
  eligibleDirectionIds: readonly [string, string, string, ...string[]],
  coverageDirective: SectorCoverageDirective,
): z.ZodType<SectorDirectionResearchSubmission> {
  if (eligibleDirectionIds.length < 3) {
    throw new Error("standard Sector direction research requires at least three directions");
  }
  const base = {
    comparison_claims: z.array(ClaimSchemaV2).min(1),
  };
  const expectedPairs = expectedOrderedPairs(eligibleDirectionIds);
  const pairwiseMatrixSchema = z.tuple(
    expectedPairs.map(([directionA, directionB]) =>
      exactDirectionPairSchema(directionA, directionB, coverageDirective),
    ) as [
      ReturnType<typeof exactDirectionPairSchema>,
      ...Array<ReturnType<typeof exactDirectionPairSchema>>,
    ],
  ) as unknown as z.ZodType<DirectionPairwiseComparisonSubmission[]>;
  const schema = z
    .object({
      research_mode: z.literal("PAIRWISE"),
      ...base,
      direction_comparisons: pairwiseMatrixSchema,
    })
    .strict();
  return schema.superRefine((submission, ctx) => {
    const claimIds = new Set(submission.comparison_claims.map((claim) => claim.claim_id));
    const refs = submission.direction_comparisons.flatMap((comparison) => comparison.claim_refs);
    if (claimIds.size !== submission.comparison_claims.length) {
      ctx.addIssue({
        code: "custom",
        path: ["comparison_claims"],
        message: "comparison claim ids must be unique",
      });
    }
    for (const ref of refs) {
      if (!claimIds.has(ref)) {
        ctx.addIssue({
          code: "custom",
          path: ["comparison_claims"],
          message: `unknown claim ${ref}`,
        });
      }
    }
    const referencedClaimIds = new Set(refs);
    for (const claimId of claimIds) {
      if (!referencedClaimIds.has(claimId)) {
        ctx.addIssue({
          code: "custom",
          path: ["comparison_claims"],
          message: `unreferenced comparison claim ${claimId}`,
        });
      }
    }
    const expected = expectedOrderedPairKeys(eligibleDirectionIds);
    const actual = submission.direction_comparisons.map((comparison) =>
      orderedPairKey(comparison.direction_a_id, comparison.direction_b_id),
    );
    if (
      actual.length !== expected.size ||
      new Set(actual).size !== expected.size ||
      actual.some((key) => !expected.has(key))
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["direction_comparisons"],
        message: "complete unique eligible pair matrix required",
      });
    }
    validateCoverageClaimBindings(
      submission.direction_comparisons,
      submission.comparison_claims,
      coverageDirective,
      ctx,
      "direction_comparisons",
    );
  }) as z.ZodType<SectorDirectionResearchSubmission>;
}

function exactDirectionPairSchema(
  directionA: string,
  directionB: string,
  coverageDirective: SectorCoverageDirective,
) {
  return DirectionPairwiseComparisonSubmissionSchema.safeExtend({
    direction_a_id: z.literal(directionA),
    direction_b_id: z.literal(directionB),
    criterion_results: exactDirectionCriterionResultsSchema(
      coverageDirective,
    ) as unknown as typeof DirectionCriterionResultsSchema,
  });
}

export function buildSectorConflictReviewSchema(
  conflictDirectionIds: readonly [string, string, ...string[]],
  coverageDirective: SectorCoverageDirective,
  reservedClaimIds: ReadonlySet<string> = new Set(),
) {
  const expectedPairs = expectedOrderedPairs(conflictDirectionIds);
  const revisedMatrixSchema = z.tuple(
    expectedPairs.map(([directionA, directionB]) =>
      exactDirectionPairSchema(directionA, directionB, coverageDirective),
    ) as [
      ReturnType<typeof exactDirectionPairSchema>,
      ...Array<ReturnType<typeof exactDirectionPairSchema>>,
    ],
  ) as unknown as z.ZodType<DirectionPairwiseComparisonSubmission[]>;
  return z
    .object({
      review_round: z.literal(1),
      comparison_claims: z.array(ClaimSchemaV2).min(1),
      revised_comparisons: revisedMatrixSchema,
    })
    .strict()
    .superRefine((submission, ctx) => {
      const expected = expectedOrderedPairKeys(conflictDirectionIds);
      const actual = submission.revised_comparisons.map((comparison) =>
        orderedPairKey(comparison.direction_a_id, comparison.direction_b_id),
      );
      if (
        actual.length !== expected.size ||
        new Set(actual).size !== expected.size ||
        actual.some((key) => !expected.has(key))
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["revised_comparisons"],
          message: "review must contain every conflict-internal pair exactly once",
        });
      }
      const claimIds = new Set(submission.comparison_claims.map((claim) => claim.claim_id));
      if (claimIds.size !== submission.comparison_claims.length) {
        ctx.addIssue({
          code: "custom",
          path: ["comparison_claims"],
          message: "review claim ids must be unique",
        });
      }
      for (const claimId of claimIds) {
        if (reservedClaimIds.has(claimId)) {
          ctx.addIssue({
            code: "custom",
            path: ["comparison_claims"],
            message: `review claim id must be new and immutable: ${claimId}`,
          });
        }
      }
      for (const ref of submission.revised_comparisons.flatMap((row) => row.claim_refs)) {
        if (!claimIds.has(ref)) {
          ctx.addIssue({
            code: "custom",
            path: ["comparison_claims"],
            message: `unknown review claim ${ref}`,
          });
        }
      }
      const referencedClaimIds = new Set(
        submission.revised_comparisons.flatMap((row) => row.claim_refs),
      );
      for (const claimId of claimIds) {
        if (!referencedClaimIds.has(claimId)) {
          ctx.addIssue({
            code: "custom",
            path: ["comparison_claims"],
            message: `unreferenced review claim ${claimId}`,
          });
        }
      }
      validateCoverageClaimBindings(
        submission.revised_comparisons,
        submission.comparison_claims,
        coverageDirective,
        ctx,
        "revised_comparisons",
      );
    });
}

function validateCoverageClaimBindings(
  comparisons: readonly DirectionPairwiseComparisonSubmission[],
  claims: readonly z.infer<typeof ClaimSchemaV2>[],
  directive: SectorCoverageDirective,
  ctx: z.core.$RefinementCtx,
  comparisonsField: "direction_comparisons" | "revised_comparisons",
): void {
  const claimById = new Map(claims.map((claim) => [claim.claim_id, claim]));
  for (const [comparisonIndex, comparison] of comparisons.entries()) {
    for (const [criterion, expected] of [
      ["MACRO_EVENT_FIT", directive.macro_event_fit],
      ["CATALYSTS", directive.catalysts],
    ] as const) {
      if (expected.coverage_state === "SOURCE_UNAVAILABLE") continue;
      const result = comparison.criterion_results.find((row) => row.criterion === criterion);
      if (!result) continue;
      const citedEvidence = new Set(
        result.claim_refs.flatMap((claimId) => claimById.get(claimId)?.evidence_ids ?? []),
      );
      if (!expected.coverage_evidence_ids.every((evidenceId) => citedEvidence.has(evidenceId))) {
        ctx.addIssue({
          code: "custom",
          path: [comparisonsField, comparisonIndex, "criterion_results", criterion, "claim_refs"],
          message: `${criterion} claims must cite every runtime coverage evidence id`,
        });
      }
    }
  }
}

export interface AcceptedDirectionPairResolution {
  comparison_local_id: string;
  direction_a_id: string;
  direction_b_id: string;
  resolved_verdict: ResolvedDirectionPairVerdict;
  base_support_count_a: number;
  base_support_count_b: number;
  optional_etf_support_weight_a: number;
  optional_etf_support_weight_b: number;
  weighted_support_a: number;
  weighted_support_b: number;
  decisive_voting_criteria: SectorComparisonCriterion[];
  qualifying_non_etf_criteria: SectorComparisonCriterion[];
  resolution_reason:
    | "WEIGHTED_SUPPORT_MARGIN_A"
    | "WEIGHTED_SUPPORT_MARGIN_B"
    | "INSUFFICIENT_BASE_SUPPORT"
    | "INSUFFICIENT_WEIGHTED_MARGIN";
  source_submission_hash: string;
}

export function resolveDirectionPair(
  input: DirectionPairwiseComparisonSubmission,
): AcceptedDirectionPairResolution {
  const comparison = DirectionPairwiseComparisonSubmissionSchema.parse(input);
  let baseA = 0;
  let baseB = 0;
  let etfA = 0;
  let etfB = 0;
  for (const result of comparison.criterion_results) {
    if (result.comparison_status !== "COMPARABLE") continue;
    const isEtf = OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA.includes(
      result.criterion as (typeof OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA)[number],
    );
    const isCoverageGated = COVERAGE_GATED_SECTOR_COMPARISON_CRITERIA.includes(
      result.criterion as (typeof COVERAGE_GATED_SECTOR_COMPARISON_CRITERIA)[number],
    );
    const increment = isEtf
      ? SECTOR_DIRECTION_COMPARISON_CONTRACT.optional_etf_vote_weight
      : isCoverageGated
        ? SECTOR_DIRECTION_COMPARISON_CONTRACT.available_coverage_gated_vote_weight
        : SECTOR_DIRECTION_COMPARISON_CONTRACT.core_vote_weight;
    if (result.verdict === "FAVORS_A") {
      if (isEtf) etfA += increment;
      else baseA += increment;
    } else if (result.verdict === "FAVORS_B") {
      if (isEtf) etfB += increment;
      else baseB += increment;
    }
  }
  const weightedA = baseA + etfA;
  const weightedB = baseB + etfB;
  const aWins =
    baseA >= SECTOR_DIRECTION_COMPARISON_CONTRACT.minimum_base_support_count &&
    weightedA - weightedB >= SECTOR_DIRECTION_COMPARISON_CONTRACT.minimum_weighted_support_margin;
  const bWins =
    baseB >= SECTOR_DIRECTION_COMPARISON_CONTRACT.minimum_base_support_count &&
    weightedB - weightedA >= SECTOR_DIRECTION_COMPARISON_CONTRACT.minimum_weighted_support_margin;
  const resolved: ResolvedDirectionPairVerdict = aWins ? "A" : bWins ? "B" : "NO_CLEAR_WINNER";
  const winningVerdict = resolved === "A" ? "FAVORS_A" : "FAVORS_B";
  const decisive =
    resolved === "NO_CLEAR_WINNER"
      ? []
      : comparison.criterion_results
          .filter(
            (result) =>
              result.comparison_status === "COMPARABLE" && result.verdict === winningVerdict,
          )
          .map((result) => result.criterion);
  const qualifying = decisive.filter(
    (criterion) =>
      !OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA.includes(
        criterion as (typeof OPTIONAL_ETF_SECTOR_COMPARISON_CRITERIA)[number],
      ),
  );
  return {
    comparison_local_id: comparison.comparison_local_id,
    direction_a_id: comparison.direction_a_id,
    direction_b_id: comparison.direction_b_id,
    resolved_verdict: resolved,
    base_support_count_a: baseA,
    base_support_count_b: baseB,
    optional_etf_support_weight_a: etfA,
    optional_etf_support_weight_b: etfB,
    weighted_support_a: weightedA,
    weighted_support_b: weightedB,
    decisive_voting_criteria: decisive,
    qualifying_non_etf_criteria: qualifying,
    resolution_reason: aWins
      ? "WEIGHTED_SUPPORT_MARGIN_A"
      : bWins
        ? "WEIGHTED_SUPPORT_MARGIN_B"
        : baseA < SECTOR_DIRECTION_COMPARISON_CONTRACT.minimum_base_support_count &&
            baseB < SECTOR_DIRECTION_COMPARISON_CONTRACT.minimum_base_support_count
          ? "INSUFFICIENT_BASE_SUPPORT"
          : "INSUFFICIENT_WEIGHTED_MARGIN",
    source_submission_hash: canonicalHash(comparison),
  };
}

export interface DirectionMatrixReduction {
  condorcet_winner_direction_id: string | null;
  condorcet_loser_direction_id: string | null;
  conflict_type: "NONE" | "CYCLE" | "TIE" | "NO_EDGE" | "MULTIPLE";
  conflict_direction_ids: string[];
  copeland_scores: Record<string, number>;
  finalized_pair_matrix_hash: string;
}

export function reduceDirectionMatrix(
  directionIds: readonly [string, ...string[]],
  resolutions: readonly AcceptedDirectionPairResolution[],
): DirectionMatrixReduction {
  const expected = expectedOrderedPairKeys(directionIds);
  const actual = resolutions.map((row) => orderedPairKey(row.direction_a_id, row.direction_b_id));
  if (
    actual.length !== expected.size ||
    new Set(actual).size !== expected.size ||
    actual.some((key) => !expected.has(key))
  ) {
    throw new Error("complete unique resolved pair matrix required");
  }
  const wins = new Map(directionIds.map((direction) => [direction, new Set<string>()]));
  const losses = new Map(directionIds.map((direction) => [direction, new Set<string>()]));
  const noEdge = new Set<string>();
  for (const row of resolutions) {
    if (row.resolved_verdict === "NO_CLEAR_WINNER") {
      noEdge.add(row.direction_a_id);
      noEdge.add(row.direction_b_id);
      continue;
    }
    const winner = row.resolved_verdict === "A" ? row.direction_a_id : row.direction_b_id;
    const loser = row.resolved_verdict === "A" ? row.direction_b_id : row.direction_a_id;
    wins.get(winner)?.add(loser);
    losses.get(loser)?.add(winner);
  }
  const winners = directionIds.filter(
    (direction) => wins.get(direction)?.size === directionIds.length - 1,
  );
  const losers = directionIds.filter(
    (direction) => losses.get(direction)?.size === directionIds.length - 1,
  );
  const copeland = Object.fromEntries(
    directionIds.map((direction) => [
      direction,
      (wins.get(direction)?.size ?? 0) - (losses.get(direction)?.size ?? 0),
    ]),
  );
  const cycleDirections = stronglyConnectedCycleDirections(directionIds, wins);
  const maxScore = Math.max(...Object.values(copeland));
  const minScore = Math.min(...Object.values(copeland));
  const maxTies = directionIds.filter((direction) => copeland[direction] === maxScore);
  const minTies = directionIds.filter((direction) => copeland[direction] === minScore);
  const tied = new Set<string>();
  if (winners.length !== 1 && maxTies.length > 1) {
    for (const direction of maxTies) tied.add(direction);
  }
  if (losers.length !== 1 && minTies.length > 1) {
    for (const direction of minTies) tied.add(direction);
  }
  const conflictDirections =
    winners.length === 1 && losers.length === 1
      ? []
      : sortedUnique([...cycleDirections, ...noEdge, ...tied]);
  const conflictKinds = [
    conflictDirections.some((direction) => cycleDirections.has(direction)) ? "CYCLE" : null,
    conflictDirections.some((direction) => tied.has(direction)) ? "TIE" : null,
    conflictDirections.some((direction) => noEdge.has(direction)) ? "NO_EDGE" : null,
  ].filter((value): value is "CYCLE" | "TIE" | "NO_EDGE" => value !== null);
  return {
    condorcet_winner_direction_id: winners.length === 1 ? (winners[0] ?? null) : null,
    condorcet_loser_direction_id: losers.length === 1 ? (losers[0] ?? null) : null,
    conflict_type:
      conflictKinds.length === 0
        ? "NONE"
        : conflictKinds.length === 1
          ? (conflictKinds[0] as "CYCLE" | "TIE" | "NO_EDGE")
          : "MULTIPLE",
    conflict_direction_ids: conflictDirections,
    copeland_scores: copeland,
    finalized_pair_matrix_hash: canonicalHash(resolutions),
  };
}

export function applyConflictReview(
  initial: readonly DirectionPairwiseComparisonSubmission[],
  reviewInput: {
    review_round: 1;
    comparison_claims: z.infer<typeof ClaimSchemaV2>[];
    revised_comparisons: DirectionPairwiseComparisonSubmission[];
  },
  conflictDirectionIds: readonly [string, string, ...string[]],
  coverageDirective: SectorCoverageDirective,
): DirectionPairwiseComparisonSubmission[] {
  const review = buildSectorConflictReviewSchema(
    conflictDirectionIds,
    coverageDirective,
    new Set(),
  ).parse(reviewInput);
  const replacement = new Map(
    review.revised_comparisons.map((row) => [
      orderedPairKey(row.direction_a_id, row.direction_b_id),
      row,
    ]),
  );
  return initial.map(
    (row) => replacement.get(orderedPairKey(row.direction_a_id, row.direction_b_id)) ?? row,
  );
}

export function expectedOrderedPairKeys(directionIds: readonly string[]): Set<string> {
  return new Set(
    expectedOrderedPairs(directionIds).map(([left, right]) => orderedPairKey(left, right)),
  );
}

function expectedOrderedPairs(directionIds: readonly string[]): Array<[string, string]> {
  const pairs: Array<[string, string]> = [];
  for (let left = 0; left < directionIds.length; left++) {
    for (let right = left + 1; right < directionIds.length; right++) {
      pairs.push([directionIds[left] as string, directionIds[right] as string]);
    }
  }
  return pairs;
}

function orderedPairKey(left: string, right: string): string {
  return `${left}|${right}`;
}

function stronglyConnectedCycleDirections(
  directionIds: readonly string[],
  wins: ReadonlyMap<string, ReadonlySet<string>>,
): Set<string> {
  const reachable = new Map<string, Set<string>>(
    directionIds.map((direction) => [direction, new Set(wins.get(direction) ?? [])]),
  );
  for (const pivot of directionIds) {
    for (const source of directionIds) {
      if (!reachable.get(source)?.has(pivot)) continue;
      for (const target of reachable.get(pivot) ?? []) reachable.get(source)?.add(target);
    }
  }
  return new Set(
    directionIds.filter((left) =>
      directionIds.some(
        (right) =>
          left !== right && reachable.get(left)?.has(right) && reachable.get(right)?.has(left),
      ),
    ),
  );
}

function sortedUnique(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value;
}

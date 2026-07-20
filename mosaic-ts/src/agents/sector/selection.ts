import type { z } from "zod";
import type { ClaimSchemaV2 } from "../evidence_contract.js";
import { canonicalJsonHash } from "../helpers/canonical_json.js";
import type { SectorAgentOutputBase, SectorRuntimeSelectionBinding } from "../types.js";
import type {
  AcceptedDirectionPairResolution,
  DirectionMatrixReduction,
  DirectionPairwiseComparisonSubmission,
} from "./comparison.js";
import { SECTOR_SECURITY_SCORING_CONTRACT } from "./registry.js";

export const SECURITY_SCORING_CONTRACT_VERSION =
  SECTOR_SECURITY_SCORING_CONTRACT.scoring_contract_version;
export const SECURITY_SCORING_CONTRACT_HASH =
  SECTOR_SECURITY_SCORING_CONTRACT.scoring_contract_hash as string;

export interface SectorSecurityScoringRow {
  ts_code: string;
  direction_id: string;
  availability_status: "AVAILABLE" | "UNAVAILABLE";
  unavailability_reason:
    | "INSUFFICIENT_PIT_OBSERVATIONS"
    | "MISSING_ADJUSTMENT_FACTOR"
    | "MISSING_MONEYFLOW"
    | null;
  observation_date: string;
  released_at: string;
  vintage_at: string;
  pit_status: "PIT_VERIFIED";
  adjusted_return_20d: number | null;
  realized_volatility_20d: number | null;
  median_amount_20d_cny: number | null;
  net_moneyflow_20d_cny: number | null;
  observation_count: number;
  required_observation_count: number;
  coverage_ratio: number;
  evidence_ids: string[];
  security_scoring_row_hash: string;
}

export interface SectorFinalSelectionRuntimeDirective {
  selection_status: "SELECTED";
  preferred_direction_id: string;
  least_preferred_direction_id: string;
  preferred_security_shortlist_id: string;
  preferred_security_shortlist_hash: string;
  least_preferred_security_shortlist_id: string;
  least_preferred_security_shortlist_hash: string;
  security_scoring_contract_version: typeof SECURITY_SCORING_CONTRACT_VERSION;
  security_scoring_contract_hash: string;
  allowed_preferred_security_ids: string[];
  allowed_least_preferred_security_ids: string[];
  required_preferred_evidence_ids: string[];
  required_least_preferred_evidence_ids: string[];
  required_final_evidence_ids: string[];
}

export type ModelVisibleSectorFinalSelectionDirective = Pick<
  SectorFinalSelectionRuntimeDirective,
  | "selection_status"
  | "preferred_direction_id"
  | "least_preferred_direction_id"
  | "allowed_preferred_security_ids"
  | "allowed_least_preferred_security_ids"
  | "required_preferred_evidence_ids"
  | "required_least_preferred_evidence_ids"
  | "required_final_evidence_ids"
>;

export function buildPairwiseFinalDirective(input: {
  reduction: DirectionMatrixReduction;
  finalizedComparisons: readonly DirectionPairwiseComparisonSubmission[];
  resolutions: readonly AcceptedDirectionPairResolution[];
  comparisonClaims: readonly z.infer<typeof ClaimSchemaV2>[];
  securityScoringRows: readonly SectorSecurityScoringRow[];
}): SectorFinalSelectionRuntimeDirective {
  const preferred = input.reduction.condorcet_winner_direction_id;
  if (!preferred) {
    throw new Error("Sector stage rejected: no unique Condorcet winner");
  }
  const least = input.reduction.condorcet_loser_direction_id;
  if (!least) {
    throw new Error("Sector stage rejected: no unique Condorcet loser");
  }
  if (preferred === least) {
    throw new Error("preferred and least-preferred directions must differ");
  }
  const leastRows = input.resolutions.filter((row) => {
    if (row.direction_a_id === least) return row.resolved_verdict === "B";
    if (row.direction_b_id === least) return row.resolved_verdict === "A";
    return false;
  });
  const directionCount = new Set(
    input.resolutions.flatMap((row) => [row.direction_a_id, row.direction_b_id]),
  ).size;
  if (
    leastRows.length !== directionCount - 1 ||
    leastRows.some((row) => row.qualifying_non_etf_criteria.length === 0)
  ) {
    throw new Error("Sector stage rejected: least-preferred direction lacks decisive evidence");
  }
  const preferredEvidence = decisiveEvidenceForDirection(
    preferred,
    "WINNER",
    input.finalizedComparisons,
    input.resolutions,
    input.comparisonClaims,
  );
  const leastEvidence = decisiveEvidenceForDirection(
    least,
    "LOSER",
    input.finalizedComparisons,
    input.resolutions,
    input.comparisonClaims,
  );
  if (preferredEvidence.length === 0 || leastEvidence.length === 0) {
    throw new Error("preferred or least-preferred direction has no decisive final evidence");
  }
  return selectedDirective({
    preferred,
    least,
    securityScoringRows: input.securityScoringRows,
    requiredPreferredEvidence: preferredEvidence,
    requiredLeastEvidence: leastEvidence,
  });
}

export function modelVisibleDirective(
  directive: SectorFinalSelectionRuntimeDirective,
): ModelVisibleSectorFinalSelectionDirective {
  return {
    selection_status: directive.selection_status,
    preferred_direction_id: directive.preferred_direction_id,
    least_preferred_direction_id: directive.least_preferred_direction_id,
    allowed_preferred_security_ids: directive.allowed_preferred_security_ids,
    allowed_least_preferred_security_ids: directive.allowed_least_preferred_security_ids,
    required_preferred_evidence_ids: directive.required_preferred_evidence_ids,
    required_least_preferred_evidence_ids: directive.required_least_preferred_evidence_ids,
    required_final_evidence_ids: directive.required_final_evidence_ids,
  };
}

export function validateFinalSelectionAgainstDirective(
  output: SectorAgentOutputBase,
  directive: SectorFinalSelectionRuntimeDirective,
): string[] {
  const issues: string[] = [];
  if (output.selection_status !== directive.selection_status) {
    issues.push("selection_status does not match runtime directive");
  }
  if (output.preferred_direction.direction_id !== directive.preferred_direction_id) {
    issues.push("preferred direction does not match runtime directive");
  }
  if (output.least_preferred_direction.direction_id !== directive.least_preferred_direction_id) {
    issues.push("least-preferred direction does not match runtime directive");
  } else if (
    output.preferred_direction.direction_id === output.least_preferred_direction.direction_id
  ) {
    issues.push("preferred and least-preferred directions must differ");
  }
  validatePicks(
    output.long_picks,
    directive.allowed_preferred_security_ids,
    output.preferred_direction.direction_local_id,
    new Set(["LONG"]),
    "preferred",
    issues,
  );
  validatePicks(
    output.short_or_avoid_picks,
    directive.allowed_least_preferred_security_ids,
    output.least_preferred_direction.direction_local_id,
    new Set(["SHORT", "AVOID"]),
    "least-preferred",
    issues,
  );
  validateLegEvidence(
    output,
    [
      ...output.preferred_direction.claim_refs,
      ...output.long_picks.flatMap((pick) => pick.claim_refs),
    ],
    directive.required_preferred_evidence_ids,
    "preferred",
    issues,
  );
  validateLegEvidence(
    output,
    [
      ...output.least_preferred_direction.claim_refs,
      ...output.short_or_avoid_picks.flatMap((pick) => pick.claim_refs),
    ],
    directive.required_least_preferred_evidence_ids,
    "least-preferred",
    issues,
  );
  const finalClaimIds = new Set(output.claim_refs);
  const finalEvidence = new Set(
    output.claims
      .filter((claim) => finalClaimIds.has(claim.claim_id))
      .flatMap((claim) => claim.evidence_ids),
  );
  if (!directive.required_final_evidence_ids.every((evidenceId) => finalEvidence.has(evidenceId))) {
    issues.push("final conclusion claims do not cite every required decisive evidence id");
  }
  return issues;
}

export function attachSectorRuntimeBinding<T extends SectorAgentOutputBase>(input: {
  output: T;
  directive: SectorFinalSelectionRuntimeDirective;
  snapshotBundleId: string;
  snapshotBundleHash: string;
  directionComparisonAuditHash: string;
  finalizedPairMatrixHash: string;
}): T {
  const binding: SectorRuntimeSelectionBinding = {
    snapshot_bundle_id: input.snapshotBundleId,
    snapshot_bundle_hash: input.snapshotBundleHash,
    direction_comparison_audit_hash: input.directionComparisonAuditHash,
    finalized_pair_matrix_hash: input.finalizedPairMatrixHash,
    selection_status: input.directive.selection_status,
    preferred_direction_id: input.directive.preferred_direction_id,
    least_preferred_direction_id: input.directive.least_preferred_direction_id,
    preferred_security_shortlist_id: input.directive.preferred_security_shortlist_id,
    preferred_security_shortlist_hash: input.directive.preferred_security_shortlist_hash,
    least_preferred_security_shortlist_id: input.directive.least_preferred_security_shortlist_id,
    least_preferred_security_shortlist_hash:
      input.directive.least_preferred_security_shortlist_hash,
    security_scoring_contract_version: input.directive.security_scoring_contract_version,
    security_scoring_contract_hash: input.directive.security_scoring_contract_hash,
    required_preferred_evidence_ids: input.directive.required_preferred_evidence_ids,
    required_least_preferred_evidence_ids: input.directive.required_least_preferred_evidence_ids,
    required_final_evidence_ids: input.directive.required_final_evidence_ids,
  };
  return { ...input.output, sector_runtime_binding: binding };
}

export function directionComparisonAuditHash(value: unknown): string {
  return canonicalHash({ contract: "sector_direction_comparison_audit_v1", value });
}

function selectedDirective(input: {
  preferred: string;
  least: string;
  securityScoringRows: readonly SectorSecurityScoringRow[];
  requiredPreferredEvidence: string[];
  requiredLeastEvidence: string[];
}): SectorFinalSelectionRuntimeDirective {
  const preferredList = shortlist(input.preferred, input.securityScoringRows);
  const leastList = shortlist(input.least, input.securityScoringRows);
  const requiredPreferredEvidence = sortedUnique(input.requiredPreferredEvidence);
  const requiredLeastEvidence = sortedUnique(input.requiredLeastEvidence);
  return {
    selection_status: "SELECTED",
    preferred_direction_id: input.preferred,
    least_preferred_direction_id: input.least,
    preferred_security_shortlist_id: preferredList.id,
    preferred_security_shortlist_hash: preferredList.hash,
    least_preferred_security_shortlist_id: leastList.id,
    least_preferred_security_shortlist_hash: leastList.hash,
    security_scoring_contract_version: SECURITY_SCORING_CONTRACT_VERSION,
    security_scoring_contract_hash: SECURITY_SCORING_CONTRACT_HASH,
    allowed_preferred_security_ids: preferredList.tickers,
    allowed_least_preferred_security_ids: leastList.tickers,
    required_preferred_evidence_ids: requiredPreferredEvidence,
    required_least_preferred_evidence_ids: requiredLeastEvidence,
    required_final_evidence_ids: sortedUnique([
      ...requiredPreferredEvidence,
      ...requiredLeastEvidence,
    ]),
  };
}

function shortlist(
  directionId: string,
  scoringRows: readonly SectorSecurityScoringRow[],
): { id: string; hash: string; tickers: string[] } {
  const rows = scoringRows
    .filter((row) => row.direction_id === directionId && row.availability_status === "AVAILABLE")
    .sort(
      (left, right) =>
        (right.median_amount_20d_cny ?? Number.NEGATIVE_INFINITY) -
          (left.median_amount_20d_cny ?? Number.NEGATIVE_INFINITY) ||
        left.ts_code.localeCompare(right.ts_code),
    )
    .slice(0, SECTOR_SECURITY_SCORING_CONTRACT.shortlist_maximum_size_per_direction);
  const tickers = rows.map((row) => row.ts_code);
  const hash = canonicalHash({
    direction_id: directionId,
    security_scoring_contract_version: SECURITY_SCORING_CONTRACT_VERSION,
    security_scoring_contract_hash: SECURITY_SCORING_CONTRACT_HASH,
    rows,
  });
  return { id: `sector-shortlist:${directionId}:${hash.slice(-16)}`, hash, tickers };
}

function validateLegEvidence(
  output: SectorAgentOutputBase,
  claimRefs: readonly string[],
  requiredEvidenceIds: readonly string[],
  label: string,
  issues: string[],
): void {
  const referencedClaims = new Set(claimRefs);
  const evidence = new Set(
    output.claims
      .filter((claim) => referencedClaims.has(claim.claim_id))
      .flatMap((claim) => claim.evidence_ids),
  );
  if (!requiredEvidenceIds.every((evidenceId) => evidence.has(evidenceId))) {
    issues.push(`${label} conclusion claims do not cite every required decisive evidence id`);
  }
}

function decisiveEvidenceForDirection(
  directionId: string,
  selectionRole: "WINNER" | "LOSER",
  comparisons: readonly DirectionPairwiseComparisonSubmission[],
  resolutions: readonly AcceptedDirectionPairResolution[],
  claims: readonly z.infer<typeof ClaimSchemaV2>[],
): string[] {
  const comparisonById = new Map(comparisons.map((row) => [row.comparison_local_id, row]));
  const refs: string[] = [];
  for (const resolution of resolutions) {
    const wins =
      (resolution.direction_a_id === directionId && resolution.resolved_verdict === "A") ||
      (resolution.direction_b_id === directionId && resolution.resolved_verdict === "B");
    const loses =
      (resolution.direction_a_id === directionId && resolution.resolved_verdict === "B") ||
      (resolution.direction_b_id === directionId && resolution.resolved_verdict === "A");
    if (
      (selectionRole === "WINNER" ? !wins : !loses) ||
      resolution.qualifying_non_etf_criteria.length === 0
    ) {
      continue;
    }
    const submission = comparisonById.get(resolution.comparison_local_id);
    if (!submission) throw new Error("resolution cannot be joined to comparison submission");
    for (const result of submission.criterion_results) {
      if (resolution.decisive_voting_criteria.includes(result.criterion)) {
        refs.push(...result.claim_refs);
      }
    }
  }
  return evidenceForClaimRefs(refs, claims);
}

function evidenceForClaimRefs(
  refs: readonly string[],
  claims: readonly z.infer<typeof ClaimSchemaV2>[],
): string[] {
  const wanted = new Set(refs);
  return sortedUnique(
    claims.filter((claim) => wanted.has(claim.claim_id)).flatMap((claim) => claim.evidence_ids),
  );
}

function validatePicks(
  picks: SectorAgentOutputBase["long_picks"],
  allowed: readonly string[],
  directionId: string | null,
  actions: ReadonlySet<string>,
  label: string,
  issues: string[],
): void {
  const allowedSet = new Set(allowed);
  for (const pick of picks) {
    if (!allowedSet.has(pick.ts_code)) issues.push(`${label} pick is outside frozen shortlist`);
    if (pick.direction_local_id !== directionId) {
      issues.push(`${label} pick direction does not match directive`);
    }
    if (!actions.has(pick.position_action)) issues.push(`${label} pick action is not allowed`);
  }
}

function sortedUnique(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
}

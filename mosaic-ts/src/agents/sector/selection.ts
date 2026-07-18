import { createHash } from "node:crypto";
import type { z } from "zod";
import type { ClaimSchemaV2 } from "../evidence_contract.js";
import type { SectorAgentOutputBase, SectorRuntimeSelectionBinding } from "../types.js";
import type {
  AcceptedDirectionPairResolution,
  DirectionMatrixReduction,
  DirectionPairwiseComparisonSubmission,
  LeastPreferredEligibility,
  SingleDirectionQualificationResolution,
} from "./comparison.js";

export const SECURITY_SCORING_CONTRACT_VERSION = "sector_security_scoring_v1";
export const SECURITY_SCORING_CONTRACT_HASH = canonicalHash({
  contract_version: SECURITY_SCORING_CONTRACT_VERSION,
  universe: "frozen_role_security_universe",
  ordering: "snapshot_order_then_ts_code",
  model_visibility: "ticker_allowlist_only",
});

export interface SectorSecurityUniverseRow {
  ts_code: string;
  direction_id: string;
}

export interface SectorFinalSelectionRuntimeDirective {
  selection_status: "SELECTED" | "NO_QUALIFIED_DIRECTION";
  preferred_direction_id: string | null;
  least_preferred_status: "REQUIRED" | "NOT_QUALIFIED" | "NOT_APPLICABLE";
  least_preferred_direction_id: string | null;
  least_preferred_reason: LeastPreferredEligibility["reason"];
  preferred_security_shortlist_id: string | null;
  preferred_security_shortlist_hash: string | null;
  least_preferred_security_shortlist_id: string | null;
  least_preferred_security_shortlist_hash: string | null;
  security_scoring_contract_version: typeof SECURITY_SCORING_CONTRACT_VERSION;
  security_scoring_contract_hash: string;
  allowed_preferred_security_ids: string[];
  allowed_least_preferred_security_ids: string[];
  required_final_evidence_ids: string[];
}

export type ModelVisibleSectorFinalSelectionDirective = Pick<
  SectorFinalSelectionRuntimeDirective,
  | "selection_status"
  | "preferred_direction_id"
  | "least_preferred_status"
  | "least_preferred_direction_id"
  | "least_preferred_reason"
  | "allowed_preferred_security_ids"
  | "allowed_least_preferred_security_ids"
  | "required_final_evidence_ids"
>;

export function buildPairwiseFinalDirective(input: {
  reduction: DirectionMatrixReduction;
  leastEligibility: LeastPreferredEligibility;
  finalizedComparisons: readonly DirectionPairwiseComparisonSubmission[];
  resolutions: readonly AcceptedDirectionPairResolution[];
  comparisonClaims: readonly z.infer<typeof ClaimSchemaV2>[];
  securityUniverse: readonly SectorSecurityUniverseRow[];
}): SectorFinalSelectionRuntimeDirective {
  const preferred = input.reduction.condorcet_winner_direction_id;
  if (!preferred) {
    return noQualifiedDirective(
      "NOT_QUALIFIED",
      "PREFERRED_NOT_QUALIFIED",
      requiredUnresolvedEvidence(input),
    );
  }
  const least =
    input.leastEligibility.status === "REQUIRED"
      ? input.leastEligibility.least_preferred_direction_id
      : null;
  const requiredEvidence = decisiveEvidenceForDirection(
    preferred,
    input.finalizedComparisons,
    input.resolutions,
    input.comparisonClaims,
  );
  if (requiredEvidence.length === 0) {
    throw new Error("preferred direction has no decisive final evidence");
  }
  return selectedDirective({
    preferred,
    least,
    leastEligibility: input.leastEligibility,
    securityUniverse: input.securityUniverse,
    requiredEvidence,
  });
}

export function buildSingleDirectionFinalDirective(input: {
  qualification: SingleDirectionQualificationResolution;
  submission: {
    claim_refs: string[];
    criterion_results: DirectionPairwiseComparisonSubmission["criterion_results"];
  };
  comparisonClaims: readonly z.infer<typeof ClaimSchemaV2>[];
  securityUniverse: readonly SectorSecurityUniverseRow[];
}): SectorFinalSelectionRuntimeDirective {
  const evidence = evidenceForClaimRefs(input.submission.claim_refs, input.comparisonClaims);
  if (evidence.length === 0) {
    throw new Error("single-direction qualification has no final evidence");
  }
  if (input.qualification.status === "NOT_QUALIFIED") {
    return noQualifiedDirective("NOT_APPLICABLE", "SINGLE_ELIGIBLE_DIRECTION", evidence);
  }
  return selectedDirective({
    preferred: input.qualification.direction_id,
    least: null,
    leastEligibility: {
      status: "NOT_APPLICABLE",
      reason: "SINGLE_ELIGIBLE_DIRECTION",
      least_preferred_direction_id: null,
      qualifying_comparison_local_ids: [],
    },
    securityUniverse: input.securityUniverse,
    requiredEvidence: evidence,
  });
}

export function modelVisibleDirective(
  directive: SectorFinalSelectionRuntimeDirective,
): ModelVisibleSectorFinalSelectionDirective {
  return {
    selection_status: directive.selection_status,
    preferred_direction_id: directive.preferred_direction_id,
    least_preferred_status: directive.least_preferred_status,
    least_preferred_direction_id: directive.least_preferred_direction_id,
    least_preferred_reason: directive.least_preferred_reason,
    allowed_preferred_security_ids: directive.allowed_preferred_security_ids,
    allowed_least_preferred_security_ids: directive.allowed_least_preferred_security_ids,
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
  if (directive.selection_status === "NO_QUALIFIED_DIRECTION") {
    if ("direction_id" in output.preferred_direction) {
      issues.push("abstention cannot submit a preferred direction");
    }
    if ("direction_id" in output.least_preferred_direction) {
      issues.push("abstention cannot submit a least-preferred direction");
    } else if (output.least_preferred_direction.reason !== directive.least_preferred_reason) {
      issues.push("abstention least-preferred reason does not match directive");
    }
  } else {
    if (
      !("direction_id" in output.preferred_direction) ||
      output.preferred_direction.direction_id !== directive.preferred_direction_id
    ) {
      issues.push("preferred direction does not match runtime directive");
    }
    if (directive.least_preferred_status === "REQUIRED") {
      if (
        !("direction_id" in output.least_preferred_direction) ||
        output.least_preferred_direction.direction_id !== directive.least_preferred_direction_id
      ) {
        issues.push("least-preferred direction does not match runtime directive");
      }
    } else if ("direction_id" in output.least_preferred_direction) {
      issues.push("runtime did not qualify a least-preferred direction");
    } else if (output.least_preferred_direction.reason !== directive.least_preferred_reason) {
      issues.push("least-preferred reason does not match runtime directive");
    }
  }
  validatePicks(
    output.long_picks,
    directive.allowed_preferred_security_ids,
    "direction_local_id" in output.preferred_direction
      ? output.preferred_direction.direction_local_id
      : null,
    new Set(["LONG"]),
    "preferred",
    issues,
  );
  validatePicks(
    output.short_or_avoid_picks,
    directive.allowed_least_preferred_security_ids,
    "direction_local_id" in output.least_preferred_direction
      ? output.least_preferred_direction.direction_local_id
      : null,
    new Set(["SHORT", "AVOID"]),
    "least-preferred",
    issues,
  );
  const finalClaimIds = new Set(output.claim_refs);
  const finalEvidence = new Set(
    output.claims
      .filter((claim) => finalClaimIds.has(claim.claim_id))
      .flatMap((claim) => claim.evidence_ids),
  );
  if (!directive.required_final_evidence_ids.some((evidenceId) => finalEvidence.has(evidenceId))) {
    issues.push("final conclusion claims do not cite required decisive evidence");
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
    least_preferred_status: input.directive.least_preferred_status,
    least_preferred_direction_id: input.directive.least_preferred_direction_id,
    preferred_security_shortlist_id: input.directive.preferred_security_shortlist_id,
    preferred_security_shortlist_hash: input.directive.preferred_security_shortlist_hash,
    least_preferred_security_shortlist_id: input.directive.least_preferred_security_shortlist_id,
    least_preferred_security_shortlist_hash:
      input.directive.least_preferred_security_shortlist_hash,
    security_scoring_contract_version: input.directive.security_scoring_contract_version,
    security_scoring_contract_hash: input.directive.security_scoring_contract_hash,
    required_final_evidence_ids: input.directive.required_final_evidence_ids,
  };
  return { ...input.output, sector_runtime_binding: binding };
}

export function directionComparisonAuditHash(value: unknown): string {
  return canonicalHash({ contract: "sector_direction_comparison_audit_v1", value });
}

function selectedDirective(input: {
  preferred: string;
  least: string | null;
  leastEligibility: LeastPreferredEligibility;
  securityUniverse: readonly SectorSecurityUniverseRow[];
  requiredEvidence: string[];
}): SectorFinalSelectionRuntimeDirective {
  const preferredList = shortlist(input.preferred, input.securityUniverse);
  const leastList = input.least ? shortlist(input.least, input.securityUniverse) : null;
  return {
    selection_status: "SELECTED",
    preferred_direction_id: input.preferred,
    least_preferred_status: input.leastEligibility.status,
    least_preferred_direction_id: input.least,
    least_preferred_reason: input.leastEligibility.reason,
    preferred_security_shortlist_id: preferredList.id,
    preferred_security_shortlist_hash: preferredList.hash,
    least_preferred_security_shortlist_id: leastList?.id ?? null,
    least_preferred_security_shortlist_hash: leastList?.hash ?? null,
    security_scoring_contract_version: SECURITY_SCORING_CONTRACT_VERSION,
    security_scoring_contract_hash: SECURITY_SCORING_CONTRACT_HASH,
    allowed_preferred_security_ids: preferredList.tickers,
    allowed_least_preferred_security_ids: leastList?.tickers ?? [],
    required_final_evidence_ids: sortedUnique(input.requiredEvidence),
  };
}

function noQualifiedDirective(
  leastStatus: "NOT_QUALIFIED" | "NOT_APPLICABLE",
  leastReason: "PREFERRED_NOT_QUALIFIED" | "SINGLE_ELIGIBLE_DIRECTION",
  requiredEvidence: string[],
): SectorFinalSelectionRuntimeDirective {
  if (requiredEvidence.length === 0) {
    throw new Error("abstention directive requires comparison evidence");
  }
  return {
    selection_status: "NO_QUALIFIED_DIRECTION",
    preferred_direction_id: null,
    least_preferred_status: leastStatus,
    least_preferred_direction_id: null,
    least_preferred_reason: leastReason,
    preferred_security_shortlist_id: null,
    preferred_security_shortlist_hash: null,
    least_preferred_security_shortlist_id: null,
    least_preferred_security_shortlist_hash: null,
    security_scoring_contract_version: SECURITY_SCORING_CONTRACT_VERSION,
    security_scoring_contract_hash: SECURITY_SCORING_CONTRACT_HASH,
    allowed_preferred_security_ids: [],
    allowed_least_preferred_security_ids: [],
    required_final_evidence_ids: sortedUnique(requiredEvidence),
  };
}

function shortlist(
  directionId: string,
  universe: readonly SectorSecurityUniverseRow[],
): { id: string; hash: string; tickers: string[] } {
  const tickers = sortedUnique(
    universe.filter((row) => row.direction_id === directionId).map((row) => row.ts_code),
  );
  const hash = canonicalHash({
    direction_id: directionId,
    security_scoring_contract_version: SECURITY_SCORING_CONTRACT_VERSION,
    tickers,
  });
  return { id: `sector-shortlist:${directionId}:${hash.slice(-16)}`, hash, tickers };
}

function decisiveEvidenceForDirection(
  directionId: string,
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
    if (!wins || resolution.qualifying_non_etf_criteria.length === 0) continue;
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

function requiredUnresolvedEvidence(input: {
  reduction: DirectionMatrixReduction;
  finalizedComparisons: readonly DirectionPairwiseComparisonSubmission[];
  resolutions: readonly AcceptedDirectionPairResolution[];
  comparisonClaims: readonly z.infer<typeof ClaimSchemaV2>[];
}): string[] {
  const conflict = new Set(input.reduction.conflict_direction_ids);
  const ids = new Set(
    input.resolutions
      .filter(
        (row) =>
          row.resolved_verdict === "NO_CLEAR_WINNER" ||
          conflict.has(row.direction_a_id) ||
          conflict.has(row.direction_b_id),
      )
      .map((row) => row.comparison_local_id),
  );
  const refs = input.finalizedComparisons
    .filter((row) => ids.has(row.comparison_local_id))
    .flatMap((row) => row.claim_refs);
  return evidenceForClaimRefs(
    refs.length > 0 ? refs : input.finalizedComparisons.flatMap((row) => row.claim_refs),
    input.comparisonClaims,
  );
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

import { z } from "zod";

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);

export const EvidenceLedgerEntrySchema = z
  .object({
    evidence_id: z.string().min(1),
    run_id: z.string().min(1),
    snapshot_hash: Sha256Schema,
    source_kind: z.enum(["tool", "runtime_source", "derived_metric"]),
    tool_or_source: z.string().min(1),
    metric: z.string().min(1),
    value: z.unknown(),
    unit: z.string().min(1),
    as_of: z.string().min(1),
    lookback: z.string().min(1),
    freshness: z.enum(["current", "stale", "missing", "fallback", "tool_failed"]),
    fallback: z.boolean(),
    source_fingerprint: Sha256Schema,
    direction: z.enum(["positive", "negative", "neutral", "ambiguous"]),
    privacy_class: z.enum(["public_structured", "private_runtime", "licensed_private"]),
  })
  .strict();

export const ResearchClaimSchema = z
  .object({
    claim_id: z.string().min(1),
    claim_type: z.enum(["fact", "inference", "uncertainty"]),
    statement: z.string().min(1),
    structured_conclusion: z.record(z.string(), z.unknown()),
    evidence_refs: z.array(z.string().min(1)),
    research_rule_refs: z.array(z.string().min(1)),
    snapshot_hash: Sha256Schema,
  })
  .strict();

export const RecommendationClaimReferenceSchema = z
  .object({
    output_id: z.string().min(1),
    output_type: z.enum(["recommendation", "candidate", "position_decision", "portfolio_action"]),
    claim_refs: z.array(z.string().min(1)).min(1),
  })
  .strict();

export const ClaimEvidenceGraphSchema = z
  .object({
    schema_version: z.literal("evidence_claim_graph_v1"),
    run_id: z.string().min(1),
    snapshot_hash: Sha256Schema,
    evidence_ledger: z.array(EvidenceLedgerEntrySchema),
    claims: z.array(ResearchClaimSchema),
    recommendation_claim_refs: z.array(RecommendationClaimReferenceSchema),
  })
  .strict();

export type EvidenceLedgerEntry = z.infer<typeof EvidenceLedgerEntrySchema>;
export type ResearchClaim = z.infer<typeof ResearchClaimSchema>;
export type RecommendationClaimReference = z.infer<typeof RecommendationClaimReferenceSchema>;
export type ClaimEvidenceGraph = z.infer<typeof ClaimEvidenceGraphSchema>;

export interface ClaimEvidenceGraphValidationResult {
  accepted: boolean;
  reasons: string[];
}

export function validateClaimEvidenceGraph(
  graphInput: unknown,
  opts: {
    expectedRunId?: string;
    expectedSnapshotHash?: string;
    runtimeOwnedEvidenceIds?: ReadonlySet<string>;
    allowFallbackEvidenceIds?: ReadonlySet<string>;
  } = {},
): ClaimEvidenceGraphValidationResult {
  const parsed = ClaimEvidenceGraphSchema.safeParse(graphInput);
  if (!parsed.success) {
    return {
      accepted: false,
      reasons: parsed.error.issues.map(
        (issue) => `claim_evidence_schema:${issue.path.join(".")}:${issue.message}`,
      ),
    };
  }
  const graph = parsed.data;
  const reasons: string[] = [];
  if (opts.expectedRunId && graph.run_id !== opts.expectedRunId) {
    reasons.push(`claim_evidence_run_mismatch:${graph.run_id}:expected:${opts.expectedRunId}`);
  }
  if (opts.expectedSnapshotHash && graph.snapshot_hash !== opts.expectedSnapshotHash) {
    reasons.push(
      `claim_evidence_snapshot_mismatch:${graph.snapshot_hash}:expected:${opts.expectedSnapshotHash}`,
    );
  }

  const evidenceById = uniqueById(
    graph.evidence_ledger,
    (entry) => entry.evidence_id,
    "duplicate_evidence_id",
    reasons,
  );
  const claimsById = uniqueById(
    graph.claims,
    (claim) => claim.claim_id,
    "duplicate_claim_id",
    reasons,
  );
  uniqueById(
    graph.recommendation_claim_refs,
    (reference) => reference.output_id,
    "duplicate_output_claim_reference",
    reasons,
  );

  for (const evidence of graph.evidence_ledger) {
    if (evidence.run_id !== graph.run_id) {
      reasons.push(`evidence_run_mismatch:${evidence.evidence_id}`);
    }
    if (evidence.snapshot_hash !== graph.snapshot_hash) {
      reasons.push(`evidence_snapshot_mismatch:${evidence.evidence_id}`);
    }
    if (evidence.fallback !== (evidence.freshness === "fallback")) {
      reasons.push(`evidence_fallback_flag_mismatch:${evidence.evidence_id}`);
    }
    if (opts.runtimeOwnedEvidenceIds && !opts.runtimeOwnedEvidenceIds.has(evidence.evidence_id)) {
      reasons.push(`evidence_id_not_runtime_owned:${evidence.evidence_id}`);
    }
  }

  for (const claim of graph.claims) {
    if (claim.snapshot_hash !== graph.snapshot_hash) {
      reasons.push(`claim_snapshot_mismatch:${claim.claim_id}`);
    }
    if (claim.claim_type !== "uncertainty" && claim.evidence_refs.length === 0) {
      reasons.push(`claim_evidence_required:${claim.claim_id}`);
    }
    if (claim.claim_type === "inference" && claim.research_rule_refs.length === 0) {
      reasons.push(`claim_rule_required:${claim.claim_id}`);
    }
    for (const evidenceId of claim.evidence_refs) {
      const evidence = evidenceById.get(evidenceId);
      if (!evidence) {
        reasons.push(`claim_unknown_evidence_ref:${claim.claim_id}:${evidenceId}`);
        continue;
      }
      if (["stale", "missing", "tool_failed"].includes(evidence.freshness)) {
        reasons.push(`claim_unsupported_evidence:${claim.claim_id}:${evidenceId}`);
      }
      if (
        evidence.freshness === "fallback" &&
        !opts.allowFallbackEvidenceIds?.has(evidence.evidence_id)
      ) {
        reasons.push(`claim_unapproved_fallback_evidence:${claim.claim_id}:${evidenceId}`);
      }
    }
  }

  for (const reference of graph.recommendation_claim_refs) {
    for (const claimId of reference.claim_refs) {
      if (!claimsById.has(claimId)) {
        reasons.push(`output_unknown_claim_ref:${reference.output_id}:${claimId}`);
      }
    }
  }
  return { accepted: reasons.length === 0, reasons };
}

function uniqueById<T>(
  items: ReadonlyArray<T>,
  idFor: (item: T) => string,
  duplicateReason: string,
  reasons: string[],
): Map<string, T> {
  const byId = new Map<string, T>();
  for (const item of items) {
    const id = idFor(item);
    if (byId.has(id)) reasons.push(`${duplicateReason}:${id}`);
    byId.set(id, item);
  }
  return byId;
}

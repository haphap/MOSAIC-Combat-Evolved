import { describe, expect, it } from "vitest";
import {
  type ClaimEvidenceGraph,
  validateClaimEvidenceGraph,
} from "../src/agents/evidence_contract.js";

const SNAPSHOT_HASH = `sha256:${"1".repeat(64)}`;
const SOURCE_HASH = `sha256:${"2".repeat(64)}`;

function validGraph(): ClaimEvidenceGraph {
  return {
    schema_version: "evidence_claim_graph_v1",
    run_id: "run-1",
    snapshot_hash: SNAPSHOT_HASH,
    evidence_ledger: [
      {
        evidence_id: "ev-1",
        run_id: "run-1",
        snapshot_hash: SNAPSHOT_HASH,
        source_kind: "tool",
        tool_or_source: "get_stock_data",
        metric: "close_return_20d",
        value: 0.08,
        unit: "ratio",
        as_of: "2026-07-10",
        lookback: "20d",
        freshness: "current",
        fallback: false,
        source_fingerprint: SOURCE_HASH,
        direction: "positive",
        privacy_class: "public_structured",
      },
    ],
    claims: [
      {
        claim_id: "claim-1",
        claim_type: "inference",
        statement: "Momentum is positive on current data.",
        structured_conclusion: { signal: "positive" },
        evidence_refs: ["ev-1"],
        research_rule_refs: ["sector.semiconductor.soft.001"],
        snapshot_hash: SNAPSHOT_HASH,
      },
    ],
    recommendation_claim_refs: [
      {
        output_id: "action-1",
        output_type: "portfolio_action",
        claim_refs: ["claim-1"],
      },
    ],
  };
}

describe("claim-to-evidence graph", () => {
  it("accepts a runtime-owned same-snapshot graph", () => {
    const result = validateClaimEvidenceGraph(validGraph(), {
      expectedRunId: "run-1",
      expectedSnapshotHash: SNAPSHOT_HASH,
      runtimeOwnedEvidenceIds: new Set(["ev-1"]),
    });

    expect(result).toEqual({ accepted: true, reasons: [] });
  });

  it("rejects dangling evidence and action claim references", () => {
    const graph = validGraph();
    graph.claims[0]?.evidence_refs.push("ev-missing");
    graph.recommendation_claim_refs[0]?.claim_refs.push("claim-missing");

    const result = validateClaimEvidenceGraph(graph);

    expect(result.accepted).toBe(false);
    expect(result.reasons).toEqual(
      expect.arrayContaining([
        "claim_unknown_evidence_ref:claim-1:ev-missing",
        "output_unknown_claim_ref:action-1:claim-missing",
      ]),
    );
  });

  it("rejects cross-snapshot and non-runtime evidence ids", () => {
    const graph = validGraph();
    if (graph.evidence_ledger[0]) {
      graph.evidence_ledger[0].snapshot_hash = `sha256:${"3".repeat(64)}`;
    }

    const result = validateClaimEvidenceGraph(graph, {
      runtimeOwnedEvidenceIds: new Set(["different-id"]),
    });

    expect(result.reasons).toEqual(
      expect.arrayContaining([
        "evidence_snapshot_mismatch:ev-1",
        "evidence_id_not_runtime_owned:ev-1",
      ]),
    );
  });

  it("rejects mutation of a runtime-owned evidence payload", () => {
    const graph = validGraph();
    const runtimeEvidence = structuredClone(graph.evidence_ledger[0]);
    if (!runtimeEvidence || !graph.evidence_ledger[0]) return;
    graph.evidence_ledger[0].value = 0.99;

    const result = validateClaimEvidenceGraph(graph, {
      runtimeOwnedEvidenceById: new Map([[runtimeEvidence.evidence_id, runtimeEvidence]]),
    });

    expect(result.reasons).toContain("runtime_evidence_payload_mismatch:ev-1");
  });

  it("requires every declared output to have a supported claim chain", () => {
    const missing = validateClaimEvidenceGraph(validGraph(), {
      requiredOutputIds: new Set(["action-1", "action-2"]),
    });
    expect(missing.reasons).toContain("required_output_claim_reference_missing:action-2");

    const uncertaintyGraph = validGraph();
    const claim = uncertaintyGraph.claims[0];
    if (!claim) return;
    claim.claim_type = "uncertainty";
    claim.evidence_refs = [];
    claim.research_rule_refs = [];
    const rejected = validateClaimEvidenceGraph(uncertaintyGraph);
    expect(rejected.reasons).toContain("output_only_uncertainty_claims:action-1");

    const allowed = validateClaimEvidenceGraph(uncertaintyGraph, {
      allowUncertaintyOnlyOutputIds: new Set(["action-1"]),
    });
    expect(allowed).toEqual({ accepted: true, reasons: [] });
  });

  it("rejects stale, failed, or unapproved fallback evidence", () => {
    for (const freshness of ["stale", "tool_failed", "fallback"] as const) {
      const graph = validGraph();
      if (graph.evidence_ledger[0]) {
        graph.evidence_ledger[0].freshness = freshness;
        graph.evidence_ledger[0].fallback = freshness === "fallback";
      }

      const result = validateClaimEvidenceGraph(graph);

      expect(result.accepted).toBe(false);
      expect(result.reasons.join("|")).toContain(
        freshness === "fallback"
          ? "claim_unapproved_fallback_evidence"
          : "claim_unsupported_evidence",
      );
    }
  });

  it("allows explicitly compatible fallback evidence", () => {
    const graph = validGraph();
    if (graph.evidence_ledger[0]) {
      graph.evidence_ledger[0].freshness = "fallback";
      graph.evidence_ledger[0].fallback = true;
    }

    const result = validateClaimEvidenceGraph(graph, {
      allowFallbackEvidenceIds: new Set(["ev-1"]),
    });

    expect(result).toEqual({ accepted: true, reasons: [] });
  });
});

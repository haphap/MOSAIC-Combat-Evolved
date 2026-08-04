import { describe, expect, it } from "vitest";
import {
  buildRuntimeEvidenceSnapshot,
  selectOutputByClaimEvidence,
  validateOutputByClaimEvidence,
} from "../src/agents/helpers/evidence_runtime.js";
import type { DailyCycleStateType } from "../src/agents/state.js";

const HASH = `sha256:${"1".repeat(64)}`;

function state(): DailyCycleStateType {
  return {
    trace_id: "evidence-run",
    as_of_date: "2026-07-09",
    active_cohort: "cohort_default",
    layer1_outputs: {},
    layer2_outputs: {},
    layer3_outputs: {},
    layer4_outputs: {},
  } as DailyCycleStateType;
}

function runtime() {
  return buildRuntimeEvidenceSnapshot({
    state: state(),
    agent: "china",
    stage: "agent_run",
    toolStatuses: [
      {
        name: "get_china_macro_snapshot",
        call_id: "call-1",
        called: true,
        failed: false,
        missing: false,
        fallback: false,
        cache_hit: false,
        args: {},
        as_of: "2026-07-09",
        source_fingerprint: HASH,
        result_fingerprint: HASH,
      },
    ],
    allowedResearchRuleIds: ["citation:official-release"],
  });
}

function output(evidenceId: string) {
  return {
    claims: [
      {
        claim_id: "claim-1",
        claim_kind: "FACT" as const,
        statement: "The frozen China macro snapshot supports the conclusion.",
        structured_conclusion: { direction: "supportive" },
        evidence_ids: [evidenceId],
        research_rule_refs: ["citation:official-release"],
      },
    ],
    claim_refs: ["claim-1"],
  };
}

describe("runtime evidence", () => {
  it("builds deterministic evidence identity from ordinary tool status", () => {
    const first = runtime();
    const second = runtime();
    expect(first.snapshotHash).toBe(second.snapshotHash);
    expect(first.agentInvocationId).toBe(second.agentInvocationId);
    expect(first.evidenceLedger).toEqual(second.evidenceLedger);
    expect(first.evidenceLedger).toHaveLength(1);
    expect(first.visibleCatalog).toContain("get_china_macro_snapshot");
  });

  it("accepts claims bound to frozen runtime evidence and allowed citations", () => {
    const snapshot = runtime();
    const evidenceId = snapshot.evidenceLedger[0]?.evidence_id;
    if (!evidenceId) throw new Error("evidence fixture missing");
    const result = validateOutputByClaimEvidence(output(evidenceId), snapshot);
    expect(result.rawOutputAccepted).toBe(true);
    expect(result.rejectionReasons).toEqual([]);
    expect(result.output).toHaveProperty("verified_claim_graph");
  });

  it("rejects invented evidence ids without rewriting the raw output", () => {
    const snapshot = runtime();
    const raw = output("invented-evidence");
    const result = validateOutputByClaimEvidence(raw, snapshot);
    expect(result.rawOutputAccepted).toBe(false);
    expect(result.output).toBe(raw);
    expect(result.rejectionReasons.join(" ")).toMatch(/evidence/i);
  });

  it("uses an explicit deterministic fallback only on the fallback selection path", () => {
    const snapshot = runtime();
    const fallback = { disposition: "BLOCKED", claims: [], claim_refs: [] };
    const result = selectOutputByClaimEvidence(
      output("invented-evidence"),
      () => fallback,
      snapshot,
    );
    expect(result.rawOutputAccepted).toBe(false);
    expect(result.output).toHaveProperty("verified_claim_audit.fallback_reason_code");
  });
});

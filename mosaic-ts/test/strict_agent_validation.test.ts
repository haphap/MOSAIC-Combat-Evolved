import { describe, expect, it } from "vitest";
import { z } from "zod";
import type { RuntimeEvidenceSnapshot } from "../src/agents/helpers/evidence_runtime.js";
import { validateStrictAgentOutput } from "../src/agents/helpers/strict_agent_validation.js";

const HASH = `sha256:${"1".repeat(64)}`;
const EVIDENCE_ID = "runtime-evidence:strict-agent-validation";
const schema = z
  .object({
    claims: z.array(z.unknown()),
    claim_refs: z.array(z.string()),
  })
  .passthrough();

function claimOutput() {
  return {
    claims: [
      {
        claim_id: "claim-1",
        claim_kind: "FACT" as const,
        statement: "Runtime evidence is available.",
        structured_conclusion: { available: true },
        evidence_ids: [EVIDENCE_ID],
        research_rule_refs: [],
      },
    ],
    claim_refs: ["claim-1"],
  };
}

function runtimeEvidence(agentId = "china"): RuntimeEvidenceSnapshot {
  const evidence = {
    evidence_id: EVIDENCE_ID,
    run_id: "run-1",
    snapshot_hash: HASH,
    source_kind: "runtime_source" as const,
    tool_or_source: "strict_test_source",
    metric: "availability",
    value: true,
    unit: "boolean",
    as_of: "2026-07-09",
    lookback: "point_in_time",
    freshness: "current" as const,
    fallback: false,
    source_fingerprint: HASH,
    direction: "neutral" as const,
    privacy_class: "public_structured" as const,
  };
  return {
    runId: "run-1",
    agentId,
    agentInvocationId: "agent-invocation:strict",
    stage: "agent_run",
    snapshotHash: HASH,
    evidenceLedger: [evidence],
    evidenceById: new Map([[evidence.evidence_id, evidence]]),
    allowedResearchRuleIds: new Set(),
    visibleCatalog: "",
  };
}

describe("strict Agent output validation", () => {
  it("enforces the supplied schema before evidence validation", () => {
    const result = validateStrictAgentOutput({
      output: { claims: [], claim_refs: [], forbidden: true } as unknown as {
        claims: unknown[];
        claim_refs: string[];
      },
      schema: z.object({ claims: z.array(z.unknown()), claim_refs: z.array(z.string()) }).strict(),
      agent: "china",
      stage: "agent_run",
      runtimeEvidence: null,
    });
    expect(result.issues).toContainEqual(
      expect.objectContaining({ validator: "zod_schema", reason_code: "ZOD_UNRECOGNIZED_KEYS" }),
    );
  });

  it("accepts a schema-valid claim graph bound to runtime evidence", () => {
    const result = validateStrictAgentOutput({
      output: claimOutput(),
      schema,
      agent: "china",
      stage: "agent_run",
      runtimeEvidence: runtimeEvidence(),
    });
    expect(result.issues).toEqual([]);
    expect(result.output).toHaveProperty("verified_claim_graph");
  });

  it("rejects runtime evidence belonging to another Agent", () => {
    const result = validateStrictAgentOutput({
      output: claimOutput(),
      schema,
      agent: "china",
      stage: "agent_run",
      runtimeEvidence: runtimeEvidence("us_economy"),
    });
    expect(result.issues).toContainEqual(
      expect.objectContaining({ reason_code: "RUNTIME_EVIDENCE_AGENT_MISMATCH" }),
    );
  });

  it("runs deterministic role semantics without output rewriting", () => {
    const output = claimOutput();
    const result = validateStrictAgentOutput({
      output,
      schema,
      agent: "china",
      stage: "agent_run",
      runtimeEvidence: runtimeEvidence(),
      validateRoleContract: () => [
        {
          validator: "china.role.v1",
          reason_code: "ROLE_REJECTED",
          json_path: "$",
          message: "role boundary violated",
        },
      ],
    });
    expect(result.issues).toContainEqual(expect.objectContaining({ reason_code: "ROLE_REJECTED" }));
    expect(result.output).not.toHaveProperty("private_knot_audit");
  });
});

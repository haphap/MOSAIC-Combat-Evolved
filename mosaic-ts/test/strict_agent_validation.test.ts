import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import type { RuntimeEvidenceSnapshot } from "../src/agents/helpers/evidence_runtime.js";
import {
  buildAgentInvocationId,
  clearPrivateKnotRuntimeForTests,
  installPrivateKnotRuntime,
  type PrivateKnotSnapshot,
  preparePrivateKnotModelContext,
  preparePrivateKnotSnapshot,
} from "../src/agents/helpers/private_knot_boundary.js";
import { validateStrictAgentOutput } from "../src/agents/helpers/strict_agent_validation.js";

const HASH = `sha256:${"1".repeat(64)}`;
const EVIDENCE_ID = "runtime-evidence:strict-agent-validation";

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

function runtimeEvidenceFor(snapshot: PrivateKnotSnapshot): RuntimeEvidenceSnapshot {
  const evidence = {
    evidence_id: EVIDENCE_ID,
    run_id: snapshot.graph_run_id,
    snapshot_hash: snapshot.snapshot_hash,
    source_kind: "runtime_source" as const,
    tool_or_source: "strict_test_source",
    metric: "availability",
    value: true,
    unit: "boolean",
    as_of: snapshot.as_of,
    lookback: "point_in_time",
    freshness: "current" as const,
    fallback: false,
    source_fingerprint: HASH,
    direction: "neutral" as const,
    privacy_class: "public_structured" as const,
  };
  return {
    runId: snapshot.graph_run_id,
    agentId: snapshot.agent,
    agentInvocationId: snapshot.agent_invocation_id,
    stage: snapshot.stage,
    snapshotHash: snapshot.snapshot_hash,
    evidenceLedger: [evidence],
    evidenceById: new Map([[evidence.evidence_id, evidence]]),
    allowedResearchRuleIds: new Set(),
    visibleCatalog: "",
    modelContextHash: modelContextHash(snapshot),
    effectiveModelInputHash: HASH,
  };
}

function modelContextHash(snapshot: PrivateKnotSnapshot): string {
  return canonicalJsonHash({
    schema_version: "private_knot_model_context_v1",
    snapshot_hash: snapshot.snapshot_hash,
    context: [],
  });
}

function adapterLifecycle() {
  return {
    prepareModelContext: async ({ snapshot }: { snapshot: PrivateKnotSnapshot }) => ({
      context: [],
      context_hash: modelContextHash(snapshot),
      audit: {
        snapshot_hash: snapshot.snapshot_hash,
        disposition: "NOT_TRIGGERED" as const,
        envelope_hashes: [],
      },
    }),
    finalize: () => undefined,
  };
}

async function consumeModelContext(snapshot: PrivateKnotSnapshot): Promise<void> {
  await preparePrivateKnotModelContext({
    snapshot,
    initialToolResults: [
      {
        tool_name: "get_china_macro_snapshot",
        tool_call_id: "initial_tool_1",
        agent_invocation_id: snapshot.agent_invocation_id,
        args: {},
        payload: { as_of: snapshot.as_of },
        args_fingerprint: HASH,
        result_fingerprint: HASH,
        source_fingerprint: HASH,
        as_of: snapshot.as_of,
        status: "CURRENT",
      },
    ],
  });
}

function invocationBinding(agent = "china", stage = "agent_run" as const) {
  return {
    invocation_mode: "NON_PRODUCTION_TEST" as const,
    graph_run_id: "strict-agent-validation-run",
    agent_invocation_id: buildAgentInvocationId({
      runId: "strict-agent-validation-run",
      agent,
      stage,
      cohort: "cohort_default",
      asOf: "2026-07-09",
      promptReleaseHash: HASH,
    }),
    as_of: "2026-07-09",
    execution_behavior_release_id: "non-production-test",
    prompt_release_id: "non-production-test",
    prompt_release_hash: HASH,
    prompt_pair_hash: HASH,
    prompt_commit: "non-production",
  };
}

describe("private KNOT policy evidence inputs", () => {
  afterEach(() => clearPrivateKnotRuntimeForTests());

  it("enforces the supplied public schema before evidence or private policy validation", () => {
    const invalid = { claims: [], claim_refs: [], forbidden: true } as unknown as {
      claims: unknown[];
      claim_refs: string[];
    };
    const result = validateStrictAgentOutput({
      output: invalid,
      schema: z.object({ claims: z.array(z.unknown()), claim_refs: z.array(z.string()) }).strict(),
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      runtimeEvidence: null,
      knobSnapshot: null,
      toolStatuses: [],
    });

    expect(result.issues).toContainEqual(
      expect.objectContaining({ validator: "zod_schema", reason_code: "ZOD_UNRECOGNIZED_KEYS" }),
    );
  });

  it("rejects an audit that is not bound to the supplied snapshot", async () => {
    let policyInputKeys: string[] = [];
    installPrivateKnotRuntime({
      ...adapterLifecycle(),
      describe: () => ({
        knot_runtime_contract_manifest_hash: HASH,
        private_runtime_manifest_hash: HASH,
      }),
      isStageEnabled: () => true,
      prepareSnapshot: async (input) => {
        const { runtimeSourceStatuses, ...binding } = input;
        return {
          snapshot_id: HASH,
          snapshot_hash: HASH,
          ...binding,
          evidence_bindings: [],
          allowed_research_rule_ids: [],
          runtime_source_statuses: [...runtimeSourceStatuses],
        };
      },
      applyPolicy: (input) => {
        policyInputKeys = Object.keys(input).sort();
        return {
          output: input.output,
          audit: {
            snapshot_hash: `sha256:${"2".repeat(64)}`,
            accepted: true,
            output_selection: "raw",
            reason_codes: [],
            tool_status_summary: { called: 0, failed: 0, missing: 0, fallback: 0, cache_hit: 0 },
            runtime_source_status_summary: {
              loaded: 0,
              empty_confirmed: 0,
              missing: 0,
              stale: 0,
              source_error: 0,
            },
          },
        };
      },
    });
    const binding = invocationBinding();
    const snapshot = await preparePrivateKnotSnapshot({
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      ...binding,
      runtimeSourceStatuses: [],
    });
    await consumeModelContext(snapshot);

    const result = validateStrictAgentOutput({
      output: claimOutput(),
      schema: z.object({ claims: z.array(z.unknown()), claim_refs: z.array(z.string()) }),
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      runtimeEvidence: runtimeEvidenceFor(snapshot),
      knobSnapshot: snapshot,
      toolStatuses: [],
    });

    expect(result.issues).toContainEqual(
      expect.objectContaining({ reason_code: "PRIVATE_KNOT_AUDIT_SNAPSHOT_MISMATCH" }),
    );
    expect(policyInputKeys).toEqual(["output", "snapshot", "toolStatuses"]);
  });

  it("does not consume one-use policy before deterministic validation succeeds", async () => {
    let policyCalls = 0;
    installPrivateKnotRuntime({
      ...adapterLifecycle(),
      describe: () => ({
        knot_runtime_contract_manifest_hash: HASH,
        private_runtime_manifest_hash: HASH,
      }),
      isStageEnabled: () => true,
      prepareSnapshot: async (input) => {
        const { runtimeSourceStatuses, ...binding } = input;
        return {
          snapshot_id: HASH,
          snapshot_hash: HASH,
          ...binding,
          evidence_bindings: [],
          allowed_research_rule_ids: [],
          runtime_source_statuses: [...runtimeSourceStatuses],
        };
      },
      applyPolicy: ({ snapshot, output }) => {
        policyCalls += 1;
        return {
          output,
          audit: {
            snapshot_hash: snapshot.snapshot_hash,
            accepted: true,
            output_selection: "raw",
            reason_codes: [],
            tool_status_summary: {
              called: 0,
              failed: 0,
              missing: 0,
              fallback: 0,
              cache_hit: 0,
            },
            runtime_source_status_summary: {
              loaded: 0,
              empty_confirmed: 0,
              missing: 0,
              stale: 0,
              source_error: 0,
            },
          },
        };
      },
    });
    const snapshot = await preparePrivateKnotSnapshot({
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      ...invocationBinding(),
      runtimeSourceStatuses: [],
    });
    await consumeModelContext(snapshot);
    const common = {
      output: claimOutput(),
      schema: z.object({ claims: z.array(z.unknown()), claim_refs: z.array(z.string()) }),
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      runtimeEvidence: runtimeEvidenceFor(snapshot),
      knobSnapshot: snapshot,
      toolStatuses: [],
    };

    const rejected = validateStrictAgentOutput({
      ...common,
      validateBeforePrivatePolicy: () => [
        {
          validator: "role_contract",
          reason_code: "ROLE_CONTRACT_MISMATCH",
          json_path: "$",
          message: "repairable deterministic mismatch",
        },
      ],
    });
    expect(rejected.issues).toContainEqual(
      expect.objectContaining({ reason_code: "ROLE_CONTRACT_MISMATCH" }),
    );
    expect(policyCalls).toBe(0);

    const accepted = validateStrictAgentOutput({
      ...common,
      validateBeforePrivatePolicy: () => [],
    });
    expect(accepted.issues).toEqual([]);
    expect(policyCalls).toBe(1);
  });

  it.each([
    {
      name: "snapshot",
      runtime: { agentId: "china", stage: "agent_run", snapshotHash: `sha256:${"2".repeat(64)}` },
      reason: "RUNTIME_EVIDENCE_PRIVATE_SNAPSHOT_MISMATCH",
    },
    {
      name: "agent",
      runtime: { agentId: "central_bank", stage: "agent_run", snapshotHash: HASH },
      reason: "RUNTIME_EVIDENCE_AGENT_MISMATCH",
    },
    {
      name: "stage",
      runtime: { agentId: "china", stage: "cro_review", snapshotHash: HASH },
      reason: "RUNTIME_EVIDENCE_STAGE_MISMATCH",
    },
  ])("rejects cross-$name runtime evidence", ({ runtime, reason }) => {
    const snapshot: PrivateKnotSnapshot = {
      snapshot_id: HASH,
      snapshot_hash: HASH,
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      ...invocationBinding(),
      evidence_bindings: [],
      allowed_research_rule_ids: [],
      runtime_source_statuses: [],
    };
    const runtimeEvidence: RuntimeEvidenceSnapshot = {
      runId: "run-1",
      agentId: runtime.agentId,
      agentInvocationId: "invocation-1",
      stage: runtime.stage as RuntimeEvidenceSnapshot["stage"],
      snapshotHash: runtime.snapshotHash,
      evidenceLedger: [],
      evidenceById: new Map(),
      allowedResearchRuleIds: new Set(),
      visibleCatalog: "",
      modelContextHash: HASH,
      effectiveModelInputHash: HASH,
    };

    const result = validateStrictAgentOutput({
      output: { claims: [], claim_refs: [] },
      schema: z.object({ claims: z.array(z.unknown()), claim_refs: z.array(z.string()) }),
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      runtimeEvidence,
      knobSnapshot: snapshot,
      toolStatuses: [],
    });

    expect(result.issues).toContainEqual(expect.objectContaining({ reason_code: reason }));
  });

  it("rejects a private snapshot whose public id is not its hash", () => {
    const result = validateStrictAgentOutput({
      output: { claims: [], claim_refs: [] },
      schema: z.object({ claims: z.array(z.unknown()), claim_refs: z.array(z.string()) }),
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      runtimeEvidence: null,
      knobSnapshot: {
        snapshot_id: "snapshot-alias",
        snapshot_hash: HASH,
        agent: "china",
        stage: "agent_run",
        cohort: "cohort_default",
        ...invocationBinding(),
        evidence_bindings: [],
        allowed_research_rule_ids: [],
        runtime_source_statuses: [],
      },
      toolStatuses: [],
    });
    expect(result.issues).toContainEqual(
      expect.objectContaining({ reason_code: "PRIVATE_KNOT_SNAPSHOT_ID_HASH_MISMATCH" }),
    );
  });

  it.each([
    ["agent", { agent: "central_bank" }, "PRIVATE_KNOT_SNAPSHOT_AGENT_MISMATCH"],
    ["stage", { stage: "cro_review" as const }, "PRIVATE_KNOT_SNAPSHOT_STAGE_MISMATCH"],
    ["cohort", { cohort: "crisis_2008" }, "PRIVATE_KNOT_SNAPSHOT_COHORT_MISMATCH"],
  ])("rejects cross-%s private snapshot reuse", (_name, patch, reason) => {
    const snapshot: PrivateKnotSnapshot = {
      snapshot_id: HASH,
      snapshot_hash: HASH,
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      ...invocationBinding(),
      evidence_bindings: [],
      allowed_research_rule_ids: [],
      runtime_source_statuses: [],
      ...patch,
    };

    const result = validateStrictAgentOutput({
      output: { claims: [], claim_refs: [] },
      schema: z.object({ claims: z.array(z.unknown()), claim_refs: z.array(z.string()) }),
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      runtimeEvidence: null,
      knobSnapshot: snapshot,
      toolStatuses: [],
    });

    expect(result.issues).toContainEqual(expect.objectContaining({ reason_code: reason }));
  });
});

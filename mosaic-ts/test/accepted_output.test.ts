import { describe, expect, it } from "vitest";
import {
  AcceptedAgentOutputStore,
  type AcceptedOutputBuildContext,
  acceptedOutputRecordRef,
  acceptedOutputRefKey,
  buildAcceptedAgentOutputRecord,
  validateAcceptedAgentOutputRecord,
} from "../src/agents/accepted_output.js";

function context(
  runBinding: AcceptedOutputBuildContext["run_binding"] = {
    sample_origin: "PRODUCTION_ACTIVE",
    run_slot_kind: "OUTCOME_SCHEDULED",
    scheduled_sample_id: "sample:china",
  },
): AcceptedOutputBuildContext {
  return {
    graph_run_id: "graph-run-1",
    run_id: "agent-run-china",
    run_slot_id: "slot:china",
    operational_opportunity_audit_id: "operational:china",
    production_variant_roster_id: "roster:1",
    production_variant_roster_revision_id: "roster-revision:1",
    execution_behavior_release_id: "release:1",
    cohort_id: "cohort_default",
    language: "zh",
    track_key_hash: `sha256:${"1".repeat(64)}`,
    agent_contract_version: "macro-agent-v2",
    prompt_behavior_version: "prompt-v2",
    execution_behavior_version: "execution-v2",
    component_weight_contract_version: null,
    reliability_adapter_contract_version: null,
    confidence_semantics_contract_version: null,
    as_of: "2026-07-17T00:00:00+08:00",
    accepted_at: "2026-07-17T00:00:00+08:00",
    run_binding: runBinding,
  };
}

function macroRecord() {
  return buildAcceptedAgentOutputRecord({
    kind: "MACRO_TRANSMISSION",
    agentId: "china",
    payload: { agent_id: "china", direction: "SUPPORTIVE" },
    evidenceBundleIds: ["bundle:2", "bundle:1"],
    causalDedupeKeys: ["cause:2", "cause:1"],
    context: context(),
  });
}

describe("AcceptedAgentOutputRecord", () => {
  it("creates a namespace-safe deterministic record and exact reference", () => {
    const record = macroRecord();
    validateAcceptedAgentOutputRecord(record);
    expect(record.accepted_output_id).toMatch(/^accepted-output:/);
    expect(record.accepted_output_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(record.output.evidence_bundle_ids).toEqual(["bundle:1", "bundle:2"]);
    expect(acceptedOutputRecordRef(record)).toEqual({
      accepted_output_kind: "MACRO_TRANSMISSION",
      agent_id: "china",
      accepted_output_id: record.accepted_output_id,
      accepted_output_hash: record.accepted_output_hash,
    });
    expect(acceptedOutputRefKey("MACRO_TRANSMISSION", "china")).toBe("MACRO_TRANSMISSION:china");
    expect(acceptedOutputRefKey("CIO_PROPOSAL", "cio")).not.toBe(
      acceptedOutputRefKey("CIO_FINAL", "cio"),
    );
  });

  it("rejects owner, hash and namespace mismatches", () => {
    expect(() =>
      buildAcceptedAgentOutputRecord({
        kind: "MACRO_TRANSMISSION",
        agentId: "cio" as never,
        payload: {},
        evidenceBundleIds: ["bundle:1"],
        causalDedupeKeys: ["cause:1"],
        context: context(),
      }),
    ).toThrow(/cannot be owned/);
    const record = macroRecord();
    expect(() =>
      validateAcceptedAgentOutputRecord({
        ...record,
        accepted_output_hash: `sha256:${"0".repeat(64)}`,
      }),
    ).toThrow(/hash mismatch/);
  });

  it("enforces the scheduled/downstream-only sample-origin matrix", () => {
    expect(() =>
      context({
        sample_origin: "KNOT_RESEARCH_SHADOW",
        run_slot_kind: "DOWNSTREAM_ONLY" as never,
        scheduled_sample_id: null as never,
      }),
    ).not.toThrow();
    expect(() =>
      buildAcceptedAgentOutputRecord({
        kind: "MACRO_TRANSMISSION",
        agentId: "china",
        payload: {},
        evidenceBundleIds: ["bundle:1"],
        causalDedupeKeys: ["cause:1"],
        context: context({
          sample_origin: "KNOT_RESEARCH_SHADOW",
          run_slot_kind: "DOWNSTREAM_ONLY" as never,
          scheduled_sample_id: null as never,
        }),
      }),
    ).toThrow(/must be outcome scheduled/);
  });

  it("stores idempotently and resolves only exact id/hash/kind/owner refs", () => {
    const store = new AcceptedAgentOutputStore();
    const record = macroRecord();
    const ref = store.put(record);
    expect(store.put(record)).toEqual(ref);
    expect(store.resolve(ref)).toEqual(record);
    expect(() =>
      store.resolve({ ...ref, accepted_output_hash: `sha256:${"2".repeat(64)}` }),
    ).toThrow(/reference mismatch/);
  });
});

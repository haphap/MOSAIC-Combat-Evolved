import { describe, expect, it } from "vitest";
import {
  AcceptedAgentOutputStore,
  type AcceptedOutputBuildContext,
  acceptedOutputRecordRef,
  acceptedOutputRefKey,
  buildAcceptedAgentOutputRecord,
  validateAcceptedAgentOutputRecord,
  validateCurrentAcceptedAgentOutputRecord,
} from "../src/agents/accepted_output.js";
import type { ClaimEvidenceGraph } from "../src/agents/evidence_contract.js";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";

const SOURCE_OUTPUT_HASH = `sha256:${"a".repeat(64)}`;

function claimGraph(): ClaimEvidenceGraph {
  return {
    schema_version: "evidence_claim_graph_v1",
    run_id: "graph-run-1",
    snapshot_hash: `sha256:${"b".repeat(64)}`,
    evidence_ledger: [
      {
        evidence_id: "evidence:1",
        run_id: "graph-run-1",
        snapshot_hash: `sha256:${"b".repeat(64)}`,
        source_kind: "tool",
        tool_or_source: "fixture",
        metric: "fixture",
        value: {
          server_tool_result: {
            result_event_id: "tool_evt_accepted",
            result_event_hash: `sha256:${"d".repeat(64)}`,
            result_authority_type: "SNAPSHOT_BUILD",
            result_authority_hash: `sha256:${"e".repeat(64)}`,
            tool_environment_hash: `sha256:${"f".repeat(64)}`,
            execution_behavior_release_hash: `sha256:${"0".repeat(64)}`,
            capability_bundle_hash: `sha256:${"1".repeat(64)}`,
            knot_coverage_manifest_v2_hash: `sha256:${"2".repeat(64)}`,
            knot_audit_capability_track_v2_hash: `sha256:${"3".repeat(64)}`,
            binding_result_refs: [
              {
                binding_id: `binding:${"4".repeat(64)}`,
                binding_result_fingerprint: `sha256:${"5".repeat(64)}`,
              },
            ],
          },
        },
        unit: "index",
        as_of: "2026-07-17",
        lookback: "current",
        freshness: "current",
        fallback: false,
        source_fingerprint: `sha256:${"c".repeat(64)}`,
        direction: "positive",
        privacy_class: "public_structured",
      },
    ],
    claims: [
      {
        claim_id: "claim:1",
        claim_kind: "FACT",
        statement: "Fixture claim.",
        structured_conclusion: { value: 1 },
        evidence_ids: ["evidence:1"],
        research_rule_refs: [],
      },
    ],
    recommendation_claim_refs: [],
  };
}

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
    claimGraph: claimGraph(),
    sourceAgentOutputHash: SOURCE_OUTPUT_HASH,
    context: context(),
  });
}

describe("AcceptedAgentOutputRecord", () => {
  it("creates a namespace-safe deterministic record and exact reference", () => {
    const record = macroRecord();
    validateAcceptedAgentOutputRecord(record);
    expect(record.accepted_output_id).toMatch(/^accepted-output:/);
    expect(record.accepted_output_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(record.capability_track.schema_version).toBe("accepted_output_capability_track_v1");
    expect(record.capability_track.capability_bundle_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(record.output.evidence_bundle_ids).toEqual(["bundle:1", "bundle:2"]);
    expect(record.knot_capture_v2.eligibility).toBe("ELIGIBLE");
    expect(record.knot_capture_v2.result_event_refs).toHaveLength(1);
    expect(record.knot_capture_v2.claim_specs).toEqual([
      expect.objectContaining({
        claim_id: "claim:1",
        structured_conclusion: { value: 1 },
      }),
    ]);
    expect(JSON.stringify(record.knot_capture_v2)).not.toContain("Fixture claim");
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

  it("seals an explicit KNOT-v2 ineligible capture when server authority is absent", () => {
    const legacyGraph = claimGraph();
    const firstEvidence = legacyGraph.evidence_ledger[0];
    if (!firstEvidence) throw new Error("legacy evidence fixture missing");
    legacyGraph.evidence_ledger[0] = {
      ...firstEvidence,
      value: 1,
    };
    const record = buildAcceptedAgentOutputRecord({
      kind: "MACRO_TRANSMISSION",
      agentId: "china",
      payload: { agent_id: "china", direction: "SUPPORTIVE" },
      evidenceBundleIds: ["bundle:1"],
      causalDedupeKeys: ["cause:1"],
      claimGraph: legacyGraph,
      sourceAgentOutputHash: SOURCE_OUTPUT_HASH,
      context: context(),
    });

    expect(record.knot_capture_v2.eligibility).toBe("INELIGIBLE");
    expect(record.knot_capture_v2.ineligibility_reasons).toEqual([
      "CLAIM_TOOL_EVIDENCE_SERVER_AUTHORITY_MISSING",
      "NO_SERVER_TOOL_RESULT_AUTHORITY",
    ]);
    validateCurrentAcceptedAgentOutputRecord(record);
  });

  it("carries and strictly validates the scheduled L1/L2 live source authority", () => {
    const liveContext = context();
    liveContext.evaluation_binding = {
      evaluation_opportunity_set_id: "opportunity:china",
      evaluation_opportunity_set_hash: `sha256:${"4".repeat(64)}`,
      frozen_object_set_id: null,
      frozen_object_set_hash: null,
      runtime_authority_binding: {
        source_tool_id: "get_china_macro_snapshot",
        source_snapshot_hash: `sha256:${"5".repeat(64)}`,
        domain_hash: `sha256:${"6".repeat(64)}`,
      },
    };
    const record = buildAcceptedAgentOutputRecord({
      kind: "MACRO_TRANSMISSION",
      agentId: "china",
      payload: { agent_id: "china", direction: "SUPPORTIVE" },
      evidenceBundleIds: ["bundle:1"],
      causalDedupeKeys: ["cause:1"],
      claimGraph: claimGraph(),
      sourceAgentOutputHash: SOURCE_OUTPUT_HASH,
      context: liveContext,
    });

    validateAcceptedAgentOutputRecord(record);
    expect(record.runtime_opportunity_authority).toEqual(
      liveContext.evaluation_binding.runtime_authority_binding,
    );
    const wrongToolContext = structuredClone(liveContext);
    if (!wrongToolContext.evaluation_binding) throw new Error("fixture binding required");
    wrongToolContext.evaluation_binding.runtime_authority_binding = {
      source_tool_id: "get_us_macro_snapshot",
      source_snapshot_hash: `sha256:${"5".repeat(64)}`,
      domain_hash: `sha256:${"6".repeat(64)}`,
    };
    const wrongToolRecord = buildAcceptedAgentOutputRecord({
      kind: "MACRO_TRANSMISSION",
      agentId: "china",
      payload: { agent_id: "china", direction: "SUPPORTIVE" },
      evidenceBundleIds: ["bundle:1"],
      causalDedupeKeys: ["cause:1"],
      claimGraph: claimGraph(),
      sourceAgentOutputHash: SOURCE_OUTPUT_HASH,
      context: wrongToolContext,
    });
    expect(() => validateAcceptedAgentOutputRecord(wrongToolRecord)).toThrow(
      "china: live source authority tool mismatch",
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
        claimGraph: claimGraph(),
        sourceAgentOutputHash: SOURCE_OUTPUT_HASH,
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
    const forgedTrack = structuredClone(record);
    forgedTrack.capability_track.tool_environment_hash = `sha256:${"9".repeat(64)}`;
    const { capability_bundle_hash: _, ...forgedTrackBody } = forgedTrack.capability_track;
    forgedTrack.capability_track.capability_bundle_hash = canonicalJsonHash(forgedTrackBody);
    const { accepted_output_hash: __, ...forgedBody } = forgedTrack;
    forgedTrack.accepted_output_hash = canonicalJsonHash(forgedBody);
    expect(() => validateAcceptedAgentOutputRecord(forgedTrack)).not.toThrow();
    expect(() => validateCurrentAcceptedAgentOutputRecord(forgedTrack)).toThrow(/capability track/);
  });

  it("accepts only production scheduled/downstream-only bindings", () => {
    expect(() =>
      buildAcceptedAgentOutputRecord({
        kind: "MACRO_TRANSMISSION",
        agentId: "china",
        payload: {},
        evidenceBundleIds: ["bundle:1"],
        causalDedupeKeys: ["cause:1"],
        claimGraph: claimGraph(),
        sourceAgentOutputHash: SOURCE_OUTPUT_HASH,
        context: context({
          sample_origin: "EXPERIMENT_SHADOW" as never,
          run_slot_kind: "DOWNSTREAM_ONLY",
          scheduled_sample_id: null,
        }),
      }),
    ).toThrow(/sample_origin must be PRODUCTION_ACTIVE/);
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

  it("loads legacy and cross-generation records read-only without admitting new writes", () => {
    const current = macroRecord();
    const { accepted_output_hash: _, capability_track: __, ...legacyBody } = current;
    const legacy = {
      ...legacyBody,
      accepted_output_hash: canonicalJsonHash(legacyBody),
    };
    const legacyStore = new AcceptedAgentOutputStore();
    const legacyRef = legacyStore.putReadOnly(legacy);
    expect(legacyStore.resolve(legacyRef)).toEqual(legacy);
    expect(() => legacyStore.put(legacy)).toThrow(/current capability track required/);

    const priorGeneration = structuredClone(current);
    priorGeneration.capability_track.knot_coverage_manifest_hash = `sha256:${"d".repeat(64)}`;
    const { capability_bundle_hash: ___, ...priorTrackBody } = priorGeneration.capability_track;
    priorGeneration.capability_track.capability_bundle_hash = canonicalJsonHash(priorTrackBody);
    const { accepted_output_hash: ____, ...priorRecordBody } = priorGeneration;
    priorGeneration.accepted_output_hash = canonicalJsonHash(priorRecordBody);
    const priorStore = new AcceptedAgentOutputStore();
    const priorRef = priorStore.putReadOnly(priorGeneration);
    expect(priorStore.resolve(priorRef)).toEqual(priorGeneration);
    expect(() => priorStore.put(priorGeneration)).toThrow(/capability track/);
  });
});

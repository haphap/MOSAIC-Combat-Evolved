import { describe, expect, it } from "vitest";
import {
  AcceptedAgentOutputStore,
  type AcceptedOutputBuildContext,
  type AcceptedOutputRecordRef,
  acceptedOutputRecordRef,
  acceptedOutputRefKey,
  buildAcceptedAgentOutputRecord,
  buildStructuredSmokeAcceptedOutputRecord,
  buildStructuredSmokeAcceptedOutputRef,
  validateAcceptedAgentOutputRecord,
  validateCurrentAcceptedAgentOutputRecord,
  validateStructuredSmokeAcceptedOutputRecord,
} from "../src/agents/accepted_output.js";
import type { ClaimEvidenceGraph } from "../src/agents/evidence_contract.js";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import type { DailyCycleStateType } from "../src/agents/state.js";

const SOURCE_OUTPUT_HASH = `sha256:${"a".repeat(64)}`;
const STRUCTURED_SMOKE_BUNDLE_HASH = `sha256:${"b".repeat(64)}`;

function structuredSmokeState(traceId = "structured-smoke-run"): DailyCycleStateType {
  return {
    trace_id: traceId,
    as_of_date: "2025-06-17",
    layer1_outputs: {},
    layer2_outputs: {},
    layer3_outputs: {},
    accepted_output_refs: {},
  } as unknown as DailyCycleStateType;
}

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

  it("keeps structured-smoke records read-only and preserves the legacy ref identity", () => {
    const previousBypass = process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS;
    const previousBundle = process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH;
    process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS = "structured_smoke";
    process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH = STRUCTURED_SMOKE_BUNDLE_HASH;
    try {
      const state = structuredSmokeState();
      const payload = { agent_id: "china", direction: "positive", signal: "stable" };
      const ref = buildStructuredSmokeAcceptedOutputRef({
        kind: "MACRO_TRANSMISSION",
        agentId: "china",
        payload,
        state,
      });
      const record = buildStructuredSmokeAcceptedOutputRecord({
        kind: "MACRO_TRANSMISSION",
        agentId: "china",
        payload,
        state,
      });
      if (!ref || !record) throw new Error("structured-smoke fixture setup failed");
      expect(record.accepted_output_hash).toBe(ref.accepted_output_hash);
      validateStructuredSmokeAcceptedOutputRecord(record);

      const store = new AcceptedAgentOutputStore();
      expect(store.putStructuredSmoke(record)).toEqual(ref);
      expect(store.records()).toEqual([]);
      expect(store.resolve(ref).output).toEqual({ payload });
      expect(() => store.resolveProduction(ref)).toThrow(/not production-active/);
      expect(() => store.put(record as never)).toThrow();

      const tampered = structuredClone(record);
      (tampered.output.payload as { signal: string }).signal = "tampered";
      expect(() => store.putStructuredSmoke(tampered)).toThrow(/hash mismatch/);

      const restored = new AcceptedAgentOutputStore();
      restored.restore(store.snapshot());
      expect(restored.resolve(ref).output).toEqual({ payload });
    } finally {
      if (previousBypass === undefined) delete process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS;
      else process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS = previousBypass;
      if (previousBundle === undefined)
        delete process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH;
      else process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH = previousBundle;
    }
  });

  it("hydrates a legacy Macro/Sector/Superinvestor ref-only prefix", () => {
    const previousBypass = process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS;
    const previousBundle = process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH;
    process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS = "structured_smoke";
    process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH = STRUCTURED_SMOKE_BUNDLE_HASH;
    try {
      const state = structuredSmokeState("legacy-prefix");
      const refs: Record<string, AcceptedOutputRecordRef> = {};
      const macroAgents = [
        "central_bank",
        "china",
        "commodities",
        "eu_economy",
        "euro_area_financial_conditions",
        "institutional_flow",
        "us_economy",
        "us_financial_conditions",
      ] as const;
      for (const agentId of macroAgents) {
        const payload = { agent_id: agentId, direction: "positive", signal: agentId };
        (state.layer1_outputs as Record<string, unknown>)[agentId] = {
          ...payload,
          verified_claim_graph: { state_only: true },
          verified_claim_audit: { state_only: true },
        };
        const ref = buildStructuredSmokeAcceptedOutputRef({
          kind: "MACRO_TRANSMISSION",
          agentId,
          payload,
          state,
        });
        if (!ref) throw new Error("Macro smoke ref setup failed");
        refs[acceptedOutputRefKey("MACRO_TRANSMISSION", agentId)] = ref;
      }
      const sectorAgents = [
        "agriculture",
        "biotech",
        "consumer",
        "energy",
        "financials",
        "industrials",
        "real_estate_construction",
        "semiconductor",
        "technology",
      ] as const;
      for (const agentId of sectorAgents) {
        const payload = { agent_id: agentId, selection_status: "NONE_FOUND" };
        (state.layer2_outputs as Record<string, unknown>)[agentId] = payload;
        const ref = buildStructuredSmokeAcceptedOutputRef({
          kind: "STANDARD_SECTOR_SELECTION",
          agentId,
          payload,
          state,
        });
        if (!ref) throw new Error("Sector smoke ref setup failed");
        refs[acceptedOutputRefKey("STANDARD_SECTOR_SELECTION", agentId)] = ref;
      }
      const superinvestorAgents = ["druckenmiller", "munger", "burry", "ackman"] as const;
      for (const agentId of superinvestorAgents) {
        const payload = { agent: agentId, selection_status: "NO_QUALIFIED_CANDIDATES", picks: [] };
        (state.layer3_outputs as Record<string, unknown>)[agentId] = payload;
        const ref = buildStructuredSmokeAcceptedOutputRef({
          kind: "SUPERINVESTOR_SELECTION",
          agentId,
          payload,
          state,
        });
        if (!ref) throw new Error("Superinvestor smoke ref setup failed");
        refs[acceptedOutputRefKey("SUPERINVESTOR_SELECTION", agentId)] = ref;
      }
      state.accepted_output_refs = refs;
      const restored = new AcceptedAgentOutputStore();
      restored.restore({ records: [], claim_graphs: {} });
      const completedPrefix = ["macro", "sector", "superinvestor"];
      restored.hydrateStructuredSmokeFromState(state);
      expect(completedPrefix).toEqual(["macro", "sector", "superinvestor"]);
      expect(restored.records()).toEqual([]);
      expect(Object.values(refs)).toHaveLength(21);
      for (const ref of Object.values(refs)) {
        expect(restored.resolve(ref).accepted_output_hash).toBe(ref.accepted_output_hash);
      }
      const chinaRef = refs["MACRO_TRANSMISSION:china"];
      if (!chinaRef) throw new Error("China smoke ref setup failed");
      expect((restored.resolve(chinaRef).output as { payload: unknown }).payload).toEqual({
        agent_id: "china",
        direction: "positive",
        signal: "china",
      });

      const unsupportedState = structuredSmokeState("missing-persisted-record");
      const unsupportedRef = buildStructuredSmokeAcceptedOutputRef({
        kind: "CIO_PROPOSAL",
        agentId: "cio",
        payload: {},
        state: unsupportedState,
      });
      if (!unsupportedRef) throw new Error("unsupported smoke ref setup failed");
      unsupportedState.accepted_output_refs = { "CIO_PROPOSAL:cio": unsupportedRef };
      expect(() => restored.hydrateStructuredSmokeFromState(unsupportedState)).toThrow(
        /cannot reconstruct missing persisted accepted output kind/,
      );
    } finally {
      if (previousBypass === undefined) delete process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS;
      else process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS = previousBypass;
      if (previousBundle === undefined)
        delete process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH;
      else process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH = previousBundle;
    }
  });
});

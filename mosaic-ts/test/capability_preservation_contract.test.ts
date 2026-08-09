import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { AGENT_IDS, agentToolsFor } from "../src/agents/tool_contract.js";
import {
  assertCurrentKnotTransitionAction,
  assertKnotTransitionAction,
  CapabilityBindingManifestSchema,
  CapabilityFullBundleV1Schema,
  CapabilityTrackSchema,
  canonicalCapabilityBindingId,
  canonicalToolEnvironmentHash,
  canonicalToolResultFingerprint,
  EvidenceClaimGraphV2Schema,
  KnotAuditCapabilityTrackV2Schema,
  KnotCapabilityUseAggregateSchema,
  KnotToolCoverageManifestSchema,
  KnotToolCoverageManifestV2Schema,
  loadCurrentAcceptedOutputCapabilityTrack,
  loadCurrentKnotAuditCapabilityTrackV2,
  loadCurrentKnotGateDReleaseAuthority,
  PromptTrainingProjectionV2Schema,
  StagedAgentToolContractManifestSchema,
  ToolEnvironmentManifestSchema,
  validateKnotExactClosure,
  validateToolConfigHash,
} from "../src/autoresearch/capability_preservation_contract.js";

const ROOT = resolve(import.meta.dirname, "../..");
const CONTRACT_ROOT = resolve(ROOT, "registry/prompt_checks/capability_preservation");

function load(name: string): unknown {
  return JSON.parse(readFileSync(resolve(CONTRACT_ROOT, name), "utf8"));
}

describe("capability preservation and KNOT contracts", () => {
  it("loads the exact current 29-stage/187-binding Gate-D release authority", () => {
    const authority = loadCurrentKnotGateDReleaseAuthority();
    expect(authority.stage_keys).toHaveLength(29);
    expect(new Set(authority.stage_keys).size).toBe(29);
    expect(authority.binding_count).toBe(187);
    expect(authority.knot_coverage_manifest_hash).toMatch(/^sha256:/);
    expect(authority.knot_audit_capability_track_hash).toMatch(/^sha256:/);
  });

  it("parses the staged manifests and closes every binding exactly once", () => {
    const bindings = CapabilityBindingManifestSchema.parse(
      load("agent_capability_binding_manifest_v1.json"),
    );
    const environment = ToolEnvironmentManifestSchema.parse(
      load("tool_environment_manifest_v1.json"),
    );
    const staged = StagedAgentToolContractManifestSchema.parse(
      load("staged_agent_tool_contract_manifest_v2.json"),
    );
    const coverage = KnotToolCoverageManifestSchema.parse(
      load("knot_tool_coverage_manifest_v1.json"),
    );
    validateKnotExactClosure({
      bindingManifest: bindings,
      toolEnvironmentManifest: environment,
      knotCoverageManifest: coverage,
    });
    for (const binding of bindings.bindings) {
      const { binding_id: _, ...body } = binding;
      expect(binding.binding_id).toBe(canonicalCapabilityBindingId(body));
    }
    const activeSurface = new Set(
      staged.tools.map((row) => `${row.agent_id}\0${row.stage}\0${row.tool_id}`),
    );
    expect(activeSurface.size).toBe(staged.tools.length);
    expect(staged.capability_binding_manifest_hash).toBe(bindings.manifest_hash);
    expect(environment.staged_agent_tool_contract_manifest_hash).toBe(staged.manifest_hash);
    expect(staged.tools.every((row) => row.source_route_ids.length > 0)).toBe(true);
    expect(new Set(staged.tools.flatMap((row) => row.capability_binding_ids))).toEqual(
      new Set(bindings.bindings.map((row) => row.binding_id)),
    );
  });

  it("binds trusted counterevidence coverage to the current v2 audit track", () => {
    const coverage = KnotToolCoverageManifestV2Schema.parse(
      load("knot_tool_coverage_manifest_v2.json"),
    );
    const track = KnotAuditCapabilityTrackV2Schema.parse(
      load("knot_audit_capability_track_v2.json"),
    );
    const current = loadCurrentKnotAuditCapabilityTrackV2();

    expect(coverage.coverage).toHaveLength(187);
    expect(track).toEqual(current);
    expect(track.knot_coverage_manifest_v2_hash).toBe(coverage.manifest_hash);
    expect(() =>
      KnotAuditCapabilityTrackV2Schema.parse({
        ...track,
        trusted_comparator_version: "caller_supplied_value_v1",
      }),
    ).toThrow();
  });

  it("keeps the active agentToolsFor surface unchanged", () => {
    const snapshot = JSON.parse(
      readFileSync(
        resolve(ROOT, "registry/prompt_checks/agent_tool_contract_manifest_v1.json"),
        "utf8",
      ),
    ) as {
      agents: Array<{ agent_id: (typeof AGENT_IDS)[number]; allowed_tools: string[] }>;
    };
    expect(snapshot.agents.map((row) => row.agent_id)).toEqual([...AGENT_IDS]);
    for (const row of snapshot.agents) {
      expect([...agentToolsFor(row.agent_id)]).toEqual(row.allowed_tools);
    }
    const activeTools = new Set(snapshot.agents.flatMap((row) => row.allowed_tools));
    expect(activeTools.has("get_broker_research")).toBe(true);
    expect(activeTools.has("get_stock_research")).toBe(true);
    expect(activeTools.has("get_rke_research_context")).toBe(true);
  });

  it("uses the canonical tool environment as the only toolConfigHash authority", () => {
    const environment = ToolEnvironmentManifestSchema.parse(
      load("tool_environment_manifest_v1.json"),
    );
    const hash = canonicalToolEnvironmentHash(environment);
    expect(() => validateToolConfigHash(hash, environment)).not.toThrow();
    expect(() => validateToolConfigHash(`sha256:${"0".repeat(64)}`, environment)).toThrow(
      /toolConfigHash/,
    );
  });

  it("requires capture-time track hashes and a full prompt-release bundle", () => {
    const trackBody = {
      schema_version: "accepted_output_capability_track_v1" as const,
      tool_environment_hash: `sha256:${"1".repeat(64)}`,
      execution_behavior_release_hash: `sha256:${"2".repeat(64)}`,
      capability_binding_manifest_hash: `sha256:${"3".repeat(64)}`,
      knot_coverage_manifest_hash: `sha256:${"4".repeat(64)}`,
    };
    expect(
      CapabilityTrackSchema.parse({
        ...trackBody,
        capability_bundle_hash: canonicalJsonHash(trackBody),
      }),
    ).toBeDefined();

    const releaseBody = {
      schema_version: "capability_full_bundle_v1" as const,
      prompt_hash: `sha256:${"1".repeat(64)}`,
      execution_behavior_release_hash: `sha256:${"2".repeat(64)}`,
      production_variant_roster_hash: `sha256:${"3".repeat(64)}`,
      runtime_agent_manifest_hash: `sha256:${"4".repeat(64)}`,
      agent_tool_manifest_hash: `sha256:${"5".repeat(64)}`,
      tool_environment_hash: `sha256:${"6".repeat(64)}`,
      capability_binding_manifest_hash: `sha256:${"7".repeat(64)}`,
      knot_coverage_manifest_hash: `sha256:${"8".repeat(64)}`,
      knot_audit_capability_track_hash: `sha256:${"a".repeat(64)}`,
      private_companion_pin_hash: `sha256:${"9".repeat(64)}`,
    };
    expect(
      CapabilityFullBundleV1Schema.parse({
        ...releaseBody,
        full_bundle_hash: canonicalJsonHash(releaseBody),
      }),
    ).toBeDefined();

    const capabilityUseAggregates = CapabilityBindingManifestSchema.parse(
      load("agent_capability_binding_manifest_v1.json"),
    ).bindings.map((binding) => {
      const aggregateBody = {
        schema_version: "knot_capability_use_aggregate_v1" as const,
        binding_id: binding.binding_id,
        eligible_count: 0,
        ready_count: 0,
        called_count: 0,
        succeeded_count: 0,
        used_in_accepted_evidence_count: 0,
        counterevidence_available_count: 0,
        counterevidence_handled_count: 0,
        runtime_blocker_count: 0,
        excluded_count: 0,
        gap_counts: {
          not_called: 0,
          call_failed: 0,
          succeeded_not_used: 0,
          counterevidence_ignored: 0,
        },
        model_controllable_gap_count: 0,
        opaque_failure_refs: [],
      };
      return { ...aggregateBody, aggregate_hash: canonicalJsonHash(aggregateBody) };
    });
    const productionVariantRosterRevisions: Array<{
      revisionId: string;
      revisionHash: string;
    }> = [];
    const projectionBody = {
      schemaVersion: "prompt_training_projection_v2" as const,
      target: { agentId: "china" },
      projectionId: "projection:test",
      datasetSnapshotHash: `sha256:${"a".repeat(64)}`,
      eligibleSampleIdsHash: `sha256:${"b".repeat(64)}`,
      excludedSampleIdsHash: `sha256:${"c".repeat(64)}`,
      cutoffAt: "2026-08-08T09:00:00+00:00",
      outcomeContract: { version: "outcome_v1" },
      evaluator: { version: "evaluator_v1" },
      capabilityTrack: loadCurrentAcceptedOutputCapabilityTrack(),
      knotAuditCapabilityTrack: loadCurrentKnotAuditCapabilityTrackV2(),
      knotHistoryPartitionHash: `sha256:${"2".repeat(64)}`,
      knotMaterializationSetHash: `sha256:${"3".repeat(64)}`,
      knotExcludedSampleSetHash: `sha256:${"4".repeat(64)}`,
      capabilityUseAggregates,
      productionVariantRosterRevisions,
      productionVariantRosterRevisionSetHash: canonicalJsonHash(productionVariantRosterRevisions),
      maturityContract: {
        horizonId: "horizon:20d",
        horizonContractHash: `sha256:${"d".repeat(64)}`,
        outcomeContractHash: `sha256:${"e".repeat(64)}`,
        tradingCalendarHash: `sha256:${"f".repeat(64)}`,
        labelReceiptSetHash: `sha256:${"1".repeat(64)}`,
        eligibilityEvaluatorVersion: "mature_sample_eligibility_v1" as const,
      },
      matureSampleCount: 0,
      scoreSummary: {},
      tailFailureCaseRefs: [],
      failureCategoryCounts: {},
      directComponents: [],
      controlledExperiments: [],
    };
    const projection = {
      ...projectionBody,
      projectionHash: canonicalJsonHash(projectionBody),
    };
    expect(PromptTrainingProjectionV2Schema.parse(projection)).toBeDefined();
    const { maturityContract: _, ...withoutMaturity } = projection;
    expect(() => PromptTrainingProjectionV2Schema.parse(withoutMaturity)).toThrow();
    const missingAggregateBody = {
      ...projectionBody,
      capabilityUseAggregates: capabilityUseAggregates.slice(1),
    };
    expect(() =>
      PromptTrainingProjectionV2Schema.parse({
        ...missingAggregateBody,
        projectionHash: canonicalJsonHash(missingAggregateBody),
      }),
    ).toThrow(/aggregate binding exact closure/);
  });

  it("requires successful typed lineage for every accepted v2 claim", () => {
    const binding = CapabilityBindingManifestSchema.parse(
      load("agent_capability_binding_manifest_v1.json"),
    ).bindings[0];
    if (!binding) {
      throw new Error("binding fixture missing");
    }
    const capabilityTrack = loadCurrentAcceptedOutputCapabilityTrack();
    const resultBody = {
      semantic_capability_id: binding.semantic_capability_id,
      binding_id: binding.binding_id,
      tool_id: binding.tool_id,
      canonical_args_hash: canonicalJsonHash({ as_of: "2026-08-08" }),
      payload_hash: canonicalJsonHash({ close: 10 }),
      build_receipt_hash: `sha256:${"a".repeat(64)}`,
      tool_environment_hash: capabilityTrack.tool_environment_hash,
    };
    const fingerprint = canonicalToolResultFingerprint(resultBody);
    const graph = {
      schema_version: "evidence_claim_graph_v2" as const,
      run_id: "run:test",
      agent_id: binding.agent_id,
      stage: binding.stage,
      capability_track: capabilityTrack,
      counterevidence_rule: {
        rule_version: "counterevidence_rule_v1" as const,
        dimension: "directional_strength",
        polarity_extractor_version: "signed_numeric_v1" as const,
        aggregation: "max_strength_v1" as const,
        comparison: "support_minus_contradiction" as const,
        threshold: 0.25,
        unknown_policy: "abstain" as const,
      },
      tool_results: [
        {
          fingerprint,
          ...resultBody,
          status: "SUCCEEDED" as const,
        },
      ],
      evidence_edges: [
        {
          edge_id: "edge:1",
          claim_id: "claim:1",
          tool_result_fingerprint: fingerprint,
          relation: "supports" as const,
          polarity: "supporting" as const,
          comparison_value: 0.8,
        },
        {
          edge_id: "edge:2",
          claim_id: "claim:1",
          tool_result_fingerprint: fingerprint,
          relation: "contradicts" as const,
          polarity: "contradicting" as const,
          comparison_value: 0.2,
        },
      ],
      accepted_claims: [
        {
          claim_id: "claim:1",
          accepted: true as const,
          comparison_witness: {
            supporting_edge_ids: ["edge:1"],
            contradicting_edge_ids: ["edge:2"],
            supporting_value: 0.8,
            contradicting_value: 0.2,
          },
          resolution_code: "rebutted_with_evidence" as const,
        },
      ],
    };
    expect(EvidenceClaimGraphV2Schema.parse(graph)).toBeDefined();
    expect(() =>
      EvidenceClaimGraphV2Schema.parse({
        ...graph,
        tool_results: [{ ...graph.tool_results[0], fingerprint: `sha256:${"0".repeat(64)}` }],
      }),
    ).toThrow(/fingerprint/);
    expect(() =>
      EvidenceClaimGraphV2Schema.parse({
        ...graph,
        accepted_claims: [{ ...graph.accepted_claims[0], resolution_code: "qualified" }],
      }),
    ).toThrow(/resolution/);
    expect(() =>
      EvidenceClaimGraphV2Schema.parse({
        ...graph,
        evidence_edges: [{ ...graph.evidence_edges[0], polarity: "contradicting" }],
      }),
    ).toThrow(/polarity/);
  });

  it("requires KNOT aggregate count conservation", () => {
    const aggregateBody = {
      schema_version: "knot_capability_use_aggregate_v1" as const,
      binding_id: `binding:${"a".repeat(64)}`,
      eligible_count: 5,
      ready_count: 4,
      called_count: 3,
      succeeded_count: 2,
      used_in_accepted_evidence_count: 1,
      counterevidence_available_count: 1,
      counterevidence_handled_count: 0,
      runtime_blocker_count: 1,
      excluded_count: 0,
      gap_counts: {
        not_called: 1,
        call_failed: 1,
        succeeded_not_used: 1,
        counterevidence_ignored: 1,
      },
      model_controllable_gap_count: 4,
      opaque_failure_refs: [],
    };
    const aggregate = { ...aggregateBody, aggregate_hash: canonicalJsonHash(aggregateBody) };
    expect(KnotCapabilityUseAggregateSchema.parse(aggregate)).toBeDefined();
    const forgedBody = { ...aggregateBody, ready_count: 5 };
    expect(() =>
      KnotCapabilityUseAggregateSchema.parse({
        ...forgedBody,
        aggregate_hash: canonicalJsonHash(forgedBody),
      }),
    ).toThrow(/count conservation/);
  });

  it("freezes all transitional KNOT evolution while preserving the active Champion", () => {
    const preservation = load("agent_capability_preservation_manifest_v1.json") as {
      transition_freeze: {
        state: string;
        allowed_actions: string[];
      };
    };
    expect(() =>
      assertKnotTransitionAction("USE_ACTIVE_CHAMPION", preservation.transition_freeze),
    ).not.toThrow();
    for (const action of [
      "GENERATE_CANDIDATE",
      "RUN_EXPERIMENT",
      "JUDGE_EXPERIMENT",
      "PROMOTE_DECISION",
      "STAGE_PROMPT_RELEASE",
      "START_PROMPT_CANARY",
      "ACTIVATE_PROMPT_RELEASE",
    ]) {
      expect(() => assertKnotTransitionAction(action, preservation.transition_freeze)).toThrow(
        /frozen until Gate D/,
      );
      expect(() => assertCurrentKnotTransitionAction(action)).toThrow(/frozen until Gate D/);
    }
  });
});

import { describe, expect, it, vi } from "vitest";
import type { BridgeApi, RkeAgentProfileEvolutionReadinessResult } from "../src/bridge/types.js";
import {
  buildProfileEvidence,
  runRkeProfileEvidence,
} from "../src/cli/commands/rke-profile-evidence.js";

describe("rke-profile-evidence helpers", () => {
  it("builds no-body profile evidence refs", () => {
    const evidence = buildProfileEvidence("bench-1", {
      profileUpdateRef: "rke-profile:bench-1:profile-update",
      evolutionInputRef: "rke-profile:bench-1:evolution-input",
      noSourceProseAuditRef: "rke-profile:bench-1:no-source-prose",
    });

    expect(evidence).toEqual({
      benchmark_run_id: "bench-1",
      profile_update_ref: "rke-profile:bench-1:profile-update",
      evolution_input_ref: "rke-profile:bench-1:evolution-input",
      no_source_prose_audit_ref: "rke-profile:bench-1:no-source-prose",
    });
    expect(JSON.stringify(evidence)).not.toContain(".mosaic");
    expect(JSON.stringify(evidence)).not.toContain("claim_text");
  });

  it("records profile evidence only after profile readiness is ready", async () => {
    const api = mockApi(readiness("ready"));

    const result = await runRkeProfileEvidence(api as unknown as BridgeApi, {
      benchmarkRunId: "bench-1",
      profileUpdateRef: "rke-profile:bench-1:profile-update",
      evolutionInputRef: "rke-profile:bench-1:evolution-input",
      noSourceProseAuditRef: "rke-profile:bench-1:no-source-prose",
    });

    expect(result.record.record_status).toBe("recorded");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        benchmark_run_id: "bench-1",
        profile_evidence: result.profileEvidence,
      }),
    );
  });

  it("does not record profile evidence when profile readiness blocks", async () => {
    const api = mockApi(readiness("blocked_preflight", ["layer_coverage_incomplete"]));

    await expect(
      runRkeProfileEvidence(api as unknown as BridgeApi, {
        benchmarkRunId: "bench-1",
        profileUpdateRef: "rke-profile:bench-1:profile-update",
        evolutionInputRef: "rke-profile:bench-1:evolution-input",
        noSourceProseAuditRef: "rke-profile:bench-1:no-source-prose",
      }),
    ).rejects.toThrow("profile evidence blocked: layer_coverage_incomplete");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).not.toHaveBeenCalled();
  });
});

function mockApi(readinessResult: RkeAgentProfileEvolutionReadinessResult) {
  return {
    rkeBenchmarkAgentProfileEvolutionReadiness: vi.fn().mockResolvedValue(readinessResult),
    rkeBenchmarkRecordDeliveryEvidence: vi.fn().mockResolvedValue({
      record_status: "recorded",
      benchmark_run_id: "bench-1",
      private_rows_path: ".mosaic/rke/all_agent_evolution/delivery_evidence.jsonl",
      recorded_key_count: 1,
      recorded_context_key_count: 0,
      failures: [],
    }),
    rkeBenchmarkDeliveryEvidenceAudit: vi.fn().mockResolvedValue({
      schema_version: "rke_delivery_evidence_audit_v1",
      evidence_status: "partial",
      benchmark_run_id: "bench-1",
      cohort: "cohort_default",
      private_rows_path: ".mosaic/rke/all_agent_evolution/delivery_evidence.jsonl",
      recorded_key_count: 1,
      recorded_context_keys: [],
      recorded_keys: ["profile_evidence"],
      recorded_prompt_source_status: {},
      missing_keys: [],
      failures: [],
      delivery_readiness_can_load: true,
      delivery_readiness_status: "blocked_preflight",
      condition_count: 12,
      ready_condition_count: 1,
      delivery_conditions: [],
      delivery_blocked_reasons: [],
    }),
  };
}

function readiness(
  readinessStatus: "ready" | "blocked_preflight",
  blockedReasons: string[] = [],
): RkeAgentProfileEvolutionReadinessResult {
  return {
    schema_version: "rke_agent_profile_evolution_readiness_v1",
    readiness_status: readinessStatus,
    benchmark_run_id: "bench-1",
    blocked_reasons: blockedReasons,
    summary_status: "ready",
    row_count: 25,
    required_layers: ["decision", "macro", "sector", "superinvestor"],
    observed_layers: ["decision", "macro", "sector", "superinvestor"],
    missing_layers: [],
    layer_counts: { decision: 4, macro: 9, sector: 8, superinvestor: 4 },
    claim_type_counts: {},
    rke_context_hash_count: 25,
    report_claim_ref_count: 25,
    report_claim_linked_row_count: 25,
    rke_context_report_claim_linked_count: 25,
    ranking_policy_id_counts: { rke_agent_context_rank_v1: 25 },
    retrieval_rank_count: 25,
    priority_bucket_counts: { high: 25 },
    truncation_audit_count: 25,
    current_data_confirmed_count: 25,
    privacy_scan: {
      private_text_included: false,
      source_prose_included: false,
      forbidden_field_violation_count: 0,
    },
    profile_evidence: {
      benchmark_run_id: "bench-1",
      profile_update_ref: "rke-profile:bench-1:profile-update",
      evolution_input_ref: "rke-profile:bench-1:evolution-input",
      no_source_prose_audit_ref: "rke-profile:bench-1:no-source-prose",
    },
    profile_evolution_ready: readinessStatus === "ready",
    production_signal_allowed: false,
  };
}

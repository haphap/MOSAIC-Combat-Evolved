import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { BridgeApi, RkePatchActivationReadinessResult } from "../src/bridge/types.js";
import {
  normalizePatchActivationEvidenceRows,
  runRkePatchActivationEvidence,
} from "../src/cli/commands/rke-patch-activation-evidence.js";

describe("rke-patch-activation-evidence helpers", () => {
  it("normalizes no-body patch activation rows", () => {
    const rows = normalizePatchActivationEvidenceRows([rawPatchRow()], "bench-1");

    expect(rows).toEqual([
      {
        benchmark_run_id: "bench-1",
        mutation_candidate_id: "PMUT-1",
        patch_artifact_ref: "rke-patch:bench-1:PMUT-1:artifact",
        patch_validation_ref: "rke-patch:bench-1:PMUT-1:validation",
        shadow_apply_ref: "rke-patch:bench-1:PMUT-1:shadow-apply",
        runtime_activation_ref: "rke-patch:bench-1:PMUT-1:runtime-activation",
        runtime_proof_ref: "rke-patch:bench-1:PMUT-1:runtime-proof",
        rollback_ref: "rke-patch:bench-1:PMUT-1:rollback",
        shadow_activation_passed: true,
        runtime_proof_passed: true,
        production_activation_allowed: false,
      },
    ]);
    expect(JSON.stringify(rows)).not.toContain(".mosaic");
    expect(JSON.stringify(rows)).not.toContain("prompt_body");
  });

  it("requires production activation to remain forbidden", () => {
    expect(() =>
      normalizePatchActivationEvidenceRows(
        [{ ...rawPatchRow(), production_activation_allowed: true }],
        "bench-1",
      ),
    ).toThrow("productionActivationAllowed must be false");
  });

  it("records patch activation evidence only after the gate is ready", async () => {
    const api = mockApi(readiness("ready"));
    const evidenceFile = writeJsonFile([rawPatchRow()]);
    const candidatesFile = writeJsonFile([rawCandidateRow()]);

    const result = await runRkePatchActivationEvidence(api as unknown as BridgeApi, {
      benchmarkRunId: "bench-1",
      evidenceFile,
      candidatesFile,
    });

    expect(result.record.record_status).toBe("recorded");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        benchmark_run_id: "bench-1",
        candidates: [rawCandidateRow()],
        patch_activation_evidence: result.patchActivationEvidence,
      }),
    );
  });

  it("does not record patch activation evidence when the gate blocks", async () => {
    const api = mockApi(readiness("blocked_preflight", ["runtime_proof_not_passed"]));
    const evidenceFile = writeJsonFile([rawPatchRow()]);

    await expect(
      runRkePatchActivationEvidence(api as unknown as BridgeApi, {
        benchmarkRunId: "bench-1",
        evidenceFile,
      }),
    ).rejects.toThrow("patch activation blocked: runtime_proof_not_passed");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).not.toHaveBeenCalled();
  });
});

function rawPatchRow() {
  return {
    benchmark_run_id: "bench-1",
    mutation_candidate_id: "PMUT-1",
    patch_artifact_ref: "rke-patch:bench-1:PMUT-1:artifact",
    patch_validation_ref: "rke-patch:bench-1:PMUT-1:validation",
    shadow_apply_ref: "rke-patch:bench-1:PMUT-1:shadow-apply",
    runtime_activation_ref: "rke-patch:bench-1:PMUT-1:runtime-activation",
    runtime_proof_ref: "rke-patch:bench-1:PMUT-1:runtime-proof",
    rollback_ref: "rke-patch:bench-1:PMUT-1:rollback",
    shadow_activation_passed: true,
    runtime_proof_passed: true,
    production_activation_allowed: false,
  };
}

function rawCandidateRow() {
  return {
    mutation_candidate_id: "PMUT-1",
    candidate_type: "stock_prior_recipe_rule_candidate",
    target_scope: "stock",
    target_component: "superinvestor.munger",
    severity: "medium",
    blocked_by: [],
    promotion_state: "shadow_only",
    manual_review_required: true,
    trigger_sources: ["rke_prior_usage_quality"],
    validation_requirements: ["shadow_activation"],
  };
}

function writeJsonFile(rows: unknown[]): string {
  const path = join(mkdtempSync(join(tmpdir(), "rke-patch-activation-")), "rows.json");
  writeFileSync(path, JSON.stringify(rows), "utf-8");
  return path;
}

function mockApi(readinessResult: RkePatchActivationReadinessResult) {
  return {
    rkeBenchmarkPatchActivationReadiness: vi.fn().mockResolvedValue(readinessResult),
    rkeBenchmarkRecordDeliveryEvidence: vi.fn().mockResolvedValue({
      record_status: "recorded",
      benchmark_run_id: "bench-1",
      private_rows_path: ".mosaic/rke/all_agent_evolution/delivery_evidence.jsonl",
      recorded_key_count: 2,
      recorded_context_key_count: 0,
      failures: [],
    }),
    rkeBenchmarkDeliveryEvidenceAudit: vi.fn().mockResolvedValue({
      schema_version: "rke_delivery_evidence_audit_v1",
      evidence_status: "partial",
      benchmark_run_id: "bench-1",
      cohort: "cohort_default",
      private_rows_path: ".mosaic/rke/all_agent_evolution/delivery_evidence.jsonl",
      recorded_key_count: 2,
      recorded_context_keys: [],
      recorded_keys: ["candidates", "patch_activation_evidence"],
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
  readinessStatus: "ready" | "blocked_preflight" | "not_applicable",
  blockedReasons: string[] = [],
): RkePatchActivationReadinessResult {
  return {
    schema_version: "rke_patch_activation_readiness_v1",
    benchmark_run_id: "bench-1",
    readiness_status: readinessStatus,
    blocked_reasons: blockedReasons,
    candidate_manifest_status: "ready_for_private_prompt_lifecycle",
    patch_candidate_count: readinessStatus === "not_applicable" ? 0 : 1,
    activation_record_count: readinessStatus === "not_applicable" ? 0 : 1,
    activation_records: [],
    required_evidence: [],
    patch_activation_ready: readinessStatus === "ready",
    direct_runtime_write_allowed: false,
    production_allowed: false,
    promotion_allowed: false,
  };
}

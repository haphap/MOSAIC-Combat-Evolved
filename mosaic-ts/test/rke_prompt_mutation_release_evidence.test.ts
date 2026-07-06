import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { BridgeApi, RkePromptMutationReleaseReadinessResult } from "../src/bridge/types.js";
import {
  normalizePromptMutationReleaseRows,
  runRkePromptMutationReleaseEvidence,
} from "../src/cli/commands/rke-prompt-mutation-release-evidence.js";

const promptHash = "c".repeat(64);

describe("rke-prompt-mutation-release-evidence helpers", () => {
  it("normalizes no-body prompt mutation release rows", () => {
    const rows = normalizePromptMutationReleaseRows([rawReleaseRow()], "bench-1");

    expect(rows).toEqual([
      {
        benchmark_run_id: "bench-1",
        mutation_candidate_id: "PMUT-1",
        prompt_version_id: 11,
        prompt_repo_id: "private-prompts",
        private_prompt_branch: "rke/PMUT-1",
        base_prompt_repo_revision: "base123",
        overwrite_target_paths: ["prompts/mosaic/cohort_default/superinvestor/munger.zh.md"],
        audit_version_ref: "prompt-mutation-audit:bench-1:PMUT-1",
        prompt_commit_hash: "commit123",
        prompt_sha256: promptHash,
        verify_release_ref: "prompt-mutation-verify:bench-1:PMUT-1",
        leak_drift_check_ref: "prompt-mutation-leak-drift:bench-1:PMUT-1",
        prompt_contract_check_ref: "prompt-contract:rke_prompt_contract_v1:hash",
        verify_release_passed: true,
        leak_drift_passed: true,
        prompt_contract_check_passed: true,
        release_ready: true,
      },
    ]);
    expect(JSON.stringify(rows)).not.toContain("prompt_body");
  });

  it("rejects release rows without overwrite targets", () => {
    expect(() =>
      normalizePromptMutationReleaseRows(
        [{ ...rawReleaseRow(), overwrite_target_paths: [] }],
        "bench-1",
      ),
    ).toThrow("overwriteTargetPaths must be a non-empty string array");
  });

  it("records release checks only after prompt mutation release readiness is ready", async () => {
    const api = mockApi(readiness("ready"));
    const releaseChecksFile = writeJsonFile([rawReleaseRow()]);
    const candidatesFile = writeJsonFile([rawCandidateRow()]);

    const result = await runRkePromptMutationReleaseEvidence(api as unknown as BridgeApi, {
      benchmarkRunId: "bench-1",
      releaseChecksFile,
      candidatesFile,
    });

    expect(result.record.record_status).toBe("recorded");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        benchmark_run_id: "bench-1",
        candidates: [rawCandidateRow()],
        prompt_mutation_release_checks: result.releaseChecks,
      }),
    );
  });

  it("does not record release checks when the gate blocks", async () => {
    const api = mockApi(readiness("blocked_preflight", ["leak_drift_not_passed"]));
    const releaseChecksFile = writeJsonFile([rawReleaseRow()]);
    const candidatesFile = writeJsonFile([rawCandidateRow()]);

    await expect(
      runRkePromptMutationReleaseEvidence(api as unknown as BridgeApi, {
        benchmarkRunId: "bench-1",
        releaseChecksFile,
        candidatesFile,
      }),
    ).rejects.toThrow("prompt mutation release blocked: leak_drift_not_passed");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).not.toHaveBeenCalled();
  });
});

function rawReleaseRow() {
  return {
    benchmark_run_id: "bench-1",
    mutation_candidate_id: "PMUT-1",
    prompt_version_id: 11,
    prompt_repo_id: "private-prompts",
    private_prompt_branch: "rke/PMUT-1",
    base_prompt_repo_revision: "base123",
    overwrite_target_paths: ["prompts/mosaic/cohort_default/superinvestor/munger.zh.md"],
    audit_version_ref: "prompt-mutation-audit:bench-1:PMUT-1",
    prompt_commit_hash: "commit123",
    prompt_sha256: promptHash,
    verify_release_ref: "prompt-mutation-verify:bench-1:PMUT-1",
    leak_drift_check_ref: "prompt-mutation-leak-drift:bench-1:PMUT-1",
    prompt_contract_check_ref: "prompt-contract:rke_prompt_contract_v1:hash",
    verify_release_passed: true,
    leak_drift_passed: true,
    prompt_contract_check_passed: true,
    release_ready: true,
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
    validation_requirements: ["private_prompt_branch"],
  };
}

function writeJsonFile(rows: unknown[]): string {
  const path = join(mkdtempSync(join(tmpdir(), "rke-prompt-mutation-release-")), "rows.json");
  writeFileSync(path, JSON.stringify(rows), "utf-8");
  return path;
}

function mockApi(readinessResult: RkePromptMutationReleaseReadinessResult) {
  return {
    rkeBenchmarkPromptMutationReleaseReadiness: vi.fn().mockResolvedValue(readinessResult),
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
      recorded_keys: ["candidates", "prompt_mutation_release_checks"],
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
): RkePromptMutationReleaseReadinessResult {
  return {
    schema_version: "rke_prompt_mutation_release_readiness_v1",
    benchmark_run_id: "bench-1",
    readiness_status: readinessStatus,
    blocked_reasons: blockedReasons,
    lifecycle_manifest_status: "ready_for_private_branch",
    branch_candidate_count: readinessStatus === "not_applicable" ? 0 : 1,
    release_record_count: readinessStatus === "not_applicable" ? 0 : 1,
    release_records: [],
    required_evidence: [],
    prompt_release_ready: readinessStatus === "ready",
    direct_prompt_write_allowed: false,
    promotion_allowed: false,
  };
}

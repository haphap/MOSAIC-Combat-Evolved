import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { BridgeApi, RkeAllAgentPromptProvenanceReadinessResult } from "../src/bridge/types.js";
import {
  normalizeReleaseCheckRows,
  runRkePromptProvenanceEvidence,
} from "../src/cli/commands/rke-prompt-provenance-evidence.js";

const promptHash = "b".repeat(64);

describe("rke-prompt-provenance-evidence helpers", () => {
  it("normalizes no-body release rows", () => {
    const rows = normalizeReleaseCheckRows([rawReleaseRow()], "bench-1");

    expect(rows).toEqual([
      {
        benchmark_run_id: "bench-1",
        agent: "dollar",
        lang: "zh",
        prompt_repo_id: "private-prompts",
        prompt_repo_revision: "abc123",
        prompt_file_path: "prompts/mosaic/cohort_default/macro/dollar.zh.md",
        prompt_sha256: promptHash,
        prompt_version_id: 7,
        audit_version_ref: "prompt-audit:bench-1:dollar:zh",
        verify_release_ref: "prompt-verify:bench-1:dollar:zh",
        leak_drift_check_ref: "prompt-leak-drift:bench-1:dollar:zh",
        prompt_contract_check_ref: "prompt-contract:rke_prompt_contract_v1:hash",
        verify_release_passed: true,
        leak_drift_passed: true,
        prompt_contract_check_passed: true,
      },
    ]);
    expect(JSON.stringify(rows)).not.toContain("prompt_body");
  });

  it("rejects cross-run release rows", () => {
    expect(() =>
      normalizeReleaseCheckRows([{ ...rawReleaseRow(), benchmark_run_id: "other-run" }], "bench-1"),
    ).toThrow("release check row 0 benchmark_run_id mismatch");
  });

  it("records release checks only after prompt provenance is ready", async () => {
    const api = mockApi(readiness("ready"));
    const releaseChecksFile = writeEvidenceFile([rawReleaseRow()]);

    const result = await runRkePromptProvenanceEvidence(api as unknown as BridgeApi, {
      benchmarkRunId: "bench-1",
      releaseChecksFile,
    });

    expect(result.record.record_status).toBe("recorded");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        benchmark_run_id: "bench-1",
        all_agent_prompt_release_checks: result.releaseChecks,
      }),
    );
  });

  it("generates release checks when no release file is supplied", async () => {
    const api = mockApi(readiness("ready"));

    const result = await runRkePromptProvenanceEvidence(api as unknown as BridgeApi, {
      benchmarkRunId: "bench-1",
    });

    expect(api.promptsFormalReleaseChecks).toHaveBeenCalledWith({
      benchmark_run_id: "bench-1",
      cohort: "cohort_default",
    });
    expect(result.releaseChecks).toEqual([rawReleaseRow()]);
    expect(api.rkeBenchmarkRecordDeliveryEvidence).toHaveBeenCalled();
  });

  it("does not record generated release checks when generation blocks", async () => {
    const api = mockApi(readiness("ready"), false);

    await expect(
      runRkePromptProvenanceEvidence(api as unknown as BridgeApi, {
        benchmarkRunId: "bench-1",
      }),
    ).rejects.toThrow("formal release checks blocked: private_prompt_unavailable");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).not.toHaveBeenCalled();
  });

  it("does not record release checks when prompt provenance blocks", async () => {
    const api = mockApi(readiness("blocked_preflight", ["leak_drift_not_passed"]));
    const releaseChecksFile = writeEvidenceFile([rawReleaseRow()]);

    await expect(
      runRkePromptProvenanceEvidence(api as unknown as BridgeApi, {
        benchmarkRunId: "bench-1",
        releaseChecksFile,
      }),
    ).rejects.toThrow("prompt provenance blocked: leak_drift_not_passed");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).not.toHaveBeenCalled();
  });
});

function rawReleaseRow() {
  return {
    benchmark_run_id: "bench-1",
    agent: "dollar",
    lang: "zh",
    prompt_repo_id: "private-prompts",
    prompt_repo_revision: "abc123",
    prompt_file_path: "prompts/mosaic/cohort_default/macro/dollar.zh.md",
    prompt_sha256: promptHash,
    prompt_version_id: 7,
    audit_version_ref: "prompt-audit:bench-1:dollar:zh",
    verify_release_ref: "prompt-verify:bench-1:dollar:zh",
    leak_drift_check_ref: "prompt-leak-drift:bench-1:dollar:zh",
    prompt_contract_check_ref: "prompt-contract:rke_prompt_contract_v1:hash",
    verify_release_passed: true,
    leak_drift_passed: true,
    prompt_contract_check_passed: true,
  };
}

function writeEvidenceFile(rows: unknown[]): string {
  const path = join(mkdtempSync(join(tmpdir(), "rke-prompt-provenance-")), "release.json");
  writeFileSync(path, JSON.stringify(rows), "utf-8");
  return path;
}

function mockApi(readinessResult: RkeAllAgentPromptProvenanceReadinessResult, formalReady = true) {
  return {
    promptsFormalReleaseChecks: vi.fn().mockResolvedValue({
      schema_version: "prompt_formal_release_checks_v1",
      benchmark_run_id: "bench-1",
      cohort: "cohort_default",
      ready: formalReady,
      row_count: formalReady ? 1 : 0,
      ready_count: formalReady ? 1 : 0,
      blocked_count: formalReady ? 0 : 1,
      blocked_reasons: formalReady ? [] : ["private_prompt_unavailable"],
      prompt_source_status: {
        ready: formalReady,
        blocked_reason: formalReady ? "" : "private_prompt_unavailable",
        resolved_source: formalReady ? "private_repo" : "",
        prompt_repo_id: formalReady ? "private-prompts" : "",
        prompt_repo_revision: formalReady ? "abc123" : "",
        prompt_repo_dirty_count: 0,
      },
      rows: formalReady ? [rawReleaseRow()] : [],
    }),
    rkeBenchmarkAllAgentPromptProvenanceReadiness: vi.fn().mockResolvedValue(readinessResult),
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
      recorded_keys: ["all_agent_prompt_release_checks"],
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
): RkeAllAgentPromptProvenanceReadinessResult {
  return {
    schema_version: "rke_all_agent_prompt_provenance_readiness_v1",
    readiness_status: readinessStatus,
    benchmark_run_id: "bench-1",
    cohort: "cohort_default",
    blocked_reasons: blockedReasons,
    agent_count: 1,
    prompt_row_count: 1,
    ready_prompt_row_count: readinessStatus === "ready" ? 1 : 0,
    release_check_count: 1,
    prompt_source_status: {
      ready: true,
      blocked_reason: "",
      resolved_source: "private_repo",
      prompt_repo_id: "private-prompts",
      prompt_repo_revision: "abc123",
      prompt_repo_dirty_count: 0,
    },
    prompt_rows: [],
    all_agent_prompt_provenance_ready: readinessStatus === "ready",
    fallback_used: false,
    production_prompt_change_allowed: false,
  };
}

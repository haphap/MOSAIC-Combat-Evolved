import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { BridgeApi, RkeDeliveryReadinessResult } from "../src/bridge/types.js";
import {
  normalizeRollbackEvidenceRows,
  runRkeRollbackRehearsalEvidence,
} from "../src/cli/commands/rke-rollback-rehearsal-evidence.js";

const prefix = "rke-shadow:bench-1:replay-1:";
const previousHash = "a".repeat(64);

describe("rke-rollback-rehearsal-evidence helpers", () => {
  it("normalizes no-body rollback rows from a replay run", () => {
    const rows = normalizeRollbackEvidenceRows([rawRollbackRow()], "bench-1", "replay-1");

    expect(rows).toEqual([
      {
        benchmark_run_id: "bench-1",
        mutation_candidate_id: "PMUT-1",
        previous_prompt_hashes: [previousHash],
        rollback_trigger_definition: `${prefix}rollback-trigger:PMUT-1`,
        rollback_command_or_procedure: `${prefix}rollback-procedure:PMUT-1`,
        monitor_output_ref: `${prefix}rollback-monitor:PMUT-1`,
        post_rollback_verification_ref: `${prefix}rollback-verify:PMUT-1`,
      },
    ]);
    expect(JSON.stringify(rows)).not.toContain(".mosaic");
    expect(JSON.stringify(rows)).not.toContain("prompt_body");
  });

  it("rejects rollback refs not produced by the replay run", () => {
    expect(() =>
      normalizeRollbackEvidenceRows(
        [{ ...rawRollbackRow(), monitor_output_ref: "manual:monitor" }],
        "bench-1",
        "replay-1",
      ),
    ).toThrow("monitorOutputRef must start with rke-shadow:bench-1:replay-1:");
  });

  it("records rollback evidence only after the rollback condition is ready", async () => {
    const api = mockApi(readiness(true));
    const evidenceFile = writeEvidenceFile([rawRollbackRow()]);

    const result = await runRkeRollbackRehearsalEvidence(api as unknown as BridgeApi, {
      benchmarkRunId: "bench-1",
      replayRunId: "replay-1",
      evidenceFile,
    });

    expect(result.record.record_status).toBe("recorded");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        benchmark_run_id: "bench-1",
        rollback_evidence: result.rollbackEvidence,
      }),
    );
  });

  it("does not record rollback evidence when the gate blocks it", async () => {
    const api = mockApi(readiness(false, ["previous_prompt_hashes_mismatch"]));
    const evidenceFile = writeEvidenceFile([rawRollbackRow()]);

    await expect(
      runRkeRollbackRehearsalEvidence(api as unknown as BridgeApi, {
        benchmarkRunId: "bench-1",
        replayRunId: "replay-1",
        evidenceFile,
      }),
    ).rejects.toThrow("rollback_evidence blocked: previous_prompt_hashes_mismatch");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).not.toHaveBeenCalled();
  });
});

function rawRollbackRow() {
  return {
    benchmark_run_id: "bench-1",
    mutation_candidate_id: "PMUT-1",
    previous_prompt_hashes: [previousHash],
    rollback_trigger_definition: `${prefix}rollback-trigger:PMUT-1`,
    rollback_command_or_procedure: `${prefix}rollback-procedure:PMUT-1`,
    monitor_output_ref: `${prefix}rollback-monitor:PMUT-1`,
    post_rollback_verification_ref: `${prefix}rollback-verify:PMUT-1`,
  };
}

function writeEvidenceFile(rows: unknown[]): string {
  const path = join(mkdtempSync(join(tmpdir(), "rke-rollback-evidence-")), "rollback.json");
  writeFileSync(path, JSON.stringify(rows), "utf-8");
  return path;
}

function mockApi(readinessResult: RkeDeliveryReadinessResult) {
  return {
    rkeBenchmarkDeliveryReadiness: vi.fn().mockResolvedValue(readinessResult),
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
      recorded_keys: ["rollback_evidence"],
      recorded_prompt_source_status: {},
      missing_keys: [],
      failures: [],
      delivery_readiness_can_load: true,
      delivery_readiness_status: "blocked_preflight",
      condition_count: 12,
      ready_condition_count: 11,
      delivery_conditions: [],
      delivery_blocked_reasons: [],
    }),
  };
}

function readiness(ready: boolean, blockedReasons: string[] = []): RkeDeliveryReadinessResult {
  return {
    schema_version: "rke_all_agent_delivery_readiness_v1",
    readiness_status: ready ? "ready" : "blocked_preflight",
    benchmark_run_id: "bench-1",
    cohort: "cohort_default",
    condition_count: 1,
    ready_condition_count: ready ? 1 : 0,
    blocked_reasons: blockedReasons,
    conditions: [
      {
        condition_id: "rollback_evidence",
        status: ready ? "ready" : "blocked_preflight",
        ready,
        blocked_reasons: blockedReasons,
        evidence_summary: {},
      },
    ],
    recorded_evidence_loaded: true,
    delivery_input_failures: [],
    delivery_ready: ready,
    production_allowed: false,
    promotion_allowed: false,
  };
}

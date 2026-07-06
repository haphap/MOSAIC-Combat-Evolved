import { describe, expect, it, vi } from "vitest";
import type { BridgeApi, RkeDeliveryReadinessResult } from "../src/bridge/types.js";
import {
  buildPaperTradingPlan,
  buildPromotionEvidence,
  runRkePaperPromotionEvidence,
} from "../src/cli/commands/rke-paper-promotion-evidence.js";

const prefix = "rke-shadow:bench-1:replay-1:";

describe("rke-paper-promotion-evidence helpers", () => {
  it("builds no-body paper and promotion refs from a replay run", () => {
    const paper = buildPaperTradingPlan("bench-1", "replay-1", {
      paperTradingPlanRef: `${prefix}paper-plan`,
      riskLimitRef: `${prefix}risk-limits`,
      stopLossOrRollbackRef: `${prefix}stop-loss`,
      operatorReviewTimestamp: "2026-07-05T12:00:00Z",
      operatorReviewApproved: true,
    });
    const promotion = buildPromotionEvidence("bench-1", "replay-1", {
      paperTradingResultRef: `${prefix}paper-result`,
      monitorSummaryRef: `${prefix}monitor-summary`,
      lockboxDecisionRef: `${prefix}lockbox-decision`,
      secondReviewTimestamp: "2026-07-06T12:00:00Z",
      secondReviewApproved: true,
    });

    expect(paper).toMatchObject({
      benchmark_run_id: "bench-1",
      paper_trading_plan_ref: `${prefix}paper-plan`,
      operator_review_approved: true,
    });
    expect(promotion).toMatchObject({
      benchmark_run_id: "bench-1",
      paper_trading_result_ref: `${prefix}paper-result`,
      decision: "approved_for_promotion_review",
      second_review_approved: true,
    });
    expect(JSON.stringify({ paper, promotion })).not.toContain(".mosaic");
    expect(JSON.stringify({ paper, promotion })).not.toContain("claim_text");
  });

  it("rejects paper refs not produced by the replay run", () => {
    expect(() =>
      buildPaperTradingPlan("bench-1", "replay-1", {
        paperTradingPlanRef: "manual:paper-plan",
        riskLimitRef: `${prefix}risk-limits`,
        stopLossOrRollbackRef: `${prefix}stop-loss`,
        operatorReviewTimestamp: "2026-07-05T12:00:00Z",
        operatorReviewApproved: true,
      }),
    ).toThrow("paperTradingPlanRef must start with rke-shadow:bench-1:replay-1:");
  });

  it("records paper and promotion evidence only after gate conditions are ready", async () => {
    const api = mockApi(
      readiness("paper_trading_entry", true),
      readiness("promotion_decision", true),
    );

    const result = await runRkePaperPromotionEvidence(api as unknown as BridgeApi, {
      benchmarkRunId: "bench-1",
      replayRunId: "replay-1",
      paperTradingPlanRef: `${prefix}paper-plan`,
      riskLimitRef: `${prefix}risk-limits`,
      stopLossOrRollbackRef: `${prefix}stop-loss`,
      operatorReviewTimestamp: "2026-07-05T12:00:00Z",
      operatorReviewApproved: true,
      paperTradingResultRef: `${prefix}paper-result`,
      monitorSummaryRef: `${prefix}monitor-summary`,
      lockboxDecisionRef: `${prefix}lockbox-decision`,
      secondReviewTimestamp: "2026-07-06T12:00:00Z",
      secondReviewApproved: true,
    });

    expect(result.paperRecord.record_status).toBe("recorded");
    expect(result.promotionRecord?.record_status).toBe("recorded");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).toHaveBeenCalledTimes(2);
    expect(api.rkeBenchmarkRecordDeliveryEvidence).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ benchmark_run_id: "bench-1", paper_trading_plan: paper }),
    );
    expect(api.rkeBenchmarkRecordDeliveryEvidence).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ benchmark_run_id: "bench-1", promotion_evidence: promotion }),
    );
  });

  it("does not record paper evidence when the gate blocks it", async () => {
    const api = mockApi(readiness("paper_trading_entry", false, ["shadow_replay_not_ready"]));

    await expect(
      runRkePaperPromotionEvidence(api as unknown as BridgeApi, {
        benchmarkRunId: "bench-1",
        replayRunId: "replay-1",
        paperTradingPlanRef: `${prefix}paper-plan`,
        riskLimitRef: `${prefix}risk-limits`,
        stopLossOrRollbackRef: `${prefix}stop-loss`,
        operatorReviewTimestamp: "2026-07-05T12:00:00Z",
        operatorReviewApproved: true,
      }),
    ).rejects.toThrow("paper_trading_entry blocked: shadow_replay_not_ready");
    expect(api.rkeBenchmarkRecordDeliveryEvidence).not.toHaveBeenCalled();
  });
});

const paper = {
  benchmark_run_id: "bench-1",
  paper_trading_plan_ref: `${prefix}paper-plan`,
  risk_limit_ref: `${prefix}risk-limits`,
  stop_loss_or_rollback_ref: `${prefix}stop-loss`,
  operator_review_timestamp: "2026-07-05T12:00:00Z",
  operator_review_approved: true,
};

const promotion = {
  benchmark_run_id: "bench-1",
  paper_trading_result_ref: `${prefix}paper-result`,
  monitor_summary_ref: `${prefix}monitor-summary`,
  lockbox_decision_ref: `${prefix}lockbox-decision`,
  second_review_timestamp: "2026-07-06T12:00:00Z",
  decision: "approved_for_promotion_review",
  second_review_approved: true,
};

function mockApi(...readinessResults: RkeDeliveryReadinessResult[]) {
  return {
    rkeBenchmarkDeliveryReadiness: vi
      .fn()
      .mockResolvedValueOnce(readinessResults[0])
      .mockResolvedValueOnce(readinessResults[1] ?? readinessResults[0]),
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
      recorded_keys: ["paper_trading_plan"],
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

function readiness(
  conditionId: string,
  ready: boolean,
  blockedReasons: string[] = [],
): RkeDeliveryReadinessResult {
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
        condition_id: conditionId,
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

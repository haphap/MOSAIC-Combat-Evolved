import type { Command } from "commander";
import pc from "picocolors";
import { BridgeClient, RpcError, BridgeApi as RuntimeBridgeApi } from "../../bridge/index.js";
import type {
  BridgeApi,
  RkeDeliveryCondition,
  RkeDeliveryEvidenceRecordResult,
  RkeDeliveryReadinessResult,
} from "../../bridge/types.js";
import { redactSensitiveText } from "../../security/redaction.js";

interface RkePaperPromotionEvidenceOptions {
  benchmarkRunId?: string;
  replayRunId?: string;
  cohort?: string;
  paperTradingPlanRef?: string;
  riskLimitRef?: string;
  stopLossOrRollbackRef?: string;
  operatorReviewTimestamp?: string;
  operatorReviewApproved?: boolean;
  paperTradingResultRef?: string;
  monitorSummaryRef?: string;
  lockboxDecisionRef?: string;
  secondReviewTimestamp?: string;
  secondReviewApproved?: boolean;
  promotionDecision?: string;
}

export function registerRkePaperPromotionEvidence(program: Command): void {
  program
    .command("rke-paper-promotion-evidence")
    .description("Record E7 paper-trading and promotion no-body refs after shadow replay.")
    .requiredOption("--benchmark-run-id <id>", "Benchmark run id")
    .requiredOption("--replay-run-id <id>", "Replay run id that produced these refs")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .requiredOption("--paper-trading-plan-ref <ref>", "Replay-produced paper plan ref")
    .requiredOption("--risk-limit-ref <ref>", "Replay-produced risk limit ref")
    .requiredOption("--stop-loss-or-rollback-ref <ref>", "Replay-produced stop-loss/rollback ref")
    .requiredOption("--operator-review-timestamp <iso>", "Paper-entry operator review time")
    .option("--operator-review-approved", "Operator approved paper-trading entry")
    .option("--paper-trading-result-ref <ref>", "Replay-produced paper result ref")
    .option("--monitor-summary-ref <ref>", "Replay-produced monitor summary ref")
    .option("--lockbox-decision-ref <ref>", "Replay-produced lockbox decision ref")
    .option("--second-review-timestamp <iso>", "Second-review time for promotion decision")
    .option("--second-review-approved", "Second reviewer approved promotion review")
    .option("--promotion-decision <id>", "Promotion decision id", "approved_for_promotion_review")
    .action(async (opts: RkePaperPromotionEvidenceOptions) => {
      const client = new BridgeClient();
      const api = new RuntimeBridgeApi(client);
      try {
        await client.start();
        const result = await runRkePaperPromotionEvidence(api, opts);
        console.log(
          pc.bold(
            `\nrke-paper-promotion-evidence paper=${result.paperRecord.record_status}` +
              (result.promotionRecord ? ` promotion=${result.promotionRecord.record_status}` : ""),
          ),
        );
        if (result.audit.delivery_blocked_reasons.length > 0) {
          console.log(pc.yellow(result.audit.delivery_blocked_reasons.slice(0, 8).join(" | ")));
        }
      } catch (err) {
        if (err instanceof RpcError) {
          console.error(pc.red(`bridge error [${err.code}]: ${redactSensitiveText(err.message)}`));
        } else {
          console.error(pc.red(`error: ${redactSensitiveText((err as Error).message)}`));
        }
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });
}

export async function runRkePaperPromotionEvidence(
  api: BridgeApi,
  opts: RkePaperPromotionEvidenceOptions,
) {
  const benchmarkRunId = required(opts.benchmarkRunId, "benchmarkRunId");
  const replayRunId = required(opts.replayRunId, "replayRunId");
  const cohort = opts.cohort ?? "cohort_default";
  const paperTradingPlan = buildPaperTradingPlan(benchmarkRunId, replayRunId, opts);
  const paperReadiness = await api.rkeBenchmarkDeliveryReadiness({
    benchmark_run_id: benchmarkRunId,
    cohort,
    paper_trading_plan: paperTradingPlan,
  });
  assertConditionReady(paperReadiness, "paper_trading_entry");
  const paperRecord = await api.rkeBenchmarkRecordDeliveryEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    paper_trading_plan: paperTradingPlan,
  });
  assertRecorded(paperRecord, "paper_trading_plan");

  let promotionEvidence: Record<string, unknown> | undefined;
  let promotionRecord: RkeDeliveryEvidenceRecordResult | undefined;
  if (hasPromotionEvidence(opts)) {
    promotionEvidence = buildPromotionEvidence(benchmarkRunId, replayRunId, opts);
    const promotionReadiness = await api.rkeBenchmarkDeliveryReadiness({
      benchmark_run_id: benchmarkRunId,
      cohort,
      paper_trading_plan: paperTradingPlan,
      promotion_evidence: promotionEvidence,
    });
    assertConditionReady(promotionReadiness, "promotion_decision");
    promotionRecord = await api.rkeBenchmarkRecordDeliveryEvidence({
      benchmark_run_id: benchmarkRunId,
      cohort,
      promotion_evidence: promotionEvidence,
    });
    assertRecorded(promotionRecord, "promotion_evidence");
  }

  const audit = await api.rkeBenchmarkDeliveryEvidenceAudit({
    benchmark_run_id: benchmarkRunId,
  });
  return {
    benchmarkRunId,
    replayRunId,
    paperTradingPlan,
    promotionEvidence,
    paperRecord,
    promotionRecord,
    audit,
  };
}

export function buildPaperTradingPlan(
  benchmarkRunId: string,
  replayRunId: string,
  opts: RkePaperPromotionEvidenceOptions,
): Record<string, unknown> {
  const prefix = replayRefPrefix(benchmarkRunId, replayRunId);
  return {
    benchmark_run_id: benchmarkRunId,
    paper_trading_plan_ref: requiredReplayRef(
      opts.paperTradingPlanRef,
      "paperTradingPlanRef",
      prefix,
    ),
    risk_limit_ref: requiredReplayRef(opts.riskLimitRef, "riskLimitRef", prefix),
    stop_loss_or_rollback_ref: requiredReplayRef(
      opts.stopLossOrRollbackRef,
      "stopLossOrRollbackRef",
      prefix,
    ),
    operator_review_timestamp: required(opts.operatorReviewTimestamp, "operatorReviewTimestamp"),
    operator_review_approved: opts.operatorReviewApproved === true,
  };
}

export function buildPromotionEvidence(
  benchmarkRunId: string,
  replayRunId: string,
  opts: RkePaperPromotionEvidenceOptions,
): Record<string, unknown> {
  const prefix = replayRefPrefix(benchmarkRunId, replayRunId);
  return {
    benchmark_run_id: benchmarkRunId,
    paper_trading_result_ref: requiredReplayRef(
      opts.paperTradingResultRef,
      "paperTradingResultRef",
      prefix,
    ),
    monitor_summary_ref: requiredReplayRef(opts.monitorSummaryRef, "monitorSummaryRef", prefix),
    lockbox_decision_ref: requiredReplayRef(opts.lockboxDecisionRef, "lockboxDecisionRef", prefix),
    second_review_timestamp: required(opts.secondReviewTimestamp, "secondReviewTimestamp"),
    decision: opts.promotionDecision ?? "approved_for_promotion_review",
    second_review_approved: opts.secondReviewApproved === true,
  };
}

function hasPromotionEvidence(opts: RkePaperPromotionEvidenceOptions): boolean {
  return Boolean(
    opts.paperTradingResultRef ||
      opts.monitorSummaryRef ||
      opts.lockboxDecisionRef ||
      opts.secondReviewTimestamp ||
      opts.secondReviewApproved,
  );
}

function replayRefPrefix(benchmarkRunId: string, replayRunId: string): string {
  return `rke-shadow:${benchmarkRunId}:${replayRunId}:`;
}

function requiredReplayRef(value: string | undefined, name: string, prefix: string): string {
  const ref = required(value, name);
  if (!ref.startsWith(prefix)) {
    throw new Error(`${name} must start with ${prefix}`);
  }
  return ref;
}

function assertConditionReady(readiness: RkeDeliveryReadinessResult, conditionId: string): void {
  const condition = readiness.conditions.find((row) => row.condition_id === conditionId);
  if (!condition) throw new Error(`${conditionId} condition missing`);
  if (!condition.ready) {
    throw new Error(`${conditionId} blocked: ${conditionReasons(condition)}`);
  }
}

function conditionReasons(condition: RkeDeliveryCondition): string {
  return condition.blocked_reasons.length > 0
    ? condition.blocked_reasons.join(", ")
    : condition.status;
}

function assertRecorded(record: RkeDeliveryEvidenceRecordResult, key: string): void {
  if (record.record_status !== "recorded") {
    throw new Error(`${key} record blocked: ${record.failures.join(", ")}`);
  }
}

function required(value: string | undefined, name: string): string {
  if (!value?.trim()) throw new Error(`${name} is required`);
  return value.trim();
}

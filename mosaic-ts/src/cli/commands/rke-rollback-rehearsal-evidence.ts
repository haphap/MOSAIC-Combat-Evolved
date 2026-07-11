import { readFileSync } from "node:fs";
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

interface RkeRollbackRehearsalEvidenceOptions {
  benchmarkRunId?: string;
  replayRunId?: string;
  cohort?: string;
  evidenceFile?: string;
}

export function registerRkeRollbackRehearsalEvidence(program: Command): void {
  program
    .command("rke-rollback-rehearsal-evidence")
    .description("Record E7 rollback rehearsal no-body refs after shadow replay.")
    .requiredOption("--benchmark-run-id <id>", "Benchmark run id")
    .requiredOption("--replay-run-id <id>", "Replay run id that produced rollback refs")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .requiredOption("--evidence-file <path>", "Private rollback rehearsal evidence JSON file")
    .action(async (opts: RkeRollbackRehearsalEvidenceOptions) => {
      const client = new BridgeClient();
      const api = new RuntimeBridgeApi(client);
      try {
        await client.start();
        const result = await runRkeRollbackRehearsalEvidence(api, opts);
        console.log(
          pc.bold(
            `\nrke-rollback-rehearsal-evidence ${result.record.record_status} ` +
              `rows=${result.rollbackEvidence.length}`,
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

export async function runRkeRollbackRehearsalEvidence(
  api: BridgeApi,
  opts: RkeRollbackRehearsalEvidenceOptions,
) {
  const benchmarkRunId = required(opts.benchmarkRunId, "benchmarkRunId");
  const replayRunId = required(opts.replayRunId, "replayRunId");
  const cohort = opts.cohort ?? "cohort_default";
  const rollbackEvidence = readRollbackEvidenceFile(
    required(opts.evidenceFile, "evidenceFile"),
    benchmarkRunId,
    replayRunId,
  );
  const readiness = await api.rkeBenchmarkDeliveryReadiness({
    benchmark_run_id: benchmarkRunId,
    cohort,
    rollback_evidence: rollbackEvidence,
  });
  assertConditionReady(readiness, "rollback_evidence");
  const record = await api.rkeBenchmarkRecordDeliveryEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    rollback_evidence: rollbackEvidence,
  });
  assertRecorded(record, "rollback_evidence");
  const audit = await api.rkeBenchmarkDeliveryEvidenceAudit({
    benchmark_run_id: benchmarkRunId,
  });
  return { benchmarkRunId, replayRunId, rollbackEvidence, record, audit };
}

export function normalizeRollbackEvidenceRows(
  value: unknown,
  benchmarkRunId: string,
  replayRunId: string,
): Record<string, unknown>[] {
  if (!Array.isArray(value)) throw new Error("rollback evidence file must contain a JSON array");
  return value.map((row, index) =>
    normalizeRollbackEvidenceRow(row, benchmarkRunId, replayRunId, index),
  );
}

function readRollbackEvidenceFile(
  path: string,
  benchmarkRunId: string,
  replayRunId: string,
): Record<string, unknown>[] {
  return normalizeRollbackEvidenceRows(
    JSON.parse(readFileSync(path, "utf-8")),
    benchmarkRunId,
    replayRunId,
  );
}

function normalizeRollbackEvidenceRow(
  value: unknown,
  benchmarkRunId: string,
  replayRunId: string,
  index: number,
): Record<string, unknown> {
  if (!isObject(value)) throw new Error(`rollback evidence row ${index} must be an object`);
  const prefix = replayRefPrefix(benchmarkRunId, replayRunId);
  const rowRunId = cleanString(value.benchmark_run_id) || benchmarkRunId;
  if (rowRunId !== benchmarkRunId) {
    throw new Error(`rollback evidence row ${index} benchmark_run_id mismatch`);
  }
  return {
    benchmark_run_id: benchmarkRunId,
    mutation_candidate_id: required(
      cleanString(value.mutation_candidate_id),
      "mutationCandidateId",
    ),
    previous_prompt_hashes: previousPromptHashes(value.previous_prompt_hashes, index),
    rollback_trigger_definition: requiredReplayRef(
      cleanString(value.rollback_trigger_definition),
      "rollbackTriggerDefinition",
      prefix,
    ),
    rollback_command_or_procedure: requiredReplayRef(
      cleanString(value.rollback_command_or_procedure),
      "rollbackCommandOrProcedure",
      prefix,
    ),
    monitor_output_ref: requiredReplayRef(
      cleanString(value.monitor_output_ref),
      "monitorOutputRef",
      prefix,
    ),
    post_rollback_verification_ref: requiredReplayRef(
      cleanString(value.post_rollback_verification_ref),
      "postRollbackVerificationRef",
      prefix,
    ),
  };
}

function previousPromptHashes(value: unknown, index: number): string[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`rollback evidence row ${index} previous_prompt_hashes must be non-empty`);
  }
  const hashes = [...new Set(value.map((item) => cleanString(item).toLowerCase()))].sort();
  for (const hash of hashes) {
    if (!/^[a-f0-9]{64}$/.test(hash)) {
      throw new Error(
        `rollback evidence row ${index} previous_prompt_hashes contains invalid hash`,
      );
    }
  }
  return hashes;
}

function replayRefPrefix(benchmarkRunId: string, replayRunId: string): string {
  return `rke-shadow:${benchmarkRunId}:${replayRunId}:`;
}

function requiredReplayRef(value: string, name: string, prefix: string): string {
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

function cleanString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

import { readFileSync } from "node:fs";
import type { Command } from "commander";
import pc from "picocolors";
import { BridgeClient, RpcError, BridgeApi as RuntimeBridgeApi } from "../../bridge/index.js";
import type {
  BridgeApi,
  RkeDeliveryEvidenceRecordResult,
  RkePatchActivationReadinessResult,
} from "../../bridge/types.js";
import { redactSensitiveText } from "../../security/redaction.js";

interface RkePatchActivationEvidenceOptions {
  benchmarkRunId?: string;
  cohort?: string;
  evidenceFile?: string;
  candidatesFile?: string;
}

export function registerRkePatchActivationEvidence(program: Command): void {
  program
    .command("rke-patch-activation-evidence")
    .description("Record E7 shadow patch activation no-body evidence refs.")
    .requiredOption("--benchmark-run-id <id>", "Benchmark run id")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .requiredOption("--evidence-file <path>", "Patch activation evidence JSON array")
    .option("--candidates-file <path>", "Optional mutation candidates JSON array")
    .action(async (opts: RkePatchActivationEvidenceOptions) => {
      const client = new BridgeClient();
      const api = new RuntimeBridgeApi(client);
      try {
        await client.start();
        const result = await runRkePatchActivationEvidence(api, opts);
        console.log(
          pc.bold(
            `\nrke-patch-activation-evidence ${result.record.record_status} ` +
              `rows=${result.patchActivationEvidence.length}`,
          ),
        );
        if (result.readiness.blocked_reasons.length > 0) {
          console.log(pc.yellow(result.readiness.blocked_reasons.slice(0, 8).join(" | ")));
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

export async function runRkePatchActivationEvidence(
  api: BridgeApi,
  opts: RkePatchActivationEvidenceOptions,
) {
  const benchmarkRunId = required(opts.benchmarkRunId, "benchmarkRunId");
  const cohort = opts.cohort ?? "cohort_default";
  const patchActivationEvidence = readPatchActivationEvidenceFile(
    required(opts.evidenceFile, "evidenceFile"),
    benchmarkRunId,
  );
  const candidates = opts.candidatesFile
    ? readObjectArrayFile(required(opts.candidatesFile, "candidatesFile"), "candidates")
    : undefined;
  const readiness = await api.rkeBenchmarkPatchActivationReadiness({
    benchmark_run_id: benchmarkRunId,
    ...(candidates ? { candidates } : {}),
    patch_activation_evidence: patchActivationEvidence,
  });
  assertPatchActivationReady(readiness);
  const record = await api.rkeBenchmarkRecordDeliveryEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    ...(candidates ? { candidates } : {}),
    patch_activation_evidence: patchActivationEvidence,
  });
  assertRecorded(record, "patch_activation_evidence");
  const audit = await api.rkeBenchmarkDeliveryEvidenceAudit({
    benchmark_run_id: benchmarkRunId,
  });
  return { benchmarkRunId, cohort, candidates, patchActivationEvidence, readiness, record, audit };
}

export function normalizePatchActivationEvidenceRows(
  value: unknown,
  benchmarkRunId: string,
): Record<string, unknown>[] {
  if (!Array.isArray(value))
    throw new Error("patch activation evidence file must contain a JSON array");
  return value.map((row, index) => normalizePatchActivationEvidenceRow(row, benchmarkRunId, index));
}

function readPatchActivationEvidenceFile(
  path: string,
  benchmarkRunId: string,
): Record<string, unknown>[] {
  return normalizePatchActivationEvidenceRows(
    JSON.parse(readFileSync(path, "utf-8")),
    benchmarkRunId,
  );
}

function normalizePatchActivationEvidenceRow(
  value: unknown,
  benchmarkRunId: string,
  index: number,
): Record<string, unknown> {
  if (!isObject(value)) throw new Error(`patch activation row ${index} must be an object`);
  const rowRunId = cleanString(value.benchmark_run_id) || benchmarkRunId;
  if (rowRunId !== benchmarkRunId) {
    throw new Error(`patch activation row ${index} benchmark_run_id mismatch`);
  }
  return {
    benchmark_run_id: benchmarkRunId,
    mutation_candidate_id: required(
      cleanString(value.mutation_candidate_id),
      "mutationCandidateId",
    ),
    patch_artifact_ref: required(cleanString(value.patch_artifact_ref), "patchArtifactRef"),
    patch_validation_ref: required(cleanString(value.patch_validation_ref), "patchValidationRef"),
    shadow_apply_ref: required(cleanString(value.shadow_apply_ref), "shadowApplyRef"),
    runtime_activation_ref: required(
      cleanString(value.runtime_activation_ref),
      "runtimeActivationRef",
    ),
    runtime_proof_ref: required(cleanString(value.runtime_proof_ref), "runtimeProofRef"),
    rollback_ref: required(cleanString(value.rollback_ref), "rollbackRef"),
    shadow_activation_passed: value.shadow_activation_passed === true,
    runtime_proof_passed: value.runtime_proof_passed === true,
    production_activation_allowed: requiredFalse(
      value.production_activation_allowed,
      "productionActivationAllowed",
    ),
  };
}

function readObjectArrayFile(path: string, label: string): Record<string, unknown>[] {
  const value = JSON.parse(readFileSync(path, "utf-8"));
  if (!Array.isArray(value)) throw new Error(`${label} file must contain a JSON array`);
  return value.map((row, index) => {
    if (!isObject(row)) throw new Error(`${label} row ${index} must be an object`);
    return row;
  });
}

function assertPatchActivationReady(readiness: RkePatchActivationReadinessResult): void {
  if (readiness.readiness_status !== "ready" && readiness.readiness_status !== "not_applicable") {
    throw new Error(`patch activation blocked: ${readiness.blocked_reasons.join(", ")}`);
  }
}

function requiredFalse(value: unknown, name: string): false {
  if (value !== false) throw new Error(`${name} must be false`);
  return false;
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

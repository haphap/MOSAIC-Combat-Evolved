import { readFileSync } from "node:fs";
import type { Command } from "commander";
import pc from "picocolors";
import { BridgeClient, RpcError, BridgeApi as RuntimeBridgeApi } from "../../bridge/index.js";
import type {
  BridgeApi,
  RkeAllAgentPromptProvenanceReadinessResult,
  RkeDeliveryEvidenceRecordResult,
} from "../../bridge/types.js";
import { redactSensitiveText } from "../../security/redaction.js";

interface RkePromptProvenanceEvidenceOptions {
  benchmarkRunId?: string;
  cohort?: string;
  releaseChecksFile?: string;
}

export function registerRkePromptProvenanceEvidence(program: Command): void {
  program
    .command("rke-prompt-provenance-evidence")
    .description("Record E0/E7 all-agent prompt provenance release checks.")
    .requiredOption("--benchmark-run-id <id>", "Benchmark run id")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--release-checks-file <path>", "No-body prompt release checks JSON array")
    .action(async (opts: RkePromptProvenanceEvidenceOptions) => {
      const client = new BridgeClient();
      const api = new RuntimeBridgeApi(client);
      try {
        await client.start();
        const result = await runRkePromptProvenanceEvidence(api, opts);
        console.log(
          pc.bold(
            `\nrke-prompt-provenance-evidence ${result.record.record_status} ` +
              `rows=${result.releaseChecks.length}`,
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

export async function runRkePromptProvenanceEvidence(
  api: BridgeApi,
  opts: RkePromptProvenanceEvidenceOptions,
) {
  const benchmarkRunId = required(opts.benchmarkRunId, "benchmarkRunId");
  const cohort = opts.cohort ?? "cohort_default";
  const releaseChecks = await loadReleaseChecks(api, opts, benchmarkRunId, cohort);
  const readiness = await api.rkeBenchmarkAllAgentPromptProvenanceReadiness({
    benchmark_run_id: benchmarkRunId,
    cohort,
    release_checks: releaseChecks,
  });
  assertPromptProvenanceReady(readiness);
  const record = await api.rkeBenchmarkRecordDeliveryEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    all_agent_prompt_release_checks: releaseChecks,
  });
  assertRecorded(record, "all_agent_prompt_release_checks");
  const audit = await api.rkeBenchmarkDeliveryEvidenceAudit({
    benchmark_run_id: benchmarkRunId,
  });
  return { benchmarkRunId, cohort, releaseChecks, readiness, record, audit };
}

async function loadReleaseChecks(
  api: BridgeApi,
  opts: RkePromptProvenanceEvidenceOptions,
  benchmarkRunId: string,
  cohort: string,
): Promise<Record<string, unknown>[]> {
  if (opts.releaseChecksFile) {
    return readReleaseChecksFile(opts.releaseChecksFile, benchmarkRunId);
  }
  const generated = await api.promptsFormalReleaseChecks({
    benchmark_run_id: benchmarkRunId,
    cohort,
  });
  if (!generated.ready) {
    throw new Error(`formal release checks blocked: ${generated.blocked_reasons.join(", ")}`);
  }
  return generated.rows.map((row) => ({ ...row }) as Record<string, unknown>);
}

export function normalizeReleaseCheckRows(
  value: unknown,
  benchmarkRunId: string,
): Record<string, unknown>[] {
  if (!Array.isArray(value)) throw new Error("release checks file must contain a JSON array");
  return value.map((row, index) => normalizeReleaseCheckRow(row, benchmarkRunId, index));
}

function readReleaseChecksFile(path: string, benchmarkRunId: string): Record<string, unknown>[] {
  return normalizeReleaseCheckRows(JSON.parse(readFileSync(path, "utf-8")), benchmarkRunId);
}

function normalizeReleaseCheckRow(
  value: unknown,
  benchmarkRunId: string,
  index: number,
): Record<string, unknown> {
  if (!isObject(value)) throw new Error(`release check row ${index} must be an object`);
  const rowRunId = cleanString(value.benchmark_run_id) || benchmarkRunId;
  if (rowRunId !== benchmarkRunId) {
    throw new Error(`release check row ${index} benchmark_run_id mismatch`);
  }
  return {
    benchmark_run_id: benchmarkRunId,
    agent: required(cleanString(value.agent), "agent"),
    lang: required(cleanString(value.lang), "lang"),
    prompt_repo_id: required(cleanString(value.prompt_repo_id), "promptRepoId"),
    prompt_repo_revision: required(cleanString(value.prompt_repo_revision), "promptRepoRevision"),
    prompt_file_path: required(cleanString(value.prompt_file_path), "promptFilePath"),
    prompt_sha256: requiredHash(cleanString(value.prompt_sha256), "promptSha256"),
    prompt_version_id: positiveInteger(value.prompt_version_id, "promptVersionId"),
    audit_version_ref: required(cleanString(value.audit_version_ref), "auditVersionRef"),
    verify_release_ref: required(cleanString(value.verify_release_ref), "verifyReleaseRef"),
    leak_drift_check_ref: required(cleanString(value.leak_drift_check_ref), "leakDriftCheckRef"),
    prompt_contract_check_ref: required(
      cleanString(value.prompt_contract_check_ref),
      "promptContractCheckRef",
    ),
    verify_release_passed: value.verify_release_passed === true,
    leak_drift_passed: value.leak_drift_passed === true,
    prompt_contract_check_passed: value.prompt_contract_check_passed === true,
  };
}

function assertPromptProvenanceReady(readiness: RkeAllAgentPromptProvenanceReadinessResult): void {
  if (readiness.readiness_status !== "ready") {
    throw new Error(`prompt provenance blocked: ${readiness.blocked_reasons.join(", ")}`);
  }
}

function assertRecorded(record: RkeDeliveryEvidenceRecordResult, key: string): void {
  if (record.record_status !== "recorded") {
    throw new Error(`${key} record blocked: ${record.failures.join(", ")}`);
  }
}

function positiveInteger(value: unknown, name: string): number {
  if (!Number.isInteger(value) || typeof value !== "number" || value < 1) {
    throw new Error(`${name} must be a positive integer`);
  }
  return value;
}

function requiredHash(value: string, name: string): string {
  const hash = required(value, name).toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(hash)) throw new Error(`${name} must be a sha256 hex digest`);
  return hash;
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

import { readFileSync } from "node:fs";
import type { Command } from "commander";
import pc from "picocolors";
import { BridgeClient, RpcError, BridgeApi as RuntimeBridgeApi } from "../../bridge/index.js";
import type {
  BridgeApi,
  RkeDeliveryEvidenceRecordResult,
  RkePromptMutationReleaseReadinessResult,
} from "../../bridge/types.js";
import { redactSensitiveText } from "../../security/redaction.js";

interface RkePromptMutationReleaseEvidenceOptions {
  benchmarkRunId?: string;
  cohort?: string;
  releaseChecksFile?: string;
  candidatesFile?: string;
}

export function registerRkePromptMutationReleaseEvidence(program: Command): void {
  program
    .command("rke-prompt-mutation-release-evidence")
    .description("Record E4 prompt mutation release no-body evidence refs.")
    .requiredOption("--benchmark-run-id <id>", "Benchmark run id")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .requiredOption("--release-checks-file <path>", "Prompt mutation release checks JSON array")
    .requiredOption("--candidates-file <path>", "Mutation candidates JSON array")
    .action(async (opts: RkePromptMutationReleaseEvidenceOptions) => {
      const client = new BridgeClient();
      const api = new RuntimeBridgeApi(client);
      try {
        await client.start();
        const result = await runRkePromptMutationReleaseEvidence(api, opts);
        console.log(
          pc.bold(
            `\nrke-prompt-mutation-release-evidence ${result.record.record_status} ` +
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

export async function runRkePromptMutationReleaseEvidence(
  api: BridgeApi,
  opts: RkePromptMutationReleaseEvidenceOptions,
) {
  const benchmarkRunId = required(opts.benchmarkRunId, "benchmarkRunId");
  const cohort = opts.cohort ?? "cohort_default";
  const releaseChecks = readReleaseChecksFile(
    required(opts.releaseChecksFile, "releaseChecksFile"),
    benchmarkRunId,
  );
  const candidates = readObjectArrayFile(
    required(opts.candidatesFile, "candidatesFile"),
    "candidates",
  );
  const readiness = await api.rkeBenchmarkPromptMutationReleaseReadiness({
    benchmark_run_id: benchmarkRunId,
    candidates,
    release_checks: releaseChecks,
  });
  assertPromptMutationReleaseReady(readiness);
  const record = await api.rkeBenchmarkRecordDeliveryEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    candidates,
    prompt_mutation_release_checks: releaseChecks,
  });
  assertRecorded(record, "prompt_mutation_release_checks");
  const audit = await api.rkeBenchmarkDeliveryEvidenceAudit({
    benchmark_run_id: benchmarkRunId,
  });
  return { benchmarkRunId, cohort, candidates, releaseChecks, readiness, record, audit };
}

export function normalizePromptMutationReleaseRows(
  value: unknown,
  benchmarkRunId: string,
): Record<string, unknown>[] {
  if (!Array.isArray(value)) throw new Error("release checks file must contain a JSON array");
  return value.map((row, index) => normalizeReleaseRow(row, benchmarkRunId, index));
}

function readReleaseChecksFile(path: string, benchmarkRunId: string): Record<string, unknown>[] {
  return normalizePromptMutationReleaseRows(
    JSON.parse(readFileSync(path, "utf-8")),
    benchmarkRunId,
  );
}

function normalizeReleaseRow(
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
    mutation_candidate_id: required(
      cleanString(value.mutation_candidate_id),
      "mutationCandidateId",
    ),
    prompt_version_id: positiveInteger(value.prompt_version_id, "promptVersionId"),
    prompt_repo_id: required(cleanString(value.prompt_repo_id), "promptRepoId"),
    private_prompt_branch: required(
      cleanString(value.private_prompt_branch),
      "privatePromptBranch",
    ),
    base_prompt_repo_revision: required(
      cleanString(value.base_prompt_repo_revision),
      "basePromptRepoRevision",
    ),
    overwrite_target_paths: stringList(value.overwrite_target_paths, "overwriteTargetPaths"),
    audit_version_ref: required(cleanString(value.audit_version_ref), "auditVersionRef"),
    prompt_commit_hash: required(cleanString(value.prompt_commit_hash), "promptCommitHash"),
    prompt_sha256: requiredHash(cleanString(value.prompt_sha256), "promptSha256"),
    verify_release_ref: required(cleanString(value.verify_release_ref), "verifyReleaseRef"),
    leak_drift_check_ref: required(cleanString(value.leak_drift_check_ref), "leakDriftCheckRef"),
    prompt_contract_check_ref: required(
      cleanString(value.prompt_contract_check_ref),
      "promptContractCheckRef",
    ),
    verify_release_passed: value.verify_release_passed === true,
    leak_drift_passed: value.leak_drift_passed === true,
    prompt_contract_check_passed: value.prompt_contract_check_passed === true,
    release_ready: value.release_ready === true,
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

function assertPromptMutationReleaseReady(
  readiness: RkePromptMutationReleaseReadinessResult,
): void {
  if (readiness.readiness_status !== "ready" && readiness.readiness_status !== "not_applicable") {
    throw new Error(`prompt mutation release blocked: ${readiness.blocked_reasons.join(", ")}`);
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

function stringList(value: unknown, name: string): string[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`${name} must be a non-empty string array`);
  }
  return value.map((item) => required(cleanString(item), name));
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

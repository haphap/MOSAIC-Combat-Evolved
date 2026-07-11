import type { Command } from "commander";
import pc from "picocolors";
import { BridgeClient, RpcError, BridgeApi as RuntimeBridgeApi } from "../../bridge/index.js";
import type {
  BridgeApi,
  RkeAgentProfileEvolutionReadinessResult,
  RkeDeliveryEvidenceRecordResult,
} from "../../bridge/types.js";
import { redactSensitiveText } from "../../security/redaction.js";

interface RkeProfileEvidenceOptions {
  benchmarkRunId?: string;
  cohort?: string;
  profileUpdateRef?: string;
  evolutionInputRef?: string;
  sourceProseAuditRef?: string;
  noSourceProseAuditRef?: string;
}

export function registerRkeProfileEvidence(program: Command): void {
  program
    .command("rke-profile-evidence")
    .description("Record E3 agent profile/evolution no-body evidence refs.")
    .requiredOption("--benchmark-run-id <id>", "Benchmark run id")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .requiredOption("--profile-update-ref <ref>", "Profile update evidence ref")
    .requiredOption("--evolution-input-ref <ref>", "Evolution input evidence ref")
    .requiredOption("--source-prose-audit-ref <ref>", "No-source-prose audit ref")
    .action(async (opts: RkeProfileEvidenceOptions) => {
      const client = new BridgeClient();
      const api = new RuntimeBridgeApi(client);
      try {
        await client.start();
        const result = await runRkeProfileEvidence(api, opts);
        console.log(
          pc.bold(
            `\nrke-profile-evidence ${result.record.record_status} ` +
              `rows=${result.readiness.row_count}`,
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

export async function runRkeProfileEvidence(api: BridgeApi, opts: RkeProfileEvidenceOptions) {
  const benchmarkRunId = required(opts.benchmarkRunId, "benchmarkRunId");
  const cohort = opts.cohort ?? "cohort_default";
  const profileEvidence = buildProfileEvidence(benchmarkRunId, opts);
  const readiness = await api.rkeBenchmarkAgentProfileEvolutionReadiness({
    benchmark_run_id: benchmarkRunId,
    profile_evidence: profileEvidence,
  });
  assertProfileReady(readiness);
  const record = await api.rkeBenchmarkRecordDeliveryEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    profile_evidence: profileEvidence,
  });
  assertRecorded(record, "profile_evidence");
  const audit = await api.rkeBenchmarkDeliveryEvidenceAudit({
    benchmark_run_id: benchmarkRunId,
  });
  return { benchmarkRunId, cohort, profileEvidence, readiness, record, audit };
}

export function buildProfileEvidence(
  benchmarkRunId: string,
  opts: RkeProfileEvidenceOptions,
): Record<string, unknown> {
  return {
    benchmark_run_id: benchmarkRunId,
    profile_update_ref: required(opts.profileUpdateRef, "profileUpdateRef"),
    evolution_input_ref: required(opts.evolutionInputRef, "evolutionInputRef"),
    no_source_prose_audit_ref: required(
      opts.noSourceProseAuditRef ?? opts.sourceProseAuditRef,
      "sourceProseAuditRef",
    ),
  };
}

function assertProfileReady(readiness: RkeAgentProfileEvolutionReadinessResult): void {
  if (readiness.readiness_status !== "ready") {
    throw new Error(`profile evidence blocked: ${readiness.blocked_reasons.join(", ")}`);
  }
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

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import type { Command } from "commander";
import pc from "picocolors";
import { AGENTS_BY_LAYER, ALL_AGENTS, LAYER_BY_AGENT } from "../../agents/prompts/cohorts.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { findRepoRoot } from "../../bridge/python.js";
import type { RkeAgentFootprintSummaryResult } from "../../bridge/types.js";
import { redactSensitiveText } from "../../security/redaction.js";

const PRIVATE_OUTPUT_DIR = ".mosaic/rke/all_agent_evolution/darwinian_autoresearch_compute";

interface RkeDarwinianComputeOptions {
  benchmarkRunId?: string;
  replayRunId?: string;
  cohort?: string;
  riskAdjustedReturn?: string;
  alpha?: string;
  maxDrawdown?: string;
  turnover?: string;
  costBps?: string;
  promptRepoId?: string;
  promptRepoRevision?: string;
  promptSha256?: string;
  promptCommitHash?: string;
}

interface FootprintRow {
  benchmark_run_id?: string;
  agent?: string;
  layer?: string;
  rke_context_hash?: string;
  rke_prior_usage_quality?: string;
  current_data_confirmed?: boolean;
  stale_prior_rejected?: boolean;
  contradictory_prior_handled?: boolean;
}

export interface AgentSkillWeight {
  agent: string;
  layer: string;
  weight: number;
  cold_start: boolean;
  current_data_skill: number;
  rke_prior_usage_skill: number;
  stale_prior_rejection_skill: number;
  schema_contract_skill: number;
  downstream_outcome_skill: number;
  turnover_cost_skill: number;
  mutation_reliability_skill: number;
}

export function registerRkeDarwinianCompute(program: Command): void {
  program
    .command("rke-darwinian-compute")
    .description("Compute E5 Darwinian/autoresearch weight evidence from private footprint rows.")
    .requiredOption("--benchmark-run-id <id>", "Benchmark run id")
    .requiredOption("--replay-run-id <id>", "Replay run id that will consume these weights")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .requiredOption("--risk-adjusted-return <num>", "Risk-adjusted downstream return")
    .requiredOption("--alpha <num>", "Benchmark-relative downstream alpha")
    .requiredOption("--max-drawdown <num>", "Downstream max drawdown, usually negative")
    .requiredOption("--turnover <num>", "Downstream turnover")
    .requiredOption("--cost-bps <num>", "Downstream cost in bps")
    .requiredOption("--prompt-repo-id <id>", "Private prompt repo id")
    .requiredOption("--prompt-repo-revision <sha>", "Private prompt repo revision")
    .requiredOption("--prompt-sha256 <sha>", "Prompt hash consumed by mutation/provenance")
    .option("--prompt-commit-hash <sha>", "Private prompt commit hash")
    .action(async (opts: RkeDarwinianComputeOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const result = await runRkeDarwinianCompute(api, opts);
        console.log(
          pc.bold(
            `\nrke-darwinian-compute ${result.readiness.readiness_status} ` +
              `weights=${result.weights.length} non_stub=${result.nonStubWeightCount}`,
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

export async function runRkeDarwinianCompute(api: BridgeApi, opts: RkeDarwinianComputeOptions) {
  const benchmarkRunId = required(opts.benchmarkRunId, "benchmarkRunId");
  const replayRunId = required(opts.replayRunId, "replayRunId");
  const cohort = opts.cohort ?? "cohort_default";
  const downstream = buildDownstreamOutcomeMetrics(benchmarkRunId, opts);
  const promptMutationProvenance = buildPromptMutationProvenance(benchmarkRunId, opts);
  const summary = await api.rkeBenchmarkAgentFootprintSummary({ benchmark_run_id: benchmarkRunId });
  const rows = readPrivateFootprintRows(summary, benchmarkRunId);
  const weights = computeAgentSkillWeights(rows, downstream);
  const nonStubWeightCount = weights.filter(
    (row) => !row.cold_start && !isLayerUniform(row),
  ).length;
  const artifactRef = writePrivateComputeArtifact(benchmarkRunId, replayRunId, weights);
  const consumptionEvidence = buildConsumptionEvidence(
    benchmarkRunId,
    replayRunId,
    artifactRef,
    weights.length,
    nonStubWeightCount,
  );
  const readiness = await api.rkeBenchmarkDarwinianAutoresearchConsumptionReadiness({
    benchmark_run_id: benchmarkRunId,
    downstream_outcome_metrics: downstream,
    prompt_mutation_provenance: promptMutationProvenance,
    consumption_evidence: consumptionEvidence,
  });
  const record = await api.rkeBenchmarkRecordDeliveryEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    downstream_outcome_metrics: downstream,
    prompt_mutation_provenance: promptMutationProvenance,
    darwinian_autoresearch_consumption_evidence: consumptionEvidence,
  });
  return { benchmarkRunId, replayRunId, weights, nonStubWeightCount, readiness, record };
}

export function computeAgentSkillWeights(
  rows: readonly FootprintRow[],
  downstream: Record<string, unknown>,
): AgentSkillWeight[] {
  const rawByAgent = new Map<string, Omit<AgentSkillWeight, "weight"> & { raw: number }>();
  for (const agent of ALL_AGENTS) {
    const agentRows = rows.filter((row) => row.agent === agent);
    const contextRows = agentRows.filter((row) => row.rke_context_hash);
    const contextCount = Math.max(contextRows.length, 1);
    const currentDataSkill = ratio(
      contextRows.filter((row) => row.current_data_confirmed === true).length,
      contextCount,
    );
    const rkePriorUsageSkill = ratio(
      contextRows.filter((row) => row.rke_prior_usage_quality === "used_ranked_prior").length,
      contextCount,
    );
    const stalePriorRejectionSkill = ratio(
      contextRows.filter(
        (row) => row.stale_prior_rejected === true || row.contradictory_prior_handled === true,
      ).length,
      contextCount,
    );
    const downstreamOutcomeSkill = clamp01(
      0.5 +
        Number(downstream.risk_adjusted_return ?? 0) +
        Number(downstream.alpha ?? 0) -
        Math.abs(Number(downstream.max_drawdown ?? 0)),
    );
    const turnoverCostSkill = clamp01(
      1 - Number(downstream.turnover ?? 0) * 0.1 - Number(downstream.cost_bps ?? 0) / 1000,
    );
    const coldStart = agentRows.length === 0;
    const schemaContractSkill = coldStart ? 0.5 : 1;
    const mutationReliabilitySkill = 1;
    const raw = coldStart
      ? 0.2
      : 0.25 * currentDataSkill +
        0.2 * rkePriorUsageSkill +
        0.15 * stalePriorRejectionSkill +
        0.15 * schemaContractSkill +
        0.15 * downstreamOutcomeSkill +
        0.05 * turnoverCostSkill +
        0.05 * mutationReliabilitySkill;
    rawByAgent.set(agent, {
      agent,
      layer: LAYER_BY_AGENT[agent] ?? "unknown",
      cold_start: coldStart,
      current_data_skill: currentDataSkill,
      rke_prior_usage_skill: rkePriorUsageSkill,
      stale_prior_rejection_skill: stalePriorRejectionSkill,
      schema_contract_skill: schemaContractSkill,
      downstream_outcome_skill: downstreamOutcomeSkill,
      turnover_cost_skill: turnoverCostSkill,
      mutation_reliability_skill: mutationReliabilitySkill,
      raw,
    });
  }

  const out: AgentSkillWeight[] = [];
  for (const [layer, agents] of Object.entries(AGENTS_BY_LAYER)) {
    const layerRows = agents
      .map((agent) => rawByAgent.get(agent))
      .filter((row) => row !== undefined);
    const weights = normalizeLayer(layerRows.map((row) => row.raw));
    for (const [index, row] of layerRows.entries()) {
      const { raw: _raw, ...rest } = row;
      out.push({ ...rest, layer, weight: round6(weights[index] ?? 0) });
    }
  }
  return out;
}

export function buildConsumptionEvidence(
  benchmarkRunId: string,
  replayRunId: string,
  artifactRef: string,
  agentWeightCount: number,
  nonStubWeightCount: number,
): Record<string, unknown> {
  return {
    benchmark_run_id: benchmarkRunId,
    replay_run_id: replayRunId,
    input_manifest_ref: `rke-darwinian:${benchmarkRunId}:input-manifest`,
    rke_prior_usage_metrics_ref: `${artifactRef}:rke-prior-usage`,
    downstream_outcome_metrics_ref: `${artifactRef}:downstream-outcome`,
    darwinian_weight_update_ref: `${artifactRef}:weights`,
    agent_skill_decomposition_ref: `${artifactRef}:agent-skills`,
    autoresearch_update_ref: `${artifactRef}:autoresearch-updates`,
    rejected_update_reasons_ref: `${artifactRef}:rejected-updates`,
    rollback_readiness_ref: `${artifactRef}:rollback-readiness`,
    agent_weight_count: agentWeightCount,
    non_stub_weight_count: nonStubWeightCount,
    layer_weight_sum_ready: true,
    darwinian_consumed: true,
    autoresearch_consumed: true,
    rke_prior_treated_as_current_data: false,
    production_weight_update_allowed: false,
  };
}

function readPrivateFootprintRows(
  summary: RkeAgentFootprintSummaryResult,
  benchmarkRunId: string,
): FootprintRow[] {
  const path = isAbsolute(summary.private_rows_path)
    ? summary.private_rows_path
    : join(findRepoRoot(), summary.private_rows_path);
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf-8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line) as FootprintRow)
    .filter((row) => row.benchmark_run_id === benchmarkRunId);
}

function writePrivateComputeArtifact(
  benchmarkRunId: string,
  replayRunId: string,
  weights: readonly AgentSkillWeight[],
): string {
  const root = join(findRepoRoot(), PRIVATE_OUTPUT_DIR);
  mkdirSync(root, { recursive: true });
  const payload = { benchmark_run_id: benchmarkRunId, replay_run_id: replayRunId, weights };
  const hash = createHash("sha256").update(JSON.stringify(payload)).digest("hex").slice(0, 16);
  writeFileSync(
    join(root, `${benchmarkRunId}.${replayRunId}.${hash}.json`),
    JSON.stringify(payload),
    "utf-8",
  );
  return `rke-darwinian:${benchmarkRunId}:${replayRunId}:${hash}`;
}

function buildDownstreamOutcomeMetrics(
  benchmarkRunId: string,
  opts: RkeDarwinianComputeOptions,
): Record<string, unknown> {
  return {
    benchmark_run_id: benchmarkRunId,
    risk_adjusted_return: numeric(opts.riskAdjustedReturn, "riskAdjustedReturn"),
    alpha: numeric(opts.alpha, "alpha"),
    max_drawdown: numeric(opts.maxDrawdown, "maxDrawdown"),
    turnover: numeric(opts.turnover, "turnover"),
    cost_bps: numeric(opts.costBps, "costBps"),
  };
}

function buildPromptMutationProvenance(
  benchmarkRunId: string,
  opts: RkeDarwinianComputeOptions,
): Record<string, unknown> {
  return {
    benchmark_run_id: benchmarkRunId,
    prompt_repo_id: required(opts.promptRepoId, "promptRepoId"),
    prompt_repo_revision: required(opts.promptRepoRevision, "promptRepoRevision"),
    prompt_sha256: required(opts.promptSha256, "promptSha256"),
    ...(opts.promptCommitHash ? { prompt_commit_hash: opts.promptCommitHash } : {}),
  };
}

function normalizeLayer(raw: readonly number[]): number[] {
  const n = raw.length;
  if (n === 0) return [];
  const floor = 0.5 / n;
  const cap = 2 / n;
  const sum = raw.reduce((acc, value) => acc + Math.max(value, 0), 0) || n;
  const clipped = raw.map((value) => Math.min(cap, Math.max(floor, Math.max(value, 0) / sum)));
  const clippedSum = clipped.reduce((acc, value) => acc + value, 0) || 1;
  return clipped.map((value) => value / clippedSum);
}

function isLayerUniform(row: AgentSkillWeight): boolean {
  const n = AGENTS_BY_LAYER[row.layer as keyof typeof AGENTS_BY_LAYER]?.length ?? 1;
  return Math.abs(row.weight - 1 / n) < 0.000001;
}

function numeric(value: string | undefined, name: string): number {
  const out = Number(value);
  if (!Number.isFinite(out)) throw new Error(`${name} must be numeric`);
  return out;
}

function required(value: string | undefined, name: string): string {
  if (!value?.trim()) throw new Error(`${name} is required`);
  return value.trim();
}

function ratio(numerator: number, denominator: number): number {
  return denominator <= 0 ? 0 : numerator / denominator;
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function round6(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}

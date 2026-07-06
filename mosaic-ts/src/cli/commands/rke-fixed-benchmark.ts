import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { Command } from "commander";
import pc from "picocolors";
import { captureDailyCycleRkeFootprints } from "../../agents/rke_footprints.js";
import type { DailyCycleStateType } from "../../agents/state.js";
import { BridgeClient, RpcError, BridgeApi as RuntimeBridgeApi } from "../../bridge/index.js";
import { findRepoRoot } from "../../bridge/python.js";
import type {
  BridgeApi,
  RkeBenchmarkModelConfig,
  RkeFixedEpisodeManifestResult,
} from "../../bridge/types.js";
import { buildDailyCycleGraph } from "../../graph/daily_cycle.js";
import { createLlmFromConfig, type LlmHandle } from "../../llm/factory.js";
import { redactSensitiveText } from "../../security/redaction.js";
import { buildFakeLlmHandle, makeInitialState } from "../_backtest_helpers.js";
import { applyPromptSourceOverrides } from "../prompt-source.js";

const PRIVATE_OUTPUT_DIR = ".mosaic/rke/all_agent_evolution/fixed_episode_benchmark";

interface RkeFixedBenchmarkOptions {
  benchmarkRunId?: string;
  cohort?: string;
  fakeLlm?: boolean;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
  maxTokens?: string;
  vetoThreshold?: string;
  promptsRepo?: string;
  promptsRoot?: string;
  maxRuns?: string;
  modelConfig?: string[];
  asOfDate?: string[];
  manualReviewApproved?: boolean;
  reviewerTimestamp?: string;
  reviewerIndependenceConfirmed?: boolean;
}

interface PairedOutputRecord {
  benchmark_run_id: string;
  episode_id: string;
  as_of_date: string;
  model_config_id: string;
  agent: string;
  layer: string;
  output_sha256: string;
}

interface BenchmarkRunStats {
  benchmarkRunId: string;
  pairedOutputCount: number;
  modelConfigOutputCounts: Record<string, number>;
  coveredEpisodeIds: Set<string>;
  coveredAsOfDates: Set<string>;
  coveredAgents: Set<string>;
  currentDataViolationCount: number;
  fallbackPromptRunCount: number;
  errorCount: number;
}

export function registerRkeFixedBenchmark(program: Command): void {
  program
    .command("rke-fixed-benchmark")
    .description(
      "Run the RKE E2 fixed-episode benchmark producer and record no-body evidence refs.",
    )
    .option("--benchmark-run-id <id>", "Benchmark run id (default rke-fixed-<timestamp>)")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option(
      "--fake-llm",
      "Use fake LLM for smoke only; evidence remains blocked as fallback output",
    )
    .option("--llm-provider <name>", "Baseline model provider override")
    .option("--model <name>", "Baseline model override")
    .option("--base-url <url>", "Baseline model base URL override")
    .option("--max-tokens <n>", "Per-call LLM max token cap")
    .option("--veto-threshold <num>", "CRO veto threshold (default 0.5)")
    .option("--prompts-repo <path>", "Use a private prompt git repo for this run")
    .option("--prompts-root <path>", "Override prompts root directory")
    .option("--max-runs <n>", "Cap episode/model runs for smoke; formal runs omit this")
    .option("--model-config <id>", "Run only this model config id; repeatable", collect, [])
    .option("--as-of-date <YYYY-MM-DD>", "Run only this as_of_date; repeatable", collect, [])
    .option("--manual-review-approved", "Attach approved manual-review evidence")
    .option("--reviewer-timestamp <iso>", "Manual-review timestamp")
    .option("--reviewer-independence-confirmed", "Manual reviewer is independent")
    .action(async (opts: RkeFixedBenchmarkOptions) => {
      const client = new BridgeClient();
      const api = new RuntimeBridgeApi(client);
      try {
        applyPromptSourceOverrides(opts);
        await client.start();
        const result = await runRkeFixedBenchmark(api, opts, (msg) =>
          console.log(pc.dim(redactSensitiveText(msg))),
        );
        console.log(
          pc.bold(
            `\nrke-fixed-benchmark ${result.evidence.evidence_status} ` +
              `paired=${result.stats.pairedOutputCount}`,
          ),
        );
        if (result.evidence.blocked_reasons.length > 0) {
          console.log(pc.yellow(result.evidence.blocked_reasons.slice(0, 8).join(" | ")));
        }
      } catch (err) {
        if (err instanceof RpcError) {
          console.error(pc.red(`bridge error [${err.code}]: ${redactSensitiveText(err.message)}`));
        } else {
          console.error(pc.red(`error: ${redactSensitiveText((err as Error).message)}`));
        }
        const tail = client.stderrTail.trim();
        if (tail) {
          console.error(pc.dim("\n--- bridge stderr (tail) ---"));
          console.error(pc.dim(redactSensitiveText(tail).slice(-2000)));
        }
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });
}

function collect(value: string, previous: string[]): string[] {
  previous.push(value);
  return previous;
}

export async function runRkeFixedBenchmark(
  api: BridgeApi,
  opts: RkeFixedBenchmarkOptions,
  onLog: (msg: string) => void = () => undefined,
) {
  const cohort = opts.cohort ?? "cohort_default";
  const benchmarkRunId = opts.benchmarkRunId ?? `rke-fixed-${Date.now()}`;
  const manifest = await api.rkeBenchmarkFixedEpisodeManifest({ cohort });
  if (manifest.benchmark_status !== "ready_to_run") {
    throw new Error(
      `fixed episode manifest blocked: ${manifest.prompt_preflight.blocked_reasons.join(", ")}`,
    );
  }
  const contractCheck = await api.promptsContractCheck({
    cohort,
    benchmark_run_id: benchmarkRunId,
  });
  if (!contractCheck.ready) {
    throw new Error(`prompt contract check blocked: ${contractCheck.blocked_reasons.join(", ")}`);
  }

  const config = await api.configGet();
  const modelConfigs = selectModelConfigs(manifest, opts.modelConfig);
  if (modelConfigs.length === 0) {
    throw new Error("no benchmark model configs selected");
  }
  const maxRuns = opts.maxRuns ? Number.parseInt(opts.maxRuns, 10) : undefined;
  const maxTokens = opts.maxTokens ? Number.parseInt(opts.maxTokens, 10) : undefined;
  const stats: BenchmarkRunStats = {
    benchmarkRunId,
    pairedOutputCount: 0,
    modelConfigOutputCounts: {},
    coveredEpisodeIds: new Set(),
    coveredAsOfDates: new Set(),
    coveredAgents: new Set(),
    currentDataViolationCount: 0,
    fallbackPromptRunCount: 0,
    errorCount: 0,
  };
  let runCount = 0;

  mkdirSync(fixedBenchmarkPrivateOutputDir(), { recursive: true });
  const completedRuns = completedEpisodeDateModelRuns(
    readPairedOutputRecords(benchmarkRunId),
    manifest.agent_count,
  );
  for (const modelConfig of modelConfigs) {
    if (maxRuns !== undefined && runCount >= maxRuns) break;
    const llmHandle = makeLlmHandleForModelConfig(config, modelConfig, opts, maxTokens);
    const graph = buildDailyCycleGraph({
      llmHandle,
      api,
      config,
      vetoThreshold: opts.vetoThreshold ? Number(opts.vetoThreshold) : 0.5,
      ...(opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {}),
      onLog,
    });
    stats.modelConfigOutputCounts[modelConfig.model_config_id] = 0;

    for (const item of episodeDateCases(manifest, opts.asOfDate)) {
      if (maxRuns !== undefined && runCount >= maxRuns) break;
      const runKey = `${modelConfig.model_config_id}|${item.episode_id}|${item.as_of_date}`;
      if (completedRuns.has(runKey)) {
        onLog(`skip completed ${modelConfig.model_config_id} ${item.as_of_date}`);
        continue;
      }
      runCount += 1;
      try {
        const initialState = makeInitialState(cohort, item.as_of_date);
        initialState.trace_id = `${benchmarkRunId}:${modelConfig.model_config_id}:${item.as_of_date}`;
        const final = (await graph.invoke(initialState)) as DailyCycleStateType;
        const rows = collectPairedOutputRecords(
          benchmarkRunId,
          item.episode_id,
          item.as_of_date,
          modelConfig.model_config_id,
          final,
        );
        writePairedOutputRecords(benchmarkRunId, rows);
        stats.pairedOutputCount += rows.length;
        stats.modelConfigOutputCounts[modelConfig.model_config_id] =
          (stats.modelConfigOutputCounts[modelConfig.model_config_id] ?? 0) + rows.length;
        stats.coveredEpisodeIds.add(item.episode_id);
        stats.coveredAsOfDates.add(item.as_of_date);
        for (const row of rows) stats.coveredAgents.add(row.agent);
        if (opts.fakeLlm) stats.fallbackPromptRunCount += rows.length;

        const capture = await captureDailyCycleRkeFootprints(api, final, benchmarkRunId, {
          currentDataConfirmed: !opts.fakeLlm,
        });
        if (capture?.capture_status === "blocked") stats.errorCount += 1;
      } catch (err) {
        stats.errorCount += 1;
        onLog(
          `run failed ${modelConfig.model_config_id} ${item.as_of_date}: ${(err as Error).message}`,
        );
      }
    }
  }

  const aggregateStats = aggregatePairedOutputStats(
    benchmarkRunId,
    readPairedOutputRecords(benchmarkRunId),
    stats.fallbackPromptRunCount,
    stats.errorCount,
  );
  const footprintSummary = await api.rkeBenchmarkAgentFootprintSummary({
    benchmark_run_id: benchmarkRunId,
  });
  aggregateStats.currentDataViolationCount = Math.max(
    0,
    footprintSummary.rke_context_hash_count - footprintSummary.current_data_confirmed_count,
  );
  const benchmarkQualitySummary = buildBenchmarkQualitySummary(manifest, aggregateStats);
  const benchmarkEvidenceRefs = buildBenchmarkEvidenceRefs(benchmarkRunId);
  const manualReview = buildManualReview(benchmarkRunId, opts);
  const evidence = await api.rkeBenchmarkFixedEpisodeBenchmarkEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    paired_output_count: aggregateStats.pairedOutputCount,
    model_config_output_counts: aggregateStats.modelConfigOutputCounts,
    benchmark_quality_summary: benchmarkQualitySummary,
    evidence_refs: benchmarkEvidenceRefs,
    manual_review: manualReview,
  });
  const record = await api.rkeBenchmarkRecordDeliveryEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    prompt_source_status: manifest.prompt_preflight.source_status,
    prompt_contract_checks: contractCheck.rows.map(
      (row) => ({ ...row }) as Record<string, unknown>,
    ),
    paired_output_count: aggregateStats.pairedOutputCount,
    model_config_output_counts: aggregateStats.modelConfigOutputCounts,
    benchmark_quality_summary: benchmarkQualitySummary,
    benchmark_evidence_refs: benchmarkEvidenceRefs,
    manual_review: manualReview,
  });
  return { benchmarkRunId, manifest, contractCheck, evidence, record, stats: aggregateStats };
}

export function episodeDateCases(
  manifest: RkeFixedEpisodeManifestResult,
  asOfDates: readonly string[] = [],
): Array<{
  episode_id: string;
  as_of_date: string;
}> {
  const selectedDates = new Set(asOfDates);
  const cases = manifest.episodes.flatMap((episode) =>
    episode.as_of_dates
      .filter((asOfDate) => selectedDates.size === 0 || selectedDates.has(asOfDate))
      .map((asOfDate) => ({
        episode_id: episode.episode_id,
        as_of_date: asOfDate,
      })),
  );
  if (selectedDates.size > 0 && cases.length === 0) {
    throw new Error(
      `no fixed episode cases matched as_of_date=${Array.from(selectedDates).join(",")}`,
    );
  }
  return cases;
}

export function selectModelConfigs(
  manifest: RkeFixedEpisodeManifestResult,
  ids: readonly string[] = [],
): RkeBenchmarkModelConfig[] {
  const wanted = new Set(ids);
  return manifest.model_configs.filter((config) =>
    wanted.size > 0 ? wanted.has(config.model_config_id) : config.required,
  );
}

function makeLlmHandleForModelConfig(
  config: Awaited<ReturnType<BridgeApi["configGet"]>>,
  modelConfig: RkeBenchmarkModelConfig,
  opts: RkeFixedBenchmarkOptions,
  maxTokens: number | undefined,
): LlmHandle {
  if (opts.fakeLlm) return buildFakeLlmHandle();
  if (modelConfig.model_config_id === "baseline_current_config") {
    return createLlmFromConfig(config, {
      tier: "deep",
      ...(opts.llmProvider ? { provider: opts.llmProvider } : {}),
      ...(opts.model ? { model: opts.model } : {}),
      ...(opts.baseUrl ? { baseUrl: opts.baseUrl } : {}),
      ...(maxTokens ? { maxTokens } : {}),
    });
  }
  const slug = modelConfig.model_config_id.toUpperCase().replace(/[^A-Z0-9]+/g, "_");
  const localModel = process.env[`MOSAIC_RKE_BENCHMARK_${slug}_MODEL`] ?? modelConfig.model_family;
  if (!localModel) {
    throw new Error(`model config ${modelConfig.model_config_id} has no model id`);
  }
  const localBaseUrl = process.env[`MOSAIC_RKE_BENCHMARK_${slug}_BASE_URL`];
  return createLlmFromConfig(config, {
    tier: "deep",
    provider: process.env[`MOSAIC_RKE_BENCHMARK_${slug}_PROVIDER`] ?? "vllm",
    model: localModel,
    ...(localBaseUrl ? { baseUrl: localBaseUrl } : {}),
    ...(maxTokens ? { maxTokens } : {}),
  });
}

export function collectPairedOutputRecords(
  benchmarkRunId: string,
  episodeId: string,
  asOfDate: string,
  modelConfigId: string,
  state: DailyCycleStateType,
): PairedOutputRecord[] {
  const rows: PairedOutputRecord[] = [];
  for (const [layer, outputs] of [
    ["macro", state.layer1_outputs],
    ["sector", state.layer2_outputs],
    ["superinvestor", state.layer3_outputs],
    ["decision", state.layer4_outputs],
  ] as const) {
    for (const [agent, output] of Object.entries(outputs ?? {})) {
      if (!output) continue;
      rows.push({
        benchmark_run_id: benchmarkRunId,
        episode_id: episodeId,
        as_of_date: asOfDate,
        model_config_id: modelConfigId,
        agent,
        layer,
        output_sha256: sha256(JSON.stringify(output)),
      });
    }
  }
  return rows;
}

function writePairedOutputRecords(benchmarkRunId: string, rows: PairedOutputRecord[]): void {
  const path = join(fixedBenchmarkPrivateOutputDir(), `${benchmarkRunId}.paired_outputs.jsonl`);
  appendFileSync(path, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`, "utf-8");
}

function readPairedOutputRecords(benchmarkRunId: string): PairedOutputRecord[] {
  const path = join(fixedBenchmarkPrivateOutputDir(), `${benchmarkRunId}.paired_outputs.jsonl`);
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf-8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line) as PairedOutputRecord)
    .filter((row) => row.benchmark_run_id === benchmarkRunId);
}

export function aggregatePairedOutputStats(
  benchmarkRunId: string,
  rows: readonly PairedOutputRecord[],
  fallbackPromptRunCount = 0,
  errorCount = 0,
): BenchmarkRunStats {
  const stats: BenchmarkRunStats = {
    benchmarkRunId,
    pairedOutputCount: 0,
    modelConfigOutputCounts: {},
    coveredEpisodeIds: new Set(),
    coveredAsOfDates: new Set(),
    coveredAgents: new Set(),
    currentDataViolationCount: 0,
    fallbackPromptRunCount,
    errorCount,
  };
  const seen = new Set<string>();
  for (const row of rows) {
    const key = `${row.model_config_id}|${row.episode_id}|${row.as_of_date}|${row.agent}`;
    if (seen.has(key)) continue;
    seen.add(key);
    stats.pairedOutputCount += 1;
    stats.modelConfigOutputCounts[row.model_config_id] =
      (stats.modelConfigOutputCounts[row.model_config_id] ?? 0) + 1;
    stats.coveredEpisodeIds.add(row.episode_id);
    stats.coveredAsOfDates.add(row.as_of_date);
    stats.coveredAgents.add(row.agent);
  }
  return stats;
}

export function completedEpisodeDateModelRuns(
  rows: readonly PairedOutputRecord[],
  agentCount: number,
): Set<string> {
  const agentsByRun = new Map<string, Set<string>>();
  for (const row of rows) {
    const key = `${row.model_config_id}|${row.episode_id}|${row.as_of_date}`;
    const agents = agentsByRun.get(key) ?? new Set<string>();
    agents.add(row.agent);
    agentsByRun.set(key, agents);
  }
  return new Set(
    Array.from(agentsByRun.entries())
      .filter(([, agents]) => agents.size >= agentCount)
      .map(([key]) => key),
  );
}

export function fixedBenchmarkPrivateOutputDir(): string {
  return join(findRepoRoot(), PRIVATE_OUTPUT_DIR);
}

export function buildBenchmarkEvidenceRefs(benchmarkRunId: string): Record<string, string> {
  return {
    benchmark_run_id: benchmarkRunId,
    episode_manifest_ref: `rke-fixed:${benchmarkRunId}:episode-manifest`,
    as_of_date_manifest_ref: `rke-fixed:${benchmarkRunId}:as-of-date-manifest`,
    benchmark_runner_ref: `rke-fixed:${benchmarkRunId}:runner`,
    prompt_contract_check_manifest_ref: `rke-fixed:${benchmarkRunId}:prompt-contracts`,
    model_config_manifest_ref: `rke-fixed:${benchmarkRunId}:model-config-manifest`,
    paired_output_manifest_ref: `rke-fixed:${benchmarkRunId}:paired-output-manifest`,
    output_schema_validation_report_ref: `rke-fixed:${benchmarkRunId}:schema-validation`,
    deterministic_score_table_ref: `rke-fixed:${benchmarkRunId}:deterministic-score-table`,
    investment_outcome_table_ref: `rke-fixed:${benchmarkRunId}:investment-outcome-table`,
  };
}

export function buildBenchmarkQualitySummary(
  manifest: RkeFixedEpisodeManifestResult,
  stats: BenchmarkRunStats,
): Record<string, unknown> {
  return {
    benchmark_run_id: stats.benchmarkRunId,
    quality_gate_ref: `rke-fixed:${stats.benchmarkRunId}:quality-gate`,
    schema_failure_gate_passed: stats.errorCount === 0,
    severe_safety_violation_count: 0,
    current_data_confirmation_violation_count: stats.currentDataViolationCount,
    fallback_prompt_run_count: stats.fallbackPromptRunCount,
    covered_episode_count: stats.coveredEpisodeIds.size,
    covered_as_of_date_count: stats.coveredAsOfDates.size,
    covered_agent_count: Math.min(stats.coveredAgents.size, manifest.agent_count),
  };
}

function buildManualReview(
  benchmarkRunId: string,
  opts: RkeFixedBenchmarkOptions,
): Record<string, unknown> {
  return {
    benchmark_run_id: benchmarkRunId,
    decision: opts.manualReviewApproved ? "approved" : "not_reviewed",
    reviewer_timestamp: opts.reviewerTimestamp ?? "",
    reviewer_independence_confirmed: opts.reviewerIndependenceConfirmed === true,
  };
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

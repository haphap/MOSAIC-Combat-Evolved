import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { Command } from "commander";
import pc from "picocolors";
import { buildDailyCycleRkeFootprintRows } from "../../agents/rke_footprints.js";
import type { DailyCycleStateType } from "../../agents/state.js";
import { BridgeClient, RpcError, BridgeApi as RuntimeBridgeApi } from "../../bridge/index.js";
import { findRepoRoot } from "../../bridge/python.js";
import type {
  BridgeApi,
  PromptContractCheckRow,
  RkeAgentClaimFootprintInput,
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

type PairedOutputStatus =
  | "ready"
  | "blocked_preflight"
  | "tool_failed"
  | "timeout"
  | "schema_invalid"
  | "empty_output"
  | "privacy_blocked";

export interface PromptPin {
  lang: "zh" | "en";
  prompt_repo_id: string;
  prompt_repo_revision: string;
  prompt_file_path: string;
  prompt_sha256: string;
  prompt_contract_check_ref: string;
}

export interface RkeContextMetadata {
  rke_context_hashes: string[];
  ranking_policy_ids: string[];
  retrieval_ranks: number[];
  priority_buckets: string[];
  truncated_item_count_total: number;
  current_data_confirmed: boolean;
}

interface PairedOutputRecord {
  benchmark_run_id: string;
  episode_id: string;
  as_of_date: string;
  model_config_id: string;
  agent: string;
  layer: string;
  status?: PairedOutputStatus;
  blocker_codes?: string[];
  prompt_pins?: PromptPin[];
  rke_context?: RkeContextMetadata;
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

interface AgentBenchmarkMetric {
  agent: string;
  layer: string;
  status: "done" | "timeout" | "error" | "started";
  runCount: number;
  elapsedMs: number;
  analysisLlmInvocations: number;
  toolCalls: number;
  toolCacheHits: number;
  toolExecutions: number;
  toolCallCountsByName: Record<string, number>;
  toolCallFingerprints: Record<string, number>;
  toolFailureCount: number;
  outputSource: "structured" | "fallback" | "unknown";
  promptTokens: number;
  completionTokens: number;
  llmElapsedMs: number;
}

interface BenchmarkMetricRecord {
  benchmark_run_id: string;
  episode_id: string;
  as_of_date: string;
  model_config_id: string;
  llm_provider: string;
  llm_model: string;
  llm_base_url: string;
  expected_agent_count: number;
  output_agent_count: number;
  content_generation_success_rate: number;
  agent_done_count: number;
  structured_output_count: number;
  fallback_output_count: number;
  agent_elapsed_ms_total: number;
  tool_calls_total: number;
  tool_cache_hits_total: number;
  tool_executions_total: number;
  tool_failure_count: number;
  tool_call_counts_by_name: Record<string, number>;
  tool_call_fingerprints: Record<string, number>;
  analysis_llm_invocations_total: number;
  observed_prompt_tokens_total: number;
  observed_completion_tokens_total: number;
  observed_llm_elapsed_ms_total: number;
  observed_completion_tokens_per_second: number | null;
  agents: AgentBenchmarkMetric[];
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
  const promptPinsByAgent = buildPromptPinsByAgent(contractCheck.rows, config.output_language);
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
  let activeAgentMetrics: Map<string, AgentBenchmarkMetric> | null = null;

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
      onLog: (msg) => {
        if (activeAgentMetrics) updateAgentMetricsFromLog(activeAgentMetrics, msg);
        onLog(msg);
      },
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
        activeAgentMetrics = new Map();
        const initialState = makeInitialState(cohort, item.as_of_date);
        initialState.trace_id = `${benchmarkRunId}:${modelConfig.model_config_id}:${item.as_of_date}`;
        const final = (await graph.invoke(initialState)) as DailyCycleStateType;
        const footprintRows = await buildDailyCycleRkeFootprintRows(api, final, {
          currentDataConfirmed: !opts.fakeLlm,
          episodeId: item.episode_id,
          modelConfigId: modelConfig.model_config_id,
        });
        const rows = collectPairedOutputRecords(
          benchmarkRunId,
          item.episode_id,
          item.as_of_date,
          modelConfig.model_config_id,
          final,
          promptPinsByAgent,
          buildRkeContextMetadataByAgent(footprintRows),
        );
        writePairedOutputRecords(benchmarkRunId, rows);
        writeBenchmarkMetricRecord(
          benchmarkRunId,
          buildBenchmarkMetricRecord(
            benchmarkRunId,
            item.episode_id,
            item.as_of_date,
            modelConfig.model_config_id,
            llmHandle,
            manifest.agent_count,
            rows,
            activeAgentMetrics,
          ),
        );
        stats.pairedOutputCount += rows.length;
        stats.modelConfigOutputCounts[modelConfig.model_config_id] =
          (stats.modelConfigOutputCounts[modelConfig.model_config_id] ?? 0) + rows.length;
        stats.coveredEpisodeIds.add(item.episode_id);
        stats.coveredAsOfDates.add(item.as_of_date);
        for (const row of rows) stats.coveredAgents.add(row.agent);
        if (opts.fakeLlm) stats.fallbackPromptRunCount += rows.length;

        const capture =
          footprintRows.length > 0
            ? await api.rkeBenchmarkCaptureAgentClaimFootprints({
                benchmark_run_id: benchmarkRunId,
                rows: footprintRows,
              })
            : null;
        if (capture?.capture_status === "blocked") stats.errorCount += 1;
      } catch (err) {
        stats.errorCount += 1;
        const rows = collectBlockedPairedOutputRecords(
          benchmarkRunId,
          item.episode_id,
          item.as_of_date,
          modelConfig.model_config_id,
          manifest,
          "tool_failed",
          ["graph_run_failed"],
          promptPinsByAgent,
        );
        writePairedOutputRecords(benchmarkRunId, rows);
        stats.pairedOutputCount += rows.length;
        stats.modelConfigOutputCounts[modelConfig.model_config_id] =
          (stats.modelConfigOutputCounts[modelConfig.model_config_id] ?? 0) + rows.length;
        stats.coveredEpisodeIds.add(item.episode_id);
        stats.coveredAsOfDates.add(item.as_of_date);
        for (const row of rows) stats.coveredAgents.add(row.agent);
        onLog(
          `run failed ${modelConfig.model_config_id} ${item.as_of_date}: ${(err as Error).message}`,
        );
      } finally {
        activeAgentMetrics = null;
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
  promptPinsByAgent?: ReadonlyMap<string, readonly PromptPin[]>,
  rkeContextByAgent?: ReadonlyMap<string, RkeContextMetadata>,
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
      const promptPins = promptPinsByAgent?.get(agent) ?? [];
      const promptPinMissing = promptPinsByAgent !== undefined && promptPins.length === 0;
      rows.push({
        benchmark_run_id: benchmarkRunId,
        episode_id: episodeId,
        as_of_date: asOfDate,
        model_config_id: modelConfigId,
        agent,
        layer,
        status: promptPinMissing ? "blocked_preflight" : "ready",
        blocker_codes: promptPinMissing ? ["prompt_pin_missing"] : [],
        prompt_pins: [...promptPins],
        rke_context: rkeContextByAgent?.get(agent) ?? emptyRkeContextMetadata(),
        output_sha256: sha256(JSON.stringify(output)),
      });
    }
  }
  return rows;
}

export function buildRkeContextMetadataByAgent(
  rows: readonly RkeAgentClaimFootprintInput[],
): Map<string, RkeContextMetadata> {
  const byAgent = new Map<string, RkeContextMetadata>();
  for (const row of rows) {
    if (!row.rke_context_hash) continue;
    const current = byAgent.get(row.agent) ?? emptyRkeContextMetadata();
    const firstContext = current.rke_context_hashes.length === 0;
    current.rke_context_hashes.push(row.rke_context_hash);
    if (row.ranking_policy_id) current.ranking_policy_ids.push(row.ranking_policy_id);
    if (row.retrieval_rank !== undefined) current.retrieval_ranks.push(row.retrieval_rank);
    if (row.priority_bucket) current.priority_buckets.push(row.priority_bucket);
    current.truncated_item_count_total += row.truncated_item_count ?? 0;
    current.current_data_confirmed = firstContext
      ? row.current_data_confirmed === true
      : current.current_data_confirmed && row.current_data_confirmed === true;
    byAgent.set(row.agent, current);
  }
  return byAgent;
}

function emptyRkeContextMetadata(): RkeContextMetadata {
  return {
    rke_context_hashes: [],
    ranking_policy_ids: [],
    retrieval_ranks: [],
    priority_buckets: [],
    truncated_item_count_total: 0,
    current_data_confirmed: false,
  };
}

export function collectBlockedPairedOutputRecords(
  benchmarkRunId: string,
  episodeId: string,
  asOfDate: string,
  modelConfigId: string,
  manifest: RkeFixedEpisodeManifestResult,
  status: Exclude<PairedOutputStatus, "ready">,
  blockerCodes: readonly string[],
  promptPinsByAgent?: ReadonlyMap<string, readonly PromptPin[]>,
): PairedOutputRecord[] {
  const rows: PairedOutputRecord[] = [];
  for (const [layer, agents] of Object.entries(manifest.agents_by_layer)) {
    for (const agent of agents) {
      const promptPins = promptPinsByAgent?.get(agent) ?? [];
      const missingPromptPin = promptPinsByAgent !== undefined && promptPins.length === 0;
      rows.push({
        benchmark_run_id: benchmarkRunId,
        episode_id: episodeId,
        as_of_date: asOfDate,
        model_config_id: modelConfigId,
        agent,
        layer,
        status,
        blocker_codes: missingPromptPin
          ? [...blockerCodes, "prompt_pin_missing"]
          : [...blockerCodes],
        prompt_pins: [...promptPins],
        output_sha256: "",
      });
    }
  }
  return rows;
}

export function buildPromptPinsByAgent(
  rows: readonly PromptContractCheckRow[],
  outputLanguage: string,
): Map<string, PromptPin[]> {
  const wantedLangs = promptLangsForOutput(outputLanguage);
  const pinsByAgent = new Map<string, PromptPin[]>();
  for (const row of rows) {
    if (!row.ready || !wantedLangs.has(row.lang)) continue;
    const pins = pinsByAgent.get(row.agent) ?? [];
    pins.push({
      lang: row.lang,
      prompt_repo_id: row.prompt_repo_id,
      prompt_repo_revision: row.prompt_repo_revision,
      prompt_file_path: row.prompt_file_path,
      prompt_sha256: row.prompt_sha256,
      prompt_contract_check_ref: row.prompt_contract_check_ref,
    });
    pinsByAgent.set(row.agent, pins);
  }
  return pinsByAgent;
}

function promptLangsForOutput(outputLanguage: string): ReadonlySet<"zh" | "en"> {
  const raw = outputLanguage.toLowerCase().trim();
  if (raw === "english" || raw === "en") return new Set(["en"]);
  if (raw === "bilingual") return new Set(["zh", "en"]);
  return new Set(["zh"]);
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

function writeBenchmarkMetricRecord(benchmarkRunId: string, record: BenchmarkMetricRecord): void {
  const path = join(fixedBenchmarkPrivateOutputDir(), `${benchmarkRunId}.metrics.jsonl`);
  appendFileSync(path, `${JSON.stringify(record)}\n`, "utf-8");
}

export function updateAgentMetricsFromLog(
  metrics: Map<string, AgentBenchmarkMetric>,
  message: string,
): void {
  const event = message.match(
    /^\[agent:(start|phase|done|timeout|error)\]\s+(L\d)\s+(\S+)\s*(.*)$/,
  );
  if (!event) return;
  const [, kind, layer, agent, rest = ""] = event;
  if (!kind || !layer || !agent) return;
  const key = `${layer}:${agent}`;
  const metric = metrics.get(key) ?? emptyAgentMetric(agent, layer);
  metrics.set(key, metric);

  if (kind === "phase") {
    recordToolNames(metric, rest);
    recordToolFingerprints(metric, rest);
    if (/Tool '[^']+' raised:/.test(rest)) metric.toolFailureCount += 1;
    return;
  }

  if (kind === "start") {
    metric.status = "started";
    metric.runCount += 1;
    return;
  }

  metric.status = kind === "done" ? "done" : kind === "timeout" ? "timeout" : "error";
  const fields = parseAgentFields(rest);
  metric.elapsedMs += parseDurationMs(fields.elapsed ?? "") ?? 0;
  metric.analysisLlmInvocations += parseInteger(fields.analysis_llm) ?? 0;
  metric.toolCalls += parseInteger(fields.tools) ?? 0;
  metric.toolCacheHits += parseInteger(fields.tool_cache_hits) ?? 0;
  metric.toolExecutions += parseInteger(fields.tool_executions) ?? 0;
  metric.outputSource =
    fields.source === "structured" || fields.source === "fallback"
      ? fields.source
      : metric.outputSource;
  metric.promptTokens += parseInteger(fields.prompt_tokens) ?? 0;
  metric.completionTokens += parseInteger(fields.completion_tokens) ?? 0;
  metric.llmElapsedMs += parseInteger(fields.llm_elapsed_ms) ?? 0;
}

export function buildBenchmarkMetricRecord(
  benchmarkRunId: string,
  episodeId: string,
  asOfDate: string,
  modelConfigId: string,
  llmHandle: LlmHandle,
  expectedAgentCount: number,
  rows: readonly PairedOutputRecord[],
  metrics: ReadonlyMap<string, AgentBenchmarkMetric>,
): BenchmarkMetricRecord {
  const agents = Array.from(metrics.values()).sort((a, b) =>
    `${a.layer}:${a.agent}`.localeCompare(`${b.layer}:${b.agent}`),
  );
  const toolCallCountsByName: Record<string, number> = {};
  const toolCallFingerprints: Record<string, number> = {};
  for (const agent of agents) {
    for (const [name, count] of Object.entries(agent.toolCallCountsByName)) {
      toolCallCountsByName[name] = (toolCallCountsByName[name] ?? 0) + count;
    }
    for (const [fingerprint, count] of Object.entries(agent.toolCallFingerprints)) {
      toolCallFingerprints[fingerprint] = (toolCallFingerprints[fingerprint] ?? 0) + count;
    }
  }
  const observedCompletionTokens = sum(agents, (agent) => agent.completionTokens);
  const observedLlmElapsedMs = sum(agents, (agent) => agent.llmElapsedMs);
  const doneCount = agents.filter((agent) => agent.status === "done").length;
  return {
    benchmark_run_id: benchmarkRunId,
    episode_id: episodeId,
    as_of_date: asOfDate,
    model_config_id: modelConfigId,
    llm_provider: llmHandle.provider,
    llm_model: llmHandle.model,
    llm_base_url: llmHandle.baseUrl ?? "",
    expected_agent_count: expectedAgentCount,
    output_agent_count: rows.length,
    content_generation_success_rate:
      expectedAgentCount > 0 ? round(doneCount / expectedAgentCount, 4) : 0,
    agent_done_count: doneCount,
    structured_output_count: agents.filter((agent) => agent.outputSource === "structured").length,
    fallback_output_count: agents.filter((agent) => agent.outputSource === "fallback").length,
    agent_elapsed_ms_total: sum(agents, (agent) => agent.elapsedMs),
    tool_calls_total: sum(agents, (agent) => agent.toolCalls),
    tool_cache_hits_total: sum(agents, (agent) => agent.toolCacheHits),
    tool_executions_total: sum(agents, (agent) => agent.toolExecutions),
    tool_failure_count: sum(agents, (agent) => agent.toolFailureCount),
    tool_call_counts_by_name: toolCallCountsByName,
    tool_call_fingerprints: toolCallFingerprints,
    analysis_llm_invocations_total: sum(agents, (agent) => agent.analysisLlmInvocations),
    observed_prompt_tokens_total: sum(agents, (agent) => agent.promptTokens),
    observed_completion_tokens_total: observedCompletionTokens,
    observed_llm_elapsed_ms_total: observedLlmElapsedMs,
    observed_completion_tokens_per_second:
      observedCompletionTokens > 0 && observedLlmElapsedMs > 0
        ? round(observedCompletionTokens / (observedLlmElapsedMs / 1000), 4)
        : null,
    agents,
  };
}

function emptyAgentMetric(agent: string, layer: string): AgentBenchmarkMetric {
  return {
    agent,
    layer,
    status: "started",
    runCount: 0,
    elapsedMs: 0,
    analysisLlmInvocations: 0,
    toolCalls: 0,
    toolCacheHits: 0,
    toolExecutions: 0,
    toolCallCountsByName: {},
    toolCallFingerprints: {},
    toolFailureCount: 0,
    outputSource: "unknown",
    promptTokens: 0,
    completionTokens: 0,
    llmElapsedMs: 0,
  };
}

function recordToolNames(metric: AgentBenchmarkMetric, text: string): void {
  const match = text.match(/\btools=\d+\s+names=([^\s]+)/);
  const names = match?.[1];
  if (!names) return;
  for (const name of names
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)) {
    metric.toolCallCountsByName[name] = (metric.toolCallCountsByName[name] ?? 0) + 1;
  }
}

function recordToolFingerprints(metric: AgentBenchmarkMetric, text: string): void {
  const match = text.match(/\bfingerprints=([^\s]+)/);
  const fingerprints = match?.[1];
  if (!fingerprints) return;
  for (const fingerprint of fingerprints
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)) {
    metric.toolCallFingerprints[fingerprint] = (metric.toolCallFingerprints[fingerprint] ?? 0) + 1;
  }
}

function parseAgentFields(text: string): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const match of text.matchAll(/\b([a-z_]+)=([^\s]+)/g)) {
    const key = match[1];
    const value = match[2];
    if (key && value !== undefined) fields[key] = value;
  }
  return fields;
}

function parseDurationMs(value: string): number | undefined {
  if (!value) return undefined;
  const ms = value.match(/^(\d+(?:\.\d+)?)ms$/);
  if (ms) return Math.round(Number(ms[1]));
  const seconds = value.match(/^(\d+(?:\.\d+)?)s$/);
  if (seconds) return Math.round(Number(seconds[1]) * 1000);
  const minutes = value.match(/^(\d+)m(\d{2})s$/);
  if (minutes) return (Number(minutes[1]) * 60 + Number(minutes[2])) * 1000;
  return undefined;
}

function parseInteger(value: string | undefined): number | undefined {
  if (value === undefined) return undefined;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function sum<T>(items: readonly T[], pick: (item: T) => number): number {
  return items.reduce((total, item) => total + pick(item), 0);
}

function round(value: number, digits: number): number {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
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
  const byKey = new Map<string, PairedOutputRecord>();
  for (const row of rows) {
    const key = `${row.model_config_id}|${row.episode_id}|${row.as_of_date}|${row.agent}`;
    const previous = byKey.get(key);
    if (previous && isCompletedPairedOutputRow(previous)) continue;
    if (previous && !isCompletedPairedOutputRow(row)) continue;
    byKey.set(key, row);
  }
  for (const row of byKey.values()) {
    if (!isCompletedPairedOutputRow(row)) stats.errorCount += 1;
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
    if (!isCompletedPairedOutputRow(row)) continue;
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

function isCompletedPairedOutputRow(row: PairedOutputRecord): boolean {
  return row.status === "ready" || (row.status === undefined && !!row.output_sha256);
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
    benchmark_metrics_ref: `rke-fixed:${benchmarkRunId}:metrics`,
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

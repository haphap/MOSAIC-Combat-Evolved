import { createHash } from "node:crypto";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { Command } from "commander";
import pc from "picocolors";
import { buildDailyCycleRkeFootprintRows } from "../../agents/rke_footprints.js";
import type { DailyCycleStateType } from "../../agents/state.js";
import { BridgeClient, RpcError, BridgeApi as RuntimeBridgeApi } from "../../bridge/index.js";
import { findRepoRoot } from "../../bridge/python.js";
import type { BridgeApi, RkeDeliveryReadinessResult } from "../../bridge/types.js";
import { buildDailyCycleGraph } from "../../graph/daily_cycle.js";
import { createLlmFromConfig, type LlmHandle } from "../../llm/factory.js";
import { redactSensitiveText } from "../../security/redaction.js";
import { buildFakeLlmHandle, makeInitialState } from "../_backtest_helpers.js";
import { applyPromptSourceOverrides } from "../prompt-source.js";
import {
  buildPromptPinsByAgent,
  buildRkeContextMetadataByAgent,
  type PromptPin,
  type RkeContextMetadata,
} from "./rke-fixed-benchmark.js";

const PRIVATE_OUTPUT_DIR = ".mosaic/rke/all_agent_evolution/shadow_replay";
const REPLAY_PREREQUISITE_CONDITION_IDS = [
  "all_agent_prompt_provenance",
  "runtime_ranked_context_consumption",
  "fixed_episode_benchmark",
  "agent_profile_evolution",
  "darwinian_autoresearch_inputs",
  "darwinian_autoresearch_consumption",
  "prompt_mutation_release",
  "patch_activation",
  "rollback_evidence",
] as const;

interface RkeShadowReplayOptions {
  benchmarkRunId?: string;
  replayRunId?: string;
  cohort?: string;
  asOfDate?: string[];
  fakeLlm?: boolean;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
  vetoThreshold?: string;
  promptsRepo?: string;
  promptsRoot?: string;
  maxRuns?: string;
}

interface ReplayOutputRecord {
  benchmark_run_id: string;
  replay_run_id: string;
  as_of_date: string;
  agent: string;
  layer: string;
  prompt_pins: PromptPin[];
  rke_context?: RkeContextMetadata;
  output_sha256: string;
}

interface ReplayStats {
  replayOutputCount: number;
  replayFootprintCount: number;
  privacyScanPassed: boolean;
  currentDataConfirmed: boolean;
}

export function registerRkeShadowReplay(program: Command): void {
  program
    .command("rke-shadow-replay")
    .description("Run the RKE E7 shadow replay producer and record no-body replay evidence refs.")
    .requiredOption("--benchmark-run-id <id>", "Benchmark run id")
    .option("--replay-run-id <id>", "Replay run id (default rke-shadow-<timestamp>)")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--as-of-date <YYYY-MM-DD>", "Replay date; repeatable", collect, [])
    .option("--fake-llm", "Use fake LLM for smoke runs")
    .option("--llm-provider <name>", "Model provider override")
    .option("--model <name>", "Model override")
    .option("--base-url <url>", "Model base URL override")
    .option("--veto-threshold <num>", "Deprecated compatibility option; ignored by canonical L4")
    .option("--prompts-repo <path>", "Use a private prompt git repo for this run")
    .option("--prompts-root <path>", "Override prompts root directory")
    .option("--max-runs <n>", "Cap replay dates for smoke/debug")
    .action(async (opts: RkeShadowReplayOptions) => {
      const client = new BridgeClient();
      const api = new RuntimeBridgeApi(client);
      try {
        applyPromptSourceOverrides(opts);
        await client.start();
        const result = await runRkeShadowReplay(api, opts, (msg) =>
          console.log(pc.dim(redactSensitiveText(msg))),
        );
        console.log(
          pc.bold(
            `\nrke-shadow-replay recorded outputs=${result.stats.replayOutputCount} ` +
              `footprints=${result.stats.replayFootprintCount}`,
          ),
        );
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

function collect(value: string, previous: string[]): string[] {
  previous.push(value);
  return previous;
}

export async function runRkeShadowReplay(
  api: BridgeApi,
  opts: RkeShadowReplayOptions,
  onLog: (msg: string) => void = () => undefined,
) {
  const benchmarkRunId = required(opts.benchmarkRunId, "benchmarkRunId");
  const replayRunId = opts.replayRunId ?? `rke-shadow-${Date.now()}`;
  const cohort = opts.cohort ?? "cohort_default";
  const asOfDates = opts.asOfDate ?? [];
  if (asOfDates.length === 0) throw new Error("at least one --as-of-date is required");

  const prerequisiteReadiness = await api.rkeBenchmarkDeliveryReadiness({
    benchmark_run_id: benchmarkRunId,
    cohort,
  });
  assertReplayPrerequisitesReady(prerequisiteReadiness);

  const contractCheck = await api.promptsContractCheck({
    cohort,
    benchmark_run_id: benchmarkRunId,
  });
  if (!contractCheck.ready) {
    throw new Error(`prompt contract check blocked: ${contractCheck.blocked_reasons.join(", ")}`);
  }

  const config = await api.configGet();
  const promptPinsByAgent = buildPromptPinsByAgent(contractCheck.rows, config.output_language);
  const llmHandle = makeReplayLlmHandle(config, opts);
  const graph = buildDailyCycleGraph({
    llmHandle,
    api,
    config,
    vetoThreshold: opts.vetoThreshold ? Number(opts.vetoThreshold) : 0.5,
    ...(opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {}),
    onLog,
  });
  const maxRuns = opts.maxRuns ? Number.parseInt(opts.maxRuns, 10) : undefined;
  const stats: ReplayStats = {
    replayOutputCount: 0,
    replayFootprintCount: 0,
    privacyScanPassed: true,
    currentDataConfirmed: false,
  };

  mkdirSync(join(findRepoRoot(), PRIVATE_OUTPUT_DIR), { recursive: true });
  for (const asOfDate of asOfDates.slice(0, maxRuns)) {
    const initialState = makeInitialState(cohort, asOfDate);
    initialState.trace_id = `${benchmarkRunId}:${replayRunId}:${asOfDate}`;
    const final = (await graph.invoke(initialState)) as DailyCycleStateType;
    const footprintRows = await buildDailyCycleRkeFootprintRows(api, final, {
      currentDataConfirmed: !opts.fakeLlm,
      replayRunId,
    });
    const rows = collectReplayOutputRecords(
      benchmarkRunId,
      replayRunId,
      asOfDate,
      final,
      promptPinsByAgent,
      buildRkeContextMetadataByAgent(footprintRows),
    );
    writeReplayOutputRecords(benchmarkRunId, replayRunId, rows);
    stats.replayOutputCount += rows.length;
    const capture =
      footprintRows.length > 0
        ? await api.rkeBenchmarkCaptureAgentClaimFootprints({
            benchmark_run_id: benchmarkRunId,
            rows: footprintRows,
          })
        : null;
    stats.replayFootprintCount += capture?.captured_count ?? 0;
    if (capture?.capture_status === "blocked") stats.privacyScanPassed = false;
  }

  const summary = await api.rkeBenchmarkAgentFootprintSummary({ benchmark_run_id: benchmarkRunId });
  stats.privacyScanPassed =
    stats.privacyScanPassed && summary.privacy_scan.forbidden_field_violation_count === 0;
  stats.currentDataConfirmed =
    summary.rke_context_hash_count > 0 &&
    summary.current_data_confirmed_count >= summary.rke_context_hash_count;
  const replayEvidence = buildReplayEvidence(benchmarkRunId, replayRunId, stats);
  const shadowReadiness = await api.rkeBenchmarkShadowReplayReadiness(
    buildShadowReplayReadinessParams(benchmarkRunId, cohort, replayEvidence),
  );
  const record = await api.rkeBenchmarkRecordDeliveryEvidence({
    benchmark_run_id: benchmarkRunId,
    cohort,
    replay_evidence: replayEvidence,
  });
  writeReplayMetricArtifact(benchmarkRunId, replayRunId, stats);
  return { benchmarkRunId, replayRunId, replayEvidence, shadowReadiness, record, stats };
}

export function assertReplayPrerequisitesReady(readiness: RkeDeliveryReadinessResult): void {
  const conditions = new Map(readiness.conditions.map((row) => [row.condition_id, row]));
  const blockers = REPLAY_PREREQUISITE_CONDITION_IDS.flatMap((conditionId) => {
    const condition = conditions.get(conditionId);
    if (!condition) return [`${conditionId}:condition_missing`];
    if (condition.ready) return [];
    const reasons =
      condition.blocked_reasons.length > 0 ? condition.blocked_reasons : [condition.status];
    return reasons.map((reason) => `${conditionId}:${reason}`);
  });
  if (blockers.length > 0) {
    throw new Error(`shadow replay prerequisites blocked: ${blockers.join(" | ")}`);
  }
}

export function collectReplayOutputRecords(
  benchmarkRunId: string,
  replayRunId: string,
  asOfDate: string,
  state: DailyCycleStateType,
  promptPinsByAgent?: ReadonlyMap<string, readonly PromptPin[]>,
  rkeContextByAgent?: ReadonlyMap<string, RkeContextMetadata>,
): ReplayOutputRecord[] {
  const rows: ReplayOutputRecord[] = [];
  for (const [layer, outputs] of [
    ["macro", state.layer1_outputs],
    ["sector", state.layer2_outputs],
    ["superinvestor", state.layer3_outputs],
    ["decision", state.layer4_outputs],
  ] as const) {
    for (const [agent, output] of Object.entries(outputs ?? {})) {
      if (!output) continue;
      const rkeContext = rkeContextByAgent?.get(agent);
      rows.push({
        benchmark_run_id: benchmarkRunId,
        replay_run_id: replayRunId,
        as_of_date: asOfDate,
        agent,
        layer,
        prompt_pins: [...(promptPinsByAgent?.get(agent) ?? [])],
        ...(rkeContext ? { rke_context: rkeContext } : {}),
        output_sha256: sha256(JSON.stringify(output)),
      });
    }
  }
  return rows;
}

export function buildReplayEvidence(
  benchmarkRunId: string,
  replayRunId: string,
  stats: ReplayStats,
): Record<string, unknown> {
  return {
    benchmark_run_id: benchmarkRunId,
    replay_run_id: replayRunId,
    replay_run_ref: `rke-shadow:${benchmarkRunId}:${replayRunId}:run`,
    replay_output_manifest_ref: `rke-shadow:${benchmarkRunId}:${replayRunId}:outputs`,
    runtime_context_consumption_ref: `rke-shadow:${benchmarkRunId}:${replayRunId}:contexts`,
    replay_footprint_ref: `rke-shadow:${benchmarkRunId}:${replayRunId}:footprints`,
    downstream_outcome_metrics_ref: `rke-shadow:${benchmarkRunId}:${replayRunId}:runtime-metrics`,
    replay_output_count: stats.replayOutputCount,
    replay_footprint_count: stats.replayFootprintCount,
    privacy_scan_passed: stats.privacyScanPassed,
    current_data_confirmed: stats.currentDataConfirmed,
  };
}

export function buildShadowReplayReadinessParams(
  benchmarkRunId: string,
  cohort: string,
  replayEvidence: Record<string, unknown>,
): Parameters<BridgeApi["rkeBenchmarkShadowReplayReadiness"]>[0] {
  return {
    benchmark_run_id: benchmarkRunId,
    cohort,
    replay_evidence: replayEvidence,
  };
}

function makeReplayLlmHandle(
  config: Awaited<ReturnType<BridgeApi["configGet"]>>,
  opts: RkeShadowReplayOptions,
): LlmHandle {
  if (opts.fakeLlm) return buildFakeLlmHandle();
  return createLlmFromConfig(config, {
    tier: "deep",
    ...(opts.llmProvider ? { provider: opts.llmProvider } : {}),
    ...(opts.model ? { model: opts.model } : {}),
    ...(opts.baseUrl ? { baseUrl: opts.baseUrl } : {}),
  });
}

function writeReplayOutputRecords(
  benchmarkRunId: string,
  replayRunId: string,
  rows: readonly ReplayOutputRecord[],
): void {
  if (rows.length === 0) return;
  const path = join(
    findRepoRoot(),
    PRIVATE_OUTPUT_DIR,
    `${benchmarkRunId}.${replayRunId}.outputs.jsonl`,
  );
  appendFileSync(path, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`, "utf-8");
}

function writeReplayMetricArtifact(
  benchmarkRunId: string,
  replayRunId: string,
  stats: ReplayStats,
): void {
  const path = join(
    findRepoRoot(),
    PRIVATE_OUTPUT_DIR,
    `${benchmarkRunId}.${replayRunId}.metrics.json`,
  );
  writeFileSync(
    path,
    JSON.stringify({ benchmark_run_id: benchmarkRunId, replay_run_id: replayRunId, stats }),
    "utf-8",
  );
}

function required(value: string | undefined, name: string): string {
  if (!value?.trim()) throw new Error(`${name} is required`);
  return value.trim();
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

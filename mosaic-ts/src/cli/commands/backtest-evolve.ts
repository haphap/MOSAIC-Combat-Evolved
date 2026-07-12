import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, relative, resolve } from "node:path";
import type { Command } from "commander";
import pc from "picocolors";
import { AGENTS_BY_LAYER, type Layer } from "../../agents/prompts/cohorts.js";
import type { DailyCycleStateType } from "../../agents/state.js";
import type { PreviousTargetState } from "../../agents/types.js";
import { runAutoresearchCycle } from "../../autoresearch/orchestrator.js";
import {
  type ArmCheckpoint,
  type ArmEvaluation,
  addLlmUsage,
  benjaminiHochberg,
  type CandidateStatus,
  candidateWindow,
  type DailyJournal,
  DEFAULT_EVOLUTION_POLICY,
  EMPTY_LLM_USAGE,
  EVOLUTION_CHECKPOINT_SCHEMA,
  type EvolutionCandidate,
  type EvolutionCheckpoint,
  evaluationReasonCodes,
  type LlmUsage,
  loadCheckpoint,
  pairedBlockBootstrap,
  pendingLayer,
  phaseForDate,
  selectLayerAgent,
  sha256Json,
  shouldTriggerEvolution,
  writeJsonAtomic,
} from "../../backtest/evolution.js";
import type { BacktestActionInput, MosaicConfig } from "../../bridge/index.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { buildDailyCycleGraph } from "../../graph/daily_cycle.js";
import { createLlmFromConfig, type LlmHandle } from "../../llm/factory.js";
import { serializeLlmHandle } from "../../runtime/serial_llm.js";
import {
  launchQwen35bPreset,
  preflightQwen35bPreset,
  QWEN_35B_NVFP4_PRESET,
  QWEN_35B_SERVED_MODEL,
  resolveQwen35bPreset,
  type SndrPresetResolution,
  verifyQwen35bRuntimeImage,
  waitForQwen35bService,
} from "../../runtime/sndr.js";
import { redactSensitiveText } from "../../security/redaction.js";
import {
  applyBacktestPortfolioActionsToPositions,
  buildFakeLlmHandle,
  carryPreviousTargetState,
  makeInitialState,
} from "../_backtest_helpers.js";

const DEFAULT_COHORT = "history_walkforward_2009";
const LAYER_ORDER: ReadonlyArray<Layer> = ["macro", "sector", "superinvestor", "decision"];

interface BacktestEvolveOptions {
  start: string;
  end: string;
  runDir: string;
  promptBaselineCommit: string;
  cohort?: string;
  fakeLlm?: boolean;
  launchModel?: boolean;
  resume?: boolean;
  dryRun?: boolean;
  maxDays?: string;
  logEvery?: string;
  initialCash?: string;
  benchmark?: string;
}

interface EvolutionManifest {
  schema_version: "mosaic.backtest_evolution_manifest.v1";
  run_id: string;
  created_at: string;
  start_date: string;
  end_date: string;
  cohort: string;
  code_commit: string;
  prompt_repo_id: "private";
  prompt_baseline_commit: string;
  prompt_baseline_sha256: string;
  qlib_data: QlibDataFingerprint;
  model: {
    provider: "vllm" | "fake";
    served_model: string;
    preset: string;
    resolution: SndrPresetResolution | null;
    runtime_image_id: string | null;
  };
  policy: typeof DEFAULT_EVOLUTION_POLICY;
  initial_cash: number;
  benchmark: string;
  fish_context_enabled: false;
  memory_in_backtest: false;
  rke_mode: "shadow_only";
  config_hash: string;
  manifest_hash: string;
}

export interface QlibDataFingerprint {
  calendar_sha256: string;
  instruments_sha256: string;
  feature_inventory_sha256: string;
  feature_content_sha256: string;
  feature_file_count: number;
  feature_total_bytes: number;
  first_date: string;
  last_date: string;
  selected_days_sha256: string;
}

interface WorktreeGraph {
  path: string;
  promptsRoot: string;
  promptSha256: string;
  graph: ReturnType<typeof buildDailyCycleGraph>;
}

interface DailyOutput {
  arm: ArmCheckpoint;
  actions: BacktestActionInput[];
  usage: LlmUsage;
  scorecardState: Record<string, unknown>;
}

export function registerBacktestEvolve(program: Command): void {
  program
    .command("backtest-evolve")
    .description("Resumable PIT walk-forward Agent replay with historical prompt evolution.")
    .requiredOption("--start <YYYY-MM-DD>", "first trading date")
    .requiredOption("--end <YYYY-MM-DD>", "last trading date")
    .requiredOption("--run-dir <path>", "private/gitignored run directory")
    .requiredOption("--prompt-baseline-commit <hash>", "pinned commit in MOSAIC_PROMPTS_REPO")
    .option("--cohort <name>", `isolated cohort (default ${DEFAULT_COHORT})`)
    .option("--fake-llm", "deterministic no-cost smoke mode; skips sndr")
    .option("--launch-model", "start the resolved sndr preset when it is not already healthy")
    .option("--resume", "resume an existing checkpoint in --run-dir")
    .option("--dry-run", "validate model/prompt preflight without creating a backtest run")
    .option("--max-days <n>", "stop after N newly completed trading days")
    .option("--log-every <n>", "print progress every N completed days (default 5)")
    .option("--initial-cash <amount>", "initial qlib cash (default 1000000)")
    .option("--benchmark <ticker>", "benchmark (default SH000300)")
    .action(async (opts: BacktestEvolveOptions) => runBacktestEvolution(opts));
}

async function runBacktestEvolution(opts: BacktestEvolveOptions): Promise<void> {
  const repoRoot = git(process.cwd(), ["rev-parse", "--show-toplevel"]);
  const runDir = isAbsolute(opts.runDir) ? opts.runDir : resolve(repoRoot, opts.runDir);
  const cohort = opts.cohort ?? DEFAULT_COHORT;
  const initialCash = parsePositiveNumber(opts.initialCash ?? "1000000", "--initial-cash");
  const benchmark = opts.benchmark ?? "SH000300";
  const maxDays = opts.maxDays ? parsePositiveInteger(opts.maxDays, "--max-days") : undefined;
  const logEvery = parsePositiveInteger(opts.logEvery ?? "5", "--log-every");
  const promptRepoRaw =
    process.env.MOSAIC_PROMPTS_REPO?.trim() || process.env.MOSAIC_PRIVATE_PROMPT_REPO?.trim();
  if (!promptRepoRaw) {
    throw new Error("MOSAIC_PROMPTS_REPO is required for historical prompt isolation");
  }
  const promptRepo = resolve(promptRepoRaw);
  assertPrivateRunDir(runDir, repoRoot);
  assertCleanGitRepo(repoRoot, "MOSAIC-RKE repo");
  assertCleanGitRepo(promptRepo, "private prompt repo");
  const baselineCommit = git(promptRepo, ["rev-parse", opts.promptBaselineCommit]);
  const codeCommit = git(repoRoot, ["rev-parse", "HEAD"]);

  let resolution: SndrPresetResolution | null = null;
  let runtimeImageId: string | null = null;
  if (!opts.fakeLlm) {
    resolution = resolveQwen35bPreset();
    const preflight = preflightQwen35bPreset();
    console.log(pc.dim(preflight.split("\n").at(-1) ?? "sndr preflight passed"));
    if (opts.launchModel) launchQwen35bPreset();
    const apiKey = process.env.MOSAIC_VLLM_API_KEY ?? process.env.OPENAI_API_KEY;
    await waitForQwen35bService({ resolution, ...(apiKey ? { apiKey } : {}) });
    runtimeImageId = verifyQwen35bRuntimeImage(resolution);
  }
  const qlib = loadStrictQlibTradingDays(opts.start, opts.end);

  if (opts.dryRun) {
    console.log(
      pc.green(
        `preflight ready: code=${codeCommit.slice(0, 12)} prompt=${baselineCommit.slice(0, 12)} ` +
          `model=${opts.fakeLlm ? "fake" : `${QWEN_35B_SERVED_MODEL} (${resolution?.hash})`} ` +
          `qlib_days=${qlib.tradeDays.length} data=${sha256Json(qlib.fingerprint)}`,
      ),
    );
    return;
  }

  mkdirSync(runDir, { recursive: true });
  const configPath = join(runDir, "config.json");
  const dataDir = join(runDir, "data");
  const checkpointPath = join(runDir, "checkpoint.json");
  const journalPath = join(runDir, "daily-journal.json");
  const manifestPath = join(runDir, "manifest.json");
  const configOverrides = historicalConfig(cohort, opts.start, opts.end);
  writeJsonAtomic(configPath, configOverrides);
  process.env.MOSAIC_CONFIG = configPath;
  process.env.MOSAIC_DATA_DIR = dataDir;
  process.env.MOSAIC_REPO_ROOT = repoRoot;
  process.env.MOSAIC_PROMPT_MUTATION_TRANSACTION_DIR = join(runDir, "mutation-transactions");

  const client = new BridgeClient();
  const worktrees = new Map<string, WorktreeGraph>();
  try {
    await client.start();
    const api = new BridgeApi(client);
    const config = await api.configGet();
    const rawLlmHandle = opts.fakeLlm
      ? buildFakeLlmHandle()
      : createLlmFromConfig(config, {
          tier: "deep",
          provider: "vllm",
          model: QWEN_35B_SERVED_MODEL,
          baseUrl: `http://127.0.0.1:${resolution?.port ?? 8000}/v1`,
          useProviderSamplingDefaults: true,
        });
    const llmHandle = opts.fakeLlm ? rawLlmHandle : serializeLlmHandle(rawLlmHandle);
    const baselineWorktree = await prepareGraph(api, llmHandle, config, baselineCommit, cohort);
    worktrees.set(baselineCommit, baselineWorktree);
    const manifest = ensureManifest({
      path: manifestPath,
      resume: opts.resume ?? false,
      start: opts.start,
      end: opts.end,
      cohort,
      codeCommit,
      baselineCommit,
      baselinePromptSha256: baselineWorktree.promptSha256,
      resolution,
      runtimeImageId,
      fakeLlm: opts.fakeLlm ?? false,
      initialCash,
      benchmark,
      configOverrides,
      qlibData: qlib.fingerprint,
    });
    const tradeDays = qlib.tradeDays;
    if (tradeDays.length === 0) throw new Error("no qlib trading days in requested range");
    const tradeDaysHash = sha256Json(tradeDays);
    let checkpoint = existsSync(checkpointPath)
      ? loadCheckpoint(checkpointPath)
      : await initialiseCheckpoint({
          api,
          manifest,
          cohort,
          tradeDaysHash,
          baselineCommit,
          baselinePromptSha256: baselineWorktree.promptSha256,
          start: opts.start,
          end: opts.end,
        });
    if (existsSync(checkpointPath) && !opts.resume) {
      throw new Error("checkpoint exists; pass --resume instead of starting over");
    }
    validateCheckpoint(checkpoint, manifest, tradeDaysHash);
    if (!existsSync(checkpointPath)) writeJsonAtomic(checkpointPath, checkpoint);
    if (existsSync(journalPath)) {
      checkpoint = await recoverDailyJournal(api, checkpoint, checkpointPath, journalPath);
    }

    const getGraph = async (commit: string): Promise<WorktreeGraph> => {
      const existing = worktrees.get(commit);
      if (existing) return existing;
      const prepared = await prepareGraph(api, llmHandle, config, commit, cohort);
      worktrees.set(commit, prepared);
      return prepared;
    };

    let newlyCompleted = 0;
    while (checkpoint.nextTradingDayIndex < tradeDays.length) {
      if (maxDays !== undefined && newlyCompleted >= maxDays) break;
      const index = checkpoint.nextTradingDayIndex;
      const tradeDate = tradeDays[index] as string;
      checkpoint = await settleCandidates({
        api,
        checkpoint,
        checkpointPath,
        runDir,
        tradeDate,
        initialCash,
        benchmark,
        getGraph,
      });
      await pruneWorktrees(api, worktrees, checkpoint);

      const checkpointHash = sha256Json(checkpoint);
      const mainGraph = await getGraph(checkpoint.activePromptCommit);
      const mainOutput = await invokeArm(mainGraph.graph, checkpoint.mainArm, cohort, tradeDate);
      const writes: DailyJournal["writes"] = [
        { runId: checkpoint.mainBacktestRunId, actions: mainOutput.actions },
      ];
      const candidateArms: DailyJournal["candidateArms"] = {};
      const usage: DailyJournal["usage"] = { main: mainOutput.usage };

      for (const candidate of checkpoint.candidates) {
        const phase = phaseForDate(candidate, tradeDate);
        if (phase !== "validating" && phase !== "holdout") continue;
        const [baseGraph, candidateGraph] = await Promise.all([
          getGraph(candidate.baseCommit),
          getGraph(candidate.candidateCommit),
        ]);
        const baseOutput = await invokeArm(baseGraph.graph, candidate.baseArm, cohort, tradeDate);
        const candidateOutput = await invokeArm(
          candidateGraph.graph,
          candidate.candidateArm,
          cohort,
          tradeDate,
        );
        const baseRunId =
          phase === "validating" ? candidate.runs.validationBase : candidate.runs.holdoutBase;
        const candidateRunId =
          phase === "validating"
            ? candidate.runs.validationCandidate
            : candidate.runs.holdoutCandidate;
        writes.push(
          { runId: baseRunId, actions: baseOutput.actions },
          { runId: candidateRunId, actions: candidateOutput.actions },
        );
        candidateArms[candidate.id] = {
          baseArm: baseOutput.arm,
          candidateArm: candidateOutput.arm,
        };
        usage[`${candidate.id}:base`] = baseOutput.usage;
        usage[`${candidate.id}:candidate`] = candidateOutput.usage;
      }

      const journal: DailyJournal = {
        schemaVersion: "mosaic.backtest_evolution_daily_journal.v1",
        tradingDayIndex: index,
        tradeDate,
        checkpointHash,
        writes,
        mainArm: mainOutput.arm,
        candidateArms,
        usage,
        scorecardState: mainOutput.scorecardState,
      };
      writeJsonAtomic(journalPath, journal);
      checkpoint = await applyDailyJournal(api, checkpoint, journal);
      writeJsonAtomic(checkpointPath, checkpoint);
      rmSync(journalPath, { force: true });
      newlyCompleted += 1;

      if (
        shouldTriggerEvolution(
          tradeDays,
          index,
          checkpoint.processedEvolutionMonths,
          DEFAULT_EVOLUTION_POLICY,
        )
      ) {
        checkpoint = await generateMonthlyCandidates({
          api,
          checkpoint,
          checkpointPath,
          tradeDays,
          triggerIndex: index,
          triggerDate: tradeDate,
          llmHandle,
          config,
          codeCommit,
          cohort,
          getGraph,
        });
        await pruneWorktrees(api, worktrees, checkpoint);
      }

      if (newlyCompleted === 1 || newlyCompleted % logEvery === 0) {
        console.log(
          pc.dim(
            `[${checkpoint.nextTradingDayIndex}/${tradeDays.length}] ${tradeDate} ` +
              `active=${checkpoint.activePromptCommit.slice(0, 12)} ` +
              `pending=${checkpoint.candidates.filter((item) => !isTerminal(item.status)).length}`,
          ),
        );
      }
    }

    if (checkpoint.nextTradingDayIndex >= tradeDays.length) {
      checkpoint = await settleCandidates({
        api,
        checkpoint,
        checkpointPath,
        runDir,
        tradeDate: "9999-12-31",
        initialCash,
        benchmark,
        getGraph,
      });
      await api.backtestCompleteRun(checkpoint.mainBacktestRunId);
      const metrics = await api.backtestRunHistorical(checkpoint.mainBacktestRunId, {
        initial_cash: initialCash,
        benchmark,
        results_dir: join(runDir, "final"),
      });
      checkpoint.completedAt = new Date().toISOString();
      writeJsonAtomic(checkpointPath, checkpoint);
      writeJsonAtomic(join(runDir, "final", "evolution-summary.json"), {
        metrics,
        main_usage: checkpoint.mainUsage,
        lineage: checkpoint.lineage,
        candidates: checkpoint.candidates.map(candidateSummary),
      });
      console.log(pc.green(`history evolution completed: run_id=${metrics.run_id}`));
    } else {
      console.log(
        pc.yellow(`paused at trading-day index ${checkpoint.nextTradingDayIndex}; use --resume`),
      );
    }
  } catch (error) {
    const tail = client.stderrTail.trim();
    if (tail) console.error(pc.dim(tail.slice(-2_000)));
    if (error instanceof RpcError) {
      throw new Error(`bridge error [${error.code}]: ${redactSensitiveText(error.message)}`);
    }
    throw error;
  } finally {
    for (const worktree of worktrees.values()) {
      try {
        const api = new BridgeApi(client);
        await api.autoresearchCleanupWorktree({
          path: worktree.path,
          repo_target: "private_git",
        });
      } catch {
        // Worktree GC is available for interrupted runs; cleanup is best effort.
      }
    }
    await client.close();
  }
}

function historicalConfig(cohort: string, start: string, end: string): Record<string, unknown> {
  return {
    active_cohort: cohort,
    cohorts: { [cohort]: { start, end } },
    memory_in_backtest: false,
    mirofish: { engine: "fish", scorer: "terminal", inject_context: false },
  };
}

async function initialiseCheckpoint(opts: {
  api: BridgeApi;
  manifest: EvolutionManifest;
  cohort: string;
  tradeDaysHash: string;
  baselineCommit: string;
  baselinePromptSha256: string;
  start: string;
  end: string;
}): Promise<EvolutionCheckpoint> {
  const run = await opts.api.backtestCreateRun({
    cohort: opts.cohort,
    start_date: opts.start,
    end_date: opts.end,
    prompt_commit_hash: `history-evolve:${opts.manifest.manifest_hash}`,
    prompt_repo_id: "private",
    prompt_sha256: opts.baselinePromptSha256,
    code_commit_hash: opts.manifest.code_commit,
  });
  const initial = makeInitialState(opts.cohort, opts.start);
  return {
    schemaVersion: EVOLUTION_CHECKPOINT_SCHEMA,
    runId: opts.manifest.run_id,
    cohort: opts.cohort,
    startDate: opts.start,
    endDate: opts.end,
    nextTradingDayIndex: 0,
    tradeDaysHash: opts.tradeDaysHash,
    mainBacktestRunId: run.run_id,
    activePromptCommit: opts.baselineCommit,
    activePromptSha256: opts.baselinePromptSha256,
    activePromptBranch: `history/${opts.cohort}/active/${opts.manifest.run_id}`,
    mainArm: {
      positions: initial.current_positions,
      previousTarget: initial.layer4_outputs.previous_target_state as PreviousTargetState,
    },
    mainUsage: { ...EMPTY_LLM_USAGE },
    candidates: [],
    lineage: [],
    processedEvolutionMonths: [],
    layerRotation: { macro: 0, sector: 0, superinvestor: 0, decision: 0 },
  };
}

async function prepareGraph(
  api: BridgeApi,
  llmHandle: LlmHandle,
  config: MosaicConfig,
  commit: string,
  cohort: string,
): Promise<WorktreeGraph> {
  const worktree = await api.autoresearchPrepareWorktree({
    repo_target: "private_git",
    ref: commit,
  });
  if (!worktree.prompts_root) throw new Error("private prompt worktree has no prompts_root");
  return {
    path: worktree.path,
    promptsRoot: worktree.prompts_root,
    promptSha256: hashPromptTree(worktree.prompts_root, cohort),
    graph: buildDailyCycleGraph({
      llmHandle,
      api,
      config,
      promptsRoot: worktree.prompts_root,
    }),
  };
}

async function invokeArm(
  graph: ReturnType<typeof buildDailyCycleGraph>,
  arm: ArmCheckpoint,
  cohort: string,
  tradeDate: string,
): Promise<DailyOutput> {
  const initial = makeInitialState(cohort, tradeDate);
  initial.current_positions = arm.positions;
  initial.layer4_outputs.previous_target_state = arm.previousTarget;
  const started = Date.now();
  const final = (await graph.invoke(initial)) as DailyCycleStateType;
  const actions = (final.portfolio_actions ?? []).map((action) => ({
    ticker: action.ticker,
    action: action.action,
    target_weight: action.target_weight,
    ...(action.holding_period ? { holding_period: action.holding_period } : {}),
    ...(action.dissent_notes ? { dissent_notes: action.dissent_notes } : {}),
  })) satisfies BacktestActionInput[];
  return {
    actions,
    arm: {
      positions: applyBacktestPortfolioActionsToPositions(
        arm.positions,
        final.portfolio_actions ?? [],
        tradeDate,
      ),
      previousTarget: carryPreviousTargetState(final),
    },
    usage: {
      calls: final.llm_calls.length,
      promptTokens: final.llm_calls.reduce((sum, call) => sum + call.prompt_tokens, 0),
      completionTokens: final.llm_calls.reduce((sum, call) => sum + call.completion_tokens, 0),
      costUsd: final.llm_calls.reduce((sum, call) => sum + call.cost_usd, 0),
      elapsedMs: Date.now() - started,
    },
    scorecardState: {
      active_cohort: final.active_cohort,
      as_of_date: final.as_of_date,
      layer1_outputs: final.layer1_outputs,
      layer1_consensus: final.layer1_consensus,
      layer2_outputs: final.layer2_outputs,
      layer2_consensus: final.layer2_consensus,
      layer3_outputs: final.layer3_outputs,
      layer4_outputs: final.layer4_outputs,
      portfolio_actions: final.portfolio_actions,
    },
  };
}

async function applyDailyJournal(
  api: BridgeApi,
  checkpoint: EvolutionCheckpoint,
  journal: DailyJournal,
): Promise<EvolutionCheckpoint> {
  if (journal.checkpointHash !== sha256Json(checkpoint)) {
    throw new Error("daily journal does not match checkpoint; refusing ambiguous recovery");
  }
  for (const write of journal.writes) {
    await api.backtestAppendActions(write.runId, journal.tradeDate, write.actions);
  }
  await api.scorecardAppend(journal.scorecardState);
  await api.scorecardScorePending(checkpoint.cohort, journal.tradeDate);
  await api.darwinianCompute(checkpoint.cohort, journal.tradeDate);
  checkpoint.mainArm = journal.mainArm;
  checkpoint.mainUsage = addLlmUsage(checkpoint.mainUsage, journal.usage.main ?? EMPTY_LLM_USAGE);
  for (const [candidateId, arms] of Object.entries(journal.candidateArms)) {
    const candidate = checkpoint.candidates.find((item) => item.id === candidateId);
    if (!candidate) throw new Error(`journal references unknown candidate ${candidateId}`);
    candidate.baseArm = arms.baseArm;
    candidate.candidateArm = arms.candidateArm;
    candidate.usage.base = addLlmUsage(
      candidate.usage.base,
      journal.usage[`${candidateId}:base`] ?? EMPTY_LLM_USAGE,
    );
    candidate.usage.candidate = addLlmUsage(
      candidate.usage.candidate,
      journal.usage[`${candidateId}:candidate`] ?? EMPTY_LLM_USAGE,
    );
    const phase = phaseForDate(candidate, journal.tradeDate);
    if (phase) candidate.status = phase;
  }
  checkpoint.nextTradingDayIndex = journal.tradingDayIndex + 1;
  return checkpoint;
}

async function recoverDailyJournal(
  api: BridgeApi,
  checkpoint: EvolutionCheckpoint,
  checkpointPath: string,
  journalPath: string,
): Promise<EvolutionCheckpoint> {
  const journal = JSON.parse(readFileSync(journalPath, "utf-8")) as DailyJournal;
  if (journal.schemaVersion !== "mosaic.backtest_evolution_daily_journal.v1") {
    throw new Error("unsupported daily journal schema");
  }
  if (checkpoint.nextTradingDayIndex === journal.tradingDayIndex + 1) {
    rmSync(journalPath, { force: true });
    return checkpoint;
  }
  if (checkpoint.nextTradingDayIndex !== journal.tradingDayIndex) {
    throw new Error("daily journal index is inconsistent with checkpoint");
  }
  const recovered = await applyDailyJournal(api, checkpoint, journal);
  writeJsonAtomic(checkpointPath, recovered);
  rmSync(journalPath, { force: true });
  return recovered;
}

async function generateMonthlyCandidates(opts: {
  api: BridgeApi;
  checkpoint: EvolutionCheckpoint;
  checkpointPath: string;
  tradeDays: ReadonlyArray<string>;
  triggerIndex: number;
  triggerDate: string;
  llmHandle: LlmHandle;
  config: MosaicConfig;
  codeCommit: string;
  cohort: string;
  getGraph: (commit: string) => Promise<WorktreeGraph>;
}): Promise<EvolutionCheckpoint> {
  const month = opts.triggerDate.slice(0, 7);
  const window = candidateWindow(opts.tradeDays, opts.triggerIndex, DEFAULT_EVOLUTION_POLICY);
  if (!window) {
    opts.checkpoint.processedEvolutionMonths.push(month);
    writeJsonAtomic(opts.checkpointPath, opts.checkpoint);
    return opts.checkpoint;
  }
  const [macroSkill, weights] = await Promise.all([
    opts.api.scorecardListMacroSkill(opts.cohort, window.trainStart),
    opts.api.darwinianGetWeights(opts.cohort, opts.triggerDate),
  ]);
  const baseGraph = await opts.getGraph(opts.checkpoint.activePromptCommit);
  const familyId = `${opts.checkpoint.runId}:${month}`;
  for (const layer of LAYER_ORDER) {
    if (pendingLayer(opts.checkpoint.candidates, layer)) continue;
    const agent = selectLayerAgent({
      layer,
      macroSkill: macroSkill.rows,
      weights: weights.weights,
      rotation: opts.checkpoint.layerRotation[layer],
    });
    opts.checkpoint.layerRotation[layer] += 1;
    const cycle = await runAutoresearchCycle({
      cohort: opts.cohort,
      forceAgent: agent,
      maxMutations: 1,
      mutationMode: "prompt_rewrite",
      historicalSandbox: true,
      historicalRunId: opts.checkpoint.runId,
      simulatedNow: opts.triggerDate,
      promptsRoot: baseGraph.promptsRoot,
      basePromptCommit: opts.checkpoint.activePromptCommit,
      codeCommitHash: opts.codeCommit,
      ...(opts.llmHandle.provider === "fake" ? { fakeLlm: true } : {}),
      deps: { llm: opts.llmHandle.llm, api: opts.api },
    });
    const mutation = cycle.mutations[0];
    if (!mutation?.version_id || !mutation.prompt_commit_hash || !mutation.branch_name) {
      console.error(
        pc.yellow(`evolution skipped ${layer}/${agent}: ${mutation?.error ?? "no commit"}`),
      );
      continue;
    }
    const compatibility = await opts.api.autoresearchHistoricalValidate({
      version_id: mutation.version_id,
    });
    if (!compatibility.compatible) {
      const reasonCodes = ["PROMPT_COMPATIBILITY_FAILED"];
      await opts.api.autoresearchHistoricalDecide({
        version_id: mutation.version_id,
        decision: "revert",
        decided_at: opts.triggerDate,
        base_ref: opts.checkpoint.activePromptCommit,
      });
      opts.checkpoint.lineage.push({
        date: opts.triggerDate,
        agent,
        versionId: mutation.version_id,
        decision: "revert",
        previousCommit: opts.checkpoint.activePromptCommit,
        activeCommit: opts.checkpoint.activePromptCommit,
        reasonCodes,
      });
      writeJsonAtomic(opts.checkpointPath, opts.checkpoint);
      console.error(
        pc.yellow(`evolution rejected ${layer}/${agent}: incompatible prompt contract`),
      );
      continue;
    }
    const candidateGraph = await opts.getGraph(mutation.prompt_commit_hash);
    const runs = await createCandidateRuns({
      api: opts.api,
      cohort: opts.cohort,
      window,
      baseCommit: opts.checkpoint.activePromptCommit,
      basePromptSha256: baseGraph.promptSha256,
      candidateCommit: mutation.prompt_commit_hash,
      candidatePromptSha256: candidateGraph.promptSha256,
      codeCommit: opts.codeCommit,
    });
    const candidate: EvolutionCandidate = {
      id: `${familyId}:${layer}:${agent}:${mutation.version_id}`,
      familyId,
      versionId: mutation.version_id,
      agent,
      layer,
      triggerDate: opts.triggerDate,
      triggerIndex: opts.triggerIndex,
      baseCommit: opts.checkpoint.activePromptCommit,
      candidateCommit: mutation.prompt_commit_hash,
      candidatePromptSha256: candidateGraph.promptSha256,
      branchName: mutation.branch_name,
      window,
      runs,
      baseArm: structuredClone(opts.checkpoint.mainArm),
      candidateArm: structuredClone(opts.checkpoint.mainArm),
      status: "purging",
      reasonCodes: [],
      usage: {
        base: { ...EMPTY_LLM_USAGE },
        candidate: { ...EMPTY_LLM_USAGE },
      },
    };
    opts.checkpoint.candidates.push(candidate);
    writeJsonAtomic(opts.checkpointPath, opts.checkpoint);
  }
  opts.checkpoint.processedEvolutionMonths.push(month);
  writeJsonAtomic(opts.checkpointPath, opts.checkpoint);
  return opts.checkpoint;
}

async function createCandidateRuns(opts: {
  api: BridgeApi;
  cohort: string;
  window: EvolutionCandidate["window"];
  baseCommit: string;
  basePromptSha256: string;
  candidateCommit: string;
  candidatePromptSha256: string;
  codeCommit: string;
}): Promise<EvolutionCandidate["runs"]> {
  const create = async (start: string, end: string, commit: string, sha: string) =>
    (
      await opts.api.backtestCreateRun({
        cohort: opts.cohort,
        start_date: start,
        end_date: end,
        prompt_commit_hash: commit,
        prompt_repo_id: "private",
        prompt_sha256: sha,
        code_commit_hash: opts.codeCommit,
      })
    ).run_id;
  const [validationBase, validationCandidate, holdoutBase, holdoutCandidate] = await Promise.all([
    create(
      opts.window.validationStart,
      opts.window.validationEnd,
      opts.baseCommit,
      opts.basePromptSha256,
    ),
    create(
      opts.window.validationStart,
      opts.window.validationEnd,
      opts.candidateCommit,
      opts.candidatePromptSha256,
    ),
    create(
      opts.window.holdoutStart,
      opts.window.holdoutEnd,
      opts.baseCommit,
      opts.basePromptSha256,
    ),
    create(
      opts.window.holdoutStart,
      opts.window.holdoutEnd,
      opts.candidateCommit,
      opts.candidatePromptSha256,
    ),
  ]);
  return { validationBase, validationCandidate, holdoutBase, holdoutCandidate };
}

async function settleCandidates(opts: {
  api: BridgeApi;
  checkpoint: EvolutionCheckpoint;
  checkpointPath: string;
  runDir: string;
  tradeDate: string;
  initialCash: number;
  benchmark: string;
  getGraph: (commit: string) => Promise<WorktreeGraph>;
}): Promise<EvolutionCheckpoint> {
  for (const candidate of opts.checkpoint.candidates) {
    if (
      (candidate.status === "validating" || candidate.status === "purging") &&
      opts.tradeDate > candidate.window.validationEnd
    ) {
      try {
        candidate.validation = await evaluateArms({
          api: opts.api,
          baseRunId: candidate.runs.validationBase,
          candidateRunId: candidate.runs.validationCandidate,
          outDir: join(opts.runDir, "candidates", safeId(candidate.id), "validation"),
          initialCash: opts.initialCash,
          benchmark: opts.benchmark,
          seed: `${candidate.id}:validation`,
        });
        const reasons = evaluationReasonCodes(candidate.validation);
        if (reasons.length > 0) {
          candidate.status = "validation_failed";
          candidate.reasonCodes = reasons;
          await recordDecision(opts, candidate, "revert", reasons);
        } else {
          candidate.status = "embargoed";
        }
      } catch (error) {
        candidate.status = "error";
        candidate.reasonCodes = ["VALIDATION_ERROR"];
        await recordDecision(opts, candidate, "revert", candidate.reasonCodes);
        console.error(pc.red(`${candidate.id}: ${redactSensitiveText((error as Error).message)}`));
      }
      writeJsonAtomic(opts.checkpointPath, opts.checkpoint);
    }
    if (
      (candidate.status === "holdout" || candidate.status === "embargoed") &&
      opts.tradeDate > candidate.window.holdoutEnd
    ) {
      try {
        candidate.holdout = await evaluateArms({
          api: opts.api,
          baseRunId: candidate.runs.holdoutBase,
          candidateRunId: candidate.runs.holdoutCandidate,
          outDir: join(opts.runDir, "candidates", safeId(candidate.id), "holdout"),
          initialCash: opts.initialCash,
          benchmark: opts.benchmark,
          seed: `${candidate.id}:holdout`,
        });
        candidate.status = "awaiting_family";
      } catch (error) {
        candidate.status = "error";
        candidate.reasonCodes = ["HOLDOUT_ERROR"];
        await recordDecision(opts, candidate, "revert", candidate.reasonCodes);
        console.error(pc.red(`${candidate.id}: ${redactSensitiveText((error as Error).message)}`));
      }
      writeJsonAtomic(opts.checkpointPath, opts.checkpoint);
    }
  }

  const familyIds = [...new Set(opts.checkpoint.candidates.map((candidate) => candidate.familyId))];
  for (const familyId of familyIds) {
    const family = opts.checkpoint.candidates.filter(
      (candidate) => candidate.familyId === familyId,
    );
    const ready = family.some((candidate) => candidate.status === "awaiting_family");
    const allSettled = family.every((candidate) =>
      ["awaiting_family", "validation_failed", "error", "kept", "reverted"].includes(
        candidate.status,
      ),
    );
    if (!ready || !allSettled) continue;
    const qValues = benjaminiHochberg(
      family.map((candidate) => ({
        id: candidate.id,
        pValue: candidate.holdout?.paired.pValue ?? 1,
      })),
    );
    for (const candidate of [...family].sort(
      (left, right) => LAYER_ORDER.indexOf(left.layer) - LAYER_ORDER.indexOf(right.layer),
    )) {
      if (candidate.status !== "awaiting_family" || !candidate.holdout) continue;
      candidate.adjustedQ = qValues[candidate.id] ?? 1;
      const reasons = evaluationReasonCodes(candidate.holdout, {
        adjustedQ: candidate.adjustedQ,
      });
      candidate.reasonCodes = reasons;
      if (reasons.length === 0) {
        const previousCommit = opts.checkpoint.activePromptCommit;
        const decision = await opts.api.autoresearchHistoricalDecide({
          version_id: candidate.versionId,
          decision: "keep",
          decided_at: opts.tradeDate,
          base_ref: previousCommit,
          active_branch: opts.checkpoint.activePromptBranch,
        });
        opts.checkpoint.activePromptCommit = decision.active_commit;
        const graph = await opts.getGraph(decision.active_commit);
        opts.checkpoint.activePromptSha256 = graph.promptSha256;
        candidate.status = "kept";
        opts.checkpoint.lineage.push({
          date: opts.tradeDate,
          agent: candidate.agent,
          versionId: candidate.versionId,
          decision: "keep",
          previousCommit,
          activeCommit: decision.active_commit,
          reasonCodes: [],
        });
      } else {
        await recordDecision(opts, candidate, "revert", reasons);
        candidate.status = "reverted";
      }
      writeJsonAtomic(opts.checkpointPath, opts.checkpoint);
    }
  }
  return opts.checkpoint;
}

async function recordDecision(
  opts: {
    api: BridgeApi;
    checkpoint: EvolutionCheckpoint;
    tradeDate: string;
  },
  candidate: EvolutionCandidate,
  decision: "revert",
  reasonCodes: string[],
): Promise<void> {
  await opts.api.autoresearchHistoricalDecide({
    version_id: candidate.versionId,
    decision,
    decided_at: opts.tradeDate,
    base_ref: opts.checkpoint.activePromptCommit,
  });
  opts.checkpoint.lineage.push({
    date: opts.tradeDate,
    agent: candidate.agent,
    versionId: candidate.versionId,
    decision,
    previousCommit: opts.checkpoint.activePromptCommit,
    activeCommit: opts.checkpoint.activePromptCommit,
    reasonCodes,
  });
}

async function evaluateArms(opts: {
  api: BridgeApi;
  baseRunId: number;
  candidateRunId: number;
  outDir: string;
  initialCash: number;
  benchmark: string;
  seed: string;
}): Promise<ArmEvaluation> {
  await Promise.all([
    opts.api.backtestCompleteRun(opts.baseRunId),
    opts.api.backtestCompleteRun(opts.candidateRunId),
  ]);
  const baseDir = join(opts.outDir, "base");
  const candidateDir = join(opts.outDir, "candidate");
  const [base, candidate] = await Promise.all([
    opts.api.backtestRunHistorical(opts.baseRunId, {
      initial_cash: opts.initialCash,
      benchmark: opts.benchmark,
      results_dir: baseDir,
    }),
    opts.api.backtestRunHistorical(opts.candidateRunId, {
      initial_cash: opts.initialCash,
      benchmark: opts.benchmark,
      results_dir: candidateDir,
    }),
  ]);
  const baseTrajectory = readTrajectory(join(baseDir, "portfolio_trajectory.csv"));
  const candidateTrajectory = readTrajectory(join(candidateDir, "portfolio_trajectory.csv"));
  if (baseTrajectory.returns.length !== candidateTrajectory.returns.length) {
    throw new Error("base/candidate qlib trajectories are not aligned");
  }
  return {
    base,
    candidate,
    baseTurnover: baseTrajectory.turnover,
    candidateTurnover: candidateTrajectory.turnover,
    paired: pairedBlockBootstrap({
      baseReturns: baseTrajectory.returns,
      candidateReturns: candidateTrajectory.returns,
      blockLength: DEFAULT_EVOLUTION_POLICY.blockLength,
      samples: DEFAULT_EVOLUTION_POLICY.bootstrapSamples,
      seed: opts.seed,
    }),
  };
}

function readTrajectory(path: string): { returns: number[]; turnover: number } {
  const lines = readFileSync(path, "utf-8").trim().split(/\r?\n/);
  const headers = lines.shift()?.split(",") ?? [];
  const returnIndex = headers.indexOf("return");
  const turnoverIndex = headers.indexOf("turnover");
  if (returnIndex < 0) throw new Error(`trajectory has no return column: ${path}`);
  const returns: number[] = [];
  let turnover = 0;
  for (const line of lines) {
    if (!line) continue;
    const cells = line.split(",");
    const value = Number(cells[returnIndex]);
    if (!Number.isFinite(value)) throw new Error(`trajectory contains invalid return: ${path}`);
    returns.push(value);
    if (turnoverIndex >= 0) {
      const item = Number(cells[turnoverIndex]);
      if (Number.isFinite(item)) turnover += Math.abs(item);
    }
  }
  return { returns, turnover };
}

function ensureManifest(opts: {
  path: string;
  resume: boolean;
  start: string;
  end: string;
  cohort: string;
  codeCommit: string;
  baselineCommit: string;
  baselinePromptSha256: string;
  resolution: SndrPresetResolution | null;
  runtimeImageId: string | null;
  fakeLlm: boolean;
  initialCash: number;
  benchmark: string;
  configOverrides: Record<string, unknown>;
  qlibData: QlibDataFingerprint;
}): EvolutionManifest {
  if (existsSync(opts.path)) {
    if (!opts.resume) throw new Error("manifest exists; pass --resume");
    const existing = JSON.parse(readFileSync(opts.path, "utf-8")) as EvolutionManifest;
    const expected = {
      start_date: opts.start,
      end_date: opts.end,
      cohort: opts.cohort,
      code_commit: opts.codeCommit,
      prompt_baseline_commit: opts.baselineCommit,
      config_hash: sha256Json(opts.configOverrides),
      model_hash: opts.resolution?.hash ?? "fake",
      runtime_image_id: opts.runtimeImageId,
      qlib_data_hash: sha256Json(opts.qlibData),
    };
    const actual = {
      start_date: existing.start_date,
      end_date: existing.end_date,
      cohort: existing.cohort,
      code_commit: existing.code_commit,
      prompt_baseline_commit: existing.prompt_baseline_commit,
      config_hash: existing.config_hash,
      model_hash: existing.model.resolution?.hash ?? "fake",
      runtime_image_id: existing.model.runtime_image_id,
      qlib_data_hash: sha256Json(existing.qlib_data),
    };
    if (sha256Json(actual) !== sha256Json(expected)) {
      throw new Error("resume manifest does not match code/prompt/model/config inputs");
    }
    return existing;
  }
  const createdAt = new Date().toISOString();
  const body = {
    schema_version: "mosaic.backtest_evolution_manifest.v1" as const,
    run_id: `history-${opts.start}-${createHash("sha256")
      .update(`${createdAt}:${opts.codeCommit}:${opts.baselineCommit}`)
      .digest("hex")
      .slice(0, 12)}`,
    created_at: createdAt,
    start_date: opts.start,
    end_date: opts.end,
    cohort: opts.cohort,
    code_commit: opts.codeCommit,
    prompt_repo_id: "private" as const,
    prompt_baseline_commit: opts.baselineCommit,
    prompt_baseline_sha256: opts.baselinePromptSha256,
    qlib_data: opts.qlibData,
    model: {
      provider: opts.fakeLlm ? ("fake" as const) : ("vllm" as const),
      served_model: opts.fakeLlm ? "fake-llm-mock" : QWEN_35B_SERVED_MODEL,
      preset: opts.fakeLlm ? "none" : QWEN_35B_NVFP4_PRESET,
      resolution: opts.resolution,
      runtime_image_id: opts.runtimeImageId,
    },
    policy: DEFAULT_EVOLUTION_POLICY,
    initial_cash: opts.initialCash,
    benchmark: opts.benchmark,
    fish_context_enabled: false as const,
    memory_in_backtest: false as const,
    rke_mode: "shadow_only" as const,
    config_hash: sha256Json(opts.configOverrides),
  };
  const manifest: EvolutionManifest = { ...body, manifest_hash: sha256Json(body) };
  writeJsonAtomic(opts.path, manifest);
  return manifest;
}

function validateCheckpoint(
  checkpoint: EvolutionCheckpoint,
  manifest: EvolutionManifest,
  tradeDaysHash: string,
): void {
  if (checkpoint.runId !== manifest.run_id) throw new Error("checkpoint run_id mismatch");
  if (checkpoint.tradeDaysHash !== tradeDaysHash) {
    throw new Error("trading calendar changed; start a new run instead of resuming");
  }
  if (checkpoint.startDate !== manifest.start_date || checkpoint.endDate !== manifest.end_date) {
    throw new Error("checkpoint date range mismatch");
  }
}

function hashPromptTree(root: string, cohort: string): string {
  const digest = createHash("sha256");
  for (const [layer, agents] of Object.entries(AGENTS_BY_LAYER) as Array<
    [Layer, ReadonlyArray<string>]
  >) {
    for (const agent of agents) {
      for (const language of ["zh", "en"] as const) {
        const candidates = [
          join(root, cohort, layer, `${agent}.${language}.md`),
          join(root, "cohort_default", layer, `${agent}.${language}.md`),
        ];
        const path = candidates.find((candidate) => existsSync(candidate));
        if (!path) throw new Error(`prompt missing for ${cohort}/${layer}/${agent}.${language}`);
        digest.update(`${layer}/${agent}.${language}\0`);
        digest.update(readFileSync(path));
        digest.update("\0");
      }
    }
  }
  return `sha256:${digest.digest("hex")}`;
}

function assertPrivateRunDir(runDir: string, repoRoot: string): void {
  const rel = relative(repoRoot, runDir);
  if (!rel.startsWith(".mosaic/") && !runDir.includes("/.mosaic/")) {
    throw new Error("--run-dir must be under a private .mosaic directory");
  }
}

export function loadStrictQlibTradingDays(
  start: string,
  end: string,
): { tradeDays: string[]; fingerprint: QlibDataFingerprint } {
  const root = process.env.QLIB_CN_DATA_PATH?.trim()
    ? resolve(process.env.QLIB_CN_DATA_PATH)
    : join(homedir(), ".qlib", "qlib_data", "cn_data");
  const calendarPath = join(root, "calendars", "day.txt");
  if (!existsSync(calendarPath)) {
    throw new Error(`strict Qlib calendar is missing: ${calendarPath}`);
  }
  const calendar = readFileSync(calendarPath, "utf-8")
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
  const first = calendar[0];
  const last = calendar.at(-1);
  if (!first || !last || start < first || end > last) {
    throw new Error(
      `requested range ${start}..${end} exceeds strict Qlib calendar ${first ?? "?"}..${last ?? "?"}`,
    );
  }
  const selected = calendar.filter((date) => date >= start && date <= end);
  if (selected.length === 0) throw new Error("strict Qlib calendar returned no trading days");
  const instrumentsRoot = join(root, "instruments");
  const instrumentFiles = existsSync(instrumentsRoot) ? listFiles(instrumentsRoot).sort() : [];
  if (instrumentFiles.length === 0) throw new Error("strict Qlib instruments are missing");
  const instrumentsDigest = createHash("sha256");
  for (const path of instrumentFiles) {
    instrumentsDigest.update(relative(instrumentsRoot, path));
    instrumentsDigest.update("\0");
    instrumentsDigest.update(readFileSync(path));
    instrumentsDigest.update("\0");
  }
  const featuresRoot = join(root, "features");
  const featureFiles = existsSync(featuresRoot) ? listFiles(featuresRoot).sort() : [];
  if (featureFiles.length === 0) throw new Error("strict Qlib features are missing");
  const featureDigest = createHash("sha256");
  const featureContentDigest = createHash("sha256");
  let featureTotalBytes = 0;
  for (const path of featureFiles) {
    const size = statSync(path).size;
    featureTotalBytes += size;
    const relativePath = relative(featuresRoot, path);
    featureDigest.update(`${relativePath}\0${size}\0`);
    featureContentDigest.update(`${relativePath}\0`);
    featureContentDigest.update(readFileSync(path));
    featureContentDigest.update("\0");
  }
  return {
    tradeDays: selected,
    fingerprint: {
      calendar_sha256: `sha256:${createHash("sha256").update(readFileSync(calendarPath)).digest("hex")}`,
      instruments_sha256: `sha256:${instrumentsDigest.digest("hex")}`,
      feature_inventory_sha256: `sha256:${featureDigest.digest("hex")}`,
      feature_content_sha256: `sha256:${featureContentDigest.digest("hex")}`,
      feature_file_count: featureFiles.length,
      feature_total_bytes: featureTotalBytes,
      first_date: first,
      last_date: last,
      selected_days_sha256: sha256Json(selected),
    },
  };
}

function listFiles(root: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) files.push(...listFiles(path));
    else if (entry.isFile()) files.push(path);
  }
  return files;
}

async function pruneWorktrees(
  api: BridgeApi,
  worktrees: Map<string, WorktreeGraph>,
  checkpoint: EvolutionCheckpoint,
): Promise<void> {
  const retained = new Set([checkpoint.activePromptCommit]);
  for (const candidate of checkpoint.candidates) {
    if (!isTerminal(candidate.status)) {
      retained.add(candidate.baseCommit);
      retained.add(candidate.candidateCommit);
    }
  }
  for (const [commit, worktree] of worktrees) {
    if (retained.has(commit)) continue;
    await api.autoresearchCleanupWorktree({
      path: worktree.path,
      repo_target: "private_git",
    });
    worktrees.delete(commit);
  }
}

function assertCleanGitRepo(path: string, label: string): void {
  const status = git(path, ["status", "--porcelain"]);
  if (status) throw new Error(`${label} must be clean before a historical run`);
}

function git(cwd: string, args: ReadonlyArray<string>): string {
  const result = spawnSync("git", [...args], { cwd, encoding: "utf-8" });
  if (result.status !== 0) {
    throw new Error(`git ${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`);
  }
  return result.stdout.trim();
}

function parsePositiveInteger(value: string, flag: string): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1)
    throw new Error(`${flag} must be a positive integer`);
  return parsed;
}

function parsePositiveNumber(value: string, flag: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) throw new Error(`${flag} must be positive`);
  return parsed;
}

function safeId(value: string): string {
  return value.replaceAll(/[^A-Za-z0-9._-]+/g, "-");
}

function isTerminal(status: CandidateStatus): boolean {
  return ["kept", "reverted", "validation_failed", "error"].includes(status);
}

function candidateSummary(candidate: EvolutionCandidate): Record<string, unknown> {
  return {
    id: candidate.id,
    agent: candidate.agent,
    layer: candidate.layer,
    trigger_date: candidate.triggerDate,
    base_commit: candidate.baseCommit,
    candidate_commit: candidate.candidateCommit,
    status: candidate.status,
    adjusted_q: candidate.adjustedQ,
    reason_codes: candidate.reasonCodes,
    window: candidate.window,
    validation: candidate.validation,
    holdout: candidate.holdout,
    usage: candidate.usage,
  };
}

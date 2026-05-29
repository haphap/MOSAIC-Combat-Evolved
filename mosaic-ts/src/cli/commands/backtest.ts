/**
 * Phase 3.5F CLI: ``pnpm dev backtest``.
 *
 * End-to-end orchestrator for the two-stage backtest pipeline:
 *
 *   1. Stage-1 (TS): batch-runs daily-cycles for [start, end], caches
 *      portfolio_actions to SQLite (delegates to the same logic as
 *      `pnpm dev backtest-fill`).
 *   2. Stage-2 (Python qlib): replays cached actions through qlib's
 *      executor against ~/.qlib/qlib_data/cn_data, returns metrics.
 *
 * Cache key (cohort, start, end, prompt_commit_hash) — re-running with
 * the same key skips stage-1 and goes straight to stage-2 (or just
 * recomputes metrics from cache).
 *
 * Output: pretty-printed metrics table + sparkline equity curve summary
 * (--out path writes raw JSON of {metrics, run_id}).
 */

import { writeFileSync } from "node:fs";
import type { Command } from "commander";
import pc from "picocolors";
import type { DailyCycleStateType } from "../../agents/state.js";
import type {
  BacktestActionInput,
  BacktestMetricsResult,
  BacktestRunInfo,
} from "../../bridge/index.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { buildDailyCycleGraph } from "../../graph/daily_cycle.js";
import { createLlmFromConfig, type LlmHandle } from "../../llm/factory.js";
import {
  buildFakeLlmHandle,
  enumerateTradingDays,
  makeInitialState,
} from "../_backtest_helpers.js";
import { pad } from "../_format.js";

interface BacktestOptions {
  cohort?: string;
  start: string;
  end: string;
  promptCommitHash?: string;
  fakeLlm?: boolean;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
  vetoThreshold?: string;
  initialCash?: string;
  benchmark?: string;
  out?: string;
  skipFill?: boolean;
  forceRefill?: boolean;
  logEvery?: string;
}

export function registerBacktest(program: Command): void {
  program
    .command("backtest")
    .description(
      "End-to-end backtest: stage-1 (daily-cycle fill) → stage-2 (qlib replay) → metrics.",
    )
    .requiredOption("--start <YYYY-MM-DD>", "first trade day")
    .requiredOption("--end <YYYY-MM-DD>", "last trade day (inclusive)")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--prompt-commit-hash <hash>", "Tag identifying the prompt version")
    .option("--fake-llm", "Use the in-memory canned mock for stage-1 (zero LLM cost)")
    .option("--llm-provider <name>", "Override LLM provider")
    .option("--model <name>", "Override LLM model")
    .option("--base-url <url>", "Override LLM base URL")
    .option("--veto-threshold <num>", "CRO veto threshold (default 0.5)")
    .option("--initial-cash <amount>", "Initial cash (default 1000000)")
    .option("--benchmark <ticker>", "Benchmark for alpha calc (default SH000300)")
    .option(
      "--skip-fill",
      "Skip stage-1; replay an existing run by (cohort, start, end, prompt_commit_hash)",
    )
    .option("--force-refill", "Re-run stage-1 even when a completed run exists for this cache key")
    .option("--log-every <n>", "Print stage-1 progress every N days (default 5)")
    .option("--out <path>", "Write {metrics, run_id} JSON to <path>")
    .action(async (opts: BacktestOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";
      const promptCommitHash = opts.promptCommitHash ?? "unversioned";
      const initialCash = opts.initialCash ? Number.parseFloat(opts.initialCash) : 1_000_000;
      const benchmark = opts.benchmark ?? "SH000300";

      try {
        await client.start();
        const t0 = Date.now();

        console.log(
          pc.bold(
            `\nbacktest — cohort=${cohort} prompt=${promptCommitHash} ` +
              `range=${opts.start}→${opts.end}`,
          ),
        );

        // Stage-1: fill cache (skip when --skip-fill or run is already
        // completed and not --force-refill).
        const runId = await ensureFilled(api, opts, cohort, promptCommitHash);
        const t1 = Date.now();
        console.log(pc.dim(`stage-1 done in ${((t1 - t0) / 1000).toFixed(1)}s`));

        // Stage-2: qlib replay.
        console.log(pc.dim("stage-2 (qlib replay) running..."));
        const metrics = await api.backtestRunHistorical(runId, {
          initial_cash: initialCash,
          benchmark,
        });
        const elapsed = ((Date.now() - t0) / 1000).toFixed(1);

        if (opts.out) {
          writeFileSync(opts.out, JSON.stringify({ metrics, run_id: runId }, null, 2), "utf-8");
          console.log(pc.dim(`metrics written to ${opts.out} (${elapsed}s total)`));
        } else {
          printMetrics(metrics, elapsed);
        }
      } catch (err) {
        if (err instanceof RpcError) {
          console.error(pc.red(`bridge error [${err.code}]: ${err.message}`));
        } else {
          console.error(pc.red(`error: ${(err as Error).message}`));
        }
        const tail = client.stderrTail.trim();
        if (tail) {
          console.error(pc.dim("\n--- bridge stderr (tail) ---"));
          console.error(pc.dim(tail.slice(-2000)));
        }
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });
}

// ---------------------------------------------------------------------------
// Stage-1: fill cache (or reuse existing completed run)
// ---------------------------------------------------------------------------

async function ensureFilled(
  api: BridgeApi,
  opts: BacktestOptions,
  cohort: string,
  promptCommitHash: string,
): Promise<number> {
  const runResult = await api.backtestCreateRun({
    cohort,
    start_date: opts.start,
    end_date: opts.end,
    prompt_commit_hash: promptCommitHash,
  });
  const runId = runResult.run_id;

  // Decide whether to fill: existing completed run + no force-refill = skip.
  const existing = await api.backtestGetRun(runId);
  if (opts.skipFill) {
    if (!existing.completed_at) {
      throw new Error(
        `--skip-fill set but run ${runId} has not been filled (completed_at=null). ` +
          "Drop --skip-fill or run 'pnpm dev backtest-fill' first.",
      );
    }
    console.log(pc.dim(`reusing completed run ${runId} (${existing.action_count} actions)`));
    return runId;
  }
  if (existing.completed_at && !opts.forceRefill) {
    console.log(
      pc.dim(
        `run ${runId} already filled (${existing.action_count} actions); ` +
          `use --force-refill to re-run stage-1`,
      ),
    );
    return runId;
  }

  // Need to fill.
  await fillStage1(api, opts, cohort, runId);
  return runId;
}

async function fillStage1(
  api: BridgeApi,
  opts: BacktestOptions,
  cohort: string,
  runId: number,
): Promise<void> {
  const config = await api.configGet();
  const llmHandle: LlmHandle = opts.fakeLlm
    ? buildFakeLlmHandle()
    : createLlmFromConfig(config, {
        tier: "deep",
        ...(opts.llmProvider ? { provider: opts.llmProvider } : {}),
        ...(opts.model ? { model: opts.model } : {}),
        ...(opts.baseUrl ? { baseUrl: opts.baseUrl } : {}),
      });

  const tradeDays = await enumerateTradingDays(api, opts.start, opts.end);
  const vetoThreshold = opts.vetoThreshold ? Number(opts.vetoThreshold) : 0.5;
  const logEvery = Number.parseInt(opts.logEvery ?? "5", 10);

  const graph = buildDailyCycleGraph({
    llmHandle,
    api,
    config,
    vetoThreshold,
  });

  console.log(pc.dim(`stage-1: ${tradeDays.length} trade days × 25 agents`));

  let completed = 0;
  let totalActions = 0;
  for (const tradeDate of tradeDays) {
    const tStart = Date.now();
    const initialState = makeInitialState(cohort, tradeDate);
    const final = (await graph.invoke(initialState)) as DailyCycleStateType;
    const actions = (final.portfolio_actions ?? []).map((a) => ({
      ticker: a.ticker,
      action: a.action,
      target_weight: a.target_weight,
      ...(a.holding_period ? { holding_period: a.holding_period } : {}),
      ...(a.dissent_notes ? { dissent_notes: a.dissent_notes } : {}),
    })) satisfies BacktestActionInput[];
    await api.backtestAppendActions(runId, tradeDate, actions);
    totalActions += actions.length;
    completed += 1;
    const elapsed = ((Date.now() - tStart) / 1000).toFixed(1);
    if (completed === 1 || completed % logEvery === 0 || completed === tradeDays.length) {
      console.log(
        pc.dim(
          `  [${completed}/${tradeDays.length}] ${tradeDate} (${elapsed}s, +${actions.length} actions)`,
        ),
      );
    }
  }
  await api.backtestCompleteRun(runId);
  console.log(pc.dim(`stage-1 cached ${totalActions} actions across ${tradeDays.length} days`));
}

// ---------------------------------------------------------------------------
// Pretty printer
// ---------------------------------------------------------------------------

function printMetrics(m: BacktestMetricsResult, totalElapsed: string): void {
  console.log(pc.cyan("\n=== Backtest metrics ==="));
  const fmtPct = (x: number) => `${(x * 100).toFixed(2)}%`;
  const fmtMoney = (x: number) => `¥${x.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

  const colourReturn = (x: number) => (x >= 0 ? pc.green(fmtPct(x)) : pc.red(fmtPct(x)));
  const colourSharpe = (x: number) =>
    x >= 1 ? pc.green(x.toFixed(2)) : x >= 0 ? x.toFixed(2) : pc.red(x.toFixed(2));

  console.log(`  ${pad("run_id", 22)} ${m.run_id}`);
  console.log(`  ${pad("cohort", 22)} ${m.cohort}`);
  console.log(`  ${pad("range", 22)} ${m.start_date} → ${m.end_date} (${m.n_trade_days} days)`);
  console.log(`  ${pad("benchmark", 22)} ${m.benchmark}`);
  console.log(pc.dim("  ────"));
  console.log(`  ${pad("total return", 22)} ${colourReturn(m.total_return)}`);
  console.log(`  ${pad("annualized return", 22)} ${colourReturn(m.annualized_return)}`);
  console.log(`  ${pad("benchmark return", 22)} ${colourReturn(m.benchmark_return)}`);
  console.log(`  ${pad("alpha (vs bench)", 22)} ${colourReturn(m.alpha)}`);
  console.log(pc.dim("  ────"));
  console.log(`  ${pad("Sharpe (annual)", 22)} ${colourSharpe(m.sharpe)}`);
  console.log(`  ${pad("max drawdown", 22)} ${pc.red(fmtPct(m.max_drawdown))}`);
  console.log(pc.dim("  ────"));
  console.log(`  ${pad("initial cash", 22)} ${fmtMoney(m.initial_cash)}`);
  console.log(`  ${pad("final value", 22)} ${fmtMoney(m.final_value)}`);

  console.log(pc.dim(`\n(total elapsed: ${totalElapsed}s)`));
}

// pad() imported from ../_format.js (§14 R-T2: shared CJK + ANSI-aware).

// Suppress unused for the BacktestRunInfo import (kept for future enrichment)
void ({} as BacktestRunInfo);

/**
 * Phase 3.5C CLI: ``pnpm dev backtest-fill``.
 *
 * Stage-1 of the two-stage backtest pipeline (Plan §11.4 design decision #7).
 *
 * Iterates trading days in [start, end], runs ``buildDailyCycleGraph`` for
 * each day with ``mode = backtest`` + ``as_of_date = trading_day``, captures
 * the resulting ``state.portfolio_actions``, and pushes them into the
 * ``backtest_actions`` SQLite table via the bridge. Phase 3.5D's qlib
 * runner then replays from this table (no LLM calls needed during
 * replay → fast + deterministic).
 *
 * Trading-day enumeration uses the bridge's calendar.list_trading_days
 * (PR #4 review hotfix #2) — skips A-share holidays so we don't waste
 * LLM calls on closed days.
 *
 * Cache key: (cohort, start_date, end_date, prompt_commit_hash). Re-running
 * with the same key short-circuits — operator-driven mutation evaluation
 * in Phase 4 reuses cached fills.
 */

import type { Command } from "commander";
import pc from "picocolors";
import type { DailyCycleStateType } from "../../agents/state.js";
import type { BacktestActionInput } from "../../bridge/index.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { buildDailyCycleGraph } from "../../graph/daily_cycle.js";
import { createLlmFromConfig, type LlmHandle } from "../../llm/factory.js";
import {
  buildFakeLlmHandle,
  enumerateTradingDays,
  makeInitialState,
} from "../_backtest_helpers.js";

interface BacktestFillOptions {
  cohort?: string;
  start: string;
  end: string;
  promptCommitHash?: string;
  fakeLlm?: boolean;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
  vetoThreshold?: string;
  /** Pretty progress every N trade days. */
  logEvery?: string;
}

export function registerBacktestFill(program: Command): void {
  program
    .command("backtest-fill")
    .description(
      "Stage-1 backtest cache fill: batch-runs daily-cycles for [--start, --end] " +
        "and writes portfolio_actions to the SQLite backtest cache.",
    )
    .requiredOption("--start <YYYY-MM-DD>", "first trade day")
    .requiredOption("--end <YYYY-MM-DD>", "last trade day (inclusive)")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option(
      "--prompt-commit-hash <hash>",
      "Tag identifying the prompt version (default 'unversioned')",
    )
    .option("--fake-llm", "Use the in-memory canned mock (zero LLM cost smoke)")
    .option("--llm-provider <name>", "Override LLM provider")
    .option("--model <name>", "Override LLM model")
    .option("--base-url <url>", "Override LLM base URL")
    .option(
      "--veto-threshold <num>",
      "CRO veto threshold (rejected/pool > this triggers replay; default 0.5)",
    )
    .option("--log-every <n>", "Print progress every N trade days (default 5)")
    .action(async (opts: BacktestFillOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";
      const promptCommitHash = opts.promptCommitHash ?? "unversioned";
      const logEvery = Number.parseInt(opts.logEvery ?? "5", 10);
      const vetoThreshold = opts.vetoThreshold ? Number(opts.vetoThreshold) : 0.5;

      try {
        await client.start();
        const config = await api.configGet();

        const llmHandle: LlmHandle = opts.fakeLlm
          ? buildFakeLlmHandle()
          : createLlmFromConfig(config, {
              tier: "deep",
              ...(opts.llmProvider ? { provider: opts.llmProvider } : {}),
              ...(opts.model ? { model: opts.model } : {}),
              ...(opts.baseUrl ? { baseUrl: opts.baseUrl } : {}),
            });

        // Use bridge calendar to skip A-share holidays (review #2)
        const tradeDays = await enumerateTradingDays(api, opts.start, opts.end);
        if (tradeDays.length === 0) {
          console.error(pc.red("error: no trade days in [start, end]"));
          process.exitCode = 1;
          return;
        }

        const runResult = await api.backtestCreateRun({
          cohort,
          start_date: opts.start,
          end_date: opts.end,
          prompt_commit_hash: promptCommitHash,
        });
        const runId = runResult.run_id;

        console.log(pc.bold(`\nbacktest-fill — cohort=${cohort} run_id=${runId}`));
        console.log(
          pc.dim(
            `range: ${opts.start} → ${opts.end} (${tradeDays.length} trade days) ` +
              `prompt=${promptCommitHash}`,
          ),
        );

        const graph = buildDailyCycleGraph({
          llmHandle,
          api,
          config,
          vetoThreshold,
        });

        let completed = 0;
        const totalStart = Date.now();
        let totalActions = 0;
        const errors: Array<{ date: string; err: string }> = [];

        for (const tradeDate of tradeDays) {
          const tStart = Date.now();
          try {
            const initialState: DailyCycleStateType = makeInitialState(cohort, tradeDate);
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
          } catch (err) {
            const msg = (err as Error).message;
            errors.push({ date: tradeDate, err: msg });
          }

          completed += 1;
          const elapsed = ((Date.now() - tStart) / 1000).toFixed(1);
          if (completed === 1 || completed % logEvery === 0 || completed === tradeDays.length) {
            const pct = ((completed / tradeDays.length) * 100).toFixed(1);
            console.log(
              pc.dim(`  [${completed}/${tradeDays.length} ${pct}%] ${tradeDate} (${elapsed}s)`),
            );
          }
        }

        const totalElapsed = ((Date.now() - totalStart) / 1000).toFixed(1);
        if (errors.length === 0) {
          await api.backtestCompleteRun(runId);
          console.log(
            pc.green(
              `\ndone in ${totalElapsed}s — ${tradeDays.length} days, ${totalActions} actions, run completed.`,
            ),
          );
        } else {
          console.log(
            pc.yellow(
              `\ncompleted ${completed}/${tradeDays.length} (${errors.length} errors) in ${totalElapsed}s — run NOT marked completed`,
            ),
          );
          console.log(pc.dim(`run_id=${runId}; rerun to retry failed days`));
          for (const e of errors.slice(0, 5)) {
            console.error(pc.red(`  ${e.date}: ${e.err}`));
          }
          if (errors.length > 5) console.error(pc.dim(`  ... ${errors.length - 5} more`));
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

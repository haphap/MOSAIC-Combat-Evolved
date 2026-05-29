/**
 * Phase 3E CLI: ``pnpm dev darwinian``.
 *
 * Reads ``darwinian.get_weights`` from the bridge and prints a per-agent
 * weight table sorted by weight descending (so top performers float to
 * the top, bottom-of-table at risk of low conviction). Quartile colouring
 * matches ``pnpm dev scorecard``.
 *
 * Use ``--compute`` to run ``darwinian.compute`` first, then read back
 * the just-written table — convenient one-liner for the daily cron.
 */

import type { Command } from "commander";
import pc from "picocolors";
import type { DarwinianWeightTable } from "../../bridge/index.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { pad } from "../_format.js";

interface DarwinianOptions {
  cohort?: string;
  date?: string;
  compute?: boolean;
  out?: string;
}

export function registerDarwinian(program: Command): void {
  program
    .command("darwinian")
    .description("Per-agent Darwinian weight table (rolling Sharpe → weight in [0.3, 2.5]).")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--date <YYYY-MM-DD>", "Look at a specific historical date (default: latest)")
    .option("--compute", "Run darwinian.compute first (uses today's date as as-of)")
    .option("--out <path>", "Write JSON to <path> instead of pretty-printing")
    .action(async (opts: DarwinianOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const cohort = opts.cohort ?? "cohort_default";

        if (opts.compute) {
          const today = opts.date ?? new Date().toISOString().slice(0, 10);
          const outcome = await api.darwinianCompute(cohort, today);
          console.log(
            pc.dim(
              `compute(${cohort}, ${today}) → written=${outcome.written} ` +
                `(uniform_fallback=${outcome.agents_uniform_fallback})`,
            ),
          );
        }

        const result = await api.darwinianGetWeights(cohort, opts.date ?? undefined);
        const weights = result.weights;

        if (opts.out) {
          const { writeFileSync } = await import("node:fs");
          writeFileSync(
            opts.out,
            JSON.stringify({ cohort, date: opts.date ?? null, weights }, null, 2),
            "utf-8",
          );
          console.log(pc.dim(`written to ${opts.out}`));
          return;
        }

        printDarwinianTable(cohort, opts.date, weights);
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
// Pretty printer
// ---------------------------------------------------------------------------

function printDarwinianTable(
  cohort: string,
  date: string | undefined,
  weights: DarwinianWeightTable,
): void {
  console.log(
    pc.bold(`Darwinian weights — cohort=${cohort}${date ? ` date=${date}` : " (latest)"}`),
  );

  const entries = Object.entries(weights);
  if (entries.length === 0) {
    console.log(
      pc.dim("\n(no weights computed yet — run `pnpm dev darwinian --compute` to populate)"),
    );
    console.log(pc.dim("Until then, autonomous_execution falls back to uniform 1.0."));
    return;
  }

  // Sort by weight descending; null quartile sinks
  entries.sort((a, b) => b[1].weight - a[1].weight);

  console.log(
    `\n  ${pad("agent", 22)} ${pad("weight", 8)} ${pad("sharpe30", 10)} ${pad("sharpe90", 10)} q`,
  );
  console.log(pc.dim(`  ${"─".repeat(22)} ${"─".repeat(8)} ${"─".repeat(10)} ${"─".repeat(10)} ─`));

  for (const [agent, w] of entries) {
    const colourer = w.quartile === 1 ? pc.green : w.quartile === 4 ? pc.red : (s: string) => s;
    const s30 = w.sharpe_30 === null ? "(n<5)" : w.sharpe_30.toFixed(2);
    const s90 = w.sharpe_90 === null ? "(n<5)" : w.sharpe_90.toFixed(2);
    const q = w.quartile === null ? "–" : String(w.quartile);
    console.log(
      `  ${pad(agent, 22)} ${pad(colourer(w.weight.toFixed(2)), 8)} ${pad(s30, 10)} ${pad(s90, 10)} ${colourer(q)}`,
    );
  }

  const sumWeights = entries.reduce((s, [, w]) => s + w.weight, 0);
  const meanWeight = sumWeights / entries.length;
  console.log(
    pc.dim(
      `\n  ${entries.length} agents, mean weight ${meanWeight.toFixed(2)}, ` +
        `range [${Math.min(...entries.map(([, w]) => w.weight)).toFixed(2)}, ` +
        `${Math.max(...entries.map(([, w]) => w.weight)).toFixed(2)}].`,
    ),
  );
}

// pad() imported from ../_format.js (§14 R-T2: shared CJK + ANSI-aware).

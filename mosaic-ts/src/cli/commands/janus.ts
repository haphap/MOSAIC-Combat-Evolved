/**
 * Phase 6 CLI: ``pnpm dev janus``.
 *
 * JANUS meta-weighting over the 7 PRISM regime cohorts:
 *   - run:     full daily cycle (weights + regime + blended recs), persisted
 *   - weights: cohort weights + 30d accuracy
 *   - regime:  regime signal (dominant cohort + concentration)
 *   - history: recent janus_runs (weight-drift over time)
 */

import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { pad } from "../_format.js";

interface DateOpts {
  date?: string;
  window?: string;
}

interface HistoryOpts {
  days?: string;
}

export function registerJanus(program: Command): void {
  const cmd = program
    .command("janus")
    .description("JANUS meta-weighting over the 7 PRISM regime cohorts (Phase 6).");

  cmd
    .command("run")
    .description("Full daily cycle: cohort weights + regime + blended recommendations.")
    .option("--date <date>", "As-of date (YYYY-MM-DD, default today)")
    .option("--window <n>", "Rolling accuracy window in days (default 30)")
    .action(async (opts: DateOpts) => {
      await withApi(async (api) => {
        const r = await api.janusRunDaily(dateParams(opts));
        console.log(pc.bold(`\njanus run -- ${r.date}`));
        printRegime(r.regime);
        printWeights(r.cohort_weights, r.cohort_accuracy);
        console.log(
          pc.cyan(
            `\n  blended: ${r.blended_recommendations.length} ` +
              `(${r.contested_tickers.length} contested)`,
          ),
        );
        for (const b of r.blended_recommendations.slice(0, 10)) {
          const flag = b.contested ? pc.yellow(" [contested]") : "";
          console.log(
            `  ${pad(b.direction, 6)} ${pad(b.ticker, 12)} ${b.blended_weight_pct.toFixed(1)}%${flag}`,
          );
        }
      });
    });

  cmd
    .command("weights")
    .description("Cohort weights + 30-day accuracy (no blend).")
    .option("--date <date>", "As-of date (YYYY-MM-DD, default today)")
    .option("--window <n>", "Rolling accuracy window in days (default 30)")
    .action(async (opts: DateOpts) => {
      await withApi(async (api) => {
        const r = await api.janusGetWeights(dateParams(opts));
        console.log(pc.bold(`\njanus weights -- ${r.date}`));
        printWeights(r.cohort_weights, r.cohort_accuracy);
      });
    });

  cmd
    .command("regime")
    .description("Regime signal (dominant cohort + concentration).")
    .option("--date <date>", "As-of date (YYYY-MM-DD, default today)")
    .option("--window <n>", "Rolling accuracy window in days (default 30)")
    .action(async (opts: DateOpts) => {
      await withApi(async (api) => {
        const r = await api.janusRegime(dateParams(opts));
        console.log(pc.bold(`\njanus regime -- ${r.date ?? ""}`));
        printRegime(r);
      });
    });

  cmd
    .command("history")
    .description("Recent JANUS runs (weight drift over time).")
    .option("--days <n>", "Number of runs to show (default 30)")
    .action(async (opts: HistoryOpts) => {
      await withApi(async (api) => {
        const days = opts.days ? Number.parseInt(opts.days, 10) : 30;
        const { history } = await api.janusGetHistory({ days });
        console.log(pc.bold(`\njanus history -- last ${days}`));
        if (history.length === 0) {
          console.log(pc.dim("  no runs recorded"));
          return;
        }
        console.log(
          pc.cyan(
            `\n  ${pad("date", 12)} ${pad("dominant", 18)} ${pad("conc", 8)} blended/contested`,
          ),
        );
        console.log(pc.dim(`  ${"─".repeat(56)}`));
        for (const h of history) {
          console.log(
            `  ${pad(h.date, 12)} ${pad(h.dominant_cohort ?? "-", 18)} ` +
              `${pad((h.concentration ?? 0).toFixed(3), 8)} ${h.n_blended}/${h.n_contested}`,
          );
        }
      });
    });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function dateParams(opts: DateOpts): { date?: string; window_days?: number } {
  return {
    ...(opts.date ? { date: opts.date } : {}),
    ...(opts.window ? { window_days: Number.parseInt(opts.window, 10) } : {}),
  };
}

function printRegime(r: {
  dominant_cohort: string | null;
  regime_label: string;
  concentration: number;
  concentration_state?: string;
}): void {
  console.log(
    `  regime: ${pc.cyan(r.regime_label)} ` +
      `(dominant=${r.dominant_cohort ?? "-"}, ` +
      `concentration=${r.concentration.toFixed(3)} ${r.concentration_state ?? ""})`,
  );
}

function printWeights(
  weights: Record<string, number>,
  accuracy: Record<string, { hit_rate: number; sharpe: number; n: number }>,
): void {
  console.log(
    pc.cyan(`\n  ${pad("cohort", 18)} ${pad("weight", 8)} ${pad("hit", 7)} ${pad("sharpe", 8)} n`),
  );
  console.log(pc.dim(`  ${"─".repeat(50)}`));
  const sorted = Object.entries(weights).sort((a, b) => b[1] - a[1]);
  for (const [cohort, w] of sorted) {
    const a = accuracy[cohort] ?? { hit_rate: 0, sharpe: 0, n: 0 };
    console.log(
      `  ${pad(cohort, 18)} ${pad(`${(w * 100).toFixed(1)}%`, 8)} ` +
        `${pad(`${(a.hit_rate * 100).toFixed(0)}%`, 7)} ${pad(a.sharpe.toFixed(2), 8)} ${a.n}`,
    );
  }
}

async function withApi(fn: (api: BridgeApi) => Promise<void>): Promise<void> {
  const client = new BridgeClient();
  const api = new BridgeApi(client);
  try {
    await client.start();
    await fn(api);
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
}

/**
 * Phase 3E CLI: ``pnpm dev scorecard``.
 *
 * Reads ``scorecard.list_skill`` from the bridge and prints a per-agent
 * skill table sorted by sharpe_window descending. Quartile 1 (top 25%) →
 * green, quartile 4 (bottom 25%) → red, in-between dim.
 *
 * The bridge handler computes mean_alpha_5d / sharpe_window on the fly from
 * scored recommendations. The window is whatever the caller asked for via
 * ``--since`` (all-time when omitted) — for canonical rolling-30-calendar-day
 * Sharpe used by autonomous_execution, see ``pnpm dev darwinian``.
 */

import type { Command } from "commander";
import pc from "picocolors";
import type { DarwinianWeightTable, SkillRow } from "../../bridge/index.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { pad } from "../_format.js";

interface ScorecardOptions {
  cohort?: string;
  since?: string;
  out?: string;
}

export function registerScorecard(program: Command): void {
  program
    .command("scorecard")
    .description(
      "Per-agent skill table (mean alpha_5d + sharpe_window) from scored recommendations.",
    )
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--since <date>", "Restrict to rows with date >= YYYY-MM-DD (default: all-time)")
    .option("--out <path>", "Write JSON to <path> instead of pretty-printing")
    .action(async (opts: ScorecardOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const cohort = opts.cohort ?? "cohort_default";
        const result = await api.scorecardListSkill(cohort, opts.since ?? undefined);
        const rows = result.rows;
        // Also fetch the canonical Darwinian weights for the same cohort so
        // the table can show the quartile colour annotation.
        const w = await api.darwinianGetWeights(cohort);

        if (opts.out) {
          const { writeFileSync } = await import("node:fs");
          writeFileSync(
            opts.out,
            JSON.stringify(
              { cohort, since: opts.since ?? null, skill: rows, weights: w.weights },
              null,
              2,
            ),
            "utf-8",
          );
          console.log(pc.dim(`written to ${opts.out}`));
          return;
        }
        printScorecardTable(cohort, opts.since, rows, w.weights);
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

function printScorecardTable(
  cohort: string,
  since: string | undefined,
  rows: SkillRow[],
  weights: DarwinianWeightTable,
): void {
  console.log(pc.bold(`MOSAIC scorecard — cohort=${cohort}${since ? ` since=${since}` : ""}`));

  if (rows.length === 0) {
    console.log(pc.dim("\n(no scored recommendations yet — run scorecard.score_pending first)"));
    return;
  }

  // Sort by sharpe_window descending (None / null sinks to bottom).
  const sorted = [...rows].sort((a, b) => {
    const sa = a.sharpe_window;
    const sb = b.sharpe_window;
    if (sa === null && sb === null) return 0;
    if (sa === null) return 1;
    if (sb === null) return -1;
    return sb - sa;
  });

  console.log(
    `\n  ${pad("agent", 22)} ${pad("n_obs", 6)} ${pad("mean α5d", 10)} ${pad("sharpe", 8)} ${pad("weight", 8)} q`,
  );
  console.log(
    pc.dim(
      `  ${"─".repeat(22)} ${"─".repeat(6)} ${"─".repeat(10)} ${"─".repeat(8)} ${"─".repeat(8)} ─`,
    ),
  );

  for (const r of sorted) {
    const w = weights[r.agent];
    const quartile = w?.quartile ?? null;
    const colourer = quartile === 1 ? pc.green : quartile === 4 ? pc.red : (s: string) => s;
    const sharpe = r.sharpe_window === null ? "(n<5)" : r.sharpe_window.toFixed(2);
    const weight = w ? w.weight.toFixed(2) : pc.dim("–");
    const q = quartile === null ? "–" : String(quartile);
    const meanAlphaPct = `${(r.mean_alpha_5d * 100).toFixed(2)}%`;
    console.log(
      `  ${pad(r.agent, 22)} ${pad(String(r.n_obs), 6)} ${pad(meanAlphaPct, 10)} ${pad(colourer(sharpe), 8)} ${pad(weight, 8)} ${colourer(q)}`,
    );
  }

  const totalObs = sorted.reduce((s, r) => s + r.n_obs, 0);
  const ranked = sorted.filter((r) => r.sharpe_window !== null).length;
  console.log(
    pc.dim(
      `\n  ${sorted.length} agents, ${totalObs} scored observations, ${ranked} with sufficient data (n≥5).`,
    ),
  );
}

// pad() imported from ../_format.js (§14 R-T2: shared CJK + ANSI-aware).

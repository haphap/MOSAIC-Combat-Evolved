/**
 * Phase 5 CLI: ``pnpm dev prism``.
 *
 * Historical PRISM audit CLI. The retired prompt writer is intentionally not
 * exposed; only read-only cohort history remains available.
 */

import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { pad } from "../_format.js";

interface StatusOptions {
  cohort: string;
}

interface CompareOptions {
  metric?: string;
  since?: string;
}

export function registerPrism(program: Command): void {
  const cmd = program
    .command("prism")
    .description("Read-only audit views for historical PRISM cohort runs.");

  // ── prism list ────────────────────────────────────────────────────────

  cmd
    .command("list")
    .description("List all 7 cohorts with status info.")
    .action(async () => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);

      try {
        await client.start();
        console.log(pc.bold("\nPRISM cohorts:\n"));

        const { cohorts } = await api.prismListCohorts();

        console.log(
          pc.cyan(
            `  ${pad("name", 18)} ${pad("start", 12)} ${pad("end", 12)} ` +
              `${pad("branch", 8)} ${pad("runs", 6)} ${pad("last_run", 12)} description`,
          ),
        );
        console.log(pc.dim(`  ${"─".repeat(90)}`));

        for (const c of cohorts) {
          const branchIcon = c.has_branch ? pc.green("yes") : pc.dim("no");
          console.log(
            `  ${pad(c.name, 18)} ${pad(c.start, 12)} ${pad(c.end, 12)} ` +
              `${pad(branchIcon, 8)} ${pad(String(c.n_runs), 6)} ` +
              `${pad(c.last_run_date ?? "-", 12)} ${c.description}`,
          );
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── prism status ──────────────────────────────────────────────────────

  cmd
    .command("status")
    .description("Get status for a specific cohort.")
    .requiredOption("--cohort <name>", "Cohort name")
    .action(async (opts: StatusOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);

      try {
        await client.start();
        console.log(pc.bold(`\nprism status -- cohort=${opts.cohort}\n`));

        const status = await api.prismCohortStatus({ cohort_name: opts.cohort });

        console.log(`  cohort:         ${pc.cyan(status.cohort)}`);
        console.log(`  n_runs:         ${status.n_runs}`);
        console.log(`  n_mutations:    ${status.n_mutations}`);
        console.log(`  last_date:      ${status.last_date ?? pc.dim("none")}`);
        console.log(
          `  sharpe_latest:  ${status.sharpe_latest != null ? status.sharpe_latest.toFixed(4) : pc.dim("n/a")}`,
        );
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── prism compare ─────────────────────────────────────────────────────

  cmd
    .command("compare")
    .description("Compare cohorts by metric.")
    .option("--metric <name>", "Metric to compare (default sharpe)")
    .option("--since <date>", "Filter runs since date (YYYY-MM-DD)")
    .action(async (opts: CompareOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);

      try {
        await client.start();
        console.log(
          pc.bold(
            `\nprism compare -- metric=${opts.metric ?? "sharpe"}` +
              `${opts.since ? ` since=${opts.since}` : ""}`,
          ),
        );

        const { comparisons } = await api.prismCompareCohorts({
          ...(opts.metric ? { metric: opts.metric } : {}),
          ...(opts.since ? { since: opts.since } : {}),
        });

        console.log(
          pc.cyan(
            `\n  ${pad("cohort", 18)} ${pad("runs", 6)} ${pad("mutations", 10)} ` +
              `${pad("kept", 6)} ${pad("reverted", 9)} latest_date`,
          ),
        );
        console.log(pc.dim(`  ${"─".repeat(65)}`));

        for (const c of comparisons) {
          console.log(
            `  ${pad(c.cohort, 18)} ${pad(String(c.n_runs), 6)} ` +
              `${pad(String(c.n_mutations), 10)} ${pad(String(c.n_kept), 6)} ` +
              `${pad(String(c.n_reverted), 9)} ${c.latest_date ?? "-"}`,
          );
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function handleError(err: unknown, client: BridgeClient): void {
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
}

// pad() imported from ../_format.js (§14 R-T2: shared CJK + ANSI-aware).

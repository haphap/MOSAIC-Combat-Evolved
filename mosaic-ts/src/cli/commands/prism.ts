/**
 * Phase 5 CLI: ``pnpm dev prism``.
 *
 * Subcommands:
 *   - list: show all 7 cohorts with status
 *   - train: initiate training for a cohort
 *   - status: get cohort training status
 *   - compare: compare cohorts by metric
 */

import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { createLlmFromConfig } from "../../llm/factory.js";
import { type CohortTrainingResult, runCohortTraining } from "../../prism/trainer.js";
import { buildFakeLlmHandle } from "../_backtest_helpers.js";

interface TrainOptions {
  cohort?: string;
  all?: boolean;
  start?: string;
  end?: string;
  dryRun?: boolean;
  fakeLlm?: boolean;
  maxConcurrent?: string;
  maxMutations?: string;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
}

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
    .description("PRISM 7-cohort training orchestration (Phase 5).");

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

  // ── prism train ───────────────────────────────────────────────────────

  cmd
    .command("train")
    .description("Train a cohort (or all 7): layers sequential, ≤N agents concurrent per layer.")
    .option("--cohort <name>", "Cohort name to train")
    .option("--all", "Train all 7 cohorts sequentially")
    .option("--start <date>", "Override start date (YYYY-MM-DD)")
    .option("--end <date>", "Override end date (YYYY-MM-DD)")
    .option("--dry-run", "Select + generate only; no branch/DB side effects")
    .option("--fake-llm", "Use in-memory mock LLM (zero cost)")
    .option("--max-concurrent <n>", "Max agents trained concurrently per layer (default 5)")
    .option("--max-mutations <n>", "Mutations attempted per agent (default 1)")
    .option("--llm-provider <name>", "Override LLM provider")
    .option("--model <name>", "Override LLM model")
    .option("--base-url <url>", "Override LLM base URL")
    .action(async (opts: TrainOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);

      if (!opts.all && !opts.cohort) {
        console.error(pc.red("error: provide --cohort <name> or --all"));
        process.exitCode = 1;
        return;
      }

      try {
        await client.start();
        const config = await api.configGet();
        const llmHandle = opts.fakeLlm
          ? buildFakeLlmHandle()
          : createLlmFromConfig(config, {
              tier: "deep",
              ...(opts.llmProvider ? { provider: opts.llmProvider } : {}),
              ...(opts.model ? { model: opts.model } : {}),
              ...(opts.baseUrl ? { baseUrl: opts.baseUrl } : {}),
            });

        const maxAgentsConcurrent = opts.maxConcurrent
          ? Number.parseInt(opts.maxConcurrent, 10)
          : 5;
        const maxMutationsPerAgent = opts.maxMutations ? Number.parseInt(opts.maxMutations, 10) : 1;
        const dryRun = opts.dryRun ?? false;

        // Resolve the cohort list.
        let cohorts: string[];
        if (opts.all) {
          const { cohorts: list } = await api.prismListCohorts();
          cohorts = list.map((c) => c.name);
        } else {
          cohorts = [opts.cohort as string];
        }

        console.log(
          pc.bold(
            `\nprism train -- cohorts=[${cohorts.join(", ")}] ` +
              `max-concurrent=${maxAgentsConcurrent}${dryRun ? " [DRY RUN]" : ""}` +
              `${opts.fakeLlm ? " [FAKE LLM]" : ""}`,
          ),
        );

        const common = {
          maxAgentsConcurrent,
          maxMutationsPerAgent,
          dryRun,
          ...(opts.fakeLlm ? { fakeLlm: true } : {}),
          deps: { llm: llmHandle.llm, api },
          onLog: (msg: string) => console.log(pc.dim(`  ${msg}`)),
        };

        // Per-cohort: create branch + run shell, train, then close the ledger.
        const train = async (cohort: string): Promise<CohortTrainingResult> => {
          let runId: number | undefined;
          if (!dryRun) {
            const shell = await api.prismTrainCohort({ cohort_name: cohort });
            runId = shell.run_id;
            if (runId != null) console.log(pc.dim(`  ${cohort}: run_id=${runId}`));
          }
          const result = await runCohortTraining({ cohort, ...common });
          if (!dryRun && runId != null) {
            const llmCalls = countAgents(result);
            await api.prismCompleteCohortRun({ run_id: runId, llm_calls: llmCalls });
          }
          return result;
        };

        const results = opts.all
          ? // runPrismTraining keeps cohorts sequential; but we need the
            // shell+complete ledger per cohort, so train() wraps each.
            await sequential(cohorts, train)
          : [await train(cohorts[0] as string)];

        printTrainingResults(results);
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

function pad(s: string, width: number): string {
  return s.length >= width ? s : s + " ".repeat(width - s.length);
}

/** Run an async fn over items strictly in sequence (cohorts never overlap). */
async function sequential<T, R>(
  items: ReadonlyArray<T>,
  fn: (item: T) => Promise<R>,
): Promise<R[]> {
  const out: R[] = [];
  for (const item of items) out.push(await fn(item));
  return out;
}

/** Total agent training steps across all layers of a cohort result. */
function countAgents(result: CohortTrainingResult): number {
  return result.layers.reduce((n, l) => n + l.agents.length, 0);
}

const STATUS_COLOR: Record<string, (s: string) => string> = {
  kept: pc.green,
  reverted: pc.red,
  error: pc.red,
};

function printTrainingResults(results: ReadonlyArray<CohortTrainingResult>): void {
  for (const r of results) {
    console.log(pc.cyan(`\n=== ${r.cohort} ===`));
    for (const layer of r.layers) {
      const counts: Record<string, number> = {};
      for (const a of layer.agents) counts[a.status] = (counts[a.status] ?? 0) + 1;
      const summary = Object.entries(counts)
        .map(([s, n]) => `${(STATUS_COLOR[s] ?? pc.yellow)(s)}=${n}`)
        .join(" ");
      console.log(`  ${pad(layer.layer, 14)} ${layer.agents.length} agents  ${summary}`);
    }
  }
}

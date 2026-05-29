/**
 * Phase 4F CLI: ``pnpm dev autoresearch``.
 *
 * Subcommands:
 *   - trigger: run the autoresearch mutation cycle
 *   - evaluate: evaluate pending mutations
 *   - log: view autoresearch event log
 *   - branches: list active feature branches
 *   - revert: manually revert a modification
 */

import type { Command } from "commander";
import pc from "picocolors";
import { runAutoresearchCycle } from "../../autoresearch/orchestrator.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { createLlmFromConfig } from "../../llm/factory.js";
import { buildFakeLlmHandle } from "../_backtest_helpers.js";

interface TriggerOptions {
  cohort?: string;
  agent?: string;
  max?: string;
  dryRun?: boolean;
  fakeLlm?: boolean;
  evalDays?: string;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
}

interface EvaluateOptions {
  cohort?: string;
}

interface LogOptions {
  cohort?: string;
  days?: string;
}

interface BranchesOptions {
  cohort?: string;
}

interface RevertOptions {
  versionId: string;
}

export function registerAutoresearch(program: Command): void {
  const cmd = program
    .command("autoresearch")
    .description("Autoresearch prompt mutation system (Phase 4E/4F).");

  // ── autoresearch trigger ──────────────────────────────────────────────

  cmd
    .command("trigger")
    .description("Run the autoresearch mutation cycle: trigger + mutate + commit + evaluate.")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--agent <name>", "Force a specific agent (skip constraint selection)")
    .option("--max <n>", "Max mutations per cycle (default 1)")
    .option("--dry-run", "Generate mutation but do not commit")
    .option("--fake-llm", "Use in-memory mock LLM (zero cost)")
    .option("--eval-days <n>", "Evaluation window in trading days (default 60)")
    .option("--llm-provider <name>", "Override LLM provider")
    .option("--model <name>", "Override LLM model")
    .option("--base-url <url>", "Override LLM base URL")
    .action(async (opts: TriggerOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";

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

        const maxMutations = opts.max ? Number.parseInt(opts.max, 10) : 1;
        const evalDays = opts.evalDays ? Number.parseInt(opts.evalDays, 10) : 60;

        console.log(
          pc.bold(
            `\nautoresearch trigger -- cohort=${cohort} max=${maxMutations}` +
              `${opts.dryRun ? " [DRY RUN]" : ""}`,
          ),
        );

        const result = await runAutoresearchCycle({
          cohort,
          evalDays,
          maxMutations,
          dryRun: opts.dryRun ?? false,
          ...(opts.agent ? { forceAgent: opts.agent } : {}),
          deps: { llm: llmHandle.llm, api },
          onLog: (msg) => console.log(pc.dim(`  ${msg}`)),
        });

        // Print results
        console.log(pc.cyan(`\n=== Results (${result.mutations.length} mutations) ===`));
        for (const m of result.mutations) {
          const statusColor =
            m.status === "kept"
              ? pc.green
              : m.status === "reverted"
                ? pc.red
                : m.status === "error"
                  ? pc.red
                  : pc.yellow;
          console.log(
            `  ${pad(m.agent, 20)} ${statusColor(pad(m.status, 12))} ` +
              `v${m.version_id}` +
              (m.delta_sharpe != null ? ` delta=${m.delta_sharpe.toFixed(4)}` : "") +
              (m.summary ? ` -- ${m.summary}` : "") +
              (m.error ? ` [${m.error}]` : ""),
          );
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── autoresearch evaluate ─────────────────────────────────────────────

  cmd
    .command("evaluate")
    .description("Evaluate pending mutations (compute delta Sharpe + decide keep/revert).")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .action(async (opts: EvaluateOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";

      try {
        await client.start();
        console.log(pc.bold(`\nautoresearch evaluate -- cohort=${cohort}`));

        const { results } = await api.autoresearchEvaluatePending({ cohort });

        if (results.length === 0) {
          console.log(pc.dim("  no pending mutations to evaluate"));
        } else {
          console.log(pc.cyan(`\n  ${pad("version_id", 12)} ${pad("status", 12)} delta_sharpe`));
          console.log(pc.dim(`  ${"─".repeat(44)}`));
          for (const r of results) {
            const statusColor =
              r.status === "kept" ? pc.green : r.status === "reverted" ? pc.red : pc.yellow;
            console.log(
              `  ${pad(String(r.version_id), 12)} ${statusColor(pad(r.status, 12))} ` +
                (r.delta_sharpe != null ? r.delta_sharpe.toFixed(4) : "n/a"),
            );
          }
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── autoresearch log ──────────────────────────────────────────────────

  cmd
    .command("log")
    .description("View autoresearch event log.")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--days <n>", "Show entries from the last N days (default 7)")
    .action(async (opts: LogOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";
      const days = opts.days ? Number.parseInt(opts.days, 10) : 7;

      try {
        await client.start();
        console.log(pc.bold(`\nautoresearch log -- cohort=${cohort} days=${days}`));

        const { entries } = await api.autoresearchGetLog({ cohort, days });

        if (entries.length === 0) {
          console.log(pc.dim("  no log entries"));
        } else {
          console.log(
            pc.cyan(`\n  ${pad("time", 20)} ${pad("event", 12)} ${pad("agent", 16)} detail`),
          );
          console.log(pc.dim(`  ${"─".repeat(70)}`));
          for (const e of entries) {
            const time = e.created_at.slice(0, 19).replace("T", " ");
            console.log(
              `  ${pad(time, 20)} ${pad(e.event, 12)} ${pad(e.agent ?? "-", 16)} ${e.detail ?? ""}`,
            );
          }
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── autoresearch branches ─────────────────────────────────────────────

  cmd
    .command("branches")
    .description("List active autoresearch feature branches.")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .action(async (opts: BranchesOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";

      try {
        await client.start();
        console.log(pc.bold(`\nautoresearch branches -- cohort=${cohort}`));

        const { branches } = await api.autoresearchListActiveBranches({ cohort });

        if (branches.length === 0) {
          console.log(pc.dim("  no active branches"));
        } else {
          console.log(
            pc.cyan(`\n  ${pad("id", 6)} ${pad("agent", 16)} ${pad("branch", 36)} created`),
          );
          console.log(pc.dim(`  ${"─".repeat(74)}`));
          for (const b of branches) {
            const time = b.created_at.slice(0, 19).replace("T", " ");
            console.log(
              `  ${pad(String(b.id), 6)} ${pad(b.agent, 16)} ${pad(b.branch_name, 36)} ${time}`,
            );
          }
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── autoresearch revert ───────────────────────────────────────────────

  cmd
    .command("revert")
    .description("Manually revert a specific modification by version ID.")
    .requiredOption("--version-id <id>", "Version ID to revert")
    .action(async (opts: RevertOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const versionId = Number.parseInt(opts.versionId, 10);

      try {
        await client.start();
        console.log(pc.bold(`\nautoresearch revert -- version_id=${versionId}`));

        const result = await api.autoresearchRevertModification({ version_id: versionId });

        if (result.ok) {
          console.log(pc.green(`  version ${versionId} reverted successfully`));
        } else {
          console.log(pc.yellow(`  revert returned ok=false for version ${versionId}`));
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

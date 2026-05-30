/**
 * Phase 7 CLI: ``pnpm dev mirofish``.
 *
 * MiroFish synthetic-futures forward training:
 *   - generate: print the Monte-Carlo scenario set
 *   - train:    scenario → agent rec → score → record (isolated ledger)
 *   - history:  recent mirofish_runs
 */

import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { createLlmFromConfig } from "../../llm/factory.js";
import { runMirofishTraining } from "../../mirofish/trainer.js";
import { buildFakeLlmHandle } from "../_backtest_helpers.js";
import { pad } from "../_format.js";

const DEFAULT_AGENTS = ["druckenmiller", "ackman", "aschenbrenner", "baker"];

interface GenerateOpts {
  days?: string;
  seed?: string;
  print?: boolean;
  reflexive?: boolean;
  engine?: string;
  swarm?: boolean;
}

interface TrainOpts {
  days?: string;
  seed?: string;
  agents?: string;
  dryRun?: boolean;
  fakeLlm?: boolean;
  reflexive?: boolean;
  engine?: string;
  swarm?: boolean;
  scorer?: string;
  pathAware?: boolean;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
}

interface HistoryOpts {
  days?: string;
}

export function registerMirofish(program: Command): void {
  const cmd = program
    .command("mirofish")
    .description("MiroFish synthetic-futures forward training (Phase 7).");

  cmd
    .command("generate")
    .description("Generate + print the Monte-Carlo scenario set.")
    .option("--days <n>", "Days to simulate (default 30)")
    .option("--seed <n>", "RNG seed for reproducibility")
    .option("--print", "Print scenario detail")
    .option("--reflexive", "Apply the reflexive actor overlay (price↔behavior feedback)")
    .option("--engine <name>", "Scenario engine: montecarlo (default) | swarm (agent-to-agent)")
    .option("--swarm", "Shorthand for --engine swarm (Phase 7M.1 interaction engine)")
    .action(async (opts: GenerateOpts) => {
      await withApi(async (api) => {
        const engine = resolveEngine(opts);
        const { scenarios } = await api.mirofishGenerateScenarios({
          ...(opts.days ? { num_days: Number.parseInt(opts.days, 10) } : {}),
          ...(opts.seed ? { seed: Number.parseInt(opts.seed, 10) } : {}),
          ...(opts.reflexive ? { reflexivity: true } : {}),
          ...(engine ? { engine } : {}),
        });
        console.log(
          pc.bold(
            `\nmirofish scenarios (${scenarios.length})${engine ? ` [engine=${engine}]` : ""}`,
          ),
        );
        for (const s of scenarios) {
          const csi = s.final_state.csi300_return;
          console.log(
            `  ${pad(s.scenario_type, 11)} p=${s.probability.toFixed(2)} ` +
              `${pad(s.final_state.regime, 9)} CSI300 ${(csi * 100).toFixed(1)}%`,
          );
          if (opts.print) {
            for (const [t, p] of Object.entries(s.price_paths)) {
              console.log(pc.dim(`      ${pad(t, 12)} ${(p.cumulative_return * 100).toFixed(1)}%`));
            }
          }
        }
      });
    });

  cmd
    .command("train")
    .description("Forward-train agents on simulated scenarios (isolated ledger).")
    .option("--days <n>", "Days to simulate (default 30)")
    .option("--seed <n>", "RNG seed")
    .option("--agents <list>", "Comma-separated agents (default 4 superinvestors)")
    .option("--dry-run", "Score but do not persist")
    .option("--fake-llm", "Deterministic canned recommendations (zero cost)")
    .option("--reflexive", "Apply the reflexive actor overlay (price↔behavior feedback)")
    .option("--engine <name>", "Scenario engine: montecarlo (default) | swarm")
    .option("--swarm", "Shorthand for --engine swarm (Phase 7M.1 interaction engine)")
    .option("--scorer <name>", "Scoring: terminal (default) | path_aware (drawdown-penalised)")
    .option("--path-aware", "Shorthand for --scorer path_aware (score the equity curve)")
    .option("--llm-provider <name>", "Override LLM provider")
    .option("--model <name>", "Override LLM model")
    .option("--base-url <url>", "Override LLM base URL")
    .action(async (opts: TrainOpts) => {
      await withApi(async (api) => {
        const config = await api.configGet();
        const llmHandle = opts.fakeLlm
          ? buildFakeLlmHandle()
          : createLlmFromConfig(config, {
              tier: "deep",
              ...(opts.llmProvider ? { provider: opts.llmProvider } : {}),
              ...(opts.model ? { model: opts.model } : {}),
              ...(opts.baseUrl ? { baseUrl: opts.baseUrl } : {}),
            });
        const agents = opts.agents ? opts.agents.split(",").map((a) => a.trim()) : DEFAULT_AGENTS;
        console.log(
          pc.bold(
            `\nmirofish train -- agents=[${agents.join(", ")}]` +
              `${opts.dryRun ? " [DRY RUN]" : ""}${opts.fakeLlm ? " [FAKE LLM]" : ""}`,
          ),
        );
        const engine = resolveEngine(opts);
        const scorer = resolveScorer(opts);
        const result = await runMirofishTraining({
          ...(opts.days ? { numDays: Number.parseInt(opts.days, 10) } : {}),
          ...(opts.seed ? { seed: Number.parseInt(opts.seed, 10) } : {}),
          agents,
          dryRun: opts.dryRun ?? false,
          ...(opts.fakeLlm ? { fakeLlm: true } : {}),
          ...(opts.reflexive ? { reflexive: true } : {}),
          ...(engine ? { engine } : {}),
          ...(scorer ? { scorer } : {}),
          deps: { llm: llmHandle.llm, api },
          onLog: (m) => console.log(pc.dim(`  ${m}`)),
        });
        console.log(pc.cyan(`\n  ${pad("agent", 18)} ${pad("avg_score", 10)} scenarios`));
        console.log(pc.dim(`  ${"─".repeat(44)}`));
        for (const a of result.agents) {
          const color = a.avg_score >= 0.6 ? pc.green : a.avg_score < 0.4 ? pc.red : pc.yellow;
          console.log(
            `  ${pad(a.agent, 18)} ${color(pad(a.avg_score.toFixed(3), 10))} ${a.scenario_scores.length}`,
          );
        }
      });
    });

  cmd
    .command("history")
    .description("Recent MiroFish training runs.")
    .option("--days <n>", "Rows to show (default 30)")
    .action(async (opts: HistoryOpts) => {
      await withApi(async (api) => {
        const days = opts.days ? Number.parseInt(opts.days, 10) : 30;
        const { history } = await api.mirofishGetHistory({ days });
        console.log(pc.bold(`\nmirofish history -- last ${days}`));
        if (history.length === 0) {
          console.log(pc.dim("  no runs recorded"));
          return;
        }
        console.log(
          pc.cyan(`\n  ${pad("date", 12)} ${pad("agent", 18)} ${pad("type", 10)} avg_score`),
        );
        console.log(pc.dim(`  ${"─".repeat(52)}`));
        for (const h of history) {
          console.log(
            `  ${pad(h.date, 12)} ${pad(h.agent, 18)} ${pad(h.scenario_type, 10)} ` +
              `${h.avg_score != null ? h.avg_score.toFixed(3) : "n/a"}`,
          );
        }
      });
    });
}

/** Resolve engine from --swarm shorthand or --engine; undefined → server default. */
function resolveEngine(opts: {
  engine?: string;
  swarm?: boolean;
}): "montecarlo" | "swarm" | undefined {
  if (opts.swarm) return "swarm";
  if (opts.engine === "montecarlo" || opts.engine === "swarm") return opts.engine;
  return undefined;
}

/** Resolve scorer from --path-aware shorthand or --scorer; undefined → server default. */
function resolveScorer(opts: {
  scorer?: string;
  pathAware?: boolean;
}): "terminal" | "path_aware" | undefined {
  if (opts.pathAware) return "path_aware";
  if (opts.scorer === "terminal" || opts.scorer === "path_aware") return opts.scorer;
  return undefined;
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

/**
 * Phase 2F MVP CLI command: ``pnpm dev daily-cycle``.
 *
 * Drives one full L1→L2→L3→L4 cycle via the composite graph from
 * ``graph/daily_cycle.ts``. Covers two LLM modes:
 *
 *   1. ``--fake-llm``: in-memory canned mock; sidecar + bridge tools are
 *      still real (FRED / Tushare). Validates wiring without LLM cost.
 *   2. Default: real LLM via createLlmFromConfig (lemonade by default
 *      when LEMONADE_BASE_URL is set; otherwise the bridge config's
 *      provider).
 *
 * The CLI surface is intentionally thin — every layer's logic is already
 * unit-tested in test/{macro,sector,superinvestor,decision,daily_cycle}*.
 */

import { writeFileSync } from "node:fs";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import type { BaseMessage } from "@langchain/core/messages";
import { AIMessage } from "@langchain/core/messages";
import type { Command } from "commander";
import pc from "picocolors";
import type { DailyCycleStateType } from "../../agents/state.js";
import type { PortfolioAction } from "../../agents/types.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { buildDailyCycleGraph } from "../../graph/daily_cycle.js";
import { createLlmFromConfig, type LlmHandle } from "../../llm/factory.js";

interface DailyCycleOptions {
  cohort?: string;
  date?: string;
  fakeLlm?: boolean;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
  out?: string;
  vetoThreshold?: string;
}

export function registerDailyCycle(program: Command): void {
  program
    .command("daily-cycle")
    .description(
      "Run one MOSAIC daily cycle: L1 macro → L2 sector → L3 superinvestor → L4 decision. " +
        "Use --fake-llm for zero-cost smoke; default uses the bridge's configured LLM provider.",
    )
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--date <YYYY-MM-DD>", "as_of_date (default today)")
    .option("--fake-llm", "Use a canned mock LLM (still calls real bridge tools)")
    .option("--llm-provider <name>", "Override LLM provider from bridge config")
    .option("--model <name>", "Override LLM model id (e.g. local Lemonade Qwen)")
    .option("--base-url <url>", "Override LLM base URL (e.g. http://127.0.0.1:8020/api/v0)")
    .option("--out <path>", "Write the final state JSON to <path> instead of pretty-printing")
    .option(
      "--veto-threshold <num>",
      "CRO veto threshold; rejection rate > this triggers replay (default 0.5)",
    )
    .action(async (opts: DailyCycleOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
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

        console.log(
          pc.dim(
            `provider=${llmHandle.provider} model=${llmHandle.model}` +
              (llmHandle.baseUrl ? ` base=${llmHandle.baseUrl}` : "") +
              (opts.fakeLlm ? " (fake-llm)" : ""),
          ),
        );

        const cohort = opts.cohort ?? config.active_cohort ?? "cohort_default";
        const asOfDate = opts.date ?? new Date().toISOString().slice(0, 10);
        const vetoThreshold = opts.vetoThreshold ? Number(opts.vetoThreshold) : 0.5;

        const graph = buildDailyCycleGraph({
          llmHandle,
          api,
          config,
          vetoThreshold,
        });

        const initialState: DailyCycleStateType = {
          messages: [],
          active_cohort: cohort,
          as_of_date: asOfDate,
          mode: "live",
          trace_id: `cli-${Date.now()}`,
          continuity_context: {},
          lesson_context: {},
          method_context: {},
          layer1_outputs: {},
          layer1_consensus: null,
          layer2_outputs: {},
          layer2_consensus: null,
          layer3_outputs: {},
          layer4_outputs: {
            cro: null,
            alpha_discovery: null,
            autonomous_execution: null,
            cio: null,
          },
          portfolio_actions: [],
          llm_calls: [],
        };

        console.log(pc.bold(`\nMOSAIC daily cycle — cohort=${cohort} date=${asOfDate}`));
        const t0 = Date.now();
        const final = (await graph.invoke(initialState)) as DailyCycleStateType;
        const elapsed = ((Date.now() - t0) / 1000).toFixed(1);

        if (opts.out) {
          // ``state.messages`` are LangChain BaseMessage class instances whose
          // default JSON serialisation surfaces internal fields (lc_kwargs,
          // lc_namespace, ...) that aren't useful downstream. Drop them and
          // surface only the prose content for any consumer that wants it.
          const dump = {
            ...final,
            messages: final.messages.map((m) => ({
              role: m.getType?.() ?? "unknown",
              content: typeof m.content === "string" ? m.content : JSON.stringify(m.content),
            })),
          };
          writeFileSync(opts.out, JSON.stringify(dump, null, 2), "utf-8");
          console.log(pc.dim(`\nstate written to ${opts.out} (${elapsed}s)`));
        } else {
          printCycleSummary(final, elapsed);
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
// Pretty printer (4 layer summary blocks + portfolio_actions table)
// ---------------------------------------------------------------------------

function printCycleSummary(state: DailyCycleStateType, elapsed: string): void {
  console.log(pc.cyan("\n=== Layer 1 — macro regime ==="));
  const regime = state.layer1_consensus;
  if (regime) {
    console.log(
      `stance=${pc.bold(regime.stance)} confidence=${regime.confidence.toFixed(2)} ` +
        `score=${regime.layer_1_consensus_score.toFixed(2)}`,
    );
    for (const d of regime.key_drivers.slice(0, 5)) console.log(`  • ${d}`);
  } else {
    console.log(pc.dim("(no consensus)"));
  }
  console.log(pc.dim(`  agents: ${Object.keys(state.layer1_outputs).join(", ") || "(none)"}`));

  console.log(pc.cyan("\n=== Layer 2 — sector picks ==="));
  const sectors = state.layer2_outputs ?? {};
  if (Object.keys(sectors).length === 0) {
    console.log(pc.dim("(no sector outputs)"));
  }
  for (const [id, out] of Object.entries(sectors)) {
    if (out.agent === "relationship_mapper") {
      const chains = out.supply_chains.map((c) => c.name).join(" | ");
      console.log(
        `${pc.bold(id)}  conf=${out.confidence.toFixed(2)}  chains=${chains || "(none)"}`,
      );
    } else {
      const longs = out.longs
        .slice(0, 3)
        .map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`)
        .join(", ");
      console.log(
        `${pc.bold(id)}  score=${out.sector_score.toFixed(2)}  conf=${out.confidence.toFixed(2)}  longs: ${longs || "(none)"}`,
      );
    }
  }

  console.log(pc.cyan("\n=== Layer 3 — superinvestor picks ==="));
  const supers = state.layer3_outputs ?? {};
  if (Object.keys(supers).length === 0) {
    console.log(pc.dim("(no superinvestor outputs)"));
  }
  for (const [id, out] of Object.entries(supers)) {
    const picks = out.picks
      .slice(0, 4)
      .map((p) => `${p.ticker}(${p.holding_period},${p.conviction.toFixed(2)})`)
      .join(", ");
    console.log(`${pc.bold(id)}  conf=${out.confidence.toFixed(2)}  ${picks || "(no picks)"}`);
  }

  console.log(pc.cyan("\n=== Layer 4 — decision ==="));
  const l4 = state.layer4_outputs;
  if (l4.cro) {
    console.log(
      `${pc.bold("cro")}  conf=${l4.cro.confidence.toFixed(2)}  rejected=${l4.cro.rejected_picks.length}` +
        (l4.cro.black_swan_scenarios.length > 0
          ? `  black_swan=${l4.cro.black_swan_scenarios.length}`
          : ""),
    );
  }
  if (l4.alpha_discovery) {
    console.log(
      `${pc.bold("alpha_discovery")}  conf=${l4.alpha_discovery.confidence.toFixed(2)}  novel=${l4.alpha_discovery.novel_picks.length}`,
    );
  }
  if (l4.autonomous_execution) {
    console.log(
      `${pc.bold("autonomous_execution")}  conf=${l4.autonomous_execution.confidence.toFixed(2)}  trades=${l4.autonomous_execution.trades.length}`,
    );
  }
  if (l4.cio) {
    console.log(
      `${pc.bold("cio")}  conf=${l4.cio.confidence.toFixed(2)}  actions=${l4.cio.portfolio_actions.length}`,
    );
  }

  console.log(pc.cyan("\n=== portfolio_actions (final) ==="));
  printPortfolioTable(state.portfolio_actions);

  console.log(pc.dim(`\ntotal=${state.llm_calls.length} llm calls, elapsed=${elapsed}s`));
}

function printPortfolioTable(actions: PortfolioAction[]): void {
  if (actions.length === 0) {
    console.log(pc.dim("(empty — holding 100% cash)"));
    return;
  }
  const totalWeight = actions.reduce((s, a) => s + a.target_weight, 0);
  console.log(
    `  ${pad("ticker", 12)} ${pad("action", 7)} ${pad("weight", 8)} ${pad("hp", 5)} dissent`,
  );
  for (const a of actions) {
    console.log(
      `  ${pad(a.ticker, 12)} ${pad(a.action, 7)} ${pad(a.target_weight.toFixed(2), 8)} ` +
        `${pad(a.holding_period, 5)} ${a.dissent_notes || ""}`,
    );
  }
  console.log(pc.dim(`  total_weight = ${totalWeight.toFixed(2)}`));
}

function pad(s: string, w: number): string {
  return s.length >= w ? s : s + " ".repeat(w - s.length);
}

// ---------------------------------------------------------------------------
// Fake LLM for --fake-llm mode
// ---------------------------------------------------------------------------

/**
 * A minimal mock that returns a non-tool-calling response for every invoke.
 * Each agent's structured-output extractor will fail → factory falls back
 * to the agent's ``fallback()`` (zero-conviction outputs). The cycle still
 * runs end-to-end and validates wiring; portfolio_actions ends up empty,
 * which is the expected smoke outcome.
 *
 * For LLM-driven structured outputs we use the test-style canned responses
 * — see ``test/daily_cycle.test.ts``. Reusing that here would couple the
 * CLI to test fixtures, so this fake stays minimal.
 */
class FakeChatModel {
  bindTools(_tools: unknown): FakeChatModel {
    return this;
  }
  withStructuredOutput(_schema: unknown): { invoke: () => Promise<unknown> } {
    // Throwing forces invokeStructuredOrFreetext to return null and the
    // factory to call the agent's fallback().
    return {
      invoke: async () => {
        throw new Error("--fake-llm: structured output unavailable, fallback");
      },
    };
  }
  async invoke(_messages: BaseMessage[]): Promise<AIMessage> {
    return new AIMessage(
      "(--fake-llm) skipping LLM analysis; agent will fall back to default zero-conviction output.",
    );
  }
}

function buildFakeLlmHandle(): LlmHandle {
  return {
    llm: new FakeChatModel() as unknown as BaseChatModel,
    provider: "fake",
    model: "fake-llm-mock",
    baseUrl: undefined,
  };
}

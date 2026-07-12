/**
 * Phase 7 CLI: ``pnpm dev mirofish``.
 *
 * MiroFish synthetic-futures forward training:
 *   - generate: persist + print the scenario set for Daily Cycle feedback
 *   - train:    scenario → persist context → agent rec → score → record
 *   - history:  recent mirofish_runs
 */

import { readFile } from "node:fs/promises";
import type { Command } from "commander";
import pc from "picocolors";
import { AGENTS_BY_LAYER } from "../../agents/prompts/cohorts.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { createLlmFromConfig } from "../../llm/factory.js";
import { type MirofishCurrentPositionInput, runMirofishTraining } from "../../mirofish/trainer.js";
import { redactSensitiveText } from "../../security/redaction.js";
import { buildFakeLlmHandle } from "../_backtest_helpers.js";
import { pad } from "../_format.js";

const DEFAULT_AGENTS = AGENTS_BY_LAYER.superinvestor;
const MIROFISH_BRIDGE_TIMEOUT_MS = 30 * 60 * 1000;

interface GenerateOpts {
  days?: string;
  seed?: string;
  scenarios?: string;
  print?: boolean;
  reflexive?: boolean;
  engine?: string;
  swarm?: boolean;
  maxRounds?: string;
  currentPositionsJson?: string;
  currentPositionsFile?: string;
  sectorExposureJson?: string;
  themeExposureJson?: string;
}

interface TrainOpts {
  days?: string;
  seed?: string;
  scenarios?: string;
  agents?: string;
  dryRun?: boolean;
  fakeLlm?: boolean;
  reflexive?: boolean;
  engine?: string;
  swarm?: boolean;
  scorer?: string;
  pathAware?: boolean;
  currentPositionsJson?: string;
  currentPositionsFile?: string;
  sectorExposureJson?: string;
  themeExposureJson?: string;
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
    .description("Generate, persist, and print the scenario set.")
    .option("--days <n>", "Days to simulate (default 30)")
    .option("--seed <n>", "RNG seed for reproducibility")
    .option(
      "--scenarios <list>",
      "Comma-separated scenario types (base,bull,bear,tail_up,tail_down)",
    )
    .option("--print", "Print scenario detail")
    .option("--reflexive", "Apply the reflexive actor overlay (price↔behavior feedback)")
    .option("--engine <name>", "Scenario engine: oasis (default, real Fish) | montecarlo | swarm")
    .option("--swarm", "Shorthand for --engine swarm (Phase 7M.1 interaction engine)")
    .option("--max-rounds <n>", "Cap OASIS sim rounds (oasis engine only; server default 5)")
    .option(
      "--current-positions-json <json>",
      "JSON array of current positions, or object with current_positions and exposures",
    )
    .option(
      "--current-positions-file <path>",
      "JSON file with current_positions array and optional sector/theme exposure maps",
    )
    .option("--sector-exposure-json <json>", "JSON object of sector exposure weights")
    .option("--theme-exposure-json <json>", "JSON object of theme exposure weights")
    .action(async (opts: GenerateOpts) => {
      await withApi(async (api) => {
        const engine = resolveEngine(opts);
        const portfolioInputs = await loadMirofishPortfolioInputs(opts);
        const { scenarios } = await api.mirofishGenerateScenarios({
          ...(opts.days ? { num_days: Number.parseInt(opts.days, 10) } : {}),
          ...(opts.seed ? { seed: Number.parseInt(opts.seed, 10) } : {}),
          ...(opts.scenarios ? { scenarios: splitCsv(opts.scenarios) } : {}),
          ...(opts.reflexive ? { reflexivity: true } : {}),
          ...(engine ? { engine } : {}),
          ...(opts.maxRounds ? { max_rounds: Number.parseInt(opts.maxRounds, 10) } : {}),
          ...portfolioInputs,
        });
        const persisted = await api.mirofishSaveContext({ scenarios });
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
        console.log(
          pc.dim(
            `  saved context ${persisted.date} (${persisted.context.context_hash ?? "hash unavailable"})`,
          ),
        );
      });
    });

  cmd
    .command("train")
    .description("Forward-train agents on simulated scenarios (isolated ledger).")
    .option("--days <n>", "Days to simulate (default 30)")
    .option("--seed <n>", "RNG seed")
    .option(
      "--scenarios <list>",
      "Comma-separated scenario types (base,bull,bear,tail_up,tail_down)",
    )
    .option("--agents <list>", "Comma-separated agents (default 4 superinvestors)")
    .option("--dry-run", "Score but do not persist")
    .option("--fake-llm", "Deterministic canned recommendations (zero cost)")
    .option("--reflexive", "Apply the reflexive actor overlay (price↔behavior feedback)")
    .option("--engine <name>", "Scenario engine: oasis (default, real Fish) | montecarlo | swarm")
    .option("--swarm", "Shorthand for --engine swarm (Phase 7M.1 interaction engine)")
    .option("--scorer <name>", "Scoring: terminal (default) | path_aware (drawdown-penalised)")
    .option("--path-aware", "Shorthand for --scorer path_aware (score the equity curve)")
    .option(
      "--current-positions-json <json>",
      "JSON array of current positions, or object with current_positions and exposures",
    )
    .option(
      "--current-positions-file <path>",
      "JSON file with current_positions array and optional sector/theme exposure maps",
    )
    .option("--sector-exposure-json <json>", "JSON object of sector exposure weights")
    .option("--theme-exposure-json <json>", "JSON object of theme exposure weights")
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
        const agents = opts.agents
          ? opts.agents.split(",").map((a) => a.trim())
          : [...DEFAULT_AGENTS];
        console.log(
          pc.bold(
            `\nmirofish train -- agents=[${agents.join(", ")}]` +
              `${opts.dryRun ? " [DRY RUN]" : ""}${opts.fakeLlm ? " [FAKE LLM]" : ""}`,
          ),
        );
        const engine = resolveEngine(opts);
        const scorer = resolveScorer(opts);
        const portfolioInputs = await loadMirofishPortfolioInputs(opts);
        const result = await runMirofishTraining({
          ...(opts.days ? { numDays: Number.parseInt(opts.days, 10) } : {}),
          ...(opts.seed ? { seed: Number.parseInt(opts.seed, 10) } : {}),
          ...(opts.scenarios ? { scenarios: splitCsv(opts.scenarios) } : {}),
          agents,
          dryRun: opts.dryRun ?? false,
          ...(opts.fakeLlm ? { fakeLlm: true } : {}),
          ...(opts.reflexive ? { reflexive: true } : {}),
          ...(engine ? { engine } : {}),
          ...(scorer ? { scorer } : {}),
          ...(portfolioInputs.current_positions
            ? { currentPositions: portfolioInputs.current_positions }
            : {}),
          ...(portfolioInputs.sector_exposure
            ? { sectorExposure: portfolioInputs.sector_exposure }
            : {}),
          ...(portfolioInputs.theme_exposure
            ? { themeExposure: portfolioInputs.theme_exposure }
            : {}),
          deps: { llm: llmHandle.llm, api },
          onLog: (m) => console.log(pc.dim(`  ${redactSensitiveText(m)}`)),
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
}): "montecarlo" | "swarm" | "oasis" | undefined {
  if (opts.swarm) return "swarm";
  if (opts.engine === "montecarlo" || opts.engine === "swarm" || opts.engine === "oasis") {
    return opts.engine;
  }
  return undefined;
}

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

interface MirofishPortfolioInputOpts {
  currentPositionsJson?: string;
  currentPositionsFile?: string;
  sectorExposureJson?: string;
  themeExposureJson?: string;
}

interface MirofishPortfolioInputs {
  current_positions?: MirofishCurrentPositionInput[];
  sector_exposure?: Record<string, number>;
  theme_exposure?: Record<string, number>;
}

export async function loadMirofishPortfolioInputs(
  opts: MirofishPortfolioInputOpts,
): Promise<MirofishPortfolioInputs> {
  const fromFile = opts.currentPositionsFile
    ? parsePortfolioInputPayload(
        await readFile(opts.currentPositionsFile, "utf-8"),
        opts.currentPositionsFile,
      )
    : {};
  const fromInline = opts.currentPositionsJson
    ? parsePortfolioInputPayload(opts.currentPositionsJson, "--current-positions-json")
    : {};
  return {
    ...fromFile,
    ...fromInline,
    ...(opts.sectorExposureJson
      ? {
          sector_exposure: parseExposureMap(opts.sectorExposureJson, "--sector-exposure-json"),
        }
      : {}),
    ...(opts.themeExposureJson
      ? {
          theme_exposure: parseExposureMap(opts.themeExposureJson, "--theme-exposure-json"),
        }
      : {}),
  };
}

function parsePortfolioInputPayload(text: string, label: string): MirofishPortfolioInputs {
  const parsed = parseJson(text, label);
  if (Array.isArray(parsed)) {
    return { current_positions: normalizeCurrentPositions(parsed, label) };
  }
  if (!isRecord(parsed)) {
    throw new Error(`${label} must be a JSON array or object`);
  }
  return {
    ...(parsed.current_positions !== undefined
      ? {
          current_positions: normalizeCurrentPositions(
            parsed.current_positions,
            `${label}.current_positions`,
          ),
        }
      : {}),
    ...(parsed.sector_exposure !== undefined
      ? {
          sector_exposure: normalizeExposureMap(parsed.sector_exposure, `${label}.sector_exposure`),
        }
      : {}),
    ...(parsed.theme_exposure !== undefined
      ? {
          theme_exposure: normalizeExposureMap(parsed.theme_exposure, `${label}.theme_exposure`),
        }
      : {}),
  };
}

function parseExposureMap(text: string, label: string): Record<string, number> {
  return normalizeExposureMap(parseJson(text, label), label);
}

function normalizeCurrentPositions(value: unknown, label: string): MirofishCurrentPositionInput[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be a JSON array`);
  return value.map((item, index) => normalizeCurrentPosition(item, `${label}[${index}]`));
}

function normalizeCurrentPosition(value: unknown, label: string): MirofishCurrentPositionInput {
  if (!isRecord(value)) throw new Error(`${label} must be an object`);
  const ticker = value.ticker;
  if (typeof ticker !== "string" || !ticker.trim()) {
    throw new Error(`${label}.ticker must be a non-empty string`);
  }
  if (value.market_price === undefined && value.current_price === undefined) {
    throw new Error(`${label}.market_price must be a positive number`);
  }
  return {
    ticker: ticker.trim(),
    ...optionalPositiveNumberField(value, "market_price", label),
    ...optionalPositiveNumberField(value, "current_price", label),
    ...optionalFiniteNumberField(value, "current_weight", label),
    ...optionalFiniteNumberField(value, "cost_basis", label),
    ...optionalFiniteNumberField(value, "holding_days", label),
    ...optionalFiniteNumberField(value, "unrealized_pnl_pct", label),
    ...(typeof value.entry_thesis === "string" && value.entry_thesis.trim()
      ? { entry_thesis: value.entry_thesis.trim() }
      : {}),
  };
}

function optionalPositiveNumberField(
  value: Record<string, unknown>,
  key: "market_price" | "current_price",
  label: string,
): Record<string, number> {
  const raw = value[key];
  if (raw === undefined || raw === null) return {};
  if (typeof raw !== "number" || !Number.isFinite(raw) || raw <= 0) {
    throw new Error(`${label}.${key} must be a positive number`);
  }
  return { [key]: raw };
}

function optionalFiniteNumberField(
  value: Record<string, unknown>,
  key: keyof Omit<MirofishCurrentPositionInput, "ticker" | "entry_thesis">,
  label: string,
): Record<string, number> {
  const raw = value[key];
  if (raw === undefined || raw === null) return {};
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    throw new Error(`${label}.${key} must be a finite number`);
  }
  return { [key]: raw };
}

function normalizeExposureMap(value: unknown, label: string): Record<string, number> {
  if (!isRecord(value)) throw new Error(`${label} must be a JSON object`);
  const out: Record<string, number> = {};
  for (const [key, raw] of Object.entries(value)) {
    if (typeof raw !== "number" || !Number.isFinite(raw)) {
      throw new Error(`${label}.${key} must be a finite number`);
    }
    out[key] = raw;
  }
  return out;
}

function parseJson(text: string, label: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch (err) {
    throw new Error(`${label} must be valid JSON: ${(err as Error).message}`);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
  const client = new BridgeClient({ defaultTimeoutMs: MIROFISH_BRIDGE_TIMEOUT_MS });
  const api = new BridgeApi(client);
  try {
    await client.start();
    await fn(api);
  } catch (err) {
    if (err instanceof RpcError) {
      console.error(pc.red(`bridge error [${err.code}]: ${redactSensitiveText(err.message)}`));
    } else {
      console.error(pc.red(`error: ${redactSensitiveText((err as Error).message)}`));
    }
    const tail = client.stderrTail.trim();
    if (tail) {
      console.error(pc.dim("\n--- bridge stderr (tail) ---"));
      console.error(pc.dim(redactSensitiveText(tail).slice(-2000)));
    }
    process.exitCode = 1;
  } finally {
    await client.close();
  }
}

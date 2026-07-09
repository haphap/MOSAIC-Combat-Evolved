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

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import type { BaseMessage } from "@langchain/core/messages";
import { AIMessage } from "@langchain/core/messages";
import type { Command } from "commander";
import pc from "picocolors";
import {
  formatDurationMs,
  parseAgentTimeoutSeconds,
  resolveAgentTimeoutMs,
} from "../../agents/helpers/runtime.js";
import { formatPromptSourceLabel } from "../../agents/prompts/cohorts.js";
import { captureDailyCycleRkeFootprints } from "../../agents/rke_footprints.js";
import { type DailyCycleStateType, emptyCurrentPositions } from "../../agents/state.js";
import type {
  CurrentPosition,
  CurrentPositionsSnapshot,
  PortfolioAction,
  PositionAudit,
} from "../../agents/types.js";
import {
  BridgeApi,
  BridgeClient,
  type PaperAccount,
  type PaperOrderResult,
  type PaperPosition,
  type PaperSuggestion,
  RpcError,
} from "../../bridge/index.js";
import { buildDailyCycleGraph } from "../../graph/daily_cycle.js";
import { createLlmFromConfig, type LlmHandle } from "../../llm/factory.js";
import { redactSensitiveText } from "../../security/redaction.js";
import { pad } from "../_format.js";
import { applyPromptSourceOverrides } from "../prompt-source.js";

interface DailyCycleOptions {
  cohort?: string;
  date?: string;
  fakeLlm?: boolean;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
  promptsRepo?: string;
  promptsRoot?: string;
  out?: string;
  vetoThreshold?: string;
  agentTimeoutSeconds?: string;
  paperPositions?: boolean;
  currentPositionsJson?: string;
  currentPositionsFile?: string;
  paperExecuteDeltas?: boolean;
}

export interface PaperDeltaExecution {
  ticker: string;
  target_weight: number;
  suggested_order: PaperSuggestion | null;
  submitted_order: PaperOrderResult | null;
  skipped_reason?: string;
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
    .option("--prompts-repo <path>", "Use a private prompt git repo for this run")
    .option("--prompts-root <path>", "Use a direct prompts/mosaic root for this run")
    .option("--out <path>", "Write the final state JSON to <path> instead of pretty-printing")
    .option(
      "--veto-threshold <num>",
      "CRO veto threshold; rejection rate > this triggers replay (default 0.5)",
    )
    .option(
      "--agent-timeout-seconds <seconds>",
      "Per-agent wall-clock timeout in seconds (default 300; 0/off disables)",
    )
    .option("--paper-positions", "Seed current_positions from the active paper account")
    .option("--current-positions-json <json>", "Seed current_positions from an inline JSON fixture")
    .option("--current-positions-file <path>", "Seed current_positions from a JSON fixture file")
    .option(
      "--paper-execute-deltas",
      "Submit paper orders after the run using paper.suggest_order_from_signal target-current deltas",
    )
    .action(async (opts: DailyCycleOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        applyPromptSourceOverrides(opts);

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
            redactSensitiveText(
              `provider=${llmHandle.provider} model=${llmHandle.model}` +
                (llmHandle.baseUrl ? ` base=${llmHandle.baseUrl}` : "") +
                (opts.fakeLlm ? " (fake-llm)" : ""),
            ),
          ),
        );
        console.log(pc.dim(redactSensitiveText(`prompts=${formatPromptSourceLabel()}`)));

        const cohort = opts.cohort ?? config.active_cohort ?? "cohort_default";
        const asOfDate = opts.date ?? new Date().toISOString().slice(0, 10);
        const vetoThreshold = opts.vetoThreshold ? Number(opts.vetoThreshold) : 0.5;
        const agentTimeoutSeconds = parseAgentTimeoutSeconds(opts.agentTimeoutSeconds);
        const agentTimeoutMs = resolveAgentTimeoutMs(agentTimeoutSeconds);
        const onAgentLog = (msg: string) => {
          console.log(pc.dim(`  ${redactSensitiveText(msg)}`));
        };
        const currentPositions = await loadDailyCycleCurrentPositions(opts, api);

        const graph = buildDailyCycleGraph({
          llmHandle,
          api,
          config,
          vetoThreshold,
          onLog: onAgentLog,
          ...(agentTimeoutSeconds !== undefined ? { agentTimeoutSeconds } : {}),
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
          current_positions: currentPositions,
          position_reviews: [],
          position_audit: positionAuditFromSnapshot(currentPositions),
          portfolio_actions: [],
          replay_triggered: false,
          llm_calls: [],
        };

        console.log(pc.bold(`\nMOSAIC daily cycle — cohort=${cohort} date=${asOfDate}`));
        console.log(
          pc.dim(`agent_timeout=${agentTimeoutMs > 0 ? formatDurationMs(agentTimeoutMs) : "off"}`),
        );
        const t0 = Date.now();
        const final = (await graph.invoke(initialState)) as DailyCycleStateType;
        const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
        if (opts.paperExecuteDeltas) {
          const execution = await submitPaperTargetDeltaOrders(api, final.portfolio_actions, {
            analysisId: final.trace_id,
            tradeDate: final.as_of_date,
          });
          console.log(pc.cyan("\n=== paper execution deltas ==="));
          for (const row of execution) {
            if (!row.suggested_order) {
              console.log(
                pc.dim(
                  `  ${row.ticker} target=${(row.target_weight * 100).toFixed(2)}% ${row.skipped_reason ?? "no delta order"}`,
                ),
              );
            } else {
              console.log(
                `  ${row.suggested_order.side} ${row.suggested_order.quantity} ${row.ticker} ` +
                  `target=${(row.target_weight * 100).toFixed(2)}%`,
              );
            }
          }
        }
        try {
          const capture = await captureDailyCycleRkeFootprints(api, final);
          if (capture) {
            const detail =
              capture.capture_status === "captured"
                ? `rke_footprints=${capture.captured_count}`
                : `rke_footprints_blocked=${(capture.failures ?? []).slice(0, 2).join(" | ")}`;
            console.log(pc.dim(redactSensitiveText(detail)));
          }
        } catch (err) {
          console.log(
            pc.dim(redactSensitiveText(`rke_footprints_skipped=${(err as Error).message}`)),
          );
        }

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
  printPositionAudit(state);
  printPortfolioTable(state.portfolio_actions);

  console.log(pc.dim(`\ntotal=${state.llm_calls.length} llm calls, elapsed=${elapsed}s`));
}

function printPositionAudit(state: DailyCycleStateType): void {
  const audit = state.position_audit;
  console.log(
    pc.dim(
      `positions=${audit.snapshot_status}/${audit.position_source} loaded=${audit.positions_loaded} ` +
        `reviewed=${audit.positions_reviewed} unreviewed=${audit.positions_unreviewed}`,
    ),
  );
  const warnings: string[] = [];
  if (audit.positions_unreviewed > 0) warnings.push("UNREVIEWED_POSITION");
  if (audit.snapshot_status === "missing") warnings.push("MISSING_POSITION_SNAPSHOT");
  if (audit.stale_thesis_count > 0) warnings.push("STALE_THESIS");
  if (audit.stop_loss_override_count > 0) warnings.push("STOP_LOSS_OVERRIDE");
  if (audit.target_current_drift_count > 0) warnings.push("TARGET_CURRENT_DRIFT");
  if (warnings.length > 0) {
    console.log(pc.yellow(`  warnings=${warnings.join(",")}`));
  }
}

function printPortfolioTable(actions: PortfolioAction[]): void {
  if (actions.length === 0) {
    console.log(pc.dim("(empty — holding 100% cash)"));
    return;
  }
  const totalWeight = actions.reduce((s, a) => s + a.target_weight, 0);
  console.log(
    `  ${pad("ticker", 12)} ${pad("action", 7)} ${pad("pos", 7)} ${pad("cur", 7)} ` +
      `${pad("target", 7)} ${pad("delta", 7)} ${pad("thesis", 8)} dissent`,
  );
  for (const a of actions) {
    console.log(
      `  ${pad(a.ticker, 12)} ${pad(a.action, 7)} ${pad(a.position_decision ?? "-", 7)} ` +
        `${pad(formatWeight(a.current_weight), 7)} ${pad(a.target_weight.toFixed(2), 7)} ` +
        `${pad(formatWeight(a.delta_weight), 7)} ${pad(a.thesis_status ?? "-", 8)} ` +
        `${a.dissent_notes || ""}`,
    );
  }
  console.log(pc.dim(`  total_weight = ${totalWeight.toFixed(2)}`));
}

function formatWeight(value: number | undefined): string {
  return value === undefined ? "-" : value.toFixed(2);
}

// pad() imported from ../_format.js (§14 R-T2: shared CJK + ANSI-aware).

export async function loadDailyCycleCurrentPositions(
  opts: Pick<DailyCycleOptions, "paperPositions" | "currentPositionsJson" | "currentPositionsFile">,
  api: BridgeApi,
): Promise<CurrentPositionsSnapshot> {
  if (opts.paperPositions && (opts.currentPositionsJson || opts.currentPositionsFile)) {
    throw new Error("choose either --paper-positions or a current-position fixture, not both");
  }
  const fixture = loadCurrentPositionsFixture(opts);
  if (fixture) return fixture;
  return opts.paperPositions ? await loadPaperCurrentPositions(api) : emptyCurrentPositions();
}

export function loadCurrentPositionsFixture(
  opts: Pick<DailyCycleOptions, "currentPositionsJson" | "currentPositionsFile">,
): CurrentPositionsSnapshot | null {
  if (opts.currentPositionsJson && opts.currentPositionsFile) {
    throw new Error("choose only one current-position fixture source");
  }
  let raw: unknown = null;
  if (opts.currentPositionsFile) {
    raw = JSON.parse(readFileSync(opts.currentPositionsFile, "utf-8")) as unknown;
  }
  if (opts.currentPositionsJson) {
    raw = JSON.parse(opts.currentPositionsJson) as unknown;
  }
  if (raw === null) return null;
  const snapshot = normalizeCurrentPositionsFixture(raw);
  return {
    ...snapshot,
    position_snapshot_hash:
      snapshot.position_snapshot_hash ?? currentPositionFixtureHash(snapshot.positions),
  };
}

async function loadPaperCurrentPositions(api: BridgeApi): Promise<CurrentPositionsSnapshot> {
  try {
    const [account, positions] = await Promise.all([
      api.paperGetAccount(),
      api.paperGetPositions(),
    ]);
    if (positions.length === 0) {
      return {
        ...emptyCurrentPositions(),
        position_source: "paper_account",
        position_snapshot_hash: paperPositionHash(account, positions),
      };
    }
    const totalAssets =
      account.total_assets > 0
        ? account.total_assets
        : positions.reduce((sum, position) => sum + position.market_value, 0);
    return {
      snapshot_status: "loaded",
      position_source: "paper_account",
      source_error_code: null,
      position_snapshot_hash: paperPositionHash(account, positions),
      positions: positions.map((position) => ({
        ticker: position.ticker,
        current_weight: totalAssets > 0 ? position.market_value / totalAssets : 0,
        cost_basis: position.avg_cost,
        market_price: position.current_price,
        unrealized_pnl_pct: position.pnl_pct / 100,
        holding_days: 0,
        entry_date: position.updated_at.slice(0, 10),
        source_agent: "paper_account",
        entry_thesis_id: `paper:${position.ticker}`,
        last_review_date: position.updated_at.slice(0, 10),
      })),
    };
  } catch (err) {
    return {
      snapshot_status: "missing",
      position_source: "paper_account",
      source_error_code: `paper_positions_unavailable:${(err as Error).message.slice(0, 80)}`,
      position_snapshot_hash: undefined,
      positions: [],
    };
  }
}

function paperPositionHash(account: PaperAccount, positions: ReadonlyArray<PaperPosition>): string {
  const payload = JSON.stringify({
    total_assets: account.total_assets,
    positions: positions.map((position) => ({
      ticker: position.ticker,
      quantity: position.quantity,
      market_value: position.market_value,
      updated_at: position.updated_at,
    })),
  });
  return `sha256:${createHash("sha256").update(payload).digest("hex")}`;
}

function currentPositionFixtureHash(positions: ReadonlyArray<CurrentPosition>): string {
  const payload = JSON.stringify(positions);
  return `sha256:${createHash("sha256").update(payload).digest("hex")}`;
}

function normalizeCurrentPositionsFixture(raw: unknown): CurrentPositionsSnapshot {
  if (Array.isArray(raw)) {
    return snapshotFromFixturePositions(raw);
  }
  if (raw === null || typeof raw !== "object") {
    throw new Error("current positions fixture must be a JSON array or object");
  }
  const record = raw as Record<string, unknown>;
  const positionsValue = record.current_positions ?? record.positions;
  if (!Array.isArray(positionsValue)) {
    throw new Error("current positions fixture must contain current_positions or positions array");
  }
  const snapshot = snapshotFromFixturePositions(positionsValue);
  const status = optionalString(record.snapshot_status);
  if (status !== null) {
    if (!["loaded", "empty_confirmed", "missing"].includes(status)) {
      throw new Error(`snapshot_status must be loaded, empty_confirmed, or missing: ${status}`);
    }
    snapshot.snapshot_status = status as CurrentPositionsSnapshot["snapshot_status"];
  }
  snapshot.source_error_code = optionalString(record.source_error_code);
  snapshot.position_snapshot_hash = optionalString(record.position_snapshot_hash) ?? undefined;
  return snapshot;
}

function snapshotFromFixturePositions(values: unknown[]): CurrentPositionsSnapshot {
  const positions = values.map((value, index) => normalizeFixturePosition(value, index));
  return {
    snapshot_status: positions.length > 0 ? "loaded" : "empty_confirmed",
    position_source: positions.length > 0 ? "cli_fixture" : "empty_confirmed",
    source_error_code: null,
    positions,
  };
}

function normalizeFixturePosition(value: unknown, index: number): CurrentPosition {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`current_positions[${index}] must be an object`);
  }
  const record = value as Record<string, unknown>;
  const ticker = requiredString(record.ticker, `current_positions[${index}].ticker`);
  return {
    ticker,
    current_weight: requiredFiniteNumber(
      record.current_weight,
      `current_positions[${index}].current_weight`,
    ),
    cost_basis: requiredFiniteNumber(record.cost_basis, `current_positions[${index}].cost_basis`),
    market_price: requiredFiniteNumber(
      record.market_price,
      `current_positions[${index}].market_price`,
    ),
    unrealized_pnl_pct: requiredFiniteNumber(
      record.unrealized_pnl_pct,
      `current_positions[${index}].unrealized_pnl_pct`,
    ),
    holding_days: requiredFiniteNumber(
      record.holding_days,
      `current_positions[${index}].holding_days`,
    ),
    entry_date: requiredString(record.entry_date, `current_positions[${index}].entry_date`),
    source_agent: requiredString(record.source_agent, `current_positions[${index}].source_agent`),
    entry_thesis_id: requiredString(
      record.entry_thesis_id,
      `current_positions[${index}].entry_thesis_id`,
    ),
    last_review_date: requiredString(
      record.last_review_date,
      `current_positions[${index}].last_review_date`,
    ),
  };
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function requiredFiniteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number`);
  }
  return value;
}

function positionAuditFromSnapshot(snapshot: CurrentPositionsSnapshot): PositionAudit {
  return {
    position_snapshot_hash: snapshot.position_snapshot_hash ?? null,
    snapshot_status: snapshot.snapshot_status,
    position_source: snapshot.position_source,
    source_error_code: snapshot.source_error_code,
    positions_loaded: snapshot.positions.length,
    positions_reviewed: 0,
    positions_unreviewed: snapshot.positions.length,
    hold_count: 0,
    add_count: 0,
    reduce_count: 0,
    exit_count: 0,
    stale_thesis_count: 0,
    stop_loss_override_count: 0,
    target_current_drift_count: 0,
  };
}

export async function submitPaperTargetDeltaOrders(
  api: Pick<BridgeApi, "paperSuggestOrderFromSignal" | "paperBuy" | "paperSell">,
  actions: ReadonlyArray<PortfolioAction>,
  opts: { userId?: string; dbPath?: string; analysisId?: string; tradeDate?: string } = {},
): Promise<PaperDeltaExecution[]> {
  const results: PaperDeltaExecution[] = [];
  for (const action of actions) {
    const targetWeightPct = action.target_weight * 100;
    const signalState = {
      backtest_signal: {
        ticker: action.ticker,
        decision_date: opts.tradeDate ?? new Date().toISOString().slice(0, 10),
        source: "daily_cycle_position_target",
        source_section: "portfolio_actions",
        rating: action.action,
        target_weight_pct: targetWeightPct,
        target_weight_min_pct: targetWeightPct,
        target_weight_max_pct: targetWeightPct,
        weight_source: "target_portfolio_weight",
      },
    };
    const suggested = await api.paperSuggestOrderFromSignal({
      ticker: action.ticker,
      state: signalState,
      ...(opts.userId ? { user_id: opts.userId } : {}),
      ...(opts.dbPath ? { db_path: opts.dbPath } : {}),
    });
    if (!suggested) {
      results.push({
        ticker: action.ticker,
        target_weight: action.target_weight,
        suggested_order: null,
        submitted_order: null,
        skipped_reason: "already_at_target_or_below_lot_size",
      });
      continue;
    }
    const orderParams = {
      ticker: suggested.ticker,
      quantity: suggested.quantity,
      ...(opts.userId ? { user_id: opts.userId } : {}),
      ...(opts.analysisId ? { analysis_id: opts.analysisId } : {}),
      ...(opts.dbPath ? { db_path: opts.dbPath } : {}),
    };
    const submitted =
      suggested.side === "buy" ? await api.paperBuy(orderParams) : await api.paperSell(orderParams);
    results.push({
      ticker: action.ticker,
      target_weight: action.target_weight,
      suggested_order: suggested,
      submitted_order: submitted,
    });
  }
  return results;
}

// ---------------------------------------------------------------------------
// Fake LLM for --fake-llm mode
// ---------------------------------------------------------------------------

/**
 * A minimal mock that returns a non-tool-calling response for every invoke.
 * Each agent's structured-output extractor will fail → factory falls back
 * to the agent's ``fallback()`` (zero-conviction outputs). The cycle still
 * runs end-to-end and validates wiring. With a loaded current-position
 * fixture, the CIO fallback emits conservative HOLD reviews for those
 * positions; otherwise portfolio_actions stays empty.
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

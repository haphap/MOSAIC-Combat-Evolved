/**
 * Shared helpers for the backtest CLIs (PR #4 review hotfix #3).
 *
 * Eliminates the duplication between ``backtest-fill.ts`` and ``backtest.ts``:
 *   - ``FakeChatModel`` + ``buildFakeLlmHandle`` (was duplicated in 2 files
 *     plus the original in ``daily-cycle.ts``)
 *   - ``makeInitialState`` (was duplicated in 2 files)
 *   - ``enumerateTradingDays`` (was duplicated as ``enumerateWeekdays``;
 *     now uses the bridge's ``calendar.list_trading_days`` RPC, fixing
 *     review #2 — no more wasted LLM calls on holidays)
 *
 * Also defines ``FakeLlmHandle`` as a structural interface so the module
 * can return it without any ``as any`` casts (review #5).
 */

import { createHash } from "node:crypto";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import type { AIMessage } from "@langchain/core/messages";
import {
  type DailyCycleStateType,
  emptyCurrentPositions,
  emptyPositionAudit,
} from "../agents/state.js";
import type { ClosedPosition, CurrentPositionsSnapshot, PortfolioAction } from "../agents/types.js";
import type { BridgeApi } from "../bridge/index.js";
import type { LlmHandle } from "../llm/factory.js";

/** Structural interface that ``FakeChatModel`` satisfies just enough for
 *  the daily-cycle's invokeStructuredOrFreetext path to fall back. */
export interface FakeLlmShim {
  bindTools(tools: unknown): FakeLlmShim;
  withStructuredOutput(schema: unknown): {
    invoke: () => Promise<unknown>;
  };
  invoke(messages: unknown): Promise<{ content: string }>;
}

class FakeChatModel implements FakeLlmShim {
  bindTools(_tools: unknown): FakeChatModel {
    return this;
  }
  withStructuredOutput(_schema: unknown): { invoke: () => Promise<unknown> } {
    return {
      invoke: async () => {
        throw new Error("--fake-llm: structured output unavailable, fallback");
      },
    };
  }
  async invoke(_messages: unknown): Promise<{ content: string }> {
    return { content: "(--fake-llm) fallback" };
  }
}

/**
 * Build a minimal LlmHandle backed by FakeChatModel.
 *
 * Returns the handle structurally typed without ``as any`` (review #5):
 * ``LlmHandle.llm`` is declared ``BaseChatModel`` upstream; we cast through
 * ``unknown`` rather than ``any`` to keep the cast localised + visible.
 */
export function buildFakeLlmHandle(): LlmHandle {
  const fake = new FakeChatModel();
  return {
    llm: fake as unknown as BaseChatModel,
    provider: "fake",
    model: "fake-llm-mock",
    baseUrl: undefined,
  };
}

/** Default initial DailyCycleState for backtest-mode runs (mode=backtest,
 *  fresh cycle, empty layer outputs). */
export function makeInitialState(cohort: string, asOfDate: string): DailyCycleStateType {
  return {
    messages: [],
    active_cohort: cohort,
    as_of_date: asOfDate,
    mode: "backtest",
    trace_id: `bt-${asOfDate}-${Date.now()}`,
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
    current_positions: emptyCurrentPositions(),
    position_reviews: [],
    position_audit: emptyPositionAudit(),
    portfolio_actions: [],
    replay_triggered: false,
    llm_calls: [],
  };
}

export function applyBacktestPortfolioActionsToPositions(
  previous: CurrentPositionsSnapshot,
  actions: ReadonlyArray<PortfolioAction>,
  asOfDate: string,
): CurrentPositionsSnapshot {
  const previousByTicker = new Map(
    previous.positions.map((position) => [position.ticker, position]),
  );
  const closedPositions: ClosedPosition[] = [
    ...(previous.closed_positions ?? []),
    ...actions
      .filter((action) => action.target_weight <= 0 || action.action === "SELL")
      .flatMap((action) => {
        const prior = previousByTicker.get(action.ticker);
        if (!prior) return [];
        return [
          {
            ticker: action.ticker,
            exit_date: asOfDate,
            exit_reason:
              action.position_decision_reason || action.dissent_notes || `${action.action} target`,
            realized_pnl_pct: prior.unrealized_pnl_pct,
            residual_drift_pct: 0,
            entry_thesis_id: prior.entry_thesis_id,
            holding_days: prior.holding_days,
          },
        ];
      }),
  ];
  const positions = actions
    .filter((action) => action.target_weight > 0 && action.action !== "SELL")
    .map((action) => {
      const prior = previousByTicker.get(action.ticker);
      return {
        ticker: action.ticker,
        current_weight: action.target_weight,
        cost_basis: prior?.cost_basis ?? 1,
        market_price: prior?.market_price ?? 1,
        unrealized_pnl_pct: prior?.unrealized_pnl_pct ?? 0,
        realized_pnl_pct: prior?.realized_pnl_pct ?? 0,
        residual_drift_pct: 0,
        holding_days: prior ? prior.holding_days + 1 : 0,
        entry_date: prior?.entry_date ?? asOfDate,
        source_agent: prior?.source_agent ?? "cio",
        entry_thesis_id: prior?.entry_thesis_id ?? `backtest:${action.ticker}:${asOfDate}`,
        last_review_date: asOfDate,
      };
    });
  if (positions.length === 0) {
    return {
      ...emptyCurrentPositions(),
      position_source: "backtest_replay",
      position_snapshot_hash: backtestPositionHash(asOfDate, [], closedPositions),
      ...(closedPositions.length > 0 ? { closed_positions: closedPositions } : {}),
    };
  }
  return {
    snapshot_status: "loaded",
    position_source: "backtest_replay",
    source_error_code: null,
    position_snapshot_hash: backtestPositionHash(asOfDate, positions, closedPositions),
    positions,
    ...(closedPositions.length > 0 ? { closed_positions: closedPositions } : {}),
  };
}

function backtestPositionHash(
  asOfDate: string,
  positions: ReadonlyArray<CurrentPositionsSnapshot["positions"][number]>,
  closedPositions: ReadonlyArray<ClosedPosition> = [],
): string {
  const payload = JSON.stringify({
    closed_positions: closedPositions.map((position) => ({
      ticker: position.ticker,
      exit_date: position.exit_date,
      realized_pnl_pct: position.realized_pnl_pct,
    })),
    positions: positions.map((position) => ({
      ticker: position.ticker,
      current_weight: position.current_weight,
      holding_days: position.holding_days,
      residual_drift_pct: position.residual_drift_pct ?? 0,
    })),
  });
  return `sha256:${createHash("sha256").update(`${asOfDate}:${payload}`).digest("hex")}`;
}

/**
 * Enumerate true A-share trading days in [start, end] (inclusive on both)
 * via the bridge's ``calendar.list_trading_days`` RPC.
 *
 * Replaces the prior weekday-only ``enumerateWeekdays`` which wasted
 * LLM calls on holidays (PR #4 review #2). When the bridge calendar is
 * unavailable for some reason, falls back to weekday-only with a clear
 * console warning.
 */
export async function enumerateTradingDays(
  api: BridgeApi,
  start: string,
  end: string,
): Promise<string[]> {
  if (!isValidDate(start) || !isValidDate(end)) {
    throw new Error("invalid --start / --end (must be YYYY-MM-DD)");
  }
  try {
    const result = await api.calendarListTradingDays(start, end);
    return result.trading_days;
  } catch (err) {
    // Fallback: bridge / Tushare unavailable — Mon-Fri only.
    console.warn(
      `calendar.list_trading_days failed (${(err as Error).message}); ` +
        "falling back to Mon-Fri weekday enumeration. Holidays will not be skipped.",
    );
    return enumerateWeekdaysOnly(start, end);
  }
}

/** Mon-Fri only — used as fallback when the bridge calendar is unreachable. */
function enumerateWeekdaysOnly(start: string, end: string): string[] {
  const out: string[] = [];
  const startDate = new Date(`${start}T00:00:00Z`);
  const endDate = new Date(`${end}T00:00:00Z`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return out;
  }
  if (startDate > endDate) return out;
  const cur = new Date(startDate.getTime());
  while (cur <= endDate) {
    const dow = cur.getUTCDay();
    if (dow !== 0 && dow !== 6) {
      const yyyy = cur.getUTCFullYear();
      const mm = String(cur.getUTCMonth() + 1).padStart(2, "0");
      const dd = String(cur.getUTCDate()).padStart(2, "0");
      out.push(`${yyyy}-${mm}-${dd}`);
    }
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  return out;
}

function isValidDate(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(new Date(`${s}T00:00:00Z`).getTime());
}

// Suppress unused-import warning for AIMessage when consumers grow.
void ({} as AIMessage);

import { createHash } from "node:crypto";
import type { BridgeApi } from "../../bridge/index.js";
import type { DailyCycleStateType } from "../state.js";
import type { RuntimeSourceStatus } from "./research_knobs.js";

export type Layer4SourceResolutionStage =
  | "pre_candidate"
  | "candidate_market"
  | "execution_liquidity";

const MARKET_ADAPTER_ID = "market.scoped_snapshot_adapter.v1";
const LIQUIDITY_ADAPTER_ID = "execution.liquidity_adapter.v1";

export async function resolveLayer4SourceStatuses(
  state: DailyCycleStateType,
  stage: Layer4SourceResolutionStage,
  api?: Pick<BridgeApi, "toolsCall">,
): Promise<RuntimeSourceStatus[]> {
  const asOf = state.as_of_date || new Date().toISOString().slice(0, 10);
  const sourceId =
    stage === "execution_liquidity" ? "execution_liquidity_state" : "current_market_data";
  const adapterId = stage === "execution_liquidity" ? LIQUIDITY_ADAPTER_ID : MARKET_ADAPTER_ID;
  const tickers =
    stage === "pre_candidate" ? preCandidateTickers(state) : frozenCandidateTickers(state);
  const existing = state.layer4_outputs?.runtime?.resolved_source_statuses ?? [];
  const unresolved = tickers.filter(
    (ticker) =>
      !existing.some(
        (status) =>
          status.source_id === sourceId &&
          status.scope === `ticker:${ticker}` &&
          status.status === "loaded" &&
          status.as_of === asOf,
      ),
  );
  const additions = await mapWithConcurrency(unresolved, 4, (ticker) =>
    resolveTickerSource({ api, state, ticker, asOf, sourceId, adapterId, stage }),
  );
  return mergeRuntimeSourceStatuses(existing, additions);
}

export function mergeRuntimeSourceStatuses(
  current: ReadonlyArray<RuntimeSourceStatus>,
  additions: ReadonlyArray<RuntimeSourceStatus>,
): RuntimeSourceStatus[] {
  const merged = new Map(current.map((status) => [statusKey(status), status]));
  for (const status of additions) merged.set(statusKey(status), status);
  return [...merged.values()].sort((left, right) =>
    statusKey(left).localeCompare(statusKey(right)),
  );
}

function preCandidateTickers(state: DailyCycleStateType): string[] {
  const tickers = [
    ...state.current_positions.positions.map((position) => position.ticker),
    ...Object.values(state.layer2_outputs).flatMap((output) =>
      "longs" in output
        ? [...output.longs.map((pick) => pick.ticker), ...output.shorts.map((pick) => pick.ticker)]
        : [],
    ),
    ...Object.values(state.layer3_outputs).flatMap((output) =>
      output.picks.map((pick) => pick.ticker),
    ),
    ...(state.layer4_outputs?.alpha_discovery?.novel_picks.map((pick) => pick.ticker) ?? []),
  ];
  return uniqueTickers(tickers);
}

function frozenCandidateTickers(state: DailyCycleStateType): string[] {
  return uniqueTickers(
    (
      state.layer4_outputs?.runtime?.candidate_target_state?.portfolio_actions ??
      state.layer4_outputs?.runtime?.cio_proposal?.portfolio_actions ??
      []
    ).map((action) => action.ticker),
  );
}

async function resolveTickerSource(opts: {
  api: Pick<BridgeApi, "toolsCall"> | undefined;
  state: DailyCycleStateType;
  ticker: string;
  asOf: string;
  sourceId: string;
  adapterId: string;
  stage: Layer4SourceResolutionStage;
}): Promise<RuntimeSourceStatus> {
  const common = {
    source_id: opts.sourceId,
    scope: `ticker:${opts.ticker}`,
    as_of: opts.asOf,
    producer_stage: "pre_stage_source_resolution",
    resolved_at_stage: opts.stage,
    adapter_id: opts.adapterId,
  } satisfies Partial<RuntimeSourceStatus> & Pick<RuntimeSourceStatus, "source_id" | "scope">;
  if (!opts.api) {
    return {
      ...common,
      status: "source_error",
      error_code: `${opts.sourceId}_adapter_unavailable`,
    };
  }
  const args = {
    symbol: opts.ticker,
    start_date: shiftIsoDate(opts.asOf, -10),
    end_date: opts.asOf,
  };
  try {
    const result = await opts.api.toolsCall(
      "get_stock_data",
      args,
      opts.state.mode === "backtest"
        ? { mode: "backtest", as_of_date: opts.asOf }
        : { mode: "live", as_of_date: opts.asOf },
    );
    const text = result.text.trim();
    if (text.length === 0 || /(?:no data|no rows|not found|empty result|无数据)/i.test(text)) {
      return { ...common, status: "missing", error_code: `${opts.sourceId}_empty_result` };
    }
    const observedAsOf = latestObservedDate(text);
    if (!observedAsOf) {
      return { ...common, status: "source_error", error_code: `${opts.sourceId}_date_unparseable` };
    }
    if (observedAsOf > opts.asOf) {
      return { ...common, status: "source_error", error_code: `${opts.sourceId}_lookahead` };
    }
    const snapshot_hash = stableHash({
      adapter_id: opts.adapterId,
      args,
      observed_as_of: observedAsOf,
      response_hash: stableHash(text),
    });
    if (observedAsOf !== opts.asOf) {
      return {
        ...common,
        status: "stale",
        as_of: observedAsOf,
        snapshot_hash,
        error_code: `${opts.sourceId}_not_current_for_run_date`,
      };
    }
    return { ...common, status: "loaded", as_of: observedAsOf, snapshot_hash };
  } catch {
    return { ...common, status: "source_error", error_code: `${opts.sourceId}_tool_failed` };
  }
}

function latestObservedDate(text: string): string | null {
  const dates = [
    ...text.matchAll(/\b(\d{4})-(\d{2})-(\d{2})\b/g),
    ...text.matchAll(/\b(\d{4})(\d{2})(\d{2})\b/g),
  ]
    .map((match) => `${match[1]}-${match[2]}-${match[3]}`)
    .filter((value) => !Number.isNaN(Date.parse(`${value}T00:00:00Z`)))
    .sort();
  return dates.at(-1) ?? null;
}

function shiftIsoDate(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function uniqueTickers(tickers: ReadonlyArray<string>): string[] {
  return [...new Set(tickers.map((ticker) => ticker.trim()).filter(Boolean))].sort();
}

function statusKey(status: Pick<RuntimeSourceStatus, "source_id" | "scope">): string {
  return `${status.source_id}\u0000${status.scope}`;
}

function stableHash(value: unknown): string {
  return `sha256:${createHash("sha256").update(JSON.stringify(value)).digest("hex")}`;
}

async function mapWithConcurrency<T, U>(
  values: ReadonlyArray<T>,
  concurrency: number,
  fn: (value: T) => Promise<U>,
): Promise<U[]> {
  const results = new Array<U>(values.length);
  let index = 0;
  async function worker(): Promise<void> {
    while (index < values.length) {
      const current = index;
      index += 1;
      const value = values[current];
      if (value !== undefined) results[current] = await fn(value);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, values.length) }, () => worker()));
  return results;
}

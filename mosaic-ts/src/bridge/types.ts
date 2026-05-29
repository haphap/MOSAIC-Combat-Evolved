/**
 * Typed wrappers for the 21 RPC methods exposed by `mosaic.bridge` (Phase 0).
 *
 * Keep this file as the single source of truth for the wire-level shapes.
 * If a method's params/result change on the Python side, update the type
 * here in the same commit.
 *
 * Phase 4+ will expand this surface (scorecard.* / autoresearch.* /
 * prism.* / janus.* / mirofish.* / prompts.*); add typed wrappers as those
 * RPCs land.
 */

import type { BridgeClient } from "./client.js";

/** JSON Schema as produced by Pydantic v2 `model_json_schema()`. */
export interface JsonSchemaObject {
  type: "object";
  title?: string;
  description?: string;
  properties: Record<string, JsonSchemaProperty>;
  required?: string[];
}

export interface JsonSchemaProperty {
  type?: "string" | "integer" | "number" | "boolean";
  description?: string;
  title?: string;
  default?: unknown;
  /** Allows nullable when present as an array of types in some schemas. */
  anyOf?: Array<{ type?: string }>;
}

export interface ToolMetadata {
  name: string;
  description: string;
  args_schema: JsonSchemaObject;
}

export interface ToolCallContext {
  /** ISO yyyy-mm-dd; activates backtest-mode date clamping when set. */
  as_of_date?: string | null;
  /** "live" (default) or "backtest". */
  mode?: "live" | "backtest";
}

export interface ToolCallResult {
  text: string;
}

export interface CacheStats {
  api: { count: number; size_mb: number; subdirs: string[] };
  signals: { count: number; size_mb: number };
  snapshots: { count: number; size_mb: number; kinds: string[] };
  checkpoints: { count: number; size_mb: number; tickers: string[] };
  total_mb: number;
}

export type CacheCategory = "api" | "signals" | "snapshots" | "checkpoints";

/** MOSAIC config — open shape; read defaults from `config.default`. */
export type MosaicConfig = Record<string, unknown>;

export interface PaperAccount {
  user_id: string;
  cash: number;
  market_value: number;
  total_assets: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_commission: number;
  updated_at: string;
}

export interface PaperPosition {
  ticker: string;
  name: string | null;
  quantity: number;
  available_qty: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  pnl_pct: number;
  updated_at: string;
}

export interface PaperTrade {
  id: number;
  user_id: string;
  ticker: string;
  name: string | null;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  amount: number;
  commission: number;
  pnl: number | null;
  analysis_id: string | null;
  created_at: string;
}

/** Backtest signal payload — same shape Python's analyze_candidate_pool returns. */
export type BacktestSignalsByDate = Record<string, ReadonlyArray<Record<string, unknown>>>;

export interface BacktestRunParams {
  tickers: string[];
  start_date: string;
  end_date: string;
  signals: BacktestSignalsByDate;
  rebalance_interval_days?: number;
  top_k?: number;
  execution_timing?: "same_close" | "next_open" | "next_close";
  initial_cash?: number;
  commission?: number;
  slippage_perc?: number;
  cash_buffer_pct?: number;
  benchmark_tickers?: string[] | null;
  force_refresh?: boolean;
  default_benchmark_ticker?: string | null;
}

/** BacktraderBacktestResult.to_dict() — open shape; consumers should pick fields. */
export type BacktestResult = Record<string, unknown>;

// --------------------------------------------------------- helpers

/**
 * Ergonomic helper around a BridgeClient. Methods are 1:1 with RPC names
 * (with dots replaced by camelCase grouping).
 */
export class BridgeApi {
  constructor(private readonly client: BridgeClient) {}

  // tools.*
  toolsList(): Promise<ToolMetadata[]> {
    return this.client.call<ToolMetadata[]>("tools.list", {});
  }

  toolsCall(
    name: string,
    args: Record<string, unknown>,
    context?: ToolCallContext,
  ): Promise<ToolCallResult> {
    return this.client.call<ToolCallResult>("tools.call", {
      name,
      args,
      ...(context ? { context } : {}),
    });
  }

  // config.*
  configDefault(): Promise<MosaicConfig> {
    return this.client.call<MosaicConfig>("config.default", {});
  }

  configGet(): Promise<MosaicConfig> {
    return this.client.call<MosaicConfig>("config.get", {});
  }

  configSet(config: MosaicConfig): Promise<MosaicConfig> {
    return this.client.call<MosaicConfig>("config.set", { config });
  }

  // cache.*
  cacheStats(): Promise<CacheStats> {
    return this.client.call<CacheStats>("cache.stats", {});
  }

  cacheCleanup(days: number, category: CacheCategory | "all" = "all"): Promise<unknown> {
    return this.client.call("cache.cleanup", { days, category });
  }

  cacheClear(category: CacheCategory | "all"): Promise<unknown> {
    return this.client.call("cache.clear", { category });
  }

  // paper.*
  paperCurrentUser(opts: { db_path?: string } = {}): Promise<{ user: string }> {
    return this.client.call<{ user: string }>("paper.current_user", opts);
  }

  paperGetAccount(opts: { user_id?: string; db_path?: string } = {}): Promise<PaperAccount> {
    return this.client.call<PaperAccount>("paper.get_account", opts);
  }

  paperGetPositions(opts: { user_id?: string; db_path?: string } = {}): Promise<PaperPosition[]> {
    return this.client.call<PaperPosition[]>("paper.get_positions", opts);
  }

  paperGetTrades(
    opts: { user_id?: string; limit?: number; db_path?: string } = {},
  ): Promise<PaperTrade[]> {
    return this.client.call<PaperTrade[]>("paper.get_trades", opts);
  }

  // backtest.*
  backtestRunCandidatePool(params: BacktestRunParams): Promise<BacktestResult> {
    return this.client.call<BacktestResult>("backtest.run_candidate_pool", params);
  }
}

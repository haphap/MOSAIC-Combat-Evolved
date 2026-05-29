/**
 * Wire-level type definitions for the JSON-RPC methods exposed by
 * `mosaic.bridge` (Phase 0 surface = 21 RPC methods registered).
 *
 * Keep this file as the single source of truth for the wire-level shapes.
 * If a method's params/result change on the Python side, update the type
 * here in the same commit.
 *
 * The :class:`BridgeApi` helper at the bottom only provides typed wrappers
 * for the subset of methods currently exercised by the TS front-end. The
 * remaining methods are reachable via ``client.call(method, params)`` and
 * will get typed wrappers as later phases need them (Phase 8 paper-trading
 * workflow, Phase 4+ scorecard / autoresearch / prism / janus / mirofish).
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

/**
 * MOSAIC config — the canonical Phase 0 fields are typed below; the bridge
 * exposes other keys (e.g. tool_vendors, role_brief_specs, memory_log_path)
 * that vary by phase, so the index signature keeps the shape open.
 *
 * Phase 2+ will tighten further (cohort state, agent debate budgets, etc.) —
 * follow up in plan §14 #7 when those land.
 */
export interface MosaicConfig {
  // ----- LLM (Plan §1, §13.3) -----
  /** "anthropic" | "openai" | "deepseek" | "lemonade" | ... — see `src/llm/factory.ts`. */
  llm_provider: string;
  deep_think_llm: string;
  quick_think_llm: string;
  /** Optional override base URL — usually left null and resolved per-provider. */
  backend_url: string | null;
  /** Optional override base URL specifically for the Anthropic provider. */
  anthropic_base_url: string | null;
  /** "low" | "medium" | "high" — maps to Anthropic extended-thinking budget. */
  anthropic_effort: string | null;

  // ----- Output (Plan §10) -----
  /** "Chinese" (default) | "English" | "Bilingual". */
  output_language: string;
  research_depth_name: string;

  // ----- Cohort (Plan §1, §9) -----
  /** Active cohort key, must exist in `cohorts` below. */
  active_cohort: string;
  /** 7 cohorts × {start, end} ISO date strings (Plan §9). */
  cohorts: Record<string, { start: string; end: string }>;

  // ----- Autoresearch (Plan §1, §8) -----
  autoresearch: {
    agent_mutation_cooldown_hours: number;
    keep_revert_lockout_days: number;
    keep_threshold_delta_sharpe: number;
    monthly_modification_cap_per_cohort: number;
    evaluation_horizon_trading_days: number;
  };

  // ----- Data vendors (Phase 0) -----
  data_vendors: Record<string, string>;
  tool_vendors: Record<string, string>;

  // ----- Open extension for fields not yet stabilised. -----
  [key: string]: unknown;
}

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
 * Ergonomic helper around a BridgeClient. Provides typed wrappers for the
 * subset of RPC methods the TS front-end currently uses (Phase 0/1: tools.* +
 * config.* + cache.* + read-only paper.* + backtest.*). The Python sidecar
 * registers more (`paper.{register,login,logout,reset_account,buy,sell,
 * suggest_order_from_signal}`, `cache.{clear,details}`); those are reachable
 * via ``client.call(method, params)`` and will get typed wrappers when Phase 8
 * lands the paper-trading workflow.
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

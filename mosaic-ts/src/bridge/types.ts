/**
 * Wire-level type definitions for the JSON-RPC methods exposed by
 * `mosaic.bridge` (62 RPC methods across 13 namespaces: tools / config / cache /
 * calendar / paper / backtest / scorecard / darwinian / prompts / autoresearch /
 * prism / janus / mirofish).
 *
 * Keep this file as the single source of truth for the wire-level shapes.
 * If a method's params/result change on the Python side, update the type
 * here in the same commit.
 *
 * The :class:`BridgeApi` helper at the bottom provides typed wrappers for all
 * 13 namespaces (incl. the Phase 8 paper-trading write surface). The only
 * registered methods without a typed wrapper today are `cache.details` and the
 * `mirofish.{save,get}_context` pair (added in 7M Step 1; wrappers land with
 * Step 2) — all reachable via ``client.call(method, params)`` meanwhile.
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

export interface PaperOrderResult {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  amount: number;
  commission: number;
  total_cost?: number;
  pnl?: number;
}

export interface PaperSuggestion {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  target_weight_pct: number;
  rating: string;
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

// --------------------------------------------------------- backtest cache (Phase 3.5C)

/** Shape accepted by ``backtest.append_actions`` — one trade decision. */
export interface BacktestActionInput {
  ticker: string;
  action: "BUY" | "SELL" | "HOLD" | "REDUCE";
  target_weight: number;
  holding_period?: string;
  dissent_notes?: string;
}

/** Returned by ``backtest.get_run`` and ``backtest.list_runs``. */
export interface BacktestRunInfo {
  id: number;
  cohort: string;
  start_date: string;
  end_date: string;
  prompt_commit_hash: string;
  created_at: string;
  /** ISO-8601 when stage-1 fill finished; null while still in progress. */
  completed_at: string | null;
  /** Only present in ``backtest.get_run`` response. */
  action_count?: number;
  distinct_trade_days?: number;
  first_trade_date?: string | null;
  last_trade_date?: string | null;
}

/** Returned by ``backtest.run_historical``. Mirrors
 *  ``mosaic.backtest.qlib_runner.BacktestMetrics`` (Phase 3.5D dataclass). */
export interface BacktestMetricsResult {
  run_id: number;
  cohort: string;
  start_date: string;
  end_date: string;
  benchmark: string;
  n_trade_days: number;
  /** Compounded total return over the window, decimal (0.05 = 5%). */
  total_return: number;
  /** ``(1 + total_return)^(252/n) - 1`` — annualized. */
  annualized_return: number;
  /** ``mean(daily_return) / std(daily_return) * sqrt(252)``. */
  sharpe: number;
  /** Signed (negative) value, e.g. -0.20 means -20% peak-to-trough. */
  max_drawdown: number;
  benchmark_return: number;
  /** ``total_return - benchmark_return`` (no CAPM beta). */
  alpha: number;
  initial_cash: number;
  final_value: number;
}

// --------------------------------------------------------- scorecard / darwinian (Phase 3D)

/** Outcome of a ``scorecard.score_pending`` call. */
export interface ScorecardScoreOutcome {
  /** Rows that received forward-return + alpha values. */
  scored: number;
  /** Rows whose 5d horizon has not yet matured at the current date. */
  skipped_immature: number;
  /** Rows where Tushare returned no close (suspension / missing data). */
  skipped_missing: number;
}

/** One row of ``scorecard.list_skill`` aggregate output. */
export interface SkillRow {
  agent: string;
  /** Sample mean of alpha_5d across the queried window. */
  mean_alpha_5d: number;
  /**
   * Annualized Sharpe over the queried window (since `since` param to
   * all-time). Null when n_obs < 5. Note: this is NOT the rolling-30-day
   * Sharpe — that lives on ``DarwinianAgentWeight.sharpe_30``.
   * Renamed from ``sharpe_30d`` in the PR #3 review hotfix to make the
   * window-dependent semantic explicit.
   */
  sharpe_window: number | null;
  n_obs: number;
}

export interface CioAction {
  ticker: string;
  action: string;
  target_weight_pct: number | null;
  rationale_snapshot: string | null;
  forward_return_5d: number | null;
  scored_at: string | null;
}

export interface CioActions {
  cohort: string;
  date: string | null;
  actions: CioAction[];
}

export interface WinRateRow {
  ticker: string;
  win_rate: number;
  n: number;
  avg_dir_return_5d: number;
}

/** Outcome of a ``darwinian.compute`` call. */
export interface DarwinianComputeOutcome {
  /** Rows upserted into ``darwinian_weights``. */
  written: number;
  /** Of which, how many fell back to weight=1.0 (insufficient observations). */
  agents_uniform_fallback: number;
}

/** Per-agent Darwinian weight payload returned by ``darwinian.get_weights``. */
export interface DarwinianAgentWeight {
  /** Continuous multiplier in [0.3, 2.5] (Plan §11.3 design decision #6). */
  weight: number;
  /** Annualized rolling 30-day Sharpe; null when insufficient data. */
  sharpe_30: number | null;
  /** Annualized rolling 90-day Sharpe; null when insufficient data. */
  sharpe_90: number | null;
  /** 1 (best) to 4 (worst); informational only — multiplier is the weight. */
  quartile: number | null;
}

/** ``{ <agent>: DarwinianAgentWeight }``; empty object means no weights computed yet. */
export type DarwinianWeightTable = Record<string, DarwinianAgentWeight>;

// --------------------------------------------------------- prompts (Phase 4B)

export type PromptLang = "zh" | "en";

/** Returned by ``prompts.read``. ``path`` is repo-relative. */
export interface PromptReadResult {
  content: string;
  path: string;
}

/** Returned by ``prompts.write``: commit fields present only when a branch
 *  was given (the mutation path); working-tree writes return just ``paths``. */
export interface PromptWriteResult {
  commit_hash?: string;
  branch?: string;
  paths: string[];
}

// --------------------------------------------------------- autoresearch (Phase 4C/4D)

/** Returned by ``autoresearch.trigger``. */
export interface AutoresearchTriggerResult {
  /** Null when triggered with dry_run=true (no version row was created). */
  version_id: number | null;
  agent: string;
  branch_name: string;
  base_commit: string;
  dry_run?: boolean;
}

/** One entry in the ``autoresearch.evaluate_pending`` results array. */
export interface AutoresearchEvalResult {
  version_id: number;
  status: string;
  delta_sharpe?: number;
  detail?: string;
}

/** A single autoresearch log row from ``autoresearch.get_log``. */
export interface AutoresearchLogEntry {
  id: number;
  prompt_version_id: number | null;
  event: string;
  detail: string | null;
  created_at: string;
  cohort: string | null;
  agent: string | null;
  branch_name: string | null;
}

/** A pending feature branch from ``autoresearch.list_active_branches``. */
export interface AutoresearchActiveBranch {
  id: number;
  cohort: string;
  agent: string;
  branch_name: string;
  base_commit_hash: string;
  modification_commit_hash: string | null;
  created_at: string;
}

// --------------------------------------------------------- PRISM (Phase 5)

export interface CohortInfo {
  name: string;
  start: string;
  end: string;
  description: string;
  has_branch: boolean;
  n_runs: number;
  last_run_date: string | null;
}

export interface CohortTrainResult {
  started: boolean;
  cohort: string;
  message: string;
  run_id?: number;
}

export interface CohortStatus {
  cohort: string;
  n_runs: number;
  n_mutations: number;
  last_date: string | null;
  sharpe_latest: number | null;
}

export interface CohortComparison {
  cohort: string;
  n_runs: number;
  n_mutations: number;
  n_kept: number;
  n_reverted: number;
  latest_date: string | null;
}

// --------------------------------------------------------- JANUS (Phase 6)

export interface JanusCohortAccuracy {
  hit_rate: number;
  sharpe: number;
  n: number;
}

export interface JanusRegime {
  date?: string;
  dominant_cohort: string | null;
  regime_label: string;
  concentration: number;
  concentration_state?: "CONCENTRATED" | "DIFFUSE";
}

export interface JanusWeights {
  date: string;
  cohort_weights: Record<string, number>;
  cohort_accuracy: Record<string, JanusCohortAccuracy>;
}

export interface JanusBlendedRec {
  ticker: string;
  direction: "LONG" | "SHORT";
  blended_weight_pct: number;
  contested: boolean;
  cohort_breakdown: Record<
    string,
    { action: string; target_weight_pct: number | null; weight: number }
  >;
}

export interface JanusRunResult {
  date: string;
  cohort_weights: Record<string, number>;
  regime: JanusRegime;
  cohort_accuracy: Record<string, JanusCohortAccuracy>;
  blended_recommendations: JanusBlendedRec[];
  contested_tickers: string[];
}

export interface JanusHistoryEntry {
  id: number;
  date: string;
  weights_json: string;
  regime_label: string | null;
  dominant_cohort: string | null;
  concentration: number | null;
  n_blended: number;
  n_contested: number;
  created_at: string;
}

// --------------------------------------------------------- MiroFish (Phase 7)

export interface MirofishPricePath {
  ticker: string;
  start_price: number;
  prices: number[];
  cumulative_return: number;
  volatility: number;
}

export interface MirofishScenario {
  scenario_type: string;
  scenario_name: string;
  probability: number;
  num_days: number;
  reflexive?: boolean;
  engine?: string;
  emergence?: { n_actor_classes: number; herding_index: number };
  price_paths: Record<string, MirofishPricePath>;
  events: Array<{ day: number; date: string; event: string; impact: string }>;
  final_state: { regime: string; narrative: string; csi300_return: number };
}

export interface MirofishRecommendation {
  recommendation: "BUY" | "SELL" | "HOLD";
  tickers: string[];
  conviction: number;
  reasoning?: string;
}

export interface MirofishHistoryEntry {
  id: number;
  date: string;
  agent: string;
  scenario_type: string;
  n_scenarios: number | null;
  avg_score: number | null;
  detail_json: string | null;
  created_at: string;
}

// --------------------------------------------------------- helpers

/**
 * Ergonomic helper around a BridgeClient. Provides typed wrappers across all 13
 * namespaces: tools.* / config.* / cache.* / calendar.* / paper.* (incl. the
 * Phase 8 write surface: register/login/logout/reset_account/buy/sell/
 * suggest_order_from_signal) / backtest.* / scorecard.* / darwinian.* /
 * prompts.* / autoresearch.* / prism.* / janus.* / mirofish.*. The only
 * registered methods still unwrapped are `cache.details` and
 * `mirofish.{save,get}_context` (7M Step 1; wrappers land with Step 2) —
 * reachable meanwhile via ``client.call(method, params)``.
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

  // paper.* write surface (Phase 8)
  paperRegister(params: { username: string; password: string; db_path?: string }): Promise<{
    username: string;
  }> {
    return this.client.call<{ username: string }>("paper.register", params);
  }

  paperLogin(params: { username: string; password: string; db_path?: string }): Promise<{
    ok: boolean;
    username: string | null;
  }> {
    return this.client.call<{ ok: boolean; username: string | null }>("paper.login", params);
  }

  paperLogout(opts: { db_path?: string } = {}): Promise<{ logged_out: string | null }> {
    return this.client.call<{ logged_out: string | null }>("paper.logout", opts);
  }

  paperResetAccount(
    opts: { user_id?: string; initial_cash?: number; db_path?: string } = {},
  ): Promise<{ ok: boolean }> {
    return this.client.call<{ ok: boolean }>("paper.reset_account", opts);
  }

  paperBuy(params: {
    ticker: string;
    quantity: number;
    user_id?: string;
    analysis_id?: string;
    db_path?: string;
  }): Promise<PaperOrderResult> {
    return this.client.call<PaperOrderResult>("paper.buy", params);
  }

  paperSell(params: {
    ticker: string;
    quantity: number;
    user_id?: string;
    analysis_id?: string;
    db_path?: string;
  }): Promise<PaperOrderResult> {
    return this.client.call<PaperOrderResult>("paper.sell", params);
  }

  paperSuggestOrderFromSignal(params: {
    ticker: string;
    state: Record<string, unknown>;
    user_id?: string;
    db_path?: string;
  }): Promise<PaperSuggestion | null> {
    return this.client.call<PaperSuggestion | null>("paper.suggest_order_from_signal", params);
  }

  // backtest.*
  backtestRunCandidatePool(params: BacktestRunParams): Promise<BacktestResult> {
    return this.client.call<BacktestResult>("backtest.run_candidate_pool", params);
  }

  // backtest.* (Phase 3.5C two-stage cache)
  backtestCreateRun(params: {
    cohort: string;
    start_date: string;
    end_date: string;
    prompt_commit_hash: string;
  }): Promise<{ run_id: number }> {
    return this.client.call<{ run_id: number }>("backtest.create_run", params);
  }

  backtestAppendActions(
    runId: number,
    tradeDate: string,
    actions: BacktestActionInput[],
  ): Promise<{ appended: number }> {
    return this.client.call<{ appended: number }>("backtest.append_actions", {
      run_id: runId,
      trade_date: tradeDate,
      actions,
    });
  }

  backtestCompleteRun(runId: number): Promise<{ ok: boolean }> {
    return this.client.call<{ ok: boolean }>("backtest.complete_run", { run_id: runId });
  }

  backtestGetRun(runId: number): Promise<BacktestRunInfo> {
    return this.client.call<BacktestRunInfo>("backtest.get_run", { run_id: runId });
  }

  backtestListRuns(opts?: {
    cohort?: string;
    since?: string;
  }): Promise<{ runs: BacktestRunInfo[] }> {
    return this.client.call<{ runs: BacktestRunInfo[] }>("backtest.list_runs", opts ?? {});
  }

  backtestRunHistorical(
    runId: number,
    opts?: {
      initial_cash?: number;
      benchmark?: string;
      open_cost?: number;
      close_cost?: number;
      deal_price?: string;
    },
  ): Promise<BacktestMetricsResult> {
    return this.client.call<BacktestMetricsResult>("backtest.run_historical", {
      run_id: runId,
      ...opts,
    });
  }

  // calendar.* (PR #4 review hotfix #2 — replaces weekday-only filter)
  calendarListTradingDays(start: string, end: string): Promise<{ trading_days: string[] }> {
    return this.client.call<{ trading_days: string[] }>("calendar.list_trading_days", {
      start,
      end,
    });
  }

  calendarIsTradingDay(date: string): Promise<{ is_trading: boolean }> {
    return this.client.call<{ is_trading: boolean }>("calendar.is_trading_day", { date });
  }

  calendarNextTradingDay(date: string, n = 1): Promise<{ date: string }> {
    return this.client.call<{ date: string }>("calendar.next_trading_day", { date, n });
  }

  // scorecard.* (Phase 3D)
  scorecardAppend(state: Record<string, unknown>): Promise<{ ingested: number }> {
    return this.client.call<{ ingested: number }>("scorecard.append", { state });
  }

  scorecardScorePending(cohort: string, today: string): Promise<ScorecardScoreOutcome> {
    return this.client.call<ScorecardScoreOutcome>("scorecard.score_pending", {
      cohort,
      today,
    });
  }

  scorecardListSkill(cohort: string, since?: string): Promise<{ rows: SkillRow[] }> {
    return this.client.call<{ rows: SkillRow[] }>("scorecard.list_skill", {
      cohort,
      ...(since ? { since } : {}),
    });
  }

  scorecardLatestCioActions(cohort: string): Promise<CioActions> {
    return this.client.call<CioActions>("scorecard.latest_cio_actions", { cohort });
  }

  scorecardWinRate(cohort: string, since?: string): Promise<{ rows: WinRateRow[] }> {
    return this.client.call<{ rows: WinRateRow[] }>("scorecard.win_rate", {
      cohort,
      ...(since ? { since } : {}),
    });
  }

  // darwinian.* (Phase 3D)
  darwinianCompute(cohort: string, today: string): Promise<DarwinianComputeOutcome> {
    return this.client.call<DarwinianComputeOutcome>("darwinian.compute", {
      cohort,
      today,
    });
  }

  darwinianGetWeights(cohort: string, date?: string): Promise<{ weights: DarwinianWeightTable }> {
    return this.client.call<{ weights: DarwinianWeightTable }>("darwinian.get_weights", {
      cohort,
      ...(date ? { date } : {}),
    });
  }

  // prompts.* (Phase 4B)
  promptsRead(
    agent: string,
    cohort: string,
    lang: PromptLang,
    ref?: string,
  ): Promise<PromptReadResult> {
    return this.client.call<PromptReadResult>("prompts.read", {
      agent,
      cohort,
      lang,
      ...(ref ? { ref } : {}),
    });
  }

  promptsWrite(params: {
    agent: string;
    cohort: string;
    contents: Partial<Record<PromptLang, string>>;
    branch?: string;
    message?: string;
  }): Promise<PromptWriteResult> {
    return this.client.call<PromptWriteResult>("prompts.write", params);
  }

  // autoresearch.* (Phase 4C/4D)
  autoresearchTrigger(params: {
    cohort: string;
    force_agent?: string;
    dry_run?: boolean;
  }): Promise<AutoresearchTriggerResult> {
    return this.client.call<AutoresearchTriggerResult>("autoresearch.trigger", params);
  }

  autoresearchRecordMutation(params: {
    version_id: number;
    commit_hash: string;
    summary?: string;
  }): Promise<{ ok: boolean }> {
    return this.client.call<{ ok: boolean }>("autoresearch.record_mutation", params);
  }

  autoresearchEvaluatePending(params?: {
    cohort?: string;
    version_id?: number;
  }): Promise<{ results: AutoresearchEvalResult[] }> {
    return this.client.call<{ results: AutoresearchEvalResult[] }>(
      "autoresearch.evaluate_pending",
      params ?? {},
    );
  }

  autoresearchGetLog(params?: {
    cohort?: string;
    days?: number;
  }): Promise<{ entries: AutoresearchLogEntry[] }> {
    return this.client.call<{ entries: AutoresearchLogEntry[] }>(
      "autoresearch.get_log",
      params ?? {},
    );
  }

  autoresearchListActiveBranches(params?: {
    cohort?: string;
  }): Promise<{ branches: AutoresearchActiveBranch[] }> {
    return this.client.call<{ branches: AutoresearchActiveBranch[] }>(
      "autoresearch.list_active_branches",
      params ?? {},
    );
  }

  autoresearchRevertModification(params: { version_id: number }): Promise<{ ok: boolean }> {
    return this.client.call<{ ok: boolean }>("autoresearch.revert_modification", params);
  }

  autoresearchPrepareWorktree(params: { branch: string }): Promise<{ path: string }> {
    return this.client.call<{ path: string }>("autoresearch.prepare_worktree", params);
  }

  autoresearchCleanupWorktree(params: { path: string }): Promise<{ ok: boolean }> {
    return this.client.call<{ ok: boolean }>("autoresearch.cleanup_worktree", params);
  }

  // prism.* (Phase 5)
  prismListCohorts(): Promise<{ cohorts: CohortInfo[] }> {
    return this.client.call<{ cohorts: CohortInfo[] }>("prism.list_cohorts", {});
  }

  prismTrainCohort(params: {
    cohort_name: string;
    start_date?: string;
    end_date?: string;
    dry_run?: boolean;
  }): Promise<CohortTrainResult> {
    return this.client.call<CohortTrainResult>("prism.train_cohort", params);
  }

  prismCohortStatus(params: { cohort_name: string }): Promise<CohortStatus> {
    return this.client.call<CohortStatus>("prism.cohort_status", params);
  }

  prismCompareCohorts(params?: {
    metric?: string;
    since?: string;
  }): Promise<{ comparisons: CohortComparison[] }> {
    return this.client.call<{ comparisons: CohortComparison[] }>(
      "prism.compare_cohorts",
      params ?? {},
    );
  }

  prismCompleteCohortRun(params: {
    run_id: number;
    llm_calls?: number;
    llm_cost_usd?: number;
    cio_action?: string;
    cio_target_weight?: number;
  }): Promise<{ ok: boolean }> {
    return this.client.call<{ ok: boolean }>("prism.complete_cohort_run", params);
  }

  // janus.* (Phase 6)
  janusRunDaily(params?: { date?: string; window_days?: number }): Promise<JanusRunResult> {
    return this.client.call<JanusRunResult>("janus.run_daily", params ?? {});
  }

  janusGetWeights(params?: { date?: string; window_days?: number }): Promise<JanusWeights> {
    return this.client.call<JanusWeights>("janus.get_weights", params ?? {});
  }

  janusRegime(params?: { date?: string; window_days?: number }): Promise<JanusRegime> {
    return this.client.call<JanusRegime>("janus.regime", params ?? {});
  }

  janusGetHistory(params?: { days?: number }): Promise<{ history: JanusHistoryEntry[] }> {
    return this.client.call<{ history: JanusHistoryEntry[] }>("janus.get_history", params ?? {});
  }

  // mirofish.* (Phase 7)
  mirofishGenerateScenarios(params?: {
    num_days?: number;
    seed?: number;
    scenarios?: string[];
    start_prices?: Record<string, number>;
    reflexivity?: boolean;
    engine?: "montecarlo" | "swarm";
  }): Promise<{ scenarios: MirofishScenario[]; engine?: string }> {
    return this.client.call<{ scenarios: MirofishScenario[]; engine?: string }>(
      "mirofish.generate_scenarios",
      params ?? {},
    );
  }

  mirofishScoreRecommendation(params: {
    recommendation: MirofishRecommendation;
    scenario: MirofishScenario;
    scorer?: "terminal" | "path_aware";
  }): Promise<{ score: number }> {
    return this.client.call<{ score: number }>("mirofish.score_recommendation", params);
  }

  mirofishRecordRun(params: {
    agent: string;
    scenario_type: string;
    n_scenarios?: number;
    avg_score?: number;
    date?: string;
    detail?: unknown;
  }): Promise<{ id: number }> {
    return this.client.call<{ id: number }>("mirofish.record_run", params);
  }

  mirofishGetHistory(params?: { days?: number }): Promise<{ history: MirofishHistoryEntry[] }> {
    return this.client.call<{ history: MirofishHistoryEntry[] }>(
      "mirofish.get_history",
      params ?? {},
    );
  }
}

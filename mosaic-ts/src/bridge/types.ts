/**
 * Wire-level type definitions for the JSON-RPC methods exposed by
 * `mosaic.bridge`.
 *
 * Keep this file as the single source of truth for the wire-level shapes.
 * If a method's params/result change on the Python side, update the type
 * here in the same commit.
 *
 * The :class:`BridgeApi` helper at the bottom provides typed wrappers for the
 * bridge namespaces used by the TS runtime. Diagnostic-only `cache.details`
 * and fail-closed rejection stubs for retired RPCs remain reachable only via
 * ``client.call(method, params)``.
 */

import type {
  AgentExecutionStageId,
  AgentId,
  AgentSnapshotBundle,
  SignedAgentToolCapability,
} from "../agents/tool_contract.js";
import type { LlmCallRecord } from "../agents/types.js";
import type { BridgeClient } from "./client.js";

export type {
  AgentSnapshotBundle,
  AgentToolCapabilityManifest,
  SignedAgentToolCapability,
} from "../agents/tool_contract.js";

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

export interface ToolCapabilityPrepareRequest {
  graph_run_id: string;
  run_slot_id: string;
  run_id: string;
  node_id: string;
  agent_id: AgentId;
  stage: AgentExecutionStageId;
  as_of: string;
  materialization_request_id: string;
  runtime_inputs: Record<string, unknown>;
  candidate_scope: Record<string, unknown> | null;
  ttl_seconds?: number;
}

export interface ToolCapabilityIssueRequest {
  graph_run_id: string;
  run_slot_id: string;
  run_id: string;
  node_id: string;
  agent_id: AgentId;
  stage: AgentExecutionStageId;
  as_of: string;
  snapshot_bundle_id: string;
  snapshot_bundle_hash: string;
  ttl_seconds?: number;
}

export interface PreparedAgentToolCapability {
  bundle: AgentSnapshotBundle;
  capability: SignedAgentToolCapability;
}

export interface ToolCallResult {
  text: string;
}

export interface SectorModelUsageReport {
  model_subcall_id: string;
  attempted_stage: "DIRECTION_RESEARCH" | "CONFLICT_REVIEW" | "FINAL_SELECTION";
  attempt_index: number;
  attempt_status: "ACCEPTED" | "REJECTED" | "OPERATIONAL_FAILURE";
  input_tokens: number;
  output_tokens: number;
  provider_usage_evidence_id: string;
  provider_usage_evidence_hash: string;
  direction_comparison_audit_id: string | null;
  direction_comparison_audit_hash: string | null;
  conflict_review_id: string | null;
  conflict_review_hash: string | null;
}

export interface SectorModelUsageSummaryReceipt {
  schema_version: "sector_model_usage_summary_receipt_v1";
  usage_summary_receipt_id: string;
  capability_id: string;
  capability_manifest_hash: string;
  graph_run_id: string;
  run_slot_id: string;
  run_id: string;
  node_id: string;
  agent_id: string;
  stage: string;
  as_of: string;
  snapshot_bundle_id: string;
  snapshot_bundle_hash: string;
  pair_root_reservation_id: string | null;
  pair_side: "CHAMPION" | "CANDIDATE" | null;
  budget_contract_ref: {
    budget_contract_id: string;
    budget_contract_version: string;
    budget_contract_hash: string;
  } | null;
  model_subcall_count: number;
  last_attempted_stage:
    | "PRE_MODEL"
    | "DIRECTION_RESEARCH"
    | "CONFLICT_REVIEW"
    | "FINAL_SELECTION"
    | "COMPLETED";
  conflict_review_triggered: boolean;
  input_tokens: number;
  output_tokens: number;
  model_path_disposition: "COMPLETED" | "INCOMPLETE";
  direction_comparison_audit_id: string | null;
  direction_comparison_audit_hash: string | null;
  conflict_review_id: string | null;
  conflict_review_hash: string | null;
  instrumentation_contract_id: string;
  instrumentation_contract_version: string;
  instrumentation_contract_hash: string;
  source_contract_version: string;
  measurement_rule: string;
  usage_ledger_record_id: string;
  usage_ledger_record_hash: string;
  measured_at: string;
  finalized_at: string;
  receipt_signing_key_id: string;
  usage_summary_receipt_hash: string;
  receipt_signature: string;
}

export interface CacheStats {
  api: { count: number; size_mb: number; subdirs: string[] };
  agent_data: { entries: number; size_mb: number; by_method: Record<string, number> };
  signals: { count: number; size_mb: number };
  snapshots: { count: number; size_mb: number; kinds: string[] };
  checkpoints: { count: number; size_mb: number; tickers: string[] };
  total_mb: number;
}

export type CacheCategory = "api" | "agent_data" | "signals" | "snapshots" | "checkpoints";

/**
 * MOSAIC config — fields consumed by the TypeScript runtime are typed below.
 * The bridge also exposes deployment-specific keys, so the index signature
 * keeps only this configuration DTO open. Agent tools themselves are closed
 * by the current signed capability and runtime manifest contracts.
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
  /** 8 cohorts × {start, end} ISO date strings. */
  cohorts: Record<string, { start: string; end: string }>;

  // ----- Autoresearch (Plan §1, §8) -----
  autoresearch: {
    agent_mutation_cooldown_hours: number;
    keep_revert_lockout_days: number;
    keep_threshold_delta_sharpe: number;
    monthly_modification_cap_per_cohort: number;
    evaluation_horizon_trading_days: number;
    /** Opt-in mirror of kept mutations to a self-hosted git server (default off). */
    git?: { push?: boolean; remote?: string };
  };

  // ----- Data vendors (Phase 0) -----
  data_vendors: Record<string, string>;
  tool_vendors: Record<string, string>;
  /** SQLite exact-call cache for routed agent data tools. */
  agent_data_cache?: {
    enabled?: boolean;
    db_path?: string | null;
    read_ttl_seconds?: number | null;
    max_entries?: number | null;
    skip_empty_results?: boolean;
  };

  // ----- MiroFish (Plan §11.8 / 7M) -----
  /** Forward-simulation toggles. ``inject_context`` (default true) appends one
   *  shared simulation-only MiroFish context to CRO, execution, and CIO. */
  mirofish?: {
    engine?: string;
    scorer?: string;
    inject_context?: boolean;
  };

  // ----- Legacy Darwinian-v1 audit/replay configuration -----
  darwinian?: {
    weight_rewrite_enabled?: boolean;
    weight_start?: number;
    weight_floor?: number;
    weight_ceiling?: number;
    top_multiplier?: number;
    bottom_multiplier?: number;
    min_ranked_agents_per_scope?: number;
    min_scored_observations_per_agent?: number;
    min_matured_agents_for_update?: number;
  };

  // ----- Open extension for fields not yet stabilised. -----
  [key: string]: unknown;
}

/** Result of data.incremental (qlib dataset append). */
export interface DataIncrementalResult {
  kind: "stock" | "etf";
  returncode: number;
  qlib_dir: string | null;
  ok: boolean;
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
  order_intent_key: string | null;
  final_target_hash: string | null;
  base_account_snapshot_hash: string | null;
  fill_status: "filled" | "partial" | "rejected";
  filled_quantity: number;
  residual_quantity: number;
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
  order_intent_key?: string | null;
  final_target_hash?: string | null;
  base_account_snapshot_hash?: string | null;
  fill_status?: "filled" | "partial" | "rejected";
  filled_quantity?: number;
  residual_quantity?: number;
  idempotent_replay?: boolean;
}

export interface PaperPortfolioSnapshot {
  account: PaperAccount;
  positions: PaperPosition[];
  snapshot_hash: string;
}

export interface PaperSuggestion {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  target_weight_pct: number;
  rating: string;
}

/** Backtest = qlib two-stage cache (Phase 3.5C); the backtrader candidate-pool
 *  path was dropped in Phase 8. */

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
  prompt_commit_ref?: string | null;
  prompt_repo_id?: string | null;
  prompt_sha256?: string | null;
  code_commit_hash?: string | null;
  created_at: string;
  /** ISO-8601 when stage-1 fill finished; null while still in progress. */
  completed_at: string | null;
  /** Only present in ``backtest.get_run`` response. */
  action_count?: number;
  distinct_trade_days?: number;
  first_trade_date?: string | null;
  last_trade_date?: string | null;
}

export interface BacktestActionSummary {
  run_id: number;
  action_count: number;
  trade_day_count: number;
  first_trade_date: string | null;
  last_trade_date: string | null;
  ticker_count: number;
  turnover_proxy: number;
  max_observed_holding_days: number;
  stale_thesis_proxy_count: number;
  action_counts: Record<string, number>;
  holding_period_counts: Record<string, number>;
  metric_availability: Record<string, string>;
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
  /** Macro signals that received benchmark-5d scoring. */
  macro_scored: number;
  /** Macro signals whose 5d horizon has not yet matured. */
  macro_skipped_immature: number;
  /** Macro signals where benchmark data was missing. */
  macro_skipped_missing: number;
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

/** One row of ``scorecard.list_macro_skill`` (autoresearch macro plan). */
export interface MacroSkillRow {
  agent: string;
  n_obs: number;
  /** MVP primary ranking metric (vol-scaled directional score). */
  mean_raw_macro_score_5d: number | null;
  /** Diagnostics (Phase 8); null in the MVP. */
  mean_effective_macro_score_5d: number | null;
  hit_rate_5d: number | null;
  mean_influence_weight_equal: number | null;
  latest_label_type: string | null;
  label_type_counts: Record<string, number>;
  label_source_status_counts: Record<string, number>;
  primary_label_rate: number | null;
  fallback_label_rate: number | null;
  missing_label_rate: number | null;
  sharpe_window: number | null;
  latest_signal_date: string | null;
}

export interface CioAction {
  ticker: string;
  action: string;
  target_weight_pct: number | null;
  current_weight_pct?: number | null;
  delta_weight_pct?: number | null;
  position_decision?: "HOLD" | "ADD" | "REDUCE" | "EXIT" | null;
  position_decision_reason?: string | null;
  override_reason?: string | null;
  thesis_status?: "intact" | "weakened" | "broken" | "expired" | null;
  risk_flags_json?: string | null;
  verified_knob_audit_json?: string | null;
  decision_agent_audits_json?: string | null;
  dissent_notes?: string | null;
  rationale_snapshot: string | null;
  forward_return_5d: number | null;
  scored_at: string | null;
}

export interface CioActions {
  cohort: string;
  date: string | null;
  actions: CioAction[];
}

export interface AgentDisplayNarrativeRow {
  schema_version: "agent_display_narrative_v1";
  narrative_id: string;
  agent_id: string;
  layer: "macro" | "sector" | "superinvestor" | "decision";
  language: "zh" | "en";
  source: "ACCEPTED_OUTPUT" | "NO_EVALUATION_OBJECT" | "NON_PRODUCTION_STRUCTURED_OUTPUT";
  source_output_id: string | null;
  source_output_hash: string;
  narrative_text: string;
  ui_only: true;
}

export interface AgentDisplayNarratives {
  schema_version: "agent_display_narrative_bundle_v1";
  cohort: string;
  date: string | null;
  trace_id: string | null;
  bundle_hash: string | null;
  language: "zh" | "en" | null;
  narratives: AgentDisplayNarrativeRow[];
}

export interface WinRateRow {
  ticker: string;
  win_rate: number;
  n: number;
  avg_dir_return_5d: number;
}

/** Audit-only outcome of the legacy-unverified ``darwinian.compute`` call. */
export interface DarwinianComputeOutcome {
  status: "legacy_unverified";
  audit_only: true;
  /** Rows upserted into ``darwinian_weights``. */
  written: number;
  /** Of which, how many fell back to weight=1.0 (insufficient observations). */
  agents_uniform_fallback: number;
}

/** Legacy-unverified weight payload returned only for audit/replay. */
export interface DarwinianAgentWeight {
  /** Continuous multiplier in [0.3, 2.5] (Plan §11.3 design decision #6). */
  weight: number;
  /** Annualized rolling 30-day Sharpe; null when insufficient data. */
  sharpe_30: number | null;
  /** Annualized rolling 90-day Sharpe; null when insufficient data. */
  sharpe_90: number | null;
  /** 1 (best) to 4 (worst); informational only — multiplier is the weight. */
  quartile: number | null;
  /** Unified Darwinian metadata. Present when Phase-9 rows are written. */
  layer?: "macro" | "sector" | "superinvestor" | "decision" | string | null;
  previous_weight?: number | null;
  performance_metric?: string | null;
  performance_value?: number | null;
  normalized_performance?: number | null;
  rank_scope?: string | null;
  update_action?: "up" | "down" | "unchanged" | "skipped" | "legacy_sharpe" | string | null;
  n_obs?: number | null;
  source_table?: string | null;
  source_date?: string | null;
  updated_at?: string | null;
}

/** ``{ <agent>: DarwinianAgentWeight }``; empty object means no weights computed yet. */
export type DarwinianWeightTable = Record<string, DarwinianAgentWeight>;

export interface DarwinianOutcomeMaturationResult {
  agent_id: string;
  scheduled_sample_id: string;
  outcome_schedule_slot_id: string;
  outcome_schedule_slot_hash: string;
  outcome_due_at: string;
  maturation_status:
    | "SCORE"
    | "ABSTAIN"
    | "PENDING_INPUT_UNAVAILABLE"
    | "PENDING_ELIGIBILITY_AUDIT_MISSING"
    | "PENDING_PREPARATION_UNAVAILABLE"
    | "PENDING_TERMINAL_COMPANION_UNAVAILABLE";
  matured_at?: string;
  failure_code?:
    | "REQUIRED_OUTCOME_PROJECTION_UNAVAILABLE"
    | "REQUIRED_ELIGIBILITY_AUDIT_UNAVAILABLE"
    | "REQUIRED_OUTCOME_PREPARATION_UNAVAILABLE"
    | "REQUIRED_TERMINAL_OUTCOME_COMPANION_UNAVAILABLE";
  audit_revision_id?: string;
  realized_outcome_observation_id?: string;
  outcome_label_id?: string | null;
  darwin_application_mode?: "DOWNSTREAM_USAGE_WEIGHT" | "EVOLUTION_ONLY";
}

export interface DarwinianOutcomeMaturationBatch {
  schema_version: "outcome_maturation_batch_v2";
  production_variant_roster_revision_id: string;
  production_variant_roster_id: string;
  cutoff_at: string;
  due_pending_count: number;
  scored_count: number;
  abstained_count: number;
  unresolved_count: number;
  not_due_count: number;
  results: DarwinianOutcomeMaturationResult[];
  maturation_batch_hash: string;
}

export interface DarwinianMaterializeDueOutcomesResult {
  outcome_maturation: DarwinianOutcomeMaturationBatch;
}

export interface DarwinianRefreshV2WindowsResult extends DarwinianMaterializeDueOutcomesResult {
  evaluation_windows: Array<Record<string, unknown>>;
}

export interface DarwinianPublishV2UpdatesResult extends DarwinianMaterializeDueOutcomesResult {
  published_batches: Array<Record<string, unknown>>;
  publication_status: "PUBLISHED" | "BLOCKED_UNRESOLVED_DUE_OUTCOMES";
}

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
  target?: "private_git" | "project_git" | "working_tree";
  prompt_repo_id?: string;
  prompt_base_commit_hash?: string;
  prompt_commit_hash?: string;
  prompt_sha256?: string;
  commit_hash?: string;
  branch?: string;
  paths: string[];
}

export interface PromptInitPrivateRepoResult {
  repo_root: string;
  prompts_root: string;
  seeded: boolean;
  commit_hash: string;
}

export interface PromptVersionAuditRow {
  id: number;
  cohort: string;
  agent: string;
  status: string;
  branch_name: string;
  base_commit_hash: string;
  modification_commit_hash?: string | null;
  prompt_repo_id?: string | null;
  prompt_base_commit_hash?: string | null;
  prompt_sha256?: string | null;
  code_commit_hash?: string | null;
  mutation_id?: string | null;
  mutation_lifecycle?: string | null;
  delta_sharpe?: number | null;
  created_at?: string | null;
  decided_at?: string | null;
  modification_summary?: string | null;
}

export interface PromptPreflightRow {
  agent: string;
  layer: string;
  cohort: string;
  lang: PromptLang;
  status: "ready" | "blocked";
  blocked_reason?:
    | "private_prompt_unavailable"
    | "prompt_provenance_unavailable"
    | "private_prompt_repo_dirty";
  prompt_repo_id?: string;
  prompt_repo_revision?: string;
  prompt_file_path?: string;
  prompt_sha256?: string;
  resolved_source?: "private_repo" | "private_root";
  fallback_used: boolean;
}

export interface PromptPreflightResult {
  ready: boolean;
  cohort: string;
  expected_prompt_repo_id: string;
  source_status: {
    ready: boolean;
    blocked_reason: string;
    resolved_source: "" | "private_repo" | "private_root";
    prompt_repo_id: string;
    prompt_repo_revision: string;
    prompt_repo_dirty_count: number;
  };
  row_count: number;
  blocked_count: number;
  rows: PromptPreflightRow[];
}

export interface PromptContractCheckRow {
  agent: string;
  layer: string;
  lang: PromptLang;
  prompt_repo_id: string;
  prompt_repo_revision: string;
  prompt_file_path: string;
  prompt_sha256: string;
  prompt_contract_check_ref: string;
  benchmark_run_id: string;
  ready: boolean;
  blockers: string[];
  contract_categories: Record<string, boolean>;
}

export interface PromptContractCheckResult {
  schema_version: "prompt_contract_check_v1";
  contract_version: string;
  benchmark_run_id: string;
  cohort: string;
  ready: boolean;
  row_count: number;
  ready_count: number;
  blocked_count: number;
  blocked_reasons: string[];
  counts_by_layer: Record<string, number>;
  counts_by_language: Record<string, number>;
  counts_by_ready_status: Record<string, number>;
  counts_by_blocker_code: Record<string, number>;
  rows: PromptContractCheckRow[];
}

export interface PromptFormalReleaseCheckRow {
  agent: string;
  layer: string;
  lang: PromptLang;
  benchmark_run_id: string;
  prompt_version_id: number;
  prompt_repo_id: string;
  prompt_repo_revision: string;
  prompt_file_path: string;
  prompt_sha256: string;
  audit_version_ref: string;
  verify_release_ref: string;
  leak_drift_check_ref: string;
  prompt_contract_check_ref: string;
  verify_release_passed: boolean;
  leak_drift_passed: boolean;
  prompt_contract_check_passed: boolean;
  ready: boolean;
  blockers: string[];
}

export interface PromptFormalReleaseChecksResult {
  schema_version: "prompt_formal_release_checks_v1";
  benchmark_run_id: string;
  cohort: string;
  ready: boolean;
  row_count: number;
  ready_count: number;
  blocked_count: number;
  blocked_reasons: string[];
  prompt_source_status: PromptPreflightResult["source_status"];
  rows: PromptFormalReleaseCheckRow[];
}

export interface PromptReleaseCheckResult {
  ready: boolean;
  checks: Record<string, boolean>;
  details: Record<string, unknown>;
  pin: {
    version_id: number;
    cohort: string;
    agent: string;
    code_commit_hash?: string | null;
    prompt_repo_id?: string | null;
    prompt_commit_hash?: string | null;
    prompt_sha256?: string | null;
    mutation_id?: string | null;
    experiment_id?: string | null;
    keep_decision_hash?: string | null;
    evaluation_result_hash?: string | null;
    transaction_manifest_hash?: string | null;
  };
}

// --------------------------------------------------------- rke (Part 1 context/export)

export interface RkeAgentResearchContextResult {
  schema_version: "rke_agent_research_context_v1";
  agent_id: string;
  layer: string;
  as_of_date: string;
  ranking_policy_id: string;
  research_only: boolean;
  production_signal_allowed: boolean;
  actionability: string;
  summary: Record<string, unknown>;
  context_items: Array<Record<string, unknown>>;
  no_prior_reasons: string[];
}

export interface RkeMacroAgentPriorsResult {
  accepted: boolean;
  schema_version: string;
  agent_id: string;
  as_of_date: string;
  prior_count: number;
  priors: Array<Record<string, unknown>>;
  gap_reasons: string[];
  no_source_prose: boolean;
  source_policy: string;
  use_policy: string;
  production_signal_allowed: boolean;
}

// --------------------------------------------------------- rke_benchmark (Part 2 E2)

export interface RkeBenchmarkEpisode {
  episode_id: string;
  regime: string;
  as_of_dates: string[];
}

export interface RkeBenchmarkModelConfig {
  model_config_id: string;
  runner: string;
  model_family?: string;
  required: boolean;
}

export interface RkeBenchmarkPromptPreflightSummary {
  ready: boolean;
  row_count: number;
  blocked_count: number;
  blocked_reasons: string[];
  source_status: PromptPreflightResult["source_status"];
  fallback_used: boolean;
}

export interface RkeAllAgentPromptProvenanceRow {
  agent: string;
  layer: string;
  lang: string;
  prompt_file_path: string;
  prompt_repo_id: string;
  prompt_repo_revision: string;
  prompt_sha256: string;
  benchmark_run_id: string;
  prompt_version_id: number | null;
  audit_version_ref: string;
  verify_release_ref: string;
  leak_drift_check_ref: string;
  prompt_contract_check_ref: string;
  prompt_contract_check_passed: boolean;
  fallback_used: boolean;
  ready: boolean;
  blockers: string[];
}

export interface RkeAllAgentPromptProvenanceReadinessResult {
  schema_version: "rke_all_agent_prompt_provenance_readiness_v1";
  readiness_status: "ready" | "blocked_preflight";
  benchmark_run_id: string;
  cohort: string;
  blocked_reasons: string[];
  agent_count: number;
  prompt_row_count: number;
  ready_prompt_row_count: number;
  release_check_count: number;
  prompt_source_status: PromptPreflightResult["source_status"];
  prompt_rows: RkeAllAgentPromptProvenanceRow[];
  all_agent_prompt_provenance_ready: boolean;
  fallback_used: boolean;
  production_prompt_change_allowed: boolean;
}

export interface RkeFixedEpisodeManifestResult {
  schema_version: "rke_fixed_episode_benchmark_manifest_v1";
  benchmark_status: "ready_to_run" | "blocked_preflight";
  cohort: string;
  episode_count: number;
  as_of_date_count: number;
  agent_count: number;
  model_config_count: number;
  planned_run_count: number;
  episodes: RkeBenchmarkEpisode[];
  agents_by_layer: Record<string, string[]>;
  model_configs: RkeBenchmarkModelConfig[];
  input_requirements: string[];
  scoring_metrics: string[];
  prompt_preflight: RkeBenchmarkPromptPreflightSummary;
  manual_review: {
    status: "not_run";
    required: boolean;
    reviewer_timestamp: string | null;
  };
  promotion_allowed: boolean;
}

export interface RkeFixedEpisodeBenchmarkEvidenceResult {
  schema_version: "rke_fixed_episode_benchmark_evidence_v1";
  evidence_status: "ready" | "blocked_preflight";
  benchmark_run_id: string;
  blocked_reasons: string[];
  episode_count: number;
  as_of_date_count: number;
  agent_count: number;
  required_model_config_count: number;
  required_model_config_ids: string[];
  required_per_model_output_count: number;
  required_paired_output_count: number;
  paired_output_count: number;
  model_config_output_counts: Record<string, number>;
  benchmark_quality_summary: {
    benchmark_run_id: string;
    quality_gate_ref: string;
    schema_failure_gate_passed: boolean;
    severe_safety_violation_count: number | null;
    current_data_confirmation_violation_count: number | null;
    fallback_prompt_run_count: number | null;
    covered_episode_count: number | null;
    covered_as_of_date_count: number | null;
    covered_agent_count: number | null;
  };
  prompt_source_status: PromptPreflightResult["source_status"];
  evidence_refs: {
    benchmark_run_id: string;
    episode_manifest_ref: string;
    as_of_date_manifest_ref: string;
    benchmark_runner_ref: string;
    prompt_contract_check_manifest_ref: string;
    model_config_manifest_ref: string;
    paired_output_manifest_ref: string;
    output_schema_validation_report_ref: string;
    deterministic_score_table_ref: string;
    investment_outcome_table_ref: string;
  };
  manual_review: {
    benchmark_run_id: string;
    decision: string;
    reviewer_timestamp: string;
    reviewer_independence_confirmed: boolean;
  };
  promotion_allowed: boolean;
}

export interface RkeAgentClaimFootprintInput {
  replay_run_id?: string;
  episode_id?: string;
  model_config_id?: string;
  agent: string;
  layer?: string;
  as_of_date: string;
  claim_type:
    | "macro_regime_claim"
    | "macro_series_claim"
    | "macro_asset_claim"
    | "sector_claim"
    | "ticker_metric_claim"
    | "style_candidate_claim"
    | "rejection_reason"
    | "portfolio_action_claim"
    | "risk_claim"
    | "dissent_note";
  target: Partial<
    Record<"target_type" | "target_id" | "metric_family" | "ticker" | "sector", string>
  >;
  direction?: string;
  horizon_bucket?: string;
  confidence_bucket?: string;
  rke_context_hash?: string;
  ranking_policy_id?: string;
  retrieval_rank?: number;
  priority_bucket?: string;
  truncated_item_count?: number;
  rke_prior_usage_quality?: string;
  current_data_confirmed?: boolean;
  stale_prior_rejected?: boolean;
  contradictory_prior_handled?: boolean;
  reason_codes?: string[];
  failure_mode_tags?: string[];
  tool_refs?: string[];
  report_claim_refs?: string[];
}

export interface RkeAgentClaimFootprintCaptureResult {
  capture_status: "captured" | "blocked";
  captured_count: number;
  private_rows_path: string;
  failures?: string[];
  aggregate_profile_summary?: {
    benchmark_run_id: string;
    layer_counts: Record<string, number>;
    claim_type_counts: Record<string, number>;
    current_data_confirmed_count: number;
    rke_context_hash_count: number;
    report_claim_ref_count: number;
    report_claim_linked_row_count: number;
    rke_context_report_claim_linked_count: number;
    ranking_policy_id_counts: Record<string, number>;
    retrieval_rank_count: number;
    priority_bucket_counts: Record<string, number>;
    truncation_audit_count: number;
  };
  privacy_scan: {
    private_text_included: boolean;
    source_prose_included: boolean;
    forbidden_field_violation_count: number;
  };
}

export interface RkeAgentFootprintSummaryResult {
  summary_status: "ready" | "blocked" | "empty";
  private_rows_path: string;
  benchmark_run_id: string;
  row_count: number;
  layer_counts: Record<string, number>;
  claim_type_counts: Record<string, number>;
  rke_prior_usage_quality_counts: Record<string, number>;
  current_data_confirmed_count: number;
  stale_prior_rejected_count: number;
  contradictory_prior_handled_count: number;
  rke_context_hash_count: number;
  report_claim_ref_count: number;
  report_claim_linked_row_count: number;
  rke_context_report_claim_linked_count: number;
  ranking_policy_id_counts: Record<string, number>;
  retrieval_rank_count: number;
  priority_bucket_counts: Record<string, number>;
  truncation_audit_count: number;
  privacy_scan: {
    private_text_included: boolean;
    source_prose_included: boolean;
    forbidden_field_violation_count: number;
  };
  failures: string[];
}

export interface RkeAgentProfileEvolutionReadinessResult {
  schema_version: "rke_agent_profile_evolution_readiness_v1";
  readiness_status: "ready" | "blocked_preflight";
  benchmark_run_id: string;
  blocked_reasons: string[];
  summary_status: "ready" | "blocked" | "empty";
  row_count: number;
  required_layers: string[];
  observed_layers: string[];
  missing_layers: string[];
  layer_counts: Record<string, number>;
  claim_type_counts: Record<string, number>;
  rke_context_hash_count: number;
  report_claim_ref_count: number;
  report_claim_linked_row_count: number;
  rke_context_report_claim_linked_count: number;
  ranking_policy_id_counts: Record<string, number>;
  retrieval_rank_count: number;
  priority_bucket_counts: Record<string, number>;
  truncation_audit_count: number;
  current_data_confirmed_count: number;
  privacy_scan: {
    private_text_included: boolean;
    source_prose_included: boolean;
    forbidden_field_violation_count: number;
  };
  profile_evidence: {
    benchmark_run_id: string;
    profile_update_ref: string;
    evolution_input_ref: string;
    no_source_prose_audit_ref: string;
  };
  profile_evolution_ready: boolean;
  production_signal_allowed: boolean;
}

export interface RkeDarwinianAutoresearchInputManifestResult {
  schema_version: "rke_darwinian_autoresearch_input_manifest_v1";
  manifest_status: "ready" | "blocked_preflight";
  benchmark_run_id: string;
  blocked_reasons: string[];
  rke_prior_treated_as_current_data: boolean;
  skill_inputs: Record<string, unknown>;
  privacy_scan: {
    private_text_included: boolean;
    source_prose_included: boolean;
    forbidden_field_violation_count: number;
  };
  promotion_allowed: boolean;
}

export interface RkeDarwinianAutoresearchConsumptionReadinessResult {
  schema_version: "rke_darwinian_autoresearch_consumption_readiness_v1";
  readiness_status: "ready" | "blocked_preflight";
  benchmark_run_id: string;
  input_manifest_status: "ready" | "blocked_preflight";
  blocked_reasons: string[];
  consumption_evidence: {
    benchmark_run_id: string;
    replay_run_id: string;
    input_manifest_ref: string;
    rke_prior_usage_metrics_ref: string;
    downstream_outcome_metrics_ref: string;
    darwinian_weight_update_ref: string;
    agent_skill_decomposition_ref: string;
    autoresearch_update_ref: string;
    rejected_update_reasons_ref: string;
    rollback_readiness_ref: string;
    agent_weight_count: number | null;
    non_stub_weight_count: number | null;
    layer_weight_sum_ready: boolean;
    darwinian_consumed: boolean;
    autoresearch_consumed: boolean;
  };
  rke_prior_treated_as_current_data: boolean;
  darwinian_autoresearch_consumption_ready: boolean;
  production_allowed: boolean;
  promotion_allowed: boolean;
}

export interface RkeCandidateConsumptionSummary {
  mutation_candidate_id: string;
  candidate_type: string;
  target_scope: string;
  target_component: string;
  severity: string;
  blocked_by: string[];
  promotion_state: string;
  manual_review_required: boolean;
  production_prompt_change_allowed: boolean;
  private_text_included: boolean;
  trigger_sources: string[];
  validation_requirements: string[];
}

export interface RkeCandidateConsumptionManifestResult {
  schema_version: "rke_candidate_consumption_manifest_v1";
  manifest_status: "ready_for_private_prompt_lifecycle" | "blocked_preflight";
  artifact_path: string;
  candidate_count: number;
  refusal_count: number;
  candidate_type_counts: Record<string, number>;
  target_scope_counts: Record<string, number>;
  blocked_reason_counts: Record<string, number>;
  candidate_summaries: RkeCandidateConsumptionSummary[];
  manifest_blockers: string[];
  missing_artifact: boolean;
  private_prompt_mutation_required: boolean;
  production_prompt_change_allowed: boolean;
  candidate_consumption_policy: string;
  privacy_scan: {
    private_text_included: boolean;
    source_prose_included: boolean;
    forbidden_field_violation_count: number;
  };
}

export interface RkePromptMutationPromptPin {
  agent: string;
  lang: string;
  prompt_repo_id: string;
  prompt_repo_revision: string;
  prompt_file_path: string;
  prompt_sha256: string;
  fallback_used: boolean;
}

export interface RkePromptMutationLifecycleRecord {
  mutation_candidate_id: string;
  candidate_type: string;
  target_component: string;
  affected_agents: string[];
  candidate_action:
    | "private_prompt_branch_after_blockers_clear"
    | "record_refusal_no_prompt_branch";
  private_prompt_branch: string;
  overwrite_target_paths: string[];
  prompt_pins: RkePromptMutationPromptPin[];
  lifecycle_stages: string[];
  rke_prior_usage_hypothesis: string;
  expected_improvement_metric: string;
  fallback_rollback_rule: string;
  benchmark_evidence_required: boolean;
  manual_review_required: boolean;
  promotion_allowed: boolean;
  blocked_by: string[];
}

export interface RkePromptMutationLifecycleManifestResult {
  schema_version: "rke_prompt_mutation_lifecycle_manifest_v1";
  manifest_status: "ready_for_private_branch" | "blocked_preflight";
  blocked_reasons: string[];
  candidate_count: number;
  affected_agents: string[];
  prompt_preflight: {
    ready: boolean;
    row_count: number;
    blocked_count: number;
  };
  lifecycle_records: RkePromptMutationLifecycleRecord[];
  private_prompt_repo_required: boolean;
  direct_prompt_write_allowed: boolean;
  promotion_allowed: boolean;
  rollback_required_before_promotion: boolean;
}

export interface RkePromptMutationReleaseRecord {
  mutation_candidate_id: string;
  private_prompt_branch: string;
  affected_agents: string[];
  benchmark_run_id: string;
  prompt_version_id: number | null;
  prompt_repo_id: string;
  release_private_prompt_branch: string;
  base_prompt_repo_revision: string;
  overwrite_target_paths: string[];
  audit_version_ref: string;
  prompt_commit_hash: string;
  prompt_sha256: string;
  verify_release_ref: string;
  leak_drift_check_ref: string;
  prompt_contract_check_ref: string;
  prompt_contract_check_passed: boolean;
  release_ready: boolean;
  blockers: string[];
}

export interface RkePromptMutationReleaseReadinessResult {
  schema_version: "rke_prompt_mutation_release_readiness_v1";
  benchmark_run_id: string;
  readiness_status: "ready" | "blocked_preflight" | "not_applicable";
  blocked_reasons: string[];
  lifecycle_manifest_status: "ready_for_private_branch" | "blocked_preflight";
  branch_candidate_count: number;
  release_record_count: number;
  release_records: RkePromptMutationReleaseRecord[];
  required_evidence: string[];
  prompt_release_ready: boolean;
  direct_prompt_write_allowed: boolean;
  promotion_allowed: boolean;
}

export interface RkePromptMutationRollbackRecord {
  mutation_candidate_id: string;
  private_prompt_branch: string;
  affected_agents: string[];
  previous_prompt_hashes: string[];
  rollback_previous_prompt_hashes: string[];
  benchmark_run_id: string;
  rollback_trigger_definition: string;
  rollback_command_or_procedure: string;
  monitor_output_ref: string;
  post_rollback_verification_ref: string;
  rollback_ready: boolean;
  blockers: string[];
}

export interface RkePromptMutationRollbackReadinessResult {
  schema_version: "rke_prompt_mutation_rollback_readiness_v1";
  benchmark_run_id: string;
  readiness_status: "ready" | "blocked_preflight" | "not_applicable";
  blocked_reasons: string[];
  lifecycle_manifest_status: "ready_for_private_branch" | "blocked_preflight";
  branch_candidate_count: number;
  rollback_record_count: number;
  rollback_records: RkePromptMutationRollbackRecord[];
  required_evidence: string[];
  rollback_gate_ready: boolean;
  promotion_allowed: boolean;
}

export interface RkePatchActivationRecord {
  mutation_candidate_id: string;
  candidate_type: string;
  target_scope: string;
  target_component: string;
  benchmark_run_id: string;
  patch_artifact_ref: string;
  patch_validation_ref: string;
  shadow_apply_ref: string;
  runtime_activation_ref: string;
  runtime_proof_ref: string;
  rollback_ref: string;
  patch_activation_ready: boolean;
  blockers: string[];
}

export interface RkePatchActivationReadinessResult {
  schema_version: "rke_patch_activation_readiness_v1";
  benchmark_run_id: string;
  readiness_status: "ready" | "blocked_preflight" | "not_applicable";
  blocked_reasons: string[];
  candidate_manifest_status: "ready_for_private_prompt_lifecycle" | "blocked_preflight";
  patch_candidate_count: number;
  activation_record_count: number;
  activation_records: RkePatchActivationRecord[];
  required_evidence: string[];
  patch_activation_ready: boolean;
  direct_runtime_write_allowed: boolean;
  production_allowed: boolean;
  promotion_allowed: boolean;
}

export interface RkeShadowReplayReadinessResult {
  schema_version: "rke_shadow_replay_readiness_v1";
  readiness_status: "ready" | "blocked_preflight";
  benchmark_run_id: string;
  blocked_reasons: string[];
  prompt_provenance_readiness_status: "ready" | "blocked_preflight";
  benchmark_evidence_status: "ready" | "blocked_preflight";
  darwinian_manifest_status: "ready" | "blocked_preflight";
  darwinian_consumption_status: "ready" | "blocked_preflight";
  prompt_release_readiness_status: "ready" | "blocked_preflight" | "not_applicable";
  rollback_readiness_status: "ready" | "blocked_preflight" | "not_applicable";
  replay_evidence: {
    benchmark_run_id: string;
    replay_run_id: string;
    replay_run_ref: string;
    replay_output_manifest_ref: string;
    runtime_context_consumption_ref: string;
    replay_footprint_ref: string;
    downstream_outcome_metrics_ref: string;
    replay_output_count: number | null;
    replay_footprint_count: number | null;
    privacy_scan_passed: boolean;
    current_data_confirmed: boolean;
  };
  rke_context_hash_count: number;
  ranking_policy_id_counts: Record<string, number>;
  retrieval_rank_count: number;
  priority_bucket_counts: Record<string, number>;
  truncation_audit_count: number;
  current_data_confirmed_count: number;
  shadow_replay_ready: boolean;
  paper_trading_allowed: boolean;
  promotion_allowed: boolean;
}

export interface RkePaperTradingReadinessResult {
  schema_version: "rke_paper_trading_readiness_v1";
  readiness_status: "ready" | "blocked_preflight";
  benchmark_run_id: string;
  blocked_reasons: string[];
  shadow_replay_status: "ready" | "blocked_preflight";
  paper_trading_plan: {
    benchmark_run_id: string;
    paper_trading_plan_ref: string;
    risk_limit_ref: string;
    stop_loss_or_rollback_ref: string;
    operator_review_timestamp: string;
    operator_review_approved: boolean;
  };
  paper_trading_allowed: boolean;
  promotion_allowed: boolean;
}

export interface RkePromotionDecisionReadinessResult {
  schema_version: "rke_promotion_decision_readiness_v1";
  readiness_status: "ready" | "blocked_preflight";
  benchmark_run_id: string;
  blocked_reasons: string[];
  paper_trading_status: "ready" | "blocked_preflight";
  promotion_evidence: {
    benchmark_run_id: string;
    paper_trading_result_ref: string;
    monitor_summary_ref: string;
    second_review_timestamp: string;
    lockbox_decision_ref: string;
    decision: string;
    second_review_approved: boolean;
  };
  ready_for_operator_promotion_decision: boolean;
  production_allowed: boolean;
  promotion_allowed: boolean;
}

export interface RkeDeliveryCondition {
  condition_id: string;
  status: string;
  ready: boolean;
  blocked_reasons: string[];
  evidence_summary: Record<string, unknown>;
}

export interface RkeDeliveryReadinessResult {
  schema_version: "rke_all_agent_delivery_readiness_v1";
  readiness_status: "ready" | "blocked_preflight";
  benchmark_run_id: string;
  cohort: string;
  condition_count: number;
  ready_condition_count: number;
  blocked_reasons: string[];
  conditions: RkeDeliveryCondition[];
  recorded_evidence_loaded: boolean;
  delivery_input_failures: string[];
  delivery_ready: boolean;
  production_allowed: boolean;
  promotion_allowed: boolean;
}

export interface RkeDeliveryEvidenceRecordResult {
  record_status: "recorded" | "blocked";
  benchmark_run_id: string;
  private_rows_path: string;
  recorded_key_count: number;
  recorded_context_key_count: number;
  failures: string[];
}

export interface RkeDeliveryEvidenceAuditResult {
  schema_version: "rke_delivery_evidence_audit_v1";
  evidence_status: "missing" | "partial" | "complete" | "blocked";
  benchmark_run_id: string;
  cohort: string;
  private_rows_path: string;
  recorded_key_count: number;
  recorded_context_keys: string[];
  recorded_keys: string[];
  recorded_prompt_source_status: Record<string, unknown>;
  missing_keys: string[];
  failures: string[];
  delivery_readiness_can_load: boolean;
  delivery_readiness_status: "ready" | "blocked_preflight";
  condition_count: number;
  ready_condition_count: number;
  delivery_conditions: RkeDeliveryCondition[];
  delivery_blocked_reasons: string[];
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
  existing?: boolean;
  prompt_commit_hash?: string | null;
  prompt_sha256?: string | null;
  prompt_base_commit_hash?: string | null;
}

export interface AutoresearchHistoricalDecisionResult {
  version_id: number;
  decision: "keep" | "revert";
  active_commit: string;
  created: boolean;
}

export interface AutoresearchHistoricalValidationResult {
  version_id: number;
  compatible: boolean;
  unknown_tools: string[];
  missing_files: string[];
  dropped_output_sections: string[];
}

/** One entry in the ``autoresearch.evaluate_pending`` results array. */
export interface AutoresearchMissingRun {
  kind: "base" | "mod";
  cohort: string;
  start_date: string;
  end_date: string;
  prompt_commit_hash: string;
  prompt_repo_id?: string;
  prompt_sha256?: string;
  code_commit_hash?: string;
  private_prompt_commit?: string;
}

export interface AutoresearchEvalResult {
  version_id: number;
  mutation_id?: string;
  status: string;
  delta_sharpe?: number;
  detail?: string;
  missing_runs?: AutoresearchMissingRun[];
  missing_domain_samples?: boolean;
  evaluation_result?: Record<string, unknown> | null;
}

export interface AutoresearchDomainPromotionResult {
  version_id: number;
  status: "reverted";
  decision_hash: string;
  decision: Record<string, unknown>;
  created: boolean;
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
  portfolio_context?: {
    current_position_tickers?: string[];
    position_count?: number;
    sector_exposure?: Record<string, number>;
    theme_exposure?: Record<string, number>;
    current_positions?: Array<{
      ticker: string;
      market_price?: number;
      current_weight?: number;
      cost_basis?: number;
      holding_days?: number;
      unrealized_pnl_pct?: number;
      entry_thesis?: string;
    }>;
  };
}

export interface MirofishRecommendation {
  recommendation: "BUY" | "SELL" | "HOLD";
  tickers: string[];
  conviction: number;
  reasoning?: string;
  position_reviews?:
    | Array<{
        ticker: string;
        decision: "HOLD" | "ADD" | "REDUCE" | "EXIT";
        target_weight?: number | undefined;
        current_weight?: number | undefined;
        reason?: string | undefined;
      }>
    | undefined;
  new_entries?:
    | Array<{
        ticker: string;
        target_weight?: number | undefined;
        reason?: string | undefined;
      }>
    | undefined;
  portfolio_actions?:
    | Array<{
        ticker: string;
        action: "BUY" | "SELL" | "HOLD" | "REDUCE";
        target_weight?: number | undefined;
        current_weight?: number | undefined;
        delta_weight?: number | undefined;
      }>
    | undefined;
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

/** Compact forward-looking context derived from a scenario set (7M Step 1/2).
 *  ``hct_direction`` / ``tail_summary`` may be null (see derive_context). */
export interface MirofishContext {
  n_scenarios: number;
  scenario_count?: number;
  horizon_days?: number;
  as_of_date?: string;
  context_hash?: string;
  generator_version?: string;
  regime: string | null;
  narrative: string | null;
  csi300_return: number;
  hct_ticker: string;
  hct_direction: "LONG" | "SHORT" | null;
  hct_csi300_return: number;
  tail_summary: string | null;
  position_stress?:
    | Array<{
        ticker: string;
        tail_loss?: number | undefined;
        scenario_agreement?: number | undefined;
        suggested_action?: "HOLD" | "ADD" | "REDUCE" | "EXIT" | undefined;
      }>
    | undefined;
  engine: string;
  date?: string;
  created_at?: string;
}

// --------------------------------------------------------- helpers

/**
 * Ergonomic helper around a BridgeClient. Provides typed wrappers across all 13
 * namespaces: tools.* / config.* / cache.* / calendar.* / paper.* (incl. the
 * Phase 8 write surface: register/login/logout/reset_account/buy/sell/
 * suggest_order_from_signal) / backtest.* / scorecard.* / darwinian.* /
 * prompts.* / autoresearch.* / prism.* / janus.* / mirofish.* (incl.
 * save/get_context). The only registered method still unwrapped is
 * `cache.details` — reachable via ``client.call(method, params)``.
 */
export class BridgeApi {
  constructor(private readonly client: BridgeClient) {}

  // tools.*
  toolsPrepareCapability(
    request: ToolCapabilityPrepareRequest,
  ): Promise<PreparedAgentToolCapability> {
    return this.client.call<PreparedAgentToolCapability>("tools.prepare_capability", request);
  }

  toolsIssueCapability(request: ToolCapabilityIssueRequest): Promise<PreparedAgentToolCapability> {
    return this.client.call<PreparedAgentToolCapability>("tools.issue_capability", request);
  }

  toolsList(capability: SignedAgentToolCapability): Promise<ToolMetadata[]> {
    return this.client.call<ToolMetadata[]>("tools.list", { capability });
  }

  toolsCall(
    name: string,
    args: Record<string, unknown>,
    capability: SignedAgentToolCapability,
  ): Promise<ToolCallResult> {
    return this.client.call<ToolCallResult>("tools.call", {
      name,
      args,
      capability,
    });
  }

  toolsTerminateCapability(
    capability: SignedAgentToolCapability,
    reason = "node_finished",
  ): Promise<{ terminated: true }> {
    return this.client.call<{ terminated: true }>("tools.terminate_capability", {
      capability,
      reason,
    });
  }

  toolsRecordModelUsage(
    capability: SignedAgentToolCapability,
    usageReport: SectorModelUsageReport,
  ): Promise<Record<string, unknown>> {
    return this.client.call<Record<string, unknown>>("tools.record_model_usage", {
      capability,
      usage_report: usageReport,
    });
  }

  toolsFinalizeModelUsage(
    capability: SignedAgentToolCapability,
  ): Promise<SectorModelUsageSummaryReceipt> {
    return this.client.call<SectorModelUsageSummaryReceipt>("tools.finalize_model_usage", {
      capability,
    });
  }

  runtimeStockMarketSnapshot(params: {
    ticker: string;
    start_date: string;
    as_of_date: string;
    mode: "live" | "backtest";
  }): Promise<ToolCallResult> {
    return this.client.call<ToolCallResult>("runtime_data.stock_market_snapshot", params);
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

  /** Persist config to ~/.mosaic/config.json + apply (survives restarts). */
  configSave(config: MosaicConfig): Promise<MosaicConfig> {
    return this.client.call<MosaicConfig>("config.save", { config });
  }

  // data.* (qlib incremental ingest — vendored collectors)
  dataIncremental(params: {
    kind?: "stock" | "etf";
    end: string;
    timeout?: number;
  }): Promise<DataIncrementalResult> {
    return this.client.call<DataIncrementalResult>("data.incremental", params);
  }

  dataValidate(params: {
    kind?: "stock" | "etf";
    gap_threshold?: number;
  }): Promise<Record<string, unknown>> {
    return this.client.call<Record<string, unknown>>("data.validate", params);
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

  paperGetPortfolioSnapshot(
    opts: { user_id?: string; db_path?: string } = {},
  ): Promise<PaperPortfolioSnapshot> {
    return this.client.call<PaperPortfolioSnapshot>("paper.get_portfolio_snapshot", opts);
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
    order_intent_key?: string;
    expected_account_snapshot_hash?: string;
    final_target_hash?: string;
    db_path?: string;
  }): Promise<PaperOrderResult> {
    return this.client.call<PaperOrderResult>("paper.buy", params);
  }

  paperSell(params: {
    ticker: string;
    quantity: number;
    user_id?: string;
    analysis_id?: string;
    order_intent_key?: string;
    expected_account_snapshot_hash?: string;
    final_target_hash?: string;
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

  // backtest.* (Phase 3.5C two-stage cache; backtrader candidate-pool dropped in Phase 8)
  backtestCreateRun(params: {
    cohort: string;
    start_date: string;
    end_date: string;
    prompt_commit_hash: string;
    prompt_repo_id?: string;
    prompt_sha256?: string;
    code_commit_hash?: string;
  }): Promise<{ run_id: number }> {
    return this.client.call<{ run_id: number }>("backtest.create_run", params);
  }

  backtestAppendActions(
    runId: number,
    tradeDate: string,
    actions: BacktestActionInput[],
    agentRunAudits: NonNullable<LlmCallRecord["agent_run_audit"]>[],
    decisionDisposition: "TARGET_PORTFOLIO" | "HOLD_CURRENT" | "ALL_CASH",
  ): Promise<{ appended: number }> {
    return this.client.call<{ appended: number }>("backtest.append_actions", {
      run_id: runId,
      trade_date: tradeDate,
      actions,
      agent_run_audits: agentRunAudits,
      decision_disposition: decisionDisposition,
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

  backtestActionSummary(runId: number): Promise<BacktestActionSummary> {
    return this.client.call<BacktestActionSummary>("backtest.action_summary", { run_id: runId });
  }

  // R-A3: stage-1 failed-day tracking.
  backtestRecordFailedDays(
    runId: number,
    failures: Array<{
      date: string;
      error: string;
      agent_run_audit?: NonNullable<LlmCallRecord["agent_run_audit"]>;
    }>,
  ): Promise<{ recorded: number }> {
    return this.client.call<{ recorded: number }>("backtest.record_failed_days", {
      run_id: runId,
      failures,
    });
  }

  backtestGetFailedDays(
    runId: number,
    opts?: { clear_dates?: string[]; clear_all?: boolean },
  ): Promise<{ failures: Array<{ date: string; error: string; recorded_at: string }> }> {
    return this.client.call("backtest.get_failed_days", { run_id: runId, ...(opts ?? {}) });
  }

  backtestRunHistorical(
    runId: number,
    opts?: {
      initial_cash?: number;
      benchmark?: string;
      open_cost?: number;
      close_cost?: number;
      deal_price?: string;
      results_dir?: string;
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

  calendarVerifiedSnapshot(params: {
    start: string;
    end: string;
    as_of: string;
  }): Promise<Record<string, unknown>> {
    return this.client.call("calendar.verified_snapshot", params);
  }

  calendarIsTradingDay(date: string): Promise<{ is_trading: boolean }> {
    return this.client.call<{ is_trading: boolean }>("calendar.is_trading_day", { date });
  }

  calendarNextTradingDay(date: string, n = 1): Promise<{ date: string }> {
    return this.client.call<{ date: string }>("calendar.next_trading_day", { date, n });
  }

  // scorecard.* (Phase 3D)
  scorecardAppend(state: Record<string, unknown>): Promise<{
    ingested: number;
    macro_ingested: number;
    agent_narratives_ingested?: number;
    darwinian_v2?: {
      production_variant_roster_revision_id: string;
      accepted_output_records: number;
      operational_opportunity_audits: number;
      evaluation_tracks_inserted: number;
      usage_tracks_inserted: number;
      cold_start_weights_inserted: number;
    };
  }> {
    return this.client.call("scorecard.append", { state });
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

  scorecardListMacroSkill(cohort: string, since?: string): Promise<{ rows: MacroSkillRow[] }> {
    return this.client.call<{ rows: MacroSkillRow[] }>("scorecard.list_macro_skill", {
      cohort,
      ...(since ? { since } : {}),
    });
  }

  scorecardCompareMacroLabelSources(
    cohort: string,
    today: string,
    since?: string,
  ): Promise<Record<string, unknown>> {
    return this.client.call<Record<string, unknown>>("scorecard.compare_macro_label_sources", {
      cohort,
      today,
      ...(since ? { since } : {}),
    });
  }

  scorecardClassifyMacroDocuments(params?: {
    source?: string;
    discovered_at_lte?: string;
    only_unclassified?: boolean;
  }): Promise<Record<string, unknown>> {
    return this.client.call<Record<string, unknown>>(
      "scorecard.classify_macro_documents",
      params ?? {},
    );
  }

  scorecardMacroSentimentIndex(params: {
    agent: string;
    as_of: string;
    lookback_days?: number;
  }): Promise<Record<string, unknown>> {
    return this.client.call<Record<string, unknown>>("scorecard.macro_sentiment_index", params);
  }

  scorecardLatestCioActions(cohort: string): Promise<CioActions> {
    return this.client.call<CioActions>("scorecard.latest_cio_actions", { cohort });
  }

  scorecardLatestAgentNarratives(cohort: string): Promise<AgentDisplayNarratives> {
    return this.client.call<AgentDisplayNarratives>("scorecard.latest_agent_narratives", {
      cohort,
    });
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
      audit_only: true,
    });
  }

  darwinianGetWeights(
    cohort: string,
    date?: string,
  ): Promise<{
    status: "legacy_unverified";
    audit_only: true;
    weights: DarwinianWeightTable;
  }> {
    return this.client.call("darwinian.get_weights", {
      cohort,
      ...(date ? { date } : {}),
      audit_only: true,
    });
  }

  darwinianPrepareVariant(
    binding: import("../autoresearch/production_variant.js").DarwinianRuntimeBinding,
    asOf: string,
  ): Promise<{
    runtime_binding: import("../autoresearch/production_variant.js").DarwinianRuntimeBinding;
    roster_revision: Record<string, unknown>;
    weight_snapshot: import("../autoresearch/production_variant.js").DarwinianUsageWeightSnapshot;
    component_weight_snapshot: import("../autoresearch/production_variant.js").ComponentWeightRuntimeSnapshot;
  }> {
    return this.client.call("darwinian.prepare_variant", { binding, as_of: asOf });
  }

  darwinianPrepareDailyCycleOutcomes(params: {
    production_variant_roster_revision_id: string;
    graph_run_id: string;
    as_of: string;
    prepared_at: string;
  }): Promise<{
    outcome_schedule_plan: {
      outcome_schedule_plan_id: string;
      outcome_schedule_plan_hash: string;
      schema_version: string;
      graph_run_id: string;
      production_variant_roster_id: string;
      production_variant_roster_revision_id: string;
      execution_behavior_release_id: string;
      cohort_id: string;
      language: "en" | "zh";
      as_of: string;
      prepared_at: string;
      slots: import("../agents/state.js").OutcomeRunSlot[];
    };
    scheduled_opportunity_decisions: Array<Record<string, unknown>>;
    stage_skips: Record<string, unknown>;
    run_blockers: Array<{ agent_id: string; reason: string }>;
    trading_calendar_snapshot_hash: string;
    event_candidate_input_hash: string;
    deferred_opportunity_agent_ids: string[];
  }> {
    return this.client.call("darwinian.prepare_daily_cycle_outcomes", params);
  }

  darwinianFreezeOutcomeOpportunity(params: {
    outcome_schedule_plan_id: string;
    scheduled_sample_id: string;
    agent_id: AgentId;
  }): Promise<{
    run_allowed: boolean;
    blocker_reason?: string;
    scheduled_sample_id: string;
    evaluation_opportunity_set_id?: string;
    evaluation_opportunity_set_hash?: string;
    frozen_object_set_id?: null;
    frozen_object_set_hash?: null;
    runtime_authority_binding?: import("../agents/state.js").OutcomeLiveSourceAuthorityBinding;
  }> {
    return this.client.call("darwinian.freeze_outcome_opportunity", params);
  }

  darwinianFreezeStageOutcomeOpportunity(params: {
    outcome_schedule_plan_id: string;
    scheduled_sample_id: string;
    agent_id: "alpha_discovery" | "cro" | "autonomous_execution" | "cio";
    recorded_at: string;
    frozen_object?: Record<string, unknown>;
  }): Promise<{
    run_allowed: boolean;
    blocker_reason?: string;
    scheduled_sample_id: string;
    evaluation_opportunity_set_id?: string;
    evaluation_opportunity_set_hash?: string;
    frozen_object_set_id?: string;
    frozen_object_set_hash?: string;
    runtime_authority_binding?: import("../agents/state.js").OutcomeRuntimeAuthorityBinding;
    frozen_object?: Record<string, unknown>;
    stage_skip?: Record<string, unknown>;
  }> {
    return this.client.call("darwinian.freeze_stage_outcome_opportunity", params);
  }

  darwinianFreezeSuperinvestorOutcomeOpportunity(params: {
    outcome_schedule_plan_id: string;
    scheduled_sample_id: string;
    agent_id: "druckenmiller" | "munger" | "burry" | "ackman";
    recorded_at: string;
    accepted_output_refs: Array<Record<string, unknown>>;
  }): Promise<{
    run_allowed: boolean;
    blocker_reason?: string;
    scheduled_sample_id: string;
    evaluation_opportunity_set_id?: string;
    evaluation_opportunity_set_hash?: string;
    frozen_object_set_id?: string;
    frozen_object_set_hash?: string;
    runtime_candidate_scope_hash?: string;
    runtime_candidate_universe_hash?: string;
    runtime_source_snapshot_hash?: string;
    stage_skip?: Record<string, unknown>;
  }> {
    return this.client.call("darwinian.freeze_superinvestor_outcome_opportunity", params);
  }

  darwinianRefreshV2Windows(params: {
    production_variant_roster_revision_id: string;
    cutoff_at: string;
  }): Promise<DarwinianRefreshV2WindowsResult> {
    return this.client.call<DarwinianRefreshV2WindowsResult>(
      "darwinian.refresh_v2_windows",
      params,
    );
  }

  darwinianMaterializeDueOutcomes(params: {
    production_variant_roster_revision_id: string;
    cutoff_at: string;
  }): Promise<DarwinianMaterializeDueOutcomesResult> {
    return this.client.call<DarwinianMaterializeDueOutcomesResult>(
      "darwinian.materialize_due_outcomes",
      params,
    );
  }

  darwinianPublishV2Updates(params: {
    production_variant_roster_revision_id: string;
    cutoff_at: string;
  }): Promise<DarwinianPublishV2UpdatesResult> {
    return this.client.call<DarwinianPublishV2UpdatesResult>(
      "darwinian.publish_v2_updates",
      params,
    );
  }

  darwinianKnotRegisterTrack(params: {
    knot_nomination_audit_id: string;
    production_variant_roster_revision_id: string;
    target_evaluation_track_key_hash: string;
    mutation_definition: Record<string, unknown>;
    created_at: string;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_register_track", params);
  }

  darwinianKnotNominate(params: {
    production_variant_roster_revision_id: string;
    research_slot_id: string;
    research_slot_sequence: number;
    recorded_at: string;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_nominate", params);
  }

  darwinianKnotPublishSchedule(params: {
    knot_research_track_id: string;
    pair_phase: "RESEARCH" | "POST_PROMOTION_SHADOW";
    slots: Array<{
      research_slot_id: string;
      research_slot_sequence: number;
      scheduled_sample_id: string;
    }>;
    published_at: string;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_publish_schedule", params);
  }

  darwinianKnotPreregisterPairAssignment(params: {
    knot_research_track_id: string;
    research_slot_id: string;
    scheduled_sample_id: string;
    pair_phase: "RESEARCH" | "POST_PROMOTION_SHADOW";
    regime_source_snapshot: Record<string, unknown>;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_preregister_pair_assignment", params);
  }

  darwinianKnotFreezePair(params: {
    knot_research_track_id: string;
    knot_pair_assignment_id: string;
    research_slot_id: string;
    evaluation_opportunity_set_id: string;
    champion_capability_envelope: SignedAgentToolCapability;
    candidate_capability_envelope: SignedAgentToolCapability;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_freeze_pair", params);
  }

  darwinianKnotAppendScore(
    params: {
      knot_pair_id: string;
      pair_side: "CHAMPION" | "CANDIDATE";
      recorded_at: string;
      sector_inference_cost_audit_id?: string | null;
    } & (
      | {
          score_disposition: "SCORE";
          outcome_label_id: string;
          operational_opportunity_audit_id?: never;
        }
      | {
          score_disposition: "AGENT_FAILURE";
          outcome_label_id?: never;
          operational_opportunity_audit_id?: string | null;
        }
    ),
  ): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_append_score", params);
  }

  darwinianKnotAppendPairSideResult(
    params:
      | {
          knot_pair_id: string;
          pair_side: "CHAMPION" | "CANDIDATE";
          result_disposition: "ACCEPTED";
          output_phase?: "CIO_PROPOSAL" | "CIO_FINAL";
          recorded_at: string;
          accepted_output_record: Record<string, unknown>;
          verified_claim_graph: Record<string, unknown>;
          schema_json: Record<string, unknown>;
        }
      | {
          knot_pair_id: string;
          pair_side: "CHAMPION" | "CANDIDATE";
          result_disposition: "AGENT_FAILURE";
          recorded_at: string;
          failure_reason: string;
          cio_failure_phase?: "PROPOSAL" | "FINAL" | null;
        },
  ): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_append_pair_side_result", params);
  }

  darwinianKnotAppendSectorCostAudit(params: {
    knot_pair_id: string;
    pair_side: "CHAMPION" | "CANDIDATE";
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_append_sector_cost_audit", params);
  }

  darwinianKnotAppendControlDependency(
    params: {
      knot_pair_id: string;
      control_side: "SHARED" | "CHAMPION" | "CANDIDATE";
      agent_id: "alpha_discovery" | "cro" | "autonomous_execution";
      graph_run_id: string;
      frozen_object_set_id: string;
      frozen_object_set_hash: string;
      evidence_ids: string[];
      recorded_at: string;
    } & (
      | {
          result_disposition: "ACCEPTED";
          run_id: string;
          output: Record<string, unknown>;
          schema_json: Record<string, unknown>;
          failure_reason?: never;
        }
      | {
          result_disposition: "NO_EVALUATION_OBJECT" | "AGENT_FAILURE" | "EXOGENOUS_EXCLUSION";
          run_id?: string | null;
          output?: never;
          schema_json?: never;
          failure_reason?: string | null;
        }
    ),
  ): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_append_control_dependency", params);
  }

  darwinianKnotFinalizePair(params: {
    knot_pair_id: string;
    pair_disposition:
      | "ACCOUNTABLE"
      | "EXOGENOUS_EXCLUSION"
      | "DEPENDENCY_BLOCKED"
      | "CONTRACT_FAILURE";
    recorded_at: string;
    exclusion_or_failure_reason?: string | null;
    dependency_blocked_audit_id?: string | null;
    exclusion_audit_id?: string | null;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_finalize_pair", params);
  }

  darwinianKnotAppendCioDependencyBlocked(params: {
    knot_pair_id: string;
    control_side: "SHARED" | "CHAMPION" | "CANDIDATE";
    blocked_dependency_operational_audit_id: string;
    recorded_at: string;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_append_cio_dependency_blocked", params);
  }

  darwinianKnotPublishPromotion(params: {
    knot_research_track_id: string;
    recorded_at: string;
    effective_from_research_slot_id?: string | null;
    effective_from_research_slot_sequence?: number | null;
    new_execution_behavior_release_id?: string | null;
    new_production_variant_roster_revision_id?: string | null;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_publish_promotion", params);
  }

  darwinianKnotPublishPromotionBatch(params: {
    targets: Array<{
      knot_research_track_id: string;
      new_production_variant_roster_revision_id: string;
    }>;
    effective_from_research_slot_id: string;
    effective_from_research_slot_sequence: number;
    new_execution_behavior_release_id: string;
    recorded_at: string;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_publish_promotion_batch", params);
  }

  darwinianKnotPublishRollback(params: {
    knot_research_track_id: string;
    effective_from_research_slot_id: string;
    effective_from_research_slot_sequence: number;
    new_execution_behavior_release_id: string;
    new_production_variant_roster_revision_id: string;
    cooldown_until_research_slot_id: string;
    cooldown_until_research_slot_sequence: number;
    recorded_at: string;
  }): Promise<Record<string, unknown>> {
    return this.client.call("darwinian.knot_publish_rollback", params);
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
    expected_base_hashes?: Record<string, string>;
    target?: "private_git" | "project_git" | "working_tree";
    branch?: string;
    base_ref?: string;
    message?: string;
    allow_public_prompt_write?: boolean;
  }): Promise<PromptWriteResult> {
    return this.client.call<PromptWriteResult>("prompts.write", params);
  }

  promptsCandidateState(params: {
    branch: string;
    target?: "private_git" | "project_git";
    expected_hashes: Record<string, string>;
  }): Promise<{ candidate_visible: boolean; new_commit: string | null; hashes_match: boolean }> {
    return this.client.call("prompts.candidate_state", params);
  }

  promptsAbortCandidate(params: {
    branch: string;
    target?: "private_git" | "project_git";
  }): Promise<{ ok: boolean }> {
    return this.client.call("prompts.abort_candidate", params);
  }

  promptsInitPrivateRepo(params: {
    path: string;
    seed_baseline?: boolean;
  }): Promise<PromptInitPrivateRepoResult> {
    return this.client.call<PromptInitPrivateRepoResult>("prompts.init_private_repo", params);
  }

  promptsAuditVersions(params?: {
    cohort?: string;
    status?: string;
    agent?: string;
    limit?: number;
  }): Promise<{ versions: PromptVersionAuditRow[] }> {
    return this.client.call<{ versions: PromptVersionAuditRow[] }>(
      "prompts.audit_versions",
      params ?? {},
    );
  }

  promptsPreflight(params?: {
    cohort?: string;
    agents?: string[];
    langs?: PromptLang[];
  }): Promise<PromptPreflightResult> {
    return this.client.call<PromptPreflightResult>("prompts.preflight", params ?? {});
  }

  promptsContractCheck(params?: {
    cohort?: string;
    agents?: string[];
    langs?: PromptLang[];
    prompt_rows?: PromptPreflightRow[];
    benchmark_run_id?: string;
  }): Promise<PromptContractCheckResult> {
    return this.client.call<PromptContractCheckResult>("prompts.contract_check", params ?? {});
  }

  promptsFormalReleaseChecks(params?: {
    cohort?: string;
    agents?: string[];
    langs?: PromptLang[];
    benchmark_run_id?: string;
  }): Promise<PromptFormalReleaseChecksResult> {
    return this.client.call<PromptFormalReleaseChecksResult>(
      "prompts.formal_release_checks",
      params ?? {},
    );
  }

  promptsVerifyRelease(params: {
    version_id: number;
    require_kept?: boolean;
  }): Promise<PromptReleaseCheckResult> {
    return this.client.call<PromptReleaseCheckResult>("prompts.verify_release", params);
  }

  // rke.* (Part 1 context/export)
  rkeAgentResearchContext(params: {
    agent_id: string;
    root?: string;
    registry_dir?: string;
    as_of_date?: string;
    layer?: string;
    ticker?: string;
    sector?: string;
    max_items?: number;
  }): Promise<RkeAgentResearchContextResult> {
    return this.client.call<RkeAgentResearchContextResult>("rke.agentResearchContext", params);
  }

  rkeMacroAgentPriors(params?: {
    root?: string;
    registry_dir?: string;
    as_of_date?: string;
    agent_id?: string;
    no_source_prose?: boolean;
  }): Promise<RkeMacroAgentPriorsResult> {
    return this.client.call<RkeMacroAgentPriorsResult>("rke.macroAgentPriors", params ?? {});
  }

  // rke_benchmark.* (Part 2 E2)
  rkeBenchmarkAllAgentPromptProvenanceReadiness(params?: {
    benchmark_run_id?: string;
    cohort?: string;
    release_checks?: Array<Record<string, unknown>>;
  }): Promise<RkeAllAgentPromptProvenanceReadinessResult> {
    return this.client.call<RkeAllAgentPromptProvenanceReadinessResult>(
      "rke_benchmark.all_agent_prompt_provenance_readiness",
      params ?? {},
    );
  }

  rkeBenchmarkFixedEpisodeManifest(params?: {
    cohort?: string;
  }): Promise<RkeFixedEpisodeManifestResult> {
    return this.client.call<RkeFixedEpisodeManifestResult>(
      "rke_benchmark.fixed_episode_manifest",
      params ?? {},
    );
  }

  rkeBenchmarkFixedEpisodeBenchmarkEvidence(params: {
    benchmark_run_id: string;
    cohort?: string;
    paired_output_count?: number;
    model_config_output_counts?: Record<string, number>;
    benchmark_quality_summary?: Record<string, unknown>;
    evidence_refs?: Record<string, unknown>;
    manual_review?: Record<string, unknown>;
  }): Promise<RkeFixedEpisodeBenchmarkEvidenceResult> {
    return this.client.call<RkeFixedEpisodeBenchmarkEvidenceResult>(
      "rke_benchmark.fixed_episode_benchmark_evidence",
      params,
    );
  }

  rkeBenchmarkCaptureAgentClaimFootprints(params: {
    benchmark_run_id: string;
    rows: RkeAgentClaimFootprintInput[];
  }): Promise<RkeAgentClaimFootprintCaptureResult> {
    return this.client.call<RkeAgentClaimFootprintCaptureResult>(
      "rke_benchmark.capture_agent_claim_footprints",
      params,
    );
  }

  rkeBenchmarkAgentFootprintSummary(params?: {
    benchmark_run_id?: string;
  }): Promise<RkeAgentFootprintSummaryResult> {
    return this.client.call<RkeAgentFootprintSummaryResult>(
      "rke_benchmark.agent_footprint_summary",
      params ?? {},
    );
  }

  rkeBenchmarkAgentProfileEvolutionReadiness(params: {
    benchmark_run_id: string;
    profile_evidence?: Record<string, unknown>;
  }): Promise<RkeAgentProfileEvolutionReadinessResult> {
    return this.client.call<RkeAgentProfileEvolutionReadinessResult>(
      "rke_benchmark.agent_profile_evolution_readiness",
      params,
    );
  }

  rkeBenchmarkDarwinianAutoresearchInputManifest(params?: {
    benchmark_run_id?: string;
    downstream_outcome_metrics?: Record<string, unknown>;
    prompt_mutation_provenance?: {
      benchmark_run_id?: string;
      prompt_repo_id?: string;
      prompt_repo_revision?: string;
      prompt_sha256?: string;
      prompt_commit_hash?: string;
    };
  }): Promise<RkeDarwinianAutoresearchInputManifestResult> {
    return this.client.call<RkeDarwinianAutoresearchInputManifestResult>(
      "rke_benchmark.darwinian_autoresearch_input_manifest",
      params ?? {},
    );
  }

  rkeBenchmarkDarwinianAutoresearchConsumptionReadiness(params?: {
    benchmark_run_id?: string;
    downstream_outcome_metrics?: Record<string, unknown>;
    prompt_mutation_provenance?: Record<string, unknown>;
    consumption_evidence?: Record<string, unknown>;
  }): Promise<RkeDarwinianAutoresearchConsumptionReadinessResult> {
    return this.client.call<RkeDarwinianAutoresearchConsumptionReadinessResult>(
      "rke_benchmark.darwinian_autoresearch_consumption_readiness",
      params ?? {},
    );
  }

  rkeBenchmarkCandidateConsumptionManifest(params?: {
    candidates?: Array<Record<string, unknown>>;
  }): Promise<RkeCandidateConsumptionManifestResult> {
    return this.client.call<RkeCandidateConsumptionManifestResult>(
      "rke_benchmark.candidate_consumption_manifest",
      params ?? {},
    );
  }

  rkeBenchmarkPromptMutationLifecycleManifest(params?: {
    candidates?: Array<Record<string, unknown>>;
  }): Promise<RkePromptMutationLifecycleManifestResult> {
    return this.client.call<RkePromptMutationLifecycleManifestResult>(
      "rke_benchmark.prompt_mutation_lifecycle_manifest",
      params ?? {},
    );
  }

  rkeBenchmarkPromptMutationReleaseReadiness(params?: {
    benchmark_run_id?: string;
    candidates?: Array<Record<string, unknown>>;
    release_checks?: Array<Record<string, unknown>>;
  }): Promise<RkePromptMutationReleaseReadinessResult> {
    return this.client.call<RkePromptMutationReleaseReadinessResult>(
      "rke_benchmark.prompt_mutation_release_readiness",
      params ?? {},
    );
  }

  rkeBenchmarkPromptMutationRollbackReadiness(params?: {
    benchmark_run_id?: string;
    candidates?: Array<Record<string, unknown>>;
    rollback_evidence?: Array<Record<string, unknown>>;
  }): Promise<RkePromptMutationRollbackReadinessResult> {
    return this.client.call<RkePromptMutationRollbackReadinessResult>(
      "rke_benchmark.prompt_mutation_rollback_readiness",
      params ?? {},
    );
  }

  rkeBenchmarkPatchActivationReadiness(params?: {
    benchmark_run_id?: string;
    candidates?: Array<Record<string, unknown>>;
    patch_activation_evidence?: Array<Record<string, unknown>>;
  }): Promise<RkePatchActivationReadinessResult> {
    return this.client.call<RkePatchActivationReadinessResult>(
      "rke_benchmark.patch_activation_readiness",
      params ?? {},
    );
  }

  rkeBenchmarkShadowReplayReadiness(params: {
    benchmark_run_id: string;
    cohort?: string;
    all_agent_prompt_release_checks?: Array<Record<string, unknown>>;
    prompt_contract_checks?: Array<Record<string, unknown>>;
    paired_output_count?: number;
    model_config_output_counts?: Record<string, number>;
    benchmark_quality_summary?: Record<string, unknown>;
    benchmark_evidence_refs?: Record<string, unknown>;
    manual_review?: Record<string, unknown>;
    downstream_outcome_metrics?: Record<string, unknown>;
    prompt_mutation_provenance?: Record<string, unknown>;
    replay_evidence?: Record<string, unknown>;
    candidates?: Array<Record<string, unknown>>;
    prompt_mutation_release_checks?: Array<Record<string, unknown>>;
    rollback_evidence?: Array<Record<string, unknown>>;
  }): Promise<RkeShadowReplayReadinessResult> {
    return this.client.call<RkeShadowReplayReadinessResult>(
      "rke_benchmark.shadow_replay_readiness",
      params,
    );
  }

  rkeBenchmarkPaperTradingReadiness(params: {
    benchmark_run_id: string;
    cohort?: string;
    all_agent_prompt_release_checks?: Array<Record<string, unknown>>;
    prompt_contract_checks?: Array<Record<string, unknown>>;
    paired_output_count?: number;
    model_config_output_counts?: Record<string, number>;
    benchmark_quality_summary?: Record<string, unknown>;
    benchmark_evidence_refs?: Record<string, unknown>;
    manual_review?: Record<string, unknown>;
    downstream_outcome_metrics?: Record<string, unknown>;
    prompt_mutation_provenance?: Record<string, unknown>;
    replay_evidence?: Record<string, unknown>;
    candidates?: Array<Record<string, unknown>>;
    prompt_mutation_release_checks?: Array<Record<string, unknown>>;
    rollback_evidence?: Array<Record<string, unknown>>;
    paper_trading_plan?: Record<string, unknown>;
  }): Promise<RkePaperTradingReadinessResult> {
    return this.client.call<RkePaperTradingReadinessResult>(
      "rke_benchmark.paper_trading_readiness",
      params,
    );
  }

  rkeBenchmarkPromotionDecisionReadiness(params: {
    benchmark_run_id: string;
    cohort?: string;
    all_agent_prompt_release_checks?: Array<Record<string, unknown>>;
    prompt_contract_checks?: Array<Record<string, unknown>>;
    paired_output_count?: number;
    model_config_output_counts?: Record<string, number>;
    benchmark_quality_summary?: Record<string, unknown>;
    benchmark_evidence_refs?: Record<string, unknown>;
    manual_review?: Record<string, unknown>;
    downstream_outcome_metrics?: Record<string, unknown>;
    prompt_mutation_provenance?: Record<string, unknown>;
    replay_evidence?: Record<string, unknown>;
    candidates?: Array<Record<string, unknown>>;
    prompt_mutation_release_checks?: Array<Record<string, unknown>>;
    rollback_evidence?: Array<Record<string, unknown>>;
    paper_trading_plan?: Record<string, unknown>;
    promotion_evidence?: Record<string, unknown>;
  }): Promise<RkePromotionDecisionReadinessResult> {
    return this.client.call<RkePromotionDecisionReadinessResult>(
      "rke_benchmark.promotion_decision_readiness",
      params,
    );
  }

  rkeBenchmarkRecordDeliveryEvidence(params: {
    benchmark_run_id: string;
    cohort?: string;
    prompt_source_status?: Record<string, unknown>;
    all_agent_prompt_release_checks?: Array<Record<string, unknown>>;
    prompt_contract_checks?: Array<Record<string, unknown>>;
    paired_output_count?: number;
    model_config_output_counts?: Record<string, number>;
    benchmark_quality_summary?: Record<string, unknown>;
    benchmark_evidence_refs?: Record<string, unknown>;
    manual_review?: Record<string, unknown>;
    profile_evidence?: Record<string, unknown>;
    downstream_outcome_metrics?: Record<string, unknown>;
    prompt_mutation_provenance?: Record<string, unknown>;
    darwinian_autoresearch_consumption_evidence?: Record<string, unknown>;
    replay_evidence?: Record<string, unknown>;
    candidates?: Array<Record<string, unknown>>;
    patch_activation_evidence?: Array<Record<string, unknown>>;
    prompt_mutation_release_checks?: Array<Record<string, unknown>>;
    rollback_evidence?: Array<Record<string, unknown>>;
    paper_trading_plan?: Record<string, unknown>;
    promotion_evidence?: Record<string, unknown>;
  }): Promise<RkeDeliveryEvidenceRecordResult> {
    return this.client.call<RkeDeliveryEvidenceRecordResult>(
      "rke_benchmark.record_delivery_evidence",
      params,
    );
  }

  rkeBenchmarkDeliveryEvidenceAudit(params: {
    benchmark_run_id: string;
  }): Promise<RkeDeliveryEvidenceAuditResult> {
    return this.client.call<RkeDeliveryEvidenceAuditResult>(
      "rke_benchmark.delivery_evidence_audit",
      params,
    );
  }

  rkeBenchmarkDeliveryReadiness(params: {
    benchmark_run_id: string;
    cohort?: string;
    all_agent_prompt_release_checks?: Array<Record<string, unknown>>;
    prompt_contract_checks?: Array<Record<string, unknown>>;
    paired_output_count?: number;
    model_config_output_counts?: Record<string, number>;
    benchmark_quality_summary?: Record<string, unknown>;
    benchmark_evidence_refs?: Record<string, unknown>;
    manual_review?: Record<string, unknown>;
    profile_evidence?: Record<string, unknown>;
    downstream_outcome_metrics?: Record<string, unknown>;
    prompt_mutation_provenance?: Record<string, unknown>;
    darwinian_autoresearch_consumption_evidence?: Record<string, unknown>;
    replay_evidence?: Record<string, unknown>;
    candidates?: Array<Record<string, unknown>>;
    patch_activation_evidence?: Array<Record<string, unknown>>;
    prompt_mutation_release_checks?: Array<Record<string, unknown>>;
    rollback_evidence?: Array<Record<string, unknown>>;
    paper_trading_plan?: Record<string, unknown>;
    promotion_evidence?: Record<string, unknown>;
  }): Promise<RkeDeliveryReadinessResult> {
    return this.client.call<RkeDeliveryReadinessResult>("rke_benchmark.delivery_readiness", params);
  }

  // autoresearch.* (Phase 4C/4D)
  autoresearchTrigger(params: {
    cohort: string;
    force_agent?: string;
    dry_run?: boolean;
    historical_sandbox?: boolean;
    historical_run_id?: string;
    as_of_date?: string;
    base_prompt_commit?: string;
    code_commit_hash?: string;
  }): Promise<AutoresearchTriggerResult> {
    return this.client.call<AutoresearchTriggerResult>("autoresearch.trigger", params);
  }

  autoresearchHistoricalDecide(params: {
    version_id: number;
    decision: "keep" | "revert";
    decided_at: string;
    base_ref: string;
    active_branch?: string;
  }): Promise<AutoresearchHistoricalDecisionResult> {
    return this.client.call<AutoresearchHistoricalDecisionResult>(
      "autoresearch.historical_decide",
      params,
    );
  }

  autoresearchHistoricalValidate(params: {
    version_id: number;
  }): Promise<AutoresearchHistoricalValidationResult> {
    return this.client.call<AutoresearchHistoricalValidationResult>(
      "autoresearch.historical_validate",
      params,
    );
  }

  autoresearchRecordMutation(params: {
    version_id: number;
    commit_hash: string;
    summary?: string;
    prompt_repo_id?: string;
    prompt_base_commit_hash?: string;
    prompt_sha256?: string;
    code_commit_hash?: string;
    mutation_metadata?: object;
  }): Promise<{ ok: boolean }> {
    return this.client.call<{ ok: boolean }>("autoresearch.record_mutation", params);
  }

  autoresearchEvaluatePending(params?: {
    cohort?: string;
    version_id?: number;
    domain_sample_manifest?: Record<string, unknown>;
  }): Promise<{ results: AutoresearchEvalResult[] }> {
    return this.client.call<{ results: AutoresearchEvalResult[] }>(
      "autoresearch.evaluate_pending",
      params ?? {},
    );
  }

  autoresearchReviewDomainPromotion(params: {
    version_id: number;
    decision: "revert";
    approved_by: string;
    approval_policy_id: "domain_release_manual_v1" | "decision_release_manual_v1";
    review_reason: string;
  }): Promise<AutoresearchDomainPromotionResult> {
    return this.client.call<AutoresearchDomainPromotionResult>(
      "autoresearch.review_domain_promotion",
      params,
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

  autoresearchPrepareWorktree(params: {
    branch?: string;
    ref?: string;
    repo_target?: "project_git" | "private_git";
  }): Promise<{ path: string; repo_target?: string; prompts_root?: string }> {
    return this.client.call<{ path: string; repo_target?: string; prompts_root?: string }>(
      "autoresearch.prepare_worktree",
      params,
    );
  }

  autoresearchCleanupWorktree(params: {
    path: string;
    repo_target?: "project_git" | "private_git";
  }): Promise<{ ok: boolean }> {
    return this.client.call<{ ok: boolean }>("autoresearch.cleanup_worktree", params);
  }

  autoresearchGcWorktrees(params?: {
    repo_target?: "project_git" | "private_git" | "all";
    max_age_hours?: number;
  }): Promise<{
    results: Array<{
      repo_target: string;
      removed: string[];
      kept: string[];
      skipped?: string[];
      missing: boolean;
      skipped_reason?: string;
    }>;
  }> {
    return this.client.call("autoresearch.gc_worktrees", params ?? {});
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
    current_positions?: Array<{
      ticker: string;
      market_price?: number;
      current_price?: number;
      current_weight?: number;
      cost_basis?: number;
      unrealized_pnl_pct?: number;
      holding_days?: number;
      entry_thesis?: string;
    }>;
    sector_exposure?: Record<string, number>;
    theme_exposure?: Record<string, number>;
    reflexivity?: boolean;
    engine?: "montecarlo" | "swarm" | "oasis";
    /** Cap OASIS sim rounds (oasis engine only; positive int, server default 5). */
    max_rounds?: number;
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

  mirofishSaveContext(params: {
    scenarios: MirofishScenario[];
    date?: string;
  }): Promise<{ date: string; context: MirofishContext }> {
    return this.client.call<{ date: string; context: MirofishContext }>(
      "mirofish.save_context",
      params,
    );
  }

  mirofishGetContext(params: { as_of_date?: string } = {}): Promise<{
    context: MirofishContext | null;
  }> {
    return this.client.call<{ context: MirofishContext | null }>("mirofish.get_context", params);
  }
}

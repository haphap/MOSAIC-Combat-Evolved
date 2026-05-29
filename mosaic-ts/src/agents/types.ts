/**
 * Output contracts for the 4-layer 25-agent daily cycle (Plan §5).
 *
 * Each layer-X agent produces a typed payload that gets written into
 * ``state.layer<X>_outputs[<agent_id>]`` by the dict-merge reducer in
 * ``state.ts``. Aggregator nodes at the end of each layer collapse those
 * maps into a single consensus object (``layer<X>_consensus``).
 *
 * Conventions:
 *   * All confidences are in [0, 1].
 *   * All dates are ISO yyyy-mm-dd strings.
 *   * Tickers follow the canonical MOSAIC form ``"600519.SH" | "300750.SZ" |
 *     "2800.HK"``. Numeric-only / Eastmoney prefixed forms ("SH600519") are
 *     normalised at the bridge boundary.
 *
 * State.ts uses these as TS interfaces (compile-time only). Each agent
 * additionally exports a Zod schema for runtime validation of the LLM
 * structured-output payload (``z.infer<typeof XSchema>`` matches the
 * interface here). The schemas live next to the agent node in
 * ``agents/<layer>/<agent>.ts``.
 */

// ============================================================ Layer 1: Macro

/** Plan §5.1 — central_bank, geopolitical, china, dollar, yield_curve,
 *  commodities, volatility, emerging_markets, news_sentiment, institutional_flow.
 *
 *  Each agent emits a different payload shape; the union below covers the 10
 *  but consumers usually narrow by agent ID. The aggregator only reads the
 *  shared `confidence` + `key_drivers` fields.
 */
export interface MacroAgentOutputBase {
  /** Agent ID, e.g. "central_bank". Useful for debugging when payloads are
   *  passed around without their map key. */
  agent: string;
  /** Required by every macro agent — drives layer_1_consensus_score. */
  confidence: number;
  /** ≤ 5 short evidence bullets pulled from tool returns. */
  key_drivers: string[];
}

export interface CentralBankOutput extends MacroAgentOutputBase {
  agent: "central_bank";
  stance: "ACCOMMODATIVE" | "NEUTRAL" | "TIGHTENING";
  key_rate_change_bps: number;
  qe_qt_balance_change: string;
  next_window: string;
}

export interface GeopoliticalOutput extends MacroAgentOutputBase {
  agent: "geopolitical";
  /** 1 (calm) → 5 (acute crisis). */
  escalation_level: 1 | 2 | 3 | 4 | 5;
  hot_zones: string[];
  trade_impact: string;
}

export interface ChinaOutput extends MacroAgentOutputBase {
  agent: "china";
  policy_direction: "PRO_GROWTH" | "BALANCED" | "RESTRAINING";
  sector_focus: string[];
  risk_drivers: string[];
}

export interface DollarOutput extends MacroAgentOutputBase {
  agent: "dollar";
  dxy_trend: "STRENGTHENING" | "STABLE" | "WEAKENING";
  cny_pressure: "HIGH" | "MODERATE" | "LOW";
  /** Integer correlation × 100 (e.g. 73 means 0.73). */
  north_flow_correlation: number;
}

export interface YieldCurveOutput extends MacroAgentOutputBase {
  agent: "yield_curve";
  curve_shape: "STEEPENING" | "FLATTENING" | "INVERTED" | "BULL_FLATTENING";
  recession_signal: "GREEN" | "YELLOW" | "RED";
  /** China minus US 10Y yield, in basis points. */
  cn_us_spread_bps: number;
}

export interface CommoditiesOutput extends MacroAgentOutputBase {
  agent: "commodities";
  oil_regime: "BACKWARDATION" | "CONTANGO" | "NEUTRAL";
  metals_regime: "RISK_ON" | "RISK_OFF" | "ROTATING";
  ag_regime: "TIGHT" | "BALANCED" | "GLUT";
  china_demand_signal: "ACCELERATING" | "STEADY" | "DECELERATING";
}

export interface VolatilityOutput extends MacroAgentOutputBase {
  agent: "volatility";
  vix_regime: "LOW" | "ELEVATED" | "STRESS";
  ivx_regime: "LOW" | "ELEVATED" | "STRESS";
  /** Computed from VIX/iVX ratio per Plan §5.1. */
  regime_filter: "RISK_ON" | "NEUTRAL" | "RISK_OFF";
}

export interface EmergingMarketsOutput extends MacroAgentOutputBase {
  agent: "emerging_markets";
  em_relative: "OUTPERFORMING" | "INLINE" | "UNDERPERFORMING";
  /** HK index level / A-share index level. */
  hk_a_share_ratio: number;
  capital_flow: "NET_INFLOW" | "FLAT" | "NET_OUTFLOW";
}

export interface NewsSentimentOutput extends MacroAgentOutputBase {
  agent: "news_sentiment";
  /** Retail sentiment from Xueqiu, normalised to [-1, 1]. */
  retail_sentiment_score: number;
  hot_topics: string[];
  /** True when retail sentiment diverges sharply from institutional flow. */
  contrarian_flag: boolean;
}

export interface InstitutionalFlowOutput extends MacroAgentOutputBase {
  agent: "institutional_flow";
  /** Net north-bound (HK→A) flow in CNY million. Negative = outflow. */
  north_net_flow_cny: number;
  /** Top 5 buyer institutions by amount. */
  top_buyers: string[];
  /** Sectors net bought (positive amount) / sold (negative). */
  sectors_in_out: Array<{ sector: string; net_amount_cny: number }>;
}

export type MacroAgentOutput =
  | CentralBankOutput
  | GeopoliticalOutput
  | ChinaOutput
  | DollarOutput
  | YieldCurveOutput
  | CommoditiesOutput
  | VolatilityOutput
  | EmergingMarketsOutput
  | NewsSentimentOutput
  | InstitutionalFlowOutput;

/** Plan §5.1 — aggregated regime call after all 10 macro agents have written. */
export interface RegimeSignal {
  stance: "BULLISH" | "BEARISH" | "NEUTRAL";
  confidence: number;
  key_drivers: string[];
  /** Mean confidence of the 10 macro agents weighted by their stance alignment. */
  layer_1_consensus_score: number;
}

// ============================================================ Layer 2: Sector

/** Plan §5.2 — semiconductor, energy, biotech, consumer, industrials, financials,
 *  relationship_mapper.
 *
 *  Sector agents share a uniform shape: longs / shorts with thesis, plus a
 *  numeric sector_score. relationship_mapper deviates and uses
 *  ``RelationshipMapperOutput`` instead.
 */
export interface SectorPick {
  ticker: string;
  thesis: string;
  /** [0, 1]. */
  conviction: number;
}

export interface SectorAgentOutputBase {
  agent: string;
  longs: SectorPick[];
  shorts: SectorPick[];
  /** [-1, 1], where +1 = max bullish on the sector. */
  sector_score: number;
  key_drivers: string[];
}

export interface RelationshipMapperOutput {
  agent: "relationship_mapper";
  supply_chains: Array<{ name: string; tickers: string[]; risk: string }>;
  ownership_clusters: Array<{ cluster_id: string; tickers: string[] }>;
  contagion_risks: string[];
}

export type SectorAgentOutput = SectorAgentOutputBase | RelationshipMapperOutput;

/** Aggregated sector view written by the L2 aggregator. */
export interface SectorConsensus {
  /** Top 3 sectors with the strongest positive sector_score. */
  top_sectors: Array<{ sector: string; score: number }>;
  /** Top 3 sectors with the strongest negative sector_score. */
  bottom_sectors: Array<{ sector: string; score: number }>;
  /** Cross-sector contagion or relationship signals from relationship_mapper. */
  cross_sector_risks: string[];
}

// ============================================================ Layer 3: Superinvestor

/** Plan §5.3 — druckenmiller, aschenbrenner, baker, ackman.
 *
 *  Each superinvestor applies a philosophy filter and produces a concentrated
 *  pick list (typically 3–5 names) with the philosophical rationale.
 */
export interface SuperinvestorPick {
  ticker: string;
  /** The investor-style rationale: macro asymmetry / IP moat / quality compounder / AI cycle. */
  thesis: string;
  conviction: number;
  /** Suggested holding period bracket. */
  holding_period: "1W" | "1M" | "3M" | "6M" | "1Y" | "5Y+";
}

export interface SuperinvestorOutput {
  agent: "druckenmiller" | "aschenbrenner" | "baker" | "ackman";
  picks: SuperinvestorPick[];
  /** Why these 3-5 names + macro/sector regime fit. */
  philosophy_note: string;
  key_drivers: string[];
}

// ============================================================ Layer 4: Decision

/** Plan §5.4 — cro, alpha_discovery, autonomous_execution, cio. */

export interface CroOutput {
  agent: "cro";
  rejected_picks: Array<{ ticker: string; reason: string }>;
  correlated_risks: string[];
  black_swan_scenarios: string[];
}

export interface AlphaDiscoveryOutput {
  agent: "alpha_discovery";
  novel_picks: Array<{ ticker: string; why_missed_by_others: string }>;
}

export interface AutoExecOutput {
  agent: "autonomous_execution";
  trades: Array<{
    ticker: string;
    action: "BUY" | "SELL" | "HOLD" | "REDUCE";
    size_pct: number;
    conviction: number;
  }>;
}

export interface PortfolioAction {
  ticker: string;
  action: "BUY" | "SELL" | "HOLD" | "REDUCE";
  /** Target portfolio weight in [0, 1]. */
  target_weight: number;
  holding_period: SuperinvestorPick["holding_period"];
  /** CIO note explaining dissent against another agent's call, if any. */
  dissent_notes: string;
}

export interface CioOutput {
  agent: "cio";
  portfolio_actions: PortfolioAction[];
}

export interface Layer4Outputs {
  cro: CroOutput | null;
  alpha_discovery: AlphaDiscoveryOutput | null;
  autonomous_execution: AutoExecOutput | null;
  cio: CioOutput | null;
}

// ============================================================ Observability

export interface LlmCallRecord {
  /** ISO timestamp of the call. */
  ts: string;
  /** Logical agent that triggered the call (e.g. "central_bank"). */
  agent: string;
  /** Model identifier from the bridge config (e.g. "claude-sonnet-4"). */
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  /** Provider as resolved by the LLM factory. */
  provider: string;
  /** Estimated USD cost; computed at the call site, may be 0 for local providers. */
  cost_usd: number;
}

// ============================================================ Convenience

/** Complete final cycle output for downstream consumers (Phase 3 scorecard,
 *  TUI rendering, persistence). */
export interface DailyCycleResult {
  active_cohort: string;
  as_of_date: string;
  layer1_outputs: Record<string, MacroAgentOutput>;
  layer1_consensus: RegimeSignal | null;
  layer2_outputs: Record<string, SectorAgentOutput>;
  layer2_consensus: SectorConsensus | null;
  layer3_outputs: Record<string, SuperinvestorOutput>;
  layer4_outputs: Layer4Outputs;
  /** The CIO's final allocation, surfaced for convenience. */
  portfolio_actions: PortfolioAction[];
  llm_calls: LlmCallRecord[];
  trace_id: string;
}

/**
 * Zod schemas for Layer-1 macro agents (Plan §5.1).
 *
 * Co-located in this file so a single agent-config table can reference all
 * 10 schemas from one import. ``z.infer<typeof X> extends Y`` guards at
 * the bottom prevent schema-vs-interface drift at compile time.
 */

import { z } from "zod";
import type {
  CentralBankOutput,
  ChinaOutput,
  CommoditiesOutput,
  DollarOutput,
  EmergingMarketsOutput,
  GeopoliticalOutput,
  InstitutionalFlowOutput,
  MacroAgentOutput,
  NewsSentimentOutput,
  VolatilityOutput,
  YieldCurveOutput,
} from "../types.js";

// ---------------------------------------------------------------------------
// Shared base helpers
// ---------------------------------------------------------------------------

const KEY_DRIVERS = z
  .array(z.string().min(1).describe("≤ 30-char evidence bullet pulled from tool returns"))
  .min(1)
  .max(8)
  .describe(
    "3-5 concrete evidence bullets, each containing a number or date. " +
      "Vague phrases like '偏松' or 'turning hawkish' without a metric are not allowed.",
  );

const CONFIDENCE = z
  .number()
  .min(0)
  .max(1)
  .describe(
    "Self-rated certainty in [0, 1]. Use ≥ 0.7 only when every required tool returned " +
      "conclusive data; drop to ≤ 0.5 if any tool failed or returned thin data.",
  );

const STRING_LIST_1_8 = (label: string) => z.array(z.string().min(1)).min(1).max(8).describe(label);

// ---------------------------------------------------------------------------
// 1. central_bank (Plan §5.1)
// ---------------------------------------------------------------------------

export const CentralBankSchema = z
  .object({
    agent: z.literal("central_bank"),
    stance: z
      .enum(["ACCOMMODATIVE", "NEUTRAL", "TIGHTENING"])
      .describe("Combined PBOC + Fed stance for the as_of_date window."),
    key_rate_change_bps: z
      .number()
      .describe(
        "Combined effective rate-change direction in basis points; negative = easing. " +
          "Synthesise PBOC + Fed actions into a single signed number.",
      ),
    qe_qt_balance_change: z
      .string()
      .min(1)
      .describe(
        "Free-form summary of OMO / MLF / QE balance shifts, e.g. " +
          "'OMO net injection +20B CNY, MLF -150B CNY'.",
      ),
    next_window: z
      .string()
      .describe(
        "Either an ISO yyyy-mm-dd date for the next material policy window, " +
          "or the literal token 'unknown'.",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Central-bank stance read for one daily-cycle date. Required: dual-bank (PBOC + Fed) " +
      "coupling explicitly assessed.",
  );

export const CENTRAL_BANK_FIELD_NAMES = [
  "stance",
  "key_rate_change_bps",
  "qe_qt_balance_change",
  "next_window",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 2. china (Plan §5.1)
// ---------------------------------------------------------------------------

export const ChinaSchema = z
  .object({
    agent: z.literal("china"),
    policy_direction: z
      .enum(["PRO_GROWTH", "BALANCED", "RESTRAINING"])
      .describe(
        "Aggregate Chinese policy posture for the as_of_date window. " +
          "PRO_GROWTH = stimulus / industry support; BALANCED = wait-and-see; " +
          "RESTRAINING = anti-speculation / regulation tightening.",
      ),
    sector_focus: STRING_LIST_1_8(
      "Sectors the policy text is steering capital toward (e.g. '半导体', " +
        "'新质生产力'). Use the tool outputs verbatim; do not paraphrase.",
    ),
    risk_drivers: STRING_LIST_1_8(
      "Domestic risks flagged by the latest policy / capital-flow signals " +
        "(e.g. 'property leverage', 'youth unemployment').",
    ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "China-domestic policy stance read for one daily-cycle date. Required: " +
      "blend industrial-policy + capital-flow signals; do not infer policy from " +
      "PBOC operations alone (that's the central_bank agent's territory).",
  );

export const CHINA_FIELD_NAMES = [
  "policy_direction",
  "sector_focus",
  "risk_drivers",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 3. geopolitical (Plan §5.1)
// ---------------------------------------------------------------------------

export const GeopoliticalSchema = z
  .object({
    agent: z.literal("geopolitical"),
    escalation_level: z
      .union([z.literal(1), z.literal(2), z.literal(3), z.literal(4), z.literal(5)])
      .describe(
        "1 = calm / multilateral cooperation; 2 = mild friction; 3 = active disputes; " +
          "4 = escalation w/ economic measures (tariffs / sanctions / export controls); " +
          "5 = acute crisis (military / large-scale sanctions). Integer 1-5 only.",
      ),
    hot_zones: STRING_LIST_1_8(
      "Specific regions / corridors with active tension that affect A-share risk " +
        "(e.g. 'US-China semiconductor exports', 'Taiwan Strait', 'Red Sea shipping').",
    ),
    trade_impact: z
      .string()
      .min(1)
      .describe(
        "Concise summary of how current tensions hit A-share trade-exposed sectors " +
          "(e.g. 'export controls on advanced node tools tighten further; 半导体设备 -3% premium').",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Geopolitical risk read with focus on Sino-US frictions + adjacent zones. " +
      "Output is read by sector agents (semiconductor / energy) for risk premium adjustment.",
  );

export const GEOPOLITICAL_FIELD_NAMES = [
  "escalation_level",
  "hot_zones",
  "trade_impact",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 4. dollar (Plan §5.1)
// ---------------------------------------------------------------------------

export const DollarSchema = z
  .object({
    agent: z.literal("dollar"),
    dxy_trend: z
      .enum(["STRENGTHENING", "STABLE", "WEAKENING"])
      .describe("Broad-dollar trajectory over the window, using exact FRED DTWEXBGS."),
    cny_pressure: z
      .enum(["HIGH", "MODERATE", "LOW"])
      .describe(
        "Pressure on USD/CNY judged from DXY trend + CN-US 10Y spread sign. " +
          "HIGH = depreciation risk; LOW = appreciation tailwind.",
      ),
    dxy_cny_correlation: z
      .number()
      .int()
      .min(-100)
      .max(100)
      .describe(
        "Correlation of USD/CNY with DXY moves over the window, scaled to integer " +
          "percent. Positive = CNY weakens as the broad dollar strengthens (typical).",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Dollar / RMB triangulation read. Required: cite DXY level change in BPS + " +
      "USD/CNY move + CN-US 10Y spread shift.",
  );

export const DOLLAR_FIELD_NAMES = [
  "dxy_trend",
  "cny_pressure",
  "dxy_cny_correlation",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 5. yield_curve (Plan §5.1)
// ---------------------------------------------------------------------------

export const YieldCurveSchema = z
  .object({
    agent: z.literal("yield_curve"),
    curve_shape: z
      .enum(["STEEPENING", "FLATTENING", "INVERTED", "BULL_FLATTENING"])
      .describe(
        "CN curve shape transition over the window. BULL_FLATTENING = long end falls " +
          "faster than short end (recession-front risk).",
      ),
    recession_signal: z
      .enum(["GREEN", "YELLOW", "RED"])
      .describe(
        "Composite recession risk light: GREEN = curve healthy steep; YELLOW = flat or " +
          "mild inversion; RED = persistent inversion + bull-flattening.",
      ),
    cn_us_spread_bps: z
      .number()
      .describe(
        "Current CN 10Y - US 10Y spread in basis points (sourced from get_us_china_spread). " +
          "Negative spread is normal in 2024+; sign + magnitude both matter.",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "CN yield-curve regime + CN-US 10Y spread read. Required: cite specific BPS values " +
      "and curve-shape changes by tenor (1y/2y/10y).",
  );

export const YIELD_CURVE_FIELD_NAMES = [
  "curve_shape",
  "recession_signal",
  "cn_us_spread_bps",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 6. commodities (Plan §5.1)
// ---------------------------------------------------------------------------

export const CommoditiesSchema = z
  .object({
    agent: z.literal("commodities"),
    oil_regime: z
      .enum(["BACKWARDATION", "CONTANGO", "NEUTRAL"])
      .describe(
        "Crude-oil regime inferred from the commodity futures basket and optional WTI cross-check. " +
          "BACKWARDATION = tight/upward crude path; CONTANGO = slack/weak crude path.",
      ),
    metals_regime: z
      .enum(["RISK_ON", "RISK_OFF", "ROTATING"])
      .describe(
        "Industrial / precious metals regime inferred from copper, ferrous and gold futures paths.",
      ),
    ag_regime: z
      .enum(["TIGHT", "BALANCED", "GLUT"])
      .describe(
        "Agricultural commodities supply-demand state inferred from soybean meal + energy.",
      ),
    china_demand_signal: z
      .enum(["ACCELERATING", "STEADY", "DECELERATING"])
      .describe(
        "Implicit Chinese commodity demand signal from oil + metals price action " +
          "+ CN yield curve shape (recall PBOC easing usually precedes commodity demand).",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Commodities regime read split into oil / metals / ag / China-demand axes. " +
      "Phase 0 only has oil + gold tools; ag is currently a derived inference.",
  );

export const COMMODITIES_FIELD_NAMES = [
  "oil_regime",
  "metals_regime",
  "ag_regime",
  "china_demand_signal",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 7. volatility (Plan §5.1)
// ---------------------------------------------------------------------------

export const VolatilitySchema = z
  .object({
    agent: z.literal("volatility"),
    vix_regime: z
      .enum(["LOW", "ELEVATED", "STRESS"])
      .describe("Current VIX (FRED VIXCLS) regime: LOW < 15, ELEVATED 15-25, STRESS > 25."),
    ivx_regime: z
      .enum(["LOW", "ELEVATED", "STRESS"])
      .describe(
        "iVX (China implied vol) regime. Phase 0 lacks a direct iVX feed; for now " +
          "infer from CN curve volatility + cross-cite VIX. Mark confidence ≤ 0.5 if no " +
          "iVX-specific data is available.",
      ),
    regime_filter: z
      .enum(["RISK_ON", "NEUTRAL", "RISK_OFF"])
      .describe(
        "Top-level regime gate consumed by execution layer (Plan §5.4). RISK_OFF when " +
          "VIX > 25 OR iVX > 30 OR persistent CN curve inversion.",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Volatility regime classifier. Required: cite VIX absolute level + week-over-week change.",
  );

export const VOLATILITY_FIELD_NAMES = [
  "vix_regime",
  "ivx_regime",
  "regime_filter",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 8. emerging_markets (Plan §5.1)
// ---------------------------------------------------------------------------

export const EmergingMarketsSchema = z
  .object({
    agent: z.literal("emerging_markets"),
    em_relative: z
      .enum(["OUTPERFORMING", "INLINE", "UNDERPERFORMING"])
      .describe(
        "EM (proxy: cross-market ETF prices + USD trend + CN-US spread) performance vs DM. " +
          "OUTPERFORMING when DXY weakening + A/HK ETFs rising + spread narrowing.",
      ),
    hk_a_share_ratio: z
      .number()
      .describe(
        "HK index level / A-share index level, computed from cross-market ETF prices " +
          "(e.g. 513050.SH HK-tech vs 510300.SH CSI300 via get_etf_price_data / get_etf_nav).",
      ),
    capital_flow: z
      .enum(["NET_INFLOW", "FLAT", "NET_OUTFLOW"])
      .describe(
        "Composite EM capital-flow direction inferred from A/HK ETF price + premium trend " +
          "+ DXY direction + CN-US spread.",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Emerging-markets / HK-A read. Triangulate via cross-market ETF prices + " +
      "us_china_spread + DXY proxy.",
  );

export const EMERGING_MARKETS_FIELD_NAMES = [
  "em_relative",
  "hk_a_share_ratio",
  "capital_flow",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 9. news_sentiment (Plan §5.1)
// ---------------------------------------------------------------------------

export const NewsSentimentSchema = z
  .object({
    agent: z.literal("news_sentiment"),
    retail_sentiment_score: z
      .number()
      .min(-1)
      .max(1)
      .describe(
        "Retail sentiment from Xueqiu hot-follow + recent policy documents, scaled to [-1, 1]. " +
          "+1 = euphoria; -1 = capitulation.",
      ),
    hot_topics: STRING_LIST_1_8(
      "Top 5-8 hot topics on Xueqiu / news today (concrete tickers or themes, e.g. " +
        "'600519.SH 茅台', '半导体设备国产替代').",
    ),
    contrarian_flag: z
      .boolean()
      .describe(
        "True when retail sentiment diverges sharply from institutional flow (e.g. retail " +
          "euphoric while main funds are selling). Sector / superinvestor agents read this.",
      ),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Retail-sentiment read built from Xueqiu hot-follow + gov.cn policy documents. The " +
      "contrarian_flag is the most actionable downstream signal.",
  );

export const NEWS_SENTIMENT_FIELD_NAMES = [
  "retail_sentiment_score",
  "hot_topics",
  "contrarian_flag",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// 10. institutional_flow (Plan §5.1)
// ---------------------------------------------------------------------------

export const InstitutionalFlowSchema = z
  .object({
    agent: z.literal("institutional_flow"),
    main_net_flow_cny: z
      .number()
      .describe(
        "Cumulative main-funds (主力: large + extra-large orders, from get_stock_moneyflow) " +
          "net flow over the window in CNY millions. Negative = outflow.",
      ),
    top_buyers: STRING_LIST_1_8(
      "Top 3-5 institutions / 龙虎榜 buyer codes by amount over the window. " +
        "Use ts_code or institution name verbatim from tool returns.",
    ),
    sectors_in_out: z
      .array(
        z.object({
          sector: z.string().min(1),
          net_amount_cny: z.number(),
        }),
      )
      .min(1)
      .max(15)
      .describe("Sectors net bought (positive) or sold (negative) over the window, in CNY mil."),
    key_drivers: KEY_DRIVERS,
    confidence: CONFIDENCE,
  })
  .describe(
    "Institutional flow read from main-funds money-flow + 龙虎榜. Required: surface concrete " +
      "ts_codes + magnitudes; sector-level aggregation is the primary downstream input.",
  );

export const INSTITUTIONAL_FLOW_FIELD_NAMES = [
  "main_net_flow_cny",
  "top_buyers",
  "sectors_in_out",
  "key_drivers",
  "confidence",
] as const;

// ---------------------------------------------------------------------------
// Type-check guards: zod schema must produce the canonical TS interface.
// These are unused at runtime; they exist to make `tsc` reject schema drift.
// ---------------------------------------------------------------------------

type _GuardEqShape<T, U> = T extends U ? (U extends T ? true : never) : never;

const _centralBankSchemaCheck: _GuardEqShape<
  z.infer<typeof CentralBankSchema>,
  CentralBankOutput
> = true;
const _chinaSchemaCheck: _GuardEqShape<z.infer<typeof ChinaSchema>, ChinaOutput> = true;
const _geopoliticalSchemaCheck: _GuardEqShape<
  z.infer<typeof GeopoliticalSchema>,
  GeopoliticalOutput
> = true;
const _dollarSchemaCheck: _GuardEqShape<z.infer<typeof DollarSchema>, DollarOutput> = true;
const _yieldCurveSchemaCheck: _GuardEqShape<
  z.infer<typeof YieldCurveSchema>,
  YieldCurveOutput
> = true;
const _commoditiesSchemaCheck: _GuardEqShape<
  z.infer<typeof CommoditiesSchema>,
  CommoditiesOutput
> = true;
const _volatilitySchemaCheck: _GuardEqShape<
  z.infer<typeof VolatilitySchema>,
  VolatilityOutput
> = true;
const _emergingMarketsSchemaCheck: _GuardEqShape<
  z.infer<typeof EmergingMarketsSchema>,
  EmergingMarketsOutput
> = true;
const _newsSentimentSchemaCheck: _GuardEqShape<
  z.infer<typeof NewsSentimentSchema>,
  NewsSentimentOutput
> = true;
const _institutionalFlowSchemaCheck: _GuardEqShape<
  z.infer<typeof InstitutionalFlowSchema>,
  InstitutionalFlowOutput
> = true;

export type _MacroSchemaGuards = MacroAgentOutput; // re-exported so unused-import lint stays quiet
void _centralBankSchemaCheck;
void _chinaSchemaCheck;
void _geopoliticalSchemaCheck;
void _dollarSchemaCheck;
void _yieldCurveSchemaCheck;
void _commoditiesSchemaCheck;
void _volatilitySchemaCheck;
void _emergingMarketsSchemaCheck;
void _newsSentimentSchemaCheck;
void _institutionalFlowSchemaCheck;

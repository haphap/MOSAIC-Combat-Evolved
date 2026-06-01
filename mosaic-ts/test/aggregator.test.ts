/**
 * Tests for the deterministic Layer-1 aggregator (Plan §11.2 sub-step 2C.3).
 *
 * Pure-function tests cover:
 *   - voteForAgent maps every agent's stance field correctly
 *   - aggregateLayer1 produces BULLISH / BEARISH / NEUTRAL given controlled votes
 *   - confidence + alignment_ratio drive consensus_score
 *   - key_drivers honours the > 0.5 confidence gate + per-agent ordering
 *   - the LangGraph node wrapper produces a state update
 */

import { describe, expect, it } from "vitest";
import {
  ALL_MACRO_AGENTS,
  aggregateLayer1,
  aggregateLayer1Node,
  STANCE_THRESHOLD,
  voteForAgent,
} from "../src/agents/macro/_aggregator.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
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
  RegimeSignal,
  VolatilityOutput,
  YieldCurveOutput,
} from "../src/agents/types.js";

// ============================================================ canned outputs

const CB_BULL: CentralBankOutput = {
  agent: "central_bank",
  stance: "ACCOMMODATIVE",
  key_rate_change_bps: -10,
  qe_qt_balance_change: "OMO +20B",
  next_window: "2024-07-15",
  key_drivers: ["MLF rolled lower"],
  confidence: 0.8,
};
const CB_BEAR: CentralBankOutput = { ...CB_BULL, stance: "TIGHTENING" };
const CB_NEUT: CentralBankOutput = { ...CB_BULL, stance: "NEUTRAL" };

const CN_BULL: ChinaOutput = {
  agent: "china",
  policy_direction: "PRO_GROWTH",
  sector_focus: ["半导体"],
  risk_drivers: ["地方债"],
  key_drivers: ["国务院 6/24 产业政策"],
  confidence: 0.7,
};
const CN_BEAR: ChinaOutput = { ...CN_BULL, policy_direction: "RESTRAINING" };

const GEO_BULL: GeopoliticalOutput = {
  agent: "geopolitical",
  escalation_level: 1,
  hot_zones: ["multilateral cooperation"],
  trade_impact: "no impact",
  key_drivers: ["G7 framework agreement"],
  confidence: 0.6,
};
const GEO_BEAR: GeopoliticalOutput = { ...GEO_BULL, escalation_level: 5 };
const GEO_NEUT: GeopoliticalOutput = { ...GEO_BULL, escalation_level: 3 };

const DLR_BULL: DollarOutput = {
  agent: "dollar",
  dxy_trend: "WEAKENING",
  cny_pressure: "LOW",
  dxy_cny_correlation: 73,
  key_drivers: ["DXY -1.2% WoW"],
  confidence: 0.7,
};
const DLR_BEAR: DollarOutput = { ...DLR_BULL, dxy_trend: "STRENGTHENING", cny_pressure: "HIGH" };

const YC_BULL: YieldCurveOutput = {
  agent: "yield_curve",
  curve_shape: "STEEPENING",
  recession_signal: "GREEN",
  cn_us_spread_bps: -150,
  key_drivers: ["CN 10Y +5bp WoW"],
  confidence: 0.7,
};
const YC_BEAR: YieldCurveOutput = {
  ...YC_BULL,
  curve_shape: "BULL_FLATTENING",
  recession_signal: "RED",
};

const CMD_BULL: CommoditiesOutput = {
  agent: "commodities",
  oil_regime: "BACKWARDATION",
  metals_regime: "RISK_ON",
  ag_regime: "BALANCED",
  china_demand_signal: "ACCELERATING",
  key_drivers: ["WTI 81 +3% WoW"],
  confidence: 0.5,
};
const CMD_BEAR: CommoditiesOutput = { ...CMD_BULL, china_demand_signal: "DECELERATING" };

const VOL_BULL: VolatilityOutput = {
  agent: "volatility",
  vix_regime: "LOW",
  ivx_regime: "LOW",
  regime_filter: "RISK_ON",
  key_drivers: ["VIX 13.4"],
  confidence: 0.6,
};
const VOL_BEAR: VolatilityOutput = {
  ...VOL_BULL,
  vix_regime: "STRESS",
  ivx_regime: "STRESS",
  regime_filter: "RISK_OFF",
};

const EM_BULL: EmergingMarketsOutput = {
  agent: "emerging_markets",
  em_relative: "OUTPERFORMING",
  hk_a_share_ratio: 1.4,
  capital_flow: "NET_INFLOW",
  key_drivers: ["main funds +120B CNY week"],
  confidence: 0.5,
};
const EM_BEAR: EmergingMarketsOutput = {
  ...EM_BULL,
  em_relative: "UNDERPERFORMING",
  capital_flow: "NET_OUTFLOW",
};

const NS_BULL: NewsSentimentOutput = {
  agent: "news_sentiment",
  retail_sentiment_score: 0.6,
  hot_topics: ["半导体设备"],
  contrarian_flag: false,
  key_drivers: ["Xueqiu top-50 follower count +12%"],
  confidence: 0.6,
};
const NS_CONTRARIAN: NewsSentimentOutput = {
  ...NS_BULL,
  contrarian_flag: true, // retail euphoric while institutions selling = bearish
};
const NS_BEAR: NewsSentimentOutput = {
  ...NS_BULL,
  retail_sentiment_score: -0.6,
};

const IF_BULL: InstitutionalFlowOutput = {
  agent: "institutional_flow",
  main_net_flow_cny: 12345,
  top_buyers: ["中信证券上海溧阳路营业部"],
  sectors_in_out: [
    { sector: "semiconductor", net_amount_cny: 5000 },
    { sector: "consumer", net_amount_cny: -3000 },
  ],
  key_drivers: ["semi sector +5B CNY net buy"],
  confidence: 0.6,
};
const IF_BEAR: InstitutionalFlowOutput = {
  ...IF_BULL,
  sectors_in_out: [{ sector: "semiconductor", net_amount_cny: -5000 }],
};

// ============================================================ voteForAgent

describe("voteForAgent maps stance to vote per Plan §11.2 2C.3", () => {
  const cases = [
    [CB_BULL, +1, "central_bank ACCOMMODATIVE"],
    [CB_BEAR, -1, "central_bank TIGHTENING"],
    [CB_NEUT, 0, "central_bank NEUTRAL"],
    [CN_BULL, +1, "china PRO_GROWTH"],
    [CN_BEAR, -1, "china RESTRAINING"],
    [GEO_BULL, +1, "geopolitical level 1"],
    [GEO_BEAR, -1, "geopolitical level 5"],
    [GEO_NEUT, 0, "geopolitical level 3"],
    [DLR_BULL, +1, "dollar WEAKENING"],
    [DLR_BEAR, -1, "dollar STRENGTHENING"],
    [YC_BULL, +1, "yield_curve GREEN"],
    [YC_BEAR, -1, "yield_curve RED"],
    [CMD_BULL, +1, "commodities ACCELERATING"],
    [CMD_BEAR, -1, "commodities DECELERATING"],
    [VOL_BULL, +1, "volatility RISK_ON"],
    [VOL_BEAR, -1, "volatility RISK_OFF"],
    [EM_BULL, +1, "emerging_markets OUTPERFORMING"],
    [EM_BEAR, -1, "emerging_markets UNDERPERFORMING"],
    [NS_BULL, +1, "news_sentiment positive non-contrarian"],
    [NS_BEAR, -1, "news_sentiment score < -0.3"],
    [NS_CONTRARIAN, -1, "news_sentiment contrarian retail euphoria"],
    [IF_BULL, +1, "institutional_flow net positive across sectors"],
    [IF_BEAR, -1, "institutional_flow net negative"],
  ] as const;

  for (const [out, expected, label] of cases) {
    it(`${label}`, () => {
      expect(voteForAgent(out as MacroAgentOutput)).toBe(expected);
    });
  }
});

// ============================================================ aggregateLayer1

describe("aggregateLayer1", () => {
  function makeAllBullish(): Record<string, MacroAgentOutput> {
    return {
      central_bank: CB_BULL,
      china: CN_BULL,
      geopolitical: GEO_BULL,
      dollar: DLR_BULL,
      yield_curve: YC_BULL,
      commodities: CMD_BULL,
      volatility: VOL_BULL,
      emerging_markets: EM_BULL,
      news_sentiment: NS_BULL,
      institutional_flow: IF_BULL,
    };
  }

  function makeAllBearish(): Record<string, MacroAgentOutput> {
    return {
      central_bank: CB_BEAR,
      china: CN_BEAR,
      geopolitical: GEO_BEAR,
      dollar: DLR_BEAR,
      yield_curve: YC_BEAR,
      commodities: CMD_BEAR,
      volatility: VOL_BEAR,
      emerging_markets: EM_BEAR,
      news_sentiment: NS_BEAR,
      institutional_flow: IF_BEAR,
    };
  }

  it("calls BULLISH when all 10 agents vote +1", () => {
    const { signal, votes } = aggregateLayer1(makeAllBullish());
    expect(signal.stance).toBe("BULLISH");
    expect(votes).toHaveLength(10);
    expect(signal.confidence).toBeGreaterThan(0.5);
    expect(signal.layer_1_consensus_score).toBeGreaterThan(0.5);
    // Drivers should pull from agents with confidence > 0.5; all 10 in this fixture
    expect(signal.key_drivers.length).toBeGreaterThanOrEqual(8);
  });

  it("calls BEARISH when all 10 agents vote -1", () => {
    const { signal } = aggregateLayer1(makeAllBearish());
    expect(signal.stance).toBe("BEARISH");
    expect(signal.layer_1_consensus_score).toBeGreaterThan(0.5);
  });

  it("returns NEUTRAL when score sits within ±STANCE_THRESHOLD", () => {
    // 5 bullish + 5 bearish all conf 0.5 → score = 0
    const outputs: Record<string, MacroAgentOutput> = {
      central_bank: { ...CB_BULL, confidence: 0.5 },
      china: { ...CN_BULL, confidence: 0.5 },
      geopolitical: { ...GEO_BULL, confidence: 0.5 },
      dollar: { ...DLR_BULL, confidence: 0.5 },
      yield_curve: { ...YC_BULL, confidence: 0.5 },
      commodities: { ...CMD_BEAR, confidence: 0.5 },
      volatility: { ...VOL_BEAR, confidence: 0.5 },
      emerging_markets: { ...EM_BEAR, confidence: 0.5 },
      news_sentiment: { ...NS_BEAR, confidence: 0.5 },
      institutional_flow: { ...IF_BEAR, confidence: 0.5 },
    };
    const { signal } = aggregateLayer1(outputs);
    expect(signal.stance).toBe("NEUTRAL");
  });

  it("conservative ±0.3 threshold: 6:4 weak split stays NEUTRAL", () => {
    // 6 bull conf 0.5 + 4 bear conf 0.5 → weighted score = 0.2 < 0.3 → NEUTRAL
    const outputs: Record<string, MacroAgentOutput> = {
      central_bank: { ...CB_BULL, confidence: 0.5 },
      china: { ...CN_BULL, confidence: 0.5 },
      geopolitical: { ...GEO_BULL, confidence: 0.5 },
      dollar: { ...DLR_BULL, confidence: 0.5 },
      yield_curve: { ...YC_BULL, confidence: 0.5 },
      commodities: { ...CMD_BULL, confidence: 0.5 },
      volatility: { ...VOL_BEAR, confidence: 0.5 },
      emerging_markets: { ...EM_BEAR, confidence: 0.5 },
      news_sentiment: { ...NS_BEAR, confidence: 0.5 },
      institutional_flow: { ...IF_BEAR, confidence: 0.5 },
    };
    const { signal } = aggregateLayer1(outputs);
    // weighted_sum = 6*1*0.5 + 4*-1*0.5 = 1.0; total_weight = 5.0; score = 0.2 → NEUTRAL
    expect(signal.stance).toBe("NEUTRAL");
  });

  it("layer_1_consensus_score = mean_confidence × alignment_ratio", () => {
    // Set up 8 bull (conf 0.7) + 2 neutral (conf 0.7); stance should be BULLISH;
    // alignment_ratio = 8/10 = 0.8; mean_conf = 0.7; consensus = 0.56.
    const outputs: Record<string, MacroAgentOutput> = {
      central_bank: { ...CB_BULL, confidence: 0.7 },
      china: { ...CN_BULL, confidence: 0.7 },
      geopolitical: { ...GEO_BULL, confidence: 0.7 },
      dollar: { ...DLR_BULL, confidence: 0.7 },
      yield_curve: { ...YC_BULL, confidence: 0.7 },
      commodities: { ...CMD_BULL, confidence: 0.7 },
      volatility: { ...VOL_BULL, confidence: 0.7 },
      emerging_markets: { ...EM_BULL, confidence: 0.7 },
      news_sentiment: { ...CN_NEUT_AS_NEWS(), confidence: 0.7 },
      institutional_flow: { ...IF_NEUT_AS_FLOW(), confidence: 0.7 },
    };
    const { signal } = aggregateLayer1(outputs);
    expect(signal.stance).toBe("BULLISH");
    expect(signal.confidence).toBeCloseTo(0.7, 2);
    expect(signal.layer_1_consensus_score).toBeCloseTo(0.56, 2);
  });

  it("key_drivers excludes agents with confidence ≤ 0.5", () => {
    const outputs: Record<string, MacroAgentOutput> = {
      central_bank: { ...CB_BULL, confidence: 0.8, key_drivers: ["high-conf driver"] },
      china: { ...CN_BULL, confidence: 0.4, key_drivers: ["LOW-CONF DRIVER"] },
      geopolitical: { ...GEO_BULL, confidence: 0.7, key_drivers: ["another high"] },
    };
    const { signal } = aggregateLayer1(outputs);
    const joined = signal.key_drivers.join("|");
    expect(joined).toContain("high-conf driver");
    expect(joined).toContain("another high");
    expect(joined).not.toContain("LOW-CONF DRIVER");
  });

  it("returns NEUTRAL stub when outputs is empty", () => {
    const { signal, votes } = aggregateLayer1({});
    expect(signal.stance).toBe("NEUTRAL");
    expect(signal.confidence).toBe(0);
    expect(votes).toHaveLength(0);
  });

  it("ALL_MACRO_AGENTS list matches the expected 10 names", () => {
    expect(ALL_MACRO_AGENTS).toEqual([
      "central_bank",
      "china",
      "geopolitical",
      "dollar",
      "yield_curve",
      "commodities",
      "volatility",
      "emerging_markets",
      "news_sentiment",
      "institutional_flow",
    ]);
  });

  it("STANCE_THRESHOLD is the documented 0.3 (Plan §11.2)", () => {
    expect(STANCE_THRESHOLD).toBe(0.3);
  });
});

// ============================================================ aggregateLayer1Node

describe("aggregateLayer1Node (LangGraph wrapper)", () => {
  it("reads state.layer1_outputs and returns layer1_consensus update", async () => {
    const sample: DailyCycleStateType = {
      messages: [],
      active_cohort: "cohort_default",
      as_of_date: "2024-06-24",
      mode: "live",
      trace_id: "test",
      continuity_context: {},
      lesson_context: {},
      method_context: {},
      layer1_outputs: { central_bank: CB_BULL, china: CN_BULL },
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
      portfolio_actions: [],
      replay_triggered: false,
      llm_calls: [],
    };
    const update = (await aggregateLayer1Node(sample)) as DailyCycleStateUpdate;
    const consensus = (update as { layer1_consensus?: RegimeSignal | null }).layer1_consensus;
    expect(consensus?.stance).toBe("BULLISH"); // both BULL with high conf
    expect(consensus?.layer_1_consensus_score).toBeGreaterThan(0.4);
  });
});

// ============================================================ helpers

/** A NEUTRAL news_sentiment fixture (vote = 0). */
function CN_NEUT_AS_NEWS(): NewsSentimentOutput {
  return {
    agent: "news_sentiment",
    retail_sentiment_score: 0.0,
    hot_topics: ["mixed"],
    contrarian_flag: false,
    key_drivers: ["mixed"],
    confidence: 0.7,
  };
}

/** A NEUTRAL institutional_flow fixture (vote = 0; net flow within ±1B). */
function IF_NEUT_AS_FLOW(): InstitutionalFlowOutput {
  return {
    agent: "institutional_flow",
    main_net_flow_cny: 0,
    top_buyers: ["mixed"],
    sectors_in_out: [{ sector: "mixed", net_amount_cny: 0 }],
    key_drivers: ["mixed"],
    confidence: 0.7,
  };
}

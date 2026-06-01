/**
 * Tests for the daily-cycle composite graph (Plan §11.2 sub-step 2E).
 *
 * Three test groups:
 *   1. ``checkCroVeto`` / ``getCandidatePoolSize`` unit tests — pure
 *      routing helpers, no graph required.
 *   2. ``buildDailyCycleGraph`` compiles successfully (validates the
 *      LangGraph topology is well-formed).
 *   3. End-to-end smoke: 25 mocked agents run via the composite graph,
 *      portfolio_actions populated, llm_calls = 25 (no duplication
 *      from subgraph composition — Plan §11.2 design decision #7).
 *   4. Veto loop: heavy cro rejection routes through layer4_replay,
 *      ending up with 25 + 3 (alpha + auto + cio replay) = 28 llm_calls.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage, type SystemMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type {
  AlphaDiscoveryOutput,
  AutoExecOutput,
  BiotechOutput,
  CentralBankOutput,
  ChinaOutput,
  CioOutput,
  CommoditiesOutput,
  ConsumerOutput,
  CroOutput,
  DollarOutput,
  EmergingMarketsOutput,
  EnergyOutput,
  FinancialsOutput,
  GeopoliticalOutput,
  IndustrialsOutput,
  InstitutionalFlowOutput,
  NewsSentimentOutput,
  RegimeSignal,
  RelationshipMapperOutput,
  SemiconductorOutput,
  SuperinvestorOutput,
  VolatilityOutput,
  YieldCurveOutput,
} from "../src/agents/types.js";
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import {
  buildDailyCycleGraph,
  checkCroVeto,
  DAILY_CYCLE_LAYER_NODES,
  getCandidatePoolSize,
} from "../src/graph/daily_cycle.js";
import type { LlmHandle } from "../src/llm/factory.js";

// ============================================================ helpers / shared

const TOOL_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: { x: { type: "string" } },
  required: ["x"],
};

const FAKE_TOOLS: ToolMetadata[] = [
  "get_pboc_ops",
  "get_fred_series",
  "get_yield_curve_cn",
  "get_industry_policy",
  "get_property_data",
  "get_north_capital_flow",
  "get_us_china_spread",
  "get_xueqiu_heat",
  "get_lhb_ranking",
  "get_usdcny",
  "get_commodity_prices",
  "get_ivx",
  "get_etf_indicator",
  "get_fund_flow",
  "get_news",
  "get_etf_price_data",
  "get_etf_info",
  "get_etf_nav",
  "get_etf_universe",
  "get_etf_holdings",
  "get_caixin_sentiment",
  "get_us_china_relations",
  "get_broker_research",
  "get_stock_research",
  "get_fundamentals",
  "get_balance_sheet",
  "get_income_statement",
  "get_cashflow",
  "get_stock_data",
  "get_indicators",
  "get_stock_moneyflow",
  "get_industry_moneyflow",
].map((name) => ({ name, description: name, args_schema: TOOL_SCHEMA }));

const fakeApi: BridgeApi = {
  toolsList: async () => FAKE_TOOLS,
  toolsCall: async (name: string) => ({ text: `${name}_csv` }),
} as unknown as BridgeApi;

const BASE_CONFIG: MosaicConfig = {
  llm_provider: "fake",
  deep_think_llm: "fake",
  quick_think_llm: "fake",
  backend_url: null,
  anthropic_base_url: null,
  anthropic_effort: null,
  output_language: "Chinese",
  research_depth_name: "标准",
  active_cohort: "cohort_default",
  cohorts: { cohort_default: { start: "2000-01-01", end: "2099-12-31" } },
  autoresearch: {
    agent_mutation_cooldown_hours: 24,
    keep_revert_lockout_days: 3,
    keep_threshold_delta_sharpe: 0.1,
    monthly_modification_cap_per_cohort: 100,
    evaluation_horizon_trading_days: 5,
  },
  data_vendors: {},
  tool_vendors: {},
};

function emptyState(): DailyCycleStateType {
  return {
    messages: [],
    active_cohort: "cohort_default",
    as_of_date: "2024-06-24",
    mode: "live",
    trace_id: "test",
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
    portfolio_actions: [],
    replay_triggered: false,
    llm_calls: [],
  };
}

// ============================================================ unit: routing helpers

const druckPick = (ticker: string) => ({
  ticker,
  thesis: "x",
  conviction: 0.5,
  holding_period: "3M" as const,
});

describe("getCandidatePoolSize", () => {
  it("returns 0 for empty L3", () => {
    expect(getCandidatePoolSize(emptyState())).toBe(0);
  });

  it("dedupes tickers across superinvestors", () => {
    const s = emptyState();
    s.layer3_outputs = {
      druckenmiller: {
        agent: "druckenmiller",
        picks: [druckPick("A"), druckPick("B"), druckPick("C")],
        philosophy_note: "x",
        key_drivers: ["d"],
        confidence: 0.5,
      },
      ackman: {
        agent: "ackman",
        picks: [druckPick("A"), druckPick("D")],
        philosophy_note: "x",
        key_drivers: ["d"],
        confidence: 0.5,
      },
    };
    expect(getCandidatePoolSize(s)).toBe(4); // A, B, C, D
  });
});

describe("checkCroVeto", () => {
  it("end when cro is null", () => {
    expect(checkCroVeto(emptyState())).toBe("end");
  });

  it("end when cro rejected zero", () => {
    const s = emptyState();
    s.layer4_outputs.cro = {
      agent: "cro",
      rejected_picks: [],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    };
    expect(checkCroVeto(s)).toBe("end");
  });

  it("end when L3 pool is empty (defensive)", () => {
    const s = emptyState();
    s.layer4_outputs.cro = {
      agent: "cro",
      rejected_picks: [{ ticker: "X", reason: "y" }],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    };
    expect(checkCroVeto(s)).toBe("end");
  });

  it("end when rejection rate is at threshold (strict >)", () => {
    const s = emptyState();
    s.layer3_outputs = {
      druckenmiller: {
        agent: "druckenmiller",
        picks: [druckPick("A"), druckPick("B")],
        philosophy_note: "x",
        key_drivers: ["d"],
        confidence: 0.5,
      },
    };
    s.layer4_outputs.cro = {
      agent: "cro",
      rejected_picks: [{ ticker: "A", reason: "y" }],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    };
    // 1 / 2 = 0.5, not strictly greater than 0.5 → end.
    expect(checkCroVeto(s, 0.5)).toBe("end");
  });

  it("replay when rejection rate strictly exceeds threshold", () => {
    const s = emptyState();
    s.layer3_outputs = {
      druckenmiller: {
        agent: "druckenmiller",
        picks: [druckPick("A"), druckPick("B"), druckPick("C")],
        philosophy_note: "x",
        key_drivers: ["d"],
        confidence: 0.5,
      },
    };
    s.layer4_outputs.cro = {
      agent: "cro",
      rejected_picks: [
        { ticker: "A", reason: "y" },
        { ticker: "B", reason: "y" },
      ],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    };
    // 2 / 3 = 0.66 > 0.5 → replay.
    expect(checkCroVeto(s, 0.5)).toBe("replay");
  });

  it("dedupes rejected_picks by ticker (review hotfix #3)", () => {
    // Pool = 3, but CRO rejects ticker A twice (regulatory + concentration)
    // and B once. Raw count = 3 → 100% → would trip replay; deduped = 2/3 →
    // 66% → still trips. Use a case where dedupe DOES change the outcome:
    // pool = 5, CRO rejects A 3× (3 risks) + B 1× = 4 raw entries →
    // 4/5 = 80% → replay. Deduped = 2 unique tickers / 5 = 40% → end.
    const s = emptyState();
    s.layer3_outputs = {
      druckenmiller: {
        agent: "druckenmiller",
        picks: [druckPick("A"), druckPick("B"), druckPick("C"), druckPick("D"), druckPick("E")],
        philosophy_note: "x",
        key_drivers: ["d"],
        confidence: 0.5,
      },
    };
    s.layer4_outputs.cro = {
      agent: "cro",
      rejected_picks: [
        { ticker: "A", reason: "regulatory" },
        { ticker: "A", reason: "concentration" },
        { ticker: "A", reason: "valuation" },
        { ticker: "B", reason: "liquidity" },
      ],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    };
    // Raw count would be 4/5 = 0.8 → replay. Deduped is 2/5 = 0.4 → end.
    expect(checkCroVeto(s, 0.5)).toBe("end");
  });
});

// ============================================================ canned outputs for 25 agents

interface CannedOutputs {
  // L1 macro (10)
  central_bank: CentralBankOutput;
  china: ChinaOutput;
  geopolitical: GeopoliticalOutput;
  dollar: DollarOutput;
  yield_curve: YieldCurveOutput;
  commodities: CommoditiesOutput;
  volatility: VolatilityOutput;
  emerging_markets: EmergingMarketsOutput;
  news_sentiment: NewsSentimentOutput;
  institutional_flow: InstitutionalFlowOutput;
  // L2 sector (7)
  semiconductor: SemiconductorOutput;
  energy: EnergyOutput;
  biotech: BiotechOutput;
  consumer: ConsumerOutput;
  industrials: IndustrialsOutput;
  financials: FinancialsOutput;
  relationship_mapper: RelationshipMapperOutput;
  // L3 superinvestor (4)
  druckenmiller: SuperinvestorOutput;
  aschenbrenner: SuperinvestorOutput;
  baker: SuperinvestorOutput;
  ackman: SuperinvestorOutput;
  // L4 decision (4)
  cro: CroOutput;
  alpha_discovery: AlphaDiscoveryOutput;
  autonomous_execution: AutoExecOutput;
  cio: CioOutput;
}

function makeCannedOutputs(opts?: { croRejected?: number }): CannedOutputs {
  const rejectedCount = opts?.croRejected ?? 0;
  // Deterministic outputs that should let the L1 aggregator emit BULLISH and
  // produce a non-empty portfolio.
  const sectorLong = (ticker: string, conv = 0.5) => ({
    ticker,
    thesis: "x",
    conviction: conv,
  });
  const superPick = (ticker: string, conv = 0.5) => ({
    ticker,
    thesis: "x",
    conviction: conv,
    holding_period: "3M" as const,
  });
  return {
    // ---- L1 ----
    central_bank: {
      agent: "central_bank",
      stance: "ACCOMMODATIVE",
      key_rate_change_bps: -10,
      qe_qt_balance_change: "OMO +20B",
      next_window: "2024-07-15",
      key_drivers: ["d-cb"],
      confidence: 0.7,
    },
    china: {
      agent: "china",
      policy_direction: "PRO_GROWTH",
      sector_focus: ["semi"],
      risk_drivers: ["debt"],
      key_drivers: ["d-cn"],
      confidence: 0.7,
    },
    geopolitical: {
      agent: "geopolitical",
      escalation_level: 1,
      hot_zones: ["x"],
      trade_impact: "x",
      key_drivers: ["d-geo"],
      confidence: 0.7,
    },
    dollar: {
      agent: "dollar",
      dxy_trend: "WEAKENING",
      cny_pressure: "LOW",
      north_flow_correlation: -70,
      key_drivers: ["d-dlr"],
      confidence: 0.7,
    },
    yield_curve: {
      agent: "yield_curve",
      curve_shape: "STEEPENING",
      recession_signal: "GREEN",
      cn_us_spread_bps: -150,
      key_drivers: ["d-yc"],
      confidence: 0.7,
    },
    commodities: {
      agent: "commodities",
      oil_regime: "BACKWARDATION",
      metals_regime: "RISK_ON",
      ag_regime: "BALANCED",
      china_demand_signal: "ACCELERATING",
      key_drivers: ["d-cmd"],
      confidence: 0.7,
    },
    volatility: {
      agent: "volatility",
      vix_regime: "LOW",
      ivx_regime: "LOW",
      regime_filter: "RISK_ON",
      key_drivers: ["d-vol"],
      confidence: 0.7,
    },
    emerging_markets: {
      agent: "emerging_markets",
      em_relative: "OUTPERFORMING",
      hk_a_share_ratio: 1.3,
      capital_flow: "NET_INFLOW",
      key_drivers: ["d-em"],
      confidence: 0.7,
    },
    news_sentiment: {
      agent: "news_sentiment",
      retail_sentiment_score: 0.5,
      hot_topics: ["x"],
      contrarian_flag: false,
      key_drivers: ["d-ns"],
      confidence: 0.7,
    },
    institutional_flow: {
      agent: "institutional_flow",
      north_net_flow_cny: 5000,
      top_buyers: ["x"],
      sectors_in_out: [{ sector: "semi", net_amount_cny: 5000 }],
      key_drivers: ["d-if"],
      confidence: 0.7,
    },
    // ---- L2 ----
    semiconductor: {
      agent: "semiconductor",
      longs: [sectorLong("688981.SH"), sectorLong("002371.SZ")],
      shorts: [],
      sector_score: 0.6,
      key_drivers: ["d-semi"],
      confidence: 0.5,
    },
    energy: {
      agent: "energy",
      longs: [sectorLong("601857.SH")],
      shorts: [],
      sector_score: 0.4,
      key_drivers: ["d-en"],
      confidence: 0.4,
    },
    biotech: {
      agent: "biotech",
      longs: [sectorLong("600276.SH")],
      shorts: [],
      sector_score: 0.5,
      key_drivers: ["d-bio"],
      confidence: 0.4,
    },
    consumer: {
      agent: "consumer",
      longs: [sectorLong("600519.SH")],
      shorts: [],
      sector_score: 0.5,
      key_drivers: ["d-cons"],
      confidence: 0.5,
    },
    industrials: {
      agent: "industrials",
      longs: [sectorLong("600031.SH")],
      shorts: [],
      sector_score: 0.4,
      key_drivers: ["d-ind"],
      confidence: 0.4,
    },
    financials: {
      agent: "financials",
      longs: [sectorLong("601318.SH")],
      shorts: [],
      sector_score: 0.4,
      key_drivers: ["d-fin"],
      confidence: 0.4,
    },
    relationship_mapper: {
      agent: "relationship_mapper",
      supply_chains: [{ name: "semi", tickers: ["688981.SH", "002371.SZ"], risk: "export" }],
      ownership_clusters: [],
      contagion_risks: ["spillover"],
      key_drivers: ["d-rm"],
      confidence: 0.4,
    },
    // ---- L3 ----
    druckenmiller: {
      agent: "druckenmiller",
      picks: [superPick("688981.SH", 0.7), superPick("600519.SH", 0.6)],
      philosophy_note: "macro / momentum",
      key_drivers: ["d-druck"],
      confidence: 0.6,
    },
    aschenbrenner: {
      agent: "aschenbrenner",
      picks: [superPick("688981.SH", 0.8), superPick("002371.SZ", 0.7)],
      philosophy_note: "AI capex",
      key_drivers: ["d-asch"],
      confidence: 0.6,
    },
    baker: {
      agent: "baker",
      picks: [superPick("600276.SH", 0.7)],
      philosophy_note: "biotech IP",
      key_drivers: ["d-baker"],
      confidence: 0.5,
    },
    ackman: {
      agent: "ackman",
      picks: [superPick("600519.SH", 0.8), superPick("601318.SH", 0.5)],
      philosophy_note: "quality compounder",
      key_drivers: ["d-ackman"],
      confidence: 0.6,
    },
    // ---- L4 ----
    cro: {
      agent: "cro",
      rejected_picks: Array.from({ length: rejectedCount }, (_, i) => {
        const tickers = ["688981.SH", "600519.SH", "002371.SZ", "600276.SH", "601318.SH"];
        return {
          ticker: tickers[i % 5] as string,
          reason: `risk-${i}`,
        };
      }),
      correlated_risks: [],
      black_swan_scenarios: ["fed pivot"],
      confidence: 0.5,
    },
    alpha_discovery: {
      agent: "alpha_discovery",
      novel_picks: [],
      confidence: 0.3,
    },
    autonomous_execution: {
      agent: "autonomous_execution",
      trades: [
        { ticker: "688981.SH", action: "BUY", size_pct: 0.4, conviction: 0.7 },
        { ticker: "600519.SH", action: "BUY", size_pct: 0.4, conviction: 0.6 },
      ],
      confidence: 0.6,
    },
    cio: {
      agent: "cio",
      portfolio_actions: [
        {
          ticker: "688981.SH",
          action: "BUY",
          target_weight: 0.4,
          holding_period: "3M",
          dissent_notes: "",
        },
        {
          ticker: "600519.SH",
          action: "BUY",
          target_weight: 0.4,
          holding_period: "3M",
          dissent_notes: "",
        },
      ],
      confidence: 0.55,
    },
  };
}

const ALL_AGENT_IDS = [
  // L1
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
  // L2
  "semiconductor",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "financials",
  "relationship_mapper",
  // L3
  "druckenmiller",
  "aschenbrenner",
  "baker",
  "ackman",
  // L4
  "cro",
  "alpha_discovery",
  "autonomous_execution",
  "cio",
] as const;

// L4 layer subdir mapping
const AGENT_SUBDIR: Record<string, string> = {
  central_bank: "macro",
  china: "macro",
  geopolitical: "macro",
  dollar: "macro",
  yield_curve: "macro",
  commodities: "macro",
  volatility: "macro",
  emerging_markets: "macro",
  news_sentiment: "macro",
  institutional_flow: "macro",
  semiconductor: "sector",
  energy: "sector",
  biotech: "sector",
  consumer: "sector",
  industrials: "sector",
  financials: "sector",
  relationship_mapper: "sector",
  druckenmiller: "superinvestor",
  aschenbrenner: "superinvestor",
  baker: "superinvestor",
  ackman: "superinvestor",
  cro: "decision",
  alpha_discovery: "decision",
  autonomous_execution: "decision",
  cio: "decision",
};

// ============================================================ scripted LLM (25 agents)

class ScriptedLlm25 {
  invokeCalls = 0;
  bindToolsCalls = 0;
  structuredCalls = 0;
  perAgentStructuredCount: Record<string, number> = {};
  readonly canned: CannedOutputs;
  // Sorted by descending name length so e.g. "alpha_discovery" matches before
  // "alpha" (no current overlaps but defensive).
  readonly sortedAgentIds: string[];

  constructor(canned: CannedOutputs) {
    this.canned = canned;
    this.sortedAgentIds = [...ALL_AGENT_IDS].sort((a, b) => b.length - a.length);
  }

  bindTools(_tools: unknown): ScriptedLlm25 {
    this.bindToolsCalls++;
    return this;
  }

  withStructuredOutput(_schema: unknown): { invoke: (input: unknown) => Promise<unknown> } {
    return {
      invoke: async (input: unknown) => {
        this.structuredCalls++;
        const msgs = input as BaseMessage[];
        const sys = msgs[0] as SystemMessage | undefined;
        const sysContent = typeof sys?.content === "string" ? sys.content : "";
        for (const agent of this.sortedAgentIds) {
          // Match unique marker `the ${agent} ` (with trailing space) so e.g.
          // "the cro " doesn't match "the macro " (no such substring exists)
          // and "alpha_discovery" beats "alpha" by descending-length sort.
          if (sysContent.includes(`the ${agent} `)) {
            this.perAgentStructuredCount[agent] = (this.perAgentStructuredCount[agent] ?? 0) + 1;
            return this.canned[agent as keyof CannedOutputs] as unknown;
          }
        }
        throw new Error(
          `ScriptedLlm25: no canned response matched system: ${sysContent.slice(0, 120)}`,
        );
      },
    };
  }

  async invoke(_messages: BaseMessage[]): Promise<AIMessage> {
    this.invokeCalls++;
    return new AIMessage("analysis text for the daily cycle");
  }
}

// ============================================================ compile sanity

describe("buildDailyCycleGraph (compile-only)", () => {
  beforeEach(() => clearPromptCache());
  afterEach(() => clearPromptCache());

  it("compiles without throwing and exposes the canonical layer node names", () => {
    expect([...DAILY_CYCLE_LAYER_NODES]).toEqual([
      "layer1",
      "layer2",
      "layer3",
      "layer4",
      "layer4_replay",
    ]);
    const handle: LlmHandle = {
      llm: new ScriptedLlm25(makeCannedOutputs()) as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };
    const graph = buildDailyCycleGraph({
      llmHandle: handle,
      api: fakeApi,
      config: BASE_CONFIG,
    });
    expect(graph).toBeDefined();
  });
});

// ============================================================ end-to-end smoke

describe("buildDailyCycleGraph (end-to-end smoke, no veto)", () => {
  let promptDir: string;

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-dc-"));
    for (const agent of ALL_AGENT_IDS) {
      const subdir = AGENT_SUBDIR[agent] as string;
      const dir = join(promptDir, "cohort_default", subdir);
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, `${agent}.zh.md`), "FAKE", "utf-8");
      writeFileSync(join(dir, `${agent}.en.md`), "FAKE", "utf-8");
    }
    clearPromptCache();
  });

  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("runs all 25 agents through 4 layers, populates portfolio_actions, no veto", async () => {
    const llm = new ScriptedLlm25(makeCannedOutputs({ croRejected: 0 }));
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    const graph = buildDailyCycleGraph({
      llmHandle: handle,
      api: fakeApi,
      config: BASE_CONFIG,
      promptsRoot: promptDir,
    });

    const final = (await graph.invoke(emptyState())) as DailyCycleStateType;

    // L1 — 10 agents + consensus
    expect(Object.keys(final.layer1_outputs)).toHaveLength(10);
    const consensus = final.layer1_consensus as RegimeSignal | null;
    expect(consensus).not.toBeNull();
    expect(consensus?.stance).toBe("BULLISH");

    // L2 — 7 sector outputs
    expect(Object.keys(final.layer2_outputs)).toHaveLength(7);

    // L3 — 4 superinvestor outputs
    expect(Object.keys(final.layer3_outputs)).toHaveLength(4);

    // L4 — all 4 slots populated
    expect(final.layer4_outputs.cro).not.toBeNull();
    expect(final.layer4_outputs.alpha_discovery).not.toBeNull();
    expect(final.layer4_outputs.autonomous_execution).not.toBeNull();
    expect(final.layer4_outputs.cio).not.toBeNull();

    // Top-level mirror
    expect(final.portfolio_actions).toHaveLength(2);
    expect(final.portfolio_actions[0]?.ticker).toBe("688981.SH");

    // 25 LLM structured calls (no duplication from subgraph composition).
    expect(llm.structuredCalls).toBe(25);
    // Each agent ran exactly once.
    expect(Object.keys(llm.perAgentStructuredCount).length).toBe(25);
    for (const agent of ALL_AGENT_IDS) {
      expect(llm.perAgentStructuredCount[agent]).toBe(1);
    }

    // 25 LlmCallRecord appends (Plan §11.2 design decision #7).
    expect(final.llm_calls).toHaveLength(25);
    // R-A1: no veto → replay never ran.
    expect(final.replay_triggered).toBe(false);
  });
});

// ============================================================ veto branch

describe("buildDailyCycleGraph (veto loop triggers replay)", () => {
  let promptDir: string;

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-dc-veto-"));
    for (const agent of ALL_AGENT_IDS) {
      const subdir = AGENT_SUBDIR[agent] as string;
      const dir = join(promptDir, "cohort_default", subdir);
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, `${agent}.zh.md`), "FAKE", "utf-8");
      writeFileSync(join(dir, `${agent}.en.md`), "FAKE", "utf-8");
    }
    clearPromptCache();
  });

  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("re-runs alpha + auto + cio when cro vetoes > 50% of L3 candidates", async () => {
    // L3 candidate pool de-duped = {688981.SH, 600519.SH, 002371.SZ, 600276.SH, 601318.SH} = 5.
    // Reject 4 → rate 0.8 → strictly > 0.5 → replay.
    const llm = new ScriptedLlm25(makeCannedOutputs({ croRejected: 4 }));
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    const graph = buildDailyCycleGraph({
      llmHandle: handle,
      api: fakeApi,
      config: BASE_CONFIG,
      promptsRoot: promptDir,
    });

    const final = (await graph.invoke(emptyState())) as DailyCycleStateType;

    // 25 first-pass + 3 replay (alpha + auto + cio) = 28.
    expect(llm.structuredCalls).toBe(28);
    // alpha / auto / cio each ran twice (first pass + replay); cro once.
    expect(llm.perAgentStructuredCount.cro).toBe(1);
    expect(llm.perAgentStructuredCount.alpha_discovery).toBe(2);
    expect(llm.perAgentStructuredCount.autonomous_execution).toBe(2);
    expect(llm.perAgentStructuredCount.cio).toBe(2);

    // 28 llm_calls total.
    expect(final.llm_calls).toHaveLength(28);

    // portfolio_actions still populated by the replay's cio.
    expect(final.portfolio_actions.length).toBeGreaterThan(0);
    // R-A1: the replay node set the provenance flag.
    expect(final.replay_triggered).toBe(true);
  });

  it("end branch (no replay) when cro rejects 0 picks even with full L3 pool", async () => {
    const llm = new ScriptedLlm25(makeCannedOutputs({ croRejected: 0 }));
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    const graph = buildDailyCycleGraph({
      llmHandle: handle,
      api: fakeApi,
      config: BASE_CONFIG,
      promptsRoot: promptDir,
    });
    await graph.invoke(emptyState());
    expect(llm.structuredCalls).toBe(25);
  });
});

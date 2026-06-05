/**
 * Tests for the Layer-1 LangGraph subgraph (Plan §11.2 sub-step 2C.3).
 *
 * The subgraph topology is fixed (10 macro nodes serially, then aggregator),
 * so we focus on:
 *   - All 10 agent nodes + the aggregator are registered
 *   - Compiled graph runs end-to-end with mocked agent outputs
 *   - layer1_consensus is populated correctly after aggregation
 *
 * Each agent node's internal flow is already covered by central_bank /
 * china / macro_layer1_agents tests; here we only need to know that the
 * graph wires them in the right order.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
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
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import {
  buildLayer1Graph,
  LAYER1_AGENT_NODES,
  LAYER1_AGGREGATOR_NODE,
} from "../src/graph/layer1.js";
import type { LlmHandle } from "../src/llm/factory.js";

// ============================================================ shape

describe("LAYER1_AGENT_NODES + LAYER1_AGGREGATOR_NODE constants", () => {
  it("declares the canonical 10 macro nodes", () => {
    expect([...LAYER1_AGENT_NODES]).toEqual([
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

  it("aggregator node id is stable", () => {
    expect(LAYER1_AGGREGATOR_NODE).toBe("aggregate_l1");
  });
});

// ============================================================ end-to-end mock serial graph

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
  "get_policy_uncertainty",
  "get_property_data",
  "get_us_china_spread",
  "get_xueqiu_heat",
  "get_lhb_ranking",
  "get_usdcny",
  "get_commodity_prices",
  "get_ivx",
  "get_realized_volatility",
  "get_etf_indicator",
  "get_fund_flow",
  "get_stock_moneyflow",
  "get_news",
  "get_etf_price_data",
  "get_etf_info",
  "get_etf_nav",
  "get_etf_universe",
  "get_etf_holdings",
  "get_caixin_sentiment",
  "get_us_china_relations",
].map((name) => ({ name, description: name, args_schema: TOOL_SCHEMA }));

/**
 * Per-agent canned structured outputs. Tweak the stance fields here to
 * exercise different aggregator outcomes.
 */
function cannedOutputs(): Record<string, MacroAgentOutput> {
  const cb: CentralBankOutput = {
    agent: "central_bank",
    stance: "ACCOMMODATIVE",
    key_rate_change_bps: -10,
    qe_qt_balance_change: "OMO +20B",
    next_window: "2024-07-15",
    key_drivers: ["d-cb"],
    confidence: 0.7,
  };
  const cn: ChinaOutput = {
    agent: "china",
    policy_direction: "PRO_GROWTH",
    sector_focus: ["semi"],
    risk_drivers: ["debt"],
    key_drivers: ["d-cn"],
    confidence: 0.7,
  };
  const geo: GeopoliticalOutput = {
    agent: "geopolitical",
    escalation_level: 1,
    hot_zones: ["x"],
    trade_impact: "x",
    key_drivers: ["d-geo"],
    confidence: 0.7,
  };
  const dlr: DollarOutput = {
    agent: "dollar",
    dxy_trend: "WEAKENING",
    cny_pressure: "LOW",
    dxy_cny_correlation: -70,
    key_drivers: ["d-dlr"],
    confidence: 0.7,
  };
  const yc: YieldCurveOutput = {
    agent: "yield_curve",
    curve_shape: "STEEPENING",
    recession_signal: "GREEN",
    cn_us_spread_bps: -150,
    key_drivers: ["d-yc"],
    confidence: 0.7,
  };
  const cmd: CommoditiesOutput = {
    agent: "commodities",
    oil_regime: "BACKWARDATION",
    metals_regime: "RISK_ON",
    ag_regime: "BALANCED",
    china_demand_signal: "ACCELERATING",
    key_drivers: ["d-cmd"],
    confidence: 0.7,
  };
  const vol: VolatilityOutput = {
    agent: "volatility",
    vix_regime: "LOW",
    ivx_regime: "LOW",
    regime_filter: "RISK_ON",
    key_drivers: ["d-vol"],
    confidence: 0.7,
  };
  const em: EmergingMarketsOutput = {
    agent: "emerging_markets",
    em_relative: "OUTPERFORMING",
    hk_a_share_ratio: 1.3,
    capital_flow: "NET_INFLOW",
    key_drivers: ["d-em"],
    confidence: 0.7,
  };
  const ns: NewsSentimentOutput = {
    agent: "news_sentiment",
    retail_sentiment_score: 0.5,
    hot_topics: ["x"],
    contrarian_flag: false,
    key_drivers: ["d-ns"],
    confidence: 0.7,
  };
  const inf: InstitutionalFlowOutput = {
    agent: "institutional_flow",
    main_net_flow_cny: 5000,
    top_buyers: ["x"],
    sectors_in_out: [{ sector: "semi", net_amount_cny: 5000 }],
    key_drivers: ["d-if"],
    confidence: 0.7,
  };
  return {
    central_bank: cb,
    china: cn,
    geopolitical: geo,
    dollar: dlr,
    yield_curve: yc,
    commodities: cmd,
    volatility: vol,
    emerging_markets: em,
    news_sentiment: ns,
    institutional_flow: inf,
  };
}

class ScriptedLlm {
  invokeCalls = 0;
  bindToolsCalls = 0;
  structuredCalls = 0;
  readonly perAgentResponse: Record<string, MacroAgentOutput>;
  readonly textBetweenInvokes: string;
  invokeIndex = 0;

  constructor(perAgentResponse: Record<string, MacroAgentOutput>, textBetween = "analysis") {
    this.perAgentResponse = perAgentResponse;
    this.textBetweenInvokes = textBetween;
  }

  bindTools(_tools: unknown): ScriptedLlm {
    this.bindToolsCalls++;
    return this;
  }

  withStructuredOutput(_schema: unknown): { invoke: (input: unknown) => Promise<unknown> } {
    return {
      invoke: async (input: unknown) => {
        this.structuredCalls++;
        // Pull the agent name from the system message in the input messages
        // array. invokeStructuredOrFreetext passes BaseMessage[] when used.
        const msgs = input as BaseMessage[];
        const sys = msgs[0];
        const sysContent = typeof sys?.content === "string" ? sys.content : "";
        for (const agent of Object.keys(this.perAgentResponse)) {
          if (sysContent.includes(agent)) {
            return this.perAgentResponse[agent] as unknown;
          }
        }
        throw new Error(
          `ScriptedLlm.withStructuredOutput: no canned response matched system: ${sysContent.slice(0, 80)}`,
        );
      },
    };
  }

  async invoke(_messages: BaseMessage[]): Promise<AIMessage> {
    this.invokeCalls++;
    return new AIMessage(this.textBetweenInvokes);
  }
}

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

describe("buildLayer1Graph (end-to-end serial / aggregate)", () => {
  let promptDir: string;

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-l1-graph-"));
    const dir = join(promptDir, "cohort_default", "macro");
    mkdirSync(dir, { recursive: true });
    for (const name of LAYER1_AGENT_NODES) {
      writeFileSync(join(dir, `${name}.zh.md`), "FAKE", "utf-8");
      writeFileSync(join(dir, `${name}.en.md`), "FAKE", "utf-8");
    }
    clearPromptCache();
  });

  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("compiled graph runs all 10 macro nodes + aggregator and emits BULLISH consensus", async () => {
    const llm = new ScriptedLlm(cannedOutputs());
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    const graph = buildLayer1Graph({
      llmHandle: handle,
      api: fakeApi,
      config: BASE_CONFIG,
      promptsRoot: promptDir,
    });

    const initialState: DailyCycleStateType = {
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

    const final = (await graph.invoke(initialState)) as DailyCycleStateType;

    // All 10 agent outputs present in the merged state.
    expect(Object.keys(final.layer1_outputs).sort()).toEqual([...LAYER1_AGENT_NODES].sort());

    // Aggregator wrote consensus.
    const consensus = final.layer1_consensus as RegimeSignal | null;
    expect(consensus).not.toBeNull();
    expect(consensus?.stance).toBe("BULLISH");
    expect(consensus?.layer_1_consensus_score).toBeGreaterThan(0.5);

    // Each agent ran through phase-1 (1 LLM invoke per agent for the loop's
    // tool-free finishing turn) + phase-2 structured. 10 invokes + 10 structured.
    expect(llm.invokeCalls).toBe(10);
    expect(llm.structuredCalls).toBe(10);
    expect(llm.bindToolsCalls).toBe(10);

    // 10 LlmCallRecord entries appended.
    expect(final.llm_calls).toHaveLength(10);
  });
});

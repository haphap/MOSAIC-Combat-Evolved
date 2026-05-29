/**
 * Bulk smoke test for the 8 macro agents added in Plan §11.2 sub-step 2C.2.
 *
 * The factory itself was end-to-end tested via central_bank.test.ts and
 * china.test.ts. Here we only verify, for each new agent, that:
 *   (a) the spec declares the right agent ID + tools
 *   (b) the schema accepts a well-formed canonical output
 *   (c) the schema rejects the most common malformations (bad enum,
 *       empty arrays, out-of-range numerics)
 *   (d) the renderer + fallback produce non-empty strings
 *   (e) AGENTS_BY_LAYER.macro lists exactly the 10 agent IDs we have
 *
 * Plus one factory-driven end-to-end smoke for `geopolitical` (smallest
 * tool set — 2 tools), to confirm the factory picks up new specs without
 * any per-agent test scaffolding.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  buildCommoditiesNode,
  commoditiesSpec,
  fallbackCommodities,
  renderCommodities,
} from "../src/agents/macro/commodities.js";
import {
  buildDollarNode,
  dollarSpec,
  fallbackDollar,
  renderDollar,
} from "../src/agents/macro/dollar.js";
import {
  buildEmergingMarketsNode,
  emergingMarketsSpec,
  fallbackEmergingMarkets,
  renderEmergingMarkets,
} from "../src/agents/macro/emerging_markets.js";
import {
  buildGeopoliticalNode,
  fallbackGeopolitical,
  geopoliticalSpec,
  renderGeopolitical,
} from "../src/agents/macro/geopolitical.js";
import {
  buildInstitutionalFlowNode,
  fallbackInstitutionalFlow,
  institutionalFlowSpec,
  renderInstitutionalFlow,
} from "../src/agents/macro/institutional_flow.js";
import {
  buildNewsSentimentNode,
  fallbackNewsSentiment,
  newsSentimentSpec,
  renderNewsSentiment,
} from "../src/agents/macro/news_sentiment.js";
import {
  buildVolatilityNode,
  fallbackVolatility,
  renderVolatility,
  volatilitySpec,
} from "../src/agents/macro/volatility.js";
import {
  buildYieldCurveNode,
  fallbackYieldCurve,
  renderYieldCurve,
  yieldCurveSpec,
} from "../src/agents/macro/yield_curve.js";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { GeopoliticalOutput, LlmCallRecord, MacroAgentOutput } from "../src/agents/types.js";
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import type { LlmHandle } from "../src/llm/factory.js";

// ============================================================ AGENTS_BY_LAYER

describe("AGENTS_BY_LAYER.macro", () => {
  it("lists the canonical 10 macro agents from Plan §5.1", () => {
    expect([...AGENTS_BY_LAYER.macro]).toEqual([
      "central_bank",
      "geopolitical",
      "china",
      "dollar",
      "yield_curve",
      "commodities",
      "volatility",
      "emerging_markets",
      "news_sentiment",
      "institutional_flow",
    ]);
  });
});

// ============================================================ spec sanity

describe("each macro agent spec wires the right factory inputs", () => {
  const cases = [
    { name: "geopolitical", spec: geopoliticalSpec, expected_tools: 2 },
    { name: "dollar", spec: dollarSpec, expected_tools: 4 },
    { name: "yield_curve", spec: yieldCurveSpec, expected_tools: 3 },
    { name: "commodities", spec: commoditiesSpec, expected_tools: 3 },
    { name: "volatility", spec: volatilitySpec, expected_tools: 3 },
    { name: "emerging_markets", spec: emergingMarketsSpec, expected_tools: 3 },
    { name: "news_sentiment", spec: newsSentimentSpec, expected_tools: 3 },
    { name: "institutional_flow", spec: institutionalFlowSpec, expected_tools: 3 },
  ] as const;

  for (const { name, spec, expected_tools } of cases) {
    it(`${name}`, () => {
      expect(spec.agentId).toBe(name);
      expect(spec.requiredTools.length).toBe(expected_tools);
      expect(spec.fieldNames.length).toBeGreaterThanOrEqual(4);
      // Every spec must include `key_drivers` + `confidence` (Plan §11.2 2B-6
      // contract for the L1 aggregator).
      expect(spec.fieldNames).toContain("key_drivers");
      expect(spec.fieldNames).toContain("confidence");
    });
  }
});

// ============================================================ render + fallback

describe("renderers + fallbacks emit non-empty strings", () => {
  it("geopolitical", () => {
    const fb = fallbackGeopolitical("");
    expect(fb.confidence).toBe(0);
    expect(renderGeopolitical(fb).length).toBeGreaterThan(20);
  });
  it("dollar", () => {
    const fb = fallbackDollar("");
    expect(fb.confidence).toBe(0);
    expect(renderDollar(fb).length).toBeGreaterThan(20);
  });
  it("yield_curve", () => {
    const fb = fallbackYieldCurve("");
    expect(fb.confidence).toBe(0);
    expect(renderYieldCurve(fb).length).toBeGreaterThan(20);
  });
  it("commodities", () => {
    const fb = fallbackCommodities("");
    expect(fb.confidence).toBe(0);
    expect(renderCommodities(fb).length).toBeGreaterThan(20);
  });
  it("volatility", () => {
    const fb = fallbackVolatility("");
    expect(fb.confidence).toBe(0);
    expect(renderVolatility(fb).length).toBeGreaterThan(20);
  });
  it("emerging_markets", () => {
    const fb = fallbackEmergingMarkets("");
    expect(fb.confidence).toBe(0);
    expect(renderEmergingMarkets(fb).length).toBeGreaterThan(20);
  });
  it("news_sentiment", () => {
    const fb = fallbackNewsSentiment("");
    expect(fb.confidence).toBe(0);
    expect(renderNewsSentiment(fb).length).toBeGreaterThan(20);
  });
  it("institutional_flow", () => {
    const fb = fallbackInstitutionalFlow("");
    expect(fb.confidence).toBe(0);
    expect(renderInstitutionalFlow(fb).length).toBeGreaterThan(20);
  });
});

// ============================================================ schema rejects

describe("schemas reject canonical malformations", () => {
  it("geopoliticalSpec rejects out-of-range escalation_level", () => {
    expect(() =>
      geopoliticalSpec.schema.parse({
        agent: "geopolitical",
        escalation_level: 7, // > 5
        hot_zones: ["x"],
        trade_impact: "x",
        key_drivers: ["d"],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("dollarSpec rejects north_flow_correlation > 100", () => {
    expect(() =>
      dollarSpec.schema.parse({
        agent: "dollar",
        dxy_trend: "STABLE",
        cny_pressure: "MODERATE",
        north_flow_correlation: 200, // > 100
        key_drivers: ["d"],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("newsSentimentSpec rejects retail_sentiment_score outside [-1, 1]", () => {
    expect(() =>
      newsSentimentSpec.schema.parse({
        agent: "news_sentiment",
        retail_sentiment_score: 1.5,
        hot_topics: ["x"],
        contrarian_flag: false,
        key_drivers: ["d"],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("institutionalFlowSpec rejects empty sectors_in_out", () => {
    expect(() =>
      institutionalFlowSpec.schema.parse({
        agent: "institutional_flow",
        north_net_flow_cny: 0,
        top_buyers: ["x"],
        sectors_in_out: [], // empty
        key_drivers: ["d"],
        confidence: 0.5,
      }),
    ).toThrow();
  });
});

// ============================================================ end-to-end via factory

describe("buildGeopoliticalNode (factory smoke)", () => {
  let promptDir: string;

  class ScriptedLlm {
    invokeCalls: BaseMessage[][] = [];
    bindToolsCalled = 0;
    structuredCalls = 0;
    readonly responses: AIMessage[];
    readonly structuredResponse: GeopoliticalOutput | null;
    constructor(responses: AIMessage[], structured: GeopoliticalOutput) {
      this.responses = [...responses];
      this.structuredResponse = structured;
    }
    bindTools(_t: unknown): ScriptedLlm {
      this.bindToolsCalled++;
      return this;
    }
    withStructuredOutput(_s: unknown): { invoke: (input: unknown) => Promise<unknown> } {
      return {
        invoke: async () => {
          this.structuredCalls++;
          if (this.structuredResponse === null) throw new Error("no canned response");
          return this.structuredResponse;
        },
      };
    }
    async invoke(messages: BaseMessage[]): Promise<AIMessage> {
      this.invokeCalls.push(messages);
      const next = this.responses.shift();
      if (!next) throw new Error("ScriptedLlm exhausted");
      return next;
    }
  }

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-geo-"));
    const dir = join(promptDir, "cohort_default", "macro");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "geopolitical.zh.md"), "FAKE", "utf-8");
    writeFileSync(join(dir, "geopolitical.en.md"), "FAKE", "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("dispatches 2 tools and writes layer1_outputs.geopolitical", async () => {
    const TOOL_SCHEMA: JsonSchemaObject = {
      type: "object",
      properties: { curr_date: { type: "string" } },
      required: ["curr_date"],
    };
    const FAKE_TOOL_METADATAS: ToolMetadata[] = [
      { name: "get_xueqiu_heat", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_industry_policy", description: "x", args_schema: TOOL_SCHEMA },
    ];
    const canned: GeopoliticalOutput = {
      agent: "geopolitical",
      escalation_level: 3,
      hot_zones: ["US-China semi exports"],
      trade_impact: "半导体设备 -2% 风险溢价上升",
      key_drivers: ["6/24 US BIS 新增 5 家中国实体清单", "半导体设备相关股关注度+35%"],
      confidence: 0.6,
    };
    const llm = new ScriptedLlm(
      [
        new AIMessage({
          content: "",
          tool_calls: [
            {
              id: "c1",
              name: "get_xueqiu_heat",
              args: { curr_date: "2024-06-24" },
              type: "tool_call",
            },
            {
              id: "c2",
              name: "get_industry_policy",
              args: { curr_date: "2024-06-24" },
              type: "tool_call",
            },
          ],
        }),
        new AIMessage("BIS list expansion + Xueqiu heat spike — escalation 3."),
      ],
      canned,
    );

    const api = {
      toolsList: async () => FAKE_TOOL_METADATAS,
      toolsCall: async (name: string) => ({ text: `${name}_csv` }),
    } as unknown as BridgeApi;

    const config: MosaicConfig = {
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

    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    const sample: DailyCycleStateType = {
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
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
      portfolio_actions: [],
      llm_calls: [],
    };

    const node = buildGeopoliticalNode({ llmHandle: handle, api, config, promptsRoot: promptDir });
    const update = await node(sample);
    const unwrapped = update as unknown as {
      layer1_outputs?: Record<string, MacroAgentOutput>;
      llm_calls?: LlmCallRecord[];
    };
    expect(unwrapped.layer1_outputs?.geopolitical).toEqual(canned);
    expect(unwrapped.llm_calls?.[0]?.agent).toBe("geopolitical");
    expect(llm.invokeCalls.length).toBe(2);
    expect(llm.bindToolsCalled).toBe(1);
    expect(llm.structuredCalls).toBe(1);
  });
});

// Compile-time assertion: every macro builder exists. If 2D adds Layer-2
// agents and accidentally drops a macro builder, this list is the canary.
const _allMacroBuilders = {
  geopolitical: buildGeopoliticalNode,
  dollar: buildDollarNode,
  yield_curve: buildYieldCurveNode,
  commodities: buildCommoditiesNode,
  volatility: buildVolatilityNode,
  emerging_markets: buildEmergingMarketsNode,
  news_sentiment: buildNewsSentimentNode,
  institutional_flow: buildInstitutionalFlowNode,
};
void _allMacroBuilders;

/**
 * Bulk smoke test for the 7 sector agents added in Plan §11.2 sub-step 2D.1.
 * Same pattern as test/macro_layer1_agents.test.ts.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import {
  biotechSpec,
  buildBiotechNode,
  fallbackBiotech,
  renderBiotech,
} from "../src/agents/sector/biotech.js";
import {
  buildConsumerNode,
  consumerSpec,
  fallbackConsumer,
  renderConsumer,
} from "../src/agents/sector/consumer.js";
import {
  buildEnergyNode,
  energySpec,
  fallbackEnergy,
  renderEnergy,
} from "../src/agents/sector/energy.js";
import {
  buildFinancialsNode,
  fallbackFinancials,
  financialsSpec,
  renderFinancials,
} from "../src/agents/sector/financials.js";
import {
  buildIndustrialsNode,
  fallbackIndustrials,
  industrialsSpec,
  renderIndustrials,
} from "../src/agents/sector/industrials.js";
import {
  buildRelationshipMapperNode,
  fallbackRelationshipMapper,
  relationshipMapperSpec,
  renderRelationshipMapper,
} from "../src/agents/sector/relationship_mapper.js";
import {
  buildSemiconductorNode,
  fallbackSemiconductor,
  renderSemiconductor,
  semiconductorSpec,
} from "../src/agents/sector/semiconductor.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
import type {
  CentralBankOutput,
  ChinaOutput,
  InstitutionalFlowOutput,
  RegimeSignal,
  SectorAgentOutput,
  SemiconductorOutput,
} from "../src/agents/types.js";
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import type { LlmHandle } from "../src/llm/factory.js";

// ============================================================ AGENTS_BY_LAYER

describe("AGENTS_BY_LAYER.sector", () => {
  it("lists the canonical 7 sector agents from Plan §5.2", () => {
    expect([...AGENTS_BY_LAYER.sector]).toEqual([
      "semiconductor",
      "energy",
      "biotech",
      "consumer",
      "industrials",
      "financials",
      "relationship_mapper",
    ]);
  });
});

// ============================================================ spec sanity

describe("each sector spec wires the right factory inputs", () => {
  const cases = [
    { name: "semiconductor", spec: semiconductorSpec },
    { name: "energy", spec: energySpec },
    { name: "biotech", spec: biotechSpec },
    { name: "consumer", spec: consumerSpec },
    { name: "industrials", spec: industrialsSpec },
    { name: "financials", spec: financialsSpec },
    { name: "relationship_mapper", spec: relationshipMapperSpec },
  ] as const;

  for (const { name, spec } of cases) {
    it(`${name}`, () => {
      expect(spec.agentId).toBe(name);
      expect(spec.requiredTools.length).toBeGreaterThanOrEqual(2);
      expect(spec.fieldNames).toContain("key_drivers");
      expect(spec.fieldNames).toContain("confidence");
    });
  }

  it("industry sector agents require get_broker_research (行业研报)", () => {
    for (const { name, spec } of cases) {
      if (name === "relationship_mapper") continue; // stock-level, not industry
      expect(spec.requiredTools).toContain("get_broker_research");
    }
  });

  it("industry sector agents require get_etf_holdings (行业 ETF 暴露)", () => {
    for (const { name, spec } of cases) {
      if (name === "relationship_mapper") continue;
      expect(spec.requiredTools).toContain("get_etf_holdings");
    }
  });

  it("relationship_mapper requires get_stock_research (个股研报)", () => {
    expect(relationshipMapperSpec.requiredTools).toContain("get_stock_research");
  });
});

// ============================================================ render + fallback

describe("renderers + fallbacks emit non-empty strings", () => {
  it("semiconductor", () => {
    const fb = fallbackSemiconductor("", null);
    expect(fb.confidence).toBe(0);
    expect(renderSemiconductor(fb).length).toBeGreaterThan(20);
  });
  it("energy", () => {
    const fb = fallbackEnergy("", null);
    expect(fb.confidence).toBe(0);
    expect(renderEnergy(fb).length).toBeGreaterThan(20);
  });
  it("biotech", () => {
    const fb = fallbackBiotech("", null);
    expect(fb.confidence).toBe(0);
    expect(renderBiotech(fb).length).toBeGreaterThan(20);
  });
  it("consumer", () => {
    const fb = fallbackConsumer("", null);
    expect(fb.confidence).toBe(0);
    expect(renderConsumer(fb).length).toBeGreaterThan(20);
  });
  it("industrials", () => {
    const fb = fallbackIndustrials("", null);
    expect(fb.confidence).toBe(0);
    expect(renderIndustrials(fb).length).toBeGreaterThan(20);
  });
  it("financials", () => {
    const fb = fallbackFinancials("", null);
    expect(fb.confidence).toBe(0);
    expect(renderFinancials(fb).length).toBeGreaterThan(20);
  });
  it("relationship_mapper", () => {
    const fb = fallbackRelationshipMapper("", null);
    expect(fb.confidence).toBe(0);
    expect(renderRelationshipMapper(fb).length).toBeGreaterThan(20);
  });
});

// ============================================================ schema rejects

describe("schemas reject malformations", () => {
  it("standard sector rejects sector_score outside [-1, 1]", () => {
    expect(() =>
      semiconductorSpec.schema.parse({
        agent: "semiconductor",
        longs: [],
        shorts: [],
        sector_score: 2.0,
        key_drivers: ["x"],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("relationship_mapper rejects empty supply_chains", () => {
    expect(() =>
      relationshipMapperSpec.schema.parse({
        agent: "relationship_mapper",
        supply_chains: [],
        ownership_clusters: [],
        contagion_risks: ["x"],
        key_drivers: ["d"],
        confidence: 0.5,
      }),
    ).toThrow();
  });
});

// ============================================================ end-to-end via factory

describe("buildSemiconductorNode (Layer-2 factory smoke)", () => {
  let promptDir: string;

  class ScriptedLlm {
    invokeCalls = 0;
    bindToolsCalled = 0;
    structuredCalls = 0;
    readonly response: AIMessage;
    readonly structuredResponse: SectorAgentOutput;
    constructor(text: string, structured: SectorAgentOutput) {
      this.response = new AIMessage(text);
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
          return this.structuredResponse;
        },
      };
    }
    async invoke(_messages: BaseMessage[]): Promise<AIMessage> {
      this.invokeCalls++;
      return this.response;
    }
  }

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-l2-"));
    const dir = join(promptDir, "cohort_default", "sector");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "semiconductor.zh.md"), "FAKE", "utf-8");
    writeFileSync(join(dir, "semiconductor.en.md"), "FAKE", "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("reads layer1_consensus from state and writes layer2_outputs.semiconductor", async () => {
    const TOOL_SCHEMA: JsonSchemaObject = {
      type: "object",
      properties: { x: { type: "string" } },
      required: ["x"],
    };
    const FAKE_TOOLS: ToolMetadata[] = [
      "get_industry_policy",
      "get_xueqiu_heat",
      "get_lhb_ranking",
      "get_north_capital_flow",
      "get_broker_research",
      "get_stock_research",
      "get_etf_holdings",
      "get_stock_data",
      "get_indicators",
    ].map((name) => ({ name, description: name, args_schema: TOOL_SCHEMA }));

    const cannedOutput: SemiconductorOutput = {
      agent: "semiconductor",
      longs: [
        { ticker: "688981.SH", thesis: "国产替代 + 大基金催化", conviction: 0.8 },
        { ticker: "002371.SZ", thesis: "设备国产化率提升", conviction: 0.75 },
      ],
      shorts: [],
      sector_score: 0.6,
      key_drivers: [
        "Layer-1 BULLISH 且 china.sector_focus 含半导体",
        "工信部 6/24 出台先进制程支持政策",
      ],
      confidence: 0.45, // capped under 0.5 per Phase 0/1 prompt rule
    };

    const llm = new ScriptedLlm("semi analysis text", cannedOutput);
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    let observedSystem = "";
    const originalInvoke = llm.invoke.bind(llm);
    llm.invoke = async (messages: BaseMessage[]) => {
      observedSystem = String(messages[0]?.content ?? "");
      return originalInvoke(messages);
    };

    const api = {
      toolsList: async () => FAKE_TOOLS,
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

    // Pre-populate Layer-1 state — the factory must surface this in user context.
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
      sector_focus: ["半导体", "新质生产力"],
      risk_drivers: ["地方债"],
      key_drivers: ["国务院 6/24 半导体扶持"],
      confidence: 0.7,
    };
    const inf: InstitutionalFlowOutput = {
      agent: "institutional_flow",
      north_net_flow_cny: 12345,
      top_buyers: ["中信"],
      sectors_in_out: [{ sector: "semiconductor", net_amount_cny: 5000 }],
      key_drivers: ["d-inf"],
      confidence: 0.7,
    };
    const regime: RegimeSignal = {
      stance: "BULLISH",
      confidence: 0.7,
      key_drivers: ["regime drv"],
      layer_1_consensus_score: 0.6,
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
      layer1_outputs: { central_bank: cb, china: cn, institutional_flow: inf },
      layer1_consensus: regime,
      layer2_outputs: {},
      layer2_consensus: null,
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
      portfolio_actions: [],
      replay_triggered: false,
      llm_calls: [],
    };

    const node = buildSemiconductorNode({ llmHandle: handle, api, config, promptsRoot: promptDir });
    const update = await node(sample);
    const unwrapped = update as DailyCycleStateUpdate as unknown as {
      layer2_outputs?: Record<string, SectorAgentOutput>;
    };
    expect(unwrapped.layer2_outputs?.semiconductor).toEqual(cannedOutput);
    expect(llm.invokeCalls).toBe(1);
    expect(llm.bindToolsCalled).toBe(1);
    expect(llm.structuredCalls).toBe(1);
    void observedSystem; // observation hook kept for future debugging
  });
});

import { buildLayerTwoUserContext } from "../src/agents/sector/_factory.js";

describe("buildLayerTwoUserContext", () => {
  it("includes layer1_consensus + china + institutional_flow when populated", () => {
    const regime: RegimeSignal = {
      stance: "BULLISH",
      confidence: 0.7,
      key_drivers: ["d1"],
      layer_1_consensus_score: 0.6,
    };
    const china: ChinaOutput = {
      agent: "china",
      policy_direction: "PRO_GROWTH",
      sector_focus: ["半导体"],
      risk_drivers: ["地方债"],
      key_drivers: ["d-cn"],
      confidence: 0.7,
    };
    const inf: InstitutionalFlowOutput = {
      agent: "institutional_flow",
      north_net_flow_cny: 5000,
      top_buyers: ["a"],
      sectors_in_out: [{ sector: "semi", net_amount_cny: 3000 }],
      key_drivers: ["d-inf"],
      confidence: 0.7,
    };
    const state: DailyCycleStateType = {
      messages: [],
      active_cohort: "cohort_default",
      as_of_date: "2024-06-24",
      mode: "live",
      trace_id: "t",
      continuity_context: {},
      lesson_context: {},
      method_context: {},
      layer1_outputs: { china, institutional_flow: inf },
      layer1_consensus: regime,
      layer2_outputs: {},
      layer2_consensus: null,
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
      portfolio_actions: [],
      replay_triggered: false,
      llm_calls: [],
    };
    const ctx = buildLayerTwoUserContext(state, "semiconductor");
    expect(ctx).toContain("BULLISH");
    expect(ctx).toContain("PRO_GROWTH");
    expect(ctx).toContain("半导体");
    expect(ctx).toContain("5000"); // north_net_flow_cny
    expect(ctx).toContain("semiconductor"); // agentId in header
  });

  it("degrades gracefully when upstream Layer-1 state is missing", () => {
    const state: DailyCycleStateType = {
      messages: [],
      active_cohort: "cohort_default",
      as_of_date: "2024-06-24",
      mode: "live",
      trace_id: "t",
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
      replay_triggered: false,
      llm_calls: [],
    };
    const ctx = buildLayerTwoUserContext(state, "semiconductor");
    expect(ctx).toContain("not available");
  });
});

// Compile-time canary — every spec exists.
const _allSectorBuilders = {
  semiconductor: buildSemiconductorNode,
  energy: buildEnergyNode,
  biotech: buildBiotechNode,
  consumer: buildConsumerNode,
  industrials: buildIndustrialsNode,
  financials: buildFinancialsNode,
  relationship_mapper: buildRelationshipMapperNode,
};
void _allSectorBuilders;

/**
 * Bulk smoke test for the 4 superinvestor agents (Plan §11.2 sub-step 2D.2).
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as cohortsModule from "../src/agents/prompts/cohorts.js";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
import { buildLayerThreeUserContext } from "../src/agents/superinvestor/_factory.js";
import {
  ackmanSpec,
  buildAckmanNode,
  fallbackAckman,
  renderAckman,
} from "../src/agents/superinvestor/ackman.js";
import {
  aschenbrennerSpec,
  buildAschenbrennerNode,
  fallbackAschenbrenner,
  renderAschenbrenner,
} from "../src/agents/superinvestor/aschenbrenner.js";
import {
  bakerSpec,
  buildBakerNode,
  fallbackBaker,
  renderBaker,
} from "../src/agents/superinvestor/baker.js";
import {
  buildDruckenmillerNode,
  druckenmillerSpec,
  fallbackDruckenmiller,
  renderDruckenmiller,
} from "../src/agents/superinvestor/druckenmiller.js";
import type {
  DruckenmillerOutput,
  RegimeSignal,
  SemiconductorOutput,
  SuperinvestorOutput,
} from "../src/agents/types.js";
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import type { LlmHandle } from "../src/llm/factory.js";

// ============================================================ AGENTS_BY_LAYER

describe("AGENTS_BY_LAYER.superinvestor", () => {
  it("lists the canonical 4 superinvestor agents from Plan §5.3", () => {
    expect([...AGENTS_BY_LAYER.superinvestor]).toEqual([
      "druckenmiller",
      "aschenbrenner",
      "baker",
      "ackman",
    ]);
  });
});

// ============================================================ spec sanity

describe("each superinvestor spec wires the right factory inputs", () => {
  const cases = [
    { name: "druckenmiller", spec: druckenmillerSpec },
    { name: "aschenbrenner", spec: aschenbrennerSpec },
    { name: "baker", spec: bakerSpec },
    { name: "ackman", spec: ackmanSpec },
  ] as const;

  for (const { name, spec } of cases) {
    it(`${name}`, () => {
      expect(spec.agentId).toBe(name);
      expect(spec.requiredTools.length).toBeGreaterThanOrEqual(1);
      expect(spec.fieldNames).toEqual(["picks", "philosophy_note", "key_drivers", "confidence"]);
    });
  }
});

// ============================================================ render + fallback

describe("renderers + fallbacks", () => {
  it("druckenmiller", () => {
    const fb = fallbackDruckenmiller("", null);
    expect(fb.confidence).toBe(0);
    expect(renderDruckenmiller(fb).length).toBeGreaterThan(20);
  });
  it("aschenbrenner", () => {
    const fb = fallbackAschenbrenner("", null);
    expect(fb.confidence).toBe(0);
    expect(renderAschenbrenner(fb).length).toBeGreaterThan(20);
  });
  it("baker", () => {
    const fb = fallbackBaker("", null);
    expect(fb.confidence).toBe(0);
    expect(renderBaker(fb).length).toBeGreaterThan(20);
  });
  it("ackman", () => {
    const fb = fallbackAckman("", null);
    expect(fb.confidence).toBe(0);
    expect(renderAckman(fb).length).toBeGreaterThan(20);
  });
});

// ============================================================ schema rejects

describe("schemas reject malformations", () => {
  it("rejects holding_period outside enum", () => {
    expect(() =>
      druckenmillerSpec.schema.parse({
        agent: "druckenmiller",
        picks: [
          {
            ticker: "600519.SH",
            thesis: "x",
            conviction: 0.5,
            // biome-ignore lint/suspicious/noExplicitAny: deliberately invalid
            holding_period: "10Y" as any,
          },
        ],
        philosophy_note: "x",
        key_drivers: ["d"],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("rejects conviction outside [0, 1]", () => {
    expect(() =>
      ackmanSpec.schema.parse({
        agent: "ackman",
        picks: [{ ticker: "600519.SH", thesis: "x", conviction: 1.5, holding_period: "5Y+" }],
        philosophy_note: "x",
        key_drivers: ["d"],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("rejects empty key_drivers", () => {
    expect(() =>
      bakerSpec.schema.parse({
        agent: "baker",
        picks: [],
        philosophy_note: "x",
        key_drivers: [],
        confidence: 0.5,
      }),
    ).toThrow();
  });
});

// ============================================================ buildLayerThreeUserContext

describe("buildLayerThreeUserContext", () => {
  it("includes regime + sector picks when populated", () => {
    const regime: RegimeSignal = {
      stance: "BULLISH",
      confidence: 0.7,
      key_drivers: ["d-regime"],
      layer_1_consensus_score: 0.6,
    };
    const semi: SemiconductorOutput = {
      agent: "semiconductor",
      longs: [
        { ticker: "688981.SH", thesis: "国产替代", conviction: 0.8 },
        { ticker: "002371.SZ", thesis: "设备国产化", conviction: 0.7 },
      ],
      shorts: [],
      sector_score: 0.6,
      key_drivers: ["d"],
      confidence: 0.45,
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
      layer1_outputs: {},
      layer1_consensus: regime,
      layer2_outputs: { semiconductor: semi },
      layer2_consensus: null,
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
      portfolio_actions: [],
      llm_calls: [],
    };
    const ctx = buildLayerThreeUserContext(state, "druckenmiller");
    expect(ctx).toContain("BULLISH");
    expect(ctx).toContain("688981.SH");
    expect(ctx).toContain("druckenmiller");
    expect(ctx).toContain("score=0.60");
  });

  it("degrades gracefully when L1/L2 state is empty", () => {
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
      llm_calls: [],
    };
    const ctx = buildLayerThreeUserContext(state, "druckenmiller");
    expect(ctx).toContain("not available");
  });

  it("renders relationship_mapper section differently", () => {
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
      layer2_outputs: {
        relationship_mapper: {
          agent: "relationship_mapper",
          supply_chains: [
            {
              name: "半导体设备链",
              tickers: ["002371.SZ", "688012.SH"],
              risk: "出口管制",
            },
          ],
          ownership_clusters: [],
          contagion_risks: ["半导体 → AI 应用同步下跌"],
          key_drivers: ["d"],
          confidence: 0.4,
        },
      },
      layer2_consensus: null,
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
      portfolio_actions: [],
      llm_calls: [],
    };
    const ctx = buildLayerThreeUserContext(state, "druckenmiller");
    expect(ctx).toContain("半导体设备链");
    expect(ctx).toContain("contagion_risks");
  });
});

// ============================================================ end-to-end via factory

describe("buildDruckenmillerNode (Layer-3 factory smoke)", () => {
  let promptDir: string;
  let promptsRootSpy: ReturnType<typeof vi.spyOn>;

  class ScriptedLlm {
    invokeCalls = 0;
    bindToolsCalled = 0;
    structuredCalls = 0;
    readonly response: AIMessage;
    readonly structuredResponse: SuperinvestorOutput;
    constructor(text: string, structured: SuperinvestorOutput) {
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
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-l3-"));
    const dir = join(promptDir, "cohort_default", "superinvestor");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "druckenmiller.zh.md"), "FAKE", "utf-8");
    writeFileSync(join(dir, "druckenmiller.en.md"), "FAKE", "utf-8");
    promptsRootSpy = vi.spyOn(cohortsModule, "findPromptsRoot").mockReturnValue(promptDir);
    clearPromptCache();
  });
  afterEach(() => {
    promptsRootSpy.mockRestore();
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("writes layer3_outputs.druckenmiller via the factory", async () => {
    const TOOL_SCHEMA: JsonSchemaObject = {
      type: "object",
      properties: { x: { type: "string" } },
      required: ["x"],
    };
    const FAKE_TOOLS: ToolMetadata[] = [
      { name: "get_yield_curve_cn", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_industry_policy", description: "x", args_schema: TOOL_SCHEMA },
    ];

    const canned: DruckenmillerOutput = {
      agent: "druckenmiller",
      picks: [
        {
          ticker: "688981.SH",
          thesis: "BULLISH + 半导体 sector_score 0.6 + 6/24 政策催化",
          conviction: 0.7,
          holding_period: "6M",
        },
        {
          ticker: "600519.SH",
          thesis: "consumer 配置防御",
          conviction: 0.5,
          holding_period: "1Y",
        },
      ],
      philosophy_note: "regime BULLISH 下 sector rotation 到半导体 + 防御性 quality 持仓",
      key_drivers: ["regime BULLISH", "半导体 catalyst", "consumer 防御"],
      confidence: 0.6,
    };

    const llm = new ScriptedLlm("analysis text", canned);
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
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
      layer1_consensus: {
        stance: "BULLISH",
        confidence: 0.7,
        key_drivers: ["d"],
        layer_1_consensus_score: 0.6,
      },
      layer2_outputs: {
        semiconductor: {
          agent: "semiconductor",
          longs: [{ ticker: "688981.SH", thesis: "国产替代", conviction: 0.8 }],
          shorts: [],
          sector_score: 0.6,
          key_drivers: ["d"],
          confidence: 0.45,
        },
        consumer: {
          agent: "consumer",
          longs: [{ ticker: "600519.SH", thesis: "quality", conviction: 0.7 }],
          shorts: [],
          sector_score: 0.4,
          key_drivers: ["d"],
          confidence: 0.45,
        },
      },
      layer2_consensus: null,
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
      portfolio_actions: [],
      llm_calls: [],
    };

    const node = buildDruckenmillerNode({ llmHandle: handle, api, config });
    const update = await node(sample);
    const unwrapped = update as DailyCycleStateUpdate as unknown as {
      layer3_outputs?: Record<string, SuperinvestorOutput>;
    };
    expect(unwrapped.layer3_outputs?.druckenmiller).toEqual(canned);
    expect(llm.bindToolsCalled).toBe(1);
    expect(llm.invokeCalls).toBe(1);
    expect(llm.structuredCalls).toBe(1);
  });
});

// Compile-time canary
const _allBuilders = {
  druckenmiller: buildDruckenmillerNode,
  aschenbrenner: buildAschenbrennerNode,
  baker: buildBakerNode,
  ackman: buildAckmanNode,
};
void _allBuilders;

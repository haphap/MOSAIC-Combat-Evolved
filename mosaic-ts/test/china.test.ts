/**
 * china agent test (Plan §11.2 sub-step 2C.1).
 *
 * Lighter than central_bank's because the factory is shared — we only need
 * to assert the agent-specific spec (schema / fields / required tools /
 * fallback) and one end-to-end smoke through the factory.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  buildChinaNode,
  ChinaSchema,
  chinaSpec,
  fallbackChinaOutput,
  REQUIRED_TOOLS,
  renderChina,
} from "../src/agents/macro/china.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
import type { ChinaOutput, LlmCallRecord, MacroAgentOutput } from "../src/agents/types.js";
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import type { LlmHandle } from "../src/llm/factory.js";

// ============================================================ shared mocks

const TOOL_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: {
    curr_date: { type: "string", description: "yyyy-mm-dd" },
    look_back_days: { type: "integer", description: "days", default: 7 },
  },
  required: ["curr_date"],
};
const FLOW_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: {
    start_date: { type: "string", description: "start" },
    end_date: { type: "string", description: "end" },
  },
  required: ["start_date", "end_date"],
};

const FAKE_TOOL_METADATAS: ToolMetadata[] = [
  { name: "get_industry_policy", description: "policy news", args_schema: TOOL_SCHEMA },
  { name: "get_pboc_ops", description: "PBOC ops", args_schema: TOOL_SCHEMA },
  { name: "get_property_data", description: "real-estate climate", args_schema: TOOL_SCHEMA },
  { name: "get_north_capital_flow", description: "north flow", args_schema: FLOW_SCHEMA },
];

class ScriptedLlm {
  invokeCalls: BaseMessage[][] = [];
  bindToolsCalled = 0;
  structuredCalls = 0;
  readonly responses: AIMessage[];
  readonly structuredResponse: ChinaOutput | null;

  constructor(opts: { responses: AIMessage[]; structuredResponse?: ChinaOutput | null }) {
    this.responses = [...opts.responses];
    this.structuredResponse = opts.structuredResponse ?? null;
  }
  bindTools(_t: unknown): ScriptedLlm {
    this.bindToolsCalled++;
    return this;
  }
  withStructuredOutput(_s: unknown): { invoke: (input: unknown) => Promise<unknown> } {
    return {
      invoke: async (_input) => {
        this.structuredCalls++;
        if (this.structuredResponse === null) throw new Error("no structured response queued");
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

const handle = (llm: ScriptedLlm): LlmHandle => ({
  llm: llm as unknown as LlmHandle["llm"],
  provider: "fake",
  model: "fake-model",
  baseUrl: undefined,
});

const fakeApi = (canned: Record<string, string>): BridgeApi =>
  ({
    toolsList: async () => FAKE_TOOL_METADATAS,
    toolsCall: async (name: string) => {
      const text = canned[name];
      if (text === undefined) throw new Error(`no canned response for ${name}`);
      return { text };
    },
  }) as unknown as BridgeApi;

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

const SAMPLE_STATE: DailyCycleStateType = {
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
  replay_triggered: false,
  llm_calls: [],
};

function unwrap(update: DailyCycleStateUpdate): {
  layer1_outputs?: Record<string, MacroAgentOutput>;
  llm_calls?: LlmCallRecord[];
} {
  return update as unknown as {
    layer1_outputs?: Record<string, MacroAgentOutput>;
    llm_calls?: LlmCallRecord[];
  };
}

// ============================================================ spec sanity

describe("chinaSpec", () => {
  it("declares the right agent ID + tools per Plan §5.1 (with §14 #8 get_property_data)", () => {
    expect(chinaSpec.agentId).toBe("china");
    expect([...REQUIRED_TOOLS]).toEqual([
      "get_industry_policy",
      "get_pboc_ops",
      "get_property_data",
      "get_north_capital_flow",
    ]);
    expect(chinaSpec.fieldNames).toContain("policy_direction");
    expect(chinaSpec.fieldNames).toContain("sector_focus");
    expect(chinaSpec.fieldNames).toContain("risk_drivers");
  });
});

describe("ChinaSchema", () => {
  it("accepts a well-formed china output", () => {
    expect(() =>
      ChinaSchema.parse({
        agent: "china",
        policy_direction: "PRO_GROWTH",
        sector_focus: ["半导体", "新质生产力"],
        risk_drivers: ["地方债"],
        key_drivers: ["国务院 6/24 发布产业政策"],
        confidence: 0.7,
      }),
    ).not.toThrow();
  });

  it("rejects empty sector_focus / risk_drivers / key_drivers", () => {
    const base = {
      agent: "china" as const,
      policy_direction: "BALANCED" as const,
      sector_focus: ["x"],
      risk_drivers: ["y"],
      key_drivers: ["z"],
      confidence: 0.5,
    };
    expect(() => ChinaSchema.parse({ ...base, sector_focus: [] })).toThrow();
    expect(() => ChinaSchema.parse({ ...base, risk_drivers: [] })).toThrow();
    expect(() => ChinaSchema.parse({ ...base, key_drivers: [] })).toThrow();
  });

  it("rejects an unknown policy_direction", () => {
    expect(() =>
      ChinaSchema.parse({
        agent: "china",
        // biome-ignore lint/suspicious/noExplicitAny: deliberately invalid
        policy_direction: "OFFENSIVE" as any,
        sector_focus: ["x"],
        risk_drivers: ["y"],
        key_drivers: ["z"],
        confidence: 0.5,
      }),
    ).toThrow();
  });
});

describe("renderChina + fallbackChinaOutput", () => {
  it("renders a populated output", () => {
    const out: ChinaOutput = {
      agent: "china",
      policy_direction: "PRO_GROWTH",
      sector_focus: ["半导体"],
      risk_drivers: ["地方债"],
      key_drivers: ["d1"],
      confidence: 0.65,
    };
    const text = renderChina(out);
    expect(text).toContain("PRO_GROWTH");
    expect(text).toContain("半导体");
    expect(text).toContain("0.65");
  });

  it("fallback emits confidence=0 BALANCED stance", () => {
    const out = fallbackChinaOutput("");
    expect(out.confidence).toBe(0);
    expect(out.policy_direction).toBe("BALANCED");
    expect(out.sector_focus.length).toBeGreaterThan(0);
  });
});

// ============================================================ end-to-end

describe("buildChinaNode (vertical slice via factory)", () => {
  let promptDir: string;

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-china-"));
    const dir = join(promptDir, "cohort_default", "macro");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "china.zh.md"), "FAKE PROMPT ZH", "utf-8");
    writeFileSync(join(dir, "china.en.md"), "FAKE PROMPT EN", "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("end-to-end: 3 tools dispatched, structured output written to layer1_outputs.china", async () => {
    const canned: ChinaOutput = {
      agent: "china",
      policy_direction: "PRO_GROWTH",
      sector_focus: ["半导体", "新质生产力"],
      risk_drivers: ["地方债", "房地产融资"],
      key_drivers: [
        "国务院 6/24 发布科技产业扶持意见",
        "北向资金 6/20-6/24 净流入 152 亿",
        "OMO 净投放 200 亿配合产业政策",
      ],
      confidence: 0.74,
    };
    const llm = new ScriptedLlm({
      responses: [
        new AIMessage({
          content: "",
          tool_calls: [
            {
              id: "c1",
              name: "get_industry_policy",
              args: { curr_date: "2024-06-24" },
              type: "tool_call",
            },
            {
              id: "c2",
              name: "get_pboc_ops",
              args: { curr_date: "2024-06-24" },
              type: "tool_call",
            },
            {
              id: "c3",
              name: "get_north_capital_flow",
              args: { start_date: "2024-06-17", end_date: "2024-06-24" },
              type: "tool_call",
            },
          ],
        }),
        new AIMessage(
          "国务院 6/24 发布产业政策，北向资金净流入 152 亿，OMO 净投放 200 亿。" +
            "判断为偏积极的 PRO_GROWTH。",
        ),
      ],
      structuredResponse: canned,
    });

    const api = fakeApi({
      get_industry_policy: "datetime,title\n20240624,国务院发布科技产业扶持意见",
      get_pboc_ops: "trade_date,op_type,volume\n20240624,Reverse Repo,200",
      get_property_data: "日期,最新值\n2024-06-01,92.1",
      get_north_capital_flow: "trade_date,north_money\n20240620,42.5\n20240624,30.1",
    });

    const node = buildChinaNode({
      llmHandle: handle(llm),
      api,
      config: BASE_CONFIG,
      promptsRoot: promptDir,
    });
    const update = await node(SAMPLE_STATE);

    const out = unwrap(update).layer1_outputs?.china as ChinaOutput;
    expect(out).toEqual(canned);
    expect(unwrap(update).llm_calls?.[0]?.agent).toBe("china");
    // Two LLM invocations in tool loop + 1 structured = 3 (factory handles the third).
    expect(llm.invokeCalls.length).toBe(2);
    expect(llm.bindToolsCalled).toBe(1);
    expect(llm.structuredCalls).toBe(1);
  });
});

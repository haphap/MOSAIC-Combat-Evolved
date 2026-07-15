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
import type { MacroAgentOutput, RegimeSignal } from "../src/agents/types.js";
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import { fakeAgentStructuredOutput, fakeSchemaValue } from "../src/cli/fake_agent_output.js";
import {
  buildLayer1Graph,
  LAYER1_AGENT_NODES,
  LAYER1_AGGREGATOR_NODE,
} from "../src/graph/layer1.js";
import type { LlmHandle } from "../src/llm/factory.js";
import { macroOutput } from "./helpers/macro.js";

// ============================================================ shape

describe("LAYER1_AGENT_NODES + LAYER1_AGGREGATOR_NODE constants", () => {
  it("declares the canonical 10 macro nodes", () => {
    expect([...LAYER1_AGENT_NODES]).toEqual([
      "china",
      "us_economy",
      "central_bank",
      "dollar",
      "yield_curve",
      "commodities",
      "geopolitical",
      "volatility",
      "market_breadth",
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
  "get_china_macro_snapshot",
  "get_us_macro_snapshot",
  "get_central_bank_snapshot",
  "get_fx_conditions_snapshot",
  "get_rates_credit_snapshot",
  "get_commodity_conditions_snapshot",
  "get_geopolitical_events_snapshot",
  "get_volatility_snapshot",
  "get_market_breadth_snapshot",
  "get_market_positioning_snapshot",
].map((name) => ({ name, description: name, args_schema: TOOL_SCHEMA }));

/**
 * Per-agent canned structured outputs. Tweak the stance fields here to
 * exercise different aggregator outcomes.
 */
function cannedOutputs(): Record<string, MacroAgentOutput> {
  return Object.fromEntries(
    LAYER1_AGENT_NODES.map((agent) => [
      agent,
      macroOutput(agent, { direction: "SUPPORTIVE", strength: 5 }),
    ]),
  ) as Record<string, MacroAgentOutput>;
}

class ScriptedLlm {
  invokeCalls = 0;
  bindToolsCalls = 0;
  structuredCalls = 0;
  readonly perAgentResponse: Record<string, MacroAgentOutput>;
  readonly textBetweenInvokes: string;
  invokeIndex = 0;
  private tools: Array<{ name: string; schema?: unknown }> = [];

  constructor(perAgentResponse: Record<string, MacroAgentOutput>, textBetween = "analysis") {
    this.perAgentResponse = perAgentResponse;
    this.textBetweenInvokes = textBetween;
  }

  bindTools(tools: unknown): ScriptedLlm {
    this.bindToolsCalls++;
    this.tools = Array.isArray(tools) ? tools : [];
    return this;
  }

  withStructuredOutput(schema: unknown): { invoke: (input: unknown) => Promise<unknown> } {
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
            return fakeAgentStructuredOutput(schema, agent, input);
          }
        }
        throw new Error(
          `ScriptedLlm.withStructuredOutput: no canned response matched system: ${sysContent.slice(0, 80)}`,
        );
      },
    };
  }

  async invoke(messages: BaseMessage[]): Promise<AIMessage> {
    this.invokeCalls++;
    if (this.tools.length > 0 && !messages.some((message) => message._getType() === "tool")) {
      return new AIMessage({
        content: "",
        tool_calls: this.tools.map((tool, index) => ({
          id: `fake-tool-${index}`,
          name: tool.name,
          args: fakeSchemaValue(tool.schema),
        })),
      });
    }
    return new AIMessage(this.textBetweenInvokes);
  }
}

const fakeApi: BridgeApi = {
  toolsList: async () => FAKE_TOOLS,
  toolsCall: async (name: string) => ({ text: fakeSnapshot(name, "2024-06-24") }),
} as unknown as BridgeApi;

function fakeSnapshot(name: string, asOfDate: string): string {
  const agent = LAYER1_AGENT_NODES.find((candidate) => MACRO_TOOL_BY_AGENT[candidate] === name);
  return JSON.stringify({
    schema_version:
      agent === "market_breadth" ? "market_breadth_snapshot_v1" : "macro_role_snapshot_v1",
    ...(agent !== "market_breadth" ? { role: agent } : {}),
    as_of_date: asOfDate,
  });
}

const MACRO_TOOL_BY_AGENT: Record<(typeof LAYER1_AGENT_NODES)[number], string> = {
  china: "get_china_macro_snapshot",
  us_economy: "get_us_macro_snapshot",
  central_bank: "get_central_bank_snapshot",
  dollar: "get_fx_conditions_snapshot",
  yield_curve: "get_rates_credit_snapshot",
  commodities: "get_commodity_conditions_snapshot",
  geopolitical: "get_geopolitical_events_snapshot",
  volatility: "get_volatility_snapshot",
  market_breadth: "get_market_breadth_snapshot",
  institutional_flow: "get_market_positioning_snapshot",
};

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

  it("compiled graph runs all 10 macro nodes + aggregator with strict outputs", async () => {
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
      current_positions: {
        snapshot_status: "empty_confirmed",
        position_source: "empty_confirmed",
        source_error_code: null,
        position_snapshot_hash: "sha256:empty_positions",
        positions: [],
      },
      position_reviews: [],
      position_audit: {
        position_snapshot_hash: "sha256:empty_positions",
        snapshot_status: "empty_confirmed",
        position_source: "empty_confirmed",
        source_error_code: null,
        positions_loaded: 0,
        positions_reviewed: 0,
        positions_unreviewed: 0,
        hold_count: 0,
        add_count: 0,
        reduce_count: 0,
        exit_count: 0,
        stale_thesis_count: 0,
        stop_loss_override_count: 0,
        target_current_drift_count: 0,
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
    expect(consensus?.stance).toBe("NEUTRAL");
    expect(consensus?.layer_1_consensus_score).toBe(0);

    // Each agent receives its deterministic role snapshot before one analysis turn.
    expect(llm.invokeCalls).toBe(10);
    expect(llm.structuredCalls).toBe(10);
    expect(llm.bindToolsCalls).toBe(0);

    // 10 LlmCallRecord entries appended.
    expect(final.llm_calls).toHaveLength(10);
  });
});

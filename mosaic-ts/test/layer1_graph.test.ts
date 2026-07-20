import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MACRO_AGENT_IDS, MACRO_ROLE_CONTRACTS } from "../src/agents/macro/_contracts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import { emptyCurrentPositions, emptyLayer4, emptyPositionAudit } from "../src/agents/state.js";
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import { fakeAgentStructuredOutput } from "../src/cli/fake_agent_output.js";
import {
  buildLayer1Graph,
  LAYER1_AGENT_NODES,
  LAYER1_INPUT_GATE_NODE,
} from "../src/graph/layer1.js";
import type { LlmHandle } from "../src/llm/factory.js";

describe("Layer-1 v2 topology", () => {
  it("contains ten target agents and a non-semantic gate", () => {
    expect(LAYER1_AGENT_NODES).toEqual(MACRO_AGENT_IDS);
    expect(LAYER1_INPUT_GATE_NODE).toBe("macro_input_gate_node");
    expect(LAYER1_AGENT_NODES).not.toEqual(
      expect.arrayContaining([
        "us_financial_conditions",
        "euro_area_financial_conditions",
        "macro_input_gate_node",
      ]),
    );
  });
});

const TOOL_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: { as_of_date: { type: "string" } },
  required: ["as_of_date"],
};
const FAKE_TOOLS: ToolMetadata[] = MACRO_AGENT_IDS.map((agent) => ({
  name: MACRO_ROLE_CONTRACTS[agent].requiredTools[0],
  description: agent,
  args_schema: TOOL_SCHEMA,
}));

class ScriptedLlm {
  structuredCalls = 0;
  async invoke(): Promise<AIMessage> {
    return new AIMessage("analysis text");
  }
  withStructuredOutput(
    schema: unknown,
    options?: { name?: string },
  ): { invoke: (input: unknown) => Promise<unknown> } {
    return {
      invoke: async (input) => {
        this.structuredCalls++;
        const agent = MACRO_AGENT_IDS.find(
          (candidate) => options?.name === `${candidate}_agent_run`,
        );
        if (!agent) throw new Error("macro agent missing from structured prompt");
        return fakeAgentStructuredOutput(schema, agent, input);
      },
    };
  }
}

const fakeApi: BridgeApi = {
  toolsList: async () => FAKE_TOOLS,
  toolsCall: async () => ({ text: "unused by fake provider" }),
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

describe("buildLayer1Graph", () => {
  let promptDir: string;
  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-l1-v2-"));
    const dir = join(promptDir, "cohort_default", "macro");
    mkdirSync(dir, { recursive: true });
    for (const agent of MACRO_AGENT_IDS) {
      writeFileSync(join(dir, `${agent}.zh.md`), "FAKE", "utf8");
      writeFileSync(join(dir, `${agent}.en.md`), "FAKE", "utf8");
    }
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("runs all ten agents, composes accepted outputs, and closes the gate", async () => {
    const llm = new ScriptedLlm();
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };
    const initial: DailyCycleStateType = {
      messages: [],
      active_cohort: "cohort_default",
      as_of_date: "2026-07-17",
      mode: "live",
      trace_id: "macro-v2-smoke",
      darwinian_runtime_binding: null,
      darwinian_weight_snapshot: null,
      component_weight_snapshot: null,
      component_calibration_inputs: {},
      outcome_schedule_plan: null,
      outcome_stage_skips: {},
      outcome_opportunity_bindings: {},
      accepted_output_refs: {},
      continuity_context: {},
      lesson_context: {},
      method_context: {},
      layer1_outputs: {},
      macro_input_gate: null,
      layer2_outputs: {},
      layer3_outputs: {},
      layer4_outputs: emptyLayer4(),
      current_positions: emptyCurrentPositions(),
      position_reviews: [],
      position_audit: emptyPositionAudit(),
      portfolio_actions: [],
      replay_triggered: false,
      llm_calls: [],
    };
    const graph = buildLayer1Graph({
      llmHandle: handle,
      api: fakeApi,
      config,
      promptsRoot: promptDir,
    });
    const final = (await graph.invoke(initial)) as DailyCycleStateType;
    expect(Object.keys(final.layer1_outputs).sort()).toEqual([...MACRO_AGENT_IDS].sort());
    expect(final.macro_input_gate).toMatchObject({ accepted_count: 10 });
    expect(final.macro_input_gate?.input_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(
      Object.values(final.layer1_outputs).every((output) => output.direction === "NEUTRAL"),
    ).toBe(true);
    expect(llm.structuredCalls).toBe(10);
    expect(final.llm_calls).toHaveLength(10);
  });
});

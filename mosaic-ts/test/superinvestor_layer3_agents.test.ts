/**
 * Bulk smoke test for the 4 superinvestor agents (Plan §11.2 sub-step 2D.2).
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
import {
  buildLayerThreeInitialToolCalls,
  buildLayerThreeUserContext,
} from "../src/agents/superinvestor/_factory.js";
import {
  ackmanSpec,
  buildAckmanNode,
  fallbackAckman,
  renderAckman,
} from "../src/agents/superinvestor/ackman.js";
import {
  buildBurryNode,
  burrySpec,
  fallbackBurry,
  renderBurry,
} from "../src/agents/superinvestor/burry.js";
import {
  buildDruckenmillerNode,
  druckenmillerSpec,
  fallbackDruckenmiller,
  renderDruckenmiller,
} from "../src/agents/superinvestor/druckenmiller.js";
import {
  buildMungerNode,
  fallbackMunger,
  mungerSpec,
  renderMunger,
} from "../src/agents/superinvestor/munger.js";
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
      "munger",
      "burry",
      "ackman",
    ]);
  });
});

// ============================================================ spec sanity

describe("each superinvestor spec wires the right factory inputs", () => {
  const cases = [
    { name: "druckenmiller", spec: druckenmillerSpec },
    { name: "munger", spec: mungerSpec },
    { name: "burry", spec: burrySpec },
    { name: "ackman", spec: ackmanSpec },
  ] as const;

  for (const { name, spec } of cases) {
    it(`${name}`, () => {
      expect(spec.agentId).toBe(name);
      expect(spec.requiredTools.length).toBeGreaterThanOrEqual(1);
      expect(spec.fieldNames).toEqual([
        "picks",
        "philosophy_note",
        "key_drivers",
        "confidence",
        "claims",
        "claim_refs",
      ]);
    });
  }

  it("every superinvestor requires get_stock_research (个股研报)", () => {
    for (const { spec } of cases) {
      expect(spec.requiredTools).toContain("get_stock_research");
    }
  });

  it("every superinvestor requires get_fundamentals (财报快照)", () => {
    for (const { spec } of cases) {
      expect(spec.requiredTools).toContain("get_fundamentals");
    }
  });
});

// ============================================================ render + fallback

describe("renderers + fallbacks", () => {
  it("druckenmiller", () => {
    const fb = fallbackDruckenmiller("", null);
    expect(fb.confidence).toBe(0);
    expect(renderDruckenmiller(fb).length).toBeGreaterThan(20);
  });
  it("munger", () => {
    const fb = fallbackMunger("", null);
    expect(fb.confidence).toBe(0);
    expect(renderMunger(fb).length).toBeGreaterThan(20);
  });
  it("burry", () => {
    const fb = fallbackBurry("", null);
    expect(fb.confidence).toBe(0);
    expect(renderBurry(fb).length).toBeGreaterThan(20);
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
      burrySpec.schema.parse({
        agent: "burry",
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
    const ctx = buildLayerThreeUserContext(state, "druckenmiller");
    expect(ctx).toContain("BULLISH");
    expect(ctx).toContain("688981.SH");
    expect(ctx).toContain("druckenmiller");
    expect(ctx).toContain("score=0.60");
    expect(ctx).toContain("pick at least 2 candidate tickers");
    expect(ctx).toContain("confirmed by current stock research");
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
    const ctx = buildLayerThreeUserContext(state, "druckenmiller");
    expect(ctx).toContain("半导体设备链");
    expect(ctx).toContain("contagion_risks");
  });

  it("plans Ackman tools around quality-compounder duties", () => {
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
        consumer: {
          agent: "consumer",
          longs: [
            { ticker: "600519.SH", thesis: "pricing power", conviction: 0.8 },
            { ticker: "000858.SZ", thesis: "brand compounder", conviction: 0.7 },
          ],
          shorts: [],
          sector_score: 0.4,
          key_drivers: ["d"],
          confidence: 0.7,
        },
        financials: {
          agent: "financials",
          longs: [{ ticker: "600036.SH", thesis: "quality bank", conviction: 0.6 }],
          shorts: [],
          sector_score: 0.2,
          key_drivers: ["d"],
          confidence: 0.6,
        },
      },
      layer2_consensus: null,
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
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

    const ctx = buildLayerThreeUserContext(state, "ackman");
    expect(ctx).toContain("pricing power, FCF conversion");
    expect(ctx).toContain("same candidate or one backup");
    expect(ctx).toContain("initial quality candidate and one backup");
    expect(buildLayerThreeInitialToolCalls(state, "ackman")).toEqual([
      { name: "get_fundamentals", args: { ticker: "600519.SH", curr_date: "2024-06-24" } },
      {
        name: "get_cashflow",
        args: { ticker: "600519.SH", freq: "annual", curr_date: "2024-06-24" },
      },
    ]);
  });

  it("plans Burry tools around downside-first duties", () => {
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
        semiconductor: {
          agent: "semiconductor",
          longs: [{ ticker: "688981.SH", thesis: "cycle bottom", conviction: 0.5 }],
          shorts: [{ ticker: "300750.SZ", thesis: "crowded", conviction: 0.6 }],
          sector_score: 0.4,
          key_drivers: ["d"],
          confidence: 0.7,
        },
      },
      layer2_consensus: null,
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
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

    const ctx = buildLayerThreeUserContext(state, "burry");
    expect(ctx).toContain("balance-sheet stress, cash burn");
    expect(ctx).toContain("initial downside candidate and one backup");
    expect(buildLayerThreeInitialToolCalls(state, "burry")).toEqual([
      { name: "get_fundamentals", args: { ticker: "300750.SZ", curr_date: "2024-06-24" } },
      {
        name: "get_balance_sheet",
        args: { ticker: "300750.SZ", freq: "annual", curr_date: "2024-06-24" },
      },
    ]);
  });

  it("plans Munger tools around compounding-quality duties", () => {
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
        consumer: {
          agent: "consumer",
          longs: [{ ticker: "600519.SH", thesis: "pricing power", conviction: 0.8 }],
          shorts: [],
          sector_score: 0.4,
          key_drivers: ["d"],
          confidence: 0.7,
        },
      },
      layer2_consensus: null,
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
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

    expect(buildLayerThreeInitialToolCalls(state, "munger")).toEqual([
      { name: "get_fundamentals", args: { ticker: "600519.SH", curr_date: "2024-06-24" } },
      {
        name: "get_cashflow",
        args: { ticker: "600519.SH", freq: "annual", curr_date: "2024-06-24" },
      },
    ]);
    const ctx = buildLayerThreeUserContext(state, "munger");
    expect(ctx).toContain("moat durability, cash conversion");
    expect(ctx).toContain("same candidate or one backup");
  });
});

// ============================================================ end-to-end via factory

describe("buildDruckenmillerNode (Layer-3 factory smoke)", () => {
  let promptDir: string;

  class ScriptedLlm {
    invokeCalls = 0;
    bindToolsCalled = 0;
    structuredCalls = 0;
    lastMessages: BaseMessage[] | undefined;
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
      this.lastMessages = _messages;
      return this.response;
    }
  }

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-l3-"));
    const dir = join(promptDir, "cohort_default", "superinvestor");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "druckenmiller.zh.md"), "FAKE old tool get_xueqiu_heat", "utf-8");
    writeFileSync(join(dir, "druckenmiller.en.md"), "FAKE old tool get_xueqiu_heat", "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
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
      { name: "get_rke_research_context", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_yield_curve_cn", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_industry_policy", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_stock_research", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_fundamentals", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_balance_sheet", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_income_statement", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_cashflow", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_stock_data", description: "x", args_schema: TOOL_SCHEMA },
      { name: "get_indicators", description: "x", args_schema: TOOL_SCHEMA },
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

    const node = buildDruckenmillerNode({ llmHandle: handle, api, config, promptsRoot: promptDir });
    const update = await node(sample);
    const unwrapped = update as DailyCycleStateUpdate as unknown as {
      layer3_outputs?: Record<string, SuperinvestorOutput>;
    };
    expect(unwrapped.layer3_outputs?.druckenmiller).toEqual(canned);
    expect(llm.bindToolsCalled).toBe(1);
    expect(llm.invokeCalls).toBe(1);
    expect(llm.structuredCalls).toBe(1);
    const system = String(llm.lastMessages?.[0]?.content ?? "");
    expect(system).toContain("Only call these registered tools");
    expect(system).toContain("get_stock_research");
  });
});

// Compile-time canary
const _allBuilders = {
  druckenmiller: buildDruckenmillerNode,
  munger: buildMungerNode,
  burry: buildBurryNode,
  ackman: buildAckmanNode,
};
void _allBuilders;

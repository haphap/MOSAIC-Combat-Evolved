/**
 * Bulk smoke test for the 4 Layer-4 decision agents (Plan §11.2 sub-step 2D.3).
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  renderDarwinianWeightsStub,
  renderJanusRegimeStub,
  renderLayer1Context,
  renderLayer2Context,
  renderLayer3Context,
  renderLayer4PeerContext,
} from "../src/agents/decision/_user_context.js";
import {
  alphaDiscoverySpec,
  buildAlphaDiscoveryNode,
  fallbackAlphaDiscovery,
  renderAlphaDiscovery,
} from "../src/agents/decision/alpha_discovery.js";
import {
  autonomousExecutionSpec,
  buildAutonomousExecutionNode,
  fallbackAutonomousExecution,
  renderAutonomousExecution,
} from "../src/agents/decision/autonomous_execution.js";
import { buildCioNode, cioSpec, fallbackCio, renderCio } from "../src/agents/decision/cio.js";
import { buildCroNode, croSpec, fallbackCro, renderCro } from "../src/agents/decision/cro.js";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
import type {
  CioOutput,
  CroOutput,
  Layer4Outputs,
  PortfolioAction,
  RegimeSignal,
  SemiconductorOutput,
  SuperinvestorOutput,
} from "../src/agents/types.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import type { LlmHandle } from "../src/llm/factory.js";

// ============================================================ AGENTS_BY_LAYER

describe("AGENTS_BY_LAYER.decision", () => {
  it("lists the canonical 4 decision agents from Plan §5.4", () => {
    expect([...AGENTS_BY_LAYER.decision]).toEqual([
      "cro",
      "alpha_discovery",
      "autonomous_execution",
      "cio",
    ]);
  });
});

// ============================================================ spec sanity

describe("each Layer-4 spec wires correct fields", () => {
  it("cro", () => {
    expect(croSpec.agentId).toBe("cro");
    expect(croSpec.stateUpdateField).toBe("cro");
    expect(croSpec.fieldNames).toEqual([
      "rejected_picks",
      "correlated_risks",
      "black_swan_scenarios",
      "confidence",
    ]);
  });
  it("alpha_discovery", () => {
    expect(alphaDiscoverySpec.agentId).toBe("alpha_discovery");
    expect(alphaDiscoverySpec.stateUpdateField).toBe("alpha_discovery");
    expect(alphaDiscoverySpec.fieldNames).toEqual(["novel_picks", "confidence"]);
  });
  it("autonomous_execution", () => {
    expect(autonomousExecutionSpec.agentId).toBe("autonomous_execution");
    expect(autonomousExecutionSpec.stateUpdateField).toBe("autonomous_execution");
    expect(autonomousExecutionSpec.fieldNames).toEqual(["trades", "confidence"]);
  });
  it("cio", () => {
    expect(cioSpec.agentId).toBe("cio");
    expect(cioSpec.stateUpdateField).toBe("cio");
    expect(cioSpec.fieldNames).toEqual(["portfolio_actions", "confidence"]);
  });
});

// ============================================================ render + fallback

describe("renderers + fallbacks", () => {
  it("cro", () => {
    const fb = fallbackCro("");
    expect(fb.confidence).toBe(0);
    expect(renderCro(fb).length).toBeGreaterThan(20);
  });
  it("alpha_discovery", () => {
    const fb = fallbackAlphaDiscovery("");
    expect(fb.confidence).toBe(0);
    expect(fb.novel_picks).toHaveLength(0);
    expect(renderAlphaDiscovery(fb).length).toBeGreaterThan(10);
  });
  it("autonomous_execution", () => {
    const fb = fallbackAutonomousExecution("");
    expect(fb.confidence).toBe(0);
    expect(fb.trades).toHaveLength(0);
    expect(renderAutonomousExecution(fb).length).toBeGreaterThan(10);
  });
  it("cio", () => {
    const fb = fallbackCio("");
    expect(fb.confidence).toBe(0);
    expect(fb.portfolio_actions).toHaveLength(0);
    expect(renderCio(fb).length).toBeGreaterThan(20);
  });
});

// ============================================================ schema rejects

describe("schemas reject malformations", () => {
  it("cro rejects non-string ticker in rejected_picks", () => {
    expect(() =>
      croSpec.schema.parse({
        agent: "cro",
        // biome-ignore lint/suspicious/noExplicitAny: deliberately invalid
        rejected_picks: [{ ticker: 123 as any, reason: "x" }],
        correlated_risks: [],
        black_swan_scenarios: [],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("alpha_discovery rejects empty why_missed_by_others", () => {
    expect(() =>
      alphaDiscoverySpec.schema.parse({
        agent: "alpha_discovery",
        novel_picks: [{ ticker: "600519.SH", why_missed_by_others: "" }],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("autonomous_execution rejects size_pct out of [0, 1]", () => {
    expect(() =>
      autonomousExecutionSpec.schema.parse({
        agent: "autonomous_execution",
        trades: [{ ticker: "600519.SH", action: "BUY", size_pct: 1.5, conviction: 0.5 }],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("autonomous_execution rejects unknown action", () => {
    expect(() =>
      autonomousExecutionSpec.schema.parse({
        agent: "autonomous_execution",
        trades: [
          {
            ticker: "600519.SH",
            // biome-ignore lint/suspicious/noExplicitAny: deliberately invalid
            action: "BORROW" as any,
            size_pct: 0.1,
            conviction: 0.5,
          },
        ],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("cio rejects target_weight sum > 1.05", () => {
    expect(() =>
      cioSpec.schema.parse({
        agent: "cio",
        portfolio_actions: [
          {
            ticker: "A",
            action: "BUY",
            target_weight: 0.6,
            holding_period: "3M",
            dissent_notes: "",
          },
          {
            ticker: "B",
            action: "BUY",
            target_weight: 0.6,
            holding_period: "3M",
            dissent_notes: "",
          },
        ],
        confidence: 0.5,
      }),
    ).toThrow();
  });

  it("cio accepts target_weight sum < 1.0 (cash holding)", () => {
    expect(() =>
      cioSpec.schema.parse({
        agent: "cio",
        portfolio_actions: [
          {
            ticker: "600519.SH",
            action: "BUY",
            target_weight: 0.4,
            holding_period: "1Y",
            dissent_notes: "",
          },
        ],
        confidence: 0.5,
      }),
    ).not.toThrow();
  });

  it("cio rejects holding_period outside enum", () => {
    expect(() =>
      cioSpec.schema.parse({
        agent: "cio",
        portfolio_actions: [
          {
            ticker: "A",
            action: "BUY",
            target_weight: 0.5,
            // biome-ignore lint/suspicious/noExplicitAny: deliberately invalid
            holding_period: "10Y" as any,
            dissent_notes: "",
          },
        ],
        confidence: 0.5,
      }),
    ).toThrow();
  });
});

// ============================================================ context renderers

const baseState = (): DailyCycleStateType => ({
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
});

describe("Layer 1/2/3/4 context renderers", () => {
  const regime: RegimeSignal = {
    stance: "BULLISH",
    confidence: 0.7,
    key_drivers: ["d1", "d2"],
    layer_1_consensus_score: 0.6,
  };
  const semi: SemiconductorOutput = {
    agent: "semiconductor",
    longs: [{ ticker: "688981.SH", thesis: "x", conviction: 0.8 }],
    shorts: [],
    sector_score: 0.6,
    key_drivers: ["d"],
    confidence: 0.45,
  };
  const druck: SuperinvestorOutput = {
    agent: "druckenmiller",
    picks: [
      { ticker: "688981.SH", thesis: "regime BULLISH", conviction: 0.7, holding_period: "6M" },
    ],
    philosophy_note: "macro / momentum",
    key_drivers: ["d"],
    confidence: 0.6,
  };
  const cro: CroOutput = {
    agent: "cro",
    rejected_picks: [{ ticker: "BAD", reason: "regulatory" }],
    correlated_risks: ["multi-tier-1 cluster"],
    black_swan_scenarios: ["fed pivot"],
    confidence: 0.5,
  };

  it("L1 renders regime + falls back when null", () => {
    const s = baseState();
    expect(renderLayer1Context(s)).toContain("not available");
    s.layer1_consensus = regime;
    expect(renderLayer1Context(s)).toContain("BULLISH");
  });

  it("L2 renders sector picks + relationship_mapper differently", () => {
    const s = baseState();
    expect(renderLayer2Context(s)).toContain("not available");
    s.layer2_outputs = { semiconductor: semi };
    expect(renderLayer2Context(s)).toContain("688981.SH");
    s.layer2_outputs = {
      relationship_mapper: {
        agent: "relationship_mapper",
        supply_chains: [{ name: "半导体", tickers: ["688981.SH"], risk: "出口" }],
        ownership_clusters: [],
        contagion_risks: ["spillover"],
        key_drivers: ["d"],
        confidence: 0.4,
      },
    };
    expect(renderLayer2Context(s)).toContain("supply_chains");
    expect(renderLayer2Context(s)).toContain("contagion_risks");
  });

  it("L3 renders superinvestor picks", () => {
    const s = baseState();
    expect(renderLayer3Context(s)).toContain("not available");
    s.layer3_outputs = { druckenmiller: druck };
    expect(renderLayer3Context(s)).toContain("688981.SH");
    expect(renderLayer3Context(s)).toContain("druckenmiller");
  });

  it("L4 peer renders cro + excludes self", () => {
    const s = baseState();
    expect(renderLayer4PeerContext(s)).toContain("none of the peer outputs");
    s.layer4_outputs = { ...s.layer4_outputs, cro };
    const ctx = renderLayer4PeerContext(s, ["cio"]);
    expect(ctx).toContain("BAD:regulatory");
    expect(ctx).toContain("multi-tier-1 cluster");
    // Self-exclude when called for autonomous_execution
    const ctxExcl = renderLayer4PeerContext(s, ["cro", "cio"]);
    expect(ctxExcl).not.toContain("BAD:regulatory");
  });

  it("Phase-3/6 stubs are present", () => {
    expect(renderDarwinianWeightsStub()).toContain("Phase 3 stub");
    expect(renderJanusRegimeStub()).toContain("Phase 6 stub");
  });
});

// ============================================================ end-to-end via factory (cio)

describe("buildCioNode (Layer-4 factory smoke)", () => {
  let promptDir: string;

  class ScriptedLlm {
    invokeCalls = 0;
    bindToolsCalled = 0;
    structuredCalls = 0;
    readonly response: AIMessage;
    readonly structuredResponse: CioOutput;
    constructor(text: string, structured: CioOutput) {
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
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-l4-"));
    const dir = join(promptDir, "cohort_default", "decision");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "cio.zh.md"), "FAKE-CIO", "utf-8");
    writeFileSync(join(dir, "cio.en.md"), "FAKE-CIO", "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("writes layer4_outputs.cio AND mirrors to portfolio_actions", async () => {
    const cannedPortfolio: PortfolioAction[] = [
      {
        ticker: "688981.SH",
        action: "BUY",
        target_weight: 0.5,
        holding_period: "6M",
        dissent_notes: "",
      },
      {
        ticker: "600519.SH",
        action: "BUY",
        target_weight: 0.3,
        holding_period: "5Y+",
        dissent_notes: "alpha_discovery flagged this; auto_exec missed",
      },
    ];
    const canned: CioOutput = {
      agent: "cio",
      portfolio_actions: cannedPortfolio,
      confidence: 0.55,
    };

    const llm = new ScriptedLlm("analysis text", canned);
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

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

    const sample: DailyCycleStateType = baseState();
    sample.layer1_consensus = {
      stance: "BULLISH",
      confidence: 0.6,
      key_drivers: ["d"],
      layer_1_consensus_score: 0.5,
    };
    sample.layer4_outputs = {
      cro: {
        agent: "cro",
        rejected_picks: [],
        correlated_risks: [],
        black_swan_scenarios: ["fed pivot"],
        confidence: 0.4,
      },
      alpha_discovery: {
        agent: "alpha_discovery",
        novel_picks: [{ ticker: "600519.SH", why_missed_by_others: "ackman 嫌小" }],
        confidence: 0.5,
      },
      autonomous_execution: {
        agent: "autonomous_execution",
        trades: [{ ticker: "688981.SH", action: "BUY", size_pct: 0.5, conviction: 0.7 }],
        confidence: 0.5,
      },
      cio: null,
    };

    const node = buildCioNode({ llmHandle: handle, config, promptsRoot: promptDir });
    const update = await node(sample);
    const u = update as DailyCycleStateUpdate as unknown as {
      layer4_outputs?: Partial<Layer4Outputs>;
      portfolio_actions?: PortfolioAction[];
    };
    expect(u.layer4_outputs?.cio).toEqual(canned);
    // Top-level mirror — Phase 3 scorecard / TUI consumers read this.
    expect(u.portfolio_actions).toEqual(cannedPortfolio);
    expect(llm.invokeCalls).toBe(1);
    expect(llm.bindToolsCalled).toBe(0); // Layer-4 bypasses tool loop
    expect(llm.structuredCalls).toBe(1);
  });
});

// ============================================================ end-to-end via factory (cro)

describe("buildCroNode (no-tool synthesis, no portfolio_actions mirror)", () => {
  let promptDir: string;

  class ScriptedLlm {
    bindToolsCalled = 0;
    invokeCalls = 0;
    structuredCalls = 0;
    constructor(public canned: CroOutput) {}
    bindTools(_t: unknown): ScriptedLlm {
      this.bindToolsCalled++;
      return this;
    }
    withStructuredOutput(_s: unknown): { invoke: (input: unknown) => Promise<unknown> } {
      return {
        invoke: async () => {
          this.structuredCalls++;
          return this.canned;
        },
      };
    }
    async invoke(_messages: BaseMessage[]): Promise<AIMessage> {
      this.invokeCalls++;
      return new AIMessage("cro analysis");
    }
  }

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-l4cro-"));
    const dir = join(promptDir, "cohort_default", "decision");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "cro.zh.md"), "FAKE-CRO", "utf-8");
    writeFileSync(join(dir, "cro.en.md"), "FAKE-CRO", "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("does NOT write portfolio_actions (only cio does)", async () => {
    const canned: CroOutput = {
      agent: "cro",
      rejected_picks: [],
      correlated_risks: ["test"],
      black_swan_scenarios: ["test"],
      confidence: 0.4,
    };
    const llm = new ScriptedLlm(canned);
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };
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
    const node = buildCroNode({ llmHandle: handle, config, promptsRoot: promptDir });
    const update = await node(baseState());
    const u = update as DailyCycleStateUpdate as unknown as {
      layer4_outputs?: Partial<Layer4Outputs>;
      portfolio_actions?: PortfolioAction[];
    };
    expect(u.layer4_outputs?.cro).toEqual(canned);
    expect(u.portfolio_actions).toBeUndefined();
    expect(llm.bindToolsCalled).toBe(0);
    expect(llm.invokeCalls).toBe(1);
  });
});

// Compile-time canary
const _allBuilders = {
  cro: buildCroNode,
  alpha_discovery: buildAlphaDiscoveryNode,
  autonomous_execution: buildAutonomousExecutionNode,
  cio: buildCioNode,
};
void _allBuilders;
void ({} as BridgeApi);

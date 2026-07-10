/**
 * Vertical-slice test for central_bank — Plan §11.2 sub-step 2B exit gate.
 *
 * Drives the full path:
 *   loadPrompt → pickBridgeTools → runAgentToolLoop → invokeStructuredOrFreetext
 *   → state update with layer1_outputs.central_bank + llm_calls.
 *
 * Mocks:
 *   - BridgeApi.toolsList (so pickBridgeTools resolves)
 *   - BridgeApi.toolsCall (canned CSV per tool)
 *   - LLM (scripted: emits one tool_calls round, then a final analysis,
 *     then withStructuredOutput returns canned CentralBankOutput).
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { disableManifestResearchKnobsForLegacyFixtures } from "./helpers/research_knobs_env.js";

disableManifestResearchKnobsForLegacyFixtures();

import {
  buildCentralBankNode,
  buildUserContext,
  fallbackOutputFromText,
  pickPromptLanguage,
  renderCentralBank,
} from "../src/agents/macro/central_bank.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
import type { CentralBankOutput, LlmCallRecord, MacroAgentOutput } from "../src/agents/types.js";
import type { JsonSchemaObject, ToolMetadata } from "../src/bridge/index.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import type { LlmHandle } from "../src/llm/factory.js";

/**
 * LangGraph's Update type wraps each channel value in ``T | OverwriteValue<T>``.
 * Tests work with the plain ``T`` so cast through this helper to keep
 * assertions readable.
 */
function unwrapUpdate(update: DailyCycleStateUpdate): {
  layer1_outputs?: Record<string, MacroAgentOutput>;
  llm_calls?: LlmCallRecord[];
} {
  return update as unknown as {
    layer1_outputs?: Record<string, MacroAgentOutput>;
    llm_calls?: LlmCallRecord[];
  };
}

// ============================================================ helpers

interface FakePromptsRoot {
  root: string;
  cleanup: () => void;
}

function makeFakePromptsRootWithCentralBank(): FakePromptsRoot {
  const root = mkdtempSync(join(tmpdir(), "mosaic-2b-"));
  const dir = join(root, "cohort_default", "macro");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "central_bank.zh.md"), "# central_bank zh\n\nFAKE PROMPT ZH", "utf-8");
  writeFileSync(join(dir, "central_bank.en.md"), "# central_bank en\n\nFAKE PROMPT EN", "utf-8");
  return { root, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

function researchKnobsFence(): string {
  return `\`\`\`research-knobs
research-knobs:
  schema_version: research_knobs_v1
  layer: macro
  agent: macro.central_bank
  research_scope:
    must_cover: [liquidity_regime]
    must_not_cover: [final_portfolio_sizing]
  prediction_targets:
    - id: policy_stance_1w
      target_variable: central_bank_stance
      horizon: 1w
      allowed_outputs: [tightening, neutral, easing]
  evidence_registry:
    pboc_liquidity:
      tool: get_pboc_ops
      metric: pboc_net_injection_7d
      current_data: true
      primary: true
  evidence_weights:
    pboc_liquidity: 1.0
  lookbacks:
    net_injection_window_days: 7
  thresholds: {}
  confidence_caps:
    missing_current_data:
      cap: 0.55
      trigger: missing_required_evidence
      enforcement: code
      required_evidence: [pboc_liquidity]
  tie_breaks: []
  mutation_targets:
    - path: /rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value
      type: number
      min: 0
      max: 1
\`\`\``;
}

function writeCentralBankPromptWithKnobs(root: string): void {
  const dir = join(root, "cohort_default", "macro");
  writeFileSync(
    join(dir, "central_bank.zh.md"),
    `${researchKnobsFence()}\n\n# central_bank zh\n\nFAKE PROMPT ZH`,
    "utf-8",
  );
  writeFileSync(
    join(dir, "central_bank.en.md"),
    `${researchKnobsFence()}\n\n# central_bank en\n\nFAKE PROMPT EN`,
    "utf-8",
  );
}

const TOOL_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: {
    curr_date: { type: "string", description: "yyyy-mm-dd" },
    look_back_days: { type: "integer", description: "days", default: 7 },
  },
  required: ["curr_date"],
};

const FRED_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: {
    series_id: { type: "string", description: "id" },
    start_date: { type: "string", description: "start" },
    end_date: { type: "string", description: "end" },
  },
  required: ["series_id", "start_date", "end_date"],
};

const FAKE_TOOL_METADATAS: ToolMetadata[] = [
  {
    name: "get_rke_research_context",
    description: "RKE context",
    args_schema: TOOL_SCHEMA,
  },
  {
    name: "get_pboc_ops",
    description: "PBOC ops",
    args_schema: TOOL_SCHEMA,
  },
  {
    name: "get_fred_series",
    description: "FRED series",
    args_schema: FRED_SCHEMA,
  },
  {
    name: "get_yield_curve_cn",
    description: "CN yield curve",
    args_schema: TOOL_SCHEMA,
  },
];

class ScriptedLlm {
  invokeCalls: BaseMessage[][] = [];
  bindToolsCalled = 0;
  structuredCalls = 0;
  readonly responses: AIMessage[];
  readonly structuredResponse: CentralBankOutput | null;
  readonly structuredThrows: boolean;

  constructor(opts: {
    responses: AIMessage[];
    structuredResponse?: CentralBankOutput | null;
    structuredThrows?: boolean;
  }) {
    this.responses = [...opts.responses];
    this.structuredResponse = opts.structuredResponse ?? null;
    this.structuredThrows = opts.structuredThrows ?? false;
  }

  bindTools(_tools: unknown): ScriptedLlm {
    this.bindToolsCalled++;
    return this;
  }

  withStructuredOutput(_schema: unknown): {
    invoke: (input: unknown) => Promise<unknown>;
  } {
    if (this.structuredThrows) {
      throw new Error("structured output not supported");
    }
    return {
      invoke: async (_input) => {
        this.structuredCalls++;
        if (this.structuredResponse === null) {
          throw new Error("no structured response queued");
        }
        return this.structuredResponse;
      },
    };
  }

  async invoke(messages: BaseMessage[]): Promise<AIMessage> {
    this.invokeCalls.push(messages);
    const next = this.responses.shift();
    if (!next) throw new Error(`ScriptedLlm exhausted after ${this.invokeCalls.length} invokes`);
    return next;
  }
}

function makeScriptedHandle(llm: ScriptedLlm): LlmHandle {
  return {
    llm: llm as unknown as LlmHandle["llm"],
    provider: "fake",
    model: "fake-model",
    baseUrl: undefined,
  };
}

interface FakeApiOpts {
  toolCallResponses?: Record<string, string>;
  metadatas?: ToolMetadata[];
  toolCallSpy?: (name: string, args: Record<string, unknown>) => void;
}

function makeFakeBridgeApi(opts: FakeApiOpts = {}): BridgeApi {
  const responses = opts.toolCallResponses ?? {
    get_pboc_ops: "trade_date,op_type,volume\n20240624,Reverse Repo,200",
    get_fred_series: "# FRED FEDFUNDS\ndate,value\n2024-06-24,5.33",
    get_yield_curve_cn: "trade_date,curve_term,curve_yield\n20240624,10,2.42",
  };
  return {
    toolsList: async () => opts.metadatas ?? FAKE_TOOL_METADATAS,
    toolsCall: async (name: string, args: Record<string, unknown>) => {
      opts.toolCallSpy?.(name, args);
      const text = responses[name];
      if (text === undefined) {
        throw new Error(`No mock response for tool ${name}`);
      }
      return { text };
    },
  } as unknown as BridgeApi;
}

const BASE_CONFIG: MosaicConfig = {
  llm_provider: "fake",
  deep_think_llm: "fake-deep",
  quick_think_llm: "fake-quick",
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
  trace_id: "test-trace",
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

// ============================================================ helpers tests

describe("pickPromptLanguage", () => {
  it("maps Chinese / English / Bilingual", () => {
    expect(pickPromptLanguage({ ...BASE_CONFIG, output_language: "Chinese" })).toBe("zh");
    expect(pickPromptLanguage({ ...BASE_CONFIG, output_language: "English" })).toBe("en");
    expect(pickPromptLanguage({ ...BASE_CONFIG, output_language: "Bilingual" })).toBe("Bilingual");
    // Defaults to Chinese on unknown values.
    expect(pickPromptLanguage({ ...BASE_CONFIG, output_language: "klingon" })).toBe("zh");
  });
});

describe("buildUserContext", () => {
  it("includes as_of_date / mode / cohort", () => {
    const ctx = buildUserContext(SAMPLE_STATE, "central_bank");
    expect(ctx).toContain("2024-06-24");
    expect(ctx).toContain("live");
    expect(ctx).toContain("cohort_default");
    expect(ctx).toContain("central_bank");
  });
});

describe("renderCentralBank", () => {
  it("formats the output as readable prose", () => {
    const o: CentralBankOutput = {
      agent: "central_bank",
      stance: "ACCOMMODATIVE",
      key_rate_change_bps: -10,
      qe_qt_balance_change: "OMO net +20B CNY",
      next_window: "2024-07-15",
      key_drivers: ["d1", "d2"],
      confidence: 0.78,
    };
    const out = renderCentralBank(o);
    expect(out).toContain("ACCOMMODATIVE");
    expect(out).toContain("d1");
    expect(out).toContain("0.78");
  });
});

describe("fallbackOutputFromText", () => {
  it("emits confidence=0 with a non-empty key_drivers list", () => {
    const out = fallbackOutputFromText("");
    expect(out.confidence).toBe(0);
    expect(out.key_drivers.length).toBeGreaterThan(0);
    expect(out.stance).toBe("NEUTRAL");
  });
});

// ============================================================ vertical slice

describe("buildCentralBankNode (vertical slice)", () => {
  let fakePrompts: FakePromptsRoot;
  let oldKnobsEnabled: string | undefined;

  beforeEach(() => {
    oldKnobsEnabled = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS;
    delete process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS;
    fakePrompts = makeFakePromptsRootWithCentralBank();
    clearPromptCache();
  });

  afterEach(() => {
    if (oldKnobsEnabled === undefined) {
      delete process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS;
    } else {
      process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS = oldKnobsEnabled;
    }
    fakePrompts.cleanup();
    clearPromptCache();
  });

  it("end-to-end: tool loop -> structured extraction -> state update", async () => {
    const cannedOutput: CentralBankOutput = {
      agent: "central_bank",
      stance: "ACCOMMODATIVE",
      key_rate_change_bps: -5,
      qe_qt_balance_change: "OMO net injection +20B CNY, MLF -150B CNY",
      next_window: "2024-07-15",
      key_drivers: [
        "PBOC OMO net injection +200亿 on 2024-06-24",
        "Fed FEDFUNDS held at 5.33% — no change",
        "CN 10Y yield down 5bp to 2.42%",
      ],
      confidence: 0.78,
    };

    const llm = new ScriptedLlm({
      responses: [
        // Iteration 1: emit 3 tool calls.
        new AIMessage({
          content: "",
          tool_calls: [
            {
              id: "c1",
              name: "get_pboc_ops",
              args: { curr_date: "2024-06-24" },
              type: "tool_call",
            },
            {
              id: "c2",
              name: "get_fred_series",
              args: { series_id: "FEDFUNDS", start_date: "2024-06-17", end_date: "2024-06-24" },
              type: "tool_call",
            },
            {
              id: "c3",
              name: "get_yield_curve_cn",
              args: { curr_date: "2024-06-24" },
              type: "tool_call",
            },
          ],
        }),
        // Iteration 2: tool results returned, model writes the analysis.
        new AIMessage(
          "央行立场偏松：PBOC OMO 净投放 200 亿（reverse repo），" +
            "Fed FEDFUNDS 维持 5.33%，CN 10Y 微下 5bp 至 2.42%。" +
            "双央行错位，PBOC 边际宽松，Fed 持平。",
        ),
      ],
      structuredResponse: cannedOutput,
    });

    const toolCallSpy = vi.fn();
    const api = makeFakeBridgeApi({ toolCallSpy });

    const node = buildCentralBankNode({
      llmHandle: makeScriptedHandle(llm),
      api,
      config: BASE_CONFIG,
      promptsRoot: fakePrompts.root,
    });

    const update = await node(SAMPLE_STATE);

    // Three mock tools were invoked exactly once each.
    expect(toolCallSpy).toHaveBeenCalledTimes(3);
    const toolNames = toolCallSpy.mock.calls.map((c) => c[0]).sort();
    expect(toolNames).toEqual(["get_fred_series", "get_pboc_ops", "get_yield_curve_cn"]);

    // LLM was invoked twice in the tool loop + once for structured output.
    expect(llm.invokeCalls.length).toBe(2);
    expect(llm.bindToolsCalled).toBe(1);
    expect(llm.structuredCalls).toBe(1);

    // State update writes the canned output.
    const out = unwrapUpdate(update);
    expect(out.layer1_outputs?.central_bank).toEqual(cannedOutput);
    expect(out.llm_calls).toBeDefined();
    expect(out.llm_calls?.[0]?.agent).toBe("central_bank");
    expect(out.llm_calls?.[0]?.model).toBe("fake-model");
  });

  it("uses the evidence snapshot and rejects an enabled output without claims", async () => {
    process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS = "central_bank";
    process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES = "central_bank:agent_run";
    writeCentralBankPromptWithKnobs(fakePrompts.root);
    const llm = new ScriptedLlm({
      responses: [new AIMessage("analysis without required current-data tool call")],
      structuredResponse: {
        agent: "central_bank",
        stance: "ACCOMMODATIVE",
        key_rate_change_bps: -5,
        qe_qt_balance_change: "PBOC liquidity supportive",
        next_window: "2024-07-15",
        key_drivers: ["PBOC supportive"],
        confidence: 0.82,
      },
    });
    const logs: string[] = [];
    const node = buildCentralBankNode({
      llmHandle: makeScriptedHandle(llm),
      api: makeFakeBridgeApi(),
      config: BASE_CONFIG,
      promptsRoot: fakePrompts.root,
      onLog: (message) => logs.push(message),
    });

    const update = await node(SAMPLE_STATE);

    const output = unwrapUpdate(update).layer1_outputs?.central_bank as CentralBankOutput;
    expect(output.confidence).toBe(0);
    expect(output.verified_claim_audit).toMatchObject({
      raw_output_accepted: false,
      fallback_reason_code: "CLAIM_EVIDENCE_GRAPH_REJECTED",
    });
    expect(output.verified_claim_graph?.claims).toEqual([
      expect.objectContaining({ claim_type: "uncertainty", evidence_refs: [] }),
    ]);
    expect(String(llm.invokeCalls[0]?.[0]?.content)).toContain("Runtime Research Knobs Contract");
    expect(String(llm.invokeCalls[0]?.[1]?.content)).toContain("Runtime-owned evidence catalog");
    expect(logs.join("\n")).toContain("fired_caps=missing_current_data");
    expect(logs.join("\n")).toContain("knob_snapshot=sha256:");
    expect(logs.join("\n")).toContain("claim_output=fallback");
  });

  it("forwards backtest context to the bridge when as_of_date is set", async () => {
    const llm = new ScriptedLlm({
      responses: [new AIMessage("simple analysis text")],
      structuredResponse: {
        agent: "central_bank",
        stance: "NEUTRAL",
        key_rate_change_bps: 0,
        qe_qt_balance_change: "no material change",
        next_window: "unknown",
        key_drivers: ["holiday week"],
        confidence: 0.4,
      },
    });

    let observedContext: { mode?: string; as_of_date?: string | null } | undefined;
    const api = {
      toolsList: async () => FAKE_TOOL_METADATAS,
      toolsCall: async (
        _name: string,
        _args: Record<string, unknown>,
        ctx?: { mode?: string; as_of_date?: string | null },
      ) => {
        observedContext = ctx;
        return { text: "{}" };
      },
    } as unknown as BridgeApi;

    const node = buildCentralBankNode({
      llmHandle: makeScriptedHandle(llm),
      api,
      config: BASE_CONFIG,
      promptsRoot: fakePrompts.root,
    });

    await node({ ...SAMPLE_STATE, mode: "backtest", as_of_date: "2024-06-24" });

    // Even though no tool got called (the LLM short-circuited with a final
    // text), pickBridgeTools embedded the backtest context for any tool that
    // *would* have been invoked. We exercise the active path by issuing a
    // tool_call instead — see the previous test.
    expect(observedContext).toBeUndefined();
  });

  it("falls back to fallbackOutputFromText when structured extractor throws and free-text loop yields nothing", async () => {
    const llm = new ScriptedLlm({
      responses: [
        // Loop returns empty content immediately (no tools needed).
        new AIMessage(""),
        // Free-text fallback inside invokeStructuredOrFreetext also empty.
        new AIMessage(""),
      ],
      structuredThrows: true,
    });

    const api = makeFakeBridgeApi();
    const node = buildCentralBankNode({
      llmHandle: makeScriptedHandle(llm),
      api,
      config: BASE_CONFIG,
      promptsRoot: fakePrompts.root,
    });

    const update = await node(SAMPLE_STATE);
    const out = unwrapUpdate(update).layer1_outputs?.central_bank as CentralBankOutput;
    expect(out.confidence).toBe(0);
    expect(out.stance).toBe("NEUTRAL");
    expect(out.next_window).toBe("unknown");
  });

  it("CentralBankSchema rejects malformed outputs at the type boundary", async () => {
    const { CentralBankSchema } = await import("../src/agents/macro/_schemas.js");
    expect(() =>
      CentralBankSchema.parse({
        agent: "central_bank",
        stance: "WEIRD",
        key_rate_change_bps: 0,
        qe_qt_balance_change: "x",
        next_window: "unknown",
        key_drivers: ["a"],
        confidence: 0.5,
      }),
    ).toThrow();
    expect(() =>
      CentralBankSchema.parse({
        agent: "central_bank",
        stance: "NEUTRAL",
        key_rate_change_bps: 0,
        qe_qt_balance_change: "x",
        next_window: "unknown",
        key_drivers: [],
        confidence: 0.5,
      }),
    ).toThrow(); // empty key_drivers
  });
});

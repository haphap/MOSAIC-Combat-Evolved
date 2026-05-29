import { describe, expect, it } from "vitest";
import {
  appendReducer,
  type DailyCycleState,
  dictMergeReducer,
  emptyLayer4,
  layer4Reducer,
  replaceReducer,
} from "../src/agents/state.js";
import type {
  CentralBankOutput,
  ChinaOutput,
  CroOutput,
  Layer4Outputs,
  LlmCallRecord,
  RegimeSignal,
} from "../src/agents/types.js";

/** Reducer functions are exported for direct unit testing — see Plan §11.2. */

describe("state reducers", () => {
  describe("replaceReducer (last-write-wins)", () => {
    it("returns the latest value regardless of type", () => {
      expect(replaceReducer("a", "b")).toBe("b");
      expect(replaceReducer<number | null>(null, 42)).toBe(42);
      expect(replaceReducer<{ x: number }>({ x: 1 }, { x: 2 })).toEqual({ x: 2 });
    });
  });

  describe("dictMergeReducer", () => {
    it("merges two non-overlapping dicts", () => {
      const a = { central_bank: "first" };
      const b = { china: "second" };
      expect(dictMergeReducer(a, b)).toEqual({
        central_bank: "first",
        china: "second",
      });
    });

    it("new value wins on key collision", () => {
      const merged = dictMergeReducer({ x: 1, y: 2 }, { y: 99 });
      expect(merged).toEqual({ x: 1, y: 99 });
    });

    it("does not mutate the previous dict", () => {
      const prev = { x: 1 };
      dictMergeReducer(prev, { y: 2 });
      expect(prev).toEqual({ x: 1 });
    });
  });

  describe("layer4Reducer (per-key partial update)", () => {
    it("preserves existing keys when only one is written", () => {
      const empty = emptyLayer4();
      const cro: CroOutput = {
        agent: "cro",
        rejected_picks: [{ ticker: "600519.SH", reason: "too crowded" }],
        correlated_risks: ["liquor concentration"],
        black_swan_scenarios: ["regulator action"],
      };
      const after = layer4Reducer(empty, { cro });
      expect(after.cro).toEqual(cro);
      expect(after.alpha_discovery).toBeNull();
      expect(after.autonomous_execution).toBeNull();
      expect(after.cio).toBeNull();
    });

    it("overwrites only the keys present in the update", () => {
      const stage1: Layer4Outputs = {
        ...emptyLayer4(),
        cro: {
          agent: "cro",
          rejected_picks: [],
          correlated_risks: [],
          black_swan_scenarios: [],
        },
      };
      const stage2 = layer4Reducer(stage1, {
        alpha_discovery: { agent: "alpha_discovery", novel_picks: [] },
      });
      expect(stage2.cro).not.toBeNull();
      expect(stage2.alpha_discovery).not.toBeNull();
    });
  });

  describe("appendReducer", () => {
    it("appends two batches preserving order", () => {
      const c1: LlmCallRecord = {
        ts: "2024-06-30T10:00:00Z",
        agent: "central_bank",
        model: "claude-sonnet-4",
        provider: "anthropic",
        prompt_tokens: 1200,
        completion_tokens: 320,
        cost_usd: 0.0078,
      };
      const c2 = { ...c1, agent: "china" };
      const c3 = { ...c1, agent: "dollar" };
      const after = appendReducer(appendReducer([], [c1]), [c2, c3]);
      expect(after.map((r) => r.agent)).toEqual(["central_bank", "china", "dollar"]);
    });

    it("does not mutate the previous array", () => {
      const prev = [1, 2, 3];
      appendReducer(prev, [4]);
      expect(prev).toEqual([1, 2, 3]);
    });
  });

  describe("emptyLayer4", () => {
    it("returns a fresh object on each call", () => {
      const a = emptyLayer4();
      const b = emptyLayer4();
      expect(a).toEqual(b);
      expect(a).not.toBe(b); // identity check — defaults must not share state
    });

    it("has all four slots null", () => {
      expect(emptyLayer4()).toEqual({
        cro: null,
        alpha_discovery: null,
        autonomous_execution: null,
        cio: null,
      });
    });
  });
});

describe("DailyCycleState integration via reducer composition", () => {
  it("simulates a full Layer-1 fan-out with two parallel writers", () => {
    const cb: CentralBankOutput = {
      agent: "central_bank",
      stance: "ACCOMMODATIVE",
      key_rate_change_bps: -10,
      qe_qt_balance_change: "reverse repo +200B CNY",
      next_window: "2024-07-15",
      key_drivers: ["MLF rolled at lower rate"],
      confidence: 0.78,
    };
    const cn: ChinaOutput = {
      agent: "china",
      policy_direction: "PRO_GROWTH",
      sector_focus: ["semiconductor"],
      risk_drivers: ["property"],
      key_drivers: ["新质生产力 keyword"],
      confidence: 0.65,
    };
    // Two concurrent agent nodes both produce a 1-key update — the reducer
    // composes them into a single map.
    const after = dictMergeReducer<CentralBankOutput | ChinaOutput>(
      dictMergeReducer<CentralBankOutput | ChinaOutput>({}, { central_bank: cb }),
      { china: cn },
    );
    expect(Object.keys(after)).toEqual(["central_bank", "china"]);
  });

  it("Annotation root carries our 14 channels (sanity check)", () => {
    // Spot-check that the named channels exist on the Annotation root.
    // We do NOT poke at internal reducer/default APIs (private LangGraph shape);
    // instead we rely on the named-export reducer tests above + the typecheck
    // pass to lock the contract.
    type Keys = keyof typeof DailyCycleState.State;
    const channels: Keys[] = [
      "messages",
      "active_cohort",
      "as_of_date",
      "mode",
      "trace_id",
      "continuity_context",
      "lesson_context",
      "method_context",
      "layer1_outputs",
      "layer1_consensus",
      "layer2_outputs",
      "layer2_consensus",
      "layer3_outputs",
      "layer4_outputs",
      "portfolio_actions",
      "llm_calls",
    ];
    expect(channels).toHaveLength(16);
  });

  it("layer-4 partial update via the canonical reducer chain", () => {
    const cro: CroOutput = {
      agent: "cro",
      rejected_picks: [{ ticker: "600519.SH", reason: "too crowded" }],
      correlated_risks: [],
      black_swan_scenarios: [],
    };
    const start = emptyLayer4();
    const stage1 = layer4Reducer(start, { cro });
    const final: RegimeSignal = {
      stance: "BULLISH",
      confidence: 0.6,
      key_drivers: [],
      layer_1_consensus_score: 0.55,
    };
    // unrelated layer-1 consensus replace happens independently
    expect(replaceReducer<RegimeSignal | null>(null, final)).toEqual(final);
    expect(stage1.cro).toEqual(cro);
  });
});

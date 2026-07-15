import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  ALL_MACRO_AGENTS,
  aggregateLayer1,
  buildAggregateLayer1Node,
  MACRO_FACTOR_GROUPS,
  MacroAggregationRejectedError,
  signalForAgent,
} from "../src/agents/macro/_aggregator.js";
import type { MacroAgentId, MacroAgentOutput } from "../src/agents/types.js";
import { macroOutput } from "./helpers/macro.js";

function completeOutputs(
  overrides: Partial<Record<MacroAgentId, Partial<MacroAgentOutput>>> = {},
): Record<string, MacroAgentOutput> {
  return Object.fromEntries(
    ALL_MACRO_AGENTS.map((agent) => [agent, macroOutput(agent, overrides[agent] as never)]),
  ) as Record<string, MacroAgentOutput>;
}

describe("uniform macro transmission", () => {
  it("maps direction and strength to s_i", () => {
    expect(signalForAgent(macroOutput("china", { direction: "SUPPORTIVE", strength: 3 }))).toBe(
      0.6,
    );
    expect(signalForAgent(macroOutput("china", { direction: "ADVERSE", strength: 5 }))).toBe(-1);
    expect(signalForAgent(macroOutput("china"))).toBe(0);
  });

  it("keeps exactly ten current roles and six non-overlapping groups", () => {
    expect(ALL_MACRO_AGENTS).toEqual([
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
    expect(Object.values(MACRO_FACTOR_GROUPS).flat()).toEqual(ALL_MACRO_AGENTS);
    expect(Object.keys(MACRO_FACTOR_GROUPS)).toHaveLength(6);
  });
});

describe("six-group aggregation", () => {
  it("rejects formal aggregation until all ten agents are accepted", () => {
    expect(() => aggregateLayer1({ china: macroOutput("china") })).toThrow(
      MacroAggregationRejectedError,
    );
  });

  it("does not reward a group for having more agents", () => {
    const outputs = completeOutputs();
    for (const agent of ALL_MACRO_AGENTS) {
      outputs[agent] = macroOutput(agent, {
        direction: "SUPPORTIVE",
        strength: 5,
        confidence: 1,
      } as never);
    }
    const result = aggregateLayer1(outputs);
    expect(result.score).toBeCloseTo(1);
    for (const group of result.groups) expect(group.effective_weight).toBeCloseTo(1 / 6);
  });

  it("preserves a single-agent group's Darwinian reliability", () => {
    const result = aggregateLayer1(completeOutputs(), {
      darwinianWeights: { china: { weight: 2 } },
    });
    expect(
      result.groups.find((group) => group.group === "china_economy")?.effective_weight,
    ).toBeCloseTo(2 / 7);
  });

  it("ranks agents only inside a multi-agent group before group weighting", () => {
    const outputs = completeOutputs({
      dollar: { direction: "SUPPORTIVE", strength: 5, confidence: 1 },
      yield_curve: { direction: "ADVERSE", strength: 5, confidence: 1 },
    });
    const result = aggregateLayer1(outputs, {
      darwinianWeights: { dollar: { weight: 2 }, yield_curve: { weight: 0.5 } },
    });
    const financial = result.groups.find((group) => group.group === "financial_conditions");
    expect(financial?.direction).toBeCloseTo(0.6);
    expect(financial?.reliability).toBeCloseTo(1.25);
  });

  it("uses ±0.3 only after the exact reliability-normalized group score", () => {
    const outputs = completeOutputs();
    for (const agent of ALL_MACRO_AGENTS) {
      outputs[agent] = macroOutput(agent, { confidence: 1 } as never);
    }
    outputs.china = macroOutput("china", {
      direction: "SUPPORTIVE",
      strength: 5,
      confidence: 1,
    });
    outputs.us_economy = macroOutput("us_economy", {
      direction: "SUPPORTIVE",
      strength: 5,
      confidence: 1,
    });
    outputs.central_bank = macroOutput("central_bank", {
      direction: "ADVERSE",
      strength: 5,
      confidence: 1,
    });
    const result = aggregateLayer1(outputs);
    expect(result.score).toBeCloseTo(1 / 6);
    expect(result.signal.stance).toBe("NEUTRAL");
    expect(result.signal.layer_1_consensus_score).toBeCloseTo(0.167);
  });

  it("never inherits legacy-agent weights", () => {
    const baseline = aggregateLayer1(completeOutputs());
    const legacy = aggregateLayer1(completeOutputs(), {
      darwinianWeights: {
        emerging_markets: { weight: 2.5 },
        news_sentiment: { weight: 2.5 },
      },
    });
    expect(legacy.score).toBe(baseline.score);
  });

  it("matches the shared Python/TypeScript aggregation fixture", () => {
    const fixture = JSON.parse(
      readFileSync(
        resolve(process.cwd(), "..", "tests", "fixtures", "macro_aggregation_case.json"),
        "utf8",
      ),
    ) as {
      outputs: Record<MacroAgentId, Partial<MacroAgentOutput>>;
      darwinian_weights: Record<string, number>;
      expected_score: number;
      expected_stance: string;
    };
    const outputs = Object.fromEntries(
      ALL_MACRO_AGENTS.map((agent) => [agent, macroOutput(agent, fixture.outputs[agent] as never)]),
    ) as Record<string, MacroAgentOutput>;
    const darwinianWeights = Object.fromEntries(
      Object.entries(fixture.darwinian_weights).map(([agent, weight]) => [agent, { weight }]),
    );
    const result = aggregateLayer1(outputs, { darwinianWeights });
    expect(result.score).toBeCloseTo(fixture.expected_score);
    expect(result.signal.stance).toBe(fixture.expected_stance);
  });

  it("loads current role weights in the graph node", async () => {
    const darwinianGetWeights = vi.fn(async () => ({
      weights: { china: { weight: 2, sharpe_30: null, sharpe_90: null, quartile: null } },
    }));
    const node = buildAggregateLayer1Node({
      api: { darwinianGetWeights },
      config: { darwinian: { weight_rewrite_enabled: true } } as never,
    });
    const update = await node({
      active_cohort: "cohort_default",
      as_of_date: "2026-07-15",
      layer1_outputs: completeOutputs(),
    } as never);
    expect((update.layer1_consensus as never as { stance: string }).stance).toBe("NEUTRAL");
    expect(darwinianGetWeights).toHaveBeenCalledWith("cohort_default", "2026-07-15");
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import type { BridgeApi } from "../src/bridge/types.js";
import { LAYER_ORDER, runCohortTraining, runPrismTraining } from "../src/prism/trainer.js";

// Mock the autoresearch orchestrator the trainer fans out to.
vi.mock("../src/autoresearch/orchestrator.js", () => ({
  runAutoresearchCycle: vi.fn(),
}));

import { runAutoresearchCycle } from "../src/autoresearch/orchestrator.js";

const mockedCycle = vi.mocked(runAutoresearchCycle);

class FakeLlm {
  async invoke() {
    return { content: "fake" };
  }
  withStructuredOutput() {
    return { invoke: async () => ({}) };
  }
}

const deps = { llm: new FakeLlm() as never, api: {} as unknown as BridgeApi };

beforeEach(() => {
  vi.clearAllMocks();
  mockedCycle.mockImplementation(async (opts) => ({
    mutations: [
      { agent: opts.forceAgent ?? "?", version_id: 1, status: "kept" as const, delta_sharpe: 0.2 },
    ],
  }));
});

describe("runCohortTraining", () => {
  it("trains all 25 agents across the 4 layers in order", async () => {
    const result = await runCohortTraining({ cohort: "crisis_2008", fakeLlm: true, deps });

    expect(result.layers.map((l) => l.layer)).toEqual([...LAYER_ORDER]);
    for (const l of result.layers) {
      expect(l.agents.length).toBe(AGENTS_BY_LAYER[l.layer].length);
    }
    const total = result.layers.reduce((n, l) => n + l.agents.length, 0);
    expect(total).toBe(25);
    expect(mockedCycle).toHaveBeenCalledTimes(25);
  });

  it("forces each agent and threads cohort/fakeLlm/maxMutations", async () => {
    await runCohortTraining({
      cohort: "crisis_2008",
      fakeLlm: true,
      maxMutationsPerAgent: 1,
      deps,
    });
    const call = mockedCycle.mock.calls.find((c) => c[0].forceAgent === "volatility");
    expect(call).toBeDefined();
    expect(call?.[0]).toMatchObject({
      cohort: "crisis_2008",
      forceAgent: "volatility",
      maxMutations: 1,
      fakeLlm: true,
    });
  });

  it("never exceeds maxAgentsConcurrent within a layer", async () => {
    let inFlight = 0;
    let peak = 0;
    mockedCycle.mockImplementation(async (opts) => {
      inFlight++;
      peak = Math.max(peak, inFlight);
      await new Promise((r) => setTimeout(r, 1));
      inFlight--;
      return {
        mutations: [{ agent: opts.forceAgent ?? "?", version_id: 1, status: "kept" as const }],
      };
    });

    await runCohortTraining({ cohort: "crisis_2008", maxAgentsConcurrent: 3, fakeLlm: true, deps });
    expect(peak).toBeLessThanOrEqual(3);
    expect(peak).toBeGreaterThan(1); // actually ran concurrently
  });

  it("respects a layer subset", async () => {
    const result = await runCohortTraining({
      cohort: "crisis_2008",
      layers: ["decision"],
      fakeLlm: true,
      deps,
    });
    expect(result.layers).toHaveLength(1);
    expect(result.layers[0]?.layer).toBe("decision");
    expect(mockedCycle).toHaveBeenCalledTimes(AGENTS_BY_LAYER.decision.length);
  });

  it("synthesizes needs_fill when an agent produces no mutation", async () => {
    mockedCycle.mockResolvedValue({ mutations: [] });
    const result = await runCohortTraining({
      cohort: "crisis_2008",
      layers: ["decision"],
      fakeLlm: true,
      deps,
    });
    expect(result.layers[0]?.agents.every((a) => a.status === "needs_fill")).toBe(true);
  });
});

describe("runPrismTraining", () => {
  it("trains cohorts sequentially in the given order", async () => {
    const order: string[] = [];
    mockedCycle.mockImplementation(async (opts) => {
      order.push(opts.cohort);
      return { mutations: [{ agent: opts.forceAgent ?? "?", version_id: 1, status: "kept" }] };
    });

    const results = await runPrismTraining({
      cohorts: ["bull_2007", "crisis_2008"],
      layers: ["macro"],
      fakeLlm: true,
      deps,
    });

    expect(results.map((r) => r.cohort)).toEqual(["bull_2007", "crisis_2008"]);
    // All bull_2007 calls precede all crisis_2008 calls (sequential cohorts).
    const firstCrisis = order.indexOf("crisis_2008");
    const lastBull = order.lastIndexOf("bull_2007");
    expect(lastBull).toBeLessThan(firstCrisis);
  });
});

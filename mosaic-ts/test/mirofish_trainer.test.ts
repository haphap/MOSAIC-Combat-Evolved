import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BridgeApi, MirofishScenario } from "../src/bridge/types.js";
import { runMirofishTraining } from "../src/mirofish/trainer.js";

function scenario(type: string, csiRet: number): MirofishScenario {
  return {
    scenario_type: type,
    scenario_name: type,
    probability: 0.2,
    num_days: 30,
    price_paths: {
      "000300.SH": {
        ticker: "000300.SH",
        start_price: 3500,
        prices: [3500, 3500 * (1 + csiRet)],
        cumulative_return: csiRet,
        volatility: 0.2,
      },
    },
    events: [{ day: 5, date: "2024-01-06", event: "x", impact: "HIGH" }],
    final_state: { regime: "NEUTRAL", narrative: "", csi300_return: csiRet },
  };
}

class FakeLlm {
  async invoke() {
    return { content: "fake" };
  }
  withStructuredOutput() {
    return { invoke: async () => ({}) };
  }
}

function fakeApi(overrides: Partial<Record<string, unknown>> = {}): BridgeApi {
  return {
    mirofishGenerateScenarios: vi.fn().mockResolvedValue({
      scenarios: [scenario("bull", 0.12), scenario("bear", -0.1)],
    }),
    mirofishScoreRecommendation: vi.fn().mockResolvedValue({ score: 0.7 }),
    mirofishRecordRun: vi.fn().mockResolvedValue({ id: 1 }),
    ...overrides,
  } as unknown as BridgeApi;
}

const deps = (api: BridgeApi) => ({ llm: new FakeLlm() as never, api });

beforeEach(() => vi.clearAllMocks());

describe("runMirofishTraining", () => {
  it("trains each agent over all scenarios and records (fake-llm)", async () => {
    const api = fakeApi();
    const result = await runMirofishTraining({
      agents: ["druckenmiller", "ackman"],
      seed: 42,
      fakeLlm: true,
      deps: deps(api),
    });

    expect(result.agents).toHaveLength(2);
    // 2 scenarios scored per agent.
    expect(result.agents[0]?.scenario_scores).toHaveLength(2);
    expect(result.agents[0]?.avg_score).toBeCloseTo(0.7);
    expect(api.mirofishScoreRecommendation).toHaveBeenCalledTimes(4); // 2 agents × 2 scenarios
    expect(api.mirofishRecordRun).toHaveBeenCalledTimes(2);
  });

  it("dry-run scores but does not record", async () => {
    const api = fakeApi();
    await runMirofishTraining({
      agents: ["druckenmiller"],
      fakeLlm: true,
      dryRun: true,
      deps: deps(api),
    });
    expect(api.mirofishScoreRecommendation).toHaveBeenCalled();
    expect(api.mirofishRecordRun).not.toHaveBeenCalled();
  });

  it("fake-llm canned rec longs the strongest path in a bull scenario", async () => {
    let captured: unknown = null;
    const api = fakeApi({
      mirofishScoreRecommendation: vi.fn().mockImplementation(async (p: unknown) => {
        captured = (p as { recommendation: unknown }).recommendation;
        return { score: 0.8 };
      }),
      mirofishGenerateScenarios: vi.fn().mockResolvedValue({ scenarios: [scenario("bull", 0.15)] }),
    });
    await runMirofishTraining({ agents: ["x"], fakeLlm: true, deps: deps(api) });
    expect(captured).toMatchObject({ recommendation: "BUY", tickers: ["000300.SH"] });
  });

  it("passes seed/num_days/scenarios through to generate", async () => {
    const api = fakeApi();
    await runMirofishTraining({
      agents: ["x"],
      numDays: 10,
      seed: 99,
      scenarios: ["base"],
      fakeLlm: true,
      deps: deps(api),
    });
    expect(api.mirofishGenerateScenarios).toHaveBeenCalledWith({
      num_days: 10,
      seed: 99,
      scenarios: ["base"],
    });
  });

  it("threads scorer through to score_recommendation (default omits it)", async () => {
    const api = fakeApi();
    await runMirofishTraining({
      agents: ["x"],
      fakeLlm: true,
      scorer: "path_aware",
      deps: deps(api),
    });
    expect(api.mirofishScoreRecommendation).toHaveBeenCalledWith(
      expect.objectContaining({ scorer: "path_aware" }),
    );

    const api2 = fakeApi();
    await runMirofishTraining({ agents: ["x"], fakeLlm: true, deps: deps(api2) });
    const call = (api2.mirofishScoreRecommendation as ReturnType<typeof vi.fn>).mock.calls[0]?.[0];
    expect(call).not.toHaveProperty("scorer"); // default → server decides
  });
});

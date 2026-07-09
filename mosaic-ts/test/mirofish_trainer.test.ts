import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BridgeApi, MirofishScenario } from "../src/bridge/types.js";
import { parseRecommendationResponse, runMirofishTraining } from "../src/mirofish/trainer.js";

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

function scenarioWithCurrentPositions(): MirofishScenario {
  return {
    ...scenario("position_stress", 0.01),
    price_paths: {
      "000300.SH": {
        ticker: "000300.SH",
        start_price: 3500,
        prices: [3500, 3535],
        cumulative_return: 0.01,
        volatility: 0.2,
      },
      "WIN.SH": {
        ticker: "WIN.SH",
        start_price: 100,
        prices: [100, 112],
        cumulative_return: 0.12,
        volatility: 0.2,
      },
      "LOSS.SH": {
        ticker: "LOSS.SH",
        start_price: 100,
        prices: [100, 88],
        cumulative_return: -0.12,
        volatility: 0.2,
      },
    },
    portfolio_context: {
      current_position_tickers: ["WIN.SH", "LOSS.SH"],
      position_count: 2,
      sector_exposure: { battery: 0.05, consumer: 0.08 },
      theme_exposure: { ev_supply_chain: 0.05, premium_consumption: 0.08 },
      current_positions: [
        {
          ticker: "WIN.SH",
          market_price: 100,
          current_weight: 0.08,
          cost_basis: 90,
          holding_days: 30,
          unrealized_pnl_pct: 0.11,
          entry_thesis: "winner thesis",
        },
        {
          ticker: "LOSS.SH",
          market_price: 100,
          current_weight: 0.05,
          cost_basis: 110,
          holding_days: 45,
          unrealized_pnl_pct: -0.09,
          entry_thesis: "loss thesis",
        },
      ],
    },
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

class JsonLlm {
  captured: unknown[] = [];
  constructor(private readonly content: string) {}
  async invoke(messages: unknown[]) {
    this.captured = messages;
    return { content: this.content };
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
const jsonDeps = (api: BridgeApi, content: string) => ({ llm: new JsonLlm(content) as never, api });

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

  it("fake-llm emits portfolio reviews for current positions", async () => {
    let captured: unknown = null;
    const api = fakeApi({
      mirofishScoreRecommendation: vi.fn().mockImplementation(async (p: unknown) => {
        captured = (p as { recommendation: unknown }).recommendation;
        return { score: 0.8 };
      }),
      mirofishGenerateScenarios: vi
        .fn()
        .mockResolvedValue({ scenarios: [scenarioWithCurrentPositions()] }),
    });
    await runMirofishTraining({ agents: ["x"], fakeLlm: true, deps: deps(api) });
    expect(captured).toMatchObject({
      position_reviews: [
        { ticker: "WIN.SH", decision: "ADD", current_weight: 0.08, target_weight: 0.1 },
        { ticker: "LOSS.SH", decision: "EXIT", current_weight: 0.05, target_weight: 0 },
      ],
      portfolio_actions: [
        { ticker: "WIN.SH", action: "BUY", current_weight: 0.08, target_weight: 0.1 },
        { ticker: "LOSS.SH", action: "SELL", current_weight: 0.05, target_weight: 0 },
      ],
    });
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

  it("passes current position stress inputs through to scenario generation", async () => {
    const api = fakeApi();
    await runMirofishTraining({
      agents: ["x"],
      seed: 7,
      fakeLlm: true,
      currentPositions: [
        {
          ticker: "600519.SH",
          market_price: 1680,
          current_weight: 0.08,
          cost_basis: 1500,
          holding_days: 42,
          unrealized_pnl_pct: 0.12,
          entry_thesis: "premium moat thesis",
        },
        {
          ticker: "300750.SZ",
          current_price: 190,
          current_weight: 0.05,
          holding_days: 12,
        },
        {
          ticker: "688981.SH",
          market_price: 58,
          current_weight: 0.03,
          unrealized_pnl_pct: -0.06,
        },
      ],
      sectorExposure: { consumer: 0.08, battery: 0.05 },
      themeExposure: { premium_consumption: 0.08, ev_supply_chain: 0.05 },
      deps: deps(api),
    });

    expect(api.mirofishGenerateScenarios).toHaveBeenCalledWith({
      num_days: 30,
      seed: 7,
      current_positions: [
        {
          ticker: "600519.SH",
          market_price: 1680,
          current_weight: 0.08,
          cost_basis: 1500,
          holding_days: 42,
          unrealized_pnl_pct: 0.12,
          entry_thesis: "premium moat thesis",
        },
        {
          ticker: "300750.SZ",
          current_price: 190,
          current_weight: 0.05,
          holding_days: 12,
        },
        {
          ticker: "688981.SH",
          market_price: 58,
          current_weight: 0.03,
          unrealized_pnl_pct: -0.06,
        },
      ],
      sector_exposure: { consumer: 0.08, battery: 0.05 },
      theme_exposure: { premium_consumption: 0.08, ev_supply_chain: 0.05 },
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

  it("parses provider JSON with trailing prose for real-LLM recommendations", async () => {
    const rec = parseRecommendationResponse(
      '{"recommendation":"BUY","tickers":["000300.SH"],"conviction":0.75,"reasoning":"up path"}\n\n结论：买入',
      scenario("bull", 0.12),
    );
    expect(rec).toEqual({
      recommendation: "BUY",
      tickers: ["000300.SH"],
      conviction: 0.75,
      reasoning: "up path",
    });
  });

  it("normalizes Chinese action/ticker fields in real-LLM recommendations", () => {
    const rec = parseRecommendationResponse(
      '{"操作":"买入","标的":"000300.SH","置信度":"80%","理由":"上涨路径最强"}',
      scenario("bull", 0.12),
    );
    expect(rec).toMatchObject({
      recommendation: "BUY",
      tickers: ["000300.SH"],
      conviction: 0.8,
      reasoning: "上涨路径最强",
    });
  });

  it("scores a non-fake JSON recommendation without structured-output support", async () => {
    const api = fakeApi({
      mirofishGenerateScenarios: vi.fn().mockResolvedValue({ scenarios: [scenario("bull", 0.15)] }),
    });
    await runMirofishTraining({
      agents: ["druckenmiller"],
      dryRun: true,
      deps: jsonDeps(
        api,
        '```json\n{"action":"long","ticker":"000300.SH","confidence":0.7,"reason":"trend"}\n```',
      ),
    });
    expect(api.mirofishScoreRecommendation).toHaveBeenCalledWith(
      expect.objectContaining({
        recommendation: {
          recommendation: "BUY",
          tickers: ["000300.SH"],
          conviction: 0.7,
          reasoning: "trend",
        },
      }),
    );
  });

  it("includes current positions and exposure context in real-LLM prompt", async () => {
    const api = fakeApi({
      mirofishGenerateScenarios: vi
        .fn()
        .mockResolvedValue({ scenarios: [scenarioWithCurrentPositions()] }),
    });
    const llm = new JsonLlm(
      '{"recommendation":"HOLD","tickers":[],"conviction":0.5,"reasoning":"review positions"}',
    );
    await runMirofishTraining({
      agents: ["cio"],
      dryRun: true,
      deps: { llm: llm as never, api },
    });
    const user = llm.captured[1] as { content?: unknown } | undefined;
    const content = typeof user?.content === "string" ? user.content : JSON.stringify(user);
    expect(content).toContain("Current positions:");
    expect(content).toContain("WIN.SH");
    expect(content).toContain("Portfolio exposure:");
    expect(content).toContain("sector_exposure: battery=0.0500, consumer=0.0800");
    expect(content).toContain("theme_exposure: ev_supply_chain=0.0500, premium_consumption=0.0800");
  });
});

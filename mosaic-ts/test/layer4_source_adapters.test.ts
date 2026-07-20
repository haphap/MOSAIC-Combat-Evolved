import { describe, expect, it, vi } from "vitest";
import {
  mergeRuntimeSourceStatuses,
  parseLatestMarketRecord,
  resolveLayer4SourceBundle,
  resolveLayer4SourceStatuses,
} from "../src/agents/helpers/layer4_source_adapters.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { BridgeApi } from "../src/bridge/index.js";

function sourceState(): DailyCycleStateType {
  return {
    active_cohort: "cohort_default",
    as_of_date: "2026-07-09",
    mode: "backtest",
    trace_id: "run-1",
    layer1_outputs: {},
    layer2_outputs: {},
    layer3_outputs: {
      munger: {
        picks: [{ ticker: "600519.SH" }, { ticker: "000001.SZ" }, { ticker: "300750.SZ" }],
      },
    },
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
      position_snapshot_hash: `sha256:${"0".repeat(64)}`,
      positions: [],
    },
  } as unknown as DailyCycleStateType;
}

describe("Layer 4 runtime source adapters", () => {
  it("normalizes the latest quoted CSV market row", () => {
    expect(
      parseLatestMarketRecord(
        'Stock data\ndate,close,volume,note\n2026-07-08,12,100,"old,row"\n2026-07-09,13.5,120,"new,row"',
      ),
    ).toEqual({
      asOf: "2026-07-09",
      value: {
        date: "2026-07-09",
        close: 13.5,
        volume: 120,
        note: "new,row",
      },
    });
  });

  it("keeps loaded, stale, and failed ticker scopes separate", async () => {
    const runtimeStockMarketSnapshot = vi.fn(async (args: Record<string, unknown>) => {
      if (args.ticker === "600519.SH") return { text: "date,close\n2026-07-09,1500" };
      if (args.ticker === "000001.SZ") return { text: "date,close\n2026-07-08,12" };
      throw new Error("source unavailable");
    });

    const statuses = await resolveLayer4SourceStatuses(sourceState(), "pre_candidate", {
      runtimeStockMarketSnapshot,
    } as Pick<BridgeApi, "runtimeStockMarketSnapshot">);

    expect(statuses).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source_id: "current_market_data",
          scope: "ticker:600519.SH",
          status: "loaded",
          as_of: "2026-07-09",
          adapter_id: "market.scoped_snapshot_adapter.v1",
        }),
        expect.objectContaining({
          scope: "ticker:000001.SZ",
          status: "stale",
          as_of: "2026-07-08",
        }),
        expect.objectContaining({
          scope: "ticker:300750.SZ",
          status: "source_error",
          error_code: "current_market_data_tool_failed",
        }),
      ]),
    );
    expect(runtimeStockMarketSnapshot).toHaveBeenCalledTimes(3);
  });

  it("resolves candidate liquidity from the real stock-data adapter", async () => {
    const state = sourceState();
    state.layer4_outputs = {
      ...state.layer4_outputs,
      runtime: {
        cio_proposal: null,
        position_review_state: null,
        portfolio_exposure_state: null,
        cro_review_state: null,
        execution_feasibility_state: null,
        final_target_state: null,
        cio_final_knob_snapshot: null,
        resolved_source_statuses: [],
        stage_trace: [],
        candidate_target_state: {
          portfolio_actions: [
            {
              ticker: "600519.SH",
              action: "BUY",
              target_weight: 0.1,
              holding_period: "1M",
              dissent_notes: "",
            },
          ],
        },
      },
    } as unknown as DailyCycleStateType["layer4_outputs"];
    const runtimeStockMarketSnapshot = vi.fn(async () => ({
      text: "trade_date,close,volume\n20260709,1500,1200",
    }));

    const statuses = await resolveLayer4SourceStatuses(state, "execution_liquidity", {
      runtimeStockMarketSnapshot,
    } as Pick<BridgeApi, "runtimeStockMarketSnapshot">);

    expect(statuses).toContainEqual(
      expect.objectContaining({
        source_id: "execution_liquidity_state",
        scope: "ticker:600519.SH",
        status: "loaded",
        adapter_id: "execution.liquidity_adapter.v1",
      }),
    );
  });

  it("does not refresh a base market scope after the L4 bundle freezes it", async () => {
    const state = sourceState();
    state.layer3_outputs.munger = { picks: [{ ticker: "600519.SH" }] } as never;
    const frozenStatus = {
      source_id: "current_market_data",
      scope: "ticker:600519.SH",
      status: "stale" as const,
      as_of: "2026-07-08",
      snapshot_hash: `sha256:${"1".repeat(64)}`,
    };
    state.layer4_outputs.runtime = {
      l4_run_snapshot_bundle: {
        base_market_source_hashes: {
          "current_market_data|ticker:600519.SH": `sha256:${"2".repeat(64)}`,
        },
      },
      resolved_source_statuses: [frozenStatus],
      source_evidence_observations: [],
    } as never;
    const runtimeStockMarketSnapshot = vi.fn();

    const statuses = await resolveLayer4SourceStatuses(state, "candidate_market", {
      runtimeStockMarketSnapshot,
    } as Pick<BridgeApi, "runtimeStockMarketSnapshot">);

    expect(statuses).toEqual([frozenStatus]);
    expect(runtimeStockMarketSnapshot).not.toHaveBeenCalled();
  });

  it("retains normalized evidence separately from source status", async () => {
    const bundle = await resolveLayer4SourceBundle(sourceState(), "pre_candidate", {
      runtimeStockMarketSnapshot: vi.fn(async () => ({
        text: "date,close,volume\n2026-07-09,1500,1200",
      })),
    } as Pick<BridgeApi, "runtimeStockMarketSnapshot">);

    expect(bundle.evidence).toContainEqual(
      expect.objectContaining({
        source_id: "current_market_data",
        scope: "ticker:600519.SH",
        metric: "current_market_data",
        value: { date: "2026-07-09", close: 1500, volume: 1200 },
        freshness: "current",
        adapter_id: "market.scoped_snapshot_adapter.v1",
        source_fingerprint: expect.stringMatching(/^sha256:[0-9a-f]{64}$/),
      }),
    );
  });

  it("replaces only the matching source and scope", () => {
    const merged = mergeRuntimeSourceStatuses(
      [
        { source_id: "current_market_data", scope: "ticker:A", status: "missing" },
        { source_id: "current_market_data", scope: "ticker:B", status: "loaded" },
      ],
      [{ source_id: "current_market_data", scope: "ticker:A", status: "loaded" }],
    );

    expect(merged).toEqual([
      { source_id: "current_market_data", scope: "ticker:A", status: "loaded" },
      { source_id: "current_market_data", scope: "ticker:B", status: "loaded" },
    ]);
  });
});

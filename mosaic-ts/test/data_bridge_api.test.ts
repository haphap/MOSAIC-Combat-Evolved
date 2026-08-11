import { describe, expect, it, vi } from "vitest";
import { BridgeApi, type BridgeClient } from "../src/bridge/index.js";

describe("Agent data materialization bridge wrappers", () => {
  it("routes status and dry-run calls through read-only RPC methods", async () => {
    const call = vi.fn().mockResolvedValue({ status: "BLOCKED" });
    const api = new BridgeApi({ call } as unknown as BridgeClient);

    await api.dataSourceStatus({ as_of: "2026-07-01", route_id: "tushare.eco_cal.cny" });
    await api.dataSourceBackfill({
      route_id: "tushare.a_share_breadth",
      from: "2026-07-01",
      to: "2026-07-02",
      historical_replay: true,
    });
    await api.dataEarliestReadyDate({ all_agents: true });
    await api.dataSnapshotStatus({ as_of: "2026-07-01", agent_id: "china", stage: "china" });
    await api.dataMaterializeDryRun({
      as_of: "2026-07-01",
      agent_id: "china",
      stage: "china",
      dry_run: true,
    });
    await api.dataMaterializeCycleDryRun({
      as_of: "2026-07-01",
      all_agents: true,
      dry_run: true,
    });

    expect(call.mock.calls).toEqual([
      ["data.source_status", { as_of: "2026-07-01", route_id: "tushare.eco_cal.cny" }],
      [
        "data.source_backfill",
        {
          route_id: "tushare.a_share_breadth",
          from: "2026-07-01",
          to: "2026-07-02",
          historical_replay: true,
        },
      ],
      ["data.earliest_ready_date", { all_agents: true }],
      ["data.snapshot_status", { as_of: "2026-07-01", agent_id: "china", stage: "china" }],
      [
        "data.materialize_dry_run",
        { as_of: "2026-07-01", agent_id: "china", stage: "china", dry_run: true },
      ],
      ["data.materialize_cycle_dry_run", { as_of: "2026-07-01", all_agents: true, dry_run: true }],
    ]);
  });

  it("routes cycle lifecycle calls without caller-supplied authority hashes", async () => {
    const call = vi.fn().mockResolvedValue({ status: "OPEN" });
    const api = new BridgeApi({ call } as unknown as BridgeClient);
    const state = { trace_id: "daily-run-1" };

    await api.dataCycleOpen({
      as_of: "2026-07-01",
      run_id: "daily-run-1",
      cohort: "cohort_default",
      mode: "enforce",
      cycle_kind: "PRODUCTION",
      lease_seconds: 3600,
    });
    await api.dataCycleCommit({ state });
    await api.dataCycleAbort({ run_id: "daily-run-2", reason: "STAGE_FAILURE" });

    expect(call.mock.calls).toEqual([
      [
        "data.cycle_open",
        {
          as_of: "2026-07-01",
          run_id: "daily-run-1",
          cohort: "cohort_default",
          mode: "enforce",
          cycle_kind: "PRODUCTION",
          lease_seconds: 3600,
        },
      ],
      ["data.cycle_commit", { state }],
      ["data.cycle_abort", { run_id: "daily-run-2", reason: "STAGE_FAILURE" }],
    ]);
  });
});

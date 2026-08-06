import { describe, expect, it, vi } from "vitest";
import { BridgeApi, type BridgeClient } from "../src/bridge/index.js";

describe("Agent data materialization bridge wrappers", () => {
  it("routes status and dry-run calls through read-only RPC methods", async () => {
    const call = vi.fn().mockResolvedValue({ status: "BLOCKED" });
    const api = new BridgeApi({ call } as unknown as BridgeClient);

    await api.dataSourceStatus({ as_of: "2026-07-01", route_id: "tushare.eco_cal.cny" });
    await api.dataSnapshotStatus({ as_of: "2026-07-01", agent_id: "china", stage: "china" });
    await api.dataMaterializeDryRun({
      as_of: "2026-07-01",
      agent_id: "china",
      stage: "china",
      dry_run: true,
    });

    expect(call.mock.calls).toEqual([
      ["data.source_status", { as_of: "2026-07-01", route_id: "tushare.eco_cal.cny" }],
      ["data.snapshot_status", { as_of: "2026-07-01", agent_id: "china", stage: "china" }],
      [
        "data.materialize_dry_run",
        { as_of: "2026-07-01", agent_id: "china", stage: "china", dry_run: true },
      ],
    ]);
  });
});

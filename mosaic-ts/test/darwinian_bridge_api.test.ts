import { describe, expect, it, vi } from "vitest";
import { BridgeApi, type BridgeClient } from "../src/bridge/index.js";

describe("Darwinian v2 outcome bridge wrappers", () => {
  it("routes materialize, refresh, and publish through their typed RPC methods", async () => {
    const call = vi.fn().mockResolvedValue({});
    const api = new BridgeApi({ call } as unknown as BridgeClient);
    const params = {
      production_variant_roster_revision_id: "roster-revision-v2",
      cutoff_at: "2026-07-17T15:00:00+08:00",
    };

    await api.darwinianMaterializeDueOutcomes(params);
    await api.darwinianRefreshV2Windows(params);
    await api.darwinianPublishV2Updates(params);

    expect(call.mock.calls).toEqual([
      ["darwinian.materialize_due_outcomes", params],
      ["darwinian.refresh_v2_windows", params],
      ["darwinian.publish_v2_updates", params],
    ]);
  });
});

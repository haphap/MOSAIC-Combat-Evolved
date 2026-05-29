import { describe, expect, it } from "vitest";
import {
  BridgeApi,
  BridgeClient,
  BridgeTransportError,
  INVALID_PARAMS,
  METHOD_NOT_FOUND,
  PAPER_ERROR,
  RpcError,
} from "../src/bridge/index.js";

/**
 * Black-box client tests. They drive the real `mosaic.bridge` subprocess,
 * proving that the TS client's framing, correlation, error mapping, and
 * shutdown semantics line up with the Python server.
 *
 * Phase 0 surface: ≥8 macro tools registered; paper.* / backtest.* handlers
 * registered but degrade to PAPER_ERROR / BACKTEST_ERROR until Phase 8.
 */

describe("BridgeClient against real sidecar", () => {
  it("correlates concurrent requests by id", async () => {
    const client = new BridgeClient();
    try {
      await client.start();
      // Fire all four in parallel — the client must demux responses back to
      // the correct promise. Using only Phase-0 stable methods.
      const [list, cfg, stats, defaultCfg] = await Promise.all([
        client.call<unknown[]>("tools.list", {}),
        client.call<Record<string, unknown>>("config.get", {}),
        client.call<Record<string, unknown>>("cache.stats", {}),
        client.call<Record<string, unknown>>("config.default", {}),
      ]);
      expect(Array.isArray(list)).toBe(true);
      expect(list.length).toBeGreaterThanOrEqual(8); // Phase 0 macro_tools surface
      expect(cfg.llm_provider).toBeTypeOf("string");
      expect(stats.total_mb).toBeTypeOf("number");
      // MOSAIC-specific defaults from Plan §1
      expect(defaultCfg.llm_provider).toBe("anthropic");
      expect(defaultCfg.output_language).toBe("Chinese");
      expect(defaultCfg.active_cohort).toBe("euphoria_2021");
    } finally {
      await client.close();
    }
  });

  it("maps {error} envelope to RpcError with code/method", async () => {
    const client = new BridgeClient();
    try {
      await client.start();
      await expect(client.call("does.not.exist", {})).rejects.toMatchObject({
        name: "RpcError",
        code: METHOD_NOT_FOUND,
        method: "does.not.exist",
      });
    } finally {
      await client.close();
    }
  });

  it("maps invalid-params errors per JSON-RPC spec", async () => {
    const client = new BridgeClient();
    try {
      await client.start();
      const err = await client.call("tools.call", { args: {} }).catch((e) => e);
      expect(err).toBeInstanceOf(RpcError);
      expect((err as RpcError).code).toBe(INVALID_PARAMS);
    } finally {
      await client.close();
    }
  });

  it("times out a call when timeoutMs is short", async () => {
    const client = new BridgeClient();
    try {
      await client.start();
      // Use a 1ms timeout to force a timeout regardless of how fast Python
      // would normally respond.
      await expect(client.call("tools.list", {}, { timeoutMs: 1 })).rejects.toBeInstanceOf(
        BridgeTransportError,
      );
    } finally {
      await client.close();
    }
  });

  it("paper.* is registered but degrades to PAPER_ERROR until Phase 8", async () => {
    const client = new BridgeClient();
    try {
      await client.start();
      const err = await client.call("paper.current_user", {}).catch((e) => e);
      expect(err).toBeInstanceOf(RpcError);
      expect((err as RpcError).code).toBe(PAPER_ERROR);
      expect((err as RpcError).message).toMatch(/Phase 8/);
    } finally {
      await client.close();
    }
  });

  it("BridgeApi ergonomic helpers cover the same surface", async () => {
    const client = new BridgeClient();
    const api = new BridgeApi(client);
    try {
      await client.start();
      const tools = await api.toolsList();
      expect(tools.length).toBeGreaterThanOrEqual(8);
      const stats = await api.cacheStats();
      expect(stats.total_mb).toBeTypeOf("number");
      const cfg = await api.configGet();
      expect(cfg.data_vendors).toBeDefined();
    } finally {
      await client.close();
    }
  });

  it("Phase 3D scorecard / darwinian wrappers reach a live bridge", async () => {
    const client = new BridgeClient();
    const api = new BridgeApi(client);
    try {
      await client.start();
      // Empty cohort: list_skill returns no rows, get_weights returns empty table.
      const skill = await api.scorecardListSkill("test_cohort_phase3d_unused");
      expect(skill.rows).toEqual([]);
      const weights = await api.darwinianGetWeights("test_cohort_phase3d_unused");
      expect(weights.weights).toEqual({});

      // score_pending on empty cohort returns zero counts (idempotent).
      const scoreOutcome = await api.scorecardScorePending(
        "test_cohort_phase3d_unused",
        "2024-07-01",
      );
      expect(scoreOutcome.scored).toBe(0);
      expect(scoreOutcome.skipped_immature).toBe(0);
      expect(scoreOutcome.skipped_missing).toBe(0);

      // compute on empty cohort: no rows written.
      const computeOutcome = await api.darwinianCompute("test_cohort_phase3d_unused", "2024-07-01");
      expect(computeOutcome.written).toBe(0);
    } finally {
      await client.close();
    }
  });
});

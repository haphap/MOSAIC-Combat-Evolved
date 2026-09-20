import { describe, expect, it, vi } from "vitest";
import {
  buildDailyCycleRkeFootprintRows,
  captureDailyCycleRkeFootprints,
} from "../src/agents/rke_footprints.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { BridgeApi } from "../src/bridge/types.js";
import { computeAgentSkillWeights } from "../src/cli/commands/rke-darwinian-compute.js";

describe("RKE footprint capture helpers", () => {
  it("captures output diagnostics without querying a post-run research context", async () => {
    const api = {
      rkeAgentResearchContext: vi.fn().mockRejectedValue(new Error("must not query after run")),
      rkeBenchmarkCaptureAgentClaimFootprints: vi.fn().mockResolvedValue({ captured_count: 1 }),
    } as unknown as BridgeApi;
    const state = {
      trace_id: "cycle-1",
      as_of_date: "2026-06-18",
      layer1_outputs: {
        us_financial_conditions: {
          agent: "us_financial_conditions",
          confidence: 0.7,
          key_drivers: ["private report prose"],
          claim_text: "private report prose",
          rke_context_hash: "a".repeat(64),
          current_data_confirmed: true,
        },
      },
    } as unknown as DailyCycleStateType;

    const result = await captureDailyCycleRkeFootprints(api, state);

    expect(result).toEqual({ captured_count: 1 });
    expect(api.rkeAgentResearchContext).not.toHaveBeenCalled();
    expect(api.rkeBenchmarkCaptureAgentClaimFootprints).toHaveBeenCalledExactlyOnceWith({
      benchmark_run_id: "cycle-1",
      rows: [
        {
          agent: "us_financial_conditions",
          layer: "macro",
          as_of_date: "2026-06-18",
          claim_type: "macro_regime_claim",
          target: { target_type: "macro", target_id: "us_financial_conditions" },
          confidence_bucket: "high",
          rke_prior_usage_quality: "not_evaluated",
          current_data_confirmed: false,
          stale_prior_rejected: false,
          contradictory_prior_handled: false,
          reason_codes: ["daily_cycle_runtime_capture", "rke_runtime_usage_unverified"],
          failure_mode_tags: [],
        },
      ],
    });
  });

  it("keeps run identifiers without granting RKE usage credit to completed outputs", () => {
    const state = {
      as_of_date: "2026-06-18",
      layer1_outputs: { us_financial_conditions: { confidence: 0.7 } },
    } as unknown as DailyCycleStateType;

    const rows = buildDailyCycleRkeFootprintRows(state, {
      replayRunId: "replay-1",
      episodeId: "episode-1",
      modelConfigId: "local_qwen_27b",
    });

    expect(rows[0]).toMatchObject({
      replay_run_id: "replay-1",
      episode_id: "episode-1",
      model_config_id: "local_qwen_27b",
      current_data_confirmed: false,
      rke_prior_usage_quality: "not_evaluated",
    });
    expect(rows[0]).not.toHaveProperty("rke_context_hash");
    expect(rows[0]).not.toHaveProperty("report_claim_refs");
    expect(rows[0]).not.toHaveProperty("tool_refs");
    const weights = computeAgentSkillWeights(rows, {});
    expect(weights.find((row) => row.agent === "us_financial_conditions")).toMatchObject({
      current_data_skill: 0,
      rke_prior_usage_skill: 0,
    });
  });

  it("does not persist footprints for an empty cycle", async () => {
    const api = {
      rkeAgentResearchContext: vi.fn(),
      rkeBenchmarkCaptureAgentClaimFootprints: vi.fn(),
    } as unknown as BridgeApi;
    const state = { as_of_date: "2026-06-18" } as DailyCycleStateType;

    expect(await captureDailyCycleRkeFootprints(api, state)).toBeNull();
    expect(api.rkeAgentResearchContext).not.toHaveBeenCalled();
    expect(api.rkeBenchmarkCaptureAgentClaimFootprints).not.toHaveBeenCalled();
  });
});

import { describe, expect, it } from "vitest";
import { buildDailyCycleRkeFootprintRows, parseRkeAudit } from "../src/agents/rke_footprints.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { BridgeApi } from "../src/bridge/types.js";

describe("RKE footprint capture helpers", () => {
  it("parses runtime audit header without source prose", () => {
    const audit = parseRkeAudit(
      [
        "Runtime preflight: runtime_preflight_status=ready; ranking_policy_id=rke_agent_research_context_rank_v1; context_hash=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; display_sort_policy=preserve_part1_retrieval_rank",
        "Runtime ranking audit: retrieval_ranks=1; priority_buckets=high; truncated_item_count=0; current_data_required=true",
        "",
        "### Prior forecast_claim:macro-usdcny-001",
      ].join("\n"),
    );

    expect(audit.rke_context_hash).toBe("a".repeat(64));
    expect(audit.retrieval_rank).toBe(1);
    expect(audit.priority_bucket).toBe("high");
    expect(audit.report_claim_refs).toEqual(["forecast_claim:macro-usdcny-001"]);
  });

  it("builds redacted rows and calls only the RKE context tool", async () => {
    const called: string[] = [];
    const api = {
      toolsCall: async (name: string) => {
        called.push(name);
        return {
          text: [
            "Runtime preflight: runtime_preflight_status=ready; ranking_policy_id=rke_agent_research_context_rank_v1; context_hash=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; display_sort_policy=preserve_part1_retrieval_rank",
            "Runtime ranking audit: retrieval_ranks=1; priority_buckets=high; truncated_item_count=0; current_data_required=true",
            "",
            "### Prior forecast_claim:macro-dollar-001",
          ].join("\n"),
        };
      },
    } as unknown as BridgeApi;
    const state = {
      as_of_date: "2026-06-18",
      layer1_outputs: {
        dollar: {
          agent: "dollar",
          confidence: 0.7,
          key_drivers: [],
          dxy_trend: "STABLE",
          cny_pressure: "LOW",
          dxy_cny_correlation: 0,
        },
      },
      layer2_outputs: {},
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
    } as unknown as DailyCycleStateType;

    const rows = await buildDailyCycleRkeFootprintRows(api, state);

    expect(called).toEqual(["get_rke_research_context"]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      agent: "dollar",
      claim_type: "macro_regime_claim",
      rke_context_hash: "b".repeat(64),
      ranking_policy_id: "rke_agent_research_context_rank_v1",
      current_data_confirmed: false,
    });
    expect(JSON.stringify(rows[0])).not.toContain("claim_text");
  });

  it("marks current data confirmed only when the producer opts in", async () => {
    const api = {
      toolsCall: async () => ({
        text: [
          "Runtime preflight: runtime_preflight_status=ready; ranking_policy_id=rke_agent_research_context_rank_v1; context_hash=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc; display_sort_policy=preserve_part1_retrieval_rank",
          "Runtime ranking audit: retrieval_ranks=1; priority_buckets=high; truncated_item_count=0; current_data_required=true",
          "",
          "### Prior forecast_claim:macro-dollar-002",
        ].join("\n"),
      }),
    } as unknown as BridgeApi;
    const state = {
      as_of_date: "2026-06-18",
      layer1_outputs: {
        dollar: {
          agent: "dollar",
          confidence: 0.7,
          key_drivers: [],
          dxy_trend: "STABLE",
          cny_pressure: "LOW",
          dxy_cny_correlation: 0,
        },
      },
      layer2_outputs: {},
      layer3_outputs: {},
      layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
    } as unknown as DailyCycleStateType;

    const rows = await buildDailyCycleRkeFootprintRows(api, state, {
      currentDataConfirmed: true,
      replayRunId: "replay-1",
      episodeId: "episode-1",
      modelConfigId: "local_qwen_27b",
    });

    expect(rows[0]).toMatchObject({
      replay_run_id: "replay-1",
      episode_id: "episode-1",
      model_config_id: "local_qwen_27b",
      current_data_confirmed: true,
      rke_prior_usage_quality: "used_ranked_prior",
      reason_codes: ["daily_cycle_runtime_capture", "formal_runtime_current_data_confirmed"],
    });
  });
});

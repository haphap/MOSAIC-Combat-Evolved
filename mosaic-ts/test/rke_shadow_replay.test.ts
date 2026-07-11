import { describe, expect, it, vi } from "vitest";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { BridgeApi, RkeDeliveryReadinessResult } from "../src/bridge/types.js";
import { buildRkeContextMetadataByAgent } from "../src/cli/commands/rke-fixed-benchmark.js";
import {
  assertReplayPrerequisitesReady,
  buildReplayEvidence,
  buildShadowReplayReadinessParams,
  collectReplayOutputRecords,
  runRkeShadowReplay,
} from "../src/cli/commands/rke-shadow-replay.js";

describe("rke-shadow-replay helpers", () => {
  it("records replay output hashes without output bodies", () => {
    const state = {
      layer1_outputs: { dollar: { agent: "dollar", confidence: 0.7 } },
      layer2_outputs: {},
      layer3_outputs: {},
      layer4_outputs: { cio: { agent: "cio", confidence: 0.4, portfolio_actions: [] } },
    } as unknown as DailyCycleStateType;

    const rows = collectReplayOutputRecords("bench-1", "replay-1", "2026-06-18", state);

    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      benchmark_run_id: "bench-1",
      replay_run_id: "replay-1",
      agent: "dollar",
      layer: "macro",
      prompt_pins: [],
    });
    expect(rows[0]?.output_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(JSON.stringify(rows)).not.toContain("confidence");
  });

  it("records replay prompt pins without prompt bodies", () => {
    const state = {
      layer1_outputs: { dollar: { agent: "dollar", confidence: 0.7 } },
      layer2_outputs: {},
      layer3_outputs: {},
      layer4_outputs: {},
    } as unknown as DailyCycleStateType;

    const rows = collectReplayOutputRecords(
      "bench-1",
      "replay-1",
      "2026-06-18",
      state,
      new Map([
        [
          "dollar",
          [
            {
              lang: "zh",
              prompt_repo_id: "private-prompts",
              prompt_repo_revision: "abc123",
              prompt_file_path: "cohort_default/macro/dollar.zh.md",
              prompt_sha256: "hash",
              prompt_contract_check_ref: "prompt-contract:hash",
            },
          ],
        ],
      ]),
    );

    expect(rows[0]?.prompt_pins).toEqual([
      {
        lang: "zh",
        prompt_repo_id: "private-prompts",
        prompt_repo_revision: "abc123",
        prompt_file_path: "cohort_default/macro/dollar.zh.md",
        prompt_sha256: "hash",
        prompt_contract_check_ref: "prompt-contract:hash",
      },
    ]);
    expect(JSON.stringify(rows)).not.toContain("prompt body");
  });

  it("records replay RKE context metadata from footprint rows", () => {
    const state = {
      layer1_outputs: { dollar: { agent: "dollar", confidence: 0.7 } },
      layer2_outputs: {},
      layer3_outputs: {},
      layer4_outputs: {},
    } as unknown as DailyCycleStateType;
    const contextByAgent = buildRkeContextMetadataByAgent([
      {
        agent: "dollar",
        as_of_date: "2024-01-02",
        claim_type: "macro_regime_claim",
        target: { target_type: "macro", target_id: "dollar" },
        rke_context_hash: "a".repeat(64),
        ranking_policy_id: "rke_agent_research_context_rank_v1",
        retrieval_rank: 1,
        priority_bucket: "high",
        truncated_item_count: 2,
        current_data_confirmed: true,
      },
    ]);

    const rows = collectReplayOutputRecords(
      "bench-1",
      "replay-1",
      "2024-01-02",
      state,
      undefined,
      contextByAgent,
    );

    expect(rows[0]?.rke_context).toEqual({
      rke_context_hashes: ["a".repeat(64)],
      ranking_policy_ids: ["rke_agent_research_context_rank_v1"],
      retrieval_ranks: [1],
      priority_buckets: ["high"],
      truncated_item_count_total: 2,
      current_data_confirmed: true,
    });
    expect(JSON.stringify(rows)).not.toContain("claim_text");
  });

  it("builds no-body replay evidence for shadow readiness", () => {
    const evidence = buildReplayEvidence("bench-1", "replay-1", {
      replayOutputCount: 25,
      replayFootprintCount: 25,
      privacyScanPassed: true,
      currentDataConfirmed: true,
    });

    expect(evidence).toMatchObject({
      benchmark_run_id: "bench-1",
      replay_run_id: "replay-1",
      replay_output_count: 25,
      replay_footprint_count: 25,
      privacy_scan_passed: true,
      current_data_confirmed: true,
    });
    expect(JSON.stringify(evidence)).not.toContain(".mosaic");
    expect(JSON.stringify(evidence)).not.toContain("claim_text");
  });

  it("binds replay evidence into the shadow readiness gate params", () => {
    const evidence = buildReplayEvidence("bench-1", "replay-1", {
      replayOutputCount: 25,
      replayFootprintCount: 25,
      privacyScanPassed: true,
      currentDataConfirmed: true,
    });

    expect(buildShadowReplayReadinessParams("bench-1", "cohort_default", evidence)).toEqual({
      benchmark_run_id: "bench-1",
      cohort: "cohort_default",
      replay_evidence: evidence,
    });
  });

  it("requires staged delivery evidence before replay starts", async () => {
    const api = {
      rkeBenchmarkDeliveryReadiness: vi
        .fn()
        .mockResolvedValue(readiness({ fixed_episode_benchmark: false })),
      promptsContractCheck: vi.fn(),
    };

    await expect(
      runRkeShadowReplay(api as unknown as BridgeApi, {
        benchmarkRunId: "bench-1",
        replayRunId: "replay-1",
        asOfDate: ["2026-06-18"],
      }),
    ).rejects.toThrow(
      "shadow replay prerequisites blocked: fixed_episode_benchmark:fixed_episode_benchmark_not_ready",
    );
    expect(api.promptsContractCheck).not.toHaveBeenCalled();
  });

  it("accepts ready replay prerequisites", () => {
    expect(() => assertReplayPrerequisitesReady(readiness())).not.toThrow();
  });
});

const prerequisiteIds = [
  "all_agent_prompt_provenance",
  "runtime_ranked_context_consumption",
  "fixed_episode_benchmark",
  "agent_profile_evolution",
  "darwinian_autoresearch_inputs",
  "darwinian_autoresearch_consumption",
  "prompt_mutation_release",
  "patch_activation",
  "rollback_evidence",
];

function readiness(blocked: Record<string, boolean> = {}): RkeDeliveryReadinessResult {
  const conditions = prerequisiteIds.map((conditionId) => {
    const ready = blocked[conditionId] !== false;
    return {
      condition_id: conditionId,
      status: ready ? "ready" : "blocked_preflight",
      ready,
      blocked_reasons: ready ? [] : [`${conditionId}_not_ready`],
      evidence_summary: {},
    };
  });
  return {
    schema_version: "rke_all_agent_delivery_readiness_v1",
    readiness_status: conditions.every((row) => row.ready) ? "ready" : "blocked_preflight",
    benchmark_run_id: "bench-1",
    cohort: "cohort_default",
    condition_count: conditions.length,
    ready_condition_count: conditions.filter((row) => row.ready).length,
    blocked_reasons: conditions.flatMap((row) => row.blocked_reasons),
    conditions,
    recorded_evidence_loaded: true,
    delivery_input_failures: [],
    delivery_ready: conditions.every((row) => row.ready),
    production_allowed: false,
    promotion_allowed: false,
  };
}

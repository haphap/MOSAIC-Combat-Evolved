import { describe, expect, it } from "vitest";
import {
  buildConsumptionEvidence,
  computeAgentSkillWeights,
} from "../src/cli/commands/rke-darwinian-compute.js";

describe("rke-darwinian-compute helpers", () => {
  it("computes bounded layer-local weights for all canonical agents", () => {
    const weights = computeAgentSkillWeights(
      [
        {
          agent: "dollar",
          layer: "macro",
          rke_context_hash: "a".repeat(64),
          rke_prior_usage_quality: "used_ranked_prior",
          current_data_confirmed: true,
          stale_prior_rejected: true,
        },
        {
          agent: "central_bank",
          layer: "macro",
          rke_context_hash: "b".repeat(64),
          rke_prior_usage_quality: "used_ranked_prior_unconfirmed",
          current_data_confirmed: false,
        },
        {
          agent: "munger",
          layer: "superinvestor",
          rke_context_hash: "c".repeat(64),
          rke_prior_usage_quality: "used_ranked_prior",
          current_data_confirmed: true,
          contradictory_prior_handled: true,
        },
        {
          agent: "burry",
          layer: "superinvestor",
          rke_context_hash: "d".repeat(64),
          rke_prior_usage_quality: "used_ranked_prior",
          current_data_confirmed: true,
          private_text_included: true,
        },
        {
          agent: "ackman",
          layer: "superinvestor",
          rke_context_hash: "e".repeat(64),
          rke_prior_usage_quality: "used_ranked_prior",
          current_data_confirmed: true,
          failure_mode_tags: ["schema_invalid"],
        },
      ],
      {
        risk_adjusted_return: 0.12,
        alpha: 0.03,
        max_drawdown: -0.04,
        turnover: 0.8,
        cost_bps: 12,
      },
    );

    expect(weights).toHaveLength(25);
    expect(weights.find((row) => row.agent === "dollar")?.weight).toBeGreaterThan(
      weights.find((row) => row.agent === "central_bank")?.weight ?? 0,
    );
    expect(weights.find((row) => row.agent === "central_bank")).toMatchObject({
      safety_capped: true,
      current_data_skill: 0,
    });
    expect(weights.find((row) => row.agent === "burry")?.safety_capped).toBe(true);
    expect(weights.find((row) => row.agent === "ackman")?.safety_capped).toBe(true);
    expect(weights.find((row) => row.agent === "burry")?.schema_contract_skill).toBe(0);
    expect(weights.find((row) => row.agent === "ackman")?.schema_contract_skill).toBe(0);
    expect(weights.find((row) => row.agent === "munger")?.safety_capped).toBe(false);
    expect(weights.find((row) => row.agent === "dollar")?.safety_capped).toBe(false);
    for (const layer of ["macro", "sector", "superinvestor", "decision"]) {
      const sum = weights
        .filter((row) => row.layer === layer)
        .reduce((acc, row) => acc + row.weight, 0);
      expect(sum).toBeCloseTo(1, 5);
    }
    expect(weights.some((row) => row.cold_start)).toBe(true);
  });

  it("builds no-body consumption evidence for the readiness gate", () => {
    const evidence = buildConsumptionEvidence(
      "bench-1",
      "replay-1",
      "rke-darwinian:bench-1:x",
      25,
      3,
    );

    expect(evidence).toMatchObject({
      benchmark_run_id: "bench-1",
      replay_run_id: "replay-1",
      agent_weight_count: 25,
      non_stub_weight_count: 3,
      layer_weight_sum_ready: true,
      darwinian_consumed: true,
      autoresearch_consumed: true,
      rke_prior_treated_as_current_data: false,
      production_weight_update_allowed: false,
    });
    expect(JSON.stringify(evidence)).not.toContain(".mosaic");
    expect(JSON.stringify(evidence)).not.toContain("claim_text");
  });
});

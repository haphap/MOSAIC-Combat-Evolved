import { describe, expect, it } from "vitest";
import {
  ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE,
  type DeterministicDecisionPolicyRelease,
} from "../src/agents/decision/deterministic_policy.js";
import {
  ExecutionActionValidationError,
  validateAutonomousExecutionActions,
} from "../src/agents/decision/execution_validator.js";
import type { AutoExecOutput } from "../src/agents/types.js";

function executionOutput(
  input: {
    requested?: number;
    executable?: number;
    costBps?: number;
    status?: "feasible" | "partial" | "blocked";
  } = {},
): AutoExecOutput {
  const requested = input.requested ?? 0.02;
  const status = input.status ?? "feasible";
  const executable = input.executable ?? (status === "blocked" ? 0 : Math.abs(requested));
  const tradeMagnitude = status === "feasible" ? Math.abs(requested) : executable;
  const costBps = input.costBps ?? 10;
  const ref = "order-intent-1";
  return {
    agent: "autonomous_execution",
    execution_disposition: status === "blocked" ? "BLOCKED" : "TRADES",
    trades:
      status === "blocked"
        ? []
        : [
            {
              order_intent_ref: ref,
              ticker: "600519.SH",
              action: requested > 0 ? "BUY" : "SELL",
              size_pct: tradeMagnitude,
              delta_weight: Math.sign(requested) * tradeMagnitude,
              estimated_slippage_pct: costBps / 10_000,
              conviction: 0.7,
            },
          ],
    execution_checks: [
      {
        order_intent_ref: ref,
        ticker: "600519.SH",
        requested_delta_weight: requested,
        status,
        estimated_cost_bps: costBps,
        max_executable_delta_weight: executable,
        reason: "deterministic fixture",
      },
    ],
    confidence: 0.7,
  };
}

function validate(output: AutoExecOutput) {
  return validateAutonomousExecutionActions({
    output,
    policy: ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE,
  });
}

describe("autonomous execution deterministic policy", () => {
  it("accepts a feasible trade and records the complete policy audit", () => {
    const result = validate(executionOutput());
    expect(result.trades[0]?.liquidity_score).toBe(1);
    expect(result.execution_enforcement).toEqual({
      checked_trade_count: 1,
      checked_assessment_count: 1,
      policy_release_id: ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE.policy_release_id,
      policy_release_hash: ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE.release_hash,
      active_policy_ids: [
        "autonomous_execution.liquidity_floor",
        "autonomous_execution.min_delta_trade_weight",
        "autonomous_execution.slippage_cap",
      ],
      min_delta_trade_weight: 0.01,
      slippage_cap: 0.003,
      liquidity_floor: 0.6,
      policy_blocked_order_intent_refs: [],
    });
    expect(validate(executionOutput({ executable: 0.05 })).trades[0]?.liquidity_score).toBe(1);
  });

  it("accepts the liquidity boundary and rejects a lower partial ratio", () => {
    expect(
      validate(executionOutput({ executable: 0.012, status: "partial" })).trades[0],
    ).toMatchObject({ liquidity_score: 0.6, delta_weight: 0.012 });
    expect(() => validate(executionOutput({ executable: 0.01, status: "partial" }))).toThrow(
      /liquidity_floor/,
    );
  });

  it("requires blocked status below the minimum trade size", () => {
    expect(() => validate(executionOutput({ requested: 0.005 }))).toThrow(/min_delta_trade_weight/);
  });

  it("requires blocked status above the slippage cap", () => {
    expect(() => validate(executionOutput({ costBps: 31 }))).toThrow(/slippage_cap/);
  });

  it("accepts policy-blocked assessments without manufacturing trades", () => {
    const result = validate(
      executionOutput({ requested: 0.005, executable: 0, costBps: 31, status: "blocked" }),
    );
    expect(result.trades).toEqual([]);
    expect(result.execution_enforcement?.policy_blocked_order_intent_refs).toEqual([
      "order-intent-1",
    ]);
    expect(() => validate(executionOutput({ executable: 0.001, status: "blocked" }))).toThrow(
      /zero executable delta/,
    );
  });

  it("rejects an authored audit or an invalid policy release", () => {
    const authored = executionOutput();
    authored.execution_enforcement = {
      checked_trade_count: 0,
      checked_assessment_count: 0,
      policy_release_id: "forged",
      policy_release_hash: "forged",
      active_policy_ids: [],
      min_delta_trade_weight: 0,
      slippage_cap: 0,
      liquidity_floor: 0,
      policy_blocked_order_intent_refs: [],
    };
    expect(() => validate(authored)).toThrow(/audit does not match policy/);

    const invalidPolicy = {
      ...ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE,
      release_hash: `sha256:${"0".repeat(64)}`,
    } as DeterministicDecisionPolicyRelease;
    expect(() =>
      validateAutonomousExecutionActions({ output: executionOutput(), policy: invalidPolicy }),
    ).toThrow(/policy release hash mismatch/);
  });

  it("rejects trades whose checked cost is not reflected in slippage", () => {
    const output = executionOutput();
    const trade = output.trades[0];
    if (!trade) throw new Error("fixture requires one trade");
    trade.estimated_slippage_pct = 0.002;
    expect(() => validate(output)).toThrow(ExecutionActionValidationError);
  });
});

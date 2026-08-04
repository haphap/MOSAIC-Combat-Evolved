import { canonicalJsonHash } from "../helpers/canonical_json.js";
import type { AutoExecOutput } from "../types.js";
import {
  type DeterministicDecisionPolicyRelease,
  validateDeterministicDecisionPolicyRelease,
} from "./deterministic_policy.js";

export class ExecutionActionValidationError extends Error {
  override readonly name = "ExecutionActionValidationError";
}

export function validateAutonomousExecutionActions(opts: {
  output: AutoExecOutput;
  policy: DeterministicDecisionPolicyRelease;
}): AutoExecOutput {
  const policy = validateDeterministicDecisionPolicyRelease(opts.policy);
  const values = policy.policies.autonomous_execution;
  const activePolicyIds = [
    "autonomous_execution.liquidity_floor",
    "autonomous_execution.min_delta_trade_weight",
    "autonomous_execution.slippage_cap",
  ];
  const liquidityByIntent = new Map<string, number>();
  const policyBlockedRefs: string[] = [];
  for (const check of opts.output.execution_checks ?? []) {
    const requestedMagnitude = Math.abs(check.requested_delta_weight ?? Number.NaN);
    if (!Number.isFinite(requestedMagnitude) || requestedMagnitude <= 1e-9) {
      throw new ExecutionActionValidationError(
        `${check.ticker}: execution policy requires a non-zero requested_delta_weight`,
      );
    }
    const executableMagnitude = check.max_executable_delta_weight ?? Number.NaN;
    if (
      !Number.isFinite(executableMagnitude) ||
      executableMagnitude < 0 ||
      executableMagnitude > 1 + 1e-9
    ) {
      throw new ExecutionActionValidationError(
        `${check.ticker}: execution policy requires a bounded executable delta`,
      );
    }
    if (check.status === "blocked" && executableMagnitude > 1e-9) {
      throw new ExecutionActionValidationError(
        `${check.ticker}: blocked assessment requires zero executable delta`,
      );
    }
    if (
      check.status === "partial" &&
      (executableMagnitude <= 1e-9 || executableMagnitude >= requestedMagnitude - 1e-9)
    ) {
      throw new ExecutionActionValidationError(
        `${check.ticker}: partial assessment requires executable delta below the request`,
      );
    }
    if (check.status === "feasible" && executableMagnitude + 1e-9 < requestedMagnitude) {
      throw new ExecutionActionValidationError(
        `${check.ticker}: feasible assessment cannot be below the requested delta`,
      );
    }
    const liquidityScore =
      check.status === "blocked" ? 0 : Math.min(1, executableMagnitude / requestedMagnitude);
    liquidityByIntent.set(check.order_intent_ref ?? "", liquidityScore);
    const triggered = [
      ...(requestedMagnitude + 1e-9 < values.min_delta_trade_weight
        ? ["autonomous_execution.min_delta_trade_weight"]
        : []),
      ...(check.estimated_cost_bps / 10_000 > values.slippage_cap + 1e-9
        ? ["autonomous_execution.slippage_cap"]
        : []),
      ...(liquidityScore + 1e-9 < values.liquidity_floor
        ? ["autonomous_execution.liquidity_floor"]
        : []),
    ];
    if (triggered.length > 0 && check.status !== "blocked") {
      throw new ExecutionActionValidationError(
        `${check.ticker}: execution policy requires blocked status (${triggered.sort().join(",")})`,
      );
    }
    if (triggered.length > 0 && check.order_intent_ref) {
      policyBlockedRefs.push(check.order_intent_ref);
    }
  }
  const trades = opts.output.trades.map((trade) => {
    const ref = trade.order_intent_ref ?? "";
    const check = (opts.output.execution_checks ?? []).find(
      (item) => item.order_intent_ref === ref,
    );
    const liquidityScore = liquidityByIntent.get(ref);
    if (!check || liquidityScore === undefined) {
      throw new ExecutionActionValidationError(
        `${trade.ticker}: execution trade lacks a policy-checked assessment`,
      );
    }
    if (
      trade.estimated_slippage_pct === undefined ||
      Math.abs(trade.estimated_slippage_pct - check.estimated_cost_bps / 10_000) > 1e-9
    ) {
      throw new ExecutionActionValidationError(
        `${trade.ticker}: trade slippage does not match the checked execution cost`,
      );
    }
    return { ...trade, liquidity_score: liquidityScore };
  });
  const enforcement = {
    checked_trade_count: trades.length,
    checked_assessment_count: (opts.output.execution_checks ?? []).length,
    policy_release_id: policy.policy_release_id,
    policy_release_hash: policy.release_hash,
    active_policy_ids: activePolicyIds,
    min_delta_trade_weight: values.min_delta_trade_weight,
    slippage_cap: values.slippage_cap,
    liquidity_floor: values.liquidity_floor,
    policy_blocked_order_intent_refs: [...new Set(policyBlockedRefs)].sort(),
  };
  if (
    opts.output.execution_enforcement &&
    canonicalJsonHash(opts.output.execution_enforcement) !== canonicalJsonHash(enforcement)
  ) {
    throw new ExecutionActionValidationError("execution enforcement audit does not match policy");
  }
  return {
    ...opts.output,
    trades,
    execution_enforcement: enforcement,
  };
}

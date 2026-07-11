import type { ResearchKnobsSnapshot } from "../helpers/research_knobs.js";
import type { AutoExecOutput } from "../types.js";

export class ExecutionActionValidationError extends Error {
  override readonly name = "ExecutionActionValidationError";
}

export function validateAutonomousExecutionActions(opts: {
  output: AutoExecOutput;
  knobSnapshot?: ResearchKnobsSnapshot | null;
}): AutoExecOutput {
  const minDelta = activeNumberKnob(opts.knobSnapshot, "min_delta_trade_weight");
  const slippageCap = activeNumberKnob(opts.knobSnapshot, "slippage_cap");
  const liquidityFloor = activeNumberKnob(opts.knobSnapshot, "liquidity_floor");
  const activePolicyIds = [
    ...(minDelta !== undefined ? ["min_delta_trade_weight"] : []),
    ...(slippageCap !== undefined ? ["slippage_cap"] : []),
    ...(liquidityFloor !== undefined ? ["liquidity_floor"] : []),
  ];

  for (const trade of opts.output.trades) {
    if (trade.action === "HOLD") continue;
    if (minDelta !== undefined) {
      const delta = Math.abs(trade.delta_weight ?? trade.size_pct);
      if (delta < minDelta) {
        throw new ExecutionActionValidationError(
          `${trade.ticker}: trade delta ${delta.toFixed(4)} below min_delta_trade_weight ${minDelta}`,
        );
      }
    }
    if (slippageCap !== undefined) {
      if (trade.estimated_slippage_pct === undefined) {
        throw new ExecutionActionValidationError(
          `${trade.ticker}: slippage_cap active but estimated_slippage_pct missing`,
        );
      }
      if (trade.estimated_slippage_pct > slippageCap) {
        throw new ExecutionActionValidationError(
          `${trade.ticker}: estimated_slippage_pct ${trade.estimated_slippage_pct.toFixed(4)} exceeds slippage_cap ${slippageCap}`,
        );
      }
    }
    if (liquidityFloor !== undefined) {
      if (trade.liquidity_score === undefined) {
        throw new ExecutionActionValidationError(
          `${trade.ticker}: liquidity_floor active but liquidity_score missing`,
        );
      }
      if (trade.liquidity_score < liquidityFloor) {
        throw new ExecutionActionValidationError(
          `${trade.ticker}: liquidity_score ${trade.liquidity_score.toFixed(4)} below liquidity_floor ${liquidityFloor}`,
        );
      }
    }
  }

  return {
    ...opts.output,
    execution_enforcement: {
      checked_trade_count: opts.output.trades.length,
      active_policy_ids: activePolicyIds,
      ...(minDelta !== undefined ? { min_delta_trade_weight: minDelta } : {}),
      ...(slippageCap !== undefined ? { slippage_cap: slippageCap } : {}),
      ...(liquidityFloor !== undefined ? { liquidity_floor: liquidityFloor } : {}),
    },
  };
}

function activeNumberKnob(
  snapshot: ResearchKnobsSnapshot | null | undefined,
  cardId: string,
): number | undefined {
  const value = snapshot?.consumptionSnapshot.active_knobs.find(
    (knob) => knob.card_id === cardId,
  )?.value;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

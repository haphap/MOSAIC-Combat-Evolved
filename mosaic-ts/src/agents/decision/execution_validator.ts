import type { AutoExecOutput } from "../types.js";

export class ExecutionActionValidationError extends Error {
  override readonly name = "ExecutionActionValidationError";
}

export function validateAutonomousExecutionActions(opts: {
  output: AutoExecOutput;
}): AutoExecOutput {
  return {
    ...opts.output,
    execution_enforcement: {
      checked_trade_count: opts.output.trades.length,
      active_policy_ids: [],
    },
  };
}

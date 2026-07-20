/**
 * autonomous_execution Layer-4.
 *
 * Reads the frozen CIO proposal, CRO controls, order intents, and execution
 * evidence; it does not directly consume Macro outputs or re-attribute them.
 *
 * Darwinian weights are applied before Layer 4 by the accepted-output usage
 * adapter. This decision role never receives raw weights, ranks, or records.
 */

import type { AcceptedAgentOutputStore } from "../accepted_output.js";
import type { DailyCycleStateType } from "../state.js";
import type { AutoExecOutput } from "../types.js";
import {
  buildLayerFourAgentNode,
  type LayerFourAgentDeps,
  type LayerFourAgentNode,
  type LayerFourAgentSpec,
} from "./_factory.js";
import { AUTONOMOUS_EXECUTION_FIELD_NAMES, AutonomousExecutionSchema } from "./_schemas.js";
import { renderLayer4PeerContext, renderLayer4RuntimeContext } from "./_user_context.js";
import type { AutonomousExecutionSubmission } from "./accepted.js";

const REQUIRED_TOOLS = ["get_execution_snapshot", "get_role_event_snapshot"] as const;

function buildUserContext(
  state: DailyCycleStateType,
  acceptedOutputStore?: AcceptedAgentOutputStore,
): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for autonomous_execution (Layer 4):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer4PeerContext(state, ["alpha_discovery", "autonomous_execution", "cio"], acceptedOutputStore)}\n\n` +
    `${renderLayer4RuntimeContext(state)}\n\n` +
    `Translate the frozen candidate target after applying cro's review into executable deltas ` +
    `with size_pct in [0, 1]. Do not reweight candidates by raw upstream Agent scores. ` +
    `HOLD with size_pct = 0 is fine for picks that are valid but ` +
    `already in the portfolio at target weight.`
  );
}

export const autonomousExecutionSpec: LayerFourAgentSpec<AutonomousExecutionSubmission> = {
  agentId: "autonomous_execution",
  runtimeStage: "execution_feasibility",
  schema: AutonomousExecutionSchema,
  fieldNames: AUTONOMOUS_EXECUTION_FIELD_NAMES,
  stateUpdateField: "autonomous_execution",
  requiredTools: REQUIRED_TOOLS,
  buildUserContext,
  render: renderAutonomousExecution,
};

export function buildAutonomousExecutionNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  return buildLayerFourAgentNode(autonomousExecutionSpec, deps);
}

export function renderAutonomousExecution(
  o: AutonomousExecutionSubmission | AutoExecOutput,
): string {
  if ("agent" in o) {
    const legacy = o.trades
      .map(
        (trade) =>
          `${trade.ticker}:${trade.action}@${trade.size_pct.toFixed(2)}(conv=${trade.conviction.toFixed(2)})`,
      )
      .join(" | ");
    return `autonomous_execution (confidence=${o.confidence.toFixed(2)})\n  trades: ${legacy || "(none)"}`;
  }
  const assessments = o.order_assessments
    .map(
      (assessment) =>
        `${assessment.ts_code}:${assessment.feasibility}@${assessment.requested_delta_weight.toFixed(4)}`,
    )
    .join(" | ");
  return (
    `autonomous_execution (confidence=${o.confidence.toFixed(2)})\n` +
    `  order_assessments: ${assessments}`
  );
}

export function fallbackAutonomousExecution(text: string): AutoExecOutput {
  void text;
  return {
    agent: "autonomous_execution",
    trades: [],
    execution_checks: [],
    confidence: 0,
  };
}

export { AUTONOMOUS_EXECUTION_FIELD_NAMES, AutonomousExecutionSchema };

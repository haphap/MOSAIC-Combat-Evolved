/**
 * autonomous_execution Layer-4 (Plan §5.4).
 * Reads L3 picks + L4 cro / alpha (peer L4 outputs); produces concrete
 * trade actions with size_pct + conviction. Darwinian weights stubbed
 * uniform 1/N until Phase 3 scorecard lands.
 */

import type { DailyCycleStateType } from "../state.js";
import type { AutoExecOutput } from "../types.js";
import {
  buildLayerFourAgentNode,
  type LayerFourAgentDeps,
  type LayerFourAgentNode,
  type LayerFourAgentSpec,
} from "./_factory.js";
import { AUTONOMOUS_EXECUTION_FIELD_NAMES, AutonomousExecutionSchema } from "./_schemas.js";
import {
  renderDarwinianWeightsStub,
  renderLayer3Context,
  renderLayer4PeerContext,
} from "./_user_context.js";

function buildUserContext(state: DailyCycleStateType): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for autonomous_execution (Layer 4):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer3Context(state)}\n\n` +
    `${renderLayer4PeerContext(state, ["autonomous_execution", "cio"])}\n\n` +
    `${renderDarwinianWeightsStub()}\n\n` +
    `Translate the Layer-3 picks (after subtracting cro's rejected_picks and ` +
    `optionally adding alpha_discovery's novel_picks) into concrete trade actions ` +
    `with size_pct in [0, 1]. Use uniform 1/N weights for now (Phase 3 will plug ` +
    `in real Darwinian weights). HOLD with size_pct = 0 is fine for picks that ` +
    `are valid but already in the portfolio at target weight.`
  );
}

export const autonomousExecutionSpec: LayerFourAgentSpec<AutoExecOutput> = {
  agentId: "autonomous_execution",
  schema: AutonomousExecutionSchema,
  fieldNames: AUTONOMOUS_EXECUTION_FIELD_NAMES,
  stateUpdateField: "autonomous_execution",
  buildUserContext,
  render: renderAutonomousExecution,
  fallback: fallbackAutonomousExecution,
};

export function buildAutonomousExecutionNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  return buildLayerFourAgentNode(autonomousExecutionSpec, deps);
}

export function renderAutonomousExecution(o: AutoExecOutput): string {
  const trades = o.trades
    .map((t) => `${t.ticker}:${t.action}@${t.size_pct.toFixed(2)}(conv=${t.conviction.toFixed(2)})`)
    .join(" | ");
  return (
    `autonomous_execution (confidence=${o.confidence.toFixed(2)})\n` +
    `  trades: ${trades || "(none)"}`
  );
}

export function fallbackAutonomousExecution(text: string): AutoExecOutput {
  void text;
  return {
    agent: "autonomous_execution",
    trades: [],
    confidence: 0,
  };
}

export { AUTONOMOUS_EXECUTION_FIELD_NAMES, AutonomousExecutionSchema };

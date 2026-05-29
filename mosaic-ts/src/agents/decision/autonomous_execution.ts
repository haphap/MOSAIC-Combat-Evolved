/**
 * autonomous_execution Layer-4 (Plan §5.4 + Plan §11.3 sub-step 3F).
 *
 * Reads L3 picks + L4 cro / alpha (peer L4 outputs); produces concrete
 * trade actions with size_pct + conviction.
 *
 * Phase 3F change: Darwinian weights are no longer a static stub. The
 * ``buildAutonomousExecutionNode`` factory wraps the static spec with a
 * deps-aware async ``buildUserContext`` that fetches per-agent weights
 * via ``deps.api.darwinianGetWeights``. When the bridge is unavailable,
 * weights have not been computed yet (empty cohort), or the call errors,
 * the renderer transparently falls back to the original stub — matching
 * the uniform 1.0 baseline that Phase 2 used.
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
  renderDarwinianWeights,
  renderDarwinianWeightsStub,
  renderLayer3Context,
  renderLayer4PeerContext,
} from "./_user_context.js";

/** Build the static portion of the user-context (peers + L3 picks). The
 *  Darwinian weights block is injected by the factory wrapper below. */
function buildBaseUserContext(state: DailyCycleStateType, weightsBlock: string): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for autonomous_execution (Layer 4):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer3Context(state)}\n\n` +
    `${renderLayer4PeerContext(state, ["autonomous_execution", "cio"])}\n\n` +
    `${weightsBlock}\n\n` +
    `Translate the Layer-3 picks (after subtracting cro's rejected_picks and ` +
    `optionally adding alpha_discovery's novel_picks) into concrete trade actions ` +
    `with size_pct in [0, 1]. Apply the Darwinian weights above as a per-agent ` +
    `multiplier when sizing each pick (an agent in quartile 1 gets more weight than ` +
    `quartile 4). HOLD with size_pct = 0 is fine for picks that are valid but ` +
    `already in the portfolio at target weight.`
  );
}

/** Synchronous fallback used by the static spec (and tests that don't
 *  want to mock the bridge). Always renders the stub. */
function buildUserContextSync(state: DailyCycleStateType): string {
  return buildBaseUserContext(state, renderDarwinianWeightsStub());
}

/** Async user-context: tries to fetch real Darwinian weights via the
 *  bridge; on any failure falls back to the stub block. */
async function buildUserContextWithWeights(
  state: DailyCycleStateType,
  deps: LayerFourAgentDeps,
): Promise<string> {
  if (!deps.api) {
    return buildUserContextSync(state);
  }
  const cohort = state.active_cohort || "cohort_default";
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);

  let weightsBlock = renderDarwinianWeightsStub();
  try {
    const result = await deps.api.darwinianGetWeights(cohort, date);
    weightsBlock = renderDarwinianWeights(result.weights, date);
  } catch (err) {
    deps.onLog?.(
      `autonomous_execution: darwinian.get_weights failed (${(err as Error).message}); ` +
        `falling back to uniform stub`,
    );
  }
  return buildBaseUserContext(state, weightsBlock);
}

export const autonomousExecutionSpec: LayerFourAgentSpec<AutoExecOutput> = {
  agentId: "autonomous_execution",
  schema: AutonomousExecutionSchema,
  fieldNames: AUTONOMOUS_EXECUTION_FIELD_NAMES,
  stateUpdateField: "autonomous_execution",
  // Static spec uses sync stub fallback; the factory below wraps this for
  // async deps-aware injection. Tests that import the spec directly still
  // get a working buildUserContext without bridge mocks.
  buildUserContext: buildUserContextSync,
  render: renderAutonomousExecution,
  fallback: fallbackAutonomousExecution,
};

export function buildAutonomousExecutionNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  // Per-instance spec that closes over deps.api so buildUserContext can
  // call the bridge for Darwinian weights. The static spec above retains
  // the sync stub for callers that don't go through this factory.
  const specWithWeights: LayerFourAgentSpec<AutoExecOutput> = {
    ...autonomousExecutionSpec,
    buildUserContext: (state) => buildUserContextWithWeights(state, deps),
  };
  return buildLayerFourAgentNode(specWithWeights, deps);
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

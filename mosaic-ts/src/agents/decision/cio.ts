/**
 * cio Layer-4 (Plan §5.4) — final portfolio decision.
 * Reads everything (L1+L2+L3 + cro + alpha + autonomous_execution +
 * JANUS regime stub) and emits portfolio_actions. Mirrors
 * portfolio_actions to top-level state via the factory's cio-special-case.
 */

import type { DailyCycleStateType } from "../state.js";
import type { CioOutput } from "../types.js";
import {
  buildLayerFourAgentNode,
  type LayerFourAgentDeps,
  type LayerFourAgentNode,
  type LayerFourAgentSpec,
} from "./_factory.js";
import { CIO_FIELD_NAMES, CioSchema } from "./_schemas.js";
import {
  renderJanusRegimeStub,
  renderLayer1Context,
  renderLayer2Context,
  renderLayer3Context,
  renderLayer4PeerContext,
} from "./_user_context.js";

function buildUserContext(state: DailyCycleStateType): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for cio (Layer 4 final decision):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer1Context(state)}\n` +
    `${renderLayer2Context(state)}\n` +
    `${renderLayer3Context(state)}\n` +
    `${renderLayer4PeerContext(state, ["cio"])}\n\n` +
    `${renderJanusRegimeStub()}\n\n` +
    `Synthesise the final portfolio. By default follow autonomous_execution's trades, ` +
    `but override when:\n` +
    `* cro flagged a black-swan that auto_exec didn't act on\n` +
    `* alpha_discovery surfaced a high-conviction novel pick that fits the regime\n` +
    `* total target_weight implied by auto_exec exceeds 100% (must rebalance down)\n` +
    `Every override needs a non-empty dissent_notes explaining why. ` +
    `target_weight should sum to 1.0 ± 0.05 unless intentionally holding cash ` +
    `(BEARISH regime + low confidence is the legitimate cash-holding case).`
  );
}

export const cioSpec: LayerFourAgentSpec<CioOutput> = {
  agentId: "cio",
  schema: CioSchema,
  fieldNames: CIO_FIELD_NAMES,
  stateUpdateField: "cio",
  buildUserContext,
  render: renderCio,
  fallback: fallbackCio,
};

export function buildCioNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  return buildLayerFourAgentNode(cioSpec, deps);
}

export function renderCio(o: CioOutput): string {
  const actions = o.portfolio_actions
    .map(
      (a) =>
        `${a.ticker}:${a.action}@w=${a.target_weight.toFixed(2)}(${a.holding_period})${a.dissent_notes ? "[d]" : ""}`,
    )
    .join(" | ");
  const totalWeight = o.portfolio_actions.reduce((sum, a) => sum + a.target_weight, 0);
  return (
    `cio (confidence=${o.confidence.toFixed(2)}, total_weight=${totalWeight.toFixed(2)})\n` +
    `  actions: ${actions || "(none — holding cash)"}`
  );
}

export function fallbackCio(text: string): CioOutput {
  void text;
  return {
    agent: "cio",
    portfolio_actions: [],
    confidence: 0,
  };
}

export { CIO_FIELD_NAMES, CioSchema };

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
  renderCurrentPositionsContext,
  renderJanusRegimeStub,
  renderLayer1Context,
  renderLayer2Context,
  renderLayer3Context,
  renderLayer4PeerContext,
  renderLayer4RuntimeContext,
  renderPreviousTargetContext,
} from "./_user_context.js";

const REQUIRED_TOOLS = ["get_rke_research_context"] as const;

function buildProposalUserContext(state: DailyCycleStateType): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for cio (Layer 4 proposal):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer1Context(state)}\n` +
    `${renderLayer2Context(state)}\n` +
    `${renderLayer3Context(state)}\n` +
    `${renderLayer4PeerContext(state, ["cro", "autonomous_execution", "cio"])}\n\n` +
    `${renderCurrentPositionsContext(state)}\n\n` +
    `${renderPreviousTargetContext(state)}\n\n` +
    `${renderJanusRegimeStub()}\n\n` +
    `Build the candidate target portfolio before CRO and execution review. Include every current ` +
    `position with a HOLD, ADD, REDUCE, or EXIT decision and consider alpha_discovery's novel picks. ` +
    `target_weight should sum to 1.0 ± 0.05 unless intentionally holding cash ` +
    `(BEARISH regime + low confidence is the legitimate cash-holding case).`
  );
}

function buildFinalUserContext(state: DailyCycleStateType): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for cio (Layer 4 final decision):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer4RuntimeContext(state)}\n\n` +
    `${renderLayer4PeerContext(state, ["alpha_discovery", "cio"])}\n\n` +
    `${renderCurrentPositionsContext(state)}\n\n` +
    `Start from the frozen candidate target. Apply CRO objections and execution feasibility; do not ` +
    `silently add a ticker that was absent from the candidate. Every change from the candidate needs ` +
    `a non-empty dissent_notes field. Return a complete final target for every current position.`
  );
}

export const cioProposalSpec: LayerFourAgentSpec<CioOutput> = {
  agentId: "cio",
  runtimeStage: "cio_proposal",
  stateWriteMode: "cio_proposal",
  schema: CioSchema,
  fieldNames: CIO_FIELD_NAMES,
  stateUpdateField: "cio",
  requiredTools: REQUIRED_TOOLS,
  buildUserContext: buildProposalUserContext,
  render: renderCio,
  fallback: fallbackCio,
};

export const cioSpec: LayerFourAgentSpec<CioOutput> = {
  ...cioProposalSpec,
  runtimeStage: "cio_final",
  stateWriteMode: "cio_final",
  buildUserContext: buildFinalUserContext,
};

export function buildCioProposalNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  return buildLayerFourAgentNode(cioProposalSpec, deps);
}

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

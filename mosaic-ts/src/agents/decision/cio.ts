/**
 * cio Layer-4 (Plan §5.4) — final portfolio decision.
 * Reads everything (L1+L2+L3 + cro + alpha + autonomous_execution +
 * JANUS regime stub) and emits portfolio_actions. Mirrors
 * portfolio_actions to top-level state via the factory's cio-special-case.
 */

import type { AcceptedAgentOutputStore } from "../accepted_output.js";
import { renderCausalEvidenceResolutionSet } from "../helpers/causal_evidence_resolution.js";
import type { DailyCycleStateType } from "../state.js";
import type { CioFinalOutput, CioOutput, CioProposalOutput } from "../types.js";
import {
  buildLayerFourAgentNode,
  type LayerFourAgentDeps,
  type LayerFourAgentNode,
  type LayerFourAgentSpec,
} from "./_factory.js";
import { CIO_FIELD_NAMES, CioFinalSchema, CioProposalSchema, CioSchema } from "./_schemas.js";
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
import type { CioFinalSubmission, CioProposalSubmission } from "./accepted.js";

const REQUIRED_TOOLS = ["get_cio_decision_snapshot"] as const;

function buildProposalUserContext(
  state: DailyCycleStateType,
  acceptedOutputStore?: AcceptedAgentOutputStore,
): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for cio (Layer 4 proposal):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer1Context(state, acceptedOutputStore)}\n` +
    `${renderLayer2Context(state, acceptedOutputStore)}\n` +
    `${renderLayer3Context(state, acceptedOutputStore)}\n` +
    `${renderCausalEvidenceResolutionSet({
      state,
      consumerAgentId: "cio",
      sourceLayers: ["MACRO", "SECTOR", "SUPERINVESTOR"],
      ...(acceptedOutputStore ? { acceptedOutputStore } : {}),
    })}\n` +
    `${renderLayer4PeerContext(state, ["cro", "autonomous_execution", "cio"], acceptedOutputStore)}\n\n` +
    `${renderCurrentPositionsContext(state)}\n\n` +
    `${renderPreviousTargetContext(state)}\n\n` +
    `${renderJanusRegimeStub()}\n\n` +
    `Build the candidate target portfolio before CRO and execution review. Include every current ` +
    `position with a HOLD, ADD, REDUCE, or EXIT decision and consider alpha_discovery's novel picks. ` +
    `target_weight must not exceed 1.0; a lower sum is intentional cash ` +
    `(BEARISH regime + low confidence is the legitimate cash-holding case).`
  );
}

function buildFinalUserContext(
  state: DailyCycleStateType,
  acceptedOutputStore?: AcceptedAgentOutputStore,
): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for cio (Layer 4 final decision):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer4RuntimeContext(state)}\n\n` +
    `${renderCausalEvidenceResolutionSet({
      state,
      consumerAgentId: "cio",
      sourceLayers: ["MACRO", "SECTOR", "SUPERINVESTOR"],
      ...(acceptedOutputStore ? { acceptedOutputStore } : {}),
    })}\n\n` +
    `${renderLayer4PeerContext(state, ["alpha_discovery", "cio"], acceptedOutputStore)}\n\n` +
    `${renderCurrentPositionsContext(state)}\n\n` +
    `Start from the frozen candidate target. Apply CRO objections and execution feasibility; do not ` +
    `silently add a ticker that was absent from the candidate. Every change from the candidate needs ` +
    `a non-empty dissent_notes field. Return a complete final target for every current position.`
  );
}

export const cioProposalSpec: LayerFourAgentSpec<CioProposalSubmission> = {
  agentId: "cio",
  runtimeStage: "cio_proposal",
  stateWriteMode: "cio_proposal",
  schema: CioProposalSchema,
  fieldNames: CIO_FIELD_NAMES,
  stateUpdateField: "cio",
  requiredTools: REQUIRED_TOOLS,
  buildUserContext: buildProposalUserContext,
  render: renderCio,
};

export const cioSpec: LayerFourAgentSpec<CioFinalSubmission> = {
  agentId: "cio",
  runtimeStage: "cio_final",
  stateWriteMode: "cio_final",
  schema: CioFinalSchema,
  fieldNames: CIO_FIELD_NAMES,
  stateUpdateField: "cio",
  requiredTools: REQUIRED_TOOLS,
  buildUserContext: buildFinalUserContext,
  render: renderCio,
};

export function buildCioProposalNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  return buildLayerFourAgentNode(cioProposalSpec, deps);
}

export function buildCioNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  return buildLayerFourAgentNode(cioSpec, deps);
}

export function renderCio(o: CioProposalSubmission | CioFinalSubmission | CioOutput): string {
  if ("agent" in o) {
    const legacy = o.portfolio_actions
      .map(
        (action) =>
          `${action.ticker}:${action.action}@w=${action.target_weight.toFixed(2)}(${action.holding_period})${action.dissent_notes ? "[d]" : ""}`,
      )
      .join(" | ");
    const total = o.portfolio_actions.reduce((sum, action) => sum + action.target_weight, 0);
    return `cio (confidence=${o.confidence.toFixed(2)}, total_weight=${total.toFixed(2)})\n  actions: ${legacy || "(none — holding cash)"}`;
  }
  const actions = o.target_positions
    .map(
      (position) =>
        `${position.ts_code}:${position.position_decision}@w=${position.target_weight.toFixed(2)}(${position.holding_period})`,
    )
    .join(" | ");
  const totalWeight = o.target_positions.reduce((sum, position) => sum + position.target_weight, 0);
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

export function fallbackCioProposal(text: string): CioProposalOutput {
  return { ...fallbackCio(text), position_reviews: [] };
}

export function fallbackCioFinal(text: string): CioFinalOutput {
  return { ...fallbackCio(text), dissent_refs: [] };
}

export { CIO_FIELD_NAMES, CioFinalSchema, CioProposalSchema, CioSchema };

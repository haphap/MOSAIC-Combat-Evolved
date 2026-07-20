/**
 * cro Layer-4 chief risk officer (Plan §5.4).
 * Reads Layer 1+2+3 fully, produces adversarial risk review.
 */

import type { DailyCycleStateType } from "../state.js";
import type { CroOutput } from "../types.js";
import {
  buildLayerFourAgentNode,
  type LayerFourAgentDeps,
  type LayerFourAgentNode,
  type LayerFourAgentSpec,
} from "./_factory.js";
import { CRO_FIELD_NAMES, CroSchema } from "./_schemas.js";
import { renderCurrentPositionsContext, renderLayer4RuntimeContext } from "./_user_context.js";
import type { CroAgentSubmission } from "./accepted.js";

const REQUIRED_TOOLS = ["get_cro_risk_snapshot", "get_role_event_snapshot"] as const;

function buildUserContext(state: DailyCycleStateType): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for cro (Layer 4 chief risk officer):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderCurrentPositionsContext(state)}\n\n` +
    `${renderLayer4RuntimeContext(state)}\n\n` +
    `Review every ticker and exposure in the frozen candidate target. Reject the ones with concentrated ` +
    `correlated risks, regulatory exposure, or black-swan vulnerability. ` +
    `Empty rejected_picks is fine when upstream looks clean.`
  );
}

export const croSpec: LayerFourAgentSpec<CroAgentSubmission> = {
  agentId: "cro",
  runtimeStage: "cro_review",
  schema: CroSchema,
  fieldNames: CRO_FIELD_NAMES,
  stateUpdateField: "cro",
  requiredTools: REQUIRED_TOOLS,
  buildUserContext,
  render: renderCro,
};

export function buildCroNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  return buildLayerFourAgentNode(croSpec, deps);
}

export function renderCro(o: CroAgentSubmission | CroOutput): string {
  if ("agent" in o) {
    const rejected = o.rejected_picks.map((pick) => `${pick.ticker}:${pick.reason}`).join(" | ");
    return (
      `cro review (confidence=${o.confidence.toFixed(2)})\n` +
      `  rejected: ${rejected || "(none)"}\n` +
      `  correlated_risks: ${o.correlated_risks.join(" | ")}\n` +
      `  black_swans: ${o.black_swan_scenarios.join(" | ")}`
    );
  }
  const actions = o.candidate_actions
    .map((action) => `${action.ts_code}:${action.action}:${action.reason}`)
    .join(" | ");
  return (
    `cro review (confidence=${o.confidence.toFixed(2)})\n` +
    `  candidate_actions: ${actions || "(none)"}\n` +
    `  correlated_risks: ${o.correlated_risks.map((risk) => risk.summary).join(" | ")}\n` +
    `  black_swans: ${o.black_swan_scenarios.map((risk) => risk.summary).join(" | ")}`
  );
}

export function fallbackCro(text: string): CroOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "cro",
    rejected_picks: [],
    required_adjustments: [],
    correlated_risks: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    black_swan_scenarios: ["analysis missing"],
    confidence: 0,
  };
}

export { CRO_FIELD_NAMES, CroSchema };

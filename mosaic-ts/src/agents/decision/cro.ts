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
import { renderLayer1Context, renderLayer2Context, renderLayer3Context } from "./_user_context.js";

function buildUserContext(state: DailyCycleStateType): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for cro (Layer 4 chief risk officer):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer1Context(state)}\n` +
    `${renderLayer2Context(state)}\n` +
    `${renderLayer3Context(state)}\n\n` +
    `Review every pick across L2 longs and L3 picks. Reject the ones with concentrated ` +
    `correlated risks, regulatory exposure, or black-swan vulnerability. ` +
    `Empty rejected_picks is fine when upstream looks clean.`
  );
}

export const croSpec: LayerFourAgentSpec<CroOutput> = {
  agentId: "cro",
  schema: CroSchema,
  fieldNames: CRO_FIELD_NAMES,
  stateUpdateField: "cro",
  buildUserContext,
  render: renderCro,
  fallback: fallbackCro,
};

export function buildCroNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  return buildLayerFourAgentNode(croSpec, deps);
}

export function renderCro(o: CroOutput): string {
  const rejected = o.rejected_picks.map((r) => `${r.ticker}:${r.reason}`).join(" | ");
  return (
    `cro review (confidence=${o.confidence.toFixed(2)})\n` +
    `  rejected: ${rejected || "(none)"}\n` +
    `  correlated_risks: ${o.correlated_risks.join(" | ")}\n` +
    `  black_swans: ${o.black_swan_scenarios.join(" | ")}`
  );
}

export function fallbackCro(text: string): CroOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "cro",
    rejected_picks: [],
    correlated_risks: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    black_swan_scenarios: ["analysis missing"],
    confidence: 0,
  };
}

export { CRO_FIELD_NAMES, CroSchema };

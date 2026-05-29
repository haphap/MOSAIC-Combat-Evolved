/**
 * alpha_discovery Layer-4 (Plan §5.4).
 * Reads L1+L2+L3 fully, surfaces picks that fell between superinvestor
 * philosophy filters.
 */

import type { DailyCycleStateType } from "../state.js";
import type { AlphaDiscoveryOutput } from "../types.js";
import {
  buildLayerFourAgentNode,
  type LayerFourAgentDeps,
  type LayerFourAgentNode,
  type LayerFourAgentSpec,
} from "./_factory.js";
import { ALPHA_DISCOVERY_FIELD_NAMES, AlphaDiscoverySchema } from "./_schemas.js";
import { renderLayer1Context, renderLayer2Context, renderLayer3Context } from "./_user_context.js";

function buildUserContext(state: DailyCycleStateType): string {
  const date = state.as_of_date || new Date().toISOString().slice(0, 10);
  return (
    `Cycle context for alpha_discovery (Layer 4 alpha hunter):\n` +
    `* as_of_date: ${date}\n` +
    `* mode:       ${state.mode || "live"}\n\n` +
    `${renderLayer1Context(state)}\n` +
    `${renderLayer2Context(state)}\n` +
    `${renderLayer3Context(state)}\n\n` +
    `Find tickers visible in L1/L2 signals that none of the 4 superinvestors picked. ` +
    `Explain why each philosopher missed it. Empty novel_picks is the most common ` +
    `outcome and is fine — only flag genuinely novel cross-cutting picks.`
  );
}

export const alphaDiscoverySpec: LayerFourAgentSpec<AlphaDiscoveryOutput> = {
  agentId: "alpha_discovery",
  schema: AlphaDiscoverySchema,
  fieldNames: ALPHA_DISCOVERY_FIELD_NAMES,
  stateUpdateField: "alpha_discovery",
  buildUserContext,
  render: renderAlphaDiscovery,
  fallback: fallbackAlphaDiscovery,
};

export function buildAlphaDiscoveryNode(deps: LayerFourAgentDeps): LayerFourAgentNode {
  return buildLayerFourAgentNode(alphaDiscoverySpec, deps);
}

export function renderAlphaDiscovery(o: AlphaDiscoveryOutput): string {
  const novel = o.novel_picks.map((p) => `${p.ticker}:${p.why_missed_by_others}`).join(" | ");
  return (
    `alpha_discovery (confidence=${o.confidence.toFixed(2)})\n` +
    `  novel_picks: ${novel || "(none)"}`
  );
}

export function fallbackAlphaDiscovery(text: string): AlphaDiscoveryOutput {
  void text;
  return {
    agent: "alpha_discovery",
    novel_picks: [],
    confidence: 0,
  };
}

export { ALPHA_DISCOVERY_FIELD_NAMES, AlphaDiscoverySchema };

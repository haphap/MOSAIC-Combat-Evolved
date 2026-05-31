/** baker Layer-3 (Plan §5.3): deep tech / biotech IP moats. */

import type { BakerOutput, RegimeSignal } from "../types.js";
import {
  buildLayerThreeAgentNode,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { BakerSchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_industry_policy", "get_stock_research"] as const;

export const bakerSpec: LayerThreeAgentSpec<BakerOutput> = {
  agentId: "baker",
  schema: BakerSchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderBaker,
  fallback: fallbackBaker,
};

export function buildBakerNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(bakerSpec, deps);
}

export function renderBaker(o: BakerOutput): string {
  const picks = o.picks
    .map((p) => `${p.ticker}(${p.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `baker picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  picks: ${picks || "(none)"}\n` +
    `  philosophy: ${o.philosophy_note}`
  );
}

export function fallbackBaker(text: string, _regime: RegimeSignal | null): BakerOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "baker",
    picks: [],
    philosophy_note: "no IP-moat candidate identified — biotech sector picks insufficient.",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { BakerSchema, SUPERINVESTOR_FIELD_NAMES };

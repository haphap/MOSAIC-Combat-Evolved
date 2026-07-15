/** burry Layer-3 (Plan §5.3): contrarian deep value / downside-first. */

import type { BurryOutput, RegimeSignal } from "../types.js";
import {
  buildLayerThreeAgentNode,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { BurrySchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_rke_research_context",
  "get_stock_research",
  "get_fundamentals",
  "get_income_statement",
  "get_cashflow",
  "get_balance_sheet",
  "get_stock_data",
] as const;

export const burrySpec: LayerThreeAgentSpec<BurryOutput> = {
  agentId: "burry",
  schema: BurrySchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderBurry,
};

export function buildBurryNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(burrySpec, deps);
}

export function renderBurry(o: BurryOutput): string {
  const picks = o.picks
    .map((p) => `${p.ticker}(${p.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `burry picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  picks: ${picks || "(none)"}\n` +
    `  philosophy: ${o.philosophy_note}`
  );
}

export function fallbackBurry(text: string, _regime: RegimeSignal | null): BurryOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "burry",
    picks: [],
    philosophy_note: "no contrarian deep-value candidate passed downside and balance-sheet checks.",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { BurrySchema, SUPERINVESTOR_FIELD_NAMES };

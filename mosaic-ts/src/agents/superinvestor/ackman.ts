/** ackman Layer-3 (Plan §5.3): quality compounder, pricing power + FCF + catalyst. */

import type { AckmanOutput, RegimeSignal } from "../types.js";
import {
  buildLayerThreeAgentNode,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { AckmanSchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_xueqiu_heat",
  "get_lhb_ranking",
  "get_stock_research",
  "get_fundamentals",
  "get_income_statement",
  "get_cashflow",
  "get_balance_sheet",
  "get_stock_data",
  "get_indicators",
] as const;

export const ackmanSpec: LayerThreeAgentSpec<AckmanOutput> = {
  agentId: "ackman",
  schema: AckmanSchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderAckman,
  fallback: fallbackAckman,
};

export function buildAckmanNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(ackmanSpec, deps);
}

export function renderAckman(o: AckmanOutput): string {
  const picks = o.picks
    .map((p) => `${p.ticker}(${p.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `ackman picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  picks: ${picks || "(none)"}\n` +
    `  philosophy: ${o.philosophy_note}`
  );
}

export function fallbackAckman(text: string, _regime: RegimeSignal | null): AckmanOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "ackman",
    picks: [],
    philosophy_note:
      "no quality compounder identified — pricing power + FCF + catalyst trio not present in candidate set.",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { AckmanSchema, SUPERINVESTOR_FIELD_NAMES };

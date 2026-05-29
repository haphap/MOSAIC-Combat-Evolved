/**
 * emerging_markets Layer-1 macro agent (Plan §5.1).
 *
 * Plan §5.1 wants `get_etf_price_data(EEM)` + `get_etf_price_data(2800.HK)`;
 * Phase 0 has no ETF price tools. Substitution: `get_north_capital_flow` +
 * `get_us_china_spread` + `get_fred_series(DTWEXBGS)`. Tracked plan §14 #8.
 */

import type { EmergingMarketsOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
} from "./_factory.js";
import { EMERGING_MARKETS_FIELD_NAMES, EmergingMarketsSchema } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_north_capital_flow",
  "get_us_china_spread",
  "get_fred_series",
] as const;

export const emergingMarketsSpec: LayerOneAgentSpec<EmergingMarketsOutput> = {
  agentId: "emerging_markets",
  schema: EmergingMarketsSchema,
  fieldNames: EMERGING_MARKETS_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderEmergingMarkets,
  fallback: fallbackEmergingMarkets,
};

export function buildEmergingMarketsNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(emergingMarketsSpec, deps);
}

export function renderEmergingMarkets(o: EmergingMarketsOutput): string {
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `emerging_markets analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  em_relative:        ${o.em_relative}\n` +
    `  hk_a_share_ratio:   ${o.hk_a_share_ratio.toFixed(2)}\n` +
    `  capital_flow:       ${o.capital_flow}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackEmergingMarkets(text: string): EmergingMarketsOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "emerging_markets",
    em_relative: "INLINE",
    hk_a_share_ratio: 0,
    capital_flow: "FLAT",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { EMERGING_MARKETS_FIELD_NAMES, EmergingMarketsSchema };

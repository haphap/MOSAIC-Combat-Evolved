/**
 * emerging_markets Layer-1 macro agent (Plan §5.1).
 *
 * Tools: `get_etf_price_data` / `get_etf_info` / `get_etf_nav` /
 * `get_etf_universe` + `get_us_china_spread` + `get_fred_series(DTWEXBGS)`.
 * DTWEXBGS uses the exact FRED broad-dollar series; DGS* series still route
 * through Tushare us_tycr first.
 * Use ETF prices on HK/A-share/EM-proxy funds (e.g. 510300.SH, 513050.SH) for
 * the HK-A ratio. (Northbound flow dropped — live quota disclosure discontinued.)
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
  "get_etf_price_data",
  "get_us_china_spread",
  "get_fred_series",
  "get_etf_info",
  "get_etf_nav",
  "get_etf_universe",
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

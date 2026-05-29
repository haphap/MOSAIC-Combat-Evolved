/**
 * commodities Layer-1 macro agent (Plan §5.1).
 *
 * Plan §5.1 wants `get_commodity_prices` (general); Phase 0 lacks that.
 * Substitution: `get_fred_series(DCOILWTICO)` + `get_fred_series(GOLDPMGBD228NLBM)`
 * + `get_yield_curve_cn` (CN curve as a China-demand proxy). Tracked plan §14 #8.
 */

import type { CommoditiesOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
} from "./_factory.js";
import { COMMODITIES_FIELD_NAMES, CommoditiesSchema } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_fred_series", "get_yield_curve_cn"] as const;

export const commoditiesSpec: LayerOneAgentSpec<CommoditiesOutput> = {
  agentId: "commodities",
  schema: CommoditiesSchema,
  fieldNames: COMMODITIES_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderCommodities,
  fallback: fallbackCommodities,
};

export function buildCommoditiesNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(commoditiesSpec, deps);
}

export function renderCommodities(o: CommoditiesOutput): string {
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `commodities analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  oil_regime:           ${o.oil_regime}\n` +
    `  metals_regime:        ${o.metals_regime}\n` +
    `  ag_regime:            ${o.ag_regime}\n` +
    `  china_demand_signal:  ${o.china_demand_signal}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackCommodities(text: string): CommoditiesOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "commodities",
    oil_regime: "NEUTRAL",
    metals_regime: "ROTATING",
    ag_regime: "BALANCED",
    china_demand_signal: "STEADY",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { COMMODITIES_FIELD_NAMES, CommoditiesSchema };

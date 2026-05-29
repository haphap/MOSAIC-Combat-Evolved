/**
 * dollar Layer-1 macro agent (Plan §5.1).
 *
 * Plan §5.1 wants `get_fred_series(DTWEXBGS)` + `get_usdcny` +
 * `get_north_capital_flow`. Phase 0 lacks `get_usdcny`; substitute with
 * `get_us_china_spread` (CN-US 10Y spread is the de-facto USDCNY driver).
 * Tracked in plan §14 #8.
 */

import type { DollarOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
} from "./_factory.js";
import { DOLLAR_FIELD_NAMES, DollarSchema } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_fred_series",
  "get_north_capital_flow",
  "get_us_china_spread",
] as const;

export const dollarSpec: LayerOneAgentSpec<DollarOutput> = {
  agentId: "dollar",
  schema: DollarSchema,
  fieldNames: DOLLAR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderDollar,
  fallback: fallbackDollar,
};

export function buildDollarNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(dollarSpec, deps);
}

export function renderDollar(o: DollarOutput): string {
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `dollar analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  dxy_trend:               ${o.dxy_trend}\n` +
    `  cny_pressure:            ${o.cny_pressure}\n` +
    `  north_flow_correlation:  ${o.north_flow_correlation}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackDollar(text: string): DollarOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "dollar",
    dxy_trend: "STABLE",
    cny_pressure: "MODERATE",
    north_flow_correlation: 0,
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { DOLLAR_FIELD_NAMES, DollarSchema };

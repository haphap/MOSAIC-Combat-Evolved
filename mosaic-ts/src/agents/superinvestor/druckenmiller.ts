/**
 * druckenmiller Layer-3 superinvestor (Plan §5.3).
 *
 * Philosophy: macro / momentum, asymmetric trades, sector rotation +
 * policy catalyst pairs. Concentrated 3-5 names.
 */

import type { DruckenmillerOutput, RegimeSignal } from "../types.js";
import {
  buildLayerThreeAgentNode,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { DruckenmillerSchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_yield_curve_cn",
  "get_industry_policy",
  "get_stock_research",
  "get_fundamentals",
  "get_stock_data",
  "get_indicators",
] as const;

export const druckenmillerSpec: LayerThreeAgentSpec<DruckenmillerOutput> = {
  agentId: "druckenmiller",
  schema: DruckenmillerSchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderDruckenmiller,
  fallback: fallbackDruckenmiller,
};

export function buildDruckenmillerNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(druckenmillerSpec, deps);
}

export function renderDruckenmiller(o: DruckenmillerOutput): string {
  const picks = o.picks
    .map((p) => `${p.ticker}(${p.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `druckenmiller picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  picks: ${picks || "(none)"}\n` +
    `  philosophy: ${o.philosophy_note}`
  );
}

export function fallbackDruckenmiller(
  text: string,
  _regime: RegimeSignal | null,
): DruckenmillerOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "druckenmiller",
    picks: [],
    philosophy_note:
      "no asymmetric trade identified — analysis missing or no regime catalyst pair.",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { DruckenmillerSchema, SUPERINVESTOR_FIELD_NAMES };

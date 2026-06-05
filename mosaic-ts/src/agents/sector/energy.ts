/**
 * energy Layer-2 sector agent (Plan §5.2). Covers oil&gas + coal + utilities.
 * ETF holdings tools missing (plan §14 #8) — substitute via policy / heat /
 * LHB / north flow.
 */

import type { EnergyOutput, RegimeSignal } from "../types.js";
import {
  buildLayerTwoAgentNode,
  type LayerTwoAgentDeps,
  type LayerTwoAgentNode,
  type LayerTwoAgentSpec,
} from "./_factory.js";
import { EnergySchema, STANDARD_SECTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_industry_policy",
  "get_xueqiu_heat",
  "get_lhb_ranking",
  "get_broker_research",
  "get_etf_holdings",
  "get_stock_data",
  "get_indicators",
  "get_industry_moneyflow",
] as const;

export const energySpec: LayerTwoAgentSpec<EnergyOutput> = {
  agentId: "energy",
  schema: EnergySchema,
  fieldNames: STANDARD_SECTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderEnergy,
  fallback: fallbackEnergy,
};

export function buildEnergyNode(deps: LayerTwoAgentDeps): LayerTwoAgentNode {
  return buildLayerTwoAgentNode(energySpec, deps);
}

export function renderEnergy(o: EnergyOutput): string {
  const longs = o.longs.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  const shorts = o.shorts.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  return (
    `energy analysis (confidence=${o.confidence.toFixed(2)}, score=${o.sector_score.toFixed(2)})\n` +
    `  longs:  ${longs || "(none)"}\n` +
    `  shorts: ${shorts || "(none)"}\n` +
    `  drivers: ${o.key_drivers.join(" | ")}`
  );
}

export function fallbackEnergy(text: string, _regime: RegimeSignal | null): EnergyOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "energy",
    longs: [],
    shorts: [],
    sector_score: 0,
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { EnergySchema, STANDARD_SECTOR_FIELD_NAMES };

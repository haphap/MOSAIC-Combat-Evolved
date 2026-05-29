/** financials Layer-2 (Plan §5.2). 银行 + 非银 sector. */

import type { FinancialsOutput, RegimeSignal } from "../types.js";
import {
  buildLayerTwoAgentNode,
  type LayerTwoAgentDeps,
  type LayerTwoAgentNode,
  type LayerTwoAgentSpec,
} from "./_factory.js";
import { FinancialsSchema, STANDARD_SECTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_industry_policy",
  "get_xueqiu_heat",
  "get_lhb_ranking",
  "get_yield_curve_cn",
] as const;

export const financialsSpec: LayerTwoAgentSpec<FinancialsOutput> = {
  agentId: "financials",
  schema: FinancialsSchema,
  fieldNames: STANDARD_SECTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderFinancials,
  fallback: fallbackFinancials,
};

export function buildFinancialsNode(deps: LayerTwoAgentDeps): LayerTwoAgentNode {
  return buildLayerTwoAgentNode(financialsSpec, deps);
}

export function renderFinancials(o: FinancialsOutput): string {
  const longs = o.longs.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  const shorts = o.shorts.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  return (
    `financials analysis (confidence=${o.confidence.toFixed(2)}, score=${o.sector_score.toFixed(2)})\n` +
    `  longs:  ${longs || "(none)"}\n` +
    `  shorts: ${shorts || "(none)"}\n` +
    `  drivers: ${o.key_drivers.join(" | ")}`
  );
}

export function fallbackFinancials(text: string, _regime: RegimeSignal | null): FinancialsOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "financials",
    longs: [],
    shorts: [],
    sector_score: 0,
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { FinancialsSchema, STANDARD_SECTOR_FIELD_NAMES };

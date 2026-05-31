/** industrials Layer-2 (Plan §5.2). 机械 + 军工 + 交运 sector. */

import type { IndustrialsOutput, RegimeSignal } from "../types.js";
import {
  buildLayerTwoAgentNode,
  type LayerTwoAgentDeps,
  type LayerTwoAgentNode,
  type LayerTwoAgentSpec,
} from "./_factory.js";
import { IndustrialsSchema, STANDARD_SECTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_industry_policy",
  "get_xueqiu_heat",
  "get_lhb_ranking",
  "get_broker_research",
] as const;

export const industrialsSpec: LayerTwoAgentSpec<IndustrialsOutput> = {
  agentId: "industrials",
  schema: IndustrialsSchema,
  fieldNames: STANDARD_SECTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderIndustrials,
  fallback: fallbackIndustrials,
};

export function buildIndustrialsNode(deps: LayerTwoAgentDeps): LayerTwoAgentNode {
  return buildLayerTwoAgentNode(industrialsSpec, deps);
}

export function renderIndustrials(o: IndustrialsOutput): string {
  const longs = o.longs.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  const shorts = o.shorts.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  return (
    `industrials analysis (confidence=${o.confidence.toFixed(2)}, score=${o.sector_score.toFixed(2)})\n` +
    `  longs:  ${longs || "(none)"}\n` +
    `  shorts: ${shorts || "(none)"}\n` +
    `  drivers: ${o.key_drivers.join(" | ")}`
  );
}

export function fallbackIndustrials(text: string, _regime: RegimeSignal | null): IndustrialsOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "industrials",
    longs: [],
    shorts: [],
    sector_score: 0,
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { IndustrialsSchema, STANDARD_SECTOR_FIELD_NAMES };

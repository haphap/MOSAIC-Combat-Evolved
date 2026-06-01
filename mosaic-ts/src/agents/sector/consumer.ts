/** consumer Layer-2 (Plan §5.2). 食饮 + 家电 + 美护 sector. */

import type { ConsumerOutput, RegimeSignal } from "../types.js";
import {
  buildLayerTwoAgentNode,
  type LayerTwoAgentDeps,
  type LayerTwoAgentNode,
  type LayerTwoAgentSpec,
} from "./_factory.js";
import { ConsumerSchema, STANDARD_SECTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_industry_policy",
  "get_xueqiu_heat",
  "get_lhb_ranking",
  "get_north_capital_flow",
  "get_broker_research",
  "get_etf_holdings",
  "get_stock_data",
  "get_indicators",
  "get_industry_moneyflow",
] as const;

export const consumerSpec: LayerTwoAgentSpec<ConsumerOutput> = {
  agentId: "consumer",
  schema: ConsumerSchema,
  fieldNames: STANDARD_SECTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderConsumer,
  fallback: fallbackConsumer,
};

export function buildConsumerNode(deps: LayerTwoAgentDeps): LayerTwoAgentNode {
  return buildLayerTwoAgentNode(consumerSpec, deps);
}

export function renderConsumer(o: ConsumerOutput): string {
  const longs = o.longs.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  const shorts = o.shorts.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  return (
    `consumer analysis (confidence=${o.confidence.toFixed(2)}, score=${o.sector_score.toFixed(2)})\n` +
    `  longs:  ${longs || "(none)"}\n` +
    `  shorts: ${shorts || "(none)"}\n` +
    `  drivers: ${o.key_drivers.join(" | ")}`
  );
}

export function fallbackConsumer(text: string, _regime: RegimeSignal | null): ConsumerOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "consumer",
    longs: [],
    shorts: [],
    sector_score: 0,
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { ConsumerSchema, STANDARD_SECTOR_FIELD_NAMES };

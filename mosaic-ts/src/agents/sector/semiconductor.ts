/**
 * semiconductor Layer-2 sector agent (Plan §5.2).
 *
 * Plan §5.2 ideal tool set requires ETF holdings + industry research; both
 * Phase 0+1 absent (tracked plan §14 #8). Substitution: industry policy
 * filtered for semi keywords + retail attention concentration on semi
 * leaders + LHB sector aggregation + north-flow with semi sector preference.
 */

import type { RegimeSignal, SemiconductorOutput } from "../types.js";
import {
  buildLayerTwoAgentNode,
  type LayerTwoAgentDeps,
  type LayerTwoAgentNode,
  type LayerTwoAgentSpec,
} from "./_factory.js";
import { SemiconductorSchema, STANDARD_SECTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_industry_policy",
  "get_xueqiu_heat",
  "get_lhb_ranking",
  "get_north_capital_flow",
  "get_broker_research",
  "get_etf_holdings",
] as const;

export const semiconductorSpec: LayerTwoAgentSpec<SemiconductorOutput> = {
  agentId: "semiconductor",
  schema: SemiconductorSchema,
  fieldNames: STANDARD_SECTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderSemiconductor,
  fallback: fallbackSemiconductor,
};

export function buildSemiconductorNode(deps: LayerTwoAgentDeps): LayerTwoAgentNode {
  return buildLayerTwoAgentNode(semiconductorSpec, deps);
}

export function renderSemiconductor(o: SemiconductorOutput): string {
  const longs = o.longs.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  const shorts = o.shorts.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  return (
    `semiconductor analysis (confidence=${o.confidence.toFixed(2)}, score=${o.sector_score.toFixed(2)})\n` +
    `  longs:  ${longs || "(none)"}\n` +
    `  shorts: ${shorts || "(none)"}\n` +
    `  drivers: ${o.key_drivers.join(" | ")}`
  );
}

export function fallbackSemiconductor(
  text: string,
  _regime: RegimeSignal | null,
): SemiconductorOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "semiconductor",
    longs: [],
    shorts: [],
    sector_score: 0,
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { SemiconductorSchema, STANDARD_SECTOR_FIELD_NAMES };

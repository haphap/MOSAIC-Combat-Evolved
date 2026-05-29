/** biotech Layer-2 (Plan §5.2). 医药生物 sector. */

import type { BiotechOutput, RegimeSignal } from "../types.js";
import {
  buildLayerTwoAgentNode,
  type LayerTwoAgentDeps,
  type LayerTwoAgentNode,
  type LayerTwoAgentSpec,
} from "./_factory.js";
import { BiotechSchema, STANDARD_SECTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_industry_policy",
  "get_xueqiu_heat",
  "get_lhb_ranking",
] as const;

export const biotechSpec: LayerTwoAgentSpec<BiotechOutput> = {
  agentId: "biotech",
  schema: BiotechSchema,
  fieldNames: STANDARD_SECTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderBiotech,
  fallback: fallbackBiotech,
};

export function buildBiotechNode(deps: LayerTwoAgentDeps): LayerTwoAgentNode {
  return buildLayerTwoAgentNode(biotechSpec, deps);
}

export function renderBiotech(o: BiotechOutput): string {
  const longs = o.longs.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  const shorts = o.shorts.map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`).join(", ");
  return (
    `biotech analysis (confidence=${o.confidence.toFixed(2)}, score=${o.sector_score.toFixed(2)})\n` +
    `  longs:  ${longs || "(none)"}\n` +
    `  shorts: ${shorts || "(none)"}\n` +
    `  drivers: ${o.key_drivers.join(" | ")}`
  );
}

export function fallbackBiotech(text: string, _regime: RegimeSignal | null): BiotechOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "biotech",
    longs: [],
    shorts: [],
    sector_score: 0,
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { BiotechSchema, STANDARD_SECTOR_FIELD_NAMES };

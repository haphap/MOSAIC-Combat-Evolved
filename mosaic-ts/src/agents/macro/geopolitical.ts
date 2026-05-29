/**
 * geopolitical Layer-1 macro agent (Plan §5.1).
 *
 * Plan §5.1 lists `get_global_news(geopolitical)` + `get_us_china_relations`;
 * Phase 0 has neither. Substitution per plan §14 #8: use `get_xueqiu_heat`
 * (retail attention captures geopolitical events fast) + `get_industry_policy`
 * (filters policy news incl. trade-war / export-control language).
 */

import type { GeopoliticalOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
} from "./_factory.js";
import { GEOPOLITICAL_FIELD_NAMES, GeopoliticalSchema } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_xueqiu_heat", "get_industry_policy"] as const;

export const geopoliticalSpec: LayerOneAgentSpec<GeopoliticalOutput> = {
  agentId: "geopolitical",
  schema: GeopoliticalSchema,
  fieldNames: GEOPOLITICAL_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderGeopolitical,
  fallback: fallbackGeopolitical,
};

export function buildGeopoliticalNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(geopoliticalSpec, deps);
}

export function renderGeopolitical(o: GeopoliticalOutput): string {
  const zones = (o.hot_zones ?? []).join(", ");
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `geopolitical analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  escalation_level: ${o.escalation_level}\n` +
    `  hot_zones:        ${zones}\n` +
    `  trade_impact:     ${o.trade_impact}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackGeopolitical(text: string): GeopoliticalOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "geopolitical",
    escalation_level: 2,
    hot_zones: ["unknown"],
    trade_impact: "no material change",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { GEOPOLITICAL_FIELD_NAMES, GeopoliticalSchema };

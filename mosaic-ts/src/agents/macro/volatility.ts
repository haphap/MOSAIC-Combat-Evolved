/**
 * volatility Layer-1 macro agent (Plan §5.1).
 *
 * Plan §5.1 wants `get_ivx` + `get_etf_indicator(510050.SH)`; Phase 0 has
 * neither. Substitution: `get_fred_series(VIXCLS)` + `get_yield_curve_cn`
 * (curve volatility is a passable iVX proxy until ETF tools land in Phase 8).
 * Tracked plan §14 #8.
 */

import type { VolatilityOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
} from "./_factory.js";
import { VOLATILITY_FIELD_NAMES, VolatilitySchema } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_fred_series", "get_yield_curve_cn"] as const;

export const volatilitySpec: LayerOneAgentSpec<VolatilityOutput> = {
  agentId: "volatility",
  schema: VolatilitySchema,
  fieldNames: VOLATILITY_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderVolatility,
  fallback: fallbackVolatility,
};

export function buildVolatilityNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(volatilitySpec, deps);
}

export function renderVolatility(o: VolatilityOutput): string {
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `volatility analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  vix_regime:      ${o.vix_regime}\n` +
    `  ivx_regime:      ${o.ivx_regime}\n` +
    `  regime_filter:   ${o.regime_filter}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackVolatility(text: string): VolatilityOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "volatility",
    vix_regime: "ELEVATED",
    ivx_regime: "ELEVATED",
    regime_filter: "NEUTRAL",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { VOLATILITY_FIELD_NAMES, VolatilitySchema };

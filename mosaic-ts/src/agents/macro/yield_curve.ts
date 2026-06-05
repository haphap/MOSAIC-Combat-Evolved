/**
 * yield_curve Layer-1 macro agent (Plan §5.1).
 *
 * Tools: get_yield_curve_cn (CN curve daily) + get_fred_series (US DGS10/DGS2,
 * routed through Tushare us_tycr first) + get_us_china_spread (composite).
 */

import type { YieldCurveOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
} from "./_factory.js";
import { YIELD_CURVE_FIELD_NAMES, YieldCurveSchema } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_yield_curve_cn",
  "get_fred_series",
  "get_us_china_spread",
] as const;

export const yieldCurveSpec: LayerOneAgentSpec<YieldCurveOutput> = {
  agentId: "yield_curve",
  schema: YieldCurveSchema,
  fieldNames: YIELD_CURVE_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderYieldCurve,
  fallback: fallbackYieldCurve,
};

export function buildYieldCurveNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(yieldCurveSpec, deps);
}

export function renderYieldCurve(o: YieldCurveOutput): string {
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `yield_curve analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  curve_shape:       ${o.curve_shape}\n` +
    `  recession_signal:  ${o.recession_signal}\n` +
    `  cn_us_spread_bps:  ${o.cn_us_spread_bps}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackYieldCurve(text: string): YieldCurveOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "yield_curve",
    curve_shape: "STEEPENING",
    recession_signal: "GREEN",
    cn_us_spread_bps: 0,
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { YIELD_CURVE_FIELD_NAMES, YieldCurveSchema };

import type { YieldCurveOutput } from "../types.js";
import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { YIELD_CURVE_FIELD_NAMES, YieldCurveSchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.yield_curve.requiredTools;
export const yieldCurveSpec = macroAgentSpec<YieldCurveOutput>("yield_curve", YieldCurveSchema);
export const buildYieldCurveNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(yieldCurveSpec, deps);
export const renderYieldCurve = renderMacroTransmission;
export { YIELD_CURVE_FIELD_NAMES, YieldCurveSchema };

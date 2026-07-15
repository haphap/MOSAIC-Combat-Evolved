import type { VolatilityOutput } from "../types.js";
import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { VOLATILITY_FIELD_NAMES, VolatilitySchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.volatility.requiredTools;
export const volatilitySpec = macroAgentSpec<VolatilityOutput>("volatility", VolatilitySchema);
export const buildVolatilityNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(volatilitySpec, deps);
export const renderVolatility = renderMacroTransmission;
export { VOLATILITY_FIELD_NAMES, VolatilitySchema };

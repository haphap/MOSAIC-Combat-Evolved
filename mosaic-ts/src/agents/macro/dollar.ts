import type { DollarOutput } from "../types.js";
import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { DOLLAR_FIELD_NAMES, DollarSchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.dollar.requiredTools;
export const dollarSpec = macroAgentSpec<DollarOutput>("dollar", DollarSchema);
export const buildDollarNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(dollarSpec, deps);
export const renderDollar = renderMacroTransmission;
export { DOLLAR_FIELD_NAMES, DollarSchema };

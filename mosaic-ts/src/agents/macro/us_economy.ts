import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { US_ECONOMY_FIELD_NAMES, UsEconomySchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.us_economy.requiredTools;
export const usEconomySpec = macroAgentSpec("us_economy", UsEconomySchema);
export const buildUsEconomyNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(usEconomySpec, deps);
export const renderUsEconomy = renderMacroTransmission;
export { US_ECONOMY_FIELD_NAMES, UsEconomySchema };

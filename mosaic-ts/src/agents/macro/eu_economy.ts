import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { EU_ECONOMY_FIELD_NAMES, EuEconomySchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.eu_economy.requiredTools;
export const euEconomySpec = macroAgentSpec("eu_economy", EuEconomySchema);
export const buildEuEconomyNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(euEconomySpec, deps);
export const renderEuEconomy = renderMacroTransmission;
export { EU_ECONOMY_FIELD_NAMES, EuEconomySchema };

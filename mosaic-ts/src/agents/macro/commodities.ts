import type { CommoditiesOutput } from "../types.js";
import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { COMMODITIES_FIELD_NAMES, CommoditiesSchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.commodities.requiredTools;
export const commoditiesSpec = macroAgentSpec<CommoditiesOutput>("commodities", CommoditiesSchema);
export const buildCommoditiesNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(commoditiesSpec, deps);
export const renderCommodities = renderMacroTransmission;
export { COMMODITIES_FIELD_NAMES, CommoditiesSchema };

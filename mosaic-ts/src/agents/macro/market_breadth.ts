import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { MARKET_BREADTH_FIELD_NAMES, MarketBreadthSchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.market_breadth.requiredTools;
export const marketBreadthSpec = macroAgentSpec("market_breadth", MarketBreadthSchema);
export const buildMarketBreadthNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(marketBreadthSpec, deps);
export const renderMarketBreadth = renderMacroTransmission;
export { MARKET_BREADTH_FIELD_NAMES, MarketBreadthSchema };

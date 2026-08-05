import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { GEOPOLITICAL_FIELD_NAMES, GeopoliticalSchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.geopolitical.requiredTools;
export const geopoliticalSpec = macroAgentSpec("geopolitical", GeopoliticalSchema);
export const buildGeopoliticalNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(geopoliticalSpec, deps);
export const renderGeopolitical = renderMacroTransmission;
export { GEOPOLITICAL_FIELD_NAMES, GeopoliticalSchema };

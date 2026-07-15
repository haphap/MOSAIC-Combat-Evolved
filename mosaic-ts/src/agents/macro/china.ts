import type { ChinaOutput } from "../types.js";
import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { CHINA_FIELD_NAMES, ChinaSchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.china.requiredTools;
export const chinaSpec = macroAgentSpec<ChinaOutput>("china", ChinaSchema);
export const buildChinaNode = (deps: LayerOneAgentDeps) => buildLayerOneAgentNode(chinaSpec, deps);
export const renderChina = renderMacroTransmission;
export { CHINA_FIELD_NAMES, ChinaSchema };

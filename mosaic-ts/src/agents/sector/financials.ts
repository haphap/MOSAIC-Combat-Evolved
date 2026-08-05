import type { FinancialsOutput } from "../types.js";
import { buildLayerTwoAgentNode, type LayerTwoAgentDeps } from "./_factory.js";
import { FinancialsSchema } from "./_schemas.js";
import { renderStandardSector, standardSectorSpec } from "./_spec.js";

export const financialsSpec = standardSectorSpec<FinancialsOutput>("financials", FinancialsSchema);
export const REQUIRED_TOOLS = financialsSpec.requiredTools;
export const buildFinancialsNode = (deps: LayerTwoAgentDeps) =>
  buildLayerTwoAgentNode(financialsSpec, deps);
export const renderFinancials = renderStandardSector;
export { FinancialsSchema };

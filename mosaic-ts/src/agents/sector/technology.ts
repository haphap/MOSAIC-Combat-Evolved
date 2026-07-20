import type { TechnologyOutput } from "../types.js";
import { buildLayerTwoAgentNode, type LayerTwoAgentDeps } from "./_factory.js";
import { TechnologySchema } from "./_schemas.js";
import { renderStandardSector, standardSectorSpec } from "./_spec.js";

export const technologySpec = standardSectorSpec<TechnologyOutput>("technology", TechnologySchema);
export const REQUIRED_TOOLS = technologySpec.requiredTools;
export const buildTechnologyNode = (deps: LayerTwoAgentDeps) =>
  buildLayerTwoAgentNode(technologySpec, deps);
export const renderTechnology = renderStandardSector;
export { TechnologySchema };

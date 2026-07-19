import type { RealEstateConstructionOutput } from "../types.js";
import { buildLayerTwoAgentNode, type LayerTwoAgentDeps } from "./_factory.js";
import { RealEstateConstructionSchema } from "./_schemas.js";
import { renderStandardSector, standardSectorSpec } from "./_spec.js";

export const realEstateConstructionSpec = standardSectorSpec<RealEstateConstructionOutput>(
  "real_estate_construction",
  RealEstateConstructionSchema,
);
export const REQUIRED_TOOLS = realEstateConstructionSpec.requiredTools;
export const buildRealEstateConstructionNode = (deps: LayerTwoAgentDeps) =>
  buildLayerTwoAgentNode(realEstateConstructionSpec, deps);
export const renderRealEstateConstruction = renderStandardSector;
export { RealEstateConstructionSchema };

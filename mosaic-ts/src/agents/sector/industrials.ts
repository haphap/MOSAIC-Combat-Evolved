import type { IndustrialsOutput } from "../types.js";
import { buildLayerTwoAgentNode, type LayerTwoAgentDeps } from "./_factory.js";
import { IndustrialsSchema } from "./_schemas.js";
import { renderStandardSector, standardSectorSpec } from "./_spec.js";

export const industrialsSpec = standardSectorSpec<IndustrialsOutput>(
  "industrials",
  IndustrialsSchema,
);
export const REQUIRED_TOOLS = industrialsSpec.requiredTools;
export const buildIndustrialsNode = (deps: LayerTwoAgentDeps) =>
  buildLayerTwoAgentNode(industrialsSpec, deps);
export const renderIndustrials = renderStandardSector;
export { IndustrialsSchema };

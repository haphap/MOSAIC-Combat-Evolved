import type { SemiconductorOutput } from "../types.js";
import { buildLayerTwoAgentNode, type LayerTwoAgentDeps } from "./_factory.js";
import { SemiconductorSchema } from "./_schemas.js";
import { renderStandardSector, standardSectorSpec } from "./_spec.js";

export const semiconductorSpec = standardSectorSpec<SemiconductorOutput>(
  "semiconductor",
  SemiconductorSchema,
);
export const REQUIRED_TOOLS = semiconductorSpec.requiredTools;
export const buildSemiconductorNode = (deps: LayerTwoAgentDeps) =>
  buildLayerTwoAgentNode(semiconductorSpec, deps);
export const renderSemiconductor = renderStandardSector;
export { SemiconductorSchema };

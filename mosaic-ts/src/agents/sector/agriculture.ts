import type { AgricultureOutput } from "../types.js";
import { buildLayerTwoAgentNode, type LayerTwoAgentDeps } from "./_factory.js";
import { AgricultureSchema } from "./_schemas.js";
import { renderStandardSector, standardSectorSpec } from "./_spec.js";

export const agricultureSpec = standardSectorSpec<AgricultureOutput>(
  "agriculture",
  AgricultureSchema,
);
export const REQUIRED_TOOLS = agricultureSpec.requiredTools;
export const buildAgricultureNode = (deps: LayerTwoAgentDeps) =>
  buildLayerTwoAgentNode(agricultureSpec, deps);
export const renderAgriculture = renderStandardSector;
export { AgricultureSchema };

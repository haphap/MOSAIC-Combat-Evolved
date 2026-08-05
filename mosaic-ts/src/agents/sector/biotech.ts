import type { BiotechOutput } from "../types.js";
import { buildLayerTwoAgentNode, type LayerTwoAgentDeps } from "./_factory.js";
import { BiotechSchema } from "./_schemas.js";
import { renderStandardSector, standardSectorSpec } from "./_spec.js";

export const biotechSpec = standardSectorSpec<BiotechOutput>("biotech", BiotechSchema);
export const REQUIRED_TOOLS = biotechSpec.requiredTools;
export const buildBiotechNode = (deps: LayerTwoAgentDeps) =>
  buildLayerTwoAgentNode(biotechSpec, deps);
export const renderBiotech = renderStandardSector;
export { BiotechSchema };

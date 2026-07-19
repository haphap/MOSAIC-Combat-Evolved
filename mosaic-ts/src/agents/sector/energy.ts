import type { EnergyOutput } from "../types.js";
import { buildLayerTwoAgentNode, type LayerTwoAgentDeps } from "./_factory.js";
import { EnergySchema } from "./_schemas.js";
import { renderStandardSector, standardSectorSpec } from "./_spec.js";

export const energySpec = standardSectorSpec<EnergyOutput>("energy", EnergySchema);
export const REQUIRED_TOOLS = energySpec.requiredTools;
export const buildEnergyNode = (deps: LayerTwoAgentDeps) =>
  buildLayerTwoAgentNode(energySpec, deps);
export const renderEnergy = renderStandardSector;
export { EnergySchema };

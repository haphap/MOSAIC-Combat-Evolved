import type { ConsumerOutput } from "../types.js";
import { buildLayerTwoAgentNode, type LayerTwoAgentDeps } from "./_factory.js";
import { ConsumerSchema } from "./_schemas.js";
import { renderStandardSector, standardSectorSpec } from "./_spec.js";

export const consumerSpec = standardSectorSpec<ConsumerOutput>("consumer", ConsumerSchema);
export const REQUIRED_TOOLS = consumerSpec.requiredTools;
export const buildConsumerNode = (deps: LayerTwoAgentDeps) =>
  buildLayerTwoAgentNode(consumerSpec, deps);
export const renderConsumer = renderStandardSector;
export { ConsumerSchema };

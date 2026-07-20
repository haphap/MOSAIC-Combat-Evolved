/** Cross-sector relationships over the frozen accepted sector/security domain. */

import type { RelationshipMapperOutput } from "../types.js";
import {
  buildLayerTwoAgentNode,
  type LayerTwoAgentDeps,
  type LayerTwoAgentNode,
  type LayerTwoAgentSpec,
} from "./_factory.js";
import { RELATIONSHIP_MAPPER_FIELD_NAMES, RelationshipMapperSchema } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_relationship_graph_snapshot"] as const;

export const relationshipMapperSpec: LayerTwoAgentSpec<RelationshipMapperOutput> = {
  agentId: "relationship_mapper",
  schema: RelationshipMapperSchema,
  fieldNames: RELATIONSHIP_MAPPER_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderRelationshipMapper,
};

export function buildRelationshipMapperNode(deps: LayerTwoAgentDeps): LayerTwoAgentNode {
  return buildLayerTwoAgentNode(relationshipMapperSpec, deps);
}

export function renderRelationshipMapper(o: RelationshipMapperOutput): string {
  const factual = o.factual_edges
    .map((edge) => `${edge.source_entity}->${edge.target_entity}:${edge.edge_type}`)
    .join(" | ");
  return (
    `relationship_mapper analysis (${o.predictive_graph_status})\n` +
    `  factual_edges: ${factual || "(none)"}\n` +
    `  predictive_edges: ${o.predictive_edges.length}`
  );
}

export { RELATIONSHIP_MAPPER_FIELD_NAMES, RelationshipMapperSchema };

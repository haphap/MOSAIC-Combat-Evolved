/**
 * relationship_mapper Layer-2 cross-sector agent (Plan §5.2).
 *
 * Plan §5.2 wants `get_top_holdings_overlap` + `get_related_party_transactions`;
 * neither exists in Phase 0/1 (plan §14 #8). 2D.1 substitution:
 * derive contagion risks from the other 6 sector agents' sector_score signs +
 * north-flow sector breakdown. supply_chains uses a small hard-coded reference
 * map (semi equipment chain, EV chain, liquor chain) until Phase 4 ETF
 * holdings tools land.
 */

import type { RegimeSignal, RelationshipMapperOutput } from "../types.js";
import {
  buildLayerTwoAgentNode,
  type LayerTwoAgentDeps,
  type LayerTwoAgentNode,
  type LayerTwoAgentSpec,
} from "./_factory.js";
import { RELATIONSHIP_MAPPER_FIELD_NAMES, RelationshipMapperSchema } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_north_capital_flow",
  "get_lhb_ranking",
  "get_stock_research",
] as const;

export const relationshipMapperSpec: LayerTwoAgentSpec<RelationshipMapperOutput> = {
  agentId: "relationship_mapper",
  schema: RelationshipMapperSchema,
  fieldNames: RELATIONSHIP_MAPPER_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderRelationshipMapper,
  fallback: fallbackRelationshipMapper,
};

export function buildRelationshipMapperNode(deps: LayerTwoAgentDeps): LayerTwoAgentNode {
  return buildLayerTwoAgentNode(relationshipMapperSpec, deps);
}

export function renderRelationshipMapper(o: RelationshipMapperOutput): string {
  const chains = o.supply_chains
    .map((c) => `${c.name}[${c.tickers.join(",")}]:${c.risk}`)
    .join(" | ");
  const risks = o.contagion_risks.join(" | ");
  return (
    `relationship_mapper analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  supply_chains: ${chains}\n` +
    `  contagion_risks: ${risks}`
  );
}

export function fallbackRelationshipMapper(
  text: string,
  _regime: RegimeSignal | null,
): RelationshipMapperOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "relationship_mapper",
    supply_chains: [
      {
        name: "fallback",
        tickers: ["unknown"],
        risk: "analysis missing",
      },
    ],
    ownership_clusters: [],
    contagion_risks: ["analysis missing"],
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { RELATIONSHIP_MAPPER_FIELD_NAMES, RelationshipMapperSchema };

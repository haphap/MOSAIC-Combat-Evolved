/** burry Layer-3 (Plan §5.3): contrarian deep value / downside-first. */

import type { BurryOutput } from "../types.js";
import {
  buildLayerThreeAgentNode,
  fallbackSuperinvestorOutput,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { BurrySchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_superinvestor_candidate_snapshot"] as const;

export const burrySpec: LayerThreeAgentSpec<BurryOutput> = {
  agentId: "burry",
  schema: BurrySchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderBurry,
};

export function buildBurryNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(burrySpec, deps);
}

export function renderBurry(o: BurryOutput): string {
  const picks = o.picks
    .map((p) => `${p.ts_code}(${o.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `burry picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  status: ${o.selection_status}\n` +
    `  picks: ${picks || "(none)"}`
  );
}

export function fallbackBurry(text: string, _macroInputs?: unknown): BurryOutput {
  return fallbackSuperinvestorOutput("burry", text) as BurryOutput;
}

export { BurrySchema, SUPERINVESTOR_FIELD_NAMES };

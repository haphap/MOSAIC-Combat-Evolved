/**
 * druckenmiller Layer-3 superinvestor (Plan §5.3).
 *
 * Philosophy: macro / momentum, asymmetric trades, sector rotation +
 * policy catalyst pairs. Concentrated 3-5 names.
 */

import type { DruckenmillerOutput } from "../types.js";
import {
  buildLayerThreeAgentNode,
  fallbackSuperinvestorOutput,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { DruckenmillerSchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_superinvestor_candidate_snapshot"] as const;

export const druckenmillerSpec: LayerThreeAgentSpec<DruckenmillerOutput> = {
  agentId: "druckenmiller",
  schema: DruckenmillerSchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderDruckenmiller,
};

export function buildDruckenmillerNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(druckenmillerSpec, deps);
}

export function renderDruckenmiller(o: DruckenmillerOutput): string {
  const picks = o.picks
    .map((p) => `${p.ts_code}(${o.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `druckenmiller picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  status: ${o.selection_status}\n` +
    `  picks: ${picks || "(none)"}`
  );
}

export function fallbackDruckenmiller(text: string, _macroInputs?: unknown): DruckenmillerOutput {
  return fallbackSuperinvestorOutput("druckenmiller", text) as DruckenmillerOutput;
}

export { DruckenmillerSchema, SUPERINVESTOR_FIELD_NAMES };

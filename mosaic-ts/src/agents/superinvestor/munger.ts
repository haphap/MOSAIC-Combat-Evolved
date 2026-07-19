/** munger Layer-3 (Plan §5.3): quality moat / predictable compounding. */

import type { MungerOutput } from "../types.js";
import {
  buildLayerThreeAgentNode,
  fallbackSuperinvestorOutput,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { MungerSchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_superinvestor_candidate_snapshot"] as const;

export const mungerSpec: LayerThreeAgentSpec<MungerOutput> = {
  agentId: "munger",
  schema: MungerSchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderMunger,
};

export function buildMungerNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(mungerSpec, deps);
}

export function renderMunger(o: MungerOutput): string {
  const picks = o.picks
    .map((p) => `${p.ts_code}(${o.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `munger picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  status: ${o.selection_status}\n` +
    `  picks: ${picks || "(none)"}`
  );
}

export function fallbackMunger(text: string, _macroInputs?: unknown): MungerOutput {
  return fallbackSuperinvestorOutput("munger", text) as MungerOutput;
}

export { MungerSchema, SUPERINVESTOR_FIELD_NAMES };

/** ackman Layer-3 (Plan §5.3): quality compounder, pricing power + FCF + catalyst. */

import type { AckmanOutput } from "../types.js";
import {
  buildLayerThreeAgentNode,
  fallbackSuperinvestorOutput,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { AckmanSchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_superinvestor_candidate_snapshot"] as const;

export const ackmanSpec: LayerThreeAgentSpec<AckmanOutput> = {
  agentId: "ackman",
  schema: AckmanSchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderAckman,
};

export function buildAckmanNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(ackmanSpec, deps);
}

export function renderAckman(o: AckmanOutput): string {
  const picks = o.picks
    .map((p) => `${p.ts_code}(${o.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `ackman picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  status: ${o.selection_status}\n` +
    `  picks: ${picks || "(none)"}`
  );
}

export function fallbackAckman(text: string, _macroInputs?: unknown): AckmanOutput {
  return fallbackSuperinvestorOutput("ackman", text) as AckmanOutput;
}

export { AckmanSchema, SUPERINVESTOR_FIELD_NAMES };

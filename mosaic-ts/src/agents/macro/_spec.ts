import type { z } from "zod";
import type { AcceptedMacroTransmission, MacroAgentId, MacroAgentSubmission } from "../types.js";
import { MACRO_ROLE_CONTRACTS, MACRO_SUBMISSION_FIELD_NAMES } from "./_contracts.js";
import type { LayerOneAgentSpec } from "./_factory.js";

export function macroAgentSpec(
  agentId: MacroAgentId,
  schema: z.ZodType<MacroAgentSubmission>,
): LayerOneAgentSpec {
  return {
    agentId,
    schema,
    fieldNames: MACRO_SUBMISSION_FIELD_NAMES,
    requiredTools: MACRO_ROLE_CONTRACTS[agentId].requiredTools,
    render: renderMacroTransmission,
  };
}

export function renderMacroTransmission(output: AcceptedMacroTransmission): string {
  const drivers = output.key_drivers.map((driver) => `  - ${driver}`).join("\n");
  const channels = output.channels.join(", ");
  return (
    `${output.agent_id} transmission (confidence=${output.confidence.toFixed(2)})\n` +
    `  direction: ${output.direction}\n` +
    `  strength:  ${output.strength}/5\n` +
    `  horizon:   ${output.persistence_horizon}\n` +
    `  channels:  ${channels}\n` +
    `  key_drivers:\n${drivers}`
  );
}

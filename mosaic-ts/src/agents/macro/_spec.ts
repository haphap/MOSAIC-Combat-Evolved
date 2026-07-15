import type { z } from "zod";
import type { MacroAgentId, MacroAgentOutput } from "../types.js";
import { MACRO_OUTPUT_FIELD_NAMES, MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import type { LayerOneAgentSpec } from "./_factory.js";

export function macroAgentSpec<TOutput extends MacroAgentOutput>(
  agentId: TOutput["agent"],
  schema: z.ZodType<TOutput>,
): LayerOneAgentSpec<TOutput> {
  return {
    agentId,
    schema,
    fieldNames: MACRO_OUTPUT_FIELD_NAMES,
    requiredTools: MACRO_ROLE_CONTRACTS[agentId].requiredTools,
    render: renderMacroTransmission,
  };
}

export function renderMacroTransmission(output: MacroAgentOutput): string {
  const drivers = output.key_drivers.map((driver) => `  - ${driver}`).join("\n");
  const channels = output.channels.join(", ");
  return (
    `${output.agent} transmission (confidence=${output.confidence.toFixed(2)})\n` +
    `  direction: ${output.direction}\n` +
    `  strength:  ${output.strength}/5\n` +
    `  horizon:   ${output.horizon}\n` +
    `  channels:  ${channels}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackMacroTransmission<TAgent extends MacroAgentId>(
  agent: TAgent,
  text: string,
): Omit<Extract<MacroAgentOutput, { agent: TAgent }>, "claims" | "claim_refs"> {
  const driver = text.trim().slice(0, 80) || "analysis missing";
  return {
    agent,
    direction: "NEUTRAL",
    strength: 0,
    horizon: "DAYS",
    channels: ["insufficient evidence"],
    key_drivers: [driver],
    confidence: 0,
  } as Omit<Extract<MacroAgentOutput, { agent: TAgent }>, "claims" | "claim_refs">;
}

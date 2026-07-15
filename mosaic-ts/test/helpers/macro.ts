import type { MacroAgentId, MacroAgentOutput } from "../../src/agents/types.js";

export function macroOutput<TAgent extends MacroAgentId>(
  agent: TAgent,
  overrides: Partial<Extract<MacroAgentOutput, { agent: TAgent }>> = {},
): Extract<MacroAgentOutput, { agent: TAgent }> {
  return {
    agent,
    direction: "NEUTRAL",
    strength: 0,
    horizon: "WEEKS",
    channels: ["A-share risk premium"],
    key_drivers: ["fixture evidence"],
    confidence: 0.7,
    claims: [
      {
        claim_id: `${agent}-claim`,
        claim_type: "uncertainty",
        statement: "fixture uncertainty",
        structured_conclusion: { direction: "neutral" },
        evidence_refs: [],
        research_rule_refs: [],
      },
    ],
    claim_refs: [`${agent}-claim`],
    ...overrides,
  } as unknown as Extract<MacroAgentOutput, { agent: TAgent }>;
}

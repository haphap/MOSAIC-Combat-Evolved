import { MACRO_AGENT_IDS } from "../../src/agents/macro/_contracts.js";
import { STANDARD_SECTOR_ROLE_CONTRACTS } from "../../src/agents/sector/_contracts.js";
import type { SectorAgentOutput, StandardSectorAgentId } from "../../src/agents/types.js";

export function sectorOutput<TAgent extends StandardSectorAgentId>(
  agent: TAgent,
  overrides: Partial<Extract<SectorAgentOutput, { agent: TAgent }>> = {},
): Extract<SectorAgentOutput, { agent: TAgent }> {
  const directions = STANDARD_SECTOR_ROLE_CONTRACTS[agent].directionIds;
  if (directions.length < 2) throw new Error(`${agent} requires at least two fixture directions`);
  const claimId = `${agent}-claim`;
  return {
    agent,
    selection_status: "SELECTED",
    preferred_direction: {
      selection_role: "PREFERRED",
      direction_local_id: `${agent}-preferred`,
      direction_id: directions[0],
      allocation_action: "OVERWEIGHT",
      strength: 2,
      thesis: "fixture preferred direction",
      claim_refs: [claimId],
    },
    least_preferred_direction: {
      selection_role: "LEAST_PREFERRED",
      direction_local_id: `${agent}-least-preferred`,
      direction_id: directions[directions.length - 1],
      allocation_action: "UNDERWEIGHT",
      strength: 2,
      thesis: "fixture least-preferred direction",
      claim_refs: [claimId],
    },
    persistence_horizon: "WEEKS",
    confidence: 0.6,
    key_drivers: [
      { driver_local_id: `${agent}-driver`, summary: "fixture driver", claim_refs: [claimId] },
    ],
    risks: [{ risk_local_id: `${agent}-risk`, summary: "fixture risk", claim_refs: [claimId] }],
    claims: [
      {
        claim_id: claimId,
        claim_kind: "RISK_FLAG",
        statement: "fixture sector comparison",
        structured_conclusion: {
          conclusion_type: "SECTOR_DIRECTION",
          target_local_ref: `${agent}-preferred`,
          selection_status: "SELECTED",
          direction_id: directions[0],
          position_action: null,
          summary: "Fixture sector direction selection.",
        },
        evidence_ids: [`fixture:${agent}`],
        research_rule_refs: [],
      },
    ],
    claim_refs: [claimId],
    preferred_security_status: "NO_QUALIFIED_SECURITY",
    preferred_security_abstention_confidence: 0.4,
    long_picks: [],
    least_preferred_security_status: "NO_QUALIFIED_SECURITY",
    least_preferred_security_abstention_confidence: 0.4,
    short_or_avoid_picks: [],
    macro_input_attributions: MACRO_AGENT_IDS.map((macroAgentId) => ({
      agent_id: macroAgentId,
      target_type: "SUBMISSION_SUMMARY",
      target_local_ref: "$SUBMISSION",
      claim_refs_used: [],
      effect: "NOT_MATERIAL",
    })),
    ...overrides,
  } as Extract<SectorAgentOutput, { agent: TAgent }>;
}

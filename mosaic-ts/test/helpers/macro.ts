import { MACRO_ROLE_CONTRACTS } from "../../src/agents/macro/_contracts.js";
import type {
  AcceptedMacroTransmission,
  MacroAgentId,
  MacroAgentSubmission,
  MacroDirection,
} from "../../src/agents/types.js";

function claim(agent: MacroAgentId, component?: string) {
  return {
    claim_id: component ? `${agent}-${component}-claim` : `${agent}-claim`,
    claim_kind: "RISK_FLAG" as const,
    statement: "fixture risk flag",
    structured_conclusion: {
      conclusion_type: "MACRO_RISK",
      subject: component ?? agent,
      state: "fixture neutral state",
      a_share_transmission: "fixture A-share transmission",
      snapshot_echo_id: null,
      snapshot_metric: null,
      snapshot_value: null,
    },
    evidence_ids: [`fixture:${agent}`],
    research_rule_refs: [],
  };
}

export function macroSubmission(
  agent: MacroAgentId,
  overrides: Record<string, unknown> = {},
): MacroAgentSubmission {
  const contract = MACRO_ROLE_CONTRACTS[agent];
  const components = Object.keys(contract.components).sort();
  const base =
    contract.mode === "DIRECT"
      ? {
          mode: "DIRECT" as const,
          claims: [claim(agent)],
          key_drivers: ["fixture evidence"],
          signal: {
            direction: "NEUTRAL" as const,
            strength: 0 as const,
            persistence_horizon: "WEEKS" as const,
            evaluation_horizon_trading_days: 5 as const,
            confidence: 0.7,
            channels: ["A-share risk premium"],
            claim_refs: [`${agent}-claim`],
          },
        }
      : {
          mode: "COMPONENTS" as const,
          claims: components.map((component) => claim(agent, component)),
          key_drivers: ["fixture evidence"],
          components: components.map((component) => ({
            component,
            direction: "NEUTRAL" as const,
            strength: 0 as const,
            persistence_horizon: "WEEKS" as const,
            evaluation_horizon_trading_days: 5 as const,
            confidence: 0.7,
            channels: ["A-share risk premium"],
            claim_refs: [`${agent}-${component}-claim`],
          })),
        };
  return { ...base, ...overrides } as MacroAgentSubmission;
}

export function macroOutput(
  agent: MacroAgentId,
  overrides: Partial<AcceptedMacroTransmission> = {},
): AcceptedMacroTransmission {
  return {
    agent_id: agent,
    agent_contract_version: "macro_agent_contract_v2",
    prompt_behavior_version: "macro_prompt_behavior_v2",
    execution_behavior_version: "macro_execution_behavior_v2",
    component_weight_contract_version:
      MACRO_ROLE_CONTRACTS[agent].mode === "COMPONENTS" ? "macro_component_weights_v2" : null,
    direction: "NEUTRAL",
    strength: 0,
    persistence_horizon: "WEEKS",
    evaluation_horizon_trading_days: 5,
    model_confidence: 0.7,
    deterministic_data_quality: 1,
    confidence: 0.7,
    channels: ["A-share risk premium"],
    key_drivers: ["fixture evidence"],
    claims: [claim(agent)],
    claim_refs: [`${agent}-claim`],
    ...overrides,
  };
}

export function macroSignalOverride(direction: MacroDirection, strength: 0 | 1 | 2 | 3 | 4 | 5) {
  return { direction, strength };
}

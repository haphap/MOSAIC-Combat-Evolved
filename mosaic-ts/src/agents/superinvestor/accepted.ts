import type { DarwinianAgentBehaviorBinding } from "../../autoresearch/production_variant.js";
import type {
  AcceptedMacroInputAttribution,
  MacroAttributionTarget,
} from "../helpers/macro_attribution.js";
import type {
  SuperinvestorAgentId,
  SuperinvestorDriverSubmission,
  SuperinvestorOutput,
  SuperinvestorRiskSubmission,
  SuperinvestorSecurityPickSubmission,
} from "../types.js";

export type AcceptedSuperinvestorSelectionPayload =
  | {
      selection_status: "SELECTED";
      holding_period: "WEEKS" | "MONTHS" | "YEARS";
      picks: SuperinvestorSecurityPickSubmission[];
      key_drivers: SuperinvestorDriverSubmission[];
      risks: SuperinvestorRiskSubmission[];
      claims: SuperinvestorOutput["claims"];
      claim_refs: string[];
    }
  | {
      selection_status: "NO_QUALIFIED_CANDIDATES";
      holding_period: "WEEKS" | "MONTHS" | "YEARS";
      picks: [];
      key_drivers: SuperinvestorDriverSubmission[];
      risks: SuperinvestorRiskSubmission[];
      claims: SuperinvestorOutput["claims"];
      claim_refs: string[];
    };

export interface AcceptedSuperinvestorSelection {
  superinvestor_agent_id: SuperinvestorAgentId;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  selection: AcceptedSuperinvestorSelectionPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
  directional_confidence: number;
  abstention_confidence: number;
}

export interface ModelVisibleAcceptedSuperinvestorSelection {
  superinvestor_agent_id: SuperinvestorAgentId;
  selection: AcceptedSuperinvestorSelectionPayload;
  directional_confidence: number;
  abstention_confidence: number;
}

export function acceptedSuperinvestorSelectionPayload(
  output: SuperinvestorOutput,
): AcceptedSuperinvestorSelectionPayload {
  const common = {
    holding_period: output.holding_period,
    key_drivers: output.key_drivers,
    risks: output.risks,
    claims: output.claims,
    claim_refs: output.claim_refs,
  };
  return output.selection_status === "SELECTED"
    ? { selection_status: output.selection_status, picks: output.picks, ...common }
    : { selection_status: output.selection_status, picks: [], ...common };
}

export function superinvestorMacroAttributionTargets(
  output: SuperinvestorOutput,
): MacroAttributionTarget[] {
  return output.picks.map((pick) => ({
    target_type: "SECURITY_PICK",
    target_local_ref: pick.pick_local_id,
    target: pick,
  }));
}

export function buildAcceptedSuperinvestorSelection(input: {
  output: SuperinvestorOutput;
  behavior: DarwinianAgentBehaviorBinding;
  acceptedMacroInputAttributions: AcceptedMacroInputAttribution[];
}): AcceptedSuperinvestorSelection {
  const selected = input.output.selection_status === "SELECTED";
  return {
    superinvestor_agent_id: input.output.agent,
    agent_contract_version: input.behavior.agent_contract_version,
    prompt_behavior_version: input.behavior.prompt_behavior_version,
    execution_behavior_version: input.behavior.execution_behavior_version,
    selection: acceptedSuperinvestorSelectionPayload(input.output),
    accepted_macro_input_attributions: input.acceptedMacroInputAttributions,
    model_confidence: input.output.confidence,
    directional_confidence: selected ? input.output.confidence : 0,
    abstention_confidence: selected ? 0 : input.output.confidence,
  };
}

export function modelVisibleAcceptedSuperinvestorSelection(
  accepted: AcceptedSuperinvestorSelection,
): ModelVisibleAcceptedSuperinvestorSelection {
  return {
    superinvestor_agent_id: accepted.superinvestor_agent_id,
    selection: accepted.selection,
    directional_confidence: accepted.directional_confidence,
    abstention_confidence: accepted.abstention_confidence,
  };
}

import { describe, expect, it } from "vitest";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import { fallbackSuperinvestorOutput } from "../src/agents/superinvestor/_factory.js";
import {
  acceptedSuperinvestorSelectionPayload,
  buildAcceptedSuperinvestorSelection,
  modelVisibleAcceptedSuperinvestorSelection,
} from "../src/agents/superinvestor/accepted.js";

const behavior = {
  agent_contract_version: "superinvestor_selection_v2",
  prompt_behavior_version: "superinvestor_prompt_v2",
  execution_behavior_version: "superinvestor_execution_v2",
  component_weight_contract_version: null,
  reliability_adapter_contract_version: "explicit_identity_adapter_v1",
  confidence_semantics_contract_version: "superinvestor_confidence_v2",
};

function acceptedAttributions() {
  return MACRO_AGENT_IDS.map((agentId) => ({
    agent_id: agentId,
    usage_share: 0.1,
    target_type: "SUBMISSION_SUMMARY" as const,
    target_ref: `accepted-target:${agentId}`,
    target_hash: `sha256:${agentId.padEnd(64, "0").slice(0, 64)}`,
    claim_refs_used: [],
    effect: "NOT_MATERIAL" as const,
  }));
}

describe("accepted Superinvestor contract", () => {
  it("separates active selection confidence from abstention confidence", () => {
    const base = fallbackSuperinvestorOutput("munger", "fixture");
    const selected = {
      ...base,
      selection_status: "SELECTED" as const,
      confidence: 0.7,
      picks: [
        {
          pick_local_id: "pick-1",
          ts_code: "600519.SH",
          position_action: "LONG" as const,
          conviction: 0.7,
          thesis: "fixture thesis",
          claim_refs: base.claim_refs,
        },
      ],
    };
    const accepted = buildAcceptedSuperinvestorSelection({
      output: selected,
      behavior,
      acceptedMacroInputAttributions: acceptedAttributions(),
    });
    expect(accepted.directional_confidence).toBe(0.7);
    expect(accepted.abstention_confidence).toBe(0);
    expect(accepted.selection).not.toHaveProperty("confidence");
    expect(accepted.selection).not.toHaveProperty("macro_input_attributions");
  });

  it("keeps an explicit abstention forecast without creating a direction signal", () => {
    const output = { ...fallbackSuperinvestorOutput("burry", "fixture"), confidence: 0.8 };
    const accepted = buildAcceptedSuperinvestorSelection({
      output,
      behavior,
      acceptedMacroInputAttributions: acceptedAttributions(),
    });
    expect(accepted.directional_confidence).toBe(0);
    expect(accepted.abstention_confidence).toBe(0.8);
    expect(acceptedSuperinvestorSelectionPayload(output).picks).toEqual([]);
  });

  it("projects only the downstream model whitelist", () => {
    const accepted = buildAcceptedSuperinvestorSelection({
      output: fallbackSuperinvestorOutput("ackman", "fixture"),
      behavior,
      acceptedMacroInputAttributions: acceptedAttributions(),
    });
    const visible = modelVisibleAcceptedSuperinvestorSelection(accepted);
    expect(Object.keys(visible).sort()).toEqual([
      "abstention_confidence",
      "directional_confidence",
      "selection",
      "superinvestor_agent_id",
    ]);
    expect(visible).not.toHaveProperty("accepted_macro_input_attributions");
    expect(visible).not.toHaveProperty("model_confidence");
  });
});

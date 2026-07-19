import {
  type AcceptedAgentOutputStore,
  type AcceptedOutputRecordRef,
  acceptedOutputRefKey,
} from "../accepted_output.js";
import { MACRO_AGENT_IDS } from "../macro/_contracts.js";
import type { DailyCycleStateType } from "../state.js";
import type { AcceptedMacroTransmission, MacroAgentId } from "../types.js";

export function acceptedMacroOutputs(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): Record<MacroAgentId, AcceptedMacroTransmission> {
  if (!state.darwinian_runtime_binding) {
    return Object.fromEntries(
      MACRO_AGENT_IDS.map((agent) => {
        const output = state.layer1_outputs[agent];
        if (!output || output.agent_id !== agent) {
          throw new Error(`${agent}: accepted Macro transmission is unavailable`);
        }
        return [agent, output];
      }),
    ) as Record<MacroAgentId, AcceptedMacroTransmission>;
  }
  if (!store) throw new Error("production Macro transport requires the accepted-output store");
  return Object.fromEntries(
    MACRO_AGENT_IDS.map((agent) => {
      const ref = state.accepted_output_refs[acceptedOutputRefKey("MACRO_TRANSMISSION", agent)];
      if (ref?.accepted_output_kind !== "MACRO_TRANSMISSION" || ref.agent_id !== agent) {
        throw new Error(`${agent}: accepted Macro record reference is unavailable`);
      }
      const record = store.resolve<"MACRO_TRANSMISSION", AcceptedMacroTransmission>(
        ref as AcceptedOutputRecordRef<"MACRO_TRANSMISSION">,
      );
      if (
        record.graph_run_id !== state.trace_id ||
        record.cohort_id !== state.darwinian_runtime_binding?.cohort_id ||
        record.language !== state.darwinian_runtime_binding?.language ||
        record.as_of !== state.outcome_schedule_plan?.as_of
      ) {
        throw new Error(`${agent}: accepted Macro transport binding mismatch`);
      }
      return [agent, record.output.payload];
    }),
  ) as Record<MacroAgentId, AcceptedMacroTransmission>;
}

export function renderAcceptedMacroInputs(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): string {
  const lines = ["## Accepted Macro transmissions (no aggregate stance)"];
  if (!state.macro_input_gate) {
    lines.push("* macro_input_gate: NOT_READY");
    return lines.join("\n");
  }
  const outputs = acceptedMacroOutputs(state, store);
  lines.push(`* macro_input_gate: READY (${state.macro_input_gate.input_hash})`);
  lines.push(`* source_layer_snapshot_id: ${state.macro_input_gate.source_layer_snapshot_id}`);
  for (const agent of MACRO_AGENT_IDS) {
    const output = outputs[agent];
    const reliability = state.macro_input_gate.reliability_by_agent[agent];
    if (!reliability) throw new Error(`${agent}: accepted Macro usage share is unavailable`);
    lines.push(`### ${agent}`);
    lines.push(`* usage_share: ${reliability.usage_share.toFixed(6)}`);
    lines.push(`* output: ${JSON.stringify(modelVisibleAcceptedMacroTransmission(output))}`);
  }
  return lines.join("\n");
}

export function modelVisibleAcceptedMacroTransmission(output: AcceptedMacroTransmission) {
  return {
    direction: output.direction,
    strength: output.strength,
    persistence_horizon: output.persistence_horizon,
    evaluation_horizon_trading_days: output.evaluation_horizon_trading_days,
    confidence: output.confidence,
    channels: output.channels,
    claims: output.claims,
    claim_refs: output.claim_refs,
    key_drivers: output.key_drivers,
  };
}

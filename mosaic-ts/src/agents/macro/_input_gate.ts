import { createHash } from "node:crypto";
import type {
  DarwinianAgentBehaviorBinding,
  DarwinianUsageWeightSnapshot,
} from "../../autoresearch/production_variant.js";
import {
  type AcceptedAgentOutputStore,
  type AcceptedOutputRecordRef,
  acceptedOutputRefKey,
} from "../accepted_output.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type { AcceptedMacroTransmission, MacroInputGateReceipt } from "../types.js";
import {
  MACRO_AGENT_CONTRACT_VERSION,
  MACRO_AGENT_IDS,
  MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION,
  MACRO_EXECUTION_BEHAVIOR_VERSION,
  MACRO_PROMPT_BEHAVIOR_VERSION,
  MACRO_ROLE_CONTRACTS,
} from "./_contracts.js";

export function buildMacroInputGateNode(acceptedOutputStore?: AcceptedAgentOutputStore) {
  return async (state: DailyCycleStateType): Promise<DailyCycleStateUpdate> => {
    if (state.darwinian_runtime_binding && !state.darwinian_weight_snapshot) {
      throw new Error("macro_input_gate requires the frozen Darwinian v2 weight snapshot");
    }
    const acceptedRefs = state.darwinian_runtime_binding
      ? resolveProductionMacroOutputs(state, acceptedOutputStore)
      : null;
    return {
      macro_input_gate: validateMacroInputs(
        acceptedRefs?.outputs ?? state.layer1_outputs,
        state.darwinian_runtime_binding?.agent_behavior_bindings,
        state.darwinian_weight_snapshot ?? undefined,
        acceptedRefs?.refs,
      ),
    };
  };
}

function resolveProductionMacroOutputs(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): {
  outputs: Record<string, AcceptedMacroTransmission>;
  refs: Record<string, AcceptedOutputRecordRef<"MACRO_TRANSMISSION">>;
} {
  if (!store) throw new Error("macro_input_gate requires the accepted-output store");
  const outputs: Record<string, AcceptedMacroTransmission> = {};
  const refs: Record<string, AcceptedOutputRecordRef<"MACRO_TRANSMISSION">> = {};
  for (const agent of MACRO_AGENT_IDS) {
    const key = acceptedOutputRefKey("MACRO_TRANSMISSION", agent);
    const ref = state.accepted_output_refs[key];
    if (ref?.accepted_output_kind !== "MACRO_TRANSMISSION" || ref.agent_id !== agent) {
      throw new Error(`${agent}: named accepted Macro record reference is missing`);
    }
    const typedRef = ref as AcceptedOutputRecordRef<"MACRO_TRANSMISSION">;
    const record = store.resolve<"MACRO_TRANSMISSION", AcceptedMacroTransmission>(typedRef);
    if (
      record.graph_run_id !== state.trace_id ||
      record.cohort_id !== state.darwinian_runtime_binding?.cohort_id ||
      record.language !== state.darwinian_runtime_binding?.language ||
      record.as_of !== state.outcome_schedule_plan?.as_of
    ) {
      throw new Error(`${agent}: accepted Macro record run binding mismatch`);
    }
    outputs[agent] = record.output.payload;
    refs[agent] = typedRef;
  }
  return { outputs, refs };
}

export function validateMacroInputs(
  outputs: Readonly<Record<string, AcceptedMacroTransmission>>,
  behaviorBindings?: Readonly<Record<string, DarwinianAgentBehaviorBinding>>,
  weightSnapshot?: DarwinianUsageWeightSnapshot,
  acceptedRefs?: Readonly<Record<string, AcceptedOutputRecordRef<"MACRO_TRANSMISSION">>>,
): MacroInputGateReceipt {
  if (acceptedRefs) {
    const refIds = Object.keys(acceptedRefs).sort();
    const expectedRefIds = [...MACRO_AGENT_IDS].sort();
    if (refIds.join("\0") !== expectedRefIds.join("\0")) {
      throw new Error("macro_input_gate requires exactly ten accepted Macro record references");
    }
    for (const agent of MACRO_AGENT_IDS) {
      const ref = acceptedRefs[agent];
      if (ref?.accepted_output_kind !== "MACRO_TRANSMISSION" || ref.agent_id !== agent) {
        throw new Error(`${agent}: accepted Macro record reference owner mismatch`);
      }
    }
  }
  const actualIds = Object.keys(outputs).sort();
  const expectedIds = [...MACRO_AGENT_IDS].sort();
  if (actualIds.join("\0") !== expectedIds.join("\0")) {
    throw new Error(
      `macro_input_gate requires exactly ${expectedIds.join(", ")}; got ${actualIds.join(",")}`,
    );
  }
  const ordered = MACRO_AGENT_IDS.map((agent) => {
    const output = outputs[agent];
    if (!output || output.agent_id !== agent) throw new Error(`${agent}: accepted slot mismatch`);
    const binding = behaviorBindings?.[agent];
    const expectedBehavior = binding ?? {
      agent_contract_version: MACRO_AGENT_CONTRACT_VERSION,
      prompt_behavior_version: MACRO_PROMPT_BEHAVIOR_VERSION,
      execution_behavior_version: MACRO_EXECUTION_BEHAVIOR_VERSION,
      component_weight_contract_version:
        MACRO_ROLE_CONTRACTS[agent].mode === "COMPONENTS"
          ? MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION
          : null,
    };
    if (
      output.agent_contract_version !== expectedBehavior.agent_contract_version ||
      output.prompt_behavior_version !== expectedBehavior.prompt_behavior_version ||
      output.execution_behavior_version !== expectedBehavior.execution_behavior_version
    ) {
      throw new Error(`${agent}: accepted contract version mismatch`);
    }
    const expectedComponentVersion = expectedBehavior.component_weight_contract_version;
    if (output.component_weight_contract_version !== expectedComponentVersion) {
      throw new Error(`${agent}: component weight version mismatch`);
    }
    return output;
  });
  const weightByAgent = new Map((weightSnapshot?.weights ?? []).map((row) => [row.agent_id, row]));
  if (weightSnapshot) {
    if (weightSnapshot.weights.length !== 24 || new Set(weightByAgent).size !== 24) {
      throw new Error("macro_input_gate requires an exact 24-Agent Darwinian snapshot");
    }
    for (const agent of MACRO_AGENT_IDS) {
      if (!weightByAgent.has(agent)) throw new Error(`${agent}: Darwinian weight is missing`);
    }
  }
  const effective = Object.fromEntries(
    ordered.map((output) => {
      const row = weightByAgent.get(output.agent_id);
      const darwinWeight = row?.darwin_weight ?? 1;
      const operationalReliability = row?.operational_reliability_if_accepted ?? 1;
      if (
        !Number.isFinite(darwinWeight) ||
        darwinWeight <= 0 ||
        !Number.isFinite(operationalReliability) ||
        operationalReliability < 0 ||
        operationalReliability > 1
      ) {
        throw new Error(`${output.agent_id}: invalid Darwinian reliability metadata`);
      }
      return [
        output.agent_id,
        {
          effective_reliability: output.confidence * darwinWeight * operationalReliability,
          usage_share: 0,
          weight_record_id: row?.weight_record_id ?? null,
          reliability_record_id: row?.reliability_record_id ?? null,
        },
      ];
    }),
  ) as MacroInputGateReceipt["reliability_by_agent"];
  const denominator = Object.values(effective).reduce(
    (sum, row) => sum + row.effective_reliability,
    0,
  );
  if (!Number.isFinite(denominator) || denominator <= 0) {
    throw new Error("macro_input_gate rejects zero total effective reliability");
  }
  for (const agent of MACRO_AGENT_IDS) {
    effective[agent].usage_share = effective[agent].effective_reliability / denominator;
  }
  const sourceLayerBody = {
    accepted_outputs: acceptedRefs ? MACRO_AGENT_IDS.map((agent) => acceptedRefs[agent]) : ordered,
    usage_shares: Object.fromEntries(
      MACRO_AGENT_IDS.map((agent) => [agent, effective[agent].usage_share]),
    ),
    darwinian_snapshot_id: weightSnapshot?.darwinian_snapshot_id ?? null,
    darwinian_snapshot_hash: weightSnapshot?.darwinian_snapshot_hash ?? null,
  };
  const sourceLayerSnapshotHash = `sha256:${createHash("sha256")
    .update(canonicalJson(sourceLayerBody))
    .digest("hex")}`;
  const sourceLayerSnapshotId = `macro-source-layer:${sourceLayerSnapshotHash.slice("sha256:".length)}`;
  return {
    schema_version: "macro_input_gate_receipt_v1",
    accepted_agent_ids: [...MACRO_AGENT_IDS],
    accepted_count: 10,
    input_hash: sourceLayerSnapshotHash,
    source_layer_snapshot_id: sourceLayerSnapshotId,
    source_layer_snapshot_hash: sourceLayerSnapshotHash,
    darwinian_snapshot_id: weightSnapshot?.darwinian_snapshot_id ?? null,
    darwinian_snapshot_hash: weightSnapshot?.darwinian_snapshot_hash ?? null,
    reliability_by_agent: effective,
  };
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(sortJson(value));
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJson);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, sortJson(item)]),
    );
  }
  return value;
}

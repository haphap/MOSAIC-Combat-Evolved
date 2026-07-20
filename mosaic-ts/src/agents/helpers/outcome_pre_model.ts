import { NoEvaluationObjectStageSkipRecordSchema } from "../../autoresearch/outcome_stage_skip.js";
import type { BridgeApi } from "../../bridge/index.js";
import type {
  DailyCycleStateType,
  OutcomeLiveSourceAuthorityBinding,
  OutcomeOpportunityBinding,
  OutcomeRunSlot,
} from "../state.js";
import { AgentIdSchema } from "../tool_contract.js";

type OutcomeAuthorityKind = "SUPERINVESTOR" | "DECISION";
type OutcomePreModelDisposition = "RUN" | "SKIP";

export const LIVE_SOURCE_TOOL_BY_AGENT = {
  china: "get_china_macro_snapshot",
  us_economy: "get_us_macro_snapshot",
  eu_economy: "get_eu_macro_snapshot",
  central_bank: "get_central_bank_snapshot",
  us_financial_conditions: "get_us_financial_conditions_snapshot",
  euro_area_financial_conditions: "get_euro_area_financial_conditions_snapshot",
  commodities: "get_commodity_conditions_snapshot",
  geopolitical: "get_geopolitical_events_snapshot",
  market_breadth: "get_market_breadth_snapshot",
  institutional_flow: "get_market_positioning_snapshot",
  semiconductor: "get_sector_research_snapshot",
  technology: "get_sector_research_snapshot",
  energy: "get_sector_research_snapshot",
  biotech: "get_sector_research_snapshot",
  consumer: "get_sector_research_snapshot",
  industrials: "get_sector_research_snapshot",
  real_estate_construction: "get_sector_research_snapshot",
  financials: "get_sector_research_snapshot",
  agriculture: "get_sector_research_snapshot",
  relationship_mapper: "get_relationship_graph_snapshot",
} as const satisfies Readonly<Record<string, OutcomeLiveSourceAuthorityBinding["source_tool_id"]>>;

export interface LiveOutcomeFreezeResult {
  state: DailyCycleStateType;
  update: { outcome_opportunity_bindings: Record<string, OutcomeOpportunityBinding> } | null;
}

/** First operation for every formal L1/L2 node; no prompt or model work may precede it. */
export async function freezeLiveOutcomeOpportunity(input: {
  api: BridgeApi;
  state: DailyCycleStateType;
  agentId: keyof typeof LIVE_SOURCE_TOOL_BY_AGENT;
}): Promise<LiveOutcomeFreezeResult> {
  const { api, state, agentId } = input;
  if (!state.darwinian_runtime_binding) return { state, update: null };
  const schedule = state.outcome_schedule_plan;
  if (!schedule) throw new Error(`${agentId}: outcome schedule is unavailable before live freeze`);
  if (schedule.graph_run_id !== state.trace_id) {
    throw new Error(`${agentId}: outcome schedule graph run mismatch before live freeze`);
  }
  const slots = schedule.slots.filter((candidate) => candidate.agent_id === agentId);
  if (slots.length !== 1) {
    throw new Error(`${agentId}: outcome schedule slot is ambiguous before live freeze`);
  }
  const slot = slots[0];
  if (!slot) throw new Error(`${agentId}: outcome schedule slot is unavailable before live freeze`);
  assertSlotClosure(agentId, slot, schedule.outcome_schedule_plan_id, schedule.graph_run_id);
  if (slot.run_slot_kind === "DOWNSTREAM_ONLY") {
    if (state.outcome_opportunity_bindings[agentId] !== undefined) {
      throw new Error(`${agentId}: downstream-only slot cannot carry opportunity authority`);
    }
    return { state, update: null };
  }
  const scheduledSampleId = requiredText(
    slot.scheduled_sample_id,
    `${agentId}.scheduled_sample_id`,
  );
  if (typeof api.darwinianFreezeOutcomeOpportunity !== "function") {
    throw new Error(`${agentId}: live opportunity freeze API is unavailable`);
  }
  const frozen = await api.darwinianFreezeOutcomeOpportunity({
    outcome_schedule_plan_id: schedule.outcome_schedule_plan_id,
    scheduled_sample_id: scheduledSampleId,
    agent_id: AgentIdSchema.parse(agentId),
  });
  if (!frozen.run_allowed) {
    throw new Error(
      `${agentId}: live opportunity freeze blocked: ${frozen.blocker_reason ?? "UNKNOWN"}`,
    );
  }
  const authority = liveSourceAuthority(agentId, frozen.runtime_authority_binding);
  if (frozen.frozen_object_set_id != null || frozen.frozen_object_set_hash != null) {
    throw new Error(`${agentId}: L1/L2 live freeze cannot carry a stage object`);
  }
  const binding: OutcomeOpportunityBinding = {
    agent_id: agentId,
    scheduled_sample_id: scheduledSampleId,
    evaluation_opportunity_set_id: requiredText(
      frozen.evaluation_opportunity_set_id,
      `${agentId}.evaluation_opportunity_set_id`,
    ),
    evaluation_opportunity_set_hash: requiredSha256(
      frozen.evaluation_opportunity_set_hash,
      `${agentId}.evaluation_opportunity_set_hash`,
    ),
    frozen_object_set_id: null,
    frozen_object_set_hash: null,
    runtime_authority_binding: authority,
  };
  const prior = state.outcome_opportunity_bindings[agentId];
  if (prior !== undefined && JSON.stringify(prior) !== JSON.stringify(binding)) {
    throw new Error(`${agentId}: live opportunity retry changed its frozen binding`);
  }
  const update = { outcome_opportunity_bindings: { [agentId]: binding } };
  return {
    state: {
      ...state,
      outcome_opportunity_bindings: {
        ...state.outcome_opportunity_bindings,
        [agentId]: binding,
      },
    },
    update,
  };
}

export function liveOutcomeCapabilityRuntimeInput(
  state: DailyCycleStateType,
  agentId: keyof typeof LIVE_SOURCE_TOOL_BY_AGENT,
): { outcome_opportunity_authority: OutcomeLiveSourceAuthorityBinding } | Record<string, never> {
  if (!state.darwinian_runtime_binding) return {};
  if (!liveOutcomeIsScheduled(state, agentId)) return {};
  return {
    outcome_opportunity_authority: liveSourceAuthority(
      agentId,
      state.outcome_opportunity_bindings[agentId]?.runtime_authority_binding,
    ),
  };
}

export function assertLiveOutcomeSourceSnapshot(input: {
  state: DailyCycleStateType;
  agentId: keyof typeof LIVE_SOURCE_TOOL_BY_AGENT;
  sourceToolId: string;
  sourceSnapshotHash: unknown;
}): void {
  if (!input.state.darwinian_runtime_binding) return;
  if (!liveOutcomeIsScheduled(input.state, input.agentId)) return;
  const authority = liveSourceAuthority(
    input.agentId,
    input.state.outcome_opportunity_bindings[input.agentId]?.runtime_authority_binding,
  );
  if (
    input.sourceToolId !== authority.source_tool_id ||
    input.sourceSnapshotHash !== authority.source_snapshot_hash
  ) {
    throw new Error(`${input.agentId}: model tool snapshot differs from live opportunity freeze`);
  }
}

function liveOutcomeIsScheduled(
  state: DailyCycleStateType,
  agentId: keyof typeof LIVE_SOURCE_TOOL_BY_AGENT,
): boolean {
  const slots = state.outcome_schedule_plan?.slots.filter((slot) => slot.agent_id === agentId);
  if (slots?.length !== 1 || !slots[0]) {
    throw new Error(`${agentId}: live opportunity schedule slot is unavailable`);
  }
  return slots[0].run_slot_kind === "OUTCOME_SCHEDULED";
}

function liveSourceAuthority(
  agentId: keyof typeof LIVE_SOURCE_TOOL_BY_AGENT,
  value: unknown,
): OutcomeLiveSourceAuthorityBinding {
  if (!value || typeof value !== "object") {
    throw new Error(`${agentId}: live source authority binding is unavailable`);
  }
  const authority = value as Partial<OutcomeLiveSourceAuthorityBinding>;
  if (
    Object.keys(authority).sort().join("\0") !==
      ["domain_hash", "source_snapshot_hash", "source_tool_id"].join("\0") ||
    authority.source_tool_id !== LIVE_SOURCE_TOOL_BY_AGENT[agentId]
  ) {
    throw new Error(`${agentId}: live source authority fields mismatch`);
  }
  return {
    source_tool_id: authority.source_tool_id,
    source_snapshot_hash: requiredSha256(
      authority.source_snapshot_hash,
      `${agentId}.source_snapshot_hash`,
    ),
    domain_hash: requiredSha256(authority.domain_hash, `${agentId}.domain_hash`),
  };
}

export function preModelOutcomeDisposition(input: {
  state: DailyCycleStateType;
  agentId: string;
  stage: string;
  authorityKind: OutcomeAuthorityKind;
}): OutcomePreModelDisposition {
  const { state, agentId, stage, authorityKind } = input;
  if (!state.darwinian_runtime_binding) return "RUN";
  if (agentId === "cio" && stage === "cio_proposal") {
    assertCioProposalAlphaSourceClosure(state);
    return "RUN";
  }

  const schedule = state.outcome_schedule_plan;
  if (!schedule) throw new Error(`${agentId}: outcome schedule is unavailable before model call`);
  if (state.trace_id && schedule.graph_run_id !== state.trace_id) {
    throw new Error(`${agentId}: outcome schedule graph run mismatch before model call`);
  }
  const slots = schedule.slots.filter((candidate) => candidate.agent_id === agentId);
  if (slots.length !== 1) {
    throw new Error(`${agentId}: outcome schedule slot is ambiguous before model call`);
  }
  const slot = slots[0];
  if (!slot) throw new Error(`${agentId}: outcome schedule slot is unavailable before model call`);
  assertSlotClosure(agentId, slot, schedule.outcome_schedule_plan_id, schedule.graph_run_id);

  const stageSkip = (state.outcome_stage_skips as Readonly<Record<string, unknown>>)[agentId];
  const binding = state.outcome_opportunity_bindings[agentId];
  if (slot.run_slot_kind === "DOWNSTREAM_ONLY") {
    if (stageSkip !== undefined || binding !== undefined) {
      throw new Error(`${agentId}: downstream-only slot cannot carry opportunity authority`);
    }
    return "RUN";
  }
  if (slot.run_slot_kind !== "OUTCOME_SCHEDULED") {
    throw new Error(`${agentId}: outcome schedule slot kind is invalid before model call`);
  }
  const scheduledSampleId = requiredText(
    slot.scheduled_sample_id,
    `${agentId}.scheduled_sample_id`,
  );
  if (!binding) {
    throw new Error(`${agentId}: frozen opportunity binding is unavailable before model call`);
  }
  assertBindingClosure(agentId, scheduledSampleId, binding, authorityKind);

  if (stageSkip === undefined) return "RUN";
  if (agentId === "cio") {
    throw new Error("cio: final Decision opportunity cannot be skipped as an empty object set");
  }
  const parsed = NoEvaluationObjectStageSkipRecordSchema.parse(stageSkip);
  if (
    parsed.agent_id !== agentId ||
    parsed.graph_run_id !== schedule.graph_run_id ||
    parsed.outcome_schedule_plan_id !== schedule.outcome_schedule_plan_id ||
    parsed.outcome_schedule_slot_id !== slot.outcome_schedule_slot_id ||
    parsed.scheduled_sample_id !== scheduledSampleId ||
    parsed.track_key_hash !== slot.track_key_hash ||
    parsed.frozen_object_set_id !== binding.frozen_object_set_id ||
    parsed.frozen_object_set_hash !== binding.frozen_object_set_hash
  ) {
    throw new Error(`${agentId}: stage skip differs from frozen opportunity authority`);
  }
  return "SKIP";
}

function assertCioProposalAlphaSourceClosure(state: DailyCycleStateType): void {
  const disposition = preModelOutcomeDisposition({
    state,
    agentId: "alpha_discovery",
    stage: "alpha_discovery",
    authorityKind: "DECISION",
  });
  const ref = state.accepted_output_refs["ALPHA_DISCOVERY:alpha_discovery"];
  if (disposition === "SKIP") {
    if (ref !== undefined) {
      throw new Error("cio: Alpha stage skip cannot mask an accepted output before model call");
    }
    return;
  }
  if (ref?.accepted_output_kind !== "ALPHA_DISCOVERY" || ref.agent_id !== "alpha_discovery") {
    throw new Error("cio: accepted Alpha source is unavailable before model call");
  }
  requiredText(ref.accepted_output_id, "cio.alpha_source.accepted_output_id");
  requiredSha256(ref.accepted_output_hash, "cio.alpha_source.accepted_output_hash");
}

function assertSlotClosure(
  agentId: string,
  slot: OutcomeRunSlot,
  planId: string,
  graphRunId: string,
): void {
  if (
    slot.agent_id !== agentId ||
    slot.outcome_schedule_plan_id !== planId ||
    slot.graph_run_id !== graphRunId
  ) {
    throw new Error(`${agentId}: outcome schedule slot closure mismatch before model call`);
  }
  requiredText(slot.outcome_schedule_slot_id, `${agentId}.outcome_schedule_slot_id`);
  requiredSha256(slot.outcome_schedule_slot_hash, `${agentId}.outcome_schedule_slot_hash`);
  requiredSha256(slot.track_key_hash, `${agentId}.track_key_hash`);
}

function assertBindingClosure(
  agentId: string,
  scheduledSampleId: string,
  binding: OutcomeOpportunityBinding,
  authorityKind: OutcomeAuthorityKind,
): void {
  if (binding.agent_id !== agentId || binding.scheduled_sample_id !== scheduledSampleId) {
    throw new Error(`${agentId}: frozen opportunity binding owner/sample mismatch`);
  }
  requiredText(binding.evaluation_opportunity_set_id, `${agentId}.evaluation_opportunity_set_id`);
  requiredSha256(
    binding.evaluation_opportunity_set_hash,
    `${agentId}.evaluation_opportunity_set_hash`,
  );
  requiredText(binding.frozen_object_set_id, `${agentId}.frozen_object_set_id`);
  const frozenHash = requiredSha256(
    binding.frozen_object_set_hash,
    `${agentId}.frozen_object_set_hash`,
  );

  if (authorityKind === "SUPERINVESTOR") {
    requiredSha256(binding.runtime_candidate_scope_hash, `${agentId}.runtime_candidate_scope_hash`);
    const universeHash = requiredSha256(
      binding.runtime_candidate_universe_hash,
      `${agentId}.runtime_candidate_universe_hash`,
    );
    requiredSha256(binding.runtime_source_snapshot_hash, `${agentId}.runtime_source_snapshot_hash`);
    if (universeHash !== frozenHash) {
      throw new Error(`${agentId}: frozen candidate universe hash mismatch before model call`);
    }
    return;
  }

  const authority = binding.runtime_authority_binding;
  if (!authority) {
    throw new Error(`${agentId}: Decision runtime authority binding is unavailable`);
  }
  if (!("candidate_scope_hash" in authority)) {
    throw new Error(`${agentId}: Decision runtime authority shape mismatch`);
  }
  const expectedTool = {
    alpha_discovery: "get_alpha_candidate_snapshot",
    cro: "get_cro_risk_snapshot",
    autonomous_execution: "get_execution_snapshot",
    cio: "get_cio_decision_snapshot",
  }[agentId];
  if (!expectedTool || authority.source_tool_id !== expectedTool) {
    throw new Error(`${agentId}: Decision runtime authority tool mismatch`);
  }
  for (const field of [
    "source_snapshot_hash",
    "candidate_scope_hash",
    "candidate_universe_hash",
    "upstream_accepted_output_refs_hash",
  ] as const) {
    requiredSha256(authority[field], `${agentId}.runtime_authority_binding.${field}`);
  }
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value.trim();
}

function requiredSha256(value: unknown, label: string): string {
  const text = requiredText(value, label);
  if (!/^sha256:[0-9a-f]{64}$/.test(text)) {
    throw new Error(`${label} must be lowercase sha256`);
  }
  return text;
}

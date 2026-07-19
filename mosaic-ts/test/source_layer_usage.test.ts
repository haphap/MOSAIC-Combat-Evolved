import { describe, expect, it } from "vitest";
import {
  deriveSectorUsageReceipt,
  deriveSuperinvestorUsageReceipt,
  renderAcceptedSectorInputs,
  renderAcceptedSuperinvestorInputs,
} from "../src/agents/helpers/source_layer_usage.js";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import { emptyCurrentPositions, emptyLayer4, emptyPositionAudit } from "../src/agents/state.js";
import { fallbackSuperinvestorOutput } from "../src/agents/superinvestor/_factory.js";
import type { SuperinvestorOutput } from "../src/agents/types.js";
import type {
  NoEvaluationObjectStageSkipAgentId,
  NoEvaluationObjectStageSkipRecord,
} from "../src/autoresearch/outcome_stage_skip.js";
import type {
  DarwinianUsageWeightRow,
  DarwinianUsageWeightSnapshot,
} from "../src/autoresearch/production_variant.js";
import { sectorOutput } from "./helpers/sector.js";

function state(): DailyCycleStateType {
  return {
    messages: [],
    active_cohort: "cohort_default",
    as_of_date: "2026-07-17",
    mode: "backtest",
    trace_id: "source-layer-test",
    darwinian_runtime_binding: null,
    darwinian_weight_snapshot: weights(),
    component_weight_snapshot: null,
    component_calibration_inputs: {},
    outcome_schedule_plan: null,
    outcome_stage_skips: {},
    accepted_output_refs: {},
    continuity_context: {},
    lesson_context: {},
    method_context: {},
    layer1_outputs: {},
    macro_input_gate: null,
    layer2_outputs: {},
    layer3_outputs: {},
    layer4_outputs: emptyLayer4(),
    current_positions: emptyCurrentPositions(),
    position_reviews: [],
    position_audit: emptyPositionAudit(),
    portfolio_actions: [],
    replay_triggered: false,
    llm_calls: [],
  };
}

function weightRow(agentId: string): DarwinianUsageWeightRow {
  return {
    agent_id: agentId,
    usage_track_key_hash: `usage:${agentId}`,
    weight_record_id: `weight:${agentId}`,
    weight_record_hash: `sha256:${"a".repeat(64)}`,
    record_kind: "MATURE_UPDATE",
    darwin_weight: agentId === "technology" ? 2 : 1,
    previous_weight_record_id: null,
    n_eligible_scores: 30,
    scoring_window_hash: `sha256:${"b".repeat(64)}`,
    update_event_id: "event-1",
    effective_at: "2026-07-16T00:00:00+08:00",
    reliability_record_id: `reliability:${agentId}`,
    reliability_record_hash: `sha256:${"c".repeat(64)}`,
    operational_reliability: 1,
    operational_reliability_if_accepted: 1,
    reliability_state: "OBSERVED",
    accountable_count: 30,
    accepted_count: 30,
  };
}

function weights(): DarwinianUsageWeightSnapshot {
  const agentIds = [
    ...AGENTS_BY_LAYER.macro,
    ...AGENTS_BY_LAYER.sector,
    ...AGENTS_BY_LAYER.superinvestor,
  ];
  return {
    darwinian_snapshot_id: "darwin-snapshot-1",
    darwinian_snapshot_hash: `sha256:${"d".repeat(64)}`,
    schema_version: "darwinian_usage_weight_snapshot_v2",
    production_variant_roster_id: "roster-1",
    production_variant_roster_revision_id: "revision-1",
    execution_behavior_release_id: "release-1",
    cohort_id: "cohort_default",
    language: "zh",
    as_of: "2026-07-17T00:00:00+08:00",
    weights: agentIds.map(weightRow),
  };
}

function superOutput(
  agent: SuperinvestorOutput["agent"],
  confidence: number,
  selected = true,
): SuperinvestorOutput {
  const base = fallbackSuperinvestorOutput(agent, "fixture");
  if (!selected) return { ...base, confidence };
  return {
    ...base,
    selection_status: "SELECTED",
    picks: [
      {
        pick_local_id: `${agent}-pick-1`,
        ts_code: "600519.SH",
        position_action: "LONG",
        thesis: "fixture",
        conviction: 0.7,
        claim_refs: [`fallback-${agent}-claim`],
      },
    ],
    holding_period: "MONTHS",
    confidence,
  };
}

function stageSkip(agentId: NoEvaluationObjectStageSkipAgentId): NoEvaluationObjectStageSkipRecord {
  return {
    stage_skip_id: `skip:${agentId}`,
    stage_skip_hash: `sha256:${"1".repeat(64)}`,
    schema_version: "no_evaluation_object_stage_skip_v2",
    graph_run_id: "source-layer-test",
    outcome_schedule_plan_id: "plan-1",
    outcome_schedule_slot_id: `slot:${agentId}`,
    scheduled_sample_id: `sample:${agentId}`,
    track_key_hash: `sha256:${"2".repeat(64)}`,
    agent_id: agentId,
    skip_reason: "NO_EVALUATION_OBJECT",
    frozen_object_set_id: `set:${agentId}`,
    frozen_object_set_hash: `sha256:${"3".repeat(64)}`,
    member_count: 0,
    model_invoked: false,
    eligibility_audit_id: `audit:${agentId}`,
    eligibility_audit_revision_id: `revision:${agentId}`,
    eligibility_audit_revision_hash: `sha256:${"4".repeat(64)}`,
    evidence_ids: [`evidence:${agentId}`],
    causal_dedupe_key: `sha256:${"5".repeat(64)}`,
    recorded_at: "2026-07-17T09:00:00+08:00",
  };
}

describe("source-layer Darwinian usage", () => {
  it("normalizes Sector confidence × weight × operational reliability", () => {
    const input = state();
    input.layer2_outputs = {
      technology: sectorOutput("technology", { confidence: 0.8 }),
      agriculture: sectorOutput("agriculture", { confidence: 0.4 }),
    };
    const receipt = deriveSectorUsageReceipt(input);
    expect(receipt.source_layer_signal_state).toBe("SIGNAL_SET_READY");
    expect(receipt.reliability_by_agent.technology?.usage_share).toBeCloseTo(0.8);
    expect(receipt.reliability_by_agent.agriculture?.usage_share).toBeCloseTo(0.2);
    const rendered = renderAcceptedSectorInputs(input);
    expect(rendered).toContain("usage_share: 0.800000");
    expect(rendered).not.toContain("\n* abstention_confidence:");
    expect(rendered).not.toContain("sector_runtime_binding");
    expect(rendered).not.toContain("macro_input_attributions");
  });

  it("does not turn rejected Sector stages into fake directional weights", () => {
    const input = state();
    expect(() => deriveSectorUsageReceipt(input)).toThrow("SECTOR roster is empty");
  });

  it("normalizes accepted Superinvestor selections and keeps abstention separate", () => {
    const input = state();
    input.layer3_outputs = {
      druckenmiller: superOutput("druckenmiller", 0.6),
      munger: superOutput("munger", 0.4),
      burry: superOutput("burry", 0.9, false),
      ackman: superOutput("ackman", 0.8, false),
    };
    const receipt = deriveSuperinvestorUsageReceipt(input);
    expect(receipt.reliability_by_agent.druckenmiller?.usage_share).toBeCloseTo(0.6);
    expect(receipt.reliability_by_agent.munger?.usage_share).toBeCloseTo(0.4);
    expect(receipt.reliability_by_agent.burry?.usage_share).toBe(0);
    expect(receipt.reliability_by_agent.burry?.abstention_confidence).toBe(0.9);
    const rendered = renderAcceptedSuperinvestorInputs(input);
    expect(rendered).not.toContain("weight_record_id");
    expect(rendered).not.toContain("operational_reliability");
  });

  it("keeps empty Superinvestor opportunity slots as zero-usage stage skips", () => {
    const input = state();
    input.layer3_outputs = {
      druckenmiller: superOutput("druckenmiller", 0.6),
      munger: superOutput("munger", 0.4),
    };
    input.outcome_stage_skips = {
      burry: stageSkip("burry"),
      ackman: stageSkip("ackman"),
    };
    const receipt = deriveSuperinvestorUsageReceipt(input);
    expect(receipt.accepted_agent_ids).toEqual(["druckenmiller", "munger"]);
    expect(receipt.stage_skipped_agent_ids).toEqual(["ackman", "burry"]);
    expect(receipt.reliability_by_agent.druckenmiller?.usage_share).toBeCloseTo(0.6);
    expect(receipt.reliability_by_agent.munger?.usage_share).toBeCloseTo(0.4);
    expect(receipt.reliability_by_agent.burry).toBeUndefined();
    const rendered = renderAcceptedSuperinvestorInputs(input);
    expect(rendered).toContain("source_entry_status: NO_EVALUATION_OBJECT");
    expect(rendered).toContain('"agent_id":"burry"');
    expect(rendered).not.toContain("stage_skip_hash");
  });

  it("allows all four Superinvestor slots to skip without synthesizing weights", () => {
    const input = state();
    input.outcome_stage_skips = Object.fromEntries(
      AGENTS_BY_LAYER.superinvestor.map((agentId) => [agentId, stageSkip(agentId)]),
    );
    const receipt = deriveSuperinvestorUsageReceipt(input);
    expect(receipt.source_layer_signal_state).toBe("NO_DIRECTIONAL_SIGNAL");
    expect(receipt.accepted_agent_ids).toEqual([]);
    expect(Object.keys(receipt.reliability_by_agent)).toEqual([]);
  });
});

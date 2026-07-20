import { describe, expect, it } from "vitest";
import {
  freezeCroReview,
  freezeCroStageSkip,
  freezeExecutionStageSkip,
  Layer4RuntimeContractError,
} from "../src/agents/decision/layer4_runtime.js";
import type { CandidateTargetState } from "../src/agents/types.js";
import {
  type NoEvaluationObjectStageSkipAgentId,
  type NoEvaluationObjectStageSkipRecord,
  parseOutcomeStageSkips,
} from "../src/autoresearch/outcome_stage_skip.js";

function stageSkip(agentId: NoEvaluationObjectStageSkipAgentId): NoEvaluationObjectStageSkipRecord {
  return {
    stage_skip_id: `skip:${agentId}`,
    stage_skip_hash: `sha256:${"1".repeat(64)}`,
    schema_version: "no_evaluation_object_stage_skip_v2",
    graph_run_id: "run-1",
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

function candidate(actions: CandidateTargetState["portfolio_actions"] = []): CandidateTargetState {
  return {
    schema_version: "portfolio.candidate_target_state.v1",
    run_id: "run-1",
    cohort: "cohort_default",
    as_of_date: "2026-07-17",
    proposal_hash: `sha256:${"6".repeat(64)}`,
    l4_run_snapshot_hash: `sha256:${"7".repeat(64)}`,
    candidate_target_hash: `sha256:${"8".repeat(64)}`,
    position_snapshot_hash: null,
    previous_target_hash: null,
    market_data_vintage_hash: `sha256:${"9".repeat(64)}`,
    portfolio_actions: actions,
    confidence: 0.5,
    frozen: true,
  };
}

describe("no-evaluation-object stage skip", () => {
  it("parses the runtime record and rejects a map owner mismatch", () => {
    const skip = stageSkip("burry");
    expect(parseOutcomeStageSkips({ burry: skip })).toEqual({ burry: skip });
    expect(() => parseOutcomeStageSkips({ ackman: skip })).toThrow(/owner mismatch/);
  });

  it("creates deterministic internal control states without accepted Agent outputs", () => {
    const frozenCandidate = candidate();
    const cro = freezeCroStageSkip("run-1", frozenCandidate, stageSkip("cro"));
    expect(cro.source_status).toBe("NO_EVALUATION_OBJECT");
    expect(cro.output.confidence).toBe(0);
    const execution = freezeExecutionStageSkip(
      "run-1",
      frozenCandidate,
      cro,
      stageSkip("autonomous_execution"),
    );
    expect(execution.source_status).toBe("NO_EVALUATION_OBJECT");
    expect(execution.output.trades).toEqual([]);
  });

  it("cannot use a stage skip to bypass non-empty candidate or order-intent domains", () => {
    const held = candidate([
      {
        ticker: "600519.SH",
        action: "HOLD",
        target_weight: 0.1,
        delta_weight: 0,
        holding_period: "1Y",
        dissent_notes: "",
      },
    ]);
    expect(() => freezeCroStageSkip("run-1", held, stageSkip("cro"))).toThrow(
      Layer4RuntimeContractError,
    );
    const empty = candidate();
    const cro = freezeCroStageSkip("run-1", empty, stageSkip("cro"));
    const actionable = candidate([
      {
        ticker: "600519.SH",
        action: "BUY",
        target_weight: 0.1,
        delta_weight: 0.1,
        holding_period: "1Y",
        dissent_notes: "",
      },
    ]);
    expect(() =>
      freezeExecutionStageSkip("run-1", actionable, cro, stageSkip("autonomous_execution")),
    ).toThrow(Layer4RuntimeContractError);
  });

  it("allows execution stage skip when a CRO control reduces the frozen delta to zero", () => {
    const controlled = candidate([
      {
        ticker: "600519.SH",
        action: "BUY",
        current_weight: 0.1,
        target_weight: 0.2,
        delta_weight: 0.1,
        holding_period: "1Y",
        dissent_notes: "",
      },
    ]);
    const cro = freezeCroReview("run-1", controlled, {
      agent: "cro",
      review_disposition: "REVIEW_ACTIONS",
      rejected_picks: [],
      required_adjustments: [
        {
          action_local_id: "cap-to-current",
          ticker: "600519.SH",
          adjustment: "CAP_WEIGHT",
          max_target_weight: 0.1,
          reason: "do not increase the current position",
        },
      ],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.8,
    });

    expect(
      freezeExecutionStageSkip("run-1", controlled, cro, stageSkip("autonomous_execution")).output
        .execution_disposition,
    ).toBe("NO_DELTA");
  });
});

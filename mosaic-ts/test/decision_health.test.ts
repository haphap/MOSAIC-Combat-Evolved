import { describe, expect, it } from "vitest";
import type { DailyCycleStateType } from "../src/agents/state.js";
import { emptyCurrentPositions, emptyLayer4 } from "../src/agents/state.js";
import { evaluateHistoricalDecisionHealth } from "../src/backtest/decision_health.js";

function acceptedCalls() {
  return Array.from({ length: 26 }, (_, index) => ({
    ts: "2026-01-01T00:00:00Z",
    agent: index === 25 ? "cio" : `agent_${index}`,
    model: "fake",
    prompt_tokens: 1,
    completion_tokens: 1,
    provider: "fake",
    cost_usd: 0,
    agent_run_audit: {
      schema_version: "agent_run_audit_v1" as const,
      run_id: "run-1",
      agent: index === 25 ? "cio" : `agent_${index}`,
      stage: index === 25 ? "cio_final" : `stage_${index}`,
      status: "accepted" as const,
      output_source: "structured_primary" as const,
      attempt_count: 1,
      repair_count: 0,
      stop_reason: "accepted" as const,
      reason_codes: [],
      prompt_hash: `prompt-${index}`,
      schema_hash: `schema-${index}`,
      evidence_hash: `evidence-${index}`,
      output_hash: `output-${index}`,
      attempts: [],
    },
  }));
}

function state(): DailyCycleStateType {
  return {
    messages: [],
    active_cohort: "history_walkforward_2009",
    as_of_date: "2009-01-05",
    mode: "backtest",
    trace_id: "run-1",
    continuity_context: {},
    lesson_context: {},
    method_context: {},
    layer1_outputs: {},
    layer1_consensus: null,
    layer2_outputs: {},
    layer2_consensus: null,
    layer3_outputs: {},
    layer4_outputs: emptyLayer4(),
    current_positions: emptyCurrentPositions(),
    position_reviews: [],
    position_audit: {
      position_snapshot_hash: null,
      snapshot_status: "empty_confirmed",
      position_source: "empty_confirmed",
      source_error_code: null,
      positions_loaded: 0,
      positions_reviewed: 0,
      positions_unreviewed: 0,
      hold_count: 0,
      add_count: 0,
      reduce_count: 0,
      exit_count: 0,
      stale_thesis_count: 0,
      stop_loss_override_count: 0,
      target_current_drift_count: 0,
    },
    portfolio_actions: [],
    replay_triggered: false,
    llm_calls: [],
  };
}

function withUpstreamCandidate(value: DailyCycleStateType): DailyCycleStateType {
  return {
    ...value,
    layer3_outputs: {
      munger: {
        agent: "munger",
        picks: [
          {
            ticker: "600519.SH",
            conviction: 0.8,
            holding_period: "1Y",
            thesis: "quality",
          },
        ],
        philosophy_note: "quality",
        key_drivers: ["quality"],
        confidence: 0.8,
      },
    },
  };
}

describe("evaluateHistoricalDecisionHealth", () => {
  it("fails before fallback classification when all stages were not accepted", () => {
    const input = withUpstreamCandidate(state());
    input.layer4_outputs.runtime = {
      l4_run_snapshot_bundle: null,
      cio_proposal: null,
      candidate_target_state: null,
      position_review_state: null,
      portfolio_exposure_state: null,
      cro_review_state: null,
      execution_feasibility_state: null,
      final_target_state: null,
      portfolio_summary: null,
      cio_final_knob_snapshot: null,
      resolved_source_statuses: [],
      source_evidence_observations: [],
      stage_trace: [
        {
          sequence: 1,
          stage: "cio_proposal",
          operation: "agent_run",
          status: "fallback",
          reason_codes: ["CLAIM_EVIDENCE_GRAPH_REJECTED"],
          input_hashes: {},
          output_hashes: {},
        },
      ],
    };

    expect(evaluateHistoricalDecisionHealth(input)).toMatchObject({
      upstreamCandidateCount: 1,
      actionCount: 0,
      fallbackReasonCodes: ["CLAIM_EVIDENCE_GRAPH_REJECTED"],
      failureCode: "UNACCEPTED_AGENT_STAGE",
    });
  });

  it("rejects an unclassified empty decision on the first day", () => {
    const input = withUpstreamCandidate(state());
    input.llm_calls = acceptedCalls();
    expect(evaluateHistoricalDecisionHealth(input)).toMatchObject({
      consecutiveEmptyDecisionDays: 1,
      failureCode: "UNCLASSIFIED_EMPTY_DECISION",
    });
  });

  it("accepts explicit evidence-gated ALL_CASH", () => {
    const input = withUpstreamCandidate(state());
    input.llm_calls = acceptedCalls();
    input.layer4_outputs.cio = {
      agent: "cio",
      decision_disposition: "ALL_CASH",
      decision_reason: "risk evidence supports cash",
      decision_claim_refs: ["claim-1"],
      portfolio_actions: [],
      confidence: 0.7,
      claims: [],
      claim_refs: ["claim-1"],
    };
    expect(evaluateHistoricalDecisionHealth(input).failureCode).toBeNull();
  });

  it("resets the empty streak when CIO emits an action", () => {
    const input = withUpstreamCandidate(state());
    input.portfolio_actions = [
      {
        ticker: "600519.SH",
        action: "BUY",
        target_weight: 0.04,
        holding_period: "1Y",
        dissent_notes: "",
      },
    ];
    input.llm_calls = acceptedCalls();
    input.layer4_outputs.cio = {
      agent: "cio",
      decision_disposition: "TARGET_PORTFOLIO",
      decision_reason: "accepted target",
      decision_claim_refs: ["claim-1"],
      portfolio_actions: input.portfolio_actions,
      confidence: 0.7,
      claims: [],
      claim_refs: ["claim-1"],
    };

    expect(evaluateHistoricalDecisionHealth(input, 2)).toMatchObject({
      actionCount: 1,
      consecutiveEmptyDecisionDays: 0,
      failureCode: null,
    });
  });
});

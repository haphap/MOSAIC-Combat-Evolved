/**
 * Bulk smoke test for the 4 Layer-4 decision agents (Plan §11.2 sub-step 2D.3).
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage, ToolMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { frozenAlphaCandidatesFromToolLoop } from "../src/agents/decision/_factory.js";
import {
  renderJanusRegimeStub,
  renderLayer1Context,
  renderLayer2Context,
  renderLayer3Context,
  renderLayer4PeerContext,
} from "../src/agents/decision/_user_context.js";
import {
  alphaDiscoverySpec,
  buildAlphaDiscoveryNode,
  fallbackAlphaDiscovery,
  renderAlphaDiscovery,
} from "../src/agents/decision/alpha_discovery.js";
import {
  autonomousExecutionSpec,
  buildAutonomousExecutionNode,
  fallbackAutonomousExecution,
  renderAutonomousExecution,
} from "../src/agents/decision/autonomous_execution.js";
import {
  buildCioNode,
  buildCioProposalNode,
  cioProposalSpec,
  cioSpec,
  fallbackCio,
  renderCio,
} from "../src/agents/decision/cio.js";
import { buildCroNode, croSpec, fallbackCro, renderCro } from "../src/agents/decision/cro.js";
import {
  assertL4RunSnapshotStage,
  emptyLayer4RuntimeState,
  freezeCioProposal,
  freezeCroReview,
  freezeExecutionFeasibility,
  freezeFinalTarget,
  freezeL4RunSnapshotBundle,
  Layer4RuntimeContractError,
  missingPreviousTargetState,
  previousTargetStateFromFinal,
  updateLayer4Runtime,
} from "../src/agents/decision/layer4_runtime.js";
import {
  PositionActionValidationError,
  validateCioPositionActions,
} from "../src/agents/decision/position_validator.js";
import { AgentRunContractError } from "../src/agents/helpers/agent_run_contract.js";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import { validateMacroInputs } from "../src/agents/macro/_input_gate.js";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../src/agents/state.js";
import { fallbackSuperinvestorOutput } from "../src/agents/superinvestor/_factory.js";
import type {
  AutoExecOutput,
  CioOutput,
  CroOutput,
  CurrentPositionsSnapshot,
  Layer4Outputs,
  PortfolioAction,
  SemiconductorOutput,
  SuperinvestorOutput,
} from "../src/agents/types.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/types.js";
import { fakeAgentStructuredOutput } from "../src/cli/fake_agent_output.js";
import { validateFinalTargetNode } from "../src/graph/layer4.js";
import type { LlmHandle } from "../src/llm/factory.js";
import { macroOutput } from "./helpers/macro.js";
import { sectorOutput } from "./helpers/sector.js";

describe("frozen Alpha candidate snapshot", () => {
  it("extracts exact pairs and rejects constraint-conflicting domains", () => {
    const message = (payload: unknown) =>
      new ToolMessage({
        content: JSON.stringify(payload),
        tool_call_id: "alpha-tool-call",
      });
    const status = [
      {
        name: "get_alpha_candidate_snapshot",
        call_id: "alpha-tool-call",
        called: true,
        failed: false,
        missing: false,
        fallback: false,
        cache_hit: false,
      },
    ];
    expect(
      frozenAlphaCandidatesFromToolLoop(
        [
          message({
            candidate_universe: [
              { candidate_ref: "candidate-b", ts_code: "000001.SZ" },
              { candidate_ref: "candidate-a", ticker: "600000.sh" },
            ],
            constraints: { cash_only: false, allow_new_positions: true },
          }),
        ],
        status,
      ),
    ).toEqual([
      { candidate_ref: "candidate-a", ts_code: "600000.SH" },
      { candidate_ref: "candidate-b", ts_code: "000001.SZ" },
    ]);
    expect(() =>
      frozenAlphaCandidatesFromToolLoop(
        [
          message({
            candidate_universe: [{ candidate_ref: "candidate-a", ts_code: "600000.SH" }],
            constraints: { cash_only: true, allow_new_positions: false },
          }),
        ],
        status,
      ),
    ).toThrow(/conflicts/);
  });
});

// ============================================================ AGENTS_BY_LAYER

describe("AGENTS_BY_LAYER.decision", () => {
  it("lists the canonical 4 decision agents from Plan §5.4", () => {
    expect([...AGENTS_BY_LAYER.decision]).toEqual([
      "cro",
      "alpha_discovery",
      "autonomous_execution",
      "cio",
    ]);
  });
});

// ============================================================ spec sanity

describe("each Layer-4 spec wires correct fields", () => {
  it("cro", () => {
    expect(croSpec.agentId).toBe("cro");
    expect(croSpec.runtimeStage).toBe("cro_review");
    expect(croSpec.stateUpdateField).toBe("cro");
    expect(croSpec.fieldNames).toEqual([
      "agent_id",
      "review_disposition",
      "candidate_actions",
      "correlated_risks",
      "black_swan_scenarios",
      "confidence",
      "claims",
      "claim_refs",
      "macro_input_attributions",
    ]);
    expect(croSpec.requiredTools).toEqual(["get_cro_risk_snapshot", "get_role_event_snapshot"]);
  });
  it("alpha_discovery", () => {
    expect(alphaDiscoverySpec.agentId).toBe("alpha_discovery");
    expect(alphaDiscoverySpec.runtimeStage).toBe("alpha_discovery");
    expect(alphaDiscoverySpec.stateUpdateField).toBe("alpha_discovery");
    expect(alphaDiscoverySpec.fieldNames).toEqual([
      "agent_id",
      "discovery_disposition",
      "novel_picks",
      "key_drivers",
      "risks",
      "confidence",
      "claims",
      "claim_refs",
      "macro_input_attributions",
    ]);
    expect(alphaDiscoverySpec.requiredTools).toEqual([
      "get_alpha_candidate_snapshot",
      "get_role_event_snapshot",
    ]);
  });
  it("autonomous_execution", () => {
    expect(autonomousExecutionSpec.agentId).toBe("autonomous_execution");
    expect(autonomousExecutionSpec.runtimeStage).toBe("execution_feasibility");
    expect(autonomousExecutionSpec.stateUpdateField).toBe("autonomous_execution");
    expect(autonomousExecutionSpec.fieldNames).toEqual([
      "agent_id",
      "execution_disposition",
      "order_assessments",
      "confidence",
      "claims",
      "claim_refs",
    ]);
    expect(autonomousExecutionSpec.requiredTools).toEqual([
      "get_execution_snapshot",
      "get_role_event_snapshot",
    ]);
  });
  it("cio", () => {
    expect(cioSpec.agentId).toBe("cio");
    expect(cioProposalSpec.runtimeStage).toBe("cio_proposal");
    expect(cioSpec.runtimeStage).toBe("cio_final");
    expect(cioSpec.stateUpdateField).toBe("cio");
    expect(cioProposalSpec.fieldNames).toEqual([
      "agent_id",
      "decision_stage",
      "decision_disposition",
      "target_positions",
      "cash_weight",
      "decision_reason",
      "confidence",
      "claims",
      "claim_refs",
      "macro_input_attributions",
    ]);
    expect(cioSpec.fieldNames).toEqual([
      "agent_id",
      "decision_stage",
      "decision_disposition",
      "target_positions",
      "cash_weight",
      "decision_reason",
      "cro_control_resolutions",
      "execution_control_resolutions",
      "confidence",
      "claims",
      "claim_refs",
      "macro_input_attributions",
    ]);
    expect(cioSpec.requiredTools).toEqual(["get_cio_decision_snapshot"]);
  });
});

// ============================================================ render + fallback

describe("renderers + fallbacks", () => {
  it("cro", () => {
    const fb = fallbackCro("");
    expect(fb.confidence).toBe(0);
    expect(renderCro(fb).length).toBeGreaterThan(20);
  });
  it("alpha_discovery", () => {
    const fb = fallbackAlphaDiscovery("");
    expect(fb.confidence).toBe(0);
    expect(fb.novel_picks).toHaveLength(0);
    expect(renderAlphaDiscovery(fb).length).toBeGreaterThan(10);
  });
  it("autonomous_execution", () => {
    const fb = fallbackAutonomousExecution("");
    expect(fb.confidence).toBe(0);
    expect(fb.trades).toHaveLength(0);
    expect(renderAutonomousExecution(fb).length).toBeGreaterThan(10);
  });
  it("cio", () => {
    const fb = fallbackCio("");
    expect(fb.confidence).toBe(0);
    expect(fb.portfolio_actions).toHaveLength(0);
    expect(renderCio(fb).length).toBeGreaterThan(20);
  });
});

// ============================================================ schema rejects

describe("schemas reject malformations", () => {
  const claim = {
    claim_id: "claim-1",
    claim_kind: "FACT" as const,
    statement: "Frozen evidence supports the structural contract test.",
    structured_conclusion: { status: "supported" },
    evidence_ids: ["evidence-1"],
    research_rule_refs: [],
  };
  const macroAttributions = MACRO_AGENT_IDS.map((agent_id) => ({
    agent_id,
    target_type: "SUBMISSION_SUMMARY" as const,
    target_local_ref: "$SUBMISSION",
    claim_refs_used: [],
    effect: "NOT_MATERIAL" as const,
  }));

  it("uses distinct CIO proposal and final contracts", () => {
    const base = {
      agent_id: "cio",
      decision_disposition: "ALL_CASH",
      target_positions: [],
      cash_weight: 1,
      decision_reason: "Current evidence supports cash.",
      confidence: 0.4,
      claims: [claim],
      claim_refs: ["claim-1"],
      macro_input_attributions: macroAttributions,
    };
    expect(() =>
      cioProposalSpec.schema.parse({ ...base, decision_stage: "PROPOSAL" }),
    ).not.toThrow();
    expect(() =>
      cioSpec.schema.parse({
        ...base,
        decision_stage: "FINAL",
        cro_control_resolutions: [],
        execution_control_resolutions: [],
      }),
    ).not.toThrow();
    expect(() =>
      cioProposalSpec.schema.parse({
        ...base,
        decision_stage: "PROPOSAL",
        cro_control_resolutions: [],
        execution_control_resolutions: [],
      }),
    ).toThrow();
    expect(() => cioSpec.schema.parse({ ...base, decision_stage: "FINAL" })).toThrow();
    expect(() => cioSpec.schema.parse({ ...base, decision_stage: "PROPOSAL" })).toThrow();
  });

  it("rejects CRO action/disposition conflicts and unresolved claims", () => {
    const base = {
      agent_id: "cro",
      review_disposition: "REVIEW_ACTIONS",
      candidate_actions: [
        {
          action_local_id: "action-1",
          candidate_ref: "candidate-1",
          ts_code: "600519.SH",
          action: "VETO",
          predicted_risk_probability: 0.8,
          max_target_weight: 0,
          reason: "Risk exceeds the frozen limit.",
          claim_refs: ["claim-1"],
        },
      ],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
      claims: [claim],
      claim_refs: ["claim-1"],
      macro_input_attributions: macroAttributions,
    };
    expect(() => croSpec.schema.parse(base)).toThrow(/BLOCK_ALL/);
    expect(() =>
      croSpec.schema.parse({
        ...base,
        review_disposition: "BLOCK_ALL",
        candidate_actions: [{ ...base.candidate_actions[0], claim_refs: ["missing"] }],
      }),
    ).toThrow(/unresolved/);
  });

  it("rejects invalid execution feasibility bounds", () => {
    const assessment = {
      assessment_local_id: "assessment-1",
      order_intent_ref: "intent-1",
      ts_code: "600519.SH",
      requested_delta_weight: 0.1,
      feasibility: "PARTIAL",
      feasibility_confidence: 0.5,
      predicted_cost_bps: 10,
      max_executable_delta_weight: 0.1,
      recommended_slice_count: 1,
      reason: "Partial capacity.",
      claim_refs: ["claim-1"],
    };
    expect(() =>
      autonomousExecutionSpec.schema.parse({
        agent_id: "autonomous_execution",
        execution_disposition: "ORDERS_ASSESSED",
        order_assessments: [assessment],
        confidence: 0.5,
        claims: [claim],
        claim_refs: ["claim-1"],
      }),
    ).toThrow(/strictly between/);
  });

  it("requires CIO target weights plus explicit cash to equal one", () => {
    const base = {
      agent_id: "cio",
      decision_stage: "FINAL",
      decision_disposition: "TARGET_PORTFOLIO",
      target_positions: [
        {
          position_local_id: "position-1",
          ts_code: "600519.SH",
          target_weight: 0.4,
          position_decision: "ADD",
          holding_period: "WEEKS",
          thesis_status: "INTACT",
          risk_flags: [],
          claim_refs: ["claim-1"],
        },
      ],
      cash_weight: 0.6,
      decision_reason: "Partial allocation with explicit cash.",
      cro_control_resolutions: [],
      execution_control_resolutions: [],
      confidence: 0.5,
      claims: [claim],
      claim_refs: ["claim-1"],
      macro_input_attributions: macroAttributions,
    };
    expect(() => cioSpec.schema.parse(base)).not.toThrow();
    expect(() => cioSpec.schema.parse({ ...base, cash_weight: 0.5 })).toThrow(/equal 1/);
    expect(() =>
      cioSpec.schema.parse({
        ...base,
        target_positions: [{ ...base.target_positions[0], holding_period: "10Y" }],
      }),
    ).toThrow();
  });
});

// ============================================================ context renderers

const baseState = (): DailyCycleStateType => ({
  messages: [],
  active_cohort: "cohort_default",
  as_of_date: "2024-06-24",
  mode: "live",
  trace_id: "t",
  darwinian_runtime_binding: null,
  darwinian_weight_snapshot: null,
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
  layer4_outputs: { cro: null, alpha_discovery: null, autonomous_execution: null, cio: null },
  current_positions: {
    snapshot_status: "empty_confirmed",
    position_source: "empty_confirmed",
    source_error_code: null,
    position_snapshot_hash: "sha256:empty_positions",
    positions: [],
  },
  position_reviews: [],
  position_audit: {
    position_snapshot_hash: "sha256:empty_positions",
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
});

function loadedPositions(
  positions: CurrentPositionsSnapshot["positions"],
): CurrentPositionsSnapshot {
  return {
    snapshot_status: "loaded",
    position_source: "cli_fixture",
    source_error_code: null,
    position_snapshot_hash: "sha256:test_positions",
    positions,
  };
}

const testL4PromptSnapshots = [
  {
    agent: "alpha_discovery" as const,
    stage: "alpha_discovery" as const,
    prompt_source_hash: "p1",
    private_knot_snapshot_hash: null,
  },
  {
    agent: "cio" as const,
    stage: "cio_proposal" as const,
    prompt_source_hash: "p2",
    private_knot_snapshot_hash: null,
  },
  {
    agent: "cro" as const,
    stage: "cro_review" as const,
    prompt_source_hash: "p3",
    private_knot_snapshot_hash: null,
  },
  {
    agent: "autonomous_execution" as const,
    stage: "execution_feasibility" as const,
    prompt_source_hash: "p4",
    private_knot_snapshot_hash: null,
  },
  {
    agent: "cio" as const,
    stage: "cio_final" as const,
    prompt_source_hash: "p5",
    private_knot_snapshot_hash: null,
  },
];

function attachTestL4Snapshot(state: DailyCycleStateType): void {
  const runtime = state.layer4_outputs.runtime ?? emptyLayer4RuntimeState();
  const bundle = freezeL4RunSnapshotBundle({
    state,
    promptSnapshots: testL4PromptSnapshots,
    sourceStatuses: runtime.resolved_source_statuses,
    mirofishContextHash: null,
  });
  state.layer4_outputs.runtime = { ...runtime, l4_run_snapshot_bundle: bundle };
}

function cioOutput(portfolio_actions: PortfolioAction[]): CioOutput {
  return {
    agent: "cio",
    portfolio_actions,
    confidence: 0.61,
  };
}

function executableOutput(deltaWeight = 0.2): AutoExecOutput {
  return {
    agent: "autonomous_execution",
    execution_disposition: "TRADES",
    trades: [
      {
        ticker: "600519.SH",
        action: "BUY",
        size_pct: Math.abs(deltaWeight),
        delta_weight: deltaWeight,
        conviction: 0.6,
      },
    ],
    execution_checks: [
      {
        ticker: "600519.SH",
        status: "feasible",
        estimated_cost_bps: 5,
        max_executable_delta_weight: Math.abs(deltaWeight),
        reason: "fixture liquidity supports the frozen delta",
      },
    ],
    confidence: 0.6,
  };
}

const heldPosition = {
  ticker: "600519.SH",
  sector: "consumer",
  current_weight: 0.2,
  cost_basis: 100,
  market_price: 108,
  unrealized_pnl_pct: 0.08,
  holding_days: 12,
  entry_date: "2024-06-01",
  source_agent: "munger",
  entry_thesis_id: "thesis-600519",
  last_review_date: "2024-06-20",
};

function stateWithFrozenCandidate(): DailyCycleStateType {
  const state = baseState();
  const frozen = freezeCioProposal(
    state,
    cioOutput([
      {
        ticker: "600519.SH",
        action: "BUY",
        target_weight: 0.2,
        holding_period: "3M",
        dissent_notes: "",
      },
    ]),
  );
  state.layer4_outputs.runtime = {
    ...emptyLayer4RuntimeState(),
    cio_proposal: frozen.proposal,
    candidate_target_state: frozen.candidate,
    position_review_state: frozen.reviews,
    portfolio_exposure_state: frozen.exposure,
  };
  return state;
}

describe("Layer-4 runtime source envelopes", () => {
  it("rejects prompt, position, and base-market drift after L4 snapshot freeze", () => {
    const state = baseState();
    const status = {
      source_id: "current_market_data",
      scope: "ticker:600519.SH",
      status: "loaded" as const,
      as_of: state.as_of_date,
      snapshot_hash: "sha256:market-v1",
    };
    state.layer4_outputs.runtime = {
      ...emptyLayer4RuntimeState(),
      resolved_source_statuses: [status],
    };
    attachTestL4Snapshot(state);

    expect(
      assertL4RunSnapshotStage({
        state,
        agent: "cio",
        stage: "cio_proposal",
        promptSourceHash: "p2",
        privateKnotSnapshotHash: null,
        mirofishContextHash: null,
      }).bundle_hash,
    ).toMatch(/^sha256:/);
    expect(() =>
      assertL4RunSnapshotStage({
        state,
        agent: "cio",
        stage: "cio_proposal",
        promptSourceHash: "prompt-drift",
        privateKnotSnapshotHash: null,
        mirofishContextHash: null,
      }),
    ).toThrow(/prompt or knob hash drifted/);

    const originalPositions = state.current_positions;
    state.current_positions = { ...originalPositions, position_snapshot_hash: "sha256:changed" };
    expect(() =>
      assertL4RunSnapshotStage({
        state,
        agent: "cio",
        stage: "cio_proposal",
        promptSourceHash: "p2",
        privateKnotSnapshotHash: null,
        mirofishContextHash: null,
      }),
    ).toThrow(/immutable input changed/);
    state.current_positions = originalPositions;

    state.layer4_outputs.runtime = {
      ...(state.layer4_outputs.runtime ?? emptyLayer4RuntimeState()),
      resolved_source_statuses: [{ ...status, snapshot_hash: "sha256:market-v2" }],
    };
    expect(() =>
      assertL4RunSnapshotStage({
        state,
        agent: "cio",
        stage: "cio_proposal",
        promptSourceHash: "p2",
        privateKnotSnapshotHash: null,
        mirofishContextHash: null,
      }),
    ).toThrow(/base market source drifted/);
  });

  it("freezes a deterministic candidate only after every current position is reviewed", () => {
    const state = baseState();
    state.current_positions = loadedPositions([
      heldPosition,
      { ...heldPosition, ticker: "688981.SH", entry_thesis_id: "thesis-688981" },
    ]);
    state.layer4_outputs.previous_target_state = {
      schema_version: "portfolio.previous_target_state.v1",
      snapshot_status: "loaded",
      final_target_hash: "sha256:prior-final",
      as_of_date: "2026-07-08",
      portfolio_actions: [],
      source_error_code: null,
    };
    const proposal = {
      ...cioOutput([
        {
          ticker: "600519.SH",
          action: "HOLD",
          position_decision: "HOLD",
          current_weight: 0.2,
          target_weight: 0.2,
          delta_weight: 0,
          holding_period: "3M",
          position_decision_reason: "thesis remains intact",
          thesis_status: "intact",
          risk_flags: [],
          dissent_notes: "",
        },
        {
          ticker: "688981.SH",
          action: "HOLD",
          position_decision: "HOLD",
          current_weight: 0.2,
          target_weight: 0.2,
          delta_weight: 0,
          holding_period: "3M",
          position_decision_reason: "second thesis remains intact",
          thesis_status: "intact",
          risk_flags: [],
          dissent_notes: "",
        },
      ]),
      position_reviews: [
        {
          ticker: "600519.SH",
          decision: "HOLD" as const,
          target_weight: 0.2,
          reason: "thesis remains intact",
          thesis_status: "intact" as const,
          risk_flags: [],
          confidence: 0.61,
        },
        {
          ticker: "688981.SH",
          decision: "HOLD" as const,
          target_weight: 0.2,
          reason: "second thesis remains intact",
          thesis_status: "intact" as const,
          risk_flags: [],
          confidence: 0.61,
        },
      ],
    };

    const first = freezeCioProposal(state, proposal);
    const second = freezeCioProposal(state, proposal);

    expect(first.candidate.candidate_target_hash).toBe(second.candidate.candidate_target_hash);
    expect(first.candidate.market_data_vintage_hash).toMatch(/^sha256:/);
    expect(first.candidate.previous_target_hash).toBe("sha256:prior-final");
    expect(first.candidate.frozen).toBe(true);
    expect(first.candidate.portfolio_actions).toHaveLength(2);
    expect(first.reviews.llm_reviewed_tickers).toEqual(["600519.SH", "688981.SH"]);
    expect(first.reviews.fallback_tickers).toEqual([]);
    expect(
      first.candidate.portfolio_actions.find((action) => action.ticker === "688981.SH"),
    ).toMatchObject({
      action: "HOLD",
      review_source: "llm",
    });
  });

  it("rejects an action without explicit position_reviews", () => {
    const state = baseState();
    state.current_positions = loadedPositions([heldPosition]);
    expect(() =>
      freezeCioProposal(
        state,
        cioOutput([
          {
            ticker: "600519.SH",
            action: "BUY",
            position_decision: "ADD",
            current_weight: 0.2,
            target_weight: 0.3,
            delta_weight: 0.1,
            holding_period: "3M",
            position_decision_reason: "add without formal review",
            dissent_notes: "",
          },
        ]),
      ),
    ).toThrow(/explicit current-position review/);
  });

  it("binds CRO, execution, and final target envelopes to the same candidate hash", () => {
    const state = baseState();
    const frozen = freezeCioProposal(
      state,
      cioOutput([
        {
          ticker: "600519.SH",
          action: "BUY",
          target_weight: 0.2,
          holding_period: "3M",
          dissent_notes: "",
        },
      ]),
    );
    const cro = freezeCroReview("t", frozen.candidate, {
      agent: "cro",
      rejected_picks: [],
      required_adjustments: [],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    });
    const execution = freezeExecutionFeasibility("t", frozen.candidate, cro, executableOutput());
    state.layer4_outputs.runtime = {
      ...emptyLayer4RuntimeState(),
      candidate_target_state: frozen.candidate,
      cro_review_state: cro,
      execution_feasibility_state: execution,
    };

    const final = freezeFinalTarget(state, frozen.proposal, ["validator:portfolio.v1"]);

    expect(final.candidate_target_hash).toBe(frozen.candidate.candidate_target_hash);
    expect(final.cro_review_hash).toBe(cro.review_hash);
    expect(final.execution_feasibility_hash).toBe(execution.feasibility_hash);
    expect(execution.liquidity_vintage_hash).toMatch(/^sha256:/);
    expect(final.market_data_vintage_hash).toBe(frozen.candidate.market_data_vintage_hash);
    expect(final.liquidity_vintage_hash).toBe(execution.liquidity_vintage_hash);
    expect(final.validator_hashes).toEqual(["validator:portfolio.v1"]);
    expect(previousTargetStateFromFinal(final)).toMatchObject({
      snapshot_status: "loaded",
      final_target_hash: final.final_target_hash,
      as_of_date: final.as_of_date,
    });
    expect(missingPreviousTargetState()).toMatchObject({
      snapshot_status: "missing",
      final_target_hash: null,
    });
  });

  it("rejects CRO and execution fallback shells instead of constructing decisions", () => {
    const frozen = freezeCioProposal(
      baseState(),
      cioOutput([
        {
          ticker: "600519.SH",
          action: "BUY",
          target_weight: 0.2,
          holding_period: "3M",
          dissent_notes: "",
        },
      ]),
    );

    expect(() => croSpec.schema.parse(fallbackCro(""))).toThrow();
    const cro = freezeCroReview("t", frozen.candidate, {
      agent: "cro",
      rejected_picks: [],
      required_adjustments: [],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    });
    expect(() =>
      freezeExecutionFeasibility("t", frozen.candidate, cro, fallbackAutonomousExecution("")),
    ).toThrow(/target delta lacks execution check/);
  });

  it("rejects CRO references outside the candidate and malformed reductions", () => {
    const frozen = freezeCioProposal(
      baseState(),
      cioOutput([
        {
          ticker: "600519.SH",
          action: "BUY",
          target_weight: 0.2,
          holding_period: "3M",
          dissent_notes: "",
        },
      ]),
    );
    const baseCro: CroOutput = {
      agent: "cro",
      rejected_picks: [],
      required_adjustments: [],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    };

    expect(() =>
      freezeCroReview("t", frozen.candidate, {
        ...baseCro,
        rejected_picks: [{ ticker: "000001.SZ", reason: "outside" }],
        required_adjustments: [{ ticker: "000001.SZ", adjustment: "VETO", reason: "outside" }],
      }),
    ).toThrow(/outside frozen candidate/);
    expect(() =>
      freezeCroReview("t", frozen.candidate, {
        ...baseCro,
        required_adjustments: [
          {
            ticker: "600519.SH",
            adjustment: "REDUCE_WEIGHT",
            max_target_weight: 0.2,
            reason: "not a reduction",
          },
        ],
      }),
    ).toThrow(/must be below frozen candidate target/);
  });

  it("rejects blocked or partial execution that carries excess delta", () => {
    const frozen = freezeCioProposal(
      baseState(),
      cioOutput([
        {
          ticker: "600519.SH",
          action: "BUY",
          target_weight: 0.2,
          holding_period: "3M",
          dissent_notes: "",
        },
      ]),
    );
    const cro = freezeCroReview("t", frozen.candidate, {
      agent: "cro",
      rejected_picks: [],
      required_adjustments: [],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    });

    expect(() =>
      freezeExecutionFeasibility("t", frozen.candidate, cro, {
        agent: "autonomous_execution",
        trades: [
          {
            ticker: "600519.SH",
            action: "BUY",
            size_pct: 0.2,
            delta_weight: 0.2,
            conviction: 0.5,
          },
        ],
        execution_checks: [
          {
            ticker: "600519.SH",
            status: "blocked",
            estimated_cost_bps: 10,
            reason: "halted",
          },
        ],
        confidence: 0.5,
      }),
    ).toThrow(/blocked execution cannot carry a trade/);
    expect(() =>
      freezeExecutionFeasibility("t", frozen.candidate, cro, {
        agent: "autonomous_execution",
        trades: [
          {
            ticker: "600519.SH",
            action: "BUY",
            size_pct: 0.15,
            delta_weight: 0.15,
            conviction: 0.5,
          },
        ],
        execution_checks: [
          {
            ticker: "600519.SH",
            status: "partial",
            estimated_cost_bps: 10,
            max_executable_delta_weight: 0.1,
            reason: "capacity",
          },
        ],
        confidence: 0.5,
      }),
    ).toThrow(/exceeds partial executable cap/);
  });

  it("requires frozen CRO authorization for final target changes", () => {
    const state = baseState();
    const frozen = freezeCioProposal(
      state,
      cioOutput([
        {
          ticker: "600519.SH",
          action: "BUY",
          target_weight: 0.2,
          holding_period: "3M",
          dissent_notes: "",
        },
      ]),
    );
    const cro = freezeCroReview("t", frozen.candidate, {
      agent: "cro",
      rejected_picks: [],
      required_adjustments: [
        {
          ticker: "600519.SH",
          adjustment: "CAP_WEIGHT",
          max_target_weight: 0.1,
          reason: "concentration",
        },
      ],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    });
    const execution = freezeExecutionFeasibility("t", frozen.candidate, cro, executableOutput());
    state.layer4_outputs.runtime = {
      ...emptyLayer4RuntimeState(),
      candidate_target_state: frozen.candidate,
      cro_review_state: cro,
      execution_feasibility_state: execution,
    };
    const adjusted = cioOutput([
      {
        ticker: "600519.SH",
        action: "BUY",
        target_weight: 0.1,
        holding_period: "3M",
        dissent_notes: "applied CRO cap",
      },
    ]);

    expect(() => freezeFinalTarget(state, adjusted, [])).toThrow(/lacks frozen CRO dissent/);
    adjusted.dissent_refs = [
      {
        ticker: "600519.SH",
        source: "cro_review",
        source_hash: cro.review_hash,
        reason: "applied CRO cap",
      },
    ];
    expect(freezeFinalTarget(state, adjusted, []).portfolio_actions[0]?.target_weight).toBe(0.1);
    adjusted.dissent_refs[0] = {
      ticker: "600519.SH",
      source: "cro_review",
      source_hash: "sha256:wrong",
      reason: "applied CRO cap",
    };
    expect(() => freezeFinalTarget(state, adjusted, [])).toThrow(/dissent hash mismatch/);
  });

  it("enforces FEASIBLE, PARTIAL, and BLOCKED execution caps with frozen dissent", () => {
    const makeState = (executionOutput: AutoExecOutput) => {
      const state = baseState();
      const frozen = freezeCioProposal(
        state,
        cioOutput([
          {
            ticker: "600519.SH",
            action: "BUY",
            target_weight: 0.2,
            holding_period: "3M",
            dissent_notes: "",
          },
        ]),
      );
      const cro = freezeCroReview("t", frozen.candidate, {
        agent: "cro",
        rejected_picks: [],
        required_adjustments: [],
        correlated_risks: [],
        black_swan_scenarios: [],
        confidence: 0.5,
      });
      const execution = freezeExecutionFeasibility("t", frozen.candidate, cro, executionOutput);
      state.layer4_outputs.runtime = {
        ...emptyLayer4RuntimeState(),
        candidate_target_state: frozen.candidate,
        cro_review_state: cro,
        execution_feasibility_state: execution,
      };
      return { state, frozen, execution };
    };

    const feasible = makeState(executableOutput(0.2));
    expect(freezeFinalTarget(feasible.state, feasible.frozen.proposal, [])).toBeDefined();
    expect(() =>
      freezeFinalTarget(
        feasible.state,
        cioOutput([
          {
            ticker: "600519.SH",
            action: "BUY",
            target_weight: 0.1,
            holding_period: "3M",
            dissent_notes: "uncontrolled reduction",
          },
        ]),
        [],
      ),
    ).toThrow(/without a binding control/);

    const partial = makeState({
      agent: "autonomous_execution",
      execution_disposition: "TRADES",
      trades: [
        {
          ticker: "600519.SH",
          action: "BUY",
          size_pct: 0.1,
          delta_weight: 0.1,
          conviction: 0.5,
        },
      ],
      execution_checks: [
        {
          ticker: "600519.SH",
          status: "partial",
          estimated_cost_bps: 10,
          max_executable_delta_weight: 0.1,
          reason: "bounded capacity",
        },
      ],
      confidence: 0.5,
    });
    const partialFinal = cioOutput([
      {
        ticker: "600519.SH",
        action: "BUY",
        target_weight: 0.1,
        holding_period: "3M",
        dissent_notes: "applied execution cap",
      },
    ]);
    expect(() => freezeFinalTarget(partial.state, partialFinal, [])).toThrow(
      /lacks frozen execution dissent/,
    );
    partialFinal.dissent_refs = [
      {
        ticker: "600519.SH",
        source: "execution_feasibility",
        source_hash: partial.execution.feasibility_hash,
        reason: "applied execution cap",
      },
    ];
    expect(
      freezeFinalTarget(partial.state, partialFinal, []).portfolio_actions[0]?.target_weight,
    ).toBe(0.1);
    const partialAction = partialFinal.portfolio_actions[0];
    if (!partialAction) throw new Error("partial fixture requires one action");
    partialAction.target_weight = 0.15;
    expect(() => freezeFinalTarget(partial.state, partialFinal, [])).toThrow(
      /exceeds frozen partial execution cap/,
    );

    const blocked = makeState({
      agent: "autonomous_execution",
      execution_disposition: "BLOCKED",
      trades: [],
      execution_checks: [
        {
          ticker: "600519.SH",
          status: "blocked",
          estimated_cost_bps: 0,
          max_executable_delta_weight: 0,
          reason: "halted",
        },
      ],
      confidence: 0.5,
    });
    const blockedFinal = cioOutput([
      {
        ticker: "600519.SH",
        action: "HOLD",
        target_weight: 0,
        holding_period: "3M",
        dissent_notes: "blocked",
      },
    ]);
    blockedFinal.dissent_refs = [
      {
        ticker: "600519.SH",
        source: "execution_feasibility",
        source_hash: blocked.execution.feasibility_hash,
        reason: "blocked",
      },
    ];
    expect(
      freezeFinalTarget(blocked.state, blockedFinal, []).portfolio_actions[0]?.target_weight,
    ).toBe(0);
    const blockedDissent = blockedFinal.dissent_refs[0];
    if (!blockedDissent) throw new Error("blocked fixture requires one dissent ref");
    blockedDissent.source_hash = "sha256:wrong";
    expect(() => freezeFinalTarget(blocked.state, blockedFinal, [])).toThrow(
      /dissent hash mismatch/,
    );
  });

  it("rejects CIO final after shared validation without constructing a hard exit", () => {
    const state = baseState();
    state.current_positions = loadedPositions([{ ...heldPosition, unrealized_pnl_pct: -0.12 }]);
    const proposal = {
      ...cioOutput([
        {
          ticker: "600519.SH",
          action: "HOLD" as const,
          target_weight: 0.2,
          holding_period: "3M" as const,
          dissent_notes: "",
        },
      ]),
      position_reviews: [
        {
          ticker: "600519.SH",
          decision: "HOLD" as const,
          target_weight: 0.2,
          reason: "raw proposal",
          thesis_status: "intact" as const,
          risk_flags: [],
          confidence: 0.5,
        },
      ],
    };
    const frozen = freezeCioProposal(state, proposal);
    const cro = freezeCroReview("t", frozen.candidate, {
      agent: "cro",
      rejected_picks: [],
      required_adjustments: [],
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
    });
    const execution = freezeExecutionFeasibility(
      "t",
      frozen.candidate,
      cro,
      fallbackAutonomousExecution(""),
    );
    state.layer4_outputs.runtime = {
      ...emptyLayer4RuntimeState(),
      candidate_target_state: frozen.candidate,
      cro_review_state: cro,
      execution_feasibility_state: execution,
    };
    state.layer4_outputs.cio = cioOutput([
      {
        ticker: "000001.SZ",
        action: "BUY",
        target_weight: 0.1,
        holding_period: "1M",
        dissent_notes: "invalid new ticker",
      },
    ]);

    expect(() => validateFinalTargetNode(state)).toThrow(PositionActionValidationError);
  });

  it("fails closed when a stage reads before its required source is frozen", () => {
    expect(() => freezeCroReview("t", null, fallbackCro(""))).toThrow(Layer4RuntimeContractError);
    expect(() =>
      freezeExecutionFeasibility("t", null, null, fallbackAutonomousExecution("")),
    ).toThrow(Layer4RuntimeContractError);
  });

  it("records an ordered runtime-owned stage trace", () => {
    const first = updateLayer4Runtime(
      emptyLayer4RuntimeState(),
      {},
      {
        stage: "alpha_discovery",
        operation: "agent_run",
        status: "completed",
        input_hashes: {},
        output_hashes: { alpha: "sha256:alpha" },
      },
    );
    const second = updateLayer4Runtime(
      first,
      {},
      {
        stage: "cio_proposal",
        operation: "source_freeze",
        status: "completed",
        input_hashes: { alpha: "sha256:alpha" },
        output_hashes: { candidate_target_state: "sha256:candidate" },
      },
    );

    expect(second.stage_trace.map((entry) => [entry.sequence, entry.stage])).toEqual([
      [1, "alpha_discovery"],
      [2, "cio_proposal"],
    ]);
  });
});

describe("CIO position validator", () => {
  it("rejects duplicate tickers before portfolio arithmetic", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "600519.SH",
            action: "HOLD",
            target_weight: 0.1,
            holding_period: "1M",
            dissent_notes: "",
          },
          {
            ticker: "600519.SH",
            action: "HOLD",
            target_weight: 0.1,
            holding_period: "1M",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([heldPosition]),
      }),
    ).toThrow(/duplicate portfolio action ticker/);
  });

  it("does not count runtime fallback reductions as model-reviewed positions", () => {
    const result = validateCioPositionActions({
      output: cioOutput([
        {
          ticker: "600519.SH",
          action: "REDUCE",
          position_decision: "REDUCE",
          current_weight: 0.2,
          target_weight: 0.12,
          delta_weight: -0.08,
          holding_period: "1M",
          position_decision_reason: "runtime reduced omitted over-limit position",
          thesis_status: "intact",
          risk_flags: ["position_review_missing"],
          dissent_notes: "",
          review_source: "runtime_safety_fallback",
        },
      ]),
      currentPositions: loadedPositions([heldPosition]),
    });

    expect(result.position_reviews[0]?.review_source).toBe("runtime_safety_fallback");
    expect(result.position_audit).toMatchObject({
      positions_loaded: 1,
      positions_reviewed: 0,
      positions_unreviewed: 1,
      hold_count: 0,
    });
  });

  it("rejects a loaded current position missing from CIO actions", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "688981.SH",
            action: "BUY",
            target_weight: 0.1,
            holding_period: "3M",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([heldPosition]),
      }),
    ).toThrow(PositionActionValidationError);
  });

  it("rejects stop-loss breached HOLD without an override", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "600519.SH",
            action: "HOLD",
            target_weight: 0.2,
            holding_period: "3M",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([
          { ...heldPosition, unrealized_pnl_pct: -0.12, holding_days: 25 },
        ]),
      }),
    ).toThrow(/stop_loss breached/);
  });

  it("rejects stop-loss breached HOLD without CRO risk override", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "600519.SH",
            action: "HOLD",
            target_weight: 0.2,
            holding_period: "3M",
            override_reason: "policy catalyst remains live through next review window",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([
          { ...heldPosition, unrealized_pnl_pct: -0.12, holding_days: 25 },
        ]),
      }),
    ).toThrow(/CRO risk override/);
  });

  it("rejects stop-loss breached HOLD without counterevidence", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "600519.SH",
            action: "HOLD",
            target_weight: 0.2,
            holding_period: "3M",
            override_reason: "policy catalyst remains live through next review window",
            risk_flags: ["cro_risk_override"],
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([
          { ...heldPosition, unrealized_pnl_pct: -0.12, holding_days: 25 },
        ]),
      }),
    ).toThrow(/counterevidence/);
  });

  it("rejects max single-name breaches without CRO risk override", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "688981.SH",
            action: "BUY",
            target_weight: 0.3,
            holding_period: "3M",
            override_reason: "temporary high-conviction thesis window",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([]),
      }),
    ).toThrow(/CRO risk override/);
  });

  it("allows max single-name breaches with rationale and CRO risk override", () => {
    const result = validateCioPositionActions({
      output: cioOutput([
        {
          ticker: "688981.SH",
          sector: "semiconductor",
          action: "BUY",
          target_weight: 0.3,
          holding_period: "3M",
          override_reason: "temporary high-conviction thesis window",
          risk_flags: ["cro_risk_override"],
          dissent_notes: "",
        },
      ]),
      currentPositions: loadedPositions([]),
    });

    expect(result.output.portfolio_actions[0]?.risk_flags).toEqual(["cro_risk_override"]);
  });

  it("uses the public hard-control single-name cap", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "688981.SH",
            sector: "semiconductor",
            action: "BUY",
            target_weight: 0.13,
            holding_period: "3M",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([]),
      }),
    ).toThrow(/max_single_name_weight/);
  });

  it("uses the public hard-control sector cap", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput(
          ["688981.SH", "300750.SZ", "002371.SZ"].map((ticker) => ({
            ticker,
            sector: "semiconductor",
            action: "BUY" as const,
            target_weight: 0.11,
            holding_period: "3M",
            dissent_notes: "",
          })),
        ),
        currentPositions: loadedPositions([]),
      }),
    ).toThrow(/max_sector_weight/);
  });

  it("requires sector exposure when max_sector_weight is active", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "688981.SH",
            action: "BUY",
            target_weight: 0.1,
            holding_period: "3M",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([]),
      }),
    ).toThrow(/sector is missing/);
  });

  it("rejects ADD decisions that do not map to a positive BUY delta", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "600519.SH",
            action: "HOLD",
            position_decision: "ADD",
            target_weight: 0.2,
            holding_period: "3M",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([heldPosition]),
      }),
    ).toThrow(/ADD position_decision must map to BUY/);

    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "600519.SH",
            action: "BUY",
            position_decision: "ADD",
            target_weight: 0.18,
            holding_period: "3M",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([heldPosition]),
      }),
    ).toThrow(/target_weight above current_weight/);
  });

  it("rejects REDUCE decisions that do not trim an existing holding", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "600519.SH",
            action: "REDUCE",
            position_decision: "REDUCE",
            target_weight: 0.22,
            holding_period: "3M",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([heldPosition]),
      }),
    ).toThrow(/0 < target_weight < current_weight/);
  });

  it("rejects EXIT decisions that retain target weight", () => {
    expect(() =>
      validateCioPositionActions({
        output: cioOutput([
          {
            ticker: "600519.SH",
            action: "SELL",
            position_decision: "EXIT",
            target_weight: 0.05,
            holding_period: "3M",
            dissent_notes: "",
          },
        ]),
        currentPositions: loadedPositions([heldPosition]),
      }),
    ).toThrow(/target_weight = 0/);
  });

  it("allows stop-loss breached HOLD with an override and audits it", () => {
    const result = validateCioPositionActions({
      output: cioOutput([
        {
          ticker: "600519.SH",
          action: "HOLD",
          target_weight: 0.2,
          holding_period: "3M",
          override_reason: "policy catalyst remains live through next review window",
          position_decision_reason: "fresh channel checks contradict a forced exit",
          risk_flags: ["cro_risk_override"],
          dissent_notes: "",
        },
      ]),
      currentPositions: loadedPositions([
        { ...heldPosition, unrealized_pnl_pct: -0.12, holding_days: 25 },
      ]),
    });

    expect(result.position_reviews).toEqual([
      {
        ticker: "600519.SH",
        decision: "HOLD",
        target_weight: 0.2,
        reason: "fresh channel checks contradict a forced exit",
        thesis_status: "intact",
        risk_flags: ["cro_risk_override", "stop_loss_breached", "stale_thesis"],
        confidence: 0.61,
        review_source: "llm",
      },
    ]);
    expect(result.position_audit.stop_loss_override_count).toBe(1);
    expect(result.position_audit.positions_unreviewed).toBe(0);
  });

  it("normalizes covered loaded positions into reviews and audit counts", () => {
    const result = validateCioPositionActions({
      output: cioOutput([
        {
          ticker: "600519.SH",
          action: "BUY",
          current_weight: 0.9,
          target_weight: 0.27,
          delta_weight: -0.63,
          holding_period: "6M",
          position_decision_reason: "increase high-conviction intact thesis",
          override_reason: "CRO-approved temporary concentration for the reviewed thesis",
          risk_flags: ["cro_risk_override"],
          dissent_notes: "",
        },
      ]),
      currentPositions: loadedPositions([heldPosition]),
    });

    const action = result.output.portfolio_actions[0];
    expect(action?.current_weight).toBe(0.2);
    expect(action?.delta_weight).toBeCloseTo(0.07);
    expect(action?.position_decision).toBe("ADD");
    expect(result.position_audit.positions_loaded).toBe(1);
    expect(result.position_audit.positions_reviewed).toBe(1);
    expect(result.position_audit.tool_status_summary).toMatchObject({
      "cli.current_positions_fixture": "loaded",
      market_prices: "loaded",
    });
    expect(result.position_audit.add_count).toBe(1);
    expect(result.position_audit.target_current_drift_count).toBe(1);
    expect(result.position_audit).toMatchObject({
      runtime_safety_hold_count: 0,
      cash_weight: 0.73,
      gross_exposure: 0.27,
      net_exposure: 0.27,
    });
  });

  it("marks stale thesis holdings with an explicit review flag and reason", () => {
    const result = validateCioPositionActions({
      output: cioOutput([
        {
          ticker: "600519.SH",
          action: "HOLD",
          target_weight: 0.1,
          holding_period: "3M",
          dissent_notes: "",
        },
      ]),
      currentPositions: loadedPositions([
        { ...heldPosition, current_weight: 0.1, holding_days: 30 },
      ]),
    });

    expect(result.output.portfolio_actions[0]?.risk_flags).toContain("stale_thesis");
    expect(result.output.portfolio_actions[0]?.position_decision_reason).toBe(
      "stale thesis review required",
    );
    expect(result.position_reviews[0]?.risk_flags).toContain("stale_thesis");
    expect(result.position_audit.stale_thesis_count).toBe(1);
  });

  it("covers a 3-position fixture and audits stale thesis reviews", () => {
    const result = validateCioPositionActions({
      output: cioOutput([
        {
          ticker: "600519.SH",
          action: "HOLD",
          target_weight: 0.1,
          holding_period: "6M",
          dissent_notes: "core position still intact",
        },
        {
          ticker: "688981.SH",
          action: "REDUCE",
          target_weight: 0.04,
          holding_period: "3M",
          position_decision_reason: "trim after thesis decay",
          thesis_status: "weakened",
          dissent_notes: "",
        },
        {
          ticker: "000001.SZ",
          action: "SELL",
          target_weight: 0,
          holding_period: "1M",
          position_decision_reason: "exit stale thesis",
          thesis_status: "expired",
          dissent_notes: "",
        },
      ]),
      currentPositions: loadedPositions([
        { ...heldPosition, current_weight: 0.1 },
        {
          ...heldPosition,
          ticker: "688981.SH",
          current_weight: 0.08,
          holding_days: 31,
          entry_thesis_id: "thesis-688981",
        },
        {
          ...heldPosition,
          ticker: "000001.SZ",
          current_weight: 0.03,
          holding_days: 45,
          entry_thesis_id: "thesis-000001",
        },
      ]),
    });

    expect(result.position_reviews.map((review) => review.ticker).sort()).toEqual([
      "000001.SZ",
      "600519.SH",
      "688981.SH",
    ]);
    expect(result.position_audit.positions_loaded).toBe(3);
    expect(result.position_audit.positions_reviewed).toBe(3);
    expect(result.position_audit.positions_unreviewed).toBe(0);
    expect(result.position_audit.stale_thesis_count).toBe(2);
    expect(result.position_audit.exit_count).toBe(1);
    expect(
      result.output.portfolio_actions.find((action) => action.ticker === "688981.SH")?.risk_flags,
    ).toContain("stale_thesis");
    expect(
      result.output.portfolio_actions.find((action) => action.ticker === "000001.SZ")?.risk_flags,
    ).toContain("stale_thesis");
  });
});

describe("Layer 1/2/3/4 context renderers", () => {
  const semi: SemiconductorOutput = sectorOutput("semiconductor", {
    preferred_security_status: "PICKS_PRESENT",
    preferred_security_abstention_confidence: null,
    long_picks: [
      {
        pick_local_id: "semi-pick",
        ts_code: "688981.SH",
        direction_local_id: "semiconductor-preferred",
        position_action: "LONG",
        conviction: 0.8,
        thesis: "x",
        claim_refs: ["semiconductor-claim"],
      },
    ],
  });
  const druck: SuperinvestorOutput = {
    ...fallbackSuperinvestorOutput("druckenmiller", "macro momentum"),
    agent: "druckenmiller",
    selection_status: "SELECTED",
    picks: [
      {
        pick_local_id: "druck-pick-1",
        ts_code: "688981.SH",
        position_action: "LONG",
        thesis: "regime BULLISH",
        conviction: 0.7,
        claim_refs: ["fallback-druckenmiller-claim"],
      },
    ],
    holding_period: "MONTHS",
    confidence: 0.6,
  };
  const cro: CroOutput = {
    agent: "cro",
    rejected_picks: [{ ticker: "BAD", reason: "regulatory" }],
    correlated_risks: ["multi-tier-1 cluster"],
    black_swan_scenarios: ["fed pivot"],
    confidence: 0.5,
  };

  it("L1 renders independent transmissions and has no aggregate stance", () => {
    const s = baseState();
    expect(renderLayer1Context(s)).toContain("macro_input_gate: NOT_READY");
    s.layer1_outputs = Object.fromEntries(
      MACRO_AGENT_IDS.map((agent) => [
        agent,
        macroOutput(
          agent,
          agent === "china" ? { direction: "SUPPORTIVE", strength: 3 } : undefined,
        ),
      ]),
    );
    s.macro_input_gate = validateMacroInputs(s.layer1_outputs);
    expect(renderLayer1Context(s)).toContain("china");
    expect(renderLayer1Context(s)).not.toContain("layer_1_consensus_score");
  });

  it("L2 renders sector picks + relationship_mapper differently", () => {
    const s = baseState();
    expect(renderLayer2Context(s)).toContain("not available");
    s.layer2_outputs = { semiconductor: semi };
    expect(renderLayer2Context(s)).toContain("688981.SH");
    s.layer2_outputs = {
      relationship_mapper: {
        agent: "relationship_mapper",
        factual_edges: [
          {
            edge_local_id: "edge-1",
            source_entity: "688981.SH",
            target_entity: "semiconductor_equipment",
            edge_type: "supply_chain",
            claim_refs: ["mapper-claim"],
          },
        ],
        predictive_edges: [],
        predictive_graph_status: "NO_QUALIFIED_PREDICTIVE_EDGE",
        predictive_graph_abstention_confidence: 0.4,
        key_drivers: [
          { driver_local_id: "driver-1", summary: "fixture driver", claim_refs: ["mapper-claim"] },
        ],
        risks: [{ risk_local_id: "risk-1", summary: "spillover", claim_refs: ["mapper-claim"] }],
        claims: [
          {
            claim_id: "mapper-claim",
            claim_kind: "FACT",
            statement: "Relationship fixture.",
            structured_conclusion: { relationship: "supply_chain" },
            evidence_ids: ["fixture:mapper"],
            research_rule_refs: [],
          },
        ],
        claim_refs: ["mapper-claim"],
        macro_input_attributions: MACRO_AGENT_IDS.map((macroAgentId) => ({
          agent_id: macroAgentId,
          target_type: "SUBMISSION_SUMMARY",
          target_local_ref: "$SUBMISSION",
          claim_refs_used: [],
          effect: "NOT_MATERIAL",
        })),
      },
    };
    expect(renderLayer2Context(s)).toContain("factual_edges");
    expect(renderLayer2Context(s)).toContain("predictive_graph_status");
  });

  it("L3 renders superinvestor picks", () => {
    const s = baseState();
    expect(renderLayer3Context(s)).toContain("not available");
    s.layer3_outputs = { druckenmiller: druck };
    expect(renderLayer3Context(s)).toContain("688981.SH");
    expect(renderLayer3Context(s)).toContain("druckenmiller");
  });

  it("L4 peer renders cro + excludes self", () => {
    const s = baseState();
    expect(renderLayer4PeerContext(s)).toContain("none of the peer outputs");
    s.layer4_outputs = { ...s.layer4_outputs, cro };
    const ctx = renderLayer4PeerContext(s, ["cio"]);
    expect(ctx).toContain("BAD:regulatory");
    expect(ctx).toContain("multi-tier-1 cluster");
    // Self-exclude when called for autonomous_execution
    const ctxExcl = renderLayer4PeerContext(s, ["cro", "cio"]);
    expect(ctxExcl).not.toContain("BAD:regulatory");
  });

  it("keeps cohort provenance separate from a synthetic stance", () => {
    expect(renderJanusRegimeStub()).toContain("Cohort provenance");
    expect(renderJanusRegimeStub()).not.toContain("Phase 6 stub");
  });
});

describe("autonomous execution reliability boundary", () => {
  it("does not expose raw Darwinian fields in its model context", async () => {
    const { autonomousExecutionSpec } = await import(
      "../src/agents/decision/autonomous_execution.js"
    );
    const context = await autonomousExecutionSpec.buildUserContext(baseState());
    expect(context).not.toMatch(/darwinian|quartile|sharpe|weight_record/i);
    expect(context).toContain("frozen candidate target");
  });
});

// ============================================================ end-to-end via factory (cio)

describe("buildCioNode (Layer-4 factory smoke)", () => {
  let promptDir: string;

  class ScriptedLlm {
    invokeCalls = 0;
    bindToolsCalled = 0;
    structuredCalls = 0;
    readonly response: AIMessage;
    readonly structuredResponse: CioOutput;
    constructor(text: string, structured: CioOutput) {
      this.response = new AIMessage(text);
      this.structuredResponse = structured;
    }
    bindTools(_t: unknown): ScriptedLlm {
      this.bindToolsCalled++;
      return this;
    }
    withStructuredOutput(_s: unknown): { invoke: (input: unknown) => Promise<unknown> } {
      return {
        invoke: async () => {
          this.structuredCalls++;
          return this.structuredResponse;
        },
      };
    }
    async invoke(_messages: BaseMessage[]): Promise<AIMessage> {
      this.invokeCalls++;
      return this.response;
    }
  }

  class FallbackLlm {
    invokeCalls = 0;
    bindToolsCalled = 0;
    structuredCalls = 0;
    bindTools(_t: unknown): FallbackLlm {
      this.bindToolsCalled++;
      return this;
    }
    withStructuredOutput(_s: unknown): { invoke: (input: unknown) => Promise<unknown> } {
      return {
        invoke: async () => {
          this.structuredCalls++;
          throw new Error("force fallback");
        },
      };
    }
    async invoke(_messages: BaseMessage[]): Promise<AIMessage> {
      this.invokeCalls++;
      return new AIMessage("fallback text without JSON");
    }
  }

  function testConfig(): MosaicConfig {
    return {
      llm_provider: "fake",
      deep_think_llm: "fake",
      quick_think_llm: "fake",
      backend_url: null,
      anthropic_base_url: null,
      anthropic_effort: null,
      output_language: "Chinese",
      research_depth_name: "标准",
      active_cohort: "cohort_default",
      cohorts: { cohort_default: { start: "2000-01-01", end: "2099-12-31" } },
      autoresearch: {
        agent_mutation_cooldown_hours: 24,
        keep_revert_lockout_days: 3,
        keep_threshold_delta_sharpe: 0.1,
        monthly_modification_cap_per_cohort: 100,
        evaluation_horizon_trading_days: 5,
      },
      data_vendors: {},
      tool_vendors: {},
    };
  }

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-l4-"));
    const dir = join(promptDir, "cohort_default", "decision");
    mkdirSync(dir, { recursive: true });
    const prompt = "FAKE-CIO";
    writeFileSync(join(dir, "cio.zh.md"), prompt, "utf-8");
    writeFileSync(join(dir, "cio.en.md"), prompt, "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("rejects an unreferenced CIO final output without publishing it", async () => {
    const cannedPortfolio: PortfolioAction[] = [
      {
        ticker: "688981.SH",
        action: "BUY",
        target_weight: 0.5,
        holding_period: "6M",
        dissent_notes: "",
      },
      {
        ticker: "600519.SH",
        action: "BUY",
        target_weight: 0.3,
        holding_period: "5Y+",
        dissent_notes: "alpha_discovery flagged this; auto_exec missed",
      },
    ];
    const canned: CioOutput = {
      agent: "cio",
      portfolio_actions: cannedPortfolio,
      confidence: 0.55,
    };

    const llm = new ScriptedLlm("analysis text", canned);
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };

    const config: MosaicConfig = {
      llm_provider: "fake",
      deep_think_llm: "fake",
      quick_think_llm: "fake",
      backend_url: null,
      anthropic_base_url: null,
      anthropic_effort: null,
      output_language: "Chinese",
      research_depth_name: "标准",
      active_cohort: "cohort_default",
      cohorts: { cohort_default: { start: "2000-01-01", end: "2099-12-31" } },
      autoresearch: {
        agent_mutation_cooldown_hours: 24,
        keep_revert_lockout_days: 3,
        keep_threshold_delta_sharpe: 0.1,
        monthly_modification_cap_per_cohort: 100,
        evaluation_horizon_trading_days: 5,
      },
      data_vendors: {},
      tool_vendors: {},
    };

    const sample: DailyCycleStateType = baseState();
    sample.layer1_outputs = Object.fromEntries(
      MACRO_AGENT_IDS.map((agent) => [
        agent,
        macroOutput(
          agent,
          agent === "china" ? { direction: "SUPPORTIVE", strength: 3 } : undefined,
        ),
      ]),
    );
    sample.macro_input_gate = validateMacroInputs(sample.layer1_outputs);
    sample.layer4_outputs = {
      cro: {
        agent: "cro",
        rejected_picks: [],
        correlated_risks: [],
        black_swan_scenarios: ["fed pivot"],
        confidence: 0.4,
      },
      alpha_discovery: {
        agent: "alpha_discovery",
        novel_picks: [{ ticker: "600519.SH", why_missed_by_others: "ackman 嫌小" }],
        confidence: 0.5,
      },
      autonomous_execution: {
        agent: "autonomous_execution",
        trades: [{ ticker: "688981.SH", action: "BUY", size_pct: 0.5, conviction: 0.7 }],
        confidence: 0.5,
      },
      cio: null,
    };

    const node = buildCioNode({ llmHandle: handle, config, promptsRoot: promptDir });
    await expect(node(sample)).rejects.toBeInstanceOf(AgentRunContractError);
    expect(llm.bindToolsCalled).toBe(0); // Layer-4 bypasses tool loop
    expect(llm.structuredCalls).toBeGreaterThan(0);
  });

  it("rejects omitted positions instead of freezing runtime fallback HOLDs", async () => {
    const llm = new FallbackLlm();
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };
    const sample: DailyCycleStateType = baseState();
    sample.current_positions = loadedPositions([
      heldPosition,
      {
        ...heldPosition,
        ticker: "688981.SH",
        current_weight: 0.08,
        entry_thesis_id: "thesis-688981",
      },
      {
        ...heldPosition,
        ticker: "300750.SZ",
        current_weight: 0.05,
        entry_thesis_id: "thesis-300750",
      },
    ]);

    const node = buildCioProposalNode({
      llmHandle: handle,
      config: testConfig(),
      promptsRoot: promptDir,
    });
    await expect(node(sample)).rejects.toBeInstanceOf(AgentRunContractError);
    expect(llm.structuredCalls).toBeGreaterThan(0);
  });

  it("passes runtime evidence ids to extraction and verifies action claim refs", async () => {
    const previousEnabled = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES;
    process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES = "cio:cio_proposal";
    try {
      const prompt = "FAKE-CIO";
      const dir = join(promptDir, "cohort_default", "decision");
      writeFileSync(join(dir, "cio.zh.md"), prompt, "utf-8");
      writeFileSync(join(dir, "cio.en.md"), prompt, "utf-8");
      clearPromptCache();

      class EvidenceAwareLlm {
        invokeCalls = 0;
        structuredCalls = 0;
        evidenceId: string | undefined;
        async invoke(): Promise<AIMessage> {
          this.invokeCalls++;
          return new AIMessage("Hold the existing position on current account evidence.");
        }
        withStructuredOutput(): { invoke: (messages: BaseMessage[]) => Promise<unknown> } {
          return {
            invoke: async (messages) => {
              this.structuredCalls++;
              const text = messages.map((message) => String(message.content)).join("\n");
              const marker = "Runtime-owned evidence catalog (use only these evidence_id values):";
              const markerIndex = text.indexOf(marker);
              if (!this.evidenceId && markerIndex >= 0) {
                const catalog = JSON.parse(text.slice(markerIndex + marker.length).trim()) as {
                  evidence: Array<{ evidence_id: string; freshness: string }>;
                };
                this.evidenceId = catalog.evidence.find(
                  (entry) => entry.freshness === "current",
                )?.evidence_id;
              }
              const evidenceId = this.evidenceId;
              if (!evidenceId) throw new Error("current evidence missing from extraction catalog");
              return {
                agent_id: "cio",
                decision_stage: "PROPOSAL",
                decision_disposition: "HOLD_CURRENT",
                decision_reason: "Current evidence supports holding the existing target.",
                cash_weight: 0.8,
                target_positions: [
                  {
                    position_local_id: "position-hold",
                    ts_code: "600519.SH",
                    position_decision: "HOLD",
                    target_weight: 0.2,
                    holding_period: "WEEKS",
                    thesis_status: "INTACT",
                    risk_flags: [],
                    claim_refs: ["claim-hold"],
                  },
                ],
                confidence: 0.5,
                claims: [
                  {
                    claim_id: "claim-hold",
                    claim_kind: "FACT",
                    statement: "Keep the existing target unchanged.",
                    structured_conclusion: { decision: "HOLD" },
                    evidence_ids: [evidenceId ?? "missing"],
                    research_rule_refs: [],
                  },
                ],
                claim_refs: ["claim-hold"],
                macro_input_attributions: MACRO_AGENT_IDS.map((agent_id) => ({
                  agent_id,
                  target_type: "SUBMISSION_SUMMARY",
                  target_local_ref: "$SUBMISSION",
                  claim_refs_used: [],
                  effect: "NOT_MATERIAL",
                })),
              };
            },
          };
        }
      }

      const llm = new EvidenceAwareLlm();
      const sample = baseState();
      sample.trace_id = "claim-run";
      sample.current_positions = loadedPositions([heldPosition]);
      const runtime = emptyLayer4RuntimeState();
      runtime.resolved_source_statuses = [
        {
          source_id: "current_market_data",
          scope: "ticker:600519.SH",
          status: "loaded",
          as_of: sample.as_of_date,
          snapshot_hash: `sha256:${"4".repeat(64)}`,
          adapter_id: "market.scoped_snapshot_adapter.v1",
        },
      ];
      sample.layer4_outputs = {
        ...sample.layer4_outputs,
        runtime,
        previous_target_state: missingPreviousTargetState(),
      };
      const handle: LlmHandle = {
        llm: llm as unknown as LlmHandle["llm"],
        provider: "fake",
        model: "fake-model",
        baseUrl: undefined,
      };

      const update = await buildCioProposalNode({
        llmHandle: handle,
        config: testConfig(),
        promptsRoot: promptDir,
      })(sample);
      const proposal = (update.layer4_outputs as Partial<Layer4Outputs> | undefined)?.runtime
        ?.cio_proposal;

      expect(proposal?.verified_claim_audit).toEqual({
        raw_output_accepted: true,
        rejection_reasons: [],
      });
      expect(proposal?.verified_claim_graph?.recommendation_claim_refs).toEqual([
        {
          output_id: "recommendation:0:cio",
          output_type: "recommendation",
          claim_refs: ["claim-hold"],
        },
        {
          output_id: "target_position:0:600519.SH",
          output_type: "portfolio_action",
          claim_refs: ["claim-hold"],
        },
      ]);
      expect(llm.invokeCalls).toBe(1);
      expect(llm.structuredCalls).toBe(1);
    } finally {
      if (previousEnabled === undefined) {
        delete process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES;
      } else {
        process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES = previousEnabled;
      }
      clearPromptCache();
    }
  });
});

// ============================================================ end-to-end via factory (cro)

describe("buildCroNode (frozen snapshots, no portfolio_actions mirror)", () => {
  let promptDir: string;

  class ScriptedLlm {
    bindToolsCalled = 0;
    invokeCalls = 0;
    structuredCalls = 0;
    lastMessages: BaseMessage[] = [];
    constructor(public canned: CroOutput) {}
    bindTools(_t: unknown): ScriptedLlm {
      this.bindToolsCalled++;
      return this;
    }
    withStructuredOutput(schema: unknown): { invoke: (input: unknown) => Promise<unknown> } {
      return {
        invoke: async (input) => {
          this.structuredCalls++;
          return fakeAgentStructuredOutput(schema, "cro", input);
        },
      };
    }
    async invoke(messages: BaseMessage[]): Promise<AIMessage> {
      this.invokeCalls++;
      this.lastMessages = messages;
      return new AIMessage("cro analysis");
    }
  }

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-l4cro-"));
    const dir = join(promptDir, "cohort_default", "decision");
    mkdirSync(dir, { recursive: true });
    const prompt = "FAKE-CRO";
    writeFileSync(join(dir, "cro.zh.md"), prompt, "utf-8");
    writeFileSync(join(dir, "cro.en.md"), prompt, "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  function croApi(
    includeRke = false,
    calls: Array<{ name: string; args: Record<string, unknown> }> = [],
  ): BridgeApi {
    const names = [
      "get_cro_risk_snapshot",
      "get_role_event_snapshot",
      ...(includeRke ? ["get_rke_research_context"] : []),
    ];
    return {
      toolsList: async () =>
        names.map((name) => ({
          name,
          description: name,
          args_schema: { type: "object", properties: {}, required: [] },
        })),
      toolsCall: async (name: string, args: Record<string, unknown>) => {
        calls.push({ name, args });
        return { text: `Frozen snapshot from ${name}` };
      },
    } as unknown as BridgeApi;
  }

  it("does NOT write portfolio_actions (only cio does)", async () => {
    const canned: CroOutput = {
      agent: "cro",
      review_disposition: "NO_OBJECTION",
      rejected_picks: [],
      required_adjustments: [],
      correlated_risks: ["test"],
      black_swan_scenarios: ["test"],
      confidence: 0.4,
      claims: [
        {
          claim_id: "claim-no-objection",
          claim_kind: "RISK_FLAG",
          statement: "No evidence-backed objection was identified.",
          structured_conclusion: { decision: "NO_OBJECTION" },
          evidence_ids: ["test:no-objection"],
          research_rule_refs: [],
        },
      ],
      claim_refs: ["claim-no-objection"],
    };
    const llm = new ScriptedLlm(canned);
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };
    const config: MosaicConfig = {
      llm_provider: "fake",
      deep_think_llm: "fake",
      quick_think_llm: "fake",
      backend_url: null,
      anthropic_base_url: null,
      anthropic_effort: null,
      output_language: "Chinese",
      research_depth_name: "标准",
      active_cohort: "cohort_default",
      cohorts: { cohort_default: { start: "2000-01-01", end: "2099-12-31" } },
      autoresearch: {
        agent_mutation_cooldown_hours: 24,
        keep_revert_lockout_days: 3,
        keep_threshold_delta_sharpe: 0.1,
        monthly_modification_cap_per_cohort: 100,
        evaluation_horizon_trading_days: 5,
      },
      data_vendors: {},
      tool_vendors: {},
    };
    const sample = stateWithFrozenCandidate();
    const node = buildCroNode({
      llmHandle: handle,
      api: croApi(),
      config,
      promptsRoot: promptDir,
    });
    const update = await node(sample);
    const u = update as DailyCycleStateUpdate as unknown as {
      layer4_outputs?: Partial<Layer4Outputs>;
      portfolio_actions?: PortfolioAction[];
    };
    expect(u.layer4_outputs?.cro).toMatchObject({
      agent: "cro",
      review_disposition: "NO_OBJECTION",
    });
    expect(u.portfolio_actions).toBeUndefined();
    expect(llm.bindToolsCalled).toBe(0);
    expect(llm.invokeCalls).toBe(1);
  });

  it("keeps RKE research context outside the production decision graph", async () => {
    const canned: CroOutput = {
      agent: "cro",
      review_disposition: "NO_OBJECTION",
      rejected_picks: [],
      required_adjustments: [],
      correlated_risks: ["test"],
      black_swan_scenarios: ["test"],
      confidence: 0.4,
      claims: [
        {
          claim_id: "claim-no-objection",
          claim_kind: "RISK_FLAG",
          statement: "No evidence-backed objection was identified.",
          structured_conclusion: { decision: "NO_OBJECTION" },
          evidence_ids: ["test:no-objection"],
          research_rule_refs: [],
        },
      ],
      claim_refs: ["claim-no-objection"],
    };
    const llm = new ScriptedLlm(canned);
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake-model",
      baseUrl: undefined,
    };
    const config: MosaicConfig = {
      llm_provider: "fake",
      deep_think_llm: "fake",
      quick_think_llm: "fake",
      backend_url: null,
      anthropic_base_url: null,
      anthropic_effort: null,
      output_language: "Chinese",
      research_depth_name: "标准",
      active_cohort: "cohort_default",
      cohorts: { cohort_default: { start: "2000-01-01", end: "2099-12-31" } },
      autoresearch: {
        agent_mutation_cooldown_hours: 24,
        keep_revert_lockout_days: 3,
        keep_threshold_delta_sharpe: 0.1,
        monthly_modification_cap_per_cohort: 100,
        evaluation_horizon_trading_days: 5,
      },
      data_vendors: {},
      tool_vendors: {},
    };
    const toolCalls: Array<{ name: string; args: Record<string, unknown> }> = [];
    const api = croApi(true, toolCalls);

    const node = buildCroNode({ llmHandle: handle, api, config, promptsRoot: promptDir });
    await node(stateWithFrozenCandidate());

    expect(toolCalls.map((call) => call.name)).not.toContain("get_rke_research_context");
    expect(llm.bindToolsCalled).toBe(0);
    expect(llm.invokeCalls).toBe(1);
    expect(llm.lastMessages.map((msg) => String(msg.content)).join("\n")).not.toContain(
      "RKE research prior context",
    );
  });
});

// Compile-time canary
const _allBuilders = {
  cro: buildCroNode,
  alpha_discovery: buildAlphaDiscoveryNode,
  autonomous_execution: buildAutonomousExecutionNode,
  cio: buildCioNode,
};
void _allBuilders;
void ({} as BridgeApi);

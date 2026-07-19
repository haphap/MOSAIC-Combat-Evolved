import { describe, expect, it } from "vitest";
import type { CioProposalSubmission } from "../src/agents/decision/accepted.js";
import {
  buildAgentInvocationId,
  buildRuntimeEvidenceSnapshot,
  selectOutputByClaimEvidence,
} from "../src/agents/helpers/evidence_runtime.js";
import type { PrivateKnotSnapshot } from "../src/agents/helpers/private_knot_boundary.js";
import { resolveRuntimeSourceStatusesForAgent } from "../src/agents/helpers/runtime_sources.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import { fallbackSuperinvestorOutput } from "../src/agents/superinvestor/_factory.js";
import type {
  CentralBankOutput,
  CioOutput,
  MungerOutput,
  SemiconductorOutput,
} from "../src/agents/types.js";
import { macroSubmission } from "./helpers/macro.js";
import { sectorOutput } from "./helpers/sector.js";

const HASH = `sha256:${"1".repeat(64)}`;
const MARKET_HASH = `sha256:${"2".repeat(64)}`;
const TOOL_HASH = `sha256:${"3".repeat(64)}`;

function invocationBinding(
  agent = "cio",
  stage: PrivateKnotSnapshot["stage"] = "cio_proposal",
  graphRunId = "run-1",
) {
  const asOf = "2026-07-09";
  return {
    invocation_mode: "NON_PRODUCTION_TEST" as const,
    graph_run_id: graphRunId,
    agent_invocation_id: buildAgentInvocationId({
      runId: graphRunId,
      agent,
      stage,
      cohort: "cohort_default",
      asOf,
      promptReleaseHash: HASH,
    }),
    as_of: asOf,
    execution_behavior_release_id: "non-production-test",
    prompt_release_id: "non-production-test",
    prompt_release_hash: HASH,
    prompt_pair_hash: HASH,
    prompt_commit: "non-production",
  };
}

function knobSnapshot(
  agent = "cio",
  stage: PrivateKnotSnapshot["stage"] = "cio_proposal",
  graphRunId = "run-1",
): PrivateKnotSnapshot {
  return {
    snapshot_id: "private-session:test",
    snapshot_hash: HASH,
    agent,
    stage,
    cohort: "cohort_default",
    ...invocationBinding(agent, stage, graphRunId),
    evidence_bindings: [
      {
        evidence_key: "current_position_snapshot",
        source: "current_position_snapshot",
        metric: "current_position_snapshot",
      },
      {
        evidence_key: "current_market_data",
        source: "current_market_data",
        metric: "current_market_data",
      },
      {
        evidence_key: "rke_prior",
        tool: "get_rke_research_context",
        metric: "research_prior",
      },
    ],
    allowed_research_rule_ids: ["decision.cio.policy.001"],
    runtime_source_statuses: [
      {
        source_id: "current_position_snapshot",
        scope: "account:default|run:run-1",
        status: "loaded",
        as_of: "2026-07-09",
        snapshot_hash: HASH,
      },
      {
        source_id: "current_market_data",
        scope: "ticker:600519.SH",
        status: "loaded",
        as_of: "2026-07-09",
        snapshot_hash: MARKET_HASH,
        adapter_id: "market.scoped_snapshot_adapter.v1",
      },
    ],
  };
}

function state(): DailyCycleStateType {
  return {
    active_cohort: "cohort_default",
    as_of_date: "2026-07-09",
    trace_id: "run-1",
    current_positions: {
      snapshot_status: "loaded",
      position_source: "cli_fixture",
      source_error_code: null,
      position_snapshot_hash: HASH,
      positions: [
        {
          ticker: "600519.SH",
          current_weight: 0.1,
          cost_basis: 1400,
          market_price: 1500,
          unrealized_pnl_pct: 0.0714,
          holding_days: 10,
          entry_date: "2026-06-25",
          source_agent: "cio",
          entry_thesis_id: "thesis-1",
          last_review_date: "2026-07-08",
        },
      ],
    },
    layer1_outputs: {},
    layer2_outputs: {},
    layer3_outputs: {},
    layer4_outputs: {
      cro: null,
      alpha_discovery: null,
      autonomous_execution: null,
      cio: null,
      runtime: {
        source_evidence_observations: [
          {
            source_id: "current_market_data",
            scope: "ticker:600519.SH",
            metric: "current_market_data",
            value: { date: "2026-07-09", close: 1500, volume: 1200 },
            unit: "market_record",
            as_of: "2026-07-09",
            lookback: "10d",
            freshness: "current",
            source_fingerprint: MARKET_HASH,
            direction: "ambiguous",
            privacy_class: "private_runtime",
            adapter_id: "market.scoped_snapshot_adapter.v1",
            adapter_version: "1",
          },
        ],
      },
    },
  } as unknown as DailyCycleStateType;
}

describe("runtime evidence snapshots", () => {
  it("binds source and tool observations to one invocation snapshot", () => {
    const result = buildRuntimeEvidenceSnapshot({
      state: state(),
      agent: "cio",
      stage: "cio_proposal",
      knobSnapshot: knobSnapshot(),
      toolStatuses: [
        {
          name: "get_rke_research_context",
          call_id: "call-1",
          agent_invocation_id: "ignored-untrusted-id",
          called: true,
          failed: false,
          missing: false,
          fallback: false,
          cache_hit: false,
          args_fingerprint: HASH,
          result_fingerprint: TOOL_HASH,
          source_fingerprint: TOOL_HASH,
          as_of: "2026-07-09",
        },
      ],
    });

    expect(result.agentInvocationId).toMatch(/^agent-invocation:[0-9a-f]{64}$/);
    expect(result.evidenceLedger).toHaveLength(3);
    expect(result.evidenceLedger).toContainEqual(
      expect.objectContaining({
        tool_or_source: "current_market_data",
        value: { date: "2026-07-09", close: 1500, volume: 1200 },
        source_fingerprint: MARKET_HASH,
      }),
    );
    expect(result.evidenceLedger).toContainEqual(
      expect.objectContaining({
        tool_or_source: "get_rke_research_context",
        metric: "research_prior",
        source_fingerprint: TOOL_HASH,
      }),
    );
    expect(result.evidenceLedger.every((entry) => entry.run_id === "run-1")).toBe(true);
    expect(result.evidenceLedger.every((entry) => entry.snapshot_hash === HASH)).toBe(true);
    expect(result.allowedResearchRuleIds).toEqual(new Set(["decision.cio.policy.001"]));
    expect(result.visibleCatalog).toContain(result.evidenceLedger[0]?.evidence_id ?? "missing");
    expect(result.visibleCatalog).toContain("decision.cio.policy.001");
    expect(result.visibleCatalog).toContain("allowed_citation_ids");
    expect(result.visibleCatalog).not.toContain("allowed_research_rule_ids");
  });

  it("rejects cross-run snapshot reuse and changes ids with a newly bound snapshot", () => {
    const first = buildRuntimeEvidenceSnapshot({
      state: state(),
      agent: "cio",
      stage: "cio_proposal",
      knobSnapshot: knobSnapshot(),
    });
    const changedState = state();
    changedState.trace_id = "run-2";
    expect(() =>
      buildRuntimeEvidenceSnapshot({
        state: changedState,
        agent: "cio",
        stage: "cio_proposal",
        knobSnapshot: knobSnapshot(),
      }),
    ).toThrow(/private_knot_snapshot_graph_run_id_mismatch/);
    const second = buildRuntimeEvidenceSnapshot({
      state: changedState,
      agent: "cio",
      stage: "cio_proposal",
      knobSnapshot: knobSnapshot("cio", "cio_proposal", "run-2"),
    });

    expect(second.agentInvocationId).not.toBe(first.agentInvocationId);
    expect(second.evidenceLedger[0]?.evidence_id).not.toBe(first.evidenceLedger[0]?.evidence_id);
    expect(
      buildAgentInvocationId({
        runId: "run-1",
        agent: "cio",
        stage: "cio_proposal",
        cohort: "cohort_default",
        asOf: "2026-07-09",
        promptReleaseHash: HASH,
      }),
    ).toBe(first.agentInvocationId);
  });

  it.each([
    ["source_fingerprint", HASH],
    ["as_of", "2026-07-08"],
    ["freshness", "stale"],
    ["adapter_id", "market.other_adapter.v1"],
    ["metric", "other_metric"],
  ] as const)("rejects a runtime observation with mismatched %s", (field, value) => {
    const inputState = state();
    const observation = inputState.layer4_outputs.runtime?.source_evidence_observations?.[0];
    if (!observation) throw new Error("test observation missing");
    Object.assign(observation, { [field]: value });

    expect(() =>
      buildRuntimeEvidenceSnapshot({
        state: inputState,
        agent: "cio",
        stage: "cio_proposal",
        knobSnapshot: knobSnapshot(),
      }),
    ).toThrow(
      `runtime_source_observation_status_mismatch:current_market_data:ticker:600519.SH:${field}`,
    );
  });

  it("extracts a loaded position thesis from the exact ticker scope", () => {
    const inputState = state();
    const status = resolveRuntimeSourceStatusesForAgent(inputState, "cio", "cio_proposal").find(
      (item) => item.source_id === "position_thesis_state",
    );
    if (!status) throw new Error("position thesis status missing");
    const snapshot: PrivateKnotSnapshot = {
      snapshot_id: "private-session:position-thesis",
      snapshot_hash: HASH,
      agent: "cio",
      stage: "cio_proposal",
      cohort: "cohort_default",
      ...invocationBinding(),
      evidence_bindings: [
        {
          evidence_key: "position_thesis_state",
          source: "position_thesis_state",
          metric: "position_thesis_state",
        },
      ],
      allowed_research_rule_ids: [],
      runtime_source_statuses: [status],
    };

    const result = buildRuntimeEvidenceSnapshot({
      state: inputState,
      agent: "cio",
      stage: "cio_proposal",
      knobSnapshot: snapshot,
    });

    expect(result.evidenceLedger).toHaveLength(1);
    expect(result.evidenceLedger[0]).toEqual(
      expect.objectContaining({
        tool_or_source: "position_thesis_state",
        source_fingerprint: status.snapshot_hash,
        value: {
          entry_thesis_id: "thesis-1",
          last_review_date: "2026-07-08",
          ticker: "600519.SH",
        },
      }),
    );
  });

  it("keeps a missing position thesis content-free", () => {
    const inputState = state();
    inputState.current_positions = {
      ...inputState.current_positions,
      snapshot_status: "empty_confirmed",
      position_source: "empty_confirmed",
      positions: [],
    };
    const status = {
      source_id: "position_thesis_state",
      scope: "ticker:600519.SH",
      status: "missing" as const,
      as_of: inputState.as_of_date,
      error_code: "position_thesis_missing",
      adapter_id: "portfolio.position_thesis_adapter.v1",
    };
    const snapshot: PrivateKnotSnapshot = {
      snapshot_id: "private-session:position-thesis-missing",
      snapshot_hash: HASH,
      agent: "cio",
      stage: "cio_proposal",
      cohort: "cohort_default",
      ...invocationBinding(),
      evidence_bindings: [
        {
          evidence_key: "position_thesis_state",
          source: "position_thesis_state",
          metric: "position_thesis_state",
        },
      ],
      allowed_research_rule_ids: [],
      runtime_source_statuses: [status],
    };

    const result = buildRuntimeEvidenceSnapshot({
      state: inputState,
      agent: "cio",
      stage: "cio_proposal",
      knobSnapshot: snapshot,
    });

    expect(result.evidenceLedger[0]?.value).toEqual({
      scope: "ticker:600519.SH",
      status: "missing",
      snapshot_hash: null,
      error_code: "position_thesis_missing",
    });
  });

  it.each([
    ["source_fingerprint", { snapshot_hash: HASH }],
    ["adapter_id", { adapter_id: "portfolio.other_adapter.v1" }],
    ["as_of", { as_of: "2026-07-08" }],
    ["status", { status: "missing" as const }],
  ] as const)("rejects a position thesis with mismatched %s", (field, patch) => {
    const inputState = state();
    const status = resolveRuntimeSourceStatusesForAgent(inputState, "cio", "cio_proposal").find(
      (item) => item.source_id === "position_thesis_state",
    );
    if (!status) throw new Error("position thesis status missing");
    const snapshot: PrivateKnotSnapshot = {
      snapshot_id: "private-session:position-thesis-tamper",
      snapshot_hash: HASH,
      agent: "cio",
      stage: "cio_proposal",
      cohort: "cohort_default",
      ...invocationBinding(),
      evidence_bindings: [
        {
          evidence_key: "position_thesis_state",
          source: "position_thesis_state",
          metric: "position_thesis_state",
        },
      ],
      allowed_research_rule_ids: [],
      runtime_source_statuses: [{ ...status, ...patch }],
    };

    expect(() =>
      buildRuntimeEvidenceSnapshot({
        state: inputState,
        agent: "cio",
        stage: "cio_proposal",
        knobSnapshot: snapshot,
      }),
    ).toThrow(
      `runtime_source_observation_status_mismatch:position_thesis_state:ticker:600519.SH:${field}`,
    );
  });

  it.each([
    "current_market_data",
    "execution_liquidity_state",
  ] as const)("rejects loaded %s status without its exact observation", (sourceId) => {
    const inputState = state();
    const runtime = inputState.layer4_outputs.runtime;
    if (!runtime) throw new Error("layer-4 runtime missing");
    runtime.source_evidence_observations = [];
    const snapshot: PrivateKnotSnapshot = {
      snapshot_id: `private-session:${sourceId}`,
      snapshot_hash: HASH,
      agent: "cio",
      stage: "cio_proposal",
      cohort: "cohort_default",
      ...invocationBinding(),
      evidence_bindings: [
        {
          evidence_key: sourceId,
          source: sourceId,
          metric: sourceId,
        },
      ],
      allowed_research_rule_ids: [],
      runtime_source_statuses: [
        {
          source_id: sourceId,
          scope: "ticker:600519.SH",
          status: "loaded",
          as_of: "2026-07-09",
          snapshot_hash: MARKET_HASH,
          adapter_id: `${sourceId}.adapter.v1`,
        },
      ],
    };

    expect(() =>
      buildRuntimeEvidenceSnapshot({
        state: inputState,
        agent: "cio",
        stage: "cio_proposal",
        knobSnapshot: snapshot,
      }),
    ).toThrow(
      `runtime_source_observation_status_mismatch:${sourceId}:ticker:600519.SH:observation`,
    );
  });

  it("accepts an action only when its claim graph closes over runtime evidence", () => {
    const runtime = buildRuntimeEvidenceSnapshot({
      state: state(),
      agent: "cio",
      stage: "cio_proposal",
      knobSnapshot: knobSnapshot(),
    });
    const evidenceId = runtime.evidenceLedger.find(
      (entry) => entry.tool_or_source === "current_market_data",
    )?.evidence_id;
    expect(evidenceId).toBeDefined();
    const raw: CioProposalSubmission = {
      agent_id: "cio",
      decision_stage: "PROPOSAL",
      decision_disposition: "TARGET_PORTFOLIO",
      claim_refs: ["claim-1"],
      target_positions: [
        {
          position_local_id: "position-1",
          ts_code: "600519.SH",
          target_weight: 0.1,
          position_decision: "HOLD",
          holding_period: "MONTHS",
          thesis_status: "INTACT",
          risk_flags: [],
          claim_refs: ["claim-1"],
        },
      ],
      cash_weight: 0.9,
      decision_reason: "The existing position remains supported.",
      confidence: 0.6,
      macro_input_attributions: [],
      claims: [
        {
          claim_id: "claim-1",
          claim_kind: "INTERPRETATION",
          statement: "Current evidence supports holding the existing position.",
          structured_conclusion: { decision: "HOLD" },
          evidence_ids: [evidenceId ?? "missing"],
          research_rule_refs: ["decision.cio.policy.001"],
        },
      ],
    };

    const selected = selectOutputByClaimEvidence(
      raw,
      (): CioProposalSubmission => ({
        agent_id: "cio",
        decision_stage: "PROPOSAL",
        decision_disposition: "ALL_CASH",
        target_positions: [],
        cash_weight: 1,
        decision_reason: "Fallback to cash.",
        confidence: 0,
        macro_input_attributions: [],
        claims: raw.claims,
        claim_refs: raw.claim_refs,
      }),
      runtime,
    );

    expect(selected.rawOutputAccepted).toBe(true);
    expect(selected.graph.recommendation_claim_refs).toEqual([
      {
        output_id: "recommendation:0:cio",
        output_type: "recommendation",
        claim_refs: ["claim-1"],
      },
      {
        output_id: "target_position:0:600519.SH",
        output_type: "portfolio_action",
        claim_refs: ["claim-1"],
      },
    ]);
    expect(selected.output.verified_claim_audit?.raw_output_accepted).toBe(true);
  });

  it("binds a macro recommendation to top-level claim references", () => {
    const runtime = buildRuntimeEvidenceSnapshot({
      state: state(),
      agent: "central_bank",
      stage: "agent_run",
      knobSnapshot: knobSnapshot("central_bank", "agent_run"),
    });
    const evidenceId = runtime.evidenceLedger.find(
      (entry) => entry.tool_or_source === "current_market_data",
    )?.evidence_id;
    const baseSubmission = macroSubmission("central_bank");
    if (baseSubmission.mode !== "COMPONENTS") throw new Error("central_bank is component mode");
    const raw: CentralBankOutput = macroSubmission("central_bank", {
      key_drivers: ["Current market evidence is neutral"],
      claims: [
        {
          claim_id: "claim-macro-1",
          claim_kind: "INTERPRETATION",
          statement: "Current evidence supports a neutral policy stance.",
          structured_conclusion: { direction: "NEUTRAL", strength: 0 },
          evidence_ids: [evidenceId ?? "missing"],
          research_rule_refs: ["decision.cio.policy.001"],
        },
      ],
      components: baseSubmission.components.map((component) => ({
        ...component,
        claim_refs: ["claim-macro-1"],
      })),
    });

    const selected = selectOutputByClaimEvidence(
      raw,
      (): CentralBankOutput => macroSubmission("central_bank"),
      runtime,
    );

    expect(selected.rawOutputAccepted).toBe(true);
    expect(selected.graph.recommendation_claim_refs).toEqual([
      {
        output_id: "recommendation:0:central_bank",
        output_type: "recommendation",
        claim_refs: ["claim-macro-1"],
      },
    ]);
  });

  it("requires both sector-level and per-candidate claim references", () => {
    const runtime = buildRuntimeEvidenceSnapshot({
      state: state(),
      agent: "semiconductor",
      stage: "agent_run",
      knobSnapshot: knobSnapshot("semiconductor", "agent_run"),
    });
    const evidenceId = runtime.evidenceLedger.find(
      (entry) => entry.tool_or_source === "current_market_data",
    )?.evidence_id;
    const raw: SemiconductorOutput = sectorOutput("semiconductor", {
      preferred_security_status: "PICKS_PRESENT",
      preferred_security_abstention_confidence: null,
      long_picks: [
        {
          pick_local_id: "pick-sector-1",
          ts_code: "600519.SH",
          direction_local_id: "semiconductor-preferred",
          position_action: "LONG",
          thesis: "verified candidate",
          conviction: 0.5,
          claim_refs: ["claim-sector-1"],
        },
      ],
      claim_refs: ["claim-sector-1"],
      claims: [
        {
          claim_id: "claim-sector-1",
          claim_kind: "INTERPRETATION",
          statement: "Current evidence supports the candidate and sector tilt.",
          structured_conclusion: { selection_status: "SELECTED" },
          evidence_ids: [evidenceId ?? "missing"],
          research_rule_refs: ["decision.cio.policy.001"],
        },
      ],
    });

    const selected = selectOutputByClaimEvidence(
      raw,
      (): SemiconductorOutput => sectorOutput("semiconductor"),
      runtime,
    );

    expect(selected.rawOutputAccepted).toBe(true);
    expect(selected.graph.recommendation_claim_refs).toEqual([
      {
        output_id: "recommendation:0:semiconductor",
        output_type: "recommendation",
        claim_refs: ["claim-sector-1"],
      },
      {
        output_id: "long_candidate:0:600519.SH",
        output_type: "candidate",
        claim_refs: ["claim-sector-1"],
      },
    ]);
  });

  it("requires both philosophy-level and per-pick claim references", () => {
    const runtime = buildRuntimeEvidenceSnapshot({
      state: state(),
      agent: "munger",
      stage: "agent_run",
      knobSnapshot: knobSnapshot("munger", "agent_run"),
    });
    const evidenceId = runtime.evidenceLedger.find(
      (entry) => entry.tool_or_source === "current_market_data",
    )?.evidence_id;
    const raw: MungerOutput = {
      ...fallbackSuperinvestorOutput("munger", "Current evidence"),
      agent: "munger",
      selection_status: "SELECTED",
      picks: [
        {
          pick_local_id: "munger-pick-1",
          ts_code: "600519.SH",
          position_action: "LONG",
          thesis: "verified quality",
          conviction: 0.5,
          claim_refs: ["claim-pick-1"],
        },
      ],
      holding_period: "YEARS",
      key_drivers: [
        {
          driver_local_id: "munger-driver-1",
          summary: "Current evidence",
          claim_refs: ["claim-pick-1"],
        },
      ],
      risks: [
        {
          risk_local_id: "munger-risk-1",
          summary: "Quality evidence may weaken.",
          claim_refs: ["claim-pick-1"],
        },
      ],
      confidence: 0.5,
      claim_refs: ["claim-pick-1"],
      claims: [
        {
          claim_id: "claim-pick-1",
          claim_kind: "INTERPRETATION",
          statement: "Current evidence supports the philosophy-filtered pick.",
          structured_conclusion: { philosophy: "quality" },
          evidence_ids: [evidenceId ?? "missing"],
          research_rule_refs: ["decision.cio.policy.001"],
        },
      ],
    };

    const selected = selectOutputByClaimEvidence(
      raw,
      (): MungerOutput => fallbackSuperinvestorOutput("munger", "fallback") as MungerOutput,
      runtime,
    );

    expect(selected.rawOutputAccepted).toBe(true);
    expect(selected.graph.recommendation_claim_refs).toEqual([
      {
        output_id: "recommendation:0:munger",
        output_type: "recommendation",
        claim_refs: ["claim-pick-1"],
      },
      {
        output_id: "pick:0:600519.SH",
        output_type: "candidate",
        claim_refs: ["claim-pick-1"],
      },
    ]);
  });

  it("replaces dangling action claims with a runtime-owned uncertainty fallback", () => {
    const runtime = buildRuntimeEvidenceSnapshot({
      state: state(),
      agent: "cio",
      stage: "cio_proposal",
      knobSnapshot: knobSnapshot(),
    });
    const raw: CioOutput = {
      agent: "cio",
      decision_claim_refs: ["claim-1"],
      portfolio_actions: [
        {
          ticker: "600519.SH",
          action: "BUY",
          target_weight: 0.1,
          holding_period: "1M",
          dissent_notes: "",
          claim_refs: ["claim-1"],
        },
      ],
      confidence: 0.7,
      claims: [
        {
          claim_id: "claim-1",
          claim_kind: "INTERPRETATION",
          statement: "Unsupported buy.",
          structured_conclusion: { decision: "BUY" },
          evidence_ids: ["invented-evidence"],
          research_rule_refs: ["decision.cio.policy.001"],
        },
      ],
    };

    const selected = selectOutputByClaimEvidence(
      raw,
      (): CioOutput => ({ agent: "cio", portfolio_actions: [], confidence: 0 }),
      runtime,
    );

    expect(selected.rawOutputAccepted).toBe(false);
    expect(selected.output.portfolio_actions).toEqual([]);
    expect(selected.output.verified_claim_audit).toEqual(
      expect.objectContaining({
        raw_output_accepted: false,
        fallback_reason_code: "CLAIM_EVIDENCE_GRAPH_REJECTED",
        rejection_reasons: expect.arrayContaining([
          expect.stringContaining("claim_unknown_evidence_ref"),
        ]),
      }),
    );
    expect(selected.graph.claims).toEqual([expect.objectContaining({ claim_kind: "RISK_FLAG" })]);
  });
});

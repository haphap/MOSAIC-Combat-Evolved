import { describe, expect, it } from "vitest";
import {
  buildAgentInvocationId,
  buildRuntimeEvidenceSnapshot,
  selectOutputByClaimEvidence,
} from "../src/agents/helpers/evidence_runtime.js";
import type { ResearchKnobsSnapshot } from "../src/agents/helpers/research_knobs.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { CioOutput } from "../src/agents/types.js";

const HASH = `sha256:${"1".repeat(64)}`;
const MARKET_HASH = `sha256:${"2".repeat(64)}`;
const TOOL_HASH = `sha256:${"3".repeat(64)}`;

function knobSnapshot(): ResearchKnobsSnapshot {
  return {
    agent: "cio",
    cohort: "cohort_default",
    stage: "cio_proposal",
    hash: HASH,
    knobs: {
      schema_version: "research_knobs_v1",
      layer: "decision",
      agent: "decision.cio",
      research_scope: { must_cover: [], must_not_cover: [] },
      prediction_targets: [],
      evidence_registry: {
        current_position_snapshot: {
          source: "daily_cycle_state",
          metric: "current_position_snapshot",
          current_data: true,
          primary: true,
        },
        current_market_data: {
          source: "daily_cycle_state",
          metric: "current_market_data",
          current_data: true,
          primary: true,
        },
        rke_prior: {
          tool: "get_rke_research_context",
          metric: "research_prior",
          current_data: false,
          primary: false,
        },
      },
      evidence_weights: {
        current_position_snapshot: 0.5,
        current_market_data: 0.5,
      },
      lookbacks: {},
      thresholds: {},
      confidence_caps: {},
      tie_breaks: [],
      mutation_targets: [
        {
          path: "/rule_packs/decision.cio.runtime.v1/rules/decision.cio.policy.001/learnable_parameters/x/value",
          type: "number",
          min: 0,
          max: 1,
        },
      ],
    },
    consumptionSnapshot: {
      active_knobs: [],
      disabled_knobs: [],
      runtimeSourceStatuses: [
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
        },
      ],
    },
    visibleContract: "",
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
  });

  it("changes invocation and evidence ids across runs", () => {
    const first = buildRuntimeEvidenceSnapshot({
      state: state(),
      agent: "cio",
      stage: "cio_proposal",
      knobSnapshot: knobSnapshot(),
    });
    const changedState = state();
    changedState.trace_id = "run-2";
    const second = buildRuntimeEvidenceSnapshot({
      state: changedState,
      agent: "cio",
      stage: "cio_proposal",
      knobSnapshot: knobSnapshot(),
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
        snapshotHash: HASH,
      }),
    ).toBe(first.agentInvocationId);
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
    const raw: CioOutput = {
      agent: "cio",
      portfolio_actions: [
        {
          ticker: "600519.SH",
          action: "HOLD",
          target_weight: 0.1,
          holding_period: "1M",
          dissent_notes: "",
          claim_refs: ["claim-1"],
        },
      ],
      confidence: 0.6,
      claims: [
        {
          claim_id: "claim-1",
          claim_type: "inference",
          statement: "Current evidence supports holding the existing position.",
          structured_conclusion: { decision: "HOLD" },
          evidence_refs: [evidenceId ?? "missing"],
          research_rule_refs: ["decision.cio.policy.001"],
        },
      ],
    };

    const selected = selectOutputByClaimEvidence(
      raw,
      (): CioOutput => ({ agent: "cio", portfolio_actions: [], confidence: 0 }),
      runtime,
    );

    expect(selected.rawOutputAccepted).toBe(true);
    expect(selected.graph.recommendation_claim_refs).toEqual([
      {
        output_id: "portfolio_action:0:600519.SH",
        output_type: "portfolio_action",
        claim_refs: ["claim-1"],
      },
    ]);
    expect(selected.output.verified_claim_audit?.raw_output_accepted).toBe(true);
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
          claim_type: "inference",
          statement: "Unsupported buy.",
          structured_conclusion: { decision: "BUY" },
          evidence_refs: ["invented-evidence"],
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
    expect(selected.graph.claims).toEqual([
      expect.objectContaining({ claim_type: "uncertainty", evidence_refs: [] }),
    ]);
  });
});

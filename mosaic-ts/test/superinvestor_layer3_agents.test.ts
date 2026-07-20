import { ToolMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import { canonicalAcceptedOutputHash } from "../src/agents/accepted_output.js";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import { validateMacroInputs } from "../src/agents/macro/_input_gate.js";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import { emptyCurrentPositions, emptyLayer4, emptyPositionAudit } from "../src/agents/state.js";
import {
  buildLayerThreeInitialToolCalls,
  buildLayerThreeUserContext,
  frozenSuperinvestorCandidateCodes,
  superinvestorAcceptedSnapshotRefs,
} from "../src/agents/superinvestor/_factory.js";
import { buildRuntimeSuperinvestorSchema } from "../src/agents/superinvestor/_schemas.js";
import { ackmanSpec, fallbackAckman, renderAckman } from "../src/agents/superinvestor/ackman.js";
import { burrySpec, fallbackBurry, renderBurry } from "../src/agents/superinvestor/burry.js";
import {
  druckenmillerSpec,
  fallbackDruckenmiller,
  renderDruckenmiller,
} from "../src/agents/superinvestor/druckenmiller.js";
import {
  buildMungerNode,
  fallbackMunger,
  mungerSpec,
  renderMunger,
} from "../src/agents/superinvestor/munger.js";
import type { BridgeApi, MosaicConfig } from "../src/bridge/index.js";
import { buildLayer3Graph } from "../src/graph/layer3.js";
import type { LlmHandle } from "../src/llm/factory.js";
import { macroOutput } from "./helpers/macro.js";
import { sectorOutput } from "./helpers/sector.js";

const specs = [druckenmillerSpec, mungerSpec, burrySpec, ackmanSpec] as const;

function state(): DailyCycleStateType {
  return {
    messages: [],
    active_cohort: "cohort_default",
    as_of_date: "2026-07-16",
    mode: "backtest",
    trace_id: "layer3-test",
    darwinian_runtime_binding: null,
    darwinian_weight_snapshot: null,
    component_weight_snapshot: null,
    component_calibration_inputs: {},
    outcome_schedule_plan: null,
    outcome_stage_skips: {},
    outcome_opportunity_bindings: {},
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

describe("Layer-3 superinvestor contracts", () => {
  it("keeps exactly four distinct roles", () => {
    expect([...AGENTS_BY_LAYER.superinvestor]).toEqual([
      "druckenmiller",
      "munger",
      "burry",
      "ackman",
    ]);
    expect(specs.map((spec) => spec.agentId)).toEqual([...AGENTS_BY_LAYER.superinvestor]);
  });

  it.each(specs)("$agentId preserves the common candidate contract", (spec) => {
    expect(spec.fieldNames).toEqual([
      "agent",
      "selection_status",
      "confidence",
      "holding_period",
      "picks",
      "key_drivers",
      "risks",
      "claims",
      "claim_refs",
      "macro_input_attributions",
    ]);
    expect(spec.requiredTools.length).toBeGreaterThan(0);
  });

  it("fallbacks abstain instead of inventing picks", () => {
    const druck = fallbackDruckenmiller("", null);
    const munger = fallbackMunger("", null);
    const burry = fallbackBurry("", null);
    const ackman = fallbackAckman("", null);
    const fallbacks = [druck, munger, burry, ackman];
    expect(
      fallbacks.every(
        (output) =>
          output.selection_status === "NO_QUALIFIED_CANDIDATES" &&
          output.picks.length === 0 &&
          output.confidence === 1,
      ),
    ).toBe(true);
    expect(renderDruckenmiller(druck).length).toBeGreaterThan(20);
    expect(renderMunger(munger).length).toBeGreaterThan(20);
    expect(renderBurry(burry).length).toBeGreaterThan(20);
    expect(renderAckman(ackman).length).toBeGreaterThan(20);
  });

  it("binds selections to the exact frozen candidate set and forces empty-domain abstention", () => {
    const fallback = fallbackAckman("No qualified candidate.", null);
    const selected = {
      ...fallback,
      selection_status: "SELECTED" as const,
      picks: [
        {
          pick_local_id: "pick-1",
          ts_code: "600519.SH",
          position_action: "LONG" as const,
          conviction: 0.8,
          thesis: "The frozen candidate passes the philosophy filter.",
          claim_refs: fallback.claim_refs,
        },
      ],
    };
    const bounded = buildRuntimeSuperinvestorSchema("ackman", ["600519.SH"]);
    expect(bounded.parse(selected).picks[0]?.ts_code).toBe("600519.SH");
    expect(
      bounded.safeParse({
        ...selected,
        picks: [{ ...selected.picks[0], ts_code: "000001.SZ" }],
      }).success,
    ).toBe(false);

    const empty = buildRuntimeSuperinvestorSchema("ackman", []);
    expect(empty.safeParse(selected).success).toBe(false);
    expect(empty.parse(fallback).selection_status).toBe("NO_QUALIFIED_CANDIDATES");
  });

  it("reads the runtime-owned candidate universe instead of model prose", () => {
    const message = new ToolMessage({
      tool_call_id: "initial_tool_1",
      content: JSON.stringify({
        candidate_universe: [{ ts_code: "600519.SH" }, { ticker: "000001.SZ" }],
        constraints: { cash_only: false, allow_new_positions: true },
      }),
    });
    expect(frozenSuperinvestorCandidateCodes([message])).toEqual(["000001.SZ", "600519.SH"]);
    expect(
      frozenSuperinvestorCandidateCodes([
        new ToolMessage({
          tool_call_id: "initial_tool_1",
          content: JSON.stringify({
            candidate_universe: [],
            constraints: { cash_only: true, allow_new_positions: false },
          }),
        }),
      ]),
    ).toEqual([]);
    expect(() =>
      frozenSuperinvestorCandidateCodes([
        new ToolMessage({
          tool_call_id: "initial_tool_1",
          content: JSON.stringify({
            candidate_universe: [{ ts_code: "600519.SH" }],
            constraints: { cash_only: true, allow_new_positions: false },
          }),
        }),
      ]),
    ).toThrow(/cash-only constraints/);
  });

  it("rejects candidate deletion or changed source context after authority freeze", () => {
    const candidateUniverse = [
      { candidate_ref: "candidate:1", ts_code: "600519.SH" },
      { candidate_ref: "candidate:2", ts_code: "000001.SZ" },
    ];
    const candidateUniverseHash = canonicalAcceptedOutputHash({
      candidate_status: "AVAILABLE",
      candidate_universe: candidateUniverse,
    });
    const candidateScope = {
      candidate_universe_id: "candidate-universe:1",
      candidate_universe_hash: candidateUniverseHash,
      constraint_set_id: "constraint-set:1",
      constraint_set_hash: `sha256:${"1".repeat(64)}`,
    };
    const candidateScopeHash = canonicalAcceptedOutputHash(candidateScope);
    const sourceSnapshotHash = `sha256:${"2".repeat(64)}`;
    const payload = {
      snapshot_hash: sourceSnapshotHash,
      candidate_status: "AVAILABLE",
      candidate_universe: candidateUniverse,
      candidate_universe_hash: candidateUniverseHash,
      candidate_scope: candidateScope,
      candidate_scope_hash: candidateScopeHash,
      constraints: { cash_only: false, allow_new_positions: true },
      role_context: { context_id: "context:1" },
    };
    const authority = { candidateScopeHash, candidateUniverseHash, sourceSnapshotHash };

    expect(
      frozenSuperinvestorCandidateCodes(
        [
          new ToolMessage({
            tool_call_id: "initial_tool_1",
            content: JSON.stringify(payload),
          }),
        ],
        authority,
      ),
    ).toEqual(["000001.SZ", "600519.SH"]);
    expect(() =>
      frozenSuperinvestorCandidateCodes(
        [
          new ToolMessage({
            tool_call_id: "initial_tool_1",
            content: JSON.stringify({
              ...payload,
              candidate_universe: candidateUniverse.slice(0, 1),
            }),
          }),
        ],
        authority,
      ),
    ).toThrow(/content hash mismatch/);
    expect(() =>
      frozenSuperinvestorCandidateCodes(
        [
          new ToolMessage({
            tool_call_id: "initial_tool_1",
            content: JSON.stringify({
              ...payload,
              snapshot_hash: `sha256:${"3".repeat(64)}`,
              role_context: { context_id: "context:2" },
            }),
          }),
        ],
        authority,
      ),
    ).toThrow(/changed after opportunity freeze/);
  });
});

describe("Layer-3 upstream consumption", () => {
  it("binds the relationship graph into the same frozen accepted-output closure", () => {
    const input = state();
    input.accepted_output_refs = {
      "RELATIONSHIP_GRAPH:relationship_mapper": {
        accepted_output_kind: "RELATIONSHIP_GRAPH",
        agent_id: "relationship_mapper",
        accepted_output_id: "accepted:relationship_mapper",
        accepted_output_hash: `sha256:${"a".repeat(64)}`,
      },
    };
    expect(superinvestorAcceptedSnapshotRefs(input)).toEqual([
      {
        key: "RELATIONSHIP_GRAPH:relationship_mapper",
        ...input.accepted_output_refs["RELATIONSHIP_GRAPH:relationship_mapper"],
      },
    ]);
  });

  it("renders independent Macro transmissions and sector direction/security outputs", () => {
    const input = state();
    input.layer1_outputs = Object.fromEntries(
      MACRO_AGENT_IDS.map((agent) => [
        agent,
        macroOutput(
          agent,
          agent === "china"
            ? { direction: "SUPPORTIVE", strength: 3 }
            : agent === "us_financial_conditions"
              ? { direction: "ADVERSE", strength: 2 }
              : undefined,
        ),
      ]),
    );
    input.macro_input_gate = validateMacroInputs(input.layer1_outputs);
    input.layer2_outputs = {
      semiconductor: sectorOutput("semiconductor", {
        preferred_security_status: "PICKS_PRESENT",
        preferred_security_abstention_confidence: null,
        long_picks: [
          {
            pick_local_id: "semi-pick",
            ts_code: "688981.SH",
            direction_local_id: "semiconductor-preferred",
            position_action: "LONG",
            conviction: 0.7,
            thesis: "fixture",
            claim_refs: ["semiconductor-claim"],
          },
        ],
      }),
    };
    const rendered = buildLayerThreeUserContext(input, "munger");
    expect(rendered).toContain("china");
    expect(rendered).toContain("us_financial_conditions");
    expect(rendered).toContain("688981.SH");
    expect(rendered).not.toContain("layer1_consensus");
  });

  it("builds deterministic initial calls only for the role tool list", () => {
    const calls = buildLayerThreeInitialToolCalls(state(), "munger");
    expect(calls.map((call) => call.name)).toEqual(mungerSpec.requiredTools);
  });
});

describe("Layer-3 scheduled opportunity boundary", () => {
  it("freezes each authoritative empty set and skips every model invocation", async () => {
    const input = state();
    input.trace_id = "graph:1";
    const agents = [...AGENTS_BY_LAYER.superinvestor];
    input.darwinian_runtime_binding = {} as DailyCycleStateType["darwinian_runtime_binding"];
    input.accepted_output_refs = {
      "RELATIONSHIP_GRAPH:relationship_mapper": {
        accepted_output_kind: "RELATIONSHIP_GRAPH",
        agent_id: "relationship_mapper",
        accepted_output_id: "accepted:relationship_mapper",
        accepted_output_hash: `sha256:${"a".repeat(64)}`,
      },
    };
    input.outcome_schedule_plan = {
      outcome_schedule_plan_id: "plan:1",
      outcome_schedule_plan_hash: `sha256:${"b".repeat(64)}`,
      schema_version: "outcome_schedule_plan_v2",
      graph_run_id: "graph:1",
      production_variant_roster_id: "roster:1",
      production_variant_roster_revision_id: "revision:1",
      execution_behavior_release_id: "release:1",
      cohort_id: "cohort_default",
      language: "zh",
      as_of: "2026-07-16T15:00:00+08:00",
      prepared_at: "2026-07-16T15:00:00+08:00",
      slots: agents.map((agentId, index) => ({
        schema_version: "outcome_schedule_slot_v2",
        outcome_schedule_slot_id: `slot:${agentId}`,
        outcome_schedule_slot_hash: `sha256:${(index + 1).toString(16).padStart(64, "0")}`,
        outcome_schedule_plan_id: "plan:1",
        graph_run_id: "graph:1",
        agent_id: agentId,
        track_key_hash: `sha256:${(index + 10).toString(16).padStart(64, "0")}`,
        run_slot_id: `run-slot:${agentId}`,
        run_slot_kind: "OUTCOME_SCHEDULED" as const,
        scheduled_sample_id: `sample:${agentId}`,
      })),
    };
    const freezeCalls: string[] = [];
    const api = {
      darwinianFreezeSuperinvestorOutcomeOpportunity: async (params: {
        agent_id: (typeof agents)[number];
        scheduled_sample_id: string;
      }) => {
        freezeCalls.push(params.agent_id);
        const slot = input.outcome_schedule_plan?.slots.find(
          (candidate) => candidate.agent_id === params.agent_id,
        );
        if (!slot) throw new Error("missing test slot");
        const universeHash = `sha256:${"c".repeat(64)}`;
        return {
          run_allowed: false,
          scheduled_sample_id: params.scheduled_sample_id,
          evaluation_opportunity_set_id: `opportunity:${params.agent_id}`,
          evaluation_opportunity_set_hash: `sha256:${"d".repeat(64)}`,
          frozen_object_set_id: `candidate-universe:${params.agent_id}`,
          frozen_object_set_hash: universeHash,
          runtime_candidate_scope_hash: `sha256:${"e".repeat(64)}`,
          runtime_candidate_universe_hash: universeHash,
          runtime_source_snapshot_hash: `sha256:${"6".repeat(64)}`,
          stage_skip: {
            stage_skip_id: `stage-skip:${params.agent_id}`,
            stage_skip_hash: `sha256:${"f".repeat(64)}`,
            schema_version: "no_evaluation_object_stage_skip_v2",
            graph_run_id: "graph:1",
            outcome_schedule_plan_id: "plan:1",
            outcome_schedule_slot_id: slot.outcome_schedule_slot_id,
            scheduled_sample_id: params.scheduled_sample_id,
            track_key_hash: slot.track_key_hash,
            agent_id: params.agent_id,
            skip_reason: "NO_EVALUATION_OBJECT",
            frozen_object_set_id: `candidate-universe:${params.agent_id}`,
            frozen_object_set_hash: universeHash,
            member_count: 0,
            model_invoked: false,
            eligibility_audit_id: `audit:${params.agent_id}`,
            eligibility_audit_revision_id: `audit-revision:${params.agent_id}`,
            eligibility_audit_revision_hash: `sha256:${"1".repeat(64)}`,
            evidence_ids: [`evidence:${params.agent_id}`],
            causal_dedupe_key: `sha256:${"2".repeat(64)}`,
            recorded_at: "2026-07-16T15:00:00+08:00",
          },
        };
      },
    } as unknown as BridgeApi;
    let modelInvocations = 0;
    const deps = {
      api,
      config: {} as MosaicConfig,
      llmHandle: {
        provider: "fake",
        model: "fake",
        baseUrl: undefined,
        llm: {
          invoke: async () => {
            modelInvocations += 1;
            throw new Error("model must not be invoked for an empty authority");
          },
        } as unknown as LlmHandle["llm"],
      },
    };
    const graph = buildLayer3Graph(deps);

    const final = (await graph.invoke(input)) as DailyCycleStateType;
    expect(freezeCalls).toEqual(agents);
    expect(modelInvocations).toBe(0);
    expect(Object.keys(final.outcome_stage_skips).sort()).toEqual([...agents].sort());
    expect(Object.keys(final.outcome_opportunity_bindings).sort()).toEqual([...agents].sort());
    expect(await buildMungerNode(deps)(final)).toEqual({});
    expect(modelInvocations).toBe(0);
  });
});

import { ToolMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
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
import { fallbackMunger, mungerSpec, renderMunger } from "../src/agents/superinvestor/munger.js";
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

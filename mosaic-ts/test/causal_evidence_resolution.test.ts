import { describe, expect, it } from "vitest";
import {
  AcceptedAgentOutputStore,
  type AcceptedOutputBuildContext,
  acceptedOutputRefKey,
  buildAcceptedAgentOutputRecord,
} from "../src/agents/accepted_output.js";
import type { ClaimEvidenceGraph } from "../src/agents/evidence_contract.js";
import {
  buildCausalEvidenceResolutionSet,
  evidenceLineageEnvelope,
  modelVisibleCausalEvidenceResolutionSet,
} from "../src/agents/helpers/causal_evidence_resolution.js";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import { validateMacroInputs } from "../src/agents/macro/_input_gate.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import { emptyCurrentPositions, emptyLayer4, emptyPositionAudit } from "../src/agents/state.js";
import type { AcceptedMacroTransmission, MacroAgentId } from "../src/agents/types.js";
import { macroOutput } from "./helpers/macro.js";
import {
  EXECUTION_RELEASE_ID_FIXTURE,
  ROSTER_REVISION_ID_FIXTURE,
  runtimeBehaviorRunPinsFixture,
} from "./helpers/runtime_behavior.js";

const SHARED_FINGERPRINT = `sha256:${"a".repeat(64)}`;

function graph(agent: MacroAgentId, polarity: "positive" | "negative" | null): ClaimEvidenceGraph {
  const evidenceId = `evidence:${agent}`;
  const fingerprint =
    agent === "china" || agent === "us_economy"
      ? SHARED_FINGERPRINT
      : `sha256:${agent.charCodeAt(0).toString(16).padStart(2, "0").repeat(32)}`;
  return {
    schema_version: "evidence_claim_graph_v1",
    run_id: "causal-test",
    snapshot_hash: `sha256:${"b".repeat(64)}`,
    evidence_ledger: [
      {
        evidence_id: evidenceId,
        run_id: "causal-test",
        snapshot_hash: `sha256:${"b".repeat(64)}`,
        source_kind: "runtime_source",
        tool_or_source: "fixture",
        metric: "fixture_metric",
        value: 1,
        unit: "index",
        as_of: "2026-07-17",
        lookback: "1d",
        freshness: "current",
        fallback: false,
        source_fingerprint: fingerprint,
        direction: "neutral",
        privacy_class: "public_structured",
      },
    ],
    claims: [
      {
        claim_id: `${agent}-claim`,
        claim_kind: polarity === null ? "FACT" : "INTERPRETATION",
        statement: "fixture claim",
        structured_conclusion:
          polarity === null ? { observation: "reported" } : { direction: polarity },
        evidence_ids: [evidenceId],
        research_rule_refs: polarity === null ? [] : ["fixture-rule"],
      },
    ],
    recommendation_claim_refs: [],
  };
}

function macroOutputs(): Record<string, AcceptedMacroTransmission> {
  return Object.fromEntries(
    MACRO_AGENT_IDS.map((agent) => {
      const polarity = agent === "china" ? "positive" : agent === "us_economy" ? "negative" : null;
      return [agent, macroOutput(agent, { verified_claim_graph: graph(agent, polarity) })];
    }),
  );
}

function state(): DailyCycleStateType {
  const layer1Outputs = macroOutputs();
  return {
    messages: [],
    active_cohort: "cohort_default",
    as_of_date: "2026-07-17",
    mode: "backtest",
    trace_id: "causal-test",
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
    layer1_outputs: layer1Outputs,
    macro_input_gate: validateMacroInputs(layer1Outputs),
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

function productionAcceptedState(): {
  state: DailyCycleStateType;
  store: AcceptedAgentOutputStore;
} {
  const fixture = state();
  const store = new AcceptedAgentOutputStore();
  const accepted_output_refs = Object.fromEntries(
    MACRO_AGENT_IDS.map((agent) => {
      const claimGraph = graph(
        agent,
        agent === "china" ? "positive" : agent === "us_economy" ? "negative" : null,
      );
      const context: AcceptedOutputBuildContext = {
        graph_run_id: "causal-test",
        run_id: `agent-run:${agent}`,
        run_slot_id: `slot:${agent}`,
        operational_opportunity_audit_id: `operational:${agent}`,
        production_variant_roster_id: "roster:1",
        production_variant_roster_revision_id: ROSTER_REVISION_ID_FIXTURE,
        execution_behavior_release_id: EXECUTION_RELEASE_ID_FIXTURE,
        runtime_release_pins: runtimeBehaviorRunPinsFixture(),
        cohort_id: "cohort_default",
        language: "zh",
        track_key_hash: `sha256:${"1".repeat(64)}`,
        agent_contract_version: "macro-agent-v2",
        prompt_behavior_version: "prompt-v2",
        execution_behavior_version: "execution-v2",
        component_weight_contract_version: null,
        reliability_adapter_contract_version: null,
        confidence_semantics_contract_version: null,
        as_of: "2026-07-17",
        accepted_at: "2026-07-17T00:00:00+08:00",
        run_binding: {
          sample_origin: "PRODUCTION_ACTIVE",
          run_slot_kind: "OUTCOME_SCHEDULED",
          scheduled_sample_id: `sample:${agent}`,
        },
      };
      const record = buildAcceptedAgentOutputRecord({
        kind: "MACRO_TRANSMISSION",
        agentId: agent,
        payload: macroOutput(agent),
        evidenceBundleIds: [
          `evidence-bundle:${claimGraph.run_id}:${claimGraph.snapshot_hash.slice(7)}`,
        ],
        causalDedupeKeys: [
          ...new Set(claimGraph.evidence_ledger.map((entry) => entry.source_fingerprint)),
        ] as [string, ...string[]],
        claimGraph,
        sourceAgentOutputHash: `sha256:${"f".repeat(64)}`,
        context,
      });
      return [
        acceptedOutputRefKey("MACRO_TRANSMISSION", agent),
        store.put(record, claimGraph),
      ] as const;
    }),
  );
  return {
    store,
    state: {
      ...fixture,
      layer1_outputs: {},
      accepted_output_refs,
      darwinian_runtime_binding: {
        language: "zh",
        production_variant_roster_id: "roster:1",
        execution_behavior_release_id: EXECUTION_RELEASE_ID_FIXTURE,
      } as DailyCycleStateType["darwinian_runtime_binding"],
    },
  };
}

describe("causal evidence resolution", () => {
  it("counts a shared source fingerprint once while preserving conflicting interpretations", () => {
    const set = buildCausalEvidenceResolutionSet({
      state: state(),
      consumerAgentId: "technology",
      sourceLayers: ["MACRO"],
    });
    expect(set).not.toBeNull();
    const shared = set?.resolutions.find(
      (resolution) => resolution.causal_dedupe_key === SHARED_FINGERPRINT,
    );
    expect(shared).toMatchObject({
      independent_evidence_count: 1,
      contributing_agent_ids: ["china", "us_economy"],
      contributing_claim_refs: ["china-claim", "us_economy-claim"],
      interpretation_state: "CONFLICTING",
      cross_layer_confidence_reducer: "NONE",
    });
  });

  it("uses an explicit model-view DTO that cannot expose private evidence bundle ids", () => {
    const set = buildCausalEvidenceResolutionSet({
      state: state(),
      consumerAgentId: "technology",
      sourceLayers: ["MACRO"],
    });
    if (!set) throw new Error("fixture must produce a resolution set");
    const visible = modelVisibleCausalEvidenceResolutionSet(set);
    expect(JSON.stringify(visible)).not.toContain("evidence_bundle_ids");
    expect(
      visible.resolutions.every((resolution) => resolution.independent_evidence_count === 1),
    ).toBe(true);
  });

  it("derives lineage keys from source fingerprints rather than invocation-local evidence ids", () => {
    const output = macroOutputs().china;
    if (!output) throw new Error("china fixture missing");
    const envelope = evidenceLineageEnvelope(output);
    expect(envelope.causal_dedupe_keys).toEqual([SHARED_FINGERPRINT]);
    expect(envelope.causal_dedupe_keys).not.toContain("evidence:china");
  });

  it("resolves formal causal lineage from accepted records when raw graph outputs are absent", () => {
    const fixture = productionAcceptedState();
    const set = buildCausalEvidenceResolutionSet({
      state: fixture.state,
      consumerAgentId: "technology",
      sourceLayers: ["MACRO"],
      acceptedOutputStore: fixture.store,
    });
    const shared = set?.resolutions.find(
      (resolution) => resolution.causal_dedupe_key === SHARED_FINGERPRINT,
    );
    expect(shared).toMatchObject({
      independent_evidence_count: 1,
      contributing_agent_ids: ["china", "us_economy"],
      contributing_claim_refs: ["china-claim", "us_economy-claim"],
      interpretation_state: "CONFLICTING",
    });
    expect(fixture.state.layer1_outputs).toEqual({});
  });
});

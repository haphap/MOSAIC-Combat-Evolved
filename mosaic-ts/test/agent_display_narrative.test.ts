import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  AcceptedAgentOutputStore,
  type AcceptedOutputKind,
  type AcceptedOutputRecordRef,
  acceptedOutputRefKey,
  buildAcceptedAgentOutputRecord,
} from "../src/agents/accepted_output.js";
import {
  buildAgentDisplayNarrativeBundle,
  formatAgentDisplayPercent,
  truncateAgentDisplayText,
} from "../src/agents/agent_display_narrative.js";
import type { ClaimEvidenceGraph } from "../src/agents/evidence_contract.js";
import { AGENTS_BY_LAYER, ALL_AGENTS, LAYER_BY_AGENT } from "../src/agents/prompts/cohorts.js";

function acceptedKind(agent: string): AcceptedOutputKind {
  if (AGENTS_BY_LAYER.macro.includes(agent as never)) return "MACRO_TRANSMISSION";
  if (agent === "relationship_mapper") return "RELATIONSHIP_GRAPH";
  if (AGENTS_BY_LAYER.sector.includes(agent as never)) return "STANDARD_SECTOR_SELECTION";
  if (AGENTS_BY_LAYER.superinvestor.includes(agent as never)) return "SUPERINVESTOR_SELECTION";
  if (agent === "cro") return "CRO_RISK_REVIEW";
  if (agent === "alpha_discovery") return "ALPHA_DISCOVERY";
  if (agent === "autonomous_execution") return "EXECUTION_ASSESSMENT";
  return "CIO_FINAL";
}

function stateFixture() {
  const layer1_outputs = Object.fromEntries(
    AGENTS_BY_LAYER.macro.map((agent) => [
      agent,
      {
        agent_id: agent,
        direction: "SUPPORTIVE",
        strength: 4,
        persistence_horizon: "WEEKS",
        confidence: 0.8,
        channels: ["A股流动性"],
        key_drivers: ["数据改善"],
        claims: [{ statement: `${agent} evidence` }],
        declared_knob_influence_ids: ["hidden_research_knob"],
        declared_influence_rationale: "HIDDEN_RESEARCH_KNOB_RATIONALE",
      },
    ]),
  );
  const layer2_outputs = Object.fromEntries(
    AGENTS_BY_LAYER.sector.map((agent) => [
      agent,
      agent === "relationship_mapper"
        ? {
            agent,
            predictive_graph_status: "EDGES_PRESENT",
            factual_edges: [{}],
            predictive_edges: [{}, {}],
            key_drivers: [{ summary: "供应链关系" }],
            risks: [{ summary: "映射失效" }],
            claims: [{ statement: "关系证据" }],
          }
        : {
            agent,
            preferred_direction: { direction_id: `${agent}_preferred` },
            least_preferred_direction: { direction_id: `${agent}_avoid` },
            persistence_horizon: "MONTHS",
            confidence: 0.75,
            key_drivers: [{ summary: "盈利趋势" }],
            risks: [{ summary: "估值风险" }],
            long_picks: [
              { ts_code: "600000.SH", position_action: "LONG", conviction: 0.7, thesis: "龙头" },
            ],
            short_or_avoid_picks: [],
            claims: [{ statement: "行业证据" }],
          },
    ]),
  );
  const layer3_outputs = Object.fromEntries(
    AGENTS_BY_LAYER.superinvestor.map((agent) => [
      agent,
      {
        agent,
        selection_status: "SELECTED",
        holding_period: "YEARS",
        confidence: 0.7,
        key_drivers: [{ summary: "哲学匹配" }],
        risks: [{ summary: "兑现较慢" }],
        picks: [
          { ts_code: "600519.SH", position_action: "LONG", conviction: 0.8, thesis: "护城河" },
        ],
        claims: [{ statement: "公司证据" }],
      },
    ]),
  );
  const layer4_outputs = {
    cro: {
      review_disposition: "REVIEW_ACTIONS",
      rejected_picks: [{ ticker: "000001.SZ", reason: "风险过高" }],
      correlated_risks: ["拥挤"],
      black_swan_scenarios: ["流动性骤降"],
      confidence: 0.9,
    },
    alpha_discovery: {
      discovery_disposition: "CANDIDATES",
      novel_picks: [{ ticker: "000002.SZ", why_missed_by_others: "预期差" }],
      confidence: 0.65,
    },
    autonomous_execution: {
      execution_disposition: "TRADES",
      trades: [{ ticker: "600000.SH", action: "BUY", size_pct: 0.1 }],
      execution_checks: [{ ticker: "600000.SH", reason: "流动性足够" }],
      confidence: 0.85,
    },
    cio: {
      decision_disposition: "TARGET_PORTFOLIO",
      decision_reason: "风险收益占优",
      portfolio_actions: [
        {
          ticker: "600000.SH",
          action: "BUY",
          target_weight: 0.1,
          position_decision_reason: "综合信号一致",
        },
      ],
      confidence: 0.8,
    },
  };
  return {
    trace_id: "trace-1",
    active_cohort: "cohort_default",
    as_of_date: "2026-07-18",
    darwinian_runtime_binding: {},
    outcome_schedule_plan: { language: "zh", as_of: "2026-07-18T15:00:00+08:00" },
    outcome_stage_skips: {},
    accepted_output_refs: {} as Record<string, AcceptedOutputRecordRef>,
    layer1_outputs,
    layer2_outputs,
    layer3_outputs,
    layer4_outputs,
  };
}

function outputForFixture(state: ReturnType<typeof stateFixture>, agent: string): unknown {
  const layer = LAYER_BY_AGENT[agent];
  if (layer === "macro") return state.layer1_outputs[agent];
  if (layer === "sector") return state.layer2_outputs[agent];
  if (layer === "superinvestor") return state.layer3_outputs[agent];
  return state.layer4_outputs[agent as keyof typeof state.layer4_outputs];
}

function acceptedPayloadForFixture(
  state: ReturnType<typeof stateFixture>,
  agent: string,
  kind: AcceptedOutputKind,
): Record<string, unknown> {
  const raw = outputForFixture(state, agent) as Record<string, unknown>;
  const behavior = {
    agent_contract_version: "contract-v1",
    prompt_behavior_version: "prompt-v1",
    execution_behavior_version: "execution-v1",
  };
  if (kind === "MACRO_TRANSMISSION") {
    return {
      agent_id: agent,
      ...behavior,
      component_weight_contract_version: "component-v1",
      direction: raw.direction,
      strength: raw.strength,
      persistence_horizon: raw.persistence_horizon,
      evaluation_horizon_trading_days: 5,
      model_confidence: raw.confidence,
      deterministic_data_quality: 1,
      confidence: raw.confidence,
      channels: raw.channels,
      key_drivers: raw.key_drivers,
      claims: raw.claims,
      claim_refs: [],
    };
  }
  if (kind === "RELATIONSHIP_GRAPH") {
    return {
      relationship_agent_id: "relationship_mapper",
      ...behavior,
      opportunity_set_id: "relationship-opportunities-1",
      opportunity_set_hash: `sha256:${"1".repeat(64)}`,
      factual_edges: [
        {
          edge_id: "factual-edge-1",
          edge_hash: `sha256:${"2".repeat(64)}`,
          source_entity: "原油",
          target_entity: "化工",
          edge_type: "SUPPLY_CHAIN",
          claim_refs: [],
        },
      ],
      predictive_edges: [
        {
          edge_id: "predictive-edge-1",
          edge_hash: `sha256:${"3".repeat(64)}`,
          edge_candidate_id: "candidate-1",
          source_entity: "原油",
          target_entity: "化工",
          edge_type: "INPUT_COST",
          transmission_direction: "NEGATIVE",
          activation_trigger: "油价突破阈值",
          evaluation_horizon_trading_days: 20,
          model_confidence: 0.7,
          calibrated_confidence: 0.65,
          calibration_state_id: "calibration-1",
          calibration_state_effective_at: state.outcome_schedule_plan.as_of,
          claim_refs: [],
        },
      ],
      predictive_graph_status: "EDGES_PRESENT",
      predictive_graph_abstention_confidence: null,
      key_drivers: raw.key_drivers,
      risks: raw.risks,
      claims: raw.claims,
      claim_refs: [],
      accepted_macro_input_attributions: [],
      directional_confidence: 0.65,
    };
  }
  if (kind === "STANDARD_SECTOR_SELECTION") {
    return {
      sector_agent_id: agent,
      ...behavior,
      sector_direction_registry_version: "sector-direction-registry-v1",
      sector_direction_registry_hash: `sha256:${"4".repeat(64)}`,
      selection: {
        selection_status: "SELECTED",
        preferred_direction: raw.preferred_direction,
        least_preferred_direction: raw.least_preferred_direction,
        persistence_horizon: raw.persistence_horizon,
        key_drivers: raw.key_drivers,
        risks: raw.risks,
        claims: raw.claims,
        claim_refs: [],
        preferred_security_status: "PICKS_PRESENT",
        long_picks: raw.long_picks,
        least_preferred_security_status: "NO_QUALIFIED_SECURITY",
        short_or_avoid_picks: raw.short_or_avoid_picks,
      },
      accepted_macro_input_attributions: [],
      direction_comparison_audit_id: "direction-audit-1",
      direction_comparison_audit_hash: `sha256:${"5".repeat(64)}`,
      preferred_security_shortlist_id: "preferred-shortlist-1",
      preferred_security_shortlist_hash: `sha256:${"6".repeat(64)}`,
      least_preferred_security_shortlist_id: "least-shortlist-1",
      least_preferred_security_shortlist_hash: `sha256:${"7".repeat(64)}`,
      security_scoring_contract_version: "security-scoring-v1",
      security_scoring_contract_hash: `sha256:${"8".repeat(64)}`,
      inference_cost_audit_id: "inference-audit-1",
      inference_cost_audit_hash: `sha256:${"9".repeat(64)}`,
      preferred_security_abstention_confidence: null,
      least_preferred_security_abstention_confidence: 0.6,
      model_confidence: raw.confidence,
      directional_confidence: raw.confidence,
    };
  }
  if (kind === "SUPERINVESTOR_SELECTION") {
    return {
      superinvestor_agent_id: agent,
      ...behavior,
      selection: {
        selection_status: raw.selection_status,
        holding_period: raw.holding_period,
        picks: raw.picks,
        key_drivers: raw.key_drivers,
        risks: raw.risks,
        claims: raw.claims,
        claim_refs: [],
      },
      accepted_macro_input_attributions: [],
      model_confidence: raw.confidence,
      directional_confidence: raw.confidence,
      abstention_confidence: 0,
    };
  }
  if (kind === "CRO_RISK_REVIEW") {
    return {
      agent_id: "cro",
      ...behavior,
      accepted_cro_review_id: "cro-review-1",
      accepted_cro_review_hash: `sha256:${"a".repeat(64)}`,
      frozen_proposal_id: "proposal-1",
      frozen_proposal_hash: `sha256:${"b".repeat(64)}`,
      frozen_candidate_universe_id: "candidate-universe-1",
      frozen_candidate_universe_hash: `sha256:${"c".repeat(64)}`,
      review: {
        review_disposition: raw.review_disposition,
        candidate_actions: [
          {
            action_local_id: "risk-action-1",
            candidate_ref: "candidate-000001",
            ts_code: "000001.SZ",
            action: "VETO",
            predicted_risk_probability: 0.8,
            max_target_weight: null,
            reason: "风险过高",
            claim_refs: [],
            cro_action_ref: "cro-action-1",
            cro_action_hash: `sha256:${"d".repeat(64)}`,
          },
        ],
        correlated_risks: [{ risk_local_id: "risk-1", summary: "拥挤", claim_refs: [] }],
        black_swan_scenarios: [{ risk_local_id: "risk-2", summary: "流动性骤降", claim_refs: [] }],
        claims: [{ statement: "风险审查证据" }],
        claim_refs: [],
      },
      accepted_macro_input_attributions: [],
      model_confidence: raw.confidence,
    };
  }
  if (kind === "ALPHA_DISCOVERY") {
    return {
      agent_id: "alpha_discovery",
      ...behavior,
      accepted_alpha_discovery_id: "alpha-1",
      accepted_alpha_discovery_hash: `sha256:${"e".repeat(64)}`,
      frozen_novel_candidate_universe_id: "alpha-universe-1",
      frozen_novel_candidate_universe_hash: `sha256:${"f".repeat(64)}`,
      selection: {
        discovery_disposition: raw.discovery_disposition,
        novel_picks: [
          {
            pick_local_id: "alpha-pick-1",
            candidate_ref: "candidate-000002",
            ts_code: "000002.SZ",
            conviction: 0.7,
            thesis: "预期差",
            claim_refs: [],
          },
        ],
        key_drivers: [],
        risks: [],
        claims: [{ statement: "Alpha 证据" }],
        claim_refs: [],
      },
      accepted_macro_input_attributions: [],
      model_confidence: raw.confidence,
    };
  }
  if (kind === "EXECUTION_ASSESSMENT") {
    return {
      agent_id: "autonomous_execution",
      ...behavior,
      accepted_execution_assessment_id: "execution-1",
      accepted_execution_assessment_hash: `sha256:${"0".repeat(64)}`,
      execution_mode: "PAPER",
      frozen_proposal_id: "proposal-1",
      frozen_proposal_hash: `sha256:${"1".repeat(64)}`,
      cro_control_source: {},
      frozen_order_intent_set_id: "orders-1",
      frozen_order_intent_set_hash: `sha256:${"2".repeat(64)}`,
      assessment: {
        execution_disposition: "ORDERS_ASSESSED",
        order_assessments: [
          {
            assessment_local_id: "assessment-1",
            order_intent_ref: "order-1",
            ts_code: "600000.SH",
            requested_delta_weight: 0.1,
            feasibility: "FEASIBLE",
            feasibility_confidence: 0.9,
            predicted_cost_bps: 8,
            max_executable_delta_weight: 0.1,
            recommended_slice_count: 2,
            reason: "流动性足够",
            claim_refs: [],
            execution_assessment_ref: "execution-assessment-1",
            execution_assessment_hash: `sha256:${"3".repeat(64)}`,
          },
        ],
        claims: [{ statement: "执行证据" }],
        claim_refs: [],
      },
      model_confidence: raw.confidence,
    };
  }
  return {
    agent_id: "cio",
    decision_stage: kind === "CIO_PROPOSAL" ? "PROPOSAL" : "FINAL",
    ...behavior,
    frozen_proposal_id: "proposal-1",
    frozen_proposal_hash: `sha256:${"4".repeat(64)}`,
    cro_control_source: {},
    execution_control_source: {},
    final_portfolio_id: "portfolio-1",
    final_portfolio_hash: `sha256:${"5".repeat(64)}`,
    decision: {
      decision_disposition: raw.decision_disposition,
      cash_weight: 0.9,
      decision_reason: raw.decision_reason,
      target_positions: [
        {
          position_local_id: "position-1",
          ts_code: "600000.SH",
          target_weight: 0.1,
          position_decision: "ADD",
          holding_period: "WEEKS",
          thesis_status: "INTACT",
          risk_flags: [],
          claim_refs: [],
        },
      ],
      claims: [{ statement: "组合证据" }],
      claim_refs: [],
    },
    cro_control_resolutions: [],
    execution_control_resolutions: [],
    accepted_macro_input_attributions: [],
    model_confidence: raw.confidence,
  };
}

function bindAcceptedRecords(state: ReturnType<typeof stateFixture>): AcceptedAgentOutputStore {
  const store = new AcceptedAgentOutputStore();
  const refs: Record<string, AcceptedOutputRecordRef> = {};
  const add = (kind: AcceptedOutputKind, agent: string, payload: unknown) => {
    const snapshotHash = `sha256:${"b".repeat(64)}`;
    const claimGraph: ClaimEvidenceGraph = {
      schema_version: "evidence_claim_graph_v1",
      run_id: state.trace_id,
      snapshot_hash: snapshotHash,
      evidence_ledger: [
        {
          evidence_id: `evidence:${agent}:${kind}`,
          run_id: state.trace_id,
          snapshot_hash: snapshotHash,
          source_kind: "tool",
          tool_or_source: "fixture",
          metric: "fixture",
          value: 1,
          unit: "index",
          as_of: state.as_of_date,
          lookback: "current",
          freshness: "current",
          fallback: false,
          source_fingerprint: `sha256:${"c".repeat(64)}`,
          direction: "neutral",
          privacy_class: "public_structured",
        },
      ],
      claims: [
        {
          claim_id: `claim:${agent}:${kind}`,
          claim_kind: "FACT",
          statement: "Fixture claim.",
          structured_conclusion: { value: 1 },
          evidence_ids: [`evidence:${agent}:${kind}`],
          research_rule_refs: [],
        },
      ],
      recommendation_claim_refs: [],
    };
    const record = buildAcceptedAgentOutputRecord({
      kind: kind as never,
      agentId: agent as never,
      payload,
      evidenceBundleIds: [`evidence-bundle:${agent}:${kind}`],
      causalDedupeKeys: [`dedupe:${agent}:${kind}`],
      claimGraph,
      sourceAgentOutputHash: `sha256:${"d".repeat(64)}`,
      context: {
        graph_run_id: state.trace_id,
        run_id: `run:${agent}:${kind}`,
        run_slot_id: `slot:${agent}:${kind}`,
        operational_opportunity_audit_id: `opportunity:${agent}:${kind}`,
        production_variant_roster_id: "roster-1",
        production_variant_roster_revision_id: "roster-revision-1",
        execution_behavior_release_id: "execution-release-1",
        cohort_id: state.active_cohort,
        language: "zh",
        track_key_hash: `track:${agent}:${kind}`,
        agent_contract_version: "contract-v1",
        prompt_behavior_version: "prompt-v1",
        execution_behavior_version: "execution-v1",
        component_weight_contract_version: null,
        reliability_adapter_contract_version: null,
        confidence_semantics_contract_version: null,
        as_of: state.outcome_schedule_plan.as_of,
        accepted_at: "2026-07-18T00:00:00Z",
        run_binding: {
          sample_origin: "PRODUCTION_ACTIVE",
          run_slot_kind: "DOWNSTREAM_ONLY",
          scheduled_sample_id: null,
        },
      },
    });
    const ref = store.put(record);
    refs[acceptedOutputRefKey(kind as never, agent as never)] = ref;
  };
  for (const agent of ALL_AGENTS) {
    const kind = acceptedKind(agent);
    add(kind, agent, acceptedPayloadForFixture(state, agent, kind));
  }
  add("CIO_PROPOSAL", "cio", acceptedPayloadForFixture(state, "cio", "CIO_PROPOSAL"));
  state.accepted_output_refs = refs;
  return store;
}

function clearStateOutputs(state: ReturnType<typeof stateFixture>): void {
  state.layer1_outputs = {};
  state.layer2_outputs = {};
  state.layer3_outputs = {};
  state.layer4_outputs = {
    cro: null,
    alpha_discovery: null,
    autonomous_execution: null,
    cio: null,
  } as never;
}

describe("Agent display narratives", () => {
  it("matches the cross-runtime percentage and Unicode truncation contract", () => {
    const fixture = JSON.parse(
      readFileSync(
        resolve(process.cwd(), "..", "tests", "fixtures", "agent_display_cross_runtime_cases.json"),
        "utf8",
      ),
    ) as {
      percent_cases: Array<{ value: number; expected: string }>;
      unicode_truncation_cases: Array<{
        unit: string;
        repeat: number;
        maximum: number;
        kept: number;
      }>;
    };
    for (const testCase of fixture.percent_cases) {
      expect(formatAgentDisplayPercent(testCase.value)).toBe(testCase.expected);
    }
    for (const testCase of fixture.unicode_truncation_cases) {
      const rendered = truncateAgentDisplayText(
        testCase.unit.repeat(testCase.repeat),
        testCase.maximum,
      );
      expect(rendered).toBe(`${testCase.unit.repeat(testCase.kept)}…`);
      expect([...rendered]).toHaveLength(testCase.maximum);
    }
  });

  it("deterministically renders all 28 Agents from accepted structured outputs", () => {
    const state = stateFixture();
    const store = bindAcceptedRecords(state);
    clearStateOutputs(state);
    const before = structuredClone(state);

    const first = buildAgentDisplayNarrativeBundle(state as never, store);
    const second = buildAgentDisplayNarrativeBundle(state as never, store);

    expect(first).toEqual(second);
    expect(first.narrative_count).toBe(28);
    expect(first.narratives.map((row) => row.agent_id)).toEqual(ALL_AGENTS);
    expect(first.narratives.every((row) => row.ui_only)).toBe(true);
    expect(first.narratives.every((row) => row.source === "ACCEPTED_OUTPUT")).toBe(true);
    expect(first.narratives.find((row) => row.agent_id === "china")?.narrative_text).toContain(
      "数据改善",
    );
    expect(
      first.narratives.find((row) => row.agent_id === "relationship_mapper")?.narrative_text,
    ).toContain("原油 → 化工");
    expect(first.narratives.find((row) => row.agent_id === "agriculture")?.narrative_text).toMatch(
      /agriculture_preferred.*600000\.SH/s,
    );
    expect(first.narratives.find((row) => row.agent_id === "munger")?.narrative_text).toContain(
      "600519.SH",
    );
    expect(first.narratives.find((row) => row.agent_id === "cro")?.narrative_text).toMatch(
      /000001\.SZ.*VETO.*风险过高/s,
    );
    expect(
      first.narratives.find((row) => row.agent_id === "alpha_discovery")?.narrative_text,
    ).toMatch(/000002\.SZ.*预期差/s);
    expect(
      first.narratives.find((row) => row.agent_id === "autonomous_execution")?.narrative_text,
    ).toMatch(/600000\.SH.*FEASIBLE.*8bps/s);
    expect(first.narratives.find((row) => row.agent_id === "cio")?.narrative_text).toMatch(
      /600000\.SH.*ADD.*10%/s,
    );
    expect(first.narratives.find((row) => row.agent_id === "cio")?.source_output_id).toBe(
      state.accepted_output_refs["CIO_FINAL:cio"]?.accepted_output_id,
    );
    expect(JSON.stringify(first)).not.toContain("HIDDEN_RESEARCH_KNOB");
    expect(JSON.stringify(first)).not.toContain("hidden_research_knob");
    expect(state).toEqual(before);
    expect(JSON.stringify(state)).not.toContain("narrative_text");
  });

  it("fails closed when a production Agent lacks accepted-output lineage", () => {
    const state = stateFixture();
    const store = bindAcceptedRecords(state);
    delete state.accepted_output_refs["MACRO_TRANSMISSION:china"];
    expect(() => buildAgentDisplayNarrativeBundle(state as never, store)).toThrow(
      "china: production display narrative lacks accepted-output lineage",
    );
  });

  it("fails closed when the production accepted-output record is unavailable", () => {
    const state = stateFixture();
    bindAcceptedRecords(state);
    clearStateOutputs(state);
    expect(() =>
      buildAgentDisplayNarrativeBundle(state as never, new AcceptedAgentOutputStore()),
    ).toThrow("accepted output is unavailable");
  });

  it("fails closed when an accepted-output reference is forged", () => {
    const state = stateFixture();
    const store = bindAcceptedRecords(state);
    const chinaRef = state.accepted_output_refs["MACRO_TRANSMISSION:china"];
    if (!chinaRef) throw new Error("test fixture lacks china accepted-output ref");
    chinaRef.accepted_output_hash = `sha256:${"f".repeat(64)}`;
    expect(() => buildAgentDisplayNarrativeBundle(state as never, store)).toThrow(
      "accepted output reference mismatch",
    );
  });

  it("labels a deterministic no-object skip without treating it as neutral", () => {
    const state = stateFixture();
    const store = bindAcceptedRecords(state);
    delete state.accepted_output_refs["SUPERINVESTOR_SELECTION:druckenmiller"];
    delete state.layer3_outputs.druckenmiller;
    state.outcome_stage_skips = {
      druckenmiller: { stage_skip_hash: `sha256:${"c".repeat(64)}` },
    };

    const bundle = buildAgentDisplayNarrativeBundle(state as never, store);
    const row = bundle.narratives.find((item) => item.agent_id === "druckenmiller");
    expect(row?.source).toBe("NO_EVALUATION_OBJECT");
    expect(row?.narrative_text).toContain("不是中性判断");
  });

  it("keeps canonical layer ownership in every UI record", () => {
    const state = stateFixture();
    const store = bindAcceptedRecords(state);
    const bundle = buildAgentDisplayNarrativeBundle(state as never, store);
    expect(bundle.narratives.every((row) => row.layer === LAYER_BY_AGENT[row.agent_id])).toBe(true);
  });
});

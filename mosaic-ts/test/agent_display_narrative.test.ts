import { describe, expect, it } from "vitest";
import { buildAgentDisplayNarrativeBundle } from "../src/agents/agent_display_narrative.js";
import { AGENTS_BY_LAYER, ALL_AGENTS, LAYER_BY_AGENT } from "../src/agents/prompts/cohorts.js";

const HASH = `sha256:${"a".repeat(64)}`;

function acceptedKind(agent: string): string {
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
  const accepted_output_refs = Object.fromEntries(
    ALL_AGENTS.map((agent) => [
      `${acceptedKind(agent)}:${agent}`,
      {
        accepted_output_kind: acceptedKind(agent),
        agent_id: agent,
        accepted_output_id: `accepted:${agent}`,
        accepted_output_hash: HASH,
      },
    ]),
  );
  accepted_output_refs["CIO_PROPOSAL:cio"] = {
    accepted_output_kind: "CIO_PROPOSAL",
    agent_id: "cio",
    accepted_output_id: "accepted:cio:proposal",
    accepted_output_hash: `sha256:${"b".repeat(64)}`,
  };
  return {
    trace_id: "trace-1",
    active_cohort: "cohort_default",
    as_of_date: "2026-07-18",
    darwinian_runtime_binding: {},
    outcome_schedule_plan: { language: "zh" },
    outcome_stage_skips: {},
    accepted_output_refs,
    layer1_outputs,
    layer2_outputs,
    layer3_outputs,
    layer4_outputs,
  };
}

describe("Agent display narratives", () => {
  it("deterministically renders all 28 Agents from accepted structured outputs", () => {
    const state = stateFixture();
    const before = structuredClone(state);

    const first = buildAgentDisplayNarrativeBundle(state as never);
    const second = buildAgentDisplayNarrativeBundle(state as never);

    expect(first).toEqual(second);
    expect(first.narrative_count).toBe(28);
    expect(first.narratives.map((row) => row.agent_id)).toEqual(ALL_AGENTS);
    expect(first.narratives.every((row) => row.ui_only)).toBe(true);
    expect(first.narratives.every((row) => row.source === "ACCEPTED_OUTPUT")).toBe(true);
    expect(first.narratives.find((row) => row.agent_id === "china")?.narrative_text).toContain(
      "数据改善",
    );
    expect(first.narratives.find((row) => row.agent_id === "cio")?.source_output_id).toBe(
      "accepted:cio",
    );
    expect(JSON.stringify(first)).not.toContain("HIDDEN_RESEARCH_KNOB");
    expect(JSON.stringify(first)).not.toContain("hidden_research_knob");
    expect(state).toEqual(before);
    expect(JSON.stringify(state)).not.toContain("narrative_text");
  });

  it("fails closed when a production Agent lacks accepted-output lineage", () => {
    const state = stateFixture();
    delete state.accepted_output_refs["MACRO_TRANSMISSION:china"];
    expect(() => buildAgentDisplayNarrativeBundle(state as never)).toThrow(
      "china: production display narrative lacks accepted-output lineage",
    );
  });

  it("labels a deterministic no-object skip without treating it as neutral", () => {
    const state = stateFixture();
    delete state.accepted_output_refs["SUPERINVESTOR_SELECTION:druckenmiller"];
    delete state.layer3_outputs.druckenmiller;
    state.outcome_stage_skips = {
      druckenmiller: { stage_skip_hash: `sha256:${"c".repeat(64)}` },
    };

    const bundle = buildAgentDisplayNarrativeBundle(state as never);
    const row = bundle.narratives.find((item) => item.agent_id === "druckenmiller");
    expect(row?.source).toBe("NO_EVALUATION_OBJECT");
    expect(row?.narrative_text).toContain("不是中性判断");
  });

  it("keeps canonical layer ownership in every UI record", () => {
    const bundle = buildAgentDisplayNarrativeBundle(stateFixture() as never);
    expect(bundle.narratives.every((row) => row.layer === LAYER_BY_AGENT[row.agent_id])).toBe(true);
  });
});
